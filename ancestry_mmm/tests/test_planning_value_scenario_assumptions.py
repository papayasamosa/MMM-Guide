"""Tests for core.planning.value.ScenarioValueAssumptions /
build_scenario_value_assumptions - the explicit forward economic-value
assumption for Scenario Planner (REQ-ECON-003 Requirement 5, WP2G).
Never extrapolated from historical valuation; both DNA representations
(one overall value vs segment-specific) must be supported."""

import pytest

from ancestry_mmm.core.planning.value import (
    DNA_VALUE_MODE_OVERALL,
    DNA_VALUE_MODE_SEGMENT_SPECIFIC,
    ScenarioValueAssumptions,
    build_scenario_value_assumptions,
)


class TestBuildScenarioValueAssumptionsOverallMode:
    def test_expands_one_value_across_every_dna_outcome_id(self):
        assumptions = build_scenario_value_assumptions(
            fh_value_by_outcome_id={"FH_New": 120.0},
            dna_mode=DNA_VALUE_MODE_OVERALL,
            currency="GBP",
            dna_outcome_ids=["DNA_A", "DNA_B", "DNA_C"],
            dna_overall_value=45.0,
        )
        assert assumptions.dna_mode == DNA_VALUE_MODE_OVERALL
        assert assumptions.dna_value_by_outcome_id == {
            "DNA_A": 45.0,
            "DNA_B": 45.0,
            "DNA_C": 45.0,
        }

    def test_missing_overall_value_raises(self):
        with pytest.raises(ValueError, match="dna_overall_value"):
            build_scenario_value_assumptions(
                fh_value_by_outcome_id={},
                dna_mode=DNA_VALUE_MODE_OVERALL,
                currency="GBP",
                dna_outcome_ids=["DNA_A"],
            )

    def test_negative_overall_value_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            build_scenario_value_assumptions(
                fh_value_by_outcome_id={},
                dna_mode=DNA_VALUE_MODE_OVERALL,
                currency="GBP",
                dna_outcome_ids=["DNA_A"],
                dna_overall_value=-1.0,
            )


class TestBuildScenarioValueAssumptionsSegmentSpecificMode:
    def test_uses_the_supplied_per_outcome_values(self):
        assumptions = build_scenario_value_assumptions(
            fh_value_by_outcome_id={},
            dna_mode=DNA_VALUE_MODE_SEGMENT_SPECIFIC,
            currency="GBP",
            dna_outcome_ids=["DNA_A", "DNA_B"],
            dna_value_by_outcome_id={"DNA_A": 40.0, "DNA_B": 60.0},
        )
        assert assumptions.dna_value_by_outcome_id == {"DNA_A": 40.0, "DNA_B": 60.0}

    def test_missing_a_required_outcome_id_raises(self):
        with pytest.raises(ValueError, match="DNA_B"):
            build_scenario_value_assumptions(
                fh_value_by_outcome_id={},
                dna_mode=DNA_VALUE_MODE_SEGMENT_SPECIFIC,
                currency="GBP",
                dna_outcome_ids=["DNA_A", "DNA_B"],
                dna_value_by_outcome_id={"DNA_A": 40.0},
            )

    def test_never_silently_defaults_missing_value_to_zero(self):
        """Explicit regression guard: a segment with no supplied value
        must block, never silently become 0.0."""
        with pytest.raises(ValueError):
            build_scenario_value_assumptions(
                fh_value_by_outcome_id={},
                dna_mode=DNA_VALUE_MODE_SEGMENT_SPECIFIC,
                currency="GBP",
                dna_outcome_ids=["DNA_A"],
                dna_value_by_outcome_id={},
            )


class TestBuildScenarioValueAssumptionsUnknownMode:
    def test_unknown_dna_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown dna_mode"):
            build_scenario_value_assumptions(
                fh_value_by_outcome_id={},
                dna_mode="halfway",
                currency="GBP",
            )


class TestScenarioValueAssumptionsValidation:
    def test_negative_fh_value_raises(self):
        with pytest.raises(ValueError, match="negative"):
            ScenarioValueAssumptions(
                fh_value_by_outcome_id={"FH_New": -5.0},
                dna_value_by_outcome_id={},
                dna_mode=DNA_VALUE_MODE_OVERALL,
                currency="GBP",
            )

    def test_non_finite_value_raises(self):
        with pytest.raises(ValueError, match="non-finite"):
            ScenarioValueAssumptions(
                fh_value_by_outcome_id={"FH_New": float("nan")},
                dna_value_by_outcome_id={},
                dna_mode=DNA_VALUE_MODE_OVERALL,
                currency="GBP",
            )

    def test_invalid_currency_raises(self):
        with pytest.raises(ValueError, match="currency"):
            ScenarioValueAssumptions(
                fh_value_by_outcome_id={},
                dna_value_by_outcome_id={},
                dna_mode=DNA_VALUE_MODE_OVERALL,
                currency="gbp",
            )

    def test_unknown_dna_mode_raises(self):
        with pytest.raises(ValueError, match="dna_mode"):
            ScenarioValueAssumptions(
                fh_value_by_outcome_id={},
                dna_value_by_outcome_id={},
                dna_mode="halfway",
                currency="GBP",
            )

    def test_outcome_id_in_both_fh_and_dna_raises(self):
        with pytest.raises(ValueError, match="exactly one product"):
            ScenarioValueAssumptions(
                fh_value_by_outcome_id={"Shared": 10.0},
                dna_value_by_outcome_id={"Shared": 20.0},
                dna_mode=DNA_VALUE_MODE_SEGMENT_SPECIFIC,
                currency="GBP",
            )


class TestScenarioValueAssumptionsMissingOutcomeIds:
    def test_reports_uncovered_ids_only(self):
        assumptions = ScenarioValueAssumptions(
            fh_value_by_outcome_id={"FH_New": 100.0},
            dna_value_by_outcome_id={"DNA_A": 40.0},
            dna_mode=DNA_VALUE_MODE_SEGMENT_SPECIFIC,
            currency="GBP",
        )
        missing = assumptions.missing_outcome_ids(["FH_New", "DNA_A", "DNA_B"])
        assert missing == ["DNA_B"]

    def test_empty_when_everything_covered(self):
        assumptions = ScenarioValueAssumptions(
            fh_value_by_outcome_id={"FH_New": 100.0},
            dna_value_by_outcome_id={},
            dna_mode=DNA_VALUE_MODE_OVERALL,
            currency="GBP",
        )
        assert assumptions.missing_outcome_ids(["FH_New"]) == []


class TestScenarioValueAssumptionsToOutcomeValueMapping:
    def test_flattens_fh_and_dna_into_one_mapping(self):
        assumptions = ScenarioValueAssumptions(
            fh_value_by_outcome_id={"FH_New": 100.0},
            dna_value_by_outcome_id={"DNA_A": 40.0, "DNA_B": 40.0},
            dna_mode=DNA_VALUE_MODE_OVERALL,
            currency="GBP",
        )
        mapping = assumptions.to_outcome_value_mapping()
        assert mapping.value_by_outcome_id == {
            "FH_New": 100.0,
            "DNA_A": 40.0,
            "DNA_B": 40.0,
        }
        assert mapping.currency_by_outcome_id == {
            "FH_New": "GBP",
            "DNA_A": "GBP",
            "DNA_B": "GBP",
        }
        assert mapping.source == "scenario_forward_assumption"


class TestScenarioValueAssumptionsRoundTrip:
    def test_to_dict_from_dict_round_trip(self):
        assumptions = build_scenario_value_assumptions(
            fh_value_by_outcome_id={"FH_New": 100.0, "FH_Gift": 80.0},
            dna_mode=DNA_VALUE_MODE_SEGMENT_SPECIFIC,
            currency="USD",
            dna_outcome_ids=["DNA_A"],
            dna_value_by_outcome_id={"DNA_A": 55.0},
            assumptions_id="scenario-2026-q1",
        )
        restored = ScenarioValueAssumptions.from_dict(assumptions.to_dict())
        assert restored == assumptions
