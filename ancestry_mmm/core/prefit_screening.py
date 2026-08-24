"""Deterministic, leakage-safe pre-fit surrogate screens.

This module is intentionally separate from the Bayesian Model A builder.  It
uses time-respecting folds and regularised linear surrogates to expose obvious
geometry, timing, residual, feature, and transform instability before a
production sampler is launched.  It never selects channels, changes priors,
or certifies a posterior.
"""

from __future__ import annotations

import time
from collections import defaultdict
from copy import deepcopy
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PREFIT_SCREENING_SCHEMA_VERSION = 1
PREFIT_SCREENING_VERSION = "prefit-screening-v1"
PREFIT_SCREEN_GRID_VERSION = "bounded-adstock-hill-grid-v1"


def _matrix(
    frame: Mapping[str, Any], key: str, rows: int, columns: int = 0
) -> np.ndarray:
    value = frame.get(key)
    if value is None:
        return np.zeros((rows, columns), dtype=float)
    result = np.asarray(value, dtype=float)
    if result.ndim == 1:
        result = result[:, None]
    if result.ndim != 2 or result.shape[0] != rows:
        raise ValueError(
            f"frame['{key}'] must be a two-dimensional matrix with {rows} rows"
        )
    if not np.isfinite(result).all():
        raise ValueError(f"frame['{key}'] must contain finite values")
    return result


def build_leakage_safe_folds(
    dates: Sequence[Any], *, n_folds: int = 3, min_train_periods: int = 8
) -> list[dict[str, Any]]:
    """Build expanding date folds without using future rows in training."""

    if n_folds < 1:
        raise ValueError("n_folds must be at least one")
    date_values = pd.to_datetime(pd.Series(list(dates)), errors="coerce")
    if date_values.isna().any():
        raise ValueError("dates must be valid and finite")
    unique_dates = pd.DatetimeIndex(sorted(date_values.unique()))
    if len(unique_dates) <= min_train_periods:
        return []
    test_periods = max(1, (len(unique_dates) - min_train_periods) // n_folds)
    folds: list[dict[str, Any]] = []
    for index in range(n_folds):
        train_end_position = min_train_periods + index * test_periods
        test_end_position = min(len(unique_dates), train_end_position + test_periods)
        if test_end_position <= train_end_position:
            continue
        train_end = unique_dates[train_end_position - 1]
        test_start = unique_dates[train_end_position]
        test_end = unique_dates[test_end_position - 1]
        train_mask = date_values <= train_end
        test_mask = (date_values >= test_start) & (date_values <= test_end)
        if not bool(train_mask.any()) or not bool(test_mask.any()):
            continue
        folds.append(
            {
                "fold_id": f"prefit-fold-{index + 1}",
                "train_start": str(unique_dates[0].date()),
                "train_end": str(train_end.date()),
                "test_start": str(test_start.date()),
                "test_end": str(test_end.date()),
                "train_rows": int(train_mask.sum()),
                "test_rows": int(test_mask.sum()),
                "leakage_safe": True,
                "train_mask": train_mask.to_numpy(),
                "test_mask": test_mask.to_numpy(),
            }
        )
    return folds


def _group_positions(markets: Sequence[Any] | None, rows: int) -> list[np.ndarray]:
    if markets is None:
        return [np.arange(rows, dtype=int)]
    values = np.asarray(markets)
    if values.shape != (rows,):
        raise ValueError("frame['markets'] must have one value per row")
    groups: dict[str, list[int]] = {}
    for position, market in enumerate(values):
        groups.setdefault(str(market), []).append(position)
    return [np.asarray(positions, dtype=int) for positions in groups.values()]


def _grouped_adstock(
    values: np.ndarray, markets: Sequence[Any] | None, decay: float
) -> np.ndarray:
    result = np.zeros_like(values, dtype=float)
    for positions in _group_positions(markets, values.shape[0]):
        previous = np.zeros(values.shape[1], dtype=float)
        for position in positions:
            previous = values[position] + decay * previous
            result[position] = previous * (1.0 - decay)
    return result


def _shift_by_market(values: np.ndarray, markets: Sequence[Any] | None) -> np.ndarray:
    result = np.zeros_like(values, dtype=float)
    for positions in _group_positions(markets, values.shape[0]):
        if len(positions) > 1:
            result[positions[:-1]] = values[positions[1:]]
    return result


def _media_transform(
    media: np.ndarray,
    markets: Sequence[Any] | None,
    train_mask: np.ndarray,
    *,
    decay: float,
    hill_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    adstocked = _grouped_adstock(media, markets, decay)
    positive = np.where(train_mask[:, None] & (adstocked > 0), adstocked, np.nan)
    k = np.nanmedian(positive, axis=0)
    k = np.where(np.isfinite(k) & (k > 0), k, 1.0)
    ratio = np.maximum(adstocked / k, 0.0)
    transformed = ratio**hill_s / (1.0 + ratio**hill_s)
    return transformed, k


def _base_features(frame: Mapping[str, Any], rows: int) -> np.ndarray:
    pieces = [np.ones((rows, 1), dtype=float)]
    for key in ("trend", "fourier", "X_controls"):
        value = frame.get(key)
        if value is not None:
            matrix = _matrix(frame, key, rows)
            if matrix.shape[1]:
                pieces.append(matrix)
    return np.column_stack(pieces)


def _fit_surrogate(kind: str, alpha: float, l1_ratio: float):
    if kind == "ridge":
        estimator = Ridge(alpha=alpha)
    elif kind == "elastic_net":
        estimator = ElasticNet(alpha=alpha, l1_ratio=l1_ratio, max_iter=5000)
    else:
        raise ValueError(f"unsupported surrogate kind: {kind}")
    return make_pipeline(StandardScaler(), estimator)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    residuals = actual - predicted
    rmse = float(np.sqrt(np.mean(residuals**2))) if len(actual) else None
    mae = float(np.mean(np.abs(residuals))) if len(actual) else None
    total = float(np.sum((actual - np.mean(actual)) ** 2)) if len(actual) > 1 else 0.0
    r2 = float(1.0 - np.sum(residuals**2) / total) if total > 0 else None
    if len(residuals) < 2 or np.std(residuals[:-1]) == 0 or np.std(residuals[1:]) == 0:
        lag1 = None
    else:
        lag1 = float(np.corrcoef(residuals[:-1], residuals[1:])[0, 1])
    denominator = float(np.sum(residuals**2))
    durbin_watson = (
        float(np.sum(np.diff(residuals) ** 2) / denominator)
        if denominator > 0
        else None
    )
    return {
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "lag1_residual_autocorrelation": lag1,
        "durbin_watson": durbin_watson,
    }


def _screen_grid(transform_config: Mapping[str, Any] | None) -> list[dict[str, float]]:
    config = dict(transform_config or {})
    decays = config.get("prefit_decay_grid", (0.0, 0.5, 0.8))
    hill_shapes = config.get("prefit_hill_s_grid", (1.0, 2.0))
    grid = []
    for decay in decays:
        for hill_s in hill_shapes:
            decay_value = float(decay)
            hill_value = float(hill_s)
            if not 0 <= decay_value < 1 or hill_value <= 0:
                raise ValueError("prefit transform grid has invalid decay or Hill S")
            grid.append({"decay": decay_value, "hill_s": hill_value})
    if not grid:
        raise ValueError("prefit transform grid must not be empty")
    return grid


def record_prefit_analyst_review(
    report: Mapping[str, Any], rationale: str
) -> dict[str, Any]:
    """Retain an analyst rationale without turning evidence into approval."""

    text = str(rationale or "").strip()
    if not text:
        raise ValueError("an analyst rationale is required before saving review")
    result = deepcopy(dict(report))
    analyst_review = dict(result.get("analyst_review") or {})
    analyst_review.update(
        {
            "status": "retained",
            "rationale": text,
            "rationale_retained": True,
        }
    )
    result["analyst_review"] = analyst_review
    result["submission_gate"] = (
        "blocked" if result.get("status") == "blocked" else "review_rationale_retained"
    )
    # The screen remains preparation evidence only, even after review.
    result["official_eligibility"] = False
    result["diagnostic_only"] = True
    return result


def build_prefit_screening_report(
    frame: Mapping[str, Any],
    *,
    transform_config: Mapping[str, Any] | None = None,
    n_folds: int = 3,
    min_train_periods: int = 8,
    ridge_alpha: float = 1.0,
    elastic_net_alpha: float = 0.05,
    elastic_net_l1_ratio: float = 0.5,
    fingerprints: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run deterministic baseline/media surrogate evidence on a model frame."""

    started = time.perf_counter()
    media = np.asarray(frame.get("X_media"), dtype=float)
    outcomes = np.asarray(frame.get("Y"), dtype=float)
    if media.ndim != 2 or outcomes.ndim != 2 or media.shape[0] != outcomes.shape[0]:
        raise ValueError("frame must contain compatible two-dimensional X_media and Y")
    if not np.isfinite(media).all() or not np.isfinite(outcomes).all():
        raise ValueError("X_media and Y must contain finite values")
    if np.any(outcomes < 0):
        raise ValueError("surrogate screen requires non-negative count outcomes")
    rows, channels = media.shape
    outcome_ids = [
        str(value) for value in frame.get("outcome_ids", range(outcomes.shape[1]))
    ]
    channel_ids = [str(value) for value in frame.get("channels", range(channels))]
    if len(channel_ids) != channels or len(outcome_ids) != outcomes.shape[1]:
        raise ValueError("frame channel/outcome labels must match matrix dimensions")
    dates = frame.get("dates", np.arange(rows))
    folds = build_leakage_safe_folds(
        dates,
        n_folds=n_folds,
        min_train_periods=min_train_periods,
    )
    if not folds:
        return {
            "schema_version": PREFIT_SCREENING_SCHEMA_VERSION,
            "diagnostic_version": PREFIT_SCREENING_VERSION,
            "status": "blocked",
            "review_status": "blocked",
            "reason": "insufficient ordered history for a leakage-safe expanding fold",
            "folds": [],
            "diagnostic_only": True,
            "official_eligibility": False,
            "same_sample_prior_safeguards": {
                "status": "not_run",
                "transform_fit_on_training_rows_only": True,
            },
            "analyst_review": {
                "status": "not_available",
                "rationale": None,
                "rationale_retained": False,
            },
            "submission_gate": "blocked",
        }

    markets = frame.get("markets")
    base = _base_features(frame, rows)
    grid = _screen_grid(transform_config)
    surrogate_kinds = ("ridge", "elastic_net")
    result_rows: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []
    timing_rows: list[dict[str, Any]] = []
    baseline_cache: dict[tuple[str, str, str], dict[str, float | None]] = {}
    for fold in folds:
        train_mask = fold["train_mask"]
        test_mask = fold["test_mask"]
        for outcome_index, outcome_id in enumerate(outcome_ids):
            target = np.log1p(outcomes[:, outcome_index])
            for kind in surrogate_kinds:
                baseline_model = _fit_surrogate(
                    kind,
                    ridge_alpha if kind == "ridge" else elastic_net_alpha,
                    elastic_net_l1_ratio,
                )
                baseline_model.fit(base[train_mask], target[train_mask])
                baseline_metrics = _metrics(
                    target[test_mask], baseline_model.predict(base[test_mask])
                )
                baseline_cache[(fold["fold_id"], outcome_id, kind)] = baseline_metrics
            for variant_index, variant in enumerate(grid):
                transformed, k_reference = _media_transform(
                    media,
                    markets,
                    train_mask,
                    decay=variant["decay"],
                    hill_s=variant["hill_s"],
                )
                full_features = np.column_stack([base, transformed])
                for kind in surrogate_kinds:
                    full_model = _fit_surrogate(
                        kind,
                        ridge_alpha if kind == "ridge" else elastic_net_alpha,
                        elastic_net_l1_ratio,
                    )
                    full_model.fit(full_features[train_mask], target[train_mask])
                    full_metrics = _metrics(
                        target[test_mask], full_model.predict(full_features[test_mask])
                    )
                    baseline_metrics = baseline_cache[
                        (fold["fold_id"], outcome_id, kind)
                    ]
                    result_rows.append(
                        {
                            "fold_id": fold["fold_id"],
                            "outcome_id": outcome_id,
                            "surrogate": kind,
                            "transform_variant": f"T{variant_index + 1}",
                            "decay": variant["decay"],
                            "hill_s": variant["hill_s"],
                            "k_reference": k_reference.tolist(),
                            "baseline_context_only": baseline_metrics,
                            "baseline_context_plus_media": full_metrics,
                            "media_delta_r2": (
                                full_metrics["r2"] - baseline_metrics["r2"]
                                if full_metrics["r2"] is not None
                                and baseline_metrics["r2"] is not None
                                else None
                            ),
                        }
                    )
                    coefficients = np.asarray(
                        full_model[-1].coef_, dtype=float
                    ).reshape(-1)
                    for channel_index, channel in enumerate(channel_ids):
                        coefficient_rows.append(
                            {
                                "fold_id": fold["fold_id"],
                                "outcome_id": outcome_id,
                                "surrogate": kind,
                                "transform_variant": f"T{variant_index + 1}",
                                "channel": channel,
                                "absolute_coefficient": float(
                                    abs(coefficients[base.shape[1] + channel_index])
                                ),
                            }
                        )
                # Timing refutation is deliberately diagnostic and uses the
                # same fold-local transform reference, but shifts media from
                # the future into the current row.
                future_features = np.column_stack(
                    [base, _shift_by_market(transformed, markets)]
                )
                timing_model = _fit_surrogate(
                    "ridge", ridge_alpha, elastic_net_l1_ratio
                )
                timing_model.fit(future_features[train_mask], target[train_mask])
                timing_metrics = _metrics(
                    target[test_mask], timing_model.predict(future_features[test_mask])
                )
                timing_rows.append(
                    {
                        "fold_id": fold["fold_id"],
                        "outcome_id": outcome_id,
                        "transform_variant": f"T{variant_index + 1}",
                        "future_media_r2": timing_metrics["r2"],
                        "future_media_rmse": timing_metrics["rmse"],
                        "interpretation": "refutation diagnostic only; future media is not a production predictor",
                    }
                )

    stability_accumulator: dict[str, list[float]] = defaultdict(list)
    for row in coefficient_rows:
        stability_accumulator[row["channel"]].append(row["absolute_coefficient"])
    channel_stability = [
        {
            "channel": channel,
            "records": len(values),
            "nonzero_share": float(np.mean(np.asarray(values) > 1e-8)),
            "mean_absolute_coefficient": float(np.mean(values)),
            "coefficient_cv": (
                float(np.std(values) / np.mean(values)) if np.mean(values) > 0 else None
            ),
            "diagnostic_only": True,
        }
        for channel, values in stability_accumulator.items()
    ]
    transform_summary: dict[str, list[float]] = defaultdict(list)
    for row in result_rows:
        metrics = row["baseline_context_plus_media"]
        if metrics["rmse"] is not None:
            transform_summary[row["transform_variant"]].append(float(metrics["rmse"]))
    transform_stability = [
        {
            "transform_variant": variant,
            "records": len(values),
            "mean_test_rmse": float(np.mean(values)),
            "test_rmse_cv": (
                float(np.std(values) / np.mean(values)) if np.mean(values) > 0 else None
            ),
            "diagnostic_only": True,
        }
        for variant, values in transform_summary.items()
    ]
    return {
        "schema_version": PREFIT_SCREENING_SCHEMA_VERSION,
        "diagnostic_version": PREFIT_SCREENING_VERSION,
        "screen_grid_version": PREFIT_SCREEN_GRID_VERSION,
        "status": "computed",
        "review_status": "review_recommended",
        "reason": "deterministic surrogate evidence requires analyst review; it is not a posterior or production approval",
        "folds": [
            {
                key: value
                for key, value in fold.items()
                if key not in {"train_mask", "test_mask"}
            }
            for fold in folds
        ],
        "surrogate_results": result_rows,
        "channel_stability": channel_stability,
        "transform_stability": transform_stability,
        "timing_refutation": {
            "status": "computed",
            "rows": timing_rows,
            "future_to_past_is_not_a_production_predictor": True,
        },
        "residual_autocorrelation": [
            {
                "fold_id": row["fold_id"],
                "outcome_id": row["outcome_id"],
                "surrogate": row["surrogate"],
                "transform_variant": row["transform_variant"],
                **row["baseline_context_plus_media"],
            }
            for row in result_rows
        ],
        "same_sample_prior_safeguards": {
            "status": "passed",
            "transform_fit_on_training_rows_only": True,
            "feature_scaler_fit_on_training_rows_only": True,
            "outcome_not_used_to_set_media_transform": True,
            "prior_not_tightened_or_mutated": True,
        },
        "analyst_review": {
            "status": "required",
            "rationale": None,
            "rationale_retained": False,
        },
        "submission_gate": "blocked_pending_analyst_rationale",
        "fingerprints": dict(fingerprints or {}),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "diagnostic_only": True,
        "official_eligibility": False,
        "model_mutation_applied": False,
    }
