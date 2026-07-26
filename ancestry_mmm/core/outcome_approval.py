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
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from .outcomes import OutcomeDefinition, AGGREGATION_TYPES, DATE_BASIS_VALUES, METRIC_REGISTRY

# ---------------------------------------------------------------------------
# G2A.7a.2 date normalisation (REQ-OUT-002 section 7.4)
# ---------------------------------------------------------------------------

# Regex for ISO timestamps with optional timezone: 2026-07-26T10:30:00Z,
# 2026-07-26T10:30:00+01:00, 2026-07-26T10:30:00-05:00, or naive
# 2026-07-26T10:30:00. Also matches date-only YYYY-MM-DD.
_ISO_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})"
    r"(?:[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def _normalise_datetime(value: str) -> datetime:
    """Parse a date or timestamp string into a timezone-aware UTC datetime.

    Supports:
    - ``YYYY-MM-DD`` (treated as UTC midnight)
    - ISO timestamps with ``Z`` suffix
    - ISO timestamps with ``+HH:MM`` or ``-HH:MM`` offset
    - ISO timestamps with ``+HHMM`` (no colon) offset
    - timezone-naive ISO timestamps (treated as UTC — documented policy:
      a naive timestamp carries no offset information so we normalise to
      UTC rather than guessing a local timezone)

    Raises ValueError for unparseable input so callers can block rather
    than silently default.

    G2A.7a.2: this is the single normalisation point all approval-date
    comparisons pass through — no caller should compare raw
    `datetime.fromisoformat()` values directly, because aware-vs-naive
    comparison raises TypeError.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid date value: {value!r}")
    value = value.strip()
    m = _ISO_TS_RE.match(value)
    if not m:
        # Fall back to fromisoformat for other ISO shapes Python accepts
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    date_part = m.group(1)
    time_part = m.group(2)
    tz_part = m.group(3)

    if time_part is None:
        # Date-only: treat as UTC midnight
        dt = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        dt_str = f"{date_part}T{time_part}"
        # Expand +HHMM to +HH:MM for fromisoformat compatibility
        if tz_part and len(tz_part) == 5 and ":" not in tz_part:
            tz_part = f"{tz_part[:3]}:{tz_part[3:]}"
        if tz_part and tz_part != "Z":
            dt_str += tz_part
        elif tz_part == "Z":
            dt_str += "+00:00"
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _normalise_date_only(value: str) -> datetime:
    """Like _normalise_datetime but always truncates to date midnight UTC.
    Used for date-only comparison where timestamps should be compared at
    day granularity."""
    dt = _normalise_datetime(value)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

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
    status: str = "draft"
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
        """True if this approval is currently in effect (approved, not expired,
        not future-dated).

        G2A.7a: when `as_of` is omitted, compares against the current UTC date.
        Expiry is evaluated as `as_of >= expires_at` — the approval expires at
        the start of the expiry date (inclusive).

        G2A.7a.1 (REQ-OUT-002 section 7.4): dates are parsed, not compared as
        raw strings, and a future-dated `approved_at` (relative to `as_of`)
        does not authorise current use - an approval recorded for a future
        effective date must not be treated as already in force today.

        G2A.7a.2: all datetime comparisons go through `_normalise_datetime`
        so timezone-aware timestamps (e.g. ``2026-07-26T10:30:00Z``) and
        timezone-naive values are compared safely without TypeError."""
        if self.status != "approved":
            return False
        effective_as_of = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            as_of_dt = _normalise_datetime(effective_as_of)
        except (ValueError, TypeError):
            return False
        # Validate dates for approved records. `approved_at` presence itself
        # is enforced by `_validate_approved_record` in the full gate chain
        # (outcome_is_approved_for_use / require_outcome_approval /
        # find_matching_outcome_approval); here we only validate the dates
        # that ARE present, so `is_active()` stays a pure "is this record
        # currently in force" question, not a completeness check.
        approved_at_dt = None
        if self.approved_at:
            try:
                approved_at_dt = _normalise_datetime(self.approved_at)
            except (ValueError, TypeError):
                return False
            if approved_at_dt > as_of_dt:
                return False
        if self.expires_at is not None:
            try:
                expires_at_dt = _normalise_datetime(self.expires_at)
            except (ValueError, TypeError):
                return False
            if approved_at_dt is not None and expires_at_dt <= approved_at_dt:
                return False
            if as_of_dt >= expires_at_dt:
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
        require_explicit_scoped_dimensions: bool = False,
    ) -> bool:
        """True if this approval's scope covers the requested market/product/segment.

        None scope on the approval means "unrestricted" for that dimension.
        None passed by the caller means "don't filter on that dimension" -
        unless `require_explicit_scoped_dimensions=True` (G2A.7a.1, REQ-OUT-002
        section 7.3), in which case a caller omitting a dimension the
        approval itself scopes to (market_scope/product_scope/segment_scope
        not None) fails closed instead of silently matching. Official-use
        resolution (`find_matching_outcome_approval`) always passes this;
        the default stays permissive for exploratory/display callers that
        may not always have every dimension available."""
        if self.market_scope is not None:
            if market is None:
                if require_explicit_scoped_dimensions:
                    return False
            elif market not in self.market_scope:
                return False
        if self.product_scope is not None:
            if product is None:
                if require_explicit_scoped_dimensions:
                    return False
            elif product not in self.product_scope:
                return False
        if self.segment_scope is not None:
            if segment is None:
                if require_explicit_scoped_dimensions:
                    return False
            elif segment not in self.segment_scope:
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
    """Fields that must be non-blank for an outcome to be approvable (G2A.7a)."""
    return (
        "outcome_id",
        "definition_version",
        "product",
        "segment",
        "metric",
        "metric_key",
        "source_column",
        "unit",
        "aggregation_type",
        "event_definition",
        "date_basis",
        "cohort_or_attribution_basis",
        "completeness_or_maturity_policy",
        "exclusions",
        "reconciliation_source",
        "business_owner",
    )


def validate_outcome_definition_for_approval(outcome: OutcomeDefinition) -> List[str]:
    """Return a list of human-readable issues that prevent this outcome from
    being approved for ANY use. Empty list means the definition is complete
    enough for approval review (it does NOT mean approval is automatically
    granted - that still requires an OutcomeApproval record).

    G2A.7a: also validates vocabulary, effective-date ordering, custom-metric
    unit, and non-empty fingerprint.

    G2A.7a.1 (REQ-OUT-002 fix): metric-registry restrictions on optimisation
    eligibility and CPA-denominator validity are deliberately NOT checked
    here - a rate metric (e.g. `fh_net_billthrough_rate`) is not allowed as
    an optimisation target or a CPA denominator, but that must not make it
    unapprovable for every other use (`model_fit`, `technical_reporting`,
    ...). See `validate_outcome_for_requested_use` for those use-scoped
    restrictions."""
    issues: List[str] = []
    # Required fields
    for field_name in _required_definition_fields():
        value = getattr(outcome, field_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            issues.append(
                f"Required definition field '{field_name}' is missing or blank"
            )
    # date_basis: blank is invalid (must be explicit or "not_applicable")
    if outcome.date_basis is None or (isinstance(outcome.date_basis, str) and not outcome.date_basis.strip()):
        issues.append("date_basis must be an explicit value from DATE_BASIS_VALUES or 'not_applicable'")
    elif outcome.date_basis not in DATE_BASIS_VALUES and outcome.date_basis != "not_applicable":
        issues.append(f"date_basis '{outcome.date_basis}' is not a recognised value; must be one of {DATE_BASIS_VALUES} or 'not_applicable'")
    # aggregation_type vocabulary
    if outcome.aggregation_type and outcome.aggregation_type not in AGGREGATION_TYPES:
        issues.append(f"aggregation_type '{outcome.aggregation_type}' is not one of {AGGREGATION_TYPES}")
    # Custom metric must have explicit unit
    if outcome.metric_key == "custom" and not outcome.unit:
        issues.append("Custom-metric outcomes must have an explicit unit set")
    # Effective-date ordering
    if outcome.effective_from and outcome.effective_to:
        try:
            from_dt = datetime.fromisoformat(outcome.effective_from)
            to_dt = datetime.fromisoformat(outcome.effective_to)
            if from_dt >= to_dt:
                issues.append("effective_from must be before effective_to")
        except (ValueError, TypeError):
            issues.append("effective_from/effective_to must be valid ISO dates")
    # Non-empty fingerprint
    fp = fingerprint_outcome_definition(outcome)
    if not fp or len(fp) < 16:
        issues.append("Outcome definition fingerprint is missing or too short")
    return issues


def validate_outcome_for_requested_use(outcome: OutcomeDefinition, requested_use: str) -> List[str]:
    """Requested-use-aware metric restrictions, separate from definition
    completeness (G2A.7a.1, REQ-OUT-002 fix). A metric invalid for one use
    (a rate metric as an optimisation target or a CPA denominator) must not
    make the outcome unapprovable for every other use - an NBT rate may
    still be approved for `model_fit` or `technical_reporting`.

    `requested_use` accepts every value in `OUTCOME_USES` (checked here only
    for `"optimisation"`) plus the pseudo-use `"cpa_denominator"` - not an
    approvable use in its own right, but a recognised value for this
    function only, used wherever an outcome is about to be divided into as a
    CPA denominator."""
    issues: List[str] = []
    reg = METRIC_REGISTRY.get(outcome.metric_key)
    if reg is None:
        return issues
    if requested_use == "optimisation" and not reg.allowed_in_optimiser:
        issues.append(
            f"Metric '{outcome.metric_key}' is not allowed as an optimisation "
            "target per the metric registry"
        )
    if requested_use == "cpa_denominator" and not reg.allowed_in_cpa:
        issues.append(
            f"Metric '{outcome.metric_key}' is not valid as a CPA denominator "
            "per the metric registry"
        )
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


def _validate_approved_record(approval: OutcomeApproval) -> List[str]:
    """G2A.7a: validate that an 'approved' record has required fields."""
    issues: List[str] = []
    if not approval.approval_id:
        issues.append("approval_id is required for an approved record")
    if not approval.outcome_id:
        issues.append("outcome_id is required")
    if not approval.definition_fingerprint:
        issues.append("definition_fingerprint is required")
    if not approval.allowed_uses:
        issues.append("at least one allowed_use is required")
    if not approval.approved_by:
        issues.append("approved_by is required")
    if not approval.approved_at:
        issues.append("approved_at is required")
    else:
        try:
            _normalise_datetime(approval.approved_at)
        except (ValueError, TypeError):
            issues.append(f"approved_at '{approval.approved_at}' is not a valid ISO date")
    if approval.expires_at is not None:
        try:
            _normalise_datetime(approval.expires_at)
        except (ValueError, TypeError):
            issues.append(f"expires_at '{approval.expires_at}' is not a valid ISO date")
        else:
            # Cross-validate: expiry must be after approval
            if approval.approved_at:
                try:
                    approved_dt = _normalise_datetime(approval.approved_at)
                    expires_dt = _normalise_datetime(approval.expires_at)
                    if expires_dt <= approved_dt:
                        issues.append(
                            f"expires_at '{approval.expires_at}' is not after "
                            f"approved_at '{approval.approved_at}'"
                        )
                except (ValueError, TypeError):
                    pass  # already reported above
    return issues


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

    G2A.7a: also validates that the outcome definition is complete and the
    approval record itself is valid. A matching fingerprint on an incomplete
    definition or invalid approval record is not sufficient.

    Returns False (never raises) when:
    - approval is None
    - approval status is not 'approved'
    - approval has expired
    - approval fingerprint doesn't match
    - requested use is not in allowed_uses
    - scope doesn't match
    - outcome definition is incomplete
    - approval record is invalid"""
    if approval is None:
        return False
    if approval.status != "approved":
        return False
    # G2A.7a: validate the approval record itself
    if _validate_approved_record(approval):
        return False
    # G2A.7a: definition must be complete
    if validate_outcome_definition_for_approval(outcome):
        return False
    # G2A.7a.1 (REQ-OUT-002 fix): requested-use-aware metric restrictions
    if validate_outcome_for_requested_use(outcome, requested_use):
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

    G2A.7a: first validates definition completeness, then checks approval.
    The error message names the specific reason (missing, stale, expired,
    wrong scope, use not allowed, incomplete definition) so callers can
    surface it clearly."""
    # G2A.7a: definition must be complete first
    defn_issues = validate_outcome_definition_for_approval(outcome)
    if defn_issues:
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' definition is incomplete for "
            f"official use '{requested_use}': {'; '.join(defn_issues)}"
        )
    # G2A.7a.1 (REQ-OUT-002 fix): requested-use-aware metric restrictions
    # (e.g. a rate metric is not a valid optimisation target) — separate
    # from general definition completeness, so a metric restricted for THIS
    # use does not block every other use.
    use_issues = validate_outcome_for_requested_use(outcome, requested_use)
    if use_issues:
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' is not valid for use "
            f"'{requested_use}': {'; '.join(use_issues)}"
        )
    if approval is None:
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' has no approval record. "
            f"Official use '{requested_use}' is blocked."
        )
    if approval.status != "approved":
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' approval status is "
            f"'{approval.status}'. Official use '{requested_use}' is blocked."
        )
    record_issues = _validate_approved_record(approval)
    if record_issues:
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' approval record is invalid: "
            f"{'; '.join(record_issues)}"
        )
    if not approval.is_active():
        raise OutcomeApprovalBlockedError(
            f"Outcome '{outcome.outcome_id}' approval is not active "
            f"(status={approval.status}, expires={approval.expires_at}). "
            f"Official use '{requested_use}' is blocked."
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
# Multi-approval resolution (G2A.7a)
# ---------------------------------------------------------------------------


def find_matching_outcome_approval(
    outcome: OutcomeDefinition,
    approvals: List[OutcomeApproval],
    requested_use: str,
    *,
    market: Optional[str] = None,
    product: Optional[str] = None,
    segment: Optional[str] = None,
    as_of: Optional[str] = None,
) -> Optional[OutcomeApproval]:
    """Find one matching approval from a list of candidates for an outcome.

    Filters candidates by: outcome definition completeness, requested-use
    metric restrictions, outcome_id, active status, fingerprint match,
    requested use, and scope (fail-closed: a caller omitting a dimension
    the approval itself scopes to does not match). If multiple valid
    candidates remain, returns the one with the latest approved_at
    (deterministic tiebreak).

    G2A.7a: replaces the simple last-wins resolve_approvals_by_outcome_id
    for use-site resolution — the old approach could let a later narrow or
    rejected record hide a valid record for a different scope.

    G2A.7a.1 (REQ-OUT-002 section 7.1, 7.2, 7.3): a matching fingerprint on
    an incomplete definition, or on a definition restricted from this
    requested use (e.g. a rate metric requested for optimisation), never
    authorises official use — validated here, not only by the single-
    approval helpers above, since this is the resolver the real planning/
    optimisation gate actually calls."""
    if validate_outcome_definition_for_approval(outcome):
        return None
    if validate_outcome_for_requested_use(outcome, requested_use):
        return None
    candidates = [
        a for a in approvals
        if a.outcome_id == outcome.outcome_id
        and a.status == "approved"
        and not _validate_approved_record(a)
        and a.is_active(as_of=as_of)
        and a.definition_fingerprint == fingerprint_outcome_definition(outcome)
        and a.allows_use(requested_use)
        and a.matches_scope(
            market=market, product=product, segment=segment,
            require_explicit_scoped_dimensions=True,
        )
    ]
    if not candidates:
        return None
    # Deterministic tiebreak: latest approved_at
    candidates.sort(key=lambda a: a.approved_at or "", reverse=True)
    return candidates[0]


def resolve_approvals_by_outcome_id(
    approvals: List[OutcomeApproval],
) -> Dict[str, OutcomeApproval]:
    """Index approvals by outcome_id. When multiple approvals exist for the
    same outcome_id, the most recently approved one wins.

    Prefer `find_matching_outcome_approval` for use-site checks where
    scope matters. This flat index is appropriate for listing/discovery."""
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
    requested use, using multi-approval resolution (find_matching_outcome_approval)."""
    result: List[str] = []
    for outcome in outcomes:
        if find_matching_outcome_approval(
            outcome, approvals, requested_use, **scope,
        ):
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
