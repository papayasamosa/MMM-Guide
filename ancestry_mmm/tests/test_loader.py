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
import io

import pandas as pd

from ancestry_mmm.core.coverage import SourceVersion, compute_checksum
from ancestry_mmm.data.loader import (
    detect_column_types,
    load_file,
    load_file_with_source_version,
)


class _FakeUploadedFile(io.BytesIO):
    """Minimal stand-in for Streamlit's `UploadedFile`: an `io.BytesIO`
    with a `.name` attribute, exposing `.getvalue()` without consuming the
    read position `pd.read_csv`/`read_excel`/`read_parquet` use - matches
    the real `UploadedFile`'s contract `load_file_with_source_version`
    depends on."""

    def __init__(self, name: str, data: bytes):
        super().__init__(data)
        self.name = name


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


# ---------------------------------------------------------------------------
# REQ-COVERAGE-001 S3/S6 (WP3 Phase 2): Parquet/XLSM import support, and
# immutable SourceVersion capture from a real upload's raw bytes.
# ---------------------------------------------------------------------------


def _csv_upload(name: str = "media.csv") -> _FakeUploadedFile:
    df = _frame()
    return _FakeUploadedFile(name, df.to_csv(index=False).encode())


def _parquet_upload(name: str = "media.parquet") -> _FakeUploadedFile:
    df = _frame()
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return _FakeUploadedFile(name, buf.getvalue())


def _xlsm_upload(name: str = "media.xlsm") -> _FakeUploadedFile:
    df = _frame()
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return _FakeUploadedFile(name, buf.getvalue())


class TestParquetAndXlsmSupport:
    def test_parquet_file_loads(self):
        df, err = load_file(_parquet_upload())
        assert err is None
        assert df is not None
        assert list(df.columns) == list(_frame().columns)

    def test_xlsm_file_loads(self):
        df, err = load_file(_xlsm_upload())
        assert err is None
        assert df is not None
        assert list(df.columns) == list(_frame().columns)

    def test_still_unsupported_format_rejected(self):
        df, err = load_file(_FakeUploadedFile("media.json", b"{}"))
        assert df is None
        assert "Unsupported file format" in err


class TestLoadFileWithSourceVersion:
    def test_returns_a_source_version_with_correct_checksum(self):
        upload = _csv_upload()
        raw_bytes = upload.getvalue()
        upload.seek(0)
        df, source_version, err = load_file_with_source_version(upload, "media")
        assert err is None
        assert df is not None
        assert source_version.source_id == "media"
        assert source_version.version == 1
        assert source_version.checksum == compute_checksum(raw_bytes)
        assert source_version.size_bytes == len(raw_bytes)
        assert source_version.original_filename == "media.csv"

    def test_no_source_version_produced_on_parse_failure(self):
        df, source_version, err = load_file_with_source_version(
            _FakeUploadedFile("media.json", b"{}"), "media"
        )
        assert df is None
        assert source_version is None
        assert err is not None

    def test_version_increments_from_existing_history(self):
        existing = [
            SourceVersion(
                source_id="media",
                version=1,
                original_filename="media_v1.csv",
                checksum=compute_checksum(b"v1"),
                size_bytes=2,
                uploaded_at="2026-08-01T00:00:00+00:00",
                parsed_representation_version="pandas-test",
            ),
            SourceVersion(
                source_id="media",
                version=2,
                original_filename="media_v2.csv",
                checksum=compute_checksum(b"v2"),
                size_bytes=2,
                uploaded_at="2026-08-02T00:00:00+00:00",
                parsed_representation_version="pandas-test",
            ),
        ]
        _df, source_version, _err = load_file_with_source_version(
            _csv_upload(), "media", existing
        )
        assert source_version.version == 3

    def test_different_source_id_starts_at_version_one_even_with_other_history(self):
        existing = [
            SourceVersion(
                source_id="outcomes",
                version=5,
                original_filename="outcomes.csv",
                checksum=compute_checksum(b"x"),
                size_bytes=1,
                uploaded_at="2026-08-01T00:00:00+00:00",
                parsed_representation_version="pandas-test",
            ),
        ]
        _df, source_version, _err = load_file_with_source_version(
            _csv_upload(), "media", existing
        )
        assert source_version.version == 1

    def test_parsed_representation_version_records_pandas_version(self):
        _df, source_version, _err = load_file_with_source_version(
            _csv_upload(), "media"
        )
        assert (
            source_version.parsed_representation_version == f"pandas-{pd.__version__}"
        )

    def test_parquet_upload_produces_a_valid_source_version(self):
        upload = _parquet_upload()
        raw_bytes = upload.getvalue()
        upload.seek(0)
        df, source_version, err = load_file_with_source_version(upload, "media")
        assert err is None
        assert df is not None
        assert source_version.checksum == compute_checksum(raw_bytes)
