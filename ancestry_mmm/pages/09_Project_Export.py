"""Page 9: project export/import bundle (Parquet + JSON + NetCDF) and Excel export for portability and recovery.

Phase 6 of the dashboard UX/UI brief applies the shared shell and an
Export & Recovery dashboard to this page. Presentation only:
every value shown is read from existing session-state getters or from the
bundle's own manifest.json ("contains" dict, written by
core.persistence.export_project - never recomputed here), never invented or
duplicated. WP2 also persists the official canonical preparation evidence
and its durable native frame through the existing persistence boundary.
"""

import json
import sys
import uuid
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
    render_workspace_note,
    SectionCard,
)
from ancestry_mmm.core.persistence import (
    export_project,
    import_project,
    export_excel_summary,
    reconstruct_model_state,
    replace_curve_artifact_store,
    resolve_imported_outcome_approvals,
    resolve_imported_media_outcome_pathways,
    resolve_imported_causal_graphs,
    resolve_imported_search_objects,
    resolve_imported_source_versions,
    resolve_imported_source_definitions,
    resolve_imported_variable_coverage_matrices,
    resolve_imported_outcome_groups,
    resolve_imported_outcome_group_treatments,
    resolve_imported_outcome_reconciliation_groups,
    resolve_imported_experiments,
    resolve_imported_named_events,
    verify_imported_approval,
    UnsafeZipEntryError,
    audit_project_resumability,
)
from ancestry_mmm.application.experiment_service import (
    registry_has_content,
    registry_to_dict,
)
from ancestry_mmm.application.fx_service import (
    FXUploadValidationError,
    build_manual_fx_rate_set,
)
from ancestry_mmm.application.event_service import (
    registry_has_content as named_event_registry_has_content,
    registry_to_dict as named_event_registry_to_dict,
)
from ancestry_mmm.core.experiments import (
    CompatibilityAssessment,
    ExperimentRecord,
    ExperimentToModelUse,
)
from ancestry_mmm.core.named_events import (
    EventResponseDefinition,
    NamedEventFamily,
    NamedEventOccurrence,
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
from ancestry_mmm.core.search_intent_taxonomy import (
    resolve_imported_search_intent_groups,
    resolve_imported_search_intent_group_versions,
    resolve_search_intent_model_grain,
    search_intent_taxonomy_fit_fingerprint,
)
from ancestry_mmm.core.coverage import (
    VariableCoverageMatrix,
    current_variable_coverage_matrix_from_resolved_versions,
    variable_coverage_matrix_versions_for_export,
)
from ancestry_mmm.core.media_units import market_specific_cpa_table
from ancestry_mmm.core.outcome_approval import OutcomeApproval
from ancestry_mmm.core.outcomes import (
    OutcomeGroupDefinition,
    fh_gsa_outcome_ids,
    outcome_catalogue_fingerprint_payload,
    resolve_outcome_definitions,
)
from ancestry_mmm.core.seo_visibility import seo_fit_inputs_fingerprint
from ancestry_mmm.core.pathways import (
    MediaOutcomePathway,
    pathway_catalogue_fingerprint_payload,
    pathways_drift_dataframe,
)
from ancestry_mmm.core.optimization import compare_scenarios
from ancestry_mmm.core.report import build_report_sections, render_markdown, render_html
from ancestry_mmm.core.promotions import PROMOTION_EVENT_OP
from ancestry_mmm.data import (
    adopted_model_input_frame,
    apply_pipeline,
    pipeline_from_json,
)

_CURVE_SERVICE = CurveService()

# Human-readable labels for core.persistence.export_project's manifest.json
# "contains" keys, purely presentational (label text only, no logic) - used
# to render an honest "what's actually in this bundle" checklist straight
# from the bundle's own manifest after a real build/import, rather than
# re-deriving a second, possibly-drifting notion of bundle contents here.
_CONTAINS_LABELS = {
    "raw_data": "Original source files and tables",
    "transformed_data": "Prepared modelling data",
    "model_spec": "Model definition (segments, markets, channels)",
    "fitted_model_spec": "Fitted Search-grain model definition",
    "posterior": "Fitted model and posterior draws",
    "diagnostics": "Diagnostics scorecard / backtest results",
    "curves": "Exploratory curve snapshots",
    "official_curve_artifacts": "Governed Planning Curves",
    "approval": "Model approval record",
    "outcome_approvals": "Outcome approvals",
    "scenarios": "Saved scenarios",
    "notes": "Analyst notes",
    "validation_policy": "Validation policy and thresholds",
    "diagnostics_artefact": "Diagnostic evidence record",
    "validation_results": "Validation results",
    "approval_readiness": "Approval readiness evidence",
    "counterfactual_policy": "Counterfactual policy",
    "currency_context": "Currency context",
    "fx_rate_set": "Finance FX rate set",
    "value_mapping": "Outcome value mapping",
    "causal_graphs": "Causal graph versions",
    "search_objects": "Search definitions and versions",
    "search_intent_groups": "Search intent taxonomy",
    "search_intent_group_versions": "Search intent taxonomy versions",
    "search_intent_model_grain": "Search intent model grain",
    "source_versions": "Source file version history",
    "source_definitions": "Source categories and roles",
    "variable_coverage_matrices": "Coverage and frequency review history",
    "join_config": "Source join settings",
    "standard_activity_model_input": "Adopted Activity model input",
    "standard_outcome_data": "Adopted Outcomes model input",
    "standard_context_data": "Adopted Context model input",
    "context_variable_metadata": "Context variable metadata",
    "source_domain_semantics": "Source semantic adoption statuses",
    "experiment_registry": "Experiment evidence registry",
    "named_event_registry": "Governed named-event registry",
}

_CHECKPOINT_LABELS = {
    "uploaded": "Sources uploaded",
    "transformed": "Data prepared",
    "configured": "Model configured",
    "pre_fit": "Ready to fit",
    "fitted": "Model fitted",
    "approved": "Model approved",
    "curves": "Curves saved",
    "official_curves": "Planning curves saved",
    "scenarios": "Scenarios saved",
    "unknown": "Not recorded",
}


def _display_checkpoint(checkpoint: object) -> str:
    """Translate persisted checkpoint values into analyst-facing copy."""

    value = str(checkpoint or "unknown")
    return _CHECKPOINT_LABELS.get(value, value.replace("_", " ").title())


def _experiments_for_export() -> dict | None:
    """The governed experiment registry as one exportable payload (records,
    declared model uses, compatibility assessments, retained source rows
    under one record-level schema version) - None while the registry is
    empty, so older bundles remain byte-comparable."""
    records = [
        ExperimentRecord.from_dict(item)
        for item in (get_state("experiment_records") or [])
    ]
    uses = [
        ExperimentToModelUse.from_dict(item)
        for item in (get_state("experiment_model_uses") or [])
    ]
    assessments = [
        CompatibilityAssessment.from_dict(item)
        for item in (get_state("experiment_compatibility_assessments") or [])
    ]
    evidence_rows = get_state("experiment_evidence_rows") or []
    if not registry_has_content(records, uses, assessments, evidence_rows):
        return None
    return registry_to_dict(records, uses, assessments, evidence_rows)


def _named_events_for_export() -> dict | None:
    """The governed named-event registry as one exportable payload
    (families, factual occurrences, response definitions under one
    record-level schema version) - None while the registry is empty, so
    older bundles remain byte-comparable."""
    families = [
        NamedEventFamily.from_dict(item)
        for item in (get_state("named_event_families") or [])
    ]
    occurrences = [
        NamedEventOccurrence.from_dict(item)
        for item in (get_state("named_event_occurrences") or [])
    ]
    definitions = [
        EventResponseDefinition.from_dict(item)
        for item in (get_state("named_event_response_definitions") or [])
    ]
    if not named_event_registry_has_content(families, occurrences, definitions):
        return None
    return named_event_registry_to_dict(families, occurrences, definitions)


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
                search_intent_taxonomy_fit_fingerprint=search_intent_taxonomy_fit_fingerprint(
                    activity_definitions,
                    get_state("search_intent_groups") or [],
                    get_state("search_intent_group_versions") or [],
                    consumed_model_input_columns=spec_dict.get("channels") or [],
                ),
                variable_coverage_fingerprint=(
                    VariableCoverageMatrix.from_dict(coverage_matrix_dict).fingerprint()
                    if coverage_matrix_dict
                    else None
                ),
                official_preparation_evidence=get_state("official_preparation_result"),
                seo_fit_fingerprint=seo_fit_inputs_fingerprint(
                    get_state("seo_fit_inputs")
                    or getattr(meta, "seo_fit_inputs_at_fit", None)
                ),
                calibration_fit_fingerprint=(
                    getattr(meta, "calibration_fit_fingerprint", "") or None
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
    page_title="Export & Recovery | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("export")
render_page_header(
    "export",
    task_prompt="Can this project be resumed from a durable bundle?",
    badges=[page_readiness("export")],
)
render_workspace_note(
    "Durable bundle",
    "Use the bundle for recovery and collaboration; Excel and report outputs are read-only exports and do not replace the system of record.",
    kind="governed",
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

_bundle_activity = (
    "Built + restored"
    if _last_bundle_build and _last_bundle_import
    else "Built this session"
    if _last_bundle_build
    else "Restored this session"
    if _last_bundle_import
    else "Not started"
)
_latest_checkpoint = _last_bundle_import or _last_bundle_build or {}
_secondary_outputs = (
    "Excel + report" if get_state("trace") is not None else "Report only"
)

st.markdown("### Export & Recovery dashboard")
st.caption(
    "Keep the durable project bundle as the recovery object. Use the one-way Excel and report exports for sharing or review."
)
_dashboard_col1, _dashboard_col2 = st.columns(2)
with _dashboard_col1:
    st.metric("Primary recovery object", "Durable bundle")
with _dashboard_col2:
    st.metric("Bundle activity", _bundle_activity)
_dashboard_col3, _dashboard_col4 = st.columns(2)
with _dashboard_col3:
    st.metric(
        "Latest checkpoint",
        _display_checkpoint(_latest_checkpoint.get("checkpoint")),
    )
with _dashboard_col4:
    st.metric("Secondary outputs", _secondary_outputs)

with SectionCard(
    "Project snapshot",
    description=(
        "A compact view of the working project and this session's bundle activity. The durable "
        "bundle remains the source of truth."
    ),
):
    _status_col1, _status_col2 = st.columns(2)
    with _status_col1:
        st.markdown("**Current project**")
        st.caption(f"Project name: {get_state('project_name', 'ancestry-fh-uk')}")
        st.caption(
            f"Source files/tables loaded: {len(get_state('raw_sources') or {})} "
            f"(source versions recorded: {len(get_state('source_versions') or [])})"
        )
        st.caption(f"Preparation steps saved: {len(get_state('pipeline_steps') or [])}")
        _model_run_id = get_state("model_run_id")
        st.caption(
            "Fitted model: "
            + ("available" if _model_run_id else "not yet available")
            + (", approved" if get_state("model_approval") else ", not approved")
        )
        st.caption(
            f"Causal graph versions saved: {len(get_state('causal_graph_versions') or [])}"
        )
        st.caption(
            "Search definitions saved: "
            f"{len(get_state('search_object_versions') or [])}"
        )
        st.caption(
            "Coverage and frequency reviews saved: "
            f"{len(get_state('variable_coverage_matrix_versions') or [])}"
        )
        st.caption(f"Exploratory curve snapshots: {len(_curve_bank_entries)}")
        st.caption(
            f"Saved Planning Curves: {len(_official_curve_artifact_rows)} "
            f"({_authorized_artifact_count} currently authorised for headline reporting)"
            if _official_curve_artifact_rows
            else "Saved Planning Curves: none created yet"
        )
        st.caption(
            "Activity taxonomy entries saved: "
            f"{len(get_state('activity_definitions') or [])}"
        )
        st.caption(f"Saved scenarios: {len(get_state('scenarios') or [])}")
    with _status_col2:
        st.markdown("**This session's bundle activity**")
        if _last_bundle_build:
            st.caption(
                f"Last bundle built this session: `{_last_bundle_build['project_name']}` "
                f"at {_display_checkpoint(_last_bundle_build['checkpoint'])}, "
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
                + f" at {_display_checkpoint(_last_bundle_import.get('checkpoint'))}, "
                f"{_last_bundle_import['imported_at']} UTC."
            )
        else:
            st.caption("No bundle has been imported yet this session.")
        st.caption(
            "This activity log is session-only and resets on refresh. The bundle file is the durable recovery object."
        )

    with st.expander("Technical details", expanded=False):
        if _model_run_id:
            st.caption(f"Model run ID: `{_model_run_id}`")
        st.caption(
            "Session state is not durable storage; build or restore a project bundle before leaving this session."
        )

st.markdown("---")
st.markdown("### Restore from a project bundle")
st.caption(
    "Restore a bundle from another analyst, session, or date. Restored project "
    "evidence is re-verified before official use."
)
uploaded_zip = st.file_uploader("Upload a previously exported .zip", type=["zip"])

st.markdown("---")
with SectionCard(
    "Finance FX rate set",
    description=(
        "Optional manual upload boundary for Finance-approved rates. No rate is "
        "invented or fetched automatically; an uploaded set remains pending until "
        "Finance approval is recorded."
    ),
):
    st.caption(
        "UK reporting convention for an approved currency view: source GBP is "
        "translated to USD using `USD = GBP × approved GBP-to-USD rate`, by "
        "calendar year (January–December). No live-rate fallback is used; a "
        "pending or unapproved rate set cannot drive official reporting. NBT "
        "count fitting is unaffected by FX readiness."
    )
    _fx_current = get_state("fx_rate_set")
    if _fx_current:
        st.caption(
            f"Loaded rate set `{_fx_current.get('rate_set_id', '')}` "
            f"v{_fx_current.get('rate_set_version', '?')} "
            f"({_fx_current.get('approval_status', 'pending')}); "
            f"records: {len(get_state('fx_rate_records') or [])}."
        )
    else:
        st.info(
            "No Finance rate set is loaded. Cross-currency constant-dollar "
            "conversion remains unavailable until an approved set is supplied."
        )
    with st.expander("Upload or replace a Finance rate set", expanded=False):
        _fx_upload = st.file_uploader(
            "Rate CSV",
            type=["csv"],
            key="fx_rate_upload",
            help=(
                "Required columns: rate_date, source_currency, target_currency, "
                "rate, method, frequency; annual rows also require financial_year."
            ),
        )
        _fx_meta_cols = st.columns(3)
        _fx_name = _fx_meta_cols[0].text_input("Rate-set name", key="fx_rate_name")
        _fx_provider = _fx_meta_cols[1].text_input(
            "Provider identity", key="fx_rate_provider"
        )
        _fx_reference = _fx_meta_cols[2].text_input(
            "Reference currency", value="GBP", key="fx_rate_reference"
        )
        _fx_dates = st.columns(2)
        _fx_start = _fx_dates[0].text_input(
            "Start date (YYYY-MM-DD)", key="fx_rate_start"
        )
        _fx_end = _fx_dates[1].text_input("End date (YYYY-MM-DD)", key="fx_rate_end")
        _fx_policy = st.text_input(
            "Finance rate policy / approval reference", key="fx_rate_policy"
        )
        if st.button("Validate and load rate set", key="load_fx_rate_set"):
            if _fx_upload is None:
                st.error("Choose a Finance rate CSV before loading it.")
            else:
                try:
                    _fx_version = (
                        int((_fx_current or {}).get("rate_set_version", 0)) + 1
                    )
                    _fx_set, _fx_records = build_manual_fx_rate_set(
                        _fx_upload.getvalue(),
                        rate_set_id=(_fx_current or {}).get(
                            "rate_set_id", "manual-fx-pending"
                        ),
                        rate_set_version=_fx_version,
                        name=_fx_name,
                        provider=_fx_provider,
                        base_or_reference_currency=_fx_reference,
                        start_date=_fx_start,
                        end_date=_fx_end,
                        rate_policy=_fx_policy,
                    )
                    set_state("fx_rate_set", _fx_set.to_dict())
                    set_state(
                        "fx_rate_records", [record.to_dict() for record in _fx_records]
                    )
                    st.success(
                        f"Validated {len(_fx_records)} FX record(s). The set is pending "
                        "Finance approval and is now included in the next bundle."
                    )
                    st.rerun()
                except (FXUploadValidationError, ValueError, TypeError) as exc:
                    st.error(f"FX rate-set validation failed: {exc}")

st.markdown("---")
st.markdown("### Build durable project bundle")
st.caption(
    "The primary recovery object: one portable .zip that can be restored into a working project."
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
    # Codex review (PR #348, P1 follow-up): a per-project-name path here -
    # even one only ever read back within this same block, as the original
    # code did - is still a write-side race. Two sessions building
    # "proj-status" concurrently would both target this exact file; whichever
    # session's read happens after the other's write completed (mid- or
    # post-write) could read a corrupt or entirely foreign bundle, before
    # either session's own private byte-caching (below) ever gets a chance
    # to help. A session-unique filename (never shared with any other
    # session, concurrent or not) removes the collision at its source rather
    # than mitigating it after the fact. Deleted once its bytes/manifest are
    # cached - see below - since nothing needs it to persist on disk.
    output_path = PROJECT_EXPORT_ROOT / f"_build_{uuid.uuid4().hex}.zip"
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
            model_spec=(get_state("prepared_model_spec") or get_state("model_spec")),
            fitted_model_spec=get_state("fitted_model_spec"),
            prior_config=get_state("prior_config"),
            dna_lag_weeks=get_state("dna_lag_weeks", 4),
            trace=get_state("trace"),
            scenarios=get_state("scenarios") or [],
            project_display_name=project_name,
            curve_bank_source_dir=curve_bank_dir(),
            curve_artifact_store_source_dir=curve_artifact_store_dir(),
            model_approval=get_state("model_approval"),
            model_run_id=get_state("model_run_id"),
            model_meta=get_state("model_meta"),
            market_spec_config=get_state("market_spec_config"),
            model_type=get_state("model_type", "shared"),
            outcome_definitions=get_state("outcome_definitions"),
            outcome_groups=get_state("outcome_groups"),
            outcome_group_treatments=get_state("outcome_group_treatments"),
            outcome_reconciliation_groups=get_state("outcome_reconciliation_groups"),
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
                "prefit_identifiability": get_state("prefit_identifiability"),
                "prefit_screening": get_state("prefit_screening"),
                # Production integration (Decision 17, REQ-DATASUPPORT-001):
                # the analyst's chosen governed response per channel for the
                # consolidated data-support classification tab on
                # Diagnostics (pages/06_Diagnostics.py) - a plain
                # channel -> governed-response-string dict, JSON-
                # serialisable like every other key in this bag. Without
                # this, re-importing a project would silently lose a
                # recorded governed response and force the analyst to
                # re-select it, even though the underlying evidence itself
                # (prefit_identifiability, above) is preserved.
                "data_support_governed_response_by_channel": get_state(
                    "data_support_governed_response_by_channel"
                ),
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
            fx_rate_set=get_state("fx_rate_set"),
            fx_rate_records=get_state("fx_rate_records"),
            value_mapping=get_state("value_mapping"),
            outcome_valuation_records=get_state("outcome_valuation_records") or [],
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
            search_intent_groups=get_state("search_intent_groups") or [],
            search_intent_group_versions=get_state("search_intent_group_versions")
            or [],
            search_intent_model_grain=get_state("search_intent_model_grain") or [],
            google_trends_anchor=get_state("google_trends_anchor"),
            seo_fit_inputs=get_state("seo_fit_inputs"),
            future_assumption_bundles=get_state("future_assumption_bundles"),
            candidate_a_fit_inputs=(
                get_state("candidate_a_fit_inputs").to_dict()
                if hasattr(get_state("candidate_a_fit_inputs"), "to_dict")
                else get_state("candidate_a_fit_inputs")
            ),
            search_candidate_a_spec=get_state("search_candidate_a_spec")
            or (
                get_state("candidate_a_fit_inputs").get("spec")
                if isinstance(get_state("candidate_a_fit_inputs"), dict)
                else get_state("candidate_a_fit_inputs").spec.to_dict()
                if get_state("candidate_a_fit_inputs") is not None
                else None
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
            canonical_calendar=get_state("canonical_calendar"),
            official_preparation_result=get_state("official_preparation_result"),
            official_capability_report=get_state("official_capability_report"),
            official_prepared_data=get_state("official_prepared_data"),
            official_join_diagnostics=get_state("official_join_diagnostics"),
            standard_activity_model_input=get_state("standard_activity_model_input"),
            standard_outcome_data=get_state("standard_outcome_data"),
            standard_context_data=get_state("standard_context_data"),
            context_variable_metadata=get_state("context_variable_metadata") or [],
            source_domain_semantics=get_state("source_domain_semantics") or [],
            # REQ-EXPMODE-001 (Work Package 2): the governed experiment
            # registry travels with the project - records, declared model
            # uses, compatibility assessments and retained source rows
            # under one record-level schema version. None (omitted) while
            # the registry is empty.
            experiments=_experiments_for_export(),
            # REQ-EVENT-001 (Work Package 1): the governed named-event
            # registry travels with the project - families, factual
            # occurrences and response definitions under one record-level
            # schema version. None (omitted) while the registry is empty.
            named_events=_named_events_for_export(),
        )
    st.success("Durable project bundle built and ready to download.")
    # Read back this bundle's own manifest.json (written by
    # core.persistence.export_project - see the module docstring) rather
    # than re-deriving a second "what's in it" notion here, so the
    # checklist below can never drift from what was actually written.
    #
    # Codex review (PR #348, P1 + P1 follow-up): PROJECT_EXPORT_ROOT/
    # <project_name>.zip was a single shared filesystem path, not
    # session-scoped, on both the read side (re-opened on every later rerun
    # so the checklist/download would survive - a second session's build in
    # between would silently overwrite the file, offering it to this
    # session) and the write side (two concurrent builds of the same project
    # name both targeting this exact path, racing on the write itself,
    # before either session's caching ever got a chance to help). Fixed on
    # both sides: `output_path` above is now a session-unique temporary
    # filename `export_project()` builds to and nothing else ever
    # coincidentally shares, and the bytes/manifest are read into this
    # session's own private state exactly once, right here, before the
    # temporary file is deleted - nothing below this point re-opens
    # `output_path`, and nothing above it is ever shared with another
    # session's build.
    _build_bytes = output_path.read_bytes()
    with zipfile.ZipFile(output_path) as _build_zf:
        _build_manifest = json.loads(_build_zf.read("manifest.json"))
    output_path.unlink(missing_ok=True)
    set_state(
        "export_last_bundle_summary",
        {
            "project_name": project_name,
            "checkpoint": _build_manifest.get("workflow_checkpoint"),
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    set_state("export_last_bundle_bytes", _build_bytes)
    set_state("export_last_bundle_manifest", _build_manifest)
    # Project Export redesign (pass 4, closing the gap passes 2-3 logged but
    # deliberately did not fix): re-run so the "Export & Recovery dashboard"
    # and "Project snapshot" cards above - both computed earlier in this
    # same script run from `export_last_bundle_summary` - stop showing
    # stale pre-build state next to this success message. The checklist and
    # download button that used to live only inside this `if` block (and so
    # would have vanished on this rerun) are rendered below, unconditionally,
    # from this session's own private state this block just wrote - see that
    # block's own comment for why this is safe.
    st.rerun()

# Render the "what's included" checklist and the download control from
# already-persisted, session-private state, not from this button's transient
# scope - this is what makes both survive the `st.rerun()` above (and any
# later rerun this session, e.g. an unrelated widget interaction) instead of
# disappearing the moment the analyst does anything else. Deliberately reads
# the bundle bytes and manifest cached in this session's own `st.session_state`
# rather than re-opening `PROJECT_EXPORT_ROOT/<project_name>.zip` from disk on
# every render: that shared path can be silently overwritten by a different
# session building the same-named project in between reruns, which would
# otherwise leak another analyst's bundle into this session's download
# control (Codex review, PR #348, P1). A session that has lost its cached
# bytes (e.g. after a full app/server restart) degrades to a plain,
# actionable message instead of a crash or a stale/foreign read - the
# session-activity record above is not erased just because the in-memory
# bytes are gone, and stays an honest log of what this session actually did.
if _last_bundle_build:
    _bundle_project_name = _last_bundle_build.get("project_name", project_name)
    _bundle_bytes = get_state("export_last_bundle_bytes")
    _persisted_manifest = get_state("export_last_bundle_manifest")
    if _bundle_bytes and _persisted_manifest:
        with st.expander("What's included in this bundle", expanded=False):
            _render_contains_checklist(_persisted_manifest.get("contains", {}))
        st.download_button(
            "Download project bundle (.zip)",
            _bundle_bytes,
            file_name=f"{_bundle_project_name}.zip",
            mime="application/zip",
            key="download_export_bundle",
        )
    else:
        st.warning(
            "The bundle built this session is no longer available in memory "
            "(for example, after a full app restart). Build the bundle again "
            "to restore the checklist and download link."
        )

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
        if (
            isinstance(imported.get("project_display_name"), str)
            and imported["project_display_name"].strip()
        ):
            set_state("project_name", imported["project_display_name"])
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
        set_state(
            "standard_activity_model_input",
            imported.get("standard_activity_model_input"),
        )
        set_state("standard_outcome_data", imported.get("standard_outcome_data"))
        set_state("standard_context_data", imported.get("standard_context_data"))
        set_state(
            "context_variable_metadata",
            imported.get("context_variable_metadata") or [],
        )
        set_state(
            "source_domain_semantics",
            imported.get("source_domain_semantics") or [],
        )
        _standard_joined = adopted_model_input_frame(
            outcome_data=imported.get("standard_outcome_data"),
            activity_model_input=imported.get("standard_activity_model_input"),
            context_model_input=imported.get("standard_context_data"),
        )
        set_state("standard_joined_data", _standard_joined)
        if _standard_joined is not None:
            if transformed is None:
                transformed = _standard_joined
            set_state("transformed_data_origin", "standard_source_pack")
        else:
            set_state("transformed_data_origin", None)
        set_state("transformed_data", transformed)
        set_state("official_prepared_data", imported.get("official_prepared_data"))
        set_state(
            "official_join_diagnostics", imported.get("official_join_diagnostics")
        )
        set_state(
            "official_prepared_data_fingerprint",
            (
                fingerprint_dataframe(imported["official_prepared_data"])
                if imported.get("official_prepared_data") is not None
                else None
            ),
        )
        set_state("pipeline_steps", imported["pipeline_steps"])
        # Keep the durable preparation boundary separate from the optional
        # Search-grain specification that produced the persisted posterior.
        # Pages that replay the fit use the latter; Model Structure can still
        # recover the complete unsliced configuration after invalidation.
        set_state("prepared_model_spec", imported["model_spec"])
        set_state("fitted_model_spec", imported.get("fitted_model_spec"))
        set_state(
            "model_spec",
            imported.get("fitted_model_spec") or imported["model_spec"],
        )
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
        _resolved_outcome_groups, _outcome_group_warnings = (
            resolve_imported_outcome_groups(imported)
        )
        set_state("outcome_groups", _resolved_outcome_groups)
        _group_objects = [
            OutcomeGroupDefinition.from_dict(value)
            for value in _resolved_outcome_groups
        ]
        _resolved_group_treatments, _group_treatment_warnings = (
            resolve_imported_outcome_group_treatments(
                imported,
                groups=_group_objects,
            )
        )
        set_state("outcome_group_treatments", _resolved_group_treatments)
        _resolved_reconciliation_groups, _reconciliation_warnings = (
            resolve_imported_outcome_reconciliation_groups(
                imported,
                outcome_ids=[
                    value.get("outcome_id")
                    for value in (imported.get("outcome_definitions") or [])
                    if isinstance(value, dict)
                ]
                or None,
            )
        )
        set_state("outcome_reconciliation_groups", _resolved_reconciliation_groups)
        for _outcome_group_warning in (
            _outcome_group_warnings
            + _group_treatment_warnings
            + _reconciliation_warnings
        ):
            st.warning(_outcome_group_warning)
        # Draft import review is session-local.  The durable catalogue above
        # is the source of truth after a bundle restore.
        set_state("outcome_source_draft", None)
        set_state("outcome_source_draft_groups", [])
        set_state("outcome_source_draft_reconciliation_groups", [])
        set_state("outcome_source_import_status", None)
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
        _resolved_pathways, _pathway_warnings = resolve_imported_media_outcome_pathways(
            imported
        )
        set_state("media_outcome_pathways", _resolved_pathways)
        for _pathway_warning in _pathway_warnings:
            st.warning(_pathway_warning)
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
        set_state("search_candidate_a_spec", imported.get("search_candidate_a_spec"))
        set_state("google_trends_anchor", imported.get("google_trends_anchor"))
        set_state("seo_fit_inputs", imported.get("seo_fit_inputs"))
        # REQ-SEARCH-004/005: restore only valid, explicitly persisted custom
        # taxonomy records. The approved minimum is supplied by the taxonomy
        # module; malformed children are quarantined and named.
        _raw_search_intent_groups = imported.get("search_intent_groups") or []
        try:
            _governed_groups = resolve_imported_search_intent_groups(
                _raw_search_intent_groups
            )
            set_state(
                "search_intent_groups",
                [group.to_dict() for group in _governed_groups],
            )
            _resolved_group_versions, _group_version_warnings = (
                resolve_imported_search_intent_group_versions(
                    imported.get("search_intent_group_versions"),
                    current_groups=_governed_groups,
                )
            )
            set_state(
                "search_intent_group_versions",
                _resolved_group_versions,
            )
            set_state(
                "search_intent_model_grain",
                list(
                    resolve_search_intent_model_grain(
                        imported.get("search_intent_model_grain") or (),
                        _governed_groups,
                        imported.get("activity_definitions") or (),
                    )
                ),
            )
        except (TypeError, ValueError) as _taxonomy_exc:
            set_state("search_intent_groups", [])
            set_state("search_intent_group_versions", [])
            set_state("search_intent_model_grain", [])
            # Downstream resumability/readiness/approval checks in this same
            # import (e.g. `current_model_identity_fingerprints`) re-read
            # `imported["search_intent_groups"]` directly, not session state.
            # Leaving the raw malformed collection in `imported` after only
            # clearing session state means those checks re-raise the same
            # error outside this handler, crashing the import after it has
            # already installed the rest of the project. Mirror the
            # sanitized (quarantined-to-empty) session state into `imported`
            # so every later reader sees the same already-validated result.
            imported["search_intent_groups"] = []
            imported["search_intent_group_versions"] = []
            imported["search_intent_model_grain"] = []
            st.warning(
                f"Persisted Search intent taxonomy was quarantined: {_taxonomy_exc}"
            )
        else:
            for _group_version_warning in _group_version_warnings:
                st.warning(_group_version_warning)
        set_state(
            "future_assumption_bundles", imported.get("future_assumption_bundles")
        )
        set_state("candidate_a_fit_inputs", imported.get("candidate_a_fit_inputs"))
        set_state(
            "outcome_valuation_records",
            imported.get("outcome_valuation_records") or [],
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
        # REQ-EXPMODE-001 (Work Package 2): restore the quarantine-checked
        # governed experiment registry. A bundle with no experiments.json
        # (every bundle exported before this capability existed, or an
        # empty registry) resolves to empty lists - "no registry yet"
        # restored as none, never fabricated; malformed records and
        # orphaned model uses are quarantined and named in warnings.
        (
            _resolved_experiment_records,
            _resolved_experiment_uses,
            _resolved_experiment_assessments,
            _resolved_experiment_rows,
            _experiment_warnings,
        ) = resolve_imported_experiments(imported)
        set_state("experiment_records", _resolved_experiment_records)
        set_state("experiment_model_uses", _resolved_experiment_uses)
        set_state(
            "experiment_compatibility_assessments",
            _resolved_experiment_assessments,
        )
        set_state("experiment_evidence_rows", _resolved_experiment_rows)
        for _experiment_warning in _experiment_warnings:
            st.warning(_experiment_warning)
        # REQ-EVENT-001 (Work Package 1): restore the quarantine-checked
        # governed named-event registry. A bundle with no named_events.json
        # (every bundle exported before this capability existed, or an
        # empty registry) resolves to empty lists - "no registry yet"
        # restored as none, never fabricated; malformed records, orphan
        # response definitions and unreviewed family links are named in
        # warnings, and factual occurrence dates are never rewritten.
        (
            _resolved_event_families,
            _resolved_event_occurrences,
            _resolved_event_definitions,
            _named_event_warnings,
        ) = resolve_imported_named_events(imported)
        set_state("named_event_families", _resolved_event_families)
        set_state("named_event_occurrences", _resolved_event_occurrences)
        set_state("named_event_response_definitions", _resolved_event_definitions)
        for _named_event_warning in _named_event_warnings:
            st.warning(_named_event_warning)
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
        set_state("canonical_calendar", imported.get("canonical_calendar"))
        set_state(
            "official_preparation_result",
            imported.get("official_preparation_result"),
        )
        set_state(
            "official_capability_report",
            imported.get("official_capability_report"),
        )
        set_state("migration_review", imported.get("migration_review"))
        # PR 125A: restore the project-level planning dependencies so a
        # resumed session's Scenario Planner selection (and any newly
        # re-saved scenario) matches what was exported, and so a re-export
        # of this same session round-trips the identical policy/context.
        set_state("counterfactual_policy", imported.get("counterfactual_policy"))
        set_state("currency_context", imported.get("currency_context"))
        set_state("fx_rate_set", imported.get("fx_rate_set"))
        set_state("fx_rate_records", imported.get("fx_rate_records") or [])
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
        set_state(
            "prefit_identifiability",
            imported_diagnostics.get("prefit_identifiability"),
        )
        set_state("prefit_screening", imported_diagnostics.get("prefit_screening"))
        set_state(
            "data_support_governed_response_by_channel",
            imported_diagnostics.get("data_support_governed_response_by_channel") or {},
        )
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
                        f"{len(artifact_load_result.malformed)} imported Planning "
                        "Curve(s) failed to verify and are reported below "
                        "- never silently skipped."
                    )
                    for entry in artifact_load_result.malformed:
                        st.caption(f"{entry.artifact_dir.name}: {entry.error}")
                if artifact_load_result.loaded:
                    st.success(
                        f"Restored {len(artifact_load_result.loaded)} Planning "
                        "Curve(s) and verified their stored integrity."
                    )
        if imported["market_spec_config"] is None:
            st.caption(
                "This bundle predates the market-specific redesign - no market descriptors or "
                "media-unit mappings to import. Add them on Activity Mapping / "
                "Market Context if needed."
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
                "Resumability audit passed at "
                f"{_display_checkpoint(resume_audit['checkpoint'])}."
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
                "This bundle is officially resumable at "
                f"{_display_checkpoint(resume_audit['checkpoint'])}."
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
                "or inconsistent prepared data / model structure) - re-run Model Setup's "
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

with SectionCard(
    "Secondary: Excel summary",
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
                    "fitting; this is informational only."
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
    "Secondary: Project report",
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

st.caption(
    "This is the last step in the workflow. Revisit any page from the sidebar to refine the model or plans."
)
