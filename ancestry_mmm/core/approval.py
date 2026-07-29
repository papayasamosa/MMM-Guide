"""
Explicit model-approval gate, bound to the exact fitted model it was
granted for.

The guide this build follows is explicit: "A high R-squared must not
automatically mean the model is accepted... Only an approved model should
populate the official curve bank and planning defaults." An approval that
merely *exists* is not enough on its own: if the model is retrained, the
data changes, the specification (structure or priors) changes, or the
posterior is recalculated, an approval granted for the *previous* model run
must stop being valid for the new one, even though a `ModelApproval` object
is still sitting in session state.

ModelApproval therefore records not just who approved a model and what they
reviewed, but the exact model run's identity: `model_run_id` (a fresh UUID
minted on every fit - see pages/05_Model_Training.py) plus SHA-256
fingerprints of the modelling data, the model specification (structure +
priors), and the fitted posterior (see core.fingerprint). Two model runs
with byte-identical inputs can still be distinguished by `model_run_id`;
everything else is content-addressed.

The gate has teeth at the core API level, not just in the Streamlit
interface: core.curve_bank.make_entries and core.optimization.evaluate_scenario
/optimize_scenario call require_matching_approval() themselves, so calling
them directly - bypassing whatever a Streamlit page's own checks do - still
requires a valid, matching approval.

REQ-VAL-001: ModelApproval may optionally reference a ``validation_policy_id``
to bind the approval to a governed validation policy. When set, the approval
also requires that the policy's gates have been evaluated (via
``evaluate_approval_readiness``) before the approval is considered valid for
official use.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .validation_policy import ApprovalReadiness, ThresholdPolicy


class ApprovalMismatchError(RuntimeError):
    """
    Raised when an approval is missing, legacy (predates model-binding), or
    does not match the model run it is being used to authorise.
    """


class ValidationPolicyBlockedError(RuntimeError):
    """
    Raised when official approval is attempted but the validation policy
    gates have not been satisfied (missing required gates, blocking failures,
    or expired policy).
    """


@dataclass
class ModelApproval:
    approved_by: str
    approved_at: float = field(default_factory=time.time)
    run_label: str = ""
    notes: str = ""
    known_limitations: str = ""
    # Which scorecard sections the approver reviewed before signing off,
    # e.g. ["convergence", "in_sample_fit", "ppc_coverage", "plausibility_flags"].
    diagnostics_accepted: List[str] = field(default_factory=list)

    # Model-binding identity: which exact fitted model this approval covers.
    # Empty strings (the default) mean "unbound" - either a legacy approval
    # created before this field existed, or one built without the current
    # model artefacts available. matches_current_model() treats an unbound
    # approval as never matching, regardless of what it's compared against.
    model_run_id: str = ""
    data_fingerprint: str = ""
    model_spec_fingerprint: str = ""
    posterior_fingerprint: str = ""

    # REQ-VAL-001 / PR 53D: Optional reference to a validation policy
    # and its readiness artefact. When validation_policy_id is set,
    # require_matching_approval also checks that the policy's gates have
    # been evaluated with overall_ready=True, that the policy version
    # and fingerprint match, and that the readiness artefact identity
    # is present.
    validation_policy_id: str = ""
    validation_policy_version: str = ""
    validation_policy_fingerprint: str = ""
    readiness_artefact_id: str = ""
    readiness_fingerprint: str = ""

    def is_model_bound(self) -> bool:
        return bool(
            self.model_run_id
            and self.data_fingerprint
            and self.model_spec_fingerprint
            and self.posterior_fingerprint
        )

    def matches_current_model(
        self,
        *,
        model_run_id: str,
        data_fingerprint: str,
        model_spec_fingerprint: str,
        posterior_fingerprint: str,
    ) -> bool:
        """
        True only if every identifier is present on both sides and they all
        match exactly. False whenever any identifier is missing (on this
        approval or on the "current" side passed in) - including a legacy
        approval with no model-binding fields at all, which must never be
        treated as valid merely because a ModelApproval object exists.
        """
        if not self.is_model_bound():
            return False
        if not (
            model_run_id
            and data_fingerprint
            and model_spec_fingerprint
            and posterior_fingerprint
        ):
            return False
        return (
            self.model_run_id == model_run_id
            and self.data_fingerprint == data_fingerprint
            and self.model_spec_fingerprint == model_spec_fingerprint
            and self.posterior_fingerprint == posterior_fingerprint
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelApproval":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def require_matching_approval(
    approval: Optional[ModelApproval],
    *,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    approval_readiness: Optional["ApprovalReadiness"] = None,
    current_policy: Optional["ThresholdPolicy"] = None,
) -> ModelApproval:
    """
    Raise ApprovalMismatchError unless `approval` is a ModelApproval that is
    model-bound and matches the given current identifiers; otherwise return
    it unchanged. Shared by core.curve_bank.make_entries and
    core.optimization.evaluate_scenario/optimize_scenario so the check can't
    be skipped by calling those functions directly instead of going through
    a Streamlit page's own (weaker, UI-only) checks.

    REQ-VAL-001: If the approval references a ``validation_policy_id``,
    ``approval_readiness`` must be provided and must have
    ``overall_ready=True``, otherwise ``ValidationPolicyBlockedError`` is
    raised. When ``approval_readiness`` is provided but the approval does
    not reference a policy, the readiness is ignored (backward compatible).

    PR 64A: When ``current_policy`` is provided, verifies the policy is
    still active (not expired and not superseded) at the time of use.
    """
    # Lazy import to avoid circular dependency at module level
    from .validation_policy import ApprovalReadiness as _ApprovalReadiness

    if not isinstance(approval, ModelApproval):
        raise ApprovalMismatchError("No approval was provided for this model.")
    if not approval.is_model_bound():
        raise ApprovalMismatchError(
            "This approval predates model-bound approval (no run/fingerprint identifiers "
            "recorded) and cannot be treated as valid for the current model. Re-approve after review."
        )
    if not approval.matches_current_model(
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    ):
        raise ApprovalMismatchError(
            "This approval does not match the current fitted model - the data, "
            "specification, posterior, or model run have changed since it was approved. "
            "Re-approve after review."
        )

    # REQ-VAL-001 / PR 53D + PR 56C + PR 62B: Validation policy and readiness check
    if approval.validation_policy_id:
        if approval_readiness is None:
            raise ValidationPolicyBlockedError(
                f"Approval references validation policy "
                f"'{approval.validation_policy_id}' but no readiness "
                f"assessment was provided."
            )
        if not isinstance(approval_readiness, _ApprovalReadiness):
            raise ValidationPolicyBlockedError(
                "Approval readiness must be a valid ApprovalReadiness object."
            )

        # PR 62B: When policy-backed, ALL evidence fields must be present
        _missing: list[str] = []
        if not approval.validation_policy_version:
            _missing.append("validation_policy_version")
        if not approval.validation_policy_fingerprint:
            _missing.append("validation_policy_fingerprint")
        if not approval.readiness_artefact_id:
            _missing.append("readiness_artefact_id")
        if not approval.readiness_fingerprint:
            _missing.append("readiness_fingerprint")
        if _missing:
            raise ValidationPolicyBlockedError(
                f"Policy-backed approval is missing required evidence fields: "
                f"{', '.join(_missing)}. "
                "All proof fields must be present for policy-backed approval."
            )

        if approval_readiness.policy_id != approval.validation_policy_id:
            raise ValidationPolicyBlockedError(
                f"Approval references policy '{approval.validation_policy_id}' "
                f"but readiness was evaluated against "
                f"'{approval_readiness.policy_id}'."
            )
        if approval_readiness.policy_version != approval.validation_policy_version:
            raise ValidationPolicyBlockedError(
                f"Approval references policy version "
                f"'{approval.validation_policy_version}' but readiness "
                f"was evaluated against version "
                f"'{approval_readiness.policy_version}'."
            )
        if (
            approval_readiness.policy_fingerprint
            != approval.validation_policy_fingerprint
        ):
            raise ValidationPolicyBlockedError(
                f"Approval references policy fingerprint "
                f"'{approval.validation_policy_fingerprint}' but readiness "
                f"was evaluated against fingerprint "
                f"'{approval_readiness.policy_fingerprint}'."
            )
        if approval_readiness.readiness_artefact_id != approval.readiness_artefact_id:
            raise ValidationPolicyBlockedError(
                f"Approval references readiness artefact "
                f"'{approval.readiness_artefact_id}' but readiness "
                f"has artefact '{approval_readiness.readiness_artefact_id}'."
            )
        # Verify readiness fingerprint matches
        actual_fp = approval_readiness.fingerprint()
        if actual_fp != approval.readiness_fingerprint:
            raise ValidationPolicyBlockedError(
                f"Approval readiness fingerprint mismatch: "
                f"stored '{approval.readiness_fingerprint}' vs "
                f"computed '{actual_fp}'."
            )
        # Verify readiness is overall ready
        if not approval_readiness.overall_ready:
            _detail_parts: list[str] = []
            if approval_readiness.config_errors:
                _detail_parts.append(
                    f"Config errors: {len(approval_readiness.config_errors)}"
                )
            if approval_readiness.blocking_failures:
                _detail_parts.append(
                    f"Blocking failures: {len(approval_readiness.blocking_failures)}"
                )
            if approval_readiness.missing_required_gates:
                _detail_parts.append(
                    f"Missing required gates: "
                    f"{len(approval_readiness.missing_required_gates)}"
                )
            raise ValidationPolicyBlockedError(
                "Validation policy gates are not satisfied. "
                f"{'; '.join(_detail_parts)}. "
                "Resolve issues or use exploratory mode."
            )
        # PR 62B: Verify readiness model identity fingerprint matches the
        # current model identity components provided to this function.
        # We reconstruct the ModelIdentity to compute the expected fingerprint.
        from .model_identity import ModelIdentity as _ModelIdentity

        _current_identity = _ModelIdentity(
            model_run_id=model_run_id,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
        )
        _expected_fp = _current_identity.fingerprint()
        if approval_readiness.model_identity_fingerprint != _expected_fp:
            raise ValidationPolicyBlockedError(
                f"Readiness model identity fingerprint "
                f"'{approval_readiness.model_identity_fingerprint}' does not "
                f"match current model identity fingerprint '{_expected_fp}'."
            )

        # PR 66A: Schema v3 required for policy-backed official use.
        # Schema v0/v1: legacy unverified, never official.
        # Schema v2: loadable and fingerprint-compatible, but not valid
        # for newly created policy-backed approvals. Existing continuation
        # requires explicit migration policy.
        if approval_readiness.schema_version < 3:
            _sv = approval_readiness.schema_version
            raise ValidationPolicyBlockedError(
                f"Readiness artefact has schema version {_sv}. "
                f"Policy-backed official approval requires schema v3+. "
                f"Re-evaluate readiness with the current policy."
            )

        # PR 66A: Current policy is now mandatory for policy-backed use.
        # The readiness fingerprint alone is insufficient — the caller must
        # provide the live policy object to verify it is still active and
        # matches what was evaluated.
        if current_policy is None:
            raise ValidationPolicyBlockedError(
                "Current validation policy must be provided for "
                "policy-backed official approval. "
                "Call require_matching_approval with current_policy=<policy>."
            )
        from .validation_policy import ThresholdPolicy as _TP

        if not isinstance(current_policy, _TP):
            raise ValidationPolicyBlockedError(
                "current_policy must be a valid ThresholdPolicy object."
            )
        if current_policy.policy_id != approval_readiness.policy_id:
            raise ValidationPolicyBlockedError(
                f"Current policy ID '{current_policy.policy_id}' does not "
                f"match readiness policy ID "
                f"'{approval_readiness.policy_id}'."
            )
        if current_policy.version != approval_readiness.policy_version:
            raise ValidationPolicyBlockedError(
                f"Current policy version '{current_policy.version}' does not "
                f"match readiness policy version "
                f"'{approval_readiness.policy_version}'."
            )
        if current_policy.fingerprint() != approval_readiness.policy_fingerprint:
            raise ValidationPolicyBlockedError(
                "Current policy fingerprint does not match "
                "readiness policy fingerprint."
            )
        if not current_policy.is_active():
            raise ValidationPolicyBlockedError(
                f"Validation policy '{current_policy.policy_id}' "
                f"version '{current_policy.version}' is no longer active. "
                f"Expired: {current_policy.is_expired()}, "
                f"Superseded: {bool(current_policy.superseded_by)}. "
                "A new readiness evaluation with a current policy is required."
            )

    return approval


def fingerprint_model_approval(approval: ModelApproval) -> str:
    """Canonical SHA-256 fingerprint of a ModelApproval's complete record.

    Includes all approval-record fields:
    - approved_by, approved_at, run_label, notes, known_limitations
    - diagnostics_accepted
    - model_run_id, data_fingerprint, model_spec_fingerprint, posterior_fingerprint
    - validation_policy_id, validation_policy_version, validation_policy_fingerprint
    - readiness_artefact_id, readiness_fingerprint

    A material change to any of these fields produces a different fingerprint
    and therefore stales scenarios saved against the previous approval record.

    Returns a 64-character hex string.
    """
    payload = approval.to_dict()
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_policy_backed_model_approval(
    *,
    approved_by: str,
    readiness: "ApprovalReadiness",
    current_policy: "ThresholdPolicy",
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    run_label: str = "",
    notes: str = "",
    known_limitations: str = "",
    diagnostics_accepted: Optional[List[str]] = None,
) -> ModelApproval:
    """Create a policy-backed ModelApproval requiring schema-v3 readiness.

    PR 66A: This is the only supported path for creating new official
    policy-backed approvals. Direct dataclass construction with
    ``validation_policy_id`` set is not sufficient — this function
    enforces:

    - readiness schema version >= 3
    - current_policy is active (not expired, not superseded)
    - current_policy identity matches readiness bindings
    - model identity matches the current model

    Parameters
    ----------
    approved_by : str
        Person who approved the model.
    readiness : ApprovalReadiness
        Schema-v3 readiness artefact with overall_ready=True.
    current_policy : ThresholdPolicy
        The live policy object (not just the stored fingerprint).
    model_run_id, data_fingerprint, model_spec_fingerprint,
    posterior_fingerprint : str
        Current model identity fields.
    run_label, notes, known_limitations : str
        Optional human-readable metadata.
    diagnostics_accepted : list[str] | None
        Diagnostics sections the approver reviewed.

    Returns
    -------
    ModelApproval
        A fully populated policy-backed approval bound to the readiness
        artefact and current policy.

    Raises
    ------
    ValidationPolicyBlockedError
        If readiness is not schema v3 or current_policy is inactive
        or does not match the readiness bindings.
    """
    if readiness.schema_version < 3:
        raise ValidationPolicyBlockedError(
            f"Cannot create policy-backed approval from readiness schema "
            f"version {readiness.schema_version}. Schema v3+ is required. "
            "Re-evaluate readiness with the current policy."
        )
    if not readiness.overall_ready:
        _parts: list[str] = []
        if readiness.config_errors:
            _parts.append(f"{len(readiness.config_errors)} config error(s)")
        if readiness.blocking_failures:
            _parts.append(f"{len(readiness.blocking_failures)} blocking failure(s)")
        if readiness.missing_required_gates:
            _parts.append(
                f"{len(readiness.missing_required_gates)} missing required gate(s)"
            )
        if readiness.lifecycle_issues:
            _parts.append(f"{len(readiness.lifecycle_issues)} lifecycle issue(s)")
        raise ValidationPolicyBlockedError(
            f"Cannot create policy-backed approval: readiness is not ready. "
            f"Details: {'; '.join(_parts)}."
        )
    if current_policy is None:
        raise ValidationPolicyBlockedError(
            "A current validation policy object is required to create a "
            "policy-backed approval."
        )
    if not current_policy.is_active():
        raise ValidationPolicyBlockedError(
            f"Policy '{current_policy.policy_id}' version "
            f"'{current_policy.version}' is not active. "
            f"Expired: {current_policy.is_expired()}, "
            f"Superseded: {bool(current_policy.superseded_by)}."
        )

    approval = ModelApproval(
        approved_by=approved_by,
        run_label=run_label,
        notes=notes,
        known_limitations=known_limitations,
        diagnostics_accepted=diagnostics_accepted or [],
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
        validation_policy_id=current_policy.policy_id,
        validation_policy_version=current_policy.version,
        validation_policy_fingerprint=current_policy.fingerprint(),
        readiness_artefact_id=readiness.readiness_artefact_id,
        readiness_fingerprint=readiness.fingerprint(),
    )
    return approval
