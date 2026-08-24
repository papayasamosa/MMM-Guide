"""WP2.5 bounded diagnostic investigation (analyst-directed, 2026-08-24),
run before any WP3 full-fit sampling is authorised.

The human analyst reviewed WP2's real UK governed pre-fit evidence
(`scripts/run_uk_prefit_governance.py`) and did **not** approve the
candidate for expensive production sampling. This script investigates five
specific findings from that evidence, all diagnostic-only:

1. Prior-predictive component decomposition - isolates which additive
   log-linear-predictor term (baseline/intercept, trend/seasonality,
   hierarchy, promotions, context/controls, media) dominates the
   implausibly wide q95/q99 outcome-scale tail, using the new
   `component_var_names` support in `core.diagnostics.
   prior_predictive_summary` (WP2.5, additive/opt-in - see
   `core.hierarchical_model.build_fh_hierarchical_model`'s new named
   `eta_trend`/`eta_season`/`eta_market`/`eta_promo`/`eta_controls`
   Deterministics). No production prior is changed.
2. DNA future-to-past timing refutation - reports each fold's
   `incremental_future_media_r2` (WP2.5 addition to `core.
   prefit_screening.build_prefit_screening_report`'s timing-refutation
   rows: future-media R2 minus that identical fold's own baseline/
   context-only R2), so shared seasonality can be distinguished from a
   genuine incremental future-media signal. Future media is never
   introduced as a production predictor.
3. Transformation sensitivity - isolates the "mature" fold (the one with
   the most training weeks) and reports its own per-transform-variant
   surrogate performance alongside the existing per-channel coefficient
   stability evidence (`channel_stability`'s `coefficient_cv`/
   `nonzero_share`), to help distinguish weak empirical support for
   flexible carryover from channel instability/collinearity signal versus
   genuine short-lived response. No production adstock prior is changed.
4. Sparse-channel review - flags the specific identification-sensitive
   channels the analyst named, including circulation's positive-value
   max-to-median ratio. No channel is removed, aggregated, pooled, or
   given a different transform/prior.
5. Fold-policy review - reports the fold manifest (train/test row counts)
   so fold 1's shallow training history can be read as a stress test
   rather than production-representative evidence for an 18/19-channel
   weekly MMM. No fold-policy default is changed by this script; any
   change belongs in a REQ-*/decision record, not here.

Writes two kinds of output:

- Raw/aggregate evidence JSON to a D-drive directory (no raw source rows,
  never committed) - the full component decomposition, fold-level
  breakdown, and collinearity matrices for the analyst's own review.
- Two repository-committed decision/findings documents under `docs/`,
  containing only already-aggregated statistics (channel names, counts,
  R2/RMSE values, quantile ranges) - never raw source rows - so the
  written analysis is available for review without requiring D-drive
  access.

This script does not fit a production model, does not run MCMC, and does
not proceed to WP3. It never selects a candidate remedy on the analyst's
behalf.
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

from ancestry_mmm.core.schema import ModelSpec  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-5-diagnostics-20260824"
)

# The additive log-linear-predictor terms core.hierarchical_model.
# build_fh_hierarchical_model now exposes as named Deterministics/free
# variables (WP2.5), covering the analyst's requested decomposition
# categories: baseline/intercept, trend/seasonality, hierarchy,
# promotions/events, context (controls), media, and likelihood/dispersion.
COMPONENT_VAR_NAMES = [
    "intercept",
    "eta_trend",
    "eta_season",
    "eta_market",
    "eta_promo",
    "eta_controls",
    "eta_channels",
    "mu",
    "alpha",
]

# Channels the analyst explicitly flagged as identification-sensitive,
# with the active-week counts cited in the review (verified below against
# the freshly computed identifiability evidence rather than assumed).
FLAGGED_CHANNELS = {
    "uk_dna_content_marketing": 2,
    "uk_fh_content_marketing": 6,
    "uk_influencer": 12,
    "uk_radio": 13,
    "uk_tv_sponsorship_vod": 16,
    "circulation": 25,
    "uk_fh_midfunnel_social": 20,
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


def _mature_fold_id(fold_manifest: list[dict[str, Any]]) -> str | None:
    if not fold_manifest:
        return None
    return max(fold_manifest, key=lambda fold: fold["train_rows"])["fold_id"]


def _transform_sensitivity_for_fold(
    surrogate_results: list[dict[str, Any]], fold_id: str
) -> list[dict[str, Any]]:
    by_variant: dict[str, list[float]] = {}
    for row in surrogate_results:
        if row["fold_id"] != fold_id:
            continue
        rmse = row["baseline_context_plus_media"].get("rmse")
        if rmse is None:
            continue
        by_variant.setdefault(row["transform_variant"], []).append(float(rmse))
    return [
        {
            "transform_variant": variant,
            "mean_test_rmse": sum(values) / len(values),
            "records": len(values),
        }
        for variant, values in sorted(by_variant.items())
    ]


def _sparse_channel_flags(support_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flags = []
    for row in support_rows:
        channel = row["channel"]
        cited_weeks = FLAGGED_CHANNELS.get(channel)
        if cited_weeks is None and row["support_status"] not in {"weak", "very_weak"}:
            continue
        flags.append(
            {
                "channel": channel,
                "positive_weeks": row["positive_weeks"],
                "distinct_positive_values": row["distinct_positive_values"],
                "positive_max_to_median": row.get("positive_max_to_median"),
                "support_status": row["support_status"],
                "cited_active_weeks": cited_weeks,
                "active_weeks_matches_citation": (
                    cited_weeks is not None and row["positive_weeks"] == cited_weeks
                ),
            }
        )
    return flags


def _run_wp2_5_for_model(
    *,
    gov,
    runner,
    model_name: str,
    frame: dict[str, Any],
    spec: ModelSpec,
    governed_start: str,
    governed_end: str,
    n_prior_samples: int,
    seed: int,
) -> dict[str, Any]:
    run_payload = gov._build_prefit_evidence(
        runner=runner,
        model_name=model_name,
        frame=frame,
        spec=spec,
        prior_config={},
        governed_start=governed_start,
        governed_end=governed_end,
        n_prior_samples=n_prior_samples,
        seed=seed,
        component_var_names=COMPONENT_VAR_NAMES,
    )

    screening_report = run_payload["screening_report"]
    identifiability_report = run_payload["identifiability_report"]

    fold_manifest = run_payload["fold_manifest"]
    mature_fold = _mature_fold_id(fold_manifest)
    transform_sensitivity = (
        _transform_sensitivity_for_fold(screening_report["surrogate_results"], mature_fold)
        if mature_fold
        else []
    )

    timing_rows = screening_report["timing_refutation"]["rows"]
    future_media_findings = [
        row
        for row in timing_rows
        if row.get("incremental_future_media_r2") is not None
        and row["incremental_future_media_r2"] > 0.3
    ]

    sparse_flags = _sparse_channel_flags(
        identifiability_report["support_identifiability"]["rows"]
    )

    return {
        "run": run_payload,
        "wp2_5": {
            "fold_manifest": fold_manifest,
            "mature_fold_id": mature_fold,
            "mature_fold_transform_sensitivity": transform_sensitivity,
            "material_future_media_findings": future_media_findings,
            "sparse_channel_flags": sparse_flags,
            "prior_predictive_component_decomposition": identifiability_report[
                "prior_predictive"
            ].get("component_decomposition"),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    parser.add_argument("--n-prior-samples", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    return parser


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)
    parser = build_parser()
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    captured: dict[str, tuple[dict[str, Any], ModelSpec]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: ModelSpec) -> None:
        captured[model_name] = (frame, spec)

    preparation_report = runner.run(
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
        prior_config={},
        frame_callback=_capture,
    )
    _write_json(
        args.output_dir / "official_preparation_report.json", preparation_report
    )

    results: dict[str, dict[str, Any]] = {}
    for model_name, (frame, spec) in captured.items():
        result = _run_wp2_5_for_model(
            gov=gov,
            runner=runner,
            model_name=model_name,
            frame=frame,
            spec=spec,
            governed_start=args.governed_start,
            governed_end=args.governed_end,
            n_prior_samples=args.n_prior_samples,
            seed=args.seed,
        )
        results[model_name] = result
        _write_json(args.output_dir / f"wp2_5_{model_name}.json", result)

    print(f"Wrote WP2.5 diagnostic evidence to {args.output_dir}")
    for model_name, result in results.items():
        readiness = result["run"]["readiness"]
        n_flags = len(result["wp2_5"]["sparse_channel_flags"])
        n_future = len(result["wp2_5"]["material_future_media_findings"])
        print(
            f"  {model_name}: readiness={readiness}, "
            f"sparse_channel_flags={n_flags}, "
            f"material_future_media_findings={n_future}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
