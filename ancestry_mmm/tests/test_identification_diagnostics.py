"""Tests for core.identification_diagnostics - multicollinearity and
weak-identification diagnostics (PR G1)."""

import numpy as np
import pandas as pd
import pytest
import arviz as az

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.identification_diagnostics import (
    channel_spend_correlation_matrix,
    design_matrix_condition_number,
    high_correlation_pairs,
    identification_report,
    leave_one_channel_out_sensitivity,
    posterior_coefficient_stability,
)

OUTCOME_IDS = ["New"]
CHANNELS = ["TV", "Radio", "Search"]


def _meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], outcome_ids=OUTCOME_IDS, channels=CHANNELS,
        dna_channels=[], dna_channel_idx=[], non_dna_idx=[0, 1, 2],
        dna_outcome_id="New", dna_lag_weeks=0, unpooled_markets=[], control_names=[],
    )


class TestChannelSpendCorrelationMatrix:
    def test_identical_spend_series_are_perfectly_correlated(self):
        n = 20
        rng = np.random.default_rng(0)
        tv = rng.uniform(100, 500, n)
        frame = {"X_media": np.column_stack([tv, tv, rng.uniform(0, 100, n)])}
        corr = channel_spend_correlation_matrix(frame, _meta())
        assert corr.loc["TV", "Radio"] == pytest.approx(1.0)

    def test_independent_random_series_are_not_highly_correlated(self):
        n = 200
        rng = np.random.default_rng(1)
        frame = {"X_media": rng.uniform(0, 500, size=(n, 3))}
        corr = channel_spend_correlation_matrix(frame, _meta())
        assert abs(corr.loc["TV", "Search"]) < 0.5

    def test_diagonal_is_always_one(self):
        n = 10
        rng = np.random.default_rng(2)
        frame = {"X_media": rng.uniform(0, 500, size=(n, 3))}
        corr = channel_spend_correlation_matrix(frame, _meta())
        for ch in CHANNELS:
            assert corr.loc[ch, ch] == pytest.approx(1.0)


class TestHighCorrelationPairs:
    def test_flags_pairs_above_threshold_once_each(self):
        corr = pd.DataFrame(
            [[1.0, 0.95, 0.1], [0.95, 1.0, 0.2], [0.1, 0.2, 1.0]],
            index=CHANNELS, columns=CHANNELS,
        )
        pairs = high_correlation_pairs(corr, threshold=0.7)
        assert pairs == [("TV", "Radio", 0.95)]

    def test_no_pairs_above_threshold_returns_empty(self):
        corr = pd.DataFrame(np.eye(3), index=CHANNELS, columns=CHANNELS)
        assert high_correlation_pairs(corr, threshold=0.7) == []

    def test_negative_correlation_is_flagged_by_absolute_value(self):
        corr = pd.DataFrame(
            [[1.0, -0.9, 0.0], [-0.9, 1.0, 0.0], [0.0, 0.0, 1.0]],
            index=CHANNELS, columns=CHANNELS,
        )
        pairs = high_correlation_pairs(corr, threshold=0.7)
        assert pairs == [("TV", "Radio", -0.9)]


class TestDesignMatrixConditionNumber:
    def test_orthogonal_channels_have_a_low_condition_number(self):
        n = 100
        rng = np.random.default_rng(3)
        # Independent random columns - well-conditioned.
        X = rng.uniform(50, 500, size=(n, 3))
        cond = design_matrix_condition_number({"X_media": X})
        assert np.isfinite(cond)
        assert cond < 50

    def test_a_duplicated_channel_gives_a_very_large_condition_number(self):
        n = 50
        rng = np.random.default_rng(4)
        tv = rng.uniform(50, 500, n)
        radio = rng.uniform(0, 100, n)
        X = np.column_stack([tv, tv, radio])  # TV duplicated exactly
        cond = design_matrix_condition_number({"X_media": X})
        assert cond > 1e6

    def test_all_zero_media_gives_infinite_condition_number(self):
        X = np.zeros((10, 3))
        cond = design_matrix_condition_number({"X_media": X})
        assert cond == float("inf")


class TestPosteriorCoefficientStability:
    def _trace(self, beta_std: float) -> az.InferenceData:
        n_chain, n_draw = 2, 20
        rng = np.random.default_rng(5)
        coords = {"outcome": OUTCOME_IDS, "channel": CHANNELS}
        beta = rng.normal(loc=1.0, scale=beta_std, size=(n_chain, n_draw, 1, 3))
        return az.from_dict(posterior={"beta": beta}, coords=coords, dims={"beta": ["outcome", "channel"]})

    def test_high_variance_posterior_has_a_high_coefficient_of_variation(self):
        trace = self._trace(beta_std=0.8)
        result = posterior_coefficient_stability(trace, _meta())
        assert (result["coefficient_of_variation"] > 0.3).any()

    def test_low_variance_posterior_has_a_low_coefficient_of_variation(self):
        trace = self._trace(beta_std=0.001)
        result = posterior_coefficient_stability(trace, _meta())
        assert (result["coefficient_of_variation"] < 0.05).all()

    def test_returns_one_row_per_outcome_channel_pair(self):
        trace = self._trace(beta_std=0.1)
        result = posterior_coefficient_stability(trace, _meta())
        assert len(result) == len(OUTCOME_IDS) * len(CHANNELS)


class TestLeaveOneChannelOutSensitivity:
    def test_stable_channel_reports_near_zero_pct_change(self):
        def fit_without(dropped):
            # Dropping Radio barely moves TV/Search's coefficients.
            return {"TV": 1.01, "Search": 0.5} if dropped == "Radio" else {}

        result = leave_one_channel_out_sensitivity(
            ["Radio"], fit_without, baseline_beta={"TV": 1.0, "Radio": 0.3, "Search": 0.5},
        )
        tv_row = result[result["remaining_channel"] == "TV"].iloc[0]
        assert abs(tv_row["pct_change"]) < 5.0

    def test_entangled_channel_reports_large_pct_change(self):
        def fit_without(dropped):
            # Dropping Radio makes TV absorb a lot of its credit.
            return {"TV": 2.0, "Search": 0.5} if dropped == "Radio" else {}

        result = leave_one_channel_out_sensitivity(
            ["Radio"], fit_without, baseline_beta={"TV": 1.0, "Radio": 0.3, "Search": 0.5},
        )
        tv_row = result[result["remaining_channel"] == "TV"].iloc[0]
        assert tv_row["pct_change"] == pytest.approx(100.0)

    def test_dropped_channel_itself_is_excluded_from_its_own_results(self):
        def fit_without(dropped):
            return {"TV": 1.0, "Search": 0.5}  # Radio (dropped) intentionally absent

        result = leave_one_channel_out_sensitivity(
            ["Radio"], fit_without, baseline_beta={"TV": 1.0, "Radio": 0.3, "Search": 0.5},
        )
        assert "Radio" not in result["remaining_channel"].to_numpy()

    def test_missing_baseline_beta_gives_nan_pct_change_not_a_crash(self):
        def fit_without(dropped):
            return {"NewChannel": 1.0}

        result = leave_one_channel_out_sensitivity(
            ["Radio"], fit_without, baseline_beta={"TV": 1.0},
        )
        assert pd.isna(result["pct_change"].iloc[0])


class TestIdentificationReport:
    def _trace(self) -> az.InferenceData:
        n_chain, n_draw = 2, 10
        rng = np.random.default_rng(6)
        coords = {"outcome": OUTCOME_IDS, "channel": CHANNELS}
        beta = rng.normal(loc=1.0, scale=0.01, size=(n_chain, n_draw, 1, 3))
        return az.from_dict(posterior={"beta": beta}, coords=coords, dims={"beta": ["outcome", "channel"]})

    def test_highly_correlated_channels_produce_a_flag(self):
        n = 50
        rng = np.random.default_rng(7)
        tv = rng.uniform(100, 500, n)
        frame = {"X_media": np.column_stack([tv, tv * 1.01, rng.uniform(0, 100, n)])}
        flags = identification_report(frame, _meta(), self._trace())
        assert any("TV" in f["channel"] and "Radio" in f["channel"] for f in flags)

    def test_well_identified_model_produces_no_flags(self):
        n = 200
        rng = np.random.default_rng(8)
        frame = {"X_media": rng.uniform(50, 500, size=(n, 3))}
        flags = identification_report(frame, _meta(), self._trace())
        assert flags == []

    def test_sensitivity_df_flags_are_included_when_supplied(self):
        n = 200
        rng = np.random.default_rng(9)
        frame = {"X_media": rng.uniform(50, 500, size=(n, 3))}
        sensitivity_df = pd.DataFrame([
            {"dropped_channel": "Radio", "remaining_channel": "TV", "baseline_beta": 1.0, "refit_beta": 2.5, "pct_change": 150.0},
        ])
        flags = identification_report(frame, _meta(), self._trace(), sensitivity_df=sensitivity_df)
        assert any("Dropping 'Radio'" in f["message"] for f in flags)

    def test_flags_have_the_same_shape_as_curve_plausibility_checks(self):
        n = 50
        rng = np.random.default_rng(10)
        tv = rng.uniform(100, 500, n)
        frame = {"X_media": np.column_stack([tv, tv, rng.uniform(0, 100, n)])}
        flags = identification_report(frame, _meta(), self._trace())
        assert flags  # non-empty, since TV/Radio are identical here
        for f in flags:
            assert set(f.keys()) == {"level", "channel", "message"}
            assert f["level"] in ("warning", "error")
