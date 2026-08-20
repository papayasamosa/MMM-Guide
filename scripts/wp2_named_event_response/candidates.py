"""Candidate event-response encodings for the WP2 evidence package.

Every candidate shares the same non-event specification (intercept,
linear trend, two-harmonic Fourier seasonality, three media channels
with fixed 0.7 geometric retention and estimated Hill saturation,
optional promotion term, Normal observation noise) so any difference in
metrics is attributable to the event encoding alone. The retention is
fixed and identical across candidates - media carryover is never run
backwards in any candidate.

Encodings:
  S1 fixed governed profile  - fixed reference weights, one estimated scale
  S2 low-dimensional parametric kernel - discretised normal kernel with
      estimated centre, width and amplitude
  S3 regularised distributed basis - cubic B-spline over the lead/lag
      window with a shared shrinkage prior on the coefficients
  S4 unconstrained weekly dummies - independent coefficients per
      relative week (PRD-discouraged reference)
  S5 partially pooled basis    - market-specific spline coefficients
      with a shared mean (multi-market only)

None of these is approved by this package; they are measured, not
selected.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pymc as pm
import pytensor.tensor as at
from scipy.interpolate import BSpline

from .dgp import REL_OFFSETS, Scenario

CANDIDATES = ("S1_fixed_profile", "S2_parametric", "S3_spline_basis", "S4_dummies")
CANDIDATES_MULTI = CANDIDATES + ("S5_pooled_basis",)

RETENTION = 0.7


def _adstock_matrix(n_weeks: int, retention: float) -> np.ndarray:
    """Toeplitz forward-adstock operator `T` with `T[i, j] = r^(i-j)` for
    `i >= j`. Media adstock only - never applied backwards."""
    idx = np.arange(n_weeks)
    dist = idx[:, None] - idx[None, :]
    return np.where(dist >= 0, retention**dist, 0.0)


def _event_design_tensor(event_design: np.ndarray) -> np.ndarray:
    return event_design.astype("float64")


def _spline_basis() -> np.ndarray:
    """Cubic B-spline basis over the relative-offset grid with interior
    knots at -2 and +2 (6 basis functions)."""
    knots = np.array([-4.0, -4.0, -4.0, -4.0, -2.0, 2.0, 4.0, 4.0, 4.0, 4.0])
    design = np.zeros((len(REL_OFFSETS), 6))
    for i in range(6):
        coef = np.zeros(6)
        coef[i] = 1.0
        design[:, i] = BSpline(knots, coef, 3)(REL_OFFSETS)
    return design


_SPLINE_BASIS = _spline_basis()
_FIXED_REFERENCE = np.exp(-0.5 * ((REL_OFFSETS - 0.0) / 1.0) ** 2)
_FIXED_REFERENCE = _FIXED_REFERENCE / _FIXED_REFERENCE.sum()


def _stable_hill(
    x: at.TensorVariable, alpha: at.TensorVariable, lam: at.TensorVariable
) -> at.TensorVariable:
    """Hill saturation in the numerically stable ratio form
    `1 / (1 + (x/lam)^-alpha)` - mathematically identical to
    `x^a/(x^a+l^a)` but overflow-safe for sampled alpha/lam."""
    ratio = at.maximum(x, 1e-12) / at.maximum(lam, 1e-12)
    return 1.0 / (1.0 + ratio ** (-alpha))


def _shared_terms(
    model: pm.Model, scenario: Scenario, n_weeks: int, market_media: np.ndarray
) -> Tuple[Dict, at.TensorVariable]:
    """Intercept, trend, seasonality, media and optional promotion terms
    shared by every candidate. `market_media` is the (W, C) media spend
    for a single-market scenario, or a stacked (W, M*C) tensor for a
    multi-market shared-structure scenario."""
    weeks = np.arange(n_weeks, dtype=float)
    with model:
        intercept = pm.Normal("intercept", 0.0, 10.0)
        trend_coef = pm.Normal("trend_coef", 0.0, 1.0)
        fourier_coefs = pm.Normal("fourier_coefs", 0.0, 2.0, shape=4)
        w = 2.0 * np.pi * weeks / 52.0
        seasonality = (
            fourier_coefs[0] * at.cos(w)
            + fourier_coefs[1] * at.sin(w)
            + fourier_coefs[2] * at.cos(2 * w)
            + fourier_coefs[3] * at.sin(2 * w)
        )

        n_ch = market_media.shape[1]
        x_t = at.as_tensor_variable(market_media).T  # (C, W)
        adstock_t = at.dot(
            x_t, at.as_tensor_variable(_adstock_matrix(n_weeks, RETENTION)).T
        )
        adstock = adstock_t.T  # (W, C)
        alpha = pm.HalfNormal("media_alpha", 3.0, shape=n_ch)
        lam = pm.HalfNormal("media_lam", 100.0, shape=n_ch)
        beta_media = pm.Normal("media_beta", 0.0, 1.0, shape=n_ch)
        saturation = _stable_hill(adstock, alpha, at.reshape(lam, (1, n_ch)))
        media_contrib = at.dot(saturation, beta_media)

        mu = intercept + trend_coef * weeks + seasonality + media_contrib
        terms = {
            "intercept": intercept,
            "seasonality": seasonality,
            "media_contrib": media_contrib,
        }
        if scenario.promo:
            promo_coef = pm.Normal("promo_coef", 0.0, 3.0)
            mu = mu + promo_coef * scenario.x_promo
            terms["promo_contrib"] = promo_coef * scenario.x_promo
            terms["promo_coef"] = promo_coef
    return terms, mu


def _event_encoding(
    model: pm.Model,
    candidate: str,
    event_design: np.ndarray,
    offsets: np.ndarray = REL_OFFSETS,
    fixed_reference: np.ndarray | None = None,
    wide_prior: bool = False,
) -> Tuple[Dict, at.TensorVariable]:
    """The candidate-specific event contribution `(terms, contrib)`.
    `offsets`/`fixed_reference`/`wide_prior` exist for the sensitivity
    fits only (wrong-window, oracle fixed-profile, wide-prior)."""
    e = at.as_tensor_variable(_event_design_tensor(event_design))
    with model:
        if candidate == "S1_fixed_profile":
            scale = pm.Normal("event_scale", 1.0, 0.5)
            weights = at.as_tensor_variable(
                fixed_reference if fixed_reference is not None else _FIXED_REFERENCE
            )
            contrib = scale * at.dot(e, weights)
        elif candidate == "S2_parametric":
            center = pm.Normal("event_center", 0.0, 3.0)
            width = pm.HalfNormal("event_width", 5.0 if wide_prior else 2.0)
            amplitude = pm.Normal("event_amplitude", 0.0, 20.0 if wide_prior else 10.0)
            weights = at.exp(
                -0.5 * ((at.as_tensor_variable(offsets) - center) / width) ** 2
            )
            contrib = amplitude * at.dot(e, weights)
        elif candidate in ("S3_spline_basis", "S5_pooled_basis"):
            tau = pm.HalfNormal("event_tau", 1.0)
            coefs = pm.Normal("event_coefs", 0.0, tau, shape=_SPLINE_BASIS.shape[1])
            weights = at.dot(at.as_tensor_variable(_SPLINE_BASIS), coefs)
            contrib = at.dot(e, weights)
        elif candidate == "S4_dummies":
            coefs = pm.Normal("event_coefs", 0.0, 2.0, shape=len(offsets))
            contrib = at.dot(e, coefs)
        else:
            raise ValueError(f"unknown candidate {candidate}")
    return {"event_contrib": contrib}, contrib


def build_single_market_model(
    scenario: Scenario,
    candidate: str,
    *,
    event_design: np.ndarray | None = None,
    offsets: np.ndarray = REL_OFFSETS,
    fixed_reference: np.ndarray | None = None,
    wide_prior: bool = False,
) -> pm.Model:
    """Single-market candidate model (S1-S4). The override keyword
    arguments exist for the sensitivity fits only."""
    design = event_design if event_design is not None else scenario.event_design
    model = pm.Model(coords={})
    with model:
        terms, mu = _shared_terms(
            model, scenario, scenario.y.shape[0], scenario.x_media
        )
        event_terms, contrib = _event_encoding(
            model,
            candidate,
            design,
            offsets=offsets,
            fixed_reference=fixed_reference,
            wide_prior=wide_prior,
        )
        mu = mu + contrib
        sigma = pm.HalfNormal("sigma", 5.0)
        pm.Normal("y_obs", mu, sigma, observed=scenario.y)
        terms.update(event_terms)
    return model


def build_multi_market_model(scenario: Scenario, candidate: str) -> pm.Model:
    """Multi-market candidate model. `structure` selects the shared
    (Model A analogue) or market-specific (Model C analogue) media
    specification; the event encoding is shared across markets for
    S1-S4 and market-specific partially pooled for S5."""
    n_markets, n_weeks, n_ch = scenario.x_media.shape
    weeks = np.arange(n_weeks, dtype=float)
    model = pm.Model(coords={"market": range(n_markets)})
    with model:
        intercept = pm.Normal("intercept", 0.0, 10.0)
        market_offset = pm.Normal("market_offset", 0.0, 5.0, shape=n_markets)
        trend_coef = pm.Normal("trend_coef", 0.0, 1.0)
        fourier_coefs = pm.Normal("fourier_coefs", 0.0, 2.0, shape=4)
        w = 2.0 * np.pi * weeks / 52.0
        seasonality = (
            fourier_coefs[0] * at.cos(w)
            + fourier_coefs[1] * at.sin(w)
            + fourier_coefs[2] * at.cos(2 * w)
            + fourier_coefs[3] * at.sin(2 * w)
        )
        base = intercept + market_offset[0] + trend_coef * weeks + seasonality

        if scenario.structure == "shared":
            beta_shape = (n_ch,)
            alpha = pm.HalfNormal("media_alpha", 3.0, shape=n_ch)
            lam = pm.HalfNormal("media_lam", 100.0, shape=n_ch)
            beta_media = pm.Normal("media_beta", 0.0, 1.0, shape=beta_shape)
            media_contribs = []
            for m in range(n_markets):
                x_t = at.as_tensor_variable(scenario.x_media[m]).T
                adstock_t = at.dot(
                    x_t,
                    at.as_tensor_variable(_adstock_matrix(n_weeks, RETENTION)).T,
                )
                adstock = adstock_t.T
                saturation = _stable_hill(adstock, alpha, at.reshape(lam, (1, n_ch)))
                media_contribs.append(at.dot(saturation, beta_media))
        else:  # market_specific
            beta_shape = (n_markets, n_ch)
            alpha = pm.HalfNormal("media_alpha", 3.0, shape=n_ch)
            lam = pm.HalfNormal("media_lam", 100.0, shape=n_ch)
            beta_media = pm.Normal("media_beta", 0.0, 1.0, shape=beta_shape)
            media_contribs = []
            for m in range(n_markets):
                x_t = at.as_tensor_variable(scenario.x_media[m]).T
                adstock_t = at.dot(
                    x_t,
                    at.as_tensor_variable(_adstock_matrix(n_weeks, RETENTION)).T,
                )
                adstock = adstock_t.T
                saturation = _stable_hill(adstock, alpha, at.reshape(lam, (1, n_ch)))
                media_contribs.append(at.dot(saturation, beta_media[m]))

        e = at.as_tensor_variable(_event_design_tensor(scenario.event_design))
        if candidate == "S1_fixed_profile":
            scale = pm.Normal("event_scale", 1.0, 0.5)
            event_contribs = [
                scale * at.dot(e, at.as_tensor_variable(_FIXED_REFERENCE))
                for _ in range(n_markets)
            ]
        elif candidate == "S2_parametric":
            center = pm.Normal("event_center", 0.0, 3.0)
            width = pm.HalfNormal("event_width", 2.0)
            amplitude = pm.Normal("event_amplitude", 0.0, 10.0)
            weights = at.exp(
                -0.5 * ((at.as_tensor_variable(REL_OFFSETS) - center) / width) ** 2
            )
            event_contribs = [amplitude * at.dot(e, weights) for _ in range(n_markets)]
        elif candidate == "S3_spline_basis":
            tau = pm.HalfNormal("event_tau", 1.0)
            coefs = pm.Normal("event_coefs", 0.0, tau, shape=_SPLINE_BASIS.shape[1])
            weights = at.dot(at.as_tensor_variable(_SPLINE_BASIS), coefs)
            event_contribs = [at.dot(e, weights) for _ in range(n_markets)]
        elif candidate == "S4_dummies":
            coefs = pm.Normal("event_coefs", 0.0, 2.0, shape=len(REL_OFFSETS))
            event_contribs = [at.dot(e, coefs) for _ in range(n_markets)]
        elif candidate == "S5_pooled_basis":
            center_coefs = pm.Normal(
                "event_center_coefs", 0.0, 1.0, shape=_SPLINE_BASIS.shape[1]
            )
            spread = pm.HalfNormal("event_spread", 1.0)
            market_coefs = pm.Normal(
                "event_market_coefs",
                center_coefs,
                spread,
                shape=(n_markets, _SPLINE_BASIS.shape[1]),
            )
            weights_m = at.dot(at.as_tensor_variable(_SPLINE_BASIS), market_coefs.T).T
            event_contribs = [at.dot(e, weights_m[m]) for m in range(n_markets)]
        else:
            raise ValueError(f"unknown candidate {candidate}")

        sigma = pm.HalfNormal("sigma", 5.0)
        mu_stack = at.stack(
            [
                base
                + (market_offset[m] - market_offset[0])
                + media_contribs[m]
                + event_contribs[m]
                for m in range(n_markets)
            ]
        )
        pm.Normal("y_obs", mu_stack, sigma, observed=scenario.y)
    return model


def model_and_vars(
    scenario: Scenario, candidate: str
) -> Tuple[pm.Model, Dict[str, str]]:
    """Build the model for `(scenario, candidate)` and return the
    variable names the metrics need: event contribution term, media
    term, promo term (if any), seasonality term."""
    if scenario.n_markets == 1:
        return build_single_market_model(scenario, candidate), {
            "event": "event_contrib",
            "media": "media_contrib",
            "seasonality": "seasonality",
            "promo": "promo_contrib" if scenario.promo else None,
        }
    return build_multi_market_model(scenario, candidate), {
        "event": "event_contrib",
        "media": "media_contrib",
        "seasonality": "seasonality",
        "promo": None,
    }
