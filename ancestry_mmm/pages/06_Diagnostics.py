"""Page 6: model scorecard - convergence, in-sample fit, posterior predictive coverage, plausibility flags, out-of-sample backtest."""

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
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_glossary,
    render_drift_status,
    render_status_badge,
    render_top_line,
    render_primary_concern,
    render_domain_health_rail,
    render_workspace_note,
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
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.predict import extract_posterior_params, predict_mu
from ancestry_mmm.core.market_specific_predict import (
    extract_market_specific_posterior_params,
    predict_mu_market_specific,
)
from ancestry_mmm.data import prepare_fh_modeling_frame

MODEL_TYPE_LABEL = {
    "shared": "Model A - shared curve",
    "market_specific": "Model C - market-specific, partially pooled",
}

st.set_page_config(
    page_title="Diagnostics | Ancestry Family History & DNA MMM",
    page_icon="🧬",
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

trace = get_state("trace")
frame = get_state("frame")
meta = get_state("model_meta")
if trace is None or frame is None or meta is None:
    render_empty_state(
        "No trained model yet. Complete Model Training first.",
        button_label="Go to Model Training",
        target_key="model_training",
    )
    st.stop()

model_type = get_state("model_type", "shared")

spec_dict = get_state("model_spec")
if spec_dict:
    _spec_for_drift = ModelSpec.from_dict(spec_dict)
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
                f"{len(_changed_pathways)} media-outcome pathway(s) differ from this fit's captured "
                "pathway metadata - since PR G1 the pathway catalogue drives which coefficients get "
                "estimated, so this fit's results no longer reflect the catalogue currently configured "
                "on the Structure page. Re-run Model Training to pick up the change."
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
        ),
        posterior_fingerprint=fingerprint_posterior(posterior_params),
    )
# Dict view of the same identity object (never recomputed independently)
# for the model-approval section below, which binds approvals by keyword.
current_identity = asdict(current_model_identity) if current_model_identity else None

st.markdown("---")
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

st.markdown("### Full diagnostic detail")
st.caption(
    "Detail behind the summary above, grouped by evidence domain - not "
    "rendered flat and simultaneously. A domain's detail here is the same "
    "canonical evidence the rail above reads; nothing below recomputes it "
    "separately."
)
if scorecard:
    tab_conv, tab_fit, tab_ppc, tab_plaus, tab_ident = st.tabs(
        [
            "Convergence",
            "In-sample fit & error metrics",
            "Posterior predictive coverage",
            "Plausibility flags",
            "Identification & collinearity",
        ]
    )
    with tab_conv:
        conv = scorecard["convergence"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Max R-hat", f"{conv['max_rhat']:.3f}", help="Should be < 1.01")
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
        fit_df = pd.DataFrame(scorecard["in_sample_fit"])
        st.dataframe(
            fit_df, width="stretch", column_config=dataframe_column_config(fit_df)
        )

        st.markdown("#### Error metrics & residual temporal structure")
        st.caption(
            "REQ-VAL-001: MAE/RMSE (magnitude), sMAPE/WAPE (percentage, "
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
            "core.identification_diagnostics - a leave-one-channel-out refit sensitivity check is not run "
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
                for f in id_flags:
                    (st.error if f["level"] == "error" else st.warning)(
                        f"**{f['channel']}**: {f['message']}"
                    )

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
        ready_icon = "✅" if rd.overall_ready else "❌"
        st.markdown(
            f"### {ready_icon} Overall readiness: **{'Ready' if rd.overall_ready else 'Not ready'}**"
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
render_glossary(["Prior", "Posterior", "Approval"])

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
        "This fit's market/channel combination goes beyond what the "
        "engine can validly support today per the governed coverage "
        "matrix (REQ-COVERAGE-001 S6). Exploratory review remains "
        "available; whether this blocks policy-backed approval depends "
        "on whether the active validation policy includes the "
        "market_channel_capability gate:\n\n"
        + "\n".join(
            f"- **{issue.market} / {issue.channel}**: {issue.reason}"
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
        "is complete and approved on Channel & Media Units: "
        + "; ".join(activity_governance_errors)
    )
elif current_identity is None:
    st.warning(
        "Can't approve yet: the current model run's identity (run ID, data/specification/"
        "posterior fingerprints) isn't fully available. This shouldn't normally happen once "
        "a model has trained - try recomputing the scorecard, or retrain if the problem persists."
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
    rebuild_builder = (
        build_fh_market_specific_model
        if model_type == "market_specific"
        else build_fh_hierarchical_model
    )
    rebuilt_model, _rebuilt_meta = rebuild_builder(
        frame,
        rebuild_spec,
        dna_lag_weeks=meta.dna_lag_weeks,
        prior_config=get_state("prior_config"),
        dna_outcome_id=meta.dna_outcome_id,
        direct_dna_outcome_ids=meta.direct_dna_outcome_ids,
        causal_graph=rebuild_causal_graph,
    )
    return rebuilt_model


st.markdown("---")
st.markdown("### Prior predictive check")
st.caption(
    "REQ-VAL-001: samples from this model's declared PRIORS - never its "
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
    st.dataframe(pp_df, width="stretch", column_config=dataframe_column_config(pp_df))
    for w in pp_section.warnings:
        st.caption(f"Sampling warning: {w}")
elif pp_section is not None and pp_section.status == "failed":
    st.error(f"Prior predictive check failed: {pp_section.error}")

st.markdown("---")
st.markdown("### Predictive density (PSIS-LOO / WAIC)")
st.caption(
    "REQ-VAL-001: pointwise predictive-density evidence computed post-hoc "
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
                updated_artefact = DiagnosticsService().run_predictive_density_check(
                    diag_artefact,
                    model=pd_model,
                    trace=trace,
                    frame=frame,
                    meta=meta,
                    model_type=model_type,
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
    st.dataframe(pd_df, width="stretch", column_config=dataframe_column_config(pd_df))
    for w in pd_section.warnings:
        st.caption(f"Computation warning: {w}")
elif pd_section is not None and pd_section.status == "failed":
    st.error(f"Predictive density check failed: {pd_section.error}")

st.markdown("---")
st.markdown("### Out-of-sample accuracy (expanding-window backtest)")
st.caption(
    "Each fold refits the full model on an expanding training window and evaluates the next "
    "held-out block - this can take a while (it's a real fit per fold). Use a reduced draws/tune "
    "budget for a quicker check. Refits use the model structure chosen on Model Configuration "
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
                mu_test = predict_mu_market_specific(test_frame, fold_meta, fold_params)
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
                        (abs((actual[mask] - pred[mask]) / actual[mask])).mean() * 100
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
st.markdown("### Funnel-coherence diagnostics")
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
        icon = "⚠️" if result["has_any_warning"] else "✅"
        st.markdown(
            f"**{icon} {link.upstream_outcome_id} -> {link.downstream_outcome_id}**"
        )
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Coherence violations", f"{result['n_violations']} / {result['n_periods']}"
        )
        c2.metric(
            "Mean conversion rate",
            f"{result['conversion_rate_mean']:.1%}"
            if result["conversion_rate_mean"] is not None
            else "n/a",
        )
        c3.metric("Out-of-range periods", result["conversion_rate_out_of_range_count"])
        if result["conversion_rate_unstable"]:
            st.caption(
                f"Conversion rate is unstable across periods (CV={result['conversion_rate_cv']:.2f})."
            )
        if result["violation_periods"]:
            st.caption(
                f"Violations at: {', '.join(format_date(d) for d in result['violation_periods'][:10])}"
                + (" ..." if len(result["violation_periods"]) > 10 else "")
            )

render_next_step("diagnostics")
