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
    CONSTRAINT_KIND_LABELS,
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
from ancestry_mmm.core.uncertainty import evaluate_scenario_with_uncertainty
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
)
from ancestry_mmm.core.validation_policy import (
    load_approval_readiness,
    load_threshold_policy,
)
from ancestry_mmm.application.scenario_service import (
    ManualScenarioInput,
    OptimisationInput,
    ScenarioService,
)
from ancestry_mmm.data.preprocessor import create_fourier_features_from_calendar


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
    "**Steady-state monthly approximation.** Predicted outcomes hold spend constant within a "
    "month and treat it as having reached its adstock steady state, so a month's outcome is a "
    "closed-form function of that month's spend - no MCMC in the planning loop, no sequential "
    "week-over-week carry-in simulation, no capacity-constrained delivery model, and no "
    "Chronos-2 (or other external) forecasting path. This is what is actually implemented today "
    "(see core/predict.py) - not a placeholder description of a future capability."
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
nbt_completeness_metadata = get_state("net_billthrough_metadata")
if frame is None or meta is None or params is None:
    st.markdown("---")
    render_empty_state(
        "No trained model yet. Complete Model Training first.",
        button_label="Go to Model Training",
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
        "This model hasn't been approved yet. Approve it on Diagnostics before planning scenarios - "
        "only an approved model's results may drive the planner."
    )
    if st.button("Go to Diagnostics"):
        st.switch_page("pages/06_Diagnostics.py")
    st.stop()
if not approval_matches_current:
    st.warning(
        "This model's approval no longer matches the current fitted model, policy, or "
        "readiness evidence"
        + (f": {approval_invalid_reason}" if approval_invalid_reason else "")
        + " - the model must be reviewed and approved again on Diagnostics before "
        "planning scenarios."
    )
    if st.button("Go to Diagnostics", key="stale_approval_diagnostics"):
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

render_glossary(["Scenario", "Constraint", "Response curve", "Incremental outcome"])

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
        + ", ".join(readable_label(c) for c in sorted(unmapped_cost_bearing_channels))
        + ". Configure a mapping on Channel & Media Units to seed a spend default."
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
            ch: f"{readable_label(ch)} ({info['unit_type']})"
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
                f"{readable_label(ch)} = {info['avg_cost_per_unit']:,.2f} / {info['unit_type']}"
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
            "Governance mode changed since this result was computed - re-run "
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
st.markdown("### Planning assumptions & governance")
st.caption(
    "These are assumptions the plan is evaluated under, not decisions in the spend-plan "
    "grid above - the counterfactual policy, governance mode, and optimisation objective "
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
    "Demand-capture counterfactual",
    _DEMAND_CAPTURE_RULE_OPTIONS,
    index=_demand_capture_rule_index,
    horizontal=True,
    format_func=lambda value: {
        "hold_plan": "Hold demand-capture activity at the candidate level",
        "zero": "Set demand-capture activity to zero (sensitivity only)",
    }[value],
    help=(
        "Demand capture is never zeroed implicitly. This explicit selection "
        "is stored with the scenario and objective."
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
    "Governance mode",
    ["official", "exploratory"],
    horizontal=True,
    key="scenario_governance_mode",
    format_func=lambda value: {
        "official": "Official - requires approved activity and outcome governance",
        "exploratory": "Exploratory - sensitivity only, skips approval gates",
    }[value],
    help=(
        "Official mode blocks optimisation against any activity whose governance "
        "isn't approved (draft or rejected model role, economic treatment, or "
        "planning eligibility must not drive an official recommendation), and "
        "against any target outcome without a matching, active approval. "
        "Exploratory mode skips both checks - always visibly labelled below, "
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
_objective_labels = {
    "fh_net_billthrough": "Maximise incremental Family History net bill-through",
    "fh_gsa": "Maximise Family History GSAs",
    "fh_signups": "Maximise Family History sign-ups",
    "dna_kits": "Maximise DNA kit sales",
    "expected_value": "Maximise LTV-weighted expected value",
}
objective = st.radio(
    "Optimisation objective",
    _objective_options,
    horizontal=True,
    format_func=lambda x: _objective_labels[x],
    help=FIELD_HELP["ltv"],
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

# G2A.7a.10 (brief section 9, 11): one canonical OutcomeValueMapping drives
# manual evaluation, both optimiser modes, and posterior uncertainty alike -
# replacing the previous split where the objective resolved against
# catalogue weights but calculation used the legacy segment_ltv dict.
# Prefer outcome-ID-keyed catalogue weights; fall back to the strict legacy
# segment-LTV adapter only when catalogue weights don't cover every target.
value_mapping: OutcomeValueMapping | None = None
if objective == "expected_value" and value_currency and _target_ids_for_value:
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
            value_mapping = OutcomeValueMapping.from_dict(_stored_value_mapping_dict)
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

st.caption(
    "Each objective states exactly what it maximises - Family History GSAs, Family History sign-ups "
    "and DNA kit sales are never silently combined into one generic 'volume' number. "
    "**Official planning requires each target outcome to have an approved definition "
    "(Structure → Outcome Governance).**"
)
if _objective_error:
    st.error(f"Objective configuration: {_objective_error}")
elif objective == "expected_value":
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
tab_manual, tab_constrained, tab_unconstrained = st.tabs(
    ["Manual", "Constrained optimisation", "Unconstrained benchmark"]
)

with tab_manual:
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
    st.dataframe(
        predicted, width="stretch", column_config=dataframe_column_config(predicted)
    )
    totals = (
        predicted.groupby("outcome_id")[["predicted_outcome", "value"]]
        .sum()
        .reset_index()
    )
    st.markdown("**Totals by outcome**")
    st.dataframe(totals, width="stretch", column_config=dataframe_column_config(totals))
    if (
        "total_value_is_complete" in predicted.columns
        and not predicted["total_value_is_complete"].all()
    ):
        st.caption(
            "Total predicted value excludes outcome_id(s) with no LTV weight configured (never "
            "silently treated as $1) - set a value weight for every outcome on the Structure page "
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

    st.markdown("**Governed economics by month**")
    st.caption(
        "Straight from the core evaluator - never recomputed on this page. `whole_plan_*` "
        "fields are blank for a month where response-only activity contributes to the "
        "incremental outcome without a corresponding spend (a whole-plan cost-per-outcome "
        "would be misleading there); `paid_media_*` fields are scoped to paid spend only and "
        "are never suppressed this way."
    )
    econ_table = monthly_economics_table(predicted)
    st.dataframe(
        econ_table, width="stretch", column_config=dataframe_column_config(econ_table)
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
                st.dataframe(
                    summary_df,
                    width="stretch",
                    column_config=dataframe_column_config(summary_df),
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

with tab_constrained:
    st.markdown("#### Constraints (distinct from the assumptions above)")
    st.markdown(
        "Add the constraints Ancestry actually plans against: locked cells (e.g. committed TV "
        "bookings), fixed channel/month totals, bounded movement from the current plan, and "
        "minimum-spend floors (e.g. DNA promotional windows). Constraints are hard bounds the "
        "optimiser must respect; they are separate from the planning assumptions (counterfactual "
        "policy, governance mode, objective) set above, which shape how a plan is evaluated "
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
            format_func=lambda c: c if c == "(any)" else readable_label(c),
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
            f"channel={readable_label(c.channel) or 'any'}, month={c.month or 'any'}, value={c.value}, max % movement={c.max_pct_move}"
        )
        if c2.button("Remove", key=f"rm_constraint_{i}"):
            st.session_state["scenario_constraints"].pop(i)
            st.rerun()

    if st.button("Run constrained optimisation", type="primary"):
        if objective == "expected_value" and value_mapping is None:
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
                        constraints=st.session_state["scenario_constraints"],
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
            st.caption("**Governance mode** (persisted with this result)")
            render_status_badge("exploratory")
        else:
            st.caption("**Governance mode: Official** (persisted with this result)")
        c1, c2 = st.columns(2)
        c1.metric(
            f"Current total ({_objective_labels[objective]})",
            f"{result['current_objective_value']:,.0f}",
        )
        c2.metric(
            "Optimised total",
            f"{result['objective_value']:,.0f}",
            delta=f"{result['objective_value'] - result['current_objective_value']:,.0f}",
        )

        st.markdown("**Governed economics by month: current vs optimised**")
        st.caption(
            "Straight from the core evaluator - never recomputed on this page. `whole_plan_*` "
            "fields are blank for a month where response-only activity contributes to the "
            "incremental outcome without a corresponding spend; `paid_media_*` fields are "
            "scoped to paid spend only and are never suppressed this way."
        )
        current_econ = monthly_economics_table(result["current_predicted"])
        current_econ.insert(0, "plan", "current")
        optimised_econ = monthly_economics_table(result["predicted"])
        optimised_econ.insert(0, "plan", "optimised")
        combined_econ = pd.concat([current_econ, optimised_econ], ignore_index=True)
        st.dataframe(
            combined_econ,
            width="stretch",
            column_config=dataframe_column_config(combined_econ),
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
        st.dataframe(
            result["predicted"],
            width="stretch",
            column_config=dataframe_column_config(result["predicted"]),
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
        if objective == "expected_value" and value_mapping is None:
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
            st.caption("**Governance mode**")
            render_status_badge("exploratory")
        else:
            st.caption("**Governance mode: Official**")
        c1, c2 = st.columns(2)
        c1.metric(
            f"Current total ({_objective_labels[objective]})",
            f"{result['current_objective_value']:,.0f}",
        )
        c2.metric(
            "Theoretical optimum",
            f"{result['objective_value']:,.0f}",
            delta=f"{result['objective_value'] - result['current_objective_value']:,.0f}",
        )

        st.markdown("**Governed economics by month: current vs theoretical optimum**")
        st.caption(
            "Straight from the core evaluator - never recomputed on this page. `whole_plan_*` "
            "fields are blank for a month where response-only activity contributes to the "
            "incremental outcome without a corresponding spend; `paid_media_*` fields are "
            "scoped to paid spend only and are never suppressed this way."
        )
        current_econ = monthly_economics_table(result["current_predicted"])
        current_econ.insert(0, "plan", "current")
        optimised_econ = monthly_economics_table(result["predicted"])
        optimised_econ.insert(0, "plan", "theoretical optimum")
        combined_econ = pd.concat([current_econ, optimised_econ], ignore_index=True)
        st.dataframe(
            combined_econ,
            width="stretch",
            column_config=dataframe_column_config(combined_econ),
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

with SectionCard(
    "Saved scenarios",
    description=(
        "Persisted state: explicitly saved plans, distinct from the proposed (not-yet-saved) "
        "plans shown in the tabs above - saving is the only way a plan lands here."
    ),
):
    scenarios = get_state("scenarios") or []
    if scenarios:
        # A scenario saved under a since-edited cost mapping predicts totals
        # that no longer reflect the governed mapping in effect now - comparing
        # it alongside current scenarios would be indistinguishable from a
        # current comparison (Corrective PR C9). Only a scenario whose resolved
        # dependency (Corrective PR E2.1: nested governance_dependencies is the
        # current contract, the top-level field only an explicit legacy
        # fallback - see resolve_scenario_cost_mapping_fingerprint) actually
        # names a cost mapping has this dependency at all; a scenario that
        # never depended on cost mappings is never flagged stale by this check.
        current_cost_mapping_fingerprint = cost_mapping_registry.fingerprint()
        # Corrective review finding: this comparison only ever checked cost
        # mappings - a scenario saved under a since-changed counterfactual
        # policy predicted totals under a demand-capture rule the project no
        # longer uses, but was never excluded or flagged, indistinguishable from
        # a genuinely current scenario.
        current_counterfactual_fingerprint = counterfactual_policy.fingerprint()
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
                dependency_fingerprint = resolve_scenario_cost_mapping_fingerprint(
                    scenario
                )
            except ValueError:
                # Conflicting top-level vs. nested fingerprints - neither can
                # be trusted, so fail closed rather than silently picking one.
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
        if stale_scenario_names:
            st.warning(
                "Excluded from the comparison below because their governed cost "
                "mapping or counterfactual policy has since changed - regenerate "
                f"them to compare current totals: {', '.join(stale_scenario_names)}"
            )
        if current_scenarios:
            compare_df = compare_scenarios(current_scenarios)
            st.dataframe(
                compare_df,
                width="stretch",
                column_config=dataframe_column_config(compare_df),
            )
        elif not stale_scenario_names:
            st.info("No scenarios saved yet.")
    else:
        st.info("No scenarios saved yet.")

render_next_step("scenario_planner")
