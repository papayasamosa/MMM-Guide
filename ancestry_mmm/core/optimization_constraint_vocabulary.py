"""Closed, extended per-channel/per-month constraint-kind vocabulary
(`REQ-OPT-001` Requirement 2; Decision 16 of the "Post-UI/UX
Implementation Instructions: Approved Business Decisions" brief).

See `docs/optimizer_objective_and_constraint_vocabulary_decision_record.md`
for the full decision record. Summary:

`core.optimization.SpendConstraint` already implements five kinds
(`locked_cell`, `channel_total`, `month_total`, `bounded_movement`,
`min_spend_floor`). Decision 16 names five more (`maximum_spend`,
`spend_range`, `absolute_change_from_reference`, `zero_spend`,
`required_minimum_activity`) plus an explicit `no_constraint`/
`unavailable` pair. `REQ-OPT-001` itself leaves open "whether each new
kind is implemented as a new `SpendConstraint` variant or a parallel
structure," calling it Phase E implementation work, not a business
decision.

This module chooses the **parallel structure** (`GovernedSpendConstraint`),
for the same reason every other Phase C/D/E module in this project has
chosen additive-and-standalone over touching an existing, heavily tested
governance-critical function: `core.optimization.build_bounds_and_
constraints` is unmodified, zero regression surface, and every existing
`SpendConstraint`/optimiser test continues to exercise exactly the same
code it always has.

Governed kinds with a direct, exact existing equivalent
(`fixed_absolute_spend`, `minimum_spend`, `percentage_change_from_
reference`, `zero_spend`) are translated into real `core.optimization.
SpendConstraint` instances and fed through the existing, proven
`build_bounds_and_constraints` - never reimplemented. Kinds with no
existing equivalent (`maximum_spend`, `spend_range`,
`absolute_change_from_reference`, `unavailable`) are applied as a direct
bounds-tightening pass on top of that result. `required_minimum_activity`
is a genuinely non-monetary floor (Decision 16's own text: "distinct from
a spend floor") and is never silently treated as a money bound - it is
applied only when the caller supplies an explicit, governed
`unit_to_spend_mapping`; otherwise it is disclosed as advisory-only,
never silently dropped or misapplied.

`unavailable` and `zero_spend` both numerically collapse to a forced
zero-spend bound (there is no third value a scipy bound can hold), but
this module's own governed representation and disclosure output keep
them fully distinguishable audit-visible facts throughout, per
`REQ-OPT-001` Requirement 2's explicit instruction and consistent with
`REQ-CAP-001`'s cap-hit vocabulary's identical "collapse the number,
never the disclosure" pattern.

Requirement 5 (infeasibility must be reported, never silently relaxed) is
enforced by `resolve_governed_constraints`: any cell where the resolved
lower bound exceeds the resolved upper bound is reported in
`GovernedConstraintResolution.infeasible_cells` rather than silently
clamped or dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

import numpy as np

CONSTRAINT_KIND_VOCABULARY_VERSION = "constraint-kind-vocabulary-v1"

CONSTRAINT_KIND_NO_CONSTRAINT = "no_constraint"
CONSTRAINT_KIND_FIXED_ABSOLUTE_SPEND = "fixed_absolute_spend"
CONSTRAINT_KIND_MINIMUM_SPEND = "minimum_spend"
CONSTRAINT_KIND_MAXIMUM_SPEND = "maximum_spend"
CONSTRAINT_KIND_SPEND_RANGE = "spend_range"
CONSTRAINT_KIND_PERCENTAGE_CHANGE_FROM_REFERENCE = "percentage_change_from_reference"
CONSTRAINT_KIND_ABSOLUTE_CHANGE_FROM_REFERENCE = "absolute_change_from_reference"
CONSTRAINT_KIND_ZERO_SPEND = "zero_spend"
CONSTRAINT_KIND_REQUIRED_MINIMUM_ACTIVITY = "required_minimum_activity"
CONSTRAINT_KIND_UNAVAILABLE = "unavailable"

CONSTRAINT_KINDS = (
    CONSTRAINT_KIND_NO_CONSTRAINT,
    CONSTRAINT_KIND_FIXED_ABSOLUTE_SPEND,
    CONSTRAINT_KIND_MINIMUM_SPEND,
    CONSTRAINT_KIND_MAXIMUM_SPEND,
    CONSTRAINT_KIND_SPEND_RANGE,
    CONSTRAINT_KIND_PERCENTAGE_CHANGE_FROM_REFERENCE,
    CONSTRAINT_KIND_ABSOLUTE_CHANGE_FROM_REFERENCE,
    CONSTRAINT_KIND_ZERO_SPEND,
    CONSTRAINT_KIND_REQUIRED_MINIMUM_ACTIVITY,
    CONSTRAINT_KIND_UNAVAILABLE,
)

# Kinds with a direct, exact existing `SpendConstraint` equivalent.
_LEGACY_EQUIVALENT_KINDS = frozenset(
    {
        CONSTRAINT_KIND_FIXED_ABSOLUTE_SPEND,
        CONSTRAINT_KIND_MINIMUM_SPEND,
        CONSTRAINT_KIND_PERCENTAGE_CHANGE_FROM_REFERENCE,
        CONSTRAINT_KIND_ZERO_SPEND,
    }
)

# Kinds applied as a direct bounds-tightening pass (no legacy equivalent).
_DIRECT_BOUNDS_KINDS = frozenset(
    {
        CONSTRAINT_KIND_MAXIMUM_SPEND,
        CONSTRAINT_KIND_SPEND_RANGE,
        CONSTRAINT_KIND_ABSOLUTE_CHANGE_FROM_REFERENCE,
        CONSTRAINT_KIND_UNAVAILABLE,
    }
)


@dataclass(frozen=True)
class GovernedSpendConstraint:
    """One governed, closed-vocabulary constraint cell (`REQ-OPT-001`
    Requirement 2). Exactly one `kind`; only the fields that kind requires
    may be populated - `__post_init__` rejects any other combination fail-
    closed rather than silently ignoring an irrelevant field."""

    kind: str
    channel: Optional[str] = None
    month: Optional[str] = None
    months: Optional[Tuple[str, ...]] = None
    value: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    pct_move: Optional[float] = None
    absolute_delta: Optional[float] = None
    unit_to_spend_rate: Optional[float] = None
    label: str = ""

    def __post_init__(self) -> None:
        if self.kind not in CONSTRAINT_KINDS:
            raise ValueError(
                f"GovernedSpendConstraint: unknown kind {self.kind!r}; "
                f"must be one of {CONSTRAINT_KINDS}"
            )
        if self.kind == CONSTRAINT_KIND_NO_CONSTRAINT:
            return
        if not self.channel:
            raise ValueError(
                f"GovernedSpendConstraint(kind={self.kind!r}) requires a channel"
            )
        if not self.month and not self.months:
            raise ValueError(
                f"GovernedSpendConstraint(kind={self.kind!r}) requires month or months"
            )
        if self.kind in (
            CONSTRAINT_KIND_FIXED_ABSOLUTE_SPEND,
            CONSTRAINT_KIND_MINIMUM_SPEND,
            CONSTRAINT_KIND_MAXIMUM_SPEND,
        ):
            if self.value is None or self.value < 0:
                raise ValueError(
                    f"GovernedSpendConstraint(kind={self.kind!r}) requires a non-negative value"
                )
        if self.kind == CONSTRAINT_KIND_SPEND_RANGE:
            if self.min_value is None or self.max_value is None:
                raise ValueError(
                    "GovernedSpendConstraint(kind='spend_range') requires min_value and max_value"
                )
            if self.min_value < 0 or self.max_value < 0:
                raise ValueError(
                    "GovernedSpendConstraint(kind='spend_range') values must be non-negative"
                )
            if self.min_value > self.max_value:
                raise ValueError(
                    "GovernedSpendConstraint(kind='spend_range') requires min_value <= max_value"
                )
        if self.kind == CONSTRAINT_KIND_PERCENTAGE_CHANGE_FROM_REFERENCE:
            if self.pct_move is None or self.pct_move < 0:
                raise ValueError(
                    "GovernedSpendConstraint(kind='percentage_change_from_reference') "
                    "requires a non-negative pct_move"
                )
        if self.kind == CONSTRAINT_KIND_ABSOLUTE_CHANGE_FROM_REFERENCE:
            if self.absolute_delta is None or self.absolute_delta < 0:
                raise ValueError(
                    "GovernedSpendConstraint(kind='absolute_change_from_reference') "
                    "requires a non-negative absolute_delta"
                )
        if self.kind == CONSTRAINT_KIND_REQUIRED_MINIMUM_ACTIVITY:
            if self.value is None or self.value < 0:
                raise ValueError(
                    "GovernedSpendConstraint(kind='required_minimum_activity') "
                    "requires a non-negative value (the non-monetary activity floor)"
                )
        if self.kind in (CONSTRAINT_KIND_ZERO_SPEND, CONSTRAINT_KIND_UNAVAILABLE):
            if self.value is not None:
                raise ValueError(
                    f"GovernedSpendConstraint(kind={self.kind!r}) must not carry a value "
                    "- it is a fixed fact/choice, not a numeric input"
                )

    def resolved_months(self, all_months: Sequence[str]) -> Tuple[str, ...]:
        if self.months:
            return tuple(self.months)
        if self.month:
            return (self.month,)
        return tuple(all_months)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "channel": self.channel,
            "month": self.month,
            "months": list(self.months) if self.months else None,
            "value": self.value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "pct_move": self.pct_move,
            "absolute_delta": self.absolute_delta,
            "unit_to_spend_rate": self.unit_to_spend_rate,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "GovernedSpendConstraint":
        payload = dict(values)
        if payload.get("months") is not None:
            payload["months"] = tuple(payload["months"])
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in payload.items() if k in known})


def _cell_index(
    month: str, channel: str, months: Sequence[str], channels: Sequence[str]
) -> int:
    return list(months).index(month) * len(channels) + list(channels).index(channel)


@dataclass(frozen=True)
class GovernedConstraintDisclosure:
    """What happened to one `GovernedSpendConstraint` during resolution -
    never silently absorbed into a bound with no audit trail."""

    kind: str
    channel: Optional[str]
    months: Tuple[str, ...]
    disposition: str  # "translated_to_legacy" | "applied_direct_bounds" | "advisory_only" | "skipped"
    detail: str
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "channel": self.channel,
            "months": list(self.months),
            "disposition": self.disposition,
            "detail": self.detail,
            "label": self.label,
        }


@dataclass(frozen=True)
class GovernedConstraintResolution:
    """The result of resolving a full list of `GovernedSpendConstraint`s
    into scipy-ready bounds, alongside a full disclosure of how every
    governed constraint was actually applied (Requirement 4/5)."""

    bounds: Tuple[Tuple[float, float], ...]
    legacy_constraints: Tuple[Any, ...]
    disclosures: Tuple[GovernedConstraintDisclosure, ...]
    infeasible_cells: Tuple[Tuple[str, str, float, float], ...]
    vocabulary_version: str = CONSTRAINT_KIND_VOCABULARY_VERSION

    @property
    def is_feasible(self) -> bool:
        return len(self.infeasible_cells) == 0

    def to_dict(self) -> dict:
        return {
            "bounds": [list(bound) for bound in self.bounds],
            "disclosures": [d.to_dict() for d in self.disclosures],
            "infeasible_cells": [list(cell) for cell in self.infeasible_cells],
            "is_feasible": self.is_feasible,
            "vocabulary_version": self.vocabulary_version,
        }


def resolve_governed_constraints(
    governed: Sequence[GovernedSpendConstraint],
    *,
    months: Sequence[str],
    channels: Sequence[str],
    current_spend: Sequence[float],
    default_max_pct_move: Optional[float] = None,
    resource_channels: Optional[Sequence[str]] = None,
) -> GovernedConstraintResolution:
    """Resolve a full governed constraint list into scipy-ready bounds and
    linear constraints, delegating every legacy-equivalent kind to the
    real, already-tested `core.optimization.build_bounds_and_constraints`,
    and applying every other kind as a direct bounds-tightening pass.
    """
    # Imported lazily so this module has no hard import-time dependency on
    # the full `core.optimization` module graph for callers who only need
    # the vocabulary/validation half.
    from .optimization import SpendConstraint, build_bounds_and_constraints

    months = list(months)
    channels = list(channels)
    current_spend_arr = list(float(v) for v in current_spend)
    n = len(months) * len(channels)
    if len(current_spend_arr) != n:
        raise ValueError(
            "current_spend must have one entry per (month, channel) cell, "
            f"expected {n}, got {len(current_spend_arr)}"
        )

    legacy: List[Any] = []
    disclosures: List[GovernedConstraintDisclosure] = []
    direct_kind_items: List[GovernedSpendConstraint] = []

    for gc in governed:
        resolved_months = gc.resolved_months(months)
        if gc.kind == CONSTRAINT_KIND_NO_CONSTRAINT:
            disclosures.append(
                GovernedConstraintDisclosure(
                    kind=gc.kind,
                    channel=gc.channel,
                    months=resolved_months,
                    disposition="skipped",
                    detail="no_constraint carries no numeric effect",
                    label=gc.label,
                )
            )
            continue
        if gc.kind in _LEGACY_EQUIVALENT_KINDS:
            for month in resolved_months:
                if gc.kind == CONSTRAINT_KIND_FIXED_ABSOLUTE_SPEND:
                    legacy.append(
                        SpendConstraint(
                            kind="locked_cell",
                            channel=gc.channel,
                            month=month,
                            value=gc.value,
                            label=gc.label,
                        )
                    )
                elif gc.kind == CONSTRAINT_KIND_MINIMUM_SPEND:
                    legacy.append(
                        SpendConstraint(
                            kind="min_spend_floor",
                            channel=gc.channel,
                            month=month,
                            value=gc.value,
                            label=gc.label,
                        )
                    )
                elif gc.kind == CONSTRAINT_KIND_PERCENTAGE_CHANGE_FROM_REFERENCE:
                    legacy.append(
                        SpendConstraint(
                            kind="bounded_movement",
                            channel=gc.channel,
                            month=month,
                            max_pct_move=gc.pct_move,
                            label=gc.label,
                        )
                    )
                elif gc.kind == CONSTRAINT_KIND_ZERO_SPEND:
                    legacy.append(
                        SpendConstraint(
                            kind="locked_cell",
                            channel=gc.channel,
                            month=month,
                            value=0.0,
                            label=gc.label,
                        )
                    )
            disclosures.append(
                GovernedConstraintDisclosure(
                    kind=gc.kind,
                    channel=gc.channel,
                    months=resolved_months,
                    disposition="translated_to_legacy",
                    detail=(
                        "translated to an equivalent core.optimization.SpendConstraint "
                        "and resolved by build_bounds_and_constraints"
                    ),
                    label=gc.label,
                )
            )
            continue
        if gc.kind == CONSTRAINT_KIND_REQUIRED_MINIMUM_ACTIVITY:
            if gc.unit_to_spend_rate is None:
                disclosures.append(
                    GovernedConstraintDisclosure(
                        kind=gc.kind,
                        channel=gc.channel,
                        months=resolved_months,
                        disposition="advisory_only",
                        detail=(
                            "required_minimum_activity is a non-monetary floor; no "
                            "unit_to_spend_rate was supplied, so it is disclosed but "
                            "never silently applied as a spend bound"
                        ),
                        label=gc.label,
                    )
                )
                continue
            # A governed unit -> spend rate was explicitly supplied: apply
            # as an equivalent minimum-spend floor, disclosed as such.
            direct_kind_items.append(gc)
            continue
        # maximum_spend, spend_range, absolute_change_from_reference, unavailable
        direct_kind_items.append(gc)

    bounds, linear_constraints = build_bounds_and_constraints(
        months,
        channels,
        np.asarray(current_spend_arr, dtype=float),
        legacy,
        default_max_pct_move=default_max_pct_move,
        resource_channels=list(resource_channels)
        if resource_channels is not None
        else None,
    )
    lower = [b[0] for b in bounds]
    upper = [b[1] for b in bounds]

    for gc in direct_kind_items:
        assert (
            gc.channel is not None
        )  # validated in __post_init__ for every non-no_constraint kind
        resolved_months = gc.resolved_months(months)
        for month in resolved_months:
            idx = _cell_index(month, gc.channel, months, channels)
            current = current_spend_arr[idx]
            if gc.kind == CONSTRAINT_KIND_MAXIMUM_SPEND:
                assert gc.value is not None  # validated in __post_init__
                upper[idx] = min(upper[idx], gc.value)
                detail = f"upper bound tightened to {gc.value}"
            elif gc.kind == CONSTRAINT_KIND_SPEND_RANGE:
                assert gc.min_value is not None and gc.max_value is not None
                lower[idx] = max(lower[idx], gc.min_value)
                upper[idx] = min(upper[idx], gc.max_value)
                detail = f"bound tightened to [{gc.min_value}, {gc.max_value}]"
            elif gc.kind == CONSTRAINT_KIND_ABSOLUTE_CHANGE_FROM_REFERENCE:
                assert gc.absolute_delta is not None  # validated in __post_init__
                lower[idx] = max(lower[idx], max(0.0, current - gc.absolute_delta))
                upper[idx] = min(upper[idx], current + gc.absolute_delta)
                detail = f"bound tightened to +/-{gc.absolute_delta} around reference {current}"
            elif gc.kind == CONSTRAINT_KIND_UNAVAILABLE:
                lower[idx] = 0.0
                upper[idx] = 0.0
                detail = (
                    "forced to zero spend: no available demand/activity this period "
                    "(a fact, distinct from an analyst's zero_spend choice)"
                )
            elif gc.kind == CONSTRAINT_KIND_REQUIRED_MINIMUM_ACTIVITY:
                assert gc.value is not None and gc.unit_to_spend_rate is not None
                floor = gc.value * gc.unit_to_spend_rate
                lower[idx] = max(lower[idx], floor)
                detail = (
                    f"applied as an equivalent spend floor ({floor}) via the "
                    f"caller-supplied unit_to_spend_rate={gc.unit_to_spend_rate} "
                    "- never invented by this module"
                )
            else:  # pragma: no cover - exhaustive by construction
                raise AssertionError(gc.kind)
            disclosures.append(
                GovernedConstraintDisclosure(
                    kind=gc.kind,
                    channel=gc.channel,
                    months=(month,),
                    disposition=(
                        "applied_direct_bounds"
                        if gc.kind != CONSTRAINT_KIND_REQUIRED_MINIMUM_ACTIVITY
                        else "translated_to_legacy"
                    ),
                    detail=detail,
                    label=gc.label,
                )
            )

    infeasible: List[Tuple[str, str, float, float]] = []
    for month in months:
        for channel in channels:
            idx = _cell_index(month, channel, months, channels)
            if lower[idx] > upper[idx]:
                infeasible.append((month, channel, lower[idx], upper[idx]))

    return GovernedConstraintResolution(
        bounds=tuple(zip(lower, upper)),
        legacy_constraints=tuple(linear_constraints),
        disclosures=tuple(disclosures),
        infeasible_cells=tuple(infeasible),
    )
