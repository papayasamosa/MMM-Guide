"""WP2 evidence runner: fits every candidate encoding on the full
synthetic DGP grid with the pinned PyMC stack and writes
`results.json` plus a human-readable `summary.md`.

Usage:
    uv run python scripts/wp2_named_event_response/run_evaluation.py --out <dir>

Exit code 0 when every scheduled fit completed (individual fit failures
are recorded in `results.json`, never silently dropped). Nothing here
approves a statistical method - it only measures candidates.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import arviz as az
import numpy as np
import pymc as pm
import pytensor
import scipy

from .candidates import (
    build_multi_market_model,
    build_single_market_model,
)
from .dgp import (
    KERNELS,
    Scenario,
    build_multi_market_scenario,
    build_scenarios,
)
from .metrics import (
    compute_holdout_metrics,
    compute_multi_market_metrics,
    compute_single_market_metrics,
    failure_metrics,
)

DRAWS = 300
TUNE = 300
CHAINS = 2
TARGET_ACCEPT = 0.9
SEED_BASE = 300


def versions() -> Dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "pymc": pm.__version__,
        "pytensor": pytensor.__version__,
        "arviz": az.__version__,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }


def fit(model: pm.Model, seed: int, smoke: bool) -> az.InferenceData:
    draws, tune, chains = (50, 50, 1) if smoke else (DRAWS, TUNE, CHAINS)
    with model:
        return pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=TARGET_ACCEPT,
            cores=2,
            progressbar=False,
            random_seed=seed,
        )


def _wrong_window_design(event_weeks: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    n_weeks = 156
    design = np.zeros((n_weeks, len(offsets)))
    for week in event_weeks:
        for k, offset in enumerate(offsets):
            target = week + offset
            if 0 <= target < n_weeks:
                design[target, k] = 1.0
    return design


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="wp2_evidence_out")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Small fast smoke run (reduced budget, first entries only).",
    )
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    scenarios = {sc.key: sc for sc in build_scenarios()}
    multi_shared = build_multi_market_scenario("shared")
    multi_model_c = build_multi_market_scenario("market_specific")

    grid: List[Dict[str, Any]] = []
    for key, scenario in scenarios.items():
        for candidate in (
            "S1_fixed_profile",
            "S2_parametric",
            "S3_spline_basis",
            "S4_dummies",
        ):
            grid.append({"run": "main", "scenario": key, "candidate": candidate})
    for candidate in (
        "S1_fixed_profile",
        "S2_parametric",
        "S3_spline_basis",
        "S4_dummies",
    ):
        grid.append(
            {
                "run": "multi_market_shared",
                "scenario": "multi_market",
                "candidate": candidate,
            }
        )
    grid.append(
        {
            "run": "multi_market_model_c",
            "scenario": "multi_market",
            "candidate": "S2_parametric",
        }
    )
    grid.append(
        {
            "run": "multi_market_model_c",
            "scenario": "multi_market",
            "candidate": "S5_pooled_basis",
        }
    )

    anticipatory = scenarios["anticipatory"]
    train_weeks = 120
    holdout_scenario = Scenario(
        key=anticipatory.key,
        kernel_key=anticipatory.kernel_key,
        event_weeks=anticipatory.event_weeks,
        amplitude=anticipatory.amplitude,
        seed=anticipatory.seed,
        n_markets=anticipatory.n_markets,
        promo=anticipatory.promo,
        media_burst=anticipatory.media_burst,
        seasonal_peak=anticipatory.seasonal_peak,
        structure=anticipatory.structure,
    )
    holdout_scenario.y = anticipatory.y[:train_weeks]
    holdout_scenario.x_media = anticipatory.x_media[:train_weeks]
    holdout_scenario.x_promo = anticipatory.x_promo[:train_weeks]
    holdout_scenario.event_design = anticipatory.event_design
    holdout_scenario.true = anticipatory.true
    for candidate in (
        "S1_fixed_profile",
        "S2_parametric",
        "S3_spline_basis",
        "S4_dummies",
    ):
        grid.append(
            {"run": "holdout", "scenario": "anticipatory", "candidate": candidate}
        )

    wrong_offsets = np.arange(0, 5)
    wrong_design = _wrong_window_design(anticipatory.event_weeks, wrong_offsets)
    grid.append(
        {
            "run": "sensitivity_wrong_window",
            "scenario": "anticipatory",
            "candidate": "S2_parametric",
        }
    )
    grid.append(
        {
            "run": "sensitivity_wrong_window",
            "scenario": "anticipatory",
            "candidate": "S4_dummies",
        }
    )
    grid.append(
        {
            "run": "sensitivity_oracle_fixed",
            "scenario": "anticipatory",
            "candidate": "S1_fixed_profile",
        }
    )
    grid.append(
        {
            "run": "sensitivity_wide_prior",
            "scenario": "anticipatory",
            "candidate": "S2_parametric",
        }
    )

    results: List[Dict[str, Any]] = []
    if args.smoke:
        grid = grid[:4]
    for index, entry in enumerate(grid):
        run, key, candidate = entry["run"], entry["scenario"], entry["candidate"]
        seed = SEED_BASE + index
        started = time.perf_counter()
        scenario = (
            holdout_scenario
            if run == "holdout"
            else multi_shared
            if run == "multi_market_shared"
            else multi_model_c
            if run == "multi_market_model_c"
            else scenarios[key]
        )
        model: Optional[pm.Model] = None
        error: Optional[str] = None
        idata: Optional[az.InferenceData] = None
        try:
            if run in ("multi_market_shared", "multi_market_model_c"):
                model = build_multi_market_model(scenario, candidate)
            elif run == "sensitivity_wrong_window":
                model = build_single_market_model(
                    scenario,
                    candidate,
                    event_design=wrong_design,
                    offsets=wrong_offsets,
                )
            elif run == "sensitivity_oracle_fixed":
                model = build_single_market_model(
                    scenario,
                    candidate,
                    fixed_reference=KERNELS["anticipatory"],
                )
            elif run == "sensitivity_wide_prior":
                model = build_single_market_model(scenario, candidate, wide_prior=True)
            else:
                model = build_single_market_model(scenario, candidate)
            idata = fit(model, seed, smoke=args.smoke)
        except Exception as exc:  # noqa: BLE001 - evidence records failures
            error = f"{type(exc).__name__}: {exc}"
        runtime = time.perf_counter() - started
        if error is None:
            assert idata is not None
            try:
                if run == "holdout":
                    metrics = {
                        **compute_single_market_metrics(
                            holdout_scenario, candidate, idata, runtime
                        ),
                        **compute_holdout_metrics(
                            anticipatory, candidate, idata, train_weeks
                        ),
                    }
                elif run == "sensitivity_wrong_window":
                    metrics = compute_single_market_metrics(
                        scenario, candidate, idata, runtime, event_design=wrong_design
                    )
                elif run in ("multi_market_shared", "multi_market_model_c"):
                    metrics = compute_multi_market_metrics(
                        scenario, candidate, idata, runtime
                    )
                else:
                    metrics = compute_single_market_metrics(
                        scenario, candidate, idata, runtime
                    )
            except Exception as exc:  # noqa: BLE001 - metrics bugs are recorded
                error = f"metrics: {type(exc).__name__}: {exc}"
        if error is not None:
            record = {
                "run": run,
                "scenario": key,
                "candidate": candidate,
                "seed": seed,
                "metrics": failure_metrics(error, runtime),
            }
        else:
            record = {
                "run": run,
                "scenario": key,
                "candidate": candidate,
                "seed": seed,
                "metrics": metrics,
            }
        results.append(record)
        (out / "results.json").write_text(
            json.dumps({"versions": versions(), "results": results}, indent=2)
        )
        print(
            f"[{index + 1}/{len(grid)}] {run}/{key}/{candidate}: "
            f"{record['metrics'].get('status')} "
            f"rmse={record['metrics'].get('event_rmse')} "
            f"({record['metrics'].get('runtime_s')}s)",
            flush=True,
        )

    (out / "summary.md").write_text(_summary_markdown(results), encoding="utf-8")
    print(f"wrote {out / 'results.json'} and {out / 'summary.md'}")
    return 0


def _summary_markdown(results: List[Dict[str, Any]]) -> str:
    lines = [
        "# WP2 named-event response evidence - run summary",
        "",
        "Generated by `scripts/wp2_named_event_response/run_evaluation.py`.",
        "",
    ]
    lines.append(
        "| run | scenario | candidate | status | event_rmse | amplitude_ratio | media_bias_max | r_hat_max | runtime_s |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for record in results:
        metrics = record["metrics"]
        lines.append(
            f"| {record['run']} | {record['scenario']} | {record['candidate']} "
            f"| {metrics.get('status')} | {metrics.get('event_rmse')} "
            f"| {metrics.get('amplitude_ratio')} | {metrics.get('media_bias_max')} "
            f"| {metrics.get('r_hat_max')} | {metrics.get('runtime_s')} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
