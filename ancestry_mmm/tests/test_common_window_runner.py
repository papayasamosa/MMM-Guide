"""Focused contracts for the common-window UK readiness runner."""

from pathlib import PureWindowsPath

import numpy as np
import pandas as pd

from scripts.run_uk_production_fit import (
    COMMON_WINDOW_END,
    DEFAULT_OUTPUT_DIR,
    HISTORICAL_TEST_USE_MODE,
    HISTORICAL_TEST_WINDOW_ROLE,
    _prepare_context_audit,
)


def test_common_window_default_matches_approved_initial_target_window():
    assert COMMON_WINDOW_END == "2025-04-06"


def test_context_audit_consumes_complete_weekly_category_demand_only():
    dates = pd.date_range("2023-01-01", "2023-01-15", freq="7D")
    context = pd.DataFrame(
        {
            "period_start": dates,
            "market": "UK",
            "fh_category_demand_google_trends": [40.0, 45.0, 42.0],
            "dna_category_demand_google_trends": [30.0, 31.0, 29.0],
            # A monthly value is deliberately present only as a native source
            # value; it has no release timing and must remain blocked.
            "uk_cpih_all_items_index": np.nan,
            "uk_unemployment_rate_pct": np.nan,
            "uk_new_mortgage_effective_interest_rate_pct": np.nan,
            "uk_deaths_registered_monthly": np.nan,
        }
    )
    metadata = [
        {
            "variable_id": "fh_category_demand_google_trends",
            "native_frequency": "weekly",
            "variable_class": "rate_index",
            "role": "diagnostic",
        },
        {
            "variable_id": "dna_category_demand_google_trends",
            "native_frequency": "weekly",
            "variable_class": "rate_index",
            "role": "diagnostic",
        },
        *[
            {
                "variable_id": variable_id,
                "native_frequency": "monthly",
                "variable_class": "rate_index",
                "role": "diagnostic",
            }
            for variable_id in (
                "uk_cpih_all_items_index",
                "uk_unemployment_rate_pct",
                "uk_new_mortgage_effective_interest_rate_pct",
            )
        ],
        {
            "variable_id": "uk_deaths_registered_monthly",
            "native_frequency": "monthly",
            "variable_class": "flow_count",
            "role": "diagnostic",
        },
    ]

    audit = _prepare_context_audit(
        context,
        metadata,
        governed_start="2023-01-01",
        governed_end="2023-01-15",
    )

    assert audit["consumed_controls"] == {
        "family_history": ["fh_category_demand_google_trends"],
        "dna_kit": ["dna_category_demand_google_trends"],
    }
    assert all(
        row["status"] == "ready"
        for row in audit["candidates"]
        if row["variable_id"].endswith("category_demand_google_trends")
    )
    assert all(
        row["status"] == "blocked"
        for row in audit["candidates"]
        if row["native_frequency"] == "monthly"
    )
    assert audit["no_values_filled"] is True


def test_context_audit_does_not_consume_blocked_weekly_candidate():
    dates = pd.date_range("2023-01-01", "2023-01-15", freq="7D")
    context = pd.DataFrame(
        {
            "period_start": dates,
            "market": "UK",
            "fh_category_demand_google_trends": [40.0, np.nan, 42.0],
            "dna_category_demand_google_trends": [30.0, 31.0, 29.0],
        }
    )
    metadata = [
        {
            "variable_id": "fh_category_demand_google_trends",
            "native_frequency": "weekly",
            "variable_class": "rate_index",
            "role": "diagnostic",
        },
        {
            "variable_id": "dna_category_demand_google_trends",
            "native_frequency": "weekly",
            "variable_class": "rate_index",
            "role": "diagnostic",
        },
    ]

    audit = _prepare_context_audit(
        context,
        metadata,
        governed_start="2023-01-01",
        governed_end="2023-01-15",
    )

    assert audit["consumed_controls"] == {
        "family_history": [],
        "dna_kit": ["dna_category_demand_google_trends"],
    }
    assert any(
        row["variable_id"] == "fh_category_demand_google_trends"
        and row["status"] == "blocked"
        for row in audit["candidates"]
    )


def test_common_window_runner_default_output_is_distinct_from_prior_window():
    assert PureWindowsPath(str(DEFAULT_OUTPUT_DIR)).name == (
        "production-fit-common-window-20260822"
    )
    assert "production-fit-20260820" not in str(DEFAULT_OUTPUT_DIR)


def test_historical_test_scope_is_explicitly_non_production():
    assert HISTORICAL_TEST_WINDOW_ROLE == "historical_test_common_window"
    assert HISTORICAL_TEST_USE_MODE == "historical_test_non_production"
