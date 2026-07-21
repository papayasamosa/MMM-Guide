import numpy as np
import pytest

from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.optimization import evaluate_scenario, optimize_scenario
from ancestry_mmm.core.predict import FHPosteriorParams

IDENTITY = dict(
    model_run_id="run-abc123",
    data_fingerprint="data-fp-1",
    model_spec_fingerprint="spec-fp-1",
    posterior_fingerprint="posterior-fp-1",
)


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], segments=["New"], channels=["TV_Brand"], dna_channels=[],
        dna_channel_idx=[], non_dna_idx=[0], dna_segment="New", dna_lag_weeks=4,
        unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.5}, hill_K={"TV_Brand": 1000.0}, hill_S={"TV_Brand": 1.0},
        beta={"New": {"TV_Brand": 0.1}}, halo_strength={"New": 0.0}, promo_coef={"New": 0.1},
        market_offset={"UK": {"New": 0.0}}, intercept={"New": 3.0}, trend_coef={"New": 0.0},
        gamma_fourier={"New": np.zeros(6)}, alpha={"New": 5.0}, control_coef={}, segment_control_coef={},
    )


@pytest.fixture
def approval() -> ModelApproval:
    return ModelApproval(approved_by="Jane Analyst", **IDENTITY)


@pytest.fixture
def reference_context():
    return {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0}, "controls": {}, "segment_controls": {}}}


@pytest.fixture
def spend_plan():
    return {"2024-01": {"TV_Brand": 1000.0}}


@pytest.fixture
def market_specific_meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK", "Australia"], segments=["New"], channels=["TV_Brand"], dna_channels=[],
        dna_channel_idx=[], non_dna_idx=[0], dna_segment="New", dna_lag_weeks=4,
        unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def market_specific_params() -> FHMarketSpecificPosteriorParams:
    markets = ["UK", "Australia"]
    return FHMarketSpecificPosteriorParams(
        decay_rate={"TV_Brand": 0.5},
        hill_K={"UK": {"TV_Brand": 1000.0}, "Australia": {"TV_Brand": 600.0}},
        hill_S={"TV_Brand": 1.0},
        beta={"UK": {"New": {"TV_Brand": 0.1}}, "Australia": {"New": {"TV_Brand": 0.15}}},
        halo_strength={"New": 0.0}, promo_coef={"New": 0.1},
        market_offset={m: {"New": 0.0} for m in markets},
        intercept={"New": 3.0}, trend_coef={"New": 0.0},
        gamma_fourier={"New": np.zeros(6)}, alpha={"New": 5.0},
        control_coef={}, segment_control_coef={},
    )


class TestEvaluateScenarioApprovalEnforcement:
    def test_unapproved_model_cannot_be_evaluated(self, meta, params, spend_plan, reference_context):
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                approval=None, **IDENTITY,
            )

    def test_correctly_approved_model_can_be_evaluated(self, meta, params, approval, spend_plan, reference_context):
        result = evaluate_scenario(
            spend_plan, "UK", meta, params, reference_context,
            approval=approval, **IDENTITY,
        )
        assert not result.empty
        assert set(result.columns) >= {"month", "segment", "predicted_gsa", "value"}

    def test_stale_approval_cannot_be_used(self, meta, params, approval, spend_plan, reference_context):
        stale_identity = dict(IDENTITY)
        stale_identity["posterior_fingerprint"] = "a-different-posterior"  # e.g. model was retrained
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                approval=approval, **stale_identity,
            )

    def test_legacy_approval_cannot_be_used(self, meta, params, spend_plan, reference_context):
        legacy = ModelApproval(approved_by="Jane Analyst")
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                approval=legacy, **IDENTITY,
            )

    def test_the_core_planning_path_rejects_invalid_approval_directly(self, meta, params, spend_plan, reference_context):
        """Calling evaluate_scenario directly - not via the Streamlit page - must still
        be blocked, proving enforcement lives in core, not only in page-level checks."""
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                approval=None, model_run_id="", data_fingerprint="", model_spec_fingerprint="", posterior_fingerprint="",
            )


class TestOptimizeScenarioApprovalEnforcement:
    def test_unapproved_model_cannot_be_optimized(self, meta, params, spend_plan, reference_context):
        with pytest.raises(ApprovalMismatchError):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                approval=None, **IDENTITY,
            )

    def test_correctly_approved_model_can_be_optimized(self, meta, params, approval, spend_plan, reference_context):
        result = optimize_scenario(
            spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
            approval=approval, **IDENTITY,
        )
        assert "spend_plan" in result and "predicted" in result

    def test_stale_or_mismatched_approval_cannot_be_used(self, meta, params, approval, spend_plan, reference_context):
        stale_identity = dict(IDENTITY)
        stale_identity["model_run_id"] = "a-newer-run"
        with pytest.raises(ApprovalMismatchError):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                approval=approval, **stale_identity,
            )

    def test_rejected_before_running_the_optimiser(self, meta, params, spend_plan, reference_context, monkeypatch):
        """Approval is checked up front - the (potentially slow) SLSQP call must never
        run for an invalid approval, not just get its result discarded afterwards."""
        import ancestry_mmm.core.optimization as optimization_module

        def _fail_if_called(*args, **kwargs):
            raise AssertionError("minimize() should not be called when approval is invalid")

        monkeypatch.setattr(optimization_module, "minimize", _fail_if_called)
        with pytest.raises(ApprovalMismatchError):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                approval=None, **IDENTITY,
            )


class TestModelTypeDispatch:
    def test_default_model_type_is_shared(self, meta, params, approval, spend_plan, reference_context):
        # No model_type kwarg at all - must behave exactly as before Phase 3c.
        result = evaluate_scenario(spend_plan, "UK", meta, params, reference_context, approval=approval, **IDENTITY)
        assert not result.empty

    def test_invalid_model_type_raises(self, meta, params, approval, spend_plan, reference_context):
        with pytest.raises(ValueError, match="model_type must be"):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                model_type="not_a_real_type", approval=approval, **IDENTITY,
            )

    def test_market_specific_evaluate_scenario_uses_that_markets_own_curve(
        self, market_specific_meta, market_specific_params, approval, spend_plan, reference_context,
    ):
        uk_result = evaluate_scenario(
            spend_plan, "UK", market_specific_meta, market_specific_params, reference_context,
            model_type="market_specific", approval=approval, **IDENTITY,
        )
        au_result = evaluate_scenario(
            spend_plan, "Australia", market_specific_meta, market_specific_params, reference_context,
            model_type="market_specific", approval=approval, **IDENTITY,
        )
        # Different beta/K between markets -> different predicted GSAs for the same spend plan.
        assert uk_result["predicted_gsa"].iloc[0] != pytest.approx(au_result["predicted_gsa"].iloc[0])

    def test_market_specific_optimize_scenario_runs_end_to_end(
        self, market_specific_meta, market_specific_params, approval, spend_plan, reference_context,
    ):
        result = optimize_scenario(
            spend_plan, ["2024-01"], ["TV_Brand"], "UK", market_specific_meta, market_specific_params,
            reference_context, model_type="market_specific", approval=approval, **IDENTITY,
        )
        assert "spend_plan" in result and "predicted" in result
        assert not result["predicted"].empty


class TestAverageCpa:
    def test_avg_cpa_is_total_spend_over_total_predicted_gsa(self, meta, params, approval, spend_plan, reference_context):
        result = evaluate_scenario(spend_plan, "UK", meta, params, reference_context, approval=approval, **IDENTITY)
        total_spend = result["total_spend"].iloc[0]
        total_gsa = result["predicted_gsa"].sum()
        assert result["avg_cpa"].iloc[0] == pytest.approx(total_spend / total_gsa)

    def test_avg_cpa_is_repeated_across_every_segment_row_for_the_same_month(
        self, market_specific_meta, market_specific_params, approval, reference_context,
    ):
        # A multi-segment month should carry one avg_cpa value (computed from the
        # month's *total* predicted GSA across segments), not a different one per segment row.
        meta_two_segments = FHModelMeta(
            markets=["UK"], segments=["New", "Winback"], channels=["TV_Brand"], dna_channels=[],
            dna_channel_idx=[], non_dna_idx=[0], dna_segment="New", dna_lag_weeks=4,
            unpooled_markets=[], control_names=[],
        )
        params = FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5}, hill_K={"TV_Brand": 1000.0}, hill_S={"TV_Brand": 1.0},
            beta={"New": {"TV_Brand": 0.1}, "Winback": {"TV_Brand": 0.05}},
            halo_strength={"New": 0.0, "Winback": 0.0}, promo_coef={"New": 0.1, "Winback": 0.1},
            market_offset={"UK": {"New": 0.0, "Winback": 0.0}}, intercept={"New": 3.0, "Winback": 2.0},
            trend_coef={"New": 0.0, "Winback": 0.0},
            gamma_fourier={"New": np.zeros(6), "Winback": np.zeros(6)},
            alpha={"New": 5.0, "Winback": 5.0}, control_coef={}, segment_control_coef={},
        )
        ref = {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0, "Winback": 0.0}, "controls": {}, "segment_controls": {}}}
        result = evaluate_scenario(
            {"2024-01": {"TV_Brand": 1000.0}}, "UK", meta_two_segments, params, ref,
            approval=approval, **IDENTITY,
        )
        assert len(result) == 2  # one row per segment
        assert result["avg_cpa"].nunique() == 1
