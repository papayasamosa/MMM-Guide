"""Leakage-safe, time-respecting historical validation folds
(REQ-LEAK-001, Work Package 1 of `Media-Mix-Lab: Coding LLM Next Steps
After PR #267 and Latest PRD Validation Updates`; point-in-time source
reconstruction added by Work Package 1 of `Media-Mix-Lab: Coding LLM Next
Steps After PR #286`, "part 2").

`core.diagnostics.expanding_window_backtest` performs a date-sliced
train/test split and calls a caller-supplied `fit_fold_fn`. That split
already correctly excludes rows dated after each fold's cutoff, but the
function has no way to know whether the *preprocessing state* behind
`df` (source vintages, publication lag, scaling fit on the wrong window,
mixed-frequency conversions, effective-dated business definitions) was
itself leakage-safe - it trusts the caller entirely. This module does not
change that function's contract or behaviour; it is a separate, additive
path for callers that need a provable answer to "could this fold have
been reconstructed using only information available at the time".

This module provides:

- `ValidationFold`: a typed, versioned fold manifest - never an ad hoc
  date slice recomputed differently by each caller.
- `assess_fold_source_reconstruction`: reuses the leakage/definition-break
  primitives `core.frequency_alignment` already defines for source-data
  preparation (`check_publication_leakage`, `check_definition_break_
  crossing`) to assess, per variable in a supplied `VariableCoverageMatrix`,
  whether that variable's training-window data could have been
  reconstructed as of the fold's information cutoff.
- `leakage_safe_expanding_window_backtest`: builds fold manifests, assesses
  each one, and refuses to call `fit_fold_fn` for a fold the assessment
  could not clear - leakage-safety is provable per fold, never assumed.

Point-in-time source-version reconstruction (Work Package 1 part 2):
`assess_fold_source_reconstruction` optionally accepts `source_versions` -
the project's registered `core.coverage.SourceVersion` upload-event
records. When supplied, each assessed `VariableCoverageRecord`'s pinned
`(source_id, source_version)` is cross-checked against those records: if
the specific `SourceVersion` that record's coverage/mapping content was
derived from was itself uploaded (`uploaded_at`) *after* the fold's
`effective_information_cutoff`, that data could not have existed for this
fold - reported as `cannot_verify`, never silently accepted. This
module retains no separate per-vintage byte content beyond a
`SourceVersion`'s own identity fields (checksum/filename/size), so an
earlier vintage's actual data (had one existed) can never be substituted
for the too-late pinned version - the only honest outcome is an explicit
limitation, exactly REQ-LEAK-001 requirement 4's "never substitute
today's later revision and call it historically valid". Omitting
`source_versions` (the default, `()`) preserves this function's exact
prior behaviour - existing callers are unaffected.

Deliberately out of scope for this module (see REQ-LEAK-001's own
"Unresolved decisions"):

- Rebuilding the full model-ready `frame`/scaling/mixed-frequency
  pipeline per fold from raw sources. This module assesses leakage risk
  from `VariableCoverageMatrix` metadata (effective periods, publication
  lag, definition breaks, coverage-segment states) and, when
  `source_versions` is supplied, upload-event timing - it does not itself
  refit a scaler. A variable this module cannot assess from that metadata
  alone is reported as a limitation, never silently assumed safe.
  `ancestry_mmm.application.fold_refit_service.
  run_leakage_safe_fold_refit_from_sources` reuses this assessment and
  additionally re-runs `core.official_preparation`/`core.
  frequency_alignment` fold-locally from raw native source tables (Work
  Package 1 part 2).
- Wiring this evidence into `DiagnosticsArtefact`/the Diagnostics page.
  This landed with the canonical Diagnostics evidence integration (schema
  v8, PR #291): `DiagnosticsService.run_historical_and_structural_
  validation_check` consumes one fold-refit run for both the historical
  and structural-stability sections. The Diagnostics page now routes to
  the stronger `run_leakage_safe_fold_refit_from_sources` path
  automatically when the project has its raw source tables and outcome
  definitions, and labels the weaker coverage-metadata-only tier
  explicitly otherwise - the two tiers are the `RECONSTRUCTION_TIER_*`
  vocabulary defined below, recorded in the `historical_validation`
  payload so the evidence tier is part of the artefact fingerprint.
- Any specific minimum source-vintage/publication-lag evidence threshold
  for calling a fold "leakage-safe enough" for production use - Part 7
  S48 `VL-023` remains an open decision; this module reports what it can
  verify and what it cannot, and leaves the production threshold policy
  to that separate decision record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from .coverage import (
    STATE_UNAVAILABLE_SOURCE,
    STATE_UNKNOWN,
    SourceVersion,
    VariableCoverageMatrix,
)
from .frequency_alignment import (
    check_definition_break_crossing,
    check_publication_leakage,
)

FOLD_MANIFEST_SCHEMA_VERSION = 1

LEAKAGE_STATUS_SAFE = "leakage_safe"
LEAKAGE_STATUS_RISK = "leakage_risk"
LEAKAGE_STATUS_NOT_YET_EFFECTIVE = "not_yet_effective"
LEAKAGE_STATUS_DEFINITION_BREAK = "definition_break_crossing"
LEAKAGE_STATUS_CANNOT_VERIFY = "cannot_verify"

LEAKAGE_STATUSES = (
    LEAKAGE_STATUS_SAFE,
    LEAKAGE_STATUS_RISK,
    LEAKAGE_STATUS_NOT_YET_EFFECTIVE,
    LEAKAGE_STATUS_DEFINITION_BREAK,
    LEAKAGE_STATUS_CANNOT_VERIFY,
)

# Coverage states that themselves record genuine ambiguity about a
# variable's history - a fold overlapping one of these cannot be proven
# leakage-safe for that variable from coverage metadata alone.
_AMBIGUOUS_COVERAGE_STATES = frozenset({STATE_UNAVAILABLE_SOURCE, STATE_UNKNOWN})

# Evidence-source tiers for a completed historical-validation run (Work
# Package 1 of `Media-Mix-Lab: Coding LLM Next Steps After PR #291`).
# These record *which* reconstruction the run's evidence was produced by -
# a distinct, closed vocabulary from the per-fold leakage statuses above,
# which stay per fold. A run must never be presented as having used the
# stronger tier than the one recorded here.
RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL = "source_version_aware_fold_local"
RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY = "coverage_metadata_only"

RECONSTRUCTION_TIERS = (
    RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL,
    RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
)


@dataclass(frozen=True)
class ValidationFold:
    """A single time-respecting historical validation fold as a typed,
    versioned object (REQ-LEAK-001 requirement 1) - never an ad hoc date
    slice computed inline by a caller.

    `information_cutoff` defaults to `train_end`: the purpose of a
    leakage-safe fold is to ask "what would a forecaster standing exactly
    at the end of this fold's training window have known" - not "what do
    we know today, with the benefit of every subsequent source revision".
    A caller with a genuine point-in-time vintage source may supply a
    different, later `information_cutoff` explicitly; this module never
    defaults to "today" or otherwise invents one.
    """

    fold_id: str
    fold_manifest_version: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    market_scope: Tuple[str, ...] = ()
    outcome_scope: Tuple[str, ...] = ()
    information_cutoff: Optional[str] = None
    schema_version: int = FOLD_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.fold_id:
            raise ValueError("fold_id is required")
        if self.fold_manifest_version < 1:
            raise ValueError("fold_manifest_version must be >= 1")
        if (
            self.schema_version < 1
            or self.schema_version > FOLD_MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError(
                f"Unsupported ValidationFold schema_version {self.schema_version} - "
                f"this build only understands up to {FOLD_MANIFEST_SCHEMA_VERSION}."
            )
        for label, start, end in (
            ("train", self.train_start, self.train_end),
            ("test", self.test_start, self.test_end),
        ):
            if pd.Timestamp(start) > pd.Timestamp(end):
                raise ValueError(f"{label}_start must not be after {label}_end")
        if pd.Timestamp(self.train_end) >= pd.Timestamp(self.test_start):
            raise ValueError(
                "train_end must be strictly before test_start - a fold's "
                "training and held-out windows must not overlap "
                f"(train_end={self.train_end!r}, test_start={self.test_start!r})."
            )
        if self.information_cutoff is not None:
            pd.Timestamp(self.information_cutoff)  # raises if malformed

    @property
    def effective_information_cutoff(self) -> str:
        return self.information_cutoff or self.train_end

    def to_dict(self) -> dict:
        return {
            "fold_id": self.fold_id,
            "fold_manifest_version": self.fold_manifest_version,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "market_scope": list(self.market_scope),
            "outcome_scope": list(self.outcome_scope),
            "information_cutoff": self.information_cutoff,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "ValidationFold":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in values.items() if k in known}
        payload["market_scope"] = tuple(payload.get("market_scope") or ())
        payload["outcome_scope"] = tuple(payload.get("outcome_scope") or ())
        return cls(**payload)


@dataclass(frozen=True)
class VariableReconstructionAssessment:
    """One variable's leakage-safety assessment for a specific fold
    (REQ-LEAK-001 requirement 2)."""

    variable_id: str
    market: str
    status: str
    reason: str

    def __post_init__(self) -> None:
        if not self.variable_id:
            raise ValueError("variable_id is required")
        if not self.market:
            raise ValueError("market is required")
        if self.status not in LEAKAGE_STATUSES:
            raise ValueError(
                f"invalid status {self.status!r}; must be one of {LEAKAGE_STATUSES}"
            )

    def to_dict(self) -> dict:
        return {
            "variable_id": self.variable_id,
            "market": self.market,
            "status": self.status,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "VariableReconstructionAssessment":
        return cls(
            variable_id=values["variable_id"],
            market=values["market"],
            status=values["status"],
            reason=values["reason"],
        )


@dataclass(frozen=True)
class FoldReconstructionAssessment:
    """Whether a fold's training window can be reconstructed using only
    information that would have been available at its information cutoff
    (REQ-LEAK-001 requirements 3-4) - the evidence a fold needs before it
    may be labelled leakage-safe, never assumed.
    """

    fold_id: str
    per_variable: Tuple[VariableReconstructionAssessment, ...]
    limitations: Tuple[str, ...] = ()

    @property
    def is_leakage_safe(self) -> bool:
        """A fold is leakage-safe only when every assessed variable
        resolves to `leakage_safe` and no limitation was recorded. A
        variable this assessment could not evaluate (`cannot_verify`)
        is never silently treated as safe - it both sets that variable's
        own status and is guaranteed to accompany a recorded limitation
        (see `assess_fold_source_reconstruction`)."""
        if self.limitations:
            return False
        return all(v.status == LEAKAGE_STATUS_SAFE for v in self.per_variable)

    def to_dict(self) -> dict:
        return {
            "fold_id": self.fold_id,
            "per_variable": [v.to_dict() for v in self.per_variable],
            "limitations": list(self.limitations),
            "is_leakage_safe": self.is_leakage_safe,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "FoldReconstructionAssessment":
        return cls(
            fold_id=values["fold_id"],
            per_variable=tuple(
                VariableReconstructionAssessment.from_dict(v)
                for v in values.get("per_variable") or ()
            ),
            limitations=tuple(values.get("limitations") or ()),
        )


def build_expanding_window_folds(
    df: pd.DataFrame,
    date_col: str,
    *,
    n_folds: int = 3,
    min_train_frac: float = 0.6,
    market_scope: Tuple[str, ...] = (),
    outcome_scope: Tuple[str, ...] = (),
) -> Tuple[ValidationFold, ...]:
    """Build typed, versioned expanding-window folds from `df`'s date
    column - the same boundary arithmetic `core.diagnostics.
    expanding_window_backtest` uses internally, extracted into first-class
    fold objects any caller can inspect, assess for leakage-safety
    (`assess_fold_source_reconstruction`), or reuse for structural-
    stability comparison (Work Package 2), rather than a private date
    slice recomputed differently by every caller.

    Random row-level splitting is never used here - REQ-LEAK-001
    requirement 5 requires a time-respecting design for a weekly
    time-series MMM, and expanding-window is this repository's first
    approved instance of one.
    """
    dates = pd.to_datetime(df[date_col])
    unique_dates = np.sort(dates.unique())
    n = len(unique_dates)
    start_idx = int(n * min_train_frac)
    if start_idx >= n:
        raise ValueError("min_train_frac leaves no data for a held-out block.")

    fold_edges = np.linspace(start_idx, n - 1, n_folds + 1, dtype=int)[1:]
    folds = []
    prev_edge = start_idx
    for fold_i, edge in enumerate(fold_edges):
        if edge <= prev_edge:
            continue
        if prev_edge + 1 > edge:
            continue
        cutoff_ts = pd.Timestamp(unique_dates[prev_edge])
        test_start_ts = pd.Timestamp(unique_dates[prev_edge + 1])
        test_end_ts = pd.Timestamp(unique_dates[edge])
        folds.append(
            ValidationFold(
                fold_id=f"fold_{fold_i + 1}",
                fold_manifest_version=1,
                train_start=pd.Timestamp(unique_dates[0]).strftime("%Y-%m-%d"),
                train_end=cutoff_ts.strftime("%Y-%m-%d"),
                test_start=test_start_ts.strftime("%Y-%m-%d"),
                test_end=test_end_ts.strftime("%Y-%m-%d"),
                market_scope=market_scope,
                outcome_scope=outcome_scope,
            )
        )
        prev_edge = edge
    return tuple(folds)


def _resolve_pinned_source_version(
    record_source_id: str,
    record_source_version: int,
    source_versions: Tuple[SourceVersion, ...],
) -> Optional[SourceVersion]:
    """The exact `SourceVersion` a `VariableCoverageRecord` pins itself to
    (its `(source_id, source_version)` pair), or `None` if no supplied
    `SourceVersion` identifies it. Never falls back to `current_source_
    versions` (the highest-numbered version) - a coverage record's pinned
    `source_version` may deliberately not be the current one, and this
    module must assess the version it actually reflects, not today's
    latest."""
    for version in source_versions:
        if (
            version.source_id == record_source_id
            and version.version == record_source_version
        ):
            return version
    return None


def assess_fold_source_reconstruction(
    fold: ValidationFold,
    coverage_matrix: VariableCoverageMatrix,
    source_versions: Iterable[SourceVersion] = (),
) -> FoldReconstructionAssessment:
    """Assess, per variable in `coverage_matrix`, whether that variable's
    training-window data for `fold` could have been reconstructed using
    only information available at `fold.effective_information_cutoff`
    (REQ-LEAK-001 requirements 2-4).

    Reuses the same primitives `core.frequency_alignment` already defines
    for source-data-preparation leakage checks (`check_publication_
    leakage`, `check_definition_break_crossing`) - this module does not
    invent a second leakage-detection mechanism.

    `source_versions` (Work Package 1 part 2, optional, default `()`):
    the project's registered `SourceVersion` upload events. When supplied,
    each record's pinned `(source_id, source_version)` is additionally
    cross-checked against them - see the module docstring's "Point-in-time
    source-version reconstruction" section. Omitting this parameter
    preserves this function's exact prior behaviour.
    """
    scoped_markets = set(fold.market_scope) or None
    assessments = []
    limitations = []
    resolved_source_versions = tuple(source_versions)

    for record in coverage_matrix.records:
        if (
            scoped_markets is not None
            and record.market not in scoped_markets
            and record.market != "*"
        ):
            continue

        if resolved_source_versions:
            pinned_version = _resolve_pinned_source_version(
                record.source_id, record.source_version, resolved_source_versions
            )
            if pinned_version is None:
                reason = (
                    f"{record.variable_id!r} ({record.market}) is pinned to "
                    f"{record.source_id!r} version {record.source_version}, "
                    "but no SourceVersion record identifies that upload "
                    "event - point-in-time availability cannot be verified."
                )
                assessments.append(
                    VariableReconstructionAssessment(
                        variable_id=record.variable_id,
                        market=record.market,
                        status=LEAKAGE_STATUS_CANNOT_VERIFY,
                        reason=reason,
                    )
                )
                limitations.append(reason)
                continue
            if pd.Timestamp(pinned_version.uploaded_at) > pd.Timestamp(
                fold.effective_information_cutoff
            ):
                reason = (
                    f"{record.variable_id!r} ({record.market}) reflects "
                    f"{record.source_id!r} version {record.source_version}, "
                    f"uploaded {pinned_version.uploaded_at} - after this "
                    f"fold's information cutoff "
                    f"{fold.effective_information_cutoff}. This module "
                    "retains no separate historical vintage content to "
                    "reconstruct what an earlier upload would have shown; "
                    "this fold cannot be proven leakage-safe for this "
                    "variable rather than substituting the later revision."
                )
                assessments.append(
                    VariableReconstructionAssessment(
                        variable_id=record.variable_id,
                        market=record.market,
                        status=LEAKAGE_STATUS_CANNOT_VERIFY,
                        reason=reason,
                    )
                )
                limitations.append(reason)
                continue

        ambiguous_segment = next(
            (
                segment
                for segment in record.coverage_segments
                if segment.state in _AMBIGUOUS_COVERAGE_STATES
                and pd.Timestamp(segment.period_start) <= pd.Timestamp(fold.train_end)
                and pd.Timestamp(segment.period_end) >= pd.Timestamp(fold.train_start)
            ),
            None,
        )
        if ambiguous_segment is not None:
            reason = (
                f"{record.variable_id!r} ({record.market}) has "
                f"{ambiguous_segment.state!r} coverage overlapping this "
                f"fold's training window [{fold.train_start}, "
                f"{fold.train_end}] at [{ambiguous_segment.period_start}, "
                f"{ambiguous_segment.period_end}] - this fold cannot be "
                "proven leakage-safe for this variable from coverage "
                "metadata alone."
            )
            assessments.append(
                VariableReconstructionAssessment(
                    variable_id=record.variable_id,
                    market=record.market,
                    status=LEAKAGE_STATUS_CANNOT_VERIFY,
                    reason=reason,
                )
            )
            limitations.append(reason)
            continue

        if record.effective_start and pd.Timestamp(
            record.effective_start
        ) > pd.Timestamp(fold.train_end):
            assessments.append(
                VariableReconstructionAssessment(
                    variable_id=record.variable_id,
                    market=record.market,
                    status=LEAKAGE_STATUS_NOT_YET_EFFECTIVE,
                    reason=(
                        f"{record.variable_id!r} becomes effective "
                        f"{record.effective_start}, after this fold's "
                        f"train_end {fold.train_end} - not available to "
                        "this fold."
                    ),
                )
            )
            continue

        blocking_break = check_definition_break_crossing(
            period_start=fold.train_start,
            period_end=fold.train_end,
            definition_breaks=record.definition_breaks,
        )
        if blocking_break is not None:
            assessments.append(
                VariableReconstructionAssessment(
                    variable_id=record.variable_id,
                    market=record.market,
                    status=LEAKAGE_STATUS_DEFINITION_BREAK,
                    reason=(
                        "An unapproved source-definition break on "
                        f"{blocking_break.break_date} falls inside this "
                        f"fold's training window [{fold.train_start}, "
                        f"{fold.train_end}]."
                    ),
                )
            )
            continue

        leaks = check_publication_leakage(
            reconstructed_period_end=fold.train_end,
            as_of=fold.effective_information_cutoff,
            native_frequency=record.frequency.native_frequency,
            publication_lag_periods=record.frequency.publication_lag_periods,
        )
        if leaks:
            assessments.append(
                VariableReconstructionAssessment(
                    variable_id=record.variable_id,
                    market=record.market,
                    status=LEAKAGE_STATUS_RISK,
                    reason=(
                        f"Reconstructing {record.variable_id!r} through "
                        f"{fold.train_end} as of "
                        f"{fold.effective_information_cutoff} would use "
                        "information not yet published, given "
                        f"{record.frequency.publication_lag_periods} "
                        "period(s) of publication lag at native frequency "
                        f"{record.frequency.native_frequency!r}."
                    ),
                )
            )
            continue

        assessments.append(
            VariableReconstructionAssessment(
                variable_id=record.variable_id,
                market=record.market,
                status=LEAKAGE_STATUS_SAFE,
                reason=(
                    "Effective as of this fold's training window, no "
                    "unapproved definition break crossing, and no "
                    "publication-lag leakage as of this fold's "
                    "information cutoff."
                ),
            )
        )

    return FoldReconstructionAssessment(
        fold_id=fold.fold_id,
        per_variable=tuple(assessments),
        limitations=tuple(limitations),
    )


def leakage_safe_expanding_window_backtest(
    df: pd.DataFrame,
    spec: Any,
    fit_fold_fn: Callable[
        [pd.DataFrame, pd.DataFrame], Tuple[Dict[str, float], Dict[str, float]]
    ],
    coverage_matrix: VariableCoverageMatrix,
    *,
    n_folds: int = 3,
    min_train_frac: float = 0.6,
    source_versions: Iterable[SourceVersion] = (),
) -> Tuple[
    pd.DataFrame, Tuple[ValidationFold, ...], Tuple[FoldReconstructionAssessment, ...]
]:
    """Leakage-safe counterpart to `core.diagnostics.
    expanding_window_backtest`: builds typed fold manifests, assesses each
    fold's leakage-safety against `coverage_matrix` *before* calling
    `fit_fold_fn`, and refuses to call `fit_fold_fn` for a fold the
    assessment did not clear (REQ-LEAK-001 requirement 3: leakage-safety
    is provable, not assumed).

    `expanding_window_backtest` itself is unchanged and remains a plain
    date-sliced backtest with no leakage-safety claim - this function is
    additive, never a silent upgrade of that helper's contract (per
    REQ-LEAK-001's own instruction not to present the existing helper as
    satisfying this stronger contract).

    `source_versions` (Work Package 1 part 2, optional): forwarded to
    `assess_fold_source_reconstruction` unchanged - see that function's
    docstring. Omitting it preserves this function's exact prior
    behaviour.

    Returns `(results_df, folds, assessments)` - the caller retains the
    full fold/assessment evidence, not only the flattened metric rows.
    """
    folds = build_expanding_window_folds(
        df,
        spec.date_col,
        n_folds=n_folds,
        min_train_frac=min_train_frac,
    )
    assessments = tuple(
        assess_fold_source_reconstruction(fold, coverage_matrix, source_versions)
        for fold in folds
    )

    dates = pd.to_datetime(df[spec.date_col])
    rows: list[Dict[str, Any]] = []
    for fold, assessment in zip(folds, assessments):
        test_df = df[
            (dates > pd.Timestamp(fold.train_end))
            & (dates <= pd.Timestamp(fold.test_end))
        ]
        if test_df.empty:
            continue

        if not assessment.is_leakage_safe:
            rows.append(
                {
                    "fold_id": fold.fold_id,
                    "train_end": fold.train_end,
                    "test_end": fold.test_end,
                    "outcome_id": None,
                    "r_squared": None,
                    "mape_pct": None,
                    "leakage_safe": False,
                    "skipped_reason": (
                        "fold failed leakage-safety assessment - see the "
                        "returned FoldReconstructionAssessment for this "
                        "fold_id"
                    ),
                }
            )
            continue

        train_df = df[dates <= pd.Timestamp(fold.train_end)]
        r2_by_seg, mape_by_seg = fit_fold_fn(train_df, test_df)
        for oid in r2_by_seg:
            rows.append(
                {
                    "fold_id": fold.fold_id,
                    "train_end": fold.train_end,
                    "test_end": fold.test_end,
                    "outcome_id": oid,
                    "r_squared": r2_by_seg[oid],
                    "mape_pct": mape_by_seg[oid],
                    "leakage_safe": True,
                    "skipped_reason": None,
                }
            )

    return pd.DataFrame(rows), folds, assessments
