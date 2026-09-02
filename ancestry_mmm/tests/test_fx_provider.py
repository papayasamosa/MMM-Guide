"""Tests for `ancestry_mmm.core.fx_provider` (REQ-FX-004 build-out). No
actual exchange rate appears anywhere in this file, and no network call
is ever made by any test here."""

from decimal import Decimal

import pytest

from ancestry_mmm.core.fx_provider import (
    ManualUploadFXProvider,
    ManualUploadRateRow,
    assert_no_embedded_credentials,
    find_missing_periods,
    validate_rate_records,
)
from ancestry_mmm.core.fx_rates import FXRateRecord


def _rate(**overrides) -> FXRateRecord:
    defaults = dict(
        rate_id="r1",
        rate_date="2026-01-01",
        source_currency="GBP",
        target_currency="USD",
        rate=Decimal("1.25"),
        frequency="daily",
        method="observed_daily",
        provider="test_provider",
        provider_series_id="series1",
        retrieved_at="2026-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    return FXRateRecord(**defaults)


class TestManualUploadFXProvider:
    def test_fetch_returns_matching_rows_only(self):
        rows = [
            ManualUploadRateRow(
                rate_date="2026-01-01",
                source_currency="GBP",
                target_currency="USD",
                rate=Decimal("1.25"),
                method="manual_approved_rate",
            ),
            ManualUploadRateRow(
                rate_date="2026-01-01",
                source_currency="EUR",
                target_currency="USD",
                rate=Decimal("1.10"),
                method="manual_approved_rate",
            ),
        ]
        provider = ManualUploadFXProvider(rows)
        results = provider.fetch_rates([("GBP", "USD")], "2026-01-01", "2026-01-31")
        assert len(results) == 1
        assert results[0].source_currency == "GBP"
        assert isinstance(results[0], FXRateRecord)

    def test_fetch_respects_date_range(self):
        rows = [
            ManualUploadRateRow(
                rate_date="2025-12-31",
                source_currency="GBP",
                target_currency="USD",
                rate=Decimal("1.20"),
                method="manual_approved_rate",
            )
        ]
        provider = ManualUploadFXProvider(rows)
        results = provider.fetch_rates([("GBP", "USD")], "2026-01-01", "2026-01-31")
        assert results == []

    def test_no_network_dependency_is_deterministic(self):
        # Calling fetch_rates twice with the same inputs yields identical
        # results - confirms no hidden I/O or non-determinism.
        rows = [
            ManualUploadRateRow(
                rate_date="2026-01-01",
                source_currency="GBP",
                target_currency="USD",
                rate=Decimal("1.25"),
                method="manual_approved_rate",
            )
        ]
        provider = ManualUploadFXProvider(rows)
        r1 = provider.fetch_rates([("GBP", "USD")], "2026-01-01", "2026-01-31")
        r2 = provider.fetch_rates([("GBP", "USD")], "2026-01-01", "2026-01-31")
        assert r1 == r2


class TestValidateRateRecords:
    def test_no_issues_for_clean_records(self):
        records = [
            _rate(rate_id="r1", rate_date="2026-01-01"),
            _rate(rate_id="r2", rate_date="2026-01-02"),
        ]
        assert validate_rate_records(records) == []

    def test_detects_duplicate_date(self):
        records = [
            _rate(rate_id="r1", rate_date="2026-01-01"),
            _rate(rate_id="r2", rate_date="2026-01-01"),
        ]
        issues = validate_rate_records(records)
        assert len(issues) == 1
        assert issues[0].issue_kind == "duplicate_date"

    def test_detects_implausible_rate(self):
        records = [_rate(rate_id="r1", rate=Decimal("50000"))]
        issues = validate_rate_records(records)
        assert any(i.issue_kind == "implausible_rate" for i in issues)

    def test_implausible_rate_uses_disclosed_default_bounds(self):
        records = [_rate(rate_id="r1", rate=Decimal("0.5"))]
        assert validate_rate_records(records) == []


class TestFindMissingPeriods:
    def test_finds_gaps(self):
        expected = ["2026-01-01", "2026-01-02", "2026-01-03"]
        observed = ["2026-01-01", "2026-01-03"]
        assert find_missing_periods(expected, observed) == ["2026-01-02"]

    def test_no_gaps(self):
        expected = ["2026-01-01", "2026-01-02"]
        assert find_missing_periods(expected, expected) == []


class TestAssertNoEmbeddedCredentials:
    def test_clean_payload_passes(self):
        assert_no_embedded_credentials('{"provider": "test_provider", "rate": "1.25"}')

    def test_detects_api_key(self):
        with pytest.raises(ValueError, match="credential"):
            assert_no_embedded_credentials('{"api_key": "abc123"}')

    def test_detects_bearer_token(self):
        with pytest.raises(ValueError, match="credential"):
            assert_no_embedded_credentials("Authorization: Bearer abcdef1234567890")

    def test_detects_password(self):
        with pytest.raises(ValueError, match="credential"):
            assert_no_embedded_credentials("password: hunter2")
