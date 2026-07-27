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

OUTCOME_IDS = ["New", "DNA_CrossSell"]
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
        markets=MARKETS, outcome_ids=OUTCOME_IDS, channels=CHANNELS,
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def trace() -> az.InferenceData:
    """Model A ("shared curve") shaped posterior - `beta`/`hill_K` have no
    market dimension, matching `core.predict.extract_posterior_params`."""
    n_chain, n_draw = 2, 20
    coords = {"outcome": OUTCOME_IDS, "channel": CHANNELS, "market": MARKETS, "fourier": list(range(4))}
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
        "beta": ["outcome", "channel"], "halo_strength": ["outcome"],
        "promo_coef": ["outcome"], "market_offset": ["market", "outcome"],
        "intercept": ["outcome"], "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"], "alpha": ["outcome"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


@pytest.fixture
def market_trace() -> az.InferenceData:
    """Model C ("market-specific") shaped posterior - `beta`/`hill_K` are
    market-indexed, matching `core.market_specific_predict.extract_market_specific_posterior_params`."""
    n_chain, n_draw = 2, 20
    coords = {"outcome": OUTCOME_IDS, "channel": CHANNELS, "market": MARKETS, "fourier": list(range(4))}
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
        "beta": ["market", "outcome", "channel"], "halo_strength": ["outcome"],
        "promo_coef": ["outcome"], "market_offset": ["market", "outcome"],
        "intercept": ["outcome"], "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"], "alpha": ["outcome"],
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
    """G2A.7a.10 (brief section 6.3): these tests exercise numerical
    properties only (credible-interval ordering, paired baseline-comparison
    probabilities, summary column presence) - not governance semantics, which
    TestEvaluateScenarioWithUncertaintyGovernance below covers with real
    approval/outcome-approval fixtures. governance_mode="exploratory" is used
    deliberately here rather than supplying a PlanningObjective + matching
    OutcomeApprovals these tests don't otherwise need."""

    @pytest.fixture
    def approval(self) -> ModelApproval:
        return ModelApproval(approved_by="Jane Analyst", **IDENTITY)

    @pytest.fixture
    def reference_context(self):
        return {"2024-01": {"trend": 1.0, "fourier": np.zeros(4), "promo": {s: 0.0 for s in OUTCOME_IDS}, "controls": {}, "outcome_controls": {}}}

    def test_summary_has_lower_le_mean_le_upper_for_value(self, meta, market_trace, approval, reference_context):
        # value is only meaningful (non-NaN) once every eligible outcome_id
        # is priced (PR E.2 - raw units are never silently shown as value).
        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        ltv = {oid: 5.0 for oid in OUTCOME_IDS}
        result = evaluate_scenario_with_uncertainty(
            spend_plan, "UK", meta, market_trace, reference_context, ltv=ltv,
            model_type="market_specific", n_draws=20, seed=1,
            approval=approval, governance_mode="exploratory", **IDENTITY,
        )
        summary = result["summary"]
        assert np.all(summary["value_lower"] <= summary["value_mean"] + 1e-9)
        assert np.all(summary["value_mean"] <= summary["value_upper"] + 1e-9)
        assert result["n_draws"] == 20
        assert result["prob_outperforms_baseline"] is None
        assert len(result["draws"]["posterior_draw"].unique()) == 20
        assert {
            "incremental_outcome_mean",
            "incremental_outcome_lower",
            "incremental_outcome_upper",
            "probability_incremental_positive",
            "incremental_nbt_cpa_mean",
            "incremental_roi_mean",
        } <= set(summary.columns)
        assert summary["probability_incremental_positive"].between(0, 1).all()

    def test_paired_baseline_comparison_gives_prob_one_when_proposed_strictly_dominates(
        self, meta, market_trace, approval, reference_context,
    ):
        higher_spend = {"2024-01": {"TV_Brand": 5000.0, "DNA_Media": 2000.0}}
        lower_spend = {"2024-01": {"TV_Brand": 10.0, "DNA_Media": 5.0}}
        ltv = {oid: 5.0 for oid in OUTCOME_IDS}
        result = evaluate_scenario_with_uncertainty(
            higher_spend, "UK", meta, market_trace, reference_context, ltv=ltv,
            model_type="market_specific", n_draws=20, seed=1,
            approval=approval, governance_mode="exploratory",
            baseline_spend_plan=lower_spend, **IDENTITY,
        )
        assert result["prob_outperforms_baseline"] == pytest.approx(1.0)

    def test_paired_baseline_comparison_gives_prob_zero_when_reversed(self, meta, market_trace, approval, reference_context):
        higher_spend = {"2024-01": {"TV_Brand": 5000.0, "DNA_Media": 2000.0}}
        lower_spend = {"2024-01": {"TV_Brand": 10.0, "DNA_Media": 5.0}}
        ltv = {oid: 5.0 for oid in OUTCOME_IDS}
        result = evaluate_scenario_with_uncertainty(
            lower_spend, "UK", meta, market_trace, reference_context, ltv=ltv,
            model_type="market_specific", n_draws=20, seed=1,
            approval=approval, governance_mode="exploratory",
            baseline_spend_plan=higher_spend, **IDENTITY,
        )
        assert result["prob_outperforms_baseline"] == pytest.approx(0.0)

    def test_summary_carries_product_aware_and_total_value_columns(self, meta, market_trace, approval, reference_context):
        """The per-draw scenario summary must expose the same product-aware
        split as the point-estimate path (core.optimization.evaluate_scenario):
        this fixture's meta has no kit-only segments, so dna_avg_cpa is
        NaN throughout - not present at all would be a silent regression."""
        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        ltv = {oid: 5.0 for oid in OUTCOME_IDS}
        result = evaluate_scenario_with_uncertainty(
            spend_plan, "UK", meta, market_trace, reference_context, ltv=ltv,
            model_type="market_specific", n_draws=20, seed=1,
            approval=approval, governance_mode="exploratory", **IDENTITY,
        )
        summary = result["summary"]
        assert {"dna_avg_cpa_mean", "dna_avg_cpa_lower", "dna_avg_cpa_upper", "total_value_mean", "total_value_lower", "total_value_upper"} <= set(summary.columns)
        assert np.all(summary["dna_avg_cpa_mean"].isna())  # no kit-only segments in this fixture
        assert np.all(summary["total_value_lower"] <= summary["total_value_mean"] + 1e-9)
        assert np.all(summary["total_value_mean"] <= summary["total_value_upper"] + 1e-9)


class TestEvaluateScenarioWithUncertaintyGovernance:
    """G2A.7a.1 (section 4.3, REQ-PLAN-001, REQ-USE-001): before this fix,
    evaluate_scenario_with_uncertainty had no outcome_approvals/governance_mode
    parameters at all, so a caller passing them (e.g. the Scenario Planner
    page's manual-uncertainty checkbox) got `TypeError: got an unexpected
    keyword argument`. These tests are a regression guard for that crash,
    plus confirmation that governance is actually enforced/forwarded, not
    just silently accepted."""

    @pytest.fixture
    def approval(self) -> ModelApproval:
        return ModelApproval(approved_by="Jane Analyst", **IDENTITY)

    @pytest.fixture
    def reference_context(self):
        return {"2024-01": {"trend": 1.0, "fourier": np.zeros(4), "promo": {s: 0.0 for s in OUTCOME_IDS}, "controls": {}, "outcome_controls": {}}}

    @pytest.fixture
    def meta_with_catalogue(self) -> FHModelMeta:
        from ancestry_mmm.core.outcomes import FAMILY_HISTORY, METRIC_KEY_FH_GSA, OutcomeDefinition

        catalogue = [
            OutcomeDefinition(
                outcome_id="New", product=FAMILY_HISTORY, segment="New", metric="GSA",
                metric_key=METRIC_KEY_FH_GSA, source_column="GSA_New", unit="GSA",
                aggregation_type="count", event_definition="A new subscriber",
                date_basis="event_date", cohort_or_attribution_basis="signup_cohort",
                completeness_or_maturity_policy="Mature after 12 weeks",
                exclusions="Excludes internal/test accounts",
                reconciliation_source="Finance report", business_owner="Analytics",
                definition_version="1.0",
            ),
        ]
        return FHModelMeta(
            markets=MARKETS, outcome_ids=OUTCOME_IDS, channels=CHANNELS,
            dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_outcome_id="DNA_CrossSell", dna_lag_weeks=1, unpooled_markets=[], control_names=[],
            outcome_catalogue_at_fit=catalogue,
        )

    def test_accepts_outcome_governance_kwargs_without_typeerror(self, meta, market_trace, approval, reference_context):
        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        # Must not raise TypeError - the confirmed P0 crash this fixes.
        result = evaluate_scenario_with_uncertainty(
            spend_plan, "UK", meta, market_trace, reference_context,
            model_type="market_specific", n_draws=10, seed=1,
            approval=approval, outcome_approvals=[], governance_mode="exploratory",
            nbt_completeness_metadata=None, **IDENTITY,
        )
        assert "summary" in result

    def test_official_mode_with_planning_objective_and_no_approval_blocks(
        self, meta_with_catalogue, market_trace, approval, reference_context,
    ):
        from ancestry_mmm.core.optimization import PlanningObjective
        from ancestry_mmm.core.outcome_approval import OutcomeApprovalBlockedError
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA

        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        planning_objective = PlanningObjective(
            estimand="incremental_outcome", metric_key=METRIC_KEY_FH_GSA, target_outcome_ids=("New",),
        )
        with pytest.raises(OutcomeApprovalBlockedError):
            evaluate_scenario_with_uncertainty(
                spend_plan, "UK", meta_with_catalogue, market_trace, reference_context,
                model_type="market_specific", n_draws=10, seed=1,
                approval=approval, planning_objective=planning_objective,
                governance_mode="official", **IDENTITY,
            )

    def test_official_mode_with_matching_approval_succeeds(
        self, meta_with_catalogue, market_trace, approval, reference_context,
    ):
        from ancestry_mmm.core.optimization import PlanningObjective
        from ancestry_mmm.core.outcome_approval import OutcomeApproval, fingerprint_outcome_definition
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA

        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        planning_objective = PlanningObjective(
            estimand="incremental_outcome", metric_key=METRIC_KEY_FH_GSA, target_outcome_ids=("New",),
        )
        gsa_definition = meta_with_catalogue.outcome_catalogue_at_fit[0]
        gsa_approval = OutcomeApproval(
            approval_id="apr-gsa", outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(gsa_definition),
            status="approved", allowed_uses=("planning",),
            approved_by="Jane Analyst", approved_at="2026-01-01",
        )
        result = evaluate_scenario_with_uncertainty(
            spend_plan, "UK", meta_with_catalogue, market_trace, reference_context,
            model_type="market_specific", n_draws=10, seed=1,
            approval=approval, planning_objective=planning_objective,
            outcome_approvals=[gsa_approval], governance_mode="official", **IDENTITY,
        )
        assert "summary" in result

    def test_optimisation_operation_accepts_optimisation_scoped_approval(
        self, meta_with_catalogue, market_trace, approval, reference_context,
    ):
        """G2A.7a.10 (brief section 6.2, 12.1): optimize_scenario's posterior
        evaluation now passes operation="optimisation" (matching its own
        already-resolved optimisation proof) instead of implicitly resolving
        for "planning" - an approval scoped to "optimisation" only (not
        "planning") must succeed here, the same as it does inside
        optimize_scenario itself."""
        from ancestry_mmm.core.optimization import PlanningObjective
        from ancestry_mmm.core.outcome_approval import OutcomeApproval, fingerprint_outcome_definition
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA

        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        planning_objective = PlanningObjective(
            estimand="incremental_outcome", metric_key=METRIC_KEY_FH_GSA, target_outcome_ids=("New",),
        )
        gsa_definition = meta_with_catalogue.outcome_catalogue_at_fit[0]
        optimisation_approval = OutcomeApproval(
            approval_id="apr-gsa", outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(gsa_definition),
            status="approved", allowed_uses=("optimisation",),
            approved_by="Jane Analyst", approved_at="2026-01-01",
        )
        result = evaluate_scenario_with_uncertainty(
            spend_plan, "UK", meta_with_catalogue, market_trace, reference_context,
            model_type="market_specific", n_draws=10, seed=1,
            approval=approval, planning_objective=planning_objective,
            outcome_approvals=[optimisation_approval],
            governance_mode="official", operation="optimisation", **IDENTITY,
        )
        assert "summary" in result

    # -- G2A.7a.10 (brief section 6, 14.3): evaluate_scenario_with_uncertainty
    # previously accepted `approval` without ever validating it, and only
    # checked `outcome_approvals` for truthiness - not status, expiry, use,
    # scope, or fingerprint. These tests lock in the real validation now
    # wired through the same resolve_planning_governance() used by
    # evaluate_manual_scenario/optimize_scenario.

    def test_object_list_as_outcome_approvals_never_authorises_official_output(
        self, meta_with_catalogue, market_trace, approval, reference_context,
    ):
        from ancestry_mmm.core.optimization import PlanningObjective
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA

        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        planning_objective = PlanningObjective(
            estimand="incremental_outcome", metric_key=METRIC_KEY_FH_GSA, target_outcome_ids=("New",),
        )
        # A list of junk objects is truthy (passes the old `not
        # outcome_approvals` check) but must never authorise official
        # output - it fails resolving real approval identity instead of
        # silently succeeding.
        with pytest.raises(Exception):
            evaluate_scenario_with_uncertainty(
                spend_plan, "UK", meta_with_catalogue, market_trace, reference_context,
                model_type="market_specific", n_draws=10, seed=1,
                approval=approval, planning_objective=planning_objective,
                outcome_approvals=[object()], governance_mode="official", **IDENTITY,
            )

    def test_stale_model_approval_blocks(
        self, meta_with_catalogue, market_trace, reference_context,
    ):
        from ancestry_mmm.core.approval import ApprovalMismatchError
        from ancestry_mmm.core.optimization import PlanningObjective
        from ancestry_mmm.core.outcome_approval import OutcomeApproval, fingerprint_outcome_definition
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA

        stale_approval = ModelApproval(
            approved_by="Jane Analyst",
            model_run_id="run-OLD", data_fingerprint="data-fp-1",
            model_spec_fingerprint="spec-fp-1", posterior_fingerprint="posterior-fp-1",
        )
        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        planning_objective = PlanningObjective(
            estimand="incremental_outcome", metric_key=METRIC_KEY_FH_GSA, target_outcome_ids=("New",),
        )
        gsa_definition = meta_with_catalogue.outcome_catalogue_at_fit[0]
        gsa_approval = OutcomeApproval(
            approval_id="apr-gsa", outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(gsa_definition),
            status="approved", allowed_uses=("planning",),
            approved_by="Jane Analyst", approved_at="2026-01-01",
        )
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario_with_uncertainty(
                spend_plan, "UK", meta_with_catalogue, market_trace, reference_context,
                model_type="market_specific", n_draws=10, seed=1,
                approval=stale_approval, planning_objective=planning_objective,
                outcome_approvals=[gsa_approval], governance_mode="official", **IDENTITY,
            )

    def test_rejected_outcome_approval_blocks(
        self, meta_with_catalogue, market_trace, approval, reference_context,
    ):
        from ancestry_mmm.core.optimization import PlanningObjective
        from ancestry_mmm.core.outcome_approval import (
            OutcomeApproval,
            OutcomeApprovalBlockedError,
            fingerprint_outcome_definition,
        )
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA

        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        planning_objective = PlanningObjective(
            estimand="incremental_outcome", metric_key=METRIC_KEY_FH_GSA, target_outcome_ids=("New",),
        )
        gsa_definition = meta_with_catalogue.outcome_catalogue_at_fit[0]
        rejected_approval = OutcomeApproval(
            approval_id="apr-gsa", outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(gsa_definition),
            status="rejected", allowed_uses=("planning",),
            approved_by="Jane Analyst", approved_at="2026-01-01",
        )
        with pytest.raises(OutcomeApprovalBlockedError):
            evaluate_scenario_with_uncertainty(
                spend_plan, "UK", meta_with_catalogue, market_trace, reference_context,
                model_type="market_specific", n_draws=10, seed=1,
                approval=approval, planning_objective=planning_objective,
                outcome_approvals=[rejected_approval], governance_mode="official", **IDENTITY,
            )

    def test_expired_outcome_approval_blocks(
        self, meta_with_catalogue, market_trace, approval, reference_context,
    ):
        from ancestry_mmm.core.optimization import PlanningObjective
        from ancestry_mmm.core.outcome_approval import (
            OutcomeApproval,
            OutcomeApprovalBlockedError,
            fingerprint_outcome_definition,
        )
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA

        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        planning_objective = PlanningObjective(
            estimand="incremental_outcome", metric_key=METRIC_KEY_FH_GSA, target_outcome_ids=("New",),
        )
        gsa_definition = meta_with_catalogue.outcome_catalogue_at_fit[0]
        expired_approval = OutcomeApproval(
            approval_id="apr-gsa", outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(gsa_definition),
            status="approved", allowed_uses=("planning",),
            approved_by="Jane Analyst", approved_at="2020-01-01",
            expires_at="2020-06-01",
        )
        with pytest.raises(OutcomeApprovalBlockedError):
            evaluate_scenario_with_uncertainty(
                spend_plan, "UK", meta_with_catalogue, market_trace, reference_context,
                model_type="market_specific", n_draws=10, seed=1,
                approval=approval, planning_objective=planning_objective,
                outcome_approvals=[expired_approval], governance_mode="official", **IDENTITY,
            )

    def test_wrong_use_outcome_approval_blocks(
        self, meta_with_catalogue, market_trace, approval, reference_context,
    ):
        from ancestry_mmm.core.optimization import PlanningObjective
        from ancestry_mmm.core.outcome_approval import (
            OutcomeApproval,
            OutcomeApprovalBlockedError,
            fingerprint_outcome_definition,
        )
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA

        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        planning_objective = PlanningObjective(
            estimand="incremental_outcome", metric_key=METRIC_KEY_FH_GSA, target_outcome_ids=("New",),
        )
        gsa_definition = meta_with_catalogue.outcome_catalogue_at_fit[0]
        # Approved for "optimisation" only - this call resolves for the
        # default operation="planning".
        optimisation_only_approval = OutcomeApproval(
            approval_id="apr-gsa", outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(gsa_definition),
            status="approved", allowed_uses=("optimisation",),
            approved_by="Jane Analyst", approved_at="2026-01-01",
        )
        with pytest.raises(OutcomeApprovalBlockedError):
            evaluate_scenario_with_uncertainty(
                spend_plan, "UK", meta_with_catalogue, market_trace, reference_context,
                model_type="market_specific", n_draws=10, seed=1,
                approval=approval, planning_objective=planning_objective,
                outcome_approvals=[optimisation_only_approval],
                governance_mode="official", operation="planning", **IDENTITY,
            )

    def test_wrong_scope_outcome_approval_blocks(
        self, meta_with_catalogue, market_trace, approval, reference_context,
    ):
        from ancestry_mmm.core.optimization import PlanningObjective
        from ancestry_mmm.core.outcome_approval import (
            OutcomeApproval,
            OutcomeApprovalBlockedError,
            fingerprint_outcome_definition,
        )
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA

        spend_plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Media": 200.0}}
        planning_objective = PlanningObjective(
            estimand="incremental_outcome", metric_key=METRIC_KEY_FH_GSA, target_outcome_ids=("New",),
        )
        gsa_definition = meta_with_catalogue.outcome_catalogue_at_fit[0]
        # Approved for the "AU" market only - this evaluation is for "UK".
        wrong_market_approval = OutcomeApproval(
            approval_id="apr-gsa", outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(gsa_definition),
            status="approved", allowed_uses=("planning",),
            approved_by="Jane Analyst", approved_at="2026-01-01",
            market_scope=("AU",),
        )
        with pytest.raises(OutcomeApprovalBlockedError):
            evaluate_scenario_with_uncertainty(
                spend_plan, "UK", meta_with_catalogue, market_trace, reference_context,
                model_type="market_specific", n_draws=10, seed=1,
                approval=approval, planning_objective=planning_objective,
                outcome_approvals=[wrong_market_approval],
                governance_mode="official", **IDENTITY,
            )
