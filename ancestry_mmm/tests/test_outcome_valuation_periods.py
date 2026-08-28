"""Tests for reporting-period resolution (REQ-ECON-004 Requirements
1-4): calendar month/quarter/year labelling, custom date-range
resolution, and the no-scaling-of-partial-periods invariant.
"""

import pytest

from ancestry_mmm.core.outcome_valuation_periods import (
    PERIOD_GRAIN_MONTH,
    PERIOD_GRAIN_QUARTER,
    PERIOD_GRAIN_YEAR,
    calendar_month_label,
    calendar_quarter_label,
    calendar_year_label,
    distinct_calendar_periods,
    resolve_weeks_for_calendar_period,
    resolve_weeks_for_custom_range,
)
import pandas as pd


class TestCalendarLabels:
    @pytest.mark.parametrize(
        "date_str,expected",
        [
            ("2025-01-06", "2025-01"),
            ("2025-12-29", "2025-12"),
        ],
    )
    def test_month_label(self, date_str, expected):
        assert calendar_month_label(pd.Timestamp(date_str)) == expected

    @pytest.mark.parametrize(
        "date_str,expected",
        [
            ("2025-01-06", "2025-Q1"),
            ("2025-03-31", "2025-Q1"),
            ("2025-04-01", "2025-Q2"),
            ("2025-06-30", "2025-Q2"),
            ("2025-07-01", "2025-Q3"),
            ("2025-09-30", "2025-Q3"),
            ("2025-10-01", "2025-Q4"),
            ("2025-12-31", "2025-Q4"),
        ],
    )
    def test_quarter_label_matches_ancestry_standard_calendar_quarters(
        self, date_str, expected
    ):
        """Ancestry uses standard calendar quarters: Q1 Jan-Mar, Q2
        Apr-Jun, Q3 Jul-Sep, Q4 Oct-Dec - no fiscal-year offset."""
        assert calendar_quarter_label(pd.Timestamp(date_str)) == expected

    def test_year_label(self):
        assert calendar_year_label(pd.Timestamp("2025-06-15")) == "2025"


class TestResolveWeeksForCalendarPeriod:
    def test_filters_to_the_requested_month(self):
        weeks = ["2025-01-06", "2025-01-13", "2025-02-03"]
        resolved = resolve_weeks_for_calendar_period(
            weeks, PERIOD_GRAIN_MONTH, "2025-01"
        )
        assert resolved == ["2025-01-06", "2025-01-13"]

    def test_filters_to_the_requested_quarter(self):
        weeks = ["2025-01-06", "2025-03-31", "2025-04-07", "2025-06-30"]
        resolved = resolve_weeks_for_calendar_period(
            weeks, PERIOD_GRAIN_QUARTER, "2025-Q1"
        )
        assert resolved == ["2025-01-06", "2025-03-31"]

    def test_filters_to_the_requested_year(self):
        weeks = ["2024-12-30", "2025-01-06", "2025-12-29"]
        resolved = resolve_weeks_for_calendar_period(weeks, PERIOD_GRAIN_YEAR, "2025")
        assert resolved == ["2025-01-06", "2025-12-29"]

    def test_partial_period_returns_only_actual_available_weeks(self):
        """REQ-ECON-004 Requirement 3: a quarter only half elapsed
        returns only its actual weeks - never scaled or annualised, and
        never padded with weeks that don't exist."""
        weeks = ["2025-01-06", "2025-01-13"]  # only 2 of ~13 weeks in Q1
        resolved = resolve_weeks_for_calendar_period(
            weeks, PERIOD_GRAIN_QUARTER, "2025-Q1"
        )
        assert resolved == ["2025-01-06", "2025-01-13"]
        assert len(resolved) == 2  # not scaled up to represent a full quarter

    def test_no_matching_weeks_returns_empty(self):
        weeks = ["2025-01-06"]
        resolved = resolve_weeks_for_calendar_period(weeks, PERIOD_GRAIN_YEAR, "2030")
        assert resolved == []

    def test_result_is_chronologically_sorted_regardless_of_input_order(self):
        weeks = ["2025-01-13", "2025-01-06", "2025-01-20"]
        resolved = resolve_weeks_for_calendar_period(
            weeks, PERIOD_GRAIN_MONTH, "2025-01"
        )
        assert resolved == ["2025-01-06", "2025-01-13", "2025-01-20"]

    def test_unsupported_grain_rejected(self):
        with pytest.raises(ValueError, match="unsupported grain"):
            resolve_weeks_for_calendar_period(["2025-01-06"], "fortnight", "2025-01")

    def test_never_returns_a_week_absent_from_available_weeks(self):
        """No fabrication: only weeks explicitly supplied can ever be
        returned, regardless of what a full calendar month would
        contain."""
        weeks = ["2025-01-06"]
        resolved = resolve_weeks_for_calendar_period(
            weeks, PERIOD_GRAIN_MONTH, "2025-01"
        )
        assert set(resolved) <= set(weeks)


class TestResolveWeeksForCustomRange:
    def test_filters_inclusive_of_both_ends(self):
        weeks = ["2025-01-06", "2025-01-13", "2025-01-20", "2025-01-27"]
        resolved = resolve_weeks_for_custom_range(weeks, "2025-01-06", "2025-01-20")
        assert resolved == ["2025-01-06", "2025-01-13", "2025-01-20"]

    def test_inverted_range_rejected(self):
        with pytest.raises(ValueError, match="is after"):
            resolve_weeks_for_custom_range(["2025-01-06"], "2025-02-01", "2025-01-01")

    def test_range_with_no_matching_weeks_returns_empty(self):
        weeks = ["2025-01-06"]
        resolved = resolve_weeks_for_custom_range(weeks, "2030-01-01", "2030-12-31")
        assert resolved == []

    def test_partial_overlap_returns_only_available_weeks(self):
        """A user-selected range extending beyond the available calendar
        never fabricates weeks to fill it."""
        weeks = ["2025-01-06", "2025-01-13"]
        resolved = resolve_weeks_for_custom_range(weeks, "2024-01-01", "2026-01-01")
        assert resolved == weeks


class TestDistinctCalendarPeriods:
    def test_lists_distinct_periods_in_chronological_order(self):
        weeks = ["2025-02-03", "2025-01-06", "2025-01-13", "2025-03-03"]
        periods = distinct_calendar_periods(weeks, PERIOD_GRAIN_MONTH)
        assert periods == ["2025-01", "2025-02", "2025-03"]

    def test_quarter_grain(self):
        weeks = ["2025-01-06", "2025-04-07", "2025-07-07"]
        periods = distinct_calendar_periods(weeks, PERIOD_GRAIN_QUARTER)
        assert periods == ["2025-Q1", "2025-Q2", "2025-Q3"]

    def test_no_duplicate_periods(self):
        weeks = ["2025-01-06", "2025-01-13", "2025-01-20"]
        periods = distinct_calendar_periods(weeks, PERIOD_GRAIN_MONTH)
        assert periods == ["2025-01"]
