"""WP2.10 items 4/5/8 (analyst-directed, 2026-08-25): evaluate the fitted
FH Overall / DNA Overall single-outcome challenger posteriors
(`scripts/run_uk_wp2_10_overall_challenger.py`'s output) and compare them
against WP2.9's posterior-derived Overall totals
(`scripts/run_uk_wp2_9_product_level_totals.py`'s output) - the item 8
reconciliation. Reuses `core.diagnostics.compute_scorecard`/
`error_metrics_by_outcome`/`residual_temporal_diagnostics`, `core.
attribution.compute_shapley_contributions`, and `core.uncertainty.
sample_draw_indices` - no new statistical methodology.
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
    compute_scorecard,
    error_metrics_by_outcome,
    residual_temporal_diagnostics,
)
from ancestry_mmm.core.predict import extract_posterior_params  # noqa: E402
from ancestry_mmm.core.uncertainty import sample_draw_indices  # noqa: E402

DEFAULT_CHALLENGER_TRACE_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-10-overall-challenger-20260825"
)
DEFAULT_PRODUCT_TOTALS_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-product-level-totals-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-10-overall-challenger-evaluation-20260825"
)
N_DRAWS_FOR_CONTRIBUTION = 200
SHAPLEY_N_PERMUTATIONS = 50
SHAPLEY_SEED = 20260825

CHALLENGER_CONFIG = {
    "fh": {
        "model_name": "family_history",
        "challenger_name": "fh_overall_challenger",
        "product": "Family History",
        "outcome_id": "fh_overall_challenger",
        "segment": "Overall",
        "product_label": "FH Overall",
    },
    "dna": {
        "model_name": "dna_kit",
        "challenger_name": "dna_overall_challenger",
        "product": "DNA",
        "outcome_id": "dna_overall_challenger",
        "segment": "Overall",
        "product_label": "DNA Overall",
    },
}


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


def _relative_width(q: dict[str, float]) -> float:
    return (
        (q["q95"] - q["q05"]) / q["q50"]
        if q.get("q50") not in (0, None)
        else float("nan")
    )


def _rebuild_challenger_frame(
    runner, key: str, governed_start: str, governed_end: str, seed: int
):
    """Reconstruct the exact same challenger frame/spec
    `run_uk_wp2_10_overall_challenger.py` built for the real fit - frame
    construction is deterministic given the same source pack/window, so
    no intermediate frame needs to have been persisted."""
    cfg = CHALLENGER_CONFIG[key]
    captured: dict[str, tuple[dict[str, Any], Any]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: Any) -> None:
        captured[model_name] = (frame, spec)

    runner.run(
        pack_dir=runner.DEFAULT_PACK_DIR,
        output_dir=Path(r"D:\Ancestry-MMM\tmp\wp2_10_challenger_eval_prep"),
        draws=2000,
        tune=1000,
        chains=4,
        target_accept=0.9,
        seed=seed,
        fit_enabled=False,
        only_model=cfg["model_name"],
        governed_start=governed_start,
        governed_end=governed_end,
        prior_config=runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG,
        frame_callback=_capture,
    )
    segment_frame, segment_spec = captured[cfg["model_name"]]
    pack = runner._load_pack(runner.DEFAULT_PACK_DIR)

    challenger_module = _load_module(
        "wp2_10_challenger",
        REPO_ROOT / "scripts" / "run_uk_wp2_10_overall_challenger.py",
    )
    frame, spec, synthetic_outcome = challenger_module._build_overall_frame(
        runner, pack, key, segment_frame, segment_spec, governed_start
    )
    return frame, spec, synthetic_outcome


def _evaluate_challenger(
    key: str,
    trace_dir: Path,
    product_totals_dir: Path,
    output_dir: Path,
    governed_start: str,
    governed_end: str,
    seed: int,
) -> dict[str, Any]:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)
    cfg = CHALLENGER_CONFIG[key]

    frame, spec, synthetic_outcome = _rebuild_challenger_frame(
        runner, key, governed_start, governed_end, seed
    )
    trace_path = trace_dir / cfg["challenger_name"] / "posterior.nc"
    posterior = az.from_netcdf(trace_path)

    prior_config = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)
    prior_config["pooled_beta_reference"] = True
    dna_outcome_id = cfg["outcome_id"] if key == "fh" else None
    direct_dna_outcome_ids = [cfg["outcome_id"]] if key == "dna" else None
    proposed = build_model_for_spec(
        frame=frame,
        model_spec=spec,
        model_type="shared",
        dna_lag_weeks=4,
        dna_outcome_id=dna_outcome_id,
        prior_config=prior_config,
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        causal_graph=None,
        search_objects=(),
    )
    params = extract_posterior_params(posterior, proposed.meta)

    scorecard = compute_scorecard(posterior, frame, proposed.meta)
    error_metrics = error_metrics_by_outcome(frame, proposed.meta, params).to_dict(
        orient="records"
    )
    residuals = residual_temporal_diagnostics(frame, proposed.meta, params).to_dict(
        orient="records"
    )

    draw_pairs = sample_draw_indices(
        posterior, n_draws=N_DRAWS_FOR_CONTRIBUTION, seed=seed
    )
    per_channel_draws: dict[str, list[float]] = {c: [] for c in proposed.meta.channels}
    for pair in draw_pairs:
        draw_params = extract_posterior_params(posterior, proposed.meta, at=pair)
        contributions = compute_shapley_contributions(
            frame,
            proposed.meta,
            draw_params,
            n_permutations=SHAPLEY_N_PERMUTATIONS,
            seed=SHAPLEY_SEED,
        )
        for ch in proposed.meta.channels:
            per_channel_draws[ch].append(
                float(contributions["channel_contributions"][ch].sum())
            )

    total_volume_draws = np.sum(list(per_channel_draws.values()), axis=0)
    spend_by_channel = {
        c: float(np.asarray(frame["X_media"], dtype=float)[:, ci].sum())
        for ci, c in enumerate(proposed.meta.channels)
    }
    channel_rows = []
    for ch in proposed.meta.channels:
        vol = np.asarray(per_channel_draws[ch])
        q = _quantiles(vol)
        share = vol / np.where(total_volume_draws != 0, total_volume_draws, np.nan)
        channel_rows.append(
            {
                "channel": ch,
                "volume_contribution_quantiles": q,
                "share_of_incremental_contribution_quantiles": _quantiles(share),
                "spend": spend_by_channel[ch],
            }
        )

    # Reconciliation against WP2.9's posterior-derived Overall totals.
    posterior_derived_path = (
        product_totals_dir / f"wp2_9_product_level_totals_{cfg['model_name']}.json"
    )
    posterior_derived = json.loads(posterior_derived_path.read_text(encoding="utf-8"))
    pd_channel_by_name = {
        row["channel"]: row
        for row in posterior_derived["channel_level_totals"]["by_channel"]
    }
    comparison_rows = []
    for row in channel_rows:
        ch = row["channel"]
        pd_row = pd_channel_by_name.get(ch)
        if pd_row is None:
            continue
        challenger_median = row["volume_contribution_quantiles"]["q50"]
        posterior_median = pd_row["volume_contribution_quantiles"]["q50"]
        pct_diff = (
            100.0 * (challenger_median - posterior_median) / abs(posterior_median)
            if posterior_median != 0
            else None
        )
        comparison_rows.append(
            {
                "channel": ch,
                "challenger_median_volume": challenger_median,
                "posterior_derived_median_volume": posterior_median,
                "pct_difference": pct_diff,
                "challenger_relative_interval_width": _relative_width(
                    row["volume_contribution_quantiles"]
                ),
                "posterior_derived_relative_interval_width": _relative_width(
                    pd_row["volume_contribution_quantiles"]
                ),
            }
        )
    comparison_rows.sort(key=lambda r: abs(r["pct_difference"] or 0), reverse=True)

    posterior_derived_fit_metrics = posterior_derived["fit_and_ppc"]["fit_metrics"]
    result = {
        "product_label": cfg["product_label"],
        "challenger_name": cfg["challenger_name"],
        "in_sample_fit": scorecard["in_sample_fit"],
        "posterior_derived_fit_metrics_for_comparison": posterior_derived_fit_metrics,
        "error_metrics": error_metrics,
        "ppc_coverage": scorecard["ppc_coverage"],
        "residual_temporal_diagnostics": residuals,
        "channel_level_totals": channel_rows,
        "reconciliation_vs_posterior_derived_overall": {
            "posterior_derived_source": str(posterior_derived_path),
            "by_channel_sorted_by_largest_pct_difference": comparison_rows,
        },
    }
    _write_json(
        output_dir
        / f"wp2_10_overall_challenger_evaluation_{cfg['challenger_name']}.json",
        result,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_CHALLENGER_TRACE_DIR)
    parser.add_argument(
        "--product-totals-dir", type=Path, default=DEFAULT_PRODUCT_TOTALS_DIR
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--product", choices=["fh", "dna"], required=True)
    parser.add_argument("--seed", type=int, default=20261010)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    result = _evaluate_challenger(
        args.product,
        args.trace_dir,
        args.product_totals_dir,
        args.output_dir,
        args.governed_start,
        args.governed_end,
        args.seed,
    )
    fm = result["in_sample_fit"]
    print(f"{result['product_label']}: in_sample_fit={fm}")
    top = result["reconciliation_vs_posterior_derived_overall"][
        "by_channel_sorted_by_largest_pct_difference"
    ]
    for row in top[:5]:
        print(
            f"  {row['channel']}: challenger={row['challenger_median_volume']:.1f} posterior_derived={row['posterior_derived_median_volume']:.1f} pct_diff={row['pct_difference']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
