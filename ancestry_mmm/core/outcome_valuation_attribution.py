"""Posterior economic attribution: joining fixed weekly value-per-outcome
rates to posterior incremental outcome draws (REQ-ECON-003 Requirements
3-4).

The join happens at draw level, at the weekly grain, strictly before any
temporal aggregation - "week 1 incremental outcome x week 1 rate + week 2
incremental outcome x week 2 rate + ...", never "total incremental
outcome x average rate" (the business decision's own example, and
REQ-ECON-003 Requirement 3, verbatim). Supplied historical LTR/revenue
rates are fixed inputs with no uncertainty of their own (REQ-ECON-003
Requirement 4) - only the posterior draws of the incremental outcome
carry uncertainty, summarised via the existing governed
`core.uncertainty.summarize_distribution` credible-interval convention,
never a newly invented interval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple, cast

import numpy as np

from .outcome_valuation_rates import WeeklyValueRate
from .uncertainty import DEFAULT_CRED_MASS, summarize_distribution


def _validate_single_cohesive_series(weekly_rates: Sequence[WeeklyValueRate]) -> None:
    if not weekly_rates:
        raise ValueError("weekly_rates must not be empty.")
    first = weekly_rates[0]
    for rate in weekly_rates[1:]:
        if (
            rate.valuation_kind != first.valuation_kind
            or rate.market != first.market
            or rate.segment != first.segment
        ):
            raise ValueError(
                "weekly_rates must all share the same valuation_kind, "
                "market, and segment - a single cohesive weekly series, "
                "never a mix of cells joined together implicitly."
            )
        if rate.currency != first.currency:
            raise ValueError(
                "weekly_rates must not mix currencies within one series "
                "without an explicit, approved conversion - none exists "
                "here (FX policy for value/revenue remains blocked, "
                "REQ-ECON-002 Requirement 7)."
            )


def join_incremental_outcome_draws_to_value(
    incremental_outcome_draws: np.ndarray,
    weekly_rates: Sequence[WeeklyValueRate],
) -> np.ndarray:
    """REQ-ECON-003 Requirement 3: the draw-level, weekly-grain join.

    ``incremental_outcome_draws`` has shape ``(n_draws, n_weeks)`` - one
    posterior incremental-outcome-count draw per row, one week per
    column, in the same week order as ``weekly_rates``.

    Returns the joined incremental-*value* draws with the identical
    ``(n_draws, n_weeks)`` shape - deliberately NOT summed over weeks.
    Aggregating over weeks is the caller's job, and must happen only
    after this join (see `aggregate_incremental_value_draws`), never by
    multiplying a pre-summed total incremental outcome by an average
    rate.
    """
    _validate_single_cohesive_series(weekly_rates)
    draws = np.asarray(incremental_outcome_draws, dtype=float)
    if draws.ndim != 2:
        raise ValueError(
            "incremental_outcome_draws must be 2-D (n_draws, n_weeks), "
            f"got shape {draws.shape}."
        )
    if draws.shape[1] != len(weekly_rates):
        raise ValueError(
            f"incremental_outcome_draws has {draws.shape[1]} week columns "
            f"but {len(weekly_rates)} weekly_rates were supplied - these "
            "must correspond one-to-one, in the same week order."
        )
    rate_values = np.array([rate.value_per_unit for rate in weekly_rates], dtype=float)
    return cast(np.ndarray, draws * rate_values[np.newaxis, :])


def aggregate_incremental_value_draws(value_draws: np.ndarray) -> np.ndarray:
    """Sum already-joined weekly incremental-value draws into one
    per-draw total. Must only ever be called on the *output* of
    `join_incremental_outcome_draws_to_value` - never on raw outcome
    draws before the join (REQ-ECON-003 Requirement 3)."""
    return cast(np.ndarray, np.asarray(value_draws, dtype=float).sum(axis=1))


@dataclass(frozen=True)
class PosteriorEconomicAttribution:
    """Governed incremental-value/ROI artefact with posterior uncertainty
    (REQ-ECON-003 Requirements 3-4). ``value_per_unit`` inputs are fixed,
    non-drawn business data; only ``incremental_value``/``roi`` carry
    posterior uncertainty, summarised via the existing governed
    credible-interval convention.

    ``incremental_outcome_*`` (WP2E) is the same ``incremental_outcome_
    draws`` this artefact is built from, summed per draw and summarised
    *before* the value join - the raw attributed-outcome-unit posterior,
    always available whenever the caller could resolve weeks/draws at
    all, independent of whether a governed value rate exists for this
    cell (REQ-ECON-001's CPA-vs-ROI split: CPA-style raw-outcome
    reporting never requires a value operand, only ROI does)."""

    valuation_kind: str
    market: str
    segment: str
    currency: str
    weeks: Tuple[str, ...]
    incremental_value_mean: float
    incremental_value_median: float
    incremental_value_lower: float
    incremental_value_upper: float
    incremental_value_n_draws: int
    credible_mass: float
    spend: Optional[float] = None
    roi_mean: Optional[float] = None
    roi_median: Optional[float] = None
    roi_lower: Optional[float] = None
    roi_upper: Optional[float] = None
    source_rate_fingerprints: Tuple[str, ...] = ()
    incremental_outcome_mean: Optional[float] = None
    incremental_outcome_median: Optional[float] = None
    incremental_outcome_lower: Optional[float] = None
    incremental_outcome_upper: Optional[float] = None


def summarize_posterior_economic_attribution(
    incremental_outcome_draws: np.ndarray,
    weekly_rates: Sequence[WeeklyValueRate],
    *,
    spend: Optional[float] = None,
    credible_mass: float = DEFAULT_CRED_MASS,
) -> PosteriorEconomicAttribution:
    """Join, aggregate, and summarise - the full REQ-ECON-003
    Requirements 3-4 pipeline for one market/segment/valuation_kind
    series. ROI is computed only when ``spend`` is a positive number;
    per `REQ-ECON-001`, ROI never requires a value operand for CPA but
    always does for ROI, and a zero/negative/absent spend never produces
    a fabricated ROI figure."""
    _validate_single_cohesive_series(weekly_rates)
    total_outcome_draws = np.asarray(incremental_outcome_draws, dtype=float).sum(axis=1)
    outcome_summary = summarize_distribution(
        total_outcome_draws, cred_mass=credible_mass
    )
    value_draws = join_incremental_outcome_draws_to_value(
        incremental_outcome_draws, weekly_rates
    )
    total_value_draws = aggregate_incremental_value_draws(value_draws)
    value_summary = summarize_distribution(total_value_draws, cred_mass=credible_mass)

    roi_summary = None
    if spend is not None and spend > 0:
        roi_draws = total_value_draws / spend
        roi_summary = summarize_distribution(roi_draws, cred_mass=credible_mass)

    first = weekly_rates[0]
    return PosteriorEconomicAttribution(
        valuation_kind=first.valuation_kind,
        market=first.market,
        segment=first.segment,
        currency=first.currency,
        weeks=tuple(rate.week for rate in weekly_rates),
        incremental_value_mean=value_summary["mean"],
        incremental_value_median=value_summary["median"],
        incremental_value_lower=value_summary["lower"],
        incremental_value_upper=value_summary["upper"],
        incremental_value_n_draws=int(value_summary["n_draws"]),
        credible_mass=credible_mass,
        spend=spend,
        roi_mean=roi_summary["mean"] if roi_summary else None,
        roi_median=roi_summary["median"] if roi_summary else None,
        roi_lower=roi_summary["lower"] if roi_summary else None,
        roi_upper=roi_summary["upper"] if roi_summary else None,
        source_rate_fingerprints=tuple(
            rate.source_record_fingerprint for rate in weekly_rates
        ),
        incremental_outcome_mean=outcome_summary["mean"],
        incremental_outcome_median=outcome_summary["median"],
        incremental_outcome_lower=outcome_summary["lower"],
        incremental_outcome_upper=outcome_summary["upper"],
    )
