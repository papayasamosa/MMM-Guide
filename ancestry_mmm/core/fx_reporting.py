"""FX reporting, currency-labelled economics, and year-on-year
translation decomposition (`REQ-FX-006`; Decision 13 build-out of the
"Post-UI/UX Implementation Instructions: Approved Business Decisions"
brief).

See `docs/governed_fx_contract_implementation_decision_record.md` for
the full options-considered decision record, including this module's
explicit scope boundary against the full (not-yet-existing anywhere in
this repository) eight-component year-on-year decomposition framework.
No actual exchange rate or reference-rate-set default appears anywhere
in this module, including its tests.

Summary (see the decision record for full reasoning):

1. `CURRENCY_VIEWS` (Requirement 1): the four-value currency-view
   vocabulary a monetary report must be able to render.
2. `label_currency_figure` (Requirement 2): every CPA/ROI figure must
   display its currency explicitly - fails closed when ambiguous.
3. `FxTranslationDecompositionComponent` (Requirement 4): FX translation
   as its own explicit year-on-year decomposition component, distinct
   from media-price inflation - deliberately self-contained, not wired
   into a larger decomposition framework this repository does not yet
   have.
4. `FxDependencySnapshot`/`assess_fx_staleness_triggers` (Requirement 5):
   the persisted FX-dependency identity and staleness-trigger contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional, Tuple, cast

FX_REPORTING_SCHEMA_VERSION = 1

CURRENCY_VIEW_TRANSACTION = "transaction"
CURRENCY_VIEW_MARKET_REPORTING = "market_reporting"
CURRENCY_VIEW_GROUP_REPORTING = "group_reporting"
CURRENCY_VIEW_CONSTANT_CURRENCY = "constant_currency"

CURRENCY_VIEWS = (
    CURRENCY_VIEW_TRANSACTION,
    CURRENCY_VIEW_MARKET_REPORTING,
    CURRENCY_VIEW_GROUP_REPORTING,
    CURRENCY_VIEW_CONSTANT_CURRENCY,
)


def _is_iso_currency_shaped(value: str) -> bool:
    return len(value) == 3 and value.isalpha() and value.isupper()


def label_currency_figure(
    metric_name: str,
    value: Decimal,
    currency: str,
    *,
    other_currencies_in_context: Tuple[str, ...] = (),
) -> str:
    """Requirement 2: every CPA/ROI figure must display its currency
    explicitly (e.g. "Average CPA (GBP)"). Fails closed - raises rather
    than returning an unlabelled string - when `other_currencies_in_
    context` shows more than one currency is present in the same report
    context and `currency` is empty."""
    if not _is_iso_currency_shaped(currency):
        raise ValueError(
            f"label_currency_figure requires an ISO-4217-shaped currency, "
            f"got {currency!r}."
        )
    if other_currencies_in_context and currency not in other_currencies_in_context:
        raise ValueError(
            f"label_currency_figure: currency {currency!r} is not among "
            f"other_currencies_in_context {other_currencies_in_context!r} - "
            "an unqualified or mismatched currency must never be shown "
            "when more than one currency is present in the same report "
            "context."
        )
    return f"{metric_name} ({currency}): {value}"


@dataclass(frozen=True)
class FxTranslationDecompositionComponent:
    """Requirement 4: FX translation as its own explicit year-on-year
    decomposition component, distinct from and never merged into
    media-price inflation. Deliberately self-contained (computable from
    a pair of period-level translated values and the two periods' FX
    rates alone) so a future, not-yet-built decomposition framework can
    adopt it without this record guessing that framework's own shape -
    see this module's docstring and the decision record for the explicit
    scope boundary against the other seven decomposition components this
    requirement lists alongside FX (none of which exist anywhere in this
    repository yet)."""

    period_a_label: str
    period_b_label: str
    local_currency: str
    reporting_currency: str
    period_a_rate: Decimal
    period_b_rate: Decimal
    local_amount_period_b: Decimal
    schema_version: int = FX_REPORTING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.period_a_rate <= 0 or self.period_b_rate <= 0:
            raise ValueError(
                "FxTranslationDecompositionComponent: rates must be positive."
            )

    @property
    def fx_translation_effect(self) -> Decimal:
        """The portion of period B's reporting-currency change
        attributable to FX movement alone: period B's local amount,
        translated at period A's rate versus period B's rate - isolates
        the rate movement from the underlying local-currency (operational)
        change, which this component does not itself explain."""
        at_period_a_rate = self.local_amount_period_b * self.period_a_rate
        at_period_b_rate = self.local_amount_period_b * self.period_b_rate
        return at_period_b_rate - at_period_a_rate

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key in ("period_a_rate", "period_b_rate", "local_amount_period_b"):
            payload[key] = str(payload[key])
        payload["fx_translation_effect"] = str(self.fx_translation_effect)
        return payload

    @classmethod
    def from_dict(
        cls, values: Mapping[str, Any]
    ) -> "FxTranslationDecompositionComponent":
        payload = dict(values)
        for decimal_field in (
            "period_a_rate",
            "period_b_rate",
            "local_amount_period_b",
        ):
            if decimal_field in payload:
                payload[decimal_field] = Decimal(str(payload[decimal_field]))
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in payload.items() if k in known}))


@dataclass(frozen=True)
class FxDependencySnapshot:
    """Requirement 5: the persisted FX dependency identity a model,
    curve, scenario, or report must carry."""

    historical_rate_set_id: Optional[str]
    historical_rate_set_fingerprint: Optional[str]
    market_reporting_currency: str
    group_reporting_currency: str
    model_currency: str
    future_fx_assumption_id: Optional[str] = None
    future_fx_assumption_fingerprint: Optional[str] = None
    conversion_policy: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StalenessAssessment:
    """Never a bare boolean - always names which specific dependency
    change (if any) triggered staleness, per Requirement 5's own
    enumerated rules."""

    is_stale: bool
    reasons: Tuple[str, ...]

    def to_dict(self) -> dict:
        return {"is_stale": self.is_stale, "reasons": list(self.reasons)}


def assess_fx_staleness_triggers(
    previous: FxDependencySnapshot,
    current: FxDependencySnapshot,
    *,
    reporting_currency_selection_changed: bool = False,
) -> StalenessAssessment:
    """Requirement 5's staleness rules: a changed historical rate set
    stales the prepared data/model/curve/scenario/report; a changed
    future FX assumption stales scenario/recommendation economics; a
    changed conversion policy stales every dependent calculation; a
    changed reporting-currency SELECTION alone (passed separately, since
    it is not itself part of either snapshot's identity - it is a
    presentation choice) is never a staleness trigger by itself."""
    reasons = []
    if (
        previous.historical_rate_set_fingerprint
        != current.historical_rate_set_fingerprint
    ):
        reasons.append("historical_rate_set_changed")
    if (
        previous.future_fx_assumption_fingerprint
        != current.future_fx_assumption_fingerprint
    ):
        reasons.append("future_fx_assumption_changed")
    if previous.conversion_policy != current.conversion_policy:
        reasons.append("conversion_policy_changed")
    # reporting_currency_selection_changed is deliberately NOT checked
    # here - Requirement 5 is explicit that a presentation-only currency
    # selection change must never itself trigger staleness.
    return StalenessAssessment(is_stale=bool(reasons), reasons=tuple(reasons))
