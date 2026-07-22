"""Tests for core.outcomes - the canonical outcome schema (PR E, "make
OutcomeDefinition the source of truth" - see docs/decision_log.md)."""

from types import SimpleNamespace

from ancestry_mmm.core.outcomes import (
    DNA,
    DNA_SEGMENT_COMBINED,
    DNA_SEGMENT_EXISTING_FH,
    DNA_SEGMENT_NEW,
    FAMILY_HISTORY,
    METRIC_GSA,
    METRIC_KIT_SALE,
    METRIC_SIGNUP,
    METRIC_KEY_CUSTOM,
    METRIC_KEY_DNA_KIT_SALE,
    METRIC_KEY_FH_GSA,
    METRIC_KEY_FH_SIGNUP,
    METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    METRIC_KEY_FH_NET_BILLTHROUGH_RATE,
    METRIC_KEY_FH_GSA_FINANCE_DATE,
    METRIC_KEY_DNA_KIT_SALE_SELF_ACTIVATED,
    METRIC_KEY_DNA_KIT_SALE_GIFTED_ACTIVATED,
    METRIC_KEY_DNA_KIT_SALE_UNACTIVATED,
    METRIC_KEY_DNA_KIT_SALE_TOTAL,
    AGGREGATION_TYPES,
    DATE_BASIS_VALUES,
    METRIC_REGISTRY,
    OUTCOME_ROLES,
    OUTCOME_STATUSES,
    DRIFT_STATUSES,
    ELIGIBILITY_FLAGS,
    MetricDefinition,
    OutcomeDefinition,
    dna_kit_outcome_columns,
    dna_outcomes_from_columns,
    dna_kit_sale_outcome_ids,
    fh_gsa_outcome_ids,
    fh_outcomes_from_spec,
    fh_signup_outcome_ids,
    has_blocking_drift,
    included_outcomes,
    infer_legacy_fh_dna_cross_sell_outcome_id,
    normalize_metric_key,
    official_total_outcome_ids,
    outcome_catalogue_at_fit_by_id,
    outcome_catalogue_fingerprint_payload,
    outcome_drift_status,
    outcome_eligibility,
    outcome_requires_opt_in,
    outcome_status,
    outcome_was_modelled,
    outcomes_drift_dataframe,
    outcomes_to_dataframe,
    resolve_outcome_definitions,
    select_outcome_ids,
    validate_fh_dna_cross_sell_outcome_id,
    validate_outcome_definitions,
)


def _meta(outcome_ids, id_to_product, id_to_metric, id_to_role=None, kit_only=None):
    """Minimal FHModelMeta-shaped stand-in - select_outcome_ids/the named
    totals only ever read these attributes, so a real FHModelMeta (which
    would pull in core.hierarchical_model) isn't needed here."""
    return SimpleNamespace(
        outcome_ids=outcome_ids,
        outcome_id_to_product=id_to_product,
        outcome_id_to_metric=id_to_metric,
        outcome_id_to_unit={},
        outcome_id_to_role=id_to_role or {},
        kit_only_outcome_ids=kit_only or [],
    )


class TestOutcomeDefinitionRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        outcome = OutcomeDefinition(
            outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric="GSA",
            source_column="GSA_New", value_weight=180.0,
        )
        restored = OutcomeDefinition.from_dict(outcome.to_dict())
        assert restored == outcome

    def test_from_dict_ignores_unknown_keys(self):
        d = {
            "outcome_id": "fh_new", "product": FAMILY_HISTORY, "segment": "New", "metric": "GSA",
            "source_column": "GSA_New", "value_weight": 180.0, "some_future_field": "ignored",
        }
        restored = OutcomeDefinition.from_dict(d)
        assert restored.outcome_id == "fh_new"

    def test_from_dict_translates_legacy_column_key(self):
        d = {"outcome_id": "fh_new", "product": FAMILY_HISTORY, "segment": "New", "metric": "GSA", "column": "GSA_New"}
        restored = OutcomeDefinition.from_dict(d)
        assert restored.source_column == "GSA_New"

    def test_from_dict_prefers_source_column_over_legacy_column_if_both_present(self):
        d = {
            "outcome_id": "fh_new", "product": FAMILY_HISTORY, "segment": "New", "metric": "GSA",
            "column": "legacy_col", "source_column": "GSA_New",
        }
        restored = OutcomeDefinition.from_dict(d)
        assert restored.source_column == "GSA_New"

    def test_value_weight_defaults_to_none(self):
        outcome = OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c")
        assert outcome.value_weight is None

    def test_role_defaults_to_primary(self):
        outcome = OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c")
        assert outcome.role == "primary"

    def test_included_in_fit_defaults_to_true(self):
        outcome = OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c")
        assert outcome.included_in_fit is True

    def test_exclusion_reason_defaults_to_none(self):
        outcome = OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c")
        assert outcome.exclusion_reason is None

    def test_unit_derives_from_metric_registry_when_not_given(self):
        fh = OutcomeDefinition(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c")
        dna = OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", source_column="c")
        assert fh.unit == "GSA"
        assert dna.unit == "kit"

    def test_explicit_unit_is_not_overridden(self):
        outcome = OutcomeDefinition(
            outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric="Sign-up",
            source_column="c", unit="sign-up",
        )
        assert outcome.unit == "sign-up"

    def test_legacy_bundle_without_new_fields_loads_with_defaults(self):
        d = {"outcome_id": "fh_new", "product": FAMILY_HISTORY, "segment": "New", "metric": "GSA", "column": "GSA_New"}
        restored = OutcomeDefinition.from_dict(d)
        assert restored.role == "primary"
        assert restored.included_in_fit is True
        assert restored.exclusion_reason is None


# ---------------------------------------------------------------------------
# PR E.2 required test cases 1-3: unit defaults driven by the metric
# registry (not product alone), metric display-variant normalisation, and
# custom metrics requiring an explicit unit.
# ---------------------------------------------------------------------------

class TestMetricRegistryAndUnitDefaults:
    def test_blank_unit_on_fh_signup_does_not_become_gsa(self):
        # Required test case 1 - the confirmed pitfall: __post_init__ used to
        # default every Family History outcome's unit to "GSA" regardless of
        # metric, which was simply wrong for a Family History *sign-up*.
        signup = OutcomeDefinition(
            outcome_id="fh_new_signup", product=FAMILY_HISTORY, segment="New", metric="Sign-up",
            source_column="c",
        )
        assert signup.unit == "sign-up"
        assert signup.unit != "GSA"

    def test_metric_key_derives_from_metric_for_the_three_builtin_metrics(self):
        gsa = OutcomeDefinition(outcome_id="a", product=FAMILY_HISTORY, segment="S", metric="GSA", source_column="c")
        signup = OutcomeDefinition(outcome_id="b", product=FAMILY_HISTORY, segment="S", metric="Sign-up", source_column="c")
        kit = OutcomeDefinition(outcome_id="c", product=DNA, segment="S", metric="Kit sale", source_column="c")
        assert gsa.metric_key == METRIC_KEY_FH_GSA
        assert signup.metric_key == METRIC_KEY_FH_SIGNUP
        assert kit.metric_key == METRIC_KEY_DNA_KIT_SALE

    def test_metric_display_variants_migrate_to_canonical_keys(self):
        # Required test case 2. A small, explicit, known-variant table -
        # never fuzzy matching.
        for variant in ("Signup", "signups", "Sign Up", "SIGN-UPS"):
            assert normalize_metric_key(variant) == METRIC_KEY_FH_SIGNUP, variant
        for variant in ("Kit Sale", "kit sales", "DNA Kit Sale"):
            assert normalize_metric_key(variant) == METRIC_KEY_DNA_KIT_SALE, variant
        for variant in ("gsa", "Family History GSA"):
            assert normalize_metric_key(variant) == METRIC_KEY_FH_GSA, variant

    def test_ambiguous_custom_metric_is_never_guessed(self):
        assert normalize_metric_key("Repeat purchase") == METRIC_KEY_CUSTOM
        assert normalize_metric_key("") == METRIC_KEY_CUSTOM
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="Repeat purchase", source_column="c",
        )
        assert outcome.metric_key == METRIC_KEY_CUSTOM

    def test_custom_metrics_require_explicit_units(self):
        # Required test case 3 - a custom/unrecognised metric_key gets no
        # default unit at all; validate_outcome_definitions's "no unit set"
        # check is what actually enforces the requirement.
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="Repeat purchase", source_column="c",
        )
        assert outcome.unit == ""
        errors = validate_outcome_definitions([outcome])
        assert any("no unit set" in e for e in errors)

        outcome_with_unit = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="Repeat purchase", source_column="c",
            unit="repeat purchase",
        )
        errors2 = validate_outcome_definitions([outcome_with_unit])
        assert not any("no unit set" in e for e in errors2)

    def test_explicit_metric_key_overrides_derivation(self):
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="Some custom label",
            source_column="c", metric_key=METRIC_KEY_FH_GSA,
        )
        assert outcome.metric_key == METRIC_KEY_FH_GSA
        # unit still derives from the (explicitly given) metric_key, not
        # from the free-text metric label.
        assert outcome.unit == "GSA"

    def test_metric_registry_entries_are_internally_consistent(self):
        for key, definition in METRIC_REGISTRY.items():
            assert isinstance(definition, MetricDefinition)
            assert definition.metric_key == key
            assert definition.default_unit


class TestPlannedMetricKeysAndAggregationType:
    """PR F (net bill-through / DNA purchase-type roadmap) - the seven new
    metric keys are registered with correct product/unit/aggregation_type,
    and OutcomeDefinition's new aggregation_type field derives from them the
    same way unit already does. No transformation pipeline exists yet for
    any of these outcomes (see docs/media_outcome_pathways.md) - this is
    catalogue/registry-level coverage only."""

    PLANNED_KEYS = (
        METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
        METRIC_KEY_FH_NET_BILLTHROUGH_RATE,
        METRIC_KEY_FH_GSA_FINANCE_DATE,
        METRIC_KEY_DNA_KIT_SALE_SELF_ACTIVATED,
        METRIC_KEY_DNA_KIT_SALE_GIFTED_ACTIVATED,
        METRIC_KEY_DNA_KIT_SALE_UNACTIVATED,
        METRIC_KEY_DNA_KIT_SALE_TOTAL,
    )

    def test_all_planned_keys_are_registered(self):
        for key in self.PLANNED_KEYS:
            assert key in METRIC_REGISTRY, key

    def test_net_billthrough_rate_is_the_only_rate_aggregation_builtin(self):
        rate_keys = [k for k, d in METRIC_REGISTRY.items() if d.aggregation_type == "rate"]
        assert rate_keys == [METRIC_KEY_FH_NET_BILLTHROUGH_RATE]

    def test_net_billthrough_rate_is_disallowed_in_optimiser_and_cpa(self):
        definition = METRIC_REGISTRY[METRIC_KEY_FH_NET_BILLTHROUGH_RATE]
        assert definition.allowed_in_optimiser is False
        assert definition.allowed_in_cpa is False

    def test_every_other_planned_key_is_a_count_allowed_everywhere(self):
        for key in self.PLANNED_KEYS:
            if key == METRIC_KEY_FH_NET_BILLTHROUGH_RATE:
                continue
            definition = METRIC_REGISTRY[key]
            assert definition.aggregation_type == "count"
            assert definition.allowed_in_optimiser is True
            assert definition.allowed_in_cpa is True

    def test_dna_kit_sale_total_is_distinct_from_dna_kit_sale(self):
        # The roadmap lists dna_kit_sale_total as a distinct key from the
        # pre-existing generic dna_kit_sale - not a rename, not an alias.
        assert METRIC_KEY_DNA_KIT_SALE_TOTAL != METRIC_KEY_DNA_KIT_SALE

    def test_outcome_definition_aggregation_type_derives_from_registry(self):
        rate_outcome = OutcomeDefinition(
            outcome_id="fh_billthrough_rate", product=FAMILY_HISTORY, segment="New",
            metric="Net bill-through rate", source_column="c", role="secondary",
        )
        assert rate_outcome.metric_key == METRIC_KEY_FH_NET_BILLTHROUGH_RATE
        assert rate_outcome.aggregation_type == "rate"

        count_outcome = OutcomeDefinition(
            outcome_id="dna_self", product=DNA, segment="New Customer",
            metric="Kit sale (self-activated)", source_column="c",
        )
        assert count_outcome.metric_key == METRIC_KEY_DNA_KIT_SALE_SELF_ACTIVATED
        assert count_outcome.aggregation_type == "count"

    def test_custom_metric_defaults_aggregation_type_to_count(self):
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="Repeat purchase",
            source_column="c", unit="repeat purchase",
        )
        assert outcome.metric_key == METRIC_KEY_CUSTOM
        assert outcome.aggregation_type == "count"

    def test_explicit_aggregation_type_is_preserved(self):
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="Custom index",
            source_column="c", unit="index points", aggregation_type="index",
        )
        assert outcome.aggregation_type == "index"

    def test_date_basis_and_maturity_required_default_to_none(self):
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="GSA", source_column="c",
        )
        assert outcome.date_basis is None
        assert outcome.maturity_required is None

    def test_date_basis_can_be_set_explicitly(self):
        outcome = OutcomeDefinition(
            outcome_id="fh_billthrough", product=FAMILY_HISTORY, segment="New",
            metric="Net bill-through count", source_column="c",
            date_basis="signup_date_attributed", maturity_required=True,
        )
        assert outcome.date_basis == "signup_date_attributed"
        assert outcome.maturity_required is True

    def test_date_basis_values_matches_roadmap_vocabulary(self):
        assert set(DATE_BASIS_VALUES) == {
            "event_date", "signup_date_attributed", "billing_date", "purchase_date", "activation_date",
        }


class TestValidateOutcomeDefinitionsAggregationRules:
    """PR F - "do not allow rate outcomes into count totals or count-based
    CPA": a rate-aggregation outcome must not resolve eligible for the
    official total or optimisation."""

    def _rate_outcome(self, **overrides):
        defaults = dict(
            outcome_id="fh_billthrough_rate", product=FAMILY_HISTORY, segment="New",
            metric="Net bill-through rate", source_column="c", role="secondary",
            include_in_official_total=None, include_in_optimisation=None,
        )
        defaults.update(overrides)
        return OutcomeDefinition(**defaults)

    def test_rate_outcome_with_correct_secondary_role_has_no_error(self):
        outcome = self._rate_outcome()
        errors = validate_outcome_definitions([outcome])
        assert not any("rate" in e.lower() for e in errors)

    def test_rate_outcome_left_at_default_primary_role_is_an_error(self):
        outcome = self._rate_outcome(role="primary")
        errors = validate_outcome_definitions([outcome])
        assert any("eligible for the official total" in e for e in errors)
        assert any("eligible for optimisation" in e for e in errors)

    def test_rate_outcome_with_explicit_optimisation_override_is_an_error(self):
        outcome = self._rate_outcome(include_in_optimisation=True)
        errors = validate_outcome_definitions([outcome])
        assert any("eligible for optimisation" in e for e in errors)

    def test_unknown_aggregation_type_is_an_error(self):
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="GSA", source_column="c",
            aggregation_type="not_a_real_type",
        )
        errors = validate_outcome_definitions([outcome])
        assert any("aggregation_type" in e for e in errors)

    def test_unknown_date_basis_is_an_error(self):
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="GSA", source_column="c",
            date_basis="not_a_real_basis",
        )
        errors = validate_outcome_definitions([outcome])
        assert any("date_basis" in e for e in errors)

    def test_aggregation_types_constant_matches_roadmap_vocabulary(self):
        assert set(AGGREGATION_TYPES) == {"count", "rate", "currency", "index"}


class TestOutcomeEligibility:
    def test_primary_role_defaults_everything_true(self):
        outcome = OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="GSA", source_column="c")
        eligibility = outcome_eligibility(outcome)
        assert set(eligibility) == set(ELIGIBILITY_FLAGS)
        assert all(eligibility.values())

    def test_diagnostic_role_defaults_everything_false(self):
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="GSA", source_column="c", role="diagnostic",
        )
        eligibility = outcome_eligibility(outcome)
        assert not any(eligibility.values())

    def test_funnel_intermediate_role_defaults(self):
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="Sign-up", source_column="c",
            role="funnel_intermediate",
        )
        eligibility = outcome_eligibility(outcome)
        assert eligibility["include_in_default_reporting"] is True
        assert eligibility["include_in_official_total"] is False
        assert eligibility["include_in_value"] is False
        assert eligibility["include_in_optimisation"] is False

    def test_secondary_role_defaults(self):
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="GSA", source_column="c", role="secondary",
        )
        eligibility = outcome_eligibility(outcome)
        assert eligibility["include_in_default_reporting"] is True
        assert eligibility["include_in_official_total"] is False
        assert eligibility["include_in_value"] is True
        assert eligibility["include_in_optimisation"] is False

    def test_explicit_override_wins_over_role_default(self):
        # A secondary outcome explicitly opted back into optimisation.
        outcome = OutcomeDefinition(
            outcome_id="x", product=FAMILY_HISTORY, segment="S", metric="GSA", source_column="c",
            role="secondary", include_in_optimisation=True,
        )
        assert outcome_eligibility(outcome)["include_in_optimisation"] is True

        # A primary outcome explicitly excluded from value.
        outcome2 = OutcomeDefinition(
            outcome_id="y", product=FAMILY_HISTORY, segment="S", metric="GSA", source_column="c",
            include_in_value=False,
        )
        assert outcome_eligibility(outcome2)["include_in_value"] is False


class TestOutcomeRequiresOptIn:
    def test_family_history_does_not_require_opt_in(self):
        outcome = OutcomeDefinition(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c")
        assert outcome_requires_opt_in(outcome) is False

    def test_dna_requires_opt_in(self):
        outcome = OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", source_column="c")
        assert outcome_requires_opt_in(outcome) is True


class TestOutcomeWasModelled:
    def test_none_model_meta_is_always_false(self):
        outcome = OutcomeDefinition(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c")
        assert outcome_was_modelled(outcome, None) is False

    def test_true_when_outcome_id_is_in_the_fitted_models_outcome_ids(self):
        outcome = OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", source_column="c")

        class FakeMeta:
            outcome_ids = ["dna_new_kit", "fh_new"]

        assert outcome_was_modelled(outcome, FakeMeta()) is True

    def test_false_when_outcome_id_is_not_in_the_fitted_models_outcome_ids(self):
        outcome = OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", source_column="c")

        class FakeMeta:
            outcome_ids = ["fh_new", "fh_winback"]

        assert outcome_was_modelled(outcome, FakeMeta()) is False

    def test_shared_segment_does_not_cause_a_false_positive(self):
        # fh_new_signup and fh_new_gsa share segment="New" but are distinct
        # outcome_ids - only the one actually fitted should read as modelled.
        signup = OutcomeDefinition(outcome_id="fh_new_signup", product=FAMILY_HISTORY, segment="New", metric="Sign-up", source_column="c1")

        class FakeMeta:
            outcome_ids = ["fh_new_gsa"]

        assert outcome_was_modelled(signup, FakeMeta()) is False


class TestOutcomeStatus:
    def _outcome(self, column="kit_col", included_in_fit=True):
        return OutcomeDefinition(
            outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale",
            source_column=column, included_in_fit=included_in_fit,
        )

    def test_defaults_to_configured(self):
        assert outcome_status(self._outcome()) == "Configured"

    def test_excluded_takes_priority_over_configured(self):
        assert outcome_status(self._outcome(included_in_fit=False)) == "Excluded"

    def test_missing_source_column_when_never_prepared_or_fit(self):
        assert outcome_status(self._outcome(), available_columns={"other_col"}) == "Missing source column"

    def test_included_in_prepared_frame(self):
        assert outcome_status(self._outcome(), frame_outcome_ids=["dna_new_kit"]) == "Included in prepared frame"

    def test_included_in_fitted_run_takes_priority_over_prepared_frame(self):
        status = outcome_status(
            self._outcome(), frame_outcome_ids=["dna_new_kit"], model_meta_outcome_ids=["dna_new_kit"],
        )
        assert status == "Included in fitted run"

    def test_stale_when_column_vanishes_after_being_prepared(self):
        status = outcome_status(self._outcome(), available_columns={"other_col"}, frame_outcome_ids=["dna_new_kit"])
        assert status == "Stale after configuration changes"

    def test_stale_when_column_vanishes_after_being_fit(self):
        status = outcome_status(
            self._outcome(), available_columns={"other_col"},
            frame_outcome_ids=["dna_new_kit"], model_meta_outcome_ids=["dna_new_kit"],
        )
        assert status == "Stale after configuration changes"

    def test_every_returned_value_is_a_known_status(self):
        cases = [
            outcome_status(self._outcome()),
            outcome_status(self._outcome(included_in_fit=False)),
            outcome_status(self._outcome(), available_columns={"other_col"}),
            outcome_status(self._outcome(), frame_outcome_ids=["dna_new_kit"]),
            outcome_status(self._outcome(), model_meta_outcome_ids=["dna_new_kit"]),
        ]
        for status in cases:
            assert status in OUTCOME_STATUSES


class TestFhOutcomesFromSpec:
    def test_derives_one_outcome_per_segment(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New", "Winback": "GSA_Winback"})
        assert len(outcomes) == 2
        assert {o.segment for o in outcomes} == {"New", "Winback"}
        assert all(o.product == FAMILY_HISTORY for o in outcomes)
        assert all(o.metric == "GSA" for o in outcomes)

    def test_maps_source_column_correctly(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"})
        assert outcomes[0].source_column == "GSA_New"

    def test_picks_up_value_weight_from_segment_ltv(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"}, segment_ltv={"New": 180.0})
        assert outcomes[0].value_weight == 180.0

    def test_missing_ltv_entry_leaves_value_weight_none(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"}, segment_ltv={})
        assert outcomes[0].value_weight is None

    def test_empty_segment_outcomes_gives_empty_list(self):
        assert fh_outcomes_from_spec({}) == []

    def test_outcome_ids_are_deterministic_and_lowercase(self):
        outcomes = fh_outcomes_from_spec({"DNA_CrossSell": "GSA_DNA_CrossSell"})
        assert outcomes[0].outcome_id == "fh_dna_crosssell"

    def test_derived_outcomes_default_to_included_and_primary(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"})
        assert outcomes[0].included_in_fit is True
        assert outcomes[0].role == "primary"


class TestDnaOutcomesFromColumns:
    def test_no_columns_gives_empty_list(self):
        assert dna_outcomes_from_columns() == []

    def test_split_columns_give_two_outcomes(self):
        outcomes = dna_outcomes_from_columns(
            new_customer_column="DNA_Kit_New", existing_fh_column="DNA_Kit_Existing",
        )
        assert len(outcomes) == 2
        segments = {o.segment for o in outcomes}
        assert segments == {DNA_SEGMENT_NEW, DNA_SEGMENT_EXISTING_FH}
        assert all(o.product == DNA for o in outcomes)
        assert all(o.metric == "Kit sale" for o in outcomes)

    def test_only_new_customer_column_gives_one_outcome(self):
        outcomes = dna_outcomes_from_columns(new_customer_column="DNA_Kit_New")
        assert len(outcomes) == 1
        assert outcomes[0].segment == DNA_SEGMENT_NEW
        assert outcomes[0].source_column == "DNA_Kit_New"

    def test_combined_column_gives_one_combined_outcome(self):
        outcomes = dna_outcomes_from_columns(combined_column="DNA_Kit_Total")
        assert len(outcomes) == 1
        assert outcomes[0].segment == DNA_SEGMENT_COMBINED
        assert outcomes[0].source_column == "DNA_Kit_Total"

    def test_combined_takes_precedence_over_split_columns(self):
        outcomes = dna_outcomes_from_columns(
            new_customer_column="DNA_Kit_New", existing_fh_column="DNA_Kit_Existing",
            combined_column="DNA_Kit_Total",
        )
        assert len(outcomes) == 1
        assert outcomes[0].segment == DNA_SEGMENT_COMBINED

    def test_value_weights_are_carried_through(self):
        outcomes = dna_outcomes_from_columns(new_customer_column="DNA_Kit_New", value_weight_new=90.0)
        assert outcomes[0].value_weight == 90.0


class TestValidateOutcomeDefinitions:
    def test_no_errors_for_a_well_formed_set(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"}) + dna_outcomes_from_columns(new_customer_column="DNA_Kit_New")
        assert validate_outcome_definitions(outcomes) == []

    def test_missing_outcome_id_is_an_error(self):
        outcomes = [OutcomeDefinition(outcome_id="", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c")]
        errors = validate_outcome_definitions(outcomes)
        assert any("outcome_id" in e for e in errors)

    def test_duplicate_outcome_id_is_an_error(self):
        outcomes = [
            OutcomeDefinition(outcome_id="dup", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="a"),
            OutcomeDefinition(outcome_id="dup", product=FAMILY_HISTORY, segment="Winback", metric="GSA", source_column="b"),
        ]
        errors = validate_outcome_definitions(outcomes)
        assert any("Duplicate" in e for e in errors)

    def test_missing_source_column_is_an_error(self):
        outcomes = [OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="")]
        errors = validate_outcome_definitions(outcomes)
        assert any("source column" in e for e in errors)

    def test_unknown_product_is_an_error(self):
        outcomes = [OutcomeDefinition(outcome_id="x", product="Unknown Product", segment="New", metric="GSA", source_column="c")]
        errors = validate_outcome_definitions(outcomes)
        assert any("unknown product" in e for e in errors)

    def test_unknown_role_is_an_error(self):
        outcomes = [OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c", role="made_up")]
        errors = validate_outcome_definitions(outcomes)
        assert any("unknown role" in e for e in errors)

    def test_every_known_role_is_accepted(self):
        for role in OUTCOME_ROLES:
            outcomes = [OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c", role=role)]
            assert validate_outcome_definitions(outcomes) == []

    def test_mixing_combined_and_split_dna_outcomes_is_an_error(self):
        outcomes = [
            OutcomeDefinition(outcome_id="dna_combined_kit", product=DNA, segment=DNA_SEGMENT_COMBINED, metric="Kit sale", source_column="a"),
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", source_column="b"),
        ]
        errors = validate_outcome_definitions(outcomes)
        assert any("cannot be mixed" in e for e in errors)

    def test_split_dna_outcomes_alone_are_not_an_error(self):
        outcomes = [
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", source_column="a"),
            OutcomeDefinition(outcome_id="dna_existing_fh_kit", product=DNA, segment=DNA_SEGMENT_EXISTING_FH, metric="Kit sale", source_column="b"),
        ]
        assert validate_outcome_definitions(outcomes) == []

    def test_included_outcome_missing_from_available_columns_is_an_error(self):
        outcomes = [OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="missing_col")]
        errors = validate_outcome_definitions(outcomes, available_columns={"other_col"})
        assert any("not in the current data" in e for e in errors)

    def test_excluded_outcome_missing_from_available_columns_is_not_an_error(self):
        outcomes = [
            OutcomeDefinition(
                outcome_id="included", product=FAMILY_HISTORY, segment="New", metric="GSA",
                source_column="other_col",
            ),
            OutcomeDefinition(
                outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="Sign-up",
                source_column="missing_col", included_in_fit=False,
            ),
        ]
        errors = validate_outcome_definitions(outcomes, available_columns={"other_col"})
        assert errors == []

    def test_empty_catalogue_is_an_error(self):
        assert any("at least one outcome" in e.lower() for e in validate_outcome_definitions([]))

    def test_catalogue_with_only_excluded_outcomes_is_an_error(self):
        outcomes = [
            OutcomeDefinition(
                outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA",
                source_column="c", included_in_fit=False,
            )
        ]
        assert any("at least one outcome" in e.lower() for e in validate_outcome_definitions(outcomes))

    def test_signup_only_catalogue_is_valid_no_gsa_required(self):
        # Required test case 8 (PR E.2): a sign-up-only project does not
        # require a legacy GSA mapping.
        outcomes = [
            OutcomeDefinition(
                outcome_id="fh_new_signup", product=FAMILY_HISTORY, segment="New", metric="Sign-up",
                source_column="c",
            )
        ]
        assert validate_outcome_definitions(outcomes) == []

    def test_signup_id_labelled_as_gsa_metric_is_an_error(self):
        outcomes = [
            OutcomeDefinition(outcome_id="fh_new_signup", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="Signup_New"),
        ]
        errors = validate_outcome_definitions(outcomes)
        assert any("sign-up vs. GSA" in e or "different KPI" in e for e in errors)

    def test_gsa_id_labelled_as_signup_metric_is_an_error(self):
        outcomes = [
            OutcomeDefinition(outcome_id="fh_new_gsa", product=FAMILY_HISTORY, segment="New", metric="Sign-up", source_column="GSA_New"),
        ]
        errors = validate_outcome_definitions(outcomes)
        assert any("different KPI" in e for e in errors)

    def test_consistent_signup_and_gsa_labels_are_not_an_error(self):
        outcomes = [
            OutcomeDefinition(outcome_id="fh_new_signup", product=FAMILY_HISTORY, segment="New", metric="Sign-up", source_column="Signup_New"),
            OutcomeDefinition(outcome_id="fh_new_gsa", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="GSA_New"),
        ]
        assert validate_outcome_definitions(outcomes) == []

    def test_signup_and_gsa_can_share_a_segment(self):
        # The exact scenario PR E exists for: two distinct KPIs, same segment.
        outcomes = [
            OutcomeDefinition(outcome_id="fh_new_signup", product=FAMILY_HISTORY, segment="New", metric="Sign-up", source_column="Signup_New"),
            OutcomeDefinition(outcome_id="fh_new_gsa", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="GSA_New"),
        ]
        assert {o.segment for o in outcomes} == {"New"}
        assert len({o.outcome_id for o in outcomes}) == 2
        assert validate_outcome_definitions(outcomes) == []


class TestResolveOutcomeDefinitions:
    def test_none_derives_from_segment_outcomes(self):
        resolved = resolve_outcome_definitions(None, {"New": "GSA_New"}, {"New": 180.0})
        assert len(resolved) == 1
        assert resolved[0].product == FAMILY_HISTORY
        assert resolved[0].value_weight == 180.0

    def test_empty_list_also_derives_from_segment_outcomes(self):
        # Backward compatibility: a legacy bundle's outcome_definitions key
        # is None, but a project that has never saved any outcome (empty
        # list) should behave identically - both mean "nothing explicit was
        # saved, derive it."
        resolved = resolve_outcome_definitions([], {"New": "GSA_New"})
        assert len(resolved) == 1

    def test_explicit_outcome_definitions_win_over_derivation(self):
        explicit = [
            OutcomeDefinition(
                outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale",
                source_column="DNA_Kit_New",
            ).to_dict(),
        ]
        resolved = resolve_outcome_definitions(explicit, {"New": "GSA_New"})
        # Only the explicit DNA outcome comes back - segment_outcomes is NOT
        # re-derived once a project has an explicit saved set (that set
        # already includes whatever FH outcomes fh_outcomes_from_spec would
        # have derived, from whenever it was saved).
        assert len(resolved) == 1
        assert resolved[0].product == DNA

    def test_round_trips_through_dicts(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"})
        as_dicts = [o.to_dict() for o in outcomes]
        resolved = resolve_outcome_definitions(as_dicts, {"New": "GSA_New"})
        assert resolved == outcomes


class TestIncludedOutcomes:
    def test_filters_out_excluded_outcomes(self):
        outcomes = [
            OutcomeDefinition(outcome_id="a", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c1"),
            OutcomeDefinition(outcome_id="b", product=FAMILY_HISTORY, segment="Winback", metric="GSA", source_column="c2", included_in_fit=False),
        ]
        assert [o.outcome_id for o in included_outcomes(outcomes)] == ["a"]

    def test_empty_list_gives_empty_list(self):
        assert included_outcomes([]) == []

    def test_all_included_returns_all(self):
        outcomes = [
            OutcomeDefinition(outcome_id="a", product=FAMILY_HISTORY, segment="New", metric="GSA", source_column="c1"),
            OutcomeDefinition(outcome_id="b", product=FAMILY_HISTORY, segment="Winback", metric="GSA", source_column="c2"),
        ]
        assert included_outcomes(outcomes) == outcomes


class TestOutcomesToDataframe:
    def test_empty_list_gives_empty_dataframe_with_expected_columns(self):
        df = outcomes_to_dataframe([])
        assert df.empty
        assert "status" in df.columns
        assert "source_column" in df.columns
        assert "included_in_fit" in df.columns

    def test_has_one_row_per_outcome_with_status_column(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"}) + dna_outcomes_from_columns(new_customer_column="DNA_Kit_New")
        df = outcomes_to_dataframe(outcomes)
        assert len(df) == 2
        fh_row = df[df["product"] == FAMILY_HISTORY].iloc[0]
        dna_row = df[df["product"] == DNA].iloc[0]
        # No frame/fit context given - FH and DNA both just "Configured"
        # (both are included_in_fit=True by default, but with no frame/
        # model_meta context there's nothing to distinguish that from
        # "Configured" here).
        assert fh_row["status"] == "Configured"
        assert dna_row["status"] == "Configured"

    def test_excluded_outcomes_are_marked_excluded_via_included_in_fit(self):
        outcomes = dna_outcomes_from_columns(new_customer_column="DNA_Kit_New")
        outcomes[0].included_in_fit = False
        df = outcomes_to_dataframe(outcomes)
        assert df.iloc[0]["status"] == "Excluded"


class TestDnaKitOutcomeColumns:
    def test_returns_column_per_dna_outcome_id(self):
        outcomes = dna_outcomes_from_columns(
            new_customer_column="DNA_Kit_New", existing_fh_column="DNA_Kit_Existing",
        )
        assert dna_kit_outcome_columns(outcomes) == {
            "dna_new_kit": "DNA_Kit_New", "dna_existing_fh_kit": "DNA_Kit_Existing",
        }

    def test_excludes_family_history_outcomes(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"}) + dna_outcomes_from_columns(new_customer_column="DNA_Kit_New")
        result = dna_kit_outcome_columns(outcomes)
        assert result == {"dna_new_kit": "DNA_Kit_New"}

    def test_empty_outcomes_gives_empty_dict(self):
        assert dna_kit_outcome_columns([]) == {}

    def test_no_dna_outcomes_gives_empty_dict(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New", "Winback": "GSA_Winback"})
        assert dna_kit_outcome_columns(outcomes) == {}


# ---------------------------------------------------------------------------
# PR E.1: metric-aware selection - the required test cases from the
# instruction document ("FH New GSA only", "FH New sign-up only", "FH New
# GSA and FH New sign-up together", "multiple FH segments each with sign-up
# and GSA", "FH plus DNA kits", "same segment/different KPIs/independent
# dimensions", "GSA objective GSA-only", "sign-up objective signup-only" -
# the last two are exercised in test_optimization.py against these same
# selectors).
# ---------------------------------------------------------------------------

class TestSelectOutcomeIds:
    def test_fh_gsa_only_project_selects_correctly(self):
        meta = _meta(
            ["fh_new"], {"fh_new": FAMILY_HISTORY}, {"fh_new": METRIC_GSA},
        )
        assert fh_gsa_outcome_ids(meta) == ["fh_new"]
        assert fh_signup_outcome_ids(meta) == []
        assert dna_kit_sale_outcome_ids(meta) == []

    def test_fh_signup_only_project_selects_correctly(self):
        meta = _meta(
            ["fh_new_signup"], {"fh_new_signup": FAMILY_HISTORY}, {"fh_new_signup": METRIC_SIGNUP},
        )
        assert fh_gsa_outcome_ids(meta) == []
        assert fh_signup_outcome_ids(meta) == ["fh_new_signup"]
        assert dna_kit_sale_outcome_ids(meta) == []

    def test_gsa_and_signup_on_same_segment_are_disjoint_and_both_selected(self):
        # The exact scenario the instruction document's confirmed defect was
        # about: two outcome_ids sharing segment="New" must never collapse
        # into one total.
        meta = _meta(
            ["fh_new_gsa", "fh_new_signup"],
            {"fh_new_gsa": FAMILY_HISTORY, "fh_new_signup": FAMILY_HISTORY},
            {"fh_new_gsa": METRIC_GSA, "fh_new_signup": METRIC_SIGNUP},
        )
        gsa = fh_gsa_outcome_ids(meta)
        signup = fh_signup_outcome_ids(meta)
        assert gsa == ["fh_new_gsa"]
        assert signup == ["fh_new_signup"]
        assert set(gsa) & set(signup) == set()

    def test_multiple_fh_segments_each_with_signup_and_gsa(self):
        outcome_ids = ["fh_new_gsa", "fh_new_signup", "fh_winback_gsa", "fh_winback_signup"]
        products = {oid: FAMILY_HISTORY for oid in outcome_ids}
        metrics = {
            "fh_new_gsa": METRIC_GSA, "fh_new_signup": METRIC_SIGNUP,
            "fh_winback_gsa": METRIC_GSA, "fh_winback_signup": METRIC_SIGNUP,
        }
        meta = _meta(outcome_ids, products, metrics)
        assert set(fh_gsa_outcome_ids(meta)) == {"fh_new_gsa", "fh_winback_gsa"}
        assert set(fh_signup_outcome_ids(meta)) == {"fh_new_signup", "fh_winback_signup"}

    def test_fh_plus_dna_kits_never_mixed(self):
        meta = _meta(
            ["fh_new_gsa", "dna_new_kit"],
            {"fh_new_gsa": FAMILY_HISTORY, "dna_new_kit": DNA},
            {"fh_new_gsa": METRIC_GSA, "dna_new_kit": METRIC_KIT_SALE},
        )
        assert fh_gsa_outcome_ids(meta) == ["fh_new_gsa"]
        assert dna_kit_sale_outcome_ids(meta) == ["dna_new_kit"]

    def test_select_outcome_ids_filters_by_arbitrary_combination(self):
        meta = _meta(
            ["a", "b", "c"],
            {"a": FAMILY_HISTORY, "b": FAMILY_HISTORY, "c": DNA},
            {"a": METRIC_GSA, "b": METRIC_SIGNUP, "c": METRIC_KIT_SALE},
            id_to_role={"a": "primary", "b": "secondary", "c": "primary"},
        )
        assert select_outcome_ids(meta) == ["a", "b", "c"]
        assert select_outcome_ids(meta, product=FAMILY_HISTORY) == ["a", "b"]
        assert select_outcome_ids(meta, product=FAMILY_HISTORY, metric=METRIC_GSA) == ["a"]
        assert select_outcome_ids(meta, role="secondary") == ["b"]

    def test_funnel_intermediate_appears_in_its_own_default_reporting_total(self):
        # PR E.2 requirement #4/#5: a funnel_intermediate sign-up must still
        # appear in its own fh_signups default-reporting total (gated by
        # include_in_default_reporting, True by default for
        # funnel_intermediate) even though it's excluded from the stricter
        # official total (include_in_official_total, False by default for
        # funnel_intermediate) - see official_total_outcome_ids below.
        meta = _meta(
            ["fh_new_gsa", "fh_new_signup"],
            {"fh_new_gsa": FAMILY_HISTORY, "fh_new_signup": FAMILY_HISTORY},
            {"fh_new_gsa": METRIC_GSA, "fh_new_signup": METRIC_SIGNUP},
            id_to_role={"fh_new_gsa": "primary", "fh_new_signup": "funnel_intermediate"},
        )
        assert fh_signup_outcome_ids(meta) == ["fh_new_signup"]
        assert official_total_outcome_ids(meta, metric_key=METRIC_KEY_FH_SIGNUP) == []
        assert official_total_outcome_ids(meta, metric_key=METRIC_KEY_FH_GSA) == ["fh_new_gsa"]

    def test_legacy_meta_with_no_catalogue_metadata_falls_back_to_kit_only(self):
        # A FHModelMeta reconstructed from a bundle exported before
        # outcome_catalogue_at_fit existed has outcome_id_to_product == {}
        # for every outcome_id - the pre-PR-E.1 "everything non-DNA-kit is
        # the GSA total" behaviour must still work for it (test case 14,
        # "legacy bundles migrate safely").
        meta = _meta(
            ["New", "DNA_CrossSell", "Winback", "dna_new_kit"],
            {}, {},
            kit_only=["dna_new_kit"],
        )
        assert set(fh_gsa_outcome_ids(meta)) == {"New", "DNA_CrossSell", "Winback"}
        assert fh_signup_outcome_ids(meta) == []
        assert dna_kit_sale_outcome_ids(meta) == ["dna_new_kit"]


class TestFhChannelLogTermsIndependentDimensions:
    def test_gsa_and_signup_have_independent_posterior_dimensions(self):
        # "Same segment, different KPIs, independent posterior dimensions"
        # (test case 6) - proven at the curve-generation level: two
        # outcome_ids sharing a segment get their own beta and produce
        # different response curves, not one shared number. The full
        # real-MCMC version of this proof (both outcomes actually get
        # independently *fitted* posteriors, not just independently
        # *replayed* ones) is the offline recovery check, matching this
        # codebase's established convention for anything requiring real
        # PyMC sampling (docs/decision_log.md).
        from ancestry_mmm.core.hierarchical_model import FHModelMeta
        from ancestry_mmm.core.predict import FHPosteriorParams, generate_channel_curve
        import numpy as np

        outcome_ids = ["fh_new_gsa", "fh_new_signup"]
        meta = FHModelMeta(
            markets=["UK"], outcome_ids=outcome_ids, channels=["tv"], dna_channels=[],
            dna_channel_idx=[], non_dna_idx=[0], dna_outcome_id="fh_new_gsa", dna_lag_weeks=0,
            unpooled_markets=[], control_names=[],
            outcome_id_to_product={"fh_new_gsa": FAMILY_HISTORY, "fh_new_signup": FAMILY_HISTORY},
            outcome_id_to_metric={"fh_new_gsa": METRIC_GSA, "fh_new_signup": METRIC_SIGNUP},
            outcome_id_to_segment={"fh_new_gsa": "New", "fh_new_signup": "New"},
        )
        params = FHPosteriorParams(
            decay_rate={"tv": 0.5}, hill_K={"tv": 1000.0}, hill_S={"tv": 1.0},
            beta={"fh_new_gsa": {"tv": 0.1}, "fh_new_signup": {"tv": 0.4}},
            pathway_strength={}, promo_coef={"fh_new_gsa": 0.0, "fh_new_signup": 0.0},
            market_offset={"UK": {"fh_new_gsa": 0.0, "fh_new_signup": 0.0}},
            intercept={"fh_new_gsa": 3.0, "fh_new_signup": 3.0},
            trend_coef={"fh_new_gsa": 0.0, "fh_new_signup": 0.0},
            gamma_fourier={"fh_new_gsa": np.zeros(6), "fh_new_signup": np.zeros(6)},
            alpha={"fh_new_gsa": 5.0, "fh_new_signup": 5.0},
            control_coef={}, outcome_control_coef={},
        )
        curve = generate_channel_curve("tv", meta, params, spend_range=np.array([0.0, 500.0, 1000.0]))
        gsa_response = curve["fh_new_gsa_response"].to_numpy()
        signup_response = curve["fh_new_signup_response"].to_numpy()
        assert not np.allclose(gsa_response, signup_response), (
            "Two outcome_ids on the same segment with different betas must produce different "
            "response curves - they are independent dimensions, not one shared number."
        )
        assert curve["fh_response"].tolist() == gsa_response.tolist()
        assert curve["fh_signup_response"].tolist() == signup_response.tolist()


class TestExplicitFhDnaCrossSellOutcome:
    def _outcomes(self):
        return [
            OutcomeDefinition(outcome_id="fh_new_gsa", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA, source_column="col_gsa"),
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric=METRIC_KIT_SALE, source_column="col_kit"),
        ]

    def test_none_is_valid_when_no_candidate_configured(self):
        assert validate_fh_dna_cross_sell_outcome_id(None, self._outcomes()) == []

    def test_valid_fh_outcome_passes(self):
        assert validate_fh_dna_cross_sell_outcome_id("fh_new_gsa", self._outcomes()) == []

    def test_unknown_outcome_id_rejected(self):
        errors = validate_fh_dna_cross_sell_outcome_id("not_a_real_outcome", self._outcomes())
        assert errors and "not_a_real_outcome" in errors[0]

    def test_dna_kit_outcome_rejected_as_cross_sell_target(self):
        # A kit sale has no halo pathway onto itself - it must never be
        # accepted as the FH DNA cross-sell target.
        errors = validate_fh_dna_cross_sell_outcome_id("dna_new_kit", self._outcomes())
        assert errors and any("Family History" in e for e in errors)

    def test_excluded_outcome_rejected(self):
        outcomes = self._outcomes()
        outcomes[0].included_in_fit = False
        errors = validate_fh_dna_cross_sell_outcome_id("fh_new_gsa", outcomes)
        assert errors and "excluded" in errors[0]

    def test_infer_legacy_returns_none_when_no_candidates(self):
        outcomes = [OutcomeDefinition(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA, source_column="c")]
        candidate, warning = infer_legacy_fh_dna_cross_sell_outcome_id(outcomes)
        assert candidate is None and warning is None

    def test_infer_legacy_finds_single_candidate_with_warning(self):
        outcomes = [
            OutcomeDefinition(outcome_id="fh_dna_crosssell", product=FAMILY_HISTORY, segment="DNA_CrossSell", metric=METRIC_GSA, source_column="c"),
            OutcomeDefinition(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA, source_column="c2"),
        ]
        candidate, warning = infer_legacy_fh_dna_cross_sell_outcome_id(outcomes)
        assert candidate == "fh_dna_crosssell"
        assert warning is not None and "inferred" in warning

    def test_infer_legacy_ambiguous_with_multiple_candidates_returns_none(self):
        outcomes = [
            OutcomeDefinition(outcome_id="fh_dna_a", product=FAMILY_HISTORY, segment="A", metric=METRIC_GSA, source_column="c"),
            OutcomeDefinition(outcome_id="fh_dna_b", product=FAMILY_HISTORY, segment="B", metric=METRIC_GSA, source_column="c2"),
        ]
        candidate, warning = infer_legacy_fh_dna_cross_sell_outcome_id(outcomes)
        assert candidate is None
        assert warning is not None
        assert "fh_dna_a" in warning and "fh_dna_b" in warning

    def test_builder_requires_explicit_target_when_dna_channels_configured(self):
        # The confirmed defect this closes: substring-based inference used
        # to silently pick a DNA cross-sell target; it must now raise
        # instead when no explicit dna_outcome_id is resolvable and DNA
        # channels are configured.
        from ancestry_mmm.core.hierarchical_model import _default_dna_outcome_id
        import pytest

        with pytest.raises(ValueError, match="explicit"):
            _default_dna_outcome_id(["dna_new_kit", "fh_new"], None, dna_channel_idx=[0])

    def test_builder_does_not_require_target_without_dna_channels(self):
        from ancestry_mmm.core.hierarchical_model import _default_dna_outcome_id

        # No DNA-targeted channels at all - nothing to target, so an
        # unresolved id is harmless (never read by any pathway-dependent
        # code) rather than blocking an unrelated FH-only fit.
        assert _default_dna_outcome_id(["fh_new"], None, dna_channel_idx=[]) == "fh_new"


class TestOutcomeDriftStatus:
    def _outcome(self, **overrides):
        base = dict(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA, source_column="col_a", value_weight=100.0)
        base.update(overrides)
        return OutcomeDefinition(**base)

    def test_unchanged_outcome_is_fitted_and_current(self):
        current = self._outcome()
        fit_time = self._outcome()
        assert outcome_drift_status(current, fit_time) == "Fitted and current"

    def test_valid_column_remap_is_detected_as_changed_not_silently_unchanged(self):
        # The exact gap outcome_status (column-disappearing only) can't
        # catch: the mapping changed to a *different, still-present*
        # column - test case "valid-column remapping is detected as stale".
        current = self._outcome(source_column="col_b")
        fit_time = self._outcome(source_column="col_a")
        status = outcome_drift_status(current, fit_time, available_columns={"col_a", "col_b"})
        assert status == "Changed since fit"

    def test_metric_change_is_detected(self):
        current = self._outcome(metric=METRIC_SIGNUP)
        fit_time = self._outcome(metric=METRIC_GSA)
        assert outcome_drift_status(current, fit_time) == "Changed since fit"

    def test_missing_source_column_detected(self):
        current = self._outcome(source_column="col_a")
        fit_time = self._outcome(source_column="col_a")
        status = outcome_drift_status(current, fit_time, available_columns={"col_b"})
        assert status == "Missing source column"

    def test_excluded_from_next_fit_detected(self):
        current = self._outcome(included_in_fit=False)
        fit_time = self._outcome(included_in_fit=True)
        assert outcome_drift_status(current, fit_time) == "Excluded from next fit"

    def test_new_since_fit(self):
        current = self._outcome()
        assert outcome_drift_status(current, None) == "New since fit"

    def test_removed_since_fit(self):
        fit_time = self._outcome()
        assert outcome_drift_status(None, fit_time) == "Removed since fit"

    def test_all_drift_statuses_are_reachable(self):
        # Documentation-level check mirroring the instruction document's
        # required status list verbatim.
        assert set(DRIFT_STATUSES) == {
            "Fitted and current", "Excluded from next fit", "Changed since fit",
            "Missing source column", "New since fit", "Removed since fit",
        }

    def test_outcomes_drift_dataframe_covers_union_of_current_and_fit_time(self):
        current = [self._outcome(outcome_id="a"), self._outcome(outcome_id="c", metric=METRIC_SIGNUP)]
        fit_time = [self._outcome(outcome_id="a"), self._outcome(outcome_id="b")]
        model_meta = SimpleNamespace(outcome_catalogue_at_fit=fit_time)
        df = outcomes_drift_dataframe(current, model_meta)
        statuses = dict(zip(df["outcome_id"], df["drift_status"]))
        assert statuses["a"] == "Fitted and current"
        assert statuses["b"] == "Removed since fit"
        assert statuses["c"] == "New since fit"

    def test_outcomes_drift_dataframe_empty_without_model_meta(self):
        df = outcomes_drift_dataframe([self._outcome()], None)
        assert df.empty

    def test_has_blocking_drift_false_with_no_model_meta(self):
        assert has_blocking_drift([self._outcome()], None) is False

    def test_has_blocking_drift_false_when_unchanged(self):
        outcomes = [self._outcome()]
        model_meta = SimpleNamespace(outcome_catalogue_at_fit=[self._outcome()])
        assert has_blocking_drift(outcomes, model_meta) is False

    def test_has_blocking_drift_true_when_changed(self):
        # Required test case 15 - catalogue drift blocks planning.
        current = [self._outcome(metric=METRIC_SIGNUP)]
        model_meta = SimpleNamespace(outcome_catalogue_at_fit=[self._outcome(metric=METRIC_GSA)])
        assert has_blocking_drift(current, model_meta) is True

    def test_has_blocking_drift_true_when_removed(self):
        current = []
        model_meta = SimpleNamespace(outcome_catalogue_at_fit=[self._outcome()])
        assert has_blocking_drift(current, model_meta) is True

    def test_has_blocking_drift_false_when_only_new_since_fit(self):
        # A brand-new outcome not yet part of any fit doesn't make the
        # *existing* fit's numbers wrong - must not block.
        current = [self._outcome(outcome_id="a"), self._outcome(outcome_id="new_one")]
        model_meta = SimpleNamespace(outcome_catalogue_at_fit=[self._outcome(outcome_id="a")])
        assert has_blocking_drift(current, model_meta) is False

    def test_has_blocking_drift_false_when_only_excluded_from_next_fit(self):
        # Excluding an outcome from the *next* fit doesn't affect the
        # validity of the *current* fitted model - must not block.
        current = [self._outcome(included_in_fit=False)]
        model_meta = SimpleNamespace(outcome_catalogue_at_fit=[self._outcome(included_in_fit=True)])
        assert has_blocking_drift(current, model_meta) is False

    def test_outcome_catalogue_at_fit_by_id_keys_by_outcome_id(self):
        fit_time = [self._outcome(outcome_id="a"), self._outcome(outcome_id="b")]
        model_meta = SimpleNamespace(outcome_catalogue_at_fit=fit_time)
        by_id = outcome_catalogue_at_fit_by_id(model_meta)
        assert set(by_id) == {"a", "b"}

    def test_outcome_catalogue_at_fit_by_id_none_meta_gives_empty(self):
        assert outcome_catalogue_at_fit_by_id(None) == {}


class TestOutcomeCatalogueFingerprintPayload:
    def test_sorted_by_outcome_id(self):
        outcomes = [
            OutcomeDefinition(outcome_id="z", product=FAMILY_HISTORY, segment="S", metric=METRIC_GSA, source_column="c"),
            OutcomeDefinition(outcome_id="a", product=FAMILY_HISTORY, segment="S", metric=METRIC_GSA, source_column="c"),
        ]
        payload = outcome_catalogue_fingerprint_payload(outcomes)
        assert [p["outcome_id"] for p in payload] == ["a", "z"]

    def test_only_fingerprint_relevant_fields_included(self):
        outcomes = [OutcomeDefinition(
            outcome_id="a", product=FAMILY_HISTORY, segment="S", metric=METRIC_GSA, source_column="c",
            value_weight=1.0, value_currency="USD", role="primary", included_in_fit=True, exclusion_reason="x",
        )]
        payload = outcome_catalogue_fingerprint_payload(outcomes)[0]
        assert set(payload) == {
            "outcome_id", "product", "segment", "metric", "metric_key", "unit", "source_column",
            "role", "included_in_fit", "value_weight", "value_currency",
            "include_in_default_reporting", "include_in_official_total",
            "include_in_value", "include_in_optimisation",
        }
