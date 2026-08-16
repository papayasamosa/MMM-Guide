"""
Planning and optimisation package.

PR 51A: Canonical source of planning value objects.
``core.optimization`` imports from this module and re-exports for backward
compatibility.

Domain layout:
- ``value.py``: Pure value objects and dataclasses (canonical definitions)
- ``phasing.py``: Monthly-to-weekly phasing contract (REQ-SCEN-002, WP1)
- ``governance.py``: Planning governance logic (to be moved)
- ``objectives.py``: Planning objectives (to be moved)
- ``constraints.py``: Spend constraints (to be moved)
- ``resources.py``: Optimization resources (to be moved)
- ``evaluation.py``: Scenario evaluation (to be moved)
- ``solver.py``: Optimisation solver (to be moved)
- ``serialization.py``: Serialization helpers (to be moved)
- ``comparison.py``: Scenario comparison utilities (to be moved)
"""

from __future__ import annotations

from .phasing import (
    EXPLICIT_OVERRIDE_METHOD_ID,
    HorizonConfiguration,
    MethodProvenance,
    MonetaryPhasingResult,
    MonthReconciliation,
    PHASING_METHOD_ID,
    PHASING_METHOD_VERSION,
    PhasingReconciliationError,
    WeeklyAllocationResult,
    WeeklyModelInputDerivation,
    canonical_weeks,
    phase_model_input_plan_calendar_day_overlap_v1,
    phase_monetary_plan_calendar_day_overlap_v1,
    phase_monthly_series_calendar_day_overlap_v1,
    phase_monthly_series_explicit_override,
    reconcile_explicit_weekly_schedule,
)
from .value import (
    AdstockState,
    CurrencyContext,
    CURRENT_PLANNING_EVALUATION_SEMANTICS,
    OutcomeValueMapping,
    PLANNING_SEMANTICS_SCHEMA_VERSION,
    PlanningEvaluationSemantics,
    PlanningObjective,
    ResolvedOutcomeAuthorisation,
    ResolvedPlanningGovernance,
    ScenarioDependencyIssue,
    ScenarioEvaluationResult,
    ScenarioGovernanceDependencies,
    ScenarioValidationContext,
    planning_objective_from_legacy,
    validation_context_from_legacy_args,
    zero_carry_in_adstock_state,
)

__all__ = [
    "AdstockState",
    "CurrencyContext",
    "CURRENT_PLANNING_EVALUATION_SEMANTICS",
    "EXPLICIT_OVERRIDE_METHOD_ID",
    "HorizonConfiguration",
    "MethodProvenance",
    "MonetaryPhasingResult",
    "MonthReconciliation",
    "OutcomeValueMapping",
    "PHASING_METHOD_ID",
    "PHASING_METHOD_VERSION",
    "PLANNING_SEMANTICS_SCHEMA_VERSION",
    "PhasingReconciliationError",
    "PlanningEvaluationSemantics",
    "PlanningObjective",
    "ResolvedOutcomeAuthorisation",
    "ResolvedPlanningGovernance",
    "ScenarioDependencyIssue",
    "ScenarioEvaluationResult",
    "ScenarioGovernanceDependencies",
    "ScenarioValidationContext",
    "WeeklyAllocationResult",
    "WeeklyModelInputDerivation",
    "canonical_weeks",
    "phase_model_input_plan_calendar_day_overlap_v1",
    "phase_monetary_plan_calendar_day_overlap_v1",
    "phase_monthly_series_calendar_day_overlap_v1",
    "phase_monthly_series_explicit_override",
    "planning_objective_from_legacy",
    "reconcile_explicit_weekly_schedule",
    "validation_context_from_legacy_args",
    "zero_carry_in_adstock_state",
]
