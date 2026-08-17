"""Tests for core.planning.terminal_response (Work Package 4 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR262`, brief §5.7/§10.3)."""

from __future__ import annotations

import numpy as np
import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.planning.future_context import (
    OFFICIAL_MODE,
    build_future_context,
)
from ancestry_mmm.core.planning.terminal_response import (
    TerminalResponseError,
    build_zero_decision_terminal_extension_plan,
    evaluate_terminal_incremental_response,
    evaluate_terminal_incremental_response_market_specific,
)
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.sequential_simulation import (
    SequentialCarryInState,
    zero_media_extension_plan,
)
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

CHANNELS = ["TV", "DNA_Media"]
OUTCOME_IDS = ["New", "DNA_CrossSell"]
DNA_LAG_WEEKS = 2
WEEKS = ("2026-06-01", "2026-06-08", "2026-06-15")


def _meta(markets=("UK",)) -> FHModelMeta:
    return FHModelMeta(
        markets=list(markets),
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell",
        dna_lag_weeks=DNA_LAG_WEEKS,
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
        promo_coef={s: 0.05 for s in OUTCOME_IDS},
        market_offset={m: {s: 0.0 for s in OUTCOME_IDS} for m in markets},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={s: 0.02 for s in OUTCOME_IDS},
        gamma_fourier={
            s: np.array([0.1, -0.1, 0.05, 0.0, 0.0, 0.0]) for s in OUTCOME_IDS
        },
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


def _future_context_with_nonzero_context(market="UK"):
    return build_future_context(
        market=market,
        period_labels=WEEKS,
        historical_n_weeks=30,
        n_fourier_harmonics=3,
        outcome_ids=tuple(OUTCOME_IDS),
        mode=OFFICIAL_MODE,
        promo_future={oid: {w: 1.0 for w in WEEKS} for oid in OUTCOME_IDS},
    )


def _carry_in(market="UK", tv=50.0, dna=20.0) -> SequentialCarryInState:
    return SequentialCarryInState(
        market=market,
        channels=tuple(CHANNELS),
        starting_adstock={"TV": tv, "DNA_Media": dna},
        lag_context_sat_media=np.zeros((DNA_LAG_WEEKS, len(CHANNELS))),
        lag_context_length=DNA_LAG_WEEKS,
    )


class TestBuildZeroDecisionTerminalExtensionPlan:
    def test_media_is_zero_but_context_is_not(self):
        future_context = _future_context_with_nonzero_context()
        plan = build_zero_decision_terminal_extension_plan(
            "UK", CHANNELS, future_context
        )
        for channel in CHANNELS:
            np.testing.assert_allclose(plan.media_by_channel[channel], 0.0)
        assert not np.allclose(plan.trend, 0.0)
        assert not np.allclose(plan.fourier, 0.0)
        assert not np.allclose(plan.promo, 0.0)

    def test_differs_from_the_low_level_zero_context_fixture(self):
        # zero_media_extension_plan zeros EVERYTHING (media and context) -
        # the business-facing terminal plan must not be equivalent to it
        # whenever the future context has genuine non-zero content.
        meta = _meta()
        future_context = _future_context_with_nonzero_context()
        governed_plan = build_zero_decision_terminal_extension_plan(
            "UK", CHANNELS, future_context
        )
        low_level_plan = zero_media_extension_plan("UK", WEEKS, meta, n_fourier=6)
        assert not np.allclose(governed_plan.trend, low_level_plan.trend)
        assert not np.allclose(governed_plan.promo, low_level_plan.promo)

    def test_market_mismatch_raises(self):
        future_context = _future_context_with_nonzero_context(market="IE")
        with pytest.raises(TerminalResponseError, match="market"):
            build_zero_decision_terminal_extension_plan("UK", CHANNELS, future_context)


class TestEvaluateTerminalIncrementalResponse:
    def test_no_change_produces_zero_terminal_incrementality(self):
        meta = _meta()
        params = _params()
        future_context = _future_context_with_nonzero_context()
        ending_state = _carry_in()

        result = evaluate_terminal_incremental_response(
            market="UK",
            channels=CHANNELS,
            candidate_ending_state=ending_state,
            reference_ending_state=ending_state,
            future_context=future_context,
            meta=meta,
            params=params,
        )
        np.testing.assert_allclose(result.incremental, 0.0, atol=1e-10)

    def test_different_ending_states_produce_nonzero_terminal_incrementality(self):
        meta = _meta()
        params = _params()
        future_context = _future_context_with_nonzero_context()

        result = evaluate_terminal_incremental_response(
            market="UK",
            channels=CHANNELS,
            candidate_ending_state=_carry_in(tv=200.0, dna=100.0),
            reference_ending_state=_carry_in(tv=0.0, dna=0.0),
            future_context=future_context,
            meta=meta,
            params=params,
        )
        assert np.any(result.incremental > 0.0)

    def test_result_is_separate_from_a_plan_window_result(self):
        meta = _meta()
        params = _params()
        future_context = _future_context_with_nonzero_context()
        result = evaluate_terminal_incremental_response(
            market="UK",
            channels=CHANNELS,
            candidate_ending_state=_carry_in(),
            reference_ending_state=_carry_in(tv=10.0),
            future_context=future_context,
            meta=meta,
            params=params,
        )
        # A distinct, explicitly-terminal result type - never a
        # SequentialSimulationResult standing in for a plan-window result.
        assert result.candidate is not result.reference
        assert result.incremental.shape == (len(WEEKS), len(OUTCOME_IDS))

    def test_candidate_and_reference_share_the_same_future_context(self):
        # Both evaluations are built from ONE extension_plan object inside
        # evaluate_terminal_incremental_response - structurally guaranteeing
        # identical non-decision assumptions, not merely equal by luck.
        meta = _meta()
        params = _params()
        future_context = _future_context_with_nonzero_context()
        result = evaluate_terminal_incremental_response(
            market="UK",
            channels=CHANNELS,
            candidate_ending_state=_carry_in(tv=5.0),
            reference_ending_state=_carry_in(tv=9.0),
            future_context=future_context,
            meta=meta,
            params=params,
        )
        np.testing.assert_array_equal(
            result.candidate.period_labels, result.reference.period_labels
        )


class TestEvaluateTerminalIncrementalResponseMarketSpecific:
    def test_no_change_produces_zero_terminal_incrementality(self):
        meta = _meta()
        params = _market_specific_params()
        future_context = _future_context_with_nonzero_context()
        ending_state = _carry_in()

        result = evaluate_terminal_incremental_response_market_specific(
            market="UK",
            channels=CHANNELS,
            candidate_ending_state=ending_state,
            reference_ending_state=ending_state,
            future_context=future_context,
            meta=meta,
            params=params,
        )
        np.testing.assert_allclose(result.incremental, 0.0, atol=1e-10)

    def test_second_market_still_works(self):
        meta = _meta(markets=("UK", "IE"))
        params = _market_specific_params(markets=("UK", "IE"))
        future_context = _future_context_with_nonzero_context(market="IE")

        result = evaluate_terminal_incremental_response_market_specific(
            market="IE",
            channels=CHANNELS,
            candidate_ending_state=_carry_in(market="IE", tv=100.0),
            reference_ending_state=_carry_in(market="IE", tv=0.0),
            future_context=future_context,
            meta=meta,
            params=params,
        )
        assert result.market == "IE"
        assert np.any(result.incremental > 0.0)
