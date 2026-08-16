"""REQ-SCEN-002 (WP1): tests for core.planning.phasing."""

from __future__ import annotations

import pytest

from ancestry_mmm.core.frequency_alignment import CanonicalCalendar
from ancestry_mmm.core.media_costs import CostMappingRegistry, FixedCostPerUnitMapping
from ancestry_mmm.core.planning.phasing import (
    EXPLICIT_OVERRIDE_METHOD_ID,
    HorizonConfiguration,
    PHASING_METHOD_ID,
    PHASING_METHOD_VERSION,
    PhasingReconciliationError,
    WeeklyAllocationResult,
    canonical_weeks,
    phase_model_input_plan_calendar_day_overlap_v1,
    phase_monetary_plan_calendar_day_overlap_v1,
    phase_monthly_series_calendar_day_overlap_v1,
    phase_monthly_series_explicit_override,
    reconcile_explicit_weekly_schedule,
)


def _calendar(start: str, end: str) -> CanonicalCalendar:
    return CanonicalCalendar(start=start, end=end, frequency="weekly")


def _governance(**overrides):
    values = {
        "mapping_id": "uk-search",
        "market": "UK",
        "channel": "Search",
        "currency": "GBP",
        "cost_context_id": "default",
        "source": "finance rate card",
        "effective_period_start": "2026-01-01",
        "effective_period_end": "2026-12-31",
        "assumptions": "net media cost",
        "approval_status": "approved",
        "approved_by": "finance-owner",
        "approved_at": "2026-01-01T10:00:00Z",
        "owner": "media-finance",
        "approval_note": "Approved net media rate",
        "last_reviewed_at": "2026-01-01",
    }
    values.update(overrides)
    return values


class TestCanonicalWeeks:
    def test_generates_weekly_cadence_from_start(self):
        weeks = canonical_weeks(_calendar("2026-01-05", "2026-02-15"))
        assert weeks == (
            "2026-01-05",
            "2026-01-12",
            "2026-01-19",
            "2026-01-26",
            "2026-02-02",
            "2026-02-09",
        )

    def test_rejects_non_weekly_calendar(self):
        with pytest.raises(ValueError, match="weekly"):
            canonical_weeks(
                CanonicalCalendar(
                    start="2026-01-01", end="2026-01-31", frequency="daily"
                )
            )


class TestConservation:
    def test_month_entirely_within_canonical_weeks(self):
        calendar = _calendar("2026-01-05", "2026-04-30")
        result = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-02": 1000.0},
            calendar=calendar,
        )
        assert result.reconciliation[0].within_tolerance
        assert sum(result.values) == pytest.approx(1000.0, abs=1e-9)

    def test_month_beginning_mid_week_and_ending_mid_week(self):
        # 2026-01-05 is a Monday; January 2026 begins on a Thursday and
        # ends on a Saturday - neither a week boundary - so this exercises
        # both "month begins mid-week" and "month ends mid-week" together.
        calendar = _calendar("2025-12-29", "2026-02-28")
        result = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 3100.0},
            calendar=calendar,
        )
        rec = result.reconciliation[0]
        assert rec.within_tolerance
        assert rec.allocated_total == pytest.approx(3100.0, abs=1e-9)
        # January spans more than 4 calendar weeks once mid-week boundaries
        # are counted, so it must touch at least 5 canonical weeks.
        assert len(rec.weeks) >= 5

    def test_week_spanning_two_months_receives_both_allocations(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        result = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 3100.0, "2026-02": 2800.0},
            calendar=calendar,
        )
        jan_weeks = set(result.reconciliation[0].weeks)
        feb_weeks = set(result.reconciliation[1].weeks)
        boundary_weeks = jan_weeks & feb_weeks
        assert boundary_weeks, (
            "expected at least one week shared between January and February"
        )
        by_week = result.as_dict_by_week()
        for week in boundary_weeks:
            assert by_week[week] > 0
        # Both months individually reconcile even though they share a week.
        assert result.reconciliation[0].within_tolerance
        assert result.reconciliation[1].within_tolerance

    def test_leap_year_february_reconciles(self):
        calendar = _calendar("2028-01-01", "2028-03-31")
        result = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2028-02": 2900.0},
            calendar=calendar,
        )
        assert result.reconciliation[0].within_tolerance

    def test_zero_plan_reconciles_trivially(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        result = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 0.0},
            calendar=calendar,
        )
        assert all(v == 0.0 for v in result.values)
        assert result.reconciliation[0].within_tolerance

    def test_month_with_no_overlap_against_calendar_raises(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        with pytest.raises(PhasingReconciliationError):
            phase_monthly_series_calendar_day_overlap_v1(
                market="UK",
                series_id="TV",
                monthly_values={"2027-06": 500.0},
                calendar=calendar,
            )

    def test_provenance_records_method_and_calendar(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        result = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 700.0},
            calendar=calendar,
        )
        assert result.provenance.method_id == PHASING_METHOD_ID
        assert result.provenance.method_version == PHASING_METHOD_VERSION
        assert result.provenance.canonical_calendar_start == calendar.start
        assert result.provenance.canonical_calendar_end == calendar.end
        assert result.provenance.source_monthly_plan_fingerprint
        assert result.provenance.generated_weekly_plan_fingerprint


class TestInvalidInput:
    def test_empty_monthly_values_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            phase_monthly_series_calendar_day_overlap_v1(
                market="UK",
                series_id="TV",
                monthly_values={},
                calendar=_calendar("2025-12-29", "2026-02-28"),
            )

    def test_negative_value_rejected(self):
        with pytest.raises(ValueError, match="negative"):
            phase_monthly_series_calendar_day_overlap_v1(
                market="UK",
                series_id="TV",
                monthly_values={"2026-01": -1.0},
                calendar=_calendar("2025-12-29", "2026-02-28"),
            )

    def test_malformed_month_label_rejected(self):
        with pytest.raises(ValueError, match="YYYY-MM"):
            phase_monthly_series_calendar_day_overlap_v1(
                market="UK",
                series_id="TV",
                monthly_values={"Jan-2026": 1.0},
                calendar=_calendar("2025-12-29", "2026-02-28"),
            )


class TestExplicitWeeklyOverride:
    def test_matching_schedule_reconciles(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        governed = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 400.0},
            calendar=calendar,
        )
        schedule = governed.as_dict_by_week()
        result = phase_monthly_series_explicit_override(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 400.0},
            weekly_schedule=schedule,
            calendar=calendar,
        )
        assert result.provenance.method_id == EXPLICIT_OVERRIDE_METHOD_ID
        assert all(r.within_tolerance for r in result.reconciliation)
        assert result.values == governed.values

    def test_mismatched_schedule_blocks(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        bad_schedule = {w: 0.0 for w in canonical_weeks(calendar)}
        with pytest.raises(PhasingReconciliationError):
            reconcile_explicit_weekly_schedule(
                monthly_values={"2026-01": 400.0},
                weekly_schedule=bad_schedule,
                calendar=calendar,
            )

    def test_boundary_week_fraction_attributed_correctly(self):
        # A week that falls half in January, half in February: an explicit
        # value on that week must reconcile against both months in
        # proportion to day-overlap, not be double counted against each.
        calendar = _calendar("2026-01-26", "2026-02-08")  # two weeks
        weeks = canonical_weeks(calendar)
        assert weeks == ("2026-01-26", "2026-02-02")
        # Week 2026-01-26..02-01 is wholly January (6 days) + Feb 1 (1 day).
        # Week 2026-02-02..02-08 is wholly February.
        schedule = {"2026-01-26": 700.0, "2026-02-02": 700.0}
        jan_days = 6  # 26,27,28,29,30,31
        feb_days_in_week1 = 1  # Feb 1
        expected_jan = 700.0 * (jan_days / 7.0)
        reconciliation = reconcile_explicit_weekly_schedule(
            monthly_values={
                "2026-01": expected_jan,
                "2026-02": 700.0 * (feb_days_in_week1 / 7.0) + 700.0,
            },
            weekly_schedule=schedule,
            calendar=calendar,
        )
        assert all(r.within_tolerance for r in reconciliation)


class TestModelInputPath:
    def test_does_not_touch_cost_mapping(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        result = phase_model_input_plan_calendar_day_overlap_v1(
            market="UK",
            channel="TV",
            monthly_quantity={"2026-01": 12000.0},
            calendar=calendar,
        )
        assert isinstance(result, WeeklyAllocationResult)
        assert sum(result.values) == pytest.approx(12000.0, abs=1e-9)


class TestMonetaryPath:
    def test_phases_then_converts_via_cost_mapping(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        mapping = FixedCostPerUnitMapping(
            **_governance(effective_period_start="2025-01-01"), cost_per_media_input=2.0
        )
        registry = CostMappingRegistry([mapping])
        result = phase_monetary_plan_calendar_day_overlap_v1(
            market="UK",
            channel="Search",
            monthly_spend={"2026-01": 1400.0},
            calendar=calendar,
            cost_registry=registry,
        )
        assert sum(result.weekly_spend.values) == pytest.approx(1400.0, abs=1e-9)
        for spend, quantity in zip(
            result.weekly_spend.values, result.weekly_model_input.values
        ):
            assert quantity == pytest.approx(spend / 2.0, abs=1e-9)
        # Zero-spend weeks (outside the plan window but inside the
        # canonical calendar) need no cost mapping at all - "" is the
        # sentinel for that; every non-zero-spend week uses the one
        # mapping supplied.
        for spend, mapping_id in zip(
            result.weekly_spend.values, result.weekly_model_input.mapping_ids
        ):
            assert mapping_id == (mapping.mapping_id if spend != 0.0 else "")

    def test_time_varying_cost_mapping_changes_delivery_per_week(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        early = FixedCostPerUnitMapping(
            **_governance(
                mapping_id="early",
                effective_period_start="2025-12-01",
                effective_period_end="2026-01-18",
            ),
            cost_per_media_input=2.0,
        )
        late = FixedCostPerUnitMapping(
            **_governance(
                mapping_id="late",
                effective_period_start="2026-01-19",
                effective_period_end="2026-12-31",
            ),
            cost_per_media_input=4.0,
        )
        registry = CostMappingRegistry([early, late])
        result = phase_monetary_plan_calendar_day_overlap_v1(
            market="UK",
            channel="Search",
            monthly_spend={"2026-01": 1400.0, "2026-02": 800.0},
            calendar=calendar,
            cost_registry=registry,
        )
        mapping_ids = result.weekly_model_input.mapping_ids
        assert mapping_ids[0] == "early"
        assert mapping_ids[-1] == "late"
        assert "early" in mapping_ids and "late" in mapping_ids
        for spend, quantity, mapping_id in zip(
            result.weekly_spend.values, result.weekly_model_input.values, mapping_ids
        ):
            expected_cost = 2.0 if mapping_id == "early" else 4.0
            assert quantity == pytest.approx(spend / expected_cost, abs=1e-9)

    def test_missing_cost_mapping_blocks(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        registry = CostMappingRegistry([])
        with pytest.raises(PhasingReconciliationError):
            phase_monetary_plan_calendar_day_overlap_v1(
                market="UK",
                channel="Search",
                monthly_spend={"2026-01": 100.0},
                calendar=calendar,
                cost_registry=registry,
            )


class TestFingerprintsAndSerialization:
    def test_stable_fingerprints_for_identical_input(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        first = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 500.0},
            calendar=calendar,
        )
        second = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 500.0},
            calendar=calendar,
        )
        assert (
            first.provenance.source_monthly_plan_fingerprint
            == second.provenance.source_monthly_plan_fingerprint
        )
        assert (
            first.provenance.generated_weekly_plan_fingerprint
            == second.provenance.generated_weekly_plan_fingerprint
        )

    def test_fingerprint_changes_with_different_input(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        first = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 500.0},
            calendar=calendar,
        )
        second = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 600.0},
            calendar=calendar,
        )
        assert (
            first.provenance.generated_weekly_plan_fingerprint
            != second.provenance.generated_weekly_plan_fingerprint
        )

    def test_serialization_round_trip(self):
        calendar = _calendar("2025-12-29", "2026-02-28")
        result = phase_monthly_series_calendar_day_overlap_v1(
            market="UK",
            series_id="TV",
            monthly_values={"2026-01": 500.0},
            calendar=calendar,
        )
        restored = WeeklyAllocationResult.from_dict(result.to_dict())
        assert restored == result


class TestHorizonConfiguration:
    def test_defaults_are_valid(self):
        config = HorizonConfiguration()
        assert config.short_horizon_weeks == (0, 4)
        assert config.long_horizon_weeks == (5, 52)
        assert config.terminal_continuation_weeks == 52
        assert config.plan_horizon_weeks is None

    def test_rejects_inverted_bounds(self):
        with pytest.raises(ValueError):
            HorizonConfiguration(short_horizon_weeks=(4, 0))

    def test_accepts_explicit_plan_horizon(self):
        config = HorizonConfiguration(plan_horizon_weeks=13)
        assert config.plan_horizon_weeks == 13

    def test_round_trip(self):
        config = HorizonConfiguration(plan_horizon_weeks=8)
        restored = HorizonConfiguration.from_dict(config.to_dict())
        assert restored == config
