"""Tests for `ancestry_mmm.core.fx_future_assumption` (REQ-FX-005
build-out). No actual exchange rate appears anywhere in this file."""

from decimal import Decimal

import pytest

from ancestry_mmm.core.fx_future_assumption import (
    FUTURE_FX_METHOD_MANUAL_FIXED,
    CurrencyResource,
    FutureFXAssumption,
    LocalDecisionVariable,
    translate_within_market_plan,
    validate_cross_market_currency_translation,
)


def _assumption(**overrides) -> FutureFXAssumption:
    defaults = dict(
        assumption_id="fx_assume_1",
        scenario_id="scenario_1",
        source_currency="GBP",
        target_currency="USD",
        start_date="2026-01-01",
        end_date="2026-12-31",
        method=FUTURE_FX_METHOD_MANUAL_FIXED,
        rate=Decimal("1.30"),
    )
    defaults.update(overrides)
    return FutureFXAssumption(**defaults)


class TestFutureFXAssumption:
    def test_valid_assumption(self):
        assumption = _assumption()
        assert assumption.method == FUTURE_FX_METHOD_MANUAL_FIXED

    def test_never_a_silently_substituted_spot_rate_requires_explicit_method(self):
        with pytest.raises(ValueError, match="method"):
            _assumption(method="live_spot_rate")

    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError, match="positive"):
            _assumption(rate=Decimal("0"))

    def test_end_before_start_rejected(self):
        with pytest.raises(ValueError, match="end_date"):
            _assumption(start_date="2026-12-31", end_date="2026-01-01")

    def test_round_trip(self):
        assumption = _assumption()
        restored = FutureFXAssumption.from_dict(assumption.to_dict())
        assert restored == assumption


class TestCurrencyResource:
    def test_valid_resource(self):
        resource = CurrencyResource(
            resource_id="budget1", currency="USD", total_amount=Decimal("10000.00")
        )
        assert resource.unit == "currency"

    def test_rejects_non_currency_unit(self):
        with pytest.raises(ValueError, match="unit"):
            CurrencyResource(
                resource_id="r1",
                currency="USD",
                total_amount=Decimal("100"),
                unit="impressions",
            )


class TestValidateCrossMarketCurrencyTranslation:
    def test_translates_every_market_correctly(self):
        variables = [
            LocalDecisionVariable("UK", "GBP", Decimal("1000.00")),
            LocalDecisionVariable("US", "USD", Decimal("500.00")),
        ]
        result = validate_cross_market_currency_translation(
            "cross_market_budget",
            "USD",
            variables,
            {"GBP": Decimal("1.30")},
        )
        assert result.translated_amounts_by_market["US"] == Decimal("500.00")
        assert result.translated_amounts_by_market["UK"] == Decimal("1300.000")
        assert result.resource.total_amount == Decimal("1300.000") + Decimal("500.00")

    def test_missing_rate_for_local_currency_raises(self):
        variables = [LocalDecisionVariable("UK", "GBP", Decimal("1000.00"))]
        with pytest.raises(ValueError, match="no FX rate supplied"):
            validate_cross_market_currency_translation("budget1", "USD", variables, {})

    def test_requires_at_least_one_variable(self):
        with pytest.raises(ValueError, match="at least one"):
            validate_cross_market_currency_translation("budget1", "USD", [], {})

    def test_never_silently_coerces_negative_rate(self):
        variables = [LocalDecisionVariable("UK", "GBP", Decimal("1000.00"))]
        with pytest.raises(ValueError, match="positive"):
            validate_cross_market_currency_translation(
                "budget1", "USD", variables, {"GBP": Decimal("-1.0")}
            )


class TestTranslateWithinMarketPlan:
    def test_translates_and_discloses_assumption(self):
        assumption = _assumption()
        translation = translate_within_market_plan("UK", Decimal("1000.00"), assumption)
        assert translation.local_amount == Decimal("1000.00")
        assert translation.consolidated_amount == Decimal("1300.000")
        assert translation.fx_assumption_id == "fx_assume_1"
        assert translation.fx_assumption_method == FUTURE_FX_METHOD_MANUAL_FIXED

    def test_requires_distinct_currencies_on_assumption(self):
        same_currency = _assumption(source_currency="GBP", target_currency="USD")
        # Manually construct a same-currency assumption bypassing normal
        # construction path is not possible (dataclass validates its own
        # fields, not cross-field currency identity) - this test instead
        # verifies translate_within_market_plan's own defensive check by
        # using object.__setattr__ on a copy, since FutureFXAssumption
        # does not itself forbid source==target (a valid business case
        # elsewhere), only this specific translation function does.
        from dataclasses import replace

        same = replace(same_currency, target_currency="GBP")
        with pytest.raises(ValueError, match="must differ"):
            translate_within_market_plan("UK", Decimal("1000.00"), same)
