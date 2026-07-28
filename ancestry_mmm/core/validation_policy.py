"""
Validation-policy and approval-readiness foundation (REQ-VAL-001).

PR 51C: Improved semantics with pass/review/fail bands, model-identity
binding on ValidationResult, waiver expiry validation, and staleness
based on dependency mismatch (not just age).

PR 62B: ValidationEvidenceContext, matches_evidence(), strict waiver
binding, canonical waiver payload, policy-config rejection, operational
scope matcher, and readiness schema v2.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import arviz as az

if TYPE_CHECKING:
    from .model_identity import ModelIdentity


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_INTENDED_USES: tuple[str, ...] = (
    "model_approval",
    "exploratory_review",
    "planning",
    "optimisation",
    "curve_bank",
    "backtest",
)

VALID_MODEL_TYPES: tuple[str, ...] = (
    "shared",
    "market_specific",
    "all_models",
)


# ---------------------------------------------------------------------------
# ValidationEvidenceContext — PR 62B
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationEvidenceContext:
    """Typed context that every validation result must match.

    PR 62B: Introduced to replace loose string comparisons. Every evidence
    binding (model identity, policy identity, gate fingerprint, diagnostics
    identity) is verified against this context before a result is accepted
    as current.

    Parameters
    ----------
    model_identity : ModelIdentity
        The model run's canonical identity.
    policy : ThresholdPolicy
        The policy being evaluated.
    diagnostic_artefact_id : str
        Identifier of the diagnostic artefact.
    diagnostic_artefact_fingerprint : str
        Fingerprint of the diagnostic artefact.
    model_type : str
        Model type, e.g. ``"shared"`` or ``"market_specific"``.
    market : str | None
        Optional market scope.
    intended_use : str
        Intended use for this evaluation. Must be one of
        ``VALID_INTENDED_USES``.
    """

    model_identity: ModelIdentity
    policy: ThresholdPolicy
    diagnostic_artefact_id: str
    diagnostic_artefact_fingerprint: str
    model_type: str = "all_models"
    market: Optional[str] = None
    intended_use: str = "model_approval"

    def __post_init__(self) -> None:
        if not self.diagnostic_artefact_id or not self.diagnostic_artefact_id.strip():
            raise ValueError(
                "ValidationEvidenceContext.diagnostic_artefact_id must be non-blank"
            )
        if (
            not self.diagnostic_artefact_fingerprint
            or not self.diagnostic_artefact_fingerprint.strip()
        ):
            raise ValueError(
                "ValidationEvidenceContext.diagnostic_artefact_fingerprint "
                "must be non-blank"
            )
        if self.intended_use not in VALID_INTENDED_USES:
            raise ValueError(
                f"Invalid intended_use: {self.intended_use!r}. "
                f"Must be one of {VALID_INTENDED_USES}"
            )
        if self.model_type not in VALID_MODEL_TYPES:
            raise ValueError(
                f"Invalid model_type: {self.model_type!r}. "
                f"Must be one of {VALID_MODEL_TYPES}"
            )

    def is_official(self) -> bool:
        """True when this context is for an official (non-exploratory) use."""
        return self.intended_use != "exploratory_review"


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationWaiverReference:
    """An approved exception to a specific gate.

    A waiver does not change the gate's threshold — it records that a
    responsible party explicitly accepted the failure.

    PR 51C: ``expiry`` is validated during readiness evaluation.
    An expired, revoked, or mismatched waiver does not unblock a gate.

    PR 62B: Evidence bindings (model_identity_fingerprint,
    policy_fingerprint, gate_fingerprint, diagnostic_artefact_fingerprint,
    original_result_status) are enforced for official waivers. An unbound
    legacy waiver cannot unblock official readiness.
    """

    waiver_id: str
    approved_by: str
    approved_at: datetime
    reason: str
    gate_name: str
    expiry: Optional[datetime] = None
    superseded_by: Optional[str] = None
    # PR 56E: waiver binding fields
    model_identity_fingerprint: str = ""
    policy_fingerprint: str = ""
    gate_fingerprint: str = ""
    diagnostic_artefact_fingerprint: str = ""
    original_result_status: str = ""

    def is_active(self, as_of: Optional[datetime] = None) -> bool:
        """Check whether this waiver is currently active.

        A waiver is active if:
        - not superseded
        - not expired (if an expiry is set)
        """
        if self.superseded_by:
            return False
        if self.expiry is not None:
            as_of = as_of or datetime.now(timezone.utc)
            if as_of >= self.expiry:
                return False
        return True

    def is_officially_bound(self) -> bool:
        """True if all evidence-binding fields are present.

        An unbound legacy waiver cannot unblock official readiness."""
        return bool(
            self.model_identity_fingerprint
            and self.model_identity_fingerprint.strip()
            and self.policy_fingerprint
            and self.policy_fingerprint.strip()
            and self.gate_fingerprint
            and self.gate_fingerprint.strip()
            and self.diagnostic_artefact_fingerprint
            and self.diagnostic_artefact_fingerprint.strip()
            and self.original_result_status
            and self.original_result_status.strip()
        )

    def matches_evidence(self, context: ValidationEvidenceContext) -> bool:
        """True if this waiver's bindings match the given evidence context.

        An unbound waiver always returns False."""
        if not self.is_officially_bound():
            return False
        # Check model identity fingerprint
        if self.model_identity_fingerprint != context.model_identity.fingerprint():
            return False
        # Check policy fingerprint
        if self.policy_fingerprint != context.policy.fingerprint():
            return False
        # Check gate fingerprint (gate must exist in policy)
        policy_gate = context.policy.get_gate(self.gate_name)
        if policy_gate is None:
            return False
        if self.gate_fingerprint != policy_gate.fingerprint():
            return False
        # Check diagnostics fingerprint
        if (
            self.diagnostic_artefact_fingerprint
            != context.diagnostic_artefact_fingerprint
        ):
            return False
        return True

    def to_waiver_payload(self) -> dict:
        """Canonical waiver payload used by fingerprinting, serialisation
        and deserialisation. PR 62B: includes every evidence-binding field
        plus approval time."""
        return {
            "waiver_id": self.waiver_id,
            "gate_name": self.gate_name,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat(),
            "reason": self.reason,
            "expiry": self.expiry.isoformat() if self.expiry else None,
            "superseded_by": self.superseded_by,
            "model_identity_fingerprint": self.model_identity_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "gate_fingerprint": self.gate_fingerprint,
            "diagnostic_artefact_fingerprint": self.diagnostic_artefact_fingerprint,
            "original_result_status": self.original_result_status,
        }

    @classmethod
    def from_waiver_payload(cls, d: dict) -> "ValidationWaiverReference":
        """Restore a waiver from a canonical payload dict."""
        return cls(
            waiver_id=d["waiver_id"],
            approved_by=d["approved_by"],
            approved_at=datetime.fromisoformat(d["approved_at"]),
            reason=d["reason"],
            gate_name=d["gate_name"],
            expiry=datetime.fromisoformat(d["expiry"]) if d.get("expiry") else None,
            superseded_by=d.get("superseded_by"),
            model_identity_fingerprint=d.get("model_identity_fingerprint", ""),
            policy_fingerprint=d.get("policy_fingerprint", ""),
            gate_fingerprint=d.get("gate_fingerprint", ""),
            diagnostic_artefact_fingerprint=d.get(
                "diagnostic_artefact_fingerprint", ""
            ),
            original_result_status=d.get("original_result_status", ""),
        )


@dataclass(frozen=True)
class ValidationGate:
    """One validation gate within a policy.

    PR 51C: Supports explicit pass/review/fail bands via
    ``acceptable_range`` (pass) and optional ``review_range`` (review).
    Values within ``acceptable_range`` pass; values outside
    ``acceptable_range`` but within ``review_range`` are review items;
    values outside ``review_range`` fail.

    Parameters
    ----------
    name : str
        Machine-readable identifier, e.g. ``convergence_rhat``.
    description : str
        Human-readable description of what this gate checks.
    evaluator_id : str
        Identifier for the evaluator function that computes this gate.
    scope : str
        What the gate applies to, e.g. ``all_models``, ``model_a_only``.
    acceptable_range : tuple[float, float] | None
        Lower and upper bounds for a passing result. ``None`` means
        pass/fail is based on a boolean check from the evaluator.
    review_range : tuple[float, float] | None
        Lower and upper bounds for a review (warning) result. Values
        outside ``acceptable_range`` but inside ``review_range`` get
        review status. ``None`` means no review band — values outside
        acceptable_range fail directly.
    direction : str
        ``"lower_is_better"`` (e.g. R-hat) or ``"higher_is_better"``
        (e.g. ESS, coverage). Determines which side of the range is
        pass vs fail.
    units : str
        Human-readable units, e.g. ``"R-hat"``, ``"n_eff"``, ``"%"``.
    blocking : bool
        If True, a failing result on this gate blocks official approval.
    waivable : bool
        If True, a waiver can override a failure.
    required : bool
        If True, a result for this gate *must* be present. A missing
        required gate blocks official approval.
    """

    name: str
    description: str
    evaluator_id: str = ""
    scope: str = "all_models"
    acceptable_range: Optional[tuple[float, float]] = None
    review_range: Optional[tuple[float, float]] = None
    direction: str = "lower_is_better"
    units: str = ""
    blocking: bool = True
    waivable: bool = False
    required: bool = True
    expected_state: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.direction not in ("lower_is_better", "higher_is_better"):
            raise ValueError(f"Invalid direction: {self.direction!r}")
        if self.review_range is not None and self.acceptable_range is not None:
            lo, hi = self.acceptable_range
            rlo, rhi = self.review_range
            if self.direction == "lower_is_better":
                if not (hi <= rhi):
                    raise ValueError(
                        f"review_range upper bound ({rhi}) must be >= "
                        f"acceptable_range upper bound ({hi}) for "
                        "lower_is_better"
                    )
            else:
                if not (lo >= rlo):
                    raise ValueError(
                        f"review_range lower bound ({rlo}) must be <= "
                        f"acceptable_range lower bound ({lo}) for "
                        "higher_is_better"
                    )

    def fingerprint(self) -> str:
        """Deterministic fingerprint of this gate's definition."""
        payload = {
            "name": self.name,
            "evaluator_id": self.evaluator_id,
            "scope": self.scope,
            "acceptable_range": self.acceptable_range,
            "review_range": self.review_range,
            "direction": self.direction,
            "blocking": self.blocking,
            "waivable": self.waivable,
            "required": self.required,
            "expected_state": self.expected_state,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ThresholdPolicy:
    """A versioned set of validation gates.

    PR 51C: Validates that:
    - policy_id is non-blank
    - version is non-blank
    - owner is non-blank
    - gate names are unique
    - scope is non-blank
    - approval_date is set

    Parameters
    ----------
    policy_id : str
        Unique identifier, e.g. ``val-pol-001``.
    version : str
        Semantic version string, e.g. ``1.0.0``.
    scope : str
        What models this policy applies to.
    gates : list[ValidationGate]
        The gates that make up this policy.
    owner : str
        Who owns/maintains the policy (individual or team).
    approval_date : datetime
        When the policy was approved.
    expiry : datetime | None
        Optional expiry date. An expired policy blocks official approval.
    supersedes : str | None
        Optional reference to a policy this one replaces.
    superseded_by : str | None
        Optional reference to a newer policy that replaces this one.
    """

    policy_id: str
    version: str
    scope: str
    gates: List[ValidationGate] = field(default_factory=list)
    owner: str = ""
    approval_date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expiry: Optional[datetime] = None
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.policy_id or not self.policy_id.strip():
            raise ValueError("ThresholdPolicy.policy_id must be non-blank")
        if not self.version or not self.version.strip():
            raise ValueError("ThresholdPolicy.version must be non-blank")
        if not self.owner or not self.owner.strip():
            raise ValueError("ThresholdPolicy.owner must be non-blank")
        if not self.scope or not self.scope.strip():
            raise ValueError("ThresholdPolicy.scope must be non-blank")
        # Check unique gate names
        names = [g.name for g in self.gates]
        if len(names) != len(set(names)):
            dupes = [n for n in names if names.count(n) > 1]
            raise ValueError(
                f"ThresholdPolicy gates contain duplicate names: {sorted(set(dupes))}"
            )

    def is_expired(self, as_of: Optional[datetime] = None) -> bool:
        """Check whether this policy has expired."""
        if self.expiry is None:
            return False
        as_of = as_of or datetime.now(timezone.utc)
        return as_of >= self.expiry

    def get_gate(self, name: str) -> Optional[ValidationGate]:
        """Look up a gate by name."""
        for g in self.gates:
            if g.name == name:
                return g
        return None

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint of this policy."""
        payload = {
            "policy_id": self.policy_id,
            "version": self.version,
            "scope": self.scope,
            "owner": self.owner,
            "approval_date": self.approval_date.isoformat()
            if self.approval_date
            else None,
            "expiry": self.expiry.isoformat() if self.expiry else None,
            "gates": [g.fingerprint() for g in self.gates],
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


VALIDATION_STATUS_VALUES = ("pass", "review", "fail")


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of evaluating one gate.

    PR 51C: Added model identity binding (``model_run_id``,
    ``data_fingerprint``, ``model_spec_fingerprint``,
    ``posterior_fingerprint``, ``policy_id``, ``policy_version``,
    ``gate_fingerprint``). A result is stale when its identity
    bindings do not match the current model or policy.

    ``passed`` is kept as a property for backward compatibility:
    ``True`` when ``status`` is ``"pass"``, ``False`` otherwise.

    Parameters
    ----------
    gate_name : str
        Name of the gate that was evaluated.
    status : str
        One of ``"pass"``, ``"review"``, ``"fail"``.
    value : float | None
        Numeric value that was checked (e.g. max R-hat). ``None`` for
        boolean checks.
    message : str
        Human-readable summary of the result.
    artefact_id : str | None
        Reference to supporting evidence (scorecard fingerprint, etc.).
    evaluated_at : datetime
        When the evaluation was performed.
    model_run_id : str
        Model run ID this result was evaluated against.
    data_fingerprint : str
        Data fingerprint this result was evaluated against.
    model_spec_fingerprint : str
        Model spec fingerprint this result was evaluated against.
    posterior_fingerprint : str
        Posterior fingerprint this result was evaluated against.
    policy_id : str
        Policy ID this result was evaluated under.
    policy_version : str
        Policy version this result was evaluated under.
    gate_fingerprint : str
        Fingerprint of the gate definition at evaluation time.
    model_identity_fingerprint : str
        Fingerprint of the ModelIdentity at evaluation time.
    diagnostic_artefact_fingerprint : str
        Fingerprint of the diagnostic artefact at evaluation time.
    """

    gate_name: str
    status: str = "fail"  # "pass", "review", or "fail"
    value: Optional[float] = None
    message: str = ""
    artefact_id: Optional[str] = None
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    model_run_id: str = ""
    data_fingerprint: str = ""
    model_spec_fingerprint: str = ""
    posterior_fingerprint: str = ""
    policy_id: str = ""
    policy_version: str = ""
    gate_fingerprint: str = ""
    model_identity_fingerprint: str = ""
    diagnostic_artefact_fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.status not in VALIDATION_STATUS_VALUES:
            raise ValueError(
                f"Invalid status: {self.status!r}. Must be one of {VALIDATION_STATUS_VALUES}"
            )

    @property
    def passed(self) -> bool:
        """Backward-compatible: True when status is ``pass``."""
        return self.status == "pass"

    def matches_identity(
        self,
        *,
        model_run_id: str,
        data_fingerprint: str,
        model_spec_fingerprint: str,
        posterior_fingerprint: str,
        policy_id: str,
        policy_version: str,
    ) -> bool:
        """Check whether this result was evaluated against the given identity."""
        return (
            self.model_run_id == model_run_id
            and self.data_fingerprint == data_fingerprint
            and self.model_spec_fingerprint == model_spec_fingerprint
            and self.posterior_fingerprint == posterior_fingerprint
            and self.policy_id == policy_id
            and self.policy_version == policy_version
        )

    def is_stale_for(
        self,
        *,
        model_run_id: str,
        data_fingerprint: str,
        model_spec_fingerprint: str,
        posterior_fingerprint: str,
        policy_id: str,
        policy_version: str,
    ) -> bool:
        """A result is stale when its identity bindings do not match.

        This replaces the age-based staleness check. A result is stale
        if any identity field differs between the result and the current
        model/policy. An empty-string identity field on either side
        causes a staleness result (incomplete binding is stale).
        """
        if not all(
            [
                model_run_id,
                data_fingerprint,
                model_spec_fingerprint,
                posterior_fingerprint,
                policy_id,
                policy_version,
            ]
        ):
            return True  # Missing identity = stale
        if not all(
            [
                self.model_run_id,
                self.data_fingerprint,
                self.model_spec_fingerprint,
                self.posterior_fingerprint,
                self.policy_id,
                self.policy_version,
            ]
        ):
            return True  # Result not fully bound = stale
        return not self.matches_identity(
            model_run_id=model_run_id,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            policy_id=policy_id,
            policy_version=policy_version,
        )

    def matches_evidence(
        self,
        *,
        evidence_context: "ValidationEvidenceContext",
        gate: "ValidationGate",
    ) -> bool:
        """PR 62B: Verify every evidence binding matches the given context.

        Checks: model run ID, data fingerprint, model spec fingerprint,
        posterior fingerprint, model identity fingerprint, policy ID,
        policy version, gate fingerprint, diagnostics artefact ID and
        diagnostics fingerprint.

        A blank mandatory field on either side causes mismatch."""
        if not evidence_context.model_identity.is_complete():
            return False
        ctx = evidence_context

        # Check model identity bindings
        if self.model_run_id != ctx.model_identity.model_run_id:
            return False
        if self.data_fingerprint != ctx.model_identity.data_fingerprint:
            return False
        if self.model_spec_fingerprint != ctx.model_identity.model_spec_fingerprint:
            return False
        if self.posterior_fingerprint != ctx.model_identity.posterior_fingerprint:
            return False
        if self.model_identity_fingerprint != ctx.model_identity.fingerprint():
            return False

        # Check policy bindings
        if self.policy_id != ctx.policy.policy_id:
            return False
        if self.policy_version != ctx.policy.version:
            return False

        # Check gate fingerprint
        if self.gate_fingerprint != gate.fingerprint():
            return False

        # Check diagnostics bindings
        if self.diagnostic_artefact_fingerprint != ctx.diagnostic_artefact_fingerprint:
            return False

        # artefact_id on result should match the context's diagnostic_artefact_id
        if self.artefact_id != ctx.diagnostic_artefact_id:
            return False

        return True


@dataclass(frozen=True)
class ApprovalReadiness:
    """Immutable, auditable readiness artefact binding model identity,
    diagnostic evidence, policy definition, and gate results into a single
    fingerprinted proof.

    PR 56B: Extended to include artefacts IDs and fingerprints for every
    evidence component, plus deterministic ``fingerprint()``,
    ``to_dict()``, and ``from_dict()``.

    PR 62B: Schema v2 — added ``config_errors``, canonical waiver payload
    in fingerprint/serialisation, and strict evidence enforcement.

    Parameters
    ----------
    readiness_artefact_id : str
        Unique identifier for this readiness evaluation.
    policy_id : str
        The policy that was evaluated.
    policy_version : str
        Version of the policy.
    policy_fingerprint : str
        Fingerprint of the policy definition at evaluation time.
    model_identity_fingerprint : str
        Fingerprint of the ModelIdentity at evaluation time.
    diagnostic_artefact_id : str
        Identifier of the diagnostic artefact evaluated.
    diagnostic_artefact_fingerprint : str
        Fingerprint of the diagnostic artefact at evaluation time.
    gate_results : tuple[ValidationResult, ...]
        All gate results from the evaluation.
    blocking_failures : tuple[ValidationResult, ...]
        Gates that failed and are marked as blocking.
    review_items : tuple[ValidationResult, ...]
        Gates that failed but are not blocking (review-only).
    passes : tuple[ValidationResult, ...]
        Gates that passed.
    missing_required_gates : tuple[str, ...]
        Names of required gates for which no result was provided.
    waivers_applied : tuple[ValidationWaiverReference, ...]
        Waivers that were accepted for failing gates.
    evaluated_at : datetime
        When the evaluation was performed.
    overall_ready : bool
        True if no blocking failures, no missing required gates, no
        non-waivable failures, policy is not expired, and no config errors.
    schema_version : int
        Version of the readiness artefact schema.
    config_errors : tuple[str, ...]
        PR 62B: Policy configuration errors found before evaluation.
        When non-empty, no gates were evaluated and overall_ready is False.
    """

    readiness_artefact_id: str = ""
    policy_id: str = ""
    policy_version: str = ""
    policy_fingerprint: str = ""
    model_identity_fingerprint: str = ""
    diagnostic_artefact_id: str = ""
    diagnostic_artefact_fingerprint: str = ""
    gate_results: tuple[ValidationResult, ...] = field(default_factory=tuple)
    blocking_failures: tuple[ValidationResult, ...] = field(default_factory=tuple)
    review_items: tuple[ValidationResult, ...] = field(default_factory=tuple)
    passes: tuple[ValidationResult, ...] = field(default_factory=tuple)
    missing_required_gates: tuple[str, ...] = field(default_factory=tuple)
    waivers_applied: tuple[ValidationWaiverReference, ...] = field(
        default_factory=tuple
    )
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    overall_ready: bool = False
    schema_version: int = 2
    config_errors: tuple[str, ...] = field(default_factory=tuple)

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint of this readiness artefact.

        PR 62B: Uses canonical ``to_waiver_payload()`` for waivers.
        """
        payload = {
            "readiness_artefact_id": self.readiness_artefact_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "model_identity_fingerprint": self.model_identity_fingerprint,
            "diagnostic_artefact_id": self.diagnostic_artefact_id,
            "diagnostic_artefact_fingerprint": self.diagnostic_artefact_fingerprint,
            "gate_results": [_result_to_dict(r) for r in self.gate_results],
            "blocking_failures": [_result_to_dict(r) for r in self.blocking_failures],
            "review_items": [_result_to_dict(r) for r in self.review_items],
            "passes": [_result_to_dict(r) for r in self.passes],
            "missing_required_gates": sorted(self.missing_required_gates),
            "waivers_applied": [
                w.to_waiver_payload()
                for w in sorted(self.waivers_applied, key=lambda x: x.waiver_id)
            ],
            "evaluated_at": self.evaluated_at.isoformat(),
            "overall_ready": self.overall_ready,
            "schema_version": self.schema_version,
            "config_errors": sorted(self.config_errors),
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict:
        """JSON-serialisable dict with all fields.

        PR 62B: Uses canonical ``to_waiver_payload()`` for waivers,
        includes config_errors.
        """
        return {
            "readiness_artefact_id": self.readiness_artefact_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "model_identity_fingerprint": self.model_identity_fingerprint,
            "diagnostic_artefact_id": self.diagnostic_artefact_id,
            "diagnostic_artefact_fingerprint": self.diagnostic_artefact_fingerprint,
            "gate_results": [_result_to_dict(r) for r in self.gate_results],
            "blocking_failures": [_result_to_dict(r) for r in self.blocking_failures],
            "review_items": [_result_to_dict(r) for r in self.review_items],
            "passes": [_result_to_dict(r) for r in self.passes],
            "missing_required_gates": list(self.missing_required_gates),
            "waivers_applied": [w.to_waiver_payload() for w in self.waivers_applied],
            "evaluated_at": self.evaluated_at.isoformat(),
            "overall_ready": self.overall_ready,
            "schema_version": self.schema_version,
            "config_errors": list(self.config_errors),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ApprovalReadiness:
        """Restore from a dict produced by ``to_dict()``.

        PR 62B: Uses canonical ``from_waiver_payload()``, handles
        legacy schema v1 (waivers without bindings).
        """
        known_fields = {
            "readiness_artefact_id",
            "policy_id",
            "policy_version",
            "policy_fingerprint",
            "model_identity_fingerprint",
            "diagnostic_artefact_id",
            "diagnostic_artefact_fingerprint",
            "evaluated_at",
            "overall_ready",
            "schema_version",
        }
        kwargs: dict[str, Any] = {}
        for k in known_fields:
            if k in d:
                kwargs[k] = d[k]
        # Restore tuples from lists
        if "gate_results" in d:
            kwargs["gate_results"] = tuple(
                _result_from_dict(r) for r in d["gate_results"]
            )
        if "blocking_failures" in d:
            kwargs["blocking_failures"] = tuple(
                _result_from_dict(r) for r in d["blocking_failures"]
            )
        if "review_items" in d:
            kwargs["review_items"] = tuple(
                _result_from_dict(r) for r in d["review_items"]
            )
        if "passes" in d:
            kwargs["passes"] = tuple(_result_from_dict(r) for r in d["passes"])
        if "missing_required_gates" in d:
            kwargs["missing_required_gates"] = tuple(d["missing_required_gates"])
        if "config_errors" in d:
            kwargs["config_errors"] = tuple(d["config_errors"])
        if "waivers_applied" in d and isinstance(d.get("waivers_applied"), list):
            schema_ver = d.get("schema_version", 1)
            if schema_ver >= 2:
                # Canonical waiver payload with bindings
                kwargs["waivers_applied"] = tuple(
                    ValidationWaiverReference.from_waiver_payload(w)
                    for w in d["waivers_applied"]
                )
            else:
                # Legacy v1: waivers without evidence bindings
                kwargs["waivers_applied"] = tuple(
                    ValidationWaiverReference(
                        waiver_id=w["waiver_id"],
                        approved_by=w["approved_by"],
                        approved_at=datetime.fromisoformat(w["approved_at"]),
                        reason=w["reason"],
                        gate_name=w["gate_name"],
                        expiry=datetime.fromisoformat(w["expiry"])
                        if w.get("expiry")
                        else None,
                        superseded_by=w.get("superseded_by"),
                    )
                    for w in d["waivers_applied"]
                )
        if "evaluated_at" in d and isinstance(d["evaluated_at"], str):
            kwargs["evaluated_at"] = datetime.fromisoformat(d["evaluated_at"])
        # Default schema_version to 2 for new objects
        if "schema_version" not in kwargs:
            kwargs["schema_version"] = 2
        return cls(**kwargs)


def _result_to_dict(r: ValidationResult) -> dict:
    """Convert a ValidationResult to a plain dict."""
    return {
        "gate_name": r.gate_name,
        "status": r.status,
        "value": r.value,
        "message": r.message,
        "artefact_id": r.artefact_id,
        "evaluated_at": r.evaluated_at.isoformat(),
        "model_run_id": r.model_run_id,
        "data_fingerprint": r.data_fingerprint,
        "model_spec_fingerprint": r.model_spec_fingerprint,
        "posterior_fingerprint": r.posterior_fingerprint,
        "policy_id": r.policy_id,
        "policy_version": r.policy_version,
        "gate_fingerprint": r.gate_fingerprint,
        "model_identity_fingerprint": r.model_identity_fingerprint,
        "diagnostic_artefact_fingerprint": r.diagnostic_artefact_fingerprint,
    }


def _result_from_dict(d: dict) -> ValidationResult:
    """Restore a ValidationResult from a dict."""
    kwargs: dict[str, Any] = {}
    known = {
        "gate_name",
        "status",
        "value",
        "message",
        "artefact_id",
        "model_run_id",
        "data_fingerprint",
        "model_spec_fingerprint",
        "posterior_fingerprint",
        "policy_id",
        "policy_version",
        "gate_fingerprint",
        "model_identity_fingerprint",
        "diagnostic_artefact_fingerprint",
    }
    for k in known:
        if k in d:
            kwargs[k] = d[k]
    if "evaluated_at" in d:
        if isinstance(d["evaluated_at"], str):
            kwargs["evaluated_at"] = datetime.fromisoformat(d["evaluated_at"])
        else:
            kwargs["evaluated_at"] = d["evaluated_at"]
    return ValidationResult(**kwargs)


# ---------------------------------------------------------------------------
# Readiness evaluator
# ---------------------------------------------------------------------------


def evaluate_approval_readiness(
    results: List[ValidationResult],
    policy: ThresholdPolicy,
    current_model_identity: "ModelIdentity",
    *,
    diagnostic_artefact_id: str = "",
    diagnostic_artefact_fingerprint: str = "",
    waivers: Optional[List[ValidationWaiverReference]] = None,
    as_of: Optional[datetime] = None,
    evidence_context: Optional["ValidationEvidenceContext"] = None,
) -> ApprovalReadiness:
    """Evaluate validation results against a policy.

    PR 53B: Accepts ``current_model_identity`` for staleness checking.
    PR 56B: ``current_model_identity`` is now mandatory for official
    readiness. Results whose identity bindings do not match the current
    identity are stale.

    PR 62B:
    - Calls ``validate_policy_config()`` before evaluating any gate.
      When config errors exist, returns readiness with ``config_errors``
      set and ``overall_ready=False``, no gate results, no waivers.
    - Rejects duplicate result gate names, duplicate waiver gate names,
      results for gates absent from policy, waivers for gates absent from
      policy, and more than one active waiver per gate.
    - Uses ``matches_evidence()`` for staleness (checks all bindings).
    - Enforces waiver evidence binding for official readiness.

    This is a pure function: it does not choose thresholds, mutate approvals,
    or access any external state.

    Parameters
    ----------
    results : list[ValidationResult]
        Results from evaluating diagnostics against the fitted model.
    policy : ThresholdPolicy
        The policy to evaluate against.
    current_model_identity : ModelIdentity
        The current model's identity. Results whose identity does not
        match are stale. Must be provided for official readiness.
    diagnostic_artefact_id : str
        Identifier of the diagnostic artefact evaluated.
    diagnostic_artefact_fingerprint : str
        Fingerprint of the diagnostic artefact at evaluation time.
    waivers : list[ValidationWaiverReference] | None
        Any approved waivers for failing gates.
    as_of : datetime | None
        Evaluation time (defaults to now). Used for expiry checking.
    evidence_context : ValidationEvidenceContext | None
        PR 62B: When provided, used for full ``matches_evidence()``
        staleness checking and waiver evidence binding.

    Returns
    -------
    ApprovalReadiness
        Full fingerprinted readiness artefact with binding evidence.
    """
    as_of = as_of or datetime.now(timezone.utc)
    waivers = waivers or []

    # --- PR 62B: Validate policy configuration before any gate evaluation ---
    config_errors = validate_policy_config(policy)
    if config_errors:
        return ApprovalReadiness(
            readiness_artefact_id=uuid.uuid4().hex,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_fingerprint=policy.fingerprint(),
            model_identity_fingerprint=current_model_identity.fingerprint(),
            diagnostic_artefact_id=diagnostic_artefact_id,
            diagnostic_artefact_fingerprint=diagnostic_artefact_fingerprint,
            gate_results=(),
            blocking_failures=(),
            review_items=(),
            passes=(),
            missing_required_gates=(),
            waivers_applied=(),
            evaluated_at=as_of,
            overall_ready=False,
            schema_version=2,
            config_errors=tuple(config_errors),
        )

    # --- PR 62B: Reject ambiguous input ---
    # Check duplicate result gate names
    result_names = [r.gate_name for r in results]
    if len(result_names) != len(set(result_names)):
        dupes = [n for n in result_names if result_names.count(n) > 1]
        raise ValueError(
            f"Duplicate result gate names are not permitted: {sorted(set(dupes))}"
        )

    # Check duplicate waiver gate names
    waiver_names = [w.gate_name for w in waivers]
    if len(waiver_names) != len(set(waiver_names)):
        dupes = [n for n in waiver_names if waiver_names.count(n) > 1]
        raise ValueError(
            f"Duplicate waiver gate names are not permitted: {sorted(set(dupes))}"
        )

    # Check results for gates absent from policy
    policy_gate_names = {g.name for g in policy.gates}
    for r in results:
        if r.gate_name not in policy_gate_names:
            raise ValueError(
                f"Result gate '{r.gate_name}' is not present in policy "
                f"'{policy.policy_id}'."
            )

    # Check waivers for gates absent from policy
    for w in waivers:
        if w.gate_name not in policy_gate_names:
            raise ValueError(
                f"Waiver gate '{w.gate_name}' is not present in policy "
                f"'{policy.policy_id}'."
            )

    # Check more than one active waiver for a gate
    active_waiver_counts: Dict[str, int] = {}
    for w in waivers:
        if w.is_active(as_of=as_of):
            active_waiver_counts[w.gate_name] = (
                active_waiver_counts.get(w.gate_name, 0) + 1
            )
    for gate_name, count in active_waiver_counts.items():
        if count > 1:
            raise ValueError(
                f"Gate '{gate_name}' has {count} active waivers. "
                "Only one active waiver per gate is permitted."
            )

    result_by_gate: Dict[str, ValidationResult] = {r.gate_name: r for r in results}
    waiver_by_gate: Dict[str, ValidationWaiverReference] = {
        w.gate_name: w for w in waivers
    }

    blocking_failures: List[ValidationResult] = []
    review_items: List[ValidationResult] = []
    passes: List[ValidationResult] = []
    missing_required_gates: List[str] = []

    # Compute identity fingerprint once
    identity_fp = current_model_identity.fingerprint()

    # --- Check policy expiry first ---
    if policy.is_expired(as_of=as_of):
        for gate in policy.gates:
            if gate.required and gate.name not in result_by_gate:
                missing_required_gates.append(gate.name)

        return ApprovalReadiness(
            readiness_artefact_id=uuid.uuid4().hex,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_fingerprint=policy.fingerprint(),
            model_identity_fingerprint=identity_fp,
            diagnostic_artefact_id=diagnostic_artefact_id,
            diagnostic_artefact_fingerprint=diagnostic_artefact_fingerprint,
            gate_results=tuple(results),
            blocking_failures=tuple(result_by_gate.values()),
            passes=(),
            missing_required_gates=tuple(missing_required_gates),
            waivers_applied=tuple(waivers),
            evaluated_at=as_of,
            overall_ready=False,
            schema_version=2,
        )

    # --- Evaluate each gate ---
    for gate in policy.gates:
        result = result_by_gate.get(gate.name)

        if result is None:
            if gate.required:
                missing_required_gates.append(gate.name)
            continue

        # PR 62B: Use matches_evidence() for full staleness check when
        # evidence_context is provided; fall back to matches_identity()
        # for backward compatibility.
        if evidence_context is not None:
            is_stale = not result.matches_evidence(
                evidence_context=evidence_context, gate=gate
            )
        else:
            is_stale = not result.matches_identity(
                model_run_id=current_model_identity.model_run_id,
                data_fingerprint=current_model_identity.data_fingerprint,
                model_spec_fingerprint=current_model_identity.model_spec_fingerprint,
                posterior_fingerprint=current_model_identity.posterior_fingerprint,
                policy_id=policy.policy_id,
                policy_version=policy.version,
            )

        if is_stale:
            # Stale result: treat as missing if required
            if gate.required:
                missing_required_gates.append(gate.name)
            continue

        # Apply status logic
        if result.status == "pass":
            passes.append(result)
            continue

        # result.status is "review" or "fail"
        waiver = waiver_by_gate.get(gate.name)
        if waiver is not None and gate.waivable:
            # PR 62B: For official readiness, waiver must be evidence-bound
            if evidence_context is not None and evidence_context.is_official():
                if not waiver.matches_evidence(evidence_context):
                    # Unbound waiver cannot unblock official readiness
                    if result.status == "fail" and gate.blocking:
                        blocking_failures.append(result)
                    else:
                        review_items.append(result)
                    continue
            # Only accept active waivers
            if waiver.is_active(as_of=as_of):
                passes.append(result)
                continue

        if result.status == "fail" and gate.blocking:
            blocking_failures.append(result)
        else:
            review_items.append(result)

        # Non-waivable failure blocks even if not marked blocking
        if result.status == "fail" and not gate.waivable and not gate.blocking:
            if result not in blocking_failures:
                blocking_failures.append(result)

    # Build the list of *actually applied* waivers (only those that unblocked a gate)
    applied_waivers: List[ValidationWaiverReference] = []
    for result in passes:
        if result.gate_name in waiver_by_gate:
            w_active = waiver_by_gate[result.gate_name]
            if w_active.is_active(as_of=as_of):
                applied_waivers.append(w_active)

    overall_ready = (
        len(blocking_failures) == 0
        and len(missing_required_gates) == 0
        and not policy.is_expired(as_of=as_of)
    )

    return ApprovalReadiness(
        readiness_artefact_id=uuid.uuid4().hex,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_fingerprint=policy.fingerprint(),
        model_identity_fingerprint=identity_fp,
        diagnostic_artefact_id=diagnostic_artefact_id,
        diagnostic_artefact_fingerprint=diagnostic_artefact_fingerprint,
        gate_results=tuple(results),
        blocking_failures=tuple(blocking_failures),
        review_items=tuple(review_items),
        passes=tuple(passes),
        missing_required_gates=tuple(missing_required_gates),
        waivers_applied=tuple(applied_waivers),
        evaluated_at=as_of,
        overall_ready=overall_ready,
        schema_version=2,
    )


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------
# Evaluator registry
# ---------------------------------------------------------------------------
# PR 56E: Typed evaluator registry replacing the hard-coded if-chain in
# ValidationService._evaluate_gate. Each evaluator declares its metadata
# and a callable, enabling discovery, validation, and documentation.


@dataclass(frozen=True)
class EvaluatorMeta:
    """Metadata for a registered validation evaluator.

    Parameters
    ----------
    evaluator_id : str
        Unique identifier used in ``ValidationGate.evaluator_id``.
    output_type : str
        ``"numeric"`` for gates with acceptable_range thresholds,
        ``"boolean"`` for gates with an explicit expected state.
    units : str
        Human-readable units for the output value.
    requires_threshold : bool
        Whether the gate must have ``acceptable_range`` set.
    supported_model_types : tuple[str, ...]
        Model types this evaluator supports, e.g. ``("shared", "market_specific")``.
    required_inputs : tuple[str, ...]
        ValidationInput fields required, e.g. ``("trace",)``, ``("trace", "frame", "meta")``.
    is_deterministic : bool
        Whether the evaluator produces the same output for the same inputs.
    description : str
        Human-readable description of what this evaluator checks.
    """

    evaluator_id: str
    output_type: str = "numeric"
    units: str = ""
    requires_threshold: bool = True
    supported_model_types: tuple[str, ...] = ("shared", "market_specific")
    required_inputs: tuple[str, ...] = ("trace",)
    is_deterministic: bool = True
    description: str = ""


# Type alias for evaluator callables
EvaluatorFn = Callable[..., ValidationResult]


# Internal registry: evaluator_id -> (meta, fn)
_EVALUATOR_REGISTRY: dict[str, tuple[EvaluatorMeta, EvaluatorFn]] = {}


def register_evaluator(
    evaluator_id: str,
    meta: EvaluatorMeta,
) -> Callable[[EvaluatorFn], EvaluatorFn]:
    """Decorator to register an evaluator function.

    Usage::

        @register_evaluator("rhat", EvaluatorMeta(...))
        def evaluate_rhat(gate, trace, frame, meta, credible_mass):
            ...
    """

    def decorator(fn: EvaluatorFn) -> EvaluatorFn:
        _EVALUATOR_REGISTRY[evaluator_id] = (meta, fn)
        return fn

    return decorator


def get_evaluator(
    evaluator_id: str,
) -> tuple[EvaluatorMeta, EvaluatorFn] | None:
    """Look up an evaluator by ID. Returns None if not found."""
    return _EVALUATOR_REGISTRY.get(evaluator_id)


def list_evaluators() -> list[tuple[str, EvaluatorMeta]]:
    """List all registered evaluators with their metadata."""
    return [(eid, meta) for eid, (meta, _) in _EVALUATOR_REGISTRY.items()]


def validate_gate_config(gate: ValidationGate) -> list[str]:
    """Validate a gate's configuration against its evaluator's requirements.

    Returns a list of configuration error messages. An empty list means the
    gate configuration is valid.

    This catches malformed policy configurations before they reach evaluation,
    rather than returning a misleading ``fail`` result.
    """
    errors: list[str] = []
    entry = _EVALUATOR_REGISTRY.get(gate.evaluator_id or gate.name)
    if entry is None:
        errors.append(
            f"No evaluator registered for '{gate.evaluator_id or gate.name}'."
        )
        return errors

    meta, _ = entry

    if meta.requires_threshold and gate.acceptable_range is None:
        errors.append(
            f"Gate '{gate.name}' uses evaluator '{meta.evaluator_id}' which "
            f"requires acceptable_range but none was configured."
        )
    elif meta.requires_threshold and gate.acceptable_range is not None:
        lo, hi = gate.acceptable_range
        if not (math.isfinite(lo) and math.isfinite(hi)):
            errors.append(
                f"Gate '{gate.name}' has non-finite acceptable_range ({lo}, {hi})."
            )
        if lo > hi:
            errors.append(
                f"Gate '{gate.name}' has acceptable_range lower bound {lo} > upper bound {hi}."
            )

    if not meta.requires_threshold and gate.acceptable_range is not None:
        errors.append(
            f"Gate '{gate.name}' uses boolean evaluator '{meta.evaluator_id}' "
            f"but has acceptable_range configured (expected None)."
        )

    if meta.output_type == "boolean" and gate.acceptable_range is not None:
        errors.append(
            f"Gate '{gate.name}' is boolean but has acceptable_range configured. "
            f"Use expected_state instead."
        )

    return errors


def validate_policy_config(policy: ThresholdPolicy) -> list[str]:
    """Validate all gates in a policy against the evaluator registry.

    Returns a list of configuration errors across all gates.
    """
    errors: list[str] = []
    for gate in policy.gates:
        errors.extend(validate_gate_config(gate))
    return errors


# ---------------------------------------------------------------------------
# Operational scope matcher — PR 62B
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationScopeContext:
    """Typed scope for matching gates against operational context.

    PR 62B: Every gate must be:
    - applicable and evaluated, or
    - inapplicable with an explicit reason, or
    - invalid for the current scope.

    Parameters
    ----------
    model_type : str
        The model type being evaluated, e.g. ``"shared"`` or
        ``"market_specific"``.
    market : str | None
        Optional market scope.
    intended_use : str
        Intended use, e.g. ``"model_approval"``.
    """

    model_type: str = "all_models"
    market: Optional[str] = None
    intended_use: str = "model_approval"

    def gate_is_applicable(self, gate: ValidationGate) -> tuple[bool, Optional[str]]:
        """Check whether a gate is applicable in this scope.

        Returns
        -------
        (True, None) if applicable.
        (False, reason) if inapplicable.
        """
        # Gate scope matching
        gate_scope = gate.scope or "all_models"

        if gate_scope == "all_models":
            return True, None

        if gate_scope == "shared" and self.model_type not in (
            "shared",
            "all_models",
        ):
            return False, (
                f"Gate '{gate.name}' is scoped to 'shared' models but "
                f"current model_type is '{self.model_type}'."
            )

        if gate_scope == "market_specific" and self.model_type not in (
            "market_specific",
            "all_models",
        ):
            return False, (
                f"Gate '{gate.name}' is scoped to 'market_specific' "
                f"models but current model_type is '{self.model_type}'."
            )

        return True, None


def filter_applicable_gates(
    policy: ThresholdPolicy,
    scope: ValidationScopeContext,
) -> list[tuple[ValidationGate, bool, Optional[str]]]:
    """Filter policy gates by scope applicability.

    Returns a list of ``(gate, applicable, reason)`` tuples.
    """
    result: list[tuple[ValidationGate, bool, Optional[str]]] = []
    for gate in policy.gates:
        applicable, reason = scope.gate_is_applicable(gate)
        result.append((gate, applicable, reason))
    return result


# ---------------------------------------------------------------------------
# Concrete evaluator implementations
# ---------------------------------------------------------------------------


def _evaluate_rhat(
    gate: ValidationGate,
    trace: Any,
    frame: Any | None,
    meta: Any | None,
    credible_mass: float,
) -> ValidationResult:
    """Evaluate R-hat convergence diagnostic."""
    rhat = az.rhat(trace, var_names=["mu", "beta", "hill_K", "alpha"])
    max_val = float("-inf")
    for var_data in rhat.values():
        if hasattr(var_data, "values"):
            max_val = max(max_val, float(var_data.values.max()))
    status = _classify_numeric_gate(max_val, gate)
    return ValidationResult(
        gate_name=gate.name,
        status=status,
        value=max_val,
        message=f"Max R-hat = {max_val:.4f}",
    )


def _evaluate_ess(
    gate: ValidationGate,
    trace: Any,
    frame: Any | None,
    meta: Any | None,
    credible_mass: float,
) -> ValidationResult:
    """Evaluate effective sample size."""
    ess = az.ess(trace, var_names=["mu", "beta", "hill_K", "alpha"])
    min_val = float("inf")
    for var_data in ess.values():
        if hasattr(var_data, "values"):
            min_val = min(min_val, float(var_data.values.min()))
    status = _classify_numeric_gate(min_val, gate)
    return ValidationResult(
        gate_name=gate.name,
        status=status,
        value=min_val,
        message=f"Min ESS = {min_val:.1f}",
    )


def _evaluate_divergences(
    gate: ValidationGate,
    trace: Any,
    frame: Any | None,
    meta: Any | None,
    credible_mass: float,
) -> ValidationResult:
    """Check for divergent transitions."""
    has_div = False
    if hasattr(trace, "sample_stats") and "diverging" in trace.sample_stats:
        has_div = bool(trace.sample_stats["diverging"].values.any())
    # Boolean gate: use expected_state if set, else pass when no divergences
    expected = getattr(gate, "expected_state", None)
    if expected is not None:
        status = "pass" if has_div == expected else "fail"
    else:
        status = "pass" if not has_div else "fail"
    return ValidationResult(
        gate_name=gate.name,
        status=status,
        value=float(has_div),
        message="No divergences" if not has_div else "Divergences detected",
    )


def _evaluate_ppc(
    gate: ValidationGate,
    trace: Any,
    frame: Any | None,
    meta: Any | None,
    credible_mass: float,
) -> ValidationResult:
    """Evaluate posterior predictive coverage."""
    # Local import to avoid circular dependency
    from ancestry_mmm.core.diagnostics import posterior_predictive_coverage as _ppc

    if frame is None or meta is None:
        return ValidationResult(
            gate_name=gate.name,
            status="fail",
            message="Missing frame or meta for PPC evaluation",
        )
    ppc = _ppc(
        trace,
        frame,
        meta,
        credible_mass=credible_mass,
        random_seed=42,
    )
    mean_cov = float(ppc["coverage_pct"].mean())
    status = _classify_numeric_gate(mean_cov, gate)
    return ValidationResult(
        gate_name=gate.name,
        status=status,
        value=mean_cov,
        message=f"Mean PPC coverage = {mean_cov:.1f}%",
    )


# Register evaluators
register_evaluator(
    "rhat",
    EvaluatorMeta(
        evaluator_id="rhat",
        output_type="numeric",
        units="R-hat",
        requires_threshold=True,
        required_inputs=("trace",),
        description="Gelman-Rubin convergence diagnostic (R-hat). Lower is better.",
    ),
)(_evaluate_rhat)

register_evaluator(
    "convergence_rhat",
    EvaluatorMeta(
        evaluator_id="convergence_rhat",
        output_type="numeric",
        units="R-hat",
        requires_threshold=True,
        required_inputs=("trace",),
        description="Gelman-Rubin convergence diagnostic (R-hat). Lower is better.",
    ),
)(_evaluate_rhat)

register_evaluator(
    "ess",
    EvaluatorMeta(
        evaluator_id="ess",
        output_type="numeric",
        units="n_eff",
        requires_threshold=True,
        required_inputs=("trace",),
        description="Effective sample size. Higher is better.",
    ),
)(_evaluate_ess)

register_evaluator(
    "min_ess",
    EvaluatorMeta(
        evaluator_id="min_ess",
        output_type="numeric",
        units="n_eff",
        requires_threshold=True,
        required_inputs=("trace",),
        description="Minimum effective sample size across parameters. Higher is better.",
    ),
)(_evaluate_ess)

register_evaluator(
    "divergences",
    EvaluatorMeta(
        evaluator_id="divergences",
        output_type="boolean",
        units="",
        requires_threshold=False,
        required_inputs=("trace",),
        description="Checks for divergent transitions in HMC sampling.",
    ),
)(_evaluate_divergences)

register_evaluator(
    "ppc",
    EvaluatorMeta(
        evaluator_id="ppc",
        output_type="numeric",
        units="%",
        requires_threshold=True,
        required_inputs=("trace", "frame", "meta"),
        description="Posterior predictive coverage percentage. Higher is better.",
    ),
)(_evaluate_ppc)

register_evaluator(
    "ppc_coverage",
    EvaluatorMeta(
        evaluator_id="ppc_coverage",
        output_type="numeric",
        units="%",
        requires_threshold=True,
        required_inputs=("trace", "frame", "meta"),
        description="Posterior predictive coverage percentage. Higher is better.",
    ),
)(_evaluate_ppc)


# ---------------------------------------------------------------------------
# Numeric gate classification (shared by evaluators and validation service)
# ---------------------------------------------------------------------------


def _classify_numeric_gate(value: float, gate: ValidationGate) -> str:
    """Classify a numeric value against a gate's pass/review/fail bands.

    Returns ``"pass"``, ``"review"``, or ``"fail"``.

    Validates threshold finiteness and ordering. Missing thresholds on a
    numeric gate is a configuration error (raises ValueError) rather than
    a silent fail.
    """
    if gate.acceptable_range is None:
        raise ValueError(
            f"Gate '{gate.name}' is numeric but has no acceptable_range configured. "
            "This is a policy configuration error."
        )

    lo, hi = gate.acceptable_range
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ValueError(
            f"Gate '{gate.name}' has non-finite acceptable_range ({lo}, {hi})."
        )
    if lo > hi:
        raise ValueError(
            f"Gate '{gate.name}' has acceptable_range lower bound {lo} > upper bound {hi}."
        )

    if not math.isfinite(value):
        return "fail"

    direction = gate.direction
    if direction == "lower_is_better":
        if value <= hi:
            return "pass"
        if gate.review_range is not None:
            _rlo, rhi = gate.review_range
            if value <= rhi:
                return "review"
        return "fail"
    else:  # higher_is_better
        if value >= lo:
            return "pass"
        if gate.review_range is not None:
            rlo, _rhi = gate.review_range
            if value >= rlo:
                return "review"
        return "fail"


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------


def readiness_to_dict(readiness: ApprovalReadiness) -> dict:
    """Convert ApprovalReadiness to a JSON-serialisable dict."""
    return readiness.to_dict()
