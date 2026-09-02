"""Tests for `ancestry_mmm.core.capacity_plan_application` - the
generalised wiring of `core.capacity.CapacityLimitDefinition` into a
candidate plan (`REQ-CAP-001` 2026-08-30 addendum; Decision 18;
`REQ-OPT-001` Requirement 4)."""

from ancestry_mmm.core.capacity import CapacityLimitDefinition
from ancestry_mmm.core.capacity_plan_application import (
    apply_capacity_limits_to_bounds,
    classify_capacity_limit_binding,
)

MONTHS = ["2024-01", "2024-02"]
CHANNELS = ["TV", "Search"]
DEFAULT_BOUNDS = [(0.0, float("inf"))] * 4


class TestClassifyCapacityLimitBinding:
    def test_no_cap_value_is_unavailable(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-spend",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV",
            value_by_period={"2024-01": None},
        )
        reports = classify_capacity_limit_binding(limit, {"2024-01": 100.0})
        assert reports[0].classification.status == "unavailable"

    def test_realised_over_cap_is_capped(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-spend",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV",
            value_by_period={"2024-01": 1000.0},
        )
        reports = classify_capacity_limit_binding(limit, {"2024-01": 1000.0})
        assert reports[0].classification.status == "capped"

    def test_realised_well_under_cap_is_uncapped(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-spend",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV",
            value_by_period={"2024-01": 1000.0},
        )
        reports = classify_capacity_limit_binding(limit, {"2024-01": 200.0})
        assert reports[0].classification.status == "uncapped"

    def test_missing_realised_value_treated_as_not_binding(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-spend",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV",
            value_by_period={"2024-01": 1000.0},
        )
        reports = classify_capacity_limit_binding(limit, {})
        assert reports[0].classification.status == "uncapped"


class TestApplyCapacityLimitsToBoundsSpendLimit:
    def test_spend_limit_tightens_upper_bound(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-spend",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV",
            value_by_period={"2024-01": 500.0},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS, months=MONTHS, channels=CHANNELS, limits=[limit]
        )
        assert result.bounds[0] == (0.0, 500.0)
        assert result.disclosures[0].disposition == "applied_direct"

    def test_channel_not_in_plan_is_a_no_op(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-spend",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="Not_In_Plan",
            value_by_period={"2024-01": 500.0},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS, months=MONTHS, channels=CHANNELS, limits=[limit]
        )
        assert result.bounds == tuple(DEFAULT_BOUNDS)
        assert result.disclosures == ()


class TestApplyCapacityLimitsAvailabilityToggle:
    def test_toggle_off_forces_zero_spend(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-availability",
            limit_version=1,
            kind="availability_toggle",
            unit="on_off",
            applies_to="TV",
            value_by_period={"2024-01": 0.0},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS, months=MONTHS, channels=CHANNELS, limits=[limit]
        )
        assert result.bounds[0] == (0.0, 0.0)

    def test_toggle_on_leaves_bounds_unchanged(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-availability",
            limit_version=1,
            kind="availability_toggle",
            unit="on_off",
            applies_to="TV",
            value_by_period={"2024-01": 1.0},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS, months=MONTHS, channels=CHANNELS, limits=[limit]
        )
        assert result.bounds[0] == (0.0, float("inf"))


class TestApplyCapacityLimitsNonMoneyRequiresUnitRate:
    def test_delivery_exposure_limit_advisory_only_without_rate(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-impressions",
            limit_version=1,
            kind="delivery_exposure_limit",
            unit="impressions",
            applies_to="TV",
            value_by_period={"2024-01": 100000.0},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS, months=MONTHS, channels=CHANNELS, limits=[limit]
        )
        # Never silently treated as a spend cap.
        assert result.bounds[0] == (0.0, float("inf"))
        assert result.disclosures[0].disposition == "advisory_only"

    def test_delivery_exposure_limit_applied_with_governed_unit_rate(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-impressions",
            limit_version=1,
            kind="delivery_exposure_limit",
            unit="impressions",
            applies_to="TV",
            value_by_period={"2024-01": 100000.0},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS,
            months=MONTHS,
            channels=CHANNELS,
            limits=[limit],
            unit_to_spend_rate_by_limit_id={"tv-impressions": 0.01},
        )
        assert result.bounds[0] == (0.0, 1000.0)
        assert result.disclosures[0].disposition == "applied_via_unit_rate"

    def test_fixed_commitment_locks_cell_with_rate(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-commitment",
            limit_version=1,
            kind="fixed_commitment",
            unit="slots",
            applies_to="TV",
            value_by_period={"2024-01": 10.0},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS,
            months=MONTHS,
            channels=CHANNELS,
            limits=[limit],
            unit_to_spend_rate_by_limit_id={"tv-commitment": 40.0},
        )
        assert result.bounds[0] == (400.0, 400.0)

    def test_bounded_range_upper_only_without_min_metadata(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-range",
            limit_version=1,
            kind="bounded_range",
            unit="impressions",
            applies_to="TV",
            value_by_period={"2024-01": 1000.0},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS,
            months=MONTHS,
            channels=CHANNELS,
            limits=[limit],
            unit_to_spend_rate_by_limit_id={"tv-range": 1.0},
        )
        assert result.bounds[0] == (0.0, 1000.0)

    def test_bounded_range_applies_min_metadata_when_present(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-range",
            limit_version=1,
            kind="bounded_range",
            unit="impressions",
            applies_to="TV",
            value_by_period={"2024-01": 1000.0},
            metadata={"min_value_by_period": {"2024-01": 200.0}},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS,
            months=MONTHS,
            channels=CHANNELS,
            limits=[limit],
            unit_to_spend_rate_by_limit_id={"tv-range": 1.0},
        )
        assert result.bounds[0] == (200.0, 1000.0)


class TestApplyCapacityLimitsWithBindingReports:
    def test_binding_reports_populated_when_realised_supplied(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-spend",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV",
            value_by_period={"2024-01": 500.0},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS,
            months=MONTHS,
            channels=CHANNELS,
            limits=[limit],
            realised_by_limit_and_period={"tv-spend": {"2024-01": 500.0}},
        )
        assert len(result.binding_reports) == 1
        assert result.binding_reports[0].classification.status == "capped"

    def test_no_limit_declared_disclosed_distinctly(self):
        limit = CapacityLimitDefinition(
            limit_id="tv-spend",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV",
            value_by_period={"2024-01": None},
        )
        result = apply_capacity_limits_to_bounds(
            DEFAULT_BOUNDS, months=MONTHS, channels=CHANNELS, limits=[limit]
        )
        assert result.disclosures[0].disposition == "no_limit_declared"
        assert result.bounds[0] == (0.0, float("inf"))
