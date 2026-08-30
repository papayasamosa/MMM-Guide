"""Tests for `ancestry_mmm.core.fx_conversion` (REQ-FX-003 build-out).
No actual exchange rate appears anywhere in this file."""

from decimal import Decimal

import pytest

from ancestry_mmm.core.fx_conversion import (
    CONVERSION_METHOD_FINANCE_CONSTANT_DOLLAR_ANNUAL,
    CONVERSION_METHODS,
    DEFAULT_CONVERSION_METHOD,
    apply_finance_constant_dollar_annual,
    apply_previous_business_day_fallback,
    assert_valid_conversion_method,
    convert_daily_spend,
    convert_spend_weighted_weekly,
    convert_weekly_average,
)


class TestAssertValidConversionMethod:
    def test_every_declared_method_is_valid(self):
        for method in CONVERSION_METHODS:
            assert_valid_conversion_method(method)  # no raise

    def test_unrecognised_method_fails_closed(self):
        with pytest.raises(ValueError, match="Unrecognised"):
            assert_valid_conversion_method("made_up_method")

    def test_default_method_is_finance_constant_dollar_annual(self):
        assert (
            DEFAULT_CONVERSION_METHOD
            == CONVERSION_METHOD_FINANCE_CONSTANT_DOLLAR_ANNUAL
        )


class TestConvertDailySpend:
    def test_converts_each_day_at_its_own_rate(self):
        rows = [
            ("2026-01-01", Decimal("100.00"), Decimal("1.20")),
            ("2026-01-02", Decimal("200.00"), Decimal("1.25")),
        ]
        results = convert_daily_spend(rows)
        assert results[0].converted_amount == Decimal("120.000")
        assert results[1].converted_amount == Decimal("250.00")

    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError, match="positive"):
            convert_daily_spend([("2026-01-01", Decimal("100.00"), Decimal("0"))])


class TestConvertWeeklyAverage:
    def test_arithmetic_mean_of_available_rates(self):
        rates = [Decimal("1.20"), Decimal("1.30")]
        result = convert_weekly_average("2026-W01", Decimal("1000.00"), rates, 5)
        assert result.average_rate == Decimal("1.25")
        assert result.observations_used == 2
        assert result.is_shortfall is True  # 2 < 5 expected

    def test_no_shortfall_when_observations_meet_expected(self):
        rates = [Decimal("1.20")] * 5
        result = convert_weekly_average("2026-W01", Decimal("1000.00"), rates, 5)
        assert result.is_shortfall is False

    def test_requires_at_least_one_rate(self):
        with pytest.raises(ValueError, match="at least one"):
            convert_weekly_average("2026-W01", Decimal("1000.00"), [], 5)

    def test_fails_closed_below_approved_minimum(self):
        rates = [Decimal("1.20"), Decimal("1.25")]
        with pytest.raises(ValueError, match="below the approved minimum"):
            convert_weekly_average(
                "2026-W01",
                Decimal("1000.00"),
                rates,
                5,
                approved_minimum_observations=3,
            )

    def test_no_threshold_supplied_never_raises_for_shortfall(self):
        # This module invents no default threshold - without one supplied,
        # a shortfall is reported (is_shortfall=True) but does not raise.
        rates = [Decimal("1.20")]
        result = convert_weekly_average("2026-W01", Decimal("1000.00"), rates, 5)
        assert result.is_shortfall is True


class TestConvertSpendWeightedWeekly:
    def test_computes_weighted_sum_and_effective_rate(self):
        rows = [
            (Decimal("100.00"), Decimal("1.20")),
            (Decimal("200.00"), Decimal("1.30")),
        ]
        result = convert_spend_weighted_weekly("2026-W01", rows)
        assert result.total_source_amount == Decimal("300.00")
        expected_converted = Decimal("100.00") * Decimal("1.20") + Decimal(
            "200.00"
        ) * Decimal("1.30")
        assert result.total_converted_amount == expected_converted
        assert result.effective_weekly_rate == expected_converted / Decimal("300.00")

    def test_requires_at_least_one_pair(self):
        with pytest.raises(ValueError):
            convert_spend_weighted_weekly("2026-W01", [])

    def test_effective_rate_undefined_at_zero_source(self):
        result = convert_spend_weighted_weekly(
            "2026-W01", [(Decimal("0"), Decimal("1.2"))]
        )
        with pytest.raises(ValueError, match="undefined"):
            _ = result.effective_weekly_rate


class TestApplyPreviousBusinessDayFallback:
    def test_uses_latest_prior_business_day(self):
        # Saturday transaction date, most recent Friday rate used.
        candidates = [
            ("2026-01-02", Decimal("1.25")),  # Friday
            ("2026-01-01", Decimal("1.20")),  # Thursday
        ]
        result = apply_previous_business_day_fallback("2026-01-03", candidates)
        assert result.source_observation_date == "2026-01-02"
        assert result.rate == Decimal("1.25")

    def test_no_available_prior_date_raises(self):
        with pytest.raises(ValueError, match="no available rate"):
            apply_previous_business_day_fallback(
                "2025-12-31", [("2026-01-01", Decimal("1.25"))]
            )


class TestApplyFinanceConstantDollarAnnual:
    def test_applies_uniformly(self):
        result = apply_finance_constant_dollar_annual(
            "FY2026", "2026-W01", Decimal("1000.00"), Decimal("1.30")
        )
        assert result.converted_amount == Decimal("1300.000")
        assert result.method == CONVERSION_METHOD_FINANCE_CONSTANT_DOLLAR_ANNUAL

    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError, match="positive"):
            apply_finance_constant_dollar_annual(
                "FY2026", "2026-W01", Decimal("1000.00"), Decimal("0")
            )
