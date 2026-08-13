"""Versioned standard source-pack schemas and canonicalisation.

The standard source pack is deliberately different from the model-ready wide
matrix. This module reads every workbook sheet, validates its logical table
identity, preserves native-frequency source tables, and only pivots the
activity table at the explicit model-input boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any

import pandas as pd

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    DOMAIN_EXPERIMENT_EVIDENCE,
    DOMAIN_OUTCOMES,
    compute_checksum,
)

STANDARD_TEMPLATE_SCHEMA_VERSION = "standard-source-pack-v1"
PERIOD_COLUMN = "period_start"
MARKET_COLUMN = "market"


@dataclass(frozen=True)
class SheetSpec:
    sheet_name: str
    required_columns: tuple[str, ...]
    description: str
    required: bool = True


@dataclass(frozen=True)
class ParsedTable:
    table_id: str
    logical_domain: str
    sheet_name: str
    row_count: int
    columns: tuple[str, ...]


@dataclass(frozen=True)
class WorkbookManifest:
    """Workbook-level provenance and parsed table identity."""

    source_id: str
    original_filename: str
    checksum: str
    size_bytes: int
    template_schema_version: str | None
    logical_domain: str | None
    standard_template: bool
    table_ids: tuple[str, ...]
    sheet_names: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id or not self.original_filename:
            raise ValueError("source_id and original_filename are required")
        if len(self.checksum) != 64:
            raise ValueError("checksum must be a sha256 hex digest")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be >= 0")

    @property
    def valid_standard_template(self) -> bool:
        return self.standard_template and not self.errors

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "WorkbookManifest":
        payload: dict[str, Any] = dict(values)
        payload["table_ids"] = tuple(payload.get("table_ids") or ())
        payload["sheet_names"] = tuple(payload.get("sheet_names") or ())
        payload["warnings"] = tuple(payload.get("warnings") or ())
        payload["errors"] = tuple(payload.get("errors") or ())
        return cls(**payload)


@dataclass(frozen=True)
class StandardWorkbook:
    manifest: WorkbookManifest
    tables: Mapping[str, pd.DataFrame]
    table_metadata: tuple[ParsedTable, ...]


@dataclass(frozen=True)
class CanonicalSourceBundle:
    """Canonicalised standard tables and their governed activity mapping."""

    manifest: WorkbookManifest
    raw_tables: Mapping[str, pd.DataFrame]
    activity_definitions: tuple[ActivityDefinition, ...]
    model_input_media: pd.DataFrame
    activity_column_map: Mapping[tuple[str, str], str]
    native_context_data: pd.DataFrame | None = None
    outcomes: pd.DataFrame | None = None
    experiment_evidence: pd.DataFrame | None = None


STANDARD_SHEET_SPECS: dict[str, tuple[SheetSpec, ...]] = {
    DOMAIN_OUTCOMES: (
        SheetSpec(
            "outcomes",
            (PERIOD_COLUMN, MARKET_COLUMN),
            "One row per observed period and market; measures remain separate columns.",
        ),
        SheetSpec(
            "outcome_dictionary",
            ("outcome_id", "source_column"),
            "Optional governed outcome metadata for source measures.",
            required=False,
        ),
    ),
    DOMAIN_ACTIVITY_AND_MEDIA: (
        SheetSpec(
            "activity_data",
            (PERIOD_COLUMN, MARKET_COLUMN, "activity_id"),
            "Tidy activity observations at period x market x activity_id grain.",
        ),
        SheetSpec(
            "activity_dictionary",
            (
                "activity_id",
                "market",
                "pooling_group_id",
                "channel",
                "platform",
                "campaign_type",
                "marketing_objective",
                "funnel_stage",
                "product_advertised",
                "message_type",
                "activity_ownership",
                "intended_model_role",
                "model_input_column",
                "model_input_measure",
                "economic_treatment",
                "planning_eligibility",
                "source",
            ),
            "Governed activity taxonomy and explicit model-input mapping.",
        ),
    ),
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS: (
        SheetSpec(
            "context_data",
            (PERIOD_COLUMN, MARKET_COLUMN, "variable_id", "value", "native_frequency"),
            "Tidy native-frequency context observations.",
        ),
        SheetSpec(
            "variable_dictionary",
            ("variable_id", "variable_class", "native_frequency", "role"),
            "Governed variable role, class, unit, and frequency metadata.",
        ),
        SheetSpec(
            "events",
            ("event_id", "event_name", "start_date", "end_date"),
            "Irregular named events and their scopes.",
            required=False,
        ),
    ),
    DOMAIN_EXPERIMENT_EVIDENCE: (
        SheetSpec(
            "experiment_evidence",
            ("experiment_id", "activity_id", "market", "start_date", "end_date"),
            "Optional experiment and lift evidence kept separate from historical controls.",
        ),
    ),
}


def standard_sheet_specs(logical_domain: str) -> tuple[SheetSpec, ...]:
    try:
        return STANDARD_SHEET_SPECS[logical_domain]
    except KeyError as exc:
        raise ValueError(f"unsupported standard logical domain {logical_domain!r}") from exc


def standard_template_columns(logical_domain: str, sheet_name: str) -> tuple[str, ...]:
    for spec in standard_sheet_specs(logical_domain):
        if spec.sheet_name == sheet_name:
            return spec.required_columns
    raise ValueError(
        f"sheet {sheet_name!r} is not supported for logical domain {logical_domain!r}"
    )


def _normalise_sheet_name(value: object) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _candidate_domains(sheet_names: Sequence[str]) -> list[str]:
    normalised = {_normalise_sheet_name(name) for name in sheet_names}
    return [
        domain
        for domain, specs in STANDARD_SHEET_SPECS.items()
        if any(spec.sheet_name in normalised for spec in specs)
    ]


def _validate_tables(
    *,
    logical_domain: str,
    sheet_names: Sequence[str],
    tables: Mapping[str, pd.DataFrame],
) -> tuple[list[ParsedTable], list[str], list[str], bool]:
    specs = standard_sheet_specs(logical_domain)
    by_normalised = {_normalise_sheet_name(name): name for name in sheet_names}
    parsed: list[ParsedTable] = []
    warnings: list[str] = []
    errors: list[str] = []
    for spec in specs:
        actual_name = by_normalised.get(spec.sheet_name)
        if actual_name is None:
            if spec.required:
                errors.append(
                    f"missing required sheet '{spec.sheet_name}' for {logical_domain}"
                )
            continue
        table = tables[actual_name]
        if table.empty:
            errors.append(f"sheet '{actual_name}' is empty")
        columns = tuple(str(column).strip() for column in table.columns)
        missing = [column for column in spec.required_columns if column not in columns]
        if missing:
            errors.append(
                f"sheet '{actual_name}' is missing required column(s): {missing}"
            )
        parsed.append(
            ParsedTable(
                table_id=f"{logical_domain}:{spec.sheet_name}",
                logical_domain=logical_domain,
                sheet_name=actual_name,
                row_count=len(table),
                columns=columns,
            )
        )
    known = {spec.sheet_name for spec in specs}
    unknown = [name for name in sheet_names if _normalise_sheet_name(name) not in known]
    if unknown:
        warnings.append(
            "unknown sheet(s) retained for review and not combined: "
            + ", ".join(unknown)
        )
    valid = bool(parsed) and not errors
    return parsed, warnings, errors, valid


def parse_standard_workbook(
    raw_bytes: bytes,
    *,
    source_id: str,
    filename: str,
    logical_domain: str | None = None,
) -> StandardWorkbook:
    """Parse every Excel sheet and validate a standard logical domain.

    A workbook is never treated as a standard template merely because its
    first sheet resembles one. If no domain is supplied, exactly one domain
    must be discoverable from the sheet names; otherwise the caller receives
    an explicit warning/error manifest and can use the generic source path.
    """
    if not filename.lower().endswith((".xlsx", ".xls", ".xlsm")):
        raise ValueError("standard workbook parsing requires an Excel file")
    try:
        excel = pd.ExcelFile(BytesIO(raw_bytes))
        sheet_names = tuple(str(name) for name in excel.sheet_names)
        tables = {
            name: pd.read_excel(excel, sheet_name=name) for name in sheet_names
        }
    except Exception as exc:
        manifest = WorkbookManifest(
            source_id=source_id,
            original_filename=filename,
            checksum=compute_checksum(raw_bytes),
            size_bytes=len(raw_bytes),
            template_schema_version=None,
            logical_domain=logical_domain,
            standard_template=False,
            table_ids=(),
            sheet_names=(),
            errors=(f"Excel workbook could not be parsed: {exc}",),
        )
        return StandardWorkbook(manifest, {}, ())

    warnings: list[str] = []
    errors: list[str] = []
    selected_domain = logical_domain
    if selected_domain is None:
        candidates = _candidate_domains(sheet_names)
        if len(candidates) == 1:
            selected_domain = candidates[0]
        elif len(candidates) > 1:
            errors.append(
                "workbook contains sheets from multiple standard domains; "
                "choose a logical domain explicitly"
            )
        else:
            warnings.append(
                "no standard template sheet set was recognised; generic source "
                "handling remains available"
            )
    parsed: list[ParsedTable] = []
    standard = False
    if selected_domain in STANDARD_SHEET_SPECS and not errors:
        parsed, domain_warnings, domain_errors, standard = _validate_tables(
            logical_domain=selected_domain,
            sheet_names=sheet_names,
            tables=tables,
        )
        warnings.extend(domain_warnings)
        errors.extend(domain_errors)
    elif selected_domain is not None and selected_domain not in STANDARD_SHEET_SPECS:
        errors.append(f"unsupported standard logical domain {selected_domain!r}")

    if not parsed and not errors:
        warnings.append(
            "generic workbook path selected; sheets remain separate and no "
            "standard-table identity was assigned"
        )
    manifest = WorkbookManifest(
        source_id=source_id,
        original_filename=filename,
        checksum=compute_checksum(raw_bytes),
        size_bytes=len(raw_bytes),
        template_schema_version=(STANDARD_TEMPLATE_SCHEMA_VERSION if standard else None),
        logical_domain=selected_domain,
        standard_template=standard,
        table_ids=tuple(item.table_id for item in parsed),
        sheet_names=sheet_names,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    return StandardWorkbook(manifest, tables, tuple(parsed))


def activity_definitions_from_dictionary(
    activity_dictionary: pd.DataFrame,
) -> tuple[ActivityDefinition, ...]:
    """Build governed activity rows from explicit dictionary columns."""
    required = set(standard_template_columns(DOMAIN_ACTIVITY_AND_MEDIA, "activity_dictionary"))
    missing = sorted(required - set(activity_dictionary.columns))
    if missing:
        raise ValueError(f"activity dictionary is missing required columns: {missing}")
    def required_text(row: Mapping[str, Any], column: str) -> str:
        value = row.get(column)
        if value is None or pd.isna(value) or not str(value).strip():
            raise ValueError(
                f"activity dictionary column {column!r} must be populated"
            )
        return str(value).strip()

    definitions: list[ActivityDefinition] = []
    for row in activity_dictionary.to_dict(orient="records"):
        payload: dict[str, Any] = {
            "activity_id": required_text(row, "activity_id"),
            "channel": required_text(row, "channel"),
            "activity_ownership": required_text(row, "activity_ownership"),
            "model_role": required_text(row, "intended_model_role"),
            "economic_treatment": required_text(row, "economic_treatment"),
            "planning_eligibility": required_text(row, "planning_eligibility"),
            "source": required_text(row, "source"),
            "market": required_text(row, "market"),
            "platform": required_text(row, "platform"),
            "campaign_type": required_text(row, "campaign_type"),
            "product_advertised": required_text(row, "product_advertised"),
            "marketing_objective": required_text(row, "marketing_objective"),
            "funnel_stage": required_text(row, "funnel_stage"),
            "message_type": required_text(row, "message_type"),
            "model_input_column": required_text(row, "model_input_column"),
            "pooling_group_id": (
                None if pd.isna(row.get("pooling_group_id")) else str(row["pooling_group_id"])
            ),
        }
        definitions.append(ActivityDefinition(**payload))
    identities = [(item.market, item.activity_id) for item in definitions]
    if len(identities) != len(set(identities)):
        raise ValueError("activity dictionary contains duplicate market/activity_id rows")
    return tuple(definitions)


def canonicalize_activity_data(
    activity_data: pd.DataFrame,
    activity_dictionary: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[ActivityDefinition, ...], dict[tuple[str, str], str]]:
    """Pivot tidy activity observations into the existing wide input boundary.

    The pivot is driven only by the dictionary's explicit
    ``model_input_measure`` and ``model_input_column``. Missing activity rows
    remain missing after the pivot; no zero or frequency fill is invented.
    """
    required = set(standard_template_columns(DOMAIN_ACTIVITY_AND_MEDIA, "activity_data"))
    missing = sorted(required - set(activity_data.columns))
    if missing:
        raise ValueError(f"activity data is missing required columns: {missing}")
    definitions = activity_definitions_from_dictionary(activity_dictionary)
    dictionary_records = activity_dictionary.to_dict(orient="records")
    mapping: dict[tuple[str, str], str] = {}
    measure_by_activity: dict[tuple[str, str], str] = {}
    definition_by_key = {(item.market, item.activity_id): item for item in definitions}
    wildcard_by_id = {
        item.activity_id: item for item in definitions if item.market == "*"
    }
    for row in dictionary_records:
        activity_id = str(row["activity_id"])
        model_column = str(row["model_input_column"]).strip()
        measure_value = row["model_input_measure"]
        configured_measure = (
            ""
            if measure_value is None or pd.isna(measure_value)
            else str(measure_value).strip()
        )
        if not model_column or not configured_measure:
            raise ValueError(
                f"activity {activity_id!r} needs explicit model_input_column and "
                "model_input_measure"
            )
        market = str(row["market"]).strip()
        mapping[(market, activity_id)] = model_column
        measure_by_activity[(market, activity_id)] = configured_measure
    rows: list[pd.DataFrame] = []
    for (market, activity_id), group in activity_data.groupby(
        [MARKET_COLUMN, "activity_id"], dropna=False, sort=False
    ):
        market_text = str(market)
        activity_text = str(activity_id)
        definition = definition_by_key.get((market_text, activity_text)) or wildcard_by_id.get(
            activity_text
        )
        if definition is None:
            raise ValueError(
                f"activity data row has no dictionary mapping for {market_text}/{activity_text}"
            )
        selected_measure: str | None = measure_by_activity.get(
            (market_text, activity_text)
        ) or measure_by_activity.get(("*", activity_text))
        if selected_measure is None or selected_measure not in group.columns:
            raise ValueError(
                f"activity {activity_text!r} maps to missing measure column {selected_measure!r}"
            )
        selected = group[[PERIOD_COLUMN, MARKET_COLUMN, selected_measure]].copy()
        selected["model_input_column"] = definition.resolved_model_input_column
        selected = selected.rename(columns={selected_measure: "model_input_value"})
        rows.append(selected)
    if not rows:
        raise ValueError("activity data contains no rows")
    long = pd.concat(rows, ignore_index=True)
    duplicates = long.duplicated(
        [PERIOD_COLUMN, MARKET_COLUMN, "model_input_column"], keep=False
    )
    if duplicates.any():
        raise ValueError(
            "activity data has duplicate period/market/model-input rows; "
            "resolve source grain before canonicalisation"
        )
    wide = (
        long.pivot(
            index=[PERIOD_COLUMN, MARKET_COLUMN],
            columns="model_input_column",
            values="model_input_value",
        )
        .reset_index()
    )
    wide.columns.name = None
    for model_column in mapping.values():
        if model_column not in wide.columns:
            wide[model_column] = pd.NA
    ordered = [PERIOD_COLUMN, MARKET_COLUMN, *dict.fromkeys(mapping.values())]
    return wide[ordered], definitions, mapping


def canonicalize_standard_workbook(
    workbook: StandardWorkbook,
) -> CanonicalSourceBundle:
    """Canonicalise a valid standard workbook without frequency conversion."""
    if not workbook.manifest.valid_standard_template:
        raise ValueError(
            "cannot canonicalise an invalid standard workbook: "
            + "; ".join(workbook.manifest.errors)
        )
    domain = workbook.manifest.logical_domain
    if domain == DOMAIN_ACTIVITY_AND_MEDIA:
        media, definitions, mapping = canonicalize_activity_data(
            workbook.tables["activity_data"], workbook.tables["activity_dictionary"]
        )
        return CanonicalSourceBundle(
            manifest=workbook.manifest,
            raw_tables=workbook.tables,
            activity_definitions=definitions,
            model_input_media=media,
            activity_column_map=mapping,
        )
    if domain == DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS:
        return CanonicalSourceBundle(
            manifest=workbook.manifest,
            raw_tables=workbook.tables,
            activity_definitions=(),
            model_input_media=pd.DataFrame(),
            activity_column_map={},
            native_context_data=workbook.tables["context_data"].copy(),
        )
    if domain == DOMAIN_OUTCOMES:
        return CanonicalSourceBundle(
            manifest=workbook.manifest,
            raw_tables=workbook.tables,
            activity_definitions=(),
            model_input_media=pd.DataFrame(),
            activity_column_map={},
            outcomes=workbook.tables["outcomes"].copy(),
        )
    return CanonicalSourceBundle(
        manifest=workbook.manifest,
        raw_tables=workbook.tables,
        activity_definitions=(),
        model_input_media=pd.DataFrame(),
        activity_column_map={},
        experiment_evidence=workbook.tables.get("experiment_evidence"),
    )
