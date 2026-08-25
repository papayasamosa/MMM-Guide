"""WP2.10 item 2 (analyst-directed, 2026-08-25): inspect the current
outcome-level hierarchy/pooling structure and explain why the funnel
(`mu_channel`/`sigma_pool`/`z_offset`) remains weakly identified, using
the already-saved posterior traces (target_accept=0.90 and 0.95, both
products) - no new fit, no production change.

`core.hierarchical_model.build_fh_hierarchical_model`'s partial-pooling
layer is `log_beta[o, c] = mu_channel[c] + sigma_pool[c] * z_offset[o, c]`
(non-centred, one `sigma_pool[c]` per channel, dims=("outcome","channel")).
A hierarchical variance parameter's identifiability scales with the
number of groups it pools across - Family History has 3 outcome groups
per channel, DNA has only 2 - so this script explicitly quantifies that
mechanical explanation alongside the empirical evidence (which channels
show the most pooling tension, whether sparse channels dominate it,
how different the fitted per-outcome channel effects actually are).
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

DEFAULT_TRACE_DIRS = {
    "0.90": Path(
        r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-20260825"
    ),
    "0.95": Path(
        r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-target-accept-0.95-20260825"
    ),
}
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-10-pooling-geometry-20260825"
)
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


def _pooling_geometry_for_trace(
    idata: az.InferenceData, channel_coord: list[str], outcome_coord: list[str]
) -> dict[str, Any]:
    post = idata.posterior
    sigma_pool = (
        post["sigma_pool"]
        .stack(sample=("chain", "draw"))
        .transpose("channel", "sample")
        .values
    )
    z_offset = (
        post["z_offset"]
        .stack(sample=("chain", "draw"))
        .transpose("outcome", "channel", "sample")
        .values
    )
    log_beta = (
        post["log_beta"]
        .stack(sample=("chain", "draw"))
        .transpose("outcome", "channel", "sample")
        .values
    )
    n_outcomes = len(outcome_coord)

    per_channel: list[dict[str, Any]] = []
    for c_idx, channel in enumerate(channel_coord):
        sp = sigma_pool[c_idx]
        # Per-outcome deviation from the pooled mean, in the same units as
        # log_beta (sigma_pool[c] * z_offset[o, c] per draw).
        deviations = sp[None, :] * z_offset[:, c_idx, :]  # (outcome, sample)
        deviation_magnitude = np.abs(deviations).mean(
            axis=1
        )  # mean |deviation| per outcome
        # Actual fitted per-outcome channel effect spread (exp(log_beta),
        # the real multiplicative effect the model uses) - how different
        # are the outcomes' fitted channel effects, in the units that
        # actually enter eta.
        beta_by_outcome = np.exp(log_beta[:, c_idx, :]).mean(
            axis=1
        )  # posterior mean per outcome
        beta_spread_ratio = (
            float(np.max(beta_by_outcome) / np.min(beta_by_outcome))
            if np.min(beta_by_outcome) > 0
            else None
        )
        per_channel.append(
            {
                "channel": channel,
                "sparse_channel": channel in SPARSE_CHANNELS,
                "sigma_pool_quantiles": _quantiles(sp),
                "sigma_pool_mean": float(np.mean(sp)),
                "per_outcome_deviation_magnitude_mean": {
                    outcome_coord[o]: float(deviation_magnitude[o])
                    for o in range(n_outcomes)
                },
                "per_outcome_fitted_beta_posterior_mean": {
                    outcome_coord[o]: float(beta_by_outcome[o])
                    for o in range(n_outcomes)
                },
                "fitted_beta_max_over_min_ratio_across_outcomes": beta_spread_ratio,
            }
        )
    per_channel.sort(key=lambda row: row["sigma_pool_mean"], reverse=True)

    sparse_sigma = [r["sigma_pool_mean"] for r in per_channel if r["sparse_channel"]]
    nonsparse_sigma = [
        r["sigma_pool_mean"] for r in per_channel if not r["sparse_channel"]
    ]

    return {
        "n_outcomes": n_outcomes,
        "n_channels": len(channel_coord),
        "per_channel_sorted_by_sigma_pool": per_channel,
        "sparse_vs_nonsparse_sigma_pool_mean": {
            "sparse_channels_mean_sigma_pool": float(np.mean(sparse_sigma))
            if sparse_sigma
            else None,
            "non_sparse_channels_mean_sigma_pool": float(np.mean(nonsparse_sigma))
            if nonsparse_sigma
            else None,
            "n_sparse": len(sparse_sigma),
            "n_non_sparse": len(nonsparse_sigma),
        },
        "top5_strongest_pooling_tension_channels": [
            r["channel"] for r in per_channel[:5]
        ],
    }


def _evaluate_model(model_name: str, output_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"model_name": model_name}
    for label, trace_dir in DEFAULT_TRACE_DIRS.items():
        trace_path = trace_dir / model_name / "posterior.nc"
        if not trace_path.exists():
            continue
        idata = az.from_netcdf(trace_path)
        channel_coord = list(idata.posterior.coords["channel"].values)
        outcome_coord = list(idata.posterior.coords["outcome"].values)
        result[f"target_accept_{label}"] = _pooling_geometry_for_trace(
            idata, channel_coord, outcome_coord
        )
    n_outcomes = result.get("target_accept_0.90", {}).get("n_outcomes")
    result["group_count_explanation"] = (
        f"This model has {n_outcomes} outcome group(s) per channel for sigma_pool "
        "to be identified from. A hierarchical variance parameter's "
        "identifiability improves with the number of groups it pools "
        "across; 2-3 groups is a genuinely small-group regime where "
        "sigma_pool is only weakly informed by data regardless of "
        "reparameterisation (non-centred parameterisation, already in use, "
        "removes the classic mu/sigma correlation funnel but cannot "
        "manufacture identifying information the data does not contain)."
    )
    _write_json(output_dir / f"wp2_10_pooling_geometry_{model_name}.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    models = [args.only_model] if args.only_model else ["family_history", "dna_kit"]
    for model_name in models:
        result = _evaluate_model(model_name, args.output_dir)
        top = result.get("target_accept_0.90", {}).get(
            "top5_strongest_pooling_tension_channels", []
        )
        print(
            f"{model_name}: n_outcomes={result.get('target_accept_0.90', {}).get('n_outcomes')} top pooling-tension channels={top}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
