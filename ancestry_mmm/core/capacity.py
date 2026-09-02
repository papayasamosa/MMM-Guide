"""Pathway-agnostic capacity and cap semantics (`REQ-CAP-001`; Decisions
10 and 18 of the "Post-UI/UX Implementation Instructions: Approved
Business Decisions" brief).

See `docs/capacity_cap_semantics_decision_record.md` for the full
options-considered decision record (PyMC documentation consulted, and
why this vocabulary/architecture was chosen). This record resolves
`docs/wp11_capacity_cap_semantics_decision_package.md`'s S1-S3 (cap-hit
status vocabulary) and G1-G3 (module-sharing timing) candidates, per the
user's explicit 2026-08-30 authorisation delegating that technical
selection.

Summary (see the decision record for full reasoning):

1. `AGENTS.md`'s four-value cap-hit vocabulary (capped / uncapped /
   ambiguous / unavailable) is implemented once here, generalised across
   any capacity-constrained pathway - never redefined per pathway
   (decision S1, extended with disclosure discipline: the classification
   is always computed from, and reported alongside, the full underlying
   probability evidence, never a lossy replacement for it).
2. `unavailable` means no governed cap value exists at all - distinct
   from a supplied, finite cap of zero (a genuine, if extreme, limit) or
   an explicit unbounded cap.
3. `ambiguous` is only reachable from posterior-draw evidence (a
   probability of binding) - a single point evaluation is definitionally
   either binding or not; there is no ambiguity without a distribution.
4. The reconciliation identity (`realised + unmet == potential`) is
   retained as the shared, pathway-agnostic conservation contract every
   capacity-constrained pathway must satisfy (decision R4) - this does
   not prescribe a specific likelihood family or link function, only
   that nothing is created or destroyed between the three quantities.
5. `CapacityLimitDefinition` is the governed, versioned, user-editable
   object shape spanning the categories Decision 18 names (spend limits,
   delivery/exposure limits, availability on/off, fixed commitments,
   minimum/maximum ranges), usable by Scenario Planner, Optimiser, and
   Search-specific capped contribution from one governed source (decision
   G1, scoped to this vocabulary/object/reconciliation layer only - NOT
   `core.graph_model_compiler`'s `capacity_constrained` structural
   validation, which remains Candidate-A-only until a second concrete
   capacity-constrained pathway actually exists to validate against).

This module does not fit or re-fit a model, does not modify `core.
search_capacity`'s existing reconciliation arithmetic, and does not
extend `core.graph_model_compiler`'s compiler-level structural
validation to a second pathway.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, List, Mapping, Optional, Sequence, Tuple, cast

import numpy as np

CAPACITY_SCHEMA_VERSION = 1

# --- Cap-hit status vocabulary (AGENTS.md's standing invariant) ------------

CAP_HIT_CAPPED = "capped"
CAP_HIT_UNCAPPED = "uncapped"
CAP_HIT_AMBIGUOUS = "ambiguous"
CAP_HIT_UNAVAILABLE = "unavailable"

CAP_HIT_STATUSES = (
    CAP_HIT_CAPPED,
    CAP_HIT_UNCAPPED,
    CAP_HIT_AMBIGUOUS,
    CAP_HIT_UNAVAILABLE,
)

# Classification-rule version, distinct from any cap VALUE's own identity/
# versioning (already provided by core.search_objects for Candidate A) -
# changing this band is a rule-version change, never a silent drift.
CAP_HIT_CLASSIFICATION_RULE_VERSION = "1.0.0"
CAP_HIT_AMBIGUITY_BAND = 0.20

# Reused verbatim from core.search_capacity.candidate_a_forward's own
# point-evaluation binding tolerance - not re-derived, to avoid two
# silently-diverging definitions of "binding" for the same underlying
# concept.
POINT_EVALUATION_RTOL = 1e-8
POINT_EVALUATION_ATOL = 1e-8

CAP_HIT_STATUS_DISCLAIMER = (
    "This status is a governed summary of the underlying binding evidence "
    "(a point evaluation, or a posterior probability of binding), never a "
    "replacement for it - the evidence that produced this status should "
    "always remain available alongside it."
)


@dataclass(frozen=True)
class CapHitClassification:
    """One period's cap-hit status (Decision S), always carrying the
    evidence it was derived from - never a bare categorical label."""

    status: str
    cap_value: Optional[float]
    probability_binding: Optional[float] = None
    point_binding: Optional[bool] = None
    rule_version: str = CAP_HIT_CLASSIFICATION_RULE_VERSION
    disclaimer: str = CAP_HIT_STATUS_DISCLAIMER

    def __post_init__(self) -> None:
        if self.status not in CAP_HIT_STATUSES:
            raise ValueError(
                f"invalid cap-hit status {self.status!r}; must be one of "
                f"{CAP_HIT_STATUSES}"
            )
        if self.status == CAP_HIT_UNAVAILABLE and self.cap_value is not None:
            raise ValueError(
                "CapHitClassification: status 'unavailable' requires "
                "cap_value=None (no governed cap value exists) - a "
                "supplied, finite cap of zero is a genuine limit, not "
                "'unavailable'."
            )
        if self.status != CAP_HIT_UNAVAILABLE and self.cap_value is None:
            raise ValueError(
                "CapHitClassification: a non-'unavailable' status requires a cap_value."
            )
        if self.probability_binding is not None and not (
            0.0 <= self.probability_binding <= 1.0
        ):
            raise ValueError(
                "CapHitClassification.probability_binding must be in [0, 1]."
            )
        if self.status == CAP_HIT_AMBIGUOUS and self.probability_binding is None:
            raise ValueError(
                "CapHitClassification: status 'ambiguous' requires "
                "probability_binding - a point evaluation is definitionally "
                "either binding or not; there is no ambiguity without a "
                "posterior distribution."
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CapHitClassification":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


def classify_cap_hit_status(
    *,
    cap_value: Optional[float],
    point_binding: Optional[bool] = None,
    probability_binding: Optional[float] = None,
) -> CapHitClassification:
    """Classify one period's cap-hit status (Decision S). Exactly one of
    `point_binding` (a single deterministic evaluation, e.g. observed
    history) or `probability_binding` (a posterior fraction of draws
    where the cap bound, e.g. `core.search_capacity.CandidateAPosteriorOutputs.
    probability_cap_binding`) must be supplied when `cap_value` is not
    `None`. `cap_value=None` always resolves `unavailable` regardless of
    other inputs - a governed cap value's absence is never inferred from
    a binding signal.
    """
    if cap_value is None:
        return CapHitClassification(status=CAP_HIT_UNAVAILABLE, cap_value=None)

    if point_binding is not None and probability_binding is not None:
        raise ValueError(
            "classify_cap_hit_status: supply exactly one of point_binding "
            "or probability_binding, not both."
        )
    if point_binding is None and probability_binding is None:
        raise ValueError(
            "classify_cap_hit_status: cap_value is present, so exactly one "
            "of point_binding or probability_binding is required."
        )

    if probability_binding is not None:
        if not (0.0 <= probability_binding <= 1.0):
            raise ValueError("probability_binding must be in [0, 1].")
        if probability_binding >= 1.0 - CAP_HIT_AMBIGUITY_BAND:
            status = CAP_HIT_CAPPED
        elif probability_binding <= CAP_HIT_AMBIGUITY_BAND:
            status = CAP_HIT_UNCAPPED
        else:
            status = CAP_HIT_AMBIGUOUS
        return CapHitClassification(
            status=status,
            cap_value=cap_value,
            probability_binding=probability_binding,
        )

    status = CAP_HIT_CAPPED if point_binding else CAP_HIT_UNCAPPED
    return CapHitClassification(
        status=status, cap_value=cap_value, point_binding=point_binding
    )


def classify_cap_hit_status_series(
    *,
    cap_values: Sequence[Optional[float]],
    point_binding: Optional[Sequence[Optional[bool]]] = None,
    probability_binding: Optional[Sequence[Optional[float]]] = None,
) -> List[CapHitClassification]:
    """Vectorised `classify_cap_hit_status` over a period series. Exactly
    one of `point_binding`/`probability_binding` must be supplied (as a
    same-length sequence); per-period entries may still be `None`
    (treated as absent for that period) only when the corresponding
    `cap_values` entry is also `None`."""
    if (point_binding is None) == (probability_binding is None):
        raise ValueError(
            "classify_cap_hit_status_series: supply exactly one of "
            "point_binding or probability_binding."
        )
    n = len(cap_values)
    source = point_binding if point_binding is not None else probability_binding
    if source is not None and len(source) != n:
        raise ValueError(
            "classify_cap_hit_status_series: cap_values and the supplied "
            "binding series must be the same length."
        )
    results = []
    for index in range(n):
        cap_value = cap_values[index]
        if point_binding is not None:
            results.append(
                classify_cap_hit_status(
                    cap_value=cap_value, point_binding=point_binding[index]
                )
            )
        else:
            assert probability_binding is not None
            results.append(
                classify_cap_hit_status(
                    cap_value=cap_value,
                    probability_binding=probability_binding[index],
                )
            )
    return results


def verify_capacity_reconciliation(
    realised: np.ndarray,
    unmet: np.ndarray,
    potential: np.ndarray,
    *,
    rtol: float = 1e-8,
    atol: float = 1e-8,
) -> None:
    """The generalised, pathway-agnostic conservation identity (decision
    R4): `realised + unmet == potential`, for every element. Raises
    `ValueError` on violation - never silently tolerates a reconciliation
    failure. This is deliberately the only structural requirement: it
    does not prescribe a specific likelihood family, censoring mechanism,
    or link function (`AGENTS.md`'s own "not one frozen algebraic form"
    caution), only that nothing is created or destroyed between the three
    quantities."""
    realised_arr = np.asarray(realised, dtype=float)
    unmet_arr = np.asarray(unmet, dtype=float)
    potential_arr = np.asarray(potential, dtype=float)
    if not (realised_arr.shape == unmet_arr.shape == potential_arr.shape):
        raise ValueError(
            "verify_capacity_reconciliation: realised, unmet, and potential "
            "must share the same shape."
        )
    if np.any(unmet_arr < -atol):
        raise ValueError("verify_capacity_reconciliation: unmet cannot be negative.")
    if not np.allclose(realised_arr + unmet_arr, potential_arr, rtol=rtol, atol=atol):
        raise ValueError(
            "verify_capacity_reconciliation: realised + unmet != potential "
            "- capacity reconciliation failed."
        )


# --- Governed capacity-limit object (Decision 18) ---------------------------

CAPACITY_LIMIT_KIND_SPEND = "spend_limit"
CAPACITY_LIMIT_KIND_DELIVERY_EXPOSURE = "delivery_exposure_limit"
CAPACITY_LIMIT_KIND_AVAILABILITY_TOGGLE = "availability_toggle"
CAPACITY_LIMIT_KIND_FIXED_COMMITMENT = "fixed_commitment"
CAPACITY_LIMIT_KIND_BOUNDED_RANGE = "bounded_range"

CAPACITY_LIMIT_KINDS = (
    CAPACITY_LIMIT_KIND_SPEND,
    CAPACITY_LIMIT_KIND_DELIVERY_EXPOSURE,
    CAPACITY_LIMIT_KIND_AVAILABILITY_TOGGLE,
    CAPACITY_LIMIT_KIND_FIXED_COMMITMENT,
    CAPACITY_LIMIT_KIND_BOUNDED_RANGE,
)


@dataclass(frozen=True)
class CapacityLimitDefinition:
    """One governed, versioned, user-editable capacity/cap limit
    (Decision 18) - usable by Scenario Planner, Optimiser, and
    Search-specific capped contribution from one governed source, never
    three independently diverging representations (`REQ-CAP-001`'s own
    2026-08-30 addendum). `limit_id`/`limit_version` is the lineage/
    version identity, mirroring `core.search_objects`'s established
    pattern exactly.

    `kind` must be one of `CAPACITY_LIMIT_KINDS`, covering at least the
    categories Decision 18 names. `unit` records the limit's own unit
    (e.g. `"GBP"`, `"impressions"`, `"bookings"`) - a non-money-
    denominated limit must never be silently treated as a spend cap
    absent a valid, governed mapping (`REQ-CAP-001` addendum); this
    class does not perform or assume such a mapping itself.
    `value_by_period` is the actual limit value per period (a governed,
    editable input, not a fitted quantity) - `None` for a period means
    no limit is declared for that period (equivalent to `unavailable`
    when classified), never an implicit zero or infinity.
    """

    limit_id: str
    limit_version: int
    kind: str
    unit: str
    applies_to: str
    value_by_period: Mapping[str, Optional[float]]
    owner: str = ""
    notes: str = ""
    schema_version: int = CAPACITY_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.limit_id:
            raise ValueError("CapacityLimitDefinition requires a limit_id.")
        if self.limit_version < 1:
            raise ValueError("CapacityLimitDefinition.limit_version must be >= 1.")
        if self.kind not in CAPACITY_LIMIT_KINDS:
            raise ValueError(
                f"CapacityLimitDefinition: unknown kind {self.kind!r} "
                f"(expected one of {CAPACITY_LIMIT_KINDS})."
            )
        if not self.unit:
            raise ValueError("CapacityLimitDefinition requires a unit.")
        if not self.applies_to:
            raise ValueError(
                "CapacityLimitDefinition requires applies_to (the governed "
                "channel/activity/market identity this limit constrains)."
            )
        for period, value in self.value_by_period.items():
            if value is not None and value < 0:
                raise ValueError(
                    f"CapacityLimitDefinition: period {period!r} has a "
                    f"negative value ({value}) - a capacity limit cannot "
                    "be negative."
                )

    def to_dict(self) -> dict:
        return {
            "limit_id": self.limit_id,
            "limit_version": self.limit_version,
            "kind": self.kind,
            "unit": self.unit,
            "applies_to": self.applies_to,
            "value_by_period": dict(self.value_by_period),
            "owner": self.owner,
            "notes": self.notes,
            "schema_version": self.schema_version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CapacityLimitDefinition":
        payload = dict(values)
        if "value_by_period" in payload:
            payload["value_by_period"] = dict(payload["value_by_period"] or {})
        if "metadata" in payload:
            payload["metadata"] = dict(payload["metadata"] or {})
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in payload.items() if k in known}))


def new_capacity_limit_version(
    definition: CapacityLimitDefinition, **changes: Any
) -> CapacityLimitDefinition:
    """Apply an edit to a governed capacity limit as a new version - never
    an in-place mutation of history. Mirrors `core.search_objects.new_
    search_object_version`/`core.experiments.new_experiment_version`
    exactly."""
    for locked_field in ("limit_id", "limit_version"):
        if locked_field in changes:
            raise ValueError(
                f"{locked_field!r} is lineage/version identity and cannot "
                "be set via new_capacity_limit_version."
            )
    from dataclasses import replace

    return replace(definition, limit_version=definition.limit_version + 1, **changes)


def current_capacity_limit_versions(
    definitions: Sequence[CapacityLimitDefinition],
) -> Tuple[CapacityLimitDefinition, ...]:
    """Resolve, per `limit_id` lineage, the current (highest
    `limit_version`) definition."""
    latest: dict = {}
    for definition in definitions:
        current = latest.get(definition.limit_id)
        if current is None or definition.limit_version > current.limit_version:
            latest[definition.limit_id] = definition
    return tuple(latest.values())
