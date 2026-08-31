"""Page 8: manual, constrained and unconstrained-benchmark scenario planning."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    dataframe_column_config,
    readable_label,
    model_input_display_label,
    CONSTRAINT_KIND_LABELS,
    FIELD_HELP,
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
    render_workspace_note,
    SectionCard,
)
from ancestry_mmm.core.approval import (
    ApprovalMismatchError,
    ModelApproval,
    ValidationPolicyBlockedError,
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
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.causal_graph import current_structural_fingerprint_for_identity
from ancestry_mmm.core.outcomes import (
    dna_kit_sale_outcome_ids,
    eligible_outcome_ids,
    fh_gsa_outcome_ids,
    fh_net_billthrough_outcome_ids,
    fh_signup_outcome_ids,
    outcome_catalogue_fingerprint_payload,
    resolve_outcome_definitions,
)
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    PlanningGovernanceError,
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.planning.value import (
    DNA_VALUE_MODE_OVERALL,
    DNA_VALUE_MODE_SEGMENT_SPECIFIC,
    ScenarioValueAssumptions,
    build_scenario_value_assumptions,
)
from ancestry_mmm.core.planning.planned_activity import (
    PromotionPeriod,
    materialize_promo_future,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.optimization import (
    CurrencyContext,
    OutcomeValueMapping,
    ScenarioGovernanceDependencies,
    SpendConstraint,
    compare_scenarios,
    governance_deps_from_optimizer_result,
    monthly_economics_table,
    require_current_cost_mapping,
    resolve_planning_objective,
    resolve_scenario_cost_mapping_fingerprint,
    scenario_to_dict,
    seed_monetary_and_quantity_defaults,
    whole_plan_scope_compatible,
)
from ancestry_mmm.core.optimization_objective_vocabulary import resolve_objective_kind
from ancestry_mmm.core.optimization_constraint_vocabulary import (
    GovernedSpendConstraint,
)
from ancestry_mmm.core.uncertainty import evaluate_scenario_with_uncertainty
from ancestry_mmm.core.outcome_group_totals import aggregate_outcome_groups
from ancestry_mmm.core.evidence_tiers import classify_market_evidence
from ancestry_mmm.core.market_config import MarketSpecConfig
from ancestry_mmm.core.media_units import (
    extract_cost_per_unit_series,
    historical_cost_trend,
)
from ancestry_mmm.core.media_costs import CostMappingRegistry
from ancestry_mmm.core.scenario_governance import (
    CounterfactualPolicy,
    ScenarioPlan,
    classify_activity_plan,
    resolve_counterfactual,
)
from ancestry_mmm.core.validation_policy import (
    load_approval_readiness,
    load_threshold_policy,
)
from ancestry_mmm.application.scenario_plan_period import derive_plan_period_disclosure
from ancestry_mmm.application.scenario_service import (
    ManualScenarioInput,
    OptimisationInput,
    ScenarioService,
    SequentialManualScenarioInput,
)
from ancestry_mmm.data.preprocessor import create_fourier_features_from_calendar
from ancestry_mmm.core.frequency_alignment import CanonicalCalendar
from ancestry_mmm.core.planning.future_context import (
    EXPLORATORY_MODE,
    OFFICIAL_MODE,
    build_future_context,
)
from ancestry_mmm.core.planning.phasing import (
    HorizonConfiguration,
    canonical_weeks,
    phase_monetary_plan_from_partial_start_calendar_day_overlap_v1,
    phase_monthly_series_from_partial_start_calendar_day_overlap_v1,
    reseat_ordinal_monthly_plan_to_start_week,
)
from ancestry_mmm.core.planning.weekly_plan_builder import build_governed_weekly_plan
from ancestry_mmm.core.sequential_evaluation_context import SequentialEvaluationContext
from ancestry_mmm.core.sequential_scenario_evaluation import sequential_scenario_to_dict


def _catalogue_value(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _scenario_outcome_labels(outcome_definitions, outcome_groups):
    """Build display labels without changing persisted outcome/group IDs."""
    labels = {}
    for outcome in outcome_definitions or []:
        outcome_id = _catalogue_value(outcome, "outcome_id")
        if not outcome_id:
            continue
        parts = [
            str(_catalogue_value(outcome, key, "")).strip()
            for key in ("product", "segment", "metric")
            if str(_catalogue_value(outcome, key, "")).strip()
        ]
        label = " · ".join(parts) or readable_label(str(outcome_id))
        version = str(_catalogue_value(outcome, "definition_version", "")).strip()
        if version:
            label += f" (definition {version})"
        labels[str(outcome_id)] = label
    for group in outcome_groups or []:
        group_id = _catalogue_value(group, "group_id")
        if group_id:
            labels[str(group_id)] = _catalogue_value(
                group, "group_label", readable_label(str(group_id))
            )
    return labels


_SCENARIO_DISPLAY_COLUMNS = {
    "scenario": "Scenario",
    "market": "Market",
    "governance_mode": "Planning use",
    "total_spend": "Total spend",
    "total_value": "Total outcome value",
    "total_value_is_complete": "Complete value total",
    "total_fh_gsa": "Total Family History GSAs",
    "total_fh_signups": "Total Family History sign-ups",
    "total_dna_kits": "Total DNA kits",
    "month": "Month",
    "predicted_outcome": "Predicted outcome",
    "predicted_total_outcome": "Predicted total outcome",
    "predicted_counterfactual_outcome": "Comparison baseline",
    "incremental_outcome": "Incremental outcome",
    "incremental_outcome_all_activities": "Incremental outcome · all activity",
    "incremental_outcome_paid_decisions": "Incremental outcome · paid decisions",
    "incremental_outcome_response_only_activities": "Incremental outcome · response-only activity",
    "value": "Outcome value",
    "incremental_total_value": "Incremental outcome value",
    "paid_spend": "Paid-media spend",
    "fully_loaded_owned_spend": "Fully loaded owned spend",
    "campaign_cost_spend": "Campaign-cost spend",
    "fh_gsa": "Family History GSAs",
    "fh_signups": "Family History sign-ups",
    "fh_net_billthrough": "Family History net bill-through",
    "dna_kits": "DNA kits",
    "incremental_fh_gsa": "Incremental Family History GSAs",
    "incremental_fh_signups": "Incremental Family History sign-ups",
    "incremental_fh_net_billthrough": "Incremental Family History net bill-through",
    "incremental_dna_kits": "Incremental DNA kits",
    "economics_availability_status": "Economics availability",
    "whole_plan_incremental_nbt_cpa": "Whole-plan Net Bill Through CPA",
    "paid_media_incremental_nbt_cpa": "Paid-media Net Bill Through CPA",
    "whole_plan_incremental_roi": "Whole-plan incremental ROI",
    "paid_media_incremental_roi": "Paid-media incremental ROI",
    "whole_plan_cost_per_fh_gsa": "Whole-plan Family History GSA CPA",
    "paid_media_incremental_cpa": "Paid-media incremental CPA",
    "whole_plan_cost_per_dna_kit": "Whole-plan DNA kit CPA",
    "whole_plan_cost_per_fh_signup": "Whole-plan Family History sign-up CPA",
}

_SCENARIO_TECHNICAL_COLUMNS = {
    "counterfactual_media_input",
    "resolved_counterfactual_vector",
    "counterfactual_policy",
    "counterfactual_policy_fingerprint",
    "unpriced_outcome_ids",
    "economics_coverage",
    "activity_definitions_fingerprint",
    "scenario_plan_fingerprint",
    "planning_objective",
}


def _humanise_scenario_output(dataframe, outcome_labels):
    """Return the business-facing view of evaluator output."""
    displayed = dataframe.copy()
    if "governance_mode" in displayed.columns:
        displayed["governance_mode"] = displayed["governance_mode"].replace(
            {
                "official": "Official planning",
                "exploratory": "Exploratory sensitivity",
            }
        )
    if "outcome_id" in displayed.columns:
        displayed["Outcome"] = displayed["outcome_id"].map(
            lambda value: outcome_labels.get(str(value), readable_label(str(value)))
        )
        displayed = displayed.drop(columns=["outcome_id"])
    displayed = displayed.drop(
        columns=[
            column
            for column in _SCENARIO_TECHNICAL_COLUMNS
            if column in displayed.columns
        ]
    )
    preferred = [
        "month",
        "Outcome",
        "predicted_outcome",
        "predicted_total_outcome",
        "predicted_counterfactual_outcome",
        "incremental_outcome",
        "value",
        "total_spend",
        "paid_spend",
    ]
    ordered = [column for column in preferred if column in displayed.columns]
    ordered.extend(column for column in displayed.columns if column not in ordered)
    displayed = displayed[ordered]
    return displayed.rename(columns=_SCENARIO_DISPLAY_COLUMNS)


def _humanise_economics_table(dataframe):
    displayed = dataframe.copy()
    if "plan" in displayed.columns:
        displayed["plan"] = displayed["plan"].replace(
            {"current": "Current plan", "optimised": "Optimised plan"}
        )
    return displayed.rename(columns=_SCENARIO_DISPLAY_COLUMNS)


def _render_scenario_output(dataframe, outcome_labels, *, technical_title):
    displayed = _humanise_scenario_output(dataframe, outcome_labels)
    st.dataframe(
        displayed,
        width="stretch",
        column_config=dataframe_column_config(displayed),
    )
    render_technical_details(
        title=technical_title,
        details={
            "Raw evaluator fields": ", ".join(
                str(column) for column in dataframe.columns
            ),
            "Display rule": "Outcome IDs and implementation fields are retained in the evaluator output and disclosed here, not used as routine business labels.",
        },
    )


def _render_economics_table(dataframe, *, technical_title):
    displayed = _humanise_economics_table(dataframe)
    st.dataframe(
        displayed,
        width="stretch",
        column_config=dataframe_column_config(displayed),
    )
    render_technical_details(
        title=technical_title,
        details={
            "Core evaluator fields": ", ".join(
                str(column) for column in dataframe.columns
            ),
            "Calculation rule": "All CPA and ROI values are supplied by the core evaluator; this page does not recompute them.",
        },
    )


def _sequential_plan_start_week(frame, market, spec) -> pd.Timestamp:
    """The Monday immediately following this market's last historical
    canonical week - continuing the exact same weekly cadence as the
    fitted data, with no gap and no overlap (WP5, `Media-Mix-Lab: Coding
    LLM Next Steps Post PR262`). Sequential mode always starts here,
    never at the steady-state tab's user-chosen `start_month` - avoiding
    an unmodelled gap (or double-counted overlap) between the historical
    carry-in and the first planned week."""
    market_mask = np.array(frame["df"][spec.market_col] == market)
    market_dates = pd.to_datetime(frame["dates"])[market_mask]
    if len(market_dates) == 0:
        raise ValueError(f"No historical weeks found for market {market!r}.")
    return market_dates.max() + pd.Timedelta(days=7)


def _evaluate_sequential_manual_plan(
    *,
    market: str,
    meta,
    params,
    frame,
    spec,
    n_months: int,
    spend_plan: dict,
    activity_definitions,
    counterfactual_policy,
    governed_cost_registry,
    planning_objective,
    identity_kwargs: dict,
    scenario_governance_kwargs: dict,
    value_mapping,
    currency_context,
    trace=None,
    n_posterior_draws: int = 0,
    promotion_periods=(),
):
    """Build and evaluate a sequential-weekly manual scenario from the same
    monthly spend_plan/governance inputs the steady-state tab uses (WP5,
    `Media-Mix-Lab: Coding LLM Next Steps Post PR262`). Raises `ValueError`
    with an analyst-readable message on any failure the caller should
    render via `st.error`; never raises for an ordinary governance/
    validation rejection surfaced instead as `ScenarioServiceResult.errors`.

    `promotion_periods` (`REQ-PLANACT-001`, Decision 14): structured
    `core.planning.planned_activity.PromotionPeriod` declarations for this
    plan window, materialised into `build_future_context`'s `promo_future`
    via the real, unmodified `materialize_promo_future` - an empty
    sequence (the default) yields the exact same all-zero `promo_future`
    this function always built before. The terminal continuation window
    deliberately keeps zero promo regardless (documented, unchanged
    "residual carryover under continuing seasonality but zero future
    decision media" assumption) - promotion periods are scoped to the
    analyst's real plan window only.
    """
    plan_start_week = _sequential_plan_start_week(frame, market, spec)
    candidate_monthly_by_channel = {
        c: {m: spend_plan[m][c] for m in spend_plan} for c in meta.channels
    }

    # Reference (counterfactual) uses the SAME resolution the steady-state
    # path uses (core.scenario_governance.resolve_counterfactual is
    # confirmed period-key-agnostic), applied to the original monthly plan
    # BEFORE re-seating onto the sequential calendar - the counterfactual
    # rule (zero/hold_plan/explicit) is evaluated per real analyst-entered
    # month, then re-seated and pro-rated identically to the candidate.
    reference_monthly_plan = resolve_counterfactual(
        spend_plan,
        market=market,
        activity_definitions=activity_definitions or None,
        policy=counterfactual_policy,
    )
    reference_monthly_by_channel = {
        c: {m: reference_monthly_plan[m][c] for m in reference_monthly_plan}
        for c in meta.channels
    }

    # Re-keying each channel's ordered monthly values onto the real
    # calendar months starting at `plan_start_week` (pro-rating a partial
    # first month) is the governed `core.planning.phasing` contract
    # (`reseat_ordinal_monthly_plan_to_start_week`), not page-local logic -
    # WP0 of `Media-Mix-Lab: Coding LLM Next Steps After PR #267` moved
    # this out of the page (previously `_prorated_sequential_monthly_
    # values`) to resolve the thin-interface violation flagged there.
    sequential_months: tuple = ()
    reseated_candidate: dict = {}
    for c in meta.channels:
        ordered_values = [
            candidate_monthly_by_channel[c][m] for m in candidate_monthly_by_channel[c]
        ]
        reseated_candidate[c], sequential_months = (
            reseat_ordinal_monthly_plan_to_start_week(
                ordinal_monthly_values=ordered_values,
                plan_start_week=plan_start_week,
            )
        )
    reseated_reference: dict = {}
    for c in meta.channels:
        ordered_values = [
            reference_monthly_by_channel[c][m] for m in reference_monthly_by_channel[c]
        ]
        reseated_reference[c], _ = reseat_ordinal_monthly_plan_to_start_week(
            ordinal_monthly_values=ordered_values,
            plan_start_week=plan_start_week,
        )

    calendar_end = pd.Timestamp(sequential_months[-1] + "-01") + pd.offsets.MonthEnd(0)
    calendar = CanonicalCalendar(
        start=plan_start_week.strftime("%Y-%m-%d"),
        end=calendar_end.strftime("%Y-%m-%d"),
        frequency="weekly",
    )
    weeks = canonical_weeks(calendar)

    activity_map = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions
        else {}
    )
    cost_as_of_by_period = {w: w for w in weeks}

    def _phase_channel(reseated_monthly_values: dict, channel: str):
        # The first sequential month is necessarily partial (the plan
        # starts mid-month, immediately after history ends - see
        # `_sequential_plan_start_week`); the governed phasing functions
        # below (`core.planning.phasing`) phase that already-pro-rated
        # fragment and every subsequent whole month additively per week,
        # so a boundary week between month 1 and month 2 legitimately
        # carries spend from both - this page no longer implements that
        # arithmetic itself (WP0 of `Media-Mix-Lab: Coding LLM Next Steps
        # After PR #267`, resolving the thin-interface violation flagged
        # there; previously `_first_month_fragment_schedule` plus an
        # inline per-week cost-mapping loop).
        definition = activity_map.get(channel)
        is_cost_bearing = definition.is_cost_bearing if definition else True

        if is_cost_bearing and governed_cost_registry is not None:
            # `channel_allocations` (below) takes `WeeklyAllocationResult`
            # or `WeeklyModelInputDerivation` directly, never the combined
            # `MonetaryPhasingResult` wrapper - the derived model-input
            # quantity is what a fit-time model input expects.
            return phase_monetary_plan_from_partial_start_calendar_day_overlap_v1(
                market=market,
                channel=channel,
                reseated_monthly_spend=reseated_monthly_values,
                plan_start_week=plan_start_week,
                calendar=calendar,
                cost_registry=governed_cost_registry,
            ).weekly_model_input
        return phase_monthly_series_from_partial_start_calendar_day_overlap_v1(
            market=market,
            series_id=channel,
            reseated_monthly_values=reseated_monthly_values,
            plan_start_week=plan_start_week,
            calendar=calendar,
        )

    candidate_allocations = {
        c: _phase_channel(reseated_candidate[c], c) for c in meta.channels
    }
    reference_allocations = {
        c: _phase_channel(reseated_reference[c], c) for c in meta.channels
    }

    n_fourier_harmonics = spec.fourier_harmonics
    market_mask = np.array(frame["df"][spec.market_col] == market)
    historical_n_weeks = int(market_mask.sum())
    control_names = tuple(getattr(meta, "control_names", ()) or ())
    outcome_control_names = getattr(meta, "outcome_control_names", None) or {}
    has_exogenous_controls = bool(control_names) or bool(
        any(names for names in outcome_control_names.values())
    )
    future_mode = EXPLORATORY_MODE if has_exogenous_controls else OFFICIAL_MODE

    last_observed_controls = {}
    last_observed_outcome_controls = {}
    if has_exogenous_controls and market_mask.any():
        for i, name in enumerate(control_names):
            last_observed_controls[name] = float(
                frame["X_controls"][market_mask, i][-1]
            )
        for oid, names in outcome_control_names.items():
            for i, name in enumerate(names):
                last_observed_outcome_controls[f"{oid}.{name}"] = float(
                    frame["outcome_controls"][oid][market_mask, i][-1]
                )

    future_context = build_future_context(
        market=market,
        period_labels=weeks,
        historical_n_weeks=historical_n_weeks,
        n_fourier_harmonics=n_fourier_harmonics,
        outcome_ids=tuple(meta.outcome_ids),
        control_names=control_names,
        outcome_control_names=outcome_control_names,
        mode=future_mode,
        # REQ-PLANACT-001 (Decision 14): real, structured promotion-period
        # input for this plan window - materialize_promo_future returns
        # the identical all-zero shape when promotion_periods is empty, so
        # this is a strict superset of the previous unconditional zero.
        promo_future=materialize_promo_future(
            promotion_periods, outcome_ids=meta.outcome_ids, weeks=weeks
        ),
        eligible_for_hold_last_observed=frozenset(last_observed_controls)
        | frozenset(last_observed_outcome_controls),
        hold_last_observed=frozenset(last_observed_controls)
        | frozenset(last_observed_outcome_controls),
        last_observed_controls=last_observed_controls,
        last_observed_outcome_controls=last_observed_outcome_controls,
    )

    candidate_plan, candidate_provenance = build_governed_weekly_plan(
        market=market,
        meta=meta,
        channel_allocations=candidate_allocations,
        future_context=future_context,
        expected_n_fourier_columns=2 * n_fourier_harmonics,
    )
    reference_plan, reference_provenance = build_governed_weekly_plan(
        market=market,
        meta=meta,
        channel_allocations=reference_allocations,
        future_context=future_context,
        expected_n_fourier_columns=2 * n_fourier_harmonics,
    )

    # Terminal incremental carryover (WP5 of `Media-Mix-Lab: Coding LLM Next
    # Steps After PR #267`): the residual value that carries forward after
    # the plan window ends, under the SAME real future non-decision context
    # (continuing seasonality/controls) but zero future decision media -
    # reported structurally separately, never merged into the plan-window
    # result (`core.planning.terminal_response`'s own contract). Reuses the
    # exact assumption set (hold-last-observed controls, zero promo) the
    # analyst already acknowledged above for the plan window itself - no
    # new consent gate, since no new assumption is introduced.
    horizon_configuration = HorizonConfiguration()
    terminal_weeks = tuple(
        pd.date_range(
            weeks[-1],
            periods=horizon_configuration.terminal_continuation_weeks + 1,
            freq="7D",
        )[1:]
        .strftime("%Y-%m-%d")
        .tolist()
    )
    terminal_future_context = build_future_context(
        market=market,
        period_labels=terminal_weeks,
        historical_n_weeks=historical_n_weeks + len(weeks),
        n_fourier_harmonics=n_fourier_harmonics,
        outcome_ids=tuple(meta.outcome_ids),
        control_names=control_names,
        outcome_control_names=outcome_control_names,
        mode=future_mode,
        promo_future={
            oid: {w: 0.0 for w in terminal_weeks} for oid in meta.outcome_ids
        },
        eligible_for_hold_last_observed=frozenset(last_observed_controls)
        | frozenset(last_observed_outcome_controls),
        hold_last_observed=frozenset(last_observed_controls)
        | frozenset(last_observed_outcome_controls),
        last_observed_controls=last_observed_controls,
        last_observed_outcome_controls=last_observed_outcome_controls,
    )

    evaluation_context = SequentialEvaluationContext(
        model_identity=identity_kwargs.get("model_spec_fingerprint", "") or "unset",
        posterior_identity=identity_kwargs.get("posterior_fingerprint", "") or "unset",
        market=market,
        canonical_calendar_identity=f"{calendar.start}:{calendar.end}",
        historical_state_source_identity=identity_kwargs.get("data_fingerprint", "")
        or "unset",
        evaluation_semantics_identity="sequential_weekly",
        phasing_policy_identity="calendar_day_overlap_v1",
        future_assumption_identity=future_context.fingerprint(),
        cost_context_identity="default",
        counterfactual_policy_identity=counterfactual_policy.fingerprint() or "unset",
    )

    sc_input = SequentialManualScenarioInput(
        market=market,
        candidate_plan=candidate_plan,
        reference_plan=reference_plan,
        meta=meta,
        params=params,
        historical_frame=frame,
        horizon_configuration=horizon_configuration,
        evaluation_context=evaluation_context,
        weekly_plan_fingerprint=candidate_provenance.fingerprint(),
        reference_weekly_plan_fingerprint=reference_provenance.fingerprint(),
        future_context=future_context,
        terminal_future_context=terminal_future_context,
        planning_objective=planning_objective,
        activity_definitions=activity_definitions or None,
        counterfactual_policy=counterfactual_policy,
        cost_mapping_registry=governed_cost_registry,
        cost_context_id="default",
        cost_as_of_by_period=cost_as_of_by_period,
        artefact_kind="manual_scenario",
        value_mapping=value_mapping,
        currency_context=currency_context,
        trace=trace,
        n_posterior_draws=n_posterior_draws,
        **identity_kwargs,
        **scenario_governance_kwargs,
    )
    service_result = ScenarioService().evaluate_manual_sequential(sc_input)
    return (
        service_result,
        plan_start_week,
        weeks,
        future_context,
        terminal_future_context,
    )


st.set_page_config(
    page_title="Scenario Planner | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("scenario_planner")
render_page_header(
    "scenario_planner",
    task_prompt="What spend decision should be evaluated under current evidence?",
)
render_workspace_note(
    "Plan versus result",
    "Edit the spend plan below; outcomes, economics, and optimisation outputs are calculated from the approved fit and remain distinct from saved scenarios.",
    kind="derived",
)
st.info(
    "**Two evaluation methods are available below: steady-state monthly "
    "approximation, and sequential weekly.** The spend plan grid and optimiser "
    "tabs are shared; how a plan is calculated depends on the evaluation method "
    "you choose under Planning assumptions. Method-specific detail is shown "
    "once you choose one."
)

_dashboard_trained = all(
    get_state(key) is not None
    for key in ("trace", "frame", "model_meta", "posterior_params")
)
with st.container(border=True):
    st.markdown("### Allocation desk")
    _desk_status = st.columns(4)
    _desk_status[0].metric(
        "Model approval",
        "Current"
        if get_state("model_approval")
        # Overnight UI/UX pass (2026-08-29): "Needs review" implies an
        # existing model is awaiting an approval decision. Before any model
        # has even been fitted (checked via the same _dashboard_trained
        # gate used by "Plan state" below), there is nothing to review yet
        # - say so plainly rather than implying a pending action that does
        # not exist.
        else ("Needs review" if _dashboard_trained else "Not started"),
    )
    _desk_status[1].metric(
        "Plan state", "Editable" if _dashboard_trained else "Blocked"
    )
    _selected_evaluation_method = str(
        st.session_state.get("scenario_evaluation_method") or ""
    )
    _desk_status[2].metric(
        "Evaluation method",
        (
            {
                "steady_state_monthly": "Steady-state monthly",
                "sequential_weekly": "Sequential weekly",
            }.get(_selected_evaluation_method, "Choose below")
            if _dashboard_trained
            else "Unavailable"
        ),
    )
    _desk_status[3].metric("Saved scenarios", len(get_state("scenarios") or []))
    st.caption(
        "Decision flow: current reference plan → editable plan → calculated result → "
        "constrained or benchmark proposal → explicitly saved scenario. Calculated and "
        "optimiser outputs remain read-only until the plan is saved."
    )

frame = get_state("frame")
meta = get_state("model_meta")
params = get_state("posterior_params")
spec_dict = get_state("model_spec")
trace = get_state("trace")
activity_definitions = [
    ActivityDefinition.from_dict(item)
    for item in (get_state("activity_definitions") or [])
]
search_objects = [
    SearchObjectDefinition.from_dict(item)
    for item in (get_state("search_objects") or [])
]
coverage_matrix_dict = get_state("variable_coverage_matrix")
cost_mapping_registry = CostMappingRegistry.from_dict(get_state("media_cost_mappings"))
governed_cost_registry = (
    cost_mapping_registry if cost_mapping_registry.to_dict()["mappings"] else None
)
# G2A.7a (DEFECT-7): load outcome approvals from session state
outcome_approvals = [
    OutcomeApproval.from_dict(item) for item in (get_state("outcome_approvals") or [])
]
outcome_definitions = [outcome for outcome in (get_state("outcome_definitions") or [])]
outcome_groups_at_fit = getattr(meta, "outcome_groups_at_fit", None) or []
outcome_group_treatments_at_fit = (
    getattr(meta, "outcome_group_treatments_at_fit", None) or []
)
outcome_labels = _scenario_outcome_labels(
    outcome_definitions,
    outcome_groups_at_fit,
)
nbt_completeness_metadata = get_state("net_billthrough_metadata")
if frame is None or meta is None or params is None:
    st.markdown("---")
    render_empty_state(
        "No fitted model yet. Complete Fit Model first.",
        button_label="Go to Fit Model",
        target_key="model_training",
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
            official_preparation_evidence=get_state("official_preparation_result"),
        ),
        "posterior_fingerprint": fingerprint_posterior(params),
    }

# PR 82C: validation_policy / approval_readiness are the sole policy/
# readiness state keys (matching pages/06_Diagnostics.py) - rehydrated once,
# here, through the shared fail-closed loaders (PR 88A: also used by
# Diagnostics, Curve Bank, and Project Import) and reused as these same two
# objects for the approval gate below AND every planning/uncertainty call
# further down the page, so official planning can never end up proving
# governance against two different resolved policy/readiness objects in the
# same rerun, and a malformed policy/readiness is reported rather than
# crashing the page.
validation_policy_dict = get_state("validation_policy")
current_policy, _policy_config_error = load_threshold_policy(validation_policy_dict)
if _policy_config_error:
    st.warning(
        "The configured validation policy is malformed and cannot be used: "
        f"{_policy_config_error}"
    )

approval_readiness_dict = get_state("approval_readiness")
current_readiness, _readiness_config_error = load_approval_readiness(
    approval_readiness_dict
)
if _readiness_config_error:
    st.warning(
        f"The stored approval readiness is malformed and cannot be used: "
        f"{_readiness_config_error}"
    )

approval_dict = get_state("model_approval")
# PR 82C: require_matching_approval (already used by curve_bank/optimization
# to gate real use of an approval) re-verifies the FULL chain - model
# identity AND, for policy-backed approvals, that the bound readiness still
# exists, is still overall_ready, and its policy/model-identity fingerprints
# still match the current policy and model - not just model identity alone.
# A missing, stale, expired, or mismatched policy/readiness is rejected
# here, up front, rather than surfacing deep inside a planning call.
approval_invalid_reason: str | None = None
approval_matches_current = False
if approval_dict is not None and current_identity is not None:
    try:
        require_matching_approval(
            ModelApproval.from_dict(approval_dict),
            approval_readiness=current_readiness,
            current_policy=current_policy,
            **current_identity,
        )
        approval_matches_current = True
    except (ApprovalMismatchError, ValidationPolicyBlockedError) as exc:
        approval_invalid_reason = str(exc)

if not approval_dict:
    st.warning(
        "This model hasn't been approved yet. Approve it on Model Diagnostics before planning scenarios - "
        "only an approved model's results may drive the planner."
    )
    if st.button("Go to Model Diagnostics"):
        st.switch_page("pages/06_Diagnostics.py")
    st.stop()
if not approval_matches_current:
    st.warning(
        "This model's approval no longer matches the current fitted model, policy, or "
        "readiness evidence"
        + (f": {approval_invalid_reason}" if approval_invalid_reason else "")
        + " - the model must be reviewed and approved again on Model Diagnostics before "
        "planning scenarios."
    )
    if st.button("Go to Model Diagnostics", key="stale_approval_diagnostics"):
        st.switch_page("pages/06_Diagnostics.py")
    st.stop()

approval = ModelApproval.from_dict(approval_dict)
# G2A.7a.1 (section 4.1): model-identity kwargs ONLY - governance kwargs
# (outcome_approvals/governance_mode) are built separately, after the
# governance-mode radio is rendered below, and must never be merged into
# this dict - passing both `identity_kwargs` and an explicit
# `governance_mode=` to the same call raises "got multiple values for
# keyword argument 'governance_mode'" (the confirmed G2A.7a.1 P0 defect).
identity_kwargs = dict(
    model_type=model_type,
    approval=approval,
    **current_identity,
)

spec = ModelSpec.from_dict(spec_dict)
ltv = spec.segment_ltv

# PR E.2 requirement #10: block planning outright when the live outcome
# catalogue has drifted from what `meta` was actually fit on in a
# calculation-relevant way - a stale in-memory trace must not be plannable
# against once its catalogue has genuinely changed, even though the trace
# object itself is unaffected. Informational-only drift (new/excluded-from-
# next-fit) does not block - see core.outcomes.has_blocking_drift.
if render_drift_status(
    resolve_outcome_definitions(
        get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv
    ),
    meta,
    blocking=True,
):
    st.stop()

render_definition_help(
    "a scenario",
    "A named plan or calculated proposal that records the assumptions, governance context, and outputs used for a planning decision.",
)
render_definition_help(
    "a constraint",
    "A limit or rule applied to a plan, such as a spend bound, share limit, or operational cap.",
)
render_definition_help(
    "an incremental outcome",
    "The additional outcome attributed to the proposed plan relative to the approved counterfactual under the selected definition.",
)
render_decision_help(
    "How should I read plan states?",
    controls="The difference between the current reference, your edited inputs, calculated outputs, proposed optimised plans, and saved scenarios.",
    why="A calculated result is not automatically a proposal, and a proposal is not saved until you explicitly choose to save it.",
    options={
        "Current": "The reference state inherited from the approved fit and current planning context.",
        "Edited": "The plan inputs you are changing before evaluation.",
        "Calculated": "Read-only outputs calculated from the edited plan.",
        "Proposed": "A constrained or unconstrained benchmark plan produced by the optimiser for review.",
        "Saved": "A named scenario explicitly persisted for later comparison or export.",
    },
    normal_path="Review the current state, edit inputs, calculate, inspect constraints and economics, review any proposal, then save only the scenario you intend to keep.",
    downstream="Each state carries different assumptions and governance dependencies; only the explicitly saved scenario becomes part of the project's planning record.",
    invalidates="Changing the approved fit, policy, cost mapping, counterfactual, or outcome authorisation invalidates affected planning results and may require recalculation or re-approval.",
)

with SectionCard(
    "Plan setup",
    description="Which market and time window this plan (and every tab below) covers.",
):
    c1, c2, c3 = st.columns(3)
    market = c1.selectbox("Market *", meta.markets)
    start_month = c2.date_input(
        "Plan start month *", value=pd.Timestamp.today().replace(day=1)
    )
    n_months = c3.number_input(
        "Number of months *", min_value=1, max_value=24, value=12
    )

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
            st.dataframe(
                tier_df, width="stretch", column_config=dataframe_column_config(tier_df)
            )
            if (tier_df["curve_status"] == "Transferred estimate").any():
                st.caption(
                    "One or more channels above are a **transferred estimate** for this market - "
                    "not enough local data to estimate a market-specific curve confidently. Plan "
                    "against these with extra caution until more local evidence is available."
                )

month_dates = pd.date_range(pd.Timestamp(start_month), periods=n_months, freq="MS")
months = [d.strftime("%Y-%m") for d in month_dates]

# --- Reference context per month: real calendar seasonality for each forecast
# month, trend held at the last observed level, promo/controls at their
# historical means - a documented planning approximation, not a forecast of
# future promo/control values.
market_mask = np.array(frame["df"][spec.market_col] == market)
last_trend = float(frame["trend"][market_mask][-1]) if market_mask.any() else 1.0

# UX-020: disclose when some or all of the plan lies beyond the model's
# observed data, mirroring the "Beyond observed support (extrapolated)"
# disclosure already used on curve pages (application/curve_annotations.py)
# rather than inventing new wording. Informational severity only (spec
# section 12) - this does not mean the model is invalid, and future
# conditions are not claimed to be known; the existing flat-trend safeguard
# (trend held at its last observed level, only calendar seasonality varies -
# see comment above) already bounds the risk this discloses, so
# `derive_plan_period_disclosure` states that mitigation rather than raising
# an alarm. Shown only when it is actually relevant to this plan's dates -
# fully in-sample scenarios get no caption at all.
_observed_dates_for_market = (
    frame["dates"][market_mask] if market_mask.any() else frame["dates"]
)
_plan_period_disclosure = derive_plan_period_disclosure(
    _observed_dates_for_market,
    month_dates,
    plan_start_label=months[0],
    plan_end_label=months[-1],
)
if _plan_period_disclosure is not None and _plan_period_disclosure.message:
    st.info(_plan_period_disclosure.message)
mean_promo = {
    oid: float(frame["promo"][market_mask, i].mean()) if market_mask.any() else 0.0
    for i, oid in enumerate(meta.outcome_ids)
}
mean_controls = {
    name: float(frame["X_controls"][market_mask, i].mean())
    if (market_mask.any() and frame["X_controls"].shape[1])
    else 0.0
    for i, name in enumerate(frame.get("control_names") or [])
}
mean_outcome_controls = {
    oid: {
        name: float(frame["outcome_controls"][oid][market_mask, i].mean())
        if market_mask.any()
        else 0.0
        for i, name in enumerate(frame.get("outcome_control_names", {}).get(oid, []))
    }
    for oid in (frame.get("outcome_controls") or {})
}

reference_context_by_month = {}
for d, m in zip(month_dates, months):
    fourier_vec = create_fourier_features_from_calendar(
        pd.Series([d]), n_harmonics=spec.fourier_harmonics
    )[0]
    reference_context_by_month[m] = {
        "trend": last_trend,
        "fourier": fourier_vec,
        "promo": mean_promo,
        "controls": mean_controls,
        "outcome_controls": mean_outcome_controls,
    }

# --- Current/baseline plan: recent average weekly model input for this
# market, held flat. `frame["X_media"]` is in each channel's fitted
# model-input unit, not currency - a cost-bearing activity's default is
# only ever derived through its governed cost mapping's
# media_input_to_spend, never by treating the raw model input as spend
# (PR G2A.6 workstream C). Activities without a resolvable effective
# mapping default to 0 rather than mislabel media-input units as currency.
#
# The mapping used for that conversion is resolved as of the most recent
# *historical* observation for this market, never the future plan-start
# date - applying a not-yet-effective future cost assumption to historical
# delivery would misstate the reference plan (PR G2A.6b workstream 2).
# There is no genuine historical spend series retained separately from the
# fitted model input in this project's data model, so this reverse
# conversion remains an estimated reference, not a record of actual spend.
by_input_for_seeding = (
    activity_by_model_input(activity_definitions, market)
    if activity_definitions
    else {}
)
if market_mask.any():
    avg_weekly_media_input = frame["X_media"][market_mask].mean(axis=0)
    historical_reference_date = pd.Timestamp(frame["dates"][market_mask][-1])
else:
    avg_weekly_media_input = frame["X_media"].mean(axis=0)
    historical_reference_date = (
        pd.Timestamp(frame["dates"][-1]) if len(frame["dates"]) else None
    )
avg_weekly_by_channel = dict(zip(meta.channels, avg_weekly_media_input))
seed_as_of = (
    historical_reference_date.strftime("%Y-%m-%d")
    if historical_reference_date is not None
    else None
)
default_by_channel, unmapped_cost_bearing_channels = (
    seed_monetary_and_quantity_defaults(
        avg_weekly_media_input=avg_weekly_by_channel,
        activity_definitions=activity_definitions,
        market=market,
        cost_mapping_registry=governed_cost_registry,
        cost_context_id="default",
        as_of=seed_as_of,
    )
)
default_monthly = [default_by_channel[c] for c in meta.channels]
if unmapped_cost_bearing_channels:
    st.caption(
        "Defaulted to 0 for cost-bearing activities with no approved, effective "
        "cost mapping (never inferred from the raw model input): "
        + ", ".join(
            model_input_display_label(
                c, activity_definitions=activity_definitions, market=market
            )
            for c in sorted(unmapped_cost_bearing_channels)
        )
        + ". Configure a mapping on Activity Mapping to seed a spend default."
    )
if historical_reference_date is not None and any(
    definition.is_cost_bearing for definition in by_input_for_seeding.values()
):
    st.caption(
        "Monetary defaults for cost-bearing activities are an **estimated reference**: "
        f"historical average model input as of {historical_reference_date.date()} "
        "(the most recent observed period for this market), converted through the cost "
        "mapping effective on that date - not a record of actual historical spend."
    )

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
        cost_df = extract_cost_per_unit_series(
            frame["df"], spec.date_col, spec.market_col, market, cfg
        )
        trend = historical_cost_trend(cost_df, spec.date_col)
    except ValueError:
        continue
    if trend["avg_cost_per_unit"]:
        media_unit_channels[ch] = {
            "unit_type": cfg.unit_type or "units",
            "avg_cost_per_unit": trend["avg_cost_per_unit"],
        }

with SectionCard(
    "Spend plan - editable decision (monthly, by channel)",
    description=(
        "This grid is the plan you control - edit values directly for manual mode; the "
        "same plan seeds the optimisation tabs below. Predicted outcomes and economics "
        "further down are calculated *from* this grid, never editable themselves."
    ),
):
    planning_mode = "Spend"
    if media_unit_channels:
        planning_mode = st.radio(
            "Planning mode",
            ["Spend", "Media units"],
            horizontal=True,
            help=(
                "Media units mode converts to/from spend using each channel's average historical "
                "cost per unit - available for: "
                + ", ".join(sorted(media_unit_channels))
                + ". "
                "Other channels stay in spend terms either way. The two modes are never mixed in "
                "one column - each column header states which unit it's currently in."
            ),
        )

    plan_df = st.session_state[plan_key]
    if planning_mode == "Media units":
        display_df = plan_df.copy()
        for ch, info in media_unit_channels.items():
            display_df[ch] = plan_df[ch] / info["avg_cost_per_unit"]
        label_overrides = {
            ch: (
                f"{model_input_display_label(ch, activity_definitions=activity_definitions, market=market)} "
                f"({info['unit_type']})"
            )
            for ch, info in media_unit_channels.items()
        }
        edited_display = st.data_editor(
            display_df,
            width="stretch",
            key=f"editor_{plan_key}_units",
            column_config=dataframe_column_config(
                display_df, label_overrides=label_overrides
            ),
        )
        edited = edited_display.copy()
        for ch, info in media_unit_channels.items():
            edited[ch] = edited_display[ch] * info["avg_cost_per_unit"]
        st.caption(
            "Cost-per-unit assumptions in use: "
            + ", ".join(
                f"{model_input_display_label(ch, activity_definitions=activity_definitions, market=market)}"
                f" = {info['avg_cost_per_unit']:,.2f} / {info['unit_type']}"
                for ch, info in media_unit_channels.items()
            )
        )
    else:
        edited = st.data_editor(
            plan_df,
            width="stretch",
            key=f"editor_{plan_key}",
            column_config=dataframe_column_config(plan_df),
        )
    st.session_state[plan_key] = edited
spend_plan = {m: {c: float(edited.loc[m, c]) for c in meta.channels} for m in months}
activity_map = (
    activity_by_model_input(activity_definitions, market)
    if activity_definitions
    else {}
)
scenario_plan = None
if activity_definitions:
    missing_activity_inputs = set(meta.channels) - set(activity_map)
    if missing_activity_inputs:
        st.error(
            "Activity governance is incomplete for model inputs: "
            f"{sorted(missing_activity_inputs)}. Complete the required "
            "activity register before planning."
        )
        st.stop()
if activity_map:
    monetary_decisions = {}
    activity_quantities = {}
    for period, values in spend_plan.items():
        monetary_decisions[period] = {}
        activity_quantities[period] = {}
        for column, value in values.items():
            definition = activity_map[column]
            target = (
                monetary_decisions
                if definition.is_cost_bearing
                else activity_quantities
            )
            target[period][definition.activity_id] = value
    scenario_plan = ScenarioPlan(
        monetary_decisions_by_period=monetary_decisions,
        activity_quantity_assumptions_by_period=activity_quantities,
        activity_units={
            definition.activity_id: (
                "local_currency"
                if definition.is_cost_bearing
                else "model_input_quantity"
            )
            for definition in activity_map.values()
        },
    )
    st.caption(
        "Cost-bearing activity is stored as monetary decisions; response-only "
        "and non-applicable activity is stored separately as model-input quantities."
    )


def _validated_stored_mapping(
    state_key: str, *, label: str
) -> tuple[dict | None, bool]:
    """Corrective review finding: `config/<state_key>.json` round-trips
    through `import_project()` as whatever JSON value it actually contains -
    a bundle with a structurally malformed file (e.g. a JSON array or
    string, not an object) restores that raw non-mapping value into session
    state as-is. Calling `.get()` or `**`-unpacking it directly then crashes
    the page with an AttributeError/TypeError instead of the fail-closed
    warning every other malformed-evidence path in this app gives.

    Returns ``(value, is_malformed)``. A non-mapping stored value is fresh
    evidence of corruption, not the same as nothing having been stored at
    all - a caller that collapsed both cases to `None` would let a
    corrupted array/string be silently treated as "no evidence, safe to
    default", the WEAKEST possible handling, while a dict with one invalid
    field correctly gets the STRONGEST (blocked until explicitly repaired).
    Callers must route `is_malformed=True` through the same blocking path
    as any other invalid evidence, never the same path as `value is None`
    from nothing having been stored."""
    stored = get_state(state_key)
    if stored is not None and not isinstance(stored, dict):
        st.warning(
            f"This project's stored {label} is malformed (expected an "
            f"object, got {type(stored).__name__})."
        )
        return None, True
    return stored, False


def _invalidate_stale_cached_result(
    state_key: str,
    result: dict | None,
    *,
    current_governance_mode: str,
    current_counterfactual_fingerprint: str,
) -> dict | None:
    """Corrective review finding: a cached optimiser result
    (`st.session_state["constrained_result"]`/`"unconstrained_result"`) was
    only ever invalidated on a governance_mode change - an analyst changing
    the counterfactual-policy radio after running an optimisation left the
    stale result (still carrying the OLD policy's fingerprint) fully
    displayable and saveable, with the project's now-current policy already
    silently diverged from it. Clears and returns `None` for `result` the
    same way the governance_mode check already does, the moment either has
    drifted since the result was computed."""
    if not result:
        return result
    if result.get("governance_mode") != current_governance_mode:
        st.session_state[state_key] = None
        st.info(
            "Planning use changed since this result was computed - re-run "
            "the optimisation to refresh it."
        )
        return None
    cached_cf_fp = governance_deps_from_optimizer_result(result).get(
        "counterfactual_policy_fingerprint"
    )
    if cached_cf_fp and cached_cf_fp != current_counterfactual_fingerprint:
        st.session_state[state_key] = None
        st.info(
            "The project's counterfactual policy changed since this result "
            "was computed - re-run the optimisation to refresh it."
        )
        return None
    return result


st.markdown("---")
st.markdown("### Planning assumptions & use")
st.caption(
    "These are assumptions the plan is evaluated under, not decisions in the spend-plan "
    "grid above - the comparison baseline, planning use, and optimisation objective "
    "below apply to every tab further down."
)

_DEMAND_CAPTURE_RULE_OPTIONS = ["hold_plan", "zero"]
# PR 125A: seed the widget's default from the project-level counterfactual
# policy restored by a bundle import, not always the first option - so a
# resumed session shows the same selection that was exported, and re-saves
# the identical CounterfactualPolicy (same fingerprint) until the analyst
# deliberately changes it.
_stored_cf_policy_dict, _cf_policy_mapping_malformed = _validated_stored_mapping(
    "counterfactual_policy", label="counterfactual policy"
)
_stored_demand_capture_rule = None
# Corrective review finding: this radio can only ever choose between two of
# CounterfactualPolicy's four demand_capture_rule values (e.g. an imported/
# fixture-built policy's default is "require_explicit", never offered here)
# and never edits fixed_activity_rule / mediator_rule / control_rule /
# event_rule / explicit_values_by_period at all. Rendering the widget always
# returns one of its two options regardless, so treating that return value
# as authoritative whenever the stored policy uses a value or field this
# widget doesn't expose would silently narrow the project's real policy the
# moment this page loads - staling every official scenario that depended on
# the policy it just overwrote, with no explicit choice behind it. Fresh
# review finding: a stored policy can also be a structurally valid mapping
# that is simply not a valid CounterfactualPolicy (e.g. an invalid
# fixed_activity_rule) - checking demand_capture_rule membership alone
# isn't enough; the whole dict must round-trip through from_dict() first.
_cf_policy_safe_to_sync = True
_cf_policy_problem: str | None = None
if _cf_policy_mapping_malformed:
    # Fresh review finding: a non-mapping stored value must be routed
    # through the same "blocked, explicit repair required" path as any
    # other invalid evidence below - never silently treated the same as
    # "nothing was ever stored" (which would let a corrupted array/string
    # be quietly replaced with a fresh default and continue).
    _cf_policy_safe_to_sync = False
    _cf_policy_problem = "is malformed and cannot be used"
elif _stored_cf_policy_dict:
    _stored_demand_capture_rule = _stored_cf_policy_dict.get("demand_capture_rule")
    try:
        CounterfactualPolicy.from_dict(_stored_cf_policy_dict)
    except (TypeError, ValueError) as exc:
        _cf_policy_safe_to_sync = False
        _cf_policy_problem = f"is invalid and cannot be used ({exc})"
    if _stored_demand_capture_rule not in (None, *_DEMAND_CAPTURE_RULE_OPTIONS):
        _cf_policy_safe_to_sync = False
        _cf_policy_problem = (
            "currently uses demand_capture_rule="
            f"{_stored_demand_capture_rule!r}, which this control does not "
            "offer (supported here: hold_plan, zero)"
        )
if _cf_policy_problem:
    st.warning(
        f"This project's counterfactual policy {_cf_policy_problem}. The "
        "existing policy - including any other governance fields this page "
        "does not expose - is preserved untouched until you explicitly "
        "replace it below."
    )
_demand_capture_rule_index = (
    _DEMAND_CAPTURE_RULE_OPTIONS.index(_stored_demand_capture_rule)
    if _stored_demand_capture_rule in _DEMAND_CAPTURE_RULE_OPTIONS
    else 0
)
demand_capture_rule = st.radio(
    "How should demand-capture activity behave in the comparison baseline?",
    _DEMAND_CAPTURE_RULE_OPTIONS,
    index=_demand_capture_rule_index,
    horizontal=True,
    format_func=lambda value: {
        "hold_plan": "Hold at the candidate level",
        "zero": "Set to zero for sensitivity",
    }[value],
    help=(
        "Demand-capture activity is never zeroed implicitly. Hold it at the "
        "candidate level for the ordinary comparison, or set it to zero only "
        "as an explicitly labelled sensitivity assumption. This choice is "
        "stored with the scenario and objective."
    ),
)
if _cf_policy_safe_to_sync:
    # Safe: the stored policy (if any) is already a valid CounterfactualPolicy
    # whose demand_capture_rule is one of this widget's own options, so
    # keeping it in sync on every rerun never discards a choice the widget
    # itself didn't just make. Every OTHER field (fixed_activity_rule,
    # mediator_rule, control_rule, event_rule, explicit_values_by_period,
    # rationale) is carried over from whatever was already stored - e.g. an
    # import - never silently reset to CounterfactualPolicy's own dataclass
    # defaults.
    try:
        counterfactual_policy = CounterfactualPolicy.from_dict(
            {
                **(_stored_cf_policy_dict or {}),
                "demand_capture_rule": demand_capture_rule,
            }
        )
    except (TypeError, ValueError):
        counterfactual_policy = CounterfactualPolicy(
            demand_capture_rule=demand_capture_rule
        )
    # PR 125A: the project-level policy every official scenario's saved
    # counterfactual identity is verified against on import - see
    # core.persistence's module docstring and audit_project_resumability().
    set_state("counterfactual_policy", counterfactual_policy.to_dict())
elif st.button("Replace this project's counterfactual policy with the selection above"):
    counterfactual_policy = CounterfactualPolicy(
        demand_capture_rule=demand_capture_rule
    )
    set_state("counterfactual_policy", counterfactual_policy.to_dict())
    st.rerun()
else:
    # Fresh review finding: merely declining to persist a substitute policy
    # wasn't enough - the rest of this page (evaluation, saving,
    # optimisation) still ran against a fallback CounterfactualPolicy that
    # was never the analyst's explicit choice, so a scenario could still be
    # saved and exported carrying a fingerprint that matches neither the
    # invalid/unsupported stored policy nor any policy the analyst actually
    # approved. Block the entire planning workflow below this point until
    # the analyst explicitly replaces or repairs the policy - the same
    # st.stop() gate this page already uses for "no trained model yet".
    st.error(
        "Planning is blocked until the counterfactual policy above is "
        "replaced or repaired - see the warning above for why the stored "
        "policy can't be used as-is."
    )
    st.stop()

# G2A.7a.1 (section 4.2): one source of truth. The radio's own return
# value IS the authoritative governance mode for this rerun - it is never
# read from session state before this point, and every call below is built
# from this value, not from a stale read captured earlier in the script.
governance_mode = st.radio(
    "Planning use",
    ["official", "exploratory"],
    horizontal=True,
    key="scenario_governance_mode",
    format_func=lambda value: {
        "official": "Official planning",
        "exploratory": "Exploratory sensitivity",
    }[value],
    help=(
        "Official planning blocks optimisation against any activity whose governance "
        "isn't approved (draft or rejected model role, economic treatment, or "
        "planning eligibility must not drive an official recommendation), and "
        "against any target outcome without a matching, active approval. "
        "Exploratory sensitivity skips both checks - always visibly labelled below, "
        "never a silent fallback."
    ),
)
if governance_mode == "exploratory":
    st.warning(
        "**Exploratory mode** - this run may use activity or outcome governance "
        "that is not yet approved. Results here are a sensitivity, not an "
        "official recommendation."
    )
# G2A.7a.1 (section 4.1, 4.2): governance kwargs, built AFTER the radio so
# every consumer below sees the same rerun's selection - separate from
# identity_kwargs (model identity only) so no call ever receives
# governance_mode twice.
# PR 82C: approval_readiness/current_policy reuse the exact same
# current_readiness/current_policy objects rehydrated once above for the
# approval gate - the single governance proof for this rerun, shared by the
# gate, manual evaluation, both optimiser modes, and posterior uncertainty.
scenario_governance_kwargs = dict(
    outcome_approvals=outcome_approvals,
    governance_mode=governance_mode,
    nbt_completeness_metadata=nbt_completeness_metadata,
    approval_readiness=current_readiness,
    current_policy=current_policy,
)
cost_as_of_by_month = {
    month: f"{month}-01" if len(month) == 7 else month for month in months
}

# WP5 (`Media-Mix-Lab: Coding LLM Next Steps Post PR262`): the manual-plan
# evaluation method - steady-state (existing, default, every other tab
# still uses it exclusively) or sequential weekly (new). Never silently
# switches: the radio's own return value is the single source of truth for
# this rerun, exactly like governance_mode above. Sequential weekly only
# evaluates the "Edited plan and calculated result" tab in this release -
# the constrained/unconstrained optimiser tabs remain steady-state-only
# (sequential optimisation is a separate, not-yet-implemented work
# package).
st.markdown("#### Evaluation method")
evaluation_method = st.radio(
    "Manual plan evaluation method",
    ["steady_state_monthly", "sequential_weekly"],
    horizontal=True,
    key="scenario_evaluation_method",
    format_func=lambda value: {
        "steady_state_monthly": "Steady-state monthly approximation",
        "sequential_weekly": "Sequential weekly",
    }[value],
    help=(
        "Sequential weekly simulates real week-by-week media carry-in from "
        "this market's own historical spend, continuing immediately after "
        "the fitted data ends - recommended for timing-aware decisions. "
        "Steady-state monthly approximates each month independently at its "
        "adstock steady state and cannot answer starting carryover, "
        "month-by-month timing, short/long response horizons, or terminal "
        "carryover. Only the 'Edited plan and calculated result' tab below "
        "offers sequential weekly in this release - the optimiser tabs "
        "remain steady-state only."
    ),
)
if evaluation_method == "steady_state_monthly":
    st.info(
        "**Steady-state monthly approximation** is selected.\n"
        "- Each month is approximated independently.\n"
        "- It uses the fitted model's steady-state response.\n"
        "- It does not reproduce starting carryover or sequential month-to-month "
        "timing."
    )
else:
    st.info(
        "**Sequential weekly** is selected.\n"
        "- It continues from this market's own historical fitted state.\n"
        "- It models real week-by-week media carryover.\n"
        "- It supports short/long response horizons and terminal carryover.\n"
        "- Constrained and unconstrained optimisation below remain "
        "steady-state-monthly only in this release - not available for "
        "sequential weekly."
    )

# G2A.7a.7: build objective options from fitted outcome catalogue
_fitted_outcome_ids = set(meta.outcome_ids) if hasattr(meta, "outcome_ids") else set()
_has_fh_gsa = bool(fh_gsa_outcome_ids(meta)) if hasattr(meta, "outcome_ids") else False
_has_dna_kit_segments = bool(dna_kit_sale_outcome_ids(meta))
_has_fh_signups = bool(fh_signup_outcome_ids(meta))
_has_fh_nbt = bool(fh_net_billthrough_outcome_ids(meta))
_objective_options = []
if _has_fh_gsa:
    _objective_options.append("fh_gsa")
if _has_dna_kit_segments:
    _objective_options.append("dna_kits")
if _has_fh_signups:
    _objective_options.append("fh_signups")
if _has_fh_nbt:
    _objective_options.append("fh_net_billthrough")
_objective_options.append("expected_value")  # Always available if value config exists
# REQ-OPT-001 (Decision 16): the closed objective-kind vocabulary's three
# value-based kinds beyond "maximise revenue" (which is already the
# existing "expected_value" objective, per core.optimization_objective_
# vocabulary's own resolution - not a new, separately-invented value
# definition). Always offered - never silently hidden - even though
# maximise_profit is always blocked and maximise_roi/minimise_cpa are
# gated on every considered channel being cost-bearing; see
# `_objective_vocab_resolution` below for the disclosed reason in each
# case.
_objective_options.extend(["maximise_profit", "maximise_roi", "minimise_cpa"])
_objective_labels = {
    "fh_net_billthrough": "Maximise incremental Family History net bill-through",
    "fh_gsa": "Maximise Family History GSAs",
    "fh_signups": "Maximise Family History sign-ups",
    "dna_kits": "Maximise DNA kit sales",
    "expected_value": "Maximise LTV-weighted expected value",
    "maximise_profit": "Maximise profit",
    "maximise_roi": "Maximise ROI",
    "minimise_cpa": "Minimise CPA",
}
objective_display_kind = st.radio(
    "Optimisation objective",
    _objective_options,
    horizontal=True,
    format_func=lambda x: _objective_labels[x],
    help=FIELD_HELP["ltv"],
)
# REQ-OPT-001 Requirement 1 (Decision 16): maximise_revenue/maximise_profit/
# maximise_roi/minimise_cpa all resolve to the same governed value/return
# definition as the existing "expected_value" objective (core.
# optimization_objective_vocabulary.resolve_objective_kind resolves every
# one of them via the real resolve_planning_objective(objective_kind=
# "expected_value", ...)) - so every downstream expected_value computation
# in this page (value mapping derivation, currency derivation, the value-
# assumptions editor) already correctly drives all four once aliased here.
# `objective_display_kind` (what the analyst actually asked for) is kept
# separately for labelling and for the vocabulary's own gating check below -
# never overwritten, so a blocked/gated choice is never silently relabelled
# as something else.
_OBJECTIVE_VOCAB_LEGACY_ALIAS = {
    "maximise_profit": "expected_value",
    "maximise_roi": "expected_value",
    "minimise_cpa": "expected_value",
}
objective = _OBJECTIVE_VOCAB_LEGACY_ALIAS.get(
    objective_display_kind, objective_display_kind
)
# G2A.7a.5: build value weights from outcome catalogue
value_weights_by_outcome_id: dict[str, float] = {}
if hasattr(meta, "outcome_catalogue_at_fit") and meta.outcome_catalogue_at_fit:
    for outcome in meta.outcome_catalogue_at_fit:
        weight = getattr(outcome, "value_weight", None)
        if weight is not None:
            value_weights_by_outcome_id[outcome.outcome_id] = weight

# G2A.7a.10 (brief section 10.1): derive value currency from the exact
# selected/eligible *target* outcome IDs for this objective, not the whole
# fitted catalogue - a non-target outcome priced in another currency must
# never block an otherwise single-currency objective.
if objective in ("expected_value", "value"):
    _target_ids_for_value = set(
        eligible_outcome_ids(meta, list(meta.outcome_ids), "include_in_value")
    )
else:
    _target_resolvers_by_objective = {
        "fh_gsa": fh_gsa_outcome_ids,
        "fh_signups": fh_signup_outcome_ids,
        "fh_net_billthrough": fh_net_billthrough_outcome_ids,
        "dna_kits": dna_kit_sale_outcome_ids,
    }
    _target_ids_for_value = set(
        _target_resolvers_by_objective.get(objective, lambda m: [])(meta)
    )

value_currency = None
if hasattr(meta, "outcome_catalogue_at_fit") and meta.outcome_catalogue_at_fit:
    target_currencies = {
        getattr(o, "value_currency", None)
        for o in meta.outcome_catalogue_at_fit
        if o.outcome_id in _target_ids_for_value and getattr(o, "value_currency", None)
    }
    if len(target_currencies) == 1:
        value_currency = target_currencies.pop()
    elif len(target_currencies) > 1:
        value_currency = (
            None  # Mixed currencies among targets need an explicit FX layer
        )


def _render_scenario_value_assumptions_editor(
    meta, target_ids_for_value, default_currency
):
    """WP2G (`REQ-ECON-003` Requirement 5): explicit forward economic
    value assumptions for this scenario - never extrapolated from
    historical valuation. Saved (session-state key
    "scenario_value_assumptions", exported/imported with the project
    bundle exactly like value_mapping/currency_context) only when the
    analyst explicitly clicks Save - live widget edits never silently
    apply to evaluation before being confirmed."""
    fh_ids = sorted(
        set(fh_gsa_outcome_ids(meta))
        | set(fh_signup_outcome_ids(meta))
        | set(fh_net_billthrough_outcome_ids(meta))
    )
    dna_ids = sorted(dna_kit_sale_outcome_ids(meta))
    fh_target_ids = [oid for oid in fh_ids if oid in target_ids_for_value]
    dna_target_ids = [oid for oid in dna_ids if oid in target_ids_for_value]
    if not fh_target_ids and not dna_target_ids:
        return

    outcome_labels = {
        o.outcome_id: (o.segment or o.outcome_id)
        for o in (meta.outcome_catalogue_at_fit or [])
    }
    stored = get_state("scenario_value_assumptions") or {}

    with st.expander("Economic value assumptions (forward, for this scenario)"):
        st.caption(
            "Explicit future value assumptions for this scenario only - "
            "never derived or extrapolated from historical valuation "
            "data. Distinct from the Results page's historical ROI, "
            "which reports what already happened."
        )
        currency = st.text_input(
            "Currency (ISO-3)",
            value=stored.get("currency") or default_currency or "",
            key="sva_currency",
            max_chars=3,
        ).upper()

        fh_values: dict[str, float] = {}
        if fh_target_ids:
            st.markdown("**Family History: LTR per outcome**")
            for oid in fh_target_ids:
                default_value = (stored.get("fh_value_by_outcome_id") or {}).get(
                    oid, 0.0
                )
                fh_values[oid] = st.number_input(
                    f"{outcome_labels.get(oid, oid)} ({oid})",
                    min_value=0.0,
                    value=float(default_value),
                    key=f"sva_fh_{oid}",
                )

        dna_mode = DNA_VALUE_MODE_OVERALL
        dna_overall_value: float | None = None
        dna_values: dict[str, float] = {}
        if dna_target_ids:
            st.markdown("**DNA: average revenue per kit**")
            dna_mode_label = st.radio(
                "DNA value entry",
                ["One overall value", "Segment-specific values"],
                index=0
                if stored.get("dna_mode") != DNA_VALUE_MODE_SEGMENT_SPECIFIC
                else 1,
                key="sva_dna_mode",
            )
            dna_mode = (
                DNA_VALUE_MODE_OVERALL
                if dna_mode_label == "One overall value"
                else DNA_VALUE_MODE_SEGMENT_SPECIFIC
            )
            if dna_mode == DNA_VALUE_MODE_OVERALL:
                stored_dna = stored.get("dna_value_by_outcome_id") or {}
                default_overall = next(iter(stored_dna.values()), 0.0)
                dna_overall_value = st.number_input(
                    "Average revenue per kit (all DNA segments)",
                    min_value=0.0,
                    value=float(default_overall),
                    key="sva_dna_overall",
                )
            else:
                for oid in dna_target_ids:
                    default_value = (stored.get("dna_value_by_outcome_id") or {}).get(
                        oid, 0.0
                    )
                    dna_values[oid] = st.number_input(
                        f"{outcome_labels.get(oid, oid)} ({oid})",
                        min_value=0.0,
                        value=float(default_value),
                        key=f"sva_dna_{oid}",
                    )

        if not currency or len(currency) != 3:
            st.warning(
                "Enter a valid three-letter currency code to save value assumptions."
            )
            return

        try:
            assumptions = build_scenario_value_assumptions(
                fh_value_by_outcome_id=fh_values,
                dna_mode=dna_mode,
                currency=currency,
                dna_outcome_ids=dna_target_ids,
                dna_overall_value=dna_overall_value,
                dna_value_by_outcome_id=dna_values,
            )
        except ValueError as exc:
            st.error(f"Value assumptions incomplete: {exc}")
            return

        if st.button("Save value assumptions", key="sva_save"):
            set_state("scenario_value_assumptions", assumptions.to_dict())
            st.success("Value assumptions saved with this scenario.")


if objective == "expected_value" and _target_ids_for_value:
    _render_scenario_value_assumptions_editor(
        meta, _target_ids_for_value, value_currency
    )

# G2A.7a.10 (brief section 9, 11): one canonical OutcomeValueMapping drives
# manual evaluation, both optimiser modes, and posterior uncertainty alike -
# replacing the previous split where the objective resolved against
# catalogue weights but calculation used the legacy segment_ltv dict.
# Prefer outcome-ID-keyed catalogue weights; fall back to the strict legacy
# segment-LTV adapter only when catalogue weights don't cover every target.
value_mapping: OutcomeValueMapping | None = None
if objective == "expected_value" and value_currency and _target_ids_for_value:
    # WP2G (REQ-ECON-003 Requirement 5): an explicit, analyst-saved
    # forward value assumption for these exact target outcomes takes
    # precedence over every derived fallback below - never silently
    # overridden by a catalogue-derived or legacy-segment-LTV value once
    # the analyst has explicitly saved one.
    _stored_scenario_value_assumptions = get_state("scenario_value_assumptions")
    if _stored_scenario_value_assumptions:
        try:
            _scenario_value_assumptions = ScenarioValueAssumptions.from_dict(
                _stored_scenario_value_assumptions
            )
            _assumptions_outcome_ids = set(
                _scenario_value_assumptions.fh_value_by_outcome_id
            ) | set(_scenario_value_assumptions.dna_value_by_outcome_id)
            if (
                _assumptions_outcome_ids == _target_ids_for_value
                and _scenario_value_assumptions.currency == value_currency
            ):
                value_mapping = _scenario_value_assumptions.to_outcome_value_mapping()
        except (TypeError, ValueError):
            value_mapping = None

    # Fresh review finding: a stored value mapping (e.g. from an import) may
    # be a legitimately governed/curated mapping that isn't exactly
    # reproducible by either derivation path below (a custom mapping_id/
    # source, or values curated rather than taken straight from the fitted
    # catalogue). Preserve it when it's still compatible with the CURRENT
    # objective's target outcome set and currency - re-deriving from scratch
    # would silently discard it with no analyst choice behind it, exactly
    # the counterfactual-policy/currency-context defect above. When the
    # target set has genuinely changed (a different objective/outcome
    # selection), the stored mapping no longer describes this objective at
    # all, so re-deriving fresh below is correct, not a preservation
    # concern.
    #
    # WP2G: only reached when the explicit scenario_value_assumptions check
    # above did not already resolve value_mapping - an explicitly saved
    # forward assumption must never be silently clobbered by a stale
    # leftover "value_mapping" from a previous rerun/import.
    if value_mapping is None:
        _stored_value_mapping_dict, _value_mapping_mapping_malformed = (
            _validated_stored_mapping("value_mapping", label="value mapping")
        )
        if (
            not _value_mapping_mapping_malformed
            and _stored_value_mapping_dict
            and set(_stored_value_mapping_dict.get("value_by_outcome_id") or {})
            == _target_ids_for_value
            and all(
                currency == value_currency
                for currency in (
                    _stored_value_mapping_dict.get("currency_by_outcome_id") or {}
                ).values()
            )
        ):
            try:
                value_mapping = OutcomeValueMapping.from_dict(
                    _stored_value_mapping_dict
                )
            except (TypeError, ValueError):
                value_mapping = None
    if value_mapping is None:
        _catalogue_target_weights = {
            oid: value_weights_by_outcome_id[oid]
            for oid in _target_ids_for_value
            if oid in value_weights_by_outcome_id
        }
        if len(_catalogue_target_weights) == len(_target_ids_for_value):
            value_mapping = OutcomeValueMapping(
                value_by_outcome_id=_catalogue_target_weights,
                currency_by_outcome_id={
                    oid: value_currency for oid in _catalogue_target_weights
                },
                mapping_id="outcome-catalogue",
                source="outcome_catalogue",
            )
        elif ltv:
            _segment_by_outcome_id = {
                o.outcome_id: o.segment
                for o in (meta.outcome_catalogue_at_fit or [])
                if o.outcome_id in _target_ids_for_value
            }
            try:
                value_mapping = OutcomeValueMapping.from_legacy_segment_ltv(
                    segment_by_outcome_id=_segment_by_outcome_id,
                    segment_ltv=ltv,
                    currency=value_currency,
                    outcome_ids=tuple(sorted(_target_ids_for_value)),
                )
            except (ValueError, KeyError):
                value_mapping = None
# PR 125A: the project-level value mapping every official "incremental_
# value" scenario's saved governance_dependencies.value_mapping_fingerprint
# is verified against on import - see core.persistence's module docstring
# and audit_project_resumability(). Unlike counterfactual_policy/
# currency_context above, every field of OutcomeValueMapping is fully
# re-derived by this page from the outcome catalogue each rerun (no field
# only an import could ever supply), so there is nothing to merge/preserve
# here - only set when this rerun actually resolved one, the same "never
# overwrite with None" rule currency_context follows.
if value_mapping is not None:
    set_state("value_mapping", value_mapping.to_dict())

# Corrective review finding: market_reporting_currency/value_currency are
# genuinely re-derived from the current objective's target outcomes every
# rerun (that's this block's job), but group_reporting_currency,
# model_currency, and any governed FX rate-set identity are never derived
# by this page at all - they can only ever have come from an import.
# Constructing a fresh minimal CurrencyContext from just the two derived
# fields discarded those on every rerun with no analyst choice behind it,
# exactly the counterfactual-policy defect above. Preserve them by merging
# onto whatever was already stored, only overriding the two fields this
# page actually computes.
_stored_currency_context_dict, _currency_context_mapping_malformed = (
    _validated_stored_mapping("currency_context", label="currency context")
)
try:
    if _currency_context_mapping_malformed:
        # Fresh review finding: route a non-mapping stored value through the
        # same blocking path as a mapping that fails CurrencyContext
        # validation below - never silently treated the same as "nothing
        # stored" (which would let a corrupted array/string be quietly
        # replaced with a fresh default and continue).
        raise ValueError("stored currency context is not a valid object")
    currency_context = (
        CurrencyContext.from_dict(
            {
                **(_stored_currency_context_dict or {}),
                # Fresh review finding: market_reporting_currency and
                # value_currency are DISTINCT fields (a market can report in
                # one currency while its outcomes are value-weighted in
                # another, governed by explicit FX evidence) - only
                # value_currency is genuinely re-derived by this page every
                # rerun. Overwriting market_reporting_currency from the same
                # derived value too corrupted a legitimately different
                # stored market currency the moment this page loaded.
                # Preserve whatever was already stored for it; only a fresh
                # project (nothing stored yet) falls back to the derived
                # value.
                "market_reporting_currency": (
                    (_stored_currency_context_dict or {}).get(
                        "market_reporting_currency"
                    )
                    or value_currency
                ),
                "value_currency": value_currency,
            }
        )
        if value_currency
        else None
    )
except (TypeError, ValueError) as exc:
    # Fresh review finding: falling back to a freshly-constructed minimal
    # CurrencyContext and continuing with it - even only in memory, never
    # persisted - still let evaluation, saving, and optimisation run against
    # governance semantics the analyst never chose, and a saved scenario's
    # fingerprint would match neither the invalid stored context nor any
    # context the analyst actually approved. Block the entire planning
    # workflow below this point, the same st.stop() gate the counterfactual
    # policy check above uses, until the underlying currency/FX data (e.g.
    # Market Descriptors) is corrected - the stored context itself is left
    # completely untouched in session state.
    st.error(
        "Planning is blocked until this project's stored currency context is "
        f"corrected: it is invalid and cannot be combined with the current "
        f"objective's currency ({exc}). Fix the underlying currency/FX data "
        "(e.g. Market Descriptors) rather than continuing."
    )
    st.stop()
# PR 125A: the project-level currency context every official scenario's
# saved currency identity is verified against on import. Only set when this
# rerun actually resolved one - an objective with no target-outcome
# currency must not overwrite a previously exported context with None.
if currency_context is not None:
    set_state("currency_context", currency_context.to_dict())

# G2A.7a.7: protected objective resolution with error boundary
planning_objective = None
optimisation_objective = None
_objective_error = None
try:
    planning_objective = resolve_planning_objective(
        objective_kind=objective,
        meta=meta,
        operation="planning",
        ltv=ltv,
        value_currency=value_currency,
        counterfactual_policy_fingerprint=counterfactual_policy.fingerprint(),
        value_weights_by_outcome_id=value_weights_by_outcome_id or None,
    )
except (ValueError, PlanningGovernanceError) as e:
    _objective_error = f"Planning objective: {e}"

try:
    optimisation_objective = resolve_planning_objective(
        objective_kind=objective,
        meta=meta,
        operation="optimisation",
        ltv=ltv,
        value_currency=value_currency,
        counterfactual_policy_fingerprint=counterfactual_policy.fingerprint(),
        value_weights_by_outcome_id=value_weights_by_outcome_id or None,
    )
except (ValueError, PlanningGovernanceError) as e:
    _objective_error = (_objective_error or "") + f" Optimisation objective: {e}"

# REQ-OPT-001 Requirement 1 (Decision 16): validate the actual vocabulary
# kind the analyst selected - this is the real gate, not a display sitting
# beside the optimiser unused. maximise_profit is unconditionally blocked
# (a repository-wide audit found no governed profit/margin/COGS definition
# anywhere); maximise_roi/minimise_cpa require every channel this
# optimisation considers to be cost-bearing (Decision 7 - SEO exclusion).
# Blocked/gated kinds are never silently hidden from the selector above -
# they stay selectable, and the reason is disclosed here and used below to
# block the Run buttons.
_objective_vocab_error: str | None = None
if objective_display_kind in ("maximise_profit", "maximise_roi", "minimise_cpa"):
    _vocab_resolution = resolve_objective_kind(
        objective_display_kind,
        meta=meta,
        operation="optimisation",
        ltv=ltv,
        value_currency=value_currency,
        value_weights_by_outcome_id=value_weights_by_outcome_id or None,
        considered_channels=meta.channels,
        activities=activity_definitions or None,
    )
    if not _vocab_resolution.ready:
        _objective_vocab_error = "; ".join(_vocab_resolution.reasons)

st.caption(
    "Each objective states exactly what it maximises - Family History GSAs, Family History sign-ups "
    "and DNA kit sales are never silently combined into one generic 'volume' number. "
    "**Official planning requires each target outcome to have an approved definition "
    "(Structure → Outcome Governance).**"
)
if _objective_error:
    st.error(f"Objective configuration: {_objective_error}")
if _objective_vocab_error:
    render_status_badge("unavailable", label=_objective_labels[objective_display_kind])
    st.error(
        f"'{_objective_labels[objective_display_kind]}' is not available for this "
        f"optimisation: {_objective_vocab_error}"
    )
if not _objective_error and objective == "expected_value":
    # Display actual currency when available
    if value_currency:
        st.caption(f"Value currency: **{value_currency}**")
    if value_mapping is None:
        st.warning(
            "No outcome value mapping is available for this project's target "
            "outcomes - 'Maximise expected value' needs a value weight for "
            "every target outcome (set on the Structure page) and a single "
            "governed currency across them before running."
        )

st.markdown("---")
st.markdown("### Decision outputs")
st.caption(
    "Choose the output view that matches the decision: evaluate the edited plan, "
    "run a constrained proposal, or inspect the unconstrained benchmark."
)
tab_manual, tab_constrained, tab_unconstrained = st.tabs(
    [
        "Edited plan and calculated result",
        "Constrained proposal",
        "Unconstrained benchmark",
    ]
)


def _render_steady_state_manual_tab():
    st.caption("Evaluation method: **Steady-state monthly approximation**.")
    st.markdown("Predicted outcomes for the spend plan as edited above.")
    # PR 82C: routed through ScenarioService.evaluate_manual() with a typed
    # ManualScenarioInput - the page no longer calls evaluate_manual_scenario()
    # directly.
    manual_service_result = ScenarioService().evaluate_manual(
        ManualScenarioInput(
            market=market,
            spend_plan=spend_plan,
            meta=meta,
            params=params,
            reference_context_by_month=reference_context_by_month,
            ltv=ltv,
            planning_objective=planning_objective,
            activity_definitions=activity_definitions or None,
            scenario_plan=scenario_plan,
            counterfactual_policy=counterfactual_policy,
            cost_mapping_registry=governed_cost_registry,
            cost_context_id="default",
            cost_as_of_by_month=cost_as_of_by_month,
            artefact_kind="manual_scenario",
            value_mapping=value_mapping,
            currency_context=currency_context,
            **identity_kwargs,
            **scenario_governance_kwargs,
        )
    )
    if manual_service_result.errors:
        for _err in manual_service_result.errors:
            st.error(f"Cannot evaluate this scenario: {_err}")
        st.stop()
    manual_result = manual_service_result.evaluation
    predicted = manual_result.predicted
    st.markdown("#### Calculated output (read-only)")
    st.caption(
        "Everything below is computed from the spend plan grid above - edit the plan, not "
        "these tables, to change these numbers."
    )
    _render_scenario_output(
        predicted,
        outcome_labels,
        technical_title="Technical details · calculated output",
    )
    totals_source = aggregate_outcome_groups(
        predicted,
        outcome_groups_at_fit,
        outcome_group_treatments_at_fit,
        by=["month"],
        value_columns=("predicted_outcome", "value"),
    )
    totals = (
        totals_source.groupby("outcome_id")[["predicted_outcome", "value"]]
        .sum()
        .reset_index()
    )
    st.markdown("**Totals by outcome**")
    if outcome_groups_at_fit:
        st.caption(
            "Outcome-group totals are shown once; their member outcomes are not counted again."
        )
    _render_scenario_output(
        totals,
        outcome_labels,
        technical_title="Technical details · outcome totals",
    )
    if (
        "total_value_is_complete" in predicted.columns
        and not predicted["total_value_is_complete"].all()
    ):
        st.caption(
            "Total predicted value excludes outcomes with no value weight configured (never "
            "silently treated as $1) - set a value weight for every outcome on Model Structure "
            "for a complete total."
        )
    by_month_cols = ["fh_gsa", "fh_net_billthrough", "dna_kits"] + (
        ["fh_signups"] if "fh_signups" in predicted.columns else []
    )
    by_month_totals = predicted.groupby("month")[by_month_cols].first()
    _objective_totals = {
        "fh_gsa": ("Total predicted FH GSAs", float(by_month_totals["fh_gsa"].sum())),
        "fh_net_billthrough": (
            "Total predicted FH net bill-through",
            float(by_month_totals["fh_net_billthrough"].sum()),
        ),
        "dna_kits": (
            "Total predicted DNA kits",
            float(by_month_totals["dna_kits"].sum()),
        ),
        "expected_value": ("Total predicted value", float(predicted["value"].sum())),
    }
    if "fh_signups" in by_month_cols:
        _objective_totals["fh_signups"] = (
            "Total predicted FH sign-ups",
            float(by_month_totals["fh_signups"].sum()),
        )
    total_label, total_value = _objective_totals[objective]
    st.metric(total_label, f"{total_value:,.0f}")
    if objective == "expected_value" and value_mapping is not None:
        with st.expander("Value assumptions used (forward, not historical)"):
            st.caption(
                "These are explicit, analyst-supplied future value "
                "assumptions for this scenario - never derived or "
                "extrapolated from historical valuation data."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Outcome": outcome_labels.get(oid, oid),
                            "outcome_id": oid,
                            "Value per unit": value_mapping.value_by_outcome_id[oid],
                            "Currency": value_mapping.currency_by_outcome_id[oid],
                        }
                        for oid in sorted(value_mapping.value_by_outcome_id)
                    ]
                ),
                width="stretch",
            )

    st.markdown("**Economics by month**")
    st.caption(
        "Calculated by the model evaluator. Whole-plan measures are unavailable when "
        "response-only activity makes that scope incompatible; paid-media measures remain "
        "available when supported."
    )
    econ_table = monthly_economics_table(predicted)
    _render_economics_table(
        econ_table,
        technical_title="Technical details · economics fields",
    )
    if not whole_plan_scope_compatible(predicted):
        st.caption(
            "Whole-plan CPA/ROI is unavailable for one or more months above - see paid-media-only "
            "CPA/ROI instead."
        )

    scenario_name = st.text_input(
        "Scenario name *", value=f"manual-{market}-{months[0]}", key="manual_name"
    )
    if st.button("Save this scenario"):
        scenarios = get_state("scenarios") or []
        # G2A.7a.5: use the exact governance dependencies from evaluate_manual_scenario
        gov_deps = manual_result.governance_dependencies
        manual_scenario = scenario_to_dict(
            scenario_name,
            market,
            spend_plan,
            objective,
            [],
            notes="manual",
            planning_objective=planning_objective,
            activity_definitions_fingerprint=(
                gov_deps.activity_definitions_fingerprint
                if gov_deps is not None
                else predicted["activity_definitions_fingerprint"].iloc[0]
            ),
            scenario_plan=scenario_plan,
            counterfactual_policy=counterfactual_policy,
            economics_coverage=predicted["economics_coverage"].iloc[0],
            governance_mode=governance_mode,
            artefact_kind=manual_result.artefact_kind,
            # Persist the exact governance dependencies from the service
            governance_dependencies=gov_deps,
        )
        manual_scenario["predicted"] = predicted
        # REQ-OPT-001 (Decision 16): disclose exactly which closed
        # objective-kind vocabulary entry the analyst selected - never
        # buried behind the aliased legacy `objective` string alone (e.g.
        # "minimise_cpa" and "maximise_revenue" both alias to the legacy
        # "expected_value" objective, but are materially different analyst
        # intents worth persisting distinctly).
        manual_scenario["objective_kind_vocabulary_selection"] = objective_display_kind
        scenarios.append(manual_scenario)
        set_state("scenarios", scenarios)
        st.success(f"Saved scenario '{scenario_name}'.")

    st.markdown("---")
    if trace is None:
        st.caption(
            "Posterior uncertainty needs a fitted trace, not just point-estimate posterior params - unavailable here."
        )
    else:
        show_scenario_uncertainty = st.checkbox(
            "Show posterior uncertainty for this plan (re-runs the scenario once per sampled draw - slower)",
            value=False,
            key="manual_scenario_uncertainty",
        )
        if show_scenario_uncertainty:
            n_draws = st.slider(
                "Posterior draws to sample",
                20,
                200,
                50,
                step=10,
                key="manual_scenario_n_draws",
            )
            baseline_plan = {
                m: {c: float(v) for c, v in zip(meta.channels, default_monthly)}
                for m in months
            }
            baseline_scenario_plan = (
                classify_activity_plan(
                    baseline_plan,
                    market=market,
                    activity_definitions=activity_definitions,
                )
                if activity_definitions
                else None
            )
            with st.spinner(
                f"Computing scenario uncertainty from {n_draws} posterior draws..."
            ):
                try:
                    uncertainty_result = evaluate_scenario_with_uncertainty(
                        spend_plan,
                        market,
                        meta,
                        trace,
                        reference_context_by_month,
                        ltv,
                        n_draws=n_draws,
                        baseline_spend_plan=baseline_plan,
                        scenario_plan=scenario_plan,
                        baseline_scenario_plan=baseline_scenario_plan,
                        activity_definitions=activity_definitions or None,
                        counterfactual_policy=counterfactual_policy,
                        planning_objective=planning_objective,
                        cost_mapping_registry=governed_cost_registry,
                        cost_context_id="default",
                        cost_as_of_by_month=cost_as_of_by_month,
                        value_mapping=value_mapping,
                        outcome_groups=outcome_groups_at_fit,
                        outcome_group_treatments=outcome_group_treatments_at_fit,
                        **identity_kwargs,
                        **scenario_governance_kwargs,
                    )
                except (
                    ApprovalMismatchError,
                    ValueError,
                    PlanningGovernanceError,
                ) as e:
                    st.error(f"Cannot evaluate this scenario: {e}")
                    uncertainty_result = None
            if uncertainty_result is not None:
                st.markdown(
                    "**Predicted outcomes with uncertainty (mean / median / 90% credible interval)**"
                )
                summary_df = uncertainty_result["summary"]
                _render_scenario_output(
                    summary_df,
                    outcome_labels,
                    technical_title="Technical details · uncertainty summary",
                )
                prob = uncertainty_result["prob_outperforms_baseline"]
                if prob is not None:
                    st.metric(
                        "Probability this plan outperforms the recent-average baseline",
                        f"{prob:.0%}",
                        help=(
                            "Fraction of paired posterior draws where this plan's total predicted value "
                            "exceeds the recent-average-spend baseline's - the same draw index is used "
                            "for both plans in each comparison, so the result isn't inflated by "
                            "independently-resampled noise."
                        ),
                    )
                st.caption(
                    f"Based on {uncertainty_result['n_draws']} sampled posterior draws - a subsample of "
                    "the full posterior for speed, not the full posterior itself."
                )


def _render_sequential_manual_tab():
    st.caption("Evaluation method: **Sequential weekly**.")
    st.markdown(
        "Predicted outcomes for the spend plan as edited above, simulated week by "
        "week from this market's real historical carry-in."
    )
    st.caption(
        "**Sequential weekly starts immediately after this market's historical data "
        "ends**, continuing the exact same weekly cadence with no gap - not at the "
        f"{months[0]} you selected in 'Plan start month' above (that control still "
        "applies to steady-state monthly). Each planned month's spend values are "
        "used in the same order, starting from that continuation point."
    )

    # WP0 of `Media-Mix-Lab: Coding LLM Next Steps After PR #267`: three
    # assumptions this method makes automatically must instead be explicit,
    # analyst-acknowledged choices before any result is calculated or
    # shown - never a silent page default. Each gate below is scoped to
    # `plan_key` (market/months/start_month), so a changed plan requires
    # re-acknowledgment rather than carrying forward a stale consent.
    all_acknowledged = True

    preview_start_week = _sequential_plan_start_week(frame, market, spec)
    sequential_start_month = preview_start_week.strftime("%Y-%m")
    if sequential_start_month != months[0]:
        shifted_months = [
            (preview_start_week.replace(day=1) + pd.DateOffset(months=i)).strftime(
                "%Y-%m"
            )
            for i in range(n_months)
        ]
        st.warning(
            f"**'Plan start month' above is set to {months[0]}, but sequential weekly "
            f"always starts {preview_start_week.date()}** - immediately after this "
            "market's historical data ends, with no gap or overlap. Each entered "
            "monthly value keeps its position (1st entered month, 2nd, ...) but is "
            "reassigned to a different real calendar month below, which can change "
            "its seasonality and cost context:"
        )
        st.dataframe(
            pd.DataFrame(
                {"Entered as": months, "Sequential weekly will use": shifted_months}
            ),
            width="stretch",
            hide_index=True,
        )
        start_month_ack = st.checkbox(
            "I understand my entered monthly values will be reassigned to these "
            "different calendar months, and want to proceed.",
            key=f"{plan_key}_seq_start_month_ack",
        )
        all_acknowledged = all_acknowledged and start_month_ack

    control_names = tuple(getattr(meta, "control_names", ()) or ())
    outcome_control_names = getattr(meta, "outcome_control_names", None) or {}
    has_exogenous_controls = bool(control_names) or bool(
        any(names for names in outcome_control_names.values())
    )
    if has_exogenous_controls:
        st.warning(
            "**This model has fitted exogenous control(s) with no future-value input "
            "available in this UI yet.** Sequential weekly can only proceed by "
            "explicitly holding each one at its last observed value - a labelled, "
            "exploratory assumption, never an official forecast."
        )
        hold_last_ack = st.checkbox(
            "I explicitly choose to hold each exogenous control at its last "
            "observed value (exploratory) for this evaluation.",
            key=f"{plan_key}_seq_hold_last_ack",
        )
        all_acknowledged = all_acknowledged and hold_last_ack

    # REQ-PLANACT-001 (Decision 14): structured promotion-period input,
    # materialised into build_future_context's promo_future above via the
    # real, unmodified materialize_promo_future - the analyst declares
    # promotions once (start/end week, intensity), not by hand-constructing
    # a per-week value. When none are declared, the previous unconditional
    # "confirm no promotion" gate is preserved exactly (same checkbox
    # label/key, so no analyst-facing regression for the common case).
    if "promotion_periods" not in st.session_state:
        st.session_state["promotion_periods"] = []

    st.markdown("#### Promotion periods (sequential weekly only)")
    with st.expander("+ Add a promotion period"):
        promo_outcome = st.selectbox(
            "Outcome", meta.outcome_ids, key=f"{plan_key}_promo_outcome"
        )
        promo_start = st.date_input(
            "Start week",
            value=preview_start_week.date(),
            key=f"{plan_key}_promo_start",
        )
        promo_end = st.date_input(
            "End week",
            value=preview_start_week.date(),
            key=f"{plan_key}_promo_end",
        )
        promo_intensity = st.number_input(
            "Intensity (same unit/scale as the historical promo column this "
            "outcome was fit with)",
            value=0.0,
            key=f"{plan_key}_promo_intensity",
        )
        promo_label = st.text_input(
            "Label (optional)", value="", key=f"{plan_key}_promo_label"
        )
        if st.button("Add promotion period", key=f"{plan_key}_add_promo"):
            try:
                period = PromotionPeriod(
                    promotion_id=f"promo-{len(st.session_state['promotion_periods'])}-{promo_outcome}",
                    outcome_id=promo_outcome,
                    start_week=promo_start.strftime("%Y-%m-%d"),
                    end_week=promo_end.strftime("%Y-%m-%d"),
                    intensity=promo_intensity,
                    label=promo_label,
                )
            except ValueError as exc:
                st.error(f"Cannot add promotion period: {exc}")
            else:
                st.session_state["promotion_periods"].append(period)
                st.rerun()

    for i, promo in enumerate(st.session_state["promotion_periods"]):
        p1, p2 = st.columns([5, 1])
        p1.markdown(
            f"**{i + 1}.** {promo.label or promo.promotion_id} - outcome="
            f"{promo.outcome_id}, {promo.start_week} to {promo.end_week}, "
            f"intensity={promo.intensity}"
        )
        if p2.button("Remove", key=f"{plan_key}_rm_promo_{i}"):
            st.session_state["promotion_periods"].pop(i)
            st.rerun()

    if st.session_state["promotion_periods"]:
        st.caption(
            f"{len(st.session_state['promotion_periods'])} promotion period(s) "
            "declared above will be used for this plan window - an explicit "
            "input, not an unstated default."
        )
    else:
        st.warning(
            "**No promotion schedule can be entered for sequential weekly in this UI "
            "yet.** Choose explicitly rather than relying on an unstated default:"
        )
        no_promotion_ack = st.checkbox(
            "I explicitly confirm no promotion is planned for this plan window.",
            key=f"{plan_key}_seq_no_promotion_ack",
        )
        all_acknowledged = all_acknowledged and no_promotion_ack

    if not all_acknowledged:
        st.info(
            "Confirm the assumption(s) above to calculate this sequential scenario."
        )
        return

    if trace is None:
        st.caption(
            "Posterior uncertainty needs a fitted trace, not just point-estimate "
            "posterior params - unavailable here."
        )
        seq_n_posterior_draws = 0
    else:
        show_sequential_uncertainty = st.checkbox(
            "Show posterior uncertainty for this sequential plan (re-runs the "
            "scenario once per sampled draw - slower)",
            value=False,
            key=f"{plan_key}_seq_uncertainty",
        )
        seq_n_posterior_draws = (
            st.slider(
                "Posterior draws to sample",
                20,
                200,
                50,
                step=10,
                key=f"{plan_key}_seq_n_draws",
            )
            if show_sequential_uncertainty
            else 0
        )

    spinner_text = (
        f"Computing sequential scenario uncertainty from {seq_n_posterior_draws} "
        "posterior draws..."
        if seq_n_posterior_draws
        else "Computing sequential scenario..."
    )
    try:
        with st.spinner(spinner_text):
            (
                service_result,
                plan_start_week,
                weeks,
                future_context,
                terminal_future_context,
            ) = _evaluate_sequential_manual_plan(
                market=market,
                meta=meta,
                params=params,
                frame=frame,
                spec=spec,
                n_months=n_months,
                spend_plan=spend_plan,
                activity_definitions=activity_definitions,
                counterfactual_policy=counterfactual_policy,
                governed_cost_registry=governed_cost_registry,
                planning_objective=planning_objective,
                identity_kwargs=identity_kwargs,
                scenario_governance_kwargs=scenario_governance_kwargs,
                value_mapping=value_mapping,
                currency_context=currency_context,
                trace=trace,
                n_posterior_draws=seq_n_posterior_draws,
                promotion_periods=st.session_state["promotion_periods"],
            )
    except ValueError as exc:
        st.error(f"Cannot build the sequential weekly plan: {exc}")
        return

    if service_result.errors:
        for _err in service_result.errors:
            st.error(f"Cannot evaluate this scenario: {_err}")
        return
    for _warn in service_result.warnings:
        st.warning(_warn)

    result = service_result.sequential_evaluation
    st.caption(
        f"Plan window: {weeks[0]} through {weeks[-1]} ({len(weeks)} weeks), "
        f"starting {plan_start_week.date()}."
    )
    if not future_context.is_decision_ready:
        st.warning(
            "**Not decision-ready.** This market has exogenous control(s) with no "
            "future-value input in this UI yet - held at their last observed value "
            "(an explicit, exploratory assumption, not an official forecast). "
            "Use steady-state monthly for an official recommendation until future "
            "control input is added here."
        )

    st.markdown("#### Weekly incremental outcome (candidate − reference)")
    weekly_df = pd.DataFrame(
        result.weekly_incremental,
        index=result.weekly_period_labels,
        columns=result.outcome_ids,
    )
    st.dataframe(
        weekly_df, width="stretch", column_config=dataframe_column_config(weekly_df)
    )

    st.markdown(
        "#### Monthly incremental outcome (summed from weekly - never recalculated)"
    )
    monthly_df = pd.DataFrame(
        result.monthly_incremental,
        index=result.monthly_period_labels,
        columns=result.outcome_ids,
    )
    st.dataframe(
        monthly_df, width="stretch", column_config=dataframe_column_config(monthly_df)
    )

    st.markdown("#### Response horizons")
    horizon_cols = st.columns(2)
    for col, (label, values) in zip(
        horizon_cols,
        (
            ("Short-horizon incremental (weeks 0-4)", result.short_horizon_incremental),
            ("Long-horizon incremental (weeks 5-52)", result.long_horizon_incremental),
        ),
    ):
        with col:
            for outcome_id, value in zip(result.outcome_ids, values):
                st.metric(f"{readable_label(outcome_id)} · {label}", f"{value:,.1f}")

    st.markdown("#### Terminal carryover (informational)")
    st.caption(
        "Residual value carrying forward after the plan window ends, if future "
        "media spend stopped at zero - evaluated under the SAME real future "
        "non-decision context (seasonality/controls) as the plan window above, "
        "reusing the assumptions already acknowledged. Structurally separate "
        "evidence: never added to the weekly/monthly/horizon totals above."
    )
    if result.terminal is not None:
        terminal_df = pd.DataFrame(
            result.terminal.incremental,
            index=result.terminal.period_labels,
            columns=result.terminal.outcome_ids,
        )
        st.dataframe(
            terminal_df,
            width="stretch",
            column_config=dataframe_column_config(terminal_df),
        )
    else:
        st.caption("Terminal carryover could not be computed for this plan.")

    st.markdown("#### Posterior uncertainty")
    if result.posterior_weekly_incremental is not None:
        window_totals = result.posterior_weekly_incremental.sum(axis=1)
        summary_df = pd.DataFrame(
            {
                "mean": window_totals.mean(axis=0),
                "median": np.median(window_totals, axis=0),
                "p5": np.percentile(window_totals, 5, axis=0),
                "p95": np.percentile(window_totals, 95, axis=0),
            },
            index=result.outcome_ids,
        )
        st.markdown(
            "**Plan-window total incremental outcome, per sampled posterior draw "
            "(mean / median / 90% credible interval)**"
        )
        st.dataframe(
            summary_df,
            width="stretch",
            column_config=dataframe_column_config(summary_df),
        )
        st.caption(
            f"Based on {result.posterior_weekly_incremental.shape[0]} sampled "
            "posterior draws, summed per draw across the plan window (weekly "
            "draws are not independently re-sampled per week - the same draw "
            "index is used throughout, preserving draw-to-draw correlation)."
        )
    else:
        st.caption(
            "Enable 'Show posterior uncertainty for this sequential plan' above "
            "to compute a credible interval for this plan's total incremental "
            "outcome."
        )

    render_technical_details(
        title="Technical details · sequential evaluation provenance",
        details={
            "Calculation method": result.calculation_method,
            "Phasing method": result.phasing_method_id,
            "Weekly plan fingerprint (candidate)": result.weekly_plan_fingerprint,
            "Weekly plan fingerprint (reference)": result.reference_weekly_plan_fingerprint,
            "Future-context fingerprint": result.future_context_fingerprint,
            "Terminal future-context fingerprint": terminal_future_context.fingerprint(),
            "Starting-state fingerprint": result.starting_state_fingerprint,
            "Evaluation-context fingerprint": result.evaluation_context_fingerprint,
            "Decision-ready": str(future_context.is_decision_ready),
        },
    )
    seq_scenario_name = st.text_input(
        "Scenario name *",
        value=f"sequential-{market}-{plan_start_week.date()}",
        key=f"{plan_key}_seq_scenario_name",
    )
    if st.button("Save this scenario", key=f"{plan_key}_save_sequential"):
        scenarios = get_state("scenarios") or []
        scenarios.append(
            sequential_scenario_to_dict(
                seq_scenario_name, result, notes="sequential_weekly manual"
            )
        )
        set_state("scenarios", scenarios)
        st.success(f"Saved scenario '{seq_scenario_name}'.")


with tab_manual:
    if evaluation_method == "sequential_weekly":
        _render_sequential_manual_tab()
    else:
        _render_steady_state_manual_tab()

with tab_constrained:
    st.caption(
        "Evaluation method: **steady-state monthly** - this optimiser mode does "
        "not support sequential weekly."
    )
    st.markdown("#### Constraints (distinct from the assumptions above)")
    st.markdown(
        "Add the constraints Ancestry actually plans against: locked cells (e.g. committed TV "
        "bookings), fixed channel/month totals, bounded movement from the current plan, and "
        "minimum-spend floors (e.g. DNA promotional windows). Constraints are hard bounds the "
        "optimiser must respect; they are separate from the planning assumptions (comparison "
        "baseline, planning use, and objective) set above, which shape how a plan is evaluated "
        "rather than what values it may take."
    )
    if "scenario_constraints" not in st.session_state:
        st.session_state["scenario_constraints"] = []

    with st.expander("+ Add a constraint"):
        kind = st.selectbox(
            "Constraint type",
            [
                "locked_cell",
                "channel_total",
                "month_total",
                "bounded_movement",
                "min_spend_floor",
            ],
            format_func=lambda k: CONSTRAINT_KIND_LABELS.get(k, k),
        )
        st.caption(
            {
                "locked_cell": FIELD_HELP["locked_cells"],
                "channel_total": "Fix the total spend for one channel across the whole plan.",
                "month_total": "Fix the total spend across all channels for one month.",
                "bounded_movement": FIELD_HELP["maximum_movement"],
                "min_spend_floor": FIELD_HELP["minimum_spend"],
            }.get(kind, "")
        )
        ch = st.selectbox(
            "Channel (if applicable)",
            ["(any)"] + meta.channels,
            key="c_channel",
            format_func=lambda c: (
                c
                if c == "(any)"
                else model_input_display_label(
                    c, activity_definitions=activity_definitions, market=market
                )
            ),
        )
        mo = st.selectbox("Month (if applicable)", ["(any)"] + months, key="c_month")
        val = st.number_input(
            "Value / target (if applicable)", min_value=0.0, value=0.0, key="c_value"
        )
        pct = st.slider(
            "Max % movement (if applicable)", 0.0, 1.0, 0.2, 0.05, key="c_pct"
        )
        if st.button("Add constraint"):
            constraint = SpendConstraint(
                kind=kind,
                channel=None if ch == "(any)" else ch,
                month=None if mo == "(any)" else mo,
                months=None
                if mo == "(any)"
                else [mo]
                if kind == "min_spend_floor"
                else None,
                value=val if val > 0 else None,
                max_pct_move=pct if kind == "bounded_movement" else None,
                label=f"{kind} {ch} {mo}",
            )
            st.session_state["scenario_constraints"].append(constraint)
            st.rerun()

    for i, c in enumerate(st.session_state["scenario_constraints"]):
        c1, c2 = st.columns([5, 1])
        c1.markdown(
            f"**{i + 1}.** {CONSTRAINT_KIND_LABELS.get(c.kind, c.kind)} - "
            "channel="
            f"{model_input_display_label(c.channel, activity_definitions=activity_definitions, market=market) if c.channel else 'any'}"
            f", month={c.month or 'any'}, value={c.value}, max % movement={c.max_pct_move}"
        )
        if c2.button("Remove", key=f"rm_constraint_{i}"):
            st.session_state["scenario_constraints"].pop(i)
            st.rerun()

    st.markdown("#### Extended constraints (Decision 16 governed vocabulary)")
    st.caption(
        "The extended kinds Decision 16 adds beyond the constraints above - maximum spend, "
        "a spend range, an absolute change from the reference plan, zero spend/no available "
        "demand, and a non-monetary required-minimum-activity floor. These reach the same "
        "optimiser bounds the constraints above do (`core.optimization_constraint_vocabulary`), "
        "never a separate/duplicate rule set."
    )
    if "governed_scenario_constraints" not in st.session_state:
        st.session_state["governed_scenario_constraints"] = []

    with st.expander("+ Add an extended constraint"):
        g_kind = st.selectbox(
            "Constraint type",
            [
                "maximum_spend",
                "spend_range",
                "absolute_change_from_reference",
                "zero_spend",
                "unavailable",
                "required_minimum_activity",
            ],
            format_func=lambda k: CONSTRAINT_KIND_LABELS.get(k, k),
            key="gc_kind",
        )
        st.caption(
            {
                "maximum_spend": "An upper bound on spend, distinct from a locked/fixed value.",
                "spend_range": "Both a minimum and a maximum bound in one constraint.",
                "absolute_change_from_reference": "A +/- absolute-currency band around the reference plan's spend, distinct from a percentage band.",
                "zero_spend": "An analyst's explicit choice to spend nothing - distinct from 'unavailable'.",
                "unavailable": "No available demand/activity this period - a fact, distinct from an analyst's zero-spend choice.",
                "required_minimum_activity": "A non-monetary activity floor (e.g. units, impressions) - never treated as a spend bound unless a governed unit-to-spend rate is supplied below.",
            }.get(g_kind, "")
        )
        g_ch = st.selectbox(
            "Channel",
            meta.channels,
            key="gc_channel",
            format_func=lambda c: model_input_display_label(
                c, activity_definitions=activity_definitions, market=market
            ),
        )
        g_mo = st.selectbox("Month", months, key="gc_month")
        g_value = None
        g_min_value = None
        g_max_value = None
        g_absolute_delta = None
        g_unit_to_spend_rate = None
        if g_kind == "maximum_spend":
            g_value = st.number_input(
                "Maximum spend", min_value=0.0, value=0.0, key="gc_value"
            )
        elif g_kind == "spend_range":
            g_min_value = st.number_input(
                "Minimum spend", min_value=0.0, value=0.0, key="gc_min_value"
            )
            g_max_value = st.number_input(
                "Maximum spend", min_value=0.0, value=0.0, key="gc_max_value"
            )
        elif g_kind == "absolute_change_from_reference":
            g_absolute_delta = st.number_input(
                "Absolute allowed change (+/-)",
                min_value=0.0,
                value=0.0,
                key="gc_abs_delta",
            )
        elif g_kind == "required_minimum_activity":
            g_value = st.number_input(
                "Required minimum activity (units)",
                min_value=0.0,
                value=0.0,
                key="gc_activity_value",
            )
            g_unit_to_spend_rate = st.number_input(
                "Unit-to-spend rate (0 = advisory-only, never invented)",
                min_value=0.0,
                value=0.0,
                key="gc_unit_rate",
                help="A governed currency-per-unit rate, if one exists - left at 0, this "
                "floor is disclosed but never silently applied as a spend bound.",
            )
        if st.button("Add extended constraint"):
            try:
                governed_constraint = GovernedSpendConstraint(
                    kind=g_kind,
                    channel=g_ch,
                    month=g_mo,
                    value=g_value if g_value else None,
                    min_value=g_min_value if g_kind == "spend_range" else None,
                    max_value=g_max_value if g_kind == "spend_range" else None,
                    absolute_delta=g_absolute_delta if g_absolute_delta else None,
                    unit_to_spend_rate=(
                        g_unit_to_spend_rate if g_unit_to_spend_rate else None
                    ),
                    label=f"{g_kind} {g_ch} {g_mo}",
                )
            except ValueError as exc:
                st.error(f"Cannot add constraint: {exc}")
            else:
                st.session_state["governed_scenario_constraints"].append(
                    governed_constraint
                )
                st.rerun()

    for i, gc in enumerate(st.session_state["governed_scenario_constraints"]):
        gc1, gc2 = st.columns([5, 1])
        gc1.markdown(
            f"**{i + 1}.** {CONSTRAINT_KIND_LABELS.get(gc.kind, gc.kind)} - "
            f"channel={model_input_display_label(gc.channel, activity_definitions=activity_definitions, market=market) if gc.channel else 'any'}"
            f", month={gc.month or 'any'}, value={gc.value}, "
            f"range=[{gc.min_value}, {gc.max_value}], absolute delta={gc.absolute_delta}"
        )
        if gc2.button("Remove", key=f"rm_governed_constraint_{i}"):
            st.session_state["governed_scenario_constraints"].pop(i)
            st.rerun()

    if st.button("Run constrained optimisation", type="primary"):
        if _objective_vocab_error:
            st.error(
                f"Cannot run optimisation: '{_objective_labels[objective_display_kind]}' "
                f"is not available: {_objective_vocab_error}"
            )
            result = None
        elif objective == "expected_value" and value_mapping is None:
            st.error(
                "Cannot run optimisation: 'Maximise expected value' needs an outcome value mapping - a value weight for every target outcome and a single governed currency across them (set on the Structure page)."
            )
            result = None
        elif (
            st.session_state["scenario_constraints"]
            and st.session_state["governed_scenario_constraints"]
        ):
            # REQ-OPT-001 Requirement 2 (Decision 16): the two constraint
            # vocabularies are never combined in one optimisation run
            # (core.optimization_constraint_vocabulary's own approved
            # design - governed_constraints replaces, never supplements,
            # the legacy constraints for bounds-building). Block with a
            # clear reason rather than silently dropping one list.
            st.error(
                "Cannot run optimisation: both the constraints above and the extended "
                "(Decision 16) constraints below are populated. Remove all constraints from "
                "one list before running - the two vocabularies are never combined in a "
                "single optimisation run."
            )
            result = None
        else:
            with st.spinner("Optimising..."):
                # PR 82C: routed through ScenarioService.optimise() with a
                # typed OptimisationInput - the page no longer calls
                # optimize_scenario() directly.
                opt_service_result = ScenarioService().optimise(
                    OptimisationInput(
                        current_spend_plan=spend_plan,
                        months=months,
                        channels=meta.channels,
                        market=market,
                        meta=meta,
                        params=params,
                        reference_context_by_month=reference_context_by_month,
                        ltv=ltv,
                        objective=objective if planning_objective is None else None,
                        planning_objective=optimisation_objective,
                        constraints=st.session_state["scenario_constraints"],
                        governed_constraints=(
                            st.session_state["governed_scenario_constraints"] or None
                        ),
                        artefact_kind="constrained_optimisation",
                        conserve_total_budget=True,
                        activity_definitions=activity_definitions or None,
                        counterfactual_policy=counterfactual_policy,
                        cost_mapping_registry=governed_cost_registry,
                        cost_context_id="default",
                        cost_as_of_by_month=cost_as_of_by_month,
                        posterior_trace=trace,
                        posterior_evaluation_draws=50,
                        value_mapping=value_mapping,
                        currency_context=currency_context,
                        **identity_kwargs,
                        **scenario_governance_kwargs,
                    )
                )
                if opt_service_result.errors:
                    for _err in opt_service_result.errors:
                        st.error(f"Cannot run optimisation: {_err}")
                    result = None
                else:
                    result = opt_service_result.optimisation_result
            if result is not None:
                if not result["success"]:
                    st.warning(f"Optimiser did not fully converge: {result['message']}")
                st.session_state["constrained_result"] = result

    # The governance-mode control or the project's counterfactual policy may
    # have changed since this result was computed (e.g. switched back to
    # "official" after an exploratory run, or the demand-capture rule was
    # changed) - a cached result that no longer matches either must never be
    # shown or saved under a mismatched label.
    result = _invalidate_stale_cached_result(
        "constrained_result",
        st.session_state.get("constrained_result"),
        current_governance_mode=governance_mode,
        current_counterfactual_fingerprint=counterfactual_policy.fingerprint(),
    )
    if result:
        # Consistent status-badge vocabulary (Phase 7 QA, docs/decision_log.md):
        # "exploratory" is an exact STATUS_BADGES key already used elsewhere
        # for this same concept - render through the shared badge instead of
        # a page-local "⚠️ Exploratory" string. "official" isn't a lifecycle
        # status STATUS_BADGES covers (it's this scenario's governance mode,
        # not a state to flag) and stays plain text, same as before.
        if result["governance_mode"] == "exploratory":
            st.caption("**Planning use** (persisted with this result)")
            render_status_badge("exploratory")
        else:
            st.caption(
                "**Planning use: Official planning** (persisted with this result)"
            )
        c1, c2 = st.columns(2)
        c1.metric(
            f"Current total ({_objective_labels[objective_display_kind]})",
            f"{result['current_objective_value']:,.0f}",
        )
        c2.metric(
            "Optimised total",
            f"{result['objective_value']:,.0f}",
            delta=f"{result['objective_value'] - result['current_objective_value']:,.0f}",
        )

        st.markdown("**Economics by month: current vs optimised**")
        st.caption(
            "Calculated by the model evaluator; scope-limited measures remain visibly unavailable "
            "where the comparison is not supported."
        )
        current_econ = monthly_economics_table(result["current_predicted"])
        current_econ.insert(0, "plan", "current")
        optimised_econ = monthly_economics_table(result["predicted"])
        optimised_econ.insert(0, "plan", "optimised")
        combined_econ = pd.concat([current_econ, optimised_econ], ignore_index=True)
        _render_economics_table(
            combined_econ,
            technical_title="Technical details · comparison economics fields",
        )
        if not (
            whole_plan_scope_compatible(result["current_predicted"])
            and whole_plan_scope_compatible(result["predicted"])
        ):
            st.caption(
                "Whole-plan CPA/ROI is unavailable for one or more months above - see "
                "paid-media-only CPA/ROI instead."
            )

        st.markdown("**Proposed (optimised) spend plan** - not yet saved")
        plan_result_df = pd.DataFrame(result["spend_plan"]).T
        st.dataframe(
            plan_result_df,
            width="stretch",
            column_config=dataframe_column_config(plan_result_df),
        )
        _render_scenario_output(
            result["predicted"],
            outcome_labels,
            technical_title="Technical details · optimised evaluator output",
        )

        # REQ-OPT-001 Requirement 4 (Decision 16): disclose which extended
        # governed constraints actually bound at this solution - never
        # buried in raw session state.
        _gc_disclosures = result.get("governed_constraint_disclosures") or []
        if _gc_disclosures:
            st.markdown("**Extended constraints: disposition and binding status**")
            for _d in _gc_disclosures:
                _bound_note = (
                    "**binding at this solution**"
                    if _d.get("binding")
                    else "not binding at this solution"
                )
                st.caption(
                    f"{CONSTRAINT_KIND_LABELS.get(_d['kind'], _d['kind'])} "
                    f"({_d.get('channel') or 'any'}, {', '.join(_d.get('months') or []) or 'any'}) - "
                    f"{_d['disposition']}, {_bound_note}. {_d['detail']}"
                )

        name = st.text_input(
            "Scenario name *",
            value=f"constrained-{market}-{months[0]}",
            key="constrained_name",
        )
        if st.button("Save this scenario", key="save_constrained"):
            scenarios = get_state("scenarios") or []
            # G2A.7a.4: build structured governance dependencies from result
            gov_deps_dict = governance_deps_from_optimizer_result(result)
            gov_deps = ScenarioGovernanceDependencies.from_dict(gov_deps_dict)
            s = scenario_to_dict(
                name,
                market,
                result["spend_plan"],
                objective,
                st.session_state["scenario_constraints"],
                notes="constrained",
                planning_objective=result["planning_objective"],
                activity_definitions_fingerprint=result[
                    "activity_definitions_fingerprint"
                ],
                scenario_plan=ScenarioPlan.from_dict(result["scenario_plan"]),
                counterfactual_policy=result["counterfactual_policy"],
                economics_coverage=result["predicted"]["economics_coverage"].iloc[0],
                governance_mode=result["governance_mode"],
                artefact_kind="constrained_optimisation",
                governance_dependencies=gov_deps,
            )
            s["predicted"] = result["predicted"]
            # REQ-OPT-001 (Decision 16): disclose exactly which closed
            # objective-kind vocabulary entry the analyst selected, plus
            # every governed constraint's disposition/binding status at the
            # solution actually returned - never buried in raw session
            # state.
            s["objective_kind_vocabulary_selection"] = objective_display_kind
            s["governed_constraint_disclosures"] = result[
                "governed_constraint_disclosures"
            ]
            scenarios.append(s)
            set_state("scenarios", scenarios)
            st.success(f"Saved scenario '{name}'.")

with tab_unconstrained:
    st.caption(
        "Evaluation method: **steady-state monthly** - this optimiser mode does "
        "not support sequential weekly."
    )
    st.warning(
        "**Theoretical optimum, not a recommended plan.** This reallocates the same total budget "
        "freely, ignoring locks, timing commitments and operational constraints - shown for "
        "comparison only."
    )
    if st.button("Run unconstrained benchmark", type="primary"):
        if _objective_vocab_error:
            st.error(
                f"Cannot run optimisation: '{_objective_labels[objective_display_kind]}' "
                f"is not available: {_objective_vocab_error}"
            )
            result = None
        elif objective == "expected_value" and value_mapping is None:
            st.error(
                "Cannot run optimisation: 'Maximise expected value' needs an outcome value mapping - a value weight for every target outcome and a single governed currency across them (set on the Structure page)."
            )
            result = None
        else:
            with st.spinner("Optimising..."):
                # PR 82C: routed through ScenarioService.optimise() with a
                # typed OptimisationInput - the page no longer calls
                # optimize_scenario() directly.
                opt_service_result = ScenarioService().optimise(
                    OptimisationInput(
                        current_spend_plan=spend_plan,
                        months=months,
                        channels=meta.channels,
                        market=market,
                        meta=meta,
                        params=params,
                        reference_context_by_month=reference_context_by_month,
                        ltv=ltv,
                        objective=objective if planning_objective is None else None,
                        planning_objective=optimisation_objective,
                        constraints=[],
                        artefact_kind="unconstrained_benchmark",
                        conserve_total_budget=True,
                        activity_definitions=activity_definitions or None,
                        counterfactual_policy=counterfactual_policy,
                        cost_mapping_registry=governed_cost_registry,
                        cost_context_id="default",
                        cost_as_of_by_month=cost_as_of_by_month,
                        posterior_trace=trace,
                        posterior_evaluation_draws=50,
                        value_mapping=value_mapping,
                        currency_context=currency_context,
                        **identity_kwargs,
                        **scenario_governance_kwargs,
                    )
                )
                if opt_service_result.errors:
                    for _err in opt_service_result.errors:
                        st.error(f"Cannot run optimisation: {_err}")
                    result = None
                else:
                    result = opt_service_result.optimisation_result
            if result is not None:
                st.session_state["unconstrained_result"] = result

    result = _invalidate_stale_cached_result(
        "unconstrained_result",
        st.session_state.get("unconstrained_result"),
        current_governance_mode=governance_mode,
        current_counterfactual_fingerprint=counterfactual_policy.fingerprint(),
    )
    if result:
        # See the matching comment above (constrained-result section) - same
        # shared-vocabulary fix, applied here for the unconstrained result.
        if result["governance_mode"] == "exploratory":
            st.caption("**Planning use**")
            render_status_badge("exploratory")
        else:
            st.caption("**Planning use: Official planning**")
        c1, c2 = st.columns(2)
        c1.metric(
            f"Current total ({_objective_labels[objective_display_kind]})",
            f"{result['current_objective_value']:,.0f}",
        )
        c2.metric(
            "Theoretical optimum",
            f"{result['objective_value']:,.0f}",
            delta=f"{result['objective_value'] - result['current_objective_value']:,.0f}",
        )

        st.markdown("**Economics by month: current vs theoretical optimum**")
        st.caption(
            "Calculated by the model evaluator; scope-limited measures remain visibly unavailable "
            "where the benchmark is not supported."
        )
        current_econ = monthly_economics_table(result["current_predicted"])
        current_econ.insert(0, "plan", "current")
        optimised_econ = monthly_economics_table(result["predicted"])
        optimised_econ.insert(0, "plan", "theoretical optimum")
        combined_econ = pd.concat([current_econ, optimised_econ], ignore_index=True)
        _render_economics_table(
            combined_econ,
            technical_title="Technical details · benchmark economics fields",
        )
        if not (
            whole_plan_scope_compatible(result["current_predicted"])
            and whole_plan_scope_compatible(result["predicted"])
        ):
            st.caption(
                "Whole-plan CPA/ROI is unavailable for one or more months above - see "
                "paid-media-only CPA/ROI instead."
            )

        st.markdown(
            "**Theoretical-optimum spend plan** - unconstrained benchmark, not a recommended plan"
        )
        unconstrained_plan_df = pd.DataFrame(result["spend_plan"]).T
        st.dataframe(
            unconstrained_plan_df,
            width="stretch",
            column_config=dataframe_column_config(unconstrained_plan_df),
        )


def _filter_current_scenarios(
    scenarios, current_cost_mapping_fingerprint, current_counterfactual_fingerprint
):
    """A scenario saved under a since-edited cost mapping or counterfactual
    policy predicts totals that no longer reflect governance now in effect
    - comparing it alongside current scenarios would be indistinguishable
    from a current comparison (Corrective PR C9/review finding). Shared by
    the steady-state and sequential-weekly saved-scenario sections below -
    both dict shapes carry `governance_dependencies` the same way
    (`sequential_scenario_to_dict` populates it identically to
    `scenario_to_dict`), so one staleness check covers both."""
    current_scenarios = []
    stale_scenario_names = []
    for scenario in scenarios:
        scenario_cf_fp = (scenario.get("governance_dependencies") or {}).get(
            "counterfactual_policy_fingerprint"
        )
        if scenario_cf_fp and scenario_cf_fp != current_counterfactual_fingerprint:
            stale_scenario_names.append(scenario.get("name", "(unnamed)"))
            continue
        try:
            dependency_fingerprint = resolve_scenario_cost_mapping_fingerprint(scenario)
        except ValueError:
            # Conflicting top-level vs. nested fingerprints - neither can be
            # trusted, so fail closed rather than silently picking one.
            stale_scenario_names.append(scenario.get("name", "(unnamed)"))
            continue
        if not dependency_fingerprint:
            current_scenarios.append(scenario)
            continue
        try:
            require_current_cost_mapping(scenario, current_cost_mapping_fingerprint)
        except ValueError:
            stale_scenario_names.append(scenario.get("name", "(unnamed)"))
        else:
            current_scenarios.append(scenario)
    return current_scenarios, stale_scenario_names


with SectionCard(
    "Saved scenarios",
    description=(
        "Persisted state: explicitly saved plans, distinct from the proposed (not-yet-saved) "
        "plans shown in the tabs above - saving is the only way a plan lands here."
    ),
):
    scenarios = get_state("scenarios") or []
    # WP5 part 4: a saved sequential-weekly scenario has no `predicted`
    # DataFrame (`compare_scenarios` requires one) - split by calculation
    # method rather than passing a mixed list into the steady-state-only
    # comparison below.
    steady_state_scenarios = [
        s for s in scenarios if s.get("calculation_method") != "sequential_weekly"
    ]
    sequential_scenarios_saved = [
        s for s in scenarios if s.get("calculation_method") == "sequential_weekly"
    ]
    current_cost_mapping_fingerprint = cost_mapping_registry.fingerprint()
    current_counterfactual_fingerprint = counterfactual_policy.fingerprint()

    if steady_state_scenarios:
        current_scenarios, stale_scenario_names = _filter_current_scenarios(
            steady_state_scenarios,
            current_cost_mapping_fingerprint,
            current_counterfactual_fingerprint,
        )
        if stale_scenario_names:
            st.warning(
                "Excluded from the comparison below because their governed cost "
                "mapping or counterfactual policy has since changed - regenerate "
                f"them to compare current totals: {', '.join(stale_scenario_names)}"
            )
        if current_scenarios:
            compare_df = compare_scenarios(current_scenarios)
            compare_display = compare_df.copy()
            if "governance_mode" in compare_display.columns:
                compare_display["governance_mode"] = compare_display[
                    "governance_mode"
                ].replace(
                    {
                        "official": "Official planning",
                        "exploratory": "Exploratory sensitivity",
                    }
                )
            compare_display = compare_display.rename(columns=_SCENARIO_DISPLAY_COLUMNS)
            st.dataframe(
                compare_display,
                width="stretch",
                column_config=dataframe_column_config(compare_display),
            )
            render_technical_details(
                title="Technical details · saved scenario comparison",
                details={
                    "Comparison source": "Totals and labels are supplied by the saved scenario comparison service.",
                    "Planning use values": "Official planning and Exploratory sensitivity are display labels for the stored official/exploratory values.",
                },
            )
        elif not stale_scenario_names:
            st.info("No steady-state scenarios saved yet.")
    else:
        st.info("No steady-state scenarios saved yet.")

    if sequential_scenarios_saved:
        st.markdown("**Saved sequential-weekly scenarios**")
        seq_current, seq_stale_names = _filter_current_scenarios(
            sequential_scenarios_saved,
            current_cost_mapping_fingerprint,
            current_counterfactual_fingerprint,
        )
        if seq_stale_names:
            st.warning(
                "Excluded below because their governed cost mapping or "
                "counterfactual policy has since changed - regenerate them to "
                f"compare current totals: {', '.join(seq_stale_names)}"
            )
        if seq_current:
            seq_rows = []
            for scenario in seq_current:
                ev = scenario["sequential_evaluation"]
                weekly = np.array(ev["weekly_incremental"])
                row = {
                    "name": scenario.get("name", "(unnamed)"),
                    "market": scenario.get("market", ""),
                    "governance_mode": scenario.get("governance_mode", ""),
                    "weeks": len(ev.get("weekly_period_labels", [])),
                }
                for i, oid in enumerate(ev.get("outcome_ids", [])):
                    row[f"total_{readable_label(oid)}"] = (
                        float(weekly[:, i].sum()) if weekly.size else 0.0
                    )
                seq_rows.append(row)
            seq_display = pd.DataFrame(seq_rows)
            st.dataframe(
                seq_display,
                width="stretch",
                column_config=dataframe_column_config(seq_display),
            )
            st.caption(
                "Totals are the plan-window weekly incremental outcome summed per "
                "outcome - not directly comparable to the steady-state monthly "
                "comparison above (a different calculation method). Terminal "
                "carryover and posterior uncertainty are not shown in this "
                "comparison - re-evaluate the scenario in the manual tab above to "
                "see them."
            )

render_next_step("scenario_planner")
