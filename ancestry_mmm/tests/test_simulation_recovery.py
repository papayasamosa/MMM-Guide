"""Simulation recovery tests (PR G1's required test cases: "correlated-media
credit-displacement recovery" and "mediator credit allocation reconciles").

These do not fit a PyMC model - matching this codebase's established
convention (see test_hierarchical_model.py's module docstring) that the
committed test suite never builds/compiles a real PyMC model since that's
slow; a real MCMC-recovery check for the joint hierarchical model is an
offline, not-committed script (docs/decision_log.md). What's tested here is
the DETERMINISTIC replay/attribution machinery's behaviour when handed
KNOWN ground-truth parameters and a deliberately correlated spend pattern -
"recovery" in the sense that the attribution correctly recovers the true
relative channel strength from data where naive credit-splitting (e.g. by
spend share) would get it wrong."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.attribution import compute_shapley_contributions
from ancestry_mmm.core.brand_search import BrandSearchConfig, MODE_DEMAND_CAPTURE_MEDIATOR, mediator_reallocation
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.predict import FHPosteriorParams

OUTCOME_IDS = ["New"]
CHANNELS = ["TV", "Radio"]


def _meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], outcome_ids=OUTCOME_IDS, channels=CHANNELS,
        dna_channels=[], dna_channel_idx=[], non_dna_idx=[0, 1],
        dna_outcome_id="New", dna_lag_weeks=0, unpooled_markets=[], control_names=[],
    )


def _params(beta_tv: float, beta_radio: float) -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV": 0.3, "Radio": 0.3},
        hill_K={"TV": 2000.0, "Radio": 2000.0},
        hill_S={"TV": 1.0, "Radio": 1.0},
        beta={"New": {"TV": beta_tv, "Radio": beta_radio}},
        pathway_strength={},
        promo_coef={"New": 0.0},
        market_offset={"UK": {"New": 0.0}},
        intercept={"New": 3.0},
        trend_coef={"New": 0.0},
        gamma_fourier={"New": np.zeros(4)},
        alpha={"New": 5.0},
        control_coef={}, outcome_control_coef={},
    )


def _correlated_frame(n: int = 60, correlation: float = 0.95, seed: int = 0) -> dict:
    """TV and Radio spend deliberately correlated (a shared seasonal budget
    pattern, e.g.) - Radio's spend series is `correlation`-weighted toward
    TV's own series plus independent noise, so a naive "split credit by
    spend share" rule would give Radio credit it doesn't deserve whenever
    its true beta is much smaller than TV's."""
    rng = np.random.default_rng(seed)
    tv = rng.uniform(200, 800, n)
    independent = rng.uniform(200, 800, n)
    radio = correlation * tv + (1 - correlation) * independent
    X_media = np.column_stack([tv, radio])
    return {
        "markets": ["UK"], "market_idx": np.zeros(n, dtype=int), "market_bounds": [(0, n)],
        "X_media": X_media, "promo": np.zeros((n, 1)),
        "trend": np.zeros(n), "fourier": np.zeros((n, 4)),
        "control_names": [], "X_controls": np.zeros((n, 0)),
        "outcome_controls": {}, "outcome_control_names": {},
    }


class TestCorrelatedMediaCreditDisplacementRecovery:
    """Required test case: correlated-media credit-displacement recovery -
    Shapley attribution must recover the TRUE relative driver strength from
    known betas even when the two channels' spend series are highly
    correlated, not just split credit by spend share (which would be wrong
    whenever the true betas differ)."""

    def test_contributions_reconcile_exactly_even_under_high_correlation(self):
        # Additivity (baseline + sum(contributions) == mu_total) is a
        # structural Shapley guarantee, but worth confirming explicitly
        # under the exact scenario of concern - near-collinear spend does
        # not break the reconciliation, only the attributed split.
        frame = _correlated_frame(correlation=0.98)
        meta = _meta()
        params = _params(beta_tv=0.10, beta_radio=0.02)
        contributions = compute_shapley_contributions(frame, meta, params, n_permutations=100)
        total_channel_contrib = sum(contributions["channel_contributions"][ch] for ch in CHANNELS)
        reconstructed = contributions["baseline"] + total_channel_contrib
        np.testing.assert_allclose(reconstructed, contributions["mu_total"], rtol=1e-5, atol=1e-6)

    def test_the_true_stronger_driver_recovers_more_credit_despite_correlated_spend(self):
        # TV has 5x Radio's true beta; their spend is 98% correlated. A
        # naive spend-share split would give them comparable credit (their
        # spend levels are nearly identical by construction) - Shapley must
        # still recover TV as the dominant driver.
        frame = _correlated_frame(correlation=0.98)
        meta = _meta()
        params = _params(beta_tv=0.10, beta_radio=0.02)
        contributions = compute_shapley_contributions(frame, meta, params, n_permutations=200)
        tv_total = contributions["channel_contributions"]["TV"].sum()
        radio_total = contributions["channel_contributions"]["Radio"].sum()
        assert tv_total > radio_total
        # Spend share alone (the naive, wrong baseline) is close to 50/50
        # by construction - confirms the test scenario is genuinely a case
        # where credit displacement, not spend share, is what's being recovered.
        tv_spend_share = frame["X_media"][:, 0].sum() / frame["X_media"].sum()
        assert 0.45 < tv_spend_share < 0.55

    def test_swapping_which_channel_has_the_larger_true_beta_swaps_the_recovered_credit_ordering(self):
        # Same correlated spend pattern, betas reversed - the recovered
        # credit ordering must flip too, proving the displacement tracks
        # the true beta, not an artifact of column order or the specific
        # spend series shape.
        frame = _correlated_frame(correlation=0.98, seed=1)
        meta = _meta()

        tv_favoured = compute_shapley_contributions(frame, meta, _params(beta_tv=0.10, beta_radio=0.02), n_permutations=150)
        radio_favoured = compute_shapley_contributions(frame, meta, _params(beta_tv=0.02, beta_radio=0.10), n_permutations=150)

        assert tv_favoured["channel_contributions"]["TV"].sum() > tv_favoured["channel_contributions"]["Radio"].sum()
        assert radio_favoured["channel_contributions"]["Radio"].sum() > radio_favoured["channel_contributions"]["TV"].sum()

    def test_equal_true_betas_under_correlation_recover_a_near_equal_split(self):
        # Sanity check the other direction: when the true betas ARE equal,
        # high correlation should not artificially favour one channel over
        # the other - the permutation-averaged Shapley split should land
        # close to even.
        frame = _correlated_frame(correlation=0.98, seed=2)
        meta = _meta()
        params = _params(beta_tv=0.06, beta_radio=0.06)
        contributions = compute_shapley_contributions(frame, meta, params, n_permutations=300)
        tv_total = contributions["channel_contributions"]["TV"].sum()
        radio_total = contributions["channel_contributions"]["Radio"].sum()
        ratio = tv_total / radio_total
        assert 0.85 < ratio < 1.15


class TestMediatorCreditAllocationRecovery:
    """Required test case: mediator credit allocation - core.brand_search's
    deterministic reallocation must recover the exact known upstream-share
    ratio it was configured to reproduce, not merely reconcile to the
    right total (test_brand_search.py already covers reconciliation) -
    this is the "recovery" side: given a known 70/30 upstream split, the
    reallocated mediated amounts must land at 70/30, not some other stable
    but wrong ratio."""

    def test_recovers_the_known_upstream_contribution_ratio(self):
        config = BrandSearchConfig(
            channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR,
            mediator_of=["TV", "YouTube"], mediation_share=0.5,
        )
        brand_search_contribution = pd.Series([1000.0] * 4)
        # TV consistently drives 70% of upstream activity, YouTube 30%.
        upstream = {
            "TV": pd.Series([700.0, 350.0, 1400.0, 70.0]),
            "YouTube": pd.Series([300.0, 150.0, 600.0, 30.0]),
        }
        result = mediator_reallocation(config, brand_search_contribution, upstream)
        tv_share = result["mediated_by_TV"] / (result["mediated_by_TV"] + result["mediated_by_YouTube"])
        np.testing.assert_allclose(tv_share.to_numpy(), 0.7, atol=1e-9)

    def test_recovers_a_shifting_upstream_ratio_period_by_period(self):
        config = BrandSearchConfig(
            channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR,
            mediator_of=["TV", "YouTube"], mediation_share=1.0,
        )
        brand_search_contribution = pd.Series([100.0, 100.0])
        # Period 1: TV dominates (90/10). Period 2: YouTube dominates (10/90).
        upstream = {"TV": pd.Series([90.0, 10.0]), "YouTube": pd.Series([10.0, 90.0])}
        result = mediator_reallocation(config, brand_search_contribution, upstream)
        assert result["mediated_by_TV"].iloc[0] == pytest.approx(90.0)
        assert result["mediated_by_YouTube"].iloc[0] == pytest.approx(10.0)
        assert result["mediated_by_TV"].iloc[1] == pytest.approx(10.0)
        assert result["mediated_by_YouTube"].iloc[1] == pytest.approx(90.0)
