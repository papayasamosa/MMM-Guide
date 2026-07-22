"""
Market-specific, partially-pooled joint hierarchical FH MMM ("Model C" in
docs/model_validation.md) - Phase 2 of the market-specific redesign
(docs/decision_log.md).

Structurally identical to core.hierarchical_model.build_fh_hierarchical_model
(same likelihood, DNA halo pathway, promo/control/trend/seasonality terms,
market baseline pooling) except for two parameters, per the design record in
docs/market_hierarchy.md section 3 and docs/modelling_methodology.md:

- `hill_K[market, channel]` - the saturation point is now market-specific,
  drawn around a shared global mean on the log scale:
  `log_K[market, channel] ~ Normal(global_log_K[channel], market_K_sigma[channel])`.
- `beta[market, segment, channel]` - response strength is now market- *and*
  segment-specific, built as the simplest identifiable additive form the
  redesign brief recommends (global channel effect + market deviation +
  segment deviation, no free market x segment interaction term):
  `log_beta[market, segment, channel]
      = mu_channel[channel] + market_dev[market, channel] + segment_dev[segment, channel]`.

`decay_rate[channel]` and `hill_S[channel]` deliberately stay shared across
markets - decision_log.md entry 3 - this is the "initial production version"
the redesign brief itself recommends; per-market decay/shape is a documented
future extension, not part of this phase.

core.hierarchical_model.build_fh_hierarchical_model (the shared-curve model,
"Model A") is untouched by this module - both remain fully available side by
side for the model comparison workflow (docs/model_validation.md).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pymc as pm
import pytensor.tensor as pt

from .hierarchical_model import FHModelMeta, _default_dna_outcome_id, _market_grouped_lag, _resolve_direct_dna_outcome_ids
from .outcomes import outcome_eligibility
from .schema import ModelSpec
from .transformations import pt_geometric_adstock_matrix, pt_hill_function


def _market_specific_adstock_and_saturation(
    X_media: np.ndarray,
    market_bounds: List[tuple],
    decay_rate: pt.TensorVariable,
    hill_K: pt.TensorVariable,
    hill_S: pt.TensorVariable,
) -> pt.TensorVariable:
    """
    Per-market adstock + Hill saturation, matching
    hierarchical_model._market_grouped_adstock_and_saturation exactly except
    that `hill_K` here is a (n_market, n_channel) tensor - each market block
    is saturated against its own row of K, while decay and S (both
    (n_channel,)) stay shared across every block.
    """
    blocks = []
    for m_i, (start, end) in enumerate(market_bounds):
        X_slice = pt.as_tensor_variable(X_media[start:end])
        adstocked = pt_geometric_adstock_matrix(X_slice, decay_rate, normalize=True)
        saturated = pt_hill_function(adstocked, hill_K[m_i], hill_S)
        blocks.append(saturated)
    return pt.concatenate(blocks, axis=0)


def build_fh_market_specific_model(
    frame: Dict[str, Any],
    spec: ModelSpec,
    dna_lag_weeks: int = 4,
    dna_outcome_id: Optional[str] = None,
    prior_config: Optional[Dict] = None,
    direct_dna_outcome_ids: Optional[List[str]] = None,
) -> "tuple[pm.Model, FHModelMeta]":
    """
    Build the market-specific, partially-pooled joint hierarchical FH model
    ("Model C"). Same signature, same `frame`/`spec` inputs, and the same
    `FHModelMeta` return type as
    `core.hierarchical_model.build_fh_hierarchical_model` - nothing about the
    model's *structural* metadata (which channels are DNA channels, the halo
    lag, market/outcome_id/channel lists) differs between Model A and Model
    C; only the shape of `hill_K` and `beta` in the fitted trace does, which
    is why posterior extraction and curve replay need their own
    market-specific-aware code (core.market_specific_predict), not this
    module. `direct_dna_outcome_ids` has the same meaning as Model A's - see
    that function's docstring.

    Requires at least 2 markets - partial pooling across a single market is
    meaningless (there is nothing to pool with).
    """
    prior_config = prior_config or {}

    markets: List[str] = frame["markets"]
    market_idx: np.ndarray = frame["market_idx"]
    market_bounds: List[tuple] = frame["market_bounds"]
    channels: List[str] = frame["channels"]
    dna_channel_idx: List[int] = frame["dna_channel_idx"]
    outcome_ids: List[str] = frame["outcome_ids"]
    X_media: np.ndarray = frame["X_media"]
    Y: np.ndarray = frame["Y"]
    promo: np.ndarray = frame["promo"]
    X_controls: np.ndarray = frame["X_controls"]
    control_names: List[str] = frame["control_names"]
    fourier: np.ndarray = frame["fourier"]
    trend: np.ndarray = frame["trend"]
    unpooled_markets: List[str] = frame.get("unpooled_markets") or []

    n_obs, n_channels = X_media.shape
    n_markets = len(markets)
    n_outcomes = len(outcome_ids)
    n_fourier = fourier.shape[1]
    n_controls = X_controls.shape[1]

    if n_markets < 2:
        raise ValueError(
            f"Market-specific partial pooling needs at least 2 markets, got {n_markets}. "
            "Use core.hierarchical_model.build_fh_hierarchical_model (Model A) for a single market."
        )

    dna_outcome_id = _default_dna_outcome_id(outcome_ids, dna_outcome_id, dna_channel_idx)
    direct_dna_outcome_ids = _resolve_direct_dna_outcome_ids(outcome_ids, dna_outcome_id, direct_dna_outcome_ids)
    non_dna_idx = [i for i, c in enumerate(channels) if i not in dna_channel_idx]

    channel_mean_spend = X_media.mean(axis=0)
    channel_mean_spend = np.where(channel_mean_spend > 0, channel_mean_spend, 1.0)

    with pm.Model() as model:
        model.add_coord("obs", np.arange(n_obs))
        model.add_coord("market", markets)
        model.add_coord("outcome", outcome_ids)
        model.add_coord("channel", channels)
        model.add_coord("fourier", np.arange(n_fourier))

        # -----------------------------------------------------------------
        # Adstock decay: shared across markets (decision_log.md entry 3).
        # -----------------------------------------------------------------
        decay_rate = pm.Beta(
            "decay_rate",
            mu=prior_config.get("decay_mu", 0.5),
            sigma=prior_config.get("decay_sigma", 0.2),
            dims="channel",
        )

        # -----------------------------------------------------------------
        # Saturation point: market-specific, partially pooled on the log
        # scale around a shared global mean per channel -
        # docs/market_hierarchy.md section 3:
        #   log_K[market, channel] ~ Normal(global_log_K[channel], market_K_sigma[channel])
        # Parameterised as global_hill_K * exp(market deviation) rather than
        # a raw Normal on log(K) directly, so the *global* component keeps
        # the same Gamma-on-spend-scale prior as Model A (comparable priors
        # across model types, easier model comparison) while the market
        # deviation is exactly the log-Normal the brief specifies.
        # -----------------------------------------------------------------
        K_prior_mean = channel_mean_spend * prior_config.get("K_scale", 1.0)
        K_alpha = prior_config.get("K_alpha", 3.0)
        global_hill_K = pm.Gamma(
            "global_hill_K",
            alpha=K_alpha,
            beta=K_alpha / K_prior_mean,
            dims="channel",
        )
        market_K_sigma = pm.HalfNormal(
            "market_K_sigma", sigma=prior_config.get("market_K_sigma_prior", 0.3), dims="channel",
        )
        z_market_K = pm.Normal("z_market_K", mu=0, sigma=1, dims=("market", "channel"))
        log_K_market_dev = pm.Deterministic(
            "log_K_market_dev", market_K_sigma[None, :] * z_market_K, dims=("market", "channel")
        )
        hill_K = pm.Deterministic(
            "hill_K", global_hill_K[None, :] * pt.exp(log_K_market_dev), dims=("market", "channel")
        )

        # Hill shape: shared across markets (decision_log.md entry 3).
        hill_S = pm.Gamma(
            "hill_S",
            alpha=prior_config.get("S_alpha", 4.0),
            beta=prior_config.get("S_beta", 4.0),
            dims="channel",
        )

        sat_media = pm.Deterministic(
            "sat_media",
            _market_specific_adstock_and_saturation(X_media, market_bounds, decay_rate, hill_K, hill_S),
            dims=("obs", "channel"),
        )

        # Two genuinely separate DNA-media inputs - identical to Model A
        # (hierarchical_model.py's matching comment,
        # docs/dna_fh_causal_structure.md): `dna_direct_media` is the
        # (market-specific) saturated DNA-channel series itself, no extra
        # lag; `dna_halo_media` is that series with a further lag applied.
        if dna_channel_idx:
            dna_direct_media = sat_media[:, dna_channel_idx]
            dna_halo_media = pm.Deterministic(
                "dna_halo_media",
                _market_grouped_lag(dna_direct_media, market_bounds, dna_lag_weeks),
            )
        else:
            dna_direct_media = None
            dna_halo_media = None

        # -----------------------------------------------------------------
        # Response strength: market- *and* segment-specific, additive on
        # the log scale - docs/market_hierarchy.md section 2.1 /
        # docs/modelling_methodology.md "simplest identifiable form":
        #   log_beta[market, segment, channel]
        #       = mu_channel[channel] + market_dev[market, channel] + segment_dev[segment, channel]
        # No free market x segment x channel interaction term - the brief is
        # explicit that this isn't added unless diagnostics show the data
        # supports it.
        # -----------------------------------------------------------------
        mu_channel = pm.Normal(
            "mu_channel", mu=prior_config.get("channel_effect_mu", -2.5),
            sigma=prior_config.get("channel_effect_sigma", 0.5), dims="channel",
        )

        market_beta_sigma = pm.HalfNormal(
            "market_beta_sigma", sigma=prior_config.get("market_beta_sigma_prior", 0.3), dims="channel",
        )
        z_market_beta = pm.Normal("z_market_beta", mu=0, sigma=1, dims=("market", "channel"))
        market_beta_dev = pm.Deterministic(
            "market_beta_dev", market_beta_sigma[None, :] * z_market_beta, dims=("market", "channel")
        )

        sigma_pool = pm.HalfNormal(
            "sigma_pool", sigma=prior_config.get("pooling_sigma_prior", 0.3), dims="channel",
        )
        z_offset = pm.Normal("z_offset", mu=0, sigma=1, dims=("outcome", "channel"))
        outcome_beta_dev = pm.Deterministic(
            "outcome_beta_dev", sigma_pool[None, :] * z_offset, dims=("outcome", "channel")
        )

        log_beta = pm.Deterministic(
            "log_beta",
            mu_channel[None, None, :] + market_beta_dev[:, None, :] + outcome_beta_dev[None, :, :],
            dims=("market", "outcome", "channel"),
        )
        beta = pm.Deterministic("beta", pt.exp(log_beta), dims=("market", "outcome", "channel"))
        beta_by_market_idx = beta[market_idx]  # (obs, outcome, channel) - this row's own market's beta

        # -----------------------------------------------------------------
        # Direct vs. halo pathway coefficients, by outcome_id - identical
        # structure to Model A (halo_strength itself not market-specific in
        # this phase; a documented future extension, same as decay/S) - see
        # hierarchical_model.py's matching comment and
        # docs/dna_fh_causal_structure.md for the full rationale.
        # `kit_only_outcome_ids` (DNA-product kit-sale outcomes) get only
        # the direct term; `dna_outcome_id` (FH DNA-cross-sell) gets both,
        # with a regularised, shrunk-toward-zero halo term; every other
        # outcome_id gets only the halo term, unchanged from before this
        # split.
        # -----------------------------------------------------------------
        if dna_channel_idx:
            kit_only_outcome_ids = [s for s in direct_dna_outcome_ids if s != dna_outcome_id]
            halo_eligible_outcome_ids = [s for s in outcome_ids if s not in kit_only_outcome_ids]
            halo_strength_est = pm.HalfNormal(
                "halo_strength_est",
                sigma=prior_config.get("dna_halo_sigma", 0.25),
                shape=len(halo_eligible_outcome_ids),
            )
            halo_pieces = []
            j = 0
            for s in outcome_ids:
                if s in kit_only_outcome_ids:
                    halo_pieces.append(pt.constant(0.0))
                else:
                    halo_pieces.append(halo_strength_est[j])
                    j += 1
            halo_strength = pm.Deterministic("halo_strength", pt.stack(halo_pieces), dims="outcome")

            has_direct = pt.constant(np.array([1.0 if s in direct_dna_outcome_ids else 0.0 for s in outcome_ids]))

            non_dna_beta = beta_by_market_idx[:, :, non_dna_idx] if non_dna_idx else None
            dna_beta = beta_by_market_idx[:, :, dna_channel_idx]

            eta_nondna = (
                pt.sum(sat_media[:, None, non_dna_idx] * non_dna_beta, axis=2)
                if non_dna_idx else pt.zeros((n_obs, n_outcomes))
            )
            eta_dna_direct = pt.sum(dna_direct_media[:, None, :] * dna_beta, axis=2) * has_direct[None, :]
            eta_dna_halo = pt.sum(dna_halo_media[:, None, :] * dna_beta, axis=2) * halo_strength[None, :]
            eta_channels = eta_nondna + eta_dna_direct + eta_dna_halo
        else:
            eta_channels = pt.sum(sat_media[:, None, :] * beta_by_market_idx, axis=2)

        # -----------------------------------------------------------------
        # Everything below is identical to Model A: promo sensitivity,
        # market baseline pooling, trend, seasonality, controls, likelihood.
        # -----------------------------------------------------------------
        promo_coef = pm.HalfNormal(
            "promo_coef", sigma=prior_config.get("promo_sigma", 0.5), dims="outcome"
        )
        eta_promo = promo * promo_coef[None, :]

        market_pool_sigma = pm.HalfNormal(
            "market_pool_sigma", sigma=prior_config.get("market_pool_sigma_prior", 0.4), dims="outcome"
        )
        unpooled_sigma_const = prior_config.get("unpooled_market_sigma", 2.0)
        sigma_rows = []
        for m in markets:
            if m in unpooled_markets:
                sigma_rows.append(pt.as_tensor_variable(np.full(n_outcomes, unpooled_sigma_const)))
            else:
                sigma_rows.append(market_pool_sigma)
        market_sigma_stack = pt.stack(sigma_rows)

        market_offset_raw = pm.Normal("market_offset_raw", mu=0, sigma=1, dims=("market", "outcome"))
        market_offset = pm.Deterministic(
            "market_offset", market_offset_raw * market_sigma_stack, dims=("market", "outcome")
        )
        eta_market = market_offset[market_idx]

        intercept = pm.Normal(
            "intercept",
            mu=prior_config.get("intercept_mu", np.log(np.clip(Y.mean(axis=0), 1, None))),
            sigma=prior_config.get("intercept_sigma", 1.0),
            dims="outcome",
        )
        trend_coef = pm.Normal("trend_coef", mu=0, sigma=prior_config.get("trend_sigma", 0.5), dims="outcome")
        eta_trend = trend[:, None] * trend_coef[None, :]

        gamma_fourier = pm.Normal(
            "gamma_fourier", mu=0, sigma=prior_config.get("fourier_sigma", 0.4), dims=("fourier", "outcome")
        )
        eta_season = pm.math.dot(fourier, gamma_fourier)

        eta = intercept[None, :] + eta_market + eta_trend + eta_season + eta_channels + eta_promo

        outcome_controls = frame.get("outcome_controls") or {}
        outcome_control_names = frame.get("outcome_control_names") or {}
        for oid, arr in outcome_controls.items():
            if oid not in outcome_ids:
                continue
            o_idx = outcome_ids.index(oid)
            names = outcome_control_names.get(oid, [f"ctrl_{i}" for i in range(arr.shape[1])])
            coord_name = f"{oid}_control"
            model.add_coord(coord_name, names)
            coef = pm.Normal(f"outcome_control_coef_{oid}", mu=0, sigma=prior_config.get("control_sigma", 0.5), dims=coord_name)
            contrib = pm.math.dot(pt.as_tensor_variable(arr), coef)
            eta = pt.set_subtensor(eta[:, o_idx], eta[:, o_idx] + contrib)

        if n_controls > 0:
            model.add_coord("control", control_names)
            control_coef = pm.Normal(
                "control_coef", mu=0, sigma=prior_config.get("control_sigma", 0.5), dims="control"
            )
            eta = eta + pm.math.dot(pt.as_tensor_variable(X_controls), control_coef)[:, None]

        mu = pm.Deterministic("mu", pt.clip(pt.exp(eta), 1e-6, 1e9), dims=("obs", "outcome"))

        alpha = pm.Gamma(
            "alpha", alpha=prior_config.get("alpha_shape", 2.0), beta=prior_config.get("alpha_rate", 0.1),
            dims="outcome",
        )

        pm.NegativeBinomial("y_obs", mu=mu, alpha=alpha[None, :], observed=Y, dims=("obs", "outcome"))

    outcome_catalogue: List[Any] = frame.get("outcomes") or []
    meta = FHModelMeta(
        markets=markets,
        outcome_ids=outcome_ids,
        channels=channels,
        dna_channels=[channels[i] for i in dna_channel_idx],
        dna_channel_idx=dna_channel_idx,
        non_dna_idx=non_dna_idx,
        dna_outcome_id=dna_outcome_id,
        dna_lag_weeks=dna_lag_weeks,
        unpooled_markets=unpooled_markets,
        control_names=control_names,
        outcome_id_to_segment={o.outcome_id: o.segment for o in outcome_catalogue},
        outcome_id_to_product={o.outcome_id: o.product for o in outcome_catalogue},
        outcome_id_to_metric={o.outcome_id: o.metric for o in outcome_catalogue},
        outcome_id_to_metric_key={o.outcome_id: o.metric_key for o in outcome_catalogue},
        outcome_id_to_unit={o.outcome_id: o.unit for o in outcome_catalogue},
        outcome_id_to_role={o.outcome_id: o.role for o in outcome_catalogue},
        outcome_id_to_eligibility={o.outcome_id: outcome_eligibility(o) for o in outcome_catalogue},
        outcome_id_to_source_column={o.outcome_id: o.source_column for o in outcome_catalogue},
        outcome_catalogue_at_fit=outcome_catalogue,
        outcome_control_names=frame.get("outcome_control_names") or {},
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        pathway_catalogue_at_fit=frame.get("media_outcome_pathways") or [],
    )
    return model, meta
