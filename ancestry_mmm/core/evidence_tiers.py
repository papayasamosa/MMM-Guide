"""
Market evidence tier classification (docs/market_hierarchy.md section 4) -
Phase 3a of the market-specific redesign.

Every market, once a market-specific model (Model C) has been fit, falls
into one of three evidence tiers describing how much its curve is driven by
its own local data versus the shared/pooled distribution:

- "Locally estimated": enough periods and low enough posterior uncertainty
  that the market's own data is doing most of the work.
- "Partially pooled": some local evidence, but not enough to stand alone -
  the market leans on the pooled distribution, with wider uncertainty.
- "Transferred estimate": not enough local data for a genuinely local
  curve; the estimate is effectively borrowed from the pooled distribution.

This is deliberately not the same thing as `core.market_config.
market_data_quality_status` (a coarse, pre-model, observation-count-only
heuristic used before any model exists) - this classifier additionally
reads the *fitted* model's own posterior uncertainty, which is the actual
signal partial pooling produces. See docs/market_hierarchy.md section 4 and
docs/decision_log.md for the reasoning.
"""

from __future__ import annotations

from typing import Dict, Optional

import arviz as az
import pandas as pd

from .hierarchical_model import FHModelMeta

LOCALLY_ESTIMATED = "Locally estimated"
PARTIALLY_POOLED = "Partially pooled"
TRANSFERRED_ESTIMATE = "Transferred estimate"

EVIDENCE_TIERS = [LOCALLY_ESTIMATED, PARTIALLY_POOLED, TRANSFERRED_ESTIMATE]

# Same observation-count thresholds as core.market_config.market_data_quality_status,
# so the pre-model heuristic and the post-fit classification agree on what
# "enough periods" means.
DEFAULT_MIN_OBSERVATIONS_FOR_LOCAL = 52
DEFAULT_MIN_OBSERVATIONS_FOR_POOLED = 12
# Relative posterior uncertainty (std/mean) above which a market's own
# estimate is too noisy to call "locally estimated" even with enough periods.
DEFAULT_MAX_RELATIVE_UNCERTAINTY_FOR_LOCAL = 0.5


def _relative_uncertainty(
    trace: az.InferenceData, var: str, market: str, channel: str, outcome_id: Optional[str] = None,
) -> float:
    selector = {"market": market, "channel": channel}
    if outcome_id is not None:
        selector["outcome"] = outcome_id
    draws = trace.posterior[var].sel(**selector)
    mean = float(draws.mean())
    std = float(draws.std())
    if mean == 0:
        return float("inf")
    return abs(std / mean)


def classify_market_evidence(
    trace: az.InferenceData,
    frame: Dict,
    meta: FHModelMeta,
    market: str,
    channel: str,
    *,
    min_observations_for_local: int = DEFAULT_MIN_OBSERVATIONS_FOR_LOCAL,
    min_observations_for_pooled: int = DEFAULT_MIN_OBSERVATIONS_FOR_POOLED,
    max_relative_uncertainty_for_local: float = DEFAULT_MAX_RELATIVE_UNCERTAINTY_FOR_LOCAL,
) -> str:
    """
    Classify one (market, channel) into an evidence tier for a fitted Model C.

    Combines two signals: how many periods of data that market has (from
    `frame["market_bounds"]`), and how uncertain the fitted `hill_K` and
    `beta` posteriors are for that market/channel relative to their own
    mean (from `trace`). Both must look strong for "Locally estimated";
    either being weak enough (too few periods) forces "Transferred
    estimate"; anything in between is "Partially pooled".
    """
    if market not in frame["markets"]:
        raise ValueError(f"'{market}' is not one of this frame's markets: {frame['markets']}")
    if channel not in meta.channels:
        raise ValueError(f"'{channel}' is not one of this model's channels: {meta.channels}")

    m_idx = frame["markets"].index(market)
    start, end = frame["market_bounds"][m_idx]
    n_observations = end - start

    if n_observations < min_observations_for_pooled:
        return TRANSFERRED_ESTIMATE

    beta_rel_uncertainties = [
        _relative_uncertainty(trace, "beta", market, channel, outcome_id=oid) for oid in meta.outcome_ids
    ]
    rel_uncertainty = max([_relative_uncertainty(trace, "hill_K", market, channel)] + beta_rel_uncertainties)

    if n_observations >= min_observations_for_local and rel_uncertainty <= max_relative_uncertainty_for_local:
        return LOCALLY_ESTIMATED
    return PARTIALLY_POOLED


def classify_all_markets(
    trace: az.InferenceData,
    frame: Dict,
    meta: FHModelMeta,
    **kwargs,
) -> Dict[str, Dict[str, str]]:
    """`{market: {channel: tier}}` for every market/channel in this fitted
    Model C - a convenience wrapper around `classify_market_evidence` for
    populating a full curve bank save or a summary table in one pass."""
    return {
        market: {
            channel: classify_market_evidence(trace, frame, meta, market, channel, **kwargs)
            for channel in meta.channels
        }
        for market in frame["markets"]
    }


def evidence_tiers_dataframe(trace: az.InferenceData, frame: Dict, meta: FHModelMeta, **kwargs) -> pd.DataFrame:
    """Flat `market, channel, curve_status` table - `classify_all_markets`'s
    output reshaped for direct display or Excel export (used by
    pages/09_Project_Export.py's Model C summary, docs/curve_bank.md)."""
    tiers = classify_all_markets(trace, frame, meta, **kwargs)
    return pd.DataFrame([
        {"market": market, "channel": channel, "curve_status": tier}
        for market, by_channel in tiers.items()
        for channel, tier in by_channel.items()
    ])
