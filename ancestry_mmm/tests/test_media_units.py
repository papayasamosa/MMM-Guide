"""Tests for core.media_units - CPA and media-unit/inflation calculations,
operating on plain curve DataFrames (the shared output shape of
core.predict.generate_channel_curve and
core.market_specific_predict.generate_market_channel_curve), so no PyMC or
posterior-params fixtures are needed here."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.market_config import ChannelMediaUnitConfig
from ancestry_mmm.core.media_units import (
    compute_cpa,
    cpa_stability_flags,
    equivalent_delivery,
    equivalent_response,
    extract_cost_per_unit_series,
    historical_cost_trend,
    response_unit_curve,
)


def _curve_df(spend, overall_response):
    return pd.DataFrame({"spend": spend, "overall_response": overall_response})


class TestComputeCpa:
    def test_average_cpa_is_spend_over_response(self):
        df = _curve_df([0.0, 100.0, 200.0], [0.0, 10.0, 15.0])
        out = compute_cpa(df)
        assert out["avg_cpa"].iloc[1] == pytest.approx(10.0)
        assert out["avg_cpa"].iloc[2] == pytest.approx(200.0 / 15.0)

    def test_average_cpa_is_nan_where_response_is_zero_or_negative(self):
        df = _curve_df([0.0, 100.0, 200.0], [0.0, -1.0, 5.0])
        out = compute_cpa(df)
        assert pd.isna(out["avg_cpa"].iloc[0])
        assert pd.isna(out["avg_cpa"].iloc[1])
        assert not pd.isna(out["avg_cpa"].iloc[2])

    def test_marginal_cpa_is_change_in_spend_over_change_in_response(self):
        df = _curve_df([0.0, 100.0, 300.0], [0.0, 10.0, 25.0])
        out = compute_cpa(df)
        assert pd.isna(out["marginal_cpa"].iloc[0])  # no preceding point
        assert out["marginal_cpa"].iloc[1] == pytest.approx(100.0 / 10.0)
        assert out["marginal_cpa"].iloc[2] == pytest.approx(200.0 / 15.0)

    def test_marginal_cpa_is_nan_when_response_does_not_increase(self):
        df = _curve_df([0.0, 100.0, 200.0], [0.0, 10.0, 10.0])
        out = compute_cpa(df)
        assert pd.isna(out["marginal_cpa"].iloc[2])

    def test_single_row_curve_has_all_nan_marginal_cpa(self):
        df = _curve_df([100.0], [10.0])
        out = compute_cpa(df)
        assert pd.isna(out["marginal_cpa"].iloc[0])

    def test_respects_a_custom_response_column(self):
        df = pd.DataFrame({"spend": [0.0, 100.0], "New_response": [0.0, 5.0]})
        out = compute_cpa(df, response_col="New_response")
        assert out["avg_cpa"].iloc[1] == pytest.approx(20.0)


class TestCpaStabilityFlags:
    def test_flags_flat_regions_of_the_curve(self):
        # Response rises steeply then flattens hard near the end (saturation).
        df = _curve_df([0, 100, 200, 300, 400], [0, 20, 38, 38.5, 38.51])
        flags = cpa_stability_flags(df)
        flagged_indices = {f["index"] for f in flags}
        assert 4 in flagged_indices  # the near-flat final step
        assert 1 not in flagged_indices  # the steep first step

    def test_no_flags_for_a_short_curve(self):
        assert cpa_stability_flags(_curve_df([0.0], [0.0])) == []

    def test_no_flags_when_response_never_changes(self):
        df = _curve_df([0.0, 100.0, 200.0], [5.0, 5.0, 5.0])
        assert cpa_stability_flags(df) == []


class TestExtractCostPerUnitSeries:
    def _config(self):
        return ChannelMediaUnitConfig(
            market="UK", channel="TV", spend_column="tv_spend", response_unit_column="tv_impressions",
        )

    def _df(self):
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=4, freq="W"),
            "market": ["UK", "UK", "Australia", "UK"],
            "tv_spend": [1000.0, 2000.0, 500.0, 0.0],
            "tv_impressions": [100.0, 250.0, 50.0, 0.0],
        })

    def test_computes_cost_per_unit_for_the_selected_market_only(self):
        result = extract_cost_per_unit_series(self._df(), "date", "market", "UK", self._config())
        assert len(result) == 3  # only UK rows
        assert result["cost_per_unit"].iloc[0] == pytest.approx(10.0)
        assert result["cost_per_unit"].iloc[1] == pytest.approx(8.0)

    def test_zero_media_units_gives_nan_not_a_divide_error(self):
        result = extract_cost_per_unit_series(self._df(), "date", "market", "UK", self._config())
        assert pd.isna(result["cost_per_unit"].iloc[2])  # the zero-spend/zero-units row

    def test_spend_only_config_raises(self):
        config = ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="tv_spend")
        with pytest.raises(ValueError, match="spend-only"):
            extract_cost_per_unit_series(self._df(), "date", "market", "UK", config)

    def test_missing_column_raises(self):
        config = ChannelMediaUnitConfig(
            market="UK", channel="TV", spend_column="tv_spend", response_unit_column="not_a_real_column",
        )
        with pytest.raises(ValueError, match="missing"):
            extract_cost_per_unit_series(self._df(), "date", "market", "UK", config)


class TestHistoricalCostTrend:
    def test_empty_series_returns_none_values(self):
        empty = pd.DataFrame({"date": [], "cost_per_unit": []})
        result = historical_cost_trend(empty, "date")
        assert result["yoy_inflation_pct"] is None
        assert result["avg_cost_per_unit"] is None
        assert result["indexed_trend"].empty

    def test_all_nan_series_returns_none_values(self):
        df = pd.DataFrame({"date": pd.date_range("2023-01-01", periods=3, freq="YS"), "cost_per_unit": [np.nan] * 3})
        result = historical_cost_trend(df, "date")
        assert result["yoy_inflation_pct"] is None

    def test_flat_cost_gives_zero_inflation(self):
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=3, freq="YS"),
            "cost_per_unit": [10.0, 10.0, 10.0],
        })
        result = historical_cost_trend(df, "date")
        assert result["yoy_inflation_pct"] == pytest.approx(0.0, abs=1e-9)
        assert result["avg_cost_per_unit"] == pytest.approx(10.0)

    def test_rising_cost_gives_positive_inflation(self):
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=3, freq="YS"),
            "cost_per_unit": [10.0, 11.0, 12.1],
        })
        result = historical_cost_trend(df, "date")
        assert result["yoy_inflation_pct"] == pytest.approx(10.0, rel=1e-2)

    def test_indexed_trend_starts_at_100(self):
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=2, freq="YS"),
            "cost_per_unit": [5.0, 6.0],
        })
        result = historical_cost_trend(df, "date")
        assert result["indexed_trend"]["indexed"].iloc[0] == pytest.approx(100.0)
        assert result["indexed_trend"]["indexed"].iloc[1] == pytest.approx(120.0)

    def test_single_year_has_no_yoy_but_has_average(self):
        df = pd.DataFrame({"date": pd.date_range("2020-06-01", periods=2, freq="W"), "cost_per_unit": [8.0, 9.0]})
        result = historical_cost_trend(df, "date")
        assert result["yoy_inflation_pct"] is None
        assert result["avg_cost_per_unit"] == pytest.approx(8.5)


class TestResponseUnitCurve:
    def test_media_units_is_spend_divided_by_cost_per_unit(self):
        df = _curve_df([0.0, 100.0, 250.0], [0.0, 10.0, 20.0])
        out = response_unit_curve(df, avg_cost_per_unit=5.0)
        np.testing.assert_allclose(out["media_units"], [0.0, 20.0, 50.0])

    def test_does_not_mutate_the_response_column(self):
        df = _curve_df([100.0], [10.0])
        out = response_unit_curve(df, avg_cost_per_unit=2.0)
        assert out["overall_response"].iloc[0] == pytest.approx(10.0)

    def test_zero_or_negative_cost_per_unit_raises(self):
        df = _curve_df([100.0], [10.0])
        with pytest.raises(ValueError):
            response_unit_curve(df, avg_cost_per_unit=0.0)
        with pytest.raises(ValueError):
            response_unit_curve(df, avg_cost_per_unit=-1.0)


class TestEquivalentDelivery:
    def test_multiplies_units_by_cost(self):
        assert equivalent_delivery(target_media_units=100.0, expected_future_cost_per_unit=5.0) == pytest.approx(500.0)

    def test_negative_inputs_raise(self):
        with pytest.raises(ValueError):
            equivalent_delivery(-1.0, 5.0)
        with pytest.raises(ValueError):
            equivalent_delivery(1.0, -5.0)


class TestEquivalentResponse:
    def test_interpolates_on_the_curve(self):
        df = _curve_df([0.0, 100.0, 200.0], [0.0, 10.0, 20.0])
        # target spend = 50 units x 1.0 cost/unit = 50 spend -> halfway between 0 and 10 -> 5
        result = equivalent_response(target_media_units=50.0, cost_per_unit=1.0, curve_df=df)
        assert result == pytest.approx(5.0)

    def test_clamps_beyond_the_curves_range(self):
        df = _curve_df([0.0, 100.0], [0.0, 10.0])
        # target spend way beyond the curve's max - np.interp clamps to the last value.
        result = equivalent_response(target_media_units=1000.0, cost_per_unit=1.0, curve_df=df)
        assert result == pytest.approx(10.0)

    def test_negative_inputs_raise(self):
        df = _curve_df([0.0, 100.0], [0.0, 10.0])
        with pytest.raises(ValueError):
            equivalent_response(-1.0, 1.0, df)
        with pytest.raises(ValueError):
            equivalent_response(1.0, -1.0, df)
