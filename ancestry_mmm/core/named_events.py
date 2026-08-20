"""Governed named-event occurrence, family and response-definition data
contracts (`REQ-EVENT-001`, Work Package 1 of `Media-Mix-Lab: Coding LLM
Next Steps Post PR #297`).

This repository has no approved named-event statistical response method
(the response structure, kernel/basis family, priors, regularisation,
pooling, heterogeneity, support windows and thresholds are all tracked as
decision-required by `docs/wp2_named_event_statistical_method_decision_
package.md`). This module therefore registers governed identities and
lifecycle metadata only. It deliberately contains **no feature
construction**: the deterministic event-relative basis/kernel is a
statistical choice no record approves, so nothing here (or anywhere else
in the application) computes event-relative features.

Three governed analytical resources, all frozen and lineage-versioned
exactly like `core.causal_graph` (`graph_id`/`graph_version`),
`core.search_objects` (`search_object_id`/`search_object_version`) and
`core.experiments` (`experiment_id`/`experiment_version`):

- `NamedEventFamily` - one recurring conceptual occasion (e.g. one
  `mothers_day` family across years). Classification is analyst-supplied
  and governed; it is **never** inferred from `display_name` free text,
  and no real-world family is pre-classified by this module.
- `NamedEventOccurrence` - one factual dated occurrence with a stable
  `event_id`, factual start/end dates that are never shifted to
  represent pre/post-event purchasing, source lineage, and an optional
  governed family link (an occurrence may legitimately exist before its
  family mapping is reviewed).
- `EventResponseDefinition` - the governed temporal treatment (closed
  four-value vocabulary), explicit maximum lead/lag support, scope, and
  an opaque versioned transformation-method reference. No kernel is
  selected by this module; the reference is a governed string, and
  nothing downstream consumes it to build features today.

Domain separation (Part 11 v1.6): these are *analytical* resources. An
application domain event (e.g. `model_run.completed`) is a software
message with a different type, schema and identifier space; nothing here
represents a named calendar event as a domain-event message and nothing
here emits domain events.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import (
    Any,
    Dict,
    Iterable,
    Mapping,
    Optional,
    Tuple,
    TypeVar,
    cast,
)

import pandas as pd

EVENT_TREATMENT_CONTEMPORANEOUS = "contemporaneous"
EVENT_TREATMENT_ANTICIPATORY = "anticipatory"
EVENT_TREATMENT_POST_EVENT = "post_event"
EVENT_TREATMENT_ANTICIPATORY_AND_POST_EVENT = "anticipatory_and_post_event"

# REQ-EVENT-001 section 3: the closed temporal-treatment vocabulary. No
# other treatment label may be introduced without a separately approved
# requirement change.
EVENT_TREATMENTS = (
    EVENT_TREATMENT_CONTEMPORANEOUS,
    EVENT_TREATMENT_ANTICIPATORY,
    EVENT_TREATMENT_POST_EVENT,
    EVENT_TREATMENT_ANTICIPATORY_AND_POST_EVENT,
)

# Record-level schema version of the persisted governed named-event
# registry file (`config/named_events.json` in the project bundle).
# Importers reject an unrecognised future version rather than guessing -
# mirrors every other governed record's schema-version contract.
EVENT_REGISTRY_SCHEMA_VERSION = 1

# Newly created governed records default to an explicitly review-required
# evidence status - registration is never approval. Mirrors
# `application.experiment_service.DEFAULT_EVIDENCE_STATUS`.
DEFAULT_EVENT_EVIDENCE_STATUS = "draft_review_required"


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")


def _validate_iso_date_range(start_date: str, end_date: str, label: str) -> None:
    """The factual occurrence interval must parse and must not be inverted.
    The stored strings are preserved verbatim - nothing here rewrites,
    normalises, or shifts a factual date."""
    try:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label} has an unparseable start/end date: {exc}") from exc
    if end < start:
        raise ValueError(
            f"{label} end date ({end_date!r}) is before its start date ({start_date!r})"
        )


def _fingerprint_payload(payload: Mapping[str, Any]) -> str:
    """Deterministic SHA-256 over a stable, sorted JSON encoding of the
    payload. Pure - depends only on the argument, never on wall-clock
    time, object identity or iteration order."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NamedEventFamily:
    """One governed event-family identity. `family_id`/`family_version`
    is the lineage/version identity. `classification` is the governed,
    analyst-supplied classification (e.g. a gifting, commercial, holiday
    or cultural designation) - never inferred from `display_name`, which
    is a free-text display label that can change without changing
    identity."""

    family_id: str
    family_version: int
    display_name: str
    classification: str
    classification_status: str = DEFAULT_EVENT_EVIDENCE_STATUS
    market_scope: Tuple[str, ...] = ()
    product_scope: Tuple[str, ...] = ()
    outcome_scope: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_blank(self.family_id, "family_id")
        if self.family_version < 1:
            raise ValueError("family_version must be >= 1")
        _require_non_blank(self.display_name, "display_name")
        _require_non_blank(self.classification, "classification")
        _require_non_blank(self.classification_status, "classification_status")

    def to_dict(self) -> dict:
        return {
            "family_id": self.family_id,
            "family_version": self.family_version,
            "display_name": self.display_name,
            "classification": self.classification,
            "classification_status": self.classification_status,
            "market_scope": list(self.market_scope),
            "product_scope": list(self.product_scope),
            "outcome_scope": list(self.outcome_scope),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "NamedEventFamily":
        return cls(
            family_id=values["family_id"],
            family_version=int(values["family_version"]),
            display_name=values["display_name"],
            classification=values["classification"],
            classification_status=values.get("classification_status")
            or DEFAULT_EVENT_EVIDENCE_STATUS,
            market_scope=tuple(values.get("market_scope") or ()),
            product_scope=tuple(values.get("product_scope") or ()),
            outcome_scope=tuple(values.get("outcome_scope") or ()),
            metadata=dict(values.get("metadata") or {}),
        )


@dataclass(frozen=True)
class NamedEventOccurrence:
    """One factual, dated named-event occurrence. The factual
    `start_date`/`end_date` interval is source truth and is never
    shifted to represent pre/post-event purchasing (`REQ-EVENT-001`
    section 1). `source_id` records which uploaded source carried this
    occurrence; `family_id` is an optional governed link (an occurrence
    may exist before its family mapping is reviewed)."""

    event_id: str
    event_version: int
    display_name: str
    start_date: str  # factual ISO 'YYYY-MM-DD' - never shifted
    end_date: str
    market_scope: Tuple[str, ...]
    source_id: str
    source_version: Optional[int] = None
    family_id: Optional[str] = None
    transformation_version: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_blank(self.event_id, "event_id")
        if self.event_version < 1:
            raise ValueError("event_version must be >= 1")
        _require_non_blank(self.display_name, "display_name")
        _require_non_blank(self.source_id, "source_id")
        if not self.market_scope:
            raise ValueError("market_scope is required")
        if self.transformation_version < 1:
            raise ValueError("transformation_version must be >= 1")
        _validate_iso_date_range(self.start_date, self.end_date, self.event_id)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_version": self.event_version,
            "display_name": self.display_name,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "market_scope": list(self.market_scope),
            "source_id": self.source_id,
            "source_version": self.source_version,
            "family_id": self.family_id,
            "transformation_version": self.transformation_version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "NamedEventOccurrence":
        return cls(
            event_id=values["event_id"],
            event_version=int(values["event_version"]),
            display_name=values["display_name"],
            start_date=values["start_date"],
            end_date=values["end_date"],
            market_scope=tuple(values.get("market_scope") or ()),
            source_id=values["source_id"],
            source_version=(
                int(values["source_version"])
                if values.get("source_version") is not None
                else None
            ),
            family_id=values.get("family_id") or None,
            transformation_version=int(values.get("transformation_version") or 1),
            metadata=dict(values.get("metadata") or {}),
        )


@dataclass(frozen=True)
class EventResponseDefinition:
    """The governed temporal-treatment definition for one event family.
    `treatment` must be exactly one value of the closed four-value
    vocabulary. `max_lead`/`max_lag` are governed support windows only -
    never evidence that every period inside the window has a material
    effect. `transformation_method_reference` is an opaque governed
    string; no kernel/basis is selected by this module and nothing
    consumes the reference to build features today."""

    response_definition_id: str
    response_definition_version: int
    family_id: str
    treatment: str
    max_lead: int
    max_lag: int
    transformation_method_reference: str
    transformation_version: int = 1
    market_scope: Tuple[str, ...] = ()
    product_scope: Tuple[str, ...] = ()
    outcome_scope: Tuple[str, ...] = ()
    evidence_status: str = DEFAULT_EVENT_EVIDENCE_STATUS
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_blank(self.response_definition_id, "response_definition_id")
        if self.response_definition_version < 1:
            raise ValueError("response_definition_version must be >= 1")
        _require_non_blank(self.family_id, "family_id")
        if self.treatment not in EVENT_TREATMENTS:
            raise ValueError(
                f"invalid treatment {self.treatment!r}; must be one of "
                f"{EVENT_TREATMENTS}"
            )
        if self.max_lead < 0:
            raise ValueError("max_lead must be >= 0")
        if self.max_lag < 0:
            raise ValueError("max_lag must be >= 0")
        _require_non_blank(
            self.transformation_method_reference,
            "transformation_method_reference",
        )
        if self.transformation_version < 1:
            raise ValueError("transformation_version must be >= 1")
        _require_non_blank(self.evidence_status, "evidence_status")

    def to_dict(self) -> dict:
        return {
            "response_definition_id": self.response_definition_id,
            "response_definition_version": self.response_definition_version,
            "family_id": self.family_id,
            "treatment": self.treatment,
            "max_lead": self.max_lead,
            "max_lag": self.max_lag,
            "transformation_method_reference": (self.transformation_method_reference),
            "transformation_version": self.transformation_version,
            "market_scope": list(self.market_scope),
            "product_scope": list(self.product_scope),
            "outcome_scope": list(self.outcome_scope),
            "evidence_status": self.evidence_status,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "EventResponseDefinition":
        return cls(
            response_definition_id=values["response_definition_id"],
            response_definition_version=int(values["response_definition_version"]),
            family_id=values["family_id"],
            treatment=values["treatment"],
            max_lead=int(values["max_lead"]),
            max_lag=int(values["max_lag"]),
            transformation_method_reference=values["transformation_method_reference"],
            transformation_version=int(values.get("transformation_version") or 1),
            market_scope=tuple(values.get("market_scope") or ()),
            product_scope=tuple(values.get("product_scope") or ()),
            outcome_scope=tuple(values.get("outcome_scope") or ()),
            evidence_status=values.get("evidence_status")
            or DEFAULT_EVENT_EVIDENCE_STATUS,
            metadata=dict(values.get("metadata") or {}),
        )


_RecordT = TypeVar("_RecordT")


def new_family_version(family: NamedEventFamily, **changes: Any) -> NamedEventFamily:
    return _new_version(family, "family_id", "family_version", changes)


def new_occurrence_version(
    occurrence: NamedEventOccurrence, **changes: Any
) -> NamedEventOccurrence:
    return _new_version(occurrence, "event_id", "event_version", changes)


def new_response_definition_version(
    definition: EventResponseDefinition, **changes: Any
) -> EventResponseDefinition:
    return _new_version(
        definition, "response_definition_id", "response_definition_version", changes
    )


def _new_version(
    record: _RecordT, id_field: str, version_field: str, changes: dict
) -> _RecordT:
    for locked_field in (id_field, version_field):
        if locked_field in changes:
            raise ValueError(
                f"{locked_field!r} is lineage/version identity and cannot be "
                "changed in place - construct a new record to register a "
                "different identity."
            )
    return cast(
        _RecordT,
        replace(
            cast(Any, record),
            **{version_field: getattr(record, version_field) + 1},
            **changes,
        ),
    )


def current_family_versions(
    families: Iterable[NamedEventFamily],
) -> Tuple[NamedEventFamily, ...]:
    return _current_versions(families, "family_id", "family_version")


def current_occurrence_versions(
    occurrences: Iterable[NamedEventOccurrence],
) -> Tuple[NamedEventOccurrence, ...]:
    return _current_versions(occurrences, "event_id", "event_version")


def current_response_definition_versions(
    definitions: Iterable[EventResponseDefinition],
) -> Tuple[EventResponseDefinition, ...]:
    return _current_versions(
        definitions, "response_definition_id", "response_definition_version"
    )


def _current_versions(
    records: Iterable[_RecordT], id_field: str, version_field: str
) -> Tuple[_RecordT, ...]:
    latest: Dict[str, _RecordT] = {}
    for record in records:
        current = latest.get(getattr(record, id_field))
        if current is None or getattr(record, version_field) > getattr(
            current, version_field
        ):
            latest[getattr(record, id_field)] = record
    return tuple(latest.values())


def validate_registry_references(
    families: Iterable[NamedEventFamily],
    occurrences: Iterable[NamedEventOccurrence],
    definitions: Iterable[EventResponseDefinition],
) -> Tuple[str, ...]:
    """Reference-validation problems across the registry, as
    human-readable messages (an empty tuple means no problems). A
    response definition must reference a family that exists; an
    occurrence's family link, if set, must reference a family that
    exists (an orphan link is reported, never silently re-mapped)."""
    problems: list = []
    family_ids = {family.family_id for family in families}
    for definition in definitions:
        if definition.family_id not in family_ids:
            problems.append(
                f"Event response definition {definition.response_definition_id!r} "
                f"references family {definition.family_id!r}, which is not in "
                "the registry."
            )
    for occurrence in occurrences:
        if occurrence.family_id and occurrence.family_id not in family_ids:
            problems.append(
                f"Event occurrence {occurrence.event_id!r} references family "
                f"{occurrence.family_id!r}, which is not in the registry."
            )
    return tuple(problems)


def fingerprint_event_family(family: NamedEventFamily) -> str:
    """Deterministic family fingerprint. Excludes the free-text
    `display_name` (a label change must not stale governed downstream
    artefacts); includes the governed classification and scopes."""
    return _fingerprint_payload(
        {
            "family_id": family.family_id,
            "family_version": family.family_version,
            "classification": family.classification,
            "classification_status": family.classification_status,
            "market_scope": list(family.market_scope),
            "product_scope": list(family.product_scope),
            "outcome_scope": list(family.outcome_scope),
            "metadata": dict(family.metadata),
        }
    )


def fingerprint_event_occurrence(occurrence: NamedEventOccurrence) -> str:
    """Deterministic occurrence fingerprint over the factual interval,
    identity, lineage and family link. Excludes the free-text
    `display_name`. Changing any factual date changes the fingerprint -
    nothing in this repository shifts factual dates."""
    return _fingerprint_payload(
        {
            "event_id": occurrence.event_id,
            "event_version": occurrence.event_version,
            "start_date": occurrence.start_date,
            "end_date": occurrence.end_date,
            "market_scope": list(occurrence.market_scope),
            "source_id": occurrence.source_id,
            "source_version": occurrence.source_version,
            "family_id": occurrence.family_id,
            "transformation_version": occurrence.transformation_version,
            "metadata": dict(occurrence.metadata),
        }
    )


def fingerprint_event_response_definition(
    definition: EventResponseDefinition,
) -> str:
    """Deterministic response-definition fingerprint over treatment,
    support, scope and transformation reference/version - the fields
    `REQ-EVENT-001` section 8 says must stale downstream artefacts."""
    return _fingerprint_payload(
        {
            "response_definition_id": definition.response_definition_id,
            "response_definition_version": definition.response_definition_version,
            "family_id": definition.family_id,
            "treatment": definition.treatment,
            "max_lead": definition.max_lead,
            "max_lag": definition.max_lag,
            "transformation_method_reference": (
                definition.transformation_method_reference
            ),
            "transformation_version": definition.transformation_version,
            "market_scope": list(definition.market_scope),
            "product_scope": list(definition.product_scope),
            "outcome_scope": list(definition.outcome_scope),
            "evidence_status": definition.evidence_status,
            "metadata": dict(definition.metadata),
        }
    )


def registry_fingerprint(
    families: Iterable[NamedEventFamily],
    occurrences: Iterable[NamedEventOccurrence],
    definitions: Iterable[EventResponseDefinition],
) -> str:
    """Deterministic registry-level fingerprint over the *current*
    (highest) version of every family, occurrence and response
    definition, sorted by identity for stability."""
    return _fingerprint_payload(
        {
            "families": sorted(
                (fingerprint_event_family(f) for f in current_family_versions(families))
            ),
            "occurrences": sorted(
                (
                    fingerprint_event_occurrence(o)
                    for o in current_occurrence_versions(occurrences)
                )
            ),
            "response_definitions": sorted(
                (
                    fingerprint_event_response_definition(d)
                    for d in current_response_definition_versions(definitions)
                )
            ),
        }
    )
