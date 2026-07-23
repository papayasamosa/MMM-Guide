"""Validation for authoritative, uploaded Family History net bill-through.

Net bill-through is an input KPI, not a transformation performed by the MMM.
This module deliberately contains no signup, billing, cancellation, refund,
offer or maturity-estimation logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List, Sequence

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


def _outcome_value(outcome: object, key: str, default=None):
    if isinstance(outcome, dict):
        return outcome.get(key, default)
    return getattr(outcome, key, default)


def validate_supplied_net_billthrough(
    data: pd.DataFrame,
    metadata: NetBillthroughCompletenessMetadata | None,
    *,
    configured_markets: Sequence[str] | None = None,
    configured_segments: Sequence[str] | None = None,
    configured_outcomes: Sequence[object] | None = None,
    value_column: str = NBT_METRIC_KEY,
    week_column: str = "week_start",
    market_column: str = "market",
    segment_column: str = "segment",
) -> List[str]:
    """Validate canonical long or wide weekly net bill-through data."""
    if metadata is None:
        return [
            "Model training blocked: net bill-through completeness metadata is required."
        ]
    if isinstance(metadata, dict):
        metadata = NetBillthroughCompletenessMetadata.from_dict(metadata)

    errors: List[str] = []
    required = {week_column, market_column}
    missing_columns = sorted(required - set(data.columns))
    if missing_columns:
        return [
            f"Supplied net bill-through data is missing columns: {missing_columns}."
        ]

    if metadata.metric_key != NBT_METRIC_KEY or metadata.date_basis != NBT_DATE_BASIS:
        errors.append(
            "Net bill-through must use metric_key 'fh_net_billthrough_count' "
            "and signup_date_attributed, not finance-date GSA."
        )
    if metadata.aggregation_type != "count" or metadata.unit != NBT_UNIT:
        errors.append(
            "Net bill-through must be a count measured in bill-through subscribers."
        )

    try:
        start = pd.Timestamp(metadata.model_start_week).normalize()
        end = pd.Timestamp(metadata.model_end_week).normalize()
        latest = pd.Timestamp(metadata.latest_complete_net_billthrough_week).normalize()
        as_of = pd.Timestamp(metadata.data_as_of_date).normalize()
    except (TypeError, ValueError):
        return errors + [
            "Net bill-through completeness metadata contains invalid dates."
        ]
    if start > end:
        errors.append("model_start_week must not be after model_end_week.")
        return errors
    if latest < end:
        errors.append(
            f"Model training blocked: latest complete net bill-through week "
            f"{latest.date()} is earlier than model end week {end.date()}."
        )
    if latest > as_of:
        errors.append(
            "latest_complete_net_billthrough_week cannot be after data_as_of_date."
        )
    if (
        not metadata.maturity_rule_description.strip()
        or not metadata.source_owner.strip()
    ):
        errors.append(
            "Net bill-through metadata requires a maturity rule and source owner."
        )

    frame = data.copy()
    frame[week_column] = pd.to_datetime(
        frame[week_column], errors="coerce"
    ).dt.normalize()
    if frame[week_column].isna().any():
        errors.append("Net bill-through contains invalid week values.")
    before_start = frame[week_column] < start
    after_end = frame[week_column] > end
    if before_start.any() or after_end.any():
        errors.append(
            "Net bill-through coverage must exactly match the configured model window; "
            f"found {int(before_start.sum())} row(s) before and {int(after_end.sum())} row(s) after it."
        )

    within = frame[frame[week_column].between(start, end, inclusive="both")].copy()
    expected_weeks = set(pd.date_range(start, end, freq="7D"))
    unexpected_weeks = sorted(set(within[week_column].dropna()) - expected_weeks)
    if unexpected_weeks:
        errors.append(
            "Net bill-through uses an incorrect weekly anchor; every date must be "
            f"7 days from {start.date()}."
        )

    configured_outcomes = list(configured_outcomes or [])
    if configured_outcomes:
        configured_outcomes = [
            outcome
            for outcome in configured_outcomes
            if _outcome_value(outcome, "metric_key") == NBT_METRIC_KEY
        ]
    markets_default = [str(m) for m in (configured_markets or [])]

    def validate_values(values: pd.Series, label: str) -> None:
        numeric = pd.to_numeric(values, errors="coerce")
        if numeric.isna().any():
            errors.append(
                f"Net bill-through counts for {label} contain missing or non-numeric values."
            )
        valid = numeric.dropna()
        if (valid < 0).any():
            errors.append(f"Net bill-through counts for {label} must be non-negative.")
        if not np.allclose(valid, np.round(valid), atol=1e-8):
            errors.append(f"Net bill-through counts for {label} must be integer-like.")

    # Canonical wide form: one row per market/week, one source column per
    # configured outcome. This is the shape consumed by the model preprocessor.
    if configured_outcomes:
        duplicate_count = int(
            within.duplicated([market_column, week_column], keep=False).sum()
        )
        if duplicate_count:
            errors.append(
                f"Net bill-through contains {duplicate_count} duplicate market × week row(s)."
            )
        for outcome in configured_outcomes:
            source_column = _outcome_value(outcome, "source_column", value_column)
            segment = str(_outcome_value(outcome, "segment", "unknown"))
            outcome_markets = (
                _outcome_value(outcome, "markets", None) or markets_default
            )
            if source_column not in within.columns:
                errors.append(
                    f"Supplied net bill-through data is missing outcome column '{source_column}'."
                )
                continue
            for market in [str(m) for m in outcome_markets]:
                rows = within[within[market_column].astype(str) == market]
                missing_weeks = sorted(expected_weeks - set(rows[week_column].dropna()))
                if missing_weeks:
                    errors.append(
                        f"Net bill-through is missing {len(missing_weeks)} week(s) for "
                        f"market '{market}', segment '{segment}', outcome '{source_column}'."
                    )
                validate_values(
                    rows[source_column], f"market '{market}', segment '{segment}'"
                )
        return errors

    # Canonical long form: one row per market/segment/week with a shared
    # fh_net_billthrough_count value column.
    required_long = {segment_column, value_column}
    missing_long = sorted(required_long - set(within.columns))
    if missing_long:
        return errors + [
            f"Supplied net bill-through data is missing columns: {missing_long}."
        ]
    duplicate_count = int(
        within.duplicated(
            [market_column, segment_column, week_column], keep=False
        ).sum()
    )
    if duplicate_count:
        errors.append(
            f"Net bill-through contains {duplicate_count} duplicate market × segment × week row(s)."
        )
    validate_values(within[value_column], "the prepared long frame")
    markets = markets_default or sorted(
        within[market_column].dropna().astype(str).unique()
    )
    segments = [str(s) for s in (configured_segments or [])] or sorted(
        within[segment_column].dropna().astype(str).unique()
    )
    configured_pairs = {(market, segment) for market in markets for segment in segments}
    actual_pairs = set(
        zip(within[market_column].astype(str), within[segment_column].astype(str))
    )
    absent_pairs = sorted(configured_pairs - actual_pairs)
    if absent_pairs:
        errors.append(
            f"Net bill-through is missing configured market × segment combinations: {absent_pairs}."
        )
    for market, segment in sorted(configured_pairs & actual_pairs):
        rows = within[
            (within[market_column].astype(str) == market)
            & (within[segment_column].astype(str) == segment)
        ]
        missing_weeks = sorted(expected_weeks - set(rows[week_column].dropna()))
        if missing_weeks:
            errors.append(
                f"Net bill-through is missing {len(missing_weeks)} week(s) for "
                f"market '{market}', segment '{segment}'."
            )
    return errors


def assert_supplied_net_billthrough_complete(*args, **kwargs) -> None:
    """Raise before model construction when the authoritative KPI is invalid."""
    errors = validate_supplied_net_billthrough(*args, **kwargs)
    if errors:
        raise ValueError(
            "Model training blocked by net bill-through validation:\n"
            + "\n".join(errors)
        )


def assert_model_frame_net_billthrough_complete(frame: dict) -> None:
    """Defensive training gate for frames that bypassed the preprocessor."""
    outcomes = list(frame.get("outcomes") or [])
    nbt = [o for o in outcomes if _outcome_value(o, "metric_key") == NBT_METRIC_KEY]
    if not nbt:
        return
    y = np.asarray(frame.get("Y"))
    market_idx = np.asarray(frame.get("market_idx"))
    markets = list(frame.get("markets") or [])
    validation = pd.DataFrame(
        {
            "week_start": pd.to_datetime(frame.get("dates")),
            "market": [markets[int(index)] for index in market_idx],
        }
    )
    configured = []
    outcome_ids = list(frame.get("outcome_ids") or [])
    for outcome in nbt:
        outcome_id = _outcome_value(outcome, "outcome_id")
        position = outcome_ids.index(outcome_id)
        source_column = f"__nbt_validation_{position}"
        validation[source_column] = y[:, position]
        configured.append(
            {
                "metric_key": NBT_METRIC_KEY,
                "source_column": source_column,
                "segment": _outcome_value(outcome, "segment", "unknown"),
                "markets": markets,
            }
        )
    assert_supplied_net_billthrough_complete(
        validation,
        frame.get("net_billthrough_metadata"),
        configured_outcomes=configured,
    )
