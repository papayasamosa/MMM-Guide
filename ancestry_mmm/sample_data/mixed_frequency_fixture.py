"""Small deterministic mixed-frequency fixture for WP1 tests and demos.

All values are synthetic.  The fixture intentionally contains weekly
outcomes/media, monthly and quarterly context, a released survey measure, and
point/duration events so conversion boundaries can be exercised without real
Ancestry data.
"""

from __future__ import annotations

import pandas as pd

from ancestry_mmm.core.coverage import FrequencyMetadata


def build_mixed_frequency_fixture() -> dict[str, object]:
    """Return synthetic source frames plus their explicit frequency metadata."""

    weekly = pd.date_range("2024-01-01", "2024-03-25", freq="7D")
    monthly = pd.date_range("2024-01-01", "2024-03-01", freq="MS")
    quarterly = pd.to_datetime(["2024-01-01"])
    markets = ["UK"]

    weekly_rows = [
        {
            "period_start": period,
            "market": market,
            "paid_search_spend": 1000.0 + index * 25.0,
            "fh_new_signups": 200.0 + index,
            "confidence_weekly": 50.0 + index / 10.0,
        }
        for index, period in enumerate(weekly)
        for market in markets
    ]
    monthly_rows = [
        {
            "period_start": period,
            "released_on": (period + pd.offsets.MonthEnd(0)),
            "market": "UK",
            "cpi_index": 100.0 + index,
            "brand_health": 70.0 + index,
        }
        for index, period in enumerate(monthly)
    ]
    quarterly_rows = [
        {
            "period_start": period,
            "market": "UK",
            "consumer_confidence_quarterly": 80.0,
        }
        for period in quarterly
    ]
    events = pd.DataFrame(
        [
            {
                "event_start": pd.Timestamp("2024-01-15"),
                "event_end": pd.Timestamp("2024-01-15"),
                "market": "UK",
                "promotion_event": 1.0,
            },
            {
                "event_start": pd.Timestamp("2024-02-26"),
                "event_end": pd.Timestamp("2024-03-10"),
                "market": "UK",
                "promotion_event": 1.0,
            },
        ]
    )
    survey = pd.DataFrame(
        [
            {
                "period_start": pd.Timestamp("2024-01-01"),
                "released_on": pd.Timestamp("2024-01-20"),
                "market": "UK",
                "brand_health_survey": 72.0,
            },
            {
                "period_start": pd.Timestamp("2024-02-01"),
                "released_on": pd.Timestamp("2024-02-20"),
                "market": "UK",
                "brand_health_survey": 73.0,
            },
        ]
    )
    return {
        "sources": {
            "weekly": pd.DataFrame(weekly_rows),
            "monthly": pd.DataFrame(monthly_rows),
            "quarterly": pd.DataFrame(quarterly_rows),
            "events": events,
            "survey": survey,
        },
        "frequency_metadata": {
            "cpi_index": FrequencyMetadata(
                native_frequency="monthly",
                target_frequency="weekly",
                variable_class="rate_index",
                method="release_aware_locf",
                method_version=1,
                publication_timing={"release_date_column": "released_on"},
                reconciliation_rule="last released observation carried forward",
            ),
            "brand_health": FrequencyMetadata(
                native_frequency="monthly",
                target_frequency="weekly",
                variable_class="survey_measurement",
                method="release_aware_locf",
                method_version=1,
                publication_timing={"release_date_column": "released_on"},
                reconciliation_rule="last released survey measurement carried forward",
            ),
            "consumer_confidence_quarterly": FrequencyMetadata(
                native_frequency="quarterly",
                target_frequency="weekly",
                variable_class="rate_index",
                method="release_aware_locf",
                method_version=1,
                reconciliation_rule="last released observation carried forward",
            ),
            "promotion_event": FrequencyMetadata(
                native_frequency="irregular",
                target_frequency="weekly",
                variable_class="event_flag",
                method="calendar_event_alignment",
                method_version=1,
                method_parameters={
                    "event_type": "duration",
                    "start_column": "event_start",
                    "end_column": "event_end",
                },
                reconciliation_rule="inclusive active-day overlap divided by seven",
            ),
        },
    }


__all__ = ["build_mixed_frequency_fixture"]
