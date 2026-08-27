"""Source-to-model reconciliation diagnostics (2026-08-26 analyst
follow-up to WP2.11): for one activity/variable, compare its raw per-source
series against its canonical/mapped (post-join, post-governed-window)
series and report first/last date, row count, non-zero rows, missing
rows, and total value at each stage - so an unexpected loss (an activity
that exists upstream but disappears, or whose total materially changes,
downstream) is visible directly, rather than only showing up later as an
unexplained sparse-support finding at fold-fit time
(`core.fold_data_support`).

`n_nonzero_rows`/`n_missing` count *rows of the supplied frame*, not
calendar weeks - deliberately, not by oversight (2026-08-27 WP1 contract
fix, renamed from the original `n_nonzero_weeks`/an implicit weeks
assumption). A raw source frame may carry a cadence other than one row
per week (daily, monthly, or another native frequency); this module makes
no assumption about a frame's cadence and performs no frequency
conversion - a caller wanting a week-denominated count must supply an
already-weekly-cadence frame (as this module's own canonical-stage input
always is) or convert before calling. Inventing a row-to-week conversion
here would be exactly the kind of transformation rule this module's own
docstring below says it must not invent.

This module is a diagnostic *report*, not a new join/mapping mechanism: it
never re-derives or re-joins anything `data.pipeline.
join_sources_with_diagnostics` / `core.official_preparation.
prepare_canonical_native_frame` already compute (row/key-level join loss is
that module's `JoinDiagnostics`, reused here rather than duplicated) - this
module adds the one thing those don't: a per-*variable* (not per-row-key)
comparison of value-level evidence (totals, non-zero weeks, active date
range) across the raw and canonical stages, for exactly the columns a
candidate's `ModelSpec` actually consumes.

It makes no judgement about whether a given change is acceptable - "how
much drop is too much" is a business/statistical decision (like
`core.fold_data_support.SupportThresholds`, no default is invented here),
and doing so now would risk baking in a rule from the exact UK activity
data currently under review for suspected upstream mapping issues. This
module reports the numbers and one deterministic structural fact (whether
the variable is present at all in each stage); it never emits a pass/fail
verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd


@dataclass(frozen=True)
class StageValueSummary:
    """One variable's evidence at one pipeline stage (raw source or
    canonical/mapped). `None` fields mean the variable/column was not
    present at this stage at all - distinct from a present-but-empty or
    present-but-all-zero column, which get real (zero-valued) summaries."""

    present: bool
    n_rows: Optional[int] = None
    n_nonzero_rows: Optional[int] = None
    n_missing: Optional[int] = None
    first_active_date: Optional[str] = None
    last_active_date: Optional[str] = None
    total_value: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "present": self.present,
            "n_rows": self.n_rows,
            "n_nonzero_rows": self.n_nonzero_rows,
            "n_missing": self.n_missing,
            "first_active_date": self.first_active_date,
            "last_active_date": self.last_active_date,
            "total_value": self.total_value,
        }


@dataclass(frozen=True)
class VariableReconciliationDiagnostic:
    """One activity/variable's evidence across the raw -> canonical
    boundary, plus deterministic structural flags. `pct_total_change` is
    `None` whenever either stage's total is `None`/zero (undefined, not
    zero) - never silently reported as 0% change."""

    variable_id: str
    raw: StageValueSummary
    canonical: StageValueSummary
    disappeared_downstream: bool
    pct_total_change: Optional[float]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variable_id": self.variable_id,
            "raw": self.raw.to_dict(),
            "canonical": self.canonical.to_dict(),
            "disappeared_downstream": self.disappeared_downstream,
            "pct_total_change": self.pct_total_change,
            "notes": list(self.notes),
        }


def _summarize_stage(
    df: Optional[pd.DataFrame], date_col: str, variable_id: str
) -> StageValueSummary:
    if df is None or variable_id not in df.columns:
        return StageValueSummary(present=False)

    values = pd.to_numeric(df[variable_id], errors="coerce")
    dates = (
        pd.to_datetime(df[date_col])
        if date_col in df.columns
        else pd.Series([], dtype="datetime64[ns]")
    )
    n_rows = len(values)
    missing_mask = values.isna()
    n_missing = int(missing_mask.sum())
    observed = values[~missing_mask]
    nonzero_mask = observed != 0
    n_nonzero = int(nonzero_mask.sum())

    active_dates = (
        dates[~missing_mask][nonzero_mask]
        if len(dates) == n_rows
        else pd.Series([], dtype="datetime64[ns]")
    )
    first_active = str(active_dates.min().date()) if not active_dates.empty else None
    last_active = str(active_dates.max().date()) if not active_dates.empty else None

    total_value = float(observed.sum()) if len(observed) > 0 else None

    return StageValueSummary(
        present=True,
        n_rows=n_rows,
        n_nonzero_rows=n_nonzero,
        n_missing=n_missing,
        first_active_date=first_active,
        last_active_date=last_active,
        total_value=total_value,
    )


def reconcile_variable(
    variable_id: str,
    raw_df: Optional[pd.DataFrame],
    canonical_df: Optional[pd.DataFrame],
    date_col: str,
) -> VariableReconciliationDiagnostic:
    """Compare one variable's evidence between its raw source frame and the
    canonical/mapped (post-join, post-governed-window) frame.

    `raw_df`/`canonical_df` may be `None` (stage not available to this
    caller) - reported as `present=False` for that stage, exactly like a
    variable genuinely absent from a supplied frame; a caller wanting to
    distinguish "not checked" from "checked and absent" must track that
    separately, this module only reports what a supplied frame does or
    does not contain.
    """
    raw_summary = _summarize_stage(raw_df, date_col, variable_id)
    canonical_summary = _summarize_stage(canonical_df, date_col, variable_id)

    disappeared_downstream = raw_summary.present and not canonical_summary.present
    if (
        raw_summary.present
        and canonical_summary.present
        and (raw_summary.n_nonzero_rows or 0) > 0
        and (canonical_summary.n_nonzero_rows or 0) == 0
    ):
        disappeared_downstream = True

    pct_total_change: Optional[float] = None
    if (
        raw_summary.total_value is not None
        and canonical_summary.total_value is not None
        and raw_summary.total_value != 0
    ):
        pct_total_change = (
            (canonical_summary.total_value - raw_summary.total_value)
            / abs(raw_summary.total_value)
            * 100.0
        )

    notes: List[str] = []
    if disappeared_downstream:
        notes.append(
            "variable has activity in the raw source but no non-zero "
            "observations in the canonical/mapped frame"
        )
    if (
        raw_summary.present
        and not canonical_summary.present
        and not disappeared_downstream
    ):
        notes.append(
            "variable column is entirely absent from the canonical/mapped frame"
        )

    return VariableReconciliationDiagnostic(
        variable_id=variable_id,
        raw=raw_summary,
        canonical=canonical_summary,
        disappeared_downstream=disappeared_downstream,
        pct_total_change=pct_total_change,
        notes=tuple(notes),
    )


def reconcile_variables(
    variable_ids: Sequence[str],
    raw_sources: Dict[str, pd.DataFrame],
    canonical_df: Optional[pd.DataFrame],
    date_col: str,
) -> List[VariableReconciliationDiagnostic]:
    """Reconcile several variables at once. `raw_sources` is keyed by
    source_id (matching `core.official_preparation.
    prepare_canonical_native_frame`'s own `sources` shape) - a variable is
    looked up across every raw source frame supplied, using the first
    source frame that actually contains that column (a variable belonging
    to more than one raw source at once is not expected in this pipeline's
    per-source-table model, and is reported using whichever source is
    checked first rather than silently merged)."""
    results: List[VariableReconciliationDiagnostic] = []
    for variable_id in variable_ids:
        raw_df = next(
            (frame for frame in raw_sources.values() if variable_id in frame.columns),
            None,
        )
        results.append(reconcile_variable(variable_id, raw_df, canonical_df, date_col))
    return results
