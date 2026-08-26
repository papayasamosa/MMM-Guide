"""Per-fold data-support diagnostics (2026-08-26 analyst follow-up to
WP2.11): before a Bayesian validation fold is fit, report how much genuine
data support each fitted variable (channel, control, outcome) has within
that *fold's own training window* - training weeks, active (non-zero)
weeks, active percentage, first/last active date, variance, and missing
(not-observed, per REQ-COVERAGE-001's "missing is not zero" vocabulary -
`core.coverage`) week count.

Motivated directly by the WP2.11 item-5 backtest incident (2026-08-26): a
quick probe of the current governed hierarchy's fold-1 training slice found
several channels with as few as 2 non-zero weeks out of 72 - a plausible
driver of the severe NUTS geometry (deep tree searches, many gradient
evaluations per draw) that made that fold's fit take hours instead of the
~15 minutes a full-data fit's own per-draw rate would predict. This module
exists so that finding is available *before* a fold is fit, not
reverse-engineered afterwards from how slow it turned out to be.

This module deliberately stops short of turning any of those numbers into
a pass/fail verdict. `SupportThresholds` is the analyst-owned configuration
that would do that, and it is entirely optional - passing none (the
default) leaves every variable's `readiness` as `NOT_EVALUATED`, never a
threshold this module invented on its own. A sparse-channel support cutoff
is a statistical/business decision, not an engineering default - and as of
2026-08-26 the current UK activity data feeding these numbers is itself
under review for suspected upstream source-to-model mapping issues, so no
cutoff may ever be derived FROM today's data by this module or its
callers.

Deliberately distinct from, and never merged into, `core.prefit_
identifiability.SupportThresholdPolicy` (`REQ-PREFIT-001`'s pre-fit gate):
that policy classifies one variable's support across the *whole prepared
frame*, ships versioned non-zero default thresholds (recorded in
`docs/specification_authority.md` as themselves still unapproved diagnostic
values that may only ever relax a run to `review_recommended`, never force
`blocked`/`ready`), and feeds the mandatory pre-fit submission gate. This
module classifies support within *one backtest fold's own truncated
training window* - a variable can pass the whole-frame pre-fit gate yet
still have inadequate support inside an early expanding-window fold's
shorter slice, exactly the case this module was built to catch. Reusing
the same `ready`/`review_recommended`/`blocked` vocabulary (`REQ-PREFIT-
001`'s own governed three-value naming) is intentional for a reader's
consistency; sharing a `SupportThresholds` *instance* across the two would
wrongly conflate a whole-submission decision with a single fold's
diagnostic, so `SupportThresholds` here defaults every field to `None`
rather than reusing `SupportThresholdPolicy`'s shipped defaults.

Framework-independent (no Streamlit/PyMC import - matches
`core.identification_diagnostics`/`core.market_data_capability`'s own
convention).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd


class SupportReadiness(str, Enum):
    """Categorical readiness label. `NOT_EVALUATED` is the only value this
    module ever assigns when no `SupportThresholds` is supplied.
    `READY`/`REVIEW_RECOMMENDED`/`BLOCKED` only ever come from a caller-
    supplied `SupportThresholds` - never a number this module invents."""

    NOT_EVALUATED = "not_evaluated"
    READY = "ready"
    REVIEW_RECOMMENDED = "review_recommended"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SupportThresholds:
    """Analyst-supplied cutoffs for categorising a variable's data support.

    Every field is optional; a field left `None` means "make no readiness
    judgement on this dimension" rather than an implicit always-pass. There
    is no built-in default instance - a caller wanting categorisation must
    construct one explicitly with numbers it can justify, and that
    justification belongs in `docs/decision_log.md` exactly like any other
    analyst decision this codebase requires - never invented ad hoc inside
    this module or derived from data currently under review.
    """

    min_active_pct_ready: Optional[float] = None
    min_active_pct_review: Optional[float] = None
    min_active_weeks_ready: Optional[int] = None
    min_active_weeks_review: Optional[int] = None


@dataclass(frozen=True)
class VariableSupportDiagnostic:
    """One fitted variable's data-support evidence within one fold's
    training window."""

    variable_id: str
    role: str  # "channel" | "control" | "outcome"
    n_train_weeks: int
    n_active_weeks: int
    active_pct: float
    n_missing_weeks: int
    first_active_date: Optional[str]
    last_active_date: Optional[str]
    variance: float
    min_value: Optional[float]
    max_value: Optional[float]
    readiness: SupportReadiness
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variable_id": self.variable_id,
            "role": self.role,
            "n_train_weeks": self.n_train_weeks,
            "n_active_weeks": self.n_active_weeks,
            "active_pct": self.active_pct,
            "n_missing_weeks": self.n_missing_weeks,
            "first_active_date": self.first_active_date,
            "last_active_date": self.last_active_date,
            "variance": self.variance,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "readiness": self.readiness.value,
            "notes": list(self.notes),
        }

    def summary_line(self) -> str:
        return (
            f"{self.variable_id} [{self.role}]: "
            f"{self.n_active_weeks}/{self.n_train_weeks} active weeks "
            f"({self.active_pct:.1f}%), missing={self.n_missing_weeks}, "
            f"first_active={self.first_active_date}, "
            f"var={self.variance:.4g}, readiness={self.readiness.value}"
        )


@dataclass(frozen=True)
class FoldSupportReport:
    """All variables' support diagnostics for one fold's training window."""

    fold_id: Optional[str]
    train_start: Optional[str]
    train_end: Optional[str]
    variables: tuple[VariableSupportDiagnostic, ...]

    def by_readiness(self) -> Dict[str, List[VariableSupportDiagnostic]]:
        out: Dict[str, List[VariableSupportDiagnostic]] = {}
        for v in self.variables:
            out.setdefault(v.readiness.value, []).append(v)
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "variables": [v.to_dict() for v in self.variables],
        }


def _categorize(
    active_pct: float,
    n_active_weeks: int,
    thresholds: Optional[SupportThresholds],
) -> SupportReadiness:
    if thresholds is None:
        return SupportReadiness.NOT_EVALUATED

    ready_ok = True
    review_ok = True
    if (
        thresholds.min_active_pct_ready is not None
        and active_pct < thresholds.min_active_pct_ready
    ):
        ready_ok = False
    if (
        thresholds.min_active_weeks_ready is not None
        and n_active_weeks < thresholds.min_active_weeks_ready
    ):
        ready_ok = False
    if (
        thresholds.min_active_pct_review is not None
        and active_pct < thresholds.min_active_pct_review
    ):
        review_ok = False
    if (
        thresholds.min_active_weeks_review is not None
        and n_active_weeks < thresholds.min_active_weeks_review
    ):
        review_ok = False

    if ready_ok:
        return SupportReadiness.READY
    if review_ok:
        return SupportReadiness.REVIEW_RECOMMENDED
    return SupportReadiness.BLOCKED


def variable_support_diagnostic(
    series: pd.Series,
    dates: pd.Series,
    variable_id: str,
    role: str,
    thresholds: Optional[SupportThresholds] = None,
) -> VariableSupportDiagnostic:
    """Compute one variable's data-support diagnostic within a training
    window. `series`/`dates` must be aligned (same index, same length) -
    one row per training-window observation (typically one row per week).

    "Missing" means a genuinely absent/NaN observation (REQ-COVERAGE-001's
    "missing is not zero" - `core.coverage`), never a zero value; "active"
    means a non-missing, non-zero observation. A row that is present but
    legitimately zero (e.g. a channel not yet launched, or a week with no
    spend) is neither missing nor active.
    """
    values = pd.to_numeric(series, errors="coerce")
    n_train_weeks = len(values)
    missing_mask = values.isna()
    n_missing_weeks = int(missing_mask.sum())
    observed = values[~missing_mask]
    active_mask = observed != 0
    n_active_weeks = int(active_mask.sum())
    active_pct = (
        (n_active_weeks / n_train_weeks * 100.0) if n_train_weeks > 0 else float("nan")
    )

    active_dates = pd.to_datetime(dates[~missing_mask][active_mask])
    first_active_date = (
        str(active_dates.min().date()) if not active_dates.empty else None
    )
    last_active_date = (
        str(active_dates.max().date()) if not active_dates.empty else None
    )

    variance = float(observed.var(ddof=0)) if len(observed) > 0 else float("nan")
    min_value = float(observed.min()) if len(observed) > 0 else None
    max_value = float(observed.max()) if len(observed) > 0 else None

    notes: List[str] = []
    if n_train_weeks > 0 and n_active_weeks == 0:
        notes.append("no active (non-zero, non-missing) weeks in this training window")
    elif n_train_weeks > 0 and n_active_weeks <= 2:
        notes.append(
            f"only {n_active_weeks} active week(s) in this training window - "
            "channel/control parameters are effectively unidentified from data"
        )

    readiness = _categorize(active_pct, n_active_weeks, thresholds)

    return VariableSupportDiagnostic(
        variable_id=variable_id,
        role=role,
        n_train_weeks=n_train_weeks,
        n_active_weeks=n_active_weeks,
        active_pct=active_pct,
        n_missing_weeks=n_missing_weeks,
        first_active_date=first_active_date,
        last_active_date=last_active_date,
        variance=variance,
        min_value=min_value,
        max_value=max_value,
        readiness=readiness,
        notes=tuple(notes),
    )


def fold_support_report(
    train_df: pd.DataFrame,
    date_col: str,
    channels: Sequence[str],
    control_cols: Sequence[str],
    outcome_cols: Sequence[str],
    *,
    fold_id: Optional[str] = None,
    thresholds: Optional[SupportThresholds] = None,
) -> FoldSupportReport:
    """Data-support diagnostics for every channel/control/outcome column
    present in `train_df`, for one fold's training-window slice.

    Columns named in `channels`/`control_cols`/`outcome_cols` but absent
    from `train_df` are skipped (not silently treated as zero-support) -
    a caller wanting to know about a genuinely missing column should
    consult `core.coverage.VariableCoverageMatrix`/`core.official_
    preparation`, which are the governed authority on column presence and
    already distinguish "never existed", "not sourced for this window", and
    "sourced but not observed".
    """
    dates = (
        train_df[date_col]
        if date_col in train_df.columns
        else pd.Series([], dtype="datetime64[ns]")
    )
    variables: List[VariableSupportDiagnostic] = []

    def _add(col: str, role: str) -> None:
        if col not in train_df.columns:
            return
        variables.append(
            variable_support_diagnostic(
                train_df[col], dates, variable_id=col, role=role, thresholds=thresholds
            )
        )

    for col in channels:
        _add(col, "channel")
    for col in control_cols:
        _add(col, "control")
    for col in outcome_cols:
        _add(col, "outcome")

    train_dates = pd.to_datetime(dates) if len(dates) > 0 else dates
    train_start = str(train_dates.min().date()) if len(train_dates) > 0 else None
    train_end = str(train_dates.max().date()) if len(train_dates) > 0 else None

    return FoldSupportReport(
        fold_id=fold_id,
        train_start=train_start,
        train_end=train_end,
        variables=tuple(variables),
    )
