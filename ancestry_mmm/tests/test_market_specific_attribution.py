"""Tests for core.market_specific_attribution - Model C's market-aware
Shapley attribution (docs/decision_log.md). Hand-constructed
FHModelMeta/params/frame, no PyMC/MCMC involved, matching
test_market_specific_predict.py's and test_attribution.py's convention."""

import numpy as np
import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_attribution import (
    compute_shapley_contributions_market_specific,
    segment_channel_market_summary,
    total_contribution_market_specific,
)
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams

MARKETS = ["UK", "AU"]
SEGMENTS = ["New", "DNA_CrossSell", "New Customer"]
CHANNELS = ["TV", "DNA_Media"]


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=MARKETS, segments=SEGMENTS, channels=CHANNELS,
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_segment="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
        direct_dna_segments=["DNA_CrossSell", "New Customer"],
    )


@pytest.fixture
def params() -> FHMarketSpecificPosteriorParams:
    return FHMarketSpecificPosteriorParams(
        decay_rate={"TV": 0.6, "DNA_Media": 0.4},
        hill_K={"UK": {"TV": 1000.0, "DNA_Media": 500.0}, "AU": {"TV": 800.0, "DNA_Media": 300.0}},
        hill_S={"TV": 1.2, "DNA_Media": 1.0},
        beta={
            "UK": {
                "New": {"TV": 0.10, "DNA_Media": 0.05},
                "DNA_CrossSell": {"TV": 0.02, "DNA_Media": 0.20},
                "New Customer": {"TV": 0.01, "DNA_Media": 0.50},
            },
            "AU": {
                "New": {"TV": 0.08, "DNA_Media": 0.04},
                "DNA_CrossSell": {"TV": 0.015, "DNA_Media": 0.18},
                "New Customer": {"TV": 0.012, "DNA_Media": 0.45},
            },
        },
        # "New Customer" carries a low halo_strength deliberately - when it's
        # NOT a direct segment, this is what its DNA_Media contribution gets
        # shrunk by; when it IS direct (as in `meta` above), it's bypassed.
        halo_strength={"New": 0.15, "DNA_CrossSell": 1.0, "New Customer": 0.2},
        promo_coef={"New": 0.2, "DNA_CrossSell": 0.3, "New Customer": 0.1},
        market_offset={
            "UK": {"New": 0.0, "DNA_CrossSell": 0.0, "New Customer": 0.0},
            "AU": {"New": 0.1, "DNA_CrossSell": -0.1, "New Customer": 0.05},
        },
        intercept={"New": 3.0, "DNA_CrossSell": 2.0, "New Customer": 2.5},
        trend_coef={"New": 0.1, "DNA_CrossSell": 0.05, "New Customer": 0.0},
        gamma_fourier={s: np.zeros(4) for s in SEGMENTS},
        alpha={s: 5.0 for s in SEGMENTS},
        control_coef={},
        segment_control_coef={},
    )


@pytest.fixture
def frame():
    n = 6
    rng = np.random.default_rng(0)
    return {
        "markets": MARKETS,
        "market_idx": np.array([0, 0, 0, 1, 1, 1]),
        "market_bounds": [(0, 3), (3, 6)],
        "X_media": rng.uniform(50, 500, size=(n, 2)),
        "promo": rng.uniform(0, 1, size=(n, len(SEGMENTS))),
        "trend": np.linspace(1.0, 1.2, n),
        "fourier": rng.normal(size=(n, 4)),
        "control_names": [],
        "X_controls": np.zeros((n, 0)),
        "segment_controls": {},
        "segment_control_names": {},
    }


class TestComputeShapleyContributionsMarketSpecific:
    def test_contributions_sum_to_mu_total_for_every_row_and_segment(self, frame, meta, params):
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)
        total_channel_contrib = sum(contributions["channel_contributions"][ch] for ch in CHANNELS)
        reconstructed = contributions["baseline"] + total_channel_contrib
        np.testing.assert_allclose(reconstructed, contributions["mu_total"], rtol=1e-5, atol=1e-6)

    def test_contributions_differ_by_market_since_beta_and_hill_k_are_market_indexed(self, frame, meta, params):
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=50)
        uk_rows = contributions["market_idx"] == 0
        au_rows = contributions["market_idx"] == 1
        # Same channel/segment, different markets -> different contribution
        # per unit spend, since beta/hill_K genuinely differ by market.
        tv_uk = contributions["channel_contributions"]["TV"][uk_rows, 0]
        tv_au = contributions["channel_contributions"]["TV"][au_rows, 0]
        assert not np.allclose(tv_uk.mean(), tv_au.mean())

    def test_dna_kit_segment_channel_contribution_uses_full_beta_not_halo_shrunk(self, frame, meta, params):
        contributions_direct = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)

        halo_meta = FHModelMeta(
            markets=MARKETS, segments=SEGMENTS, channels=CHANNELS,
            dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_segment="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
            direct_dna_segments=["DNA_CrossSell"],  # "New Customer" NOT direct here
        )
        contributions_shrunk = compute_shapley_contributions_market_specific(frame, halo_meta, params, n_permutations=20)

        seg_idx = SEGMENTS.index("New Customer")
        direct_total = contributions_direct["channel_contributions"]["DNA_Media"][:, seg_idx].sum()
        shrunk_total = contributions_shrunk["channel_contributions"]["DNA_Media"][:, seg_idx].sum()
        assert direct_total > shrunk_total


class TestSegmentChannelMarketSummary:
    def test_has_one_row_per_market_channel_segment_combination(self, frame, meta, params):
        summary = segment_channel_market_summary(frame, meta, params, n_permutations=20)
        assert len(summary) == len(MARKETS) * len(CHANNELS) * len(SEGMENTS)
        assert set(summary["market"]) == set(MARKETS)

    def test_spend_is_the_markets_own_channel_spend_not_shared_across_markets(self, frame, meta, params):
        summary = segment_channel_market_summary(frame, meta, params, n_permutations=20)
        uk_tv_spend = summary[(summary["market"] == "UK") & (summary["channel"] == "TV")]["spend"].iloc[0]
        au_tv_spend = summary[(summary["market"] == "AU") & (summary["channel"] == "TV")]["spend"].iloc[0]
        expected_uk = frame["X_media"][:3, 0].sum()
        expected_au = frame["X_media"][3:, 0].sum()
        assert uk_tv_spend == pytest.approx(expected_uk)
        assert au_tv_spend == pytest.approx(expected_au)
        assert uk_tv_spend != au_tv_spend


class TestTotalContributionMarketSpecific:
    def test_default_aggregates_across_markets_to_one_row_per_channel(self, frame, meta, params):
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)
        total = total_contribution_market_specific(frame, meta, params, contributions, ltv=None)
        assert len(total) == len(CHANNELS)
        assert set(total["channel"]) == set(CHANNELS)

    def test_by_market_keeps_market_as_a_grouping_key(self, frame, meta, params):
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)
        total = total_contribution_market_specific(frame, meta, params, contributions, ltv=None, by_market=True)
        assert len(total) == len(MARKETS) * len(CHANNELS)

    def test_total_spend_does_not_double_count_across_dna_kit_and_fh_segment_rows(self, frame, meta, params):
        # Spend is constant across segment rows for a given (market, channel)
        # - the two-stage aggregation must take it once per (market, channel),
        # not once per (market, channel, segment) row summed together.
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)
        total = total_contribution_market_specific(frame, meta, params, contributions, ltv=None)
        tv_total_spend = total.set_index("channel").loc["TV", "spend"]
        expected = frame["X_media"][:, 0].sum()
        assert tv_total_spend == pytest.approx(expected)

    def test_segments_filter_excludes_dna_kit_segment_from_the_total(self, frame, meta, params):
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)
        fh_only_segments = [s for s in SEGMENTS if s != "New Customer"]
        total_fh_only = total_contribution_market_specific(
            frame, meta, params, contributions, ltv=None, segments=fh_only_segments,
        )
        total_all = total_contribution_market_specific(frame, meta, params, contributions, ltv=None, segments=None)

        dna_media_fh_only = total_fh_only.set_index("channel").loc["DNA_Media", "volume_contribution"]
        dna_media_all = total_all.set_index("channel").loc["DNA_Media", "volume_contribution"]
        assert dna_media_fh_only < dna_media_all
        # Spend is unaffected by the segment filter - it isn't segment-level.
        assert total_fh_only.set_index("channel").loc["DNA_Media", "spend"] == pytest.approx(
            total_all.set_index("channel").loc["DNA_Media", "spend"]
        )

    def test_segment_shares_sum_to_one_per_channel(self, frame, meta, params):
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)
        total = total_contribution_market_specific(frame, meta, params, contributions, ltv=None)
        share_cols = [f"{s}_share" for s in SEGMENTS]
        row_sums = total[share_cols].sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, rtol=1e-6)

    def test_ltv_weighting_scales_value_contribution_per_segment(self, frame, meta, params):
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)
        ltv = {"New": 1.0, "DNA_CrossSell": 2.0, "New Customer": 0.5}
        total = total_contribution_market_specific(frame, meta, params, contributions, ltv=ltv)
        summary = segment_channel_market_summary(frame, meta, params, contributions, ltv=ltv)
        expected = summary.groupby("channel")["value_contribution"].sum()
        for ch in CHANNELS:
            assert total.set_index("channel").loc[ch, "value_contribution"] == pytest.approx(expected[ch])
