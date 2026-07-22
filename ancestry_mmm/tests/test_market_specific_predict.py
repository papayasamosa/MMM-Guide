"""Tests for core.market_specific_predict - the NumPy replay of Model C's
math, mirroring how core.predict's Model A equivalents would be tested
(hand-constructed FHModelMeta/params/frame, no PyMC/MCMC involved)."""

import numpy as np
import pytest
import arviz as az

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    adstock_saturate_frame_market_specific,
    extract_market_specific_posterior_params,
    generate_market_channel_curve,
    predict_mu_market_specific,
    steady_state_segment_response_market_specific,
)
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

MARKETS = ["UK", "AU"]
OUTCOME_IDS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV", "DNA_Media"]


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
    n = 6
    rng = np.random.default_rng(0)
    return {
        "markets": MARKETS,
        "market_idx": np.array([0, 0, 0, 1, 1, 1]),
        "market_bounds": [(0, 3), (3, 6)],
        "X_media": rng.uniform(50, 500, size=(n, 2)),
        "Y": rng.integers(5, 50, size=(n, 2)).astype(float),
        "promo": rng.uniform(0, 1, size=(n, 2)),
        "trend": np.linspace(1.0, 1.2, n),
        "fourier": rng.normal(size=(n, 4)),
        "control_names": [],
        "X_controls": np.zeros((n, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


class TestExtractMarketSpecificPosteriorParams:
    @pytest.fixture
    def trace(self) -> az.InferenceData:
        n_chain, n_draw = 2, 5
        coords = {"market": MARKETS, "channel": CHANNELS, "outcome": OUTCOME_IDS, "fourier": [0, 1, 2, 3]}
        rng = np.random.default_rng(1)

        def const(value):
            arr = np.asarray(value, dtype=float)
            return np.broadcast_to(arr, (n_chain, n_draw) + arr.shape).copy()

        posterior = {
            "decay_rate": const([0.5, 0.5]) + rng.normal(0, 1e-6, size=(n_chain, n_draw, 2)),
            "hill_K": const([[1000.0, 500.0], [800.0, 300.0]]),
            "hill_S": const([1.1, 1.1]),
            "beta": const([[[0.10, 0.05], [0.02, 0.20]], [[0.08, 0.04], [0.015, 0.18]]]),
            "promo_coef": const([0.2, 0.3]),
            "market_offset": const([[0.0, 0.0], [0.1, -0.1]]),
            "intercept": const([3.0, 2.0]),
            "trend_coef": const([0.1, 0.05]),
            "gamma_fourier": const(np.zeros((4, 2))),
            "alpha": const([5.0, 5.0]),
        }
        dims = {
            "decay_rate": ["channel"], "hill_K": ["market", "channel"], "hill_S": ["channel"],
            "beta": ["market", "outcome", "channel"],
            "promo_coef": ["outcome"], "market_offset": ["market", "outcome"],
            "intercept": ["outcome"], "trend_coef": ["outcome"],
            "gamma_fourier": ["fourier", "outcome"], "alpha": ["outcome"],
        }
        return az.from_dict(posterior=posterior, coords=coords, dims=dims)

    def test_hill_k_is_keyed_by_market_then_channel(self, trace, meta):
        params = extract_market_specific_posterior_params(trace, meta)
        assert params.hill_K["UK"]["TV"] == pytest.approx(1000.0)
        assert params.hill_K["AU"]["DNA_Media"] == pytest.approx(300.0)

    def test_beta_is_keyed_by_market_then_segment_then_channel(self, trace, meta):
        params = extract_market_specific_posterior_params(trace, meta)
        assert params.beta["UK"]["New"]["TV"] == pytest.approx(0.10)
        assert params.beta["AU"]["DNA_CrossSell"]["DNA_Media"] == pytest.approx(0.18)

    def test_decay_rate_and_hill_s_have_no_market_key(self, trace, meta):
        params = extract_market_specific_posterior_params(trace, meta)
        assert set(params.decay_rate) == {"TV", "DNA_Media"}
        assert params.decay_rate["TV"] == pytest.approx(0.5, abs=1e-3)

    def test_at_selects_one_draw_instead_of_averaging_over_the_posterior(self, trace, meta):
        # decay_rate has rng noise added per (chain, draw) in the trace fixture
        # above, so two different (chain, draw) selections must disagree with
        # each other and with the posterior mean - proves `at=` actually
        # indexes rather than silently falling back to the mean.
        mean_params = extract_market_specific_posterior_params(trace, meta)
        draw_a = extract_market_specific_posterior_params(trace, meta, at=(0, 0))
        draw_b = extract_market_specific_posterior_params(trace, meta, at=(1, 3))
        assert draw_a.decay_rate["TV"] != draw_b.decay_rate["TV"]
        assert draw_a.decay_rate["TV"] != mean_params.decay_rate["TV"]

    def test_at_still_selects_correctly_for_market_and_segment_indexed_fields(self, trace, meta):
        # beta has no per-draw noise in the fixture, so every (chain, draw)
        # must reproduce the same hand-known value - confirms `at=` selects
        # the right coordinate slice, not just a different scalar.
        draw = extract_market_specific_posterior_params(trace, meta, at=(1, 2))
        assert draw.beta["UK"]["New"]["TV"] == pytest.approx(0.10)
        assert draw.beta["AU"]["DNA_CrossSell"]["DNA_Media"] == pytest.approx(0.18)
        assert draw.hill_K["AU"]["DNA_Media"] == pytest.approx(300.0)


class TestAdstockSaturateFrameMarketSpecific:
    def test_uses_each_markets_own_k(self, meta, params, frame):
        out = adstock_saturate_frame_market_specific(
            frame["X_media"], frame["market_bounds"], frame["markets"], meta, params,
        )
        assert out.shape == frame["X_media"].shape
        assert np.all(out >= 0) and np.all(out <= 1)

    def test_zero_spend_saturates_to_zero(self, meta, params):
        X = np.zeros((4, 2))
        out = adstock_saturate_frame_market_specific(X, [(0, 2), (2, 4)], MARKETS, meta, params)
        np.testing.assert_allclose(out, 0.0)


class TestPredictMuMarketSpecific:
    def test_output_is_finite_positive_and_correctly_shaped(self, meta, params, frame):
        mu = predict_mu_market_specific(frame, meta, params)
        assert mu.shape == (6, 2)
        assert np.all(np.isfinite(mu))
        assert np.all(mu > 0)

    def test_more_spend_never_decreases_predicted_mu(self, meta, params, frame):
        low = predict_mu_market_specific(frame, meta, params)
        boosted_frame = dict(frame, X_media=frame["X_media"] * 10)
        high = predict_mu_market_specific(boosted_frame, meta, params)
        assert np.all(high >= low - 1e-9)


class TestSteadyStateSegmentResponseMarketSpecific:
    def test_zero_spend_matches_hand_computed_baseline(self, meta, params):
        result = steady_state_segment_response_market_specific("UK", {}, meta, params)
        # spend=0 -> saturation=0 for every channel, so eta = intercept + market_offset + trend_coef*1.0
        expected_new = np.exp(params.intercept["New"] + 0.0 + params.trend_coef["New"] * 1.0)
        expected_dna = np.exp(params.intercept["DNA_CrossSell"] + 0.0 + params.trend_coef["DNA_CrossSell"] * 1.0)
        assert result["New"] == pytest.approx(expected_new, rel=1e-6)
        assert result["DNA_CrossSell"] == pytest.approx(expected_dna, rel=1e-6)

    def test_different_markets_give_different_responses(self, meta, params):
        uk = steady_state_segment_response_market_specific("UK", {"TV": 500.0, "DNA_Media": 200.0}, meta, params)
        au = steady_state_segment_response_market_specific("AU", {"TV": 500.0, "DNA_Media": 200.0}, meta, params)
        assert uk["New"] != pytest.approx(au["New"])

    def test_more_spend_increases_response(self, meta, params):
        low = steady_state_segment_response_market_specific("UK", {"TV": 10.0}, meta, params)
        high = steady_state_segment_response_market_specific("UK", {"TV": 5000.0}, meta, params)
        assert high["New"] > low["New"]


class TestGenerateMarketChannelCurve:
    def test_unknown_market_raises(self, meta, params):
        with pytest.raises(ValueError, match="not one of this model's markets"):
            generate_market_channel_curve("FR", "TV", meta, params)

    def test_unknown_channel_raises(self, meta, params):
        with pytest.raises(ValueError, match="not one of this model's channels"):
            generate_market_channel_curve("UK", "Radio", meta, params)

    def test_zero_spend_gives_zero_response(self, meta, params):
        df = generate_market_channel_curve("UK", "TV", meta, params, spend_range=np.array([0.0, 100.0, 500.0]))
        assert df.iloc[0]["overall_response"] == pytest.approx(0.0)
        assert df.iloc[0]["saturation"] == pytest.approx(0.0)

    def test_overall_response_is_sum_of_segment_responses(self, meta, params):
        df = generate_market_channel_curve("UK", "DNA_Media", meta, params, spend_range=np.array([0.0, 250.0, 1000.0]))
        seg_cols = [f"{s}_response" for s in OUTCOME_IDS]
        np.testing.assert_allclose(df["overall_response"], df[seg_cols].sum(axis=1))

    def test_dna_channel_halo_scales_non_dna_segment_response(self, meta, params):
        # For a DNA channel, the non-DNA segment's response is beta * saturation * halo_strength -
        # strictly smaller than the DNA segment's own beta * saturation (halo_strength < 1 for "New").
        df = generate_market_channel_curve("UK", "DNA_Media", meta, params, spend_range=np.array([500.0]))
        row = df.iloc[0]
        raw_new = params.beta["UK"]["New"]["DNA_Media"] * row["saturation"]
        assert row["New_response"] == pytest.approx(raw_new * params.pathway_strength["New"]["DNA_Media"])

    def test_response_increases_with_spend(self, meta, params):
        df = generate_market_channel_curve("UK", "TV", meta, params, spend_range=np.array([0.0, 500.0, 5000.0]))
        assert df["overall_response"].is_monotonic_increasing


class TestGenerateMarketChannelCurveDirectDnaSegments:
    """A DNA-product kit-sale segment fit alongside the FH segments must get
    DNA media's full, undamped response, not the halo-shrunk pathway other
    segments get - same requirement as core.predict, tested separately for
    Model C's market-indexed parameter shape."""

    @pytest.fixture
    def meta_with_dna_kit_segment(self) -> FHModelMeta:
        return FHModelMeta(
            markets=MARKETS, outcome_ids=OUTCOME_IDS + ["New Customer"], channels=CHANNELS,
            dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_outcome_id="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"],
        )

    @pytest.fixture
    def params_with_dna_kit_segment(self, params) -> FHMarketSpecificPosteriorParams:
        for market in MARKETS:
            params.beta[market]["New Customer"] = {"TV": 0.03, "DNA_Media": 0.5}
        params.pathway_strength["New Customer"] = {"DNA_Media": 0.2}
        return params

    def test_dna_kit_segment_gets_full_response_not_halo_shrunk(self, meta_with_dna_kit_segment, params_with_dna_kit_segment):
        df = generate_market_channel_curve("UK", "DNA_Media", meta_with_dna_kit_segment, params_with_dna_kit_segment, spend_range=np.array([500.0]))
        row = df.iloc[0]
        raw = params_with_dna_kit_segment.beta["UK"]["New Customer"]["DNA_Media"] * row["saturation"]
        assert row["New Customer_response"] == pytest.approx(raw)  # NOT raw * pathway_strength

    def test_ordinary_non_direct_segment_is_still_halo_shrunk(self, meta_with_dna_kit_segment, params_with_dna_kit_segment):
        df = generate_market_channel_curve("UK", "DNA_Media", meta_with_dna_kit_segment, params_with_dna_kit_segment, spend_range=np.array([500.0]))
        row = df.iloc[0]
        raw_new = params_with_dna_kit_segment.beta["UK"]["New"]["DNA_Media"] * row["saturation"]
        assert row["New_response"] == pytest.approx(raw_new * params_with_dna_kit_segment.pathway_strength["New"]["DNA_Media"])


class TestPredictMuMarketSpecificDirectHaloSeparation:
    """Model C equivalent of test_predict.py's TestPredictMuDirectHaloSeparation -
    proves the same four invariants using predict_mu_market_specific on a
    real (non-constant) frame, since the steady-state functions can't
    observe a lag at all (a lag of a constant series is that same constant).
    See that class's docstring for the full design rationale."""

    OUTCOME_IDS = ["New", "DNA_CrossSell", "New Customer"]
    CHANNELS = ["TV", "DNA_Media"]
    N_WEEKS = 10
    SPIKE_WEEK = 3

    def _meta(self, dna_lag_weeks: int) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"], outcome_ids=self.OUTCOME_IDS, channels=self.CHANNELS,
            dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_outcome_id="DNA_CrossSell", dna_lag_weeks=dna_lag_weeks,
            unpooled_markets=[], control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"],
        )

    def _params(self) -> FHMarketSpecificPosteriorParams:
        beta_uk = {
            "New": {"TV": 0.0, "DNA_Media": 1.0},
            "DNA_CrossSell": {"TV": 0.0, "DNA_Media": 1.0},
            "New Customer": {"TV": 0.0, "DNA_Media": 1.0},
        }
        return FHMarketSpecificPosteriorParams(
            decay_rate={"TV": 0.0, "DNA_Media": 0.0},
            hill_K={"UK": {"TV": 1000.0, "DNA_Media": 1000.0}},
            hill_S={"TV": 1.0, "DNA_Media": 1.0},
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
        X_media = np.zeros((n, 2))
        X_media[self.SPIKE_WEEK, 1] = 500.0
        return {
            "markets": ["UK"], "market_idx": np.zeros(n, dtype=int), "market_bounds": [(0, n)],
            "X_media": X_media, "promo": np.zeros((n, len(self.OUTCOME_IDS))),
            "trend": np.zeros(n), "fourier": np.zeros((n, 4)),
            "control_names": [], "X_controls": np.zeros((n, 0)),
            "outcome_controls": {}, "outcome_control_names": {},
        }

    def test_kit_only_segment_does_not_inherit_the_extra_halo_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        mu = predict_mu_market_specific(self._frame(), meta, self._params())
        seg_idx = meta.outcome_ids.index("New Customer")
        baseline = mu[0, seg_idx]
        assert mu[self.SPIKE_WEEK, seg_idx] > baseline
        assert mu[self.SPIKE_WEEK + lag, seg_idx] == pytest.approx(baseline)

    def test_fh_halo_segment_does_inherit_the_extra_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        mu = predict_mu_market_specific(self._frame(), meta, self._params())
        seg_idx = meta.outcome_ids.index("New")
        baseline = mu[0, seg_idx]
        assert mu[self.SPIKE_WEEK, seg_idx] == pytest.approx(baseline)
        assert mu[self.SPIKE_WEEK + lag, seg_idx] > baseline

    def test_changing_halo_lag_does_not_alter_the_direct_kit_response(self):
        params = self._params()
        frame = self._frame()
        seg_idx = self.OUTCOME_IDS.index("New Customer")
        mu_lag2 = predict_mu_market_specific(frame, self._meta(dna_lag_weeks=2), params)
        mu_lag5 = predict_mu_market_specific(frame, self._meta(dna_lag_weeks=5), params)
        np.testing.assert_allclose(mu_lag2[:, seg_idx], mu_lag5[:, seg_idx])

    def test_dna_cross_sell_direct_and_halo_components_add_without_double_counting(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        mu = predict_mu_market_specific(self._frame(), meta, self._params())

        cross_idx = meta.outcome_ids.index("DNA_CrossSell")
        kit_idx = meta.outcome_ids.index("New Customer")
        halo_idx = meta.outcome_ids.index("New")

        assert mu[self.SPIKE_WEEK, cross_idx] == pytest.approx(mu[self.SPIKE_WEEK, kit_idx])
        assert mu[self.SPIKE_WEEK + lag, cross_idx] == pytest.approx(mu[self.SPIKE_WEEK + lag, halo_idx])
        assert mu[self.SPIKE_WEEK + lag, kit_idx] == pytest.approx(mu[0, kit_idx])
