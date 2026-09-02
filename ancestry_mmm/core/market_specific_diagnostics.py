"""
Scorecard for the market-specific hierarchical model ("Model C" -
core.market_specific_model), mirroring core.diagnostics but using
market-indexed `hill_K`/`beta`. `compute_model_diagnostics` (convergence,
generic arviz stats) and `posterior_predictive_coverage` (reads `mu`/`alpha`,
whose shapes don't depend on whether K/beta are market-specific) are
reused unchanged from core.diagnostics; only the pieces that read
`hill_K`/`beta` directly need a market-specific-aware version.
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional, Tuple

import arviz as az
import numpy as np
import pandas as pd

from .diagnostics import (
    _bias,
    _mae,
    _mape,
    _posterior_predictive_metric_distributions_core,
    _r_squared,
    _residual_autocorrelation_stats,
    _rmse,
    _smape,
    _wape,
    posterior_predictive_coverage,
)
from .hierarchical_model import FHModelMeta
from .named_event_fit_inputs import NamedEventFitInputs
from .market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    extract_market_specific_posterior_params,
    predict_mu_market_specific,
)
from .models import compute_model_diagnostics


def in_sample_fit_market_specific(
    frame: Dict,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    *,
    named_event_fit_inputs: Optional[NamedEventFitInputs] = None,
) -> pd.DataFrame:
    """R-squared and MAPE per outcome_id - Model C equivalent of core.diagnostics.in_sample_fit."""
    mu = predict_mu_market_specific(
        frame, meta, params, named_event_fit_inputs=named_event_fit_inputs
    )
    Y = frame["Y"]
    rows = []
    for i, oid in enumerate(meta.outcome_ids):
        rows.append(
            {
                "outcome_id": oid,
                "r_squared": _r_squared(Y[:, i], mu[:, i]),
                "mape_pct": _mape(Y[:, i], mu[:, i]),
                "actual_mean": float(Y[:, i].mean()),
                "predicted_mean": float(mu[:, i].mean()),
            }
        )
    return pd.DataFrame(rows)


def error_metrics_by_outcome_market_specific(
    frame: Dict,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    *,
    named_event_fit_inputs: Optional[NamedEventFitInputs] = None,
) -> pd.DataFrame:
    """MAE/RMSE/sMAPE/WAPE/bias per outcome_id - Model C equivalent of
    core.diagnostics.error_metrics_by_outcome."""
    mu = predict_mu_market_specific(
        frame, meta, params, named_event_fit_inputs=named_event_fit_inputs
    )
    Y = frame["Y"]
    rows = []
    for i, oid in enumerate(meta.outcome_ids):
        actual, pred = Y[:, i], mu[:, i]
        rows.append(
            {
                "outcome_id": oid,
                "mae": _mae(actual, pred),
                "rmse": _rmse(actual, pred),
                "smape_pct": _smape(actual, pred),
                "wape_pct": _wape(actual, pred),
                "bias": _bias(actual, pred),
            }
        )
    return pd.DataFrame(rows)


def posterior_predictive_metric_distributions_market_specific(
    trace: az.InferenceData,
    frame: Dict,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    *,
    credible_mass: float = 0.9,
    named_event_fit_inputs: Optional[NamedEventFitInputs] = None,
) -> pd.DataFrame:
    """REQ-PPD-001 (Model C / market-specific model) - Model C equivalent
    of `core.diagnostics.posterior_predictive_metric_distributions`. The
    draw-level computation is shared with Model A via `_posterior_
    predictive_metric_distributions_core` (`trace.posterior["mu"]`'s shape
    does not depend on whether `hill_K`/`beta` are market-specific); only
    the point-metric column, reused unchanged from `error_metrics_by_
    outcome_market_specific`, differs."""
    point_metrics = error_metrics_by_outcome_market_specific(
        frame, meta, params, named_event_fit_inputs=named_event_fit_inputs
    )
    return _posterior_predictive_metric_distributions_core(
        trace, frame, meta, point_metrics, credible_mass=credible_mass
    )


def residual_temporal_diagnostics_market_specific(
    frame: Dict,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    *,
    named_event_fit_inputs: Optional[NamedEventFitInputs] = None,
) -> pd.DataFrame:
    """Lag-1 autocorrelation/Durbin-Watson per market x outcome_id - Model C
    equivalent of core.diagnostics.residual_temporal_diagnostics. Computed
    within each market's own `frame["market_bounds"]` slice, never across a
    market boundary - the same market-safety fix, and the same
    `frame["markets"]`/`frame["market_bounds"]` convention
    `curve_plausibility_checks_market_specific` above already uses for its
    own per-market slicing. Market-specific curve parameters (hill_K/beta)
    already vary by market; residual temporal evidence must be market-safe
    for exactly the same reason."""
    mu = predict_mu_market_specific(
        frame, meta, params, named_event_fit_inputs=named_event_fit_inputs
    )
    Y = frame["Y"]
    markets = frame["markets"]
    market_bounds = frame["market_bounds"]
    rows = []
    for m_i, market in enumerate(markets):
        start, end = market_bounds[m_i]
        for i, oid in enumerate(meta.outcome_ids):
            residuals = Y[start:end, i] - mu[start:end, i]
            lag1_autocorr, durbin_watson = _residual_autocorrelation_stats(residuals)
            rows.append(
                {
                    "market": market,
                    "outcome_id": oid,
                    "n_observations": len(residuals),
                    "lag1_autocorrelation": lag1_autocorr,
                    "durbin_watson": durbin_watson,
                }
            )
    return pd.DataFrame(rows)


def residual_series_market_specific(
    frame: Dict,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    trace: Optional[az.InferenceData] = None,
    credible_mass: float = 0.9,
    *,
    named_event_fit_inputs: Optional[NamedEventFitInputs] = None,
) -> pd.DataFrame:
    """Model C equivalent of `core.diagnostics.residual_series` - identical
    per-`market x date x outcome_id` row shape and column names (same
    `residual = actual - predicted` convention, same `expected_mean_*`
    interval labelling), only using `predict_mu_market_specific` since
    Model C's `hill_K`/`beta` are market-indexed."""
    mu = predict_mu_market_specific(
        frame, meta, params, named_event_fit_inputs=named_event_fit_inputs
    )
    Y = frame["Y"]
    markets = frame["markets"]
    market_bounds = frame["market_bounds"]
    dates = frame.get("dates")
    outcome_ids = list(meta.outcome_ids)

    mu_lower = mu_upper = None
    if trace is not None and "mu" in getattr(trace, "posterior", {}):
        lower_q, upper_q = (1 - credible_mass) / 2, 1 - (1 - credible_mass) / 2
        mu_posterior = trace.posterior["mu"]
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            mu_lower = mu_posterior.quantile(lower_q, dim=("chain", "draw")).values
            mu_upper = mu_posterior.quantile(upper_q, dim=("chain", "draw")).values

    rows: List[Dict[str, Any]] = []
    for m_i, market in enumerate(markets):
        start, end = market_bounds[m_i]
        for i, oid in enumerate(outcome_ids):
            actual = np.asarray(Y[start:end, i], dtype=float)
            predicted = np.asarray(mu[start:end, i], dtype=float)
            residual = actual - predicted
            abs_residual = np.abs(residual)
            residual_rank_pct = pd.Series(residual).rank(pct=True).to_numpy()
            abs_residual_rank_pct = pd.Series(abs_residual).rank(pct=True).to_numpy()
            for j in range(end - start):
                row: Dict[str, Any] = {
                    "market": market,
                    "date": dates[start + j] if dates is not None else start + j,
                    "outcome_id": oid,
                    "actual": float(actual[j]),
                    "predicted": float(predicted[j]),
                    "residual": float(residual[j]),
                    "abs_residual": float(abs_residual[j]),
                    "residual_rank_pct": float(residual_rank_pct[j]),
                    "abs_residual_rank_pct": float(abs_residual_rank_pct[j]),
                }
                if mu_lower is not None and mu_upper is not None:
                    row["expected_mean_lower"] = float(mu_lower[start + j, i])
                    row["expected_mean_upper"] = float(mu_upper[start + j, i])
                    row["expected_mean_credible_mass"] = credible_mass
                rows.append(row)
    return pd.DataFrame(rows)


def curve_plausibility_checks_market_specific(
    trace: az.InferenceData,
    meta: FHModelMeta,
    frame: Dict,
    roi_bounds: Optional[Dict[str, Tuple[float, float]]] = None,
) -> List[Dict[str, str]]:
    """Model C equivalent of core.diagnostics.curve_plausibility_checks - the
    same checks, run once per (market, channel) since K is now market-specific,
    against that market's own slice of observed spend."""
    roi_bounds = roi_bounds or {}
    issues: List[Dict[str, str]] = []

    K_mean = trace.posterior["hill_K"].mean(dim=["chain", "draw"])  # (market, channel)
    beta_mean = trace.posterior["beta"].mean(
        dim=["chain", "draw"]
    )  # (market, outcome, channel)
    beta_std = trace.posterior["beta"].std(dim=["chain", "draw"])

    markets = frame["markets"]
    for m_i, market in enumerate(markets):
        start, end = frame["market_bounds"][m_i]
        for ci, ch in enumerate(meta.channels):
            spend = frame["X_media"][start:end, ci]
            spend_max = spend.max() if len(spend) else 0.0
            spend_nonzero_min = spend[spend > 0].min() if (spend > 0).any() else 0
            k_val = float(K_mean.sel(market=market, channel=ch).values)

            if spend_max > 0 and k_val > spend_max * 3:
                issues.append(
                    {
                        "level": "warning",
                        "channel": ch,
                        "message": f"[{market}] Half-saturation point for '{ch}' (K={k_val:,.0f}) is far "
                        f"above the highest observed spend in this market ({spend_max:,.0f}) - "
                        "the saturation curve is essentially unidentified in the observed spend "
                        "range for this market; treat as ~linear.",
                    }
                )
            if spend_nonzero_min and k_val < spend_nonzero_min / 3:
                issues.append(
                    {
                        "level": "warning",
                        "channel": ch,
                        "message": f"[{market}] Half-saturation point for '{ch}' (K={k_val:,.0f}) is far "
                        f"below the lowest observed non-zero spend in this market "
                        f"({spend_nonzero_min:,.0f}) - the channel looks fully saturated across "
                        "this market's whole observed range.",
                    }
                )

            for oid in meta.outcome_ids:
                b_mean = float(
                    beta_mean.sel(market=market, outcome=oid, channel=ch).values
                )
                b_std = float(
                    beta_std.sel(market=market, outcome=oid, channel=ch).values
                )
                if b_mean > 0 and b_std / b_mean > 1.0:
                    issues.append(
                        {
                            "level": "warning",
                            "channel": ch,
                            "message": f"[{market}] '{ch}' effect on outcome '{oid}' has high relative "
                            f"uncertainty (std/mean = {b_std / b_mean:.1f}) - treat the point "
                            "estimate cautiously; this market may have insufficient local "
                            "evidence (see docs/market_hierarchy.md section 4).",
                        }
                    )

            if ch in roi_bounds:
                lo, hi = roi_bounds[ch]
                S = float(trace.posterior["hill_S"].sel(channel=ch).mean().values)
                mean_spend = spend[spend > 0].mean() if (spend > 0).any() else 1.0
                slope = (S * (mean_spend ** (S - 1)) * (k_val**S)) / (
                    (k_val**S + mean_spend**S) ** 2
                )
                beta_sum = float(
                    trace.posterior["beta"]
                    .sel(market=market, channel=ch)
                    .mean(dim=["chain", "draw", "outcome"])
                    .values
                )
                approx_roi = slope * beta_sum
                if not (lo <= approx_roi <= hi):
                    issues.append(
                        {
                            "level": "warning",
                            "channel": ch,
                            "message": f"[{market}] Approximate marginal ROI for '{ch}' ({approx_roi:.2f}) "
                            f"falls outside the business-expected range [{lo}, {hi}] - worth a "
                            "sense-check against known channel economics for this market.",
                        }
                    )

    return issues


def compute_scorecard_market_specific(
    trace: az.InferenceData,
    frame: Dict,
    meta: FHModelMeta,
    roi_bounds: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    """Model C equivalent of core.diagnostics.compute_scorecard: convergence
    + in-sample fit + PPC coverage + plausibility flags, all market-aware
    where the underlying parameter is market-specific."""
    params = extract_market_specific_posterior_params(trace, meta)
    return {
        "convergence": compute_model_diagnostics(trace),
        "in_sample_fit": in_sample_fit_market_specific(frame, meta, params).to_dict(
            orient="records"
        ),
        "ppc_coverage": posterior_predictive_coverage(trace, frame, meta).to_dict(
            orient="records"
        ),
        "plausibility_flags": curve_plausibility_checks_market_specific(
            trace, meta, frame, roi_bounds
        ),
    }
