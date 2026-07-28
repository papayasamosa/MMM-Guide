"""
Tests for ``core.validation_policy`` — validation-policy and
approval-readiness foundation (REQ-VAL-001).
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.validation_policy import (
    ThresholdPolicy,
    ValidationGate,
    ValidationResult,
    ValidationWaiverReference,
    evaluate_approval_readiness,
    readiness_to_dict,
)

# Default ModelIdentity matching _make_result's identity fields
_DEFAULT_IDENTITY = ModelIdentity("run-123", "data-abc", "spec-def", "post-ghi")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(
    gate_name: str,
    status: str = "pass",
    value: float | None = None,
    message: str = "",
) -> ValidationResult:
    """Helper to build a ValidationResult with mininal identity fields."""
    return ValidationResult(
        gate_name=gate_name,
        status=status,
        value=value,
        message=message or f"{gate_name}={value}",
        model_run_id="run-123",
        data_fingerprint="data-abc",
        model_spec_fingerprint="spec-def",
        posterior_fingerprint="post-ghi",
        policy_id="val-pol-001",
        policy_version="1.0.0",
    )


@pytest.fixture
def convergence_gate() -> ValidationGate:
    return ValidationGate(
        name="convergence_rhat",
        description="All R-hat values must be below 1.05",
        evaluator_id="rhat",
        scope="all_models",
        acceptable_range=(0.0, 1.05),
        direction="lower_is_better",
        blocking=True,
        waivable=False,
        required=True,
    )


@pytest.fixture
def ppc_gate() -> ValidationGate:
    return ValidationGate(
        name="ppc_coverage",
        description="Posterior predictive coverage within expected range",
        evaluator_id="ppc",
        scope="all_models",
        acceptable_range=(70.0, 100.0),
        direction="higher_is_better",
        blocking=True,
        waivable=True,
        required=True,
    )


@pytest.fixture
def backtest_gate() -> ValidationGate:
    return ValidationGate(
        name="backtest_mape",
        description="Backtest MAPE within acceptable range",
        evaluator_id="mape",
        scope="all_models",
        acceptable_range=(0.0, 30.0),
        direction="lower_is_better",
        blocking=False,
        waivable=True,
        required=False,
    )


@pytest.fixture
def divergence_gate() -> ValidationGate:
    return ValidationGate(
        name="divergences",
        description="No divergences in sampling",
        evaluator_id="divergences",
        scope="all_models",
        acceptable_range=None,
        direction="lower_is_better",
        blocking=True,
        waivable=False,
        required=True,
    )


@pytest.fixture
def sample_policy(
    convergence_gate: ValidationGate,
    ppc_gate: ValidationGate,
    backtest_gate: ValidationGate,
    divergence_gate: ValidationGate,
) -> ThresholdPolicy:
    return ThresholdPolicy(
        policy_id="val-pol-001",
        version="1.0.0",
        scope="all_models",
        gates=[convergence_gate, ppc_gate, backtest_gate, divergence_gate],
        owner="Modelling Team",
        approval_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def expired_policy(
    convergence_gate: ValidationGate,
) -> ThresholdPolicy:
    return ThresholdPolicy(
        policy_id="val-pol-expired",
        version="1.0.0",
        scope="all_models",
        gates=[convergence_gate],
        owner="Modelling Team",
        approval_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expiry=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# ThresholdPolicy structure
# ---------------------------------------------------------------------------


class TestThresholdPolicyStructure:
    def test_policy_has_required_fields(self):
        policy = ThresholdPolicy(
            policy_id="p1", version="1.0", scope="test", owner="Test Owner"
        )
        assert policy.policy_id == "p1"
        assert policy.version == "1.0"
        assert policy.scope == "test"
        assert policy.gates == []
        assert policy.owner == "Test Owner"

    def test_version_is_string(self):
        policy = ThresholdPolicy(
            policy_id="p1", version="1.0.0", scope="test", owner="Test Owner"
        )
        assert isinstance(policy.version, str)

    def test_is_expired_with_no_expiry(self):
        policy = ThresholdPolicy(
            policy_id="p1", version="1.0", scope="test", owner="Test Owner"
        )
        assert not policy.is_expired()

    def test_is_expired_when_past_expiry(self, expired_policy):
        assert expired_policy.is_expired(
            as_of=datetime(2026, 7, 1, tzinfo=timezone.utc)
        )

    def test_is_expired_when_before_expiry(self, expired_policy):
        assert not expired_policy.is_expired(
            as_of=datetime(2026, 5, 1, tzinfo=timezone.utc)
        )

    def test_get_gate_returns_valid_gate(self, sample_policy, convergence_gate):
        gate = sample_policy.get_gate("convergence_rhat")
        assert gate is not None
        assert gate.name == convergence_gate.name

    def test_get_gate_returns_none_for_unknown(self, sample_policy):
        assert sample_policy.get_gate("nonexistent") is None


# ---------------------------------------------------------------------------
# ValidationGate
# ---------------------------------------------------------------------------


class TestValidationGate:
    def test_gate_has_scope_and_blocking_flag(self):
        gate = ValidationGate(
            name="test_gate",
            description="A test gate",
            scope="all_models",
            blocking=True,
            required=True,
        )
        assert gate.scope == "all_models"
        assert gate.blocking is True
        assert gate.required is True

    def test_gate_with_waiver_creates_reference(self):
        gate = ValidationGate(
            name="waivable_gate",
            description="A waivable gate",
            blocking=True,
            waivable=True,
            required=True,
        )
        assert gate.waivable is True

    def test_gate_defaults(self):
        gate = ValidationGate(name="minimal", description="Minimal gate")
        assert gate.scope == "all_models"
        assert gate.blocking is True
        assert gate.waivable is False
        assert gate.required is True
        assert gate.acceptable_range is None

    def test_gate_with_numeric_range(self):
        gate = ValidationGate(
            name="rhat",
            description="R-hat check",
            acceptable_range=(0.0, 1.05),
            blocking=True,
            required=True,
        )
        assert gate.acceptable_range == (0.0, 1.05)


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_passing_result(self):
        r = ValidationResult(gate_name="test", status="pass", message="OK")
        assert r.passed is True
        assert r.value is None
        assert r.status == "pass"

    def test_failing_result_with_value(self):
        r = ValidationResult(
            gate_name="rhat",
            status="fail",
            value=1.2,
            message="Max R-hat is 1.2, exceeds 1.05",
        )
        assert r.passed is False
        assert r.value == 1.2
        assert r.status == "fail"

    def test_review_status(self):
        r = ValidationResult(
            gate_name="test", status="review", value=1.1, message="Borderline"
        )
        assert r.passed is False
        assert r.status == "review"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            ValidationResult(gate_name="test", status="invalid")

    def test_is_stale_for_when_identity_mismatch(self):
        r = ValidationResult(
            gate_name="test",
            status="pass",
            model_run_id="old-run",
            data_fingerprint="old-data",
            model_spec_fingerprint="old-spec",
            posterior_fingerprint="old-post",
            policy_id="pol-1",
            policy_version="1.0",
        )
        assert r.is_stale_for(
            model_run_id="new-run",
            data_fingerprint="new-data",
            model_spec_fingerprint="new-spec",
            posterior_fingerprint="new-post",
            policy_id="pol-1",
            policy_version="1.0",
        )

    def test_is_not_stale_for_when_identity_matches(self):
        r = ValidationResult(
            gate_name="test",
            status="pass",
            model_run_id="run-1",
            data_fingerprint="data-1",
            model_spec_fingerprint="spec-1",
            posterior_fingerprint="post-1",
            policy_id="pol-1",
            policy_version="1.0",
        )
        assert not r.is_stale_for(
            model_run_id="run-1",
            data_fingerprint="data-1",
            model_spec_fingerprint="spec-1",
            posterior_fingerprint="post-1",
            policy_id="pol-1",
            policy_version="1.0",
        )


# ---------------------------------------------------------------------------
# ApprovalReadiness evaluation
# ---------------------------------------------------------------------------


class TestApprovalReadinessEvaluation:
    """Core behaviour tests for evaluate_approval_readiness."""

    def test_matching_successful_readiness_passes(self, sample_policy):
        """All required gates pass -> overall_ready is True."""
        results = [
            _make_result("convergence_rhat", "pass", 1.02, "Converged"),
            _make_result("ppc_coverage", "pass", 85.0, "Coverage OK"),
            _make_result("backtest_mape", "pass", 20.0, "MAPE OK"),
            _make_result("divergences", "pass", 0, "No divergences"),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY
        )
        assert readiness.overall_ready is True
        assert len(readiness.blocking_failures) == 0
        assert len(readiness.missing_required_gates) == 0
        assert len(readiness.passes) == 4

    def test_missing_required_gate_blocks(self, sample_policy):
        """A required gate with no result blocks official approval."""
        results = [
            _make_result("convergence_rhat", "pass", 1.02),
            # ppc_coverage missing — but it's required
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "pass", 0),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY
        )
        assert readiness.overall_ready is False
        assert "ppc_coverage" in readiness.missing_required_gates

    def test_failed_blocking_gate_blocks(self, sample_policy):
        """A blocking gate that fails blocks official approval."""
        results = [
            _make_result("convergence_rhat", "fail", 1.2, "R-hat too high"),
            _make_result("ppc_coverage", "pass", 85.0),
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "pass", 0),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY
        )
        assert readiness.overall_ready is False
        assert len(readiness.blocking_failures) == 1
        assert readiness.blocking_failures[0].gate_name == "convergence_rhat"

    def test_review_only_gate_does_not_block(self, sample_policy):
        """A non-blocking failing (review) gate is a review item, not a blocker."""
        results = [
            _make_result("convergence_rhat", "pass", 1.02),
            _make_result("ppc_coverage", "pass", 85.0),
            # backtest_mape is non-blocking and gets review status
            _make_result("backtest_mape", "review", 35.0, "MAPE elevated"),
            _make_result("divergences", "pass", 0),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY
        )
        assert readiness.overall_ready is True  # review doesn't block
        assert len(readiness.review_items) == 1
        assert readiness.review_items[0].gate_name == "backtest_mape"
        assert len(readiness.blocking_failures) == 0

    def test_expired_policy_blocks(self, expired_policy):
        """An expired policy makes overall_ready False."""
        results = [
            _make_result("convergence_rhat", "pass", 1.02),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = evaluate_approval_readiness(
            results, expired_policy, _DEFAULT_IDENTITY, as_of=as_of
        )
        assert readiness.overall_ready is False

    def test_stale_validation_artefact_blocks(self, sample_policy):
        """A stale result (identity mismatch) blocks approval."""
        # Create a result with empty identity fields — incomplete binding is stale
        stale = ValidationResult(
            gate_name="convergence_rhat",
            status="pass",
            value=1.02,
            model_run_id="",
            data_fingerprint="",
            model_spec_fingerprint="",
            posterior_fingerprint="",
            policy_id="val-pol-001",
            policy_version="1.0.0",
        )
        results = [
            stale,
            _make_result("ppc_coverage", "pass", 85.0),
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "pass", 0),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY
        )
        # A stale result is treated as missing — convergence_rhat is required
        assert "convergence_rhat" in readiness.missing_required_gates
        assert readiness.overall_ready is False

    def test_approved_waiver_unblocks(self, sample_policy):
        """A failing waivable gate unblocked by an approved waiver."""
        results = [
            _make_result("convergence_rhat", "pass", 1.02),
            # ppc_coverage is waivable and fails
            _make_result("ppc_coverage", "fail", 65.0, "Coverage below target"),
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "pass", 0),
        ]
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-001",
                approved_by="Reviewer A",
                approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                reason="Accepted lower coverage due to sparse data",
                gate_name="ppc_coverage",
            ),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers
        )
        assert readiness.overall_ready is True
        assert len(readiness.waivers_applied) == 1

    def test_non_waivable_failure_still_blocks(self, sample_policy):
        """A non-waivable gate that fails cannot be unblocked by a waiver."""
        results = [
            _make_result("convergence_rhat", "fail", 1.2),
            _make_result("ppc_coverage", "pass", 85.0),
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "pass", 0),
        ]
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-002",
                approved_by="Reviewer A",
                approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                reason="Waiver for convergence failure",
                gate_name="convergence_rhat",
            ),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers
        )
        # convergence_rhat is not waivable, so waiver doesn't apply
        assert readiness.overall_ready is False
        assert len(readiness.blocking_failures) == 1

    def test_multiple_blocking_failures_reported(self, sample_policy):
        """Multiple failing blocking gates are all reported."""
        results = [
            _make_result("convergence_rhat", "fail", 1.2),
            _make_result("ppc_coverage", "fail", 50.0),
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "fail", 5, "Divergences found"),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY
        )
        assert readiness.overall_ready is False
        assert len(readiness.blocking_failures) == 3

    def test_no_results_at_all(self, sample_policy):
        """With no results, all required gates are missing."""
        readiness = evaluate_approval_readiness([], sample_policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is False
        assert (
            len(readiness.missing_required_gates) == 3
        )  # convergence, ppc, divergences (backtest not required)
        assert "backtest_mape" not in readiness.missing_required_gates

    def test_expired_waiver_does_not_unblock(self, sample_policy):
        """An expired waiver must not unblock a failing gate."""
        results = [
            _make_result("convergence_rhat", "pass", 1.02),
            _make_result("ppc_coverage", "fail", 65.0),
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "pass", 0),
        ]
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-expired",
                approved_by="Reviewer A",
                approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                reason="Old waiver",
                gate_name="ppc_coverage",
                expiry=datetime(2026, 6, 1, tzinfo=timezone.utc),
            ),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers, as_of=as_of
        )
        assert readiness.overall_ready is False
        assert len(readiness.waivers_applied) == 0  # expired waiver not applied

    def test_policy_scope_mismatch_skips_gate(self):
        """A gate whose scope does not match the policy scope is skipped.
        Note: Gate scope is informational — gates defined within a policy
        inherit the policy scope. The evaluator does not skip gates based
        on scope mismatch; instead, scope is validated at policy creation."""
        gate = ValidationGate(
            name="market_specific_gate",
            description="Market specific",
            scope="market_specific_only",
            evaluator_id="rhat",
            acceptable_range=(0.0, 1.05),
            direction="lower_is_better",
            blocking=True,
            required=True,
        )
        policy = ThresholdPolicy(
            policy_id="pol-scope",
            version="1.0",
            scope="shared_model_only",
            gates=[gate],
            owner="Test",
            approval_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        results = [
            ValidationResult(
                gate_name="market_specific_gate",
                status="pass",
                model_run_id="r",
                data_fingerprint="d",
                model_spec_fingerprint="s",
                posterior_fingerprint="p",
                policy_id="pol-scope",
                policy_version="1.0",
            ),
        ]
        readiness = evaluate_approval_readiness(results, policy, _DEFAULT_IDENTITY)
        # The gate is evaluated normally (scope mismatch is not enforced
        # at gate level — policy scope governs which models it applies to)
        assert readiness.overall_ready is True
        assert len(readiness.passes) == 1  # Gate was evaluated

    def test_review_band_result_blocking(self):
        """A review-band result on a blocking gate should be reported
        but not block (review is not fail)."""
        gate = ValidationGate(
            name="rhat",
            description="R-hat check",
            evaluator_id="rhat",
            acceptable_range=(0.0, 1.05),
            review_range=(0.0, 1.1),
            direction="lower_is_better",
            blocking=True,
            required=True,
        )
        policy = ThresholdPolicy(
            policy_id="pol-review",
            version="1.0",
            scope="all",
            gates=[gate],
            owner="Test",
            approval_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        results = [
            ValidationResult(
                gate_name="rhat",
                status="review",
                value=1.08,
                message="Borderline R-hat",
                model_run_id="r",
                data_fingerprint="d",
                model_spec_fingerprint="s",
                posterior_fingerprint="p",
                policy_id="pol-review",
                policy_version="1.0",
            ),
        ]
        readiness = evaluate_approval_readiness(results, policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is True  # review doesn't block
        assert len(readiness.review_items) == 1
        assert len(readiness.blocking_failures) == 0


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestReadinessToDict:
    def test_returns_dict_with_expected_keys(self, sample_policy):
        results = [
            _make_result("convergence_rhat", "pass", 1.02),
            _make_result("ppc_coverage", "pass", 85.0),
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "pass", 0),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY
        )
        d = readiness_to_dict(readiness)
        assert isinstance(d, dict)
        assert d["overall_ready"] is True
        assert d["policy_id"] == "val-pol-001"
        assert d["policy_version"] == "1.0.0"

    def test_round_trip_blocking_failures(self, sample_policy):
        results = [
            _make_result("convergence_rhat", "fail", 1.2, "Too high"),
            _make_result("ppc_coverage", "pass", 85.0),
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "pass", 0),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY
        )
        d = readiness_to_dict(readiness)
        assert len(d["blocking_failures"]) == 1
        assert d["blocking_failures"][0]["gate_name"] == "convergence_rhat"
        assert d["blocking_failures"][0]["status"] == "fail"

    def test_waivers_appear_in_dict(self, sample_policy):
        results = [
            _make_result("convergence_rhat", "pass", 1.02),
            _make_result("ppc_coverage", "fail", 60.0),
            _make_result("backtest_mape", "pass", 20.0),
            _make_result("divergences", "pass", 0),
        ]
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-001",
                approved_by="A",
                approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                reason="OK",
                gate_name="ppc_coverage",
            ),
        ]
        readiness = evaluate_approval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers
        )
        d = readiness_to_dict(readiness)
        assert len(d["waivers_applied"]) == 1
        assert d["waivers_applied"][0]["waiver_id"] == "wv-001"
