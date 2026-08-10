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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Any, List, Optional

import pandas as pd

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

# v1: initial VariableCoverageRecord shape (no `approved_for_official_use`;
#     `treatment_status == "approved"` alone cleared `is_officially_unresolved`).
# v2: added `VariableCoverageRecord.approved_for_official_use` - a v1 payload
#     (predating the field entirely) migrates fail-closed, never granted:
#     `approved_for_official_use` defaults to `False` regardless of any v1
#     `treatment_status == "approved"` value, so a previously "accepted"
#     record requires explicit re-approval under the new contract rather
#     than being silently promoted to (or left assuming) official-fit
#     eligibility. This is a deliberate migration decision (root AGENTS.md
#     Persistence: "changes to persistence require migration ... tests" -
#     see `TestLegacySchemaV1Migration` in `test_coverage.py`), not an
#     unversioned behaviour change.
COVERAGE_MATRIX_SCHEMA_VERSION = 2


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
    approved_for_official_use: bool = False
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
        if type(self.approved_for_official_use) is not bool:
            raise ValueError(
                "approved_for_official_use must be an actual bool, got "
                f"{self.approved_for_official_use!r} (type="
                f"{type(self.approved_for_official_use).__name__}) - never "
                "coerced from a truthy string, int, or other value; "
                "is_officially_unresolved reads this field directly, so a "
                "non-bool value (e.g. the JSON string 'false', which is "
                "truthy in Python) could otherwise silently clear the "
                "official-fit block."
            )
        if self.approved_for_official_use and self.treatment_status != "approved":
            raise ValueError(
                "approved_for_official_use=True requires treatment_status="
                "'approved' - a record cannot be officially fit-eligible "
                "without an approved treatment behind it"
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
        coverage must not become official fit input silently. An *approved*
        treatment alone is not enough to clear this - approving a treatment
        of, say, "exploratory_only" is itself a governance decision to keep
        the record excluded from official use, and treating that approval
        as if it resolved the blocking state would be exactly the silent
        promotion this invariant exists to prevent. Only the explicit,
        separately-gated `approved_for_official_use` flag (which itself
        requires `treatment_status='approved'`, never the reverse) clears
        this - approval attribution alone never does."""
        if self.approved_for_official_use:
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

    def fit_relevant_fields(self) -> dict:
        """The subset of this record that actually determines a prepared
        dataset's values (REQ-COVERAGE-001 S5: "a coverage or treatment
        change that alters prepared-data semantics must change
        prepared-data/model identity ... a purely presentational metadata
        change must not"). Mirrors the boundary rule
        `core.fingerprint._model_relevant_market_config` already
        established: a field belongs here the moment a dependent
        transformation/model-preparation step would read it to decide what
        numeric value or support boundary to produce.

        Excluded as administrative/audit-only, not calculation-relevant:
        `owner` (record ownership), `proposed_treatment` (a proposal, not
        what is actually applied), `treatment_approved_by`/
        `treatment_approved_at` (attribution, not content),
        `observed_start`/`observed_end`/`expected_start`/`expected_end`
        (diagnostic annotations for review - `effective_start`/
        `effective_end` is what a dependent preparation step actually
        honours), each `CoverageSegment.justification` (audit text) and
        each `DefinitionBreak.description`/`approved_by`/`approved_at`
        (audit text/attribution, not the break's date or whether bridging
        is permitted)."""
        return {
            "variable_id": self.variable_id,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "market": self.market,
            "product": self.product,
            "segment": self.segment,
            "frequency": self.frequency.to_dict(),
            "coverage_segments": [
                {
                    "period_start": s.period_start,
                    "period_end": s.period_end,
                    "state": s.state,
                    "structural_zero": s.structural_zero,
                }
                for s in self.coverage_segments
            ],
            "definition_breaks": [
                {
                    "break_date": b.break_date,
                    "bridge_treatment_approved": b.bridge_treatment_approved,
                }
                for b in self.definition_breaks
            ],
            "effective_start": self.effective_start,
            "effective_end": self.effective_end,
            "approved_treatment": self.approved_treatment,
            "treatment_status": self.treatment_status,
            "approved_for_official_use": self.approved_for_official_use,
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
                f"{', '.join(blocking_states)} coverage not approved for "
                "official use"
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
    the deterministic payload to hash. Hashes `fit_relevant_fields()`, not
    `to_dict()` - administrative/audit-only metadata (`owner`,
    `proposed_treatment`, approval attribution, observed/expected windows,
    free-text justifications) must not stale a fit merely because it
    changed."""
    payload = [
        (
            item.fit_relevant_fields()
            if isinstance(item, VariableCoverageRecord)
            else VariableCoverageRecord.from_dict(item).fit_relevant_fields()
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


# --- Coverage-matrix generation from a real joined frame (WP3 Phase 3) -----


def _observed_dates_for_market(
    market_frame: pd.DataFrame, date_col: str, variable: str
) -> set:
    """The subset of `market_frame`'s own dates where `variable` has a
    genuinely non-null value - a row that doesn't exist for this market at
    all is already absent from `market_frame`, so it can never appear
    here, exactly like a row whose value is null."""
    if variable not in market_frame.columns:
        return set()
    observed = market_frame.loc[market_frame[variable].notna(), date_col]
    return {pd.Timestamp(d) for d in observed}


# Recognised target_frequency labels this builder can turn into a
# governed calendar of expected periods (REQ-COVERAGE-001 S4's
# variable-class-specific handling extended to frequency labels). An
# unrecognised or genuinely irregular frequency has no fixed step to
# construct a calendar from - see _expected_periods's fallback.
_FREQUENCY_TO_PANDAS_ALIAS = {
    "daily": "D",
    "weekly": "W-MON",
    "monthly": "MS",
    "quarterly": "QS",
}


def _expected_periods(
    target_frequency: str,
    project_start: pd.Timestamp,
    project_end: pd.Timestamp,
    project_dates: list,
) -> list:
    """The full calendar of periods a variable at `target_frequency` is
    expected to have between the project's own start/end - constructed
    from the *governed frequency*, not merely from whatever dates happen
    to appear in the uploaded rows. A period missing from every source
    (e.g. a week no source has any row for at all) is still a real gap;
    deriving the expected calendar only from observed rows would make it
    invisible (P1 review finding on an earlier version of this builder).

    An unrecognised `target_frequency` (including "irregular", which
    REQ-COVERAGE-001 S1 explicitly names as a valid case) has no fixed
    step to construct a calendar from - it falls back to the project's
    own observed dates, the best obtainable basis, rather than raising or
    guessing a step.
    """
    alias = _FREQUENCY_TO_PANDAS_ALIAS.get(target_frequency.strip().lower())
    if alias is None:
        return project_dates
    return list(pd.date_range(start=project_start, end=project_end, freq=alias))


def _gap_segments(
    expected_periods: list, observed_dates: set
) -> tuple["CoverageSegment", ...]:
    """Group every period in `expected_periods` that is NOT in
    `observed_dates` into contiguous runs (by position in the sorted
    expected-periods list) and return one `unknown` `CoverageSegment` per
    run. `unknown` - never a guessed state - is the only state this
    function ever assigns: REQ-COVERAGE-001 S1 forbids inferring
    `not_applicable`/`unavailable_source`/structural `observed_zero`
    merely from an absent value; a human must reclassify each gap this
    function surfaces."""
    segments = []
    run_start = None
    previous_date = None
    for current_date in sorted(expected_periods):
        if current_date in observed_dates:
            if run_start is not None:
                # previous_date was set on every prior loop iteration, and
                # a run only starts inside this loop, so it is always
                # non-None here - mypy cannot see that cross-iteration
                # invariant on its own.
                assert previous_date is not None
                segments.append(
                    CoverageSegment(
                        period_start=run_start.strftime("%Y-%m-%d"),
                        period_end=previous_date.strftime("%Y-%m-%d"),
                        state=STATE_UNKNOWN,
                    )
                )
                run_start = None
        else:
            if run_start is None:
                run_start = current_date
        previous_date = current_date
    if run_start is not None:
        assert previous_date is not None
        segments.append(
            CoverageSegment(
                period_start=run_start.strftime("%Y-%m-%d"),
                period_end=previous_date.strftime("%Y-%m-%d"),
                state=STATE_UNKNOWN,
            )
        )
    return tuple(segments)


def build_coverage_matrix_from_frame(
    df: pd.DataFrame,
    *,
    date_col: str,
    market_col: str,
    variable_columns: Iterable[str],
    frequency_metadata: Mapping[str, FrequencyMetadata],
    variable_sources: Mapping[str, "tuple[str, int]"],
    matrix_id: str,
    matrix_version: int,
    generated_at: str,
    product_col: Optional[str] = None,
    segment_col: Optional[str] = None,
) -> VariableCoverageMatrix:
    """Generate a `VariableCoverageMatrix` from an already-joined DataFrame -
    the missing link between the Phase 1 domain contracts and real data
    (REQ-COVERAGE-001 S3: "every candidate model must expose a variable
    coverage matrix before fitting").

    Only mechanically observable facts are computed: `expected_start`/
    `expected_end` (the project's own full date range, across every
    market - v1.6's "never truncate to the narrowest common window" reread
    the other way: a market missing early history is measured against the
    *project's* window, not shrunk down to its own), `observed_start`/
    `observed_end` (this market/product/segment's own non-null date range
    for the variable, `None` if entirely absent), and gap segments (every
    period the variable's own governed frequency expects that this
    market/product/segment does not have, grouped into contiguous
    `unknown` runs via `_gap_segments`/`_expected_periods`) - a period
    missing from every source entirely is still checked, not merely
    whatever dates happen to appear in the uploaded rows.

    What this function deliberately does NOT do: classify *why* a gap
    exists (`not_applicable` vs `unavailable_source` vs a genuine
    structural pre-launch `observed_zero`) - every gap is `unknown` until
    a human reclassifies it, matching this record's core invariant that a
    state must never be inferred merely because a value is absent. It also
    never assigns a state to an *observed* value - the eight-state
    vocabulary describes exceptions, not confirmation that ordinary data
    is present.

    `frequency_metadata` and `variable_sources` must each supply an entry
    for every `variable_columns` entry - REQ-COVERAGE-001 S4 forbids a
    single default conversion method/variable-class assumption, and a
    joined frame routinely combines several distinct uploads (e.g. media
    from one source, controls from another), so provenance can never be a
    single value applied to every variable either. Both raise rather than
    guessing when an entry is missing.

    `product_col`/`segment_col` (optional): when a joined frame stacks
    more than one product or segment's data under shared variable column
    names (rather than each product/segment already being its own
    distinctly-named column, this app's more common shape), pass the
    discriminator column(s) so coverage is computed per
    `market x product x segment` grain, not silently unioned across them -
    a value present for one product/segment must never hide that the same
    variable is entirely absent for another.
    """
    variable_columns = list(variable_columns)
    missing_frequency = [v for v in variable_columns if v not in frequency_metadata]
    if missing_frequency:
        raise ValueError(
            "frequency_metadata is missing an entry for: "
            f"{missing_frequency} - every variable requires an explicit, "
            "governed FrequencyMetadata (REQ-COVERAGE-001 S4), never a "
            "default assumption."
        )
    missing_sources = [v for v in variable_columns if v not in variable_sources]
    if missing_sources:
        raise ValueError(
            "variable_sources is missing an entry for: "
            f"{missing_sources} - every variable requires its own explicit "
            "(source_id, source_version), never a single provenance value "
            "assumed for every variable in a joined frame."
        )

    project_dates = sorted({pd.Timestamp(d) for d in df[date_col].unique()})
    if not project_dates:
        raise ValueError("df has no dates to build a coverage matrix from.")
    project_start = project_dates[0]
    project_end = project_dates[-1]
    expected_start = project_start.strftime("%Y-%m-%d")
    expected_end = project_end.strftime("%Y-%m-%d")

    scope_cols = [c for c in (product_col, segment_col) if c is not None]

    records = []
    for market in sorted(df[market_col].astype(str).unique()):
        market_frame = df[df[market_col].astype(str) == market]
        if scope_cols:
            scopes = list(
                market_frame[scope_cols]
                .drop_duplicates()
                .itertuples(index=False, name=None)
            )
        else:
            scopes = [()]

        for scope in scopes:
            scoped_frame = market_frame
            product = segment = None
            remaining = list(scope)
            if product_col is not None:
                product = remaining.pop(0)
                scoped_frame = scoped_frame[scoped_frame[product_col] == product]
            if segment_col is not None:
                segment = remaining.pop(0)
                scoped_frame = scoped_frame[scoped_frame[segment_col] == segment]

            for variable in variable_columns:
                target_frequency = frequency_metadata[variable].target_frequency
                expected_periods = _expected_periods(
                    target_frequency, project_start, project_end, project_dates
                )
                observed_dates = _observed_dates_for_market(
                    scoped_frame, date_col, variable
                )
                observed_start = (
                    min(observed_dates).strftime("%Y-%m-%d") if observed_dates else None
                )
                observed_end = (
                    max(observed_dates).strftime("%Y-%m-%d") if observed_dates else None
                )
                source_id, source_version = variable_sources[variable]
                records.append(
                    VariableCoverageRecord(
                        variable_id=variable,
                        source_id=source_id,
                        source_version=source_version,
                        market=market,
                        product=product,
                        segment=segment,
                        frequency=frequency_metadata[variable],
                        coverage_segments=_gap_segments(
                            expected_periods, observed_dates
                        ),
                        observed_start=observed_start,
                        observed_end=observed_end,
                        expected_start=expected_start,
                        expected_end=expected_end,
                    )
                )

    return VariableCoverageMatrix(
        matrix_id=matrix_id,
        matrix_version=matrix_version,
        generated_at=generated_at,
        records=tuple(records),
    )


def carry_forward_treatment_decisions(
    new_records: Iterable[VariableCoverageRecord],
    previous_records: Iterable[VariableCoverageRecord],
) -> "tuple[VariableCoverageRecord, ...]":
    """Re-running `build_coverage_matrix_from_frame` (e.g. after adding a
    variable, or simply refreshing against updated data) produces entirely
    fresh `VariableCoverageRecord`s with default (`treatment_status=
    "proposed"`, `approved_for_official_use=False`) treatment fields -
    without this, every previously-reviewed and approved treatment decision
    would be silently discarded on every rebuild, which is exactly what
    REQ-COVERAGE-001 S1 ("coverage decisions must be versioned and
    portable") forbids losing.

    For each `new_records` entry, if a `previous_records` entry shares its
    `variable_key` (`variable_id`, `market`, `product`, `segment`) AND the
    two agree on every fact a treatment decision was actually made *about*
    (`frequency`, `coverage_segments`, `source_id`, `source_version`), the
    previous record's treatment fields (`proposed_treatment`,
    `approved_treatment`, `treatment_status`, `treatment_approved_by`,
    `treatment_approved_at`, `approved_for_official_use`, `owner`) are
    carried onto the new record. When the underlying facts genuinely
    changed (a different coverage gap, a new source version, ...), the new
    record keeps its fresh, unresolved default instead - carrying an
    approval forward across a *changed* set of facts would be exactly the
    silent promotion REQ-COVERAGE-001 S5 exists to prevent, the mirror
    image of why `is_officially_unresolved` never trusts `treatment_status`
    alone. A `new_records` entry with no matching key (a genuinely new
    variable/market/product/segment combination) is returned unchanged.
    """
    previous_by_key = {record.variable_key: record for record in previous_records}
    carried = []
    for record in new_records:
        previous = previous_by_key.get(record.variable_key)
        if previous is None:
            carried.append(record)
            continue
        same_facts = (
            record.frequency == previous.frequency
            and record.coverage_segments == previous.coverage_segments
            and record.source_id == previous.source_id
            and record.source_version == previous.source_version
        )
        if not same_facts:
            carried.append(record)
            continue
        carried.append(
            replace(
                record,
                proposed_treatment=previous.proposed_treatment,
                approved_treatment=previous.approved_treatment,
                treatment_status=previous.treatment_status,
                treatment_approved_by=previous.treatment_approved_by,
                treatment_approved_at=previous.treatment_approved_at,
                approved_for_official_use=previous.approved_for_official_use,
                owner=previous.owner,
            )
        )
    return tuple(carried)


# --- Project export/import portability (REQ-COVERAGE-001 S1: "coverage
# decisions must be versioned and portable - survive project export/import
# exactly") - mirrors `core.causal_graph`'s single-lineage version-history
# pattern (`graph_versions_for_export`/`current_graph_from_resolved_versions`)
# exactly, since `VariableCoverageMatrix` deliberately mirrors `CausalGraph`'s
# "whole artefact is one lineage, not each record independently versioned"
# shape (see this module's docstring). -------------------------------------


def current_variable_coverage_matrix_from_resolved_versions(
    resolved_versions: Sequence[Mapping[str, Any]],
) -> Optional[dict]:
    """Which restored matrix version becomes "current" after importing a
    project bundle (`core.persistence.resolve_imported_variable_coverage_
    matrices`'s output) - the highest-numbered version, this project's
    single coverage-matrix lineage's most recently saved state. `None` when
    no matrix versions were resolved at all - "no coverage matrix" restores
    to "no coverage matrix", never fabricated. Mirrors `core.causal_graph.
    current_graph_from_resolved_versions`."""
    if not resolved_versions:
        return None
    best = max(resolved_versions, key=lambda m: int(m.get("matrix_version", 0)))
    return dict(best)


def variable_coverage_matrix_versions_for_export(
    *,
    current_matrix_dict: Optional[Mapping[str, Any]],
    version_history: Optional[Sequence[Mapping[str, Any]]],
) -> List[dict]:
    """The coverage-matrix version records worth persisting in a project
    export bundle (`core.persistence.export_project`'s
    `variable_coverage_matrices` argument): every explicitly saved version
    (`version_history` - appended whenever the coverage-matrix review page
    saves a new version) plus the current live matrix, so a brand-new,
    never-yet-saved matrix is not silently lost across an export/import
    round trip. Mirrors `core.causal_graph.graph_versions_for_export`
    exactly, including its collision rule: `version_history` is always
    authoritative for a `(matrix_id, matrix_version)` key it already
    contains; the current live matrix is added only when its key is new or
    identical in content to the already-saved record under that key - a
    live matrix that shares a key with a saved record but has *different*
    content is an unsaved edit that must never silently overwrite the saved
    record it collided with, dropped from the export the same way any other
    unsaved widget edit elsewhere in the app already isn't durable until
    explicitly saved."""
    history_by_key: "dict[tuple[str, int], dict]" = {}
    for item in version_history or []:
        key = (str(item.get("matrix_id", "")), int(item.get("matrix_version", 0)))
        history_by_key[key] = dict(item)
    if current_matrix_dict:
        key = (
            str(current_matrix_dict.get("matrix_id", "")),
            int(current_matrix_dict.get("matrix_version", 0)),
        )
        existing = history_by_key.get(key)
        if existing is None or existing == dict(current_matrix_dict):
            history_by_key[key] = dict(current_matrix_dict)
    return list(history_by_key.values())
