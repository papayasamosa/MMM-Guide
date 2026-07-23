"""Outcome-scale counterfactual posterior curves and economics (G2A.2).

The fitted models use a log link.  Media terms therefore live on the
linear-predictor scale, while business response lives on the outcome scale:

    incremental_response = mu(selected spend) - mu(counterfactual spend)

This module always obtains ``mu`` through the normal steady-state NumPy
prediction functions.  Component rows decompose response but carry no cost
economics by default; channel rows count spend once.  Portfolio marginal
economics require an explicit path and budget-perturbation direction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import arviz as az
import numpy as np
import pandas as pd

from .hierarchical_model import FHModelMeta
from .media_costs import CostMappingRegistry, MediaCostMapping, MediaInputSpec
from .market_specific_predict import (
    extract_market_specific_posterior_params,
    steady_state_outcome_response_market_specific,
)
from .predict import extract_posterior_params, steady_state_outcome_response
from .transformations import hill_function
from .uncertainty import DEFAULT_CRED_MASS, DEFAULT_N_DRAWS, sample_draw_indices

ECONOMICS_OK = "ok"
ECONOMICS_ZERO_SPEND = "zero_spend"
ECONOMICS_ZERO_RESPONSE = "zero_or_invalid_response"
ECONOMICS_NEAR_ZERO_MARGINAL = "zero_or_near_zero_marginal_response"
ECONOMICS_MISSING_VALUE = "missing_value"
ECONOMICS_UNIT_ERROR = "unit_error"
ECONOMICS_CURRENCY_ERROR = "currency_error"
ECONOMICS_COMPONENT_COST_UNALLOCATED = "component_cost_unallocated"
ECONOMICS_PORTFOLIO_DIRECTION_REQUIRED = "portfolio_direction_required"
ECONOMICS_COST_MAPPING_MISSING = "cost_mapping_missing"

SUPPORT_AVAILABLE = "available"
SUPPORT_MISSING = "missing"
SUPPORTED_SPEND_UNITS = {"currency", "currency_thousands"}
CONTEXT_MODES = {
    "recent_average",
    "period_average",
    "specific_week",
    "specific_scenario",
    "steady_state_reference",
}
CURRENT_SPEND_METHODS = {
    "latest_complete_week",
    "last_4_week_average",
    "last_13_week_average",
    "selected_period_average",
    "uploaded_plan",
}
DEFAULT_NEAR_ZERO = 1e-12
ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")

IDENTITY_COLUMNS = [
    "model_run_id",
    "reference_context_id",
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


@dataclass(frozen=True)
class CurveReferenceContext:
    """Business context held fixed while one channel's spend is varied."""

    reference_context_id: str
    mode: str
    market: str
    trend: float
    fourier: Tuple[float, ...]
    promo: Mapping[str, float]
    controls: Mapping[str, float]
    outcome_controls: Mapping[str, Mapping[str, float]]
    other_channel_spend: Mapping[str, float]
    counterfactual_spend: float = 0.0
    reference_period_start: Optional[str] = None
    reference_period_end: Optional[str] = None
    other_media_assumption: str = "held_at_reference"
    promotion_assumption: str = "explicit_reference_values"
    seasonality_assumption: str = "explicit_fourier_values"

    def __post_init__(self) -> None:
        if not self.reference_context_id:
            raise ValueError("reference_context_id is required")
        if self.mode not in CONTEXT_MODES:
            raise ValueError(
                f"Unsupported context mode '{self.mode}'; expected {sorted(CONTEXT_MODES)}"
            )
        if not self.market:
            raise ValueError("reference market is required")
        if not np.isfinite(self.trend):
            raise ValueError("reference trend must be finite")
        if self.counterfactual_spend < 0 or not np.isfinite(
            self.counterfactual_spend
        ):
            raise ValueError("counterfactual_spend must be finite and non-negative")
        if any(value < 0 or not np.isfinite(value) for value in self.other_channel_spend.values()):
            raise ValueError("other-channel reference spend must be finite and non-negative")

    def prediction_context(self) -> dict:
        return {
            "trend": float(self.trend),
            "fourier": np.asarray(self.fourier, dtype=float),
            "promo": dict(self.promo),
            "controls": dict(self.controls),
            "outcome_controls": {
                key: dict(values) for key, values in self.outcome_controls.items()
            },
        }

    def metadata(self) -> dict:
        return {
            "reference_context_id": self.reference_context_id,
            "reference_context_mode": self.mode,
            "reference_period_start": self.reference_period_start,
            "reference_period_end": self.reference_period_end,
            "reference_market": self.market,
            "other_media_assumption": self.other_media_assumption,
            "promotion_assumption": self.promotion_assumption,
            "seasonality_assumption": self.seasonality_assumption,
            "counterfactual_spend": float(self.counterfactual_spend),
            "reference_other_channel_spend": json.dumps(
                dict(self.other_channel_spend), sort_keys=True
            ),
            "reference_trend": float(self.trend),
            "reference_fourier": json.dumps(list(self.fourier)),
            "reference_promotions": json.dumps(dict(self.promo), sort_keys=True),
            "reference_controls": json.dumps(dict(self.controls), sort_keys=True),
            "reference_outcome_controls": json.dumps(
                {
                    key: dict(values)
                    for key, values in self.outcome_controls.items()
                },
                sort_keys=True,
            ),
        }


@dataclass(frozen=True)
class PortfolioPerturbation:
    """Direction of one reporting-currency unit of incremental portfolio budget."""

    perturbation_id: str
    allocation_direction: Mapping[str, float]
    method: str = "analyst_defined"
    source: str = ""

    def __post_init__(self) -> None:
        if not self.perturbation_id:
            raise ValueError("perturbation_id is required")
        values = np.asarray(list(self.allocation_direction.values()), dtype=float)
        if not len(values) or np.any(~np.isfinite(values)) or np.any(values < 0):
            raise ValueError("allocation_direction must contain finite non-negative shares")
        if not np.isclose(values.sum(), 1.0):
            raise ValueError("allocation_direction shares must sum to 1")


@dataclass(frozen=True)
class ComponentCostAllocation:
    """Explicit allocation of channel cost to equation components.

    Keys are ``(outcome_id, channel, component_type)``. Shares for the
    components of each outcome/channel relationship must sum to one.
    """

    allocation_id: str
    shares: Mapping[Tuple[str, str, str], float]
    method: str = "analyst_defined"
    source: str = ""

    def __post_init__(self) -> None:
        if not self.allocation_id:
            raise ValueError("component allocation_id is required")
        if any(
            not np.isfinite(value) or value < 0 or value > 1
            for value in self.shares.values()
        ):
            raise ValueError("component cost shares must be finite and between 0 and 1")


def _is_iso_currency(value: Optional[str]) -> bool:
    return bool(value and ISO_CURRENCY.fullmatch(value))


def _normalise_support(
    meta: FHModelMeta,
    support_by_market_channel: Optional[
        Mapping[Tuple[str, str], Mapping[str, object]]
    ],
) -> Dict[Tuple[str, str], Dict[str, object]]:
    supplied = support_by_market_channel or {}
    result: Dict[Tuple[str, str], Dict[str, object]] = {}
    for market in meta.markets:
        for channel in meta.channels:
            values = dict(supplied.get((market, channel), {}))
            required = {
                "observed_spend_min",
                "observed_spend_max",
                "current_spend",
            }
            if not required <= values.keys():
                result[(market, channel)] = {
                    "observed_support_status": SUPPORT_MISSING,
                    "current_spend": np.nan,
                    "observed_spend_min": np.nan,
                    "observed_spend_max": np.nan,
                    "planning_spend_min": np.nan,
                    "planning_spend_max": np.nan,
                    "current_spend_method": values.get(
                        "current_spend_method", "unknown"
                    ),
                    "current_spend_reference_period_start": values.get(
                        "current_spend_reference_period_start"
                    ),
                    "current_spend_reference_period_end": values.get(
                        "current_spend_reference_period_end"
                    ),
                }
                continue
            observed_min = float(values["observed_spend_min"])
            observed_max = float(values["observed_spend_max"])
            current = float(values["current_spend"])
            planning_min = float(values.get("planning_spend_min", observed_min))
            planning_max = float(values.get("planning_spend_max", observed_max))
            if not (
                0 <= observed_min <= observed_max
                and 0 <= planning_min <= planning_max
                and current >= 0
                and np.isfinite(
                    [observed_min, observed_max, planning_min, planning_max, current]
                ).all()
            ):
                raise ValueError(
                    f"Invalid actual spend support for {market}/{channel}: {values}"
                )
            result[(market, channel)] = {
                "observed_support_status": SUPPORT_AVAILABLE,
                "current_spend": current,
                "observed_spend_min": observed_min,
                "observed_spend_max": observed_max,
                "planning_spend_min": planning_min,
                "planning_spend_max": planning_max,
                "current_spend_method": values.get(
                    "current_spend_method", "selected_period_average"
                ),
                "current_spend_reference_period_start": values.get(
                    "current_spend_reference_period_start"
                ),
                "current_spend_reference_period_end": values.get(
                    "current_spend_reference_period_end"
                ),
            }
    return result


def support_from_model_frame(
    frame: Mapping[str, object],
    meta: FHModelMeta,
    *,
    current_spend_method: str = "last_4_week_average",
    selected_period_start: Optional[str] = None,
    selected_period_end: Optional[str] = None,
    uploaded_plan: Optional[Mapping[Tuple[str, str], float]] = None,
) -> Dict[Tuple[str, str], Dict[str, object]]:
    """Derive actual observed support and a governed current-spend definition."""
    if current_spend_method not in CURRENT_SPEND_METHODS:
        raise ValueError(
            f"Unsupported current-spend method '{current_spend_method}'"
        )
    media = np.asarray(frame["X_media"], dtype=float)
    market_idx = np.asarray(
        frame.get("market_idx", np.zeros(len(media))), dtype=int
    )
    dates = pd.to_datetime(
        frame.get("dates", np.arange(len(media))), errors="coerce"
    )
    result = {}
    for market_pos, market in enumerate(meta.markets):
        mask = market_idx == market_pos
        rows = media[mask]
        market_dates = dates[mask]
        if not len(rows):
            continue
        for channel_pos, channel in enumerate(meta.channels):
            values = rows[:, channel_pos]
            reference_mask = np.ones(len(values), dtype=bool)
            if current_spend_method == "latest_complete_week":
                current_values = values[-1:]
                reference_mask[:] = False
                reference_mask[-1] = True
            elif current_spend_method == "last_4_week_average":
                current_values = values[-4:]
                reference_mask[:] = False
                reference_mask[-min(4, len(values)) :] = True
            elif current_spend_method == "last_13_week_average":
                current_values = values[-13:]
                reference_mask[:] = False
                reference_mask[-min(13, len(values)) :] = True
            elif current_spend_method == "selected_period_average":
                if selected_period_start is None or selected_period_end is None:
                    raise ValueError(
                        "selected_period_average requires start and end dates"
                    )
                reference_mask = (
                    (market_dates >= pd.Timestamp(selected_period_start))
                    & (market_dates <= pd.Timestamp(selected_period_end))
                )
                if not reference_mask.any():
                    raise ValueError(
                        f"Selected period has no observations for {market}"
                    )
                current_values = values[reference_mask]
            else:
                key = (market, channel)
                if uploaded_plan is None or key not in uploaded_plan:
                    raise ValueError(
                        f"uploaded_plan is missing current spend for {market}/{channel}"
                    )
                current_values = np.asarray([uploaded_plan[key]], dtype=float)
                reference_mask[:] = False
            selected_dates = market_dates[reference_mask]
            result[(market, channel)] = {
                "current_spend": float(np.mean(current_values)),
                "observed_spend_min": float(np.nanmin(values)),
                "observed_spend_max": float(np.nanmax(values)),
                "planning_spend_min": float(np.nanmin(values)),
                "planning_spend_max": float(np.nanmax(values)),
                "current_spend_method": current_spend_method,
                "current_spend_reference_period_start": (
                    str(pd.Timestamp(selected_dates.min()).date())
                    if len(selected_dates) and not pd.isna(selected_dates.min())
                    else selected_period_start
                ),
                "current_spend_reference_period_end": (
                    str(pd.Timestamp(selected_dates.max()).date())
                    if len(selected_dates) and not pd.isna(selected_dates.max())
                    else selected_period_end
                ),
            }
    return result


def reference_context_from_model_frame(
    frame: Mapping[str, object],
    meta: FHModelMeta,
    *,
    market: str,
    mode: str,
    reference_context_id: str,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    specific_week: Optional[str] = None,
    other_channel_spend: Optional[Mapping[str, float]] = None,
    counterfactual_spend: float = 0.0,
) -> CurveReferenceContext:
    """Build a recent/period/week reference context from prepared arrays.

    ``specific_scenario`` remains explicit by design and should be created
    directly as :class:`CurveReferenceContext`; silently averaging historical
    arrays would not represent an uploaded scenario.
    """
    if mode not in {
        "recent_average",
        "period_average",
        "specific_week",
        "steady_state_reference",
    }:
        raise ValueError(
            "Model-frame context mode must be recent_average, period_average, "
            "specific_week, or steady_state_reference"
        )
    if market not in meta.markets:
        raise ValueError(f"Unknown reference market '{market}'")
    market_pos = meta.markets.index(market)
    market_idx = np.asarray(frame["market_idx"], dtype=int)
    dates = pd.to_datetime(frame["dates"])
    mask = market_idx == market_pos
    if mode == "recent_average":
        positions = np.flatnonzero(mask)[-13:]
        mask = np.zeros(len(market_idx), dtype=bool)
        mask[positions] = True
    elif mode == "period_average":
        if period_start is None or period_end is None:
            raise ValueError("period_average requires period_start and period_end")
        mask &= (dates >= pd.Timestamp(period_start)) & (
            dates <= pd.Timestamp(period_end)
        )
    elif mode == "specific_week":
        if specific_week is None:
            raise ValueError("specific_week mode requires specific_week")
        mask &= dates.normalize() == pd.Timestamp(specific_week).normalize()
    if not mask.any():
        raise ValueError(f"Reference selection has no observations for {market}")
    media = np.asarray(frame["X_media"], dtype=float)[mask]
    trend = float(np.asarray(frame["trend"], dtype=float)[mask].mean())
    fourier = tuple(
        np.asarray(frame["fourier"], dtype=float)[mask].mean(axis=0).tolist()
    )
    promo_values = np.asarray(frame["promo"], dtype=float)[mask].mean(axis=0)
    promo = {
        outcome_id: float(promo_values[index])
        for index, outcome_id in enumerate(meta.outcome_ids)
    }
    controls = {}
    control_names = list(frame.get("control_names") or [])
    if control_names:
        control_values = np.asarray(frame["X_controls"], dtype=float)[mask].mean(
            axis=0
        )
        controls = {
            name: float(control_values[index])
            for index, name in enumerate(control_names)
        }
    outcome_controls = {}
    for outcome_id, values in (frame.get("outcome_controls") or {}).items():
        names = (frame.get("outcome_control_names") or {}).get(outcome_id, [])
        averages = np.asarray(values, dtype=float)[mask].mean(axis=0)
        outcome_controls[outcome_id] = {
            name: float(averages[index]) for index, name in enumerate(names)
        }
    reference_spend = (
        dict(other_channel_spend)
        if other_channel_spend is not None
        else {
            channel: float(media[:, index].mean())
            for index, channel in enumerate(meta.channels)
        }
    )
    selected_dates = dates[mask]
    return CurveReferenceContext(
        reference_context_id=reference_context_id,
        mode=mode,
        market=market,
        trend=trend,
        fourier=fourier,
        promo=promo,
        controls=controls,
        outcome_controls=outcome_controls,
        other_channel_spend=reference_spend,
        counterfactual_spend=counterfactual_spend,
        reference_period_start=str(pd.Timestamp(selected_dates.min()).date()),
        reference_period_end=str(pd.Timestamp(selected_dates.max()).date()),
        other_media_assumption=(
            "explicit_reference"
            if other_channel_spend is not None
            else f"{mode}_observed_average"
        ),
        promotion_assumption=f"{mode}_observed_average",
        seasonality_assumption=f"{mode}_observed_average",
    )


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
    average_cpa = spend / response if status == ECONOMICS_OK else np.nan
    marginal_ok = (
        units_valid
        and currency_valid
        and np.isfinite(marginal_response)
        and marginal_response > near_zero
    )
    marginal_cpa = 1.0 / marginal_response if marginal_ok else np.nan
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
        else np.nan
    )
    marginal_roi = (
        marginal_response * float(value_per_response)
        if marginal_ok and value_ok
        else np.nan
    )
    return {
        "average_cpa": average_cpa,
        "marginal_cpa": marginal_cpa,
        "average_roi": average_roi,
        "marginal_roi": marginal_roi,
        "average_economics_status": status,
        "marginal_economics_status": marginal_status,
        "roi_status": (
            ECONOMICS_MISSING_VALUE
            if not value_ok
            else status
        ),
    }


def _currency_metadata(
    meta: FHModelMeta,
    currency_by_market: Optional[Mapping[str, str]],
    reporting_currency: Optional[str],
    currency_rates: Optional[Mapping[Tuple[str, str], float]],
    fx_as_of_date: Optional[str],
) -> Dict[str, dict]:
    currencies = dict(currency_by_market or {})
    rates = dict(currency_rates or {})
    multi_market = len(meta.markets) > 1
    if multi_market:
        if set(currencies) != set(meta.markets):
            raise ValueError(
                "Multi-market curves require an explicit ISO currency for every market"
            )
        if not _is_iso_currency(reporting_currency):
            raise ValueError(
                "Multi-market curves require an explicit ISO reporting currency"
            )
        if not fx_as_of_date:
            raise ValueError("Multi-market curves require an FX as-of date")
        pd.Timestamp(fx_as_of_date)
    result = {}
    for market in meta.markets:
        local = currencies.get(market)
        if not _is_iso_currency(local):
            raise ValueError(f"Invalid or missing ISO currency for {market}: {local}")
        reporting = reporting_currency or local
        if not _is_iso_currency(reporting):
            raise ValueError(f"Invalid reporting currency: {reporting}")
        rate = 1.0 if local == reporting else rates.get((local, reporting))
        valid = rate is not None and np.isfinite(rate) and rate > 0
        if multi_market and not valid:
            raise ValueError(
                f"Missing valid FX rate for {local}->{reporting}"
            )
        result[market] = {
            "local_currency": local,
            "reporting_currency": reporting,
            "fx_rate": float(rate) if valid else np.nan,
            "fx_as_of_date": fx_as_of_date,
            "currency_valid": bool(valid),
        }
    return result


def _predict(
    *,
    market: str,
    spend_by_channel: Dict[str, float],
    meta: FHModelMeta,
    params,
    model_type: str,
    context: CurveReferenceContext,
) -> Dict[str, float]:
    fn = (
        steady_state_outcome_response_market_specific
        if model_type == "market_specific"
        else steady_state_outcome_response
    )
    return fn(
        market,
        spend_by_channel,
        meta,
        params,
        context.prediction_context(),
    )


def _axis_for_channel(
    spend_points: Optional[Sequence[float]],
    channel_support: Mapping[str, object],
    n_points: int,
) -> np.ndarray:
    if spend_points is not None:
        axis = np.asarray(spend_points, dtype=float)
    elif channel_support["observed_support_status"] == SUPPORT_AVAILABLE:
        axis = np.linspace(
            float(channel_support["planning_spend_min"]),
            float(channel_support["planning_spend_max"]),
            n_points,
        )
    else:
        raise ValueError(
            "Observed support is missing; provide an explicit diagnostic spend axis "
            "or actual support from the prepared model frame"
        )
    if not len(axis) or np.any(~np.isfinite(axis)) or np.any(axis < 0):
        raise ValueError("spend_points must be finite, non-negative, and non-empty")
    return axis


def _finite_difference_delta(
    spend: float,
    channel_support: Mapping[str, object],
    configured_delta: Optional[float],
) -> float:
    if configured_delta is not None:
        if configured_delta <= 0 or not np.isfinite(configured_delta):
            raise ValueError("marginal_delta must be finite and positive")
        return float(configured_delta)
    support_width = 0.0
    if channel_support["observed_support_status"] == SUPPORT_AVAILABLE:
        support_width = float(channel_support["observed_spend_max"]) - float(
            channel_support["observed_spend_min"]
        )
    return max(abs(spend) * 1e-4, support_width * 1e-5, 1e-6)


def generate_canonical_curve_draws(
    *,
    model_run_id: str,
    meta: FHModelMeta,
    trace: az.InferenceData,
    reference_contexts: Mapping[str, CurveReferenceContext],
    model_type: str = "shared",
    n_draws: int = DEFAULT_N_DRAWS,
    seed: int = 42,
    spend_points: Optional[Sequence[float]] = None,
    n_points: int = 25,
    support_by_market_channel: Optional[
        Mapping[Tuple[str, str], Mapping[str, object]]
    ] = None,
    spend_unit: str = "currency",
    spend_unit_scale: float = 1.0,
    currency_by_market: Optional[Mapping[str, str]] = None,
    reporting_currency: Optional[str] = None,
    currency_rates: Optional[Mapping[Tuple[str, str], float]] = None,
    fx_as_of_date: Optional[str] = None,
    value_per_response: Optional[Mapping[str, float]] = None,
    evidence_status: Optional[Mapping[Tuple[str, str], str]] = None,
    identification_status: Optional[Mapping[Tuple[str, str], str]] = None,
    marginal_delta: Optional[float] = None,
    near_zero: float = DEFAULT_NEAR_ZERO,
    attribution_reference: Optional[Mapping[Tuple[str, str, str], float]] = None,
    component_cost_allocation: Optional[ComponentCostAllocation] = None,
    curve_type: Optional[str] = None,
    media_input_specs: Optional[
        Mapping[Tuple[str, str], MediaInputSpec]
    ] = None,
    cost_mappings: Optional[
        Mapping[Tuple[str, str], MediaCostMapping]
    ] = None,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: str = "default",
    cost_as_of_date: Optional[str] = None,
) -> pd.DataFrame:
    """Generate component response decomposition on the outcome-count scale.

    Component ``average_cpa``/``marginal_cpa``/ROI are intentionally absent
    (NaN) because no component cost-allocation method is defined. Use
    :func:`aggregate_curve_draws` with a channel in the grouping to obtain
    valid channel-total economics.
    """
    if model_type not in {"shared", "market_specific"}:
        raise ValueError("model_type must be 'shared' or 'market_specific'")
    if curve_type not in {None, "model_input", "monetary"}:
        raise ValueError("curve_type must be 'model_input' or 'monetary'")
    legacy_monetary = curve_type is None
    effective_curve_type = "monetary" if legacy_monetary else curve_type
    input_specs = dict(media_input_specs or {})
    governed_costs = dict(cost_mappings or {})
    if governed_costs and cost_mapping_registry is not None:
        raise ValueError(
            "Supply cost_mappings or cost_mapping_registry, not both"
        )

    def resolve_cost(market: str, channel: str) -> Optional[MediaCostMapping]:
        if cost_mapping_registry is not None:
            return cost_mapping_registry.resolve(
                market,
                channel,
                cost_context_id,
                as_of=cost_as_of_date,
            )
        return governed_costs.get((market, channel))

    if not legacy_monetary:
        missing_specs = {
            (market, channel)
            for market in meta.markets
            for channel in meta.channels
            if (market, channel) not in input_specs
        }
        if missing_specs:
            raise ValueError(
                "Explicit media-input metadata is required for "
                f"{sorted(missing_specs)}"
            )
    if effective_curve_type == "monetary" and not legacy_monetary:
        missing_costs = []
        for market in meta.markets:
            for channel in meta.channels:
                mapping = resolve_cost(market, channel)
                if (
                    mapping is None
                    or mapping.cost_context_id != cost_context_id
                    or not mapping.is_valid_for(as_of=cost_as_of_date)
                ):
                    missing_costs.append((market, channel))
        if missing_costs:
            raise ValueError(
                "Monetary curves are blocked without an approved, effective "
                f"cost mapping for {sorted(missing_costs)}"
            )
    if not model_run_id:
        raise ValueError("model_run_id is required")
    if set(reference_contexts) != set(meta.markets):
        raise ValueError("Provide exactly one explicit reference context per market")
    for market, context in reference_contexts.items():
        if context.market != market:
            raise ValueError(
                f"Reference context {context.reference_context_id} targets "
                f"{context.market}, not mapping key {market}"
            )
        missing_channels = set(meta.channels) - set(context.other_channel_spend)
        if missing_channels:
            raise ValueError(
                f"Reference context {context.reference_context_id} is missing "
                f"other-channel spend for {sorted(missing_channels)}"
            )
    units_valid = (
        spend_unit in SUPPORTED_SPEND_UNITS
        and np.isfinite(spend_unit_scale)
        and spend_unit_scale > 0
    )
    if effective_curve_type == "model_input":
        currencies = {
            market: {
                "local_currency": (currency_by_market or {}).get(market),
                "reporting_currency": reporting_currency,
                "fx_rate": np.nan,
                "fx_as_of_date": fx_as_of_date,
                "currency_valid": False,
            }
            for market in meta.markets
        }
    else:
        currencies = _currency_metadata(
            meta,
            currency_by_market,
            reporting_currency,
            currency_rates,
            fx_as_of_date,
        )
    support = _normalise_support(meta, support_by_market_channel)
    extract = (
        extract_market_specific_posterior_params
        if model_type == "market_specific"
        else extract_posterior_params
    )
    values = dict(value_per_response or {})
    evidence = dict(evidence_status or {})
    identification = dict(identification_status or {})
    attribution = dict(attribution_reference or {})
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
            context = reference_contexts[market]
            currency = currencies[market]
            fx_rate = currency["fx_rate"]
            for channel in meta.channels:
                channel_support = support[(market, channel)]
                axis = _axis_for_channel(spend_points, channel_support, n_points)
                input_spec = input_specs.get((market, channel))
                cost_mapping = resolve_cost(market, channel)
                if (
                    not legacy_monetary
                    and cost_mapping is not None
                    and cost_mapping.currency != currency["local_currency"]
                ):
                    raise ValueError(
                        f"Cost mapping currency for {market}/{channel} is "
                        f"{cost_mapping.currency}, expected {currency['local_currency']}"
                    )
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
                counterfactual_axis = float(context.counterfactual_spend)
                counterfactual = (
                    float(cost_mapping.spend_to_media_input(counterfactual_axis))
                    if effective_curve_type == "monetary"
                    and not legacy_monetary
                    and cost_mapping is not None
                    else counterfactual_axis
                )
                without_plan = dict(context.other_channel_spend)
                without_plan[channel] = counterfactual
                mu_without = _predict(
                    market=market,
                    spend_by_channel=without_plan,
                    meta=meta,
                    params=params,
                    model_type=model_type,
                    context=context,
                )
                for spend_point, raw_spend in enumerate(axis):
                    raw_spend = float(raw_spend)
                    media_input = (
                        float(cost_mapping.spend_to_media_input(raw_spend))
                        if effective_curve_type == "monetary"
                        and not legacy_monetary
                        and cost_mapping is not None
                        else raw_spend
                    )
                    with_plan = dict(context.other_channel_spend)
                    with_plan[channel] = media_input
                    mu_with = _predict(
                        market=market,
                        spend_by_channel=with_plan,
                        meta=meta,
                        params=params,
                        model_type=model_type,
                        context=context,
                    )
                    delta = _finite_difference_delta(
                        media_input, channel_support, marginal_delta
                    )
                    lower_spend = max(0.0, media_input - delta)
                    upper_spend = media_input + delta
                    lower_plan = dict(with_plan)
                    upper_plan = dict(with_plan)
                    lower_plan[channel] = lower_spend
                    upper_plan[channel] = upper_spend
                    mu_lower = _predict(
                        market=market,
                        spend_by_channel=lower_plan,
                        meta=meta,
                        params=params,
                        model_type=model_type,
                        context=context,
                    )
                    mu_upper = _predict(
                        market=market,
                        spend_by_channel=upper_plan,
                        meta=meta,
                        params=params,
                        model_type=model_type,
                        context=context,
                    )
                    saturation = float(
                        hill_function(
                            np.array([media_input]), K, params.hill_S[channel]
                        )[0]
                    )
                    counterfactual_saturation = float(
                        hill_function(
                            np.array([counterfactual]), K, params.hill_S[channel]
                        )[0]
                    )
                    for outcome_id in meta.outcome_ids:
                        outcome_components = [
                            item
                            for item in components
                            if item.channel == channel
                            and item.outcome_id == outcome_id
                        ]
                        if not outcome_components:
                            continue
                        channel_incremental = (
                            mu_with[outcome_id] - mu_without[outcome_id]
                        )
                        marginal_raw = (
                            mu_upper[outcome_id] - mu_lower[outcome_id]
                        ) / (upper_spend - lower_spend)
                        if not legacy_monetary and effective_curve_type == "model_input":
                            marginal_mapping = np.nan
                            marginal_reporting = np.nan
                        elif not legacy_monetary and cost_mapping is not None:
                            marginal_mapping = float(
                                cost_mapping.marginal_media_input_per_currency(
                                    raw_spend
                                )
                            )
                            marginal_reporting = (
                                marginal_raw * marginal_mapping / fx_rate
                                if currency["currency_valid"]
                                else np.nan
                            )
                        else:
                            marginal_mapping = 1.0 / spend_unit_scale
                            marginal_reporting = (
                                marginal_raw / (spend_unit_scale * fx_rate)
                                if units_valid and currency["currency_valid"]
                                else np.nan
                            )
                        component_eta = []
                        component_eta_delta = []
                        for component in outcome_components:
                            strength = (
                                1.0
                                if component.component_type == "direct"
                                else params.pathway_strength[outcome_id][channel]
                            )
                            coefficient = beta_by_outcome[outcome_id][channel]
                            component_eta.append(
                                coefficient * strength * saturation
                            )
                            component_eta_delta.append(
                                coefficient
                                * strength
                                * (saturation - counterfactual_saturation)
                            )
                        total_eta_delta = float(np.sum(component_eta_delta))
                        if effective_curve_type == "model_input":
                            local_spend = np.nan
                            reporting_spend = np.nan
                            local_counterfactual = np.nan
                            incremental_spend = np.nan
                        elif legacy_monetary:
                            local_spend = raw_spend * spend_unit_scale
                            reporting_spend = local_spend * fx_rate
                            local_counterfactual = (
                                counterfactual * spend_unit_scale
                            )
                            incremental_spend = (
                                (raw_spend - counterfactual)
                                * spend_unit_scale
                                * fx_rate
                            )
                        else:
                            local_spend = raw_spend
                            reporting_spend = local_spend * fx_rate
                            local_counterfactual = counterfactual_axis
                            incremental_spend = (
                                raw_spend - counterfactual_axis
                            ) * fx_rate
                        observed_status = channel_support[
                            "observed_support_status"
                        ]
                        if observed_status == SUPPORT_AVAILABLE:
                            is_extrapolated: Optional[bool] = not (
                                channel_support["observed_spend_min"]
                                <= raw_spend
                                <= channel_support["observed_spend_max"]
                            )
                        else:
                            is_extrapolated = None
                        matched_attribution = attribution.get(
                            (market, channel, outcome_id)
                        )
                        if component_cost_allocation is not None:
                            allocation_shares = [
                                component_cost_allocation.shares.get(
                                    (
                                        outcome_id,
                                        channel,
                                        item.component_type,
                                    )
                                )
                                for item in outcome_components
                            ]
                            if any(value is None for value in allocation_shares):
                                raise ValueError(
                                    "Component cost allocation is missing a share "
                                    f"for {outcome_id}/{channel}"
                                )
                            if not np.isclose(sum(allocation_shares), 1.0):
                                raise ValueError(
                                    "Component cost shares must sum to 1 for "
                                    f"{outcome_id}/{channel}"
                                )
                        else:
                            allocation_shares = [None] * len(outcome_components)
                        for position, component in enumerate(outcome_components):
                            eta_share = (
                                component_eta_delta[position] / total_eta_delta
                                if not np.isclose(total_eta_delta, 0.0)
                                else 1.0 / len(outcome_components)
                            )
                            component_response = channel_incremental * eta_share
                            component_marginal = marginal_reporting * eta_share
                            strength = (
                                1.0
                                if component.component_type == "direct"
                                else params.pathway_strength[outcome_id][channel]
                            )
                            coefficient = beta_by_outcome[outcome_id][channel]
                            cost_share = allocation_shares[position]
                            component_value = (
                                component_response * values[outcome_id]
                                if outcome_id in values
                                and np.isfinite(values[outcome_id])
                                else np.nan
                            )
                            component_marginal_value = (
                                component_marginal * values[outcome_id]
                                if outcome_id in values
                                and np.isfinite(values[outcome_id])
                                else np.nan
                            )
                            if cost_share is None:
                                component_economics = {
                                    "average_cpa": np.nan,
                                    "marginal_cpa": np.nan,
                                    "average_roi": np.nan,
                                    "marginal_roi": np.nan,
                                    "average_economics_status": ECONOMICS_COMPONENT_COST_UNALLOCATED,
                                    "marginal_economics_status": ECONOMICS_COMPONENT_COST_UNALLOCATED,
                                    "roi_status": ECONOMICS_COMPONENT_COST_UNALLOCATED,
                                }
                                economics_scope = "component_response_no_cost"
                                allocated_spend = np.nan
                            else:
                                allocated_spend = incremental_spend * cost_share
                                component_economics = _economic_values(
                                    spend=allocated_spend,
                                    response=component_response,
                                    marginal_response=(
                                        component_marginal / cost_share
                                        if cost_share > 0
                                        else np.nan
                                    ),
                                    value_per_response=values.get(outcome_id),
                                    units_valid=units_valid,
                                    currency_valid=currency["currency_valid"],
                                    near_zero=near_zero,
                                )
                                economics_scope = "component_allocated_cost"
                            rows.append(
                                {
                                    "model_run_id": model_run_id,
                                    **context.metadata(),
                                    "market": market,
                                    "product": meta.outcome_id_to_product.get(
                                        outcome_id, ""
                                    ),
                                    "segment": meta.outcome_id_to_segment.get(
                                        outcome_id, ""
                                    ),
                                    "outcome_id": outcome_id,
                                    "metric_key": meta.outcome_id_to_metric_key.get(
                                        outcome_id, ""
                                    ),
                                    "channel": channel,
                                    "component_type": component.component_type,
                                    "pathway_role": component.role,
                                    "spend_point": spend_point,
                                    "posterior_draw": posterior_draw,
                                    "curve_type": effective_curve_type,
                                    "curve_method": "steady_state",
                                    "reference_interpretation": (
                                        "representative_context_not_historical_attribution"
                                    ),
                                    "media_input": media_input,
                                    "counterfactual_media_input": counterfactual,
                                    "media_input_column": (
                                        input_spec.column if input_spec else None
                                    ),
                                    "media_input_unit": (
                                        input_spec.unit
                                        if input_spec
                                        else spend_unit
                                    ),
                                    "media_input_unit_scale": (
                                        input_spec.unit_scale
                                        if input_spec
                                        else spend_unit_scale
                                    ),
                                    "cost_mapping_id": (
                                        cost_mapping.mapping_id
                                        if cost_mapping is not None
                                        else (
                                            "legacy_identity"
                                            if legacy_monetary
                                            else None
                                        )
                                    ),
                                    "cost_mapping_method": (
                                        cost_mapping.method
                                        if cost_mapping is not None
                                        else (
                                            "legacy_identity"
                                            if legacy_monetary
                                            else None
                                        )
                                    ),
                                    "cost_context_id": cost_context_id,
                                    "local_spend": local_spend,
                                    "reporting_currency_spend": reporting_spend,
                                    "spend": reporting_spend,
                                    "incremental_spend": incremental_spend,
                                    "counterfactual_local_spend": local_counterfactual,
                                    "spend_unit": (
                                        currency["reporting_currency"]
                                        if effective_curve_type == "monetary"
                                        else None
                                    ),
                                    "local_currency": currency["local_currency"],
                                    "reporting_currency": currency[
                                        "reporting_currency"
                                    ],
                                    "fx_rate": fx_rate,
                                    "fx_as_of_date": currency["fx_as_of_date"],
                                    "mu_with": mu_with[outcome_id],
                                    "mu_without": mu_without[outcome_id],
                                    "incremental_response": component_response,
                                    "response": component_response,
                                    "channel_total_incremental_response": channel_incremental,
                                    "response_unit": meta.outcome_id_to_unit.get(
                                        outcome_id, ""
                                    ),
                                    "media_eta_contribution": component_eta[position],
                                    "incremental_media_eta_contribution": component_eta_delta[
                                        position
                                    ],
                                    "component_response_allocation_method": "incremental_eta_share",
                                    "marginal_incremental_response_per_currency_unit": component_marginal,
                                    "marginal_incremental_response_per_media_input_unit": (
                                        marginal_raw * eta_share
                                    ),
                                    "marginal_media_input_per_local_currency_unit": (
                                        marginal_mapping
                                    ),
                                    "marginal_response": component_marginal,
                                    "channel_total_marginal_response": marginal_reporting,
                                    "marginal_calculation_method": (
                                        "forward_finite_difference"
                                        if lower_spend == media_input
                                        else "central_finite_difference"
                                    ),
                                    "marginal_delta_media_input": delta,
                                    "marginal_delta_local_spend": (
                                        delta * spend_unit_scale
                                        if legacy_monetary
                                        else np.nan
                                    ),
                                    "current_media_input": (
                                        channel_support["current_spend"]
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "model_input"
                                        else (
                                            float(
                                                cost_mapping.spend_to_media_input(
                                                    channel_support["current_spend"]
                                                )
                                            )
                                            if observed_status == SUPPORT_AVAILABLE
                                            and not legacy_monetary
                                            and cost_mapping is not None
                                            else np.nan
                                        )
                                    ),
                                    "current_spend": (
                                        channel_support["current_spend"]
                                        * (
                                            spend_unit_scale
                                            if legacy_monetary
                                            else 1.0
                                        )
                                        * fx_rate
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "monetary"
                                        else np.nan
                                    ),
                                    "current_spend_method": channel_support[
                                        "current_spend_method"
                                    ],
                                    "current_spend_reference_period_start": channel_support[
                                        "current_spend_reference_period_start"
                                    ],
                                    "current_spend_reference_period_end": channel_support[
                                        "current_spend_reference_period_end"
                                    ],
                                    "observed_support_status": observed_status,
                                    "observed_media_input_min": (
                                        channel_support["observed_spend_min"]
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "model_input"
                                        else np.nan
                                    ),
                                    "observed_media_input_max": (
                                        channel_support["observed_spend_max"]
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "model_input"
                                        else np.nan
                                    ),
                                    "planning_media_input_min": (
                                        channel_support["planning_spend_min"]
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "model_input"
                                        else np.nan
                                    ),
                                    "planning_media_input_max": (
                                        channel_support["planning_spend_max"]
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "model_input"
                                        else np.nan
                                    ),
                                    "observed_spend_min": (
                                        channel_support["observed_spend_min"]
                                        * (
                                            spend_unit_scale
                                            if legacy_monetary
                                            else 1.0
                                        )
                                        * fx_rate
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "monetary"
                                        else np.nan
                                    ),
                                    "observed_spend_max": (
                                        channel_support["observed_spend_max"]
                                        * (
                                            spend_unit_scale
                                            if legacy_monetary
                                            else 1.0
                                        )
                                        * fx_rate
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "monetary"
                                        else np.nan
                                    ),
                                    "planning_spend_min": (
                                        channel_support["planning_spend_min"]
                                        * (
                                            spend_unit_scale
                                            if legacy_monetary
                                            else 1.0
                                        )
                                        * fx_rate
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "monetary"
                                        else np.nan
                                    ),
                                    "planning_spend_max": (
                                        channel_support["planning_spend_max"]
                                        * (
                                            spend_unit_scale
                                            if legacy_monetary
                                            else 1.0
                                        )
                                        * fx_rate
                                        if observed_status == SUPPORT_AVAILABLE
                                        and effective_curve_type == "monetary"
                                        else np.nan
                                    ),
                                    "planning_support_eligible": (
                                        observed_status == SUPPORT_AVAILABLE
                                    ),
                                    "planning_blocked_reason": (
                                        ""
                                        if observed_status == SUPPORT_AVAILABLE
                                        else "observed_support_missing"
                                    ),
                                    "adstock_parameter": params.decay_rate[channel],
                                    "lag_weeks": component.lag_weeks,
                                    "hill_K": (
                                        K * spend_unit_scale * fx_rate
                                        if legacy_monetary
                                        else K
                                    ),
                                    "hill_S": params.hill_S[channel],
                                    "coefficient": coefficient,
                                    "pathway_strength": strength,
                                    "include_in_attribution": component.include_in_attribution,
                                    "include_in_headline": component.include_in_headline,
                                    "include_in_planning": (
                                        component.include_in_planning
                                        and observed_status == SUPPORT_AVAILABLE
                                    ),
                                    "evidence_status": evidence.get(
                                        (market, channel),
                                        component.evidence_status,
                                    ),
                                    "identification_label": identification.get(
                                        (market, channel),
                                        "shared_across_markets"
                                        if model_type == "shared"
                                        else "not_assessed",
                                    ),
                                    "is_extrapolated": is_extrapolated,
                                    "economics_scope": economics_scope,
                                    "component_cost_allocation_id": (
                                        component_cost_allocation.allocation_id
                                        if component_cost_allocation is not None
                                        else None
                                    ),
                                    "component_cost_allocation_method": (
                                        component_cost_allocation.method
                                        if component_cost_allocation is not None
                                        else "none"
                                    ),
                                    "component_cost_share": cost_share,
                                    "allocated_incremental_spend": allocated_spend,
                                    "economics_denominator": meta.outcome_id_to_metric_key.get(
                                        outcome_id, ""
                                    ),
                                    "incremental_value": component_value,
                                    "marginal_value": component_marginal_value,
                                    **component_economics,
                                    "counterfactual_prediction_reconciliation_error": (
                                        channel_incremental
                                        - (
                                            mu_with[outcome_id]
                                            - mu_without[outcome_id]
                                        )
                                    ),
                                    "curve_attribution_reconciliation_error": (
                                        channel_incremental
                                        - matched_attribution
                                        if matched_attribution is not None
                                        else np.nan
                                    ),
                                }
                            )
    return pd.DataFrame(rows)


def aggregate_curve_draws(
    draws: pd.DataFrame,
    *,
    by: Sequence[str],
    governance: Optional[str] = None,
    value_per_response: Optional[Mapping[str, float]] = None,
    economics_allowed: bool = True,
) -> pd.DataFrame:
    """Aggregate component response into valid channel-total economics.

    Cross-channel aggregation is rejected because ordinal channel spend axes
    do not define a portfolio path. Use :func:`aggregate_portfolio_marginal`
    with rows carrying an explicit ``portfolio_path_id``.
    """
    if "channel" not in by:
        raise ValueError(
            "Cross-channel curve aggregation is undefined without an explicit "
            "portfolio path; keep channel in `by`"
        )
    data = draws.copy()
    if governance in {"headline", "planning"}:
        data = data[data[f"include_in_{governance}"]]
    elif governance not in {None, "attribution"}:
        raise ValueError(
            "governance must be attribution, headline, planning, or None"
        )
    if governance == "attribution":
        data = data[data["include_in_attribution"]]
    group_cols = list(by) + ["posterior_draw"]
    grouped = data.groupby(group_cols, dropna=False, sort=False)
    result = grouped.agg(
        response=("incremental_response", "sum"),
        incremental_response=("incremental_response", "sum"),
        marginal_response=(
            "marginal_incremental_response_per_currency_unit",
            "sum",
        ),
        marginal_incremental_response_per_currency_unit=(
            "marginal_incremental_response_per_currency_unit",
            "sum",
        ),
        marginal_incremental_response_per_media_input_unit=(
            "marginal_incremental_response_per_media_input_unit",
            "sum",
        ),
        spend=("reporting_currency_spend", "max"),
        incremental_spend=("incremental_spend", "max"),
        local_spend=("local_spend", "max"),
        incremental_value=(
            "incremental_value",
            lambda values: values.sum()
            if values.notna().all()
            else np.nan,
        ),
        marginal_value=(
            "marginal_value",
            lambda values: values.sum()
            if values.notna().all()
            else np.nan,
        ),
        response_unit=(
            "response_unit",
            lambda values: values.iloc[0]
            if values.nunique() == 1
            else "mixed",
        ),
        spend_unit=(
            "reporting_currency",
            lambda values: values.iloc[0]
            if values.nunique() == 1
            else "mixed",
        ),
        is_extrapolated=(
            "is_extrapolated",
            lambda values: (
                None if values.isna().all() else bool(values.dropna().max())
            ),
        ),
        observed_support_status=(
            "observed_support_status",
            lambda values: values.iloc[0]
            if values.nunique() == 1
            else SUPPORT_MISSING,
        ),
        counterfactual_prediction_reconciliation_error=(
            "counterfactual_prediction_reconciliation_error",
            "max",
        ),
        curve_attribution_reconciliation_error=(
            "curve_attribution_reconciliation_error",
            lambda values: values.sum(min_count=1),
        ),
        curve_type=("curve_type", "first"),
        counterfactual_media_input=("counterfactual_media_input", "max"),
        cost_mapping_id=("cost_mapping_id", "first"),
    ).reset_index()
    values = dict(value_per_response or {})
    economics = []
    for _, row in result.iterrows():
        value = values.get(row.get("outcome_id"))
        if not economics_allowed:
            economics.append(
                {
                    "average_cpa": np.nan,
                    "marginal_cpa": np.nan,
                    "average_roi": np.nan,
                    "marginal_roi": np.nan,
                    "average_economics_status": ECONOMICS_COMPONENT_COST_UNALLOCATED,
                    "marginal_economics_status": ECONOMICS_COMPONENT_COST_UNALLOCATED,
                    "roi_status": ECONOMICS_COMPONENT_COST_UNALLOCATED,
                }
            )
        elif row["curve_type"] != "monetary" or not row["cost_mapping_id"]:
            economics.append(
                {
                    "average_cpa": np.nan,
                    "marginal_cpa": np.nan,
                    "average_roi": np.nan,
                    "marginal_roi": np.nan,
                    "average_economics_status": ECONOMICS_COST_MAPPING_MISSING,
                    "marginal_economics_status": ECONOMICS_COST_MAPPING_MISSING,
                    "roi_status": ECONOMICS_COST_MAPPING_MISSING,
                }
            )
        else:
            economics.append(_economic_values(
                spend=float(row["incremental_spend"]),
                response=float(row["incremental_response"]),
                marginal_response=float(
                    row["marginal_incremental_response_per_currency_unit"]
                ),
                value_per_response=value,
                units_valid=row["response_unit"] != "mixed",
                currency_valid=row["spend_unit"] != "mixed",
                near_zero=DEFAULT_NEAR_ZERO,
            ))
    result = pd.concat(
        [result, pd.DataFrame(economics, index=result.index)], axis=1
    )
    # A caller may supply outcome values at aggregation time for a draw table
    # generated without them. For mixed-outcome totals, draw-level component
    # value is authoritative and is summed only when every component is known.
    if values and "outcome_id" in result:
        missing_value = result["incremental_value"].isna()
        result.loc[missing_value, "incremental_value"] = [
            row["incremental_response"]
            * values.get(row.get("outcome_id"), np.nan)
            for _, row in result[missing_value].iterrows()
        ]
        result.loc[missing_value, "marginal_value"] = [
            row["marginal_incremental_response_per_currency_unit"]
            * values.get(row.get("outcome_id"), np.nan)
            for _, row in result[missing_value].iterrows()
        ]
    value_complete = (
        result["incremental_value"].notna()
        & (result["curve_type"] == "monetary")
        & result["cost_mapping_id"].notna()
        & economics_allowed
    )
    result.loc[value_complete & (result["incremental_spend"] > 0), "average_roi"] = (
        result["incremental_value"] / result["incremental_spend"]
    )
    result.loc[value_complete, "marginal_roi"] = result["marginal_value"]
    result.loc[value_complete, "roi_status"] = ECONOMICS_OK
    result.loc[~value_complete, "roi_status"] = ECONOMICS_MISSING_VALUE
    cost_unavailable = (
        (result["curve_type"] != "monetary")
        | result["cost_mapping_id"].isna()
    )
    result.loc[
        cost_unavailable,
        [
            "average_cpa",
            "marginal_cpa",
            "average_roi",
            "marginal_roi",
        ],
    ] = np.nan
    result.loc[
        cost_unavailable,
        [
            "average_economics_status",
            "marginal_economics_status",
            "roi_status",
        ],
    ] = ECONOMICS_COST_MAPPING_MISSING
    if not economics_allowed:
        result.loc[:, ["average_roi", "marginal_roi"]] = np.nan
        result["roi_status"] = ECONOMICS_COMPONENT_COST_UNALLOCATED
    result["counterfactual_incremental_cpa"] = result["average_cpa"]
    result["average_cpa_scope"] = np.where(
        result["counterfactual_media_input"] > 0,
        "relative_to_nonzero_counterfactual",
        "from_zero",
    )
    result["economics_scope"] = (
        "channel_total" if economics_allowed else "decomposition_response_only"
    )
    return result


def aggregate_portfolio_marginal(
    channel_draws: pd.DataFrame,
    perturbation: PortfolioPerturbation,
    *,
    by: Sequence[str],
) -> pd.DataFrame:
    """Directional whole-plan marginal response for an explicit portfolio path."""
    if "portfolio_path_id" not in channel_draws.columns:
        raise ValueError(
            "Portfolio marginal economics require an explicit portfolio_path_id"
        )
    missing = set(channel_draws["channel"]) - set(
        perturbation.allocation_direction
    )
    if missing:
        raise ValueError(
            f"Perturbation is missing allocation shares for {sorted(missing)}"
        )
    data = channel_draws.copy()
    group_cols = list(by) + ["portfolio_path_id", "posterior_draw"]
    if data.duplicated(group_cols + ["channel"]).any():
        raise ValueError(
            "Each portfolio path must define exactly one spend row per channel "
            "and posterior draw"
        )
    data["_weighted_marginal"] = data[
        "marginal_incremental_response_per_currency_unit"
    ] * data["channel"].map(perturbation.allocation_direction)
    result = (
        data.groupby(group_cols, dropna=False, sort=False)
        .agg(
            portfolio_marginal_response=("_weighted_marginal", "sum"),
            total_budget=("spend", "sum"),
        )
        .reset_index()
    )
    result["portfolio_marginal_cpa"] = np.where(
        result["portfolio_marginal_response"] > DEFAULT_NEAR_ZERO,
        1.0 / result["portfolio_marginal_response"],
        np.nan,
    )
    result["portfolio_perturbation_id"] = perturbation.perturbation_id
    result["portfolio_perturbation_method"] = perturbation.method
    result["portfolio_allocation_direction"] = json.dumps(
        dict(perturbation.allocation_direction), sort_keys=True
    )
    return result


def canonical_governance_views(
    draws: pd.DataFrame,
    *,
    value_per_response: Optional[Mapping[str, float]] = None,
) -> Dict[str, pd.DataFrame]:
    """Channel-safe draw-level views; each reports its governance purpose."""
    common = [
        "model_run_id",
        "reference_context_id",
        "market",
        "channel",
        "spend_point",
    ]
    nbt = draws[draws["metric_key"] == "fh_net_billthrough_count"]
    views = {
        "segment": aggregate_curve_draws(
            draws,
            by=common + ["product", "segment", "outcome_id", "metric_key"],
            value_per_response=value_per_response,
        ),
        "product": aggregate_curve_draws(
            draws,
            by=common + ["product", "metric_key"],
            value_per_response=value_per_response,
        ),
        "market_channel_metric": aggregate_curve_draws(
            draws,
            by=common + ["metric_key"],
            value_per_response=value_per_response,
        ),
        "fh_nbt_total": aggregate_curve_draws(
            nbt,
            by=common + ["metric_key"],
            value_per_response=value_per_response,
        ),
        "direct": aggregate_curve_draws(
            draws[draws["component_type"] == "direct"],
            by=common + ["product", "metric_key"],
            value_per_response=value_per_response,
            economics_allowed=False,
        ),
        "halo": aggregate_curve_draws(
            draws[draws["component_type"] == "cross_product"],
            by=common + ["product", "metric_key"],
            value_per_response=value_per_response,
            economics_allowed=False,
        ),
        "headline": aggregate_curve_draws(
            draws,
            by=common + ["product", "metric_key"],
            governance="headline",
            value_per_response=value_per_response,
        ),
        "planning": aggregate_curve_draws(
            draws,
            by=common + ["product", "metric_key"],
            governance="planning",
            value_per_response=value_per_response,
        ),
    }
    for purpose, view in views.items():
        view["governance_view"] = purpose
    return views


def reconcile_curve_to_attribution(
    draws: pd.DataFrame,
    attribution_by_market_channel_outcome: Mapping[
        Tuple[str, str, str], float
    ],
) -> pd.DataFrame:
    """Attach curve-minus-attribution diagnostics under matched assumptions."""
    result = draws.copy()
    result["curve_attribution_reconciliation_error"] = [
        row["channel_total_incremental_response"]
        - attribution_by_market_channel_outcome.get(
            (row["market"], row["channel"], row["outcome_id"]), np.nan
        )
        for _, row in result.iterrows()
    ]
    return result


def summarize_curve_draws(
    draws: pd.DataFrame, cred_mass: float = DEFAULT_CRED_MASS
) -> pd.DataFrame:
    """Posterior summaries after draw-level response/economics calculation."""
    if not 0 < cred_mass < 1:
        raise ValueError("cred_mass must be between zero and one")
    identity = [column for column in IDENTITY_COLUMNS if column in draws.columns]
    if not identity:
        raise ValueError("draws do not contain canonical identity columns")
    tail = (1.0 - cred_mass) / 2.0
    measures = [
        name
        for name in (
            "incremental_response",
            "response",
            "media_eta_contribution",
            "marginal_incremental_response_per_currency_unit",
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
            "curve_attribution_reconciliation_error",
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
    if "incremental_response_posterior_mean" in result:
        result["posterior_mean"] = result[
            "incremental_response_posterior_mean"
        ]
        result["posterior_median"] = result[
            "incremental_response_posterior_median"
        ]
        result["lower_interval"] = result[
            "incremental_response_lower_interval"
        ]
        result["upper_interval"] = result[
            "incremental_response_upper_interval"
        ]
    return result


def export_canonical_curve_bank(
    draws: pd.DataFrame, summaries: pd.DataFrame, directory: Path
) -> Tuple[Path, Path, Path]:
    """Write open draw, summary, and versioned schema artifacts."""
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
                "version": "G2A.2-1",
                "response_definition": (
                    "mu(selected_channel_media_input)"
                    "-mu(counterfactual_channel_media_input)"
                ),
                "curve_types": ["model_input", "monetary"],
                "monetary_economics_requirement": (
                    "approved_effective_market_channel_context_cost_mapping"
                ),
                "component_economics_default": "suppressed_without_cost_allocation",
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
