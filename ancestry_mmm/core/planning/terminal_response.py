"""
Terminal candidate/reference evaluator (Work Package 4 of `Media-Mix-Lab:
Coding LLM Next Steps Post PR262`, brief §5.7/§10.3).

`core.sequential_simulation.zero_media_extension_plan` is a low-level decay
fixture (zero future media AND zero promo/trend/Fourier/controls) - correct
for isolating pure adstock decay in a unit test, but not a business-facing
terminal-response definition: an application asking "what residual value
carries forward after the formal plan window ends" needs the SAME real
future non-decision context (trend, seasonality, controls, promotions) a
candidate/reference pair uses for the plan window itself, with only the
*decision* (future media) held at zero for the initial residual-carryover
policy - never a context artificially zeroed to nothing.

This module builds that extension plan from a real `FutureContextResult`
(never `zero_media_extension_plan`'s all-zero context), evaluates
candidate and reference through the SAME simulator sharing that ONE future
non-decision context, and reports the incremental terminal response as a
structurally separate, typed result - never merged into a plan-window
`SequentialSimulationResult` or an optimisation objective
(`core.sequential_simulation.simulate_terminal_carryover`'s own docstring:
"Returns a SEPARATE... report it separately").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..hierarchical_model import FHModelMeta
from ..market_specific_predict import FHMarketSpecificPosteriorParams
from ..predict import FHPosteriorParams
from ..sequential_simulation import (
    SequentialCarryInState,
    SequentialSimulationResult,
    WeeklyPlan,
    compute_incremental_outcome,
    simulate_terminal_carryover,
    simulate_terminal_carryover_market_specific,
)
from ..named_event_fit_inputs import NamedEventFitInputs
from .future_context import FutureContextResult


class TerminalResponseError(ValueError):
    """Raised when a terminal extension plan/evaluation cannot be built
    safely - e.g. a mismatched market between the requested evaluation and
    the supplied future context."""


def build_zero_decision_terminal_extension_plan(
    market: str,
    channels: Sequence[str],
    future_context: FutureContextResult,
    candidate_a_paid_search_cap: Optional[np.ndarray] = None,
) -> WeeklyPlan:
    """The terminal-carryover extension plan for the initial residual-
    carryover policy: every channel's future media is set to zero (the
    *decision*), but every non-decision term (trend, Fourier, promo,
    controls) is taken from `future_context` unchanged - never zeroed."""
    if future_context.market != market:
        raise TerminalResponseError(
            f"future_context.market ({future_context.market!r}) does not "
            f"match the requested market ({market!r})."
        )
    n_weeks = len(future_context.period_labels)
    return WeeklyPlan(
        market=market,
        period_labels=future_context.period_labels,
        media_by_channel={c: np.zeros(n_weeks) for c in channels},
        promo=future_context.promo,
        trend=future_context.trend,
        fourier=future_context.fourier,
        control_names=future_context.control_names,
        X_controls=(
            future_context.X_controls if future_context.control_names else None
        ),
        outcome_controls=future_context.outcome_controls,
        outcome_control_names={
            oid: list(names)
            for oid, names in future_context.outcome_control_names.items()
        },
        candidate_a_paid_search_cap=candidate_a_paid_search_cap,
    )


@dataclass(frozen=True)
class TerminalIncrementalResult:
    """Terminal incremental response - candidate minus reference, both
    evaluated over the SAME zero-future-decision-media extension plan
    sharing one real future non-decision context. Structurally separate
    from any plan-window result; a caller must never fold this into a
    formal-plan response or an optimisation objective."""

    market: str
    period_labels: Tuple[str, ...]
    outcome_ids: Tuple[str, ...]
    candidate: SequentialSimulationResult
    reference: SequentialSimulationResult
    incremental: np.ndarray  # (n_weeks, n_outcomes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market": self.market,
            "period_labels": list(self.period_labels),
            "outcome_ids": list(self.outcome_ids),
            "candidate": self.candidate.to_dict(),
            "reference": self.reference.to_dict(),
            "incremental": self.incremental.tolist(),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "TerminalIncrementalResult":
        return cls(
            market=d.get("market", ""),
            period_labels=tuple(d.get("period_labels", [])),
            outcome_ids=tuple(d.get("outcome_ids", [])),
            candidate=SequentialSimulationResult.from_dict(d["candidate"]),
            reference=SequentialSimulationResult.from_dict(d["reference"]),
            incremental=np.array(d.get("incremental", [])),
        )


def evaluate_terminal_incremental_response(
    *,
    market: str,
    channels: Sequence[str],
    candidate_ending_state: SequentialCarryInState,
    reference_ending_state: SequentialCarryInState,
    future_context: FutureContextResult,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    named_event_fit_inputs: NamedEventFitInputs | None = None,
    candidate_a_paid_search_cap: Optional[np.ndarray] = None,
) -> TerminalIncrementalResult:
    """Model A (shared) terminal candidate/reference evaluation."""
    extension_plan = build_zero_decision_terminal_extension_plan(
        market,
        channels,
        future_context,
        candidate_a_paid_search_cap=candidate_a_paid_search_cap,
    )
    candidate = simulate_terminal_carryover(
        extension_plan,
        candidate_ending_state,
        meta,
        params,
        named_event_fit_inputs=named_event_fit_inputs,
        candidate_a_paid_search_cap=candidate_a_paid_search_cap,
    )
    reference = simulate_terminal_carryover(
        extension_plan,
        reference_ending_state,
        meta,
        params,
        named_event_fit_inputs=named_event_fit_inputs,
        candidate_a_paid_search_cap=candidate_a_paid_search_cap,
    )
    incremental = compute_incremental_outcome(candidate, reference)
    return TerminalIncrementalResult(
        market=market,
        period_labels=extension_plan.period_labels,
        outcome_ids=candidate.outcome_ids,
        candidate=candidate,
        reference=reference,
        incremental=incremental,
    )


def evaluate_terminal_incremental_response_market_specific(
    *,
    market: str,
    channels: Sequence[str],
    candidate_ending_state: SequentialCarryInState,
    reference_ending_state: SequentialCarryInState,
    future_context: FutureContextResult,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    named_event_fit_inputs: NamedEventFitInputs | None = None,
    candidate_a_paid_search_cap: Optional[np.ndarray] = None,
) -> TerminalIncrementalResult:
    """Model C (market-specific) mirror of
    `evaluate_terminal_incremental_response`."""
    extension_plan = build_zero_decision_terminal_extension_plan(
        market,
        channels,
        future_context,
        candidate_a_paid_search_cap=candidate_a_paid_search_cap,
    )
    candidate = simulate_terminal_carryover_market_specific(
        extension_plan,
        candidate_ending_state,
        meta,
        params,
        named_event_fit_inputs=named_event_fit_inputs,
    )
    reference = simulate_terminal_carryover_market_specific(
        extension_plan,
        reference_ending_state,
        meta,
        params,
        named_event_fit_inputs=named_event_fit_inputs,
    )
    incremental = compute_incremental_outcome(candidate, reference)
    return TerminalIncrementalResult(
        market=market,
        period_labels=extension_plan.period_labels,
        outcome_ids=candidate.outcome_ids,
        candidate=candidate,
        reference=reference,
        incremental=incremental,
    )


__all__ = [
    "TerminalIncrementalResult",
    "TerminalResponseError",
    "build_zero_decision_terminal_extension_plan",
    "evaluate_terminal_incremental_response",
    "evaluate_terminal_incremental_response_market_specific",
]
