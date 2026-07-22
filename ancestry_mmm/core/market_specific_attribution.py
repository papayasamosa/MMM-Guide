"""
Market-aware Shapley attribution for the market-specific model ("Model C") -
the instruction document's section 5 ("Add Model C attribution").

Model A's Shapley decomposition (`core.attribution`) is built around a
single shared curve per channel (`params.beta[outcome_id][channel]`,
`params.hill_K[channel]`) and would misread Model C's market-indexed
parameters (`params.beta[market][outcome_id][channel]`,
`params.hill_K[market][channel]`) if applied directly - this module
redesigns the parameter handling for that shape rather than forcing Model
A's implementation onto it, per the brief's explicit instruction.

Everything *not* market-indexed (intercept, market_offset, trend_coef,
gamma_fourier, promo_coef, control_coef, outcome_control_coef) is identical
in shape between `FHPosteriorParams` and `FHMarketSpecificPosteriorParams`,
so `core.attribution._baseline_eta` is reused directly rather than
duplicated - only the channel-response term (which touches `beta`/`hill_K`)
needs Model C's own version.

Each observation row already belongs to exactly one market
(`frame["market_idx"]`/`frame["market_bounds"]` - the frame is built one
contiguous block per market, see data.preprocessor.prepare_fh_modeling_frame),
so a market-aware Shapley decomposition falls out of using each row's own
market's `beta`/`hill_K` in the per-channel log-term, with no separate
market loop needed in the decomposition itself - `segment_channel_market_summary`
below is what turns the resulting row-level contributions into a
`(market, channel, outcome_id)` table.

Same additivity guarantee as Model A: because the permutation-average
Shapley decomposition is a telescoping sum for every individual
permutation, `baseline + sum(channel contributions) == mu_total` exactly,
for every row - this holds regardless of whether `beta`/`hill_K` are shared
or market-indexed, and is tested directly (`tests/test_market_specific_attribution.py`).
The DNA halo is handled exactly like Model A: `meta.direct_dna_outcome_ids`
gets DNA-targeted media's full, undamped response; every other outcome_id
gets the shrunk halo response (docs/dna_fh_causal_structure.md) - unaffected
by which market a row belongs to, since halo_strength is not
market-specific in this model version (docs/decision_log.md).
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .attribution import _baseline_eta
from .hierarchical_model import FHModelMeta
from .market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    adstock_saturate_frame_market_specific,
)
from .predict import lag_frame


def _channel_log_terms_market_specific(
    frame: Dict, meta: FHModelMeta, params: FHMarketSpecificPosteriorParams,
) -> Dict[str, np.ndarray]:
    """Per-channel additive log-mu contribution, shape (n_obs, n_outcomes),
    before the final exp() - Model C equivalent of
    core.attribution._channel_log_terms, using each row's own market's
    `beta`/`hill_K` (via `market_idx`) rather than one shared value.

    Same direct/halo split as core.attribution._channel_log_terms: a DNA
    channel's term for an outcome_id sums its direct-pathway contribution
    (`direct_dna_outcome_ids` members, `dna_direct_media`) and halo-pathway
    contribution (`halo_eligible_outcome_ids` members, `dna_halo_media`) -
    two genuinely separate media inputs, not one shared lagged series
    (docs/dna_fh_causal_structure.md)."""
    outcome_ids = meta.outcome_ids
    markets = frame["markets"]
    market_idx = frame["market_idx"]
    n_obs = frame["X_media"].shape[0]
    n_out = len(outcome_ids)

    sat_media = adstock_saturate_frame_market_specific(
        frame["X_media"], frame["market_bounds"], markets, meta, params
    )
    dna_direct_media = sat_media[:, meta.dna_channel_idx] if meta.dna_channel_idx else None
    dna_halo_media = (
        lag_frame(dna_direct_media, frame["market_bounds"], meta.dna_lag_weeks)
        if meta.dna_channel_idx else None
    )

    # beta_by_row[obs, outcome, channel] - this row's own market's beta,
    # matching core.market_specific_predict.predict_mu_market_specific.
    beta_stack = np.array([
        [[params.beta[m][s][c] for c in meta.channels] for s in outcome_ids] for m in markets
    ])  # (n_market, n_outcome, n_channel)
    beta_by_row = beta_stack[market_idx]  # (n_obs, n_outcome, n_channel)

    terms: Dict[str, np.ndarray] = {}
    for ci, ch in enumerate(meta.channels):
        term = np.zeros((n_obs, n_out))
        is_dna = ci in meta.dna_channel_idx
        dna_pos = meta.dna_channel_idx.index(ci) if is_dna else None
        for si, oid in enumerate(outcome_ids):
            b = beta_by_row[:, si, ci]
            if is_dna:
                value = 0.0
                if oid in meta.direct_dna_outcome_ids:
                    value = value + b * dna_direct_media[:, dna_pos]
                if oid in meta.halo_eligible_outcome_ids:
                    halo = params.halo_strength.get(oid, 0.0)
                    if halo:
                        value = value + b * halo * dna_halo_media[:, dna_pos]
                term[:, si] = value
            else:
                term[:, si] = b * sat_media[:, ci]
        terms[ch] = term
    return terms


def compute_shapley_contributions_market_specific(
    frame: Dict,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    n_permutations: int = 200,
    seed: int = 42,
) -> Dict[str, object]:
    """
    Row-and-outcome_id-level Shapley decomposition of predicted mu into a
    baseline and per-channel contributions (outcome units), averaged over
    `n_permutations` random channel removal orders - Model C equivalent of
    `core.attribution.compute_shapley_contributions`. Contributions sum
    exactly to `(mu_total - mu_baseline)` for every row/outcome_id, whichever
    market that row belongs to.
    """
    rng = np.random.default_rng(seed)
    channels = meta.channels
    n_obs = frame["X_media"].shape[0]
    n_out = len(meta.outcome_ids)

    baseline_eta = _baseline_eta(frame, meta, params)
    mu_baseline = np.exp(np.clip(baseline_eta, -50, 50))
    channel_terms = _channel_log_terms_market_specific(frame, meta, params)

    contributions = {c: np.zeros((n_obs, n_out)) for c in channels}
    for _ in range(n_permutations):
        order = rng.permutation(channels)
        current = mu_baseline.copy()
        for c in order:
            new = current * np.exp(np.clip(channel_terms[c], -50, 50))
            contributions[c] += new - current
            current = new
    for c in channels:
        contributions[c] /= n_permutations

    mu_total = mu_baseline.copy()
    for c in channels:
        mu_total = mu_total + contributions[c]

    return {
        "baseline": mu_baseline,
        "channel_contributions": contributions,
        "mu_total": mu_total,
        "outcome_ids": meta.outcome_ids,
        "channels": channels,
        "markets": frame["markets"],
        "market_idx": frame["market_idx"],
    }


def segment_channel_market_summary(
    frame: Dict,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    contributions: Optional[Dict] = None,
    ltv: Optional[Dict[str, float]] = None,
    n_permutations: int = 200,
) -> pd.DataFrame:
    """
    Market x channel x outcome_id summary: total volume contribution, spend,
    ROAS/CPA, and (if `ltv` given) LTV-weighted value - the Model C
    equivalent of `core.attribution.segment_channel_summary`, with an added
    `market` column since Model C's parameters (and hence contributions)
    genuinely differ by market. `ltv` is keyed by outcome_id.
    """
    contributions = contributions or compute_shapley_contributions_market_specific(frame, meta, params, n_permutations)
    ltv = ltv or {}
    markets = frame["markets"]
    market_idx = frame["market_idx"]

    rows = []
    for ci, ch in enumerate(meta.channels):
        for m_i, market in enumerate(markets):
            row_mask = market_idx == m_i
            market_spend = float(frame["X_media"][row_mask, ci].sum())
            for si, oid in enumerate(meta.outcome_ids):
                vol = float(contributions["channel_contributions"][ch][row_mask, si].sum())
                value = vol * ltv.get(oid, 1.0)
                rows.append({
                    "market": market,
                    "channel": ch,
                    "outcome_id": oid,
                    "spend": market_spend,
                    "volume_contribution": vol,
                    "roas": vol / market_spend if market_spend > 0 else np.nan,
                    "cpa": market_spend / vol if vol > 0 else np.nan,
                    "ltv": ltv.get(oid),
                    "value_contribution": value,
                    "value_roas": value / market_spend if market_spend > 0 else np.nan,
                })
    return pd.DataFrame(rows)


def total_contribution_market_specific(
    frame: Dict,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    contributions: Optional[Dict] = None,
    ltv: Optional[Dict[str, float]] = None,
    n_permutations: int = 200,
    outcome_ids: Optional[List[str]] = None,
    by_market: bool = False,
) -> pd.DataFrame:
    """
    Total contribution by channel - the Model C equivalent of
    `core.attribution.total_fh_contribution`.

    `outcome_ids` restricts which outcome_ids are summed - pass the Family
    History outcome_id subset when the fit also includes DNA-product
    outcomes (`core.outcomes`), so a kit-sale count is never summed into a
    business-wide total alongside a GSA count (same convention as
    `total_fh_contribution`).

    `by_market=False` (default) aggregates across every market for a single
    total per channel ("total-business" view); `by_market=True` keeps
    `market` as a grouping key (one row per market x channel) for a
    market-by-market view. Spend is summed carefully in two stages to avoid
    double counting - it's constant across every outcome_id row for a given
    (market, channel), so it's taken once per (market, channel) before any
    cross-market summation.
    """
    summary = segment_channel_market_summary(frame, meta, params, contributions, ltv, n_permutations)
    if outcome_ids is not None:
        summary = summary[summary["outcome_id"].isin(outcome_ids)]

    market_channel = summary.groupby(["market", "channel"], sort=False).agg(
        spend=("spend", "first"),
        volume_contribution=("volume_contribution", "sum"),
        value_contribution=("value_contribution", "sum"),
    ).reset_index()

    if by_market:
        total = market_channel
    else:
        total = market_channel.groupby("channel", sort=False).agg(
            spend=("spend", "sum"),
            volume_contribution=("volume_contribution", "sum"),
            value_contribution=("value_contribution", "sum"),
        ).reset_index()

    total["roas"] = total["volume_contribution"] / total["spend"].replace(0, np.nan)
    total["value_roas"] = total["value_contribution"] / total["spend"].replace(0, np.nan)

    group_cols = ["market", "channel"] if by_market else ["channel"]
    pivot = summary.pivot_table(index=group_cols, columns="outcome_id", values="volume_contribution", aggfunc="sum")
    pivot = pivot.div(pivot.sum(axis=1), axis=0).add_suffix("_share").reset_index()
    return total.merge(pivot, on=group_cols, how="left")
