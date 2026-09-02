"""FX provider-adapter interface and network-free ingestion governance
(`REQ-FX-004`; Decision 13 build-out of the "Post-UI/UX Implementation
Instructions: Approved Business Decisions" brief).

See `docs/governed_fx_contract_implementation_decision_record.md` for
the full options-considered decision record. **No live network provider
adapter (ECB, FRED, or any corporate feed) is implemented or selected
here** - this module implements the protocol and the network-free
manual-upload tier only, exactly as `REQ-FX-004`'s own text requires
("never a hard-coded call to one specific website or API... provider
selection remains Finance-owned").

Summary (see the decision record for full reasoning):

1. `FXProvider` - the provider-adapter `Protocol` (Requirement 1).
2. `ManualUploadFXProvider` - a genuine, working reference
   implementation of the source hierarchy's own third tier ("manual
   approved upload... when an API cannot supply a required historical
   pair") that validates and normalises caller-supplied rows into
   governed `FXRateRecord`s, with no network dependency.
3. `validate_rate_records` - the network-free ingestion controls
   (Requirement 4): duplicate-date detection, missing-period detection,
   impossible-rate checks. (Timeout/retry/rate-limit handling are
   properties of a live network adapter this module does not implement.)
4. `assert_no_embedded_credentials` - Requirement 5's credential-security
   rule as a genuinely testable structural safeguard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Protocol, Sequence, Tuple

from .fx_rates import FXRateRecord

FX_PROVIDER_SCHEMA_VERSION = 1

# Recommended source hierarchy (Requirement 2) - GUIDANCE for adapter
# design only, never a selection of which adapter(s) are actually built
# or enabled for this project.
RECOMMENDED_SOURCE_HIERARCHY = (
    "finance_approved_corporate_feed",
    "official_public_central_bank_source",
    "manual_approved_upload",
)


class FXProvider(Protocol):
    """Requirement 1: FX rate retrieval must be implemented behind this
    interface, never a hard-coded call to one specific website or API.
    The provider must be configurable per project and per rate purpose."""

    def fetch_rates(
        self, currencies: Sequence[Tuple[str, str]], start_date: str, end_date: str
    ) -> List[FXRateRecord]: ...


@dataclass(frozen=True)
class ManualUploadRateRow:
    """One caller-supplied rate row for `ManualUploadFXProvider` - the
    minimum shape an analyst-provided upload (e.g. a spreadsheet row)
    must carry before it can become a governed `FXRateRecord`."""

    rate_date: str
    source_currency: str
    target_currency: str
    rate: Decimal
    method: str
    frequency: str = "daily"
    financial_year: str | None = None


class ManualUploadFXProvider:
    """Requirement 2's third source-hierarchy tier, implemented for
    real: validates and normalises caller-supplied rate rows into
    governed `FXRateRecord`s. Used "when an API cannot supply a required
    historical pair" - or, as in this repository today, when no network
    provider has been selected or authorised at all. Carries no network
    dependency, no credentials, and fetches nothing itself - the caller
    supplies every row explicitly."""

    def __init__(
        self,
        rows: Sequence[ManualUploadRateRow],
        *,
        provider_name: str = "manual_upload",
    ):
        self._rows = tuple(rows)
        self._provider_name = provider_name

    def fetch_rates(
        self, currencies: Sequence[Tuple[str, str]], start_date: str, end_date: str
    ) -> List[FXRateRecord]:
        """Return every supplied row matching one of `currencies`
        (`(source, target)` pairs) within `[start_date, end_date]`,
        as governed `FXRateRecord`s - never fetched from a network, per
        this class's own design."""
        wanted = set(currencies)
        records = []
        for index, row in enumerate(self._rows):
            if (row.source_currency, row.target_currency) not in wanted:
                continue
            if not (start_date <= row.rate_date <= end_date):
                continue
            records.append(
                FXRateRecord(
                    rate_id=f"{self._provider_name}:{row.source_currency}"
                    f"{row.target_currency}:{row.rate_date}:{index}",
                    rate_date=row.rate_date,
                    source_currency=row.source_currency,
                    target_currency=row.target_currency,
                    rate=row.rate,
                    frequency=row.frequency,
                    method=row.method,
                    provider=self._provider_name,
                    provider_series_id=f"manual:{row.source_currency}{row.target_currency}",
                    retrieved_at=row.rate_date,
                    financial_year=row.financial_year,
                )
            )
        return records


@dataclass(frozen=True)
class RateValidationIssue:
    """One issue found by `validate_rate_records` - never a silent drop;
    every issue is reported, the caller decides how to act on it."""

    issue_kind: str
    detail: str
    rate_id: str | None = None


def validate_rate_records(
    records: Sequence[FXRateRecord],
    *,
    max_plausible_rate: Decimal = Decimal("1000"),
    min_plausible_rate: Decimal = Decimal("0.0001"),
) -> List[RateValidationIssue]:
    """Requirement 4's network-free ingestion controls: duplicate-date
    detection, missing-period detection (returned separately per pair,
    not invented here since "the required period" is caller-context-
    specific), and impossible-rate checks. `max_plausible_rate`/`min_
    plausible_rate` are deliberately generous, disclosed defaults for a
    sanity check only (catching a clear data-entry error, e.g. a
    misplaced decimal point) - never a claim about any real currency
    pair's actual plausible range, which this module has no authority to
    assert."""
    issues: List[RateValidationIssue] = []
    seen_dates_by_pair: dict[tuple[str, str], set[str]] = {}
    for record in records:
        pair = (record.source_currency, record.target_currency)
        seen = seen_dates_by_pair.setdefault(pair, set())
        if record.rate_date in seen:
            issues.append(
                RateValidationIssue(
                    issue_kind="duplicate_date",
                    detail=f"Duplicate rate for {pair} on {record.rate_date}.",
                    rate_id=record.rate_id,
                )
            )
        seen.add(record.rate_date)
        if record.rate > max_plausible_rate or record.rate < min_plausible_rate:
            issues.append(
                RateValidationIssue(
                    issue_kind="implausible_rate",
                    detail=(
                        f"Rate {record.rate} for {pair} on {record.rate_date} "
                        f"is outside the plausible sanity range "
                        f"[{min_plausible_rate}, {max_plausible_rate}]."
                    ),
                    rate_id=record.rate_id,
                )
            )
    return issues


def find_missing_periods(
    expected_dates: Sequence[str], observed_dates: Sequence[str]
) -> List[str]:
    """Requirement 4's missing-period detection: every date in
    `expected_dates` not present in `observed_dates`, in order - never
    silently interpolated or ignored."""
    observed = set(observed_dates)
    return [date for date in expected_dates if date not in observed]


_CREDENTIAL_PATTERNS = (
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"bearer\s+[a-z0-9._-]{10,}", re.IGNORECASE),
    re.compile(r"secret[_-]?(key|token)", re.IGNORECASE),
    re.compile(r"password\s*[:=]", re.IGNORECASE),
    re.compile(r"access[_-]?token", re.IGNORECASE),
)


def assert_no_embedded_credentials(serialised_payload: str) -> None:
    """Requirement 5: API credentials must never be persisted inside a
    project bundle, scenario JSON, log output, or a Streamlit session
    export - only provider *identity* and retrieved rate *data* may be
    persisted. Raises `ValueError` if `serialised_payload` (e.g. a
    project-bundle JSON string about to be written to disk) contains
    anything matching a common secret-shaped pattern. This is a
    structural safeguard, not a guarantee against every possible secret
    shape - callers should still avoid ever constructing such a payload
    in the first place."""
    for pattern in _CREDENTIAL_PATTERNS:
        match = pattern.search(serialised_payload)
        if match:
            raise ValueError(
                "assert_no_embedded_credentials: payload appears to contain "
                f"a credential-shaped string matching {pattern.pattern!r} - "
                "provider secrets must never be persisted (REQ-FX-004 "
                "Requirement 5)."
            )
