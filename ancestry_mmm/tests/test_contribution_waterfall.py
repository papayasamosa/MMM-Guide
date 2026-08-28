"""Tests for core.contribution_waterfall - the generalised Shapley
period-over-period contribution waterfall (WP2F implementation),
following docs/wp2f_contribution_waterfall_design_note.md exactly.
Hand-constructed FHModelMeta/InferenceData/frame, no PyMC/MCMC
involved, matching this project's existing convention
(test_attribution.py, test_uncertainty.py,
test_outcome_valuation_reporting.py)."""

from __future__ import annotations

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.attribution import compute_shapley_contributions
from ancestry_mmm.core.contribution_waterfall import (
    BASELINE_COMPONENT,
    MissingGeneralisedEtaComponentError,
    compute_contribution_waterfall_bridge,
    compute_generalised_shapley_contributions,
    extract_generalised_eta_terms,
    sorted_presented_components,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.predict import extract_posterior_params

OUTCOME_IDS = ["New"]
CHANNELS = ["TV_Brand", "Search"]
MARKETS = ["UK"]
N_WEEKS = 8
WEEK_STARTS = [
    (pd.Timestamp("2025-01-06") + pd.Timedelta(weeks=i)).strftime("%Y-%m-%d")
    for i in range(N_WEEKS)
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
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0, 1],
        dna_outcome_id="New",
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
    )


def _build_trace(
    *,
    n_chain=2,
    n_draw=10,
    market_value=0.4,
    trend_values=None,
    season_values=None,
    promo_values=None,
    controls_values=None,
) -> az.InferenceData:
    """A trace carrying both the standard `extract_posterior_params`
    variables AND the five generalised-eta Deterministics this module
    reads directly by name. `market_value` is a SINGLE scalar broadcast
    identically to every obs row - mirroring the real fitted model's
    `eta_market` (indexed by market only, constant within one market) -
    so Section 4's zero-delta proof is genuinely exercised, not merely
    assumed, by these fixtures."""
    rng = np.random.default_rng(7)
    coords = {
        "outcome": OUTCOME_IDS,
        "channel": CHANNELS,
        "market": MARKETS,
        "obs": list(range(N_WEEKS)),
    }

    def const(value):
        return _const_broadcast(value, n_chain, n_draw)

    trend_values = (
        trend_values if trend_values is not None else np.linspace(0.0, 0.3, N_WEEKS)
    )
    season_values = (
        season_values if season_values is not None else np.linspace(0.1, -0.1, N_WEEKS)
    )
    promo_values = promo_values if promo_values is not None else np.zeros(N_WEEKS)
    controls_values = (
        controls_values
        if controls_values is not None
        else np.linspace(-0.05, 0.05, N_WEEKS)
    )

    posterior = {
        "decay_rate": const([0.5, 0.3]),
        "hill_K": const([1000.0, 800.0])
        * (1 + rng.normal(0, 0.02, size=(n_chain, n_draw, 2))),
        "hill_S": const([1.0, 1.0]),
        "beta": const([[0.10, 0.06]])
        * (1 + rng.normal(0, 0.05, size=(n_chain, n_draw, 1, 2))),
        "halo_strength": const([0.0, 0.0]),
        "promo_coef": const([0.0]),
        "market_offset": const([[0.0]]),
        "intercept": const([3.0]),
        "trend_coef": const([0.0]),
        "gamma_fourier": const(np.zeros((4, 1))),
        "alpha": const([5.0]),
        "eta_market": const(np.full((N_WEEKS, 1), market_value)),
        "eta_trend": const(np.tile(trend_values[:, None], (1, 1))),
        "eta_season": const(np.tile(season_values[:, None], (1, 1))),
        "eta_promo": const(np.tile(promo_values[:, None], (1, 1))),
        "eta_controls": const(np.tile(controls_values[:, None], (1, 1))),
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "beta": ["outcome", "channel"],
        "halo_strength": ["channel"],
        "promo_coef": ["outcome"],
        "market_offset": ["market", "outcome"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"],
        "alpha": ["outcome"],
        "eta_market": ["obs", "outcome"],
        "eta_trend": ["obs", "outcome"],
        "eta_season": ["obs", "outcome"],
        "eta_promo": ["obs", "outcome"],
        "eta_controls": ["obs", "outcome"],
    }
    coords["fourier"] = list(range(4))
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


@pytest.fixture
def trace() -> az.InferenceData:
    return _build_trace()


@pytest.fixture
def frame():
    rng = np.random.default_rng(3)
    dates = np.array(WEEK_STARTS, dtype="datetime64[D]")
    return {
        "markets": MARKETS,
        "market_idx": np.zeros(N_WEEKS, dtype=int),
        "market_bounds": [(0, N_WEEKS)],
        "dates": dates,
        "X_media": rng.uniform(50, 500, size=(N_WEEKS, len(CHANNELS))),
        "promo": np.zeros((N_WEEKS, len(OUTCOME_IDS))),
        "trend": np.zeros(N_WEEKS),
        "fourier": np.zeros((N_WEEKS, 4)),
        "control_names": [],
        "X_controls": np.zeros((N_WEEKS, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


class TestExtractGeneralisedEtaTerms:
    def test_reads_all_six_named_terms(self, trace, meta):
        params = extract_posterior_params(trace, meta)
        terms = extract_generalised_eta_terms(trace, meta, params)
        assert set(terms.keys()) == {
            "intercept",
            "market",
            "trend",
            "season",
            "promo",
            "controls",
        }
        for arr in terms.values():
            assert arr.shape == (N_WEEKS, len(OUTCOME_IDS))

    def test_market_term_is_constant_across_weeks(self, trace, meta):
        """Mirrors the real fitted model's eta_market: indexed by market
        only, so constant across every week within one market - the
        premise Section 4's zero-delta proof depends on."""
        params = extract_posterior_params(trace, meta)
        terms = extract_generalised_eta_terms(trace, meta, params)
        assert np.allclose(terms["market"], terms["market"][0])

    def test_intercept_term_is_constant_across_weeks(self, trace, meta):
        params = extract_posterior_params(trace, meta)
        terms = extract_generalised_eta_terms(trace, meta, params)
        assert np.allclose(terms["intercept"], terms["intercept"][0])

    def test_at_a_specific_draw_matches_direct_isel(self, trace, meta):
        params = extract_posterior_params(trace, meta, at=(0, 3))
        terms = extract_generalised_eta_terms(trace, meta, params, at=(0, 3))
        expected_trend = trace.posterior["eta_trend"].isel(chain=0, draw=3).values
        np.testing.assert_allclose(terms["trend"], expected_trend)

    def test_missing_deterministic_raises_named_error(self, meta):
        trace_missing = _build_trace()
        del trace_missing.posterior["eta_controls"]
        params = extract_posterior_params(trace_missing, meta)
        with pytest.raises(MissingGeneralisedEtaComponentError, match="eta_controls"):
            extract_generalised_eta_terms(trace_missing, meta, params)


class TestComputeGeneralisedShapleyContributions:
    def test_reconciles_exactly_with_one_permutation(self, trace, frame, meta):
        """Section 8: the reconciliation invariant holds exactly even
        for n_permutations=1 - Monte Carlo sampling only affects how
        credit is split among players, never whether the total
        reconciles."""
        params = extract_posterior_params(trace, meta)
        result = compute_generalised_shapley_contributions(
            frame, meta, params, trace, n_permutations=1, seed=1
        )
        reconstructed = np.zeros((N_WEEKS, len(OUTCOME_IDS)))
        for p in result["players"]:
            reconstructed = reconstructed + result["contributions"][p]
        np.testing.assert_allclose(
            reconstructed, result["mu_total"], rtol=1e-10, atol=1e-10
        )

    def test_reconciles_with_many_permutations(self, trace, frame, meta):
        params = extract_posterior_params(trace, meta)
        result = compute_generalised_shapley_contributions(
            frame, meta, params, trace, n_permutations=50, seed=9
        )
        reconstructed = np.zeros((N_WEEKS, len(OUTCOME_IDS)))
        for p in result["players"]:
            reconstructed = reconstructed + result["contributions"][p]
        np.testing.assert_allclose(
            reconstructed, result["mu_total"], rtol=1e-8, atol=1e-9
        )

    def test_player_list_is_baseline_plus_decomposed_terms_plus_channels(
        self, trace, frame, meta
    ):
        params = extract_posterior_params(trace, meta)
        result = compute_generalised_shapley_contributions(
            frame, meta, params, trace, n_permutations=2
        )
        assert set(result["players"]) == {
            BASELINE_COMPONENT,
            "trend",
            "season",
            "promo",
            "controls",
            "TV_Brand",
            "Search",
        }

    def test_baseline_component_equals_exp_intercept_plus_market(self, trace, meta):
        params = extract_posterior_params(trace, meta)
        terms = extract_generalised_eta_terms(trace, meta, params)
        expected_reference = np.exp(terms["intercept"] + terms["market"])
        result = compute_generalised_shapley_contributions(
            {
                "X_media": np.zeros((N_WEEKS, len(CHANNELS))),
                "market_bounds": [(0, N_WEEKS)],
            },
            meta,
            params,
            trace,
            n_permutations=1,
        )
        np.testing.assert_allclose(
            result["contributions"][BASELINE_COMPONENT], expected_reference
        )
        np.testing.assert_allclose(result["mu_reference"], expected_reference)

    def test_mu_total_matches_the_existing_shapley_functions_mu_total(self, meta):
        """The generalised decomposition's mu_total must agree with the
        existing, already-approved compute_shapley_contributions's
        mu_total when both are fed a self-consistent fitted structure -
        both replay the identical fitted eta, just split into a
        different player list. Uses a dedicated trace/frame where the
        injected eta_trend/eta_season/eta_promo/eta_controls/eta_market
        Deterministics are actually derived from the same params/frame
        `_baseline_eta` recomputes them from - the shared `trace`/
        `frame` fixtures used elsewhere in this file inject arbitrary,
        mutually-independent values that are not meant to be
        cross-consistent (they only need to be internally
        self-reconciling, which every other test here checks)."""
        rng = np.random.default_rng(11)
        frame = {
            "markets": MARKETS,
            "market_idx": np.zeros(N_WEEKS, dtype=int),
            "market_bounds": [(0, N_WEEKS)],
            "dates": np.array(WEEK_STARTS, dtype="datetime64[D]"),
            "X_media": rng.uniform(50, 500, size=(N_WEEKS, len(CHANNELS))),
            "promo": np.zeros((N_WEEKS, len(OUTCOME_IDS))),
            "trend": np.linspace(0.0, 1.0, N_WEEKS),
            "fourier": np.zeros((N_WEEKS, 4)),
            "control_names": [],
            "X_controls": np.zeros((N_WEEKS, 0)),
            "outcome_controls": {},
            "outcome_control_names": {},
        }
        trend_coef = 0.2
        market_offset = 0.4
        trace = _build_trace(
            market_value=market_offset,
            trend_values=frame["trend"] * trend_coef,
            season_values=np.zeros(N_WEEKS),
            promo_values=np.zeros(N_WEEKS),
            controls_values=np.zeros(N_WEEKS),
        )
        params = extract_posterior_params(trace, meta)
        params.trend_coef["New"] = trend_coef
        params.market_offset["UK"]["New"] = market_offset

        generalised = compute_generalised_shapley_contributions(
            frame, meta, params, trace, n_permutations=50, seed=4
        )
        existing = compute_shapley_contributions(frame, meta, params, n_permutations=50)
        np.testing.assert_allclose(
            generalised["mu_total"], existing["mu_total"], rtol=1e-6, atol=1e-6
        )


class TestComputeContributionWaterfallBridge:
    def test_reconciliation_invariant_holds(self, trace, frame, meta):
        """Section 8's invariant every implementation test must
        enforce: Outcome_A_total + sum(bridge_contributions) ==
        Outcome_B_total, exactly."""
        bridge = compute_contribution_waterfall_bridge(
            trace,
            frame,
            meta,
            market="UK",
            outcome_ids=["New"],
            period_a_weeks=WEEK_STARTS[:3],
            period_b_weeks=WEEK_STARTS[3:6],
            n_draws=5,
            n_permutations=10,
            seed=2,
        )
        bridge_sum = sum(c.bridge_mean for c in bridge.components)
        np.testing.assert_allclose(
            bridge.period_a_outcome_mean + bridge_sum,
            bridge.period_b_outcome_mean,
            rtol=1e-5,
            atol=1e-6,
        )
        np.testing.assert_allclose(bridge.reconciliation_error_mean, 0.0, atol=1e-6)

    def test_reconciliation_holds_with_unequal_period_lengths(self, trace, frame, meta):
        bridge = compute_contribution_waterfall_bridge(
            trace,
            frame,
            meta,
            market="UK",
            outcome_ids=["New"],
            period_a_weeks=WEEK_STARTS[:1],
            period_b_weeks=WEEK_STARTS[1:6],
            n_draws=4,
            n_permutations=10,
            seed=5,
        )
        bridge_sum = sum(c.bridge_mean for c in bridge.components)
        np.testing.assert_allclose(
            bridge.period_a_outcome_mean + bridge_sum,
            bridge.period_b_outcome_mean,
            rtol=1e-5,
            atol=1e-6,
        )

    def test_reconciliation_holds_with_a_zero_spend_channel_in_period_a(
        self, trace, meta
    ):
        frame_zero_spend = {
            "markets": MARKETS,
            "market_idx": np.zeros(N_WEEKS, dtype=int),
            "market_bounds": [(0, N_WEEKS)],
            "dates": np.array(WEEK_STARTS, dtype="datetime64[D]"),
            "X_media": np.array([[0.0, 100.0]] * 3 + [[200.0, 100.0]] * (N_WEEKS - 3)),
            "promo": np.zeros((N_WEEKS, len(OUTCOME_IDS))),
            "trend": np.zeros(N_WEEKS),
            "fourier": np.zeros((N_WEEKS, 4)),
            "control_names": [],
            "X_controls": np.zeros((N_WEEKS, 0)),
            "outcome_controls": {},
            "outcome_control_names": {},
        }
        bridge = compute_contribution_waterfall_bridge(
            trace,
            frame_zero_spend,
            meta,
            market="UK",
            outcome_ids=["New"],
            period_a_weeks=WEEK_STARTS[:3],
            period_b_weeks=WEEK_STARTS[3:6],
            n_draws=4,
            n_permutations=10,
            seed=6,
        )
        bridge_sum = sum(c.bridge_mean for c in bridge.components)
        np.testing.assert_allclose(
            bridge.period_a_outcome_mean + bridge_sum,
            bridge.period_b_outcome_mean,
            rtol=1e-5,
            atol=1e-6,
        )
        tv_component = next(c for c in bridge.components if c.component == "TV_Brand")
        assert tv_component.period_a_mean == pytest.approx(0.0, abs=1e-8)

    def test_baseline_bridge_is_zero_for_equal_length_periods(self, trace, frame, meta):
        """Section 4/13.3's claim, exercised numerically and correctly
        scoped: for a fixed-market bridge with EQUAL-length periods,
        the fused intercept+market baseline contributes exactly zero to
        the delta (recovering Section 4's original claim exactly)."""
        bridge = compute_contribution_waterfall_bridge(
            trace,
            frame,
            meta,
            market="UK",
            outcome_ids=["New"],
            period_a_weeks=WEEK_STARTS[:3],
            period_b_weeks=WEEK_STARTS[5:8],
            n_draws=4,
            n_permutations=10,
            seed=8,
        )
        by_name = {c.component: c for c in bridge.components}
        assert by_name[BASELINE_COMPONENT].bridge_mean == pytest.approx(0.0, abs=1e-8)

    def test_baseline_bridge_is_nonzero_and_honest_for_unequal_length_periods(
        self, trace, frame, meta
    ):
        """Implementation-time correction (this module's docstring):
        for an UNEQUAL-length comparison, the baseline's bridge is
        exactly `(n_B_weeks - n_A_weeks) * mu_reference` - real,
        disclosed information, never hidden."""
        params = extract_posterior_params(trace, meta)
        terms = extract_generalised_eta_terms(trace, meta, params)
        mu_reference_value = float(np.exp(terms["intercept"] + terms["market"])[0, 0])

        period_a_weeks = WEEK_STARTS[:1]
        period_b_weeks = WEEK_STARTS[1:6]
        bridge = compute_contribution_waterfall_bridge(
            trace,
            frame,
            meta,
            market="UK",
            outcome_ids=["New"],
            period_a_weeks=period_a_weeks,
            period_b_weeks=period_b_weeks,
            n_draws=1,
            n_permutations=10,
            seed=8,
        )
        by_name = {c.component: c for c in bridge.components}
        expected = (len(period_b_weeks) - len(period_a_weeks)) * mu_reference_value
        assert by_name[BASELINE_COMPONENT].bridge_mean == pytest.approx(
            expected, rel=1e-6
        )

    def test_every_component_is_presentable(self, trace, frame, meta):
        """Section 13.3's fused reference removes the "computed but
        excluded" category entirely - every returned component is a
        genuine, presentable bridge line."""
        bridge = compute_contribution_waterfall_bridge(
            trace,
            frame,
            meta,
            market="UK",
            outcome_ids=["New"],
            period_a_weeks=WEEK_STARTS[:3],
            period_b_weeks=WEEK_STARTS[3:6],
            n_draws=3,
            n_permutations=5,
        )
        component_names = {c.component for c in bridge.components}
        assert component_names == {
            BASELINE_COMPONENT,
            "trend",
            "season",
            "promo",
            "controls",
            "TV_Brand",
            "Search",
        }

    def test_unknown_outcome_id_raises(self, trace, frame, meta):
        with pytest.raises(ValueError, match="outcome_id"):
            compute_contribution_waterfall_bridge(
                trace,
                frame,
                meta,
                market="UK",
                outcome_ids=["Nonexistent"],
                period_a_weeks=WEEK_STARTS[:2],
                period_b_weeks=WEEK_STARTS[2:4],
            )

    def test_missing_week_coverage_raises(self, trace, frame, meta):
        from ancestry_mmm.core.outcome_valuation_reporting import (
            OutcomeValuationReportingCoverageError,
        )

        with pytest.raises(OutcomeValuationReportingCoverageError):
            compute_contribution_waterfall_bridge(
                trace,
                frame,
                meta,
                market="UK",
                outcome_ids=["New"],
                period_a_weeks=["2099-01-01"],
                period_b_weeks=WEEK_STARTS[2:4],
            )


class TestSortedPresentedComponents:
    def test_positive_descending_then_negative_ascending_magnitude(self):
        from ancestry_mmm.core.contribution_waterfall import ContributionBridgeComponent

        def _component(name, bridge_mean):
            return ContributionBridgeComponent(
                component=name,
                period_a_mean=0.0,
                period_b_mean=bridge_mean,
                bridge_mean=bridge_mean,
                bridge_median=bridge_mean,
                bridge_lower=bridge_mean,
                bridge_upper=bridge_mean,
            )

        components = [
            _component(BASELINE_COMPONENT, 0.0),
            _component("small_drag", -1.0),
            _component("big_boost", 10.0),
            _component("big_drag", -5.0),
            _component("small_boost", 2.0),
        ]
        ordered = sorted_presented_components(components)
        assert [c.component for c in ordered] == [
            "big_boost",
            "small_boost",
            BASELINE_COMPONENT,
            "small_drag",
            "big_drag",
        ]
