"""Durable Experiment Evidence adoption boundary (Work Package 2 of
`Media-Mix-Lab: Coding LLM Next Steps After PR #291`).

Connects the optional Experiment Evidence source domain to the governed
experiment registry (`core.experiments`) and the project lifecycle -
without implementing any calibration mathematics. No model-fitting module
reads this registry; no likelihood/prior translation exists here or is
implied.

Contract summary (REQ-EXPMODE-001 / REQ-CALIB-001):

- an uploaded evidence row never becomes an approved calibration input
  automatically: the analyst explicitly adopts it into an immutable,
  versioned `ExperimentRecord` at this boundary;
- every experiment-to-model use declares exactly one governed evidence
  mode;
- calibrating modes require a caller-evidenced `CompatibilityAssessment`
  and explicit affected prior/likelihood identity, and fail closed on
  double-counted dependence;
- provenance is always per experiment, never averaged;
- `validation_only`/`diagnostic_comparison` uses cannot alter fitting
  because nothing downstream reads the registry to build a model - this
  service performs no calibration computation of any kind.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from ancestry_mmm.core.experiments import (
    EVIDENCE_MODE_DIAGNOSTIC_COMPARISON,
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
    EVIDENCE_MODE_PRIOR_CALIBRATION,
    EVIDENCE_MODE_VALIDATION_ONLY,
    EXPERIMENT_REGISTRY_SCHEMA_VERSION,
    CompatibilityAssessment,
    ExperimentProvenanceReport,
    ExperimentRecord,
    ExperimentToModelUse,
    assess_experiment_compatibility,
    build_calibrating_use,
    build_provenance_report,
    current_experiment_versions,
    new_experiment_version,
    validate_no_double_counted_dependence,
)

# Newly adopted records default to an explicitly review-required evidence
# status - adoption is never approval. Analysts may set any status the
# existing free-text `evidence_status` field permits; nothing here infers
# one.
DEFAULT_EVIDENCE_STATUS = "draft_review_required"

_CALIBRATING_MODES = (
    EVIDENCE_MODE_PRIOR_CALIBRATION,
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
)

# ExperimentRecord fields a raw source evidence row can never supply by
# itself (the standard template carries only experiment_id, activity_id,
# market, start_date, end_date). They are required by the record contract
# and must be analyst-supplied at this adoption boundary - never invented,
# defaulted, or zero-filled.
ANALYST_REQUIRED_FIELDS = (
    "design",
    "estimand",
    "observed_effect_estimate",
    "effect_uncertainty",
    "method",
    "source",
    "evidence_status",
)

# Standard template columns mapped onto the record by adoption.
_SOURCE_ROW_COLUMNS = (
    "experiment_id",
    "activity_id",
    "market",
    "start_date",
    "end_date",
)


def missing_adoption_fields(
    row: Mapping[str, Any], analyst_input: Mapping[str, Any]
) -> Tuple[str, ...]:
    """The field names that still block adopting `row` into a full
    `ExperimentRecord`. Source-row-derived fields are checked against the
    row itself; the remaining required fields against the analyst's input.
    Never returns a fabricated default as if it were supplied."""
    missing = []
    for column in _SOURCE_ROW_COLUMNS:
        if not row.get(column):
            missing.append(column)
    for field in ANALYST_REQUIRED_FIELDS:
        if not analyst_input.get(field):
            missing.append(field)
    return tuple(missing)


def adopt_experiment_record(
    row: Mapping[str, Any], analyst_input: Mapping[str, Any]
) -> ExperimentRecord:
    """Adopt one source evidence row into an immutable, version-1
    `ExperimentRecord`. Raises `ValueError` listing every missing required
    field (source-derived or analyst-supplied) - the row is never adopted
    with a fabricated value."""
    missing = missing_adoption_fields(row, analyst_input)
    if missing:
        raise ValueError(
            "Cannot adopt this experiment evidence row - missing required "
            f"field(s): {', '.join(missing)}."
        )
    metadata: dict = {}
    if row.get("activity_id"):
        metadata["activity_id"] = row["activity_id"]
    return ExperimentRecord(
        experiment_id=str(row["experiment_id"]),
        experiment_version=1,
        design=str(analyst_input["design"]),
        start_date=str(row["start_date"]),
        end_date=str(row["end_date"]),
        market_scope=(str(row["market"]),),
        estimand=str(analyst_input["estimand"]),
        observed_effect_estimate=float(analyst_input["observed_effect_estimate"]),
        effect_uncertainty=float(analyst_input["effect_uncertainty"]),
        method=str(analyst_input["method"]),
        source=str(analyst_input["source"]),
        evidence_status=str(analyst_input["evidence_status"]),
        treatment_quantity=(
            float(analyst_input["treatment_quantity"])
            if analyst_input.get("treatment_quantity")
            else None
        ),
        limitations=tuple(analyst_input.get("limitations") or ()),
        overlapping_experiment_ids=tuple(
            analyst_input.get("overlapping_experiment_ids") or ()
        ),
        metadata=metadata,
    )


def register_experiment_record(
    records: Sequence[ExperimentRecord], record: ExperimentRecord
) -> Tuple[ExperimentRecord, ...]:
    """Append an adopted record to the registry. Re-adopting a row that is
    byte-identical (version ignored) to the current version is an idempotent
    no-op; re-adopting a row whose content differs from the current version
    raises - the registry is immutable, so an edit is a new version via
    `new_registered_experiment_version`, never a mutation."""
    current = {rec.experiment_id: rec for rec in current_experiment_versions(records)}
    existing = current.get(record.experiment_id)
    if existing is not None:
        existing_dict = existing.to_dict()
        incoming_dict = record.to_dict()
        existing_dict.pop("experiment_version")
        incoming_dict.pop("experiment_version")
        if existing_dict == incoming_dict:
            return tuple(records)
        raise ValueError(
            f"Experiment {record.experiment_id!r} is already registered "
            "with different content - create a new version instead of "
            "mutating the registry."
        )
    return tuple(records) + (record,)


def new_registered_experiment_version(
    records: Sequence[ExperimentRecord], experiment_id: str, **changes: Any
) -> Tuple[ExperimentRecord, ...]:
    """Create a new version of a registered experiment (never an in-place
    edit). Raises if the experiment has no registered version."""
    current = {rec.experiment_id: rec for rec in current_experiment_versions(records)}
    if experiment_id not in current:
        raise ValueError(
            f"Experiment {experiment_id!r} is not registered - adopt it "
            "before creating a new version."
        )
    return tuple(records) + (new_experiment_version(current[experiment_id], **changes),)


def build_compatibility_assessment(
    experiment_id: str,
    dimension_results: Mapping[str, bool],
    *,
    dimension_notes: Optional[Mapping[str, str]] = None,
    is_local: bool = False,
    scope_note: Optional[str] = None,
) -> CompatibilityAssessment:
    """Thin, UI-friendly wrapper over `core.experiments.
    assess_experiment_compatibility` - assembly + validation only, never
    inference about whether two scopes are compatible."""
    return assess_experiment_compatibility(
        experiment_id,
        dimension_results,
        dimension_notes=dimension_notes,
        is_local=is_local,
        scope_note=scope_note,
    )


def register_model_use(
    records: Sequence[ExperimentRecord],
    uses: Sequence[ExperimentToModelUse],
    *,
    experiment_id: str,
    experiment_version: int,
    evidence_mode: str,
    model_id: str,
    model_version: str,
    compatibility: Optional[CompatibilityAssessment] = None,
    affected_prior_name: Optional[str] = None,
    affected_prior_version: Optional[str] = None,
    affected_likelihood_term_name: Optional[str] = None,
    affected_likelihood_term_version: Optional[str] = None,
    dependence_handling_method: Optional[str] = None,
) -> Tuple[ExperimentToModelUse, ...]:
    """Register one experiment-to-model use with exactly one governed
    evidence mode, fail-closed:

    - the referenced experiment version must exist in the registry;
    - calibrating modes require a fully compatible `CompatibilityAssessment`
      (`build_calibrating_use` enforces this) plus explicit affected
      prior/likelihood identity;
    - `validation_only`/`diagnostic_comparison` require no compatibility
      assessment (they cannot alter fitting) but still declare their mode
      explicitly;
    - after appending, `validate_no_double_counted_dependence` runs: if the
      new use participates in a double-counted dependence without a
      `dependence_handling_method`, construction fails closed.

    Returns a new uses tuple; never mutates the registry or the model."""
    versioned = {(rec.experiment_id, rec.experiment_version): rec for rec in records}
    if (experiment_id, experiment_version) not in versioned:
        raise ValueError(
            f"Experiment {experiment_id!r} version {experiment_version} is "
            "not registered - register the version before referencing it."
        )

    if evidence_mode in _CALIBRATING_MODES:
        if compatibility is None:
            raise ValueError(
                f"Evidence mode {evidence_mode!r} requires a compatibility "
                "assessment - no calibrating use may be constructed without "
                "one."
            )
        if compatibility.experiment_id != experiment_id:
            raise ValueError(
                f"Compatibility assessment is for experiment "
                f"{compatibility.experiment_id!r}, not {experiment_id!r} - "
                "the two must never be mixed."
            )
        new_use = build_calibrating_use(
            compatibility,
            experiment_version=experiment_version,
            evidence_mode=evidence_mode,
            model_id=model_id,
            model_version=model_version,
            affected_prior_name=affected_prior_name,
            affected_prior_version=affected_prior_version,
            affected_likelihood_term_name=affected_likelihood_term_name,
            affected_likelihood_term_version=affected_likelihood_term_version,
            dependence_handling_method=dependence_handling_method,
        )
    elif evidence_mode in (
        EVIDENCE_MODE_VALIDATION_ONLY,
        EVIDENCE_MODE_DIAGNOSTIC_COMPARISON,
    ):
        new_use = ExperimentToModelUse(
            experiment_id=experiment_id,
            experiment_version=experiment_version,
            evidence_mode=evidence_mode,
            model_id=model_id,
            model_version=model_version,
            dependence_handling_method=dependence_handling_method,
        )
    else:
        raise ValueError(
            f"Unknown evidence mode {evidence_mode!r} - must be one of "
            f"{_CALIBRATING_MODES + (EVIDENCE_MODE_VALIDATION_ONLY, EVIDENCE_MODE_DIAGNOSTIC_COMPARISON)}."
        )

    new_uses = tuple(uses) + (new_use,)
    violations = validate_no_double_counted_dependence(new_uses)
    if violations and not new_use.dependence_handling_method:
        raise ValueError(
            "Registering this use creates a double-counted dependence for "
            f"experiment(s): {', '.join(violations)}. Two different "
            "calibrating modes against the same model require an explicit "
            "dependence_handling_method on every such use - refuse to "
            "register without one."
        )
    return new_uses


def provenance_for_model(
    records: Sequence[ExperimentRecord],
    uses: Sequence[ExperimentToModelUse],
    *,
    model_id: str,
    model_version: str,
) -> Optional[ExperimentProvenanceReport]:
    """The per-experiment (never averaged) provenance report for one model
    identity, or `None` when that model has no registered experiment uses -
    `None` is the caller's signal that no provenance exists, never an empty
    fabricated report."""
    model_uses = [
        use
        for use in uses
        if use.model_id == model_id and use.model_version == model_version
    ]
    if not model_uses:
        return None
    records_by_id = {
        rec.experiment_id: rec for rec in current_experiment_versions(records)
    }
    return build_provenance_report(model_id, model_version, model_uses, records_by_id)


def registry_to_dict(
    records: Sequence[ExperimentRecord],
    uses: Sequence[ExperimentToModelUse],
    assessments: Sequence[CompatibilityAssessment],
    evidence_rows: Sequence[Mapping[str, Any]],
) -> dict:
    """Serialise the full registry for project export - one stable dict
    with its own record-level `schema_version` so an importer can reject an
    unrecognised future schema instead of guessing."""
    return {
        "schema_version": EXPERIMENT_REGISTRY_SCHEMA_VERSION,
        "records": [rec.to_dict() for rec in records],
        "model_uses": [use.to_dict() for use in uses],
        "compatibility_assessments": [
            assessment.to_dict() for assessment in assessments
        ],
        "evidence_rows": [dict(row) for row in evidence_rows],
    }


def registry_has_content(
    records: Sequence[ExperimentRecord],
    uses: Sequence[ExperimentToModelUse],
    assessments: Sequence[CompatibilityAssessment],
    evidence_rows: Sequence[Mapping[str, Any]],
) -> bool:
    """Whether any part of the registry is non-empty - exporters use this
    to decide whether to write the registry file at all, keeping older
    bundles byte-comparable."""
    return bool(records or uses or assessments or evidence_rows)


def models_referenced_by_uses(
    uses: Iterable[ExperimentToModelUse],
) -> Tuple[Tuple[str, str], ...]:
    """The distinct (model_id, model_version) pairs any registered use
    references - used by import-time validation to report uses that point
    at a model identity this project does not contain."""
    return tuple(sorted({(use.model_id, use.model_version) for use in uses}))
