"""Tests for core.media_units - CPA and media-unit/inflation calculations,
operating on plain curve DataFrames (the shared output shape of
core.predict.generate_channel_curve and
core.market_specific_predict.generate_market_channel_curve), so no PyMC or
posterior-params fixtures are needed here."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_config import ChannelMediaUnitConfig
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.media_units import (
    CPA_INCREMENTAL_VS_OBSERVED,
    CPA_SPEND_SCOPES,
    compute_cpa,
    compute_cpa_by_product,
    cpa_scope_metadata,
    cpa_stability_flags,
    equivalent_delivery,
    equivalent_response,
    extract_cost_per_unit_series,
    historical_cost_trend,
    market_specific_cpa_table,
    response_unit_curve,
)
from ancestry_mmm.tests.conftest import pathway_strength_from_flat


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

    def test_default_overall_response_raises_on_a_genuinely_mixed_curve(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0], "overall_response": [0.0, 15.0],
            "fh_response": [0.0, 10.0], "dna_response": [0.0, 5.0],
        })
        with pytest.raises(ValueError, match="mixes Family History"):
            compute_cpa(df)

    def test_allow_mixed_bypasses_the_guard(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0], "overall_response": [0.0, 15.0],
            "fh_response": [0.0, 10.0], "dna_response": [0.0, 5.0],
        })
        out = compute_cpa(df, allow_mixed=True)
        assert out["avg_cpa"].iloc[1] == pytest.approx(100.0 / 15.0)

    def test_no_guard_when_dna_response_is_all_zero(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0], "overall_response": [0.0, 10.0],
            "fh_response": [0.0, 10.0], "dna_response": [0.0, 0.0],
        })
        out = compute_cpa(df)
        assert out["avg_cpa"].iloc[1] == pytest.approx(10.0)

    def test_explicit_response_col_does_not_need_allow_mixed(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0], "overall_response": [0.0, 15.0],
            "fh_response": [0.0, 10.0], "dna_response": [0.0, 5.0],
        })
        out = compute_cpa(df, response_col="dna_response")
        assert out["avg_cpa"].iloc[1] == pytest.approx(20.0)

    def test_column_prefix_names_the_output_columns(self):
        df = _curve_df([0.0, 100.0], [0.0, 10.0])
        out = compute_cpa(df, column_prefix="dna_")
        assert "dna_avg_cpa" in out.columns and "dna_marginal_cpa" in out.columns
        assert "avg_cpa" not in out.columns


class TestComputeCpaByProduct:
    def _mixed_curve(self):
        return pd.DataFrame({
            "spend": [0.0, 100.0, 200.0], "overall_response": [0.0, 15.0, 27.0],
            "fh_response": [0.0, 10.0, 17.0], "dna_response": [0.0, 5.0, 10.0],
        })

    def test_fh_only_curve_gets_plain_avg_cpa_no_dna_columns(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0], "overall_response": [0.0, 10.0],
            "fh_response": [0.0, 10.0], "dna_response": [0.0, 0.0],
        })
        out = compute_cpa_by_product(df)
        assert out["avg_cpa"].iloc[1] == pytest.approx(10.0)
        assert "dna_avg_cpa" not in out.columns

    def test_mixed_curve_gets_both_fh_and_dna_cpa_never_combined(self):
        out = compute_cpa_by_product(self._mixed_curve())
        assert out["avg_cpa"].iloc[1] == pytest.approx(100.0 / 10.0)
        assert out["dna_avg_cpa"].iloc[1] == pytest.approx(100.0 / 5.0)
        assert out["marginal_cpa"].iloc[2] == pytest.approx(100.0 / 7.0)
        assert out["dna_marginal_cpa"].iloc[2] == pytest.approx(100.0 / 5.0)

    def test_curve_without_fh_response_falls_back_to_overall_response(self):
        df = _curve_df([0.0, 100.0], [0.0, 10.0])
        out = compute_cpa_by_product(df)
        assert out["avg_cpa"].iloc[1] == pytest.approx(10.0)

    def test_cost_per_x_aliases_match_the_bare_names(self):
        # PR E.1 requires named denominators (cost_per_fh_gsa/cost_per_fh_signup/
        # cost_per_dna_kit) - kept as aliases of the existing avg_cpa/
        # dna_avg_cpa/fh_signup_avg_cpa columns, never a separate computation
        # that could silently diverge from them.
        out = compute_cpa_by_product(self._mixed_curve())
        assert np.array_equal(out["cost_per_fh_gsa"].to_numpy(), out["avg_cpa"].to_numpy(), equal_nan=True)
        assert np.array_equal(out["cost_per_dna_kit"].to_numpy(), out["dna_avg_cpa"].to_numpy(), equal_nan=True)

    def test_signup_response_gets_its_own_named_denominator_never_mixed_with_gsa(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0, 200.0], "overall_response": [0.0, 25.0, 47.0],
            "fh_response": [0.0, 10.0, 17.0], "fh_signup_response": [0.0, 15.0, 30.0],
            "dna_response": [0.0, 0.0, 0.0],
        })
        out = compute_cpa_by_product(df)
        assert out["cost_per_fh_gsa"].iloc[1] == pytest.approx(100.0 / 10.0)
        assert out["cost_per_fh_signup"].iloc[1] == pytest.approx(100.0 / 15.0)
        # The two denominators must never be equal to a CPA computed against
        # their sum - proof they're genuinely separate, not coincidentally
        # the same number.
        assert out["cost_per_fh_gsa"].iloc[1] != pytest.approx(100.0 / 25.0)
        assert out["cost_per_fh_signup"].iloc[1] != pytest.approx(100.0 / 25.0)
        assert "cost_per_dna_kit" not in out.columns  # no non-trivial dna_response here

    def test_curve_with_no_signup_response_has_no_signup_cpa_columns(self):
        out = compute_cpa_by_product(self._mixed_curve())
        assert "cost_per_fh_signup" not in out.columns
        assert "fh_signup_avg_cpa" not in out.columns

    def test_channel_incremental_aliases_match_the_bare_names(self):
        # PR E.2 #8 - the explicit-spend-scope names must never silently
        # diverge from the underlying avg_cpa/marginal_cpa numbers.
        out = compute_cpa_by_product(self._mixed_curve())
        assert np.array_equal(
            out["channel_incremental_cost_per_fh_gsa"].to_numpy(), out["avg_cpa"].to_numpy(), equal_nan=True,
        )
        assert np.array_equal(
            out["channel_incremental_marginal_cost_per_fh_gsa"].to_numpy(), out["marginal_cpa"].to_numpy(), equal_nan=True,
        )
        assert np.array_equal(
            out["channel_incremental_cost_per_dna_kit"].to_numpy(), out["dna_avg_cpa"].to_numpy(), equal_nan=True,
        )

    def test_channel_incremental_signup_alias_present_only_with_signup_response(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0], "overall_response": [0.0, 25.0],
            "fh_response": [0.0, 10.0], "fh_signup_response": [0.0, 15.0], "dna_response": [0.0, 0.0],
        })
        out = compute_cpa_by_product(df)
        assert np.array_equal(
            out["channel_incremental_cost_per_fh_signup"].to_numpy(), out["fh_signup_avg_cpa"].to_numpy(), equal_nan=True,
        )
        assert "channel_incremental_cost_per_fh_signup" not in compute_cpa_by_product(self._mixed_curve()).columns


class TestCpaScopeMetadata:
    """Required test case 14 (PR E.2): every CPA output must be presentable
    with denominator and spend-scope metadata."""

    def test_returns_all_required_fields(self):
        meta = cpa_scope_metadata(
            denominator_metric="fh_gsa", included_outcome_ids=["fh_new_gsa"],
            spend_scope="whole_plan", included_channels=["TV_Brand"], market="UK",
            time_window="2024-01", incremental_vs_observed="incremental",
        )
        assert meta == {
            "denominator_metric": "fh_gsa",
            "included_outcome_ids": ["fh_new_gsa"],
            "spend_scope": "whole_plan",
            "included_channels": ["TV_Brand"],
            "market": "UK",
            "time_window": "2024-01",
            "incremental_vs_observed": "incremental",
        }

    def test_optional_fields_default_to_none(self):
        meta = cpa_scope_metadata(denominator_metric="fh_gsa", included_outcome_ids=["fh_new_gsa"], spend_scope="channel_incremental")
        assert meta["included_channels"] is None
        assert meta["market"] is None
        assert meta["time_window"] is None
        assert meta["incremental_vs_observed"] == "incremental"

    def test_invalid_spend_scope_raises(self):
        with pytest.raises(ValueError, match="spend_scope"):
            cpa_scope_metadata(denominator_metric="fh_gsa", included_outcome_ids=[], spend_scope="not_a_real_scope")

    def test_invalid_incremental_vs_observed_raises(self):
        with pytest.raises(ValueError, match="incremental_vs_observed"):
            cpa_scope_metadata(
                denominator_metric="fh_gsa", included_outcome_ids=[], spend_scope="whole_plan",
                incremental_vs_observed="not_a_real_value",
            )

    def test_all_documented_spend_scopes_are_accepted(self):
        for scope in CPA_SPEND_SCOPES:
            cpa_scope_metadata(denominator_metric="fh_gsa", included_outcome_ids=[], spend_scope=scope)

    def test_all_documented_incremental_vs_observed_values_are_accepted(self):
        for value in CPA_INCREMENTAL_VS_OBSERVED:
            cpa_scope_metadata(
                denominator_metric="fh_gsa", included_outcome_ids=[], spend_scope="whole_plan",
                incremental_vs_observed=value,
            )


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

    def test_default_overall_response_raises_on_a_genuinely_mixed_curve(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0], "overall_response": [0.0, 15.0],
            "fh_response": [0.0, 10.0], "dna_response": [0.0, 5.0],
        })
        with pytest.raises(ValueError, match="mixes Family History"):
            equivalent_response(50.0, 1.0, df)

    def test_allow_mixed_bypasses_the_guard(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0], "overall_response": [0.0, 15.0],
            "fh_response": [0.0, 10.0], "dna_response": [0.0, 5.0],
        })
        result = equivalent_response(50.0, 1.0, df, allow_mixed=True)
        assert result == pytest.approx(7.5)

    def test_explicit_response_col_does_not_need_allow_mixed(self):
        df = pd.DataFrame({
            "spend": [0.0, 100.0], "overall_response": [0.0, 15.0],
            "fh_response": [0.0, 10.0], "dna_response": [0.0, 5.0],
        })
        result = equivalent_response(50.0, 1.0, df, response_col="dna_response")
        assert result == pytest.approx(2.5)


class TestMarketSpecificCpaTable:
    MARKETS = ["UK", "Australia"]
    SEGMENTS = ["New", "DNA_CrossSell"]
    CHANNELS = ["TV", "Search"]

    @pytest.fixture
    def meta(self) -> FHModelMeta:
        return FHModelMeta(
            markets=self.MARKETS, outcome_ids=self.SEGMENTS, channels=self.CHANNELS,
            dna_channels=["TV"], dna_channel_idx=[0], non_dna_idx=[1],
            dna_outcome_id="DNA_CrossSell", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
        )

    @pytest.fixture
    def params(self) -> FHMarketSpecificPosteriorParams:
        return FHMarketSpecificPosteriorParams(
            decay_rate={"TV": 0.5, "Search": 0.3},
            hill_K={m: {"TV": 1000.0, "Search": 500.0} for m in self.MARKETS},
            hill_S={"TV": 1.0, "Search": 1.0},
            beta={m: {s: {c: 0.1 for c in self.CHANNELS} for s in self.SEGMENTS} for m in self.MARKETS},
            pathway_strength=pathway_strength_from_flat({"New": 0.1, "DNA_CrossSell": 1.0}, "TV"), promo_coef={"New": 0.1, "DNA_CrossSell": 0.1},
            market_offset={m: {"New": 0.0, "DNA_CrossSell": 0.0} for m in self.MARKETS},
            intercept={"New": 3.0, "DNA_CrossSell": 2.0}, trend_coef={"New": 0.0, "DNA_CrossSell": 0.0},
            gamma_fourier={"New": np.zeros(6), "DNA_CrossSell": np.zeros(6)},
            alpha={"New": 5.0, "DNA_CrossSell": 5.0}, control_coef={}, outcome_control_coef={},
        )

    def test_covers_every_market_and_channel_by_default(self, meta, params):
        table = market_specific_cpa_table(meta, params, n_points=5)
        assert set(table["market"].unique()) == set(self.MARKETS)
        assert set(table["channel"].unique()) == set(self.CHANNELS)
        assert len(table) == len(self.MARKETS) * len(self.CHANNELS) * 5

    def test_includes_cpa_columns(self, meta, params):
        table = market_specific_cpa_table(meta, params, n_points=5)
        assert {"avg_cpa", "marginal_cpa", "overall_response", "spend"} <= set(table.columns)

    def test_restricts_to_the_requested_markets_and_channels(self, meta, params):
        table = market_specific_cpa_table(meta, params, markets=["UK"], channels=["TV"], n_points=3)
        assert set(table["market"].unique()) == {"UK"}
        assert set(table["channel"].unique()) == {"TV"}
        assert len(table) == 3

    def test_empty_selection_gives_an_empty_dataframe_with_expected_columns(self, meta, params):
        table = market_specific_cpa_table(meta, params, markets=[], channels=[])
        assert table.empty
        assert "avg_cpa" in table.columns
