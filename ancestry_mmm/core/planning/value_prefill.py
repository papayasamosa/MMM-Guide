"""Optional, governed, disclosed pre-fill suggestions for
`ScenarioValueAssumptions` (`REQ-FUTURE-001`; Decision 14 of the
"Post-UI/UX Implementation Instructions: Approved Business Decisions"
brief, reconciling WP2G's `REQ-ECON-003` Requirement 5).

See `docs/scenario_value_assumption_prefill_decision_record.md` for the
full options-considered decision record (why "most recent observed
rate" was chosen over a windowed average, and the scope boundary versus
`docs/wp9_future_assumption_bundle_decision_package.md`'s reserved
"future-assumption bundle" architecture question, which this module does
not touch).

Summary (see the decision record for full reasoning):

1. A suggestion is the most recent (highest-week) `WeeklyValueRate.
   value_per_unit` for a given `(valuation_kind, market, segment)` cell,
   drawn from `core.outcome_valuation_rates.derive_weekly_value_rates`'s
   already-approved historical rate-derivation output. No new
   smoothing/averaging/windowing statistical step is introduced.
2. A suggestion is never applied automatically. This module returns a
   separate, clearly-labelled `ScenarioValuePrefillSuggestion` record -
   it never constructs or mutates a `ScenarioValueAssumptions` instance
   itself. Copying a suggestion's value into an analyst's actual input
   is a future, explicit, disclosed, overridable UI action (a separate
   integration pass) - not performed by this module.
3. A `(valuation_kind, market, segment)` cell with no matching
   `WeeklyValueRate` at all produces `None` (no suggestion), never a
   fabricated `0.0` or an arbitrarily chosen fallback.
4. `WeeklyValueRate` carries no `outcome_id` of its own (its key is
   `(valuation_kind, market, week, segment)`) - this module therefore
   has no domain knowledge of which target `outcome_id` in
   `ScenarioValueAssumptions.fh_value_by_outcome_id`/`dna_value_by_
   outcome_id` a given cell's suggestion should apply to. That mapping
   is the caller's own responsibility, mirroring every other "this
   module has no domain knowledge of X" pattern already established in
   this repository.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, cast

import pandas as pd

from ..outcome_valuation_rates import WeeklyValueRate

SCENARIO_VALUE_PREFILL_SCHEMA_VERSION = 1

PREFILL_BASIS_MOST_RECENT_OBSERVED_RATE = "most_recent_observed_rate"

SCENARIO_VALUE_PREFILL_DISCLAIMER = (
    "This is a suggested value only, computed from the most recent "
    "historical rate for this cell - it is never applied automatically. "
    "The analyst must explicitly accept or override it; an unaccepted "
    "suggestion has no effect on any ScenarioValueAssumptions instance."
)


@dataclass(frozen=True)
class ScenarioValuePrefillSuggestion:
    """One suggested forward value for a `(valuation_kind, market,
    segment)` cell, sourced from `core.outcome_valuation_rates`'s
    already-approved historical rate-derivation. Deliberately carries no
    `outcome_id` - see module docstring point 4."""

    valuation_kind: str
    market: str
    segment: str
    suggested_value: float
    currency: str
    source_week: str
    basis: str = PREFILL_BASIS_MOST_RECENT_OBSERVED_RATE
    disclaimer: str = SCENARIO_VALUE_PREFILL_DISCLAIMER
    schema_version: int = SCENARIO_VALUE_PREFILL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.valuation_kind:
            raise ValueError(
                "ScenarioValuePrefillSuggestion requires a valuation_kind."
            )
        if not self.market:
            raise ValueError("ScenarioValuePrefillSuggestion requires a market.")
        if not self.segment:
            raise ValueError("ScenarioValuePrefillSuggestion requires a segment.")
        if not self.currency or len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError(
                "ScenarioValuePrefillSuggestion requires a valid three-letter "
                f"uppercase ISO currency, got {self.currency!r}."
            )
        if self.suggested_value < 0:
            raise ValueError(
                "ScenarioValuePrefillSuggestion.suggested_value cannot be "
                "negative - Finance has not approved negative value "
                "semantics (mirrors ScenarioValueAssumptions)."
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "ScenarioValuePrefillSuggestion":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


def suggest_value_prefill(
    rates: Sequence[WeeklyValueRate],
    *,
    valuation_kind: str,
    market: str,
    segment: str,
) -> Optional[ScenarioValuePrefillSuggestion]:
    """Suggest a forward value for one `(valuation_kind, market, segment)`
    cell: the most recent (highest-week) matching `WeeklyValueRate`'s
    `value_per_unit`, or `None` if no rate matches at all (P1-B/P3 of the
    decision record). A `WeeklyValueRate` marked `is_zero_denominator_
    carve_out=True` is excluded - a carve-out cell's `value_per_unit` is
    not a genuine observed rate and must not be suggested as one."""
    if not valuation_kind or not market or not segment:
        raise ValueError(
            "suggest_value_prefill requires valuation_kind, market, and segment."
        )

    matching = [
        rate
        for rate in rates
        if rate.valuation_kind == valuation_kind
        and rate.market == market
        and rate.segment == segment
        and not rate.is_zero_denominator_carve_out
    ]
    if not matching:
        return None

    latest = max(matching, key=lambda rate: pd.Timestamp(rate.week))

    return ScenarioValuePrefillSuggestion(
        valuation_kind=latest.valuation_kind,
        market=latest.market,
        segment=latest.segment,
        suggested_value=latest.value_per_unit,
        currency=latest.currency,
        source_week=latest.week,
    )


def suggest_value_prefills(
    rates: Sequence[WeeklyValueRate],
    cells: Sequence[Tuple[str, str, str]],
) -> Dict[Tuple[str, str, str], Optional[ScenarioValuePrefillSuggestion]]:
    """Apply `suggest_value_prefill` over a batch of `(valuation_kind,
    market, segment)` cells, returning `None` per entry with no matching
    data - never raising for a partially-covered batch."""
    result: Dict[Tuple[str, str, str], Optional[ScenarioValuePrefillSuggestion]] = {}
    for valuation_kind, market, segment in cells:
        result[(valuation_kind, market, segment)] = suggest_value_prefill(
            rates, valuation_kind=valuation_kind, market=market, segment=segment
        )
    return result
