"""WP2.7 item 3 (analyst-directed, 2026-08-25): re-run the DNA-only
transformation-collinearity diagnostic from WP2.6
(`scripts/run_uk_wp2_6_transform_collinearity.py`) with
`uk_dna_content_marketing` omitted from the diagnostic design matrix,
because WP2.6 found it constant-zero in the mature fold's training
sample - which made the previous run's condition-number/VIF numbers for
DNA an artefact of that one channel's fold coverage rather than a real
adstock-collinearity signal.

This omits the channel from this diagnostic's own design matrix only. It
does not remove `uk_dna_content_marketing` from Model A, does not change
any production adstock/transform default, and does not select a
transform variant on the analyst's behalf. Family History is unaffected
and not re-run here (WP2.6's existing Family History result already
excludes no channels and is not implicated by this artefact).

Reuses `core.prefit_screening`'s own transform/fold-construction helpers
directly - no second implementation of the adstock/Hill transform or
fold construction exists here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.core.prefit_screening import (  # noqa: E402
    _base_features,
    _media_transform,
    _screen_grid,
    build_leakage_safe_folds,
)

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-7-dna-collinearity-recheck-20260825"
)

EXCLUDED_CHANNEL = "uk_dna_content_marketing"


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


def _vif(design: np.ndarray, column_index: int) -> float:
    y = design[:, column_index]
    others = np.delete(design, column_index, axis=1)
    if others.shape[1] == 0 or np.std(y) == 0:
        return float("nan")
    others_with_intercept = np.column_stack([np.ones(others.shape[0]), others])
    coef, *_ = np.linalg.lstsq(others_with_intercept, y, rcond=None)
    predicted = others_with_intercept @ coef
    ss_res = np.sum((y - predicted) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    if ss_tot <= 0:
        return float("nan")
    r2 = 1 - ss_res / ss_tot
    if r2 >= 1.0:
        return float("inf")
    return float(1.0 / (1.0 - r2))


def _condition_number(design: np.ndarray) -> float:
    centred = design - design.mean(axis=0, keepdims=True)
    scale = centred.std(axis=0, keepdims=True)
    scale = np.where(scale > 0, scale, 1.0)
    standardised = centred / scale
    return float(np.linalg.cond(standardised))


def _mature_fold_train_mask(dates: Any) -> tuple[np.ndarray, str]:
    folds = build_leakage_safe_folds(dates, n_folds=3, min_train_periods=8)
    mature = max(folds, key=lambda fold: fold["train_rows"])
    return mature["train_mask"], mature["fold_id"]


def _analyse_dna(frame: dict[str, Any]) -> dict[str, Any]:
    media = np.asarray(frame["X_media"], dtype=float)
    dates = frame.get("dates", np.arange(media.shape[0]))
    markets = frame.get("market_idx")
    all_channels = [str(c) for c in frame["channels"]]
    keep_indices = [
        index for index, name in enumerate(all_channels) if name != EXCLUDED_CHANNEL
    ]
    channels = [all_channels[index] for index in keep_indices]
    if len(channels) == len(all_channels):
        raise RuntimeError(
            f"Expected excluded channel {EXCLUDED_CHANNEL!r} to be present in "
            f"the DNA frame's channel list; found none. Channel list may have "
            f"changed since WP2.6 - investigate before trusting this result."
        )

    train_mask, mature_fold_id = _mature_fold_train_mask(dates)
    rows = int(train_mask.sum())

    base = _base_features(frame, media.shape[0])[train_mask]

    grid = _screen_grid(None)
    variant_transformed: dict[str, np.ndarray] = {}
    variant_design: dict[str, np.ndarray] = {}
    for variant_index, variant in enumerate(grid):
        transformed, _k = _media_transform(
            media,
            markets,
            train_mask,
            decay=variant["decay"],
            hill_s=variant["hill_s"],
        )
        transformed_train = transformed[train_mask][:, keep_indices]
        variant_transformed[f"T{variant_index + 1}"] = transformed_train
        variant_design[f"T{variant_index + 1}"] = np.column_stack(
            [base[:, 1:], transformed_train]
        )

    vif_and_condition = []
    for variant_name, design in variant_design.items():
        channel_vifs = {
            channel: _vif(design, (base.shape[1] - 1) + index)
            for index, channel in enumerate(channels)
        }
        vif_and_condition.append(
            {
                "transform_variant": variant_name,
                "condition_number": _condition_number(design),
                "channel_vif": channel_vifs,
            }
        )

    base_overlap = {}
    cross_channel_overlap = {}
    for variant_name in ("T1", "T6"):
        matrix = variant_transformed[variant_name]
        rows_out = []
        cross_out = []
        for channel_index, channel in enumerate(channels):
            channel_values = matrix[:, channel_index]
            base_correlations = []
            for base_col_index in range(base.shape[1]):
                base_values = base[:, base_col_index]
                corr = (
                    float(np.corrcoef(channel_values, base_values)[0, 1])
                    if np.std(channel_values) > 0 and np.std(base_values) > 0
                    else None
                )
                base_correlations.append(corr)
            other_channel_correlations = {}
            for other_index, other_channel in enumerate(channels):
                if other_index == channel_index:
                    continue
                other_values = matrix[:, other_index]
                corr = (
                    float(np.corrcoef(channel_values, other_values)[0, 1])
                    if np.std(channel_values) > 0 and np.std(other_values) > 0
                    else None
                )
                other_channel_correlations[other_channel] = corr
            rows_out.append(
                {
                    "channel": channel,
                    "max_abs_correlation_with_base_columns": max(
                        (abs(c) for c in base_correlations if c is not None),
                        default=None,
                    ),
                    "max_abs_correlation_with_other_channels": max(
                        (
                            abs(c)
                            for c in other_channel_correlations.values()
                            if c is not None
                        ),
                        default=None,
                    ),
                }
            )
            cross_out.append(
                {
                    "channel": channel,
                    "mean_abs_correlation_with_other_channels": (
                        float(
                            np.mean(
                                [
                                    abs(c)
                                    for c in other_channel_correlations.values()
                                    if c is not None
                                ]
                            )
                        )
                        if any(
                            c is not None
                            for c in other_channel_correlations.values()
                        )
                        else None
                    ),
                    "mean_abs_correlation_with_base_columns": (
                        float(
                            np.mean(
                                [abs(c) for c in base_correlations if c is not None]
                            )
                        )
                        if any(c is not None for c in base_correlations)
                        else None
                    ),
                }
            )
        base_overlap[variant_name] = rows_out
        cross_channel_overlap[variant_name] = cross_out

    mean_base_corr_by_variant = {
        variant_name: (
            float(
                np.mean(
                    [
                        r["mean_abs_correlation_with_base_columns"]
                        for r in rows
                        if r["mean_abs_correlation_with_base_columns"] is not None
                    ]
                )
            )
        )
        for variant_name, rows in cross_channel_overlap.items()
    }
    mean_cross_corr_by_variant = {
        variant_name: (
            float(
                np.mean(
                    [
                        r["mean_abs_correlation_with_other_channels"]
                        for r in rows
                        if r["mean_abs_correlation_with_other_channels"] is not None
                    ]
                )
            )
        )
        for variant_name, rows in cross_channel_overlap.items()
    }

    return {
        "model_name": "dna_kit",
        "excluded_channel": EXCLUDED_CHANNEL,
        "excluded_channel_reason": (
            "constant-zero in the mature fold's training sample per WP2.6 "
            "(scripts/run_uk_wp2_6_transform_collinearity.py real-data run) "
            "- excluded from this diagnostic's design matrix only, not from "
            "Model A"
        ),
        "mature_fold_id": mature_fold_id,
        "mature_fold_train_rows": rows,
        "base_feature_columns": int(base.shape[1]),
        "channels_included": channels,
        "vif_and_condition_number": vif_and_condition,
        "base_overlap_t1_vs_t6": base_overlap,
        "mean_base_correlation_by_variant_t1_and_t6": mean_base_corr_by_variant,
        "mean_cross_channel_correlation_by_variant_t1_and_t6": mean_cross_corr_by_variant,
    }


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

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
        only_model="dna_kit",
        governed_start=args.governed_start,
        governed_end=args.governed_end,
        prior_config={},
        frame_callback=_capture,
    )

    frame, _spec = captured["dna_kit"]
    result = _analyse_dna(frame)
    _write_json(args.output_dir / "wp2_7_dna_collinearity_recheck.json", result)
    print(f"dna_kit: wrote DNA collinearity recheck to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
