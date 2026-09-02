"""Tests for `ancestry_mmm.core.experiment_lift_test_mapping` (Decision 11
Phase C implementation: PyMC-Marketing lift-test calibration mapping).
See `docs/experiment_calibration_mechanism_decision_record.md` for the
decisions (C1-C3) these tests verify."""

import pytest

from ancestry_mmm.core.experiment_lift_test_mapping import (
    LiftTestCalibrationRow,
    build_lift_test_calibration_row,
    build_lift_test_calibration_rows,
)
from ancestry_mmm.core.experiments import (
    COMPATIBILITY_DIMENSIONS,
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
    EVIDENCE_MODE_VALIDATION_ONLY,
    ExperimentRecord,
    ExperimentToModelUse,
    assess_experiment_compatibility,
    build_calibrating_use,
)


def _fully_compatible_assessment(experiment_id="exp1"):
    return assess_experiment_compatibility(
        experiment_id, {dim: True for dim in COMPATIBILITY_DIMENSIONS}
    )


def _partially_incompatible_assessment(experiment_id="exp1"):
    results = {dim: True for dim in COMPATIBILITY_DIMENSIONS}
    results["treatment"] = False
    return assess_experiment_compatibility(experiment_id, results)


def _record(**overrides):
    defaults = dict(
        experiment_id="exp1",
        experiment_version=1,
        design="geo_test",
        start_date="2025-01-01",
        end_date="2025-03-01",
        market_scope=("UK",),
        estimand="paid_search_incremental_gsa",
        observed_effect_estimate=120.0,
        effect_uncertainty=15.0,
        method="synthetic_control",
        source="internal_geo_experiment",
        evidence_status="approved",
        treatment_quantity=5000.0,
        baseline_exposure_level=20000.0,
    )
    defaults.update(overrides)
    return ExperimentRecord(**defaults)


def _calibrating_use(compatibility, **overrides):
    defaults = dict(
        compatibility=compatibility,
        experiment_version=1,
        evidence_mode=EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
        model_id="uk_national_model",
        model_version="1",
        affected_likelihood_term_name="paid_search_saturation",
        affected_likelihood_term_version="1",
    )
    defaults.update(overrides)
    return build_calibrating_use(**defaults)


class TestBuildLiftTestCalibrationRow:
    def test_valid_mapping(self):
        record = _record()
        compatibility = _fully_compatible_assessment()
        use = _calibrating_use(compatibility)
        row = build_lift_test_calibration_row(
            record, use, compatibility, channel="paid_search_uk"
        )
        assert row.channel == "paid_search_uk"
        assert row.x == 20000.0
        assert row.delta_x == 5000.0
        assert row.delta_y == 120.0
        assert row.sigma == 15.0
        assert row.date == "2025-01-01"
        assert row.experiment_id == "exp1"

    def test_non_likelihood_calibration_evidence_mode_is_rejected(self):
        record = _record()
        compatibility = _fully_compatible_assessment()
        use = ExperimentToModelUse(
            experiment_id="exp1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
            model_id="uk_national_model",
            model_version="1",
        )
        with pytest.raises(ValueError, match="likelihood_calibration"):
            build_lift_test_calibration_row(
                record, use, compatibility, channel="paid_search_uk"
            )

    def test_incompatible_experiment_is_rejected_even_if_use_exists(self):
        # ExperimentToModelUse can technically be constructed directly,
        # bypassing build_calibrating_use's own gate - this module must
        # re-verify compatibility independently, never trust the use blindly.
        record = _record()
        incompatible = _partially_incompatible_assessment()
        use = ExperimentToModelUse(
            experiment_id="exp1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
            model_id="uk_national_model",
            model_version="1",
            affected_likelihood_term_name="paid_search_saturation",
            affected_likelihood_term_version="1",
        )
        with pytest.raises(ValueError, match="not fully compatible"):
            build_lift_test_calibration_row(
                record, use, incompatible, channel="paid_search_uk"
            )

    def test_missing_baseline_exposure_level_is_rejected(self):
        record = _record(baseline_exposure_level=None)
        compatibility = _fully_compatible_assessment()
        use = _calibrating_use(compatibility)
        with pytest.raises(ValueError, match="baseline_exposure_level"):
            build_lift_test_calibration_row(
                record, use, compatibility, channel="paid_search_uk"
            )

    def test_missing_treatment_quantity_is_rejected(self):
        record = _record(treatment_quantity=None)
        compatibility = _fully_compatible_assessment()
        use = _calibrating_use(compatibility)
        with pytest.raises(ValueError, match="treatment_quantity"):
            build_lift_test_calibration_row(
                record, use, compatibility, channel="paid_search_uk"
            )

    def test_zero_uncertainty_is_rejected(self):
        record = _record(effect_uncertainty=0.0)
        compatibility = _fully_compatible_assessment()
        use = _calibrating_use(compatibility)
        with pytest.raises(ValueError, match="effect_uncertainty"):
            build_lift_test_calibration_row(
                record, use, compatibility, channel="paid_search_uk"
            )

    def test_mismatched_experiment_id_between_use_and_record_is_rejected(self):
        compatibility = _fully_compatible_assessment(experiment_id="exp1")
        use = _calibrating_use(compatibility)
        other_record = _record(experiment_id="exp2")
        with pytest.raises(ValueError, match="experiment_id"):
            build_lift_test_calibration_row(
                other_record, use, compatibility, channel="paid_search_uk"
            )

    def test_requires_channel(self):
        record = _record()
        compatibility = _fully_compatible_assessment()
        use = _calibrating_use(compatibility)
        with pytest.raises(ValueError, match="channel"):
            build_lift_test_calibration_row(record, use, compatibility, channel="")


class TestBuildLiftTestCalibrationRows:
    def test_batch_builds_all_rows(self):
        record1 = _record(experiment_id="exp1")
        compatibility1 = _fully_compatible_assessment("exp1")
        use1 = _calibrating_use(compatibility1)

        record2 = _record(
            experiment_id="exp2",
            baseline_exposure_level=1000.0,
            treatment_quantity=200.0,
        )
        compatibility2 = _fully_compatible_assessment("exp2")
        use2 = build_calibrating_use(
            compatibility=compatibility2,
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
            model_id="uk_national_model",
            model_version="1",
            affected_likelihood_term_name="paid_search_saturation",
            affected_likelihood_term_version="1",
        )

        rows = build_lift_test_calibration_rows(
            [
                (record1, use1, compatibility1, "paid_search_uk"),
                (record2, use2, compatibility2, "brand_search_uk"),
            ]
        )
        assert len(rows) == 2
        assert rows[0].channel == "paid_search_uk"
        assert rows[1].channel == "brand_search_uk"

    def test_raises_on_first_invalid_entry_rather_than_skipping(self):
        record = _record(baseline_exposure_level=None)
        compatibility = _fully_compatible_assessment()
        use = _calibrating_use(compatibility)
        with pytest.raises(ValueError):
            build_lift_test_calibration_rows(
                [(record, use, compatibility, "paid_search_uk")]
            )


class TestLiftTestCalibrationRow:
    def test_round_trip(self):
        row = LiftTestCalibrationRow(
            experiment_id="exp1",
            experiment_version=1,
            channel="paid_search_uk",
            x=20000.0,
            delta_x=5000.0,
            delta_y=120.0,
            sigma=15.0,
            date="2025-01-01",
        )
        restored = LiftTestCalibrationRow.from_dict(row.to_dict())
        assert restored == row

    def test_rejects_non_positive_sigma(self):
        with pytest.raises(ValueError, match="sigma"):
            LiftTestCalibrationRow(
                experiment_id="exp1",
                experiment_version=1,
                channel="paid_search_uk",
                x=20000.0,
                delta_x=5000.0,
                delta_y=120.0,
                sigma=0.0,
            )

    def test_rejects_negative_x(self):
        with pytest.raises(ValueError, match="x"):
            LiftTestCalibrationRow(
                experiment_id="exp1",
                experiment_version=1,
                channel="paid_search_uk",
                x=-1.0,
                delta_x=5000.0,
                delta_y=120.0,
                sigma=15.0,
            )
