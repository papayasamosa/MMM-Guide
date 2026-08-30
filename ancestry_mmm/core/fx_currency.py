"""Currency-concept separation and canonical monetary record
(`REQ-FX-001`; Decision 13 build-out of the "Post-UI/UX Implementation
Instructions: Approved Business Decisions" brief).

See `docs/governed_fx_contract_implementation_decision_record.md` for
the full options-considered decision record and this module's explicit
scope boundary (architecture only - no currency list, default group/
model currency, or rounding policy is invented; no actual exchange rate
appears anywhere in this module, including its tests).

Summary (see the decision record for full reasoning):

1. Four distinct currency concepts, never conflated: transaction,
   market reporting, group reporting, and model currency
   (Requirement 1).
2. The original `transaction_amount`/`transaction_currency` is never
   overwritten - every conversion is a separately named, nullable field
   (Requirement 2).
3. `MonetaryObservation` is the canonical monetary record shape
   (Requirement 3): identity, the original amount/currency, the three
   converted amounts (each nullable until conversion has run), the
   specific FX-rate identifier used for each conversion, and source
   provenance.
4. Persisted amounts use Python `Decimal`, not binary floating point
   (Requirement 4) - a float conversion is the caller's own
   responsibility only at the numerical-model boundary, never performed
   by this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional, cast

FX_CURRENCY_SCHEMA_VERSION = 1


def _is_iso_currency_shaped(value: str) -> bool:
    return len(value) == 3 and value.isalpha() and value.isupper()


@dataclass(frozen=True)
class MonetaryObservation:
    """One cost-bearing observation's canonical monetary record
    (Requirement 3). `transaction_amount`/`transaction_currency` are the
    original, source-of-truth values and are never mutated by this
    class or any function in this module - every conversion is a
    separate, independently nullable field.

    `market_fx_rate_id`/`group_fx_rate_id`/`model_fx_rate_id` are opaque
    identifiers this module does not resolve itself - they reference a
    `core.fx_rates.FXRateRecord`/`FXRateSet` a caller resolves
    separately (Requirement 3's own cross-reference to `REQ-FX-002`).
    """

    observation_id: str
    market: str
    channel: str
    activity_id: str
    period_start: str
    period_end: str
    transaction_amount: Decimal
    transaction_currency: str
    source_system: str
    source_record_id: str
    market_reporting_amount: Optional[Decimal] = None
    market_reporting_currency: Optional[str] = None
    market_fx_rate_id: Optional[str] = None
    group_reporting_amount: Optional[Decimal] = None
    group_reporting_currency: Optional[str] = None
    group_fx_rate_id: Optional[str] = None
    model_currency_amount: Optional[Decimal] = None
    model_currency: Optional[str] = None
    model_fx_rate_id: Optional[str] = None
    schema_version: int = FX_CURRENCY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.observation_id:
            raise ValueError("MonetaryObservation requires an observation_id.")
        if not self.market:
            raise ValueError("MonetaryObservation requires a market.")
        if not isinstance(self.transaction_amount, Decimal):
            raise ValueError(
                "MonetaryObservation.transaction_amount must be a Decimal "
                "(Requirement 4: exact decimal arithmetic, not binary "
                f"floating point) - got {type(self.transaction_amount).__name__}."
            )
        if not _is_iso_currency_shaped(self.transaction_currency):
            raise ValueError(
                "MonetaryObservation.transaction_currency must be a "
                f"three-letter uppercase ISO-4217-shaped code, got "
                f"{self.transaction_currency!r}."
            )
        for amount_field, currency_field, rate_id_field in (
            (
                "market_reporting_amount",
                "market_reporting_currency",
                "market_fx_rate_id",
            ),
            ("group_reporting_amount", "group_reporting_currency", "group_fx_rate_id"),
            ("model_currency_amount", "model_currency", "model_fx_rate_id"),
        ):
            amount = getattr(self, amount_field)
            currency = getattr(self, currency_field)
            rate_id = getattr(self, rate_id_field)
            if amount is not None:
                if not isinstance(amount, Decimal):
                    raise ValueError(
                        f"MonetaryObservation.{amount_field} must be a "
                        f"Decimal, got {type(amount).__name__}."
                    )
                if currency is None:
                    raise ValueError(
                        f"MonetaryObservation.{amount_field} is present but "
                        f"{currency_field} is missing - a converted amount "
                        "always requires its own currency."
                    )
                if rate_id is None:
                    raise ValueError(
                        f"MonetaryObservation.{amount_field} is present but "
                        f"{rate_id_field} is missing - a converted amount "
                        "must record which FX rate produced it."
                    )
                if not _is_iso_currency_shaped(currency):
                    raise ValueError(
                        f"MonetaryObservation.{currency_field} must be a "
                        f"three-letter uppercase ISO-4217-shaped code, got "
                        f"{currency!r}."
                    )

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "MonetaryObservation":
        payload = dict(values)
        for decimal_field in (
            "transaction_amount",
            "market_reporting_amount",
            "group_reporting_amount",
            "model_currency_amount",
        ):
            if payload.get(decimal_field) is not None:
                payload[decimal_field] = Decimal(str(payload[decimal_field]))
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in payload.items() if k in known}))
