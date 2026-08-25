"""WP2.9 item 7A (analyst-directed, 2026-08-25): FH Overall and DNA
Overall posterior results from the existing joint Model A posterior - not
a new model or a new likelihood. Every summary is computed by summing the
constituent outcome-level posterior draws *within* each posterior draw
first (`trace.posterior["mu"]`/`"alpha"`, already-saved per-draw
deterministics - reused, never recomputed), then summarising the resulting
per-draw product-level series - never by adding posterior means or
credible-interval endpoints together.

Family History's saved posterior already has exactly the three FH outcome
columns (New, DNA cross-sell, Winback), so "FH Overall" is the sum over
every outcome column of that model; DNA Kit's saved posterior already has
exactly the two DNA outcome columns (New, Existing FH customer), so "DNA
Overall" is the sum over every outcome column of that model. Channel-level
contribution reuses `core.attribution.compute_shapley_contributions`
(the model's own governed decomposition, already outcome-column-summed by
construction) on a posterior-draw subsample
(`core.uncertainty.sample_draw_indices`, the repository's own existing,
documented posterior-subsampling convention) rather than the full ~8,000
draws, for tractable runtime - not a new statistical approximation beyond
what `core.uncertainty` already establishes as this repository's accepted
speed/precision trade-off.
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
from ancestry_mmm.core.attribution import compute_shapley_contributions  # noqa: E402
from ancestry_mmm.core.diagnostics import (  # noqa: E402
    _bias,
    _mae,
    _mape,
    _r_squared,
    _residual_autocorrelation_stats,
    _rmse,
)
from ancestry_mmm.core.predict import extract_posterior_params  # noqa: E402
from ancestry_mmm.core.uncertainty import sample_draw_indices  # noqa: E402

DEFAULT_TRACE_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-product-level-totals-20260825"
)
N_DRAWS_FOR_CHANNEL_ATTRIBUTION = 200
SHAPLEY_N_PERMUTATIONS = 50
SHAPLEY_SEED = 20260825
CREDIBLE_MASS = 0.9


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


def _product_fit_and_ppc(
    posterior: az.InferenceData,
    frame: dict[str, Any],
    outcome_ids: list[str],
    seed: int,
) -> dict[str, Any]:
    mu_sum = posterior.posterior["mu"].sel(outcome=outcome_ids).sum(dim="outcome")
    # dims (chain, draw, obs)
    mu_sample = mu_sum.stack(sample=("chain", "draw")).transpose("obs", "sample").values
    predicted_mean = mu_sample.mean(axis=1)
    predicted_interval = _quantiles_axis1(mu_sample, (0.05, 0.5, 0.95))

    Y = np.asarray(frame["Y"], dtype=float)
    outcome_coord = list(frame["outcome_ids"])
    idx = [outcome_coord.index(oid) for oid in outcome_ids]
    actual = Y[:, idx].sum(axis=1)

    residual = actual - predicted_mean
    lag1_autocorr, durbin_watson = _residual_autocorrelation_stats(residual)

    rng = np.random.default_rng(seed)
    n_obs, n_sample = mu_sample.shape
    sim_sum = np.zeros((n_obs, n_sample))
    for oid in outcome_ids:
        mu_o = (
            posterior.posterior["mu"]
            .sel(outcome=oid)
            .stack(sample=("chain", "draw"))
            .transpose("obs", "sample")
            .values
        )
        alpha_o = (
            posterior.posterior["alpha"]
            .sel(outcome=oid)
            .stack(sample=("chain", "draw"))
            .values
        )  # (sample,)
        alpha_b = alpha_o[None, :]
        p = np.clip(alpha_b / (alpha_b + mu_o), 1e-9, 1 - 1e-9)
        sim_sum += rng.negative_binomial(alpha_b, p, size=(n_obs, n_sample))

    lower_q, upper_q = (1 - CREDIBLE_MASS) / 2, 1 - (1 - CREDIBLE_MASS) / 2
    lo = np.quantile(sim_sum, lower_q, axis=1)
    hi = np.quantile(sim_sum, upper_q, axis=1)
    covered = (actual >= lo) & (actual <= hi)

    mape = _mape(actual, predicted_mean) if np.all(actual != 0) else None

    return {
        "constituent_outcome_ids": outcome_ids,
        "n_observations": int(n_obs),
        "n_posterior_samples": int(n_sample),
        "actual_time_series": actual.tolist(),
        "posterior_predicted_mean_time_series": predicted_mean.tolist(),
        "posterior_predicted_interval_time_series": {
            "credible_mass": CREDIBLE_MASS,
            "q05": predicted_interval[0].tolist(),
            "q50": predicted_interval[1].tolist(),
            "q95": predicted_interval[2].tolist(),
        },
        "fit_metrics": {
            "r_squared": _r_squared(actual, predicted_mean),
            "rmse": _rmse(actual, predicted_mean),
            "mae": _mae(actual, predicted_mean),
            "mape_pct": mape,
            "bias": _bias(actual, predicted_mean),
        },
        "residual_time_series": residual.tolist(),
        "residual_lag1_autocorrelation": lag1_autocorr,
        "durbin_watson": durbin_watson,
        "ppc_coverage": {
            "credible_mass": CREDIBLE_MASS,
            "coverage_pct": float(covered.mean() * 100),
            "target_pct": CREDIBLE_MASS * 100,
        },
    }


def _quantiles_axis1(arr: np.ndarray, qs: tuple[float, ...]) -> list[np.ndarray]:
    return [np.quantile(arr, q, axis=1) for q in qs]


def _channel_level_product_totals(
    posterior: az.InferenceData,
    frame: dict[str, Any],
    meta: Any,
    outcome_ids: list[str],
    seed: int,
) -> dict[str, Any]:
    draw_pairs = sample_draw_indices(
        posterior, n_draws=N_DRAWS_FOR_CHANNEL_ATTRIBUTION, seed=seed
    )
    outcome_coord = list(frame["outcome_ids"])
    idx = [outcome_coord.index(oid) for oid in outcome_ids]

    per_channel_draws: dict[str, list[float]] = {c: [] for c in meta.channels}
    per_outcome_per_channel_draws: dict[str, dict[str, list[float]]] = {
        oid: {c: [] for c in meta.channels} for oid in outcome_ids
    }
    baseline_total_draws: list[float] = []
    predicted_total_draws: list[float] = []
    reconciliation_max_abs_diff = 0.0

    for pair in draw_pairs:
        params = extract_posterior_params(posterior, meta, at=pair)
        contributions = compute_shapley_contributions(
            frame,
            meta,
            params,
            n_permutations=SHAPLEY_N_PERMUTATIONS,
            seed=SHAPLEY_SEED,
        )
        baseline_sum = float(contributions["baseline"][:, idx].sum())
        baseline_total_draws.append(baseline_sum)
        mu_total_sum = float(contributions["mu_total"][:, idx].sum())
        predicted_total_draws.append(mu_total_sum)

        product_total_from_channels = baseline_sum
        for ch in meta.channels:
            per_outcome_sum = 0.0
            for oid, o_idx in zip(outcome_ids, idx):
                val = float(contributions["channel_contributions"][ch][:, o_idx].sum())
                per_outcome_per_channel_draws[oid][ch].append(val)
                per_outcome_sum += val
            per_channel_draws[ch].append(per_outcome_sum)
            product_total_from_channels += per_outcome_sum
        reconciliation_max_abs_diff = max(
            reconciliation_max_abs_diff, abs(product_total_from_channels - mu_total_sum)
        )

    spend_by_channel = {
        c: float(np.asarray(frame["X_media"], dtype=float)[:, ci].sum())
        for ci, c in enumerate(meta.channels)
    }

    rows = []
    for ch in meta.channels:
        vol = np.asarray(per_channel_draws[ch])
        spend = spend_by_channel[ch]
        roi = vol / spend if spend > 0 else np.full_like(vol, np.nan)
        cpa = np.where(vol > 0, spend / np.where(vol > 0, vol, np.nan), np.nan)
        rows.append(
            {
                "channel": ch,
                "spend": spend,
                "volume_contribution_quantiles": _quantiles(vol),
                "roi_quantiles": _quantiles(roi),
                "cpa_quantiles": _quantiles(cpa),
                "reconciliation_sum_of_outcome_level_contributions_matches": {
                    oid: _quantiles(np.asarray(per_outcome_per_channel_draws[oid][ch]))
                    for oid in outcome_ids
                },
            }
        )

    total_volume_draws = np.sum([per_channel_draws[c] for c in meta.channels], axis=0)
    for row in rows:
        share = np.asarray(per_channel_draws[row["channel"]]) / np.where(
            total_volume_draws != 0, total_volume_draws, np.nan
        )
        row["share_of_incremental_contribution_quantiles"] = _quantiles(share)

    return {
        "n_draws_used": len(draw_pairs),
        "shapley_n_permutations": SHAPLEY_N_PERMUTATIONS,
        "baseline_outcome_quantiles": _quantiles(np.asarray(baseline_total_draws)),
        "incremental_outcome_quantiles": _quantiles(
            np.asarray(predicted_total_draws) - np.asarray(baseline_total_draws)
        ),
        "reconciliation_check": {
            "description": (
                "max |sum(baseline + per-channel contributions) - mu_total|, "
                "per draw, across all draws used - should be at or near "
                "floating-point tolerance since channel contributions sum "
                "exactly to (mu_total - mu_baseline) by Shapley construction"
            ),
            "max_abs_diff": reconciliation_max_abs_diff,
        },
        "by_channel": rows,
    }


def _evaluate_product(
    product_label: str,
    model_name: str,
    outcome_ids: list[str],
    frame: dict[str, Any],
    spec: Any,
    prior_config: dict[str, Any],
    trace_dir: Path,
    output_dir: Path,
    seed: int,
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

    fit_and_ppc = _product_fit_and_ppc(posterior, frame, outcome_ids, seed)
    channel_totals = _channel_level_product_totals(
        posterior, frame, proposed.meta, outcome_ids, seed
    )

    # Individual-segment stability comparison: same subsample, same Shapley
    # config, but only the single largest constituent outcome's own volume
    # per channel (already computed above) - lets the analyst compare the
    # product-level distribution's spread against a single-segment one on
    # a like-for-like basis (same draws, same permutations, same seed).
    segment_volume_cv: dict[str, dict[str, float]] = {}
    for oid in outcome_ids:
        for row in channel_totals["by_channel"]:
            ch = row["channel"]
            segment_volume_cv.setdefault(oid, {})
            q = row["reconciliation_sum_of_outcome_level_contributions_matches"][oid]
            spread = q["q95"] - q["q05"]
            segment_volume_cv[oid][ch] = (
                spread / q["q50"] if q["q50"] not in (0, None) else float("nan")
            )

    product_volume_cv = {
        row["channel"]: (
            row["volume_contribution_quantiles"]["q95"]
            - row["volume_contribution_quantiles"]["q05"]
        )
        / row["volume_contribution_quantiles"]["q50"]
        if row["volume_contribution_quantiles"]["q50"] not in (0, None)
        else float("nan")
        for row in channel_totals["by_channel"]
    }

    result = {
        "product_label": product_label,
        "model_name": model_name,
        "constituent_outcome_ids": outcome_ids,
        "fit_and_ppc": fit_and_ppc,
        "channel_level_totals": channel_totals,
        "stability_comparison": {
            "description": (
                "relative 90% credible interval width (q95-q05)/q50 of "
                "per-channel volume contribution, product-level vs. each "
                "constituent segment - a smaller product-level ratio means "
                "product-level aggregation is more stable than the "
                "individual segments it sums"
            ),
            "product_level_relative_interval_width": product_volume_cv,
            "segment_level_relative_interval_width": segment_volume_cv,
        },
    }
    _write_json(output_dir / f"wp2_9_product_level_totals_{model_name}.json", result)
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

    for model_name, (frame, spec) in captured.items():
        product_label = (
            "FH Overall" if model_name == "family_history" else "DNA Overall"
        )
        outcome_ids = list(frame["outcome_ids"])
        result = _evaluate_product(
            product_label,
            model_name,
            outcome_ids,
            frame,
            spec,
            prior_config,
            args.trace_dir,
            args.output_dir,
            args.seed,
        )
        fm = result["fit_and_ppc"]["fit_metrics"]
        print(
            f"{product_label}: r2={fm['r_squared']:.3f} rmse={fm['rmse']:.1f} "
            f"mae={fm['mae']:.1f} bias={fm['bias']:.1f} "
            f"ppc_coverage={result['fit_and_ppc']['ppc_coverage']['coverage_pct']:.1f}% "
            f"reconciliation_max_abs_diff={result['channel_level_totals']['reconciliation_check']['max_abs_diff']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
