"""Tests for ancestry_mmm.data.loader.detect_column_types - previously had no
dedicated test file (PR 97A), covered only incidentally through pages that
call it inline (e.g. pages/10_Channel_Media_Units.py).

Also locks in a fix discovered while writing these tests: this environment's
pandas (3.0.3) defaults plain Python string columns - including what
pd.read_csv produces for text columns, the actual production path via
load_file - to pd.StringDtype() ("str"), not the legacy numpy "object"
dtype. detect_column_types's date- and categorical-detection branches used
to check `dtype == "object"` only, which silently missed both a CSV's date
column (never attempted pd.to_datetime, so it only fell back to a date-hint
in the column name) and any plain string column at all under pandas 3.
Both branches now use pd.api.types.is_string_dtype, which covers "object",
the new "str" dtype, and (for the categorical branch, kept as an explicit
extra check) any pd.CategoricalDtype regardless of its category value type.

Also locks in a follow-up fix for a regression the above fix introduced
(flagged in PR #107 review): is_string_dtype inspects column content, not
just dtype, so it returns False for object-dtype columns holding real
date/Timestamp objects rather than strings - the date-detection branch
silently stopped attempting pd.to_datetime on those. An explicit
dtype == "object" check is retained alongside is_string_dtype to cover
them. The pandas-3-only regression test above was also replaced with one
that constructs its StringDtype column explicitly, so it exercises the same
gap regardless of whether the test environment runs pandas 2.x or 3.x.
"""

import datetime

import pandas as pd

from ancestry_mmm.data.loader import detect_column_types


def _frame():
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=4, freq="W"),
            "TV_Brand_spend": [100.0, 150.0, 200.0, 250.0],
            "fh_new_gsa": [10, 12, 14, 16],
            "market": ["UK", "UK", "AU", "AU"],
        }
    )


def test_datetime_column_is_detected_as_date():
    result = detect_column_types(_frame())
    assert "date" in result["date"]


def test_date_hint_in_name_is_detected_even_without_datetime_dtype():
    df = pd.DataFrame({"period": ["p1", "p2"], "value": [1, 2]})
    result = detect_column_types(df)
    assert "period" in result["date"]


def test_string_dtype_date_column_is_detected_without_a_name_hint():
    """Regression guard: a StringDtype date column (a name with no date
    hint) must still be parsed and classified as date, not silently skipped
    because its dtype isn't "object". The StringDtype column is constructed
    explicitly rather than relying on pd.read_csv's ambient, pandas-version-
    dependent output dtype, so this exercises the gap on both pandas 2.x
    (read_csv defaults text columns to "object") and pandas>=3
    (read_csv defaults text columns to StringDtype)."""
    df = pd.DataFrame(
        {
            "as_of": pd.array(["2026-01-01", "2026-01-08"], dtype="string"),
            "value": [10, 12],
        }
    )
    assert isinstance(df["as_of"].dtype, pd.StringDtype)
    result = detect_column_types(df)
    assert "as_of" in result["date"]


def test_object_dtype_date_objects_column_is_detected_without_a_name_hint():
    """Regression guard for the P2 finding on PR #107: is_string_dtype
    returns False for object-dtype columns holding real date/Timestamp
    objects (not strings), since it inspects content rather than just
    dtype. The explicit dtype == "object" check must still trigger the
    pd.to_datetime attempt for these."""
    df = pd.DataFrame(
        {
            "as_of": pd.Series(
                [datetime.date(2026, 1, 1), datetime.date(2026, 1, 8)], dtype=object
            ),
            "value": [10, 12],
        }
    )
    assert df["as_of"].dtype == object
    result = detect_column_types(df)
    assert "as_of" in result["date"]


def test_object_dtype_timestamp_objects_column_is_detected_without_a_name_hint():
    df = pd.Series(
        [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-08")], dtype=object
    )
    df = pd.DataFrame({"as_of": df, "value": [10, 12]})
    assert df["as_of"].dtype == object
    result = detect_column_types(df)
    assert "as_of" in result["date"]


def test_numeric_spend_column_is_detected_as_potential_media():
    result = detect_column_types(_frame())
    assert "TV_Brand_spend" in result["numeric"]
    assert "TV_Brand_spend" in result["potential_media"]


def test_numeric_target_column_is_detected_as_potential_target():
    result = detect_column_types(_frame())
    assert "fh_new_gsa" in result["numeric"]
    assert "fh_new_gsa" in result["potential_target"]


def test_string_column_is_detected_as_categorical():
    """market is a plain Python string column - under this pandas version
    that is dtype "str" (pd.StringDtype), not the legacy "object" dtype;
    both must be classified as categorical."""
    result = detect_column_types(_frame())
    assert "market" in result["categorical"]
    assert "market" in result["potential_market"]


def test_explicit_object_dtype_column_is_still_detected_as_categorical():
    df = pd.DataFrame({"market": pd.array(["UK", "AU"], dtype=object)})
    result = detect_column_types(df)
    assert "market" in result["categorical"]


def test_pandas_categorical_dtype_column_is_detected_as_categorical():
    """Regression guard for the is_categorical_dtype -> isinstance(...,
    pd.CategoricalDtype) fix - a real pd.Categorical dtype (not just a
    string dtype) must still be classified as categorical."""
    df = pd.DataFrame(
        {
            "region": pd.Categorical(["North", "South", "North", "South"]),
        }
    )
    result = detect_column_types(df)
    assert "region" in result["categorical"]


def test_dna_and_promo_hints_are_detected_on_numeric_columns():
    df = pd.DataFrame(
        {
            "DNA_Media_spend": [1.0, 2.0],
            "promo_flag": [0, 1],
        }
    )
    result = detect_column_types(df)
    assert "DNA_Media_spend" in result["potential_dna"]
    assert "promo_flag" in result["potential_promo"]
