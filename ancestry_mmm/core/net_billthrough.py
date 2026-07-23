"""Validation for authoritative, uploaded Family History net bill-through.

Net bill-through is an input KPI, not a transformation performed by the MMM.
This module deliberately contains no signup, billing, cancellation, refund,
offer or maturity-estimation logic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, List, Sequence

import numpy as np
import pandas as pd

NBT_METRIC_KEY = "fh_net_billthrough_count"
NBT_DATE_BASIS = "signup_date_attributed"
NBT_UNIT = "bill-through subscriber"


@dataclass(frozen=True)
class NetBillthroughCompletenessMetadata:
    data_as_of_date: str
    model_start_week: str
    model_end_week: str
    latest_complete_net_billthrough_week: str
    maturity_rule_description: str
    source_owner: str
    metric_key: str = NBT_METRIC_KEY
    aggregation_type: str = "count"
    date_basis: str = NBT_DATE_BASIS
    unit: str = NBT_UNIT

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "NetBillthroughCompletenessMetadata":
        known = cls.__dataclass_fields__
        return cls(**{key: item for key, item in value.items() if key in known})


def validate_supplied_net_billthrough(
    data: pd.DataFrame,
    metadata: NetBillthroughCompletenessMetadata,
    *,
    configured_markets: Sequence[str],
    configured_segments: Sequence[str],
    value_column: str = NBT_METRIC_KEY,
    week_column: str = "week_start",
    market_column: str = "market",
    segment_column: str = "segment",
) -> List[str]:
    """Validate the uploaded weekly KPI and return all blocking errors.

    Rows after ``model_end_week`` are rejected rather than silently entering a
    fit. Every market/segment combination must have exactly one row for every
    weekly date in the inclusive modelling window.
    """
    errors: List[str] = []
    required = {week_column, market_column, segment_column, value_column}
    missing_columns = sorted(required - set(data.columns))
    if missing_columns:
        return [f"Supplied net bill-through data is missing columns: {missing_columns}."]

    if metadata.metric_key != NBT_METRIC_KEY or metadata.date_basis != NBT_DATE_BASIS:
        errors.append("Net bill-through must use metric_key 'fh_net_billthrough_count' and signup_date_attributed, not finance-date GSA.")
    if metadata.aggregation_type != "count" or metadata.unit != NBT_UNIT:
        errors.append("Net bill-through must be a count measured in bill-through subscribers.")

    start = pd.Timestamp(metadata.model_start_week).normalize()
    end = pd.Timestamp(metadata.model_end_week).normalize()
    latest = pd.Timestamp(metadata.latest_complete_net_billthrough_week).normalize()
    if latest < end:
        errors.append(f"Model training blocked: latest complete net bill-through week {latest.date()} is earlier than model end week {end.date()}.")
    if start > end:
        errors.append("model_start_week must not be after model_end_week.")
        return errors

    frame = data.copy()
    frame[week_column] = pd.to_datetime(frame[week_column], errors="coerce").dt.normalize()
    if frame[week_column].isna().any():
        errors.append("Net bill-through contains invalid week values.")
    after_end = frame[week_column] > end
    if after_end.any():
        errors.append(f"Net bill-through contains {int(after_end.sum())} row(s) after the stated model end week; trim them explicitly before training.")

    within = frame[frame[week_column].between(start, end, inclusive="both")]
    keys = [market_column, segment_column, week_column]
    duplicate_count = int(within.duplicated(keys, keep=False).sum())
    if duplicate_count:
        errors.append(f"Net bill-through contains {duplicate_count} duplicate market × segment × week row(s).")

    numeric = pd.to_numeric(within[value_column], errors="coerce")
    if numeric.isna().any():
        errors.append("Net bill-through counts contain missing or non-numeric values.")
    if (numeric.dropna() < 0).any():
        errors.append("Net bill-through counts must be non-negative.")
    if not np.allclose(numeric.dropna(), np.round(numeric.dropna()), atol=1e-8):
        errors.append("Net bill-through counts must be integer-like.")

    expected_weeks = set(pd.date_range(start, end, freq="7D"))
    configured_pairs = {(str(m), str(s)) for m in configured_markets for s in configured_segments}
    actual_pairs = set(zip(within[market_column].astype(str), within[segment_column].astype(str)))
    absent_pairs = sorted(configured_pairs - actual_pairs)
    if absent_pairs:
        errors.append(f"Net bill-through is missing configured market × segment combinations: {absent_pairs}.")
    for market, segment in sorted(configured_pairs & actual_pairs):
        rows = within[(within[market_column].astype(str) == market) & (within[segment_column].astype(str) == segment)]
        missing_weeks = sorted(expected_weeks - set(rows[week_column].dropna()))
        if missing_weeks:
            errors.append(f"Net bill-through is missing {len(missing_weeks)} week(s) for market '{market}', segment '{segment}'.")
    return errors


def assert_supplied_net_billthrough_complete(*args, **kwargs) -> None:
    """Raise before model construction when the authoritative KPI is invalid."""
    errors = validate_supplied_net_billthrough(*args, **kwargs)
    if errors:
        raise ValueError("\n".join(errors))
