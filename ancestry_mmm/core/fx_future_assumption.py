"""Future FX assumptions and cross-market currency-typed resources
(`REQ-FX-005`; Decision 13 build-out of the "Post-UI/UX Implementation
Instructions: Approved Business Decisions" brief).

See `docs/governed_fx_contract_implementation_decision_record.md` for
the full options-considered decision record. No actual future rate
value, forward curve, or budget-rate source is invented anywhere in this
module, including its tests - every example uses a clearly synthetic
value.

Summary (see the decision record for full reasoning):

1. `FutureFXAssumption` (Requirement 1): a future/planning exchange rate
   is a governed assumption object, never the current live spot rate
   substituted automatically for an official scenario.
2. `CurrencyResource` (Requirement 4): a typed cross-market budget
   resource - a cross-market total must never sum mixed local currencies
   directly.
3. `validate_cross_market_currency_translation` (Requirement 4): every
   local decision variable must carry an explicit FX translation into
   the group-currency resource before an optimiser runs - never silently
   coerced.
4. `WithinMarketPlanTranslation` (Requirement 3): a plan entered in
   market reporting currency, translated into model/group currency,
   with both the local value and its consolidated equivalent displayed
   alongside the specific FX assumption used.

This module does not select a default future-FX method, a typed-
resource naming convention beyond its own introduced shape, or wire
anything into `core.planning.future_context`/`core.optimization` - see
the decision record's "What this record does not implement."
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence, cast

FX_FUTURE_ASSUMPTION_SCHEMA_VERSION = 1

FUTURE_FX_METHOD_FINANCE_BUDGET_RATE = "finance_budget_rate"
FUTURE_FX_METHOD_LATEST_OBSERVED = "latest_observed"
FUTURE_FX_METHOD_TRAILING_AVERAGE = "trailing_average"
FUTURE_FX_METHOD_MANUAL_FIXED = "manual_fixed"
FUTURE_FX_METHOD_FORWARD_CURVE = "forward_curve"

FUTURE_FX_METHODS = (
    FUTURE_FX_METHOD_FINANCE_BUDGET_RATE,
    FUTURE_FX_METHOD_LATEST_OBSERVED,
    FUTURE_FX_METHOD_TRAILING_AVERAGE,
    FUTURE_FX_METHOD_MANUAL_FIXED,
    FUTURE_FX_METHOD_FORWARD_CURVE,
)


def _is_iso_currency_shaped(value: str) -> bool:
    return len(value) == 3 and value.isalpha() and value.isupper()


@dataclass(frozen=True)
class FutureFXAssumption:
    """Requirement 1: a governed future/planning exchange-rate
    assumption - never a silently substituted live spot rate."""

    assumption_id: str
    scenario_id: str
    source_currency: str
    target_currency: str
    start_date: str
    end_date: str
    method: str
    rate: Decimal
    source_rate_set_id: Optional[str] = None
    lookback_window_weeks: Optional[int] = None
    approval_status: str = "pending"
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    schema_version: int = FX_FUTURE_ASSUMPTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.assumption_id:
            raise ValueError("FutureFXAssumption requires an assumption_id.")
        if not self.scenario_id:
            raise ValueError("FutureFXAssumption requires a scenario_id.")
        if not _is_iso_currency_shaped(self.source_currency):
            raise ValueError(
                f"FutureFXAssumption.source_currency must be ISO-4217-"
                f"shaped, got {self.source_currency!r}."
            )
        if not _is_iso_currency_shaped(self.target_currency):
            raise ValueError(
                f"FutureFXAssumption.target_currency must be ISO-4217-"
                f"shaped, got {self.target_currency!r}."
            )
        if self.end_date < self.start_date:
            raise ValueError("FutureFXAssumption.end_date must not precede start_date.")
        if self.method not in FUTURE_FX_METHODS:
            raise ValueError(
                f"FutureFXAssumption: unknown method {self.method!r} "
                f"(expected one of {FUTURE_FX_METHODS})."
            )
        if not isinstance(self.rate, Decimal):
            raise ValueError(
                f"FutureFXAssumption.rate must be a Decimal, got "
                f"{type(self.rate).__name__}."
            )
        if self.rate <= 0:
            raise ValueError("FutureFXAssumption.rate must be strictly positive.")
        if self.approval_status not in ("pending", "approved", "rejected"):
            raise ValueError(
                f"FutureFXAssumption: unknown approval_status {self.approval_status!r}."
            )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["rate"] = str(self.rate)
        return payload

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "FutureFXAssumption":
        payload = dict(values)
        if "rate" in payload:
            payload["rate"] = Decimal(str(payload["rate"]))
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in payload.items() if k in known}))


@dataclass(frozen=True)
class CurrencyResource:
    """Requirement 4: a typed cross-market budget resource - `unit` is
    always `"currency"` (distinguishing it from a delivery-quantity
    resource) and `currency` is explicit. A cross-market total must
    never sum mixed local currencies directly - every local amount
    feeding this resource must already have been translated."""

    resource_id: str
    currency: str
    total_amount: Decimal
    unit: str = "currency"

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("CurrencyResource requires a resource_id.")
        if self.unit != "currency":
            raise ValueError(
                f"CurrencyResource.unit must be 'currency', got {self.unit!r}."
            )
        if not _is_iso_currency_shaped(self.currency):
            raise ValueError(
                f"CurrencyResource.currency must be ISO-4217-shaped, got "
                f"{self.currency!r}."
            )
        if not isinstance(self.total_amount, Decimal):
            raise ValueError(
                f"CurrencyResource.total_amount must be a Decimal, got "
                f"{type(self.total_amount).__name__}."
            )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["total_amount"] = str(self.total_amount)
        return payload


@dataclass(frozen=True)
class LocalDecisionVariable:
    """One market's local-currency decision variable, before translation
    into a `CurrencyResource` (Requirement 4)."""

    market: str
    local_currency: str
    local_amount: Decimal
    fx_assumption_id: Optional[str] = None


@dataclass(frozen=True)
class CrossMarketTranslationResult:
    """The result of translating every `LocalDecisionVariable` into one
    group-currency `CurrencyResource` - the optimiser's own pre-solve
    validation output (Requirement 4: "must validate every conversion
    before solving, never silently coercing mismatched currencies")."""

    resource: CurrencyResource
    translated_amounts_by_market: Mapping[str, Decimal]

    def to_dict(self) -> dict:
        return {
            "resource": self.resource.to_dict(),
            "translated_amounts_by_market": {
                market: str(amount)
                for market, amount in self.translated_amounts_by_market.items()
            },
        }


def validate_cross_market_currency_translation(
    resource_id: str,
    group_currency: str,
    local_variables: Sequence[LocalDecisionVariable],
    rate_by_local_currency: Mapping[str, Decimal],
) -> CrossMarketTranslationResult:
    """Requirement 4: translate every `local_variables` entry into
    `group_currency` using `rate_by_local_currency` (a caller-supplied
    `{local_currency: rate}` mapping, following the `target = source *
    rate` convention with `local_currency` as source and `group_
    currency` as target), and validate every entry actually has a rate
    before summing. Raises if any local currency is missing from `rate_
    by_local_currency`, or if a variable already matches `group_
    currency` but still carries a rate (ambiguous double-conversion
    risk) - never silently coerces or skips a mismatched currency."""
    if not local_variables:
        raise ValueError(
            "validate_cross_market_currency_translation requires at least "
            "one local decision variable."
        )
    translated: dict[str, Decimal] = {}
    total = Decimal("0")
    for variable in local_variables:
        if variable.local_currency == group_currency:
            translated[variable.market] = variable.local_amount
            total += variable.local_amount
            continue
        if variable.local_currency not in rate_by_local_currency:
            raise ValueError(
                f"validate_cross_market_currency_translation: no FX rate "
                f"supplied for market {variable.market!r}'s local currency "
                f"{variable.local_currency!r} - every local decision "
                "variable must carry an explicit FX translation before "
                "the optimiser runs."
            )
        rate = rate_by_local_currency[variable.local_currency]
        if rate <= 0:
            raise ValueError(
                f"validate_cross_market_currency_translation: rate for "
                f"{variable.local_currency!r} must be positive."
            )
        translated_amount = variable.local_amount * rate
        translated[variable.market] = translated_amount
        total += translated_amount
    resource = CurrencyResource(
        resource_id=resource_id, currency=group_currency, total_amount=total
    )
    return CrossMarketTranslationResult(
        resource=resource, translated_amounts_by_market=translated
    )


@dataclass(frozen=True)
class WithinMarketPlanTranslation:
    """Requirement 3: a plan entered in market reporting currency,
    translated into model/group currency - both values, and the specific
    FX assumption used, must be displayed together, never only the
    converted figure with the assumption left implicit."""

    market: str
    local_currency: str
    local_amount: Decimal
    consolidated_currency: str
    consolidated_amount: Decimal
    fx_assumption_id: str
    fx_assumption_method: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["local_amount"] = str(self.local_amount)
        payload["consolidated_amount"] = str(self.consolidated_amount)
        return payload


def translate_within_market_plan(
    market: str,
    local_amount: Decimal,
    assumption: FutureFXAssumption,
) -> WithinMarketPlanTranslation:
    """Apply `assumption` to translate a market-currency plan value into
    its consolidated equivalent, retaining both values and the
    assumption's own identity/method (Requirement 3)."""
    if assumption.source_currency == assumption.target_currency:
        raise ValueError(
            "translate_within_market_plan: assumption source_currency and "
            "target_currency must differ."
        )
    consolidated = local_amount * assumption.rate
    return WithinMarketPlanTranslation(
        market=market,
        local_currency=assumption.source_currency,
        local_amount=local_amount,
        consolidated_currency=assumption.target_currency,
        consolidated_amount=consolidated,
        fx_assumption_id=assumption.assumption_id,
        fx_assumption_method=assumption.method,
    )
