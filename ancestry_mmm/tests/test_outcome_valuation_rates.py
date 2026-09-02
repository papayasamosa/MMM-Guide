"""Deterministic tests for the weekly value-per-outcome rate-derivation
engine (REQ-ECON-003 Requirements 1-2): `derive_weekly_value_rates`.

Covers the ordinary division case, the explicit zero-denominator carve-
out (both the missing-value and supplied-zero-value forms), and every
inconsistent case that must be surfaced rather than guessed. Does not
exercise the posterior draw join or uncertainty propagation - those are
REQ-ECON-003 Requirements 3-4 (WP2C), not this module's scope.
"""

import pandas as pd

from ancestry_mmm.core.outcome_valuation import (
    VALUATION_KIND_FH_LTR,
    WeeklyOutcomeValuationRecord,
)
from ancestry_mmm.core.outcome_valuation_rates import derive_weekly_value_rates
from ancestry_mmm.core.outcomes import FH_LTR_HORIZON_MONTHS


def _record(**overrides) -> WeeklyOutcomeValuationRecord:
    values = dict(
        valuation_kind=VALUATION_KIND_FH_LTR,
        market="UK",
        week="2025-01-06",
        segment="New",
        denominator_outcome_id="fh_gsa_new",
        quality_status="modelled",
        aggregate_value=1000.0,
        currency="GBP",
        horizon_months=FH_LTR_HORIZON_MONTHS,
    )
    values.update(overrides)
    return WeeklyOutcomeValuationRecord(**values)


def _observed(rows):
    return pd.DataFrame(
        rows, columns=["outcome_id", "market", "week", "segment", "count"]
    )


class TestOrdinaryDivision:
    def test_derives_the_expected_rate(self):
        record = _record(aggregate_value=1000.0)
        observed = _observed([("fh_gsa_new", "UK", "2025-01-06", "New", 50)])
        rates, issues = derive_weekly_value_rates([record], observed)
        assert issues == []
        assert len(rates) == 1
        assert rates[0].value_per_unit == 20.0
        assert rates[0].is_zero_denominator_carve_out is False
        assert rates[0].currency == "GBP"

    def test_cell_key_matches_the_source_record(self):
        record = _record()
        observed = _observed([("fh_gsa_new", "UK", "2025-01-06", "New", 50)])
        rates, _ = derive_weekly_value_rates([record], observed)
        assert rates[0].cell_key() == record.cell_key()

    def test_fingerprint_traces_back_to_the_source_record(self):
        record = _record()
        observed = _observed([("fh_gsa_new", "UK", "2025-01-06", "New", 50)])
        rates, _ = derive_weekly_value_rates([record], observed)
        assert rates[0].source_record_fingerprint == record.fingerprint()


class TestZeroDenominatorCarveOut:
    def test_missing_value_with_zero_denominator_yields_zero_rate(self):
        """REQ-ECON-003 Requirement 2: a genuinely zero denominator
        legitimately explains an absent valuation record - the derived
        rate is exactly zero, not an error."""
        record = _record(
            quality_status="missing_expected", aggregate_value=None, currency=None
        )
        observed = _observed([("fh_gsa_new", "UK", "2025-01-06", "New", 0)])
        rates, issues = derive_weekly_value_rates([record], observed)
        assert issues == []
        assert len(rates) == 1
        assert rates[0].value_per_unit == 0.0
        assert rates[0].is_zero_denominator_carve_out is True

    def test_zero_value_with_zero_denominator_yields_zero_rate(self):
        record = _record(
            quality_status="observed_zero", aggregate_value=0.0, currency="GBP"
        )
        observed = _observed([("fh_gsa_new", "UK", "2025-01-06", "New", 0)])
        rates, issues = derive_weekly_value_rates([record], observed)
        assert issues == []
        assert rates[0].value_per_unit == 0.0
        assert rates[0].is_zero_denominator_carve_out is True

    def test_never_actually_divides_by_zero(self):
        """A regression here would raise ZeroDivisionError or produce
        inf/nan instead of the governed carve-out value."""
        record = _record(
            quality_status="observed_zero", aggregate_value=0.0, currency="GBP"
        )
        observed = _observed([("fh_gsa_new", "UK", "2025-01-06", "New", 0)])
        rates, _ = derive_weekly_value_rates([record], observed)
        assert rates[0].value_per_unit == 0.0
        import math

        assert math.isfinite(rates[0].value_per_unit)


class TestInconsistentCasesAreSurfaced:
    def test_missing_value_with_nonzero_denominator_blocks(self):
        record = _record(
            quality_status="missing_expected", aggregate_value=None, currency=None
        )
        observed = _observed([("fh_gsa_new", "UK", "2025-01-06", "New", 12)])
        rates, issues = derive_weekly_value_rates([record], observed)
        assert rates == []
        assert any("valuation is missing" in i for i in issues)

    def test_nonzero_value_with_zero_denominator_blocks(self):
        record = _record(aggregate_value=500.0)
        observed = _observed([("fh_gsa_new", "UK", "2025-01-06", "New", 0)])
        rates, issues = derive_weekly_value_rates([record], observed)
        assert rates == []
        assert any("non-zero" in i for i in issues)

    def test_value_with_missing_denominator_blocks(self):
        record = _record(aggregate_value=500.0)
        observed = _observed([("fh_gsa_new", "UK", "2025-01-06", "New", None)])
        rates, issues = derive_weekly_value_rates([record], observed)
        assert rates == []
        assert any("denominator outcome is missing" in i for i in issues)

    def test_no_observed_row_for_cell_produces_neither_rate_nor_issue(self):
        record = _record()
        observed = _observed([("fh_gsa_new", "UK", "2025-02-03", "New", 10)])
        rates, issues = derive_weekly_value_rates([record], observed)
        assert rates == []
        assert issues == []


class TestMultipleCellsAreIndependent:
    def test_one_bad_cell_does_not_block_a_good_cell(self):
        good = _record(week="2025-01-06", aggregate_value=1000.0)
        bad = _record(week="2025-01-13", aggregate_value=500.0)
        observed = _observed(
            [
                ("fh_gsa_new", "UK", "2025-01-06", "New", 50),
                ("fh_gsa_new", "UK", "2025-01-13", "New", 0),
            ]
        )
        rates, issues = derive_weekly_value_rates([good, bad], observed)
        assert len(rates) == 1
        assert rates[0].value_per_unit == 20.0
        assert len(issues) == 1
