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
import shutil
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import arviz as az

from .approval import ModelApproval
from .fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from .hierarchical_model import FHModelMeta
from .outcomes import outcome_catalogue_fingerprint_payload
from .pathways import pathway_catalogue_fingerprint_payload
from .predict import extract_posterior_params
from .schema import ModelSpec
from .optimization import SpendConstraint

PROJECT_BUNDLE_SCHEMA_VERSION = 4
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
) -> Path:
    output_path = Path(output_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
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
                "approval": model_approval is not None,
                "scenarios": bool(scenarios),
                "notes": bool(notes),
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
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
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
        if (config_dir / "scenarios.json").exists():
            scenarios_meta = json.loads((config_dir / "scenarios.json").read_text())
            for i, s in enumerate(scenarios_meta):
                pred_path = tmp / "scenarios" / f"scenario_{i}_predicted.csv"
                if pred_path.exists():
                    s["predicted"] = pd.read_csv(pred_path)
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


def audit_project_resumability(imported: Dict[str, Any]) -> Dict[str, Any]:
    """Audit whether an imported bundle can resume its declared checkpoint.

    Legacy bundles remain importable; they report a migration warning rather
    than being treated as corrupt. Required artefacts grow with the furthest
    checkpoint actually represented by the bundle.
    """
    manifest = imported.get("manifest") or {}
    declared = manifest.get("workflow_checkpoint")
    if not declared or declared == "unknown":
        if imported.get("scenarios"):
            declared = "scenarios"
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
            return bool(
                value or imported.get("curve_bank_binary_files")
            )
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
    return {
        "resumable": not missing,
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


def verify_imported_approval(
    imported: Dict[str, Any],
    reconstructed: Dict[str, Any],
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
    )
    posterior_fp = fingerprint_posterior(posterior_params)
    current_run_id = imported.get("model_run_id") or approval.model_run_id

    if approval.matches_current_model(
        model_run_id=current_run_id,
        data_fingerprint=data_fp,
        model_spec_fingerprint=spec_fp,
        posterior_fingerprint=posterior_fp,
    ):
        return (
            approval,
            f"Imported approval verified: matches the imported model artefacts (approved by {approval.approved_by}).",
        )

    return None, (
        "The imported approval does not match the imported model artefacts (data, "
        "specification, or posterior differ) - the model must be reviewed and approved again."
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
