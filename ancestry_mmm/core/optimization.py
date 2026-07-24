"""
Scenario planning and budget optimisation for the joint hierarchical FH model.

Three modes, matching how Ancestry actually plans budgets rather than just
producing a mathematically optimal split:

- Manual: edit spend directly, see predicted outcomes update (evaluate_scenario).
- Constrained: optimise subject to locked cells, fixed channel/month totals,
  bounded movement from the current plan, and minimum-spend floors
  (optimize_scenario with constraints).
- Unconstrained benchmark: optimise the same total budget with none of the
  above constraints - a theoretical-optimum comparison point, not a plan.

All three evaluate expected outcomes with the steady-state response
approximation in core.predict (see that module's docstring): spend held
constant within a month is treated as having reached its adstock
steady-state, so a month's expected outcome is a closed-form function of
that month's channel spend - no MCMC in the optimisation loop.

Works against either model type (Phase 3c) via `model_type`: `"shared"`
(Model A, the default - `steady_state_outcome_response`, `params` an
`FHPosteriorParams`) or `"market_specific"` (Model C -
`steady_state_outcome_response_market_specific`, `params` an
`FHMarketSpecificPosteriorParams`). Both functions have the identical
`(market, spend_by_channel, meta, params, reference_context) -> {outcome_id:
rate}` contract - `market` already selects the right market-specific
baseline/K/beta for Model C the same way it already selected the right
market baseline for Model A - so nothing else in this module's planning
math (constraints, bounds, the optimiser objective) needs to know which
model type it's driving.

evaluate_scenario and optimize_scenario are the core planning entry points,
and both require a ModelApproval that matches the exact model run supplying
`meta`/`params` (model_run_id plus data/spec/posterior fingerprints - see
core.fingerprint and core.approval). This is enforced here, not only by the
Streamlit Scenario Planner page's own checks, so a direct call to either
function - bypassing the page - still requires a valid, matching approval.

Kept from the original single-KPI implementation for reuse:
calculate_marginal_roi_loglog, optimize_budget_marginal_roi, calculate_expected_lift.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import warnings
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

import numpy as np
import pandas as pd
from scipy.optimize import minimize, LinearConstraint

from .approval import ModelApproval, require_matching_approval
from .activities import (
    ActivityDefinition,
    activity_by_model_input,
    activity_definitions_fingerprint,
)
from .hierarchical_model import FHModelMeta
from .media_costs import CostMappingRegistry
from .outcomes import (
    fh_gsa_outcome_ids, fh_signup_outcome_ids, fh_net_billthrough_outcome_ids, dna_kit_sale_outcome_ids, select_outcome_ids,
    outcome_catalogue_at_fit_by_id, eligible_outcome_ids,
    METRIC_KEY_FH_GSA, METRIC_KEY_FH_SIGNUP, METRIC_KEY_FH_NET_BILLTHROUGH_COUNT, METRIC_KEY_DNA_KIT_SALE,
)
from .predict import FHPosteriorParams, steady_state_outcome_response
from .market_specific_predict import FHMarketSpecificPosteriorParams, steady_state_outcome_response_market_specific
from .scenario_governance import (
    CounterfactualPolicy,
    ScenarioPlan,
    classify_activity_plan,
    resolve_counterfactual,
    resolve_scenario_plan,
)

WEEKS_PER_MONTH = 365.25 / 12 / 7  # ~4.348

AnyPosteriorParams = Union[FHPosteriorParams, FHMarketSpecificPosteriorParams]

PLANNING_ESTIMANDS = {
    "total_outcome",
    "incremental_outcome",
    "incremental_value",
}


@dataclass(frozen=True)
class PlanningObjective:
    """Typed objective and estimand stored with every optimised scenario."""

    estimand: str = "incremental_outcome"
    metric_key: str = METRIC_KEY_FH_NET_BILLTHROUGH_COUNT
    target_outcome_ids: Tuple[str, ...] = ()
    value_currency: Optional[str] = None
    spend_scope: str = "cost_bearing_decisions"
    activity_scope: str = "optimisable_interventions"
    counterfactual_policy_fingerprint: Optional[str] = None
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.estimand not in PLANNING_ESTIMANDS:
            raise ValueError(f"Unsupported planning estimand: {self.estimand}")
        if self.estimand == "incremental_value" and not self.value_currency:
            raise ValueError("value objectives require value_currency")

    def to_dict(self) -> dict:
        values = asdict(self)
        values["target_outcome_ids"] = list(self.target_outcome_ids)
        return values


def planning_objective_from_legacy(
    objective: str,
    *,
    value_currency: str | None = None,
    counterfactual_policy_fingerprint: str | None = None,
) -> PlanningObjective:
    """Migrate a saved legacy objective string to the typed G2A.5 contract."""

    metric_keys = {
        "fh_gsa": METRIC_KEY_FH_GSA,
        "fh_signups": METRIC_KEY_FH_SIGNUP,
        "fh_net_billthrough": METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
        "dna_kits": METRIC_KEY_DNA_KIT_SALE,
        "weighted_mix": "weighted_mix",
    }
    if objective in {"expected_value", "value"}:
        return PlanningObjective(
            estimand="incremental_value",
            metric_key="expected_value",
            value_currency=value_currency or "UNSPECIFIED",
            counterfactual_policy_fingerprint=(
                counterfactual_policy_fingerprint
            ),
        )
    if objective not in metric_keys:
        raise ValueError(f"cannot migrate unknown legacy objective {objective!r}")
    return PlanningObjective(
        estimand="incremental_outcome",
        metric_key=metric_keys[objective],
        counterfactual_policy_fingerprint=counterfactual_policy_fingerprint,
    )


@dataclass(frozen=True)
class OptimizationResource:
    """A single conserved optimisation resource - the unit the solver is
    allowed to trade decision variables against. `eligible_activity_ids`
    scopes which activities may move as part of this resource; every other
    activity in the plan is held fixed for the duration of an optimisation
    run against this resource, regardless of its own `planning_eligibility`.
    Prevents the historical defect of summing GBP spend, impressions, GRPs
    and CRM sends into one flat vector and conserving their numerical total
    (docs/g2a5_scenario_governance.md's dimensional-correctness gap)."""

    resource_id: str
    unit: str
    currency: Optional[str] = None
    eligible_activity_ids: Tuple[str, ...] = ()
    total: Optional[float] = None
    schema_version: int = 1

    def to_dict(self) -> dict:
        values = asdict(self)
        values["eligible_activity_ids"] = list(self.eligible_activity_ids)
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "OptimizationResource":
        payload = dict(values)
        payload["eligible_activity_ids"] = tuple(
            payload.get("eligible_activity_ids") or ()
        )
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in payload.items() if key in known})


def monetary_optimization_resource(
    activity_definitions: List[ActivityDefinition],
    market: str,
    *,
    resource_id: str = "monetary_budget",
    currency: Optional[str] = None,
    total: Optional[float] = None,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: str = "default",
    cost_as_of: Optional[str] = None,
) -> OptimizationResource:
    """Default resource: every cost-bearing, optimisable activity for this
    market that is denominated in one governed currency - the monetary
    budget a spend optimisation is allowed to move. Response-only
    quantities, controls, events, mediators and fixed/scenario-only
    activity are never included, whatever `planning_eligibility` they
    carry - they are not denominated in this resource's unit.

    A resource must never silently pool decisions from more than one
    currency into one conserved total (the same currency-purity rule as
    `_validate_no_mixed_currency_value_weights`) - one USD must not be
    conserved as interchangeable with one GBP. When `cost_mapping_registry`
    is given, each candidate's effective mapping currency is resolved via
    `cost_context_id`/`cost_as_of`; a candidate with no resolvable mapping,
    or whose resolved currency disagrees with the resource's currency, is
    excluded rather than pooled in. If resolvable candidates span more than
    one currency and `currency` wasn't given explicitly, raises - the
    caller must state which currency this resource optimises. Without a
    `cost_mapping_registry`, currency cannot be checked and every
    cost-bearing optimisable activity is included as before (only safe when
    the caller has already validated currency purity itself)."""

    by_input = activity_by_model_input(activity_definitions, market)
    candidates = {
        definition.activity_id: definition
        for definition in by_input.values()
        if definition.is_cost_bearing
        and definition.planning_eligibility == "optimisable"
    }
    if cost_mapping_registry is None:
        return OptimizationResource(
            resource_id=resource_id,
            unit="currency",
            currency=currency,
            eligible_activity_ids=tuple(sorted(candidates)),
            total=total,
        )

    currency_by_activity: Dict[str, str] = {}
    for activity_id, definition in candidates.items():
        mapping = cost_mapping_registry.resolve(
            market, definition.channel, cost_context_id, as_of=cost_as_of,
        )
        if mapping is not None:
            currency_by_activity[activity_id] = mapping.currency

    resolved_currencies = set(currency_by_activity.values())
    if currency is None:
        if len(resolved_currencies) > 1:
            raise ValueError(
                "cost-bearing activities resolve to more than one currency "
                f"({sorted(resolved_currencies)}) - pass an explicit "
                "currency= to select which one this resource optimises; a "
                "monetary resource must never pool decisions across "
                "currencies into one conserved total."
            )
        currency = next(iter(resolved_currencies), None)

    eligible = tuple(
        sorted(
            activity_id
            for activity_id, resolved in currency_by_activity.items()
            if resolved == currency
        )
    )
    return OptimizationResource(
        resource_id=resource_id,
        unit="currency",
        currency=currency,
        eligible_activity_ids=eligible,
        total=total,
    )


def seed_monetary_and_quantity_defaults(
    *,
    avg_weekly_media_input: Mapping[str, float],
    activity_definitions: List[ActivityDefinition],
    market: str,
    cost_mapping_registry: Optional[CostMappingRegistry],
    cost_context_id: str = "default",
    as_of: Optional[str] = None,
    weeks_per_month: float = WEEKS_PER_MONTH,
) -> Tuple[Dict[str, float], List[str]]:
    """Seed a default monthly scenario plan from historical weekly model
    input, without reinterpreting a non-monetary model input as currency.

    Cost-bearing activities are converted through the governed cost
    mapping's `media_input_to_spend` (never assumed to already be spend);
    an activity with no resolvable effective mapping defaults to 0 rather
    than silently presenting a media-input quantity as a currency amount.
    Non-cost-bearing activities (response-only, not-applicable) are seeded
    directly from their historical model-input quantity, which is the
    correct unit for `activity_quantity_assumptions_by_period`.

    Returns `(defaults_by_channel, unmapped_cost_bearing_channels)` - the
    second list flags cost-bearing channels that were zero-defaulted for
    lack of an effective mapping, so a caller can surface that explicitly
    rather than let a silent zero look like a deliberate planning choice.
    """
    by_input = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions
        else {}
    )
    defaults: Dict[str, float] = {}
    unmapped: List[str] = []
    for channel, weekly_value in avg_weekly_media_input.items():
        definition = by_input.get(channel)
        if definition is None or not definition.is_cost_bearing:
            defaults[channel] = float(weekly_value) * weeks_per_month
            continue
        mapping = (
            cost_mapping_registry.resolve(
                market, definition.channel, cost_context_id, as_of=as_of,
            )
            if cost_mapping_registry is not None
            else None
        )
        if mapping is None:
            defaults[channel] = 0.0
            unmapped.append(channel)
            continue
        # Scale to the monthly media-input quantity *before* converting
        # through the mapping - a nonlinear mapping (e.g. piecewise-linear
        # marginal cost) does not commute with scaling, so
        # media_input_to_spend(weekly) * weeks_per_month is only correct
        # for a linear mapping and silently seeds the wrong monthly spend
        # for anything else.
        defaults[channel] = float(
            mapping.media_input_to_spend(float(weekly_value) * weeks_per_month)
        )
    return defaults, unmapped


def monetary_plan_to_media_input(
    spend_plan: Dict[str, Dict[str, float]],
    *,
    market: str,
    registry: CostMappingRegistry,
    cost_context_id: str,
    as_of_by_period: Dict[str, str],
) -> Dict[str, Dict[str, float]]:
    """Convert local-currency decisions through effective governed mappings."""

    converted: Dict[str, Dict[str, float]] = {}
    for period, channel_spend in spend_plan.items():
        if period not in as_of_by_period:
            raise ValueError(f"Missing cost-mapping date for period {period}")
        converted[period] = {}
        for channel, spend in channel_spend.items():
            mapping = registry.resolve(
                market,
                channel,
                cost_context_id,
                as_of=as_of_by_period[period],
            )
            if mapping is None:
                raise ValueError(
                    "Monetary planning blocked without an approved effective "
                    f"mapping for {market}/{channel}/{period}"
                )
            converted[period][channel] = float(
                mapping.spend_to_media_input(spend)
            )
    return converted


def _steady_state_response_fn(model_type: str):
    if model_type not in ("shared", "market_specific"):
        raise ValueError(f"model_type must be 'shared' or 'market_specific', got {model_type!r}")
    return steady_state_outcome_response_market_specific if model_type == "market_specific" else steady_state_outcome_response


# ---------------------------------------------------------------------------
# Scenario evaluation (manual mode)
# ---------------------------------------------------------------------------

def evaluate_scenario(
    spend_plan: Dict[str, Dict[str, float]],
    market: str,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    *,
    model_type: str = "shared",
    approval: ModelApproval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_month: Optional[Dict[str, str]] = None,
    counterfactual_media_input_by_month: Optional[
        Dict[str, Dict[str, float]]
    ] = None,
    planning_objective: Optional[PlanningObjective] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    scenario_plan: Optional[ScenarioPlan] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
) -> pd.DataFrame:
    """Evaluate total and incremental outcomes under governed activity scopes."""
    require_matching_approval(
        approval,
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    )
    response_fn = _steady_state_response_fn(model_type)
    ltv = ltv or {}
    gsa_ids = set(fh_gsa_outcome_ids(meta))
    signup_ids = set(fh_signup_outcome_ids(meta))
    nbt_ids = set(fh_net_billthrough_outcome_ids(meta))
    dna_ids = set(dna_kit_sale_outcome_ids(meta))
    catalogue_by_id = outcome_catalogue_at_fit_by_id(meta)
    activity_map = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions is not None
        else {}
    )
    if activity_definitions is not None:
        missing_activity = set(meta.channels) - set(activity_map)
        if missing_activity:
            raise ValueError(
                f"Missing activity definitions for model inputs "
                f"{sorted(missing_activity)}"
            )
    activity_fingerprint = (
        activity_definitions_fingerprint(activity_definitions)
        if activity_definitions is not None
        else None
    )
    policy = counterfactual_policy or CounterfactualPolicy()
    if planning_objective is not None:
        if (
            planning_objective.counterfactual_policy_fingerprint
            and planning_objective.counterfactual_policy_fingerprint
            != policy.fingerprint()
        ):
            raise ValueError(
                "PlanningObjective counterfactual fingerprint does not match "
                "the supplied CounterfactualPolicy"
            )
    rows = []
    if scenario_plan is None and activity_definitions is not None:
        scenario_plan = classify_activity_plan(
            spend_plan,
            market=market,
            activity_definitions=activity_definitions,
        )
    if scenario_plan is not None:
        model_input_plan, _, coverage = resolve_scenario_plan(
            scenario_plan,
            market=market,
            activity_definitions=activity_definitions,
            cost_mapping_registry=cost_mapping_registry,
            cost_context_id=cost_context_id or "default",
            cost_as_of_by_period=cost_as_of_by_month,
        )
        monetary_plan = scenario_plan.monetary_decisions_by_period
        quantity_plan = scenario_plan.activity_quantity_assumptions_by_period
    else:
        model_input_plan = (
            monetary_plan_to_media_input(
                spend_plan,
                market=market,
                registry=cost_mapping_registry,
                cost_context_id=cost_context_id or "default",
                as_of_by_period=cost_as_of_by_month or {},
            )
            if cost_mapping_registry is not None
            else spend_plan
        )
        monetary_plan = spend_plan
        quantity_plan = {}
        coverage = {
            "economics_status": "legacy_monetary_assumption",
            "covered_activity_ids": [],
            "uncovered_activity_ids": [],
            "excluded_response_only_activity_ids": [],
            "mapping_ids": [],
            "mapping_effective_dates": [],
            "value_coverage": "evaluated_separately",
            "currency_coverage": "legacy_unspecified",
            "counterfactual_scope": policy.policy_id,
        }
        if activity_map:
            active_definitions = [
                activity_map[column]
                for values in spend_plan.values()
                for column, amount in values.items()
                if float(amount) != 0 and column in activity_map
            ]
            costed = sorted(
                {
                    item.activity_id
                for item in active_definitions
                if item.is_cost_bearing
                }
            )
            response_only = sorted(
                {
                    item.activity_id
                for item in active_definitions
                if item.economic_treatment == "response_only"
                }
            )
            coverage.update(
                {
                    "economics_status": (
                        "mixed_cost_and_response_only"
                        if costed and response_only
                        else "response_only"
                        if response_only
                        else "monetary_economics_available"
                    ),
                    "covered_activity_ids": costed,
                    "excluded_response_only_activity_ids": response_only,
                }
            )

    resolved_counterfactual = (
        counterfactual_media_input_by_month
        if counterfactual_media_input_by_month is not None
        else resolve_counterfactual(
            model_input_plan,
            market=market,
            activity_definitions=activity_definitions,
            policy=policy,
        )
    )

    def _scoped_counterfactual(
        month: str,
        treatment: str,
    ) -> dict[str, float]:
        values = dict(model_input_plan[month])
        for column, value in values.items():
            definition = activity_map.get(column)
            if (
                definition is not None
                and definition.economic_treatment == treatment
                and definition.model_role == "intervention"
                and definition.planning_eligibility == "optimisable"
            ):
                values[column] = 0.0
        return values

    def _period_costs(month: str) -> dict[str, float]:
        result = {
            "paid_media_cost": 0.0,
            "fully_loaded_cost": 0.0,
            "campaign_cost": 0.0,
        }
        for key, amount in monetary_plan.get(month, {}).items():
            definition = next(
                (
                    item
                    for item in activity_map.values()
                    if key
                    in {
                        item.activity_id,
                        item.resolved_model_input_column,
                        item.channel,
                    }
                ),
                None,
            )
            treatment = (
                definition.economic_treatment
                if definition is not None
                else "paid_media_cost"
            )
            if treatment in result:
                result[treatment] += float(amount)
        return result

    for month, media_input_by_activity in model_input_plan.items():
        ref = reference_context_by_month.get(month, {})
        weekly_rate = response_fn(
            market,
            media_input_by_activity,
            meta,
            params,
            ref,
            planning_only=True,
        )
        counterfactual_input = resolved_counterfactual[month]
        counterfactual_weekly_rate = response_fn(
            market,
            counterfactual_input,
            meta,
            params,
            ref,
            planning_only=True,
        )
        paid_counterfactual_input = _scoped_counterfactual(
            month, "paid_media_cost"
        )
        response_only_counterfactual_input = _scoped_counterfactual(
            month, "response_only"
        )
        paid_counterfactual_rates = response_fn(
            market,
            paid_counterfactual_input,
            meta,
            params,
            ref,
            planning_only=True,
        )
        response_only_counterfactual_rates = response_fn(
            market,
            response_only_counterfactual_input,
            meta,
            params,
            ref,
            planning_only=True,
        )
        costs = _period_costs(month)
        paid_spend = costs["paid_media_cost"]
        fully_loaded_owned_spend = costs["fully_loaded_cost"]
        campaign_cost_spend = costs["campaign_cost"]
        total_spend = sum(costs.values())
        non_costed_ids = sorted(
            {
                definition.activity_id
                for key, value in quantity_plan.get(month, {}).items()
                if float(value) != 0
                for definition in activity_map.values()
                if key
                in {
                    definition.activity_id,
                    definition.resolved_model_input_column,
                    definition.channel,
                }
            }
        )
        monthly_outcome_by_id = {oid: rate * WEEKS_PER_MONTH for oid, rate in weekly_rate.items()}
        counterfactual_outcome_by_id = {
            oid: rate * WEEKS_PER_MONTH
            for oid, rate in counterfactual_weekly_rate.items()
        }
        incremental_outcome_by_id = {
            oid: monthly_outcome_by_id[oid]
            - counterfactual_outcome_by_id[oid]
            for oid in monthly_outcome_by_id
        }
        paid_incremental_outcome_by_id = {
            oid: monthly_outcome_by_id[oid]
            - paid_counterfactual_rates[oid] * WEEKS_PER_MONTH
            for oid in monthly_outcome_by_id
        }
        response_only_incremental_outcome_by_id = {
            oid: monthly_outcome_by_id[oid]
            - response_only_counterfactual_rates[oid] * WEEKS_PER_MONTH
            for oid in monthly_outcome_by_id
        }
        fh_gsa = sum(v for oid, v in monthly_outcome_by_id.items() if oid in gsa_ids)
        fh_signups = sum(v for oid, v in monthly_outcome_by_id.items() if oid in signup_ids)
        fh_net_billthrough = sum(v for oid, v in monthly_outcome_by_id.items() if oid in nbt_ids)
        dna_kits = sum(v for oid, v in monthly_outcome_by_id.items() if oid in dna_ids)
        incremental_fh_gsa = sum(v for oid, v in incremental_outcome_by_id.items() if oid in gsa_ids)
        incremental_fh_signups = sum(v for oid, v in incremental_outcome_by_id.items() if oid in signup_ids)
        incremental_fh_nbt = sum(v for oid, v in incremental_outcome_by_id.items() if oid in nbt_ids)
        incremental_dna_kits = sum(v for oid, v in incremental_outcome_by_id.items() if oid in dna_ids)
        paid_incremental_fh_gsa = sum(
            value
            for oid, value in paid_incremental_outcome_by_id.items()
            if oid in gsa_ids
        )
        paid_incremental_fh_nbt = sum(
            value
            for oid, value in paid_incremental_outcome_by_id.items()
            if oid in nbt_ids
        )
        avg_cpa = (total_spend / incremental_fh_gsa) if incremental_fh_gsa > 0 and total_spend > 0 else None
        fh_signup_avg_cpa = (total_spend / incremental_fh_signups) if incremental_fh_signups > 0 else None
        nbt_avg_cpa = (total_spend / incremental_fh_nbt) if incremental_fh_nbt > 0 else None
        dna_avg_cpa = (total_spend / incremental_dna_kits) if incremental_dna_kits > 0 else None
        paid_media_incremental_cpa = (
            paid_spend / paid_incremental_fh_gsa
            if paid_spend > 0 and paid_incremental_fh_gsa > 0
            else None
        )
        paid_media_incremental_nbt_cpa = (
            paid_spend / paid_incremental_fh_nbt
            if paid_spend > 0 and paid_incremental_fh_nbt > 0
            else None
        )

        priced_ids = sorted(oid for oid in monthly_outcome_by_id if oid in ltv)
        unpriced_ids = sorted(oid for oid in monthly_outcome_by_id if oid not in ltv)
        _validate_no_mixed_currency_value_weights(priced_ids, ltv, catalogue_by_id)
        if not priced_ids:
            # Either ltv is entirely omitted, or none of this month's
            # outcome_ids happen to be in it - either way there is nothing
            # priced to report as "value" this month.
            value_status = "not configured"
            total_value = None
            total_value_is_complete = False
        elif unpriced_ids:
            value_status = "partial"
            total_value = sum(monthly_outcome_by_id[oid] * ltv[oid] for oid in priced_ids)
            total_value_is_complete = False
        else:
            value_status = "complete"
            total_value = sum(monthly_outcome_by_id[oid] * ltv[oid] for oid in priced_ids)
            total_value_is_complete = True
        incremental_total_value = (
            sum(
                incremental_outcome_by_id[oid] * ltv[oid]
                for oid in incremental_outcome_by_id
            )
            if total_value_is_complete
            else None
        )
        paid_incremental_total_value = (
            sum(
                paid_incremental_outcome_by_id[oid] * ltv[oid]
                for oid in paid_incremental_outcome_by_id
            )
            if total_value_is_complete
            else None
        )
        whole_plan_incremental_roi = (
            incremental_total_value / total_spend
            if incremental_total_value is not None and total_spend > 0
            else None
        )
        paid_media_incremental_roi = (
            paid_incremental_total_value / paid_spend
            if paid_incremental_total_value is not None and paid_spend > 0
            else None
        )
        period_coverage = dict(coverage)
        period_coverage.update(
            {
                "counterfactual_scope": policy.policy_id,
                "non_costed_activity_ids": non_costed_ids,
                "whole_plan_scope_compatible": not any(
                    abs(value) > 1e-12
                    for value in response_only_incremental_outcome_by_id.values()
                ),
            }
        )
        if not period_coverage["whole_plan_scope_compatible"]:
            avg_cpa = None
            fh_signup_avg_cpa = None
            nbt_avg_cpa = None
            dna_avg_cpa = None
            whole_plan_incremental_roi = None

        for oid, monthly_outcome in monthly_outcome_by_id.items():
            value = monthly_outcome * ltv[oid] if oid in ltv else None
            rows.append({
                "month": month,
                "outcome_id": oid,
                "predicted_outcome": monthly_outcome,
                "predicted_total_outcome": monthly_outcome,
                "predicted_counterfactual_outcome": counterfactual_outcome_by_id[oid],
                "incremental_outcome": incremental_outcome_by_id[oid],
                "incremental_outcome_all_activities": (
                    incremental_outcome_by_id[oid]
                ),
                "incremental_outcome_paid_decisions": (
                    paid_incremental_outcome_by_id[oid]
                ),
                "incremental_outcome_response_only_activities": (
                    response_only_incremental_outcome_by_id[oid]
                ),
                "counterfactual_media_input": dict(counterfactual_input),
                "resolved_counterfactual_vector": dict(counterfactual_input),
                "counterfactual_policy": policy.to_dict(),
                "counterfactual_policy_fingerprint": policy.fingerprint(),
                "value": value,
                "value_status": value_status,
                "unpriced_outcome_ids": unpriced_ids,
                "total_spend": total_spend,
                "paid_spend": paid_spend,
                "fully_loaded_owned_spend": fully_loaded_owned_spend,
                "campaign_cost_spend": campaign_cost_spend,
                "non_costed_activity_present": bool(non_costed_ids),
                "fh_gsa": fh_gsa,
                "fh_signups": fh_signups,
                "fh_net_billthrough": fh_net_billthrough,
                "incremental_fh_gsa": incremental_fh_gsa,
                "incremental_fh_signups": incremental_fh_signups,
                "incremental_fh_net_billthrough": incremental_fh_nbt,
                "incremental_dna_kits": incremental_dna_kits,
                "dna_kits": dna_kits,
                "avg_cpa": avg_cpa,
                "cost_per_fh_gsa": avg_cpa,
                # `whole_plan_*` (PR E.2 #8) - the explicit-spend-scope name:
                # this divides *total scenario spend across every channel* by
                # a KPI total, so it is a whole-plan efficiency number, never
                # a channel-specific one (see core.media_units.CPA_SPEND_SCOPES/
                # cpa_scope_metadata). The bare avg_cpa/cost_per_fh_gsa names
                # are kept as legacy aliases.
                "whole_plan_cost_per_fh_gsa": avg_cpa,
                "fh_signup_avg_cpa": fh_signup_avg_cpa,
                "cost_per_fh_signup": fh_signup_avg_cpa,
                "whole_plan_cost_per_fh_signup": fh_signup_avg_cpa,
                "whole_plan_cost_per_fh_net_billthrough": nbt_avg_cpa,
                "whole_plan_incremental_nbt_cpa": nbt_avg_cpa,
                "paid_media_incremental_cpa": paid_media_incremental_cpa,
                "paid_media_incremental_nbt_cpa": (
                    paid_media_incremental_nbt_cpa
                ),
                "dna_avg_cpa": dna_avg_cpa,
                "cost_per_dna_kit": dna_avg_cpa,
                "whole_plan_cost_per_dna_kit": dna_avg_cpa,
                "total_value": total_value,
                "incremental_total_value": incremental_total_value,
                "whole_plan_incremental_roi": whole_plan_incremental_roi,
                "paid_media_incremental_roi": paid_media_incremental_roi,
                "economics_availability_status": period_coverage[
                    "economics_status"
                ],
                "economics_coverage": period_coverage,
                "activity_definitions_fingerprint": activity_fingerprint,
                "scenario_plan_fingerprint": (
                    scenario_plan.fingerprint()
                    if scenario_plan is not None
                    else None
                ),
                "planning_objective": (
                    planning_objective.to_dict()
                    if planning_objective is not None
                    else None
                ),
                "total_value_is_complete": total_value_is_complete,
            })
    return pd.DataFrame(rows)


def _validate_no_mixed_currency_value_weights(
    priced_outcome_ids: List[str], ltv: Dict[str, float], catalogue_by_id: Dict[str, object],
) -> None:
    """Raise ValueError if `priced_outcome_ids`' value weights would combine
    two different explicit currencies into one `total_value` (PR E.2 - "stop
    calling raw units value" also means never silently blending currencies).
    Outcome_ids with no recorded `value_currency` (blank/legacy catalogue)
    are treated as "no currency asserted" and never trigger this - there is
    nothing to conflict with. No FX conversion is applied or offered here;
    the caller must give `ltv` entries in one common currency."""
    currencies = {
        catalogue_by_id[oid].value_currency
        for oid in priced_outcome_ids
        if oid in catalogue_by_id and catalogue_by_id[oid].value_currency
    }
    if len(currencies) > 1:
        raise ValueError(
            f"Cannot combine value weights (ltv) across different currencies {sorted(currencies)} into "
            "one total_value without an explicit FX conversion - convert value_weight to one common "
            "currency before calling evaluate_scenario, or restrict to outcome_ids sharing a currency."
        )


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

@dataclass
class SpendConstraint:
    kind: str  # "locked_cell" | "channel_total" | "month_total" | "bounded_movement" | "min_spend_floor"
    channel: Optional[str] = None
    month: Optional[str] = None
    months: Optional[List[str]] = None
    value: Optional[float] = None
    max_pct_move: Optional[float] = None
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "channel": self.channel, "month": self.month,
            "months": self.months, "value": self.value,
            "max_pct_move": self.max_pct_move, "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpendConstraint":
        return cls(**d)


def _flatten(spend_plan: Dict[str, Dict[str, float]], months: List[str], channels: List[str]) -> np.ndarray:
    return np.array([spend_plan[m].get(c, 0.0) for m in months for c in channels])


def _unflatten(x: np.ndarray, months: List[str], channels: List[str]) -> Dict[str, Dict[str, float]]:
    n_ch = len(channels)
    return {
        m: {c: float(x[mi * n_ch + ci]) for ci, c in enumerate(channels)}
        for mi, m in enumerate(months)
    }


def _cell_index(month: str, channel: str, months: List[str], channels: List[str]) -> int:
    return months.index(month) * len(channels) + channels.index(channel)


def build_bounds_and_constraints(
    months: List[str],
    channels: List[str],
    current_spend: np.ndarray,
    constraints: List[SpendConstraint],
    default_max_pct_move: Optional[float] = None,
    resource_channels: Optional[List[str]] = None,
) -> Tuple[List[Tuple[float, float]], List[LinearConstraint]]:
    """Translate SpendConstraint objects into scipy bounds + LinearConstraints.

    `resource_channels`, when given, restricts a `month_total` constraint's
    row to only those channels - a `month_total` spans every channel in the
    plan by default, which mixes units (GBP spend, impressions, CRM sends)
    unless scoped to one optimisation resource's eligible channels. `None`
    preserves the legacy behaviour of summing every channel (only valid when
    the caller has no governed activity taxonomy to scope by)."""
    n = len(current_spend)
    lower = np.zeros(n)
    upper = np.full(n, np.inf)

    if default_max_pct_move is not None:
        lower = np.maximum(0, current_spend * (1 - default_max_pct_move))
        upper = current_spend * (1 + default_max_pct_move)

    linear_constraints: List[LinearConstraint] = []

    for c in constraints:
        if c.kind == "locked_cell":
            idx = _cell_index(c.month, c.channel, months, channels)
            val = c.value if c.value is not None else current_spend[idx]
            lower[idx] = upper[idx] = val

        elif c.kind == "bounded_movement":
            pct = c.max_pct_move if c.max_pct_move is not None else default_max_pct_move
            if pct is None:
                continue
            if c.channel and c.month:
                idx = _cell_index(c.month, c.channel, months, channels)
                lower[idx] = max(0, current_spend[idx] * (1 - pct))
                upper[idx] = current_spend[idx] * (1 + pct)
            elif c.channel:
                for m in months:
                    idx = _cell_index(m, c.channel, months, channels)
                    lower[idx] = max(0, current_spend[idx] * (1 - pct))
                    upper[idx] = current_spend[idx] * (1 + pct)
            else:
                lower = np.maximum(0, current_spend * (1 - pct))
                upper = current_spend * (1 + pct)

        elif c.kind == "min_spend_floor":
            months_set = c.months or ([c.month] if c.month else months)
            for m in months_set:
                idx = _cell_index(m, c.channel, months, channels)
                lower[idx] = max(lower[idx], c.value or 0.0)

        elif c.kind == "channel_total":
            row = np.zeros(n)
            for m in months:
                row[_cell_index(m, c.channel, months, channels)] = 1
            target = c.value if c.value is not None else float(
                sum(current_spend[_cell_index(m, c.channel, months, channels)] for m in months)
            )
            linear_constraints.append(LinearConstraint(row, lb=target, ub=target))

        elif c.kind == "month_total":
            target_channels = (
                resource_channels if resource_channels is not None else channels
            )
            row = np.zeros(n)
            for ch in target_channels:
                row[_cell_index(c.month, ch, months, channels)] = 1
            target = c.value if c.value is not None else float(
                sum(current_spend[_cell_index(c.month, ch, months, channels)] for ch in target_channels)
            )
            linear_constraints.append(LinearConstraint(row, lb=target, ub=target))

        else:
            raise ValueError(f"Unknown constraint kind: {c.kind}")

    bounds = list(zip(lower, upper))
    return bounds, linear_constraints


# ---------------------------------------------------------------------------
# Optimiser
# ---------------------------------------------------------------------------

VALID_OBJECTIVES = ("fh_net_billthrough", "fh_gsa", "fh_signups", "dna_kits", "weighted_mix", "expected_value")

_OBJECTIVE_METRIC_KEY = {
    "fh_gsa": METRIC_KEY_FH_GSA,
    "fh_signups": METRIC_KEY_FH_SIGNUP,
    "fh_net_billthrough": METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    "dna_kits": METRIC_KEY_DNA_KIT_SALE,
}


def _validate_target_outcome_ids(
    target_outcome_ids: Optional[List[str]], meta: FHModelMeta, *, metric_key: Optional[str] = None,
) -> None:
    """PR E.2 requirement #9 (harden optimiser target validation): every
    `target_outcome_id` must (a) actually exist in this fit, (b) match the
    requested metric when `metric_key` is given - a caller must not be able
    to pass a sign-up outcome_id into `objective="fh_gsa"` and bypass
    metric-aware selection - and (c) be eligible for optimisation
    (`include_in_optimisation`, which defaults to `False` for a diagnostic-
    role outcome and for a `funnel_intermediate` outcome - PR E.2's
    eligibility defaults - so "reject diagnostic outcomes" and "reject
    outcomes excluded from planning" are both enforced by this one check).
    No-op if `target_outcome_ids` is empty/None - there is nothing to
    validate when a caller relies on the objective's own default selector.
    Legacy fallback: a `FHModelMeta` with no catalogue metadata at all
    (`outcome_id_to_product` empty - a fit that predates
    `outcome_catalogue_at_fit`, or a hand-built test fixture) skips the
    metric-match check, matching every other named selector's legacy
    fallback in `core.outcomes` - there is no metric metadata to check
    against.
    """
    if not target_outcome_ids:
        return
    unknown = sorted(set(target_outcome_ids) - set(meta.outcome_ids))
    if unknown:
        raise ValueError(f"target_outcome_ids contains outcome_id(s) not fitted in this model: {unknown}.")
    has_catalogue_metadata = bool(getattr(meta, "outcome_id_to_product", {}))
    if metric_key is not None and has_catalogue_metadata:
        matching = set(select_outcome_ids(meta, metric_key=metric_key))
        mismatched = sorted(oid for oid in target_outcome_ids if oid not in matching)
        if mismatched:
            raise ValueError(
                f"target_outcome_ids {mismatched} do not match this objective's metric "
                f"({metric_key!r}) - a sign-up outcome cannot be optimised under a mismatched-metric "
                "objective (e.g. 'fh_gsa'), or vice versa."
            )
    optimisable = set(eligible_outcome_ids(meta, list(target_outcome_ids), "include_in_optimisation"))
    excluded = sorted(set(target_outcome_ids) - optimisable)
    if excluded:
        raise ValueError(
            f"target_outcome_ids {excluded} are not eligible for optimisation (diagnostic role, "
            "funnel_intermediate role, or an explicit include_in_optimisation=False) - remove them, or "
            "opt them in explicitly via include_in_optimisation on the OutcomeDefinition."
        )


def _objective_weight(
    objective: str,
    meta: FHModelMeta,
    ltv: Optional[Dict[str, float]],
    target_outcome_ids: Optional[List[str]],
    weights: Optional[Dict[str, float]],
    *,
    assume_value_scaled_weights: bool = False,
) -> Dict[str, float]:
    """
    Per-outcome_id weight for the optimiser's scalar objective - the
    instruction document's "optimisation objectives must be explicit" /
    "block generic raw-volume optimisation when mixed metric types are
    present" requirement. `objective` must be one of VALID_OBJECTIVES:
    there is no "maximise everything, whatever unit it's in" option, and an
    outcome_id outside the objective's scope gets weight 0 (excluded), never
    an implicit 1 (silently counted as if it were the same unit as
    everything else - the confirmed defect this replaces: `"fh_gsa"` used to
    mean "every outcome_id that isn't a DNA-kit outcome", which would
    silently fold a Family History sign-up outcome into a GSA objective).

    Every branch validates any explicit `target_outcome_ids` via
    `_validate_target_outcome_ids` (PR E.2 #9) - unknown outcome_ids,
    metric mismatches, and outcomes excluded from optimisation (diagnostic
    role or `include_in_optimisation=False`) are all rejected before the
    (potentially slow) optimisation runs, not discovered afterwards.

    - `"fh_gsa"`: Family History GSA outcomes - `core.outcomes.fh_gsa_outcome_ids`
      (metric_key=fh_gsa), or just `target_outcome_ids` if given (e.g. a
      single FH outcome - "maximise FH New GSA").
    - `"fh_signups"`: Family History sign-up outcomes -
      `core.outcomes.fh_signup_outcome_ids` (metric_key=fh_signup), or just
      `target_outcome_ids` if given. Raises if the model has none - distinct
      from `"fh_gsa"` even when both share a segment.
    - `"dna_kits"`: DNA kit sales - `core.outcomes.dna_kit_sale_outcome_ids`,
      or just `target_outcome_ids` if given. Raises if the model has none.
    - `"weighted_mix"`: an analyst-supplied per-outcome_id `weights` dict -
      required explicitly; there is no default mix to fall back to. Every
      weight must be finite and non-negative. If the weighted outcome_ids
      span more than one raw `unit` (e.g. "GSA" and "sign-up"), this raises
      unless `assume_value_scaled_weights=True` is passed explicitly - the
      instruction document's "reject weighted mixes across different units
      unless weights explicitly convert to a common business-value scale"
      requirement; there is no way to infer that intent from the numbers
      alone, so it must be asserted explicitly by the caller.
    - `"expected_value"`: LTV-weighted total value across every eligible
      (`include_in_value` AND `include_in_optimisation`, or just
      `target_outcome_ids` if given) outcome_id - requires `ltv` to have a
      finite, non-negative entry for every one of them. Fails closed
      (raises) rather than silently treating a missing weight as 0 or 1 -
      the confirmed "missing value_weight defaults to 1.0" defect this
      replaces. Also raises if the priced outcome_ids don't share one
      explicit currency (`OutcomeDefinition.value_currency`) - see
      `evaluate_scenario`'s docstring for the same rule.
    """
    if objective not in VALID_OBJECTIVES:
        raise ValueError(
            f"objective must be one of {VALID_OBJECTIVES}, got {objective!r}. Generic unlabelled "
            "volume optimisation is not supported here - it would silently combine Family History "
            "GSAs, sign-ups and DNA kit sales into one meaningless total."
        )
    if objective in _OBJECTIVE_METRIC_KEY:
        metric_key = _OBJECTIVE_METRIC_KEY[objective]
        _validate_target_outcome_ids(target_outcome_ids, meta, metric_key=metric_key)
        default_selector = {
            "fh_gsa": fh_gsa_outcome_ids, "fh_signups": fh_signup_outcome_ids,
            "fh_net_billthrough": fh_net_billthrough_outcome_ids, "dna_kits": dna_kit_sale_outcome_ids,
        }[objective]
        eligible = set(target_outcome_ids) if target_outcome_ids else set(default_selector(meta))
        if objective != "fh_gsa" and not eligible:
            noun = {"fh_signups": "Family History sign-up", "fh_net_billthrough": "Family History net bill-through", "dna_kits": "DNA-kit"}[objective]
            raise ValueError(f"objective={objective!r} but this model has no {noun} outcomes.")
        return {s: 1.0 for s in eligible}
    if objective == "weighted_mix":
        if not weights:
            raise ValueError("objective='weighted_mix' requires an explicit weights={outcome_id: weight} dict - there is no default mix.")
        _validate_target_outcome_ids(list(weights), meta)
        invalid = sorted(
            oid for oid, w in weights.items()
            if not (isinstance(w, (int, float)) and np.isfinite(w) and w >= 0)
        )
        if invalid:
            raise ValueError(f"weighted_mix weights must be finite and non-negative; invalid for: {invalid}.")
        units = {meta.outcome_id_to_unit.get(oid) for oid in weights}
        units.discard(None)
        if len(units) > 1 and not assume_value_scaled_weights:
            raise ValueError(
                f"weighted_mix combines outcome_ids with different units ({sorted(units)}) - raw counts "
                "in different units cannot be added together. Pass assume_value_scaled_weights=True only "
                "if these weights already convert every outcome_id onto one common business-value scale "
                "(e.g. LTV-weighted), not raw unit counts."
            )
        return weights
    # objective == "expected_value"
    if not ltv:
        raise ValueError("objective='expected_value' requires ltv={outcome_id: value} - it is the LTV-weighted total across every outcome_id.")
    if target_outcome_ids:
        _validate_target_outcome_ids(target_outcome_ids, meta)
        eligible = set(target_outcome_ids)
    else:
        all_ids = list(meta.outcome_ids)
        value_eligible = set(eligible_outcome_ids(meta, all_ids, "include_in_value"))
        optimisation_eligible = set(eligible_outcome_ids(meta, all_ids, "include_in_optimisation"))
        eligible = value_eligible & optimisation_eligible
    missing = sorted(oid for oid in eligible if oid not in ltv)
    if missing:
        raise ValueError(
            f"objective='expected_value' requires a value weight for every eligible outcome_id, but "
            f"{missing} have none in ltv - a missing weight must never be silently treated as 0 or 1. "
            "Provide ltv entries for all of them, or pass target_outcome_ids to restrict the objective."
        )
    invalid = sorted(oid for oid in eligible if not (isinstance(ltv[oid], (int, float)) and np.isfinite(ltv[oid]) and ltv[oid] >= 0))
    if invalid:
        raise ValueError(
            f"objective='expected_value' requires finite, non-negative value weights; invalid for: {invalid}."
        )
    catalogue_by_id = outcome_catalogue_at_fit_by_id(meta)
    _validate_no_mixed_currency_value_weights(sorted(eligible), ltv, catalogue_by_id)
    return {oid: ltv[oid] for oid in eligible}


def _objective_factory(
    months: List[str], channels: List[str], market: str,
    meta: FHModelMeta, params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]], objective: str,
    model_type: str = "shared",
    target_outcome_ids: Optional[List[str]] = None,
    weights: Optional[Dict[str, float]] = None,
    assume_value_scaled_weights: bool = False,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_month: Optional[Dict[str, str]] = None,
    planning_objective: Optional[PlanningObjective] = None,
    counterfactual_media_input_by_month: Optional[
        Dict[str, Dict[str, float]]
    ] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
):
    if planning_objective is not None:
        metric_objectives = {
            METRIC_KEY_FH_GSA: "fh_gsa",
            METRIC_KEY_FH_SIGNUP: "fh_signups",
            METRIC_KEY_FH_NET_BILLTHROUGH_COUNT: "fh_net_billthrough",
            METRIC_KEY_DNA_KIT_SALE: "dna_kits",
        }
        objective = (
            "expected_value"
            if planning_objective.estimand == "incremental_value"
            else metric_objectives.get(
                planning_objective.metric_key,
                objective,
            )
        )
        target_outcome_ids = list(planning_objective.target_outcome_ids) or None
    weight = _objective_weight(
        objective, meta, ltv, target_outcome_ids, weights,
        assume_value_scaled_weights=assume_value_scaled_weights,
    )
    response_fn = _steady_state_response_fn(model_type)
    policy = counterfactual_policy or CounterfactualPolicy()
    activity_map = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions is not None
        else {}
    )

    def neg_total(x: np.ndarray) -> float:
        spend_plan = _unflatten(x, months, channels)
        if cost_mapping_registry is not None and activity_definitions is not None:
            monetary: dict[str, dict[str, float]] = {}
            quantities: dict[str, dict[str, float]] = {}
            for period, values in spend_plan.items():
                monetary[period] = {}
                quantities[period] = {}
                for column, value in values.items():
                    definition = activity_map[column]
                    target = monetary if definition.is_cost_bearing else quantities
                    target[period][definition.activity_id] = value
            typed_plan = ScenarioPlan(monetary, quantities)
            model_input_plan, _, _ = resolve_scenario_plan(
                typed_plan,
                market=market,
                activity_definitions=activity_definitions,
                cost_mapping_registry=cost_mapping_registry,
                cost_context_id=cost_context_id or "default",
                cost_as_of_by_period=cost_as_of_by_month,
            )
        else:
            model_input_plan = (
                monetary_plan_to_media_input(
                    spend_plan,
                    market=market,
                    registry=cost_mapping_registry,
                    cost_context_id=cost_context_id or "default",
                    as_of_by_period=cost_as_of_by_month or {},
                )
                if cost_mapping_registry is not None
                else spend_plan
            )
        resolved_counterfactual = (
            counterfactual_media_input_by_month
            if counterfactual_media_input_by_month is not None
            else resolve_counterfactual(
                model_input_plan,
                market=market,
                activity_definitions=activity_definitions,
                policy=policy,
            )
        )
        total = 0.0
        for m in months:
            ref = reference_context_by_month.get(m, {})
            rates = response_fn(
                market,
                model_input_plan[m],
                meta,
                params,
                ref,
                planning_only=True,
            )
            if (
                planning_objective is not None
                and planning_objective.estimand != "total_outcome"
            ):
                counterfactual = (
                    resolved_counterfactual[m]
                )
                counterfactual_rates = response_fn(
                    market,
                    counterfactual,
                    meta,
                    params,
                    ref,
                    planning_only=True,
                )
                rates = {
                    outcome_id: rate - counterfactual_rates[outcome_id]
                    for outcome_id, rate in rates.items()
                }
            for oid, rate in rates.items():
                total += rate * WEEKS_PER_MONTH * weight.get(oid, 0.0)
        return -total

    return neg_total


def optimize_scenario(
    current_spend_plan: Dict[str, Dict[str, float]],
    months: List[str],
    channels: List[str],
    market: str,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    objective: Optional[str] = None,
    constraints: Optional[List[SpendConstraint]] = None,
    conserve_total_budget: bool = True,
    max_iter: int = 200,
    *,
    model_type: str = "shared",
    target_outcome_ids: Optional[List[str]] = None,
    weights: Optional[Dict[str, float]] = None,
    assume_value_scaled_weights: bool = False,
    approval: ModelApproval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_month: Optional[Dict[str, str]] = None,
    planning_objective: Optional[PlanningObjective] = None,
    counterfactual_media_input_by_month: Optional[
        Dict[str, Dict[str, float]]
    ] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
    posterior_trace: Optional[Any] = None,
    posterior_evaluation_draws: int = 100,
    optimization_resource: Optional[OptimizationResource] = None,
) -> Dict:
    """
    Optimise a spend plan. `constraints=None` (or empty) + conserve_total_budget=True
    is the "unconstrained benchmark" mode: reallocate the same total budget
    freely, ignoring locks/floors/bounded-movement - a theoretical-optimum
    comparison point, not a recommended plan. Pass `constraints` for the
    constrained-planning mode analysts will actually use.

    `objective` must be one of `VALID_OBJECTIVES` - see `_objective_weight`'s
    docstring for what each one maximises and what `target_outcome_ids`/
    `weights` do. There is deliberately no generic "maximise volume"
    objective (the instruction document's audit-confirmed defect this
    replaces): every objective states exactly what it sums, and an
    outcome_id outside its scope contributes 0, never an implicit 1.

    `model_type` selects which model's steady-state response function drives
    optimisation and evaluation - `"shared"` (Model A, default) or
    `"market_specific"` (Model C) - see module docstring.

    Raises ApprovalMismatchError unless `approval` matches the current model
    run identity - checked up front, before running the (potentially slow)
    SLSQP optimisation, not just when the final predicted outcomes are
    computed via evaluate_scenario below. Raises ValueError up front too if
    `objective` (plus `target_outcome_ids`/`weights`/`ltv`) isn't resolvable -
    same "fail before the slow optimisation runs" reasoning.
    """
    require_matching_approval(
        approval,
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    )
    constraints = constraints or []
    policy = counterfactual_policy or CounterfactualPolicy()
    if objective is None and planning_objective is None:
        planning_objective = PlanningObjective(
            metric_key=(
                METRIC_KEY_FH_NET_BILLTHROUGH_COUNT
                if fh_net_billthrough_outcome_ids(meta)
                else METRIC_KEY_FH_GSA
            ),
            counterfactual_policy_fingerprint=policy.fingerprint(),
        )
    elif objective is not None and planning_objective is None:
        warnings.warn(
            "String objectives are deprecated and are migrated to an "
            "incremental PlanningObjective; official workflows must persist "
            "the typed objective.",
            DeprecationWarning,
            stacklevel=2,
        )
        planning_objective = planning_objective_from_legacy(
            objective,
            counterfactual_policy_fingerprint=policy.fingerprint(),
        )
        if target_outcome_ids:
            planning_objective = replace(
                planning_objective,
                target_outcome_ids=tuple(target_outcome_ids),
            )
    legacy_objective = objective or "fh_net_billthrough"
    current_spend = _flatten(current_spend_plan, months, channels)

    activity_map = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions is not None
        else {}
    )
    resource: Optional[OptimizationResource] = None
    resource_channels: Optional[List[str]] = None
    if activity_definitions is not None:
        missing_activity = set(channels) - set(activity_map)
        if missing_activity:
            raise ValueError(
                f"Missing activity definitions for {sorted(missing_activity)}"
            )
        resource = optimization_resource or monetary_optimization_resource(
            activity_definitions, market,
            cost_mapping_registry=cost_mapping_registry,
            cost_context_id=cost_context_id or "default",
            cost_as_of=(
                (cost_as_of_by_month or {}).get(months[0]) if months else None
            ),
        )
        resource_channels = [
            channel
            for channel in channels
            if activity_map[channel].activity_id in resource.eligible_activity_ids
        ]

    bounds, linear_constraints = build_bounds_and_constraints(
        months, channels, current_spend, constraints,
        resource_channels=resource_channels,
    )

    if activity_definitions is not None:
        # Every channel outside this optimisation resource - not just the
        # ones explicitly marked non-optimisable - is held fixed for this
        # run. A response-only/quantity activity marked "optimisable" for
        # scenario purposes is still not denominated in this resource's
        # unit, so it must never be traded against it (PR G2A.6 workstream A).
        for month in months:
            for channel in channels:
                definition = activity_map[channel]
                eligible = (
                    definition.activity_id in resource.eligible_activity_ids
                    and definition.planning_eligibility == "optimisable"
                )
                if not eligible:
                    index = _cell_index(month, channel, months, channels)
                    value = float(current_spend[index])
                    bounds[index] = (value, value)

    if conserve_total_budget:
        if resource is not None:
            eligible_indices = [
                _cell_index(month, channel, months, channels)
                for month in months
                for channel in resource_channels
            ]
            if eligible_indices:
                total_row = np.zeros(len(current_spend))
                total_row[eligible_indices] = 1
                target = float(current_spend[eligible_indices].sum())
                linear_constraints.append(
                    LinearConstraint(total_row, lb=target, ub=target)
                )
        else:
            total_row = np.ones(len(current_spend))
            linear_constraints.append(LinearConstraint(total_row, lb=current_spend.sum(), ub=current_spend.sum()))

    objective_fn = _objective_factory(
        months, channels, market, meta, params, reference_context_by_month, ltv, legacy_objective, model_type,
        target_outcome_ids=target_outcome_ids, weights=weights,
        assume_value_scaled_weights=assume_value_scaled_weights,
        cost_mapping_registry=cost_mapping_registry,
        cost_context_id=cost_context_id,
        cost_as_of_by_month=cost_as_of_by_month,
        planning_objective=planning_objective,
        counterfactual_media_input_by_month=counterfactual_media_input_by_month,
        activity_definitions=activity_definitions,
        counterfactual_policy=policy,
    )

    result = minimize(
        objective_fn,
        current_spend,
        method="SLSQP",
        bounds=bounds,
        constraints=linear_constraints,
        options={"maxiter": max_iter, "ftol": 1e-8},
    )

    optimized_plan = _unflatten(np.clip(result.x, 0, None), months, channels)
    identity_kwargs = dict(
        model_type=model_type, approval=approval, model_run_id=model_run_id, data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint, posterior_fingerprint=posterior_fingerprint,
        cost_mapping_registry=cost_mapping_registry,
        cost_context_id=cost_context_id,
        cost_as_of_by_month=cost_as_of_by_month,
        planning_objective=planning_objective,
        counterfactual_media_input_by_month=counterfactual_media_input_by_month,
        activity_definitions=activity_definitions,
        counterfactual_policy=policy,
    )
    optimized_scenario_plan = (
        classify_activity_plan(
            optimized_plan,
            market=market,
            activity_definitions=activity_definitions,
        )
        if activity_definitions is not None
        else None
    )
    current_scenario_plan = (
        classify_activity_plan(
            current_spend_plan,
            market=market,
            activity_definitions=activity_definitions,
        )
        if activity_definitions is not None
        else None
    )
    predicted = evaluate_scenario(
        optimized_plan,
        market,
        meta,
        params,
        reference_context_by_month,
        ltv,
        scenario_plan=optimized_scenario_plan,
        **identity_kwargs,
    )
    current_predicted = evaluate_scenario(
        current_spend_plan,
        market,
        meta,
        params,
        reference_context_by_month,
        ltv,
        scenario_plan=current_scenario_plan,
        **identity_kwargs,
    )

    # Evaluated via the same objective_fn used for optimisation (not
    # re-derived from the predicted DataFrames) so "current" and "optimised"
    # totals are guaranteed to use the identical weighting - no risk of the
    # two diverging from a second, hand-written copy of the eligibility logic.
    current_objective_value = -float(objective_fn(current_spend))
    posterior_evaluation = None
    if posterior_trace is not None:
        from .uncertainty import evaluate_scenario_with_uncertainty

        posterior_evaluation = evaluate_scenario_with_uncertainty(
            optimized_plan,
            market,
            meta,
            posterior_trace,
            reference_context_by_month,
            ltv,
            model_type=model_type,
            n_draws=posterior_evaluation_draws,
            approval=approval,
            model_run_id=model_run_id,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            baseline_spend_plan=current_spend_plan,
            scenario_plan=optimized_scenario_plan,
            baseline_scenario_plan=current_scenario_plan,
            activity_definitions=activity_definitions,
            counterfactual_policy=policy,
            planning_objective=planning_objective,
            cost_mapping_registry=cost_mapping_registry,
            cost_context_id=cost_context_id,
            cost_as_of_by_month=cost_as_of_by_month,
        )

    return {
        "success": bool(result.success),
        "message": str(result.message),
        "spend_plan": optimized_plan,
        "scenario_plan": (
            optimized_scenario_plan.to_dict()
            if optimized_scenario_plan is not None
            else ScenarioPlan.from_legacy_spend_plan(
                optimized_plan
            ).to_dict()
        ),
        "predicted": predicted,
        "current_predicted": current_predicted,
        "objective_value": -float(result.fun),
        "current_objective_value": current_objective_value,
        "posterior_evaluation": posterior_evaluation,
        "cost_mapping_fingerprint": (
            cost_mapping_registry.fingerprint()
            if cost_mapping_registry is not None
            else None
        ),
        "planning_objective": (
            planning_objective.to_dict()
            if planning_objective is not None
            else {
                "estimand": "total_outcome",
                "legacy_objective": legacy_objective,
            }
        ),
        "counterfactual_policy": policy.to_dict(),
        "counterfactual_policy_fingerprint": policy.fingerprint(),
        "optimization_resource": resource.to_dict() if resource is not None else None,
        "activity_definitions_fingerprint": (
            activity_definitions_fingerprint(activity_definitions)
            if activity_definitions is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Scenario save/reload
# ---------------------------------------------------------------------------

def scenario_to_dict(
    name: str, market: str, spend_plan: Dict[str, Dict[str, float]],
    objective: str, constraints: List[SpendConstraint], notes: str = "",
    cost_mapping_fingerprint: Optional[str] = None,
    planning_objective: Optional[PlanningObjective | Dict[str, object]] = None,
    activity_definitions_fingerprint: Optional[str] = None,
    scenario_plan: Optional[ScenarioPlan] = None,
    counterfactual_policy: Optional[
        CounterfactualPolicy | Dict[str, object]
    ] = None,
    economics_coverage: Optional[Dict[str, object]] = None,
) -> dict:
    objective_payload = (
        planning_objective.to_dict()
        if isinstance(planning_objective, PlanningObjective)
        else planning_objective
    )
    policy_payload = (
        counterfactual_policy.to_dict()
        if isinstance(counterfactual_policy, CounterfactualPolicy)
        else counterfactual_policy
    )
    typed_plan = scenario_plan or ScenarioPlan.from_legacy_spend_plan(spend_plan)
    return {
        "name": name, "market": market, "spend_plan": spend_plan,
        "scenario_plan": typed_plan.to_dict(),
        "objective": objective, "constraints": [c.to_dict() for c in constraints], "notes": notes,
        "cost_mapping_fingerprint": cost_mapping_fingerprint,
        "planning_objective": objective_payload,
        "activity_definitions_fingerprint": activity_definitions_fingerprint,
        "counterfactual_policy": policy_payload,
        "counterfactual_policy_fingerprint": (
            CounterfactualPolicy.from_dict(policy_payload).fingerprint()
            if policy_payload
            else None
        ),
        "economics_coverage": economics_coverage,
        "schema_version": 2,
    }


def scenario_from_dict(d: dict) -> dict:
    d = dict(d)
    if "scenario_plan" not in d:
        d["scenario_plan"] = ScenarioPlan.from_legacy_spend_plan(
            d.get("spend_plan", {})
        ).to_dict()
        d["schema_version"] = 2
    if not d.get("planning_objective") and d.get("objective"):
        d["planning_objective"] = planning_objective_from_legacy(
            d["objective"]
        ).to_dict()
    d["constraints"] = [SpendConstraint.from_dict(c) for c in d.get("constraints", [])]
    return d


def require_current_cost_mapping(
    artifact: Dict, current_cost_mapping_fingerprint: str
) -> None:
    """Reject scenarios/curve metadata created under another cost mapping."""
    saved = artifact.get("cost_mapping_fingerprint")
    if not saved or saved != current_cost_mapping_fingerprint:
        raise ValueError(
            "Artifact is stale because its governed cost mapping changed"
        )


def compare_scenarios(scenarios: List[Dict], predicted_key: str = "predicted") -> pd.DataFrame:
    """
    Compare total predicted value/volume and spend across saved scenarios.

    `total_value` sums `pred["value"]` skipping any row with no value weight
    (`value is None` - see evaluate_scenario's docstring), `min_count=1` so
    a scenario with `value_status="not configured"` for every row (raw
    units, PR E.2) yields `NaN` here, never a misleading `0.0` -
    `total_value_is_complete` is `False` if any scenario-month had an
    incomplete-coverage row (including "not configured" entirely), so a
    caller can flag the total as a partial/absent sum rather than
    presenting it as exact. `total_gsa` would sum Family History outcomes,
    sign-ups and DNA
    kit sales into one meaningless count if combined - split into
    `total_fh_gsa`/`total_fh_signups`/`total_dna_kits` instead (never
    combined), same metric-aware discipline as
    core.optimization.evaluate_scenario. `fh_gsa`/`fh_signups`/`dna_kits` are
    month-level totals *duplicated* across every outcome_id row within a
    month (see evaluate_scenario's docstring), so they're deduplicated by
    month before summing across a scenario's months - directly summing them
    across every row would overcount by the number of outcome_ids in each
    month.
    """
    rows = []
    for s in scenarios:
        pred = s[predicted_key]
        total_spend = sum(sum(ch.values()) for ch in s["spend_plan"].values())
        has_product_split = "fh_gsa" in pred.columns and "dna_kits" in pred.columns
        if has_product_split:
            dedup_cols = ["fh_gsa", "dna_kits"] + (["fh_signups"] if "fh_signups" in pred.columns else [])
            by_month = pred.groupby("month")[dedup_cols].first()
            total_fh_gsa = float(by_month["fh_gsa"].sum())
            total_fh_signups = float(by_month["fh_signups"].sum()) if "fh_signups" in dedup_cols else 0.0
            total_dna_kits = float(by_month["dna_kits"].sum())
        else:
            total_fh_gsa = float(pred["predicted_outcome"].sum())
            total_fh_signups = 0.0
            total_dna_kits = 0.0
        total_value_is_complete = (
            bool(pred["total_value_is_complete"].all()) if "total_value_is_complete" in pred else True
        )
        rows.append({
            "scenario": s["name"],
            "market": s.get("market"),
            "total_spend": total_spend,
            "total_value": pred["value"].sum(min_count=1) if "value" in pred else np.nan,
            "total_value_is_complete": total_value_is_complete,
            "total_fh_gsa": total_fh_gsa,
            "total_fh_signups": total_fh_signups,
            "total_dna_kits": total_dna_kits,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Generic single-KPI helpers, kept for reuse
# ---------------------------------------------------------------------------

def calculate_marginal_roi_loglog(
    current_spend: float,
    elasticity: float,
    avg_sales: float,
    avg_spend: float,
) -> float:
    if current_spend <= 0:
        return 0
    return elasticity * (avg_sales / current_spend)


def optimize_budget_marginal_roi(
    total_budget: float,
    channels: List[str],
    elasticities: Dict[str, float],
    current_spend: Dict[str, float],
    avg_sales: float,
    constraints: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, float]:
    n_channels = len(channels)
    constraints = constraints or {}
    default_min, default_max = 0.05, 0.80

    min_bounds, max_bounds = [], []
    for ch in channels:
        min_pct, max_pct = constraints.get(ch, (default_min, default_max))
        min_bounds.append(min_pct * total_budget)
        max_bounds.append(max_pct * total_budget)

    def objective(x):
        total_effect = 0
        for i, ch in enumerate(channels):
            if x[i] > 0:
                total_effect += elasticities[ch] * np.log(x[i])
        return -total_effect

    def gradient(x):
        grad = np.zeros(n_channels)
        for i, ch in enumerate(channels):
            if x[i] > 0:
                grad[i] = -elasticities[ch] / x[i]
        return grad

    bounds = list(zip(min_bounds, max_bounds))
    total_current = sum(current_spend.values())
    if total_current > 0:
        x0 = np.array([
            current_spend.get(ch, total_budget / n_channels) / total_current * total_budget
            for ch in channels
        ])
    else:
        x0 = np.full(n_channels, total_budget / n_channels)
    x0 = np.clip(x0, min_bounds, max_bounds)
    x0 = x0 / x0.sum() * total_budget

    result = minimize(
        objective, x0, method='SLSQP', jac=gradient, bounds=bounds,
        constraints={'type': 'eq', 'fun': lambda x: x.sum() - total_budget},
        options={'maxiter': 1000, 'ftol': 1e-10},
    )

    optimal_spend = {ch: max(0, result.x[i]) for i, ch in enumerate(channels)}
    total_allocated = sum(optimal_spend.values())
    if total_allocated > 0:
        for ch in channels:
            optimal_spend[ch] = optimal_spend[ch] / total_allocated * total_budget
    return optimal_spend


def calculate_expected_lift(
    current_spend: Dict[str, float],
    optimal_spend: Dict[str, float],
    elasticities: Dict[str, float],
    current_sales: float,
) -> Dict[str, float]:
    total_pct_change = 0
    for channel in elasticities:
        curr = current_spend.get(channel, 0)
        opt = optimal_spend.get(channel, 0)
        if curr > 0:
            pct_change_spend = (opt - curr) / curr
            total_pct_change += elasticities[channel] * pct_change_spend

    expected_sales = current_sales * (1 + total_pct_change)
    return {
        'current_sales': current_sales,
        'expected_sales': expected_sales,
        'lift': expected_sales - current_sales,
        'lift_pct': total_pct_change * 100,
    }
