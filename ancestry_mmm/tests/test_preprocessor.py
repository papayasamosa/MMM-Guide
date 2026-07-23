"""Tests for data.preprocessor.prepare_fh_modeling_frame's `outcomes` param
(docs/outcomes.md, docs/dna_fh_causal_structure.md) - the canonical,
outcome_id-keyed frame-building path (PR E) that lets DNA-product outcomes,
and multiple distinct KPIs sharing one customer segment, join a fit
alongside the Family History outcomes derived from ModelSpec.segment_outcomes,
without changing ModelSpec's own shape."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.outcomes import (
    DNA,
    FAMILY_HISTORY,
    OutcomeDefinition,
    fh_outcomes_from_spec,
)
from ancestry_mmm.core.pathways import MediaOutcomePathway
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame


@pytest.fixture
def df() -> pd.DataFrame:
    n = 10
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="W"),
            "market": ["UK"] * n,
            "TV_Brand": np.linspace(100.0, 1000.0, n),
            "GSA_New": np.arange(10, 10 + n, dtype=float),
            "Signup_New": np.arange(30, 30 + n, dtype=float),
            "DNA_Kit_New_Customer": np.arange(50, 50 + n, dtype=float),
            "DNA_Kit_Existing_FH_Customer": np.arange(20, 20 + n, dtype=float),
            "Promo_DNA": np.zeros(n),
            "DNA_Kit_Price": np.full(n, 79.0),
        }
    )


@pytest.fixture
def spec() -> ModelSpec:
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "GSA_New"},
        channels=["TV_Brand"],
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
    def test_dna_kit_outcomes_are_appended_after_fh_outcomes(
        self, df, spec, fh_outcomes
    ):
        outcomes = fh_outcomes + [
            OutcomeDefinition(
                outcome_id="dna_new_kit",
                product=DNA,
                segment="New Customer",
                metric="Kit sale",
                source_column="DNA_Kit_New_Customer",
            ),
            OutcomeDefinition(
                outcome_id="dna_existing_fh_kit",
                product=DNA,
                segment="Existing FH Customer",
                metric="Kit sale",
                source_column="DNA_Kit_Existing_FH_Customer",
            ),
        ]
        frame = prepare_fh_modeling_frame(df, spec, outcomes=outcomes)
        assert frame["outcome_ids"] == ["fh_new", "dna_new_kit", "dna_existing_fh_kit"]

    def test_y_matrix_columns_match_the_mapped_outcome_source_columns(
        self, df, spec, fh_outcomes
    ):
        outcomes = fh_outcomes + [
            OutcomeDefinition(
                outcome_id="dna_new_kit",
                product=DNA,
                segment="New Customer",
                metric="Kit sale",
                source_column="DNA_Kit_New_Customer",
            ),
        ]
        frame = prepare_fh_modeling_frame(df, spec, outcomes=outcomes)
        np.testing.assert_array_equal(frame["Y"][:, 0], df["GSA_New"].to_numpy())
        np.testing.assert_array_equal(
            frame["Y"][:, 1], df["DNA_Kit_New_Customer"].to_numpy()
        )

    def test_missing_source_column_raises(self, df, spec, fh_outcomes):
        outcomes = fh_outcomes + [
            OutcomeDefinition(
                outcome_id="dna_new_kit",
                product=DNA,
                segment="New Customer",
                metric="Kit sale",
                source_column="Does_Not_Exist",
            ),
        ]
        with pytest.raises(ValueError, match="missing from data"):
            prepare_fh_modeling_frame(df, spec, outcomes=outcomes)

    def test_duplicate_outcome_id_raises(self, df, spec, fh_outcomes):
        outcomes = fh_outcomes + [
            OutcomeDefinition(
                outcome_id="fh_new",
                product=DNA,
                segment="New Customer",
                metric="Kit sale",
                source_column="DNA_Kit_New_Customer",
            ),
        ]
        with pytest.raises(ValueError, match="Duplicate outcome_id"):
            prepare_fh_modeling_frame(df, spec, outcomes=outcomes)

    def test_promo_col_mapped_for_a_dna_kit_segment_is_picked_up(self, df, fh_outcomes):
        spec_with_dna_promo = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "GSA_New"},
            channels=["TV_Brand"],
            promo_cols={"New Customer": "Promo_DNA"},
        )
        outcomes = fh_outcomes + [
            OutcomeDefinition(
                outcome_id="dna_new_kit",
                product=DNA,
                segment="New Customer",
                metric="Kit sale",
                source_column="DNA_Kit_New_Customer",
            ),
        ]
        frame = prepare_fh_modeling_frame(df, spec_with_dna_promo, outcomes=outcomes)
        idx = frame["outcome_ids"].index("dna_new_kit")
        np.testing.assert_array_equal(
            frame["promo"][:, idx], df["Promo_DNA"].to_numpy()
        )

    def test_segment_control_mapped_for_a_dna_kit_segment_is_picked_up(
        self, df, fh_outcomes
    ):
        spec_with_dna_control = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "GSA_New"},
            channels=["TV_Brand"],
            segment_control_cols={"New Customer": ["DNA_Kit_Price"]},
        )
        outcomes = fh_outcomes + [
            OutcomeDefinition(
                outcome_id="dna_new_kit",
                product=DNA,
                segment="New Customer",
                metric="Kit sale",
                source_column="DNA_Kit_New_Customer",
            ),
        ]
        frame = prepare_fh_modeling_frame(df, spec_with_dna_control, outcomes=outcomes)
        assert "dna_new_kit" in frame["outcome_controls"]
        np.testing.assert_array_equal(
            frame["outcome_controls"]["dna_new_kit"][:, 0],
            df["DNA_Kit_Price"].to_numpy(),
        )


class TestPrepareFhModelingFrameWithSharedSegmentOutcomes:
    """The exact scenario PR E exists for: two distinct KPIs (a Family
    History sign-up and a Family History GSA) sharing one customer segment."""

    def test_signup_and_gsa_on_the_same_segment_both_reach_the_frame_as_distinct_outcome_ids(
        self, df, spec
    ):
        outcomes = [
            OutcomeDefinition(
                outcome_id="fh_new_signup",
                product=FAMILY_HISTORY,
                segment="New",
                metric="Sign-up",
                source_column="Signup_New",
            ),
            OutcomeDefinition(
                outcome_id="fh_new_gsa",
                product=FAMILY_HISTORY,
                segment="New",
                metric="GSA",
                source_column="GSA_New",
            ),
        ]
        frame = prepare_fh_modeling_frame(df, spec, outcomes=outcomes)
        assert frame["outcome_ids"] == ["fh_new_signup", "fh_new_gsa"]
        assert frame["Y"].shape == (10, 2)
        np.testing.assert_array_equal(frame["Y"][:, 0], df["Signup_New"].to_numpy())
        np.testing.assert_array_equal(frame["Y"][:, 1], df["GSA_New"].to_numpy())


class TestOutcomeIdKeyedPromoAndControlMappings:
    """PR E.2 requirement #6 / required test case 9: promo and control
    mappings keyed by outcome_id, not just segment - a sign-up and a GSA
    sharing a segment can have genuinely different mappings once configured
    explicitly at the outcome_id level."""

    @pytest.fixture
    def shared_segment_outcomes(self):
        return [
            OutcomeDefinition(
                outcome_id="fh_new_signup",
                product=FAMILY_HISTORY,
                segment="New",
                metric="Sign-up",
                source_column="Signup_New",
            ),
            OutcomeDefinition(
                outcome_id="fh_new_gsa",
                product=FAMILY_HISTORY,
                segment="New",
                metric="GSA",
                source_column="GSA_New",
            ),
        ]

    def test_outcome_promo_cols_differs_across_signup_and_gsa_on_the_same_segment(
        self, df, spec, shared_segment_outcomes
    ):
        df = df.copy()
        df["Promo_Signup"] = np.ones(len(df)) * 3.0
        df["Promo_GSA"] = np.ones(len(df)) * 7.0
        spec_with_outcome_promo = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            channels=["TV_Brand"],
            outcome_promo_cols={
                "fh_new_signup": "Promo_Signup",
                "fh_new_gsa": "Promo_GSA",
            },
        )
        frame = prepare_fh_modeling_frame(
            df, spec_with_outcome_promo, outcomes=shared_segment_outcomes
        )
        signup_idx = frame["outcome_ids"].index("fh_new_signup")
        gsa_idx = frame["outcome_ids"].index("fh_new_gsa")
        np.testing.assert_array_equal(
            frame["promo"][:, signup_idx], df["Promo_Signup"].to_numpy()
        )
        np.testing.assert_array_equal(
            frame["promo"][:, gsa_idx], df["Promo_GSA"].to_numpy()
        )
        # The two outcomes share a segment but must never end up with the
        # same promo series just because of that.
        assert not np.array_equal(
            frame["promo"][:, signup_idx], frame["promo"][:, gsa_idx]
        )

    def test_outcome_promo_cols_overrides_legacy_segment_promo_cols(
        self, df, spec, shared_segment_outcomes
    ):
        df = df.copy()
        df["Promo_Segment"] = np.ones(len(df)) * 2.0
        df["Promo_Override"] = np.ones(len(df)) * 9.0
        spec_with_both = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            channels=["TV_Brand"],
            promo_cols={"New": "Promo_Segment"},
            outcome_promo_cols={"fh_new_gsa": "Promo_Override"},
        )
        frame = prepare_fh_modeling_frame(
            df, spec_with_both, outcomes=shared_segment_outcomes
        )
        signup_idx = frame["outcome_ids"].index("fh_new_signup")
        gsa_idx = frame["outcome_ids"].index("fh_new_gsa")
        # fh_new_signup has no outcome-level override - falls back to the
        # legacy segment mapping.
        np.testing.assert_array_equal(
            frame["promo"][:, signup_idx], df["Promo_Segment"].to_numpy()
        )
        # fh_new_gsa has an explicit outcome-level override - wins outright.
        np.testing.assert_array_equal(
            frame["promo"][:, gsa_idx], df["Promo_Override"].to_numpy()
        )

    def test_outcome_control_cols_differs_across_signup_and_gsa_on_the_same_segment(
        self, df, spec, shared_segment_outcomes
    ):
        df = df.copy()
        df["Signup_Control"] = np.arange(len(df), dtype=float)
        df["Gsa_Control"] = np.arange(len(df), dtype=float) * 2
        spec_with_outcome_controls = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            channels=["TV_Brand"],
            outcome_control_cols={
                "fh_new_signup": ["Signup_Control"],
                "fh_new_gsa": ["Gsa_Control"],
            },
        )
        frame = prepare_fh_modeling_frame(
            df, spec_with_outcome_controls, outcomes=shared_segment_outcomes
        )
        assert frame["outcome_control_names"]["fh_new_signup"] == ["Signup_Control"]
        assert frame["outcome_control_names"]["fh_new_gsa"] == ["Gsa_Control"]

    def test_product_level_controls_apply_to_every_outcome_of_that_product(
        self, df, spec, shared_segment_outcomes
    ):
        df = df.copy()
        df["FH_Product_Control"] = np.ones(len(df)) * 5.0
        spec_with_product_controls = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            channels=["TV_Brand"],
            product_control_cols={FAMILY_HISTORY: ["FH_Product_Control"]},
        )
        frame = prepare_fh_modeling_frame(
            df, spec_with_product_controls, outcomes=shared_segment_outcomes
        )
        assert "FH_Product_Control" in frame["outcome_control_names"]["fh_new_signup"]
        assert "FH_Product_Control" in frame["outcome_control_names"]["fh_new_gsa"]

    def test_product_segment_and_outcome_controls_are_additive_and_deduplicated(
        self, df, spec, shared_segment_outcomes
    ):
        df = df.copy()
        df["FH_Product_Control"] = np.ones(len(df))
        df["New_Segment_Control"] = np.ones(len(df)) * 2
        df["Gsa_Only_Control"] = np.ones(len(df)) * 3
        combined_spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            channels=["TV_Brand"],
            product_control_cols={FAMILY_HISTORY: ["FH_Product_Control"]},
            segment_control_cols={
                "New": ["New_Segment_Control", "FH_Product_Control"]
            },  # deliberate dupe
            outcome_control_cols={"fh_new_gsa": ["Gsa_Only_Control"]},
        )
        frame = prepare_fh_modeling_frame(
            df, combined_spec, outcomes=shared_segment_outcomes
        )
        assert sorted(frame["outcome_control_names"]["fh_new_signup"]) == [
            "FH_Product_Control",
            "New_Segment_Control",
        ]
        assert sorted(frame["outcome_control_names"]["fh_new_gsa"]) == [
            "FH_Product_Control",
            "Gsa_Only_Control",
            "New_Segment_Control",
        ]


class TestPrepareFhModelingFrameExclusion:
    def test_included_in_fit_false_outcomes_are_left_out_of_the_frame(
        self, df, spec, fh_outcomes
    ):
        outcomes = fh_outcomes + [
            OutcomeDefinition(
                outcome_id="dna_new_kit",
                product=DNA,
                segment="New Customer",
                metric="Kit sale",
                source_column="DNA_Kit_New_Customer",
                included_in_fit=False,
            ),
        ]
        frame = prepare_fh_modeling_frame(df, spec, outcomes=outcomes)
        assert frame["outcome_ids"] == ["fh_new"]

    def test_all_outcomes_excluded_raises(self, df, spec, fh_outcomes):
        excluded = [
            OutcomeDefinition(**{**o.to_dict(), "included_in_fit": False})
            for o in fh_outcomes
        ]
        with pytest.raises(ValueError, match="No outcomes are included in the fit"):
            prepare_fh_modeling_frame(df, spec, outcomes=excluded)

    def test_full_pathway_ownership_is_validated_before_frame_construction(
        self, df, spec, fh_outcomes
    ):
        invalid = MediaOutcomePathway(
            channel="TV_Brand",
            source_product=DNA,
            target_outcome_id="fh_new",
        )
        with pytest.raises(ValueError, match="before frame preparation"):
            prepare_fh_modeling_frame(
                df,
                spec,
                outcomes=fh_outcomes,
                media_outcome_pathways=[invalid],
            )


class TestNetBillthroughTrainingGate:
    @staticmethod
    def nbt_outcome():
        return OutcomeDefinition(
            outcome_id="fh_new_nbt",
            product=FAMILY_HISTORY,
            segment="New",
            metric="Net bill-through count",
            source_column="NBT_New",
        )

    @staticmethod
    def metadata():
        return {
            "data_as_of_date": "2024-03-15",
            "model_start_week": "2024-01-07",
            "model_end_week": "2024-03-10",
            "latest_complete_net_billthrough_week": "2024-03-10",
            "maturity_rule_description": "authoritative upstream finalisation",
            "source_owner": "Finance Analytics",
        }

    def test_nbt_fit_is_blocked_without_completeness_metadata(self, df, spec):
        data = df.assign(NBT_New=np.arange(10, dtype=float))
        with pytest.raises(ValueError, match="training blocked"):
            prepare_fh_modeling_frame(data, spec, outcomes=[self.nbt_outcome()])

    def test_valid_wide_nbt_frame_reaches_the_modeling_frame(self, df, spec):
        data = df.assign(NBT_New=np.arange(10, dtype=float))
        frame = prepare_fh_modeling_frame(
            data,
            spec,
            outcomes=[self.nbt_outcome()],
            net_billthrough_metadata=self.metadata(),
        )
        np.testing.assert_array_equal(frame["Y"][:, 0], data["NBT_New"])
        assert frame["net_billthrough_metadata"].source_owner == "Finance Analytics"

    def test_valid_wide_and_long_nbt_inputs_prepare_identical_outcomes(self, df, spec):
        from ancestry_mmm.core.hierarchical_model import (
            build_fh_hierarchical_model,
        )
        from ancestry_mmm.core.market_specific_model import (
            build_fh_market_specific_model,
        )

        outcomes = [
            self.nbt_outcome(),
            OutcomeDefinition(
                outcome_id="fh_winback_nbt",
                product=FAMILY_HISTORY,
                segment="Winback",
                metric="Net bill-through count",
                source_column="NBT_Winback",
            ),
        ]
        wide = df.assign(
            NBT_New=np.arange(10, dtype=float),
            NBT_Winback=np.arange(20, 30, dtype=float),
        )
        long_parts = []
        for segment, source in (("New", "NBT_New"), ("Winback", "NBT_Winback")):
            part = wide.copy()
            part["segment"] = segment
            part["fh_net_billthrough_count"] = part[source]
            long_parts.append(part.drop(columns=["NBT_New", "NBT_Winback"]))
        long = pd.concat(long_parts, ignore_index=True)

        wide_frame = prepare_fh_modeling_frame(
            wide,
            spec,
            outcomes=outcomes,
            net_billthrough_metadata=self.metadata(),
        )
        long_frame = prepare_fh_modeling_frame(
            long,
            spec,
            outcomes=outcomes,
            net_billthrough_metadata=self.metadata(),
        )
        np.testing.assert_array_equal(long_frame["Y"], wide_frame["Y"])
        np.testing.assert_array_equal(long_frame["X_media"], wide_frame["X_media"])
        for frame in (wide_frame, long_frame):
            shared_model, shared_meta = build_fh_hierarchical_model(frame, spec)
            assert shared_model is not None
            assert shared_meta.outcome_ids == [
                "fh_new_nbt",
                "fh_winback_nbt",
            ]
        two_market_spec = ModelSpec.from_dict(
            {**spec.to_dict(), "markets": ["UK", "AU"]}
        )
        for source in (wide, long):
            two_market_source = pd.concat(
                [source, source.assign(market="AU")], ignore_index=True
            )
            two_market_frame = prepare_fh_modeling_frame(
                two_market_source,
                two_market_spec,
                outcomes=outcomes,
                net_billthrough_metadata=self.metadata(),
            )
            market_model, market_meta = build_fh_market_specific_model(
                two_market_frame, two_market_spec
            )
            assert market_model is not None
            assert market_meta.outcome_ids == ["fh_new_nbt", "fh_winback_nbt"]

    def test_invalid_nbt_introduced_by_transformation_cannot_reach_aggregation(
        self, df, spec
    ):
        transformed = df.assign(NBT_New=np.arange(10, dtype=float))
        transformed.loc[0, "NBT_New"] = -1.0
        with pytest.raises(ValueError, match="negative"):
            prepare_fh_modeling_frame(
                transformed,
                spec,
                outcomes=[self.nbt_outcome()],
                net_billthrough_metadata=self.metadata(),
            )

    def test_long_nbt_duplicates_are_blocked_before_aggregation(self, df, spec):
        outcomes = [
            self.nbt_outcome(),
            OutcomeDefinition(
                outcome_id="fh_winback_nbt",
                product=FAMILY_HISTORY,
                segment="Winback",
                metric="Net bill-through count",
                source_column="NBT_Winback",
            ),
        ]
        rows = []
        for segment, offset in (("New", 0), ("Winback", 20)):
            part = df.copy()
            part["segment"] = segment
            part["fh_net_billthrough_count"] = np.arange(
                offset, offset + len(part), dtype=float
            )
            rows.append(part)
        long = pd.concat(rows, ignore_index=True)
        long = pd.concat([long, long.iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match="duplicate"):
            prepare_fh_modeling_frame(
                long,
                spec,
                outcomes=outcomes,
                net_billthrough_metadata=self.metadata(),
            )
