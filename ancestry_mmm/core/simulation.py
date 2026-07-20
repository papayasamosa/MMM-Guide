"""
Synthetic-data simulation framework for the market-specific hierarchical MMM
redesign (see docs/model_validation.md and requirements doc section 14).

Generates a panel with *known ground truth*: market-specific saturation
points and response strengths drawn from a shared global distribution
(the same hierarchical structure the Phase 2 model is meant to recover),
one small weak-data market, multiple segments, and media cost inflation
over time driving a spend/physical-media-unit relationship.

Phase 1 scope: this module only builds and returns the synthetic panel plus
its ground truth. It does not fit or validate a model against that ground
truth - the market-specific hierarchical model doesn't exist yet (Phase 2).
Its job is to give Phase 2 a ready-made, already-tested recovery fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .transformations import geometric_adstock, hill_function

DEFAULT_SEGMENTS = ["New", "Winback", "DNA_CrossSell"]


@dataclass
class MarketSimSpec:
    """One market's simulation parameters."""

    name: str
    n_weeks: int = 104
    size_multiplier: float = 1.0
    k_multiplier: float = 1.0
    beta_multiplier: float = 1.0


@dataclass
class ChannelSimSpec:
    """One channel's global (pre-pooling) simulation parameters. `K` and
    `base_cost_per_unit` are expressed in physical media units (impressions,
    GRPs, ...), not spend - spend is derived as units x cost-per-unit."""

    name: str
    decay: float = 0.5
    K: float = 100.0
    S: float = 1.5
    beta: float = 1.0
    base_cost_per_unit: float = 10.0
    annual_inflation: float = 0.05


def default_markets() -> List[MarketSimSpec]:
    """Three markets of different sizes; the third is deliberately small and
    short-history - a weak-data market that should be shrunk hard toward the
    shared distribution in Phase 2's partial pooling."""
    return [
        MarketSimSpec(name="UK", n_weeks=104, size_multiplier=1.0, k_multiplier=1.0, beta_multiplier=1.0),
        MarketSimSpec(name="Australia", n_weeks=104, size_multiplier=0.4, k_multiplier=0.6, beta_multiplier=0.8),
        MarketSimSpec(name="NewMarket", n_weeks=26, size_multiplier=0.12, k_multiplier=0.3, beta_multiplier=0.5),
    ]


def default_channels() -> List[ChannelSimSpec]:
    return [
        ChannelSimSpec(name="TV", decay=0.6, K=500.0, S=1.8, beta=1.4, base_cost_per_unit=8.0, annual_inflation=0.06),
        ChannelSimSpec(name="Search", decay=0.2, K=200.0, S=1.2, beta=0.9, base_cost_per_unit=2.0, annual_inflation=0.08),
        ChannelSimSpec(name="Social", decay=0.35, K=300.0, S=1.5, beta=0.7, base_cost_per_unit=5.0, annual_inflation=0.10),
    ]


@dataclass
class SimulationGroundTruth:
    """Ground-truth parameters used to generate the panel - what a Phase 2
    recovery test compares a fitted model's posterior against."""

    market_K: Dict[str, Dict[str, float]] = field(default_factory=dict)
    market_beta: Dict[str, Dict[str, Dict[str, float]]] = field(default_factory=dict)
    channel_decay: Dict[str, float] = field(default_factory=dict)
    channel_S: Dict[str, float] = field(default_factory=dict)
    cost_per_unit: Dict[str, Dict[str, np.ndarray]] = field(default_factory=dict)  # market -> channel -> weekly array


@dataclass
class SimulationResult:
    panel: pd.DataFrame
    ground_truth: SimulationGroundTruth
    markets: List[MarketSimSpec]
    channels: List[ChannelSimSpec]
    segments: List[str]


def simulate_market_specific_panel(
    markets: Optional[List[MarketSimSpec]] = None,
    channels: Optional[List[ChannelSimSpec]] = None,
    segments: Optional[List[str]] = None,
    *,
    seed: int = 0,
    market_k_sigma: float = 0.3,
    market_beta_sigma: float = 0.3,
    segment_beta_sigma: float = 0.25,
    noise_sd_frac: float = 0.05,
) -> SimulationResult:
    """Generate a synthetic date x market panel with per-segment outcome
    columns and per-channel spend + physical-media-unit columns.

    Hierarchical structure (matches docs/market_hierarchy.md section 2):
    - `log_K[market, channel] ~ Normal(log(channel.K * market.k_multiplier), market_k_sigma)`
      - a market-specific saturation point drawn around a market-scaled
        global mean, not shared and not independent.
    - `log_beta[market, segment, channel] ~ Normal(log(channel.beta * market.beta_multiplier), market_beta_sigma + segment_beta_sigma)`
      - same idea for response strength, with an extra segment-level
        deviation so segments differ within a market too.
    - `decay[channel]` and `S[channel]` are shared across markets (the
      "initial production version" the requirements doc recommends -
      adstock and Hill slope are not yet market-specific).
    """
    rng = np.random.default_rng(seed)
    markets = markets or default_markets()
    channels = channels or default_channels()
    segments = segments or list(DEFAULT_SEGMENTS)

    if len(markets) < 3:
        raise ValueError("Need at least 3 markets for a meaningful pooling simulation.")

    ground_truth = SimulationGroundTruth(
        channel_decay={c.name: c.decay for c in channels},
        channel_S={c.name: c.S for c in channels},
    )

    segment_beta_mult = {
        seg: float(np.exp(rng.normal(0, segment_beta_sigma))) for seg in segments
    }
    segment_baseline_mult = {
        seg: 0.6 + 0.5 * i / max(len(segments) - 1, 1) for i, seg in enumerate(segments)
    }

    frames = []
    for market in markets:
        n = market.n_weeks
        dates = pd.date_range("2022-01-05", periods=n, freq="W")
        rows: Dict[str, np.ndarray] = {"date": dates.values, "market": np.array([market.name] * n)}

        ground_truth.market_K[market.name] = {}
        ground_truth.market_beta[market.name] = {seg: {} for seg in segments}
        ground_truth.cost_per_unit[market.name] = {}

        segment_contribution: Dict[str, np.ndarray] = {seg: np.zeros(n) for seg in segments}

        for channel in channels:
            market_K = channel.K * market.k_multiplier * float(np.exp(rng.normal(0, market_k_sigma)))
            ground_truth.market_K[market.name][channel.name] = market_K

            weeks = np.arange(n)
            years = weeks / 52.0
            cost_per_unit = (
                channel.base_cost_per_unit
                * (1 + channel.annual_inflation) ** years
                * (1 + rng.normal(0, 0.02, size=n))
            )
            cost_per_unit = np.clip(cost_per_unit, a_min=channel.base_cost_per_unit * 0.5, a_max=None)
            ground_truth.cost_per_unit[market.name][channel.name] = cost_per_unit

            base_units = market_K * market.size_multiplier * 1.5
            seasonal = 1 + 0.25 * np.sin(2 * np.pi * weeks / 52.0)
            media_units = np.clip(
                base_units * seasonal * (1 + rng.normal(0, 0.15, size=n)), a_min=0.0, a_max=None
            )
            spend = media_units * cost_per_unit

            rows[f"{channel.name}_spend"] = spend
            rows[f"{channel.name}_units"] = media_units

            adstocked = geometric_adstock(media_units, channel.decay)
            saturated = hill_function(adstocked, market_K, channel.S)

            for seg in segments:
                seg_beta = (
                    channel.beta
                    * market.beta_multiplier
                    * segment_beta_mult[seg]
                    * float(np.exp(rng.normal(0, market_beta_sigma)))
                )
                ground_truth.market_beta[market.name][seg][channel.name] = seg_beta
                segment_contribution[seg] = segment_contribution[seg] + seg_beta * saturated

        trend = np.linspace(1.0, 1.1, n)
        for seg in segments:
            baseline_level = 50.0 * market.size_multiplier * segment_baseline_mult[seg]
            baseline = baseline_level * trend
            outcome = baseline + segment_contribution[seg]
            noise = rng.normal(0, noise_sd_frac * np.maximum(outcome, 1.0))
            rows[f"{seg}_outcome"] = np.clip(outcome + noise, a_min=0.0, a_max=None)

        frames.append(pd.DataFrame(rows))

    panel = pd.concat(frames, ignore_index=True)
    return SimulationResult(panel=panel, ground_truth=ground_truth, markets=markets, channels=channels, segments=segments)
