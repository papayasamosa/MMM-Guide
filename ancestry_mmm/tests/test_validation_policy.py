"""
Tests for ``core.validation_policy`` — validation-policy and
approval-readiness foundation (REQ-VAL-001).
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest

from ancestry_mmm.core.validation_policy import (
    ApprovalReadiness,
    ThresholdPolicy,
    ValidationGate,
    ValidationResult,
    ValidationWaiverReference,
    evaluate_approval_readiness,
    readiness_to_dict,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def convergence_gate() -> ValidationGate:
    return ValidationGate(
        name="convergence_rhat",
        description="All R-hat values must be below 1.05",
        scope="all_models",
        acceptable_range=(0.0, 1.05),
        blocking=True,
        waivable=False,
        required=True,
    )


@pytest.fixture
def ppc_gate() -> ValidationGate:
    return ValidationGate(
        name="ppc_coverage",
        description="Posterior predictive coverage within expected range",
        scope="all_models",
        acceptable_range=(70.0, 100.0),
        blocking=True,
        waivable=True,
        required=True,
    )


@pytest.fixture
def backtest_gate() -> ValidationGate:
    return ValidationGate(
        name="backtest_mape",
        description="Backtest MAPE within acceptable range",
        scope="all_models",
        acceptable_range=(0.0, 30.0),
        blocking=False,
        waivable=True,
        required=False,
    )


@pytest.fixture
def divergence_gate() -> ValidationGate:
    return ValidationGate(
        name="divergences",
        description="No divergences in sampling",
        scope="all_models",
        acceptable_range=None,
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
        policy = ThresholdPolicy(policy_id="p1", version="1.0", scope="test")
        assert policy.policy_id == "p1"
        assert policy.version == "1.0"
        assert policy.scope == "test"
        assert policy.gates == []
        assert policy.owner == ""

    def test_version_is_string(self):
        policy = ThresholdPolicy(policy_id="p1", version="1.0.0", scope="test")
        assert isinstance(policy.version, str)

    def test_is_expired_with_no_expiry(self):
        policy = ThresholdPolicy(policy_id="p1", version="1.0", scope="test")
        assert not policy.is_expired()

    def test_is_expired_when_past_expiry(self):
        past = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert expired_policy().is_expired(as_of=datetime(2026, 7, 1, tzinfo=timezone.utc))

    def test_is_expired_when_before_expiry(self):
        policy = expired_policy()
        assert not policy.is_expired(as_of=datetime(2026, 5, 1, tzinfo=timezone.utc))

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
            name="test_gate", description="A test gate", scope="all_models",
            blocking=True, required=True,
        )
        assert gate.scope == "all_models"
        assert gate.blocking is True
        assert gate.required is True

    def test_gate_with_waiver_creates_reference(self):
        gate = ValidationGate(
            name="waivable_gate", description="A waivable gate",
            blocking=True, waivable=True, required=True,
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
            name="rhat", description="R-hat check",
            acceptable_range=(0.0, 1.05), blocking=True, required=True,
        )
        assert gate.acceptable_range == (0.0, 1.05)


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_passing_result(self):
        r = ValidationResult(gate_name="test", passed=True, message="OK")
        assert r.passed is True
        assert r.value is None

    def test_failing_result_with_value(self):
        r = ValidationResult(
            gate_name="rhat", passed=False, value=1.2,
            message="Max R-hat is 1.2, exceeds 1.05",
        )
        assert r.passed is False
        assert r.value == 1.2

    def test_is_stale(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        r = ValidationResult(
            gate_name="test", passed=True, evaluated_at=old,
        )
        assert r.is_stale(max_age_days=1)

    def test_is_not_stale_when_recent(self):
        r = ValidationResult(gate_name="test", passed=True)
        assert not r.is_stale(max_age_days=365)


# ---------------------------------------------------------------------------
# ApprovalReadiness evaluation
# ---------------------------------------------------------------------------


class TestApprovalReadinessEvaluation:
    """Core behaviour tests for evaluate_approval_readiness."""

    def test_matching_successful_readiness_passes(self, sample_policy):
        """All required gates pass -> overall_ready is True."""
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=True, value=1.02, message="Converged"),
            ValidationResult(gate_name="ppc_coverage", passed=True, value=85.0, message="Coverage OK"),
            ValidationResult(gate_name="backtest_mape", passed=True, value=20.0, message="MAPE OK"),
            ValidationResult(gate_name="divergences", passed=True, value=0, message="No divergences"),
        ]
        readiness = evaluate_approval_readiness(results, sample_policy)
        assert readiness.overall_ready is True
        assert len(readiness.blocking_failures) == 0
        assert len(readiness.missing_required_gates) == 0
        assert len(readiness.passes) == 4

    def test_missing_required_gate_blocks(self, sample_policy):
        """A required gate with no result blocks official approval."""
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=True, value=1.02),
            # ppc_coverage missing — but it's required
            ValidationResult(gate_name="backtest_mape", passed=True, value=20.0),
            ValidationResult(gate_name="divergences", passed=True, value=0),
        ]
        readiness = evaluate_approval_readiness(results, sample_policy)
        assert readiness.overall_ready is False
        assert "ppc_coverage" in readiness.missing_required_gates

    def test_failed_blocking_gate_blocks(self, sample_policy):
        """A blocking gate that fails blocks official approval."""
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=False, value=1.2, message="R-hat too high"),
            ValidationResult(gate_name="ppc_coverage", passed=True, value=85.0),
            ValidationResult(gate_name="backtest_mape", passed=True, value=20.0),
            ValidationResult(gate_name="divergences", passed=True, value=0),
        ]
        readiness = evaluate_approval_readiness(results, sample_policy)
        assert readiness.overall_ready is False
        assert len(readiness.blocking_failures) == 1
        assert readiness.blocking_failures[0].gate_name == "convergence_rhat"

    def test_review_only_gate_does_not_block(self, sample_policy):
        """A non-blocking failing gate is a review item, not a blocker."""
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=True, value=1.02),
            ValidationResult(gate_name="ppc_coverage", passed=True, value=85.0),
            # backtest_mape is non-blocking and fails
            ValidationResult(gate_name="backtest_mape", passed=False, value=35.0, message="MAPE above threshold"),
            ValidationResult(gate_name="divergences", passed=True, value=0),
        ]
        readiness = evaluate_approval_readiness(results, sample_policy)
        assert readiness.overall_ready is True  # non-blocking failure doesn't block
        assert len(readiness.review_items) == 1
        assert readiness.review_items[0].gate_name == "backtest_mape"
        assert len(readiness.blocking_failures) == 0

    def test_expired_policy_blocks(self, expired_policy):
        """An expired policy makes overall_ready False."""
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=True, value=1.02),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = evaluate_approval_readiness(results, expired_policy, as_of=as_of)
        assert readiness.overall_ready is False

    def test_stale_validation_artefact_blocks(self, sample_policy):
        """A validation result that is stale causes the corresponding
        required gate to count as missing, blocking approval."""
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=False, evaluated_at=old),
            ValidationResult(gate_name="ppc_coverage", passed=True),
            ValidationResult(gate_name="backtest_mape", passed=True),
            ValidationResult(gate_name="divergences", passed=True),
        ]
        readiness = evaluate_approval_readiness(results, sample_policy)
        # The stale convergence_rhat result fails and is blocking
        assert readiness.overall_ready is False

    def test_approved_waiver_unblocks(self, sample_policy):
        """A failing waivable gate unblocked by an approved waiver."""
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=True, value=1.02),
            # ppc_coverage is waivable and fails
            ValidationResult(gate_name="ppc_coverage", passed=False, value=65.0, message="Coverage below target"),
            ValidationResult(gate_name="backtest_mape", passed=True, value=20.0),
            ValidationResult(gate_name="divergences", passed=True, value=0),
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
        readiness = evaluate_approval_readiness(results, sample_policy, waivers=waivers)
        assert readiness.overall_ready is True
        assert len(readiness.waivers_applied) == 1

    def test_non_waivable_failure_still_blocks(self, sample_policy):
        """A non-waivable gate that fails cannot be unblocked by a waiver."""
        results = [
            # convergence_rhat is not waivable and fails
            ValidationResult(gate_name="convergence_rhat", passed=False, value=1.2),
            ValidationResult(gate_name="ppc_coverage", passed=True, value=85.0),
            ValidationResult(gate_name="backtest_mape", passed=True, value=20.0),
            ValidationResult(gate_name="divergences", passed=True, value=0),
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
        readiness = evaluate_approval_readiness(results, sample_policy, waivers=waivers)
        # convergence_rhat is not waivable, so waiver doesn't apply
        assert readiness.overall_ready is False
        assert len(readiness.blocking_failures) == 1

    def test_multiple_blocking_failures_reported(self, sample_policy):
        """Multiple failing blocking gates are all reported."""
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=False, value=1.2),
            ValidationResult(gate_name="ppc_coverage", passed=False, value=50.0),
            ValidationResult(gate_name="backtest_mape", passed=True, value=20.0),
            ValidationResult(gate_name="divergences", passed=False, value=5, message="Divergences found"),
        ]
        readiness = evaluate_approval_readiness(results, sample_policy)
        assert readiness.overall_ready is False
        # convergence_rhat, ppc_coverage, and divergences are all blocking
        assert len(readiness.blocking_failures) == 3

    def test_no_results_at_all(self, sample_policy):
        """With no results, all required gates are missing."""
        readiness = evaluate_approval_readiness([], sample_policy)
        assert readiness.overall_ready is False
        assert len(readiness.missing_required_gates) == 3  # convergence, ppc, divergences (backtest not required)
        assert "backtest_mape" not in readiness.missing_required_gates


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestReadinessToDict:
    def test_returns_dict_with_expected_keys(self, sample_policy):
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=True, value=1.02),
            ValidationResult(gate_name="ppc_coverage", passed=True, value=85.0),
            ValidationResult(gate_name="backtest_mape", passed=True, value=20.0),
            ValidationResult(gate_name="divergences", passed=True, value=0),
        ]
        readiness = evaluate_approval_readiness(results, sample_policy)
        d = readiness_to_dict(readiness)
        assert isinstance(d, dict)
        assert d["overall_ready"] is True
        assert d["policy_id"] == "val-pol-001"
        assert d["policy_version"] == "1.0.0"

    def test_round_trip_blocking_failures(self, sample_policy):
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=False, value=1.2, message="Too high"),
            ValidationResult(gate_name="ppc_coverage", passed=True, value=85.0),
            ValidationResult(gate_name="backtest_mape", passed=True, value=20.0),
            ValidationResult(gate_name="divergences", passed=True, value=0),
        ]
        readiness = evaluate_approval_readiness(results, sample_policy)
        d = readiness_to_dict(readiness)
        assert len(d["blocking_failures"]) == 1
        assert d["blocking_failures"][0]["gate_name"] == "convergence_rhat"

    def test_waivers_appear_in_dict(self, sample_policy):
        results = [
            ValidationResult(gate_name="convergence_rhat", passed=True, value=1.02),
            ValidationResult(gate_name="ppc_coverage", passed=False, value=60.0),
            ValidationResult(gate_name="backtest_mape", passed=True, value=20.0),
            ValidationResult(gate_name="divergences", passed=True, value=0),
        ]
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-001", approved_by="A",
                approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                reason="OK", gate_name="ppc_coverage",
            ),
        ]
        readiness = evaluate_approval_readiness(results, sample_policy, waivers=waivers)
        d = readiness_to_dict(readiness)
        assert len(d["waivers_applied"]) == 1
        assert d["waivers_applied"][0]["waiver_id"] == "wv-001"
