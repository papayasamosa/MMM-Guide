"""Tests for `ancestry_mmm.core.baseline_diagnostics` (Decision 15
resolution + diagnostic-only residual-shift detector). See
`docs/time_varying_baseline_decision_record.md` for the decisions these
tests verify."""

import numpy as np
import pytest

from ancestry_mmm.core.baseline_diagnostics import (
    BASELINE_PROCESS_DECISION,
    BASELINE_PROJECTION_DECISION,
    ResidualShiftDiagnostic,
    detect_residual_level_shift,
)


class TestGovernedDecisionConstants:
    def test_process_decision_is_t3(self):
        assert BASELINE_PROCESS_DECISION == "T3_no_new_process_trend_fourier_sufficient"

    def test_projection_decision_is_p1(self):
        assert BASELINE_PROJECTION_DECISION == "P1_no_planning_use"


class TestDetectResidualLevelShift:
    def test_detects_a_genuine_step_shift(self):
        rng = np.random.default_rng(42)
        before = rng.normal(0, 1.0, size=100)
        after = rng.normal(10.0, 1.0, size=100)  # large, obvious shift
        residuals = np.concatenate([before, after])
        result = detect_residual_level_shift(residuals, breakpoint_index=100)
        assert result.shift_detected is True
        assert result.shift_magnitude > 5.0

    def test_no_shift_in_stationary_noise(self):
        rng = np.random.default_rng(7)
        residuals = rng.normal(0, 1.0, size=200)
        result = detect_residual_level_shift(residuals, breakpoint_index=100)
        assert result.shift_detected is False

    def test_result_carries_disclaimer_and_is_never_a_bare_boolean(self):
        residuals = np.zeros(10)
        result = detect_residual_level_shift(residuals, breakpoint_index=5)
        assert result.disclaimer
        assert isinstance(result.to_dict(), dict)

    def test_round_trip(self):
        residuals = np.array([1.0, 2.0, 3.0, 10.0, 11.0, 12.0])
        original = detect_residual_level_shift(residuals, breakpoint_index=3)
        restored = ResidualShiftDiagnostic.from_dict(original.to_dict())
        assert restored == original

    def test_rejects_breakpoint_at_edge(self):
        residuals = np.zeros(10)
        with pytest.raises(ValueError, match="breakpoint_index"):
            detect_residual_level_shift(residuals, breakpoint_index=0)
        with pytest.raises(ValueError, match="breakpoint_index"):
            detect_residual_level_shift(residuals, breakpoint_index=10)

    def test_rejects_non_finite_residuals(self):
        residuals = np.array([1.0, np.nan, 3.0, 4.0])
        with pytest.raises(ValueError, match="non-finite"):
            detect_residual_level_shift(residuals, breakpoint_index=2)

    def test_rejects_non_positive_threshold(self):
        residuals = np.zeros(10)
        with pytest.raises(ValueError, match="threshold_std_devs"):
            detect_residual_level_shift(
                residuals, breakpoint_index=5, threshold_std_devs=0
            )

    def test_zero_variance_series_with_any_shift_is_detected(self):
        residuals = np.array([0.0, 0.0, 0.0, 5.0, 5.0, 5.0])
        result = detect_residual_level_shift(residuals, breakpoint_index=3)
        assert result.shift_detected is True

    def test_higher_threshold_requires_larger_shift(self):
        rng = np.random.default_rng(3)
        before = rng.normal(0, 1.0, size=50)
        after = rng.normal(2.5, 1.0, size=50)  # moderate shift
        residuals = np.concatenate([before, after])
        loose = detect_residual_level_shift(
            residuals, breakpoint_index=50, threshold_std_devs=1.0
        )
        strict = detect_residual_level_shift(
            residuals, breakpoint_index=50, threshold_std_devs=10.0
        )
        assert loose.shift_detected is True
        assert strict.shift_detected is False
