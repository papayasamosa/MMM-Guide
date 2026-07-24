"""Governed activity taxonomy for paid, owned, earned, and event drivers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Iterable, Mapping, Optional

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
ECONOMICS_STATUSES = {
    "monetary_economics_available",
    "fully_loaded_economics_available",
    "response_only",
    "economics_not_applicable",
    "mapping_missing",
}


@dataclass(frozen=True)
class ActivityDefinition:
    activity_id: str
    channel: str
    activity_ownership: str
    model_role: str
    economic_treatment: str
    planning_eligibility: str
    source: str
    evidence_status: str = "not_assessed"
    governance_notes: str = ""
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.activity_id or not self.channel or not self.source:
            raise ValueError("activity_id, channel, and source are required")
        if self.activity_ownership not in OWNERSHIP:
            raise ValueError("invalid activity_ownership")
        if self.model_role not in MODEL_ROLES:
            raise ValueError("invalid model_role")
        if self.economic_treatment not in ECONOMIC_TREATMENTS:
            raise ValueError("invalid economic_treatment")
        if self.planning_eligibility not in PLANNING_ELIGIBILITY:
            raise ValueError("invalid planning_eligibility")
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
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "ActivityDefinition":
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in values.items() if key in known})


def activity_definitions_fingerprint(
    definitions: Iterable[ActivityDefinition | Mapping[str, object]],
) -> str:
    payload = [
        item.to_dict() if isinstance(item, ActivityDefinition) else dict(item)
        for item in definitions
    ]
    payload.sort(key=lambda item: (str(item.get("channel")), str(item.get("activity_id"))))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def activity_by_channel(
    definitions: Iterable[ActivityDefinition],
) -> dict[str, ActivityDefinition]:
    result: dict[str, ActivityDefinition] = {}
    for definition in definitions:
        if definition.channel in result:
            raise ValueError(f"duplicate activity definition for {definition.channel}")
        result[definition.channel] = definition
    return result
