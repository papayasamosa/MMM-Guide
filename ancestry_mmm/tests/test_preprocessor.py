"""Tests for data.preprocessor.prepare_fh_modeling_frame's `outcomes` param
(docs/outcomes.md, docs/dna_fh_causal_structure.md) - the canonical,
outcome_id-keyed frame-building path (PR E) that lets DNA-product outcomes,
and multiple distinct KPIs sharing one customer segment, join a fit
alongside the Family History outcomes derived from ModelSpec.segment_outcomes,
without changing ModelSpec's own shape."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.outcomes import DNA, FAMILY_HISTORY, OutcomeDefinition, fh_outcomes_from_spec
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
        "Signup_New": np.arange(30, 30 + n, dtype=float),
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


@pytest.fixture
def fh_outcomes(spec) -> list:
    return fh_outcomes_from_spec(spec.segment_outcomes)


class TestPrepareFhModelingFrameWithoutExplicitOutcomes:
    def test_omitting_the_argument_derives_fh_outcomes_from_spec(self, df, spec):
        frame = prepare_fh_modeling_frame(df, spec)
        assert frame["outcome_ids"] == ["fh_new"]
        assert frame["Y"].shape == (10, 1)

    def test_explicit_none_is_the_same_as_omitting_it(self, df, spec):
        frame_none = prepare_fh_modeling_frame(df, spec, outcomes=None)
        frame_omitted = prepare_fh_modeling_frame(df, spec)
        assert frame_none["outcome_ids"] == frame_omitted["outcome_ids"]


class TestPrepareFhModelingFrameWithDnaKitOutcomes:
    def test_dna_kit_outcomes_are_appended_after_fh_outcomes(self, df, spec, fh_outcomes):
        outcomes = fh_outcomes + [
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment="New Customer", metric="Kit sale", source_column="DNA_Kit_New_Customer"),
            OutcomeDefinition(outcome_id="dna_existing_fh_kit", product=DNA, segment="Existing FH Customer", metric="Kit sale", source_column="DNA_Kit_Existing_FH_Customer"),
        ]
        frame = prepare_fh_modeling_frame(df, spec, outcomes=outcomes)
        assert frame["outcome_ids"] == ["fh_new", "dna_new_kit", "dna_existing_fh_kit"]

    def test_y_matrix_columns_match_the_mapped_outcome_source_columns(self, df, spec, fh_outcomes):
        outcomes = fh_outcomes + [
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment="New Customer", metric="Kit sale", source_column="DNA_Kit_New_Customer"),
        ]
        frame = prepare_fh_modeling_frame(df, spec, outcomes=outcomes)
        np.testing.assert_array_equal(frame["Y"][:, 0], df["GSA_New"].to_numpy())
        np.testing.assert_array_equal(frame["Y"][:, 1], df["DNA_Kit_New_Customer"].to_numpy())

    def test_missing_source_column_raises(self, df, spec, fh_outcomes):
        outcomes = fh_outcomes + [
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment="New Customer", metric="Kit sale", source_column="Does_Not_Exist"),
        ]
        with pytest.raises(ValueError, match="missing from data"):
            prepare_fh_modeling_frame(df, spec, outcomes=outcomes)

    def test_duplicate_outcome_id_raises(self, df, spec, fh_outcomes):
        outcomes = fh_outcomes + [
            OutcomeDefinition(outcome_id="fh_new", product=DNA, segment="New Customer", metric="Kit sale", source_column="DNA_Kit_New_Customer"),
        ]
        with pytest.raises(ValueError, match="Duplicate outcome_id"):
            prepare_fh_modeling_frame(df, spec, outcomes=outcomes)

    def test_promo_col_mapped_for_a_dna_kit_segment_is_picked_up(self, df, fh_outcomes):
        spec_with_dna_promo = ModelSpec(
            date_col="date", market_col="market", markets=["UK"],
            segment_outcomes={"New": "GSA_New"}, channels=["TV_Brand"],
            promo_cols={"New Customer": "Promo_DNA"},
        )
        outcomes = fh_outcomes + [
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment="New Customer", metric="Kit sale", source_column="DNA_Kit_New_Customer"),
        ]
        frame = prepare_fh_modeling_frame(df, spec_with_dna_promo, outcomes=outcomes)
        idx = frame["outcome_ids"].index("dna_new_kit")
        np.testing.assert_array_equal(frame["promo"][:, idx], df["Promo_DNA"].to_numpy())

    def test_segment_control_mapped_for_a_dna_kit_segment_is_picked_up(self, df, fh_outcomes):
        spec_with_dna_control = ModelSpec(
            date_col="date", market_col="market", markets=["UK"],
            segment_outcomes={"New": "GSA_New"}, channels=["TV_Brand"],
            segment_control_cols={"New Customer": ["DNA_Kit_Price"]},
        )
        outcomes = fh_outcomes + [
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment="New Customer", metric="Kit sale", source_column="DNA_Kit_New_Customer"),
        ]
        frame = prepare_fh_modeling_frame(df, spec_with_dna_control, outcomes=outcomes)
        assert "dna_new_kit" in frame["outcome_controls"]
        np.testing.assert_array_equal(frame["outcome_controls"]["dna_new_kit"][:, 0], df["DNA_Kit_Price"].to_numpy())


class TestPrepareFhModelingFrameWithSharedSegmentOutcomes:
    """The exact scenario PR E exists for: two distinct KPIs (a Family
    History sign-up and a Family History GSA) sharing one customer segment."""

    def test_signup_and_gsa_on_the_same_segment_both_reach_the_frame_as_distinct_outcome_ids(self, df, spec):
        outcomes = [
            OutcomeDefinition(outcome_id="fh_new_signup", product=FAMILY_HISTORY, segment="New", metric="Sign-up", source_column="Signup_New"),
            OutcomeDefinition(outcome_id="fh_new_gsa", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="GSA_New"),
        ]
        frame = prepare_fh_modeling_frame(df, spec, outcomes=outcomes)
        assert frame["outcome_ids"] == ["fh_new_signup", "fh_new_gsa"]
        assert frame["Y"].shape == (10, 2)
        np.testing.assert_array_equal(frame["Y"][:, 0], df["Signup_New"].to_numpy())
        np.testing.assert_array_equal(frame["Y"][:, 1], df["GSA_New"].to_numpy())


class TestPrepareFhModelingFrameExclusion:
    def test_included_in_fit_false_outcomes_are_left_out_of_the_frame(self, df, spec, fh_outcomes):
        outcomes = fh_outcomes + [
            OutcomeDefinition(
                outcome_id="dna_new_kit", product=DNA, segment="New Customer", metric="Kit sale",
                source_column="DNA_Kit_New_Customer", included_in_fit=False,
            ),
        ]
        frame = prepare_fh_modeling_frame(df, spec, outcomes=outcomes)
        assert frame["outcome_ids"] == ["fh_new"]

    def test_all_outcomes_excluded_raises(self, df, spec, fh_outcomes):
        excluded = [OutcomeDefinition(**{**o.to_dict(), "included_in_fit": False}) for o in fh_outcomes]
        with pytest.raises(ValueError, match="No outcomes are included in the fit"):
            prepare_fh_modeling_frame(df, spec, outcomes=excluded)
