"""Tests for the canonical diagnostics evidence artefact (PR 72B).

Covers:
- DiagnosticSection states and validation
- DiagnosticsArtefact schema v2 round-trip and fingerprint
- Schema v1 → v2 compatibility
- DiagnosticsService evaluate with artefact sections
- ValidationService artefact consumption
"""

import uuid
from datetime import datetime, timezone

import pytest

from ancestry_mmm.application.diagnostics_service import (
    DiagnosticSection,
    DiagnosticsArtefact,
)
from ancestry_mmm.application.validation_service import (
    ValidationInput,
    ValidationService,
)


# =========================================================================
# DiagnosticSection
# =========================================================================


class TestDiagnosticSection:
    def test_computed_requires_payload(self):
        DiagnosticSection(status="computed", payload={"key": 1.0})  # ok

    def test_computed_without_payload_raises(self):
        with pytest.raises(ValueError, match="must have a non-None payload"):
            DiagnosticSection(status="computed", payload=None)

    def test_failed_requires_error(self):
        DiagnosticSection(status="failed", payload=None, error="something broke")

    def test_failed_without_error_raises(self):
        with pytest.raises(ValueError, match="must have a non-blank error"):
            DiagnosticSection(status="failed", payload=None, error="")

    def test_not_computed_no_payload(self):
        sec = DiagnosticSection(status="not_computed", payload=None)
        assert sec.status == "not_computed"

    def test_not_applicable_no_payload(self):
        sec = DiagnosticSection(
            status="not_applicable", payload=None, error="Only for market-specific"
        )
        assert sec.status == "not_applicable"

    def test_to_dict_round_trip(self):
        sec = DiagnosticSection(
            status="computed",
            payload={"value": 42.0, "label": "test"},
            warnings=("warn1",),
        )
        d = sec.to_dict()
        restored = DiagnosticSection.from_dict(d)
        assert restored.status == sec.status
        assert restored.payload == sec.payload
        assert restored.warnings == sec.warnings

    def test_fingerprint_changes_with_payload(self):
        sec1 = DiagnosticSection(status="computed", payload={"v": 1.0})
        sec2 = DiagnosticSection(status="computed", payload={"v": 2.0})
        assert sec1.fingerprint_payload() != sec2.fingerprint_payload()

    def test_fingerprint_changes_with_warnings(self):
        sec1 = DiagnosticSection(status="computed", payload={"v": 1.0}, warnings=())
        sec2 = DiagnosticSection(
            status="computed", payload={"v": 1.0}, warnings=("warn",)
        )
        assert sec1.fingerprint_payload() != sec2.fingerprint_payload()

    def test_fingerprint_changes_with_status(self):
        sec1 = DiagnosticSection(status="computed", payload={"v": 1.0})
        sec2 = DiagnosticSection(status="failed", payload=None, error="err")
        assert sec1.fingerprint_payload() != sec2.fingerprint_payload()


# =========================================================================
# DiagnosticsArtefact schema v2
# =========================================================================


class TestDiagnosticsArtefactV2:
    def test_default_artefact(self):
        artefact = DiagnosticsArtefact()
        assert artefact.schema_version == 2
        assert artefact.diagnostics_version == "2.0.0"
        assert artefact.convergence.status == "not_computed"
        assert artefact.legacy_incomplete is False

    def test_to_dict_has_all_sections(self):
        artefact = DiagnosticsArtefact(artefact_id="test-id")
        d = artefact.to_dict()
        assert d["schema_version"] == 2
        assert d["artefact_id"] == "test-id"
        for section in (
            "convergence",
            "in_sample_fit",
            "posterior_predictive",
            "plausibility",
            "identification",
            "coefficient_stability",
            "backtest",
        ):
            assert section in d
            assert "status" in d[section]

    def test_round_trip_preserves_all_fields(self):
        convergence = DiagnosticSection(
            status="computed",
            payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
        )
        original = DiagnosticsArtefact(
            artefact_id=uuid.uuid4().hex,
            diagnostics_version="2.0.0",
            schema_version=2,
            model_identity_fingerprint="fp123",
            evaluated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
            model_type="shared",
            convergence=convergence,
            posterior_predictive=DiagnosticSection(
                status="computed",
                payload=[{"coverage_pct": 95.0}],
            ),
            global_warnings=("warn1",),
            global_errors=("err1",),
            settings=(("credible_mass", "0.9"),),
        )
        d = original.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.artefact_id == original.artefact_id
        assert restored.schema_version == original.schema_version
        assert (
            restored.model_identity_fingerprint == original.model_identity_fingerprint
        )
        assert restored.convergence.status == "computed"
        assert restored.convergence.payload["max_rhat"] == 1.02
        assert restored.posterior_predictive.payload[0]["coverage_pct"] == 95.0
        assert restored.global_warnings == ("warn1",)
        assert restored.global_errors == ("err1",)
        assert restored.legacy_incomplete is False

    def test_deterministic_fingerprint(self):
        a1 = DiagnosticsArtefact(
            artefact_id="same",
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02},
            ),
        )
        a2 = DiagnosticsArtefact(
            artefact_id="same",
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02},
            ),
        )
        assert a1.fingerprint() == a2.fingerprint()

    def test_fingerprint_changes_on_payload_change(self):
        a1 = DiagnosticsArtefact(
            artefact_id="id1",
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02},
            ),
        )
        a2 = DiagnosticsArtefact(
            artefact_id="id1",
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.05},
            ),
        )
        assert a1.fingerprint() != a2.fingerprint()

    def test_fingerprint_changes_on_section_status(self):
        a1 = DiagnosticsArtefact(
            convergence=DiagnosticSection(status="computed", payload={"v": 1.0}),
        )
        a2 = DiagnosticsArtefact(
            convergence=DiagnosticSection(status="failed", payload=None, error="err"),
        )
        assert a1.fingerprint() != a2.fingerprint()


# =========================================================================
# Schema v1 compatibility
# =========================================================================


class TestSchemaV1Compatibility:
    def test_v1_loads_as_legacy_incomplete(self):
        v1_dict = {
            "artefact_id": "v1-artefact",
            "diagnostics_version": "1.0.0",
            "schema_version": 1,
            "model_identity_fingerprint": "",
            "evaluated_at": "2026-07-29T00:00:00+00:00",
            "max_rhat": 1.02,
            "min_ess": 400,
            "has_divergences": False,
            "mean_ppc_coverage_pct": 89.0,
            "scorecard_fields": ["r_squared"],
            "plausibility_issues": 0,
            "identification_condition_number": 0.0,
            "backtest_folds": 0,
            "backtest_mean_mape": None,
            "settings": [],
        }
        artefact = DiagnosticsArtefact.from_dict(v1_dict)
        assert artefact.schema_version == 1
        assert artefact.legacy_incomplete is True
        assert artefact.convergence.status == "computed"
        assert artefact.convergence.payload["max_rhat"] == 1.02
        assert artefact.in_sample_fit.status == "not_computed"
        assert artefact.posterior_predictive.payload["mean_ppc_coverage_pct"] == 89.0

    def test_v1_cannot_support_official_approval(self):
        v1_dict = {
            "schema_version": 1,
            "evaluated_at": "2026-07-29T00:00:00+00:00",
        }
        artefact = DiagnosticsArtefact.from_dict(v1_dict)
        assert artefact.legacy_incomplete is True
        # Official validation should reject legacy_incomplete artefacts
        assert artefact.schema_version < 2

    def test_unsupported_schema_raises(self):
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            DiagnosticsArtefact.from_dict({"schema_version": 99})


# =========================================================================
# ValidationService artefact consumption
# =========================================================================


class TestValidationServiceArtefactConsumption:
    def test_get_artefact_metric_convergence_rhat(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
            ),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("convergence_rhat", artefact)
        assert metric == 1.02

    def test_get_artefact_metric_convergence_ess(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
            ),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("convergence_ess", artefact)
        assert metric == 400

    def test_get_artefact_metric_divergences(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": True},
            ),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("divergences", artefact)
        assert metric == 1.0

    def test_get_artefact_metric_ppc_coverage(self):
        artefact = DiagnosticsArtefact(
            posterior_predictive=DiagnosticSection(
                status="computed",
                payload=[{"coverage_pct": 95.0}, {"coverage_pct": 85.0}],
            ),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("ppc_coverage", artefact)
        assert metric == 90.0  # mean of 95 and 85

    def test_get_artefact_metric_unknown_evaluator(self):
        artefact = DiagnosticsArtefact()
        service = ValidationService()
        metric = service._get_artefact_metric("unknown_evaluator", artefact)
        assert metric is None

    def test_get_artefact_metric_not_computed_section(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(status="not_computed"),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("convergence_rhat", artefact)
        assert metric is None

    def test_get_artefact_metric_legacy_v1_returns_none(self):
        v1_dict = {
            "schema_version": 1,
            "evaluated_at": "2026-07-29T00:00:00+00:00",
        }
        artefact = DiagnosticsArtefact.from_dict(v1_dict)
        service = ValidationService()
        metric = service._get_artefact_metric("convergence_rhat", artefact)
        assert metric is None

    def test_validation_input_accepts_artefact(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
            ),
        )
        v_input = ValidationInput(
            diagnostics_artefact=artefact,
        )
        assert v_input.diagnostics_artefact is artefact
