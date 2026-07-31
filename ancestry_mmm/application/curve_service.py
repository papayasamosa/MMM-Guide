"""CurveService — application boundary for official curve artifacts (REQ-CURVE-001).

PR 95A scope: define the official-curve governance boundary and implement the
parts that can be validated today with existing core validators:

- the model approval chain (``core.approval.require_matching_approval``);
- the outcome approval for ``curve_publication``
  (``core.outcome_approval.require_outcome_approval``) — official status
  requires ``curve_publication``, never ``model_fit``/``technical_reporting``
  alone;
- activity-definition non-omission (an official curve must supply them;
  omitting an optional argument must never bypass an official governance
  gate).

Deliberately NOT implemented here (wired by later PRs, per REQ-CURVE-001 and
the approved migration sequence):

- ``generate_official_curve`` — PR 95B (plus complete reference contexts,
  ``planning_support_eligible`` enforcement, and cost/currency binding);
- ``authorize_use`` — PR 95C (current-use revalidation and staleness);
- store-level import/migration/malformed-file audit — PR 95D.

No behaviour change to any existing generator. ``core.canonical_curves`` is
not called or modified by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from ancestry_mmm.core.approval import (
    ApprovalMismatchError,
    ModelApproval,
    ValidationPolicyBlockedError,
    require_matching_approval,
)
from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    OutcomeApprovalBlockedError,
    require_outcome_approval,
)
from ancestry_mmm.core.outcomes import OutcomeDefinition
from ancestry_mmm.core.validation_policy import ApprovalReadiness, ThresholdPolicy
from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact


class CurveGovernanceError(RuntimeError):
    """Base class for official-curve governance failures (REQ-CURVE-001)."""


class CurveModelApprovalError(CurveGovernanceError):
    """The model-approval chain is missing, mismatched, or not ready."""


class CurvePublicationApprovalError(CurveGovernanceError):
    """Official status requires a current, matching ``curve_publication`` approval."""


class CurveGovernanceMissingError(CurveGovernanceError):
    """A required governance input was omitted for an official curve."""


@dataclass(frozen=True)
class OfficialCurveGovernance:
    """Required inputs for an official curve (REQ-CURVE-001 governance chain).

    PR 95A validates the fields below. PR 95B extends this with reference
    context, support, cost/currency, and ``planning_support_eligible``
    enforcement; PR 95C adds the current-use revalidation inputs.
    """

    model_identity: ModelIdentity
    model_approval: ModelApproval
    outcome_definition: OutcomeDefinition
    outcome_approval: OutcomeApproval
    threshold_policy: Optional[ThresholdPolicy] = None
    approval_readiness: Optional[ApprovalReadiness] = None
    diagnostics_artefact: Optional[DiagnosticsArtefact] = None
    activity_definitions: Optional[Sequence[ActivityDefinition]] = None


class CurveService:
    """Application boundary for producing and persisting official curves.

    The service is the only intended entry point for official curve
    generation once PR 95B wires ``core.canonical_curves`` behind it. In
    PR 95A it exposes the governance validation the boundary must enforce.
    """

    def validate_official_governance(self, governance: OfficialCurveGovernance) -> None:
        """Require the full governance chain for official status.

        Raises a ``CurveGovernanceError`` subclass when any element is missing,
        mismatched, stale, expired, or not authorised for ``curve_publication``.

        - ``model_fit`` or ``technical_reporting`` approval alone never
          creates official status.
        - ``curve_publication`` does not grant any downstream use; those uses
          are validated separately at their own gates.
        """
        # 1. Model approval chain (identity, policy, readiness)
        try:
            require_matching_approval(
                governance.model_approval,
                model_run_id=governance.model_identity.model_run_id,
                data_fingerprint=governance.model_identity.data_fingerprint,
                model_spec_fingerprint=governance.model_identity.model_spec_fingerprint,
                posterior_fingerprint=governance.model_identity.posterior_fingerprint,
                approval_readiness=governance.approval_readiness,
                current_policy=governance.threshold_policy,
            )
        except (ApprovalMismatchError, ValidationPolicyBlockedError) as exc:
            raise CurveModelApprovalError(str(exc)) from exc

        # 2. Outcome approval for curve_publication (official status)
        try:
            require_outcome_approval(
                governance.outcome_definition,
                governance.outcome_approval,
                "curve_publication",
            )
        except OutcomeApprovalBlockedError as exc:
            raise CurvePublicationApprovalError(str(exc)) from exc

        # 3. Activity definitions must be supplied (non-omission; REQ-CURVE-001
        # governance chain). Omitting an optional argument must never bypass
        # an official governance gate.
        if governance.activity_definitions is None:
            raise CurveGovernanceMissingError(
                "Official curves require activity_definitions; omitting them must "
                "never bypass the official governance gate."
            )

    def generate_official_curve(
        self, governance: OfficialCurveGovernance, **kwargs: object
    ):
        """PR 95B wiring point: generate the official curve artifact.

        PR 95A defines the boundary only; this must not be called until the
        governance chain, complete reference contexts, ``planning_support_eligible``
        enforcement, and cost/currency binding are wired in PR 95B.
        """
        raise NotImplementedError(
            "generate_official_curve is the PR 95B wiring point; PR 95A defines the "
            "boundary only (no generator behaviour change)."
        )

    def authorize_use(
        self, artifact: object, requested_use: str, **current_governance: object
    ) -> bool:
        """PR 95C wiring point: current-use revalidation for an existing artifact.

        PR 95A defines the boundary only. Historical artifact integrity does
        not imply current authorization; this method will revalidate the
        artifact against live governance at every official use (PR 95C).
        """
        raise NotImplementedError(
            "authorize_use is the PR 95C current-use revalidation point; PR 95A "
            "defines the boundary only."
        )
