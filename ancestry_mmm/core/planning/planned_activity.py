"""Structured planned-activity and promotion-period future inputs
(`REQ-PLANACT-001`; Decision 14 of the "Post-UI/UX Implementation
Instructions: Approved Business Decisions" brief).

See `docs/planned_activity_and_promotion_inputs_decision_record.md` for
the full decision record. Summary:

`REQ-FUTURE-001`'s 2026-08-30 addendum records Decision 14's approved
principle: the analyst should not have to manually supply an assumption
the model, a governed default, Finance data, or an approved forecast
method can already provide (demand, seasonality, baseline growth, FX,
individual future prices) - but the analyst *should* continue to supply
"planned marketing activity, promotion periods, and explicit governed
overrides."

Repository audit (this record's own decision record) confirmed: ordinary
spend-by-week planning (`core.optimization`'s spend plan / `pages/08_
Scenario_Planner.py`'s manual tab) already *is* the analyst's structured
input for planned marketing activity - no new mechanism is needed there.
Promotion periods have no structured input at all: `core.planning.
future_context.build_future_context`'s `promo_future` parameter already
exists and is already always analyst-supplied, never given the
`hold_last_observed` relaxation available to exogenous controls - but it
is a raw `{outcome_id: {week_label: value}}` mapping, meaning today an
analyst wanting to declare "a promotion runs from week X to week Y" must
manually construct a per-week value for every week in the array by hand.

This module is the missing structured input: `PromotionPeriod` lets an
analyst declare a promotion's start/end week and intensity once, and
`materialize_promo_future` deterministically expands one or more
declared periods into the exact `promo_future` shape `build_future_
context` already requires - real, direct wiring into existing,
production-approved code, not a parallel unused contract.
`build_future_context` itself is completely unchanged.

`PlannedActivity` is a lightweight, disclosure-only record of a scheduled
future campaign's timing and label - it does not introduce a new
regressor or fitted mechanism. A planned activity's actual effect on a
plan is already carried entirely by the existing spend-by-week plan (the
mechanism REQ-ACTIVITY-001/spend planning already provides); this record
exists so a scenario's audit trail can show *which* named activity a
given week's spend increase corresponds to, never inferred from spend
values or channel names alone.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Tuple

PLANNED_ACTIVITY_INPUT_VERSION = "planned-activity-input-v1"

OVERLAP_POLICY_SUM = "sum"
OVERLAP_POLICY_MAX = "max"
OVERLAP_POLICY_REJECT = "reject_overlap"

OVERLAP_POLICIES = (OVERLAP_POLICY_SUM, OVERLAP_POLICY_MAX, OVERLAP_POLICY_REJECT)


def _validate_week_range(start_week: str, end_week: str, *, label: str) -> None:
    if not start_week or not end_week:
        raise ValueError(f"{label}: start_week and end_week are required")
    if start_week > end_week:
        raise ValueError(
            f"{label}: start_week ({start_week!r}) must be on or before "
            f"end_week ({end_week!r}) - week labels are compared lexically, "
            "matching core.planning.future_context's own sortable week-label "
            "convention (e.g. ISO calendar dates)"
        )


@dataclass(frozen=True)
class PromotionPeriod:
    """One governed, analyst-supplied future promotion window for one
    outcome. `intensity` is the promo regressor's value for every week
    inside `[start_week, end_week]` - same unit/scale as the historical
    promo column this outcome was fit with; this class does not rescale
    or interpret it."""

    promotion_id: str
    outcome_id: str
    start_week: str
    end_week: str
    intensity: float
    label: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.promotion_id:
            raise ValueError("PromotionPeriod requires a promotion_id")
        if not self.outcome_id:
            raise ValueError("PromotionPeriod requires an outcome_id")
        _validate_week_range(
            self.start_week,
            self.end_week,
            label=f"PromotionPeriod {self.promotion_id!r}",
        )
        if not math.isfinite(self.intensity):
            raise ValueError(
                f"PromotionPeriod {self.promotion_id!r}: intensity must be finite"
            )

    def weeks(self, all_weeks: Sequence[str]) -> Tuple[str, ...]:
        return tuple(w for w in all_weeks if self.start_week <= w <= self.end_week)

    def to_dict(self) -> dict:
        return {
            "promotion_id": self.promotion_id,
            "outcome_id": self.outcome_id,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "intensity": self.intensity,
            "label": self.label,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "PromotionPeriod":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in values.items() if k in known})


@dataclass(frozen=True)
class PlannedActivity:
    """A disclosure-only record of one scheduled future marketing
    activity's timing and label - never a new regressor. The activity's
    actual effect on a plan is carried entirely by the existing spend-by-
    week plan; this class documents *which* named activity a spend
    increase corresponds to, for audit purposes only."""

    activity_id: str
    channel: str
    start_week: str
    end_week: str
    label: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.activity_id:
            raise ValueError("PlannedActivity requires an activity_id")
        if not self.channel:
            raise ValueError("PlannedActivity requires a channel")
        _validate_week_range(
            self.start_week,
            self.end_week,
            label=f"PlannedActivity {self.activity_id!r}",
        )

    def to_dict(self) -> dict:
        return {
            "activity_id": self.activity_id,
            "channel": self.channel,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "label": self.label,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "PlannedActivity":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in values.items() if k in known})


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_hex(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlannedActivityAndPromotionInputs:
    """A governed, versioned bundle of one plan window's analyst-supplied
    planned-activity and promotion-period declarations - the identified
    object a Scenario Planner UI or a `core.planning.future_assumption_
    bundle.FutureAssumptionBundle` integration could reference by
    fingerprint. Deliberately does not import or modify
    `future_assumption_bundle` itself (additive, standalone, per this
    project's established Phase C/D/E discipline)."""

    promotion_periods: Tuple[PromotionPeriod, ...] = ()
    planned_activities: Tuple[PlannedActivity, ...] = ()
    version: str = PLANNED_ACTIVITY_INPUT_VERSION

    def __post_init__(self) -> None:
        promo_ids = [p.promotion_id for p in self.promotion_periods]
        if len(promo_ids) != len(set(promo_ids)):
            raise ValueError(
                "PlannedActivityAndPromotionInputs: duplicate promotion_id(s)"
            )
        activity_ids = [a.activity_id for a in self.planned_activities]
        if len(activity_ids) != len(set(activity_ids)):
            raise ValueError(
                "PlannedActivityAndPromotionInputs: duplicate activity_id(s)"
            )

    def to_dict(self) -> dict:
        return {
            "promotion_periods": [p.to_dict() for p in self.promotion_periods],
            "planned_activities": [a.to_dict() for a in self.planned_activities],
            "version": self.version,
        }

    @classmethod
    def from_dict(
        cls, values: Mapping[str, Any]
    ) -> "PlannedActivityAndPromotionInputs":
        return cls(
            promotion_periods=tuple(
                PromotionPeriod.from_dict(p)
                for p in values.get("promotion_periods", [])
            ),
            planned_activities=tuple(
                PlannedActivity.from_dict(a)
                for a in values.get("planned_activities", [])
            ),
        )

    def fingerprint(self) -> str:
        return _sha256_hex(self.to_dict())


def materialize_promo_future(
    promotion_periods: Sequence[PromotionPeriod],
    *,
    outcome_ids: Sequence[str],
    weeks: Sequence[str],
    overlap_policy: str = OVERLAP_POLICY_SUM,
) -> Dict[str, Dict[str, float]]:
    """Deterministically materialise structured `PromotionPeriod`
    declarations into the exact `promo_future` shape `core.planning.
    future_context.build_future_context` requires
    (`{outcome_id: {week_label: value}}`). Every `(outcome_id, week)` not
    covered by any promotion defaults to `0.0` - never a hold-last-
    observed relaxation, matching `build_future_context`'s own existing
    "promo never gets the hold-last-observed relaxation" rule.

    `overlap_policy` governs what happens when two or more promotion
    periods cover the same `(outcome_id, week)`: `"sum"` (default) adds
    their intensities; `"max"` takes the largest; `"reject_overlap"`
    raises rather than silently combining them. This is a disclosed
    implementation default, not an invented business rule - a caller
    wanting different overlap semantics passes a different policy.
    """
    if overlap_policy not in OVERLAP_POLICIES:
        raise ValueError(
            f"materialize_promo_future: overlap_policy must be one of {OVERLAP_POLICIES}, "
            f"got {overlap_policy!r}"
        )
    outcome_id_set = set(outcome_ids)
    result: Dict[str, Dict[str, float]] = {
        oid: {w: 0.0 for w in weeks} for oid in outcome_ids
    }
    contributions: Dict[Tuple[str, str], List[float]] = {}

    for period in promotion_periods:
        if period.outcome_id not in outcome_id_set:
            raise ValueError(
                f"PromotionPeriod {period.promotion_id!r} targets outcome_id "
                f"{period.outcome_id!r}, which is not in outcome_ids"
            )
        covered_weeks = period.weeks(weeks)
        if not covered_weeks:
            continue
        for w in covered_weeks:
            contributions.setdefault((period.outcome_id, w), []).append(
                period.intensity
            )

    for (outcome_id, week), values in contributions.items():
        if overlap_policy == OVERLAP_POLICY_REJECT and len(values) > 1:
            raise ValueError(
                f"materialize_promo_future: multiple promotion periods overlap at "
                f"outcome_id={outcome_id!r} week={week!r} and overlap_policy="
                f"{OVERLAP_POLICY_REJECT!r}"
            )
        if overlap_policy == OVERLAP_POLICY_MAX:
            result[outcome_id][week] = max(values)
        else:
            result[outcome_id][week] = float(sum(values))

    return result
