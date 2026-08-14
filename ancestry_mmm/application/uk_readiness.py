"""Local-only UK lifecycle readiness orchestration.

The readiness harness is deliberately a reporting boundary, not a second
model runner.  It reuses the standard source-pack parser/adoption boundary,
the native weekly preparation gate, coverage capability reporting, and the
existing project-bundle resumability audit.  It never prints source rows,
fills missing values, selects a frequency-conversion method, or creates an
approval on behalf of an analyst.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pandas as pd

from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    DOMAIN_EXPERIMENT_EVIDENCE,
    DOMAIN_OUTCOMES,
    FrequencyMetadata,
    VariableCoverageMatrix,
    build_coverage_matrix_from_frame,
)
from ancestry_mmm.core.frequency_alignment import assess_official_preparation
from ancestry_mmm.core.official_preparation import (
    OfficialPreparationDataError,
    build_official_capability_report,
    prepare_canonical_native_frame,
)
from ancestry_mmm.core.outcomes import OutcomeDefinition
from ancestry_mmm.core.persistence import audit_project_resumability, import_project
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.data.source_pack_adoption import (
    SourcePackAdoption,
    adopt_standard_source_bundle,
    adopted_model_input_sources,
)
from ancestry_mmm.data.template_downloads import build_standard_template
from ancestry_mmm.data.templates import (
    CanonicalSourceBundle,
    canonicalize_standard_workbook,
)
from ancestry_mmm.data.loader import load_standard_workbook_with_source_version

READINESS_REPORT_SCHEMA_VERSION = 1
DEFAULT_READINESS_OUTPUT_DIR = Path("D:/Ancestry-MMM/test-artifacts/uk-readiness")
REQUIRED_SOURCE_DOMAINS = (
    DOMAIN_OUTCOMES,
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
)
SYNTHETIC_CASES = ("pass", "mixed_frequency", "coverage_gap")
READINESS_STATUSES = (
    "pass",
    "blocked",
    "decision_required",
    "unsupported",
    "failed",
)

_DOMAIN_ALIASES = {
    "outcomes": DOMAIN_OUTCOMES,
    "activity": DOMAIN_ACTIVITY_AND_MEDIA,
    "activity_and_media": DOMAIN_ACTIVITY_AND_MEDIA,
    "context": DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    "context_and_external_factors": DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    "experiments": DOMAIN_EXPERIMENT_EVIDENCE,
    "experiment_evidence": DOMAIN_EXPERIMENT_EVIDENCE,
}


class ReadinessInputError(ValueError):
    """Raised when a harness input cannot be safely evaluated."""


@dataclass(frozen=True)
class ReadinessStage:
    name: str
    status: str
    summary: str
    details: Mapping[str, object] = field(default_factory=dict)
    next_action: str = ""
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.status not in READINESS_STATUSES:
            raise ValueError(f"invalid readiness status {self.status!r}")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "details": dict(self.details),
            "next_action": self.next_action,
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass(frozen=True)
class UKReadinessReport:
    """Safe, portable readiness evidence with no source-row payloads."""

    mode: str
    generated_at: str
    stages: tuple[ReadinessStage, ...]
    report_schema_version: int = READINESS_REPORT_SCHEMA_VERSION
    report_path: str | None = None

    @property
    def status(self) -> str:
        statuses = {stage.status for stage in self.stages}
        for status in ("failed", "blocked", "unsupported", "decision_required"):
            if status in statuses:
                return status
        return "pass"

    def to_dict(self) -> dict[str, object]:
        return {
            "report_schema_version": self.report_schema_version,
            "mode": self.mode,
            "generated_at": self.generated_at,
            "status": self.status,
            "report_path": self.report_path,
            "stages": [stage.to_dict() for stage in self.stages],
        }


@dataclass(frozen=True)
class _LocalWorkbook:
    name: str
    payload: bytes

    def getvalue(self) -> bytes:
        return self.payload


def normalise_domain(value: str) -> str:
    """Resolve the explicit CLI/source-file domain label."""

    try:
        return _DOMAIN_ALIASES[value.strip().lower()]
    except KeyError as exc:
        raise ReadinessInputError(
            f"unsupported source domain {value!r}; use outcomes, activity, "
            "context, or experiments"
        ) from exc


def ensure_d_drive_path(path: str | os.PathLike[str], *, label: str) -> Path:
    """Require a configured harness output/cache path to be on D:.

    ``ntpath`` is used for the drive check so the safety contract can also be
    unit-tested on Linux CI.  The production command enables this check and
    therefore refuses relative paths and all non-D-drive paths.
    """

    raw = os.fspath(path)
    drive, _ = ntpath.splitdrive(raw)
    if drive.upper() != "D:" or not ntpath.isabs(raw):
        raise ReadinessInputError(
            f"{label} must be an absolute D-drive path; received {raw!r}"
        )
    return Path(raw)


def _safe_frame_summary(frame: pd.DataFrame | None) -> dict[str, object]:
    if frame is None:
        return {"present": False}
    summary: dict[str, object] = {
        "present": True,
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "missing_cells": int(frame.isna().sum().sum()),
    }
    for column in ("period_start", "date"):
        if column in frame.columns:
            dates = pd.to_datetime(frame[column], errors="coerce").dropna()
            if not dates.empty:
                summary["date_start"] = dates.min().strftime("%Y-%m-%d")
                summary["date_end"] = dates.max().strftime("%Y-%m-%d")
            break
    if "market" in frame.columns:
        summary["market_count"] = int(frame["market"].nunique(dropna=True))
    return summary


def _checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_workbook_tables(payload: bytes) -> dict[str, pd.DataFrame]:
    workbook = pd.ExcelFile(BytesIO(payload))
    return {
        sheet: pd.read_excel(workbook, sheet_name=sheet)
        for sheet in workbook.sheet_names
    }


def _rewrite_synthetic_workbook(payload: bytes, case: str, domain: str) -> bytes:
    if case == "pass" and domain != DOMAIN_OUTCOMES:
        return payload
    if case == "mixed_frequency" and domain != DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS:
        return payload
    tables = _write_workbook_tables(payload)
    if case == "pass" and domain == DOMAIN_OUTCOMES:
        # The standard teaching template deliberately contains an AU example
        # row. Synthetic pass mode is a complete UK fixture, so retain the
        # source-native values while assigning both generated periods to UK.
        tables["outcomes"]["market"] = "UK"
    elif case == "mixed_frequency":
        tables["context_data"]["native_frequency"] = "monthly"
        tables["variable_dictionary"]["native_frequency"] = "monthly"
    elif case == "coverage_gap" and domain == DOMAIN_ACTIVITY_AND_MEDIA:
        tables["activity_data"] = tables["activity_data"].iloc[[0]].copy()
    else:
        return payload
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet, table in tables.items():
            table.to_excel(writer, sheet_name=sheet, index=False)
    return output.getvalue()


def synthetic_source_workbooks(case: str = "pass") -> tuple[tuple[str, bytes], ...]:
    """Return generated standard workbooks for the harness test modes."""

    if case not in SYNTHETIC_CASES:
        raise ReadinessInputError(f"unsupported synthetic case {case!r}")
    domains = (
        DOMAIN_OUTCOMES,
        DOMAIN_ACTIVITY_AND_MEDIA,
        DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
        DOMAIN_EXPERIMENT_EVIDENCE,
    )
    return tuple(
        (
            domain,
            _rewrite_synthetic_workbook(build_standard_template(domain), case, domain),
        )
        for domain in domains
    )


def _stage(
    name: str,
    status: str,
    summary: str,
    started: float,
    *,
    details: Mapping[str, object] | None = None,
    next_action: str = "",
) -> ReadinessStage:
    return ReadinessStage(
        name=name,
        status=status,
        summary=summary,
        details=details or {},
        next_action=next_action,
        elapsed_seconds=round(time.perf_counter() - started, 4),
    )


def _append_not_run_stages(stages: list[ReadinessStage]) -> None:
    """Record every downstream gate that was intentionally not attempted."""

    existing = {stage.name for stage in stages}
    for name in (
        "engine_capability",
        "governance_readiness",
        "model_preparation_and_fit",
        "validation_and_approval",
        "curve_generation_eligibility",
        "scenario_planning_eligibility",
        "project_import_resumability",
    ):
        if name in existing:
            continue
        details: dict[str, object] = {}
        if name == "engine_capability":
            details = {
                "status": "not_evaluated",
                "reason": "No approved model specification was supplied at this boundary.",
            }
        elif name == "governance_readiness":
            details = {
                "outcome_registry": "not_evaluated",
                "activity_governance": "not_evaluated",
                "search_objects": "not_evaluated",
                "causal_graph": "not_evaluated",
                "headline_reporting_eligible": False,
                "planning_eligible": False,
                "optimisation_eligible": False,
            }
        stages.append(
            ReadinessStage(
                name=name,
                status="decision_required",
                summary="Not run because an earlier readiness stage blocked continuation.",
                details=details,
                next_action="Resolve the earlier blocker and rerun the harness.",
            )
        )


def _parse_and_adopt(
    inputs: Sequence[tuple[str, _LocalWorkbook]],
) -> tuple[
    SourcePackAdoption,
    tuple[CanonicalSourceBundle, ...],
    tuple[dict[str, object], ...],
    dict[str, tuple[str, int]],
]:
    adoption: SourcePackAdoption | None = None
    bundles: list[CanonicalSourceBundle] = []
    versions: dict[str, tuple[str, int]] = {}
    source_evidence: list[dict[str, object]] = []
    for index, (raw_domain, uploaded) in enumerate(inputs, start=1):
        domain = normalise_domain(raw_domain)
        source_id = f"uk-readiness-{domain}-{index}"
        workbook, version, error = load_standard_workbook_with_source_version(
            uploaded, source_id=source_id, logical_domain=domain
        )
        if error or workbook is None or version is None:
            raise ReadinessInputError(error or f"could not parse {uploaded.name!r}")
        if workbook.manifest.logical_domain != domain:
            raise ReadinessInputError(
                f"{uploaded.name!r} declares logical domain "
                f"{workbook.manifest.logical_domain!r}, expected {domain!r}"
            )
        if not workbook.manifest.valid_standard_template:
            raise ReadinessInputError(
                f"{uploaded.name!r} failed standard validation: "
                + "; ".join(workbook.manifest.errors)
            )
        bundle = canonicalize_standard_workbook(workbook)
        bundles.append(bundle)
        versions.setdefault(domain, (version.source_id, version.version))
        source_evidence.append(
            {
                "source_id": version.source_id,
                "version": version.version,
                "domain": domain,
                "filename": version.original_filename,
                "checksum": version.checksum,
                "size_bytes": version.size_bytes,
                "schema_version": version.template_schema_version,
                "table_count": len(version.parsed_table_ids),
                "warning_count": len(version.template_warnings),
            }
        )
        adoption = adopt_standard_source_bundle(
            bundle,
            activity_definitions=adoption.activity_definitions if adoption else (),
            activity_model_input=adoption.activity_model_input if adoption else None,
            outcome_data=adoption.outcome_data if adoption else None,
            context_data=adoption.context_data if adoption else None,
            context_variable_metadata=(
                adoption.context_variable_metadata if adoption else ()
            ),
            experiment_evidence=adoption.experiment_evidence if adoption else None,
            semantic_statuses=adoption.semantic_statuses if adoption else (),
        )
    if adoption is None:
        raise ReadinessInputError("no source workbooks were supplied")
    return adoption, tuple(bundles), tuple(source_evidence), versions


def _synthetic_model_spec(
    adoption: SourcePackAdoption,
    outcomes: Sequence[OutcomeDefinition],
) -> ModelSpec:
    activities = adoption.activity_definitions
    channels = sorted(
        {
            item.resolved_model_input_column
            for item in activities
            if item.market in {"UK", "*"}
        }
    )
    segment_outcomes: dict[str, str] = {}
    for outcome in outcomes:
        if outcome.product == "Family History" and outcome.metric == "GSA":
            segment_outcomes[outcome.segment] = outcome.source_column
    controls = sorted(
        str(item["variable_id"])
        for item in adoption.context_variable_metadata
        if item.get("native_frequency")
    )
    return ModelSpec(
        date_col="period_start",
        market_col="market",
        markets=["UK"],
        segment_outcomes=segment_outcomes,
        channels=channels,
        control_cols=controls,
    )


def _build_synthetic_coverage(
    frame: pd.DataFrame,
    adoption: SourcePackAdoption,
    outcomes: Sequence[OutcomeDefinition],
    spec: ModelSpec,
    versions: Mapping[str, tuple[str, int]],
) -> VariableCoverageMatrix:
    outcome_columns = [
        item.source_column for item in outcomes if item.source_column in frame.columns
    ]
    variables = tuple(
        dict.fromkeys([*outcome_columns, *spec.channels, *spec.control_cols])
    )
    frequency: dict[str, FrequencyMetadata] = {
        variable: FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class="rate_index"
            if variable in spec.control_cols
            else "flow_count",
        )
        for variable in variables
    }
    source_for: dict[str, tuple[str, int]] = {}
    for variable in outcome_columns:
        source_for[variable] = versions[DOMAIN_OUTCOMES]
    for variable in spec.channels:
        source_for[variable] = versions[DOMAIN_ACTIVITY_AND_MEDIA]
    for variable in spec.control_cols:
        source_for[variable] = versions[DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS]
    return build_coverage_matrix_from_frame(
        frame,
        date_col="period_start",
        market_col="market",
        variable_columns=variables,
        frequency_metadata=frequency,
        variable_sources=source_for,
        matrix_id="uk-readiness-synthetic-coverage",
        matrix_version=1,
        generated_at="synthetic",
    )


def _run_source_path(
    stages: list[ReadinessStage],
    inputs: Sequence[tuple[str, _LocalWorkbook]],
    *,
    governed_start: str | None,
    governed_end: str | None,
    governed_frequency: str | None,
    synthetic: bool,
) -> tuple[
    SourcePackAdoption | None,
    tuple[CanonicalSourceBundle, ...],
    dict[str, tuple[str, int]],
    bool,
]:
    started = time.perf_counter()
    try:
        adoption, bundles, evidence, versions = _parse_and_adopt(inputs)
    except Exception as exc:
        stages.append(
            _stage(
                "source_domain_schema",
                "failed",
                "Source parsing or standard-schema validation failed.",
                started,
                details={"error_type": type(exc).__name__, "error": str(exc)},
                next_action="Correct the source workbook schema and rerun the readiness check.",
            )
        )
        return None, (), {}, False
    domains: set[str] = {
        str(bundle.manifest.logical_domain)
        for bundle in bundles
        if bundle.manifest.logical_domain
    }
    missing_domains = sorted(set(REQUIRED_SOURCE_DOMAINS) - domains)
    stages.append(
        _stage(
            "source_domain_schema",
            "pass" if not missing_domains else "decision_required",
            "Source workbooks passed standard parsing and canonical adoption."
            if not missing_domains
            else "Source workbooks are valid but required logical domains are missing.",
            started,
            details={
                "source_count": len(evidence),
                "domains_present": sorted(domains),
                "missing_required_domains": missing_domains,
                "sources": list(evidence),
            },
            next_action=(
                "Supply the missing Outcomes, Activity and Media, or Context and "
                "External Factors source domain."
                if missing_domains
                else "Continue to the governed calendar and coverage checks."
            ),
        )
    )
    identity_started = time.perf_counter()
    stages.append(
        _stage(
            "source_version_identity",
            "pass",
            "Source-version identities and raw-file fingerprints were captured.",
            identity_started,
            details={
                "source_versions": [
                    {
                        "domain": item["domain"],
                        "source_id": item["source_id"],
                        "version": item["version"],
                        "checksum": item["checksum"],
                    }
                    for item in evidence
                ],
                "fingerprint_count": len(evidence),
            },
            next_action="Retain these identities with the project bundle for reproducibility.",
        )
    )
    if missing_domains:
        return adoption, bundles, versions, False

    started = time.perf_counter()
    statuses = [status.to_dict() for status in adoption.semantic_statuses]
    stages.append(
        _stage(
            "semantic_adoption",
            "pass",
            "Canonical source state was adopted with explicit downstream review states.",
            started,
            details={"domain_statuses": statuses},
            next_action="Review any mapping or approval state before official use.",
        )
    )

    started = time.perf_counter()
    try:
        frequencies = {
            str(item.get("native_frequency") or "").lower()
            for item in adoption.context_variable_metadata
            if item.get("native_frequency")
        }
        if frequencies and frequencies != {"weekly"}:
            stages.append(
                _stage(
                    "calendar_coverage_preparation",
                    "unsupported",
                    "Official preparation is blocked by an unapproved mixed-frequency source.",
                    started,
                    details={
                        "native_frequencies": sorted(frequencies),
                        "native_data_preserved": True,
                        "conversion_performed": False,
                    },
                    next_action="Obtain an approved conversion method by variable class; no conversion was applied.",
                )
            )
            return adoption, bundles, versions, False
        sources = adopted_model_input_sources(
            outcome_data=adoption.outcome_data,
            activity_model_input=adoption.activity_model_input,
            context_model_input=adoption.context_data,
            context_variable_metadata=adoption.context_variable_metadata,
        )
        if sources is None:
            raise ReadinessInputError("no adopted model-input sources are available")
        if not governed_start or not governed_end or not governed_frequency:
            stages.append(
                _stage(
                    "calendar_coverage_preparation",
                    "decision_required",
                    "Source data is native-weekly, but the governed project calendar was not supplied.",
                    started,
                    details={"native_data_preserved": True},
                    next_action="Provide the approved governed start, end, and frequency; do not infer them from source intersection.",
                )
            )
            return adoption, bundles, versions, False
        prepared = prepare_canonical_native_frame(
            sources,
            date_col="period_start",
            market_col="market",
            governed_start=governed_start,
            governed_end=governed_end,
            governed_frequency=governed_frequency,
        )
        frame = prepared.frame
        outcomes = tuple(
            item for bundle in bundles for item in bundle.outcome_definitions
        )
        if not synthetic:
            stages.append(
                _stage(
                    "calendar_coverage_preparation",
                    "pass",
                    "Official native-weekly preparation succeeded; model-specific coverage remains to be reviewed.",
                    started,
                    details={
                        "union_period_count": len(prepared.union_periods),
                        "frame": _safe_frame_summary(frame),
                        "join_diagnostics": {
                            "source_count": len(sources),
                            "join_type": "outer_union",
                        },
                    },
                    next_action="Configure the approved model, coverage matrix, outcome approvals, causal graph, and Search objects before fitting.",
                )
            )
            return adoption, bundles, versions, True

        spec = _synthetic_model_spec(adoption, outcomes)
        capability_frame = frame[frame["market"].astype(str) == "UK"].copy()
        matrix = _build_synthetic_coverage(
            capability_frame, adoption, outcomes, spec, versions
        )
        capability = build_official_capability_report(
            spec,
            outcomes,
            matrix,
            activity_definitions=adoption.activity_definitions,
        )
        engine_started = time.perf_counter()
        stages.append(
            _stage(
                "engine_capability",
                "pass" if capability.engine.supported else "decision_required",
                "The selected synthetic model shape has an explicit engine capability result.",
                engine_started,
                details=capability.engine.to_dict(),
                next_action=(
                    "Review the engine limitation before fitting."
                    if not capability.engine.supported
                    else "Keep the engine capability evidence with the model specification."
                ),
            )
        )
        assessment = assess_official_preparation(
            matrix,
            governed_start=governed_start,
            governed_end=governed_end,
            governed_frequency=governed_frequency,
            consumed_variable_ids=tuple(
                item.variable_id for item in capability.consumed_variables
            ),
            capability_evidence=capability.to_dict(),
        )
        if not assessment.ready:
            stages.append(
                _stage(
                    "calendar_coverage_preparation",
                    "decision_required"
                    if assessment.status == "decision_required"
                    else "unsupported",
                    "Synthetic preparation was blocked by the governed coverage/frequency assessor.",
                    started,
                    details=assessment.to_dict(),
                    next_action="Resolve the reported coverage or frequency decision before fitting.",
                )
            )
            return adoption, bundles, versions, False
        stages.append(
            _stage(
                "calendar_coverage_preparation",
                "pass",
                "Synthetic official native-weekly preparation and consumed-variable capability checks passed.",
                started,
                details={
                    "assessment": assessment.to_dict(),
                    "capability": capability.to_dict(),
                    "frame": _safe_frame_summary(frame),
                    "union_period_count": len(prepared.union_periods),
                },
                next_action="Continue to the deterministic synthetic governance and lifecycle evidence.",
            )
        )
        return adoption, bundles, versions, True
    except (OfficialPreparationDataError, ReadinessInputError, ValueError) as exc:
        stages.append(
            _stage(
                "calendar_coverage_preparation",
                "blocked",
                "Official preparation stopped at a governed data boundary.",
                started,
                details={"error_type": type(exc).__name__, "error": str(exc)},
                next_action="Resolve the reported official-preparation blocker; no source values were fabricated.",
            )
        )
        return adoption, bundles, versions, False


def _run_imported_bundle(stages: list[ReadinessStage], bundle_path: Path) -> None:
    started = time.perf_counter()
    try:
        imported = import_project(bundle_path)
        audit = audit_project_resumability(imported)
    except Exception as exc:
        stages.append(
            _stage(
                "project_import_resumability",
                "failed",
                "Project bundle import or resumability audit failed.",
                started,
                details={"error_type": type(exc).__name__, "error": str(exc)},
                next_action="Repair or re-export the project bundle and rerun the readiness check.",
            )
        )
        return
    manifest = imported.get("manifest") or {}
    stages.append(
        _stage(
            "source_version_identity",
            "pass" if manifest else "decision_required",
            "Project bundle manifest and source identity were imported."
            if manifest
            else "Legacy bundle imported without a manifest; source identity needs migration evidence.",
            started,
            details={
                "workflow_checkpoint": manifest.get("workflow_checkpoint"),
                "schema_version": manifest.get("schema_version"),
                "contains": manifest.get("contains", {}),
            },
            next_action="Use the bundle manifest and source fingerprints as the reproducibility record.",
        )
    )
    governance_started = time.perf_counter()
    contains = manifest.get("contains", {})
    stages.append(
        _stage(
            "governance_readiness",
            "pass",
            "Project governance contents were inspected without creating approvals.",
            governance_started,
            details={
                "outcome_registry_present": bool(
                    contains.get("outcome_approvals") or contains.get("outcome_groups")
                ),
                "activity_governance_present": bool(contains.get("source_definitions")),
                "search_objects_present": bool(contains.get("search_objects")),
                "causal_graph_present": bool(contains.get("causal_graphs")),
                "pathway_governance_present": bool(
                    contains.get("media_outcome_pathways")
                ),
                "approval_created_by_harness": False,
            },
            next_action="Verify each pathway, Search object, and graph role is explicitly approved for its intended use.",
        )
    )
    prep = imported.get("official_preparation_result")
    prep_status = str((prep or {}).get("status") or "")
    stages.append(
        _stage(
            "calendar_coverage_preparation",
            "pass" if prep_status == "ready" else "decision_required",
            "Imported official-preparation evidence is ready."
            if prep_status == "ready"
            else "Imported bundle does not contain a current ready official-preparation decision.",
            started,
            details={"official_preparation_status": prep_status or None},
            next_action="Re-evaluate the official-preparation gate in Model Setup before fitting."
            if prep_status != "ready"
            else "Continue to model and governance evidence.",
        )
    )
    checkpoint = str(manifest.get("workflow_checkpoint") or "")
    fitted = (
        imported.get("trace") is not None and imported.get("model_meta") is not None
    )
    stages.append(
        _stage(
            "model_preparation_and_fit",
            "pass" if fitted else "decision_required",
            "Fitted model evidence is present in the imported bundle."
            if fitted
            else "No fitted model evidence is present in the imported bundle.",
            started,
            details={"workflow_checkpoint": checkpoint, "fitted_evidence": fitted},
            next_action="Review model preparation and run the approved fit."
            if not fitted
            else "Review validation and approval evidence.",
        )
    )
    officially_resumable = bool(audit.get("officially_resumable"))
    stages.append(
        _stage(
            "validation_and_approval",
            "pass" if officially_resumable else "blocked",
            "Imported validation and approval evidence is eligible for official continuation."
            if officially_resumable
            else "Imported evidence is not officially resumable.",
            started,
            details={
                "resumable": bool(audit.get("resumable")),
                "officially_resumable": officially_resumable,
                "blocking_reasons": audit.get("official_blocking_reasons", []),
            },
            next_action="Resolve the audit blockers; the harness never auto-approves evidence."
            if not officially_resumable
            else "Continue to curve and scenario evidence.",
        )
    )
    has_curves = bool(
        manifest.get("contains", {}).get("official_curve_artifacts")
        or manifest.get("contains", {}).get("curve_artifact_store")
        or checkpoint in {"official_curves", "scenarios"}
    )
    stages.append(
        _stage(
            "curve_generation_eligibility",
            "pass" if has_curves and officially_resumable else "decision_required",
            "Imported official curve evidence is present."
            if has_curves and officially_resumable
            else "Curve evidence is not available for an official readiness claim.",
            started,
            details={"curve_evidence_present": has_curves},
            next_action="Run the governed curve workflow after approval."
            if not has_curves
            else "Continue to planning and resumability evidence.",
        )
    )
    has_scenarios = bool(imported.get("scenarios"))
    stages.append(
        _stage(
            "scenario_planning_eligibility",
            "pass" if has_scenarios and officially_resumable else "decision_required",
            "Imported scenario evidence is present and officially resumable."
            if has_scenarios and officially_resumable
            else "No officially resumable scenario evidence is present.",
            started,
            details={"scenario_count": len(imported.get("scenarios") or [])},
            next_action="Run an approved scenario after curve and planning governance are current."
            if not has_scenarios
            else "Verify export/re-import resumability.",
        )
    )
    stages.append(
        _stage(
            "project_import_resumability",
            "pass" if officially_resumable else "blocked",
            "Project export/import resumability audit passed."
            if officially_resumable
            else "Project import completed but official resumability is blocked.",
            started,
            details={
                "resumable": bool(audit.get("resumable")),
                "officially_resumable": officially_resumable,
                "missing_required": audit.get("missing_required", []),
            },
            next_action="Resolve the listed resumability blockers before relying on this bundle."
            if not officially_resumable
            else "The imported bundle can resume its declared official checkpoint.",
        )
    )


def _run_synthetic_downstream(
    stages: list[ReadinessStage],
    output_dir: Path,
    lifecycle_bundle_builder: Callable[[Path], Path],
) -> None:
    started = time.perf_counter()
    bundle_path = output_dir / "synthetic-lifecycle-bundle.zip"
    try:
        built_path = lifecycle_bundle_builder(bundle_path)
        imported = import_project(built_path)
        audit = audit_project_resumability(imported)
    except Exception as exc:
        stages.append(
            _stage(
                "synthetic_deterministic_lifecycle",
                "failed",
                "The deterministic synthetic lifecycle fixture failed.",
                started,
                details={"error_type": type(exc).__name__, "error": str(exc)},
                next_action="Repair the existing deterministic lifecycle fixture before claiming synthetic readiness.",
            )
        )
        return
    manifest = imported.get("manifest") or {}
    contains = manifest.get("contains") or {}
    governance_started = time.perf_counter()
    stages.append(
        _stage(
            "governance_readiness",
            "pass",
            "Synthetic governance evidence was inspected without creating new approvals.",
            governance_started,
            details={
                "outcome_registry_present": bool(imported.get("outcome_definitions")),
                "activity_governance_present": bool(
                    imported.get("activity_definitions")
                ),
                "search_objects_present": bool(
                    imported.get("search_objects") or contains.get("search_objects")
                ),
                "pathway_governance_present": bool(
                    imported.get("media_outcome_pathways")
                    or contains.get("media_outcome_pathways")
                ),
                "approval_created_by_harness": False,
                "synthetic_only": True,
            },
            next_action="Treat this as deterministic lifecycle evidence only; real UK governance remains an analyst decision.",
        )
    )
    fitted = (
        imported.get("trace") is not None and imported.get("model_meta") is not None
    )
    fit_started = time.perf_counter()
    stages.append(
        _stage(
            "model_preparation_and_fit",
            "pass" if fitted else "decision_required",
            "Deterministic fitted-model evidence is present."
            if fitted
            else "The synthetic bundle has no fitted-model evidence.",
            fit_started,
            details={"fitted_evidence": fitted, "live_sampling": False},
            next_action="Review the model evidence; no sampling was started by the harness.",
        )
    )
    validation_started = time.perf_counter()
    officially_resumable = bool(audit.get("officially_resumable"))
    stages.append(
        _stage(
            "validation_and_approval",
            "pass" if officially_resumable else "blocked",
            "Deterministic validation and approval evidence is resumable."
            if officially_resumable
            else "Synthetic validation and approval evidence is not resumable.",
            validation_started,
            details={
                "officially_resumable": officially_resumable,
                "approval_created_by_harness": False,
                "official_blocking_reasons": audit.get("official_blocking_reasons", []),
            },
            next_action="Resolve audit blockers; the harness never auto-approves evidence."
            if not officially_resumable
            else "Review the deterministic approval evidence.",
        )
    )
    has_curves = bool(
        contains.get("official_curve_artifacts")
        or contains.get("curve_artifact_store")
        or manifest.get("workflow_checkpoint") in {"official_curves", "scenarios"}
    )
    curve_started = time.perf_counter()
    stages.append(
        _stage(
            "curve_generation_eligibility",
            "pass" if has_curves and officially_resumable else "decision_required",
            "Deterministic official curve artifacts are present."
            if has_curves and officially_resumable
            else "Official curve artifacts are not available for this synthetic bundle.",
            curve_started,
            details={"curve_evidence_present": has_curves},
            next_action="Use the governed curve workflow for real UK evidence."
            if not has_curves
            else "Review curve identity and approval dependencies.",
        )
    )
    scenario_started = time.perf_counter()
    scenario_count = len(imported.get("scenarios") or [])
    stages.append(
        _stage(
            "scenario_planning_eligibility",
            "pass" if scenario_count and officially_resumable else "decision_required",
            "A deterministic saved scenario is present and resumable."
            if scenario_count and officially_resumable
            else "No officially resumable synthetic scenario is present.",
            scenario_started,
            details={"scenario_count": scenario_count},
            next_action="Use the governed planning workflow for real UK scenarios."
            if not scenario_count
            else "Review scenario identity and planning eligibility.",
        )
    )
    resume_started = time.perf_counter()
    stages.append(
        _stage(
            "project_import_resumability",
            "pass" if officially_resumable else "blocked",
            "Synthetic project export, import, and resumability audit passed."
            if officially_resumable
            else "Synthetic project import completed but resumability is blocked.",
            resume_started,
            details={
                "resumable": bool(audit.get("resumable")),
                "officially_resumable": officially_resumable,
                "missing_required": audit.get("missing_required", []),
            },
            next_action="Use the bundle as synthetic evidence only; an authorised analyst must run real UK inputs locally."
            if officially_resumable
            else "Repair the deterministic lifecycle fixture.",
        )
    )
    stages.append(
        _stage(
            "synthetic_deterministic_lifecycle",
            "pass" if audit.get("officially_resumable") else "blocked",
            "The existing deterministic fitted lifecycle exercised model, approval, curve, scenario, and bundle stages."
            if audit.get("officially_resumable")
            else "The deterministic lifecycle bundle loaded but did not pass official resumability.",
            started,
            details={
                "bundle_filename": built_path.name,
                "workflow_checkpoint": (imported.get("manifest") or {}).get(
                    "workflow_checkpoint"
                ),
                "officially_resumable": bool(audit.get("officially_resumable")),
                "missing_required": audit.get("missing_required", []),
                "official_blocking_reasons": audit.get("official_blocking_reasons", []),
                "live_sampling": False,
            },
            next_action="Use the report as synthetic evidence only; an authorised analyst must run real UK inputs locally."
            if audit.get("officially_resumable")
            else "Repair the deterministic lifecycle fixture.",
        )
    )


def run_uk_readiness(
    *,
    source_paths: Sequence[tuple[str, Path]] = (),
    bundle_path: Path | None = None,
    synthetic_case: str | None = None,
    output_dir: str | os.PathLike[str] = DEFAULT_READINESS_OUTPUT_DIR,
    governed_start: str | None = None,
    governed_end: str | None = None,
    governed_frequency: str | None = None,
    enforce_d_drive: bool = True,
    lifecycle_bundle_builder: Callable[[Path], Path] | None = None,
) -> UKReadinessReport:
    """Run a bounded, metadata-only readiness check.

    ``source_paths`` accepts any number of ``(logical_domain, path)`` pairs.
    ``bundle_path`` is an alternative for a previously exported project.  A
    synthetic case uses generated standard templates and may inject the
    repository's deterministic lifecycle fixture for downstream evidence.
    """

    if bundle_path is not None and (source_paths or synthetic_case is not None):
        raise ReadinessInputError("choose bundle, source files, or synthetic mode")
    if synthetic_case is not None and synthetic_case not in SYNTHETIC_CASES:
        raise ReadinessInputError(f"unsupported synthetic case {synthetic_case!r}")
    output = (
        ensure_d_drive_path(output_dir, label="readiness output directory")
        if enforce_d_drive
        else Path(output_dir)
    )
    output.mkdir(parents=True, exist_ok=True)
    stages: list[ReadinessStage] = []
    mode = "bundle" if bundle_path is not None else "sources"
    if synthetic_case is not None:
        mode = f"synthetic:{synthetic_case}"
        inputs = tuple(
            (
                domain,
                _LocalWorkbook(f"synthetic-{domain}.xlsx", payload),
            )
            for domain, payload in synthetic_source_workbooks(synthetic_case)
        )
        if governed_start is None:
            governed_start = "2026-01-05"
        if governed_end is None:
            governed_end = "2026-01-12"
        if governed_frequency is None:
            governed_frequency = "weekly"
    elif source_paths:
        inputs = tuple(
            (
                domain,
                _LocalWorkbook(path.name, path.read_bytes()),
            )
            for domain, path in source_paths
        )
    else:
        inputs = ()

    if bundle_path is not None:
        _run_imported_bundle(stages, bundle_path)
    elif inputs:
        adoption, bundles, versions, preparation_ready = _run_source_path(
            stages,
            inputs,
            governed_start=governed_start,
            governed_end=governed_end,
            governed_frequency=governed_frequency,
            synthetic=synthetic_case is not None,
        )
        if synthetic_case is not None and preparation_ready:
            if lifecycle_bundle_builder is None:
                _append_not_run_stages(stages)
                stages.append(
                    ReadinessStage(
                        name="synthetic_deterministic_lifecycle",
                        status="failed",
                        summary="Synthetic downstream lifecycle builder was not supplied.",
                        next_action="Provide the repository deterministic lifecycle fixture builder.",
                    )
                )
            else:
                _run_synthetic_downstream(stages, output, lifecycle_bundle_builder)
        else:
            # Real source inputs stop after native preparation.  They must
            # never be reported as a fitted or approved official lifecycle.
            _append_not_run_stages(stages)
    else:
        stages.append(
            ReadinessStage(
                name="input_selection",
                status="failed",
                summary="No source files, project bundle, or synthetic mode was supplied.",
                next_action="Provide --source domain=PATH, --bundle PATH, or --synthetic.",
            )
        )

    report = UKReadinessReport(
        mode=mode,
        generated_at=datetime.now(timezone.utc).isoformat(),
        stages=tuple(stages),
    )
    report_path = output / "uk-readiness-report.json"
    payload = report.to_dict()
    payload["report_path"] = str(report_path)
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return UKReadinessReport(
        mode=report.mode,
        generated_at=report.generated_at,
        stages=report.stages,
        report_schema_version=report.report_schema_version,
        report_path=str(report_path),
    )


__all__ = [
    "DEFAULT_READINESS_OUTPUT_DIR",
    "READINESS_REPORT_SCHEMA_VERSION",
    "ReadinessInputError",
    "ReadinessStage",
    "UKReadinessReport",
    "ensure_d_drive_path",
    "normalise_domain",
    "run_uk_readiness",
    "synthetic_source_workbooks",
]
