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

from typing import Any, Dict, List, Optional, Tuple

import arviz as az
import pandas as pd

from .diagnostics import _mape, _r_squared, posterior_predictive_coverage
from .hierarchical_model import FHModelMeta
from .market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    extract_market_specific_posterior_params,
    predict_mu_market_specific,
)
from .models import compute_model_diagnostics


def in_sample_fit_market_specific(
    frame: Dict, meta: FHModelMeta, params: FHMarketSpecificPosteriorParams,
) -> pd.DataFrame:
    """R-squared and MAPE per segment - Model C equivalent of core.diagnostics.in_sample_fit."""
    mu = predict_mu_market_specific(frame, meta, params)
    Y = frame["Y"]
    rows = []
    for i, seg in enumerate(meta.segments):
        rows.append({
            "segment": seg,
            "r_squared": _r_squared(Y[:, i], mu[:, i]),
            "mape_pct": _mape(Y[:, i], mu[:, i]),
            "actual_mean": float(Y[:, i].mean()),
            "predicted_mean": float(mu[:, i].mean()),
        })
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

    K_mean = trace.posterior["hill_K"].mean(dim=["chain", "draw"])   # (market, channel)
    beta_mean = trace.posterior["beta"].mean(dim=["chain", "draw"])  # (market, segment, channel)
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
                issues.append({
                    "level": "warning",
                    "channel": ch,
                    "message": f"[{market}] Half-saturation point for '{ch}' (K={k_val:,.0f}) is far "
                               f"above the highest observed spend in this market ({spend_max:,.0f}) - "
                               "the saturation curve is essentially unidentified in the observed spend "
                               "range for this market; treat as ~linear.",
                })
            if spend_nonzero_min and k_val < spend_nonzero_min / 3:
                issues.append({
                    "level": "warning",
                    "channel": ch,
                    "message": f"[{market}] Half-saturation point for '{ch}' (K={k_val:,.0f}) is far "
                               f"below the lowest observed non-zero spend in this market "
                               f"({spend_nonzero_min:,.0f}) - the channel looks fully saturated across "
                               "this market's whole observed range.",
                })

            for seg in meta.segments:
                b_mean = float(beta_mean.sel(market=market, segment=seg, channel=ch).values)
                b_std = float(beta_std.sel(market=market, segment=seg, channel=ch).values)
                if b_mean > 0 and b_std / b_mean > 1.0:
                    issues.append({
                        "level": "warning",
                        "channel": ch,
                        "message": f"[{market}] '{ch}' effect on segment '{seg}' has high relative "
                                   f"uncertainty (std/mean = {b_std / b_mean:.1f}) - treat the point "
                                   "estimate cautiously; this market may have insufficient local "
                                   "evidence (see docs/market_hierarchy.md section 4).",
                    })

            if ch in roi_bounds:
                lo, hi = roi_bounds[ch]
                S = float(trace.posterior["hill_S"].sel(channel=ch).mean().values)
                mean_spend = spend[spend > 0].mean() if (spend > 0).any() else 1.0
                slope = (S * (mean_spend ** (S - 1)) * (k_val ** S)) / ((k_val ** S + mean_spend ** S) ** 2)
                beta_sum = float(
                    trace.posterior["beta"].sel(market=market, channel=ch)
                    .mean(dim=["chain", "draw", "segment"]).values
                )
                approx_roi = slope * beta_sum
                if not (lo <= approx_roi <= hi):
                    issues.append({
                        "level": "warning",
                        "channel": ch,
                        "message": f"[{market}] Approximate marginal ROI for '{ch}' ({approx_roi:.2f}) "
                                   f"falls outside the business-expected range [{lo}, {hi}] - worth a "
                                   "sense-check against known channel economics for this market.",
                    })

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
        "in_sample_fit": in_sample_fit_market_specific(frame, meta, params).to_dict(orient="records"),
        "ppc_coverage": posterior_predictive_coverage(trace, frame, meta).to_dict(orient="records"),
        "plausibility_flags": curve_plausibility_checks_market_specific(trace, meta, frame, roi_bounds),
    }
