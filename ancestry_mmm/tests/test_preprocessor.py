"""Tests for data.preprocessor.prepare_fh_modeling_frame's dna_kit_outcomes
parameter (docs/outcomes.md, docs/dna_fh_causal_structure.md) - the frame-
building extension that lets DNA-product segments join a fit alongside the
Family History segments in ModelSpec.segment_outcomes, without changing
ModelSpec's own shape."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame


@pytest.fixture
def df() -> pd.DataFrame:
    n = 10
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="W"),
        "market": ["UK"] * n,
        "TV_Brand": np.linspace(100.0, 1000.0, n),
        "GSA_New": np.arange(10, 10 + n, dtype=float),
        "DNA_Kit_New_Customer": np.arange(50, 50 + n, dtype=float),
        "DNA_Kit_Existing_FH_Customer": np.arange(20, 20 + n, dtype=float),
        "Promo_DNA": np.zeros(n),
        "DNA_Kit_Price": np.full(n, 79.0),
    })


@pytest.fixture
def spec() -> ModelSpec:
    return ModelSpec(
        date_col="date", market_col="market", markets=["UK"],
        segment_outcomes={"New": "GSA_New"}, channels=["TV_Brand"],
    )


class TestPrepareFhModelingFrameWithoutDnaKitOutcomes:
    def test_omitting_the_argument_behaves_exactly_as_before(self, df, spec):
        frame = prepare_fh_modeling_frame(df, spec)
        assert frame["segments"] == ["New"]
        assert frame["Y"].shape == (10, 1)

    def test_explicit_none_is_the_same_as_omitting_it(self, df, spec):
        frame_none = prepare_fh_modeling_frame(df, spec, dna_kit_outcomes=None)
        frame_omitted = prepare_fh_modeling_frame(df, spec)
        assert frame_none["segments"] == frame_omitted["segments"]

    def test_empty_dict_is_the_same_as_omitting_it(self, df, spec):
        frame = prepare_fh_modeling_frame(df, spec, dna_kit_outcomes={})
        assert frame["segments"] == ["New"]


class TestPrepareFhModelingFrameWithDnaKitOutcomes:
    def test_dna_kit_segments_are_appended_after_fh_segments(self, df, spec):
        frame = prepare_fh_modeling_frame(
            df, spec, dna_kit_outcomes={"New Customer": "DNA_Kit_New_Customer", "Existing FH Customer": "DNA_Kit_Existing_FH_Customer"},
        )
        assert frame["segments"] == ["New", "New Customer", "Existing FH Customer"]

    def test_y_matrix_columns_match_the_mapped_outcome_columns(self, df, spec):
        frame = prepare_fh_modeling_frame(df, spec, dna_kit_outcomes={"New Customer": "DNA_Kit_New_Customer"})
        np.testing.assert_array_equal(frame["Y"][:, 0], df["GSA_New"].to_numpy())
        np.testing.assert_array_equal(frame["Y"][:, 1], df["DNA_Kit_New_Customer"].to_numpy())

    def test_missing_dna_kit_column_raises(self, df, spec):
        with pytest.raises(ValueError, match="missing from data"):
            prepare_fh_modeling_frame(df, spec, dna_kit_outcomes={"New Customer": "Does_Not_Exist"})

    def test_colliding_segment_name_with_an_fh_segment_raises(self, df, spec):
        with pytest.raises(ValueError, match="collide"):
            prepare_fh_modeling_frame(df, spec, dna_kit_outcomes={"New": "DNA_Kit_New_Customer"})

    def test_promo_col_mapped_for_a_dna_kit_segment_is_picked_up(self, df):
        spec_with_dna_promo = ModelSpec(
            date_col="date", market_col="market", markets=["UK"],
            segment_outcomes={"New": "GSA_New"}, channels=["TV_Brand"],
            promo_cols={"New Customer": "Promo_DNA"},
        )
        frame = prepare_fh_modeling_frame(df, spec_with_dna_promo, dna_kit_outcomes={"New Customer": "DNA_Kit_New_Customer"})
        seg_idx = frame["segments"].index("New Customer")
        np.testing.assert_array_equal(frame["promo"][:, seg_idx], df["Promo_DNA"].to_numpy())

    def test_segment_control_mapped_for_a_dna_kit_segment_is_picked_up(self, df):
        spec_with_dna_control = ModelSpec(
            date_col="date", market_col="market", markets=["UK"],
            segment_outcomes={"New": "GSA_New"}, channels=["TV_Brand"],
            segment_control_cols={"New Customer": ["DNA_Kit_Price"]},
        )
        frame = prepare_fh_modeling_frame(df, spec_with_dna_control, dna_kit_outcomes={"New Customer": "DNA_Kit_New_Customer"})
        assert "New Customer" in frame["segment_controls"]
        np.testing.assert_array_equal(frame["segment_controls"]["New Customer"][:, 0], df["DNA_Kit_Price"].to_numpy())
