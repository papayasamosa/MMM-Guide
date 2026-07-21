"""Page 8: manual, constrained and unconstrained-benchmark scenario planning."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    init_session_state, get_state, set_state,
    dataframe_column_config, readable_label, CONSTRAINT_KIND_LABELS, FIELD_HELP,
)
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state, render_glossary
from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.fingerprint import fingerprint_dataframe, fingerprint_model_spec, fingerprint_posterior
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.optimization import (
    SpendConstraint, evaluate_scenario, optimize_scenario, scenario_to_dict, compare_scenarios, WEEKS_PER_MONTH,
)
from ancestry_mmm.core.uncertainty import evaluate_scenario_with_uncertainty
from ancestry_mmm.core.evidence_tiers import classify_market_evidence
from ancestry_mmm.core.market_config import MarketSpecConfig
from ancestry_mmm.core.media_units import extract_cost_per_unit_series, historical_cost_trend
from ancestry_mmm.data.preprocessor import create_fourier_features_from_calendar


def _scenario_cpa_summary(predicted_df: pd.DataFrame) -> dict:
    """Product-aware average CPA across a whole predicted-outcomes
    DataFrame (every month, every segment) - never a blended total-spend /
    (FH-GSAs-plus-DNA-kits) number (docs/dna_fh_causal_structure.md).
    `total_spend`/`fh_gsa`/`dna_kits` are month-level totals repeated per
    segment row (core.optimization.evaluate_scenario), so de-duplicated by
    month before summing across the whole plan."""
    by_month = predicted_df.groupby("month")[["total_spend", "fh_gsa", "dna_kits"]].first()
    total_spend = by_month["total_spend"].sum()
    fh_gsa = by_month["fh_gsa"].sum()
    dna_kits = by_month["dna_kits"].sum()
    return {
        "fh_avg_cpa": float(total_spend / fh_gsa) if fh_gsa > 0 else None,
        "dna_avg_cpa": float(total_spend / dna_kits) if dna_kits > 0 else None,
    }


st.set_page_config(page_title="Scenario Planner - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("scenario_planner")
render_page_header("scenario_planner")
st.caption(
    "Predicted outcomes use a steady-state approximation: spend held constant within a month is "
    "treated as having reached its adstock steady state, so a month's outcome is a closed-form "
    "function of that month's spend - no MCMC in the planning loop. See core/predict.py."
)

frame = get_state("frame")
meta = get_state("model_meta")
params = get_state("posterior_params")
spec_dict = get_state("model_spec")
trace = get_state("trace")
if frame is None or meta is None or params is None:
    st.markdown("---")
    render_empty_state(
        "No trained model yet. Complete Model Training first.",
        button_label="Go to Model Training", target_key="model_training",
    )
    st.stop()

model_type = get_state("model_type", "shared")

model_run_id = get_state("model_run_id")
prior_config = get_state("prior_config") or {}
dna_lag_weeks = get_state("dna_lag_weeks", 4)
current_identity = None
if model_run_id and spec_dict is not None:
    current_identity = {
        "model_run_id": model_run_id,
        "data_fingerprint": fingerprint_dataframe(frame["df"]),
        "model_spec_fingerprint": fingerprint_model_spec(
            spec_dict, prior_config, dna_lag_weeks, model_type=model_type,
            pipeline_steps=get_state("pipeline_steps") or [], market_spec_config=get_state("market_spec_config"),
            direct_dna_segments=meta.direct_dna_segments if meta is not None else None,
        ),
        "posterior_fingerprint": fingerprint_posterior(params),
    }

approval_dict = get_state("model_approval")
approval_matches_current = (
    approval_dict is not None
    and current_identity is not None
    and ModelApproval.from_dict(approval_dict).matches_current_model(**current_identity)
)

st.markdown("---")
if not approval_dict:
    st.warning(
        "This model hasn't been approved yet. Approve it on Diagnostics before planning scenarios - "
        "only an approved model's results may drive the planner."
    )
    if st.button("Go to Diagnostics"):
        st.switch_page("pages/06_Diagnostics.py")
    st.stop()
if not approval_matches_current:
    st.warning(
        "This model's approval no longer matches the current fitted model (the data, "
        "specification, posterior, or run have changed since it was approved) - the model must "
        "be reviewed and approved again on Diagnostics before planning scenarios."
    )
    if st.button("Go to Diagnostics", key="stale_approval_diagnostics"):
        st.switch_page("pages/06_Diagnostics.py")
    st.stop()

approval = ModelApproval.from_dict(approval_dict)
identity_kwargs = dict(model_type=model_type, approval=approval, **current_identity)

spec = ModelSpec.from_dict(spec_dict)
ltv = spec.segment_ltv

render_glossary(["Scenario", "Constraint", "Response curve", "Incremental outcome"])

st.markdown("### Plan setup")
c1, c2, c3 = st.columns(3)
market = c1.selectbox("Market *", meta.markets)
start_month = c2.date_input("Plan start month *", value=pd.Timestamp.today().replace(day=1))
n_months = c3.number_input("Number of months *", min_value=1, max_value=24, value=12)

if model_type == "market_specific":
    st.caption(
        "This model has market-specific curves - the plan below uses "
        f"**{market}**'s own fitted curve, not a curve shared with other markets."
    )
    with st.expander(f"Curve source for {market}'s channels"):
        tier_rows = []
        for ch in meta.channels:
            try:
                tier = classify_market_evidence(trace, frame, meta, market, ch)
            except (KeyError, ValueError) as e:
                tier = f"unavailable ({e})"
            tier_rows.append({"channel": ch, "curve_status": tier})
        tier_df = pd.DataFrame(tier_rows)
        st.dataframe(tier_df, width="stretch", column_config=dataframe_column_config(tier_df))
        if (tier_df["curve_status"] == "Transferred estimate").any():
            st.caption(
                "One or more channels above are a **transferred estimate** for this market - "
                "not enough local data to estimate a market-specific curve confidently. Plan "
                "against these with extra caution (`docs/market_hierarchy.md` section 4)."
            )

month_dates = pd.date_range(pd.Timestamp(start_month), periods=n_months, freq="MS")
months = [d.strftime("%Y-%m") for d in month_dates]

# --- Reference context per month: real calendar seasonality for each forecast
# month, trend held at the last observed level, promo/controls at their
# historical means - a documented planning approximation, not a forecast of
# future promo/control values.
market_mask = np.array(frame["df"][spec.market_col] == market)
last_trend = float(frame["trend"][market_mask][-1]) if market_mask.any() else 1.0
mean_promo = {seg: float(frame["promo"][market_mask, i].mean()) if market_mask.any() else 0.0 for i, seg in enumerate(meta.segments)}
mean_controls = {name: float(frame["X_controls"][market_mask, i].mean()) if (market_mask.any() and frame["X_controls"].shape[1]) else 0.0
                  for i, name in enumerate(frame.get("control_names") or [])}
mean_segment_controls = {
    seg: {name: float(frame["segment_controls"][seg][market_mask, i].mean()) if market_mask.any() else 0.0
          for i, name in enumerate(frame.get("segment_control_names", {}).get(seg, []))}
    for seg in (frame.get("segment_controls") or {})
}

reference_context_by_month = {}
for d, m in zip(month_dates, months):
    fourier_vec = create_fourier_features_from_calendar(pd.Series([d]), n_harmonics=spec.fourier_harmonics)[0]
    reference_context_by_month[m] = {
        "trend": last_trend, "fourier": fourier_vec, "promo": mean_promo,
        "controls": mean_controls, "segment_controls": mean_segment_controls,
    }

# --- Current/baseline spend plan: recent average weekly spend for this market, held flat.
if market_mask.any():
    avg_weekly_spend = frame["X_media"][market_mask].mean(axis=0)
else:
    avg_weekly_spend = frame["X_media"].mean(axis=0)
default_monthly = avg_weekly_spend * WEEKS_PER_MONTH

plan_key = f"spend_plan_editor_{market}_{n_months}_{start_month}"
if plan_key not in st.session_state:
    st.session_state[plan_key] = pd.DataFrame(
        [default_monthly for _ in months], index=months, columns=meta.channels
    ).round(0)

# --- Spend-vs-media-unit planning mode (docs/media_units_and_inflation.md,
# docs/scenario_planner.md's "Planned redesign"): the plan is always stored
# in spend terms in session state (plan_key) - media-unit mode only affects
# what the editor displays/accepts, converting at the edges using each
# channel's average historical cost-per-unit (core.media_units), the same
# documented simplification Results & Curve Bank's response-unit curve uses.
market_config = MarketSpecConfig.from_dict(get_state("market_spec_config"))
media_unit_channels = {}
for ch in meta.channels:
    cfg = market_config.get_media_unit_config(market, ch)
    if not (cfg and cfg.has_media_unit()):
        continue
    try:
        cost_df = extract_cost_per_unit_series(frame["df"], spec.date_col, spec.market_col, market, cfg)
        trend = historical_cost_trend(cost_df, spec.date_col)
    except ValueError:
        continue
    if trend["avg_cost_per_unit"]:
        media_unit_channels[ch] = {"unit_type": cfg.unit_type or "units", "avg_cost_per_unit": trend["avg_cost_per_unit"]}

st.markdown("### Spend plan (monthly, by channel)")
planning_mode = "Spend"
if media_unit_channels:
    planning_mode = st.radio(
        "Planning mode", ["Spend", "Media units"], horizontal=True,
        help=(
            "Media units mode converts to/from spend using each channel's average historical "
            "cost per unit - available for: " + ", ".join(sorted(media_unit_channels)) + ". "
            "Other channels stay in spend terms either way."
        ),
    )
st.caption("Edit values directly for manual mode - the same plan seeds the optimisation tabs below.")

plan_df = st.session_state[plan_key]
if planning_mode == "Media units":
    display_df = plan_df.copy()
    for ch, info in media_unit_channels.items():
        display_df[ch] = plan_df[ch] / info["avg_cost_per_unit"]
    label_overrides = {ch: f"{readable_label(ch)} ({info['unit_type']})" for ch, info in media_unit_channels.items()}
    edited_display = st.data_editor(
        display_df, width="stretch", key=f"editor_{plan_key}_units",
        column_config=dataframe_column_config(display_df, label_overrides=label_overrides),
    )
    edited = edited_display.copy()
    for ch, info in media_unit_channels.items():
        edited[ch] = edited_display[ch] * info["avg_cost_per_unit"]
    st.caption(
        "Cost-per-unit assumptions in use: " + ", ".join(
            f"{readable_label(ch)} = {info['avg_cost_per_unit']:,.2f} / {info['unit_type']}"
            for ch, info in media_unit_channels.items()
        )
    )
else:
    edited = st.data_editor(plan_df, width="stretch", key=f"editor_{plan_key}", column_config=dataframe_column_config(plan_df))
st.session_state[plan_key] = edited
spend_plan = {m: {c: float(edited.loc[m, c]) for c in meta.channels} for m in months}

_has_dna_kit_segments = bool(meta.kit_only_segments)
_objective_options = ["fh_gsa", "expected_value"] + (["dna_kits"] if _has_dna_kit_segments else [])
_objective_labels = {
    "fh_gsa": "Maximise Family History GSAs",
    "dna_kits": "Maximise DNA kit sales",
    "expected_value": "Maximise LTV-weighted expected value",
}
objective = st.radio(
    "Optimisation objective", _objective_options, horizontal=True,
    format_func=lambda x: _objective_labels[x], help=FIELD_HELP["ltv"],
)
st.caption(
    "Each objective states exactly what it maximises - Family History GSAs and DNA kit sales are "
    "never silently combined into one generic 'volume' number (docs/dna_fh_causal_structure.md)."
)
if objective == "expected_value" and not ltv:
    st.warning(
        "No LTV weights are configured for this project - 'Maximise expected value' needs at "
        "least one segment's LTV set on the Structure page before optimisation can run."
    )

st.markdown("---")
tab_manual, tab_constrained, tab_unconstrained = st.tabs(["Manual", "Constrained optimisation", "Unconstrained benchmark"])

with tab_manual:
    st.markdown("Predicted outcomes for the spend plan as edited above.")
    try:
        predicted = evaluate_scenario(spend_plan, market, meta, params, reference_context_by_month, ltv, **identity_kwargs)
    except ApprovalMismatchError as e:
        st.error(f"Cannot evaluate this scenario: {e}")
        st.stop()
    st.dataframe(predicted, width="stretch", column_config=dataframe_column_config(predicted))
    totals = predicted.groupby("segment")[["predicted_gsa", "value"]].sum().reset_index()
    st.markdown("**Totals by segment**")
    st.dataframe(totals, width="stretch", column_config=dataframe_column_config(totals))
    by_month_totals = predicted.groupby("month")[["fh_gsa", "dna_kits"]].first()
    _objective_totals = {
        "fh_gsa": ("Total predicted FH GSAs", float(by_month_totals["fh_gsa"].sum())),
        "dna_kits": ("Total predicted DNA kits", float(by_month_totals["dna_kits"].sum())),
        "expected_value": ("Total predicted value", float(predicted["value"].sum())),
    }
    c1, c2, c3 = st.columns(3)
    total_label, total_value = _objective_totals[objective]
    c1.metric(total_label, f"{total_value:,.0f}")
    cpa_summary = _scenario_cpa_summary(predicted)
    c2.metric("Avg CPA (Family History GSAs)", f"{cpa_summary['fh_avg_cpa']:,.2f}" if cpa_summary["fh_avg_cpa"] is not None else "n/a")
    if _has_dna_kit_segments:
        c3.metric("Avg CPA (DNA kits)", f"{cpa_summary['dna_avg_cpa']:,.2f}" if cpa_summary["dna_avg_cpa"] is not None else "n/a")

    scenario_name = st.text_input("Scenario name *", value=f"manual-{market}-{months[0]}", key="manual_name")
    if st.button("Save this scenario"):
        scenarios = get_state("scenarios") or []
        scenarios.append(scenario_to_dict(scenario_name, market, spend_plan, objective, [], notes="manual"))
        scenarios[-1]["predicted"] = predicted
        set_state("scenarios", scenarios)
        st.success(f"Saved scenario '{scenario_name}'.")

    st.markdown("---")
    if trace is None:
        st.caption("Posterior uncertainty needs a fitted trace, not just point-estimate posterior params - unavailable here.")
    else:
        show_scenario_uncertainty = st.checkbox(
            "Show posterior uncertainty for this plan (re-runs the scenario once per sampled draw - slower)",
            value=False, key="manual_scenario_uncertainty",
        )
        if show_scenario_uncertainty:
            n_draws = st.slider("Posterior draws to sample", 20, 200, 50, step=10, key="manual_scenario_n_draws")
            baseline_plan = {m: {c: float(v) for c, v in zip(meta.channels, default_monthly)} for m in months}
            with st.spinner(f"Computing scenario uncertainty from {n_draws} posterior draws..."):
                try:
                    uncertainty_result = evaluate_scenario_with_uncertainty(
                        spend_plan, market, meta, trace, reference_context_by_month, ltv,
                        n_draws=n_draws, baseline_spend_plan=baseline_plan, **identity_kwargs,
                    )
                except ApprovalMismatchError as e:
                    st.error(f"Cannot evaluate this scenario: {e}")
                    uncertainty_result = None
            if uncertainty_result is not None:
                st.markdown("**Predicted outcomes with uncertainty (mean / median / 90% credible interval)**")
                summary_df = uncertainty_result["summary"]
                st.dataframe(summary_df, width="stretch", column_config=dataframe_column_config(summary_df))
                prob = uncertainty_result["prob_outperforms_baseline"]
                if prob is not None:
                    st.metric(
                        "Probability this plan outperforms the recent-average baseline",
                        f"{prob:.0%}",
                        help=(
                            "Fraction of paired posterior draws where this plan's total predicted value "
                            "exceeds the recent-average-spend baseline's - the same draw index is used "
                            "for both plans in each comparison, so the result isn't inflated by "
                            "independently-resampled noise (docs/decision_log.md)."
                        ),
                    )
                st.caption(
                    f"Based on {uncertainty_result['n_draws']} sampled posterior draws - a subsample of "
                    "the full posterior for speed, not the full posterior itself."
                )

with tab_constrained:
    st.markdown(
        "Add the constraints Ancestry actually plans against: locked cells (e.g. committed TV "
        "bookings), fixed channel/month totals, bounded movement from the current plan, and "
        "minimum-spend floors (e.g. DNA promotional windows)."
    )
    if "scenario_constraints" not in st.session_state:
        st.session_state["scenario_constraints"] = []

    with st.expander("+ Add a constraint"):
        kind = st.selectbox(
            "Constraint type", ["locked_cell", "channel_total", "month_total", "bounded_movement", "min_spend_floor"],
            format_func=lambda k: CONSTRAINT_KIND_LABELS.get(k, k),
        )
        st.caption({
            "locked_cell": FIELD_HELP["locked_cells"],
            "channel_total": "Fix the total spend for one channel across the whole plan.",
            "month_total": "Fix the total spend across all channels for one month.",
            "bounded_movement": FIELD_HELP["maximum_movement"],
            "min_spend_floor": FIELD_HELP["minimum_spend"],
        }.get(kind, ""))
        ch = st.selectbox("Channel (if applicable)", ["(any)"] + meta.channels, key="c_channel", format_func=lambda c: c if c == "(any)" else readable_label(c))
        mo = st.selectbox("Month (if applicable)", ["(any)"] + months, key="c_month")
        val = st.number_input("Value / target (if applicable)", min_value=0.0, value=0.0, key="c_value")
        pct = st.slider("Max % movement (if applicable)", 0.0, 1.0, 0.2, 0.05, key="c_pct")
        if st.button("Add constraint"):
            constraint = SpendConstraint(
                kind=kind,
                channel=None if ch == "(any)" else ch,
                month=None if mo == "(any)" else mo,
                months=None if mo == "(any)" else [mo] if kind == "min_spend_floor" else None,
                value=val if val > 0 else None,
                max_pct_move=pct if kind == "bounded_movement" else None,
                label=f"{kind} {ch} {mo}",
            )
            st.session_state["scenario_constraints"].append(constraint)
            st.rerun()

    for i, c in enumerate(st.session_state["scenario_constraints"]):
        c1, c2 = st.columns([5, 1])
        c1.markdown(
            f"**{i+1}.** {CONSTRAINT_KIND_LABELS.get(c.kind, c.kind)} - "
            f"channel={readable_label(c.channel) or 'any'}, month={c.month or 'any'}, value={c.value}, max % movement={c.max_pct_move}"
        )
        if c2.button("Remove", key=f"rm_constraint_{i}"):
            st.session_state["scenario_constraints"].pop(i)
            st.rerun()

    if st.button("Run constrained optimisation", type="primary"):
        if objective == "expected_value" and not ltv:
            st.error("Cannot run optimisation: 'Maximise expected value' needs at least one segment's LTV set on the Structure page.")
            result = None
        else:
            with st.spinner("Optimising..."):
                try:
                    result = optimize_scenario(
                        spend_plan, months, meta.channels, market, meta, params, reference_context_by_month,
                        ltv, objective=objective, constraints=st.session_state["scenario_constraints"], conserve_total_budget=True,
                        **identity_kwargs,
                    )
                except ApprovalMismatchError as e:
                    st.error(f"Cannot run optimisation: {e}")
                    result = None
            if result is not None:
                if not result["success"]:
                    st.warning(f"Optimiser did not fully converge: {result['message']}")
                st.session_state["constrained_result"] = result

    result = st.session_state.get("constrained_result")
    if result:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"Current total ({_objective_labels[objective]})", f"{result['current_objective_value']:,.0f}")
        c2.metric("Optimised total", f"{result['objective_value']:,.0f}",
                   delta=f"{result['objective_value'] - result['current_objective_value']:,.0f}")
        current_cpa = _scenario_cpa_summary(result["current_predicted"])
        optimised_cpa = _scenario_cpa_summary(result["predicted"])
        c3.metric(
            "Avg CPA (FH GSAs)",
            f"{optimised_cpa['fh_avg_cpa']:,.2f}" if optimised_cpa["fh_avg_cpa"] is not None else "n/a",
            delta=f"{optimised_cpa['fh_avg_cpa'] - current_cpa['fh_avg_cpa']:,.2f}" if (optimised_cpa["fh_avg_cpa"] is not None and current_cpa["fh_avg_cpa"] is not None) else None,
            delta_color="inverse",  # lower CPA is an improvement
            help="Total spend / total predicted FH GSAs across the whole plan - current plan vs this optimised one.",
        )
        if _has_dna_kit_segments:
            c4.metric(
                "Avg CPA (DNA kits)",
                f"{optimised_cpa['dna_avg_cpa']:,.2f}" if optimised_cpa["dna_avg_cpa"] is not None else "n/a",
                delta=f"{optimised_cpa['dna_avg_cpa'] - current_cpa['dna_avg_cpa']:,.2f}" if (optimised_cpa["dna_avg_cpa"] is not None and current_cpa["dna_avg_cpa"] is not None) else None,
                delta_color="inverse",
                help="Total spend / total predicted DNA kits across the whole plan - current plan vs this optimised one.",
            )
        plan_result_df = pd.DataFrame(result["spend_plan"]).T
        st.dataframe(plan_result_df, width="stretch", column_config=dataframe_column_config(plan_result_df))
        st.dataframe(result["predicted"], width="stretch", column_config=dataframe_column_config(result["predicted"]))

        name = st.text_input("Scenario name *", value=f"constrained-{market}-{months[0]}", key="constrained_name")
        if st.button("Save this scenario", key="save_constrained"):
            scenarios = get_state("scenarios") or []
            s = scenario_to_dict(name, market, result["spend_plan"], objective, st.session_state["scenario_constraints"], notes="constrained")
            s["predicted"] = result["predicted"]
            scenarios.append(s)
            set_state("scenarios", scenarios)
            st.success(f"Saved scenario '{name}'.")

with tab_unconstrained:
    st.warning(
        "**Theoretical optimum, not a recommended plan.** This reallocates the same total budget "
        "freely, ignoring locks, timing commitments and operational constraints - shown for "
        "comparison only."
    )
    if st.button("Run unconstrained benchmark", type="primary"):
        if objective == "expected_value" and not ltv:
            st.error("Cannot run optimisation: 'Maximise expected value' needs at least one segment's LTV set on the Structure page.")
            result = None
        else:
            with st.spinner("Optimising..."):
                try:
                    result = optimize_scenario(
                        spend_plan, months, meta.channels, market, meta, params, reference_context_by_month,
                        ltv, objective=objective, constraints=[], conserve_total_budget=True,
                        **identity_kwargs,
                    )
                except ApprovalMismatchError as e:
                    st.error(f"Cannot run optimisation: {e}")
                    result = None
            if result is not None:
                st.session_state["unconstrained_result"] = result

    result = st.session_state.get("unconstrained_result")
    if result:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"Current total ({_objective_labels[objective]})", f"{result['current_objective_value']:,.0f}")
        c2.metric("Theoretical optimum", f"{result['objective_value']:,.0f}",
                   delta=f"{result['objective_value'] - result['current_objective_value']:,.0f}")
        current_cpa = _scenario_cpa_summary(result["current_predicted"])
        optimised_cpa = _scenario_cpa_summary(result["predicted"])
        c3.metric(
            "Avg CPA (FH GSAs)",
            f"{optimised_cpa['fh_avg_cpa']:,.2f}" if optimised_cpa["fh_avg_cpa"] is not None else "n/a",
            delta=f"{optimised_cpa['fh_avg_cpa'] - current_cpa['fh_avg_cpa']:,.2f}" if (optimised_cpa["fh_avg_cpa"] is not None and current_cpa["fh_avg_cpa"] is not None) else None,
            delta_color="inverse",
            help="Total spend / total predicted FH GSAs across the whole plan - current plan vs this theoretical optimum.",
        )
        if _has_dna_kit_segments:
            c4.metric(
                "Avg CPA (DNA kits)",
                f"{optimised_cpa['dna_avg_cpa']:,.2f}" if optimised_cpa["dna_avg_cpa"] is not None else "n/a",
                delta=f"{optimised_cpa['dna_avg_cpa'] - current_cpa['dna_avg_cpa']:,.2f}" if (optimised_cpa["dna_avg_cpa"] is not None and current_cpa["dna_avg_cpa"] is not None) else None,
                delta_color="inverse",
                help="Total spend / total predicted DNA kits across the whole plan - current plan vs this theoretical optimum.",
            )
        unconstrained_plan_df = pd.DataFrame(result["spend_plan"]).T
        st.dataframe(unconstrained_plan_df, width="stretch", column_config=dataframe_column_config(unconstrained_plan_df))

st.markdown("---")
st.markdown("### Saved scenarios")
scenarios = get_state("scenarios") or []
if scenarios:
    compare_df = compare_scenarios(scenarios)
    st.dataframe(compare_df, width="stretch", column_config=dataframe_column_config(compare_df))
else:
    st.info("No scenarios saved yet.")

render_next_step("scenario_planner")
