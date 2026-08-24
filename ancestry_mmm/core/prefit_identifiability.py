"""Reusable pre-fit support and prior-predictive evidence.

This module is deliberately framework-independent.  It describes what the
observed model-input geometry and declared priors imply before a production
fit; it does not select channels, mutate a model specification, or approve a
fit.  The same functions are used by the application workflow and by tests
with arbitrary uploaded model-ready data.

The evidence has two separate layers:

* channel support/transform identifiability diagnostics, calculated from the
  observed target window (with any supplied pre-window rows retained for the
  adstock calculation); and
* prior-predictive plausibility diagnostics, calculated from prior predictive
  draws and optionally compared with the observed outcome scale.

Both layers carry explicit versioned policies and input fingerprints.  A
fingerprint mismatch makes evidence stale; it never silently reuses an older
diagnostic for a changed data window, channel set, or transform contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .fingerprint import fingerprint_dataframe
from .transformations import geometric_adstock_matrix


PREFIT_IDENTIFIABILITY_SCHEMA_VERSION = 1
PREFIT_IDENTIFIABILITY_VERSION = "prefit-identifiability-v1"
SUPPORT_THRESHOLD_VERSION = "support-diagnostic-v1"


@dataclass(frozen=True)
class SupportThresholdPolicy:
    """Versioned, diagnostic-only support classification thresholds."""

    version: str = SUPPORT_THRESHOLD_VERSION
    strong_positive_weeks_min: int = 60
    strong_distinct_positive_values_min: int = 20
    strong_adstock_cv_min: float = 0.25
    moderate_positive_weeks_min: int = 30
    moderate_distinct_positive_values_min: int = 10
    moderate_adstock_cv_min: float = 0.10
    weak_positive_weeks_min: int = 10
    weak_distinct_positive_values_min: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PriorPredictiveThresholdPolicy:
    """An explicitly supplied observed-scale review policy.

    No instance is used by default.  When this policy is absent, finite prior
    predictive evidence is retained as ``wide_but_reviewable`` and flagged for
    analyst review rather than applying an invented plausibility cutoff.
    """

    version: str
    lower_ratio_review: float = 0.10
    lower_ratio_extreme: float = 0.01
    upper_ratio_review: float = 10.0
    upper_ratio_extreme: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _json_fingerprint(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fingerprint_payload(value: Any) -> str:
    """Fingerprint a candidate/configuration payload without machine paths."""

    if value is None:
        return _json_fingerprint(None)
    if isinstance(value, pd.DataFrame):
        return fingerprint_dataframe(value)
    if hasattr(value, "to_dict") and not isinstance(value, (dict, list, tuple)):
        value = value.to_dict()
    if isinstance(value, np.ndarray):
        value = {"shape": list(value.shape), "values": value.tolist()}
    elif isinstance(value, Mapping):
        value = {str(key): _fingerprint_value(item) for key, item in value.items()}
    elif isinstance(value, (list, tuple)):
        value = [_fingerprint_value(item) for item in value]
    return _json_fingerprint(value)


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return {"shape": list(value.shape), "values": value.tolist()}
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _fingerprint_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(item) for item in value]
    if hasattr(value, "to_dict") and not isinstance(value, (str, bytes)):
        return _fingerprint_value(value.to_dict())
    return value


def _as_float_matrix(values: Any, *, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 2:
        raise ValueError(f"{name} must be a two-dimensional matrix")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite numeric values")
    return array


def _resolve_channel_vector(
    value: Any,
    channels: Sequence[str],
    *,
    name: str,
    default: float | None = None,
    lower: float | None = None,
    upper: float | None = None,
) -> np.ndarray | None:
    if value is None:
        if default is None:
            return None
        value = default
    if isinstance(value, Mapping):
        missing = [channel for channel in channels if channel not in value]
        if missing:
            raise ValueError(f"{name} is missing channel(s): {', '.join(missing)}")
        result = np.asarray([value[channel] for channel in channels], dtype=float)
    else:
        result = np.asarray(value, dtype=float)
        if result.ndim == 0:
            result = np.full(len(channels), float(result))
        elif result.shape != (len(channels),):
            raise ValueError(
                f"{name} must be a scalar, channel mapping, or one value per channel"
            )
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain finite values")
    if lower is not None and np.any(result <= lower):
        raise ValueError(f"{name} values must be > {lower}")
    if upper is not None and np.any(result >= upper):
        raise ValueError(f"{name} values must be < {upper}")
    return result


def _longest_zero_run(values: np.ndarray) -> int:
    longest = current = 0
    for value in values:
        if value == 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def _quantiles(values: np.ndarray) -> dict[str, float | None]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {key: None for key in ("q01", "q05", "q25", "q50", "q75", "q95", "q99")}
    quantile_values = np.quantile(finite, [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99])
    return {
        key: float(value)
        for key, value in zip(
            ("q01", "q05", "q25", "q50", "q75", "q95", "q99"),
            quantile_values,
        )
    }


def _scale_summary(values: np.ndarray) -> dict[str, float | None]:
    """Return the required observed/prior-predictive scale summary."""

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    summary = _quantiles(finite)
    if finite.size == 0:
        summary.update({"min": None, "mean": None, "max": None})
    else:
        summary.update(
            {
                "min": float(np.min(finite)),
                "mean": float(np.mean(finite)),
                "max": float(np.max(finite)),
            }
        )
    return summary


def _target_selection(
    data: pd.DataFrame,
    *,
    date_col: str | None,
    market_col: str | None,
    target_start: str | pd.Timestamp | None,
    target_end: str | pd.Timestamp | None,
) -> tuple[pd.DataFrame, pd.Series, str]:
    frame = data.copy()
    if date_col is None:
        if target_start is not None or target_end is not None:
            raise ValueError("target_start/target_end require date_col")
        frame = frame.reset_index(drop=True)
        mask = pd.Series(True, index=frame.index)
        return frame, mask, "input_rows"
    if date_col not in frame.columns:
        raise ValueError(f"date column '{date_col}' is not present")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    if dates.isna().any():
        raise ValueError("date column must contain valid dates")
    frame = frame.assign(**{date_col: dates})
    sort_columns = [date_col]
    if market_col and market_col in frame.columns:
        sort_columns = [market_col, date_col]
    frame = frame.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    start = pd.Timestamp(target_start) if target_start is not None else None
    end = pd.Timestamp(target_end) if target_end is not None else None
    if start is not None and end is not None and start > end:
        raise ValueError("target_start must be on or before target_end")
    mask = pd.Series(True, index=frame.index)
    if start is not None:
        mask &= frame[date_col] >= start
    if end is not None:
        mask &= frame[date_col] <= end
    return frame, mask, "provided_dates"


def _grouped_adstock(
    values: np.ndarray,
    frame: pd.DataFrame,
    decay_rates: np.ndarray,
    *,
    market_col: str | None,
) -> np.ndarray:
    """Apply the same carryover contract independently within each market."""

    if not market_col or market_col not in frame.columns:
        return geometric_adstock_matrix(values, decay_rates, normalize=True)
    result = np.zeros_like(values, dtype=float)
    for _, positions in frame.groupby(market_col, sort=False).groups.items():
        indices = np.asarray(list(positions), dtype=int)
        result[indices] = geometric_adstock_matrix(
            values[indices], decay_rates, normalize=True
        )
    return result


def _channel_support_status(row: Mapping[str, Any], policy: SupportThresholdPolicy) -> str:
    cv = row.get("effective_adstock_cv")
    positive_weeks = int(row["positive_weeks"])
    distinct = int(row["distinct_positive_values"])
    if (
        positive_weeks >= policy.strong_positive_weeks_min
        and distinct >= policy.strong_distinct_positive_values_min
        and cv is not None
        and float(cv) >= policy.strong_adstock_cv_min
    ):
        return "strong"
    if (
        positive_weeks >= policy.moderate_positive_weeks_min
        and distinct >= policy.moderate_distinct_positive_values_min
        and cv is not None
        and float(cv) >= policy.moderate_adstock_cv_min
    ):
        return "moderate"
    if (
        positive_weeks >= policy.weak_positive_weeks_min
        and distinct >= policy.weak_distinct_positive_values_min
    ):
        return "weak"
    return "very_weak"


def _review_recommendation(
    row: Mapping[str, Any], *, transform_complexity: str
) -> dict[str, Any]:
    reasons: list[str] = []
    actions: list[str] = []
    if int(row["target_weeks"]) == 0:
        reasons.append("no observations fall inside the requested target window")
        actions.append("resolve the governed data window or source coverage")
    elif int(row["positive_weeks"]) == 0:
        reasons.append("the channel has no positive observations in the target window")
        actions.append("review source completeness and the governed activity mapping")
    elif int(row["distinct_positive_values"]) <= 1:
        reasons.append("positive observations have only one distinct value")
        actions.append("review whether the source is genuinely constant or aggregated")
    elif row["support_status"] in {"weak", "very_weak"}:
        reasons.append("observed support is weak for the current transform complexity")
        actions.append("review transform complexity and carry-in/history evidence")
    if row.get("response_domain_adstock_over_K") is None:
        reasons.append("response-domain coverage could not be calculated")
        actions.append("confirm the current transform and K prior contract")
    if row.get("posterior_evidence", {}).get("status") == "unavailable":
        reasons.append("no posterior evidence is available at pre-fit stage")
    if not reasons:
        reasons.append("observed support is adequate for diagnostic review")
    if not actions:
        actions.append("retain the configured transform and confirm analyst review")
    blocked = int(row["target_weeks"]) == 0 or int(row["positive_weeks"]) == 0
    support_status = str(row["support_status"])
    interpretation = {
        "strong": (
            "Strong support: this channel has enough variation and active weeks "
            "for a flexible transform to be considered. This does not guarantee "
            "parameter identifiability."
        ),
        "moderate": (
            "Moderate support: the observed history may support the current "
            "transform, but analyst review is still needed before interpreting "
            "separate decay and saturation parameters."
        ),
        "weak": (
            "Weak support: this channel has limited variation or too few active "
            "weeks to confidently learn several independent adstock/saturation "
            "parameters."
        ),
        "very_weak": (
            "Very weak support: the available history is unlikely to identify a "
            "fully flexible channel-specific adstock + Hill K + Hill S "
            "specification without substantial prior information or pooling."
        ),
    }[support_status]
    return {
        "support_status": support_status,
        "review_status": "blocked" if blocked else (
            "ready" if row["support_status"] in {"strong", "moderate"} else "review_recommended"
        ),
        "interpretation": interpretation,
        "reasons": reasons,
        "current_transform_complexity": transform_complexity,
        "possible_review_actions": actions,
        "diagnostic_only": True,
    }


def compute_channel_support_diagnostics(
    data: pd.DataFrame,
    channels: Sequence[str],
    *,
    date_col: str | None = None,
    market_col: str | None = None,
    target_start: str | pd.Timestamp | None = None,
    target_end: str | pd.Timestamp | None = None,
    units: Mapping[str, Any] | None = None,
    transform_config: Mapping[str, Any] | None = None,
    posterior_evidence: Mapping[str, Any] | None = None,
    recovery_evidence: Mapping[str, Any] | None = None,
    threshold_policy: SupportThresholdPolicy | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return data-driven channel support evidence without mutating inputs.

    ``data`` may include pre-window media history.  Only rows in the governed
    target window contribute to the support counts; the full ordered series is
    used for the optional adstock diagnostic, preserving carry-in semantics.
    Missing values are rejected, never zero-filled.
    """

    channel_names = [str(channel) for channel in channels]
    if len(channel_names) != len(set(channel_names)) or not channel_names:
        raise ValueError("channels must be non-empty and unique")
    missing = [channel for channel in channel_names if channel not in data.columns]
    if missing:
        raise ValueError("media columns missing from data: " + ", ".join(missing))
    frame, target_mask, window_basis = _target_selection(
        data,
        date_col=date_col,
        market_col=market_col,
        target_start=target_start,
        target_end=target_end,
    )
    raw = _as_float_matrix(frame[channel_names].to_numpy(), name="media values")
    target = raw[np.asarray(target_mask, dtype=bool)]
    config = dict(transform_config or {})
    units = dict(units or {})
    posterior_evidence = dict(posterior_evidence or {})
    recovery_evidence = dict(recovery_evidence or {})
    if isinstance(threshold_policy, Mapping):
        policy = SupportThresholdPolicy(**dict(threshold_policy))
    else:
        policy = threshold_policy or SupportThresholdPolicy()

    # Match the production builder's backward-compatible default.  The
    # historical scaled diagnostic explicitly supplies ``positive_median``;
    # this service must not silently introduce that reparameterisation into a
    # different project.
    scale_method = str(config.get("media_input_scale_method", "none"))
    supplied_scales = config.get("media_input_scales")
    if supplied_scales:
        scales = _resolve_channel_vector(
            supplied_scales, channel_names, name="media_input_scales", lower=0.0
        )
        scale_source = "supplied_transform_contract"
    elif scale_method == "positive_median":
        positive = np.where(target > 0, target, np.nan)
        scales = np.nanmedian(positive, axis=0)
        scales = np.where(np.isfinite(scales) & (scales > 0), scales, 1.0)
        scale_source = "derived_positive_median_target_window"
    elif scale_method in {"", "none"}:
        scales = np.ones(len(channel_names), dtype=float)
        scale_source = "raw_model_input_domain"
    else:
        raise ValueError(f"unsupported media_input_scale_method '{scale_method}'")

    scaled = raw / scales
    target_scaled = target / scales
    decay_reference = _resolve_channel_vector(
        config.get("decay_rate", config.get("fixed_decay_rate")),
        channel_names,
        name="decay_rate",
        default=float(config.get("decay_mu", 0.5)),
        lower=0.0,
        upper=1.0,
    )
    if decay_reference is None:  # pragma: no cover - default resolves this
        decay_reference = np.full(len(channel_names), 0.5)
    effective = _grouped_adstock(
        scaled,
        frame,
        decay_reference,
        market_col=market_col,
    )
    target_effective = effective[np.asarray(target_mask, dtype=bool)]

    k_reference = _resolve_channel_vector(
        config.get("hill_K", config.get("fixed_hill_K")),
        channel_names,
        name="hill_K",
        lower=0.0,
    )
    if k_reference is None:
        if config.get("K_reference") == "nonzero_median":
            positive_scaled = np.where(target_scaled > 0, target_scaled, np.nan)
            k_reference = np.nanmedian(positive_scaled, axis=0)
        else:
            k_reference = np.mean(target_scaled, axis=0)
        k_reference = np.where(
            np.isfinite(k_reference) & (k_reference > 0),
            k_reference,
            1.0,
        )
        k_reference *= float(config.get("K_scale", 1.0))
    s_reference = _resolve_channel_vector(
        config.get("hill_S", config.get("fixed_hill_S")),
        channel_names,
        name="hill_S",
        default=float(config.get("S_alpha", 4.0)) / float(config.get("S_beta", 4.0)),
        lower=0.0,
    )
    transform_complexity = str(
        config.get(
            "transform_complexity",
            "geometric_adstock + Hill saturation",
        )
    )

    rows: list[dict[str, Any]] = []
    for index, channel in enumerate(channel_names):
        values = target[:, index]
        positives = values[values > 0]
        effective_values = target_effective[:, index]
        positive_iqr = (
            float(np.quantile(positives, 0.75) - np.quantile(positives, 0.25))
            if positives.size
            else None
        )
        effective_mean = float(np.mean(effective_values)) if effective_values.size else None
        effective_std = float(np.std(effective_values)) if effective_values.size else None
        effective_cv = (
            float(effective_std / effective_mean)
            if effective_mean is not None and effective_mean > 0
            else None
        )
        domain_ratio = (
            target_effective[:, index] / float(k_reference[index])
            if k_reference[index] > 0
            else np.array([])
        )
        row: dict[str, Any] = {
            "channel": channel,
            "model_input_unit": units.get(channel, "unresolved"),
            "target_weeks": int(values.size),
            "positive_weeks": int(np.sum(values > 0)),
            "positive_share": float(np.mean(values > 0)) if values.size else None,
            "zero_weeks": int(np.sum(values == 0)),
            "zero_share": float(np.mean(values == 0)) if values.size else None,
            "longest_zero_run": _longest_zero_run(values),
            "distinct_positive_values": int(np.unique(positives).size),
            "positive_median": float(np.median(positives)) if positives.size else None,
            "positive_iqr": positive_iqr,
            "positive_max": float(np.max(positives)) if positives.size else None,
            "positive_max_to_median": (
                float(np.max(positives) / np.median(positives))
                if positives.size and np.median(positives) > 0
                else None
            ),
            "effective_adstock_mean": effective_mean,
            "effective_adstock_std": effective_std,
            "effective_adstock_cv": effective_cv,
            "response_domain_K_reference": float(k_reference[index]),
            "response_domain_adstock_over_K": _quantiles(domain_ratio),
            "current_transform_priors": {
                "decay_rate": {
                    "distribution": "Beta",
                    "mu": float(config.get("decay_mu", 0.5)),
                    "sigma": float(config.get("decay_sigma", 0.2)),
                    "reference": float(decay_reference[index]),
                },
                "hill_K": {
                    "distribution": "Gamma",
                    "alpha": float(config.get("K_alpha", 3.0)),
                    "beta": float(config.get("K_alpha", 3.0))
                    / float(k_reference[index]),
                    "mean": float(k_reference[index]),
                    "reference": float(k_reference[index]),
                    "scale": float(config.get("K_scale", 1.0)),
                },
                "hill_S": {
                    "distribution": "Gamma",
                    "alpha": float(config.get("S_alpha", 4.0)),
                    "beta": float(config.get("S_beta", 4.0)),
                    "mean": float(s_reference[index]),
                    "reference": float(s_reference[index]),
                },
                "scale": {
                    "method": scale_method,
                    "source": scale_source,
                    "value": float(scales[index]),
                },
            },
            "posterior_evidence": posterior_evidence.get(
                channel, {"status": "unavailable", "diagnostic_only": True}
            ),
            "recovery_evidence": recovery_evidence.get(
                channel, {"status": "unavailable", "diagnostic_only": True}
            ),
        }
        row["support_status"] = _channel_support_status(row, policy)
        row["review_recommendation"] = _review_recommendation(
            row, transform_complexity=transform_complexity
        )
        rows.append(row)

    return {
        "schema_version": PREFIT_IDENTIFIABILITY_SCHEMA_VERSION,
        "diagnostic_version": PREFIT_IDENTIFIABILITY_VERSION,
        "target_window": {
            "start": str(pd.Timestamp(target_start).date()) if target_start is not None else None,
            "end": str(pd.Timestamp(target_end).date()) if target_end is not None else None,
            "basis": window_basis,
            "target_weeks": int(target.shape[0]),
            "history_rows_retained_for_adstock": int(raw.shape[0] - target.shape[0]),
        },
        "channels": channel_names,
        "threshold_policy": policy.to_dict(),
        "classification_is_diagnostic_only": True,
        "transform_config": {
            "media_input_scale_method": scale_method,
            "transform_complexity": transform_complexity,
            "carry_in_history_used": bool(raw.shape[0] > target.shape[0]),
        },
        "rows": rows,
    }


def _normalise_outcome_draws(
    draws: Any,
    observed: Any,
    outcome_ids: Sequence[str] | None,
) -> list[tuple[str, np.ndarray, np.ndarray | None]]:
    if isinstance(draws, Mapping):
        keys = list(draws)
        labels = [str(label) for label in keys]
        if outcome_ids is not None and list(map(str, outcome_ids)) != labels:
            raise ValueError("outcome_ids must match mapped prior-predictive labels")
        observed_mapping = observed if isinstance(observed, Mapping) else {}
        return [
            (
                label,
                np.asarray(draws[key], dtype=float),
                (
                    np.asarray(
                        observed_mapping.get(label, observed_mapping.get(key)),
                        dtype=float,
                    )
                    if label in observed_mapping or key in observed_mapping
                    else None
                ),
            )
            for key, label in zip(keys, labels)
        ]
    array = np.asarray(draws, dtype=float)
    if array.ndim == 1:
        array = array[:, None]
    if array.ndim == 2:
        array = array[:, :, None]
    if array.ndim != 3:
        raise ValueError("prior predictive draws must be draws x observations x outcomes")
    labels = [str(value) for value in (outcome_ids or [f"outcome_{i}" for i in range(array.shape[2])])]
    if len(labels) != array.shape[2]:
        raise ValueError("outcome_ids must match the prior-predictive outcome dimension")
    observed_array = None if observed is None else np.asarray(observed, dtype=float)
    if observed_array is not None:
        if observed_array.ndim == 1:
            observed_array = observed_array[:, None]
        if observed_array.ndim != 2 or observed_array.shape[1] != array.shape[2]:
            raise ValueError("observed values must be observations x outcomes")
    return [
        (
            labels[index],
            array[:, :, index],
            None if observed_array is None else observed_array[:, index],
        )
        for index in range(array.shape[2])
    ]


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or not np.isfinite(denominator) or denominator == 0:
        return None
    return float(numerator / denominator)


def _component_summary(components: Mapping[str, Any] | None) -> dict[str, Any]:
    if not components:
        return {
            "status": "unavailable",
            "reason": "component draws were not supplied",
            "diagnostic_only": True,
        }
    result: dict[str, Any] = {
        "status": "available",
        "components": {},
        "diagnostic_only": True,
    }
    for name, values in components.items():
        array = np.asarray(values, dtype=float)
        finite = array[np.isfinite(array)]
        result["components"][str(name)] = {
            "finite": bool(finite.size == array.size),
            "n_values": int(array.size),
            "q05": float(np.quantile(finite, 0.05)) if finite.size else None,
            "median": float(np.median(finite)) if finite.size else None,
            "q95": float(np.quantile(finite, 0.95)) if finite.size else None,
        }
    return result


def prior_predictive_plausibility(
    draws: Any,
    observed: Any = None,
    *,
    outcome_ids: Sequence[str] | None = None,
    threshold_policy: PriorPredictiveThresholdPolicy | Mapping[str, Any] | None = None,
    component_draws: Mapping[str, Any] | None = None,
    validity_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare prior-predictive draws with observed outcome scale.

    Layer A is finite/non-finite checking.  Layer B is descriptive observed-
    scale comparison.  A threshold policy is optional and must be supplied by
    the caller; without one, finite evidence remains reviewable but is not
    treated as policy-plausible.
    """

    if isinstance(threshold_policy, Mapping):
        policy = PriorPredictiveThresholdPolicy(**dict(threshold_policy))
    else:
        policy = threshold_policy
    rows: list[dict[str, Any]] = []
    validity_evidence = dict(validity_evidence or {})
    invalid_likelihood_values = validity_evidence.get(
        "invalid_likelihood_values", "not_supplied"
    )
    any_nonfinite = False
    for label, raw_draws, raw_observed in _normalise_outcome_draws(
        draws, observed, outcome_ids
    ):
        draw_array = np.asarray(raw_draws, dtype=float)
        finite = draw_array[np.isfinite(draw_array)]
        finite_ok = bool(finite.size == draw_array.size and finite.size > 0)
        any_nonfinite = any_nonfinite or not finite_ok
        predictive = _scale_summary(finite)
        observed_summary = None
        ratios: dict[str, float | None] = {}
        if raw_observed is not None:
            observed_values = np.asarray(raw_observed, dtype=float)
            observed_finite = observed_values[np.isfinite(observed_values)]
            if observed_finite.size:
                observed_summary = _scale_summary(observed_finite)
                ratios = {
                    "q01_to_observed_q05": _ratio(predictive["q01"], observed_summary["q05"]),
                    "q05_to_observed_q05": _ratio(predictive["q05"], observed_summary["q05"]),
                    "median_to_observed_median": _ratio(
                        predictive["q50"], observed_summary["q50"]
                    ),
                    "q95_to_observed_q95": _ratio(predictive["q95"], observed_summary["q95"]),
                    "q99_to_observed_q95": _ratio(predictive["q99"], observed_summary["q95"]),
                    "q95_to_observed_median": _ratio(
                        predictive["q95"], observed_summary["q50"]
                    ),
                    "q99_to_observed_max": _ratio(
                        predictive["q99"], observed_summary["max"]
                    ),
                    "max_to_observed_max": _ratio(
                        predictive["max"], observed_summary["max"]
                    ),
                }
        if not finite_ok or invalid_likelihood_values is True:
            status = "numerically_invalid"
            review_status = "blocked"
            reason = (
                "prior-predictive draws contain no finite values or contain non-finite values"
                if not finite_ok
                else "invalid likelihood values were reported by the sampler"
            )
        elif policy is None or observed_summary is None:
            status = "wide_but_reviewable"
            review_status = "review_recommended"
            reason = (
                "no approved observed-scale threshold policy was supplied"
                if policy is None
                else "observed outcome values were not supplied for scale comparison"
            )
        else:
            lower = ratios.get("q01_to_observed_q05")
            upper = ratios.get("q99_to_observed_q95")
            if lower is None or upper is None:
                status = "wide_but_reviewable"
                review_status = "review_recommended"
                reason = "observed comparison denominator is zero or unavailable"
            elif lower < policy.lower_ratio_extreme or upper > policy.upper_ratio_extreme:
                status = "implausibly_extreme"
                review_status = "review_recommended"
                reason = "prior-predictive tails are extreme relative to the observed outcome scale"
            elif lower < policy.lower_ratio_review or upper > policy.upper_ratio_review:
                status = "wide_but_reviewable"
                review_status = "review_recommended"
                reason = "prior-predictive tails are wide relative to the observed outcome scale"
            else:
                status = "plausible"
                review_status = "ready"
                reason = "prior-predictive tails are within the supplied review policy"
        rows.append(
            {
                "outcome_id": label,
                "finite": finite_ok,
                "n_draw_values": int(draw_array.size),
                "non_finite_count": int(draw_array.size - finite.size),
                "predictive_quantiles": predictive,
                "observed_quantiles": observed_summary,
                "observed_scale_ratios": ratios,
                "status": status,
                "review_status": review_status,
                "reason": reason,
            }
        )
    return {
        "schema_version": PREFIT_IDENTIFIABILITY_SCHEMA_VERSION,
        "diagnostic_version": PREFIT_IDENTIFIABILITY_VERSION,
        "layer_a": "finite_nonfinite",
        "layer_b": "observed_scale_comparison",
        "threshold_policy": policy.to_dict() if policy is not None else None,
        "threshold_policy_status": "supplied" if policy is not None else "not_approved",
        "status": (
            "numerically_invalid"
            if any_nonfinite or invalid_likelihood_values is True
            else "computed"
        ),
        "review_status": (
            "blocked"
            if any_nonfinite or invalid_likelihood_values is True
            else "review_recommended"
        ),
        "layer_a_evidence": {
            "all_draws_finite": not any_nonfinite,
            "invalid_likelihood_values": invalid_likelihood_values,
            "warnings": list(validity_evidence.get("warnings") or []),
        },
        "component_decomposition": _component_summary(component_draws),
        "rows": rows,
        "diagnostic_only": True,
    }


def build_prefit_fingerprints(
    data: pd.DataFrame,
    *,
    channels: Sequence[str],
    date_col: str | None,
    market_col: str | None,
    target_start: str | pd.Timestamp | None,
    target_end: str | pd.Timestamp | None,
    transform_config: Mapping[str, Any] | None,
    candidate_spec: Any = None,
    prepared_frame: Any = None,
    causal_graph: Any = None,
) -> dict[str, str]:
    """Return the four fingerprints required to judge evidence freshness."""

    channel_set = {
        "channels": [str(channel) for channel in channels],
        "market_col": market_col,
    }
    window = {
        "date_col": date_col,
        "market_col": market_col,
        "target_start": str(pd.Timestamp(target_start)) if target_start is not None else None,
        "target_end": str(pd.Timestamp(target_end)) if target_end is not None else None,
    }
    result = {
        "data_fingerprint": fingerprint_dataframe(data),
        "model_window_fingerprint": _json_fingerprint(window),
        "channel_set_fingerprint": _json_fingerprint(channel_set),
        "transform_config_fingerprint": _json_fingerprint(transform_config or {}),
    }
    # The official pre-fit contract binds all three identity objects even
    # when one is currently unavailable.  Hashing ``None`` makes absence
    # explicit and ensures that later availability/change marks evidence
    # stale instead of silently weakening the contract.
    result["candidate_spec_fingerprint"] = _fingerprint_payload(candidate_spec)
    result["prepared_frame_fingerprint"] = _fingerprint_payload(prepared_frame)
    result["causal_graph_fingerprint"] = _fingerprint_payload(causal_graph)
    return result


def prefit_diagnostic_freshness(
    report: Mapping[str, Any], current_fingerprints: Mapping[str, str]
) -> dict[str, Any]:
    """Compare persisted evidence with current input fingerprints."""

    recorded = dict(report.get("fingerprints") or {})
    keys = set(recorded) | set(current_fingerprints)
    mismatches = {
        key: {"recorded": recorded.get(key), "current": current_fingerprints.get(key)}
        for key in sorted(keys)
        if recorded.get(key) != current_fingerprints.get(key)
    }
    return {
        "status": "stale" if mismatches else "current",
        "stale": bool(mismatches),
        "mismatches": mismatches,
    }


def classify_short_sampler_screen(
    *,
    divergences: int,
    rhat_max: float | None,
    ess_min: float | None,
    bfmi_min: float | None,
    chains: int,
    tune: int,
    draws: int,
) -> dict[str, Any]:
    """State semantics for a bounded sampler smoke screen.

    A short screen can establish whether the run immediately produced
    divergences, but it cannot establish production convergence.  This helper
    makes that distinction explicit so a zero-divergence smoke test is not
    reported as a converged candidate and a short screen with poor mixing is
    not described as a statistical model failure.
    """

    divergence_count = int(divergences)
    smoke = "passed" if divergence_count == 0 else "failed"
    return {
        "screen_type": "short_sampler_screen",
        "divergence_smoke_test": smoke,
        "divergences": divergence_count,
        "mixing_status": "inconclusive",
        "mixing_metrics": {
            "rhat_max": rhat_max,
            "ess_min": ess_min,
            "bfmi_min": bfmi_min,
        },
        "chains": int(chains),
        "tune": int(tune),
        "draws": int(draws),
        "production_convergence_assessed": False,
        "production_candidate": False,
        "diagnostic_only": True,
        "interpretation": (
            "divergence smoke-test passed; mixing is inconclusive on this short screen; "
            "production convergence was not assessed"
            if smoke == "passed"
            else "divergence smoke-test failed; production convergence was not assessed"
        ),
    }


def build_prefit_identifiability_report(
    data: pd.DataFrame,
    channels: Sequence[str],
    *,
    product: str,
    model_name: str,
    date_col: str | None = None,
    market_col: str | None = None,
    target_start: str | pd.Timestamp | None = None,
    target_end: str | pd.Timestamp | None = None,
    units: Mapping[str, Any] | None = None,
    transform_config: Mapping[str, Any] | None = None,
    posterior_evidence: Mapping[str, Any] | None = None,
    recovery_evidence: Mapping[str, Any] | None = None,
    prior_predictive: Mapping[str, Any] | None = None,
    support_threshold_policy: SupportThresholdPolicy | Mapping[str, Any] | None = None,
    prior_predictive_threshold_policy: PriorPredictiveThresholdPolicy
    | Mapping[str, Any]
    | None = None,
    candidate_spec: Any = None,
    prepared_frame: Any = None,
    causal_graph: Any = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the complete persisted pre-fit evidence object."""

    support = compute_channel_support_diagnostics(
        data,
        channels,
        date_col=date_col,
        market_col=market_col,
        target_start=target_start,
        target_end=target_end,
        units=units,
        transform_config=transform_config,
        posterior_evidence=posterior_evidence,
        recovery_evidence=recovery_evidence,
        threshold_policy=support_threshold_policy,
    )
    fingerprints = build_prefit_fingerprints(
        data,
        channels=channels,
        date_col=date_col,
        market_col=market_col,
        target_start=target_start,
        target_end=target_end,
        transform_config=transform_config,
        candidate_spec=candidate_spec,
        prepared_frame=prepared_frame,
        causal_graph=causal_graph,
    )
    support_statuses = [
        row["review_recommendation"]["review_status"]
        for row in support["rows"]
    ]
    support_state = (
        "blocked"
        if "blocked" in support_statuses
        else (
            "review_recommended"
            if "review_recommended" in support_statuses
            else "ready"
        )
    )
    prior_state = "not_run"
    if prior_predictive is not None:
        prior_state = str(
            prior_predictive.get("review_status")
            or prior_predictive.get("status")
            or "review_recommended"
        )
    return {
        "schema_version": PREFIT_IDENTIFIABILITY_SCHEMA_VERSION,
        "diagnostic_version": PREFIT_IDENTIFIABILITY_VERSION,
        "status": support_state,
        "review_status": support_state,
        "generated_at": generated_at or pd.Timestamp.now(tz="UTC").isoformat(),
        "product": str(product),
        "model_name": str(model_name),
        "state_semantics": {
            "static_readiness": "computed",
            "support_identifiability": support_state,
            "prior_predictive": prior_state,
            "short_sampler_screen": "not_run",
            "production_convergence": "not_assessed",
            "postfit_validation": "not_run",
            "reporting_eligibility": "not_eligible",
        },
        "fingerprints": fingerprints,
        "support_identifiability": support,
        "prior_predictive": prior_predictive
        or {
            "status": "not_run",
            "review_status": "not_run",
            "diagnostic_only": True,
        },
        "prior_predictive_threshold_policy": (
            PriorPredictiveThresholdPolicy(**dict(prior_predictive_threshold_policy)).to_dict()
            if isinstance(prior_predictive_threshold_policy, Mapping)
            else (
                prior_predictive_threshold_policy.to_dict()
                if prior_predictive_threshold_policy is not None
                else None
            )
        ),
        "diagnostic_only": True,
        "channel_selection_rule": False,
        "model_mutation_applied": False,
    }
