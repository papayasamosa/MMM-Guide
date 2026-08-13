"""Governed activity taxonomy and downstream invalidation contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

OWNERSHIP = {"paid", "owned", "earned", "external_event"}
MODEL_ROLES = {"intervention", "mediator", "demand_capture", "control", "event"}
ECONOMIC_TREATMENTS = {
    "paid_media_cost",
    "fully_loaded_cost",
    "campaign_cost",
    "response_only",
    "not_applicable",
}
PLANNING_ELIGIBILITY = {"optimisable", "scenario_only", "fixed", "excluded"}
APPROVAL_STATUSES = {"draft", "reviewed", "approved", "rejected", "superseded"}
ECONOMICS_STATUSES = {
    "monetary_economics_available",
    "fully_loaded_economics_available",
    "response_only",
    "economics_not_applicable",
    "mapping_missing",
    "partial_cost_coverage",
}
COST_BEARING_TREATMENTS = {
    "paid_media_cost",
    "fully_loaded_cost",
    "campaign_cost",
}

# Funnel classification is a governed reporting dimension. It is deliberately
# a closed vocabulary so grouped reports cannot silently acquire spelling
# variants, but it is not read by model builders or causal-graph compilation.
FUNNEL_STAGES = (
    "brand_upper",
    "mid_funnel",
    "performance_lower",
    "cross_funnel",
    "not_applicable",
    "unclassified",
)

# Marketing objective remains an optional normalized string rather than a
# closed enum. These values are UI suggestions only; the core never infers or
# rewrites an analyst-provided objective.
MARKETING_OBJECTIVE_SUGGESTIONS = (
    "brand awareness",
    "consideration",
    "acquisition/performance",
    "retention/lifecycle",
    "promotion",
    "winback",
    "service/transactional",
    "other",
)

ACTIVITY_SCHEMA_VERSION = 4

# Reporting-only identity and classification fields. Keeping this list
# explicit prevents a future taxonomy field from accidentally entering the
# mathematical fit fingerprint or the hard curve/scenario governance gate.
REPORTING_TAXONOMY_FIELDS = (
    "market",
    "activity_id",
    "pooling_group_id",
    "channel",
    "platform",
    "campaign_type",
    "product_advertised",
    "marketing_objective",
    "message_type",
    "funnel_stage",
    "activity_ownership",
)


@dataclass(frozen=True)
class ActivityDefinition:
    """One governed activity at ``market × activity_id`` grain.

    ``channel`` is the reporting family; ``model_input_column`` is the fitted
    predictor. Multiple activities may share a channel when they have distinct
    model-input columns (for example paid and organic social).

    ``pooling_group_id`` (REQ-DATAIN-001, schema v3): an optional, stable
    identity marking "the same activity across markets" for cross-market
    reporting/analysis. Deliberately excluded from ``_INVALIDATION_MATRIX``
    below (editing it triggers no refit/rebuild flag) and never read by any
    modelling code in this module or elsewhere - its presence must never,
    by itself, force, imply, or default to parameter pooling for the
    activity in any model. Pooling remains governed exclusively by the
    model's own hierarchy configuration
    (``core.market_specific_model``/``docs/market_hierarchy.md``).
    """

    activity_id: str
    channel: str
    activity_ownership: str
    model_role: str
    economic_treatment: str
    planning_eligibility: str
    source: str
    market: str = "*"
    platform: str = ""
    campaign_type: str = ""
    product_advertised: str = ""
    message_type: str = ""
    model_input_column: str = ""
    pooling_group_id: str | None = None
    pathway_ids: tuple[str, ...] = ()
    evidence_status: str = "not_assessed"
    evidence_source: str = ""
    rationale: str = ""
    limitations: str = ""
    governance_notes: str = ""
    approval_status: str = "draft"
    reviewed_by: str = ""
    reviewed_at: str = ""
    approved_by: str | None = None
    approved_at: str | None = None
    change_history: tuple[Mapping[str, Any], ...] = ()
    supersedes_activity_id: str | None = None
    # Kept after the pre-existing fields to avoid changing positional
    # constructor meaning for callers that supplied schema_version directly.
    schema_version: int = ACTIVITY_SCHEMA_VERSION
    marketing_objective: str = ""
    funnel_stage: str = "unclassified"

    def __post_init__(self) -> None:
        if not self.activity_id or not self.channel or not self.source:
            raise ValueError("activity_id, channel, and source are required")
        if not self.market:
            raise ValueError("market is required; use '*' for all markets")
        if self.activity_ownership not in OWNERSHIP:
            raise ValueError("invalid activity_ownership")
        if self.model_role not in MODEL_ROLES:
            raise ValueError("invalid model_role")
        if self.economic_treatment not in ECONOMIC_TREATMENTS:
            raise ValueError("invalid economic_treatment")
        if self.planning_eligibility not in PLANNING_ELIGIBILITY:
            raise ValueError("invalid planning_eligibility")
        if self.approval_status not in APPROVAL_STATUSES:
            raise ValueError("invalid approval_status")
        if self.funnel_stage not in FUNNEL_STAGES:
            raise ValueError(
                f"invalid funnel_stage {self.funnel_stage!r}; "
                f"expected one of {FUNNEL_STAGES}"
            )
        if not isinstance(self.marketing_objective, str):
            raise ValueError("marketing_objective must be a string")
        if self.planning_eligibility == "optimisable" and self.model_role in {
            "mediator",
            "control",
            "event",
        }:
            raise ValueError(
                "mediators, controls, and events cannot be freely optimised"
            )
        if (
            self.activity_ownership == "external_event"
            and self.planning_eligibility == "optimisable"
        ):
            raise ValueError("external events cannot be freely optimised")
        if self.approval_status == "approved" and (
            not self.approved_by or not self.approved_at
        ):
            raise ValueError("approved activities require approved_by and approved_at")

    @property
    def activity_key(self) -> tuple[str, str]:
        return self.market, self.activity_id

    @property
    def resolved_model_input_column(self) -> str:
        return self.model_input_column or self.channel

    @property
    def is_cost_bearing(self) -> bool:
        return self.economic_treatment in COST_BEARING_TREATMENTS

    def applies_to_market(self, market: str) -> bool:
        return self.market in {"*", market}

    def economics_status(self, *, has_approved_cost_basis: bool) -> str:
        if self.economic_treatment == "response_only":
            return "response_only"
        if self.economic_treatment == "not_applicable":
            return "economics_not_applicable"
        if not has_approved_cost_basis:
            return "mapping_missing"
        if self.economic_treatment == "fully_loaded_cost":
            return "fully_loaded_economics_available"
        return "monetary_economics_available"

    def to_dict(self) -> dict:
        values = asdict(self)
        values["pathway_ids"] = list(self.pathway_ids)
        values["change_history"] = [dict(item) for item in self.change_history]
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> ActivityDefinition:
        # Dataclass field values are validated by __post_init__; using Any
        # here also reflects JSON's heterogeneous object values and keeps the
        # migration adapter independent from the serialisation library.
        payload: dict[str, Any] = dict(values)
        payload.setdefault("market", "*")
        payload.setdefault(
            "model_input_column",
            str(payload.get("channel", "")),
        )
        # Explicit migration for the taxonomy fields. Missing values are
        # intentionally unclassified/blank: no activity name, platform,
        # campaign, or source-column heuristic is allowed here.
        payload.setdefault("funnel_stage", "unclassified")
        payload.setdefault("marketing_objective", "")

        # A payload with no schema_version key at all predates versioning
        # entirely. Preserve the existing legacy floor before normalising the
        # object to the current serialised shape. A subsequent export writes
        # schema v4 with the explicit taxonomy defaults.
        payload.setdefault("schema_version", 2)
        if payload["schema_version"] < ACTIVITY_SCHEMA_VERSION:
            payload["schema_version"] = ACTIVITY_SCHEMA_VERSION
        payload["pathway_ids"] = tuple(payload.get("pathway_ids") or ())
        payload["change_history"] = tuple(payload.get("change_history") or ())
        if (
            "approval_status" not in payload
            and payload.get("approved_by")
            and payload.get("approved_at")
        ):
            payload["approval_status"] = "approved"
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in payload.items() if key in known})


def activity_definitions_fingerprint(
    definitions: Iterable[ActivityDefinition | Mapping[str, object]],
) -> str:
    """Fingerprint activity governance state for curve/scenario staleness gates.

    Excludes ``pooling_group_id`` (REQ-DATAIN-001): this fingerprint is a
    hard blocking gate (``CurveArtifactService.validate_for_use``,
    ``core.optimization`` scenario staleness), not a soft audit signal.
    Including a field the approved invariant says must never force a
    rebuild would silently invalidate curves/scenarios on an edit that
    changes nothing fit-relevant - use ``activity_fit_fingerprint`` or
    ``_INVALIDATION_MATRIX`` for anything that should actually gate.
    """
    payload = [
        item.to_dict()
        if isinstance(item, ActivityDefinition)
        else ActivityDefinition.from_dict(item).to_dict()
        for item in definitions
    ]
    for item in payload:
        item.pop("pooling_group_id", None)
        # Funnel/objective are reporting taxonomy, not curve/scenario
        # governance inputs. They have their own fingerprint below.
        item.pop("marketing_objective", None)
        item.pop("funnel_stage", None)
    payload.sort(
        key=lambda item: (
            str(item.get("market")),
            str(item.get("activity_id")),
        )
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def activity_reporting_fingerprint(
    definitions: Iterable[ActivityDefinition | Mapping[str, object]],
) -> str:
    """Fingerprint the taxonomy used by grouped activity reporting.

    This is intentionally separate from ``activity_fit_fingerprint`` and the
    hard ``activity_definitions_fingerprint`` gate. A taxonomy edit should
    make a materialised grouped report reproducible against a new taxonomy
    version without pretending that model equations or fitted curves changed.
    """

    payload = []
    for item in definitions:
        definition = (
            item
            if isinstance(item, ActivityDefinition)
            else ActivityDefinition.from_dict(item)
        )
        payload.append(
            {field: getattr(definition, field) for field in REPORTING_TAXONOMY_FIELDS}
        )
    payload.sort(key=lambda item: (str(item["market"]), str(item["activity_id"])))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def activity_fit_fingerprint(
    definitions: Iterable[ActivityDefinition | Mapping[str, object]],
) -> str:
    """Fingerprint only activity fields whose changes require a model refit."""

    payload = []
    for item in definitions:
        definition = (
            item
            if isinstance(item, ActivityDefinition)
            else ActivityDefinition.from_dict(item)
        )
        payload.append(
            {
                "market": definition.market,
                "activity_id": definition.activity_id,
                "model_role": definition.model_role,
                "model_input_column": definition.resolved_model_input_column,
                "pathway_ids": sorted(definition.pathway_ids),
            }
        )
    payload.sort(key=lambda item: (item["market"], item["activity_id"]))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def activity_by_model_input(
    definitions: Iterable[ActivityDefinition],
    market: str,
) -> dict[str, ActivityDefinition]:
    """Resolve one activity per fitted predictor, preferring market-specific rows."""

    result: dict[str, ActivityDefinition] = {}
    for specificity in ("*", market):
        for definition in definitions:
            if definition.market != specificity:
                continue
            column = definition.resolved_model_input_column
            if column in result and result[column].market == specificity:
                raise ValueError(
                    "duplicate activity definitions for "
                    f"{market}/{column}; use distinct model_input_column values"
                )
            result[column] = definition
    return result


def resolve_activity_definition(
    definitions: Iterable[ActivityDefinition],
    *,
    market: str,
    activity_id: str,
) -> ActivityDefinition:
    """Resolve one governed activity for a market and stable activity ID.

    Exact market rows take precedence over a wildcard row.  Ambiguous rows
    fail closed rather than selecting the first match.  The returned object
    remains the business identity; callers use
    ``resolved_model_input_column`` only at the engine boundary.
    """

    candidates = [
        definition
        for definition in definitions
        if definition.activity_id == activity_id
        and definition.applies_to_market(market)
    ]
    exact = [definition for definition in candidates if definition.market == market]
    if len(exact) > 1:
        raise ValueError(
            f"duplicate activity definitions for {market}/{activity_id}; "
            "review the activity mapping"
        )
    if exact:
        return exact[0]
    wildcard = [definition for definition in candidates if definition.market == "*"]
    if len(wildcard) > 1:
        raise ValueError(
            f"duplicate wildcard activity definitions for {market}/{activity_id}; "
            "review the activity mapping"
        )
    if wildcard:
        return wildcard[0]
    raise KeyError(f"no governed activity {activity_id!r} applies to market {market!r}")


def resolve_activity_model_input(
    definitions: Iterable[ActivityDefinition],
    *,
    market: str,
    activity_id: str,
) -> str:
    """Resolve ``market + activity_id`` to its physical model-input column.

    This is the explicit boundary used by business-facing workflow code.
    ``ActivityDefinition.channel`` is deliberately not returned: it is a
    reporting roll-up and may be shared by several activities.
    """

    return resolve_activity_definition(
        definitions, market=market, activity_id=activity_id
    ).resolved_model_input_column


def legacy_activity_definitions_from_model_spec(
    model_spec: Any,
) -> list[ActivityDefinition]:
    """Adapt a pre-activity-governance ``ModelSpec`` into explicit activities.

    Older saved projects stored only ``ModelSpec.channels``.  This adapter
    preserves those projects without guessing from names or creating a second
    registry.  The returned rows are intentionally marked as a legacy
    compatibility source and remain reviewable in Activity Mapping before a
    new governed save.
    """

    markets = [str(market) for market in getattr(model_spec, "markets", ())]
    channels = [str(channel) for channel in getattr(model_spec, "channels", ())]
    return [
        ActivityDefinition(
            activity_id=f"{market}:{channel}",
            market=market,
            channel=channel,
            model_input_column=channel,
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="legacy ModelSpec.channels compatibility adapter; review required",
        )
        for market in markets
        for channel in channels
    ]


def activity_by_channel(
    definitions: Iterable[ActivityDefinition],
    market: str = "*",
) -> dict[str, ActivityDefinition]:
    """Legacy channel lookup for curve callers that still operate per predictor."""

    resolved = activity_by_model_input(definitions, market)
    result: dict[str, ActivityDefinition] = {}
    for definition in resolved.values():
        if definition.channel in result:
            raise ValueError(
                f"multiple activities share channel {definition.channel!r}; "
                "use activity_by_model_input"
            )
        result[definition.channel] = definition
    return result


@dataclass(frozen=True)
class ActivityInvalidation:
    refit_model: bool = False
    rebuild_curves: bool = False
    rebuild_economics: bool = False
    rebuild_scenarios: bool = False
    changed_fields: tuple[str, ...] = ()


_INVALIDATION_MATRIX = {
    "economic_treatment": (False, True, True, True),
    "planning_eligibility": (False, False, False, True),
    "activity_ownership": (False, True, True, True),
    "model_role": (True, True, True, True),
    "model_input_column": (True, True, True, True),
    "pathway_ids": (True, True, True, True),
    # pooling_group_id (REQ-DATAIN-001) is deliberately absent here - it is
    # descriptive/identity metadata never read by modelling code, so
    # editing it must never trigger a refit or rebuild prompt (which would
    # itself imply the field has a fit-relevant effect, contradicting the
    # approved invariant that its presence never forces/implies pooling).
    # It is also excluded from activity_definitions_fingerprint (the
    # curve-artifact/scenario staleness gate) for the same reason - that
    # fingerprint blocks curve use and marks scenarios stale on mismatch,
    # so including a field that must never gate a rebuild would silently
    # invalidate artifacts on a no-op-for-fitting edit.
}


def activity_invalidation(
    previous: ActivityDefinition,
    current: ActivityDefinition,
) -> ActivityInvalidation:
    """Return the explicit downstream invalidation matrix for one edit."""

    changed = tuple(
        field
        for field in _INVALIDATION_MATRIX
        if getattr(previous, field) != getattr(current, field)
    )
    impacts = [_INVALIDATION_MATRIX[field] for field in changed]
    return ActivityInvalidation(
        refit_model=any(item[0] for item in impacts),
        rebuild_curves=any(item[1] for item in impacts),
        rebuild_economics=any(item[2] for item in impacts),
        rebuild_scenarios=any(item[3] for item in impacts),
        changed_fields=changed,
    )


def validate_activity_pathway_links(
    definitions: Iterable[ActivityDefinition],
    pathway_ids: Iterable[str],
) -> None:
    known = set(pathway_ids)
    unknown = sorted(
        {
            pathway_id
            for definition in definitions
            for pathway_id in definition.pathway_ids
            if pathway_id not in known
        }
    )
    if unknown:
        raise ValueError(f"unknown pathway_ids in activity definitions: {unknown}")
