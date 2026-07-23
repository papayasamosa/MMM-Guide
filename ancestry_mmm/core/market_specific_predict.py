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
from .outcomes import (
    dna_kit_sale_outcome_ids, fh_gsa_outcome_ids, fh_net_billthrough_outcome_ids,
    fh_signup_outcome_ids,
)
from .predict import _cross_product_strength_matrix, _pathway_weight, extract_pathway_strength, lag_frame
from .transformations import geometric_adstock_matrix, hill_function


@dataclass
class FHMarketSpecificPosteriorParams:
    """Posterior point estimates (posterior means) needed to replay Model C.
    Same shape as core.predict.FHPosteriorParams except `hill_K` and `beta`
    carry an extra market key."""
    decay_rate: Dict[str, float]                          # decay_rate[channel] - shared
    hill_K: Dict[str, Dict[str, float]]                    # hill_K[market][channel]
    hill_S: Dict[str, float]                               # hill_S[channel] - shared
    beta: Dict[str, Dict[str, Dict[str, float]]]           # beta[market][outcome_id][channel]
    pathway_strength: Dict[str, Dict[str, float]]          # pathway_strength[outcome_id][channel] - PR G1,
    # not market-specific - active_cross_product_strength/exploratory_cross_product_strength
    # are fit with dims=("outcome", "channel") in build_fh_market_specific_model,
    # same as Model A (see core.predict.FHPosteriorParams.pathway_strength).
    promo_coef: Dict[str, float]
    market_offset: Dict[str, Dict[str, float]]
    intercept: Dict[str, float]
    trend_coef: Dict[str, float]
    gamma_fourier: Dict[str, np.ndarray]
    alpha: Dict[str, float]
    control_coef: Dict[str, float]
    outcome_control_coef: Dict[str, Dict[str, float]]


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
    intercept = by_coord("intercept", "outcome", meta.outcome_ids)
    trend_coef = by_coord("trend_coef", "outcome", meta.outcome_ids)
    promo_coef = by_coord("promo_coef", "outcome", meta.outcome_ids)
    alpha = by_coord("alpha", "outcome", meta.outcome_ids)
    pathway_strength = extract_pathway_strength(trace, meta, at=at)

    hill_K_reduced = _reduce(post["hill_K"])
    hill_K = {
        m: {c: float(hill_K_reduced.sel(market=m, channel=c).values) for c in meta.channels}
        for m in meta.markets
    }

    beta_reduced = _reduce(post["beta"])
    beta = {
        m: {
            s: {c: float(beta_reduced.sel(market=m, outcome=s, channel=c).values) for c in meta.channels}
            for s in meta.outcome_ids
        }
        for m in meta.markets
    }

    market_offset_reduced = _reduce(post["market_offset"])
    market_offset = {
        m: {s: float(market_offset_reduced.sel(market=m, outcome=s).values) for s in meta.outcome_ids}
        for m in meta.markets
    }

    gamma_fourier_reduced = _reduce(post["gamma_fourier"])
    gamma_fourier = {s: gamma_fourier_reduced.sel(outcome=s).values for s in meta.outcome_ids}

    control_coef = {}
    if meta.control_names and "control_coef" in post:
        cc_reduced = _reduce(post["control_coef"])
        control_coef = {c: float(cc_reduced.sel(control=c).values) for c in meta.control_names}

    outcome_control_coef: Dict[str, Dict[str, float]] = {}
    for oid, names in meta.outcome_control_names.items():
        var_name = f"outcome_control_coef_{oid}"
        if var_name in post:
            coord_name = f"{oid}_control"
            v_reduced = _reduce(post[var_name])
            outcome_control_coef[oid] = {n: float(v_reduced.sel({coord_name: n}).values) for n in names}

    return FHMarketSpecificPosteriorParams(
        decay_rate=decay_rate, hill_K=hill_K, hill_S=hill_S, beta=beta,
        pathway_strength=pathway_strength, promo_coef=promo_coef, market_offset=market_offset,
        intercept=intercept, trend_coef=trend_coef, gamma_fourier=gamma_fourier, alpha=alpha,
        control_coef=control_coef, outcome_control_coef=outcome_control_coef,
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
    (n_obs, n_outcomes), matching frame["outcome_ids"] order - same contract
    as core.predict.predict_mu."""
    outcome_ids = meta.outcome_ids
    markets = frame["markets"]
    n_obs = frame["X_media"].shape[0]
    n_out = len(outcome_ids)

    sat_media = adstock_saturate_frame_market_specific(
        frame["X_media"], frame["market_bounds"], markets, meta, params
    )

    market_idx = frame["market_idx"]
    # beta_by_row[obs, outcome, channel] - this row's own market's beta.
    beta_stack = np.array([
        [[params.beta[m][s][c] for c in meta.channels] for s in outcome_ids] for m in markets
    ])  # (n_market, n_outcome, n_channel)
    beta_by_row = beta_stack[market_idx]  # (n_obs, n_outcome, n_channel)

    # Pathway-masked replay (PR G1) - mirrors core.market_specific_model.
    # build_fh_market_specific_model's eta_primary/eta_active/eta_exploratory
    # construction exactly (same masks, same media, same beta multiplication,
    # same einsum contraction pattern) - see core.predict.predict_mu's
    # matching comment.
    primary_mask = meta.pathway_masks.primary_matrix(outcome_ids, meta.channels)  # (O, C)
    eta_primary = np.einsum("oc,osc->os", sat_media, beta_by_row * primary_mask[None, :, :])

    cross_cells = meta.pathway_masks.active_cells(outcome_ids, meta.channels) + meta.pathway_masks.exploratory_cells(outcome_ids, meta.channels)
    eta_cross = np.zeros((n_obs, n_out))
    if cross_cells:
        strength_matrix = _cross_product_strength_matrix(meta, params)
        lagged = {lag: lag_frame(sat_media, frame["market_bounds"], lag)
                  for lag in {meta.pathway_masks.lag_for_cell(cell) for cell in cross_cells}}
        for oi, ci in cross_cells:
            eta_cross[:, oi] += lagged[meta.pathway_masks.lag_for_cell((oi, ci))][:, ci] * beta_by_row[:, oi, ci] * strength_matrix[oi, ci]

    eta_channels = eta_primary + eta_cross

    promo_coef = np.array([params.promo_coef[s] for s in outcome_ids])
    eta_promo = frame["promo"] * promo_coef[None, :]

    market_offset_matrix = np.array([[params.market_offset[m][s] for s in outcome_ids] for m in markets])
    eta_market = market_offset_matrix[market_idx]

    intercept = np.array([params.intercept[s] for s in outcome_ids])
    trend_coef = np.array([params.trend_coef[s] for s in outcome_ids])
    eta_trend = frame["trend"][:, None] * trend_coef[None, :]

    gamma_fourier_matrix = np.column_stack([params.gamma_fourier[s] for s in outcome_ids])
    eta_season = frame["fourier"] @ gamma_fourier_matrix

    eta = intercept[None, :] + eta_market + eta_trend + eta_season + eta_channels + eta_promo

    outcome_controls = frame.get("outcome_controls") or {}
    outcome_control_names = frame.get("outcome_control_names") or {}
    for oid, arr in outcome_controls.items():
        if oid not in outcome_ids or oid not in params.outcome_control_coef:
            continue
        o_idx = outcome_ids.index(oid)
        names = outcome_control_names.get(oid, [])
        coefs = np.array([params.outcome_control_coef[oid].get(n, 0.0) for n in names])
        eta[:, o_idx] += arr @ coefs

    control_names = frame.get("control_names") or []
    if control_names and params.control_coef:
        coefs = np.array([params.control_coef.get(n, 0.0) for n in control_names])
        eta += (frame["X_controls"] @ coefs)[:, None]

    mu = np.clip(np.exp(eta), 1e-6, 1e9)
    return mu


def steady_state_outcome_response_market_specific(
    market: str,
    spend_by_channel: Dict[str, float],
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    reference_context: Optional[Dict] = None,
    *, planning_only: bool = False,
) -> Dict[str, float]:
    """Market-specific-model equivalent of core.predict.steady_state_outcome_response -
    same steady-state approximation, using `market`'s own K and beta."""
    reference_context = reference_context or {}
    outcome_ids = meta.outcome_ids

    sat = {}
    for c in meta.channels:
        x = spend_by_channel.get(c, 0.0)
        sat[c] = hill_function(np.array([x]), params.hill_K[market][c], params.hill_S[c])[0]

    eta = {}
    for s in outcome_ids:
        val = params.intercept[s]
        val += params.market_offset.get(market, {}).get(s, 0.0)
        val += params.trend_coef[s] * reference_context.get("trend", 1.0)
        gamma = params.gamma_fourier[s]
        fourier_ref = reference_context.get("fourier", np.zeros_like(gamma))
        val += float(np.dot(gamma, fourier_ref))
        val += params.promo_coef[s] * reference_context.get("promo", {}).get(s, 0.0)

        for c in meta.channels:
            # Steady-state collapse (primary and cross-product media converge
            # at constant spend) - see core.predict.steady_state_outcome_response.
            val += params.beta[market][s][c] * sat[c] * _pathway_weight(meta, params, s, c, planning_only=planning_only)

        for name, coef in params.control_coef.items():
            val += coef * reference_context.get("controls", {}).get(name, 0.0)
        if s in params.outcome_control_coef:
            for name, coef in params.outcome_control_coef[s].items():
                val += coef * reference_context.get("outcome_controls", {}).get(s, {}).get(name, 0.0)

        eta[s] = val

    return {s: float(np.clip(np.exp(v), 1e-6, 1e9)) for s, v in eta.items()}


# Deprecated alias (PR E.1 segment-era rename) - see core.predict's identical
# alias for steady_state_outcome_response.
steady_state_segment_response_market_specific = steady_state_outcome_response_market_specific


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
    outcome_id and overall - the "market-specific channel curve" and
    "overall market-level curve" deliverables from docs/market_hierarchy.md
    section 3 and docs/segment_methodology.md's aggregation rule (overall =
    sum of outcome responses, never an independently fitted "Overall"
    outcome). Also splits `overall_response` by product AND metric into
    `fh_response`/`fh_signup_response`/`dna_response` (PR E.1 -
    docs/dna_fh_causal_structure.md's "never sum kits and GSAs as one
    volume", extended to sign-ups vs. GSAs) - see
    core.predict.generate_channel_curve's docstring for the exact rule
    (`core.outcomes.fh_gsa_outcome_ids`/`fh_signup_outcome_ids`/
    `dna_kit_sale_outcome_ids`).

    Steady-state approximation (see core.predict module docstring): channels
    don't interact in this model's linear predictor, so a channel's own
    curve doesn't depend on any other channel's spend level - each point is
    just that channel's own Hill saturation curve, scaled by each
    outcome_id's beta (and, for a DNA channel, the halo strength).

    Point estimates only (posterior means) - matching the existing curve
    bank/scenario planner convention (core.predict.steady_state_outcome_response).
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

    gsa_ids = set(fh_gsa_outcome_ids(meta))
    nbt_ids = set(fh_net_billthrough_outcome_ids(meta))
    signup_ids = set(fh_signup_outcome_ids(meta))
    dna_ids = set(dna_kit_sale_outcome_ids(meta))
    rows = []
    for spend in spend_range:
        sat = float(hill_function(np.array([float(spend)]), K, S)[0])
        row = {"market": market, "channel": channel, "spend": float(spend), "saturation": sat}
        overall = 0.0
        dna_total = 0.0
        fh_gsa_total = 0.0
        fh_nbt_total = 0.0
        fh_signup_total = 0.0
        for oid in meta.outcome_ids:
            # Steady-state collapse - see steady_state_outcome_response_market_specific.
            beta_val = params.beta[market][oid][channel] * _pathway_weight(meta, params, oid, channel)
            value = beta_val * sat
            row[f"{oid}_response"] = value
            overall += value
            if oid in dna_ids:
                dna_total += value
            elif oid in gsa_ids:
                fh_gsa_total += value
            elif oid in nbt_ids:
                fh_nbt_total += value
            elif oid in signup_ids:
                fh_signup_total += value
        row["overall_response"] = overall
        row["dna_response"] = dna_total
        row["fh_response"] = fh_gsa_total
        row["fh_net_billthrough_response"] = fh_nbt_total
        row["fh_signup_response"] = fh_signup_total
        rows.append(row)

    return pd.DataFrame(rows)
