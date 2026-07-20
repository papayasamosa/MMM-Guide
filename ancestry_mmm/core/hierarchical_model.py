"""
Joint hierarchical Family-History (FH) MMM.

One Negative-Binomial outcome model per market, covering all FH segments
(New, DNA cross-sell, Winback, ...) jointly rather than as separate
unrelated fits. Channel-level adstock and saturation curves are *shared*
across segments and markets; segment-specific response strength, promo
sensitivity and the DNA halo pathway are estimated through partial
pooling, so segments borrow strength where data is thin and diverge where
the data supports it. See ancestry_mmm/core/schema.py for the ModelSpec
that defines markets/segments/channels/DNA channels/promo columns feeding
this builder, and data/preprocessor.prepare_fh_modeling_frame for how a
joined DataFrame becomes the arrays this function consumes.

Deliberately staged: geometric adstock + Hill saturation only for this
build (Stage 1 per the requirements brief - "ship a robust core before
harder-to-justify refinements"). Media x context interaction terms are out
of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pymc as pm
import pytensor.tensor as pt

from .transformations import pt_geometric_adstock_matrix, pt_hill_function
from .schema import ModelSpec


@dataclass
class FHModelMeta:
    """
    Structural metadata about a built model that isn't fully recoverable from
    the InferenceData's coords alone (e.g. which channels are DNA channels,
    the halo lag). core/predict.py uses this to replay the model's math in
    plain NumPy for scenario planning and out-of-sample diagnostics.
    """
    markets: List[str]
    segments: List[str]
    channels: List[str]
    dna_channels: List[str]
    dna_channel_idx: List[int]
    non_dna_idx: List[int]
    dna_segment: str
    dna_lag_weeks: int
    unpooled_markets: List[str]
    control_names: List[str]
    segment_control_names: Dict[str, List[str]] = field(default_factory=dict)


def _default_dna_segment(segments: List[str], dna_segment: Optional[str]) -> str:
    if dna_segment is not None:
        if dna_segment not in segments:
            raise ValueError(f"dna_segment '{dna_segment}' is not one of the model's segments: {segments}")
        return dna_segment
    for s in segments:
        if "dna" in s.lower():
            return s
    raise ValueError(
        "Could not infer which segment is the DNA cross-sell segment; pass dna_segment explicitly."
    )


def _market_grouped_adstock_and_saturation(
    X_media: np.ndarray,
    market_bounds: List[tuple],
    decay_rate: pt.TensorVariable,
    hill_K: pt.TensorVariable,
    hill_S: pt.TensorVariable,
) -> pt.TensorVariable:
    """
    Apply shared adstock + Hill saturation per market block, so carryover
    never leaks across a market boundary. `market_bounds` are (start, end)
    row-index pairs describing contiguous per-market slices of X_media
    (X_media is expected sorted by [market, date] - see prepare_fh_modeling_frame).
    """
    n_obs, n_channels = X_media.shape
    blocks = []
    for start, end in market_bounds:
        X_slice = pt.as_tensor_variable(X_media[start:end])
        adstocked = pt_geometric_adstock_matrix(X_slice, decay_rate, normalize=True)
        blocks.append(adstocked)
    adstocked_full = pt.concatenate(blocks, axis=0)
    saturated = pt_hill_function(adstocked_full, hill_K, hill_S)
    return saturated


def _market_grouped_lag(
    X: pt.TensorVariable,
    market_bounds: List[tuple],
    lag_weeks: int,
) -> pt.TensorVariable:
    """Shift a (n_obs, k) tensor by `lag_weeks`, resetting to zero at each market boundary."""
    blocks = []
    for start, end in market_bounds:
        n = end - start
        block = X[start:end]
        if lag_weeks <= 0:
            blocks.append(block)
        elif lag_weeks >= n:
            blocks.append(pt.zeros_like(block))
        else:
            pad = pt.zeros_like(block[:lag_weeks])
            blocks.append(pt.concatenate([pad, block[: n - lag_weeks]], axis=0))
    return pt.concatenate(blocks, axis=0)


def build_fh_hierarchical_model(
    frame: Dict[str, Any],
    spec: ModelSpec,
    dna_lag_weeks: int = 4,
    dna_segment: Optional[str] = None,
    prior_config: Optional[Dict] = None,
) -> "tuple[pm.Model, FHModelMeta]":
    """
    Build the joint hierarchical FH model.

    Args:
        frame: output of data.preprocessor.prepare_fh_modeling_frame
        spec: the ModelSpec used to build `frame`
        dna_lag_weeks: extra lag (beyond adstock carryover) applied to DNA-channel
            saturated media before it enters the DNA halo pathway
        dna_segment: which segment key is the DNA cross-sell segment (auto-detected
            from the segment names if not given)
        prior_config: optional dict of prior overrides (see defaults below)

    Returns:
        (unfit PyMC Model, FHModelMeta). Fit the model with core.models.fit_model;
        keep the FHModelMeta alongside the trace - core.predict needs it to
        replay this model's math in NumPy for scenario planning/diagnostics.
    """
    prior_config = prior_config or {}

    markets: List[str] = frame["markets"]
    market_idx: np.ndarray = frame["market_idx"]
    market_bounds: List[tuple] = frame["market_bounds"]
    channels: List[str] = frame["channels"]
    dna_channel_idx: List[int] = frame["dna_channel_idx"]
    segments: List[str] = frame["segments"]
    X_media: np.ndarray = frame["X_media"]
    Y: np.ndarray = frame["Y"]
    promo: np.ndarray = frame["promo"]
    X_controls: np.ndarray = frame["X_controls"]
    control_names: List[str] = frame["control_names"]
    fourier: np.ndarray = frame["fourier"]
    trend: np.ndarray = frame["trend"]
    unpooled_markets: List[str] = frame.get("unpooled_markets") or []

    n_obs, n_channels = X_media.shape
    n_segments = len(segments)
    n_markets = len(markets)
    n_fourier = fourier.shape[1]
    n_controls = X_controls.shape[1]

    dna_segment = _default_dna_segment(segments, dna_segment)
    dna_segment_idx = segments.index(dna_segment)
    non_dna_idx = [i for i, c in enumerate(channels) if i not in dna_channel_idx]

    channel_mean_spend = X_media.mean(axis=0)
    channel_mean_spend = np.where(channel_mean_spend > 0, channel_mean_spend, 1.0)

    with pm.Model() as model:
        model.add_coord("obs", np.arange(n_obs))
        model.add_coord("market", markets)
        model.add_coord("segment", segments)
        model.add_coord("channel", channels)
        model.add_coord("fourier", np.arange(n_fourier))

        # -----------------------------------------------------------------
        # Shared channel-level adstock + saturation curves (pooled across
        # segments AND markets - "share what should genuinely be shared").
        # -----------------------------------------------------------------
        decay_rate = pm.Beta(
            "decay_rate",
            mu=prior_config.get("decay_mu", 0.5),
            sigma=prior_config.get("decay_sigma", 0.2),
            dims="channel",
        )
        # Gamma (not HalfNormal): K is a half-saturation *spend level*, so its
        # prior should be centred near typical spend and bounded away from
        # zero. HalfNormal's mode sits at 0, which is both poor prior belief
        # (K=0 means everything is instantly saturated) and numerically
        # unstable (see pt_hill_function's docstring on the log(K) gradient).
        K_prior_mean = channel_mean_spend * prior_config.get("K_scale", 1.0)
        K_alpha = prior_config.get("K_alpha", 3.0)
        hill_K = pm.Gamma(
            "hill_K",
            alpha=K_alpha,
            beta=K_alpha / K_prior_mean,
            dims="channel",
        )
        hill_S = pm.Gamma(
            "hill_S",
            alpha=prior_config.get("S_alpha", 4.0),
            beta=prior_config.get("S_beta", 4.0),
            dims="channel",
        )

        sat_media = pm.Deterministic(
            "sat_media",
            _market_grouped_adstock_and_saturation(X_media, market_bounds, decay_rate, hill_K, hill_S),
            dims=("obs", "channel"),
        )

        # DNA halo pathway input: DNA-targeted channels enter as a *further*
        # lagged version of their saturated series (decision-time lag beyond
        # adstock carryover), reset at each market boundary.
        if dna_channel_idx:
            dna_sat = sat_media[:, dna_channel_idx]
            lagged_dna_sat = pm.Deterministic(
                "lagged_dna_sat",
                _market_grouped_lag(dna_sat, market_bounds, dna_lag_weeks),
            )
        else:
            lagged_dna_sat = None

        # -----------------------------------------------------------------
        # Segment-specific response multipliers via partial pooling.
        # log_beta[s, c] = mu_channel[c] + sigma_pool[c] * z[s, c]
        # sigma_pool[c] is the *learned* pooling strength: segments borrow
        # strength when it's small, diverge when the data supports it.
        # -----------------------------------------------------------------
        # Kept fairly tight by default: eta sums *all* channels' contributions
        # additively before the final exp(), so a wide per-channel prior
        # compounds across channels into an implausible tail very fast.
        mu_channel = pm.Normal(
            "mu_channel", mu=prior_config.get("channel_effect_mu", -2.5),
            sigma=prior_config.get("channel_effect_sigma", 0.5), dims="channel",
        )
        sigma_pool = pm.HalfNormal(
            "sigma_pool", sigma=prior_config.get("pooling_sigma_prior", 0.3), dims="channel",
        )
        z_offset = pm.Normal("z_offset", mu=0, sigma=1, dims=("segment", "channel"))
        log_beta = pm.Deterministic(
            "log_beta", mu_channel[None, :] + sigma_pool[None, :] * z_offset, dims=("segment", "channel")
        )
        beta = pm.Deterministic("beta", pt.exp(log_beta), dims=("segment", "channel"))

        # -----------------------------------------------------------------
        # DNA halo strength by segment: fixed at 1 (full weight) for the DNA
        # cross-sell segment itself; shrunk toward zero elsewhere and only
        # pulled away from zero where the data supports it ("smaller effect
        # elsewhere"). Reported as a first-class, inspectable parameter.
        # -----------------------------------------------------------------
        if dna_channel_idx:
            other_segments = [s for s in segments if s != dna_segment]
            halo_other = pm.HalfNormal(
                "halo_strength_other",
                sigma=prior_config.get("dna_halo_sigma", 0.25),
                shape=len(other_segments),
            )
            halo_pieces = []
            j = 0
            for s in segments:
                if s == dna_segment:
                    halo_pieces.append(pt.constant(1.0))
                else:
                    halo_pieces.append(halo_other[j])
                    j += 1
            halo_strength = pm.Deterministic("halo_strength", pt.stack(halo_pieces), dims="segment")

            eta_nondna = pm.math.dot(sat_media[:, non_dna_idx], beta[:, non_dna_idx].T) if non_dna_idx else pt.zeros((n_obs, n_segments))
            eta_dna = pm.math.dot(lagged_dna_sat, beta[:, dna_channel_idx].T) * halo_strength[None, :]
            eta_channels = eta_nondna + eta_dna
        else:
            eta_channels = pm.math.dot(sat_media, beta.T)

        # -----------------------------------------------------------------
        # Segment-specific promotional sensitivity (non-negative: promos lift).
        # -----------------------------------------------------------------
        promo_coef = pm.HalfNormal(
            "promo_coef", sigma=prior_config.get("promo_sigma", 0.5), dims="segment"
        )
        eta_promo = promo * promo_coef[None, :]

        # -----------------------------------------------------------------
        # Geo hierarchy: market-level baseline offsets, partially pooled by
        # default; markets in `unpooled_markets` get an effectively
        # independent (wide, unpooled) prior instead of sharing strength.
        # -----------------------------------------------------------------
        market_pool_sigma = pm.HalfNormal(
            "market_pool_sigma", sigma=prior_config.get("market_pool_sigma_prior", 0.4), dims="segment"
        )
        unpooled_sigma_const = prior_config.get("unpooled_market_sigma", 2.0)
        sigma_rows = []
        for m in markets:
            if m in unpooled_markets:
                sigma_rows.append(pt.as_tensor_variable(np.full(n_segments, unpooled_sigma_const)))
            else:
                sigma_rows.append(market_pool_sigma)
        market_sigma_stack = pt.stack(sigma_rows)  # (n_market, n_segment)

        market_offset_raw = pm.Normal("market_offset_raw", mu=0, sigma=1, dims=("market", "segment"))
        market_offset = pm.Deterministic(
            "market_offset", market_offset_raw * market_sigma_stack, dims=("market", "segment")
        )
        eta_market = market_offset[market_idx]

        # -----------------------------------------------------------------
        # Baseline, trend, seasonality (calendar-anchored Fourier).
        # -----------------------------------------------------------------
        intercept = pm.Normal(
            "intercept",
            mu=prior_config.get("intercept_mu", np.log(np.clip(Y.mean(axis=0), 1, None))),
            sigma=prior_config.get("intercept_sigma", 1.0),
            dims="segment",
        )
        trend_coef = pm.Normal("trend_coef", mu=0, sigma=prior_config.get("trend_sigma", 0.5), dims="segment")
        eta_trend = trend[:, None] * trend_coef[None, :]

        gamma_fourier = pm.Normal(
            "gamma_fourier", mu=0, sigma=prior_config.get("fourier_sigma", 0.4), dims=("fourier", "segment")
        )
        eta_season = pm.math.dot(fourier, gamma_fourier)

        eta = intercept[None, :] + eta_market + eta_trend + eta_season + eta_channels + eta_promo

        # -----------------------------------------------------------------
        # Segment-level (and, where mapped, cross-segment) controls, e.g.
        # DNA kit price acting only on the DNA cross-sell equation.
        # -----------------------------------------------------------------
        segment_controls = frame.get("segment_controls") or {}
        segment_control_names = frame.get("segment_control_names") or {}
        for seg, arr in segment_controls.items():
            if seg not in segments:
                continue
            s_idx = segments.index(seg)
            names = segment_control_names.get(seg, [f"ctrl_{i}" for i in range(arr.shape[1])])
            coord_name = f"{seg}_control"
            model.add_coord(coord_name, names)
            coef = pm.Normal(f"segment_control_coef_{seg}", mu=0, sigma=prior_config.get("control_sigma", 0.5), dims=coord_name)
            contrib = pm.math.dot(pt.as_tensor_variable(arr), coef)
            eta = pt.set_subtensor(eta[:, s_idx], eta[:, s_idx] + contrib)

        if n_controls > 0:
            model.add_coord("control", control_names)
            control_coef = pm.Normal(
                "control_coef", mu=0, sigma=prior_config.get("control_sigma", 0.5), dims="control"
            )
            eta = eta + pm.math.dot(pt.as_tensor_variable(X_controls), control_coef)[:, None]

        # Clip is a numerical safety net (not a modelling assumption): eta is
        # a sum of several additive terms before this exp(), so pathological
        # prior draws (e.g. during prior-predictive checks) can otherwise
        # overflow into values NegativeBinomial sampling can't handle.
        mu = pm.Deterministic("mu", pt.clip(pt.exp(eta), 1e-6, 1e9), dims=("obs", "segment"))

        alpha = pm.Gamma(
            "alpha", alpha=prior_config.get("alpha_shape", 2.0), beta=prior_config.get("alpha_rate", 0.1),
            dims="segment",
        )

        pm.NegativeBinomial("y_obs", mu=mu, alpha=alpha[None, :], observed=Y, dims=("obs", "segment"))

    meta = FHModelMeta(
        markets=markets,
        segments=segments,
        channels=channels,
        dna_channels=[channels[i] for i in dna_channel_idx],
        dna_channel_idx=dna_channel_idx,
        non_dna_idx=non_dna_idx,
        dna_segment=dna_segment,
        dna_lag_weeks=dna_lag_weeks,
        unpooled_markets=unpooled_markets,
        control_names=control_names,
        segment_control_names=frame.get("segment_control_names") or {},
    )
    return model, meta
