"""Application boundary for governed weekly valuation uploads."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from ancestry_mmm.core.outcome_valuation import (
    WeeklyOutcomeValuationRecord,
    validate_weekly_outcome_valuation_catalogue,
)


OUTCOME_VALUATION_UPLOAD_COLUMNS = (
    "valuation_kind",
    "market",
    "week",
    "segment",
    "denominator_outcome_id",
    "quality_status",
    "segment_dimension",
    "aggregate_value",
    "currency",
    "source",
    "source_version",
    "schema_version",
    "horizon_months",
)


def _optional(value: Any) -> Any:
    return None if pd.isna(value) else value


def _required_text(value: Any) -> str:
    optional = _optional(value)
    return "" if optional is None else str(optional).strip()


def build_weekly_outcome_valuation_records(
    rows: pd.DataFrame,
    *,
    outcome_definitions: Sequence[object],
) -> list[WeeklyOutcomeValuationRecord]:
    """Parse and validate exact Finance/Analytics valuation rows.

    The upload is intentionally additive and exact.  A blank value is only
    accepted where the record's governed quality state says the value is
    absent; this function never estimates or copies historical values.
    """
    if not isinstance(rows, pd.DataFrame):
        raise ValueError("valuation input must be a table")
    missing = [
        column
        for column in OUTCOME_VALUATION_UPLOAD_COLUMNS
        if column not in rows.columns
    ]
    if missing:
        raise ValueError(
            "valuation input is missing required fields: " + ", ".join(missing)
        )
    records: list[WeeklyOutcomeValuationRecord] = []
    for index, row in rows.loc[:, list(OUTCOME_VALUATION_UPLOAD_COLUMNS)].iterrows():
        payload: Mapping[str, Any] = {
            "valuation_kind": _required_text(row["valuation_kind"]),
            "market": _required_text(row["market"]),
            "week": str(pd.Timestamp(row["week"]).date()),
            "segment": _required_text(row["segment"]),
            "denominator_outcome_id": _required_text(row["denominator_outcome_id"]),
            "quality_status": _required_text(row["quality_status"]),
            "segment_dimension": _required_text(row["segment_dimension"]),
            "aggregate_value": _optional(row["aggregate_value"]),
            "currency": _optional(row["currency"]),
            "source": _required_text(row["source"]),
            "source_version": _required_text(row["source_version"]),
            "schema_version": int(row["schema_version"]),
            "horizon_months": (
                int(row["horizon_months"])
                if _optional(row["horizon_months"]) is not None
                else None
            ),
        }
        if not payload["source"] or not payload["source_version"]:
            raise ValueError(
                f"valuation row {index + 1} requires source and source_version"
            )
        try:
            records.append(WeeklyOutcomeValuationRecord(**payload))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"valuation row {index + 1} is invalid: {exc}") from exc
    issues = validate_weekly_outcome_valuation_catalogue(records, outcome_definitions)
    errors = [issue for issue in issues if "more than one currency" not in str(issue)]
    if errors:
        raise ValueError("valuation catalogue is invalid: " + "; ".join(errors))
    return records


__all__ = [
    "OUTCOME_VALUATION_UPLOAD_COLUMNS",
    "build_weekly_outcome_valuation_records",
]
