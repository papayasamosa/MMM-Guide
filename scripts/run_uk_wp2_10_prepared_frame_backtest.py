"""WP2.10 item 6 (analyst-directed, 2026-08-25): run the existing,
weaker-tier prepared-frame fold-refit backtest
(`application.fold_refit_service.run_leakage_safe_fold_refit`,
`reconstruction_tier=RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY`) for the
segment-level Model A candidates. WP2.9 already established that the
stronger `POINT_IN_TIME_SOURCE_RECONSTRUCTION` tier
(`run_leakage_safe_fold_refit_from_sources`) cannot be validly run against
this static historical pack (no registered `SourceVersion` upload-timing
events exist for it) - this is the next-strongest existing, real,
governed mechanism that does not require fabricating that missing
history. Explicitly the weaker tier throughout; never described as
equivalent to point-in-time source reconstruction.

Real refits (n_folds=3, draws=500/tune=500/chains=2/target_accept=0.9,
`fit_fold_with_real_model`'s own defaults - the existing function's
governed configuration, not invented here) - not a diagnostic-only
screen.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.fold_refit_service import (  # noqa: E402
    run_leakage_safe_fold_refit,
)

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-10-prepared-frame-backtest-20260825"
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
    parser.add_argument("--n-folds", type=int, default=3)
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

    pack = runner._load_pack(args.pack_dir)

    for model_name, (frame, spec) in captured.items():
        df = frame["df"]
        outcome_columns = [o.source_column for o in frame["outcomes"]]
        variables = outcome_columns + list(spec.channels) + list(spec.control_cols)
        matrix = runner._coverage_matrix(
            df,
            variables=variables,
            outcome_columns=outcome_columns,
            versions=pack.versions,
            governed_start=args.governed_start,
            governed_end=args.governed_end,
        )
        print(
            f"{model_name}: running prepared-frame fold-refit backtest ({args.n_folds} folds)..."
        )
        result = run_leakage_safe_fold_refit(
            df,
            spec,
            matrix,
            n_folds=args.n_folds,
            prior_config=prior_config,
            random_seed=args.seed,
        )
        payload = {
            "model_name": model_name,
            "reconstruction_tier": result.reconstruction_tier,
            "reconstruction_tier_caveat": (
                "RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY - the weaker "
                "prepared-frame fold-refit tier. This slices one already-"
                "prepared dataframe by date per fold; it does NOT "
                "reconstruct each fold's inputs from raw per-source tables "
                "governed by their own upload-timing/point-in-time cutoff "
                "(that stronger POINT_IN_TIME_SOURCE_RECONSTRUCTION tier "
                "requires registered SourceVersion history this static "
                "historical pack does not have - WP2.9 finding, unchanged)."
            ),
            "n_folds_requested": args.n_folds,
            "results": result.results_df.to_dict(orient="records"),
            "fold_assessments": [
                {
                    "fold_id": assessment.fold_id
                    if hasattr(assessment, "fold_id")
                    else None,
                    "is_leakage_safe": assessment.is_leakage_safe,
                }
                for assessment in result.assessments
            ],
        }
        _write_json(
            args.output_dir / f"wp2_10_prepared_frame_backtest_{model_name}.json",
            payload,
        )
        print(
            f"  {model_name}: {len(result.results_df)} result rows, tier={result.reconstruction_tier}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
