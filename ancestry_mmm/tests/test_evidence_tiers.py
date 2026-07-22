"""Tests for core.evidence_tiers - the market evidence tier classifier
(docs/market_hierarchy.md section 4), exercised against a small hand-built
InferenceData (same pattern as test_market_specific_diagnostics.py)."""

import numpy as np
import pytest
import arviz as az

from ancestry_mmm.core.evidence_tiers import (
    LOCALLY_ESTIMATED,
    PARTIALLY_POOLED,
    TRANSFERRED_ESTIMATE,
    classify_all_markets,
    classify_market_evidence,
    evidence_tiers_dataframe,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta

MARKETS = ["UK", "Australia", "NewMarket"]
SEGMENTS = ["New", "Winback"]
CHANNELS = ["TV", "Search"]


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=MARKETS, outcome_ids=SEGMENTS, channels=CHANNELS,
        dna_channels=[], dna_channel_idx=[], non_dna_idx=[0, 1],
        dna_outcome_id="New", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
    )


def _frame_with_market_sizes(sizes):
    """A minimal frame carrying only what classify_market_evidence reads:
    markets and market_bounds, derived from an observation count per market."""
    bounds = []
    offset = 0
    for n in sizes:
        bounds.append((offset, offset + n))
        offset += n
    return {"markets": MARKETS, "market_bounds": bounds}


def _trace(rel_uncertainty_by_market, n_chain=2, n_draw=10):
    """hill_K/beta posteriors where each market's spread (relative to its
    mean) is controlled directly, so the classifier's uncertainty signal is
    deterministic and easy to assert against."""
    rng = np.random.default_rng(0)
    coords = {"market": MARKETS, "channel": CHANNELS, "outcome": SEGMENTS}

    def var(mean_value):
        base = np.full((n_chain, n_draw, len(MARKETS), len(CHANNELS)), mean_value)
        for i, m in enumerate(MARKETS):
            noise_sd = rel_uncertainty_by_market[m] * mean_value
            base[:, :, i, :] += rng.normal(0, noise_sd, size=(n_chain, n_draw, len(CHANNELS)))
        return base

    hill_K = var(1000.0)
    beta = np.stack([var(0.1) for _ in SEGMENTS], axis=3)  # (chain, draw, market, segment, channel)

    posterior = {"hill_K": hill_K, "beta": beta}
    dims = {"hill_K": ["market", "channel"], "beta": ["market", "outcome", "channel"]}
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


class TestClassifyMarketEvidence:
    def test_unknown_market_raises(self, meta):
        frame = _frame_with_market_sizes([60, 60, 60])
        trace = _trace({m: 0.1 for m in MARKETS})
        with pytest.raises(ValueError, match="not one of this frame's markets"):
            classify_market_evidence(trace, frame, meta, "France", "TV")

    def test_unknown_channel_raises(self, meta):
        frame = _frame_with_market_sizes([60, 60, 60])
        trace = _trace({m: 0.1 for m in MARKETS})
        with pytest.raises(ValueError, match="not one of this model's channels"):
            classify_market_evidence(trace, frame, meta, "UK", "Radio")

    def test_few_observations_is_transferred_estimate_regardless_of_uncertainty(self, meta):
        # Even with very tight posterior uncertainty, too few periods forces "Transferred estimate".
        frame = _frame_with_market_sizes([60, 60, 5])
        trace = _trace({m: 0.01 for m in MARKETS})
        assert classify_market_evidence(trace, frame, meta, "NewMarket", "TV") == TRANSFERRED_ESTIMATE

    def test_many_observations_and_low_uncertainty_is_locally_estimated(self, meta):
        frame = _frame_with_market_sizes([104, 60, 60])
        trace = _trace({"UK": 0.05, "Australia": 0.05, "NewMarket": 0.05})
        assert classify_market_evidence(trace, frame, meta, "UK", "TV") == LOCALLY_ESTIMATED

    def test_enough_observations_but_high_uncertainty_is_partially_pooled(self, meta):
        frame = _frame_with_market_sizes([104, 60, 60])
        trace = _trace({"UK": 0.05, "Australia": 0.9, "NewMarket": 0.05})
        assert classify_market_evidence(trace, frame, meta, "Australia", "TV") == PARTIALLY_POOLED

    def test_moderate_observations_below_local_threshold_is_partially_pooled(self, meta):
        # Between the "pooled" and "local" observation thresholds, even with tight uncertainty.
        frame = _frame_with_market_sizes([104, 20, 60])
        trace = _trace({m: 0.01 for m in MARKETS})
        assert classify_market_evidence(trace, frame, meta, "Australia", "TV") == PARTIALLY_POOLED

    def test_custom_thresholds_are_respected(self, meta):
        frame = _frame_with_market_sizes([30, 60, 60])
        trace = _trace({m: 0.01 for m in MARKETS})
        # With default thresholds, 30 observations is below "local" (52).
        assert classify_market_evidence(trace, frame, meta, "UK", "TV") == PARTIALLY_POOLED
        # Lowering the "local" threshold to 20 should now qualify it.
        assert classify_market_evidence(
            trace, frame, meta, "UK", "TV", min_observations_for_local=20,
        ) == LOCALLY_ESTIMATED


class TestClassifyAllMarkets:
    def test_returns_a_tier_for_every_market_and_channel(self, meta):
        frame = _frame_with_market_sizes([104, 60, 5])
        trace = _trace({"UK": 0.05, "Australia": 0.3, "NewMarket": 0.05})
        result = classify_all_markets(trace, frame, meta)
        assert set(result) == set(MARKETS)
        for market_result in result.values():
            assert set(market_result) == set(CHANNELS)
        assert result["NewMarket"]["TV"] == TRANSFERRED_ESTIMATE
        assert result["UK"]["TV"] == LOCALLY_ESTIMATED


class TestEvidenceTiersDataframe:
    def test_has_one_row_per_market_channel_combination(self, meta):
        frame = _frame_with_market_sizes([104, 60, 5])
        trace = _trace({"UK": 0.05, "Australia": 0.3, "NewMarket": 0.05})
        df = evidence_tiers_dataframe(trace, frame, meta)
        assert len(df) == len(MARKETS) * len(CHANNELS)
        assert set(df.columns) == {"market", "channel", "curve_status"}

    def test_values_match_classify_all_markets(self, meta):
        frame = _frame_with_market_sizes([104, 60, 5])
        trace = _trace({"UK": 0.05, "Australia": 0.3, "NewMarket": 0.05})
        df = evidence_tiers_dataframe(trace, frame, meta)
        row = df[(df["market"] == "NewMarket") & (df["channel"] == "TV")].iloc[0]
        assert row["curve_status"] == TRANSFERRED_ESTIMATE
