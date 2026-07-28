import time

import pytest

from ancestry_mmm.core.approval import (
    ApprovalMismatchError,
    ModelApproval,
    require_matching_approval,
)


def test_approved_at_defaults_to_now():
    before = time.time()
    approval = ModelApproval(approved_by="Jane Analyst")
    after = time.time()
    assert before <= approval.approved_at <= after


def test_to_dict_from_dict_roundtrip():
    approval = ModelApproval(
        approved_by="Jane Analyst",
        run_label="uk-v3",
        notes="Converged cleanly, ROI plausible.",
        known_limitations="Direct Mail curve is weakly identified (low spend variation).",
        diagnostics_accepted=["convergence", "in_sample_fit", "ppc_coverage"],
        model_run_id="run-123",
        data_fingerprint="a" * 64,
        model_spec_fingerprint="b" * 64,
        posterior_fingerprint="c" * 64,
    )
    restored = ModelApproval.from_dict(approval.to_dict())
    assert restored == approval


def test_from_dict_ignores_unknown_keys():
    d = ModelApproval(approved_by="Jane Analyst").to_dict()
    d["future_field"] = "should be ignored"
    restored = ModelApproval.from_dict(d)
    assert restored.approved_by == "Jane Analyst"


IDENTITY = dict(
    model_run_id="run-123",
    data_fingerprint="data-abc",
    model_spec_fingerprint="spec-def",
    posterior_fingerprint="posterior-ghi",
)


def _bound_approval(**overrides) -> ModelApproval:
    kwargs = dict(approved_by="Jane Analyst", **IDENTITY)
    kwargs.update(overrides)
    return ModelApproval(**kwargs)


class TestIsModelBound:
    def test_bound_when_all_identity_fields_present(self):
        assert _bound_approval().is_model_bound() is True

    def test_unbound_by_default(self):
        assert ModelApproval(approved_by="Jane Analyst").is_model_bound() is False

    @pytest.mark.parametrize("missing_field", list(IDENTITY.keys()))
    def test_unbound_if_any_single_identity_field_missing(self, missing_field):
        kwargs = dict(IDENTITY)
        kwargs[missing_field] = ""
        approval = ModelApproval(approved_by="Jane Analyst", **kwargs)
        assert approval.is_model_bound() is False


class TestMatchesCurrentModel:
    def test_matches_the_exact_model_it_was_created_for(self):
        approval = _bound_approval()
        assert approval.matches_current_model(**IDENTITY) is True

    def test_fails_for_different_model_run_id(self):
        approval = _bound_approval()
        current = dict(IDENTITY)
        current["model_run_id"] = "different-run"
        assert approval.matches_current_model(**current) is False

    def test_fails_for_changed_data_fingerprint(self):
        approval = _bound_approval()
        current = dict(IDENTITY)
        current["data_fingerprint"] = "different-data"
        assert approval.matches_current_model(**current) is False

    def test_fails_for_changed_spec_fingerprint(self):
        approval = _bound_approval()
        current = dict(IDENTITY)
        current["model_spec_fingerprint"] = "different-spec"
        assert approval.matches_current_model(**current) is False

    def test_fails_for_changed_posterior_fingerprint(self):
        approval = _bound_approval()
        current = dict(IDENTITY)
        current["posterior_fingerprint"] = "different-posterior"
        assert approval.matches_current_model(**current) is False

    @pytest.mark.parametrize("missing_field", list(IDENTITY.keys()))
    def test_fails_when_a_current_identifier_is_missing(self, missing_field):
        approval = _bound_approval()
        current = dict(IDENTITY)
        current[missing_field] = ""
        assert approval.matches_current_model(**current) is False

    def test_legacy_approval_never_matches_even_with_correct_looking_values(self):
        """A legacy (unbound) approval must never be treated as valid just because a
        ModelApproval object exists - not even if someone tries to compare it
        against empty/matching-looking identifiers."""
        legacy = ModelApproval(approved_by="Jane Analyst")  # no fingerprints at all
        assert legacy.matches_current_model(**IDENTITY) is False
        assert (
            legacy.matches_current_model(
                model_run_id="",
                data_fingerprint="",
                model_spec_fingerprint="",
                posterior_fingerprint="",
            )
            is False
        )


class TestRequireMatchingApproval:
    def test_returns_approval_when_matching(self):
        approval = _bound_approval()
        assert require_matching_approval(approval, **IDENTITY) is approval

    def test_raises_for_none(self):
        with pytest.raises(ApprovalMismatchError):
            require_matching_approval(None, **IDENTITY)

    def test_raises_for_wrong_type(self):
        with pytest.raises(ApprovalMismatchError):
            require_matching_approval({"not": "an approval"}, **IDENTITY)

    def test_raises_for_legacy_approval(self):
        legacy = ModelApproval(approved_by="Jane Analyst")
        with pytest.raises(ApprovalMismatchError):
            require_matching_approval(legacy, **IDENTITY)

    def test_raises_for_mismatched_run_id(self):
        approval = _bound_approval()
        current = dict(IDENTITY)
        current["model_run_id"] = "a-different-run"
        with pytest.raises(ApprovalMismatchError):
            require_matching_approval(approval, **current)


# ---------------------------------------------------------------------------
# REQ-VAL-001: Validation policy integration
# ---------------------------------------------------------------------------


class TestValidationPolicyIntegration:
    """require_matching_approval with validation-policy-bound approval."""

    @pytest.fixture
    def val_policy_approval(self):
        return _bound_approval(validation_policy_id="val-pol-001")

    @pytest.fixture
    def passing_readiness(self):
        from ancestry_mmm.core.validation_policy import (
            ValidationResult,
            ThresholdPolicy,
        )

        policy = ThresholdPolicy(
            policy_id="val-pol-001",
            version="1.0",
            scope="test",
            owner="Test Owner",
        )
        results = [
            ValidationResult(
                gate_name="convergence_rhat",
                status="pass",
                model_run_id="run-123",
                data_fingerprint="data-abc",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
                policy_id="val-pol-001",
                policy_version="1.0",
            )
        ]
        from ancestry_mmm.core.validation_policy import evaluate_approval_readiness

        return evaluate_approval_readiness(results, policy)

    @pytest.fixture
    def failing_readiness(self):
        from ancestry_mmm.core.validation_policy import (
            ValidationResult,
            ValidationGate,
            ThresholdPolicy,
        )

        gate = ValidationGate(
            name="convergence_rhat",
            description="R-hat check",
            blocking=True,
            required=True,
        )
        policy = ThresholdPolicy(
            policy_id="val-pol-001",
            version="1.0",
            scope="test",
            gates=[gate],
            owner="Test Owner",
        )
        results = [
            ValidationResult(
                gate_name="convergence_rhat",
                status="fail",
                value=1.2,
                message="R-hat too high",
                model_run_id="run-123",
                data_fingerprint="data-abc",
                model_spec_fingerprint="spec-def",
                posterior_fingerprint="post-ghi",
                policy_id="val-pol-001",
                policy_version="1.0",
            )
        ]
        from ancestry_mmm.core.validation_policy import evaluate_approval_readiness

        return evaluate_approval_readiness(results, policy)

    def test_policy_bound_approval_passes_with_readiness(
        self,
        val_policy_approval,
        passing_readiness,
    ):
        result = require_matching_approval(
            val_policy_approval,
            **IDENTITY,
            approval_readiness=passing_readiness,
        )
        assert result is val_policy_approval

    def test_policy_bound_approval_blocked_without_readiness(
        self,
        val_policy_approval,
    ):
        from ancestry_mmm.core.approval import ValidationPolicyBlockedError

        with pytest.raises(ValidationPolicyBlockedError):
            require_matching_approval(val_policy_approval, **IDENTITY)

    def test_policy_bound_approval_blocked_with_failing_readiness(
        self,
        val_policy_approval,
        failing_readiness,
    ):
        from ancestry_mmm.core.approval import ValidationPolicyBlockedError

        with pytest.raises(ValidationPolicyBlockedError):
            require_matching_approval(
                val_policy_approval,
                **IDENTITY,
                approval_readiness=failing_readiness,
            )

    def test_non_policy_approval_ignores_readiness(self, passing_readiness):
        approval = _bound_approval()  # no validation_policy_id
        result = require_matching_approval(
            approval,
            **IDENTITY,
            approval_readiness=passing_readiness,
        )
        assert result is approval

    def test_policy_mismatch_blocked(self, val_policy_approval):
        from ancestry_mmm.core.validation_policy import (
            ThresholdPolicy,
        )
        from ancestry_mmm.core.validation_policy import evaluate_approval_readiness
        from ancestry_mmm.core.approval import ValidationPolicyBlockedError

        wrong_policy = ThresholdPolicy(
            policy_id="different-policy",
            version="1.0",
            scope="test",
            owner="Test Owner",
        )
        readiness = evaluate_approval_readiness([], wrong_policy)
        with pytest.raises(ValidationPolicyBlockedError):
            require_matching_approval(
                val_policy_approval,
                **IDENTITY,
                approval_readiness=readiness,
            )

    def test_wrong_type_readiness_blocked(self, val_policy_approval):
        from ancestry_mmm.core.approval import ValidationPolicyBlockedError

        with pytest.raises(ValidationPolicyBlockedError):
            require_matching_approval(
                val_policy_approval,
                **IDENTITY,
                approval_readiness="not_a_readiness_object",  # type: ignore
            )
