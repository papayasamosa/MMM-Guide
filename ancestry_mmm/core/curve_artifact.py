"""Official curve artifact schema, fingerprints, and round-trip IO (REQ-CURVE-001).

The versioned official-artifact schema: its JSON-safe metadata contract,
deterministic fingerprints that bind both key names and values (including
unknown/forward-compatible ``extra`` fields, PR 96A), the portable Parquet
draw/summary table contract, a schema-level migration hook, a single-artifact
write/read round-trip that fails closed on any missing, malformed,
unknown-version, or fingerprint-mismatched input, and store-level import,
migration, and malformed-file audit across many artifacts (PR 95D — already
implemented below, not future work).

No curve mathematics live here: ``core.canonical_curves`` is untouched.
Generation is wired through ``application.curve_service.CurveService``
(governance-chain enforcement in PR 95B, current-use revalidation in PR 95C,
the ``create_official_artifact`` creation-and-persistence transaction in
PR 96A). Display in the Results / Curve Bank page shipped in PR 95E; legacy
curve-bank parameter-snapshot labelling shipped in PR 95F.

Artifact status follows REQ-CURVE-001 approved decision 4 (Work package G):
artifact lifecycle status is a separate vocabulary from
``core.outcome_approval.OUTCOME_APPROVAL_STATUSES`` — an outcome-approval
status is never reused as an artifact status. The schema carries the four
concepts (format/migration status, historical evidence integrity, current
authorization status, requested-use eligibility) as governed fields; the
vocabulary is realised in persistence below (PR 95D).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Sequence, Tuple, cast

import pandas as pd

from ancestry_mmm.core.canonical_curves import IDENTITY_COLUMNS
from ancestry_mmm.core.fingerprint import _canonical_json, fingerprint_dataframe
from ancestry_mmm.core.outcomes import METRIC_REGISTRY

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

# Of the snapshot fields above, these must be non-empty: an artifact with no
# outcome-definition/outcome-approval snapshot at all has no versioned,
# approved outcome binding and must never be accepted as official, even
# though the module-level schema alone cannot enforce the fuller
# governance-chain requirements (threshold policy, readiness, diagnostics)
# that belong to CurveService's generation-time validation.
CURVE_ARTIFACT_REQUIRED_NON_EMPTY_SNAPSHOT_FIELDS = (
    "outcome_definition_snapshot",
    "outcome_approval_snapshot",
)

# Minimal identity columns the draws table must carry: the canonical
# per-component posterior draws (one row per posterior draw x spend point x
# market x channel x component), the full IDENTITY_COLUMNS grain.
# Also requires the draw-level calculation columns (posterior_draw identity
# and the incremental_response value) so a summary-shaped frame — identity
# columns only, no per-draw value or uncertainty — cannot pass as a draws
# table (REQ-CURVE-001 posterior-draws-before-summary contract).
CURVE_ARTIFACT_DRAW_VALUE_REQUIRED_COLUMNS = ("posterior_draw", "incremental_response")
CURVE_ARTIFACT_DRAW_REQUIRED_COLUMNS = tuple(IDENTITY_COLUMNS) + (
    CURVE_ARTIFACT_DRAW_VALUE_REQUIRED_COLUMNS
)

# PR 96A: the persisted summary table is the approved channel-safe
# "segment" governance view (`core.canonical_curves.canonical_governance_views`)
# summarized across posterior draws — direct and cross-product components are
# reconciled into channel-total economics before summarization (REQ-CURVE-001
# "Channel-total economics remain authoritative"), so `component_type` and
# `pathway_role` are intentionally not part of the summary grain (they remain
# required for the draws table, which keeps the component-level grain).
CURVE_ARTIFACT_SUMMARY_REQUIRED_COLUMNS = tuple(
    column
    for column in IDENTITY_COLUMNS
    if column not in ("component_type", "pathway_role")
)


class CurveArtifactError(Exception):
    """Fail-closed error for official curve artifact validation and IO.

    Following the repository's existing pattern
    (``MalformedArtefactEvidenceError``), a missing, malformed, tampered, or
    unknown-version artifact raises this error; it is never silently skipped.
    """


class CurveArtifactUnsupportedSchemaError(CurveArtifactError):
    """A curve artifact uses a schema version this loader cannot migrate.

    Distinct from a generic malformed file: an unsupported schema version is
    a forward-compatibility failure and is audited as such (never silently
    discarded).
    """


# Characters forbidden in a portable path component on every supported
# operating system - a superset of what any single OS actually forbids, so a
# name accepted here is guaranteed writable on Windows, macOS, and Linux
# alike (Corrective PR E3.2).
_FORBIDDEN_PATH_COMPONENT_CHARS = frozenset('<>:"/\\|?*')

# Windows reserved device names (case-insensitive, extension-insensitive) -
# a path component matching one of these is invalid regardless of platform,
# since artifact stores must remain portable across the repository's
# Windows-first tooling.
_RESERVED_WINDOWS_PATH_COMPONENT_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def validate_portable_path_component(
    component: str, *, label: str = "path component"
) -> None:
    """Reject a path component that is not safe to write on every supported
    operating system (Corrective PR E3.2).

    A single component - never a multi-segment relative path (path
    separators are themselves rejected here; a caller validating a relative
    path must call this once per segment). Rejects: blank/whitespace-only
    values, ``.``/``..``, ASCII control characters (0-31), the characters
    ``< > : " / \\ | ? *``, a trailing dot or trailing space (both illegal
    on Windows even though the component is otherwise well-formed), and a
    reserved Windows device stem (``CON``, ``COM1``, ... ) with or without
    an extension. Never relaxes a check already enforced elsewhere - this is
    the strict superset every portable name must satisfy.
    """
    if not component or not component.strip():
        raise CurveArtifactStoreError(f"{label} must not be blank: {component!r}")
    if component != component.strip():
        raise CurveArtifactStoreError(
            f"{label} must not have leading/trailing whitespace: {component!r}"
        )
    if component in (".", ".."):
        raise CurveArtifactStoreError(f"{label} must not be '.' or '..': {component!r}")
    if any(ord(ch) < 32 for ch in component):
        raise CurveArtifactStoreError(
            f"{label} must not contain control characters: {component!r}"
        )
    forbidden = sorted(set(component) & _FORBIDDEN_PATH_COMPONENT_CHARS)
    if forbidden:
        raise CurveArtifactStoreError(
            f"{label} must not contain {forbidden}: {component!r}"
        )
    if component.endswith("."):
        raise CurveArtifactStoreError(f"{label} must not end in a dot: {component!r}")
    stem = component.split(".", 1)[0].upper()
    if stem in _RESERVED_WINDOWS_PATH_COMPONENT_STEMS:
        raise CurveArtifactStoreError(
            f"{label} must not be a reserved device name: {component!r}"
        )


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
    REQ-CURVE-001's unknown-field policy, and are themselves bound into the
    fingerprint chain (``extra_fingerprint`` plus inclusion in
    ``chain_fingerprint``) so an unknown key or value cannot be added or
    changed without failing integrity verification (PR 96A).
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
        for name in CURVE_ARTIFACT_REQUIRED_NON_EMPTY_SNAPSHOT_FIELDS:
            if not getattr(self, name):
                raise ValueError(
                    f"{name} must be non-empty: every official curve artifact "
                    "must be bound to a versioned, approved outcome"
                )
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
        # `payload` is necessarily untyped (deserialised from an arbitrary
        # caller-supplied mapping) - `__post_init__` below is the actual
        # runtime validation boundary for the fields it checks (mapping
        # shape/JSON-safety, non-blank identifiers, exact schema version),
        # so this cast documents that trust rather than asserting a static
        # guarantee mypy cannot verify from `Dict[str, object]` alone. No
        # runtime behaviour change.
        return cls(**cast(Dict[str, Any], payload), extra=extra)


def governed_context_fields(metadata: CurveArtifactMetadata) -> Dict[str, object]:
    """Extract the governed-context fields an official curve display or
    export must label an artifact with, beyond bare artifact_id/outcome_id
    (Corrective PR D4/D5) - outcome definition version, approval status,
    segment/product, currency/FX evidence, extrapolation status, and
    component scope. Every value here already exists in the artifact's own
    immutable creation-time snapshots (``_build_artifact_metadata``); this
    only surfaces what a display/export row was previously omitting, never
    invents or recomputes anything.

    Production-integration follow-up (Results/exports disclosure labels):
    also surfaces the outcome's *metric identity* (``outcome_metric_key``/
    ``outcome_metric_label``, e.g. distinguishing a GSA outcome from a net
    bill-through one - ``outcome_definition_version`` above identifies
    which *version* of a definition was used, never which metric it is),
    plus whether this artifact's underlying model had experiment evidence
    or Search-capacity evidence linked to it at creation time
    (``experiment_calibration_status``/``linked_experiment_count``,
    ``search_capacity_status``/``search_capacity_official_use_eligible``).
    All four are read from ``metadata.diagnostics_snapshot`` - the same
    ``DiagnosticSection``-shaped dict ``pages/06_Diagnostics.py`` already
    reads for its "Identification & collinearity"/"Candidate A Search"
    tabs, snapshotted once at artifact-creation time
    (``application.curve_service``) - never recomputed here, and never
    fabricated when the underlying diagnostics artefact did not carry a
    computed section (most fits today have no experiment evidence or
    Search Candidate A spec linked - see ``application.diagnostics_
    service``'s own ``search_capacity`` section comment - so these two
    commonly read ``"not_applicable"``, which is the honest answer, not a
    gap in this function).
    """
    outcome = metadata.outcome_definition_snapshot or {}
    approval = metadata.outcome_approval_snapshot or {}
    diagnostics = metadata.diagnostics_snapshot or {}
    outcome_metric_key = outcome.get("metric_key")
    metric_definition = (
        METRIC_REGISTRY.get(str(outcome_metric_key)) if outcome_metric_key else None
    )
    experiment_calibration = cast(
        Mapping[str, object], diagnostics.get("experiment_calibration") or {}
    )
    experiment_payload = cast(
        Mapping[str, object], experiment_calibration.get("payload") or {}
    )
    experiment_report = cast(
        Mapping[str, object], experiment_payload.get("experiments") or {}
    )
    experiment_entries = experiment_report.get("entries")
    search_capacity = cast(
        Mapping[str, object], diagnostics.get("search_capacity") or {}
    )
    search_payload = cast(Mapping[str, object], search_capacity.get("payload") or {})
    search_use_gate = search_payload.get("use_gate")
    # Snapshot fields are declared Mapping[str, object] (arbitrary JSON-like
    # payload) - each `"rows"` entry is, by this artifact's own construction
    # contract (`_build_artifact_metadata`), always a sequence of row
    # mappings when present. The cast documents that contract for mypy;
    # it changes no runtime behaviour.
    cost_currency_rows = cast(
        Sequence[Mapping[str, object]],
        (metadata.cost_currency_snapshot or {}).get("rows") or [],
    )
    support_rows = cast(
        Sequence[Mapping[str, object]],
        (metadata.support_snapshot or {}).get("rows") or [],
    )
    pathway_rows = cast(
        Sequence[Mapping[str, object]],
        (metadata.pathway_governance_snapshot or {}).get("rows") or [],
    )

    def _joined(values: Iterable[Any]) -> "str | None":
        unique = sorted({v for v in values if v})
        return ", ".join(unique) if unique else None

    return {
        "outcome_definition_version": outcome.get("definition_version"),
        "segment": outcome.get("segment"),
        "product": outcome.get("product"),
        "outcome_approval_status": approval.get("status"),
        "local_currency": _joined(
            row.get("local_currency") for row in cost_currency_rows
        ),
        "reporting_currency": _joined(
            row.get("reporting_currency") for row in cost_currency_rows
        ),
        "fx_source": _joined(row.get("fx_source") for row in cost_currency_rows),
        "fx_as_of_date": _joined(
            row.get("fx_as_of_date") for row in cost_currency_rows
        ),
        "component_scope": _joined(row.get("component_type") for row in pathway_rows),
        "extrapolation_status": resolve_extrapolation_status(support_rows),
        "outcome_metric_key": outcome_metric_key,
        "outcome_metric_label": (
            metric_definition.display_name if metric_definition is not None else None
        ),
        "experiment_calibration_status": experiment_calibration.get("status"),
        "linked_experiment_count": (
            len(cast(Sequence[object], experiment_entries))
            if experiment_entries is not None
            else None
        ),
        "search_capacity_status": search_capacity.get("status"),
        "search_capacity_official_use_eligible": (
            cast(Mapping[str, object], search_use_gate).get("official_use_eligible")
            if search_use_gate is not None
            else None
        ),
    }


def resolve_extrapolation_status(
    support_rows: Sequence[Mapping[str, object]],
) -> str:
    """Tri-state support/extrapolation status (Corrective PR E2.5):
    ``"extrapolated"``, ``"within observed range"``, or ``"support
    unavailable or unknown"``.

    ``is_extrapolated`` is ``None`` on a row precisely when
    ``observed_support_status`` is not ``SUPPORT_AVAILABLE`` (see
    ``generate_canonical_curve_draws``) - the canonical representation for
    missing/unavailable support evidence, never evidence of anything.
    Every non-``True`` value (``False`` and ``None`` alike) previously
    collapsed to ``"within observed range"``, so an artifact with no
    support evidence at all - or a mix of rows, some with unknown support -
    wrongly asserted observed-range evidence that does not exist.
    ``"within observed range"`` is now reserved for the case where every
    relevant row explicitly reports ``is_extrapolated is False`` (real
    supported evidence); any row reporting ``True`` marks the whole
    artifact ``"extrapolated"`` (still the most actionable/conservative
    signal even alongside unknown rows); everything else - no rows at all,
    or any row with unknown support and none extrapolated - is
    ``"support unavailable or unknown"``, never silently asserted as
    within range.
    """
    if not support_rows:
        return "support unavailable or unknown"
    values = [row.get("is_extrapolated") for row in support_rows]
    if any(value is True for value in values):
        return "extrapolated"
    if all(value is False for value in values):
        return "within observed range"
    return "support unavailable or unknown"


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

    Deliberately excludes the ``fingerprints`` field itself (circular).

    PR 96A: unknown fields (``extra``) are now bound into the integrity
    chain rather than excluded. ``CurveArtifactMetadata.from_dict``
    preserves unknown/future-schema fields in ``extra`` for round-trip
    compatibility, but until this change they were excluded from every
    fingerprint — an unknown field could be added or changed after creation
    without changing the historical evidence-chain fingerprint, while the
    artifact still reported ``historical_integrity == "intact"``. ``extra``
    is now covered both by its own ``extra_fingerprint`` (so a targeted
    unknown-field tamper is identified precisely) and by inclusion in the
    ``chain_fingerprint`` payload (so ``verify_curve_artifact_fingerprints``
    fails closed on any unknown-key or unknown-value change). This is a
    tamper-detection policy, distinct from schema-version migration
    (``migrate_curve_artifact_metadata``): a field legitimately introduced by
    a newer, supported schema version is migrated, not treated as tampering.
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
        "extra": dict(metadata.extra),
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
    fingerprints["extra_fingerprint"] = fingerprint_curve_artifact_payload(
        dict(metadata.extra)
    )
    return fingerprints


def verify_curve_artifact_fingerprints(metadata: CurveArtifactMetadata) -> None:
    """Raise CurveArtifactError unless every expected (current-format)
    fingerprint matches.

    Fails closed: a missing fingerprint is a mismatch, never an implicit
    pass. This is the strict, current-only check: it is used at write time,
    where every newly written artifact must use the current fingerprint
    formula. Reading an existing artifact from disk should go through
    ``verify_curve_artifact_fingerprints_allow_legacy`` instead, which also
    accepts the pre-96A legacy formula for artifacts written before
    ``extra_fingerprint`` entered the chain.
    """
    expected = compute_curve_artifact_fingerprints(metadata)
    for name, value in expected.items():
        stored = metadata.fingerprints.get(name)
        if stored != value:
            raise CurveArtifactError(
                f"Curve artifact fingerprint mismatch for '{name}': stored {stored!r} "
                f"!= computed {value!r}."
            )


def compute_legacy_curve_artifact_fingerprints(
    metadata: CurveArtifactMetadata,
) -> Mapping[str, str]:
    """Compute fingerprints under the pre-PR-96A formula.

    Before PR 96A, ``extra`` was not bound into the fingerprint chain: the
    chain payload excluded the ``"extra"`` key entirely, and there was no
    ``extra_fingerprint`` entry. Every schema-v1 artifact written before that
    change has fingerprints computed this way. ``CURVE_ARTIFACT_SCHEMA_VERSION``
    was not bumped when PR 96A landed, so these legacy artifacts cannot be
    told apart from current ones by schema version alone — only by the shape
    of their stored ``fingerprints`` mapping (see
    ``verify_curve_artifact_fingerprints_allow_legacy``).
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


def verify_curve_artifact_fingerprints_allow_legacy(
    metadata: CurveArtifactMetadata,
) -> str:
    """Verify fingerprints against the current formula, falling back to the
    pre-96A legacy formula only for artifacts that are structurally legacy.

    Returns ``"current"`` or ``"legacy"``. Raises ``CurveArtifactError`` if
    neither formula matches. The legacy fallback is only attempted when the
    stored ``fingerprints`` mapping itself lacks an ``"extra_fingerprint"``
    key — that is a structural signal of a pre-96A artifact, not merely a
    wrong value. A current-format artifact whose ``extra_fingerprint`` key is
    present but wrong is a genuine tamper/corruption case and must never be
    silently reinterpreted as legacy.
    """
    try:
        verify_curve_artifact_fingerprints(metadata)
        return "current"
    except CurveArtifactError:
        if "extra_fingerprint" in metadata.fingerprints:
            raise
        legacy_expected = compute_legacy_curve_artifact_fingerprints(metadata)
        for name, value in legacy_expected.items():
            stored = metadata.fingerprints.get(name)
            if stored != value:
                raise CurveArtifactError(
                    f"Curve artifact fingerprint mismatch for '{name}' (checked "
                    f"both current and legacy pre-96A formulas): stored "
                    f"{stored!r} != legacy-expected {value!r}."
                ) from None
        return "legacy"


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
    raise CurveArtifactUnsupportedSchemaError(
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
    # Fail closed before anything touches disk: a write with unpopulated or
    # incorrect fingerprints would otherwise succeed here and only surface as
    # a fingerprint mismatch on the next read. Always current-only — a fresh
    # write must never use the legacy formula.
    verify_curve_artifact_fingerprints(metadata)

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

    detected_format = verify_curve_artifact_fingerprints_allow_legacy(metadata)
    if detected_format == "legacy" and metadata.format_status not in (
        "legacy",
        "migrated",
    ):
        # A pre-96A artifact whose fingerprints only satisfy the legacy
        # formula. Its own fingerprints (the original layout) are preserved
        # unchanged; only the in-memory format_status label is updated so
        # callers (including migrate_curve_artifact_store) can recognise and
        # migrate it to the current fingerprint layout.
        metadata = replace(metadata, format_status="legacy")
    return CurveArtifact(metadata=metadata, draws=draws, summaries=summaries)


# ---------------------------------------------------------------------------
# Store-level import, migration, and malformed-file audit (PR 95D)
# ---------------------------------------------------------------------------
#
# A *store* is a directory whose immediate subdirectories each contain one
# official curve artifact (the same layout `write_curve_artifact` produces),
# or a directory that is itself a single artifact. Loading a store never
# silently skips a file: every artifact directory appears in an audit entry,
# and the loader fails closed by default.


class CurveArtifactStoreError(CurveArtifactError):
    """Fail-closed error raised when a store contains malformed or
    unsupported artifacts (the audit is attached to the message)."""


@dataclass(frozen=True)
class CurveArtifactAuditEntry:
    """One artifact directory's load result.

    ``status`` is one of ``"loaded"``, ``"malformed"``, or
    ``"unsupported_schema"``; ``error`` carries the reason for anything
    other than ``"loaded"`` so nothing disappears silently.
    """

    artifact_dir: Path
    status: str
    error: str = ""


@dataclass(frozen=True)
class CurveArtifactStoreLoadResult:
    """Result of loading a whole store: every artifact plus its audit trail."""

    loaded: Tuple[CurveArtifact, ...] = ()
    audit: Tuple[CurveArtifactAuditEntry, ...] = ()

    @property
    def malformed(self) -> Tuple[CurveArtifactAuditEntry, ...]:
        return tuple(entry for entry in self.audit if entry.status != "loaded")


@dataclass(frozen=True)
class CurveArtifactMigrationEntry:
    """One artifact directory's migration result."""

    artifact_dir: Path
    migrated: bool
    schema_version: int
    error: str = ""


@dataclass(frozen=True)
class CurveArtifactMigrationResult:
    """Result of migrating a whole store (per-artifact audit)."""

    entries: Tuple[CurveArtifactMigrationEntry, ...] = ()

    @property
    def migrated_entries(self) -> Tuple[CurveArtifactMigrationEntry, ...]:
        return tuple(e for e in self.entries if e.migrated and not e.error)

    @property
    def failed(self) -> Tuple[CurveArtifactMigrationEntry, ...]:
        return tuple(e for e in self.entries if e.error)

    @property
    def migrated_count(self) -> int:
        return len(self.migrated_entries)


def _has_any_artifact_file(directory: Path) -> bool:
    """True if ``directory`` contains any canonical artifact file, even a
    partial set (e.g. metadata deleted, or an interrupted write leaving only
    the Parquet tables). Used so a partial artifact is audited as malformed
    rather than silently skipped (Corrective PR A3)."""
    return any(
        (directory / filename).exists()
        for filename in (
            CURVE_ARTIFACT_METADATA_FILENAME,
            CURVE_ARTIFACT_DRAWS_FILENAME,
            CURVE_ARTIFACT_SUMMARIES_FILENAME,
        )
    )


def _iter_artifact_dirs(directory: Path) -> Iterator[Path]:
    """Yield artifact directories: the store root when it is itself an
    artifact (or partial artifact), plus every immediate subdirectory
    containing any canonical artifact file — even a partial set — so a
    directory missing its metadata (deleted, or an interrupted write) is
    still audited as malformed rather than silently dropped (sorted for
    determinism)."""
    if _has_any_artifact_file(directory):
        yield directory
    for child in sorted(path for path in directory.iterdir() if path.is_dir()):
        if _has_any_artifact_file(child):
            yield child


def load_curve_artifact_store(
    directory: Path,
    *,
    raise_on_malformed: bool = True,
) -> CurveArtifactStoreLoadResult:
    """Load every official curve artifact under ``directory``.

    Every artifact directory is audited as ``"loaded"``, ``"malformed"``, or
    ``"unsupported_schema"`` — never silently skipped. When
    ``raise_on_malformed`` (default), any malformed or unsupported artifact
    raises ``CurveArtifactStoreError`` (fail closed); otherwise the result
    carries the audit for the caller to inspect.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return CurveArtifactStoreLoadResult()
    loaded: List[CurveArtifact] = []
    audit: List[CurveArtifactAuditEntry] = []
    for artifact_dir in _iter_artifact_dirs(directory):
        try:
            loaded.append(read_curve_artifact(artifact_dir))
            audit.append(
                CurveArtifactAuditEntry(artifact_dir=artifact_dir, status="loaded")
            )
        except CurveArtifactUnsupportedSchemaError as exc:
            audit.append(
                CurveArtifactAuditEntry(
                    artifact_dir=artifact_dir,
                    status="unsupported_schema",
                    error=str(exc),
                )
            )
        except CurveArtifactError as exc:
            audit.append(
                CurveArtifactAuditEntry(
                    artifact_dir=artifact_dir,
                    status="malformed",
                    error=str(exc),
                )
            )
    result = CurveArtifactStoreLoadResult(loaded=tuple(loaded), audit=tuple(audit))
    if raise_on_malformed and result.malformed:
        raise CurveArtifactStoreError(
            f"{len(result.malformed)} curve artifact(s) failed to load: "
            + "; ".join(
                f"{entry.artifact_dir}: {entry.error}" for entry in result.malformed
            )
        )
    return result


def _peek_schema_version(directory: Path) -> int | None:
    """Best-effort recovery of a schema_version from an artifact directory
    that failed full read/validation, so a failed migration entry can report
    the actual parsed version instead of always reporting 0 (Corrective PR
    A3). Returns ``None`` if no version could be parsed at all."""
    metadata_path = Path(directory) / CURVE_ARTIFACT_METADATA_FILENAME
    try:
        envelope = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(envelope, dict):
        return None
    metadata_payload = envelope.get("metadata")
    if isinstance(metadata_payload, dict):
        inner_version = metadata_payload.get("schema_version")
        if isinstance(inner_version, int):
            return inner_version
    outer_version = envelope.get("schema_version")
    if isinstance(outer_version, int):
        return outer_version
    return None


def migrate_curve_artifact_store(
    directory: Path,
    *,
    dry_run: bool = False,
    raise_on_error: bool = True,
) -> CurveArtifactMigrationResult:
    """Apply the schema migration hook to every artifact in a store.

    Each artifact is loaded (the metadata migration hook runs during load),
    and any artifact whose format migrated (``legacy`` → ``migrated``,
    REQ-CURVE-001 approved decision 4) is rewritten with recomputed
    fingerprints. Unsupported schema versions fail closed. ``dry_run``
    reports what would change without writing.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return CurveArtifactMigrationResult()
    entries: List[CurveArtifactMigrationEntry] = []
    for artifact_dir in _iter_artifact_dirs(directory):
        try:
            artifact = read_curve_artifact(artifact_dir)
        except CurveArtifactError as exc:
            parsed_version = _peek_schema_version(artifact_dir)
            entries.append(
                CurveArtifactMigrationEntry(
                    artifact_dir=artifact_dir,
                    migrated=False,
                    schema_version=(
                        parsed_version if parsed_version is not None else 0
                    ),
                    error=str(exc),
                )
            )
            continue
        metadata = artifact.metadata
        new_format_status = (
            "migrated" if metadata.format_status == "legacy" else metadata.format_status
        )
        needs_rewrite = new_format_status != metadata.format_status
        if needs_rewrite and not dry_run:
            migrated_metadata = replace(metadata, format_status=new_format_status)
            migrated_metadata = replace(
                migrated_metadata,
                fingerprints=dict(
                    compute_curve_artifact_fingerprints(migrated_metadata)
                ),
            )
            write_curve_artifact(
                artifact_dir,
                metadata=migrated_metadata,
                draws=artifact.draws,
                summaries=artifact.summaries,
            )
        entries.append(
            CurveArtifactMigrationEntry(
                artifact_dir=artifact_dir,
                migrated=needs_rewrite,
                schema_version=metadata.schema_version,
            )
        )
    result = CurveArtifactMigrationResult(tuple(entries))
    if raise_on_error and result.failed:
        raise CurveArtifactStoreError(
            f"{len(result.failed)} curve artifact(s) failed to migrate: "
            + "; ".join(
                f"{entry.artifact_dir}: {entry.error}" for entry in result.failed
            )
        )
    return result
