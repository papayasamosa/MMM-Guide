"""
Planning and optimisation package (refactored from core/optimization.py).

PR 5: Reduces the risk created by the monolithic ``core/optimization.py``
without changing numerical behaviour.

Domain layout:
- ``value.py``: Pure value objects and dataclasses (ResolvedOutcomeAuthorisation,
  ResolvedPlanningGovernance, ScenarioGovernanceDependencies,
  ScenarioEvaluationResult, OutcomeValueMapping, CurrencyContext,
  ScenarioValidationContext, PlanningObjective, ScenarioDependencyIssue)
- ``governance.py``: Planning governance logic (moved later)
- ``objectives.py``: Planning objectives (moved later)
- ``constraints.py``: Spend constraints (moved later)
- ``resources.py``: Optimization resources (moved later)
- ``evaluation.py``: Scenario evaluation (moved later)
- ``solver.py``: Optimisation solver (moved later)
- ``serialization.py``: Serialization helpers (future)
- ``comparison.py``: Scenario comparison utilities (future)
"""

from __future__ import annotations

# Pure value objects (PR 5, step 1)
from .value import (
    CurrencyContext,
    OutcomeValueMapping,
    PlanningObjective,
    ResolvedOutcomeAuthorisation,
    ResolvedPlanningGovernance,
    ScenarioDependencyIssue,
    ScenarioEvaluationResult,
    ScenarioGovernanceDependencies,
    ScenarioValidationContext,
    legacy_segment_ltv_to_value_mapping,
    validation_context_from_legacy_args,
)

__all__ = [
    "CurrencyContext",
    "OutcomeValueMapping",
    "PlanningObjective",
    "ResolvedOutcomeAuthorisation",
    "ResolvedPlanningGovernance",
    "ScenarioDependencyIssue",
    "ScenarioEvaluationResult",
    "ScenarioGovernanceDependencies",
    "ScenarioValidationContext",
    "legacy_segment_ltv_to_value_mapping",
    "validation_context_from_legacy_args",
]
