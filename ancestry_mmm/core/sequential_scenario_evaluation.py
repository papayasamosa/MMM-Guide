"""
Sequential weekly manual scenario evaluation (Work Package 5 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR262`, `REQ-SCEN-001`/
`REQ-SCEN-002`/`REQ-SCEN-003`/`REQ-STATE-001`).

Orchestrates a full sequential-weekly manual scenario evaluation:
historical-state reconstruction, candidate/reference weekly simulation
through one shared `SequentialEvaluationContext`, weekly incrementality,
monthly aggregation (only after weekly evaluation - never an independent
monthly curve), configured short/long horizon response, terminal
incremental carryover (reported structurally separately, never folded into
the plan-window result), optional fully draw-consistent posterior
evaluation, and governance/economics evidence.

Reuses the SAME governance-resolution machinery
`core.optimization.evaluate_manual_scenario` (the steady-state monthly
path) uses (`core.planning_governance.resolve_planning_governance`,
`core.planning.value.ScenarioGovernanceDependencies`, `core.scenario_
governance.resolve_scenario_plan`/`resolve_counterfactual` - all
confirmed period-key-agnostic, not steady-state-specific) - the two paths
never diverge in what "official" governance means, only in the prediction
mathematics and the resulting evidence shape (`SequentialScenarioEvaluationResult`,
a deliberately separate type from `ScenarioEvaluationResult`, whose
`predicted: pd.DataFrame` is monthly-wide-table-shaped and does not fit a
weekly/terminal/posterior result - not a competing planning domain, a
distinct result shape for a distinct calculation grain).

Never silently switches method: a caller reaching this function has
explicitly chosen the sequential-weekly evaluation contract
(`REQ-SCEN-001` item 7) - `planning_semantics` is always stamped
`SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS`, never the steady-state
constant.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from .activities import ActivityDefinition, activity_definitions_fingerprint
from .approval import ModelApproval
from .hierarchical_model import FHModelMeta
from .market_specific_predict import (
    FHMarketSpecificPosteriorParams,
)
from .outcome_approval import OutcomeApproval
from .planning.future_context import FutureContextResult
from .planning.phasing import HorizonConfiguration
from .planning.terminal_response import (
    TerminalIncrementalResult,
    evaluate_terminal_incremental_response,
    evaluate_terminal_incremental_response_market_specific,
)
from .planning.value import (
    SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS,
    CurrencyContext,
    OutcomeValueMapping,
    PlanningEvaluationSemantics,
    PlanningObjective,
    ResolvedPlanningGovernance,
    ScenarioGovernanceDependencies,
)
from .planning_governance import resolve_planning_governance
from .predict import FHPosteriorParams
from .scenario_governance import (
    CounterfactualPolicy,
    ScenarioPlan,
    resolve_scenario_plan,
)
from .sequential_evaluation_context import (
    SequentialEvaluationContext,
    compute_incremental_outcome_with_context,
)
from .sequential_simulation import (
    SequentialSimulationResult,
    WeeklyPlan,
    reconstruct_starting_state,
    reconstruct_starting_state_market_specific,
    simulate_sequential_outcomes,
    simulate_sequential_outcomes_market_specific,
    simulate_sequential_outcomes_posterior_draw_consistent,
    simulate_sequential_outcomes_posterior_market_specific_draw_consistent,
)
from .validation_policy import ApprovalReadiness, ThresholdPolicy

AnyPosteriorParams = Union[FHPosteriorParams, FHMarketSpecificPosteriorParams]

MARKET_SPECIFIC_MODEL_TYPE = "market_specific"


class SequentialScenarioEvaluationError(ValueError):
    """Raised when a sequential scenario cannot be safely evaluated - a
    mismatched market/plan/context, or a required governance input missing
    in official mode."""


def _week_to_month(week_label: str) -> str:
    return week_label[:7]


def _sha256_of(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sum_over_index_range(values: np.ndarray, bounds: Tuple[int, int]) -> np.ndarray:
    """`bounds` is an inclusive `(start, end)` week-index range, matching
    `HorizonConfiguration`'s own convention (e.g. `short_horizon_weeks=(0, 4)`
    covers weeks 0-4 inclusive, five weeks)."""
    start, end = bounds
    end = min(end, values.shape[0] - 1)
    if start > end:
        return np.zeros(values.shape[1:])
    return np.asarray(values[start : end + 1].sum(axis=0))


@dataclass(frozen=True)
class SequentialScenarioEvaluationResult:
    """Full sequential-weekly evaluation output. Deliberately a separate
    type from `core.planning.value.ScenarioEvaluationResult` (the
    steady-state method's monthly-wide-table result) - not a competing
    planning domain, a distinct result shape for a distinct calculation
    grain and contract."""

    market: str
    calculation_method: str
    weekly_period_labels: Tuple[str, ...]
    monthly_period_labels: Tuple[str, ...]
    outcome_ids: Tuple[str, ...]
    candidate: SequentialSimulationResult
    reference: SequentialSimulationResult
    weekly_incremental: np.ndarray
    monthly_incremental: np.ndarray
    short_horizon_incremental: np.ndarray
    long_horizon_incremental: np.ndarray
    terminal: Optional[TerminalIncrementalResult]
    posterior_weekly_incremental: Optional[np.ndarray]
    phasing_method_id: str
    weekly_plan_fingerprint: str
    reference_weekly_plan_fingerprint: str
    future_context_fingerprint: str
    starting_state_fingerprint: str
    evaluation_context_fingerprint: str
    governance_mode: str
    artefact_kind: str
    resolved_governance: Optional[ResolvedPlanningGovernance]
    governance_dependencies: Optional[ScenarioGovernanceDependencies]
    activity_definitions_fingerprint: Optional[str]
    cost_mapping_fingerprint: Optional[str]
    counterfactual_policy_fingerprint: str
    economics_coverage: Optional[dict]
    planning_semantics: PlanningEvaluationSemantics
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for persistence (WP5 part 4). Every numpy array
        becomes a plain list; every nested typed object delegates to its
        own `to_dict` - this method never re-derives that serialization
        itself, mirroring `core.sequential_simulation.SequentialCarryInState.
        to_dict`'s established pattern for this codebase's sequential
        types."""
        return {
            "market": self.market,
            "calculation_method": self.calculation_method,
            "weekly_period_labels": list(self.weekly_period_labels),
            "monthly_period_labels": list(self.monthly_period_labels),
            "outcome_ids": list(self.outcome_ids),
            "candidate": self.candidate.to_dict(),
            "reference": self.reference.to_dict(),
            "weekly_incremental": self.weekly_incremental.tolist(),
            "monthly_incremental": self.monthly_incremental.tolist(),
            "short_horizon_incremental": self.short_horizon_incremental.tolist(),
            "long_horizon_incremental": self.long_horizon_incremental.tolist(),
            "terminal": self.terminal.to_dict() if self.terminal is not None else None,
            "posterior_weekly_incremental": (
                self.posterior_weekly_incremental.tolist()
                if self.posterior_weekly_incremental is not None
                else None
            ),
            "phasing_method_id": self.phasing_method_id,
            "weekly_plan_fingerprint": self.weekly_plan_fingerprint,
            "reference_weekly_plan_fingerprint": self.reference_weekly_plan_fingerprint,
            "future_context_fingerprint": self.future_context_fingerprint,
            "starting_state_fingerprint": self.starting_state_fingerprint,
            "evaluation_context_fingerprint": self.evaluation_context_fingerprint,
            "governance_mode": self.governance_mode,
            "artefact_kind": self.artefact_kind,
            "resolved_governance": (
                self.resolved_governance.to_dict()
                if self.resolved_governance is not None
                else None
            ),
            "governance_dependencies": (
                self.governance_dependencies.to_dict()
                if self.governance_dependencies is not None
                else None
            ),
            "activity_definitions_fingerprint": self.activity_definitions_fingerprint,
            "cost_mapping_fingerprint": self.cost_mapping_fingerprint,
            "counterfactual_policy_fingerprint": self.counterfactual_policy_fingerprint,
            "economics_coverage": self.economics_coverage,
            "planning_semantics": self.planning_semantics.to_dict(),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SequentialScenarioEvaluationResult":
        terminal = d.get("terminal")
        resolved_governance = d.get("resolved_governance")
        governance_dependencies = d.get("governance_dependencies")
        posterior_weekly_incremental = d.get("posterior_weekly_incremental")
        return cls(
            market=d["market"],
            calculation_method=d["calculation_method"],
            weekly_period_labels=tuple(d.get("weekly_period_labels", [])),
            monthly_period_labels=tuple(d.get("monthly_period_labels", [])),
            outcome_ids=tuple(d.get("outcome_ids", [])),
            candidate=SequentialSimulationResult.from_dict(d["candidate"]),
            reference=SequentialSimulationResult.from_dict(d["reference"]),
            weekly_incremental=np.array(d.get("weekly_incremental", [])),
            monthly_incremental=np.array(d.get("monthly_incremental", [])),
            short_horizon_incremental=np.array(d.get("short_horizon_incremental", [])),
            long_horizon_incremental=np.array(d.get("long_horizon_incremental", [])),
            terminal=(
                TerminalIncrementalResult.from_dict(terminal)
                if terminal is not None
                else None
            ),
            posterior_weekly_incremental=(
                np.array(posterior_weekly_incremental)
                if posterior_weekly_incremental is not None
                else None
            ),
            phasing_method_id=d.get("phasing_method_id", ""),
            weekly_plan_fingerprint=d.get("weekly_plan_fingerprint", ""),
            reference_weekly_plan_fingerprint=d.get(
                "reference_weekly_plan_fingerprint", ""
            ),
            future_context_fingerprint=d.get("future_context_fingerprint", ""),
            starting_state_fingerprint=d.get("starting_state_fingerprint", ""),
            evaluation_context_fingerprint=d.get("evaluation_context_fingerprint", ""),
            governance_mode=d.get("governance_mode", "official"),
            artefact_kind=d.get("artefact_kind", "manual_scenario"),
            resolved_governance=(
                ResolvedPlanningGovernance.from_dict(resolved_governance)
                if resolved_governance is not None
                else None
            ),
            governance_dependencies=(
                ScenarioGovernanceDependencies.from_dict(governance_dependencies)
                if governance_dependencies is not None
                else None
            ),
            activity_definitions_fingerprint=d.get("activity_definitions_fingerprint"),
            cost_mapping_fingerprint=d.get("cost_mapping_fingerprint"),
            counterfactual_policy_fingerprint=d.get(
                "counterfactual_policy_fingerprint", ""
            ),
            economics_coverage=d.get("economics_coverage"),
            planning_semantics=PlanningEvaluationSemantics.from_dict(
                d["planning_semantics"]
            ),
            warnings=tuple(d.get("warnings", [])),
        )


def evaluate_manual_scenario_sequential(
    *,
    market: str,
    candidate_plan: WeeklyPlan,
    reference_plan: WeeklyPlan,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    historical_frame: Dict[str, Any],
    horizon_configuration: HorizonConfiguration,
    evaluation_context: SequentialEvaluationContext,
    weekly_plan_fingerprint: str,
    reference_weekly_plan_fingerprint: str,
    model_type: str = "shared",
    future_context: Optional[FutureContextResult] = None,
    terminal_future_context: Optional[FutureContextResult] = None,
    approval: Optional[ModelApproval] = None,
    model_run_id: str = "",
    data_fingerprint: str = "",
    model_spec_fingerprint: str = "",
    posterior_fingerprint: str = "",
    planning_objective: Optional[PlanningObjective] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    scenario_plan: Optional[ScenarioPlan] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
    cost_mapping_registry: Optional[Any] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_period: Optional[Dict[str, str]] = None,
    outcome_approvals: Optional[List[OutcomeApproval]] = None,
    governance_mode: str = "official",
    nbt_completeness_metadata: Optional[dict] = None,
    artefact_kind: str = "manual_scenario",
    value_mapping: Optional[OutcomeValueMapping] = None,
    currency_context: Optional[CurrencyContext] = None,
    approval_readiness: Optional[ApprovalReadiness] = None,
    current_policy: Optional[ThresholdPolicy] = None,
    trace: Optional[Any] = None,
    n_posterior_draws: int = 0,
    posterior_seed: int = 42,
) -> SequentialScenarioEvaluationResult:
    """Evaluate a sequential weekly manual scenario. See module docstring
    for the full flow. `candidate_plan`/`reference_plan` must already be
    governed `WeeklyPlan`s (see `core.planning.weekly_plan_builder.
    build_governed_weekly_plan`) sharing the same market/weeks as
    `evaluation_context` - phasing and future-context construction are the
    caller's responsibility (this function evaluates, it does not phase)."""
    if candidate_plan.market != market or reference_plan.market != market:
        raise SequentialScenarioEvaluationError(
            "candidate_plan/reference_plan market must match the requested "
            f"market ({market!r})."
        )
    if candidate_plan.period_labels != reference_plan.period_labels:
        raise SequentialScenarioEvaluationError(
            "candidate_plan and reference_plan must cover exactly the same "
            "canonical weeks."
        )
    if evaluation_context.market != market:
        raise SequentialScenarioEvaluationError(
            f"evaluation_context.market must match the requested market ({market!r})."
        )

    is_market_specific = model_type == MARKET_SPECIFIC_MODEL_TYPE

    planning_semantics = SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS
    resolved_gov: Optional[ResolvedPlanningGovernance] = None
    governance_deps: Optional[ScenarioGovernanceDependencies] = None

    if governance_mode == "official":
        if planning_objective is None:
            from .optimization import ObjectiveMissingError

            raise ObjectiveMissingError(
                "Official sequential manual evaluation requires a PlanningObjective."
            )
        if approval is None:
            raise SequentialScenarioEvaluationError(
                "Official sequential manual evaluation requires a ModelApproval."
            )
        resolved_gov = resolve_planning_governance(
            operation="planning",
            planning_objective=planning_objective,
            model_approval=approval,
            model_run_id=model_run_id,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            market=market,
            meta=meta,
            outcome_approvals=outcome_approvals or [],
            nbt_completeness_metadata=nbt_completeness_metadata,
            approval_readiness=approval_readiness,
            current_policy=current_policy,
        )
        from .optimization import _resolve_nbt_completeness_fingerprint, _is_nbt_outcome

        governance_deps = ScenarioGovernanceDependencies(
            model_run_id=model_run_id,
            model_approval_fingerprint=resolved_gov.model_approval_fingerprint,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            planning_objective_fingerprint=resolved_gov.objective_fingerprint,
            outcome_authorisations=resolved_gov.authorisations,
            value_mapping_id=(
                value_mapping.mapping_id if value_mapping is not None else None
            ),
            value_mapping_fingerprint=(
                value_mapping.fingerprint if value_mapping is not None else None
            ),
            currency_context_fingerprint=(
                currency_context.fingerprint() if currency_context is not None else None
            ),
            activity_definitions_fingerprint=(
                activity_definitions_fingerprint(activity_definitions)
                if activity_definitions is not None
                else None
            ),
            cost_mapping_fingerprint=(
                cost_mapping_registry.fingerprint()
                if cost_mapping_registry is not None
                else None
            ),
            counterfactual_policy_fingerprint=(
                counterfactual_policy.fingerprint()
                if counterfactual_policy is not None
                else ""
            ),
            nbt_completeness_fingerprint=_resolve_nbt_completeness_fingerprint(
                nbt_completeness_metadata,
                fail_closed=(
                    planning_objective is not None
                    and any(
                        _is_nbt_outcome(tid, meta)
                        for tid in planning_objective.target_outcome_ids
                    )
                ),
            ),
            validation_policy_id=(
                approval_readiness.policy_id if approval_readiness is not None else ""
            ),
            validation_policy_version=(
                approval_readiness.policy_version
                if approval_readiness is not None
                else ""
            ),
            validation_policy_fingerprint=(
                approval_readiness.policy_fingerprint
                if approval_readiness is not None
                else ""
            ),
            readiness_artefact_id=(
                approval_readiness.readiness_artefact_id
                if approval_readiness is not None
                else ""
            ),
            readiness_fingerprint=(
                approval_readiness.fingerprint()
                if approval_readiness is not None
                else ""
            ),
            diagnostic_artefact_fingerprint=(
                approval_readiness.diagnostic_artefact_fingerprint
                if approval_readiness is not None
                else ""
            ),
            model_identity_fingerprint=(
                approval_readiness.model_identity_fingerprint
                if approval_readiness is not None
                else ""
            ),
            planning_semantics_fingerprint=planning_semantics.fingerprint(),
        )

    # Same starting state for candidate and reference (REQ-SCEN-001 item 1).
    if is_market_specific:
        assert isinstance(params, FHMarketSpecificPosteriorParams)
        carry_in = reconstruct_starting_state_market_specific(
            historical_frame, meta, params, market
        )
        candidate = simulate_sequential_outcomes_market_specific(
            candidate_plan, carry_in, meta, params
        )
        reference = simulate_sequential_outcomes_market_specific(
            reference_plan, carry_in, meta, params
        )
    else:
        assert isinstance(params, FHPosteriorParams)
        carry_in = reconstruct_starting_state(historical_frame, meta, params, market)
        candidate = simulate_sequential_outcomes(candidate_plan, carry_in, meta, params)
        reference = simulate_sequential_outcomes(reference_plan, carry_in, meta, params)

    weekly_incremental = compute_incremental_outcome_with_context(
        candidate, evaluation_context, reference, evaluation_context
    )

    weeks = candidate.period_labels
    months = sorted({_week_to_month(w) for w in weeks})
    month_indices: Dict[str, List[int]] = {m: [] for m in months}
    for i, w in enumerate(weeks):
        month_indices[_week_to_month(w)].append(i)
    monthly_incremental = np.stack(
        [weekly_incremental[month_indices[m]].sum(axis=0) for m in months], axis=0
    )

    short_horizon_incremental = _sum_over_index_range(
        weekly_incremental, horizon_configuration.short_horizon_weeks
    )
    long_horizon_incremental = _sum_over_index_range(
        weekly_incremental, horizon_configuration.long_horizon_weeks
    )

    terminal: Optional[TerminalIncrementalResult] = None
    if terminal_future_context is not None:
        channels = list(candidate_plan.media_by_channel)
        if is_market_specific:
            assert isinstance(params, FHMarketSpecificPosteriorParams)
            terminal = evaluate_terminal_incremental_response_market_specific(
                market=market,
                channels=channels,
                candidate_ending_state=candidate.ending_state,
                reference_ending_state=reference.ending_state,
                future_context=terminal_future_context,
                meta=meta,
                params=params,
            )
        else:
            assert isinstance(params, FHPosteriorParams)
            terminal = evaluate_terminal_incremental_response(
                market=market,
                channels=channels,
                candidate_ending_state=candidate.ending_state,
                reference_ending_state=reference.ending_state,
                future_context=terminal_future_context,
                meta=meta,
                params=params,
            )

    posterior_weekly_incremental: Optional[np.ndarray] = None
    if trace is not None and n_posterior_draws > 0:
        if is_market_specific:
            candidate_draws = (
                simulate_sequential_outcomes_posterior_market_specific_draw_consistent(
                    candidate_plan,
                    historical_frame,
                    trace,
                    meta,
                    market,
                    n_draws=n_posterior_draws,
                    seed=posterior_seed,
                )
            )
            reference_draws = (
                simulate_sequential_outcomes_posterior_market_specific_draw_consistent(
                    reference_plan,
                    historical_frame,
                    trace,
                    meta,
                    market,
                    n_draws=n_posterior_draws,
                    seed=posterior_seed,
                )
            )
        else:
            candidate_draws = simulate_sequential_outcomes_posterior_draw_consistent(
                candidate_plan,
                historical_frame,
                trace,
                meta,
                market,
                n_draws=n_posterior_draws,
                seed=posterior_seed,
            )
            reference_draws = simulate_sequential_outcomes_posterior_draw_consistent(
                reference_plan,
                historical_frame,
                trace,
                meta,
                market,
                n_draws=n_posterior_draws,
                seed=posterior_seed,
            )
        posterior_weekly_incremental = candidate_draws - reference_draws

    warnings: List[str] = []
    economics_coverage: Optional[dict] = None
    if scenario_plan is not None:
        try:
            _model_input, _costs, economics_coverage = resolve_scenario_plan(
                scenario_plan,
                market=market,
                activity_definitions=activity_definitions,
                cost_mapping_registry=cost_mapping_registry,
                cost_context_id=cost_context_id or "default",
                cost_as_of_by_period=cost_as_of_by_period,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a warning, not a hard failure
            warnings.append(f"Economics coverage could not be resolved: {exc}")

    return SequentialScenarioEvaluationResult(
        market=market,
        calculation_method=planning_semantics.engine,
        weekly_period_labels=weeks,
        monthly_period_labels=tuple(months),
        outcome_ids=candidate.outcome_ids,
        candidate=candidate,
        reference=reference,
        weekly_incremental=weekly_incremental,
        monthly_incremental=monthly_incremental,
        short_horizon_incremental=short_horizon_incremental,
        long_horizon_incremental=long_horizon_incremental,
        terminal=terminal,
        posterior_weekly_incremental=posterior_weekly_incremental,
        phasing_method_id=evaluation_context.phasing_policy_identity,
        weekly_plan_fingerprint=weekly_plan_fingerprint,
        reference_weekly_plan_fingerprint=reference_weekly_plan_fingerprint,
        future_context_fingerprint=(
            future_context.fingerprint() if future_context is not None else ""
        ),
        starting_state_fingerprint=_sha256_of(carry_in.to_dict()),
        evaluation_context_fingerprint=evaluation_context.fingerprint(),
        governance_mode=governance_mode,
        artefact_kind=artefact_kind,
        resolved_governance=resolved_gov,
        governance_dependencies=governance_deps,
        activity_definitions_fingerprint=(
            activity_definitions_fingerprint(activity_definitions)
            if activity_definitions is not None
            else None
        ),
        cost_mapping_fingerprint=(
            cost_mapping_registry.fingerprint()
            if cost_mapping_registry is not None
            else None
        ),
        counterfactual_policy_fingerprint=(
            counterfactual_policy.fingerprint()
            if counterfactual_policy is not None
            else ""
        ),
        economics_coverage=economics_coverage,
        planning_semantics=planning_semantics,
        warnings=tuple(warnings),
    )


def sequential_scenario_to_dict(
    name: str,
    result: SequentialScenarioEvaluationResult,
    *,
    notes: str = "",
) -> Dict[str, Any]:
    """Build the persisted-scenario dict for a saved sequential-weekly
    scenario (WP5 part 4) - appended to the SAME `scenarios` list a
    steady-state scenario is (`core.optimization.scenario_to_dict`), not a
    separate parallel list, so the existing save/export/staleness
    machinery (`core.persistence.export_project`'s generic scenario
    serialization; the Scenario Planner page's cost-mapping/
    counterfactual-policy staleness loop, which reads only
    `governance_dependencies` - never `predicted`) already handles it
    without modification. `calculation_method="sequential_weekly"` is the
    discriminator `core.optimization.scenario_from_dict` checks to skip
    steady-state-specific legacy migration for this shape - a genuinely
    new schema starting now, with nothing to migrate from.

    `sequential_evaluation` holds the full `SequentialScenarioEvaluation
    Result.to_dict()` - every array already a plain list, so the whole
    dict is directly JSON-serializable with no special-casing in
    `export_project`. This dict has no `predicted` key (steady-state's
    DataFrame result) - `core.optimization.compare_scenarios` requires
    one, so callers must filter scenarios by `calculation_method` before
    comparing, never pass this dict to it directly."""
    return {
        "name": name,
        "market": result.market,
        "calculation_method": result.calculation_method,
        "notes": notes,
        "governance_mode": result.governance_mode,
        "governance_dependencies": (
            result.governance_dependencies.to_dict()
            if result.governance_dependencies is not None
            else None
        ),
        "sequential_evaluation": result.to_dict(),
        "schema_version": 1,
    }


__all__ = [
    "MARKET_SPECIFIC_MODEL_TYPE",
    "SequentialScenarioEvaluationError",
    "SequentialScenarioEvaluationResult",
    "evaluate_manual_scenario_sequential",
    "sequential_scenario_to_dict",
]
