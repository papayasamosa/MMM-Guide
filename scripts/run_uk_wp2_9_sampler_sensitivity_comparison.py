"""WP2.9 item 3 (analyst-directed, 2026-08-25): compare the WP2.8
target_accept=0.90 governed full posterior against a target_accept=0.95
sampler-sensitivity fit run in this same work package - both `chains=4,
draws=2000, tune=1000`, `scripts/run_uk_production_fit.py` unmodified,
identical statistical specification. Real precedent for 0.95 already
exists (WP2.7's short screen) - this is a controlled sampler comparison,
not an invented configuration or a model change.

Reuses `core.models.compute_model_diagnostics`, `core.diagnostics.
compute_scorecard`/`error_metrics_by_outcome`, and `core.attribution.
compute_shapley_contributions` - no new statistical methodology.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import arviz as az
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.attribution import compute_shapley_contributions  # noqa: E402
from ancestry_mmm.core.diagnostics import compute_scorecard, error_metrics_by_outcome  # noqa: E402
from ancestry_mmm.core.models import compute_model_diagnostics  # noqa: E402
from ancestry_mmm.core.predict import extract_posterior_params  # noqa: E402
from ancestry_mmm.core.uncertainty import sample_draw_indices  # noqa: E402

DEFAULT_TRACE_DIR_090 = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-20260825"
)
DEFAULT_TRACE_DIR_095 = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-target-accept-0.95-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-sampler-sensitivity-20260825"
)
N_DRAWS_FOR_CONTRIBUTION = 150
SHAPLEY_N_PERMUTATIONS = 50
SHAPLEY_SEED = 20260825


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


def _quantiles(values: np.ndarray) -> dict[str, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {q: float("nan") for q in ("q05", "q25", "q50", "q75", "q95")}
    qs = np.quantile(finite, [0.05, 0.25, 0.50, 0.75, 0.95])
    return dict(zip(("q05", "q25", "q50", "q75", "q95"), (float(q) for q in qs)))


def _sampler_pathology(idata: az.InferenceData) -> dict[str, Any]:
    stats = idata.sample_stats
    out: dict[str, Any] = {}
    if "diverging" in stats:
        out["divergences_total"] = int(stats["diverging"].sum())
        out["divergences_by_chain"] = stats["diverging"].sum(dim="draw").values.tolist()
    for var in ("tree_depth", "treedepth", "depth"):
        if var in stats:
            depths = stats[var].values
            out["max_tree_depth_observed"] = int(depths.max())
            out["n_draws_at_max_tree_depth_by_chain"] = np.sum(
                depths >= 10, axis=1
            ).tolist()
            break
    if "acceptance_rate" in stats:
        out["mean_acceptance_rate_by_chain"] = (
            stats["acceptance_rate"].mean(dim="draw").values.tolist()
        )
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        out["bfmi_by_chain"] = np.asarray(az.bfmi(idata)).tolist()
        out["bfmi_min"] = float(np.min(out["bfmi_by_chain"]))
    return out


def _convergence(idata: az.InferenceData) -> dict[str, Any]:
    diagnostics = compute_model_diagnostics(idata)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        ess_tail = az.ess(idata, method="tail")
    tail_values = np.concatenate(
        [np.atleast_1d(ess_tail[var].values).reshape(-1) for var in ess_tail.data_vars]
    )
    return {
        "rhat_max": diagnostics["rhat_max"],
        "ess_bulk_min": diagnostics["ess_min"],
        "ess_tail_min": float(np.min(tail_values)) if tail_values.size else None,
        "divergences": diagnostics["divergences"],
        "sampler_pathology": _sampler_pathology(idata),
    }


def _parameter_family_means(
    idata: az.InferenceData, channel_coord: list[str]
) -> dict[str, Any]:
    post = idata.posterior
    out: dict[str, Any] = {}
    for var in ("decay_rate", "hill_K", "hill_S"):
        if var not in post:
            continue
        vals = post[var].stack(sample=("chain", "draw")).transpose("sample", ...).values
        out[var] = {ch: _quantiles(vals[:, i]) for i, ch in enumerate(channel_coord)}
    if "control_coef" in post:
        control_coord = list(
            post["control_coef"].coords.get("control", []).values
        ) or list(range(post["control_coef"].shape[-1]))
        vals = (
            post["control_coef"]
            .stack(sample=("chain", "draw"))
            .transpose("sample", ...)
            .values
        )
        out["control_coef"] = {
            str(c): _quantiles(vals[:, i]) for i, c in enumerate(control_coord)
        }
    return out


def _fit_metrics(
    idata: az.InferenceData, frame: dict[str, Any], meta: Any
) -> dict[str, Any]:
    params = extract_posterior_params(idata, meta)
    scorecard = compute_scorecard(idata, frame, meta)
    error_metrics = error_metrics_by_outcome(frame, meta, params).to_dict(
        orient="records"
    )
    return {"in_sample_fit": scorecard["in_sample_fit"], "error_metrics": error_metrics}


def _channel_contribution_comparison(
    idata_090: az.InferenceData,
    idata_095: az.InferenceData,
    frame: dict[str, Any],
    meta: Any,
    seed: int,
) -> dict[str, Any]:
    def _totals(idata: az.InferenceData) -> dict[str, np.ndarray]:
        pairs = sample_draw_indices(idata, n_draws=N_DRAWS_FOR_CONTRIBUTION, seed=seed)
        totals: dict[str, list[float]] = {c: [] for c in meta.channels}
        for pair in pairs:
            params = extract_posterior_params(idata, meta, at=pair)
            contributions = compute_shapley_contributions(
                frame,
                meta,
                params,
                n_permutations=SHAPLEY_N_PERMUTATIONS,
                seed=SHAPLEY_SEED,
            )
            for ch in meta.channels:
                totals[ch].append(
                    float(contributions["channel_contributions"][ch].sum())
                )
        return {ch: np.asarray(v) for ch, v in totals.items()}

    totals_090 = _totals(idata_090)
    totals_095 = _totals(idata_095)
    rows = []
    for ch in meta.channels:
        q090 = _quantiles(totals_090[ch])
        q095 = _quantiles(totals_095[ch])
        pct_diff = (
            100.0 * (q095["q50"] - q090["q50"]) / abs(q090["q50"])
            if q090["q50"] != 0
            else None
        )
        rows.append(
            {
                "channel": ch,
                "target_accept_090_quantiles": q090,
                "target_accept_095_quantiles": q095,
                "median_pct_difference_095_vs_090": pct_diff,
            }
        )
    rows.sort(
        key=lambda r: abs(r["median_pct_difference_095_vs_090"] or 0), reverse=True
    )
    return {
        "n_draws_used_per_config": N_DRAWS_FOR_CONTRIBUTION,
        "shapley_n_permutations": SHAPLEY_N_PERMUTATIONS,
        "by_channel_sorted_by_largest_shift": rows,
    }


def _evaluate_model(
    model_name: str,
    frame: dict[str, Any],
    spec: Any,
    prior_config: dict[str, Any],
    trace_dir_090: Path,
    trace_dir_095: Path,
    output_dir: Path,
    seed: int,
) -> dict[str, Any]:
    idata_090 = az.from_netcdf(trace_dir_090 / model_name / "posterior.nc")
    idata_095 = az.from_netcdf(trace_dir_095 / model_name / "posterior.nc")

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
    channel_coord = [str(c) for c in frame["channels"]]

    result = {
        "model_name": model_name,
        "target_accept_090": {
            "convergence": _convergence(idata_090),
            "fit": _fit_metrics(idata_090, frame, proposed.meta),
            "parameter_family_quantiles": _parameter_family_means(
                idata_090, channel_coord
            ),
        },
        "target_accept_095": {
            "convergence": _convergence(idata_095),
            "fit": _fit_metrics(idata_095, frame, proposed.meta),
            "parameter_family_quantiles": _parameter_family_means(
                idata_095, channel_coord
            ),
        },
        "channel_contribution_comparison": _channel_contribution_comparison(
            idata_090, idata_095, frame, proposed.meta, seed
        ),
    }
    _write_json(output_dir / f"wp2_9_sampler_sensitivity_{model_name}.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--trace-dir-090", type=Path, default=DEFAULT_TRACE_DIR_090)
    parser.add_argument("--trace-dir-095", type=Path, default=DEFAULT_TRACE_DIR_095)
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

    for model_name, (frame, spec) in captured.items():
        result = _evaluate_model(
            model_name,
            frame,
            spec,
            prior_config,
            args.trace_dir_090,
            args.trace_dir_095,
            args.output_dir,
            args.seed,
        )
        c090, c095 = (
            result["target_accept_090"]["convergence"],
            result["target_accept_095"]["convergence"],
        )
        print(
            f"{model_name}: divergences 0.90={c090['divergences']} -> 0.95={c095['divergences']} "
            f"rhat_max 0.90={c090['rhat_max']:.4f} -> 0.95={c095['rhat_max']:.4f} "
            f"ess_bulk_min 0.90={c090['ess_bulk_min']:.1f} -> 0.95={c095['ess_bulk_min']:.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
