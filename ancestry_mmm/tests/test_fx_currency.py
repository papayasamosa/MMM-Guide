"""Tests for `ancestry_mmm.core.fx_currency` (REQ-FX-001 build-out).
No actual exchange rate appears anywhere in this file."""

from decimal import Decimal

import pytest

from ancestry_mmm.core.fx_currency import MonetaryObservation


def _observation(**overrides):
    defaults = dict(
        observation_id="obs1",
        market="UK",
        channel="paid_search",
        activity_id="act1",
        period_start="2026-01-01",
        period_end="2026-01-07",
        transaction_amount=Decimal("1000.00"),
        transaction_currency="GBP",
        source_system="platform_x",
        source_record_id="rec1",
    )
    defaults.update(overrides)
    return MonetaryObservation(**defaults)


class TestMonetaryObservation:
    def test_valid_minimal_observation(self):
        obs = _observation()
        assert obs.market_reporting_amount is None
        assert obs.transaction_currency == "GBP"

    def test_requires_decimal_transaction_amount(self):
        with pytest.raises(ValueError, match="Decimal"):
            _observation(transaction_amount=1000.0)

    def test_rejects_non_iso_shaped_currency(self):
        with pytest.raises(ValueError, match="ISO-4217"):
            _observation(transaction_currency="gbp")
        with pytest.raises(ValueError, match="ISO-4217"):
            _observation(transaction_currency="POUND")

    def test_conversion_amount_requires_currency_and_rate_id(self):
        with pytest.raises(ValueError, match="market_reporting_currency"):
            _observation(market_reporting_amount=Decimal("1000.00"))
        with pytest.raises(ValueError, match="market_fx_rate_id"):
            _observation(
                market_reporting_amount=Decimal("1000.00"),
                market_reporting_currency="GBP",
            )

    def test_valid_full_observation_with_all_conversions(self):
        obs = _observation(
            market_reporting_amount=Decimal("1000.00"),
            market_reporting_currency="GBP",
            market_fx_rate_id="rate1",
            group_reporting_amount=Decimal("1270.00"),
            group_reporting_currency="USD",
            group_fx_rate_id="rate2",
            model_currency_amount=Decimal("1270.00"),
            model_currency="USD",
            model_fx_rate_id="rate2",
        )
        assert obs.group_reporting_currency == "USD"

    def test_round_trip(self):
        obs = _observation(
            market_reporting_amount=Decimal("1000.00"),
            market_reporting_currency="GBP",
            market_fx_rate_id="rate1",
        )
        restored = MonetaryObservation.from_dict(obs.to_dict())
        assert restored == obs

    def test_original_amount_never_conflated_with_converted(self):
        # Original transaction fields remain distinct from every conversion.
        obs = _observation(
            market_reporting_amount=Decimal("999.00"),
            market_reporting_currency="GBP",
            market_fx_rate_id="rate1",
        )
        assert obs.transaction_amount == Decimal("1000.00")
        assert obs.market_reporting_amount == Decimal("999.00")

    def test_requires_observation_id_and_market(self):
        with pytest.raises(ValueError, match="observation_id"):
            _observation(observation_id="")
        with pytest.raises(ValueError, match="market"):
            _observation(market="")
