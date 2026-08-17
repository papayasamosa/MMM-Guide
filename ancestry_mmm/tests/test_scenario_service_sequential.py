"""Tests for application.scenario_service's sequential-weekly dispatch
(Work Package 5 of `Media-Mix-Lab: Coding LLM Next Steps Post PR262`)."""

from __future__ import annotations

import numpy as np

from ancestry_mmm.application.scenario_service import (
    ScenarioService,
    SequentialManualScenarioInput,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.planning.future_context import (
    OFFICIAL_MODE,
    build_future_context,
)
from ancestry_mmm.core.planning.phasing import HorizonConfiguration
from ancestry_mmm.core.planning.weekly_plan_builder import build_governed_weekly_plan
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.sequential_evaluation_context import SequentialEvaluationContext
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

CHANNELS = ["TV", "DNA_Media"]
OUTCOME_IDS = ["New", "DNA_CrossSell"]
N_FOURIER_HARMONICS = 3
WEEKS = tuple(
    __import__("pandas")
    .date_range("2026-06-01", periods=6, freq="7D")
    .strftime("%Y-%m-%d")
    .tolist()
)


def _meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell",
        dna_lag_weeks=2,
        unpooled_markets=[],
        control_names=[],
    )


def _params() -> FHPosteriorParams:
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
        market_offset={"UK": {s: 0.0 for s in OUTCOME_IDS}},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={s: 0.0 for s in OUTCOME_IDS},
        gamma_fourier={s: np.zeros(2 * N_FOURIER_HARMONICS) for s in OUTCOME_IDS},
        alpha={s: 5.0 for s in OUTCOME_IDS},
        control_coef={},
        outcome_control_coef={},
    )


def _historical_frame():
    rng = np.random.default_rng(9)
    X = rng.uniform(0.0, 300.0, size=(20, len(CHANNELS)))
    return {
        "markets": ["UK"],
        "market_idx": np.zeros(20, dtype=int),
        "market_bounds": [(0, 20)],
        "X_media": X,
        "promo": np.zeros((20, len(OUTCOME_IDS))),
        "trend": np.zeros(20),
        "fourier": np.zeros((20, 2 * N_FOURIER_HARMONICS)),
        "control_names": [],
        "X_controls": np.zeros((20, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


class _FixedAllocation:
    def __init__(self, market, values):
        self.market = market
        self.period_labels = WEEKS
        self._values = np.asarray(values, dtype=float)

    def as_array(self):
        return self._values


def _plan(meta, future_context, tv, dna):
    plan, _prov = build_governed_weekly_plan(
        market="UK",
        meta=meta,
        channel_allocations={
            "TV": _FixedAllocation("UK", tv),
            "DNA_Media": _FixedAllocation("UK", dna),
        },
        future_context=future_context,
        expected_n_fourier_columns=2 * N_FOURIER_HARMONICS,
    )
    return plan


def _context():
    return SequentialEvaluationContext(
        model_identity="model-fp",
        posterior_identity="posterior-fp",
        market="UK",
        canonical_calendar_identity="cal-fp",
        historical_state_source_identity="hist-fp",
        evaluation_semantics_identity="sequential_weekly",
        phasing_policy_identity="calendar_day_overlap_v1",
        future_assumption_identity="future-fp",
        cost_context_identity="cost-fp",
        counterfactual_policy_identity="zero_future_media",
    )


def _sc_input(**overrides) -> SequentialManualScenarioInput:
    meta = _meta()
    future_context = build_future_context(
        market="UK",
        period_labels=WEEKS,
        historical_n_weeks=20,
        n_fourier_harmonics=N_FOURIER_HARMONICS,
        outcome_ids=tuple(OUTCOME_IDS),
        mode=OFFICIAL_MODE,
        promo_future={oid: {w: 0.0 for w in WEEKS} for oid in OUTCOME_IDS},
    )
    candidate = _plan(meta, future_context, [150.0] * 6, [50.0] * 6)
    reference = _plan(meta, future_context, [0.0] * 6, [0.0] * 6)
    kwargs = dict(
        market="UK",
        candidate_plan=candidate,
        reference_plan=reference,
        meta=meta,
        params=_params(),
        historical_frame=_historical_frame(),
        horizon_configuration=HorizonConfiguration(),
        evaluation_context=_context(),
        weekly_plan_fingerprint="wp-candidate",
        reference_weekly_plan_fingerprint="wp-reference",
        governance_mode="exploratory",
    )
    kwargs.update(overrides)
    return SequentialManualScenarioInput(**kwargs)


class TestEvaluateManualSequentialDispatch:
    def test_successful_dispatch_returns_sequential_evaluation(self):
        result = ScenarioService().evaluate_manual_sequential(_sc_input())
        assert not result.errors
        assert result.evaluation is None  # steady-state field untouched
        assert result.sequential_evaluation is not None
        assert result.sequential_evaluation.calculation_method == "sequential_weekly"
        assert np.all(result.sequential_evaluation.weekly_incremental > 0.0)

    def test_missing_meta_returns_error_not_exception(self):
        result = ScenarioService().evaluate_manual_sequential(_sc_input(meta=None))
        assert result.errors
        assert result.sequential_evaluation is None

    def test_official_mode_without_approval_returns_error_not_exception(self):
        result = ScenarioService().evaluate_manual_sequential(
            _sc_input(governance_mode="official", approval=None)
        )
        assert any("approval" in e.lower() for e in result.errors)
        assert result.sequential_evaluation is None

    def test_core_layer_exception_is_wrapped_not_raised(self):
        # A market mismatch between candidate/reference plans raises inside
        # core.sequential_scenario_evaluation - the service must catch it
        # and report it as an error, not let it propagate.
        sc_input = _sc_input()
        object.__setattr__(sc_input.reference_plan, "market", "IE")
        result = ScenarioService().evaluate_manual_sequential(sc_input)
        assert result.errors
        assert "Sequential manual scenario evaluation failed" in result.errors[0]
