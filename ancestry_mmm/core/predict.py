"""
NumPy replay of the joint hierarchical FH model's math, driven by posterior
parameter estimates rather than PyMC/PyTensor.

Two different jobs need to evaluate "what would the model predict for these
inputs" *outside* of an active MCMC run:

1. Out-of-sample diagnostics (rolling-origin backtest) - predict a held-out
   period from parameters fit on an earlier period.
2. Scenario planning - predict expected outcomes for a hypothetical spend
   allocation, fast enough to sit inside an optimiser's objective function.

Both use the same steady-state approximation for (2): under spend held
constant at a given weekly level, geometric adstock converges to that same
level (that's what the `normalize=True` scaling is for), so the channel's
contribution simplifies to the Hill saturation curve evaluated at that
spend level directly - no need to simulate the week-by-week adstock
recursion. This is the standard approximation response-curve-based MMM
budget optimisers use; it is documented here rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import arviz as az

from .transformations import geometric_adstock_matrix, hill_function
from .hierarchical_model import FHModelMeta


@dataclass
class FHPosteriorParams:
    """Posterior point estimates (defaults to the mean) needed to replay the model."""
    decay_rate: Dict[str, float]
    hill_K: Dict[str, float]
    hill_S: Dict[str, float]
    beta: Dict[str, Dict[str, float]]          # beta[segment][channel]
    halo_strength: Dict[str, float]            # halo_strength[segment]
    promo_coef: Dict[str, float]                # promo_coef[segment]
    market_offset: Dict[str, Dict[str, float]]  # market_offset[market][segment]
    intercept: Dict[str, float]
    trend_coef: Dict[str, float]
    gamma_fourier: Dict[str, np.ndarray]        # gamma_fourier[segment] -> (n_fourier,)
    alpha: Dict[str, float]
    control_coef: Dict[str, float]
    segment_control_coef: Dict[str, Dict[str, float]]  # [segment][control_name]


def extract_posterior_params(
    trace: az.InferenceData, meta: FHModelMeta, at: Optional[tuple[int, int]] = None,
) -> FHPosteriorParams:
    """
    Pull posterior values into plain dicts keyed by name - the posterior
    mean (across every chain and draw) by default, or one specific
    `(chain, draw)` index pair when `at` is given.

    `at` is what makes per-draw uncertainty calculations possible
    (`core.uncertainty`): calling this once per sampled draw index produces
    a genuine posterior sample of `FHPosteriorParams`, not just the point
    estimate every other caller (curve bank, scenario planner) uses.
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
    hill_K = by_coord("hill_K", "channel", meta.channels)
    hill_S = by_coord("hill_S", "channel", meta.channels)
    intercept = by_coord("intercept", "segment", meta.segments)
    trend_coef = by_coord("trend_coef", "segment", meta.segments)
    promo_coef = by_coord("promo_coef", "segment", meta.segments)
    alpha = by_coord("alpha", "segment", meta.segments)
    halo_strength = by_coord("halo_strength", "segment", meta.segments) if meta.dna_channel_idx else {
        s: (1.0 if s in meta.direct_dna_segments else 0.0) for s in meta.segments
    }

    beta_reduced = _reduce(post["beta"])
    beta = {
        s: {c: float(beta_reduced.sel(segment=s, channel=c).values) for c in meta.channels}
        for s in meta.segments
    }

    market_offset_reduced = _reduce(post["market_offset"])
    market_offset = {
        m: {s: float(market_offset_reduced.sel(market=m, segment=s).values) for s in meta.segments}
        for m in meta.markets
    }

    gamma_fourier_reduced = _reduce(post["gamma_fourier"])
    gamma_fourier = {
        s: gamma_fourier_reduced.sel(segment=s).values for s in meta.segments
    }

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

    return FHPosteriorParams(
        decay_rate=decay_rate, hill_K=hill_K, hill_S=hill_S, beta=beta,
        halo_strength=halo_strength, promo_coef=promo_coef, market_offset=market_offset,
        intercept=intercept, trend_coef=trend_coef, gamma_fourier=gamma_fourier, alpha=alpha,
        control_coef=control_coef, segment_control_coef=segment_control_coef,
    )


def adstock_saturate_frame(
    X_media: np.ndarray,
    market_bounds: List[tuple],
    meta: FHModelMeta,
    params: FHPosteriorParams,
) -> np.ndarray:
    """NumPy adstock + Hill saturation per market block, matching the PyMC model exactly."""
    decay = np.array([params.decay_rate[c] for c in meta.channels])
    K = np.array([params.hill_K[c] for c in meta.channels])
    S = np.array([params.hill_S[c] for c in meta.channels])

    out = np.zeros_like(X_media, dtype=float)
    for start, end in market_bounds:
        adstocked = geometric_adstock_matrix(X_media[start:end], decay, normalize=True)
        out[start:end] = hill_function(adstocked, K, S)
    return out


def lag_frame(X: np.ndarray, market_bounds: List[tuple], lag_weeks: int) -> np.ndarray:
    out = np.zeros_like(X, dtype=float)
    for start, end in market_bounds:
        n = end - start
        if lag_weeks <= 0:
            out[start:end] = X[start:end]
        elif lag_weeks >= n:
            continue  # stays zero
        else:
            out[start + lag_weeks:end] = X[start:end - lag_weeks]
    return out


def predict_mu(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
) -> np.ndarray:
    """
    Replay the model's full linear predictor in NumPy for an arbitrary frame
    (historical, held-out, or a hypothetical scenario built with the same
    structure as data.preprocessor.prepare_fh_modeling_frame's output).

    Returns mu, shape (n_obs, n_segments), matching frame["segments"] order.
    """
    segments = meta.segments
    n_obs = frame["X_media"].shape[0]
    n_seg = len(segments)

    sat_media = adstock_saturate_frame(frame["X_media"], frame["market_bounds"], meta, params)

    beta_matrix = np.array([[params.beta[s][c] for c in meta.channels] for s in segments])  # (S, C)
    if meta.dna_channel_idx:
        lagged_dna = lag_frame(sat_media[:, meta.dna_channel_idx], frame["market_bounds"], meta.dna_lag_weeks)
        eta_nondna = sat_media[:, meta.non_dna_idx] @ beta_matrix[:, meta.non_dna_idx].T if meta.non_dna_idx else np.zeros((n_obs, n_seg))
        halo = np.array([params.halo_strength[s] for s in segments])
        eta_dna = (lagged_dna @ beta_matrix[:, meta.dna_channel_idx].T) * halo[None, :]
        eta_channels = eta_nondna + eta_dna
    else:
        eta_channels = sat_media @ beta_matrix.T

    promo_coef = np.array([params.promo_coef[s] for s in segments])
    eta_promo = frame["promo"] * promo_coef[None, :]

    market_idx = frame["market_idx"]
    market_offset_matrix = np.array([[params.market_offset[m][s] for s in segments] for m in meta.markets])
    eta_market = market_offset_matrix[market_idx]

    intercept = np.array([params.intercept[s] for s in segments])
    trend_coef = np.array([params.trend_coef[s] for s in segments])
    eta_trend = frame["trend"][:, None] * trend_coef[None, :]

    gamma_fourier_matrix = np.column_stack([params.gamma_fourier[s] for s in segments])  # (F, S)
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


def steady_state_segment_response(
    market: str,
    spend_by_channel: Dict[str, float],
    meta: FHModelMeta,
    params: FHPosteriorParams,
    reference_context: Optional[Dict] = None,
) -> Dict[str, float]:
    """
    Expected weekly outcome per segment for spend held constant at
    `spend_by_channel` levels in `market`, holding trend/seasonality/promo/
    controls at reference (typically recent-average) levels. This is the
    steady-state approximation used by the scenario planner - see module
    docstring.
    """
    reference_context = reference_context or {}
    segments = meta.segments

    sat = {}
    for c in meta.channels:
        x = spend_by_channel.get(c, 0.0)
        sat[c] = hill_function(np.array([x]), params.hill_K[c], params.hill_S[c])[0]

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
            if c in meta.dna_channels:
                if s in meta.direct_dna_segments:
                    val += params.beta[s][c] * sat[c]
                else:
                    val += params.beta[s][c] * sat[c] * params.halo_strength.get(s, 0.0)
            else:
                val += params.beta[s][c] * sat[c]

        for name, coef in params.control_coef.items():
            val += coef * reference_context.get("controls", {}).get(name, 0.0)
        if s in params.segment_control_coef:
            for name, coef in params.segment_control_coef[s].items():
                val += coef * reference_context.get("segment_controls", {}).get(s, {}).get(name, 0.0)

        eta[s] = val

    return {s: float(np.clip(np.exp(v), 1e-6, 1e9)) for s, v in eta.items()}


def generate_channel_curve(
    channel: str,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    spend_range: Optional[np.ndarray] = None,
    n_points: int = 25,
    max_spend: Optional[float] = None,
) -> pd.DataFrame:
    """
    Spend -> incremental response curve for one channel, per segment and
    overall - the Model A ("shared curve") equivalent of
    core.market_specific_predict.generate_market_channel_curve, kept
    symmetric with it (same column shape: spend, saturation,
    {segment}_response..., overall_response) so downstream consumers -
    core.media_units's CPA/media-unit calculations, the curve bank - can
    work on either model type's curve without branching on which one
    produced it.

    Steady-state approximation (see module docstring): channels don't
    interact in this model's linear predictor, so a channel's own curve
    doesn't depend on any other channel's spend level - each point is just
    that channel's own Hill saturation curve, scaled by each segment's beta
    (and, for a DNA channel, the halo strength). Point estimates only
    (posterior means), same convention as steady_state_segment_response.
    """
    if channel not in meta.channels:
        raise ValueError(f"'{channel}' is not one of this model's channels: {meta.channels}")

    K = params.hill_K[channel]
    S = params.hill_S[channel]
    if spend_range is None:
        cap = max_spend if max_spend is not None else max(K * 3, 1.0)
        spend_range = np.linspace(0.0, cap, n_points)

    is_dna = channel in meta.dna_channels
    rows = []
    for spend in spend_range:
        sat = float(hill_function(np.array([float(spend)]), K, S)[0])
        row = {"channel": channel, "spend": float(spend), "saturation": sat}
        overall = 0.0
        for seg in meta.segments:
            beta_val = params.beta[seg][channel]
            if is_dna and seg not in meta.direct_dna_segments:
                beta_val = beta_val * params.halo_strength.get(seg, 0.0)
            value = beta_val * sat
            row[f"{seg}_response"] = value
            overall += value
        row["overall_response"] = overall
        rows.append(row)

    return pd.DataFrame(rows)
