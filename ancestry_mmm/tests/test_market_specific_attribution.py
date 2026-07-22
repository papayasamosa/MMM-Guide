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
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

MARKETS = ["UK", "AU"]
OUTCOME_IDS = ["New", "DNA_CrossSell", "New Customer"]
CHANNELS = ["TV", "DNA_Media"]


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=MARKETS, outcome_ids=OUTCOME_IDS, channels=CHANNELS,
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
        direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"],
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
        # "New Customer" carries a low pathway_strength deliberately - when it's
        # NOT a direct segment, this is what its DNA_Media contribution gets
        # shrunk by; when it IS direct (as in `meta` above), it's bypassed.
        pathway_strength=pathway_strength_from_flat({"New": 0.15, "DNA_CrossSell": 1.0, "New Customer": 0.2}, "DNA_Media"),
        promo_coef={"New": 0.2, "DNA_CrossSell": 0.3, "New Customer": 0.1},
        market_offset={
            "UK": {"New": 0.0, "DNA_CrossSell": 0.0, "New Customer": 0.0},
            "AU": {"New": 0.1, "DNA_CrossSell": -0.1, "New Customer": 0.05},
        },
        intercept={"New": 3.0, "DNA_CrossSell": 2.0, "New Customer": 2.5},
        trend_coef={"New": 0.1, "DNA_CrossSell": 0.05, "New Customer": 0.0},
        gamma_fourier={s: np.zeros(4) for s in OUTCOME_IDS},
        alpha={s: 5.0 for s in OUTCOME_IDS},
        control_coef={},
        outcome_control_coef={},
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
        "promo": rng.uniform(0, 1, size=(n, len(OUTCOME_IDS))),
        "trend": np.linspace(1.0, 1.2, n),
        "fourier": rng.normal(size=(n, 4)),
        "control_names": [],
        "X_controls": np.zeros((n, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
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
            markets=MARKETS, outcome_ids=OUTCOME_IDS, channels=CHANNELS,
            dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_outcome_id="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell"],  # "New Customer" NOT direct here
        )
        contributions_shrunk = compute_shapley_contributions_market_specific(frame, halo_meta, params, n_permutations=20)

        seg_idx = OUTCOME_IDS.index("New Customer")
        direct_total = contributions_direct["channel_contributions"]["DNA_Media"][:, seg_idx].sum()
        shrunk_total = contributions_shrunk["channel_contributions"]["DNA_Media"][:, seg_idx].sum()
        assert direct_total > shrunk_total


class TestSegmentChannelMarketSummary:
    def test_has_one_row_per_market_channel_segment_combination(self, frame, meta, params):
        summary = segment_channel_market_summary(frame, meta, params, n_permutations=20)
        assert len(summary) == len(MARKETS) * len(CHANNELS) * len(OUTCOME_IDS)
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

    def test_outcome_ids_filter_excludes_dna_kit_outcome_from_the_total(self, frame, meta, params):
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)
        fh_only_outcome_ids = [s for s in OUTCOME_IDS if s != "New Customer"]
        total_fh_only = total_contribution_market_specific(
            frame, meta, params, contributions, ltv=None, outcome_ids=fh_only_outcome_ids,
        )
        total_all = total_contribution_market_specific(frame, meta, params, contributions, ltv=None, outcome_ids=None)

        dna_media_fh_only = total_fh_only.set_index("channel").loc["DNA_Media", "volume_contribution"]
        dna_media_all = total_all.set_index("channel").loc["DNA_Media", "volume_contribution"]
        assert dna_media_fh_only < dna_media_all
        # Spend is unaffected by the outcome_id filter - it isn't outcome-level.
        assert total_fh_only.set_index("channel").loc["DNA_Media", "spend"] == pytest.approx(
            total_all.set_index("channel").loc["DNA_Media", "spend"]
        )

    def test_outcome_shares_sum_to_one_per_channel(self, frame, meta, params):
        contributions = compute_shapley_contributions_market_specific(frame, meta, params, n_permutations=20)
        total = total_contribution_market_specific(frame, meta, params, contributions, ltv=None)
        share_cols = [f"{s}_share" for s in OUTCOME_IDS]
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


class TestShapleyMarketSpecificDirectHaloSeparation:
    """Model C attribution equivalent of test_attribution.py's
    TestShapleyDirectHaloSeparation - proves the same four invariants for
    the market-aware Shapley decomposition. Single-channel (DNA_Media only)
    and single-market model makes the decomposition deterministic."""

    OUTCOME_IDS = ["New", "DNA_CrossSell", "New Customer"]
    CHANNELS = ["DNA_Media"]
    N_WEEKS = 10
    SPIKE_WEEK = 3

    def _meta(self, dna_lag_weeks: int) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"], outcome_ids=self.OUTCOME_IDS, channels=self.CHANNELS,
            dna_channels=["DNA_Media"], dna_channel_idx=[0], non_dna_idx=[],
            dna_outcome_id="DNA_CrossSell", dna_lag_weeks=dna_lag_weeks,
            unpooled_markets=[], control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"],
        )

    def _params(self) -> FHMarketSpecificPosteriorParams:
        beta_uk = {
            "New": {"DNA_Media": 1.0},
            "DNA_CrossSell": {"DNA_Media": 1.0},
            "New Customer": {"DNA_Media": 1.0},
        }
        return FHMarketSpecificPosteriorParams(
            decay_rate={"DNA_Media": 0.0},
            hill_K={"UK": {"DNA_Media": 1000.0}},
            hill_S={"DNA_Media": 1.0},
            beta={"UK": beta_uk},
            pathway_strength=pathway_strength_from_flat({"New": 0.5, "DNA_CrossSell": 0.5, "New Customer": 0.0}, "DNA_Media"),
            promo_coef={s: 0.0 for s in self.OUTCOME_IDS},
            market_offset={"UK": {s: 0.0 for s in self.OUTCOME_IDS}},
            intercept={s: 0.0 for s in self.OUTCOME_IDS},
            trend_coef={s: 0.0 for s in self.OUTCOME_IDS},
            gamma_fourier={s: np.zeros(4) for s in self.OUTCOME_IDS},
            alpha={s: 5.0 for s in self.OUTCOME_IDS},
            control_coef={}, outcome_control_coef={},
        )

    def _frame(self):
        n = self.N_WEEKS
        X_media = np.zeros((n, 1))
        X_media[self.SPIKE_WEEK, 0] = 500.0
        return {
            "markets": ["UK"], "market_idx": np.zeros(n, dtype=int), "market_bounds": [(0, n)],
            "X_media": X_media, "promo": np.zeros((n, len(self.OUTCOME_IDS))),
            "trend": np.zeros(n), "fourier": np.zeros((n, 4)),
            "control_names": [], "X_controls": np.zeros((n, 0)),
            "outcome_controls": {}, "outcome_control_names": {},
        }

    def test_kit_only_segment_contribution_does_not_inherit_the_extra_halo_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        contributions = compute_shapley_contributions_market_specific(self._frame(), meta, self._params(), n_permutations=5)
        seg_idx = meta.outcome_ids.index("New Customer")
        contrib = contributions["channel_contributions"]["DNA_Media"][:, seg_idx]
        assert contrib[self.SPIKE_WEEK] > 0
        assert contrib[self.SPIKE_WEEK + lag] == pytest.approx(0.0, abs=1e-9)

    def test_fh_halo_segment_contribution_does_inherit_the_extra_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        contributions = compute_shapley_contributions_market_specific(self._frame(), meta, self._params(), n_permutations=5)
        seg_idx = meta.outcome_ids.index("New")
        contrib = contributions["channel_contributions"]["DNA_Media"][:, seg_idx]
        assert contrib[self.SPIKE_WEEK] == pytest.approx(0.0, abs=1e-9)
        assert contrib[self.SPIKE_WEEK + lag] > 0

    def test_changing_halo_lag_does_not_alter_the_direct_kit_contribution(self):
        params = self._params()
        frame = self._frame()
        seg_idx = self.OUTCOME_IDS.index("New Customer")
        c2 = compute_shapley_contributions_market_specific(frame, self._meta(dna_lag_weeks=2), params, n_permutations=5)
        c5 = compute_shapley_contributions_market_specific(frame, self._meta(dna_lag_weeks=5), params, n_permutations=5)
        np.testing.assert_allclose(
            c2["channel_contributions"]["DNA_Media"][:, seg_idx],
            c5["channel_contributions"]["DNA_Media"][:, seg_idx],
        )

    def test_dna_cross_sell_contribution_adds_direct_and_halo_without_double_counting(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        contributions = compute_shapley_contributions_market_specific(self._frame(), meta, self._params(), n_permutations=5)
        contrib = contributions["channel_contributions"]["DNA_Media"]
        cross_idx = meta.outcome_ids.index("DNA_CrossSell")
        kit_idx = meta.outcome_ids.index("New Customer")
        halo_idx = meta.outcome_ids.index("New")

        assert contrib[self.SPIKE_WEEK, cross_idx] == pytest.approx(contrib[self.SPIKE_WEEK, kit_idx])
        assert contrib[self.SPIKE_WEEK + lag, cross_idx] == pytest.approx(contrib[self.SPIKE_WEEK + lag, halo_idx])
        assert contrib[self.SPIKE_WEEK + lag, kit_idx] == pytest.approx(0.0, abs=1e-9)

        reconstructed = contributions["baseline"] + contrib
        np.testing.assert_allclose(reconstructed, contributions["mu_total"], rtol=1e-6, atol=1e-6)
