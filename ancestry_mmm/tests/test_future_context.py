"""Tests for core.planning.future_context (REQ-SCEN-002, Work Package 4 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR262`)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.planning.future_context import (
    EXPLORATORY_MODE,
    OFFICIAL_MODE,
    FutureContextError,
    build_future_context,
    continue_fourier,
    continue_trend,
)


class TestContinueTrendMatchesFitTimeDefinition:
    """`data.preprocessor.prepare_fh_modeling_frame` defines trend per
    market as `np.arange(n) / max(n - 1, 1)` over that market's own
    historical row count `n`. `continue_trend` must extend that exact
    formula, not a rescaled or reset one."""

    def test_continuation_matches_extending_the_original_arange(self):
        n_hist = 20
        n_future = 5
        historical_trend = np.arange(n_hist) / max(n_hist - 1, 1)
        future_trend = continue_trend(n_hist, n_future)
        expected_full = np.arange(n_hist + n_future) / max(n_hist - 1, 1)
        np.testing.assert_allclose(
            np.concatenate([historical_trend, future_trend]), expected_full
        )

    def test_continues_past_one_rather_than_resetting_or_holding_flat(self):
        future_trend = continue_trend(historical_n_weeks=11, n_future_weeks=3)
        # historical denom = max(11-1, 1) = 10; positions 11,12,13 -> 1.1,1.2,1.3
        np.testing.assert_allclose(future_trend, [1.1, 1.2, 1.3])

    def test_single_historical_week_denominator_is_one(self):
        future_trend = continue_trend(historical_n_weeks=1, n_future_weeks=2)
        np.testing.assert_allclose(future_trend, [1.0, 2.0])

    def test_rejects_non_positive_historical_n(self):
        with pytest.raises(FutureContextError, match="historical_n_weeks"):
            continue_trend(historical_n_weeks=0, n_future_weeks=3)

    def test_rejects_non_positive_future_n(self):
        with pytest.raises(FutureContextError, match="n_future_weeks"):
            continue_trend(historical_n_weeks=5, n_future_weeks=0)


class TestContinueFourierMatchesFitTimeDefinition:
    def test_matches_data_preprocessor_helper_directly(self):
        from ancestry_mmm.data.preprocessor import create_fourier_features_from_calendar

        weeks = pd.date_range("2026-01-05", periods=10, freq="7D").strftime("%Y-%m-%d")
        expected = create_fourier_features_from_calendar(
            pd.Series(weeks), period_days=365.25, n_harmonics=3
        )
        actual = continue_fourier(list(weeks), n_harmonics=3)
        np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)

    def test_shape_is_two_times_harmonics(self):
        weeks = pd.date_range("2026-01-05", periods=4, freq="7D").strftime("%Y-%m-%d")
        result = continue_fourier(list(weeks), n_harmonics=3)
        assert result.shape == (4, 6)

    def test_rejects_empty_period_labels(self):
        with pytest.raises(FutureContextError, match="period_labels"):
            continue_fourier([], n_harmonics=3)


def _weeks(n=4, start="2026-06-01"):
    return tuple(
        pd.date_range(start, periods=n, freq="7D").strftime("%Y-%m-%d").tolist()
    )


class TestBuildFutureContextPromo:
    def test_promo_requires_explicit_value_every_week_in_official_mode(self):
        weeks = _weeks()
        with pytest.raises(FutureContextError, match="promo"):
            build_future_context(
                market="UK",
                period_labels=weeks,
                historical_n_weeks=20,
                n_fourier_harmonics=3,
                outcome_ids=("New",),
                mode=OFFICIAL_MODE,
                promo_future={"New": {w: 0.0 for w in weeks[:-1]}},  # missing last week
            )

    def test_promo_requires_explicit_value_even_in_exploratory_mode(self):
        # REQ-SCEN-002: no hold_last_observed relaxation for promotions.
        weeks = _weeks()
        with pytest.raises(FutureContextError, match="promo"):
            build_future_context(
                market="UK",
                period_labels=weeks,
                historical_n_weeks=20,
                n_fourier_harmonics=3,
                outcome_ids=("New",),
                mode=EXPLORATORY_MODE,
                promo_future={},
            )

    def test_promo_missing_outcome_entirely_raises(self):
        weeks = _weeks()
        with pytest.raises(FutureContextError, match="promo_future"):
            build_future_context(
                market="UK",
                period_labels=weeks,
                historical_n_weeks=20,
                n_fourier_harmonics=3,
                outcome_ids=("New", "DNA_CrossSell"),
                mode=OFFICIAL_MODE,
                promo_future={"New": {w: 0.0 for w in weeks}},  # DNA_CrossSell missing
            )

    def test_complete_promo_succeeds(self):
        weeks = _weeks()
        result = build_future_context(
            market="UK",
            period_labels=weeks,
            historical_n_weeks=20,
            n_fourier_harmonics=3,
            outcome_ids=("New",),
            mode=OFFICIAL_MODE,
            promo_future={"New": {w: 1.5 for w in weeks}},
        )
        np.testing.assert_allclose(result.promo[:, 0], 1.5)
        assert result.is_decision_ready


class TestBuildFutureContextControls:
    def test_official_mode_missing_control_raises(self):
        weeks = _weeks()
        with pytest.raises(FutureContextError, match="CPI"):
            build_future_context(
                market="UK",
                period_labels=weeks,
                historical_n_weeks=20,
                n_fourier_harmonics=3,
                outcome_ids=("New",),
                control_names=("CPI",),
                mode=OFFICIAL_MODE,
                promo_future={"New": {w: 0.0 for w in weeks}},
                control_future={},
            )

    def test_exploratory_mode_missing_control_still_raises_without_explicit_opt_in(
        self,
    ):
        weeks = _weeks()
        with pytest.raises(FutureContextError, match="hold_last_observed"):
            build_future_context(
                market="UK",
                period_labels=weeks,
                historical_n_weeks=20,
                n_fourier_harmonics=3,
                outcome_ids=("New",),
                control_names=("CPI",),
                mode=EXPLORATORY_MODE,
                promo_future={"New": {w: 0.0 for w in weeks}},
                control_future={},
                eligible_for_hold_last_observed=frozenset({"CPI"}),
                last_observed_controls={"CPI": 108.0},
                # hold_last_observed not set - must still raise
            )

    def test_exploratory_hold_last_observed_succeeds_and_is_flagged_not_decision_ready(
        self,
    ):
        weeks = _weeks()
        result = build_future_context(
            market="UK",
            period_labels=weeks,
            historical_n_weeks=20,
            n_fourier_harmonics=3,
            outcome_ids=("New",),
            control_names=("CPI",),
            mode=EXPLORATORY_MODE,
            promo_future={"New": {w: 0.0 for w in weeks}},
            control_future={},
            eligible_for_hold_last_observed=frozenset({"CPI"}),
            hold_last_observed=frozenset({"CPI"}),
            last_observed_controls={"CPI": 108.0},
        )
        np.testing.assert_allclose(result.X_controls[:, 0], 108.0)
        assert not result.is_decision_ready
        assumption = next(a for a in result.control_assumptions if a.name == "CPI")
        assert assumption.assumption == "hold_last_observed"
        assert not assumption.is_decision_ready

    def test_ineligible_control_cannot_use_hold_last_observed_even_if_requested(self):
        weeks = _weeks()
        with pytest.raises(FutureContextError, match="not eligible"):
            build_future_context(
                market="UK",
                period_labels=weeks,
                historical_n_weeks=20,
                n_fourier_harmonics=3,
                outcome_ids=("New",),
                control_names=("CPI",),
                mode=EXPLORATORY_MODE,
                promo_future={"New": {w: 0.0 for w in weeks}},
                control_future={},
                eligible_for_hold_last_observed=frozenset(),  # not eligible
                hold_last_observed=frozenset({"CPI"}),
                last_observed_controls={"CPI": 108.0},
            )

    def test_explicit_control_future_takes_priority_and_is_decision_ready(self):
        weeks = _weeks()
        result = build_future_context(
            market="UK",
            period_labels=weeks,
            historical_n_weeks=20,
            n_fourier_harmonics=3,
            outcome_ids=("New",),
            control_names=("CPI",),
            mode=OFFICIAL_MODE,
            promo_future={"New": {w: 0.0 for w in weeks}},
            control_future={"CPI": {w: 110.0 for w in weeks}},
        )
        np.testing.assert_allclose(result.X_controls[:, 0], 110.0)
        assert result.is_decision_ready

    def test_outcome_specific_controls_use_qualified_name(self):
        weeks = _weeks()
        with pytest.raises(FutureContextError, match=r"New\.own_promo_flag"):
            build_future_context(
                market="UK",
                period_labels=weeks,
                historical_n_weeks=20,
                n_fourier_harmonics=3,
                outcome_ids=("New",),
                outcome_control_names={"New": ("own_promo_flag",)},
                mode=OFFICIAL_MODE,
                promo_future={"New": {w: 0.0 for w in weeks}},
                outcome_control_future={},
            )


class TestFutureContextFingerprint:
    def _result(self, **overrides):
        weeks = _weeks()
        kwargs = dict(
            market="UK",
            period_labels=weeks,
            historical_n_weeks=20,
            n_fourier_harmonics=3,
            outcome_ids=("New",),
            mode=OFFICIAL_MODE,
            promo_future={"New": {w: 0.0 for w in weeks}},
        )
        kwargs.update(overrides)
        return build_future_context(**kwargs)

    def test_stable_for_identical_input(self):
        assert self._result().fingerprint() == self._result().fingerprint()

    def test_changes_when_a_future_control_value_changes(self):
        weeks = _weeks()
        a = self._result(
            control_names=("CPI",),
            control_future={"CPI": {w: 100.0 for w in weeks}},
        )
        b = self._result(
            control_names=("CPI",),
            control_future={"CPI": {w: 200.0 for w in weeks}},
        )
        assert a.fingerprint() != b.fingerprint()

    def test_changes_when_mode_changes_the_realized_assumption(self):
        # Same explicit CPI value under both modes actually has the same
        # fingerprint content (assumption metadata is "explicit" either
        # way) - the fingerprint must instead change when the underlying
        # *assumption* differs, e.g. explicit vs hold_last_observed
        # producing the same numeric value by coincidence.
        weeks = _weeks()
        explicit = self._result(
            control_names=("CPI",),
            control_future={"CPI": {w: 108.0 for w in weeks}},
        )
        held = self._result(
            control_names=("CPI",),
            mode=EXPLORATORY_MODE,
            control_future={},
            eligible_for_hold_last_observed=frozenset({"CPI"}),
            hold_last_observed=frozenset({"CPI"}),
            last_observed_controls={"CPI": 108.0},
        )
        np.testing.assert_allclose(explicit.X_controls, held.X_controls)
        assert explicit.fingerprint() != held.fingerprint()
