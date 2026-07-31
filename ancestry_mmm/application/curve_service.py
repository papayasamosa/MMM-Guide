"""CurveService — application boundary for official curve artifacts (REQ-CURVE-001).

PR 95A defined the boundary. PR 95B wires official generation through the
service and enforces the REQ-CURVE-001 creation-time contract:

- the governance chain is validated before generation (model approval,
  ``curve_publication`` outcome approval — never ``model_fit``/
  ``technical_reporting`` alone — and activity-definition non-omission);
- every reference context is validated for completeness against the exact
  fitted model metadata and parameter structure (missing keys fail closed,
  extra unknown keys are surfaced, zeros are explicit persisted values);
- ``generate_canonical_curve_draws`` is invoked with ``governance_mode=
  "official"`` and the governance's activity definitions bound (so the
  activity-approval check is never bypassed by omission);
- the strictest ``planning_support_eligible`` / ``planning_blocked_reason``
  state across all component rows and posterior draws is preserved, and the
  enforcement contract for planning/optimisation use is exposed.

PR 95C adds the current-use revalidation gate: ``authorize_use`` revalidates
an existing artifact against live governance at every official use —
historical artifact integrity does not imply current authorization.

Still wired by a later PR (per REQ-CURVE-001 / the approved migration
sequence):

- store-level import/migration/malformed-file audit — PR 95D.

No behaviour change to existing generators: the low-level
``core.canonical_curves.generate_canonical_curve_draws`` behaviour is
unchanged; the service is the new official entry point on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Tuple

import arviz as az
import pandas as pd

from ancestry_mmm.core.approval import (
    ApprovalMismatchError,
    ModelApproval,
    ValidationPolicyBlockedError,
    require_matching_approval,
)
from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.canonical_curves import (
    CurveReferenceContext,
    ReferenceContextIncompleteError,
    generate_canonical_curve_draws,
    validate_reference_context_completeness,
)
from ancestry_mmm.core.curve_artifact import (
    CURVE_CURRENT_AUTHORIZATION_STATUSES,
    CURVE_USE_ELIGIBILITY_STATUSES,
    CurveArtifact,
    CurveArtifactError,
    verify_curve_artifact_fingerprints,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import (
    extract_market_specific_posterior_params,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    OutcomeApprovalBlockedError,
    require_outcome_approval,
)
from ancestry_mmm.core.outcomes import OutcomeDefinition
from ancestry_mmm.core.predict import extract_posterior_params
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


class CurveReferenceContextIncompleteError(CurveGovernanceError):
    """Official curve blocked: a reference context does not cover the fitted model."""


class CurvePlanningIneligibleError(CurveGovernanceError):
    """Official planning/optimisation use blocked by missing planning support."""


class CurveUseNotAuthorizedError(CurveGovernanceError):
    """Official use of a curve artifact is not currently authorised.

    Raised by the use-time gate (``CurveService.authorize_use``) — fail
    closed whenever current governance cannot be resolved or any
    revalidation check fails.
    """


@dataclass(frozen=True)
class CurveUseAuthorization:
    """Result of a current-use revalidation (REQ-CURVE-001).

    ``current_authorization_status`` and ``requested_use_eligibility`` use
    the artifact lifecycle vocabulary (``core.curve_artifact``), which is
    deliberately separate from ``OUTCOME_APPROVAL_STATUSES``.
    """

    authorized: bool
    requested_use: str
    current_authorization_status: str
    requested_use_eligibility: str
    reason: str = ""

    def __post_init__(self) -> None:
        if (
            self.current_authorization_status
            not in CURVE_CURRENT_AUTHORIZATION_STATUSES
        ):
            raise ValueError("invalid current_authorization_status")
        if self.requested_use_eligibility not in CURVE_USE_ELIGIBILITY_STATUSES:
            raise ValueError("invalid requested_use_eligibility")


@dataclass(frozen=True)
class OfficialCurveGovernance:
    """Required inputs for an official curve (REQ-CURVE-001 governance chain).

    PR 95A defined these fields and PR 95B enforces them at generation time
    (see ``CurveService.generate_official_curve``). The computation inputs
    (model metadata, trace, reference contexts, cost/currency, support) are
    passed to the generation call separately, not stored here. PR 95C adds
    the current-use revalidation inputs.
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
    """Application boundary for producing official curves (REQ-CURVE-001).

    The service is the intended entry point for official curve generation: it
    validates the full governance chain, validates every reference context
    for completeness against the fitted model, then calls
    ``core.canonical_curves.generate_canonical_curve_draws`` in official mode
    with the governance's activity definitions bound.
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
        self,
        governance: OfficialCurveGovernance,
        *,
        meta: FHModelMeta,
        trace: az.InferenceData,
        reference_contexts: Mapping[str, CurveReferenceContext],
        model_type: str = "shared",
        params: Any = None,
        **generation_kwargs: Any,
    ) -> pd.DataFrame:
        """Generate an official curve through the service.

        Order of enforcement (REQ-CURVE-001):
        1. full governance chain (``validate_official_governance``);
        2. complete reference contexts against the fitted model structure;
        3. call ``generate_canonical_curve_draws`` with
           ``governance_mode="official"`` and the governance's
           ``activity_definitions`` bound (never omission-skippable);
        4. preserve the strictest ``planning_support_eligible`` state across
           all component rows and posterior draws (planning/optimisation
           enforcement is the use gate, ``enforce_planning_support``).

        ``params`` may be pre-extracted; otherwise it is derived from the
        trace via ``extract_posterior_params`` /
        ``extract_market_specific_posterior_params``.
        """
        self.validate_official_governance(governance)
        if params is None:
            params = (
                extract_market_specific_posterior_params(trace, meta)
                if model_type == "market_specific"
                else extract_posterior_params(trace, meta)
            )
        self.validate_reference_contexts(reference_contexts, meta, params)
        kwargs = dict(generation_kwargs)
        kwargs["governance_mode"] = "official"
        kwargs["activity_definitions"] = governance.activity_definitions
        draws = generate_canonical_curve_draws(
            model_run_id=governance.model_identity.model_run_id,
            meta=meta,
            trace=trace,
            reference_contexts=reference_contexts,
            model_type=model_type,
            **kwargs,
        )
        # Preserve the strictest planning-support state; raises if the draws
        # are missing the fields or carry empty reasons on ineligible rows.
        self.planning_support_state(draws)
        return draws

    def validate_reference_contexts(
        self,
        contexts: Mapping[str, CurveReferenceContext],
        meta: FHModelMeta,
        params: Any,
    ) -> None:
        """Validate every reference context against the fitted model structure.

        Raises ``CurveReferenceContextIncompleteError`` (a
        ``CurveGovernanceError``) naming the first incomplete context.
        """
        for context in contexts.values():
            try:
                validate_reference_context_completeness(context, meta, params)
            except ReferenceContextIncompleteError as exc:
                raise CurveReferenceContextIncompleteError(
                    f"Reference context '{context.reference_context_id}' is "
                    f"incomplete: {exc}"
                ) from exc

    def planning_support_state(self, draws: pd.DataFrame) -> Tuple[bool, str]:
        """Return ``(all_eligible, blocked_reason)`` across all component rows
        and posterior draws — the strictest state (any ineligible row makes
        the artifact ineligible for planning/optimisation).

        Raises ``CurveGovernanceError`` if the fields are absent, or
        ``CurvePlanningIneligibleError`` if an ineligible row carries an
        empty ``planning_blocked_reason`` (REQ-CURVE-001 requires a
        non-empty reason whenever eligibility is false).
        """
        if "planning_support_eligible" not in draws.columns:
            raise CurveGovernanceError("draws are missing planning_support_eligible")
        if "planning_blocked_reason" not in draws.columns:
            raise CurveGovernanceError("draws are missing planning_blocked_reason")
        eligible_mask = draws["planning_support_eligible"].fillna(False).astype(bool)
        if bool(eligible_mask.all()):
            return True, ""
        ineligible = draws.loc[~eligible_mask]
        reasons = ineligible["planning_blocked_reason"]
        blank = reasons.isna() | (reasons.astype(str).str.strip() == "")
        if bool(blank.any()):
            raise CurvePlanningIneligibleError(
                "Ineligible draw rows must carry a non-empty planning_blocked_reason"
            )
        reason = "; ".join(sorted(set(reasons.astype(str))))
        return False, reason

    def enforce_planning_support(
        self, draws: pd.DataFrame, *, requested_use: str
    ) -> bool:
        """Enforce ``planning_support_eligible`` for a planning/optimisation use.

        Raises ``CurvePlanningIneligibleError`` when the requested use is
        ``planning`` or ``optimisation`` and any row is ineligible. Other
        official uses do not gate on the flag but must still preserve the
        strictest state (see ``planning_support_state``).
        """
        eligible, reason = self.planning_support_state(draws)
        if requested_use in {"planning", "optimisation"} and not eligible:
            raise CurvePlanningIneligibleError(
                f"Official {requested_use} use is blocked: planning support is "
                f"missing (planning_blocked_reason: {reason or 'unspecified'})."
            )
        return eligible

    def authorize_use(
        self,
        artifact: CurveArtifact,
        requested_use: str,
        *,
        current_governance: OfficialCurveGovernance,
        staleness_cutoff: Optional[str] = None,
    ) -> CurveUseAuthorization:
        """Revalidate an artifact against current governance for a requested use.

        REQ-CURVE-001 current official-use authorization: historical artifact
        integrity does not imply current authorization. This is the use-time
        gate, evaluated at every official use:

        1. re-verify the artifact's historical integrity (chain fingerprints);
        2. the artifact's model identity must match the current model, and the
           current model approval chain (identity/policy/readiness) must pass;
        3. the artifact's outcome definition must still match the current
           outcome definition (not stale), and a current, matching outcome
           approval must allow the requested use;
        4. current activity definitions must be resolvable and approved;
        5. planning/optimisation uses additionally enforce
           ``planning_support_eligible`` on the artifact's draws;
        6. when ``staleness_cutoff`` is provided, an artifact created before
           it is not currently authorised.

        Raises ``CurveUseNotAuthorizedError`` (fail closed) when any check
        fails or current governance cannot be resolved. Never rewrites the
        artifact's historical evidence.
        """
        # 1. Historical integrity (immutable evidence must still verify)
        try:
            verify_curve_artifact_fingerprints(artifact.metadata)
        except CurveArtifactError as exc:
            raise CurveUseNotAuthorizedError(
                f"Artifact historical integrity is not intact: {exc}"
            ) from exc

        identity = current_governance.model_identity
        identity_snapshot = artifact.metadata.model_identity_snapshot
        if not (
            identity_snapshot.get("model_run_id") == identity.model_run_id
            and identity_snapshot.get("data_fingerprint") == identity.data_fingerprint
            and identity_snapshot.get("model_spec_fingerprint")
            == identity.model_spec_fingerprint
            and identity_snapshot.get("posterior_fingerprint")
            == identity.posterior_fingerprint
        ):
            raise CurveUseNotAuthorizedError(
                "Artifact model identity does not match the current model "
                "(the artifact is stale for the current model)."
            )

        # 2. Current model approval chain (identity, policy, readiness)
        try:
            require_matching_approval(
                current_governance.model_approval,
                model_run_id=identity.model_run_id,
                data_fingerprint=identity.data_fingerprint,
                model_spec_fingerprint=identity.model_spec_fingerprint,
                posterior_fingerprint=identity.posterior_fingerprint,
                approval_readiness=current_governance.approval_readiness,
                current_policy=current_governance.threshold_policy,
            )
        except (ApprovalMismatchError, ValidationPolicyBlockedError) as exc:
            raise CurveUseNotAuthorizedError(str(exc)) from exc

        # 3. Outcome definition not stale + current approval allows the
        #    requested use (the current approval is authoritative; the
        #    artifact's snapshot is historical evidence, never rewritten).
        definition_snapshot = artifact.metadata.outcome_definition_snapshot
        current_outcome = current_governance.outcome_definition
        if definition_snapshot.get("outcome_id") != current_outcome.outcome_id:
            raise CurveUseNotAuthorizedError(
                "Artifact outcome does not match the current outcome definition."
            )
        if (
            definition_snapshot.get("definition_version")
            != current_outcome.definition_version
        ):
            raise CurveUseNotAuthorizedError(
                "Artifact outcome definition has changed since creation (stale)."
            )
        try:
            require_outcome_approval(
                current_outcome,
                current_governance.outcome_approval,
                requested_use,
            )
        except OutcomeApprovalBlockedError as exc:
            raise CurveUseNotAuthorizedError(str(exc)) from exc

        # 4. Current activity governance must be resolvable and approved
        activities = current_governance.activity_definitions
        if not activities:
            raise CurveUseNotAuthorizedError(
                "Current activity definitions are unavailable; current governance "
                "cannot be resolved (fail closed)."
            )
        unapproved = sorted(
            a.activity_id for a in activities if a.approval_status != "approved"
        )
        if unapproved:
            raise CurveUseNotAuthorizedError(
                f"Current activity definitions are not approved: {unapproved}"
            )

        # 5. Planning/optimisation uses enforce planning support on the draws
        if requested_use in {"planning", "optimisation"}:
            self.enforce_planning_support(artifact.draws, requested_use=requested_use)

        # 6. Staleness cutoff
        if staleness_cutoff is not None:
            try:
                created = datetime.fromisoformat(
                    artifact.metadata.creation_timestamp.replace("Z", "+00:00")
                )
                cutoff = datetime.fromisoformat(staleness_cutoff.replace("Z", "+00:00"))
            except (ValueError, TypeError, AttributeError) as exc:
                raise CurveUseNotAuthorizedError(
                    f"Cannot resolve staleness_cutoff {staleness_cutoff!r}: {exc}"
                ) from exc
            if created < cutoff:
                raise CurveUseNotAuthorizedError(
                    f"Artifact predates staleness cutoff {staleness_cutoff}."
                )

        return CurveUseAuthorization(
            authorized=True,
            requested_use=requested_use,
            current_authorization_status="authorized",
            requested_use_eligibility="eligible",
        )
