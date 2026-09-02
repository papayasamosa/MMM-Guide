"""Tests for `ancestry_mmm.core.planning.value_prefill` (Decision 14 /
WP2G reconciliation Phase D implementation). See
`docs/scenario_value_assumption_prefill_decision_record.md` for the
decisions (P1-P3) these tests verify."""

import pytest

from ancestry_mmm.core.outcome_valuation_rates import WeeklyValueRate
from ancestry_mmm.core.planning.value_prefill import (
    PREFILL_BASIS_MOST_RECENT_OBSERVED_RATE,
    ScenarioValuePrefillSuggestion,
    suggest_value_prefill,
    suggest_value_prefills,
)


def _rate(**overrides) -> WeeklyValueRate:
    defaults = dict(
        valuation_kind="fh_ltr",
        market="UK",
        week="2026-01-05",
        segment="new",
        value_per_unit=850.0,
        currency="GBP",
        is_zero_denominator_carve_out=False,
        source_record_fingerprint="fp1",
    )
    defaults.update(overrides)
    return WeeklyValueRate(**defaults)


class TestSuggestValuePrefill:
    def test_returns_most_recent_matching_rate(self):
        rates = [
            _rate(week="2025-06-01", value_per_unit=800.0),
            _rate(week="2026-01-05", value_per_unit=850.0),
            _rate(week="2025-09-01", value_per_unit=820.0),
        ]
        suggestion = suggest_value_prefill(
            rates, valuation_kind="fh_ltr", market="UK", segment="new"
        )
        assert suggestion is not None
        assert suggestion.suggested_value == 850.0
        assert suggestion.source_week == "2026-01-05"
        assert suggestion.basis == PREFILL_BASIS_MOST_RECENT_OBSERVED_RATE

    def test_no_matching_cell_returns_none(self):
        rates = [_rate(market="UK")]
        suggestion = suggest_value_prefill(
            rates, valuation_kind="fh_ltr", market="US", segment="new"
        )
        assert suggestion is None

    def test_empty_rates_returns_none(self):
        assert (
            suggest_value_prefill(
                [], valuation_kind="fh_ltr", market="UK", segment="new"
            )
            is None
        )

    def test_excludes_zero_denominator_carve_out(self):
        rates = [
            _rate(
                week="2026-01-05",
                value_per_unit=999.0,
                is_zero_denominator_carve_out=True,
            ),
            _rate(
                week="2025-06-01",
                value_per_unit=800.0,
                is_zero_denominator_carve_out=False,
            ),
        ]
        suggestion = suggest_value_prefill(
            rates, valuation_kind="fh_ltr", market="UK", segment="new"
        )
        assert suggestion is not None
        assert suggestion.suggested_value == 800.0

    def test_only_matches_exact_valuation_kind_market_segment(self):
        rates = [
            _rate(valuation_kind="dna_revenue", value_per_unit=100.0),
            _rate(market="US", value_per_unit=200.0),
            _rate(segment="winback", value_per_unit=300.0),
            _rate(value_per_unit=850.0),
        ]
        suggestion = suggest_value_prefill(
            rates, valuation_kind="fh_ltr", market="UK", segment="new"
        )
        assert suggestion is not None
        assert suggestion.suggested_value == 850.0

    def test_requires_all_three_keys(self):
        with pytest.raises(ValueError):
            suggest_value_prefill([], valuation_kind="", market="UK", segment="new")
        with pytest.raises(ValueError):
            suggest_value_prefill([], valuation_kind="fh_ltr", market="", segment="new")
        with pytest.raises(ValueError):
            suggest_value_prefill([], valuation_kind="fh_ltr", market="UK", segment="")


class TestSuggestValuePrefills:
    def test_batch_returns_none_for_uncovered_cells(self):
        rates = [_rate()]
        result = suggest_value_prefills(
            rates,
            [
                ("fh_ltr", "UK", "new"),
                ("dna_revenue", "UK", "new"),
            ],
        )
        assert result[("fh_ltr", "UK", "new")] is not None
        assert result[("dna_revenue", "UK", "new")] is None


class TestScenarioValuePrefillSuggestion:
    def test_round_trip(self):
        suggestion = ScenarioValuePrefillSuggestion(
            valuation_kind="fh_ltr",
            market="UK",
            segment="new",
            suggested_value=850.0,
            currency="GBP",
            source_week="2026-01-05",
        )
        restored = ScenarioValuePrefillSuggestion.from_dict(suggestion.to_dict())
        assert restored == suggestion

    def test_never_applied_disclaimer_present(self):
        suggestion = ScenarioValuePrefillSuggestion(
            valuation_kind="fh_ltr",
            market="UK",
            segment="new",
            suggested_value=850.0,
            currency="GBP",
            source_week="2026-01-05",
        )
        assert "never applied automatically" in suggestion.disclaimer

    def test_rejects_negative_value(self):
        with pytest.raises(ValueError, match="negative"):
            ScenarioValuePrefillSuggestion(
                valuation_kind="fh_ltr",
                market="UK",
                segment="new",
                suggested_value=-1.0,
                currency="GBP",
                source_week="2026-01-05",
            )

    def test_rejects_invalid_currency(self):
        with pytest.raises(ValueError, match="currency"):
            ScenarioValuePrefillSuggestion(
                valuation_kind="fh_ltr",
                market="UK",
                segment="new",
                suggested_value=850.0,
                currency="gbp",
                source_week="2026-01-05",
            )
