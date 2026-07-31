"""
Governed application-service layer producing the authoritative "official
response curve" artifact (REQ-CURVE-001, PR 93B).

``core.canonical_curves.generate_canonical_curve_draws`` remains the single
calculation source of truth and is unchanged by this module — its own
``governance_mode="official"`` gate still only checks activity approval, and
only when ``activity_definitions`` is supplied, because omitting that
argument is exactly the defect documented in
``docs/curve_authority_gap_analysis.md`` and confirmed by PR #87. This
module does not patch that function; instead it adds the one path in this
repository that is structurally incapable of reproducing the defect:
``CurveGovernanceEvidence``'s fields are all required (no ``Optional``, no
defaults), so it is a ``TypeError`` — not a silently-skipped ``if`` branch —
to build an official curve without every piece of governance evidence.

Every governance check below composes an existing hard-gate primitive
(``require_matching_approval``, ``readiness_matches_current_evidence``,
``require_outcome_approval``, ``activity_by_model_input``) rather than
re-deriving validation logic. ``CurveBankEntry``/``curve_bank.py`` and the
current Streamlit UI are untouched by this module; migrating them is later,
separately-approved work (PR 93C/93D/93E).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Sequence, Tuple

import pandas as pd

from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_by_model_input,
    activity_definitions_fingerprint,
)
from ancestry_mmm.core.approval import ModelApproval, require_matching_approval
from ancestry_mmm.core.canonical_curves import (
    generate_canonical_curve_draws,
    summarize_curve_draws,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcome_approval import OutcomeApproval, require_outcome_approval
from ancestry_mmm.core.outcomes import OutcomeDefinition
from ancestry_mmm.core.validation_policy import (
    ApprovalReadiness,
    ThresholdPolicy,
    readiness_matches_current_evidence,
)

from .diagnostics_service import DiagnosticsArtefact

OFFICIAL_CURVE_ARTIFACT_SCHEMA_VERSION = 1
CURVE_GENERATOR_VERSION = "core.canonical_curves.generate_canonical_curve_draws (G2A.2)"

# Manifest keys this schema version writes explicitly; anything else found
# on import is preserved verbatim in ``extra_manifest_fields`` rather than
# discarded — REQ-CURVE-001: "unknown future fields ... must not be
# silently discarded."
_KNOWN_MANIFEST_FIELDS = {
    "schema_version",
    "is_official",
    "model_run_id",
    "outcome_id",
    "curve_generator_version",
    "governance_chain_fingerprint",
    "planning_eligible",
    "created_at",
    "reference_context_ids",
}


class CurveGovernanceBlockedError(Exception):
    """Raised when an official curve is requested but the supplied
    governance evidence is stale, mismatched, or incomplete for one or more
    in-scope (market, channel) pairs.

    Never reached because an argument was *omitted* — ``CurveGovernanceEvidence``
    has no optional fields, so that is a ``TypeError`` at construction, not a
    path into this function. This is raised only when evidence was supplied
    but its *content* fails validation.
    """


class MalformedCurveArtifactError(Exception):
    """Raised when a persisted official curve artifact cannot be loaded
    because its manifest or draw/summary tables are missing, corrupt, or
    internally inconsistent.

    REQ-CURVE-001: a malformed artifact must produce an audit result, never
    a silent skip (contrast with ``core.curve_bank.load_all_entries()``'s
    ``except (...): continue``).
    """


def _stable_fingerprint(payload: Mapping[str, Any]) -> str:
    """Deterministic SHA-256 over a JSON-safe mapping.

    Same canonical-JSON idiom already used by
    ``core.activities.activity_definitions_fingerprint`` and
    ``core.media_costs.monetary_governance_fingerprint`` — no shared helper
    exists in ``core.fingerprint`` to import, so this replicates the
    established repository convention rather than inventing a new one.
    """
    encoded = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CurveGovernanceEvidence:
    """The complete governance chain a new official curve must carry
    (REQ-CURVE-001). Every field is required — there is no way to construct
    this object while omitting one."""

    model_identity: ModelIdentity
    model_approval: ModelApproval
    threshold_policy: ThresholdPolicy
    approval_readiness: ApprovalReadiness
    diagnostics_artefact: DiagnosticsArtefact
    outcome: OutcomeDefinition
    outcome_approval: OutcomeApproval
    activity_definitions: Tuple[ActivityDefinition, ...]


@dataclass(frozen=True)
class OfficialCurveArtifact:
    """The persisted, governed "official response curve" artifact.

    Structurally distinct from ``ExploratoryCurveResult`` (a different
    type, not the same DataFrame schema with a string flag a caller could
    ignore) and from ``core.curve_bank.CurveBankEntry`` (a fitted-parameter
    point-estimate snapshot, not an evaluated draw-level curve).
    """

    schema_version: int
    model_run_id: str
    outcome_id: str
    curve_generator_version: str
    governance_chain_fingerprint: str
    draws: pd.DataFrame
    summaries: pd.DataFrame
    planning_eligible: Dict[Tuple[str, str], bool]
    created_at: str
    reference_context_ids: Tuple[str, ...]
    extra_manifest_fields: Dict[str, Any] = field(default_factory=dict)
    is_official: Literal[True] = True

    def manifest(self) -> Dict[str, Any]:
        """JSON-safe manifest metadata persisted alongside the Parquet
        draw/summary tables. Unknown fields captured on a prior import are
        round-tripped back out unchanged."""
        payload: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "is_official": self.is_official,
            "model_run_id": self.model_run_id,
            "outcome_id": self.outcome_id,
            "curve_generator_version": self.curve_generator_version,
            "governance_chain_fingerprint": self.governance_chain_fingerprint,
            "planning_eligible": [
                {"market": market, "channel": channel, "eligible": eligible}
                for (market, channel), eligible in sorted(
                    self.planning_eligible.items()
                )
            ],
            "created_at": self.created_at,
            "reference_context_ids": list(self.reference_context_ids),
        }
        payload.update(self.extra_manifest_fields)
        return payload


@dataclass(frozen=True)
class ExploratoryCurveResult:
    """A non-official curve result. No governance evidence is required or
    persisted. Never eligible for official use without regeneration through
    ``CurveService.generate_official_curve``."""

    model_run_id: str
    draws: pd.DataFrame
    is_official: Literal[False] = False


@dataclass(frozen=True)
class CurveArtifactAuditEntry:
    """One malformed-file finding from ``load_all_curve_artifacts`` — the
    audit result REQ-CURVE-001 requires in place of a silent skip."""

    path: Path
    error: str


def _planning_eligible_by_market_channel(
    draws: pd.DataFrame,
) -> Dict[Tuple[str, str], bool]:
    """Derive per-(market, channel) planning eligibility from the draws'
    existing, never-fabricated ``planning_support_eligible`` column
    (``core.canonical_curves``: ``observed_support_status == SUPPORT_AVAILABLE``).
    A (market, channel) is eligible only if every row for it is eligible."""
    if "planning_support_eligible" not in draws.columns:
        return {}
    grouped = draws.groupby(["market", "channel"])["planning_support_eligible"]
    return {
        (str(market), str(channel)): bool(values.all())
        for (market, channel), values in grouped
    }


class CurveService:
    """Governance-enforcing producer of official response-curve artifacts.

    The only path in this repository that may label a curve "official".
    ``core.canonical_curves.generate_canonical_curve_draws`` remains
    directly callable, ungated, for exploratory/test use — that is by
    design (REQ-CURVE-001: "exploratory generation must be structurally and
    visibly non-official", not forbidden outright).
    """

    def generate_official_curve(
        self, *, evidence: CurveGovernanceEvidence, **draw_kwargs: Any
    ) -> OfficialCurveArtifact:
        if "governance_mode" in draw_kwargs or "activity_definitions" in draw_kwargs:
            raise TypeError(
                "governance_mode/activity_definitions are controlled by "
                "CurveService.generate_official_curve and must not be "
                "passed directly."
            )
        model_run_id = draw_kwargs.get("model_run_id")
        if not model_run_id:
            raise ValueError("model_run_id is required")
        meta = draw_kwargs.get("meta")
        if meta is None:
            raise ValueError("meta is required")
        market_scope: Sequence[str] = list(meta.markets)
        channel_scope: Sequence[str] = list(meta.channels)

        self._require_valid_governance_chain(
            evidence,
            model_run_id=model_run_id,
            market_scope=market_scope,
            channel_scope=channel_scope,
        )

        draws = generate_canonical_curve_draws(
            governance_mode="official",
            activity_definitions=list(evidence.activity_definitions),
            **draw_kwargs,
        )
        summaries = summarize_curve_draws(draws)
        planning_eligible = _planning_eligible_by_market_channel(draws)
        reference_context_ids: Tuple[str, ...] = (
            tuple(sorted(str(v) for v in draws["reference_context_id"].unique()))
            if "reference_context_id" in draws.columns
            else ()
        )
        governance_chain_fingerprint = _stable_fingerprint(
            {
                "model_identity": evidence.model_identity.fingerprint(),
                "model_approval": {
                    "model_run_id": evidence.model_approval.model_run_id,
                    "approved_at": evidence.model_approval.approved_at,
                    "validation_policy_id": evidence.model_approval.validation_policy_id,
                },
                "threshold_policy": evidence.threshold_policy.fingerprint(),
                "approval_readiness": evidence.approval_readiness.fingerprint(),
                "diagnostics_artefact": evidence.diagnostics_artefact.fingerprint(),
                "outcome_approval_id": evidence.outcome_approval.approval_id,
                "activity_definitions": activity_definitions_fingerprint(
                    list(evidence.activity_definitions)
                ),
            }
        )
        return OfficialCurveArtifact(
            schema_version=OFFICIAL_CURVE_ARTIFACT_SCHEMA_VERSION,
            model_run_id=model_run_id,
            outcome_id=evidence.outcome.outcome_id,
            curve_generator_version=CURVE_GENERATOR_VERSION,
            governance_chain_fingerprint=governance_chain_fingerprint,
            draws=draws,
            summaries=summaries,
            planning_eligible=planning_eligible,
            created_at=datetime.now(timezone.utc).isoformat(),
            reference_context_ids=reference_context_ids,
        )

    def generate_exploratory_curve(self, **draw_kwargs: Any) -> ExploratoryCurveResult:
        """No governance evidence required or accepted — matches the
        existing ``generate_canonical_curve_draws(governance_mode="exploratory")``
        semantics, wrapped in a type a caller cannot mistake for
        ``OfficialCurveArtifact``."""
        draw_kwargs.pop("governance_mode", None)
        draw_kwargs.pop("activity_definitions", None)
        model_run_id = draw_kwargs.get("model_run_id")
        if not model_run_id:
            raise ValueError("model_run_id is required")
        draws = generate_canonical_curve_draws(
            governance_mode="exploratory", **draw_kwargs
        )
        return ExploratoryCurveResult(model_run_id=model_run_id, draws=draws)

    @staticmethod
    def _require_valid_governance_chain(
        evidence: CurveGovernanceEvidence,
        *,
        model_run_id: str,
        market_scope: Sequence[str],
        channel_scope: Sequence[str],
    ) -> None:
        # 1. ModelApproval must be bound to, and match, this exact model
        #    run, and must actually be validation-policy-backed - an
        #    evidence chain that supplies ThresholdPolicy/ApprovalReadiness
        #    only to have them ignored by an unbound ModelApproval would
        #    not be a real governance chain (require_matching_approval only
        #    uses them when approval.validation_policy_id is set).
        if not evidence.model_approval.validation_policy_id:
            raise CurveGovernanceBlockedError(
                "ModelApproval is not bound to a validation policy - an "
                "official curve requires the ThresholdPolicy/ApprovalReadiness "
                "evidence to be load-bearing, not merely supplied and ignored."
            )
        require_matching_approval(
            evidence.model_approval,
            model_run_id=evidence.model_identity.model_run_id,
            data_fingerprint=evidence.model_identity.data_fingerprint,
            model_spec_fingerprint=evidence.model_identity.model_spec_fingerprint,
            posterior_fingerprint=evidence.model_identity.posterior_fingerprint,
            approval_readiness=evidence.approval_readiness,
            current_policy=evidence.threshold_policy,
        )
        if model_run_id != evidence.model_identity.model_run_id:
            raise CurveGovernanceBlockedError(
                "The curve's model_run_id does not match the governance "
                "evidence's ModelIdentity.model_run_id."
            )

        # 2. Readiness must currently pass and must still reflect the
        #    current policy/model/diagnostics evidence (not drifted/stale).
        if not evidence.approval_readiness.overall_ready:
            raise CurveGovernanceBlockedError(
                "ApprovalReadiness.overall_ready is False - the validation "
                "policy gates have not been satisfied."
            )
        if evidence.threshold_policy.is_expired():
            raise CurveGovernanceBlockedError("ThresholdPolicy has expired.")
        if not readiness_matches_current_evidence(
            evidence.approval_readiness,
            policy_fingerprint=evidence.threshold_policy.fingerprint(),
            model_identity_fingerprint=evidence.model_identity.fingerprint(),
            diagnostic_artefact_fingerprint=evidence.diagnostics_artefact.fingerprint(),
        ):
            raise CurveGovernanceBlockedError(
                "ApprovalReadiness no longer reflects the current policy, "
                "model identity, or diagnostics artefact - re-evaluate "
                "readiness before generating an official curve."
            )

        # 3. Diagnostics artefact identity and completeness.
        if (
            evidence.diagnostics_artefact.model_identity_fingerprint
            != evidence.model_identity.fingerprint()
        ):
            raise CurveGovernanceBlockedError(
                "DiagnosticsArtefact.model_identity_fingerprint does not "
                "match the current ModelIdentity."
            )
        if (
            evidence.diagnostics_artefact.legacy_incomplete
            or evidence.diagnostics_artefact.schema_version < 2
        ):
            raise CurveGovernanceBlockedError(
                "DiagnosticsArtefact is legacy/incomplete and cannot "
                "support a new official curve."
            )

        # 4. Outcome approval for curve_publication, per market in scope.
        #    require_outcome_approval already checks status, expiry, use,
        #    definition-fingerprint staleness, and scope - reused as-is.
        for market in market_scope:
            require_outcome_approval(
                evidence.outcome,
                evidence.outcome_approval,
                "curve_publication",
                market=market,
            )

        # 5. Activity governance: every (market, channel) in scope must
        #    resolve to an approved ActivityDefinition. Unconditional -
        #    unlike generate_canonical_curve_draws's own check, this cannot
        #    be skipped by omitting activity_definitions, because
        #    CurveGovernanceEvidence.activity_definitions is required.
        unapproved: List[Tuple[str, str]] = []
        activity_rows = list(evidence.activity_definitions)
        for market in market_scope:
            by_input = activity_by_model_input(activity_rows, market)
            for channel in channel_scope:
                definition = by_input.get(channel)
                if definition is None or definition.approval_status != "approved":
                    unapproved.append((market, channel))
        if unapproved:
            raise CurveGovernanceBlockedError(
                "Official curve blocked - no approved activity governance "
                f"for {sorted(unapproved)}."
            )


def export_curve_artifact(
    artifact: OfficialCurveArtifact, directory: Path
) -> Tuple[Path, Path, Path]:
    """Write an official curve artifact's draws, summaries, and manifest.

    Each artifact lives in its own directory (three files); use
    ``load_all_curve_artifacts`` to bulk-load a parent directory of them.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    draws_path = directory / "official_curve_draws.parquet"
    summaries_path = directory / "official_curve_summaries.parquet"
    manifest_path = directory / "official_curve_manifest.json"
    artifact.draws.to_parquet(draws_path)
    artifact.summaries.to_parquet(summaries_path)
    manifest_path.write_text(json.dumps(artifact.manifest(), indent=2, sort_keys=True))
    return draws_path, summaries_path, manifest_path


def import_curve_artifact(directory: Path) -> OfficialCurveArtifact:
    """Read back an official curve artifact previously written by
    ``export_curve_artifact``.

    Fails closed: a missing file, corrupt JSON/Parquet, or a manifest
    missing a required field raises ``MalformedCurveArtifactError`` rather
    than returning a partial object or silently skipping. A manifest
    declaring a ``schema_version`` newer than this code supports raises
    ``ValueError`` rather than guessing at its shape (mirrors
    ``core.planning.value._validate_planning_semantics_schema_version``).
    Unknown manifest keys are preserved, not discarded.
    """
    directory = Path(directory)
    manifest_path = directory / "official_curve_manifest.json"
    draws_path = directory / "official_curve_draws.parquet"
    summaries_path = directory / "official_curve_summaries.parquet"
    if (
        not manifest_path.exists()
        or not draws_path.exists()
        or not summaries_path.exists()
    ):
        raise MalformedCurveArtifactError(
            f"Curve artifact directory {directory} is missing one or more "
            "required files (manifest/draws/summaries)."
        )
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        raise MalformedCurveArtifactError(
            f"Malformed manifest at {manifest_path}: {exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise MalformedCurveArtifactError(
            f"Manifest at {manifest_path} is not a JSON object."
        )

    schema_version = manifest.get("schema_version")
    if type(schema_version) is not int:
        raise MalformedCurveArtifactError(
            f"Manifest at {manifest_path} has a missing or non-integer schema_version."
        )
    if schema_version > OFFICIAL_CURVE_ARTIFACT_SCHEMA_VERSION:
        raise ValueError(
            f"Curve artifact manifest declares schema_version={schema_version}, "
            f"which is newer than the {OFFICIAL_CURVE_ARTIFACT_SCHEMA_VERSION} "
            "this code supports. Refusing to load an unsupported future "
            "payload rather than guessing at its shape."
        )

    try:
        draws = pd.read_parquet(draws_path)
        summaries = pd.read_parquet(summaries_path)
    except Exception as exc:
        raise MalformedCurveArtifactError(
            f"Malformed draw/summary table under {directory}: {exc}"
        ) from exc

    try:
        planning_eligible = {
            (str(record["market"]), str(record["channel"])): bool(record["eligible"])
            for record in manifest["planning_eligible"]
        }
        extra_manifest_fields = {
            k: v for k, v in manifest.items() if k not in _KNOWN_MANIFEST_FIELDS
        }
        return OfficialCurveArtifact(
            schema_version=schema_version,
            model_run_id=manifest["model_run_id"],
            outcome_id=manifest["outcome_id"],
            curve_generator_version=manifest["curve_generator_version"],
            governance_chain_fingerprint=manifest["governance_chain_fingerprint"],
            draws=draws,
            summaries=summaries,
            planning_eligible=planning_eligible,
            created_at=manifest["created_at"],
            reference_context_ids=tuple(manifest.get("reference_context_ids", ())),
            extra_manifest_fields=extra_manifest_fields,
        )
    except (KeyError, TypeError) as exc:
        raise MalformedCurveArtifactError(
            f"Manifest at {manifest_path} is missing a required field: {exc}"
        ) from exc


def load_all_curve_artifacts(
    directory: Path,
) -> Tuple[List[OfficialCurveArtifact], List[CurveArtifactAuditEntry]]:
    """Bulk-load every curve artifact under ``directory`` (one
    subdirectory per artifact). Every file that fails to load produces a
    ``CurveArtifactAuditEntry`` instead of being silently skipped —
    contrast with ``core.curve_bank.load_all_entries()``."""
    directory = Path(directory)
    artifacts: List[OfficialCurveArtifact] = []
    audit: List[CurveArtifactAuditEntry] = []
    if not directory.exists():
        return artifacts, audit
    for manifest_path in sorted(directory.glob("*/official_curve_manifest.json")):
        artifact_dir = manifest_path.parent
        try:
            artifacts.append(import_curve_artifact(artifact_dir))
        except (MalformedCurveArtifactError, ValueError, OSError) as exc:
            audit.append(CurveArtifactAuditEntry(path=artifact_dir, error=str(exc)))
    return artifacts, audit
