"""Tests for `ancestry_mmm.core.fx_rates` (REQ-FX-002 build-out). No
actual exchange rate appears anywhere in this file - every rate used is
a clearly synthetic test value."""

from decimal import Decimal

import pytest

from ancestry_mmm.core.fx_rates import (
    RATE_FREQUENCY_ANNUAL,
    RATE_FREQUENCY_DAILY,
    FXRateRecord,
    FXRateSet,
    build_derived_cross_rate_record,
    compute_records_fingerprint,
    derive_cross_rate,
    new_rate_set_version,
)


def _rate(**overrides) -> FXRateRecord:
    defaults = dict(
        rate_id="r1",
        rate_date="2026-01-01",
        source_currency="GBP",
        target_currency="USD",
        rate=Decimal("1.25"),
        frequency=RATE_FREQUENCY_DAILY,
        method="observed_daily",
        provider="test_provider",
        provider_series_id="series1",
        retrieved_at="2026-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    return FXRateRecord(**defaults)


class TestFXRateRecord:
    def test_valid_daily_rate(self):
        rate = _rate()
        assert rate.rate == Decimal("1.25")

    def test_requires_distinct_currencies(self):
        with pytest.raises(ValueError, match="must differ"):
            _rate(target_currency="GBP")

    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError, match="positive"):
            _rate(rate=Decimal("0"))
        with pytest.raises(ValueError, match="positive"):
            _rate(rate=Decimal("-1.0"))

    def test_annual_frequency_requires_financial_year(self):
        with pytest.raises(ValueError, match="financial_year"):
            _rate(frequency=RATE_FREQUENCY_ANNUAL)

    def test_annual_frequency_with_financial_year_is_valid(self):
        rate = _rate(frequency=RATE_FREQUENCY_ANNUAL, financial_year="FY2026")
        assert rate.financial_year == "FY2026"

    def test_non_annual_frequency_rejects_financial_year(self):
        with pytest.raises(ValueError, match="financial_year"):
            _rate(financial_year="FY2026")

    def test_derived_cross_rate_requires_derivation_path(self):
        with pytest.raises(ValueError, match="derivation_path"):
            _rate(is_derived_cross_rate=True)

    def test_non_derived_rejects_derivation_path(self):
        with pytest.raises(ValueError, match="derivation_path"):
            _rate(derivation_path=("GBP", "EUR", "AUD"))

    def test_round_trip(self):
        rate = _rate()
        restored = FXRateRecord.from_dict(rate.to_dict())
        assert restored == rate


class TestDeriveCrossRate:
    def test_derives_correctly(self):
        # Synthetic: GBP per EUR = 0.85, AUD per EUR = 1.60 -> AUD per GBP.
        gbp_per_eur = Decimal("0.85")
        aud_per_eur = Decimal("1.60")
        result = derive_cross_rate(gbp_per_eur, aud_per_eur)
        assert result == aud_per_eur / gbp_per_eur

    def test_round_trip_identity(self):
        # A per B derived, then B per A derived from it, should invert.
        a_per_ref = Decimal("2.0")
        b_per_ref = Decimal("4.0")
        b_per_a = derive_cross_rate(a_per_ref, b_per_ref)
        a_per_b = derive_cross_rate(b_per_ref, a_per_ref)
        assert (b_per_a * a_per_b) == Decimal("1.0")

    def test_rejects_non_positive_rates(self):
        with pytest.raises(ValueError):
            derive_cross_rate(Decimal("0"), Decimal("1.0"))
        with pytest.raises(ValueError):
            derive_cross_rate(Decimal("1.0"), Decimal("-1.0"))


class TestBuildDerivedCrossRateRecord:
    def test_builds_valid_record(self):
        record = build_derived_cross_rate_record(
            rate_id="derived1",
            rate_date="2026-01-01",
            source_currency="GBP",
            target_currency="AUD",
            reference_currency="EUR",
            rate_source_per_reference=Decimal("0.85"),
            rate_target_per_reference=Decimal("1.60"),
            frequency=RATE_FREQUENCY_DAILY,
            method="observed_daily",
            provider="test_provider",
            provider_series_id="series1",
            retrieved_at="2026-01-01T00:00:00Z",
        )
        assert record.is_derived_cross_rate is True
        assert record.derivation_path == ("GBP", "EUR", "AUD")
        assert record.rate == Decimal("1.60") / Decimal("0.85")


class TestFXRateSet:
    def _rate_set(self, **overrides):
        records = [_rate()]
        defaults = dict(
            rate_set_id="set1",
            rate_set_version=1,
            name="Test set",
            provider="test_provider",
            base_or_reference_currency="EUR",
            start_date="2026-01-01",
            end_date="2026-12-31",
            retrieved_at="2026-01-01T00:00:00Z",
            rate_policy="test_policy",
            records_fingerprint=compute_records_fingerprint(records),
        )
        defaults.update(overrides)
        return FXRateSet(**defaults)

    def test_valid_rate_set(self):
        rate_set = self._rate_set()
        assert rate_set.approval_status == "pending"

    def test_end_before_start_rejected(self):
        with pytest.raises(ValueError, match="end_date"):
            self._rate_set(start_date="2026-12-31", end_date="2026-01-01")

    def test_approved_requires_approver_and_timestamp(self):
        with pytest.raises(ValueError, match="approved"):
            self._rate_set(approval_status="approved")

    def test_approved_with_metadata_is_valid(self):
        rate_set = self._rate_set(
            approval_status="approved",
            approved_by="finance_team",
            approved_at="2026-01-02",
        )
        assert rate_set.approval_status == "approved"

    def test_new_version_increments_and_preserves_id(self):
        v1 = self._rate_set()
        v2 = new_rate_set_version(v1, name="Revised set")
        assert v2.rate_set_version == 2
        assert v2.rate_set_id == v1.rate_set_id
        assert v2.name == "Revised set"

    def test_new_version_rejects_identity_change(self):
        v1 = self._rate_set()
        with pytest.raises(ValueError):
            new_rate_set_version(v1, rate_set_id="other")


class TestComputeRecordsFingerprint:
    def test_deterministic(self):
        records = [_rate(rate_id="r1"), _rate(rate_id="r2")]
        fp1 = compute_records_fingerprint(records)
        fp2 = compute_records_fingerprint(list(reversed(records)))
        assert fp1 == fp2  # order-independent

    def test_changes_when_records_change(self):
        records_a = [_rate(rate_id="r1", rate=Decimal("1.25"))]
        records_b = [_rate(rate_id="r1", rate=Decimal("1.26"))]
        assert compute_records_fingerprint(records_a) != compute_records_fingerprint(
            records_b
        )
