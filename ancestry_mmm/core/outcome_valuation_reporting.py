"""Historical Results economic reporting: per-posterior-draw, per-week
incremental-outcome extraction (WP2D-ui), bridging the fitted model's
Shapley decomposition (`core.attribution`) to the weekly economic-value
join (`core.outcome_valuation_attribution`).

REQ-ECON-003 Requirement 3 requires the value join to happen "week 1
incremental outcome x week 1 rate + week 2 incremental outcome x week 2
rate + ..." at the *posterior draw* level. Nothing upstream of this
module produces that `incremental_outcome_draws` array (shape
`(n_draws, n_weeks)`) from a fitted model's `trace`/`frame`/`meta` - this
module is that missing link, built from only already-governed pieces:
`core.uncertainty.sample_draw_indices`/`extract_posterior_params` for the
per-draw posterior sample, and `core.attribution.
compute_shapley_contributions` for the media-vs-baseline split. This is
the same per-draw Shapley pattern
`docs/wp2f_contribution_waterfall_design_note.md` Section 7 establishes
for the future contribution waterfall (WP2F), applied here to summarising
a single period's incremental outcome rather than bridging two periods.

Shapley is run over the model's FULL frame on every draw, never a
period-sliced frame, because adstock/carryover (`core.predict.
adstock_saturate_frame`, `lag_frame`) depends on `frame["market_bounds"]`
spanning that market's entire fitted history - only the *result* is
subset to the requested market/week/outcome_id rows afterwards
(`docs/wp2f_contribution_waterfall_design_note.md` Section 6, steps 2-3).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .attribution import compute_shapley_contributions
from .hierarchical_model import FHModelMeta
from .predict import FHPosteriorParams, extract_posterior_params
from .uncertainty import DEFAULT_N_DRAWS, sample_draw_indices

DEFAULT_REPORTING_N_PERMUTATIONS = 20


class OutcomeValuationReportingCoverageError(ValueError):
    """Raised when the requested market/week/outcome_id/channel selection
    cannot be resolved against the fitted model's frame - e.g. a
    requested week has no matching fitted row for that market. Fail
    closed: never silently drop, interpolate, or substitute a nearby
    week (REQ-ECON-004's "never fabricate a week" discipline)."""


def resolve_market_week_row_indices(
    frame: Dict, meta: FHModelMeta, market: str, weeks: Sequence[str]
) -> List[int]:
    """Public so callers needing the identical week->frame-row lookup for
    a different purpose (e.g. attributable spend, `frame["X_media"]`) use
    this one resolution path rather than re-implementing it - the same
    "no second calculation path" discipline applied to lookups, not just
    arithmetic."""
    if market not in meta.markets:
        raise OutcomeValuationReportingCoverageError(
            f"Market '{market}' is not one of this fit's markets {list(meta.markets)}."
        )
    market_idx = meta.markets.index(market)
    start, end = frame["market_bounds"][market_idx]
    market_dates = frame["dates"][start:end]
    date_to_row = {
        pd.Timestamp(d).normalize(): start + i for i, d in enumerate(market_dates)
    }
    row_indices: List[int] = []
    missing: List[str] = []
    for week in weeks:
        row = date_to_row.get(pd.Timestamp(week).normalize())
        if row is None:
            missing.append(str(week))
        else:
            row_indices.append(row)
    if missing:
        raise OutcomeValuationReportingCoverageError(
            f"Market '{market}' has no fitted weekly row for week(s) "
            f"{', '.join(missing)} - this period is not fully covered by "
            "the fitted model and cannot be reported without fabricating "
            "missing weeks."
        )
    return row_indices


def extract_incremental_outcome_draws(
    trace,
    frame: Dict,
    meta: FHModelMeta,
    *,
    market: str,
    weeks: Sequence[str],
    outcome_ids: Sequence[str],
    channel: Optional[str] = None,
    n_draws: int = DEFAULT_N_DRAWS,
    n_permutations: int = DEFAULT_REPORTING_N_PERMUTATIONS,
    seed: int = 42,
) -> np.ndarray:
    """Per-posterior-draw, per-week incremental outcome, shape
    `(n_draws, len(weeks))`, in the same week order as `weeks`.

    `outcome_ids` selects and sums the fitted outcome_id column(s) making
    up the requested reporting slice (e.g. every FH sign-up outcome_id
    for a "Total" FH view, or a single outcome_id for one product or
    segment) - never a raw-unit total across incompatible outcome units,
    mirroring `outcome_channel_summary`'s existing outcome_id-scoping
    discipline.

    `channel=None` returns the all-media incremental outcome
    (`mu_total - baseline`, i.e. every channel combined); a specific
    `channel` returns only that channel's Shapley-attributed share. Both
    are read off the identical `compute_shapley_contributions` call -
    one calculation path, never two, regardless of which reporting
    dimension the caller is showing.
    """
    if not outcome_ids:
        raise OutcomeValuationReportingCoverageError(
            "No outcome_ids supplied - cannot select a reporting slice."
        )
    unknown_outcomes = sorted(set(outcome_ids) - set(meta.outcome_ids))
    if unknown_outcomes:
        raise OutcomeValuationReportingCoverageError(
            f"outcome_id(s) {unknown_outcomes} are not part of this fit's "
            f"outcome_ids {list(meta.outcome_ids)}."
        )
    if channel is not None and channel not in meta.channels:
        raise OutcomeValuationReportingCoverageError(
            f"Channel '{channel}' is not one of this fit's channels "
            f"{list(meta.channels)}."
        )
    if not weeks:
        raise OutcomeValuationReportingCoverageError(
            "No weeks supplied - cannot resolve a reporting period."
        )

    row_indices = resolve_market_week_row_indices(frame, meta, market, weeks)
    outcome_col_indices = [meta.outcome_ids.index(oid) for oid in outcome_ids]
    row_index_array = np.array(row_indices)
    col_index_array = np.array(outcome_col_indices)

    draw_indices = sample_draw_indices(trace, n_draws, seed)
    result = np.zeros((len(draw_indices), len(weeks)))
    for draw_row, draw_index in enumerate(draw_indices):
        params: FHPosteriorParams = extract_posterior_params(trace, meta, at=draw_index)
        contributions = compute_shapley_contributions(
            frame, meta, params, n_permutations=n_permutations
        )
        if channel is None:
            per_row_per_outcome = contributions["mu_total"] - contributions["baseline"]
        else:
            per_row_per_outcome = contributions["channel_contributions"][channel]
        selected = per_row_per_outcome[np.ix_(row_index_array, col_index_array)]
        result[draw_row, :] = selected.sum(axis=1)
    return result


def available_weeks_for_market(
    frame: Dict, meta: FHModelMeta, market: str
) -> List[str]:
    """Every calendar week this fit actually has a row for, in this
    market, as `YYYY-MM-DD` strings in ascending order - the "already
    fitted, never fabricated" week universe `core.outcome_valuation_
    periods.resolve_weeks_for_calendar_period`/`resolve_weeks_for_custom_range`
    expect as their `available_weeks` argument."""
    if market not in meta.markets:
        raise OutcomeValuationReportingCoverageError(
            f"Market '{market}' is not one of this fit's markets {list(meta.markets)}."
        )
    market_idx = meta.markets.index(market)
    start, end = frame["market_bounds"][market_idx]
    return [pd.Timestamp(d).strftime("%Y-%m-%d") for d in frame["dates"][start:end]]


def observed_denominator_counts_frame(
    frame: Dict, meta: FHModelMeta, outcome_ids: Sequence[str]
) -> pd.DataFrame:
    """Long-form `(outcome_id, market, week, segment, count)` observed
    (never modelled) outcome counts for the requested `outcome_ids`,
    shaped exactly as `core.outcome_valuation_rates.
    derive_weekly_value_rates` expects its `observed_denominator_counts`
    argument. `segment` is each outcome_id's fitted-catalogue segment
    (`meta.outcome_id_to_segment`), defaulting to the outcome_id itself
    when the fit carries no segment mapping for it, so every row still
    joins to a stable, non-empty segment key.

    Counts are read from `frame["Y"]` - the model's own observed
    training target - never from a posterior prediction, matching
    REQ-ECON-003's "value rates are derived from what actually happened,
    not from what the model predicts happened" discipline."""
    unknown_outcomes = sorted(set(outcome_ids) - set(meta.outcome_ids))
    if unknown_outcomes:
        raise OutcomeValuationReportingCoverageError(
            f"outcome_id(s) {unknown_outcomes} are not part of this fit's "
            f"outcome_ids {list(meta.outcome_ids)}."
        )
    outcome_id_to_segment = getattr(meta, "outcome_id_to_segment", None) or {}
    rows = []
    dates = frame["dates"]
    market_idx = frame["market_idx"]
    for col, oid in enumerate(meta.outcome_ids):
        if oid not in outcome_ids:
            continue
        segment = outcome_id_to_segment.get(oid, oid)
        for row in range(frame["Y"].shape[0]):
            rows.append(
                {
                    "outcome_id": oid,
                    "market": meta.markets[market_idx[row]],
                    "week": pd.Timestamp(dates[row]).strftime("%Y-%m-%d"),
                    "segment": segment,
                    "count": float(frame["Y"][row, col]),
                }
            )
    return pd.DataFrame(
        rows, columns=["outcome_id", "market", "week", "segment", "count"]
    )


def attributable_spend(
    frame: Dict,
    meta: FHModelMeta,
    *,
    market: str,
    weeks: Sequence[str],
    channel: Optional[str] = None,
) -> float:
    """Total media spend for the requested market/weeks, matching
    `core.attribution.outcome_channel_summary`'s existing convention of
    treating `frame["X_media"]` directly as spend - the same input the
    fitted model itself consumes, never a second, independently-sourced
    cost figure. `channel=None` sums every channel (the "Total"
    reporting dimension's attributable spend); a specific `channel`
    sums only that channel's column."""
    if channel is not None and channel not in meta.channels:
        raise OutcomeValuationReportingCoverageError(
            f"Channel '{channel}' is not one of this fit's channels "
            f"{list(meta.channels)}."
        )
    row_indices = resolve_market_week_row_indices(frame, meta, market, weeks)
    channel_indices = (
        [meta.channels.index(channel)]
        if channel is not None
        else list(range(len(meta.channels)))
    )
    return float(frame["X_media"][np.ix_(row_indices, channel_indices)].sum())
