"""Versioned standard source-pack schemas and canonicalisation.

The standard source pack is deliberately different from the model-ready wide
matrix. This module reads every workbook sheet, validates its logical table
identity, preserves native-frequency source tables, and only pivots the
activity table at the explicit model-input boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
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
from ancestry_mmm.core.net_billthrough import (
    NBT_METRIC_KEY,
    NetBillthroughCompletenessMetadata,
    validate_nbt_completeness_metadata_for_outcome,
)
from ancestry_mmm.core.outcome_approval import fingerprint_outcome_definition
from ancestry_mmm.core.outcomes import (
    KNOWN_PRODUCTS,
    METRIC_REGISTRY,
    METRIC_KEY_CUSTOM,
    OutcomeDefinition,
    OutcomeGroupDefinition,
    SEGMENT_DIMENSIONS,
    validate_outcome_definitions,
    validate_outcome_group_definitions,
)
from ancestry_mmm.core.pathways import OutcomeReconciliationGroup

STANDARD_TEMPLATE_SCHEMA_VERSION = "standard-source-pack-v1"
STANDARD_TEMPLATE_SCHEMA_VERSION_V1 = STANDARD_TEMPLATE_SCHEMA_VERSION
OUTCOMES_TEMPLATE_SCHEMA_VERSION = "standard-source-pack-v2"
STANDARD_TEMPLATE_SCHEMA_VERSION_V2 = OUTCOMES_TEMPLATE_SCHEMA_VERSION
PERIOD_COLUMN = "period_start"
MARKET_COLUMN = "market"

OUTCOME_DICTIONARY_V1_COLUMNS = ("outcome_id", "source_column")
OUTCOME_DICTIONARY_V2_COLUMNS = (
    "outcome_id",
    "source_column",
    "product",
    "metric_key",
    "metric",
    "segment_dimension",
    "segment",
    "outcome_group_id",
    "outcome_group_label",
    "outcome_family_key",
    "group_aggregation",
)
OUTCOME_COMPLETENESS_COLUMNS = (
    "outcome_id",
    "data_as_of_date",
    "model_start_week",
    "model_end_week",
    "latest_complete_net_billthrough_week",
    "maturity_rule_description",
    "source_owner",
)
_OUTCOME_DEFINITION_OPTIONAL_COLUMNS = (
    "unit",
    "aggregation_type",
    "date_basis",
    "maturity_required",
    "role",
    "included_in_fit",
    "include_in_default_reporting",
    "include_in_official_total",
    "include_in_value",
    "include_in_optimisation",
    "definition_version",
    "event_definition",
    "cohort_or_attribution_basis",
    "completeness_or_maturity_policy",
    "exclusions",
    "reconciliation_source",
    "business_owner",
    "effective_from",
    "effective_to",
    "value_weight",
    "value_currency",
)


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
    model_input_context: pd.DataFrame | None = None
    context_variable_metadata: tuple[dict[str, object], ...] = ()
    activity_semantic_mappings: tuple[dict[str, object], ...] = ()
    outcomes: pd.DataFrame | None = None
    experiment_evidence: pd.DataFrame | None = None
    outcome_definitions: tuple[OutcomeDefinition, ...] = ()
    outcome_groups: tuple[OutcomeGroupDefinition, ...] = ()
    outcome_reconciliation_groups: tuple[object, ...] = ()
    outcome_completeness_metadata: Mapping[str, NetBillthroughCompletenessMetadata] = (
        field(default_factory=dict)
    )


STANDARD_SHEET_SPECS: dict[str, tuple[SheetSpec, ...]] = {
    DOMAIN_OUTCOMES: (
        SheetSpec(
            "outcomes",
            (PERIOD_COLUMN, MARKET_COLUMN),
            "One row per observed period and market; measures remain separate columns.",
        ),
        SheetSpec(
            "outcome_dictionary",
            OUTCOME_DICTIONARY_V2_COLUMNS,
            "Required governed outcome metadata for source measures.",
        ),
        SheetSpec(
            "outcome_completeness",
            OUTCOME_COMPLETENESS_COLUMNS,
            "Optional source completeness metadata for supplied outcomes such as NBT.",
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

_ACTIVITY_V2_EXTRA_COLUMNS = (
    "model_input_unit",
    "model_input_kind",
    "spend_column",
    "response_unit_column",
    "response_unit",
    "currency",
    "effective_from",
    "effective_to",
)
_CONTEXT_V2_EXTRA_COLUMNS = (
    "source",
    "scope",
    "effective_from",
    "effective_to",
    "unit",
)
_CONTEXT_V2_SCHEMA_MARKERS = (
    "source",
    "scope",
    "effective_from",
    "effective_to",
)


def _outcome_v1_sheet_specs() -> tuple[SheetSpec, ...]:
    return (
        SheetSpec(
            "outcomes",
            (PERIOD_COLUMN, MARKET_COLUMN),
            "One row per observed period and market; measures remain separate columns.",
        ),
        SheetSpec(
            "outcome_dictionary",
            OUTCOME_DICTIONARY_V1_COLUMNS,
            "Legacy optional outcome-to-source-column mapping.",
            required=False,
        ),
    )


def standard_sheet_specs(
    logical_domain: str,
    *,
    schema_version: str | None = None,
) -> tuple[SheetSpec, ...]:
    if logical_domain == DOMAIN_OUTCOMES and schema_version == STANDARD_TEMPLATE_SCHEMA_VERSION:
        return _outcome_v1_sheet_specs()
    try:
        specs = STANDARD_SHEET_SPECS[logical_domain]
    except KeyError as exc:
        raise ValueError(
            f"unsupported standard logical domain {logical_domain!r}"
        ) from exc
    if schema_version == STANDARD_TEMPLATE_SCHEMA_VERSION_V2:
        extras = {
            DOMAIN_ACTIVITY_AND_MEDIA: {"activity_dictionary": _ACTIVITY_V2_EXTRA_COLUMNS},
            DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS: {
                "variable_dictionary": _CONTEXT_V2_EXTRA_COLUMNS
            },
        }.get(logical_domain, {})
        if extras:
            return tuple(
                SheetSpec(
                    item.sheet_name,
                    item.required_columns
                    + tuple(extras.get(item.sheet_name, ())),
                    item.description,
                    item.required,
                )
                for item in specs
            )
    return specs


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


def _table_named(
    tables: Mapping[str, pd.DataFrame], sheet_name: str
) -> pd.DataFrame | None:
    target = _normalise_sheet_name(sheet_name)
    for name, table in tables.items():
        if _normalise_sheet_name(name) == target:
            return table
    return None


def _detect_outcomes_schema_version(
    tables: Mapping[str, pd.DataFrame],
) -> tuple[str, str | None]:
    """Detect the Outcomes contract without interpreting outcome IDs.

    A missing dictionary, or a dictionary containing only the historical
    ``outcome_id``/``source_column`` mapping, remains v1.  Any v2-specific
    structural field opts the workbook into v2 validation so a partially
    populated richer dictionary fails clearly instead of being downgraded to
    an incomplete legacy mapping.
    """
    dictionary = _table_named(tables, "outcome_dictionary")
    if dictionary is None:
        return STANDARD_TEMPLATE_SCHEMA_VERSION, (
            "Outcomes workbook has no outcome_dictionary; it is loadable as a "
            "legacy/incomplete v1 mapping and needs semantic review."
        )
    columns = {str(column).strip() for column in dictionary.columns}
    v2_specific = set(OUTCOME_DICTIONARY_V2_COLUMNS) - set(
        OUTCOME_DICTIONARY_V1_COLUMNS
    )
    if columns.intersection(v2_specific):
        return OUTCOMES_TEMPLATE_SCHEMA_VERSION, None
    if set(OUTCOME_DICTIONARY_V1_COLUMNS).issubset(columns):
        return STANDARD_TEMPLATE_SCHEMA_VERSION, (
            "Outcomes workbook uses the legacy v1 outcome_dictionary; product, "
            "metric, breakdown, segment, and group semantics require analyst review."
        )
    return OUTCOMES_TEMPLATE_SCHEMA_VERSION, None


def _validate_tables(
    *,
    logical_domain: str,
    schema_version: str | None = None,
    sheet_names: Sequence[str],
    tables: Mapping[str, pd.DataFrame],
) -> tuple[list[ParsedTable], list[str], list[str], bool]:
    specs = standard_sheet_specs(logical_domain, schema_version=schema_version)
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
        tables = {name: pd.read_excel(excel, sheet_name=name) for name in sheet_names}
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
    selected_schema_version: str | None = None
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
    if selected_domain == DOMAIN_OUTCOMES and not errors:
        selected_schema_version, schema_warning = _detect_outcomes_schema_version(
            tables
        )
        if schema_warning:
            warnings.append(schema_warning)
    elif selected_domain in STANDARD_SHEET_SPECS:
        selected_schema_version = (
            STANDARD_TEMPLATE_SCHEMA_VERSION_V2
            if (
                selected_domain == DOMAIN_ACTIVITY_AND_MEDIA
                and _table_named(tables, "activity_dictionary") is not None
                and set(_ACTIVITY_V2_EXTRA_COLUMNS).intersection(
                    _table_named(tables, "activity_dictionary").columns
                )
            )
            or (
                selected_domain == DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS
                and _table_named(tables, "variable_dictionary") is not None
                and set(_CONTEXT_V2_SCHEMA_MARKERS).intersection(
                    _table_named(tables, "variable_dictionary").columns
                )
            )
            else STANDARD_TEMPLATE_SCHEMA_VERSION
        )
    parsed: list[ParsedTable] = []
    standard = False
    if selected_domain in STANDARD_SHEET_SPECS and not errors:
        parsed, domain_warnings, domain_errors, standard = _validate_tables(
            logical_domain=selected_domain,
            schema_version=selected_schema_version,
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
        template_schema_version=(selected_schema_version if standard else None),
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
    required = set(
        standard_template_columns(DOMAIN_ACTIVITY_AND_MEDIA, "activity_dictionary")
    )
    missing = sorted(required - set(activity_dictionary.columns))
    if missing:
        raise ValueError(f"activity dictionary is missing required columns: {missing}")

    def required_text(row: Mapping[str, Any], column: str) -> str:
        value = row.get(column)
        if value is None or pd.isna(value) or not str(value).strip():
            raise ValueError(f"activity dictionary column {column!r} must be populated")
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
                None
                if pd.isna(row.get("pooling_group_id"))
                else str(row["pooling_group_id"])
            ),
        }
        definitions.append(ActivityDefinition(**payload))
    identities = [(item.market, item.activity_id) for item in definitions]
    if len(identities) != len(set(identities)):
        raise ValueError(
            "activity dictionary contains duplicate market/activity_id rows"
        )
    return tuple(definitions)


def activity_semantic_mappings_from_dictionary(
    activity_dictionary: pd.DataFrame,
) -> tuple[dict[str, object], ...]:
    """Return explicit source mappings without creating a competing registry.

    The existing ``ActivityDefinition`` is authoritative for activity identity
    and fitted model-input columns.  The optional fields below are retained as
    source evidence for the existing media-unit/cost mapping workflow; they
    are never applied automatically because that workflow is governed at
    market x channel grain and may be ambiguous for multiple activities.
    """

    required = {"activity_id", "market", "model_input_column", "model_input_measure"}
    missing = sorted(required - set(activity_dictionary.columns))
    if missing:
        raise ValueError(f"activity dictionary is missing required columns: {missing}")
    optional = (
        "model_input_unit",
        "model_input_kind",
        "spend_column",
        "response_unit_column",
        "response_unit",
        "currency",
        "effective_from",
        "effective_to",
    )
    rows: list[dict[str, object]] = []
    for row in activity_dictionary.to_dict(orient="records"):
        item: dict[str, object] = {
            key: row.get(key)
            for key in ("activity_id", "market", "model_input_column", "model_input_measure")
        }
        for key in optional:
            value = row.get(key)
            item[key] = None if value is None or pd.isna(value) else value
        rows.append(item)
    return tuple(rows)


def _normalised_dictionary_frame(dictionary: pd.DataFrame) -> pd.DataFrame:
    frame = dictionary.copy()
    columns = [str(column).strip() for column in frame.columns]
    if len(columns) != len(set(columns)):
        raise ValueError("outcome dictionary contains duplicate column names")
    frame.columns = columns
    return frame


def _required_dictionary_text(
    row: Mapping[str, Any], column: str, *, row_number: int
) -> str:
    value = row.get(column)
    if value is None or pd.isna(value) or not str(value).strip():
        raise ValueError(
            f"outcome dictionary row {row_number} column {column!r} must be populated"
        )
    return str(value).strip()


def _optional_dictionary_text(row: Mapping[str, Any], column: str) -> str | None:
    value = row.get(column)
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    return str(value).strip()


def _dictionary_bool(value: Any, *, column: str, row_number: int) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    raise ValueError(
        f"outcome dictionary row {row_number} column {column!r} must be boolean"
    )


def _dictionary_schema_version(
    dictionary: pd.DataFrame, schema_version: str | None
) -> str:
    if schema_version is not None:
        return schema_version
    columns = {str(column).strip() for column in dictionary.columns}
    v2_specific_columns = set(OUTCOME_DICTIONARY_V2_COLUMNS) - set(
        OUTCOME_DICTIONARY_V1_COLUMNS
    )
    if columns.intersection(v2_specific_columns):
        return OUTCOMES_TEMPLATE_SCHEMA_VERSION
    return STANDARD_TEMPLATE_SCHEMA_VERSION


def _validate_dictionary_columns(
    dictionary: pd.DataFrame, *, schema_version: str
) -> None:
    required = (
        OUTCOME_DICTIONARY_V2_COLUMNS
        if schema_version == OUTCOMES_TEMPLATE_SCHEMA_VERSION
        else OUTCOME_DICTIONARY_V1_COLUMNS
    )
    missing = sorted(set(required) - set(dictionary.columns))
    if missing:
        raise ValueError(
            f"outcome dictionary for {schema_version} is missing required columns: {missing}"
        )


def outcome_definitions_from_dictionary(
    outcome_dictionary: pd.DataFrame,
    *,
    outcomes: pd.DataFrame | None = None,
    schema_version: str | None = None,
) -> tuple[OutcomeDefinition, ...]:
    """Build canonical outcome definitions without inferring business meaning.

    v2 requires explicit product, metric, breakdown, segment, and grouping
    columns. v1 remains loadable as a fail-closed, incomplete mapping: only
    ``outcome_id`` and ``source_column`` are retained, while all business
    dimensions stay blank/``unspecified`` and the definition is excluded from
    a new fit until an analyst supplies governed semantics.
    """
    dictionary = _normalised_dictionary_frame(outcome_dictionary)
    version = _dictionary_schema_version(dictionary, schema_version)
    _validate_dictionary_columns(dictionary, schema_version=version)
    available_columns = set(outcomes.columns) if outcomes is not None else None
    definitions: list[OutcomeDefinition] = []
    seen_ids: set[str] = set()
    source_semantics: dict[str, set[tuple[object, ...]]] = {}

    for row_index, raw_row in enumerate(dictionary.to_dict(orient="records"), start=2):
        outcome_id = _required_dictionary_text(
            raw_row, "outcome_id", row_number=row_index
        )
        source_column = _required_dictionary_text(
            raw_row, "source_column", row_number=row_index
        )
        if outcome_id in seen_ids:
            raise ValueError(
                f"duplicate outcome_id {outcome_id!r} in outcome dictionary"
            )
        seen_ids.add(outcome_id)
        if available_columns is not None and source_column not in available_columns:
            raise ValueError(
                f"outcome {outcome_id!r} maps to source column {source_column!r}, "
                "which is missing from the outcomes sheet"
            )

        if version != OUTCOMES_TEMPLATE_SCHEMA_VERSION:
            definitions.append(
                OutcomeDefinition(
                    outcome_id=outcome_id,
                    product="",
                    segment="",
                    metric="",
                    source_column=source_column,
                    included_in_fit=False,
                )
            )
            continue

        product = _required_dictionary_text(raw_row, "product", row_number=row_index)
        metric_key = _required_dictionary_text(
            raw_row, "metric_key", row_number=row_index
        )
        metric = _required_dictionary_text(raw_row, "metric", row_number=row_index)
        segment_dimension = _required_dictionary_text(
            raw_row, "segment_dimension", row_number=row_index
        )
        segment = _required_dictionary_text(raw_row, "segment", row_number=row_index)
        if product not in KNOWN_PRODUCTS:
            raise ValueError(f"outcome {outcome_id!r} has unknown product {product!r}")
        if metric_key != METRIC_KEY_CUSTOM and metric_key not in METRIC_REGISTRY:
            raise ValueError(
                f"outcome {outcome_id!r} has unknown metric_key {metric_key!r}; "
                "metric keys must match the governed registry exactly"
            )
        if segment_dimension not in SEGMENT_DIMENSIONS:
            raise ValueError(
                f"outcome {outcome_id!r} has unknown segment_dimension "
                f"{segment_dimension!r}"
            )

        payload: dict[str, Any] = {
            "outcome_id": outcome_id,
            "product": product,
            "segment": segment,
            "metric": metric,
            "source_column": source_column,
            "metric_key": metric_key,
            "segment_dimension": segment_dimension,
        }
        for column in _OUTCOME_DEFINITION_OPTIONAL_COLUMNS:
            if column not in dictionary.columns:
                continue
            value = raw_row.get(column)
            if (
                value is None
                or pd.isna(value)
                or (isinstance(value, str) and not value.strip())
            ):
                continue
            if column in {
                "included_in_fit",
                "include_in_default_reporting",
                "include_in_official_total",
                "include_in_value",
                "include_in_optimisation",
            }:
                payload[column] = _dictionary_bool(
                    value, column=column, row_number=row_index
                )
            elif column == "maturity_required":
                payload[column] = _dictionary_bool(
                    value, column=column, row_number=row_index
                )
            elif column == "value_weight":
                try:
                    payload[column] = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"outcome dictionary row {row_index} column 'value_weight' "
                        "must be numeric"
                    ) from exc
            else:
                payload[column] = value.strip() if isinstance(value, str) else value
        definitions.append(OutcomeDefinition(**payload))
        source_semantics.setdefault(source_column, set()).add(
            (
                product,
                metric_key,
                segment_dimension,
                segment,
                definitions[-1].unit,
                definitions[-1].aggregation_type,
            )
        )

    if version == OUTCOMES_TEMPLATE_SCHEMA_VERSION:
        errors = validate_outcome_definitions(
            definitions, available_columns=available_columns
        )
        for source_column, semantics in source_semantics.items():
            if len(semantics) > 1:
                errors.append(
                    f"Source column {source_column!r} is mapped to incompatible "
                    "outcome definitions; provide one explicit business meaning per column."
                )
        if errors:
            raise ValueError("; ".join(errors))
    return tuple(definitions)


def outcome_groups_from_dictionary(
    outcome_dictionary: pd.DataFrame,
    *,
    outcomes: Sequence[OutcomeDefinition] | None = None,
    schema_version: str | None = None,
) -> tuple[OutcomeGroupDefinition, ...]:
    """Build semantic groups from explicit v2 dictionary rows.

    Blank group IDs are a supported explicit not-applicable state. No group
    is inferred from a metric, segment, or outcome ID.
    """
    dictionary = _normalised_dictionary_frame(outcome_dictionary)
    version = _dictionary_schema_version(dictionary, schema_version)
    _validate_dictionary_columns(dictionary, schema_version=version)
    if version != OUTCOMES_TEMPLATE_SCHEMA_VERSION:
        return ()
    definitions = (
        tuple(outcomes)
        if outcomes is not None
        else outcome_definitions_from_dictionary(dictionary, schema_version=version)
    )
    by_group: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for row_index, raw_row in enumerate(dictionary.to_dict(orient="records"), start=2):
        outcome_id = _required_dictionary_text(
            raw_row, "outcome_id", row_number=row_index
        )
        group_id = _optional_dictionary_text(raw_row, "outcome_group_id")
        group_label = _optional_dictionary_text(raw_row, "outcome_group_label")
        family_key = _optional_dictionary_text(raw_row, "outcome_family_key")
        aggregation = _optional_dictionary_text(raw_row, "group_aggregation")
        group_values = (group_label, family_key, aggregation)
        if group_id is None:
            if any(value is not None for value in group_values):
                errors.append(
                    f"outcome dictionary row {row_index} has group metadata without "
                    "an outcome_group_id; use an explicit blank/not-applicable group"
                )
            continue
        if not all(value is not None for value in group_values):
            errors.append(
                f"outcome dictionary row {row_index} group {group_id!r} must populate "
                "outcome_group_label, outcome_family_key, and group_aggregation"
            )
            continue
        product = _required_dictionary_text(raw_row, "product", row_number=row_index)
        segment_dimension = _required_dictionary_text(
            raw_row, "segment_dimension", row_number=row_index
        )
        candidate = {
            "group_id": group_id,
            "group_label": group_label,
            "product": product,
            "outcome_family_key": family_key,
            "segment_dimension": segment_dimension,
            "member_outcome_ids": [outcome_id],
            "aggregation_rule": aggregation,
            "supplied_total_outcome_id": _optional_dictionary_text(
                raw_row, "supplied_total_outcome_id"
            ),
        }
        existing = by_group.get(group_id)
        if existing is None:
            by_group[group_id] = candidate
        else:
            for field_name in (
                "group_label",
                "product",
                "outcome_family_key",
                "segment_dimension",
                "aggregation_rule",
                "supplied_total_outcome_id",
            ):
                if existing[field_name] != candidate[field_name]:
                    errors.append(
                        f"outcome group {group_id!r} has inconsistent {field_name} "
                        f"between dictionary rows"
                    )
            existing["member_outcome_ids"].append(outcome_id)
    if errors:
        raise ValueError("; ".join(errors))
    groups = tuple(OutcomeGroupDefinition(**payload) for payload in by_group.values())
    group_errors = validate_outcome_group_definitions(groups, outcomes=definitions)
    if group_errors:
        raise ValueError("; ".join(group_errors))
    return groups


def outcome_completeness_metadata_from_table(
    completeness_table: pd.DataFrame,
    outcomes: Sequence[OutcomeDefinition],
) -> dict[str, NetBillthroughCompletenessMetadata]:
    """Bind supplied completeness rows to current NBT definitions.

    The source supplies dates and the maturity description only. The parser
    computes the current definition fingerprint and never reconstructs NBT
    from billing events or manufactures an approval record.
    """
    table = _normalised_dictionary_frame(completeness_table)
    missing = sorted(set(OUTCOME_COMPLETENESS_COLUMNS) - set(table.columns))
    if missing:
        raise ValueError(f"outcome_completeness is missing required columns: {missing}")
    by_id = {outcome.outcome_id: outcome for outcome in outcomes}
    result: dict[str, NetBillthroughCompletenessMetadata] = {}
    errors: list[str] = []
    for row_index, raw_row in enumerate(table.to_dict(orient="records"), start=2):
        outcome_id = _required_dictionary_text(
            raw_row, "outcome_id", row_number=row_index
        )
        if outcome_id in result:
            errors.append(
                f"duplicate outcome_id {outcome_id!r} in outcome_completeness"
            )
            continue
        outcome = by_id.get(outcome_id)
        if outcome is None:
            errors.append(
                f"outcome_completeness references unknown outcome_id {outcome_id!r}"
            )
            continue
        if outcome.metric_key != NBT_METRIC_KEY:
            errors.append(
                f"outcome_completeness row {row_index} targets {outcome_id!r}, "
                "which is not a Net Bill Through count outcome"
            )
            continue
        payload = {
            column: _required_dictionary_text(raw_row, column, row_number=row_index)
            for column in OUTCOME_COMPLETENESS_COLUMNS
            if column != "outcome_id"
        }
        metadata = NetBillthroughCompletenessMetadata(
            outcome_id=outcome_id,
            definition_version=outcome.definition_version,
            definition_fingerprint=fingerprint_outcome_definition(outcome),
            **payload,
        )
        issues = validate_nbt_completeness_metadata_for_outcome(outcome, metadata)
        if issues:
            errors.extend(f"outcome {outcome_id!r}: {issue}" for issue in issues)
        result[outcome_id] = metadata
    if errors:
        raise ValueError("; ".join(errors))
    return result


def canonicalize_activity_data(
    activity_data: pd.DataFrame,
    activity_dictionary: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[ActivityDefinition, ...], dict[tuple[str, str], str]]:
    """Pivot tidy activity observations into the existing wide input boundary.

    The pivot is driven only by the dictionary's explicit
    ``model_input_measure`` and ``model_input_column``. Missing activity rows
    remain missing after the pivot; no zero or frequency fill is invented.
    """
    required = set(
        standard_template_columns(DOMAIN_ACTIVITY_AND_MEDIA, "activity_data")
    )
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
        definition = definition_by_key.get(
            (market_text, activity_text)
        ) or wildcard_by_id.get(activity_text)
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
    wide = long.pivot(
        index=[PERIOD_COLUMN, MARKET_COLUMN],
        columns="model_input_column",
        values="model_input_value",
    ).reset_index()
    wide.columns.name = None
    for model_column in mapping.values():
        if model_column not in wide.columns:
            wide[model_column] = pd.NA
    ordered = [PERIOD_COLUMN, MARKET_COLUMN, *dict.fromkeys(mapping.values())]
    return wide[ordered], definitions, mapping


def canonicalize_context_data(
    context_data: pd.DataFrame,
    variable_dictionary: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[dict[str, object], ...]]:
    """Pivot tidy context observations at the explicit model-input boundary.

    This is a lossless reshape only. It does not aggregate duplicate rows,
    repeat native-frequency observations, or infer a future control role.
    Native frequency and all dictionary metadata remain in the returned
    semantic records for coverage/frequency review.
    """

    required_data = {PERIOD_COLUMN, MARKET_COLUMN, "variable_id", "value", "native_frequency"}
    missing_data = sorted(required_data - set(context_data.columns))
    if missing_data:
        raise ValueError(f"context data is missing required columns: {missing_data}")
    required_dictionary = {"variable_id", "variable_class", "native_frequency", "role"}
    missing_dictionary = sorted(required_dictionary - set(variable_dictionary.columns))
    if missing_dictionary:
        raise ValueError(
            f"variable dictionary is missing required columns: {missing_dictionary}"
        )
    dictionary_ids = set(variable_dictionary["variable_id"].astype(str))
    unknown_ids = sorted(
        set(context_data["variable_id"].astype(str)) - dictionary_ids
    )
    if unknown_ids:
        raise ValueError(
            "context data contains variable_id values without dictionary metadata: "
            + ", ".join(unknown_ids)
        )
    tidy = context_data.copy()
    tidy[PERIOD_COLUMN] = pd.to_datetime(tidy[PERIOD_COLUMN])
    tidy["variable_id"] = tidy["variable_id"].astype(str)
    key_columns = [PERIOD_COLUMN, MARKET_COLUMN, "variable_id"]
    if tidy.duplicated(key_columns, keep=False).any():
        raise ValueError(
            "context data has duplicate period/market/variable rows; no implicit "
            "aggregation is approved for source-pack adoption"
        )
    wide = (
        tidy.pivot(
            index=[PERIOD_COLUMN, MARKET_COLUMN],
            columns="variable_id",
            values="value",
        )
        .reset_index()
    )
    wide.columns.name = None
    metadata_columns = (
        "variable_id",
        "variable_class",
        "native_frequency",
        "role",
        "source",
        "scope",
        "effective_from",
        "effective_to",
        "unit",
    )
    metadata = []
    for row in variable_dictionary.to_dict(orient="records"):
        metadata.append(
            {
                column: (
                    None
                    if row.get(column) is None or pd.isna(row.get(column))
                    else row.get(column)
                )
                for column in metadata_columns
            }
        )
    return wide, tuple(metadata)


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
            activity_semantic_mappings=activity_semantic_mappings_from_dictionary(
                workbook.tables["activity_dictionary"]
            ),
        )
    if domain == DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS:
        context_model_input, context_metadata = canonicalize_context_data(
            workbook.tables["context_data"], workbook.tables["variable_dictionary"]
        )
        return CanonicalSourceBundle(
            manifest=workbook.manifest,
            raw_tables=workbook.tables,
            activity_definitions=(),
            model_input_media=pd.DataFrame(),
            activity_column_map={},
            native_context_data=workbook.tables["context_data"].copy(),
            model_input_context=context_model_input,
            context_variable_metadata=context_metadata,
        )
    if domain == DOMAIN_OUTCOMES:
        dictionary = _table_named(workbook.tables, "outcome_dictionary")
        outcome_definitions = (
            outcome_definitions_from_dictionary(
                dictionary,
                outcomes=workbook.tables["outcomes"],
                schema_version=workbook.manifest.template_schema_version,
            )
            if dictionary is not None
            else ()
        )
        groups = (
            outcome_groups_from_dictionary(
                dictionary,
                outcomes=outcome_definitions,
                schema_version=workbook.manifest.template_schema_version,
            )
            if dictionary is not None
            else ()
        )
        reconciliation_groups = tuple(
            OutcomeReconciliationGroup(
                group_id=group.group_id,
                component_outcome_ids=list(group.member_outcome_ids),
                relation="sum",
                total_outcome_id=group.supplied_total_outcome_id,
            )
            for group in groups
            if group.aggregation_rule == "sum"
            and group.supplied_total_outcome_id is not None
        )
        completeness_table = _table_named(workbook.tables, "outcome_completeness")
        completeness = (
            outcome_completeness_metadata_from_table(
                completeness_table, outcome_definitions
            )
            if completeness_table is not None
            else {}
        )
        return CanonicalSourceBundle(
            manifest=workbook.manifest,
            raw_tables=workbook.tables,
            activity_definitions=(),
            model_input_media=pd.DataFrame(),
            activity_column_map={},
            outcomes=workbook.tables["outcomes"].copy(),
            outcome_definitions=outcome_definitions,
            outcome_groups=groups,
            outcome_reconciliation_groups=reconciliation_groups,
            outcome_completeness_metadata=completeness,
        )
    return CanonicalSourceBundle(
        manifest=workbook.manifest,
        raw_tables=workbook.tables,
        activity_definitions=(),
        model_input_media=pd.DataFrame(),
        activity_column_map={},
        experiment_evidence=workbook.tables.get("experiment_evidence"),
    )
