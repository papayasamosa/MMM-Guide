"""Tests for core.attribution - focused on the direct_dna_segments fix in
_channel_log_terms and the total_fh_contribution segments filter
(docs/dna_fh_causal_structure.md). Hand-constructed FHModelMeta/params/frame,
no PyMC/MCMC involved, matching test_market_specific_predict.py's
convention - this file does not attempt full existing-behaviour coverage of
compute_shapley_contributions (no test file existed for it before this PR)."""

import numpy as np
import pytest

from ancestry_mmm.core.attribution import compute_shapley_contributions, segment_channel_summary, total_fh_contribution
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.predict import FHPosteriorParams

SEGMENTS = ["New", "DNA_CrossSell", "Winback", "New Customer"]
CHANNELS = ["TV", "DNA_Media"]


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], segments=SEGMENTS, channels=CHANNELS,
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_segment="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
        direct_dna_segments=["DNA_CrossSell", "New Customer"],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV": 0.5, "DNA_Media": 0.4},
        hill_K={"TV": 1000.0, "DNA_Media": 500.0},
        hill_S={"TV": 1.0, "DNA_Media": 1.0},
        beta={
            "New": {"TV": 0.10, "DNA_Media": 0.05},
            "DNA_CrossSell": {"TV": 0.02, "DNA_Media": 0.20},
            "Winback": {"TV": 0.03, "DNA_Media": 0.06},
            "New Customer": {"TV": 0.01, "DNA_Media": 0.50},
        },
        # "New Customer" carries a low halo_strength deliberately - when it's
        # NOT a direct segment (see the halo_meta variant below), this value
        # is what its DNA_Media contribution gets shrunk by; when it IS
        # direct, this value is bypassed entirely (full beta, no shrinkage).
        halo_strength={"New": 0.15, "DNA_CrossSell": 1.0, "Winback": 0.10, "New Customer": 0.2},
        promo_coef={"New": 0.0, "DNA_CrossSell": 0.0, "Winback": 0.0, "New Customer": 0.0},
        market_offset={"UK": {s: 0.0 for s in SEGMENTS}},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0, "Winback": 1.5, "New Customer": 2.5},
        trend_coef={s: 0.0 for s in SEGMENTS},
        gamma_fourier={s: np.zeros(4) for s in SEGMENTS},
        alpha={s: 5.0 for s in SEGMENTS},
        control_coef={}, segment_control_coef={},
    )


@pytest.fixture
def frame():
    n = 8
    rng = np.random.default_rng(0)
    return {
        "markets": ["UK"], "market_idx": np.zeros(n, dtype=int), "market_bounds": [(0, n)],
        "X_media": rng.uniform(50, 500, size=(n, 2)),
        "promo": np.zeros((n, len(SEGMENTS))),
        "trend": np.zeros(n), "fourier": np.zeros((n, 4)),
        "control_names": [], "X_controls": np.zeros((n, 0)),
        "segment_controls": {}, "segment_control_names": {},
    }


class TestComputeShapleyContributionsDirectDnaSegments:
    def test_contributions_sum_to_mu_minus_baseline_with_a_dna_kit_segment_present(self, frame, meta, params):
        # additivity holds regardless of which segments are halo-shrunk vs direct
        contributions = compute_shapley_contributions(frame, meta, params, n_permutations=20)
        total_channel_contrib = sum(contributions["channel_contributions"][ch] for ch in CHANNELS)
        reconstructed = contributions["baseline"] + total_channel_contrib
        np.testing.assert_allclose(reconstructed, contributions["mu_total"], rtol=1e-5, atol=1e-6)

    def test_dna_kit_segment_channel_contribution_uses_full_beta_not_halo_shrunk(self, frame, meta, params):
        # Build a second meta where "New Customer" is NOT a direct segment,
        # and confirm its DNA_Media contribution is smaller there (halo-
        # shrunk) than when it's fit as a direct segment - the exact
        # regression this fix guards.
        contributions_direct = compute_shapley_contributions(frame, meta, params, n_permutations=20)

        halo_meta = FHModelMeta(
            markets=["UK"], segments=SEGMENTS, channels=CHANNELS,
            dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_segment="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
            direct_dna_segments=["DNA_CrossSell"],  # "New Customer" NOT direct here
        )
        contributions_shrunk = compute_shapley_contributions(frame, halo_meta, params, n_permutations=20)

        seg_idx = SEGMENTS.index("New Customer")
        direct_total = contributions_direct["channel_contributions"]["DNA_Media"][:, seg_idx].sum()
        shrunk_total = contributions_shrunk["channel_contributions"]["DNA_Media"][:, seg_idx].sum()
        assert direct_total > shrunk_total


class TestTotalFhContributionSegmentsFilter:
    def test_default_sums_every_segment(self, frame, meta, params):
        contributions = compute_shapley_contributions(frame, meta, params, n_permutations=20)
        total_all = total_fh_contribution(frame, meta, params, contributions, ltv=None)
        seg_summary = segment_channel_summary(frame, meta, params, contributions, ltv=None)
        expected = seg_summary.groupby("channel")["volume_contribution"].sum()
        for ch in CHANNELS:
            assert total_all.set_index("channel").loc[ch, "volume_contribution"] == pytest.approx(expected[ch])

    def test_segments_filter_excludes_dna_kit_segment_from_the_total(self, frame, meta, params):
        contributions = compute_shapley_contributions(frame, meta, params, n_permutations=20)
        fh_only_segments = [s for s in SEGMENTS if s != "New Customer"]
        total_fh_only = total_fh_contribution(frame, meta, params, contributions, ltv=None, segments=fh_only_segments)
        total_all = total_fh_contribution(frame, meta, params, contributions, ltv=None, segments=None)

        # Excluding a segment that gets non-zero DNA_Media contribution must
        # strictly reduce that channel's total.
        dna_media_fh_only = total_fh_only.set_index("channel").loc["DNA_Media", "volume_contribution"]
        dna_media_all = total_all.set_index("channel").loc["DNA_Media", "volume_contribution"]
        assert dna_media_fh_only < dna_media_all

    def test_segments_filter_matches_manual_sum_over_the_kept_segments(self, frame, meta, params):
        contributions = compute_shapley_contributions(frame, meta, params, n_permutations=20)
        fh_only_segments = ["New", "DNA_CrossSell"]
        total_fh_only = total_fh_contribution(frame, meta, params, contributions, ltv=None, segments=fh_only_segments)
        seg_summary = segment_channel_summary(frame, meta, params, contributions, ltv=None)
        expected = (
            seg_summary[seg_summary["segment"].isin(fh_only_segments)]
            .groupby("channel")["volume_contribution"].sum()
        )
        for ch in CHANNELS:
            assert total_fh_only.set_index("channel").loc[ch, "volume_contribution"] == pytest.approx(expected[ch])


class TestShapleyDirectHaloSeparation:
    """Model A attribution equivalent of test_predict.py's
    TestPredictMuDirectHaloSeparation - proves the same four invariants at
    the Shapley-contribution level. A single-channel model (DNA_Media only)
    makes the Shapley decomposition deterministic (only one permutation
    order exists), so contributions can be checked exactly rather than
    averaged over random removal orders."""

    SEGMENTS = ["New", "DNA_CrossSell", "New Customer"]
    CHANNELS = ["DNA_Media"]
    N_WEEKS = 10
    SPIKE_WEEK = 3

    def _meta(self, dna_lag_weeks: int) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"], segments=self.SEGMENTS, channels=self.CHANNELS,
            dna_channels=["DNA_Media"], dna_channel_idx=[0], non_dna_idx=[],
            dna_segment="DNA_CrossSell", dna_lag_weeks=dna_lag_weeks,
            unpooled_markets=[], control_names=[],
            direct_dna_segments=["DNA_CrossSell", "New Customer"],
        )

    def _params(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"DNA_Media": 0.0}, hill_K={"DNA_Media": 1000.0}, hill_S={"DNA_Media": 1.0},
            beta={
                "New": {"DNA_Media": 1.0},
                "DNA_CrossSell": {"DNA_Media": 1.0},
                "New Customer": {"DNA_Media": 1.0},
            },
            halo_strength={"New": 0.5, "DNA_CrossSell": 0.5, "New Customer": 0.0},
            promo_coef={s: 0.0 for s in self.SEGMENTS},
            market_offset={"UK": {s: 0.0 for s in self.SEGMENTS}},
            intercept={s: 0.0 for s in self.SEGMENTS},
            trend_coef={s: 0.0 for s in self.SEGMENTS},
            gamma_fourier={s: np.zeros(4) for s in self.SEGMENTS},
            alpha={s: 5.0 for s in self.SEGMENTS},
            control_coef={}, segment_control_coef={},
        )

    def _frame(self):
        n = self.N_WEEKS
        X_media = np.zeros((n, 1))
        X_media[self.SPIKE_WEEK, 0] = 500.0
        return {
            "markets": ["UK"], "market_idx": np.zeros(n, dtype=int), "market_bounds": [(0, n)],
            "X_media": X_media, "promo": np.zeros((n, len(self.SEGMENTS))),
            "trend": np.zeros(n), "fourier": np.zeros((n, 4)),
            "control_names": [], "X_controls": np.zeros((n, 0)),
            "segment_controls": {}, "segment_control_names": {},
        }

    def test_kit_only_segment_contribution_does_not_inherit_the_extra_halo_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        contributions = compute_shapley_contributions(self._frame(), meta, self._params(), n_permutations=5)
        seg_idx = meta.segments.index("New Customer")
        contrib = contributions["channel_contributions"]["DNA_Media"][:, seg_idx]
        assert contrib[self.SPIKE_WEEK] > 0
        assert contrib[self.SPIKE_WEEK + lag] == pytest.approx(0.0, abs=1e-9)

    def test_fh_halo_segment_contribution_does_inherit_the_extra_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        contributions = compute_shapley_contributions(self._frame(), meta, self._params(), n_permutations=5)
        seg_idx = meta.segments.index("New")
        contrib = contributions["channel_contributions"]["DNA_Media"][:, seg_idx]
        assert contrib[self.SPIKE_WEEK] == pytest.approx(0.0, abs=1e-9)
        assert contrib[self.SPIKE_WEEK + lag] > 0

    def test_changing_halo_lag_does_not_alter_the_direct_kit_contribution(self):
        params = self._params()
        frame = self._frame()
        seg_idx = self.SEGMENTS.index("New Customer")
        c2 = compute_shapley_contributions(frame, self._meta(dna_lag_weeks=2), params, n_permutations=5)
        c5 = compute_shapley_contributions(frame, self._meta(dna_lag_weeks=5), params, n_permutations=5)
        np.testing.assert_allclose(
            c2["channel_contributions"]["DNA_Media"][:, seg_idx],
            c5["channel_contributions"]["DNA_Media"][:, seg_idx],
        )

    def test_dna_cross_sell_contribution_adds_direct_and_halo_without_double_counting(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        contributions = compute_shapley_contributions(self._frame(), meta, self._params(), n_permutations=5)
        contrib = contributions["channel_contributions"]["DNA_Media"]
        cross_idx = meta.segments.index("DNA_CrossSell")
        kit_idx = meta.segments.index("New Customer")
        halo_idx = meta.segments.index("New")

        assert contrib[self.SPIKE_WEEK, cross_idx] == pytest.approx(contrib[self.SPIKE_WEEK, kit_idx])
        assert contrib[self.SPIKE_WEEK + lag, cross_idx] == pytest.approx(contrib[self.SPIKE_WEEK + lag, halo_idx])
        assert contrib[self.SPIKE_WEEK + lag, kit_idx] == pytest.approx(0.0, abs=1e-9)

        # Additivity still holds exactly for this single-channel model too.
        reconstructed = contributions["baseline"] + contrib
        np.testing.assert_allclose(reconstructed, contributions["mu_total"], rtol=1e-6, atol=1e-6)
