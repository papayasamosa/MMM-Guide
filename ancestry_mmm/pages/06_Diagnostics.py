"""Page 6: model scorecard - convergence, in-sample fit, posterior predictive coverage, plausibility flags, out-of-sample backtest."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    invalidate_governance_evidence,
    format_date,
    format_number,
    dataframe_column_config,
    FIELD_HELP,
    readable_label,
    outcome_display_label,
    model_input_display_label,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_definition_help,
    render_decision_help,
    render_technical_details,
    render_drift_status,
    render_status_badge,
    render_top_line,
    render_primary_concern,
    render_domain_health_rail,
    render_workspace_note,
    badge_html,
)
from ancestry_mmm.application.diagnostics_summary import (
    compute_domain_health,
    compute_top_line_status,
    derive_primary_concern,
)
from ancestry_mmm.core.approval import (
    ApprovalMismatchError,
    ModelApproval,
    ValidationPolicyBlockedError,
    create_policy_backed_model_approval,
    require_matching_approval,
)
from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_by_model_input,
    activity_fit_fingerprint,
)
from ancestry_mmm.core.search_objects import (
    SearchObjectDefinition,
    search_object_fit_fingerprint,
)
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.market_data_capability import check_market_channel_capability
from ancestry_mmm.application.diagnostics_service import (
    DiagnosticsService,
    DiagnosticsInput,
)
from ancestry_mmm.application.validation_service import (
    ValidationService,
    ValidationInput,
)
from ancestry_mmm.core.validation_policy import (
    load_approval_readiness,
    load_threshold_policy,
    readiness_matches_current_evidence,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.causal_graph import (
    CausalGraph,
    current_structural_fingerprint_for_identity,
)
from ancestry_mmm.core.funnel import FunnelLink, funnel_coherence_diagnostics
from ancestry_mmm.core.outcomes import (
    outcome_catalogue_fingerprint_payload,
    resolve_outcome_definitions,
)
from ancestry_mmm.core.pathways import (
    MediaOutcomePathway,
    pathway_catalogue_fingerprint_payload,
    pathways_drift_dataframe,
)
from ancestry_mmm.core.outcome_group_totals import reporting_group_options
from ancestry_mmm.components.charts import (
    create_actual_vs_fitted_chart,
    create_residual_bar_chart,
    create_time_series_chart,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.application.model_fit_service import build_model_for_spec
from ancestry_mmm.core.search_capacity import SEARCH_CANDIDATE_A_ENGINE
from ancestry_mmm.core.predict import extract_posterior_params, predict_mu
from ancestry_mmm.core.market_specific_predict import (
    extract_market_specific_posterior_params,
    predict_mu_market_specific,
)
from ancestry_mmm.data import prepare_fh_modeling_frame
from ancestry_mmm.application.fold_refit_service import (
    run_leakage_safe_fold_refit,
    run_leakage_safe_fold_refit_from_sources,
)
from ancestry_mmm.core.validation_folds import (
    RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
    RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL,
)
from ancestry_mmm.core.estimand_identification import (
    EFFECT_TYPE_DIRECT,
    EFFECT_TYPE_TOTAL,
)
from ancestry_mmm.application.experiment_service import (
    build_compatibility_assessment,
    provenance_for_model,
    register_model_use,
)
from ancestry_mmm.core.experiments import (
    COMPATIBILITY_DIMENSIONS,
    EVIDENCE_MODES,
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
    EVIDENCE_MODE_PRIOR_CALIBRATION,
    CompatibilityAssessment,
    ExperimentRecord,
    ExperimentToModelUse,
)

MODEL_TYPE_LABEL = {
    "shared": "Shared response across markets",
    "market_specific": "Market-specific response with partial pooling",
}

st.set_page_config(
    page_title="Model Diagnostics | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("diagnostics")
render_page_header(
    "diagnostics",
    task_prompt="Is this fit trustworthy enough for approval?",
)
st.caption(
    "A scorecard, not a single headline R-squared - convergence, fit, posterior predictive coverage and plausibility flags together."
)
render_workspace_note(
    "Evidence first",
    "Start with the summary rail, inspect domain detail, then evaluate readiness before approval.",
    kind="governed",
)
render_decision_help(
    "How should I read Diagnostics?",
    controls="Whether the fitted model is trustworthy enough for the next governed step, using convergence, fit, predictive coverage, plausibility, identification, and policy gates.",
    why="Readiness is not the same as a good-looking fit. A model can predict well while effects remain weakly identified, or converge while failing a policy gate.",
    options={
        "Trust summary": "Start with the top line and domain rail to see what needs attention.",
        "Problems": "Inspect warnings and errors for their consequence, then open the relevant evidence domain.",
        "Readiness": "Evaluate the current evidence against the configured policy before deciding whether approval is justified.",
        "Approval": "Approve only when the evidence and known limitations support the intended use; approval is bound to the current fit and evidence.",
    },
    normal_path="Compute evidence, review the trust summary, inspect problems, evaluate readiness, and approve only if justified.",
    downstream="A current readiness and approval are prerequisites for governed results, curves, and planning; stale evidence is not silently reused.",
    invalidates="Changing the fit, policy, model identity, or diagnostic evidence invalidates readiness and approval and requires the workflow to be repeated.",
)
render_definition_help(
    "R-hat",
    "A convergence check comparing variation within and between sampling chains; values close to 1 indicate the chains are behaving consistently.",
)
render_definition_help(
    "effective sample size",
    "An estimate of how much independent information remains in the posterior draws after accounting for autocorrelation.",
)
render_definition_help(
    "posterior predictive coverage",
    "The share of observed outcomes that falls inside the model's posterior predictive interval.",
)

trace = get_state("trace")
frame = get_state("frame")
meta = get_state("model_meta")
if trace is None or frame is None or meta is None:
    render_empty_state(
        "No fitted model yet. Complete Fit Model first.",
        button_label="Go to Fit Model",
        target_key="model_training",
    )
    st.stop()

model_type = get_state("model_type", "shared")

spec_dict = get_state("model_spec")
# WP2.11 item 7 (Residual Explorer): human-readable outcome labels, built
# the same way every other page derives them - resolved once here and
# reused, never a second independent label lookup.
residual_outcome_labels: dict = {}
if spec_dict:
    _spec_for_drift = ModelSpec.from_dict(spec_dict)
    residual_outcome_labels = {
        o.outcome_id: outcome_display_label(o)
        for o in resolve_outcome_definitions(
            get_state("outcome_definitions"),
            _spec_for_drift.segment_outcomes,
            _spec_for_drift.segment_ltv,
        )
    }
    render_drift_status(
        resolve_outcome_definitions(
            get_state("outcome_definitions"),
            _spec_for_drift.segment_outcomes,
            _spec_for_drift.segment_ltv,
        ),
        meta,
    )
    _current_pathways = [
        MediaOutcomePathway.from_dict(p)
        for p in (get_state("media_outcome_pathways") or [])
    ]
    _pathway_drift_df = pathways_drift_dataframe(_current_pathways, meta)
    if not _pathway_drift_df.empty:
        _changed_pathways = _pathway_drift_df[
            _pathway_drift_df["drift_status"] != "Fitted and current"
        ]
        if not _changed_pathways.empty:
            st.warning(
                f"{len(_changed_pathways)} media-outcome pathway(s) differ from this fit's saved "
                "pathway setup. These results no longer reflect the pathways currently configured "
                "on Model Structure. Refit the model before relying on these diagnostics or using "
                "the results downstream."
            )

posterior_params = get_state("posterior_params")
model_spec_dict = get_state("model_spec")
prior_config = get_state("prior_config") or {}
dna_lag_weeks = get_state("dna_lag_weeks", 4)
model_run_id = get_state("model_run_id")
activity_items = get_state("activity_definitions") or []
activity_definitions = [ActivityDefinition.from_dict(item) for item in activity_items]
search_objects = [
    SearchObjectDefinition.from_dict(item)
    for item in (get_state("search_objects") or [])
]
coverage_matrix_dict = get_state("variable_coverage_matrix")

# REQ-EXPMODE-001 (Work Package 2): the governed experiment registry -
# adopted records, declared model uses and their compatibility assessments.
# Loaded once here and reused for both the scorecard input and the
# experiment evidence section below; never two divergent reads.
experiment_records = [
    ExperimentRecord.from_dict(item) for item in (get_state("experiment_records") or [])
]
experiment_uses = [
    ExperimentToModelUse.from_dict(item)
    for item in (get_state("experiment_model_uses") or [])
]
experiment_assessments = [
    CompatibilityAssessment.from_dict(item)
    for item in (get_state("experiment_compatibility_assessments") or [])
]

# PR 79A (work package B): the current model run's identity is constructed
# once, here, and reused as this single object for diagnostics, validation
# readiness and model approval below - it must never be recalculated with
# different inputs later on this page, or diagnostics/readiness/approval
# can silently drift apart on what they each think "the current model" is.
current_model_identity: "ModelIdentity | None" = None
if model_run_id and posterior_params is not None and model_spec_dict is not None:
    current_model_identity = ModelIdentity(
        model_run_id=model_run_id,
        data_fingerprint=fingerprint_dataframe(frame["df"]),
        model_spec_fingerprint=fingerprint_model_spec(
            model_spec_dict,
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
                    consumed_model_input_columns=model_spec_dict.get("channels") or [],
                )
                if search_objects
                else None
            ),
            variable_coverage_fingerprint=(
                VariableCoverageMatrix.from_dict(coverage_matrix_dict).fingerprint()
                if coverage_matrix_dict
                else None
            ),
            official_preparation_evidence=get_state("official_preparation_result"),
        ),
        posterior_fingerprint=fingerprint_posterior(posterior_params),
    )
# Dict view of the same identity object (never recomputed independently)
# for the model-approval section below, which binds approvals by keyword.
current_identity = asdict(current_model_identity) if current_model_identity else None

with st.container(border=True):
    st.markdown("### Diagnostics state")
    st.caption(
        "Read-only state for this trained run. Compute the scorecard, evaluate the policy, then decide whether approval is justified."
    )
    summary_cols = st.columns(4)
    summary_cols[0].metric(
        "Model type", "Market-specific" if model_type == "market_specific" else "Shared"
    )
    summary_cols[1].metric("Fit state", "Trained")
    summary_cols[2].metric(
        "Scorecard", "Computed" if get_state("scorecard") else "Not computed"
    )
    summary_cols[3].metric(
        "Readiness",
        "Evaluated" if get_state("validation_service_result") else "Not evaluated",
    )

st.markdown("---")
st.markdown("### Scorecard action")
st.caption(
    "Compute the canonical evidence once. The summary rail and domain detail below read from that same stored artefact."
)
if st.button("Compute scorecard", type="primary"):
    with st.spinner("Computing diagnostics..."):
        diag_service = DiagnosticsService()
        diag_input = DiagnosticsInput(
            trace=trace,
            frame=frame,
            meta=meta,
            model_type=model_type,
            model_identity=current_model_identity,
            raw_model_spec=(
                ModelSpec.from_dict(model_spec_dict) if model_spec_dict else None
            ),
            coverage_matrix=(
                VariableCoverageMatrix.from_dict(coverage_matrix_dict)
                if coverage_matrix_dict
                else None
            ),
            # Review finding: the market_channel_capability gate must not
            # trust a coverage matrix that was built against a different
            # (or since-changed) joined dataset - mirrors the freshness
            # check already surfaced on Model Config/Data Coverage, but
            # threaded through so it is authoritative for the official gate,
            # not merely a page-level warning.
            coverage_matrix_built_against_fingerprint=get_state(
                "variable_coverage_matrix_built_against_fingerprint"
            ),
            joined_dataframe_fingerprint=fingerprint_dataframe(frame["df"]),
            # REQ-EXPMODE-001 (Work Package 2): populate the schema-v8
            # experiment section from the real saved project registry - one
            # provenance report per model identity, per experiment, never
            # averaged. None when the current model has no registered uses,
            # so the section stays explicitly not_applicable rather than a
            # fabricated empty report.
            experiment_provenance_report=(
                provenance_for_model(
                    experiment_records,
                    experiment_uses,
                    model_id=current_model_identity.model_run_id,
                    model_version=current_model_identity.model_spec_fingerprint,
                )
                if current_model_identity is not None
                else None
            ),
        )
        diag_result = diag_service.evaluate(diag_input)
        scorecard = diag_result.scorecard
        set_state("scorecard", scorecard)
        set_state("diagnostics_artefact", diag_result.diagnostics_artefact)
        set_state("diag_result", diag_result)
        # PR 88A: a freshly computed artefact invalidates any readiness/
        # approval evaluated against the previous one, in the same action -
        # not left for the next rerun's staleness check to catch.
        invalidate_governance_evidence()
    st.success("Scorecard computed.")

# Retrieve artefact for governance display
diag_artefact = get_state("diagnostics_artefact")
diag_result = get_state("diag_result")
scorecard = get_state("scorecard")

# --- Phase 5 (REQ-VAL-001): resolve the current policy and readiness once,
# here - reused by both the new top-line summary/domain-health rail below
# and the "Validation readiness" section further down, so the two can never
# disagree about what "current" readiness means. This is exactly the same
# staleness check that section has always performed (a stored readiness
# whose policy/model-identity/diagnostics-artefact fingerprints no longer
# match is never treated as current); it is only evaluated once now,
# earlier, instead of being duplicated further down the page.
validation_policy_dict = get_state("validation_policy")
_current_policy, _policy_config_error = load_threshold_policy(validation_policy_dict)

render_technical_details(
    details={
        "Model run ID": model_run_id or "Unavailable",
        "Model identity fingerprint": current_model_identity.fingerprint()
        if current_model_identity
        else "Unavailable",
        "Diagnostics evidence ID": getattr(diag_artefact, "artefact_id", "Unavailable")
        if diag_artefact
        else "Not computed",
        "Diagnostics evidence fingerprint": diag_artefact.fingerprint()
        if diag_artefact
        else "Not computed",
        "Validation policy fingerprint": _current_policy.fingerprint()
        if _current_policy
        else "Unavailable",
        "Technical boundary": "These identifiers bind diagnostics, readiness, and approval to the same fit. They are shown here for audit and recovery, not as the routine decision cue.",
    }
)

validation_service_result = get_state("validation_service_result")
approval_readiness_dict = get_state("approval_readiness")
_readiness_was_invalidated = False
if approval_readiness_dict:
    # PR 88A: fail-closed - a malformed stored readiness is treated as
    # absent (never current) rather than crashing the page.
    _stored_readiness_obj, _stored_readiness_error = load_approval_readiness(
        approval_readiness_dict
    )
    _evidence_current = (
        _stored_readiness_error is None
        and diag_artefact is not None
        and _current_policy is not None
        and current_model_identity is not None
        and readiness_matches_current_evidence(
            _stored_readiness_obj,
            policy_fingerprint=_current_policy.fingerprint(),
            model_identity_fingerprint=current_model_identity.fingerprint(),
            diagnostic_artefact_fingerprint=diag_artefact.fingerprint(),
        )
    )
    if not _evidence_current:
        invalidate_governance_evidence()
        validation_service_result = None
        _readiness_was_invalidated = True

# REQ-COVERAGE-001 S6: the same engine-capability check the Model approval
# section below displays in detail, resolved here too so the top-line
# summary/domain-health rail's "Coverage capability" row can use it -
# never a second, divergent computation of the same check.
_capability_result = None
if model_spec_dict is not None:
    _capability_spec = ModelSpec.from_dict(model_spec_dict)
    _capability_result = check_market_channel_capability(
        _capability_spec.markets,
        _capability_spec.channels,
        VariableCoverageMatrix.from_dict(coverage_matrix_dict)
        if coverage_matrix_dict
        else None,
    )

# A placeholder, not an immediate render: "Evaluate readiness" (further
# down this same script) can mutate validation_service_result/
# approval_readiness later in this same run. Rendering here immediately
# would use the pre-click value for that one run (Streamlit reruns
# top-to-bottom once per interaction; a later mutation doesn't retroactively
# update code that already ran above it). st.empty() reserves this visual
# slot at the top of the page now; _render_summary_into() (below) fills it
# with the freshest state once every same-run mutation this page can make
# has already happened - so the top-line answer is never one click behind.
_summary_slot = st.empty()


def _render_summary_into(slot) -> None:
    current_readiness = (
        get_state("validation_service_result").readiness
        if get_state("validation_service_result")
        else None
    )
    with slot.container():
        render_top_line(
            compute_top_line_status(
                readiness=current_readiness, scorecard_computed=bool(scorecard)
            )
        )
        render_domain_health_rail(
            compute_domain_health(
                scorecard=scorecard,
                diag_artefact=diag_artefact,
                capability_result=_capability_result,
                readiness=current_readiness,
                policy=_current_policy,
            )
        )
        render_primary_concern(
            derive_primary_concern(
                readiness=current_readiness,
                diag_artefact=diag_artefact,
                scorecard=scorecard,
                capability_result=_capability_result,
            )
        )


# First fill, using whatever readiness evidence already exists as of the
# start of this run (correct for every run except one where "Evaluate
# readiness" is about to be clicked later in this exact script pass - the
# second fill below, after that button's handler, corrects that case).
_render_summary_into(_summary_slot)


def _residual_outcome_label(outcome_id: str, outcome_labels: dict) -> str:
    return outcome_labels.get(outcome_id, readable_label(outcome_id))


def _residual_group_view(
    market_df: pd.DataFrame, group, group_id: str
) -> "pd.DataFrame | None":
    """WP2.11 item 6.1/7.1: an Overall/group view for a governed semantic
    outcome group, summing only outcomes an analyst has explicitly declared
    additive in compatible units (`core.outcome_group_totals`'s own
    "components_joint"/"total_only" gate - never an arbitrary sum of
    whatever outcomes happen to be fitted). The expected-mean credible
    interval is deliberately dropped for a group total: independently
    summing per-outcome interval bounds is not a valid joint interval, and
    fabricating one is explicitly against WP2.11 item 6's constraint."""
    member_df = market_df[market_df["outcome_id"].isin(group.member_outcome_ids)]
    if member_df.empty:
        return None
    agg = member_df.groupby("date", as_index=False)[["actual", "predicted"]].sum(
        min_count=1
    )
    agg["residual"] = agg["actual"] - agg["predicted"]
    agg["abs_residual"] = agg["residual"].abs()
    agg = agg.sort_values("date").reset_index(drop=True)
    agg["residual_rank_pct"] = agg["residual"].rank(pct=True)
    agg["abs_residual_rank_pct"] = agg["abs_residual"].rank(pct=True)
    agg["market"] = market_df["market"].iloc[0]
    agg["outcome_id"] = group_id
    return agg


def _render_residual_explorer(payload: dict, meta, outcome_labels: dict) -> None:
    """WP2.11 item 7: the Residual Explorer. Reads only the canonical
    `residual_series`/`shared_residual_evidence` evidence already computed
    by `DiagnosticsService.evaluate()` (item 6) - never recomputes a
    residual independently on this page."""
    residual_df = pd.DataFrame(payload.get("rows") or [])
    if residual_df.empty:
        st.info("No residual-series rows available.")
        return

    markets = [m for m in meta.markets if m in set(residual_df["market"])]
    if not markets:
        markets = sorted(residual_df["market"].unique().tolist())
    outcome_ids = [
        oid for oid in meta.outcome_ids if oid in set(residual_df["outcome_id"])
    ]

    outcome_groups = getattr(meta, "outcome_groups_at_fit", None) or []
    outcome_group_treatments = (
        getattr(meta, "outcome_group_treatments_at_fit", None) or []
    )
    groups_by_id = {g.group_id: g for g in outcome_groups}
    group_options = reporting_group_options(
        outcome_ids, outcome_groups, outcome_group_treatments
    )

    # 7.1 controls
    c1, c2 = st.columns(2)
    if len(markets) > 1:
        selected_market = c1.selectbox(
            "Market", markets, key="residual_explorer_market"
        )
    else:
        selected_market = markets[0]
        c1.caption(f"Market: {selected_market}")

    view_options: dict = {}
    for oid in outcome_ids:
        view_options[
            f"Individual outcome · {_residual_outcome_label(oid, outcome_labels)}"
        ] = (
            "outcome",
            oid,
        )
    for group_id, label in group_options:
        view_options[f"Outcome group · {label}"] = ("group", group_id)
    view_label = c2.selectbox(
        "Outcome / view", list(view_options), key="residual_explorer_view"
    )
    view_kind, view_key = view_options[view_label]

    market_df = residual_df[residual_df["market"] == selected_market].copy()

    if view_kind == "outcome":
        view_df = market_df[market_df["outcome_id"] == view_key].sort_values("date")
        has_interval = (
            "expected_mean_lower" in view_df.columns
            and view_df["expected_mean_lower"].notna().any()
        )
    else:
        view_df = _residual_group_view(market_df, groups_by_id[view_key], view_key)
        has_interval = False
        if view_df is None:
            st.info("No rows available for this outcome group in this market.")
            return
        st.caption(
            "Outcome-group total: actual and predicted are summed across the "
            "group's declared additive member outcomes (compatible units "
            "only, per the group's own reporting definition). The "
            "expected-mean credible interval is not shown for group totals - "
            "independently summing per-outcome interval bounds would not "
            "represent a valid joint interval."
        )

    if view_df.empty:
        st.info("No residual-series rows available for this selection.")
        return

    comparison_choices = [
        oid for oid in outcome_ids if not (view_kind == "outcome" and oid == view_key)
    ]
    comparison_ids = st.multiselect(
        "Compare with other outcomes (optional - overlays residuals only, "
        "no totals are formed)",
        comparison_choices,
        default=[],
        format_func=lambda oid: _residual_outcome_label(oid, outcome_labels),
        key="residual_explorer_compare",
    )

    # 7.2 actual vs modelled chart
    st.plotly_chart(
        create_actual_vs_fitted_chart(
            view_df["date"].to_numpy(),
            view_df["actual"].to_numpy(dtype=float),
            view_df["predicted"].to_numpy(dtype=float),
            lower_values=(
                view_df["expected_mean_lower"].to_numpy(dtype=float)
                if has_interval
                else None
            ),
            upper_values=(
                view_df["expected_mean_upper"].to_numpy(dtype=float)
                if has_interval
                else None
            ),
            title=f"Actual vs modelled · {selected_market} · {view_label}",
        ),
        width="stretch",
    )
    if has_interval:
        st.caption(
            f"Shaded band is the {view_df['expected_mean_credible_mass'].iloc[0]:.0%} "
            "credible interval for the fitted expected mean - not a "
            "posterior predictive interval for a simulated outcome draw."
        )

    # 7.3 residual chart
    st.markdown("##### Residuals by week")
    st.caption(
        "residual = actual - predicted. **Positive** = the model "
        "under-predicted that week; **negative** = the model over-predicted."
    )
    abs_threshold = (
        view_df["abs_residual"].quantile(0.9)
        if len(view_df) > 1
        else view_df["abs_residual"].max()
    )
    highlight_mask = (view_df["abs_residual"] >= abs_threshold).to_numpy()
    st.plotly_chart(
        create_residual_bar_chart(
            view_df["date"].to_numpy(),
            view_df["residual"].to_numpy(dtype=float),
            highlight_mask=highlight_mask,
            title=f"Residuals · {selected_market} · {view_label} (diamonds mark the largest misses)",
        ),
        width="stretch",
    )

    if comparison_ids:
        base_label = view_label
        base_series = view_df[["date", "residual"]].assign(series=base_label)
        compare_df = market_df[market_df["outcome_id"].isin(comparison_ids)].copy()
        compare_df["series"] = compare_df["outcome_id"].map(
            lambda oid: (
                f"Individual outcome · {_residual_outcome_label(oid, outcome_labels)}"
            )
        )
        overlay_long = pd.concat(
            [base_series, compare_df[["date", "residual", "series"]]],
            ignore_index=True,
        )
        overlay_wide = (
            overlay_long.pivot_table(index="date", columns="series", values="residual")
            .reset_index()
            .sort_values("date")
        )
        st.plotly_chart(
            create_time_series_chart(
                overlay_wide,
                "date",
                [c for c in overlay_wide.columns if c != "date"],
                title="Residual comparison across outcomes",
            ),
            width="stretch",
        )

    # 7.4 biggest misses table
    st.markdown("##### Biggest misses")
    st.caption(
        "Which weeks did the model get most wrong? Ranked by absolute "
        "residual by default; every row is available, not only a fixed "
        "top 10."
    )
    sort_choice = st.radio(
        "Sort",
        ["Largest absolute residual", "Most under-predicted", "Most over-predicted"],
        horizontal=True,
        key="residual_explorer_sort",
    )
    table_df = view_df[
        [
            "date",
            "actual",
            "predicted",
            "residual",
            "abs_residual",
            "abs_residual_rank_pct",
        ]
    ].copy()
    table_df.insert(1, "outcome", view_label)
    if sort_choice == "Largest absolute residual":
        table_df = table_df.sort_values("abs_residual", ascending=False)
    elif sort_choice == "Most under-predicted":
        table_df = table_df.sort_values("residual", ascending=False)
    else:
        table_df = table_df.sort_values("residual", ascending=True)
    st.dataframe(
        table_df.reset_index(drop=True),
        width="stretch",
        column_config=dataframe_column_config(table_df),
    )

    # 7.5 shared residual weeks
    shared_evidence = payload.get("shared_residual_evidence") or {}
    st.markdown("##### Shared residual weeks")
    st.caption(
        "Weeks where two or more outcomes were simultaneously among their "
        "own largest absolute residuals in this market - a co-occurrence "
        "pattern, not a causal claim. Several outcomes being under- or "
        "over-predicted in the same week may indicate a common demand "
        "factor, event, source change, or missing context worth "
        "investigating; this view does not identify which, and nothing "
        "here is added to the model automatically."
    )
    shared_weeks = [
        w
        for w in (shared_evidence.get("shared_extreme_weeks") or [])
        if w.get("market") == selected_market
    ]
    if not shared_weeks:
        st.info("No shared extreme-residual weeks found for this market.")
    else:
        shared_df = pd.DataFrame(
            [
                {
                    "date": w["date"],
                    "outcomes": ", ".join(
                        _residual_outcome_label(oid, outcome_labels)
                        for oid in w["outcomes"]
                    ),
                    "same_sign": w["all_same_sign"],
                }
                for w in shared_weeks
            ]
        ).sort_values("date")
        st.dataframe(
            shared_df, width="stretch", column_config=dataframe_column_config(shared_df)
        )
    pairwise = [
        p
        for p in (shared_evidence.get("pairwise_correlation") or [])
        if p.get("market") == selected_market
    ]
    if pairwise:
        pairwise_df = pd.DataFrame(
            [
                {
                    "outcome_a": _residual_outcome_label(
                        p["outcome_a"], outcome_labels
                    ),
                    "outcome_b": _residual_outcome_label(
                        p["outcome_b"], outcome_labels
                    ),
                    "residual_correlation": p["residual_correlation"],
                }
                for p in pairwise
            ]
        )
        st.dataframe(
            pairwise_df,
            width="stretch",
            column_config=dataframe_column_config(pairwise_df),
        )


st.markdown("### Full diagnostic detail")
st.caption(
    "Detail behind the summary above, grouped by evidence domain - not "
    "rendered flat and simultaneously. A domain's detail here is the same "
    "canonical evidence the rail above reads; nothing below recomputes it "
    "separately."
)
if scorecard:
    tab_conv, tab_fit, tab_ppc, tab_plaus, tab_ident, tab_candidate_a = st.tabs(
        [
            "Convergence",
            "In-sample fit & error metrics",
            "Posterior predictive coverage",
            "Plausibility flags",
            "Identification & collinearity",
            "Candidate A Search",
        ]
    )
    with tab_conv:
        conv = scorecard["convergence"]
        c1, c2, c3, c4 = st.columns(4)
        _max_rhat = conv["max_rhat"]
        # UX-019 (overnight UI/UX review, third pass, critic pass): Min ESS
        # right next to this already handles a NaN value gracefully (blank,
        # via format_number, a few lines below) - Max R-hat instead ran
        # straight through an f-string, which renders NaN as the bare
        # literal text "nan" (e.g. a single-chain run, or the same
        # zero-variance-chain case core.models.py already documents for
        # R-hat/ESS). Matching the sibling metric's own convention here
        # rather than introducing a new one; the "not converged" st.warning
        # below already explains the consequence, this only removes the
        # raw technical string.
        c1.metric(
            "Max R-hat",
            "Not available" if _max_rhat != _max_rhat else f"{_max_rhat:.3f}",
            help="Should be < 1.01. Not available when R-hat cannot be computed for this run.",
        )
        _min_ess = conv["min_ess"]
        # round() raises ValueError on NaN (e.g. a degenerate/zero-variance
        # chain's ESS) - only skip the round() step for that case, never
        # fabricate 0; format_number renders a plain NaN safely either way.
        _min_ess_display = format_number(
            _min_ess if _min_ess != _min_ess else round(_min_ess)
        )
        c2.metric(
            "Min ESS",
            _min_ess_display,
            help="Effective sample size; higher is better",
        )
        c3.metric("Divergences", format_number(conv["divergences"]))
        c4.metric("Converged", "Yes" if conv["converged"] else "No")
        if not conv["converged"]:
            st.warning(
                "Convergence diagnostics are outside typical thresholds. Consider more draws/tune, "
                "a higher target_accept, or simplifying the hierarchy before trusting these results."
            )

    with tab_fit:
        st.markdown("#### In-sample fit")
        st.caption(
            "R-squared and MAPE per market x outcome, comparing the posterior-mean "
            "fit to actuals. A good in-sample fit does not by itself mean channel "
            "effects are separable - see Identification & collinearity for that."
        )
        fit_df = pd.DataFrame(scorecard["in_sample_fit"])
        st.dataframe(
            fit_df, width="stretch", column_config=dataframe_column_config(fit_df)
        )

        st.markdown("#### Error metrics & residual temporal structure")
        st.caption(
            "Error metrics: MAE/RMSE (magnitude), sMAPE/WAPE (percentage, "
            "volume-weighted) and bias (systematic over/under-prediction) "
            "alongside R-squared/MAPE above - plus lag-1 autocorrelation and "
            "the Durbin-Watson statistic on the residuals, evidence of "
            "unexplained temporal structure (no blocking threshold is applied "
            "here; an approved policy decides thresholds separately). Rendered "
            "from the canonical diagnostics artefact - never recomputed "
            "separately from it."
        )
        st.caption(
            "Residual temporal evidence is reported per market x outcome, "
            "computed within each market's own chronological slice - the "
            "model frame is multi-market, so lag-1 autocorrelation/"
            "Durbin-Watson are never computed across a market boundary. Every "
            "market is shown; no overall figure is derived by concatenating "
            "markets."
        )
        error_metrics_section = diag_artefact.error_metrics if diag_artefact else None
        residual_section = diag_artefact.residual_diagnostics if diag_artefact else None
        if (
            error_metrics_section is None
            or error_metrics_section.status == "not_computed"
        ):
            st.info(
                error_metrics_section.error
                if error_metrics_section is not None and error_metrics_section.error
                else "Not computed. Click 'Compute scorecard' above."
            )
        elif error_metrics_section.status == "failed":
            st.error(f"Error metrics failed: {error_metrics_section.error}")
        else:
            error_df = pd.DataFrame(error_metrics_section.payload)
            st.dataframe(
                error_df,
                width="stretch",
                column_config=dataframe_column_config(error_df),
            )
        if residual_section is not None and residual_section.status == "computed":
            residual_df = pd.DataFrame(residual_section.payload)
            st.dataframe(
                residual_df,
                width="stretch",
                column_config=dataframe_column_config(residual_df),
            )
        elif residual_section is not None and residual_section.status == "failed":
            st.error(f"Residual temporal diagnostics failed: {residual_section.error}")

        st.markdown("---")
        st.markdown("#### Residuals over time (Residual Explorer)")
        st.caption(
            "One row per market x week x outcome, read directly from the "
            "canonical residual-series evidence above - never recomputed "
            "on this page. This is additive to the aggregate residual "
            "temporal evidence above; it never replaces it."
        )
        residual_series_section = (
            diag_artefact.residual_series if diag_artefact else None
        )
        if (
            residual_series_section is None
            or residual_series_section.status == "not_computed"
        ):
            st.info(
                residual_series_section.error
                if residual_series_section is not None and residual_series_section.error
                else "Not computed. Click 'Compute scorecard' above."
            )
        elif residual_series_section.status == "failed":
            st.error(f"Residual series failed: {residual_series_section.error}")
        else:
            _render_residual_explorer(
                residual_series_section.payload, meta, residual_outcome_labels
            )

    with tab_ppc:
        st.caption(
            "% of actual observations falling inside the posterior predictive credible interval - should be close to the target %."
        )
        ppc_df = pd.DataFrame(scorecard["ppc_coverage"])
        st.dataframe(
            ppc_df, width="stretch", column_config=dataframe_column_config(ppc_df)
        )

    with tab_plaus:
        flags = scorecard["plausibility_flags"]
        if not flags:
            st.info("No plausibility flags raised.")
        else:
            for f in flags:
                (st.warning if f["level"] == "warning" else st.error)(
                    f"**{f.get('channel', '')}**: {f['message']}"
                )

    with tab_ident:
        st.caption(
            "Whether this fit's channel coefficients are trustworthy enough to plan against at all - "
            "independent of convergence, in-sample fit or PPC coverage above, since a model can score "
            "well on all three while still having two channels whose effects the data can't tell apart. "
            "A leave-one-channel-out refit sensitivity check is not run "
            "here (it needs a full model refit per channel, too slow for an interactive page); the three "
            "signals below need no refit."
        )
        # PR 82B: rendered from the canonical artefact section only - the page
        # never calls identification_report()/channel_spend_correlation_matrix()/
        # design_matrix_condition_number()/posterior_coefficient_stability()
        # directly, so displayed evidence and artefact evidence can never
        # diverge (DiagnosticsService computes each of these exactly once).
        ident_section = diag_artefact.identification if diag_artefact else None
        if ident_section is None or ident_section.status == "not_computed":
            st.info("Not computed. Click 'Compute scorecard' above.")
        elif ident_section.status == "failed":
            st.error(f"Identification diagnostics failed: {ident_section.error}")
        else:
            id_flags = ident_section.payload["flags"]
            if not id_flags:
                st.info("No multicollinearity or weak-identification flags raised.")
            else:
                # Overnight UI/UX pass (2026-08-29): these flags are
                # analyst-review evidence, not a validation-policy gate (no
                # gate reads them - see core/validation_policy.py), so they
                # are never shown with the blocking-error treatment used
                # elsewhere on this page for a genuine stop condition (e.g.
                # "Identification diagnostics failed" above). A "severe"
                # flag is still distinguished from an "elevated" one by its
                # own message wording, not by escalating colour/icon beyond
                # warning - do not imply exclusion is required (Section 11).
                st.caption(
                    "These are statistical review signals, not a blocking check - "
                    "review the highlighted channels before relying on their "
                    "individual effects; do not exclude a channel solely because "
                    "of this diagnostic unless the governed methodology says to."
                )
                for f in id_flags:
                    st.warning(f"**{f['channel']}**: {f['message']}")

            with st.expander("Channel spend correlation matrix"):
                corr_df = pd.DataFrame(ident_section.payload["correlation_matrix"]).T
                st.dataframe(
                    corr_df,
                    width="stretch",
                    column_config=dataframe_column_config(corr_df),
                )

            with st.expander(
                "Design matrix condition number & posterior coefficient stability"
            ):
                cond = ident_section.payload["condition_number"]
                st.metric(
                    "Condition number",
                    f"{cond:,.1f}" if isinstance(cond, (int, float)) else str(cond),
                    help="Elevated above ~30, severe above ~100 - the standard econometric rule-of-thumb thresholds.",
                )
                stab_section = diag_artefact.coefficient_stability
                if stab_section.status == "computed":
                    stability_df = pd.DataFrame(stab_section.payload)
                    st.dataframe(
                        stability_df,
                        width="stretch",
                        column_config=dataframe_column_config(stability_df),
                    )
                elif stab_section.status == "failed":
                    st.error(f"Coefficient stability failed: {stab_section.error}")

    with tab_candidate_a:
        st.caption(
            "Candidate A Search mediation/capacity evidence (REQ-SEARCH-002) - "
            "rendered from the canonical artefact section only, never "
            "recomputed separately here. This evidence supplies one input to "
            "the official-use gate; it is not itself an official-use, "
            "planning, or optimisation approval."
        )
        sc_section = diag_artefact.search_capacity if diag_artefact else None
        if sc_section is None or sc_section.status == "not_applicable":
            st.info(
                "Not applicable - this fit did not use the Candidate A Search engine."
            )
        elif sc_section.status == "not_computed":
            st.info(
                sc_section.error or "Not computed. Click 'Compute scorecard' above."
            )
        elif sc_section.status == "failed":
            st.error(
                f"Candidate A Search capacity diagnostics failed: {sc_section.error}"
            )
        else:
            for w in sc_section.warnings:
                st.warning(w)
            summary = sc_section.payload["posterior_summary"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(
                "Mean latent demand", format_number(summary["mean_latent_demand"])
            )
            c2.metric(
                "Mean captured demand",
                format_number(summary["mean_total_captured_demand"]),
            )
            c3.metric(
                "P(cap binding)",
                f"{summary['cap_binding_probability_mean']:.1%}",
            )
            c4.metric("Max R-hat (Search params)", f"{summary['rhat_max']:.3f}")
            st.caption(
                f"Reconciliation error (captured + unmet vs. latent demand, "
                f"posterior mean): {summary['reconciliation_max_abs_error']:.4g}"
            )
            with st.expander("Capture shares & outcome betas"):
                st.json(
                    {
                        "capture_share_mean": summary["capture_share_mean"],
                        "demand_media_beta_mean": summary["demand_media_beta_mean"],
                        "paid_capture_outcome_beta": summary[
                            "paid_capture_outcome_beta"
                        ],
                        "organic_capture_outcome_beta": summary[
                            "organic_capture_outcome_beta"
                        ],
                        "direct_navigation_capture_outcome_beta": summary[
                            "direct_navigation_capture_outcome_beta"
                        ],
                    }
                )
            if sc_section.payload.get("use_gate") is not None:
                use_gate = sc_section.payload["use_gate"]
                st.markdown("#### Official-use gate")
                st.write(
                    f"Official use eligible: **{use_gate['official_use_eligible']}**"
                )
                if use_gate["blocking_reasons"]:
                    for reason in use_gate["blocking_reasons"]:
                        st.warning(reason)
            st.error(
                "Search planning and cap optimisation remain disabled "
                "regardless of this evidence (REQ-SEARCH-002) - see "
                "REPO_REVIEW_AND_NEXT_STEPS.md for current status."
            )
else:
    st.info("Compute the scorecard above to see full diagnostic detail by domain.")

st.markdown("### Validation readiness")
st.caption(
    "Evaluate diagnostics against a validation policy. This shows which gates pass, "
    "fail, or need review — and the overall approval readiness state."
)

# PR 79A (WP9): state contract - "validation_service_result" holds the full
# ValidationService wrapper (readiness object, errors, warnings) for this
# page's own transient UI messages; "approval_readiness" holds only the
# serialised (JSON-safe dict) ApprovalReadiness domain object, which is what
# any other page or persistence layer should read - never the wrapper
# itself under an "*_readiness" name.
#
# Phase 5 (REQ-VAL-001): policy loading and the staleness check below were
# already evaluated once, earlier on this page (right after "Compute
# scorecard"), so the new top-line summary/domain-health rail could use
# them - `_current_policy`, `_policy_config_error`, `validation_service_result`
# and `_readiness_was_invalidated` are reused here as-is, never recomputed a
# second time (which risked the two disagreeing about what "current"
# readiness means).
if _readiness_was_invalidated:
    st.info(
        "Previously evaluated readiness no longer matches the current policy, "
        "model, or diagnostics evidence - click 'Evaluate readiness' again."
    )

if st.button("Evaluate readiness", type="secondary"):
    with st.spinner("Evaluating policy gates..."):
        if diag_artefact is None:
            st.error("Compute the scorecard first.")
        elif _policy_config_error is not None:
            st.error(
                "The configured validation policy is malformed and cannot be "
                f"evaluated: {_policy_config_error}. Fix the policy "
                "configuration before evaluating readiness."
            )
        elif _current_policy is None:
            # PR 79A (WP7): no zero-gate default policy. A policy with no
            # gates would trivially report overall_ready=True (nothing to
            # fail), which is not "ready" - it is "nothing was checked".
            st.warning(
                "No validation policy is configured for this project. "
                "Readiness cannot be evaluated against an empty policy - "
                "configure a validation policy before evaluating official "
                "readiness."
            )
        else:
            policy = _current_policy
            val_service = ValidationService()
            val_input = ValidationInput(
                trace=trace,
                frame=frame,
                meta=meta,
                policy=policy,
                diagnostics_artefact=diag_artefact,
                model_type=model_type,
                model_identity=current_model_identity,
                # PR 82B: readiness evaluated here feeds policy-backed model
                # approval below - official evidence only, never a live
                # recomputation standing in for missing canonical evidence.
                evidence_mode="official_canonical",
            )
            val_result = val_service.evaluate_readiness(val_input)
            set_state("validation_service_result", val_result)
            set_state("approval_readiness", val_result.readiness_dict)
            # PR 88A: persist the full per-gate evidence list this readiness
            # was evaluated from - previously only the aggregate
            # approval_readiness dict was ever written to session state, so
            # a project bundle's validation_results was always None even
            # after a real "Evaluate readiness" click.
            set_state("validation_results", [r.to_dict() for r in val_result.results])
            # Phase 5 (REQ-VAL-001): re-fill the top-line/domain-rail summary
            # placeholder now that readiness has just been evaluated in this
            # same run - reads session state fresh (not the possibly-stale
            # `validation_service_result` local variable captured earlier in
            # this script, before this click's own mutation), so the summary
            # never shows a click-behind "not yet evaluated" state.
            _render_summary_into(_summary_slot)

if validation_service_result:
    rd = validation_service_result.readiness
    if rd:
        st.markdown(
            f"### {badge_html('ready' if rd.overall_ready else 'blocked')} "
            f"Overall readiness: **{'Ready' if rd.overall_ready else 'Not ready'}**",
            unsafe_allow_html=True,
        )
        if rd.lifecycle_issues:
            for li in rd.lifecycle_issues:
                st.warning(f"Policy lifecycle: **{li.status}** — {li.message}")
        if rd.config_errors:
            for ce in rd.config_errors:
                st.error(f"Config error: {ce}")
        if rd.gate_results:
            st.markdown("#### Gate results")
            for r in rd.gate_results:
                # Consistent status-badge vocabulary (Phase 7 QA,
                # docs/decision_log.md): "pass"/"review"/"fail" reuse
                # core.validation_policy.VALIDATION_STATUS_VALUES's own
                # vocabulary, exactly the concept STATUS_BADGES already
                # covers for this reason - render through the shared badge
                # instead of a page-local icon map. A gate status outside
                # that three-value vocabulary (e.g. "skip") falls back to
                # badge_html's own neutral, title-cased default rather than
                # a fabricated icon.
                gate_col, value_col = st.columns([1, 3])
                with gate_col:
                    render_status_badge(r.status)
                with value_col:
                    st.write(f"**{r.gate_name}** (value: {r.value})")
        if rd.waivers_applied:
            st.markdown("#### Waivers")
            for w in rd.waivers_applied:
                st.write(f"  - Waiver `{w.waiver_id}` for gate `{w.gate_name}`")

    if validation_service_result.errors:
        for e in validation_service_result.errors:
            st.error(e)

st.markdown("### Model approval")
st.caption(FIELD_HELP["approval"])
render_definition_help(
    "a prior",
    "An assumption about a model parameter before the current data are used.",
)
render_definition_help(
    "a posterior",
    "The updated distribution of model parameters after fitting the current data.",
)
render_definition_help(
    "an approval",
    "A governed decision that the current fit and evidence are suitable for a specified use.",
)

# REQ-COVERAGE-001 S6, Work Package 5 (review finding, PR #158): surface the
# same rectangular-engine capability check used on Model Config here too, so
# an approver can see whether this fit's market/channel combination is
# within what the engine can validly support before approving it. This
# display by itself is informational only - it never blocks the "Approve"
# button directly. Work Package B additionally registers this fact as an
# optional policy gate (evaluator_id="market_channel_capability", see
# core.validation_policy) computed into DiagnosticsArtefact.
# market_channel_capability above: an active policy that includes this gate
# (expected_state=True, waivable=False) DOES block policy-backed approval
# through the ordinary readiness/evaluate_approval_readiness mechanism when
# unsupported - not a separate governance rule invented here, and exploratory
# review of this display remains available regardless of whether the active
# policy includes that gate.
# Phase 5 (REQ-VAL-001): reuses `_capability_result`, resolved once earlier
# on this page (right after "Compute scorecard") for the domain-health
# rail's "Coverage capability" row - never a second, divergent computation.
if _capability_result is not None and not _capability_result.supported:
    st.info(
        "This fit's market/channel combination goes beyond today's "
        "supported market/channel coverage per the governed coverage "
        "matrix. Exploratory review remains "
        "available; whether this blocks policy-backed approval depends "
        "on whether the active validation policy includes the "
        "market_channel_capability gate:\n\n"
        + "\n".join(
            f"- **{issue.market} / "
            f"{model_input_display_label(issue.channel, activity_definitions=activity_definitions, market=issue.market)}"
            f"**: {issue.reason}"
            for issue in _capability_result.issues
        )
    )

activity_governance_errors = []
if not activity_definitions:
    activity_governance_errors.append("No activity definitions are saved.")
elif meta is not None:
    for activity_market in meta.markets:
        try:
            resolved_activities = activity_by_model_input(
                activity_definitions,
                activity_market,
            )
        except ValueError as error:
            activity_governance_errors.append(str(error))
            continue
        missing_inputs = set(meta.channels) - set(resolved_activities)
        if missing_inputs:
            activity_governance_errors.append(
                f"{activity_market} is missing {sorted(missing_inputs)}"
            )
        unapproved = sorted(
            definition.activity_id
            for column, definition in resolved_activities.items()
            if column in meta.channels and definition.approval_status != "approved"
        )
        if unapproved:
            activity_governance_errors.append(
                f"{activity_market} has unapproved activities {unapproved}"
            )
activity_governance_ready = not activity_governance_errors

approval_dict = get_state("model_approval")
if approval_dict and not activity_governance_ready:
    set_state("model_approval", None)
    approval_dict = None
    st.warning(
        "The previous model approval was invalidated because required activity "
        "and causal-role governance is incomplete."
    )
# PR 82B: require_matching_approval (already used by curve_bank/optimization
# to gate real use of an approval) re-verifies the FULL chain - model
# identity AND, for policy-backed approvals, that the bound readiness still
# exists, is still overall_ready, and its policy/model-identity fingerprints
# still match the current policy and model - not just model identity alone.
# This is strictly stronger than (and replaces) a bare matches_current_model()
# check, so an approval can no longer be displayed as valid here while it
# would actually be rejected downstream by curve-bank/planning governance.
_approval_readiness_dict_now = get_state("approval_readiness")
_approval_readiness_obj, _ = load_approval_readiness(_approval_readiness_dict_now)

approval_matches_current = False
approval_invalid_reason: str | None = None
if approval_dict is not None and current_identity is not None:
    try:
        require_matching_approval(
            ModelApproval.from_dict(approval_dict),
            approval_readiness=_approval_readiness_obj,
            current_policy=_current_policy,
            **current_identity,
        )
        approval_matches_current = True
    except (ApprovalMismatchError, ValidationPolicyBlockedError) as exc:
        approval_invalid_reason = str(exc)

if approval_dict and not approval_matches_current:
    st.warning(
        "An approval exists in this session, but it no longer matches the current model, "
        "policy, or readiness evidence"
        + (f": {approval_invalid_reason}" if approval_invalid_reason else "")
        + " - it has been invalidated. Review and approve again below."
    )
    set_state("model_approval", None)
    approval_dict = None

if approval_dict:
    approved_at = pd.Timestamp.fromtimestamp(approval_dict["approved_at"])
    st.success(
        f"Approved by **{approval_dict['approved_by']}** on {format_date(approved_at)}."
    )
    with st.expander("Approval details"):
        st.write(f"**Model run:** `{approval_dict.get('model_run_id', '')[:8]}`")
        st.write(
            f"**Data fingerprint:** `{approval_dict.get('data_fingerprint', '')[:12]}`"
        )
        st.write(
            f"**Spec fingerprint:** `{approval_dict.get('model_spec_fingerprint', '')[:12]}`"
        )
        st.write(
            f"**Posterior fingerprint:** `{approval_dict.get('posterior_fingerprint', '')[:12]}`"
        )
        st.write(f"**Notes:** {approval_dict.get('notes') or '(none)'}")
        st.write(
            f"**Known limitations:** {approval_dict.get('known_limitations') or '(none)'}"
        )
        st.write(
            f"**Diagnostics reviewed:** {', '.join(approval_dict.get('diagnostics_accepted', [])) or '(none recorded)'}"
        )
    if st.button("Revoke approval"):
        set_state("model_approval", None)
        st.rerun()
elif not scorecard:
    st.info("Compute the scorecard above before approving this model.")
elif not activity_governance_ready:
    st.error(
        "Model approval is blocked until Activity & causal-role governance "
        "is complete and approved on Activity Mapping: "
        + "; ".join(activity_governance_errors)
    )
elif current_identity is None:
    st.warning(
        "Can't approve yet: the current fit's verification details are incomplete. "
        "Recompute the scorecard, or refit the model if the problem persists."
    )
elif validation_policy_dict is None:
    st.warning(
        "No validation policy is configured for this project. Official model "
        "approval requires a policy-backed readiness evaluation - configure a "
        "validation policy and evaluate readiness above before approving this model."
    )
elif _policy_config_error is not None:
    st.error(
        "Model approval is blocked: the configured validation policy is "
        f"malformed ({_policy_config_error}). Fix the policy configuration "
        "before approving this model."
    )
else:
    with st.form("approve_model_form"):
        approved_by = st.text_input("Approved by (name) *")
        diagnostics_accepted = st.multiselect(
            "Diagnostics reviewed before approving",
            [
                "convergence",
                "in_sample_fit",
                "ppc_coverage",
                "plausibility_flags",
                "backtest",
            ],
            default=[
                "convergence",
                "in_sample_fit",
                "ppc_coverage",
                "plausibility_flags",
            ],
        )
        notes = st.text_area("Notes")
        known_limitations = st.text_area("Known limitations")
        st.caption(
            f"Binding to model run `{current_identity['model_run_id'][:8]}` "
            f"(data `{current_identity['data_fingerprint'][:8]}`, "
            f"spec `{current_identity['model_spec_fingerprint'][:8]}`, "
            f"posterior `{current_identity['posterior_fingerprint'][:8]}`) - identifiers are "
            "captured automatically, not entered by hand."
        )
        submitted = st.form_submit_button(
            "Approve this model for planning", type="primary"
        )
        if submitted:
            if not approved_by.strip():
                st.error(
                    "Enter a name before approving - approval must be attributed to a reviewer."
                )
            elif not (
                validation_service_result and validation_service_result.readiness
            ):
                # PR 79A (work package K): a validation policy is configured
                # for this project, so policy-backed approval is the only
                # official approval path - there is no unbound fallback.
                # Without an evaluated readiness object there is nothing to
                # bind the approval to, so approval is blocked rather than
                # silently creating an unofficial approval.
                st.error(
                    "Evaluate readiness against the configured policy above before "
                    "approving - click 'Evaluate readiness' first."
                )
            else:
                try:
                    approval = create_policy_backed_model_approval(
                        readiness=validation_service_result.readiness,
                        current_policy=_current_policy,
                        approved_by=approved_by.strip(),
                        model_run_id=current_identity.get("model_run_id", ""),
                        data_fingerprint=current_identity.get("data_fingerprint", ""),
                        model_spec_fingerprint=current_identity.get(
                            "model_spec_fingerprint", ""
                        ),
                        posterior_fingerprint=current_identity.get(
                            "posterior_fingerprint", ""
                        ),
                        notes=notes,
                        known_limitations=known_limitations,
                        diagnostics_accepted=diagnostics_accepted,
                    )
                    set_state("model_approval", approval.to_dict())
                    st.success(
                        f"Policy-backed model approved by {approved_by.strip()}."
                    )
                    st.rerun()
                except Exception as e:
                    # PR 79A (work package K): no fallback to a standard,
                    # policy-unbound approval - a failed policy-backed
                    # approval leaves the model unapproved.
                    st.error(f"Policy-backed approval failed: {e}")
                    st.info(
                        "No approval was created. Resolve the issue above (e.g. "
                        "re-evaluate readiness after fixing failing gates) and "
                        "try again."
                    )


def _rebuild_fit_time_model():
    """Rebuild the exact unfit `pm.Model` this project's current fit (`meta`,
    `frame`, `model_type`) was built from - same builder, same frame, live
    `model_spec`/`prior_config` (mirrors how Model Training/backtest already
    rebuild a model from these same session-state values), and `meta`'s own
    `dna_lag_weeks`/`dna_outcome_id`/`direct_dna_outcome_ids` for an exact
    identity match (rather than possibly-drifted live session state).

    For a graph-backed fit, resolves the *exact* historical causal graph
    version `meta` recorded as having been used - never the live graph,
    which may have been edited since (including a layout-only edit, which
    REQ-GRAPH-001 reverts an approved graph to draft) - and fails closed if
    that exact version can no longer be reconstructed. Raises on any
    failure; callers are responsible for turning that into an explicit
    "failed" artefact section (`DiagnosticsService.
    record_prior_predictive_failure`/`record_predictive_density_failure`)
    rather than a page-only ephemeral message, so a rebuild failure is
    itself canonical evidence, never silently dropped.

    Shared by "Prior predictive check" and "Predictive density" below -
    both need the identical exact fit-time model structure.

    WP3 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`): routes
    through `application.model_fit_service.build_model_for_spec` (the same
    engine-selection adapter Model Training uses) instead of the previous
    inline shared/market-specific ternary, which silently rebuilt the
    *ordinary* model - dropping the entire Candidate A Search chain - for
    any fit whose approved graph required the Candidate A engine. No UI on
    this page (or Model Training) yet collects Candidate A Search
    observations into session state, so `build_model_for_spec` currently
    fails closed with a specific `ModelFitServiceError` for such a fit
    instead: an honest "cannot rebuild" error is safer than a silently
    wrong prior-predictive/predictive-density check against the wrong
    model structure.
    """
    rebuild_spec = ModelSpec.from_dict(get_state("model_spec"))
    rebuild_causal_graph = None
    if meta.causal_graph_id:
        graph_versions = get_state("causal_graph_versions") or []
        matching_graph_dict = next(
            (
                g
                for g in graph_versions
                if g.get("graph_id") == meta.causal_graph_id
                and int(g.get("graph_version", -1)) == meta.causal_graph_version
            ),
            None,
        )
        if matching_graph_dict is None:
            raise ValueError(
                f"This fit used causal graph '{meta.causal_graph_id}' "
                f"version {meta.causal_graph_version}, but that exact "
                "version is no longer available in this project's "
                "saved graph history - cannot reconstruct the exact "
                "fit-time model structure."
            )
        rebuild_causal_graph = CausalGraph.from_dict(matching_graph_dict)
        if (
            rebuild_causal_graph.structural_fingerprint()
            != meta.causal_graph_structural_fingerprint
        ):
            raise ValueError(
                "The saved causal graph version's structural "
                "fingerprint no longer matches this fit's recorded "
                "fingerprint - cannot reconstruct the exact fit-time "
                "model structure."
            )
    result = build_model_for_spec(
        frame=frame,
        model_spec=rebuild_spec,
        model_type=model_type,
        dna_lag_weeks=meta.dna_lag_weeks,
        prior_config=get_state("prior_config"),
        dna_outcome_id=meta.dna_outcome_id,
        direct_dna_outcome_ids=meta.direct_dna_outcome_ids,
        causal_graph=rebuild_causal_graph,
        search_objects=get_state("search_objects") or [],
    )
    return result.model


st.markdown("## Specialised evidence")
st.caption(
    "Not required to evaluate readiness or approve this model - available "
    "for deeper investigation. Each item below is collapsed by default."
)
st.markdown("---")
with st.expander("Prior predictive check", expanded=False):
    st.caption(
        "Prior predictive sampling uses this model's declared priors - never its "
        "posterior, never fitted (no MCMC, no trace) - and summarises the "
        "outcome-scale implication per market x outcome_id before any fitting. "
        "This is evidence about what the priors imply, not a measure of "
        "posterior fit quality (see Convergence, PPC coverage and Error metrics "
        "above for that). Rebuilds this fit's exact model structure (same "
        "builder, frame, prior configuration, DNA lag, and the exact fit-time "
        "causal graph version, never a possibly-since-edited live graph) and "
        "samples fresh from its priors - no prior value is changed by running "
        "this check. Note: with the default prior configuration, this model's "
        "intercept prior is itself centred on the observed outcome data at "
        "build time (log of the mean) - sampling does not condition on that "
        "data, but the declared prior it samples from can already reflect it."
    )
    pp_col1, pp_col2 = st.columns(2)
    pp_n_samples = pp_col1.number_input(
        "Prior draws", min_value=50, max_value=5000, value=500, step=50
    )
    pp_seed = pp_col2.number_input(
        "Random seed", min_value=0, max_value=2**31 - 1, value=42, step=1
    )

    if st.button("Run prior predictive check"):
        if diag_artefact is None:
            st.error("Compute the scorecard first.")
        else:
            try:
                pp_model = _rebuild_fit_time_model()
            except Exception as e:
                # Rebuilding the exact fit-time model structure failed (e.g. no
                # model_spec available, or the fit-time causal graph version
                # could no longer be reconstructed) - reported through the same
                # "failed" artefact-section path as a sampling failure below,
                # rather than a page-only ephemeral message, so this outcome is
                # itself canonical evidence (never fabricated as computed, never
                # silently dropped) and consistently invalidates governance
                # evidence the same way any other artefact change does.
                updated_artefact = DiagnosticsService().record_prior_predictive_failure(
                    diag_artefact,
                    f"Could not rebuild the model to sample its priors: {e}",
                )
            else:
                with st.spinner("Sampling priors..."):
                    updated_artefact = DiagnosticsService().run_prior_predictive_check(
                        diag_artefact,
                        model=pp_model,
                        frame=frame,
                        meta=meta,
                        model_type=model_type,
                        n_samples=int(pp_n_samples),
                        random_seed=int(pp_seed),
                    )
            set_state("diagnostics_artefact", updated_artefact)
            diag_artefact = updated_artefact
            # The artefact's fingerprint has changed - mirrors the backtest
            # section below (and the compute-scorecard handler above):
            # invalidate any readiness/approval evaluated against the
            # previous artefact in the same action.
            invalidate_governance_evidence()
            _render_summary_into(_summary_slot)
            if updated_artefact.prior_predictive.status == "computed":
                st.success(
                    "Prior predictive check computed - diagnostics artefact updated."
                )
            else:
                st.error(
                    f"Prior predictive check failed: {updated_artefact.prior_predictive.error}"
                )

    pp_section = diag_artefact.prior_predictive if diag_artefact else None
    if pp_section is not None and pp_section.status == "computed":
        st.caption(
            f"Model type: {MODEL_TYPE_LABEL.get(pp_section.payload.get('model_type', ''), pp_section.payload.get('model_type', ''))} | "
            f"Prior draws: {format_number(pp_section.payload.get('n_samples'))} | "
            f"Seed: {pp_section.payload.get('random_seed')}"
        )
        pp_df = pd.DataFrame(pp_section.payload["rows"])
        st.dataframe(
            pp_df, width="stretch", column_config=dataframe_column_config(pp_df)
        )
        for w in pp_section.warnings:
            st.caption(f"Sampling warning: {w}")
    elif pp_section is not None and pp_section.status == "failed":
        st.error(f"Prior predictive check failed: {pp_section.error}")

st.markdown("---")
with st.expander("Predictive density (PSIS-LOO / WAIC)", expanded=False):
    st.caption(
        "Predictive-density evidence is computed post-hoc "
        "against this fit's actual posterior trace (pm.compute_log_likelihood, "
        "then ArviZ PSIS-LOO/WAIC) - no refit, no MCMC re-run, and the trace is "
        "never modified. Rebuilds the exact fit-time model structure (same as "
        "the prior predictive check above) only to supply the likelihood graph "
        "compute_log_likelihood needs; every posterior draw it evaluates comes "
        "from the trace already computed above. PSIS-LOO's leave-one-out "
        "approximation is a documented general property (Vehtari et al.): it "
        "assumes each held-out observation is exchangeable with the rest, a "
        "weaker approximation for this model's temporal structure (adstock "
        "carryover/trend/seasonality) than for genuinely independent "
        "observations. The Pareto-k values reported per market x outcome_id "
        "are ArviZ's own mechanism for flagging where that approximation is "
        "unreliable - evidence to review, not a pass/fail gate."
    )

    if st.button("Run predictive density check"):
        if diag_artefact is None:
            st.error("Compute the scorecard first.")
        else:
            try:
                pd_model = _rebuild_fit_time_model()
            except Exception as e:
                updated_artefact = DiagnosticsService().record_predictive_density_failure(
                    diag_artefact,
                    f"Could not rebuild the model to compute predictive density: {e}",
                )
            else:
                with st.spinner("Computing log-likelihood and PSIS-LOO/WAIC..."):
                    updated_artefact = (
                        DiagnosticsService().run_predictive_density_check(
                            diag_artefact,
                            model=pd_model,
                            trace=trace,
                            frame=frame,
                            meta=meta,
                            model_type=model_type,
                        )
                    )
            set_state("diagnostics_artefact", updated_artefact)
            diag_artefact = updated_artefact
            invalidate_governance_evidence()
            _render_summary_into(_summary_slot)
            if updated_artefact.predictive_density.status == "computed":
                st.success(
                    "Predictive density check computed - diagnostics artefact updated."
                )
            else:
                st.error(
                    f"Predictive density check failed: {updated_artefact.predictive_density.error}"
                )

    pd_section = diag_artefact.predictive_density if diag_artefact else None
    if pd_section is not None and pd_section.status == "computed":
        st.caption(
            f"Model type: {MODEL_TYPE_LABEL.get(pd_section.payload.get('model_type', ''), pd_section.payload.get('model_type', ''))} | "
            f"Data points: {format_number(pd_section.payload.get('n_data_points'))} | "
            f"Good-Pareto-k threshold (ArviZ, sample-size-adjusted): {pd_section.payload.get('loo_good_k_threshold'):.3f}"
        )
        c1, c2 = st.columns(2)
        c1.metric(
            "elpd_loo",
            f"{pd_section.payload.get('elpd_loo'):.2f}",
            help=f"SE: {pd_section.payload.get('elpd_loo_se'):.2f}, p_loo: {pd_section.payload.get('p_loo'):.2f}",
        )
        c2.metric(
            "elpd_waic",
            f"{pd_section.payload.get('elpd_waic'):.2f}",
            help=f"SE: {pd_section.payload.get('elpd_waic_se'):.2f}, p_waic: {pd_section.payload.get('p_waic'):.2f}",
        )
        pd_df = pd.DataFrame(pd_section.payload["rows"])
        st.dataframe(
            pd_df, width="stretch", column_config=dataframe_column_config(pd_df)
        )
        for w in pd_section.warnings:
            st.caption(f"Computation warning: {w}")
    elif pd_section is not None and pd_section.status == "failed":
        st.error(f"Predictive density check failed: {pd_section.error}")

st.markdown("---")
with st.expander("Out-of-sample accuracy (expanding-window backtest)", expanded=False):
    st.caption(
        "Each fold refits the full model on an expanding training window and evaluates the next "
        "held-out block - this can take a while (it's a real fit per fold). Use a reduced draws/tune "
        "budget for a quicker check. Refits use the model structure chosen on Model Setup "
        f"({MODEL_TYPE_LABEL.get(model_type, model_type)})."
    )

    c1, c2, c3 = st.columns(3)
    n_folds = c1.number_input("Folds", min_value=1, max_value=5, value=1)
    min_train_frac = c2.slider("Min training fraction", 0.4, 0.9, 0.7, 0.05)
    fold_draws = c3.number_input(
        "Draws per fold (reduced for speed)",
        min_value=200,
        max_value=3000,
        value=500,
        step=100,
    )

    if st.button("Run backtest"):
        if diag_artefact is None:
            st.error("Compute the scorecard first.")
        elif meta is not None and meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
            # Backtest fold-fitting below never passes a causal_graph at all
            # (a pre-existing gap affecting every graph-backed fit, not new
            # here) - for the ordinary engine that silently falls back to the
            # legacy pathway catalogue, but a Candidate A fit has no legacy-
            # catalogue equivalent and no fold has the Search observations
            # needed to rebuild its demand/capture chain. Fail closed with a
            # specific reason rather than backtest an incomplete model.
            st.error(
                "This fit used the Candidate A Search engine. Out-of-sample "
                "backtesting for Candidate A is not yet implemented - each "
                "fold would need its own Search observations, and this "
                "page's backtest does not yet collect them."
            )
        else:
            spec = ModelSpec.from_dict(get_state("model_spec"))
            df = get_state("transformed_data")
            prior_config = get_state("prior_config")
            dna_lag_weeks = get_state("dna_lag_weeks", 4)

            def fit_fold(train_df, test_df):
                train_frame = prepare_fh_modeling_frame(train_df, spec)
                if model_type == "market_specific" and len(train_frame["markets"]) >= 2:
                    fold_model, fold_meta = build_fh_market_specific_model(
                        train_frame,
                        spec,
                        dna_lag_weeks=dna_lag_weeks,
                        prior_config=prior_config,
                        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
                    )
                else:
                    fold_model, fold_meta = build_fh_hierarchical_model(
                        train_frame,
                        spec,
                        dna_lag_weeks=dna_lag_weeks,
                        prior_config=prior_config,
                        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
                    )
                fold_trace = fit_model(
                    fold_model,
                    draws=int(fold_draws),
                    tune=int(fold_draws),
                    chains=2,
                    cores=1,
                    target_accept=0.9,
                )

                test_frame = prepare_fh_modeling_frame(test_df, spec)
                if model_type == "market_specific" and len(train_frame["markets"]) >= 2:
                    fold_params = extract_market_specific_posterior_params(
                        fold_trace, fold_meta
                    )
                    mu_test = predict_mu_market_specific(
                        test_frame, fold_meta, fold_params
                    )
                else:
                    fold_params = extract_posterior_params(fold_trace, fold_meta)
                    mu_test = predict_mu(test_frame, fold_meta, fold_params)

                r2_by_seg, mape_by_seg = {}, {}
                for i, oid in enumerate(fold_meta.outcome_ids):
                    actual, pred = test_frame["Y"][:, i], mu_test[:, i]
                    ss_res = ((actual - pred) ** 2).sum()
                    ss_tot = ((actual - actual.mean()) ** 2).sum()
                    r2_by_seg[oid] = (
                        float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
                    )
                    mask = actual != 0
                    mape_by_seg[oid] = (
                        float(
                            (abs((actual[mask] - pred[mask]) / actual[mask])).mean()
                            * 100
                        )
                        if mask.any()
                        else float("nan")
                    )
                return r2_by_seg, mape_by_seg

            with st.spinner(
                f"Running {n_folds}-fold backtest (this refits the model per fold)..."
            ):
                # PR 82B: routed through DiagnosticsService.run_backtest() - a
                # pure update that replaces only the artefact's backtest
                # section, never recomputing convergence/fit/PPC/plausibility/
                # identification/coefficient-stability.
                updated_artefact = DiagnosticsService().run_backtest(
                    diag_artefact,
                    raw_model_dataframe=df,
                    raw_model_spec=spec,
                    fit_fold_fn=fit_fold,
                    n_folds=int(n_folds),
                    min_train_frac=min_train_frac,
                )
            set_state("diagnostics_artefact", updated_artefact)
            diag_artefact = updated_artefact
            # The artefact's fingerprint has changed - any previously evaluated
            # readiness, validation results, and approval no longer match it and
            # must not keep being displayed/trusted as current (mirrors the
            # staleness check above; cleared immediately here, in the same
            # action, rather than waiting for the next rerun's mismatch check to
            # catch it - PR 88A: this previously left model_approval and
            # validation_results stale for one extra rerun).
            invalidate_governance_evidence()
            _render_summary_into(_summary_slot)
            if updated_artefact.backtest.status == "computed":
                # Legacy mirror for the project-export bundle (PR 82D wires
                # diagnostics_artefact into export directly) - not the
                # canonical evidence source, which is the artefact above.
                set_state(
                    "backtest_results", pd.DataFrame(updated_artefact.backtest.payload)
                )
                st.success(
                    "Backtest complete - diagnostics artefact updated. "
                    "Click 'Evaluate readiness' above to re-evaluate against the new evidence."
                )
            else:
                st.error(f"Backtest failed: {updated_artefact.backtest.error}")

    backtest_section = diag_artefact.backtest if diag_artefact else None
    if backtest_section is not None and backtest_section.status == "computed":
        backtest_df = pd.DataFrame(backtest_section.payload)
        st.dataframe(
            backtest_df,
            width="stretch",
            column_config=dataframe_column_config(backtest_df),
        )
    elif backtest_section is not None and backtest_section.status == "failed":
        st.error(f"Backtest failed: {backtest_section.error}")

st.markdown("---")
with st.expander("Funnel-coherence diagnostics", expanded=False):
    _funnel_links_raw = get_state("funnel_links") or []
    _funnel_links = [FunnelLink.from_dict(d) for d in _funnel_links_raw]
    st.caption(
        "Sign-ups and GSAs (or any declared upstream/downstream pair - see Structure page) are fitted as "
        "independent outcome equations, not a constrained funnel model - these are diagnostics and "
        "warnings only, evaluated against the *observed* data this fit was built from. They do not block "
        "training or planning."
    )
    if not _funnel_links:
        st.info(
            "No funnel links configured. Define upstream/downstream outcome pairs on the Structure page."
        )
    else:
        for link in _funnel_links:
            if (
                link.upstream_outcome_id not in frame["outcome_ids"]
                or link.downstream_outcome_id not in frame["outcome_ids"]
            ):
                st.warning(
                    f"Funnel link {link.upstream_outcome_id} -> {link.downstream_outcome_id} references an "
                    "outcome_id not in this fit - skipped."
                )
                continue
            up_idx = frame["outcome_ids"].index(link.upstream_outcome_id)
            down_idx = frame["outcome_ids"].index(link.downstream_outcome_id)
            result = funnel_coherence_diagnostics(
                link,
                frame["Y"][:, up_idx],
                frame["Y"][:, down_idx],
                period_labels=list(frame["dates"]) if "dates" in frame else None,
            )
            status_key = "review" if result["has_any_warning"] else "pass"
            st.markdown(
                f"{badge_html(status_key)} **{link.upstream_outcome_id} -> "
                f"{link.downstream_outcome_id}**",
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "Coherence violations",
                f"{result['n_violations']} / {result['n_periods']}",
            )
            c2.metric(
                "Mean conversion rate",
                f"{result['conversion_rate_mean']:.1%}"
                if result["conversion_rate_mean"] is not None
                else "n/a",
            )
            c3.metric(
                "Out-of-range periods", result["conversion_rate_out_of_range_count"]
            )
            if result["conversion_rate_unstable"]:
                st.caption(
                    f"Conversion rate is unstable across periods (CV={result['conversion_rate_cv']:.2f})."
                )
            if result["violation_periods"]:
                st.caption(
                    f"Violations at: {', '.join(format_date(d) for d in result['violation_periods'][:10])}"
                    + (" ..." if len(result["violation_periods"]) > 10 else "")
                )

st.markdown("---")
with st.expander("Posterior predictive metric distributions", expanded=False):
    st.caption(
        "For each error metric (MAE/RMSE/sMAPE/WAPE/bias), the *distribution* of "
        "that metric computed independently across posterior predictive draws - "
        "not only the single point value from the posterior mean shown in Error "
        "metrics above. For a non-linear metric such as RMSE, the metric of the "
        "posterior mean is not generally equal to the mean of the metric across "
        "draws - these are genuinely different numbers, kept separate here. "
        "Computed automatically alongside the scorecard above - re-run "
        "'Compute scorecard' to refresh it."
    )
    ppd_section = (
        diag_artefact.posterior_predictive_metric_distributions
        if diag_artefact
        else None
    )
    if ppd_section is not None and ppd_section.status == "computed":
        ppd_df = pd.DataFrame(ppd_section.payload)
        st.dataframe(
            ppd_df, width="stretch", column_config=dataframe_column_config(ppd_df)
        )
    elif ppd_section is not None and ppd_section.status == "failed":
        st.error(
            f"Posterior predictive metric distributions failed: {ppd_section.error}"
        )
    else:
        st.info("Compute the scorecard to see this evidence.")

st.markdown("---")
with st.expander("Historical validation & structural stability", expanded=False):
    st.caption(
        "Point-in-time, leakage-safe historical folds (REQ-LEAK-001): each fold "
        "refits the real production model on an expanding training window and is "
        "only fit at all if it first clears a per-variable reconstruction "
        "assessment against the current variable coverage matrix (effective "
        "periods, publication lag, definition breaks) - a fold that cannot be "
        "proven leakage-safe is skipped, never silently fit anyway. When this "
        "project has its raw source tables and outcome definitions, the run "
        "automatically uses the stronger reconstruction: each fold's official "
        "preparation is rebuilt fold-locally from the raw sources, governed to "
        "that fold's own information cutoff, with registered source-version "
        "upload-event cross-checks where available. When those inputs are not "
        "available, the run uses the coverage-matrix's own recorded metadata "
        "only - clearly labelled as such below, never presented as the deeper "
        "reconstruction. Structural stability (REQ-STAB-001) compares "
        "decision-driving parameters (adstock decay, saturation, response "
        "coefficients, ...) across every fold that was actually fit - "
        "reporting each parameter's plain numeric range across folds, never a "
        "stability verdict or threshold. Both sections come from exactly one "
        "fit per fold - never two divergent fits for the same fold."
    )
    hv_c1, hv_c2, hv_c3 = st.columns(3)
    hv_n_folds = hv_c1.number_input(
        "Folds", min_value=1, max_value=5, value=1, key="hv_n_folds"
    )
    hv_min_train_frac = hv_c2.slider(
        "Min training fraction", 0.4, 0.9, 0.7, 0.05, key="hv_min_train_frac"
    )
    hv_draws = hv_c3.number_input(
        "Draws per fold (reduced for speed)",
        min_value=200,
        max_value=3000,
        value=500,
        step=100,
        key="hv_draws",
    )

    if st.button("Run historical validation & structural stability"):
        if diag_artefact is None:
            st.error("Compute the scorecard first.")
        elif meta is not None and meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
            # Mirrors the backtest section's own Candidate A guard above: no
            # fold has the Search observations needed to rebuild its demand/
            # capture chain.
            st.error(
                "This fit used the Candidate A Search engine. Leakage-safe "
                "fold re-fitting for Candidate A is not yet implemented."
            )
        elif not coverage_matrix_dict:
            st.error(
                "No variable coverage matrix is available for this project - "
                "build one on the Data Coverage page first."
            )
        else:
            hv_spec = ModelSpec.from_dict(get_state("model_spec"))
            hv_df = get_state("transformed_data")
            hv_coverage_matrix = VariableCoverageMatrix.from_dict(coverage_matrix_dict)
            hv_raw_sources = get_state("raw_sources") or {}
            hv_outcome_definitions = get_state("outcome_definitions") or []
            # Strongest available reconstruction, never silently downgraded:
            # raw source tables + outcome definitions let each fold rebuild its
            # official preparation fold-locally from the raw sources, governed
            # to that fold's own information cutoff. Without them, only the
            # coverage matrix's recorded metadata can be assessed - an
            # explicitly weaker tier, labelled as such in the evidence below.
            hv_use_deep = bool(hv_raw_sources) and bool(hv_outcome_definitions)
            try:
                if hv_use_deep:
                    hv_calendar = get_state("canonical_calendar") or {}
                    with st.spinner(
                        f"Running {hv_n_folds}-fold source-version-aware "
                        "fold-local refit (this rebuilds each fold's official "
                        "preparation from the raw source tables and refits the "
                        "real model per accepted fold)..."
                    ):
                        fold_refit_result = run_leakage_safe_fold_refit_from_sources(
                            hv_raw_sources,
                            hv_spec,
                            hv_coverage_matrix,
                            hv_outcome_definitions,
                            governed_frequency=str(
                                hv_calendar.get("frequency") or "weekly"
                            ).lower(),
                            source_versions=get_state("source_versions") or [],
                            activity_definitions=get_state("activity_definitions")
                            or [],
                            search_objects=get_state("search_objects") or [],
                            pipeline_steps=get_state("pipeline_steps") or [],
                            model_type=model_type,
                            n_folds=int(hv_n_folds),
                            min_train_frac=hv_min_train_frac,
                            dna_lag_weeks=get_state("dna_lag_weeks", 4),
                            prior_config=get_state("prior_config"),
                            draws=int(hv_draws),
                            tune=int(hv_draws),
                        )
                else:
                    with st.spinner(
                        f"Running {hv_n_folds}-fold leakage-safe refit from the "
                        "coverage matrix's recorded metadata (raw source tables "
                        "are not available, so each fold's official preparation "
                        "is not rebuilt fold-locally; this refits the real model "
                        "per accepted fold)..."
                    ):
                        fold_refit_result = run_leakage_safe_fold_refit(
                            hv_df,
                            hv_spec,
                            hv_coverage_matrix,
                            model_type=model_type,
                            n_folds=int(hv_n_folds),
                            min_train_frac=hv_min_train_frac,
                            dna_lag_weeks=get_state("dna_lag_weeks", 4),
                            prior_config=get_state("prior_config"),
                            draws=int(hv_draws),
                            tune=int(hv_draws),
                        )
            except Exception as e:
                # Fold construction/assessment failed before any fit could even
                # be attempted (e.g. no transformed_data available yet) -
                # reported through the same "failed" artefact-section path as a
                # sampling failure above, rather than a page-only ephemeral
                # message, so this outcome is itself canonical evidence and
                # consistently invalidates governance evidence.
                failed_path = (
                    "source-version-aware fold-local"
                    if hv_use_deep
                    else "coverage-metadata-only"
                )
                updated_artefact = DiagnosticsService().record_historical_and_structural_validation_failure(
                    diag_artefact,
                    f"Could not run the leakage-safe fold refit ({failed_path} path): {e}",
                )
            else:
                updated_artefact = (
                    DiagnosticsService().run_historical_and_structural_validation_check(
                        diag_artefact,
                        results_df=fold_refit_result.results_df,
                        folds=fold_refit_result.folds,
                        assessments=fold_refit_result.assessments,
                        snapshots=fold_refit_result.snapshots,
                        reconstruction_tier=fold_refit_result.reconstruction_tier,
                    )
                )
            set_state("diagnostics_artefact", updated_artefact)
            diag_artefact = updated_artefact
            invalidate_governance_evidence()
            _render_summary_into(_summary_slot)
            if updated_artefact.historical_validation.status == "computed":
                st.success(
                    "Historical validation computed - diagnostics artefact "
                    "updated. Click 'Evaluate readiness' above to re-evaluate "
                    "against the new evidence."
                )
            else:
                st.error(
                    "Historical validation failed: "
                    f"{updated_artefact.historical_validation.error}"
                )

    hv_section = diag_artefact.historical_validation if diag_artefact else None
    if hv_section is not None and hv_section.status == "computed":
        st.caption(
            f"Folds assessed: {hv_section.payload['n_folds_assessed']} | "
            f"Leakage-safe: {hv_section.payload['n_folds_leakage_safe']}"
        )
        hv_tier = hv_section.payload.get("reconstruction_tier")
        if hv_tier == RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL:
            st.caption(
                "Evidence source: source-version-aware fold-local reconstruction "
                "- each fold's official preparation was rebuilt from the raw "
                "source tables, governed to that fold's own information cutoff."
            )
        elif hv_tier == RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY:
            st.caption(
                "Evidence source: coverage-metadata-only assessment - the raw "
                "source tables were not available, so each fold's official "
                "preparation was NOT rebuilt fold-locally from sources; this "
                "run assessed the coverage matrix's recorded metadata only. It "
                "is not equivalent to the deeper source-version-aware "
                "reconstruction."
            )
        else:
            st.caption(
                f"Evidence source: unrecognised reconstruction tier "
                f"{hv_tier!r} recorded in this artefact - review the artefact "
                "provenance before treating this evidence as current."
            )
        with st.expander("Fold reconstruction assessments"):
            for assessment in hv_section.payload["assessments"]:
                st.markdown(
                    f"**{assessment['fold_id']}** - "
                    f"{'leakage-safe' if assessment['is_leakage_safe'] else 'not leakage-safe'}"
                )
                if assessment["limitations"]:
                    for limitation in assessment["limitations"]:
                        st.caption(f"Limitation: {limitation}")
        results_df = pd.DataFrame(hv_section.payload["results"])
        st.dataframe(
            results_df,
            width="stretch",
            column_config=dataframe_column_config(results_df),
        )
    elif hv_section is not None and hv_section.status == "failed":
        st.error(f"Historical validation failed: {hv_section.error}")

    ss_section = diag_artefact.structural_stability if diag_artefact else None
    if ss_section is not None and ss_section.status == "computed":
        st.markdown("**Structural stability across folds**")
        per_param_rows = [
            {
                "parameter_name": p["parameter_name"],
                "point_range": p["point_range"],
                # st.dataframe's Arrow serialiser cannot convert a list/dict-
                # valued object column (pyarrow ArrowTypeError) - render the
                # per-fold point values as a compact JSON string instead,
                # losing no content.
                "fold_point_values": (
                    json.dumps(p["fold_point_values"])
                    if isinstance(p["fold_point_values"], (dict, list))
                    else p["fold_point_values"]
                ),
            }
            for p in ss_section.payload["per_parameter"]
        ]
        ss_df = pd.DataFrame(per_param_rows)
        st.dataframe(
            ss_df, width="stretch", column_config=dataframe_column_config(ss_df)
        )
        for limitation in ss_section.payload["limitations"]:
            st.caption(f"Limitation: {limitation}")
    elif ss_section is not None and ss_section.status == "not_computed":
        st.info(ss_section.error)
    elif ss_section is not None and ss_section.status == "failed":
        st.error(f"Structural stability failed: {ss_section.error}")

st.markdown("---")
with st.expander("Estimand-specific graphical identification", expanded=False):
    st.caption(
        "This evaluates the assumed graph. It does not prove that the graph is "
        "true or rule out unobserved confounding. Assesses whether the proposed "
        "adjustment set blocks every backdoor path between the selected "
        "treatment and outcome under the approved causal graph (Pearl's "
        "back-door criterion) - a diagnostic on the assumed graph, never proof "
        "that the graph is correct, that timing/measurement is right, or that "
        "the functional form is valid. Direct-effect requests are not silently "
        "treated as identified by this checker - a different identification "
        "strategy is required for a direct effect, and is reported as such."
    )
    graph_dict = get_state("causal_graph")
    if not graph_dict:
        st.info("No causal graph is configured for this project.")
    else:
        gi_graph = CausalGraph.from_dict(graph_dict)
        node_ids = [n.node_id for n in gi_graph.nodes]
        gi_c1, gi_c2, gi_c3 = st.columns(3)
        gi_treatment = gi_c1.selectbox("Treatment", node_ids, key="gi_treatment")
        gi_outcome = gi_c2.selectbox("Outcome", node_ids, key="gi_outcome")
        gi_effect_type = gi_c3.selectbox(
            "Effect type", [EFFECT_TYPE_TOTAL, EFFECT_TYPE_DIRECT], key="gi_effect_type"
        )
        gi_adjustment_set = st.multiselect(
            "Proposed adjustment set", node_ids, key="gi_adjustment_set"
        )
        if st.button("Assess identification"):
            if diag_artefact is None:
                st.error("Compute the scorecard first.")
            else:
                with st.spinner("Assessing graphical identification..."):
                    gi_service = DiagnosticsService()
                    gi_input = DiagnosticsInput(
                        trace=trace,
                        frame=frame,
                        meta=meta,
                        model_type=model_type,
                        model_identity=current_model_identity,
                        raw_model_spec=(
                            ModelSpec.from_dict(model_spec_dict)
                            if model_spec_dict
                            else None
                        ),
                        coverage_matrix=(
                            VariableCoverageMatrix.from_dict(coverage_matrix_dict)
                            if coverage_matrix_dict
                            else None
                        ),
                        coverage_matrix_built_against_fingerprint=get_state(
                            "variable_coverage_matrix_built_against_fingerprint"
                        ),
                        joined_dataframe_fingerprint=fingerprint_dataframe(frame["df"]),
                        causal_graph=gi_graph,
                        identification_requests=[
                            {
                                "treatment": gi_treatment,
                                "outcome": gi_outcome,
                                "effect_type": gi_effect_type,
                                "proposed_adjustment_set": tuple(gi_adjustment_set),
                            }
                        ],
                    )
                    gi_result = gi_service.evaluate(gi_input)
                set_state("diagnostics_artefact", gi_result.diagnostics_artefact)
                diag_artefact = gi_result.diagnostics_artefact
                invalidate_governance_evidence()
                _render_summary_into(_summary_slot)

    gi_section = diag_artefact.graphical_identification if diag_artefact else None
    if gi_section is not None and gi_section.status == "computed":
        for result in gi_section.payload["results"]:
            st.markdown(
                f"**{result['treatment']} -> {result['outcome']}** "
                f"({result['effect_type']}): `{result['status']}`"
            )
            st.caption(result["disclaimer"])
            if result["minimal_adjustment_set"] is not None:
                st.caption(
                    "Constructive minimal adjustment set: "
                    f"{list(result['minimal_adjustment_set'])}"
                )
            for limitation in result["limitations"]:
                st.caption(f"Limitation: {limitation}")
    elif gi_section is not None and gi_section.status == "failed":
        st.error(f"Graphical identification failed: {gi_section.error}")
    elif gi_section is not None and gi_section.status == "not_computed":
        st.info("No estimand has been assessed yet.")

st.markdown("---")
with st.expander("Latent-state scale/location identification", expanded=False):
    st.caption(
        "Every fitted latent causal state (e.g. Candidate A's latent branded-"
        "search demand) needs a declared identifying strategy for what one unit "
        "of it means - prior regularisation alone does not resolve structural "
        "non-identification. With no declared strategy, this is not_identified "
        "(a fail-closed result), never a fabricated pass. Declaring an "
        "identifying strategy or supplying per-chain posterior draws for "
        "empirical checking is not yet available from this page."
    )
    lsi_section = diag_artefact.latent_state_identification if diag_artefact else None
    if lsi_section is not None and lsi_section.status == "computed":
        for result in lsi_section.payload["results"]:
            st.markdown(f"**{result['latent_state_id']}**: `{result['status']}`")
            st.caption(result["disclaimer"])
            for limitation in result["limitations"]:
                st.caption(f"Limitation: {limitation}")
    elif lsi_section is not None and lsi_section.status in (
        "not_applicable",
        "not_computed",
    ):
        st.info("No latent causal states are declared or fitted for this model.")
    elif lsi_section is not None and lsi_section.status == "failed":
        st.error(f"Latent-state identification failed: {lsi_section.error}")

st.markdown("---")
with st.expander("Experiment & calibration evidence", expanded=False):
    st.caption(
        "Experiment provenance (REQ-EXPMODE-001) and calibrated-versus-"
        "uncalibrated model comparison (REQ-CALIB-001), kept as two separate, "
        "individually attributed evidence groups - never averaged into one "
        "score, and never used to silently override this model's fitted "
        "estimates. Provenance below comes from the governed experiment "
        "registry (adopted on the Data Sources page); declaring a use here "
        "records evidence mode and target identity only - no calibration "
        "method runs in this application, so the calibrated-vs-uncalibrated "
        "comparison stays empty until an approved calibration mechanism "
        "exists."
    )
    ec_section = diag_artefact.experiment_calibration if diag_artefact else None

    # Live staleness: the registry is the source of truth for this section.
    # If it changed after the scorecard was computed, the stored provenance no
    # longer matches the current registry - shown explicitly, never silently
    # presented as current evidence.
    _live_provenance = None
    if current_model_identity is not None:
        _live_provenance = provenance_for_model(
            experiment_records,
            experiment_uses,
            model_id=current_model_identity.model_run_id,
            model_version=current_model_identity.model_spec_fingerprint,
        )
    if (
        ec_section is not None
        and ec_section.status == "computed"
        and ec_section.payload.get("experiments") is not None
    ):
        _stored = ec_section.payload["experiments"]
        _live = _live_provenance.to_dict() if _live_provenance is not None else None
        if _live is None or _live != _stored:
            st.info(
                "The experiment registry has changed since this scorecard was "
                "computed - recompute the scorecard to refresh this evidence."
            )

    if experiment_records and current_model_identity is not None:
        st.markdown("**Declare an experiment use against the current model**")
        with st.form("exp_use_form"):
            _use_c1, _use_c2 = st.columns(2)
            _use_selected = _use_c1.selectbox(
                "Experiment",
                options=[
                    f"{rec.experiment_id} (v{rec.experiment_version})"
                    for rec in experiment_records
                ],
                key="exp_use_select",
            )
            _use_mode = _use_c2.selectbox(
                "Evidence mode", list(EVIDENCE_MODES), key="exp_use_mode"
            )
            _use_handling = st.text_input(
                "Dependence handling method (required when one experiment "
                "informs this model through two different calibrating modes)",
                key="exp_use_handling",
            )
            _use_prior_name = None
            _use_prior_version = None
            _use_lik_name = None
            _use_lik_version = None
            _use_compat = None
            if _use_mode == EVIDENCE_MODE_PRIOR_CALIBRATION:
                _p1, _p2 = st.columns(2)
                _use_prior_name = _p1.text_input(
                    "Affected prior name", key="exp_use_prior_name"
                )
                _use_prior_version = _p2.text_input(
                    "Affected prior version", key="exp_use_prior_version"
                )
            if _use_mode == EVIDENCE_MODE_LIKELIHOOD_CALIBRATION:
                _l1, _l2 = st.columns(2)
                _use_lik_name = _l1.text_input(
                    "Affected likelihood term name", key="exp_use_lik_name"
                )
                _use_lik_version = _l2.text_input(
                    "Affected likelihood term version", key="exp_use_lik_version"
                )
            if _use_mode in (
                EVIDENCE_MODE_PRIOR_CALIBRATION,
                EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
            ):
                st.caption(
                    "Calibrating uses require a compatibility review across "
                    "all nine governed dimensions - your review, never an "
                    "automatic verdict."
                )
                _dimension_results = {}
                for dimension in COMPATIBILITY_DIMENSIONS:
                    _dimension_results[dimension] = st.checkbox(
                        f"Compatible: {dimension}", key=f"exp_use_dim_{dimension}"
                    )
                _use_compat = build_compatibility_assessment(
                    experiment_id=_use_selected.split(" (")[0],
                    dimension_results=_dimension_results,
                )
            _use_submitted = st.form_submit_button("Declare use")
        if _use_submitted:
            _selected_exp_id = _use_selected.split(" (")[0]
            _selected_exp_version = int(_use_selected.split("(v")[1].rstrip(")"))
            try:
                set_state(
                    "experiment_model_uses",
                    [
                        use.to_dict()
                        for use in register_model_use(
                            experiment_records,
                            experiment_uses,
                            experiment_id=_selected_exp_id,
                            experiment_version=_selected_exp_version,
                            evidence_mode=_use_mode,
                            model_id=current_model_identity.model_run_id,
                            model_version=current_model_identity.model_spec_fingerprint,
                            compatibility=_use_compat,
                            affected_prior_name=_use_prior_name,
                            affected_prior_version=_use_prior_version,
                            affected_likelihood_term_name=_use_lik_name,
                            affected_likelihood_term_version=_use_lik_version,
                            dependence_handling_method=_use_handling or None,
                        )
                    ],
                )
                st.success(
                    f"Use registered: {_selected_exp_id} v{_selected_exp_version} "
                    f"({_use_mode}) against the current model. Recompute the "
                    "scorecard to refresh provenance."
                )
            except ValueError as exc:
                st.error(str(exc))
    elif experiment_records and current_model_identity is None:
        st.caption(
            "Experiments are registered, but no trained model exists yet - "
            "fit a model before declaring an experiment use against it."
        )

    if ec_section is not None and ec_section.status == "computed":
        if ec_section.payload["experiments"] is not None:
            st.markdown("**Experiment provenance**")
            exp_df = pd.DataFrame(ec_section.payload["experiments"]["entries"])
            st.dataframe(
                exp_df, width="stretch", column_config=dataframe_column_config(exp_df)
            )
        if ec_section.payload["calibration_comparison"] is not None:
            st.markdown("**Calibrated vs. uncalibrated comparison**")
            cal_df = pd.DataFrame(
                ec_section.payload["calibration_comparison"]["per_metric"]
            )
            st.dataframe(
                cal_df, width="stretch", column_config=dataframe_column_config(cal_df)
            )
    elif ec_section is not None and ec_section.status in (
        "not_applicable",
        "not_computed",
    ):
        st.info(
            "No experiment uses are registered for the current model, and no "
            "calibrated-model comparison exists (no calibration mechanism is "
            "implemented in this application)."
        )

    render_next_step("diagnostics")
