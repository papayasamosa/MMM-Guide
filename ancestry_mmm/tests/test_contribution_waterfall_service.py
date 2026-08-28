"""Tests for application.contribution_waterfall_service - the
Streamlit-independent orchestration of the WP2F contribution waterfall,
composing core.outcome_valuation_periods.resolve_weeks_for_grain,
core.outcome_valuation_reporting.available_weeks_for_market, and
core.contribution_waterfall.compute_contribution_waterfall_bridge.
Hand-constructed FHModelMeta/InferenceData/frame, matching
test_contribution_waterfall.py's fixtures."""

from __future__ import annotations

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.application.contribution_waterfall_service import (
    ContributionWaterfallPeriodRequest,
    ContributionWaterfallRequest,
    ContributionWaterfallService,
)
from ancestry_mmm.core.contribution_waterfall import BASELINE_COMPONENT
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.outcome_valuation_periods import (
    PERIOD_GRAIN_CUSTOM,
    PERIOD_GRAIN_QUARTER,
    PERIOD_GRAIN_WEEK,
)

OUTCOME_IDS = ["New"]
CHANNELS = ["TV_Brand", "Search"]
MARKETS = ["UK"]
N_WEEKS = 8
WEEK_STARTS = [
    (pd.Timestamp("2025-01-06") + pd.Timedelta(weeks=i)).strftime("%Y-%m-%d")
    for i in range(N_WEEKS)
]


def _const_broadcast(value, n_chain, n_draw):
    arr = np.asarray(value, dtype=float)
    return np.broadcast_to(arr, (n_chain, n_draw) + arr.shape).copy()


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=MARKETS,
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0, 1],
        dna_outcome_id="New",
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
    )


@pytest.fixture
def trace() -> az.InferenceData:
    n_chain, n_draw = 2, 10
    rng = np.random.default_rng(7)
    coords = {
        "outcome": OUTCOME_IDS,
        "channel": CHANNELS,
        "market": MARKETS,
        "obs": list(range(N_WEEKS)),
        "fourier": list(range(4)),
    }

    def const(value):
        return _const_broadcast(value, n_chain, n_draw)

    trend_values = np.linspace(0.0, 0.3, N_WEEKS)
    season_values = np.linspace(0.1, -0.1, N_WEEKS)
    controls_values = np.linspace(-0.05, 0.05, N_WEEKS)

    posterior = {
        "decay_rate": const([0.5, 0.3]),
        "hill_K": const([1000.0, 800.0])
        * (1 + rng.normal(0, 0.02, size=(n_chain, n_draw, 2))),
        "hill_S": const([1.0, 1.0]),
        "beta": const([[0.10, 0.06]])
        * (1 + rng.normal(0, 0.05, size=(n_chain, n_draw, 1, 2))),
        "halo_strength": const([0.0, 0.0]),
        "promo_coef": const([0.0]),
        "market_offset": const([[0.0]]),
        "intercept": const([3.0]),
        "trend_coef": const([0.0]),
        "gamma_fourier": const(np.zeros((4, 1))),
        "alpha": const([5.0]),
        "eta_market": const(np.full((N_WEEKS, 1), 0.4)),
        "eta_trend": const(trend_values[:, None]),
        "eta_season": const(season_values[:, None]),
        "eta_promo": const(np.zeros((N_WEEKS, 1))),
        "eta_controls": const(controls_values[:, None]),
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "beta": ["outcome", "channel"],
        "halo_strength": ["channel"],
        "promo_coef": ["outcome"],
        "market_offset": ["market", "outcome"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"],
        "alpha": ["outcome"],
        "eta_market": ["obs", "outcome"],
        "eta_trend": ["obs", "outcome"],
        "eta_season": ["obs", "outcome"],
        "eta_promo": ["obs", "outcome"],
        "eta_controls": ["obs", "outcome"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


@pytest.fixture
def frame():
    rng = np.random.default_rng(3)
    return {
        "markets": MARKETS,
        "market_idx": np.zeros(N_WEEKS, dtype=int),
        "market_bounds": [(0, N_WEEKS)],
        "dates": np.array(WEEK_STARTS, dtype="datetime64[D]"),
        "X_media": rng.uniform(50, 500, size=(N_WEEKS, len(CHANNELS))),
        "promo": np.zeros((N_WEEKS, len(OUTCOME_IDS))),
        "trend": np.zeros(N_WEEKS),
        "fourier": np.zeros((N_WEEKS, 4)),
        "control_names": [],
        "X_controls": np.zeros((N_WEEKS, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


def _base_request(_trace, _frame, _meta, **overrides) -> ContributionWaterfallRequest:
    defaults = dict(
        market="UK",
        trace=_trace,
        frame=_frame,
        meta=_meta,
        outcome_ids=["New"],
        period_a=ContributionWaterfallPeriodRequest(
            grain=PERIOD_GRAIN_WEEK, period_label=WEEK_STARTS[0]
        ),
        period_b=ContributionWaterfallPeriodRequest(
            grain=PERIOD_GRAIN_WEEK, period_label=WEEK_STARTS[4]
        ),
        n_draws=3,
        n_permutations=5,
    )
    defaults.update(overrides)
    return ContributionWaterfallRequest(**defaults)


class TestHappyPath:
    def test_week_vs_week_reconciles(self, trace, frame, meta):
        request = _base_request(trace, frame, meta)
        result = ContributionWaterfallService().compute(request)

        assert result.errors == []
        assert result.bridge is not None
        assert result.resolved_period_a_weeks == [WEEK_STARTS[0]]
        assert result.resolved_period_b_weeks == [WEEK_STARTS[4]]
        bridge_sum = sum(c.bridge_mean for c in result.bridge.components)
        assert (
            pytest.approx(
                result.bridge.period_a_outcome_mean + bridge_sum, rel=1e-5, abs=1e-6
            )
            == result.bridge.period_b_outcome_mean
        )

    def test_quarter_vs_custom_range_reconciles(self, trace, frame, meta):
        request = _base_request(
            trace,
            frame,
            meta,
            period_a=ContributionWaterfallPeriodRequest(
                grain=PERIOD_GRAIN_QUARTER, period_label="2025-Q1"
            ),
            period_b=ContributionWaterfallPeriodRequest(
                grain=PERIOD_GRAIN_CUSTOM,
                custom_range_start=WEEK_STARTS[2],
                custom_range_end=WEEK_STARTS[5],
            ),
        )
        result = ContributionWaterfallService().compute(request)

        assert result.errors == []
        assert result.resolved_period_a_weeks == WEEK_STARTS
        assert result.resolved_period_b_weeks == WEEK_STARTS[2:6]
        bridge_sum = sum(c.bridge_mean for c in result.bridge.components)
        assert (
            pytest.approx(
                result.bridge.period_a_outcome_mean + bridge_sum, rel=1e-5, abs=1e-6
            )
            == result.bridge.period_b_outcome_mean
        )

    def test_bridge_includes_baseline_component(self, trace, frame, meta):
        request = _base_request(trace, frame, meta)
        result = ContributionWaterfallService().compute(request)
        component_names = {c.component for c in result.bridge.components}
        assert BASELINE_COMPONENT in component_names
        assert "TV_Brand" in component_names


class TestFailsClosed:
    def test_period_with_no_available_weeks_is_an_error(self, trace, frame, meta):
        request = _base_request(
            trace,
            frame,
            meta,
            period_a=ContributionWaterfallPeriodRequest(
                grain=PERIOD_GRAIN_WEEK, period_label="2099-01-01"
            ),
        )
        result = ContributionWaterfallService().compute(request)

        assert result.bridge is None
        assert any("Period A" in e for e in result.errors)

    def test_unknown_outcome_id_is_an_error(self, trace, frame, meta):
        request = _base_request(trace, frame, meta, outcome_ids=["Nonexistent"])
        result = ContributionWaterfallService().compute(request)

        assert result.bridge is None
        assert result.errors != []

    @pytest.mark.parametrize(
        "field_name,value",
        [
            ("trace", None),
            ("frame", None),
            ("meta", None),
            ("market", ""),
            ("outcome_ids", []),
        ],
    )
    def test_missing_required_field_is_a_validation_error(
        self, trace, frame, meta, field_name, value
    ):
        request = _base_request(trace, frame, meta, **{field_name: value})
        result = ContributionWaterfallService().compute(request)

        assert result.bridge is None
        assert result.errors != []
