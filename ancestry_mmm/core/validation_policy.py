"""
Validation-policy and approval-readiness foundation (REQ-VAL-001).

PR 51C: Improved semantics with pass/review/fail bands, model-identity
binding on ValidationResult, waiver expiry validation, and staleness
based on dependency mismatch (not just age).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


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
    """
    waiver_id: str
    approved_by: str
    approved_at: datetime
    reason: str
    gate_name: str
    expiry: Optional[datetime] = None
    superseded_by: Optional[str] = None

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
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
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
            raise ValueError(f"ThresholdPolicy gates contain duplicate names: {sorted(set(dupes))}")

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
            "approval_date": self.approval_date.isoformat() if self.approval_date else None,
            "expiry": self.expiry.isoformat() if self.expiry else None,
            "gates": [g.fingerprint() for g in self.gates],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
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

    def __post_init__(self) -> None:
        if self.status not in VALIDATION_STATUS_VALUES:
            raise ValueError(f"Invalid status: {self.status!r}. Must be one of {VALIDATION_STATUS_VALUES}")

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
        if not all([model_run_id, data_fingerprint, model_spec_fingerprint,
                     posterior_fingerprint, policy_id, policy_version]):
            return True  # Missing identity = stale
        if not all([self.model_run_id, self.data_fingerprint, self.model_spec_fingerprint,
                     self.posterior_fingerprint, self.policy_id, self.policy_version]):
            return True  # Result not fully bound = stale
        return not self.matches_identity(
            model_run_id=model_run_id,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            policy_id=policy_id,
            policy_version=policy_version,
        )


@dataclass(frozen=True)
class ApprovalReadiness:
    """Aggregate of all gate results under a policy.

    Parameters
    ----------
    policy_id : str
        The policy that was evaluated.
    policy_version : str
        Version of the policy.
    blocking_failures : list[ValidationResult]
        Gates that failed and are marked as blocking.
    review_items : list[ValidationResult]
        Gates that failed but are not blocking (review-only).
    passes : list[ValidationResult]
        Gates that passed.
    missing_required_gates : list[str]
        Names of required gates for which no result was provided.
    waivers_applied : list[ValidationWaiverReference]
        Waivers that were accepted for failing gates.
    overall_ready : bool
        True if no blocking failures, no missing required gates, no
        non-waivable failures, and policy is not expired.
    """
    policy_id: str
    policy_version: str
    blocking_failures: List[ValidationResult] = field(default_factory=list)
    review_items: List[ValidationResult] = field(default_factory=list)
    passes: List[ValidationResult] = field(default_factory=list)
    missing_required_gates: List[str] = field(default_factory=list)
    waivers_applied: List[ValidationWaiverReference] = field(default_factory=list)
    overall_ready: bool = False


# ---------------------------------------------------------------------------
# Readiness evaluator
# ---------------------------------------------------------------------------


def evaluate_approval_readiness(
    results: List[ValidationResult],
    policy: ThresholdPolicy,
    *,
    waivers: Optional[List[ValidationWaiverReference]] = None,
    as_of: Optional[datetime] = None,
) -> ApprovalReadiness:
    """Evaluate validation results against a policy.

    PR 51C:
    - Uses ``status`` field (pass/review/fail) from ``ValidationResult``.
    - Checks identity-based staleness: a stale passing result does *not*
      pass readiness.
    - Validates waiver expiry and activation.
    - Applies pass/review/fail bands from ``ValidationGate``.

    This is a pure function: it does not choose thresholds, mutate approvals,
    or access any external state.

    Parameters
    ----------
    results : list[ValidationResult]
        Results from evaluating diagnostics against the fitted model.
    policy : ThresholdPolicy
        The policy to evaluate against.
    waivers : list[ValidationWaiverReference] | None
        Any approved waivers for failing gates.
    as_of : datetime | None
        Evaluation time (defaults to now). Used for expiry checking.

    Returns
    -------
    ApprovalReadiness
        Aggregate readiness with blockers, review items, and passes.
    """
    as_of = as_of or datetime.now(timezone.utc)
    waivers = waivers or []

    result_by_gate: Dict[str, ValidationResult] = {r.gate_name: r for r in results}
    waiver_by_gate: Dict[str, ValidationWaiverReference] = {w.gate_name: w for w in waivers}

    blocking_failures: List[ValidationResult] = []
    review_items: List[ValidationResult] = []
    passes: List[ValidationResult] = []
    missing_required_gates: List[str] = []

    # --- Check policy expiry first ---
    if policy.is_expired(as_of=as_of):
        for gate in policy.gates:
            if gate.required and gate.name not in result_by_gate:
                missing_required_gates.append(gate.name)

        return ApprovalReadiness(
            policy_id=policy.policy_id,
            policy_version=policy.version,
            blocking_failures=list(result_by_gate.values()),
            review_items=[],
            passes=[],
            missing_required_gates=missing_required_gates,
            waivers_applied=waivers,
            overall_ready=False,
        )

    # --- Evaluate each gate ---
    for gate in policy.gates:
        result = result_by_gate.get(gate.name)

        if result is None:
            if gate.required:
                missing_required_gates.append(gate.name)
            continue

        # Staleness check: if the result's identity bindings don't match
        # the current policy, it's stale regardless of pass/review/fail status.
        # Use the policy's own identity fields to check.
        if result.is_stale_for(
            model_run_id=result.model_run_id,
            data_fingerprint=result.data_fingerprint,
            model_spec_fingerprint=result.model_spec_fingerprint,
            posterior_fingerprint=result.posterior_fingerprint,
            policy_id=policy.policy_id,
            policy_version=policy.version,
        ):
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
        w = waiver_by_gate.get(result.gate_name)
        if w is not None and w.is_active(as_of=as_of):
            applied_waivers.append(w)

    overall_ready = (
        len(blocking_failures) == 0
        and len(missing_required_gates) == 0
        and not policy.is_expired(as_of=as_of)
    )

    return ApprovalReadiness(
        policy_id=policy.policy_id,
        policy_version=policy.version,
        blocking_failures=blocking_failures,
        review_items=review_items,
        passes=passes,
        missing_required_gates=missing_required_gates,
        waivers_applied=applied_waivers,
        overall_ready=overall_ready,
    )


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------


def readiness_to_dict(readiness: ApprovalReadiness) -> dict:
    """Convert ApprovalReadiness to a JSON-serialisable dict."""
    return {
        "policy_id": readiness.policy_id,
        "policy_version": readiness.policy_version,
        "overall_ready": readiness.overall_ready,
        "blocking_failures": [
            {
                "gate_name": r.gate_name,
                "status": r.status,
                "passed": r.passed,
                "value": r.value,
                "message": r.message,
                "artefact_id": r.artefact_id,
            }
            for r in readiness.blocking_failures
        ],
        "review_items": [
            {
                "gate_name": r.gate_name,
                "status": r.status,
                "passed": r.passed,
                "value": r.value,
                "message": r.message,
            }
            for r in readiness.review_items
        ],
        "passes": [
            {
                "gate_name": r.gate_name,
                "status": r.status,
                "passed": r.passed,
                "value": r.value,
                "message": r.message,
            }
            for r in readiness.passes
        ],
        "missing_required_gates": readiness.missing_required_gates,
        "waivers_applied": [
            {
                "waiver_id": w.waiver_id,
                "gate_name": w.gate_name,
                "approved_by": w.approved_by,
                "reason": w.reason,
                "is_active": w.is_active(),
            }
            for w in readiness.waivers_applied
        ],
    }
