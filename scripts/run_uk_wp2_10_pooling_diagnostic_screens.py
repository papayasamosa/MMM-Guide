"""WP2.10 item 2 (analyst-directed, 2026-08-25): diagnostic short-screen
comparison of the pooling-prior alternatives already gated (default off)
in `core.hierarchical_model.build_fh_hierarchical_model` -
`prior_config["pooled_beta_reference"]` (complete pooling: `sigma_pool`/
`z_offset` deterministically zero) and `prior_config["pooling_sigma_
prior_distribution"] == "lognormal"` (an alternative prior family for
`sigma_pool` with no mass at exactly zero) - against the current default
(HalfNormal `sigma_pool`). No new model algebra; both gates predate this
work package.

Short-screen configuration matches `scripts/run_uk_wp2_7_short_sampler_
screen.py`'s own precedent exactly (`draws=100, tune=150, chains=2,
target_accept=0.95` - `scripts/run_uk_transform_identifiability_
experiment.py`'s existing CLI defaults) - a screen, not a production
convergence claim, run purely to compare divergence/geometry behaviour
across the three gated prior configurations under identical, cheap
conditions.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.models import compute_model_diagnostics, fit_model  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-10-pooling-diagnostic-screens-20260825"
)
SHORT_SCREEN_DRAWS = 100
SHORT_SCREEN_TUNE = 150
SHORT_SCREEN_CHAINS = 2
SHORT_SCREEN_TARGET_ACCEPT = 0.95

VARIANTS = {
    "default_halfnormal": {},
    "pooled_beta_reference": {"pooled_beta_reference": True},
    "lognormal_sigma_pool": {"pooling_sigma_prior_distribution": "lognormal"},
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


def _run_variant(
    frame: dict[str, Any],
    spec: Any,
    model_name: str,
    base_prior_config: dict[str, Any],
    variant_overrides: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    prior_config = {**base_prior_config, **variant_overrides}
    model_result = build_model_for_spec(
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
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        trace = fit_model(
            model_result.model,
            draws=SHORT_SCREEN_DRAWS,
            tune=SHORT_SCREEN_TUNE,
            chains=SHORT_SCREEN_CHAINS,
            target_accept=SHORT_SCREEN_TARGET_ACCEPT,
            random_seed=seed,
            cores=1,
        )
    diagnostics = compute_model_diagnostics(trace)
    stats = trace.sample_stats
    result = {
        "prior_config_overrides": variant_overrides,
        "rhat_max": diagnostics["rhat_max"],
        "ess_min": diagnostics["ess_min"],
        "divergences": diagnostics["divergences"],
        "converged_per_pymc_default_threshold": diagnostics["converged"],
    }
    if "tree_depth" in stats:
        result["max_tree_depth_observed"] = int(stats["tree_depth"].values.max())
    if "diverging" in stats:
        result["divergences_by_chain"] = (
            stats["diverging"].sum(dim="draw").values.tolist()
        )
    if "sigma_pool" in trace.posterior:
        sp = trace.posterior["sigma_pool"].values
        result["sigma_pool_summary"] = {
            "mean": float(np.mean(sp)),
            "min": float(np.min(sp)),
            "max": float(np.max(sp)),
        }
    return result


def _evaluate_model(
    model_name: str,
    frame: dict[str, Any],
    spec: Any,
    base_prior_config: dict[str, Any],
    seed: int,
    output_dir: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {"model_name": model_name, "variants": {}}
    for variant_name, overrides in VARIANTS.items():
        print(f"  running variant {variant_name} for {model_name}...")
        result["variants"][variant_name] = _run_variant(
            frame, spec, model_name, base_prior_config, overrides, seed
        )
    _write_json(
        output_dir / f"wp2_10_pooling_diagnostic_screens_{model_name}.json", result
    )
    return result


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    base_prior_config = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)
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
        prior_config=base_prior_config,
        frame_callback=_capture,
    )

    for model_name, (frame, spec) in captured.items():
        result = _evaluate_model(
            model_name, frame, spec, base_prior_config, args.seed, args.output_dir
        )
        print(f"{model_name}:")
        for variant_name, r in result["variants"].items():
            print(
                f"  {variant_name}: divergences={r['divergences']} rhat_max={r['rhat_max']:.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
