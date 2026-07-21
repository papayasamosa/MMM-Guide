"""
Segment-level and total-FH attribution for the joint hierarchical model.

Because the model is multiplicative in mu = exp(baseline + sum_c channel_term_c
+ ...), a channel's "contribution" isn't a well-defined single number without
a decomposition rule - removing channels one at a time and summing the
differences depends on removal order. We use a Shapley decomposition
(averaged over random removal orders) so contributions are fair and sum
exactly to (total predicted outcome - baseline), rather than an arbitrary
last-channel-in/first-channel-out convention.

Generic (non-FH-specific) helpers - compute_shapley_values, decompose_sales -
are kept from the original single-KPI implementation for reuse.
"""

from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .hierarchical_model import FHModelMeta
from .predict import FHPosteriorParams, adstock_saturate_frame, lag_frame


# ---------------------------------------------------------------------------
# Joint hierarchical FH model attribution
# ---------------------------------------------------------------------------

def _baseline_eta(frame: Dict, meta: FHModelMeta, params: FHPosteriorParams) -> np.ndarray:
    """Everything in eta except the media-channel terms: intercept, market, trend, season, promo, controls."""
    segments = meta.segments

    intercept = np.array([params.intercept[s] for s in segments])
    market_offset_matrix = np.array([[params.market_offset[m][s] for s in segments] for m in meta.markets])
    eta_market = market_offset_matrix[frame["market_idx"]]

    trend_coef = np.array([params.trend_coef[s] for s in segments])
    eta_trend = frame["trend"][:, None] * trend_coef[None, :]

    gamma_fourier_matrix = np.column_stack([params.gamma_fourier[s] for s in segments])
    eta_season = frame["fourier"] @ gamma_fourier_matrix

    promo_coef = np.array([params.promo_coef[s] for s in segments])
    eta_promo = frame["promo"] * promo_coef[None, :]

    eta = intercept[None, :] + eta_market + eta_trend + eta_season + eta_promo

    segment_controls = frame.get("segment_controls") or {}
    segment_control_names = frame.get("segment_control_names") or {}
    for seg, arr in segment_controls.items():
        if seg not in segments or seg not in params.segment_control_coef:
            continue
        s_idx = segments.index(seg)
        names = segment_control_names.get(seg, [])
        coefs = np.array([params.segment_control_coef[seg].get(n, 0.0) for n in names])
        eta[:, s_idx] += arr @ coefs

    control_names = frame.get("control_names") or []
    if control_names and params.control_coef:
        coefs = np.array([params.control_coef.get(n, 0.0) for n in control_names])
        eta += (frame["X_controls"] @ coefs)[:, None]

    return eta


def _channel_log_terms(frame: Dict, meta: FHModelMeta, params: FHPosteriorParams) -> Dict[str, np.ndarray]:
    """Per-channel additive log-mu contribution, shape (n_obs, n_segments), before the final exp().

    For a DNA channel, a segment's term is the sum of its direct-pathway
    contribution (`beta * dna_direct_media`, for `direct_dna_segments`
    members) and its halo-pathway contribution (`beta * halo_strength *
    dna_halo_media`, for `halo_eligible_segments` members) - the same two
    genuinely separate media inputs core.hierarchical_model's likelihood
    uses, not one shared lagged series (docs/dna_fh_causal_structure.md).
    Both pathways are summed into the channel's single term here (Shapley
    permutes whole channels, not pathways within a channel), so
    `dna_segment` correctly gets credit for both without either being
    double-counted."""
    segments = meta.segments
    n_obs = frame["X_media"].shape[0]
    n_seg = len(segments)

    sat_media = adstock_saturate_frame(frame["X_media"], frame["market_bounds"], meta, params)
    dna_direct_media = sat_media[:, meta.dna_channel_idx] if meta.dna_channel_idx else None
    dna_halo_media = (
        lag_frame(dna_direct_media, frame["market_bounds"], meta.dna_lag_weeks)
        if meta.dna_channel_idx else None
    )

    terms: Dict[str, np.ndarray] = {}
    for ci, ch in enumerate(meta.channels):
        term = np.zeros((n_obs, n_seg))
        is_dna = ci in meta.dna_channel_idx
        dna_pos = meta.dna_channel_idx.index(ci) if is_dna else None
        for si, seg in enumerate(segments):
            b = params.beta[seg][ch]
            if is_dna:
                value = 0.0
                if seg in meta.direct_dna_segments:
                    value = value + b * dna_direct_media[:, dna_pos]
                if seg in meta.halo_eligible_segments:
                    halo = params.halo_strength.get(seg, 0.0)
                    if halo:
                        value = value + b * halo * dna_halo_media[:, dna_pos]
                term[:, si] = value
            else:
                term[:, si] = b * sat_media[:, ci]
        terms[ch] = term
    return terms


def compute_shapley_contributions(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    n_permutations: int = 200,
    seed: int = 42,
) -> Dict[str, np.ndarray]:
    """
    Row-and-segment-level Shapley decomposition of predicted mu into a
    baseline and per-channel contributions (GSA units), averaged over
    `n_permutations` random channel removal orders. Contributions sum
    exactly to (mu_total - mu_baseline) for every row/segment.
    """
    rng = np.random.default_rng(seed)
    channels = meta.channels
    n_obs = frame["X_media"].shape[0]
    n_seg = len(meta.segments)

    baseline_eta = _baseline_eta(frame, meta, params)
    mu_baseline = np.exp(np.clip(baseline_eta, -50, 50))
    channel_terms = _channel_log_terms(frame, meta, params)

    contributions = {c: np.zeros((n_obs, n_seg)) for c in channels}
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
        "segments": meta.segments,
        "channels": channels,
    }


def segment_channel_summary(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    contributions: Optional[Dict] = None,
    ltv: Optional[Dict[str, float]] = None,
    n_permutations: int = 200,
) -> pd.DataFrame:
    """
    Channel x segment summary: total volume contribution, spend, ROAS/CPA,
    and (if `ltv` is given) LTV-weighted value contribution and value ROAS.
    """
    contributions = contributions or compute_shapley_contributions(frame, meta, params, n_permutations)
    ltv = ltv or {}
    rows = []
    for ci, ch in enumerate(meta.channels):
        total_spend = float(frame["X_media"][:, ci].sum())
        for si, seg in enumerate(meta.segments):
            vol = float(contributions["channel_contributions"][ch][:, si].sum())
            value = vol * ltv.get(seg, 1.0)
            rows.append({
                "channel": ch,
                "segment": seg,
                "spend": total_spend,
                "volume_contribution": vol,
                "roas": vol / total_spend if total_spend > 0 else np.nan,
                "cpa": total_spend / vol if vol > 0 else np.nan,
                "ltv": ltv.get(seg),
                "value_contribution": value,
                "value_roas": value / total_spend if total_spend > 0 else np.nan,
            })
    return pd.DataFrame(rows)


def total_fh_contribution(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    contributions: Optional[Dict] = None,
    ltv: Optional[Dict[str, float]] = None,
    n_permutations: int = 200,
    segments: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Total-FH (all Family History segments summed) view per channel, plus
    which segment the impact falls into.

    `segments` restricts which of `meta.segments` are summed into the total
    - pass the Family History segment subset when the fitted model also
    includes DNA-product segments (core.outcomes), so a GSA count and a kit-
    sale count are never summed into one meaningless combined number.
    Defaults to every segment in `meta.segments`, preserving existing
    behaviour for a fit with no DNA segments (where "every segment" already
    means "every FH segment").
    """
    summary = segment_channel_summary(frame, meta, params, contributions, ltv, n_permutations)
    if segments is not None:
        summary = summary[summary["segment"].isin(segments)]
    total = summary.groupby("channel").agg(
        spend=("spend", "first"),
        volume_contribution=("volume_contribution", "sum"),
        value_contribution=("value_contribution", "sum"),
    ).reset_index()
    total["roas"] = total["volume_contribution"] / total["spend"].replace(0, np.nan)
    total["value_roas"] = total["value_contribution"] / total["spend"].replace(0, np.nan)

    pivot = summary.pivot(index="channel", columns="segment", values="volume_contribution")
    pivot = pivot.div(pivot.sum(axis=1), axis=0).add_suffix("_share")
    return total.merge(pivot.reset_index(), on="channel", how="left")


def contribution_waterfall(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    segment: Optional[str] = None,
    contributions: Optional[Dict] = None,
    n_permutations: int = 200,
) -> pd.DataFrame:
    """
    Waterfall rows: baseline, then each channel's contribution, then total.
    If `segment` is None, sums across all segments (total FH); otherwise a
    single segment's waterfall.
    """
    contributions = contributions or compute_shapley_contributions(frame, meta, params, n_permutations)
    seg_idx = meta.segments.index(segment) if segment else None

    def total(arr: np.ndarray) -> float:
        return float(arr[:, seg_idx].sum()) if seg_idx is not None else float(arr.sum())

    rows = [{"category": "Baseline", "value": total(contributions["baseline"])}]
    for ch in meta.channels:
        rows.append({"category": ch, "value": total(contributions["channel_contributions"][ch])})
    rows.append({"category": "Total", "value": total(contributions["mu_total"])})
    return pd.DataFrame(rows)


def calculate_roi(
    channel_contributions: Dict[str, float],
    channel_spend: Dict[str, float],
    credible_intervals: Optional[Dict[str, Tuple[float, float]]] = None,
) -> pd.DataFrame:
    """Generic ROI table for pages that already have flat contribution/spend dicts."""
    data = []
    for channel in channel_contributions:
        contrib = channel_contributions[channel]
        spend = channel_spend.get(channel, 0)
        roi = contrib / spend if spend > 0 else 0
        row = {"channel": channel, "spend": spend, "contribution": contrib, "roi": roi}
        if credible_intervals and channel in credible_intervals:
            ci_low, ci_high = credible_intervals[channel]
            row["roi_ci_lower"] = ci_low / spend if spend > 0 else 0
            row["roi_ci_upper"] = ci_high / spend if spend > 0 else 0
        data.append(row)
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# Generic helpers (kept from the original single-KPI implementation)
# ---------------------------------------------------------------------------

def compute_shapley_values(
    baseline: float,
    channel_effects: Dict[str, float],
) -> Dict[str, float]:
    """Shapley values for an additive value function (single-KPI, non-FH use)."""
    channels = list(channel_effects.keys())
    n = len(channels)

    if n == 0:
        return {}

    if n > 10:
        return _shapley_sampling(baseline, channel_effects, n_samples=1000)

    shapley = {ch: 0.0 for ch in channels}

    def value_function(coalition: set) -> float:
        if not coalition:
            return baseline
        total = baseline
        for ch in coalition:
            total += channel_effects[ch]
        return total

    for channel in channels:
        marginal_sum = 0.0
        others = [ch for ch in channels if ch != channel]

        for k in range(len(others) + 1):
            for subset in combinations(others, k):
                subset_set = set(subset)
                with_channel = subset_set | {channel}
                marginal = value_function(with_channel) - value_function(subset_set)
                weight = (
                    np.math.factorial(len(subset_set)) *
                    np.math.factorial(n - len(subset_set) - 1) /
                    np.math.factorial(n)
                )
                marginal_sum += weight * marginal

        shapley[channel] = marginal_sum

    return shapley


def _shapley_sampling(
    baseline: float,
    channel_effects: Dict[str, float],
    n_samples: int = 1000,
) -> Dict[str, float]:
    channels = list(channel_effects.keys())
    shapley = {ch: 0.0 for ch in channels}
    rng = np.random.default_rng(42)

    for _ in range(n_samples):
        perm = rng.permutation(channels)
        current_value = baseline
        for channel in perm:
            new_value = current_value + channel_effects[channel]
            shapley[channel] += (new_value - current_value)
            current_value = new_value

    for ch in channels:
        shapley[ch] /= n_samples

    return shapley


def decompose_sales(
    y: np.ndarray,
    baseline: np.ndarray,
    channel_contributions: Dict[str, np.ndarray],
    seasonality: Optional[np.ndarray] = None,
    trend: Optional[np.ndarray] = None,
) -> pd.DataFrame:
    n = len(y)
    data = {
        'actual': y,
        'baseline': baseline if len(baseline) == n else np.full(n, baseline),
    }
    for channel, contrib in channel_contributions.items():
        data[f'channel_{channel}'] = contrib
    if seasonality is not None:
        data['seasonality'] = seasonality
    if trend is not None:
        data['trend'] = trend

    fitted = data['baseline'].copy()
    for key in data:
        if key.startswith('channel_') or key in ['seasonality', 'trend']:
            fitted = fitted + data[key]

    data['fitted'] = fitted
    data['residual'] = y - fitted
    return pd.DataFrame(data)
