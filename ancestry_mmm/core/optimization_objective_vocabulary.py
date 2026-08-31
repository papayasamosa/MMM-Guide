"""Closed optimiser objective-kind vocabulary and precondition gating
(`REQ-OPT-001` Requirement 1; Decision 16 of the "Post-UI/UX
Implementation Instructions: Approved Business Decisions" brief).

See `docs/optimizer_objective_and_constraint_vocabulary_decision_record.md`
for the full decision record. Summary:

`REQ-OPT-001` approves a closed objective-kind vocabulary
(`maximise_outcome`, `maximise_revenue`, `maximise_profit`, `maximise_roi`,
`minimise_cpa`) but explicitly defers *implementation* of the
precondition-gating logic ("do not offer an objective if the required
economic inputs are missing") as Phase E work. This module implements
that gating without touching `core.optimization`'s already-approved,
heavily tested objective-resolution machinery
(`resolve_planning_objective`, `_objective_weight`) at all:

- `maximise_outcome` and `maximise_revenue` are validated by literally
  calling the real, production-approved `core.optimization.
  resolve_planning_objective` and converting any `ValueError` it raises
  into a structured, fail-closed `ObjectiveKindResolution` - never a
  reimplementation of its validation logic, so the two can never silently
  diverge. `maximise_revenue` maps onto the existing `"expected_value"`
  objective kind: `OutcomeDefinition.value_weight`/`value_currency`
  already represent governed per-unit revenue value (FH-LTR, DNA-kit
  revenue - see `core.planning.value.ScenarioValueAssumptions`), so the
  existing expected-value precondition set (value eligibility, a value
  weight for every target, one shared currency) *is* Decision 16's
  "valid, governed value definition for every included outcome"
  (`REQ-ECON-001`'s value-join principle) - not a new, separately invented
  requirement.
- `maximise_profit` is unconditionally blocked: a repository-wide audit
  (see the decision record) confirmed no governed profit/margin/COGS
  definition exists anywhere in this codebase today. There is no valid
  economic input to compute profit from, so this module fails closed with
  an explicit reason rather than silently substituting revenue or
  disabling the check.
- `maximise_roi`/`minimise_cpa` additionally require every channel
  considered to be cost-bearing
  (`core.activities.ActivityDefinition.is_cost_bearing`) - SEO/non-paid
  activity (`economic_treatment == "response_only"`) must never be
  included in a cost-based objective as if it had paid media spend
  (Decision 7, already enforced elsewhere in this repository; reaffirmed
  here at the objective-resolution boundary). When no activity
  definitions are supplied, cost-based objectives cannot be verified safe
  and are blocked rather than assumed paid-by-default.

No production call site in `core.optimization` or
`pages/08_Scenario_Planner.py` is modified by this module - it is
additive and standalone, ready for a future UI/optimiser integration
pass, consistent with every other Phase C/D/E module built in this
project so far.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Mapping, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from .activities import ActivityDefinition
    from .hierarchical_model import FHModelMeta
    from .planning.value import PlanningObjective

OBJECTIVE_KIND_VOCABULARY_VERSION = "objective-kind-vocabulary-v1"

OBJECTIVE_KIND_MAXIMISE_OUTCOME = "maximise_outcome"
OBJECTIVE_KIND_MAXIMISE_REVENUE = "maximise_revenue"
OBJECTIVE_KIND_MAXIMISE_PROFIT = "maximise_profit"
OBJECTIVE_KIND_MAXIMISE_ROI = "maximise_roi"
OBJECTIVE_KIND_MINIMISE_CPA = "minimise_cpa"

OBJECTIVE_KINDS = (
    OBJECTIVE_KIND_MAXIMISE_OUTCOME,
    OBJECTIVE_KIND_MAXIMISE_REVENUE,
    OBJECTIVE_KIND_MAXIMISE_PROFIT,
    OBJECTIVE_KIND_MAXIMISE_ROI,
    OBJECTIVE_KIND_MINIMISE_CPA,
)

# Legacy `core.optimization.VALID_OBJECTIVES` members that resolve
# `maximise_outcome` for a specific metric - a caller must name exactly
# one, mirroring `resolve_planning_objective`'s own existing dispatch.
_MAXIMISE_OUTCOME_LEGACY_KINDS = (
    "fh_gsa",
    "fh_signups",
    "fh_net_billthrough",
    "dna_kits",
)

# Cost-based objective kinds requiring every considered channel to be
# cost-bearing (Decision 7 - SEO/non-paid exclusion).
_COST_BASED_OBJECTIVE_KINDS = (OBJECTIVE_KIND_MAXIMISE_ROI, OBJECTIVE_KIND_MINIMISE_CPA)

PROFIT_DEFINITION_MISSING_REASON = (
    "no governed profit/margin/COGS definition exists anywhere in this "
    "repository today - maximise_profit has no valid economic input to "
    "compute from and is blocked rather than silently approximated by "
    "revenue or another proxy"
)


@dataclass(frozen=True)
class ObjectiveKindResolution:
    """The result of validating one objective kind's economic-input
    precondition against a specific fitted model / activity taxonomy.

    `ready=False` always carries a non-empty, specific `reasons` list -
    never an unexplained categorical block, per this repository's
    established diagnostics-backed-warnings discipline
    (`REQ-DATASUPPORT-001` Requirement 4's same principle, applied here to
    objective gating)."""

    objective_kind: str
    ready: bool
    reasons: Tuple[str, ...] = ()
    excluded_channels: Tuple[str, ...] = ()
    resolved_planning_objective: Optional["PlanningObjective"] = None
    vocabulary_version: str = OBJECTIVE_KIND_VOCABULARY_VERSION

    def to_dict(self) -> dict:
        return {
            "objective_kind": self.objective_kind,
            "ready": self.ready,
            "reasons": list(self.reasons),
            "excluded_channels": list(self.excluded_channels),
            "resolved_planning_objective": (
                self.resolved_planning_objective.to_dict()
                if self.resolved_planning_objective is not None
                else None
            ),
            "vocabulary_version": self.vocabulary_version,
        }


def _blocked(
    objective_kind: str, *reasons: str, excluded: Sequence[str] = ()
) -> ObjectiveKindResolution:
    return ObjectiveKindResolution(
        objective_kind=objective_kind,
        ready=False,
        reasons=tuple(reasons),
        excluded_channels=tuple(excluded),
    )


def _non_cost_bearing_channels(
    activities: Optional[Sequence["ActivityDefinition"]],
) -> Optional[frozenset]:
    """Return the set of reporting `channel` values backed by at least one
    non-cost-bearing activity, or `None` when no activity taxonomy was
    supplied (meaning cost-bearing status cannot be verified at all).

    A channel is treated conservatively: if *any* activity mapped to that
    channel is not cost-bearing (e.g. a shared "Search" channel roll-up
    covering both Paid Search and SEO), the channel is excluded from a
    cost-based objective rather than assuming the paid share dominates."""

    if activities is None:
        return None
    non_cost_bearing = set()
    for activity in activities:
        if not activity.is_cost_bearing:
            non_cost_bearing.add(activity.channel)
    return frozenset(non_cost_bearing)


def resolve_objective_kind(
    objective_kind: str,
    *,
    meta: "FHModelMeta",
    operation: str = "optimisation",
    legacy_metric_kind: Optional[str] = None,
    ltv: Optional[Mapping[str, float]] = None,
    value_currency: Optional[str] = None,
    value_weights_by_outcome_id: Optional[Mapping[str, float]] = None,
    considered_channels: Optional[Sequence[str]] = None,
    activities: Optional[Sequence["ActivityDefinition"]] = None,
) -> ObjectiveKindResolution:
    """Validate `objective_kind`'s economic-input precondition and, where
    satisfied, resolve the concrete `PlanningObjective` a caller would use.

    This never silently defaults: an objective kind whose precondition is
    not met (or cannot be verified) always returns `ready=False` with an
    explicit reason, per Decision 16's "do not offer an objective if the
    required economic inputs are missing" instruction.
    """
    # Import lazily to avoid a hard import-time dependency from every
    # caller of this module on the full `core.optimization` module graph.
    from .optimization import resolve_planning_objective

    if objective_kind not in OBJECTIVE_KINDS:
        raise ValueError(
            f"objective_kind must be one of {OBJECTIVE_KINDS}, got {objective_kind!r}."
        )

    if objective_kind == OBJECTIVE_KIND_MAXIMISE_PROFIT:
        return _blocked(objective_kind, PROFIT_DEFINITION_MISSING_REASON)

    if objective_kind == OBJECTIVE_KIND_MAXIMISE_OUTCOME:
        if (
            legacy_metric_kind is None
            or legacy_metric_kind not in _MAXIMISE_OUTCOME_LEGACY_KINDS
        ):
            return _blocked(
                objective_kind,
                "maximise_outcome requires legacy_metric_kind to be one of "
                f"{_MAXIMISE_OUTCOME_LEGACY_KINDS} (which specific outcome family "
                "to maximise is not inferred)",
            )
        try:
            resolved = resolve_planning_objective(
                objective_kind=legacy_metric_kind,
                meta=meta,
                operation=operation,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            return _blocked(objective_kind, str(exc))
        return ObjectiveKindResolution(
            objective_kind=objective_kind,
            ready=True,
            resolved_planning_objective=resolved,
        )

    # maximise_revenue, maximise_roi, minimise_cpa all require the same
    # governed value/return definition as the existing expected_value
    # objective - resolved via the one real, production-approved function.
    try:
        resolved = resolve_planning_objective(
            objective_kind="expected_value",
            meta=meta,
            operation=operation,  # type: ignore[arg-type]
            ltv=ltv,
            value_currency=value_currency,
            value_weights_by_outcome_id=value_weights_by_outcome_id,
        )
    except ValueError as exc:
        return _blocked(objective_kind, str(exc))

    if objective_kind == OBJECTIVE_KIND_MAXIMISE_REVENUE:
        return ObjectiveKindResolution(
            objective_kind=objective_kind,
            ready=True,
            resolved_planning_objective=resolved,
        )

    # Cost-based objectives (maximise_roi, minimise_cpa): every considered
    # channel must be cost-bearing (Decision 7 - SEO exclusion).
    assert objective_kind in _COST_BASED_OBJECTIVE_KINDS
    if considered_channels is None:
        return _blocked(
            objective_kind,
            "cost-based objectives require considered_channels to be supplied "
            "explicitly so non-cost-bearing channels (e.g. SEO) can be excluded",
        )
    non_cost_bearing = _non_cost_bearing_channels(activities)
    if non_cost_bearing is None:
        return _blocked(
            objective_kind,
            "cost-based objectives require an activity taxonomy (activities=...) "
            "to verify every considered channel is cost-bearing - a channel's "
            "paid/non-paid status is never assumed from its name",
        )
    excluded = tuple(sorted(set(considered_channels) & non_cost_bearing))
    if excluded:
        return _blocked(
            objective_kind,
            "one or more considered channels are not cost-bearing (e.g. SEO, "
            "Decision 7) and must never be included in a cost-based objective "
            "as if they had paid media spend",
            excluded=excluded,
        )
    return ObjectiveKindResolution(
        objective_kind=objective_kind, ready=True, resolved_planning_objective=resolved
    )


def resolve_all_objective_kinds(
    *,
    meta: "FHModelMeta",
    operation: str = "optimisation",
    ltv: Optional[Mapping[str, float]] = None,
    value_currency: Optional[str] = None,
    value_weights_by_outcome_id: Optional[Mapping[str, float]] = None,
    considered_channels: Optional[Sequence[str]] = None,
    activities: Optional[Sequence["ActivityDefinition"]] = None,
    legacy_metric_kinds: Sequence[str] = _MAXIMISE_OUTCOME_LEGACY_KINDS,
) -> List[ObjectiveKindResolution]:
    """Resolve every closed objective kind at once - the menu a Scenario
    Planner/Optimiser UI would need to grey out unavailable options,
    each carrying its own explicit reason rather than a bare disabled
    control."""
    results: List[ObjectiveKindResolution] = []
    for legacy_kind in legacy_metric_kinds:
        results.append(
            resolve_objective_kind(
                OBJECTIVE_KIND_MAXIMISE_OUTCOME,
                meta=meta,
                operation=operation,
                legacy_metric_kind=legacy_kind,
            )
        )
    for kind in (
        OBJECTIVE_KIND_MAXIMISE_REVENUE,
        OBJECTIVE_KIND_MAXIMISE_PROFIT,
        OBJECTIVE_KIND_MAXIMISE_ROI,
        OBJECTIVE_KIND_MINIMISE_CPA,
    ):
        results.append(
            resolve_objective_kind(
                kind,
                meta=meta,
                operation=operation,
                ltv=ltv,
                value_currency=value_currency,
                value_weights_by_outcome_id=value_weights_by_outcome_id,
                considered_channels=considered_channels,
                activities=activities,
            )
        )
    return results
