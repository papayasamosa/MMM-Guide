"""Work Package 1 (2026-08-27, follow-up to WP2.11): a reusable preflight
entry point that runs source-to-model reconciliation
(`core.source_model_reconciliation`) and per-fold data-support diagnostics
(`core.fold_data_support`) for exactly the variables the current governed
UK Model A candidate consumes - no PyMC model is built and no sampling
occurs. Built so a candidate can be checked in seconds, before starting an
expensive fold-refit backtest that might otherwise run silent for hours
before a targeted probe finds inadequate support or a broken source
mapping (the WP2.11 item-5 incident both of the diagnostics above cite).

Reuses the exact same governed pipeline
(`scripts/run_uk_production_fit.py`'s `run()`, `fit_enabled=False`) the
WP2.11 backtest script (`run_uk_wp2_11_prepared_frame_backtest.py`) and
the pre-fit governance script (`run_uk_prefit_governance.py`) already use
- never a second, divergent frame-construction path. `run()`'s new
`sources_callback` parameter (WP1) supplies the raw per-source-domain
frames (`standard_outcomes`/`standard_activity`/`standard_context`) this
script needs for the "raw" stage of reconciliation; `frame_callback`
supplies the prepared model-ready frame for the "canonical" stage and for
building the same expanding-window folds a real fold-refit backtest would
use.

This module invents no support threshold and no pass/fail verdict -
`core.fold_data_support.SupportThresholds`/`core.source_model_
reconciliation`'s own docstrings explain why (a numeric cutoff is a
statistical/business decision, and the current UK activity data is itself
under separate review for suspected source-to-model mapping issues as of
2026-08-26/27). It reports evidence only.

Usage:
    python scripts/run_uk_source_model_preflight.py
    python scripts/run_uk_source_model_preflight.py --only-model family_history
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

from ancestry_mmm.core.preflight_reconciliation_report import (  # noqa: E402
    ModelPreflightReport,
    build_model_preflight_report,
    format_preflight_table,
)

DEFAULT_OUTPUT_DIR = Path(r"D:\Ancestry-MMM\test-artifacts\uk-source-model-preflight")


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


def run_preflight(
    *,
    pack_dir: Path,
    output_dir: Path,
    only_model: str | None = None,
    governed_start: str | None = None,
    governed_end: str | None = None,
    n_folds: int = 3,
    write_output: bool = True,
) -> dict[str, ModelPreflightReport]:
    """Run the preflight (no MCMC) and return each captured model's
    `ModelPreflightReport`, keyed by model name.

    `write_output=True` (default) writes JSON + a human-readable table to
    `output_dir` per model and prints the table; a caller wanting only the
    in-memory reports (e.g. `--preflight-only` mode of the WP2.11 backtest
    script, or a test) can pass `write_output=False` to skip all file I/O.
    """
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    resolved_governed_start = governed_start or runner.COMMON_WINDOW_START
    resolved_governed_end = governed_end or runner.COMMON_WINDOW_END

    captured_frames: dict[str, tuple[dict[str, Any], Any]] = {}
    captured_sources: dict[str, Any] = {}

    def _capture_frame(model_name: str, frame: dict[str, Any], spec: Any) -> None:
        captured_frames[model_name] = (frame, spec)

    def _capture_sources(sources: dict[str, Any]) -> None:
        captured_sources["sources"] = sources

    runner.run(
        pack_dir=pack_dir,
        output_dir=output_dir / "official_preparation_preflight",
        draws=2000,
        tune=1000,
        chains=4,
        target_accept=0.9,
        seed=0,
        fit_enabled=False,
        only_model=only_model,
        governed_start=resolved_governed_start,
        governed_end=resolved_governed_end,
        prior_config=dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG),
        frame_callback=_capture_frame,
        sources_callback=_capture_sources,
    )

    raw_sources = captured_sources.get("sources") or {}
    reports: dict[str, ModelPreflightReport] = {}
    if write_output:
        output_dir.mkdir(parents=True, exist_ok=True)

    for model_name, (frame, spec) in captured_frames.items():
        df = frame["df"]
        outcome_columns = [item.source_column for item in frame["outcomes"]]
        report = build_model_preflight_report(
            model_name,
            df,
            spec.date_col,
            channels=spec.channels,
            control_cols=spec.control_cols,
            outcome_columns=outcome_columns,
            raw_sources=raw_sources,
            n_folds=n_folds,
        )
        reports[model_name] = report

        table = format_preflight_table(report)
        print(table)
        if write_output:
            _write_json(output_dir / f"preflight_{model_name}.json", report.to_dict())
            (output_dir / f"preflight_{model_name}.txt").write_text(
                table, encoding="utf-8"
            )

    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    parser.add_argument("--n-folds", type=int, default=3)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    args = parser.parse_args(argv)

    run_preflight(
        pack_dir=args.pack_dir,
        output_dir=args.output_dir,
        only_model=args.only_model,
        governed_start=args.governed_start,
        governed_end=args.governed_end,
        n_folds=args.n_folds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
