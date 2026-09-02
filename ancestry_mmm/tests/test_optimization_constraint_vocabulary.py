"""Tests for `ancestry_mmm.core.optimization_constraint_vocabulary`
(`REQ-OPT-001` Requirement 2; Decision 16). See
`docs/optimizer_objective_and_constraint_vocabulary_decision_record.md`.
"""

import pytest

from ancestry_mmm.core.optimization_constraint_vocabulary import (
    CONSTRAINT_KINDS,
    GovernedSpendConstraint,
    resolve_governed_constraints,
)

MONTHS = ["2024-01", "2024-02"]
CHANNELS = ["TV", "Search"]
# Flattened order matches core.optimization._flatten: month-major, channel-minor.
CURRENT_SPEND = [1000.0, 500.0, 1000.0, 500.0]


class TestGovernedSpendConstraintValidation:
    def test_vocabulary_matches_req_opt_001_requirement_2(self):
        assert CONSTRAINT_KINDS == (
            "no_constraint",
            "fixed_absolute_spend",
            "minimum_spend",
            "maximum_spend",
            "spend_range",
            "percentage_change_from_reference",
            "absolute_change_from_reference",
            "zero_spend",
            "required_minimum_activity",
            "unavailable",
        )

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError):
            GovernedSpendConstraint(kind="not_a_kind")

    def test_no_constraint_needs_nothing(self):
        GovernedSpendConstraint(kind="no_constraint")

    def test_fixed_absolute_spend_requires_channel_and_month(self):
        with pytest.raises(ValueError):
            GovernedSpendConstraint(kind="fixed_absolute_spend", value=100.0)

    def test_fixed_absolute_spend_requires_value(self):
        with pytest.raises(ValueError):
            GovernedSpendConstraint(
                kind="fixed_absolute_spend", channel="TV", month="2024-01"
            )

    def test_spend_range_requires_min_and_max(self):
        with pytest.raises(ValueError):
            GovernedSpendConstraint(
                kind="spend_range", channel="TV", month="2024-01", min_value=10.0
            )

    def test_spend_range_rejects_min_greater_than_max(self):
        with pytest.raises(ValueError):
            GovernedSpendConstraint(
                kind="spend_range",
                channel="TV",
                month="2024-01",
                min_value=100.0,
                max_value=10.0,
            )

    def test_zero_spend_must_not_carry_a_value(self):
        with pytest.raises(ValueError):
            GovernedSpendConstraint(
                kind="zero_spend", channel="TV", month="2024-01", value=0.0
            )

    def test_unavailable_must_not_carry_a_value(self):
        with pytest.raises(ValueError):
            GovernedSpendConstraint(
                kind="unavailable", channel="TV", month="2024-01", value=1.0
            )

    def test_round_trip(self):
        gc = GovernedSpendConstraint(
            kind="spend_range",
            channel="TV",
            month="2024-01",
            min_value=10.0,
            max_value=100.0,
            label="x",
        )
        restored = GovernedSpendConstraint.from_dict(gc.to_dict())
        assert restored == gc


class TestResolveGovernedConstraintsLegacyEquivalents:
    def test_fixed_absolute_spend_locks_the_cell(self):
        gc = [
            GovernedSpendConstraint(
                kind="fixed_absolute_spend", channel="TV", month="2024-01", value=750.0
            )
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        idx = 0  # (2024-01, TV)
        assert result.bounds[idx] == (750.0, 750.0)
        assert result.disclosures[0].disposition == "translated_to_legacy"

    def test_minimum_spend_sets_a_floor(self):
        gc = [
            GovernedSpendConstraint(
                kind="minimum_spend", channel="TV", month="2024-01", value=200.0
            )
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        assert result.bounds[0][0] == 200.0

    def test_percentage_change_from_reference_bounds_symmetrically(self):
        gc = [
            GovernedSpendConstraint(
                kind="percentage_change_from_reference",
                channel="TV",
                month="2024-01",
                pct_move=0.1,
            )
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        lower, upper = result.bounds[0]
        assert lower == pytest.approx(900.0)
        assert upper == pytest.approx(1100.0)

    def test_zero_spend_forces_zero(self):
        gc = [GovernedSpendConstraint(kind="zero_spend", channel="TV", month="2024-01")]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        assert result.bounds[0] == (0.0, 0.0)


class TestResolveGovernedConstraintsDirectBounds:
    def test_maximum_spend_tightens_upper_only(self):
        gc = [
            GovernedSpendConstraint(
                kind="maximum_spend", channel="TV", month="2024-01", value=1200.0
            )
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        lower, upper = result.bounds[0]
        assert lower == 0.0
        assert upper == 1200.0
        assert result.disclosures[0].disposition == "applied_direct_bounds"

    def test_spend_range_tightens_both(self):
        gc = [
            GovernedSpendConstraint(
                kind="spend_range",
                channel="TV",
                month="2024-01",
                min_value=100.0,
                max_value=900.0,
            )
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        assert result.bounds[0] == (100.0, 900.0)

    def test_absolute_change_from_reference(self):
        gc = [
            GovernedSpendConstraint(
                kind="absolute_change_from_reference",
                channel="TV",
                month="2024-01",
                absolute_delta=50.0,
            )
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        assert result.bounds[0] == (950.0, 1050.0)

    def test_unavailable_forces_zero_and_is_distinguishable_from_zero_spend(self):
        gc = [
            GovernedSpendConstraint(kind="unavailable", channel="TV", month="2024-01")
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        assert result.bounds[0] == (0.0, 0.0)
        assert result.disclosures[0].kind == "unavailable"
        assert "fact" in result.disclosures[0].detail


class TestRequiredMinimumActivity:
    def test_advisory_only_without_unit_to_spend_rate(self):
        gc = [
            GovernedSpendConstraint(
                kind="required_minimum_activity",
                channel="TV",
                month="2024-01",
                value=3.0,
            )
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        # Never silently applied to money bounds.
        assert result.bounds[0] == (0.0, float("inf"))
        assert result.disclosures[0].disposition == "advisory_only"

    def test_applied_when_unit_to_spend_rate_supplied(self):
        gc = [
            GovernedSpendConstraint(
                kind="required_minimum_activity",
                channel="TV",
                month="2024-01",
                value=3.0,
                unit_to_spend_rate=50.0,
            )
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        assert result.bounds[0][0] == 150.0


class TestInfeasibilityReported:
    def test_conflicting_constraints_reported_not_silently_resolved(self):
        gc = [
            GovernedSpendConstraint(
                kind="minimum_spend", channel="TV", month="2024-01", value=900.0
            ),
            GovernedSpendConstraint(
                kind="maximum_spend", channel="TV", month="2024-01", value=100.0
            ),
        ]
        result = resolve_governed_constraints(
            gc, months=MONTHS, channels=CHANNELS, current_spend=CURRENT_SPEND
        )
        assert not result.is_feasible
        assert result.infeasible_cells == (("2024-01", "TV", 900.0, 100.0),)


class TestNoConstraintCurrentSpendLengthValidation:
    def test_wrong_length_current_spend_rejected(self):
        with pytest.raises(ValueError):
            resolve_governed_constraints(
                [], months=MONTHS, channels=CHANNELS, current_spend=[1.0, 2.0]
            )
