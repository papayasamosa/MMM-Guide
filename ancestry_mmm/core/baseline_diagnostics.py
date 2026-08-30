"""Time-varying latent baseline decision resolution and a bounded,
diagnostic-only residual-shift detector (`REQ-BASELINE-001`; Decision 15
of the "Post-UI/UX Implementation Instructions: Approved Business
Decisions" brief).

See `docs/time_varying_baseline_decision_record.md` for the full
options-considered decision record (why T3/P1 were selected, and why
T1/T2 were rejected).

Summary (see the decision record for full reasoning):

1. `BASELINE_PROCESS_DECISION = "T3_no_new_process_trend_fourier_
   sufficient"`: no new time-varying-intercept statistical process is
   introduced. `core.hierarchical_model`/`core.market_specific_model`'s
   existing static per-market/outcome intercept, combined with their
   already-fitted trend/Fourier terms (already forward-projected by
   `core.planning.future_context`), already satisfies `AGENTS.md` role
   #5's practical planning intent. Neither module is modified by this
   record.
2. `BASELINE_PROJECTION_DECISION = "P1_no_planning_use"`: no planning
   surface (`core.planning.future_context`, `core.sequential_
   simulation`, `core.optimization`) reads any baseline-shift signal.
3. T1 (a Hilbert Space Gaussian Process time-varying intercept,
   `pymc-marketing`'s built-in `time_varying_intercept=True`) is rejected
   for planning use - upstream's own documentation states this component
   "reverts to \\[its] prior mean and exhibit\\[s] rapidly growing
   uncertainty beyond the training data window" and recommends trend/
   Fourier continuation instead for anything beyond a short forecast
   horizon.
4. T2 (a new latent random-walk-style baseline process) is rejected FOR
   NOW, not permanently - no valid `REQ-LATENT-001` identifying strategy
   exists for a generic baseline-shift latent state (unlike Candidate
   A's Google-Trends-anchored demand state), so any T2 implementation
   would fail `REQ-LATENT-001`'s existing fail-closed use-eligibility
   gate regardless of its own fit quality. This is an already-approved
   governance blocker, not a preference call.

This module implements ONLY a small, bounded, opt-in, strictly
diagnostic-only utility (`detect_residual_level_shift`) that a caller may
use to check whether an already-fitted model's residuals suggest an
unexplained demand-level shift worth human investigation (e.g. a
competitor launch or a pandemic-style shock) - it is NEVER wired into
any causal pathway, planning surface, or official-use gate, and it does
NOT constitute or require T2's identification resolution, since a pure
diagnostic never enters a causal pathway or official use
(`REQ-LATENT-001`'s Requirement 1 applies only to a state that DOES).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence, cast

import numpy as np

BASELINE_DIAGNOSTICS_SCHEMA_VERSION = 1

BASELINE_PROCESS_DECISION = "T3_no_new_process_trend_fourier_sufficient"
BASELINE_PROJECTION_DECISION = "P1_no_planning_use"

RESIDUAL_SHIFT_DIAGNOSTIC_DISCLAIMER = (
    "This is a bounded, diagnostic-only signal computed from caller-"
    "supplied residuals - it is never read by any planning, scenario, or "
    "optimisation surface, and a detected shift is evidence for a human "
    "to investigate (e.g. a competitor launch or market shock), never an "
    "automatically-modelled causal effect. It does not identify, quantify, "
    "or attribute the shift's cause, and it is not a substitute for "
    "REQ-LATENT-001's identifying-strategy requirement, which this "
    "diagnostic does not attempt to satisfy because it never enters a "
    "causal pathway."
)


@dataclass(frozen=True)
class ResidualShiftDiagnostic:
    """One diagnostic result for `detect_residual_level_shift` - never a
    bare boolean, always disclosed."""

    breakpoint_index: int
    mean_before: float
    mean_after: float
    shift_magnitude: float
    shift_detected: bool
    threshold_std_devs: float
    disclaimer: str = RESIDUAL_SHIFT_DIAGNOSTIC_DISCLAIMER
    schema_version: int = BASELINE_DIAGNOSTICS_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "ResidualShiftDiagnostic":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


def detect_residual_level_shift(
    residuals: Sequence[float] | np.ndarray,
    *,
    breakpoint_index: int,
    threshold_std_devs: float = 2.0,
) -> ResidualShiftDiagnostic:
    """Diagnostic-only two-sample mean-shift check on a caller-supplied
    residual series (e.g. `actual - fitted` from an already-fitted trend/
    Fourier/media model), split at `breakpoint_index`. `shift_detected`
    is `True` when the absolute difference in before/after means exceeds
    `threshold_std_devs` times the pooled residual standard deviation - a
    simple, transparent, disclosed heuristic, not a formal changepoint
    test or a claim of statistical significance.

    This function never fits a model, never proposes a cause for a
    detected shift, and is never called by any planning/optimisation
    code in this repository (decision T3/P1, see module docstring).
    """
    array = np.asarray(residuals, dtype=float)
    if array.ndim != 1:
        raise ValueError("detect_residual_level_shift requires a 1D residual series.")
    if not np.all(np.isfinite(array)):
        raise ValueError(
            "detect_residual_level_shift: residuals contain non-finite values."
        )
    if not (0 < breakpoint_index < len(array)):
        raise ValueError(
            "detect_residual_level_shift: breakpoint_index must be strictly "
            "between 0 and len(residuals)."
        )
    if threshold_std_devs <= 0:
        raise ValueError(
            "detect_residual_level_shift: threshold_std_devs must be positive."
        )

    before = array[:breakpoint_index]
    after = array[breakpoint_index:]
    mean_before = float(np.mean(before))
    mean_after = float(np.mean(after))
    # Pooled WITHIN-group standard deviation (standard two-sample formula) -
    # deliberately NOT the naive whole-series std, which would include the
    # between-group mean difference itself and inflate the denominator,
    # masking exactly the shift this function exists to detect.
    n_before, n_after = len(before), len(after)
    var_before = float(np.var(before, ddof=1)) if n_before > 1 else 0.0
    var_after = float(np.var(after, ddof=1)) if n_after > 1 else 0.0
    dof = n_before + n_after - 2
    pooled_std = (
        float(np.sqrt(((n_before - 1) * var_before + (n_after - 1) * var_after) / dof))
        if dof > 0
        else 0.0
    )
    shift_magnitude = abs(mean_after - mean_before)

    if pooled_std <= 0:
        shift_detected = shift_magnitude > 0
    else:
        shift_detected = shift_magnitude > threshold_std_devs * pooled_std

    return ResidualShiftDiagnostic(
        breakpoint_index=breakpoint_index,
        mean_before=mean_before,
        mean_after=mean_after,
        shift_magnitude=shift_magnitude,
        shift_detected=shift_detected,
        threshold_std_devs=threshold_std_devs,
    )
