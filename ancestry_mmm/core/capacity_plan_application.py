"""Generalised wiring of `core.capacity.CapacityLimitDefinition` into a
candidate plan - usable by Scenario Planner, Optimiser, and Search-
specific capped contribution from one governed source (`REQ-CAP-001`'s
2026-08-30 addendum; Decision 18; `REQ-OPT-001` Requirement 4).

`core.capacity` itself (Decisions 10/18, commit `55a14078`) implements the
cap-hit vocabulary, the governed `CapacityLimitDefinition` object, and the
pathway-agnostic reconciliation identity - but nothing in this repository
yet actually *applies* a `CapacityLimitDefinition` to a candidate plan.
This module is that missing application layer:

- `classify_capacity_limit_binding` is the Scenario-Planner-facing,
  report-only half: given a limit and a candidate plan's realised value
  per period, it reuses `core.capacity.classify_cap_hit_status` (never
  reimplemented) to report each period's cap-hit status - no bounds, no
  optimisation, just disclosure.
- `apply_capacity_limits_to_bounds` is the Optimiser-facing half: for a
  money-denominated limit (`kind="spend_limit"`), it tightens the
  relevant cell's upper bound directly, in the exact same scipy
  bounds-tuple shape `core.optimization_constraint_vocabulary` and
  `core.optimization.build_bounds_and_constraints` already use, so a
  caller can freely combine capacity constraints with the money/
  percentage constraint vocabulary in the same optimisation run
  (`REQ-OPT-001` Requirement 4's explicit "both must be usable together"
  instruction).

A non-money-denominated limit (`delivery_exposure_limit`,
`availability_toggle`, `fixed_commitment`, `bounded_range`) is **never**
silently treated as a spend cap - `REQ-CAP-001`'s own standing invariant,
reaffirmed by the 2026-08-30 addendum. It is applied to spend bounds only
when the caller explicitly supplies a governed `unit_to_spend_rate` for
that limit; otherwise it is disclosed as advisory-only, never silently
dropped or misapplied.

`bounded_range`'s schema choice (this module's own implementation
decision, not a business fact): `CapacityLimitDefinition.value_by_period`
carries the range's upper value; an optional
`metadata["min_value_by_period"]` mapping (same period-keyed shape) may
supply the paired lower value. Absent that key, `bounded_range` behaves
as an upper-only limit - disclosed explicitly in the result, never
silently assumed to also have a floor.

Every disclosure in this module keeps `zero_spend`-shaped outcomes
(an availability toggle switched off, a capacity fact with no cap value)
distinguishable from an analyst's own spend choice, mirroring
`core.optimization_constraint_vocabulary`'s identical discipline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .capacity import (
    CAPACITY_LIMIT_KIND_AVAILABILITY_TOGGLE,
    CAPACITY_LIMIT_KIND_BOUNDED_RANGE,
    CAPACITY_LIMIT_KIND_DELIVERY_EXPOSURE,
    CAPACITY_LIMIT_KIND_FIXED_COMMITMENT,
    CAPACITY_LIMIT_KIND_SPEND,
    POINT_EVALUATION_ATOL,
    POINT_EVALUATION_RTOL,
    CapacityLimitDefinition,
    CapHitClassification,
    classify_cap_hit_status,
)

CAPACITY_PLAN_APPLICATION_VERSION = "capacity-plan-application-v1"

_MONEY_KINDS = frozenset({CAPACITY_LIMIT_KIND_SPEND})
_NON_MONEY_KINDS = frozenset(
    {
        CAPACITY_LIMIT_KIND_DELIVERY_EXPOSURE,
        CAPACITY_LIMIT_KIND_AVAILABILITY_TOGGLE,
        CAPACITY_LIMIT_KIND_FIXED_COMMITMENT,
        CAPACITY_LIMIT_KIND_BOUNDED_RANGE,
    }
)


@dataclass(frozen=True)
class CapacityBindingReport:
    """One (limit, period)'s cap-hit disclosure - always carrying the
    classification evidence, never a bare label."""

    limit_id: str
    period: str
    classification: CapHitClassification

    def to_dict(self) -> dict:
        return {
            "limit_id": self.limit_id,
            "period": self.period,
            "classification": self.classification.to_dict(),
        }


def classify_capacity_limit_binding(
    limit: CapacityLimitDefinition,
    realised_by_period: Mapping[str, float],
) -> List[CapacityBindingReport]:
    """Report-only: classify one limit's cap-hit status for every period it
    declares a value for, given the candidate plan's realised value
    (spend, delivery, or another unit matching the limit's own `unit`) for
    that period. Usable identically by Scenario Planner and Optimiser -
    this function performs no optimisation and mutates nothing."""
    reports = []
    for period, cap_value in limit.value_by_period.items():
        realised = realised_by_period.get(period)
        if cap_value is None:
            classification = classify_cap_hit_status(cap_value=None)
        elif realised is None:
            classification = classify_cap_hit_status(
                cap_value=cap_value, point_binding=False
            )
        else:
            point_binding = bool(
                np.isclose(
                    realised,
                    cap_value,
                    rtol=POINT_EVALUATION_RTOL,
                    atol=POINT_EVALUATION_ATOL,
                )
                or realised > cap_value
            )
            classification = classify_cap_hit_status(
                cap_value=cap_value, point_binding=point_binding
            )
        reports.append(
            CapacityBindingReport(
                limit_id=limit.limit_id, period=period, classification=classification
            )
        )
    return reports


@dataclass(frozen=True)
class CapacityBoundsDisclosure:
    """What happened to one `CapacityLimitDefinition` during bounds
    application - never silently absorbed with no audit trail."""

    limit_id: str
    kind: str
    channel: str
    period: str
    disposition: str  # "applied_direct" | "applied_via_unit_rate" | "advisory_only" | "no_limit_declared"
    detail: str

    def to_dict(self) -> dict:
        return {
            "limit_id": self.limit_id,
            "kind": self.kind,
            "channel": self.channel,
            "period": self.period,
            "disposition": self.disposition,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CapacityApplicationResult:
    bounds: Tuple[Tuple[float, float], ...]
    disclosures: Tuple[CapacityBoundsDisclosure, ...]
    binding_reports: Tuple[CapacityBindingReport, ...]
    version: str = CAPACITY_PLAN_APPLICATION_VERSION

    def to_dict(self) -> dict:
        return {
            "bounds": [list(b) for b in self.bounds],
            "disclosures": [d.to_dict() for d in self.disclosures],
            "binding_reports": [r.to_dict() for r in self.binding_reports],
            "version": self.version,
        }


def _cell_index(
    month: str, channel: str, months: Sequence[str], channels: Sequence[str]
) -> int:
    return list(months).index(month) * len(channels) + list(channels).index(channel)


def apply_capacity_limits_to_bounds(
    bounds: Sequence[Tuple[float, float]],
    *,
    months: Sequence[str],
    channels: Sequence[str],
    limits: Sequence[CapacityLimitDefinition],
    realised_by_limit_and_period: Optional[Mapping[str, Mapping[str, float]]] = None,
    unit_to_spend_rate_by_limit_id: Optional[Mapping[str, float]] = None,
) -> CapacityApplicationResult:
    """Tighten `bounds` (the same scipy bounds-tuple list `core.
    optimization.build_bounds_and_constraints`/`core.
    optimization_constraint_vocabulary.resolve_governed_constraints`
    produce) for every applicable `CapacityLimitDefinition`, and report
    each limit's binding status wherever a realised value was supplied.

    `limits.applies_to` is matched against `channels` by exact string
    equality - a market/activity-scoped limit is the caller's
    responsibility to pre-filter to the relevant channel list; this
    function does not perform market/activity resolution itself."""
    months = list(months)
    channels = list(channels)
    lower = [b[0] for b in bounds]
    upper = [b[1] for b in bounds]
    realised_by_limit_and_period = realised_by_limit_and_period or {}
    unit_to_spend_rate_by_limit_id = unit_to_spend_rate_by_limit_id or {}

    disclosures: List[CapacityBoundsDisclosure] = []
    binding_reports: List[CapacityBindingReport] = []

    for limit in limits:
        channel = limit.applies_to
        realised_for_limit = realised_by_limit_and_period.get(limit.limit_id, {})
        if realised_for_limit:
            binding_reports.extend(
                classify_capacity_limit_binding(limit, realised_for_limit)
            )

        if channel not in channels:
            # Limit does not apply to any channel in this plan - nothing to
            # tighten. Still classified above (report-only) if requested.
            continue

        unit_rate = unit_to_spend_rate_by_limit_id.get(limit.limit_id)
        min_value_by_period = dict(limit.metadata.get("min_value_by_period") or {})

        for period, cap_value in limit.value_by_period.items():
            if period not in months:
                continue
            if cap_value is None:
                disclosures.append(
                    CapacityBoundsDisclosure(
                        limit_id=limit.limit_id,
                        kind=limit.kind,
                        channel=channel,
                        period=period,
                        disposition="no_limit_declared",
                        detail="value_by_period is None for this period (unavailable, not zero)",
                    )
                )
                continue
            idx = _cell_index(period, channel, months, channels)

            if limit.kind in _MONEY_KINDS:
                upper[idx] = min(upper[idx], float(cap_value))
                disclosures.append(
                    CapacityBoundsDisclosure(
                        limit_id=limit.limit_id,
                        kind=limit.kind,
                        channel=channel,
                        period=period,
                        disposition="applied_direct",
                        detail=f"spend upper bound tightened to {cap_value}",
                    )
                )
                continue

            if limit.kind == CAPACITY_LIMIT_KIND_AVAILABILITY_TOGGLE:
                if not cap_value:
                    lower[idx] = 0.0
                    upper[idx] = 0.0
                    disclosures.append(
                        CapacityBoundsDisclosure(
                            limit_id=limit.limit_id,
                            kind=limit.kind,
                            channel=channel,
                            period=period,
                            disposition="applied_direct",
                            detail="availability toggled off for this period - forced to zero spend",
                        )
                    )
                else:
                    disclosures.append(
                        CapacityBoundsDisclosure(
                            limit_id=limit.limit_id,
                            kind=limit.kind,
                            channel=channel,
                            period=period,
                            disposition="applied_direct",
                            detail="availability toggled on - no bound tightening required",
                        )
                    )
                continue

            if limit.kind == CAPACITY_LIMIT_KIND_FIXED_COMMITMENT:
                if unit_rate is None:
                    disclosures.append(
                        CapacityBoundsDisclosure(
                            limit_id=limit.limit_id,
                            kind=limit.kind,
                            channel=channel,
                            period=period,
                            disposition="advisory_only",
                            detail=(
                                f"fixed_commitment ({cap_value} {limit.unit}) has no governed "
                                "unit_to_spend_rate supplied - never silently treated as a spend cap"
                            ),
                        )
                    )
                    continue
                fixed_spend = float(cap_value) * float(unit_rate)
                lower[idx] = upper[idx] = fixed_spend
                disclosures.append(
                    CapacityBoundsDisclosure(
                        limit_id=limit.limit_id,
                        kind=limit.kind,
                        channel=channel,
                        period=period,
                        disposition="applied_via_unit_rate",
                        detail=f"fixed spend commitment of {fixed_spend} (rate={unit_rate})",
                    )
                )
                continue

            if limit.kind in (
                CAPACITY_LIMIT_KIND_DELIVERY_EXPOSURE,
                CAPACITY_LIMIT_KIND_BOUNDED_RANGE,
            ):
                if unit_rate is None:
                    disclosures.append(
                        CapacityBoundsDisclosure(
                            limit_id=limit.limit_id,
                            kind=limit.kind,
                            channel=channel,
                            period=period,
                            disposition="advisory_only",
                            detail=(
                                f"{limit.kind} ({cap_value} {limit.unit}) has no governed "
                                "unit_to_spend_rate supplied - never silently treated as a spend cap"
                            ),
                        )
                    )
                    continue
                mapped_upper = float(cap_value) * float(unit_rate)
                upper[idx] = min(upper[idx], mapped_upper)
                detail = f"upper bound tightened to {mapped_upper} (rate={unit_rate})"
                if (
                    limit.kind == CAPACITY_LIMIT_KIND_BOUNDED_RANGE
                    and period in min_value_by_period
                ):
                    min_raw = min_value_by_period[period]
                    if min_raw is not None:
                        mapped_lower = float(min_raw) * float(unit_rate)
                        lower[idx] = max(lower[idx], mapped_lower)
                        detail += f"; lower bound tightened to {mapped_lower}"
                elif limit.kind == CAPACITY_LIMIT_KIND_BOUNDED_RANGE:
                    detail += "; no min_value_by_period supplied - upper-only"
                disclosures.append(
                    CapacityBoundsDisclosure(
                        limit_id=limit.limit_id,
                        kind=limit.kind,
                        channel=channel,
                        period=period,
                        disposition="applied_via_unit_rate",
                        detail=detail,
                    )
                )
                continue

            raise AssertionError(
                f"unhandled capacity limit kind: {limit.kind}"
            )  # pragma: no cover

    return CapacityApplicationResult(
        bounds=tuple(zip(lower, upper)),
        disclosures=tuple(disclosures),
        binding_reports=tuple(binding_reports),
    )
