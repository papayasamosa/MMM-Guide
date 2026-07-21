"""Tests for core.outcomes - the generalised outcome schema (PR2 of the
DNA/FH architecture work, see docs/outcomes.md)."""

from ancestry_mmm.core.outcomes import (
    DNA,
    DNA_SEGMENT_COMBINED,
    DNA_SEGMENT_EXISTING_FH,
    DNA_SEGMENT_NEW,
    FAMILY_HISTORY,
    OutcomeDefinition,
    dna_kit_outcome_columns,
    dna_outcomes_from_columns,
    fh_outcomes_from_spec,
    outcome_is_modelled,
    outcomes_to_dataframe,
    resolve_outcome_definitions,
    validate_outcome_definitions,
)


class TestOutcomeDefinitionRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        outcome = OutcomeDefinition(
            outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric="GSA",
            column="GSA_New", value_weight=180.0,
        )
        restored = OutcomeDefinition.from_dict(outcome.to_dict())
        assert restored == outcome

    def test_from_dict_ignores_unknown_keys(self):
        d = {
            "outcome_id": "fh_new", "product": FAMILY_HISTORY, "segment": "New", "metric": "GSA",
            "column": "GSA_New", "value_weight": 180.0, "some_future_field": "ignored",
        }
        restored = OutcomeDefinition.from_dict(d)
        assert restored.outcome_id == "fh_new"

    def test_value_weight_defaults_to_none(self):
        outcome = OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", column="c")
        assert outcome.value_weight is None


class TestOutcomeIsModelled:
    def test_family_history_is_modelled_today(self):
        outcome = OutcomeDefinition(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric="GSA", column="c")
        assert outcome_is_modelled(outcome) is True

    def test_dna_is_not_modelled_today(self):
        outcome = OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", column="c")
        assert outcome_is_modelled(outcome) is False


class TestFhOutcomesFromSpec:
    def test_derives_one_outcome_per_segment(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New", "Winback": "GSA_Winback"})
        assert len(outcomes) == 2
        assert {o.segment for o in outcomes} == {"New", "Winback"}
        assert all(o.product == FAMILY_HISTORY for o in outcomes)
        assert all(o.metric == "GSA" for o in outcomes)

    def test_maps_column_correctly(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"})
        assert outcomes[0].column == "GSA_New"

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
        assert outcomes[0].column == "DNA_Kit_New"

    def test_combined_column_gives_one_combined_outcome(self):
        outcomes = dna_outcomes_from_columns(combined_column="DNA_Kit_Total")
        assert len(outcomes) == 1
        assert outcomes[0].segment == DNA_SEGMENT_COMBINED
        assert outcomes[0].column == "DNA_Kit_Total"

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
        outcomes = [OutcomeDefinition(outcome_id="", product=FAMILY_HISTORY, segment="New", metric="GSA", column="c")]
        errors = validate_outcome_definitions(outcomes)
        assert any("outcome_id" in e for e in errors)

    def test_duplicate_outcome_id_is_an_error(self):
        outcomes = [
            OutcomeDefinition(outcome_id="dup", product=FAMILY_HISTORY, segment="New", metric="GSA", column="a"),
            OutcomeDefinition(outcome_id="dup", product=FAMILY_HISTORY, segment="Winback", metric="GSA", column="b"),
        ]
        errors = validate_outcome_definitions(outcomes)
        assert any("Duplicate" in e for e in errors)

    def test_missing_column_is_an_error(self):
        outcomes = [OutcomeDefinition(outcome_id="x", product=FAMILY_HISTORY, segment="New", metric="GSA", column="")]
        errors = validate_outcome_definitions(outcomes)
        assert any("source column" in e for e in errors)

    def test_unknown_product_is_an_error(self):
        outcomes = [OutcomeDefinition(outcome_id="x", product="Unknown Product", segment="New", metric="GSA", column="c")]
        errors = validate_outcome_definitions(outcomes)
        assert any("unknown product" in e for e in errors)

    def test_mixing_combined_and_split_dna_outcomes_is_an_error(self):
        outcomes = [
            OutcomeDefinition(outcome_id="dna_combined_kit", product=DNA, segment=DNA_SEGMENT_COMBINED, metric="Kit sale", column="a"),
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", column="b"),
        ]
        errors = validate_outcome_definitions(outcomes)
        assert any("cannot be mixed" in e for e in errors)

    def test_split_dna_outcomes_alone_are_not_an_error(self):
        outcomes = [
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", column="a"),
            OutcomeDefinition(outcome_id="dna_existing_fh_kit", product=DNA, segment=DNA_SEGMENT_EXISTING_FH, metric="Kit sale", column="b"),
        ]
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
            OutcomeDefinition(outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW, metric="Kit sale", column="DNA_Kit_New").to_dict(),
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


class TestOutcomesToDataframe:
    def test_empty_list_gives_empty_dataframe_with_expected_columns(self):
        df = outcomes_to_dataframe([])
        assert df.empty
        assert "modelled_today" in df.columns

    def test_has_one_row_per_outcome_with_modelled_today_column(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"}) + dna_outcomes_from_columns(new_customer_column="DNA_Kit_New")
        df = outcomes_to_dataframe(outcomes)
        assert len(df) == 2
        fh_row = df[df["product"] == FAMILY_HISTORY].iloc[0]
        dna_row = df[df["product"] == DNA].iloc[0]
        assert fh_row["modelled_today"] == True  # noqa: E712
        assert dna_row["modelled_today"] == False  # noqa: E712


class TestDnaKitOutcomeColumns:
    def test_returns_column_per_dna_segment(self):
        outcomes = dna_outcomes_from_columns(
            new_customer_column="DNA_Kit_New", existing_fh_column="DNA_Kit_Existing",
        )
        assert dna_kit_outcome_columns(outcomes) == {
            DNA_SEGMENT_NEW: "DNA_Kit_New", DNA_SEGMENT_EXISTING_FH: "DNA_Kit_Existing",
        }

    def test_excludes_family_history_outcomes(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New"}) + dna_outcomes_from_columns(new_customer_column="DNA_Kit_New")
        result = dna_kit_outcome_columns(outcomes)
        assert result == {DNA_SEGMENT_NEW: "DNA_Kit_New"}

    def test_empty_outcomes_gives_empty_dict(self):
        assert dna_kit_outcome_columns([]) == {}

    def test_no_dna_outcomes_gives_empty_dict(self):
        outcomes = fh_outcomes_from_spec({"New": "GSA_New", "Winback": "GSA_Winback"})
        assert dna_kit_outcome_columns(outcomes) == {}
