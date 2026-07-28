"""
Planning and optimisation package.

PR 51A: Canonical source of planning value objects.
``core.optimization`` imports from this module and re-exports for backward
compatibility.

Domain layout:
- ``value.py``: Pure value objects and dataclasses (canonical definitions)
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
    planning_objective_from_legacy,
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
    "planning_objective_from_legacy",
    "validation_context_from_legacy_args",
]
