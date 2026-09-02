"""Tests for the governed weekly aggregate outcome-valuation input contract
(REQ-ECON-002): `WeeklyOutcomeValuationRecord`,
`validate_weekly_outcome_valuation_catalogue`, and
`cross_validate_against_observed_denominator`.

These tests cover only the input contract - identity, currency metadata,
denominator linkage, and fail-closed missingness (including the explicit
zero-denominator/zero-outcome carve-out). Rate derivation and the
posterior join are REQ-ECON-003's scope and are not exercised here.
"""

import pandas as pd
import pytest

from ancestry_mmm.core.outcome_valuation import (
    VALUATION_KIND_DNA_REVENUE,
    VALUATION_KIND_FH_LTR,
    WeeklyOutcomeValuationRecord,
    cross_validate_against_observed_denominator,
    validate_weekly_outcome_valuation_catalogue,
)
from ancestry_mmm.core.outcomes import (
    DNA,
    FAMILY_HISTORY,
    FH_LTR_HORIZON_MONTHS,
    METRIC_KEY_DNA_KIT_SALE_TOTAL,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
)


def _fh_denominator_outcome(outcome_id: str = "fh_gsa_new") -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id=outcome_id,
        product=FAMILY_HISTORY,
        segment="New",
        metric="GSA",
        metric_key=METRIC_KEY_FH_GSA,
        source_column="fh_gsa_new",
        aggregation_type="count",
    )


def _dna_denominator_outcome(
    outcome_id: str = "dna_kit_orders_new",
) -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id=outcome_id,
        product=DNA,
        segment="New Customer",
        metric="DNA kit orders",
        metric_key=METRIC_KEY_DNA_KIT_SALE_TOTAL,
        source_column="dna_kit_orders_new",
        aggregation_type="count",
    )


def _valid_fh_record(**overrides) -> WeeklyOutcomeValuationRecord:
    values = dict(
        valuation_kind=VALUATION_KIND_FH_LTR,
        market="UK",
        week="2025-01-06",
        segment="New",
        denominator_outcome_id="fh_gsa_new",
        quality_status="observed_zero",
        aggregate_value=0.0,
        currency="GBP",
        horizon_months=FH_LTR_HORIZON_MONTHS,
    )
    values.update(overrides)
    return WeeklyOutcomeValuationRecord(**values)


class TestRecordConstruction:
    def test_valid_record_constructs(self):
        record = _valid_fh_record()
        assert record.valuation_kind == VALUATION_KIND_FH_LTR

    def test_unknown_valuation_kind_rejected(self):
        with pytest.raises(ValueError, match="unknown valuation_kind"):
            _valid_fh_record(valuation_kind="something_else")

    def test_blank_market_rejected(self):
        with pytest.raises(ValueError, match="requires a market"):
            _valid_fh_record(market="")

    def test_invalid_week_rejected(self):
        with pytest.raises(ValueError, match="invalid week"):
            _valid_fh_record(week="not-a-date")

    def test_blank_segment_rejected(self):
        with pytest.raises(ValueError, match="requires a segment"):
            _valid_fh_record(segment="")

    def test_unknown_segment_dimension_rejected(self):
        with pytest.raises(ValueError, match="unknown segment_dimension"):
            _valid_fh_record(segment_dimension="not_a_real_dimension")

    def test_blank_denominator_outcome_id_rejected(self):
        """REQ-ECON-002 Requirement 3: no default denominator - a blank
        reference must be rejected outright, never silently defaulted."""
        with pytest.raises(ValueError, match="explicit denominator_outcome_id"):
            _valid_fh_record(denominator_outcome_id="")

    def test_unknown_quality_status_rejected(self):
        with pytest.raises(ValueError, match="unknown quality_status"):
            _valid_fh_record(quality_status="not_a_real_state")

    def test_missing_expected_requires_none_value(self):
        with pytest.raises(ValueError, match="must be None"):
            _valid_fh_record(
                quality_status="missing_expected", aggregate_value=1.0, currency="GBP"
            )

    def test_missing_expected_with_none_value_is_valid(self):
        record = _valid_fh_record(
            quality_status="missing_expected", aggregate_value=None, currency=None
        )
        assert record.aggregate_value is None

    def test_observed_zero_requires_a_value(self):
        with pytest.raises(ValueError, match="requires a non-None aggregate_value"):
            _valid_fh_record(
                quality_status="observed_zero", aggregate_value=None, currency=None
            )

    def test_observed_zero_requires_value_of_exactly_zero(self):
        with pytest.raises(ValueError, match="requires aggregate_value == 0"):
            _valid_fh_record(
                quality_status="observed_zero", aggregate_value=5.0, currency="GBP"
            )

    def test_negative_value_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            _valid_fh_record(
                quality_status="modelled", aggregate_value=-1.0, currency="GBP"
            )

    def test_currency_required_when_value_present(self):
        """REQ-ECON-002 Requirement 7: currency is mandatory whenever a
        value is present, and never inferred from market - even a genuine
        zero still needs its currency declared."""
        with pytest.raises(ValueError, match="currency is required"):
            _valid_fh_record(
                quality_status="observed_zero", aggregate_value=0.0, currency=None
            )

    def test_lowercase_currency_rejected(self):
        with pytest.raises(ValueError, match="not a valid ISO-3"):
            _valid_fh_record(currency="gbp")

    def test_four_letter_currency_rejected(self):
        with pytest.raises(ValueError, match="not a valid ISO-3"):
            _valid_fh_record(currency="GBPX")

    def test_fh_ltr_record_requires_48_month_horizon(self):
        """REQ-OUT-003 §1/§6: a missing horizon on an FH LTR record blocks
        construction rather than silently proceeding."""
        with pytest.raises(ValueError, match="horizon_months == 48"):
            _valid_fh_record(horizon_months=None)

    def test_fh_ltr_record_rejects_a_different_stale_horizon(self):
        """A stale, incorrect duration figure must be blocked, not guessed
        to be the approved 48-month horizon."""
        with pytest.raises(ValueError, match="horizon_months == 48"):
            _valid_fh_record(horizon_months=36)

    def test_dna_revenue_record_must_not_carry_a_horizon(self):
        """horizon_months is an FH-LTR-only concept; a DNA revenue record
        carrying one is rejected rather than silently ignored."""
        with pytest.raises(ValueError, match="only meaningful for"):
            WeeklyOutcomeValuationRecord(
                valuation_kind=VALUATION_KIND_DNA_REVENUE,
                market="UK",
                week="2025-01-06",
                segment="New Customer",
                denominator_outcome_id="dna_kit_orders_new",
                quality_status="modelled",
                aggregate_value=1234.56,
                currency="GBP",
                horizon_months=FH_LTR_HORIZON_MONTHS,
            )

    def test_dna_revenue_record_is_distinct_kind(self):
        record = WeeklyOutcomeValuationRecord(
            valuation_kind=VALUATION_KIND_DNA_REVENUE,
            market="UK",
            week="2025-01-06",
            segment="New Customer",
            denominator_outcome_id="dna_kit_orders_new",
            quality_status="modelled",
            aggregate_value=1234.56,
            currency="GBP",
        )
        assert record.valuation_kind == VALUATION_KIND_DNA_REVENUE


class TestFingerprintAndRoundTrip:
    def test_fingerprint_is_deterministic(self):
        a = _valid_fh_record()
        b = _valid_fh_record()
        assert a.fingerprint() == b.fingerprint()

    def test_fingerprint_changes_with_value(self):
        a = _valid_fh_record()
        b = _valid_fh_record(quality_status="modelled", aggregate_value=1.0)
        assert a.fingerprint() != b.fingerprint()

    def test_round_trip_through_dict(self):
        record = _valid_fh_record()
        restored = WeeklyOutcomeValuationRecord.from_dict(record.to_dict())
        assert restored == record

    def test_from_dict_ignores_unknown_keys(self):
        payload = _valid_fh_record().to_dict()
        payload["unexpected_future_field"] = "ignored-for-now"
        restored = WeeklyOutcomeValuationRecord.from_dict(payload)
        assert restored == _valid_fh_record()

    def test_cell_key_identifies_the_grain(self):
        record = _valid_fh_record()
        assert record.cell_key() == (VALUATION_KIND_FH_LTR, "UK", "2025-01-06", "New")


class TestCatalogueValidation:
    def test_valid_catalogue_has_no_issues(self):
        records = [_valid_fh_record()]
        issues = validate_weekly_outcome_valuation_catalogue(
            records, [_fh_denominator_outcome()]
        )
        assert issues == []

    def test_duplicate_cell_is_rejected(self):
        records = [_valid_fh_record(), _valid_fh_record()]
        issues = validate_weekly_outcome_valuation_catalogue(
            records, [_fh_denominator_outcome()]
        )
        assert any("Duplicate weekly outcome valuation record" in i for i in issues)

    def test_unknown_denominator_outcome_id_is_rejected(self):
        """REQ-ECON-002 Requirement 3: GSA (or anything else) must never
        be substituted merely because it's available - an unresolved
        reference is a hard validation failure, not a silent fallback."""
        records = [_valid_fh_record(denominator_outcome_id="does_not_exist")]
        issues = validate_weekly_outcome_valuation_catalogue(records, [])
        assert any(
            "does not reference any approved outcome definition" in i for i in issues
        )

    def test_non_count_denominator_is_rejected(self):
        rate_outcome = _fh_denominator_outcome()
        rate_outcome = OutcomeDefinition(
            **{**rate_outcome.to_dict(), "aggregation_type": "rate"}
        )
        records = [_valid_fh_record()]
        issues = validate_weekly_outcome_valuation_catalogue(records, [rate_outcome])
        assert any("is not a count-type outcome" in i for i in issues)

    def test_mixed_currency_within_one_valuation_kind_is_flagged(self):
        records = [
            _valid_fh_record(week="2025-01-06"),
            _valid_fh_record(
                week="2025-01-13",
                quality_status="modelled",
                aggregate_value=1.0,
                currency="USD",
            ),
        ]
        issues = validate_weekly_outcome_valuation_catalogue(
            records, [_fh_denominator_outcome()]
        )
        assert any("more than one currency" in i for i in issues)

    def test_dna_and_fh_records_do_not_collide(self):
        """Structurally separate objects: an FH and a DNA record for the
        same market/week never count as duplicates of each other."""
        fh = _valid_fh_record()
        dna = WeeklyOutcomeValuationRecord(
            valuation_kind=VALUATION_KIND_DNA_REVENUE,
            market="UK",
            week="2025-01-06",
            segment="New",
            denominator_outcome_id="dna_kit_orders_new",
            quality_status="observed_zero",
            aggregate_value=0.0,
            currency="GBP",
        )
        issues = validate_weekly_outcome_valuation_catalogue(
            [fh, dna], [_fh_denominator_outcome(), _dna_denominator_outcome()]
        )
        assert issues == []


class TestCrossValidateAgainstObservedDenominator:
    def _observed(self, rows):
        return pd.DataFrame(
            rows, columns=["outcome_id", "market", "week", "segment", "count"]
        )

    def test_zero_zero_pair_is_not_flagged(self):
        """REQ-ECON-002 Requirement 8: a genuine zero denominator paired
        with a genuine zero value is not corrupt data."""
        record = _valid_fh_record(quality_status="observed_zero", aggregate_value=0.0)
        observed = self._observed([("fh_gsa_new", "UK", "2025-01-06", "New", 0)])
        issues = cross_validate_against_observed_denominator([record], observed)
        assert issues == []

    def test_missing_value_with_zero_denominator_is_not_flagged(self):
        """A genuinely zero denominator legitimately explains an absent
        valuation record - not every missing cell is an error."""
        record = _valid_fh_record(
            quality_status="missing_expected", aggregate_value=None, currency=None
        )
        observed = self._observed([("fh_gsa_new", "UK", "2025-01-06", "New", 0)])
        issues = cross_validate_against_observed_denominator([record], observed)
        assert issues == []

    def test_missing_value_with_nonzero_denominator_is_surfaced(self):
        record = _valid_fh_record(
            quality_status="missing_expected", aggregate_value=None, currency=None
        )
        observed = self._observed([("fh_gsa_new", "UK", "2025-01-06", "New", 12)])
        issues = cross_validate_against_observed_denominator([record], observed)
        assert any("valuation is missing" in i for i in issues)

    def test_nonzero_value_with_zero_denominator_is_surfaced(self):
        """A non-zero LTR total with a genuinely zero acquisition count is
        an inconsistent case that must be surfaced, never guessed."""
        record = _valid_fh_record(
            quality_status="modelled", aggregate_value=500.0, currency="GBP"
        )
        observed = self._observed([("fh_gsa_new", "UK", "2025-01-06", "New", 0)])
        issues = cross_validate_against_observed_denominator([record], observed)
        assert any(
            "requiring a valuation rate from a zero denominator" in i for i in issues
        )

    def test_value_with_missing_denominator_is_surfaced(self):
        record = _valid_fh_record(
            quality_status="modelled", aggregate_value=500.0, currency="GBP"
        )
        observed = self._observed([("fh_gsa_new", "UK", "2025-01-06", "New", None)])
        issues = cross_validate_against_observed_denominator([record], observed)
        assert any("observed denominator outcome is missing" in i for i in issues)

    def test_no_observed_row_for_cell_is_silently_skipped(self):
        """This function only cross-checks cells present in the observed
        frame - a cell with no observed data supplied is not this
        function's concern (nothing to cross-check against)."""
        record = _valid_fh_record()
        observed = self._observed([("fh_gsa_new", "UK", "2025-02-03", "New", 10)])
        issues = cross_validate_against_observed_denominator([record], observed)
        assert issues == []
