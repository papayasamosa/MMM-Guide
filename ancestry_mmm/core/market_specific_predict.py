"""
NumPy replay of the market-specific hierarchical FH model's math ("Model C" -
core.market_specific_model), mirroring core.predict but with market-indexed
`hill_K` and `beta`. Kept as a fully separate module from core.predict
(rather than adding market-awareness to the existing functions) so Model A's
already-shipped, tested prediction path is untouched - see
docs/decision_log.md.

decay_rate and hill_S stay shared across markets (not indexed by market) -
matching core.market_specific_model's structure exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import arviz as az
import numpy as np
import pandas as pd

from .hierarchical_model import FHModelMeta
from .predict import lag_frame
from .transformations import geometric_adstock_matrix, hill_function


@dataclass
class FHMarketSpecificPosteriorParams:
    """Posterior point estimates (posterior means) needed to replay Model C.
    Same shape as core.predict.FHPosteriorParams except `hill_K` and `beta`
    carry an extra market key."""
    decay_rate: Dict[str, float]                          # decay_rate[channel] - shared
    hill_K: Dict[str, Dict[str, float]]                    # hill_K[market][channel]
    hill_S: Dict[str, float]                               # hill_S[channel] - shared
    beta: Dict[str, Dict[str, Dict[str, float]]]           # beta[market][segment][channel]
    halo_strength: Dict[str, float]                        # halo_strength[segment] - shared
    promo_coef: Dict[str, float]
    market_offset: Dict[str, Dict[str, float]]
    intercept: Dict[str, float]
    trend_coef: Dict[str, float]
    gamma_fourier: Dict[str, np.ndarray]
    alpha: Dict[str, float]
    control_coef: Dict[str, float]
    segment_control_coef: Dict[str, Dict[str, float]]


def extract_market_specific_posterior_params(
    trace: az.InferenceData, meta: FHModelMeta, at: Optional[tuple[int, int]] = None,
) -> FHMarketSpecificPosteriorParams:
    """
    Pull posterior values into plain dicts keyed by name - the posterior
    mean (across every chain and draw) by default, or one specific
    `(chain, draw)` index pair when `at` is given (see
    core.predict.extract_posterior_params's docstring - `at` is what makes
    per-draw uncertainty calculations possible, core.uncertainty).
    """
    post = trace.posterior

    def _reduce(da):
        if at is not None:
            return da.isel(chain=at[0], draw=at[1])
        return da.mean(dim=["chain", "draw"])

    def by_coord(var: str, coord: str, labels: List[str]) -> Dict[str, float]:
        da = post[var]
        vals = da.isel(chain=at[0], draw=at[1]) if at is not None else da.mean(dim=[d for d in da.dims if d not in (coord,)])
        return {label: float(vals.sel({coord: label}).values) for label in labels}

    decay_rate = by_coord("decay_rate", "channel", meta.channels)
    hill_S = by_coord("hill_S", "channel", meta.channels)
    intercept = by_coord("intercept", "segment", meta.segments)
    trend_coef = by_coord("trend_coef", "segment", meta.segments)
    promo_coef = by_coord("promo_coef", "segment", meta.segments)
    alpha = by_coord("alpha", "segment", meta.segments)
    halo_strength = by_coord("halo_strength", "segment", meta.segments) if meta.dna_channel_idx else {
        s: 0.0 for s in meta.segments
    }

    hill_K_reduced = _reduce(post["hill_K"])
    hill_K = {
        m: {c: float(hill_K_reduced.sel(market=m, channel=c).values) for c in meta.channels}
        for m in meta.markets
    }

    beta_reduced = _reduce(post["beta"])
    beta = {
        m: {
            s: {c: float(beta_reduced.sel(market=m, segment=s, channel=c).values) for c in meta.channels}
            for s in meta.segments
        }
        for m in meta.markets
    }

    market_offset_reduced = _reduce(post["market_offset"])
    market_offset = {
        m: {s: float(market_offset_reduced.sel(market=m, segment=s).values) for s in meta.segments}
        for m in meta.markets
    }

    gamma_fourier_reduced = _reduce(post["gamma_fourier"])
    gamma_fourier = {s: gamma_fourier_reduced.sel(segment=s).values for s in meta.segments}

    control_coef = {}
    if meta.control_names and "control_coef" in post:
        cc_reduced = _reduce(post["control_coef"])
        control_coef = {c: float(cc_reduced.sel(control=c).values) for c in meta.control_names}

    segment_control_coef: Dict[str, Dict[str, float]] = {}
    for seg, names in meta.segment_control_names.items():
        var_name = f"segment_control_coef_{seg}"
        if var_name in post:
            coord_name = f"{seg}_control"
            v_reduced = _reduce(post[var_name])
            segment_control_coef[seg] = {n: float(v_reduced.sel({coord_name: n}).values) for n in names}

    return FHMarketSpecificPosteriorParams(
        decay_rate=decay_rate, hill_K=hill_K, hill_S=hill_S, beta=beta,
        halo_strength=halo_strength, promo_coef=promo_coef, market_offset=market_offset,
        intercept=intercept, trend_coef=trend_coef, gamma_fourier=gamma_fourier, alpha=alpha,
        control_coef=control_coef, segment_control_coef=segment_control_coef,
    )


def adstock_saturate_frame_market_specific(
    X_media: np.ndarray,
    market_bounds: List[tuple],
    markets: List[str],
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
) -> np.ndarray:
    """Per-market-block adstock (shared decay) + Hill saturation (market-specific K, shared S)."""
    decay = np.array([params.decay_rate[c] for c in meta.channels])
    S = np.array([params.hill_S[c] for c in meta.channels])

    out = np.zeros_like(X_media, dtype=float)
    for m, (start, end) in zip(markets, market_bounds):
        K = np.array([params.hill_K[m][c] for c in meta.channels])
        adstocked = geometric_adstock_matrix(X_media[start:end], decay, normalize=True)
        out[start:end] = hill_function(adstocked, K, S)
    return out


def predict_mu_market_specific(
    frame: Dict,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
) -> np.ndarray:
    """Replay Model C's full linear predictor in NumPy. Returns mu, shape
    (n_obs, n_segments), matching frame["segments"] order - same contract as
    core.predict.predict_mu."""
    segments = meta.segments
    markets = frame["markets"]
    n_obs = frame["X_media"].shape[0]
    n_seg = len(segments)

    sat_media = adstock_saturate_frame_market_specific(
        frame["X_media"], frame["market_bounds"], markets, meta, params
    )

    market_idx = frame["market_idx"]
    # beta_by_row[obs, segment, channel] - this row's own market's beta.
    beta_stack = np.array([
        [[params.beta[m][s][c] for c in meta.channels] for s in segments] for m in markets
    ])  # (n_market, n_segment, n_channel)
    beta_by_row = beta_stack[market_idx]  # (n_obs, n_segment, n_channel)

    if meta.dna_channel_idx:
        dna_direct_media = sat_media[:, meta.dna_channel_idx]
        dna_halo_media = lag_frame(dna_direct_media, frame["market_bounds"], meta.dna_lag_weeks)
        has_direct = np.array([1.0 if s in meta.direct_dna_segments else 0.0 for s in segments])
        # Masked by halo_eligible_segments (not just trusting params.halo_strength
        # to already be zero) so a kit-only segment structurally never picks up
        # a halo contribution here, regardless of what's in params.
        halo_eligible = set(meta.halo_eligible_segments)
        halo = np.array([params.halo_strength.get(s, 0.0) if s in halo_eligible else 0.0 for s in segments])
        if meta.non_dna_idx:
            eta_nondna = np.einsum(
                "oc,osc->os", sat_media[:, meta.non_dna_idx], beta_by_row[:, :, meta.non_dna_idx]
            )
        else:
            eta_nondna = np.zeros((n_obs, n_seg))
        eta_dna_direct = np.einsum("oc,osc->os", dna_direct_media, beta_by_row[:, :, meta.dna_channel_idx]) * has_direct[None, :]
        eta_dna_halo = np.einsum("oc,osc->os", dna_halo_media, beta_by_row[:, :, meta.dna_channel_idx]) * halo[None, :]
        eta_channels = eta_nondna + eta_dna_direct + eta_dna_halo
    else:
        eta_channels = np.einsum("oc,osc->os", sat_media, beta_by_row)

    promo_coef = np.array([params.promo_coef[s] for s in segments])
    eta_promo = frame["promo"] * promo_coef[None, :]

    market_offset_matrix = np.array([[params.market_offset[m][s] for s in segments] for m in markets])
    eta_market = market_offset_matrix[market_idx]

    intercept = np.array([params.intercept[s] for s in segments])
    trend_coef = np.array([params.trend_coef[s] for s in segments])
    eta_trend = frame["trend"][:, None] * trend_coef[None, :]

    gamma_fourier_matrix = np.column_stack([params.gamma_fourier[s] for s in segments])
    eta_season = frame["fourier"] @ gamma_fourier_matrix

    eta = intercept[None, :] + eta_market + eta_trend + eta_season + eta_channels + eta_promo

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

    mu = np.clip(np.exp(eta), 1e-6, 1e9)
    return mu


def steady_state_segment_response_market_specific(
    market: str,
    spend_by_channel: Dict[str, float],
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    reference_context: Optional[Dict] = None,
) -> Dict[str, float]:
    """Market-specific-model equivalent of core.predict.steady_state_segment_response -
    same steady-state approximation, using `market`'s own K and beta."""
    reference_context = reference_context or {}
    segments = meta.segments

    sat = {}
    for c in meta.channels:
        x = spend_by_channel.get(c, 0.0)
        sat[c] = hill_function(np.array([x]), params.hill_K[market][c], params.hill_S[c])[0]

    eta = {}
    for s in segments:
        val = params.intercept[s]
        val += params.market_offset.get(market, {}).get(s, 0.0)
        val += params.trend_coef[s] * reference_context.get("trend", 1.0)
        gamma = params.gamma_fourier[s]
        fourier_ref = reference_context.get("fourier", np.zeros_like(gamma))
        val += float(np.dot(gamma, fourier_ref))
        val += params.promo_coef[s] * reference_context.get("promo", {}).get(s, 0.0)

        for c in meta.channels:
            beta_val = params.beta[market][s][c]
            if c in meta.dna_channels:
                # Steady-state collapse (dna_direct_media == dna_halo_media
                # at constant spend) - see core.predict.steady_state_segment_response.
                weight = params.halo_strength.get(s, 0.0) if s in meta.halo_eligible_segments else 0.0
                if s in meta.direct_dna_segments:
                    weight += 1.0
                val += beta_val * sat[c] * weight
            else:
                val += beta_val * sat[c]

        for name, coef in params.control_coef.items():
            val += coef * reference_context.get("controls", {}).get(name, 0.0)
        if s in params.segment_control_coef:
            for name, coef in params.segment_control_coef[s].items():
                val += coef * reference_context.get("segment_controls", {}).get(s, {}).get(name, 0.0)

        eta[s] = val

    return {s: float(np.clip(np.exp(v), 1e-6, 1e9)) for s, v in eta.items()}


def generate_market_channel_curve(
    market: str,
    channel: str,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    spend_range: Optional[np.ndarray] = None,
    n_points: int = 25,
    max_spend: Optional[float] = None,
) -> pd.DataFrame:
    """
    Spend -> incremental response curve for one (market, channel), per
    segment and overall - the "market-specific channel curve" and "overall
    market-level curve" deliverables from docs/market_hierarchy.md section 3
    and docs/segment_methodology.md's aggregation rule (overall = sum of
    segment responses, never an independently fitted "Overall" outcome).

    Steady-state approximation (see core.predict module docstring): channels
    don't interact in this model's linear predictor, so a channel's own
    curve doesn't depend on any other channel's spend level - each point is
    just that channel's own Hill saturation curve, scaled by each segment's
    beta (and, for a DNA channel, the halo strength).

    Point estimates only (posterior means) - matching the existing curve
    bank/scenario planner convention (core.predict.steady_state_segment_response).
    Credible intervals are explicitly Phase 3 scope (docs/media_units_and_inflation.md).
    """
    if market not in params.hill_K:
        raise ValueError(f"'{market}' is not one of this model's markets: {list(params.hill_K)}")
    if channel not in meta.channels:
        raise ValueError(f"'{channel}' is not one of this model's channels: {meta.channels}")

    K = params.hill_K[market][channel]
    S = params.hill_S[channel]
    if spend_range is None:
        cap = max_spend if max_spend is not None else max(K * 3, 1.0)
        spend_range = np.linspace(0.0, cap, n_points)

    is_dna = channel in meta.dna_channels
    rows = []
    for spend in spend_range:
        sat = float(hill_function(np.array([float(spend)]), K, S)[0])
        row = {"market": market, "channel": channel, "spend": float(spend), "saturation": sat}
        overall = 0.0
        for seg in meta.segments:
            beta_val = params.beta[market][seg][channel]
            if is_dna:
                weight = params.halo_strength.get(seg, 0.0) if seg in meta.halo_eligible_segments else 0.0
                if seg in meta.direct_dna_segments:
                    weight += 1.0
                beta_val = beta_val * weight
            value = beta_val * sat
            row[f"{seg}_response"] = value
            overall += value
        row["overall_response"] = overall
        rows.append(row)

    return pd.DataFrame(rows)
