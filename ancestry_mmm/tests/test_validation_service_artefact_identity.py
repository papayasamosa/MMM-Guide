"""Regression tests for artefact identity-mismatch handling in ValidationService.

PR 79A (partial): ``evaluate_readiness`` previously computed a local
``use_artefact`` flag when a diagnostics artefact's model identity did not
match the current model, but never threaded that decision into
``_evaluate_gate`` — which independently re-derived artefact usability from
``v_input.diagnostics_artefact`` without checking identity at all. A stale
artefact could therefore still be read for gate values even after being
flagged as mismatched. These tests pin the fail-closed behaviour: a
mismatched artefact must never be read by gate evaluation.
"""

from ancestry_mmm.application.diagnostics_service import (
    DiagnosticSection,
    DiagnosticsArtefact,
)
from ancestry_mmm.application.validation_service import (
    ValidationInput,
    ValidationService,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.validation_policy import ThresholdPolicy, ValidationGate

CURRENT_IDENTITY = ModelIdentity(
    model_run_id="run-current",
    data_fingerprint="data-current",
    model_spec_fingerprint="spec-current",
    posterior_fingerprint="posterior-current",
)


def _backtest_policy() -> ThresholdPolicy:
    return ThresholdPolicy(
        policy_id="test-policy",
        version="1.0",
        scope="all_models",
        owner="Test",
        gates=[
            ValidationGate(
                name="backtest_mape",
                description="Backtest MAPE",
                evaluator_id="backtest_mape",
                acceptable_range=(0.0, 10.0),
                direction="lower_is_better",
            )
        ],
    )


class TestArtefactIdentityMismatchFailsClosed:
    def test_mismatched_artefact_is_not_read_for_gate_value(self):
        """A stale artefact (built for a different model identity) must not
        supply the gate's value even though it has a 'good' computed
        backtest MAPE that would otherwise pass the gate.
        """
        stale_artefact = DiagnosticsArtefact(
            artefact_id="stale-artefact",
            schema_version=2,
            model_identity_fingerprint="some-other-model-fingerprint",
            legacy_incomplete=False,
            backtest=DiagnosticSection(
                status="computed",
                payload=[{"mape_pct": 5.0}],
            ),
        )
        service = ValidationService()
        v_input = ValidationInput(
            trace=object(),  # backtest_mape's live evaluator needs no trace fields
            policy=_backtest_policy(),
            model_identity=CURRENT_IDENTITY,
            diagnostics_artefact=stale_artefact,
            model_type="shared",
        )

        result = service.evaluate_readiness(v_input)

        assert any(
            "does not match the current model identity" in e for e in result.errors
        )
        assert len(result.results) == 1
        gate_result = result.results[0]
        # Fell through to the live evaluator (fails closed), not the
        # artefact's mape_pct=5.0, which would have passed the (0, 10) gate.
        assert gate_result.status == "fail"
        assert gate_result.value is None
        assert "cannot be evaluated live" in gate_result.message

    def test_matching_artefact_is_read_for_gate_value(self):
        """Sanity check: when identity matches, the artefact value is used
        as before — the fix must not break the normal artefact-backed path.
        """
        identity_fp = CURRENT_IDENTITY.fingerprint()
        matching_artefact = DiagnosticsArtefact(
            artefact_id="matching-artefact",
            schema_version=2,
            model_identity_fingerprint=identity_fp,
            legacy_incomplete=False,
            backtest=DiagnosticSection(
                status="computed",
                payload=[{"mape_pct": 5.0}],
            ),
        )
        service = ValidationService()
        v_input = ValidationInput(
            trace=object(),
            policy=_backtest_policy(),
            model_identity=CURRENT_IDENTITY,
            diagnostics_artefact=matching_artefact,
            model_type="shared",
        )

        result = service.evaluate_readiness(v_input)

        assert not any(
            "does not match the current model identity" in e for e in result.errors
        )
        assert len(result.results) == 1
        gate_result = result.results[0]
        assert gate_result.status == "pass"
        assert gate_result.value == 5.0
        assert "Read from diagnostics artefact" in gate_result.message
