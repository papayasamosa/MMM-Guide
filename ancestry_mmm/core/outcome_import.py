"""Outcome-source import, draft seeding, and catalogue comparison.

The source dictionary describes business meaning; it does not approve an
outcome or select a model treatment.  This module keeps that boundary
framework-independent so upload workflows, an API, and batch imports can use
the same fail-closed interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .outcomes import (
    OutcomeDefinition,
    OutcomeGroupDefinition,
    validate_outcome_definitions,
    validate_outcome_group_definitions,
    outcome_catalogue_fingerprint_payload,
    outcome_group_fingerprint_payload,
)

OUTCOMES_SOURCE_PACK_V1 = "standard-source-pack-v1"
OUTCOMES_SOURCE_PACK_V2 = "standard-source-pack-v2"

OUTCOME_SOURCE_STATUS_V2_DRAFT = "v2_draft"
OUTCOME_SOURCE_STATUS_V1_INCOMPLETE = "v1_incomplete"
OUTCOME_SOURCE_STATUS_BLOCKED = "blocked"
OUTCOME_SOURCE_STATUS_UNSUPPORTED = "unsupported"


def _outcome(value: OutcomeDefinition | Mapping[str, object]) -> OutcomeDefinition:
    return (
        value
        if isinstance(value, OutcomeDefinition)
        else OutcomeDefinition.from_dict(value)
    )


def _group(
    value: OutcomeGroupDefinition | Mapping[str, object],
) -> OutcomeGroupDefinition:
    return (
        value
        if isinstance(value, OutcomeGroupDefinition)
        else OutcomeGroupDefinition.from_dict(value)
    )


@dataclass(frozen=True)
class OutcomeCatalogueComparison:
    """Calculation-relevant merge preview for a source and live catalogue.

    ``changed`` uses the same calculation identity as model staleness.  A
    source label change that does not alter that identity is therefore not
    presented as a statistical drift.  The preview never mutates either
    catalogue.
    """

    source_outcome_ids: tuple[str, ...] = ()
    current_outcome_ids: tuple[str, ...] = ()
    source_only_outcome_ids: tuple[str, ...] = ()
    current_only_outcome_ids: tuple[str, ...] = ()
    changed_outcome_ids: tuple[str, ...] = ()
    unchanged_outcome_ids: tuple[str, ...] = ()
    source_group_ids: tuple[str, ...] = ()
    current_group_ids: tuple[str, ...] = ()
    source_only_group_ids: tuple[str, ...] = ()
    current_only_group_ids: tuple[str, ...] = ()
    changed_group_ids: tuple[str, ...] = ()
    unchanged_group_ids: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(
            self.source_only_outcome_ids
            or self.current_only_outcome_ids
            or self.changed_outcome_ids
            or self.source_only_group_ids
            or self.current_only_group_ids
            or self.changed_group_ids
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_outcome_ids": list(self.source_outcome_ids),
            "current_outcome_ids": list(self.current_outcome_ids),
            "source_only_outcome_ids": list(self.source_only_outcome_ids),
            "current_only_outcome_ids": list(self.current_only_outcome_ids),
            "changed_outcome_ids": list(self.changed_outcome_ids),
            "unchanged_outcome_ids": list(self.unchanged_outcome_ids),
            "source_group_ids": list(self.source_group_ids),
            "current_group_ids": list(self.current_group_ids),
            "source_only_group_ids": list(self.source_only_group_ids),
            "current_only_group_ids": list(self.current_only_group_ids),
            "changed_group_ids": list(self.changed_group_ids),
            "unchanged_group_ids": list(self.unchanged_group_ids),
            "has_changes": self.has_changes,
        }


def compare_outcome_catalogues(
    current_outcomes: Sequence[OutcomeDefinition | Mapping[str, object]],
    source_outcomes: Sequence[OutcomeDefinition | Mapping[str, object]],
    current_groups: Sequence[OutcomeGroupDefinition | Mapping[str, object]] = (),
    source_groups: Sequence[OutcomeGroupDefinition | Mapping[str, object]] = (),
) -> OutcomeCatalogueComparison:
    """Compare source metadata to the live catalogue without adopting it."""

    current_defs = {
        _outcome(item).outcome_id: _outcome(item) for item in current_outcomes
    }
    source_defs = {
        _outcome(item).outcome_id: _outcome(item) for item in source_outcomes
    }
    current_group_defs = {
        _group(item).group_id: _group(item) for item in current_groups
    }
    source_group_defs = {_group(item).group_id: _group(item) for item in source_groups}

    shared_outcome_ids = sorted(set(current_defs) & set(source_defs))
    shared_group_ids = sorted(set(current_group_defs) & set(source_group_defs))
    changed_outcomes = [
        outcome_id
        for outcome_id in shared_outcome_ids
        if outcome_catalogue_fingerprint_payload([current_defs[outcome_id]])
        != outcome_catalogue_fingerprint_payload([source_defs[outcome_id]])
    ]
    changed_groups = [
        group_id
        for group_id in shared_group_ids
        if outcome_group_fingerprint_payload([current_group_defs[group_id]])
        != outcome_group_fingerprint_payload([source_group_defs[group_id]])
    ]
    return OutcomeCatalogueComparison(
        source_outcome_ids=tuple(sorted(source_defs)),
        current_outcome_ids=tuple(sorted(current_defs)),
        source_only_outcome_ids=tuple(sorted(set(source_defs) - set(current_defs))),
        current_only_outcome_ids=tuple(sorted(set(current_defs) - set(source_defs))),
        changed_outcome_ids=tuple(changed_outcomes),
        unchanged_outcome_ids=tuple(
            sorted(set(shared_outcome_ids) - set(changed_outcomes))
        ),
        source_group_ids=tuple(sorted(source_group_defs)),
        current_group_ids=tuple(sorted(current_group_defs)),
        source_only_group_ids=tuple(
            sorted(set(source_group_defs) - set(current_group_defs))
        ),
        current_only_group_ids=tuple(
            sorted(set(current_group_defs) - set(source_group_defs))
        ),
        changed_group_ids=tuple(changed_groups),
        unchanged_group_ids=tuple(sorted(set(shared_group_ids) - set(changed_groups))),
    )


@dataclass(frozen=True)
class OutcomeSourceImport:
    """Portable interpretation of one Outcomes workbook import."""

    schema_version: str
    status: str
    outcome_definitions: tuple[OutcomeDefinition, ...] = ()
    outcome_groups: tuple[OutcomeGroupDefinition, ...] = ()
    outcome_reconciliation_groups: tuple[object, ...] = ()
    outcome_completeness_metadata: Mapping[str, object] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    comparison: OutcomeCatalogueComparison | None = None

    @property
    def is_seedable_draft(self) -> bool:
        return self.status == OUTCOME_SOURCE_STATUS_V2_DRAFT and not self.errors

    @property
    def has_approval(self) -> bool:
        """Source import never creates approvals; kept explicit for callers."""

        return False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "outcome_definitions": [
                item.to_dict() for item in self.outcome_definitions
            ],
            "outcome_groups": [item.to_dict() for item in self.outcome_groups],
            "outcome_reconciliation_groups": [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in self.outcome_reconciliation_groups
            ],
            "outcome_completeness_metadata": {
                str(key): value.to_dict() if hasattr(value, "to_dict") else value
                for key, value in self.outcome_completeness_metadata.items()
            },
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "has_approval": self.has_approval,
        }


@dataclass(frozen=True)
class OutcomeCatalogueAdoption:
    """Explicit source-to-catalogue adoption payload.

    The empty ``outcome_approvals`` field is intentional.  Adoption creates
    draft definitions only; approval remains a separate analyst/governance
    action and is never inferred from the workbook.
    """

    outcome_definitions: tuple[OutcomeDefinition, ...]
    outcome_groups: tuple[OutcomeGroupDefinition, ...]
    outcome_reconciliation_groups: tuple[object, ...]
    outcome_approvals: tuple[object, ...] = ()

    def to_state(self) -> dict[str, object]:
        return {
            "outcome_definitions": [
                item.to_dict() for item in self.outcome_definitions
            ],
            "outcome_groups": [item.to_dict() for item in self.outcome_groups],
            "outcome_reconciliation_groups": [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in self.outcome_reconciliation_groups
            ],
            "outcome_approvals": [],
        }


def interpret_outcome_source(
    *,
    schema_version: str | None,
    outcome_definitions: Sequence[OutcomeDefinition | Mapping[str, object]] = (),
    outcome_groups: Sequence[OutcomeGroupDefinition | Mapping[str, object]] = (),
    outcome_reconciliation_groups: Sequence[object] = (),
    outcome_completeness_metadata: Mapping[str, object] | None = None,
    source_warnings: Sequence[str] = (),
    current_outcomes: Sequence[OutcomeDefinition | Mapping[str, object]] = (),
    current_groups: Sequence[OutcomeGroupDefinition | Mapping[str, object]] = (),
) -> OutcomeSourceImport:
    """Interpret v1/v2 semantics and produce an optional merge preview.

    v1 records are deliberately not returned as seedable definitions.  Their
    source-column mapping remains available in the raw source tables, but no
    product, metric, segment dimension, or group meaning is inferred.
    """

    version = schema_version or ""
    warnings = list(source_warnings)
    definitions = tuple(_outcome(item) for item in outcome_definitions)
    groups = tuple(_group(item) for item in outcome_groups)
    completeness = dict(outcome_completeness_metadata or {})

    if version == OUTCOMES_SOURCE_PACK_V1:
        warning = (
            "This Outcomes workbook is a legacy/incomplete v1 mapping. "
            "Product, metric, breakdown, segment, and group semantics were not "
            "inferred; review the dictionary before newly governed use."
        )
        if warning not in warnings:
            warnings.append(warning)
        return OutcomeSourceImport(
            schema_version=version,
            status=OUTCOME_SOURCE_STATUS_V1_INCOMPLETE,
            warnings=tuple(warnings),
            outcome_completeness_metadata=completeness,
        )

    if version != OUTCOMES_SOURCE_PACK_V2:
        return OutcomeSourceImport(
            schema_version=version,
            status=OUTCOME_SOURCE_STATUS_UNSUPPORTED,
            warnings=tuple(warnings),
            errors=(f"Unsupported Outcomes source schema version {version!r}.",),
            outcome_completeness_metadata=completeness,
        )

    errors = (
        validate_outcome_definitions(list(definitions))
        if definitions
        else ["The v2 Outcomes dictionary produced no canonical outcome definitions."]
    )
    errors.extend(
        validate_outcome_group_definitions(groups, outcomes=definitions)
        if groups
        else []
    )
    comparison = compare_outcome_catalogues(
        current_outcomes,
        definitions,
        current_groups,
        groups,
    )
    return OutcomeSourceImport(
        schema_version=version,
        status=OUTCOME_SOURCE_STATUS_V2_DRAFT
        if not errors
        else OUTCOME_SOURCE_STATUS_BLOCKED,
        outcome_definitions=definitions,
        outcome_groups=groups,
        outcome_reconciliation_groups=tuple(outcome_reconciliation_groups),
        outcome_completeness_metadata=completeness,
        warnings=tuple(warnings),
        errors=tuple(errors),
        comparison=comparison,
    )


def adopt_outcome_source_draft(
    source: OutcomeSourceImport,
) -> OutcomeCatalogueAdoption:
    """Return an explicit draft adoption payload; never return approvals."""

    if not source.is_seedable_draft:
        raise ValueError(
            "Only a valid v2 Outcomes source can be adopted as a draft catalogue."
        )
    return OutcomeCatalogueAdoption(
        outcome_definitions=source.outcome_definitions,
        outcome_groups=source.outcome_groups,
        outcome_reconciliation_groups=source.outcome_reconciliation_groups,
    )
