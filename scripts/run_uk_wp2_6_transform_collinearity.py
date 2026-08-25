"""WP2.6 item 3 (analyst-directed, 2026-08-24): quantify collinearity
between the T1-T6 transformed media variants and the rest of the design
matrix on the mature fold, to help determine whether T1/T2's better
surrogate performance (WP2.5 finding) is substantially consistent with
heavier-adstock variants overlapping more with baseline/context features,
rather than genuinely weak support or a real short-lived response.

Reuses `core.prefit_screening`'s own transform/fold-construction helpers
(`_media_transform`, `_screen_grid`, `build_leakage_safe_folds`) directly
- no second implementation of the adstock/Hill transform or fold
construction exists here. Diagnostic-only: this script fits no
production model, changes no adstock prior, and selects no transform
variant on the analyst's behalf.
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
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-6-collinearity-20260824"
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


def _vif(design: np.ndarray, column_index: int) -> float:
    """Variance inflation factor for one column of a design matrix: fit
    that column as a linear function of every other column and return
    1/(1-R2). A constant (zero-variance) column, or a design with fewer
    than 2 informative predictors, has no defined VIF - returns None
    rather than a divide-by-zero or fabricated large number."""
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


def _analyse_model(
    model_name: str, frame: dict[str, Any], transform_config: dict[str, Any] | None
) -> dict[str, Any]:
    media = np.asarray(frame["X_media"], dtype=float)
    dates = frame.get("dates", np.arange(media.shape[0]))
    markets = frame.get("market_idx")
    channels = [str(c) for c in frame["channels"]]
    train_mask, mature_fold_id = _mature_fold_train_mask(dates)
    rows = int(train_mask.sum())

    base = _base_features(frame, media.shape[0])[train_mask]
    # base columns are [intercept, trend?, fourier..., X_controls?] per
    # core.prefit_screening._base_features - trend/fourier/context
    # correlations below use base's own columns directly rather than
    # re-deriving them, so this stays exactly consistent with what the
    # mature-fold surrogate models in WP2.5 actually saw.

    grid = _screen_grid(transform_config)
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
        transformed_train = transformed[train_mask]
        variant_transformed[f"T{variant_index + 1}"] = transformed_train
        # base[:, 0] is the constant intercept column (core.prefit_
        # screening._base_features always prepends it) - excluded here
        # because VIF/condition-number diagnostics regress each column
        # against an explicit intercept of their own; leaving the original
        # constant column in as well makes the matrix trivially rank-
        # deficient (a standardised constant column is all-zero) and
        # inflates every VIF/condition number as an artefact of double-
        # counting the intercept, not a real collinearity finding.
        variant_design[f"T{variant_index + 1}"] = np.column_stack(
            [base[:, 1:], transformed_train]
        )

    # Pairwise correlation between T1 and every other variant, per channel.
    same_channel_cross_variant_correlation = []
    t1 = variant_transformed["T1"]
    for variant_name, matrix in variant_transformed.items():
        if variant_name == "T1":
            continue
        for channel_index, channel in enumerate(channels):
            a, b = t1[:, channel_index], matrix[:, channel_index]
            corr = (
                float(np.corrcoef(a, b)[0, 1])
                if np.std(a) > 0 and np.std(b) > 0
                else None
            )
            same_channel_cross_variant_correlation.append(
                {
                    "channel": channel,
                    "variant_a": "T1",
                    "variant_b": variant_name,
                    "correlation": corr,
                }
            )

    # VIF and condition number per variant's full design matrix.
    vif_and_condition = []
    for variant_name, design in variant_design.items():
        # design excludes the intercept column (see above) - the first
        # `base.shape[1] - 1` columns are the non-constant base features
        # (trend/season/context), the rest are this variant's channels.
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

    # Each transformed channel's correlation with the base (trend/season/
    # context) columns and with every other channel, T1 only (the
    # lightest/reference variant) and T6 (the heaviest), to see whether
    # heavier adstock specifically increases overlap with baseline.
    base_overlap = {}
    for variant_name in ("T1", "T6"):
        matrix = variant_transformed[variant_name]
        rows_out = []
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
                    "max_abs_correlation_with_base_columns": (
                        max(
                            (abs(c) for c in base_correlations if c is not None),
                            default=None,
                        )
                    ),
                    "max_abs_correlation_with_other_channels": (
                        max(
                            (
                                abs(c)
                                for c in other_channel_correlations.values()
                                if c is not None
                            ),
                            default=None,
                        )
                    ),
                }
            )
        base_overlap[variant_name] = rows_out

    return {
        "model_name": model_name,
        "mature_fold_id": mature_fold_id,
        "mature_fold_train_rows": rows,
        "base_feature_columns": int(base.shape[1]),
        "same_channel_cross_variant_correlation": same_channel_cross_variant_correlation,
        "vif_and_condition_number": vif_and_condition,
        "base_overlap_t1_vs_t6": base_overlap,
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
    parser.add_argument("--seed", type=int, default=20260824)
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
        only_model=args.only_model,
        governed_start=args.governed_start,
        governed_end=args.governed_end,
        prior_config={},
        frame_callback=_capture,
    )

    for model_name, (frame, _spec) in captured.items():
        result = _analyse_model(model_name, frame, transform_config=None)
        _write_json(args.output_dir / f"wp2_6_collinearity_{model_name}.json", result)
        print(f"{model_name}: wrote collinearity diagnostics to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
