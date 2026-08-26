"""WP2.11 item 1 (analyst-directed, 2026-08-26): H1 diagnostic hierarchy
challenger - the current governed segment Model A candidates
(unchanged outcomes, media, transforms, controls, trend, seasonality,
promo, causal/pathway routing, DNA halo treatment, likelihood, history)
refit with `prior_config["pooled_beta_reference"]=True` - the existing,
pre-dating-this-work-package gate in `core.hierarchical_model.
build_fh_hierarchical_model` that deterministically zeroes `sigma_pool`/
`z_offset`, sharing each channel's response strength across outcomes
while every outcome keeps its own intercept/trend/season/controls/promo.

Not the WP2.10 Overall challenger: outcomes are NOT summed before
fitting. Reuses `scripts/run_uk_production_fit.py`'s own `run()`
unmodified, real governed pre-fit/fit pipeline, real UK source pack -
the only difference from a normal production run is the one prior_config
key. `--short-screen-only` runs WP2.7's own short-screen configuration
(`draws=100, tune=150, chains=2, target_accept=0.95`) first; the full
posterior (the brief's `chains=4, draws=2000, tune=1000, target_accept=
0.90`) is only skipped if explicitly requested or if the short screen is
pathological (many divergences AND high R-hat together - reported, not
silently overridden).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import warnings
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.models import compute_model_diagnostics, fit_model  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-11-h1-complete-pooling-20260826"
)
SHORT_SCREEN_DRAWS = 100
SHORT_SCREEN_TUNE = 150
SHORT_SCREEN_CHAINS = 2
SHORT_SCREEN_TARGET_ACCEPT = 0.95


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


def _short_screen(
    model_name: str,
    frame: dict[str, Any],
    spec: Any,
    prior_config: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
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
    pathological = diagnostics["divergences"] > 10 and diagnostics["rhat_max"] > 1.5
    return {
        "model_name": model_name,
        "rhat_max": diagnostics["rhat_max"],
        "ess_min": diagnostics["ess_min"],
        "divergences": diagnostics["divergences"],
        "pathological": pathological,
    }


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
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    parser.add_argument("--short-screen-only", action="store_true")
    parser.add_argument("--skip-short-screen", action="store_true")
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    prior_config: dict[str, Any] = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)
    prior_config["pooled_beta_reference"] = True

    captured: dict[str, tuple[dict[str, Any], Any]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: Any) -> None:
        captured[model_name] = (frame, spec)

    if not args.skip_short_screen:
        runner.run(
            pack_dir=args.pack_dir,
            output_dir=args.output_dir / "official_preparation_screen",
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
        screen_results = {}
        for model_name, (frame, spec) in captured.items():
            result = _short_screen(model_name, frame, spec, prior_config, args.seed)
            screen_results[model_name] = result
            print(
                f"{model_name} H1 short screen: divergences={result['divergences']} rhat_max={result['rhat_max']:.3f} pathological={result['pathological']}"
            )
        _write_json(args.output_dir / "wp2_11_h1_short_screen.json", screen_results)
        if args.short_screen_only:
            return 0
        if any(r["pathological"] for r in screen_results.values()):
            print(
                "H1 short screen pathological for at least one model - stopping before full posterior. See wp2_11_h1_short_screen.json."
            )
            return 1

    print(
        "Proceeding to H1 full posterior (chains=4, draws=2000, tune=1000, target_accept=0.90)..."
    )
    report = runner.run(
        pack_dir=args.pack_dir,
        output_dir=args.output_dir,
        draws=2000,
        tune=1000,
        chains=4,
        target_accept=0.9,
        seed=args.seed,
        fit_enabled=True,
        only_model=args.only_model,
        governed_start=args.governed_start,
        governed_end=args.governed_end,
        prior_config=prior_config,
    )
    _write_json(args.output_dir / "wp2_11_h1_production_fit_report.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
