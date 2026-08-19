"""REQ-EVENT-001 (Work Package 1): contract tests for
`core.named_events` - governed identity, closed temporal-treatment
vocabulary, factual date preservation, reference validation, version
immutability, and deterministic fingerprints. No event-response
mathematics exists in this module; these tests assert the governance
contract only, and that nothing here derives classification or
treatment from free text."""

from __future__ import annotations

import pytest

from ancestry_mmm.core.named_events import (
    DEFAULT_EVENT_EVIDENCE_STATUS,
    EVENT_REGISTRY_SCHEMA_VERSION,
    EVENT_TREATMENTS,
    EventResponseDefinition,
    NamedEventFamily,
    NamedEventOccurrence,
    current_family_versions,
    current_occurrence_versions,
    current_response_definition_versions,
    fingerprint_event_family,
    fingerprint_event_occurrence,
    fingerprint_event_response_definition,
    new_family_version,
    new_occurrence_version,
    new_response_definition_version,
    registry_fingerprint,
    validate_registry_references,
)


def _family(**overrides):
    values = {
        "family_id": "mothers_day",
        "family_version": 1,
        "display_name": "Mother's Day",
        "classification": "gifting",
        "classification_status": DEFAULT_EVENT_EVIDENCE_STATUS,
        "market_scope": ("UK",),
    }
    values.update(overrides)
    return NamedEventFamily(**values)


def _occurrence(**overrides):
    values = {
        "event_id": "md-2026",
        "event_version": 1,
        "display_name": "Mother's Day 2026",
        "start_date": "2026-03-22",
        "end_date": "2026-03-22",
        "market_scope": ("UK",),
        "source_id": "events",
    }
    values.update(overrides)
    return NamedEventOccurrence(**values)


def _definition(**overrides):
    values = {
        "response_definition_id": "md-def",
        "response_definition_version": 1,
        "family_id": "mothers_day",
        "treatment": "anticipatory",
        "max_lead": 3,
        "max_lag": 0,
        "transformation_method_reference": "governed-ref-pending-approval",
    }
    values.update(overrides)
    return EventResponseDefinition(**values)


class TestClosedTemporalVocabulary:
    def test_closed_vocabulary_is_exactly_four_treatments(self):
        assert EVENT_TREATMENTS == (
            "contemporaneous",
            "anticipatory",
            "post_event",
            "anticipatory_and_post_event",
        )

    @pytest.mark.parametrize("treatment", EVENT_TREATMENTS)
    def test_every_governed_treatment_is_constructible(self, treatment):
        definition = _definition(treatment=treatment)
        assert definition.treatment == treatment

    def test_unknown_treatment_is_rejected(self):
        with pytest.raises(ValueError, match="invalid treatment"):
            _definition(treatment="reverse_adstock")
        with pytest.raises(ValueError, match="invalid treatment"):
            _definition(treatment="weekly_lead_dummies")

    def test_negative_support_windows_are_rejected(self):
        with pytest.raises(ValueError, match="max_lead must be >= 0"):
            _definition(max_lead=-1)
        with pytest.raises(ValueError, match="max_lag must be >= 0"):
            _definition(max_lag=-1)


class TestFactualDatePreservation:
    def test_occurrence_dates_round_trip_verbatim(self):
        occurrence = _occurrence(start_date="2026-03-22", end_date="2026-03-22")
        restored = NamedEventOccurrence.from_dict(occurrence.to_dict())
        assert restored.start_date == "2026-03-22"
        assert restored.end_date == "2026-03-22"

    def test_multi_day_interval_round_trips_verbatim(self):
        occurrence = _occurrence(start_date="2026-12-21", end_date="2026-12-27")
        restored = NamedEventOccurrence.from_dict(occurrence.to_dict())
        assert restored.start_date == "2026-12-21"
        assert restored.end_date == "2026-12-27"

    def test_inverted_interval_is_rejected(self):
        with pytest.raises(ValueError, match="before its start date"):
            _occurrence(start_date="2026-03-25", end_date="2026-03-20")

    def test_unparseable_dates_are_rejected(self):
        with pytest.raises(ValueError, match="unparseable"):
            _occurrence(start_date="not-a-date", end_date="2026-03-22")

    def test_no_module_api_shifts_dates(self):
        """The occurrence record has no method or field that rewrites
        factual dates - date mutation is impossible at this layer."""
        occurrence = _occurrence(start_date="2026-03-22")
        assert "shift" not in dir(occurrence)
        assert "normalise" not in dir(occurrence)
        assert "normalize" not in dir(occurrence)


class TestNoTextInference:
    def test_family_classification_is_explicitly_supplied(self):
        """No constructor derives classification from display_name."""
        with pytest.raises(TypeError):
            NamedEventFamily(  # type: ignore[call-arg]
                family_id="mothers_day",
                family_version=1,
                display_name="Mother's Day",
            )
        family = _family(display_name="Mother's Day", classification="gifting")
        assert family.classification == "gifting"
        assert family.display_name == "Mother's Day"

    def test_gifting_name_never_implies_gifting_classification(self):
        """The same text with a different governed classification stays
        exactly what was supplied - nothing reinterprets the label."""
        family = _family(display_name="Mother's Day", classification="commercial")
        assert family.classification == "commercial"

    def test_occurrence_carries_no_classification_or_treatment(self):
        occurrence = _occurrence(display_name="Mother's Day 2026")
        assert not hasattr(occurrence, "classification")
        assert not hasattr(occurrence, "treatment")
        assert occurrence.display_name == "Mother's Day 2026"


class TestReferenceValidation:
    def test_definition_must_reference_a_registered_family(self):
        problems = validate_registry_references(
            [_family()], [_occurrence()], [_definition(family_id="missing")]
        )
        assert any("references family 'missing'" in p for p in problems)

    def test_occurrence_family_link_must_reference_a_registered_family(self):
        problems = validate_registry_references(
            [_family()],
            [_occurrence(family_id="missing")],
            [_definition()],
        )
        assert any("'md-2026'" in p and "'missing'" in p for p in problems)

    def test_unmapped_occurrence_is_not_a_problem(self):
        problems = validate_registry_references(
            [_family()], [_occurrence(family_id=None)], [_definition()]
        )
        assert problems == ()

    def test_consistent_registry_has_no_problems(self):
        problems = validate_registry_references(
            [_family()],
            [_occurrence(family_id="mothers_day")],
            [_definition()],
        )
        assert problems == ()


class TestVersionImmutability:
    def test_new_family_version_increments_and_locks_identity(self):
        versioned = new_family_version(_family(), classification="commercial")
        assert versioned.family_version == 2
        assert versioned.classification == "commercial"
        with pytest.raises(ValueError, match="lineage/version identity"):
            new_family_version(_family(), family_id="other")

    def test_new_occurrence_version_increments_and_locks_identity(self):
        versioned = new_occurrence_version(_occurrence(), family_id="mothers_day")
        assert versioned.event_version == 2
        assert versioned.family_id == "mothers_day"
        with pytest.raises(ValueError, match="lineage/version identity"):
            new_occurrence_version(_occurrence(), event_id="other")

    def test_new_definition_version_increments_and_locks_identity(self):
        versioned = new_response_definition_version(_definition(), max_lead=4)
        assert versioned.response_definition_version == 2
        assert versioned.max_lead == 4
        with pytest.raises(ValueError, match="lineage/version identity"):
            new_response_definition_version(
                _definition(), response_definition_id="other"
            )

    def test_current_versions_pick_the_highest(self):
        v2 = new_family_version(_family(), classification="commercial")
        current = current_family_versions([_family(), v2])
        assert [family.family_version for family in current] == [2]
        v2_occurrence = new_occurrence_version(_occurrence(), family_id="mothers_day")
        assert [
            o.event_version
            for o in current_occurrence_versions([_occurrence(), v2_occurrence])
        ] == [2]
        v2_definition = new_response_definition_version(_definition(), max_lead=4)
        assert [
            d.response_definition_version
            for d in current_response_definition_versions(
                [_definition(), v2_definition]
            )
        ] == [2]


class TestFingerprints:
    def test_family_fingerprint_is_deterministic(self):
        assert fingerprint_event_family(_family()) == fingerprint_event_family(
            _family()
        )

    def test_family_display_name_does_not_change_fingerprint(self):
        assert fingerprint_event_family(
            _family(display_name="Mother's Day")
        ) == fingerprint_event_family(_family(display_name="Mothers Day 2026"))

    def test_family_classification_change_changes_fingerprint(self):
        assert fingerprint_event_family(
            _family(classification="gifting")
        ) != fingerprint_event_family(_family(classification="commercial"))

    def test_occurrence_fingerprint_is_deterministic(self):
        assert fingerprint_event_occurrence(
            _occurrence()
        ) == fingerprint_event_occurrence(_occurrence())

    def test_occurrence_display_name_does_not_change_fingerprint(self):
        assert fingerprint_event_occurrence(
            _occurrence(display_name="Mother's Day 2026")
        ) == fingerprint_event_occurrence(_occurrence(display_name="MD26"))

    def test_occurrence_factual_date_change_changes_fingerprint(self):
        assert fingerprint_event_occurrence(
            _occurrence(end_date="2026-03-22")
        ) != fingerprint_event_occurrence(_occurrence(end_date="2026-03-25"))

    def test_occurrence_family_link_change_changes_fingerprint(self):
        assert fingerprint_event_occurrence(
            _occurrence(family_id=None)
        ) != fingerprint_event_occurrence(_occurrence(family_id="mothers_day"))

    def test_definition_fingerprint_is_deterministic(self):
        assert fingerprint_event_response_definition(
            _definition()
        ) == fingerprint_event_response_definition(_definition())

    @pytest.mark.parametrize(
        "change",
        [
            {"treatment": "post_event"},
            {"max_lead": 5},
            {"max_lag": 2},
            {"transformation_method_reference": "other-governed-ref"},
            {"transformation_version": 2},
            {"family_id": "other_family"},
        ],
    )
    def test_definition_governed_field_changes_fingerprint(self, change):
        assert fingerprint_event_response_definition(
            _definition()
        ) != fingerprint_event_response_definition(_definition(**change))

    def test_registry_fingerprint_is_deterministic(self):
        left = registry_fingerprint([_family()], [_occurrence()], [_definition()])
        right = registry_fingerprint([_family()], [_occurrence()], [_definition()])
        assert left == right

    def test_registry_fingerprint_changes_when_any_current_record_changes(self):
        base = registry_fingerprint([_family()], [_occurrence()], [_definition()])
        assert (
            registry_fingerprint(
                [_family(classification="commercial")],
                [_occurrence()],
                [_definition()],
            )
            != base
        )
        assert (
            registry_fingerprint(
                [_family()],
                [_occurrence(end_date="2026-03-25")],
                [_definition()],
            )
            != base
        )
        assert (
            registry_fingerprint(
                [_family()], [_occurrence()], [_definition(max_lead=5)]
            )
            != base
        )

    def test_registry_schema_version_is_one(self):
        assert EVENT_REGISTRY_SCHEMA_VERSION == 1
