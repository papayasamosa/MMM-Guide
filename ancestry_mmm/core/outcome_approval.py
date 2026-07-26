"""
Outcome approval: a separate, fingerprint-bound contract for governing which
outcomes may be used officially for fitting, reporting, curve publication,
planning, optimisation, value layers, or external distribution.

Implements REQ-OUT-002, REQ-NBT-001, REQ-PLAN-001, REQ-USE-001, REQ-STALE-001
(G2A.7 - Outcome Governance Conformance).

Key principles:
- Outcome definition, analytical eligibility, and approval for use are separate.
- Approval is bound to the definition fingerprint; changing the definition stales approval.
- Role/eligibility/inclusion flags never grant approval on their own.
- Legacy projects load as `legacy_unapproved`, never silently as approved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

from .outcomes import OutcomeDefinition

# ---------------------------------------------------------------------------
# Approved vocabularies
# ---------------------------------------------------------------------------

OUTCOME_APPROVAL_STATUSES = (
    "draft",
    "approved",
    "rejected",
    "expired",
    "stale",
    "legacy_unapproved",
)

OUTCOME_USES = (
    "model_fit",
    "technical_reporting",
    "headline_reporting",
    "curve_publication",
    "planning",
    "optimisation",
    "value_layer",
    "external_distribution",
)

OUTCOME_APPROVAL_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Approval contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutcomeApproval:
    """Immutable, fingerprint-bound approval for one outcome definition.

    An `OutcomeApproval` records that a named approver has reviewed the
    outcome's business definition and authorised specific uses. It is bound
    to the exact outcome definition via `definition_fingerprint` — any change
    to calculation-relevant definition fields produces a different fingerprint
    and invalidates the approval.

    This is NOT the same as analytical eligibility (the four
    include_in_* flags on OutcomeDefinition) or model inclusion. Both
    analytical eligibility AND an approval matching the requested use are
    required for official use."""

    approval_id: str
    outcome_id: str
    definition_fingerprint: str
    status: str = "approved"
    allowed_uses: Tuple[str, ...] = ()
    market_scope: Optional[Tuple[str, ...]] = None
    product_scope: Optional[Tuple[str, ...]] = None
    segment_scope: Optional[Tuple[str, ...]] = None
    approved_by: str = ""
    approved_at: str = ""
    expires_at: Optional[str] = None
    conditions: Tuple[str, ...] = ()
    notes: str = ""
    schema_version: int = OUTCOME_APPROVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in OUTCOME_APPROVAL_STATUSES:
            raise ValueError(
                f"Unknown outcome approval status {self.status!r}; "
                f"must be one of {OUTCOME_APPROVAL_STATUSES}"
            )
        for use in self.allowed_uses:
            if use not in OUTCOME_USES:
                raise ValueError(
                    f"Unknown outcome use {use!r}; "
                    f"must be one of {OUTCOME_USES}"
                )

    def is_active(self, as_of: Optional[str] = None) -> bool:
        """True if this approval is currently in effect (approved, not expired)."""
        if self.status not in ("approved",):
            return False
        if self.expires_at is not None and as_of is not None:
            if as_of > self.expires_at:
                return False
        return True

    def allows_use(self, requested_use: str) -> bool:
        """True if `requested_use` is in this approval's allowed_uses."""
        return requested_use in self.allowed_uses

    def matches_scope(
        self,
        *,
        market: Optional[str] = None,
        product: Optional[str] = None,
        segment: Optional[str] = None,
    ) -> bool:
        """True if this approval's scope covers the requested market/product/segment.

        None scope on the approval means "unrestricted" for that dimension.
        None passed by the caller means "don't filter on that dimension"."""
        if self.market_scope is not None and market is not None:
            if market not in self.market_scope:
                return False
        if self.product_scope is not None and product is not None:
            if product not in self.product_scope:
                return False
        if self.segment_scope is not None and segment is not None:
            if segment not in self.segment_scope:
                return False
        return True

    def to_dict(self) -> dict:
        values = asdict(self)
        values["allowed_uses"] = list(self.allowed_uses)
        values["market_scope"] = (
            list(self.market_scope) if self.market_scope is not None else None
        )
        values["product_scope"] = (
            list(self.product_scope) if self.product_scope is not None else None
        )
        values["segment_scope"] = (
            list(self.segment_scope) if self.segment_scope is not None else None
        )
        values["conditions"] = list(self.conditions)
        return values

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeApproval":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in d.items() if k in known}
        for tuple_field in ("allowed_uses", "market_scope", "product_scope", "segment_scope", "conditions"):
            if tuple_field in payload and isinstance(payload[tuple_field], list):
                payload[tuple_field] = tuple(payload[tuple_field])
        return cls(**payload)


# ---------------------------------------------------------------------------
# Definition fingerprinting (REQ-STALE-001)
# ---------------------------------------------------------------------------

_FINGERPRINT_FIELDS = (
    "outcome_id",
    "definition_version",
    "product",
    "segment",
    "metric_key",
    "unit",
    "aggregation_type",
    "event_definition",
    "date_basis",
    "cohort_or_attribution_basis",
    "completeness_or_maturity_policy",
    "exclusions",
    "reconciliation_source",
    "effective_from",
    "effective_to",
)


def fingerprint_outcome_definition(outcome: OutcomeDefinition) -> str:
    """Deterministic SHA-256 fingerprint of all calculation-relevant
    outcome-definition fields. Changing any of these changes the fingerprint.

    Does NOT include: review notes, approval status, role, inclusion flags,
    value_weight, value_currency, source_column (source_column is a data
    linkage detail, not a business definition)."""
    payload: Dict[str, object] = {}
    for field_name in _FINGERPRINT_FIELDS:
        value = getattr(outcome, field_name, "")
        # Normalise None/empty for deterministic output
        if value is None:
            value = ""
        elif isinstance(value, tuple):
            value = sorted(str(v) for v in value)
        payload[field_name] = value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_definition_fields() -> Tuple[str, ...]:
    """Fields that must be non-blank for an outcome to be approvable."""
    return (
        "outcome_id",
        "product",
        "segment",
        "metric",
        "metric_key",
        "source_column",
        "unit",
        "aggregation_type",
        "event_definition",
        "cohort_or_attribution_basis",
        "completeness_or_maturity_policy",
        "reconciliation_source",
        "business_owner",
    )


def validate_outcome_definition_for_approval(outcome: OutcomeDefinition) -> List[str]:
    """Return a list of human-readable issues that prevent this outcome from
    being approved. Empty list means the definition is complete enough for
    approval review (it does NOT mean approval is automatically granted -
    that still requires an OutcomeApproval record)."""
    issues: List[str] = []
    for field_name in _required_definition_fields():
        value = getattr(outcome, field_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            issues.append(
                f"Required definition field '{field_name}' is missing or blank"
            )
    if outcome.metric_key == "custom" and not outcome.unit:
        issues.append("Custom-metric outcomes must have an explicit unit set")
    return issues


# ---------------------------------------------------------------------------
# Approval matching helpers (REQ-OUT-002)
# ---------------------------------------------------------------------------


def outcome_approval_matches_definition(
    outcome: OutcomeDefinition,
    approval: OutcomeApproval,
) -> bool:
    """True if the approval's fingerprint matches the outcome's current definition.

    A False result means the definition has changed since approval was granted
    — the approval is stale for this definition."""
    current_fingerprint = fingerprint_outcome_definition(outcome)
    return (
        approval.outcome_id == outcome.outcome_id
        and approval.definition_fingerprint == current_fingerprint
    )


def outcome_is_approved_for_use(
    outcome: OutcomeDefinition,
    approval: Optional[OutcomeApproval],
    requested_use: str,
    *,
    market: Optional[str] = None,
    product: Optional[str] = None,
    segment: Optional[str] = None,
    as_of: Optional[str] = None,
) -> bool:
    """True if the outcome has a matching, active approval that includes the
    requested use within the given scope.

    Returns False (never raises) when:
    - approval is None
    - approval status is not 'approved'
    - approval has expired
    - approval fingerprint doesn't match
    - requested use is not in allowed_uses
    - scope doesn't match"""
    if approval is None:
        return False
    if not approval.is_active(as_of=as_of):
        return False
    if not outcome_approval_matches_definition(outcome, approval):
        return False
    if not approval.allows_use(requested_use):
        return False
    if not approval.matches_scope(market=market, product=product, segment=segment):
        return False
    return True


class OutcomeApprovalBlockedError(RuntimeError):
    """Raised when official outcome use is blocked by missing/stale/rejected/
    expired/wrong-scope approval."""


def require_outcome_approval(
    outcome: OutcomeDefinition,
    approval: Optional[OutcomeApproval],
    requested_use: str,
    **scope: Optional[str],
) -> None:
    """Raise OutcomeApprovalBlockedError unless the outcome has a matching,
    active approval for the requested use.

    The error message names the specific reason (missing, stale, expired,
    wrong scope, use not allowed) so callers can surface it clearly."""
    if approval is None:
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' has no approval record. "
            f"Official use '{requested_use}' is blocked."
        )
    if not approval.is_active():
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' approval status is "
            f"'{approval.status}'. Official use '{requested_use}' is blocked."
        )
    if not outcome_approval_matches_definition(outcome, approval):
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' definition has changed since "
            f"approval was granted. Official use '{requested_use}' is blocked — "
            f"the approval is stale."
        )
    if not approval.allows_use(requested_use):
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' is approved for "
            f"{sorted(approval.allowed_uses)} but not for '{requested_use}'."
        )
    if not approval.matches_scope(**scope):
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' approval scope does not cover "
            f"the requested {scope}."
        )


# ---------------------------------------------------------------------------
# Bulk resolution helpers
# ---------------------------------------------------------------------------


def resolve_approvals_by_outcome_id(
    approvals: List[OutcomeApproval],
) -> Dict[str, OutcomeApproval]:
    """Index approvals by outcome_id. When multiple approvals exist for the
    same outcome_id, the most recently approved one wins (simple last-wins
    resolution — callers with more complex needs should filter first)."""
    by_id: Dict[str, OutcomeApproval] = {}
    for approval in sorted(approvals, key=lambda a: a.approved_at or ""):
        by_id[approval.outcome_id] = approval
    return by_id


def approved_outcome_ids_for_use(
    outcomes: List[OutcomeDefinition],
    approvals: List[OutcomeApproval],
    requested_use: str,
    **scope: Optional[str],
) -> List[str]:
    """Return outcome_ids that have an active, matching approval for the
    requested use. Outcome IDs without any approval are filtered out."""
    approval_by_id = resolve_approvals_by_outcome_id(approvals)
    result: List[str] = []
    for outcome in outcomes:
        approval = approval_by_id.get(outcome.outcome_id)
        if outcome_is_approved_for_use(outcome, approval, requested_use, **scope):
            result.append(outcome.outcome_id)
    return result


def legacy_unapproved_approval(outcome_id: str) -> OutcomeApproval:
    """Create a `legacy_unapproved` approval record for a single outcome_id.
    Used when importing a legacy project bundle that has no outcome approvals,
    so the outcome is explicitly marked rather than silently treated as
    approved."""
    return OutcomeApproval(
        approval_id=f"legacy-{outcome_id}",
        outcome_id=outcome_id,
        definition_fingerprint="",
        status="legacy_unapproved",
        allowed_uses=(),
        notes="Auto-generated for legacy project import — no approval on file.",
    )
