"""WP2.9 item 7 (analyst-directed, 2026-08-25): does weak Hill/adstock
identification (found in WP2.8: decay_rate/hill_K/hill_S posterior/prior
std ratio near 1.0 for nearly every channel in both products) actually
destabilise the business outputs marketers would use, or can a channel
still support useful attribution despite an imprecisely-identified
transform?

Combines three already-computed/real evidence sources - never a new
identification methodology:

1. WP2.8's own identification summary (`posterior_to_prior_std_ratio`,
   `weakly_identified` at ratio > 0.7 - WP2.8's own descriptive cut point,
   reused verbatim here, not reinvented).
2. WP2.9 item 7A's channel-level product-total contribution quantiles
   (`scripts/run_uk_wp2_9_product_level_totals.py`'s output) as the
   contribution-stability evidence.
3. A new, lightweight response-curve uncertainty check
   (`core.predict.generate_channel_curve` over a posterior-draw subsample,
   `core.uncertainty.sample_draw_indices` - the repository's existing
   subsampling convention) evaluated at each channel's own observed mean
   spend and at 2x that spend, avoiding `core.uncertainty.
   generate_channel_curve_with_uncertainty`'s CPA-by-product path, which
   needs project-level LTV/cost registries this standalone historical
   exercise does not have configured.

The resulting A/B/C classification is descriptive only (median-split
within each product's own channel set, not a new pass/fail policy) and is
reported alongside every underlying number so the analyst can re-derive
or override it.
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
from ancestry_mmm.core.predict import extract_posterior_params, generate_channel_curve  # noqa: E402
from ancestry_mmm.core.uncertainty import sample_draw_indices  # noqa: E402

DEFAULT_TRACE_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-20260825"
)
DEFAULT_IDENTIFICATION_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-evaluation-20260825"
)
DEFAULT_PRODUCT_TOTALS_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-product-level-totals-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-identification-business-impact-20260825"
)
N_DRAWS_FOR_CURVE = 100
WEAKLY_IDENTIFIED_RATIO_THRESHOLD = 0.7  # WP2.8's own cut point, reused verbatim

SPARSE_CHANNELS = {
    "uk_dna_content_marketing",
    "uk_fh_content_marketing",
    "uk_influencer",
    "uk_radio",
    "uk_tv_sponsorship_vod",
    "circulation",
    "uk_fh_midfunnel_social",
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


def _response_curve_uncertainty(
    posterior: az.InferenceData, frame: dict[str, Any], meta: Any, seed: int
) -> dict[str, Any]:
    draw_pairs = sample_draw_indices(posterior, n_draws=N_DRAWS_FOR_CURVE, seed=seed)
    x_media = np.asarray(frame["X_media"], dtype=float)
    out: dict[str, Any] = {}
    for ci, channel in enumerate(meta.channels):
        active = x_media[:, ci][x_media[:, ci] > 0]
        mean_spend = float(np.mean(active)) if active.size else 0.0
        spend_points = (
            np.array([mean_spend, 2 * mean_spend])
            if mean_spend > 0
            else np.array([0.0, 0.0])
        )
        saturation_draws = {0: [], 1: []}
        response_draws = {0: [], 1: []}
        for pair in draw_pairs:
            params = extract_posterior_params(posterior, meta, at=pair)
            curve = generate_channel_curve(
                channel, meta, params, spend_range=spend_points
            )
            for point_idx in (0, 1):
                saturation_draws[point_idx].append(
                    float(curve["saturation"].iloc[point_idx])
                )
                response_draws[point_idx].append(
                    float(curve["overall_response"].iloc[point_idx])
                )
        out[channel] = {
            "mean_active_week_spend": mean_spend,
            "at_mean_spend": {
                "saturation_quantiles": _quantiles(np.asarray(saturation_draws[0])),
                "response_quantiles": _quantiles(np.asarray(response_draws[0])),
                "response_relative_interval_width": _relative_width(
                    _quantiles(np.asarray(response_draws[0]))
                ),
            },
            "at_2x_mean_spend": {
                "saturation_quantiles": _quantiles(np.asarray(saturation_draws[1])),
                "response_quantiles": _quantiles(np.asarray(response_draws[1])),
                "response_relative_interval_width": _relative_width(
                    _quantiles(np.asarray(response_draws[1]))
                ),
            },
        }
    return out


def _classify(
    channel: str,
    identification: dict[str, Any],
    contribution_relative_width: float,
    all_widths: list[float],
    sparse: bool,
) -> dict[str, Any]:
    ratios = {
        var: identification.get(var, {})
        .get(channel, {})
        .get("posterior_to_prior_std_ratio")
        for var in ("decay_rate", "hill_K", "hill_S")
    }
    weakly_identified = any(
        r is not None and r > WEAKLY_IDENTIFIED_RATIO_THRESHOLD for r in ratios.values()
    )
    finite_widths = [w for w in all_widths if np.isfinite(w)]
    median_width = float(np.median(finite_widths)) if finite_widths else float("nan")
    high_contribution_uncertainty = (
        np.isfinite(contribution_relative_width)
        and contribution_relative_width > median_width
    )

    if sparse and (
        not np.isfinite(contribution_relative_width) or high_contribution_uncertainty
    ):
        label = "C"
        rationale = (
            "sparse/flighted channel with high contribution uncertainty - "
            "insufficient empirical support for a useful response curve"
        )
    elif not weakly_identified:
        label = "well_identified"
        rationale = "transform parameters are not classified weakly identified at this threshold"
    elif weakly_identified and not high_contribution_uncertainty:
        label = "A"
        rationale = (
            "transform weakly identified but contribution uncertainty is at or "
            "below the median for this product - may still support useful "
            "attribution despite imprecise carryover/saturation interpretation"
        )
    else:
        label = "B"
        rationale = (
            "transform weakly identified and contribution uncertainty is above "
            "the median for this product - requires substantial caution for "
            "attribution and planning"
        )
    return {
        "classification": label,
        "rationale": rationale,
        "decay_rate_ratio": ratios["decay_rate"],
        "hill_K_ratio": ratios["hill_K"],
        "hill_S_ratio": ratios["hill_S"],
        "weakly_identified_any": weakly_identified,
        "contribution_relative_interval_width": contribution_relative_width,
        "median_contribution_relative_interval_width_this_product": median_width,
        "sparse_channel": sparse,
    }


def _evaluate_model(
    model_name: str,
    frame: dict[str, Any],
    spec: Any,
    prior_config: dict[str, Any],
    trace_dir: Path,
    identification_dir: Path,
    product_totals_dir: Path,
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

    identification_payload = json.loads(
        (
            identification_dir / f"wp2_8_full_posterior_evaluation_{model_name}.json"
        ).read_text(encoding="utf-8")
    )["identification"]

    product_totals_payload = json.loads(
        (
            product_totals_dir / f"wp2_9_product_level_totals_{model_name}.json"
        ).read_text(encoding="utf-8")
    )
    contribution_widths = {
        row["channel"]: _relative_width(row["volume_contribution_quantiles"])
        for row in product_totals_payload["channel_level_totals"]["by_channel"]
    }

    curve_uncertainty = _response_curve_uncertainty(
        posterior, frame, proposed.meta, seed
    )

    all_widths = list(contribution_widths.values())
    classifications = {}
    for ch in proposed.meta.channels:
        classifications[ch] = _classify(
            ch,
            identification_payload,
            contribution_widths.get(ch, float("nan")),
            all_widths,
            ch in SPARSE_CHANNELS,
        )

    result = {
        "model_name": model_name,
        "weakly_identified_ratio_threshold": WEAKLY_IDENTIFIED_RATIO_THRESHOLD,
        "response_curve_uncertainty": curve_uncertainty,
        "classification_by_channel": classifications,
        "classification_counts": {
            label: sum(
                1 for c in classifications.values() if c["classification"] == label
            )
            for label in ("A", "B", "C", "well_identified")
        },
    }
    _write_json(
        output_dir / f"wp2_9_identification_business_impact_{model_name}.json", result
    )
    return result


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument(
        "--identification-dir", type=Path, default=DEFAULT_IDENTIFICATION_DIR
    )
    parser.add_argument(
        "--product-totals-dir", type=Path, default=DEFAULT_PRODUCT_TOTALS_DIR
    )
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
            args.identification_dir,
            args.product_totals_dir,
            args.output_dir,
            args.seed,
        )
        print(f"{model_name}: classification_counts={result['classification_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
