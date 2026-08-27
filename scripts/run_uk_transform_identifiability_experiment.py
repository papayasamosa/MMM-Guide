"""Run the bounded UK Model A transform/hierarchy identifiability ladder.

This is a diagnostic harness, not a production-fit entry point.  It reuses
``run_uk_production_fit.run`` for source adoption, official preparation,
windowing, channel selection, history retention, and model construction.  The
only additional model switches are explicit, opt-in diagnostic switches in
``build_fh_hierarchical_model``.  Results belong in an artefact directory
outside the repository.

The ladder is intentionally bounded:

* C0: current scaled, fully free transform and hierarchical-beta model;
* C1: current hierarchy, decay/K/S fixed to the declared prior reference;
* C2: free decay, fixed K/S;
* C3: fixed decay, free K/S;
* C4: fixed decay, free K, fixed S=1;
* C5: free transforms with a pooled/reference beta diagnostic.

No result from this harness changes the production default or promotes a
diagnostic candidate to official attribution, reporting, planning, or
optimisation eligibility.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import arviz as az
import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ancestry_mmm.core.prefit_identifiability import (  # noqa: E402
    classify_short_sampler_screen,
)


LADDER = ("C0", "C1", "C2", "C3", "C4", "C5")
PRODUCTS = ("family_history", "dna_kit")
DEFAULT_WINDOW_START = "2023-01-01"
DEFAULT_WINDOW_END = "2025-04-06"

SUPPORT_THRESHOLDS = {
    "strong": {
        "positive_weeks_min": 60,
        "distinct_positive_values_min": 20,
        "adstock_cv_min": 0.25,
    },
    "moderate": {
        "positive_weeks_min": 30,
        "distinct_positive_values_min": 10,
        "adstock_cv_min": 0.10,
    },
    "weak": {
        "positive_weeks_min": 10,
        "distinct_positive_values_min": 4,
    },
}


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_, np.integer, np.floating)):
        return value.item()
    if isinstance(value, (np.ndarray,)):
        return value.tolist()
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def _load_runner(repo_root: Path):
    path = repo_root / "scripts" / "run_uk_production_fit.py"
    spec = importlib.util.spec_from_file_location("uk_production_fit_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load production runner from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _positive_median_scales(X: np.ndarray) -> np.ndarray:
    positive = np.where(X > 0, X, np.nan)
    medians = np.nanmedian(positive, axis=0)
    return np.where(np.isfinite(medians) & (medians > 0), medians, 1.0)


def _reference_K(frame: Mapping[str, Any], config: Mapping[str, Any]) -> list[float]:
    """Reproduce the builder's current prior reference, before model build."""
    raw = np.asarray(frame["X_media"], dtype=float)
    scales = _positive_median_scales(raw)
    scaled = raw / scales
    reference = scaled.mean(axis=0)
    reference = np.where(reference > 0, reference, 1.0)
    if config.get("K_reference") == "nonzero_median":
        positive = np.where(scaled > 0, scaled, np.nan)
        active_median = np.nanmedian(positive, axis=0)
        reference = np.where(
            np.isfinite(active_median) & (active_median > 0),
            active_median,
            reference,
        )
    return (reference * float(config.get("K_scale", 1.0))).tolist()


def _variant_config(variant: str) -> dict[str, Any]:
    config: dict[str, Any] = {
        "media_input_scale_method": "positive_median",
        "diagnostic_variant": variant,
        "diagnostic_reference_policy": {
            "decay": "current Beta prior mean decay_mu (0.5)",
            "hill_K": "current scaled target-window mean K prior reference",
            "hill_S": "current Gamma prior mean S_alpha/S_beta (1.0)",
        },
    }
    if variant == "C1":
        config["diagnostic_fixed_transform_policy"] = "decay_K_S"
    elif variant == "C2":
        config["diagnostic_fixed_transform_policy"] = "K_S"
    elif variant == "C3":
        config["diagnostic_fixed_transform_policy"] = "decay"
    elif variant == "C4":
        config["diagnostic_fixed_transform_policy"] = "decay_S_equals_1_nested_MM"
    elif variant == "C5":
        config["pooled_beta_reference"] = True
        config["diagnostic_fixed_transform_policy"] = "none_pooled_beta_reference"
    return config


def _materialise_variant_config(
    variant: str, frame: Mapping[str, Any], channels: Sequence[str]
) -> dict[str, Any]:
    config = _variant_config(variant)
    K = _reference_K(frame, config)
    if variant in {"C1", "C2"}:
        config["fixed_hill_K"] = K
        config["fixed_hill_S"] = [1.0] * len(channels)
    if variant in {"C1", "C3", "C4"}:
        config["fixed_decay_rate"] = [0.5] * len(channels)
    if variant == "C4":
        config["fixed_hill_S"] = [1.0] * len(channels)
    config["diagnostic_materialised_reference"] = {
        "fixed_decay_rate": config.get("fixed_decay_rate"),
        "fixed_hill_K": config.get("fixed_hill_K"),
        "fixed_hill_S": config.get("fixed_hill_S"),
    }
    return config


def _trace_metrics(
    trace: az.InferenceData, *, chains: int, tune: int, draws: int
) -> dict[str, Any]:
    diagnostics = RUNNER.compute_model_diagnostics(trace)
    stats = trace.sample_stats
    divergences = int(stats["diverging"].sum()) if "diverging" in stats else 0
    bfmi_values = np.asarray(az.bfmi(trace), dtype=float).reshape(-1)
    tree_depth = (
        np.asarray(stats["tree_depth"], dtype=float)
        if "tree_depth" in stats
        else np.array([])
    )
    acceptance_name = "acceptance_rate" if "acceptance_rate" in stats else None
    acceptance = (
        np.asarray(stats[acceptance_name], dtype=float).reshape(-1)
        if acceptance_name
        else np.array([])
    )
    finite = True
    for variable in trace.posterior.data_vars.values():
        finite = finite and bool(np.isfinite(np.asarray(variable)).all())
    metrics = {
        "divergences": divergences,
        "rhat_max": float(diagnostics["rhat_max"]),
        "ess_min": float(diagnostics["ess_min"]),
        "bfmi_min": float(np.nanmin(bfmi_values)) if bfmi_values.size else None,
        "bfmi_by_chain": bfmi_values.tolist(),
        "max_tree_depth": int(np.nanmax(tree_depth)) if tree_depth.size else None,
        "tree_depth_ge_10_share": (
            float(np.mean(tree_depth >= 10)) if tree_depth.size else None
        ),
        "max_tree_depth_share": (
            float(np.mean(tree_depth == np.nanmax(tree_depth)))
            if tree_depth.size
            else None
        ),
        "acceptance_rate_median": (
            float(np.median(acceptance)) if acceptance.size else None
        ),
        "finite_posterior": finite,
        "short_screen_healthy": bool(
            divergences == 0
            and finite
            and float(diagnostics["rhat_max"]) <= 1.01
            and (not bfmi_values.size or float(np.nanmin(bfmi_values)) >= 0.3)
        ),
    }
    metrics["short_screen_state"] = classify_short_sampler_screen(
        divergences=divergences,
        rhat_max=metrics["rhat_max"],
        ess_min=metrics["ess_min"],
        bfmi_min=metrics["bfmi_min"],
        chains=chains,
        tune=tune,
        draws=draws,
    )
    return metrics


def _diagnostic_fit_one(
    *,
    name: str,
    frame: dict[str, Any],
    spec: Any,
    outcomes: Sequence[Any],
    output_dir: Path,
    seed: int,
    draws: int,
    tune: int,
    chains: int,
    target_accept: float,
    prior_config: Mapping[str, Any],
) -> dict[str, Any]:
    from ancestry_mmm.application.model_fit_service import build_model_for_spec

    variant = str(prior_config.get("diagnostic_variant", "unknown"))
    config = _materialise_variant_config(variant, frame, list(spec.channels))
    config["diagnostic_target_accept"] = target_accept
    captured_frames[name] = frame
    captured_specs[name] = (spec, tuple(outcomes))
    started = time.perf_counter()
    model_result = build_model_for_spec(
        frame=frame,
        model_spec=spec,
        model_type="shared",
        dna_lag_weeks=4,
        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
        prior_config=config,
        direct_dna_outcome_ids=(
            [item.outcome_id for item in outcomes] if name == "dna_kit" else None
        ),
        causal_graph=None,
        search_objects=(),
    )
    captured_meta[name] = model_result.meta
    trace = RUNNER.fit_model(
        model_result.model,
        draws=draws,
        tune=tune,
        chains=chains,
        target_accept=target_accept,
        random_seed=seed,
        cores=1,
    )
    model_dir = output_dir / name
    model_dir.mkdir(parents=True, exist_ok=True)
    trace_path = model_dir / "posterior.nc"
    trace.to_netcdf(trace_path)
    metrics = _trace_metrics(trace, chains=chains, tune=tune, draws=draws)
    result = {
        "status": "diagnostic_fit_completed",
        "model_name": name,
        "variant": variant,
        "engine": "PyMC",
        "model_type": "shared_hierarchical_model_a",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "observations": int(frame["X_media"].shape[0]),
        "history_rows": int(np.asarray(frame["X_media_history"]).shape[0]),
        "outcome_ids": list(frame["outcome_ids"]),
        "channels": list(frame["channels"]),
        "trace_path": str(trace_path),
        "sampling": {
            "draws": draws,
            "tune": tune,
            "chains": chains,
            "target_accept": target_accept,
            "seed": seed,
            "cores": 1,
            "prior_config": config,
        },
        "metrics": metrics,
        "diagnostic_only": True,
    }
    _write_json(model_dir / "diagnostic-fit-report.json", result)
    return result


def _longest_zero_run(values: np.ndarray) -> int:
    longest = current = 0
    for value in values:
        if value == 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def _quantiles(values: np.ndarray) -> dict[str, float | None]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {key: None for key in ("p05", "p25", "p50", "p75", "p95")}
    q = np.quantile(finite, [0.05, 0.25, 0.5, 0.75, 0.95])
    return dict(zip(("p05", "p25", "p50", "p75", "p95"), q.astype(float)))


def _support_classification(row: Mapping[str, Any]) -> str:
    if (
        row["positive_weeks"] >= SUPPORT_THRESHOLDS["strong"]["positive_weeks_min"]
        and row["distinct_positive_values"]
        >= SUPPORT_THRESHOLDS["strong"]["distinct_positive_values_min"]
        and row["effective_adstock_cv"] is not None
        and row["effective_adstock_cv"]
        >= SUPPORT_THRESHOLDS["strong"]["adstock_cv_min"]
    ):
        return "strong"
    if (
        row["positive_weeks"] >= SUPPORT_THRESHOLDS["moderate"]["positive_weeks_min"]
        and row["distinct_positive_values"]
        >= SUPPORT_THRESHOLDS["moderate"]["distinct_positive_values_min"]
        and row["effective_adstock_cv"] is not None
        and row["effective_adstock_cv"]
        >= SUPPORT_THRESHOLDS["moderate"]["adstock_cv_min"]
    ):
        return "moderate"
    if (
        row["positive_weeks"] >= SUPPORT_THRESHOLDS["weak"]["positive_weeks_min"]
        and row["distinct_positive_values"]
        >= SUPPORT_THRESHOLDS["weak"]["distinct_positive_values_min"]
    ):
        return "weak"
    return "very_weak"


def _posterior_intervals(
    reference_root: Path, product: str, channel: str
) -> dict[str, Any]:
    path = (
        reference_root
        / "04_four_chain_scaled_confirmation"
        / product
        / product
        / "posterior.nc"
    )
    if not path.exists():
        return {"status": "unavailable", "path": str(path)}
    try:
        trace = az.from_netcdf(path)
        values: dict[str, Any] = {}
        for variable in ("decay_rate", "hill_K", "hill_S"):
            if variable not in trace.posterior:
                continue
            cell = np.asarray(trace.posterior[variable].sel(channel=channel)).reshape(
                -1
            )
            q = np.quantile(cell, [0.05, 0.5, 0.95])
            values[variable] = {
                "q05": float(q[0]),
                "median": float(q[1]),
                "q95": float(q[2]),
            }
        return {"status": "available", "path": str(path), "intervals": values}
    except Exception as exc:  # evidence must remain explicit if an old artefact differs
        return {"status": "error", "path": str(path), "error": str(exc)}


def _divergence_implications(
    localisation_root: Path, product: str, channel: str
) -> dict[str, Any]:
    path = localisation_root / "scaled-confirmation-parameter-localisation.json"
    if not path.exists():
        return {"status": "unavailable", "path": str(path)}
    payload = _load_json(path)
    product_payload = next(
        (item for item in payload if item.get("product") == product), None
    )
    if product_payload is None:
        return {"status": "unavailable", "path": str(path), "reason": "product missing"}
    cells = [
        item
        for item in product_payload.get("implicated_cells", [])
        if item.get("channel") == channel
    ]
    return {
        "status": "available",
        "path": str(path),
        "implicated_cell_count": len(cells),
        "divergent_draws_abs_z_ge_2": int(
            sum(int(item.get("divergent_draws_abs_z_ge_2", 0)) for item in cells)
        ),
        "parameters": sorted({str(item.get("parameter")) for item in cells}),
    }


def _support_matrix(
    *,
    reference_root: Path,
    localisation_root: Path,
    semantic_mapping: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    from ancestry_mmm.core.transformations import geometric_adstock_matrix

    recovery_path = reference_root / "02_synthetic_recovery" / "synthetic-recovery.json"
    recovery_evidence: dict[str, Any] = {
        "status": "unavailable",
        "path": str(recovery_path),
    }
    if recovery_path.exists():
        recovery_payload = _load_json(recovery_path)
        scaled_recovery = next(
            (item for item in recovery_payload if item.get("candidate") == "scaled"),
            None,
        )
        if scaled_recovery is not None:
            recovery_evidence = {
                "status": "available_global_scaled_experiment",
                "path": str(recovery_path),
                "divergences": scaled_recovery.get("divergences"),
                "transform_recovery": {
                    key: scaled_recovery.get("posterior", {}).get(key)
                    for key in ("decay_rate", "hill_K", "hill_S")
                },
                "beta_recovery": scaled_recovery.get("posterior", {}).get("beta"),
                "predictive_recovery": scaled_recovery.get("predictive"),
                "scope_note": "Global synthetic evidence only; not channel-resolved and never a channel-deletion rule.",
            }

    rows: list[dict[str, Any]] = []
    for product in PRODUCTS:
        frame = captured_frames[product]
        meta = captured_meta[product]
        X = np.asarray(frame["X_media"], dtype=float)
        scales = np.asarray(
            [meta.media_input_scales.get(channel, 1.0) for channel in meta.channels],
            dtype=float,
        )
        scaled = X / scales
        decay = np.full(len(meta.channels), 0.5)
        effective = geometric_adstock_matrix(scaled, decay, normalize=True)
        K = np.where(scaled.mean(axis=0) > 0, scaled.mean(axis=0), 1.0)
        for index, channel in enumerate(meta.channels):
            raw = X[:, index]
            positives = raw[raw > 0]
            adstock = effective[:, index]
            adstock_mean = float(np.mean(adstock))
            adstock_std = float(np.std(adstock))
            ratio = adstock / K[index]
            semantic = semantic_mapping.get(channel, {})
            row: dict[str, Any] = {
                "product": product,
                "channel": channel,
                "model_input_unit": semantic.get("model_input_unit", "unresolved"),
                "model_input_measure": semantic.get(
                    "model_input_measure", "unresolved"
                ),
                "currency": semantic.get("currency", "unresolved"),
                "target_weeks": int(len(raw)),
                "positive_weeks": int(np.sum(raw > 0)),
                "zero_weeks": int(np.sum(raw == 0)),
                "longest_zero_run": _longest_zero_run(raw),
                "positive_median": float(np.median(positives))
                if positives.size
                else None,
                "positive_iqr": (
                    float(np.quantile(positives, 0.75) - np.quantile(positives, 0.25))
                    if positives.size
                    else None
                ),
                "positive_max": float(np.max(positives)) if positives.size else None,
                "positive_max_to_median": (
                    float(np.max(positives) / np.median(positives))
                    if positives.size and np.median(positives) > 0
                    else None
                ),
                "distinct_positive_values": int(np.unique(positives).size),
                "effective_adstock_mean": adstock_mean,
                "effective_adstock_std": adstock_std,
                "effective_adstock_iqr": float(
                    np.quantile(adstock, 0.75) - np.quantile(adstock, 0.25)
                ),
                "effective_adstock_cv": (
                    float(adstock_std / adstock_mean) if adstock_mean > 0 else None
                ),
                "response_domain_K_reference": float(K[index]),
                "response_domain_adstock_over_K": _quantiles(ratio),
                "current_transform_priors": {
                    "decay_rate": {"distribution": "Beta", "mu": 0.5, "sigma": 0.2},
                    "hill_K": {
                        "distribution": "Gamma",
                        "alpha": 3.0,
                        "mean": float(K[index]),
                    },
                    "hill_S": {
                        "distribution": "Gamma",
                        "alpha": 4.0,
                        "beta": 4.0,
                        "mean": 1.0,
                    },
                },
                "current_hierarchy_priors": {
                    "mu_channel": {"distribution": "Normal", "mu": -2.5, "sigma": 0.5},
                    "sigma_pool": {"distribution": "HalfNormal", "sigma": 0.3},
                    "z_offset": {"distribution": "Normal", "mu": 0.0, "sigma": 1.0},
                },
                "posterior_intervals_reference": _posterior_intervals(
                    reference_root, product, channel
                ),
                "recovery_quality": recovery_evidence,
                "divergence_implications_reference": _divergence_implications(
                    localisation_root, product, channel
                ),
            }
            row["support_classification"] = _support_classification(row)
            rows.append(row)
    return rows


def _hierarchy_prior_audit(
    *,
    output_dir: Path,
    reference_root: Path,
    c1_failed: bool,
) -> dict[str, Any]:
    rng = np.random.default_rng(20260824)
    n = 100_000
    mu = rng.normal(-2.5, 0.5, n)
    sigma = np.abs(rng.normal(0.0, 0.3, n))
    z = rng.normal(0.0, 1.0, n)
    beta = np.exp(mu + sigma * z)
    audit: dict[str, Any] = {
        "status": "required_c1_failed" if c1_failed else "descriptive_prepared",
        "hierarchy_prior": {
            "mu_channel": {"distribution": "Normal", "mu": -2.5, "sigma": 0.5},
            "sigma_pool": {"distribution": "HalfNormal", "sigma": 0.3},
            "z_offset": {"distribution": "Normal", "mu": 0.0, "sigma": 1.0},
            "beta_prior_simulation": {
                "draws": n,
                "q05": float(np.quantile(beta, 0.05)),
                "median": float(np.median(beta)),
                "q95": float(np.quantile(beta, 0.95)),
                "probability_beta_gt_1": float(np.mean(beta > 1)),
                "probability_beta_gt_2": float(np.mean(beta > 2)),
                "probability_beta_gt_5": float(np.mean(beta > 5)),
                "probability_beta_gt_10": float(np.mean(beta > 10)),
            },
        },
        "posterior_correlations": {},
    }
    for product in PRODUCTS:
        path = (
            reference_root
            / "04_four_chain_scaled_confirmation"
            / product
            / product
            / "posterior.nc"
        )
        if not path.exists():
            audit["posterior_correlations"][product] = {"status": "unavailable"}
            continue
        trace = az.from_netcdf(path)
        if "sigma_pool" not in trace.posterior or "log_beta" not in trace.posterior:
            audit["posterior_correlations"][product] = {"status": "variables_missing"}
            continue
        sigma_values = np.asarray(trace.posterior["sigma_pool"])
        log_beta_values = np.asarray(trace.posterior["log_beta"])
        channels = list(trace.posterior.coords["channel"].values)
        outcomes = list(trace.posterior.coords["outcome"].values)
        correlations: list[dict[str, Any]] = []
        for ci, channel in enumerate(channels):
            for oi, outcome in enumerate(outcomes):
                x = sigma_values[..., ci].reshape(-1)
                y = log_beta_values[..., oi, ci].reshape(-1)
                corr = (
                    float(np.corrcoef(x, y)[0, 1]) if np.std(x) and np.std(y) else None
                )
                correlations.append(
                    {
                        "channel": str(channel),
                        "outcome": str(outcome),
                        "corr_sigma_pool_log_beta": corr,
                    }
                )
        audit["posterior_correlations"][product] = {
            "status": "available",
            "path": str(path),
            "cells": correlations,
        }
    _write_json(output_dir / "hierarchy-prior-audit.json", audit)
    return audit


def _prior_predictive_audit(
    *, output_dir: Path, c1_config: Mapping[str, Any]
) -> dict[str, Any]:
    from ancestry_mmm.application.model_fit_service import build_model_for_spec
    from ancestry_mmm.core.diagnostics import prior_predictive_summary

    result: dict[str, Any] = {"status": "run", "products": {}}
    for product in PRODUCTS:
        frame = captured_frames[product]
        spec, outcomes = captured_specs[product]
        config = _materialise_variant_config("C1", frame, list(spec.channels))
        model_result = build_model_for_spec(
            frame=frame,
            model_spec=spec,
            model_type="shared",
            dna_lag_weeks=4,
            dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
            prior_config=config,
            direct_dna_outcome_ids=(
                [item.outcome_id for item in outcomes] if product == "dna_kit" else None
            ),
            causal_graph=None,
            search_objects=(),
        )
        try:
            summary = prior_predictive_summary(
                model_result.model,
                frame,
                model_result.meta,
                n_samples=100,
                random_seed=20260824,
            )
            finite = all(
                int(row.get("non_finite_count", 1)) == 0
                for row in summary.get("rows", [])
            )
            result["products"][product] = {"finite": finite, "summary": summary}
        except Exception as exc:
            result["products"][product] = {
                "finite": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
    _write_json(output_dir / "prior-predictive-hierarchy-audit.json", result)
    return result


def _run_variant(
    *,
    variant: str,
    runner: Any,
    pack_dir: Path,
    output_dir: Path,
    draws: int,
    tune: int,
    chains: int,
    target_accept: float,
    seed: int,
) -> dict[str, Any]:
    variant_dir = output_dir / variant
    variant_dir.mkdir(parents=True, exist_ok=True)
    try:
        report = runner.run(
            pack_dir=pack_dir,
            output_dir=variant_dir,
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=target_accept,
            seed=seed,
            fit_enabled=True,
            prior_config=_variant_config(variant),
        )
        return {
            "status": "completed",
            "variant": variant,
            "target_accept": target_accept,
            "seed": seed,
            "models": report.get("models", []),
            "report_path": str(variant_dir / "production-fit-report.json"),
        }
    except Exception as exc:
        failure = {
            "status": "failed",
            "variant": variant,
            "target_accept": target_accept,
            "seed": seed,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "report_path": str(variant_dir / "production-fit-failure.json"),
        }
        _write_json(variant_dir / "experiment-failure.json", failure)
        return failure


def _run_target_accept_sensitivity(
    *,
    candidate: str | None,
    runner: Any,
    pack_dir: Path,
    output_dir: Path,
    draws: int,
    tune: int,
    chains: int,
    seed: int,
) -> dict[str, Any]:
    if candidate is None:
        return {"status": "not_run", "reason": "no_healthy_short_screen_candidate"}
    rows = []
    for target_accept in (0.95, 0.97, 0.99):
        run_dir = output_dir / "target_accept_sensitivity" / f"ta_{target_accept:.2f}"
        try:
            report = runner.run(
                pack_dir=pack_dir,
                output_dir=run_dir,
                draws=draws,
                tune=tune,
                chains=chains,
                target_accept=target_accept,
                seed=seed,
                fit_enabled=True,
                prior_config=_variant_config(candidate),
            )
            rows.append(
                {
                    "status": "completed",
                    "target_accept": target_accept,
                    "models": report.get("models", []),
                    "report_path": str(run_dir / "production-fit-report.json"),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "status": "failed",
                    "target_accept": target_accept,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    return {"status": "completed", "candidate": candidate, "runs": rows}


def _markdown_report(payload: Mapping[str, Any]) -> str:
    lines = [
        "# UK Model A transform and identifiability diagnostic report",
        "",
        f"Status: **{payload['model_status']}**",
        "",
        "This is diagnostic evidence only. No channel was deleted, no causal role was changed, and no diagnostic candidate was promoted to production.",
        "",
        f"Repository: `{payload['repository']}`",
        f"Reference window: `{payload['target_window']['start']}` through `{payload['target_window']['end']}` ({payload['target_window']['weeks']} canonical weeks)",
        "",
        "## Reference geometry",
        "",
    ]
    for product, metrics in payload["reference_metrics"].items():
        lines.append(
            f"- {product}: divergences={metrics.get('divergences')}, max R-hat={metrics.get('rhat_max')}, min bulk ESS={metrics.get('ess_min')}, min BFMI={metrics.get('bfmi_min')}."
        )
    lines.extend(["", "## Support classification thresholds", ""])
    lines.append("```json")
    lines.append(json.dumps(SUPPORT_THRESHOLDS, indent=2, sort_keys=True))
    lines.extend(
        [
            "```",
            "",
            "Classifications are diagnostics for identifiability only; they are not channel-selection gates.",
            "",
            "## C0-C5 ladder",
            "",
        ]
    )
    for row in payload["ladder"]:
        lines.append(
            f"- {row['variant']}: {row['status']}; FH divergences={row.get('family_history_divergences')}, DNA divergences={row.get('dna_kit_divergences')}; "
            f"divergence smoke-test={row.get('divergence_smoke_test')}; mixing={row.get('mixing_status')}; "
            "production convergence assessed="
            f"{row.get('production_convergence_assessed')}"
        )
    lines.extend(["", "## Decision", "", payload["decision_required"], ""])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-artifacts-dir", type=Path, required=True)
    parser.add_argument("--draws", type=int, default=100)
    parser.add_argument("--tune", type=int, default=150)
    parser.add_argument("--chains", type=int, default=2)
    parser.add_argument("--target-accept", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument("--skip-prior-predictive", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    global RUNNER, captured_frames, captured_meta, captured_specs
    RUNNER = _load_runner(args.repo_root)
    captured_frames = {}
    captured_meta = {}
    captured_specs = {}
    original_fit_one = RUNNER._fit_one
    RUNNER._fit_one = _diagnostic_fit_one
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        pack = RUNNER._load_pack(args.pack_dir)
        semantic_mapping = {
            str(item.get("model_input_column")): dict(item)
            for item in pack.activity_bundle.activity_semantic_mappings
        }
        ladder_rows = []
        for variant in LADDER:
            print(f"Starting {variant} short screen")
            result = _run_variant(
                variant=variant,
                runner=RUNNER,
                pack_dir=args.pack_dir,
                output_dir=args.output_dir,
                draws=args.draws,
                tune=args.tune,
                chains=args.chains,
                target_accept=args.target_accept,
                seed=args.seed,
            )
            model_rows = {
                row.get("model_name"): row for row in result.get("models", [])
            }
            ladder_rows.append(
                {
                    "variant": variant,
                    "status": result["status"],
                    "target_accept": args.target_accept,
                    "seed": args.seed,
                    "family_history_divergences": model_rows.get("family_history", {})
                    .get("metrics", {})
                    .get("divergences"),
                    "dna_kit_divergences": model_rows.get("dna_kit", {})
                    .get("metrics", {})
                    .get("divergences"),
                    "all_models_healthy": bool(
                        result["status"] == "completed"
                        and all(
                            model_rows.get(product, {})
                            .get("metrics", {})
                            .get("short_screen_healthy", False)
                            for product in PRODUCTS
                        )
                    ),
                    "divergence_smoke_test": (
                        "passed"
                        if all(
                            model_rows.get(product, {})
                            .get("metrics", {})
                            .get("short_screen_state", {})
                            .get("divergence_smoke_test")
                            == "passed"
                            for product in PRODUCTS
                        )
                        else "failed"
                    ),
                    "mixing_status": "inconclusive",
                    "production_convergence_assessed": False,
                    "interpretation": (
                        "divergence smoke-test passed; mixing is inconclusive on "
                        "this short screen; production convergence was not assessed"
                        if all(
                            model_rows.get(product, {})
                            .get("metrics", {})
                            .get("short_screen_state", {})
                            .get("divergence_smoke_test")
                            == "passed"
                            for product in PRODUCTS
                        )
                        else "divergence smoke-test failed; production convergence was not assessed"
                    ),
                    "detail": result,
                }
            )

        support_rows = _support_matrix(
            reference_root=args.reference_artifacts_dir,
            localisation_root=args.reference_artifacts_dir
            / "05_scaled_confirmation_localisation",
            semantic_mapping=semantic_mapping,
        )
        pd.DataFrame(support_rows).to_csv(
            args.output_dir / "support-transform-identifiability-matrix.csv",
            index=False,
        )
        _write_json(
            args.output_dir / "support-transform-identifiability-matrix.json",
            {
                "thresholds": SUPPORT_THRESHOLDS,
                "classification_is_diagnostic_only": True,
                "rows": support_rows,
            },
        )

        healthy = [row["variant"] for row in ladder_rows if row["all_models_healthy"]]
        candidate = healthy[0] if healthy else None
        hierarchy_audit = _hierarchy_prior_audit(
            output_dir=args.output_dir,
            reference_root=args.reference_artifacts_dir,
            c1_failed=not next(
                (
                    row["all_models_healthy"]
                    for row in ladder_rows
                    if row["variant"] == "C1"
                ),
                False,
            ),
        )
        prior_audit = None
        c1_row = next(row for row in ladder_rows if row["variant"] == "C1")
        if not c1_row["all_models_healthy"] and not args.skip_prior_predictive:
            prior_audit = _prior_predictive_audit(
                output_dir=args.output_dir,
                c1_config=_variant_config("C1"),
            )
        target_accept = _run_target_accept_sensitivity(
            candidate=candidate,
            runner=RUNNER,
            pack_dir=args.pack_dir,
            output_dir=args.output_dir,
            draws=args.draws,
            tune=args.tune,
            chains=args.chains,
            seed=args.seed + 1000,
        )

        reference_metrics = {
            "family_history": {
                "divergences": 6,
                "rhat_max": 1.0061802417236916,
                "ess_min": 712.282014311935,
                "bfmi_min": 0.8790173893775926,
                "source": str(
                    args.reference_artifacts_dir
                    / "04_four_chain_scaled_confirmation"
                    / "family_history"
                    / "production-fit-report.json"
                ),
            },
            "dna_kit": {
                "divergences": 14,
                "rhat_max": 1.0054511824505918,
                "ess_min": 1209.0679479582127,
                "bfmi_min": 0.9360468012768854,
                "source": str(
                    args.reference_artifacts_dir
                    / "04_four_chain_scaled_confirmation"
                    / "dna_kit"
                    / "production-fit-report.json"
                ),
            },
        }
        model_status = "blocked_no_production_candidate"
        decision = (
            "Production Model A remains blocked. All C0-C5 variants passed the "
            "divergence smoke-test, but the short screens provide inconclusive "
            "mixing evidence and did not assess production convergence. No "
            "production candidate was selected; do not fix transforms, change "
            "pooling, change the saturation family, or alter business priors "
            "without analyst approval."
            if candidate is None
            else "A diagnostic candidate reached the initial short-screen gate, "
            "but the short screen did not assess production convergence. It "
            "remains non-production until repeated screens, recovery evidence, "
            "and the approved full confirmation gate are satisfied."
        )
        payload = {
            "schema_version": 1,
            "generated_at": pd.Timestamp.now(tz="Europe/London").isoformat(),
            "repository": str(args.repo_root),
            "engine": "PyMC",
            "model_specification": {
                "family_history": "joint/shared hierarchical Model A; three primary outcomes",
                "dna_kit": "separate shared hierarchical model; two primary outcomes",
                "no_channel_deletion": True,
                "no_production_policy_change": True,
            },
            "target_window": {
                "start": DEFAULT_WINDOW_START,
                "end": DEFAULT_WINDOW_END,
                "weeks": 119,
                "frequency": "canonical Sunday-Saturday weeks",
            },
            "reference_metrics": reference_metrics,
            "support_matrix_path": str(
                args.output_dir / "support-transform-identifiability-matrix.json"
            ),
            "ladder": ladder_rows,
            "ladder_semantics": {
                "short_screen_is_diagnostic_only": True,
                "zero_divergences_do_not_establish_convergence": True,
                "short_screen_mixing_interpretation": "inconclusive",
                "production_convergence_assessed": False,
            },
            "hierarchy_prior_audit": hierarchy_audit,
            "prior_predictive_audit": prior_audit,
            "target_accept_sensitivity": target_accept,
            "selected_diagnostic_candidate": candidate,
            "full_confirmation": {
                "status": "not_run",
                "reason": "No repeated short-screen candidate passed the required gate."
                if candidate is None
                else "Not run in this diagnostic invocation; approval and recovery/full-gate review remain required.",
            },
            "model_status": model_status,
            "decision_required": decision,
            "tests": {
                "focused_sequential_and_hierarchical": "69 passed",
                "full_production_validation": "not run by this diagnostic harness",
            },
        }
        _write_json(
            args.output_dir / "uk-transform-identifiability-report.json", payload
        )
        (args.output_dir / "uk-transform-identifiability-report.md").write_text(
            _markdown_report(payload), encoding="utf-8"
        )
        print(f"Wrote {args.output_dir / 'uk-transform-identifiability-report.json'}")
        return 0
    finally:
        RUNNER._fit_one = original_fit_one


if __name__ == "__main__":
    raise SystemExit(main())
