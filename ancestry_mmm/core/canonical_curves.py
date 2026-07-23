"""Canonical posterior response-curve and economics dataset (G2A).

The draw table is the source of truth.  Every summary and aggregate is
computed from draw rows; independently summarised medians are never added.
The engine deliberately has no Streamlit dependency so Results, planning,
year-on-year reporting, the curve bank, and exports can share one contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import arviz as az
import numpy as np
import pandas as pd

from .hierarchical_model import FHModelMeta
from .market_specific_predict import extract_market_specific_posterior_params
from .predict import extract_posterior_params
from .transformations import hill_function
from .uncertainty import DEFAULT_CRED_MASS, DEFAULT_N_DRAWS, sample_draw_indices

ECONOMICS_OK = "ok"
ECONOMICS_ZERO_SPEND = "zero_spend"
ECONOMICS_ZERO_RESPONSE = "zero_or_invalid_response"
ECONOMICS_NEAR_ZERO_MARGINAL = "zero_or_near_zero_marginal_response"
ECONOMICS_MISSING_VALUE = "missing_value"
ECONOMICS_UNIT_ERROR = "unit_error"
ECONOMICS_CURRENCY_ERROR = "currency_error"

SUPPORTED_SPEND_UNITS = {"currency", "currency_thousands"}
DEFAULT_NEAR_ZERO = 1e-12

IDENTITY_COLUMNS = [
    "model_run_id",
    "market",
    "product",
    "segment",
    "outcome_id",
    "metric_key",
    "channel",
    "component_type",
    "pathway_role",
    "spend_point",
]


def _normalise_support(
    meta: FHModelMeta,
    params,
    model_type: str,
    support_by_market_channel: Optional[
        Mapping[Tuple[str, str], Mapping[str, float]]
    ],
) -> Dict[Tuple[str, str], Dict[str, float]]:
    result = {}
    supplied = support_by_market_channel or {}
    for market in meta.markets:
        for channel in meta.channels:
            K = (
                params.hill_K[market][channel]
                if model_type == "market_specific"
                else params.hill_K[channel]
            )
            values = dict(supplied.get((market, channel), {}))
            observed_min = float(values.get("observed_spend_min", 0.0))
            observed_max = float(values.get("observed_spend_max", max(K, 0.0)))
            planning_min = float(
                values.get("planning_spend_min", observed_min)
            )
            planning_max = float(
                values.get("planning_spend_max", max(observed_max, K * 3.0, 1.0))
            )
            current = float(values.get("current_spend", observed_max))
            if not (
                0 <= observed_min <= observed_max
                and 0 <= planning_min <= planning_max
            ):
                raise ValueError(
                    f"Invalid spend support for {market}/{channel}: {values}"
                )
            result[(market, channel)] = {
                "current_spend": current,
                "observed_spend_min": observed_min,
                "observed_spend_max": observed_max,
                "planning_spend_min": planning_min,
                "planning_spend_max": planning_max,
            }
    return result


def support_from_model_frame(
    frame: Mapping[str, object], meta: FHModelMeta
) -> Dict[Tuple[str, str], Dict[str, float]]:
    """Derive observed/current weekly support from a prepared model frame."""
    media = np.asarray(frame["X_media"], dtype=float)
    market_idx = np.asarray(frame.get("market_idx", np.zeros(len(media))), dtype=int)
    result = {}
    for market_pos, market in enumerate(meta.markets):
        rows = media[market_idx == market_pos]
        if not len(rows):
            continue
        for channel_pos, channel in enumerate(meta.channels):
            values = rows[:, channel_pos]
            result[(market, channel)] = {
                "current_spend": float(values[-1]),
                "observed_spend_min": float(np.nanmin(values)),
                "observed_spend_max": float(np.nanmax(values)),
            }
    return result


def _hill_derivative(spend: float, K: float, S: float) -> float:
    if spend < 0 or K <= 0 or S <= 0:
        return float("nan")
    if spend == 0:
        if S > 1:
            return 0.0
        if np.isclose(S, 1.0):
            return 1.0 / K
        return float("nan")
    numerator = S * (K**S) * (spend ** (S - 1.0))
    denominator = (spend**S + K**S) ** 2
    return float(numerator / denominator)


def _economic_values(
    *,
    spend: float,
    response: float,
    marginal_response: float,
    value_per_response: Optional[float],
    units_valid: bool,
    currency_valid: bool,
    near_zero: float,
) -> dict:
    status = ECONOMICS_OK
    if not units_valid:
        status = ECONOMICS_UNIT_ERROR
    elif not currency_valid:
        status = ECONOMICS_CURRENCY_ERROR
    elif spend == 0:
        status = ECONOMICS_ZERO_SPEND
    elif not np.isfinite(response) or response <= 0:
        status = ECONOMICS_ZERO_RESPONSE
    average_cpa = (
        spend / response
        if status == ECONOMICS_OK
        else float("nan")
    )
    marginal_ok = (
        units_valid
        and currency_valid
        and np.isfinite(marginal_response)
        and marginal_response > near_zero
    )
    marginal_cpa = (
        1.0 / marginal_response if marginal_ok else float("nan")
    )
    marginal_status = (
        ECONOMICS_OK if marginal_ok else ECONOMICS_NEAR_ZERO_MARGINAL
    )
    if not units_valid:
        marginal_status = ECONOMICS_UNIT_ERROR
    elif not currency_valid:
        marginal_status = ECONOMICS_CURRENCY_ERROR
    value_ok = value_per_response is not None and np.isfinite(value_per_response)
    average_roi = (
        response * float(value_per_response) / spend
        if status == ECONOMICS_OK and value_ok
        else float("nan")
    )
    marginal_roi = (
        marginal_response * float(value_per_response)
        if marginal_ok and value_ok
        else float("nan")
    )
    roi_status = (
        ECONOMICS_OK
        if value_ok and status == ECONOMICS_OK
        else ECONOMICS_MISSING_VALUE
        if not value_ok
        else status
    )
    return {
        "average_cpa": average_cpa,
        "marginal_cpa": marginal_cpa,
        "average_roi": average_roi,
        "marginal_roi": marginal_roi,
        "average_economics_status": status,
        "marginal_economics_status": marginal_status,
        "roi_status": roi_status,
    }


def generate_canonical_curve_draws(
    *,
    model_run_id: str,
    meta: FHModelMeta,
    trace: az.InferenceData,
    model_type: str = "shared",
    n_draws: int = DEFAULT_N_DRAWS,
    seed: int = 42,
    spend_points: Optional[Sequence[float]] = None,
    support_by_market_channel: Optional[
        Mapping[Tuple[str, str], Mapping[str, float]]
    ] = None,
    spend_unit: str = "currency",
    spend_unit_scale: float = 1.0,
    currency_by_market: Optional[Mapping[str, str]] = None,
    reporting_currency: Optional[str] = None,
    currency_rates: Optional[Mapping[Tuple[str, str], float]] = None,
    value_per_response: Optional[Mapping[str, float]] = None,
    evidence_status: Optional[Mapping[Tuple[str, str], str]] = None,
    identification_status: Optional[Mapping[Tuple[str, str], str]] = None,
    near_zero: float = DEFAULT_NEAR_ZERO,
) -> pd.DataFrame:
    """Return one row per posterior draw and canonical component grain.

    Shared Model A parameters are evaluated for every market so market totals
    remain available, while their identification label defaults to
    ``shared_across_markets``.  Family History NBT outcomes are naturally
    represented by their ``metric_key`` and therefore become the default FH
    denominator in product/market economics views.
    """
    if model_type not in {"shared", "market_specific"}:
        raise ValueError("model_type must be 'shared' or 'market_specific'")
    if not model_run_id:
        raise ValueError("model_run_id is required")
    units_valid = (
        spend_unit in SUPPORTED_SPEND_UNITS
        and np.isfinite(spend_unit_scale)
        and spend_unit_scale > 0
    )
    extract = (
        extract_market_specific_posterior_params
        if model_type == "market_specific"
        else extract_posterior_params
    )
    mean_params = extract(trace, meta)
    support = _normalise_support(
        meta, mean_params, model_type, support_by_market_channel
    )
    currencies = dict(currency_by_market or {})
    rates = dict(currency_rates or {})
    values = dict(value_per_response or {})
    evidence = dict(evidence_status or {})
    identification = dict(identification_status or {})
    components = [
        component
        for component in meta.pathway_masks.components
        if component.included_in_fit
        and component.component_type in {"direct", "cross_product"}
    ]
    rows = []
    for chain, draw in sample_draw_indices(trace, n_draws, seed):
        params = extract(trace, meta, at=(chain, draw))
        posterior_draw = f"{chain}:{draw}"
        for market in meta.markets:
            market_currency = currencies.get(
                market, reporting_currency or spend_unit
            )
            currency_valid = bool(market_currency)
            rate = 1.0
            if reporting_currency and market_currency != reporting_currency:
                rate = float(rates.get((market_currency, reporting_currency), np.nan))
                currency_valid = currency_valid and np.isfinite(rate) and rate > 0
            for channel in meta.channels:
                K = (
                    params.hill_K[market][channel]
                    if model_type == "market_specific"
                    else params.hill_K[channel]
                )
                beta_by_outcome = (
                    params.beta[market]
                    if model_type == "market_specific"
                    else params.beta
                )
                channel_support = support[(market, channel)]
                axis = (
                    np.asarray(spend_points, dtype=float)
                    if spend_points is not None
                    else np.linspace(
                        channel_support["planning_spend_min"],
                        channel_support["planning_spend_max"],
                        25,
                    )
                )
                if np.any(~np.isfinite(axis)) or np.any(axis < 0):
                    raise ValueError("spend_points must be finite and non-negative")
                for spend_point, raw_spend in enumerate(axis):
                    spend = float(raw_spend) * spend_unit_scale * rate
                    saturation = float(
                        hill_function(np.array([float(raw_spend)]), K, params.hill_S[channel])[0]
                    )
                    derivative = _hill_derivative(
                        float(raw_spend), K, params.hill_S[channel]
                    )
                    for component in components:
                        if component.channel != channel:
                            continue
                        outcome_id = component.outcome_id
                        strength = (
                            1.0
                            if component.component_type == "direct"
                            else params.pathway_strength[outcome_id][channel]
                        )
                        coefficient = beta_by_outcome[outcome_id][channel]
                        response = coefficient * strength * saturation
                        marginal_response = (
                            coefficient * strength * derivative
                            / (spend_unit_scale * rate)
                            if units_valid and currency_valid
                            else float("nan")
                        )
                        economics = _economic_values(
                            spend=spend,
                            response=response,
                            marginal_response=marginal_response,
                            value_per_response=values.get(outcome_id),
                            units_valid=units_valid,
                            currency_valid=currency_valid,
                            near_zero=near_zero,
                        )
                        observed_min = channel_support["observed_spend_min"]
                        observed_max = channel_support["observed_spend_max"]
                        is_extrapolated = not (
                            observed_min <= raw_spend <= observed_max
                        )
                        rows.append(
                            {
                                "model_run_id": model_run_id,
                                "market": market,
                                "product": meta.outcome_id_to_product.get(outcome_id, ""),
                                "segment": meta.outcome_id_to_segment.get(outcome_id, ""),
                                "outcome_id": outcome_id,
                                "metric_key": meta.outcome_id_to_metric_key.get(outcome_id, ""),
                                "channel": channel,
                                "component_type": component.component_type,
                                "pathway_role": component.role,
                                "spend_point": spend_point,
                                "posterior_draw": posterior_draw,
                                "spend": spend,
                                "spend_unit": (
                                    reporting_currency
                                    or market_currency
                                    or spend_unit
                                ),
                                "response": response,
                                "response_unit": meta.outcome_id_to_unit.get(outcome_id, ""),
                                "marginal_response": marginal_response,
                                "current_spend": channel_support["current_spend"]
                                * spend_unit_scale
                                * rate,
                                "observed_spend_min": observed_min * spend_unit_scale * rate,
                                "observed_spend_max": observed_max * spend_unit_scale * rate,
                                "planning_spend_min": channel_support["planning_spend_min"]
                                * spend_unit_scale
                                * rate,
                                "planning_spend_max": channel_support["planning_spend_max"]
                                * spend_unit_scale
                                * rate,
                                "adstock_parameter": params.decay_rate[channel],
                                "lag_weeks": component.lag_weeks,
                                "hill_K": K * spend_unit_scale * rate,
                                "hill_S": params.hill_S[channel],
                                "coefficient": coefficient,
                                "pathway_strength": strength,
                                "include_in_attribution": component.include_in_attribution,
                                "include_in_headline": component.include_in_headline,
                                "include_in_planning": component.include_in_planning,
                                "evidence_status": evidence.get(
                                    (market, channel), component.evidence_status
                                ),
                                "identification_label": identification.get(
                                    (market, channel),
                                    "shared_across_markets"
                                    if model_type == "shared"
                                    else "not_assessed",
                                ),
                                "is_extrapolated": is_extrapolated,
                                "economics_scope": "channel_incremental",
                                "economics_denominator": meta.outcome_id_to_metric_key.get(
                                    outcome_id, ""
                                ),
                                "incremental_value": (
                                    response * values[outcome_id]
                                    if outcome_id in values
                                    and np.isfinite(values[outcome_id])
                                    else float("nan")
                                ),
                                "marginal_value": (
                                    marginal_response * values[outcome_id]
                                    if outcome_id in values
                                    and np.isfinite(values[outcome_id])
                                    else float("nan")
                                ),
                                **economics,
                            }
                        )
    return pd.DataFrame(rows)


def aggregate_curve_draws(
    draws: pd.DataFrame,
    *,
    by: Sequence[str],
    governance: Optional[str] = None,
) -> pd.DataFrame:
    """Aggregate responses by draw, then recompute economics.

    ``governance`` may be ``headline`` or ``planning``. Spend is counted once
    per channel within an aggregate so direct and halo rows cannot duplicate
    channel cost.
    """
    data = draws.copy()
    if governance in {"headline", "planning"}:
        data = data[data[f"include_in_{governance}"]]
    elif governance not in {None, "attribution"}:
        raise ValueError("governance must be attribution, headline, planning, or None")
    if governance == "attribution":
        data = data[data["include_in_attribution"]]
    group_cols = list(by) + ["posterior_draw"]
    channel_cost_cols = group_cols + ["channel"]
    channel_spend = (
        data.groupby(channel_cost_cols, dropna=False, sort=False)["spend"]
        .max()
        .groupby(group_cols, dropna=False, sort=False)
        .sum()
    )
    result = (
        data.groupby(group_cols, dropna=False, sort=False)
        .agg(
            response=("response", "sum"),
            marginal_response=("marginal_response", "sum"),
            incremental_value=("incremental_value", lambda s: s.sum(min_count=1)),
            marginal_value=("marginal_value", lambda s: s.sum(min_count=1)),
            response_unit=("response_unit", lambda s: s.iloc[0] if s.nunique() == 1 else "mixed"),
            spend_unit=("spend_unit", lambda s: s.iloc[0] if s.nunique() == 1 else "mixed"),
            is_extrapolated=("is_extrapolated", "max"),
        )
        .reset_index()
    )
    result["spend"] = [
        channel_spend.loc[tuple(row[col] for col in group_cols)]
        for _, row in result.iterrows()
    ]
    unit_ok = (result["response_unit"] != "mixed") & (result["spend_unit"] != "mixed")
    result["average_cpa"] = np.where(
        unit_ok & (result["spend"] > 0) & (result["response"] > 0),
        result["spend"] / result["response"],
        np.nan,
    )
    result["marginal_cpa"] = np.where(
        unit_ok & (result["marginal_response"] > DEFAULT_NEAR_ZERO),
        1.0 / result["marginal_response"],
        np.nan,
    )
    result["average_roi"] = np.where(
        unit_ok & (result["spend"] > 0),
        result["incremental_value"] / result["spend"],
        np.nan,
    )
    result["marginal_roi"] = result["marginal_value"]
    result["economics_scope"] = (
        "channel_incremental" if "channel" in by else "whole_plan"
    )
    return result


def canonical_governance_views(draws: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Standard draw-level views used by reporting, planning, and exports."""
    common = [
        "model_run_id",
        "market",
        "channel",
        "spend_point",
    ]
    nbt = draws[draws["metric_key"] == "fh_net_billthrough_count"]
    return {
        "segment": aggregate_curve_draws(
            draws, by=common + ["product", "segment", "metric_key"]
        ),
        "product": aggregate_curve_draws(
            draws, by=common + ["product", "metric_key"]
        ),
        "market": aggregate_curve_draws(
            draws,
            by=["model_run_id", "market", "spend_point", "metric_key"],
        ),
        "fh_nbt_total": aggregate_curve_draws(
            nbt,
            by=["model_run_id", "market", "channel", "spend_point", "metric_key"],
        ),
        "direct": aggregate_curve_draws(
            draws[draws["component_type"] == "direct"],
            by=common + ["product", "metric_key"],
        ),
        "halo": aggregate_curve_draws(
            draws[draws["component_type"] == "cross_product"],
            by=common + ["product", "metric_key"],
        ),
        "headline": aggregate_curve_draws(
            draws,
            by=common + ["product", "metric_key"],
            governance="headline",
        ),
        "planning": aggregate_curve_draws(
            draws,
            by=common + ["product", "metric_key"],
            governance="planning",
        ),
    }


def summarize_curve_draws(
    draws: pd.DataFrame, cred_mass: float = DEFAULT_CRED_MASS
) -> pd.DataFrame:
    """Posterior summaries at every non-draw identity in ``draws``."""
    if not 0 < cred_mass < 1:
        raise ValueError("cred_mass must be between zero and one")
    identity = [
        column
        for column in IDENTITY_COLUMNS
        if column in draws.columns
    ]
    if not identity:
        raise ValueError("draws do not contain canonical identity columns")
    tail = (1.0 - cred_mass) / 2.0
    measures = [
        name
        for name in (
            "response",
            "marginal_response",
            "average_cpa",
            "marginal_cpa",
            "average_roi",
            "marginal_roi",
            "incremental_value",
            "marginal_value",
            "adstock_parameter",
            "hill_K",
            "hill_S",
            "coefficient",
            "pathway_strength",
        )
        if name in draws.columns
    ]
    grouped = draws.groupby(identity, dropna=False, sort=False)
    base = grouped.first().reset_index()
    keep = identity + [
        column
        for column in base.columns
        if column not in identity
        and column not in measures
        and column != "posterior_draw"
    ]
    result = base[keep].copy()
    for measure in measures:
        stats = grouped[measure].agg(
            posterior_mean="mean",
            posterior_median="median",
            lower_interval=lambda values: values.quantile(tail),
            upper_interval=lambda values: values.quantile(1.0 - tail),
        ).reset_index()
        result = result.merge(
            stats.rename(
                columns={
                    "posterior_mean": f"{measure}_posterior_mean",
                    "posterior_median": f"{measure}_posterior_median",
                    "lower_interval": f"{measure}_lower_interval",
                    "upper_interval": f"{measure}_upper_interval",
                }
            ),
            on=identity,
            how="left",
        )
    if "response_posterior_mean" in result:
        result["posterior_mean"] = result["response_posterior_mean"]
        result["posterior_median"] = result["response_posterior_median"]
        result["lower_interval"] = result["response_lower_interval"]
        result["upper_interval"] = result["response_upper_interval"]
    return result


def export_canonical_curve_bank(
    draws: pd.DataFrame, summaries: pd.DataFrame, directory: Path
) -> Tuple[Path, Path, Path]:
    """Write open, machine-readable draw, summary, and schema artifacts."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    draws_path = directory / "canonical_curve_draws.parquet"
    summaries_path = directory / "canonical_curve_summaries.parquet"
    schema_path = directory / "canonical_curve_schema.json"
    draws.to_parquet(draws_path, index=False)
    summaries.to_parquet(summaries_path, index=False)
    schema_path.write_text(
        json.dumps(
            {
                "version": "G2A-1",
                "grain": IDENTITY_COLUMNS,
                "draw_rows": len(draws),
                "summary_rows": len(summaries),
                "draw_columns": list(draws.columns),
                "summary_columns": list(summaries.columns),
            },
            indent=2,
        )
    )
    return draws_path, summaries_path, schema_path
