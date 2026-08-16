"""Tests for core.sequential_simulation - WP5 (`Media-Mix-Lab: Coding LLM
Next Steps After PR #253`, sequential simulation kernel).

The centrepiece is `TestGoldenEquivalence`: splitting one continuous media
series into a "historical" prefix and a "future" plan, reconstructing
starting state from the prefix, and running the sequential kernel over the
future suffix must reproduce *exactly* what the existing, already-tested
batch replay (`core.predict.predict_mu`) computes for that same suffix when
given the whole series at once. This single equivalence proves adstock
carry-in, Hill saturation, the DNA cross-product/halo lag, and direct/halo
reconciliation are all correct simultaneously, since it is checked against
the model's own already-shipped math rather than a hand re-derivation.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.predict import (
    CandidateAReplayNotSupportedError,
    FHPosteriorParams,
    predict_mu,
)
from ancestry_mmm.core.search_capacity import (
    SEARCH_CANDIDATE_A_ENGINE,
    CandidateASequentialDrawParams,
)
from ancestry_mmm.core.sequential_simulation import (
    SequentialCarryInState,
    WeeklyPlan,
    compute_incremental_outcome,
    reconstruct_starting_state,
    reconstruct_starting_state_market_specific,
    simulate_candidate_a_mediator_state_sequentially,
    simulate_sequential_outcomes,
    simulate_sequential_outcomes_market_specific,
    simulate_sequential_outcomes_posterior,
    simulate_terminal_carryover,
    zero_media_extension_plan,
)
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

CHANNELS = ["TV", "DNA_Media"]
OUTCOME_IDS = ["New", "DNA_CrossSell"]
DNA_LAG_WEEKS = 2
N_FOURIER = 4


def _meta(markets=("UK",), dna_lag_weeks: int = DNA_LAG_WEEKS) -> FHModelMeta:
    return FHModelMeta(
        markets=list(markets),
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell",
        dna_lag_weeks=dna_lag_weeks,
        unpooled_markets=[],
        control_names=[],
    )


def _params(markets=("UK",)) -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV": 0.6, "DNA_Media": 0.4},
        hill_K={"TV": 500.0, "DNA_Media": 300.0},
        hill_S={"TV": 1.0, "DNA_Media": 1.0},
        beta={
            "New": {"TV": 0.02, "DNA_Media": 0.01},
            "DNA_CrossSell": {"TV": 0.0, "DNA_Media": 0.03},
        },
        pathway_strength=pathway_strength_from_flat({"New": 0.4}, "DNA_Media"),
        promo_coef={s: 0.0 for s in OUTCOME_IDS},
        market_offset={m: {s: 0.0 for s in OUTCOME_IDS} for m in markets},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={s: 0.0 for s in OUTCOME_IDS},
        gamma_fourier={s: np.zeros(N_FOURIER) for s in OUTCOME_IDS},
        alpha={s: 5.0 for s in OUTCOME_IDS},
        control_coef={},
        outcome_control_coef={},
    )


def _market_specific_params(markets=("UK",)) -> FHMarketSpecificPosteriorParams:
    shared = _params(markets)
    return FHMarketSpecificPosteriorParams(
        decay_rate=shared.decay_rate,
        hill_K={m: dict(shared.hill_K) for m in markets},
        hill_S=shared.hill_S,
        beta={m: {s: dict(shared.beta[s]) for s in OUTCOME_IDS} for m in markets},
        pathway_strength=shared.pathway_strength,
        promo_coef=shared.promo_coef,
        market_offset=shared.market_offset,
        intercept=shared.intercept,
        trend_coef=shared.trend_coef,
        gamma_fourier=shared.gamma_fourier,
        alpha=shared.alpha,
        control_coef=shared.control_coef,
        outcome_control_coef=shared.outcome_control_coef,
    )


def _full_frame(X_media: np.ndarray, market: str, meta: FHModelMeta) -> Dict:
    n = X_media.shape[0]
    return {
        "markets": [market],
        "market_idx": np.zeros(n, dtype=int),
        "market_bounds": [(0, n)],
        "X_media": X_media,
        "promo": np.zeros((n, len(OUTCOME_IDS))),
        "trend": np.zeros(n),
        "fourier": np.zeros((n, N_FOURIER)),
        "control_names": [],
        "X_controls": np.zeros((n, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


def _plan_from_media(
    market: str, period_labels, X_media: np.ndarray, channels=CHANNELS
) -> WeeklyPlan:
    n = X_media.shape[0]
    return WeeklyPlan(
        market=market,
        period_labels=tuple(period_labels),
        media_by_channel={c: X_media[:, j] for j, c in enumerate(channels)},
        promo=np.zeros((n, len(OUTCOME_IDS))),
        trend=np.zeros(n),
        fourier=np.zeros((n, N_FOURIER)),
    )


class TestGoldenEquivalence:
    """Splitting one series into history + plan and running the sequential
    kernel over the plan must exactly reproduce the batch replay
    (`predict_mu`) over the same series taken as a whole - "adstock
    equivalence to current batch transformation", "Hill equivalence", "DNA
    halo lag", and "direct/halo reconciliation" all at once."""

    def test_shared_model_sequential_matches_full_batch(self):
        meta = _meta()
        params = _params()
        rng = np.random.default_rng(7)
        n_hist, n_future = 12, 9
        X_full = rng.uniform(0.0, 400.0, size=(n_hist + n_future, len(CHANNELS)))

        full_frame = _full_frame(X_full, "UK", meta)
        mu_batch = predict_mu(full_frame, meta, params)

        historical_frame = {
            **full_frame,
            "X_media": X_full[:n_hist],
            "market_bounds": [(0, n_hist)],
            "market_idx": np.zeros(n_hist, dtype=int),
        }
        carry_in = reconstruct_starting_state(historical_frame, meta, params, "UK")
        plan = _plan_from_media(
            "UK", [f"w{i}" for i in range(n_future)], X_full[n_hist:]
        )
        result = simulate_sequential_outcomes(plan, carry_in, meta, params)

        np.testing.assert_allclose(result.mu, mu_batch[n_hist:], rtol=1e-10, atol=1e-10)

    def test_market_specific_model_sequential_matches_full_batch(self):
        meta = _meta()
        params = _market_specific_params()
        rng = np.random.default_rng(11)
        n_hist, n_future = 10, 6
        X_full = rng.uniform(0.0, 400.0, size=(n_hist + n_future, len(CHANNELS)))

        full_frame = _full_frame(X_full, "UK", meta)
        from ancestry_mmm.core.market_specific_predict import predict_mu_market_specific

        mu_batch = predict_mu_market_specific(full_frame, meta, params)

        historical_frame = {
            **full_frame,
            "X_media": X_full[:n_hist],
            "market_bounds": [(0, n_hist)],
            "market_idx": np.zeros(n_hist, dtype=int),
        }
        carry_in = reconstruct_starting_state_market_specific(
            historical_frame, meta, params, "UK"
        )
        plan = _plan_from_media(
            "UK", [f"w{i}" for i in range(n_future)], X_full[n_hist:]
        )
        result = simulate_sequential_outcomes_market_specific(
            plan, carry_in, meta, params
        )

        np.testing.assert_allclose(result.mu, mu_batch[n_hist:], rtol=1e-10, atol=1e-10)

    def test_second_market_in_meta_still_matches_batch(self):
        # Regression guard for the market_idx bug this test suite caught
        # during development: plan.market not being meta.markets[0] must
        # still index the right market_offset row. historical_frame is the
        # full production frame (both markets, market_bounds ordered to
        # match meta.markets) - the same convention core.predict.predict_mu
        # always assumes; reconstruct_starting_state slices out just the
        # requested market's own block.
        meta = _meta(markets=("UK", "IE"))
        params = _params(markets=("UK", "IE"))
        params.market_offset["IE"] = {"New": 0.3, "DNA_CrossSell": -0.2}
        rng = np.random.default_rng(3)
        n_hist, n_future = 8, 5
        n_uk = n_hist + n_future
        n_ie = n_hist + n_future
        X_uk = rng.uniform(0.0, 300.0, size=(n_uk, len(CHANNELS)))
        X_ie = rng.uniform(0.0, 300.0, size=(n_ie, len(CHANNELS)))
        X_all = np.concatenate([X_uk, X_ie], axis=0)

        full_frame = {
            "markets": ["UK", "IE"],
            "market_idx": np.array([0] * n_uk + [1] * n_ie),
            "market_bounds": [(0, n_uk), (n_uk, n_uk + n_ie)],
            "X_media": X_all,
            "promo": np.zeros((n_uk + n_ie, len(OUTCOME_IDS))),
            "trend": np.zeros(n_uk + n_ie),
            "fourier": np.zeros((n_uk + n_ie, N_FOURIER)),
            "control_names": [],
            "X_controls": np.zeros((n_uk + n_ie, 0)),
            "outcome_controls": {},
            "outcome_control_names": {},
        }
        mu_batch = predict_mu(full_frame, meta, params)
        ie_start = n_uk

        historical_frame = {
            **full_frame,
            "X_media": np.concatenate([X_uk[:n_hist], X_ie[:n_hist]], axis=0),
            "market_bounds": [(0, n_hist), (n_hist, 2 * n_hist)],
            "market_idx": np.array([0] * n_hist + [1] * n_hist),
        }
        carry_in = reconstruct_starting_state(historical_frame, meta, params, "IE")
        plan = _plan_from_media("IE", [f"w{i}" for i in range(n_future)], X_ie[n_hist:])
        result = simulate_sequential_outcomes(plan, carry_in, meta, params)
        np.testing.assert_allclose(
            result.mu, mu_batch[ie_start + n_hist :], rtol=1e-10, atol=1e-10
        )


class TestReconstructStartingState:
    def test_zero_history_gives_zero_starting_adstock(self):
        meta = _meta()
        params = _params()
        historical_frame = _full_frame(np.zeros((6, 2)), "UK", meta)
        carry_in = reconstruct_starting_state(historical_frame, meta, params, "UK")
        assert carry_in.starting_adstock == {"TV": 0.0, "DNA_Media": 0.0}

    def test_nonzero_history_reconstructs_matching_raw_adstock(self):
        meta = _meta()
        params = _params()
        X = np.array([[100.0, 0.0], [0.0, 0.0], [0.0, 50.0]])
        historical_frame = _full_frame(X, "UK", meta)
        carry_in = reconstruct_starting_state(historical_frame, meta, params, "UK")
        # Hand-computed raw (unnormalized) recursion.
        tv_raw = 0.0 + 0.6 * (0.0 + 0.6 * 100.0)
        dna_raw = 50.0 + 0.4 * (0.0 + 0.4 * 0.0)
        assert carry_in.starting_adstock["TV"] == pytest.approx(tv_raw)
        assert carry_in.starting_adstock["DNA_Media"] == pytest.approx(dna_raw)

    def test_lag_context_is_zero_when_history_is_all_zero(self):
        meta = _meta()
        params = _params()
        historical_frame = _full_frame(np.zeros((6, 2)), "UK", meta)
        carry_in = reconstruct_starting_state(historical_frame, meta, params, "UK")
        assert carry_in.lag_context_length == DNA_LAG_WEEKS
        assert np.allclose(carry_in.lag_context_sat_media, 0.0)

    def test_lag_context_reflects_real_recent_history(self):
        meta = _meta()
        params = _params()
        X = np.zeros((6, 2))
        X[-1, 1] = 300.0  # DNA_Media spend in the very last historical week
        historical_frame = _full_frame(X, "UK", meta)
        carry_in = reconstruct_starting_state(historical_frame, meta, params, "UK")
        # The most recent lag-context row (DNA_Media column) must be nonzero.
        assert carry_in.lag_context_sat_media[-1, 1] > 0.0

    def test_short_history_left_pads_lag_context_with_zeros(self):
        meta = _meta()  # lag = 2
        params = _params()
        X = np.array([[0.0, 40.0]])  # only 1 historical week, lag needs 2
        historical_frame = _full_frame(X, "UK", meta)
        carry_in = reconstruct_starting_state(historical_frame, meta, params, "UK")
        assert carry_in.lag_context_sat_media.shape == (2, 2)
        assert np.allclose(carry_in.lag_context_sat_media[0], 0.0)  # padded

    def test_unknown_market_raises(self):
        meta = _meta()
        params = _params()
        historical_frame = _full_frame(np.zeros((3, 2)), "UK", meta)
        with pytest.raises(ValueError, match="not one of this model's markets"):
            reconstruct_starting_state(historical_frame, meta, params, "FR")


class TestNoMarketLeakage:
    def test_changing_another_markets_history_does_not_affect_this_markets_carry_in(
        self,
    ):
        meta = _meta(markets=("UK", "IE"))
        params = _params(markets=("UK", "IE"))
        uk_history = np.array([[100.0, 20.0], [50.0, 0.0], [0.0, 30.0]])

        def build_frame(ie_history: np.ndarray) -> Dict:
            X = np.concatenate([uk_history, ie_history], axis=0)
            n_uk = uk_history.shape[0]
            n_ie = ie_history.shape[0]
            return {
                "markets": ["UK", "IE"],
                "market_idx": np.array([0] * n_uk + [1] * n_ie),
                "market_bounds": [(0, n_uk), (n_uk, n_uk + n_ie)],
                "X_media": X,
                "promo": np.zeros((n_uk + n_ie, len(OUTCOME_IDS))),
                "trend": np.zeros(n_uk + n_ie),
                "fourier": np.zeros((n_uk + n_ie, N_FOURIER)),
                "control_names": [],
                "X_controls": np.zeros((n_uk + n_ie, 0)),
                "outcome_controls": {},
                "outcome_control_names": {},
            }

        frame_a = build_frame(np.zeros((3, 2)))
        frame_b = build_frame(
            np.array([[999.0, 999.0], [999.0, 999.0], [999.0, 999.0]])
        )

        carry_in_a = reconstruct_starting_state(frame_a, meta, params, "UK")
        carry_in_b = reconstruct_starting_state(frame_b, meta, params, "UK")

        assert carry_in_a.starting_adstock == pytest.approx(carry_in_b.starting_adstock)
        np.testing.assert_allclose(
            carry_in_a.lag_context_sat_media, carry_in_b.lag_context_sat_media
        )


class TestWeeklyRecursionBehaviour:
    def test_zero_media_and_zero_carry_in_gives_baseline_only(self):
        meta = _meta()
        params = _params()
        n = 5
        carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        plan = _plan_from_media("UK", [f"w{i}" for i in range(n)], np.zeros((n, 2)))
        result = simulate_sequential_outcomes(plan, carry_in, meta, params)

        for oid in OUTCOME_IDS:
            idx = meta.outcome_ids.index(oid)
            expected = np.exp(params.intercept[oid])
            np.testing.assert_allclose(result.mu[:, idx], expected)

    def test_one_week_impulse_decays_and_the_halo_lands_on_the_lagged_week(self):
        meta = _meta()
        params = _params()
        n = 8
        carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        X = np.zeros((n, 2))
        X[0, 1] = 300.0  # DNA_Media impulse in week 0 only
        plan = _plan_from_media("UK", [f"w{i}" for i in range(n)], X)
        result = simulate_sequential_outcomes(plan, carry_in, meta, params)

        cross_idx = meta.outcome_ids.index("DNA_CrossSell")  # direct pathway only
        new_idx = meta.outcome_ids.index("New")  # halo pathway only

        baseline_cross = np.exp(params.intercept["DNA_CrossSell"])
        baseline_new = np.exp(params.intercept["New"])

        # Direct (DNA_CrossSell) responds immediately, in week 0.
        assert result.mu[0, cross_idx] > baseline_cross
        # Direct response decays monotonically afterward (single impulse).
        direct_series = result.mu[:, cross_idx]
        assert np.all(np.diff(direct_series) <= 1e-9)

        # Halo (New) shows nothing before the lag catches up...
        np.testing.assert_allclose(result.mu[0, new_idx], baseline_new)
        # ...and responds once the lag lands.
        assert result.mu[DNA_LAG_WEEKS, new_idx] > baseline_new

    def test_nonzero_historical_carry_in_changes_week_one_output(self):
        meta = _meta()
        params = _params()
        n = 4
        zero_carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        real_carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 200.0, "DNA_Media": 100.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        plan = _plan_from_media("UK", [f"w{i}" for i in range(n)], np.zeros((n, 2)))

        result_zero = simulate_sequential_outcomes(plan, zero_carry_in, meta, params)
        result_real = simulate_sequential_outcomes(plan, real_carry_in, meta, params)

        cross_idx = meta.outcome_ids.index("DNA_CrossSell")
        assert result_real.mu[0, cross_idx] > result_zero.mu[0, cross_idx]


class TestCandidateReferenceContract:
    """Candidate and reference scenarios must use the same simulator and
    the same non-decision assumptions; no-change must be exactly zero
    incremental effect - release blocking per the brief."""

    def _carry_in(self) -> SequentialCarryInState:
        return SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 50.0, "DNA_Media": 20.0},
            lag_context_sat_media=np.full((DNA_LAG_WEEKS, len(CHANNELS)), 0.1),
            lag_context_length=DNA_LAG_WEEKS,
        )

    def test_no_change_scenario_invariant_is_zero(self):
        meta = _meta()
        params = _params()
        n = 6
        rng = np.random.default_rng(5)
        X = rng.uniform(0.0, 200.0, size=(n, 2))
        candidate_plan = _plan_from_media("UK", [f"w{i}" for i in range(n)], X)
        reference_plan = _plan_from_media("UK", [f"w{i}" for i in range(n)], X.copy())
        carry_in = self._carry_in()

        candidate = simulate_sequential_outcomes(candidate_plan, carry_in, meta, params)
        reference = simulate_sequential_outcomes(reference_plan, carry_in, meta, params)

        incremental = compute_incremental_outcome(candidate, reference)
        np.testing.assert_allclose(incremental, 0.0, atol=1e-10)

    def test_different_plans_produce_nonzero_incremental_effect(self):
        meta = _meta()
        params = _params()
        n = 4
        carry_in = self._carry_in()
        candidate_plan = _plan_from_media(
            "UK", [f"w{i}" for i in range(n)], np.full((n, 2), 200.0)
        )
        reference_plan = _plan_from_media(
            "UK", [f"w{i}" for i in range(n)], np.zeros((n, 2))
        )
        candidate = simulate_sequential_outcomes(candidate_plan, carry_in, meta, params)
        reference = simulate_sequential_outcomes(reference_plan, carry_in, meta, params)
        incremental = compute_incremental_outcome(candidate, reference)
        assert np.all(incremental > 0.0)

    def test_mismatched_market_raises(self):
        meta = _meta(markets=("UK", "IE"))
        params = _params(markets=("UK", "IE"))
        n = 3
        uk_carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        ie_carry_in = SequentialCarryInState(
            market="IE",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        uk_plan = _plan_from_media("UK", [f"w{i}" for i in range(n)], np.zeros((n, 2)))
        ie_plan = _plan_from_media("IE", [f"w{i}" for i in range(n)], np.zeros((n, 2)))
        uk_result = simulate_sequential_outcomes(uk_plan, uk_carry_in, meta, params)
        ie_result = simulate_sequential_outcomes(ie_plan, ie_carry_in, meta, params)
        with pytest.raises(ValueError, match="different markets"):
            compute_incremental_outcome(uk_result, ie_result)


class TestTerminalCarryover:
    def test_terminal_carryover_shows_decaying_residual_response(self):
        meta = _meta()
        params = _params()
        n_plan = 3
        carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        X = np.zeros((n_plan, 2))
        X[-1, 0] = 400.0  # TV spend in the final plan week only
        plan = _plan_from_media("UK", [f"w{i}" for i in range(n_plan)], X)
        plan_result = simulate_sequential_outcomes(plan, carry_in, meta, params)

        n_extension = 5
        extension_plan = zero_media_extension_plan(
            "UK", [f"t{i}" for i in range(n_extension)], meta, N_FOURIER
        )
        terminal = simulate_terminal_carryover(
            extension_plan, plan_result.ending_state, meta, params
        )

        cross_idx = meta.outcome_ids.index("DNA_CrossSell")
        new_idx = meta.outcome_ids.index("New")
        baseline_cross = np.exp(params.intercept["DNA_CrossSell"])
        # TV has no effect on DNA_CrossSell in this fixture (beta=0), so use
        # "New" (TV beta > 0) for the decaying-residual assertion instead.
        baseline_new = np.exp(params.intercept["New"])
        new_series = terminal.mu[:, new_idx]
        assert new_series[0] > baseline_new
        assert np.all(np.diff(new_series) <= 1e-9)  # monotonically decaying
        assert new_series[-1] == pytest.approx(baseline_new, rel=1e-3)
        assert terminal.mu[:, cross_idx] == pytest.approx(
            np.full(n_extension, baseline_cross)
        )

    def test_terminal_carryover_is_a_separate_result_not_merged(self):
        meta = _meta()
        params = _params()
        n_plan = 2
        carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        plan = _plan_from_media(
            "UK", [f"w{i}" for i in range(n_plan)], np.full((n_plan, 2), 100.0)
        )
        plan_result = simulate_sequential_outcomes(plan, carry_in, meta, params)
        plan_mu_before = plan_result.mu.copy()

        extension_plan = zero_media_extension_plan("UK", ["t0", "t1"], meta, N_FOURIER)
        terminal = simulate_terminal_carryover(
            extension_plan, plan_result.ending_state, meta, params
        )

        assert terminal is not plan_result
        assert terminal.mu.shape[0] == 2
        np.testing.assert_array_equal(plan_result.mu, plan_mu_before)


class TestPosteriorHandling:
    def _trace(self, n_chain=2, n_draw=3):
        import arviz as az

        rng = np.random.default_rng(0)
        coords = {
            "outcome": OUTCOME_IDS,
            "channel": CHANNELS,
            "market": ["UK"],
            "fourier": list(range(N_FOURIER)),
        }
        posterior = {
            "decay_rate": rng.uniform(0.2, 0.8, size=(n_chain, n_draw, 2)),
            "hill_K": np.broadcast_to([500.0, 300.0], (n_chain, n_draw, 2)).copy(),
            "hill_S": np.broadcast_to([1.0, 1.0], (n_chain, n_draw, 2)).copy(),
            "beta": np.broadcast_to(
                [[0.02, 0.01], [0.0, 0.03]], (n_chain, n_draw, 2, 2)
            ).copy(),
            "promo_coef": np.zeros((n_chain, n_draw, 2)),
            "market_offset": np.zeros((n_chain, n_draw, 1, 2)),
            "intercept": np.broadcast_to([3.0, 2.0], (n_chain, n_draw, 2)).copy(),
            "trend_coef": np.zeros((n_chain, n_draw, 2)),
            "gamma_fourier": np.zeros((n_chain, n_draw, N_FOURIER, 2)),
            "alpha": np.full((n_chain, n_draw, 2), 5.0),
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

    def test_returns_one_full_path_per_draw_not_a_summary(self):
        meta = _meta()
        trace = self._trace(n_chain=2, n_draw=3)
        n = 4
        carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 10.0, "DNA_Media": 5.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        rng = np.random.default_rng(9)
        X = rng.uniform(0.0, 200.0, size=(n, 2))
        plan = _plan_from_media("UK", [f"w{i}" for i in range(n)], X)

        draws = simulate_sequential_outcomes_posterior(
            plan, carry_in, trace, meta, n_draws=4, seed=1
        )
        assert draws.shape == (4, n, len(OUTCOME_IDS))
        # decay_rate genuinely varies per draw in this fixture, so the
        # resulting paths must not all be identical.
        assert not np.allclose(draws[0], draws[1])


class TestCandidateAMediatorStateSequential:
    """Diagnostic-only sequential replay of Candidate A's demand/capture/cap
    chain - bounded, grants no planning/optimisation eligibility."""

    def _plan_and_carry_in(self, cap_value: float, n: int = 5):
        meta = _meta()
        carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        X = np.zeros((n, 2))
        X[:, 0] = 100.0  # steady TV spend - the demand-driving channel here
        plan = WeeklyPlan(
            market="UK",
            period_labels=tuple(f"w{i}" for i in range(n)),
            media_by_channel={"TV": X[:, 0], "DNA_Media": X[:, 1]},
            promo=np.zeros((n, len(OUTCOME_IDS))),
            trend=np.zeros(n),
            fourier=np.zeros((n, N_FOURIER)),
            candidate_a_paid_search_cap=np.full(n, cap_value),
        )
        return meta, carry_in, plan

    def _candidate_a_params(self) -> CandidateASequentialDrawParams:
        return CandidateASequentialDrawParams(
            demand_channel_names=["TV"],
            demand_intercept=2.0,
            demand_market_offset={"UK": 0.0},
            demand_media_beta={"TV": 0.01},
            capture_share={"paid": 0.4, "organic": 0.3, "direct": 0.2, "unmet": 0.1},
        )

    def test_captured_plus_unmet_equals_demand_sequentially(self):
        meta, carry_in, plan = self._plan_and_carry_in(cap_value=10_000.0)
        params = _params()
        candidate_a_params = self._candidate_a_params()
        state = simulate_candidate_a_mediator_state_sequentially(
            plan, carry_in, meta, params, candidate_a_params
        )
        f = state.forward
        np.testing.assert_allclose(
            f.total_captured_demand + f.unmet_demand,
            f.latent_branded_search_demand,
            rtol=1e-10,
            atol=1e-10,
        )

    def test_non_binding_cap_invariant_raising_cap_does_not_change_capture(self):
        meta, carry_in, plan_low = self._plan_and_carry_in(cap_value=10_000.0)
        _, _, plan_high = self._plan_and_carry_in(cap_value=1_000_000.0)
        params = _params()
        candidate_a_params = self._candidate_a_params()

        state_low = simulate_candidate_a_mediator_state_sequentially(
            plan_low, carry_in, meta, params, candidate_a_params
        )
        state_high = simulate_candidate_a_mediator_state_sequentially(
            plan_high, carry_in, meta, params, candidate_a_params
        )

        assert not np.any(state_low.forward.cap_binding)
        np.testing.assert_allclose(
            state_low.forward.total_captured_demand,
            state_high.forward.total_captured_demand,
        )
        np.testing.assert_allclose(
            state_low.forward.realised_paid_search_delivery,
            state_high.forward.realised_paid_search_delivery,
        )

    def test_missing_cap_raises(self):
        meta = _meta()
        carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        plan = _plan_from_media("UK", ["w0", "w1"], np.zeros((2, 2)))
        with pytest.raises(ValueError, match="candidate_a_paid_search_cap"):
            simulate_candidate_a_mediator_state_sequentially(
                plan, carry_in, meta, _params(), self._candidate_a_params()
            )


class TestUnsupportedGraphRolesFailClosed:
    def test_candidate_a_engine_meta_raises_for_outcome_level_replay(self):
        import dataclasses

        meta = dataclasses.replace(
            _meta(), causal_graph_engine=SEARCH_CANDIDATE_A_ENGINE
        )
        params = _params()
        carry_in = SequentialCarryInState(
            market="UK",
            channels=tuple(CHANNELS),
            starting_adstock={"TV": 0.0, "DNA_Media": 0.0},
            lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
            lag_context_length=DNA_LAG_WEEKS,
        )
        plan = _plan_from_media("UK", ["w0"], np.zeros((1, 2)))
        with pytest.raises(CandidateAReplayNotSupportedError):
            simulate_sequential_outcomes(plan, carry_in, meta, params)


class TestWeeklyPlanValidation:
    def test_missing_channel_raises(self):
        with pytest.raises(ValueError, match="missing planned weekly media"):
            WeeklyPlan(
                market="UK",
                period_labels=("w0", "w1"),
                media_by_channel={"TV": np.zeros(2)},  # DNA_Media missing
                promo=np.zeros((2, len(OUTCOME_IDS))),
                trend=np.zeros(2),
                fourier=np.zeros((2, N_FOURIER)),
            ).to_media_matrix(CHANNELS)

    def test_mismatched_promo_length_raises(self):
        with pytest.raises(ValueError, match="promo"):
            WeeklyPlan(
                market="UK",
                period_labels=("w0", "w1"),
                media_by_channel={c: np.zeros(2) for c in CHANNELS},
                promo=np.zeros((3, len(OUTCOME_IDS))),  # wrong length
                trend=np.zeros(2),
                fourier=np.zeros((2, N_FOURIER)),
            )

    def test_duplicate_period_labels_raise(self):
        with pytest.raises(ValueError, match="unique"):
            WeeklyPlan(
                market="UK",
                period_labels=("w0", "w0"),
                media_by_channel={c: np.zeros(2) for c in CHANNELS},
                promo=np.zeros((2, len(OUTCOME_IDS))),
                trend=np.zeros(2),
                fourier=np.zeros((2, N_FOURIER)),
            )
