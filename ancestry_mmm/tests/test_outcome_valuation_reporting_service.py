"""Tests for application.outcome_valuation_reporting_service - the
Streamlit-independent orchestration of historical Results economic
reporting (WP2D-ui), composing core.outcome_valuation_periods, core.
outcome_valuation_reporting, core.outcome_valuation_rates, and core.
outcome_valuation_attribution end to end. Hand-constructed FHModelMeta/
InferenceData/frame, matching test_outcome_valuation_reporting.py's
fixtures."""

from __future__ import annotations

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.application.outcome_valuation_reporting_service import (
    HistoricalOutcomeValuationRequest,
    OutcomeValuationReportingService,
)
from ancestry_mmm.core.coverage import STATE_ESTIMATED
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.outcome_valuation import (
    VALUATION_KIND_FH_LTR,
    WeeklyOutcomeValuationRecord,
)
from ancestry_mmm.core.outcome_valuation_periods import (
    PERIOD_GRAIN_CUSTOM,
    PERIOD_GRAIN_QUARTER,
    PERIOD_GRAIN_WEEK,
)
from ancestry_mmm.core.outcome_valuation_reporting import attributable_spend

OUTCOME_IDS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV_Brand", "DNA_Media"]
MARKETS = ["UK", "AU"]
N_WEEKS_PER_MARKET = 8
WEEK_STARTS = [
    (pd.Timestamp("2025-01-06") + pd.Timedelta(weeks=i)).strftime("%Y-%m-%d")
    for i in range(N_WEEKS_PER_MARKET)
]
SEGMENT = "All"


def _const_broadcast(value, n_chain, n_draw):
    arr = np.asarray(value, dtype=float)
    return np.broadcast_to(arr, (n_chain, n_draw) + arr.shape).copy()


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=MARKETS,
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell",
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
        outcome_id_to_segment={"New": SEGMENT, "DNA_CrossSell": SEGMENT},
    )


@pytest.fixture
def trace() -> az.InferenceData:
    n_chain, n_draw = 2, 10
    coords = {
        "outcome": OUTCOME_IDS,
        "channel": CHANNELS,
        "market": MARKETS,
        "fourier": list(range(4)),
    }
    rng = np.random.default_rng(11)

    def const(value):
        return _const_broadcast(value, n_chain, n_draw)

    posterior = {
        "decay_rate": const([0.5, 0.4]),
        "hill_K": const([1000.0, 500.0])
        * (1 + rng.normal(0, 0.05, size=(n_chain, n_draw, 2))),
        "hill_S": const([1.0, 1.0]),
        "beta": const([[0.10, 0.05], [0.02, 0.20]])
        * (1 + rng.normal(0, 0.1, size=(n_chain, n_draw, 2, 2))),
        "halo_strength": const([0.15, 1.0]),
        "promo_coef": const([0.0, 0.0]),
        "market_offset": const([[0.0, 0.0], [0.1, -0.1]]),
        "intercept": const([3.0, 2.0]),
        "trend_coef": const([0.0, 0.0]),
        "gamma_fourier": const(np.zeros((4, 2))),
        "alpha": const([5.0, 5.0]),
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "beta": ["outcome", "channel"],
        "halo_strength": ["outcome"],
        "promo_coef": ["outcome"],
        "market_offset": ["market", "outcome"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"],
        "alpha": ["outcome"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


@pytest.fixture
def frame():
    n_per_market = N_WEEKS_PER_MARKET
    n_markets = len(MARKETS)
    n = n_per_market * n_markets
    rng = np.random.default_rng(5)
    market_idx = np.repeat(np.arange(n_markets), n_per_market)
    market_bounds = [
        (i * n_per_market, (i + 1) * n_per_market) for i in range(n_markets)
    ]
    dates = np.array(WEEK_STARTS * n_markets, dtype="datetime64[D]")
    return {
        "markets": MARKETS,
        "market_idx": market_idx,
        "market_bounds": market_bounds,
        "dates": dates,
        "X_media": rng.uniform(50, 500, size=(n, 2)),
        "Y": rng.uniform(100, 1000, size=(n, len(OUTCOME_IDS))),
        "promo": np.zeros((n, len(OUTCOME_IDS))),
        "trend": np.zeros(n),
        "fourier": np.zeros((n, 4)),
        "control_names": [],
        "X_controls": np.zeros((n, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


def _valuation_records(weeks, *, market="UK", segment=SEGMENT, aggregate_value=500.0):
    return [
        WeeklyOutcomeValuationRecord(
            valuation_kind=VALUATION_KIND_FH_LTR,
            market=market,
            week=week,
            segment=segment,
            denominator_outcome_id="New",
            quality_status=STATE_ESTIMATED,
            aggregate_value=aggregate_value,
            currency="GBP",
        )
        for week in weeks
    ]


def _base_request(
    _trace, _frame, _meta, **overrides
) -> HistoricalOutcomeValuationRequest:
    defaults = dict(
        market="UK",
        grain=PERIOD_GRAIN_QUARTER,
        trace=_trace,
        frame=_frame,
        meta=_meta,
        outcome_ids=["New"],
        segment=SEGMENT,
        valuation_kind=VALUATION_KIND_FH_LTR,
        weekly_valuation_records=_valuation_records(WEEK_STARTS),
        period_label="2025-Q1",
        n_draws=4,
        n_permutations=5,
    )
    defaults.update(overrides)
    return HistoricalOutcomeValuationRequest(**defaults)


class TestHappyPath:
    def test_quarter_view_resolves_every_available_week(self, trace, frame, meta):
        request = _base_request(trace, frame, meta)
        result = OutcomeValuationReportingService().evaluate_period(request)

        assert result.errors == []
        assert result.resolved_weeks == WEEK_STARTS
        assert result.attribution is not None
        assert np.isfinite(result.attribution.incremental_value_mean)
        assert result.attribution.currency == "GBP"
        assert result.attribution.spend == pytest.approx(
            attributable_spend(frame, meta, market="UK", weeks=WEEK_STARTS)
        )

    def test_channel_selection_uses_that_channels_spend(self, trace, frame, meta):
        request = _base_request(trace, frame, meta, channel="TV_Brand")
        result = OutcomeValuationReportingService().evaluate_period(request)

        assert result.errors == []
        assert result.attribution is not None
        assert result.attribution.spend == pytest.approx(
            attributable_spend(
                frame, meta, market="UK", weeks=WEEK_STARTS, channel="TV_Brand"
            )
        )

    def test_single_week_grain(self, trace, frame, meta):
        request = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_WEEK,
            period_label=WEEK_STARTS[0],
        )
        result = OutcomeValuationReportingService().evaluate_period(request)

        assert result.errors == []
        assert result.resolved_weeks == [WEEK_STARTS[0]]

    def test_custom_range_grain(self, trace, frame, meta):
        request = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_CUSTOM,
            period_label=None,
            custom_range_start=WEEK_STARTS[1],
            custom_range_end=WEEK_STARTS[3],
        )
        result = OutcomeValuationReportingService().evaluate_period(request)

        assert result.errors == []
        assert result.resolved_weeks == WEEK_STARTS[1:4]


class TestFailsClosed:
    def test_missing_valuation_coverage_for_a_week_is_an_error(
        self, trace, frame, meta
    ):
        records = _valuation_records(WEEK_STARTS[:-1])  # last week has no record
        request = _base_request(trace, frame, meta, weekly_valuation_records=records)
        result = OutcomeValuationReportingService().evaluate_period(request)

        assert result.attribution is None
        assert any("Missing governed valuation coverage" in e for e in result.errors)
        assert WEEK_STARTS[-1] in result.errors[0]

    def test_wrong_segment_has_no_coverage(self, trace, frame, meta):
        records = _valuation_records(WEEK_STARTS, segment="Other")
        request = _base_request(trace, frame, meta, weekly_valuation_records=records)
        result = OutcomeValuationReportingService().evaluate_period(request)

        assert result.attribution is None
        assert any("Missing governed valuation coverage" in e for e in result.errors)

    def test_period_with_no_available_weeks_is_an_error(self, trace, frame, meta):
        request = _base_request(trace, frame, meta, period_label="2030-Q1")
        result = OutcomeValuationReportingService().evaluate_period(request)

        assert result.attribution is None
        assert result.resolved_weeks == []
        assert any("No weeks are available" in e for e in result.errors)

    def test_unsupported_grain_is_an_error(self, trace, frame, meta):
        request = _base_request(trace, frame, meta, grain="fortnight")
        result = OutcomeValuationReportingService().evaluate_period(request)

        assert result.attribution is None
        assert any("Unsupported reporting grain" in e for e in result.errors)

    @pytest.mark.parametrize(
        "field_name,value",
        [
            ("trace", None),
            ("frame", None),
            ("meta", None),
            ("market", ""),
            ("valuation_kind", ""),
            ("segment", ""),
            ("outcome_ids", []),
        ],
    )
    def test_missing_required_field_is_a_validation_error(
        self, trace, frame, meta, field_name, value
    ):
        request = _base_request(trace, frame, meta, **{field_name: value})
        result = OutcomeValuationReportingService().evaluate_period(request)

        assert result.attribution is None
        assert result.errors != []
