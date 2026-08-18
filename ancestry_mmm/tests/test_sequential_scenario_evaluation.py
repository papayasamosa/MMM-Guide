"""Tests for core.sequential_scenario_evaluation (Work Package 5 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR262`)."""

from __future__ import annotations

import numpy as np
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    fingerprint_outcome_definition,
)
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
)
from ancestry_mmm.core.planning.future_context import (
    OFFICIAL_MODE,
    build_future_context,
)
from ancestry_mmm.core.planning.phasing import HorizonConfiguration
from ancestry_mmm.core.planning.value import (
    CURRENT_PLANNING_EVALUATION_SEMANTICS,
    SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS,
    PlanningObjective,
)
from ancestry_mmm.core.planning.weekly_plan_builder import build_governed_weekly_plan
from ancestry_mmm.core.predict import (
    CandidateAReplayNotSupportedError,
    FHPosteriorParams,
)
from ancestry_mmm.core.search_capacity import SEARCH_CANDIDATE_A_ENGINE
from ancestry_mmm.core.sequential_evaluation_context import SequentialEvaluationContext
from ancestry_mmm.core.sequential_scenario_evaluation import (
    MARKET_SPECIFIC_MODEL_TYPE,
    SequentialScenarioEvaluationResult,
    evaluate_manual_scenario_sequential,
    sequential_scenario_to_dict,
)
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

CHANNELS = ["TV", "DNA_Media"]
OUTCOME_IDS = ["New", "DNA_CrossSell"]
DNA_LAG_WEEKS = 2
N_FOURIER_HARMONICS = 3
WEEKS = tuple(
    __import__("pandas")
    .date_range("2026-06-01", periods=6, freq="7D")
    .strftime("%Y-%m-%d")
    .tolist()
)


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
        promo_coef={s: 0.0 for s in OUTCOME_IDS},
        market_offset={m: {s: 0.0 for s in OUTCOME_IDS} for m in markets},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={s: 0.0 for s in OUTCOME_IDS},
        gamma_fourier={s: np.zeros(2 * N_FOURIER_HARMONICS) for s in OUTCOME_IDS},
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


def _historical_frame(
    market="UK", n_hist=20, n_channels=len(CHANNELS), n_outcomes=len(OUTCOME_IDS)
):
    rng = np.random.default_rng(3)
    X = rng.uniform(0.0, 300.0, size=(n_hist, n_channels))
    return {
        "markets": [market],
        "market_idx": np.zeros(n_hist, dtype=int),
        "market_bounds": [(0, n_hist)],
        "X_media": X,
        "promo": np.zeros((n_hist, n_outcomes)),
        "trend": np.zeros(n_hist),
        "fourier": np.zeros((n_hist, 2 * N_FOURIER_HARMONICS)),
        "control_names": [],
        "X_controls": np.zeros((n_hist, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


def _two_market_historical_frame(n_hist=20):
    """A two-market ("UK", "IE") historical frame, matching this suite's
    `_meta(markets=("UK", "IE"))` fixture - `reconstruct_starting_state_
    market_specific` requires `market_bounds` to have one entry per fitted
    market (Work Package 3's historical-state safety hardening)."""
    rng = np.random.default_rng(5)
    n_channels = len(CHANNELS)
    n_outcomes = len(OUTCOME_IDS)
    X_uk = rng.uniform(0.0, 300.0, size=(n_hist, n_channels))
    X_ie = rng.uniform(0.0, 300.0, size=(n_hist, n_channels))
    X = np.concatenate([X_uk, X_ie], axis=0)
    return {
        "markets": ["UK", "IE"],
        "market_idx": np.array([0] * n_hist + [1] * n_hist),
        "market_bounds": [(0, n_hist), (n_hist, 2 * n_hist)],
        "X_media": X,
        "promo": np.zeros((2 * n_hist, n_outcomes)),
        "trend": np.zeros(2 * n_hist),
        "fourier": np.zeros((2 * n_hist, 2 * N_FOURIER_HARMONICS)),
        "control_names": [],
        "X_controls": np.zeros((2 * n_hist, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


def _future_context(market="UK"):
    return build_future_context(
        market=market,
        period_labels=WEEKS,
        historical_n_weeks=20,
        n_fourier_harmonics=N_FOURIER_HARMONICS,
        outcome_ids=tuple(OUTCOME_IDS),
        mode=OFFICIAL_MODE,
        promo_future={oid: {w: 0.0 for w in WEEKS} for oid in OUTCOME_IDS},
    )


class _FixedAllocation:
    """Minimal WeeklyAllocationResult-shaped stand-in for a phased plan."""

    def __init__(self, market, values, period_labels=WEEKS):
        self.market = market
        self.period_labels = period_labels
        self._values = np.asarray(values, dtype=float)

    def as_array(self):
        return self._values


def _weekly_plan(market, meta, future_context, tv_values, dna_values):
    plan, _prov = build_governed_weekly_plan(
        market=market,
        meta=meta,
        channel_allocations={
            "TV": _FixedAllocation(market, tv_values, future_context.period_labels),
            "DNA_Media": _FixedAllocation(
                market, dna_values, future_context.period_labels
            ),
        },
        future_context=future_context,
        expected_n_fourier_columns=2 * N_FOURIER_HARMONICS,
    )
    return plan


def _context(market="UK", **overrides):
    values = dict(
        model_identity="model-fp",
        posterior_identity="posterior-fp",
        market=market,
        canonical_calendar_identity="cal-fp",
        historical_state_source_identity="hist-fp",
        evaluation_semantics_identity="sequential_weekly",
        phasing_policy_identity="calendar_day_overlap_v1",
        future_assumption_identity="future-fp",
        cost_context_identity="cost-fp",
        counterfactual_policy_identity="zero_future_media",
    )
    values.update(overrides)
    return SequentialEvaluationContext(**values)


class TestEvaluateManualScenarioSequentialModelA:
    def test_no_change_scenario_is_zero_at_every_grain(self):
        meta = _meta()
        params = _params()
        future_context = _future_context()
        rng = np.random.default_rng(11)
        tv = rng.uniform(0, 200, size=6)
        dna = rng.uniform(0, 200, size=6)
        plan = _weekly_plan("UK", meta, future_context, tv, dna)

        result = evaluate_manual_scenario_sequential(
            market="UK",
            candidate_plan=plan,
            reference_plan=plan,
            meta=meta,
            params=params,
            historical_frame=_historical_frame(),
            horizon_configuration=HorizonConfiguration(),
            evaluation_context=_context(),
            weekly_plan_fingerprint="wp-1",
            reference_weekly_plan_fingerprint="wp-1",
            governance_mode="exploratory",
        )
        np.testing.assert_allclose(result.weekly_incremental, 0.0, atol=1e-10)
        np.testing.assert_allclose(result.monthly_incremental, 0.0, atol=1e-10)
        np.testing.assert_allclose(result.short_horizon_incremental, 0.0, atol=1e-10)
        np.testing.assert_allclose(result.long_horizon_incremental, 0.0, atol=1e-10)
        assert result.calculation_method == "sequential_weekly"

    def test_different_plans_produce_nonzero_incremental_and_correct_monthly_conservation(
        self,
    ):
        meta = _meta()
        params = _params()
        future_context = _future_context()
        candidate = _weekly_plan("UK", meta, future_context, [200.0] * 6, [200.0] * 6)
        reference = _weekly_plan("UK", meta, future_context, [0.0] * 6, [0.0] * 6)

        result = evaluate_manual_scenario_sequential(
            market="UK",
            candidate_plan=candidate,
            reference_plan=reference,
            meta=meta,
            params=params,
            historical_frame=_historical_frame(),
            horizon_configuration=HorizonConfiguration(),
            evaluation_context=_context(),
            weekly_plan_fingerprint="wp-candidate",
            reference_weekly_plan_fingerprint="wp-reference",
            governance_mode="exploratory",
        )
        assert np.all(result.weekly_incremental > 0.0)
        # Monthly aggregation must exactly equal the sum of the weekly
        # values within each month - never an independently recomputed
        # monthly curve (REQ-SCEN-001 item 6).
        weeks_by_month: dict = {}
        for i, w in enumerate(result.weekly_period_labels):
            weeks_by_month.setdefault(w[:7], []).append(i)
        for mi, month in enumerate(result.monthly_period_labels):
            expected = result.weekly_incremental[weeks_by_month[month]].sum(axis=0)
            np.testing.assert_allclose(result.monthly_incremental[mi], expected)

    def test_terminal_is_reported_separately_when_requested(self):
        meta = _meta()
        params = _params()
        future_context = _future_context()
        candidate = _weekly_plan("UK", meta, future_context, [300.0] * 6, [0.0] * 6)
        reference = _weekly_plan("UK", meta, future_context, [0.0] * 6, [0.0] * 6)
        terminal_weeks = tuple(
            __import__("pandas")
            .date_range(WEEKS[-1], periods=5, freq="7D")[1:]
            .strftime("%Y-%m-%d")
            .tolist()
        )
        terminal_context = build_future_context(
            market="UK",
            period_labels=terminal_weeks,
            historical_n_weeks=26,
            n_fourier_harmonics=N_FOURIER_HARMONICS,
            outcome_ids=tuple(OUTCOME_IDS),
            mode=OFFICIAL_MODE,
            promo_future={oid: {w: 0.0 for w in terminal_weeks} for oid in OUTCOME_IDS},
        )

        result = evaluate_manual_scenario_sequential(
            market="UK",
            candidate_plan=candidate,
            reference_plan=reference,
            meta=meta,
            params=params,
            historical_frame=_historical_frame(),
            horizon_configuration=HorizonConfiguration(),
            evaluation_context=_context(),
            weekly_plan_fingerprint="wp-candidate",
            reference_weekly_plan_fingerprint="wp-reference",
            terminal_future_context=terminal_context,
            governance_mode="exploratory",
        )
        assert result.terminal is not None
        assert result.terminal.incremental.shape == (
            len(terminal_weeks),
            len(OUTCOME_IDS),
        )
        # Terminal result must never be folded into the plan-window result.
        assert result.terminal.incremental is not result.weekly_incremental

    def test_draw_consistent_posterior_path_returns_full_per_draw_array(self):
        import arviz as az

        meta = _meta()
        future_context = _future_context()
        candidate = _weekly_plan("UK", meta, future_context, [150.0] * 6, [50.0] * 6)
        reference = _weekly_plan("UK", meta, future_context, [0.0] * 6, [0.0] * 6)

        n_chain, n_draw = 1, 2
        coords = {
            "outcome": OUTCOME_IDS,
            "channel": CHANNELS,
            "market": ["UK"],
            "fourier": list(range(2 * N_FOURIER_HARMONICS)),
        }
        decay_rate = np.zeros((n_chain, n_draw, 2))
        decay_rate[0, 0, :] = [0.2, 0.3]
        decay_rate[0, 1, :] = [0.8, 0.7]
        posterior = {
            "decay_rate": decay_rate,
            "hill_K": np.broadcast_to([500.0, 300.0], (n_chain, n_draw, 2)).copy(),
            "hill_S": np.broadcast_to([1.0, 1.0], (n_chain, n_draw, 2)).copy(),
            "beta": np.broadcast_to(
                [[0.02, 0.01], [0.0, 0.03]], (n_chain, n_draw, 2, 2)
            ).copy(),
            "promo_coef": np.zeros((n_chain, n_draw, 2)),
            "market_offset": np.zeros((n_chain, n_draw, 1, 2)),
            "intercept": np.broadcast_to([3.0, 2.0], (n_chain, n_draw, 2)).copy(),
            "trend_coef": np.zeros((n_chain, n_draw, 2)),
            "gamma_fourier": np.zeros((n_chain, n_draw, 2 * N_FOURIER_HARMONICS, 2)),
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
        trace = az.from_dict(posterior=posterior, coords=coords, dims=dims)

        result = evaluate_manual_scenario_sequential(
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
            trace=trace,
            n_posterior_draws=2,
        )
        assert result.posterior_weekly_incremental is not None
        assert result.posterior_weekly_incremental.shape == (2, 6, len(OUTCOME_IDS))
        # Deliberately not aggregated inside the evaluator.
        assert not np.allclose(
            result.posterior_weekly_incremental[0],
            result.posterior_weekly_incremental[1],
        )

    def test_mismatched_plan_weeks_raises(self):
        meta = _meta()
        future_context = _future_context()
        candidate = _weekly_plan("UK", meta, future_context, [1.0] * 6, [1.0] * 6)
        other_weeks_context = build_future_context(
            market="UK",
            period_labels=tuple(
                __import__("pandas")
                .date_range("2026-08-01", periods=6, freq="7D")
                .strftime("%Y-%m-%d")
                .tolist()
            ),
            historical_n_weeks=20,
            n_fourier_harmonics=N_FOURIER_HARMONICS,
            outcome_ids=tuple(OUTCOME_IDS),
            mode=OFFICIAL_MODE,
            promo_future={
                oid: {
                    w: 0.0
                    for w in __import__("pandas")
                    .date_range("2026-08-01", periods=6, freq="7D")
                    .strftime("%Y-%m-%d")
                }
                for oid in OUTCOME_IDS
            },
        )
        other_plan = _weekly_plan("UK", meta, other_weeks_context, [1.0] * 6, [1.0] * 6)
        with pytest.raises(Exception, match="same canonical weeks"):
            evaluate_manual_scenario_sequential(
                market="UK",
                candidate_plan=candidate,
                reference_plan=other_plan,
                meta=meta,
                params=_params(),
                historical_frame=_historical_frame(),
                horizon_configuration=HorizonConfiguration(),
                evaluation_context=_context(),
                weekly_plan_fingerprint="wp-1",
                reference_weekly_plan_fingerprint="wp-2",
                governance_mode="exploratory",
            )


class TestEvaluateManualScenarioSequentialModelC:
    def test_no_change_scenario_is_zero(self):
        meta = _meta(markets=("UK", "IE"))
        params = _market_specific_params(markets=("UK", "IE"))
        future_context = _future_context(market="IE")
        plan = _weekly_plan("IE", meta, future_context, [100.0] * 6, [50.0] * 6)

        result = evaluate_manual_scenario_sequential(
            market="IE",
            candidate_plan=plan,
            reference_plan=plan,
            meta=meta,
            params=params,
            model_type=MARKET_SPECIFIC_MODEL_TYPE,
            historical_frame=_two_market_historical_frame(),
            horizon_configuration=HorizonConfiguration(),
            evaluation_context=_context(market="IE"),
            weekly_plan_fingerprint="wp-1",
            reference_weekly_plan_fingerprint="wp-1",
            governance_mode="exploratory",
        )
        np.testing.assert_allclose(result.weekly_incremental, 0.0, atol=1e-10)

    def test_different_plans_produce_nonzero_incremental(self):
        meta = _meta(markets=("UK", "IE"))
        params = _market_specific_params(markets=("UK", "IE"))
        future_context = _future_context(market="IE")
        candidate = _weekly_plan("IE", meta, future_context, [250.0] * 6, [100.0] * 6)
        reference = _weekly_plan("IE", meta, future_context, [0.0] * 6, [0.0] * 6)

        result = evaluate_manual_scenario_sequential(
            market="IE",
            candidate_plan=candidate,
            reference_plan=reference,
            meta=meta,
            params=params,
            model_type=MARKET_SPECIFIC_MODEL_TYPE,
            historical_frame=_two_market_historical_frame(),
            horizon_configuration=HorizonConfiguration(),
            evaluation_context=_context(market="IE"),
            weekly_plan_fingerprint="wp-candidate",
            reference_weekly_plan_fingerprint="wp-reference",
            governance_mode="exploratory",
        )
        assert np.all(result.weekly_incremental > 0.0)


class TestCandidateABoundary:
    def test_candidate_a_fit_fails_closed(self):
        import dataclasses

        meta = dataclasses.replace(
            _meta(), causal_graph_engine=SEARCH_CANDIDATE_A_ENGINE
        )
        params = _params()
        future_context = _future_context()
        plan = _weekly_plan("UK", meta, future_context, [1.0] * 6, [1.0] * 6)

        with pytest.raises(CandidateAReplayNotSupportedError):
            evaluate_manual_scenario_sequential(
                market="UK",
                candidate_plan=plan,
                reference_plan=plan,
                meta=meta,
                params=params,
                historical_frame=_historical_frame(),
                horizon_configuration=HorizonConfiguration(),
                evaluation_context=_context(),
                weekly_plan_fingerprint="wp-1",
                reference_weekly_plan_fingerprint="wp-1",
                governance_mode="exploratory",
            )


class TestOfficialGovernance:
    """Official-mode governance resolution must succeed end to end and
    stamp SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS - never the
    steady-state constant."""

    def _outcome(self) -> OutcomeDefinition:
        return OutcomeDefinition(
            outcome_id="New",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="A new subscriber",
            date_basis="event_date",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            exclusions="Excludes internal/test accounts",
            reconciliation_source="Finance report",
            business_owner="Analytics",
            definition_version="1.0",
        )

    def test_official_mode_stamps_sequential_semantics(self):
        outcome = self._outcome()
        meta = FHModelMeta(
            markets=["UK"],
            outcome_ids=["New"],
            channels=["TV"],
            dna_channels=[],
            dna_channel_idx=[],
            non_dna_idx=[0],
            dna_outcome_id="New",
            dna_lag_weeks=2,
            unpooled_markets=[],
            control_names=[],
            outcome_catalogue_at_fit=[outcome],
        )
        params = FHPosteriorParams(
            decay_rate={"TV": 0.5},
            hill_K={"TV": 1000.0},
            hill_S={"TV": 1.0},
            beta={"New": {"TV": 0.1}},
            pathway_strength={},
            promo_coef={"New": 0.0},
            market_offset={"UK": {"New": 0.0}},
            intercept={"New": 3.0},
            trend_coef={"New": 0.0},
            gamma_fourier={"New": np.zeros(2 * N_FOURIER_HARMONICS)},
            alpha={"New": 5.0},
            control_coef={},
            outcome_control_coef={},
        )
        future_context = build_future_context(
            market="UK",
            period_labels=WEEKS,
            historical_n_weeks=20,
            n_fourier_harmonics=N_FOURIER_HARMONICS,
            outcome_ids=("New",),
            mode=OFFICIAL_MODE,
            promo_future={"New": {w: 0.0 for w in WEEKS}},
        )
        plan, _prov = build_governed_weekly_plan(
            market="UK",
            meta=meta,
            channel_allocations={"TV": _FixedAllocation("UK", [100.0] * 6)},
            future_context=future_context,
            expected_n_fourier_columns=2 * N_FOURIER_HARMONICS,
        )
        identity = dict(
            model_run_id="run-abc123",
            data_fingerprint="data-fp-1",
            model_spec_fingerprint="spec-fp-1",
            posterior_fingerprint="posterior-fp-1",
        )
        approval = ModelApproval(approved_by="Jane Analyst", **identity)
        outcome_approval = OutcomeApproval(
            approval_id="apr-new-gsa",
            outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(outcome),
            status="approved",
            allowed_uses=("planning", "optimisation"),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        planning_objective = PlanningObjective(
            estimand="incremental_outcome",
            metric_key=METRIC_KEY_FH_GSA,
            target_outcome_ids=("New",),
        )

        result = evaluate_manual_scenario_sequential(
            market="UK",
            candidate_plan=plan,
            reference_plan=plan,
            meta=meta,
            params=params,
            historical_frame=_historical_frame(n_hist=20, n_channels=1, n_outcomes=1),
            horizon_configuration=HorizonConfiguration(),
            evaluation_context=_context(),
            weekly_plan_fingerprint="wp-1",
            reference_weekly_plan_fingerprint="wp-1",
            governance_mode="official",
            planning_objective=planning_objective,
            approval=approval,
            outcome_approvals=[outcome_approval],
            **identity,
        )
        assert (
            result.planning_semantics is SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS
        )
        assert (
            result.planning_semantics.fingerprint()
            != CURRENT_PLANNING_EVALUATION_SEMANTICS.fingerprint()
        )
        assert result.governance_dependencies is not None
        assert (
            result.governance_dependencies.planning_semantics_fingerprint
            == SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS.fingerprint()
        )


def _assert_round_trips_via_dict(obj) -> None:
    """`SequentialSimulationResult`/`TerminalIncrementalResult`/
    `SequentialScenarioEvaluationResult` all carry numpy-array fields, so
    a plain `==` on two instances raises `ValueError` (dataclass-
    generated `__eq__` calls `bool()` on each field's `==` result) rather
    than comparing cleanly. `to_dict()` converts every array to a plain
    list first, so comparing the two dicts (never the two dataclass
    instances directly) verifies every field, including nested objects,
    without hitting that ambiguity."""
    restored = type(obj).from_dict(obj.to_dict())
    assert restored.to_dict() == obj.to_dict()


class TestSequentialScenarioEvaluationResultSerialization:
    """WP5 part 4: a SequentialScenarioEvaluationResult must round-trip
    through to_dict/from_dict exactly, including its nested
    SequentialSimulationResult/TerminalIncrementalResult objects and
    Optional fields (terminal, posterior_weekly_incremental) - the
    persistence contract this record's own "Not yet covered" section
    previously flagged as missing."""

    def test_round_trip_without_terminal_or_posterior(self):
        meta = _meta()
        params = _params()
        future_context = _future_context()
        candidate = _weekly_plan("UK", meta, future_context, [200.0] * 6, [200.0] * 6)
        reference = _weekly_plan("UK", meta, future_context, [0.0] * 6, [0.0] * 6)

        original = evaluate_manual_scenario_sequential(
            market="UK",
            candidate_plan=candidate,
            reference_plan=reference,
            meta=meta,
            params=params,
            historical_frame=_historical_frame(),
            horizon_configuration=HorizonConfiguration(),
            evaluation_context=_context(),
            weekly_plan_fingerprint="wp-candidate",
            reference_weekly_plan_fingerprint="wp-reference",
            governance_mode="exploratory",
        )
        _assert_round_trips_via_dict(original)

    def test_round_trip_with_terminal_and_posterior(self):
        import arviz as az

        meta = _meta()
        future_context = _future_context()
        candidate = _weekly_plan("UK", meta, future_context, [300.0] * 6, [0.0] * 6)
        reference = _weekly_plan("UK", meta, future_context, [0.0] * 6, [0.0] * 6)
        terminal_weeks = tuple(
            __import__("pandas")
            .date_range(WEEKS[-1], periods=5, freq="7D")[1:]
            .strftime("%Y-%m-%d")
            .tolist()
        )
        terminal_context = build_future_context(
            market="UK",
            period_labels=terminal_weeks,
            historical_n_weeks=26,
            n_fourier_harmonics=N_FOURIER_HARMONICS,
            outcome_ids=tuple(OUTCOME_IDS),
            mode=OFFICIAL_MODE,
            promo_future={oid: {w: 0.0 for w in terminal_weeks} for oid in OUTCOME_IDS},
        )

        n_chain, n_draw = 1, 2
        coords = {
            "outcome": OUTCOME_IDS,
            "channel": CHANNELS,
            "market": ["UK"],
            "fourier": list(range(2 * N_FOURIER_HARMONICS)),
        }
        decay_rate = np.zeros((n_chain, n_draw, 2))
        decay_rate[0, 0, :] = [0.2, 0.3]
        decay_rate[0, 1, :] = [0.8, 0.7]
        posterior = {
            "decay_rate": decay_rate,
            "hill_K": np.broadcast_to([500.0, 300.0], (n_chain, n_draw, 2)).copy(),
            "hill_S": np.broadcast_to([1.0, 1.0], (n_chain, n_draw, 2)).copy(),
            "beta": np.broadcast_to(
                [[0.02, 0.01], [0.0, 0.03]], (n_chain, n_draw, 2, 2)
            ).copy(),
            "promo_coef": np.zeros((n_chain, n_draw, 2)),
            "market_offset": np.zeros((n_chain, n_draw, 1, 2)),
            "intercept": np.broadcast_to([3.0, 2.0], (n_chain, n_draw, 2)).copy(),
            "trend_coef": np.zeros((n_chain, n_draw, 2)),
            "gamma_fourier": np.zeros((n_chain, n_draw, 2 * N_FOURIER_HARMONICS, 2)),
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
        trace = az.from_dict(posterior=posterior, coords=coords, dims=dims)

        original = evaluate_manual_scenario_sequential(
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
            terminal_future_context=terminal_context,
            governance_mode="exploratory",
            trace=trace,
            n_posterior_draws=2,
        )
        assert original.terminal is not None
        assert original.posterior_weekly_incremental is not None

        _assert_round_trips_via_dict(original)

        restored = SequentialScenarioEvaluationResult.from_dict(original.to_dict())
        assert restored.terminal is not None
        assert restored.posterior_weekly_incremental is not None
        np.testing.assert_array_equal(
            restored.posterior_weekly_incremental,
            original.posterior_weekly_incremental,
        )


class TestSequentialScenarioToDict:
    """WP5 part 4: `sequential_scenario_to_dict` builds the persisted-
    scenario dict appended to the SAME `scenarios` list a steady-state
    scenario is - `core.optimization.scenario_from_dict` must recognise
    and pass it through unchanged (never injecting steady-state-specific
    legacy fields), and the whole dict must be plain-JSON-serializable
    (no numpy arrays survive `to_dict()`)."""

    def _result(self):
        meta = _meta()
        params = _params()
        future_context = _future_context()
        candidate = _weekly_plan("UK", meta, future_context, [200.0] * 6, [100.0] * 6)
        reference = _weekly_plan("UK", meta, future_context, [0.0] * 6, [0.0] * 6)
        return evaluate_manual_scenario_sequential(
            market="UK",
            candidate_plan=candidate,
            reference_plan=reference,
            meta=meta,
            params=params,
            historical_frame=_historical_frame(),
            horizon_configuration=HorizonConfiguration(),
            evaluation_context=_context(),
            weekly_plan_fingerprint="wp-candidate",
            reference_weekly_plan_fingerprint="wp-reference",
            governance_mode="exploratory",
        )

    def test_json_serializable(self):
        import json

        s = sequential_scenario_to_dict("seq-1", self._result())
        json.dumps(s, default=str)  # must not raise

    def test_has_no_predicted_key(self):
        """`compare_scenarios` requires a `predicted` DataFrame - a
        sequential scenario dict must never carry one, so a caller is
        forced to filter by calculation_method before comparing rather
        than silently passing this dict into a steady-state-only path."""
        s = sequential_scenario_to_dict("seq-1", self._result())
        assert "predicted" not in s

    def test_calculation_method_is_sequential_weekly(self):
        s = sequential_scenario_to_dict("seq-1", self._result())
        assert s["calculation_method"] == "sequential_weekly"

    def test_scenario_from_dict_passes_through_unchanged(self):
        from ancestry_mmm.core.optimization import scenario_from_dict

        s = sequential_scenario_to_dict("seq-1", self._result(), notes="test")
        migrated = scenario_from_dict(s)
        assert migrated == s
        assert "scenario_plan" not in migrated
        assert "planning_objective" not in migrated

    def test_governance_dependencies_absent_in_exploratory_mode(self):
        s = sequential_scenario_to_dict("seq-1", self._result())
        assert s["governance_dependencies"] is None

    def test_governance_dependencies_present_for_staleness_check_in_official_mode(self):
        outcome = OutcomeDefinition(
            outcome_id="New",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="A new subscriber",
            date_basis="event_date",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            exclusions="Excludes internal/test accounts",
            reconciliation_source="Finance report",
            business_owner="Analytics",
            definition_version="1.0",
        )
        meta = FHModelMeta(
            markets=["UK"],
            outcome_ids=["New"],
            channels=["TV"],
            dna_channels=[],
            dna_channel_idx=[],
            non_dna_idx=[0],
            dna_outcome_id="New",
            dna_lag_weeks=2,
            unpooled_markets=[],
            control_names=[],
            outcome_catalogue_at_fit=[outcome],
        )
        params = FHPosteriorParams(
            decay_rate={"TV": 0.5},
            hill_K={"TV": 1000.0},
            hill_S={"TV": 1.0},
            beta={"New": {"TV": 0.1}},
            pathway_strength={},
            promo_coef={"New": 0.0},
            market_offset={"UK": {"New": 0.0}},
            intercept={"New": 3.0},
            trend_coef={"New": 0.0},
            gamma_fourier={"New": np.zeros(2 * N_FOURIER_HARMONICS)},
            alpha={"New": 5.0},
            control_coef={},
            outcome_control_coef={},
        )
        future_context = build_future_context(
            market="UK",
            period_labels=WEEKS,
            historical_n_weeks=20,
            n_fourier_harmonics=N_FOURIER_HARMONICS,
            outcome_ids=("New",),
            mode=OFFICIAL_MODE,
            promo_future={"New": {w: 0.0 for w in WEEKS}},
        )
        plan, _prov = build_governed_weekly_plan(
            market="UK",
            meta=meta,
            channel_allocations={"TV": _FixedAllocation("UK", [100.0] * 6)},
            future_context=future_context,
            expected_n_fourier_columns=2 * N_FOURIER_HARMONICS,
        )
        identity = dict(
            model_run_id="run-abc123",
            data_fingerprint="data-fp-1",
            model_spec_fingerprint="spec-fp-1",
            posterior_fingerprint="posterior-fp-1",
        )
        approval = ModelApproval(approved_by="Jane Analyst", **identity)
        outcome_approval = OutcomeApproval(
            approval_id="apr-new-gsa",
            outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(outcome),
            status="approved",
            allowed_uses=("planning", "optimisation"),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        planning_objective = PlanningObjective(
            estimand="incremental_outcome",
            metric_key=METRIC_KEY_FH_GSA,
            target_outcome_ids=("New",),
        )
        result = evaluate_manual_scenario_sequential(
            market="UK",
            candidate_plan=plan,
            reference_plan=plan,
            meta=meta,
            params=params,
            historical_frame=_historical_frame(n_hist=20, n_channels=1, n_outcomes=1),
            horizon_configuration=HorizonConfiguration(),
            evaluation_context=_context(),
            weekly_plan_fingerprint="wp-1",
            reference_weekly_plan_fingerprint="wp-1",
            governance_mode="official",
            planning_objective=planning_objective,
            approval=approval,
            outcome_approvals=[outcome_approval],
            **identity,
        )
        s = sequential_scenario_to_dict("seq-1", result)
        assert s["governance_dependencies"] is not None
        assert "counterfactual_policy_fingerprint" in s["governance_dependencies"]
