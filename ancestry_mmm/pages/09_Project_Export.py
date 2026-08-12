"""Page 9: project export/import bundle (Parquet + JSON + NetCDF) and Excel export for portability and recovery.

Phase 7 of the Streamlit UI/UX overhaul (docs/decision_log.md) applies the
shared shell (SectionCard/InfoPanel, page-header badges, a "Project status"
summary) to this page - the last one not yet migrated. Presentation only:
every value shown is read from existing session-state getters or from the
bundle's own manifest.json ("contains" dict, written by
core.persistence.export_project - never recomputed here), never invented or
duplicated. No change to core.persistence or application.project_service
logic.
"""

import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    PROJECT_EXPORT_ROOT,
    curve_artifact_store_dir,
    curve_bank_dir,
    get_state,
    get_workflow_progress,
    init_session_state,
    set_state,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_drift_status,
    page_readiness,
    SectionCard,
    InfoPanel,
)
from ancestry_mmm.core.persistence import (
    export_project,
    import_project,
    export_excel_summary,
    reconstruct_model_state,
    replace_curve_artifact_store,
    resolve_imported_outcome_approvals,
    resolve_imported_causal_graphs,
    resolve_imported_search_objects,
    resolve_imported_source_versions,
    resolve_imported_source_definitions,
    resolve_imported_variable_coverage_matrices,
    verify_imported_approval,
    UnsafeZipEntryError,
    audit_project_resumability,
)
from ancestry_mmm.application.project_service import verify_imported_readiness
from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact
from ancestry_mmm.application.curve_service import CurveService, CurveGovernanceError
from ancestry_mmm.core.validation_policy import (
    load_approval_readiness,
    load_threshold_policy,
)
from ancestry_mmm.core.curve_bank import load_all_entries, entries_to_dataframe
from ancestry_mmm.core.curve_artifact import (
    CurveArtifactError,
    governed_context_fields,
    load_curve_artifact_store,
)
from ancestry_mmm.core.activities import ActivityDefinition, activity_fit_fingerprint
from ancestry_mmm.core.attribution import (
    compute_shapley_contributions,
    total_fh_contribution,
    outcome_channel_summary,
)
from ancestry_mmm.core.market_specific_attribution import (
    compute_shapley_contributions_market_specific,
    total_contribution_market_specific,
    outcome_channel_market_summary,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.market_config import MarketSpecConfig
from ancestry_mmm.core.evidence_tiers import evidence_tiers_dataframe
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.causal_graph import (
    current_graph_from_resolved_versions,
    current_structural_fingerprint_for_identity,
    graph_versions_for_export,
)
from ancestry_mmm.core.search_objects import (
    SearchObjectDefinition,
    current_search_object_versions,
    search_object_fit_fingerprint,
    search_object_versions_for_export,
)
from ancestry_mmm.core.coverage import (
    VariableCoverageMatrix,
    current_variable_coverage_matrix_from_resolved_versions,
    variable_coverage_matrix_versions_for_export,
)
from ancestry_mmm.core.media_units import market_specific_cpa_table
from ancestry_mmm.core.outcome_approval import OutcomeApproval
from ancestry_mmm.core.outcomes import (
    fh_gsa_outcome_ids,
    outcome_catalogue_fingerprint_payload,
    resolve_outcome_definitions,
)
from ancestry_mmm.core.pathways import (
    MediaOutcomePathway,
    pathway_catalogue_fingerprint_payload,
    pathways_drift_dataframe,
)
from ancestry_mmm.core.optimization import compare_scenarios
from ancestry_mmm.core.report import build_report_sections, render_markdown, render_html
from ancestry_mmm.core.promotions import PROMOTION_EVENT_OP
from ancestry_mmm.data import apply_pipeline, pipeline_from_json

_CURVE_SERVICE = CurveService()

# Human-readable labels for core.persistence.export_project's manifest.json
# "contains" keys, purely presentational (label text only, no logic) - used
# to render an honest "what's actually in this bundle" checklist straight
# from the bundle's own manifest after a real build/import, rather than
# re-deriving a second, possibly-drifting notion of bundle contents here.
_CONTAINS_LABELS = {
    "raw_data": "Raw uploaded source data",
    "transformed_data": "Transformed / joined data",
    "model_spec": "Model structure (segments, markets, channels)",
    "posterior": "Fitted posterior trace",
    "diagnostics": "Diagnostics scorecard / backtest results",
    "curves": "Legacy curve bank entries",
    "official_curve_artifacts": "Official curve artifacts (REQ-CURVE-001)",
    "approval": "Model approval",
    "outcome_approvals": "Outcome approvals",
    "scenarios": "Saved scenarios",
    "notes": "Analyst notes",
    "validation_policy": "Validation / threshold policy",
    "diagnostics_artefact": "Diagnostics artefact evidence",
    "validation_results": "Validation results",
    "approval_readiness": "Approval readiness proof",
    "counterfactual_policy": "Counterfactual policy",
    "currency_context": "Currency context",
    "value_mapping": "Outcome value mapping",
    "causal_graphs": "Causal graph versions",
    "search_objects": "Search object versions",
    "source_versions": "Source upload version history",
    "source_definitions": "Source logical-domain definitions",
    "variable_coverage_matrices": "Variable coverage matrix versions",
    "join_config": "Join configuration",
}


def _render_contains_checklist(contains: dict) -> None:
    """Two-column included / not-included checklist rendered directly from
    a bundle's own manifest.json "contains" dict - presentation only, no
    new completeness logic."""
    included = [label for key, label in _CONTAINS_LABELS.items() if contains.get(key)]
    not_included = [
        label for key, label in _CONTAINS_LABELS.items() if not contains.get(key)
    ]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Included**")
        for label in included:
            st.caption(f"✓ {label}")
    with c2:
        st.markdown("**Not included**")
        for label in not_included:
            st.caption(f"– {label}")


def _resolve_official_curve_artifact_rows() -> list[dict]:
    """Load the official curve artifact store and resolve each artifact's
    current authorization status for headline reporting.

    Reuses the same shared resolution path as Results / Curve Bank's
    official artifact section (``CurveService.resolve_current_governance``
    + ``authorize_use``) so this page never reimplements governance
    resolution. A malformed artifact is its own row (never silently
    dropped, REQ-CURVE-001); an artifact whose current governance can't be
    resolved or isn't currently authorized is reported as ``"blocked"``
    with a ``reason``, never omitted.
    """
    store_dir = curve_artifact_store_dir()
    try:
        load_result = load_curve_artifact_store(store_dir, raise_on_malformed=False)
    except CurveArtifactError as exc:
        st.warning(f"Official curve artifact store could not be read: {exc}")
        return []

    rows: list[dict] = []
    for entry in load_result.malformed:
        rows.append(
            {
                "artifact_id": entry.artifact_dir.name,
                "created": None,
                "schema_version": None,
                "outcome": None,
                "reference_context_id": None,
                "format_status": entry.status,
                "historical_integrity": "unknown",
                "current_authorization": "blocked",
                "requested_use_eligibility": "n/a",
                "planning_support_eligible": "n/a",
                "reason": entry.error,
            }
        )
    if not load_result.loaded:
        return rows

    meta = get_state("model_meta")
    params = get_state("posterior_params")
    frame = get_state("frame")
    spec_dict = get_state("model_spec")
    model_type = get_state("model_type", "shared")
    activity_definitions = [
        ActivityDefinition.from_dict(item)
        for item in (get_state("activity_definitions") or [])
    ]
    search_objects = [
        SearchObjectDefinition.from_dict(item)
        for item in (get_state("search_objects") or [])
    ]
    coverage_matrix_dict = get_state("variable_coverage_matrix")
    model_run_id = get_state("model_run_id")
    prior_config = get_state("prior_config") or {}
    dna_lag_weeks = get_state("dna_lag_weeks", 4)

    current_identity = None
    if (
        model_run_id
        and spec_dict is not None
        and frame is not None
        and params is not None
    ):
        current_identity = {
            "model_run_id": model_run_id,
            "data_fingerprint": fingerprint_dataframe(frame["df"]),
            "model_spec_fingerprint": fingerprint_model_spec(
                spec_dict,
                prior_config,
                dna_lag_weeks,
                model_type=model_type,
                pipeline_steps=get_state("pipeline_steps") or [],
                market_spec_config=get_state("market_spec_config"),
                direct_dna_outcome_ids=meta.direct_dna_outcome_ids
                if meta is not None
                else None,
                outcome_catalogue=outcome_catalogue_fingerprint_payload(
                    meta.outcome_catalogue_at_fit
                )
                if meta is not None
                else None,
                funnel_links=get_state("funnel_links"),
                media_outcome_pathways=pathway_catalogue_fingerprint_payload(
                    meta.pathway_catalogue_at_fit
                )
                if meta is not None
                else None,
                activity_fit_fingerprint=(
                    activity_fit_fingerprint(activity_definitions)
                    if activity_definitions
                    else None
                ),
                causal_graph_structural_fingerprint=current_structural_fingerprint_for_identity(
                    fit_time_structural_fingerprint=(
                        getattr(meta, "causal_graph_structural_fingerprint", "") or ""
                    )
                    if meta is not None
                    else "",
                    live_graph_dict=get_state("causal_graph"),
                ),
                search_object_fit_fingerprint=(
                    search_object_fit_fingerprint(
                        search_objects,
                        consumed_model_input_columns=spec_dict.get("channels") or [],
                    )
                    if search_objects
                    else None
                ),
                variable_coverage_fingerprint=(
                    VariableCoverageMatrix.from_dict(coverage_matrix_dict).fingerprint()
                    if coverage_matrix_dict
                    else None
                ),
            ),
            "posterior_fingerprint": fingerprint_posterior(params),
        }

    approval_dict = get_state("model_approval")
    current_policy, _ = load_threshold_policy(get_state("validation_policy"))
    current_readiness, _ = load_approval_readiness(get_state("approval_readiness"))
    current_diagnostics_artefact = get_state("diagnostics_artefact")
    spec = ModelSpec.from_dict(spec_dict) if spec_dict else None
    outcome_definitions = (
        resolve_outcome_definitions(
            get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv
        )
        if spec is not None
        else []
    )
    outcome_approvals = [
        OutcomeApproval.from_dict(d) for d in (get_state("outcome_approvals") or [])
    ]

    for artifact in load_result.loaded:
        md = artifact.metadata
        base_row = {
            "artifact_id": md.artifact_id,
            "created": md.creation_timestamp,
            "schema_version": md.schema_version,
            "outcome": (md.outcome_definition_snapshot or {}).get("outcome_id"),
            "reference_context_id": (md.reference_context_snapshot or {}).get(
                "reference_context_id"
            ),
            "format_status": md.format_status,
            "historical_integrity": md.historical_integrity,
            # Corrective PR D4/D7: the governed context REQ-CURVE-001
            # requires alongside an exported official curve row, beyond
            # bare artifact_id/outcome_id - already captured in the
            # artifact's own creation-time snapshots, just not previously
            # surfaced in this export/report row shape.
            **governed_context_fields(md),
        }
        governance = _CURVE_SERVICE.resolve_current_governance(
            artifact,
            current_identity=current_identity,
            approval_dict=approval_dict,
            current_policy=current_policy,
            current_readiness=current_readiness,
            current_diagnostics_artefact=current_diagnostics_artefact,
            activity_definitions=activity_definitions,
            outcome_definitions=outcome_definitions,
            outcome_approvals=outcome_approvals,
        )
        if governance is None:
            rows.append(
                {
                    **base_row,
                    "current_authorization": "blocked",
                    "requested_use_eligibility": "n/a",
                    "planning_support_eligible": "n/a",
                    "reason": (
                        "Current governance cannot be resolved (missing current "
                        "model identity, model approval, or a matching current "
                        "outcome approval)."
                    ),
                }
            )
            continue
        try:
            authorization = _CURVE_SERVICE.authorize_use(
                artifact, "headline_reporting", current_governance=governance
            )
        except CurveGovernanceError as exc:
            rows.append(
                {
                    **base_row,
                    "current_authorization": "blocked",
                    "requested_use_eligibility": "n/a",
                    "planning_support_eligible": "n/a",
                    "reason": str(exc),
                }
            )
            continue
        planning_support = (
            bool(artifact.draws["planning_support_eligible"].all())
            if (
                not artifact.draws.empty
                and "planning_support_eligible" in artifact.draws.columns
            )
            else "n/a"
        )
        rows.append(
            {
                **base_row,
                "current_authorization": authorization.current_authorization_status,
                "requested_use_eligibility": authorization.requested_use_eligibility,
                "planning_support_eligible": planning_support,
                "reason": "" if authorization.authorized else authorization.reason,
            }
        )
    return rows


st.set_page_config(
    page_title="Project Export | Ancestry Family History & DNA MMM",
    page_icon="🧬",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("export")
render_page_header(
    "export",
    badges=[page_readiness("export")],
)
st.info(
    "**Streamlit session state is not durable storage.** It only drives in-session "
    "interactivity and is lost on refresh or a new browser session. This project bundle "
    "(Parquet + JSON + NetCDF, all open formats) is the actual system of record: pause here, "
    "resume later, share with another analyst, or replay the same pipeline on refreshed "
    "weekly data. The Excel summary and project report further down this page are one-way, "
    "read-only exports for sharing and analysis - only the bundle round-trips back into a "
    "working, resumable project."
)

# One read of the curve bank / official curve artifact store per page render,
# reused by the "Project status" summary below and by the Excel/report
# builders further down this page - previously read up to three times per
# render (once per consumer) for the exact same on-disk state. Read-only,
# same functions/paths already used unconditionally elsewhere on this page.
_curve_bank_entries = load_all_entries(curve_bank_dir())
_official_curve_artifact_rows = _resolve_official_curve_artifact_rows()
_authorized_artifact_count = sum(
    1
    for row in _official_curve_artifact_rows
    if row.get("current_authorization") == "authorized"
)

_last_bundle_build = get_state("export_last_bundle_summary")
_last_bundle_import = get_state("export_last_import_summary")

with SectionCard(
    "Project status",
    description=(
        "What this project currently has, and what this browser session has done with the "
        "system-of-record bundle. Read from session state and the on-disk curve bank / "
        "official curve artifact store already used below - not a new signal."
    ),
):
    _status_col1, _status_col2 = st.columns(2)
    with _status_col1:
        st.markdown("**Current project (session state)**")
        st.caption(f"Project name: {get_state('project_name', 'ancestry-fh-uk')}")
        st.caption(
            f"Data sources loaded: {len(get_state('raw_sources') or {})} "
            f"(source versions recorded: {len(get_state('source_versions') or [])})"
        )
        st.caption(
            f"Transformation pipeline steps: {len(get_state('pipeline_steps') or [])}"
        )
        _model_run_id = get_state("model_run_id")
        st.caption(
            "Model: "
            + (f"run `{_model_run_id}`" if _model_run_id else "not yet trained")
            + (", approved" if get_state("model_approval") else ", not approved")
        )
        st.caption(
            f"Causal graph versions saved: {len(get_state('causal_graph_versions') or [])}"
        )
        st.caption(
            "Search object versions saved: "
            f"{len(get_state('search_object_versions') or [])}"
        )
        st.caption(
            "Coverage matrix versions saved: "
            f"{len(get_state('variable_coverage_matrix_versions') or [])}"
        )
        st.caption(f"Legacy curve bank entries: {len(_curve_bank_entries)}")
        st.caption(
            f"Official curve artifacts: {len(_official_curve_artifact_rows)} "
            f"({_authorized_artifact_count} currently authorized for headline reporting)"
            if _official_curve_artifact_rows
            else "Official curve artifacts: none generated yet"
        )
        st.caption(f"Saved scenarios: {len(get_state('scenarios') or [])}")
    with _status_col2:
        st.markdown("**This session's bundle activity**")
        if _last_bundle_build:
            st.caption(
                f"Last bundle built this session: `{_last_bundle_build['project_name']}` "
                f"at checkpoint '{_last_bundle_build['checkpoint']}', "
                f"{_last_bundle_build['built_at']} UTC."
            )
        else:
            st.caption("No bundle has been built yet this session.")
        if _last_bundle_import:
            st.caption(
                f"Last bundle imported this session: `{_last_bundle_import['bundle_name']}`"
                + (
                    ", officially resumable"
                    if _last_bundle_import.get("officially_resumable")
                    else ""
                )
                + f" at checkpoint '{_last_bundle_import.get('checkpoint')}', "
                f"{_last_bundle_import['imported_at']} UTC."
            )
        else:
            st.caption("No bundle has been imported yet this session.")
        st.caption(
            "This activity log is itself session-only - it resets on refresh or a new "
            "session, same as everything else on this page except the bundle file itself."
        )

st.markdown("---")
st.markdown("### Export project bundle")
st.caption(
    "The system of record. Produces a single portable .zip (Parquet + JSON + NetCDF, all "
    "open formats) that fully round-trips back into a working project via **Import project "
    "bundle** below."
)
project_name = get_state("project_name", "ancestry-fh-uk")
project_notes = st.text_area(
    "Analyst project notes",
    value=get_state("project_notes", ""),
    help="Saved in the resumable bundle as notes.md.",
)
set_state("project_notes", project_notes)
if st.button("Build export bundle", type="primary"):
    PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = PROJECT_EXPORT_ROOT / f"{project_name}.zip"
    # PR 88A: "diagnostics_artefact" in session state is always a
    # DiagnosticsArtefact domain object (or None) - see pages/06_Diagnostics.py
    # and reconstruct_model_state() below. This is the one explicit
    # conversion boundary to a JSON-safe dict for export; it must never be
    # handed to export_project()/json.dumps() as the raw object (that would
    # serialize through json.dumps's default=str fallback as an opaque
    # string, not structured JSON).
    _diagnostics_artefact_obj = get_state("diagnostics_artefact")
    _diagnostics_artefact_dict = (
        _diagnostics_artefact_obj.to_dict()
        if _diagnostics_artefact_obj is not None
        else None
    )
    with st.spinner("Building bundle..."):
        export_project(
            output_path,
            raw_sources=get_state("raw_sources") or {},
            transformed_data=get_state("transformed_data"),
            pipeline_steps=get_state("pipeline_steps") or [],
            model_spec=get_state("model_spec"),
            prior_config=get_state("prior_config"),
            dna_lag_weeks=get_state("dna_lag_weeks", 4),
            trace=get_state("trace"),
            scenarios=get_state("scenarios") or [],
            curve_bank_source_dir=curve_bank_dir(),
            curve_artifact_store_source_dir=curve_artifact_store_dir(),
            model_approval=get_state("model_approval"),
            model_run_id=get_state("model_run_id"),
            model_meta=get_state("model_meta"),
            market_spec_config=get_state("market_spec_config"),
            model_type=get_state("model_type", "shared"),
            outcome_definitions=get_state("outcome_definitions"),
            funnel_links=get_state("funnel_links"),
            media_outcome_pathways=get_state("media_outcome_pathways"),
            net_billthrough_metadata=get_state("net_billthrough_metadata"),
            workflow_state={
                "checkpoint": (
                    "scenarios"
                    if get_state("scenarios")
                    else "official_curves"
                    if load_curve_artifact_store(
                        curve_artifact_store_dir(), raise_on_malformed=False
                    ).loaded
                    else "curves"
                    if get_state("curve_bank_entry_id")
                    else "approved"
                    if get_state("model_approval")
                    else "fitted"
                    if get_state("trace") is not None
                    else "pre_fit"
                    if get_state("model_spec")
                    else "uploaded"
                ),
                "current_page": get_state("current_page", 0),
                "workflow_progress": get_workflow_progress(),
                "active_scenario": get_state("active_scenario"),
            },
            diagnostics={
                "scorecard": get_state("scorecard"),
                "backtest_results": get_state("backtest_results"),
            },
            notes=get_state("project_notes"),
            calibration_records=get_state("calibration_records") or [],
            model_comparison_candidates=get_state("model_comparison_candidates") or [],
            migration_review=get_state("migration_review"),
            media_input_specs=get_state("media_input_specs") or [],
            media_cost_mappings=get_state("media_cost_mappings"),
            media_input_support=get_state("media_input_support") or [],
            monetary_spend_support=get_state("monetary_spend_support") or [],
            activity_definitions=get_state("activity_definitions") or [],
            # G2A.7a (DEFECT-10): persist outcome approvals in the bundle
            outcome_approvals=get_state("outcome_approvals") or [],
            # PR 82D: persist the governance evidence chain established in
            # PR 82B (policy + diagnostics artefact + readiness proof) so a
            # re-imported project doesn't lose its official-mode evidence.
            validation_policy=get_state("validation_policy"),
            diagnostics_artefact=_diagnostics_artefact_dict,
            validation_results=get_state("validation_results"),
            approval_readiness=get_state("approval_readiness"),
            # PR 125A: the project-level planning dependencies every
            # official scenario's saved governance-dependency fingerprint
            # is verified against on import - see core.persistence's
            # module docstring.
            counterfactual_policy=get_state("counterfactual_policy"),
            currency_context=get_state("currency_context"),
            value_mapping=get_state("value_mapping"),
            # REQ-GRAPH-001 work package (graph portability): every saved
            # graph version plus the current live (possibly unsaved) graph -
            # see graph_versions_for_export's docstring.
            causal_graphs=graph_versions_for_export(
                current_graph_dict=get_state("causal_graph"),
                version_history=get_state("causal_graph_versions"),
            ),
            # REQ-SEARCH-001 S10: every saved Search object version plus the
            # current live records - see search_object_versions_for_export's
            # docstring (mirrors graph_versions_for_export above).
            search_objects=search_object_versions_for_export(
                current_definitions=get_state("search_objects") or [],
                version_history=get_state("search_object_versions"),
            ),
            # REQ-COVERAGE-001 S3: the full append-only immutable
            # SourceVersion history - never only the latest per source_id,
            # since it is a permanent upload record, not current-use state
            # (mirrors search_objects/causal_graphs above, which also
            # export their full version history, not just what's current).
            source_versions=get_state("source_versions") or [],
            # REQ-DATAIN-001: governed SourceDefinition records
            # (logical_domain per source_id) - mirrors source_versions
            # above.
            source_definitions=get_state("source_definitions") or [],
            # REQ-COVERAGE-001 S1: every saved coverage-matrix version plus
            # the current live (possibly unsaved) matrix - see
            # variable_coverage_matrix_versions_for_export's docstring
            # (mirrors search_objects/causal_graphs above).
            variable_coverage_matrices=variable_coverage_matrix_versions_for_export(
                current_matrix_dict=get_state("variable_coverage_matrix"),
                version_history=get_state("variable_coverage_matrix_versions"),
            ),
            # REQ-COVERAGE-001 S4 (Work Package 4): the join key columns,
            # mode and resulting diagnostics from the most recent "Join
            # sources" click, so a re-imported project doesn't silently
            # revert to the page's "inner" default on the analyst's next
            # visit. None (omitted from the bundle) until sources have
            # actually been joined.
            join_config=(
                {
                    "date_col": get_state("date_col"),
                    "market_col": get_state("market_col"),
                    "join_mode": get_state("join_mode"),
                    "join_diagnostics": get_state("join_diagnostics"),
                }
                if get_state("date_col")
                else None
            ),
        )
    st.success(f"Project bundle built: {output_path}")
    # Read back this bundle's own manifest.json (written by
    # core.persistence.export_project - see the module docstring) rather
    # than re-deriving a second "what's in it" notion here, so the
    # checklist below can never drift from what was actually written.
    with zipfile.ZipFile(output_path) as _build_zf:
        _build_manifest = json.loads(_build_zf.read("manifest.json"))
    set_state(
        "export_last_bundle_summary",
        {
            "project_name": project_name,
            "path": str(output_path),
            "checkpoint": _build_manifest.get("workflow_checkpoint"),
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    with st.expander("What's included in this bundle", expanded=False):
        _render_contains_checklist(_build_manifest.get("contains", {}))
    with open(output_path, "rb") as f:
        st.download_button(
            "Download project bundle (.zip)",
            f,
            file_name=f"{project_name}.zip",
            mime="application/zip",
        )

st.markdown("---")
st.markdown("### Import project bundle")
st.caption(
    "Restore a previously exported bundle to resume work - the same recovery path a "
    "different analyst, a new session, or a later date all use. Every restored artefact is "
    "re-verified against its own governance chain below (readiness, approval, fingerprints), "
    "never trusted blindly."
)
uploaded_zip = st.file_uploader("Upload a previously exported .zip", type=["zip"])
if uploaded_zip is not None and st.button("Import bundle"):
    tmp_path = PROJECT_EXPORT_ROOT / f"_import_{uploaded_zip.name}"
    PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "wb") as f:
        f.write(uploaded_zip.getbuffer())
    try:
        with st.spinner("Importing..."):
            imported = import_project(tmp_path)
    except UnsafeZipEntryError as e:
        st.error(f"Refusing to import this bundle: {e}")
    else:
        set_state("raw_sources", imported["raw_sources"])

        # Replay promotion-event pipeline steps fresh against the imported
        # data rather than trusting the derived promo columns already
        # sitting in the imported parquet (PR E.2 #11 - "re-importing a
        # project must reproduce the same derived columns from raw data").
        # Any pre-existing derived column for a segment with a
        # promotion_event step is dropped first, so the regenerated value
        # is computed purely from the versioned event list, not layered on
        # top of a stale one.
        transformed = imported["transformed_data"]
        promo_steps = [
            s
            for s in pipeline_from_json(imported["pipeline_steps"] or [])
            if s.op == PROMOTION_EVENT_OP
        ]
        if transformed is not None and promo_steps:
            promo_columns = {
                f"{s.params.get('column_prefix', '_promo_event_')}{s.params['event']['segment']}"
                for s in promo_steps
            }
            transformed = transformed.drop(
                columns=[c for c in promo_columns if c in transformed.columns]
            )
            transformed = apply_pipeline(transformed, promo_steps)
        set_state("transformed_data", transformed)
        set_state("pipeline_steps", imported["pipeline_steps"])
        set_state("model_spec", imported["model_spec"])
        set_state("prior_config", imported["prior_config"])
        set_state("dna_lag_weeks", imported["dna_lag_weeks"])
        set_state("scenarios", imported["scenarios"])
        set_state("data_loaded", bool(imported["raw_sources"]))
        set_state("trace", imported["trace"])
        set_state("model_run_id", imported["model_run_id"])
        set_state("market_spec_config", imported["market_spec_config"])
        set_state("media_input_specs", imported.get("media_input_specs") or [])
        set_state("media_cost_mappings", imported.get("media_cost_mappings"))
        set_state("media_input_support", imported.get("media_input_support") or [])
        set_state(
            "monetary_spend_support",
            imported.get("monetary_spend_support") or [],
        )
        set_state(
            "activity_definitions",
            imported.get("activity_definitions") or [],
        )
        set_state("model_type", imported["model_type"])
        set_state("outcome_definitions", imported["outcome_definitions"])
        # G2A.7a.1 (REQ-OUT-002 section 12.1, 12.3): migration now lives in
        # core (resolve_imported_outcome_approvals) - a programmatic import
        # gets the same legacy_unapproved migration a UI-driven import does,
        # and a malformed record is reported by index/id, not silently
        # dropped via a bare `except Exception`.
        resolved_approvals, approval_warnings = resolve_imported_outcome_approvals(
            imported
        )
        set_state("outcome_approvals", resolved_approvals)
        for approval_warning in approval_warnings:
            st.warning(approval_warning)
        if imported.get("outcome_approvals") is None and resolved_approvals:
            st.warning(
                "This project bundle has no outcome approvals. "
                f"{len(resolved_approvals)} legacy_unapproved record(s) were "
                "created. Official planning, optimisation, and reporting "
                "are blocked until outcomes are reviewed and approved. "
                "Go to Structure → Outcome Governance to review."
            )
        set_state("funnel_links", imported["funnel_links"])
        set_state("media_outcome_pathways", imported["media_outcome_pathways"])
        set_state("net_billthrough_metadata", imported["net_billthrough_metadata"])
        # REQ-GRAPH-001 work package (graph portability): restore every
        # quarantine-checked graph version, and make the highest-numbered
        # one (this project's single graph lineage - see
        # graph_versions_for_export) the current graph. A bundle with no
        # causal_graphs.json (every bundle exported before this capability
        # existed, or a project with no graph configured) resolves to an
        # empty list - "no graph" is restored as no graph, never fabricated.
        _resolved_graphs, _graph_warnings = resolve_imported_causal_graphs(imported)
        set_state("causal_graph_versions", _resolved_graphs)
        set_state(
            "causal_graph", current_graph_from_resolved_versions(_resolved_graphs)
        )
        for _graph_warning in _graph_warnings:
            st.warning(_graph_warning)
        # A "prepared model configuration" flag and edge-removal tombstone
        # set are both session-only working state scoped to whatever graph
        # was live in THIS session before import (mirrors the
        # constrained_result/unconstrained_result clearing below, and for
        # the same reason: importing a project is exactly the boundary
        # where session-only state from a previous project must never
        # survive) - never left over from a previous project's graph work.
        set_state("causal_graph_compiled_structural_fingerprint", None)
        set_state("cg_removed_edge_ids", None)
        # REQ-SEARCH-001 S10: restore every quarantine-checked, cross-object-
        # validated governed Search object *version* as history, and derive
        # the current record per lineage the same way the causal graph
        # import above derives `causal_graph` from `causal_graph_versions`.
        # A bundle with no search_objects.json (every bundle exported before
        # this capability existed, or a project with none governed) resolves
        # to an empty list - "none governed" is restored as none, never
        # fabricated.
        _resolved_search_objects, _search_object_warnings = (
            resolve_imported_search_objects(imported)
        )
        set_state("search_object_versions", _resolved_search_objects)
        set_state(
            "search_objects",
            [
                defn.to_dict()
                for defn in current_search_object_versions(_resolved_search_objects)
            ],
        )
        for _search_object_warning in _search_object_warnings:
            st.warning(_search_object_warning)
        # REQ-COVERAGE-001 S3: restore the quarantine-checked immutable
        # SourceVersion history in full - a bundle with no
        # source_versions.json (every bundle exported before this
        # capability existed, or a project with no real-upload provenance
        # recorded yet) resolves to an empty list, never fabricated.
        _resolved_source_versions, _source_version_warnings = (
            resolve_imported_source_versions(imported)
        )
        set_state("source_versions", _resolved_source_versions)
        for _source_version_warning in _source_version_warnings:
            st.warning(_source_version_warning)
        # REQ-DATAIN-001: restore the quarantine-checked governed
        # SourceDefinition records - a bundle with no
        # source_definitions.json (every bundle exported before this
        # capability existed) resolves to an empty list, so every source in
        # it reads as unclassified (resolve_source_logical_domain returns
        # None), never fabricated.
        _resolved_source_definitions, _source_definition_warnings = (
            resolve_imported_source_definitions(imported)
        )
        set_state("source_definitions", _resolved_source_definitions)
        for _source_definition_warning in _source_definition_warnings:
            st.warning(_source_definition_warning)
        # REQ-COVERAGE-001 S1: restore every quarantine-checked coverage-
        # matrix version as history, and derive the current matrix the same
        # way the causal graph import above derives `causal_graph` from
        # `causal_graph_versions`. A bundle with no
        # variable_coverage_matrices.json (every bundle exported before this
        # capability existed, or a project with no coverage matrix built
        # yet) resolves to an empty list - "no matrix yet" is restored as no
        # matrix, never fabricated.
        _resolved_coverage_matrices, _coverage_matrix_warnings = (
            resolve_imported_variable_coverage_matrices(imported)
        )
        set_state("variable_coverage_matrix_versions", _resolved_coverage_matrices)
        set_state(
            "variable_coverage_matrix",
            current_variable_coverage_matrix_from_resolved_versions(
                _resolved_coverage_matrices
            ),
        )
        for _coverage_matrix_warning in _coverage_matrix_warnings:
            st.warning(_coverage_matrix_warning)
        # REQ-COVERAGE-001 S4 (Work Package 4): restore the join key
        # columns, mode and diagnostics from the most recent "Join
        # sources" click - a bundle with no join_config.json (every bundle
        # exported before this capability existed, or a project with no
        # sources joined yet) resolves every key to None, "not joined yet"
        # restored as not joined yet, never fabricated.
        _join_config = imported.get("join_config") or {}
        set_state("date_col", _join_config.get("date_col"))
        set_state("market_col", _join_config.get("market_col"))
        set_state("join_mode", _join_config.get("join_mode"))
        set_state("join_diagnostics", _join_config.get("join_diagnostics"))
        set_state("migration_review", imported.get("migration_review"))
        # PR 125A: restore the project-level planning dependencies so a
        # resumed session's Scenario Planner selection (and any newly
        # re-saved scenario) matches what was exported, and so a re-export
        # of this same session round-trips the identical policy/context.
        set_state("counterfactual_policy", imported.get("counterfactual_policy"))
        set_state("currency_context", imported.get("currency_context"))
        set_state("value_mapping", imported.get("value_mapping"))
        # Fresh review finding: a cached constrained_result/unconstrained_
        # result left over from a DIFFERENT project earlier in this same
        # Streamlit session is only invalidated by a governance_mode or
        # counterfactual_policy_fingerprint change (Scenario Planner's
        # _invalidate_stale_cached_result) - it doesn't compare currency
        # context or value mapping at all, so an imported project sharing
        # the same counterfactual policy but a different currency/value
        # mapping could still show and allow saving the PREVIOUS project's
        # cached result under this newly imported one. A project import is
        # exactly the boundary where session-only cached results (never the
        # system of record - see this module's docstring) must never
        # survive across projects.
        set_state("constrained_result", None)
        set_state("unconstrained_result", None)
        workflow_state = imported.get("workflow_state") or {}
        set_state("current_page", workflow_state.get("current_page", 0))
        set_state("active_scenario", workflow_state.get("active_scenario"))
        set_state("project_notes", imported.get("notes") or "")
        set_state("calibration_records", imported.get("calibration_records") or [])
        set_state(
            "model_comparison_candidates",
            imported.get("model_comparison_candidates") or [],
        )
        imported_diagnostics = imported.get("diagnostics") or {}
        set_state("scorecard", imported_diagnostics.get("scorecard"))
        set_state("backtest_results", imported_diagnostics.get("backtest_results"))
        if imported.get("curve_bank_files") or imported.get("curve_bank_binary_files"):
            restored_curve_dir = curve_bank_dir()
            restored_curve_dir.mkdir(parents=True, exist_ok=True)
            for filename, contents in imported["curve_bank_files"].items():
                target = restored_curve_dir / Path(filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents)
            for filename, contents in imported.get(
                "curve_bank_binary_files", {}
            ).items():
                target = restored_curve_dir / Path(filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
            set_state(
                "curve_bank_entry_id",
                Path(
                    next(
                        iter(
                            imported["curve_bank_files"]
                            or imported.get("curve_bank_binary_files", {})
                        )
                    )
                ).stem,
            )
        # Corrective PR A5: importing a bundle must atomically replace the
        # destination project's official-artifact store, not merge into it -
        # unconditionally, including when the imported bundle has zero
        # official curve artifacts (replace_curve_artifact_store always
        # clears the destination first, regardless of what the bundle
        # contains).
        restored_artifact_dir = curve_artifact_store_dir()
        replace_curve_artifact_store(imported, restored_artifact_dir)
        if imported.get("curve_artifact_files") or imported.get(
            "curve_artifact_binary_files"
        ):
            # PR 96B: reload the restored store immediately - this both
            # verifies every artifact's chain/extra fingerprints (the
            # "checksum" check for a clean-environment round-trip) and
            # produces the per-artifact audit (REQ-CURVE-001: malformed
            # entries are reported, never silently dropped).
            try:
                artifact_load_result = load_curve_artifact_store(
                    restored_artifact_dir, raise_on_malformed=False
                )
            except CurveArtifactError as exc:
                st.warning(
                    f"Official curve artifact store could not be re-read after "
                    f"import: {exc}"
                )
            else:
                if artifact_load_result.malformed:
                    st.warning(
                        f"{len(artifact_load_result.malformed)} imported official "
                        "curve artifact(s) failed to verify and are reported below "
                        "- never silently skipped."
                    )
                    for entry in artifact_load_result.malformed:
                        st.caption(f"{entry.artifact_dir.name}: {entry.error}")
                if artifact_load_result.loaded:
                    st.success(
                        f"Restored {len(artifact_load_result.loaded)} official "
                        f"curve artifact(s) to {restored_artifact_dir}."
                    )
        if imported["market_spec_config"] is None:
            st.caption(
                "This bundle predates the market-specific redesign - no market descriptors or "
                "media-unit mappings to import. Add them on Channel & Media Units / Market "
                "Descriptors if needed."
            )
        if imported["outcome_definitions"] is None:
            st.caption(
                "This bundle predates the outcome-schema work - no DNA outcome mappings to "
                "import. The Family History outcome catalogue is still derived automatically "
                "from this project's structure; add DNA outcomes on Structure: Segments & "
                "Markets if needed."
            )

        # Re-derive the frame and posterior params from the raw artefacts
        # (cheap - pandas prep + posterior summarisation, no re-fit) so the
        # imported approval can be verified against them rather than blindly
        # trusted or blindly discarded.
        reconstructed = reconstruct_model_state(imported)
        set_state("frame", reconstructed["frame"])
        set_state("model_meta", reconstructed["model_meta"])
        set_state("posterior_params", reconstructed["posterior_params"])
        set_state("model_trained", reconstructed["posterior_params"] is not None)
        resume_audit = audit_project_resumability(imported)
        if resume_audit["resumable"]:
            st.success(
                f"Resumability audit passed at checkpoint "
                f"'{resume_audit['checkpoint']}'."
            )
        else:
            st.warning(
                "Bundle imported, but its declared checkpoint is incomplete: "
                + ", ".join(resume_audit["missing_required"])
            )
        for audit_warning in resume_audit["warnings"]:
            st.caption(audit_warning)
        for outcome_governance_warning in resume_audit.get(
            "outcome_governance_warnings", []
        ):
            st.caption(outcome_governance_warning)

        # PR 82D/88A: restore the governance evidence chain established in
        # PR 82B. The policy and diagnostics artefact are restored as
        # independent evidence (useful on their own, e.g. to re-evaluate a
        # fresh readiness): the policy dict as-is (every page rehydrates it
        # fresh via the shared fail-closed loader below), and the
        # diagnostics artefact rehydrated through DiagnosticsArtefact.
        # from_dict() - never left as the raw imported dict, which pages/06
        # would then crash on the moment it called e.g. `.identification`
        # on what would actually be a plain dict.
        raw_policy_dict = imported.get("validation_policy")
        set_state("validation_policy", raw_policy_dict)
        imported_policy, policy_load_error = load_threshold_policy(raw_policy_dict)
        if policy_load_error:
            st.warning(
                "Imported validation policy is malformed and cannot be used: "
                f"{policy_load_error}"
            )

        raw_diagnostics_artefact_dict = imported.get("diagnostics_artefact")
        imported_diagnostics_artefact = None
        if raw_diagnostics_artefact_dict is not None:
            try:
                imported_diagnostics_artefact = DiagnosticsArtefact.from_dict(
                    raw_diagnostics_artefact_dict
                )
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                st.warning(
                    f"Imported diagnostics artefact was malformed and discarded: {exc}"
                )
        set_state("diagnostics_artefact", imported_diagnostics_artefact)
        set_state("validation_results", imported.get("validation_results"))

        # The readiness proof binding policy + diagnostics artefact to a
        # specific model identity is only restored if it verifiably still
        # matches the imported policy, diagnostics artefact, and
        # reconstructed model - never trusted blindly, mirroring how
        # model_approval is verified below.
        verified_readiness, readiness_message = verify_imported_readiness(
            imported, reconstructed
        )
        set_state("approval_readiness", verified_readiness)
        (st.success if verified_readiness else st.warning)(readiness_message)
        verified_readiness_obj, _ = load_approval_readiness(verified_readiness)

        # PR 88A: a policy-backed approval is only restored as current
        # official authority when the FULL chain checks out - model identity
        # AND (for a policy-backed approval) an active current_policy plus
        # an overall_ready, fingerprint-matching readiness - not model
        # identity alone. Previously this was verified against identity only,
        # so a policy-backed approval could come back "verified" even though
        # its readiness was just rejected above as unverified.
        verified_approval, message = verify_imported_approval(
            imported,
            reconstructed,
            current_policy=imported_policy,
            approval_readiness=verified_readiness_obj,
        )
        set_state(
            "model_approval", verified_approval.to_dict() if verified_approval else None
        )
        (st.success if verified_approval else st.warning)(message)

        # G2A.7a.1 (REQ-OUT-002 section 12.2): a bundle can be technically
        # loadable while official use of its checkpoint remains blocked by
        # outcome governance - reported separately so "resumable" is never
        # read as "officially usable". PR 125A: the positive case is now
        # reported explicitly too (previously only the negative case had
        # any visible text), and every blocking reason is shown, not just
        # outcome-governance ones. Corrective review finding: this must be
        # decided only after verify_imported_approval above, not from
        # audit_project_resumability() alone - that core-layer check
        # cannot recompute the diagnostics-artefact fingerprint (core must
        # not import the application-layer DiagnosticsArtefact type), so a
        # bundle whose approval is policy-backed but whose diagnostics
        # artefact has since drifted could pass the coarse audit while the
        # fuller check above still rejects it. Emitting the positive claim
        # here (after that fuller check ran) rather than earlier means an
        # analyst is never told "officially resumable" only to see it
        # contradicted by a warning further down the same page.
        officially_resumable_and_verified = (
            resume_audit["resumable"]
            and resume_audit.get("officially_resumable", True)
            and (verified_approval is not None or not imported.get("model_approval"))
        )
        if officially_resumable_and_verified:
            st.success(
                f"This bundle is officially resumable at checkpoint "
                f"'{resume_audit['checkpoint']}'."
            )
        elif resume_audit["resumable"]:
            st.warning(
                "This bundle loaded successfully, but is not **officially** "
                "resumable at its checkpoint - see the reason(s) below."
            )
            for blocking_reason in resume_audit.get("official_blocking_reasons", []):
                st.caption(
                    f"{blocking_reason.get('artefact_type')} "
                    f"'{blocking_reason.get('artefact_id')}': "
                    f"{blocking_reason.get('reason')}"
                )
            if (
                resume_audit.get("officially_resumable", True)
                and verified_approval is None
                and imported.get("model_approval")
            ):
                st.caption(
                    "model_approval: the imported model approval could not be "
                    f"verified against the imported readiness and diagnostics "
                    f"evidence ({message})."
                )

        if imported["trace"] is not None and reconstructed["frame"] is None:
            st.info(
                "Imported a fitted trace, but couldn't reconstruct the modelling frame (missing "
                "or inconsistent transformed data / model spec) - re-run Model Configuration's "
                '"Prepare modelling frame" step, or re-fit, to continue.'
            )
        # Read this imported bundle's own manifest.json (already parsed by
        # import_project - see the module docstring) for the same
        # presentation-only checklist the export side shows, rather than
        # re-deriving a second notion of bundle contents here.
        set_state(
            "export_last_import_summary",
            {
                "bundle_name": uploaded_zip.name,
                "checkpoint": resume_audit.get("checkpoint"),
                "officially_resumable": officially_resumable_and_verified,
                "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        with st.expander("What was included in the imported bundle", expanded=False):
            _render_contains_checklist(
                (imported.get("manifest") or {}).get("contains", {})
            )
        st.success("Project imported. Review each page to pick up where you left off.")
    finally:
        tmp_path.unlink(missing_ok=True)

st.markdown("---")
with SectionCard(
    "Excel export",
    description=(
        "A working export for spreadsheet analysis - not the system of record. Re-importing "
        "the project bundle above is what fully restores a project; this file is one-way."
    ),
):
    model_type_for_export = get_state("model_type", "shared")
    if get_state("trace") is not None and get_state("model_spec"):
        _export_spec = ModelSpec.from_dict(get_state("model_spec"))
        render_drift_status(
            resolve_outcome_definitions(
                get_state("outcome_definitions"),
                _export_spec.segment_outcomes,
                _export_spec.segment_ltv,
            ),
            get_state("model_meta"),
        )
        _current_pathways = [
            MediaOutcomePathway.from_dict(p)
            for p in (get_state("media_outcome_pathways") or [])
        ]
        _pathway_drift_df = pathways_drift_dataframe(
            _current_pathways, get_state("model_meta")
        )
        if not _pathway_drift_df.empty:
            _changed_pathways = _pathway_drift_df[
                _pathway_drift_df["drift_status"] != "Fitted and current"
            ]
            if not _changed_pathways.empty:
                st.info(
                    f"{len(_changed_pathways)} media-outcome pathway(s) differ from this fit's captured "
                    "pathway metadata (informational only - the pathway catalogue does not yet drive "
                    "fitting; PR F)."
                )
        if model_type_for_export == "shared":
            st.caption(
                "Curve bank, total-FH contribution and segment x channel Shapley attribution (Model A)."
            )
        else:
            st.caption(
                "Curve bank, evidence tiers, a CPA table per market/channel, market-aware Shapley "
                "attribution (total and market x segment x channel detail, computed with each market's "
                "own beta/hill_K), diagnostics and approval metadata, and the scenario comparison."
            )
        if st.button("Build Excel summary"):
            meta = get_state("model_meta")
            params = get_state("posterior_params")
            frame = get_state("frame")
            trace = get_state("trace")
            spec = ModelSpec.from_dict(get_state("model_spec"))
            # Reuse the single top-of-page read (see "Project status" above)
            # instead of reading the curve bank directory a second time.
            entries = _curve_bank_entries
            entries_df = entries_to_dataframe(entries) if entries else None

            if model_type_for_export == "shared":
                contributions = compute_shapley_contributions(
                    frame, meta, params, n_permutations=100
                )
                total_df = total_fh_contribution(
                    frame,
                    meta,
                    params,
                    contributions,
                    spec.segment_ltv,
                    outcome_ids=fh_gsa_outcome_ids(meta),
                )
                seg_df = outcome_channel_summary(
                    frame, meta, params, contributions, spec.segment_ltv
                )
                sheets = {
                    "Total FH Contribution": total_df,
                    "Segment x Channel": seg_df,
                    "Curve Bank": entries_df,
                }
            else:
                scorecard = get_state("scorecard") or {}
                diagnostics_df = pd.DataFrame(scorecard.get("in_sample_fit") or [])
                approval_dict = get_state("model_approval")
                approval_df = pd.DataFrame([approval_dict]) if approval_dict else None
                scenarios = get_state("scenarios") or []
                scenarios_df = compare_scenarios(scenarios) if scenarios else None
                ms_contributions = compute_shapley_contributions_market_specific(
                    frame, meta, params, n_permutations=100
                )
                ms_total_df = total_contribution_market_specific(
                    frame,
                    meta,
                    params,
                    ms_contributions,
                    spec.segment_ltv,
                    outcome_ids=fh_gsa_outcome_ids(meta),
                    by_market=True,
                )
                ms_seg_df = outcome_channel_market_summary(
                    frame, meta, params, ms_contributions, spec.segment_ltv
                )
                sheets = {
                    "Curve Bank": entries_df,
                    "Evidence Tiers": evidence_tiers_dataframe(trace, frame, meta),
                    "CPA": market_specific_cpa_table(meta, params),
                    "Total Contribution": ms_total_df,
                    "Market x Segment x Channel": ms_seg_df,
                    "Diagnostics": diagnostics_df,
                    "Approval": approval_df,
                    "Scenarios": scenarios_df,
                }

            # Reuse the single top-of-page read (see "Project status" above)
            # instead of re-resolving official curve artifact governance a
            # second time.
            official_curve_artifact_rows = _official_curve_artifact_rows
            sheets["Official Curve Artifacts"] = (
                pd.DataFrame(official_curve_artifact_rows)
                if official_curve_artifact_rows
                else None
            )

            PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
            excel_path = PROJECT_EXPORT_ROOT / f"{project_name}_summary.xlsx"
            export_excel_summary(excel_path, sheets)
            with open(excel_path, "rb") as f:
                st.download_button(
                    "Download Excel summary (.xlsx)",
                    f,
                    file_name=excel_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
    else:
        st.info("Train a model first to build an Excel summary.")

st.markdown("---")
with SectionCard(
    "Project report",
    description=(
        "A single reproducible document - objective, data, model, diagnostics, curve bank, "
        "scenarios, known limitations, and a pointer to the decision log - built from this "
        "project's actual current state, not a static template. A working export, not the "
        "system of record: available at any point in the workflow, and sections say plainly "
        "what hasn't happened yet rather than being left out."
    ),
):
    if st.button("Build project report"):
        spec_dict = get_state("model_spec")
        spec = ModelSpec.from_dict(spec_dict) if spec_dict else None
        frame = get_state("frame")
        data_window = None
        if frame is not None and frame.get("dates") is not None and len(frame["dates"]):
            data_window = (
                str(pd.Timestamp(frame["dates"].min()).date()),
                str(pd.Timestamp(frame["dates"].max()).date()),
            )
        approval_dict = get_state("model_approval")
        approval = ModelApproval.from_dict(approval_dict) if approval_dict else None
        # Reuse the single top-of-page read (see "Project status" above)
        # instead of reading the curve bank directory a second time.
        entries = _curve_bank_entries
        market_config = MarketSpecConfig.from_dict(get_state("market_spec_config"))

        sections = build_report_sections(
            spec=spec,
            model_type=get_state("model_type", "shared"),
            pipeline_steps=get_state("pipeline_steps") or [],
            data_window=data_window,
            dna_lag_weeks=get_state("dna_lag_weeks", 4),
            scorecard=get_state("scorecard"),
            approval=approval,
            curve_bank_entries=entries,
            scenarios=get_state("scenarios") or [],
            market_spec_config=market_config,
            outcome_definitions=get_state("outcome_definitions"),
            official_curve_artifact_rows=_official_curve_artifact_rows,
        )

        PROJECT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
        md_path = PROJECT_EXPORT_ROOT / f"{project_name}_report.md"
        html_path = PROJECT_EXPORT_ROOT / f"{project_name}_report.html"
        md_path.write_text(render_markdown(project_name, sections))
        html_path.write_text(render_html(project_name, sections))
        st.success("Report built.")
        c1, c2 = st.columns(2)
        with open(md_path, "rb") as f:
            c1.download_button(
                "Download report (.md)", f, file_name=md_path.name, mime="text/markdown"
            )
        with open(html_path, "rb") as f:
            c2.download_button(
                "Download report (.html)", f, file_name=html_path.name, mime="text/html"
            )

st.markdown("---")
with InfoPanel("What's out of scope"):
    st.markdown("""
Per `docs/project_objectives.md` and `docs/limitations.md`, deliberately **not** built:

- **CPA/inflation as first-class optimiser objectives** - "minimise CPA," "maintain response/delivery
  under inflation" from the original redesign brief; `avg_cpa`/`dna_avg_cpa` are reported as output
  metrics, not optimisation targets themselves. What *is* built: explicit, product-aware optimisation
  objectives (maximise FH GSAs, DNA kits, or LTV-weighted expected value) that never silently combine
  Family History GSAs and DNA kit sales into one "volume" number.
- **Media-unit spend constraints** (locked/min/max media units) - `SpendConstraint` still operates in
  spend terms only.
- **PowerPoint export** - Excel + the project bundle + this report cover portability and recovery today.
- **Automating currency conversion** - the tool stores exchange-rate context but never silently
  converts or applies an inflation assumption without it being visible in the UI.
- **Stage 2 media x context interactions** - explicitly out of scope for the core model per the brief.
""")

st.markdown("---")
st.caption(
    "This is the last step in the workflow. Revisit any page from the sidebar to refine the model or plans."
)
