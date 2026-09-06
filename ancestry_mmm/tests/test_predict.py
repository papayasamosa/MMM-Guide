"""Tests for core.predict.generate_channel_curve - the Model A ("shared
curve") equivalent of core.market_specific_predict.generate_market_channel_curve,
added in Phase 3b so CPA/media-unit code (core.media_units) can work on
either model type's curve DataFrame uniformly. The rest of core.predict
(extract_posterior_params, steady_state_segment_response) is established,
shipped code with no dedicated test file, per this project's convention of
not unit-testing every existing NumPy-replay function - see
docs/decision_log.md and the equivalent note in test_market_specific_model.py.

`predict_mu` gets a dedicated test class below (`TestPredictMuDirectHaloSeparation`)
as a deliberate exception to that convention: it's the one NumPy-replay
function where the direct-vs-halo DNA pathway split (docs/dna_fh_causal_structure.md)
is actually observable, since the steady-state functions' constant-spend
assumption makes a lag invisible (a lag of a constant series is that same
constant) - `predict_mu` is evaluated on a real (non-constant) frame, so it's
the only place these tests can directly prove the four required invariants:
a kit-only outcome's response doesn't inherit the halo lag, an ordinary halo
outcome's does, changing the halo lag doesn't move a kit-only outcome's
response, and the FH DNA-cross-sell outcome's direct and halo components
add rather than double-count.

Outcome_id is the model's identity dimension throughout (PR E,
docs/decision_log.md) - not segment; the outcome_ids below (`"New"`,
`"DNA_CrossSell"`, `"New Customer"`) are kept as literal strings for
continuity with this file's history, but they are `FHModelMeta.outcome_ids`
entries, not segment names."""

from dataclasses import replace

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.predict import (
    FHPosteriorParams,
    adstock_saturate_frame,
    extract_posterior_params,
    generate_channel_curve,
    predict_mu,
    steady_state_segment_response,
)
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

OUTCOME_IDS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV_Brand", "DNA_Media"]


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.7, "DNA_Media": 0.5},
        hill_K={"TV_Brand": 1000.0, "DNA_Media": 500.0},
        hill_S={"TV_Brand": 1.2, "DNA_Media": 1.0},
        beta={
            "New": {"TV_Brand": 0.10, "DNA_Media": 0.05},
            "DNA_CrossSell": {"TV_Brand": 0.02, "DNA_Media": 0.20},
        },
        pathway_strength=pathway_strength_from_flat(
            {"New": 0.15, "DNA_CrossSell": 1.0}, "DNA_Media"
        ),
        promo_coef={"New": 0.2, "DNA_CrossSell": 0.3},
        market_offset={"UK": {"New": 0.0, "DNA_CrossSell": 0.0}},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={"New": 0.1, "DNA_CrossSell": 0.05},
        gamma_fourier={"New": np.zeros(6), "DNA_CrossSell": np.zeros(6)},
        alpha={"New": 5.0, "DNA_CrossSell": 5.0},
        control_coef={},
        outcome_control_coef={},
    )


class TestGenerateChannelCurve:
    def test_unknown_channel_raises(self, meta, params):
        with pytest.raises(ValueError, match="not one of this model's channels"):
            generate_channel_curve("Radio", meta, params)

    def test_zero_spend_gives_zero_response(self, meta, params):
        df = generate_channel_curve(
            "TV_Brand", meta, params, spend_range=np.array([0.0, 100.0, 500.0])
        )
        assert df.iloc[0]["overall_response"] == pytest.approx(0.0)
        assert df.iloc[0]["saturation"] == pytest.approx(0.0)

    def test_overall_response_is_sum_of_outcome_responses(self, meta, params):
        df = generate_channel_curve(
            "DNA_Media", meta, params, spend_range=np.array([0.0, 250.0, 1000.0])
        )
        outcome_cols = [f"{s}_response" for s in OUTCOME_IDS]
        np.testing.assert_allclose(df["overall_response"], df[outcome_cols].sum(axis=1))

    def test_dna_channel_halo_scales_non_dna_outcome_response(self, meta, params):
        df = generate_channel_curve(
            "DNA_Media", meta, params, spend_range=np.array([500.0])
        )
        row = df.iloc[0]
        raw_new = params.beta["New"]["DNA_Media"] * row["saturation"]
        assert row["New_response"] == pytest.approx(
            raw_new * params.pathway_strength["New"]["DNA_Media"]
        )

    def test_response_increases_with_spend(self, meta, params):
        df = generate_channel_curve(
            "TV_Brand", meta, params, spend_range=np.array([0.0, 500.0, 5000.0])
        )
        assert df["overall_response"].is_monotonic_increasing

    def test_column_shape_matches_market_specific_curve_for_downstream_compatibility(
        self, meta, params
    ):
        # core.media_units's functions rely on this shape being identical to
        # generate_market_channel_curve's output (minus the "market" column).
        df = generate_channel_curve(
            "TV_Brand", meta, params, spend_range=np.array([0.0, 100.0])
        )
        assert {"channel", "spend", "saturation", "overall_response"} <= set(df.columns)
        assert all(f"{s}_response" in df.columns for s in OUTCOME_IDS)

    def test_default_spend_range_is_derived_from_k(self, meta, params):
        df = generate_channel_curve("TV_Brand", meta, params, n_points=10)
        assert len(df) == 10
        assert df["spend"].max() == pytest.approx(params.hill_K["TV_Brand"] * 3)

    def test_max_spend_overrides_the_default_cap(self, meta, params):
        df = generate_channel_curve(
            "TV_Brand", meta, params, n_points=5, max_spend=50.0
        )
        assert df["spend"].max() == pytest.approx(50.0)


class TestMediaInputScaleReplay:
    """A persisted input-domain scale must be invisible on raw-unit curves."""

    def test_scaled_media_domain_replays_the_same_adstock_and_hill_response(
        self, meta, params
    ):
        scales = {"TV_Brand": 100.0, "DNA_Media": 50.0}
        scaled_meta = replace(meta, media_input_scales=scales)
        scaled_params = replace(
            params,
            hill_K={
                channel: value / scales[channel]
                for channel, value in params.hill_K.items()
            },
        )
        X_media = np.array([[0.0, 0.0], [100.0, 50.0], [200.0, 0.0], [0.0, 25.0]])
        raw_sat = adstock_saturate_frame(X_media, [(0, len(X_media))], meta, params)
        scaled_sat = adstock_saturate_frame(
            X_media, [(0, len(X_media))], scaled_meta, scaled_params
        )
        np.testing.assert_allclose(raw_sat, scaled_sat, rtol=1e-12, atol=1e-12)

        spend_range = np.array([0.0, 100.0, 500.0])
        raw_curve = generate_channel_curve(
            "TV_Brand", meta, params, spend_range=spend_range
        )
        scaled_curve = generate_channel_curve(
            "TV_Brand", scaled_meta, scaled_params, spend_range=spend_range
        )
        np.testing.assert_allclose(
            raw_curve["saturation"], scaled_curve["saturation"], rtol=1e-12
        )
        np.testing.assert_allclose(
            raw_curve["overall_response"],
            scaled_curve["overall_response"],
            rtol=1e-12,
        )


class TestGenerateChannelCurveDirectDnaOutcomes:
    """A DNA-product kit-sale outcome_id (core.outcomes) fit alongside the FH
    outcomes is DNA media's *direct* target, not a halo recipient - it must
    get the same full, undamped response as `dna_outcome_id` itself, not the
    shrunk-toward-zero halo other outcomes get (docs/dna_fh_causal_structure.md)."""

    @pytest.fixture
    def meta_with_dna_kit_outcome(self) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"],
            outcome_ids=OUTCOME_IDS + ["New Customer"],
            channels=CHANNELS,
            dna_channels=["DNA_Media"],
            dna_channel_idx=[1],
            non_dna_idx=[0],
            dna_outcome_id="DNA_CrossSell",
            dna_lag_weeks=4,
            unpooled_markets=[],
            control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"],
        )

    @pytest.fixture
    def params_with_dna_kit_outcome(self, params) -> FHPosteriorParams:
        params.beta["New Customer"] = {"TV_Brand": 0.03, "DNA_Media": 0.5}
        params.pathway_strength["New Customer"] = {
            "DNA_Media": 0.2
        }  # would apply if wrongly treated as a halo recipient
        return params

    def test_dna_kit_outcome_gets_full_response_not_halo_shrunk(
        self, meta_with_dna_kit_outcome, params_with_dna_kit_outcome
    ):
        df = generate_channel_curve(
            "DNA_Media",
            meta_with_dna_kit_outcome,
            params_with_dna_kit_outcome,
            spend_range=np.array([500.0]),
        )
        row = df.iloc[0]
        raw = (
            params_with_dna_kit_outcome.beta["New Customer"]["DNA_Media"]
            * row["saturation"]
        )
        assert row["New Customer_response"] == pytest.approx(
            raw
        )  # NOT raw * pathway_strength

    def test_ordinary_non_direct_outcome_is_still_halo_shrunk(
        self, meta_with_dna_kit_outcome, params_with_dna_kit_outcome
    ):
        # Regression guard: adding a direct DNA-kit outcome must not
        # accidentally exempt an unrelated FH outcome (New) from the halo
        # shrinkage it's still supposed to get.
        df = generate_channel_curve(
            "DNA_Media",
            meta_with_dna_kit_outcome,
            params_with_dna_kit_outcome,
            spend_range=np.array([500.0]),
        )
        row = df.iloc[0]
        raw_new = (
            params_with_dna_kit_outcome.beta["New"]["DNA_Media"] * row["saturation"]
        )
        assert row["New_response"] == pytest.approx(
            raw_new * params_with_dna_kit_outcome.pathway_strength["New"]["DNA_Media"]
        )


class TestSteadyStateSegmentResponseDirectDnaOutcomes:
    """steady_state_segment_response has its own (non-array-based) halo
    branch - same direct_dna_outcome_ids requirement as generate_channel_curve,
    tested separately since the code path is separate."""

    @pytest.fixture
    def meta_with_dna_kit_outcome(self) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"],
            outcome_ids=OUTCOME_IDS + ["New Customer"],
            channels=CHANNELS,
            dna_channels=["DNA_Media"],
            dna_channel_idx=[1],
            non_dna_idx=[0],
            dna_outcome_id="DNA_CrossSell",
            dna_lag_weeks=4,
            unpooled_markets=[],
            control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"],
        )

    @pytest.fixture
    def params_with_dna_kit_outcome(self, params) -> FHPosteriorParams:
        params.beta["New Customer"] = {"TV_Brand": 0.03, "DNA_Media": 0.5}
        params.pathway_strength["New Customer"] = {"DNA_Media": 0.2}
        params.intercept["New Customer"] = 2.0
        params.trend_coef["New Customer"] = 0.0
        params.promo_coef["New Customer"] = 0.0
        params.gamma_fourier["New Customer"] = np.zeros(6)
        return params

    def test_dna_kit_outcome_response_uses_full_beta_not_halo_shrunk(
        self, meta_with_dna_kit_outcome, params_with_dna_kit_outcome
    ):
        spend = {"TV_Brand": 0.0, "DNA_Media": 500.0}
        direct = steady_state_segment_response(
            "UK", spend, meta_with_dna_kit_outcome, params_with_dna_kit_outcome
        )

        halo_meta = FHModelMeta(
            markets=["UK"],
            outcome_ids=OUTCOME_IDS + ["New Customer"],
            channels=CHANNELS,
            dna_channels=["DNA_Media"],
            dna_channel_idx=[1],
            non_dna_idx=[0],
            dna_outcome_id="DNA_CrossSell",
            dna_lag_weeks=4,
            unpooled_markets=[],
            control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell"],  # New Customer NOT direct here
        )
        shrunk = steady_state_segment_response(
            "UK", spend, halo_meta, params_with_dna_kit_outcome
        )

        # Full-weight response must exceed the halo-shrunk response for the
        # same inputs (halo_strength < 1 for "New Customer").
        assert direct["New Customer"] > shrunk["New Customer"]


class TestExtractPosteriorParamsAt:
    """`at=(chain, draw)` (added for core.uncertainty's per-draw calculations)
    selects one specific posterior sample instead of averaging over the
    whole posterior - the Model A equivalent of
    TestExtractMarketSpecificPosteriorParams's `at=` coverage in
    test_market_specific_predict.py."""

    @pytest.fixture
    def trace(self) -> az.InferenceData:
        n_chain, n_draw = 2, 5
        coords = {
            "outcome": OUTCOME_IDS,
            "channel": CHANNELS,
            "market": ["UK"],
            "fourier": list(range(6)),
        }
        rng = np.random.default_rng(1)

        def const(value):
            arr = np.asarray(value, dtype=float)
            return np.broadcast_to(arr, (n_chain, n_draw) + arr.shape).copy()

        posterior = {
            "decay_rate": const([0.7, 0.5])
            + rng.normal(0, 1e-6, size=(n_chain, n_draw, 2)),
            "hill_K": const([1000.0, 500.0]),
            "hill_S": const([1.2, 1.0]),
            "beta": const([[0.10, 0.05], [0.02, 0.20]]),
            "promo_coef": const([0.2, 0.3]),
            "market_offset": const([[0.0, 0.0]]),
            "intercept": const([3.0, 2.0]),
            "trend_coef": const([0.1, 0.05]),
            "gamma_fourier": const(np.zeros((6, 2))),
            "alpha": const([5.0, 5.0]),
        }
        dims = {
            "decay_rate": ["channel"],
            "hill_K": ["channel"],
            "hill_S": ["channel"],
            "beta": ["outcome", "channel"],
            "promo_coef": ["outcome"],
            "market_offset": ["market", "outcome"],
            "intercept": ["outcome"],
            "trend_coef": ["outcome"],
            "gamma_fourier": ["fourier", "outcome"],
            "alpha": ["outcome"],
        }
        return az.from_dict(posterior=posterior, coords=coords, dims=dims)

    def test_at_selects_one_draw_instead_of_averaging_over_the_posterior(
        self, trace, meta
    ):
        mean_params = extract_posterior_params(trace, meta)
        draw_a = extract_posterior_params(trace, meta, at=(0, 0))
        draw_b = extract_posterior_params(trace, meta, at=(1, 3))
        assert draw_a.decay_rate["TV_Brand"] != draw_b.decay_rate["TV_Brand"]
        assert draw_a.decay_rate["TV_Brand"] != mean_params.decay_rate["TV_Brand"]

    def test_at_still_selects_correctly_for_outcome_and_channel_indexed_fields(
        self, trace, meta
    ):
        draw = extract_posterior_params(trace, meta, at=(1, 2))
        assert draw.beta["New"]["TV_Brand"] == pytest.approx(0.10)
        assert draw.beta["DNA_CrossSell"]["DNA_Media"] == pytest.approx(0.20)
        assert draw.hill_K["DNA_Media"] == pytest.approx(500.0)


class TestPredictMuDirectHaloSeparation:
    """Proves the four invariants docs/dna_fh_causal_structure.md and the
    post-merge correctness audit require: a kit-only outcome's response
    uses `dna_direct_media` (no extra lag), an ordinary halo outcome's uses
    `dna_halo_media` (the extra lag), changing `dna_lag_weeks` never moves a
    kit-only outcome's response, and `dna_outcome_id`'s direct and halo
    components add without double counting. Uses `predict_mu` on a real
    (non-constant) frame - the steady-state functions can't observe a lag at
    all, since a lag of a constant series is that same constant.

    Outcome_ids: "New" (ordinary FH, halo-only), "DNA_CrossSell"
    (`dna_outcome_id`, both pathways), "New Customer" (DNA-kit,
    direct-only). `decay_rate=0` removes adstock carryover, so the
    saturated DNA-media series is nonzero at exactly one week - the spend
    spike's own week - making the lag's effect land at one unambiguous,
    disjoint week index."""

    OUTCOME_IDS = ["New", "DNA_CrossSell", "New Customer"]
    CHANNELS = ["TV", "DNA_Media"]
    N_WEEKS = 10
    SPIKE_WEEK = 3

    def _meta(self, dna_lag_weeks: int) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"],
            outcome_ids=self.OUTCOME_IDS,
            channels=self.CHANNELS,
            dna_channels=["DNA_Media"],
            dna_channel_idx=[1],
            non_dna_idx=[0],
            dna_outcome_id="DNA_CrossSell",
            dna_lag_weeks=dna_lag_weeks,
            unpooled_markets=[],
            control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"],
        )

    def _params(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"TV": 0.0, "DNA_Media": 0.0},
            hill_K={"TV": 1000.0, "DNA_Media": 1000.0},
            hill_S={"TV": 1.0, "DNA_Media": 1.0},
            beta={
                "New": {"TV": 0.0, "DNA_Media": 1.0},
                "DNA_CrossSell": {"TV": 0.0, "DNA_Media": 1.0},
                "New Customer": {"TV": 0.0, "DNA_Media": 1.0},
            },
            # "New"/"DNA_CrossSell" share the same pathway_strength deliberately
            # (see test_dna_cross_sell_direct_and_halo_components_add_without_double_counting) -
            # "New Customer" (kit-only) has none, since it has no halo pathway.
            pathway_strength=pathway_strength_from_flat(
                {"New": 0.5, "DNA_CrossSell": 0.5, "New Customer": 0.0}, "DNA_Media"
            ),
            promo_coef={s: 0.0 for s in self.OUTCOME_IDS},
            market_offset={"UK": {s: 0.0 for s in self.OUTCOME_IDS}},
            intercept={s: 0.0 for s in self.OUTCOME_IDS},
            trend_coef={s: 0.0 for s in self.OUTCOME_IDS},
            gamma_fourier={s: np.zeros(4) for s in self.OUTCOME_IDS},
            alpha={s: 5.0 for s in self.OUTCOME_IDS},
            control_coef={},
            outcome_control_coef={},
        )

    def _frame(self):
        n = self.N_WEEKS
        X_media = np.zeros((n, 2))
        X_media[self.SPIKE_WEEK, 1] = 500.0  # DNA_Media spend in exactly one week
        return {
            "markets": ["UK"],
            "market_idx": np.zeros(n, dtype=int),
            "market_bounds": [(0, n)],
            "X_media": X_media,
            "promo": np.zeros((n, len(self.OUTCOME_IDS))),
            "trend": np.zeros(n),
            "fourier": np.zeros((n, 4)),
            "control_names": [],
            "X_controls": np.zeros((n, 0)),
            "outcome_controls": {},
            "outcome_control_names": {},
        }

    def test_kit_only_outcome_does_not_inherit_the_extra_halo_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        mu = predict_mu(self._frame(), meta, self._params())
        idx = meta.outcome_ids.index("New Customer")
        baseline = mu[0, idx]
        assert (
            mu[self.SPIKE_WEEK, idx] > baseline
        )  # direct response, same week as the spend
        assert mu[self.SPIKE_WEEK + lag, idx] == pytest.approx(
            baseline
        )  # no lagged response at all

    def test_fh_halo_outcome_does_inherit_the_extra_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        mu = predict_mu(self._frame(), meta, self._params())
        idx = meta.outcome_ids.index("New")
        baseline = mu[0, idx]
        assert mu[self.SPIKE_WEEK, idx] == pytest.approx(
            baseline
        )  # no premature direct-week response
        assert (
            mu[self.SPIKE_WEEK + lag, idx] > baseline
        )  # response lands on the lagged week

    def test_changing_halo_lag_does_not_alter_the_direct_kit_response(self):
        params = self._params()
        frame = self._frame()
        idx = self.OUTCOME_IDS.index("New Customer")
        mu_lag2 = predict_mu(frame, self._meta(dna_lag_weeks=2), params)
        mu_lag5 = predict_mu(frame, self._meta(dna_lag_weeks=5), params)
        np.testing.assert_allclose(mu_lag2[:, idx], mu_lag5[:, idx])

    def test_dna_cross_sell_direct_and_halo_components_add_without_double_counting(
        self,
    ):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        mu = predict_mu(self._frame(), meta, self._params())

        cross_idx = meta.outcome_ids.index("DNA_CrossSell")
        kit_idx = meta.outcome_ids.index(
            "New Customer"
        )  # direct-only, same beta as DNA_CrossSell
        halo_idx = meta.outcome_ids.index(
            "New"
        )  # halo-only, same beta AND halo_strength as DNA_CrossSell

        # At the direct week, dna_halo_media is still zero (the lag hasn't
        # caught up yet), so DNA_CrossSell's response there is *exactly* its
        # direct term alone - identical to the kit-only outcome's (same
        # beta, same weight=1.0). If the direct term were being double
        # counted (e.g. added twice, or the halo term leaking in early),
        # this would no longer match.
        assert mu[self.SPIKE_WEEK, cross_idx] == pytest.approx(
            mu[self.SPIKE_WEEK, kit_idx]
        )

        # At the lagged week, the direct term is back to zero (the spike
        # already passed) so DNA_CrossSell's response is *exactly* its halo
        # term alone - identical to the halo-only outcome's (same beta, same
        # halo_strength). The kit-only outcome shows nothing at all there.
        assert mu[self.SPIKE_WEEK + lag, cross_idx] == pytest.approx(
            mu[self.SPIKE_WEEK + lag, halo_idx]
        )
        assert mu[self.SPIKE_WEEK + lag, kit_idx] == pytest.approx(mu[0, kit_idx])


class TestPredictMuFailsClosedForCandidateA:
    """WP3 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`):
    `predict_mu` has no term for Candidate A's `search_eta_contribution` -
    silently running it on a Candidate A fit would produce a `mu` missing
    that whole pathway's contribution. Must raise instead, protecting every
    downstream caller (curves, scenario planning, backtest, optimisation)
    through this one guard."""

    def test_raises_for_a_candidate_a_engine_meta(self, meta, params):
        import dataclasses

        from ancestry_mmm.core.predict import CandidateAReplayNotSupportedError
        from ancestry_mmm.core.search_capacity import SEARCH_CANDIDATE_A_ENGINE

        candidate_a_meta = dataclasses.replace(
            meta, causal_graph_engine=SEARCH_CANDIDATE_A_ENGINE
        )
        frame = {
            "X_media": np.zeros((3, len(CHANNELS))),
            "market_bounds": [(0, 3)],
            "market_idx": np.zeros(3, dtype=int),
            "promo": np.zeros((3, len(OUTCOME_IDS))),
            "trend": np.zeros(3),
            "fourier": np.zeros((3, 2)),
        }
        with pytest.raises(CandidateAReplayNotSupportedError):
            predict_mu(frame, candidate_a_meta, params)


class TestPredictMuFailsClosedForNamedEvents:
    """Production integration (Decision 12, `core.named_event_fit_inputs`):
    `predict_mu` has no term for a fit's `event_coefs_<family>_<market>`
    contribution - silently running it on a fit that consumed a named-event
    response definition would produce a `mu` missing that pathway's
    contribution, biased specifically in the planted event weeks. Must
    raise instead, mirroring the identical Candidate A guard above."""

    def test_raises_for_a_meta_with_a_consumed_response_definition(self, meta, params):
        import dataclasses

        from ancestry_mmm.core.predict import NamedEventReplayNotSupportedError

        named_event_meta = dataclasses.replace(
            meta,
            named_event_response_definitions_at_fit=[("mothers-day-def", 1)],
        )
        frame = {
            "X_media": np.zeros((3, len(CHANNELS))),
            "market_bounds": [(0, 3)],
            "market_idx": np.zeros(3, dtype=int),
            "promo": np.zeros((3, len(OUTCOME_IDS))),
            "trend": np.zeros(3),
            "fourier": np.zeros((3, 2)),
        }
        with pytest.raises(NamedEventReplayNotSupportedError):
            predict_mu(frame, named_event_meta, params)


class TestPredictMuFailsClosedForAmbiguousSeoReplay:
    """Explicit SEO replay must not reuse one vector for several groups."""

    def test_multi_group_explicit_replay_requires_group_specific_values(
        self, meta, params
    ):
        from ancestry_mmm.core.predict import CandidateAReplayNotSupportedError

        frame = {
            "X_media": np.zeros((3, len(CHANNELS))),
            "market_bounds": [(0, 3)],
            "market_idx": np.zeros(3, dtype=int),
            "promo": np.zeros((3, len(OUTCOME_IDS))),
            "trend": np.zeros(3),
            "fourier": np.zeros((3, len(params.gamma_fourier["New"]))),
            "markets": ["UK"],
            "dates": pd.date_range("2026-01-05", periods=3, freq="W").values,
        }
        multi_group_meta = replace(
            meta,
            seo_fit_inputs_at_fit={
                "groups": [
                    {
                        "seo_group_id": "brand",
                        "model_markets": ["UK"] * 3,
                        "model_weeks": ["2026-01-05", "2026-01-12", "2026-01-19"],
                        "standardized_visibility": [0.1, 0.2, 0.3],
                        "active_mask": [1.0, 1.0, 1.0],
                    },
                    {
                        "seo_group_id": "non_brand",
                        "model_markets": ["UK"] * 3,
                        "model_weeks": ["2026-01-05", "2026-01-12", "2026-01-19"],
                        "standardized_visibility": [0.4, 0.5, 0.6],
                        "active_mask": [1.0, 1.0, 1.0],
                    },
                ]
            },
        )
        multi_group_params = replace(
            params,
            seo_visibility_betas={
                "brand": np.array([0.1, 0.2]),
                "non_brand": np.array([0.3, 0.4]),
            },
        )

        with pytest.raises(CandidateAReplayNotSupportedError, match="group-specific"):
            predict_mu(
                frame,
                multi_group_meta,
                multi_group_params,
                seo_visibility_values=np.ones(3),
                seo_visibility_active_mask=np.ones(3),
            )

    def test_ordinary_fit_with_no_named_events_is_unaffected(self, meta, params):
        """Backward compatibility: a meta with the field left at its
        default empty list must not trigger the guard - every fit before
        this field existed keeps working exactly as before."""
        assert meta.named_event_response_definitions_at_fit == []
        n_fourier = len(params.gamma_fourier["New"])
        frame = {
            "X_media": np.zeros((3, len(CHANNELS))),
            "market_bounds": [(0, 3)],
            "market_idx": np.zeros(3, dtype=int),
            "promo": np.zeros((3, len(OUTCOME_IDS))),
            "trend": np.zeros(3),
            "fourier": np.zeros((3, n_fourier)),
        }
        # Must not raise.
        predict_mu(frame, meta, params)


def _named_event_registry():
    """A minimal governed named-event registry (family, occurrence,
    response definition) for the predict/scenario-replay gap-closure
    tests below - mirrors test_named_event_fit_inputs.py's own fixtures."""
    from ancestry_mmm.core.named_event_response import NAMED_EVENT_RESPONSE_STRUCTURE
    from ancestry_mmm.core.named_events import (
        EventResponseDefinition,
        NamedEventFamily,
        NamedEventOccurrence,
    )

    family = NamedEventFamily(
        family_id="mothers_day",
        family_version=1,
        display_name="Mother's Day",
        classification="gifting",
    )
    occurrence = NamedEventOccurrence(
        event_id="md-2026",
        event_version=1,
        display_name="Mother's Day 2026",
        start_date="2026-01-25",
        end_date="2026-01-25",
        market_scope=("UK",),
        source_id="events",
        family_id="mothers_day",
    )
    definition = EventResponseDefinition(
        response_definition_id="md-def",
        response_definition_version=1,
        family_id="mothers_day",
        treatment="anticipatory",
        max_lead=3,
        max_lag=0,
        transformation_method_reference=NAMED_EVENT_RESPONSE_STRUCTURE,
    )
    return family, occurrence, definition


class TestPredictMuNamedEventReplay:
    """Production integration: predict/scenario-replay gap closure
    (Decision 12) - `predict_mu`, given a `named_event_fit_inputs` built
    for this replay frame, must replay the already-fitted `event_coefs_
    <family>_<market>` posterior coefficients EXACTLY - a deterministic
    check (not a statistical recovery test), since replaying an
    already-fitted coefficient vector through a known design matrix has
    exactly one correct numeric answer."""

    @pytest.fixture
    def frame(self, params):
        n = 8
        n_fourier = len(params.gamma_fourier["New"])
        return {
            "X_media": np.zeros((n, len(CHANNELS))),
            "market_bounds": [(0, n)],
            "market_idx": np.zeros(n, dtype=int),
            "promo": np.zeros((n, len(OUTCOME_IDS))),
            "trend": np.zeros(n),
            "fourier": np.zeros((n, n_fourier)),
            "markets": ["UK"],
            "dates": pd.date_range("2026-01-05", periods=n, freq="W").values,
        }

    def test_replay_matches_manual_design_times_coefficients(self, meta, params, frame):
        from ancestry_mmm.core.named_event_fit_inputs import (
            build_named_event_fit_inputs_for_replay,
        )

        family, occurrence, definition = _named_event_registry()
        named_event_meta = replace(
            meta,
            named_event_response_definitions_at_fit=[("md-def", 1)],
            named_event_fit_blocks=[("mothers_day", "UK")],
        )
        event_coefs_vector = np.array([0.4, -0.2, 0.15, 0.05, 0.02, 0.01])
        named_params = replace(
            params, event_coefs={"mothers_day": {"UK": event_coefs_vector}}
        )
        fit_inputs = build_named_event_fit_inputs_for_replay(
            frame,
            families=[family],
            occurrences=[occurrence],
            response_definitions=[definition],
            fitted_response_definitions=(
                named_event_meta.named_event_response_definitions_at_fit
            ),
        )
        assert len(fit_inputs.blocks) == 1
        block = fit_inputs.blocks[0]
        assert block.design.shape[1] == len(event_coefs_vector)

        baseline_mu = predict_mu(frame, meta, params)
        mu_with_event = predict_mu(
            frame, named_event_meta, named_params, named_event_fit_inputs=fit_inputs
        )
        contrib = block.design @ event_coefs_vector
        assert np.any(contrib != 0.0)  # the window actually has support here
        expected = baseline_mu * np.exp(contrib)[:, None]
        np.testing.assert_allclose(mu_with_event, expected, rtol=1e-10)

    def test_outcome_scope_restricts_the_contribution_to_named_outcomes(
        self, meta, params, frame
    ):
        from ancestry_mmm.core.named_event_fit_inputs import (
            build_named_event_fit_inputs_for_replay,
        )

        family, occurrence, definition = _named_event_registry()
        scoped_definition = replace(definition, outcome_scope=("New",))
        named_event_meta = replace(
            meta,
            named_event_response_definitions_at_fit=[("md-def", 1)],
            named_event_fit_blocks=[("mothers_day", "UK")],
        )
        event_coefs_vector = np.array([0.4, -0.2, 0.15, 0.05, 0.02, 0.01])
        named_params = replace(
            params, event_coefs={"mothers_day": {"UK": event_coefs_vector}}
        )
        fit_inputs = build_named_event_fit_inputs_for_replay(
            frame,
            families=[family],
            occurrences=[occurrence],
            response_definitions=[scoped_definition],
            fitted_response_definitions=(
                named_event_meta.named_event_response_definitions_at_fit
            ),
        )
        baseline_mu = predict_mu(frame, meta, params)
        mu_with_event = predict_mu(
            frame, named_event_meta, named_params, named_event_fit_inputs=fit_inputs
        )
        new_idx = OUTCOME_IDS.index("New")
        other_idx = OUTCOME_IDS.index("DNA_CrossSell")
        contrib = fit_inputs.blocks[0].design @ event_coefs_vector
        assert np.any(contrib != 0.0)
        np.testing.assert_allclose(
            mu_with_event[:, new_idx],
            baseline_mu[:, new_idx] * np.exp(contrib),
            rtol=1e-10,
        )
        # The unscoped outcome must be completely untouched.
        np.testing.assert_allclose(
            mu_with_event[:, other_idx], baseline_mu[:, other_idx]
        )

    def test_a_block_that_was_never_actually_fit_contributes_zero(
        self, meta, params, frame
    ):
        """Decision 12's own unpooled-by-default choice means a (family,
        market) pair the replay frame implies an event for, but that was
        never actually fit (absent from meta.named_event_fit_blocks), has
        no coefficients to borrow - contributes zero rather than
        fabricating or pooling from elsewhere."""
        from ancestry_mmm.core.named_event_fit_inputs import (
            build_named_event_fit_inputs_for_replay,
        )

        family, occurrence, definition = _named_event_registry()
        # named_event_fit_blocks deliberately left empty: this (family,
        # market) pair was never fit, even though the registry/frame
        # combination below produces a real design block for it.
        named_event_meta = replace(
            meta,
            named_event_response_definitions_at_fit=[("md-def", 1)],
            named_event_fit_blocks=[],
        )
        fit_inputs = build_named_event_fit_inputs_for_replay(
            frame,
            families=[family],
            occurrences=[occurrence],
            response_definitions=[definition],
            fitted_response_definitions=(
                named_event_meta.named_event_response_definitions_at_fit
            ),
        )
        assert len(fit_inputs.blocks) == 1  # a real block exists...
        baseline_mu = predict_mu(frame, meta, params)
        mu_with_event = predict_mu(
            frame, named_event_meta, params, named_event_fit_inputs=fit_inputs
        )
        # ...but it was never fit, so it must contribute nothing.
        np.testing.assert_allclose(mu_with_event, baseline_mu)

    def test_supplying_an_explicitly_empty_fit_inputs_does_not_raise(
        self, meta, params, frame
    ):
        """None (not supplied) means "caller did not attempt replay
        support" and still raises; an actual (possibly block-empty)
        NamedEventFitInputs instance means "replay support was attempted"
        and must not raise, even when it legitimately has nothing to add
        for this particular frame."""
        from ancestry_mmm.core.named_event_fit_inputs import NamedEventFitInputs

        named_event_meta = replace(
            meta, named_event_response_definitions_at_fit=[("md-def", 1)]
        )
        empty_inputs = NamedEventFitInputs(
            blocks=(), shrinkage_prior_scale_by_family={}
        )
        mu = predict_mu(
            frame, named_event_meta, params, named_event_fit_inputs=empty_inputs
        )
        baseline_mu = predict_mu(frame, meta, params)
        np.testing.assert_allclose(mu, baseline_mu)

    def test_still_raises_when_fit_inputs_not_supplied_at_all(
        self, meta, params, frame
    ):
        """Regression guard: the original fail-closed contract must
        survive this change for any caller that has not been updated yet."""
        from ancestry_mmm.core.predict import NamedEventReplayNotSupportedError

        named_event_meta = replace(
            meta, named_event_response_definitions_at_fit=[("md-def", 1)]
        )
        with pytest.raises(NamedEventReplayNotSupportedError):
            predict_mu(frame, named_event_meta, params)


class TestExtractEventCoefs:
    """`core.predict.extract_event_coefs` / `extract_posterior_params`'s
    new `event_coefs` field - reads `event_coefs_<family_id>_<market>`
    posterior variables named exactly as `core.hierarchical_model.
    build_fh_hierarchical_model` fits them, keyed by
    `meta.named_event_fit_blocks` (never by parsing the variable name back
    apart, which would be ambiguous for a family_id/market containing an
    underscore)."""

    @pytest.fixture
    def trace_with_event_coefs(self) -> az.InferenceData:
        n_chain, n_draw = 2, 5
        coords = {
            "channel": CHANNELS,
            "outcome": OUTCOME_IDS,
            "fourier": list(range(6)),
            "event_basis_mothers_day_UK": list(range(3)),
        }
        rng = np.random.default_rng(2)

        def const(value):
            arr = np.asarray(value, dtype=float)
            return np.broadcast_to(arr, (n_chain, n_draw) + arr.shape).copy()

        posterior = {
            "decay_rate": const([0.7, 0.5]),
            "hill_K": const([1000.0, 500.0]),
            "hill_S": const([1.2, 1.0]),
            "beta": const([[0.10, 0.05], [0.02, 0.20]]),
            "promo_coef": const([0.2, 0.3]),
            "market_offset": const([[0.0, 0.0]]),
            "intercept": const([3.0, 2.0]),
            "trend_coef": const([0.1, 0.05]),
            "gamma_fourier": const(np.zeros((6, 2))),
            "alpha": const([5.0, 5.0]),
            "event_coefs_mothers_day_UK": const([0.4, -0.2, 0.1])
            + rng.normal(0, 1e-6, size=(n_chain, n_draw, 3)),
        }
        dims = {
            "decay_rate": ["channel"],
            "hill_K": ["channel"],
            "hill_S": ["channel"],
            "beta": ["outcome", "channel"],
            "promo_coef": ["outcome"],
            "market_offset": ["market", "outcome"],
            "intercept": ["outcome"],
            "trend_coef": ["outcome"],
            "gamma_fourier": ["fourier", "outcome"],
            "alpha": ["outcome"],
            "event_coefs_mothers_day_UK": ["event_basis_mothers_day_UK"],
        }
        coords["market"] = ["UK"]
        return az.from_dict(posterior=posterior, coords=coords, dims=dims)

    def test_extracts_the_named_variable_keyed_by_family_then_market(
        self, meta, trace_with_event_coefs
    ):
        from ancestry_mmm.core.predict import extract_event_coefs

        named_event_meta = replace(meta, named_event_fit_blocks=[("mothers_day", "UK")])
        event_coefs = extract_event_coefs(trace_with_event_coefs, named_event_meta)
        np.testing.assert_allclose(
            event_coefs["mothers_day"]["UK"], [0.4, -0.2, 0.1], atol=1e-3
        )

    def test_empty_fit_blocks_returns_empty_dict(self, meta, trace_with_event_coefs):
        """Backward compatibility: a meta with no named_event_fit_blocks
        (every fit before this field existed, or any fit that never
        consumed a named event) must never try to read a variable that
        does not exist for it."""
        from ancestry_mmm.core.predict import extract_event_coefs

        assert meta.named_event_fit_blocks == []
        event_coefs = extract_event_coefs(trace_with_event_coefs, meta)
        assert event_coefs == {}

    def test_extract_posterior_params_populates_event_coefs(
        self, meta, trace_with_event_coefs
    ):
        named_event_meta = replace(meta, named_event_fit_blocks=[("mothers_day", "UK")])
        params = extract_posterior_params(trace_with_event_coefs, named_event_meta)
        np.testing.assert_allclose(
            params.event_coefs["mothers_day"]["UK"], [0.4, -0.2, 0.1], atol=1e-3
        )

    def test_at_selects_one_draw_instead_of_averaging(
        self, meta, trace_with_event_coefs
    ):
        named_event_meta = replace(meta, named_event_fit_blocks=[("mothers_day", "UK")])
        from ancestry_mmm.core.predict import extract_event_coefs

        draw_a = extract_event_coefs(
            trace_with_event_coefs, named_event_meta, at=(0, 0)
        )
        draw_b = extract_event_coefs(
            trace_with_event_coefs, named_event_meta, at=(1, 3)
        )
        assert not np.allclose(draw_a["mothers_day"]["UK"], draw_b["mothers_day"]["UK"])
