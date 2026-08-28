"""Tests for display-only formatting helpers (ancestry_mmm.utils.display).

These must never mutate the values/dtypes they're given - only control how
something is shown - so several tests assert the original input is
unchanged after formatting.
"""

import pandas as pd

from ancestry_mmm.utils.display import (
    DATE_COLUMN_FORMAT,
    currency_symbol,
    format_currency,
    format_date,
    format_number,
    format_roi_statement,
    readable_label,
    readable_labels,
    model_input_display_label,
    display_enum_options,
    display_enum_frame,
    restore_enum_frame,
    dataframe_column_config,
    OPERATION_LABELS,
    OPERATION_DESCRIPTIONS,
)
from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.data.pipeline import SUPPORTED_OPS


class TestFormatDate:
    def test_formats_to_d_mmm_yy(self):
        assert format_date(pd.Timestamp("2023-01-02")) == "2 Jan 23"

    def test_formats_double_digit_day(self):
        assert format_date(pd.Timestamp("2023-12-18")) == "18 Dec 23"

    def test_accepts_python_date(self):
        import datetime

        assert format_date(datetime.date(2024, 3, 5)) == "5 Mar 24"

    def test_accepts_iso_string(self):
        assert format_date("2023-01-02") == "2 Jan 23"

    def test_none_is_empty_string(self):
        assert format_date(None) == ""

    def test_nat_is_empty_string(self):
        assert format_date(pd.NaT) == ""

    def test_does_not_mutate_input(self):
        original = pd.Timestamp("2023-01-02")
        format_date(original)
        assert original == pd.Timestamp("2023-01-02")

    def test_date_column_format_constant_matches_helper_semantics(self):
        # "D" = day no leading zero, "MMM" = short month, "YY" = 2-digit year -
        # the same convention format_date() implements by hand. Uppercase "YY"
        # is required: Streamlit's DateColumn silently renders a 4-digit year
        # for lowercase "yy" (verified against a live Streamlit 1.59 instance).
        assert DATE_COLUMN_FORMAT == "D MMM YY"


class TestFormatNumber:
    def test_integer_gets_thousands_separator(self):
        assert format_number(55008) == "55,008"

    def test_whole_number_float_has_no_trailing_zero(self):
        assert format_number(15020.0) == "15,020"

    def test_decimal_keeps_two_places(self):
        assert format_number(79.023) == "79.02"

    def test_small_decimal(self):
        assert format_number(12982) == "12,982"

    def test_none_is_empty_string(self):
        assert format_number(None) == ""

    def test_nan_is_empty_string(self):
        assert format_number(float("nan")) == ""

    def test_negative_number(self):
        assert format_number(-1234) == "-1,234"

    def test_bool_is_not_formatted_as_number(self):
        assert format_number(True) == "True"


class TestCurrencySymbol:
    def test_known_codes(self):
        assert currency_symbol("GBP") == "£"
        assert currency_symbol("USD") == "$"
        assert currency_symbol("EUR") == "€"

    def test_case_insensitive(self):
        assert currency_symbol("gbp") == "£"

    def test_unknown_code_falls_back_to_code_itself(self):
        assert currency_symbol("NZD") == "NZD "

    def test_empty_or_none_is_empty_string(self):
        assert currency_symbol("") == ""
        assert currency_symbol(None) == ""


class TestFormatCurrency:
    def test_formats_with_symbol_and_thousands_separator(self):
        assert format_currency(1234.5, "GBP") == "£1,234.50"

    def test_unknown_currency_falls_back_to_code_prefix(self):
        assert format_currency(10, "NZD") == "NZD 10.00"

    def test_none_is_empty_string(self):
        assert format_currency(None, "GBP") == ""

    def test_nan_is_empty_string(self):
        assert format_currency(float("nan"), "GBP") == ""

    def test_does_not_mutate_input(self):
        value = 42.0
        format_currency(value, "GBP")
        assert value == 42.0


class TestFormatRoiStatement:
    def test_typical_roi(self):
        assert format_roi_statement(2.5, "GBP") == "£2.50 returned per £1 spent"

    def test_none_roi_is_empty_string(self):
        assert format_roi_statement(None, "GBP") == ""

    def test_nan_roi_is_empty_string(self):
        assert format_roi_statement(float("nan"), "GBP") == ""

    def test_unknown_currency_falls_back_to_code_prefix(self):
        assert format_roi_statement(1.5, "NZD") == "NZD 1.50 returned per NZD 1 spent"


class TestReadableLabel:
    def test_replaces_underscores_with_spaces(self):
        assert readable_label("TV_Brand") == "TV Brand"

    def test_multiple_underscores(self):
        assert readable_label("GSA_DNA_CrossSell") == "GSA DNA CrossSell"
        assert readable_label("DNA_Kit_Price") == "DNA Kit Price"
        assert readable_label("Promo_New") == "Promo New"

    def test_no_underscores_is_unchanged(self):
        assert readable_label("date") == "date"

    def test_non_string_passthrough(self):
        assert readable_label(42) == 42

    def test_readable_labels_maps_each_name(self):
        mapping = readable_labels(["TV_Brand", "Search_NonBrand"])
        assert mapping == {"TV_Brand": "TV Brand", "Search_NonBrand": "Search NonBrand"}

    def test_common_enum_values_have_analyst_labels(self):
        assert readable_label("paid_search_cap") == "Paid Search cap"
        assert readable_label("missing_expected") == "Expected data missing"
        assert readable_label("partially_pooled") != "partially_pooled"
        assert readable_label("brand_upper") == "Brand / upper funnel"
        assert readable_label("performance_lower") == "Performance / lower funnel"

    def test_enum_editor_round_trip_preserves_raw_values(self):
        original = pd.DataFrame({"role": ["paid_search_cap", "organic_search_capture"]})
        values = {"role": ("paid_search_cap", "organic_search_capture")}
        displayed = display_enum_frame(original, values)
        assert displayed["role"].tolist() == [
            "Paid Search cap",
            "Organic search",
        ]
        assert display_enum_options(values["role"]) == displayed["role"].tolist()
        edited = restore_enum_frame(displayed, values.keys(), values)
        assert edited.equals(original)
        assert original["role"].tolist() == [
            "paid_search_cap",
            "organic_search_capture",
        ]


class TestModelInputDisplayLabel:
    """UI-WP7: the shared presentation-layer label resolver for model
    inputs. Stable IDs (activity_id, model_input_column) are never
    affected - only what's shown."""

    def _activity(self, **overrides):
        defaults = dict(
            activity_id="UK:tv_spend",
            channel="TV_Brand",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="test",
            market="UK",
        )
        defaults.update(overrides)
        return ActivityDefinition(**defaults)

    def test_no_governed_metadata_falls_back_to_readable_label(self):
        assert model_input_display_label("tv_spend") == readable_label("tv_spend")

    def test_no_matching_activity_falls_back_to_readable_label(self):
        definitions = [self._activity(model_input_column="digital_spend")]
        assert model_input_display_label(
            "tv_spend", activity_definitions=definitions
        ) == readable_label("tv_spend")

    def test_matched_activity_uses_reporting_channel(self):
        definitions = [self._activity(model_input_column="tv_spend")]
        assert (
            model_input_display_label("tv_spend", activity_definitions=definitions)
            == "TV Brand"
        )

    def test_matched_activity_adds_platform_and_campaign_context(self):
        definitions = [
            self._activity(
                model_input_column="social_spend",
                channel="Social",
                platform="Meta",
                campaign_type="Prospecting",
            )
        ]
        assert (
            model_input_display_label("social_spend", activity_definitions=definitions)
            == "Social (Meta / Prospecting)"
        )

    def test_resolved_model_input_column_falls_back_to_channel(self):
        # ActivityDefinition.resolved_model_input_column falls back to
        # `channel` when `model_input_column` is unset - the resolver must
        # match on the same resolved column, not the raw (possibly blank)
        # field, matching core.activities' own resolution rule.
        definitions = [self._activity(channel="tv_spend")]
        assert model_input_display_label(
            "tv_spend", activity_definitions=definitions
        ) == readable_label("tv_spend")

    def test_prefers_exact_market_row_over_wildcard_row(self):
        definitions = [
            self._activity(
                model_input_column="tv_spend", market="*", channel="Generic_TV"
            ),
            self._activity(
                model_input_column="tv_spend", market="UK", channel="UK_TV_Brand"
            ),
        ]
        assert (
            model_input_display_label(
                "tv_spend", activity_definitions=definitions, market="UK"
            )
            == "UK TV Brand"
        )

    def test_accepts_plain_dict_definitions(self):
        definitions = [
            {
                "model_input_column": "tv_spend",
                "channel": "TV_Brand",
                "market": "UK",
            }
        ]
        assert (
            model_input_display_label("tv_spend", activity_definitions=definitions)
            == "TV Brand"
        )

    def test_never_mutates_the_stable_column_name(self):
        definitions = [self._activity(model_input_column="tv_spend")]
        label = model_input_display_label("tv_spend", activity_definitions=definitions)
        assert label != "tv_spend"
        assert definitions[0].model_input_column == "tv_spend"


class TestDataframeColumnConfig:
    def test_column_config_is_display_only(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2023-01-01", periods=3),
                "TV_Brand": [1.0, 2.0, 3.0],
                "market": ["UK", "AU", "CA"],
            }
        )
        original_columns = list(df.columns)
        original_dtypes = df.dtypes.copy()

        config = dataframe_column_config(df)

        # Underlying dataframe is untouched.
        assert list(df.columns) == original_columns
        assert (df.dtypes == original_dtypes).all()
        assert set(config.keys()) == set(original_columns)

    def test_date_column_uses_d_mmm_yy_format(self):
        df = pd.DataFrame({"date": pd.date_range("2023-01-01", periods=2)})
        config = dataframe_column_config(df)
        assert config["date"]["type_config"]["format"] == DATE_COLUMN_FORMAT

    def test_numeric_column_is_right_aligned_and_localized(self):
        df = pd.DataFrame({"spend": [1.0, 2.0]})
        config = dataframe_column_config(df)
        assert config["spend"]["alignment"] == "right"
        assert config["spend"]["type_config"]["format"] == "localized"

    def test_text_column_is_left_aligned(self):
        df = pd.DataFrame({"market": ["UK", "AU"]})
        config = dataframe_column_config(df)
        assert config["market"]["alignment"] == "left"

    def test_labels_are_readable(self):
        df = pd.DataFrame({"TV_Brand": [1.0]})
        config = dataframe_column_config(df)
        assert config["TV_Brand"]["label"] == "TV Brand"

    def test_label_overrides_take_precedence(self):
        df = pd.DataFrame({"TV_Brand": [1.0]})
        config = dataframe_column_config(df, label_overrides={"TV_Brand": "TV (Brand)"})
        assert config["TV_Brand"]["label"] == "TV (Brand)"

    def test_bool_column_is_checkbox(self):
        df = pd.DataFrame({"is_dna": [True, False]})
        config = dataframe_column_config(df)
        assert config["is_dna"]["type_config"]["type"] == "checkbox"


class TestOperationLabels:
    def test_every_supported_op_has_a_label(self):
        for op in SUPPORTED_OPS:
            assert op in OPERATION_LABELS

    def test_every_supported_op_has_a_description(self):
        for op in SUPPORTED_OPS:
            assert op in OPERATION_DESCRIPTIONS
            assert OPERATION_DESCRIPTIONS[op]  # non-empty

    def test_labels_are_human_readable(self):
        assert OPERATION_LABELS["rename_column"] == "Rename column"
        assert OPERATION_LABELS["calculated_column"] == "Calculated column"
