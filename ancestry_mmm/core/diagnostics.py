"""
Model scorecard: convergence + fit + out-of-sample accuracy + posterior
predictive coverage + curve plausibility, in one place rather than a single
headline R-squared.
"""

from __future__ import annotations

import warnings
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import arviz as az
import pymc as pm

from .models import compute_model_diagnostics
from .hierarchical_model import FHModelMeta
from .outcomes import outcome_catalogue_at_fit_by_id
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


def _mae(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - pred)))


def _rmse(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - pred) ** 2)))


def _smape(actual: np.ndarray, pred: np.ndarray) -> float:
    """Symmetric MAPE: |actual - pred| / ((|actual| + |pred|) / 2), as a
    percentage. Unlike MAPE, defined (and 0) when actual == pred == 0;
    excludes only points where actual and pred are *both* zero (a
    genuine 0/0 indeterminate form), never points where actual alone is
    zero - the specific blind spot MAPE has."""
    denom = (np.abs(actual) + np.abs(pred)) / 2
    mask = denom != 0
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs(actual[mask] - pred[mask]) / denom[mask]) * 100)


def _wape(actual: np.ndarray, pred: np.ndarray) -> float:
    """Weighted absolute percentage error: sum(|actual - pred|) / sum(|actual|),
    as a percentage - a single volume-weighted accuracy figure across all
    observations (unlike MAPE/sMAPE, which average a per-observation ratio
    and so overweight low-volume periods)."""
    denom = np.sum(np.abs(actual))
    if denom == 0:
        return float("nan")
    return float(np.sum(np.abs(actual - pred)) / denom * 100)


def _bias(actual: np.ndarray, pred: np.ndarray) -> float:
    """Mean signed error (pred - actual): positive means the model
    systematically over-predicts, negative means it systematically
    under-predicts. Unlike MAE/RMSE, signed errors are not folded to
    magnitude, so a well-calibrated model's bias should be close to zero
    even if its MAE is not."""
    return float(np.mean(pred - actual))


def error_metrics_by_outcome(
    frame: Dict, meta: FHModelMeta, params: FHPosteriorParams
) -> pd.DataFrame:
    """MAE, RMSE, sMAPE, WAPE and bias per outcome_id, comparing the
    posterior-mean prediction to actuals - the same (actual, predicted)
    pair `in_sample_fit` uses for R-squared/MAPE, as a distinct evidence
    category (a UK validation reviewer wants volume-weighted and
    symmetric error figures alongside R-squared/MAPE, not instead of
    them - see REQ-VAL-001)."""
    mu = predict_mu(frame, meta, params)
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


def residual_temporal_diagnostics(
    frame: Dict, meta: FHModelMeta, params: FHPosteriorParams
) -> pd.DataFrame:
    """Residual (actual - posterior-mean-prediction) temporal structure per
    market x outcome_id: lag-1 autocorrelation and the Durbin-Watson
    statistic.

    Computed separately within each market's own chronological row slice
    (`frame["market_bounds"]`, the same contiguous per-market row ranges
    `core.market_specific_diagnostics.curve_plausibility_checks_market_specific`
    already uses) - never across a market boundary. `frame`'s rows are
    sorted `[market, date]` by `data.preprocessor.prepare_fh_modeling_frame`,
    so each market's own slice is chronologically ordered, but the model
    frame is multi-market: concatenating every market's residuals into one
    vector before computing a lag-1 pair would form a synthetic adjacency
    between one market's last observation and a different market's first
    observation, which is not a valid time-series lag and corrupts the
    evidence (Work Package 2 corrective fix - the prior per-outcome-only
    version of this function did exactly that).

    Lag-1 autocorrelation near 0 indicates no obvious temporal
    autocorrelation left in the residuals; a value well above 0 indicates
    the model is leaving predictable temporal structure unexplained
    (under-fit carryover/trend/seasonality). Durbin-Watson is
    approximately `2 * (1 - lag1_autocorrelation)` - included alongside the
    raw coefficient since it is the more commonly cited statistic in
    econometric review, without duplicating the underlying computation.

    Deliberately reports the coefficient and statistic only - no
    blocking/pass-fail threshold is applied here (REQ-VAL-001: "evidence
    computation and approval policy are separate"; an approved policy
    decides thresholds later).
    """
    mu = predict_mu(frame, meta, params)
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


def _residual_autocorrelation_stats(residuals: np.ndarray) -> Tuple[float, float]:
    """Lag-1 autocorrelation coefficient and Durbin-Watson statistic for a
    single residual series, in chronological order. `nan` for either value
    when it is undefined (fewer than 2 residuals, or a constant - zero
    variance - lagged/current split for the autocorrelation coefficient, or
    all-zero residuals for Durbin-Watson)."""
    n = len(residuals)
    if n < 2:
        return float("nan"), float("nan")
    prev, curr = residuals[:-1], residuals[1:]
    prev_std, curr_std = prev.std(), curr.std()
    lag1_autocorr = (
        float("nan")
        if prev_std == 0 or curr_std == 0
        else float(np.corrcoef(prev, curr)[0, 1])
    )
    ss_res = np.sum(residuals**2)
    durbin_watson = (
        float(np.sum(np.diff(residuals) ** 2) / ss_res) if ss_res > 0 else float("nan")
    )
    return lag1_autocorr, durbin_watson


def prior_predictive_summary(
    model: pm.Model,
    frame: Dict[str, Any],
    meta: FHModelMeta,
    *,
    n_samples: int = 500,
    random_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Sample from `model`'s declared priors - never its posterior, never
    fitted (no MCMC, no trace involved) - via `pm.sample_prior_predictive`,
    and summarise the outcome-scale `y_obs` prior predictive distribution
    per market x outcome_id - the same grain `residual_temporal_diagnostics`/
    `error_metrics_by_outcome` use (`frame["market_bounds"]`, never
    aggregated across a market boundary).

    This function and `pm.sample_prior_predictive` itself never read the
    observed outcome data - sampling draws only from whatever priors
    `model` already declares. Those declared priors can themselves be
    empirically informed by the observed data at model-*build* time,
    though: both builders' default `intercept` prior centres its mean on
    `log(mean(Y))` unless `prior_config["intercept_mu"]` overrides it
    (`core.hierarchical_model.build_fh_hierarchical_model`/
    `core.market_specific_model.build_fh_market_specific_model`) - a
    deliberate, ordinary weakly-informative-prior choice, not something
    this function does. This evidence describes exactly what `model`'s
    priors (whatever informed them) imply on the outcome scale, not what a
    textbook fully-uninformative prior would imply.

    `model` must be an unfit `pm.Model` built by
    `core.hierarchical_model.build_fh_hierarchical_model` or
    `core.market_specific_model.build_fh_market_specific_model` (or a
    structurally identical model exposing an `("obs", "outcome")`-shaped
    `y_obs` observed variable) - both builders produce an identical `y_obs`
    shape, so this one function serves Model A and Model C alike; only
    `hill_K`/`beta`'s internal parameterisation differs between them, and
    neither is read here.

    Purely descriptive - no pass/fail threshold, no prior is read, changed,
    or refit (REQ-VAL-001: evidence computation and approval policy are
    separate; sampling from a model's own declared priors cannot alter
    them). Raises whatever `pm.sample_prior_predictive` raises on failure -
    the caller (`application.diagnostics_service.DiagnosticsService.
    run_prior_predictive_check`) is responsible for turning that into an
    explicit `failed` `DiagnosticSection` rather than fabricating zero
    evidence.
    """
    markets: List[str] = frame["markets"]
    market_bounds: List[tuple] = frame["market_bounds"]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with model:
            # var_names=["y_obs"]: only this section's own read target is
            # materialised - every other free variable/Deterministic this
            # model declares (e.g. the (obs, outcome)-shaped `mu`, the same
            # size as `y_obs` itself) would otherwise be sampled and
            # retained for no reason, needlessly scaling peak memory with a
            # large multi-market/multi-year model's parameter count.
            idata = pm.sample_prior_predictive(
                draws=n_samples, random_seed=random_seed, var_names=["y_obs"]
            )
        captured_warnings = [str(w.message) for w in caught]

    # (chain, draw, obs, outcome) -> (chain * draw, obs, outcome); prior
    # predictive sampling is always a single "chain" of independent draws,
    # but indexing defensively by shape rather than assuming chain == 1.
    y_obs = idata.prior_predictive["y_obs"].values
    n_chain, n_draw, n_obs, n_outcome = y_obs.shape
    flat = y_obs.reshape(n_chain * n_draw, n_obs, n_outcome)

    # pages/AGENTS.md "Required labels": outcome evidence must carry its
    # definition version, not only the bare outcome_id, so persisted
    # evidence stays unambiguously tied to the governed outcome definition
    # as definitions evolve (Codex review, PR #148).
    outcome_definitions_at_fit = outcome_catalogue_at_fit_by_id(meta)

    rows: List[Dict[str, Any]] = []
    for m_i, market in enumerate(markets):
        start, end = market_bounds[m_i]
        for o_i, oid in enumerate(meta.outcome_ids):
            cell = flat[:, start:end, o_i].reshape(-1)
            finite = cell[np.isfinite(cell)]
            has_finite = finite.size > 0
            outcome_definition = outcome_definitions_at_fit.get(oid)
            rows.append(
                {
                    "market": market,
                    "outcome_id": oid,
                    "outcome_definition_version": (
                        outcome_definition.definition_version
                        if outcome_definition is not None
                        else ""
                    ),
                    "n_observations": end - start,
                    "n_draws": int(cell.size),
                    "finite_count": int(finite.size),
                    "non_finite_count": int(cell.size - finite.size),
                    "mean": float(np.mean(finite)) if has_finite else float("nan"),
                    "median": float(np.median(finite)) if has_finite else float("nan"),
                    "q05": float(np.quantile(finite, 0.05))
                    if has_finite
                    else float("nan"),
                    "q95": float(np.quantile(finite, 0.95))
                    if has_finite
                    else float("nan"),
                    "min": float(np.min(finite)) if has_finite else float("nan"),
                    "max": float(np.max(finite)) if has_finite else float("nan"),
                }
            )

    return {
        "n_samples": n_samples,
        "random_seed": random_seed,
        "rows": rows,
        "warnings": captured_warnings,
    }


def predictive_density_summary(
    model: pm.Model,
    trace: az.InferenceData,
    frame: Dict[str, Any],
    meta: FHModelMeta,
) -> Dict[str, Any]:
    """PSIS-LOO and WAIC predictive-density evidence (REQ-VAL-001 Work
    Package 3), computed post-hoc against an already-fitted `trace` - no
    refit. `pm.compute_log_likelihood` requires only the unfit `model` (for
    the likelihood graph) and the existing posterior draws; feasibility was
    verified directly against PyMC 5.28.5/ArviZ 0.23.4 (not assumed):
    `y_obs`'s log-likelihood has dims `("chain", "draw", "obs", "outcome")`,
    and `az.loo`/`az.waic` with `pointwise=True` return `loo_i`/`waic_i`/
    `pareto_k` with dims `("obs", "outcome")` - pointwise identity is fully
    preserved, so it is regrouped to market x outcome_id below the same way
    `prior_predictive_summary` does (`frame["market_bounds"]`).

    `model` must be an unfit `pm.Model` built by the same builder/frame/spec
    (or an exact governed rebuild of it) as the fit `trace` came from - the
    same "which model specification" identity contract
    `prior_predictive_summary` requires. `trace` is never mutated: a copy is
    extended with the `log_likelihood` group internally
    (`pm.compute_log_likelihood(idata, extend_inferencedata=False)` returns
    a bare `xarray.Dataset`, not a usable `InferenceData` - `az.loo`/
    `az.waic` require the full `InferenceData` shape, so a defensive
    `trace.copy()` plus the default `extend_inferencedata=True` is used
    instead, verified directly rather than assumed).

    PSIS-LOO's leave-one-out approximation is a well-documented general
    property, not unique to this implementation: it assumes each held-out
    observation is exchangeable with the rest, which is a weaker
    approximation for temporally-structured data (this model's adstock
    carryover/trend/seasonality) than for genuinely independent
    observations. The Pareto-k diagnostic this function reports is exactly
    ArviZ's own mechanism for flagging individual observations where that
    approximation is unreliable - reported here as evidence, never
    silently hidden or used to assert LOO is unconditionally valid.

    Purely descriptive - no pass/fail threshold. The Pareto-k good/bad/
    very-bad counts below are bucketed against ArviZ's own returned,
    sample-size-adjusted `good_k` threshold (`loo_result.good_k` - "For a
    sample size S, the threshold is computed as min(1 - 1/log10(S), 0.7)",
    per ArviZ's own docstring) rather than a hardcoded 0.5, so a row's
    bucket counts can never contradict `loo_good_k_threshold` reported
    alongside them (Codex review, PR #148: a fixed 0.5 cutoff would
    misclassify a k above 0.5 as "bad" even when ArviZ's own adjusted
    threshold for this sample size says it is still good). >1.0 ("very
    bad") is ArviZ's own fixed upper bucket, not sample-size-adjusted.
    """
    markets: List[str] = frame["markets"]
    market_bounds: List[tuple] = frame["market_bounds"]

    idata_with_ll = trace.copy()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with model:
            pm.compute_log_likelihood(
                idata_with_ll, var_names=["y_obs"], model=model, progressbar=False
            )
        loo_result = az.loo(idata_with_ll, pointwise=True, var_name="y_obs")
        waic_result = az.waic(idata_with_ll, pointwise=True, var_name="y_obs")
        captured_warnings = [str(w.message) for w in caught]

    pareto_k = loo_result.pareto_k.values
    loo_i = loo_result.loo_i.values
    waic_i = waic_result.waic_i.values
    good_k_threshold = float(loo_result.good_k)

    # pages/AGENTS.md "Required labels": see prior_predictive_summary's
    # matching comment above.
    outcome_definitions_at_fit = outcome_catalogue_at_fit_by_id(meta)

    rows: List[Dict[str, Any]] = []
    for m_i, market in enumerate(markets):
        start, end = market_bounds[m_i]
        for o_i, oid in enumerate(meta.outcome_ids):
            k_slice = pareto_k[start:end, o_i]
            outcome_definition = outcome_definitions_at_fit.get(oid)
            rows.append(
                {
                    "market": market,
                    "outcome_id": oid,
                    "outcome_definition_version": (
                        outcome_definition.definition_version
                        if outcome_definition is not None
                        else ""
                    ),
                    "n_observations": end - start,
                    "mean_pareto_k": float(np.mean(k_slice)),
                    "max_pareto_k": float(np.max(k_slice)),
                    "n_good_pareto_k": int(np.sum(k_slice <= good_k_threshold)),
                    "n_bad_pareto_k": int(
                        np.sum((k_slice > good_k_threshold) & (k_slice <= 1.0))
                    ),
                    "n_very_bad_pareto_k": int(np.sum(k_slice > 1.0)),
                    "mean_elpd_loo_i": float(np.mean(loo_i[start:end, o_i])),
                    "mean_elpd_waic_i": float(np.mean(waic_i[start:end, o_i])),
                }
            )

    return {
        "elpd_loo": float(loo_result.elpd_loo),
        "elpd_loo_se": float(loo_result.se),
        "p_loo": float(loo_result.p_loo),
        "loo_good_k_threshold": good_k_threshold,
        "elpd_waic": float(waic_result.elpd_waic),
        "elpd_waic_se": float(waic_result.se),
        "p_waic": float(waic_result.p_waic),
        "n_data_points": int(loo_result.n_data_points),
        "rows": rows,
        "warnings": captured_warnings,
    }


def in_sample_fit(
    frame: Dict, meta: FHModelMeta, params: FHPosteriorParams
) -> pd.DataFrame:
    """R-squared and MAPE per outcome_id, comparing posterior-mean prediction to actuals."""
    mu = predict_mu(frame, meta, params)
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


def posterior_predictive_coverage(
    trace: az.InferenceData,
    frame: Dict,
    meta: FHModelMeta,
    credible_mass: float = 0.9,
    *,
    predictive_replications: int = 1,
    random_seed: Optional[int] = None,
) -> pd.DataFrame:
    """
    % of actual observations falling inside the posterior predictive credible
    interval, per outcome_id.

    Correctly computes the posterior predictive interval by:
    1. Drawing ``predictive_replications`` Negative Binomial samples from
       *each* posterior draw's ``(mu, alpha)`` parameter pair.
    2. Pooling all predictive samples across draws.
    3. Taking empirical quantiles of the pooled mixture.

    This replaces the previous (incorrect) average-of-conditional-quantiles
    approach. The average of conditional quantiles is **not** the quantile of
    the posterior predictive mixture; the reported interval was therefore not
    a correct Bayesian posterior predictive interval.

    Parameters
    ----------
    trace : az.InferenceData
        Fitted posterior with ``mu`` (obs, outcome, chain, draw) and
        ``alpha`` (outcome, chain, draw).
    frame : dict
        Must contain ``Y`` with shape ``(n_obs, n_outcomes)``.
    meta : FHModelMeta
        Model metadata providing ``outcome_ids``.
    credible_mass : float, default 0.9
        Width of the credible interval, e.g. 0.9 = 90% interval.
    predictive_replications : int, default 1
        Number of predictive samples to draw *per posterior draw*. The total
        predictive sample size is ``n_chains * n_draws * predictive_replications``.
        A value of 1 (the default) is adequate when the posterior has many
        draws; increase for more precise interval estimates.
    random_seed : int or None, default None
        Seed for reproducible predictive sampling.

    Returns
    -------
    pd.DataFrame
        Columns: ``outcome_id``, ``credible_mass``, ``coverage_pct``,
        ``target_pct``, ``n_predictive_samples``.
    """
    Y = frame["Y"]
    n_obs, n_outcomes = Y.shape

    # Stack posterior draws into a single sample dimension
    mu_draws = (
        trace.posterior["mu"].stack(sample=("chain", "draw")).values
    )  # (obs, outcome, sample)
    alpha_draws = (
        trace.posterior["alpha"].stack(sample=("chain", "draw")).values
    )  # (outcome, sample)
    n_samples = mu_draws.shape[2]

    rng = np.random.default_rng(random_seed)
    lower_q, upper_q = (1 - credible_mass) / 2, 1 - (1 - credible_mass) / 2
    rows = []

    for i, oid in enumerate(meta.outcome_ids):
        mu_i = mu_draws[:, i, :]  # (obs, sample)
        alpha_i = alpha_draws[i, :]  # (sample,)

        # NegativeBinomial parameterisation: n = alpha, p = alpha / (alpha + mu)
        n_param = alpha_i[None, :]  # (1, sample) broadcast over obs
        p_param = alpha_i[None, :] / (alpha_i[None, :] + mu_i)  # (obs, sample)
        p_param = np.clip(p_param, 1e-9, 1 - 1e-9)

        # Generate posterior predictive samples
        # Shape after loop: (obs, sample * predictive_replications)
        pred_samples = np.concatenate(
            [
                rng.negative_binomial(n_param, p_param, size=(n_obs, n_samples))
                for _ in range(predictive_replications)
            ],
            axis=1,
        )

        # Empirical quantiles across the pooled predictive mixture
        lo = np.quantile(pred_samples, lower_q, axis=1)
        hi = np.quantile(pred_samples, upper_q, axis=1)

        covered = (Y[:, i] >= lo) & (Y[:, i] <= hi)
        rows.append(
            {
                "outcome_id": oid,
                "credible_mass": credible_mass,
                "coverage_pct": float(covered.mean() * 100),
                "target_pct": credible_mass * 100,
                "n_predictive_samples": int(n_samples * predictive_replications),
            }
        )

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
            issues.append(
                {
                    "level": "warning",
                    "channel": ch,
                    "message": f"Half-saturation point for '{ch}' (K={k_val:,.0f}) is far above the "
                    f"highest observed spend ({spend_max:,.0f}) - the saturation curve is "
                    "essentially unidentified in the observed spend range; treat as ~linear.",
                }
            )
        if spend_nonzero_min and k_val < spend_nonzero_min / 3:
            issues.append(
                {
                    "level": "warning",
                    "channel": ch,
                    "message": f"Half-saturation point for '{ch}' (K={k_val:,.0f}) is far below the "
                    f"lowest observed non-zero spend ({spend_nonzero_min:,.0f}) - the channel "
                    "looks fully saturated across the whole observed range.",
                }
            )

        for oid in meta.outcome_ids:
            b_mean = float(beta_mean.sel(outcome=oid, channel=ch).values)
            b_std = float(beta_std.sel(outcome=oid, channel=ch).values)
            if b_mean > 0 and b_std / b_mean > 1.0:
                issues.append(
                    {
                        "level": "warning",
                        "channel": ch,
                        "message": f"'{ch}' effect on outcome '{oid}' has high relative uncertainty "
                        f"(std/mean = {b_std / b_mean:.1f}) - treat the point estimate cautiously.",
                    }
                )

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
    slope = (S * (mean_spend ** (S - 1)) * (K**S)) / ((K**S + mean_spend**S) ** 2)
    beta_sum = float(
        trace.posterior["beta"]
        .sel(channel=ch)
        .mean()
        .sum(dim=["chain", "draw", "outcome"])
        .values
    )
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
    fit_fold_fn: Callable[
        [pd.DataFrame, pd.DataFrame], Tuple[Dict[str, float], Dict[str, float]]
    ],
    n_folds: int = 3,
    min_train_frac: float = 0.6,
) -> pd.DataFrame:
    """
    Out-of-sample / rolling forecast accuracy: expanding-window backtest.

    For each fold, trains on all rows up to a cutoff and evaluates on the
    next held-out block. `fit_fold_fn(train_df, test_df) -> (r_squared_by_outcome_id,
    mape_by_outcome_id)` is supplied by the caller (a page-level wrapper that
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
        for oid in r2_by_seg:
            rows.append(
                {
                    "fold": fold_i + 1,
                    "train_end": cutoff_date,
                    "test_end": test_end_date,
                    "outcome_id": oid,
                    "r_squared": r2_by_seg[oid],
                    "mape_pct": mape_by_seg[oid],
                }
            )
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
        "ppc_coverage": posterior_predictive_coverage(trace, frame, meta).to_dict(
            orient="records"
        ),
        "plausibility_flags": curve_plausibility_checks(trace, meta, frame, roi_bounds),
    }
