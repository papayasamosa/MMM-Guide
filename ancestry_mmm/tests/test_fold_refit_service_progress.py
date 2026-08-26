"""Tests for `application.fold_refit_service`'s `on_progress_line`
instrumentation (2026-08-26 analyst follow-up to WP2.11): built after a
fold-refit backtest sat silent for 6+ hours, with no way to tell "still
working" from "stuck". `on_progress_line` is a purely additive optional
parameter defaulting to `None` - test_fold_refit_service.py's existing
tests (which never pass it) are the regression coverage proving byte-for-
byte unchanged default behaviour; not duplicated here.

Deliberately paced for normal blocking CI: exactly one real MCMC fit,
module-scoped so every test in this file reuses it - matching
test_fold_refit_service.py's own established "pay the real-fit cost once"
pattern."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.application.fold_refit_service import run_leakage_safe_fold_refit
from ancestry_mmm.application.model_fit_service import MODEL_TYPE_SHARED
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.schema import ModelSpec

FIT_KWARGS = dict(draws=5, tune=5, chains=1, cores=1, target_accept=0.8, random_seed=1)


def _raw_dataframe(n_weeks: int = 40) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n_weeks, freq="W")
    return pd.DataFrame(
        {
            "date": dates,
            "market": "UK",
            "TV_Brand": np.linspace(100.0, 900.0, n_weeks),
            "GSA_New": np.linspace(20.0, 120.0, n_weeks),
        }
    )


def _spec() -> ModelSpec:
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "GSA_New"},
        channels=["TV_Brand"],
    )


def _empty_coverage_matrix() -> VariableCoverageMatrix:
    return VariableCoverageMatrix(
        matrix_id="empty-matrix",
        matrix_version=1,
        generated_at="2026-08-18",
        records=(),
    )


@pytest.fixture(scope="module")
def progress_lines():
    """The one real (tiny) fit this file pays for, with `on_progress_line`
    supplied so every test can inspect the captured lines."""
    lines: list[str] = []
    run_leakage_safe_fold_refit(
        _raw_dataframe(),
        _spec(),
        _empty_coverage_matrix(),
        model_type=MODEL_TYPE_SHARED,
        n_folds=1,
        min_train_frac=0.7,
        posterior_draw_subsample=3,
        on_progress_line=lines.append,
        **FIT_KWARGS,
    )
    return lines


class TestOnProgressLineInstrumentation:
    def test_emits_a_data_support_line_before_sampling(self, progress_lines):
        assert any("data-support" in line for line in progress_lines)
        assert any("TV_Brand" in line and "channel" in line for line in progress_lines)

    def test_emits_a_fold_context_line_before_sampling(self, progress_lines):
        assert any("model build took" in line for line in progress_lines)

    def test_emits_live_sampling_geometry_lines(self, progress_lines):
        assert any(
            "step_size=" in line and "tree_depth=" in line for line in progress_lines
        )

    def test_context_and_support_lines_precede_any_sampling_line(self, progress_lines):
        first_sampling_idx = next(
            i for i, line in enumerate(progress_lines) if "step_size=" in line
        )
        assert any(
            "data-support" in line for line in progress_lines[:first_sampling_idx]
        )
        assert any(
            "model build took" in line for line in progress_lines[:first_sampling_idx]
        )
