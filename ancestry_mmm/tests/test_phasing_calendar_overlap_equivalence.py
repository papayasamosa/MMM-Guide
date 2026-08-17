"""Numerical-equivalence coverage between two separately-governed
day-overlap allocation implementations (Work Package 2, brief §5.12/§8.4):

- ``core.planning.phasing.phase_monthly_series_calendar_day_overlap_v1``
  (REQ-SCEN-002, forward-looking business planning), and
- ``core.frequency_conversion``'s ``calendar_overlap_allocation`` method
  (REQ-COVERAGE-001, backward-looking source-data conversion), reached here
  through its public entry point ``execute_frequency_conversion``.

The two modules are intentionally separately governed (different
requirement records, different method IDs, different call sites) and do
not share a code path - `core/planning/phasing.py`'s own module docstring
explains why. They do, however, share the same day-overlap arithmetic
principle (`(overlap_end - overlap_start).days + 1`, proportional
allocation, strict-tolerance reconciliation), and this suite exists to
catch the two silently drifting apart, not to merge their governance.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ancestry_mmm.core.frequency_alignment import (
    AlignmentSpecification,
    CanonicalCalendar,
)
from ancestry_mmm.core.frequency_conversion import execute_frequency_conversion
from ancestry_mmm.core.planning.phasing import (
    canonical_weeks,
    phase_monthly_series_calendar_day_overlap_v1,
)


def _calendar(start: str, end: str) -> CanonicalCalendar:
    return CanonicalCalendar(start=start, end=end, frequency="weekly")


def _spec(**overrides) -> AlignmentSpecification:
    values = dict(
        variable_id="value",
        source_id="source",
        source_version=1,
        market="UK",
        native_frequency="monthly",
        target_frequency="weekly",
        variable_class="flow_count",
        method_id="calendar_overlap_allocation",
        method_version=1,
    )
    values.update(overrides)
    return AlignmentSpecification(**values)


def _conversion_weekly_totals(monthly_values: dict, target_periods: tuple) -> dict:
    """Run the source-conversion engine over the same month->value pairs
    and target weeks, summing duplicate target weeks (a week can receive
    an allocation from more than one source month) into one dict keyed by
    the same ``%Y-%m-%d`` week-start labels `phasing.py` uses."""
    source = pd.DataFrame(
        {
            "period_start": pd.to_datetime([f"{month}-01" for month in monthly_values]),
            "value": list(monthly_values.values()),
        }
    )
    result = execute_frequency_conversion(
        source,
        _spec(),
        date_col="period_start",
        value_col="value",
        target_periods=list(target_periods),
    )
    totals: dict = {label: 0.0 for label in target_periods}
    for _, row in result.frame.iterrows():
        label = row["period_start"].strftime("%Y-%m-%d")
        totals[label] += float(row["value"])
    return totals


def _assert_equivalent(monthly_values: dict, calendar: CanonicalCalendar) -> None:
    weeks = canonical_weeks(calendar)
    phasing_result = phase_monthly_series_calendar_day_overlap_v1(
        market="UK",
        series_id="TV",
        monthly_values=monthly_values,
        calendar=calendar,
    )
    conversion_totals = _conversion_weekly_totals(monthly_values, weeks)
    phasing_totals = phasing_result.as_dict_by_week()
    for label in weeks:
        assert phasing_totals[label] == pytest.approx(
            conversion_totals[label], abs=1e-9
        ), (
            f"week {label!r} diverges between planning phasing "
            f"({phasing_totals[label]!r}) and source-conversion "
            f"({conversion_totals[label]!r})."
        )


class TestCalendarOverlapNumericalEquivalence:
    def test_leap_year_february(self):
        # 2028 is a leap year - February has 29 days. `phasing.canonical_weeks`
        # anchors weeks on `calendar.start` as given (`core.official_
        # preparation`/`core.frequency_alignment`'s own weekly convention is
        # Monday-anchored in production), while `frequency_conversion`'s
        # target-period handling always re-normalises every target period to
        # its Monday (`_week_start`) regardless of what is passed in - so a
        # non-Monday calendar start would compare two different week
        # anchorings, not exercise real equivalence. 2027-12-27 is a Monday.
        self._run({"2028-02": 2900.0}, _calendar("2027-12-27", "2028-03-31"))

    def test_thirty_day_month(self):
        # 2026-03-02 is a Monday (see note above).
        self._run({"2026-04": 3000.0}, _calendar("2026-03-02", "2026-05-31"))

    def test_thirty_one_day_month(self):
        self._run({"2026-01": 3100.0}, _calendar("2025-12-29", "2026-02-28"))

    def test_boundary_week_shared_between_two_months(self):
        # 2025-12-29..2026-02-28 covers a January that begins and ends
        # mid-week against 7-day canonical weeks starting 2025-12-29.
        self._run({"2026-01": 3100.0}, _calendar("2025-12-29", "2026-02-28"))

    def test_partial_narrow_calendar_covering_exactly_one_month(self):
        # The canonical calendar need not be a large multi-year window -
        # equivalence must hold even when it covers only the weeks one
        # month actually touches.
        self._run({"2026-06": 1800.0}, _calendar("2026-05-25", "2026-07-05"))

    def test_consecutive_tracked_months_share_a_boundary_week(self):
        self._run(
            {"2026-01": 3100.0, "2026-02": 2800.0},
            _calendar("2025-12-29", "2026-02-28"),
        )

    @staticmethod
    def _run(monthly_values: dict, calendar: CanonicalCalendar) -> None:
        _assert_equivalent(monthly_values, calendar)
