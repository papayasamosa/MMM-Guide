"""Official curve artifact schema, fingerprints, and round-trip IO (REQ-CURVE-001).

PR 95A scope: the versioned official-artifact schema, its JSON-safe metadata
contract, deterministic fingerprints that bind both key names and values, the
portable Parquet draw/summary table contract, a schema-level migration hook,
and a single-artifact write/read round-trip that fails closed on any missing,
malformed, unknown-version, or fingerprint-mismatched input.

No behaviour change to any existing generator: ``core.canonical_curves`` is
untouched. Generation wiring lands in PR 95B, current-use revalidation in
PR 95C, and store-level import/migration/malformed-file audit in PR 95D.

Artifact status follows REQ-CURVE-001 approved decision 4 (Work package G):
artifact lifecycle status is a separate vocabulary from
``core.outcome_approval.OUTCOME_APPROVAL_STATUSES`` — an outcome-approval
status is never reused as an artifact status. The schema carries the four
concepts (format/migration status, historical evidence integrity, current
authorization status, requested-use eligibility) as governed fields; the
vocabulary is realised in persistence by PR 95D.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Mapping, Tuple

import pandas as pd

from ancestry_mmm.core.canonical_curves import IDENTITY_COLUMNS
from ancestry_mmm.core.fingerprint import _canonical_json, fingerprint_dataframe

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

CURVE_ARTIFACT_SCHEMA_VERSION = 1
CURVE_ARTIFACT_GENERATOR_VERSION = "G2A.4-1"

CURVE_ARTIFACT_METADATA_FILENAME = "curve_artifact_metadata.json"
CURVE_ARTIFACT_DRAWS_FILENAME = "curve_artifact_draws.parquet"
CURVE_ARTIFACT_SUMMARIES_FILENAME = "curve_artifact_summaries.parquet"

# ---------------------------------------------------------------------------
# Artifact lifecycle status vocabulary (approved decision 4; realised in PR 95D)
# ---------------------------------------------------------------------------

CURVE_ARTIFACT_FORMAT_STATUSES = ("current", "legacy", "migrated", "unknown")
CURVE_HISTORICAL_INTEGRITY_STATUSES = ("intact", "incomplete", "tampered", "unknown")
# Current-authorization vocabulary is deliberately disjoint from
# OUTCOME_APPROVAL_STATUSES (approved decision 4, Work package G): a stale or
# expired *outcome approval* is detected by use-time revalidation and maps to
# "revoked" / "ineligible" / "superseded" here — the outcome-approval status
# value is never reused as an artifact status.
CURVE_CURRENT_AUTHORIZATION_STATUSES = (
    "authorized",
    "revoked",
    "ineligible",
    "superseded",
    "unknown",
)
CURVE_USE_ELIGIBILITY_STATUSES = (
    "eligible",
    "ineligible",
    "requires_revalidation",
    "unknown",
)

# ---------------------------------------------------------------------------
# Historical evidence chain (REQ-CURVE-001 "Historical artifact integrity")
# ---------------------------------------------------------------------------

CURVE_ARTIFACT_SNAPSHOT_FIELDS = (
    "model_identity_snapshot",
    "approval_snapshot",
    "threshold_policy_snapshot",
    "readiness_snapshot",
    "diagnostics_snapshot",
    "outcome_definition_snapshot",
    "outcome_approval_snapshot",
    "activity_governance_snapshot",
    "pathway_governance_snapshot",
    "reference_context_snapshot",
    "support_snapshot",
    "cost_currency_snapshot",
)

# Minimal identity columns a draw or summary table must carry. The full
# canonical schema is validated when generation is wired (PR 95B).
CURVE_ARTIFACT_DRAW_REQUIRED_COLUMNS = tuple(IDENTITY_COLUMNS)
CURVE_ARTIFACT_SUMMARY_REQUIRED_COLUMNS = tuple(IDENTITY_COLUMNS)


class CurveArtifactError(Exception):
    """Fail-closed error for official curve artifact validation and IO.

    Following the repository's existing pattern
    (``MalformedArtefactEvidenceError``), a missing, malformed, tampered, or
    unknown-version artifact raises this error; it is never silently skipped.
    """


def _is_json_safe(payload: object) -> bool:
    try:
        json.dumps(payload)
    except (TypeError, ValueError):
        return False
    return True


def _parse_iso_timestamp(value: str) -> None:
    """Raise ValueError unless ``value`` is a parseable ISO-8601 timestamp."""
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(
            f"creation_timestamp must be an ISO-8601 timestamp, got {value!r}"
        ) from exc


@dataclass(frozen=True)
class CurveArtifactMetadata:
    """Immutable, JSON-safe metadata proving what was true at creation time.

    Carries the historical evidence chain (REQ-CURVE-001 "Historical artifact
    integrity"): model identity, approval, threshold-policy, readiness,
    diagnostics, outcome definition and approval, activity and pathway
    governance, reference context, support, cost/currency, generator version,
    and creation timestamp — each as a JSON-safe snapshot.

    ``fingerprints`` binds the chain (both key names and values). Unknown
    fields are preserved in ``extra`` rather than silently dropped, per
    REQ-CURVE-001's unknown-field policy.
    """

    artifact_id: str
    creation_timestamp: str
    schema_version: int = CURVE_ARTIFACT_SCHEMA_VERSION
    generator_version: str = CURVE_ARTIFACT_GENERATOR_VERSION
    model_identity_snapshot: Mapping[str, object] = field(default_factory=dict)
    approval_snapshot: Mapping[str, object] = field(default_factory=dict)
    threshold_policy_snapshot: Mapping[str, object] = field(default_factory=dict)
    readiness_snapshot: Mapping[str, object] = field(default_factory=dict)
    diagnostics_snapshot: Mapping[str, object] = field(default_factory=dict)
    outcome_definition_snapshot: Mapping[str, object] = field(default_factory=dict)
    outcome_approval_snapshot: Mapping[str, object] = field(default_factory=dict)
    activity_governance_snapshot: Mapping[str, object] = field(default_factory=dict)
    pathway_governance_snapshot: Mapping[str, object] = field(default_factory=dict)
    reference_context_snapshot: Mapping[str, object] = field(default_factory=dict)
    support_snapshot: Mapping[str, object] = field(default_factory=dict)
    cost_currency_snapshot: Mapping[str, object] = field(default_factory=dict)
    fingerprints: Mapping[str, str] = field(default_factory=dict)
    format_status: str = "current"
    historical_integrity: str = "intact"
    current_authorization_status: str = "unknown"
    requested_use_eligibility: str = "unknown"
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id or not str(self.artifact_id).strip():
            raise ValueError("CurveArtifactMetadata.artifact_id must be non-blank")
        _parse_iso_timestamp(self.creation_timestamp)
        if self.schema_version != CURVE_ARTIFACT_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported curve artifact schema_version "
                f"{self.schema_version!r}; supported: {CURVE_ARTIFACT_SCHEMA_VERSION}"
            )
        if not self.generator_version or not str(self.generator_version).strip():
            raise ValueError(
                "CurveArtifactMetadata.generator_version must be non-blank"
            )
        for name in CURVE_ARTIFACT_SNAPSHOT_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise ValueError(f"{name} must be a mapping")
            if not _is_json_safe(dict(value)):
                raise ValueError(f"{name} must be JSON-safe")
        if not isinstance(self.fingerprints, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in self.fingerprints.items()
        ):
            raise ValueError("fingerprints must map str -> str")
        if self.format_status not in CURVE_ARTIFACT_FORMAT_STATUSES:
            raise ValueError(
                f"Invalid format_status {self.format_status!r}; must be one of "
                f"{CURVE_ARTIFACT_FORMAT_STATUSES}"
            )
        if self.historical_integrity not in CURVE_HISTORICAL_INTEGRITY_STATUSES:
            raise ValueError(
                f"Invalid historical_integrity {self.historical_integrity!r}; must be "
                f"one of {CURVE_HISTORICAL_INTEGRITY_STATUSES}"
            )
        if (
            self.current_authorization_status
            not in CURVE_CURRENT_AUTHORIZATION_STATUSES
        ):
            raise ValueError(
                f"Invalid current_authorization_status {self.current_authorization_status!r}; "
                f"must be one of {CURVE_CURRENT_AUTHORIZATION_STATUSES}"
            )
        if self.requested_use_eligibility not in CURVE_USE_ELIGIBILITY_STATUSES:
            raise ValueError(
                f"Invalid requested_use_eligibility {self.requested_use_eligibility!r}; "
                f"must be one of {CURVE_USE_ELIGIBILITY_STATUSES}"
            )
        if not isinstance(self.extra, Mapping) or not _is_json_safe(dict(self.extra)):
            raise ValueError("extra metadata must be a JSON-safe mapping")

    def to_dict(self) -> Dict[str, object]:
        """Stable JSON-safe serialisation. Unknown keys are re-emitted."""
        payload: Dict[str, object] = {
            "artifact_id": self.artifact_id,
            "creation_timestamp": self.creation_timestamp,
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
        }
        for name in CURVE_ARTIFACT_SNAPSHOT_FIELDS:
            payload[name] = dict(getattr(self, name))
        payload["fingerprints"] = dict(self.fingerprints)
        payload["format_status"] = self.format_status
        payload["historical_integrity"] = self.historical_integrity
        payload["current_authorization_status"] = self.current_authorization_status
        payload["requested_use_eligibility"] = self.requested_use_eligibility
        payload.update(dict(self.extra))
        return payload

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "CurveArtifactMetadata":
        """Load from a dict, preserving unknown keys in ``extra`` (not dropped)."""
        if not isinstance(values, Mapping):
            raise TypeError("CurveArtifactMetadata.from_dict requires a mapping")
        known = set(cls.__dataclass_fields__) - {"extra"}
        payload: Dict[str, object] = {}
        extra: Dict[str, object] = {}
        for key, value in values.items():
            if key in known:
                payload[key] = value
            else:
                extra[key] = value
        return cls(**payload, extra=extra)


# ---------------------------------------------------------------------------
# Fingerprints (bind both key names and values)
# ---------------------------------------------------------------------------


def fingerprint_curve_artifact_payload(payload: Mapping[str, object]) -> str:
    """Deterministic SHA-256 over canonical JSON of an arbitrary payload.

    ``_canonical_json`` sorts keys and uses compact separators, so the hash
    is stable across runs and platforms, and it binds both key names and
    values (a payload with the same values under different keys is a
    different payload).
    """
    return hashlib.sha256(_canonical_json(dict(payload)).encode("utf-8")).hexdigest()


def compute_curve_artifact_fingerprints(
    metadata: CurveArtifactMetadata,
) -> Mapping[str, str]:
    """Compute per-snapshot and chain fingerprints for the historical evidence.

    Deliberately excludes the ``fingerprints`` field itself (circular) and the
    ``extra`` unknown-key bag (unknown keys are preserved and surfaced as a
    schema-mismatch concern rather than bound into the chain fingerprint).
    """
    chain_payload: Dict[str, object] = {
        "artifact_id": metadata.artifact_id,
        "creation_timestamp": metadata.creation_timestamp,
        "schema_version": metadata.schema_version,
        "generator_version": metadata.generator_version,
        "format_status": metadata.format_status,
        "historical_integrity": metadata.historical_integrity,
        "current_authorization_status": metadata.current_authorization_status,
        "requested_use_eligibility": metadata.requested_use_eligibility,
    }
    for name in CURVE_ARTIFACT_SNAPSHOT_FIELDS:
        chain_payload[name] = dict(getattr(metadata, name))
    fingerprints: Dict[str, str] = {
        "chain_fingerprint": fingerprint_curve_artifact_payload(chain_payload)
    }
    for name in CURVE_ARTIFACT_SNAPSHOT_FIELDS:
        fingerprints[name] = fingerprint_curve_artifact_payload(
            dict(getattr(metadata, name))
        )
    return fingerprints


def verify_curve_artifact_fingerprints(metadata: CurveArtifactMetadata) -> None:
    """Raise CurveArtifactError unless every expected fingerprint matches.

    Fails closed: a missing fingerprint is a mismatch, never an implicit pass.
    """
    expected = compute_curve_artifact_fingerprints(metadata)
    for name, value in expected.items():
        stored = metadata.fingerprints.get(name)
        if stored != value:
            raise CurveArtifactError(
                f"Curve artifact fingerprint mismatch for '{name}': stored {stored!r} "
                f"!= computed {value!r}."
            )


# ---------------------------------------------------------------------------
# Table contract
# ---------------------------------------------------------------------------


def validate_draws_table(draws: pd.DataFrame) -> None:
    """Raise CurveArtifactError unless the draws table is non-empty and carries
    the required identity columns."""
    _validate_table(draws, CURVE_ARTIFACT_DRAW_REQUIRED_COLUMNS, "draws")


def validate_summaries_table(summaries: pd.DataFrame) -> None:
    """Raise CurveArtifactError unless the summaries table is non-empty and
    carries the required identity columns."""
    _validate_table(summaries, CURVE_ARTIFACT_SUMMARY_REQUIRED_COLUMNS, "summaries")


def _validate_table(df: pd.DataFrame, required: Tuple[str, ...], label: str) -> None:
    if not isinstance(df, pd.DataFrame):
        raise CurveArtifactError(f"curve artifact {label} must be a DataFrame")
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise CurveArtifactError(
            f"curve artifact {label} table is missing required column(s): {missing}"
        )
    if df.empty:
        raise CurveArtifactError(f"curve artifact {label} table is empty")


# ---------------------------------------------------------------------------
# Migration hook
# ---------------------------------------------------------------------------


def migrate_curve_artifact_metadata(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Schema-level migration hook (REQ-CURVE-001 persistence).

    Currently supports ``CURVE_ARTIFACT_SCHEMA_VERSION`` only (identity
    migration). Future schema versions register their migration here and must
    preserve unknown fields. Unknown or unsupported versions fail closed.
    """
    if not isinstance(payload, Mapping):
        raise CurveArtifactError("curve artifact metadata must be a mapping")
    version = payload.get("schema_version")
    if version == CURVE_ARTIFACT_SCHEMA_VERSION:
        return dict(payload)
    raise CurveArtifactError(
        f"Unsupported curve artifact schema_version {version!r}; supported: "
        f"{CURVE_ARTIFACT_SCHEMA_VERSION}"
    )


# ---------------------------------------------------------------------------
# Round-trip IO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurveArtifact:
    """A loaded official curve artifact: metadata plus draw/summary tables."""

    metadata: CurveArtifactMetadata
    draws: pd.DataFrame
    summaries: pd.DataFrame


def write_curve_artifact(
    directory: Path,
    *,
    metadata: CurveArtifactMetadata,
    draws: pd.DataFrame,
    summaries: pd.DataFrame,
) -> Tuple[Path, Path, Path]:
    """Write a single official curve artifact (metadata JSON + Parquet tables).

    The metadata envelope records schema version, the JSON-safe metadata, and
    deterministic fingerprints of the draw and summary tables. Raises
    ``CurveArtifactError`` if the tables do not satisfy the schema contract.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    validate_draws_table(draws)
    validate_summaries_table(summaries)

    metadata_path = directory / CURVE_ARTIFACT_METADATA_FILENAME
    draws_path = directory / CURVE_ARTIFACT_DRAWS_FILENAME
    summaries_path = directory / CURVE_ARTIFACT_SUMMARIES_FILENAME

    draws.to_parquet(draws_path, index=False)
    summaries.to_parquet(summaries_path, index=False)
    envelope = {
        "schema_version": metadata.schema_version,
        "metadata": metadata.to_dict(),
        "draws_fingerprint": fingerprint_dataframe(draws),
        "summaries_fingerprint": fingerprint_dataframe(summaries),
    }
    metadata_path.write_text(
        json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8"
    )
    return metadata_path, draws_path, summaries_path


def read_curve_artifact(directory: Path) -> CurveArtifact:
    """Load and verify one official curve artifact; fails closed on any defect.

    Verifies, in order: file presence, metadata JSON validity, schema version
    (via the migration hook), metadata validity, envelope/table consistency,
    table fingerprints (tamper detection), and the metadata chain fingerprints.
    Any failure raises ``CurveArtifactError`` — never a silent skip.
    """
    directory = Path(directory)
    metadata_path = directory / CURVE_ARTIFACT_METADATA_FILENAME
    draws_path = directory / CURVE_ARTIFACT_DRAWS_FILENAME
    summaries_path = directory / CURVE_ARTIFACT_SUMMARIES_FILENAME

    for path, label in (
        (metadata_path, "metadata"),
        (draws_path, "draws"),
        (summaries_path, "summaries"),
    ):
        if not path.exists():
            raise CurveArtifactError(f"Missing curve artifact {label} file: {path}")

    try:
        envelope = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise CurveArtifactError(
            f"Malformed curve artifact metadata JSON at {metadata_path}: {exc}"
        ) from exc
    if not isinstance(envelope, dict):
        raise CurveArtifactError(
            "curve artifact metadata envelope must be a JSON object"
        )

    metadata_payload = envelope.get("metadata")
    if not isinstance(metadata_payload, dict):
        raise CurveArtifactError(
            "curve artifact metadata envelope is missing 'metadata'"
        )
    migrated = migrate_curve_artifact_metadata(metadata_payload)
    try:
        metadata = CurveArtifactMetadata.from_dict(migrated)
    except (TypeError, ValueError) as exc:
        raise CurveArtifactError(f"Invalid curve artifact metadata: {exc}") from exc

    envelope_version = envelope.get("schema_version")
    if envelope_version != metadata.schema_version:
        raise CurveArtifactError(
            f"Curve artifact envelope schema_version {envelope_version!r} does not "
            f"match metadata schema_version {metadata.schema_version!r}"
        )

    try:
        draws = pd.read_parquet(draws_path)
        summaries = pd.read_parquet(summaries_path)
    except Exception as exc:  # fail closed on any table read error
        raise CurveArtifactError(
            f"Failed to read curve artifact tables: {exc}"
        ) from exc
    validate_draws_table(draws)
    validate_summaries_table(summaries)

    for label, df, stored in (
        ("draws", draws, envelope.get("draws_fingerprint")),
        ("summaries", summaries, envelope.get("summaries_fingerprint")),
    ):
        if not isinstance(stored, str) or not stored:
            raise CurveArtifactError(
                f"{label} fingerprint missing in metadata envelope"
            )
        if fingerprint_dataframe(df) != stored:
            raise CurveArtifactError(
                f"{label} table fingerprint mismatch (tampered or corrupted)"
            )

    verify_curve_artifact_fingerprints(metadata)
    return CurveArtifact(metadata=metadata, draws=draws, summaries=summaries)
