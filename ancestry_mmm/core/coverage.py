"""Variable coverage and mixed-frequency data authority (REQ-COVERAGE-001).

Framework-independent domain contracts translating the Part 3 v1.6 overlay's
approved invariants and canonical missingness-state vocabulary
(`docs/approved_requirements/REQ-COVERAGE-001.md` sections 1-5) into typed
objects a dependent requirement's source loader, join/frequency-conversion
services, and coverage-matrix UI build against - never the PRD text
directly.

This module intentionally does not touch `data.pipeline`, `data.loader`,
`core.persistence`, or any Streamlit page (REQ-COVERAGE-001 Work Package 3
Phase 1 of N - see `docs/decision_log.md` for the precedent of phasing a
large redesign into narrower PRs). It defines the vocabulary and invariants
those dependent, separately-scoped changes must satisfy.

Mirrors `core.activities`/`core.search_objects`'s established style: frozen
dataclasses, `__post_init__` validation, `to_dict`/`from_dict`, a strict
`schema_version` guard, and an immutable version-bump helper for the
persisted/versioned artefact (here, `VariableCoverageMatrix` as a whole -
mirroring `core.causal_graph.CausalGraph`'s single-versioned-object pattern
rather than per-record versioning, since a coverage matrix is reviewed and
approved as one snapshot).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Optional

# --- Canonical missingness-state vocabulary (REQ-COVERAGE-001 S2) ----------
#
# Never collapse into a nullable boolean or a single generic "missing" flag.
# A latent/modelled value (ESTIMATED/MODELLED) must never be stored or
# displayed as though it were an observed source fact.

STATE_OBSERVED_ZERO = "observed_zero"
STATE_MISSING_EXPECTED = "missing_expected"
STATE_NOT_APPLICABLE = "not_applicable"
STATE_UNAVAILABLE_SOURCE = "unavailable_source"
STATE_SUPPRESSED = "suppressed"
STATE_ESTIMATED = "estimated"
STATE_MODELLED = "modelled"
STATE_UNKNOWN = "unknown"

COVERAGE_STATES = (
    STATE_OBSERVED_ZERO,
    STATE_MISSING_EXPECTED,
    STATE_NOT_APPLICABLE,
    STATE_UNAVAILABLE_SOURCE,
    STATE_SUPPRESSED,
    STATE_ESTIMATED,
    STATE_MODELLED,
    STATE_UNKNOWN,
)

# States that must not become official fit input silently while unresolved
# (REQ-COVERAGE-001 S5): no approved treatment means the affected period
# stays exploratory/unsupported, never fabricated.
UNRESOLVED_BLOCKING_STATES = frozenset({STATE_UNKNOWN, STATE_MISSING_EXPECTED})

# --- Variable-class vocabulary (REQ-COVERAGE-001 S4) ------------------------
#
# "e.g." in the source record - non-exhaustive, but a single default
# conversion method must never be applied across classes, so an explicit,
# named class is required rather than a free-form string.

VARIABLE_CLASS_FLOW_COUNT = "flow_count"
VARIABLE_CLASS_STOCK_LEVEL = "stock_level"
VARIABLE_CLASS_RATE_INDEX = "rate_index"
VARIABLE_CLASS_SURVEY_MEASUREMENT = "survey_measurement"
VARIABLE_CLASS_EVENT_FLAG = "event_flag"

VARIABLE_CLASSES = (
    VARIABLE_CLASS_FLOW_COUNT,
    VARIABLE_CLASS_STOCK_LEVEL,
    VARIABLE_CLASS_RATE_INDEX,
    VARIABLE_CLASS_SURVEY_MEASUREMENT,
    VARIABLE_CLASS_EVENT_FLAG,
)

TREATMENT_STATUSES = {"proposed", "approved", "rejected"}

COVERAGE_MATRIX_SCHEMA_VERSION = 1


def _validate_period(start: Optional[str], end: Optional[str], *, label: str) -> None:
    """Mirrors `core.media_costs._validate_period` / `core.search_objects.
    _validate_effective_period`: `date.fromisoformat` itself raises
    `ValueError` for a malformed date string; an explicit start-after-end is
    rejected here."""
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    if start_date and end_date and start_date > end_date:
        raise ValueError(f"{label}_start must not be after {label}_end")


def _validate_matrix_schema_version(raw: Any) -> int:
    """Strict `schema_version` validation for `VariableCoverageMatrix.from_dict`
    - mirrors `core.search_objects._validate_search_object_schema_version`.
    `int(...)` coercion is not validation: it would silently accept a
    numeric string, truncate a float, or (since `bool` is an `int`
    subclass) accept `True`/`False` as `1`/`0`. Each is rejected outright,
    never coerced."""
    if isinstance(raw, bool) or type(raw) is not int:
        raise ValueError(
            f"VariableCoverageMatrix declares a non-integer schema_version "
            f"{raw!r} (type={type(raw).__name__}) - schema_version must be "
            "an actual integer, never a bool, float, numeric string, or "
            "other coercible value."
        )
    if raw < 1:
        raise ValueError(
            f"VariableCoverageMatrix declares schema_version {raw} - "
            "schema_version must be >= 1."
        )
    if raw > COVERAGE_MATRIX_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported VariableCoverageMatrix schema_version {raw} - "
            f"this build only understands up to {COVERAGE_MATRIX_SCHEMA_VERSION}."
        )
    return raw


@dataclass(frozen=True)
class DefinitionBreak:
    """A source-definition or methodology break inside the model window
    (REQ-COVERAGE-001 S1: "must be explicit, never silently interpolated
    through"). `bridge_treatment_approved=True` is the only thing that
    permits an approved dependent transformation to interpolate across
    `break_date` (S4) - it requires `approved_by`/`approved_at`, mirroring
    `core.activities.ActivityDefinition`'s approval-requires-attribution
    pattern.
    """

    break_date: str
    description: str
    bridge_treatment_approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.break_date or not self.description:
            raise ValueError("break_date and description are required")
        date.fromisoformat(self.break_date)
        if self.bridge_treatment_approved and not (
            self.approved_by and self.approved_at
        ):
            raise ValueError(
                "an approved bridge treatment requires approved_by and approved_at"
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "DefinitionBreak":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in values.items() if k in known})


@dataclass(frozen=True)
class FrequencyMetadata:
    """Versioned frequency-conversion metadata, distinct from a generic fill
    operation (REQ-COVERAGE-001 S4). `variable_class` gates which conversion
    methods are even eligible for a dependent transformation - it does not
    itself perform any conversion."""

    native_frequency: str
    target_frequency: str
    variable_class: str
    publication_lag_periods: int = 0
    method: str = ""
    reconciliation_rule: str = ""

    def __post_init__(self) -> None:
        if not self.native_frequency or not self.target_frequency:
            raise ValueError("native_frequency and target_frequency are required")
        if self.variable_class not in VARIABLE_CLASSES:
            raise ValueError(
                f"invalid variable_class {self.variable_class!r}; "
                f"must be one of {VARIABLE_CLASSES}"
            )
        if self.publication_lag_periods < 0:
            raise ValueError("publication_lag_periods must be >= 0")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "FrequencyMetadata":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in values.items() if k in known})


@dataclass(frozen=True)
class SourceDefinition:
    """A named, stable source identity - `core.activities.ActivityDefinition.
    source`-style provenance made a first-class governed object, distinct
    from any one upload of it (see `SourceVersion`)."""

    source_id: str
    name: str
    owner: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.source_id or not self.name:
            raise ValueError("source_id and name are required")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SourceDefinition":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in values.items() if k in known})


@dataclass(frozen=True)
class SourceVersion:
    """One immutable upload event under a `SourceDefinition` lineage
    (REQ-COVERAGE-001 S3): enough identity to reproduce provenance from a
    checksum, without requiring the original bytes be embedded in the
    portable project bundle. `byte_reference` is an optional pointer to a
    documented local artefact (e.g. a D-drive path) when retaining the
    original file is appropriate; its absence does not make this record
    invalid - the checksum/filename/size triple is the minimum contract.
    """

    source_id: str
    version: int
    original_filename: str
    checksum: str
    size_bytes: int
    uploaded_at: str
    parsed_representation_version: str
    byte_reference: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.source_id or not self.original_filename:
            raise ValueError("source_id and original_filename are required")
        if not self.checksum or len(self.checksum) != 64:
            raise ValueError(
                "checksum must be a 64-character sha256 hex digest, got "
                f"{self.checksum!r}"
            )
        try:
            int(self.checksum, 16)
        except ValueError as exc:
            raise ValueError(f"checksum is not valid hex: {self.checksum!r}") from exc
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be >= 0")
        if not self.parsed_representation_version:
            raise ValueError("parsed_representation_version is required")

    @property
    def source_key(self) -> tuple[str, int]:
        return self.source_id, self.version

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SourceVersion":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in values.items() if k in known})


def current_source_versions(
    versions: Iterable["SourceVersion | Mapping[str, Any]"],
) -> list[SourceVersion]:
    """Resolve, per `source_id` lineage, the current (highest `version`)
    record - mirrors `core.search_objects.current_search_object_versions`.
    """
    latest: dict[str, SourceVersion] = {}
    for item in versions:
        v = item if isinstance(item, SourceVersion) else SourceVersion.from_dict(item)
        current = latest.get(v.source_id)
        if current is None or v.version > current.version:
            latest[v.source_id] = v
    return list(latest.values())


def compute_checksum(data: bytes) -> str:
    """The single sanctioned way to compute a `SourceVersion.checksum` -
    sha256 over the raw uploaded bytes, so two dependent callers can never
    silently disagree on the hashing method."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class CoverageSegment:
    """One auditable, chronologically-scoped state-run within a variable's
    history (REQ-COVERAGE-001 S1/S3: "coverage state by unsupported period
    or an auditable compact equivalent" - a compact run-length encoding
    rather than one row per period). `structural_zero=True` is the only way
    a segment may assert "the activity genuinely did not exist" (S1); it
    requires a non-empty `justification` so the claim is auditable, never
    inferred merely because a value happens to be zero."""

    period_start: str
    period_end: str
    state: str
    structural_zero: bool = False
    justification: str = ""

    def __post_init__(self) -> None:
        if not self.period_start or not self.period_end:
            raise ValueError("period_start and period_end are required")
        _validate_period(self.period_start, self.period_end, label="period")
        if self.state not in COVERAGE_STATES:
            raise ValueError(
                f"invalid coverage state {self.state!r}; must be one of {COVERAGE_STATES}"
            )
        if self.structural_zero:
            if self.state != STATE_OBSERVED_ZERO:
                raise ValueError(
                    "structural_zero=True requires state='observed_zero' - "
                    f"got {self.state!r}"
                )
            if not self.justification:
                raise ValueError(
                    "a structural-zero segment requires a non-empty "
                    "justification (REQ-COVERAGE-001 S1: pre-launch may be "
                    "structural zero only when the activity genuinely did "
                    "not exist)"
                )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CoverageSegment":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in values.items() if k in known})


def _validate_non_overlapping_segments(segments: tuple[CoverageSegment, ...]) -> None:
    ordered = sorted(segments, key=lambda s: s.period_start)
    for previous, current in zip(ordered, ordered[1:]):
        if date.fromisoformat(current.period_start) <= date.fromisoformat(
            previous.period_end
        ):
            raise ValueError(
                "coverage_segments must not overlap: "
                f"{previous.period_start}..{previous.period_end} overlaps "
                f"{current.period_start}..{current.period_end}"
            )


@dataclass(frozen=True)
class VariableCoverageRecord:
    """One variable's coverage/treatment record at
    `market x product_or_none x segment_or_none` grain (REQ-COVERAGE-001
    S3). Observed values are never stored here - this is metadata *about*
    a variable's history, kept structurally distinct from the model-ready
    numeric frame a dependent transformation service produces from it."""

    variable_id: str
    source_id: str
    source_version: int
    market: str
    frequency: FrequencyMetadata
    coverage_segments: tuple[CoverageSegment, ...]
    product: Optional[str] = None
    segment: Optional[str] = None
    observed_start: Optional[str] = None
    observed_end: Optional[str] = None
    expected_start: Optional[str] = None
    expected_end: Optional[str] = None
    effective_start: Optional[str] = None
    effective_end: Optional[str] = None
    definition_breaks: tuple[DefinitionBreak, ...] = ()
    proposed_treatment: str = ""
    approved_treatment: Optional[str] = None
    treatment_status: str = "proposed"
    treatment_approved_by: Optional[str] = None
    treatment_approved_at: Optional[str] = None
    owner: str = ""

    def __post_init__(self) -> None:
        if not self.variable_id or not self.source_id:
            raise ValueError("variable_id and source_id are required")
        if not self.market:
            raise ValueError("market is required; use '*' for all markets")
        if self.source_version < 1:
            raise ValueError("source_version must be >= 1")
        if self.treatment_status not in TREATMENT_STATUSES:
            raise ValueError(f"invalid treatment_status {self.treatment_status!r}")
        if self.treatment_status == "approved" and not (
            self.approved_treatment
            and self.treatment_approved_by
            and self.treatment_approved_at
        ):
            raise ValueError(
                "treatment_status='approved' requires approved_treatment, "
                "treatment_approved_by, and treatment_approved_at"
            )
        for label, start, end in (
            ("observed", self.observed_start, self.observed_end),
            ("expected", self.expected_start, self.expected_end),
            ("effective", self.effective_start, self.effective_end),
        ):
            _validate_period(start, end, label=label)
        _validate_non_overlapping_segments(self.coverage_segments)

    @property
    def variable_key(self) -> tuple[str, str, Optional[str], Optional[str]]:
        return self.variable_id, self.market, self.product, self.segment

    @property
    def is_officially_unresolved(self) -> bool:
        """REQ-COVERAGE-001 S5: unresolved `unknown`/`missing_expected`
        coverage must not become official fit input silently - a record
        with any such segment must stay exploratory unless/until its
        treatment is approved."""
        if self.treatment_status == "approved":
            return False
        return any(
            segment.state in UNRESOLVED_BLOCKING_STATES
            for segment in self.coverage_segments
        )

    def to_dict(self) -> dict:
        return {
            **{
                k: v
                for k, v in asdict(self).items()
                if k not in {"frequency", "coverage_segments", "definition_breaks"}
            },
            "frequency": self.frequency.to_dict(),
            "coverage_segments": [s.to_dict() for s in self.coverage_segments],
            "definition_breaks": [b.to_dict() for b in self.definition_breaks],
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "VariableCoverageRecord":
        payload = dict(values)
        payload.setdefault("market", "*")
        payload["frequency"] = FrequencyMetadata.from_dict(payload["frequency"])
        payload["coverage_segments"] = tuple(
            CoverageSegment.from_dict(s) for s in payload.get("coverage_segments") or ()
        )
        payload["definition_breaks"] = tuple(
            DefinitionBreak.from_dict(b) for b in payload.get("definition_breaks") or ()
        )
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in payload.items() if k in known})


def official_fit_blocking_issues(
    records: Iterable[VariableCoverageRecord],
) -> list[str]:
    """REQ-COVERAGE-001 S5: enumerate every record whose unresolved coverage
    would otherwise become official fit input silently. An empty result
    does not mean the data is fit for use - only that no record is
    currently blocked on this specific invariant."""
    issues = []
    for record in records:
        if record.is_officially_unresolved:
            blocking_states = sorted(
                {
                    segment.state
                    for segment in record.coverage_segments
                    if segment.state in UNRESOLVED_BLOCKING_STATES
                }
            )
            issues.append(
                f"{record.variable_id!r} ({record.market}) has unresolved "
                f"{', '.join(blocking_states)} coverage with no approved "
                "treatment"
            )
    return issues


def variable_coverage_records_fingerprint(
    records: Iterable[VariableCoverageRecord | Mapping[str, Any]],
) -> str:
    """Coverage-change staleness fingerprint (REQ-COVERAGE-001 S5): a
    coverage or treatment change that alters prepared-data semantics must
    change prepared-data/model identity through the existing fingerprint
    mechanism (`core.fingerprint.fingerprint_model_spec`); a dependent
    requirement wires this into that mechanism, this module only defines
    the deterministic payload to hash."""
    payload = [
        (
            item.to_dict()
            if isinstance(item, VariableCoverageRecord)
            else VariableCoverageRecord.from_dict(item).to_dict()
        )
        for item in records
    ]
    payload.sort(
        key=lambda item: (
            str(item.get("variable_id")),
            str(item.get("market")),
            str(item.get("product")),
            str(item.get("segment")),
        )
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class VariableCoverageMatrix:
    """A versioned, persisted snapshot of every `VariableCoverageRecord`
    reviewed together (REQ-COVERAGE-001 S1: "coverage decisions must be
    versioned and portable"; S3: "reviewable before model preparation").
    Mirrors `core.causal_graph.CausalGraph`'s single-versioned-object
    pattern: the whole matrix is one lineage, not each record independently
    versioned."""

    matrix_id: str
    matrix_version: int
    generated_at: str
    records: tuple[VariableCoverageRecord, ...] = ()
    notes: str = ""
    schema_version: int = COVERAGE_MATRIX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.matrix_id:
            raise ValueError("matrix_id is required")
        if self.matrix_version < 1:
            raise ValueError("matrix_version must be >= 1")

    @property
    def matrix_key(self) -> str:
        return self.matrix_id

    @property
    def blocking_issues(self) -> list[str]:
        return official_fit_blocking_issues(self.records)

    def fingerprint(self) -> str:
        return variable_coverage_records_fingerprint(self.records)

    def to_dict(self) -> dict:
        return {
            "matrix_id": self.matrix_id,
            "matrix_version": self.matrix_version,
            "generated_at": self.generated_at,
            "notes": self.notes,
            "schema_version": self.schema_version,
            "records": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "VariableCoverageMatrix":
        """A legacy record predating `schema_version` (no key at all - the
        genuinely-absent case, mirroring `SearchObjectDefinition.from_dict`)
        resolves to the current schema version. A record that *does* supply
        `schema_version` - including an explicit `null` - is validated
        strictly; a malformed or above-supported value raises rather than
        being silently coerced or accepted."""
        payload = dict(values)
        if "schema_version" in payload:
            schema_version = _validate_matrix_schema_version(payload["schema_version"])
        else:
            schema_version = COVERAGE_MATRIX_SCHEMA_VERSION
        payload["schema_version"] = schema_version
        payload["records"] = tuple(
            VariableCoverageRecord.from_dict(r) for r in payload.get("records") or ()
        )
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in payload.items() if k in known})


def new_variable_coverage_matrix_version(
    matrix: VariableCoverageMatrix, **changes: Any
) -> VariableCoverageMatrix:
    """Apply an edit to a governed coverage matrix as a new version - never
    an in-place mutation of history (REQ-COVERAGE-001 S1/S5), mirroring
    `core.search_objects.new_search_object_version`. `matrix_id` is this
    record's lineage identity and may never be changed here; `matrix_version`
    may also not be passed in `changes` - it is always exactly
    `matrix.matrix_version + 1`."""
    for locked_field in ("matrix_id", "matrix_version"):
        if locked_field in changes:
            raise ValueError(
                f"{locked_field!r} is lineage/version identity and cannot be "
                "set via new_variable_coverage_matrix_version - construct a "
                "new VariableCoverageMatrix directly to register a "
                "genuinely different matrix."
            )
    payload = {**asdict_shallow(matrix), **changes}
    payload["matrix_version"] = matrix.matrix_version + 1
    return VariableCoverageMatrix(
        matrix_id=payload["matrix_id"],
        matrix_version=payload["matrix_version"],
        generated_at=payload["generated_at"],
        records=payload["records"],
        notes=payload["notes"],
        schema_version=payload["schema_version"],
    )


def asdict_shallow(matrix: VariableCoverageMatrix) -> dict:
    """A shallow field copy (unlike `dataclasses.asdict`, does not recurse
    into `VariableCoverageRecord`/`FrequencyMetadata` and convert them to
    plain dicts) - `new_variable_coverage_matrix_version` needs the actual
    frozen-dataclass instances back, not a JSON-shaped copy."""
    return {f: getattr(matrix, f) for f in matrix.__dataclass_fields__}
