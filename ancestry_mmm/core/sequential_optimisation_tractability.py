"""Sequential-weekly optimisation tractability resolution (`REQ-SCEN-004`;
Decision 16 of the "Post-UI/UX Implementation Instructions: Approved
Business Decisions" brief).

See `docs/sequential_optimisation_tractability_decision_record.md` for
the full options-considered decision record, including the actual
benchmark methodology and measured figures this decision relies on.

Summary (see the decision record for full reasoning):

1. Tractability: `T1_direct_replay_point_estimate` - the exact
   sequential kernel (`core.sequential_simulation.simulate_sequential_
   outcomes` + `compute_incremental_outcome`), at point-estimate
   parameters, called directly inside a numerical search loop. Selected
   because a real benchmark measured per-call cost of 0.3-0.5 ms at
   realistic plan sizes (6-10 channels, up to a 52-week plan window) -
   extrapolating to under 8 seconds total for a demanding 100-iteration
   SLSQP run, directly contradicting the "may be too slow for
   interactive use" concern the decision package itself raised. A
   finite-difference gradient-smoothness check also found no numerical
   noise, contradicting that package's separate hypothesis.
2. Objective horizon: `O1_plan_window_total` - sum of weekly incremental
   outcome across the full plan window, the direct sequential analogue
   of steady-state's existing per-month-sum objective. Requires no new
   business input (unlike a short/long-horizon weighting, which would).
3. Search is NOT posterior-aware
   (`SEQUENTIAL_OPTIMISATION_SEARCH_IS_POSTERIOR_AWARE = False`) -
   point-estimate parameters drive the search; posterior uncertainty for
   the final chosen plan is computed once, as a separate, opt-in step,
   mirroring the manual Scenario Planner tab's own already-established
   pattern.

The reusable objective/pair helpers are the numerical boundary consumed by
`core.optimization`'s sequential SLSQP path. Bounds, constraints, phasing,
future assumptions, and governance remain owned by their existing callers;
this module does not duplicate those concerns or replace the steady-state
path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, Tuple, cast

import numpy as np

from .predict import FHPosteriorParams
from .sequential_simulation import (
    SequentialCarryInState,
    WeeklyPlan,
    compute_incremental_outcome,
    simulate_sequential_outcomes,
    simulate_sequential_outcomes_market_specific,
)

if TYPE_CHECKING:
    from .hierarchical_model import FHModelMeta
    from .market_specific_predict import FHMarketSpecificPosteriorParams
    from .named_event_fit_inputs import NamedEventFitInputs

SEQUENTIAL_OPTIMISATION_SCHEMA_VERSION = 1

SEQUENTIAL_OPTIMISATION_TRACTABILITY_STRATEGY = "T1_direct_replay_point_estimate"
SEQUENTIAL_OPTIMISATION_OBJECTIVE_HORIZON = "O1_plan_window_total"
SEQUENTIAL_OPTIMISATION_SEARCH_IS_POSTERIOR_AWARE = False


@dataclass(frozen=True)
class SequentialOptimisationContext:
    """Fixed context shared by every candidate in a sequential search.

    The optimiser owns the numerical search, while the caller owns the
    already-governed monthly-to-weekly plan construction.  ``candidate_plan``
    therefore receives the candidate in the caller's plan units (normally
    monetary decisions plus response-only quantities) and must return a
    ``WeeklyPlan`` using the same canonical weeks as ``reference_plan``.
    Keeping this boundary explicit prevents the optimiser from creating a
    second phasing, cost-mapping, or future-assumption implementation.
    """

    reference_plan: WeeklyPlan
    candidate_plan: Callable[[Mapping[str, Mapping[str, float]]], WeeklyPlan]
    carry_in: SequentialCarryInState
    model_type: str = "shared"
    named_event_fit_inputs: Optional["NamedEventFitInputs"] = None


@dataclass(frozen=True)
class SequentialKernelBenchmarkEvidence:
    """One preserved benchmark measurement from
    `docs/sequential_optimisation_tractability_decision_record.md` -
    structured, not only narrative prose, so a future session can see
    exactly what was measured and re-run/update it."""

    n_channels: int
    n_future_weeks: int
    mean_seconds_per_call: float
    p95_seconds_per_call: float
    extrapolated_total_seconds_by_iterations: Mapping[int, float]
    measured_on: str
    schema_version: int = SEQUENTIAL_OPTIMISATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.n_channels <= 0:
            raise ValueError(
                "SequentialKernelBenchmarkEvidence.n_channels must be positive."
            )
        if self.n_future_weeks <= 0:
            raise ValueError(
                "SequentialKernelBenchmarkEvidence.n_future_weeks must be positive."
            )
        if self.mean_seconds_per_call < 0 or self.p95_seconds_per_call < 0:
            raise ValueError(
                "SequentialKernelBenchmarkEvidence timing fields cannot be negative."
            )
        if not self.measured_on:
            raise ValueError(
                "SequentialKernelBenchmarkEvidence requires measured_on "
                "(when/where this was measured - never left implicit)."
            )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["extrapolated_total_seconds_by_iterations"] = dict(
            self.extrapolated_total_seconds_by_iterations
        )
        return payload

    @classmethod
    def from_dict(
        cls, values: Mapping[str, Any]
    ) -> "SequentialKernelBenchmarkEvidence":
        payload = dict(values)
        if "extrapolated_total_seconds_by_iterations" in payload:
            payload["extrapolated_total_seconds_by_iterations"] = {
                int(k): float(v)
                for k, v in (
                    payload["extrapolated_total_seconds_by_iterations"] or {}
                ).items()
            }
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in payload.items() if k in known}))


# The three benchmark configurations recorded in the decision record,
# preserved here as structured evidence.
BENCHMARK_EVIDENCE: Tuple[SequentialKernelBenchmarkEvidence, ...] = (
    SequentialKernelBenchmarkEvidence(
        n_channels=6,
        n_future_weeks=12,
        mean_seconds_per_call=0.000337,
        p95_seconds_per_call=0.000515,
        extrapolated_total_seconds_by_iterations={20: 0.13, 50: 0.32, 100: 0.64},
        measured_on="2026-08-30 session development machine",
    ),
    SequentialKernelBenchmarkEvidence(
        n_channels=6,
        n_future_weeks=52,
        mean_seconds_per_call=0.000398,
        p95_seconds_per_call=0.000478,
        extrapolated_total_seconds_by_iterations={20: 1.60, 50: 4.00, 100: 7.99},
        measured_on="2026-08-30 session development machine",
    ),
    SequentialKernelBenchmarkEvidence(
        n_channels=10,
        n_future_weeks=52,
        mean_seconds_per_call=0.000494,
        p95_seconds_per_call=0.000521,
        extrapolated_total_seconds_by_iterations={20: 1.60, 50: 4.00, 100: 7.99},
        measured_on="2026-08-30 session development machine",
    ),
)


def compute_sequential_plan_objective_value(
    candidate_plan: WeeklyPlan,
    reference_plan: WeeklyPlan,
    carry_in: SequentialCarryInState,
    meta: "FHModelMeta",
    params: FHPosteriorParams,
    *,
    model_type: str = "shared",
    outcome_weights: Optional[Mapping[str, float]] = None,
    named_event_fit_inputs: Optional["NamedEventFitInputs"] = None,
    incremental: bool = True,
) -> float:
    """The O1 (`plan_window_total`) objective value for one candidate
    plan: the sum, across every week and outcome in the plan window, of
    `candidate - reference` incremental outcome, computed via the exact
    sequential kernel at point-estimate parameters (decision T1/O1). Set
    ``incremental=False`` for the legacy total-outcome objective semantics,
    where the candidate response is summed directly.

    This is the function a future `core.optimization` integration would
    call as its SLSQP objective (after negating for maximisation, as
    `core.optimization`'s existing steady-state objective already does)
    - `core.optimization` calls it after the caller has supplied a governed
      weekly candidate/reference context.
    `candidate_plan` and `reference_plan` must share the same `carry_in`
    (the same starting state) - this is the caller's responsibility,
    mirroring `compute_incremental_outcome`'s own existing contract.
    """
    if model_type == "market_specific":
        candidate_result = simulate_sequential_outcomes_market_specific(
            candidate_plan,
            carry_in,
            meta,
            cast("FHMarketSpecificPosteriorParams", params),
            named_event_fit_inputs=named_event_fit_inputs,
        )
        reference_result = simulate_sequential_outcomes_market_specific(
            reference_plan,
            carry_in,
            meta,
            cast("FHMarketSpecificPosteriorParams", params),
            named_event_fit_inputs=named_event_fit_inputs,
        )
    else:
        candidate_result = simulate_sequential_outcomes(
            candidate_plan,
            carry_in,
            meta,
            params,
            named_event_fit_inputs=named_event_fit_inputs,
        )
        reference_result = simulate_sequential_outcomes(
            reference_plan,
            carry_in,
            meta,
            params,
            named_event_fit_inputs=named_event_fit_inputs,
        )
    incremental_result = compute_incremental_outcome(candidate_result, reference_result)
    values = incremental_result if incremental else candidate_result.mu
    if outcome_weights is None:
        return float(values.sum())
    missing = set(candidate_result.outcome_ids) - set(outcome_weights)
    if missing:
        raise ValueError(
            "Sequential outcome weights must include every fitted outcome; "
            f"missing {sorted(missing)}."
        )
    return float(
        (
            np.asarray(values, dtype=float)
            @ np.asarray(
                [float(outcome_weights[oid]) for oid in candidate_result.outcome_ids]
            )
        ).sum()
    )


def compute_sequential_plan_pair(
    candidate_plan: WeeklyPlan,
    reference_plan: WeeklyPlan,
    carry_in: SequentialCarryInState,
    meta: "FHModelMeta",
    params: FHPosteriorParams,
    *,
    model_type: str = "shared",
    named_event_fit_inputs: Optional["NamedEventFitInputs"] = None,
):
    """Evaluate a candidate/reference pair through the exact weekly kernel.

    This small shared helper lets optimisation and final governed evaluation
    use identical replay inputs without introducing a planning-only shortcut.
    """
    if model_type == "market_specific":
        typed_params = cast("FHMarketSpecificPosteriorParams", params)
        candidate = simulate_sequential_outcomes_market_specific(
            candidate_plan,
            carry_in,
            meta,
            typed_params,
            named_event_fit_inputs=named_event_fit_inputs,
        )
        reference = simulate_sequential_outcomes_market_specific(
            reference_plan,
            carry_in,
            meta,
            typed_params,
            named_event_fit_inputs=named_event_fit_inputs,
        )
    else:
        candidate = simulate_sequential_outcomes(
            candidate_plan,
            carry_in,
            meta,
            params,
            named_event_fit_inputs=named_event_fit_inputs,
        )
        reference = simulate_sequential_outcomes(
            reference_plan,
            carry_in,
            meta,
            params,
            named_event_fit_inputs=named_event_fit_inputs,
        )
    return candidate, reference, compute_incremental_outcome(candidate, reference)


__all__ = [
    "BENCHMARK_EVIDENCE",
    "SEQUENTIAL_OPTIMISATION_OBJECTIVE_HORIZON",
    "SEQUENTIAL_OPTIMISATION_SCHEMA_VERSION",
    "SEQUENTIAL_OPTIMISATION_SEARCH_IS_POSTERIOR_AWARE",
    "SEQUENTIAL_OPTIMISATION_TRACTABILITY_STRATEGY",
    "SequentialKernelBenchmarkEvidence",
    "SequentialOptimisationContext",
    "compute_sequential_plan_objective_value",
    "compute_sequential_plan_pair",
]
