"""Tests for `core.source_model_reconciliation` (2026-08-26 analyst
follow-up to WP2.11): raw-source-vs-canonical-frame reconciliation
diagnostics for one activity/variable at a time.

Covers the five scenarios the analyst asked synthetic testing to exercise:
healthy activity, sparse activity, a late-launching activity, missing vs.
true zero, and a deliberately broken source-to-model column mapping. All
synthetic - no Ancestry activity data is used, since the current UK
activity data is itself under review as of 2026-08-26."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.source_model_reconciliation import (
    reconcile_variable,
    reconcile_variables,
)


def _dates(n: int) -> pd.Series:
    return pd.Series(pd.date_range("2024-01-01", periods=n, freq="W"))


class TestHealthyActivity:
    def test_present_in_both_stages_with_matching_totals(self):
        n = 20
        df = pd.DataFrame({"date": _dates(n), "tv_brand": np.linspace(100, 200, n)})
        diag = reconcile_variable("tv_brand", df, df.copy(), "date")
        assert diag.raw.present and diag.canonical.present
        assert diag.raw.total_value == pytest.approx(diag.canonical.total_value)
        assert diag.pct_total_change == pytest.approx(0.0, abs=1e-9)
        assert not diag.disappeared_downstream
        assert diag.notes == ()


class TestSparseActivity:
    def test_reports_low_nonzero_count_without_a_verdict(self):
        n = 72
        values = [0.0] * 70 + [500.0, 800.0]
        raw = pd.DataFrame({"date": _dates(n), "uk_influencer": values})
        diag = reconcile_variable("uk_influencer", raw, raw.copy(), "date")
        assert diag.raw.n_nonzero_weeks == 2
        assert diag.canonical.n_nonzero_weeks == 2
        # No pass/fail judgement - this module never invents a threshold.
        assert not diag.disappeared_downstream


class TestLateLaunchingActivity:
    def test_first_active_date_reflects_the_launch_week_not_week_zero(self):
        n = 30
        values = [0.0] * 20 + list(np.linspace(50, 150, 10))
        raw = pd.DataFrame({"date": _dates(n), "new_channel": values})
        diag = reconcile_variable("new_channel", raw, raw.copy(), "date")
        dates = _dates(n)
        assert diag.raw.first_active_date == str(dates.iloc[20].date())
        assert diag.raw.n_nonzero_weeks == 10


class TestMissingVersusTrueZero:
    def test_nan_is_not_counted_as_a_nonzero_week_or_conflated_with_zero(self):
        n = 10
        raw_values = [np.nan, np.nan, 0.0, 0.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
        raw = pd.DataFrame({"date": _dates(n), "chan": raw_values})
        diag = reconcile_variable("chan", raw, raw.copy(), "date")
        assert diag.raw.n_missing == 2
        assert diag.raw.n_nonzero_weeks == 6
        assert diag.raw.n_rows == 10

    def test_a_variable_that_goes_from_real_values_to_all_missing_is_flagged(self):
        n = 10
        raw = pd.DataFrame({"date": _dates(n), "chan": [5.0] * n})
        canonical = pd.DataFrame({"date": _dates(n), "chan": [np.nan] * n})
        diag = reconcile_variable("chan", raw, canonical, "date")
        assert diag.disappeared_downstream
        assert any("no non-zero observations" in note for note in diag.notes)


class TestBrokenSourceToModelMapping:
    def test_column_entirely_absent_downstream_is_flagged_as_disappeared(self):
        n = 10
        raw = pd.DataFrame({"date": _dates(n), "uk_tv_sponsorship_linear": [10.0] * n})
        canonical = pd.DataFrame(
            {"date": _dates(n), "some_other_renamed_column": [10.0] * n}
        )
        diag = reconcile_variable("uk_tv_sponsorship_linear", raw, canonical, "date")
        assert diag.raw.present
        assert not diag.canonical.present
        assert diag.disappeared_downstream
        assert diag.pct_total_change is None  # undefined, never reported as 0%

    def test_a_variable_never_present_anywhere_is_not_falsely_flagged_as_disappeared(
        self,
    ):
        # Absent from BOTH stages (e.g. a column name typo'd the same way in
        # a synthetic test fixture) is a different situation from "present
        # raw, absent downstream" - this module must not conflate them.
        n = 5
        raw = pd.DataFrame({"date": _dates(n), "other_col": [1.0] * n})
        canonical = pd.DataFrame({"date": _dates(n), "other_col": [1.0] * n})
        diag = reconcile_variable("never_existed", raw, canonical, "date")
        assert not diag.raw.present
        assert not diag.canonical.present
        assert not diag.disappeared_downstream


class TestReconcileVariablesAcrossMultipleRawSources:
    def test_finds_a_variable_in_whichever_raw_source_actually_has_it(self):
        n = 5
        source_a = pd.DataFrame({"date": _dates(n), "tv": [1.0] * n})
        source_b = pd.DataFrame({"date": _dates(n), "radio": [2.0] * n})
        canonical = pd.DataFrame(
            {"date": _dates(n), "tv": [1.0] * n, "radio": [2.0] * n}
        )
        results = reconcile_variables(
            ["tv", "radio"],
            {"source_a": source_a, "source_b": source_b},
            canonical,
            "date",
        )
        by_id = {r.variable_id: r for r in results}
        assert by_id["tv"].raw.present
        assert by_id["radio"].raw.present

    def test_pct_total_change_is_none_when_raw_total_is_zero(self):
        n = 5
        raw = pd.DataFrame({"date": _dates(n), "chan": [0.0] * n})
        canonical = pd.DataFrame({"date": _dates(n), "chan": [10.0] * n})
        diag = reconcile_variable("chan", raw, canonical, "date")
        assert diag.pct_total_change is None
