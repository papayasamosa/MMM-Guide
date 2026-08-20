"""Metric computation for the WP2 evidence package. All estimates are
reconstructed deterministically from the posterior trace (means, and
per-draw where an interval is needed) - never by re-running the model
and never by aggregating per-component values before the draw axis
exists."""

from __future__ import annotations

from typing import Dict, Optional

import arviz as az
import numpy as np

from .candidates import RETENTION, _SPLINE_BASIS
from .dgp import MAX_LAG, MAX_LEAD, REL_OFFSETS, Scenario


def _mean(idata: az.InferenceData, name: str) -> np.ndarray:
    return np.asarray(idata.posterior[name].mean(dim=("chain", "draw")).values)


def _event_weights(
    idata: az.InferenceData,
    candidate: str,
    offsets: np.ndarray = REL_OFFSETS,
) -> tuple[np.ndarray, np.ndarray]:
    """Posterior-mean event weights `(weights, weights_per_draw)`.
    `weights` is (K,); `weights_per_draw` is (n_draws, K). `offsets` must
    be the relative-week grid the candidate was actually fit on."""
    post = idata.posterior.stack(sample=("chain", "draw"))
    if candidate == "S1_fixed_profile":
        scale = float(idata.posterior["event_scale"].mean(dim=("chain", "draw")).values)
        scale_draws = np.asarray(post["event_scale"].values)
        reference = _fixed_reference_for(offsets)
        return scale * reference, scale_draws[:, None] * reference[None, :]
    if candidate == "S2_parametric":
        center = float(
            idata.posterior["event_center"].mean(dim=("chain", "draw")).values
        )
        width = float(idata.posterior["event_width"].mean(dim=("chain", "draw")).values)
        amplitude = float(
            idata.posterior["event_amplitude"].mean(dim=("chain", "draw")).values
        )
        weights = amplitude * np.exp(-0.5 * ((offsets - center) / width) ** 2)
        center_d = np.asarray(post["event_center"].values)
        width_d = np.asarray(post["event_width"].values)
        amplitude_d = np.asarray(post["event_amplitude"].values)
        weights_d = amplitude_d[:, None] * np.exp(
            -0.5 * ((offsets[None, :] - center_d[:, None]) / width_d[:, None]) ** 2
        )
        return weights, weights_d
    if candidate in ("S3_spline_basis", "S5_pooled_basis"):
        coefs = np.asarray(
            idata.posterior["event_coefs"].mean(dim=("chain", "draw")).values
        )
        weights = _SPLINE_BASIS @ coefs
        # xarray stacks coefficient dims before samples: (n_coef, n_draws).
        weights_d = (np.asarray(post["event_coefs"].values).T) @ _SPLINE_BASIS.T
        return weights, weights_d
    if candidate == "S4_dummies":
        coefs = np.asarray(
            idata.posterior["event_coefs"].mean(dim=("chain", "draw")).values
        )
        return coefs, np.asarray(post["event_coefs"].values).T
    raise ValueError(f"unknown candidate {candidate}")


def _reconstructed_seasonality(idata: az.InferenceData, n_weeks: int) -> np.ndarray:
    weeks = np.arange(n_weeks, dtype=float)
    coefs = _mean(idata, "fourier_coefs")
    w = 2.0 * np.pi * weeks / 52.0
    return (
        coefs[0] * np.cos(w)
        + coefs[1] * np.sin(w)
        + coefs[2] * np.cos(2 * w)
        + coefs[3] * np.sin(2 * w)
    )


def _reconstructed_media(idata: az.InferenceData, x_media: np.ndarray) -> np.ndarray:
    n_weeks, n_ch = x_media.shape
    idx = np.arange(n_weeks)
    dist = idx[:, None] - idx[None, :]
    adstock_op = np.where(dist >= 0, RETENTION**dist, 0.0)
    adstocked = adstock_op @ x_media
    alpha = _mean(idata, "media_alpha")
    lam = _mean(idata, "media_lam")
    beta = _mean(idata, "media_beta")
    saturated = np.column_stack(
        [
            np.maximum(adstocked[:, c], 0.0) ** alpha[c]
            / (np.maximum(adstocked[:, c], 0.0) ** alpha[c] + lam[c] ** alpha[c])
            for c in range(n_ch)
        ]
    )
    return saturated @ beta


def _fixed_reference_for(offsets: np.ndarray) -> np.ndarray:
    """The fixed S1 reference profile evaluated on `offsets` - the same
    generic normal shape centred at the event week, renormalised."""
    reference = np.exp(-0.5 * ((offsets - 0.0) / 1.0) ** 2)
    return reference / reference.sum()


def compute_single_market_metrics(
    scenario: Scenario,
    candidate: str,
    idata: az.InferenceData,
    runtime: float,
    event_design: np.ndarray | None = None,
    offsets: np.ndarray = REL_OFFSETS,
) -> Dict:
    """Metrics for one single-market fit. All values are floats, safe to
    JSON-serialise. `event_design` overrides the scenario's design for
    sensitivity fits with a different support window."""
    design = event_design if event_design is not None else scenario.event_design
    true = scenario.true
    event_window = np.zeros(scenario.y.shape[0], dtype=bool)
    for week in scenario.event_weeks:
        lo, hi = max(0, week - MAX_LEAD), min(scenario.y.shape[0], week + MAX_LAG + 1)
        event_window[lo:hi] = True

    weights, weights_d = _event_weights(idata, candidate, offsets=offsets)
    est_event = design @ weights
    true_event = true["event_contrib"]
    event_rmse = float(np.sqrt(np.mean((est_event - true_event) ** 2)))

    true_peak = float(np.max(np.abs(true_event)))
    est_peak = float(np.max(np.abs(est_event))) if np.any(est_event) else 0.0
    amplitude_ratio = est_peak / true_peak if true_peak > 0 else float("nan")

    draws_event = design @ weights_d.T  # (W, n_draws)
    draw_peaks = np.abs(draws_event).max(axis=0)
    lo, hi = np.percentile(draw_peaks, [5, 95])
    coverage_90 = float(lo <= true_peak <= hi)

    media_beta = _mean(idata, "media_beta")
    media_bias_mean = float(np.mean(np.abs(media_beta - true["media_beta"])))
    media_bias_max = float(np.max(np.abs(media_beta - true["media_beta"])))

    est_seasonality = _reconstructed_seasonality(idata, scenario.y.shape[0])
    seasonality_error = est_seasonality - true["seasonality"]
    seasonality_leakage = float(
        np.mean(np.abs(seasonality_error[event_window]))
        / max(np.mean(np.abs(seasonality_error[~event_window])), 1e-6)
    )

    promo_bias: Optional[float] = None
    if scenario.promo:
        promo_coef = float(_mean(idata, "promo_coef"))
        promo_bias = promo_coef - float(true["promo_coef"])

    r_hat_vals = np.asarray(az.rhat(idata).to_array().values)
    r_hat_max: Optional[float]
    if np.all(np.isnan(r_hat_vals)):
        # Single-chain (smoke) runs cannot compute R-hat - record it as
        # not computable rather than a fabricated number.
        r_hat_max = None
    else:
        r_hat_max = float(np.nanmax(r_hat_vals))
    divergences = int(idata.sample_stats["diverging"].sum().values)
    if r_hat_max is None:
        status = "ok" if divergences == 0 else "diagnostic_warning"
    else:
        status = (
            "ok" if (r_hat_max < 1.1 and divergences == 0) else "diagnostic_warning"
        )

    return {
        "status": status,
        "runtime_s": round(runtime, 2),
        "event_rmse": round(event_rmse, 4),
        "amplitude_ratio": round(amplitude_ratio, 4),
        "coverage_90": coverage_90,
        "media_bias_mean": round(media_bias_mean, 4),
        "media_bias_max": round(media_bias_max, 4),
        "seasonality_leakage_ratio": round(seasonality_leakage, 4),
        "promo_bias": round(promo_bias, 4) if promo_bias is not None else None,
        "r_hat_max": round(r_hat_max, 4) if r_hat_max is not None else None,
        "divergences": divergences,
    }


def compute_holdout_metrics(
    scenario: Scenario,
    candidate: str,
    idata: az.InferenceData,
    train_weeks: int,
) -> Dict:
    """Holdout metrics: the candidate is fit on the first `train_weeks`;
    the fitted event weights are then applied to the known future event
    occurrences in the held-out weeks and compared against the true
    event contribution there (future replay fidelity)."""
    weights, _ = _event_weights(idata, candidate)
    held = np.arange(train_weeks, scenario.y.shape[0])
    est_event = scenario.event_design[held] @ weights
    true_event = scenario.true["event_contrib"][held]
    event_rmse = float(np.sqrt(np.mean((est_event - true_event) ** 2)))

    true_peak = float(np.max(np.abs(true_event))) if np.any(true_event) else 0.0
    est_peak = float(np.max(np.abs(est_event))) if np.any(est_event) else 0.0
    amplitude_ratio = est_peak / true_peak if true_peak > 0 else float("nan")
    return {
        "holdout_event_rmse": round(event_rmse, 4),
        "holdout_amplitude_ratio": round(amplitude_ratio, 4),
    }


def compute_multi_market_metrics(
    scenario: Scenario, candidate: str, idata: az.InferenceData, runtime: float
) -> Dict:
    """Metrics for one multi-market fit: event RMSE/amplitude averaged
    over markets plus the maximum market-level media coefficient bias."""
    true_kernel = scenario.true["kernel"]
    true_event = scenario.amplitude * (scenario.event_design @ true_kernel)
    if candidate == "S5_pooled_basis":
        market_coefs = _mean(idata, "event_market_coefs")  # (M, 6)
        market_weights = np.asarray(market_coefs) @ _SPLINE_BASIS.T  # (M, K)
        est_event = scenario.event_design @ market_weights.T  # (W, M)
        market_rmse = np.sqrt(np.mean((est_event - true_event[:, None]) ** 2, axis=0))
        event_rmse = float(np.mean(market_rmse))
        est_peak = float(np.abs(est_event).max()) if np.any(est_event) else 0.0
    else:
        weights, _ = _event_weights(idata, candidate)
        est_event = scenario.event_design @ weights
        event_rmse = float(np.sqrt(np.mean((est_event - true_event) ** 2)))
        est_peak = float(np.max(np.abs(est_event))) if np.any(est_event) else 0.0
    true_peak = float(np.max(np.abs(true_event)))
    amplitude_ratio = est_peak / true_peak if true_peak > 0 else float("nan")

    beta = _mean(idata, "media_beta")
    beta_true = np.asarray(scenario.true["media_beta"])
    if scenario.structure == "shared":
        biases = [np.abs(beta - beta_true[0])]
    else:
        biases = [np.abs(beta[m] - beta_true[m]) for m in range(scenario.n_markets)]
    media_bias_max = float(max(b.mean() for b in biases))

    r_hat_vals = np.asarray(az.rhat(idata).to_array().values)
    r_hat_max: Optional[float]
    if np.all(np.isnan(r_hat_vals)):
        r_hat_max = None
    else:
        r_hat_max = float(np.nanmax(r_hat_vals))
    divergences = int(idata.sample_stats["diverging"].sum().values)
    if r_hat_max is None:
        status = "ok" if divergences == 0 else "diagnostic_warning"
    else:
        status = (
            "ok" if (r_hat_max < 1.1 and divergences == 0) else "diagnostic_warning"
        )
    return {
        "status": status,
        "runtime_s": round(runtime, 2),
        "event_rmse": round(event_rmse, 4),
        "amplitude_ratio": round(amplitude_ratio, 4),
        "media_bias_max": round(media_bias_max, 4),
        "r_hat_max": round(r_hat_max, 4) if r_hat_max is not None else None,
        "divergences": divergences,
    }


def failure_metrics(message: str, runtime: float) -> Dict:
    return {"status": "failed", "runtime_s": round(runtime, 2), "error": message[:300]}
