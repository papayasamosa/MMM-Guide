"""Unit tests for UX-020's date-boundary disclosure logic
(application/scenario_plan_period.py) - kept independent of the Scenario
Planner AppTest suite so the boundary conditions (fully in-sample, partially
beyond, fully beyond observed data) are proven directly against the pure
function rather than only through a Streamlit date-picker widget."""

import pandas as pd
import pytest

from ancestry_mmm.application.scenario_plan_period import (
    PLAN_PERIOD_STATUS_FULL_EXTRAPOLATION,
    PLAN_PERIOD_STATUS_IN_SAMPLE,
    PLAN_PERIOD_STATUS_PARTIAL_EXTRAPOLATION,
    derive_plan_period_disclosure,
)

OBSERVED_DATES = pd.date_range("2024-01-01", periods=16, freq="W").to_numpy()
# Last observed date is 2024-04-14 (16 weekly obs from 2024-01-01).


def _months(start: str, n: int):
    return pd.date_range(pd.Timestamp(start), periods=n, freq="MS")


def test_fully_in_sample_plan_gets_no_disclosure():
    disclosure = derive_plan_period_disclosure(
        OBSERVED_DATES,
        _months("2024-01-01", 3),  # Jan-Mar 2024, entirely before 2024-04-14
        plan_start_label="2024-01",
        plan_end_label="2024-03",
    )
    assert disclosure is not None
    assert disclosure.status == PLAN_PERIOD_STATUS_IN_SAMPLE
    assert disclosure.message is None


def test_plan_partially_beyond_observed_range_is_disclosed_as_partial():
    disclosure = derive_plan_period_disclosure(
        OBSERVED_DATES,
        _months("2024-03-01", 3),  # Mar, Apr, May 2024 - May is beyond Apr 14
        plan_start_label="2024-03",
        plan_end_label="2024-05",
    )
    assert disclosure is not None
    assert disclosure.status == PLAN_PERIOD_STATUS_PARTIAL_EXTRAPOLATION
    assert disclosure.message is not None
    assert "Part of this plan" in disclosure.message
    assert "April 2024" in disclosure.message
    # Must not overclaim invalidity or falsely claim future conditions known.
    assert "invalid" not in disclosure.message.lower()
    assert "unknown" not in disclosure.message.lower()
    # Must preserve/explain the existing flat-trend safeguard.
    assert "trend flat" in disclosure.message


def test_plan_wholly_beyond_observed_range_is_disclosed_as_full():
    disclosure = derive_plan_period_disclosure(
        OBSERVED_DATES,
        _months("2026-01-01", 12),  # ~2 years past observed data, like UX-020
        plan_start_label="2026-01",
        plan_end_label="2026-12",
    )
    assert disclosure is not None
    assert disclosure.status == PLAN_PERIOD_STATUS_FULL_EXTRAPOLATION
    assert disclosure.message is not None
    assert "This entire plan" in disclosure.message
    assert "invalid" not in disclosure.message.lower()


def test_plan_ending_exactly_on_the_observed_boundary_month_is_in_sample():
    """A plan whose last month exactly matches the observed end month should
    not be treated as beyond it (strict greater-than, not off-by-one)."""
    disclosure = derive_plan_period_disclosure(
        OBSERVED_DATES,
        _months("2024-04-01", 1),  # April 2024 - the observed end date's month
        plan_start_label="2024-04",
        plan_end_label="2024-04",
    )
    assert disclosure is not None
    assert disclosure.status == PLAN_PERIOD_STATUS_IN_SAMPLE
    assert disclosure.message is None


@pytest.mark.parametrize("empty_observed", [[], None])
def test_returns_none_when_there_is_no_observed_date_to_compare_against(empty_observed):
    if empty_observed is None:
        pytest.skip("None is not a valid Sequence; only the empty-list case applies")
    disclosure = derive_plan_period_disclosure(
        empty_observed,
        _months("2024-01-01", 3),
        plan_start_label="2024-01",
        plan_end_label="2024-03",
    )
    assert disclosure is None


def test_returns_none_when_there_are_no_plan_months():
    disclosure = derive_plan_period_disclosure(
        OBSERVED_DATES,
        [],
        plan_start_label="",
        plan_end_label="",
    )
    assert disclosure is None
