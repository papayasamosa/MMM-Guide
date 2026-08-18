"""Tests for `core.frequency_alignment` (REQ-COVERAGE-001 S4, Work Package C:
canonical-calendar and mixed-frequency alignment contracts).

This module never implements a conversion method - these tests prove the
*contracts* fail closed (every alignment request today resolves to an
explicit unsupported status, never fabricated data) and that the checks
(publication leakage, definition-break crossing, support boundary,
canonical-calendar resolution) behave correctly on already-known inputs,
independent of whether any method is ever approved.
"""

from __future__ import annotations

import pytest

from ancestry_mmm.core.coverage import DefinitionBreak
from ancestry_mmm.core.frequency_alignment import (
    AlignmentSpecification,
    CalendarResolutionRequiredError,
    CanonicalCalendar,
    ConversionMethodSpec,
    check_definition_break_crossing,
    check_publication_leakage,
    check_support_boundary,
    evaluate_alignment_request,
    register_conversion_method,
    registered_method_count,
    resolve_canonical_calendar,
    resolve_conversion_method,
)


# ---------------------------------------------------------------------------
# ConversionMethodSpec
# ---------------------------------------------------------------------------


class TestConversionMethodSpec:
    def test_requires_method_id_and_description(self):
        with pytest.raises(ValueError, match="method_id and description"):
            ConversionMethodSpec(
                method_id="",
                version=1,
                variable_class="flow_count",
                description="",
            )

    def test_rejects_invalid_variable_class(self):
        with pytest.raises(ValueError, match="invalid variable_class"):
            ConversionMethodSpec(
                method_id="m1",
                version=1,
                variable_class="not_a_real_class",
                description="d",
            )

    def test_rejects_version_below_one(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            ConversionMethodSpec(
                method_id="m1", version=0, variable_class="flow_count", description="d"
            )

    def test_approved_requires_attribution(self):
        with pytest.raises(ValueError, match="requires approved_by and approved_at"):
            ConversionMethodSpec(
                method_id="m1",
                version=1,
                variable_class="flow_count",
                description="d",
                approved=True,
            )

    def test_approved_with_attribution_is_valid(self):
        spec = ConversionMethodSpec(
            method_id="m1",
            version=1,
            variable_class="flow_count",
            description="d",
            approved=True,
            approved_by="Jane",
            approved_at="2026-08-11",
        )
        assert spec.approved is True

    def test_to_dict_round_trips_fields(self):
        spec = ConversionMethodSpec(
            method_id="m1", version=1, variable_class="flow_count", description="d"
        )
        d = spec.to_dict()
        assert d["method_id"] == "m1"
        assert d["approved"] is False


# ---------------------------------------------------------------------------
# Conversion-method registry - starts empty, never invents a method
# ---------------------------------------------------------------------------


class TestConversionMethodRegistry:
    def test_registry_is_empty_by_default(self):
        """The single most important invariant of this module: no method
        is registered anywhere for any variable class unless something
        explicitly registered one. Work Package D's `ensure_approved_
        frequency_methods` (`core.frequency_conversion`) does exactly
        that - idempotently, for the whole process - and by design is
        exercised by any test that reaches a "ready" `assess_official_
        preparation` result (Work Package 1 part 2's fold-local
        reconstruction tests do this legitimately). This test's own
        assertion is about a *genuinely untouched* registry, not "whatever
        this shared test process happens to have accumulated by the time
        this test runs" - so it isolates itself exactly like `test_
        registered_but_unapproved_method_is_not_resolved`/`test_
        registered_and_approved_method_is_resolved` below already do,
        rather than depending on file-collection-order accidents."""
        from ancestry_mmm.core import frequency_alignment as fa

        saved = dict(fa._METHOD_REGISTRY)
        fa._METHOD_REGISTRY.clear()
        try:
            assert registered_method_count() == 0
        finally:
            fa._METHOD_REGISTRY.update(saved)

    def test_resolve_returns_none_when_nothing_registered(self):
        assert resolve_conversion_method("flow_count") is None
        assert resolve_conversion_method("stock_level", method_id="anything") is None

    def test_registered_but_unapproved_method_is_not_resolved(self):
        register_conversion_method(
            ConversionMethodSpec(
                method_id="test-only-method",
                version=1,
                variable_class="flow_count",
                description="unapproved, registered for this test only",
                approved=False,
            )
        )
        try:
            assert resolve_conversion_method("flow_count") is None
            assert (
                resolve_conversion_method("flow_count", method_id="test-only-method")
                is None
            )
        finally:
            from ancestry_mmm.core import frequency_alignment as fa

            fa._METHOD_REGISTRY.pop(("flow_count", "test-only-method"), None)

    def test_registered_and_approved_method_is_resolved(self):
        register_conversion_method(
            ConversionMethodSpec(
                method_id="test-only-approved-method",
                version=1,
                variable_class="rate_index",
                description="approved, registered for this test only",
                approved=True,
                approved_by="Jane",
                approved_at="2026-08-11",
            )
        )
        try:
            resolved = resolve_conversion_method(
                "rate_index", method_id="test-only-approved-method"
            )
            assert resolved is not None
            assert resolved.method_id == "test-only-approved-method"
        finally:
            from ancestry_mmm.core import frequency_alignment as fa

            fa._METHOD_REGISTRY.pop(("rate_index", "test-only-approved-method"), None)


# ---------------------------------------------------------------------------
# AlignmentSpecification
# ---------------------------------------------------------------------------


def _spec(**overrides) -> AlignmentSpecification:
    defaults = dict(
        variable_id="TV",
        source_id="media-src",
        source_version=1,
        market="UK",
        native_frequency="monthly",
        target_frequency="weekly",
        variable_class="flow_count",
    )
    defaults.update(overrides)
    return AlignmentSpecification(**defaults)


class TestAlignmentSpecification:
    def test_requires_variable_and_source_id(self):
        with pytest.raises(ValueError, match="variable_id and source_id"):
            _spec(variable_id="")

    def test_requires_market(self):
        with pytest.raises(ValueError, match="market is required"):
            _spec(market="")

    def test_rejects_invalid_variable_class(self):
        with pytest.raises(ValueError, match="invalid variable_class"):
            _spec(variable_class="nonsense")

    def test_rejects_negative_publication_lag(self):
        with pytest.raises(ValueError, match="publication_lag_periods must be >= 0"):
            _spec(publication_lag_periods=-1)

    def test_rejects_support_start_after_support_end(self):
        with pytest.raises(ValueError, match="support_start must not be after"):
            _spec(support_start="2026-06-01", support_end="2026-01-01")

    def test_to_dict_serialises_definition_breaks(self):
        spec = _spec(
            definition_breaks=(
                DefinitionBreak(
                    break_date="2026-03-01", description="methodology change"
                ),
            )
        )
        d = spec.to_dict()
        assert d["definition_breaks"][0]["break_date"] == "2026-03-01"

    def test_rejects_decision_version_below_one(self):
        with pytest.raises(ValueError, match="decision_version must be >= 1"):
            _spec(decision_version=0)

    def test_rejects_effective_start_after_effective_end(self):
        with pytest.raises(ValueError, match="effective_start must not be after"):
            _spec(effective_start="2026-06-01", effective_end="2026-01-01")

    def test_default_parameters_is_an_empty_dict_not_shared_across_instances(self):
        """A mutable default_factory, not a shared mutable default -
        mutating one instance's parameters must never leak into another."""
        spec_a = _spec()
        spec_b = _spec()
        assert spec_a.parameters == {}
        assert spec_a.parameters is not spec_b.parameters

    def test_decision_version_and_parameters_distinguish_otherwise_identical_specs(
        self,
    ):
        """Review finding: source_version identifies the input source, not
        the alignment decision - two specs sharing method_id must still be
        distinguishable by decision_version/parameters."""
        spec_v1 = _spec(method_id="m1", decision_version=1, parameters={"weight": 0.5})
        spec_v2 = _spec(method_id="m1", decision_version=2, parameters={"weight": 0.7})
        assert spec_v1.to_dict() != spec_v2.to_dict()

    def test_effective_period_is_distinct_from_support_boundary(self):
        spec = _spec(
            support_start="2020-01-01",
            support_end="2026-12-31",
            effective_start="2026-01-01",
            effective_end="2026-06-30",
        )
        d = spec.to_dict()
        assert d["support_start"] == "2020-01-01"
        assert d["effective_start"] == "2026-01-01"
        assert d["support_start"] != d["effective_start"]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


class TestPublicationLeakageCheck:
    def test_leaks_when_as_of_is_before_period_end_and_no_lag(self):
        assert (
            check_publication_leakage(
                reconstructed_period_end="2026-06-30",
                as_of="2026-06-15",
                native_frequency="monthly",
                publication_lag_periods=0,
            )
            is True
        )

    def test_no_leak_when_as_of_is_on_or_after_period_end_and_no_lag(self):
        assert (
            check_publication_leakage(
                reconstructed_period_end="2026-06-30",
                as_of="2026-06-30",
                native_frequency="monthly",
                publication_lag_periods=0,
            )
            is False
        )
        assert (
            check_publication_leakage(
                reconstructed_period_end="2026-06-30",
                as_of="2026-07-15",
                native_frequency="monthly",
                publication_lag_periods=0,
            )
            is False
        )

    def test_lag_is_actually_honoured(self):
        """Review finding: an earlier version accepted
        publication_lag_periods but never used it - a monthly value
        released one month after period end must still leak at July 15
        even though July 15 is after the June 30 period end."""
        assert (
            check_publication_leakage(
                reconstructed_period_end="2026-06-30",
                as_of="2026-07-15",
                native_frequency="monthly",
                publication_lag_periods=1,
            )
            is True
        )

    def test_no_leak_once_the_lag_has_elapsed(self):
        assert (
            check_publication_leakage(
                reconstructed_period_end="2026-06-30",
                as_of="2026-08-01",
                native_frequency="monthly",
                publication_lag_periods=1,
            )
            is False
        )

    def test_unrecognised_frequency_fails_closed(self):
        """No fixed step to advance by - report leakage rather than
        assume the lag has already elapsed."""
        assert (
            check_publication_leakage(
                reconstructed_period_end="2026-06-30",
                as_of="2027-01-01",
                native_frequency="irregular",
                publication_lag_periods=2,
            )
            is True
        )


class TestDefinitionBreakCrossingCheck:
    def test_returns_none_when_no_break_in_range(self):
        breaks = (DefinitionBreak(break_date="2026-12-01", description="future break"),)
        assert (
            check_definition_break_crossing(
                period_start="2026-01-01",
                period_end="2026-01-31",
                definition_breaks=breaks,
            )
            is None
        )

    def test_returns_the_break_when_it_falls_inside_the_period(self):
        breaks = (
            DefinitionBreak(break_date="2026-01-15", description="methodology change"),
        )
        result = check_definition_break_crossing(
            period_start="2026-01-01",
            period_end="2026-01-31",
            definition_breaks=breaks,
        )
        assert result is not None
        assert result.break_date == "2026-01-15"

    def test_approved_bridge_treatment_does_not_block(self):
        breaks = (
            DefinitionBreak(
                break_date="2026-01-15",
                description="methodology change",
                bridge_treatment_approved=True,
                approved_by="Jane",
                approved_at="2026-08-11",
            ),
        )
        assert (
            check_definition_break_crossing(
                period_start="2026-01-01",
                period_end="2026-01-31",
                definition_breaks=breaks,
            )
            is None
        )


class TestSupportBoundaryCheck:
    def test_within_bounds_is_true(self):
        assert check_support_boundary(
            period="2026-06-01", support_start="2026-01-01", support_end="2026-12-31"
        )

    def test_before_support_start_is_false(self):
        assert not check_support_boundary(
            period="2025-12-01", support_start="2026-01-01", support_end="2026-12-31"
        )

    def test_after_support_end_is_false(self):
        assert not check_support_boundary(
            period="2027-01-01", support_start="2026-01-01", support_end="2026-12-31"
        )

    def test_no_declared_boundary_is_true(self):
        assert check_support_boundary(
            period="2026-06-01", support_start=None, support_end=None
        )


# ---------------------------------------------------------------------------
# evaluate_alignment_request - always unsupported today (no method approved)
# ---------------------------------------------------------------------------


class TestEvaluateAlignmentRequest:
    def test_no_approved_method_returns_unsupported(self):
        result = evaluate_alignment_request(_spec())
        assert result.status == "unsupported_no_approved_method"
        assert result.supported is False
        assert "flow_count" in result.reason

    def test_definition_break_takes_priority_when_period_supplied(self):
        breaks = (
            DefinitionBreak(break_date="2026-01-15", description="methodology change"),
        )
        spec = _spec(definition_breaks=breaks)
        result = evaluate_alignment_request(
            spec, period_start="2026-01-01", period_end="2026-01-31"
        )
        assert result.status == "unsupported_definition_break"
        assert "2026-01-15" in result.reason

    def test_no_period_supplied_skips_definition_break_check(self):
        breaks = (
            DefinitionBreak(break_date="2026-01-15", description="methodology change"),
        )
        spec = _spec(definition_breaks=breaks)
        result = evaluate_alignment_request(spec)
        assert result.status == "unsupported_no_approved_method"

    def test_to_dict_reports_supported_false(self):
        result = evaluate_alignment_request(_spec())
        d = result.to_dict()
        assert d["supported"] is False
        assert d["status"] == "unsupported_no_approved_method"

    def test_leakage_blocks_before_method_resolution(self):
        spec = _spec(native_frequency="monthly", publication_lag_periods=1)
        result = evaluate_alignment_request(
            spec, period_end="2026-06-30", as_of="2026-07-15"
        )
        assert result.status == "unsupported_leakage"
        assert result.supported is False

    def test_no_leakage_falls_through_to_method_resolution(self):
        spec = _spec(native_frequency="monthly", publication_lag_periods=1)
        result = evaluate_alignment_request(
            spec, period_end="2026-06-30", as_of="2026-08-01"
        )
        assert result.status == "unsupported_no_approved_method"

    def test_method_available_once_registered_and_approved(self):
        """Review finding: registering an approved method must be
        sufficient on its own - evaluate_alignment_request's own logic
        must not need rewriting to actually honour it."""
        register_conversion_method(
            ConversionMethodSpec(
                method_id="test-only-eval-method",
                version=1,
                variable_class="flow_count",
                description="approved, registered for this test only",
                approved=True,
                approved_by="Jane",
                approved_at="2026-08-11",
            )
        )
        try:
            result = evaluate_alignment_request(
                _spec(method_id="test-only-eval-method")
            )
            assert result.status == "method_available"
            assert result.supported is True
            assert "test-only-eval-method" in result.reason
        finally:
            from ancestry_mmm.core import frequency_alignment as fa

            fa._METHOD_REGISTRY.pop(("flow_count", "test-only-eval-method"), None)

    def test_definition_break_still_blocks_an_approved_method(self):
        register_conversion_method(
            ConversionMethodSpec(
                method_id="test-only-eval-method-2",
                version=1,
                variable_class="flow_count",
                description="approved, registered for this test only",
                approved=True,
                approved_by="Jane",
                approved_at="2026-08-11",
            )
        )
        breaks = (
            DefinitionBreak(break_date="2026-01-15", description="methodology change"),
        )
        try:
            spec = _spec(definition_breaks=breaks)
            result = evaluate_alignment_request(
                spec, period_start="2026-01-01", period_end="2026-01-31"
            )
            assert result.status == "unsupported_definition_break"
        finally:
            from ancestry_mmm.core import frequency_alignment as fa

            fa._METHOD_REGISTRY.pop(("flow_count", "test-only-eval-method-2"), None)


# ---------------------------------------------------------------------------
# Canonical calendar - fails closed without governed configuration
# ---------------------------------------------------------------------------


class TestResolveCanonicalCalendar:
    def test_raises_when_all_three_are_missing(self):
        with pytest.raises(CalendarResolutionRequiredError) as exc:
            resolve_canonical_calendar(
                governed_start=None, governed_end=None, governed_frequency=None
            )
        assert "governed_start" in str(exc.value)
        assert "governed_end" in str(exc.value)
        assert "governed_frequency" in str(exc.value)

    def test_raises_when_only_frequency_is_missing(self):
        with pytest.raises(CalendarResolutionRequiredError) as exc:
            resolve_canonical_calendar(
                governed_start="2026-01-01",
                governed_end="2026-12-31",
                governed_frequency=None,
            )
        assert "governed_frequency" in str(exc.value)
        assert "governed_start" not in str(exc.value)

    def test_returns_calendar_when_all_three_are_supplied(self):
        calendar = resolve_canonical_calendar(
            governed_start="2026-01-01",
            governed_end="2026-12-31",
            governed_frequency="weekly",
        )
        assert isinstance(calendar, CanonicalCalendar)
        assert calendar.start == "2026-01-01"
        assert calendar.end == "2026-12-31"
        assert calendar.frequency == "weekly"

    def test_calendar_rejects_start_after_end(self):
        with pytest.raises(ValueError, match="start must not be after end"):
            CanonicalCalendar(start="2026-12-31", end="2026-01-01", frequency="weekly")

    def test_calendar_to_dict(self):
        calendar = CanonicalCalendar(
            start="2026-01-01", end="2026-12-31", frequency="weekly"
        )
        assert calendar.to_dict() == {
            "start": "2026-01-01",
            "end": "2026-12-31",
            "frequency": "weekly",
        }
