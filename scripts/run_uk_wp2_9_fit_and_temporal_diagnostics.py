"""WP2.9 items 4, 5, and the LOO/WAIC/Pareto-k half of item 6
(analyst-directed, 2026-08-25): diagnose the WP2.8 Family History "New"
fit (R^2=0.068), investigate whether the positive residual autocorrelation
found in every outcome reflects a common omitted temporal process, and run
the repository's existing PSIS-LOO/WAIC evidence (`core.diagnostics.
predictive_density_summary`) against the already-saved target_accept=0.90
posterior traces. No new fit, no specification change.

The governed leakage-safe fold-refit backtest (`application.
fold_refit_service.run_leakage_safe_fold_refit[_from_sources]`) is
deliberately NOT run here - see the accompanying findings document for why
it cannot be validly applied to this static historical source pack without
inventing SourceVersion registration data that does not exist for this
one-off exercise.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import arviz as az
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.diagnostics import (  # noqa: E402
    compute_scorecard,
    error_metrics_by_outcome,
    predictive_density_summary,
    residual_temporal_diagnostics,
)
from ancestry_mmm.core.predict import extract_posterior_params, predict_mu  # noqa: E402

DEFAULT_TRACE_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-fit-and-temporal-diagnostics-20260825"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _json_default(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def _acf(x: np.ndarray, nlags: int) -> list[float]:
    x = x - np.mean(x)
    denom = np.dot(x, x)
    if denom == 0:
        return [float("nan")] * nlags
    out = []
    for lag in range(1, nlags + 1):
        out.append(float(np.dot(x[:-lag], x[lag:]) / denom))
    return out


def _pacf_durbin_levinson(acf_values: list[float], nlags: int) -> list[float]:
    """Durbin-Levinson recursion from an already-computed ACF (acf[0] is
    lag 1) - avoids adding a new statistics dependency for a supporting
    diagnostic."""
    r = [1.0] + acf_values
    phi = np.zeros((nlags + 1, nlags + 1))
    phi[1, 1] = r[1]
    pacf = [r[1]]
    for k in range(2, nlags + 1):
        num = r[k] - sum(phi[k - 1, j] * r[k - j] for j in range(1, k))
        den = 1 - sum(phi[k - 1, j] * r[j] for j in range(1, k))
        phi[k, k] = num / den if den != 0 else float("nan")
        for j in range(1, k):
            phi[k, j] = phi[k - 1, j] - phi[k, k] * phi[k - 1, k - j]
        pacf.append(float(phi[k, k]))
    return pacf


def _fh_new_diagnosis(
    frame: dict[str, Any], meta: Any, params: Any, outcome_id: str
) -> dict[str, Any]:
    outcome_ids = list(frame["outcome_ids"])
    o_idx = outcome_ids.index(outcome_id)
    y = np.asarray(frame["Y"], dtype=float)[:, o_idx]
    mu = predict_mu(frame, meta, params)[:, o_idx]
    dates = frame.get("dates")
    date_strs = (
        [str(d)[:10] for d in dates] if dates is not None else list(range(len(y)))
    )

    mean_y = float(np.mean(y))
    median_y = float(np.median(y))
    std_y = float(np.std(y, ddof=1))
    var_y = float(np.var(y, ddof=1))
    cv_y = std_y / mean_y if mean_y != 0 else float("nan")
    range_y = (float(np.min(y)), float(np.max(y)))

    residuals = y - mu
    model_rmse = float(np.sqrt(np.mean(residuals**2)))
    model_mae = float(np.mean(np.abs(residuals)))

    mean_baseline_pred = np.full_like(y, mean_y)
    mean_baseline_resid = y - mean_baseline_pred
    mean_baseline_rmse = float(np.sqrt(np.mean(mean_baseline_resid**2)))
    mean_baseline_mae = float(np.mean(np.abs(mean_baseline_resid)))

    # Diagnostic-only 52-week seasonal-naive baseline (not a governed
    # validation-policy baseline - none exists in this repository for this
    # candidate; computed transparently here purely to help distinguish
    # "the outcome has little exploitable structure at all" from "the
    # model specifically fails to capture structure a naive lag exploits").
    seasonal_lag = 52
    seasonal_baseline: dict[str, Any] | None = None
    if len(y) > seasonal_lag:
        naive_pred = y[:-seasonal_lag]
        naive_actual = y[seasonal_lag:]
        naive_resid = naive_actual - naive_pred
        seasonal_baseline = {
            "lag_weeks": seasonal_lag,
            "n_observations_compared": int(len(naive_actual)),
            "rmse": float(np.sqrt(np.mean(naive_resid**2))),
            "mae": float(np.mean(np.abs(naive_resid))),
            "caveat": (
                "diagnostic-only same-week-last-year persistence baseline, "
                "not a governed validation-policy baseline - none exists in "
                "this repository for this candidate"
            ),
        }

    largest_positive = sorted(
        (
            {"date": d, "actual": float(a), "predicted": float(p), "residual": float(r)}
            for d, a, p, r in zip(date_strs, y, mu, residuals)
        ),
        key=lambda row: row["residual"],
        reverse=True,
    )[:8]
    largest_negative = sorted(
        (
            {"date": d, "actual": float(a), "predicted": float(p), "residual": float(r)}
            for d, a, p, r in zip(date_strs, y, mu, residuals)
        ),
        key=lambda row: row["residual"],
    )[:8]

    nlags = min(12, len(residuals) // 4)
    acf_values = _acf(residuals, nlags)
    pacf_values = _pacf_durbin_levinson(acf_values, nlags)

    return {
        "outcome_id": outcome_id,
        "observed": {
            "mean": mean_y,
            "median": median_y,
            "std": std_y,
            "variance": var_y,
            "coefficient_of_variation": cv_y,
            "range": range_y,
            "n_observations": int(len(y)),
        },
        "model_fit": {"rmse": model_rmse, "mae": model_mae},
        "mean_only_baseline": {"rmse": mean_baseline_rmse, "mae": mean_baseline_mae},
        "seasonal_naive_baseline_diagnostic_only": seasonal_baseline,
        "relative_improvement_vs_mean_baseline": {
            "rmse_pct_better": 100.0 * (1 - model_rmse / mean_baseline_rmse)
            if mean_baseline_rmse > 0
            else None,
            "mae_pct_better": 100.0 * (1 - model_mae / mean_baseline_mae)
            if mean_baseline_mae > 0
            else None,
        },
        "actual_vs_predicted": {
            "dates": date_strs,
            "actual": y.tolist(),
            "predicted": mu.tolist(),
            "residual": residuals.tolist(),
        },
        "largest_positive_residual_weeks": largest_positive,
        "largest_negative_residual_weeks": largest_negative,
        "residual_acf_lags_1_to_n": acf_values,
        "residual_pacf_lags_1_to_n": pacf_values,
    }


def _temporal_structure(
    frame: dict[str, Any], meta: Any, params: Any
) -> dict[str, Any]:
    outcome_ids = list(frame["outcome_ids"])
    y = np.asarray(frame["Y"], dtype=float)
    mu = predict_mu(frame, meta, params)
    residuals = y - mu  # (n_obs, n_outcome)
    dates = frame.get("dates")
    date_strs = (
        [str(d)[:10] for d in dates] if dates is not None else list(range(y.shape[0]))
    )

    trend = (
        np.asarray(frame.get("trend"), dtype=float)
        if frame.get("trend") is not None
        else None
    )
    fourier = (
        np.asarray(frame.get("fourier"), dtype=float)
        if frame.get("fourier") is not None
        else None
    )
    controls = frame.get("X_controls")
    controls = np.asarray(controls, dtype=float) if controls is not None else None

    per_outcome: dict[str, Any] = {}
    for o_idx, oid in enumerate(outcome_ids):
        r = residuals[:, o_idx]
        nlags = min(12, len(r) // 4)
        acf_values = _acf(r, nlags)
        entry: dict[str, Any] = {"residual_acf_lags_1_to_n": acf_values}
        if trend is not None and np.std(trend) > 0:
            entry["corr_with_trend"] = float(np.corrcoef(r, trend)[0, 1])
        if fourier is not None:
            season_proxy = fourier[:, 0] if fourier.shape[1] else None
            if season_proxy is not None and np.std(season_proxy) > 0:
                entry["corr_with_first_fourier_term"] = float(
                    np.corrcoef(r, season_proxy)[0, 1]
                )
        if controls is not None and controls.shape[1] and np.std(controls[:, 0]) > 0:
            entry["corr_with_first_control"] = float(
                np.corrcoef(r, controls[:, 0])[0, 1]
            )
        media_total = np.asarray(frame["X_media"], dtype=float).sum(axis=1)
        if np.std(media_total) > 0:
            entry["corr_with_total_raw_media_spend"] = float(
                np.corrcoef(r, media_total)[0, 1]
            )
        per_outcome[oid] = entry

    cross_corr: list[dict[str, Any]] = []
    for i, oid_a in enumerate(outcome_ids):
        for oid_b in outcome_ids[i + 1 :]:
            j = outcome_ids.index(oid_b)
            a, b = residuals[:, i], residuals[:, j]
            if np.std(a) > 0 and np.std(b) > 0:
                cross_corr.append(
                    {
                        "outcome_a": oid_a,
                        "outcome_b": oid_b,
                        "residual_correlation": float(np.corrcoef(a, b)[0, 1]),
                    }
                )

    # Same-week shared-shock check: for each week, is it in the top/bottom
    # decile of residuals for more than one outcome simultaneously?
    n_obs = residuals.shape[0]
    decile_n = max(1, n_obs // 10)
    shared_extreme_weeks: list[dict[str, Any]] = []
    top_sets = {
        oid: set(np.argsort(residuals[:, i])[-decile_n:])
        for i, oid in enumerate(outcome_ids)
    }
    bottom_sets = {
        oid: set(np.argsort(residuals[:, i])[:decile_n])
        for i, oid in enumerate(outcome_ids)
    }
    for w in range(n_obs):
        in_top = [oid for oid in outcome_ids if w in top_sets[oid]]
        in_bottom = [oid for oid in outcome_ids if w in bottom_sets[oid]]
        if len(in_top) >= 2 or len(in_bottom) >= 2:
            shared_extreme_weeks.append(
                {
                    "date": date_strs[w],
                    "outcomes_in_top_decile_residual": in_top,
                    "outcomes_in_bottom_decile_residual": in_bottom,
                }
            )

    return {
        "per_outcome": per_outcome,
        "cross_outcome_residual_correlation": cross_corr,
        "weeks_with_shared_extreme_residuals_across_outcomes": shared_extreme_weeks,
    }


def _loo_waic(
    model_obj, posterior: az.InferenceData, frame: dict[str, Any], meta: Any
) -> dict[str, Any]:
    return predictive_density_summary(model_obj, posterior, frame, meta)


def _evaluate_model(
    model_name: str,
    frame: dict[str, Any],
    spec: Any,
    prior_config: dict[str, Any],
    trace_dir: Path,
    output_dir: Path,
    fh_new_outcome_candidates: tuple[str, ...],
) -> dict[str, Any]:
    trace_path = trace_dir / model_name / "posterior.nc"
    posterior = az.from_netcdf(trace_path)

    proposed = build_model_for_spec(
        frame=frame,
        model_spec=spec,
        model_type="shared",
        dna_lag_weeks=4,
        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
        prior_config=prior_config,
        direct_dna_outcome_ids=(
            list(frame["outcome_ids"]) if model_name == "dna_kit" else None
        ),
        causal_graph=None,
        search_objects=(),
    )
    params = extract_posterior_params(posterior, proposed.meta)

    result: dict[str, Any] = {"model_name": model_name, "trace_path": str(trace_path)}

    fh_new_id = next(
        (oid for oid in fh_new_outcome_candidates if oid in frame["outcome_ids"]), None
    )
    if fh_new_id is not None:
        result["fh_new_diagnosis"] = _fh_new_diagnosis(
            frame, proposed.meta, params, fh_new_id
        )

    result["temporal_structure"] = _temporal_structure(frame, proposed.meta, params)

    scorecard = compute_scorecard(posterior, frame, proposed.meta)
    result["error_metrics"] = error_metrics_by_outcome(
        frame, proposed.meta, params
    ).to_dict(orient="records")
    result["residual_temporal_diagnostics"] = residual_temporal_diagnostics(
        frame, proposed.meta, params
    ).to_dict(orient="records")
    result["ppc_coverage"] = scorecard["ppc_coverage"]

    result["predictive_density"] = _loo_waic(
        proposed.model, posterior, frame, proposed.meta
    )

    _write_json(
        output_dir / f"wp2_9_fit_and_temporal_diagnostics_{model_name}.json", result
    )
    return result


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    prior_config = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)
    captured: dict[str, tuple[dict[str, Any], Any]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: Any) -> None:
        captured[model_name] = (frame, spec)

    runner.run(
        pack_dir=args.pack_dir,
        output_dir=args.output_dir / "official_preparation",
        draws=2000,
        tune=1000,
        chains=4,
        target_accept=0.9,
        seed=args.seed,
        fit_enabled=False,
        only_model=args.only_model,
        governed_start=args.governed_start,
        governed_end=args.governed_end,
        prior_config=prior_config,
        frame_callback=_capture,
    )

    # FH "New" is one of the fh_signup/fh_gsa outcome ids in frame["outcome_ids"];
    # resolved by substring rather than a hardcoded id since the exact
    # governed id string is a catalogue detail this script should not
    # duplicate a second time - checked against every candidate present.
    fh_new_candidates = tuple(
        oid
        for oid in (
            captured.get("family_history", ({}, None))[0].get("outcome_ids") or []
        )
        if "new" in oid.lower()
    )

    for model_name, (frame, spec) in captured.items():
        result = _evaluate_model(
            model_name,
            frame,
            spec,
            prior_config,
            args.trace_dir,
            args.output_dir,
            fh_new_candidates,
        )
        pd_summary = result["predictive_density"]
        print(
            f"{model_name}: elpd_loo={pd_summary['elpd_loo']:.1f} "
            f"p_loo={pd_summary['p_loo']:.1f} "
            f"elpd_waic={pd_summary['elpd_waic']:.1f}"
        )
        if "fh_new_diagnosis" in result:
            fh = result["fh_new_diagnosis"]
            print(
                f"  FH New: model_rmse={fh['model_fit']['rmse']:.1f} "
                f"mean_baseline_rmse={fh['mean_only_baseline']['rmse']:.1f} "
                f"cv={fh['observed']['coefficient_of_variation']:.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
