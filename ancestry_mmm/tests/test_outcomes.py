"""Tests for core.outcomes - the canonical outcome schema (PR E, "make
OutcomeDefinition the source of truth" - see docs/decision_log.md)."""

from ancestry_mmm.core.outcomes import (
    DNA,
    DNA_SEGMENT_COMBINED,
    DNA_SEGMENT_EXISTING_FH,
    DNA_SEGMENT_NEW,
    FAMILY_HISTORY,
    OUTCOME_ROLES,
    OUTCOME_STATUSES,
    OutcomeDefinition,
    dna_kit_outcome_columns,
    dna_outcomes_from_columns,
    fh_outcomes_from_spec,
    included_outcomes,
    outcome_requires_opt_in,
    outcome_status,
    outcome_was_modelled,
    outcomes_to_dataframe,
    resolve_outcome_definitions,
    validate_outcome_definitions,
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

    def test_unit_derives_from_product_when_not_given(self):
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
                outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA",
                source_column="missing_col", included_in_fit=False,
            )
        ]
        errors = validate_outcome_definitions(outcomes, available_columns={"other_col"})
        assert errors == []

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
