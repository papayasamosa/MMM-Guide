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
from ancestry_mmm.core.coverage import STATE_ESTIMATED, STATE_OBSERVED_ZERO
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
from ancestry_mmm.core.outcomes import FH_LTR_HORIZON_MONTHS

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
            horizon_months=FH_LTR_HORIZON_MONTHS,
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


class TestComparePeriods:
    """WP2E: explicit two-period comparison. Reuses `evaluate_period()`
    itself (called twice) - one calculation path, verified here by
    checking the comparison numbers agree with two direct
    `evaluate_period()` calls."""

    def test_happy_path_compares_two_weeks(self, trace, frame, meta):
        records = _valuation_records(WEEK_STARTS)
        request_a = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_WEEK,
            period_label=WEEK_STARTS[0],
            weekly_valuation_records=records,
        )
        request_b = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_WEEK,
            period_label=WEEK_STARTS[4],
            weekly_valuation_records=records,
        )
        comparison = OutcomeValuationReportingService().compare_periods(
            request_a, request_b
        )

        assert comparison.errors == []
        assert comparison.period_a.resolved_weeks == [WEEK_STARTS[0]]
        assert comparison.period_b.resolved_weeks == [WEEK_STARTS[4]]

        direct_a = OutcomeValuationReportingService().evaluate_period(request_a)
        direct_b = OutcomeValuationReportingService().evaluate_period(request_b)

        assert comparison.incremental_value is not None
        assert comparison.incremental_value.period_a_value == pytest.approx(
            direct_a.attribution.incremental_value_mean
        )
        assert comparison.incremental_value.period_b_value == pytest.approx(
            direct_b.attribution.incremental_value_mean
        )
        assert comparison.incremental_value.absolute_change == pytest.approx(
            direct_b.attribution.incremental_value_mean
            - direct_a.attribution.incremental_value_mean
        )

        assert comparison.spend is not None
        assert comparison.spend.absolute_change == pytest.approx(
            direct_b.attribution.spend - direct_a.attribution.spend
        )

    def test_period_objects_expose_underlying_resolved_weeks_for_the_waterfall(
        self, trace, frame, meta
    ):
        """WP2F's future waterfall needs the exact resolved week-lists
        each period bridges from/to - exposed here via `period_a`/
        `period_b`, not re-derivable only from the comparison deltas."""
        records = _valuation_records(WEEK_STARTS)
        request_a = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_QUARTER,
            period_label="2025-Q1",
            weekly_valuation_records=records,
        )
        request_b = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_WEEK,
            period_label=WEEK_STARTS[0],
            weekly_valuation_records=records,
        )
        comparison = OutcomeValuationReportingService().compare_periods(
            request_a, request_b
        )
        assert comparison.period_a.resolved_weeks == WEEK_STARTS
        assert comparison.period_b.resolved_weeks == [WEEK_STARTS[0]]

    def test_zero_period_a_value_makes_percentage_change_unavailable(
        self, trace, frame, meta
    ):
        zero_week_record = WeeklyOutcomeValuationRecord(
            valuation_kind=VALUATION_KIND_FH_LTR,
            market="UK",
            week=WEEK_STARTS[0],
            segment=SEGMENT,
            denominator_outcome_id="New",
            quality_status=STATE_OBSERVED_ZERO,
            aggregate_value=0.0,
            currency="GBP",
            horizon_months=FH_LTR_HORIZON_MONTHS,
        )
        records = [zero_week_record] + _valuation_records(WEEK_STARTS[1:])
        request_a = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_WEEK,
            period_label=WEEK_STARTS[0],
            weekly_valuation_records=records,
        )
        request_b = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_WEEK,
            period_label=WEEK_STARTS[4],
            weekly_valuation_records=records,
        )
        comparison = OutcomeValuationReportingService().compare_periods(
            request_a, request_b
        )

        assert comparison.incremental_value is not None
        assert comparison.incremental_value.period_a_value == pytest.approx(0.0)
        assert comparison.incremental_value.percentage_change is None
        assert (
            comparison.incremental_value.percentage_change_unavailable_reason
            is not None
        )
        assert (
            "zero" in comparison.incremental_value.percentage_change_unavailable_reason
        )

    def test_a_failed_period_leaves_comparisons_none_but_surfaces_its_error(
        self, trace, frame, meta
    ):
        records = _valuation_records(WEEK_STARTS[:-1])  # last week uncovered
        request_a = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_WEEK,
            period_label=WEEK_STARTS[0],
            weekly_valuation_records=records,
        )
        request_b = _base_request(
            trace,
            frame,
            meta,
            grain=PERIOD_GRAIN_WEEK,
            period_label=WEEK_STARTS[-1],
            weekly_valuation_records=records,
        )
        comparison = OutcomeValuationReportingService().compare_periods(
            request_a, request_b
        )

        assert comparison.incremental_value is None
        assert comparison.roi is None
        assert any(e.startswith("Period B:") for e in comparison.errors)
        assert comparison.period_a.attribution is not None
