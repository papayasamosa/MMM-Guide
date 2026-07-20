"""
Model scorecard: convergence + fit + out-of-sample accuracy + posterior
predictive coverage + curve plausibility, in one place rather than a single
headline R-squared.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import arviz as az
from scipy import stats

from .models import compute_model_diagnostics
from .hierarchical_model import FHModelMeta
from .predict import FHPosteriorParams, extract_posterior_params, predict_mu


def _r_squared(actual: np.ndarray, pred: np.ndarray) -> float:
    ss_res = np.sum((actual - pred) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")


def _mape(actual: np.ndarray, pred: np.ndarray) -> float:
    mask = actual != 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)


def in_sample_fit(frame: Dict, meta: FHModelMeta, params: FHPosteriorParams) -> pd.DataFrame:
    """R-squared and MAPE per segment, comparing posterior-mean prediction to actuals."""
    mu = predict_mu(frame, meta, params)
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


def posterior_predictive_coverage(
    trace: az.InferenceData,
    frame: Dict,
    meta: FHModelMeta,
    credible_mass: float = 0.9,
) -> pd.DataFrame:
    """
    % of actual observations falling inside the posterior predictive credible
    interval, per segment - computed analytically from the NegativeBinomial
    quantile function using posterior mu/alpha draws (no extra sampling pass).
    """
    Y = frame["Y"]
    mu_draws = trace.posterior["mu"].stack(sample=("chain", "draw")).values  # (obs, segment, sample)
    alpha_draws = trace.posterior["alpha"].stack(sample=("chain", "draw")).values  # (segment, sample)

    lower_q, upper_q = (1 - credible_mass) / 2, 1 - (1 - credible_mass) / 2
    rows = []
    for i, seg in enumerate(meta.segments):
        mu_i = mu_draws[:, i, :]        # (obs, sample)
        alpha_i = alpha_draws[i, :]     # (sample,)
        n_param = alpha_i[None, :]
        p_param = alpha_i[None, :] / (alpha_i[None, :] + mu_i)
        p_param = np.clip(p_param, 1e-9, 1 - 1e-9)

        lo = stats.nbinom.ppf(lower_q, n_param, p_param)
        hi = stats.nbinom.ppf(upper_q, n_param, p_param)
        lo_mean, hi_mean = lo.mean(axis=1), hi.mean(axis=1)

        covered = (Y[:, i] >= lo_mean) & (Y[:, i] <= hi_mean)
        rows.append({
            "segment": seg,
            "credible_mass": credible_mass,
            "coverage_pct": float(covered.mean() * 100),
            "target_pct": credible_mass * 100,
        })
    return pd.DataFrame(rows)


def curve_plausibility_checks(
    trace: az.InferenceData,
    meta: FHModelMeta,
    frame: Dict,
    roi_bounds: Optional[Dict[str, Tuple[float, float]]] = None,
) -> List[Dict[str, str]]:
    """
    Flag channel effects that look implausible relative to the data or (if
    provided) business-expected ROI bounds. `roi_bounds` maps channel name
    to an acceptable (min, max) ROI range set by whoever knows the business.
    """
    roi_bounds = roi_bounds or {}
    issues: List[Dict[str, str]] = []

    K_mean = trace.posterior["hill_K"].mean(dim=["chain", "draw"])
    beta_mean = trace.posterior["beta"].mean(dim=["chain", "draw"])
    beta_std = trace.posterior["beta"].std(dim=["chain", "draw"])

    for ci, ch in enumerate(meta.channels):
        spend = frame["X_media"][:, ci]
        spend_max = spend.max()
        spend_nonzero_min = spend[spend > 0].min() if (spend > 0).any() else 0
        k_val = float(K_mean.sel(channel=ch).values)

        if spend_max > 0 and k_val > spend_max * 3:
            issues.append({
                "level": "warning",
                "channel": ch,
                "message": f"Half-saturation point for '{ch}' (K={k_val:,.0f}) is far above the "
                           f"highest observed spend ({spend_max:,.0f}) - the saturation curve is "
                           "essentially unidentified in the observed spend range; treat as ~linear.",
            })
        if spend_nonzero_min and k_val < spend_nonzero_min / 3:
            issues.append({
                "level": "warning",
                "channel": ch,
                "message": f"Half-saturation point for '{ch}' (K={k_val:,.0f}) is far below the "
                           f"lowest observed non-zero spend ({spend_nonzero_min:,.0f}) - the channel "
                           "looks fully saturated across the whole observed range.",
            })

        for seg in meta.segments:
            b_mean = float(beta_mean.sel(segment=seg, channel=ch).values)
            b_std = float(beta_std.sel(segment=seg, channel=ch).values)
            if b_mean > 0 and b_std / b_mean > 1.0:
                issues.append({
                    "level": "warning",
                    "channel": ch,
                    "message": f"'{ch}' effect on segment '{seg}' has high relative uncertainty "
                               f"(std/mean = {b_std / b_mean:.1f}) - treat the point estimate cautiously.",
                })

        if ch in roi_bounds:
            lo, hi = roi_bounds[ch]
            # Rough current-spend ROI proxy: dlog(mu)/dspend * mu / spend at the mean spend level,
            # using the shared beta/K/S curve slope - a plausibility signal, not a precise marginal ROI.
            issues_roi = _roi_plausibility_flag(ch, ci, lo, hi, trace, meta, frame)
            if issues_roi:
                issues.append(issues_roi)

    return issues


def _roi_plausibility_flag(ch, ci, lo, hi, trace, meta, frame):
    K = float(trace.posterior["hill_K"].sel(channel=ch).mean().values)
    S = float(trace.posterior["hill_S"].sel(channel=ch).mean().values)
    spend = frame["X_media"][:, ci]
    mean_spend = spend[spend > 0].mean() if (spend > 0).any() else 1.0
    slope = (S * (mean_spend ** (S - 1)) * (K ** S)) / ((K ** S + mean_spend ** S) ** 2)
    beta_sum = float(trace.posterior["beta"].sel(channel=ch).mean().sum(dim=["chain", "draw", "segment"]).values)
    approx_roi = slope * beta_sum
    if not (lo <= approx_roi <= hi):
        return {
            "level": "warning",
            "channel": ch,
            "message": f"Approximate marginal ROI for '{ch}' ({approx_roi:.2f}) falls outside the "
                       f"business-expected range [{lo}, {hi}] - worth a sense-check against known "
                       "channel economics.",
        }
    return None


def expanding_window_backtest(
    df: pd.DataFrame,
    spec,
    fit_fold_fn: Callable[[pd.DataFrame, pd.DataFrame], Tuple[Dict[str, float], Dict[str, float]]],
    n_folds: int = 3,
    min_train_frac: float = 0.6,
) -> pd.DataFrame:
    """
    Out-of-sample / rolling forecast accuracy: expanding-window backtest.

    For each fold, trains on all rows up to a cutoff and evaluates on the
    next held-out block. `fit_fold_fn(train_df, test_df) -> (r_squared_by_segment,
    mape_by_segment)` is supplied by the caller (a page-level wrapper that
    fits the model on train_df and predicts test_df) - kept generic here so
    this module has no dependency on how long a real fit takes; n_folds=1
    gives a single holdout split, which is the cheapest useful check.

    Note: each fold refits the full model, so this is only as fast as
    `fit_fold_fn` - for interactive use, keep n_folds small and/or use a
    reduced draws/tune budget inside fit_fold_fn.
    """
    dates = pd.to_datetime(df[spec.date_col])
    unique_dates = np.sort(dates.unique())
    n = len(unique_dates)
    start_idx = int(n * min_train_frac)
    if start_idx >= n:
        raise ValueError("min_train_frac leaves no data for a held-out block.")

    fold_edges = np.linspace(start_idx, n - 1, n_folds + 1, dtype=int)[1:]
    rows = []
    prev_edge = start_idx
    for fold_i, edge in enumerate(fold_edges):
        if edge <= prev_edge:
            continue
        cutoff_date = unique_dates[prev_edge]
        test_end_date = unique_dates[edge]
        train_df = df[dates <= cutoff_date]
        test_df = df[(dates > cutoff_date) & (dates <= test_end_date)]
        if test_df.empty:
            continue

        r2_by_seg, mape_by_seg = fit_fold_fn(train_df, test_df)
        for seg in r2_by_seg:
            rows.append({
                "fold": fold_i + 1,
                "train_end": cutoff_date,
                "test_end": test_end_date,
                "segment": seg,
                "r_squared": r2_by_seg[seg],
                "mape_pct": mape_by_seg[seg],
            })
        prev_edge = edge

    return pd.DataFrame(rows)


def compute_scorecard(
    trace: az.InferenceData,
    frame: Dict,
    meta: FHModelMeta,
    roi_bounds: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    """Assemble the full scorecard: convergence + in-sample fit + PPC coverage + plausibility flags."""
    params = extract_posterior_params(trace, meta)
    return {
        "convergence": compute_model_diagnostics(trace),
        "in_sample_fit": in_sample_fit(frame, meta, params).to_dict(orient="records"),
        "ppc_coverage": posterior_predictive_coverage(trace, frame, meta).to_dict(orient="records"),
        "plausibility_flags": curve_plausibility_checks(trace, meta, frame, roi_bounds),
    }
