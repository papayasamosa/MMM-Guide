"""Tests for core.uncertainty - per-draw posterior uncertainty for response
curves, CPA, and scenario outcomes (docs/decision_log.md). Hand-constructed
FHModelMeta/params/InferenceData, no real MCMC sampling involved, matching
this project's convention (test_market_specific_predict.py etc.)."""

import warnings

import arviz as az
import numpy as np
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.uncertainty import (
    DEFAULT_N_DRAWS,
    evaluate_scenario_with_uncertainty,
    generate_channel_curve_with_uncertainty,
    generate_market_channel_curve_with_uncertainty,
    sample_draw_indices,
    summarize_distribution,
)

SEGMENTS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV_Brand", "DNA_Media"]
MARKETS = ["UK", "AU"]

IDENTITY = dict(
    model_run_id="run-abc123",
    data_fingerprint="data-fp-1",
    model_spec_fingerprint="spec-fp-1",
    posterior_fingerprint="posterior-fp-1",
)


def _const_broadcast(value, n_chain, n_draw):
    arr = np.asarray(value, dtype=float)
    return np.broadcast_to(arr, (n_chain, n_draw) + arr.shape).copy()


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=MARKETS, segments=SEGMENTS, channels=CHANNELS,
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_segment="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def trace() -> az.InferenceData:
    """Model A ("shared curve") shaped posterior - `beta`/`hill_K` have no
    market dimension, matching `core.predict.extract_posterior_params`."""
    n_chain, n_draw = 2, 20
    coords = {"segment": SEGMENTS, "channel": CHANNELS, "market": MARKETS, "fourier": list(range(4))}
    rng = np.random.default_rng(3)

    def const(value):
        return _const_broadcast(value, n_chain, n_draw)

    # beta/hill_K carry real per-draw noise so the resulting curves genuinely
    # differ draw-to-draw - required for a non-degenerate uncertainty band.
    posterior = {
        "decay_rate": const([0.6, 0.4]),
        "hill_K": const([1000.0, 500.0]) * (1 + rng.normal(0, 0.05, size=(n_chain, n_draw, 2))),
        "hill_S": const([1.1, 1.0]),
        "beta": const([[0.10, 0.05], [0.02, 0.20]]) * (1 + rng.normal(0, 0.1, size=(n_chain, n_draw, 2, 2))),
        "halo_strength": const([0.15, 1.0]),
        "promo_coef": const([0.2, 0.3]),
        "market_offset": const([[0.0, 0.0], [0.1, -0.1]]),
        "intercept": const([3.0, 2.0]),
        "trend_coef": const([0.1, 0.05]),
        "gamma_fourier": const(np.zeros((4, 2))),
        "alpha": const([5.0, 5.0]),
    }
    dims = {
        "decay_rate": ["channel"], "hill_K": ["channel"], "hill_S": ["channel"],
        "beta": ["segment", "channel"], "halo_strength": ["segment"],
        "promo_coef": ["segment"], "market_offset": ["market", "segment"],
        "intercept": ["segment"], "trend_coef": ["segment"],
        "gamma_fourier": ["fourier", "segment"], "alpha": ["segment"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


@pytest.fixture
def market_trace() -> az.InferenceData:
    """Model C ("market-specific") shaped posterior - `beta`/`hill_K` are
    market-indexed, matching `core.market_specific_predict.extract_market_specific_posterior_params`."""
    n_chain, n_draw = 2, 20
    coords = {"segment": SEGMENTS, "channel": CHANNELS, "market": MARKETS, "fourier": list(range(4))}
    rng = np.random.default_rng(3)

    def const(value):
        return _const_broadcast(value, n_chain, n_draw)

    posterior = {
        "decay_rate": const([0.6, 0.4]),
        "hill_K": const([[1000.0, 500.0], [800.0, 300.0]]) * (1 + rng.normal(0, 0.05, size=(n_chain, n_draw, 2, 2))),
        "hill_S": const([1.1, 1.0]),
        "beta": const([[[0.10, 0.05], [0.02, 0.20]], [[0.08, 0.04], [0.015, 0.18]]])
        * (1 + rng.normal(0, 0.1, size=(n_chain, n_draw, 2, 2, 2))),
        "halo_strength": const([0.15, 1.0]),
        "promo_coef": const([0.2, 0.3]),
        "market_offset": const([[0.0, 0.0], [0.1, -0.1]]),
        "intercept": const([3.0, 2.0]),
        "trend_coef": const([0.1, 0.05]),
        "gamma_fourier": const(np.zeros((4, 2))),
        "alpha": const([5.0, 5.0]),
    }
    dims = {
        "decay_rate": ["channel"], "hill_K": ["market", "channel"], "hill_S": ["channel"],
        "beta": ["market", "segment", "channel"], "halo_strength": ["segment"],
        "promo_coef": ["segment"], "market_offset": ["market", "segment"],
        "intercept": ["segment"], "trend_coef": ["segment"],
        "gamma_fourier": ["fourier", "segment"], "alpha": ["segment"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


class TestSampleDrawIndices:
    def test_returns_n_draws_distinct_pairs(self, trace):
        pairs = sample_draw_indices(trace, n_draws=15, seed=1)
        assert len(pairs) == 15
        assert len(set(pairs)) == 15

    def test_returns_every_pair_when_n_draws_exceeds_the_posterior_size(self, trace):
        # trace has 2 chains x 20 draws = 40 total pairs.
        pairs = sample_draw_indices(trace, n_draws=1000, seed=1)
        assert len(pairs) == 40

    def test_is_deterministic_given_the_same_seed(self, trace):
        assert sample_draw_indices(trace, n_draws=10, seed=7) == sample_draw_indices(trace, n_draws=10, seed=7)

    def test_different_seeds_can_give_different_samples(self, trace):
        assert sample_draw_indices(trace, n_draws=10, seed=1) != sample_draw_indices(trace, n_draws=10, seed=2)


class TestSummarizeDistribution:
    def test_mean_median_and_interval_on_a_known_array(self):
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = summarize_distribution(values, cred_mass=0.8)
        assert result["mean"] == pytest.approx(3.0)
        assert result["median"] == pytest.approx(3.0)
        assert result["lower"] <= result["median"] <= result["upper"]
        assert result["n_draws"] == 5

    def test_nans_are_dropped_before_summarizing(self):
        values = np.array([1.0, np.nan, 3.0, np.nan, 5.0])
        result = summarize_distribution(values)
        assert result["n_draws"] == 3
        assert result["mean"] == pytest.approx(3.0)

    def test_all_nan_input_returns_nan_with_zero_draws(self):
        result = summarize_distribution(np.array([np.nan, np.nan]))
        assert result["n_draws"] == 0
        assert np.isnan(result["mean"])
        assert np.isnan(result["lower"])


class TestGenerateChannelCurveWithUncertainty:
    def test_lower_le_mean_le_upper_at_every_spend_point(self, meta, trace):
        df = generate_channel_curve_with_uncertainty("TV_Brand", meta, trace, n_draws=20, seed=1, n_points=8)
        assert np.all(df["overall_response_lower"] <= df["overall_response_mean"] + 1e-9)
        assert np.all(df["overall_response_mean"] <= df["overall_response_upper"] + 1e-9)

    def test_uses_a_fixed_shared_spend_axis_across_every_draw(self, meta, trace):
        df = generate_channel_curve_with_uncertainty("TV_Brand", meta, trace, n_draws=20, seed=1, n_points=8)
        # Exactly one spend value per axis point - if draws used different
        # axes this would silently misalign, but the "spend" column itself
        # must still just be the single shared axis (n_points values).
        assert df["spend"].nunique() == 8

    def test_raising_n_draws_does_not_raise_when_posterior_is_smaller_than_requested(self, meta, trace):
        # Posterior has only 40 (chain, draw) pairs total.
        df = generate_channel_curve_with_uncertainty("TV_Brand", meta, trace, n_draws=1000, seed=1, n_points=5)
        assert len(df) == 5

    def test_no_warnings_raised_despite_the_zero_spend_undefined_cpa_point(self, meta, trace):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            generate_channel_curve_with_uncertainty("TV_Brand", meta, trace, n_draws=10, seed=1, n_points=5)

    def test_default_n_draws_constant_is_used_when_not_overridden(self, meta, trace):
        # Just confirms the module constant is importable/consistent with the
        # documented default - not testing sampling internals twice.
        assert DEFAULT_N_DRAWS == 100


class TestGenerateMarketChannelCurveWithUncertainty:
    def test_lower_le_mean_le_upper_at_every_spend_point(self, meta, market_trace):
        df = generate_market_channel_curve_with_uncertainty("UK", "TV_Brand", meta, market_trace, n_draws=20, seed=1, n_points=8)
        assert np.all(df["overall_response_lower"] <= df["overall_response_mean"] + 1e-9)
        assert np.all(df["overall_response_mean"] <= df["overall_response_upper"] + 1e-9)

    def test_different_markets_give_different_mean_curves(self, meta, market_trace):
        uk = generate_market_channel_curve_with_uncertainty("UK", "TV_Brand", meta, market_trace, n_draws=20, seed=1, n_points=5)
        au = generate_market_channel_curve_with_uncertainty("AU", "TV_Brand", meta, market_trace, n_draws=20, seed=1, n_points=5)
        assert not np.allclose(uk["overall_response_mean"], au["overall_response_mean"])


class TestEvaluateScenarioWithUncertainty:
    @pytest.fixture
    def approval(self) -> ModelApproval:
        return ModelApproval(approved_by="Jane Analyst", **IDENTITY)

    @pytest.fixture
    def reference_context(self):
        return {"2024-01": {"trend": 1.0, "fourier": np.zeros(4), "promo": {s: 0.0 for s in SEGMENTS}, "controls": {}, "segment_controls": {}}}

    def test_summary_has_lower_le_mean_le_upper_for_value(self, meta, market_trace, approval, reference_context):
        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        result = evaluate_scenario_with_uncertainty(
            spend_plan, "UK", meta, market_trace, reference_context,
            model_type="market_specific", n_draws=20, seed=1,
            approval=approval, **IDENTITY,
        )
        summary = result["summary"]
        assert np.all(summary["value_lower"] <= summary["value_mean"] + 1e-9)
        assert np.all(summary["value_mean"] <= summary["value_upper"] + 1e-9)
        assert result["n_draws"] == 20
        assert result["prob_outperforms_baseline"] is None

    def test_paired_baseline_comparison_gives_prob_one_when_proposed_strictly_dominates(
        self, meta, market_trace, approval, reference_context,
    ):
        higher_spend = {"2024-01": {"TV_Brand": 5000.0, "DNA_Media": 2000.0}}
        lower_spend = {"2024-01": {"TV_Brand": 10.0, "DNA_Media": 5.0}}
        result = evaluate_scenario_with_uncertainty(
            higher_spend, "UK", meta, market_trace, reference_context,
            model_type="market_specific", n_draws=20, seed=1,
            approval=approval, baseline_spend_plan=lower_spend, **IDENTITY,
        )
        assert result["prob_outperforms_baseline"] == pytest.approx(1.0)

    def test_paired_baseline_comparison_gives_prob_zero_when_reversed(self, meta, market_trace, approval, reference_context):
        higher_spend = {"2024-01": {"TV_Brand": 5000.0, "DNA_Media": 2000.0}}
        lower_spend = {"2024-01": {"TV_Brand": 10.0, "DNA_Media": 5.0}}
        result = evaluate_scenario_with_uncertainty(
            lower_spend, "UK", meta, market_trace, reference_context,
            model_type="market_specific", n_draws=20, seed=1,
            approval=approval, baseline_spend_plan=higher_spend, **IDENTITY,
        )
        assert result["prob_outperforms_baseline"] == pytest.approx(0.0)
