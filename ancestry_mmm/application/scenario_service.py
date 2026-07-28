"""
Scenario service — orchestrates scenario construction, evaluation, and
governance checks without Streamlit dependencies.

PR 6: Separates scenario orchestration from Streamlit page rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.approval import (
    ModelApproval,
    require_matching_approval,
)
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.scenario_governance import (
    ScenarioPlan,
    CounterfactualPolicy,
)
from ancestry_mmm.core.planning.value import (
    PlanningObjective,
    ResolvedPlanningGovernance,
    ScenarioEvaluationResult,
    ScenarioValidationContext,
)
from ancestry_mmm.core.validation_policy import ApprovalReadiness


@dataclass
class ScenarioInput:
    """Typed input for scenario evaluation."""
    market: str
    spend_plan: pd.DataFrame
    meta: FHModelMeta
    params: FHPosteriorParams
    approval: Optional[ModelApproval] = None
    planning_objective: Optional[PlanningObjective] = None
    governance_mode: str = "exploratory"
    artefact_kind: str = "manual_scenario"
    counterfactual_policy: Optional[CounterfactualPolicy] = None
    approval_readiness: Optional[ApprovalReadiness] = None


@dataclass
class ScenarioServiceResult:
    """Structured scenario evaluation output."""
    evaluation: Optional[ScenarioEvaluationResult] = None
    resolved_governance: Optional[ResolvedPlanningGovernance] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    validation_context: Optional[ScenarioValidationContext] = None


class ScenarioService:
    """Application service for scenario planning and evaluation.

    Usage::

        service = ScenarioService()
        result = service.evaluate(input_data)
        if result.errors:
            # handle errors
    """

    def evaluate(self, sc_input: ScenarioInput) -> ScenarioServiceResult:
        """Evaluate a scenario with full governance validation.

        Does not access Streamlit session state, mutate global state, or
        render any UI.
        """
        errors: List[str] = []
        warnings: List[str] = []

        # Validate required inputs
        if sc_input.spend_plan is None or sc_input.spend_plan.empty:
            errors.append("No spend plan provided.")
            return ScenarioServiceResult(errors=errors)

        if sc_input.params is None:
            errors.append("No posterior params provided.")
            return ScenarioServiceResult(errors=errors)

        # --- Governance resolution ---
        # In official mode, require a matching model approval
        if sc_input.governance_mode == "official":
            if sc_input.approval is None:
                errors.append("Official mode requires a model approval.")
            else:
                try:
                    require_matching_approval(
                        sc_input.approval,
                        model_run_id=sc_input.meta.model_run_id if hasattr(sc_input.meta, "model_run_id") else "",
                        data_fingerprint=sc_input.meta.data_fingerprint if hasattr(sc_input.meta, "data_fingerprint") else "",
                        model_spec_fingerprint=sc_input.meta.model_spec_fingerprint if hasattr(sc_input.meta, "model_spec_fingerprint") else "",
                        posterior_fingerprint=sc_input.meta.posterior_fingerprint if hasattr(sc_input.meta, "posterior_fingerprint") else "",
                        approval_readiness=sc_input.approval_readiness,
                    )
                except Exception as exc:
                    errors.append(f"Approval check failed: {exc}")

        if errors:
            return ScenarioServiceResult(errors=errors)

        # --- Evaluate scenario ---
        try:
            from ancestry_mmm.core.optimization import evaluate_scenario
            evaluation = evaluate_scenario(
                sc_input.spend_plan,
                sc_input.meta,
                sc_input.params,
                market=sc_input.market,
                governance_mode=sc_input.governance_mode,
                planning_objective=sc_input.planning_objective,
                artefact_kind=sc_input.artefact_kind,
                counterfactual_policy=sc_input.counterfactual_policy,
            )
        except Exception as exc:
            errors.append(f"Scenario evaluation failed: {exc}")
            return ScenarioServiceResult(errors=errors)

        return ScenarioServiceResult(
            evaluation=evaluation,
            errors=errors,
            warnings=warnings,
        )
