"""Work Package 2 (`Media-Mix-Lab: Coding LLM Next Steps After PR #291`):
tests for `application.experiment_service` - the durable Experiment
Evidence adoption boundary between uploaded source rows and the governed
experiment registry (`core.experiments`). No calibration mathematics
exists anywhere in this service, and these tests assert that boundary
behaviour: adoption is explicit, the registry is immutable, calibrating
uses fail closed, and provenance is per experiment."""

from __future__ import annotations

import pytest

from ancestry_mmm.application.experiment_service import (
    DEFAULT_EVIDENCE_STATUS,
    adopt_experiment_record,
    build_compatibility_assessment,
    missing_adoption_fields,
    new_registered_experiment_version,
    provenance_for_model,
    register_experiment_record,
    register_model_use,
    registry_has_content,
    registry_to_dict,
)
from ancestry_mmm.core.experiments import (
    COMPATIBILITY_DIMENSIONS,
    EVIDENCE_MODE_DIAGNOSTIC_COMPARISON,
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
    EVIDENCE_MODE_PRIOR_CALIBRATION,
    EVIDENCE_MODE_VALIDATION_ONLY,
    EXPERIMENT_DESIGN_GEO_TEST,
    EXPERIMENT_REGISTRY_SCHEMA_VERSION,
    ExperimentRecord,
)


def _source_row(**overrides):
    row = {
        "experiment_id": "exp-geo-1",
        "activity_id": "TV_Brand",
        "market": "UK",
        "start_date": "2026-01-05",
        "end_date": "2026-02-01",
    }
    row.update(overrides)
    return row


def _full_analyst_input(**overrides):
    analyst = {
        "design": EXPERIMENT_DESIGN_GEO_TEST,
        "estimand": "incremental GSA acquisitions",
        "observed_effect_estimate": 0.12,
        "effect_uncertainty": 0.04,
        "method": "difference-in-differences",
        "source": "geo-test platform export",
        "evidence_status": DEFAULT_EVIDENCE_STATUS,
    }
    analyst.update(overrides)
    return analyst


def _adopt(**row_overrides):
    return adopt_experiment_record(_source_row(**row_overrides), _full_analyst_input())


def _full_compatibility(experiment_id: str = "exp-geo-1"):
    return build_compatibility_assessment(
        experiment_id,
        {dimension: True for dimension in COMPATIBILITY_DIMENSIONS},
    )


class TestAdoptionBoundary:
    def test_missing_fields_are_reported_and_nothing_is_adopted(self):
        assert missing_adoption_fields(_source_row(), _full_analyst_input()) == ()
        missing = missing_adoption_fields(
            _source_row(market=""), _full_analyst_input(estimand="")
        )
        assert "market" in missing
        assert "estimand" in missing
        with pytest.raises(ValueError, match="missing required field"):
            adopt_experiment_record(
                _source_row(market=""), _full_analyst_input(estimand="")
            )

    def test_source_row_adopts_into_a_version_1_record(self):
        record = _adopt()
        assert record.experiment_id == "exp-geo-1"
        assert record.experiment_version == 1
        assert record.market_scope == ("UK",)
        assert record.metadata == {"activity_id": "TV_Brand"}
        assert record.observed_effect_estimate == 0.12
        assert record.evidence_status == DEFAULT_EVIDENCE_STATUS

    def test_invalid_analyst_values_are_rejected_by_the_record_contract(self):
        with pytest.raises(ValueError, match="invalid design"):
            _adopt()
            adopt_experiment_record(
                _source_row(), _full_analyst_input(design="not_a_design")
            )
        with pytest.raises(ValueError, match="effect_uncertainty cannot be negative"):
            adopt_experiment_record(
                _source_row(), _full_analyst_input(effect_uncertainty=-1.0)
            )


class TestRegistryImmutability:
    def test_re_adopting_identical_content_is_idempotent(self):
        first = _adopt()
        registry = register_experiment_record((), first)
        second = _adopt()
        assert register_experiment_record(registry, second) == registry

    def test_re_adopting_different_content_raises_never_mutates(self):
        first = _adopt()
        registry = register_experiment_record((), first)
        changed = adopt_experiment_record(
            _source_row(), _full_analyst_input(observed_effect_estimate=0.5)
        )
        with pytest.raises(ValueError, match="create a new version"):
            register_experiment_record(registry, changed)

    def test_new_version_increments_and_preserves_history(self):
        first = _adopt()
        registry = register_experiment_record((), first)
        updated = new_registered_experiment_version(
            registry,
            "exp-geo-1",
            observed_effect_estimate=0.5,
        )
        assert len(updated) == 2
        assert updated[0].experiment_version == 1
        assert updated[1].experiment_version == 2
        assert updated[1].observed_effect_estimate == 0.5

    def test_new_version_for_unknown_experiment_raises(self):
        with pytest.raises(ValueError, match="not registered"):
            new_registered_experiment_version((), "missing-id")


class TestRegisterModelUse:
    def _registry(self):
        return register_experiment_record((), _adopt())

    def test_validation_only_use_needs_no_compatibility(self):
        uses = register_model_use(
            self._registry(),
            (),
            experiment_id="exp-geo-1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
            model_id="run-1",
            model_version="spec-fp",
        )
        assert uses[-1].evidence_mode == EVIDENCE_MODE_VALIDATION_ONLY

    def test_diagnostic_comparison_use_needs_no_compatibility(self):
        uses = register_model_use(
            self._registry(),
            (),
            experiment_id="exp-geo-1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_DIAGNOSTIC_COMPARISON,
            model_id="run-1",
            model_version="spec-fp",
        )
        assert uses[-1].evidence_mode == EVIDENCE_MODE_DIAGNOSTIC_COMPARISON

    def test_calibrating_use_requires_a_compatibility_assessment(self):
        with pytest.raises(ValueError, match="requires a compatibility"):
            register_model_use(
                self._registry(),
                (),
                experiment_id="exp-geo-1",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
                model_id="run-1",
                model_version="spec-fp",
                affected_prior_name="beta",
                affected_prior_version="v1",
            )

    def test_calibrating_use_fails_on_incompatible_experiment(self):
        incompatible = build_compatibility_assessment(
            "exp-geo-1",
            {dimension: False for dimension in COMPATIBILITY_DIMENSIONS},
        )
        with pytest.raises(ValueError, match="not fully compatible"):
            register_model_use(
                self._registry(),
                (),
                experiment_id="exp-geo-1",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
                model_id="run-1",
                model_version="spec-fp",
                compatibility=incompatible,
                affected_prior_name="beta",
                affected_prior_version="v1",
            )

    def test_calibrating_use_succeeds_when_compatible(self):
        uses = register_model_use(
            self._registry(),
            (),
            experiment_id="exp-geo-1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
            model_id="run-1",
            model_version="spec-fp",
            compatibility=_full_compatibility(),
            affected_prior_name="beta",
            affected_prior_version="v1",
        )
        assert uses[-1].evidence_mode == EVIDENCE_MODE_PRIOR_CALIBRATION

    def test_mismatched_compatibility_experiment_is_rejected(self):
        wrong = build_compatibility_assessment(
            "some-other-experiment",
            {dimension: True for dimension in COMPATIBILITY_DIMENSIONS},
        )
        with pytest.raises(ValueError, match="not 'exp-geo-1'"):
            register_model_use(
                self._registry(),
                (),
                experiment_id="exp-geo-1",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
                model_id="run-1",
                model_version="spec-fp",
                compatibility=wrong,
                affected_prior_name="beta",
                affected_prior_version="v1",
            )

    def test_unknown_experiment_version_is_rejected(self):
        with pytest.raises(ValueError, match="not registered"):
            register_model_use(
                self._registry(),
                (),
                experiment_id="exp-geo-1",
                experiment_version=99,
                evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
                model_id="run-1",
                model_version="spec-fp",
            )

    def test_unknown_evidence_mode_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown evidence mode"):
            register_model_use(
                self._registry(),
                (),
                experiment_id="exp-geo-1",
                experiment_version=1,
                evidence_mode="calibration_magic",
                model_id="run-1",
                model_version="spec-fp",
            )


class TestDoubleCountedDependenceFailsClosed:
    def _registry(self):
        return register_experiment_record((), _adopt())

    def test_two_calibrating_modes_without_handling_are_rejected(self):
        uses = register_model_use(
            self._registry(),
            (),
            experiment_id="exp-geo-1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
            model_id="run-1",
            model_version="spec-fp",
            compatibility=_full_compatibility(),
            affected_prior_name="beta",
            affected_prior_version="v1",
        )
        with pytest.raises(ValueError, match="double-counted dependence"):
            register_model_use(
                self._registry(),
                uses,
                experiment_id="exp-geo-1",
                experiment_version=1,
                evidence_mode=EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
                model_id="run-1",
                model_version="spec-fp",
                compatibility=_full_compatibility(),
                affected_likelihood_term_name="likelihood",
                affected_likelihood_term_version="v1",
            )

    def test_two_calibrating_modes_with_explicit_handling_are_registered(self):
        uses = register_model_use(
            self._registry(),
            (),
            experiment_id="exp-geo-1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_PRIOR_CALIBRATION,
            model_id="run-1",
            model_version="spec-fp",
            compatibility=_full_compatibility(),
            affected_prior_name="beta",
            affected_prior_version="v1",
        )
        uses = register_model_use(
            self._registry(),
            uses,
            experiment_id="exp-geo-1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
            model_id="run-1",
            model_version="spec-fp",
            compatibility=_full_compatibility(),
            affected_likelihood_term_name="likelihood",
            affected_likelihood_term_version="v1",
            dependence_handling_method="shared-evidence-partition",
        )
        assert uses[-1].dependence_handling_method == "shared-evidence-partition"


class TestProvenanceForModel:
    def _registry(self):
        return register_experiment_record((), _adopt())

    def test_no_uses_returns_none_never_an_empty_report(self):
        assert (
            provenance_for_model(
                self._registry(), (), model_id="run-1", model_version="spec-fp"
            )
            is None
        )

    def test_uses_build_a_per_experiment_report(self):
        uses = register_model_use(
            self._registry(),
            (),
            experiment_id="exp-geo-1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
            model_id="run-1",
            model_version="spec-fp",
        )
        report = provenance_for_model(
            self._registry(),
            uses,
            model_id="run-1",
            model_version="spec-fp",
        )
        assert report is not None
        assert len(report.entries) == 1
        assert report.entries[0].experiment_id == "exp-geo-1"
        assert report.entries[0].estimand == "incremental GSA acquisitions"

    def test_other_models_uses_do_not_leak_into_the_report(self):
        uses = register_model_use(
            self._registry(),
            (),
            experiment_id="exp-geo-1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
            model_id="run-1",
            model_version="spec-fp",
        )
        assert (
            provenance_for_model(
                self._registry(),
                uses,
                model_id="run-2",
                model_version="other-spec",
            )
            is None
        )


class TestRegistrySerialisation:
    def _registry(self):
        return register_experiment_record((), _adopt())

    def test_round_trips_and_records_its_schema_version(self):
        uses = register_model_use(
            self._registry(),
            (),
            experiment_id="exp-geo-1",
            experiment_version=1,
            evidence_mode=EVIDENCE_MODE_VALIDATION_ONLY,
            model_id="run-1",
            model_version="spec-fp",
        )
        payload = registry_to_dict(
            self._registry(),
            uses,
            (_full_compatibility(),),
            [_source_row()],
        )
        assert payload["schema_version"] == EXPERIMENT_REGISTRY_SCHEMA_VERSION
        assert ExperimentRecord.from_dict(payload["records"][0]) is not None

    def test_has_content_reflects_emptiness(self):
        assert not registry_has_content((), (), (), ())
        assert registry_has_content(self._registry(), (), (), ())

    def test_no_calibration_math_exists_in_the_service(self):
        """REQ-CALIB-001 requirement 3 and this package's own boundary:
        the adoption service must not contain any calibration computation
        - no likelihood translation, no prior rewriting, no pseudo-
        calibration fields."""
        import inspect

        import ancestry_mmm.application.experiment_service as service

        source = inspect.getsource(service)
        for forbidden in (
            "calibrate",
            "recalibrate",
            "adjusted_likelihood",
            "posterior_scale",
        ):
            assert forbidden not in source.lower(), forbidden
