"""
Scenario service — orchestrates scenario construction, evaluation, and
governance checks without Streamlit dependencies.

PR 51B: Correctly dispatches to ``evaluate_manual_scenario()`` for manual
scenarios and ``optimize_scenario()`` for optimisation. Identity fields
(model_run_id, fingerprints) must be supplied explicitly — never read
from ``FHModelMeta``.

Work Package 5 (`Media-Mix-Lab: Coding LLM Next Steps Post PR262`): adds
``evaluate_manual_sequential()``, dispatching to ``core.
sequential_scenario_evaluation.evaluate_manual_scenario_sequential`` for
the sequential-weekly method - the same dispatch pattern as
``evaluate_manual``, calling a different core module rather than branching
inside the existing method. The caller (not this service) is responsible
for phasing the monthly plan and building the future context/governed
``WeeklyPlan``\\ s (``core.planning.phasing``/``future_context``/
``weekly_plan_builder``) - this service only evaluates already-built
weekly plans, mirroring how ``evaluate_manual`` only evaluates an
already-built ``spend_plan``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.media_costs import CostMappingRegistry
from ancestry_mmm.core.planning.future_context import FutureContextResult
from ancestry_mmm.core.planning.phasing import HorizonConfiguration
from ancestry_mmm.core.scenario_governance import (
    ScenarioPlan,
    CounterfactualPolicy,
)
from ancestry_mmm.core.planning.value import (
    CurrencyContext,
    OutcomeValueMapping,
    PlanningObjective,
    ScenarioEvaluationResult,
)
from ancestry_mmm.core.sequential_evaluation_context import SequentialEvaluationContext
from ancestry_mmm.core.sequential_scenario_evaluation import (
    SequentialScenarioEvaluationResult,
)
from ancestry_mmm.core.sequential_simulation import WeeklyPlan
from ancestry_mmm.core.validation_policy import ApprovalReadiness, ThresholdPolicy
from ancestry_mmm.core.outcome_approval import OutcomeApproval

AnyPosteriorParams = Union[FHPosteriorParams, FHMarketSpecificPosteriorParams]


@dataclass
class ManualScenarioInput:
    """Typed input for manual scenario evaluation.

    All identity fields are explicit. Never read from FHModelMeta.
    """

    market: str
    spend_plan: Dict[str, Dict[str, float]]
    meta: FHModelMeta
    params: AnyPosteriorParams
    reference_context_by_month: Dict[str, dict]
    ltv: Optional[Dict[str, float]] = None
    model_type: str = "shared"
    approval: Optional[ModelApproval] = None
    model_run_id: str = ""
    data_fingerprint: str = ""
    model_spec_fingerprint: str = ""
    posterior_fingerprint: str = ""
    cost_mapping_registry: Optional[CostMappingRegistry] = None
    cost_context_id: Optional[str] = None
    cost_as_of_by_month: Optional[Dict[str, str]] = None
    counterfactual_media_input_by_month: Optional[Dict[str, Dict[str, float]]] = None
    planning_objective: Optional[PlanningObjective] = None
    activity_definitions: Optional[List[ActivityDefinition]] = None
    scenario_plan: Optional[ScenarioPlan] = None
    counterfactual_policy: Optional[CounterfactualPolicy] = None
    outcome_approvals: Optional[List[OutcomeApproval]] = None
    governance_mode: str = "official"
    nbt_completeness_metadata: Optional[dict] = None
    artefact_kind: str = "manual_scenario"
    value_mapping: Optional[OutcomeValueMapping] = None
    currency_context: Optional[CurrencyContext] = None
    approval_readiness: Optional[ApprovalReadiness] = None
    current_policy: Optional[ThresholdPolicy] = None


@dataclass
class SequentialManualScenarioInput:
    """Typed input for sequential-weekly manual scenario evaluation
    (Work Package 5, `REQ-SCEN-001`/`REQ-SCEN-002`).

    ``candidate_plan``/``reference_plan`` must already be governed
    ``WeeklyPlan``\\ s (``core.planning.weekly_plan_builder.
    build_governed_weekly_plan``) sharing the same market/canonical weeks
    as ``evaluation_context`` - this service evaluates, it does not phase
    a monthly plan or build a future context itself. All identity fields
    are explicit. Never read from ``FHModelMeta``.
    """

    market: str
    candidate_plan: WeeklyPlan
    reference_plan: WeeklyPlan
    meta: FHModelMeta
    params: AnyPosteriorParams
    historical_frame: Dict[str, Any]
    horizon_configuration: HorizonConfiguration
    evaluation_context: SequentialEvaluationContext
    weekly_plan_fingerprint: str
    reference_weekly_plan_fingerprint: str
    model_type: str = "shared"
    future_context: Optional[FutureContextResult] = None
    terminal_future_context: Optional[FutureContextResult] = None
    approval: Optional[ModelApproval] = None
    model_run_id: str = ""
    data_fingerprint: str = ""
    model_spec_fingerprint: str = ""
    posterior_fingerprint: str = ""
    planning_objective: Optional[PlanningObjective] = None
    activity_definitions: Optional[List[ActivityDefinition]] = None
    scenario_plan: Optional[ScenarioPlan] = None
    counterfactual_policy: Optional[CounterfactualPolicy] = None
    cost_mapping_registry: Optional[CostMappingRegistry] = None
    cost_context_id: Optional[str] = None
    cost_as_of_by_period: Optional[Dict[str, str]] = None
    outcome_approvals: Optional[List[OutcomeApproval]] = None
    governance_mode: str = "official"
    nbt_completeness_metadata: Optional[dict] = None
    artefact_kind: str = "manual_scenario"
    value_mapping: Optional[OutcomeValueMapping] = None
    currency_context: Optional[CurrencyContext] = None
    approval_readiness: Optional[ApprovalReadiness] = None
    current_policy: Optional[ThresholdPolicy] = None
    trace: Optional[Any] = None
    n_posterior_draws: int = 0
    posterior_seed: int = 42


@dataclass
class OptimisationInput:
    """Typed input for scenario optimisation."""

    current_spend_plan: Dict[str, Dict[str, float]]
    months: List[str]
    channels: List[str]
    market: str
    meta: FHModelMeta
    params: AnyPosteriorParams
    reference_context_by_month: Dict[str, dict]
    ltv: Optional[Dict[str, float]] = None
    objective: Optional[str] = None
    constraints: Optional[List[Any]] = None  # SpendConstraint
    conserve_total_budget: bool = True
    max_iter: int = 200
    model_type: str = "shared"
    target_outcome_ids: Optional[List[str]] = None
    weights: Optional[Dict[str, float]] = None
    assume_value_scaled_weights: bool = False
    approval: Optional[ModelApproval] = None
    model_run_id: str = ""
    data_fingerprint: str = ""
    model_spec_fingerprint: str = ""
    posterior_fingerprint: str = ""
    cost_mapping_registry: Optional[CostMappingRegistry] = None
    cost_context_id: Optional[str] = None
    cost_as_of_by_month: Optional[Dict[str, str]] = None
    planning_objective: Optional[PlanningObjective] = None
    counterfactual_media_input_by_month: Optional[Dict[str, Dict[str, float]]] = None
    activity_definitions: Optional[List[ActivityDefinition]] = None
    counterfactual_policy: Optional[CounterfactualPolicy] = None
    posterior_trace: Optional[Any] = None
    posterior_evaluation_draws: int = 100
    optimization_resource: Optional[Any] = None  # OptimizationResource
    governance_mode: str = "official"
    outcome_approvals: Optional[List[OutcomeApproval]] = None
    nbt_completeness_metadata: Optional[dict] = None
    artefact_kind: Optional[str] = None
    value_currency: Optional[str] = None
    value_mapping: Optional[OutcomeValueMapping] = None
    currency_context: Optional[CurrencyContext] = None
    approval_readiness: Optional[ApprovalReadiness] = None
    current_policy: Optional[ThresholdPolicy] = None
    # REQ-OPT-001 Requirement 2 (Decision 16): the extended governed
    # constraint-kind vocabulary (`core.optimization_constraint_vocabulary.
    # GovernedSpendConstraint`) - replaces `constraints` for bounds-building
    # when supplied. Typed `Any` here (not `GovernedSpendConstraint`) to
    # avoid a hard import-time dependency on that module from every caller
    # of this service, matching `constraints: Optional[List[Any]]` above.
    governed_constraints: Optional[List[Any]] = None


@dataclass
class ScenarioServiceResult:
    """Structured scenario evaluation output."""

    evaluation: Optional[ScenarioEvaluationResult] = None
    evaluation_df: Optional[pd.DataFrame] = None
    optimisation_result: Optional[dict] = None
    sequential_evaluation: Optional[SequentialScenarioEvaluationResult] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class ScenarioService:
    """Application service for scenario planning and evaluation.

    Dispatches to the correct core API:
    - ``evaluate_manual_scenario()`` for steady-state monthly manual
      scenarios
    - ``optimize_scenario()`` for steady-state optimisation
    - ``evaluate_manual_scenario_sequential()`` for sequential-weekly
      manual scenarios (Work Package 5) - a distinct, always-labelled
      method (``REQ-SCEN-001`` item 7), never a silent alternative to the
      steady-state path

    Does not access Streamlit session state, mutate global state, or
    render any UI.
    """

    def evaluate_manual(self, sc_input: ManualScenarioInput) -> ScenarioServiceResult:
        """Evaluate a manual scenario.

        Calls ``evaluate_manual_scenario()`` with the correct signature.
        All identity fields must be supplied explicitly.
        """
        errors: List[str] = []
        warnings: List[str] = []

        if sc_input.spend_plan is None:
            errors.append("No spend plan provided.")
            return ScenarioServiceResult(errors=errors)
        if sc_input.params is None:
            errors.append("No posterior params provided.")
            return ScenarioServiceResult(errors=errors)
        if sc_input.meta is None:
            errors.append("No model metadata provided.")
            return ScenarioServiceResult(errors=errors)
        if sc_input.approval is None:
            errors.append("No model approval provided.")
            return ScenarioServiceResult(errors=errors)

        if errors:
            return ScenarioServiceResult(errors=errors)

        from ancestry_mmm.core.optimization import evaluate_manual_scenario

        try:
            evaluation = evaluate_manual_scenario(
                sc_input.spend_plan,
                sc_input.market,
                sc_input.meta,
                sc_input.params,
                sc_input.reference_context_by_month,
                sc_input.ltv,
                model_type=sc_input.model_type,
                approval=sc_input.approval,
                model_run_id=sc_input.model_run_id,
                data_fingerprint=sc_input.data_fingerprint,
                model_spec_fingerprint=sc_input.model_spec_fingerprint,
                posterior_fingerprint=sc_input.posterior_fingerprint,
                cost_mapping_registry=sc_input.cost_mapping_registry,
                cost_context_id=sc_input.cost_context_id,
                cost_as_of_by_month=sc_input.cost_as_of_by_month,
                counterfactual_media_input_by_month=sc_input.counterfactual_media_input_by_month,
                planning_objective=sc_input.planning_objective,
                activity_definitions=sc_input.activity_definitions,
                scenario_plan=sc_input.scenario_plan,
                counterfactual_policy=sc_input.counterfactual_policy,
                outcome_approvals=sc_input.outcome_approvals,
                governance_mode=sc_input.governance_mode,
                nbt_completeness_metadata=sc_input.nbt_completeness_metadata,
                artefact_kind=sc_input.artefact_kind,
                value_mapping=sc_input.value_mapping,
                currency_context=sc_input.currency_context,
                approval_readiness=sc_input.approval_readiness,
                current_policy=sc_input.current_policy,
            )
        except Exception as exc:
            errors.append(f"Manual scenario evaluation failed: {exc}")
            return ScenarioServiceResult(errors=errors)

        return ScenarioServiceResult(
            evaluation=evaluation,
            errors=errors,
            warnings=warnings,
        )

    def evaluate_manual_sequential(
        self, sc_input: SequentialManualScenarioInput
    ) -> ScenarioServiceResult:
        """Evaluate a sequential-weekly manual scenario (Work Package 5).

        Calls ``evaluate_manual_scenario_sequential()`` with the correct
        signature. All identity fields must be supplied explicitly.
        ``candidate_plan``/``reference_plan`` must already be governed
        ``WeeklyPlan``\\ s - phasing and future-context construction are
        the caller's responsibility.
        """
        errors: List[str] = []
        warnings: List[str] = []

        if sc_input.candidate_plan is None or sc_input.reference_plan is None:
            errors.append("No candidate/reference weekly plan provided.")
            return ScenarioServiceResult(errors=errors)
        if sc_input.params is None:
            errors.append("No posterior params provided.")
            return ScenarioServiceResult(errors=errors)
        if sc_input.meta is None:
            errors.append("No model metadata provided.")
            return ScenarioServiceResult(errors=errors)
        if sc_input.evaluation_context is None:
            errors.append("No sequential evaluation context provided.")
            return ScenarioServiceResult(errors=errors)
        if sc_input.governance_mode == "official" and sc_input.approval is None:
            errors.append("No model approval provided.")
            return ScenarioServiceResult(errors=errors)

        if errors:
            return ScenarioServiceResult(errors=errors)

        from ancestry_mmm.core.sequential_scenario_evaluation import (
            evaluate_manual_scenario_sequential,
        )

        try:
            evaluation = evaluate_manual_scenario_sequential(
                market=sc_input.market,
                candidate_plan=sc_input.candidate_plan,
                reference_plan=sc_input.reference_plan,
                meta=sc_input.meta,
                params=sc_input.params,
                historical_frame=sc_input.historical_frame,
                horizon_configuration=sc_input.horizon_configuration,
                evaluation_context=sc_input.evaluation_context,
                weekly_plan_fingerprint=sc_input.weekly_plan_fingerprint,
                reference_weekly_plan_fingerprint=sc_input.reference_weekly_plan_fingerprint,
                model_type=sc_input.model_type,
                future_context=sc_input.future_context,
                terminal_future_context=sc_input.terminal_future_context,
                approval=sc_input.approval,
                model_run_id=sc_input.model_run_id,
                data_fingerprint=sc_input.data_fingerprint,
                model_spec_fingerprint=sc_input.model_spec_fingerprint,
                posterior_fingerprint=sc_input.posterior_fingerprint,
                planning_objective=sc_input.planning_objective,
                activity_definitions=sc_input.activity_definitions,
                scenario_plan=sc_input.scenario_plan,
                counterfactual_policy=sc_input.counterfactual_policy,
                cost_mapping_registry=sc_input.cost_mapping_registry,
                cost_context_id=sc_input.cost_context_id,
                cost_as_of_by_period=sc_input.cost_as_of_by_period,
                outcome_approvals=sc_input.outcome_approvals,
                governance_mode=sc_input.governance_mode,
                nbt_completeness_metadata=sc_input.nbt_completeness_metadata,
                artefact_kind=sc_input.artefact_kind,
                value_mapping=sc_input.value_mapping,
                currency_context=sc_input.currency_context,
                approval_readiness=sc_input.approval_readiness,
                current_policy=sc_input.current_policy,
                trace=sc_input.trace,
                n_posterior_draws=sc_input.n_posterior_draws,
                posterior_seed=sc_input.posterior_seed,
            )
        except Exception as exc:
            errors.append(f"Sequential manual scenario evaluation failed: {exc}")
            return ScenarioServiceResult(errors=errors)

        if evaluation.warnings:
            warnings.extend(evaluation.warnings)

        return ScenarioServiceResult(
            sequential_evaluation=evaluation,
            errors=errors,
            warnings=warnings,
        )

    def optimise(self, opt_input: OptimisationInput) -> ScenarioServiceResult:
        """Run constrained/unconstrained optimisation.

        Calls ``optimize_scenario()`` with the correct signature.
        """
        errors: List[str] = []

        if opt_input.current_spend_plan is None:
            errors.append("No current spend plan provided.")
            return ScenarioServiceResult(errors=errors)
        if opt_input.params is None:
            errors.append("No posterior params provided.")
            return ScenarioServiceResult(errors=errors)
        if opt_input.approval is None:
            errors.append("No model approval provided.")
            return ScenarioServiceResult(errors=errors)

        if errors:
            return ScenarioServiceResult(errors=errors)

        from ancestry_mmm.core.optimization import optimize_scenario

        try:
            result = optimize_scenario(
                opt_input.current_spend_plan,
                opt_input.months,
                opt_input.channels,
                opt_input.market,
                opt_input.meta,
                opt_input.params,
                opt_input.reference_context_by_month,
                opt_input.ltv,
                opt_input.objective,
                opt_input.constraints,
                opt_input.conserve_total_budget,
                opt_input.max_iter,
                model_type=opt_input.model_type,
                target_outcome_ids=opt_input.target_outcome_ids,
                weights=opt_input.weights,
                assume_value_scaled_weights=opt_input.assume_value_scaled_weights,
                approval=opt_input.approval,
                model_run_id=opt_input.model_run_id,
                data_fingerprint=opt_input.data_fingerprint,
                model_spec_fingerprint=opt_input.model_spec_fingerprint,
                posterior_fingerprint=opt_input.posterior_fingerprint,
                cost_mapping_registry=opt_input.cost_mapping_registry,
                cost_context_id=opt_input.cost_context_id,
                cost_as_of_by_month=opt_input.cost_as_of_by_month,
                planning_objective=opt_input.planning_objective,
                counterfactual_media_input_by_month=opt_input.counterfactual_media_input_by_month,
                activity_definitions=opt_input.activity_definitions,
                counterfactual_policy=opt_input.counterfactual_policy,
                posterior_trace=opt_input.posterior_trace,
                posterior_evaluation_draws=opt_input.posterior_evaluation_draws,
                optimization_resource=opt_input.optimization_resource,
                governance_mode=opt_input.governance_mode,
                outcome_approvals=opt_input.outcome_approvals,
                nbt_completeness_metadata=opt_input.nbt_completeness_metadata,
                artefact_kind=opt_input.artefact_kind,
                value_currency=opt_input.value_currency,
                value_mapping=opt_input.value_mapping,
                currency_context=opt_input.currency_context,
                approval_readiness=opt_input.approval_readiness,
                current_policy=opt_input.current_policy,
                governed_constraints=opt_input.governed_constraints,
            )
        except Exception as exc:
            errors.append(f"Optimisation failed: {exc}")
            return ScenarioServiceResult(errors=errors)

        return ScenarioServiceResult(
            optimisation_result=result,
            errors=errors,
            warnings=[],
        )
