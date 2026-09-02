"""Historical FX conversion-method vocabulary and computations
(`REQ-FX-003`; Decision 13 build-out of the "Post-UI/UX Implementation
Instructions: Approved Business Decisions" brief).

See `docs/governed_fx_contract_implementation_decision_record.md` for
the full options-considered decision record. No actual exchange rate
appears anywhere in this module, including its tests - every example
uses a clearly synthetic value.

Summary (see the decision record for full reasoning):

1. A closed, versioned eight-value method vocabulary
   (`CONVERSION_METHODS`) - an unrecognised method fails closed (a
   `ValueError`), never a silent fallback (Requirement 1).
2. `convert_daily_spend` (Requirement 2): each day's spend converted at
   that day's own rate before weekly summation.
3. `convert_weekly_average` (Requirement 3): arithmetic mean of
   available business-day rates for a week with only weekly-granularity
   source spend, retaining observation count/missing-day status, fails
   closed against a CALLER-SUPPLIED minimum-observation threshold (this
   module invents no such threshold).
4. `convert_spend_weighted_weekly` (Requirement 4): `sum(daily spend x
   daily rate)`, with the implied effective weekly rate always
   derivable.
5. `apply_previous_business_day_fallback` (Requirement 5): the latest
   available previous-business-day rate for a non-trading-day
   transaction date, labelled explicitly.
6. `apply_finance_constant_dollar_annual` (Decision 13's own 2026-08-30
   default method): one Finance-supplied annual rate applied uniformly
   across its financial year - no observation-count/business-day logic
   applies to this method (this record's own §5 does not apply to it).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

CONVERSION_METHOD_OBSERVED_DAILY = "observed_daily"
CONVERSION_METHOD_DAILY_SPEND_WEIGHTED_WEEKLY_AVERAGE = (
    "daily_spend_weighted_weekly_average"
)
CONVERSION_METHOD_BUSINESS_DAY_WEEKLY_AVERAGE = "business_day_weekly_average"
CONVERSION_METHOD_PREVIOUS_BUSINESS_DAY = "previous_business_day"
CONVERSION_METHOD_FINANCE_BUDGET_RATE = "finance_budget_rate"
CONVERSION_METHOD_FINANCE_ACCOUNTING_RATE = "finance_accounting_rate"
CONVERSION_METHOD_MANUAL_APPROVED_RATE = "manual_approved_rate"
# Added 2026-08-30 (Decision 13, REQ-FX-003 addendum): the approved
# DEFAULT governed FX method for MMM outputs.
CONVERSION_METHOD_FINANCE_CONSTANT_DOLLAR_ANNUAL = "finance_constant_dollar_annual"

CONVERSION_METHODS = (
    CONVERSION_METHOD_OBSERVED_DAILY,
    CONVERSION_METHOD_DAILY_SPEND_WEIGHTED_WEEKLY_AVERAGE,
    CONVERSION_METHOD_BUSINESS_DAY_WEEKLY_AVERAGE,
    CONVERSION_METHOD_PREVIOUS_BUSINESS_DAY,
    CONVERSION_METHOD_FINANCE_BUDGET_RATE,
    CONVERSION_METHOD_FINANCE_ACCOUNTING_RATE,
    CONVERSION_METHOD_MANUAL_APPROVED_RATE,
    CONVERSION_METHOD_FINANCE_CONSTANT_DOLLAR_ANNUAL,
)

# The default governed FX method for MMM outputs, per Decision 13's own
# 2026-08-30 addendum - chosen specifically so MMM outputs stay
# consistent with Finance's own constant-dollar reporting.
DEFAULT_CONVERSION_METHOD = CONVERSION_METHOD_FINANCE_CONSTANT_DOLLAR_ANNUAL


def assert_valid_conversion_method(method: str) -> None:
    """Requirement 1: an unrecognised or unapproved method must fail
    closed, never silently fall back to a different method."""
    if method not in CONVERSION_METHODS:
        raise ValueError(
            f"Unrecognised FX conversion method {method!r}; must be one of "
            f"{CONVERSION_METHODS} - an unapproved method fails closed, it "
            "never silently falls back to a different one."
        )


@dataclass(frozen=True)
class DailyConversionResult:
    """One day's converted amount (Requirement 2)."""

    date: str
    source_amount: Decimal
    rate: Decimal
    converted_amount: Decimal
    method: str = CONVERSION_METHOD_OBSERVED_DAILY

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key in ("source_amount", "rate", "converted_amount"):
            payload[key] = str(payload[key])
        return payload


def convert_daily_spend(
    daily_amounts_and_rates: Sequence[Tuple[str, Decimal, Decimal]],
) -> List[DailyConversionResult]:
    """Requirement 2: convert each day's spend at that day's own rate,
    before any weekly summation - never assume uniform spend within the
    week by converting a weekly total at a single rate. `daily_amounts_
    and_rates` is a sequence of `(date, source_amount, rate)`."""
    results = []
    for date, amount, rate in daily_amounts_and_rates:
        if not isinstance(amount, Decimal) or not isinstance(rate, Decimal):
            raise ValueError("convert_daily_spend requires Decimal amount and rate.")
        if rate <= 0:
            raise ValueError(
                f"convert_daily_spend: rate for {date!r} must be positive."
            )
        results.append(
            DailyConversionResult(
                date=date,
                source_amount=amount,
                rate=rate,
                converted_amount=amount * rate,
            )
        )
    return results


@dataclass(frozen=True)
class WeeklyAverageConversionResult:
    """Requirement 3: a weekly arithmetic-average conversion, retaining
    the observation count and missing-day status alongside the converted
    value - an explicit uniform-within-week assumption, never treated as
    equivalent to a true daily conversion."""

    week: str
    source_amount: Decimal
    average_rate: Decimal
    converted_amount: Decimal
    observations_used: int
    expected_business_days: int
    method: str = CONVERSION_METHOD_BUSINESS_DAY_WEEKLY_AVERAGE

    @property
    def is_shortfall(self) -> bool:
        return self.observations_used < self.expected_business_days

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key in ("source_amount", "average_rate", "converted_amount"):
            payload[key] = str(payload[key])
        payload["is_shortfall"] = self.is_shortfall
        return payload


def convert_weekly_average(
    week: str,
    source_amount: Decimal,
    business_day_rates: Sequence[Decimal],
    expected_business_days: int,
    *,
    approved_minimum_observations: Optional[int] = None,
) -> WeeklyAverageConversionResult:
    """Requirement 3/5: arithmetic mean of available business-day rates
    for one week's total spend. `approved_minimum_observations` is
    CALLER-SUPPLIED - this function invents no default threshold (per
    Requirement 5: "the number of available observations must be checked
    against an approved minimum, and a shortfall must block or warn
    rather than proceed silently"). Raises if `approved_minimum_
    observations` is supplied and not met - the caller decides whether
    that should be a hard block or a downgraded-but-visible warning by
    catching or not catching this exception; this function itself never
    silently proceeds past a supplied threshold."""
    if not business_day_rates:
        raise ValueError("convert_weekly_average requires at least one observed rate.")
    if any(rate <= 0 for rate in business_day_rates):
        raise ValueError("convert_weekly_average: all rates must be positive.")
    observations_used = len(business_day_rates)
    if (
        approved_minimum_observations is not None
        and observations_used < approved_minimum_observations
    ):
        raise ValueError(
            f"convert_weekly_average: only {observations_used} business-day "
            f"observation(s) available for week {week!r}, below the "
            f"approved minimum of {approved_minimum_observations} - this "
            "shortfall must block or warn, never proceed silently."
        )
    average_rate = sum(business_day_rates, start=Decimal("0")) / observations_used
    return WeeklyAverageConversionResult(
        week=week,
        source_amount=source_amount,
        average_rate=average_rate,
        converted_amount=source_amount * average_rate,
        observations_used=observations_used,
        expected_business_days=expected_business_days,
    )


@dataclass(frozen=True)
class SpendWeightedWeeklyConversionResult:
    """Requirement 4: `sum(daily source spend x daily FX rate)`, with the
    implied effective weekly rate always derivable and auditable."""

    week: str
    total_source_amount: Decimal
    total_converted_amount: Decimal
    method: str = CONVERSION_METHOD_DAILY_SPEND_WEIGHTED_WEEKLY_AVERAGE

    @property
    def effective_weekly_rate(self) -> Decimal:
        """`weekly converted spend / weekly source spend` - the implied
        rate this method's own preference over a naive weekly average
        avoids masking, per Requirement 4's own "must remain derivable
        and auditable" text."""
        if self.total_source_amount == 0:
            raise ValueError(
                "effective_weekly_rate is undefined when total_source_amount is 0."
            )
        return self.total_converted_amount / self.total_source_amount

    def to_dict(self) -> dict:
        return {
            "week": self.week,
            "total_source_amount": str(self.total_source_amount),
            "total_converted_amount": str(self.total_converted_amount),
            "method": self.method,
        }


def convert_spend_weighted_weekly(
    week: str, daily_amounts_and_rates: Sequence[Tuple[Decimal, Decimal]]
) -> SpendWeightedWeeklyConversionResult:
    """Requirement 4: preferred method when both daily spend and daily
    rates are available - `sum(daily spend x daily rate)` directly,
    rather than applying one unweighted weekly-average rate to a weekly
    total."""
    if not daily_amounts_and_rates:
        raise ValueError(
            "convert_spend_weighted_weekly requires at least one (amount, rate) pair."
        )
    total_source = sum(
        (amount for amount, _ in daily_amounts_and_rates), start=Decimal("0")
    )
    total_converted = sum(
        (amount * rate for amount, rate in daily_amounts_and_rates), start=Decimal("0")
    )
    return SpendWeightedWeeklyConversionResult(
        week=week,
        total_source_amount=total_source,
        total_converted_amount=total_converted,
    )


@dataclass(frozen=True)
class PreviousBusinessDayFallbackResult:
    """Requirement 5: the latest available previous-business-day rate
    for a non-trading-day transaction date, retaining the actual source
    observation date used."""

    transaction_date: str
    source_observation_date: str
    rate: Decimal
    method: str = CONVERSION_METHOD_PREVIOUS_BUSINESS_DAY

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["rate"] = str(payload["rate"])
        return payload


def apply_previous_business_day_fallback(
    transaction_date: str,
    available_rate_dates_descending: Sequence[Tuple[str, Decimal]],
) -> PreviousBusinessDayFallbackResult:
    """`available_rate_dates_descending` must be `(date, rate)` pairs, in
    descending date order, all on or before `transaction_date` - the
    first entry strictly on or before `transaction_date` is used."""
    if not available_rate_dates_descending:
        raise ValueError(
            "apply_previous_business_day_fallback requires at least one "
            "candidate rate date."
        )
    for date, rate in available_rate_dates_descending:
        if date <= transaction_date:
            return PreviousBusinessDayFallbackResult(
                transaction_date=transaction_date,
                source_observation_date=date,
                rate=rate,
            )
    raise ValueError(
        f"apply_previous_business_day_fallback: no available rate on or "
        f"before {transaction_date!r}."
    )


@dataclass(frozen=True)
class FinanceConstantDollarAnnualResult:
    """Decision 13's own default method: one Finance-supplied annual
    rate applied uniformly across every week of its financial year - no
    observation-count/business-day-fallback logic applies (this
    record's Requirement 5 does not apply to this method)."""

    financial_year: str
    week: str
    source_amount: Decimal
    annual_rate: Decimal
    converted_amount: Decimal
    method: str = CONVERSION_METHOD_FINANCE_CONSTANT_DOLLAR_ANNUAL

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key in ("source_amount", "annual_rate", "converted_amount"):
            payload[key] = str(payload[key])
        return payload


def apply_finance_constant_dollar_annual(
    financial_year: str, week: str, source_amount: Decimal, annual_rate: Decimal
) -> FinanceConstantDollarAnnualResult:
    """Apply one Finance-supplied `annual_rate` (a `core.fx_rates.
    FXRateRecord` with `frequency='annual'`) uniformly to `week`, within
    `financial_year`. `annual_rate` is never invented by this function -
    it must be supplied by the caller from an approved
    `finance_constant_dollar_annual`-tagged rate record."""
    if annual_rate <= 0:
        raise ValueError(
            "apply_finance_constant_dollar_annual: annual_rate must be positive."
        )
    return FinanceConstantDollarAnnualResult(
        financial_year=financial_year,
        week=week,
        source_amount=source_amount,
        annual_rate=annual_rate,
        converted_amount=source_amount * annual_rate,
    )
