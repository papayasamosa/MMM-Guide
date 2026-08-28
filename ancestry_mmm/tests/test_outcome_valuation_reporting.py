"""Tests for core.outcome_valuation_reporting - the per-posterior-draw,
per-week incremental-outcome extraction bridging core.attribution's
Shapley decomposition to core.outcome_valuation_attribution's weekly
value join (WP2D-ui). Hand-constructed FHModelMeta/InferenceData/frame,
no PyMC/MCMC involved, matching this project's existing convention
(test_uncertainty.py, test_attribution.py)."""

from __future__ import annotations

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.attribution import compute_shapley_contributions
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.outcome_valuation_reporting import (
    OutcomeValuationReportingCoverageError,
    attributable_spend,
    available_weeks_for_market,
    extract_incremental_outcome_draws,
    observed_denominator_counts_frame,
)
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.uncertainty import sample_draw_indices

OUTCOME_IDS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV_Brand", "DNA_Media"]
MARKETS = ["UK", "AU"]
N_WEEKS_PER_MARKET = 8
WEEK_STARTS = [
    (pd.Timestamp("2025-01-06") + pd.Timedelta(weeks=i)).strftime("%Y-%m-%d")
    for i in range(N_WEEKS_PER_MARKET)
]


def _const_broadcast(value, n_chain, n_draw):
    arr = np.asarray(value, dtype=float)
    return np.broadcast_to(arr, (n_chain, n_draw) + arr.shape).copy()


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=MARKETS,
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell",
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
    )


@pytest.fixture
def trace() -> az.InferenceData:
    """Matches test_uncertainty.py's shared-curve posterior shape - beta/
    hill_K carry real per-draw noise so draws genuinely differ."""
    n_chain, n_draw = 2, 20
    coords = {
        "outcome": OUTCOME_IDS,
        "channel": CHANNELS,
        "market": MARKETS,
        "fourier": list(range(4)),
    }
    rng = np.random.default_rng(11)

    def const(value):
        return _const_broadcast(value, n_chain, n_draw)

    posterior = {
        "decay_rate": const([0.5, 0.4]),
        "hill_K": const([1000.0, 500.0])
        * (1 + rng.normal(0, 0.05, size=(n_chain, n_draw, 2))),
        "hill_S": const([1.0, 1.0]),
        "beta": const([[0.10, 0.05], [0.02, 0.20]])
        * (1 + rng.normal(0, 0.1, size=(n_chain, n_draw, 2, 2))),
        "halo_strength": const([0.15, 1.0]),
        "promo_coef": const([0.0, 0.0]),
        "market_offset": const([[0.0, 0.0], [0.1, -0.1]]),
        "intercept": const([3.0, 2.0]),
        "trend_coef": const([0.0, 0.0]),
        "gamma_fourier": const(np.zeros((4, 2))),
        "alpha": const([5.0, 5.0]),
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "beta": ["outcome", "channel"],
        "halo_strength": ["outcome"],
        "promo_coef": ["outcome"],
        "market_offset": ["market", "outcome"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"],
        "alpha": ["outcome"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


@pytest.fixture
def frame():
    n_per_market = N_WEEKS_PER_MARKET
    n_markets = len(MARKETS)
    n = n_per_market * n_markets
    rng = np.random.default_rng(5)
    market_idx = np.repeat(np.arange(n_markets), n_per_market)
    market_bounds = [
        (i * n_per_market, (i + 1) * n_per_market) for i in range(n_markets)
    ]
    dates = np.array(WEEK_STARTS * n_markets, dtype="datetime64[D]")
    return {
        "markets": MARKETS,
        "market_idx": market_idx,
        "market_bounds": market_bounds,
        "dates": dates,
        "X_media": rng.uniform(50, 500, size=(n, 2)),
        "Y": rng.uniform(100, 1000, size=(n, len(OUTCOME_IDS))),
        "promo": np.zeros((n, len(OUTCOME_IDS))),
        "trend": np.zeros(n),
        "fourier": np.zeros((n, 4)),
        "control_names": [],
        "X_controls": np.zeros((n, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


class TestShapeAndDeterminism:
    def test_returns_n_draws_by_n_weeks(self, trace, frame, meta):
        weeks = WEEK_STARTS[:4]
        result = extract_incremental_outcome_draws(
            trace,
            frame,
            meta,
            market="UK",
            weeks=weeks,
            outcome_ids=["New"],
            n_draws=6,
            n_permutations=5,
        )
        assert result.shape == (6, 4)

    def test_same_seed_is_deterministic(self, trace, frame, meta):
        kwargs = dict(
            market="UK",
            weeks=WEEK_STARTS[:3],
            outcome_ids=["New"],
            n_draws=5,
            n_permutations=5,
            seed=7,
        )
        first = extract_incremental_outcome_draws(trace, frame, meta, **kwargs)
        second = extract_incremental_outcome_draws(trace, frame, meta, **kwargs)
        np.testing.assert_array_equal(first, second)


class TestReconciliationAgainstDirectShapleyCall:
    """The extracted per-draw values must be exactly what an independent,
    direct `compute_shapley_contributions` call at the same sampled draw
    indices produces - one calculation path, verified from the outside."""

    def test_total_matches_mu_total_minus_baseline(self, trace, frame, meta):
        market = "UK"
        weeks = WEEK_STARTS[2:6]
        n_draws, n_permutations, seed = 4, 8, 3
        outcome_ids = ["New", "DNA_CrossSell"]

        result = extract_incremental_outcome_draws(
            trace,
            frame,
            meta,
            market=market,
            weeks=weeks,
            outcome_ids=outcome_ids,
            n_draws=n_draws,
            n_permutations=n_permutations,
            seed=seed,
        )

        market_idx = meta.markets.index(market)
        start, _ = frame["market_bounds"][market_idx]
        row_indices = [start + 2, start + 3, start + 4, start + 5]
        outcome_col_indices = [meta.outcome_ids.index(o) for o in outcome_ids]

        draw_indices = sample_draw_indices(trace, n_draws, seed)
        expected = np.zeros((n_draws, len(weeks)))
        for i, draw_index in enumerate(draw_indices):
            params = extract_posterior_params(trace, meta, at=draw_index)
            contributions = compute_shapley_contributions(
                frame, meta, params, n_permutations=n_permutations
            )
            per_row = contributions["mu_total"] - contributions["baseline"]
            expected[i, :] = per_row[np.ix_(row_indices, outcome_col_indices)].sum(
                axis=1
            )

        np.testing.assert_allclose(result, expected, rtol=1e-10, atol=1e-10)

    def test_single_channel_matches_its_shapley_contribution(self, trace, frame, meta):
        market = "AU"
        weeks = WEEK_STARTS[:2]
        n_draws, n_permutations, seed = 3, 8, 9

        result = extract_incremental_outcome_draws(
            trace,
            frame,
            meta,
            market=market,
            weeks=weeks,
            outcome_ids=["New"],
            channel="TV_Brand",
            n_draws=n_draws,
            n_permutations=n_permutations,
            seed=seed,
        )

        market_idx = meta.markets.index(market)
        start, _ = frame["market_bounds"][market_idx]
        row_indices = [start, start + 1]
        outcome_col_index = meta.outcome_ids.index("New")

        draw_indices = sample_draw_indices(trace, n_draws, seed)
        expected = np.zeros((n_draws, len(weeks)))
        for i, draw_index in enumerate(draw_indices):
            params = extract_posterior_params(trace, meta, at=draw_index)
            contributions = compute_shapley_contributions(
                frame, meta, params, n_permutations=n_permutations
            )
            per_row = contributions["channel_contributions"]["TV_Brand"]
            expected[i, :] = per_row[row_indices, outcome_col_index]

        np.testing.assert_allclose(result, expected, rtol=1e-10, atol=1e-10)

    def test_channel_contributions_sum_to_the_total(self, trace, frame, meta):
        """Summing every channel's individually-extracted contribution must
        equal the `channel=None` total - the same reconciliation identity
        `compute_shapley_contributions` itself guarantees by construction,
        preserved end-to-end through this extraction layer."""
        market = "UK"
        weeks = WEEK_STARTS[:3]
        kwargs = dict(
            market=market,
            weeks=weeks,
            outcome_ids=["New", "DNA_CrossSell"],
            n_draws=3,
            n_permutations=6,
            seed=2,
        )
        total = extract_incremental_outcome_draws(trace, frame, meta, **kwargs)
        per_channel_sum = np.zeros_like(total)
        for channel in CHANNELS:
            per_channel_sum += extract_incremental_outcome_draws(
                trace, frame, meta, channel=channel, **kwargs
            )
        np.testing.assert_allclose(total, per_channel_sum, rtol=1e-8, atol=1e-8)


class TestFailsClosedOnUnresolvableRequests:
    def test_missing_week_for_market_raises(self, trace, frame, meta):
        with pytest.raises(OutcomeValuationReportingCoverageError, match="no fitted"):
            extract_incremental_outcome_draws(
                trace,
                frame,
                meta,
                market="UK",
                weeks=["2099-01-01"],
                outcome_ids=["New"],
            )

    def test_unknown_market_raises(self, trace, frame, meta):
        with pytest.raises(OutcomeValuationReportingCoverageError, match="market"):
            extract_incremental_outcome_draws(
                trace,
                frame,
                meta,
                market="CA",
                weeks=WEEK_STARTS[:2],
                outcome_ids=["New"],
            )

    def test_unknown_outcome_id_raises(self, trace, frame, meta):
        with pytest.raises(OutcomeValuationReportingCoverageError, match="outcome_id"):
            extract_incremental_outcome_draws(
                trace,
                frame,
                meta,
                market="UK",
                weeks=WEEK_STARTS[:2],
                outcome_ids=["Nonexistent"],
            )

    def test_unknown_channel_raises(self, trace, frame, meta):
        with pytest.raises(OutcomeValuationReportingCoverageError, match="Channel"):
            extract_incremental_outcome_draws(
                trace,
                frame,
                meta,
                market="UK",
                weeks=WEEK_STARTS[:2],
                outcome_ids=["New"],
                channel="Nonexistent",
            )

    def test_empty_outcome_ids_raises(self, trace, frame, meta):
        with pytest.raises(OutcomeValuationReportingCoverageError, match="outcome_ids"):
            extract_incremental_outcome_draws(
                trace,
                frame,
                meta,
                market="UK",
                weeks=WEEK_STARTS[:2],
                outcome_ids=[],
            )

    def test_empty_weeks_raises(self, trace, frame, meta):
        with pytest.raises(OutcomeValuationReportingCoverageError, match="weeks"):
            extract_incremental_outcome_draws(
                trace,
                frame,
                meta,
                market="UK",
                weeks=[],
                outcome_ids=["New"],
            )


class TestAvailableWeeksForMarket:
    def test_returns_that_markets_weeks_in_order(self, frame, meta):
        result = available_weeks_for_market(frame, meta, "UK")
        assert result == WEEK_STARTS

    def test_second_market_returns_its_own_slice(self, frame, meta):
        result = available_weeks_for_market(frame, meta, "AU")
        assert result == WEEK_STARTS

    def test_unknown_market_raises(self, frame, meta):
        with pytest.raises(OutcomeValuationReportingCoverageError, match="market"):
            available_weeks_for_market(frame, meta, "CA")


class TestObservedDenominatorCountsFrame:
    def test_shape_and_columns(self, frame, meta):
        result = observed_denominator_counts_frame(frame, meta, ["New"])
        assert list(result.columns) == [
            "outcome_id",
            "market",
            "week",
            "segment",
            "count",
        ]
        assert len(result) == N_WEEKS_PER_MARKET * len(MARKETS)
        assert set(result["outcome_id"]) == {"New"}

    def test_counts_match_frame_Y_column(self, frame, meta):
        result = observed_denominator_counts_frame(frame, meta, ["New"])
        oid_col = meta.outcome_ids.index("New")
        market_idx = meta.markets.index("UK")
        start, _ = frame["market_bounds"][market_idx]
        row = result[(result["market"] == "UK") & (result["week"] == WEEK_STARTS[0])]
        assert row["count"].iloc[0] == pytest.approx(frame["Y"][start, oid_col])

    def test_unknown_outcome_id_raises(self, frame, meta):
        with pytest.raises(OutcomeValuationReportingCoverageError, match="outcome_id"):
            observed_denominator_counts_frame(frame, meta, ["Nonexistent"])


class TestAttributableSpend:
    def test_total_equals_sum_of_all_channels(self, frame, meta):
        weeks = WEEK_STARTS[:3]
        total = attributable_spend(frame, meta, market="UK", weeks=weeks)
        per_channel_sum = sum(
            attributable_spend(frame, meta, market="UK", weeks=weeks, channel=c)
            for c in CHANNELS
        )
        assert total == pytest.approx(per_channel_sum)

    def test_matches_direct_frame_sum(self, frame, meta):
        weeks = WEEK_STARTS[:2]
        market_idx = meta.markets.index("UK")
        start, _ = frame["market_bounds"][market_idx]
        expected = float(frame["X_media"][start : start + 2, :].sum())
        result = attributable_spend(frame, meta, market="UK", weeks=weeks)
        assert result == pytest.approx(expected)

    def test_unknown_channel_raises(self, frame, meta):
        with pytest.raises(OutcomeValuationReportingCoverageError, match="Channel"):
            attributable_spend(
                frame,
                meta,
                market="UK",
                weeks=WEEK_STARTS[:2],
                channel="Nonexistent",
            )
