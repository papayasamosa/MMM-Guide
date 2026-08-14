import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.outcomes import (
    OutcomeGroupDefinition,
    outcome_group_fingerprint_payload,
)
from ancestry_mmm.core.market_config import (
    ChannelMediaUnitConfig,
    MarketCurrency,
    MarketDescriptors,
    MarketProfile,
    MarketSpecConfig,
)


# ---------------------------------------------------------------------------
# Data fingerprint
# ---------------------------------------------------------------------------


@pytest.fixture
def base_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="W"),
            "market": ["UK", "UK", "UK", "UK"],
            "TV_Brand": [100.0, 200.0, 150.0, 175.0],
            "fh_new_gsa": [10, 12, 11, 13],
        }
    )


class TestFingerprintDataframe:
    def test_identical_data_same_fingerprint(self, base_df):
        assert fingerprint_dataframe(base_df) == fingerprint_dataframe(base_df.copy())

    def test_changed_value_changes_fingerprint(self, base_df):
        changed = base_df.copy()
        changed.loc[0, "TV_Brand"] = 999.0
        assert fingerprint_dataframe(base_df) != fingerprint_dataframe(changed)

    def test_changed_row_order_changes_fingerprint(self, base_df):
        reordered = base_df.iloc[::-1].reset_index(drop=True)
        assert fingerprint_dataframe(base_df) != fingerprint_dataframe(reordered)

    def test_changed_column_order_changes_fingerprint(self, base_df):
        reordered = base_df[["market", "date", "fh_new_gsa", "TV_Brand"]]
        assert fingerprint_dataframe(base_df) != fingerprint_dataframe(reordered)

    def test_changed_dtype_changes_fingerprint(self, base_df):
        recast = base_df.copy()
        recast["fh_new_gsa"] = recast["fh_new_gsa"].astype(float)
        assert fingerprint_dataframe(base_df) != fingerprint_dataframe(recast)

    def test_missing_values_are_deterministic(self):
        df1 = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
        df2 = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
        assert fingerprint_dataframe(df1) == fingerprint_dataframe(df2)
        # ... and distinguishable from a genuinely different value in the same slot.
        df3 = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        assert fingerprint_dataframe(df1) != fingerprint_dataframe(df3)

    def test_date_columns_are_deterministic(self):
        df1 = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3)})
        df2 = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3)})
        df3 = pd.DataFrame({"date": pd.date_range("2024-02-01", periods=3)})
        assert fingerprint_dataframe(df1) == fingerprint_dataframe(df2)
        assert fingerprint_dataframe(df1) != fingerprint_dataframe(df3)

    def test_categorical_columns_are_deterministic(self):
        df1 = pd.DataFrame({"segment": pd.Categorical(["New", "Winback", "New"])})
        df2 = pd.DataFrame({"segment": pd.Categorical(["New", "Winback", "New"])})
        df3 = pd.DataFrame({"segment": pd.Categorical(["New", "New", "New"])})
        assert fingerprint_dataframe(df1) == fingerprint_dataframe(df2)
        assert fingerprint_dataframe(df1) != fingerprint_dataframe(df3)

    def test_empty_dataframe_does_not_raise(self):
        fingerprint_dataframe(pd.DataFrame({"a": []}))
        fingerprint_dataframe(pd.DataFrame())


# ---------------------------------------------------------------------------
# Model-specification fingerprint
# ---------------------------------------------------------------------------


class TestFingerprintModelSpec:
    def test_key_insertion_order_does_not_matter(self):
        spec_a = {"markets": ["UK"], "channels": ["TV", "Search"]}
        spec_b = {"channels": ["TV", "Search"], "markets": ["UK"]}
        assert fingerprint_model_spec(
            spec_a, {"decay_mu": 0.5}, 4
        ) == fingerprint_model_spec(spec_b, {"decay_mu": 0.5}, 4)

    def test_changed_spec_changes_fingerprint(self):
        spec_a = {"markets": ["UK"], "channels": ["TV"]}
        spec_b = {"markets": ["UK", "Australia"], "channels": ["TV"]}
        assert fingerprint_model_spec(spec_a, {}, 4) != fingerprint_model_spec(
            spec_b, {}, 4
        )

    def test_changed_prior_changes_fingerprint(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(
            spec, {"decay_mu": 0.5}, 4
        ) != fingerprint_model_spec(spec, {"decay_mu": 0.7}, 4)

    def test_changed_dna_lag_weeks_changes_fingerprint(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) != fingerprint_model_spec(
            spec, {}, 6
        )

    def test_list_order_is_preserved_and_meaningful(self):
        spec_a = {"channels": ["TV", "Search"]}
        spec_b = {"channels": ["Search", "TV"]}
        assert fingerprint_model_spec(spec_a, {}, 4) != fingerprint_model_spec(
            spec_b, {}, 4
        )

    def test_model_type_defaults_to_shared_and_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, model_type="shared"
        )

    def test_market_specific_model_type_changes_the_fingerprint(self):
        spec = {"markets": ["UK", "Australia"]}
        shared_fp = fingerprint_model_spec(spec, {}, 4, model_type="shared")
        market_specific_fp = fingerprint_model_spec(
            spec, {}, 4, model_type="market_specific"
        )
        assert shared_fp != market_specific_fp

    def test_switching_model_type_changes_the_fingerprint_even_with_identical_spec_and_priors(
        self,
    ):
        # The scenario this guards against: a user retrains under a different
        # model structure without touching the spec/priors/lag at all - the
        # fingerprint must still change so a stale approval gets invalidated.
        spec = {"markets": ["UK", "Australia"]}
        prior_config = {"decay_mu": 0.5}
        fp_a = fingerprint_model_spec(spec, prior_config, 4, model_type="shared")
        fp_c = fingerprint_model_spec(
            spec, prior_config, 4, model_type="market_specific"
        )
        assert fp_a != fp_c


# ---------------------------------------------------------------------------
# Model-specification fingerprint: pipeline_steps + market_spec_config
# (PR1 3.3 - see docs/decision_log.md for the descriptive/model-relevant
# boundary this codifies)
# ---------------------------------------------------------------------------


class TestFingerprintModelSpecPipelineSteps:
    def test_no_pipeline_steps_is_backward_compatible_with_omitting_the_argument(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, pipeline_steps=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, pipeline_steps=[]
        )

    def test_changed_pipeline_steps_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        steps_a = [{"op": "log_transform", "column": "TV_Brand"}]
        steps_b = [
            {"op": "log_transform", "column": "TV_Brand"},
            {"op": "fill_na", "column": "Search"},
        ]
        fp_a = fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps_b)
        assert fp_a != fp_b

    def test_pipeline_step_order_is_meaningful(self):
        spec = {"markets": ["UK"]}
        steps_a = [{"op": "a"}, {"op": "b"}]
        steps_b = [{"op": "b"}, {"op": "a"}]
        fp_a = fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps_b)
        assert fp_a != fp_b

    def test_identical_pipeline_steps_same_fingerprint(self):
        spec = {"markets": ["UK"]}
        steps = [{"op": "log_transform", "column": "TV_Brand"}]
        assert fingerprint_model_spec(
            spec, {}, 4, pipeline_steps=steps
        ) == fingerprint_model_spec(spec, {}, 4, pipeline_steps=list(steps))


class TestFingerprintModelSpecDirectDnaSegments:
    """direct_dna_segments (which segments get a direct DNA-media pathway -
    i.e. which DNA-kit outcomes are actually included in a fit) must be
    fingerprinted - the instruction document's audit-confirmed gap: toggling
    DNA-kit outcomes in/out of a fit changed meta.segments without changing
    model_spec/prior_config/pipeline_steps/market_spec_config at all, so an
    approval could stay "matching" across two structurally different fits."""

    def test_no_direct_dna_segments_is_backward_compatible_with_omitting_the_argument(
        self,
    ):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, direct_dna_outcome_ids=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, direct_dna_outcome_ids=[]
        )

    def test_adding_a_dna_kit_segment_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_none = fingerprint_model_spec(
            spec, {}, 4, direct_dna_outcome_ids=["DNA_CrossSell"]
        )
        fp_with_kit = fingerprint_model_spec(
            spec, {}, 4, direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"]
        )
        assert fp_none != fp_with_kit

    def test_segment_list_order_does_not_matter(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, direct_dna_outcome_ids=["A", "B"])
        fp_b = fingerprint_model_spec(spec, {}, 4, direct_dna_outcome_ids=["B", "A"])
        assert fp_a == fp_b

    def test_excluding_a_previously_included_dna_outcome_changes_the_fingerprint(self):
        # The exact scenario the audit measured: toggling the Structure
        # page's "exclude from fit" control changes which segments a fit
        # actually has, with model_spec itself untouched.
        spec = {"markets": ["UK"], "segment_outcomes": {"New": "fh_new_gsa"}}
        fp_included = fingerprint_model_spec(
            spec, {}, 4, direct_dna_outcome_ids=["New", "New Customer"]
        )
        fp_excluded = fingerprint_model_spec(
            spec, {}, 4, direct_dna_outcome_ids=["New"]
        )
        assert fp_included != fp_excluded


class TestFingerprintModelSpecOutcomeCatalogue:
    """PR E.1: the full canonical outcome catalogue must be fingerprinted -
    direct_dna_outcome_ids alone only covers DNA-kit membership, not a
    relabelled metric/unit/role/source_column/value_weight, so those changes
    used to leave an approval wrongly "matching" a structurally different
    fit (test case: "outcome catalogue change invalidates approval")."""

    def _catalogue(self, **overrides):
        row = {
            "outcome_id": "fh_new_gsa",
            "product": "Family History",
            "segment": "New",
            "metric": "GSA",
            "unit": "GSA",
            "source_column": "col_a",
            "role": "primary",
            "included_in_fit": True,
            "value_weight": 100.0,
            "value_currency": "USD",
        }
        row.update(overrides)
        return [row]

    def test_omitting_outcome_catalogue_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=[]
        )

    def test_adding_an_outcome_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_one = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue()
        )
        two = self._catalogue() + [
            {
                "outcome_id": "fh_new_signup",
                "product": "Family History",
                "segment": "New",
                "metric": "Sign-up",
                "unit": "Sign-up",
                "source_column": "col_b",
                "role": "primary",
                "included_in_fit": True,
                "value_weight": 20.0,
                "value_currency": "USD",
            }
        ]
        fp_two = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=two)
        assert fp_one != fp_two

    def test_relabelling_gsa_to_signup_changes_the_fingerprint(self):
        # Exactly the scenario the instruction document calls out:
        # "changing sign-up to GSA" must invalidate approval.
        spec = {"markets": ["UK"]}
        fp_gsa = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(metric="GSA")
        )
        fp_signup = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(metric="Sign-up")
        )
        assert fp_gsa != fp_signup

    def test_changing_source_column_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(source_column="col_a")
        )
        fp_b = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(source_column="col_b")
        )
        assert fp_a != fp_b

    def test_changing_unit_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(unit="GSA")
        )
        fp_b = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(unit="count")
        )
        assert fp_a != fp_b

    def test_changing_role_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(role="primary")
        )
        fp_b = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(role="secondary")
        )
        assert fp_a != fp_b

    def test_toggling_included_in_fit_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(included_in_fit=True)
        )
        fp_b = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(included_in_fit=False)
        )
        assert fp_a != fp_b

    def test_changing_value_weight_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(value_weight=100.0)
        )
        fp_b = fingerprint_model_spec(
            spec, {}, 4, outcome_catalogue=self._catalogue(value_weight=150.0)
        )
        assert fp_a != fp_b

    def test_catalogue_order_does_not_matter(self):
        spec = {"markets": ["UK"]}
        one = self._catalogue(outcome_id="a")[0]
        two = self._catalogue(outcome_id="b")[0]
        fp_ab = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=[one, two])
        fp_ba = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=[two, one])
        assert fp_ab == fp_ba

    def test_unchanged_catalogue_leaves_fingerprint_identical(self):
        spec = {"markets": ["UK"]}
        fp_1 = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue())
        fp_2 = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue())
        assert fp_1 == fp_2


class TestFingerprintModelSpecOutcomeGroups:
    def _groups(self, **overrides):
        group = {
            "group_id": "fh_gsa_all",
            "group_label": "Family History GSA total",
            "product": "Family History",
            "outcome_family_key": "GSA",
            "segment_dimension": "fh_customer_segment",
            "member_outcome_ids": ["fh_new_gsa", "fh_cross_sell_gsa"],
            "aggregation_rule": "sum",
            "supplied_total_outcome_id": "fh_gsa_total",
        }
        group.update(overrides)
        return outcome_group_fingerprint_payload([OutcomeGroupDefinition(**group)])

    def test_omitting_outcome_groups_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, outcome_groups=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, outcome_groups=[]
        )

    def test_group_membership_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, outcome_groups=self._groups())
        fp_b = fingerprint_model_spec(
            spec,
            {},
            4,
            outcome_groups=self._groups(member_outcome_ids=["fh_new_gsa"]),
        )
        assert fp_a != fp_b

    def test_group_label_does_not_change_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, outcome_groups=self._groups())
        fp_b = fingerprint_model_spec(
            spec,
            {},
            4,
            outcome_groups=self._groups(group_label="All GSA outcomes"),
        )
        assert fp_a == fp_b

    def test_group_order_does_not_matter(self):
        spec = {"markets": ["UK"]}
        first = self._groups(group_id="a_group")[0]
        second = self._groups(group_id="b_group")[0]
        fp_ab = fingerprint_model_spec(spec, {}, 4, outcome_groups=[first, second])
        fp_ba = fingerprint_model_spec(spec, {}, 4, outcome_groups=[second, first])
        assert fp_ab == fp_ba


class TestFingerprintModelSpecFunnelLinks:
    """PR E.2: funnel links are diagnostic-only configuration but still
    calculation-relevant to what's displayed, so they're fingerprinted the
    same way as the outcome catalogue."""

    def test_omitting_funnel_links_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, funnel_links=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, funnel_links=[]
        )

    def test_adding_a_funnel_link_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_none = fingerprint_model_spec(spec, {}, 4, funnel_links=[])
        fp_one = fingerprint_model_spec(
            spec,
            {},
            4,
            funnel_links=[
                {
                    "upstream_outcome_id": "fh_new_signup",
                    "downstream_outcome_id": "fh_new_gsa",
                },
            ],
        )
        assert fp_none != fp_one

    def test_link_order_does_not_matter(self):
        spec = {"markets": ["UK"]}
        a = {"upstream_outcome_id": "a_signup", "downstream_outcome_id": "a_gsa"}
        b = {"upstream_outcome_id": "b_signup", "downstream_outcome_id": "b_gsa"}
        fp_ab = fingerprint_model_spec(spec, {}, 4, funnel_links=[a, b])
        fp_ba = fingerprint_model_spec(spec, {}, 4, funnel_links=[b, a])
        assert fp_ab == fp_ba

    def test_changing_a_link_pair_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(
            spec,
            {},
            4,
            funnel_links=[
                {"upstream_outcome_id": "signup", "downstream_outcome_id": "gsa"},
            ],
        )
        fp_b = fingerprint_model_spec(
            spec,
            {},
            4,
            funnel_links=[
                {"upstream_outcome_id": "signup", "downstream_outcome_id": "other_gsa"},
            ],
        )
        assert fp_a != fp_b


class TestFingerprintModelSpecMediaOutcomePathways:
    """PR F: the pathway catalogue doesn't (yet) change what gets fitted,
    but is calculation-adjacent metadata a future estimation PR will read -
    fingerprinted the same way as funnel_links."""

    def test_omitting_media_outcome_pathways_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, media_outcome_pathways=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, media_outcome_pathways=[]
        )

    def test_adding_a_pathway_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_none = fingerprint_model_spec(spec, {}, 4, media_outcome_pathways=[])
        fp_one = fingerprint_model_spec(
            spec,
            {},
            4,
            media_outcome_pathways=[
                {
                    "channel": "DNA_Media",
                    "target_outcome_id": "dna_new_kit",
                    "role": "primary_direct",
                },
            ],
        )
        assert fp_none != fp_one

    def test_pathway_order_does_not_matter(self):
        spec = {"markets": ["UK"]}
        a = {"channel": "TV", "target_outcome_id": "fh_new_gsa"}
        b = {"channel": "DNA_Media", "target_outcome_id": "dna_new_kit"}
        fp_ab = fingerprint_model_spec(spec, {}, 4, media_outcome_pathways=[a, b])
        fp_ba = fingerprint_model_spec(spec, {}, 4, media_outcome_pathways=[b, a])
        assert fp_ab == fp_ba


class TestFingerprintModelSpecActivityFitFingerprint:
    """PR G2A.6c workstream F: including the fit-relevant activity
    fingerprint (core.activities.activity_fit_fingerprint) in model
    identity so changing an activity's model_role, model-input column, or
    pathway linkage automatically stales the fit and any bound approval -
    fingerprinted the same way as funnel_links/media_outcome_pathways."""

    def test_omitting_activity_fit_fingerprint_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, activity_fit_fingerprint=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, activity_fit_fingerprint=""
        )

    def test_a_different_activity_fit_fingerprint_changes_the_model_spec_fingerprint(
        self,
    ):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(
            spec, {}, 4, activity_fit_fingerprint="fp-intervention"
        )
        fp_b = fingerprint_model_spec(
            spec, {}, 4, activity_fit_fingerprint="fp-mediator"
        )
        assert fp_a != fp_b

    def test_using_the_real_activity_fit_fingerprint_function_end_to_end(self):
        from ancestry_mmm.core.activities import (
            ActivityDefinition,
            activity_fit_fingerprint,
        )

        spec = {"markets": ["UK"]}
        intervention = ActivityDefinition(
            activity_id="tv-paid",
            channel="TV_Paid",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="finance",
        )
        mediator = ActivityDefinition(
            activity_id="tv-paid",
            channel="TV_Paid",
            activity_ownership="paid",
            model_role="mediator",
            economic_treatment="paid_media_cost",
            planning_eligibility="fixed",
            source="finance",
        )
        fp_intervention = fingerprint_model_spec(
            spec,
            {},
            4,
            activity_fit_fingerprint=activity_fit_fingerprint([intervention]),
        )
        fp_mediator = fingerprint_model_spec(
            spec,
            {},
            4,
            activity_fit_fingerprint=activity_fit_fingerprint([mediator]),
        )
        # model_role is fit-relevant - intervention vs mediator must stale the fit.
        assert fp_intervention != fp_mediator

        fp_intervention_again = fingerprint_model_spec(
            spec,
            {},
            4,
            activity_fit_fingerprint=activity_fit_fingerprint([intervention]),
        )
        assert fp_intervention == fp_intervention_again

    def test_non_fit_relevant_activity_fields_do_not_change_the_fingerprint(self):
        from ancestry_mmm.core.activities import (
            ActivityDefinition,
            activity_fit_fingerprint,
        )

        spec = {"markets": ["UK"]}
        draft = ActivityDefinition(
            activity_id="tv-paid",
            channel="TV_Paid",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="finance",
            approval_status="draft",
        )
        approved = ActivityDefinition(
            activity_id="tv-paid",
            channel="TV_Paid",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="response_only",
            planning_eligibility="fixed",
            source="finance",
            approval_status="approved",
            approved_by="reviewer",
            approved_at="2026-01-01",
        )
        # economic_treatment, planning_eligibility and approval metadata are
        # not fit-relevant - only model_role/model-input column/pathway_ids
        # are (they don't change what gets fitted).
        fp_draft = fingerprint_model_spec(
            spec,
            {},
            4,
            activity_fit_fingerprint=activity_fit_fingerprint([draft]),
        )
        fp_approved = fingerprint_model_spec(
            spec,
            {},
            4,
            activity_fit_fingerprint=activity_fit_fingerprint([approved]),
        )
        assert fp_draft == fp_approved

    def test_changing_a_pathway_role_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(
            spec,
            {},
            4,
            media_outcome_pathways=[
                {
                    "channel": "DNA_Media",
                    "target_outcome_id": "dna_new_kit",
                    "role": "primary_direct",
                },
            ],
        )
        fp_b = fingerprint_model_spec(
            spec,
            {},
            4,
            media_outcome_pathways=[
                {
                    "channel": "DNA_Media",
                    "target_outcome_id": "dna_new_kit",
                    "role": "exploratory_cross_product",
                },
            ],
        )
        assert fp_a != fp_b


class TestFingerprintModelSpecSearchObjectFitFingerprint:
    """REQ-SEARCH-001 fit-identity closure: including the fit-relevant
    Search fingerprint (core.search_objects.search_object_fit_fingerprint)
    in model identity, mirrored on TestFingerprintModelSpecActivityFitFingerprint
    above."""

    def test_omitting_search_object_fit_fingerprint_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, search_object_fit_fingerprint=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, search_object_fit_fingerprint=""
        )

    def test_a_different_search_object_fit_fingerprint_changes_the_model_spec_fingerprint(
        self,
    ):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, search_object_fit_fingerprint="fp-a")
        fp_b = fingerprint_model_spec(spec, {}, 4, search_object_fit_fingerprint="fp-b")
        assert fp_a != fp_b

    def test_using_the_real_search_object_fit_fingerprint_function_end_to_end(self):
        from ancestry_mmm.core.search_objects import (
            SearchObjectDefinition,
            search_object_fit_fingerprint,
        )

        spec = {"markets": ["UK"]}
        consumed_spend = SearchObjectDefinition(
            search_object_id="uk_paid_search_spend",
            search_role="paid_search_spend",
            source_column="paid_search_gbp_spend",
            unit="monetary",
            currency="GBP",
            market="UK",
            model_input_column="paid_search_gbp_spend",
        )
        unconsumed_demand = SearchObjectDefinition(
            search_object_id="uk_search_demand",
            search_role="search_demand",
            source_column="branded_query_index",
            unit="index",
            market="UK",
        )
        fp_with_spend_only = fingerprint_model_spec(
            spec,
            {},
            4,
            search_object_fit_fingerprint=search_object_fit_fingerprint(
                [consumed_spend],
                consumed_model_input_columns=["paid_search_gbp_spend"],
            ),
        )
        fp_with_both = fingerprint_model_spec(
            spec,
            {},
            4,
            search_object_fit_fingerprint=search_object_fit_fingerprint(
                [consumed_spend, unconsumed_demand],
                consumed_model_input_columns=["paid_search_gbp_spend"],
            ),
        )
        # unconsumed_demand's model_input_column is blank - it is never
        # consumed, so adding it must not change the fit fingerprint.
        assert fp_with_spend_only == fp_with_both

    def test_editing_a_consumed_fit_relevant_field_stales_the_fingerprint(self):
        from ancestry_mmm.core.search_objects import (
            SearchObjectDefinition,
            search_object_fit_fingerprint,
        )

        spec = {"markets": ["UK"]}
        before = SearchObjectDefinition(
            search_object_id="uk_paid_search_spend",
            search_role="paid_search_spend",
            source_column="paid_search_gbp_spend",
            unit="monetary",
            currency="GBP",
            market="UK",
            model_input_column="paid_search_gbp_spend",
        )
        after = SearchObjectDefinition(
            search_object_id="uk_paid_search_spend",
            search_role="paid_search_spend",
            source_column="a_different_source_column",
            unit="monetary",
            currency="GBP",
            market="UK",
            model_input_column="paid_search_gbp_spend",
        )
        columns = ["paid_search_gbp_spend"]
        fp_before = fingerprint_model_spec(
            spec,
            {},
            4,
            search_object_fit_fingerprint=search_object_fit_fingerprint(
                [before], consumed_model_input_columns=columns
            ),
        )
        fp_after = fingerprint_model_spec(
            spec,
            {},
            4,
            search_object_fit_fingerprint=search_object_fit_fingerprint(
                [after], consumed_model_input_columns=columns
            ),
        )
        assert fp_before != fp_after

    def test_editing_an_administrative_field_does_not_stale_the_fingerprint(self):
        """Regression for the false-staleness contradiction found in the
        Work Package 1 corrective review: the original version of this test
        compared two INDEPENDENTLY constructed version-1 objects (both
        `search_object_version=1`), which can never expose a bug in how
        `search_object_version` itself is (or isn't) hashed. Real sanctioned
        edits always go through `new_search_object_version`, which
        increments `search_object_version` on every edit - administrative or
        not. This test now reproduces that real lifecycle."""
        from ancestry_mmm.core.search_objects import (
            SearchObjectDefinition,
            new_search_object_version,
            search_object_fit_fingerprint,
        )

        v1 = SearchObjectDefinition(
            search_object_id="uk_paid_search_spend",
            search_role="paid_search_spend",
            source_column="paid_search_gbp_spend",
            unit="monetary",
            currency="GBP",
            market="UK",
            model_input_column="paid_search_gbp_spend",
        )
        # A real sanctioned administrative-only edit - e.g. approval - via
        # the one sanctioned lifecycle function, never a second
        # independently-constructed record.
        v2 = new_search_object_version(
            v1,
            approval_status="approved",
            approved_by="reviewer",
            approved_at="2026-01-01",
        )
        assert v2.search_object_version == 2

        columns = ["paid_search_gbp_spend"]
        fp_v1 = fingerprint_model_spec(
            {"markets": ["UK"]},
            {},
            4,
            search_object_fit_fingerprint=search_object_fit_fingerprint(
                [v1], consumed_model_input_columns=columns
            ),
        )
        fp_v2 = fingerprint_model_spec(
            {"markets": ["UK"]},
            {},
            4,
            search_object_fit_fingerprint=search_object_fit_fingerprint(
                [v2], consumed_model_input_columns=columns
            ),
        )
        assert fp_v1 == fp_v2

    def test_editing_planning_eligibility_via_sanctioned_version_edit_does_not_stale(
        self,
    ):
        """REQ-SEARCH-001 required invariant: an administrative-only
        sanctioned edit (planning_eligibility here, mirroring the brief's
        example) must not stale a consumed fit, even though
        `new_search_object_version` always increments
        `search_object_version`."""
        from ancestry_mmm.core.search_objects import (
            SearchObjectDefinition,
            new_search_object_version,
            search_object_fit_fingerprint,
        )

        v1 = SearchObjectDefinition(
            search_object_id="uk_paid_search_spend",
            search_role="paid_search_spend",
            source_column="paid_search_gbp_spend",
            unit="monetary",
            currency="GBP",
            market="UK",
            model_input_column="paid_search_gbp_spend",
            planning_eligibility="excluded",
        )
        v2 = new_search_object_version(v1, planning_eligibility="scenario_only")
        assert v2.search_object_version == 2
        assert v2.planning_eligibility == "scenario_only"

        columns = ["paid_search_gbp_spend"]
        assert search_object_fit_fingerprint(
            [v1], consumed_model_input_columns=columns
        ) == search_object_fit_fingerprint([v2], consumed_model_input_columns=columns)

    def test_editing_a_fit_relevant_field_via_sanctioned_version_edit_stales(self):
        """The mirror-image invariant: a sanctioned edit to a fit-relevant
        field (source_column here) via the same lifecycle function must
        change the fit fingerprint."""
        from ancestry_mmm.core.search_objects import (
            SearchObjectDefinition,
            new_search_object_version,
            search_object_fit_fingerprint,
        )

        v1 = SearchObjectDefinition(
            search_object_id="uk_paid_search_spend",
            search_role="paid_search_spend",
            source_column="paid_search_gbp_spend",
            unit="monetary",
            currency="GBP",
            market="UK",
            model_input_column="paid_search_gbp_spend",
        )
        v2 = new_search_object_version(v1, source_column="a_different_source_column")

        columns = ["paid_search_gbp_spend"]
        assert search_object_fit_fingerprint(
            [v1], consumed_model_input_columns=columns
        ) != search_object_fit_fingerprint([v2], consumed_model_input_columns=columns)


class TestFingerprintModelSpecVariableCoverageFingerprint:
    """REQ-COVERAGE-001 S5: including the fit-relevant coverage-matrix
    fingerprint (core.coverage.VariableCoverageMatrix.fingerprint()) in
    model identity, mirrored on TestFingerprintModelSpecSearchObjectFitFingerprint
    above - except this parameter is a simple pass-through of the whole
    matrix's fingerprint (mirroring causal_graph_structural_fingerprint),
    not filtered by per-fit consumption the way search_object_fit_fingerprint
    is - see fingerprint_model_spec's docstring for why."""

    def test_omitting_variable_coverage_fingerprint_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, variable_coverage_fingerprint=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, variable_coverage_fingerprint=""
        )

    def test_a_different_variable_coverage_fingerprint_changes_the_model_spec_fingerprint(
        self,
    ):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, variable_coverage_fingerprint="fp-a")
        fp_b = fingerprint_model_spec(spec, {}, 4, variable_coverage_fingerprint="fp-b")
        assert fp_a != fp_b

    def test_using_the_real_variable_coverage_matrix_fingerprint_end_to_end(self):
        from ancestry_mmm.core.coverage import (
            CoverageSegment,
            FrequencyMetadata,
            VariableCoverageMatrix,
            VariableCoverageRecord,
        )

        frequency = FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class="flow_count",
        )
        record = VariableCoverageRecord(
            variable_id="tv_spend",
            source_id="media_source",
            source_version=1,
            market="UK",
            frequency=frequency,
            coverage_segments=(
                CoverageSegment(
                    period_start="2026-01-01",
                    period_end="2026-01-07",
                    state="unknown",
                ),
            ),
        )
        matrix_before = VariableCoverageMatrix(
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-01-01",
            records=(record,),
        )
        matrix_after = VariableCoverageMatrix(
            matrix_id="m1", matrix_version=1, generated_at="2026-01-01", records=()
        )
        spec = {"markets": ["UK"]}
        fp_before = fingerprint_model_spec(
            spec,
            {},
            4,
            variable_coverage_fingerprint=matrix_before.fingerprint(),
        )
        fp_after = fingerprint_model_spec(
            spec,
            {},
            4,
            variable_coverage_fingerprint=matrix_after.fingerprint(),
        )
        assert fp_before != fp_after

    def test_editing_an_administrative_field_does_not_stale_the_fingerprint(self):
        """A change confined to `fit_relevant_fields()`-excluded fields
        (here, `owner`) must not change the matrix's own fingerprint, and
        therefore must not stale `fingerprint_model_spec` either."""
        from ancestry_mmm.core.coverage import (
            CoverageSegment,
            FrequencyMetadata,
            VariableCoverageMatrix,
            VariableCoverageRecord,
        )

        frequency = FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class="flow_count",
        )
        segments = (
            CoverageSegment(
                period_start="2026-01-01", period_end="2026-01-07", state="unknown"
            ),
        )
        record_a = VariableCoverageRecord(
            variable_id="tv_spend",
            source_id="media_source",
            source_version=1,
            market="UK",
            frequency=frequency,
            coverage_segments=segments,
            owner="analyst-a",
        )
        record_b = VariableCoverageRecord(
            variable_id="tv_spend",
            source_id="media_source",
            source_version=1,
            market="UK",
            frequency=frequency,
            coverage_segments=segments,
            owner="analyst-b",
        )
        matrix_a = VariableCoverageMatrix(
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-01-01",
            records=(record_a,),
        )
        matrix_b = VariableCoverageMatrix(
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-01-01",
            records=(record_b,),
        )
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(
            spec, {}, 4, variable_coverage_fingerprint=matrix_a.fingerprint()
        )
        fp_b = fingerprint_model_spec(
            spec, {}, 4, variable_coverage_fingerprint=matrix_b.fingerprint()
        )
        assert fp_a == fp_b


class TestFingerprintModelSpecMarketConfig:
    def _config_with(self, *, currency=None, descriptors=None, media_unit=None) -> dict:
        profile = MarketProfile(
            market="UK",
            currency=currency or MarketCurrency(),
            descriptors=descriptors or MarketDescriptors(),
        )
        config = MarketSpecConfig(market_profiles={"UK": profile})
        if media_unit is not None:
            config.set_media_unit_config(media_unit)
        return config.to_dict()

    def test_no_market_spec_config_is_backward_compatible_with_omitting_the_argument(
        self,
    ):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, market_spec_config=None
        )
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(
            spec, {}, 4, market_spec_config={}
        )

    def test_changed_market_currency_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        config_a = self._config_with(currency=MarketCurrency(local_currency="GBP"))
        config_b = self._config_with(currency=MarketCurrency(local_currency="USD"))
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a != fp_b

    def test_changed_channel_media_unit_mapping_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        config_a = self._config_with(
            media_unit=ChannelMediaUnitConfig(
                market="UK", channel="TV", spend_column="TV_Spend"
            )
        )
        config_b = self._config_with(
            media_unit=ChannelMediaUnitConfig(
                market="UK",
                channel="TV",
                spend_column="TV_Spend",
                response_unit_column="TV_GRPs",
                unit_type="GRPs",
            )
        )
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a != fp_b

    def test_changed_cost_basis_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        config_a = self._config_with(
            media_unit=ChannelMediaUnitConfig(
                market="UK", channel="TV", spend_column="TV_Spend", cost_basis="CPM"
            )
        )
        config_b = self._config_with(
            media_unit=ChannelMediaUnitConfig(
                market="UK",
                channel="TV",
                spend_column="TV_Spend",
                cost_basis="Cost per GRP",
            )
        )
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a != fp_b

    def test_changed_market_descriptors_do_not_change_the_fingerprint(self):
        # The descriptive/model-relevant boundary: population, awareness etc.
        # are never read by any calculation (core/market_config.py's own
        # docstring), so editing them must not invalidate an approval.
        spec = {"markets": ["UK"]}
        config_a = self._config_with(
            descriptors=MarketDescriptors(population=1_000_000, region="North")
        )
        config_b = self._config_with(
            descriptors=MarketDescriptors(population=5_000_000, region="South")
        )
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a == fp_b


# ---------------------------------------------------------------------------
# Posterior fingerprint
# ---------------------------------------------------------------------------


class TestFingerprintPosterior:
    def _params(self, beta_tv=0.1):
        return {
            "decay_rate": {"TV": 0.5, "Search": 0.2},
            "hill_K": {"TV": 1000.0, "Search": 500.0},
            "beta": {"New": {"TV": beta_tv}, "Winback": {"TV": 0.05}},
            "gamma_fourier": {"New": np.array([1.0, 2.0, 3.0])},
        }

    def test_identical_params_same_fingerprint(self):
        assert fingerprint_posterior(self._params()) == fingerprint_posterior(
            self._params()
        )

    def test_changed_param_changes_fingerprint(self):
        assert fingerprint_posterior(
            self._params(beta_tv=0.1)
        ) != fingerprint_posterior(self._params(beta_tv=0.2))

    def test_reordered_dict_keys_do_not_change_fingerprint(self):
        params_a = self._params()
        params_b = {
            "gamma_fourier": params_a["gamma_fourier"],
            "beta": params_a["beta"],
            "hill_K": params_a["hill_K"],
            "decay_rate": params_a["decay_rate"],
        }
        assert fingerprint_posterior(params_a) == fingerprint_posterior(params_b)

    def test_array_order_is_meaningful(self):
        params_a = {"gamma_fourier": {"New": np.array([1.0, 2.0, 3.0])}}
        params_b = {"gamma_fourier": {"New": np.array([3.0, 2.0, 1.0])}}
        assert fingerprint_posterior(params_a) != fingerprint_posterior(params_b)

    def test_array_shape_matters(self):
        params_a = {"gamma_fourier": {"New": np.array([1.0, 2.0])}}
        params_b = {"gamma_fourier": {"New": np.array([[1.0, 2.0]])}}
        assert fingerprint_posterior(params_a) != fingerprint_posterior(params_b)

    def test_works_on_a_real_fh_posterior_params_dataclass(self):
        from ancestry_mmm.core.predict import FHPosteriorParams

        params = FHPosteriorParams(
            decay_rate={"TV": 0.5},
            hill_K={"TV": 1000.0},
            hill_S={"TV": 1.0},
            beta={"New": {"TV": 0.1}},
            pathway_strength={},
            promo_coef={"New": 0.1},
            market_offset={"UK": {"New": 0.0}},
            intercept={"New": 2.0},
            trend_coef={"New": 0.0},
            gamma_fourier={"New": np.zeros(6)},
            alpha={"New": 5.0},
            control_coef={},
            outcome_control_coef={},
        )
        fp1 = fingerprint_posterior(params)
        fp2 = fingerprint_posterior(params)
        assert fp1 == fp2
        assert isinstance(fp1, str) and len(fp1) == 64  # sha256 hexdigest
