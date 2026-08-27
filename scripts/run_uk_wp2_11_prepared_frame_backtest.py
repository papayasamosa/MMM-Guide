"""WP2.11 item 5 (analyst-directed, 2026-08-26): run the existing,
weaker-tier prepared-frame fold-refit backtest
(`application.fold_refit_service.run_leakage_safe_fold_refit`,
`reconstruction_tier=RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY`) for the
current governed segment Model A candidates, and (via `--prior-config-mode`)
for the H1/H2 diagnostic hierarchy challengers - now that WP2.11 item 4
(PR #317, merged) repairs `fit_fold_with_real_model`'s outcome-catalogue
propagation defect WP2.10 found in the predecessor script
(`run_uk_wp2_10_prepared_frame_backtest.py`, which never passed the real
governed `outcomes` catalogue and so silently exercised the legacy
fallback catalogue instead of the real candidate).

Explicitly still the weaker tier throughout (same WP2.9/WP2.10 finding:
`POINT_IN_TIME_SOURCE_RECONSTRUCTION` cannot be validly run against this
static historical pack - no registered `SourceVersion` upload-timing
events exist for it) - never described as equivalent to point-in-time
source reconstruction.

Real refits (n_folds=3, draws=500/tune=500/chains=2/target_accept=0.9,
`fit_fold_with_real_model`'s own governed defaults) - not a diagnostic-only
screen. Threads through the exact same `outcomes`/`dna_outcome_id`/
`direct_dna_outcome_ids`/`causal_graph`/`media_outcome_pathways`/
`activity_definitions`/`net_billthrough_metadata` the real production fit
uses (`scripts/run_uk_production_fit.py`'s own `run()`), all captured from
the same governed frame - never a second, divergent construction.

WP1 (2026-08-27) fix: this runner previously never passed
`on_progress_line` to `run_leakage_safe_fold_refit`, so a real run left a
caller with no visibility during sampling - the exact "silent for 6+
hours" failure mode `core.fold_data_support`/`core.fit_progress` were
built to fix (see the item-5 incident note above), still reproducible
through this specific entry point despite those modules already existing.
Every progress line is now both printed with an explicit flush (`core.
fit_progress`'s own convention - never relies on the process's own
buffering mode) and appended to a per-run, per-`prior-config-mode` log
file under `--output-dir` (also explicitly flushed after every write), so
progress remains inspectable even if the terminal session is lost.

Per-fold checkpoint/resume (considered, not implemented, WP1 2026-08-27):
adding safe resume-from-last-completed-fold support was considered for
this runner but not built. `run_leakage_safe_fold_refit` currently
returns one aggregate `LeakageSafeFoldRefitResult` only after every fold
completes - there is no existing per-fold persistence boundary to resume
from without changing that function's own return/streaming contract, and
doing so is a genuine service-contract decision (what a partial run
persists, how a resumed run re-validates that a persisted fold's inputs
still match the current candidate/frame, whether a changed prior_config
invalidates prior folds) rather than a mechanical addition. Deferred
pending that decision rather than guessed at here; the new `--preflight-
only` mode and live progress logging above at least let an operator judge
*before* starting whether a run is likely to complete without needing to
resume it.

WP1 (2026-08-27) `--preflight-only`: runs `core.source_model_
reconciliation` and `core.fold_data_support` (via `core.preflight_
reconciliation_report`) for the same captured frame/spec/raw-sources this
runner already builds, then exits before calling `run_leakage_safe_fold_
refit` at all - no PyMC model is built, no sampling occurs. Lets a
candidate be checked in seconds instead of discovering sparse support or a
broken source mapping only after a real run has been sitting silent for
hours (the item-5 incident above).
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
from ancestry_mmm.core.preflight_reconciliation_report import (  # noqa: E402
    build_model_preflight_report,
    format_preflight_table,
)

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-11-prepared-frame-backtest-20260826"
)

PRIOR_CONFIG_MODES = ("current", "h1_complete_pooling", "h2_shared_pooling_scale")


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


def _make_progress_reporter(log_path: Path) -> Any:
    """Return an `on_progress_line` callable that both prints (flushed) and
    appends to `log_path` (also flushed after every line), so a fold-refit
    run's progress is inspectable live and durably even if the terminal
    session that started it is lost - the exact gap the item-5 incident
    (module docstring above) found."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")

    def _report(line: str) -> None:
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    return _report


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    parser.add_argument("--seed", type=int, default=20260826)
    parser.add_argument("--n-folds", type=int, default=3)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    parser.add_argument(
        "--prior-config-mode", choices=PRIOR_CONFIG_MODES, default="current"
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help=(
            "Run source-to-model reconciliation and per-fold data-support "
            "diagnostics only, then exit - no PyMC model is built and no "
            "sampling occurs. Use before a real run to check candidate "
            "health in seconds instead of hours."
        ),
    )
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    prior_config = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)
    if args.prior_config_mode == "h1_complete_pooling":
        prior_config["pooled_beta_reference"] = True
    elif args.prior_config_mode == "h2_shared_pooling_scale":
        prior_config["shared_pooling_scale"] = True

    captured: dict[str, tuple[dict[str, Any], Any]] = {}
    captured_sources: dict[str, Any] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: Any) -> None:
        captured[model_name] = (frame, spec)

    def _capture_sources(sources: dict[str, Any]) -> None:
        captured_sources["sources"] = sources

    runner.run(
        pack_dir=args.pack_dir,
        output_dir=args.output_dir / f"official_preparation_{args.prior_config_mode}",
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
        sources_callback=_capture_sources,
    )

    if args.preflight_only:
        raw_sources = captured_sources.get("sources") or {}
        for model_name, (frame, spec) in captured.items():
            df = frame["df"]
            outcome_columns = [o.source_column for o in frame["outcomes"]]
            report = build_model_preflight_report(
                model_name,
                df,
                spec.date_col,
                channels=spec.channels,
                control_cols=spec.control_cols,
                outcome_columns=outcome_columns,
                raw_sources=raw_sources,
                n_folds=args.n_folds,
            )
            table = format_preflight_table(report)
            print(table)
            _write_json(
                args.output_dir
                / f"wp2_11_prepared_frame_backtest_{args.prior_config_mode}_{model_name}_preflight.json",
                report.to_dict(),
            )
            (
                args.output_dir
                / f"wp2_11_prepared_frame_backtest_{args.prior_config_mode}_{model_name}_preflight.txt"
            ).write_text(table, encoding="utf-8")
        return 0

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
        direct_dna_outcome_ids = (
            [item.outcome_id for item in frame["outcomes"]]
            if model_name == "dna_kit"
            else None
        )
        print(
            f"{model_name} [{args.prior_config_mode}]: running prepared-frame "
            f"fold-refit backtest ({args.n_folds} folds) with the real "
            f"governed outcome catalogue ({len(frame['outcomes'])} outcomes)..."
        )
        progress_log_path = (
            args.output_dir
            / f"wp2_11_prepared_frame_backtest_{args.prior_config_mode}_{model_name}_progress.log"
        )
        on_progress_line = _make_progress_reporter(progress_log_path)
        result = run_leakage_safe_fold_refit(
            df,
            spec,
            matrix,
            n_folds=args.n_folds,
            prior_config=prior_config,
            random_seed=args.seed,
            outcomes=frame["outcomes"],
            dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
            direct_dna_outcome_ids=direct_dna_outcome_ids,
            causal_graph=None,
            media_outcome_pathways=frame.get("media_outcome_pathways"),
            activity_definitions=frame.get("activity_definitions"),
            net_billthrough_metadata=frame.get("net_billthrough_metadata"),
            on_progress_line=on_progress_line,
        )
        payload = {
            "model_name": model_name,
            "prior_config_mode": args.prior_config_mode,
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
            "outcome_ids_used": [item.outcome_id for item in frame["outcomes"]],
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
            args.output_dir
            / f"wp2_11_prepared_frame_backtest_{args.prior_config_mode}_{model_name}.json",
            payload,
        )
        print(
            f"  {model_name} [{args.prior_config_mode}]: {len(result.results_df)} "
            f"result rows, tier={result.reconstruction_tier}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
