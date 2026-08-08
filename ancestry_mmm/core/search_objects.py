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
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .activities import PLANNING_ELIGIBILITY
from .causal_graph import (
    NODE_ROLE_CAPACITY_OR_CAP,
    NODE_ROLE_DEMAND_CAPTURE,
    NODE_ROLE_INTERVENTION,
)

# REQ-SEARCH-001 S10: bumped 1 -> 2 for effective_period_start/
# effective_period_end and search_object_version (lifecycle closure). A
# payload declaring a schema_version above this is unsupported and rejected
# outright by `SearchObjectDefinition.from_dict` (fail closed), mirroring
# `core.causal_graph.CausalGraph`'s `CAUSAL_GRAPH_SCHEMA_VERSION` contract.
SEARCH_OBJECT_SCHEMA_VERSION = 2

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


def _validate_effective_period(start: Optional[str], end: Optional[str]) -> None:
    """Mirrors `core.media_costs._validate_period`: `date.fromisoformat`
    itself raises `ValueError` for a malformed date string; an explicit
    start-after-end is rejected here."""
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    if start_date and end_date and start_date > end_date:
        raise ValueError(
            "effective_period_start must not be after effective_period_end"
        )


def _validate_search_object_schema_version(raw: Any, *, search_object_id: str) -> int:
    """Strict `schema_version` validation for `SearchObjectDefinition.from_dict`
    (REQ-SEARCH-001 S11). `int(...)` coercion is not validation - it silently
    accepts a numeric string (`"2"`), truncates a float (`2.5` -> `2`), and
    (since `bool` is a `int` subclass in Python) accepts `True`/`False` as
    `1`/`0`. None of those are a genuine integer schema-version declaration,
    so each is rejected outright here, named by the record's
    `search_object_id` and the offending value/type - never silently
    coerced. Only an actual `int` (never `bool`) that is `>= 1` and
    `<= SEARCH_OBJECT_SCHEMA_VERSION` is accepted.
    """
    if isinstance(raw, bool) or type(raw) is not int:
        raise ValueError(
            f"Search object {search_object_id!r} declares a non-integer "
            f"schema_version {raw!r} (type={type(raw).__name__}) - "
            "schema_version must be an actual integer, never a bool, float, "
            "numeric string, or other coercible value."
        )
    if raw < 1:
        raise ValueError(
            f"Search object {search_object_id!r} declares schema_version "
            f"{raw} - schema_version must be >= 1."
        )
    if raw > SEARCH_OBJECT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported search object schema_version {raw} - "
            f"this build only understands up to "
            f"{SEARCH_OBJECT_SCHEMA_VERSION}."
        )
    return raw


@dataclass(frozen=True)
class SearchObjectDefinition:
    """One governed Search object at `market x search_object_id` grain -
    mirrors `core.activities.ActivityDefinition`'s shape/validation style.

    `planning_eligibility` reuses `core.activities.PLANNING_ELIGIBILITY`
    (REQ-SEARCH-001 S9): a demand-capture role or a cap may never be
    `"optimisable"` - a cap constrains `paid_search_spend`'s optimisation,
    it is never itself an optimisable target.

    `channel` mirrors `core.activities.ActivityDefinition.channel` /
    `core.media_costs.MediaInputSpec.channel`: an explicit, governed
    attribute - never inferred from `source_column` or `search_object_id` by
    name-matching - at `market x channel` grain. It is what
    `validate_search_object_catalogue` uses to resolve a `paid_search_cap`
    record's required `paid_search_spend`/`paid_search_delivery` counterpart
    (REQ-SEARCH-001 S14's last bullet). Left blank, a record simply
    participates in no channel-scoped relationship - a blank `channel` never
    matches another blank `channel`.

    `search_object_id`/`market` together are this record's **lineage**
    identity - the same logical Search object across every version, mirroring
    `core.causal_graph.CausalGraph.graph_id`. `search_object_version` is the
    version number within that lineage (REQ-SEARCH-001 S10: "an edit is a new
    version, never an in-place mutation of an approved record"). Use
    `new_search_object_version` to edit a governed record - never construct a
    second record at the same lineage with the same `search_object_version`
    by hand (`validate_search_object_catalogue` rejects that as
    `duplicate_identity`).

    `effective_period_start`/`effective_period_end` mirror
    `core.media_costs.MediaInputSpec`/`GovernedCostMapping`'s identically
    named fields: an optional ISO-8601 date window this record is scoped to.
    Both blank means "no declared window" (always in scope). A malformed date
    string raises `ValueError` (via `date.fromisoformat`); a start after an
    end raises `ValueError` explicitly - both fail closed, never silently
    ignored.
    """

    search_object_id: str
    search_role: str
    source_column: str
    unit: str
    market: str = "*"
    channel: str = ""
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
    schema_version: int = SEARCH_OBJECT_SCHEMA_VERSION
    effective_period_start: Optional[str] = None
    effective_period_end: Optional[str] = None
    search_object_version: int = 1

    def __post_init__(self) -> None:
        if not self.search_object_id or not self.source_column:
            raise ValueError("search_object_id and source_column are required")
        if not self.market:
            raise ValueError("market is required; use '*' for all markets")
        _validate_effective_period(
            self.effective_period_start, self.effective_period_end
        )
        if self.search_object_version < 1:
            raise ValueError("search_object_version must be >= 1")
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
        """This record's lineage identity - the same logical Search object
        across every `search_object_version` (mirrors
        `core.causal_graph.CausalGraph.graph_id`)."""
        return self.market, self.search_object_id

    @property
    def search_object_version_key(self) -> Tuple[str, str, int]:
        """This exact version's identity - unique within a well-formed
        catalogue (`validate_search_object_catalogue` rejects a duplicate as
        `duplicate_identity`)."""
        return self.market, self.search_object_id, self.search_object_version

    def to_dict(self) -> dict:
        values = asdict(self)
        values["change_history"] = [dict(item) for item in self.change_history]
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SearchObjectDefinition":
        """Raises `ValueError` for a `schema_version` newer than this build
        understands, or a `schema_version` that is not an actual positive
        integer - refuses to guess at an unrecognised or malformed schema
        (REQ-SEARCH-001 S11/S10), mirroring
        `core.causal_graph.CausalGraph.from_dict`'s contract. A bool, float,
        numeric string, explicit `None`, zero, or negative value is rejected
        outright by `_validate_search_object_schema_version` - never coerced
        via `int(...)`. Callers importing untrusted bundle content should
        catch this alongside TypeError/KeyError/AttributeError and
        quarantine the record - see
        `core.persistence.resolve_imported_search_objects`.

        A legacy record predating `SEARCH_OBJECT_SCHEMA_VERSION` 2 (no
        `schema_version` key at all - genuinely absent, the documented
        migration case) resolves to the current schema version, and its
        equally-absent `effective_period_start`/`effective_period_end`/
        `search_object_version` keys default to `None`/`None`/`1`, the
        correct reading of "no declared window, first version" for a record
        that predates this capability entirely. A record that *does* supply
        `schema_version` - including an explicit `null` - is validated
        strictly; only a genuinely missing key takes the legacy default.
        """
        payload = dict(values)
        payload.setdefault("market", "*")
        search_object_id = str(payload.get("search_object_id", "<unknown>"))
        if "schema_version" in payload:
            schema_version = _validate_search_object_schema_version(
                payload["schema_version"], search_object_id=search_object_id
            )
        else:
            schema_version = SEARCH_OBJECT_SCHEMA_VERSION
        payload["schema_version"] = schema_version
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


# --- Version lifecycle (REQ-SEARCH-001 S10) ---------------------------------
#
# Mirrors `core.causal_graph`'s `graph_id`/`graph_version` immutability
# pattern: `(market, search_object_id)` is the lineage, `search_object_version`
# is the version number within it, and every edit produces a brand new
# `SearchObjectDefinition` instance - never an in-place mutation of one that
# already existed.


def new_search_object_version(
    definition: SearchObjectDefinition, **changes: Any
) -> SearchObjectDefinition:
    """Apply an edit to a governed Search object as a new version - never an
    in-place mutation of history (REQ-SEARCH-001 S10). Returns a new
    `SearchObjectDefinition` with `search_object_version` incremented by one
    and `approval_status`/`approved_by`/`approved_at` reset to draft (an
    edit to an approved record must not leave a stale "approved" label on
    now-different content - the same invariant
    `core.causal_graph.mark_draft_if_approved` enforces for causal graphs),
    unless the caller explicitly overrides those in `changes`.

    `search_object_id` and `market` are this record's lineage identity and
    may never be changed here - registering a genuinely different Search
    object means constructing a new `SearchObjectDefinition` directly, not
    calling this function. `search_object_version` may also not be passed in
    `changes`: it is always exactly `definition.search_object_version + 1`.
    """
    for locked_field in ("search_object_id", "market", "search_object_version"):
        if locked_field in changes:
            raise ValueError(
                f"{locked_field!r} is lineage/version identity and cannot be "
                "set via new_search_object_version - construct a new "
                "SearchObjectDefinition directly to register a different "
                "Search object."
            )
    changes.setdefault("approval_status", "draft")
    changes.setdefault("approved_by", None)
    changes.setdefault("approved_at", None)
    return replace(
        definition,
        search_object_version=definition.search_object_version + 1,
        **changes,
    )


def current_search_object_versions(
    definitions: Iterable[SearchObjectDefinition | Mapping[str, Any]],
) -> List[SearchObjectDefinition]:
    """Resolve, per `(market, search_object_id)` lineage, the current
    (highest `search_object_version`) record - mirrors
    `core.causal_graph.current_graph_from_resolved_versions`, generalised to
    a whole catalogue at once. Deterministic and independent of `definitions`
    order: within a well-formed catalogue (no `duplicate_identity` issue),
    at most one record per lineage carries the maximum version number for
    that lineage, so no tie-break policy is needed.
    """
    latest: Dict[Tuple[str, str], SearchObjectDefinition] = {}
    for item in definitions:
        defn = (
            item
            if isinstance(item, SearchObjectDefinition)
            else SearchObjectDefinition.from_dict(item)
        )
        key = defn.search_object_key
        current = latest.get(key)
        if (
            current is None
            or defn.search_object_version > current.search_object_version
        ):
            latest[key] = defn
    return list(latest.values())


def search_object_versions_for_export(
    *,
    current_definitions: Optional[Sequence[Mapping[str, Any]]],
    version_history: Optional[Sequence[Mapping[str, Any]]],
) -> List[dict]:
    """The Search object version records worth persisting in a project
    export bundle (`core.persistence.export_project`'s `search_objects`
    argument) - mirrors `core.causal_graph.graph_versions_for_export`: every
    explicitly saved version (`version_history` - appended by the Channel &
    Media Units page's Save action) plus the current live records, so a
    brand-new, never-yet-re-saved record is not silently lost across an
    export/import round trip. `version_history` is always authoritative for
    a `(market, search_object_id, search_object_version)` key it already
    contains; a current record is added only when its key is new or
    identical to the already-saved record under that key.
    """
    history_by_key: Dict[Tuple[str, str, int], dict] = {}
    for item in version_history or []:
        key = (
            str(item.get("market", "")),
            str(item.get("search_object_id", "")),
            int(item.get("search_object_version", 1)),
        )
        history_by_key[key] = dict(item)
    for item in current_definitions or []:
        key = (
            str(item.get("market", "")),
            str(item.get("search_object_id", "")),
            int(item.get("search_object_version", 1)),
        )
        existing = history_by_key.get(key)
        if existing is None or existing == dict(item):
            history_by_key[key] = dict(item)
    return list(history_by_key.values())


@dataclass(frozen=True)
class SearchObjectValidationIssue:
    """One cross-object validation failure (REQ-SEARCH-001 S14) -
    single-object structural errors already raise from `__post_init__`;
    this covers only checks that require seeing the whole catalogue."""

    search_object_id: str
    market: str
    issue_type: str
    detail: str


# Which search role is a valid paid_search_cap counterpart for a given cap
# unit (REQ-SEARCH-001 S14's last bullet: "a cap record with no
# corresponding S1.2 or S1.3 record in the same market x channel to
# constrain"). A monetary cap constrains spend; an exposure cap constrains
# delivery - the two are never interchangeable counterparts.
_CAP_COUNTERPART_ROLE_BY_UNIT: Dict[str, str] = {
    UNIT_MONETARY: SEARCH_ROLE_PAID_SPEND,
    UNIT_EXPOSURE_COUNT: SEARCH_ROLE_PAID_DELIVERY,
}


def validate_search_object_catalogue(
    definitions: Sequence[SearchObjectDefinition],
) -> List[SearchObjectValidationIssue]:
    """Cross-object checks a single record's own `__post_init__` cannot make:

    - no two records may share the exact same `(market, search_object_id,
      search_object_version)` (REQ-SEARCH-001 S10: distinct versions of the
      same lineage are expected and legitimate - `current_search_object_
      versions` resolves which one is current - but two records both
      claiming to *be* the same version of the same lineage is a genuine
      identity collision, e.g. corrupted or hand-edited import data);
    - no two *current* records at the same `(market, source_column)` may
      claim *different* `search_role`s - a column already governed as
      `paid_search_delivery` (e.g. a click column) can never simultaneously
      be registered as `paid_search_cap`, and equally for any other pair
      (REQ-SEARCH-001 S14, S2: "no two of S1.1-S1.6 may ever share a
      governed record"). Every record sharing the conflicting column is
      flagged - not only whichever happens to appear later - since nothing
      here can determine which of the conflicting roles is the "correct"
      one; keeping either arbitrarily would be exactly the silent
      collapsing REQ-SEARCH-001 exists to prevent.
    - every *current* `paid_search_cap` record must have exactly one
      channel-scoped relationship to the `paid_search_spend`/
      `paid_search_delivery` record it constrains (REQ-SEARCH-001 S14's last
      bullet), resolved only by exact `(market, channel)` equality on the
      governed `channel` field - never by name-matching
      `search_object_id`/`source_column`, row order, or UI position. A blank
      `channel` never resolves a relationship: it means "no relationship
      declared", not "matches every other blank".

    The column-alias and cap-counterpart checks run only over
    `current_search_object_versions(definitions)` - a superseded historical
    version of an edited record must never be flagged as conflicting with
    its own successor, or count as a second cap bound to the same channel;
    only the current state of the catalogue is a live governance claim. The
    duplicate-version check runs over the full, unresolved `definitions` -
    it is a structural integrity check on the raw input, not a current-state
    governance check.
    """
    issues: List[SearchObjectValidationIssue] = []
    seen_version_keys: Dict[Tuple[str, str, int], SearchObjectDefinition] = {}
    for defn in definitions:
        key = defn.search_object_version_key
        if key in seen_version_keys:
            issues.append(
                SearchObjectValidationIssue(
                    search_object_id=defn.search_object_id,
                    market=defn.market,
                    issue_type="duplicate_identity",
                    detail=(
                        f"(market, search_object_id, search_object_version) "
                        f"{key} is already used by another search object "
                        "record."
                    ),
                )
            )
        else:
            seen_version_keys[key] = defn

    current_definitions = current_search_object_versions(definitions)

    by_column: Dict[Tuple[str, str], List[SearchObjectDefinition]] = {}
    for defn in current_definitions:
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

    caps = [d for d in current_definitions if d.search_role == SEARCH_ROLE_PAID_CAP]
    counterparts_by_key: Dict[Tuple[str, str, str], List[SearchObjectDefinition]] = {}
    for defn in current_definitions:
        if not defn.channel or defn.search_role not in (
            SEARCH_ROLE_PAID_SPEND,
            SEARCH_ROLE_PAID_DELIVERY,
        ):
            continue
        counterparts_by_key.setdefault(
            (defn.market, defn.channel, defn.search_role), []
        ).append(defn)

    caps_by_relationship: Dict[Tuple[str, str, str], List[SearchObjectDefinition]] = {}
    for cap in caps:
        if cap.channel:
            caps_by_relationship.setdefault(
                (cap.market, cap.channel, cap.unit), []
            ).append(cap)
        # __post_init__ already restricts a cap's unit to this mapping's
        # keys, so a direct lookup is always safe.
        required_role = _CAP_COUNTERPART_ROLE_BY_UNIT[cap.unit]
        has_counterpart = bool(cap.channel) and bool(
            counterparts_by_key.get((cap.market, cap.channel, required_role))
        )
        if not has_counterpart:
            issues.append(
                SearchObjectValidationIssue(
                    search_object_id=cap.search_object_id,
                    market=cap.market,
                    issue_type="missing_cap_counterpart",
                    detail=(
                        f"paid_search_cap {cap.search_object_id!r} declares "
                        f"channel {cap.channel!r} but no {required_role!r} "
                        f"record exists at (market={cap.market!r}, "
                        f"channel={cap.channel!r}) for it to constrain. A cap "
                        "must reference, via the governed channel field, an "
                        "existing spend or delivery record in the same "
                        "market/channel scope - never assumed or fabricated."
                    ),
                )
            )

    for (market, channel, unit), group in caps_by_relationship.items():
        if len(group) <= 1:
            continue
        ids_summary = ", ".join(defn.search_object_id for defn in group)
        for cap in group:
            issues.append(
                SearchObjectValidationIssue(
                    search_object_id=cap.search_object_id,
                    market=market,
                    issue_type="duplicate_cap_relationship",
                    detail=(
                        f"channel {channel!r} in market {market!r} has more "
                        f"than one {unit!r} paid_search_cap record ({ids_summary})"
                        " - it is ambiguous which one binds. Each "
                        "(market, channel, unit) may have at most one cap."
                    ),
                )
            )
    return issues


def search_objects_fingerprint(
    definitions: Iterable[SearchObjectDefinition | Mapping[str, Any]],
) -> str:
    """Deterministic fingerprint of the *full* Search object catalogue -
    mirrors `core.activities.activity_definitions_fingerprint`. Every
    governed field, every record, regardless of whether a fit consumes it -
    never bind this whole-catalogue fingerprint into a fitted model's
    identity; use `search_object_fit_fingerprint` below for that
    (REQ-SEARCH-001 fit-identity closure).
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


def search_object_fit_fingerprint(
    definitions: Iterable[SearchObjectDefinition | Mapping[str, Any]],
    consumed_model_input_columns: Iterable[str] = (),
) -> str:
    """Fingerprint only the Search objects a fit actually consumes, and only
    their fit-relevant fields - the Search-object analogue of
    `core.activities.activity_fit_fingerprint`, for binding into
    `core.fingerprint.fingerprint_model_spec`.

    A Search object is "consumed" only if its *current* version's
    `model_input_column` is non-blank and appears, by exact string equality,
    in `consumed_model_input_columns` (pass a fit's actual
    `ModelSpec.channels` - never a name/substring heuristic). `definitions`
    is first resolved to `current_search_object_versions` - a superseded
    historical version never participates, only the live governed record for
    each `(market, search_object_id)` lineage. Registering a Search object
    does not, by itself, make it consumed - REQ-SEARCH-001 S7 is explicit
    that registration changes no fitting behaviour; a Search object only
    becomes fit-relevant when an analyst has pointed its `model_input_column`
    at a column the model spec already fits as an ordinary channel. Every
    other definition - including every one with a blank `model_input_column`
    - is excluded from the payload entirely, so editing (or deleting) an
    unconsumed Search object never changes this fingerprint.

    For each consumed definition, only the fields whose change would alter
    what that fit's governed Search identity *means* are hashed: `market`,
    `search_object_id`, `search_role`, `source_column`, `model_input_column`,
    `unit`, `grain`, `product`. `market`/`search_object_id` are this record's
    lineage identity (needed to distinguish one consumed object from
    another); the rest is fit-relevant content.

    `search_object_version` (the governance/audit version counter
    `new_search_object_version` increments on every sanctioned edit,
    including a purely administrative one - e.g. `planning_eligibility` or
    approval metadata) is deliberately **excluded**. It is governance/audit
    identity, not mathematical fit identity: REQ-SEARCH-001's required
    invariant is that an administrative-only edit changes the Search
    object's own governance version and full-catalogue fingerprint
    (`search_objects_fingerprint`) but never this fit-relevant fingerprint.
    Hashing `search_object_version` here would break that invariant, because
    *every* sanctioned edit - administrative or not - bumps it. Two versions
    of the same lineage that happen to carry identical fit-relevant content
    (e.g. a fit-relevant field edited then reverted) correctly fingerprint
    *identically* here: the fit-relevant inputs a model would actually be
    built from are, at that point, literally the same, so there is nothing
    for a fit's identity to distinguish - the *governance* record of that
    round trip still lives in `search_object_version`/`change_history`, just
    not in this mathematical-identity fingerprint.

    Also excluded, mirroring `activity_fit_fingerprint`'s exclusion of
    `economic_treatment`/`planning_eligibility`/approval metadata: `channel`
    (a cap-counterpart governance relationship only; no fitting mechanism
    reads it, mirroring `activity_fit_fingerprint`'s exclusion of
    `ActivityDefinition.channel`), `effective_period_start`/
    `effective_period_end` (not yet fit-relevant: no model builder gates
    which data rows a consumed column contributes by a Search object's
    declared window - REQ-SEARCH-001 S7's "registration changes no fitting
    behaviour" applies here too), `state`, `planning_eligibility`,
    `evidence_status`, `approval_status`, `approved_by`, `approved_at`,
    `change_history`, `currency`, `schema_version`. A future PR that makes
    the effective period, state, or the version counter itself genuinely
    gate fitted data must move it to the included side here - the same
    "move is itself a fingerprint-breaking change" pattern
    `core.fingerprint.fingerprint_model_spec`'s own docstring documents for
    `MarketDescriptors`.
    """
    consumed = frozenset(column for column in consumed_model_input_columns if column)
    payload = []
    for definition in current_search_object_versions(definitions):
        if not definition.model_input_column:
            continue
        if definition.model_input_column not in consumed:
            continue
        payload.append(
            {
                "market": definition.market,
                "search_object_id": definition.search_object_id,
                "search_role": definition.search_role,
                "source_column": definition.source_column,
                "model_input_column": definition.model_input_column,
                "unit": definition.unit,
                "grain": definition.grain,
                "product": definition.product,
            }
        )
    payload.sort(key=lambda item: (item["market"], item["search_object_id"]))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
