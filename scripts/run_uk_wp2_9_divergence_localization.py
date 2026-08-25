"""WP2.9 item 2 (analyst-directed, 2026-08-25): localise the WP2.8
divergences (Family History: 70/8,000 post-tuning draws; DNA Kit: 53/8,000)
using the already-saved target_accept=0.90 posterior traces - no new fit.

Not "are there few enough divergences to ignore" (there is no approved
<1% threshold): this script asks whether the divergent draws sit in a
materially different part of parameter space than the rest of the
posterior, and whether that difference would change a channel's reported
incremental contribution. Reuses `core.attribution.compute_shapley_
contributions` (the model's own governed attribution decomposition) and
`core.predict.extract_posterior_params` (per-draw `FHPosteriorParams` via
its `at=(chain, draw)` argument) - no new attribution methodology.
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

from ancestry_mmm.core.attribution import compute_shapley_contributions  # noqa: E402
from ancestry_mmm.core.predict import extract_posterior_params  # noqa: E402

DEFAULT_TRACE_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-divergence-localization-20260825"
)
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
        return {
            q: float("nan") for q in ("q01", "q05", "q25", "q50", "q75", "q95", "q99")
        }
    qs = np.quantile(finite, [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99])
    return dict(
        zip(("q01", "q05", "q25", "q50", "q75", "q95", "q99"), (float(q) for q in qs))
    )


def _cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Standardised mean difference (divergent minus non-divergent), pooled
    SD - a scale-free way to compare parameters with very different units
    (a decay rate in [0,1] vs. a Hill K in physical spend units)."""
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return float("nan")
    var_a, var_b = np.var(a, ddof=1), np.var(b, ddof=1)
    pooled = np.sqrt(((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2))
    if pooled == 0:
        return float("nan")
    return float((np.mean(a) - np.mean(b)) / pooled)


def _flat_param(post_var: Any, coord: list[str] | None) -> dict[str, np.ndarray]:
    """Flatten a (chain, draw, ...) posterior DataArray into {label: (chain*draw,) array},
    one array per trailing-coordinate label (channel/outcome), matching the
    diverging mask's own (chain, draw) flattening order exactly."""
    values = post_var.values
    n_chain, n_draw = values.shape[0], values.shape[1]
    flat = values.reshape(n_chain * n_draw, *values.shape[2:])
    if flat.ndim == 1:
        return {"": flat}
    if flat.ndim == 2 and coord and len(coord) == flat.shape[1]:
        return {label: flat[:, i] for i, label in enumerate(coord)}
    # Fall back to positional labels for any other shape (still exhaustive).
    out: dict[str, np.ndarray] = {}
    for index in np.ndindex(flat.shape[1:]):
        key = ",".join(str(i) for i in index)
        out[key] = flat[(slice(None), *index)]
    return out


def _sampler_stats(idata: az.InferenceData) -> dict[str, Any]:
    stats = idata.sample_stats
    diverging = stats["diverging"].values  # (chain, draw)
    n_chain, n_draw = diverging.shape
    diverging_flat = diverging.reshape(-1)
    divergent_pairs = [
        (c, d) for c in range(n_chain) for d in range(n_draw) if diverging[c, d]
    ]
    out: dict[str, Any] = {
        "divergences_total": int(diverging.sum()),
        "divergences_by_chain": diverging.sum(axis=1).tolist(),
        "n_chain": n_chain,
        "n_draw": n_draw,
        "divergent_chain_draw_pairs": divergent_pairs,
    }
    for var in ("tree_depth", "treedepth", "depth"):
        if var in stats:
            depths = stats[var].values
            out["tree_depth_at_divergent_draws"] = _quantiles(
                depths.reshape(-1)[diverging_flat]
            )
            out["tree_depth_at_non_divergent_draws"] = _quantiles(
                depths.reshape(-1)[~diverging_flat]
            )
            break
    if "energy" in stats:
        energy = stats["energy"].values.reshape(-1)
        out["energy_at_divergent_draws"] = _quantiles(energy[diverging_flat])
        out["energy_at_non_divergent_draws"] = _quantiles(energy[~diverging_flat])
        out["energy_cohens_d"] = _cohens_d(
            energy[diverging_flat], energy[~diverging_flat]
        )
    if "acceptance_rate" in stats:
        acc = stats["acceptance_rate"].values.reshape(-1)
        out["acceptance_rate_at_divergent_draws"] = _quantiles(acc[diverging_flat])
        out["acceptance_rate_at_non_divergent_draws"] = _quantiles(acc[~diverging_flat])
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        out["bfmi_by_chain_recomputed"] = np.asarray(az.bfmi(idata)).tolist()
    return out


def _parameter_localisation(
    posterior: az.InferenceData, channel_coord: list[str], control_coord: list[str]
) -> dict[str, Any]:
    stats = posterior.sample_stats
    diverging = stats["diverging"].values.reshape(-1)
    post = posterior.posterior

    var_coords: dict[str, list[str] | None] = {
        "decay_rate": channel_coord,
        "hill_K": channel_coord,
        "hill_S": channel_coord,
        "mu_channel": channel_coord,
        "control_coef": control_coord,
        "sigma_pool": None,
        "trend_coef": None,
        "alpha": None,
    }
    result: dict[str, Any] = {}
    for var, coord in var_coords.items():
        if var not in post:
            continue
        by_label = _flat_param(post[var], coord)
        var_result: dict[str, Any] = {}
        for label, values in by_label.items():
            key = label or var
            div_vals = values[diverging]
            nondiv_vals = values[~diverging]
            whole_q = _quantiles(values)
            # Boundary-clustering proxy: what fraction of divergent draws
            # fall in the extreme 5% tails of the *whole* posterior for
            # this parameter - a parameter whose divergent draws
            # disproportionately sit near a tail is a candidate boundary/
            # funnel driver, not just noise.
            below_q05 = (
                float(np.mean(div_vals < whole_q["q05"])) if div_vals.size else None
            )
            above_q95 = (
                float(np.mean(div_vals > whole_q["q95"])) if div_vals.size else None
            )
            var_result[key] = {
                "n_divergent": int(div_vals.size),
                "divergent_quantiles": _quantiles(div_vals),
                "non_divergent_quantiles": _quantiles(nondiv_vals),
                "whole_posterior_quantiles": whole_q,
                "cohens_d_divergent_vs_non_divergent": _cohens_d(div_vals, nondiv_vals),
                "frac_divergent_below_whole_q05": below_q05,
                "frac_divergent_above_whole_q95": above_q95,
            }
        result[var] = var_result
    return result


def _correlation_structure(
    posterior: az.InferenceData, channel_coord: list[str], seed: int
) -> dict[str, Any]:
    """Pairwise correlation of (decay_rate, hill_K, hill_S, mu_channel,
    sigma_pool) restricted to divergent draws vs. a matched-size random
    sample of non-divergent draws - a shift in correlation structure
    (e.g. a hierarchy funnel between sigma_pool and mu_channel) is a
    classic NUTS divergence signature this makes directly visible."""
    stats = posterior.sample_stats
    diverging = stats["diverging"].values.reshape(-1)
    post = posterior.posterior
    n_div = int(diverging.sum())
    if n_div < 5:
        return {"skipped": "fewer than 5 divergent draws - correlation unstable"}

    rng = np.random.default_rng(seed)
    nondiv_idx = np.flatnonzero(~diverging)
    matched_nondiv_idx = rng.choice(nondiv_idx, size=n_div, replace=False)
    div_idx = np.flatnonzero(diverging)

    fields: dict[str, np.ndarray] = {}
    if "sigma_pool" in post:
        vals = post["sigma_pool"].values.reshape(
            -1, *post["sigma_pool"].values.shape[2:]
        )
        fields["sigma_pool"] = vals.reshape(vals.shape[0], -1).mean(axis=1)
    for var in ("decay_rate", "hill_K", "hill_S", "mu_channel"):
        if var not in post:
            continue
        vals = post[var].values.reshape(-1, *post[var].values.shape[2:])
        for i, ch in enumerate(channel_coord):
            fields[f"{var}[{ch}]"] = vals[:, i]

    names = sorted(fields)

    def _corr_matrix(idx: np.ndarray) -> dict[str, dict[str, float]]:
        matrix: dict[str, dict[str, float]] = {}
        for a in names:
            row = {}
            for b in names:
                if a == b:
                    row[b] = 1.0
                    continue
                x, y = fields[a][idx], fields[b][idx]
                row[b] = (
                    float(np.corrcoef(x, y)[0, 1])
                    if np.std(x) > 0 and np.std(y) > 0
                    else None
                )
            matrix[a] = row
        return matrix

    div_corr = _corr_matrix(div_idx)
    nondiv_corr = _corr_matrix(matched_nondiv_idx)
    biggest_shifts = []
    for a in names:
        for b in names:
            if a >= b:
                continue
            dv, nv = div_corr[a][b], nondiv_corr[a][b]
            if dv is None or nv is None:
                continue
            biggest_shifts.append(
                {
                    "pair": [a, b],
                    "divergent_corr": dv,
                    "non_divergent_corr": nv,
                    "abs_shift": abs(dv - nv),
                }
            )
    biggest_shifts.sort(key=lambda row: row["abs_shift"], reverse=True)
    return {
        "n_divergent": n_div,
        "n_matched_non_divergent": int(matched_nondiv_idx.size),
        "correlation_divergent": div_corr,
        "correlation_non_divergent_matched_sample": nondiv_corr,
        "largest_correlation_shifts": biggest_shifts[:15],
    }


def _channel_contribution_stability(
    posterior: az.InferenceData,
    frame: dict[str, Any],
    meta: Any,
    seed: int,
) -> dict[str, Any]:
    """Does a channel's reported incremental contribution differ between
    divergent and a matched-size random non-divergent sample of draws?
    Uses the model's own governed Shapley attribution
    (`compute_shapley_contributions`) per draw, summed over rows/outcomes
    to a single per-draw per-channel total contribution."""
    stats = posterior.sample_stats
    diverging = stats["diverging"].values  # (chain, draw)
    n_chain, n_draw = diverging.shape
    div_pairs = [
        (c, d) for c in range(n_chain) for d in range(n_draw) if diverging[c, d]
    ]
    n_div = len(div_pairs)
    if n_div == 0:
        return {"skipped": "no divergent draws"}

    rng = np.random.default_rng(seed)
    all_pairs = [(c, d) for c in range(n_chain) for d in range(n_draw)]
    nondiv_pairs_pool = [p for p in all_pairs if not diverging[p[0], p[1]]]
    matched_nondiv_pairs = [
        nondiv_pairs_pool[i]
        for i in rng.choice(len(nondiv_pairs_pool), size=n_div, replace=False)
    ]

    def _totals_for(pairs: list[tuple[int, int]]) -> dict[str, list[float]]:
        totals: dict[str, list[float]] = {c: [] for c in meta.channels}
        for pair in pairs:
            params = extract_posterior_params(posterior, meta, at=pair)
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
        return totals

    div_totals = _totals_for(div_pairs)
    nondiv_totals = _totals_for(matched_nondiv_pairs)

    rows = []
    for ch in meta.channels:
        div_arr = np.asarray(div_totals[ch])
        nondiv_arr = np.asarray(nondiv_totals[ch])
        div_median = float(np.median(div_arr))
        nondiv_median = float(np.median(nondiv_arr))
        pct_diff = (
            100.0 * (div_median - nondiv_median) / abs(nondiv_median)
            if nondiv_median != 0
            else None
        )
        rows.append(
            {
                "channel": ch,
                "divergent_draw_contribution_quantiles": _quantiles(div_arr),
                "non_divergent_matched_contribution_quantiles": _quantiles(nondiv_arr),
                "median_pct_difference_divergent_vs_non_divergent": pct_diff,
                "cohens_d": _cohens_d(div_arr, nondiv_arr),
            }
        )
    rows.sort(
        key=lambda r: abs(r["median_pct_difference_divergent_vs_non_divergent"] or 0),
        reverse=True,
    )
    return {
        "n_divergent_draws_used": n_div,
        "n_matched_non_divergent_draws_used": len(matched_nondiv_pairs),
        "shapley_n_permutations": SHAPLEY_N_PERMUTATIONS,
        "by_channel_sorted_by_largest_shift": rows,
    }


def _evaluate_model(
    model_name: str,
    frame: dict[str, Any],
    spec: Any,
    prior_config: dict[str, Any],
    trace_dir: Path,
    output_dir: Path,
    seed: int,
) -> dict[str, Any]:
    from ancestry_mmm.application.model_fit_service import build_model_for_spec

    trace_path = trace_dir / model_name / "posterior.nc"
    posterior = az.from_netcdf(trace_path)
    channel_coord = [str(c) for c in frame["channels"]]
    control_coord = [str(c) for c in (frame.get("control_names") or [])]

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

    result = {
        "model_name": model_name,
        "trace_path": str(trace_path),
        "sampler_stats": _sampler_stats(posterior),
        "parameter_localisation": _parameter_localisation(
            posterior, channel_coord, control_coord
        ),
        "correlation_structure": _correlation_structure(posterior, channel_coord, seed),
        "channel_contribution_stability": _channel_contribution_stability(
            posterior, frame, proposed.meta, seed
        ),
    }
    _write_json(output_dir / f"wp2_9_divergence_localization_{model_name}.json", result)
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
        result = _evaluate_model(
            model_name,
            frame,
            spec,
            prior_config,
            args.trace_dir,
            args.output_dir,
            args.seed,
        )
        n_div = result["sampler_stats"]["divergences_total"]
        print(f"{model_name}: divergences={n_div}")
        top = result["channel_contribution_stability"].get(
            "by_channel_sorted_by_largest_shift", []
        )
        for row in top[:5]:
            print(
                f"  {row['channel']}: median pct diff (divergent vs non-divergent) = "
                f"{row['median_pct_difference_divergent_vs_non_divergent']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
