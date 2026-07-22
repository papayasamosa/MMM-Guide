"""Tests for core.market_specific_diagnostics - the Model C equivalent of
core.diagnostics's scorecard pieces, exercised against a small hand-built
InferenceData rather than a real MCMC trace (same spirit as test_curve_bank.py
and test_optimization.py's hand-built FHModelMeta/params fixtures)."""

import numpy as np
import pytest
import arviz as az

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_diagnostics import (
    compute_scorecard_market_specific,
    curve_plausibility_checks_market_specific,
    in_sample_fit_market_specific,
)
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

MARKETS = ["UK", "AU"]
OUTCOME_IDS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV", "DNA_Media"]
N_OBS = 6


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=MARKETS, outcome_ids=OUTCOME_IDS, channels=CHANNELS,
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def params() -> FHMarketSpecificPosteriorParams:
    return FHMarketSpecificPosteriorParams(
        decay_rate={"TV": 0.6, "DNA_Media": 0.4},
        hill_K={"UK": {"TV": 1000.0, "DNA_Media": 500.0}, "AU": {"TV": 800.0, "DNA_Media": 300.0}},
        hill_S={"TV": 1.2, "DNA_Media": 1.0},
        beta={
            "UK": {"New": {"TV": 0.10, "DNA_Media": 0.05}, "DNA_CrossSell": {"TV": 0.02, "DNA_Media": 0.20}},
            "AU": {"New": {"TV": 0.08, "DNA_Media": 0.04}, "DNA_CrossSell": {"TV": 0.015, "DNA_Media": 0.18}},
        },
        pathway_strength=pathway_strength_from_flat({"New": 0.15, "DNA_CrossSell": 1.0}, "DNA_Media"),
        promo_coef={"New": 0.2, "DNA_CrossSell": 0.3},
        market_offset={"UK": {"New": 0.0, "DNA_CrossSell": 0.0}, "AU": {"New": 0.1, "DNA_CrossSell": -0.1}},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={"New": 0.1, "DNA_CrossSell": 0.05},
        gamma_fourier={"New": np.zeros(4), "DNA_CrossSell": np.zeros(4)},
        alpha={"New": 5.0, "DNA_CrossSell": 5.0},
        control_coef={},
        outcome_control_coef={},
    )


@pytest.fixture
def frame():
    rng = np.random.default_rng(0)
    return {
        "markets": MARKETS,
        "market_idx": np.array([0, 0, 0, 1, 1, 1]),
        "market_bounds": [(0, 3), (3, 6)],
        "X_media": rng.uniform(50, 500, size=(N_OBS, 2)),
        "Y": rng.integers(5, 50, size=(N_OBS, 2)).astype(float),
        "promo": rng.uniform(0, 1, size=(N_OBS, 2)),
        "trend": np.linspace(1.0, 1.2, N_OBS),
        "fourier": rng.normal(size=(N_OBS, 4)),
        "control_names": [],
        "X_controls": np.zeros((N_OBS, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


@pytest.fixture
def trace(params) -> az.InferenceData:
    """A small InferenceData carrying every variable
    compute_scorecard_market_specific touches (hill_K/beta/hill_S directly,
    plus mu/alpha for posterior_predictive_coverage, plus enough posterior
    variety across chains/draws for az.rhat/ess/mcse not to choke)."""
    n_chain, n_draw = 2, 8
    rng = np.random.default_rng(2)
    coords = {
        "market": MARKETS, "channel": CHANNELS, "outcome": OUTCOME_IDS,
        "obs": list(range(N_OBS)), "fourier": [0, 1, 2, 3],
    }

    def jittered(value, noise=0.02):
        arr = np.asarray(value, dtype=float)
        base = np.broadcast_to(arr, (n_chain, n_draw) + arr.shape).copy()
        return base * (1 + rng.normal(0, noise, size=base.shape))

    def additive_jitter(value, noise=1e-3):
        arr = np.asarray(value, dtype=float)
        base = np.broadcast_to(arr, (n_chain, n_draw) + arr.shape).copy()
        return base + rng.normal(0, noise, size=base.shape)

    hill_K = jittered([[params.hill_K[m][c] for c in CHANNELS] for m in MARKETS])
    beta = jittered([[[params.beta[m][s][c] for c in CHANNELS] for s in OUTCOME_IDS] for m in MARKETS])
    hill_S = jittered([params.hill_S[c] for c in CHANNELS])
    alpha = jittered([params.alpha[s] for s in OUTCOME_IDS])
    decay_rate = jittered([params.decay_rate[c] for c in CHANNELS])
    promo_coef = jittered([params.promo_coef[s] for s in OUTCOME_IDS])
    market_offset = additive_jitter([[params.market_offset[m][s] for s in OUTCOME_IDS] for m in MARKETS])
    intercept = jittered([params.intercept[s] for s in OUTCOME_IDS])
    trend_coef = jittered([params.trend_coef[s] for s in OUTCOME_IDS])
    gamma_fourier = additive_jitter(np.zeros((4, len(OUTCOME_IDS))))
    # A plausible mu: positive, roughly tracking Y so in-sample fit isn't nonsensical.
    mu = jittered(np.full((N_OBS, len(OUTCOME_IDS)), 20.0), noise=0.05)

    posterior = {
        "hill_K": hill_K, "beta": beta, "hill_S": hill_S, "alpha": alpha, "mu": mu,
        "decay_rate": decay_rate, "promo_coef": promo_coef, "market_offset": market_offset,
        "intercept": intercept, "trend_coef": trend_coef, "gamma_fourier": gamma_fourier,
    }
    dims = {
        "hill_K": ["market", "channel"], "beta": ["market", "outcome", "channel"],
        "hill_S": ["channel"], "alpha": ["outcome"], "mu": ["obs", "outcome"],
        "decay_rate": ["channel"], "promo_coef": ["outcome"], "market_offset": ["market", "outcome"],
        "intercept": ["outcome"], "trend_coef": ["outcome"], "gamma_fourier": ["fourier", "outcome"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


class TestInSampleFitMarketSpecific:
    def test_returns_one_row_per_segment_with_expected_columns(self, meta, params, frame):
        df = in_sample_fit_market_specific(frame, meta, params)
        assert list(df["outcome_id"]) == OUTCOME_IDS
        assert {"r_squared", "mape_pct", "actual_mean", "predicted_mean"} <= set(df.columns)


class TestCurvePlausibilityChecksMarketSpecific:
    def test_flags_are_prefixed_with_the_market_name(self, trace, meta, frame):
        # Push K far below the smallest observed non-zero spend for every
        # market/channel so every combination is guaranteed to raise a flag.
        frame = dict(frame, X_media=np.full_like(frame["X_media"], 100000.0))
        issues = curve_plausibility_checks_market_specific(trace, meta, frame)
        assert issues, "expected at least one plausibility flag with K << spend"
        assert all(msg["message"].startswith("[") for msg in issues)
        assert any(m in msg["message"] for msg in issues for m in MARKETS)

    def test_no_roi_bounds_means_no_roi_flags(self, trace, meta, frame):
        issues = curve_plausibility_checks_market_specific(trace, meta, frame, roi_bounds=None)
        assert all("marginal ROI" not in i["message"] for i in issues)


class TestComputeScorecardMarketSpecific:
    def test_scorecard_has_the_same_shape_as_model_as_scorecard(self, trace, meta, frame):
        scorecard = compute_scorecard_market_specific(trace, frame, meta)
        assert set(scorecard) == {"convergence", "in_sample_fit", "ppc_coverage", "plausibility_flags"}
        assert "converged" in scorecard["convergence"]
        assert len(scorecard["in_sample_fit"]) == len(OUTCOME_IDS)
        assert len(scorecard["ppc_coverage"]) == len(OUTCOME_IDS)
