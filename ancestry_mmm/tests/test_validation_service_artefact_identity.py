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
        # PR 79A (WP5): a mismatch stops *all* gate evaluation - not just
        # the artefact read for this gate - so no live recalculation is
        # attempted either, and no gate result of any kind is produced.
        assert result.results == []
        assert result.readiness is not None
        assert result.readiness.overall_ready is False
        assert "backtest_mape" in result.readiness.missing_required_gates

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


class TestOfficialCanonicalEvidenceModeFailsClosed:
    """PR 82B: ValidationInput.evidence_mode="official_canonical" must never
    fall through to a live evaluator - a gate whose metric is genuinely
    absent from an otherwise-valid artefact fails closed instead of being
    silently recomputed, and a policy-backed approval flow (which always
    uses this mode) can never end up mixing persisted and recomputed
    evidence."""

    def _policy_with_missing_metric_gate(self) -> ThresholdPolicy:
        # "rhat" (convergence_rhat) is deliberately absent from the
        # artefact below (only backtest_mape is populated) - this is the
        # metric official mode must refuse to recompute live.
        return ThresholdPolicy(
            policy_id="official-policy",
            version="1.0",
            scope="all_models",
            owner="Test",
            gates=[
                ValidationGate(
                    name="rhat",
                    description="Max R-hat",
                    evaluator_id="rhat",
                    acceptable_range=(0.0, 1.05),
                    direction="lower_is_better",
                )
            ],
        )

    def _artefact_missing_convergence(self) -> DiagnosticsArtefact:
        identity_fp = CURRENT_IDENTITY.fingerprint()
        return DiagnosticsArtefact(
            artefact_id="official-artefact",
            schema_version=2,
            model_identity_fingerprint=identity_fp,
            legacy_incomplete=False,
            backtest=DiagnosticSection(
                status="computed",
                payload=[{"mape_pct": 5.0}],
            ),
            # convergence left at its default "not_computed" status.
        )

    def test_official_mode_fails_gate_closed_when_metric_missing_from_artefact(self):
        service = ValidationService()
        v_input = ValidationInput(
            trace=object(),  # a live evaluator, if reached, needs real trace data
            policy=self._policy_with_missing_metric_gate(),
            model_identity=CURRENT_IDENTITY,
            diagnostics_artefact=self._artefact_missing_convergence(),
            model_type="shared",
            evidence_mode="official_canonical",
        )

        result = service.evaluate_readiness(v_input)

        assert len(result.results) == 1
        gate_result = result.results[0]
        assert gate_result.status == "fail"
        assert (
            "not present in the canonical diagnostics artefact" in gate_result.message
        )
        assert "does not recompute missing evidence live" in gate_result.message

    def test_live_exploratory_mode_still_falls_back_for_the_same_input(self):
        """Sanity check: the same missing-metric scenario under the default
        live_exploratory mode still falls through and attempts live
        recomputation (whether or not that live attempt itself succeeds on
        this synthetic trace is not what's being tested here) - official
        mode is a distinct, opt-in branch, not a global change in default
        behaviour. The official-mode-specific fail-closed message must not
        appear anywhere, in either a gate result or an evaluation error."""
        service = ValidationService()
        v_input = ValidationInput(
            trace=object(),
            frame={"X_media": [[1.0]]},
            meta=object(),
            policy=self._policy_with_missing_metric_gate(),
            model_identity=CURRENT_IDENTITY,
            diagnostics_artefact=self._artefact_missing_convergence(),
            model_type="shared",
            # evidence_mode left at its default (live_exploratory).
        )

        result = service.evaluate_readiness(v_input)

        all_messages = [r.message for r in result.results] + result.errors
        assert not any(
            "not present in the canonical diagnostics artefact" in m
            for m in all_messages
        ), all_messages

    def test_official_mode_fails_closed_with_no_artefact_at_all(self):
        """Official mode never evaluates a gate live even when there is no
        artefact whatsoever for this gate - "canonical evidence only" means
        every gate, not just the ones an artefact happens to cover."""
        service = ValidationService()
        v_input = ValidationInput(
            trace=object(),
            policy=self._policy_with_missing_metric_gate(),
            model_identity=CURRENT_IDENTITY,
            diagnostics_artefact=None,
            model_type="shared",
            evidence_mode="official_canonical",
        )

        result = service.evaluate_readiness(v_input)

        assert len(result.results) == 1
        gate_result = result.results[0]
        assert gate_result.status == "fail"
        assert "requires a valid, identity-matching diagnostics artefact" in (
            gate_result.message
        )

    def test_official_mode_still_passes_when_metric_is_present(self):
        """Official mode is not simply "always fail" - a gate whose metric
        genuinely is in a valid, identity-matching artefact still passes
        normally, exactly like the pre-existing artefact-backed path."""
        identity_fp = CURRENT_IDENTITY.fingerprint()
        artefact = DiagnosticsArtefact(
            artefact_id="official-artefact-2",
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
            diagnostics_artefact=artefact,
            model_type="shared",
            evidence_mode="official_canonical",
        )

        result = service.evaluate_readiness(v_input)

        assert len(result.results) == 1
        gate_result = result.results[0]
        assert gate_result.status == "pass"
        assert gate_result.value == 5.0
