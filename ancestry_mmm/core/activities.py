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


@dataclass(frozen=True)
class ActivityDefinition:
    """One governed activity at ``market × activity_id`` grain.

    ``channel`` is the reporting family; ``model_input_column`` is the fitted
    predictor. Multiple activities may share a channel when they have distinct
    model-input columns (for example paid and organic social).
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
    schema_version: int = 2

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
            raise ValueError(
                "approved activities require approved_by and approved_at"
            )

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
        payload = dict(values)
        payload.setdefault("market", "*")
        payload.setdefault(
            "model_input_column",
            str(payload.get("channel", "")),
        )
        payload.setdefault("schema_version", 2)
        payload["pathway_ids"] = tuple(payload.get("pathway_ids") or ())
        payload["change_history"] = tuple(payload.get("change_history") or ())
        if (
            "approval_status" not in payload
            and payload.get("approved_by")
            and payload.get("approved_at")
        ):
            payload["approval_status"] = "approved"
        known = set(cls.__dataclass_fields__)
        return cls(
            **{key: value for key, value in payload.items() if key in known}
        )


def activity_definitions_fingerprint(
    definitions: Iterable[ActivityDefinition | Mapping[str, object]],
) -> str:
    payload = [
        item.to_dict()
        if isinstance(item, ActivityDefinition)
        else ActivityDefinition.from_dict(item).to_dict()
        for item in definitions
    ]
    payload.sort(
        key=lambda item: (
            str(item.get("market")),
            str(item.get("activity_id")),
        )
    )
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
