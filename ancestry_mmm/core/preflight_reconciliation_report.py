"""Combined source-to-model reconciliation and per-fold data-support
preflight report (Work Package 1, 2026-08-27, following up on WP2.11): one
assembly point for the two diagnostics WP2.11 added
(`core.source_model_reconciliation`, `core.fold_data_support`) so a
candidate can be checked before an expensive fold-refit backtest starts,
rather than only discovering sparse support or a broken source mapping
after a run has already been sitting for hours (the WP2.11 item-5
incident both of those modules cite).

Purely an assembly/formatting layer - it computes nothing itself beyond
what `core.source_model_reconciliation.reconcile_variables` and
`core.fold_data_support.fold_support_report` already report, and invents
no pass/fail threshold, no support cutoff, and no reconstruction-tier
upgrade. The fold slicing here (`train_df = df[dates <= fold.train_end]`)
is deliberately identical to `application.fold_refit_service.
run_leakage_safe_fold_refit`'s own slicing, so a preflight fold's reported
support genuinely describes the same training window a real fold-refit
run would fit - never a different, only-approximately-matching window.

Framework-independent (no Streamlit/PyMC import), matching every other
WP2.11 diagnostic module's convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

import pandas as pd

from ancestry_mmm.core.fold_data_support import FoldSupportReport, fold_support_report
from ancestry_mmm.core.source_model_reconciliation import (
    VariableReconciliationDiagnostic,
    reconcile_variables,
)
from ancestry_mmm.core.validation_folds import (
    RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
    build_expanding_window_folds,
)


@dataclass(frozen=True)
class ModelPreflightReport:
    """One model candidate's full preflight evidence: source-to-model
    reconciliation for every variable it consumes, plus per-fold data
    support for the same expanding-window folds a real fold-refit backtest
    would use. `reconstruction_tier` is always `RECONSTRUCTION_TIER_
    COVERAGE_METADATA_ONLY` - this report slices one already-prepared
    dataframe by date, exactly like the prepared-frame fold-refit backtest
    it precedes; it never claims the stronger point-in-time tier."""

    model_name: str
    reconstruction_tier: str
    variables: tuple[str, ...]
    reconciliation: tuple[VariableReconciliationDiagnostic, ...]
    fold_support: tuple[FoldSupportReport, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "reconstruction_tier": self.reconstruction_tier,
            "variables": list(self.variables),
            "reconciliation": [item.to_dict() for item in self.reconciliation],
            "fold_support": [item.to_dict() for item in self.fold_support],
        }


def build_model_preflight_report(
    model_name: str,
    df: pd.DataFrame,
    date_col: str,
    channels: Sequence[str],
    control_cols: Sequence[str],
    outcome_columns: Sequence[str],
    raw_sources: Mapping[str, pd.DataFrame],
    *,
    n_folds: int = 3,
    min_train_frac: float = 0.6,
) -> ModelPreflightReport:
    """Assemble one model's preflight report from already-prepared data -
    no PyMC model is built and no sampling occurs.

    `df` is the same model-ready frame a real fold-refit backtest would
    slice into folds (`frame["df"]` in `scripts/run_uk_wp2_11_prepared_
    frame_backtest.py`'s own terms) - the "canonical" stage for
    reconciliation and the source of every fold's training-window slice.
    `raw_sources` is the raw per-source-domain frame dict from before the
    governed join (`scripts.run_uk_production_fit.run`'s `sources`,
    exposed via its `sources_callback` parameter) - the "raw" stage for
    reconciliation. `channels`/`control_cols`/`outcome_columns` together
    define exactly the variables this candidate consumes, matching how
    `ModelSpec.channels`/`.control_cols` plus the governed outcome
    catalogue are already combined elsewhere in this pipeline (e.g. the
    `variables` list `scripts/run_uk_wp2_11_prepared_frame_backtest.py`
    builds for its own coverage-matrix call) - not re-derived differently
    here.
    """
    variables = list(outcome_columns) + list(channels) + list(control_cols)
    reconciliation = tuple(
        reconcile_variables(variables, dict(raw_sources), df, date_col)
    )

    folds = build_expanding_window_folds(
        df, date_col, n_folds=n_folds, min_train_frac=min_train_frac
    )
    dates = pd.to_datetime(df[date_col])
    fold_reports: List[FoldSupportReport] = []
    for fold in folds:
        train_df = df[dates <= pd.Timestamp(fold.train_end)]
        fold_reports.append(
            fold_support_report(
                train_df,
                date_col,
                channels,
                control_cols,
                outcome_columns,
                fold_id=fold.fold_id,
            )
        )

    return ModelPreflightReport(
        model_name=model_name,
        reconstruction_tier=RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
        variables=tuple(variables),
        reconciliation=reconciliation,
        fold_support=tuple(fold_reports),
    )


def format_preflight_table(report: ModelPreflightReport) -> str:
    """Render a `ModelPreflightReport` as a plain-text, monospace-friendly
    table - the human-readable counterpart to `ModelPreflightReport.
    to_dict()`'s JSON. Never the only output form; a caller wanting the
    full evidence (including every note) should use `to_dict()`."""
    lines: List[str] = []
    lines.append(
        f"=== {report.model_name} preflight "
        f"(reconstruction_tier={report.reconstruction_tier}) ==="
    )
    lines.append("")
    lines.append("-- Source-to-model reconciliation --")
    lines.append(
        f"{'variable':<40} {'raw_present':<12} {'canon_present':<14} "
        f"{'raw_nonzero':<12} {'canon_nonzero':<14} {'pct_total_chg':<14} "
        f"{'disappeared':<12}"
    )
    for item in report.reconciliation:
        pct = (
            f"{item.pct_total_change:.1f}%"
            if item.pct_total_change is not None
            else "n/a"
        )
        lines.append(
            f"{item.variable_id:<40} {str(item.raw.present):<12} "
            f"{str(item.canonical.present):<14} "
            f"{str(item.raw.n_nonzero_rows):<12} "
            f"{str(item.canonical.n_nonzero_rows):<14} {pct:<14} "
            f"{str(item.disappeared_downstream):<12}"
        )
    lines.append("")

    for fold in report.fold_support:
        lines.append(
            f"-- Fold {fold.fold_id} data support "
            f"(training {fold.train_start}..{fold.train_end}) --"
        )
        for variable in fold.variables:
            lines.append(f"  {variable.summary_line()}")
        lines.append("")

    return "\n".join(lines)
