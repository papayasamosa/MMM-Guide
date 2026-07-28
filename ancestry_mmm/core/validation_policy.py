"""
Validation-policy and approval-readiness foundation (REQ-VAL-001).

Separates model identity approval from evidence-based validation readiness.

Key design:
- ``ThresholdPolicy``: a named, versioned set of validation gates. The policy
  does **not** embed universal thresholds — those are in the policy data, not
  in code.
- ``ValidationGate``: one gate (convergence, PPC, backtest, etc.) with scope,
  acceptable range, blocking flag, and optional waiver support.
- ``ValidationResult``: the outcome of evaluating one gate against a fitted
  model.
- ``ApprovalReadiness``: aggregate of all gate results under a policy —
  identifies blockers, review items, and passes without mutating approvals.
- ``ValidationWaiverReference``: an approved exception to a gate.
- ``evaluate_approval_readiness``: pure function that consumes results and a
  policy, returns readiness. Does not choose thresholds or mutate approvals.
"""

from __future__ import annotations

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
    """
    waiver_id: str
    approved_by: str
    approved_at: datetime
    reason: str
    gate_name: str
    expiry: Optional[datetime] = None


@dataclass(frozen=True)
class ValidationGate:
    """One validation gate within a policy.

    Parameters
    ----------
    name : str
        Machine-readable identifier, e.g. ``convergence_rhat``,
        ``ppc_coverage``, ``backtest_mape``.
    description : str
        Human-readable description of what this gate checks.
    scope : str
        What the gate applies to, e.g. ``all_models``, ``model_a_only``,
        ``market_specific_only``.
    acceptable_range : tuple[float, float] | None
        Lower and upper acceptable bounds, if numeric (e.g. R-hat < 1.05).
        ``None`` means pass/fail is based on a boolean check.
    blocking : bool
        If True, a failing result on this gate blocks official approval.
    waivable : bool
        If True, a waiver can override a failure. If False, failure is
        final regardless of waiver.
    required : bool
        If True, a result for this gate *must* be present. A missing
        required gate blocks official approval.
    """
    name: str
    description: str
    scope: str = "all_models"
    acceptable_range: Optional[tuple[float, float]] = None
    blocking: bool = True
    waivable: bool = False
    required: bool = True


@dataclass(frozen=True)
class ThresholdPolicy:
    """A versioned set of validation gates.

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


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of evaluating one gate.

    Parameters
    ----------
    gate_name : str
        Name of the gate that was evaluated.
    passed : bool
        Whether the check passed.
    value : float | None
        Numeric value that was checked (e.g. max R-hat). ``None`` for
        boolean checks.
    message : str
        Human-readable summary of the result.
    artefact_id : str | None
        Optional reference to supporting evidence (e.g. a scorecard
        fingerprint or diagnostic artefact ID).
    evaluated_at : datetime
        When the evaluation was performed.
    """
    gate_name: str
    passed: bool
    value: Optional[float] = None
    message: str = ""
    artefact_id: Optional[str] = None
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_stale(self, max_age_days: float = 7.0) -> bool:
        """A result is stale if it was evaluated too long ago."""
        age = (datetime.now(timezone.utc) - self.evaluated_at).total_seconds()
        return age > max_age_days * 86400


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

    # Build lookup for provided results
    result_by_gate: Dict[str, ValidationResult] = {r.gate_name: r for r in results}
    waiver_by_gate: Dict[str, ValidationWaiverReference] = {w.gate_name: w for w in waivers}

    blocking_failures: List[ValidationResult] = []
    review_items: List[ValidationResult] = []
    passes: List[ValidationResult] = []
    missing_required_gates: List[str] = []

    # Check policy expiry first
    if policy.is_expired(as_of=as_of):
        # All gates are effectively blocked if the policy itself is expired
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

    # Evaluate each gate in the policy
    for gate in policy.gates:
        result = result_by_gate.get(gate.name)

        if result is None:
            if gate.required:
                missing_required_gates.append(gate.name)
            continue

        if result.passed:
            passes.append(result)
            continue

        # Gate failed
        waiver = waiver_by_gate.get(gate.name)
        if waiver is not None and gate.waivable:
            # Waiver accepted — treat as pass for blocking purposes
            passes.append(result)
            continue

        if gate.blocking:
            blocking_failures.append(result)
        else:
            review_items.append(result)

        # Non-waivable failure still blocks even if not marked blocking
        if not gate.waivable and not gate.blocking:
            # A non-waivable gate that fails should still block
            if result not in blocking_failures:
                blocking_failures.append(result)

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
        waivers_applied=waivers,
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
                "passed": r.passed,
                "value": r.value,
                "message": r.message,
            }
            for r in readiness.blocking_failures
        ],
        "review_items": [
            {
                "gate_name": r.gate_name,
                "passed": r.passed,
                "value": r.value,
                "message": r.message,
            }
            for r in readiness.review_items
        ],
        "passes": [
            {
                "gate_name": r.gate_name,
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
            }
            for w in readiness.waivers_applied
        ],
    }
