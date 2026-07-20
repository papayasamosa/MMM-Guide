import numpy as np
import pytest

from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
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
