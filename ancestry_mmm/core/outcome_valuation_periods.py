"""Reporting-period resolution for historical economic reporting
(REQ-ECON-004 Requirements 1-4).

This module resolves *which already-existing canonical weeks* fall
within a requested reporting period (month, calendar quarter, year, or
an arbitrary custom date range) - it never invents, extrapolates, or
scales a week that is not already present in the caller-supplied set of
available weeks. Aggregating the resulting weeks' economics is
`core.outcome_valuation_attribution`'s job (REQ-ECON-003), applied to
whichever week subset this module resolves - this module performs no
aggregation itself.

Ancestry uses calendar years and standard calendar quarters (Q1 Jan-Mar,
Q2 Apr-Jun, Q3 Jul-Sep, Q4 Oct-Dec) - no fiscal-year offset. A partial
selected period (e.g. a quarter only half elapsed) simply resolves to
whichever of its weeks actually exist in the supplied calendar - it is
never annualised or scaled to a full period.
"""

from __future__ import annotations

from typing import List, Sequence

import pandas as pd

PERIOD_GRAIN_WEEK = "week"
PERIOD_GRAIN_MONTH = "month"
PERIOD_GRAIN_QUARTER = "quarter"
PERIOD_GRAIN_YEAR = "year"
PERIOD_GRAIN_CUSTOM = "custom"

PERIOD_GRAINS = (
    PERIOD_GRAIN_WEEK,
    PERIOD_GRAIN_MONTH,
    PERIOD_GRAIN_QUARTER,
    PERIOD_GRAIN_YEAR,
    PERIOD_GRAIN_CUSTOM,
)


def _parse_week(week: str) -> pd.Timestamp:
    try:
        return pd.Timestamp(week).normalize()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid week value: '{week}'.") from exc


def calendar_month_label(week_start: pd.Timestamp) -> str:
    return f"{week_start.year:04d}-{week_start.month:02d}"


def calendar_quarter_label(week_start: pd.Timestamp) -> str:
    quarter = (week_start.month - 1) // 3 + 1
    return f"{week_start.year:04d}-Q{quarter}"


def calendar_year_label(week_start: pd.Timestamp) -> str:
    return f"{week_start.year:04d}"


_LABEL_FUNCTIONS = {
    PERIOD_GRAIN_MONTH: calendar_month_label,
    PERIOD_GRAIN_QUARTER: calendar_quarter_label,
    PERIOD_GRAIN_YEAR: calendar_year_label,
}


def resolve_weeks_for_calendar_period(
    available_weeks: Sequence[str],
    grain: str,
    period_label: str,
) -> List[str]:
    """Resolve which of ``available_weeks`` fall within the named
    calendar month/quarter/year (REQ-ECON-004 Requirements 1-2).

    ``period_label`` must match the exact format `calendar_month_label`/
    `calendar_quarter_label`/`calendar_year_label` produce for this
    grain (e.g. ``"2025-06"``, ``"2025-Q1"``, ``"2025"``) - this is
    deliberate: it forces the caller to use the same calendar-quarter
    convention (Q1 Jan-Mar ... Q4 Oct-Dec) this module defines, rather
    than supplying an ambiguous or fiscal-year-offset label.

    Returns only weeks that are both in ``available_weeks`` and in the
    requested period - a partial period (e.g. a quarter only half
    elapsed) simply returns however many of its weeks are actually
    available, never scaled or annualised (REQ-ECON-004 Requirement 3).
    """
    if grain not in _LABEL_FUNCTIONS:
        raise ValueError(
            f"resolve_weeks_for_calendar_period: unsupported grain "
            f"'{grain}' (expected one of {tuple(_LABEL_FUNCTIONS)})."
        )
    label_fn = _LABEL_FUNCTIONS[grain]
    matched = []
    for week in available_weeks:
        week_start = _parse_week(week)
        if label_fn(week_start) == period_label:
            matched.append(week)
    return sorted(matched, key=_parse_week)


def resolve_weeks_for_custom_range(
    available_weeks: Sequence[str],
    start: str,
    end: str,
) -> List[str]:
    """Resolve which of ``available_weeks`` fall within an arbitrary,
    user-selected ``[start, end]`` date range, inclusive of both ends
    (REQ-ECON-004 Requirement 1's "total selected date range" grain).

    Only weeks already present in ``available_weeks`` are ever returned
    - this never fabricates a week, and a range that only partially
    overlaps the available calendar simply returns the actual weeks
    within it.
    """
    start_ts = _parse_week(start)
    end_ts = _parse_week(end)
    if start_ts > end_ts:
        raise ValueError(
            f"resolve_weeks_for_custom_range: start '{start}' is after end '{end}'."
        )
    matched = [
        week for week in available_weeks if start_ts <= _parse_week(week) <= end_ts
    ]
    return sorted(matched, key=_parse_week)


def distinct_calendar_periods(available_weeks: Sequence[str], grain: str) -> List[str]:
    """Every distinct calendar month/quarter/year label actually present
    among ``available_weeks``, in chronological order - the set of
    periods a reporting-period selector would offer for this grain,
    derived from the real calendar rather than a hard-coded range."""
    if grain not in _LABEL_FUNCTIONS:
        raise ValueError(
            f"distinct_calendar_periods: unsupported grain '{grain}' "
            f"(expected one of {tuple(_LABEL_FUNCTIONS)})."
        )
    label_fn = _LABEL_FUNCTIONS[grain]
    pairs = sorted(
        {(label_fn(_parse_week(week)), _parse_week(week)) for week in available_weeks},
        key=lambda pair: pair[1],
    )
    seen: List[str] = []
    for label, _ in pairs:
        if label not in seen:
            seen.append(label)
    return seen
