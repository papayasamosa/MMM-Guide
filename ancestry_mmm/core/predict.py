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
from .outcomes import fh_gsa_outcome_ids, fh_signup_outcome_ids, dna_kit_sale_outcome_ids


@dataclass
class FHPosteriorParams:
    """Posterior point estimates (defaults to the mean) needed to replay the model."""
    decay_rate: Dict[str, float]
    hill_K: Dict[str, float]
    hill_S: Dict[str, float]
    beta: Dict[str, Dict[str, float]]          # beta[outcome_id][channel]
    halo_strength: Dict[str, float]            # halo_strength[outcome_id]
    promo_coef: Dict[str, float]                # promo_coef[outcome_id]
    market_offset: Dict[str, Dict[str, float]]  # market_offset[market][outcome_id]
    intercept: Dict[str, float]
    trend_coef: Dict[str, float]
    gamma_fourier: Dict[str, np.ndarray]        # gamma_fourier[outcome_id] -> (n_fourier,)
    alpha: Dict[str, float]
    control_coef: Dict[str, float]
    outcome_control_coef: Dict[str, Dict[str, float]]  # [outcome_id][control_name]


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
    intercept = by_coord("intercept", "outcome", meta.outcome_ids)
    trend_coef = by_coord("trend_coef", "outcome", meta.outcome_ids)
    promo_coef = by_coord("promo_coef", "outcome", meta.outcome_ids)
    alpha = by_coord("alpha", "outcome", meta.outcome_ids)
    halo_strength = by_coord("halo_strength", "outcome", meta.outcome_ids) if meta.dna_channel_idx else {
        s: 0.0 for s in meta.outcome_ids
    }

    beta_reduced = _reduce(post["beta"])
    beta = {
        s: {c: float(beta_reduced.sel(outcome=s, channel=c).values) for c in meta.channels}
        for s in meta.outcome_ids
    }

    market_offset_reduced = _reduce(post["market_offset"])
    market_offset = {
        m: {s: float(market_offset_reduced.sel(market=m, outcome=s).values) for s in meta.outcome_ids}
        for m in meta.markets
    }

    gamma_fourier_reduced = _reduce(post["gamma_fourier"])
    gamma_fourier = {
        s: gamma_fourier_reduced.sel(outcome=s).values for s in meta.outcome_ids
    }

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

    return FHPosteriorParams(
        decay_rate=decay_rate, hill_K=hill_K, hill_S=hill_S, beta=beta,
        halo_strength=halo_strength, promo_coef=promo_coef, market_offset=market_offset,
        intercept=intercept, trend_coef=trend_coef, gamma_fourier=gamma_fourier, alpha=alpha,
        control_coef=control_coef, outcome_control_coef=outcome_control_coef,
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

    Returns mu, shape (n_obs, n_outcomes), matching frame["outcome_ids"] order.
    """
    outcome_ids = meta.outcome_ids
    n_obs = frame["X_media"].shape[0]
    n_out = len(outcome_ids)

    sat_media = adstock_saturate_frame(frame["X_media"], frame["market_bounds"], meta, params)

    beta_matrix = np.array([[params.beta[s][c] for c in meta.channels] for s in outcome_ids])  # (O, C)
    if meta.dna_channel_idx:
        dna_direct_media = sat_media[:, meta.dna_channel_idx]
        dna_halo_media = lag_frame(dna_direct_media, frame["market_bounds"], meta.dna_lag_weeks)
        eta_nondna = sat_media[:, meta.non_dna_idx] @ beta_matrix[:, meta.non_dna_idx].T if meta.non_dna_idx else np.zeros((n_obs, n_out))
        has_direct = np.array([1.0 if s in meta.direct_dna_outcome_ids else 0.0 for s in outcome_ids])
        # Masked by halo_eligible_outcome_ids (not just trusting
        # params.halo_strength to already be zero) so a kit-only outcome_id
        # structurally never picks up a halo contribution here, regardless
        # of what's in params.
        halo_eligible = set(meta.halo_eligible_outcome_ids)
        halo = np.array([params.halo_strength.get(s, 0.0) if s in halo_eligible else 0.0 for s in outcome_ids])
        eta_dna_direct = (dna_direct_media @ beta_matrix[:, meta.dna_channel_idx].T) * has_direct[None, :]
        eta_dna_halo = (dna_halo_media @ beta_matrix[:, meta.dna_channel_idx].T) * halo[None, :]
        eta_channels = eta_nondna + eta_dna_direct + eta_dna_halo
    else:
        eta_channels = sat_media @ beta_matrix.T

    promo_coef = np.array([params.promo_coef[s] for s in outcome_ids])
    eta_promo = frame["promo"] * promo_coef[None, :]

    market_idx = frame["market_idx"]
    market_offset_matrix = np.array([[params.market_offset[m][s] for s in outcome_ids] for m in meta.markets])
    eta_market = market_offset_matrix[market_idx]

    intercept = np.array([params.intercept[s] for s in outcome_ids])
    trend_coef = np.array([params.trend_coef[s] for s in outcome_ids])
    eta_trend = frame["trend"][:, None] * trend_coef[None, :]

    gamma_fourier_matrix = np.column_stack([params.gamma_fourier[s] for s in outcome_ids])  # (F, O)
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


def steady_state_outcome_response(
    market: str,
    spend_by_channel: Dict[str, float],
    meta: FHModelMeta,
    params: FHPosteriorParams,
    reference_context: Optional[Dict] = None,
) -> Dict[str, float]:
    """
    Expected weekly outcome per outcome_id for spend held constant at
    `spend_by_channel` levels in `market`, holding trend/seasonality/promo/
    controls at reference (typically recent-average) levels. This is the
    steady-state approximation used by the scenario planner - see module
    docstring.
    """
    reference_context = reference_context or {}
    outcome_ids = meta.outcome_ids

    sat = {}
    for c in meta.channels:
        x = spend_by_channel.get(c, 0.0)
        sat[c] = hill_function(np.array([x]), params.hill_K[c], params.hill_S[c])[0]

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
            if c in meta.dna_channels:
                # At steady state, spend is held constant forever, so
                # dna_direct_media and dna_halo_media (a lag of that same
                # constant series) converge to the identical value `sat[c]` -
                # the two pathways collapse to one multiplier here, the sum
                # of whichever of has_direct/halo_strength apply to `s`
                # (both, for `dna_outcome_id`; exactly one, for everyone
                # else - see core.hierarchical_model.FHModelMeta).
                weight = params.halo_strength.get(s, 0.0) if s in meta.halo_eligible_outcome_ids else 0.0
                if s in meta.direct_dna_outcome_ids:
                    weight += 1.0
                val += params.beta[s][c] * sat[c] * weight
            else:
                val += params.beta[s][c] * sat[c]

        for name, coef in params.control_coef.items():
            val += coef * reference_context.get("controls", {}).get(name, 0.0)
        if s in params.outcome_control_coef:
            for name, coef in params.outcome_control_coef[s].items():
                val += coef * reference_context.get("outcome_controls", {}).get(s, {}).get(name, 0.0)

        eta[s] = val

    return {s: float(np.clip(np.exp(v), 1e-6, 1e9)) for s, v in eta.items()}


# Deprecated alias (PR E.1 segment-era rename) - kept because this name is
# part of this module's public API surface (core/__init__.py re-exports it)
# and may still be imported by external/legacy callers. Prefer
# steady_state_outcome_response in new code.
steady_state_segment_response = steady_state_outcome_response


def generate_channel_curve(
    channel: str,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    spend_range: Optional[np.ndarray] = None,
    n_points: int = 25,
    max_spend: Optional[float] = None,
) -> pd.DataFrame:
    """
    Spend -> incremental response curve for one channel, per outcome_id and
    overall - the Model A ("shared curve") equivalent of
    core.market_specific_predict.generate_market_channel_curve, kept
    symmetric with it (same column shape: spend, saturation,
    {outcome_id}_response..., overall_response, fh_response, dna_response) so
    downstream consumers - core.media_units's CPA/media-unit calculations,
    the curve bank - can work on either model type's curve without
    branching on which one produced it.

    `fh_response`/`fh_signup_response`/`dna_response` split `overall_response`
    by product AND metric (PR E.1 - docs/dna_fh_causal_structure.md's "never
    sum kits and GSAs as one volume", extended to "never sum sign-ups and
    GSAs as one volume" either, since both can now be independently fitted
    outcome_ids on the same segment): `dna_response` is the sum over
    outcome_ids with `product == DNA` (`core.outcomes.dna_kit_sale_outcome_ids`),
    `fh_response` is the sum over outcome_ids with `product == Family History
    and metric == "GSA"` (`core.outcomes.fh_gsa_outcome_ids`) - NOT "every
    other outcome_id" as before, which silently included any FH sign-up
    outcome in what was labelled a GSA total. `fh_signup_response` is the
    analogous sum for `metric == "Sign-up"`
    (`core.outcomes.fh_signup_outcome_ids`). `overall_response` remains the
    sum of every outcome_id regardless of product/metric/role, unchanged in
    value - it is not removed, since plenty of existing callers (and the
    curve bank) still want "this channel's total modelled response" as one
    number; it is never used as a CPA/objective denominator on its own
    (`core.media_units.compute_cpa` blocks that when the curve genuinely
    mixes products). For the overwhelming majority of curves (no DNA-kit
    outcomes, no distinct sign-up outcome), `dna_response`/`fh_signup_response`
    are identically zero and `overall_response == fh_response`, unchanged
    from before this split existed.

    Steady-state approximation (see module docstring): channels don't
    interact in this model's linear predictor, so a channel's own curve
    doesn't depend on any other channel's spend level - each point is just
    that channel's own Hill saturation curve, scaled by each outcome_id's
    beta (and, for a DNA channel, that outcome_id's direct-plus-halo weight
    - see steady_state_outcome_response). Point estimates only (posterior
    means), same convention as steady_state_outcome_response.
    """
    if channel not in meta.channels:
        raise ValueError(f"'{channel}' is not one of this model's channels: {meta.channels}")

    K = params.hill_K[channel]
    S = params.hill_S[channel]
    if spend_range is None:
        cap = max_spend if max_spend is not None else max(K * 3, 1.0)
        spend_range = np.linspace(0.0, cap, n_points)

    is_dna = channel in meta.dna_channels
    gsa_ids = set(fh_gsa_outcome_ids(meta))
    signup_ids = set(fh_signup_outcome_ids(meta))
    dna_ids = set(dna_kit_sale_outcome_ids(meta))
    rows = []
    for spend in spend_range:
        sat = float(hill_function(np.array([float(spend)]), K, S)[0])
        row = {"channel": channel, "spend": float(spend), "saturation": sat}
        overall = 0.0
        dna_total = 0.0
        fh_gsa_total = 0.0
        fh_signup_total = 0.0
        for oid in meta.outcome_ids:
            beta_val = params.beta[oid][channel]
            if is_dna:
                # Same steady-state collapse as steady_state_outcome_response:
                # dna_direct_media and dna_halo_media converge to the same
                # constant `sat` here, so the two pathways' weights just add.
                weight = params.halo_strength.get(oid, 0.0) if oid in meta.halo_eligible_outcome_ids else 0.0
                if oid in meta.direct_dna_outcome_ids:
                    weight += 1.0
                beta_val = beta_val * weight
            value = beta_val * sat
            row[f"{oid}_response"] = value
            overall += value
            if oid in dna_ids:
                dna_total += value
            elif oid in gsa_ids:
                fh_gsa_total += value
            elif oid in signup_ids:
                fh_signup_total += value
        row["overall_response"] = overall
        row["dna_response"] = dna_total
        row["fh_response"] = fh_gsa_total
        row["fh_signup_response"] = fh_signup_total
        rows.append(row)

    return pd.DataFrame(rows)
