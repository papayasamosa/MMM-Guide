"""Presentation-safe summaries for loaded source layouts.

The raw source mapping intentionally contains one entry per table.  That is
the right storage boundary for source-native workbooks, but it is not a safe
user-facing file count and it is not enough to decide whether the rectangular
join page applies.  This module keeps those two presentation decisions in a
framework-independent helper so Home and the Data Sources / Prepare Data
pages use the same interpretation without changing any stored source values.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ancestry_mmm.core.coverage import (
    SourceVersion,
    resolve_source_logical_domain,
)

WORKBOOK_TABLE_SEPARATOR = "__sheet__"

_STANDARD_TABLE_NAMES = frozenset(
    {
        "activity_data",
        "activity_dictionary",
        "outcomes",
        "outcome_dictionary",
        "context_data",
        "variable_dictionary",
        "events",
        "experiment_evidence",
    }
)

_SOURCE_NATIVE_TABLE_ROLES = {
    "activity_data": "Time-series activity",
    "activity_dictionary": "Activity metadata",
    "outcomes": "Time-series outcomes",
    "outcome_dictionary": "Outcome metadata",
    "context_data": "Native-frequency context",
    "variable_dictionary": "Variable metadata",
    "events": "Irregular events",
    "experiment_evidence": "Experiment evidence",
}


def source_table_name(source_id: str) -> str:
    """Return the table name represented by a stored source identity."""

    if WORKBOOK_TABLE_SEPARATOR in source_id:
        return source_id.rsplit(WORKBOOK_TABLE_SEPARATOR, 1)[1]
    return source_id


def source_lineage_id(source_id: str) -> str:
    """Return the physical file/workbook lineage for a stored source identity."""

    if WORKBOOK_TABLE_SEPARATOR in source_id:
        return source_id.rsplit(WORKBOOK_TABLE_SEPARATOR, 1)[0]
    return source_id


def source_table_role(source_id: str) -> str:
    """Describe a recognised source-native table without exposing enum keys."""

    return _SOURCE_NATIVE_TABLE_ROLES.get(
        source_table_name(source_id), "Uploaded table"
    )


@dataclass(frozen=True)
class SourceInventory:
    """Counts that keep physical inputs separate from stored tables."""

    uploaded_file_count: int
    data_category_count: int
    table_count: int
    recognised_standard_table_count: int
    active_source_version_count: int


@dataclass(frozen=True)
class SourceLayout:
    """The preparation contract implied by the currently loaded source tables."""

    kind: str
    is_source_native: bool
    can_use_rectangular_join: bool
    table_names: tuple[str, ...]

    @property
    def title(self) -> str:
        if self.kind == "realistic_source_pack":
            return "Realistic source pack"
        if self.kind == "standard_source_pack":
            return "Standard source pack"
        return "Rectangular source set"

    @property
    def description(self) -> str:
        if self.kind == "realistic_source_pack":
            return (
                "Source-native tables are available for review, but the current "
                "application does not yet prepare this mixed-frequency pack "
                "end-to-end for official modelling."
            )
        if self.kind == "standard_source_pack":
            return (
                "Standard tables are recognised and remain separate. The current "
                "rectangular preparation path is available only when the selected "
                "inputs already share a model-ready time grain."
            )
        return (
            "These inputs can be reviewed and joined on an explicit shared key "
            "before transformation."
        )


def _as_source_version(value: SourceVersion | Mapping[str, Any]) -> SourceVersion:
    return value if isinstance(value, SourceVersion) else SourceVersion.from_dict(value)


def _active_versions_by_lineage(
    source_versions: Iterable[SourceVersion | Mapping[str, Any]],
    active_upload_versions: Mapping[str, int] | None,
) -> dict[str, SourceVersion]:
    active = active_upload_versions or {}
    by_key = {
        (version.source_id, version.version): version
        for version in (_as_source_version(item) for item in source_versions)
    }
    result: dict[str, SourceVersion] = {}
    for stored_source_id, version_number in active.items():
        lineage = source_lineage_id(str(stored_source_id))
        version = by_key.get((lineage, int(version_number)))
        if version is not None:
            result[lineage] = version
    return result


def summarise_source_inventory(
    raw_sources: Mapping[str, object] | None,
    source_definitions: Iterable[Mapping[str, Any]] | None = None,
    source_versions: Iterable[SourceVersion | Mapping[str, Any]] | None = None,
    active_upload_versions: Mapping[str, int] | None = None,
    demo_source_pack: str | None = None,
) -> SourceInventory:
    """Summarise current inputs without treating each workbook sheet as a file."""

    sources = raw_sources or {}
    definitions = tuple(source_definitions or ())
    versions = tuple(source_versions or ())
    active_versions = _active_versions_by_lineage(versions, active_upload_versions)
    domains = {
        resolve_source_logical_domain(source_id, definitions) or "unclassified"
        for source_id in sources
    }
    recognised_ids = {
        table_id
        for version in active_versions.values()
        if version.standard_template
        for table_id in version.parsed_table_ids
    }
    if demo_source_pack == "realistic-source-pack-v1":
        recognised_ids.update(
            f"source-native:{source_table_name(source_id)}"
            for source_id in sources
            if source_table_name(source_id) in _STANDARD_TABLE_NAMES
        )
    return SourceInventory(
        uploaded_file_count=len(active_versions),
        data_category_count=len(domains),
        table_count=len(sources),
        recognised_standard_table_count=len(recognised_ids),
        active_source_version_count=len(
            {
                (version.source_id, version.version)
                for version in active_versions.values()
            }
        ),
    )


def inspect_source_layout(
    raw_sources: Mapping[str, object] | None,
    *,
    source_versions: Iterable[SourceVersion | Mapping[str, Any]] | None = None,
    active_upload_versions: Mapping[str, int] | None = None,
    demo_source_pack: str | None = None,
) -> SourceLayout:
    """Classify the current inputs for the preparation UI.

    A source-native classification is intentionally conservative. It is based
    on the governed standard workbook metadata or the explicit realistic demo
    identifier, not on guessed column names in an arbitrary upload.
    """

    source_ids = tuple(str(source_id) for source_id in (raw_sources or {}))
    table_names = tuple(source_table_name(source_id) for source_id in source_ids)
    active_versions = _active_versions_by_lineage(
        source_versions or (), active_upload_versions
    )
    has_standard_version = any(
        version.standard_template for version in active_versions.values()
    )
    has_realistic_demo = demo_source_pack == "realistic-source-pack-v1"
    has_standard_names = len(set(table_names).intersection(_STANDARD_TABLE_NAMES)) >= 2
    is_source_native = has_realistic_demo or has_standard_version or has_standard_names
    kind = (
        "realistic_source_pack"
        if has_realistic_demo
        else "standard_source_pack"
        if is_source_native
        else "rectangular"
    )
    return SourceLayout(
        kind=kind,
        is_source_native=is_source_native,
        can_use_rectangular_join=not is_source_native,
        table_names=table_names,
    )


__all__ = [
    "SourceInventory",
    "SourceLayout",
    "inspect_source_layout",
    "source_lineage_id",
    "source_table_name",
    "source_table_role",
    "summarise_source_inventory",
]
