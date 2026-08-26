"""Tests for `core.fold_data_support` (2026-08-26 analyst follow-up to
WP2.11): per-fold, per-variable data-support diagnostics - built after a
fold-1 probe found several channels with as few as 2 non-zero weeks out of
72 in the current UK activity data, a plausible driver of that fold's
severe NUTS geometry. Deliberately does not invent numeric readiness
thresholds - `SupportThresholds` is optional and every field within it is
also optional, matching the explicit instruction not to derive cutoffs
from data currently under review."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.fold_data_support import (
    SupportReadiness,
    SupportThresholds,
    fold_support_report,
    variable_support_diagnostic,
)


def _dates(n: int) -> pd.Series:
    return pd.Series(pd.date_range("2024-01-01", periods=n, freq="W"))


class TestVariableSupportDiagnosticMissingVsZero:
    def test_missing_is_not_counted_as_active_or_inactive_zero(self):
        # REQ-COVERAGE-001 vocabulary: NaN means "not observed", not zero.
        series = pd.Series([np.nan, np.nan, 5.0, 0.0, 3.0])
        diag = variable_support_diagnostic(series, _dates(5), "chan_a", "channel")
        assert diag.n_train_weeks == 5
        assert diag.n_missing_weeks == 2
        assert diag.n_active_weeks == 2  # the two nonzero, non-missing values
        assert diag.active_pct == pytest.approx(40.0)

    def test_all_zero_but_present_is_zero_active_weeks_not_missing(self):
        series = pd.Series([0.0, 0.0, 0.0, 0.0])
        diag = variable_support_diagnostic(series, _dates(4), "chan_b", "channel")
        assert diag.n_missing_weeks == 0
        assert diag.n_active_weeks == 0
        assert "no active" in diag.notes[0]

    def test_first_and_last_active_date_reflect_only_active_weeks(self):
        series = pd.Series([0.0, 5.0, 0.0, 7.0, 0.0])
        diag = variable_support_diagnostic(series, _dates(5), "chan_c", "channel")
        dates = _dates(5)
        assert diag.first_active_date == str(dates.iloc[1].date())
        assert diag.last_active_date == str(dates.iloc[3].date())

    def test_sparse_channel_gets_a_note(self):
        series = pd.Series([0.0] * 70 + [5.0, 8.0])
        diag = variable_support_diagnostic(
            series, _dates(72), "uk_influencer", "channel"
        )
        assert diag.n_active_weeks == 2
        assert any("effectively unidentified" in n for n in diag.notes)


class TestReadinessNotEvaluatedByDefault:
    def test_no_thresholds_means_not_evaluated_even_for_a_terrible_channel(self):
        series = pd.Series([0.0] * 70 + [5.0, 8.0])
        diag = variable_support_diagnostic(
            series, _dates(72), "uk_influencer", "channel"
        )
        assert diag.readiness == SupportReadiness.NOT_EVALUATED

    def test_this_module_never_invents_a_default_thresholds_instance(self):
        # SupportThresholds has no built-in non-None default - every field
        # must be constructed explicitly by a caller/analyst.
        thresholds = SupportThresholds()
        assert thresholds.min_active_pct_ready is None
        assert thresholds.min_active_pct_review is None
        assert thresholds.min_active_weeks_ready is None
        assert thresholds.min_active_weeks_review is None


class TestReadinessCategorizationWhenThresholdsSupplied:
    def test_ready_when_above_ready_bar(self):
        series = pd.Series([5.0] * 60 + [0.0] * 12)
        thresholds = SupportThresholds(
            min_active_pct_ready=50.0, min_active_pct_review=10.0
        )
        diag = variable_support_diagnostic(
            series, _dates(72), "chan", "channel", thresholds
        )
        assert diag.readiness == SupportReadiness.READY

    def test_review_recommended_between_bars(self):
        series = pd.Series([5.0] * 20 + [0.0] * 52)
        thresholds = SupportThresholds(
            min_active_pct_ready=50.0, min_active_pct_review=10.0
        )
        diag = variable_support_diagnostic(
            series, _dates(72), "chan", "channel", thresholds
        )
        assert diag.readiness == SupportReadiness.REVIEW_RECOMMENDED

    def test_blocked_below_review_bar(self):
        series = pd.Series([5.0] * 2 + [0.0] * 70)
        thresholds = SupportThresholds(
            min_active_pct_ready=50.0, min_active_pct_review=10.0
        )
        diag = variable_support_diagnostic(
            series, _dates(72), "chan", "channel", thresholds
        )
        assert diag.readiness == SupportReadiness.BLOCKED


class TestFoldSupportReport:
    def test_reports_every_role_and_skips_absent_columns(self):
        df = pd.DataFrame(
            {
                "date": _dates(10),
                "tv": [100.0] * 10,
                "control_x": [1.0] * 10,
                "outcome_y": [50.0] * 10,
            }
        )
        report = fold_support_report(
            df,
            "date",
            channels=["tv", "radio_not_present"],
            control_cols=["control_x"],
            outcome_cols=["outcome_y"],
            fold_id="fold_1",
        )
        ids_and_roles = {(v.variable_id, v.role) for v in report.variables}
        assert ("tv", "channel") in ids_and_roles
        assert ("control_x", "control") in ids_and_roles
        assert ("outcome_y", "outcome") in ids_and_roles
        assert not any(v.variable_id == "radio_not_present" for v in report.variables)
        assert report.fold_id == "fold_1"

    def test_by_readiness_groups_correctly(self):
        df = pd.DataFrame({"date": _dates(10), "tv": [100.0] * 10})
        report = fold_support_report(df, "date", ["tv"], [], [], fold_id="fold_1")
        grouped = report.by_readiness()
        assert "not_evaluated" in grouped
        assert len(grouped["not_evaluated"]) == 1

    def test_to_dict_round_trips_readiness_as_plain_string(self):
        df = pd.DataFrame({"date": _dates(5), "tv": [1.0] * 5})
        report = fold_support_report(df, "date", ["tv"], [], [])
        d = report.to_dict()
        assert d["variables"][0]["readiness"] == "not_evaluated"
