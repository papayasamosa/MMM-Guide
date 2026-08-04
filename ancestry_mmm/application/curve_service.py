"""CurveService — application boundary for official curve artifacts (REQ-CURVE-001).

``CurveService`` is the official application boundary for producing and
persisting official response-curve artifacts. No other code path may
generate or write an artifact and have it treated as official (REQ-CURVE-001
"Single source of authority"). Everything below this line is implemented and
in production use — none of it is future work:

- **Governance chain (PR 95A/95B, closed out by PR 96A):**
  ``validate_official_governance`` requires the complete REQ-CURVE-001
  evidence chain before any official generation — model identity, a
  policy-backed ``ModelApproval`` (a model-bound-only approval with a blank
  ``validation_policy_id`` is never sufficient), a current ``ThresholdPolicy``,
  a current, matching ``ApprovalReadiness``, a ``DiagnosticsArtefact`` that
  matches both the readiness binding and the current model identity, a
  current ``curve_publication`` outcome approval, and approved activity
  definitions. None of these is an optional pass-through a caller can omit
  to bypass the gate (see ``_require_governance_chain``, shared with
  ``authorize_use`` so both checkpoints apply the identical structural gate).
- **Official generation (PR 95B):** ``generate_official_curve`` validates
  every reference context for completeness against the fitted model, then
  calls ``generate_canonical_curve_draws`` with ``governance_mode="official"``
  and the governance's activity definitions bound (never omission-skippable),
  preserving the strictest ``planning_support_eligible`` /
  ``planning_blocked_reason`` state across all component rows and posterior
  draws.
- **Current-use revalidation (PR 95C):** ``authorize_use`` revalidates an
  existing artifact against *live* governance at every official use —
  historical artifact integrity never implies current authorization.
- **Official artifact creation and persistence (PR 96A):**
  ``create_official_artifact`` is the only supported application boundary
  for producing a newly persisted official curve artifact: it generates
  governed draws, builds the approved channel-safe summary view, stamps
  immutable creation-time evidence snapshots from the validated governance
  (never from a caller-supplied fingerprint), and writes/verifies/promotes
  the artifact atomically (see ``ancestry_mmm.core.curve_artifact``, whose
  store-level import, migration, and malformed-file audit shipped in PR 95D,
  whose display in the Results / Curve Bank page shipped in PR 95E).

The legacy ``core.curve_bank.CurveBankEntry`` registry (labelled as fitted
parameter snapshots since PR 95F) is not an official evaluated-curve store
and is never a substitute for an artifact produced by this service.

No behaviour change to existing generators: the low-level
``core.canonical_curves.generate_canonical_curve_draws`` behaviour is
unchanged; the service is the official entry point on top of it.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

import arviz as az
import numpy as np
import pandas as pd

from ancestry_mmm.core.approval import (
    ApprovalMismatchError,
    ModelApproval,
    ValidationPolicyBlockedError,
    require_matching_approval,
)
from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_definitions_fingerprint,
)
from ancestry_mmm.core.canonical_curves import (
    CurveReferenceContext,
    ReferenceContextIncompleteError,
    canonical_governance_views,
    generate_canonical_curve_draws,
    summarize_curve_draws,
    validate_reference_context_completeness,
)
from ancestry_mmm.core.curve_artifact import (
    CURVE_ARTIFACT_DRAWS_FILENAME,
    CURVE_ARTIFACT_GENERATOR_VERSION,
    CURVE_ARTIFACT_METADATA_FILENAME,
    CURVE_ARTIFACT_SUMMARIES_FILENAME,
    CURVE_CURRENT_AUTHORIZATION_STATUSES,
    CURVE_USE_ELIGIBILITY_STATUSES,
    CurveArtifact,
    CurveArtifactError,
    CurveArtifactMetadata,
    compute_curve_artifact_fingerprints,
    read_curve_artifact,
    verify_curve_artifact_fingerprints,
    write_curve_artifact,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import (
    extract_market_specific_posterior_params,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    OutcomeApprovalBlockedError,
    normalise_datetime,
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


class CurveDiagnosticsArtefactError(CurveGovernanceError):
    """The supplied diagnostics artefact does not match the readiness
    binding or the current model identity (REQ-CURVE-001 Work package A)."""


class CurveArtifactAlreadyExistsError(CurveGovernanceError):
    """An official artifact already exists at the requested artifact ID.

    Official artifacts are never silently overwritten (REQ-CURVE-001 Work
    package B).
    """


class CurveArtifactUnsafeIdError(CurveGovernanceError):
    """``artifact_id`` is not a single safe path component.

    Raised before anything touches disk, so a caller can never escape the
    configured artifact store via ``..``, an absolute path, a drive prefix,
    a path separator, or a reserved Windows device name (Corrective PR A1).
    """


# Windows reserved device names (case-insensitive, extension-insensitive) —
# a path component matching one of these is invalid regardless of platform,
# since artifact stores must remain portable across the repository's
# Windows-first tooling.
_RESERVED_WINDOWS_ARTIFACT_ID_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _validate_safe_artifact_id(artifact_id: str) -> None:
    """Reject any ``artifact_id`` that is not a single safe path component.

    Corrective PR A1: ``artifact_id`` is joined onto the configured
    ``store_dir`` (and used as a ``tempfile.mkdtemp`` prefix) to build the
    on-disk path for an official artifact. Blankness alone is not a
    sufficient check — ``..``, an absolute path, or a drive prefix can make
    the resolved destination escape ``store_dir`` entirely.
    """
    if not artifact_id or not artifact_id.strip():
        raise CurveArtifactUnsafeIdError("artifact_id must be non-blank")
    candidate = artifact_id.strip()
    if candidate != artifact_id:
        raise CurveArtifactUnsafeIdError(
            f"artifact_id must not have leading/trailing whitespace: {artifact_id!r}"
        )
    if candidate in (".", ".."):
        raise CurveArtifactUnsafeIdError(
            f"artifact_id must not be '.' or '..': {artifact_id!r}"
        )
    if "/" in candidate or "\\" in candidate:
        raise CurveArtifactUnsafeIdError(
            f"artifact_id must be a single path component (no separators): "
            f"{artifact_id!r}"
        )
    if ":" in candidate:
        raise CurveArtifactUnsafeIdError(
            f"artifact_id must not contain a drive prefix: {artifact_id!r}"
        )
    if Path(candidate).is_absolute():
        raise CurveArtifactUnsafeIdError(
            f"artifact_id must not be an absolute path: {artifact_id!r}"
        )
    stem = candidate.split(".", 1)[0].upper()
    if stem in _RESERVED_WINDOWS_ARTIFACT_ID_STEMS:
        raise CurveArtifactUnsafeIdError(
            f"artifact_id must not be a reserved device name: {artifact_id!r}"
        )


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

    PR 95A defined these fields; PR 95B wired generation-time enforcement.
    PR 96A (this record) closes the structural gap: every element below is a
    required field, not an optionally-omittable one with best-effort
    validation layered on top. ``threshold_policy``, ``approval_readiness``,
    ``diagnostics_artefact``, and ``activity_definitions`` were previously
    ``Optional[...] = None`` — a caller could construct a "complete"
    governance object while omitting all four, and ``model_approval`` could
    be model-bound without ever being policy-backed
    (``validation_policy_id`` blank). Both gaps let a non-policy-backed
    approval pass as an official governance chain. ``validate_official_governance``
    and ``authorize_use`` now reject any of these that are missing, blank, or
    unbound (see ``CurveGovernanceMissingError`` / ``CurveModelApprovalError``
    / ``CurveDiagnosticsArtefactError``) — never a silent pass.

    The computation inputs (model metadata, trace, reference contexts,
    cost/currency, support) are passed to the generation call separately,
    not stored here.
    """

    model_identity: ModelIdentity
    model_approval: ModelApproval
    outcome_definition: OutcomeDefinition
    outcome_approval: OutcomeApproval
    threshold_policy: ThresholdPolicy
    approval_readiness: ApprovalReadiness
    diagnostics_artefact: DiagnosticsArtefact
    activity_definitions: Sequence[ActivityDefinition]


@dataclass(frozen=True)
class OfficialArtifactCreationResult:
    """Result of ``CurveService.create_official_artifact`` (REQ-CURVE-001
    Work package B): the verified artifact plus its final storage paths."""

    artifact: CurveArtifact
    artifact_id: str
    directory: Path
    metadata_path: Path
    draws_path: Path
    summaries_path: Path


def _json_default(value: Any) -> Any:
    """``json.dumps(default=...)`` hook for numpy scalars/arrays found in
    canonical curve draws when building metadata evidence snapshots."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Object of type {type(value)!r} is not JSON serialisable")


def _json_safe_records(
    draws: pd.DataFrame, columns: Sequence[str]
) -> List[Dict[str, object]]:
    """Deterministic, deduplicated, JSON-safe rows for a metadata snapshot.

    Columns absent from ``draws`` are skipped rather than raised on: the
    snapshot documents whatever evidence the actual generation call
    produced, never a caller-asserted shape.
    """
    present = [column for column in columns if column in draws.columns]
    if not present:
        return []
    subset = (
        draws[present].drop_duplicates().sort_values(present).reset_index(drop=True)
    )
    encoded = json.dumps(
        subset.to_dict(orient="records"), default=_json_default, sort_keys=True
    )
    decoded: List[Dict[str, object]] = json.loads(encoded)
    return decoded


def _artifact_scopes(draws: pd.DataFrame) -> List[Dict[str, Optional[str]]]:
    """Every distinct (market, product, segment) scope represented by an
    artifact's own draw rows (Corrective PR B3).

    An outcome approval scoped to only some of these must not authorize use
    of an artifact whose rows span other markets/products/segments too -
    resolving/validating a single unscoped approval is not sufficient for a
    multi-scope artifact.
    """
    scope_columns = ["market", "product", "segment"]
    present = [c for c in scope_columns if c in draws.columns]
    if not present:
        return [{}]
    unique = draws[present].drop_duplicates()
    return [
        {column: row[column] for column in present}
        for row in unique.to_dict(orient="records")
    ]


def _require_governance_chain(governance: OfficialCurveGovernance) -> None:
    """Validate the complete REQ-CURVE-001 governance chain.

    Shared by ``CurveService.validate_official_governance`` (generation time)
    and ``CurveService.authorize_use`` (current-use time) so the identical
    structural gate applies at both checkpoints — reusing
    ``require_matching_approval`` rather than a second, inconsistent
    approval implementation. Raises a ``CurveGovernanceError`` subclass and
    never silently passes when an element is missing, blank, unbound, or
    mismatched:

    - ``threshold_policy``, ``approval_readiness``, ``diagnostics_artefact``,
      and ``activity_definitions`` must all be present (never optional
      pass-throughs a caller can omit).
    - ``model_approval`` must be policy-backed (``validation_policy_id``
      non-blank) and pass ``require_matching_approval`` (model identity,
      proof-field completeness, readiness fingerprint/model-identity
      match, ``overall_ready``, current policy identity/fingerprint/
      activity).
    - ``diagnostics_artefact`` must match the readiness binding
      (``diagnostic_artefact_id`` / ``diagnostic_artefact_fingerprint``) and
      the current model identity.
    - Every activity definition must be ``approval_status == "approved"``.
    """
    if governance.threshold_policy is None:
        raise CurveGovernanceMissingError(
            "Official curves require threshold_policy; current governance "
            "cannot be resolved without it (omission must never bypass the "
            "official governance gate)."
        )
    if governance.approval_readiness is None:
        raise CurveGovernanceMissingError(
            "Official curves require approval_readiness; current governance "
            "cannot be resolved without it (omission must never bypass the "
            "official governance gate)."
        )
    if governance.diagnostics_artefact is None:
        raise CurveGovernanceMissingError(
            "Official curves require diagnostics_artefact; current governance "
            "cannot be resolved without it (omission must never bypass the "
            "official governance gate)."
        )
    if not governance.activity_definitions:
        raise CurveGovernanceMissingError(
            "Official curves require activity_definitions; current governance "
            "cannot be resolved without them (omission must never bypass the "
            "official governance gate)."
        )
    # A non-model-bound approval (no run_id/fingerprints at all) is caught
    # below by require_matching_approval's own "predates model-bound
    # approval" check. This check targets the narrower gap: an approval that
    # *is* model-bound but was never made policy-backed (validation_policy_id
    # blank) — require_matching_approval alone treats that as fully valid
    # (backward compatible), which is exactly the structural gap this PR
    # closes.
    if governance.model_approval.is_model_bound() and not (
        governance.model_approval.validation_policy_id
    ):
        raise CurveModelApprovalError(
            "Official curves require a policy-backed ModelApproval "
            "(validation_policy_id is blank); a model-bound-only approval is "
            "not sufficient for official status."
        )
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

    model_identity_fingerprint = governance.model_identity.fingerprint()
    if governance.diagnostics_artefact.model_identity_fingerprint != (
        model_identity_fingerprint
    ):
        raise CurveDiagnosticsArtefactError(
            "Diagnostics artefact model identity does not match the current "
            "model identity."
        )
    if (
        governance.approval_readiness.diagnostic_artefact_id
        != governance.diagnostics_artefact.artefact_id
    ):
        raise CurveDiagnosticsArtefactError(
            "Approval readiness diagnostic_artefact_id does not match the "
            "supplied diagnostics artefact."
        )
    if (
        governance.approval_readiness.diagnostic_artefact_fingerprint
        != governance.diagnostics_artefact.fingerprint()
    ):
        raise CurveDiagnosticsArtefactError(
            "Approval readiness diagnostic_artefact_fingerprint does not "
            "match the supplied diagnostics artefact."
        )

    unapproved = sorted(
        a.activity_id
        for a in governance.activity_definitions
        if a.approval_status != "approved"
    )
    if unapproved:
        raise CurveGovernanceMissingError(
            "Official curves require approved activity governance; activity "
            f"definitions are not approved: {unapproved}"
        )


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
        - A model-bound-but-not-policy-backed ``ModelApproval`` (blank
          ``validation_policy_id``) is never sufficient for official status.
        """
        _require_governance_chain(governance)

        # Outcome approval for curve_publication (official status)
        try:
            require_outcome_approval(
                governance.outcome_definition,
                governance.outcome_approval,
                "curve_publication",
            )
        except OutcomeApprovalBlockedError as exc:
            raise CurvePublicationApprovalError(str(exc)) from exc

    def generate_official_curve(
        self,
        governance: OfficialCurveGovernance,
        *,
        meta: FHModelMeta,
        trace: az.InferenceData,
        reference_contexts: Mapping[str, CurveReferenceContext],
        model_type: str = "shared",
        **generation_kwargs: Any,
    ) -> pd.DataFrame:
        """Generate an official curve through the service.

        Order of enforcement (REQ-CURVE-001):
        1. full governance chain (``validate_official_governance``);
        2. complete reference contexts against the fitted model structure,
           validated against parameters derived fresh from ``trace``/``meta``
           (never a caller-supplied override — Corrective PR B, "derive
           context structure from the trace being generated": the low-level
           generator always re-derives its own parameters per draw from
           ``trace`` regardless, so an override here could only desynchronise
           validation from what is actually generated, never legitimately
           change it);
        3. call ``generate_canonical_curve_draws`` with
           ``governance_mode="official"`` and the governance's
           ``activity_definitions`` bound (never omission-skippable);
        4. restrict the result to the single outcome
           ``governance.outcome_definition.outcome_id`` this governance
           actually approves (Corrective PR B2, "bind approval to each
           generated outcome" — one official artifact represents exactly one
           approved outcome; a jointly-fitted model's *other* outcomes are
           never included merely because they share a trace, since they
           have no approval of their own here);
        5. preserve the strictest ``planning_support_eligible`` state across
           all component rows and posterior draws (planning/optimisation
           enforcement is the use gate, ``enforce_planning_support``).
        """
        self.validate_official_governance(governance)
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
        approved_outcome_id = governance.outcome_definition.outcome_id
        if "outcome_id" in draws.columns:
            if approved_outcome_id not in set(draws["outcome_id"]):
                raise CurveGovernanceMissingError(
                    f"Approved outcome '{approved_outcome_id}' was not generated "
                    "by this model (meta.outcome_ids does not include it)."
                )
            draws = draws[draws["outcome_id"] == approved_outcome_id].reset_index(
                drop=True
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
        2. the artifact's model identity must match the current model;
        3. the complete current governance chain must be satisfied — model
           approval (identity/policy-backed/readiness), the diagnostics
           artefact binding, and approved activity definitions (the same
           structural gate ``validate_official_governance`` applies at
           generation time; see ``_require_governance_chain``) — **and**
           the supplied activity definitions must be the artifact's own
           (fingerprint-matched against ``activity_governance_snapshot``,
           not merely approved activities of any kind);
        4. the artifact's outcome definition must still match the current
           outcome definition (not stale), and for every distinct
           market/product/segment scope the artifact's rows actually span,
           a current, matching outcome approval must independently grant
           both ``curve_publication`` (the artifact's own official status —
           checked regardless of the requested use) and the specific
           requested use;
        5. planning/optimisation uses additionally enforce
           ``planning_support_eligible`` on the artifact's draws;
        6. when ``staleness_cutoff`` is provided, both it and the artifact's
           creation timestamp are normalised to timezone-aware UTC before
           comparison, and an artifact created before the cutoff is not
           currently authorised.

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

        # 2. Current full governance chain: model approval (identity, policy,
        #    readiness), diagnostics-artefact binding, and activity approval
        #    — the same structural gate as generation time (never optional).
        try:
            _require_governance_chain(current_governance)
        except CurveGovernanceError as exc:
            raise CurveUseNotAuthorizedError(str(exc)) from exc

        # 3. The supplied activities must be the artifact's OWN activities,
        #    not merely approved activities of any kind (Corrective PR B4):
        #    compare against the fingerprint the artifact was actually
        #    generated with (activity_governance_snapshot), the same
        #    fingerprint _build_artifact_metadata records at creation time.
        current_activity_fingerprint = activity_definitions_fingerprint(
            current_governance.activity_definitions
        )
        snapshot_activity_fingerprint = (
            artifact.metadata.activity_governance_snapshot or {}
        ).get("fingerprint")
        if current_activity_fingerprint != snapshot_activity_fingerprint:
            raise CurveUseNotAuthorizedError(
                "Current activity definitions do not match the activities "
                "this artifact was actually generated against (activity "
                "governance is stale or unrelated)."
            )

        # 4. Outcome definition not stale, and — for EVERY distinct
        #    market/product/segment scope the artifact's own rows actually
        #    span (Corrective PR B3) — a current, matching approval that
        #    (a) still grants curve_publication (the artifact's official
        #    status itself, Corrective PR B1 — checked independently of the
        #    requested use, since a replacement approval can grant a
        #    downstream use while no longer granting official status) and
        #    (b) grants the specific requested_use. The current approval is
        #    authoritative; the artifact's snapshot is historical evidence,
        #    never rewritten.
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
        for scope in _artifact_scopes(artifact.draws):
            try:
                require_outcome_approval(
                    current_outcome,
                    current_governance.outcome_approval,
                    "curve_publication",
                    **scope,
                )
            except OutcomeApprovalBlockedError as exc:
                raise CurveUseNotAuthorizedError(
                    f"Artifact is no longer currently authorised as official "
                    f"(curve_publication) for scope {scope}: {exc}"
                ) from exc
            try:
                require_outcome_approval(
                    current_outcome,
                    current_governance.outcome_approval,
                    requested_use,
                    **scope,
                )
            except OutcomeApprovalBlockedError as exc:
                raise CurveUseNotAuthorizedError(str(exc)) from exc

        # 5. Planning/optimisation uses enforce planning support on the draws
        if requested_use in {"planning", "optimisation"}:
            self.enforce_planning_support(artifact.draws, requested_use=requested_use)

        # 6. Staleness cutoff — both timestamps normalised to timezone-aware
        #    UTC before comparison (Corrective PR B7), so a naive/aware
        #    mismatch never raises an uncaught TypeError in place of the
        #    documented CurveUseNotAuthorizedError.
        if staleness_cutoff is not None:
            try:
                created = normalise_datetime(artifact.metadata.creation_timestamp)
                cutoff = normalise_datetime(staleness_cutoff)
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

    def resolve_current_governance(
        self,
        artifact: CurveArtifact,
        *,
        current_identity: Optional[Mapping[str, str]],
        approval_dict: Optional[Mapping[str, Any]],
        current_policy: Optional[ThresholdPolicy],
        current_readiness: Optional[ApprovalReadiness],
        current_diagnostics_artefact: Optional[DiagnosticsArtefact],
        activity_definitions: Sequence[ActivityDefinition],
        outcome_definitions: Sequence[OutcomeDefinition],
        outcome_approvals: Sequence[OutcomeApproval],
    ) -> Optional[OfficialCurveGovernance]:
        """Resolve current governance for one official artifact from
        whatever evidence a caller (a Streamlit page, the project-export
        boundary, a script) currently has in hand.

        Returns ``None`` when the artifact's current model identity,
        current model approval, or a matching current outcome/outcome
        approval cannot be resolved at all — the artifact should then be
        treated as blocked/ungoverned by the caller, never rendered or
        reported as currently authorized.

        ``current_policy``/``current_readiness``/``current_diagnostics_artefact``
        are deliberately **not** required to be non-``None`` here: when any
        of them is unavailable, an ``OfficialCurveGovernance`` is still
        constructed (with that field ``None``, despite the dataclass's
        declared type — the same tolerance ``_require_governance_chain``
        already checks for defensively) so the caller's subsequent
        ``authorize_use`` call raises the specific, actionable
        ``CurveGovernanceMissingError`` (e.g. "Official curves require
        threshold_policy...") instead of this function collapsing every
        missing-evidence case into one generic "cannot be resolved" message.
        Both call sites (below) wrap ``authorize_use`` in a
        ``CurveGovernanceError`` handler and fail closed either way.

        This is the one shared resolution path for every caller that needs
        to revalidate an artifact against *live* governance outside of
        generation — used by both the Results / Curve Bank page and the
        Project Export page's report/Excel authorization-status exposure,
        so the resolution logic is never duplicated a second time.
        """
        snapshot = artifact.metadata.outcome_definition_snapshot or {}
        outcome_id = snapshot.get("outcome_id")
        if not current_identity or not approval_dict or not outcome_definitions:
            return None
        outcome = next(
            (o for o in outcome_definitions if o.outcome_id == outcome_id), None
        )
        approval = next(
            (a for a in outcome_approvals if a.outcome_id == outcome_id), None
        )
        if outcome is None or approval is None:
            return None
        return OfficialCurveGovernance(
            model_identity=ModelIdentity(**current_identity),
            model_approval=ModelApproval.from_dict(dict(approval_dict)),
            outcome_definition=outcome,
            outcome_approval=approval,
            # cast: these three may genuinely be None at runtime (see
            # docstring above) — _require_governance_chain checks for that
            # explicitly and fails closed; the dataclass's non-Optional
            # annotation documents the *steady-state* requirement, not a
            # runtime guarantee this resolver can make.
            threshold_policy=cast(ThresholdPolicy, current_policy),
            approval_readiness=cast(ApprovalReadiness, current_readiness),
            diagnostics_artefact=cast(
                DiagnosticsArtefact, current_diagnostics_artefact
            ),
            activity_definitions=activity_definitions,
        )

    # -------------------------------------------------------------------
    # Official artifact creation and persistence (REQ-CURVE-001 Work
    # package B) — the only supported application boundary for producing a
    # newly persisted official curve artifact.
    # -------------------------------------------------------------------

    def create_official_artifact(
        self,
        governance: OfficialCurveGovernance,
        *,
        artifact_id: str,
        store_dir: Path,
        meta: FHModelMeta,
        trace: az.InferenceData,
        reference_contexts: Mapping[str, CurveReferenceContext],
        model_type: str = "shared",
        creation_timestamp: Optional[str] = None,
        value_per_response: Optional[Mapping[str, float]] = None,
        **generation_kwargs: Any,
    ) -> OfficialArtifactCreationResult:
        """Generate and persist a new official curve artifact.

        The only supported application boundary for producing a newly
        persisted official curve artifact (REQ-CURVE-001 Work package B).
        Sequence:

        1. reject the call outright if ``artifact_id`` already exists in
           ``store_dir`` (an official artifact is never silently
           overwritten);
        2. generate canonical posterior draws via
           ``generate_official_curve`` — this validates the complete
           governance chain and every reference context's completeness,
           invokes ``generate_canonical_curve_draws`` in official mode with
           the governance's activity definitions bound, and preserves the
           strictest ``planning_support_eligible`` state;
        3. build the persisted summary table as the approved channel-safe
           "segment" governance view (``canonical_governance_views``:
           direct + cross-product components reconciled into channel-total
           economics, REQ-CURVE-001 "Channel-total economics remain
           authoritative") summarized across posterior draws
           (``summarize_curve_draws``) — this is the one persisted summary
           grain (Work package C), matching
           ``CURVE_ARTIFACT_SUMMARY_REQUIRED_COLUMNS``;
        4. build immutable creation-time evidence snapshots from the
           *validated* governance objects and the actually-generated draws
           — never from a caller-supplied fingerprint;
        5. write metadata + draws + summaries into a temporary directory
           beneath ``store_dir``, read the artifact back, and verify every
           table and metadata fingerprint;
        6. atomically rename the verified temporary directory into its
           final ``artifact_id`` directory.

        On any failure the temporary directory is removed and no partial
        final artifact is left; an existing artifact ID is never
        overwritten, silently or otherwise.
        """
        _validate_safe_artifact_id(artifact_id)
        store_dir = Path(store_dir)
        final_dir = store_dir / artifact_id
        resolved_store_dir = store_dir.resolve()
        if final_dir.resolve().parent != resolved_store_dir:
            # Defense in depth beyond _validate_safe_artifact_id's component-
            # level checks: verify the resolved destination is still a
            # direct child of the configured store before anything is
            # written (Corrective PR A1).
            raise CurveArtifactUnsafeIdError(
                f"artifact_id {artifact_id!r} must resolve to a direct child of "
                f"the configured artifact store {store_dir}"
            )
        if final_dir.exists():
            raise CurveArtifactAlreadyExistsError(
                f"Curve artifact '{artifact_id}' already exists at {final_dir}; "
                "official artifacts are never silently overwritten."
            )

        draws = self.generate_official_curve(
            governance,
            meta=meta,
            trace=trace,
            reference_contexts=reference_contexts,
            model_type=model_type,
            **generation_kwargs,
        )

        # Work package C: the approved channel-safe governance view,
        # summarized across posterior draws after draw-level response and
        # economics have been calculated (never parameters summarized
        # before response calculation).
        channel_view = canonical_governance_views(
            draws, value_per_response=value_per_response
        )["segment"]
        summaries = summarize_curve_draws(channel_view)

        timestamp = creation_timestamp or datetime.now(timezone.utc).isoformat()
        metadata = self._build_artifact_metadata(
            artifact_id=artifact_id,
            creation_timestamp=timestamp,
            governance=governance,
            reference_contexts=reference_contexts,
            draws=draws,
        )

        store_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(
            tempfile.mkdtemp(prefix=f".{artifact_id}.tmp-", dir=str(store_dir))
        )
        wrote_successfully = False
        try:
            write_curve_artifact(
                tmp_dir, metadata=metadata, draws=draws, summaries=summaries
            )
            read_curve_artifact(tmp_dir)  # verify before promotion; fails closed
            wrote_successfully = True
        finally:
            if not wrote_successfully:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        if final_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise CurveArtifactAlreadyExistsError(
                f"Curve artifact '{artifact_id}' already exists at {final_dir}; "
                "official artifacts are never silently overwritten."
            )
        try:
            tmp_dir.rename(final_dir)
        except FileExistsError:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise CurveArtifactAlreadyExistsError(
                f"Curve artifact '{artifact_id}' already exists at {final_dir}; "
                "official artifacts are never silently overwritten."
            ) from None

        try:
            verified = read_curve_artifact(final_dir)
        except CurveArtifactError:
            # Post-promotion verification failed after the atomic rename
            # already succeeded. Remove the promoted directory rather than
            # leaving it behind: a leftover final_dir would otherwise
            # permanently block a retry with this artifact_id (the
            # already-exists guard above) and later surface as a malformed
            # entry in the store's audit instead of a clean retry
            # opportunity (Corrective PR A4).
            shutil.rmtree(final_dir, ignore_errors=True)
            raise
        return OfficialArtifactCreationResult(
            artifact=verified,
            artifact_id=artifact_id,
            directory=final_dir,
            metadata_path=final_dir / CURVE_ARTIFACT_METADATA_FILENAME,
            draws_path=final_dir / CURVE_ARTIFACT_DRAWS_FILENAME,
            summaries_path=final_dir / CURVE_ARTIFACT_SUMMARIES_FILENAME,
        )

    def _build_artifact_metadata(
        self,
        *,
        artifact_id: str,
        creation_timestamp: str,
        governance: OfficialCurveGovernance,
        reference_contexts: Mapping[str, CurveReferenceContext],
        draws: pd.DataFrame,
    ) -> CurveArtifactMetadata:
        """Build the immutable creation-time evidence snapshot.

        Built entirely from the *validated* governance objects and the
        actually-generated draws — a caller can never pass a pre-computed
        metadata snapshot or fingerprint that could disagree with the
        validated governance (REQ-CURVE-001 Work package B).
        """
        activity_rows = list(governance.activity_definitions)
        support_columns = [
            "market",
            "channel",
            "observed_support_status",
            "is_extrapolated",
        ]
        cost_currency_columns = [
            "market",
            "channel",
            "curve_type",
            "cost_mapping_id",
            "local_currency",
            "reporting_currency",
            "fx_rate",
            "fx_as_of_date",
            "fx_source",
        ]
        pathway_columns = [
            "channel",
            "component_type",
            "pathway_role",
            "include_in_headline",
            "include_in_planning",
            "include_in_attribution",
        ]
        pathway_snapshot: Dict[str, object] = {
            "rows": _json_safe_records(draws, pathway_columns),
            # Curve generator / component-allocation version actually used
            # (REQ-CURVE-001: "curve generator version"; approved decision 3:
            # incremental-eta share is the current, versioned, tested
            # component-allocation convention — not a unique causal
            # decomposition).
            "component_response_allocation_method": "incremental_eta_share",
        }
        metadata_without_fingerprints = CurveArtifactMetadata(
            artifact_id=artifact_id,
            creation_timestamp=creation_timestamp,
            generator_version=CURVE_ARTIFACT_GENERATOR_VERSION,
            model_identity_snapshot=governance.model_identity.to_dict(),
            approval_snapshot=governance.model_approval.to_dict(),
            threshold_policy_snapshot=governance.threshold_policy.to_dict(),
            readiness_snapshot=governance.approval_readiness.to_dict(),
            diagnostics_snapshot=governance.diagnostics_artefact.to_dict(),
            outcome_definition_snapshot=governance.outcome_definition.to_dict(),
            outcome_approval_snapshot=governance.outcome_approval.to_dict(),
            activity_governance_snapshot={
                "activities": [a.to_dict() for a in activity_rows],
                "fingerprint": activity_definitions_fingerprint(activity_rows),
            },
            pathway_governance_snapshot=pathway_snapshot,
            reference_context_snapshot={
                market: context.to_dict()
                for market, context in reference_contexts.items()
            },
            support_snapshot={"rows": _json_safe_records(draws, support_columns)},
            cost_currency_snapshot={
                "rows": _json_safe_records(draws, cost_currency_columns)
            },
        )
        fingerprints = dict(
            compute_curve_artifact_fingerprints(metadata_without_fingerprints)
        )
        return replace(metadata_without_fingerprints, fingerprints=fingerprints)
