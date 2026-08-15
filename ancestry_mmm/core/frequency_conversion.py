"""Governed mixed-frequency conversion catalogue and deterministic executor.

This module implements only the method families approved by the WP1 brief.
It is framework-independent and deliberately receives an explicit
``AlignmentSpecification`` plus an explicit value column.  No method is
selected from a column name, source label, or inferred frequency.

The output is a weekly source-scale series.  It is not a model outcome and it
does not change the count-model estimand.  Every execution returns evidence
for the method, version, parameters, source support, release timing, and
reconciliation checks so the official-preparation bundle can preserve the
decision that produced the transformed value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

import numpy as np
import pandas as pd

from .coverage import VARIABLE_CLASSES
from .frequency_alignment import (
    AlignmentSpecification,
    ConversionMethodSpec,
    register_conversion_method,
    resolve_conversion_method,
)

METHOD_APPROVED_BY = "Ancestry MMM WP1 implementation brief"
METHOD_APPROVED_AT = "2026-08-15"
METHOD_VERSION = 1


class FrequencyConversionError(ValueError):
    """Raised when a governed conversion cannot be executed safely."""


@dataclass(frozen=True)
class ConversionExecution:
    """A converted source-scale frame and its auditable evidence."""

    frame: pd.DataFrame
    evidence: dict[str, Any]


def _week_start(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value).normalize()
    return timestamp - pd.Timedelta(days=int(timestamp.weekday()))


def _week_periods(
    target_periods: Sequence[str],
) -> tuple[pd.Timestamp, ...]:
    periods = tuple(sorted({_week_start(value) for value in target_periods}))
    if not periods:
        raise FrequencyConversionError("target_periods must not be empty")
    return periods


def _frequency_period_bounds(
    value: Any, frequency: str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    frequency_key = frequency.strip().lower()
    timestamp = pd.Timestamp(value).normalize()
    if frequency_key == "daily":
        return timestamp, timestamp
    if frequency_key == "weekly":
        start = _week_start(timestamp)
        return start, start + pd.Timedelta(days=6)
    if frequency_key == "monthly":
        period = timestamp.to_period("M")
        return period.start_time.normalize(), period.end_time.normalize()
    if frequency_key == "quarterly":
        period = timestamp.to_period("Q")
        return period.start_time.normalize(), period.end_time.normalize()
    raise FrequencyConversionError(
        f"frequency {frequency!r} has no governed calendar conversion"
    )


def _target_frame(
    target_periods: tuple[pd.Timestamp, ...],
    *,
    date_col: str,
    market_col: Optional[str],
    markets: Sequence[Any],
) -> pd.DataFrame:
    if market_col:
        return pd.DataFrame(
            {
                date_col: [period for period in target_periods for _ in markets],
                market_col: [market for _ in target_periods for market in markets],
            }
        )
    return pd.DataFrame({date_col: list(target_periods)})


def _common_evidence(
    spec: AlignmentSpecification,
    *,
    target_periods: tuple[pd.Timestamp, ...],
    source_rows: int,
    output_rows: int,
    method_notes: str,
) -> dict[str, Any]:
    return {
        "variable_id": spec.variable_id,
        "source_id": spec.source_id,
        "source_version": spec.source_version,
        "market": spec.market,
        "native_frequency": spec.native_frequency,
        "target_frequency": spec.target_frequency,
        "variable_class": spec.variable_class,
        "method_id": spec.method_id,
        "method_version": spec.method_version,
        "parameters": dict(spec.parameters),
        "publication_lag_periods": spec.publication_lag_periods,
        "publication_timing": dict(spec.publication_timing),
        "support_start": spec.support_start,
        "support_end": spec.support_end,
        "effective_start": spec.effective_start,
        "effective_end": spec.effective_end,
        "reconciliation_rule": spec.reconciliation_rule,
        "target_period_start": target_periods[0].strftime("%Y-%m-%d"),
        "target_period_end": target_periods[-1].strftime("%Y-%m-%d"),
        "source_rows": source_rows,
        "output_rows": output_rows,
        "method_notes": method_notes,
    }


def _numeric_series(frame: pd.DataFrame, value_col: str) -> pd.Series:
    if value_col not in frame.columns:
        raise FrequencyConversionError(
            f"source has no governed value column {value_col!r}"
        )
    values = pd.to_numeric(frame[value_col], errors="coerce")
    invalid = frame[value_col].notna() & values.isna()
    if invalid.any():
        raise FrequencyConversionError(
            f"value column {value_col!r} contains non-numeric observations"
        )
    return values


def _validate_source_frame(
    frame: pd.DataFrame,
    *,
    spec: AlignmentSpecification,
    date_col: str,
    value_col: str,
    market_col: Optional[str],
) -> pd.DataFrame:
    required = [date_col, value_col]
    if market_col:
        required.append(market_col)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise FrequencyConversionError(
            f"source is missing governed conversion columns: {missing}"
        )
    typed = frame.copy()
    typed[date_col] = pd.to_datetime(typed[date_col], errors="coerce")
    if typed[date_col].isna().any():
        raise FrequencyConversionError(
            f"source date column {date_col!r} contains invalid dates"
        )
    typed[value_col] = _numeric_series(typed, value_col)
    if market_col and spec.market != "*":
        typed = typed[typed[market_col].astype(str) == str(spec.market)]
    return typed


def _calendar_overlap_allocation(
    frame: pd.DataFrame,
    *,
    spec: AlignmentSpecification,
    date_col: str,
    value_col: str,
    market_col: Optional[str],
    target_periods: tuple[pd.Timestamp, ...],
) -> ConversionExecution:
    rows: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    targets = tuple(
        (period, period + pd.Timedelta(days=6)) for period in target_periods
    )
    for row_number, row in frame.iterrows():
        value = row[value_col]
        source_start, source_end = _frequency_period_bounds(
            row[date_col], spec.native_frequency
        )
        if pd.isna(value):
            continue
        source_days = (source_end - source_start).days + 1
        allocations: list[tuple[pd.Timestamp, float]] = []
        for target_start, target_end in targets:
            overlap_start = max(source_start, target_start)
            overlap_end = min(source_end, target_end)
            overlap_days = (overlap_end - overlap_start).days + 1
            if overlap_days > 0:
                allocations.append(
                    (target_start, float(value) * overlap_days / source_days)
                )
                payload = {
                    "source_row": int(row_number)
                    if isinstance(row_number, (int, np.integer))
                    else str(row_number),
                    "source_period_start": source_start.strftime("%Y-%m-%d"),
                    "source_period_end": source_end.strftime("%Y-%m-%d"),
                    "target_period_start": target_start.strftime("%Y-%m-%d"),
                    "overlap_days": overlap_days,
                    "source_days": source_days,
                }
                reconciliation.append(payload)
        allocated = sum(amount for _, amount in allocations)
        if not np.isclose(allocated, float(value), rtol=1e-10, atol=1e-10):
            raise FrequencyConversionError(
                "calendar overlap allocation did not reconcile the source period "
                f"{source_start.date()} to its source value"
            )
        for target_start, amount in allocations:
            output = {date_col: target_start, value_col: amount}
            if market_col:
                output[market_col] = row[market_col]
            rows.append(output)

    output = pd.DataFrame(
        rows, columns=[date_col] + ([market_col] if market_col else []) + [value_col]
    )
    if not output.empty:
        group_keys = [date_col] + ([market_col] if market_col else [])
        output = output.groupby(group_keys, as_index=False, dropna=False)[
            value_col
        ].sum()
    evidence = _common_evidence(
        spec,
        target_periods=target_periods,
        source_rows=len(frame),
        output_rows=len(output),
        method_notes=(
            "Inclusive calendar-day overlap allocation; every non-missing source "
            "period reconciles to its original source value."
        ),
    )
    evidence["reconciliation"] = reconciliation
    return ConversionExecution(output, evidence)


def _release_date(
    row: pd.Series,
    *,
    spec: AlignmentSpecification,
    date_col: str,
) -> pd.Timestamp:
    release_column = spec.publication_timing.get("release_date_column")
    if release_column:
        if release_column not in row.index:
            raise FrequencyConversionError(
                f"publication timing names missing release column {release_column!r}"
            )
        release = pd.Timestamp(row[release_column])
        if pd.isna(release):
            return pd.NaT
        return release.normalize()
    _, source_end = _frequency_period_bounds(row[date_col], spec.native_frequency)
    if spec.publication_lag_periods == 0:
        return source_end
    frequency_alias = {
        "daily": "D",
        "weekly": "W-SUN",
        "monthly": "M",
        "quarterly": "Q",
    }.get(spec.native_frequency.strip().lower())
    if frequency_alias is None:
        raise FrequencyConversionError(
            f"publication lag has no governed period for {spec.native_frequency!r}"
        )
    shifted = pd.Period(source_end, freq=frequency_alias) + spec.publication_lag_periods
    return shifted.end_time.normalize()


def _release_aware_locf(
    frame: pd.DataFrame,
    *,
    spec: AlignmentSpecification,
    date_col: str,
    value_col: str,
    market_col: Optional[str],
    target_periods: tuple[pd.Timestamp, ...],
) -> ConversionExecution:
    if spec.definition_breaks:
        governed_start = target_periods[0].strftime("%Y-%m-%d")
        governed_end = (target_periods[-1] + pd.Timedelta(days=6)).strftime("%Y-%m-%d")
        crossed = [
            item.break_date
            for item in spec.definition_breaks
            if governed_start <= item.break_date <= governed_end
        ]
        if crossed:
            raise FrequencyConversionError(
                "release-aware LOCF cannot cross an unresolved definition break: "
                + ", ".join(crossed)
            )
    typed = frame.copy()
    typed["__release_date"] = typed.apply(
        lambda row: _release_date(row, spec=spec, date_col=date_col), axis=1
    )
    typed = typed[typed["__release_date"].notna() & typed[value_col].notna()]
    typed = typed.sort_values(["__release_date", date_col])
    markets = [None]
    if market_col:
        markets = list(typed[market_col].drop_duplicates())
        if not markets and spec.market != "*":
            markets = [spec.market]
    rows: list[dict[str, Any]] = []
    for market in markets:
        available = typed if not market_col else typed[typed[market_col] == market]
        for target_start in target_periods:
            target_end = target_start + pd.Timedelta(days=6)
            eligible = available[available["__release_date"] <= target_end]
            output = {date_col: target_start, value_col: np.nan}
            if market_col:
                output[market_col] = market
            if not eligible.empty:
                latest = eligible.iloc[-1]
                output[value_col] = latest[value_col]
                output[f"{value_col}__source_date"] = latest[date_col]
                output[f"{value_col}__release_date"] = latest["__release_date"]
                output[f"{value_col}__age_periods"] = int(
                    (target_start - _week_start(latest[date_col])).days // 7
                )
            rows.append(output)
    output = pd.DataFrame(rows)
    evidence = _common_evidence(
        spec,
        target_periods=target_periods,
        source_rows=len(frame),
        output_rows=len(output),
        method_notes=(
            "Release-aware last observation carried forward; no observation is "
            "used before its release and pre-first-observation periods remain missing."
        ),
    )
    evidence["missing_output_rows"] = int(output[value_col].isna().sum())
    return ConversionExecution(output, evidence)


def _native_cadence_only(
    frame: pd.DataFrame,
    *,
    spec: AlignmentSpecification,
    date_col: str,
    value_col: str,
    market_col: Optional[str],
    target_periods: tuple[pd.Timestamp, ...],
) -> ConversionExecution:
    if spec.native_frequency.strip().lower() != spec.target_frequency.strip().lower():
        raise FrequencyConversionError(
            "native_cadence_only requires native and target frequencies to match"
        )
    typed = frame.copy()
    typed[date_col] = (
        typed[date_col].map(_week_start)
        if spec.target_frequency == "weekly"
        else typed[date_col]
    )
    evidence = _common_evidence(
        spec,
        target_periods=target_periods,
        source_rows=len(frame),
        output_rows=len(typed),
        method_notes="Native cadence retained without imputation or aggregation.",
    )
    return ConversionExecution(typed, evidence)


def _event_alignment(
    frame: pd.DataFrame,
    *,
    spec: AlignmentSpecification,
    date_col: str,
    value_col: str,
    market_col: Optional[str],
    target_periods: tuple[pd.Timestamp, ...],
) -> ConversionExecution:
    parameters = spec.parameters
    event_type = str(parameters.get("event_type", "")).strip().lower()
    if event_type not in {"point", "duration"}:
        raise FrequencyConversionError(
            "event_flag requires parameters.event_type point or duration"
        )
    start_column = str(parameters.get("start_column", date_col))
    end_column = str(parameters.get("end_column", start_column))
    whole_week_column = parameters.get("whole_week_indicator_column")
    if whole_week_column and str(whole_week_column) not in frame.columns:
        raise FrequencyConversionError(
            "event_flag parameters name a missing whole-week indicator column"
        )
    if start_column not in frame.columns or end_column not in frame.columns:
        raise FrequencyConversionError(
            "event_flag parameters name missing start/end columns"
        )
    typed = frame.copy()
    typed[start_column] = pd.to_datetime(typed[start_column], errors="coerce")
    typed[end_column] = pd.to_datetime(typed[end_column], errors="coerce")
    if typed[[start_column, end_column]].isna().any().any():
        raise FrequencyConversionError("event_flag has invalid event dates")
    rows: list[dict[str, Any]] = []
    for _, source in typed.iterrows():
        source_start = source[start_column].normalize()
        source_end = source[end_column].normalize()
        if source_end < source_start:
            raise FrequencyConversionError("event end must not precede event start")
        multiplier = np.nan if pd.isna(source[value_col]) else float(source[value_col])
        whole_week = (
            bool(source[str(whole_week_column)]) if whole_week_column else False
        )
        for target_start in target_periods:
            target_end = target_start + pd.Timedelta(days=6)
            overlap_start = max(source_start, target_start)
            overlap_end = min(source_end, target_end)
            overlap_days = (overlap_end - overlap_start).days + 1
            if overlap_days <= 0:
                continue
            amount = (
                multiplier
                if event_type == "point" or whole_week
                else multiplier * overlap_days / 7.0
            )
            output = {date_col: target_start, value_col: amount}
            if market_col:
                output[market_col] = source[market_col]
            rows.append(output)
    output = pd.DataFrame(
        rows, columns=[date_col] + ([market_col] if market_col else []) + [value_col]
    )
    if not output.empty:
        keys = [date_col] + ([market_col] if market_col else [])
        output = output.groupby(keys, as_index=False, dropna=False)[value_col].sum(
            min_count=1
        )
    evidence = _common_evidence(
        spec,
        target_periods=target_periods,
        source_rows=len(frame),
        output_rows=len(output),
        method_notes=(
            "Point events are placed on their containing Monday week; duration "
            "events use inclusive active-day overlap divided by seven."
        ),
    )
    return ConversionExecution(output, evidence)


def _execute_registered(
    frame: pd.DataFrame,
    *,
    spec: AlignmentSpecification,
    date_col: str,
    value_col: str,
    market_col: Optional[str],
    target_periods: Sequence[str],
) -> ConversionExecution:
    method = resolve_conversion_method(spec.variable_class, spec.method_id)
    if method is None:
        raise FrequencyConversionError(
            f"no approved method is registered for {spec.variable_class!r} / {spec.method_id!r}"
        )
    if spec.method_version is None:
        raise FrequencyConversionError(
            "method_version is required for an executable mixed-frequency method"
        )
    if spec.method_version is not None and spec.method_version != method.version:
        raise FrequencyConversionError(
            f"requested method version {spec.method_version} does not match approved {method.version}"
        )
    if not isinstance(spec.publication_timing, dict):
        raise FrequencyConversionError("publication_timing must be a dictionary")
    unknown_timing = sorted(set(spec.publication_timing) - {"release_date_column"})
    if unknown_timing:
        raise FrequencyConversionError(
            f"publication_timing has unknown key(s): {unknown_timing}"
        )
    validate_conversion_spec(spec)
    typed = _validate_source_frame(
        frame, spec=spec, date_col=date_col, value_col=value_col, market_col=market_col
    )
    periods = _week_periods(target_periods)
    executor = _EXECUTORS.get((method.variable_class, method.method_id, method.version))
    if executor is None:
        raise FrequencyConversionError(
            f"no executor is registered for {method.variable_class!r} / {method.method_id!r} v{method.version}"
        )
    return executor(
        typed,
        spec=spec,
        date_col=date_col,
        value_col=value_col,
        market_col=market_col,
        target_periods=periods,
    )


_EXECUTORS: dict[tuple[str, str, int], Callable[..., ConversionExecution]] = {}

_METHOD_CATALOGUE = {
    "flow_count": ("calendar_overlap_allocation",),
    "stock_level": ("release_aware_locf",),
    "rate_index": ("release_aware_locf",),
    "survey_measurement": ("native_cadence_only", "release_aware_locf"),
    "event_flag": ("calendar_event_alignment",),
}


def validate_conversion_spec(spec: AlignmentSpecification) -> None:
    """Validate method-specific parameters without inspecting source values."""

    method = resolve_conversion_method(spec.variable_class, spec.method_id)
    if method is None:
        raise FrequencyConversionError(
            f"no approved method is registered for {spec.variable_class!r} / {spec.method_id!r}"
        )
    if spec.method_version is None:
        raise FrequencyConversionError(
            "method_version is required for an executable mixed-frequency method"
        )
    if spec.method_version is not None and spec.method_version != method.version:
        raise FrequencyConversionError(
            f"requested method version {spec.method_version} does not match approved {method.version}"
        )
    parameters = spec.parameters
    if not isinstance(parameters, dict):
        raise FrequencyConversionError("parameters must be a dictionary")
    if method.method_id == "calendar_overlap_allocation":
        if set(parameters) - {"source_column"}:
            raise FrequencyConversionError(
                "calendar_overlap_allocation accepts no parameters in WP1"
            )
    elif method.method_id == "release_aware_locf":
        allowed = {"release_basis", "source_column"}
        unknown = sorted(set(parameters) - allowed)
        if unknown:
            raise FrequencyConversionError(
                f"release_aware_locf has unknown parameter(s): {unknown}"
            )
        release_column = spec.publication_timing.get("release_date_column")
        if release_column is not None and not isinstance(release_column, str):
            raise FrequencyConversionError(
                "publication_timing.release_date_column must be a string"
            )
    elif method.method_id == "native_cadence_only":
        if set(parameters) - {"source_column"}:
            raise FrequencyConversionError("native_cadence_only accepts no parameters")
    elif method.method_id == "calendar_event_alignment":
        allowed = {
            "event_type",
            "start_column",
            "end_column",
            "whole_week_indicator_column",
            "source_column",
        }
        unknown = sorted(set(parameters) - allowed)
        if unknown:
            raise FrequencyConversionError(
                f"calendar_event_alignment has unknown parameter(s): {unknown}"
            )
        event_type = str(parameters.get("event_type", "")).strip().lower()
        if event_type not in {"point", "duration"}:
            raise FrequencyConversionError(
                "calendar_event_alignment requires event_type point or duration"
            )
        if event_type == "duration" and not parameters.get("end_column"):
            raise FrequencyConversionError(
                "duration events require an explicit end_column"
            )


def _register(
    *,
    variable_class: str,
    method_id: str,
    description: str,
    executor: Callable[..., ConversionExecution],
) -> None:
    spec = ConversionMethodSpec(
        method_id=method_id,
        version=METHOD_VERSION,
        variable_class=variable_class,
        description=description,
        approved=True,
        approved_by=METHOD_APPROVED_BY,
        approved_at=METHOD_APPROVED_AT,
    )
    _EXECUTORS[(variable_class, method_id, METHOD_VERSION)] = executor
    register_conversion_method(spec, executor=executor)


def ensure_approved_frequency_methods() -> None:
    """Install the WP1 catalogue once, idempotently for app/test processes."""

    expected = {
        (variable_class, method_id)
        for variable_class, method_ids in _METHOD_CATALOGUE.items()
        for method_id in method_ids
    }
    existing = {
        (variable_class, method_id)
        for variable_class, method_id, _version in _EXECUTORS
    }
    if expected <= existing:
        return
    _register(
        variable_class="flow_count",
        method_id="calendar_overlap_allocation",
        description="Allocate flow totals to target weeks by inclusive calendar-day overlap.",
        executor=_calendar_overlap_allocation,
    )
    _register(
        variable_class="stock_level",
        method_id="release_aware_locf",
        description="Carry released stock levels forward without pre-first backfill.",
        executor=_release_aware_locf,
    )
    _register(
        variable_class="rate_index",
        method_id="release_aware_locf",
        description="Carry released rates or indices forward without interpolation.",
        executor=_release_aware_locf,
    )
    _register(
        variable_class="survey_measurement",
        method_id="release_aware_locf",
        description="Carry released survey measurements forward with age evidence.",
        executor=_release_aware_locf,
    )
    _register(
        variable_class="survey_measurement",
        method_id="native_cadence_only",
        description="Retain a survey at its native cadence without conversion.",
        executor=_native_cadence_only,
    )
    _register(
        variable_class="event_flag",
        method_id="calendar_event_alignment",
        description="Place point events and allocate duration events to target weeks.",
        executor=_event_alignment,
    )


def available_method_ids(variable_class: str) -> tuple[str, ...]:
    """Return explicit catalogue choices for the Coverage review UI."""

    if variable_class not in VARIABLE_CLASSES:
        raise FrequencyConversionError(f"unknown variable class {variable_class!r}")
    return tuple(sorted(method_id for method_id in _METHOD_CATALOGUE[variable_class]))


def execute_frequency_conversion(
    frame: pd.DataFrame,
    spec: AlignmentSpecification,
    *,
    date_col: str,
    value_col: str,
    target_periods: Sequence[str],
    market_col: Optional[str] = None,
) -> ConversionExecution:
    """Execute one explicitly specified variable conversion."""

    ensure_approved_frequency_methods()
    if not spec.method_id:
        raise FrequencyConversionError(
            "an explicit method_id is required; variable class and frequency do not select one"
        )
    if spec.target_frequency.strip().lower() != "weekly":
        raise FrequencyConversionError(
            "WP1 official conversion currently targets the governed weekly calendar"
        )
    return _execute_registered(
        frame,
        spec=spec,
        date_col=date_col,
        value_col=value_col,
        market_col=market_col,
        target_periods=target_periods,
    )


__all__ = [
    "ConversionExecution",
    "FrequencyConversionError",
    "available_method_ids",
    "ensure_approved_frequency_methods",
    "execute_frequency_conversion",
    "validate_conversion_spec",
]
