"""
Tests for the market x channel engine-capability gate (REQ-COVERAGE-001 S6,
Work Package B: "make coverage a real official-use prerequisite").

Exploratory review of ``core.market_data_capability.
check_market_channel_capability`` and its various coverage-state semantics
(unknown/missing_expected/unavailable_source/not_applicable/approved
treatment/...) is already covered by ``test_market_data_capability.py`` -
this file does not re-derive that. It tests the new plumbing added on top:

1. ``application.diagnostics_service.DiagnosticsService`` computes a
   ``market_channel_capability`` DiagnosticsArtefact section from a
   ``ModelSpec`` + ``VariableCoverageMatrix``.
2. ``application.validation_service.ValidationService`` reads that section
   as a boolean gate metric.
3. ``core.validation_policy.evaluate_approval_readiness`` treats an
   unsupported result as a non-waivable blocking failure, and a supported
   result as a pass - exercised through the exact same generic gate
   mechanism every other gate uses, not a bespoke governance rule.
4. ``core.approval.create_policy_backed_model_approval`` fails closed when
   overall_ready is False because of this gate, and succeeds when it is
   True (all other gates passing).
"""

from __future__ import annotations

from datetime import datetime, timezone

import arviz as az
import numpy as np
import pytest

from ancestry_mmm.application.diagnostics_service import (
    DiagnosticsInput,
    DiagnosticsService,
)
from ancestry_mmm.application.validation_service import (
    MalformedArtefactEvidenceError,
    ValidationService,
)
from ancestry_mmm.core.approval import (
    ValidationPolicyBlockedError,
    create_policy_backed_model_approval,
)
from ancestry_mmm.core.coverage import (
    CoverageSegment,
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.validation_policy import (
    ThresholdPolicy,
    ValidationEvidenceContext,
    ValidationGate,
    ValidationWaiverReference,
    evaluate_approval_readiness,
)

_IDENTITY = ModelIdentity("run-1", "data-1", "spec-1", "post-1")


def _supported_matrix() -> VariableCoverageMatrix:
    """A coverage matrix where TV/UK is fully observed and approved."""
    record = VariableCoverageRecord(
        variable_id="TV",
        source_id="media-src",
        source_version=1,
        market="UK",
        frequency=FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class="flow_count",
        ),
        coverage_segments=(
            CoverageSegment(
                period_start="2026-01-05",
                period_end="2026-01-05",
                state="observed_zero",
            ),
        ),
    )
    return VariableCoverageMatrix(
        matrix_id="mx-1", matrix_version=1, generated_at="2026-08-11", records=(record,)
    )


def _capability_gate() -> ValidationGate:
    return ValidationGate(
        name="market_channel_capability",
        description=(
            "Every requested (market, channel) cell must have governed, "
            "officially-resolved coverage (REQ-COVERAGE-001 S6)."
        ),
        evaluator_id="market_channel_capability",
        scope="all_models",
        acceptable_range=None,
        expected_state=True,
        direction="higher_is_better",
        blocking=True,
        waivable=False,
        required=True,
    )


def _policy(gate: ValidationGate) -> ThresholdPolicy:
    return ThresholdPolicy(
        policy_id="coverage-gate-policy",
        version="1.0.0",
        scope="all_models",
        gates=[gate],
        owner="Platform engineering",
        approval_date=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )


def _context(policy: ThresholdPolicy) -> ValidationEvidenceContext:
    return ValidationEvidenceContext(
        model_identity=_IDENTITY,
        policy=policy,
        diagnostic_artefact_id="diag-1",
        diagnostic_artefact_fingerprint="diag-fp-1",
        model_type="shared",
        intended_use="model_approval",
    )


def _minimal_trace() -> az.InferenceData:
    rng = np.random.default_rng(0)
    return az.from_dict(
        posterior={
            "mu": rng.normal(size=(2, 5, 3)),
            "beta": rng.normal(size=(2, 5, 1)),
            "hill_K": rng.normal(size=(2, 5, 1)),
            "alpha": rng.normal(size=(2, 5)),
        },
        sample_stats={"diverging": np.zeros((2, 5), dtype=bool)},
    )


def _diag_input(
    *, spec: ModelSpec | None, coverage_matrix: VariableCoverageMatrix | None
) -> DiagnosticsInput:
    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=["fh_new_gsa"],
        channels=["TV"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="fh_new_gsa",
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
    )
    frame = {
        "fh_new_gsa": np.array([1, 2, 3]),
        "market_idx": np.array([0, 0, 0]),
        "X_media": np.zeros((3, 1)),
    }
    return DiagnosticsInput(
        trace=_minimal_trace(),
        frame=frame,
        meta=meta,
        model_identity=_IDENTITY,
        raw_model_spec=spec,
        coverage_matrix=coverage_matrix,
    )


# ---------------------------------------------------------------------------
# 1. DiagnosticsService computes the section
# ---------------------------------------------------------------------------


class TestDiagnosticsServiceComputesCapabilitySection:
    def test_not_applicable_without_a_model_spec(self):
        result = DiagnosticsService().evaluate(
            _diag_input(spec=None, coverage_matrix=_supported_matrix())
        )
        section = result.diagnostics_artefact.market_channel_capability
        assert section.status == "not_applicable"

    def test_unsupported_without_a_coverage_matrix(self):
        spec = ModelSpec(date_col="date", market_col="market", markets=["UK"], channels=["TV"])
        result = DiagnosticsService().evaluate(_diag_input(spec=spec, coverage_matrix=None))
        section = result.diagnostics_artefact.market_channel_capability
        assert section.status == "computed"
        assert section.payload["supported"] is False

    def test_supported_with_a_matching_coverage_matrix(self):
        spec = ModelSpec(date_col="date", market_col="market", markets=["UK"], channels=["TV"])
        result = DiagnosticsService().evaluate(
            _diag_input(spec=spec, coverage_matrix=_supported_matrix())
        )
        section = result.diagnostics_artefact.market_channel_capability
        assert section.status == "computed"
        assert section.payload["supported"] is True
        assert section.payload["issues"] == []

    def test_schema_version_is_6(self):
        spec = ModelSpec(date_col="date", market_col="market", markets=["UK"], channels=["TV"])
        result = DiagnosticsService().evaluate(
            _diag_input(spec=spec, coverage_matrix=_supported_matrix())
        )
        assert result.diagnostics_artefact.schema_version == 6


# ---------------------------------------------------------------------------
# 2. ValidationService reads the section
# ---------------------------------------------------------------------------


class TestValidationServiceReadsCapabilityMetric:
    def _artefact_with(self, supported: bool | None, *, status: str = "computed"):
        from ancestry_mmm.application.diagnostics_service import (
            CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
            DiagnosticsArtefact,
            DiagnosticSection,
        )

        payload = None if supported is None else {"supported": supported}
        return DiagnosticsArtefact(
            schema_version=CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
            market_channel_capability=DiagnosticSection(status=status, payload=payload),
        )

    def test_reads_true_as_1(self):
        artefact = self._artefact_with(True)
        value = ValidationService._get_artefact_metric(
            "market_channel_capability", artefact
        )
        assert value == 1.0

    def test_reads_false_as_0(self):
        artefact = self._artefact_with(False)
        value = ValidationService._get_artefact_metric(
            "market_channel_capability", artefact
        )
        assert value == 0.0

    def test_not_computed_section_returns_none(self):
        artefact = self._artefact_with(True, status="not_applicable")
        value = ValidationService._get_artefact_metric(
            "market_channel_capability", artefact
        )
        assert value is None

    def test_missing_supported_key_raises_malformed(self):
        from ancestry_mmm.application.diagnostics_service import (
            CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
            DiagnosticsArtefact,
            DiagnosticSection,
        )

        artefact = DiagnosticsArtefact(
            schema_version=CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
            market_channel_capability=DiagnosticSection(
                status="computed", payload={"markets": ["UK"]}
            ),
        )
        with pytest.raises(MalformedArtefactEvidenceError):
            ValidationService._get_artefact_metric("market_channel_capability", artefact)

    def test_non_bool_supported_value_raises_malformed(self):
        from ancestry_mmm.application.diagnostics_service import (
            CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
            DiagnosticsArtefact,
            DiagnosticSection,
        )

        artefact = DiagnosticsArtefact(
            schema_version=CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
            market_channel_capability=DiagnosticSection(
                status="computed", payload={"supported": "yes"}
            ),
        )
        with pytest.raises(MalformedArtefactEvidenceError):
            ValidationService._get_artefact_metric("market_channel_capability", artefact)


# ---------------------------------------------------------------------------
# 3. evaluate_approval_readiness treats this as a non-waivable blocking gate
# ---------------------------------------------------------------------------


class TestReadinessGating:
    def _result(self, policy, *, status, value):
        gate = policy.get_gate("market_channel_capability")
        return_kwargs = dict(
            gate_name="market_channel_capability",
            status=status,
            value=value,
            message="test",
            model_run_id=_IDENTITY.model_run_id,
            data_fingerprint=_IDENTITY.data_fingerprint,
            model_spec_fingerprint=_IDENTITY.model_spec_fingerprint,
            posterior_fingerprint=_IDENTITY.posterior_fingerprint,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_fingerprint=policy.fingerprint(),
            model_identity_fingerprint=_IDENTITY.fingerprint(),
            gate_fingerprint=gate.fingerprint(),
            diagnostic_artefact_fingerprint="diag-fp-1",
            artefact_id="diag-1",
        )
        from ancestry_mmm.core.validation_policy import ValidationResult

        return ValidationResult(**return_kwargs)

    def test_unsupported_result_is_a_blocking_failure(self):
        gate = _capability_gate()
        policy = _policy(gate)
        result = self._result(policy, status="fail", value=0.0)
        readiness = evaluate_approval_readiness(
            [result],
            policy,
            _IDENTITY,
            diagnostic_artefact_id="diag-1",
            diagnostic_artefact_fingerprint="diag-fp-1",
            evidence_context=_context(policy),
        )
        assert readiness.overall_ready is False
        assert any(
            r.gate_name == "market_channel_capability"
            for r in readiness.blocking_failures
        )

    def test_supported_result_passes_and_readiness_is_ready(self):
        gate = _capability_gate()
        policy = _policy(gate)
        result = self._result(policy, status="pass", value=1.0)
        readiness = evaluate_approval_readiness(
            [result],
            policy,
            _IDENTITY,
            diagnostic_artefact_id="diag-1",
            diagnostic_artefact_fingerprint="diag-fp-1",
            evidence_context=_context(policy),
        )
        assert readiness.overall_ready is True
        assert not readiness.blocking_failures

    def test_missing_result_blocks_via_missing_required_gates(self):
        gate = _capability_gate()
        policy = _policy(gate)
        readiness = evaluate_approval_readiness(
            [],
            policy,
            _IDENTITY,
            diagnostic_artefact_id="diag-1",
            diagnostic_artefact_fingerprint="diag-fp-1",
            evidence_context=_context(policy),
        )
        assert readiness.overall_ready is False
        assert readiness.missing_required_gates

    def test_gate_is_not_waivable_even_with_a_waiver_supplied(self):
        gate = _capability_gate()
        policy = _policy(gate)
        result = self._result(policy, status="fail", value=0.0)
        waiver = ValidationWaiverReference(
            waiver_id="waiver-1",
            gate_name="market_channel_capability",
            reason="We need to ship anyway",
            approved_by="someone",
            approved_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
            original_result_status="fail",
            policy_fingerprint=policy.fingerprint(),
            model_identity_fingerprint=_IDENTITY.fingerprint(),
            gate_fingerprint=gate.fingerprint(),
            diagnostic_artefact_fingerprint="diag-fp-1",
        )
        readiness = evaluate_approval_readiness(
            [result],
            policy,
            _IDENTITY,
            diagnostic_artefact_id="diag-1",
            diagnostic_artefact_fingerprint="diag-fp-1",
            waivers=[waiver],
            evidence_context=_context(policy),
        )
        assert readiness.overall_ready is False
        assert any(
            r.gate_name == "market_channel_capability"
            for r in readiness.blocking_failures
        ), "a waivable=False gate must stay blocking regardless of a supplied waiver"


# ---------------------------------------------------------------------------
# 4. create_policy_backed_model_approval fails closed
# ---------------------------------------------------------------------------


class TestPolicyBackedApprovalFailsClosed:
    def test_approval_blocked_when_capability_gate_fails(self):
        gate = _capability_gate()
        policy = _policy(gate)
        from ancestry_mmm.core.validation_policy import ValidationResult

        failing_result = ValidationResult(
            gate_name="market_channel_capability",
            status="fail",
            value=0.0,
            message="unsupported",
            model_run_id=_IDENTITY.model_run_id,
            data_fingerprint=_IDENTITY.data_fingerprint,
            model_spec_fingerprint=_IDENTITY.model_spec_fingerprint,
            posterior_fingerprint=_IDENTITY.posterior_fingerprint,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_fingerprint=policy.fingerprint(),
            model_identity_fingerprint=_IDENTITY.fingerprint(),
            gate_fingerprint=gate.fingerprint(),
            diagnostic_artefact_fingerprint="diag-fp-1",
            artefact_id="diag-1",
        )
        readiness = evaluate_approval_readiness(
            [failing_result],
            policy,
            _IDENTITY,
            diagnostic_artefact_id="diag-1",
            diagnostic_artefact_fingerprint="diag-fp-1",
            evidence_context=_context(policy),
        )
        assert readiness.overall_ready is False
        with pytest.raises(ValidationPolicyBlockedError):
            create_policy_backed_model_approval(
                approved_by="Jane Analyst",
                readiness=readiness,
                current_policy=policy,
                model_run_id=_IDENTITY.model_run_id,
                data_fingerprint=_IDENTITY.data_fingerprint,
                model_spec_fingerprint=_IDENTITY.model_spec_fingerprint,
                posterior_fingerprint=_IDENTITY.posterior_fingerprint,
            )

    def test_approval_succeeds_when_capability_gate_passes(self):
        gate = _capability_gate()
        policy = _policy(gate)
        from ancestry_mmm.core.validation_policy import ValidationResult

        passing_result = ValidationResult(
            gate_name="market_channel_capability",
            status="pass",
            value=1.0,
            message="supported",
            model_run_id=_IDENTITY.model_run_id,
            data_fingerprint=_IDENTITY.data_fingerprint,
            model_spec_fingerprint=_IDENTITY.model_spec_fingerprint,
            posterior_fingerprint=_IDENTITY.posterior_fingerprint,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_fingerprint=policy.fingerprint(),
            model_identity_fingerprint=_IDENTITY.fingerprint(),
            gate_fingerprint=gate.fingerprint(),
            diagnostic_artefact_fingerprint="diag-fp-1",
            artefact_id="diag-1",
        )
        readiness = evaluate_approval_readiness(
            [passing_result],
            policy,
            _IDENTITY,
            diagnostic_artefact_id="diag-1",
            diagnostic_artefact_fingerprint="diag-fp-1",
            evidence_context=_context(policy),
        )
        assert readiness.overall_ready is True
        approval = create_policy_backed_model_approval(
            approved_by="Jane Analyst",
            readiness=readiness,
            current_policy=policy,
            model_run_id=_IDENTITY.model_run_id,
            data_fingerprint=_IDENTITY.data_fingerprint,
            model_spec_fingerprint=_IDENTITY.model_spec_fingerprint,
            posterior_fingerprint=_IDENTITY.posterior_fingerprint,
        )
        assert approval.validation_policy_id == policy.policy_id
