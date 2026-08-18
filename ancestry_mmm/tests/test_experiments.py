"""REQ-EXPMODE-001 (Work Package 4): tests for core.experiments."""

from __future__ import annotations

import pytest

from ancestry_mmm.core.experiments import (
    COMPATIBILITY_DIMENSIONS,
    EVIDENCE_MODE_DIAGNOSTIC_COMPARISON,
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
    EVIDENCE_MODE_PRIOR_CALIBRATION,
    EVIDENCE_MODE_VALIDATION_ONLY,
    EXPERIMENT_DESIGN_GEO_TEST,
    CompatibilityAssessment,
    ExperimentRecord,
    ExperimentToModelUse,
    assess_experiment_compatibility,
    build_calibrating_use,
    build_provenance_report,
    current_experiment_versions,
    new_experiment_version,
    validate_no_double_counted_dependence,
)


def _record(experiment_id: str = "geo-2026-01", **overrides) -> ExperimentRecord:
    defaults = dict(
        experiment_id=experiment_id,
        experiment_version=1,
        design=EXPERIMENT_DESIGN_GEO_TEST,
        start_date="2026-01-01",
        end_date="2026-02-01",
        market_scope=("US",),
        estimand="incremental_conversions_per_spend",
        observed_effect_estimate=1.2,
        effect_uncertainty=0.3,
        method="geo-holdout",
        source="internal",
        evidence_status="final",
    )
    defaults.update(overrides)
    return ExperimentRecord(**defaults)


def _full_compatibility(experiment_id: str = "geo-2026-01") -> CompatibilityAssessment:
    return assess_experiment_compatibility(
        experiment_id, {dim: True for dim in COMPATIBILITY_DIMENSIONS}
    )


# ---------------------------------------------------------------------------
# ExperimentRecord validation / round-trip / versioning
# ---------------------------------------------------------------------------


class TestExperimentRecordValidation:
    def test_requires_experiment_id(self):
        with pytest.raises(ValueError, match="experiment_id is required"):
            _record(experiment_id="")

    def test_rejects_invalid_design(self):
        with pytest.raises(ValueError, match="invalid design"):
            _record(design="not_a_design")

    def test_rejects_end_before_start(self):
        with pytest.raises(ValueError, match="end_date"):
            _record(start_date="2026-02-01", end_date="2026-01-01")

    def test_requires_market_scope(self):
        with pytest.raises(ValueError, match="market_scope is required"):
            _record(market_scope=())

    def test_rejects_negative_uncertainty(self):
        with pytest.raises(ValueError, match="effect_uncertainty"):
            _record(effect_uncertainty=-1.0)

    def test_round_trip(self):
        original = _record()
        restored = ExperimentRecord.from_dict(original.to_dict())
        assert restored == original


class TestExperimentVersioning:
    def test_new_version_increments(self):
        v1 = _record()
        v2 = new_experiment_version(v1, evidence_status="superseded")
        assert v2.experiment_version == 2
        assert v2.evidence_status == "superseded"
        assert v1.evidence_status == "final"

    def test_cannot_change_lineage_identity(self):
        v1 = _record()
        with pytest.raises(ValueError, match="lineage/version identity"):
            new_experiment_version(v1, experiment_id="other")

    def test_current_versions_resolves_highest_per_lineage(self):
        v1 = _record()
        v2 = new_experiment_version(v1, evidence_status="superseded")
        other = _record(experiment_id="holdout-2026-02")
        current = current_experiment_versions([v1, v2, other])
        by_id = {r.experiment_id: r for r in current}
        assert by_id["geo-2026-01"].experiment_version == 2
        assert by_id["holdout-2026-02"].experiment_version == 1


# ---------------------------------------------------------------------------
# CompatibilityAssessment
# ---------------------------------------------------------------------------


class TestCompatibilityAssessment:
    def test_requires_every_dimension(self):
        with pytest.raises(ValueError, match="missing required dimension"):
            assess_experiment_compatibility("e1", {"outcome": True})

    def test_rejects_unknown_dimension(self):
        with pytest.raises(ValueError, match="unknown dimension"):
            assess_experiment_compatibility(
                "e1",
                {dim: True for dim in COMPATIBILITY_DIMENSIONS} | {"extra": True},
            )

    def test_fully_compatible(self):
        assessment = _full_compatibility()
        assert assessment.is_fully_compatible is True
        assert assessment.incompatible_dimensions == ()

    def test_partially_incompatible(self):
        results = {dim: True for dim in COMPATIBILITY_DIMENSIONS}
        results["time_horizon"] = False
        assessment = assess_experiment_compatibility("e1", results)
        assert assessment.is_fully_compatible is False
        assert assessment.incompatible_dimensions == ("time_horizon",)

    def test_round_trip(self):
        original = _full_compatibility()
        restored = CompatibilityAssessment.from_dict(original.to_dict())
        assert restored == original


# ---------------------------------------------------------------------------
# ExperimentToModelUse validation
# ---------------------------------------------------------------------------


class TestExperimentToModelUse:
    def test_validation_only_needs_no_calibration_fields(self):
        use = ExperimentToModelUse(
            experiment_id="geo-2026-01",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
            model_id="model-a",
            model_version="v3",
        )
        assert use.evidence_mode == EVIDENCE_MODE_VALIDATION_ONLY

    def test_prior_calibration_requires_affected_prior(self):
        with pytest.raises(ValueError, match="prior_calibration requires"):
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
                model_id="model-a",
                model_version="v3",
            )

    def test_likelihood_calibration_requires_affected_term(self):
        with pytest.raises(ValueError, match="likelihood_calibration requires"):
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
                model_id="model-a",
                model_version="v3",
            )

    def test_rejects_invalid_evidence_mode(self):
        with pytest.raises(ValueError, match="invalid evidence_mode"):
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode="not_a_mode",
                model_id="model-a",
                model_version="v3",
            )

    def test_round_trip(self):
        original = ExperimentToModelUse(
            experiment_id="geo-2026-01",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_DIAGNOSTIC_COMPARISON,
            model_id="model-a",
            model_version="v3",
        )
        restored = ExperimentToModelUse.from_dict(original.to_dict())
        assert restored == original


# ---------------------------------------------------------------------------
# build_calibrating_use: fail-closed on incompatibility
# ---------------------------------------------------------------------------


class TestBuildCalibratingUse:
    def test_fully_compatible_builds_successfully(self):
        use = build_calibrating_use(
            _full_compatibility(),
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
            model_id="model-a",
            model_version="v3",
            affected_prior_name="tv_beta",
            affected_prior_version="v1",
        )
        assert use.evidence_mode == EVIDENCE_MODE_PRIOR_CALIBRATION

    def test_incompatible_experiment_is_rejected(self):
        results = {dim: True for dim in COMPATIBILITY_DIMENSIONS}
        results["outcome"] = False
        incompatible = assess_experiment_compatibility("geo-2026-01", results)
        with pytest.raises(ValueError, match="not fully compatible"):
            build_calibrating_use(
                incompatible,
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
                model_id="model-a",
                model_version="v3",
                affected_prior_name="tv_beta",
                affected_prior_version="v1",
            )

    def test_rejects_non_calibrating_evidence_mode(self):
        with pytest.raises(ValueError, match="only for"):
            build_calibrating_use(
                _full_compatibility(),
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
                model_id="model-a",
                model_version="v3",
            )


# ---------------------------------------------------------------------------
# Double-counting rule
# ---------------------------------------------------------------------------


class TestDoubleCountedDependence:
    def test_single_calibrating_mode_is_fine(self):
        uses = [
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
                model_id="model-a",
                model_version="v3",
                affected_prior_name="tv_beta",
                affected_prior_version="v1",
            )
        ]
        assert validate_no_double_counted_dependence(uses) == ()

    def test_both_modes_without_dependence_handling_is_flagged(self):
        uses = [
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
                model_id="model-a",
                model_version="v3",
                affected_prior_name="tv_beta",
                affected_prior_version="v1",
            ),
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
                model_id="model-a",
                model_version="v3",
                affected_likelihood_term_name="tv_calibration_term",
                affected_likelihood_term_version="v1",
            ),
        ]
        assert validate_no_double_counted_dependence(uses) == ("geo-2026-01",)

    def test_both_modes_with_dependence_handling_is_not_flagged(self):
        uses = [
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
                model_id="model-a",
                model_version="v3",
                affected_prior_name="tv_beta",
                affected_prior_version="v1",
                dependence_handling_method="joint_likelihood_adjustment",
            ),
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
                model_id="model-a",
                model_version="v3",
                affected_likelihood_term_name="tv_calibration_term",
                affected_likelihood_term_version="v1",
                dependence_handling_method="joint_likelihood_adjustment",
            ),
        ]
        assert validate_no_double_counted_dependence(uses) == ()

    def test_different_models_are_not_flagged_together(self):
        uses = [
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
                model_id="model-a",
                model_version="v3",
                affected_prior_name="tv_beta",
                affected_prior_version="v1",
            ),
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
                model_id="model-b",
                model_version="v1",
                affected_likelihood_term_name="tv_calibration_term",
                affected_likelihood_term_version="v1",
            ),
        ]
        assert validate_no_double_counted_dependence(uses) == ()

    def test_validation_only_uses_are_ignored(self):
        uses = [
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
                model_id="model-a",
                model_version="v3",
            ),
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_DIAGNOSTIC_COMPARISON,
                model_id="model-a",
                model_version="v3",
            ),
        ]
        assert validate_no_double_counted_dependence(uses) == ()


# ---------------------------------------------------------------------------
# Provenance report
# ---------------------------------------------------------------------------


class TestProvenanceReport:
    def test_reports_each_experiment_individually(self):
        record_a = _record("geo-2026-01")
        record_b = _record(
            "holdout-2026-02",
            design=EXPERIMENT_DESIGN_GEO_TEST,
            evidence_status="final",
        )
        uses = [
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
                model_id="model-a",
                model_version="v3",
            ),
            ExperimentToModelUse(
                experiment_id="holdout-2026-02",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_DIAGNOSTIC_COMPARISON,
                model_id="model-a",
                model_version="v3",
            ),
        ]
        report = build_provenance_report(
            "model-a",
            "v3",
            uses,
            {"geo-2026-01": record_a, "holdout-2026-02": record_b},
            portfolio_summary="2 experiments reviewed",
        )
        assert len(report.entries) == 2
        ids = {e.experiment_id for e in report.entries}
        assert ids == {"geo-2026-01", "holdout-2026-02"}
        assert report.portfolio_summary == "2 experiments reviewed"

    def test_filters_uses_for_other_models(self):
        record_a = _record("geo-2026-01")
        uses = [
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
                model_id="model-a",
                model_version="v3",
            ),
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
                model_id="model-b",
                model_version="v1",
            ),
        ]
        report = build_provenance_report(
            "model-a", "v3", uses, {"geo-2026-01": record_a}
        )
        assert len(report.entries) == 1

    def test_missing_record_raises(self):
        uses = [
            ExperimentToModelUse(
                experiment_id="geo-2026-01",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
                model_id="model-a",
                model_version="v3",
            )
        ]
        with pytest.raises(KeyError):
            build_provenance_report("model-a", "v3", uses, {})
