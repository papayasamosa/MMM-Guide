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
from ancestry_mmm.data.preprocessor import create_fourier_features_from_calendar

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
if frame is None or meta is None or params is None:
    st.markdown("---")
    render_empty_state(
        "No trained model yet. Complete Model Training first.",
        button_label="Go to Model Training", target_key="model_training",
    )
    st.stop()

model_run_id = get_state("model_run_id")
prior_config = get_state("prior_config") or {}
dna_lag_weeks = get_state("dna_lag_weeks", 4)
current_identity = None
if model_run_id and spec_dict is not None:
    current_identity = {
        "model_run_id": model_run_id,
        "data_fingerprint": fingerprint_dataframe(frame["df"]),
        "model_spec_fingerprint": fingerprint_model_spec(spec_dict, prior_config, dna_lag_weeks),
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
identity_kwargs = dict(approval=approval, **current_identity)

spec = ModelSpec.from_dict(spec_dict)
ltv = spec.segment_ltv

render_glossary(["Scenario", "Constraint", "Response curve", "Incremental outcome"])

st.markdown("### Plan setup")
c1, c2, c3 = st.columns(3)
market = c1.selectbox("Market *", meta.markets)
start_month = c2.date_input("Plan start month *", value=pd.Timestamp.today().replace(day=1))
n_months = c3.number_input("Number of months *", min_value=1, max_value=24, value=12)

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

st.markdown("### Spend plan (monthly, by channel)")
st.caption("Edit values directly for manual mode - the same plan seeds the optimisation tabs below.")
plan_df = st.session_state[plan_key]
edited = st.data_editor(plan_df, width="stretch", key=f"editor_{plan_key}", column_config=dataframe_column_config(plan_df))
st.session_state[plan_key] = edited
spend_plan = {m: {c: float(edited.loc[m, c]) for c in meta.channels} for m in months}

objective = st.radio("Optimisation objective", ["value", "volume"], horizontal=True,
                      format_func=lambda x: "LTV-weighted value" if x == "value" else "Raw segment volume (GSAs)",
                      help=FIELD_HELP["ltv"])

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
    st.metric("Total predicted value" if objective == "value" else "Total predicted GSAs",
               f"{predicted['value'].sum():,.0f}" if objective == "value" else f"{predicted['predicted_gsa'].sum():,.0f}")

    scenario_name = st.text_input("Scenario name *", value=f"manual-{market}-{months[0]}", key="manual_name")
    if st.button("Save this scenario"):
        scenarios = get_state("scenarios") or []
        scenarios.append(scenario_to_dict(scenario_name, market, spend_plan, objective, [], notes="manual"))
        scenarios[-1]["predicted"] = predicted
        set_state("scenarios", scenarios)
        st.success(f"Saved scenario '{scenario_name}'.")

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
        st.metric("Current total", f"{result['current_objective_value']:,.0f}")
        st.metric("Optimised total", f"{result['objective_value']:,.0f}",
                   delta=f"{result['objective_value'] - result['current_objective_value']:,.0f}")
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
        st.metric("Current total", f"{result['current_objective_value']:,.0f}")
        st.metric("Theoretical optimum", f"{result['objective_value']:,.0f}",
                   delta=f"{result['objective_value'] - result['current_objective_value']:,.0f}")
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
