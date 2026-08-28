"""Weekly segment-level value-per-outcome rate derivation (REQ-ECON-003
Requirements 1-2).

This module derives ``value_per_unit(market, week, segment) =
aggregate_value / denominator_count`` from a governed
`WeeklyOutcomeValuationRecord` catalogue (REQ-ECON-002) and the
corresponding already-observed denominator-outcome counts. It
implements only the rate-derivation step and its fail-closed
missing-data/zero-denominator semantics.

It deliberately does not join a derived rate to any posterior draw
(REQ-ECON-003 Requirement 3, WP2C), does not propagate posterior
uncertainty (Requirement 4, WP2C), and does not implement the forward/
scenario-assumption path (Requirement 5, WP2G).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import pandas as pd

from .outcome_valuation import WeeklyOutcomeValuationRecord


@dataclass(frozen=True)
class WeeklyValueRate:
    """One derived ``value_per_unit`` for a single governed valuation
    cell (REQ-ECON-003 Requirement 1). This is always a *derived*
    quantity - it is never itself supplied or hand-entered."""

    valuation_kind: str
    market: str
    week: str
    segment: str
    value_per_unit: float
    currency: str
    is_zero_denominator_carve_out: bool
    source_record_fingerprint: str

    def cell_key(self) -> tuple:
        return (self.valuation_kind, self.market, self.week, self.segment)


def _lookup_observed_counts(
    observed_denominator_counts: pd.DataFrame,
    *,
    market_column: str,
    week_column: str,
    segment_column: str,
    outcome_id_column: str,
    count_column: str,
) -> Dict[tuple, Any]:
    frame = observed_denominator_counts.copy()
    frame[week_column] = pd.to_datetime(frame[week_column], errors="coerce")
    lookup: Dict[tuple, Any] = {}
    for _, row in frame.iterrows():
        key = (
            str(row[outcome_id_column]),
            str(row[market_column]),
            pd.Timestamp(row[week_column]).normalize(),
            str(row[segment_column]),
        )
        lookup[key] = row[count_column]
    return lookup


def derive_weekly_value_rates(
    records: Sequence[WeeklyOutcomeValuationRecord],
    observed_denominator_counts: pd.DataFrame,
    *,
    market_column: str = "market",
    week_column: str = "week",
    segment_column: str = "segment",
    outcome_id_column: str = "outcome_id",
    count_column: str = "count",
) -> Tuple[List[WeeklyValueRate], List[str]]:
    """Derive a `WeeklyValueRate` for every record whose cell is
    internally consistent; every inconsistent cell is reported as a
    blocking issue instead of a fabricated or guessed rate
    (REQ-ECON-003 Requirement 2).

    Returns ``(rates, blocking_issues)``. A cell missing from
    ``observed_denominator_counts`` entirely produces neither a rate nor
    an issue here - no observed data was supplied to derive a rate from,
    which is a data-completeness question upstream of this function, not
    a rate-derivation inconsistency.
    """
    rates: List[WeeklyValueRate] = []
    issues: List[str] = []

    lookup = _lookup_observed_counts(
        observed_denominator_counts,
        market_column=market_column,
        week_column=week_column,
        segment_column=segment_column,
        outcome_id_column=outcome_id_column,
        count_column=count_column,
    )

    for index, record in enumerate(records):
        try:
            week_ts = pd.Timestamp(record.week).normalize()
        except (TypeError, ValueError):
            issues.append(
                f"Row {index}: cannot derive a rate for invalid week '{record.week}'."
            )
            continue

        key = (record.denominator_outcome_id, record.market, week_ts, record.segment)
        if key not in lookup:
            continue  # no observed denominator supplied for this cell - not this function's concern

        observed_count = lookup[key]
        denominator_missing = pd.isna(observed_count)
        denominator_is_zero = (not denominator_missing) and observed_count == 0

        if record.aggregate_value is None:
            if denominator_is_zero:
                # REQ-ECON-003 Requirement 2 / REQ-ECON-002 Requirement 8:
                # a genuinely zero denominator legitimately explains an
                # absent valuation record - contributes a rate of exactly
                # zero, never a division and never a fabricated non-zero
                # number.
                rates.append(
                    WeeklyValueRate(
                        valuation_kind=record.valuation_kind,
                        market=record.market,
                        week=record.week,
                        segment=record.segment,
                        value_per_unit=0.0,
                        currency=record.currency or "",
                        is_zero_denominator_carve_out=True,
                        source_record_fingerprint=record.fingerprint(),
                    )
                )
            else:
                issues.append(
                    f"Row {index}: cannot derive a rate for "
                    f"market='{record.market}', week='{record.week}', "
                    f"segment='{record.segment}' - valuation is missing "
                    f"but the observed denominator outcome is "
                    f"{'missing' if denominator_missing else observed_count} "
                    f"(not a genuine zero)."
                )
            continue

        # aggregate_value is present.
        if denominator_missing:
            issues.append(
                f"Row {index}: cannot derive a rate for "
                f"market='{record.market}', week='{record.week}', "
                f"segment='{record.segment}' - the observed denominator "
                f"outcome is missing."
            )
            continue
        if denominator_is_zero:
            if record.aggregate_value != 0:
                issues.append(
                    f"Row {index}: cannot derive a rate for "
                    f"market='{record.market}', week='{record.week}', "
                    f"segment='{record.segment}' - denominator is "
                    f"genuinely zero but the supplied value "
                    f"({record.aggregate_value}) is non-zero."
                )
                continue
            rates.append(
                WeeklyValueRate(
                    valuation_kind=record.valuation_kind,
                    market=record.market,
                    week=record.week,
                    segment=record.segment,
                    value_per_unit=0.0,
                    currency=record.currency or "",
                    is_zero_denominator_carve_out=True,
                    source_record_fingerprint=record.fingerprint(),
                )
            )
            continue

        # Ordinary case: a genuine division.
        rates.append(
            WeeklyValueRate(
                valuation_kind=record.valuation_kind,
                market=record.market,
                week=record.week,
                segment=record.segment,
                value_per_unit=float(record.aggregate_value) / float(observed_count),
                currency=record.currency or "",
                is_zero_denominator_carve_out=False,
                source_record_fingerprint=record.fingerprint(),
            )
        )

    return rates, issues
