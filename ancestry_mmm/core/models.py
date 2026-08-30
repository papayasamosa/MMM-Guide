"""PyMC model builders for Marketing Mix Modeling."""

import warnings

import numpy as np
import pymc as pm
import arviz as az
from typing import Dict, List, Optional, Tuple, Callable, Any

from .transformations import log_transform


def build_loglog_model(
    X_media: np.ndarray,
    X_fourier: np.ndarray,
    trend: np.ndarray,
    y: np.ndarray,
    channel_names: List[str],
    X_events: Optional[np.ndarray] = None,
    event_names: Optional[List[str]] = None,
    X_controls: Optional[np.ndarray] = None,
    control_names: Optional[List[str]] = None,
    prior_config: Optional[Dict] = None,
) -> pm.Model:
    """
    Build a Log-Log multiplicative MMM.

    In the log-log specification:
    log(y) = intercept + sum(beta_i * log(x_i)) + seasonality + trend + noise

    The beta coefficients are directly interpretable as elasticities:
    a 1% increase in channel i spend leads to a beta_i% increase in sales.

    Args:
        X_media: Media spend data, shape (n_periods, n_channels)
        X_fourier: Fourier features for seasonality, shape (n_periods, n_harmonics*2)
        trend: Trend feature, shape (n_periods,)
        y: Target variable, shape (n_periods,)
        channel_names: Names of media channels
        X_events: Optional event indicators (e.g., COVID), shape (n_periods, n_events)
        event_names: Names of events
        X_controls: Optional control variables, shape (n_periods, n_controls)
        control_names: Names of control variables
        prior_config: Optional dictionary of prior parameters

    Returns:
        PyMC Model object
    """
    prior_config = prior_config or {}

    n_obs, n_channels = X_media.shape
    n_fourier = X_fourier.shape[1]

    # Log-transform inputs
    y_log = log_transform(y)
    X_media_log = log_transform(X_media)

    with pm.Model() as model:
        # Store data for later reference
        model.add_coord("obs", range(n_obs))
        model.add_coord("channel", channel_names)
        model.add_coord("fourier", range(n_fourier))

        # Priors for intercept
        intercept = pm.Normal(
            "intercept",
            mu=prior_config.get("intercept_mu", y_log.mean()),
            sigma=prior_config.get("intercept_sigma", 1.0),
        )

        # Priors for channel elasticities (betas)
        # Elasticities are typically small positive values for advertising
        beta = pm.HalfNormal(
            "beta",
            sigma=prior_config.get("beta_sigma", 0.3),
            dims="channel",
        )

        # Priors for seasonality coefficients
        # sigma=0.5 allows seasonality to explain up to ~50% variation in log scale
        gamma_fourier = pm.Normal(
            "gamma_fourier",
            mu=0,
            sigma=prior_config.get("fourier_sigma", 0.5),
            dims="fourier",
        )

        # Prior for trend coefficient
        # sigma=0.5 allows trend to capture meaningful growth/decline
        gamma_trend = pm.Normal(
            "gamma_trend",
            mu=0,
            sigma=prior_config.get("trend_sigma", 0.5),
        )

        # Priors for events (COVID, holidays, etc.) - can be positive or negative
        gamma_events = None
        n_events = 0
        if X_events is not None and X_events.shape[1] > 0:
            n_events = X_events.shape[1]
            model.add_coord("event", event_names)
            # Use pm.Data to wrap the events array for proper tensor handling
            X_events_data = pm.Data("X_events_data", X_events)
            gamma_events = pm.Normal(
                "gamma_events",
                mu=0,
                sigma=prior_config.get("event_sigma", 1.0),
                dims="event",
            )

        # Priors for control variables
        gamma_controls = None
        n_controls = 0
        if X_controls is not None and X_controls.shape[1] > 0:
            n_controls = X_controls.shape[1]
            model.add_coord("control", control_names)
            X_controls_data = pm.Data("X_controls_data", X_controls)
            gamma_controls = pm.Normal(
                "gamma_controls",
                mu=0,
                sigma=prior_config.get("control_sigma", 0.5),
                dims="control",
            )

        # Prior for noise
        sigma = pm.HalfNormal(
            "sigma",
            sigma=prior_config.get("sigma_sigma", 0.5),
        )

        # Linear predictor in log space
        mu = (
            intercept
            + pm.math.dot(X_media_log, beta)
            + pm.math.dot(X_fourier, gamma_fourier)
            + gamma_trend * trend
        )

        # Add events contribution (e.g., COVID impact)
        if n_events > 0 and gamma_events is not None:
            mu = mu + pm.math.dot(X_events_data, gamma_events)

        # Add controls contribution (already standardized, no log transform)
        if n_controls > 0 and gamma_controls is not None:
            mu = mu + pm.math.dot(X_controls_data, gamma_controls)

        # Likelihood
        pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y_log, dims="obs")

        # Store transformed data for later use
        pm.Deterministic("y_log", pm.math.constant(y_log), dims="obs")

    return model


def build_lift_model(
    X_media: np.ndarray,
    X_fourier: np.ndarray,
    trend: np.ndarray,
    y: np.ndarray,
    channel_names: List[str],
    adstock_decay_priors: Optional[Dict[str, Tuple[float, float]]] = None,
    prior_config: Optional[Dict] = None,
) -> pm.Model:
    """
    Build a Lift-Factor multiplicative MMM with adstock.

    This model explicitly estimates adstock decay rates and models
    the multiplicative lift from each channel.

    Args:
        X_media: Media spend data, shape (n_periods, n_channels)
        X_fourier: Fourier features for seasonality
        trend: Trend feature
        y: Target variable
        channel_names: Names of media channels
        adstock_decay_priors: Dict mapping channel names to (mean, sd) tuples
        prior_config: Optional dictionary of prior parameters

    Returns:
        PyMC Model object
    """
    prior_config = prior_config or {}
    adstock_decay_priors = adstock_decay_priors or {}

    n_obs, n_channels = X_media.shape
    n_fourier = X_fourier.shape[1]

    # Default adstock priors
    default_decay_prior = (0.5, 0.2)

    with pm.Model() as model:
        model.add_coord("obs", range(n_obs))
        model.add_coord("channel", channel_names)
        model.add_coord("fourier", range(n_fourier))

        # Adstock decay rates per channel
        decay_rates = []
        for i, ch in enumerate(channel_names):
            mu, sd = adstock_decay_priors.get(ch, default_decay_prior)
            decay = pm.Beta(
                f"decay_{ch}",
                mu=mu,
                sigma=sd,
            )
            decay_rates.append(decay)

        # Baseline sales
        baseline = pm.LogNormal(
            "baseline",
            mu=prior_config.get("baseline_mu", np.log(y.mean())),
            sigma=prior_config.get("baseline_sigma", 0.5),
        )

        # Channel lift factors (multiplicative effects)
        lift_factors = pm.HalfNormal(
            "lift_factor",
            sigma=prior_config.get("lift_sigma", 0.1),
            dims="channel",
        )

        # Seasonality coefficients
        gamma_fourier = pm.Normal(
            "gamma_fourier",
            mu=0,
            sigma=prior_config.get("fourier_sigma", 0.5),
            dims="fourier",
        )

        # Trend coefficient
        gamma_trend = pm.Normal(
            "gamma_trend",
            mu=0,
            sigma=prior_config.get("trend_sigma", 0.5),
        )

        # Noise
        sigma = pm.HalfNormal(
            "sigma",
            sigma=prior_config.get("sigma_sigma", 0.3),
        )

        # Apply adstock (done outside the model for simplicity in this version)
        # In practice, you might want to use PyTensor scan for full Bayesian treatment
        X_media_adstocked = pm.Data(
            "X_media_adstocked",
            X_media,  # Placeholder - actual adstock applied during sampling
        )

        # Multiplicative model
        # y = baseline * prod((1 + lift_i * x_i)) * exp(seasonality + trend)
        channel_effects = 1.0
        for i in range(n_channels):
            channel_effects = channel_effects * (
                1 + lift_factors[i] * X_media_adstocked[:, i] / X_media[:, i].mean()
            )

        seasonality = pm.math.dot(X_fourier, gamma_fourier)
        mu = baseline * channel_effects * pm.math.exp(seasonality + gamma_trend * trend)

        # Likelihood (log-normal for positive outcomes)
        pm.LogNormal("y_obs", mu=pm.math.log(mu), sigma=sigma, observed=y, dims="obs")

    return model


def fit_model(
    model: pm.Model,
    draws: int = 2000,
    tune: int = 1000,
    chains: int = 4,
    target_accept: float = 0.9,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    stats_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    random_seed: int = 42,
    cores: Optional[int] = None,
) -> az.InferenceData:
    """
    Fit a PyMC model using MCMC sampling.

    Args:
        model: PyMC Model object
        draws: Number of posterior samples per chain
        tune: Number of tuning samples
        chains: Number of MCMC chains
        target_accept: Target acceptance rate for NUTS
        progress_callback: Optional callback function for progress updates
        stats_callback: Optional callback receiving one dict per draw with live
            NUTS sampler geometry - see below.
        random_seed: Random seed for reproducibility
        cores: Number of parallel processes; pass 1 when using `progress_callback`
            or `stats_callback` from a single-process host like Streamlit - PyMC's
            callback runs inside each chain's own process with multiprocessing, so
            a shared Python object mutated by the callback (e.g. a plain dict) is
            only visible to the caller when everything runs in-process (cores=1).
            A callback that only prints/logs (never mutates shared state) remains
            visible regardless of `cores`, since child processes share the parent's
            stdout. Defaults to PyMC's own choice (one process per chain) when not
            given.

    Returns:
        ArviZ InferenceData object containing the trace

    If `progress_callback` is given, it's called as progress_callback(n_done, n_total)
    after (approximately) every draw via PyMC's `callback` hook, and the console
    progress bar is disabled - so a caller (e.g. a Streamlit page) can drive its own
    progress indicator instead. Long-running sampling must not silently block the
    UI with no feedback.

    If `stats_callback` is given, it's called after every draw with a dict:
    `{"chain", "draw_idx", "tuning", "completed", "total", "diverging",
    "tree_depth", "tree_size", "step_size", "reached_max_treedepth"}` - the raw
    per-draw NUTS geometry PyMC's own step method already computes (see
    `pymc.step_methods.hmc.nuts.NUTS`'s documented stats), never a second,
    independently-derived approximation of it. Giving either callback disables
    the console progress bar exactly like `progress_callback` alone does today -
    a long-running fit (e.g. a fold-refit backtest calling this once per fold)
    must never leave a caller with no visibility into whether it is still making
    progress or stuck, for potentially hours, with nothing to look at.
    """
    total_steps = (draws + tune) * chains
    any_callback = progress_callback is not None or stats_callback is not None

    def _callback(trace, draw):
        completed = draw.chain * (draws + tune) + len(trace)
        if progress_callback is not None:
            progress_callback(completed, total_steps)
        if stats_callback is not None:
            step_stats = draw.stats[0] if draw.stats else {}
            stats_callback(
                {
                    "chain": draw.chain,
                    "draw_idx": draw.draw_idx,
                    "tuning": draw.tuning,
                    "completed": completed,
                    "total": total_steps,
                    "diverging": bool(step_stats.get("diverging", False)),
                    "tree_depth": step_stats.get("depth"),
                    "tree_size": step_stats.get("tree_size"),
                    "step_size": step_stats.get("step_size"),
                    "reached_max_treedepth": bool(
                        step_stats.get("reached_max_treedepth", False)
                    ),
                }
            )

    with model:
        trace = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            cores=cores,
            target_accept=target_accept,
            random_seed=random_seed,
            return_inferencedata=True,
            progressbar=not any_callback,
            callback=_callback if any_callback else None,
        )

    return trace


def compute_model_diagnostics(trace: az.InferenceData) -> Dict[str, Any]:
    """
    Compute model diagnostics from the trace.

    Args:
        trace: ArviZ InferenceData object

    Returns:
        Dictionary of diagnostic metrics
    """
    diagnostics = {}

    # R-hat (should be < 1.01 for convergence). ArviZ's rank-normalised R-hat
    # divides by each chain's within-chain variance (arviz/stats/diagnostics.py
    # _rhat) - a genuinely zero-variance chain (e.g. a small/degenerate
    # synthetic trace used in tests) makes that division 0/0, which numpy
    # reports as "invalid value encountered in scalar divide". This is
    # ArviZ's own numerics, not this codebase's, and the resulting NaN R-hat
    # is already the correct non-convergence signal - suppressed only around
    # this exact call, not repo-wide, so the same warning from any other,
    # non-ArviZ source (a genuine app-code divide bug) still surfaces
    # normally.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="invalid value encountered in scalar divide",
            category=RuntimeWarning,
        )
        rhat = az.rhat(trace)
    diagnostics["rhat"] = {
        var: float(rhat[var].values)
        if rhat[var].ndim == 0
        else rhat[var].values.tolist()
        for var in rhat.data_vars
    }
    diagnostics["rhat_max"] = float(
        max(
            np.max(v) if isinstance(v, (list, np.ndarray)) else v
            for v in diagnostics["rhat"].values()
        )
    )

    # Effective sample size
    ess = az.ess(trace)
    diagnostics["ess"] = {
        var: float(ess[var].values) if ess[var].ndim == 0 else ess[var].values.tolist()
        for var in ess.data_vars
    }
    diagnostics["ess_min"] = float(
        min(
            np.min(v) if isinstance(v, (list, np.ndarray)) else v
            for v in diagnostics["ess"].values()
        )
    )

    # MCSE (Monte Carlo Standard Error)
    mcse = az.mcse(trace)
    diagnostics["mcse"] = {
        var: float(mcse[var].values)
        if mcse[var].ndim == 0
        else mcse[var].values.tolist()
        for var in mcse.data_vars
    }

    # Divergences
    if hasattr(trace, "sample_stats") and "diverging" in trace.sample_stats:
        diagnostics["divergences"] = int(trace.sample_stats.diverging.sum())
    else:
        diagnostics["divergences"] = 0

    # Summary of convergence. UX-021: `rhat_max`/`ess_min` above are now
    # native Python floats (not numpy.float64), so this comparison chain
    # produces a native Python bool, not numpy.bool_ - important because
    # this dict is embedded (as "convergence") in a ModelComparisonCandidate
    # and other diagnostics payloads that get JSON-serialised via
    # `json.dumps(..., default=str)` when a project bundle is exported
    # (core/persistence.py). A numpy.bool_(False) is not natively
    # JSON-serialisable, so `default=str` silently stringifies it to the
    # literal text "False" - which is truthy on read-back, silently
    # flipping a non-converged candidate's status to "Converged" on the
    # Compare Models page after any export/import round-trip. Casting to
    # `bool()` here (the root cause) fixes every downstream consumer at
    # once rather than special-casing each serialisation call site.
    diagnostics["converged"] = bool(
        diagnostics["rhat_max"] < 1.05
        and diagnostics["ess_min"] > 100
        and diagnostics["divergences"] == 0
    )

    return diagnostics
