"""REQ-CALIB-001 (Work Package 4, second record): tests for
core.calibration_comparison."""

from __future__ import annotations

import pytest

from ancestry_mmm.core.calibration_comparison import (
    UNCERTAINTY_CHANGE_INCREASED,
    UNCERTAINTY_CHANGE_REDUCED,
    CalibratedVsUncalibratedComparisonArtefact,
    CalibrationComparisonMetric,
    CalibrationEventRecord,
    ExperimentAgreementComparison,
    assemble_calibration_comparison,
)
from ancestry_mmm.core.model_identity import ModelIdentity


def _identity(model_run_id: str = "run-1") -> ModelIdentity:
    return ModelIdentity(
        model_run_id=model_run_id,
        data_fingerprint="data-fp",
        model_spec_fingerprint="spec-fp",
        posterior_fingerprint=f"posterior-fp-{model_run_id}",
    )


CALIBRATED = _identity("calibrated-run")
UNCALIBRATED = _identity("uncalibrated-run")


# ---------------------------------------------------------------------------
# CalibrationComparisonMetric
# ---------------------------------------------------------------------------


class TestCalibrationComparisonMetric:
    def test_requires_metric_name(self):
        with pytest.raises(ValueError, match="metric_name is required"):
            CalibrationComparisonMetric(
                metric_name="", calibrated_value=1.0, uncalibrated_value=1.0
            )

    def test_difference_is_descriptive(self):
        metric = CalibrationComparisonMetric(
            metric_name="mae", calibrated_value=1.2, uncalibrated_value=1.5
        )
        assert metric.difference == pytest.approx(-0.3)

    def test_round_trip(self):
        original = CalibrationComparisonMetric(
            metric_name="mae",
            calibrated_value=1.2,
            uncalibrated_value=1.5,
            calibrated_draws=(1.1, 1.3),
            uncalibrated_draws=(1.4, 1.6),
        )
        restored = CalibrationComparisonMetric.from_dict(original.to_dict())
        assert restored == original


# ---------------------------------------------------------------------------
# ExperimentAgreementComparison
# ---------------------------------------------------------------------------


class TestExperimentAgreementComparison:
    def test_requires_experiment_id(self):
        with pytest.raises(ValueError, match="experiment_id is required"):
            ExperimentAgreementComparison(
                experiment_id="", calibrated_agreement=0.1, uncalibrated_agreement=0.3
            )

    def test_round_trip(self):
        original = ExperimentAgreementComparison(
            experiment_id="geo-2026-01",
            calibrated_agreement=0.1,
            uncalibrated_agreement=0.3,
        )
        restored = ExperimentAgreementComparison.from_dict(original.to_dict())
        assert restored == original


# ---------------------------------------------------------------------------
# CalibratedVsUncalibratedComparisonArtefact
# ---------------------------------------------------------------------------


class TestComparisonArtefact:
    def test_rejects_identical_identities(self):
        with pytest.raises(ValueError, match="must be distinct"):
            assemble_calibration_comparison(CALIBRATED, CALIBRATED)

    def test_assembles_from_caller_supplied_evidence(self):
        artefact = assemble_calibration_comparison(
            CALIBRATED,
            UNCALIBRATED,
            metrics=(
                CalibrationComparisonMetric(
                    metric_name="mae", calibrated_value=1.2, uncalibrated_value=1.5
                ),
            ),
            experiment_agreements=(
                ExperimentAgreementComparison(
                    experiment_id="geo-2026-01",
                    calibrated_agreement=0.1,
                    uncalibrated_agreement=0.3,
                ),
            ),
        )
        assert len(artefact.per_metric) == 1
        assert len(artefact.per_experiment_agreement) == 1

    def test_round_trip(self):
        original = assemble_calibration_comparison(
            CALIBRATED,
            UNCALIBRATED,
            metrics=(
                CalibrationComparisonMetric(
                    metric_name="mae", calibrated_value=1.2, uncalibrated_value=1.5
                ),
            ),
            limitations=("some limitation",),
        )
        restored = CalibratedVsUncalibratedComparisonArtefact.from_dict(
            original.to_dict()
        )
        assert restored == original

    def test_no_verdict_or_recommendation_field_exists(self):
        """Requirement 3: closer agreement with an experiment must never
        be automatically preferred - this class must never expose a
        threshold, pass/fail, "recommended", or "preferred" field."""
        artefact = assemble_calibration_comparison(CALIBRATED, UNCALIBRATED)
        forbidden_substrings = ("recommend", "prefer", "verdict", "pass_fail", "passed")
        field_names = [f for f in artefact.__dataclass_fields__]
        for name in field_names:
            lowered = name.lower()
            for forbidden in forbidden_substrings:
                assert forbidden not in lowered, (
                    f"field {name!r} suggests an automatic verdict, which "
                    "Requirement 3 forbids"
                )


# ---------------------------------------------------------------------------
# CalibrationEventRecord
# ---------------------------------------------------------------------------


class TestCalibrationEventRecord:
    def test_rejects_identical_identities(self):
        with pytest.raises(ValueError, match="must be distinct"):
            CalibrationEventRecord(
                calibrated_model_identity=CALIBRATED,
                uncalibrated_model_identity=CALIBRATED,
            )

    def test_rejects_invalid_uncertainty_change(self):
        with pytest.raises(ValueError, match="invalid uncertainty_change"):
            CalibrationEventRecord(
                calibrated_model_identity=CALIBRATED,
                uncalibrated_model_identity=UNCALIBRATED,
                uncertainty_change="not_a_value",
            )

    def test_none_fields_mean_not_yet_assessed(self):
        record = CalibrationEventRecord(
            calibrated_model_identity=CALIBRATED,
            uncalibrated_model_identity=UNCALIBRATED,
        )
        assert record.resolved_prior_conflict is None
        assert record.materially_changed_decision is None
        assert record.uncertainty_change is None

    def test_full_record_round_trip(self):
        original = CalibrationEventRecord(
            calibrated_model_identity=CALIBRATED,
            uncalibrated_model_identity=UNCALIBRATED,
            resolved_prior_conflict=True,
            materially_changed_decision=False,
            uncertainty_change=UNCERTAINTY_CHANGE_REDUCED,
            validation_dimensions_improved=("structural_stability",),
            validation_dimensions_worsened=(),
            new_limitations_introduced=("wider tail uncertainty in TV curve",),
        )
        restored = CalibrationEventRecord.from_dict(original.to_dict())
        assert restored == original

    def test_uncertainty_increased_is_valid(self):
        record = CalibrationEventRecord(
            calibrated_model_identity=CALIBRATED,
            uncalibrated_model_identity=UNCALIBRATED,
            uncertainty_change=UNCERTAINTY_CHANGE_INCREASED,
        )
        assert record.uncertainty_change == UNCERTAINTY_CHANGE_INCREASED
