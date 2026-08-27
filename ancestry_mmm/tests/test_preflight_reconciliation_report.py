"""Tests for `core.preflight_reconciliation_report` (Work Package 1,
2026-08-27): synthetic-only coverage for the combined source-to-model
reconciliation + per-fold data-support preflight assembly, so a candidate
can be checked before an expensive fold-refit backtest starts. No
Ancestry activity data is used - the current UK activity data is itself
under review as of 2026-08-26/27."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ancestry_mmm.core.preflight_reconciliation_report import (
    build_model_preflight_report,
    format_preflight_table,
)
from ancestry_mmm.core.validation_folds import (
    RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
)


def _weekly_dates(n: int) -> pd.Series:
    return pd.Series(pd.date_range("2023-01-01", periods=n, freq="W"))


def _healthy_frame(n: int = 100) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = _weekly_dates(n)
    df = pd.DataFrame(
        {
            "period_start": dates,
            "tv_brand": np.linspace(100, 200, n),
            "category_demand": np.linspace(1.0, 2.0, n),
            "gsa_new": np.linspace(10, 50, n),
        }
    )
    raw_sources = {
        "standard_activity": pd.DataFrame(
            {"period_start": dates, "tv_brand": np.linspace(100, 200, n)}
        ),
        "standard_context": pd.DataFrame(
            {"period_start": dates, "category_demand": np.linspace(1.0, 2.0, n)}
        ),
        "standard_outcomes": pd.DataFrame(
            {"period_start": dates, "gsa_new": np.linspace(10, 50, n)}
        ),
    }
    return df, raw_sources


class TestBuildModelPreflightReport:
    def test_reconstruction_tier_is_always_coverage_metadata_only(self):
        df, raw_sources = _healthy_frame()
        report = build_model_preflight_report(
            "family_history",
            df,
            "period_start",
            channels=["tv_brand"],
            control_cols=["category_demand"],
            outcome_columns=["gsa_new"],
            raw_sources=raw_sources,
        )
        assert report.reconstruction_tier == RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY

    def test_reconciliation_covers_every_consumed_variable_exactly_once(self):
        df, raw_sources = _healthy_frame()
        report = build_model_preflight_report(
            "family_history",
            df,
            "period_start",
            channels=["tv_brand"],
            control_cols=["category_demand"],
            outcome_columns=["gsa_new"],
            raw_sources=raw_sources,
        )
        variable_ids = [item.variable_id for item in report.reconciliation]
        assert variable_ids == ["gsa_new", "tv_brand", "category_demand"]
        assert all(
            item.raw.present and item.canonical.present
            for item in report.reconciliation
        )
        assert all(not item.disappeared_downstream for item in report.reconciliation)

    def test_disappeared_downstream_variable_is_flagged(self):
        df, raw_sources = _healthy_frame()
        # Simulate a broken source-to-model mapping: the canonical frame
        # never received "tv_brand" under that name.
        df = df.drop(columns=["tv_brand"])
        report = build_model_preflight_report(
            "family_history",
            df,
            "period_start",
            channels=["tv_brand"],
            control_cols=["category_demand"],
            outcome_columns=["gsa_new"],
            raw_sources=raw_sources,
        )
        tv_diag = next(
            item for item in report.reconciliation if item.variable_id == "tv_brand"
        )
        assert tv_diag.raw.present
        assert not tv_diag.canonical.present
        assert tv_diag.disappeared_downstream

    def test_fold_support_uses_the_same_expanding_window_slicing_as_a_real_backtest(
        self,
    ):
        df, raw_sources = _healthy_frame(n=100)
        report = build_model_preflight_report(
            "family_history",
            df,
            "period_start",
            channels=["tv_brand"],
            control_cols=["category_demand"],
            outcome_columns=["gsa_new"],
            raw_sources=raw_sources,
            n_folds=3,
        )
        assert len(report.fold_support) == 3
        # Expanding window: each successive fold's training window is a
        # superset (by row count) of the previous one.
        train_week_counts = [
            fold.variables[0].n_train_weeks for fold in report.fold_support
        ]
        assert train_week_counts == sorted(train_week_counts)
        assert train_week_counts[0] < train_week_counts[-1]

    def test_sparse_fold_1_channel_is_visible_before_any_fit_is_attempted(self):
        # Mirrors the WP2.11 item-5 incident: a channel launching very late
        # in the window should show near-zero active weeks in fold 1's
        # training slice, discoverable from this report alone.
        n = 100
        dates = _weekly_dates(n)
        values = [0.0] * 95 + [10.0, 20.0, 30.0, 40.0, 50.0]
        df = pd.DataFrame(
            {
                "period_start": dates,
                "late_channel": values,
                "gsa_new": np.linspace(10, 50, n),
            }
        )
        raw_sources = {
            "standard_activity": pd.DataFrame(
                {"period_start": dates, "late_channel": values}
            ),
            "standard_outcomes": pd.DataFrame(
                {"period_start": dates, "gsa_new": np.linspace(10, 50, n)}
            ),
        }
        report = build_model_preflight_report(
            "family_history",
            df,
            "period_start",
            channels=["late_channel"],
            control_cols=[],
            outcome_columns=["gsa_new"],
            raw_sources=raw_sources,
            n_folds=3,
        )
        fold_1 = report.fold_support[0]
        late_channel_diag = next(
            v for v in fold_1.variables if v.variable_id == "late_channel"
        )
        assert late_channel_diag.n_active_weeks == 0

    def test_no_thresholds_or_verdicts_are_invented(self):
        """Neither reconciliation nor fold-support carries a pass/fail
        judgement - this module assembles evidence only."""
        df, raw_sources = _healthy_frame()
        report = build_model_preflight_report(
            "family_history",
            df,
            "period_start",
            channels=["tv_brand"],
            control_cols=["category_demand"],
            outcome_columns=["gsa_new"],
            raw_sources=raw_sources,
        )
        for fold in report.fold_support:
            for variable in fold.variables:
                assert variable.readiness.value == "not_evaluated"


class TestFormatPreflightTable:
    def test_table_contains_model_name_variables_and_fold_ids(self):
        df, raw_sources = _healthy_frame()
        report = build_model_preflight_report(
            "dna_kit",
            df,
            "period_start",
            channels=["tv_brand"],
            control_cols=["category_demand"],
            outcome_columns=["gsa_new"],
            raw_sources=raw_sources,
            n_folds=2,
        )
        table = format_preflight_table(report)
        assert "dna_kit" in table
        assert "tv_brand" in table
        assert "category_demand" in table
        assert "gsa_new" in table
        for fold in report.fold_support:
            assert f"Fold {fold.fold_id}" in table

    def test_table_reports_undefined_pct_change_as_n_a_not_a_fabricated_zero(self):
        n = 5
        dates = _weekly_dates(n)
        df = pd.DataFrame(
            {"period_start": dates, "chan": [10.0] * n, "gsa_new": [1.0] * n}
        )
        raw_sources = {
            "standard_activity": pd.DataFrame(
                {"period_start": dates, "chan": [0.0] * n}
            ),
            "standard_outcomes": pd.DataFrame(
                {"period_start": dates, "gsa_new": [1.0] * n}
            ),
        }
        report = build_model_preflight_report(
            "family_history",
            df,
            "period_start",
            channels=["chan"],
            control_cols=[],
            outcome_columns=["gsa_new"],
            raw_sources=raw_sources,
            n_folds=1,
            min_train_frac=0.5,
        )
        table = format_preflight_table(report)
        assert "n/a" in table
