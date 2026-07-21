"""Tests for core.model_comparison - frame slicing for Model B, and the
comparison-candidate bookkeeping used by pages/12_Compare_Models.py."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.model_comparison import (
    ModelComparisonCandidate,
    candidates_to_dataframe,
    slice_frame_to_market,
)


@pytest.fixture
def two_market_frame():
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=6, freq="W"),
        "market": ["UK", "UK", "UK", "AU", "AU", "AU"],
    })
    return {
        "markets": ["UK", "AU"],
        "market_idx": np.array([0, 0, 0, 1, 1, 1]),
        "market_bounds": [(0, 3), (3, 6)],
        "unpooled_markets": ["AU"],
        "X_media": np.arange(12.0).reshape(6, 2),
        "Y": np.arange(6.0).reshape(6, 1),
        "promo": np.zeros((6, 1)),
        "X_controls": np.zeros((6, 0)),
        "fourier": np.zeros((6, 2)),
        "trend": np.linspace(1.0, 1.5, 6),
        "dates": df["date"].to_numpy(),
        "segment_controls": {"New": np.zeros((6, 1))},
        "df": df,
        "channels": ["TV", "DNA_Media"],
        "segments": ["New"],
    }


class TestSliceFrameToMarket:
    def test_unknown_market_raises(self, two_market_frame):
        with pytest.raises(ValueError, match="not one of this frame's markets"):
            slice_frame_to_market(two_market_frame, "FR")

    def test_sliced_frame_has_a_single_market_starting_at_zero(self, two_market_frame):
        sliced = slice_frame_to_market(two_market_frame, "AU")
        assert sliced["markets"] == ["AU"]
        assert sliced["market_bounds"] == [(0, 3)]
        np.testing.assert_array_equal(sliced["market_idx"], np.zeros(3, dtype=int))

    def test_sliced_frame_carries_only_that_markets_rows(self, two_market_frame):
        sliced = slice_frame_to_market(two_market_frame, "UK")
        np.testing.assert_array_equal(sliced["X_media"], two_market_frame["X_media"][:3])
        np.testing.assert_array_equal(sliced["Y"], two_market_frame["Y"][:3])
        assert len(sliced["df"]) == 3
        assert set(sliced["df"]["market"]) == {"UK"}

    def test_unpooled_markets_is_cleared_since_a_single_market_has_nothing_to_pool_with(self, two_market_frame):
        sliced = slice_frame_to_market(two_market_frame, "AU")
        assert sliced["unpooled_markets"] == []

    def test_original_frame_is_not_mutated(self, two_market_frame):
        original_markets = list(two_market_frame["markets"])
        slice_frame_to_market(two_market_frame, "UK")
        assert two_market_frame["markets"] == original_markets


class TestModelComparisonCandidate:
    def test_to_dict_from_dict_round_trip(self):
        candidate = ModelComparisonCandidate(
            model_type="C", label="Model C - UK, AU", model_run_id="run-1", fitted_at=1700000000.0,
            market=None, convergence={"rhat_max": 1.01, "converged": True},
            in_sample_fit=[{"segment": "New", "r_squared": 0.9}],
            ppc_coverage=[{"segment": "New", "coverage_pct": 91.0}],
            n_plausibility_flags=2,
        )
        restored = ModelComparisonCandidate.from_dict(candidate.to_dict())
        assert restored == candidate

    def test_from_dict_ignores_unknown_keys(self):
        d = {
            "model_type": "A", "label": "Model A", "model_run_id": "run-2", "fitted_at": 1.0,
            "some_future_field": "ignored",
        }
        candidate = ModelComparisonCandidate.from_dict(d)
        assert candidate.model_type == "A"
        assert candidate.market is None

    def test_from_scorecard_extracts_the_relevant_pieces(self):
        scorecard = {
            "convergence": {"rhat_max": 1.02, "converged": True},
            "in_sample_fit": [{"segment": "New", "r_squared": 0.8}],
            "ppc_coverage": [{"segment": "New", "coverage_pct": 88.0}],
            "plausibility_flags": [{"level": "warning", "channel": "TV", "message": "..."}],
        }
        candidate = ModelComparisonCandidate.from_scorecard(
            model_type="B", label="Model B - UK", model_run_id="run-3", fitted_at=2.0,
            scorecard=scorecard, market="UK",
        )
        assert candidate.market == "UK"
        assert candidate.convergence == scorecard["convergence"]
        assert candidate.n_plausibility_flags == 1

    def test_from_scorecard_defaults_missing_scorecard_keys(self):
        candidate = ModelComparisonCandidate.from_scorecard(
            model_type="A", label="Model A", model_run_id="run-4", fitted_at=3.0, scorecard={},
        )
        assert candidate.convergence == {}
        assert candidate.in_sample_fit == []
        assert candidate.n_plausibility_flags == 0


class TestCandidatesToDataframe:
    def test_one_row_per_candidate_with_means_collapsed_across_segments(self):
        candidates = [
            ModelComparisonCandidate(
                model_type="A", label="Model A", model_run_id="run-1", fitted_at=1.0,
                convergence={"rhat_max": 1.0, "ess_min": 500, "divergences": 0, "converged": True},
                in_sample_fit=[{"segment": "New", "r_squared": 0.8}, {"segment": "Winback", "r_squared": 0.6}],
                ppc_coverage=[{"segment": "New", "coverage_pct": 90.0}, {"segment": "Winback", "coverage_pct": 88.0}],
                n_plausibility_flags=0,
            ),
            ModelComparisonCandidate(
                model_type="C", label="Model C", model_run_id="run-2", fitted_at=2.0,
                convergence={}, in_sample_fit=[], ppc_coverage=[], n_plausibility_flags=3,
            ),
        ]
        df = candidates_to_dataframe(candidates)
        assert len(df) == 2
        assert df.loc[0, "mean_r_squared"] == pytest.approx(0.7)
        assert df.loc[0, "mean_ppc_coverage_pct"] == pytest.approx(89.0)
        assert pd.isna(df.loc[1, "mean_r_squared"])
        assert df.loc[1, "market"] == "(all)"

    def test_market_column_shows_the_candidates_market_when_set(self):
        candidate = ModelComparisonCandidate(
            model_type="B", label="Model B - UK", model_run_id="run-1", fitted_at=1.0, market="UK",
        )
        df = candidates_to_dataframe([candidate])
        assert df.loc[0, "market"] == "UK"

    def test_empty_candidate_list_gives_empty_dataframe(self):
        df = candidates_to_dataframe([])
        assert df.empty
