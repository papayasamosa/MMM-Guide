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

This module does NOT modify `core.optimization.py`, `core.sequential_
simulation.py`, or `core.sequential_scenario_evaluation.py` - it
implements the governed decision constants, the preserved benchmark
evidence, and a reusable O1 objective-value helper function only. Wiring
this into `core.optimization`'s actual SLSQP call sites (bounds/
constraints translation, `REQ-OPT-001`'s objective-kind vocabulary) is a
separate, substantial engineering integration requiring its own
end-to-end validation, not attempted here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Mapping, Tuple, cast

from .predict import FHPosteriorParams
from .sequential_simulation import (
    SequentialCarryInState,
    WeeklyPlan,
    compute_incremental_outcome,
    simulate_sequential_outcomes,
)

if TYPE_CHECKING:
    from .hierarchical_model import FHModelMeta

SEQUENTIAL_OPTIMISATION_SCHEMA_VERSION = 1

SEQUENTIAL_OPTIMISATION_TRACTABILITY_STRATEGY = "T1_direct_replay_point_estimate"
SEQUENTIAL_OPTIMISATION_OBJECTIVE_HORIZON = "O1_plan_window_total"
SEQUENTIAL_OPTIMISATION_SEARCH_IS_POSTERIOR_AWARE = False


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
) -> float:
    """The O1 (`plan_window_total`) objective value for one candidate
    plan: the sum, across every week and outcome in the plan window, of
    `candidate - reference` incremental outcome, computed via the exact
    sequential kernel at point-estimate parameters (decision T1/O1).

    This is the function a future `core.optimization` integration would
    call as its SLSQP objective (after negating for maximisation, as
    `core.optimization`'s existing steady-state objective already does)
    - it is not itself wired into `core.optimization` by this module.
    `candidate_plan` and `reference_plan` must share the same `carry_in`
    (the same starting state) - this is the caller's responsibility,
    mirroring `compute_incremental_outcome`'s own existing contract.
    """
    candidate_result = simulate_sequential_outcomes(
        candidate_plan, carry_in, meta, params
    )
    reference_result = simulate_sequential_outcomes(
        reference_plan, carry_in, meta, params
    )
    incremental = compute_incremental_outcome(candidate_result, reference_result)
    return float(incremental.sum())
