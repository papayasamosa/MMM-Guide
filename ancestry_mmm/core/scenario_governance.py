"""Typed scenario inputs, counterfactual resolution, and economics coverage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from .activities import (
    COST_BEARING_TREATMENTS,
    ActivityDefinition,
    activity_by_model_input,
)
from .media_costs import CostMappingRegistry

COUNTERFACTUAL_RULES = {"zero", "hold_plan", "explicit", "require_explicit"}


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CounterfactualPolicy:
    policy_id: str = "paid_decisions_zero_fixed_held"
    decision_activity_rule: str = "zero"
    fixed_activity_rule: str = "hold_plan"
    demand_capture_rule: str = "require_explicit"
    mediator_rule: str = "hold_plan"
    control_rule: str = "hold_plan"
    event_rule: str = "hold_plan"
    explicit_values_by_period: Mapping[str, Mapping[str, float]] | None = None
    rationale: str = (
        "Zero optimisable interventions; hold fixed, scenario-only, mediator, "
        "control, and event activity at the candidate-plan level."
    )
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in (
            "decision_activity_rule",
            "fixed_activity_rule",
            "demand_capture_rule",
            "mediator_rule",
            "control_rule",
            "event_rule",
        ):
            if getattr(self, field) not in COUNTERFACTUAL_RULES:
                raise ValueError(f"invalid counterfactual rule in {field}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> CounterfactualPolicy:
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in values.items() if key in known})

    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True)
class ScenarioPlan:
    """Separate cost-bearing decisions from non-costed activity quantities."""

    monetary_decisions_by_period: Mapping[str, Mapping[str, float]]
    activity_quantity_assumptions_by_period: Mapping[str, Mapping[str, float]]
    activity_units: Mapping[str, str] | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        overlap = {
            (period, activity_id)
            for period, decisions in self.monetary_decisions_by_period.items()
            for activity_id in decisions
            if activity_id
            in self.activity_quantity_assumptions_by_period.get(period, {})
        }
        if overlap:
            raise ValueError(
                "an activity cannot be both a monetary decision and a direct "
                f"quantity assumption in the same period: {sorted(overlap)}"
            )
        for plans in (
            self.monetary_decisions_by_period,
            self.activity_quantity_assumptions_by_period,
        ):
            for period, values in plans.items():
                if not period:
                    raise ValueError("scenario period cannot be blank")
                if any(float(value) < 0 for value in values.values()):
                    raise ValueError("scenario inputs must be non-negative")

    @property
    def periods(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [
                    *self.monetary_decisions_by_period,
                    *self.activity_quantity_assumptions_by_period,
                ]
            )
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> ScenarioPlan:
        if "spend_plan" in values:
            return cls.from_legacy_spend_plan(values["spend_plan"])
        return cls(
            monetary_decisions_by_period=values.get(
                "monetary_decisions_by_period", {}
            ),
            activity_quantity_assumptions_by_period=values.get(
                "activity_quantity_assumptions_by_period", {}
            ),
            activity_units=values.get("activity_units"),
            schema_version=int(values.get("schema_version", 1)),
        )

    @classmethod
    def from_legacy_spend_plan(
        cls,
        spend_plan: Mapping[str, Mapping[str, float]],
    ) -> ScenarioPlan:
        return cls(
            monetary_decisions_by_period={
                period: dict(values) for period, values in spend_plan.items()
            },
            activity_quantity_assumptions_by_period={},
        )

    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())


def classify_activity_plan(
    values_by_period: Mapping[str, Mapping[str, float]],
    *,
    market: str,
    activity_definitions: list[ActivityDefinition],
) -> ScenarioPlan:
    """Classify a flat UI/optimizer plan without treating quantities as spend."""

    by_input = activity_by_model_input(activity_definitions, market)
    monetary: dict[str, dict[str, float]] = {}
    quantities: dict[str, dict[str, float]] = {}
    for period, values in values_by_period.items():
        monetary[period] = {}
        quantities[period] = {}
        for key, value in values.items():
            if key not in by_input:
                raise ValueError(
                    f"missing activity definition for model input {key!r}"
                )
            target = monetary if by_input[key].is_cost_bearing else quantities
            target[period][key] = float(value)
    return ScenarioPlan(
        monetary_decisions_by_period=monetary,
        activity_quantity_assumptions_by_period=quantities,
        activity_units={
            column: (
                "currency"
                if definition.is_cost_bearing
                else "model_input_quantity"
            )
            for column, definition in by_input.items()
        },
    )


def _activities_by_id(
    definitions: list[ActivityDefinition],
    market: str,
) -> dict[str, ActivityDefinition]:
    result: dict[str, ActivityDefinition] = {}
    for specificity in ("*", market):
        for definition in definitions:
            if definition.market != specificity:
                continue
            result[definition.activity_id] = definition
    return result


def _resolve_activity(
    key: str,
    by_id: Mapping[str, ActivityDefinition],
    by_input: Mapping[str, ActivityDefinition],
) -> ActivityDefinition:
    if key in by_id:
        return by_id[key]
    if key in by_input:
        return by_input[key]
    raise ValueError(f"scenario references unknown activity/model input {key!r}")


def resolve_scenario_plan(
    plan: ScenarioPlan,
    *,
    market: str,
    activity_definitions: list[ActivityDefinition] | None,
    cost_mapping_registry: CostMappingRegistry | None = None,
    cost_context_id: str = "default",
    cost_as_of_by_period: Mapping[str, str] | None = None,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]], dict]:
    """Return model inputs, classified costs, and a structured coverage report."""

    if activity_definitions is None:
        model_input = {
            period: {key: float(value) for key, value in values.items()}
            for period, values in plan.monetary_decisions_by_period.items()
        }
        total = sum(
            float(value)
            for values in plan.monetary_decisions_by_period.values()
            for value in values.values()
        )
        return model_input, {"paid_media_cost": {"total": total}}, {
            "economics_status": "legacy_monetary_assumption",
            "covered_activity_ids": [],
            "uncovered_activity_ids": [],
            "excluded_response_only_activity_ids": [],
            "mapping_ids": [],
            "mapping_effective_dates": [],
            "value_coverage": "evaluated_separately",
            "currency_coverage": "legacy_unspecified",
            "counterfactual_scope": "resolved_separately",
        }

    by_input = activity_by_model_input(activity_definitions, market)
    by_id = _activities_by_id(activity_definitions, market)
    dates = dict(cost_as_of_by_period or {})
    model_input: dict[str, dict[str, float]] = {}
    costs: dict[str, dict[str, float]] = {
        treatment: {} for treatment in COST_BEARING_TREATMENTS
    }
    covered: set[str] = set()
    uncovered: set[str] = set()
    response_only: set[str] = set()
    mapping_ids: set[str] = set()
    mapping_dates: set[str] = set()

    for period in plan.periods:
        model_input[period] = {}
        for key, amount in plan.monetary_decisions_by_period.get(
            period, {}
        ).items():
            definition = _resolve_activity(key, by_id, by_input)
            if not definition.is_cost_bearing:
                raise ValueError(
                    f"{definition.activity_id} is {definition.economic_treatment}; "
                    "enter it under activity_quantity_assumptions_by_period"
                )
            if cost_mapping_registry is None:
                uncovered.add(definition.activity_id)
                continue
            if period not in dates:
                raise ValueError(f"missing cost-mapping date for period {period}")
            mapping = cost_mapping_registry.resolve(
                market,
                definition.channel,
                cost_context_id,
                as_of=dates[period],
            )
            if mapping is None:
                uncovered.add(definition.activity_id)
                continue
            model_input[period][definition.resolved_model_input_column] = float(
                mapping.spend_to_media_input(float(amount))
            )
            costs[definition.economic_treatment][definition.activity_id] = (
                costs[definition.economic_treatment].get(
                    definition.activity_id, 0.0
                )
                + float(amount)
            )
            covered.add(definition.activity_id)
            mapping_ids.add(mapping.mapping_id)
            mapping_dates.add(dates[period])

        for key, quantity in plan.activity_quantity_assumptions_by_period.get(
            period, {}
        ).items():
            definition = _resolve_activity(key, by_id, by_input)
            if definition.is_cost_bearing:
                raise ValueError(
                    f"{definition.activity_id} is cost-bearing; enter it under "
                    "monetary_decisions_by_period"
                )
            model_input[period][definition.resolved_model_input_column] = float(
                quantity
            )
            if definition.economic_treatment == "response_only":
                response_only.add(definition.activity_id)

    if uncovered:
        raise ValueError(
            "monetary planning blocked only for affected activities without "
            f"approved effective mappings: {sorted(uncovered)}"
        )
    status = (
        "mixed_cost_and_response_only"
        if covered and response_only
        else "monetary_economics_available"
        if covered
        else "response_only"
        if response_only
        else "economics_not_applicable"
    )
    coverage = {
        "economics_status": status,
        "covered_activity_ids": sorted(covered),
        "uncovered_activity_ids": sorted(uncovered),
        "excluded_response_only_activity_ids": sorted(response_only),
        "mapping_ids": sorted(mapping_ids),
        "mapping_effective_dates": sorted(mapping_dates),
        "value_coverage": "evaluated_separately",
        "currency_coverage": "mapping_governed" if covered else "not_applicable",
        "counterfactual_scope": "resolved_separately",
    }
    return model_input, costs, coverage


def _resolved_rule(
    definition: ActivityDefinition,
    policy: CounterfactualPolicy,
) -> str:
    if definition.model_role == "demand_capture":
        return policy.demand_capture_rule
    if definition.model_role == "mediator":
        return policy.mediator_rule
    if definition.model_role == "control":
        return policy.control_rule
    if definition.model_role == "event":
        return policy.event_rule
    if definition.planning_eligibility != "optimisable":
        return policy.fixed_activity_rule
    return policy.decision_activity_rule


def resolve_counterfactual(
    model_input_plan: Mapping[str, Mapping[str, float]],
    *,
    market: str,
    activity_definitions: list[ActivityDefinition] | None,
    policy: CounterfactualPolicy,
) -> dict[str, dict[str, float]]:
    """Resolve a policy to an auditable model-input vector for every period."""

    if activity_definitions is None:
        return {
            period: {column: 0.0 for column in values}
            for period, values in model_input_plan.items()
        }
    by_input = activity_by_model_input(activity_definitions, market)
    explicit = policy.explicit_values_by_period or {}
    resolved: dict[str, dict[str, float]] = {}
    for period, values in model_input_plan.items():
        resolved[period] = {}
        for column, plan_value in values.items():
            if column not in by_input:
                raise ValueError(
                    f"missing activity definition for model input {column!r}"
                )
            definition = by_input[column]
            rule = _resolved_rule(definition, policy)
            explicit_period = explicit.get(period, {})
            explicit_value = explicit_period.get(
                definition.activity_id,
                explicit_period.get(column),
            )
            if rule in {"explicit", "require_explicit"}:
                if explicit_value is None:
                    raise ValueError(
                        f"counterfactual policy requires an explicit value for "
                        f"{period}/{definition.activity_id}"
                    )
                value = float(explicit_value)
            elif rule == "hold_plan":
                value = float(plan_value)
            else:
                value = 0.0
            resolved[period][column] = value
    return resolved
