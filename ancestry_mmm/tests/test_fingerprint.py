import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
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
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=4, freq="W"),
        "market": ["UK", "UK", "UK", "UK"],
        "TV_Brand": [100.0, 200.0, 150.0, 175.0],
        "fh_new_gsa": [10, 12, 11, 13],
    })


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
        assert fingerprint_model_spec(spec_a, {"decay_mu": 0.5}, 4) == fingerprint_model_spec(spec_b, {"decay_mu": 0.5}, 4)

    def test_changed_spec_changes_fingerprint(self):
        spec_a = {"markets": ["UK"], "channels": ["TV"]}
        spec_b = {"markets": ["UK", "Australia"], "channels": ["TV"]}
        assert fingerprint_model_spec(spec_a, {}, 4) != fingerprint_model_spec(spec_b, {}, 4)

    def test_changed_prior_changes_fingerprint(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {"decay_mu": 0.5}, 4) != fingerprint_model_spec(spec, {"decay_mu": 0.7}, 4)

    def test_changed_dna_lag_weeks_changes_fingerprint(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) != fingerprint_model_spec(spec, {}, 6)

    def test_list_order_is_preserved_and_meaningful(self):
        spec_a = {"channels": ["TV", "Search"]}
        spec_b = {"channels": ["Search", "TV"]}
        assert fingerprint_model_spec(spec_a, {}, 4) != fingerprint_model_spec(spec_b, {}, 4)

    def test_model_type_defaults_to_shared_and_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, model_type="shared")

    def test_market_specific_model_type_changes_the_fingerprint(self):
        spec = {"markets": ["UK", "Australia"]}
        shared_fp = fingerprint_model_spec(spec, {}, 4, model_type="shared")
        market_specific_fp = fingerprint_model_spec(spec, {}, 4, model_type="market_specific")
        assert shared_fp != market_specific_fp

    def test_switching_model_type_changes_the_fingerprint_even_with_identical_spec_and_priors(self):
        # The scenario this guards against: a user retrains under a different
        # model structure without touching the spec/priors/lag at all - the
        # fingerprint must still change so a stale approval gets invalidated.
        spec = {"markets": ["UK", "Australia"]}
        prior_config = {"decay_mu": 0.5}
        fp_a = fingerprint_model_spec(spec, prior_config, 4, model_type="shared")
        fp_c = fingerprint_model_spec(spec, prior_config, 4, model_type="market_specific")
        assert fp_a != fp_c


# ---------------------------------------------------------------------------
# Model-specification fingerprint: pipeline_steps + market_spec_config
# (PR1 3.3 - see docs/decision_log.md for the descriptive/model-relevant
# boundary this codifies)
# ---------------------------------------------------------------------------

class TestFingerprintModelSpecPipelineSteps:
    def test_no_pipeline_steps_is_backward_compatible_with_omitting_the_argument(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, pipeline_steps=None)
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, pipeline_steps=[])

    def test_changed_pipeline_steps_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        steps_a = [{"op": "log_transform", "column": "TV_Brand"}]
        steps_b = [{"op": "log_transform", "column": "TV_Brand"}, {"op": "fill_na", "column": "Search"}]
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
        assert fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps) == fingerprint_model_spec(
            spec, {}, 4, pipeline_steps=list(steps)
        )


class TestFingerprintModelSpecDirectDnaSegments:
    """direct_dna_segments (which segments get a direct DNA-media pathway -
    i.e. which DNA-kit outcomes are actually included in a fit) must be
    fingerprinted - the instruction document's audit-confirmed gap: toggling
    DNA-kit outcomes in/out of a fit changed meta.segments without changing
    model_spec/prior_config/pipeline_steps/market_spec_config at all, so an
    approval could stay "matching" across two structurally different fits."""

    def test_no_direct_dna_segments_is_backward_compatible_with_omitting_the_argument(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, direct_dna_outcome_ids=None)
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, direct_dna_outcome_ids=[])

    def test_adding_a_dna_kit_segment_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_none = fingerprint_model_spec(spec, {}, 4, direct_dna_outcome_ids=["DNA_CrossSell"])
        fp_with_kit = fingerprint_model_spec(spec, {}, 4, direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"])
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
        fp_included = fingerprint_model_spec(spec, {}, 4, direct_dna_outcome_ids=["New", "New Customer"])
        fp_excluded = fingerprint_model_spec(spec, {}, 4, direct_dna_outcome_ids=["New"])
        assert fp_included != fp_excluded


class TestFingerprintModelSpecOutcomeCatalogue:
    """PR E.1: the full canonical outcome catalogue must be fingerprinted -
    direct_dna_outcome_ids alone only covers DNA-kit membership, not a
    relabelled metric/unit/role/source_column/value_weight, so those changes
    used to leave an approval wrongly "matching" a structurally different
    fit (test case: "outcome catalogue change invalidates approval")."""

    def _catalogue(self, **overrides):
        row = {
            "outcome_id": "fh_new_gsa", "product": "Family History", "segment": "New", "metric": "GSA",
            "unit": "GSA", "source_column": "col_a", "role": "primary", "included_in_fit": True,
            "value_weight": 100.0, "value_currency": "USD",
        }
        row.update(overrides)
        return [row]

    def test_omitting_outcome_catalogue_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, outcome_catalogue=None)
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, outcome_catalogue=[])

    def test_adding_an_outcome_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_one = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue())
        two = self._catalogue() + [{
            "outcome_id": "fh_new_signup", "product": "Family History", "segment": "New", "metric": "Sign-up",
            "unit": "Sign-up", "source_column": "col_b", "role": "primary", "included_in_fit": True,
            "value_weight": 20.0, "value_currency": "USD",
        }]
        fp_two = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=two)
        assert fp_one != fp_two

    def test_relabelling_gsa_to_signup_changes_the_fingerprint(self):
        # Exactly the scenario the instruction document calls out:
        # "changing sign-up to GSA" must invalidate approval.
        spec = {"markets": ["UK"]}
        fp_gsa = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(metric="GSA"))
        fp_signup = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(metric="Sign-up"))
        assert fp_gsa != fp_signup

    def test_changing_source_column_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(source_column="col_a"))
        fp_b = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(source_column="col_b"))
        assert fp_a != fp_b

    def test_changing_unit_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(unit="GSA"))
        fp_b = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(unit="count"))
        assert fp_a != fp_b

    def test_changing_role_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(role="primary"))
        fp_b = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(role="secondary"))
        assert fp_a != fp_b

    def test_toggling_included_in_fit_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(included_in_fit=True))
        fp_b = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(included_in_fit=False))
        assert fp_a != fp_b

    def test_changing_value_weight_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(value_weight=100.0))
        fp_b = fingerprint_model_spec(spec, {}, 4, outcome_catalogue=self._catalogue(value_weight=150.0))
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


class TestFingerprintModelSpecFunnelLinks:
    """PR E.2: funnel links are diagnostic-only configuration but still
    calculation-relevant to what's displayed, so they're fingerprinted the
    same way as the outcome catalogue."""

    def test_omitting_funnel_links_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, funnel_links=None)
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, funnel_links=[])

    def test_adding_a_funnel_link_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_none = fingerprint_model_spec(spec, {}, 4, funnel_links=[])
        fp_one = fingerprint_model_spec(spec, {}, 4, funnel_links=[
            {"upstream_outcome_id": "fh_new_signup", "downstream_outcome_id": "fh_new_gsa"},
        ])
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
        fp_a = fingerprint_model_spec(spec, {}, 4, funnel_links=[
            {"upstream_outcome_id": "signup", "downstream_outcome_id": "gsa"},
        ])
        fp_b = fingerprint_model_spec(spec, {}, 4, funnel_links=[
            {"upstream_outcome_id": "signup", "downstream_outcome_id": "other_gsa"},
        ])
        assert fp_a != fp_b


class TestFingerprintModelSpecMediaOutcomePathways:
    """PR F: the pathway catalogue doesn't (yet) change what gets fitted,
    but is calculation-adjacent metadata a future estimation PR will read -
    fingerprinted the same way as funnel_links."""

    def test_omitting_media_outcome_pathways_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, media_outcome_pathways=None)
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, media_outcome_pathways=[])

    def test_adding_a_pathway_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_none = fingerprint_model_spec(spec, {}, 4, media_outcome_pathways=[])
        fp_one = fingerprint_model_spec(spec, {}, 4, media_outcome_pathways=[
            {"channel": "DNA_Media", "target_outcome_id": "dna_new_kit", "role": "primary_direct"},
        ])
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
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, activity_fit_fingerprint=None)
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, activity_fit_fingerprint="")

    def test_a_different_activity_fit_fingerprint_changes_the_model_spec_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, activity_fit_fingerprint="fp-intervention")
        fp_b = fingerprint_model_spec(spec, {}, 4, activity_fit_fingerprint="fp-mediator")
        assert fp_a != fp_b

    def test_using_the_real_activity_fit_fingerprint_function_end_to_end(self):
        from ancestry_mmm.core.activities import ActivityDefinition, activity_fit_fingerprint

        spec = {"markets": ["UK"]}
        intervention = ActivityDefinition(
            activity_id="tv-paid", channel="TV_Paid", activity_ownership="paid",
            model_role="intervention", economic_treatment="paid_media_cost",
            planning_eligibility="optimisable", source="finance",
        )
        mediator = ActivityDefinition(
            activity_id="tv-paid", channel="TV_Paid", activity_ownership="paid",
            model_role="mediator", economic_treatment="paid_media_cost",
            planning_eligibility="fixed", source="finance",
        )
        fp_intervention = fingerprint_model_spec(
            spec, {}, 4, activity_fit_fingerprint=activity_fit_fingerprint([intervention]),
        )
        fp_mediator = fingerprint_model_spec(
            spec, {}, 4, activity_fit_fingerprint=activity_fit_fingerprint([mediator]),
        )
        # model_role is fit-relevant - intervention vs mediator must stale the fit.
        assert fp_intervention != fp_mediator

        fp_intervention_again = fingerprint_model_spec(
            spec, {}, 4, activity_fit_fingerprint=activity_fit_fingerprint([intervention]),
        )
        assert fp_intervention == fp_intervention_again

    def test_non_fit_relevant_activity_fields_do_not_change_the_fingerprint(self):
        from ancestry_mmm.core.activities import ActivityDefinition, activity_fit_fingerprint

        spec = {"markets": ["UK"]}
        draft = ActivityDefinition(
            activity_id="tv-paid", channel="TV_Paid", activity_ownership="paid",
            model_role="intervention", economic_treatment="paid_media_cost",
            planning_eligibility="optimisable", source="finance",
            approval_status="draft",
        )
        approved = ActivityDefinition(
            activity_id="tv-paid", channel="TV_Paid", activity_ownership="paid",
            model_role="intervention", economic_treatment="response_only",
            planning_eligibility="fixed", source="finance",
            approval_status="approved", approved_by="reviewer", approved_at="2026-01-01",
        )
        # economic_treatment, planning_eligibility and approval metadata are
        # not fit-relevant - only model_role/model-input column/pathway_ids
        # are (they don't change what gets fitted).
        fp_draft = fingerprint_model_spec(
            spec, {}, 4, activity_fit_fingerprint=activity_fit_fingerprint([draft]),
        )
        fp_approved = fingerprint_model_spec(
            spec, {}, 4, activity_fit_fingerprint=activity_fit_fingerprint([approved]),
        )
        assert fp_draft == fp_approved

    def test_changing_a_pathway_role_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        fp_a = fingerprint_model_spec(spec, {}, 4, media_outcome_pathways=[
            {"channel": "DNA_Media", "target_outcome_id": "dna_new_kit", "role": "primary_direct"},
        ])
        fp_b = fingerprint_model_spec(spec, {}, 4, media_outcome_pathways=[
            {"channel": "DNA_Media", "target_outcome_id": "dna_new_kit", "role": "exploratory_cross_product"},
        ])
        assert fp_a != fp_b


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

    def test_no_market_spec_config_is_backward_compatible_with_omitting_the_argument(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, market_spec_config=None)
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, market_spec_config={})

    def test_changed_market_currency_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        config_a = self._config_with(currency=MarketCurrency(local_currency="GBP"))
        config_b = self._config_with(currency=MarketCurrency(local_currency="USD"))
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a != fp_b

    def test_changed_channel_media_unit_mapping_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        config_a = self._config_with(media_unit=ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend"))
        config_b = self._config_with(
            media_unit=ChannelMediaUnitConfig(
                market="UK", channel="TV", spend_column="TV_Spend", response_unit_column="TV_GRPs", unit_type="GRPs",
            )
        )
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a != fp_b

    def test_changed_cost_basis_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        config_a = self._config_with(
            media_unit=ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend", cost_basis="CPM")
        )
        config_b = self._config_with(
            media_unit=ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend", cost_basis="Cost per GRP")
        )
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a != fp_b

    def test_changed_market_descriptors_do_not_change_the_fingerprint(self):
        # The descriptive/model-relevant boundary: population, awareness etc.
        # are never read by any calculation (core/market_config.py's own
        # docstring), so editing them must not invalidate an approval.
        spec = {"markets": ["UK"]}
        config_a = self._config_with(descriptors=MarketDescriptors(population=1_000_000, region="North"))
        config_b = self._config_with(descriptors=MarketDescriptors(population=5_000_000, region="South"))
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
        assert fingerprint_posterior(self._params()) == fingerprint_posterior(self._params())

    def test_changed_param_changes_fingerprint(self):
        assert fingerprint_posterior(self._params(beta_tv=0.1)) != fingerprint_posterior(self._params(beta_tv=0.2))

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
            decay_rate={"TV": 0.5}, hill_K={"TV": 1000.0}, hill_S={"TV": 1.0},
            beta={"New": {"TV": 0.1}}, pathway_strength={}, promo_coef={"New": 0.1},
            market_offset={"UK": {"New": 0.0}}, intercept={"New": 2.0}, trend_coef={"New": 0.0},
            gamma_fourier={"New": np.zeros(6)}, alpha={"New": 5.0}, control_coef={}, outcome_control_coef={},
        )
        fp1 = fingerprint_posterior(params)
        fp2 = fingerprint_posterior(params)
        assert fp1 == fp2
        assert isinstance(fp1, str) and len(fp1) == 64  # sha256 hexdigest
