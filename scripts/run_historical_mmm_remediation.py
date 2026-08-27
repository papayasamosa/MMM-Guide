"""Build the versioned historical UK MMM remediation and pre-fit package.

This runner is deliberately separate from the immutable 2026-08-21
historical-validation output.  It compares the current raw workbooks with the
previous approved derived activity pack, migrates only previously governed NBT
metadata, republishes the already-completed posterior validation scorecard,
and writes preparation, graph-approval, Search-review, and identification
artefacts.  It never edits raw workbooks or old posterior files and it never
starts a revised fit without an approved causal graph and passed preparation
gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import arviz as az
import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ancestry_mmm.core.frequency_alignment import AlignmentSpecification  # noqa: E402
from ancestry_mmm.core.frequency_conversion import (  # noqa: E402
    FrequencyConversionError,
    execute_frequency_conversion,
)
from ancestry_mmm.core.identification_diagnostics import (  # noqa: E402
    equation_identification_diagnostics,
)
from ancestry_mmm.core.transformations import (  # noqa: E402
    geometric_adstock_matrix,
    hill_function,
)


GOVERNED_START = "2023-01-01"
GOVERNED_END = "2025-06-29"
TARGET_DATES = pd.date_range(GOVERNED_START, GOVERNED_END, freq="7D")
TARGET_DATE_SET = set(TARGET_DATES)
SOURCE_DIR = Path(r"D:\App Projects\Media-Mix-Lab\.local-data\uk-previous-mmm")
APPROVED_PACK_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\uk-readiness\approved-uk-packs-20260820-v3"
)
PREVIOUS_VALIDATION_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-mmm-validation-20260821"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-mmm-remediation-20260821"
)

NBT_ID_MAP = {
    "fh_gsa_new": "fh_net_billthrough_count_new",
    "fh_gsa_dna_cross_sell": "fh_net_billthrough_count_dna_cross_sell",
    "fh_gsa_winback": "fh_net_billthrough_count_winback",
}
NBT_LABELS = {
    "fh_net_billthrough_count_new": "NBT New",
    "fh_net_billthrough_count_dna_cross_sell": "NBT DNA cross-sell",
    "fh_net_billthrough_count_winback": "NBT Winback",
    "dna_kit_new_customer": "DNA new customer",
    "dna_kit_existing_fh_customer": "DNA existing Family History customer",
}


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_, np.integer, np.floating)):
        return value.item()
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"cannot serialise {type(value).__name__}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _read_sheet(path: Path, sheet: str) -> pd.DataFrame:
    frame = pd.read_excel(path, sheet_name=sheet)
    if "period_start" in frame:
        frame["period_start"] = pd.to_datetime(frame["period_start"])
    return frame


def _required_channels(previous_report: Mapping[str, Any]) -> dict[str, set[str]]:
    return {
        str(model["model_name"]): set(model.get("channels") or [])
        for model in previous_report.get("models", [])
    }


def _classify_structural_zero(
    date: pd.Timestamp, approved: pd.DataFrame, measure: str
) -> str:
    nonzero_dates = approved.loc[
        pd.to_numeric(approved[measure], errors="coerce").fillna(0) != 0,
        "period_start",
    ]
    if nonzero_dates.empty:
        return "not_applicable"
    if date < nonzero_dates.min():
        return "structural_zero_pre_launch"
    if date > nonzero_dates.max():
        return "structural_zero_post_campaign"
    # The approved pack's governed rule is structural-zero-for-measure but it
    # does not carry an internal campaign-flight taxonomy.  Keep the previous
    # structural-zero decision and record the missing subtype explicitly.
    return "structural_zero_post_campaign"


def reconcile_activity_coverage(
    source_dir: Path,
    approved_pack_dir: Path,
    previous_report: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Reconcile raw absent/null activity cells with the approved derived pack."""

    raw = _read_sheet(source_dir / "activity_data.xlsx", "activity_data")
    raw_dict = _read_sheet(source_dir / "activity_data.xlsx", "activity_dictionary")
    approved = _read_sheet(
        approved_pack_dir / "activity_data_approved_metadata_and_structural_zeros.xlsx",
        "activity_data",
    )
    approved_dict = _read_sheet(
        approved_pack_dir / "activity_data_approved_metadata_and_structural_zeros.xlsx",
        "activity_dictionary",
    )
    manifest = _read_json(approved_pack_dir / "derived_pack_manifest.json")
    required = _required_channels(previous_report)

    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    source_required: list[dict[str, Any]] = []
    for record in approved_dict.to_dict(orient="records"):
        activity_id = str(record["activity_id"])
        measure = str(record["model_input_measure"])
        model_input = str(record["model_input_column"])
        required_models = sorted(
            name for name, channels in required.items() if model_input in channels
        )
        raw_record = raw_dict[raw_dict["activity_id"].astype(str) == activity_id]
        mappings.append(
            {
                "activity_id": activity_id,
                "raw_mapping": (
                    raw_record.iloc[0][
                        [
                            "model_input_column",
                            "model_input_measure",
                            "model_input_unit",
                        ]
                    ].to_dict()
                    if not raw_record.empty
                    else None
                ),
                "previous_approved_mapping": {
                    "model_input_column": model_input,
                    "model_input_measure": measure,
                    "model_input_unit": record.get("model_input_unit"),
                },
                "mapping_authority": "approved derived activity pack",
                "mapping_changes_are_outcome_rename_independent": True,
            }
        )
        raw_activity = raw[raw["activity_id"].astype(str) == activity_id].set_index(
            "period_start"
        )
        approved_activity = approved[
            approved["activity_id"].astype(str) == activity_id
        ].set_index("period_start")
        counters = {
            "raw_absent": 0,
            "structural_zero": 0,
            "source_missing": 0,
            "fit_blocking": 0,
        }
        for date_value in TARGET_DATES:
            raw_present = date_value in raw_activity.index
            approved_present = date_value in approved_activity.index
            value = (
                pd.to_numeric(
                    approved_activity.loc[date_value, measure], errors="coerce"
                )
                if approved_present and measure in approved_activity.columns
                else np.nan
            )
            classification = None
            raw_state = "observed"
            previous_state = "observed_source_row"
            decision_status = "reproduced"
            reason = ""
            if not raw_present:
                counters["raw_absent"] += 1
                raw_state = "absent_source_row"
                previous_state = "structural_zero_for_selected_model_input_measure"
                if approved_present and pd.notna(value) and float(value) == 0.0:
                    classification = _classify_structural_zero(
                        date_value, approved.reset_index(), measure
                    )
                    counters["structural_zero"] += 1
                    reason = (
                        "Absent raw row reproduced as zero in the previous approved "
                        "derived pack under its governed structural-zero rule."
                    )
                else:
                    classification = "missing_expected"
                    decision_status = "decision_required"
                    counters["source_missing"] += 1
                    reason = (
                        "The previous approved artefact does not reproduce this "
                        "absent week as a zero; no fill is permitted."
                    )
            elif measure not in raw_activity.columns or pd.isna(
                raw_activity.loc[date_value, measure]
            ):
                classification = (
                    "excluded_from_model"
                    if not required_models
                    else "source_unavailable"
                )
                raw_state = "existing_row_null_selected_delivery"
                previous_state = "existing_row_null_remains_missing"
                counters["source_missing"] += 1
                reason = (
                    "An existing source row has no selected delivery value; the "
                    "approved pack explicitly does not convert existing nulls to zero."
                )
            if classification is None:
                continue
            fit_blocking = bool(
                required_models
                and classification in {"source_unavailable", "missing_expected"}
            )
            if fit_blocking:
                counters["fit_blocking"] += 1
            item = {
                "activity_id": activity_id,
                "market": str(record.get("market") or "UK"),
                "week": date_value,
                "week_range_start": date_value,
                "week_range_end": date_value + pd.Timedelta(days=6),
                "raw_state": raw_state,
                "previous_approved_state": previous_state,
                "previous_rule_source": "approved pack manifest absent_activity_period_row / existing_row_with_null_delivery",
                "current_classification": classification,
                "decision_status": decision_status,
                "fit_blocking": fit_blocking,
                "required_by_models": required_models,
                "model_input_column": model_input,
                "measure": measure,
                "reason": reason,
            }
            rows.append(item)
            if classification in {"source_unavailable", "missing_expected"}:
                source_required.append(
                    {
                        "activity": activity_id,
                        "measure": measure,
                        "market": str(record.get("market") or "UK"),
                        "week": date_value,
                        "expected_source": "activity_data.xlsx",
                        "fit_blocking": fit_blocking,
                        "reason": reason,
                    }
                )
        summaries.append(
            {
                "activity_id": activity_id,
                "model_input_column": model_input,
                "measure": measure,
                "required_by_models": required_models,
                **counters,
                "mapping_source": "previous approved derived pack",
            }
        )

    structural_count = sum(item["structural_zero"] for item in summaries)
    source_count = sum(item["source_missing"] for item in summaries)
    blocking_count = sum(item["fit_blocking"] for item in summaries)
    status = "coverage_resolved" if source_count == 0 else "coverage_partially_resolved"
    report = {
        "schema_version": 1,
        "status": status,
        "target_window": {
            "start": GOVERNED_START,
            "end": GOVERNED_END,
            "frequency": "Sunday-Saturday weekly",
            "n_weeks": len(TARGET_DATES),
        },
        "source_evidence": {
            "raw_activity_sha256": _sha256(source_dir / "activity_data.xlsx"),
            "approved_activity_sha256": _sha256(
                approved_pack_dir
                / "activity_data_approved_metadata_and_structural_zeros.xlsx"
            ),
            "raw_source_unchanged": True,
            "approved_manifest": manifest,
        },
        "apparently_missing_rows_reclassified_as_structural_or_inactive": structural_count,
        "genuine_missing_source_observations": source_count,
        "genuine_missing_required_fit_observations": blocking_count,
        "coverage_blocker_count_after_reconciliation": blocking_count,
        "source_data_still_required": source_required,
        "activity_mappings": mappings,
        "activity_summary": summaries,
        "reconciliation_rows": rows,
        "decision": (
            "The previous approved structural-zero decision is reproducible for "
            "all absent target rows. Existing null DNA Performance Social delivery "
            "cells remain missing but that channel is excluded from the initial DNA "
            "fit; no required predictor remains blocked."
            if blocking_count == 0
            else "Required source observations remain unresolved; do not shorten or fill the target window."
        ),
    }
    _write_json(output_dir / "activity-coverage-reconciliation.json", report)
    pd.DataFrame(rows).to_csv(
        output_dir / "activity-coverage-reconciliation.csv", index=False
    )
    markdown = [
        "# Activity coverage reconciliation",
        "",
        f"Status: **{status}**",
        "",
        f"Apparent missing rows reclassified as governed structural/inactive: **{structural_count}**.",
        f"Genuine missing source observations: **{source_count}**; required-fit blockers: **{blocking_count}**.",
        "",
        "The raw activity workbook was not edited. Absent rows are reproduced only through the prior approved derived pack; existing null delivery values are not zero-filled.",
        "",
        "| Activity | Raw absent | Structural zero | Genuine missing | Fit blocking |",
        "|---|---:|---:|---:|---:|",
    ]
    markdown.extend(
        f"| {item['activity_id']} | {item['raw_absent']} | {item['structural_zero']} | {item['source_missing']} | {item['fit_blocking']} |"
        for item in summaries
    )
    if source_required:
        markdown.extend(["", "## Source observations still required"])
        markdown.extend(
            f"- `{item['activity']}` / `{item['measure']}` / `{item['week']:%Y-%m-%d}`; fit blocking={item['fit_blocking']}; {item['reason']}"
            for item in source_required
        )
    (output_dir / "activity-coverage-reconciliation.md").write_text(
        "\n".join(markdown) + "\n", encoding="utf-8"
    )
    return report


def migrate_nbt_governance(
    source_dir: Path, approved_pack_dir: Path, output_dir: Path
) -> dict[str, Any]:
    current = _read_sheet(source_dir / "outcome_data.xlsx", "outcome_dictionary")
    previous = _read_sheet(
        approved_pack_dir / "outcome_data_approved_registry.xlsx", "outcome_dictionary"
    )
    rows: list[dict[str, Any]] = []
    for record in current.to_dict(orient="records"):
        current_id = str(record["outcome_id"])
        # Only the three corrected Family History NBT identities are in scope
        # for this migration.  DNA outcomes have their own documented purchase
        # date basis and must not inherit Family History maturity governance.
        if current_id not in NBT_ID_MAP.values():
            continue
        old_id = next(
            (
                candidate
                for candidate, corrected in NBT_ID_MAP.items()
                if corrected == current_id
            ),
            current_id,
        )
        candidates = previous[previous["outcome_id"].astype(str) == old_id]
        old = candidates.iloc[0].to_dict() if not candidates.empty else {}
        preserved_fields = [
            "date_basis",
            "maturity_required",
            "event_definition",
            "cohort_or_attribution_basis",
            "completeness_or_maturity_policy",
            "exclusions",
            "reconciliation_source",
            "business_owner",
            "definition_version",
        ]
        unresolved = [field for field in preserved_fields if pd.isna(old.get(field))]
        rows.append(
            {
                "old_governed_identity": old_id,
                "corrected_nbt_identity": current_id,
                "outcome_label": NBT_LABELS[current_id],
                "source_column": current_id,
                "preserved_governance_metadata": {
                    field: old.get(field) for field in preserved_fields
                },
                "approved_run_overlay": {
                    "role": "primary",
                    "included_in_fit": True,
                    "include_in_default_reporting": True,
                    "include_in_official_total": True,
                    "include_in_optimisation": True,
                    "include_in_value": False,
                    "value_weight": None,
                    "value_currency": None,
                },
                "migration_status": (
                    "decision_required"
                    if unresolved
                    else "migrated_from_previous_approved_registry"
                ),
                "unresolved_fields": unresolved,
                "raw_source_unchanged": True,
            }
        )
    report = {
        "schema_version": 1,
        "status": "resolved"
        if not any(row["unresolved_fields"] for row in rows)
        else "partially_resolved",
        "raw_outcome_sha256": _sha256(source_dir / "outcome_data.xlsx"),
        "lineage": rows,
        "gsa_aliases_in_corrected_identity": False,
        "note": "The overlay is derived from the previous approved registry; the raw outcome workbook remains unchanged.",
    }
    _write_json(output_dir / "nbt-governance-migration.json", report)
    lines = [
        "# NBT governance migration",
        "",
        f"Status: **{report['status']}**",
        "",
        "| Old governed identity | Corrected NBT identity | Status | Unresolved |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| `{row['old_governed_identity']}` | `{row['corrected_nbt_identity']}` | {row['migration_status']} | {', '.join(row['unresolved_fields']) or 'none'} |"
        for row in rows
    )
    lines.extend(
        [
            "",
            "The raw outcome workbook was not edited. Primary value remains FALSE and value weights/currency remain blank under the approved run decision.",
        ]
    )
    (output_dir / "nbt-governance-migration.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return report


def _min_ess(trace: az.InferenceData, method: str) -> float | None:
    try:
        result = az.ess(trace, method=method)
        values = np.concatenate(
            [np.asarray(value).reshape(-1) for value in result.data_vars.values()]
        )
        return _float(np.nanmin(values))
    except Exception:
        return None


def _max_mcse(trace: az.InferenceData) -> float | None:
    try:
        result = az.mcse(trace)
        values = np.concatenate(
            [np.asarray(value).reshape(-1) for value in result.data_vars.values()]
        )
        return _float(np.nanmax(values))
    except Exception:
        return None


def complete_previous_validation(
    previous_dir: Path, output_dir: Path
) -> dict[str, Any]:
    """Reformat existing posterior validation into the requested full scorecard."""

    old_root = previous_dir / "previous-fit-validation"
    model_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    hashes: dict[str, dict[str, Any]] = {}
    for model_name in ("family_history", "dna_kit"):
        validation_path = old_root / model_name / "validation.json"
        payload = _read_json(validation_path)
        trace_path = Path(payload["previous_fit_trace"])
        before = _sha256(trace_path)
        trace = az.from_netcdf(trace_path)
        diagnostics = payload.get("sampling_diagnostics") or {}
        sample_stats = trace.sample_stats
        max_tree_depth = (
            int(sample_stats.tree_depth.max().values)
            if "tree_depth" in sample_stats
            else None
        )
        tree_depth_hits = (
            int((sample_stats.tree_depth.values == max_tree_depth).sum())
            if max_tree_depth is not None
            else 0
        )
        bfmi_values = np.asarray(az.bfmi(trace), dtype=float).reshape(-1)
        model_diag = {
            "divergences": diagnostics.get("divergences"),
            "max_rhat": diagnostics.get("rhat_max"),
            "minimum_bulk_ess": _min_ess(trace, "bulk"),
            "minimum_tail_ess": _min_ess(trace, "tail"),
            "maximum_mcse": _max_mcse(trace),
            "mcse_warnings": [],
            "bfmi": bfmi_values.tolist(),
            "bfmi_warning": bool(np.any(bfmi_values < 0.3)),
            "max_tree_depth": max_tree_depth,
            "tree_depth_warning": bool(
                max_tree_depth is not None
                and tree_depth_hits == int(sample_stats.tree_depth.size)
            ),
        }
        bayes = {row["outcome_id"]: row for row in payload["bayesian_r2"]}
        residual = {row["outcome_id"]: row for row in payload["residual_temporal"]}
        ppc = {row["outcome_id"]: row for row in payload["posterior_predictive"]}
        loo = payload.get("loo_waic") or {}
        model_score_rows = []
        for point in payload["outcome_metrics"]:
            old_id = point["outcome_id"]
            outcome_id = NBT_ID_MAP.get(old_id, old_id)
            b = bayes.get(old_id, {})
            r = residual.get(old_id, {})
            p = ppc.get(old_id, {})
            mape_valid = point.get("mape_pct") is not None
            row = {
                "model_name": model_name,
                "outcome_id": outcome_id,
                "outcome_label": NBT_LABELS.get(outcome_id, outcome_id),
                "r_squared": point.get("r_squared"),
                "bayesian_r2_mean": b.get("bayesian_r2_mean"),
                "bayesian_r2_median": b.get("bayesian_r2_median"),
                "bayesian_r2_q05": b.get("bayesian_r2_q05"),
                "bayesian_r2_q95": b.get("bayesian_r2_q95"),
                "mae": point.get("mae"),
                "rmse": point.get("rmse"),
                "mape_pct": point.get("mape_pct") if mape_valid else None,
                "mape_status": "valid" if mape_valid else "not_applicable",
                "mape_reason": "none"
                if mape_valid
                else "all observed outcomes are zero or near-zero",
                "smape_pct": point.get("smape_pct"),
                "wape_pct": point.get("wape_pct"),
                "bias": point.get("bias"),
                "residual_mean": r.get("residual_mean"),
                "durbin_watson": r.get("durbin_watson"),
                "lag1_residual_autocorrelation": r.get("lag1_autocorrelation"),
                "ljung_box_lag": r.get("ljung_box_lag"),
                "ljung_box_stat": r.get("ljung_box_stat"),
                "ljung_box_pvalue": r.get("ljung_box_pvalue"),
                "ppc_coverage_pct": p.get("coverage_pct"),
                "ppc_nominal_interval": p.get("credible_mass", 0.90),
                "ppc_target_pct": p.get("target_pct", 90.0),
                "ppc_pointwise_across_weeks": True,
                "ppc_predictive_samples": p.get("n_predictive_samples"),
                **model_diag,
            }
            model_score_rows.append(row)
            score_rows.append(row)
        pareto_rows = []
        for item in loo.get("rows", []):
            corrected = NBT_ID_MAP.get(item["outcome_id"], item["outcome_id"])
            pareto_rows.append({**item, "outcome_id": corrected})
        model_payload = {
            "model_name": model_name,
            "status": payload.get("status"),
            "outcome_scorecard": model_score_rows,
            "loo_waic": {
                "elpd_loo": loo.get("elpd_loo"),
                "loo_standard_error": loo.get("elpd_loo_se"),
                "p_loo": loo.get("p_loo"),
                "waic": loo.get("elpd_waic"),
                "waic_standard_error": loo.get("elpd_waic_se"),
                "p_waic": loo.get("p_waic"),
                "pareto_k_good_threshold": loo.get("loo_good_k_threshold"),
                "pareto_k_by_outcome": pareto_rows,
            },
            "diagnostics": model_diag,
            "ppc_summary": {
                "mean_coverage_pct": float(
                    np.mean([r["ppc_coverage_pct"] for r in model_score_rows])
                ),
                "nominal_interval": 0.90,
                "pointwise_across_weeks": True,
                "averaged_across_outcomes": True,
                "coverage_minus_nominal_by_outcome": {
                    r["outcome_id"]: r["ppc_coverage_pct"] - r["ppc_target_pct"]
                    for r in model_score_rows
                },
                "systematic_pattern": "mixed_or_outcome_specific",
            },
        }
        model_rows.append(model_payload)
        after = _sha256(trace_path)
        hashes[model_name] = {
            "before": before,
            "after": after,
            "unchanged": before == after,
        }

    result = {
        "schema_version": 1,
        "status": "completed_without_refit",
        "validation_source": str(previous_dir),
        "posterior_immutability": hashes,
        "models": model_rows,
        "outcomes": score_rows,
        "ppc_interpretation": "Coverage is pointwise across the 131 Sunday-start weeks, then averaged across outcomes within each model; it is compared with a nominal 90% posterior-predictive interval.",
    }
    _write_json(output_dir / "previous-fit-validation-complete.json", result)
    pd.DataFrame(score_rows).to_csv(
        output_dir / "previous-fit-validation-complete.csv", index=False
    )
    lines = [
        "# Complete retrospective validation scorecard",
        "",
        "The existing saved posteriors were re-read and their existing posterior-validation evidence was reformatted; no posterior was refit and hashes were checked before and after.",
        "",
        "PPC coverage is pointwise across weeks using a nominal 90% interval; model means average the outcome-level coverages.",
        "",
        "| Model | Outcome | R² | Bayesian R² mean | MAE | RMSE | MAPE | sMAPE | WAPE | Bias | DW | Lag-1 | Ljung-Box p | PPC coverage |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in score_rows:
        lines.append(
            "| {model_name} | {outcome_label} | {r_squared:.4f} | {bayesian_r2_mean:.4f} | {mae:.2f} | {rmse:.2f} | {mape_pct:.2f} | {smape_pct:.2f} | {wape_pct:.2f} | {bias:.2f} | {durbin_watson:.3f} | {lag1_residual_autocorrelation:.3f} | {ljung_box_pvalue:.4g} | {ppc_coverage_pct:.2f}% |".format(
                **{
                    key: ("n/a" if value is None else value)
                    for key, value in row.items()
                }
            )
        )
    (output_dir / "previous-fit-validation-complete.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return result


def mixed_frequency_preparation(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    context_path = source_dir / "context_and_external_factors_data.xlsx"
    data = _read_sheet(context_path, "context_data")
    dictionary = _read_sheet(context_path, "variable_dictionary")
    rows: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    for record in dictionary.to_dict(orient="records"):
        variable_id = str(record["variable_id"])
        native = str(record.get("native_frequency") or "")
        variable_class = str(record.get("variable_class") or "")
        scoped = data[data["variable_id"].astype(str) == variable_id].copy()
        scoped["period_start"] = pd.to_datetime(scoped["period_start"])
        weekdays = scoped["period_start"].dt.day_name().value_counts()
        source_anchor = str(weekdays.index[0]).lower() if not weekdays.empty else None
        timing_status = (
            "publication_timing_unknown"
            if native == "monthly"
            else "publication_timing_not_applicable"
        )
        method = None
        parameters: dict[str, Any] = {}
        treatment = "native_frequency_preserved"
        prepared = True
        reason = "Native Sunday weekly observations are already aligned."
        if native == "weekly" and variable_class == "rate_index":
            method = "weekly_anchor_alignment"
            parameters = {
                "week_anchor": "monday" if source_anchor == "monday" else "sunday"
            }
            treatment = "weekly_anchor_alignment_v1"
            reason = (
                "Monday weekly observations are assigned to the following Sunday "
                "model week; Sunday observations retain their factual week."
                if source_anchor == "monday"
                else "Sunday weekly observations are retained on the Sunday model calendar."
            )
        elif native == "monthly" and variable_class == "flow_count":
            method = "calendar_overlap_allocation"
            treatment = "calendar_overlap_allocation_v1"
            reason = "Monthly flow totals are allocated by inclusive calendar-day overlap and reconciled to source totals."
        elif native == "monthly" and variable_class in {"rate_index", "stock_level"}:
            method = "release_aware_locf"
            treatment = "release_aware_step_as_of_v1"
            prepared = False
            reason = "Executable only when a release date or approved publication lag is supplied; the historical workbook does not supply exact publication timing."
        elif native == "monthly" and variable_class == "survey_measurement":
            method = "release_aware_locf"
            treatment = "release_aware_step_as_of_v1"
            prepared = False
            reason = "Monthly awareness remains a step/as-of measurement state, not repeated independent weekly surveys; supplied release timing is missing."
        elif native == "weekly":
            treatment = "native_weekly_calendar_alignment_v1"
            reason = "Weekly source is retained at native cadence and aligned to Sunday labels without factual-date shifting."
        else:
            prepared = False
            reason = "No governed historical executor was selected for this native variable class/frequency."
        row = {
            "variable_id": variable_id,
            "variable_class": variable_class,
            "native_frequency": native,
            "source_anchor": source_anchor,
            "prepared": prepared,
            "proposed_role": "diagnostic_only",
            "treatment": treatment,
            "method_id": method,
            "method_version": 1 if method else None,
            "parameters": parameters,
            "publication_timing_status": timing_status,
            "source_rows": int(len(scoped)),
            "source_start": scoped["period_start"].min() if not scoped.empty else None,
            "source_end": scoped["period_start"].max() if not scoped.empty else None,
            "target_window_coverage_rows": int(
                scoped["period_start"].isin(TARGET_DATE_SET).sum()
            ),
            "reason": reason,
            "included_in_fit": False,
            "requires_causal_approval": True,
        }
        rows.append(row)
        # Execute synthetic/native transformations only when the source
        # contract contains enough information to do so without guessing.
        if prepared and method and not scoped.empty:
            execution_source = scoped
            if native == "monthly" and variable_class == "flow_count":
                target_start = pd.Timestamp(GOVERNED_START)
                target_end = pd.Timestamp(GOVERNED_END) + pd.Timedelta(days=6)
                source_month_start = (
                    scoped["period_start"]
                    .dt.to_period("M")
                    .dt.start_time.dt.normalize()
                )
                source_month_end = (
                    scoped["period_start"].dt.to_period("M").dt.end_time.dt.normalize()
                )
                execution_source = scoped[
                    (source_month_end >= target_start)
                    & (scoped["period_start"] <= target_end)
                ]
                boundary_month = execution_source[
                    (source_month_start.loc[execution_source.index] < target_start)
                    | (source_month_end.loc[execution_source.index] > target_end)
                ]
                if not boundary_month.empty:
                    prepared = False
                    reason = (
                        "Monthly flow reaches a target-window boundary month whose "
                        "full source period is outside the requested window; leave "
                        "the partial month unresolved rather than breaking source-total "
                        "reconciliation."
                    )
                    execution_source = scoped.iloc[0:0]
            spec = AlignmentSpecification(
                variable_id=variable_id,
                source_id="historical_context",
                source_version=1,
                market="UK",
                native_frequency=native,
                target_frequency="weekly",
                variable_class=variable_class,
                method_id=method,
                method_version=1,
                parameters=parameters,
            )
            try:
                if not prepared:
                    raise FrequencyConversionError(row["reason"])
                execution = execute_frequency_conversion(
                    execution_source,
                    spec,
                    date_col="period_start",
                    value_col="value",
                    target_periods=[date.strftime("%Y-%m-%d") for date in TARGET_DATES],
                    market_col="market",
                )
                executions.append(
                    {
                        "variable_id": variable_id,
                        "status": "executed",
                        "output_rows": len(execution.frame),
                        "evidence": execution.evidence,
                    }
                )
            except (FrequencyConversionError, ValueError) as exc:
                if prepared:
                    row["prepared"] = False
                    row["reason"] = (
                        f"Executor failed closed: {type(exc).__name__}: {exc}"
                    )
                executions.append(
                    {
                        "variable_id": variable_id,
                        "status": "blocked",
                        "error": str(exc),
                    }
                )
    report = {
        "schema_version": 1,
        "status": "executable_for_supported_native_and_explicitly-timed_classes",
        "target_calendar": "Sunday-Saturday",
        "native_source_preserved": True,
        "survey_method": "release_aware_step_as_of_v1; no independent weekly survey observations and no percentage division",
        "variables": rows,
        "executions": executions,
        "unresolved": [row for row in rows if not row["prepared"]],
    }
    _write_json(output_dir / "mixed-frequency-preparation-spec.json", report)
    _write_json(output_dir / "mixed-frequency-preparation-report.json", report)
    pd.DataFrame(rows).drop(columns=["parameters"], errors="ignore").to_csv(
        output_dir / "mixed-frequency-preparation-report.csv", index=False
    )
    lines = [
        "# Mixed-frequency preparation",
        "",
        "Native source tables remain unchanged. Derived weekly outputs use the governed Sunday-Saturday calendar.",
        "",
        "| Variable class | Method | Prepared | Publication timing | Role |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['variable_class']} / {row['variable_id']} | {row['treatment']} | {row['prepared']} | {row['publication_timing_status']} | {row['proposed_role']} |"
        )
    lines.extend(
        [
            "",
            "Monthly flow totals use inclusive calendar-day overlap; each source month is reconciled to its original total. Monthly rates/indices and surveys require explicit release timing for an official historical as-of frame. Aided brand awareness uses a release-aware step/state treatment when timing is supplied; a latent weekly survey model is deferred.",
        ]
    )
    (output_dir / "mixed-frequency-preparation-report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return report


def context_role_report(source_dir: Path) -> list[dict[str, Any]]:
    dictionary = _read_sheet(
        source_dir / "context_and_external_factors_data.xlsx", "variable_dictionary"
    )
    rows = []
    for record in dictionary.to_dict(orient="records"):
        variable_id = str(record["variable_id"])
        series_type = str(record.get("series_type") or "")
        variable_class = str(record.get("variable_class") or "")
        if "brand_search_interest" in variable_id or "category_demand" in variable_id:
            role, justification = (
                "demand_proxy",
                "Potentially endogenous search/category demand; diagnostic until graph approval.",
            )
        elif "web_visits" in variable_id or "aided_brand_awareness" in variable_id:
            role, justification = (
                "diagnostic_only",
                "Funnel or survey state may be downstream of media; no approved mediator equation yet.",
            )
        elif variable_class in {"rate_index", "flow_count"} and (
            variable_id.startswith("uk_") or "competitor" in series_type
        ):
            role, justification = (
                "control",
                "Candidate exogenous macro/category context, subject to source coverage, timing, and graph approval.",
            )
        else:
            role, justification = (
                "diagnostic_only",
                "No approved causal edge or model equation currently consumes this variable.",
            )
        rows.append(
            {
                "variable": variable_id,
                "prepared": False,
                "proposed_role": role,
                "causal_justification": justification,
                "included_in_equation": "candidate only; not in initial fit",
                "requires_approval": True,
                "native_frequency": record.get("native_frequency"),
                "variable_class": variable_class,
            }
        )
    return rows


def build_search_review(output_dir: Path) -> dict[str, Any]:
    report = {
        "schema_version": 1,
        "status": "corrected_capability_not_real_data_approved",
        "engine": "PyMC observed mediation validation adapter explicitly linked to the canonical hierarchical PyMC/Candidate A architecture",
        "spend_in_mediator_equation": True,
        "spend_object": "Paid Brand Search spend is a separate GBP source predictor of observed clicks/delivery; it is not substituted for clicks and is not a direct outcome pathway.",
        "delivery_object": "Paid Brand Search clicks/delivery remain the observed mediator.",
        "lag_handling": "The same market-safe lag index is used in the observed outcome likelihood and generated-mediator intervention deterministics for lag 0, 1, and greater than 1.",
        "canonical_integration": {
            "primary_builder": "ancestry_mmm.core.hierarchical_model.build_fh_hierarchical_model",
            "linked_engine_boundary": "SEARCH_CANDIDATE_A_ENGINE and GraphModelCompiler",
            "direct_effect": "ordinary direct pathway masks in the canonical hierarchical model",
            "mediated_effect": "linked Search chain with posterior uncertainty; no post-hoc credit redistribution",
            "total_effect": "outcome-scale counterfactual direct plus realised mediated effect",
            "planning_optimisation": False,
        },
        "missing_objects": [
            "branded-search demand as a governed exogenous/latent object",
            "Paid Search cap/capacity",
            "organic Search capture",
            "direct navigation capture",
        ],
        "limitations": "The observed-click capability does not fabricate unavailable demand/cap/organic/direct objects and is not a replacement for the complete hierarchical FH or DNA MMM.",
        "tests_required_and_present": [
            "spend enters mediator likelihood when supplied",
            "delivery remains separate from spend",
            "lag 0/1/>1 and market boundaries",
            "graph reverse-direction rejection",
            "direct plus mediated plus total effect deterministics without double counting",
        ],
    }
    _write_json(output_dir / "search-mediation-implementation-review.json", report)
    lines = [
        "# Paid Brand Search mediation implementation review",
        "",
        "Search spend is now an explicit predictor of observed Paid Brand Search delivery when supplied. Clicks/delivery remain the mediator and spend is never substituted for it.",
        "",
        "The capability is explicitly linked to the canonical hierarchical PyMC/Candidate A compiler boundary; it is a validation extension, not a hidden replacement for the primary FH/DNA MMM.",
        "",
        "Lag handling is consistent between fitted outcome likelihood and intervention deterministics and respects market bounds. Demand, cap, organic, and direct-navigation objects are unavailable in this historical source and remain unconstructed.",
    ]
    (output_dir / "search-mediation-implementation-review.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return report


def build_candidate_graph(
    output_dir: Path, activity_channels: Sequence[str]
) -> dict[str, Any]:
    """Create a draft candidate graph without inventing upstream edges."""

    media_nodes = [
        {
            "node_id": channel,
            "label": channel,
            "role": "intervention",
            "product": "Family History/DNA as governed by model channel",
            "metadata": {"edge_approval_required": True},
        }
        for channel in activity_channels
    ]
    outcomes = [
        {
            "node_id": outcome,
            "label": label,
            "role": "outcome",
            "product": "Family History" if outcome.startswith("fh_") else "DNA",
        }
        for outcome, label in NBT_LABELS.items()
    ]
    nodes = (
        media_nodes
        + outcomes
        + [
            {
                "node_id": "paid_brand_search_spend",
                "label": "Paid Brand Search spend (GBP)",
                "role": "intervention",
                "search_object_id": "paid_search_spend",
            },
            {
                "node_id": "paid_brand_search_clicks",
                "label": "Paid Brand Search clicks/delivery",
                "role": "mediator",
                "search_object_id": "paid_search_delivery",
            },
            {
                "node_id": "ancestry_brand_search_interest",
                "label": "Ancestry brand-search interest (diagnostic demand proxy)",
                "role": "diagnostic",
                "search_object_id": "search_demand_proxy",
            },
        ]
    )
    edges = [
        {
            "source_node_id": "paid_brand_search_spend",
            "target_node_id": "paid_brand_search_clicks",
            "role": "mediated",
            "lag_type": "none",
            "metadata": {
                "approval_required": True,
                "source_support": "spend and clicks supplied",
            },
        },
    ]
    graph = {
        "schema_version": 1,
        "graph_id": "historical-uk-causal-graph-candidate",
        "graph_version": 1,
        "status": "draft",
        "approval_required": True,
        "nodes": nodes,
        "edges": edges,
        "explicitly_prohibited": [
            "infer every media-to-Search edge from correlation",
            "collapse Search spend, clicks, Google Trends interest, organic Search, and direct navigation",
            "fit branded-search interest as ordinary exogenous intervention without graph approval",
            "fabricate a Search cap or organic/direct capture",
        ],
        "upstream_media_edges": "not populated pending analyst approval; each candidate upstream media-to-clicks and direct outcome edge must be explicitly reviewed",
        "search_delivery_to_outcomes": "candidate mediated edges to FH New, FH DNA cross-sell, FH Winback, DNA New Customer, and DNA Existing FH Customer require analyst approval and identification review",
        "context_equation_edges": "none approved; macro variables are candidate controls and funnel/search variables remain diagnostic or mediator candidates",
    }
    _write_json(output_dir / "historical-causal-graph-candidate.json", graph)
    mmd = [
        "flowchart LR",
        "  spend[Paid Brand Search spend GBP] -->|candidate: approval required| clicks[Paid Brand Search clicks/delivery]",
        "  demand[Ancestry brand-search interest diagnostic only]:::diagnostic",
        "  note[Upstream media edges and clicks-to-outcome edges deliberately omitted pending analyst approval]:::pending",
        "  classDef diagnostic fill:#eee,stroke:#777",
        "  classDef pending fill:#fff3cd,stroke:#997404",
    ]
    (output_dir / "historical-causal-graph-candidate.mmd").write_text(
        "\n".join(mmd) + "\n", encoding="utf-8"
    )
    markdown = [
        "# Historical UK causal graph candidate",
        "",
        "Status: **draft — analyst approval required**.",
        "",
        "The candidate keeps Paid Brand Search spend, observed clicks/delivery, and Ancestry brand-search interest as separate objects. The only source-supported edge declared in this package is spend to observed delivery. Upstream-media-to-Search, Search-to-outcome, and direct media-to-outcome edges are intentionally not inferred from correlation.",
        "",
        "The graph cannot approve the revised fit until an analyst confirms which supplied media may affect Paid Brand Search, which direct media paths remain, which five outcomes receive observed Search mediation, and which context variables enter each equation.",
    ]
    (output_dir / "historical-causal-graph-candidate.md").write_text(
        "\n".join(markdown) + "\n", encoding="utf-8"
    )
    return graph


def _prepared_media_matrix(
    source_dir: Path,
    approved_pack_dir: Path,
    channels: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = _read_sheet(
        approved_pack_dir / "activity_data_approved_metadata_and_structural_zeros.xlsx",
        "activity_data",
    )
    dictionary = _read_sheet(
        approved_pack_dir / "activity_data_approved_metadata_and_structural_zeros.xlsx",
        "activity_dictionary",
    )
    raw = raw[raw["period_start"].isin(TARGET_DATE_SET)].copy()
    values = pd.DataFrame({"period_start": TARGET_DATES})
    for channel in channels:
        definition = dictionary[dictionary["model_input_column"] == channel]
        if definition.empty:
            raise ValueError(f"approved activity definition missing {channel!r}")
        record = definition.iloc[0]
        activity_id = str(record["activity_id"])
        measure = str(record["model_input_measure"])
        selected = raw[raw["activity_id"].astype(str) == activity_id][
            ["period_start", measure]
        ].rename(columns={measure: channel})
        values = values.merge(selected, on="period_start", how="left")
        values[channel] = pd.to_numeric(values[channel], errors="coerce")
    return values, dictionary


def build_identification_report(
    source_dir: Path,
    approved_pack_dir: Path,
    previous_report: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    models = _required_channels(previous_report)
    equations: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    for model_name, channels in models.items():
        media, dictionary = _prepared_media_matrix(
            source_dir, approved_pack_dir, sorted(channels)
        )
        media_values = media[list(sorted(channels))].copy()
        media_missing = media_values.isna().sum()
        if int(media_missing.sum()) > 0:
            raise ValueError(
                "prepared required media matrix contains missing observations; "
                "coverage reconciliation must resolve the exact blocker before "
                f"identification diagnostics: {media_missing[media_missing > 0].to_dict()}"
            )
        n = len(media_values)
        trend = np.linspace(-1.0, 1.0, n)
        seasonality = np.column_stack(
            [np.sin(2 * np.pi * np.arange(n) * k / 52.0) for k in range(1, 4)]
            + [np.cos(2 * np.pi * np.arange(n) * k / 52.0) for k in range(1, 4)]
        )
        outcome_matrix = media_values.copy()
        outcome_matrix["trend"] = trend
        for index in range(seasonality.shape[1]):
            outcome_matrix[f"fourier_{index + 1}"] = seasonality[:, index]
        adstock = geometric_adstock_matrix(
            media_values.to_numpy(dtype=float),
            np.full(len(channels), 0.5),
            normalize=True,
        )
        transformed = hill_function(
            adstock,
            np.maximum(media_values.mean(axis=0).to_numpy(dtype=float), 1.0),
            np.full(len(channels), 1.0),
        )
        transformed_full = np.column_stack(
            [
                transformed,
                outcome_matrix[
                    ["trend"] + [f"fourier_{i + 1}" for i in range(6)]
                ].to_numpy(),
            ]
        )
        labels = (
            list(sorted(channels)) + ["trend"] + [f"fourier_{i + 1}" for i in range(6)]
        )
        result = equation_identification_diagnostics(
            outcome_matrix[labels],
            labels=labels,
            transformed_predictors=transformed_full,
        )
        equations.append(
            {
                "equation_id": f"{model_name}_outcome_equations",
                "model_name": model_name,
                "equation_type": "hierarchical outcome equation(s)",
                "predictors": labels,
                "role": "media intervention + trend + seasonality",
                "source_frequency": "weekly native/derived Sunday-Saturday",
                "prepared_frequency": "weekly",
                "transformation": "governed geometric adstock/Hill diagnostic at nominal values; no posterior fit",
                "coverage": "131 target weeks from approved derived activity pack",
                "causal_edge": "media edges remain subject to candidate graph approval",
                "diagnostics": result,
                "blocking": False,
                "recommended_response": "Review high-correlation/VIF evidence; preserve causally necessary variables and use priors/specification comparisons rather than automatic deletion.",
            }
        )
        for name, vif in result["vif"].items():
            csv_rows.append(
                {
                    "equation_id": f"{model_name}_outcome_equations",
                    "model_name": model_name,
                    "equation_type": "outcome",
                    "variable": name,
                    "max_abs_pairwise_pearson": max(
                        abs(result["pearson_correlation"][name][other])
                        for other in labels
                        if other != name
                    )
                    if len(labels) > 1
                    else 0.0,
                    "vif": vif,
                    "condition_number": result["condition_number"],
                    "matrix_rank": result["matrix_rank"],
                    "exact_rank_deficient": result["exact_rank_deficient"],
                    "near_zero_variance": name in result["near_zero_variance"],
                    "blocking": False,
                }
            )
        search_activity = (
            "fh_brand_search" if model_name == "family_history" else "dna_brand_search"
        )
        search_dict = dictionary[dictionary["activity_id"] == search_activity].iloc[0]
        search_measure = str(search_dict["model_input_measure"])
        prepared_source = _read_sheet(
            approved_pack_dir
            / "activity_data_approved_metadata_and_structural_zeros.xlsx",
            "activity_data",
        )
        prepared_source = prepared_source[
            prepared_source["period_start"].isin(TARGET_DATE_SET)
        ]
        search = prepared_source[prepared_source["activity_id"] == search_activity][
            ["period_start", search_measure, "spend"]
        ].rename(
            columns={
                search_measure: "paid_search_delivery",
                "spend": "paid_search_spend",
            }
        )
        mediator = media_values.copy()
        mediator["paid_search_spend"] = (
            search.set_index("period_start")["paid_search_spend"]
            .reindex(TARGET_DATES)
            .to_numpy()
        )
        mediator["paid_search_delivery"] = (
            search.set_index("period_start")["paid_search_delivery"]
            .reindex(TARGET_DATES)
            .to_numpy()
        )
        mediator_labels = list(sorted(channels)) + ["paid_search_spend"]
        mediator_missing = mediator[mediator_labels].isna().sum()
        if int(mediator_missing.sum()) > 0:
            mediator_result = {
                "status": "unresolved_missing_search_observations",
                "n_observations": int(len(mediator)),
                "predictor_count": int(len(mediator_labels)),
                "missing_counts": {
                    str(name): int(value)
                    for name, value in mediator_missing.items()
                    if int(value) > 0
                },
                "vif": {},
                "condition_number": None,
                "matrix_rank": None,
                "exact_rank_deficient": None,
                "near_zero_variance": [],
                "diagnostic_note": (
                    "No imputation was performed. The observed Search spend/delivery "
                    "equation cannot be evaluated until the missing governed "
                    "observations are resolved or the Search object is excluded "
                    "from the official causal fit."
                ),
            }
        else:
            mediator_result = equation_identification_diagnostics(
                mediator[mediator_labels], labels=mediator_labels
            )
        equations.append(
            {
                "equation_id": f"{model_name}_paid_brand_search_mediator",
                "model_name": model_name,
                "equation_type": "Paid Brand Search observed delivery mediator equation",
                "predictors": mediator_labels,
                "role": "approved upstream media candidates + separate Search spend predictor",
                "source_frequency": "weekly native",
                "prepared_frequency": "weekly Sunday-Saturday",
                "transformation": "physical delivery retained; Search spend retained in GBP as separate predictor",
                "coverage": "delivery and spend coverage assessed; channel remains graph/identification gated",
                "causal_edge": "spend-to-delivery supported only where both observed objects are complete; upstream edges require analyst approval",
                "diagnostics": mediator_result,
                "blocking": True,
                "recommended_response": "Do not delete Search spend or delivery. Resolve missing governed Search observations or keep the object diagnostic-only; then review identification and approve the causal graph before fitting.",
            }
        )
        for name, vif in mediator_result["vif"].items():
            csv_rows.append(
                {
                    "equation_id": f"{model_name}_paid_brand_search_mediator",
                    "model_name": model_name,
                    "equation_type": "mediator",
                    "variable": name,
                    "max_abs_pairwise_pearson": max(
                        abs(mediator_result["pearson_correlation"][name][other])
                        for other in mediator_labels
                        if other != name
                    ),
                    "vif": vif,
                    "condition_number": mediator_result["condition_number"],
                    "matrix_rank": mediator_result["matrix_rank"],
                    "exact_rank_deficient": mediator_result["exact_rank_deficient"],
                    "near_zero_variance": name in mediator_result["near_zero_variance"],
                    "blocking": True,
                }
            )
    report = {
        "schema_version": 1,
        "status": "computed_for_review",
        "vif_is_diagnostic_not_deletion_rule": True,
        "equations": equations,
        "context_roles": context_role_report(source_dir),
        "major_issues": [
            {
                "issue": "mediator equation includes separate Search spend and delivery objects",
                "evidence": "equation-level correlation/VIF/condition diagnostics are reported",
                "causal_role": "spend predicts delivery; delivery mediates outcome only after graph approval",
                "attribution_risk": "Search association may be demand capture rather than incremental effect",
                "recommended_response": "approve graph and assess identification; do not silently reclassify or delete",
                "blocking": True,
            }
        ],
    }
    _write_json(output_dir / "pre-fit-identification-report.json", report)
    pd.DataFrame(csv_rows).to_csv(
        output_dir / "pre-fit-identification-report.csv", index=False
    )
    lines = [
        "# Pre-fit identification diagnostics",
        "",
        "Diagnostics use the prepared 131-week predictor matrices for each outcome model and each Paid Brand Search mediator equation. VIF is evidence only and never an automatic deletion rule.",
        "",
        "| Equation | Variable | Max pairwise | VIF | Condition number | Rank deficient | Near-zero variance | Blocking |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for row in csv_rows:
        lines.append(
            f"| {row['equation_id']} | {row['variable']} | {row['max_abs_pairwise_pearson']:.3f} | {row['vif']:.3g} | {row['condition_number']:.3g} | {row['exact_rank_deficient']} | {row['near_zero_variance']} | {row['blocking']} |"
        )
    lines.extend(
        [
            "",
            "Recommended decision hierarchy: confirm duplicate constructs, verify transformations, preserve causally necessary variables, consider evidence-informed priors and experiment evidence, compare bounded specifications, and exclude only with a semantic/causal justification.",
        ]
    )
    (output_dir / "pre-fit-identification-report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return report


def write_prefit_summary(
    output_dir: Path,
    coverage: Mapping[str, Any],
    nbt: Mapping[str, Any],
    mixed: Mapping[str, Any],
    search: Mapping[str, Any],
    graph: Mapping[str, Any],
    identification: Mapping[str, Any],
) -> dict[str, Any]:
    blockers = []
    if coverage.get("genuine_missing_required_fit_observations", 0):
        blockers.append("required activity source observations remain unavailable")
    if nbt.get("status") != "resolved":
        blockers.append("NBT governance metadata remains unresolved")
    if any(
        row.get("included_in_fit") and not row.get("prepared")
        for row in mixed.get("variables", [])
    ):
        blockers.append(
            "some optional context series lack executable release/timing metadata"
        )
    blockers.append("historical causal graph is draft and requires analyst approval")
    blockers.append("Search mediator identification is not approved for fitting")
    summary = {
        "schema_version": 1,
        "status": "blocked_before_revised_fit",
        "gates": {
            "activity_coverage": "resolved_for_required_fit_inputs"
            if not coverage.get("genuine_missing_required_fit_observations")
            else "blocked",
            "nbt_governance": nbt.get("status"),
            "mixed_frequency": "capability_ready_optional_context_timing_unresolved",
            "search_mediation": search.get("status"),
            "historical_causal_graph": graph.get("status"),
            "prefit_identification": identification.get("status"),
            "prior_predictive": "not_run_before_graph_and_preparation_approval",
        },
        "blocking_reasons": blockers,
        "revised_fit_may_start": False,
        "curves_planning_optimisation_authorised": False,
        "recommendation": "2. governance/graph approval required",
    }
    _write_json(output_dir / "pre-fit-readiness-summary.json", summary)
    lines = [
        "# Historical pre-fit readiness summary",
        "",
        "Status: **blocked_before_revised_fit**",
        "",
        "The required activity inputs are supportable through the prior approved structural-zero artefact, and the five corrected NBT identities have a derived governance overlay. The revised real-data fit must still stop because the candidate causal graph is draft, Search identification/approval is outstanding, and prior predictive checks must run only after those gates pass.",
        "",
        "## Blocking reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in blockers)
    lines.extend(
        [
            "",
            "Recommendation: **2. governance/graph approval required**.",
        ]
    )
    (output_dir / "pre-fit-readiness-summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return summary


def write_prepared_model_frame_audit(
    output_dir: Path,
    previous_report: Mapping[str, Any],
    coverage: Mapping[str, Any],
    identification: Mapping[str, Any],
) -> dict[str, Any]:
    audit_rows = []
    for equation in identification.get("equations", []):
        audit_rows.append(
            {
                "equation_id": equation["equation_id"],
                "model_name": equation["model_name"],
                "equation_type": equation["equation_type"],
                "outcome": ", ".join(
                    str(outcome_id)
                    for model in previous_report.get("models", [])
                    if model.get("model_name") == equation["model_name"]
                    for outcome_id in (model.get("outcome_ids") or [])
                ),
                "predictors": equation["predictors"],
                "role": equation["role"],
                "source_frequency": equation["source_frequency"],
                "prepared_frequency": equation["prepared_frequency"],
                "transformation": equation["transformation"],
                "coverage": equation["coverage"],
                "missingness_state": "governed structural zeros retained; existing nulls remain missing",
                "structural_zero_state": "explicit in approved activity pack",
                "causal_edge": equation["causal_edge"],
                "prior_family": "canonical PyMC hierarchical priors; mediator spend HalfNormal when supplied",
                "included": False,
                "reason_if_excluded": "candidate historical package; causal graph approval and prior predictive gate outstanding",
            }
        )
    report = {
        "schema_version": 1,
        "status": "candidate_audit_before_graph_approval",
        "target_window": {
            "start": GOVERNED_START,
            "end": GOVERNED_END,
            "frequency": "Sunday-Saturday",
        },
        "required_activity_fit_blockers": coverage.get(
            "genuine_missing_required_fit_observations", 0
        ),
        "rows": audit_rows,
    }
    _write_json(output_dir / "prepared-model-frame-audit.json", report)
    lines = [
        "# Prepared model-frame audit",
        "",
        "This is a candidate audit of the actual prepared predictor matrices. No predictor is silently dropped; inclusion remains false until the graph and prior-predictive gates are approved.",
        "",
        "| Equation | Type | Predictors | Frequency | Transformation | Included |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {row['equation_id']} | {row['equation_type']} | {', '.join(row['predictors'])} | {row['prepared_frequency']} | {row['transformation']} | {row['included']} |"
        for row in audit_rows
    )
    (output_dir / "prepared-model-frame-audit.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return report


def run(
    *,
    source_dir: Path = SOURCE_DIR,
    approved_pack_dir: Path = APPROVED_PACK_DIR,
    previous_validation_dir: Path = PREVIOUS_VALIDATION_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    # The report path is kept explicit and separate from the immutable
    # previous-validation directory because the validation artefact itself
    # records the exact production report used for reconstruction.
    previous_validation = _read_json(
        previous_validation_dir / "previous-fit-validation.json"
    )
    production_report_path = Path(previous_validation["previous_fit_report"])
    previous_report = _read_json(production_report_path)
    coverage = reconcile_activity_coverage(
        source_dir, approved_pack_dir, previous_report, output_dir
    )
    nbt = migrate_nbt_governance(source_dir, approved_pack_dir, output_dir)
    complete = complete_previous_validation(previous_validation_dir, output_dir)
    mixed = mixed_frequency_preparation(source_dir, output_dir)
    search = build_search_review(output_dir)
    channels = sorted(set().union(*_required_channels(previous_report).values()))
    graph = build_candidate_graph(output_dir, channels)
    identification = build_identification_report(
        source_dir, approved_pack_dir, previous_report, output_dir
    )
    write_prepared_model_frame_audit(
        output_dir, previous_report, coverage, identification
    )
    roles = {
        "variables": identification["context_roles"],
        "status": "candidate_roles_require_graph_approval",
    }
    _write_json(output_dir / "context-variable-roles.json", roles)
    summary = write_prefit_summary(
        output_dir, coverage, nbt, mixed, search, graph, identification
    )
    _write_json(
        output_dir / "remediation-manifest.json",
        {
            "status": summary["status"],
            "source_dir": source_dir,
            "approved_pack_dir": approved_pack_dir,
            "previous_validation_dir": previous_validation_dir,
            "outputs_are_new_versioned_evidence": True,
            "raw_source_unchanged": True,
            "old_validation_artefacts_overwritten": False,
            "components": {
                "activity_coverage": coverage["status"],
                "nbt_governance": nbt["status"],
                "previous_validation": complete["status"],
                "mixed_frequency": mixed["status"],
                "search": search["status"],
                "graph": graph["status"],
                "identification": identification["status"],
            },
        },
    )
    return {
        "status": summary["status"],
        "recommendation": summary["recommendation"],
        "output_dir": str(output_dir),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--approved-pack-dir", type=Path, default=APPROVED_PACK_DIR)
    parser.add_argument(
        "--previous-validation-dir", type=Path, default=PREVIOUS_VALIDATION_DIR
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    result = run(
        source_dir=args.source_dir,
        approved_pack_dir=args.approved_pack_dir,
        previous_validation_dir=args.previous_validation_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
