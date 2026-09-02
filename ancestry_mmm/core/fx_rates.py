"""FX-rate record and immutable FX-rate-set governance (`REQ-FX-002`;
Decision 13 build-out of the "Post-UI/UX Implementation Instructions:
Approved Business Decisions" brief).

See `docs/governed_fx_contract_implementation_decision_record.md` for
the full options-considered decision record. No actual exchange rate
appears anywhere in this module, including its tests - every example
uses a clearly synthetic value.

Summary (see the decision record for full reasoning):

1. `FXRateRecord` (Requirement 1): a stable `rate_id`, rate date,
   source/target currency, the rate with a fixed `target_amount =
   source_amount * rate` direction convention (never inferred from a
   provider's own display label), frequency (`daily`/`weekly`/`monthly`/
   `annual` - the last added by Decision 13's own 2026-08-30 addendum to
   this record), method (from `core.fx_conversion`'s closed vocabulary),
   provider identity, retrieval timestamp/source vintage, and an
   explicit `is_derived_cross_rate`/`derivation_path` for a derived rate.
2. `FXRateSet` (Requirement 2): versioned, immutable once used - a
   refreshed download creates a new version and a new
   `records_fingerprint`, mirroring `core.coverage.SourceVersion`'s
   already-established "immutable identity, new version on change"
   pattern exactly.
3. `derive_cross_rate` (Requirement 3): explicit, tested cross-rate
   derivation via a shared reference currency - never silently assumed
   correct from a provider's raw response shape.

This module does not select a provider, an authoritative rate set for
any purpose, or any actual rate value - see the decision record's
"What this record does not implement."
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence, Tuple, cast

FX_RATES_SCHEMA_VERSION = 1

RATE_FREQUENCY_DAILY = "daily"
RATE_FREQUENCY_WEEKLY = "weekly"
RATE_FREQUENCY_MONTHLY = "monthly"
# Added 2026-08-30 (Decision 13, REQ-FX-002 addendum): one rate per
# financial year, scoped by an explicit financial_year identifier.
RATE_FREQUENCY_ANNUAL = "annual"

RATE_FREQUENCIES = (
    RATE_FREQUENCY_DAILY,
    RATE_FREQUENCY_WEEKLY,
    RATE_FREQUENCY_MONTHLY,
    RATE_FREQUENCY_ANNUAL,
)


def _is_iso_currency_shaped(value: str) -> bool:
    return len(value) == 3 and value.isalpha() and value.isupper()


@dataclass(frozen=True)
class FXRateRecord:
    """One FX-rate observation (Requirement 1). `rate` follows the fixed
    direction convention `target_amount = source_amount * rate` -
    callers must never infer direction from a provider's own display
    label, which varies by source."""

    rate_id: str
    rate_date: str
    source_currency: str
    target_currency: str
    rate: Decimal
    frequency: str
    method: str
    provider: str
    provider_series_id: str
    retrieved_at: str
    is_derived_cross_rate: bool = False
    derivation_path: Tuple[str, ...] = ()
    financial_year: Optional[str] = None
    schema_version: int = FX_RATES_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.rate_id:
            raise ValueError("FXRateRecord requires a rate_id.")
        if not self.rate_date:
            raise ValueError("FXRateRecord requires a rate_date.")
        if not _is_iso_currency_shaped(self.source_currency):
            raise ValueError(
                f"FXRateRecord.source_currency must be ISO-4217-shaped, "
                f"got {self.source_currency!r}."
            )
        if not _is_iso_currency_shaped(self.target_currency):
            raise ValueError(
                f"FXRateRecord.target_currency must be ISO-4217-shaped, "
                f"got {self.target_currency!r}."
            )
        if self.source_currency == self.target_currency:
            raise ValueError(
                "FXRateRecord.source_currency and target_currency must differ."
            )
        if not isinstance(self.rate, Decimal):
            raise ValueError(
                f"FXRateRecord.rate must be a Decimal, got {type(self.rate).__name__}."
            )
        if self.rate <= 0:
            raise ValueError("FXRateRecord.rate must be strictly positive.")
        if self.frequency not in RATE_FREQUENCIES:
            raise ValueError(
                f"FXRateRecord: unknown frequency {self.frequency!r} "
                f"(expected one of {RATE_FREQUENCIES})."
            )
        if self.frequency == RATE_FREQUENCY_ANNUAL and not self.financial_year:
            raise ValueError(
                "FXRateRecord: frequency='annual' requires an explicit "
                "financial_year identifier."
            )
        if self.frequency != RATE_FREQUENCY_ANNUAL and self.financial_year:
            raise ValueError(
                "FXRateRecord: financial_year is only meaningful when "
                "frequency='annual'."
            )
        if self.is_derived_cross_rate and not self.derivation_path:
            raise ValueError(
                "FXRateRecord: is_derived_cross_rate=True requires a "
                "non-empty derivation_path naming every currency hop."
            )
        if not self.is_derived_cross_rate and self.derivation_path:
            raise ValueError(
                "FXRateRecord: derivation_path is only meaningful when "
                "is_derived_cross_rate=True."
            )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["rate"] = str(self.rate)
        payload["derivation_path"] = list(self.derivation_path)
        return payload

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "FXRateRecord":
        payload = dict(values)
        if "rate" in payload:
            payload["rate"] = Decimal(str(payload["rate"]))
        if "derivation_path" in payload:
            payload["derivation_path"] = tuple(payload["derivation_path"] or ())
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in payload.items() if k in known}))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_records_fingerprint(records: Sequence[FXRateRecord]) -> str:
    """The single sanctioned way to compute an `FXRateSet.records_
    fingerprint` - callers must never hash the records independently, to
    avoid two silently-diverging fingerprint definitions for the same
    concept (mirrors `core.coverage`'s own equivalent precedent)."""
    payload = [record.to_dict() for record in sorted(records, key=lambda r: r.rate_id)]
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FXRateSet:
    """A versioned, immutable-once-used collection of `FXRateRecord`s
    (Requirement 2). Mirrors `core.coverage.SourceVersion`'s
    "immutable identity, new version on change" pattern: a refreshed or
    revised download must create a new `FXRateSet` (new
    `rate_set_version`, new `records_fingerprint`), never mutate this one
    in place."""

    rate_set_id: str
    rate_set_version: int
    name: str
    provider: str
    base_or_reference_currency: str
    start_date: str
    end_date: str
    retrieved_at: str
    rate_policy: str
    records_fingerprint: str
    approval_status: str = "pending"
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    schema_version: int = FX_RATES_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.rate_set_id:
            raise ValueError("FXRateSet requires a rate_set_id.")
        if self.rate_set_version < 1:
            raise ValueError("FXRateSet.rate_set_version must be >= 1.")
        if not _is_iso_currency_shaped(self.base_or_reference_currency):
            raise ValueError(
                "FXRateSet.base_or_reference_currency must be "
                f"ISO-4217-shaped, got {self.base_or_reference_currency!r}."
            )
        if self.end_date < self.start_date:
            raise ValueError("FXRateSet.end_date must not precede start_date.")
        if len(self.records_fingerprint) != 64:
            raise ValueError(
                "FXRateSet.records_fingerprint must be a 64-character "
                "sha256 hex digest."
            )
        if self.approval_status not in ("pending", "approved", "rejected"):
            raise ValueError(
                f"FXRateSet: unknown approval_status {self.approval_status!r}."
            )
        if self.approval_status == "approved" and not (
            self.approved_by and self.approved_at
        ):
            raise ValueError(
                "FXRateSet: approval_status='approved' requires "
                "approved_by and approved_at."
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "FXRateSet":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


def new_rate_set_version(rate_set: FXRateSet, **changes: Any) -> FXRateSet:
    """Apply an edit to a rate set as a new version - never an in-place
    mutation of a rate set that may already be in use (Requirement 2)."""
    from dataclasses import replace

    for locked_field in ("rate_set_id", "rate_set_version"):
        if locked_field in changes:
            raise ValueError(
                f"{locked_field!r} is lineage/version identity and cannot "
                "be set via new_rate_set_version."
            )
    return replace(rate_set, rate_set_version=rate_set.rate_set_version + 1, **changes)


def derive_cross_rate(
    rate_a_per_reference: Decimal,
    rate_b_per_reference: Decimal,
) -> Decimal:
    """Requirement 3: derive `B per A` from two reference-currency-
    denominated rates (`A per REF`, `B per REF`) via
    `B per A = (B per REF) / (A per REF)`. Deterministic; the caller is
    responsible for recording the resulting `FXRateRecord` with
    `is_derived_cross_rate=True` and an explicit `derivation_path`."""
    if rate_a_per_reference <= 0 or rate_b_per_reference <= 0:
        raise ValueError("derive_cross_rate requires strictly positive rates.")
    return rate_b_per_reference / rate_a_per_reference


def build_derived_cross_rate_record(
    *,
    rate_id: str,
    rate_date: str,
    source_currency: str,
    target_currency: str,
    reference_currency: str,
    rate_source_per_reference: Decimal,
    rate_target_per_reference: Decimal,
    frequency: str,
    method: str,
    provider: str,
    provider_series_id: str,
    retrieved_at: str,
) -> FXRateRecord:
    """Build one `FXRateRecord` for a derived cross-rate between
    `source_currency` and `target_currency`, via `reference_currency`
    (Requirement 3). `rate_source_per_reference`/`rate_target_per_
    reference` are `source per reference`/`target per reference` -
    e.g. for GBP->AUD via EUR, `rate_source_per_reference` is
    `GBP per EUR` and `rate_target_per_reference` is `AUD per EUR`."""
    rate = derive_cross_rate(rate_source_per_reference, rate_target_per_reference)
    return FXRateRecord(
        rate_id=rate_id,
        rate_date=rate_date,
        source_currency=source_currency,
        target_currency=target_currency,
        rate=rate,
        frequency=frequency,
        method=method,
        provider=provider,
        provider_series_id=provider_series_id,
        retrieved_at=retrieved_at,
        is_derived_cross_rate=True,
        derivation_path=(source_currency, reference_currency, target_currency),
    )
