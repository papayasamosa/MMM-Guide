"""Tests for `ancestry_mmm.core.fx_reporting` (REQ-FX-006 build-out). No
actual exchange rate appears anywhere in this file."""

from decimal import Decimal

import pytest

from ancestry_mmm.core.fx_reporting import (
    CURRENCY_VIEWS,
    FxDependencySnapshot,
    FxTranslationDecompositionComponent,
    assess_fx_staleness_triggers,
    label_currency_figure,
)


class TestCurrencyViews:
    def test_four_views_declared(self):
        assert len(CURRENCY_VIEWS) == 4
        assert "transaction" in CURRENCY_VIEWS
        assert "constant_currency" in CURRENCY_VIEWS


class TestLabelCurrencyFigure:
    def test_labels_the_figure(self):
        label = label_currency_figure("Average CPA", Decimal("12.50"), "GBP")
        assert label == "Average CPA (GBP): 12.50"

    def test_rejects_non_iso_currency(self):
        with pytest.raises(ValueError, match="ISO-4217"):
            label_currency_figure("Average CPA", Decimal("12.50"), "pounds")

    def test_rejects_currency_not_in_context(self):
        with pytest.raises(ValueError, match="not among"):
            label_currency_figure(
                "Average CPA",
                Decimal("12.50"),
                "GBP",
                other_currencies_in_context=("USD", "EUR"),
            )

    def test_currency_in_context_is_fine(self):
        label = label_currency_figure(
            "Average CPA",
            Decimal("12.50"),
            "GBP",
            other_currencies_in_context=("GBP", "USD"),
        )
        assert "(GBP)" in label


class TestFxTranslationDecompositionComponent:
    def test_computes_translation_effect(self):
        component = FxTranslationDecompositionComponent(
            period_a_label="2025",
            period_b_label="2026",
            local_currency="GBP",
            reporting_currency="USD",
            period_a_rate=Decimal("1.20"),
            period_b_rate=Decimal("1.30"),
            local_amount_period_b=Decimal("1000.00"),
        )
        expected = Decimal("1000.00") * Decimal("1.30") - Decimal("1000.00") * Decimal(
            "1.20"
        )
        assert component.fx_translation_effect == expected

    def test_zero_effect_when_rate_unchanged(self):
        component = FxTranslationDecompositionComponent(
            period_a_label="2025",
            period_b_label="2026",
            local_currency="GBP",
            reporting_currency="USD",
            period_a_rate=Decimal("1.25"),
            period_b_rate=Decimal("1.25"),
            local_amount_period_b=Decimal("1000.00"),
        )
        assert component.fx_translation_effect == Decimal("0")

    def test_rejects_non_positive_rates(self):
        with pytest.raises(ValueError, match="positive"):
            FxTranslationDecompositionComponent(
                period_a_label="2025",
                period_b_label="2026",
                local_currency="GBP",
                reporting_currency="USD",
                period_a_rate=Decimal("0"),
                period_b_rate=Decimal("1.25"),
                local_amount_period_b=Decimal("1000.00"),
            )

    def test_round_trip(self):
        component = FxTranslationDecompositionComponent(
            period_a_label="2025",
            period_b_label="2026",
            local_currency="GBP",
            reporting_currency="USD",
            period_a_rate=Decimal("1.20"),
            period_b_rate=Decimal("1.30"),
            local_amount_period_b=Decimal("1000.00"),
        )
        restored = FxTranslationDecompositionComponent.from_dict(component.to_dict())
        assert restored == component


class TestAssessFxStalenessTriggers:
    def _snapshot(self, **overrides):
        defaults = dict(
            historical_rate_set_id="set1",
            historical_rate_set_fingerprint="fp1",
            market_reporting_currency="GBP",
            group_reporting_currency="USD",
            model_currency="USD",
            future_fx_assumption_id=None,
            future_fx_assumption_fingerprint=None,
            conversion_policy="policy1",
        )
        defaults.update(overrides)
        return FxDependencySnapshot(**defaults)

    def test_no_change_is_not_stale(self):
        snapshot = self._snapshot()
        result = assess_fx_staleness_triggers(snapshot, snapshot)
        assert result.is_stale is False
        assert result.reasons == ()

    def test_changed_rate_set_is_stale(self):
        previous = self._snapshot(historical_rate_set_fingerprint="fp1")
        current = self._snapshot(historical_rate_set_fingerprint="fp2")
        result = assess_fx_staleness_triggers(previous, current)
        assert result.is_stale is True
        assert "historical_rate_set_changed" in result.reasons

    def test_changed_future_assumption_is_stale(self):
        previous = self._snapshot(future_fx_assumption_fingerprint="a1")
        current = self._snapshot(future_fx_assumption_fingerprint="a2")
        result = assess_fx_staleness_triggers(previous, current)
        assert "future_fx_assumption_changed" in result.reasons

    def test_changed_conversion_policy_is_stale(self):
        previous = self._snapshot(conversion_policy="policy1")
        current = self._snapshot(conversion_policy="policy2")
        result = assess_fx_staleness_triggers(previous, current)
        assert "conversion_policy_changed" in result.reasons

    def test_reporting_currency_selection_alone_never_triggers_staleness(self):
        snapshot = self._snapshot()
        result = assess_fx_staleness_triggers(
            snapshot, snapshot, reporting_currency_selection_changed=True
        )
        assert result.is_stale is False
