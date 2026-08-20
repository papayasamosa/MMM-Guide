"""Governed named-event adoption boundary (Work Package 1 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR #297`, `REQ-EVENT-001`).

Connects the optional Context `events` source table (the raw
`event_id`/`event_name`/`start_date`/`end_date` groundwork in
`data.templates`) to the governed named-event registry
(`core.named_events`) and the project lifecycle - without implementing
any event-response mathematics.

Contract summary:

- an uploaded Context events row never becomes a governed occurrence
  automatically: the analyst explicitly adopts it at this boundary;
- the source row supplies identity (`event_id`), the factual interval
  (`start_date`/`end_date`, preserved verbatim - never shifted) and a
  free-text display label (`event_name`) only;
- market scope, source lineage and the optional family link are
  analyst-supplied, never invented - and event-family classification,
  temporal treatment and lead/lag support are **never** inferred from
  `event_name` (no code path here derives them from text);
- the registry is immutable and lineage-versioned; every edit is a new
  version, never an in-place mutation;
- response definitions reference a registered family and use exactly
  the closed four-value temporal-treatment vocabulary;
- nothing in this service computes event-relative features or consumes
  `transformation_method_reference` to build a model component.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Tuple, TypeVar

from ancestry_mmm.core.named_events import (
    DEFAULT_EVENT_EVIDENCE_STATUS,
    EVENT_REGISTRY_SCHEMA_VERSION,
    EventResponseDefinition,
    NamedEventFamily,
    NamedEventOccurrence,
    current_family_versions,
    current_occurrence_versions,
    current_response_definition_versions,
    new_family_version,
    new_occurrence_version,
    new_response_definition_version,
    validate_registry_references,
)

# Source-row columns the standard Context `events` template carries.
_SOURCE_ROW_COLUMNS = ("event_id", "event_name", "start_date", "end_date")

# Occurrence fields a raw source events row can never supply by itself
# (the template carries no market or lineage columns). They are required
# by the record contract and must be analyst-supplied at this boundary -
# never invented, defaulted, or zero-filled.
ANALYST_REQUIRED_FIELDS = ("market", "source_id")


def missing_occurrence_adoption_fields(
    row: Mapping[str, Any], analyst_input: Mapping[str, Any]
) -> Tuple[str, ...]:
    """The field names that still block adopting `row` into a full
    `NamedEventOccurrence`. Source-row-derived fields are checked against
    the row itself; the remaining required fields against the analyst's
    input. Never returns a fabricated default as if it were supplied."""
    missing = []
    for column in _SOURCE_ROW_COLUMNS:
        if not row.get(column):
            missing.append(column)
    for field in ANALYST_REQUIRED_FIELDS:
        if not analyst_input.get(field):
            missing.append(field)
    return tuple(missing)


def adopt_source_event_occurrence(
    row: Mapping[str, Any],
    analyst_input: Mapping[str, Any],
) -> NamedEventOccurrence:
    """Adopt one Context events row into a governed, version-1
    `NamedEventOccurrence`. Raises `ValueError` listing every missing
    required field - the row is never adopted with a fabricated value.

    The source row supplies identity and the factual interval only.
    `event_name` becomes the free-text `display_name`; it is never used
    to derive classification, treatment or support - no such derivation
    exists anywhere in this module."""
    missing = missing_occurrence_adoption_fields(row, analyst_input)
    if missing:
        raise ValueError(
            "Cannot adopt this event occurrence row - missing required "
            f"field(s): {', '.join(missing)}."
        )
    family_id = analyst_input.get("family_id") or None
    return NamedEventOccurrence(
        event_id=str(row["event_id"]),
        event_version=1,
        display_name=str(row["event_name"]),
        start_date=str(row["start_date"]),
        end_date=str(row["end_date"]),
        market_scope=tuple(str(m) for m in analyst_input["market"]),
        source_id=str(analyst_input["source_id"]),
        source_version=(
            int(analyst_input["source_version"])
            if analyst_input.get("source_version") is not None
            else None
        ),
        family_id=family_id,
    )


def new_family(
    *,
    family_id: str,
    display_name: str,
    classification: str,
    market_scope: Sequence[str] = (),
    product_scope: Sequence[str] = (),
    outcome_scope: Sequence[str] = (),
    classification_status: str = DEFAULT_EVENT_EVIDENCE_STATUS,
    metadata: Optional[Mapping[str, Any]] = None,
) -> NamedEventFamily:
    """Construct a governed, version-1 event family. `classification` is
    the analyst-supplied governed classification - this function never
    derives it from `display_name` or any other text."""
    return NamedEventFamily(
        family_id=str(family_id),
        family_version=1,
        display_name=str(display_name),
        classification=str(classification),
        classification_status=str(classification_status),
        market_scope=tuple(market_scope),
        product_scope=tuple(product_scope),
        outcome_scope=tuple(outcome_scope),
        metadata=dict(metadata or {}),
    )


def new_response_definition(
    *,
    response_definition_id: str,
    family_id: str,
    treatment: str,
    max_lead: int,
    max_lag: int,
    transformation_method_reference: str,
    market_scope: Sequence[str] = (),
    product_scope: Sequence[str] = (),
    outcome_scope: Sequence[str] = (),
    evidence_status: str = DEFAULT_EVENT_EVIDENCE_STATUS,
    metadata: Optional[Mapping[str, Any]] = None,
) -> EventResponseDefinition:
    """Construct a governed, version-1 response definition. `treatment`
    must be one of the closed four-value vocabulary (validated by the
    record); the transformation-method reference is an opaque governed
    string - no kernel is selected here."""
    return EventResponseDefinition(
        response_definition_id=str(response_definition_id),
        response_definition_version=1,
        family_id=str(family_id),
        treatment=str(treatment),
        max_lead=int(max_lead),
        max_lag=int(max_lag),
        transformation_method_reference=str(transformation_method_reference),
        market_scope=tuple(market_scope),
        product_scope=tuple(product_scope),
        outcome_scope=tuple(outcome_scope),
        evidence_status=str(evidence_status),
        metadata=dict(metadata or {}),
    )


def register_family(
    records: Sequence[NamedEventFamily], record: NamedEventFamily
) -> Tuple[NamedEventFamily, ...]:
    """Append a family to the registry. Re-registering content identical
    (version ignored) to the current version is an idempotent no-op;
    differing content raises - the registry is immutable, so an edit is a
    new version via `new_registered_family_version`, never a mutation."""
    return _register(
        records, record, "family_id", "family_version", current_family_versions
    )


def register_occurrence(
    records: Sequence[NamedEventOccurrence], record: NamedEventOccurrence
) -> Tuple[NamedEventOccurrence, ...]:
    """Append an occurrence to the registry (immutability contract
    identical to `register_family`)."""
    return _register(
        records, record, "event_id", "event_version", current_occurrence_versions
    )


def register_response_definition(
    records: Sequence[EventResponseDefinition], record: EventResponseDefinition
) -> Tuple[EventResponseDefinition, ...]:
    """Append a response definition to the registry (immutability
    contract identical to `register_family`)."""
    return _register(
        records,
        record,
        "response_definition_id",
        "response_definition_version",
        current_response_definition_versions,
    )


_RecordT = TypeVar("_RecordT")


def _register(
    records: Sequence[_RecordT],
    record: _RecordT,
    id_field: str,
    version_field: str,
    current_fn: Any,
) -> Tuple[_RecordT, ...]:
    current = {getattr(rec, id_field): rec for rec in current_fn(records)}
    existing = current.get(getattr(record, id_field))
    if existing is not None:
        existing_dict = dict(getattr(existing, "to_dict")())
        incoming_dict = dict(getattr(record, "to_dict")())
        existing_dict.pop(version_field, None)
        incoming_dict.pop(version_field, None)
        if existing_dict == incoming_dict:
            return tuple(records)
        raise ValueError(
            f"{getattr(record, id_field)!r} is already registered with "
            "different content - create a new version instead of mutating "
            "the registry."
        )
    return tuple(records) + (record,)


def new_registered_family_version(
    records: Sequence[NamedEventFamily], family_id: str, **changes: Any
) -> Tuple[NamedEventFamily, ...]:
    current = {rec.family_id: rec for rec in current_family_versions(records)}
    if family_id not in current:
        raise ValueError(
            f"Family {family_id!r} is not registered - register it before "
            "creating a new version."
        )
    return tuple(records) + (new_family_version(current[family_id], **changes),)


def new_registered_occurrence_version(
    records: Sequence[NamedEventOccurrence], event_id: str, **changes: Any
) -> Tuple[NamedEventOccurrence, ...]:
    current = {rec.event_id: rec for rec in current_occurrence_versions(records)}
    if event_id not in current:
        raise ValueError(
            f"Occurrence {event_id!r} is not registered - adopt it before "
            "creating a new version."
        )
    return tuple(records) + (new_occurrence_version(current[event_id], **changes),)


def new_registered_response_definition_version(
    records: Sequence[EventResponseDefinition],
    response_definition_id: str,
    **changes: Any,
) -> Tuple[EventResponseDefinition, ...]:
    current = {
        rec.response_definition_id: rec
        for rec in current_response_definition_versions(records)
    }
    if response_definition_id not in current:
        raise ValueError(
            f"Response definition {response_definition_id!r} is not "
            "registered - register it before creating a new version."
        )
    return tuple(records) + (
        new_response_definition_version(current[response_definition_id], **changes),
    )


def registry_problems(
    families: Sequence[NamedEventFamily],
    occurrences: Sequence[NamedEventOccurrence],
    definitions: Sequence[EventResponseDefinition],
) -> Tuple[str, ...]:
    """Reference-validation problems across the registry (empty tuple =
    no problems). A response definition must reference a registered
    family; an occurrence's family link, if set, must too."""
    return validate_registry_references(families, occurrences, definitions)


def registry_to_dict(
    families: Sequence[NamedEventFamily],
    occurrences: Sequence[NamedEventOccurrence],
    definitions: Sequence[EventResponseDefinition],
) -> dict:
    """Serialise the full registry for project export - one stable dict
    with its own record-level `schema_version` so an importer can reject
    an unrecognised future schema instead of guessing."""
    return {
        "schema_version": EVENT_REGISTRY_SCHEMA_VERSION,
        "families": [rec.to_dict() for rec in families],
        "occurrences": [rec.to_dict() for rec in occurrences],
        "response_definitions": [rec.to_dict() for rec in definitions],
    }


def registry_has_content(
    families: Sequence[NamedEventFamily],
    occurrences: Sequence[NamedEventOccurrence],
    definitions: Sequence[EventResponseDefinition],
) -> bool:
    """Whether any part of the registry is non-empty - exporters use this
    to decide whether to write the registry file at all, keeping older
    bundles byte-comparable."""
    return bool(families or occurrences or definitions)
