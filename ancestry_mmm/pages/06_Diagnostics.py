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
)
from ancestry_mmm.core.approval import (
    ModelApproval,
    create_policy_backed_model_approval,
)
from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_by_model_input,
    activity_fit_fingerprint,
)
from ancestry_mmm.core.diagnostics import expanding_window_backtest
from ancestry_mmm.application.diagnostics_service import (
    DiagnosticsService,
    DiagnosticsInput,
)
from ancestry_mmm.application.validation_service import (
    ValidationService,
    ValidationInput,
)
from ancestry_mmm.core.validation_policy import (
    ThresholdPolicy,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.funnel import FunnelLink, funnel_coherence_diagnostics
from ancestry_mmm.core.identification_diagnostics import (
    channel_spend_correlation_matrix,
    design_matrix_condition_number,
    identification_report,
    posterior_coefficient_stability,
)
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
    page_title="Diagnostics - Ancestry FH MMM", page_icon="🧬", layout="wide"
)
init_session_state()
apply_theme()
render_sidebar("diagnostics")
render_page_header("diagnostics")
st.caption(
    "A scorecard, not a single headline R-squared - convergence, fit, posterior predictive coverage and plausibility flags together."
)

trace = get_state("trace")
frame = get_state("frame")
meta = get_state("model_meta")
if trace is None or frame is None or meta is None:
    st.markdown("---")
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
        )
        diag_result = diag_service.evaluate(diag_input)
        scorecard = diag_result.scorecard
        set_state("scorecard", scorecard)
        set_state("diagnostics_artefact", diag_result.diagnostics_artefact)
        set_state("diag_result", diag_result)
    st.success("Scorecard computed.")

# Retrieve artefact for governance display
diag_artefact = get_state("diagnostics_artefact")
diag_result = get_state("diag_result")

scorecard = get_state("scorecard")
if scorecard:
    st.markdown("### Convergence")
    conv = scorecard["convergence"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Max R-hat", f"{conv['max_rhat']:.3f}", help="Should be < 1.01")
    c2.metric(
        "Min ESS",
        format_number(round(conv["min_ess"])),
        help="Effective sample size; higher is better",
    )
    c3.metric("Divergences", format_number(conv["divergences"]))
    c4.metric("Converged", "Yes" if conv["converged"] else "No")
    if not conv["converged"]:
        st.warning(
            "Convergence diagnostics are outside typical thresholds. Consider more draws/tune, "
            "a higher target_accept, or simplifying the hierarchy before trusting these results."
        )

    st.markdown("---")
    st.markdown("### In-sample fit")
    fit_df = pd.DataFrame(scorecard["in_sample_fit"])
    st.dataframe(fit_df, width="stretch", column_config=dataframe_column_config(fit_df))

    st.markdown("---")
    st.markdown("### Posterior predictive coverage")
    st.caption(
        "% of actual observations falling inside the posterior predictive credible interval - should be close to the target %."
    )
    ppc_df = pd.DataFrame(scorecard["ppc_coverage"])
    st.dataframe(ppc_df, width="stretch", column_config=dataframe_column_config(ppc_df))

    st.markdown("---")
    st.markdown("### Curve & ROI plausibility flags")
    flags = scorecard["plausibility_flags"]
    if not flags:
        st.info("No plausibility flags raised.")
    else:
        for f in flags:
            (st.warning if f["level"] == "warning" else st.error)(
                f"**{f.get('channel', '')}**: {f['message']}"
            )

    st.markdown("---")
    st.markdown("### Multicollinearity & weak-identification diagnostics")
    st.caption(
        "Whether this fit's channel coefficients are trustworthy enough to plan against at all - "
        "independent of convergence, in-sample fit or PPC coverage above, since a model can score "
        "well on all three while still having two channels whose effects the data can't tell apart. "
        "core.identification_diagnostics - a leave-one-channel-out refit sensitivity check is not run "
        "here (it needs a full model refit per channel, too slow for an interactive page); the three "
        "signals below need no refit."
    )
    id_flags = identification_report(frame, meta, trace)
    if not id_flags:
        st.info("No multicollinearity or weak-identification flags raised.")
    else:
        for f in id_flags:
            (st.error if f["level"] == "error" else st.warning)(
                f"**{f['channel']}**: {f['message']}"
            )

    with st.expander("Channel spend correlation matrix"):
        corr_df = channel_spend_correlation_matrix(frame, meta)
        st.dataframe(
            corr_df, width="stretch", column_config=dataframe_column_config(corr_df)
        )

    with st.expander(
        "Design matrix condition number & posterior coefficient stability"
    ):
        cond = design_matrix_condition_number(frame)
        st.metric(
            "Condition number",
            f"{cond:,.1f}" if cond != float("inf") else "inf",
            help="Elevated above ~30, severe above ~100 - the standard econometric rule-of-thumb thresholds.",
        )
        stability_df = posterior_coefficient_stability(trace, meta)
        st.dataframe(
            stability_df,
            width="stretch",
            column_config=dataframe_column_config(stability_df),
        )

st.markdown("---")
st.markdown("### Validation readiness")
st.caption(
    "Evaluate diagnostics against a validation policy. This shows which gates pass, "
    "fail, or need review — and the overall approval readiness state."
)

validation_policy_dict = get_state("validation_policy")
validation_readiness = get_state("validation_readiness")

# Load policy for later use. A configured policy must deserialize through
# ThresholdPolicy.from_dict() — a malformed policy is a blocking error, not
# a silent downgrade to an empty policy (an empty policy would pass every
# gate by having none to evaluate).
_current_policy = None
_policy_config_error: str | None = None
if validation_policy_dict and isinstance(validation_policy_dict, dict):
    try:
        _current_policy = ThresholdPolicy.from_dict(validation_policy_dict)
    except ValueError as exc:
        _policy_config_error = str(exc)

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
        else:
            policy = _current_policy
            if policy is None:
                st.warning("No validation policy configured. Using minimal default.")
                policy = ThresholdPolicy(
                    policy_id="default-policy",
                    version="1.0",
                    scope="all_models",
                    gates=[],
                    owner="System",
                )
            val_service = ValidationService()
            val_input = ValidationInput(
                trace=trace,
                frame=frame,
                meta=meta,
                policy=policy,
                diagnostics_artefact=diag_artefact,
                model_type=model_type,
                model_identity=current_model_identity,
            )
            val_result = val_service.evaluate_readiness(val_input)
            set_state("validation_readiness", val_result)
            set_state("validation_result", val_result)

if validation_readiness:
    rd = validation_readiness.readiness
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
                gate_icon = {"pass": "✅", "fail": "❌", "review": "🔍", "skip": "➖"}
                icon = gate_icon.get(r.status, "❓")
                st.write(f"{icon} **{r.gate_name}**: {r.status} (value: {r.value})")
        if rd.waivers_applied:
            st.markdown("#### Waivers")
            for w in rd.waivers_applied:
                st.write(f"  - Waiver `{w.waiver_id}` for gate `{w.gate_name}`")

    if validation_readiness.errors:
        for e in validation_readiness.errors:
            st.error(e)

st.markdown("---")
st.markdown("### Model approval")
st.caption(FIELD_HELP["approval"])
render_glossary(["Prior", "Posterior", "Approval"])

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
approval_matches_current = (
    approval_dict is not None
    and current_identity is not None
    and ModelApproval.from_dict(approval_dict).matches_current_model(**current_identity)
)

if approval_dict and not approval_matches_current:
    st.warning(
        "An approval exists in this session, but it no longer matches the current model "
        "(it was granted for a different run, or the data/specification/posterior have "
        "changed since) - it has been invalidated. Review and approve again below."
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
            elif not (validation_readiness and validation_readiness.readiness):
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
                        readiness=validation_readiness.readiness,
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
            r2_by_seg[oid] = float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
            mask = actual != 0
            mape_by_seg[oid] = (
                float((abs((actual[mask] - pred[mask]) / actual[mask])).mean() * 100)
                if mask.any()
                else float("nan")
            )
        return r2_by_seg, mape_by_seg

    with st.spinner(
        f"Running {n_folds}-fold backtest (this refits the model per fold)..."
    ):
        results = expanding_window_backtest(
            df, spec, fit_fold, n_folds=int(n_folds), min_train_frac=min_train_frac
        )
    set_state("backtest_results", results)
    st.success("Backtest complete.")

backtest_results = get_state("backtest_results")
if backtest_results is not None and not backtest_results.empty:
    st.dataframe(
        backtest_results,
        width="stretch",
        column_config=dataframe_column_config(backtest_results),
    )

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
