"""
Project export/import: a downloadable, re-importable project bundle so an
analyst can pause and resume work without a live server session.

Bundle layout (a single zip):
    data/raw_<source>.parquet          - each raw source, as uploaded
    data/transformed.parquet           - post-pipeline data
    config/pipeline_steps.json         - ordered transform steps
    config/model_spec.json             - ModelSpec
    config/prior_config.json           - prior overrides + dna_lag_weeks
    config/model_approval.json         - ModelApproval, if the trained model has been approved
    config/scenarios.json              - scenario definitions (spend plan, constraints)
    scenarios/scenario_<i>_predicted.csv
    model/trace.nc                     - fitted posterior (ArviZ InferenceData, NetCDF)
    curve_bank/*.json                  - curve bank + calibration records, if any

Session state (Streamlit) is never the system of record - this bundle is.
No proprietary format: Parquet, JSON and NetCDF are all open, and readable
without this app (pandas.read_parquet, json, arviz.from_netcdf).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import arviz as az

from .schema import ModelSpec
from .optimization import SpendConstraint


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
) -> Path:
    output_path = Path(output_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "data").mkdir()
        (tmp / "config").mkdir()
        (tmp / "scenarios").mkdir()

        for name, df in raw_sources.items():
            df.to_parquet(tmp / "data" / f"raw_{name}.parquet", index=False)
        if transformed_data is not None:
            transformed_data.to_parquet(tmp / "data" / "transformed.parquet", index=False)

        (tmp / "config" / "pipeline_steps.json").write_text(json.dumps(pipeline_steps, indent=2))
        if model_spec is not None:
            (tmp / "config" / "model_spec.json").write_text(json.dumps(model_spec, indent=2, default=str))
        (tmp / "config" / "prior_config.json").write_text(
            json.dumps({"prior_config": prior_config or {}, "dna_lag_weeks": dna_lag_weeks}, indent=2)
        )
        if model_approval is not None:
            (tmp / "config" / "model_approval.json").write_text(json.dumps(model_approval, indent=2, default=str))

        scenarios_meta = []
        for i, s in enumerate(scenarios):
            meta = {k: v for k, v in s.items() if k != "predicted"}
            if "constraints" in meta:
                meta["constraints"] = [
                    c.to_dict() if isinstance(c, SpendConstraint) else c for c in meta["constraints"]
                ]
            scenarios_meta.append(meta)
            if "predicted" in s and isinstance(s["predicted"], pd.DataFrame):
                s["predicted"].to_csv(tmp / "scenarios" / f"scenario_{i}_predicted.csv", index=False)
        (tmp / "config" / "scenarios.json").write_text(json.dumps(scenarios_meta, indent=2, default=str))

        if trace is not None:
            (tmp / "model").mkdir()
            trace.to_netcdf(str(tmp / "model" / "trace.nc"))

        if curve_bank_source_dir is not None and Path(curve_bank_source_dir).exists():
            shutil.copytree(curve_bank_source_dir, tmp / "curve_bank")

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
        "raw_sources": {}, "transformed_data": None, "pipeline_steps": [],
        "model_spec": None, "prior_config": {}, "dna_lag_weeks": 4,
        "trace": None, "scenarios": [], "model_approval": None,
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract_zip(zf, tmp)

        data_dir = tmp / "data"
        if data_dir.exists():
            for f in data_dir.glob("raw_*.parquet"):
                name = f.stem[len("raw_"):]
                result["raw_sources"][name] = pd.read_parquet(f)
            transformed_path = data_dir / "transformed.parquet"
            if transformed_path.exists():
                result["transformed_data"] = pd.read_parquet(transformed_path)

        config_dir = tmp / "config"
        if (config_dir / "pipeline_steps.json").exists():
            result["pipeline_steps"] = json.loads((config_dir / "pipeline_steps.json").read_text())
        if (config_dir / "model_spec.json").exists():
            result["model_spec"] = json.loads((config_dir / "model_spec.json").read_text())
        if (config_dir / "prior_config.json").exists():
            prior_data = json.loads((config_dir / "prior_config.json").read_text())
            result["prior_config"] = prior_data.get("prior_config", {})
            result["dna_lag_weeks"] = prior_data.get("dna_lag_weeks", 4)
        if (config_dir / "model_approval.json").exists():
            result["model_approval"] = json.loads((config_dir / "model_approval.json").read_text())
        if (config_dir / "scenarios.json").exists():
            scenarios_meta = json.loads((config_dir / "scenarios.json").read_text())
            for i, s in enumerate(scenarios_meta):
                pred_path = tmp / "scenarios" / f"scenario_{i}_predicted.csv"
                if pred_path.exists():
                    s["predicted"] = pd.read_csv(pred_path)
            result["scenarios"] = scenarios_meta

        trace_path = tmp / "model" / "trace.nc"
        if trace_path.exists():
            result["trace"] = az.from_netcdf(str(trace_path))

        curve_bank_path = tmp / "curve_bank"
        if curve_bank_path.exists():
            result["curve_bank_files"] = {
                f.name: f.read_text() for f in curve_bank_path.glob("*.json")
            }

    return result


def export_excel_summary(
    output_path: Path,
    curve_bank_entries_df: Optional[pd.DataFrame],
    total_fh_df: Optional[pd.DataFrame],
    segment_channel_df: Optional[pd.DataFrame],
) -> Path:
    """Excel export of curve bank + contribution summaries for stakeholders who consume Excel, not code."""
    output_path = Path(output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        if total_fh_df is not None:
            total_fh_df.to_excel(writer, sheet_name="Total FH Contribution", index=False)
        if segment_channel_df is not None:
            segment_channel_df.to_excel(writer, sheet_name="Segment x Channel", index=False)
        if curve_bank_entries_df is not None and not curve_bank_entries_df.empty:
            curve_bank_entries_df.to_excel(writer, sheet_name="Curve Bank", index=False)
    return output_path
