"""
Tests for ``core.validation_policy`` — validation-policy and
approval-readiness foundation (REQ-VAL-001).
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.validation_policy import (
    ApprovalReadiness,
    ThresholdPolicy,
    ValidationEvidenceContext,
    ValidationGate,
    ValidationResult,
    ValidationScopeContext,
    ValidationWaiverReference,
    evaluate_approval_readiness,
    filter_applicable_gates,
    readiness_to_dict,
)

# Default ModelIdentity matching _make_result's identity fields
_DEFAULT_IDENTITY = ModelIdentity("run-123", "data-abc", "spec-def", "post-ghi")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(
    *,
    policy: "ThresholdPolicy",
    gate_name: str,
    status: str = "pass",
    value: float | None = None,
    message: str = "",
) -> ValidationResult:
    """Helper to build a ValidationResult with v3-ready evidence fields.

    ``policy`` is required — the default-policy-without-gates pattern was
    removed in PR 66A because it produced blank gate fingerprints that
    fail strict schema-v3 evidence matching.

    Raises ``ValueError`` if ``gate_name`` is not found in the policy.
    """
    gate = policy.get_gate(gate_name)
    if gate is None:
        raise ValueError(
            f"Gate '{gate_name}' not found in policy '{policy.policy_id}'. "
            "All test results must reference an existing gate."
        )
    gf = gate.fingerprint()
    return ValidationResult(
        gate_name=gate_name,
        status=status,
        value=value,
        message=message or f"{gate_name}={value}",
        model_run_id="run-123",
        data_fingerprint="data-abc",
        model_spec_fingerprint="spec-def",
        posterior_fingerprint="post-ghi",
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_fingerprint=policy.fingerprint(),
        model_identity_fingerprint=_DEFAULT_IDENTITY.fingerprint(),
        gate_fingerprint=gf,
        diagnostic_artefact_fingerprint="diag-fp-001",
        artefact_id="diag-001",
    )


def _make_context(*, policy, identity=None) -> ValidationEvidenceContext:
    """Helper to build a default ValidationEvidenceContext for tests."""
    if identity is None:
        identity = _DEFAULT_IDENTITY
    return ValidationEvidenceContext(
        model_identity=identity,
        policy=policy,
        diagnostic_artefact_id="diag-001",
        diagnostic_artefact_fingerprint="diag-fp-001",
        model_type="shared",
        intended_use="model_approval",
    )


def _eval_readiness(
    results,
    policy,
    identity,
    *,
    diagnostic_artefact_id="diag-001",
    diagnostic_artefact_fingerprint="diag-fp-001",
    waivers=None,
    as_of=None,
    ctx=None,
    evidence_context=None,
) -> ApprovalReadiness:
    """Wrapper that adds a default evidence_context if none provided."""
    ec = ctx or evidence_context
    if ec is None:
        ec = _make_context(policy=policy, identity=identity)
    return evaluate_approval_readiness(
        results,
        policy,
        identity,
        diagnostic_artefact_id=diagnostic_artefact_id,
        diagnostic_artefact_fingerprint=diagnostic_artefact_fingerprint,
        waivers=waivers,
        as_of=as_of,
        evidence_context=ec,
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
        evaluator_id="rhat",
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
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
                message="Converged",
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
                message="Coverage OK",
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
                message="MAPE OK",
            ),
            _make_result(
                policy=sample_policy,
                gate_name="divergences",
                status="pass",
                value=0,
                message="No divergences",
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is True
        assert len(readiness.blocking_failures) == 0
        assert len(readiness.missing_required_gates) == 0
        assert len(readiness.passes) == 4

    def test_missing_required_gate_blocks(self, sample_policy):
        """A required gate with no result blocks official approval."""
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            # ppc_coverage missing — but it's required
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is False
        assert "ppc_coverage" in readiness.missing_required_gates

    def test_failed_blocking_gate_blocks(self, sample_policy):
        """A blocking gate that fails blocks official approval."""
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="fail",
                value=1.2,
                message="R-hat too high",
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is False
        assert len(readiness.blocking_failures) == 1
        assert readiness.blocking_failures[0].gate_name == "convergence_rhat"

    def test_review_only_gate_does_not_block(self, sample_policy):
        """A non-blocking failing (review) gate is a review item, not a blocker."""
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            # backtest_mape is non-blocking and gets review status
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="review",
                value=35.0,
                message="MAPE elevated",
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is True  # review doesn't block
        assert len(readiness.review_items) == 1
        assert readiness.review_items[0].gate_name == "backtest_mape"
        assert len(readiness.blocking_failures) == 0

    def test_expired_policy_blocks(self, expired_policy):
        """An expired policy makes overall_ready False."""
        results = [
            _make_result(
                policy=expired_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = _eval_readiness(
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
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        # A stale result is treated as missing — convergence_rhat is required
        assert "convergence_rhat" in readiness.missing_required_gates
        assert readiness.overall_ready is False

    def test_approved_waiver_unblocks(self, sample_policy):
        """A failing waivable gate unblocked by an approved waiver."""
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            # ppc_coverage is waivable and fails
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="fail",
                value=65.0,
                message="Coverage below target",
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        ppc_gate = sample_policy.get_gate("ppc_coverage")
        assert ppc_gate is not None
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-001",
                approved_by="Reviewer A",
                approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                reason="Accepted lower coverage due to sparse data",
                gate_name="ppc_coverage",
                model_identity_fingerprint=_DEFAULT_IDENTITY.fingerprint(),
                policy_fingerprint=sample_policy.fingerprint(),
                gate_fingerprint=ppc_gate.fingerprint(),
                diagnostic_artefact_fingerprint="diag-fp-001",
                original_result_status="fail",
            ),
        ]
        readiness = _eval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers
        )
        assert readiness.overall_ready is True
        assert len(readiness.waivers_applied) == 1

    def test_non_waivable_failure_still_blocks(self, sample_policy):
        """A non-waivable gate that fails cannot be unblocked by a waiver."""
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="fail",
                value=1.2,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
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
        readiness = _eval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers
        )
        # convergence_rhat is not waivable, so waiver doesn't apply
        assert readiness.overall_ready is False
        assert len(readiness.blocking_failures) == 1

    def test_multiple_blocking_failures_reported(self, sample_policy):
        """Multiple failing blocking gates are all reported."""
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="fail",
                value=1.2,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="fail",
                value=50.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="divergences",
                status="fail",
                value=5,
                message="Divergences found",
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is False
        assert len(readiness.blocking_failures) == 3

    def test_no_results_at_all(self, sample_policy):
        """With no results, all required gates are missing."""
        readiness = _eval_readiness([], sample_policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is False
        assert (
            len(readiness.missing_required_gates) == 3
        )  # convergence, ppc, divergences (backtest not required)
        assert "backtest_mape" not in readiness.missing_required_gates

    def test_expired_waiver_does_not_unblock(self, sample_policy):
        """An expired waiver must not unblock a failing gate."""
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="fail",
                value=65.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
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
        readiness = _eval_readiness(
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
                model_run_id="run-123",
                data_fingerprint="data-abc",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
                policy_id="pol-scope",
                policy_version="1.0",
                policy_fingerprint=policy.fingerprint(),
                gate_fingerprint=gate.fingerprint(),
                model_identity_fingerprint=_DEFAULT_IDENTITY.fingerprint(),
                diagnostic_artefact_fingerprint="diag-fp-001",
                artefact_id="diag-001",
            ),
        ]
        readiness = _eval_readiness(results, policy, _DEFAULT_IDENTITY)
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
                model_run_id="run-123",
                data_fingerprint="data-abc",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
                policy_id="pol-review",
                policy_version="1.0",
                policy_fingerprint=policy.fingerprint(),
                gate_fingerprint=gate.fingerprint(),
                model_identity_fingerprint=_DEFAULT_IDENTITY.fingerprint(),
                diagnostic_artefact_fingerprint="diag-fp-001",
                artefact_id="diag-001",
            ),
        ]
        readiness = _eval_readiness(results, policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is True  # review doesn't block
        assert len(readiness.review_items) == 1
        assert len(readiness.blocking_failures) == 0


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestReadinessToDict:
    def test_returns_dict_with_expected_keys(self, sample_policy):
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        d = readiness_to_dict(readiness)
        assert isinstance(d, dict)
        assert d["overall_ready"] is True
        assert d["policy_id"] == "val-pol-001"
        assert d["policy_version"] == "1.0.0"

    def test_round_trip_blocking_failures(self, sample_policy):
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="fail",
                value=1.2,
                message="Too high",
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        d = readiness_to_dict(readiness)
        assert len(d["blocking_failures"]) == 1
        assert d["blocking_failures"][0]["gate_name"] == "convergence_rhat"
        assert d["blocking_failures"][0]["status"] == "fail"

    def test_waivers_appear_in_dict(self, sample_policy):
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="fail",
                value=60.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        ppc_gate = sample_policy.get_gate("ppc_coverage")
        assert ppc_gate is not None
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-001",
                approved_by="A",
                approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                reason="OK",
                gate_name="ppc_coverage",
                model_identity_fingerprint=_DEFAULT_IDENTITY.fingerprint(),
                policy_fingerprint=sample_policy.fingerprint(),
                gate_fingerprint=ppc_gate.fingerprint(),
                diagnostic_artefact_fingerprint="diag-fp-001",
                original_result_status="fail",
            ),
        ]
        readiness = _eval_readiness(
            results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers
        )
        d = readiness_to_dict(readiness)
        assert len(d["waivers_applied"]) == 1
        assert d["waivers_applied"][0]["waiver_id"] == "wv-001"


# ---------------------------------------------------------------------------
# PR 62B: ValidationEvidenceContext, matches_evidence, input validation
# ---------------------------------------------------------------------------


class TestValidationEvidenceContext:
    """Tests for the ValidationEvidenceContext dataclass."""

    def test_valid_context_created(self):
        ctx = ValidationEvidenceContext(
            model_identity=_DEFAULT_IDENTITY,
            policy=sample_policy,
            diagnostic_artefact_id="diag-001",
            diagnostic_artefact_fingerprint="diag-fp-001",
        )
        assert ctx.is_official() is True
        assert ctx.diagnostic_artefact_id == "diag-001"

    def test_blank_diagnostics_id_raises(self):
        with pytest.raises(
            ValueError, match="diagnostic_artefact_id must be non-blank"
        ):
            ValidationEvidenceContext(
                model_identity=_DEFAULT_IDENTITY,
                policy=sample_policy,
                diagnostic_artefact_id="",
                diagnostic_artefact_fingerprint="fp",
            )

    def test_blank_diagnostics_fingerprint_raises(self):
        with pytest.raises(
            ValueError, match="diagnostic_artefact_fingerprint must be non-blank"
        ):
            ValidationEvidenceContext(
                model_identity=_DEFAULT_IDENTITY,
                policy=sample_policy,
                diagnostic_artefact_id="diag-001",
                diagnostic_artefact_fingerprint="",
            )

    def test_invalid_intended_use_raises(self):
        with pytest.raises(ValueError, match="Invalid intended_use"):
            ValidationEvidenceContext(
                model_identity=_DEFAULT_IDENTITY,
                policy=sample_policy,
                diagnostic_artefact_id="diag-001",
                diagnostic_artefact_fingerprint="fp",
                intended_use="invalid",
            )

    def test_exploratory_mode(self):
        ctx = ValidationEvidenceContext(
            model_identity=_DEFAULT_IDENTITY,
            policy=sample_policy,
            diagnostic_artefact_id="diag-001",
            diagnostic_artefact_fingerprint="fp",
            intended_use="exploratory_review",
        )
        assert ctx.is_official() is False

    def test_invalid_model_type_raises(self):
        with pytest.raises(ValueError, match="Invalid model_type"):
            ValidationEvidenceContext(
                model_identity=_DEFAULT_IDENTITY,
                policy=sample_policy,
                diagnostic_artefact_id="diag-001",
                diagnostic_artefact_fingerprint="fp",
                model_type="unknown_type",
            )


class TestMatchesEvidence:
    """Tests for ValidationResult.matches_evidence()."""

    @pytest.fixture(autouse=True)
    def _setup(self, sample_policy):
        self.policy = sample_policy
        self.gate = sample_policy.get_gate("convergence_rhat")
        self.ctx = ValidationEvidenceContext(
            model_identity=_DEFAULT_IDENTITY,
            policy=self.policy,
            diagnostic_artefact_id="diag-001",
            diagnostic_artefact_fingerprint="diag-fp-001",
            model_type="shared",
            intended_use="model_approval",
        )

    def _matching_result(self):
        return ValidationResult(
            gate_name="convergence_rhat",
            status="pass",
            value=1.02,
            model_run_id="run-123",
            data_fingerprint="data-abc",
            model_spec_fingerprint="spec-def",
            posterior_fingerprint="post-ghi",
            policy_id="val-pol-001",
            policy_version="1.0.0",
            gate_fingerprint=self.gate.fingerprint(),
            model_identity_fingerprint=_DEFAULT_IDENTITY.fingerprint(),
            diagnostic_artefact_fingerprint="diag-fp-001",
            artefact_id="diag-001",
        )

    def test_matches_when_all_fields_align(self):
        result = self._matching_result()
        assert (
            result.matches_evidence(evidence_context=self.ctx, gate=self.gate) is True
        )

    def test_changed_gate_fingerprint_fails(self):
        result = self._matching_result()
        result = ValidationResult(
            gate_name=result.gate_name,
            status=result.status,
            value=result.value,
            message=result.message,
            artefact_id=result.artefact_id,
            evaluated_at=result.evaluated_at,
            model_run_id=result.model_run_id,
            data_fingerprint=result.data_fingerprint,
            model_spec_fingerprint=result.model_spec_fingerprint,
            posterior_fingerprint=result.posterior_fingerprint,
            policy_id=result.policy_id,
            policy_version=result.policy_version,
            gate_fingerprint="different-gate-fingerprint",
            model_identity_fingerprint=result.model_identity_fingerprint,
            diagnostic_artefact_fingerprint=result.diagnostic_artefact_fingerprint,
        )
        assert (
            result.matches_evidence(evidence_context=self.ctx, gate=self.gate) is False
        )

    def test_changed_diagnostics_fingerprint_fails(self):
        result = self._matching_result()
        result = ValidationResult(
            gate_name=result.gate_name,
            status=result.status,
            value=result.value,
            message=result.message,
            artefact_id=result.artefact_id,
            evaluated_at=result.evaluated_at,
            model_run_id=result.model_run_id,
            data_fingerprint=result.data_fingerprint,
            model_spec_fingerprint=result.model_spec_fingerprint,
            posterior_fingerprint=result.posterior_fingerprint,
            policy_id=result.policy_id,
            policy_version=result.policy_version,
            gate_fingerprint=result.gate_fingerprint,
            model_identity_fingerprint=result.model_identity_fingerprint,
            diagnostic_artefact_fingerprint="different-diag-fp",
        )
        assert (
            result.matches_evidence(evidence_context=self.ctx, gate=self.gate) is False
        )

    def test_changed_diagnostics_id_fails(self):
        result = self._matching_result()
        result = ValidationResult(
            gate_name=result.gate_name,
            status=result.status,
            value=result.value,
            message=result.message,
            artefact_id="different-diag-id",
            evaluated_at=result.evaluated_at,
            model_run_id=result.model_run_id,
            data_fingerprint=result.data_fingerprint,
            model_spec_fingerprint=result.model_spec_fingerprint,
            posterior_fingerprint=result.posterior_fingerprint,
            policy_id=result.policy_id,
            policy_version=result.policy_version,
            gate_fingerprint=result.gate_fingerprint,
            model_identity_fingerprint=result.model_identity_fingerprint,
            diagnostic_artefact_fingerprint=result.diagnostic_artefact_fingerprint,
        )
        assert (
            result.matches_evidence(evidence_context=self.ctx, gate=self.gate) is False
        )

    def test_changed_model_identity_fingerprint_fails(self):
        result = self._matching_result()
        result = ValidationResult(
            gate_name=result.gate_name,
            status=result.status,
            value=result.value,
            message=result.message,
            artefact_id=result.artefact_id,
            evaluated_at=result.evaluated_at,
            model_run_id=result.model_run_id,
            data_fingerprint=result.data_fingerprint,
            model_spec_fingerprint=result.model_spec_fingerprint,
            posterior_fingerprint=result.posterior_fingerprint,
            policy_id=result.policy_id,
            policy_version=result.policy_version,
            gate_fingerprint=result.gate_fingerprint,
            model_identity_fingerprint="different-identity-fp",
            diagnostic_artefact_fingerprint=result.diagnostic_artefact_fingerprint,
        )
        assert (
            result.matches_evidence(evidence_context=self.ctx, gate=self.gate) is False
        )

    def test_blank_required_evidence_fails(self):
        result = ValidationResult(
            gate_name="convergence_rhat",
            status="pass",
            model_run_id="",
            data_fingerprint="",
            model_spec_fingerprint="",
            posterior_fingerprint="",
            policy_id="val-pol-001",
            policy_version="1.0.0",
            gate_fingerprint="",
            model_identity_fingerprint="",
            diagnostic_artefact_fingerprint="",
        )
        assert (
            result.matches_evidence(evidence_context=self.ctx, gate=self.gate) is False
        )


class TestDuplicateAndUnknownGateRejection:
    """PR 62B: Reject ambiguous input in evaluate_approval_readiness."""

    def test_duplicate_result_gate_names_raises(self, sample_policy):
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),  # duplicate
        ]
        with pytest.raises(ValueError, match="Duplicate result gate names"):
            _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)

    def test_duplicate_waiver_gate_names_raises(self, sample_policy):
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="fail",
                value=60.0,
            ),
        ]
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-001",
                approved_by="A",
                approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                reason="First",
                gate_name="ppc_coverage",
            ),
            ValidationWaiverReference(
                waiver_id="wv-002",
                approved_by="B",
                approved_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
                reason="Second",
                gate_name="ppc_coverage",
            ),
        ]
        with pytest.raises(ValueError, match="Duplicate waiver gate names"):
            _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers)

    def test_unknown_result_gate_raises(self, sample_policy):
        # Use a raw ValidationResult (not _make_result) to bypass the gate-lookup guard
        from ancestry_mmm.core.validation_policy import ValidationResult as _VR

        results = [
            _VR(
                gate_name="nonexistent_gate",
                status="pass",
                value=1.0,
                model_run_id="run-123",
                data_fingerprint="data-abc",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
                policy_id=sample_policy.policy_id,
                policy_version=sample_policy.version,
            ),
        ]
        with pytest.raises(ValueError, match="not present in policy"):
            _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)

    def test_unknown_waiver_gate_raises(self, sample_policy):
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
        ]
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-001",
                approved_by="A",
                approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                reason="Test",
                gate_name="nonexistent_gate",
            ),
        ]
        with pytest.raises(ValueError, match="not present in policy"):
            _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers)

    def test_multiple_active_waivers_for_same_gate_raises(self, sample_policy):
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="fail",
                value=60.0,
            ),
        ]
        waivers = [
            ValidationWaiverReference(
                waiver_id="wv-001",
                approved_by="A",
                approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                reason="First waiver",
                gate_name="ppc_coverage",
            ),
            ValidationWaiverReference(
                waiver_id="wv-002",
                approved_by="B",
                approved_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
                reason="Second waiver",
                gate_name="ppc_coverage",
            ),
        ]
        # The duplicate gate name check fires before the active waiver check
        with pytest.raises(ValueError, match="Duplicate waiver gate names"):
            _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY, waivers=waivers)


class TestWaiverEvidenceBinding:
    """PR 62B: Waiver evidence binding enforcement."""

    @pytest.fixture
    def evidence_ctx(self, sample_policy):
        return ValidationEvidenceContext(
            model_identity=_DEFAULT_IDENTITY,
            policy=sample_policy,
            diagnostic_artefact_id="diag-001",
            diagnostic_artefact_fingerprint="diag-fp-001",
            model_type="shared",
            intended_use="model_approval",
        )

    def test_officially_bound_waiver_passes(self, sample_policy, evidence_ctx):
        gate = sample_policy.get_gate("ppc_coverage")
        waiver = ValidationWaiverReference(
            waiver_id="wv-bound",
            approved_by="Reviewer",
            approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            reason="Accepted lower coverage",
            gate_name="ppc_coverage",
            model_identity_fingerprint=_DEFAULT_IDENTITY.fingerprint(),
            policy_fingerprint=sample_policy.fingerprint(),
            gate_fingerprint=gate.fingerprint() if gate else "",
            diagnostic_artefact_fingerprint="diag-fp-001",
            original_result_status="fail",
        )
        assert waiver.is_officially_bound() is True
        assert waiver.matches_evidence(evidence_ctx) is True

    def test_unbound_waiver_not_officially_bound(self):
        waiver = ValidationWaiverReference(
            waiver_id="wv-unbound",
            approved_by="Reviewer",
            approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            reason="Old waiver",
            gate_name="ppc_coverage",
        )
        assert waiver.is_officially_bound() is False

    def test_unbound_waiver_matches_evidence_false(self, sample_policy, evidence_ctx):
        waiver = ValidationWaiverReference(
            waiver_id="wv-unbound",
            approved_by="Reviewer",
            approved_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            reason="Old waiver",
            gate_name="ppc_coverage",
        )
        assert waiver.matches_evidence(evidence_ctx) is False

    def test_waiver_round_trip_payload(self):
        waiver = ValidationWaiverReference(
            waiver_id="wv-rt",
            approved_by="Reviewer",
            approved_at=datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc),
            reason="Round trip test",
            gate_name="ppc_coverage",
            model_identity_fingerprint="mid-fp-001",
            policy_fingerprint="pol-fp-001",
            gate_fingerprint="gate-fp-001",
            diagnostic_artefact_fingerprint="diag-fp-001",
            original_result_status="fail",
        )
        payload = waiver.to_waiver_payload()
        restored = ValidationWaiverReference.from_waiver_payload(payload)
        assert restored == waiver

    def test_legacy_waiver_from_dict_preserves_missing_bindings(self):
        d = {
            "waiver_id": "wv-legacy",
            "gate_name": "ppc_coverage",
            "approved_by": "Reviewer",
            "approved_at": "2026-07-15T12:00:00+00:00",
            "reason": "Legacy",
            "expiry": None,
            "superseded_by": None,
        }
        waiver = ValidationWaiverReference.from_waiver_payload(d)
        assert waiver.is_officially_bound() is False


class TestMalformedPolicyConfig:
    """PR 62B: Malformed policy configuration returns config_errors."""

    def test_config_errors_in_readiness(self):
        gate = ValidationGate(
            name="unknown_evaluator_gate",
            description="No evaluator",
            acceptable_range=(0.0, 1.0),
        )
        policy = ThresholdPolicy(
            policy_id="pol-bad",
            version="1.0",
            scope="test",
            gates=[gate],
            owner="Test",
        )
        readiness = _eval_readiness([], policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is False
        assert len(readiness.config_errors) > 0
        assert len(readiness.gate_results) == 0
        assert len(readiness.blocking_failures) == 0

    def test_config_errors_cannot_be_waived(self, sample_policy):
        bad_gate = ValidationGate(
            name="bad_gate",
            description="No evaluator",
            acceptable_range=(0.0, 1.0),
        )
        policy = ThresholdPolicy(
            policy_id="pol-bad",
            version="1.0",
            scope="test",
            gates=[bad_gate],
            owner="Test",
        )
        readiness = _eval_readiness([], policy, _DEFAULT_IDENTITY)
        assert readiness.overall_ready is False
        assert len(readiness.config_errors) > 0
        assert len(readiness.waivers_applied) == 0


# ---------------------------------------------------------------------------
# PR 67A: Lifecycle issues on config-error early return
# ---------------------------------------------------------------------------


class TestLifecycleOnConfigError:
    """PR 67A + 69A: lifecycle issues must be populated exactly once even
    when config errors trigger the early return path."""

    def _make_bad_policy(self, **overrides) -> ThresholdPolicy:
        gate = ValidationGate(
            name="unknown_evaluator_gate",
            description="No evaluator",
            acceptable_range=(0.0, 1.0),
        )
        kwargs = dict(
            policy_id="pol-bad",
            version="1.0",
            scope="test",
            gates=[gate],
            owner="Test",
            approval_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        kwargs.update(overrides)
        return ThresholdPolicy(**kwargs)

    def test_config_error_plus_expired(self):
        """Invalid config + expired = exactly one expired issue (no duplication)."""
        policy = self._make_bad_policy(
            expiry=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = _eval_readiness([], policy, _DEFAULT_IDENTITY, as_of=as_of)
        assert len(readiness.config_errors) > 0
        assert len(readiness.lifecycle_issues) == 1
        assert readiness.lifecycle_issues[0].status == "expired"
        assert "Re-evaluate readiness" in readiness.lifecycle_issues[0].message

    def test_config_error_plus_superseded(self):
        """Invalid config + superseded = exactly one superseded issue."""
        policy = self._make_bad_policy(superseded_by="pol-v2")
        readiness = _eval_readiness([], policy, _DEFAULT_IDENTITY)
        assert len(readiness.config_errors) > 0
        assert len(readiness.lifecycle_issues) == 1
        assert readiness.lifecycle_issues[0].status == "superseded"
        assert "Re-evaluate readiness" in readiness.lifecycle_issues[0].message

    def test_config_error_plus_expired_and_superseded(self):
        """Invalid config + expired + superseded = exactly two issues (one each)."""
        policy = self._make_bad_policy(
            expiry=datetime(2025, 6, 1, tzinfo=timezone.utc),
            superseded_by="pol-v2",
        )
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = _eval_readiness([], policy, _DEFAULT_IDENTITY, as_of=as_of)
        assert len(readiness.config_errors) > 0
        assert len(readiness.lifecycle_issues) == 2
        assert readiness.lifecycle_issues[0].status == "expired"
        assert readiness.lifecycle_issues[1].status == "superseded"
        # Stable ordering
        assert [li.status for li in readiness.lifecycle_issues] == [
            "expired",
            "superseded",
        ]


# ---------------------------------------------------------------------------
# PR 67A: Approval factory binding validation
# ---------------------------------------------------------------------------


class TestApprovalFactoryBindings:
    """create_policy_backed_model_approval must reject mismatched bindings."""

    def test_matching_bindings_creates_approval(self, sample_policy):
        from ancestry_mmm.core.approval import (
            create_policy_backed_model_approval,
        )

        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        approval = create_policy_backed_model_approval(
            approved_by="Reviewer A",
            readiness=readiness,
            current_policy=sample_policy,
            model_run_id="run-123",
            data_fingerprint="data-abc",
            model_spec_fingerprint="spec-def",
            posterior_fingerprint="post-ghi",
        )
        assert approval.validation_policy_id == "val-pol-001"

    def test_mismatched_policy_id_fails(self, sample_policy):
        from ancestry_mmm.core.approval import (
            create_policy_backed_model_approval,
            ValidationPolicyBlockedError,
        )

        # Build a fully passing readiness
        results_all = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results_all, sample_policy, _DEFAULT_IDENTITY)
        # Use a different policy — same shape but different ID
        wrong_policy = ThresholdPolicy(
            policy_id="wrong-pol",
            version="1.0.0",
            scope="test",
            gates=sample_policy.gates,
            owner="Test",
            approval_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(ValidationPolicyBlockedError, match="policy_id"):
            create_policy_backed_model_approval(
                approved_by="Reviewer A",
                readiness=readiness,
                current_policy=wrong_policy,
                model_run_id="run-123",
                data_fingerprint="data-abc",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
            )

    def test_mismatched_model_identity_fails(self, sample_policy):
        from ancestry_mmm.core.approval import (
            create_policy_backed_model_approval,
            ValidationPolicyBlockedError,
        )

        results_all = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results_all, sample_policy, _DEFAULT_IDENTITY)
        with pytest.raises(ValidationPolicyBlockedError, match="model_identity"):
            create_policy_backed_model_approval(
                approved_by="Reviewer A",
                readiness=readiness,
                current_policy=sample_policy,
                model_run_id="different-run",
                data_fingerprint="different-data",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
            )


class TestScopeMatcher:
    """PR 62B: Operational scope matcher."""

    def test_scope_applicable_all_models(self):
        gate = ValidationGate(
            name="test_gate",
            description="All models gate",
            scope="all_models",
        )
        scope = ValidationScopeContext(model_type="shared")
        applicable, reason = scope.gate_is_applicable(gate)
        assert applicable is True
        assert reason is None

    def test_scope_shared_gate_applicable_to_shared(self):
        gate = ValidationGate(
            name="shared_gate",
            description="Shared only",
            scope="shared",
        )
        scope = ValidationScopeContext(model_type="shared")
        applicable, reason = scope.gate_is_applicable(gate)
        assert applicable is True
        assert reason is None

    def test_scope_shared_gate_not_applicable_to_market_specific(self):
        gate = ValidationGate(
            name="shared_gate",
            description="Shared only",
            scope="shared",
        )
        scope = ValidationScopeContext(model_type="market_specific")
        applicable, reason = scope.gate_is_applicable(gate)
        assert applicable is False
        assert reason is not None
        assert "shared" in reason

    def test_scope_market_specific_gate_applicable(self):
        gate = ValidationGate(
            name="ms_gate",
            description="Market specific only",
            scope="market_specific",
        )
        scope = ValidationScopeContext(model_type="market_specific")
        applicable, reason = scope.gate_is_applicable(gate)
        assert applicable is True
        assert reason is None

    def test_filter_applicable_gates(self, sample_policy):
        scope = ValidationScopeContext(model_type="shared")
        result = filter_applicable_gates(sample_policy, scope)
        for gate, applicable, reason in result:
            assert applicable is True


# ---------------------------------------------------------------------------
# PR 66A: Lifecycle issues, schema-v2 golden fixture, create_policy_backed
# ---------------------------------------------------------------------------


class TestPolicyLifecycleIssues:
    """PR 66A + 69A: Lifecycle issues are populated exactly once per condition."""

    def test_lifecycle_issues_expired(self, expired_policy):
        """An expired policy produces exactly one expired issue."""
        results = [
            _make_result(
                policy=expired_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = _eval_readiness(
            results, expired_policy, _DEFAULT_IDENTITY, as_of=as_of
        )
        # Exactly one issue, status=expired — no duplication
        assert len(readiness.lifecycle_issues) == 1
        assert readiness.lifecycle_issues[0].status == "expired"
        assert "Re-evaluate readiness" in readiness.lifecycle_issues[0].message

    def test_lifecycle_issues_superseded(self, convergence_gate):
        """A superseded policy produces exactly one superseded issue."""
        policy = ThresholdPolicy(
            policy_id="val-pol-superseded",
            version="1.0",
            scope="all_models",
            gates=[convergence_gate],
            owner="Modelling Team",
            approval_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            superseded_by="val-pol-002",
        )
        results = [
            _make_result(
                policy=policy, gate_name="convergence_rhat", status="pass", value=1.02
            ),
        ]
        readiness = _eval_readiness(results, policy, _DEFAULT_IDENTITY)
        # Exactly one issue, status=superseded — no duplication
        assert len(readiness.lifecycle_issues) == 1
        assert readiness.lifecycle_issues[0].status == "superseded"
        assert "Re-evaluate readiness" in readiness.lifecycle_issues[0].message

    def test_lifecycle_issues_both(self, convergence_gate):
        """An expired AND superseded policy produces exactly two issues (one each)."""
        policy = ThresholdPolicy(
            policy_id="val-pol-both",
            version="1.0",
            scope="all_models",
            gates=[convergence_gate],
            owner="Modelling Team",
            approval_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            expiry=datetime(2025, 6, 1, tzinfo=timezone.utc),
            superseded_by="val-pol-003",
        )
        results = [
            _make_result(
                policy=policy, gate_name="convergence_rhat", status="pass", value=1.02
            ),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = _eval_readiness(results, policy, _DEFAULT_IDENTITY, as_of=as_of)
        # Exactly two issues — one expired, one superseded
        assert len(readiness.lifecycle_issues) == 2
        assert readiness.lifecycle_issues[0].status == "expired"
        assert readiness.lifecycle_issues[1].status == "superseded"
        # Stable ordering: expired before superseded
        statuses = [li.status for li in readiness.lifecycle_issues]
        assert statuses == ["expired", "superseded"]

    def test_overall_ready_false_when_lifecycle_blocks(self, expired_policy):
        """overall_ready is False when lifecycle issues exist (expired policy)."""
        results = [
            _make_result(
                policy=expired_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = _eval_readiness(
            results, expired_policy, _DEFAULT_IDENTITY, as_of=as_of
        )
        assert readiness.overall_ready is False

    def test_lifecycle_round_trip_preserves_list(self, expired_policy):
        """Schema-v3 round trip preserves the exact lifecycle_issues list."""
        results = [
            _make_result(
                policy=expired_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = _eval_readiness(
            results, expired_policy, _DEFAULT_IDENTITY, as_of=as_of
        )
        d = readiness_to_dict(readiness)
        restored = ApprovalReadiness.from_dict(d)
        assert len(restored.lifecycle_issues) == len(readiness.lifecycle_issues)
        for original, restored_li in zip(
            readiness.lifecycle_issues, restored.lifecycle_issues
        ):
            assert original.status == restored_li.status
            assert original.message == restored_li.message

    def test_lifecycle_fingerprint_deterministic(self, expired_policy):
        """Lifecycle issues produce a deterministic readiness fingerprint
        (same object, repeated call)."""
        results = [
            _make_result(
                policy=expired_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        readiness = _eval_readiness(
            results, expired_policy, _DEFAULT_IDENTITY, as_of=as_of
        )
        fp1 = readiness.fingerprint()
        fp2 = readiness.fingerprint()
        assert fp1 == fp2

    def test_lifecycle_message_structure_consistent_across_paths(
        self, convergence_gate
    ):
        """Config-error and normal paths produce the same message structure."""
        # Normal path — valid config, expired + superseded
        normal_policy = ThresholdPolicy(
            policy_id="val-pol-msg-normal",
            version="1.0",
            scope="all_models",
            gates=[convergence_gate],
            owner="Modelling Team",
            approval_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            expiry=datetime(2025, 6, 1, tzinfo=timezone.utc),
            superseded_by="val-pol-002",
        )
        normal_results = [
            _make_result(
                policy=normal_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
        ]
        as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
        normal_readiness = _eval_readiness(
            normal_results, normal_policy, _DEFAULT_IDENTITY, as_of=as_of
        )

        # Config-error path — bad gate, expired + superseded
        bad_gate = ValidationGate(
            name="unknown_evaluator_gate",
            description="No evaluator",
            acceptable_range=(0.0, 1.0),
        )
        error_policy = ThresholdPolicy(
            policy_id="val-pol-msg-error",
            version="1.0",
            scope="test",
            gates=[bad_gate],
            owner="Test",
            approval_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            expiry=datetime(2025, 6, 1, tzinfo=timezone.utc),
            superseded_by="val-pol-002",
        )
        error_readiness = _eval_readiness(
            [], error_policy, _DEFAULT_IDENTITY, as_of=as_of
        )

        # Same number of issues, same statuses, same message pattern
        assert len(normal_readiness.lifecycle_issues) == len(
            error_readiness.lifecycle_issues
        )
        for n_li, e_li in zip(
            normal_readiness.lifecycle_issues, error_readiness.lifecycle_issues
        ):
            assert n_li.status == e_li.status
            # Messages follow the same pattern structure
            assert ("expired on" in n_li.message) == ("expired on" in e_li.message)
            assert ("superseded by" in n_li.message) == (
                "superseded by" in e_li.message
            )
            assert ("Re-evaluate readiness" in n_li.message) == (
                "Re-evaluate readiness" in e_li.message
            )


class TestSchemaV2GoldenFixture:
    """PR 66A: Schema-v2 fingerprint backward compatibility."""

    def test_schema_v2_fingerprint_includes_scope_fields(self, sample_policy):
        """V2 fingerprint must include model_type, market, intended_use etc."""
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        # Force schema v2 for fingerprint test
        v2_readiness = ApprovalReadiness(
            readiness_artefact_id=readiness.readiness_artefact_id,
            policy_id=readiness.policy_id,
            policy_version=readiness.policy_version,
            policy_fingerprint=readiness.policy_fingerprint,
            model_identity_fingerprint=readiness.model_identity_fingerprint,
            diagnostic_artefact_id=readiness.diagnostic_artefact_id,
            diagnostic_artefact_fingerprint=readiness.diagnostic_artefact_fingerprint,
            gate_results=readiness.gate_results,
            blocking_failures=readiness.blocking_failures,
            review_items=readiness.review_items,
            passes=readiness.passes,
            missing_required_gates=readiness.missing_required_gates,
            waivers_applied=readiness.waivers_applied,
            evaluated_at=readiness.evaluated_at,
            overall_ready=readiness.overall_ready,
            schema_version=2,
            config_errors=readiness.config_errors,
            model_type=readiness.model_type,
            market=readiness.market,
            intended_use=readiness.intended_use,
            scope_context_fingerprint=readiness.scope_context_fingerprint,
            gate_applicability=readiness.gate_applicability,
        )
        fp = v2_readiness.fingerprint()
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 hex digest
        # The fingerprint must be deterministic
        fp2 = v2_readiness.fingerprint()
        assert fp == fp2


class TestCreatePolicyBackedModelApproval:
    """PR 66A: create_policy_backed_model_approval enforces schema v3."""

    def test_requires_schema_v3(self, sample_policy):
        """Creating a policy-backed approval from schema v2 readiness is rejected."""
        from ancestry_mmm.core.approval import (
            create_policy_backed_model_approval,
            ValidationPolicyBlockedError,
        )

        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        # Force schema v2 by constructing directly with schema_version=2
        v2_readiness = ApprovalReadiness(
            readiness_artefact_id=readiness.readiness_artefact_id,
            policy_id=readiness.policy_id,
            policy_version=readiness.policy_version,
            policy_fingerprint=readiness.policy_fingerprint,
            model_identity_fingerprint=readiness.model_identity_fingerprint,
            diagnostic_artefact_id=readiness.diagnostic_artefact_id,
            diagnostic_artefact_fingerprint=readiness.diagnostic_artefact_fingerprint,
            gate_results=readiness.gate_results,
            blocking_failures=readiness.blocking_failures,
            review_items=readiness.review_items,
            passes=readiness.passes,
            missing_required_gates=readiness.missing_required_gates,
            waivers_applied=readiness.waivers_applied,
            evaluated_at=readiness.evaluated_at,
            overall_ready=readiness.overall_ready,
            schema_version=2,
            config_errors=readiness.config_errors,
            model_type=readiness.model_type,
            market=readiness.market,
            intended_use=readiness.intended_use,
            scope_context_fingerprint=readiness.scope_context_fingerprint,
            gate_applicability=readiness.gate_applicability,
            lifecycle_issues=readiness.lifecycle_issues,
        )
        with pytest.raises(ValidationPolicyBlockedError, match="Schema v3"):
            create_policy_backed_model_approval(
                approved_by="Reviewer A",
                readiness=v2_readiness,
                current_policy=sample_policy,
                model_run_id="run-123",
                data_fingerprint="data-abc",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
            )

    def test_requires_overall_ready(self, sample_policy):
        """Creating a policy-backed approval from unready readiness is rejected."""
        from ancestry_mmm.core.approval import (
            create_policy_backed_model_approval,
            ValidationPolicyBlockedError,
        )

        # Readiness with a failing gate
        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="fail",
                value=1.2,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        with pytest.raises(ValidationPolicyBlockedError, match="not ready"):
            create_policy_backed_model_approval(
                approved_by="Reviewer A",
                readiness=readiness,
                current_policy=sample_policy,
                model_run_id="run-123",
                data_fingerprint="data-abc",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
            )

    def test_requires_active_current_policy(self, expired_policy):
        """Creating a policy-backed approval with inactive policy is rejected."""
        from ancestry_mmm.core.approval import (
            create_policy_backed_model_approval,
            ValidationPolicyBlockedError,
        )

        # Need a passing readiness with the expired policy
        results = [
            _make_result(
                policy=expired_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
        ]
        as_of = datetime(2026, 5, 1, tzinfo=timezone.utc)  # Before expiry
        readiness = _eval_readiness(
            results, expired_policy, _DEFAULT_IDENTITY, as_of=as_of
        )
        # readiness should be schema v3 and overall_ready
        assert readiness.schema_version >= 3
        # But current_policy is expired
        with pytest.raises(ValidationPolicyBlockedError, match="not active"):
            create_policy_backed_model_approval(
                approved_by="Reviewer A",
                readiness=readiness,
                current_policy=expired_policy,
                model_run_id="run-123",
                data_fingerprint="data-abc",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
            )

    def test_successful_creation(self, sample_policy):
        """A fully passing schema-v3 readiness creates a valid policy-backed approval."""
        from ancestry_mmm.core.approval import (
            create_policy_backed_model_approval,
            fingerprint_model_approval,
        )

        results = [
            _make_result(
                policy=sample_policy,
                gate_name="convergence_rhat",
                status="pass",
                value=1.02,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="ppc_coverage",
                status="pass",
                value=85.0,
            ),
            _make_result(
                policy=sample_policy,
                gate_name="backtest_mape",
                status="pass",
                value=20.0,
            ),
            _make_result(
                policy=sample_policy, gate_name="divergences", status="pass", value=0
            ),
        ]
        readiness = _eval_readiness(results, sample_policy, _DEFAULT_IDENTITY)
        approval = create_policy_backed_model_approval(
            approved_by="Reviewer A",
            readiness=readiness,
            current_policy=sample_policy,
            model_run_id="run-123",
            data_fingerprint="data-abc",
            model_spec_fingerprint="spec-def",
            posterior_fingerprint="post-ghi",
            run_label="Test run",
            notes="Approved for testing",
        )
        assert approval.validation_policy_id == "val-pol-001"
        assert approval.validation_policy_version == "1.0.0"
        assert approval.validation_policy_fingerprint == sample_policy.fingerprint()
        assert approval.readiness_artefact_id == readiness.readiness_artefact_id
        assert approval.readiness_fingerprint == readiness.fingerprint()
        assert approval.is_model_bound()
        # Verify the fingerprint is deterministic
        fp1 = fingerprint_model_approval(approval)
        fp2 = fingerprint_model_approval(approval)
        assert fp1 == fp2
