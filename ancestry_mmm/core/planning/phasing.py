"""
Monthly-to-weekly phasing contract (REQ-SCEN-002, WP1 of `Media-Mix-Lab:
Coding LLM Next Steps Post WP5`).

The business-facing plan is monthly; `core.sequential_simulation.WeeklyPlan`
requires an explicit weekly media plan and deliberately never decides how a
coarser plan spreads across weeks itself (see that module's docstring).
This module is the bridge: it turns a monthly total into a governed weekly
allocation, with an approved default method (`calendar_day_overlap_v1`), an
explicit-override escape hatch, and strict-tolerance conservation.

This module is framework-independent (no Streamlit import) and UI-mode
agnostic - the "official planning must explicitly record and confirm the
phasing method" / "exploratory planning may preselect but must keep it
visible and editable" distinction (REQ-SCEN-002) is an application-layer
governance concern for the caller (the not-yet-built Scenario Planner
integration, WP2) to enforce using the `MethodProvenance` this module
already returns - this module does not itself gate on a governance mode.

Deliberately out of scope for this module (see REQ-SCEN-002's own "Not yet
covered" boundary and the module's own README-equivalent, this docstring):
promotions/events/controls/trend/Fourier future-context generation (a
separate future-context builder, not yet implemented); any Streamlit page
or `application/` service wiring.

`calendar_day_overlap_v1` is a distinct, separately-governed method from
`core.frequency_conversion`'s `calendar_overlap_allocation` (mixed-frequency
*source-data* conversion, REQ-COVERAGE-001) - same day-overlap allocation
principle, deliberately not the same function or method ID, because a
forward-looking business plan and a backward-looking source-data conversion
are governed by different requirement records with different scopes. This
module mirrors that function's inclusive day-counting convention
(`(overlap_end - overlap_start).days + 1`, 7-day weeks) so the two stay
numerically consistent without being the same code path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ancestry_mmm.core.frequency_alignment import CanonicalCalendar
from ancestry_mmm.core.media_costs import CostMappingRegistry

PHASING_METHOD_ID = "calendar_day_overlap_v1"
PHASING_METHOD_VERSION = 1
EXPLICIT_OVERRIDE_METHOD_ID = "explicit_weekly_schedule"

# Matches core.frequency_conversion._calendar_overlap_allocation's own
# reconciliation tolerance exactly - the two methods must agree on what
# "reconciles" means even though they are separately governed.
RECONCILIATION_RTOL = 1e-10
RECONCILIATION_ATOL = 1e-10


class PhasingReconciliationError(Exception):
    """Raised when an allocation - the governed method's own output, or an
    analyst-supplied explicit weekly override - does not reconcile to its
    source monthly total within numerical tolerance. Never silently
    normalised (REQ-SCEN-002: "block rather than normalising silently")."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_hex(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _month_bounds(month: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """`month` is `"YYYY-MM"`. Returns the month's inclusive
    (first day, last day) as Timestamps - correctly handles a leap-year
    February via `pandas`' own calendar arithmetic."""
    try:
        start = pd.Timestamp(f"{month}-01")
    except ValueError as exc:
        raise ValueError(f"month must be 'YYYY-MM', got {month!r}") from exc
    if len(month) != 7 or month[4] != "-":
        raise ValueError(f"month must be 'YYYY-MM', got {month!r}")
    end = start + pd.offsets.MonthEnd(0)
    return start, end


def _week_bounds(week_start_label: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(week_start_label)
    return start, start + pd.Timedelta(days=6)


def canonical_weeks(calendar: CanonicalCalendar) -> Tuple[str, ...]:
    """The canonical model weeks (ISO week-start date strings) covering
    `calendar`'s window, at 7-day cadence. Reuses the same
    `pd.date_range(freq="7D")` convention as `core.official_preparation`
    and `core.frequency_alignment` - this module does not create a
    competing calendar representation."""
    if calendar.frequency != "weekly":
        raise ValueError(
            "canonical_weeks requires a weekly canonical calendar "
            f"(frequency='weekly'), got {calendar.frequency!r}."
        )
    index = pd.date_range(start=calendar.start, end=calendar.end, freq="7D")
    return tuple(ts.strftime("%Y-%m-%d") for ts in index)


def _validate_monthly_values(monthly_values: Mapping[str, float]) -> None:
    if not monthly_values:
        raise ValueError("monthly_values must not be empty.")
    for month, value in monthly_values.items():
        _month_bounds(month)  # raises on malformed month label
        if not np.isfinite(value):
            raise ValueError(
                f"monthly_values[{month!r}] must be finite, got {value!r}."
            )
        if value < 0:
            raise ValueError(
                f"monthly_values[{month!r}] is negative ({value!r}) - a monthly "
                "spend or model-input quantity plan must be non-negative."
            )


def _validate_weekly_schedule(
    weekly_schedule: Mapping[str, float], canonical: Tuple[str, ...]
) -> None:
    """Guard an analyst-supplied explicit weekly schedule before it is used
    (brief §8.4/§5.10): every key must be a canonical target week - a
    weekly value keyed by a label outside the canonical calendar (a typo,
    a stale label from a resized calendar, a non-canonical date format)
    must never be silently ignored by falling through
    `weekly_schedule.get(label, 0.0)`'s per-canonical-week lookup. Every
    value must be finite and non-negative - this module is scoped to flow
    quantities/spend only (REQ-SCEN-002's own "excluded from this phasing
    method" boundary excludes promotions/controls/caps, which may
    legitimately need other signs elsewhere)."""
    canonical_set = set(canonical)
    unknown = sorted(set(weekly_schedule) - canonical_set)
    if unknown:
        raise ValueError(
            "weekly_schedule contains key(s) outside the canonical calendar "
            f"weeks and cannot be silently ignored: {unknown!r}. Every "
            "supplied key must be a canonical target week "
            f"({canonical[0]!r}..{canonical[-1]!r})."
        )
    for label, value in weekly_schedule.items():
        if not np.isfinite(value):
            raise ValueError(
                f"weekly_schedule[{label!r}] must be finite, got {value!r}."
            )
        if value < 0:
            raise ValueError(
                f"weekly_schedule[{label!r}] is negative ({value!r}) - an "
                "explicit weekly spend/model-input schedule must be "
                "non-negative."
            )


@dataclass(frozen=True)
class MethodProvenance:
    """Stored provenance for a governed phasing allocation (REQ-SCEN-002:
    "Store: method ID; method version; parameters; canonical calendar
    identity; source monthly plan fingerprint; generated weekly-plan
    fingerprint.")."""

    method_id: str
    method_version: int
    parameters: Dict[str, Any] = field(default_factory=dict)
    canonical_calendar_start: str = ""
    canonical_calendar_end: str = ""
    source_monthly_plan_fingerprint: str = ""
    generated_weekly_plan_fingerprint: str = ""

    def to_dict(self) -> dict:
        return {
            "method_id": self.method_id,
            "method_version": self.method_version,
            "parameters": dict(self.parameters),
            "canonical_calendar_start": self.canonical_calendar_start,
            "canonical_calendar_end": self.canonical_calendar_end,
            "source_monthly_plan_fingerprint": self.source_monthly_plan_fingerprint,
            "generated_weekly_plan_fingerprint": self.generated_weekly_plan_fingerprint,
        }


@dataclass(frozen=True)
class MonthReconciliation:
    """Auditable evidence that one source month's allocation conserves
    exactly - "a boundary week that receives allocations from two months
    remains auditable" (REQ-SCEN-002)."""

    month: str
    source_value: float
    allocated_total: float
    within_tolerance: bool
    weeks: Tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "source_value": self.source_value,
            "allocated_total": self.allocated_total,
            "within_tolerance": self.within_tolerance,
            "weeks": list(self.weeks),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "MonthReconciliation":
        return cls(
            month=values["month"],
            source_value=values["source_value"],
            allocated_total=values["allocated_total"],
            within_tolerance=values["within_tolerance"],
            weeks=tuple(values["weeks"]),
        )


@dataclass(frozen=True)
class WeeklyAllocationResult:
    """One market/series (activity or channel id, caller's choice) weekly
    allocation, with full provenance and per-month reconciliation
    evidence."""

    market: str
    series_id: str
    period_labels: Tuple[str, ...]
    values: Tuple[float, ...]
    provenance: MethodProvenance
    reconciliation: Tuple[MonthReconciliation, ...]

    def __post_init__(self) -> None:
        if len(self.period_labels) != len(self.values):
            raise ValueError(
                "period_labels and values must have the same length "
                f"({len(self.period_labels)} != {len(self.values)})."
            )
        # Defensive - not just a guard on the two module functions that
        # build this dataclass, but on direct construction too (brief
        # §5.10: "WeeklyAllocationResult should also defensively reject
        # invalid values even if it is constructed directly"). This module
        # only ever represents flow-quantity/spend weekly allocations, so
        # every value must be finite and non-negative.
        for label, value in zip(self.period_labels, self.values):
            if not np.isfinite(value):
                raise ValueError(
                    f"WeeklyAllocationResult.values[{label!r}] must be finite, "
                    f"got {value!r}."
                )
            if value < 0:
                raise ValueError(
                    f"WeeklyAllocationResult.values[{label!r}] is negative "
                    f"({value!r}) - a weekly spend/model-input allocation "
                    "must be non-negative."
                )

    def as_array(self) -> np.ndarray:
        return np.asarray(self.values, dtype=float)

    def as_dict_by_week(self) -> Dict[str, float]:
        return dict(zip(self.period_labels, self.values))

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "series_id": self.series_id,
            "period_labels": list(self.period_labels),
            "values": list(self.values),
            "provenance": self.provenance.to_dict(),
            "reconciliation": [r.to_dict() for r in self.reconciliation],
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "WeeklyAllocationResult":
        return cls(
            market=values["market"],
            series_id=values["series_id"],
            period_labels=tuple(values["period_labels"]),
            values=tuple(values["values"]),
            provenance=MethodProvenance(**values["provenance"]),
            reconciliation=tuple(
                MonthReconciliation.from_dict(r) for r in values["reconciliation"]
            ),
        )


def phase_monthly_series_calendar_day_overlap_v1(
    *,
    market: str,
    series_id: str,
    monthly_values: Mapping[str, float],
    calendar: CanonicalCalendar,
) -> WeeklyAllocationResult:
    """Allocate a monthly total series to canonical weeks using the
    approved `calendar_day_overlap_v1` method (REQ-SCEN-002):

    1. identify every canonical model week overlapping the month;
    2. calculate the number of calendar days in the month/week
       intersection;
    3. allocate the monthly total proportionally to those intersection-day
       counts;
    4. weekly allocations sum back exactly to the original monthly total
       within numerical tolerance - checked per month, not merely in
       aggregate, and raised as `PhasingReconciliationError` (never
       silently accepted) if it does not.

    A week spanning two months legitimately receives allocations from
    both - never shifted wholly into one month for display convenience.
    A monthly value for a month with zero overlap against `calendar` will
    always fail reconciliation unless that value is itself zero - this is
    intentional fail-closed behaviour, not a bug: a plan value the
    calendar cannot represent must not be silently dropped.
    """
    _validate_monthly_values(monthly_values)
    weeks = canonical_weeks(calendar)
    week_bounds = {w: _week_bounds(w) for w in weeks}

    allocated: Dict[str, float] = {w: 0.0 for w in weeks}
    reconciliation = []

    for month in sorted(monthly_values):
        value = float(monthly_values[month])
        month_start, month_end = _month_bounds(month)
        source_days = (month_end - month_start).days + 1
        month_weeks = []
        allocated_total = 0.0
        for label in weeks:
            w_start, w_end = week_bounds[label]
            overlap_start = max(month_start, w_start)
            overlap_end = min(month_end, w_end)
            overlap_days = (overlap_end - overlap_start).days + 1
            if overlap_days > 0:
                amount = value * overlap_days / source_days
                allocated[label] += amount
                allocated_total += amount
                month_weeks.append(label)
        within_tolerance = bool(
            np.isclose(
                allocated_total,
                value,
                rtol=RECONCILIATION_RTOL,
                atol=RECONCILIATION_ATOL,
            )
        )
        if not within_tolerance:
            raise PhasingReconciliationError(
                f"calendar_day_overlap_v1 did not reconcile month {month!r}: "
                f"allocated {allocated_total!r} != source value {value!r} "
                f"(tolerance rtol={RECONCILIATION_RTOL}, atol={RECONCILIATION_ATOL}). "
                "The canonical calendar may not cover this month at all."
            )
        reconciliation.append(
            MonthReconciliation(
                month=month,
                source_value=value,
                allocated_total=allocated_total,
                within_tolerance=within_tolerance,
                weeks=tuple(month_weeks),
            )
        )

    values = tuple(allocated[w] for w in weeks)
    provenance = MethodProvenance(
        method_id=PHASING_METHOD_ID,
        method_version=PHASING_METHOD_VERSION,
        parameters={},
        canonical_calendar_start=calendar.start,
        canonical_calendar_end=calendar.end,
        source_monthly_plan_fingerprint=_sha256_hex(
            {m: monthly_values[m] for m in sorted(monthly_values)}
        ),
        generated_weekly_plan_fingerprint=_sha256_hex(
            {"period_labels": list(weeks), "values": list(values)}
        ),
    )
    return WeeklyAllocationResult(
        market=market,
        series_id=series_id,
        period_labels=weeks,
        values=values,
        provenance=provenance,
        reconciliation=tuple(reconciliation),
    )


def reconcile_explicit_weekly_schedule(
    *,
    monthly_values: Mapping[str, float],
    weekly_schedule: Mapping[str, float],
    calendar: CanonicalCalendar,
) -> Tuple[MonthReconciliation, ...]:
    """Validate that an analyst-supplied explicit weekly schedule
    reconciles to the monthly-total-constrained plan it overrides
    (REQ-SCEN-002's explicit-override contract) - raises
    `PhasingReconciliationError` rather than silently normalising on
    mismatch.

    A week's single explicit total has no unique split across the months
    it spans without extra information, so this function attributes a
    week's value to each *tracked* month (a month present in
    `monthly_values`) in proportion to that month's share of the week's
    day-overlap *across only the tracked months touching that week* - not
    a flat "/7". This matters: if a week overlaps one tracked month for
    only part of its 7 days (the rest falling in a month absent from
    `monthly_values`, or outside the calendar entirely), the tracked
    month still receives the *whole* explicit value for that week (weight
    1.0), matching `calendar_day_overlap_v1`'s own output exactly rather
    than under-attributing it. Only when a week is shared between two (or
    more) *tracked* months does it split proportionally between them.
    """
    _validate_monthly_values(monthly_values)
    weeks = canonical_weeks(calendar)
    _validate_weekly_schedule(weekly_schedule, weeks)
    week_bounds = {w: _week_bounds(w) for w in weeks}
    month_bounds = {month: _month_bounds(month) for month in monthly_values}

    # For each week, the day-overlap with every *tracked* month it touches.
    week_tracked_overlap: Dict[str, Dict[str, int]] = {w: {} for w in weeks}
    for month, (month_start, month_end) in month_bounds.items():
        for label in weeks:
            w_start, w_end = week_bounds[label]
            overlap_start = max(month_start, w_start)
            overlap_end = min(month_end, w_end)
            overlap_days = (overlap_end - overlap_start).days + 1
            if overlap_days > 0:
                week_tracked_overlap[label][month] = overlap_days

    reconciliation = []
    for month in sorted(monthly_values):
        value = float(monthly_values[month])
        allocated_total = 0.0
        month_weeks = []
        for label in weeks:
            overlaps = week_tracked_overlap[label]
            if month not in overlaps:
                continue
            total_tracked_days = sum(overlaps.values())
            weight = overlaps[month] / total_tracked_days
            week_value = float(weekly_schedule.get(label, 0.0))
            allocated_total += week_value * weight
            month_weeks.append(label)
        within_tolerance = bool(
            np.isclose(
                allocated_total,
                value,
                rtol=RECONCILIATION_RTOL,
                atol=RECONCILIATION_ATOL,
            )
        )
        if not within_tolerance:
            raise PhasingReconciliationError(
                f"Explicit weekly schedule does not reconcile month {month!r}: "
                f"tracked-month-weighted sum {allocated_total!r} != monthly "
                f"total {value!r} (tolerance rtol={RECONCILIATION_RTOL}, "
                f"atol={RECONCILIATION_ATOL})."
            )
        reconciliation.append(
            MonthReconciliation(
                month=month,
                source_value=value,
                allocated_total=allocated_total,
                within_tolerance=within_tolerance,
                weeks=tuple(month_weeks),
            )
        )
    return tuple(reconciliation)


def phase_monthly_series_explicit_override(
    *,
    market: str,
    series_id: str,
    monthly_values: Mapping[str, float],
    weekly_schedule: Mapping[str, float],
    calendar: CanonicalCalendar,
) -> WeeklyAllocationResult:
    """Build a `WeeklyAllocationResult` from an analyst-supplied explicit
    weekly schedule, after validating it reconciles to `monthly_values`
    (REQ-SCEN-002's explicit-override contract). Blocks - raises, does not
    silently accept - on mismatch; see `reconcile_explicit_weekly_schedule`.
    """
    reconciliation = reconcile_explicit_weekly_schedule(
        monthly_values=monthly_values,
        weekly_schedule=weekly_schedule,
        calendar=calendar,
    )
    weeks = canonical_weeks(calendar)
    values = tuple(float(weekly_schedule.get(w, 0.0)) for w in weeks)
    provenance = MethodProvenance(
        method_id=EXPLICIT_OVERRIDE_METHOD_ID,
        method_version=1,
        parameters={},
        canonical_calendar_start=calendar.start,
        canonical_calendar_end=calendar.end,
        source_monthly_plan_fingerprint=_sha256_hex(
            {m: monthly_values[m] for m in sorted(monthly_values)}
        ),
        generated_weekly_plan_fingerprint=_sha256_hex(
            {"period_labels": list(weeks), "values": list(values)}
        ),
    )
    return WeeklyAllocationResult(
        market=market,
        series_id=series_id,
        period_labels=weeks,
        values=values,
        provenance=provenance,
        reconciliation=reconciliation,
    )


def phase_model_input_plan_calendar_day_overlap_v1(
    *,
    market: str,
    channel: str,
    monthly_quantity: Mapping[str, float],
    calendar: CanonicalCalendar,
) -> WeeklyAllocationResult:
    """Model-input quantity path (REQ-SCEN-002 §"Spend-to-delivery order"):
    a monthly plan already expressed in model-input units is phased
    directly - this function never calls a cost mapping, so a caller
    cannot accidentally treat a model-input plan as monetary spend."""
    return phase_monthly_series_calendar_day_overlap_v1(
        market=market,
        series_id=channel,
        monthly_values=monthly_quantity,
        calendar=calendar,
    )


@dataclass(frozen=True)
class WeeklyModelInputDerivation:
    """The weekly model-input quantity derived from phased weekly spend via
    a governed, weekly/period-specific cost mapping - a distinct, typed
    result from `WeeklyAllocationResult` because this quantity was not
    itself phased (conservation against a monthly total is not a
    meaningful check here; the cost mapping is not required to be
    linear), only derived week-by-week from already-phased spend."""

    market: str
    channel: str
    period_labels: Tuple[str, ...]
    values: Tuple[float, ...]
    mapping_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        n = len(self.period_labels)
        if len(self.values) != n or len(self.mapping_ids) != n:
            raise ValueError(
                "period_labels, values, and mapping_ids must all have the same length."
            )

    def as_array(self) -> np.ndarray:
        return np.asarray(self.values, dtype=float)

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "channel": self.channel,
            "period_labels": list(self.period_labels),
            "values": list(self.values),
            "mapping_ids": list(self.mapping_ids),
        }


@dataclass(frozen=True)
class MonetaryPhasingResult:
    """Spend-to-delivery order (REQ-SCEN-002): monthly spend -> weekly
    spend -> governed weekly cost mapping -> weekly model-input quantity.
    `weekly_spend` and `weekly_model_input` are always separate, explicitly
    typed fields - never one generic value column ambiguously reused for
    both monetary and physical units."""

    weekly_spend: WeeklyAllocationResult
    weekly_model_input: WeeklyModelInputDerivation


def phase_monetary_plan_calendar_day_overlap_v1(
    *,
    market: str,
    channel: str,
    monthly_spend: Mapping[str, float],
    calendar: CanonicalCalendar,
    cost_registry: CostMappingRegistry,
    cost_context_id: str = "default",
) -> MonetaryPhasingResult:
    """Monetary plan path (REQ-SCEN-002 §"Spend-to-delivery order"):

    1. phase monthly spend into weekly spend (`calendar_day_overlap_v1`);
    2. apply the governed weekly/period-specific cost mapping (resolved
       per week via `cost_registry.resolve(..., as_of=week_label)`, so a
       cost mapping that changes mid-window is honoured correctly rather
       than one average cost being applied and the resulting delivery
       phased afterwards - REQ-SCEN-002 explicitly forbids that ordering);
    3. derive weekly model-input quantity/delivery.

    Raises `PhasingReconciliationError` if no governed, currently-valid
    cost mapping is resolvable for a week with non-zero phased spend -
    never silently falls back to an unapproved or expired mapping. A week
    with exactly zero phased spend (e.g. a canonical-calendar week outside
    every supplied month - `calendar` is typically the project's full,
    multi-year window, not just the months being planned) requires no
    mapping at all: converting zero spend is unambiguously zero regardless
    of cost, so that week's `mapping_id` is `""` and no lookup is
    attempted.
    """
    weekly_spend = phase_monthly_series_calendar_day_overlap_v1(
        market=market,
        series_id=channel,
        monthly_values=monthly_spend,
        calendar=calendar,
    )

    model_input_values = []
    mapping_ids = []
    for label, spend in zip(weekly_spend.period_labels, weekly_spend.values):
        if spend == 0.0:
            model_input_values.append(0.0)
            mapping_ids.append("")
            continue
        mapping = cost_registry.resolve(market, channel, cost_context_id, as_of=label)
        if mapping is None:
            raise PhasingReconciliationError(
                f"No governed, currently-valid cost mapping for market={market!r} "
                f"channel={channel!r} cost_context_id={cost_context_id!r} "
                f"as_of={label!r} - cannot derive a weekly model-input quantity "
                "from phased spend for this week."
            )
        derived = np.asarray(mapping.spend_to_media_input(spend)).reshape(-1)
        # Fail closed on a malformed/custom cost mapping rather than
        # silently discarding extra values (brief §5.11): a scalar weekly
        # spend must map to exactly one derived model-input value.
        if derived.size != 1:
            raise PhasingReconciliationError(
                f"Cost mapping {mapping.mapping_id!r} returned "
                f"{derived.size} value(s) for a single scalar weekly spend "
                f"({market=!r} {channel=!r} {label=!r} spend={spend!r}) - "
                "expected exactly one derived model-input value."
            )
        derived_value = float(derived[0])
        if not np.isfinite(derived_value):
            raise PhasingReconciliationError(
                f"Cost mapping {mapping.mapping_id!r} returned a non-finite "
                f"derived model-input value ({derived_value!r}) for "
                f"{market=!r} {channel=!r} {label=!r} spend={spend!r}."
            )
        if derived_value < 0:
            raise PhasingReconciliationError(
                f"Cost mapping {mapping.mapping_id!r} returned a negative "
                f"derived model-input value ({derived_value!r}) for "
                f"{market=!r} {channel=!r} {label=!r} spend={spend!r}."
            )
        model_input_values.append(derived_value)
        mapping_ids.append(mapping.mapping_id)

    weekly_model_input = WeeklyModelInputDerivation(
        market=market,
        channel=channel,
        period_labels=weekly_spend.period_labels,
        values=tuple(model_input_values),
        mapping_ids=tuple(mapping_ids),
    )
    return MonetaryPhasingResult(
        weekly_spend=weekly_spend, weekly_model_input=weekly_model_input
    )


def reseat_ordinal_monthly_plan_to_start_week(
    *,
    ordinal_monthly_values: Sequence[float],
    plan_start_week: pd.Timestamp,
) -> Tuple[Dict[str, float], Tuple[str, ...]]:
    """Re-key an ordered sequence of monthly plan values (the analyst's 1st
    entered month, 2nd entered month, ...) onto the real calendar months
    starting at `plan_start_week`, pro-rating only the first month for the
    partial period from `plan_start_week` to that month's end (WP0 of
    `Media-Mix-Lab: Coding LLM Next Steps After PR #267`, resolving the
    sequential-planner defect where this reseating happened only inside
    `pages/08_Scenario_Planner.py`).

    This function only performs the *reseating* (which real month each
    ordinal value now belongs to, and how much of the first one is
    covered); it does not decide whether reseating onto a start week other
    than the one the analyst's entered labels imply is itself an
    appropriate default - that is an application/UI-layer disclosure and
    consent concern (see `pages/08_Scenario_Planner.py`'s explicit
    plan-start reconciliation gate), not this module's.

    `plan_start_week` need not fall on the first of a month - the returned
    first month is pro-rated for the *remaining* days in that calendar
    month from `plan_start_week` onward. Returns `(reseated_by_month,
    sequential_months)` where `reseated_by_month` maps each real
    `"YYYY-MM"` label to its (possibly pro-rated) value, and
    `sequential_months` is the same set of labels in chronological order -
    the caller needs the ordered labels separately because `dict` key order
    is not itself a documented contract for callers outside this module.
    """
    n_months = len(ordinal_monthly_values)
    if n_months == 0:
        raise ValueError("ordinal_monthly_values must not be empty.")
    first_month_start = plan_start_week.replace(day=1)
    sequential_months = tuple(
        (first_month_start + pd.DateOffset(months=i)).strftime("%Y-%m")
        for i in range(n_months)
    )
    first_month_end = first_month_start + pd.offsets.MonthEnd(0)
    days_in_first_month = (first_month_end - first_month_start).days + 1
    covered_days_in_first_month = (first_month_end - plan_start_week).days + 1
    proration = covered_days_in_first_month / days_in_first_month

    reseated: Dict[str, float] = {}
    for i, label in enumerate(sequential_months):
        value = float(ordinal_monthly_values[i])
        reseated[label] = value * proration if i == 0 else value
    return reseated, sequential_months


def phase_monthly_series_from_partial_start_calendar_day_overlap_v1(
    *,
    market: str,
    series_id: str,
    reseated_monthly_values: Mapping[str, float],
    plan_start_week: pd.Timestamp,
    calendar: CanonicalCalendar,
) -> WeeklyAllocationResult:
    """Phase a monthly series whose first month is a partial period
    starting at `plan_start_week` (already pro-rated by
    `reseat_ordinal_monthly_plan_to_start_week`) onto canonical weeks.

    The already-pro-rated first-month value is spread only across the
    canonical weeks overlapping `[plan_start_week, first-month-end]` -
    using the same day-overlap formula `calendar_day_overlap_v1` itself
    uses, just scoped to the covered (future) portion of that month, since
    `calendar_day_overlap_v1` can only reconcile a month `calendar` fully
    covers (REQ-SCEN-002) and would otherwise silently double-shrink the
    already-pro-rated value. Every subsequent (whole) month is phased
    normally through `phase_monthly_series_calendar_day_overlap_v1`,
    unmodified. The two contributions are additive per week, never a
    choice between them, since a boundary week between the first and
    second month legitimately carries spend from both.
    """
    if not reseated_monthly_values:
        raise ValueError("reseated_monthly_values must not be empty.")
    weeks = canonical_weeks(calendar)
    week_bounds = {w: _week_bounds(w) for w in weeks}

    first_month = min(reseated_monthly_values)
    first_month_start = plan_start_week.replace(day=1)
    first_month_end = first_month_start + pd.offsets.MonthEnd(0)
    fragment_value = float(reseated_monthly_values[first_month])
    total_fragment_days = (first_month_end - plan_start_week).days + 1

    allocated: Dict[str, float] = {w: 0.0 for w in weeks}
    fragment_weeks = []
    fragment_allocated_total = 0.0
    for label in weeks:
        w_start, w_end = week_bounds[label]
        overlap_start = max(plan_start_week, w_start)
        overlap_end = min(first_month_end, w_end)
        overlap_days = (overlap_end - overlap_start).days + 1
        if overlap_days > 0:
            amount = fragment_value * overlap_days / total_fragment_days
            allocated[label] += amount
            fragment_allocated_total += amount
            fragment_weeks.append(label)

    fragment_within_tolerance = bool(
        np.isclose(
            fragment_allocated_total,
            fragment_value,
            rtol=RECONCILIATION_RTOL,
            atol=RECONCILIATION_ATOL,
        )
    )
    if not fragment_within_tolerance:
        raise PhasingReconciliationError(
            f"Partial-first-month phasing did not reconcile month {first_month!r}: "
            f"allocated {fragment_allocated_total!r} != pro-rated fragment value "
            f"{fragment_value!r} (tolerance rtol={RECONCILIATION_RTOL}, "
            f"atol={RECONCILIATION_ATOL})."
        )
    reconciliation = [
        MonthReconciliation(
            month=first_month,
            source_value=fragment_value,
            allocated_total=fragment_allocated_total,
            within_tolerance=fragment_within_tolerance,
            weeks=tuple(fragment_weeks),
        )
    ]

    rest_values = {m: v for m, v in reseated_monthly_values.items() if m != first_month}
    if rest_values:
        rest_result = phase_monthly_series_calendar_day_overlap_v1(
            market=market,
            series_id=series_id,
            monthly_values=rest_values,
            calendar=calendar,
        )
        for label, value in zip(rest_result.period_labels, rest_result.values):
            allocated[label] += value
        reconciliation.extend(rest_result.reconciliation)

    values = tuple(allocated[w] for w in weeks)
    provenance = MethodProvenance(
        method_id=PHASING_METHOD_ID,
        method_version=PHASING_METHOD_VERSION,
        parameters={"partial_first_month": first_month},
        canonical_calendar_start=calendar.start,
        canonical_calendar_end=calendar.end,
        source_monthly_plan_fingerprint=_sha256_hex(
            {m: reseated_monthly_values[m] for m in sorted(reseated_monthly_values)}
        ),
        generated_weekly_plan_fingerprint=_sha256_hex(
            {"period_labels": list(weeks), "values": list(values)}
        ),
    )
    return WeeklyAllocationResult(
        market=market,
        series_id=series_id,
        period_labels=weeks,
        values=values,
        provenance=provenance,
        reconciliation=tuple(reconciliation),
    )


def phase_monetary_plan_from_partial_start_calendar_day_overlap_v1(
    *,
    market: str,
    channel: str,
    reseated_monthly_spend: Mapping[str, float],
    plan_start_week: pd.Timestamp,
    calendar: CanonicalCalendar,
    cost_registry: CostMappingRegistry,
    cost_context_id: str = "default",
) -> MonetaryPhasingResult:
    """Monetary counterpart to
    `phase_monthly_series_from_partial_start_calendar_day_overlap_v1`,
    mirroring `phase_monetary_plan_calendar_day_overlap_v1`'s spend ->
    governed weekly cost mapping -> model-input order for a plan whose
    first month is a partial period (WP0 of `Media-Mix-Lab: Coding LLM
    Next Steps After PR #267`, resolving the sequential-planner defect
    where this per-week cost-mapping derivation was duplicated inline in
    `pages/08_Scenario_Planner.py`).

    Raises `PhasingReconciliationError` if no governed, currently-valid
    cost mapping is resolvable for a week with non-zero phased spend -
    never silently falls back to an unapproved or expired mapping, exactly
    like `phase_monetary_plan_calendar_day_overlap_v1`.
    """
    weekly_spend = phase_monthly_series_from_partial_start_calendar_day_overlap_v1(
        market=market,
        series_id=channel,
        reseated_monthly_values=reseated_monthly_spend,
        plan_start_week=plan_start_week,
        calendar=calendar,
    )

    model_input_values = []
    mapping_ids = []
    for label, spend in zip(weekly_spend.period_labels, weekly_spend.values):
        if spend == 0.0:
            model_input_values.append(0.0)
            mapping_ids.append("")
            continue
        mapping = cost_registry.resolve(market, channel, cost_context_id, as_of=label)
        if mapping is None:
            raise PhasingReconciliationError(
                f"No governed, currently-valid cost mapping for market={market!r} "
                f"channel={channel!r} cost_context_id={cost_context_id!r} "
                f"as_of={label!r} - cannot derive a weekly model-input quantity "
                "from phased spend for this week."
            )
        derived = np.asarray(mapping.spend_to_media_input(spend)).reshape(-1)
        if derived.size != 1:
            raise PhasingReconciliationError(
                f"Cost mapping {mapping.mapping_id!r} returned "
                f"{derived.size} value(s) for a single scalar weekly spend "
                f"({market=!r} {channel=!r} {label=!r} spend={spend!r}) - "
                "expected exactly one derived model-input value."
            )
        derived_value = float(derived[0])
        if not np.isfinite(derived_value):
            raise PhasingReconciliationError(
                f"Cost mapping {mapping.mapping_id!r} returned a non-finite "
                f"derived model-input value ({derived_value!r}) for "
                f"{market=!r} {channel=!r} {label=!r} spend={spend!r}."
            )
        if derived_value < 0:
            raise PhasingReconciliationError(
                f"Cost mapping {mapping.mapping_id!r} returned a negative "
                f"derived model-input value ({derived_value!r}) for "
                f"{market=!r} {channel=!r} {label=!r} spend={spend!r}."
            )
        model_input_values.append(derived_value)
        mapping_ids.append(mapping.mapping_id)

    weekly_model_input = WeeklyModelInputDerivation(
        market=market,
        channel=channel,
        period_labels=weekly_spend.period_labels,
        values=tuple(model_input_values),
        mapping_ids=tuple(mapping_ids),
    )
    return MonetaryPhasingResult(
        weekly_spend=weekly_spend, weekly_model_input=weekly_model_input
    )


@dataclass(frozen=True)
class HorizonConfiguration:
    """Typed response-horizon and terminal-continuation configuration
    (REQ-SCEN-003 / brief §7.6). The core contract must accept explicit
    values - UI presets (short: weeks 0-4, long: weeks 5-52, terminal: 52
    weeks) are convenience defaults, never a hidden constant baked into a
    calculation."""

    short_horizon_weeks: Tuple[int, int] = (0, 4)
    long_horizon_weeks: Tuple[int, int] = (5, 52)
    terminal_continuation_weeks: int = 52
    plan_horizon_weeks: Optional[int] = None

    def __post_init__(self) -> None:
        for name, bounds in (
            ("short_horizon_weeks", self.short_horizon_weeks),
            ("long_horizon_weeks", self.long_horizon_weeks),
        ):
            start, end = bounds
            if start < 0 or end < start:
                raise ValueError(
                    f"{name} must be (start, end) with 0 <= start <= end, got {bounds!r}."
                )
        if self.terminal_continuation_weeks < 0:
            raise ValueError("terminal_continuation_weeks must be non-negative.")
        if self.plan_horizon_weeks is not None and self.plan_horizon_weeks < 1:
            raise ValueError("plan_horizon_weeks, if supplied, must be at least 1.")

    def to_dict(self) -> dict:
        return {
            "short_horizon_weeks": list(self.short_horizon_weeks),
            "long_horizon_weeks": list(self.long_horizon_weeks),
            "terminal_continuation_weeks": self.terminal_continuation_weeks,
            "plan_horizon_weeks": self.plan_horizon_weeks,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "HorizonConfiguration":
        return cls(
            short_horizon_weeks=tuple(values["short_horizon_weeks"]),
            long_horizon_weeks=tuple(values["long_horizon_weeks"]),
            terminal_continuation_weeks=values["terminal_continuation_weeks"],
            plan_horizon_weeks=values.get("plan_horizon_weeks"),
        )
