"""Tests for `ancestry_mmm.core.sequential_optimisation_tractability`
(Decision 16 resolution). See
`docs/sequential_optimisation_tractability_decision_record.md` for the
decisions these tests verify."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.optimization import optimize_scenario
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.sequential_optimisation_tractability import (
    BENCHMARK_EVIDENCE,
    SEQUENTIAL_OPTIMISATION_OBJECTIVE_HORIZON,
    SEQUENTIAL_OPTIMISATION_SEARCH_IS_POSTERIOR_AWARE,
    SEQUENTIAL_OPTIMISATION_TRACTABILITY_STRATEGY,
    SequentialKernelBenchmarkEvidence,
    SequentialOptimisationContext,
    compute_sequential_plan_objective_value,
)
from ancestry_mmm.core.sequential_simulation import (
    WeeklyPlan,
    reconstruct_starting_state,
    reconstruct_starting_state_market_specific,
)
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

CHANNELS = ["TV", "DNA_Media"]
OUTCOME_IDS = ["New", "DNA_CrossSell"]
N_FOURIER = 4

IDENTITY = dict(
    model_run_id="run-sequential",
    data_fingerprint="data-sequential",
    model_spec_fingerprint="spec-sequential",
    posterior_fingerprint="posterior-sequential",
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
        gamma_fourier={s: np.zeros(N_FOURIER) for s in OUTCOME_IDS},
        alpha={s: 5.0 for s in OUTCOME_IDS},
        control_coef={},
        outcome_control_coef={},
    )


def _full_frame(X_media, meta):
    n = X_media.shape[0]
    return {
        "markets": ["UK"],
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


def _plan_from_media(period_labels, X_media):
    n = X_media.shape[0]
    return WeeklyPlan(
        market="UK",
        period_labels=tuple(period_labels),
        media_by_channel={c: X_media[:, j] for j, c in enumerate(CHANNELS)},
        promo=np.zeros((n, len(OUTCOME_IDS))),
        trend=np.zeros(n),
        fourier=np.zeros((n, N_FOURIER)),
    )


class TestGovernedConstants:
    def test_tractability_strategy(self):
        assert (
            SEQUENTIAL_OPTIMISATION_TRACTABILITY_STRATEGY
            == "T1_direct_replay_point_estimate"
        )

    def test_objective_horizon(self):
        assert SEQUENTIAL_OPTIMISATION_OBJECTIVE_HORIZON == "O1_plan_window_total"

    def test_search_not_posterior_aware(self):
        assert SEQUENTIAL_OPTIMISATION_SEARCH_IS_POSTERIOR_AWARE is False


class TestBenchmarkEvidence:
    def test_three_configurations_preserved(self):
        assert len(BENCHMARK_EVIDENCE) == 3

    def test_round_trip(self):
        original = BENCHMARK_EVIDENCE[0]
        restored = SequentialKernelBenchmarkEvidence.from_dict(original.to_dict())
        assert restored == original

    def test_requires_measured_on(self):
        with pytest.raises(ValueError, match="measured_on"):
            SequentialKernelBenchmarkEvidence(
                n_channels=1,
                n_future_weeks=1,
                mean_seconds_per_call=0.001,
                p95_seconds_per_call=0.001,
                extrapolated_total_seconds_by_iterations={20: 0.1},
                measured_on="",
            )

    def test_rejects_negative_timing(self):
        with pytest.raises(ValueError):
            SequentialKernelBenchmarkEvidence(
                n_channels=1,
                n_future_weeks=1,
                mean_seconds_per_call=-0.1,
                p95_seconds_per_call=0.001,
                extrapolated_total_seconds_by_iterations={20: 0.1},
                measured_on="test",
            )


class TestComputeSequentialPlanObjectiveValue:
    def test_no_change_plan_is_zero(self):
        meta = _meta()
        params = _params()
        rng = np.random.default_rng(1)
        n_hist, n_future = 12, 8
        X_full = rng.uniform(0.0, 400.0, size=(n_hist + n_future, len(CHANNELS)))
        hist_frame = _full_frame(X_full[:n_hist], meta)
        carry_in = reconstruct_starting_state(hist_frame, meta, params, "UK")
        labels = [f"w{i}" for i in range(n_future)]
        plan = _plan_from_media(labels, X_full[n_hist:])

        value = compute_sequential_plan_objective_value(
            plan, plan, carry_in, meta, params
        )
        assert value == pytest.approx(0.0, abs=1e-8)

    def test_higher_spend_plan_is_not_negative_when_channels_help(self):
        meta = _meta()
        params = _params()
        rng = np.random.default_rng(2)
        n_hist, n_future = 12, 8
        X_full = rng.uniform(50.0, 200.0, size=(n_hist + n_future, len(CHANNELS)))
        hist_frame = _full_frame(X_full[:n_hist], meta)
        carry_in = reconstruct_starting_state(hist_frame, meta, params, "UK")
        labels = [f"w{i}" for i in range(n_future)]
        reference = _plan_from_media(labels, X_full[n_hist:])
        boosted = _plan_from_media(labels, X_full[n_hist:] * 2.0)

        value = compute_sequential_plan_objective_value(
            boosted, reference, carry_in, meta, params
        )
        # Positive betas everywhere -> more spend cannot reduce the total
        # incremental outcome (allowing for saturation, never negative).
        assert value >= -1e-6

    def test_objective_is_sum_across_full_plan_window(self):
        # O1 = plan-window total, not a single-week or short-horizon slice.
        meta = _meta()
        params = _params()
        rng = np.random.default_rng(3)
        n_hist, n_future = 12, 20
        X_full = rng.uniform(50.0, 200.0, size=(n_hist + n_future, len(CHANNELS)))
        hist_frame = _full_frame(X_full[:n_hist], meta)
        carry_in = reconstruct_starting_state(hist_frame, meta, params, "UK")
        labels = [f"w{i}" for i in range(n_future)]
        reference = _plan_from_media(labels, X_full[n_hist:])
        boosted = _plan_from_media(labels, X_full[n_hist:] * 1.5)

        from ancestry_mmm.core.sequential_simulation import (
            compute_incremental_outcome,
            simulate_sequential_outcomes,
        )

        candidate_result = simulate_sequential_outcomes(boosted, carry_in, meta, params)
        reference_result = simulate_sequential_outcomes(
            reference, carry_in, meta, params
        )
        expected = float(
            compute_incremental_outcome(candidate_result, reference_result).sum()
        )
        value = compute_sequential_plan_objective_value(
            boosted, reference, carry_in, meta, params
        )
        assert value == pytest.approx(expected)

    def test_optimizer_uses_sequential_kernel_for_search_and_final_output(self):
        """REQ-OPT-001 / Decision 16: optimisation does not silently
        evaluate a sequential run through the steady-state evaluator."""
        meta = _meta()
        params = _params()
        rng = np.random.default_rng(7)
        n_hist, n_future = 12, 8
        X_full = rng.uniform(50.0, 200.0, size=(n_hist + n_future, len(CHANNELS)))
        hist_frame = _full_frame(X_full[:n_hist], meta)
        carry_in = reconstruct_starting_state(hist_frame, meta, params, "UK")
        labels = [
            str(label.date())
            for label in pd.date_range("2026-02-02", periods=n_future, freq="7D")
        ]
        reference = _plan_from_media(labels, X_full[n_hist:])

        def candidate_plan(monthly_plan):
            values = np.array(
                [
                    [
                        sum(
                            float(period.get(channel, 0.0))
                            for period in monthly_plan.values()
                        )
                        / n_future
                        for channel in CHANNELS
                    ]
                ]
                * n_future
            )
            return _plan_from_media(labels, values)

        context = SequentialOptimisationContext(
            reference_plan=reference,
            candidate_plan=candidate_plan,
            carry_in=carry_in,
        )
        current_plan = {
            "2026-02": {"TV": 800.0, "DNA_Media": 400.0},
        }

        result = optimize_scenario(
            current_spend_plan=current_plan,
            months=["2026-02"],
            channels=CHANNELS,
            market="UK",
            meta=meta,
            params=params,
            reference_context_by_month={"2026-02": {}},
            objective="fh_gsa",
            approval=ModelApproval(approved_by="test", **IDENTITY),
            governance_mode="exploratory",
            evaluation_method="sequential_weekly",
            sequential_context=context,
            max_iter=10,
            **IDENTITY,
        )

        assert result["evaluation_method"] == "sequential_weekly"
        assert result["sequential_optimisation_strategy"] == (
            "T1_direct_replay_point_estimate"
        )
        assert result["sequential_optimisation_objective_horizon"] == (
            "O1_plan_window_total"
        )
        assert result["predicted"]["calculation_method"].eq("sequential_weekly").all()

    def test_market_specific_optimizer_uses_sequential_kernel(self):
        """Decision 16 must remain available for Model C as well as Model A."""
        meta = _meta()
        shared = _params()
        params = FHMarketSpecificPosteriorParams(
            decay_rate=shared.decay_rate,
            hill_K={"UK": dict(shared.hill_K)},
            hill_S=shared.hill_S,
            beta={"UK": {oid: dict(values) for oid, values in shared.beta.items()}},
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
        rng = np.random.default_rng(8)
        n_hist, n_future = 12, 8
        X_full = rng.uniform(50.0, 200.0, size=(n_hist + n_future, len(CHANNELS)))
        hist_frame = _full_frame(X_full[:n_hist], meta)
        carry_in = reconstruct_starting_state_market_specific(
            hist_frame, meta, params, "UK"
        )
        labels = [
            str(label.date())
            for label in pd.date_range("2026-02-02", periods=n_future, freq="7D")
        ]
        reference = _plan_from_media(labels, X_full[n_hist:])

        def candidate_plan(monthly_plan):
            values = np.array(
                [
                    [
                        sum(
                            float(period.get(channel, 0.0))
                            for period in monthly_plan.values()
                        )
                        / n_future
                        for channel in CHANNELS
                    ]
                ]
                * n_future
            )
            return _plan_from_media(labels, values)

        context = SequentialOptimisationContext(
            reference_plan=reference,
            candidate_plan=candidate_plan,
            carry_in=carry_in,
            model_type="market_specific",
        )
        result = optimize_scenario(
            current_spend_plan={
                "2026-02": {"TV": 800.0, "DNA_Media": 400.0},
            },
            months=["2026-02"],
            channels=CHANNELS,
            market="UK",
            meta=meta,
            params=params,
            reference_context_by_month={"2026-02": {}},
            objective="fh_gsa",
            approval=ModelApproval(approved_by="test", **IDENTITY),
            governance_mode="exploratory",
            model_type="market_specific",
            evaluation_method="sequential_weekly",
            sequential_context=context,
            max_iter=10,
            **IDENTITY,
        )

        assert result["evaluation_method"] == "sequential_weekly"
        assert result["predicted"]["calculation_method"].eq("sequential_weekly").all()
