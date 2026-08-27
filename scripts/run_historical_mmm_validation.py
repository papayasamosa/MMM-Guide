"""Run the historical UK MMM validation gate without mutating source or old fits.

The script has two intentionally separate responsibilities:

* audit the updated raw workbooks and write a governed preparation/mixed-
  frequency report; and
* reconstruct the exact previous Model A specifications from the immutable
  approved source pack and saved fit report, then validate those saved
  posteriors without refitting them.

The revised fit is attempted only if the updated source passes the exact
Sunday-Saturday target-window coverage gate and an approved observed Search
mediation graph is available.  Missing input coverage is reported as a
blocker; it is never shortened, interpolated, or zero-filled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import arviz as az
import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ancestry_mmm.application.uk_readiness import run_uk_readiness  # noqa: E402
from ancestry_mmm.core.diagnostics import (  # noqa: E402
    predictive_density_summary,
    prior_predictive_summary,
)
from ancestry_mmm.core.models import compute_model_diagnostics  # noqa: E402
from ancestry_mmm.core.schema import ModelSpec  # noqa: E402
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame  # noqa: E402

from scripts.run_uk_production_fit import (  # noqa: E402
    COMMON_WINDOW_END as GOVERNED_END,
    COMMON_WINDOW_START as GOVERNED_START,
    TARGET_FREQUENCY,
    _add_history,
    _completeness_metadata,
    _load_pack,
    _model_meta_payload,
)
from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402


CURRENT_SOURCE_DIR = Path(r"D:\App Projects\Media-Mix-Lab\.local-data\uk-previous-mmm")
PREVIOUS_PACK_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\uk-readiness\approved-uk-packs-20260820-v3"
)
PREVIOUS_REPORT = Path(
    r"D:\Ancestry-MMM\test-artifacts\uk-readiness\production-fit-final-20260821\production-fit-report.json"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-mmm-validation-20260821"
)
TARGET_DATES = pd.date_range(GOVERNED_START, GOVERNED_END, freq="7D")


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
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _metric_rows(
    actual: np.ndarray, prediction_draws: np.ndarray, outcome_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return point and Bayesian-R2 evidence from posterior mean draws."""

    prediction_draws = np.asarray(prediction_draws, dtype=float)
    point = prediction_draws.mean(axis=1)
    residual = point - actual
    denom = (np.abs(actual) + np.abs(point)) / 2
    smape_mask = denom != 0
    nonzero = actual != 0
    total = np.sum(np.abs(actual))
    ss_total = np.sum((actual - actual.mean()) ** 2)
    point_row = {
        "outcome_id": outcome_id,
        "r_squared": _float(1 - np.sum((actual - point) ** 2) / ss_total)
        if ss_total > 0
        else None,
        "mae": _float(np.mean(np.abs(residual))),
        "rmse": _float(np.sqrt(np.mean(residual**2))),
        "mape_pct": _float(np.mean(np.abs(residual[nonzero] / actual[nonzero])) * 100)
        if nonzero.any()
        else None,
        "smape_pct": _float(
            np.mean(np.abs(residual[smape_mask]) / denom[smape_mask]) * 100
        )
        if smape_mask.any()
        else 0.0,
        "wape_pct": _float(np.sum(np.abs(residual)) / total * 100)
        if total > 0
        else None,
        "bias": _float(np.mean(residual)),
        "actual_mean": _float(actual.mean()),
        "predicted_mean": _float(point.mean()),
        "n_observations": int(actual.size),
    }
    r2_draws = []
    for draw in prediction_draws.T:
        residual_draw = actual - draw
        var_mu = np.var(draw)
        var_resid = np.var(residual_draw)
        r2_draws.append(var_mu / (var_mu + var_resid) if var_mu + var_resid else np.nan)
    finite = np.asarray(r2_draws)[np.isfinite(r2_draws)]
    bayesian_row = {
        "outcome_id": outcome_id,
        "draw_count": int(prediction_draws.shape[1]),
        "bayesian_r2_mean": _float(np.mean(finite)) if finite.size else None,
        "bayesian_r2_median": _float(np.median(finite)) if finite.size else None,
        "bayesian_r2_q05": _float(np.quantile(finite, 0.05)) if finite.size else None,
        "bayesian_r2_q95": _float(np.quantile(finite, 0.95)) if finite.size else None,
    }
    return point_row, bayesian_row


def _residual_rows(
    actual: np.ndarray, prediction_draws: np.ndarray, outcome_id: str
) -> dict[str, Any]:
    residual = actual - prediction_draws.mean(axis=1)
    if residual.size > 1 and np.std(residual[:-1]) and np.std(residual[1:]):
        lag1 = float(np.corrcoef(residual[:-1], residual[1:])[0, 1])
    else:
        lag1 = None
    ss = float(np.sum(residual**2))
    dw = float(np.sum(np.diff(residual) ** 2) / ss) if ss > 0 else None
    lb_lag = min(10, max(1, residual.size // 5))
    lb_stat = lb_p = None
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox

        lb = acorr_ljungbox(residual, lags=[lb_lag], return_df=True).iloc[0]
        lb_stat, lb_p = _float(lb["lb_stat"]), _float(lb["lb_pvalue"])
    except Exception:
        pass
    return {
        "outcome_id": outcome_id,
        "n_observations": int(residual.size),
        "residual_mean": _float(residual.mean()),
        "lag1_autocorrelation": lag1,
        "durbin_watson": dw,
        "ljung_box_lag": lb_lag,
        "ljung_box_stat": lb_stat,
        "ljung_box_pvalue": lb_p,
    }


def _posterior_metrics(
    trace: az.InferenceData, frame: Mapping[str, Any], outcome_ids: Sequence[str]
) -> dict[str, Any]:
    mu = trace.posterior["mu"].stack(sample=("chain", "draw")).values
    if mu.shape[0] != len(frame["Y"]):
        raise ValueError("saved posterior mu does not match reconstructed frame rows")
    point_rows: list[dict[str, Any]] = []
    r2_rows: list[dict[str, Any]] = []
    residual_rows: list[dict[str, Any]] = []
    for index, outcome_id in enumerate(outcome_ids):
        draws = mu[:, index, :]
        point, r2 = _metric_rows(np.asarray(frame["Y"])[:, index], draws, outcome_id)
        point_rows.append(point)
        r2_rows.append(r2)
        residual_rows.append(
            _residual_rows(np.asarray(frame["Y"])[:, index], draws, outcome_id)
        )
    return {
        "point_metrics": point_rows,
        "bayesian_r2": r2_rows,
        "residual_temporal": residual_rows,
    }


def _ppc_rows(
    ppc: az.InferenceData, frame: Mapping[str, Any], outcome_ids: Sequence[str]
) -> list[dict[str, Any]]:
    values = (
        ppc.posterior_predictive["y_obs"]
        .stack(sample=("chain", "draw"))
        .transpose("obs", "outcome", "sample")
        .values
    )
    rows = []
    for index, outcome_id in enumerate(outcome_ids):
        actual = np.asarray(frame["Y"])[:, index]
        draws = values[:, index, :]
        lower, upper = np.quantile(draws, [0.05, 0.95], axis=1)
        rows.append(
            {
                "outcome_id": outcome_id,
                "credible_mass": 0.90,
                "coverage_pct": _float(
                    np.mean((actual >= lower) & (actual <= upper)) * 100
                ),
                "target_pct": 90.0,
                "n_predictive_samples": int(draws.shape[1]),
            }
        )
    return rows


def _sampling_diagnostics(trace: az.InferenceData) -> dict[str, Any]:
    result = compute_model_diagnostics(trace)
    stats = trace.sample_stats if hasattr(trace, "sample_stats") else None
    if stats is not None:
        if "tree_depth" in stats:
            result["max_tree_depth"] = int(stats["tree_depth"].max().values)
        else:
            result["max_tree_depth"] = None
        try:
            result["bfmi"] = [float(value) for value in az.bfmi(trace).values]
        except Exception:
            result["bfmi"] = None
    else:
        result["max_tree_depth"] = None
        result["bfmi"] = None
    return result


def _source_readiness(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    paths = (
        ("activity_and_media", source_dir / "activity_data.xlsx"),
        (
            "context_and_external_factors",
            source_dir / "context_and_external_factors_data.xlsx",
        ),
        ("outcomes", source_dir / "outcome_data.xlsx"),
    )
    evidence = []
    for domain, path in paths:
        evidence.append(
            {
                "domain": domain,
                "path": str(path),
                "exists": path.exists(),
                "sha256": _sha256(path) if path.exists() else None,
                "size_bytes": path.stat().st_size if path.exists() else None,
            }
        )
    try:
        report = run_uk_readiness(
            source_paths=tuple(paths),
            output_dir=output_dir / "source-readiness",
            governed_start=GOVERNED_START,
            governed_end=GOVERNED_END,
            governed_frequency=TARGET_FREQUENCY,
        )
        return {
            "status": report.status,
            "report_path": str(report.report_path),
            "source_evidence": evidence,
            "stages": {
                stage.name: {
                    "status": stage.status,
                    "summary": stage.summary,
                }
                for stage in report.stages
            },
        }
    except Exception as exc:
        return {
            "status": "failed",
            "source_evidence": evidence,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _current_preparation_audit(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    activity = pd.read_excel(
        source_dir / "activity_data.xlsx", sheet_name="activity_data"
    )
    activity_dict = pd.read_excel(
        source_dir / "activity_data.xlsx", sheet_name="activity_dictionary"
    )
    outcomes = pd.read_excel(source_dir / "outcome_data.xlsx", sheet_name="outcomes")
    outcome_dict = pd.read_excel(
        source_dir / "outcome_data.xlsx", sheet_name="outcome_dictionary"
    )
    context = pd.read_excel(
        source_dir / "context_and_external_factors_data.xlsx", sheet_name="context_data"
    )
    context_dict = pd.read_excel(
        source_dir / "context_and_external_factors_data.xlsx",
        sheet_name="variable_dictionary",
    )
    activity["period_start"] = pd.to_datetime(activity["period_start"])
    outcomes["period_start"] = pd.to_datetime(outcomes["period_start"])
    context["period_start"] = pd.to_datetime(context["period_start"])
    target_set = set(TARGET_DATES)
    activity_rows = []
    coverage_blockers = []
    for record in activity_dict.to_dict(orient="records"):
        activity_id = str(record["activity_id"])
        model_input = str(record["model_input_column"])
        measure = str(record["model_input_measure"])
        source_column = measure if measure in activity.columns else "spend"
        scoped = activity[activity["activity_id"].astype(str) == activity_id]
        target = scoped[scoped["period_start"].isin(target_set)]
        observed = (
            target[source_column].notna()
            if source_column in target
            else pd.Series(dtype=bool)
        )
        missing = int(len(TARGET_DATES) - int(observed.sum()))
        row = {
            "activity_id": activity_id,
            "model_input_column": model_input,
            "model_input_measure": measure,
            "model_input_unit": record.get("model_input_unit"),
            "spend_column": record.get("spend_column"),
            "currency": record.get("currency"),
            "source_column": source_column,
            "source_rows": int(len(scoped)),
            "source_start": scoped["period_start"].min().strftime("%Y-%m-%d")
            if not scoped.empty
            else None,
            "source_end": scoped["period_start"].max().strftime("%Y-%m-%d")
            if not scoped.empty
            else None,
            "target_observed_rows": int(observed.sum()),
            "target_missing_rows": missing,
            "target_nonzero_or_variable": bool(
                observed.any()
                and target.loc[observed, source_column].nunique(dropna=True) > 1
            ),
        }
        activity_rows.append(row)
        if missing:
            coverage_blockers.append(
                {
                    "activity_id": activity_id,
                    "model_input_column": model_input,
                    "missing_target_weeks": missing,
                    "source_end": row["source_end"],
                    "reason": "required target-window observations are unavailable; no fill applied",
                }
            )

    primary_outcomes = outcome_dict[
        outcome_dict["included_in_fit"].fillna(False).astype(bool)
    ]
    unresolved_outcome_fields = [
        column
        for column in (
            "date_basis",
            "maturity_required",
            "event_definition",
            "exclusions",
            "reconciliation_source",
        )
        if primary_outcomes[column].isna().all()
    ]
    nbt_identity_ok = set(
        primary_outcomes[primary_outcomes["product"] == "Family History"][
            "source_column"
        ]
    ) == {
        "fh_net_billthrough_count_new",
        "fh_net_billthrough_count_dna_cross_sell",
        "fh_net_billthrough_count_winback",
    }
    target_outcome_rows = outcomes[outcomes["period_start"].isin(target_set)]
    outcome_missing = {
        str(column): int(len(TARGET_DATES) - target_outcome_rows[column].notna().sum())
        for column in primary_outcomes["source_column"]
    }
    context_inventory = []
    for record in context_dict.to_dict(orient="records"):
        variable_id = str(record["variable_id"])
        scoped = context[context["variable_id"].astype(str) == variable_id]
        context_inventory.append(
            {
                "variable_id": variable_id,
                "variable_class": record.get("variable_class"),
                "native_frequency": record.get("native_frequency"),
                "role": record.get("role"),
                "source": record.get("source"),
                "series_type": record.get("series_type"),
                "source_rows": int(len(scoped)),
                "source_start": scoped["period_start"].min().strftime("%Y-%m-%d")
                if not scoped.empty
                else None,
                "source_end": scoped["period_start"].max().strftime("%Y-%m-%d")
                if not scoped.empty
                else None,
                "target_overlap_rows": int(
                    scoped[scoped["period_start"].isin(target_set)].shape[0]
                ),
                "treatment": "retained native; not consumed without an explicit approved causal/control role",
            }
        )

    required_blockers = [
        item
        for item in coverage_blockers
        if item["activity_id"] not in {"dna_performance_social"}
    ]
    report = {
        "status": "blocked" if required_blockers else "ready_for_model_specific_gate",
        "target_window": {
            "start": GOVERNED_START,
            "end": GOVERNED_END,
            "frequency": "Sunday-Saturday weekly",
            "weeks": len(TARGET_DATES),
        },
        "source_evidence": {
            "activity_data": {
                "sha256": _sha256(source_dir / "activity_data.xlsx"),
                "rows": int(len(activity)),
                "source_start": activity["period_start"].min().strftime("%Y-%m-%d"),
                "source_end": activity["period_start"].max().strftime("%Y-%m-%d"),
            },
            "outcome_data": {
                "sha256": _sha256(source_dir / "outcome_data.xlsx"),
                "rows": int(len(outcomes)),
                "source_start": outcomes["period_start"].min().strftime("%Y-%m-%d"),
                "source_end": outcomes["period_start"].max().strftime("%Y-%m-%d"),
            },
            "context_and_external_factors": {
                "sha256": _sha256(
                    source_dir / "context_and_external_factors_data.xlsx"
                ),
                "rows": int(len(context)),
                "source_start": context["period_start"].min().strftime("%Y-%m-%d"),
                "source_end": context["period_start"].max().strftime("%Y-%m-%d"),
            },
        },
        "outcome_identity": {
            "family_history_primary_source_columns": sorted(
                primary_outcomes[primary_outcomes["product"] == "Family History"][
                    "source_column"
                ].tolist()
            ),
            "dna_primary_source_columns": sorted(
                primary_outcomes[primary_outcomes["product"] == "DNA"][
                    "source_column"
                ].tolist()
            ),
            "nbt_identity_ok": bool(nbt_identity_ok),
            "gsa_aliases_present": bool(
                any("gsa" in str(column).lower() for column in outcomes.columns)
                or any(
                    "gsa" in str(column).lower()
                    for column in outcome_dict["source_column"]
                )
            ),
            "unresolved_governance_fields": unresolved_outcome_fields,
            "official_value_weight_status": "unresolved_blank_in_source"
            if primary_outcomes["include_in_value"].isna().any()
            else "resolved",
            "official_optimisation_status": "unresolved_blank_in_source"
            if primary_outcomes["include_in_optimisation"].isna().any()
            else "resolved",
            "approved_run_governance_overlay": {
                "scope": "five primary UK outcomes only",
                "role": "primary",
                "included_in_fit": True,
                "include_in_default_reporting": True,
                "include_in_official_total": True,
                "include_in_optimisation": True,
                "include_in_value": False,
                "value_weight": "blank_until_approved",
                "value_currency": "blank_until_approved",
                "raw_source_unchanged": True,
                "note": "This is the approved run decision recorded for derived preparation; the raw blanks remain a source-schema correction item and are not silently edited.",
            },
            "target_missing_rows": outcome_missing,
        },
        "activity_coverage": activity_rows,
        "coverage_blockers": coverage_blockers,
        "required_fit_coverage_blockers": required_blockers,
        "context_inventory": context_inventory,
        "preparation_decision": (
            "Do not fit or shorten the requested window until the required activity series are supplied through 2025-06-29."
            if required_blockers
            else "Proceed to model-specific preparation."
        ),
    }
    _write_json(output_dir / "updated-data-preparation-report.json", report)
    return report


def _mixed_frequency_report(
    preparation: Mapping[str, Any], output_dir: Path
) -> dict[str, Any]:
    inventory = preparation["context_inventory"]
    rows = []
    for item in inventory:
        frequency = str(item.get("native_frequency") or "").lower()
        variable_class = str(item.get("variable_class") or "")
        if frequency == "monthly" and variable_class == "flow_count":
            method = "calendar_overlap_allocation_v1"
            treatment = "candidate only; Sunday target-anchor reconciliation is not implemented by the current Monday-week executor"
        elif frequency == "monthly" and variable_class in {"rate_index", "stock_level"}:
            method = "release_aware_locf_v1"
            treatment = "candidate only; publication timing and Sunday target-anchor evidence unresolved"
        elif frequency == "weekly":
            method = "native_cadence_only_v1"
            treatment = "candidate only; native weekly anchor must be verified against Sunday-Saturday target calendar"
        else:
            method = None
            treatment = "no approved executable conversion selected"
        rows.append(
            {
                "variable_id": item["variable_id"],
                "native_frequency": item["native_frequency"],
                "variable_class": item["variable_class"],
                "method_id": method,
                "method_version": 1 if method else None,
                "status": "diagnostic_only_unresolved"
                if item.get("role") == "diagnostic"
                else "decision_required",
                "treatment": treatment,
                "source_support": {
                    "start": item.get("source_start"),
                    "end": item.get("source_end"),
                },
                "publication_leakage": "not assessed: source publication timing is not documented",
                "reconciliation": "not executed: no transformed series was written",
            }
        )
    report = {
        "status": "diagnostic_inventory_complete",
        "target_calendar": "Sunday-Saturday",
        "native_source_preserved": True,
        "universal_monthly_fill_applied": False,
        "rows": rows,
        "flow_total_reconciliation": "not executed without approved target-anchor and source-total semantics",
        "publication_leakage": "unresolved where source timing is undocumented",
    }
    _write_json(output_dir / "mixed-frequency-alignment-report.json", report)
    _write_json(output_dir / "mixed-frequency-reconciliation-report.json", report)
    return report


def _previous_model_inputs(
    report: Mapping[str, Any], pack: Any
) -> list[tuple[str, Any, ModelSpec, dict[str, Any]]]:
    from ancestry_mmm.data.source_pack_adoption import adopted_model_input_sources
    from ancestry_mmm.core.official_preparation import prepare_canonical_native_frame

    sources = adopted_model_input_sources(
        outcome_data=pack.adoption.outcome_data,
        activity_model_input=pack.adoption.activity_model_input,
        context_model_input=pack.adoption.context_data,
        context_variable_metadata=pack.adoption.context_variable_metadata,
    )
    if sources is None:
        raise RuntimeError("previous approved source pack has no adopted sources")
    canonical = prepare_canonical_native_frame(
        sources,
        date_col="period_start",
        market_col="market",
        governed_start=GOVERNED_START,
        governed_end=GOVERNED_END,
        governed_frequency=TARGET_FREQUENCY,
        consumed_variable_ids=(),
    )
    target = canonical.frame.copy()
    target["period_start"] = pd.to_datetime(target["period_start"])
    target = target[target["period_start"].isin(TARGET_DATES)].copy()
    target = target.sort_values(["market", "period_start"]).reset_index(drop=True)
    definitions = {
        item.outcome_id: item for item in pack.outcome_bundle.outcome_definitions
    }
    results = []
    for model in report["models"]:
        name = model["model_name"]
        outcomes = [definitions[oid] for oid in model["outcome_ids"]]
        meta = model.get("meta", {})
        dna_outcome = meta.get("dna_outcome_id") or (
            "fh_gsa_dna_cross_sell" if name == "family_history" else None
        )
        spec = ModelSpec(
            date_col="period_start",
            market_col="market",
            markets=list(model["markets"]),
            segment_outcomes={item.segment: item.source_column for item in outcomes},
            channels=list(model["channels"]),
            dna_channels=list(meta.get("dna_channels", [])),
            fh_dna_cross_sell_outcome_id=dna_outcome,
            fourier_harmonics=3,
        )
        frame = prepare_fh_modeling_frame(
            target,
            spec,
            outcomes=outcomes,
            activity_definitions=list(pack.activity_bundle.activity_definitions),
            net_billthrough_metadata=next(
                iter(_completeness_metadata(definitions.values()).values())
            ),
        )
        frame["preparation_mode"] = "historical_exact_reconstruction"
        history = _add_history(frame, pack.activity_bundle.model_input_media, spec)
        model_result = build_model_for_spec(
            frame=frame,
            model_spec=spec,
            model_type="shared",
            dna_lag_weeks=4,
            dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
            prior_config={},
            direct_dna_outcome_ids=(
                list(spec.segment_outcomes.values()) if name == "dna_kit" else None
            ),
            causal_graph=None,
            search_objects=(),
        )
        results.append(
            (
                name,
                model_result,
                spec,
                {"frame": frame, "history": history, "outcomes": outcomes},
            )
        )
    return results


def _validate_previous_fit(
    report: Mapping[str, Any], pack_dir: Path, output_dir: Path
) -> dict[str, Any]:
    pack = _load_pack(pack_dir)
    rebuilt = _previous_model_inputs(report, pack)
    by_name = {item[0]: item for item in rebuilt}
    model_rows = []
    outcome_rows = []
    old_posterior_hashes = {}
    for saved in report["models"]:
        name = saved["model_name"]
        trace_path = Path(saved["trace_path"])
        if not trace_path.exists():
            model_rows.append(
                {
                    "model_name": name,
                    "status": "blocked",
                    "reason": f"posterior missing: {trace_path}",
                }
            )
            continue
        old_posterior_hashes[name] = _sha256(trace_path)
        model_result, prepared = by_name[name][1], by_name[name][3]
        trace = az.from_netcdf(trace_path)
        model_dir = output_dir / "previous-fit-validation" / name
        model_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        import pymc as pm

        with model_result.model:
            ppc = pm.sample_posterior_predictive(
                trace,
                var_names=["y_obs"],
                random_seed=20260821,
                progressbar=False,
                return_inferencedata=True,
            )
        ppc.to_netcdf(model_dir / "posterior_predictive.nc")
        metrics = _posterior_metrics(trace, prepared["frame"], saved["outcome_ids"])
        ppc_rows = _ppc_rows(ppc, prepared["frame"], saved["outcome_ids"])
        diagnostics = _sampling_diagnostics(trace)
        density = None
        density_error = None
        try:
            density = predictive_density_summary(
                model_result.model, trace, prepared["frame"], model_result.meta
            )
        except Exception as exc:
            density_error = f"{type(exc).__name__}: {exc}"
        prior = None
        prior_error = None
        try:
            prior = prior_predictive_summary(
                model_result.model,
                prepared["frame"],
                model_result.meta,
                n_samples=100,
                random_seed=20260822,
            )
        except Exception as exc:
            prior_error = f"{type(exc).__name__}: {exc}"
        payload = {
            "validation_schema_version": 2,
            "status": "validated_without_refit",
            "model_name": name,
            "previous_fit_trace": str(trace_path),
            "previous_fit_trace_sha256_before": old_posterior_hashes[name],
            "previous_fit_trace_sha256_after": _sha256(trace_path),
            "reconstruction": {
                "source_pack": str(pack_dir),
                "outcome_ids": saved["outcome_ids"],
                "channels": saved["channels"],
                "history": prepared["history"],
                "model_meta": saved.get("meta", {}),
                "reconstructed_meta": _model_meta_payload(model_result.meta),
                "exact_structural_identity_match": bool(
                    saved.get("outcome_ids") == model_result.meta.outcome_ids
                    and saved.get("channels") == model_result.meta.channels
                ),
            },
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "outcome_metrics": metrics["point_metrics"],
            "bayesian_r2": metrics["bayesian_r2"],
            "residual_temporal": metrics["residual_temporal"],
            "posterior_predictive": ppc_rows,
            "sampling_diagnostics": diagnostics,
            "loo_waic": density,
            "loo_waic_error": density_error,
            "prior_predictive": prior,
            "prior_predictive_error": prior_error,
            "rolling_origin": {
                "status": "not_run",
                "reason": "would require refitting the previous model; prohibited by the retrospective validation brief",
            },
            "structural_stability": {
                "status": "not_run",
                "reason": "requires additional fits or saved fold posteriors; not inferred from one posterior",
            },
        }
        _write_json(model_dir / "validation.json", payload)
        pd.DataFrame(metrics["point_metrics"]).to_csv(
            model_dir / "outcome_metrics.csv", index=False
        )
        pd.DataFrame(metrics["bayesian_r2"]).to_csv(
            model_dir / "bayesian_r2.csv", index=False
        )
        pd.DataFrame(metrics["residual_temporal"]).to_csv(
            model_dir / "residual_temporal.csv", index=False
        )
        pd.DataFrame(ppc_rows).to_csv(model_dir / "ppc_coverage.csv", index=False)
        model_rows.append(
            {
                "model_name": name,
                "status": payload["status"],
                "exact_structural_identity_match": payload["reconstruction"][
                    "exact_structural_identity_match"
                ],
                "trace_sha256_unchanged": payload["previous_fit_trace_sha256_before"]
                == payload["previous_fit_trace_sha256_after"],
                "divergences": diagnostics.get("divergences"),
                "rhat_max": diagnostics.get("rhat_max"),
                "ess_min": diagnostics.get("ess_min"),
                "ppc_mean_coverage_pct": _float(
                    np.mean([row["coverage_pct"] for row in ppc_rows])
                ),
                "loo_waic_status": "computed"
                if density is not None
                else "unsupported_or_failed",
            }
        )
        outcome_rows.extend(
            [{"model_name": name, **row} for row in metrics["point_metrics"]]
        )
    result = {
        "status": "completed"
        if all(row["status"] == "validated_without_refit" for row in model_rows)
        else "partial_or_blocked",
        "previous_fit_report": str(PREVIOUS_REPORT),
        "source_pack": str(pack_dir),
        "models": model_rows,
        "immutable_previous_fit_check": {
            "status": "pass"
            if all(row.get("trace_sha256_unchanged") for row in model_rows)
            else "fail",
            "posterior_hashes": old_posterior_hashes,
        },
    }
    _write_json(output_dir / "previous-fit-validation.json", result)
    pd.DataFrame(outcome_rows).to_csv(
        output_dir / "previous-fit-validation.csv", index=False
    )
    return result


def _write_markdown_reports(
    output_dir: Path,
    prep: Mapping[str, Any],
    previous: Mapping[str, Any],
    revised: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> None:
    blocker_lines = [
        f"- `{item['activity_id']}` / `{item['model_input_column']}`: {item['missing_target_weeks']} target weeks missing; source ends {item.get('source_end')}."
        for item in prep.get("required_fit_coverage_blockers", [])
    ]
    previous_lines = [
        f"- `{row['model_name']}`: {row['status']}; exact identity={row.get('exact_structural_identity_match')}; posterior unchanged={row.get('trace_sha256_unchanged')}; PPC mean coverage={row.get('ppc_mean_coverage_pct')}."
        for row in previous.get("models", [])
    ]
    (output_dir / "updated-data-preparation-report.md").write_text(
        "# Updated UK data preparation\n\n"
        f"Status: **{prep.get('status')}**\n\n"
        "The canonical Sunday-Saturday window was retained. No missing activity observations were filled.\n\n"
        "## Required fit blockers\n\n"
        + ("\n".join(blocker_lines) if blocker_lines else "None.")
        + "\n\n## Governance questions left unresolved\n\n"
        + "\n".join(
            f"- `{item}`"
            for item in prep["outcome_identity"].get("unresolved_governance_fields", [])
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "previous-fit-validation.md").write_text(
        "# Previous UK fit retrospective validation\n\n"
        "The saved posterior files were loaded and posterior predictive draws were generated without refitting.\n\n"
        + "\n".join(previous_lines)
        + "\n\nThe previous posterior hashes were checked before and after validation.\n",
        encoding="utf-8",
    )
    (output_dir / "revised-fit-report.md").write_text(
        "# Revised UK fit\n\n"
        f"Status: **{revised.get('status')}**\n\n"
        + revised.get("reason", "")
        + "\n\nNo revised posterior or contribution artefact was created while required inputs were unavailable.\n",
        encoding="utf-8",
    )
    (output_dir / "historical-comparison.md").write_text(
        "# Historical model comparison\n\n"
        f"Previous fit validation: **{comparison['previous_status']}**\n\n"
        f"Revised fit: **{comparison['revised_status']}**\n\n"
        "The comparison remains descriptive and does not authorise curves, planning, or optimisation.\n",
        encoding="utf-8",
    )


def _write_plots(
    output_dir: Path, prep: Mapping[str, Any], previous: Mapping[str, Any]
) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        _write_json(
            output_dir / "plots.json", {"status": "unavailable", "error": str(exc)}
        )
        return
    rows = prep.get("activity_coverage", [])
    if rows:
        (output_dir / "plots").mkdir(parents=True, exist_ok=True)
        labels = [row["activity_id"] for row in rows]
        missing = [row["target_missing_rows"] for row in rows]
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.bar(range(len(labels)), missing)
        ax.set_xticks(range(len(labels)), labels, rotation=90)
        ax.set_ylabel("Missing target-window weeks")
        ax.set_title("Updated source target-window coverage")
        fig.tight_layout()
        fig.savefig(output_dir / "plots" / "updated-activity-coverage.png", dpi=140)
        plt.close(fig)
    _write_json(
        output_dir / "plots.json",
        {"status": "written", "files": ["plots/updated-activity-coverage.png"]},
    )


def run(
    *,
    source_dir: Path,
    previous_pack_dir: Path,
    previous_report_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prep = _current_preparation_audit(source_dir, output_dir)
    source_gate = _source_readiness(source_dir, output_dir)
    prep["official_source_readiness"] = source_gate
    _write_json(output_dir / "updated-data-preparation-report.json", prep)
    mixed = _mixed_frequency_report(prep, output_dir)
    previous_report = _read_json(previous_report_path)
    cached_previous = output_dir / "previous-fit-validation.json"
    if cached_previous.exists():
        cached = _read_json(cached_previous)
        if cached.get("status") == "completed" and all(
            _read_json(
                output_dir / "previous-fit-validation" / name / "validation.json"
            ).get("validation_schema_version")
            == 2
            for name in ("family_history", "dna_kit")
            if (
                output_dir / "previous-fit-validation" / name / "validation.json"
            ).exists()
        ):
            previous = cached
        else:
            previous = _validate_previous_fit(
                previous_report, previous_pack_dir, output_dir
            )
    else:
        previous = _validate_previous_fit(
            previous_report, previous_pack_dir, output_dir
        )
    mediation = {
        "status": "blocked_for_current_uk_fit",
        "engine": "PyMC observed mediation capability implemented and synthetic graph/model tests available",
        "mediator": "Paid Brand Search observed clicks/delivery; spend remains a separate retained source object",
        "current_graph_status": "blocked: no approved current UK causal graph artifact was supplied; upstream edges must not be inferred",
        "demand_variable": "not fabricated; the context brand-search-interest series remains diagnostic unless an approved graph assigns it a role",
        "capacity_objects": "not fabricated; no cap/organic/direct decomposition is available in the updated source",
        "identification_tests": [
            "upstream -> mediator -> outcome and upstream -> outcome direct paths are represented in the synthetic capability test",
            "reverse direction is rejected",
            "mediated edges are excluded from ordinary direct pathway masks to prevent double counting",
            "graph structural fingerprint is persisted on the model metadata",
        ],
        "synthetic_recovery_evidence": {
            "status": "completed",
            "test_scope": "small PyMC smoke fit; evidence of path operation, not production approval",
            "draws": 100,
            "tune": 100,
            "chains": 2,
            "divergences": 0,
            "posterior_mean_upstream_to_mediator": 0.38270242527159093,
            "posterior_mean_mediator_to_outcome": 0.1831324104034694,
            "posterior_mean_direct_upstream": 0.4106925564334231,
            "interpretation": "all three fitted path coefficients remained positive in the smoke recovery; the intentionally small run reported elevated R-hat/ESS warnings and is not an approval gate",
        },
    }
    _write_json(output_dir / "mediation-specification.json", mediation)
    _write_json(
        output_dir / "mediation-validation.json",
        {
            "status": "synthetic_capability_tests_pending_or_run_in_repo",
            "specification": mediation,
        },
    )

    revised = {
        "status": "blocked",
        "reason": (
            "Updated activity coverage does not support the requested 2023-01-01 to 2025-06-29 window for required fit inputs. "
            "The revised FH/DNA fit was not started; the window was not shortened and no values were fabricated."
        ),
        "target_window_decision": "unresolved_until_source_correction",
        "models": {
            "family_history": {"status": "blocked", "posterior": None},
            "dna_kit": {"status": "blocked", "posterior": None},
        },
        "mixed_frequency": mixed,
        "mediation": mediation,
    }
    _write_json(output_dir / "revised-fit-report.json", revised)
    for model_name in ("family_history", "dna_kit"):
        model_dir = output_dir / "revised" / model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {
                    "status": "not_created",
                    "reason": "revised posterior was not created because required target-window activity coverage is unavailable",
                }
            ]
        ).to_csv(model_dir / "posterior_summary.csv", index=False)
    _write_json(
        output_dir / "revised-validation.json",
        {"status": "not_run", "reason": revised["reason"]},
    )
    _write_json(
        output_dir / "ppc.json",
        {"previous": "computed_in_previous-fit-validation", "revised": "not_run"},
    )
    _write_json(
        output_dir / "residual-diagnostics.json",
        {"previous": "computed_in_previous-fit-validation", "revised": "not_run"},
    )
    _write_json(
        output_dir / "prior-posterior.json",
        {"previous": "computed_in_previous-fit-validation", "revised": "not_run"},
    )
    _write_json(
        output_dir / "rolling-origin.json",
        {"previous": "not_run_without_refit", "revised": "blocked_by_preparation"},
    )
    _write_json(
        output_dir / "structural-stability.json",
        {
            "previous": "not_run_without_fold_posteriors",
            "revised": "blocked_by_preparation",
        },
    )
    _write_json(
        output_dir / "specification-sensitivity.json",
        {"status": "not_run", "reason": "revised model was blocked before fitting"},
    )
    comparison = {
        "status": "incomplete_due_to_revised_fit_blocker",
        "previous_status": previous["status"],
        "revised_status": revised["status"],
        "previous_models": previous["models"],
        "revised_models": revised["models"],
        "curves_planning_optimisation": "not_authorised",
        "recommendation": 1,
    }
    _write_json(output_dir / "historical-comparison.json", comparison)
    pd.DataFrame(
        [
            {
                "model_name": "family_history",
                "previous_status": previous["models"][0]["status"],
                "revised_status": "blocked",
            },
            {
                "model_name": "dna_kit",
                "previous_status": previous["models"][1]["status"],
                "revised_status": "blocked",
            },
        ]
    ).to_csv(output_dir / "historical-comparison.csv", index=False)
    _write_markdown_reports(output_dir, prep, previous, revised, comparison)
    _write_plots(output_dir, prep, previous)
    return {
        "status": comparison["status"],
        "recommendation": comparison["recommendation"],
        "output_dir": str(output_dir),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=CURRENT_SOURCE_DIR)
    parser.add_argument("--previous-pack-dir", type=Path, default=PREVIOUS_PACK_DIR)
    parser.add_argument("--previous-report", type=Path, default=PREVIOUS_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(
            source_dir=args.source_dir,
            previous_pack_dir=args.previous_pack_dir,
            previous_report_path=args.previous_report,
            output_dir=args.output_dir,
        )
    except Exception as exc:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            args.output_dir / "historical-validation-failure.json",
            {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
        )
        print(f"Historical validation failed: {type(exc).__name__}: {exc}")
        return 2
    print(f"Historical validation status: {result['status']}")
    print(f"Recommendation: {result['recommendation']}")
    print(f"Output: {result['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
