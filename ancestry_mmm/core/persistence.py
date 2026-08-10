"""
Project export/import: a downloadable, re-importable project bundle so an
analyst can pause and resume work without a live server session.

Bundle layout (a single zip):
    data/raw_<source>.parquet          - each raw source, as uploaded
    data/transformed.parquet           - post-pipeline data
    config/pipeline_steps.json         - ordered transform steps
    config/model_spec.json             - ModelSpec
    config/prior_config.json           - prior overrides + dna_lag_weeks
    config/model_run_id.json           - the fitted model's run ID, if trained
    config/model_meta.json             - FHModelMeta, if trained (lets a re-import
                                          reconstruct the modelling frame and posterior
                                          parameters without a full re-fit)
    config/model_approval.json         - ModelApproval, if the trained model has been approved
    config/market_spec_config.json     - MarketSpecConfig (market descriptors, currency,
                                          media-unit mappings), if any is set
    config/media_input_specs.json      - explicit model-input identity/unit metadata
    config/media_cost_mappings.json    - governed market/channel/context cost mappings
    config/model_type.json             - which model builder was fit: "shared" (Model A,
                                          core.hierarchical_model - the default/legacy value
                                          when this file is absent) or "market_specific"
                                          (Model C, core.market_specific_model)
    config/scenarios.json              - scenario definitions (spend plan, constraints)
    config/counterfactual_policy.json  - PR 125A: project-level CounterfactualPolicy
                                          (core.scenario_governance), if one was in
                                          effect when the project was exported. Every
                                          official scenario's saved
                                          governance_dependencies.counterfactual_policy_
                                          fingerprint is verified against THIS file on
                                          import, not against itself - a bundle
                                          exported before this field existed carries no
                                          project-level policy, so any of its official
                                          scenarios with a saved counterfactual
                                          fingerprint remain unverifiable (fails closed,
                                          never silently promoted to official).
    config/currency_context.json       - PR 125A: project-level CurrencyContext
                                          (core.planning.value), if a value/reporting
                                          currency was in effect when the project was
                                          exported. Bundles a single-market project's
                                          reporting currency, value currency, and any
                                          historical/future FX rate-set identity
                                          together - verified the same way as
                                          counterfactual_policy above. A project with
                                          official scenarios spanning more than one
                                          currency context is not yet supported by this
                                          single project-level file (out of scope here -
                                          see PR 125A's dependency inventory).
    config/value_mapping.json          - PR 125A: project-level OutcomeValueMapping
                                          (core.planning.value), if an expected-value
                                          objective's value mapping was resolved when
                                          the project was exported - verified the same
                                          way as counterfactual_policy/currency_context
                                          above, required by any official scenario whose
                                          planning_objective.estimand is
                                          "incremental_value".
    config/causal_graphs.json          - REQ-GRAPH-001: every `CausalGraph` version
                                          worth keeping (core.causal_graph.
                                          graph_versions_for_export), if any have
                                          been saved or are currently in progress.
                                          Absent for every bundle exported before
                                          this capability existed, and for any
                                          current project with no graph configured
                                          yet - "no graph yet" is a valid,
                                          not-an-error reading (see
                                          resolve_imported_causal_graphs below).
                                          audit_project_resumability fails closed
                                          when a fitted model's bound
                                          causal_graph_structural_fingerprint
                                          (core.hierarchical_model.FHModelMeta) has
                                          no matching record here.
    config/search_objects.json         - REQ-SEARCH-001: every governed
                                          `SearchObjectDefinition` (branded-search
                                          demand, Paid Search spend/delivery/cap,
                                          organic-search capture, direct-navigation
                                          capture - core.search_objects). Absent
                                          for every bundle exported before this
                                          capability existed, and for any current
                                          project with no Search objects governed
                                          yet - "none governed yet" is a valid,
                                          not-an-error reading (see
                                          resolve_imported_search_objects below).
    config/variable_coverage_matrices.json - REQ-COVERAGE-001 S1: every
                                          `VariableCoverageMatrix` version worth
                                          keeping (core.coverage.
                                          variable_coverage_matrix_versions_for_export),
                                          if any have been built or are currently
                                          in progress. Absent for every bundle
                                          exported before this capability existed,
                                          and for any current project with no
                                          coverage matrix built yet - "none built
                                          yet" is a valid, not-an-error reading
                                          (see resolve_imported_variable_coverage_
                                          matrices below).
    scenarios/scenario_<i>_predicted.csv
    model/trace.nc                     - fitted posterior (ArviZ InferenceData, NetCDF)
    curve_bank/*.json                  - curve bank + calibration records, if any

Session state (Streamlit) is never the system of record - this bundle is.
No proprietary format: Parquet, JSON and NetCDF are all open, and readable
without this app (pandas.read_parquet, json, arviz.from_netcdf).

reconstruct_model_state() and verify_imported_approval() below turn a raw
import_project() result into re-derived model artefacts (frame, posterior
params) and a verified-or-rejected approval, without requiring a full
re-fit - see their docstrings.
"""

from __future__ import annotations

import gc
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import arviz as az

from .approval import (
    ApprovalMismatchError,
    ModelApproval,
    ValidationPolicyBlockedError,
    fingerprint_model_approval,
    require_matching_approval,
)

if TYPE_CHECKING:
    from .validation_policy import ApprovalReadiness, ThresholdPolicy
from .activities import ActivityDefinition, activity_fit_fingerprint
from .fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from .curve_artifact import (
    CurveArtifact,
    CurveArtifactStoreError,
    load_curve_artifact_store,
    validate_portable_path_component,
)
from .hierarchical_model import FHModelMeta
from .outcomes import outcome_catalogue_fingerprint_payload
from .pathways import pathway_catalogue_fingerprint_payload
from .planning.value import CurrencyContext, OutcomeValueMapping
from .predict import extract_posterior_params
from .scenario_governance import CounterfactualPolicy
from .schema import ModelSpec
from .optimization import SpendConstraint

# REQ-GRAPH-001: bumped 11 -> 12 for the project-level causal_graphs bundle
# file (see export_project()'s docstring). REQ-SEARCH-001: bumped 12 -> 13
# for the project-level search_objects bundle file. REQ-COVERAGE-001: bumped
# 13 -> 14 for the project-level variable_coverage_matrices bundle file.
PROJECT_BUNDLE_SCHEMA_VERSION = 14
PROJECT_APP_VERSION = "0.1.0"


class UnsafeZipEntryError(ValueError):
    """A project bundle zip contained an entry that would extract outside the target directory."""


def _is_safe_zip_member(name: str) -> bool:
    """
    True if a zip entry's raw member name is a plain relative path: no
    absolute-path prefix (POSIX '/' or a Windows drive/UNC form) and no '..'
    path segment - the two shapes a "zip slip" path-traversal payload needs.

    Checked independently of zipfile's own internal member-name sanitisation
    (CPython's `ZipFile._extract_member` already strips '..'/leading '/'
    before writing), because that's interpreter/version behaviour we don't
    want this security property to depend on silently - see
    ancestry_mmm/tests/test_persistence.py for the payloads this rejects.
    """
    if not name or name.startswith("/") or name.startswith("\\"):
        return False
    if len(name) >= 2 and name[1] == ":":  # e.g. "C:\\evil" or "C:evil"
        return False
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    return ".." not in parts


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    """
    Extract every member of `zf` into `dest`, raising UnsafeZipEntryError
    (aborting the whole import - no partial extraction) if any entry's name
    is an absolute/`..`-containing path, or its resolved on-disk target
    would land outside `dest`. `zipfile.ZipFile.extractall` performs no such
    check on its own callers should rely on.
    """
    dest = Path(dest).resolve()
    for member in zf.infolist():
        if not _is_safe_zip_member(member.filename):
            raise UnsafeZipEntryError(
                f"Refusing to import: zip entry '{member.filename}' is an absolute path "
                "or contains a '..' path segment."
            )
        target = (dest / member.filename).resolve()
        if target != dest and dest not in target.parents:
            raise UnsafeZipEntryError(
                f"Refusing to import: zip entry '{member.filename}' resolves outside the "
                "target directory."
            )
    zf.extractall(dest)


def export_project(
    output_path: Path,
    raw_sources: Dict[str, pd.DataFrame],
    transformed_data: Optional[pd.DataFrame],
    pipeline_steps: List[dict],
    model_spec: Optional[dict],
    prior_config: Optional[dict],
    dna_lag_weeks: int,
    trace: Optional[az.InferenceData],
    scenarios: List[dict],
    curve_bank_source_dir: Optional[Path] = None,
    curve_artifact_store_source_dir: Optional[Path] = None,
    model_approval: Optional[dict] = None,
    model_run_id: Optional[str] = None,
    model_meta: Optional[FHModelMeta] = None,
    market_spec_config: Optional[dict] = None,
    model_type: Optional[str] = None,
    outcome_definitions: Optional[List[dict]] = None,
    funnel_links: Optional[List[dict]] = None,
    media_outcome_pathways: Optional[List[dict]] = None,
    net_billthrough_metadata: Optional[dict] = None,
    workflow_state: Optional[dict] = None,
    diagnostics: Optional[dict] = None,
    notes: Optional[str] = None,
    calibration_records: Optional[List[dict]] = None,
    model_comparison_candidates: Optional[List[dict]] = None,
    migration_review: Optional[dict] = None,
    media_input_specs: Optional[List[dict]] = None,
    media_cost_mappings: Optional[dict] = None,
    media_input_support: Optional[List[dict]] = None,
    monetary_spend_support: Optional[List[dict]] = None,
    activity_definitions: Optional[List[dict]] = None,
    outcome_approvals: Optional[List[dict]] = None,
    validation_policy: Optional[dict] = None,
    diagnostics_artefact: Optional[dict] = None,
    validation_results: Optional[List[dict]] = None,
    approval_readiness: Optional[dict] = None,
    counterfactual_policy: Optional[dict] = None,
    currency_context: Optional[dict] = None,
    value_mapping: Optional[dict] = None,
    causal_graphs: Optional[List[dict]] = None,
    search_objects: Optional[List[dict]] = None,
    source_versions: Optional[List[dict]] = None,
    variable_coverage_matrices: Optional[List[dict]] = None,
) -> Path:
    output_path = Path(output_path)
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        (tmp / "data").mkdir()
        (tmp / "config").mkdir()
        (tmp / "scenarios").mkdir()
        (tmp / "diagnostics").mkdir()

        for name, df in raw_sources.items():
            df.to_parquet(tmp / "data" / f"raw_{name}.parquet", index=False)
        if transformed_data is not None:
            transformed_data.to_parquet(
                tmp / "data" / "transformed.parquet", index=False
            )

        (tmp / "config" / "pipeline_steps.json").write_text(
            json.dumps(pipeline_steps, indent=2)
        )
        if model_spec is not None:
            (tmp / "config" / "model_spec.json").write_text(
                json.dumps(model_spec, indent=2, default=str)
            )
        (tmp / "config" / "prior_config.json").write_text(
            json.dumps(
                {"prior_config": prior_config or {}, "dna_lag_weeks": dna_lag_weeks},
                indent=2,
            )
        )
        if model_approval is not None:
            (tmp / "config" / "model_approval.json").write_text(
                json.dumps(model_approval, indent=2, default=str)
            )
        if model_run_id is not None:
            (tmp / "config" / "model_run_id.json").write_text(
                json.dumps({"model_run_id": model_run_id}, indent=2)
            )
        if model_meta is not None:
            (tmp / "config" / "model_meta.json").write_text(
                json.dumps(asdict(model_meta), indent=2, default=str)
            )
        if market_spec_config is not None:
            (tmp / "config" / "market_spec_config.json").write_text(
                json.dumps(market_spec_config, indent=2, default=str)
            )
        if media_input_specs is not None:
            (tmp / "config" / "media_input_specs.json").write_text(
                json.dumps(media_input_specs, indent=2, default=str)
            )
        if media_cost_mappings is not None:
            (tmp / "config" / "media_cost_mappings.json").write_text(
                json.dumps(media_cost_mappings, indent=2, default=str)
            )
        if media_input_support is not None:
            (tmp / "config" / "media_input_support.json").write_text(
                json.dumps(media_input_support, indent=2, default=str)
            )
        if monetary_spend_support is not None:
            (tmp / "config" / "monetary_spend_support.json").write_text(
                json.dumps(monetary_spend_support, indent=2, default=str)
            )
        if activity_definitions is not None:
            (tmp / "config" / "activity_definitions.json").write_text(
                json.dumps(activity_definitions, indent=2, default=str)
            )
        if model_type is not None:
            (tmp / "config" / "model_type.json").write_text(
                json.dumps({"model_type": model_type}, indent=2)
            )
        if outcome_definitions is not None:
            (tmp / "config" / "outcome_definitions.json").write_text(
                json.dumps(outcome_definitions, indent=2, default=str)
            )
        if funnel_links is not None:
            (tmp / "config" / "funnel_links.json").write_text(
                json.dumps(funnel_links, indent=2, default=str)
            )
        if media_outcome_pathways is not None:
            (tmp / "config" / "media_outcome_pathways.json").write_text(
                json.dumps(media_outcome_pathways, indent=2, default=str)
            )
        if net_billthrough_metadata is not None:
            (tmp / "config" / "net_billthrough_metadata.json").write_text(
                json.dumps(net_billthrough_metadata, indent=2, default=str)
            )
        if workflow_state is not None:
            (tmp / "config" / "workflow_state.json").write_text(
                json.dumps(workflow_state, indent=2, default=str)
            )
        if calibration_records is not None:
            (tmp / "config" / "calibration_records.json").write_text(
                json.dumps(calibration_records, indent=2, default=str)
            )
        if model_comparison_candidates is not None:
            (tmp / "config" / "model_comparison_candidates.json").write_text(
                json.dumps(model_comparison_candidates, indent=2, default=str)
            )
        if migration_review is not None:
            (tmp / "config" / "migration_review.json").write_text(
                json.dumps(migration_review, indent=2, default=str)
            )
        if outcome_approvals is not None:
            (tmp / "config" / "outcome_approvals.json").write_text(
                json.dumps(outcome_approvals, indent=2, default=str)
            )
        # PR 72E: Persist governance evidence chain
        if validation_policy is not None:
            (tmp / "config" / "validation_policy.json").write_text(
                json.dumps(validation_policy, indent=2, default=str)
            )
        if diagnostics_artefact is not None:
            (tmp / "config" / "diagnostics_artefact.json").write_text(
                json.dumps(diagnostics_artefact, indent=2, default=str)
            )
        if validation_results is not None:
            (tmp / "config" / "validation_results.json").write_text(
                json.dumps(validation_results, indent=2, default=str)
            )
        if approval_readiness is not None:
            (tmp / "config" / "approval_readiness.json").write_text(
                json.dumps(approval_readiness, indent=2, default=str)
            )
        # PR 125A: project-level planning dependencies that every official
        # scenario's saved governance_dependencies fingerprint must be
        # verifiable against on import - see the module docstring.
        if counterfactual_policy is not None:
            (tmp / "config" / "counterfactual_policy.json").write_text(
                json.dumps(counterfactual_policy, indent=2, default=str)
            )
        if currency_context is not None:
            (tmp / "config" / "currency_context.json").write_text(
                json.dumps(currency_context, indent=2, default=str)
            )
        if value_mapping is not None:
            (tmp / "config" / "value_mapping.json").write_text(
                json.dumps(value_mapping, indent=2, default=str)
            )
        # REQ-GRAPH-001: all CausalGraph versions worth keeping - see the
        # module docstring.
        if causal_graphs is not None:
            (tmp / "config" / "causal_graphs.json").write_text(
                json.dumps(causal_graphs, indent=2, default=str)
            )
        # REQ-SEARCH-001: governed Search object definitions (search_demand,
        # paid_search_spend/delivery/cap, organic_search_capture,
        # direct_navigation_capture) - see resolve_imported_search_objects.
        if search_objects is not None:
            (tmp / "config" / "search_objects.json").write_text(
                json.dumps(search_objects, indent=2, default=str)
            )
        # REQ-COVERAGE-001 S3: append-only immutable SourceVersion history
        # (core.coverage.SourceVersion.to_dict() dicts) - never pruned on
        # export; a bundle preserves every recorded upload's provenance so
        # a re-uploaded source resumes version numbering correctly rather
        # than colliding with a prior version's checksum identity (P1
        # review finding on an earlier version of this capability).
        if source_versions is not None:
            (tmp / "config" / "source_versions.json").write_text(
                json.dumps(source_versions, indent=2, default=str)
            )
        # REQ-COVERAGE-001 S1: every VariableCoverageMatrix version worth
        # keeping (core.coverage.variable_coverage_matrix_versions_for_export),
        # mirroring causal_graphs above.
        if variable_coverage_matrices is not None:
            (tmp / "config" / "variable_coverage_matrices.json").write_text(
                json.dumps(variable_coverage_matrices, indent=2, default=str)
            )
        if diagnostics is not None:
            for name, value in diagnostics.items():
                if value is None:
                    continue
                if isinstance(value, pd.DataFrame):
                    value.to_parquet(tmp / "diagnostics" / f"{name}.parquet")
                else:
                    (tmp / "diagnostics" / f"{name}.json").write_text(
                        json.dumps(value, indent=2, default=str)
                    )
        if notes:
            (tmp / "notes.md").write_text(notes)

        scenarios_meta = []
        for i, s in enumerate(scenarios):
            meta = {k: v for k, v in s.items() if k != "predicted"}
            if "constraints" in meta:
                meta["constraints"] = [
                    c.to_dict() if isinstance(c, SpendConstraint) else c
                    for c in meta["constraints"]
                ]
            scenarios_meta.append(meta)
            if "predicted" in s and isinstance(s["predicted"], pd.DataFrame):
                s["predicted"].to_csv(
                    tmp / "scenarios" / f"scenario_{i}_predicted.csv", index=False
                )
        (tmp / "config" / "scenarios.json").write_text(
            json.dumps(scenarios_meta, indent=2, default=str)
        )

        if trace is not None:
            (tmp / "model").mkdir()
            trace.to_netcdf(str(tmp / "model" / "trace.nc"))

        if curve_bank_source_dir is not None and Path(curve_bank_source_dir).exists():
            shutil.copytree(curve_bank_source_dir, tmp / "curve_bank")

        if (
            curve_artifact_store_source_dir is not None
            and Path(curve_artifact_store_source_dir).exists()
        ):
            shutil.copytree(curve_artifact_store_source_dir, tmp / "curve_artifacts")

        manifest = {
            "schema_version": PROJECT_BUNDLE_SCHEMA_VERSION,
            "app_version": PROJECT_APP_VERSION,
            "workflow_checkpoint": (workflow_state or {}).get("checkpoint", "unknown"),
            "contains": {
                "raw_data": bool(raw_sources),
                "transformed_data": transformed_data is not None,
                "model_spec": model_spec is not None,
                "posterior": trace is not None,
                "diagnostics": bool(diagnostics),
                "curves": (tmp / "curve_bank").exists(),
                "official_curve_artifacts": (tmp / "curve_artifacts").exists(),
                "approval": model_approval is not None,
                "outcome_approvals": outcome_approvals is not None
                and bool(outcome_approvals),
                "scenarios": bool(scenarios),
                "notes": bool(notes),
                "validation_policy": validation_policy is not None,
                "diagnostics_artefact": diagnostics_artefact is not None,
                "validation_results": validation_results is not None,
                "approval_readiness": approval_readiness is not None,
                "counterfactual_policy": counterfactual_policy is not None,
                "currency_context": currency_context is not None,
                "value_mapping": value_mapping is not None,
                "causal_graphs": causal_graphs is not None and bool(causal_graphs),
                "search_objects": search_objects is not None and bool(search_objects),
                "source_versions": source_versions is not None
                and bool(source_versions),
                "variable_coverage_matrices": variable_coverage_matrices is not None
                and bool(variable_coverage_matrices),
            },
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

        if output_path.exists():
            output_path.unlink()
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in tmp.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(tmp))

    return output_path


def import_project(zip_path: Path) -> Dict[str, Any]:
    zip_path = Path(zip_path)
    result: Dict[str, Any] = {
        "raw_sources": {},
        "transformed_data": None,
        "pipeline_steps": [],
        "model_spec": None,
        "prior_config": {},
        "dna_lag_weeks": 4,
        "trace": None,
        "scenarios": [],
        "model_approval": None,
        "model_run_id": None,
        "model_meta": None,
        # Absent in bundles exported before the market-specific redesign
        # (Phase 1) - None here is the correct "legacy bundle" signal, not
        # an error; core.market_config.MarketSpecConfig.from_dict(None)
        # returns an empty config.
        "market_spec_config": None,
        # G2A.2 metadata is optional so older bundles remain resumable.
        "media_input_specs": [],
        "media_cost_mappings": None,
        "media_input_support": [],
        "monetary_spend_support": [],
        "activity_definitions": [],
        # Absent in bundles exported before the market-specific redesign's
        # Phase 2 - "shared" (Model A) is the correct default: every bundle
        # exported before Model C existed was necessarily a Model A fit.
        "model_type": "shared",
        # Absent in bundles exported before the outcome-schema work (PR2) -
        # None here is the correct "legacy bundle" signal, not an error;
        # core.outcomes.resolve_outcome_definitions(None, ...) derives an
        # equivalent FH-only outcome set from the imported model_spec.
        "outcome_definitions": None,
        # Absent in bundles exported before PR E.2 - None (not an error);
        # "no funnel links configured" is the correct legacy/default reading,
        # not "funnel diagnostics are unavailable" (they still work with an
        # empty list, just show no configured pairs).
        "funnel_links": None,
        # Absent in bundles exported before PR F - None (not an error); "no
        # pathway catalogue configured" is the correct legacy/default
        # reading, matching funnel_links' convention above.
        "media_outcome_pathways": None,
        "net_billthrough_metadata": None,
        "manifest": None,
        "workflow_state": None,
        "diagnostics": {},
        "notes": None,
        "calibration_records": [],
        "model_comparison_candidates": [],
        "migration_review": None,
        "curve_bank_binary_files": {},
        # PR 96B: official curve artifact store subtree - text (metadata
        # JSON) and binary (draws/summaries Parquet) files, keyed by path
        # relative to the store root (mirrors curve_bank_files/
        # curve_bank_binary_files above). Empty for bundles exported before
        # this PR or with no official artifacts yet - not an error.
        "curve_artifact_files": {},
        "curve_artifact_binary_files": {},
        # G2A.7 (REQ-OUT-002): outcome approvals - None for legacy bundles
        # (no approvals on file). Imported bundles without this file get
        # legacy_unapproved status for every outcome, never implicit approval.
        "outcome_approvals": None,
        # PR 72E: Governance evidence chain - None for legacy bundles
        # (no governance on file).
        "validation_policy": None,
        "diagnostics_artefact": None,
        "validation_results": None,
        "approval_readiness": None,
        # PR 125A: project-level planning dependencies - None for bundles
        # exported before this field existed (a legacy bundle, not an
        # error). audit_project_resumability() fails closed for any
        # official scenario that depended on one of these but finds it
        # absent here - it never fabricates legacy evidence.
        "counterfactual_policy": None,
        "currency_context": None,
        "value_mapping": None,
        # REQ-GRAPH-001: None for bundles exported before this capability
        # existed - "no graph yet" is a valid, not-an-error reading, same
        # convention as funnel_links/media_outcome_pathways above.
        "causal_graphs": None,
        # REQ-SEARCH-001: None for bundles exported before this capability
        # existed - "no Search objects governed yet" is a valid,
        # not-an-error reading, same convention as causal_graphs above.
        "search_objects": None,
        # REQ-COVERAGE-001 S3: None for bundles exported before this
        # capability existed - "no source-version history recorded yet" is
        # a valid, not-an-error reading, same convention as causal_graphs/
        # search_objects above.
        "source_versions": None,
        # REQ-COVERAGE-001 S1: None for bundles exported before this
        # capability existed - "no coverage matrix built yet" is a valid,
        # not-an-error reading, same convention as causal_graphs/
        # search_objects/source_versions above.
        "variable_coverage_matrices": None,
    }
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract_zip(zf, tmp)

        if (tmp / "manifest.json").exists():
            result["manifest"] = json.loads((tmp / "manifest.json").read_text())

        data_dir = tmp / "data"
        if data_dir.exists():
            for f in data_dir.glob("raw_*.parquet"):
                name = f.stem[len("raw_") :]
                result["raw_sources"][name] = pd.read_parquet(f)
            transformed_path = data_dir / "transformed.parquet"
            if transformed_path.exists():
                result["transformed_data"] = pd.read_parquet(transformed_path)

        config_dir = tmp / "config"
        if (config_dir / "pipeline_steps.json").exists():
            result["pipeline_steps"] = json.loads(
                (config_dir / "pipeline_steps.json").read_text()
            )
        if (config_dir / "model_spec.json").exists():
            result["model_spec"] = json.loads(
                (config_dir / "model_spec.json").read_text()
            )
        if (config_dir / "prior_config.json").exists():
            prior_data = json.loads((config_dir / "prior_config.json").read_text())
            result["prior_config"] = prior_data.get("prior_config", {})
            result["dna_lag_weeks"] = prior_data.get("dna_lag_weeks", 4)
        if (config_dir / "model_approval.json").exists():
            result["model_approval"] = json.loads(
                (config_dir / "model_approval.json").read_text()
            )
        if (config_dir / "model_run_id.json").exists():
            result["model_run_id"] = json.loads(
                (config_dir / "model_run_id.json").read_text()
            ).get("model_run_id")
        if (config_dir / "model_meta.json").exists():
            result["model_meta"] = json.loads(
                (config_dir / "model_meta.json").read_text()
            )
        if (config_dir / "market_spec_config.json").exists():
            result["market_spec_config"] = json.loads(
                (config_dir / "market_spec_config.json").read_text()
            )
        if (config_dir / "media_input_specs.json").exists():
            result["media_input_specs"] = json.loads(
                (config_dir / "media_input_specs.json").read_text()
            )
        if (config_dir / "media_cost_mappings.json").exists():
            result["media_cost_mappings"] = json.loads(
                (config_dir / "media_cost_mappings.json").read_text()
            )
        if (config_dir / "media_input_support.json").exists():
            result["media_input_support"] = json.loads(
                (config_dir / "media_input_support.json").read_text()
            )
        if (config_dir / "monetary_spend_support.json").exists():
            result["monetary_spend_support"] = json.loads(
                (config_dir / "monetary_spend_support.json").read_text()
            )
        if (config_dir / "activity_definitions.json").exists():
            activity_payload = json.loads(
                (config_dir / "activity_definitions.json").read_text()
            )
            result["activity_definitions"] = [
                ActivityDefinition.from_dict(item).to_dict()
                for item in activity_payload
            ]
        if (config_dir / "model_type.json").exists():
            result["model_type"] = json.loads(
                (config_dir / "model_type.json").read_text()
            ).get("model_type", "shared")
        if (config_dir / "outcome_definitions.json").exists():
            result["outcome_definitions"] = json.loads(
                (config_dir / "outcome_definitions.json").read_text()
            )
        if (config_dir / "funnel_links.json").exists():
            result["funnel_links"] = json.loads(
                (config_dir / "funnel_links.json").read_text()
            )
        if (config_dir / "media_outcome_pathways.json").exists():
            result["media_outcome_pathways"] = json.loads(
                (config_dir / "media_outcome_pathways.json").read_text()
            )
        if (config_dir / "net_billthrough_metadata.json").exists():
            result["net_billthrough_metadata"] = json.loads(
                (config_dir / "net_billthrough_metadata.json").read_text()
            )
        if (config_dir / "workflow_state.json").exists():
            result["workflow_state"] = json.loads(
                (config_dir / "workflow_state.json").read_text()
            )
        if (config_dir / "calibration_records.json").exists():
            result["calibration_records"] = json.loads(
                (config_dir / "calibration_records.json").read_text()
            )
        if (config_dir / "model_comparison_candidates.json").exists():
            result["model_comparison_candidates"] = json.loads(
                (config_dir / "model_comparison_candidates.json").read_text()
            )
        if (config_dir / "migration_review.json").exists():
            result["migration_review"] = json.loads(
                (config_dir / "migration_review.json").read_text()
            )
        # PR 72E: Load governance evidence chain
        if (config_dir / "validation_policy.json").exists():
            result["validation_policy"] = json.loads(
                (config_dir / "validation_policy.json").read_text()
            )
        if (config_dir / "diagnostics_artefact.json").exists():
            result["diagnostics_artefact"] = json.loads(
                (config_dir / "diagnostics_artefact.json").read_text()
            )
        if (config_dir / "validation_results.json").exists():
            result["validation_results"] = json.loads(
                (config_dir / "validation_results.json").read_text()
            )
        if (config_dir / "approval_readiness.json").exists():
            result["approval_readiness"] = json.loads(
                (config_dir / "approval_readiness.json").read_text()
            )
        if (config_dir / "counterfactual_policy.json").exists():
            result["counterfactual_policy"] = json.loads(
                (config_dir / "counterfactual_policy.json").read_text()
            )
        if (config_dir / "currency_context.json").exists():
            result["currency_context"] = json.loads(
                (config_dir / "currency_context.json").read_text()
            )
        if (config_dir / "value_mapping.json").exists():
            result["value_mapping"] = json.loads(
                (config_dir / "value_mapping.json").read_text()
            )
        if (config_dir / "causal_graphs.json").exists():
            result["causal_graphs"] = json.loads(
                (config_dir / "causal_graphs.json").read_text()
            )
        if (config_dir / "search_objects.json").exists():
            result["search_objects"] = json.loads(
                (config_dir / "search_objects.json").read_text()
            )
        if (config_dir / "source_versions.json").exists():
            result["source_versions"] = json.loads(
                (config_dir / "source_versions.json").read_text()
            )
        if (config_dir / "variable_coverage_matrices.json").exists():
            result["variable_coverage_matrices"] = json.loads(
                (config_dir / "variable_coverage_matrices.json").read_text()
            )
        # G2A.7 (REQ-OUT-002): outcome approvals persisted alongside outcome
        # definitions. Absent in legacy bundles — treated as no approvals on
        # file, not an error.
        if (config_dir / "outcome_approvals.json").exists():
            result["outcome_approvals"] = json.loads(
                (config_dir / "outcome_approvals.json").read_text()
            )
        if (config_dir / "scenarios.json").exists():
            scenarios_meta = json.loads((config_dir / "scenarios.json").read_text())
            for i, s in enumerate(scenarios_meta):
                # G2A.7a.4: use shared scenario_from_dict for migration
                from .optimization import scenario_from_dict

                migrated = scenario_from_dict(s)
                pred_path = tmp / "scenarios" / f"scenario_{i}_predicted.csv"
                if pred_path.exists():
                    migrated["predicted"] = pd.read_csv(pred_path)
                scenarios_meta[i] = migrated
            result["scenarios"] = scenarios_meta

        trace_path = tmp / "model" / "trace.nc"
        if trace_path.exists():
            disk_trace = az.from_netcdf(str(trace_path))
            memory_groups = {
                group: getattr(disk_trace, group).load().copy(deep=True)
                for group in disk_trace.groups()
            }
            disk_trace.close()
            del disk_trace
            gc.collect()
            result["trace"] = az.InferenceData(**memory_groups)

        curve_bank_path = tmp / "curve_bank"
        if curve_bank_path.exists():
            result["curve_bank_files"] = {
                str(f.relative_to(curve_bank_path)): f.read_text()
                for f in curve_bank_path.rglob("*.json")
            }
            result["curve_bank_binary_files"] = {
                str(f.relative_to(curve_bank_path)): f.read_bytes()
                for f in curve_bank_path.rglob("*")
                if f.is_file() and f.suffix.lower() != ".json"
            }
        curve_artifact_path = tmp / "curve_artifacts"
        if curve_artifact_path.exists():
            result["curve_artifact_files"] = {
                str(f.relative_to(curve_artifact_path)): f.read_text()
                for f in curve_artifact_path.rglob("*.json")
            }
            result["curve_artifact_binary_files"] = {
                str(f.relative_to(curve_artifact_path)): f.read_bytes()
                for f in curve_artifact_path.rglob("*")
                if f.is_file() and f.suffix.lower() != ".json"
            }
        diagnostics_path = tmp / "diagnostics"
        if diagnostics_path.exists():
            for path in diagnostics_path.glob("*.json"):
                result["diagnostics"][path.stem] = json.loads(path.read_text())
            for path in diagnostics_path.glob("*.parquet"):
                result["diagnostics"][path.stem] = pd.read_parquet(path)
        notes_path = tmp / "notes.md"
        if notes_path.exists():
            result["notes"] = notes_path.read_text()

    return result


def resolve_imported_outcome_approvals(
    imported: Dict[str, Any],
) -> Tuple[List[dict], List[str]]:
    """G2A.7a.1 (REQ-OUT-002 section 12.1): resolve the outcome-approval
    records an imported bundle should use to `legacy_unapproved` migration
    lives in core (callable without Streamlit), not only in the project-
    export page, so a programmatic import (API, script, test) gets the same
    behaviour a UI-driven import does.

    Call this after `import_project()`, passing its result. Returns
    `(approvals, warnings)`:

    - If the bundle has an `outcome_approvals.json` file (`imported
      ["outcome_approvals"] is not None`), each record is round-tripped
      through `OutcomeApproval.from_dict`/`to_dict` for validation. A
      malformed record is quarantined (dropped), never silently discarded
      without a trace (REQ-OUT-002 section 12.3) - it is named by index and
      approval_id in `warnings`, and excluded from the returned list.
    - If the bundle has no approvals file at all (a legacy bundle predating
      G2A.7), one `legacy_unapproved` record is synthesised per outcome in
      the resolved outcome catalogue. The catalogue is resolved via
      `resolve_outcome_definitions` - the same derivation every other
      consumer uses - so a bundle whose outcomes are only derivable from
      `model_spec.segment_outcomes` (no persisted `outcome_definitions.json`
      at all) is migrated correctly too, not only bundles with an explicit
      persisted outcome catalogue.
    """
    from .outcome_approval import OutcomeApproval, legacy_unapproved_approval
    from .outcomes import resolve_outcome_definitions

    raw_approvals = imported.get("outcome_approvals")
    warnings: List[str] = []
    if raw_approvals is not None:
        normalised: List[dict] = []
        for index, item in enumerate(raw_approvals):
            # G2A.7a.2: validate that each record is a mapping before
            # deserialisation. Non-mapping values (None, string, number,
            # list) would fail with AttributeError on .items() — the old
            # (TypeError, ValueError, KeyError) tuple didn't catch this.
            if not isinstance(item, Mapping):
                input_type = type(item).__name__
                warnings.append(
                    f"Outcome approval record {index} is not a mapping "
                    f"(type={input_type!r}) and was quarantined "
                    "(dropped, not silently kept)."
                )
                continue
            try:
                normalised.append(OutcomeApproval.from_dict(item).to_dict())
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                approval_id = item.get("approval_id", "<unknown>")
                warnings.append(
                    f"Outcome approval record {index} (approval_id="
                    f"{approval_id!r}) was malformed and was quarantined "
                    f"(dropped, not silently kept): {exc}"
                )
        return normalised, warnings

    model_spec_dict = imported.get("model_spec")
    segment_outcomes: Dict[str, str] = {}
    segment_ltv: Optional[Dict[str, float]] = None
    if model_spec_dict:
        spec = ModelSpec.from_dict(model_spec_dict)
        segment_outcomes = spec.segment_outcomes
        segment_ltv = spec.segment_ltv
    resolved_outcomes = resolve_outcome_definitions(
        imported.get("outcome_definitions"),
        segment_outcomes,
        segment_ltv,
    )
    legacy_records = [
        legacy_unapproved_approval(outcome.outcome_id).to_dict()
        for outcome in resolved_outcomes
        if outcome.outcome_id
    ]
    return legacy_records, warnings


def resolve_imported_causal_graphs(
    imported: Dict[str, Any],
) -> Tuple[List[dict], List[str]]:
    """REQ-GRAPH-001 S10: resolve the causal-graph version records an
    imported bundle should use. Each record is round-tripped through
    `CausalGraph.from_dict`/`to_dict` for validation - a malformed record,
    or one carrying an unrecognised future `schema_version`, is quarantined
    (dropped), never silently discarded without a trace: it is named by
    index in `warnings` and excluded from the returned list, mirroring
    `resolve_imported_outcome_approvals`'s never-trust-silently contract.

    A bundle with no `causal_graphs.json` file (every bundle exported before
    this capability existed, and every current project with no graph
    configured yet) resolves to an empty list with no warnings - that is
    the correct "no graph yet" reading, not an error.
    """
    from .causal_graph import CausalGraph

    raw_graphs = imported.get("causal_graphs")
    warnings: List[str] = []
    if not raw_graphs:
        return [], warnings

    normalised: List[dict] = []
    for index, item in enumerate(raw_graphs):
        if not isinstance(item, Mapping):
            input_type = type(item).__name__
            warnings.append(
                f"Causal graph record {index} is not a mapping "
                f"(type={input_type!r}) and was quarantined "
                "(dropped, not silently kept)."
            )
            continue
        try:
            normalised.append(CausalGraph.from_dict(item).to_dict())
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            graph_id = item.get("graph_id", "<unknown>")
            warnings.append(
                f"Causal graph record {index} (graph_id={graph_id!r}) was "
                f"malformed and was quarantined (dropped, not silently "
                f"kept): {exc}"
            )
    return normalised, warnings


def resolve_imported_search_objects(
    imported: Dict[str, Any],
) -> Tuple[List[dict], List[str]]:
    """REQ-SEARCH-001: resolve the governed `SearchObjectDefinition` version
    records an imported bundle should use - every saved
    `search_object_version` per lineage (REQ-SEARCH-001 S10), mirroring
    `resolve_imported_causal_graphs`'s "resolve every version, let the
    caller derive current" contract. Each record is round-tripped through
    `SearchObjectDefinition.from_dict`/`to_dict` for validation - a
    malformed record, or one carrying an unrecognised future
    `schema_version`, is quarantined (dropped), never silently discarded
    without a trace: it is named by index in `warnings` and excluded from
    the returned list, mirroring `resolve_imported_causal_graphs`'s
    never-trust-silently contract. The surviving records are then run
    through `validate_search_object_catalogue` - a cross-object issue (a
    duplicate `(market, search_object_id, search_object_version)`, or the
    same source column claimed by two different search roles in the
    *current* version of each lineage) is reported the same way, never
    silently accepted just because each record was individually
    well-formed.

    Callers wanting only the current record per lineage (the common case -
    everywhere except a version-history display) should pass this
    function's output through
    `core.search_objects.current_search_object_versions`, mirroring how
    `core.causal_graph.current_graph_from_resolved_versions` is layered on
    top of `resolve_imported_causal_graphs`.

    A bundle with no `search_objects.json` file (every bundle exported
    before this capability existed, and every current project with no
    Search objects governed yet) resolves to an empty list with no
    warnings - that is the correct "none governed yet" reading, not an
    error.
    """
    from .search_objects import SearchObjectDefinition, validate_search_object_catalogue

    raw_objects = imported.get("search_objects")
    warnings: List[str] = []
    if not raw_objects:
        return [], warnings

    normalised: List[SearchObjectDefinition] = []
    for index, item in enumerate(raw_objects):
        if not isinstance(item, Mapping):
            input_type = type(item).__name__
            warnings.append(
                f"Search object record {index} is not a mapping "
                f"(type={input_type!r}) and was quarantined "
                "(dropped, not silently kept)."
            )
            continue
        try:
            normalised.append(SearchObjectDefinition.from_dict(item))
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            search_object_id = item.get("search_object_id", "<unknown>")
            warnings.append(
                f"Search object record {index} "
                f"(search_object_id={search_object_id!r}) was malformed and "
                f"was quarantined (dropped, not silently kept): {exc}"
            )

    catalogue_issues = validate_search_object_catalogue(normalised)
    if catalogue_issues:
        quarantined_keys = {
            (issue.market, issue.search_object_id) for issue in catalogue_issues
        }
        warnings.extend(
            f"Search object {issue.search_object_id!r} (market "
            f"{issue.market!r}) was quarantined ({issue.issue_type}): "
            f"{issue.detail}"
            for issue in catalogue_issues
        )
        normalised = [
            defn
            for defn in normalised
            if (defn.market, defn.search_object_id) not in quarantined_keys
        ]

    return [defn.to_dict() for defn in normalised], warnings


def resolve_imported_source_versions(
    imported: Dict[str, Any],
) -> Tuple[List[dict], List[str]]:
    """REQ-COVERAGE-001 S3: resolve the immutable `SourceVersion` history an
    imported bundle should use - every recorded upload (never only the
    latest per `source_id`; a version history is a permanent audit record,
    not a "current state" the way `resolve_imported_search_objects`'
    per-lineage current record is). Each record is round-tripped through
    `SourceVersion.from_dict`/`to_dict` for validation - a malformed
    record is quarantined (dropped), never silently discarded without a
    trace, mirroring `resolve_imported_causal_graphs`/
    `resolve_imported_search_objects`'s never-trust-silently contract.

    A bundle with no `source_versions.json` file (every bundle exported
    before this capability existed, and every current project with no
    real-upload provenance recorded yet) resolves to an empty list with no
    warnings - that is the correct "no history recorded yet" reading, not
    an error. Callers resuming an upload (deciding the next `version`
    number for a given `source_id`) should pass this function's output to
    `core.coverage.current_source_versions` to find the highest recorded
    version per lineage.
    """
    from .coverage import SourceVersion

    raw_versions = imported.get("source_versions")
    warnings: List[str] = []
    if not raw_versions:
        return [], warnings

    normalised: List[dict] = []
    for index, item in enumerate(raw_versions):
        if not isinstance(item, Mapping):
            input_type = type(item).__name__
            warnings.append(
                f"Source version record {index} is not a mapping "
                f"(type={input_type!r}) and was quarantined "
                "(dropped, not silently kept)."
            )
            continue
        try:
            normalised.append(SourceVersion.from_dict(item).to_dict())
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            source_id = item.get("source_id", "<unknown>")
            warnings.append(
                f"Source version record {index} (source_id={source_id!r}) "
                f"was malformed and was quarantined (dropped, not silently "
                f"kept): {exc}"
            )
    return normalised, warnings


def resolve_imported_variable_coverage_matrices(
    imported: Dict[str, Any],
) -> Tuple[List[dict], List[str]]:
    """REQ-COVERAGE-001 S1: resolve the `VariableCoverageMatrix` version
    records an imported bundle should use - every saved version, mirroring
    `resolve_imported_causal_graphs`'s "resolve every version, let the
    caller derive current" contract (`core.coverage.
    current_variable_coverage_matrix_from_resolved_versions` is layered on
    top of this, the same way `current_graph_from_resolved_versions` is
    layered on top of `resolve_imported_causal_graphs`). Each record is
    round-tripped through `VariableCoverageMatrix.from_dict`/`to_dict` for
    validation - a malformed record, or one carrying an unrecognised future
    `schema_version`, is quarantined (dropped), never silently discarded
    without a trace: it is named by index in `warnings` and excluded from
    the returned list, mirroring `resolve_imported_causal_graphs`/
    `resolve_imported_search_objects`'s never-trust-silently contract.

    A bundle with no `variable_coverage_matrices.json` file (every bundle
    exported before this capability existed, and every current project with
    no coverage matrix built yet) resolves to an empty list with no
    warnings - that is the correct "no coverage matrix yet" reading, not an
    error.
    """
    from .coverage import VariableCoverageMatrix

    raw_matrices = imported.get("variable_coverage_matrices")
    warnings: List[str] = []
    if not raw_matrices:
        return [], warnings

    normalised: List[dict] = []
    for index, item in enumerate(raw_matrices):
        if not isinstance(item, Mapping):
            input_type = type(item).__name__
            warnings.append(
                f"Variable coverage matrix record {index} is not a mapping "
                f"(type={input_type!r}) and was quarantined "
                "(dropped, not silently kept)."
            )
            continue
        try:
            normalised.append(VariableCoverageMatrix.from_dict(item).to_dict())
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            matrix_id = item.get("matrix_id", "<unknown>")
            warnings.append(
                f"Variable coverage matrix record {index} "
                f"(matrix_id={matrix_id!r}) was malformed and was "
                f"quarantined (dropped, not silently kept): {exc}"
            )
    return normalised, warnings


def _validate_relative_artifact_path(rel_path: str) -> None:
    """Reject a bundle-supplied relative path unless every segment is a
    portable, non-traversing path component (Corrective PR E3.2)."""
    candidate = Path(rel_path)
    if candidate.is_absolute():
        raise CurveArtifactStoreError(
            f"curve artifact path must be relative, got an absolute path: {rel_path!r}"
        )
    if not candidate.parts:
        raise CurveArtifactStoreError("curve artifact path must not be blank")
    for part in candidate.parts:
        validate_portable_path_component(part, label="curve artifact path segment")


def _reject_case_insensitive_top_level_collisions(rel_paths: Sequence[str]) -> None:
    """Reject two distinct top-level artifact directories that would collide
    once case-folded (Corrective PR E3.2) - Windows and macOS default
    filesystems are case-insensitive, so ``Art-1`` and ``art-1`` are the same
    destination on disk even though the bundle carries them as distinct
    entries."""
    seen: Dict[str, str] = {}
    for rel_path in rel_paths:
        top = Path(rel_path).parts[0]
        folded = top.casefold()
        existing = seen.setdefault(folded, top)
        if existing != top:
            raise CurveArtifactStoreError(
                "curve artifact paths collide once case-folded (unsafe on a "
                f"case-insensitive filesystem): {existing!r} vs {top!r}"
            )


def _resolve_under(root: Path, rel_path: str) -> Path:
    """Join ``rel_path`` onto ``root`` and verify the resolved destination
    is still beneath ``root`` (defense in depth beyond
    ``_validate_relative_artifact_path``'s component-level checks -
    Corrective PR E3.2, mirroring ``CurveService``'s equivalent
    resolved-destination check for a freshly generated artifact_id)."""
    target = root / Path(rel_path)
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_target != resolved_root and not resolved_target.is_relative_to(
        resolved_root
    ):
        raise CurveArtifactStoreError(
            f"curve artifact path resolves outside the store: {rel_path!r}"
        )
    return target


def replace_curve_artifact_store(
    imported: Dict[str, Any], restored_artifact_dir: Path
) -> None:
    """Transactionally replace ``restored_artifact_dir``'s contents with an
    imported bundle's official curve artifacts (Corrective PR A5, made
    transactional by Corrective PR E3.1/E3.2).

    Importing a bundle must replace the destination project's
    official-artifact store, never merge into it - unconditionally,
    including when the bundle declares zero official curve artifacts.
    Without this, (a) a bundle that omits ``curve_artifact_files`` entirely
    leaves the destination's prior artifacts untouched, and (b) even a
    bundle that does declare artifacts only ever adds/overwrites paths
    present in the bundle, so any artifact directory already present in the
    destination but absent from the bundle survives the import. Either way,
    stale artifacts from a previously open project could satisfy the
    ``official_curves`` checkpoint or appear in reports for a project they
    don't belong to.

    The previous implementation removed ``restored_artifact_dir`` before
    writing anything, so a failure partway through (malformed payload, a
    write failure, disk exhaustion, a failed promotion or verification)
    could destroy a previously valid store and leave an empty or partial
    destination. This version stages the complete imported store on a
    sibling directory (same volume as the destination, so the final
    promotion can be an atomic rename), verifies it through the same
    canonical loader/fingerprint audit the live app uses, and only then
    swaps it in - backing up the current destination first and restoring
    that backup if anything past this point fails. The old store is never
    touched until the staged replacement has already proven loadable.
    """
    restored_artifact_dir = Path(restored_artifact_dir)
    text_files: Dict[str, str] = imported.get("curve_artifact_files") or {}
    binary_files: Dict[str, bytes] = imported.get("curve_artifact_binary_files") or {}
    all_rel_paths = [*text_files.keys(), *binary_files.keys()]

    if not all_rel_paths and not restored_artifact_dir.exists():
        # Nothing to import, nothing to replace - preserve "never existed"
        # rather than manufacturing an empty directory that wasn't there
        # before (existing contract, still transactional: source state
        # already equals destination state).
        return

    # 1. Validate every relative path before writing anything.
    for rel_path in all_rel_paths:
        _validate_relative_artifact_path(rel_path)
    _reject_case_insensitive_top_level_collisions(all_rel_paths)

    store_root = restored_artifact_dir.parent
    store_root.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{restored_artifact_dir.name}.stage-", dir=str(store_root)
        )
    )
    backup_dir: Optional[Path] = None
    promoted = False
    preserve_backup_for_manual_recovery = False
    try:
        # 2-4. Materialise the complete imported store into staging (an
        # empty bundle stages an empty directory - still promoted through
        # the same swap below, never a shortcut that touches the old store
        # first).
        for rel_path, contents in text_files.items():
            target = _resolve_under(stage_dir, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents)
        for rel_path, binary_contents in binary_files.items():
            target = _resolve_under(stage_dir, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(binary_contents)

        # 5-6. Canonical artefact-store loader and fingerprint audit on
        # staging - fails closed before the current destination is touched
        # if the staged store is invalid.
        load_curve_artifact_store(stage_dir, raise_on_malformed=True)

        # 7-8. Atomically back up the current destination, if any exists.
        # ``backup_dir`` is only ever recorded once the rename onto it has
        # actually succeeded - if this ``os.replace`` itself raises, the
        # original destination was never touched, so the except clause
        # below must see no backup to roll back (nothing to undo).
        if restored_artifact_dir.exists():
            candidate_backup_dir = store_root / (
                f".{restored_artifact_dir.name}.backup-{uuid.uuid4().hex}"
            )
            os.replace(restored_artifact_dir, candidate_backup_dir)
            backup_dir = candidate_backup_dir

        # 9. Atomically promote staging into the destination.
        os.replace(stage_dir, restored_artifact_dir)
        promoted = True

        # 10. Verify the final destination through the canonical loader.
        load_curve_artifact_store(restored_artifact_dir, raise_on_malformed=True)

        # 11. Remove the backup only after final verification succeeds.
        if backup_dir is not None:
            shutil.rmtree(backup_dir, ignore_errors=True)
            backup_dir = None
    except Exception as exc:
        # 12. On any failure from this point on - including promotion
        # itself failing, not only a later verification failure - restore
        # the backup: ``promoted`` only controls whether the (bad) promoted
        # content must be discarded first, never whether a restore is
        # attempted at all. A backup exists (``backup_dir is not None``)
        # whenever the previous store was renamed aside, regardless of
        # whether the rename that was supposed to replace it afterward ever
        # completed - the old store is preserved byte-for-byte whenever the
        # replacement itself fails.
        if backup_dir is not None:
            if promoted:
                shutil.rmtree(restored_artifact_dir, ignore_errors=True)
            try:
                os.replace(backup_dir, restored_artifact_dir)
            except OSError as restore_exc:
                # The rollback itself failed - never silently drop the only
                # surviving copy of the previous store. Leave it on disk at
                # ``backup_dir`` (finally: below must not clean it up) and
                # say exactly where it is and what to do.
                preserve_backup_for_manual_recovery = True
                raise CurveArtifactStoreError(
                    "Curve artifact store replacement failed and the "
                    f"automatic rollback also failed ({restore_exc}). "
                    f"The previous store was NOT lost - it is intact at "
                    f"{backup_dir} and must be moved back to "
                    f"{restored_artifact_dir} manually."
                ) from exc
            backup_dir = None
        raise
    finally:
        # 13. Clean up staging/backup remnants after success or rollback -
        # except a backup a failed rollback couldn't restore, which must
        # survive for manual recovery (see the except clause above).
        shutil.rmtree(stage_dir, ignore_errors=True)
        if backup_dir is not None and not preserve_backup_for_manual_recovery:
            shutil.rmtree(backup_dir, ignore_errors=True)


def _load_curve_artifacts_for_audit(imported: Dict[str, Any]) -> List[CurveArtifact]:
    """Materialise and load every official curve artifact from an imported
    bundle's ``curve_artifact_files``/``curve_artifact_binary_files``.

    Materialises the imported files into a fresh temp directory and reuses
    ``load_curve_artifact_store``'s existing fingerprint verification and
    per-artifact audit (REQ-CURVE-001) rather than a second, bundle-level
    checksum mechanism - a store that fails to reload here fails the same
    way it would in the live app. The returned artifacts (metadata plus
    in-memory draw/summary frames) are fully materialised before the temp
    directory is cleaned up, so they remain valid after this function
    returns. Used both to count loadable artifacts and, for the
    ``official_curves`` checkpoint, to revalidate each artifact's own
    governance snapshot against the imported bundle's reconstructed
    identity (Corrective PR A6) - historical fingerprint self-consistency
    alone is not sufficient for that checkpoint.
    """
    text_files = imported.get("curve_artifact_files") or {}
    binary_files = imported.get("curve_artifact_binary_files") or {}
    if not text_files and not binary_files:
        return []
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        for rel_path, contents in text_files.items():
            target = tmp / Path(rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents)
        for rel_path, binary_contents in binary_files.items():
            target = tmp / Path(rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(binary_contents)
        result = load_curve_artifact_store(tmp, raise_on_malformed=False)
        return list(result.loaded)


def _count_loaded_curve_artifacts(imported: Dict[str, Any]) -> int:
    """How many official curve artifacts round-trip cleanly from an
    imported bundle's ``curve_artifact_files``/``curve_artifact_binary_files``.

    A malformed-only store (0 loaded) must not satisfy the
    ``official_curves`` checkpoint (PR 96B).
    """
    return len(_load_curve_artifacts_for_audit(imported))


def audit_project_resumability(imported: Dict[str, Any]) -> Dict[str, Any]:
    """Audit whether an imported bundle can resume its declared checkpoint.

    Legacy bundles remain importable; they report a migration warning rather
    than being treated as corrupt. Required artefacts grow with the furthest
    checkpoint actually represented by the bundle.
    """
    manifest = imported.get("manifest") or {}
    loaded_curve_artifact_count = _count_loaded_curve_artifacts(imported)
    declared = manifest.get("workflow_checkpoint")
    if not declared or declared == "unknown":
        if imported.get("scenarios"):
            declared = "scenarios"
        elif loaded_curve_artifact_count > 0:
            declared = "official_curves"
        elif imported.get("curve_bank_files") or imported.get(
            "curve_bank_binary_files"
        ):
            declared = "curves"
        elif imported.get("model_approval"):
            declared = "approved"
        elif imported.get("trace") is not None:
            declared = "fitted"
        elif imported.get("model_spec"):
            declared = "pre_fit"
        else:
            declared = "uploaded"

    required = {
        "uploaded": ["raw_sources"],
        "transformed": ["raw_sources", "transformed_data"],
        "configured": ["raw_sources", "transformed_data", "model_spec"],
        "pre_fit": ["raw_sources", "transformed_data", "model_spec"],
        "fitted": [
            "raw_sources",
            "transformed_data",
            "model_spec",
            "trace",
            "model_meta",
        ],
        "approved": [
            "raw_sources",
            "transformed_data",
            "model_spec",
            "trace",
            "model_meta",
            "model_approval",
        ],
        "curves": [
            "raw_sources",
            "transformed_data",
            "model_spec",
            "trace",
            "model_meta",
            "model_approval",
            "curve_bank_files",
        ],
        # PR 96B: a distinct, stricter checkpoint from "curves" - reached
        # only via at least one artifact from the governed official curve
        # artifact store (CurveService.create_official_artifact), never via
        # the legacy CurveBankEntry parameter-snapshot registry alone. See
        # `present()`'s "curve_artifact_files" case below and
        # `_count_loaded_curve_artifacts`.
        "official_curves": [
            "raw_sources",
            "transformed_data",
            "model_spec",
            "trace",
            "model_meta",
            "model_approval",
            "curve_artifact_files",
        ],
        "scenarios": [
            "raw_sources",
            "transformed_data",
            "model_spec",
            "trace",
            "model_meta",
            "model_approval",
            "scenarios",
        ],
    }.get(declared, [])

    def present(key: str) -> bool:
        value = imported.get(key)
        if key == "curve_bank_files":
            return bool(value or imported.get("curve_bank_binary_files"))
        if key == "curve_artifact_files":
            return loaded_curve_artifact_count > 0
        if key == "trace":
            return value is not None
        if key in {"transformed_data", "model_spec", "model_meta", "model_approval"}:
            return value is not None
        return bool(value)

    missing = [key for key in required if not present(key)]
    warnings = []
    if not manifest:
        warnings.append(
            "Legacy bundle has no manifest; checkpoint was inferred and will "
            "be migrated on the next export."
        )
    pathway_masks = (imported.get("model_meta") or {}).get("pathway_masks") or {}
    if pathway_masks and (
        pathway_masks.get("legacy_governance_mode")
        or not pathway_masks.get("components")
    ):
        warnings.append(
            "Legacy mask-only pathway metadata will be migrated to explicit "
            "components. Analyst attribution is preserved, but headline reporting "
            "and planning remain blocked until governance review."
        )
    # G2A.7a.2 (REQ-OUT-002 section 12.2): a bundle may be technically
    # loadable ("resumable") while official use of its checkpoint remains
    # blocked by outcome governance - a checkpoint that implies official
    # artefacts (approved model / curves / scenarios) additionally requires
    # at least one outcome with an active, valid "approved" approval that
    # covers the required use, not merely a bundle that loads without error.
    officially_resumable = not missing
    outcome_governance_warnings: List[str] = []
    official_blocking_reasons: List[dict] = []
    if declared in {"approved", "curves", "official_curves", "scenarios"}:
        approvals, _ = resolve_imported_outcome_approvals(imported)
        from .outcome_approval import OutcomeApproval

        # G2A.7a.2: validate each approval record beyond status == "approved"
        active_approvals: list[dict] = []
        for a_dict in approvals:
            try:
                approval = OutcomeApproval.from_dict(a_dict)
            except (TypeError, ValueError, KeyError, AttributeError):
                official_blocking_reasons.append(
                    {
                        "artefact_type": "outcome_approval",
                        "artefact_id": a_dict.get("approval_id", "<unknown>"),
                        "reason": "malformed_approval_record",
                    }
                )
                continue
            if approval.status != "approved":
                continue
            if not approval.is_active():
                official_blocking_reasons.append(
                    {
                        "artefact_type": "outcome_approval",
                        "artefact_id": approval.approval_id,
                        "outcome_id": approval.outcome_id,
                        "reason": "approval_not_active",
                    }
                )
                continue
            if not approval.definition_fingerprint:
                official_blocking_reasons.append(
                    {
                        "artefact_type": "outcome_approval",
                        "artefact_id": approval.approval_id,
                        "outcome_id": approval.outcome_id,
                        "reason": "missing_definition_fingerprint",
                    }
                )
                continue
            # Valid active approval
            active_approvals.append(a_dict)

        if not active_approvals:
            officially_resumable = False
            if not any(
                r["reason"] == "malformed_approval_record"
                for r in official_blocking_reasons
            ):
                outcome_governance_warnings.append(
                    "No outcome has an active 'approved' OutcomeApproval - "
                    "official curves, scenarios, and reports remain blocked "
                    "until outcomes are reviewed and approved on Structure -> "
                    "Outcome Governance, even though this bundle loaded "
                    "successfully."
                )

        # G2A.7a.2, G2A.7a.3: for scenarios checkpoint, check that saved
        # scenario targets have matching approvals for the correct use —
        # manual scenarios require "planning", optimiser results require
        # "optimisation". Corrective PR A6: the official_curves checkpoint
        # shares the same model-identity reconstruction, since historical
        # fingerprint self-consistency alone (each artifact matching its own
        # stored fingerprints) does not prove the artifact belongs to *this*
        # bundle's model — a foreign artifact copied from another project,
        # or one bound to an outcome with only an unrelated active approval,
        # must not satisfy the checkpoint.
        if declared in {"official_curves", "scenarios"} and officially_resumable:
            scenarios = imported.get("scenarios") or []

            # G2A.7a.9: build a complete validation context per scenario.
            # Each official scenario has its own planning objective which
            # must match the current project state.
            current_outcome_defns = imported.get("outcome_definitions") or ()
            current_outcome_appr = tuple(a_dict for a_dict in active_approvals)

            # G2A.7a.10: the model-approval fingerprint and current identity
            # fingerprints used to be read from a "fingerprint" dict key that
            # ModelApproval.to_dict() never populates (always "") and the
            # approval's own self-reported data/spec/posterior fields (which
            # would make the check tautological - the approval always
            # "matches itself"). Instead, reconstruct the bundle's actual
            # current model identity once and validate the approval against
            # it - the canonical model_approval_fingerprint is calculated
            # via fingerprint_model_approval(), never looked up as a dict key.
            reconstructed = reconstruct_model_state(imported)
            verified_model_approval_fingerprint = ""
            current_data_fp = current_spec_fp = current_posterior_fp = ""
            model_identity_reason: Optional[str] = None
            if (
                reconstructed.get("frame") is None
                or reconstructed.get("posterior_params") is None
            ):
                model_identity_reason = (
                    "model_identity_unreconstructable: could not rebuild this "
                    "bundle's modelling frame/posterior well enough to verify "
                    "its model approval."
                )
            else:
                current_data_fp, current_spec_fp, current_posterior_fp = (
                    current_model_identity_fingerprints(imported, reconstructed)
                )
                raw_approval = imported.get("model_approval")
                if not raw_approval:
                    model_identity_reason = (
                        "model_approval_missing: no model approval is recorded "
                        "in this bundle."
                    )
                else:
                    # REQ-VAL-001: a policy-backed approval also requires its
                    # readiness and current policy evidence, not model
                    # identity alone (require_matching_approval raises
                    # ValidationPolicyBlockedError, not ApprovalMismatchError,
                    # when either is missing) - load both from this same
                    # bundle so a genuinely policy-backed, self-consistent
                    # approval is verified rather than always rejected for
                    # evidence this function never looked up.
                    from .validation_policy import (
                        load_approval_readiness,
                        load_threshold_policy,
                    )

                    bundle_readiness, _ = load_approval_readiness(
                        imported.get("approval_readiness")
                    )
                    bundle_policy, _ = load_threshold_policy(
                        imported.get("validation_policy")
                    )
                    try:
                        approval_obj = ModelApproval.from_dict(raw_approval)
                        # require_matching_approval only checks that
                        # approval_readiness's own recorded fingerprints are
                        # internally self-consistent - it cannot also verify
                        # those fingerprints against a freshly recomputed
                        # diagnostics artefact fingerprint, since
                        # DiagnosticsArtefact is an application-layer type
                        # core must not import (see
                        # application.project_service.verify_imported_readiness,
                        # the caller that does that fuller check - a bundle
                        # this audit calls "resumable" must still go through
                        # that fuller verification before any official use is
                        # actually authorised; CurveService.authorize_use
                        # independently re-verifies the full chain at every
                        # official use regardless of what this audit
                        # reports). A missing or structurally-invalid
                        # diagnostics_artefact for a policy-backed approval is
                        # still a core-detectable evidence gap, so it fails
                        # closed here too rather than letting an incomplete
                        # bundle report full official resumability.
                        raw_diagnostics_artefact = imported.get("diagnostics_artefact")
                        if approval_obj.validation_policy_id and (
                            raw_diagnostics_artefact is None
                            or not isinstance(raw_diagnostics_artefact, dict)
                        ):
                            raise ValidationPolicyBlockedError(
                                "Approval references validation policy "
                                f"'{approval_obj.validation_policy_id}' but this "
                                "bundle has no diagnostics artefact to verify "
                                "the readiness evidence against."
                            )
                        require_matching_approval(
                            approval_obj,
                            model_run_id=imported.get("model_run_id", ""),
                            data_fingerprint=current_data_fp,
                            model_spec_fingerprint=current_spec_fp,
                            posterior_fingerprint=current_posterior_fp,
                            approval_readiness=bundle_readiness,
                            current_policy=bundle_policy,
                        )
                        verified_model_approval_fingerprint = (
                            fingerprint_model_approval(approval_obj)
                        )
                    except (
                        TypeError,
                        ValueError,
                        ApprovalMismatchError,
                        ValidationPolicyBlockedError,
                    ) as exc:
                        model_identity_reason = f"model_approval_mismatch: {exc}"

            # Corrective PR A6: revalidate every loaded curve artifact
            # against the reconstructed imported model identity and a
            # matching current outcome approval, rather than trusting an
            # artifact's own historical fingerprint self-consistency.
            if declared == "official_curves":
                from .outcome_approval import fingerprint_outcome_definition
                from .outcomes import OutcomeDefinition

                bundle_model_run_id = imported.get("model_run_id", "")
                for artifact in _load_curve_artifacts_for_audit(imported):
                    artifact_label = artifact.metadata.artifact_id
                    if model_identity_reason is not None:
                        officially_resumable = False
                        official_blocking_reasons.append(
                            {
                                "artefact_type": "curve_artifact",
                                "artefact_id": artifact_label,
                                "reason": model_identity_reason,
                            }
                        )
                        continue

                    identity_snapshot = artifact.metadata.model_identity_snapshot
                    if (
                        identity_snapshot.get("model_run_id") != bundle_model_run_id
                        or identity_snapshot.get("data_fingerprint") != current_data_fp
                        or identity_snapshot.get("model_spec_fingerprint")
                        != current_spec_fp
                        or identity_snapshot.get("posterior_fingerprint")
                        != current_posterior_fp
                    ):
                        officially_resumable = False
                        official_blocking_reasons.append(
                            {
                                "artefact_type": "curve_artifact",
                                "artefact_id": artifact_label,
                                "reason": (
                                    "model_identity_mismatch: artifact's "
                                    "model_identity_snapshot does not match this "
                                    "bundle's reconstructed model identity — it "
                                    "may belong to a different model."
                                ),
                            }
                        )
                        continue

                    try:
                        outcome_def = OutcomeDefinition.from_dict(
                            artifact.metadata.outcome_definition_snapshot
                        )
                    except (TypeError, ValueError, KeyError, AttributeError) as exc:
                        officially_resumable = False
                        official_blocking_reasons.append(
                            {
                                "artefact_type": "curve_artifact",
                                "artefact_id": artifact_label,
                                "reason": (
                                    f"malformed_outcome_definition_snapshot: {exc}"
                                ),
                            }
                        )
                        continue

                    definition_fingerprint = fingerprint_outcome_definition(outcome_def)
                    matching_approval = next(
                        (
                            a_dict
                            for a_dict in active_approvals
                            if a_dict.get("outcome_id") == outcome_def.outcome_id
                            and a_dict.get("definition_fingerprint")
                            == definition_fingerprint
                            and "curve_publication"
                            in (a_dict.get("allowed_uses") or ())
                        ),
                        None,
                    )
                    if matching_approval is None:
                        officially_resumable = False
                        official_blocking_reasons.append(
                            {
                                "artefact_type": "curve_artifact",
                                "artefact_id": artifact_label,
                                "outcome_id": outcome_def.outcome_id,
                                "required_use": "curve_publication",
                                "reason": (
                                    "no_matching_outcome_approval: no active "
                                    "approval with 'curve_publication' authority "
                                    "matches this artifact's actual outcome "
                                    "definition."
                                ),
                            }
                        )

            if declared == "scenarios":
                from .optimization import (
                    PlanningObjective,
                    validation_context_from_legacy_args,
                    validate_scenario_dependencies,
                )

            for idx, sc in enumerate(scenarios if declared == "scenarios" else []):
                sc_gov = sc.get("governance_mode", "exploratory")
                if sc_gov != "official":
                    continue
                # Build scenario-specific planning objective
                sc_po_raw = sc.get("planning_objective")
                try:
                    sc_po = (
                        PlanningObjective.from_dict(sc_po_raw)
                        if isinstance(sc_po_raw, dict)
                        else PlanningObjective()
                    )
                except (TypeError, ValueError):
                    officially_resumable = False
                    official_blocking_reasons.append(
                        {
                            "artefact_type": "scenario",
                            "artefact_id": sc.get("name", f"scenario_{idx}"),
                            "reason": "invalid_planning_objective: saved objective cannot be deserialised",
                        }
                    )
                    continue

                if model_identity_reason is not None:
                    officially_resumable = False
                    official_blocking_reasons.append(
                        {
                            "artefact_type": "scenario",
                            "artefact_id": sc.get("name", f"scenario_{idx}"),
                            "reason": model_identity_reason,
                        }
                    )
                    continue

                # PR 125A (brief section 7.2): a project-level
                # CounterfactualPolicy and CurrencyContext now travel through
                # the bundle (config/counterfactual_policy.json,
                # config/currency_context.json) alongside each scenario's own
                # saved dependency fingerprint. A scenario is verified
                # against THIS bundle's project-level evidence, never against
                # its own saved fingerprint (that would be tautological -
                # see the model-approval comment above). A bundle exported
                # before this field existed (or one where the project-level
                # evidence is missing/malformed) still fails closed, exactly
                # as every scenario with a saved dependency did before this
                # PR - no legacy evidence is ever fabricated.
                sc_deps = sc.get("governance_dependencies") or {}
                sc_cf_fp = sc_deps.get("counterfactual_policy_fingerprint")
                sc_currency_fp = sc_deps.get("currency_context_fingerprint")
                sc_value_mapping_fp = sc_deps.get("value_mapping_fingerprint")
                identity_check_failed = False

                if sc_cf_fp:
                    raw_cf_policy = imported.get("counterfactual_policy")
                    if raw_cf_policy is None:
                        identity_check_failed = True
                        official_blocking_reasons.append(
                            {
                                "artefact_type": "scenario",
                                "artefact_id": sc.get("name", f"scenario_{idx}"),
                                "reason": (
                                    "counterfactual_identity_unverifiable: this "
                                    "bundle has no project-level counterfactual "
                                    "policy to verify the scenario's saved "
                                    "counterfactual identity against."
                                ),
                            }
                        )
                    else:
                        try:
                            current_cf_fp = CounterfactualPolicy.from_dict(
                                raw_cf_policy
                            ).fingerprint()
                        except (TypeError, ValueError, KeyError, AttributeError) as exc:
                            identity_check_failed = True
                            official_blocking_reasons.append(
                                {
                                    "artefact_type": "scenario",
                                    "artefact_id": sc.get("name", f"scenario_{idx}"),
                                    "reason": (
                                        "counterfactual_policy_malformed: this "
                                        f"bundle's project-level counterfactual "
                                        f"policy could not be loaded: {exc}"
                                    ),
                                }
                            )
                        else:
                            if current_cf_fp != sc_cf_fp:
                                identity_check_failed = True
                                official_blocking_reasons.append(
                                    {
                                        "artefact_type": "scenario",
                                        "artefact_id": sc.get(
                                            "name", f"scenario_{idx}"
                                        ),
                                        "reason": (
                                            "counterfactual_identity_mismatch: "
                                            "this scenario's saved counterfactual "
                                            "policy fingerprint does not match "
                                            "this bundle's project-level "
                                            "counterfactual policy."
                                        ),
                                    }
                                )

                if sc_currency_fp:
                    raw_currency_context = imported.get("currency_context")
                    if raw_currency_context is None:
                        identity_check_failed = True
                        official_blocking_reasons.append(
                            {
                                "artefact_type": "scenario",
                                "artefact_id": sc.get("name", f"scenario_{idx}"),
                                "reason": (
                                    "currency_identity_unverifiable: this bundle "
                                    "has no project-level currency context to "
                                    "verify the scenario's saved currency "
                                    "identity against."
                                ),
                            }
                        )
                    else:
                        try:
                            current_currency_fp = CurrencyContext.from_dict(
                                raw_currency_context
                            ).fingerprint()
                        except (TypeError, ValueError, KeyError, AttributeError) as exc:
                            identity_check_failed = True
                            official_blocking_reasons.append(
                                {
                                    "artefact_type": "scenario",
                                    "artefact_id": sc.get("name", f"scenario_{idx}"),
                                    "reason": (
                                        "currency_context_malformed: this "
                                        f"bundle's project-level currency "
                                        f"context could not be loaded: {exc}"
                                    ),
                                }
                            )
                        else:
                            if current_currency_fp != sc_currency_fp:
                                identity_check_failed = True
                                official_blocking_reasons.append(
                                    {
                                        "artefact_type": "scenario",
                                        "artefact_id": sc.get(
                                            "name", f"scenario_{idx}"
                                        ),
                                        "reason": (
                                            "currency_identity_mismatch: this "
                                            "scenario's saved currency context "
                                            "fingerprint does not match this "
                                            "bundle's project-level currency "
                                            "context."
                                        ),
                                    }
                                )

                if sc_value_mapping_fp:
                    raw_value_mapping = imported.get("value_mapping")
                    if raw_value_mapping is None:
                        identity_check_failed = True
                        official_blocking_reasons.append(
                            {
                                "artefact_type": "scenario",
                                "artefact_id": sc.get("name", f"scenario_{idx}"),
                                "reason": (
                                    "value_mapping_identity_unverifiable: this "
                                    "bundle has no project-level value mapping "
                                    "to verify the scenario's saved value-"
                                    "mapping identity against."
                                ),
                            }
                        )
                    else:
                        try:
                            current_value_mapping_fp = OutcomeValueMapping.from_dict(
                                raw_value_mapping
                            ).fingerprint
                        except (TypeError, ValueError, KeyError, AttributeError) as exc:
                            identity_check_failed = True
                            official_blocking_reasons.append(
                                {
                                    "artefact_type": "scenario",
                                    "artefact_id": sc.get("name", f"scenario_{idx}"),
                                    "reason": (
                                        "value_mapping_malformed: this bundle's "
                                        "project-level value mapping could not "
                                        f"be loaded: {exc}"
                                    ),
                                }
                            )
                        else:
                            if current_value_mapping_fp != sc_value_mapping_fp:
                                identity_check_failed = True
                                official_blocking_reasons.append(
                                    {
                                        "artefact_type": "scenario",
                                        "artefact_id": sc.get(
                                            "name", f"scenario_{idx}"
                                        ),
                                        "reason": (
                                            "value_mapping_identity_mismatch: "
                                            "this scenario's saved value-mapping "
                                            "fingerprint does not match this "
                                            "bundle's project-level value "
                                            "mapping."
                                        ),
                                    }
                                )

                if identity_check_failed:
                    officially_resumable = False
                    continue

                # Build per-scenario validation context
                try:
                    val_context = validation_context_from_legacy_args(
                        model_run_id=imported.get("model_run_id", ""),
                        model_approval_fingerprint=verified_model_approval_fingerprint,
                        data_fingerprint=current_data_fp,
                        model_spec_fingerprint=current_spec_fp,
                        posterior_fingerprint=current_posterior_fp,
                        planning_objective=sc_po,
                        outcome_definitions=current_outcome_defns,
                        outcome_approvals=current_outcome_appr,
                        counterfactual_fingerprint=sc_cf_fp or "unverifiable",
                        currency_context_fingerprint=sc_currency_fp,
                        value_mapping_fingerprint=sc_value_mapping_fp,
                    )
                except ValueError as exc:
                    officially_resumable = False
                    official_blocking_reasons.append(
                        {
                            "artefact_type": "scenario",
                            "artefact_id": sc.get("name", f"scenario_{idx}"),
                            "reason": f"incomplete_validation_context: {exc}",
                        }
                    )
                    continue
                issues = validate_scenario_dependencies(sc, context=val_context)
                for issue in issues:
                    officially_resumable = False
                    official_blocking_reasons.append(
                        {
                            "artefact_type": "scenario",
                            "artefact_id": sc.get("name", f"scenario_{idx}"),
                            "outcome_id": "",
                            "required_use": "",
                            "reason": f"{issue.reason_code or issue.issue_type}: {issue.detail}",
                        }
                    )

    # REQ-GRAPH-001 work package (graph portability): a fit that used an
    # approved causal graph (FHModelMeta.causal_graph_structural_fingerprint,
    # "graph authority and fitted identity") must have that exact graph
    # identity recoverable from this same bundle's causal_graphs.json - a
    # fitted/approved model whose authoritative structural input cannot be
    # verified fails closed here rather than silently being treated as if no
    # graph was ever used. Unconditional on `declared`: even a bare "fitted"
    # bundle's identity is unverifiable if its graph evidence is missing.
    meta_dict = imported.get("model_meta") or {}
    fit_time_graph_fingerprint = meta_dict.get("causal_graph_structural_fingerprint")
    if fit_time_graph_fingerprint:
        from .causal_graph import CausalGraph

        resolved_graphs, graph_warnings = resolve_imported_causal_graphs(imported)
        warnings.extend(graph_warnings)
        matching_graph = next(
            (
                g
                for g in resolved_graphs
                if CausalGraph.from_dict(g).structural_fingerprint()
                == fit_time_graph_fingerprint
            ),
            None,
        )
        if matching_graph is None:
            officially_resumable = False
            official_blocking_reasons.append(
                {
                    "artefact_type": "causal_graph",
                    "artefact_id": meta_dict.get("causal_graph_id", "<unknown>"),
                    "reason": (
                        "causal_graph_evidence_missing: this fit's bound "
                        f"structural fingerprint {fit_time_graph_fingerprint!r} "
                        "has no matching causal graph record in this bundle's "
                        "causal_graphs.json - the authoritative structural "
                        "input for this fit cannot be verified."
                    ),
                }
            )

    return {
        "resumable": not missing,
        "officially_resumable": officially_resumable,
        "outcome_governance_warnings": outcome_governance_warnings,
        "official_blocking_reasons": official_blocking_reasons,
        "checkpoint": declared,
        "missing_required": missing,
        "warnings": warnings,
        "schema_version": manifest.get("schema_version"),
    }


def reconstruct_model_state(imported: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given the dict returned by import_project(), re-derive the model
    artefacts that aren't directly serialised in the bundle - the modelling
    frame and posterior parameters - from what is: transformed_data +
    model_spec + outcome_definitions (frame; no MCMC involved, just the
    same pandas/numpy prep fit uses) and trace + model_meta (posterior
    params; posterior summarisation, not re-sampling). Doesn't require or
    trigger a re-fit.

    The frame is rebuilt from the *same* outcome catalogue the original fit
    used - `resolve_outcome_definitions(imported.get("outcome_definitions"),
    ...)`, the identical derivation `pages/04_Model_Config.py` uses when
    first preparing a frame - filtered to outcomes whose `source_column` is
    actually present in `transformed_data` (the same defensive filtering
    the old DNA-kit-only version of this function did, now applied to the
    whole catalogue since any outcome, not just a DNA one, could in
    principle reference a column that's since vanished). `included_in_fit`
    (persisted on each `OutcomeDefinition` - PR E) is respected exactly as
    any other fit would respect it, via `prepare_fh_modeling_frame`'s own
    `included_outcomes()` filtering - unlike the pre-PR-E `excluded_outcome_ids`
    mechanism this replaces, a reimport now reconstructs the *exact* set of
    outcomes that were included at fit time, not "every mapped DNA outcome
    regardless of exclusions in effect when the project was saved".

    Returns {"frame": ..., "model_meta": ..., "posterior_params": ...},
    with any entry left None if its inputs are missing or inconsistent
    (never raises - callers decide what an incomplete reconstruction means).
    """
    result: Dict[str, Any] = {
        "frame": None,
        "model_meta": None,
        "posterior_params": None,
    }

    if imported.get("model_meta") is not None:
        try:
            meta_dict = dict(imported["model_meta"])
            # outcome_catalogue_at_fit round-trips through JSON as plain
            # dicts (asdict() on export, json.loads() on import) - restore
            # OutcomeDefinition instances so any caller treating this field
            # as the catalogue it documents itself as gets real objects,
            # not dicts, after a reimport.
            if meta_dict.get("outcome_catalogue_at_fit"):
                from .outcomes import OutcomeDefinition

                meta_dict["outcome_catalogue_at_fit"] = [
                    OutcomeDefinition.from_dict(o)
                    for o in meta_dict["outcome_catalogue_at_fit"]
                ]
            if meta_dict.get("pathway_catalogue_at_fit"):
                from .pathways import MediaOutcomePathway

                meta_dict["pathway_catalogue_at_fit"] = [
                    MediaOutcomePathway.from_dict(p)
                    for p in meta_dict["pathway_catalogue_at_fit"]
                ]
            result["model_meta"] = FHModelMeta(**meta_dict)
        except TypeError:
            result["model_meta"] = None

    if (
        imported.get("transformed_data") is not None
        and imported.get("model_spec") is not None
    ):
        try:
            # Local import: `ancestry_mmm.data.preprocessor` imports `ancestry_mmm.core.schema`
            # at module level, so importing it at module level here would close a
            # circular dependency whenever `ancestry_mmm.data` is the first of the two
            # packages a caller imports (see e.g. any pages/*.py that import
            # `ancestry_mmm.data` before `ancestry_mmm.core`).
            from ..data.preprocessor import prepare_fh_modeling_frame
            from .outcomes import resolve_outcome_definitions

            spec = ModelSpec.from_dict(imported["model_spec"])
            transformed_data = imported["transformed_data"]
            outcome_definitions = resolve_outcome_definitions(
                imported.get("outcome_definitions"),
                spec.segment_outcomes,
                spec.segment_ltv,
            )
            available_columns = set(transformed_data.columns)
            usable_outcomes = [
                o for o in outcome_definitions if o.source_column in available_columns
            ]
            result["frame"] = prepare_fh_modeling_frame(
                transformed_data, spec, outcomes=usable_outcomes
            )
        except (ValueError, KeyError):
            result["frame"] = None

    if imported.get("trace") is not None and result["model_meta"] is not None:
        try:
            if imported.get("model_type") == "market_specific":
                # Local import: mirrors the prepare_fh_modeling_frame import above -
                # avoids a module-level circular import between core and data.
                from .market_specific_predict import (
                    extract_market_specific_posterior_params,
                )

                result["posterior_params"] = extract_market_specific_posterior_params(
                    imported["trace"], result["model_meta"]
                )
            else:
                result["posterior_params"] = extract_posterior_params(
                    imported["trace"], result["model_meta"]
                )
        except (KeyError, ValueError):
            result["posterior_params"] = None

    return result


def current_model_identity_fingerprints(
    imported: Dict[str, Any],
    reconstructed: Dict[str, Any],
) -> Tuple[str, str, str]:
    """Recompute the current (data, model-spec, posterior) identity
    fingerprints from a `reconstruct_model_state(imported)` result - the
    same recipe `verify_imported_approval` uses to check an approval, shared
    here so `audit_project_resumability` can validate a scenario's saved
    `model_approval_fingerprint` against the bundle's *actual* reconstructed
    model, not the approval's own self-reported fields (G2A.7a.10 - the
    latter would make the check tautological, always "matching" whatever
    the approval itself claims).

    Callers must check `reconstructed["frame"]`/`reconstructed["posterior_params"]`
    are not None before calling this - it assumes reconstruction succeeded.
    """
    from .coverage import (
        VariableCoverageMatrix,
        current_variable_coverage_matrix_from_resolved_versions,
    )
    from .search_objects import search_object_fit_fingerprint

    frame = reconstructed["frame"]
    posterior_params = reconstructed["posterior_params"]
    model_meta = reconstructed.get("model_meta")
    data_fp = fingerprint_dataframe(frame["df"])
    # Fingerprint the exact outcome catalogue this model was fit against
    # (model_meta.outcome_catalogue_at_fit, restored to OutcomeDefinition
    # instances by reconstruct_model_state), not the imported project's
    # *current* outcome_definitions - those can differ (e.g. re-edited on
    # Structure page since the fit) and would make a verified-valid approval
    # wrongly appear mismatched, or a genuinely stale one wrongly appear to
    # still match.
    outcome_catalogue_at_fit = (
        getattr(model_meta, "outcome_catalogue_at_fit", None) or []
    )
    # funnel_links/media_outcome_pathways: fingerprint the fit-time pathway
    # catalogue the same way outcome_catalogue is fingerprinted above (the
    # exact catalogue this fit's metadata was captured from, not the
    # project's current, possibly-since-edited one) - funnel_links has no
    # fit-time snapshot field, so the imported bundle's own funnel_links.json
    # is used directly (it is diagnostic-only configuration, never something
    # a fit is "built from").
    pathway_catalogue_at_fit = (
        getattr(model_meta, "pathway_catalogue_at_fit", None) or []
    )
    # REQ-COVERAGE-001 S5: the imported bundle's own coverage-matrix history
    # (quarantine-checked, mirroring how search_objects/causal_graphs are
    # never trusted un-validated), reduced to the single current version the
    # same way the Data Coverage/Project Export pages derive "current" from
    # "every saved version" - see current_variable_coverage_matrix_from_
    # resolved_versions's docstring.
    _resolved_coverage_matrices, _ = resolve_imported_variable_coverage_matrices(
        imported
    )
    current_coverage_matrix_dict = (
        current_variable_coverage_matrix_from_resolved_versions(
            _resolved_coverage_matrices
        )
    )
    spec_fp = fingerprint_model_spec(
        imported.get("model_spec") or {},
        imported.get("prior_config") or {},
        imported.get("dna_lag_weeks", 4),
        model_type=imported.get("model_type", "shared"),
        pipeline_steps=imported.get("pipeline_steps") or [],
        market_spec_config=imported.get("market_spec_config"),
        direct_dna_outcome_ids=model_meta.direct_dna_outcome_ids
        if model_meta is not None
        else None,
        outcome_catalogue=outcome_catalogue_fingerprint_payload(
            outcome_catalogue_at_fit
        ),
        funnel_links=imported.get("funnel_links"),
        media_outcome_pathways=pathway_catalogue_fingerprint_payload(
            pathway_catalogue_at_fit
        ),
        activity_fit_fingerprint=(
            activity_fit_fingerprint(imported["activity_definitions"])
            if imported.get("activity_definitions")
            else None
        ),
        search_object_fit_fingerprint=(
            search_object_fit_fingerprint(
                imported["search_objects"],
                consumed_model_input_columns=(imported.get("model_spec") or {}).get(
                    "channels"
                )
                or [],
            )
            if imported.get("search_objects")
            else None
        ),
        variable_coverage_fingerprint=(
            VariableCoverageMatrix.from_dict(current_coverage_matrix_dict).fingerprint()
            if current_coverage_matrix_dict
            else None
        ),
    )
    posterior_fp = fingerprint_posterior(posterior_params)
    return data_fp, spec_fp, posterior_fp


def verify_imported_approval(
    imported: Dict[str, Any],
    reconstructed: Dict[str, Any],
    *,
    current_policy: Optional["ThresholdPolicy"] = None,
    approval_readiness: Optional["ApprovalReadiness"] = None,
) -> Tuple[Optional[ModelApproval], str]:
    """
    Decide whether an imported project's approval is still valid against its
    (reconstructed) model artefacts. Never silently accepts or discards a
    mismatch: always returns an explanatory message alongside the verdict,
    for the caller to show the user. Returns (None, reason) when the
    approval should NOT be treated as valid; (approval, reason) when it is
    verified.

    `imported` is an import_project() result; `reconstructed` is a
    reconstruct_model_state(imported) result.

    PR 88A: `current_policy`/`approval_readiness` should be the caller's
    already-verified policy and readiness for this same bundle (e.g. from
    `application.project_service.verify_imported_readiness`) - passed
    through to `require_matching_approval` so a *policy-backed* approval is
    checked against the full chain (policy active, readiness overall_ready,
    every fingerprint binding matches), not model identity alone. Previously
    this function only checked `matches_current_model()`, so a policy-backed
    approval whose readiness had just been rejected as unverified could
    still come back "verified" here on identity alone. Both parameters
    default to `None`, which preserves the original identity-only behaviour
    for legacy/unbound approvals (`require_matching_approval` only consults
    them when the approval itself references a `validation_policy_id`).
    """
    approval_dict = imported.get("model_approval")
    if approval_dict is None:
        return None, "No approval was included in this project bundle."

    approval = ModelApproval.from_dict(approval_dict)
    if not approval.is_model_bound():
        return None, (
            "The imported approval predates model-bound approval (no run ID or "
            "fingerprints were recorded) - treated as unverified. The model must be "
            "reviewed and approved again."
        )

    frame = reconstructed.get("frame")
    posterior_params = reconstructed.get("posterior_params")
    if frame is None or posterior_params is None:
        return None, (
            "Could not reconstruct this project's model artefacts (data, specification "
            "or posterior) well enough to verify its approval - treated as unverified. "
            "The model must be reviewed and approved again."
        )

    data_fp, spec_fp, posterior_fp = current_model_identity_fingerprints(
        imported, reconstructed
    )
    current_run_id = imported.get("model_run_id") or approval.model_run_id

    try:
        require_matching_approval(
            approval,
            model_run_id=current_run_id,
            data_fingerprint=data_fp,
            model_spec_fingerprint=spec_fp,
            posterior_fingerprint=posterior_fp,
            approval_readiness=approval_readiness,
            current_policy=current_policy,
        )
    except ApprovalMismatchError:
        return None, (
            "The imported approval does not match the imported model artefacts (data, "
            "specification, or posterior differ) - the model must be reviewed and approved again."
        )
    except ValidationPolicyBlockedError as exc:
        return None, (
            "The imported approval is policy-backed, but its validation policy or "
            f"readiness evidence is not currently valid: {exc} The bundle's technical "
            "artefacts remain loadable, but this approval cannot be treated as current "
            "official authority until the model is reviewed and approved again."
        )

    return (
        approval,
        f"Imported approval verified: matches the imported model artefacts (approved by {approval.approved_by}).",
    )


def export_excel_summary(
    output_path: Path, sheets: Dict[str, Optional[pd.DataFrame]]
) -> Path:
    """
    Excel export of named summary sheets for stakeholders who consume Excel,
    not code. `sheets` maps a sheet name to its DataFrame - `None` or an
    empty DataFrame is skipped (so callers can pass every sheet they might
    have without checking emptiness themselves). Sheet names are truncated
    to Excel's 31-character limit.

    Deliberately generic rather than fixed named parameters (curve bank /
    total FH / segment x channel) - Model A and Model C summaries share
    almost none of the same sheets (docs/decision_log.md: Shapley
    attribution is Model-A-only), so a fixed signature would force one
    model type's callers to pass `None` for sheets that make no sense for
    them.
    """
    output_path = Path(output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=name[:31], index=False)
    return output_path
