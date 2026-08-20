"""Synthetic data-generating processes for the WP2 named-event response
evidence package. Every generator is deterministic (seeded) and returns
the observed series, the design inputs, and the true parameter values
the metrics compare against.

All DGPs share one structural skeleton (weekly grain, 156 weeks, three
media channels with geometric adstock + Hill saturation, smooth Fourier
seasonality, linear trend) so every candidate model is misspecification-
comparable against the same unknowns; only the event mechanism and the
confounders vary per scenario. The production Model A / Model C builders
are intentionally not used - these are simplified synthetic analogues
(shared vs market-specific structural variants) suited to small repeated
recovery fits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

WEEKS = 156
CHANNELS = ("tv", "display", "social")
MEDIA_RETENTION = 0.7
SIGMA_NOISE = 1.5

# Relative-week event kernels, indexed by offset lead=-4..+4 (index 4 is
# the event week itself). These are the TRUE data-generating shapes the
# candidates must recover without being told the family.
KERNELS: Dict[str, np.ndarray] = {
    "contemporaneous": np.array([0.0, 0.0, 0.0, 0.0, 1.0, 0.5, 0.0, 0.0, 0.0]),
    "anticipatory": np.array([0.10, 0.20, 0.35, 0.15, 0.15, 0.0, 0.0, 0.0, 0.0]),
    "post_event": np.array([0.0, 0.0, 0.0, 0.0, 0.2, 0.6, 0.9, 0.5, 0.1]),
    "anticipatory_and_post_event": np.array(
        [0.10, 0.25, 0.30, 0.0, 0.4, 0.5, 0.4, 0.0, 0.0]
    ),
}

MAX_LEAD = 4
MAX_LAG = 4
REL_OFFSETS = np.arange(-MAX_LEAD, MAX_LAG + 1)


def _hill(x: np.ndarray, alpha: float, lam: float) -> np.ndarray:
    """Hill saturation of a non-negative series, same functional form the
    production engine uses (`x^alpha / (x^alpha + lam^alpha)`)."""
    x = np.maximum(x, 0.0)
    return x**alpha / (x**alpha + lam**alpha)


def _geometric_adstock(x: np.ndarray, retention: float) -> np.ndarray:
    """Forward geometric adstock. Never run backwards - anticipatory
    event response in the DGP is event-relative, not reverse adstock."""
    out = np.empty_like(x)
    carry = np.zeros(x.shape[1])
    for t in range(x.shape[0]):
        carry = x[t] + retention * carry
        out[t] = carry
    return out


def _fourier_seasonality(weeks: np.ndarray, coefs: np.ndarray) -> np.ndarray:
    """Smooth two-harmonic Fourier seasonality; `coefs` is
    `[c1, s1, c2, s2]`."""
    w = 2.0 * np.pi * weeks / 52.0
    return (
        coefs[0] * np.cos(w)
        + coefs[1] * np.sin(w)
        + coefs[2] * np.cos(2 * w)
        + coefs[3] * np.sin(2 * w)
    )


def _event_design(
    event_weeks: np.ndarray, offsets: np.ndarray = REL_OFFSETS
) -> np.ndarray:
    """Event-relative indicator design matrix `E` of shape (W, K): row t,
    column k is 1 when week t lies exactly `offsets[k]` from some
    occurrence's factual date. The factual dates are never shifted."""
    e = np.zeros((WEEKS, len(offsets)))
    for week in event_weeks:
        for k, offset in enumerate(offsets):
            target = week + offset
            if 0 <= target < WEEKS:
                e[target, k] = 1.0
    return e


@dataclass
class Scenario:
    key: str
    kernel_key: str
    event_weeks: np.ndarray
    amplitude: float
    seed: int
    n_markets: int = 1
    promo: bool = False
    media_burst: bool = False
    seasonal_peak: bool = False
    # Structural variant: "shared" (Model A analogue: pooled media
    # coefficients with market offsets) or "market_specific" (Model C
    # analogue: market-specific media coefficients).
    structure: str = "shared"
    y: np.ndarray = field(default=None, init=False)
    x_media: np.ndarray = field(default=None, init=False)
    x_promo: np.ndarray = field(default=None, init=False)
    event_design: np.ndarray = field(default=None, init=False)
    true: Dict = field(default=None, init=False)


def _generate(scenario: Scenario) -> None:
    rng = np.random.default_rng(scenario.seed)
    weeks = np.arange(WEEKS, dtype=float)
    trend = 30.0 + 0.04 * weeks
    season_coefs = np.array([2.0, -1.5, 0.8, 0.6])
    seasonality = _fourier_seasonality(weeks, season_coefs)

    n_ch = len(CHANNELS)
    base_spend = np.column_stack(
        [
            40
            + 8 * np.sin(2 * np.pi * weeks / 52.0 + phase)
            + rng.uniform(-3, 3, WEEKS)
            for phase in (0.0, 1.8, 3.4)
        ]
    )
    if scenario.media_burst:
        for week in scenario.event_weeks:
            lo, hi = max(0, week - 1), min(WEEKS, week + 2)
            base_spend[lo:hi, 0] += 60.0
    x_media = np.maximum(base_spend, 0.0)

    true_alpha = np.array([1.2, 1.0, 1.5])
    true_lam = np.array([40.0, 55.0, 30.0])
    true_media_beta = np.array([0.35, 0.25, 0.18])
    adstocked = _geometric_adstock(x_media, MEDIA_RETENTION)
    saturated = np.column_stack(
        [_hill(adstocked[:, c], true_alpha[c], true_lam[c]) for c in range(n_ch)]
    )
    media_contrib = saturated @ true_media_beta

    if scenario.promo:
        x_promo = np.zeros(WEEKS)
        for week in scenario.event_weeks:
            lo, hi = max(0, week - 1), min(WEEKS, week + 1)
            x_promo[lo:hi] = 1.0
        promo_contrib = 6.0 * x_promo
    else:
        x_promo = np.zeros(WEEKS)
        promo_contrib = np.zeros(WEEKS)

    kernel = KERNELS[scenario.kernel_key]
    event_design = _event_design(scenario.event_weeks)
    event_contrib = scenario.amplitude * (event_design @ kernel)

    if scenario.seasonal_peak:
        # A seasonal bulge aligned with the event occurrences (e.g. a
        # gifting occasion on top of the smooth cycle) - the candidate
        # must not absorb it into media or the event.
        peak = np.zeros(WEEKS)
        for week in scenario.event_weeks:
            lo, hi = max(0, week - 1), min(WEEKS, week + 1)
            peak[lo:hi] = 5.0
        seasonality = seasonality + peak

    mu = trend + seasonality + media_contrib + promo_contrib + event_contrib
    y = mu + rng.normal(0.0, SIGMA_NOISE, WEEKS)

    scenario.y = y
    scenario.x_media = x_media
    scenario.x_promo = x_promo
    scenario.event_design = event_design
    scenario.true = {
        "trend": trend,
        "seasonality": seasonality,
        "media_contrib": media_contrib,
        "promo_contrib": promo_contrib,
        "event_contrib": event_contrib,
        "kernel": kernel,
        "media_beta": true_media_beta,
        "media_alpha": true_alpha,
        "media_lam": true_lam,
        "amplitude": scenario.amplitude,
        "promo_coef": 6.0 if scenario.promo else 0.0,
    }


def build_scenarios() -> List[Scenario]:
    """The full deterministic scenario grid. Event weeks are spread so
    overlapping relative windows never collide within a scenario."""
    scenarios = [
        Scenario(
            key="contemporaneous",
            kernel_key="contemporaneous",
            event_weeks=np.arange(12, WEEKS - 10, 14),
            amplitude=8.0,
            seed=101,
        ),
        Scenario(
            key="anticipatory",
            kernel_key="anticipatory",
            event_weeks=np.arange(12, WEEKS - 10, 14),
            amplitude=8.0,
            seed=102,
        ),
        Scenario(
            key="post_event",
            kernel_key="post_event",
            event_weeks=np.arange(12, WEEKS - 10, 14),
            amplitude=8.0,
            seed=103,
        ),
        Scenario(
            key="anticipatory_and_post_event",
            kernel_key="anticipatory_and_post_event",
            event_weeks=np.arange(12, WEEKS - 10, 14),
            amplitude=8.0,
            seed=104,
        ),
        Scenario(
            key="event_plus_promotion",
            kernel_key="anticipatory",
            event_weeks=np.arange(12, WEEKS - 10, 17),
            amplitude=8.0,
            seed=105,
            promo=True,
        ),
        Scenario(
            key="event_plus_media_burst",
            kernel_key="anticipatory",
            event_weeks=np.arange(12, WEEKS - 10, 17),
            amplitude=8.0,
            seed=106,
            media_burst=True,
        ),
        Scenario(
            key="event_plus_seasonal_peak",
            kernel_key="contemporaneous",
            event_weeks=np.arange(12, WEEKS - 10, 17),
            amplitude=8.0,
            seed=107,
            seasonal_peak=True,
        ),
        Scenario(
            key="sparse_repeats",
            kernel_key="anticipatory",
            event_weeks=np.array([30, 80, 130]),
            amplitude=8.0,
            seed=108,
        ),
    ]
    for scenario in scenarios:
        _generate(scenario)
    return scenarios


def build_multi_market_scenario(structure: str) -> Scenario:
    """One multi-market scenario (two markets, market-specific baseline
    and media coefficients; partially pooled event shape). Model A/C
    analogues only - not the production builders."""
    rng = np.random.default_rng(200)
    weeks = np.arange(WEEKS, dtype=float)
    event_weeks = np.arange(12, WEEKS - 10, 17)
    kernel = KERNELS["anticipatory"]
    event_design = _event_design(event_weeks)

    market_y, market_x = [], []
    for m, (bias, beta_scale) in enumerate(((0.0, 1.0), (1.5, 0.8))):
        trend = 30.0 + bias + 0.04 * weeks
        seasonality = _fourier_seasonality(weeks, np.array([2.0, -1.5, 0.8, 0.6]))
        base_spend = np.column_stack(
            [
                40
                + 8 * np.sin(2 * np.pi * weeks / 52.0 + phase + 0.5 * m)
                + rng.uniform(-3, 3, WEEKS)
                for phase in (0.0, 1.8, 3.4)
            ]
        )
        x_media_m = np.maximum(base_spend, 0.0)
        true_alpha = np.array([1.2, 1.0, 1.5])
        true_lam = np.array([40.0, 55.0, 30.0])
        true_media_beta = np.array([0.35, 0.25, 0.18]) * beta_scale
        adstocked = _geometric_adstock(x_media_m, MEDIA_RETENTION)
        saturated = np.column_stack(
            [_hill(adstocked[:, c], true_alpha[c], true_lam[c]) for c in range(3)]
        )
        media_contrib = saturated @ true_media_beta
        event_contrib = 8.0 * (event_design @ kernel)
        mu = trend + seasonality + media_contrib + event_contrib
        market_y.append(mu + rng.normal(0.0, SIGMA_NOISE, WEEKS))
        market_x.append(x_media_m)

    scenario = Scenario(
        key="multi_market",
        kernel_key="anticipatory",
        event_weeks=event_weeks,
        amplitude=8.0,
        seed=200,
        n_markets=2,
        structure=structure,
    )
    scenario.y = np.stack(market_y)  # (M, W)
    scenario.x_media = np.stack(market_x)  # (M, W, C)
    scenario.x_promo = np.zeros((2, WEEKS))
    scenario.event_design = event_design
    scenario.true = {
        "kernel": kernel,
        "amplitude": 8.0,
        "media_beta": np.array([[0.35, 0.25, 0.18], [0.28, 0.20, 0.144]]),
        "media_alpha": np.array([1.2, 1.0, 1.5]),
        "media_lam": np.array([40.0, 55.0, 30.0]),
    }
    return scenario
