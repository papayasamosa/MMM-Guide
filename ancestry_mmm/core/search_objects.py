"""
REQ-SEARCH-001: governed identity for the seven Search concepts a Brand
Search/Paid Search variable must never silently collapse into
branded-search demand, Paid Search spend, Paid Search delivery, a Paid
Search budget/operational cap, organic-search capture, direct-navigation
capture, and residual Paid Search incrementality.

This module governs the first six as `SearchObjectDefinition` records - a
`market x search_object_id` grained object mirroring
`core.activities.ActivityDefinition`'s shape and validation style, never a
competing one. The seventh, residual Paid Search incrementality, is not a
new object here at all: it is `core.brand_search`'s existing treatment-mode
output (`demand_capture_mediator`/`experiment_calibrated_incremental`),
computed from a `paid_search_spend` object's fitted contribution - nothing
in this module computes it a second time.

No latent-demand, capacity/censoring, cap-hit-probability, unmet-demand, or
joint media/cap optimisation mathematics live here (REQ-SEARCH-001's
explicit "out of scope" list) - this module only governs identity, unit,
scope, provenance, planning eligibility, and cross-object validation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .activities import PLANNING_ELIGIBILITY
from .causal_graph import (
    NODE_ROLE_CAPACITY_OR_CAP,
    NODE_ROLE_DEMAND_CAPTURE,
    NODE_ROLE_INTERVENTION,
)

# --- Search role vocabulary (REQ-SEARCH-001 S1) -----------------------------

SEARCH_ROLE_DEMAND = "search_demand"
SEARCH_ROLE_PAID_SPEND = "paid_search_spend"
SEARCH_ROLE_PAID_DELIVERY = "paid_search_delivery"
SEARCH_ROLE_PAID_CAP = "paid_search_cap"
SEARCH_ROLE_ORGANIC_CAPTURE = "organic_search_capture"
SEARCH_ROLE_DIRECT_NAV_CAPTURE = "direct_navigation_capture"

SEARCH_ROLES = (
    SEARCH_ROLE_DEMAND,
    SEARCH_ROLE_PAID_SPEND,
    SEARCH_ROLE_PAID_DELIVERY,
    SEARCH_ROLE_PAID_CAP,
    SEARCH_ROLE_ORGANIC_CAPTURE,
    SEARCH_ROLE_DIRECT_NAV_CAPTURE,
)

# Roles that capture existing demand rather than creating or spending on it
# (REQ-SEARCH-001 S6 "demand_capture" model role).
_DEMAND_CAPTURE_ROLES = (
    SEARCH_ROLE_DEMAND,
    SEARCH_ROLE_ORGANIC_CAPTURE,
    SEARCH_ROLE_DIRECT_NAV_CAPTURE,
)

# --- Unit vocabulary (REQ-SEARCH-001 S5) ------------------------------------

UNIT_MONETARY = "monetary"
UNIT_EXPOSURE_COUNT = "exposure_count"
UNIT_RESPONSE_COUNT = "response_count"
UNIT_INDEX = "index"

SEARCH_UNITS = (UNIT_MONETARY, UNIT_EXPOSURE_COUNT, UNIT_RESPONSE_COUNT, UNIT_INDEX)

# Which units each role may legitimately be denominated in - the structural
# half of "reject incompatible aliases" (REQ-SEARCH-001 S14): a role whose
# unit is not in this set is rejected outright, regardless of what its
# source column happens to be named.
_ALLOWED_UNITS_BY_ROLE: Dict[str, Tuple[str, ...]] = {
    SEARCH_ROLE_DEMAND: (UNIT_INDEX, UNIT_EXPOSURE_COUNT),
    SEARCH_ROLE_PAID_SPEND: (UNIT_MONETARY,),
    SEARCH_ROLE_PAID_DELIVERY: (UNIT_EXPOSURE_COUNT,),
    SEARCH_ROLE_PAID_CAP: (UNIT_MONETARY, UNIT_EXPOSURE_COUNT),
    SEARCH_ROLE_ORGANIC_CAPTURE: (UNIT_RESPONSE_COUNT,),
    SEARCH_ROLE_DIRECT_NAV_CAPTURE: (UNIT_RESPONSE_COUNT,),
}

STATE_OBSERVED = "observed"
STATE_ASSUMED = "assumed"
SEARCH_OBJECT_STATES = (STATE_OBSERVED, STATE_ASSUMED)

DEFAULT_GRAIN = "market_week"


@dataclass(frozen=True)
class SearchObjectDefinition:
    """One governed Search object at `market x search_object_id` grain -
    mirrors `core.activities.ActivityDefinition`'s shape/validation style.

    `planning_eligibility` reuses `core.activities.PLANNING_ELIGIBILITY`
    (REQ-SEARCH-001 S9): a demand-capture role or a cap may never be
    `"optimisable"` - a cap constrains `paid_search_spend`'s optimisation,
    it is never itself an optimisable target.
    """

    search_object_id: str
    search_role: str
    source_column: str
    unit: str
    market: str = "*"
    product: str = ""
    currency: str = ""
    grain: str = DEFAULT_GRAIN
    state: str = STATE_OBSERVED
    planning_eligibility: str = "excluded"
    model_input_column: str = ""
    source: str = ""
    evidence_status: str = "not_assessed"
    approval_status: str = "draft"
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    change_history: Tuple[Mapping[str, Any], ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.search_object_id or not self.source_column:
            raise ValueError("search_object_id and source_column are required")
        if not self.market:
            raise ValueError("market is required; use '*' for all markets")
        if self.search_role not in SEARCH_ROLES:
            raise ValueError(f"invalid search_role {self.search_role!r}")
        allowed_units = _ALLOWED_UNITS_BY_ROLE[self.search_role]
        if self.unit not in allowed_units:
            raise ValueError(
                f"search_role {self.search_role!r} cannot be denominated in "
                f"unit {self.unit!r} - allowed units: {allowed_units}. A "
                "monetary column is never branded-search demand, and a raw "
                "delivery/exposure column is never Paid Search spend."
            )
        if self.unit == UNIT_MONETARY and not self.currency:
            raise ValueError("currency is required when unit is 'monetary'")
        if self.unit != UNIT_MONETARY and self.currency:
            raise ValueError("currency must be blank when unit is not 'monetary'")
        if self.state not in SEARCH_OBJECT_STATES:
            raise ValueError(f"invalid state {self.state!r}")
        if self.planning_eligibility not in PLANNING_ELIGIBILITY:
            raise ValueError(
                f"invalid planning_eligibility {self.planning_eligibility!r}"
            )
        if (
            self.search_role in _DEMAND_CAPTURE_ROLES
            or self.search_role == SEARCH_ROLE_PAID_CAP
        ) and self.planning_eligibility == "optimisable":
            raise ValueError(
                f"search_role {self.search_role!r} can never be "
                "'optimisable' - it captures existing demand or constrains "
                "spend, it is not itself a spendable channel"
            )
        if self.approval_status == "approved" and (
            not self.approved_by or not self.approved_at
        ):
            raise ValueError(
                "approved search objects require approved_by and approved_at"
            )

    @property
    def search_object_key(self) -> Tuple[str, str]:
        return self.market, self.search_object_id

    def to_dict(self) -> dict:
        values = asdict(self)
        values["change_history"] = [dict(item) for item in self.change_history]
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SearchObjectDefinition":
        payload = dict(values)
        payload.setdefault("market", "*")
        payload["change_history"] = tuple(payload.get("change_history") or ())
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in payload.items() if key in known})


def graph_node_role_for_search_object(defn: SearchObjectDefinition) -> Optional[str]:
    """The `core.causal_graph` node role this object seeds when added to a
    causal graph (REQ-SEARCH-001 S8) - `None` for `paid_search_delivery`,
    which is descriptive spend-to-delivery context (via
    `core.media_costs.GovernedCostMapping`), never a graph node of its own.
    """
    if defn.search_role in _DEMAND_CAPTURE_ROLES:
        return NODE_ROLE_DEMAND_CAPTURE
    if defn.search_role == SEARCH_ROLE_PAID_SPEND:
        return NODE_ROLE_INTERVENTION
    if defn.search_role == SEARCH_ROLE_PAID_CAP:
        return NODE_ROLE_CAPACITY_OR_CAP
    return None


@dataclass(frozen=True)
class SearchObjectValidationIssue:
    """One cross-object validation failure (REQ-SEARCH-001 S14) -
    single-object structural errors already raise from `__post_init__`;
    this covers only checks that require seeing the whole catalogue."""

    search_object_id: str
    market: str
    issue_type: str
    detail: str


def validate_search_object_catalogue(
    definitions: Sequence[SearchObjectDefinition],
) -> List[SearchObjectValidationIssue]:
    """Cross-object checks a single record's own `__post_init__` cannot make:

    - no two records may share `(market, search_object_id)` (the same
      unambiguous identity `ActivityDefinition.activity_key` already
      requires);
    - no two records at the same `(market, source_column)` may claim
      *different* `search_role`s - a column already governed as
      `paid_search_delivery` (e.g. a click column) can never simultaneously
      be registered as `paid_search_cap`, and equally for any other pair
      (REQ-SEARCH-001 S14, S2: "no two of S1.1-S1.6 may ever share a
      governed record"). Every record sharing the conflicting column is
      flagged - not only whichever happens to appear later - since nothing
      here can determine which of the conflicting roles is the "correct"
      one; keeping either arbitrarily would be exactly the silent
      collapsing REQ-SEARCH-001 exists to prevent.
    """
    issues: List[SearchObjectValidationIssue] = []
    seen_keys: Dict[Tuple[str, str], SearchObjectDefinition] = {}
    for defn in definitions:
        key = defn.search_object_key
        if key in seen_keys:
            issues.append(
                SearchObjectValidationIssue(
                    search_object_id=defn.search_object_id,
                    market=defn.market,
                    issue_type="duplicate_identity",
                    detail=(
                        f"(market, search_object_id) {key} is already used by "
                        "another search object record."
                    ),
                )
            )
        else:
            seen_keys[key] = defn

    by_column: Dict[Tuple[str, str], List[SearchObjectDefinition]] = {}
    for defn in definitions:
        by_column.setdefault((defn.market, defn.source_column), []).append(defn)
    for (market, column), group in by_column.items():
        distinct_roles = {member.search_role for member in group}
        if len(distinct_roles) <= 1:
            continue
        roles_summary = ", ".join(
            f"{member.search_role!r} ({member.search_object_id})" for member in group
        )
        for defn in group:
            issues.append(
                SearchObjectValidationIssue(
                    search_object_id=defn.search_object_id,
                    market=market,
                    issue_type="incompatible_column_alias",
                    detail=(
                        f"source_column {column!r} in market {market!r} is "
                        f"claimed by conflicting search roles: {roles_summary}. "
                        "The same raw column can never serve two different "
                        "Search semantic roles."
                    ),
                )
            )
    return issues


def search_objects_fingerprint(
    definitions: Iterable[SearchObjectDefinition | Mapping[str, Any]],
) -> str:
    """Deterministic fingerprint of a Search object catalogue - mirrors
    `core.activities.activity_definitions_fingerprint`. Not yet wired into
    `core.fingerprint.fingerprint_model_spec`'s current-model-identity
    payload (that threading is deferred to when a fit actually consumes a
    Search object's `model_input_column` - REQ-SEARCH-001 explicitly scopes
    this record to identity/governance, not fit-time mathematics), but is
    available now so a dependent PR can bind it the same way
    `activity_fit_fingerprint` already is.
    """
    payload = [
        item.to_dict()
        if isinstance(item, SearchObjectDefinition)
        else SearchObjectDefinition.from_dict(item).to_dict()
        for item in definitions
    ]
    payload.sort(
        key=lambda item: (str(item.get("market")), str(item.get("search_object_id")))
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
