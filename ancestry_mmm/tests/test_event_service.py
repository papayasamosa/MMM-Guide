"""REQ-EVENT-001 (Work Package 1): tests for
`application.event_service` - the governed named-event adoption boundary
between uploaded Context `events` rows and the registry
(`core.named_events`). Adoption is explicit, the registry is immutable,
factual dates are preserved, and nothing derives classification or
treatment from an event name."""

from __future__ import annotations

import pytest

from ancestry_mmm.application.event_service import (
    adopt_source_event_occurrence,
    missing_occurrence_adoption_fields,
    new_family,
    new_registered_family_version,
    new_registered_occurrence_version,
    new_registered_response_definition_version,
    new_response_definition,
    register_family,
    register_occurrence,
    register_response_definition,
    registry_has_content,
    registry_problems,
    registry_to_dict,
)
from ancestry_mmm.core.named_events import (
    DEFAULT_EVENT_EVIDENCE_STATUS,
    EVENT_REGISTRY_SCHEMA_VERSION,
)


def _source_row(**overrides):
    row = {
        "event_id": "md-2026",
        "event_name": "Mother's Day 2026",
        "start_date": "2026-03-22",
        "end_date": "2026-03-22",
    }
    row.update(overrides)
    return row


def _analyst_input(**overrides):
    analyst = {
        "market": ["UK"],
        "source_id": "events",
        "source_version": 1,
    }
    analyst.update(overrides)
    return analyst


def _adopt(**overrides):
    return adopt_source_event_occurrence(_source_row(), _analyst_input(**overrides))


class TestAdoptionBoundary:
    def test_missing_fields_are_reported_and_nothing_is_adopted(self):
        assert missing_occurrence_adoption_fields(_source_row(), _analyst_input()) == ()
        missing = missing_occurrence_adoption_fields(
            _source_row(end_date=""), _analyst_input(market=[], source_id="")
        )
        assert "end_date" in missing
        assert "market" in missing
        assert "source_id" in missing
        with pytest.raises(ValueError, match="missing required field"):
            adopt_source_event_occurrence(
                _source_row(end_date=""), _analyst_input(market=[], source_id="")
            )

    def test_source_row_adopts_into_a_version_1_occurrence(self):
        occurrence = _adopt()
        assert occurrence.event_id == "md-2026"
        assert occurrence.event_version == 1
        assert occurrence.start_date == "2026-03-22"
        assert occurrence.end_date == "2026-03-22"
        assert occurrence.market_scope == ("UK",)
        assert occurrence.source_id == "events"
        assert occurrence.source_version == 1
        assert occurrence.family_id is None

    def test_factual_dates_are_preserved_verbatim(self):
        occurrence = _adopt()
        assert occurrence.start_date == _source_row()["start_date"]
        assert occurrence.end_date == _source_row()["end_date"]

    def test_family_link_is_only_what_the_analyst_supplied(self):
        occurrence = _adopt(family_id="mothers_day")
        assert occurrence.family_id == "mothers_day"
        assert _adopt().family_id is None

    def test_no_classification_or_treatment_is_derived(self):
        """Adopting a row named like a gifting occasion must produce no
        classification or treatment anywhere on the record."""
        occurrence = _adopt()
        assert not hasattr(occurrence, "classification")
        assert not hasattr(occurrence, "treatment")
        assert occurrence.display_name == "Mother's Day 2026"


class TestRegistryImmutability:
    def test_re_adopting_identical_content_is_idempotent(self):
        first = _adopt()
        registry = register_occurrence((), first)
        second = _adopt()
        assert register_occurrence(registry, second) == registry

    def test_re_adopting_different_content_raises_never_mutates(self):
        first = _adopt()
        registry = register_occurrence((), first)
        changed = adopt_source_event_occurrence(
            _source_row(end_date="2026-03-25"), _analyst_input()
        )
        with pytest.raises(ValueError, match="already registered"):
            register_occurrence(registry, changed)

    def test_new_occurrence_version_registers_without_mutation(self):
        registry = register_occurrence((), _adopt())
        versioned = new_registered_occurrence_version(
            registry, "md-2026", family_id="mothers_day"
        )
        assert len(versioned) == 2
        assert versioned[0].event_version == 1
        assert versioned[1].event_version == 2
        assert versioned[1].family_id == "mothers_day"

    def test_new_version_of_unregistered_occurrence_raises(self):
        with pytest.raises(ValueError, match="not registered"):
            new_registered_occurrence_version((), "md-2026", family_id="x")

    def test_family_registry_is_immutable(self):
        family = new_family(
            family_id="mothers_day",
            display_name="Mother's Day",
            classification="gifting",
        )
        registry = register_family((), family)
        assert register_family(registry, family) == registry
        changed = new_family(
            family_id="mothers_day",
            display_name="Mother's Day",
            classification="commercial",
        )
        with pytest.raises(ValueError, match="already registered"):
            register_family(registry, changed)
        versioned = new_registered_family_version(
            registry, "mothers_day", classification="commercial"
        )
        assert len(versioned) == 2
        assert versioned[1].classification == "commercial"

    def test_definition_registry_is_immutable(self):
        definition = new_response_definition(
            response_definition_id="md-def",
            family_id="mothers_day",
            treatment="anticipatory",
            max_lead=3,
            max_lag=0,
            transformation_method_reference="governed-ref",
        )
        registry = register_response_definition((), definition)
        assert register_response_definition(registry, definition) == registry
        changed = new_response_definition(
            response_definition_id="md-def",
            family_id="mothers_day",
            treatment="post_event",
            max_lead=0,
            max_lag=2,
            transformation_method_reference="governed-ref",
        )
        with pytest.raises(ValueError, match="already registered"):
            register_response_definition(registry, changed)
        versioned = new_registered_response_definition_version(
            registry, "md-def", max_lead=4
        )
        assert len(versioned) == 2
        assert versioned[1].max_lead == 4


class TestRegistrySerialisation:
    def test_registry_to_dict_has_schema_version_and_parts(self):
        family = new_family(
            family_id="mothers_day",
            display_name="Mother's Day",
            classification="gifting",
        )
        occurrence = _adopt(family_id="mothers_day")
        definition = new_response_definition(
            response_definition_id="md-def",
            family_id="mothers_day",
            treatment="anticipatory",
            max_lead=3,
            max_lag=0,
            transformation_method_reference="governed-ref",
        )
        payload = registry_to_dict([family], [occurrence], [definition])
        assert payload["schema_version"] == EVENT_REGISTRY_SCHEMA_VERSION
        assert payload["families"][0]["family_id"] == "mothers_day"
        assert payload["occurrences"][0]["start_date"] == "2026-03-22"
        assert payload["response_definitions"][0]["treatment"] == "anticipatory"

    def test_registry_has_content(self):
        family = new_family(
            family_id="mothers_day",
            display_name="Mother's Day",
            classification="gifting",
        )
        assert registry_has_content([family], [], [])
        assert not registry_has_content([], [], [])

    def test_registry_problems_surface_reference_errors(self):
        definition = new_response_definition(
            response_definition_id="md-def",
            family_id="missing",
            treatment="anticipatory",
            max_lead=3,
            max_lag=0,
            transformation_method_reference="governed-ref",
        )
        problems = registry_problems([], [_adopt()], [definition])
        assert any("references family 'missing'" in p for p in problems)

    def test_default_evidence_status_is_review_required(self):
        assert DEFAULT_EVENT_EVIDENCE_STATUS == "draft_review_required"
        definition = new_response_definition(
            response_definition_id="md-def",
            family_id="mothers_day",
            treatment="contemporaneous",
            max_lead=0,
            max_lag=0,
            transformation_method_reference="governed-ref",
        )
        assert definition.evidence_status == DEFAULT_EVENT_EVIDENCE_STATUS
