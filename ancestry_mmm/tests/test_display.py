"""Tests for display-only formatting helpers (ancestry_mmm.utils.display).

These must never mutate the values/dtypes they're given - only control how
something is shown - so several tests assert the original input is
unchanged after formatting.
"""

import pandas as pd

from ancestry_mmm.utils.display import (
    DATE_COLUMN_FORMAT,
    format_date,
    format_number,
    readable_label,
    readable_labels,
    dataframe_column_config,
    OPERATION_LABELS,
    OPERATION_DESCRIPTIONS,
)
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


class TestDataframeColumnConfig:
    def test_column_config_is_display_only(self):
        df = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=3),
            "TV_Brand": [1.0, 2.0, 3.0],
            "market": ["UK", "AU", "CA"],
        })
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
