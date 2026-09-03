"""Analyst-facing Candidate A Search observation boundary.

The Candidate A model consumes an aligned, governed observation bundle.  This
module is the application boundary from an uploaded tidy table to that
existing core contract; it does not derive observations, caps, or demand
values and it never fills missing cells.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ancestry_mmm.core.google_trends_anchor import GoogleTrendsAnchorFitInputs
from ancestry_mmm.core.search_capacity import (
    CandidateASearchFitInputs,
    SearchCandidateASpec,
    SearchCapacityValidationError,
    validate_candidate_a_spec,
)
from ancestry_mmm.core.search_objects import SearchObjectDefinition


CANDIDATE_A_UPLOAD_COLUMNS = (
    "period_start",
    "market",
    "paid_search_delivery",
    "paid_search_cap",
    "organic_search_capture",
    "direct_navigation_capture",
)


def _number_column(frame: pd.DataFrame, name: str) -> np.ndarray:
    values: np.ndarray = np.asarray(
        pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
    )
    if not np.all(np.isfinite(values)):
        raise SearchCapacityValidationError(
            f"Candidate A upload field {name!r} contains blank or non-numeric values"
        )
    if np.any(values < 0):
        raise SearchCapacityValidationError(
            f"Candidate A upload field {name!r} cannot contain negative values"
        )
    return values


def _model_keys(model_frame: Mapping[str, Any]) -> list[tuple[str, str]]:
    frame = model_frame.get("df") if isinstance(model_frame, Mapping) else None
    if not isinstance(frame, pd.DataFrame):
        raise SearchCapacityValidationError(
            "Candidate A upload requires the prepared model frame"
        )
    required = {"period_start", "market"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SearchCapacityValidationError(
            "The prepared model frame is missing alignment fields: "
            + ", ".join(missing)
        )
    periods = pd.to_datetime(frame["period_start"], errors="coerce")
    if periods.isna().any():
        raise SearchCapacityValidationError(
            "The prepared model frame contains invalid period_start values"
        )
    keys = [
        (str(period.date()), str(market).strip())
        for period, market in zip(periods, frame["market"])
    ]
    if any(not market for _, market in keys) or len(set(keys)) != len(keys):
        raise SearchCapacityValidationError(
            "The prepared model frame must have unique period_start/market rows"
        )
    return keys


def build_candidate_a_fit_inputs_from_frame(
    observations: pd.DataFrame,
    *,
    model_frame: Mapping[str, Any],
    spec: SearchCandidateASpec,
    demand_channel_names: Sequence[str],
    search_objects: Sequence[SearchObjectDefinition | Mapping[str, Any]],
    google_trends_anchor: GoogleTrendsAnchorFitInputs | None = None,
) -> CandidateASearchFitInputs:
    """Validate and align an uploaded Candidate A observation table.

    The source is required to contain one exact row for every prepared model
    row.  The cap remains in its governed ``spec.cap_unit`` and is translated
    only by the existing ``cap_to_delivery_scale`` at model execution time.
    """

    if not isinstance(observations, pd.DataFrame):
        raise SearchCapacityValidationError("Candidate A observations must be a table")
    missing = [
        column
        for column in CANDIDATE_A_UPLOAD_COLUMNS
        if column not in observations.columns
    ]
    if missing:
        raise SearchCapacityValidationError(
            "Candidate A upload is missing required fields: " + ", ".join(missing)
        )
    spec_issues = validate_candidate_a_spec(spec, search_objects)
    if spec_issues:
        raise SearchCapacityValidationError(
            "Candidate A specification is not governed: " + "; ".join(spec_issues)
        )

    uploaded = observations.loc[:, list(CANDIDATE_A_UPLOAD_COLUMNS)].copy()
    periods = pd.to_datetime(uploaded["period_start"], errors="coerce")
    if periods.isna().any():
        raise SearchCapacityValidationError(
            "Candidate A period_start must contain valid dates"
        )
    uploaded["period_start"] = periods.dt.date.map(str)
    uploaded["market"] = uploaded["market"].astype(str).str.strip()
    if uploaded["market"].eq("").any():
        raise SearchCapacityValidationError("Candidate A market cannot be blank")
    keys = list(zip(uploaded["period_start"], uploaded["market"]))
    if len(set(keys)) != len(keys):
        raise SearchCapacityValidationError(
            "Candidate A upload must contain one unique row per period_start/market"
        )

    expected_keys = _model_keys(model_frame)
    expected_set = set(expected_keys)
    uploaded_set = set(keys)
    missing_keys = sorted(expected_set - uploaded_set)
    extra_keys = sorted(uploaded_set - expected_set)
    if missing_keys or extra_keys:
        detail = []
        if missing_keys:
            detail.append(f"missing model rows {missing_keys[:5]}")
        if extra_keys:
            detail.append(f"rows outside the model frame {extra_keys[:5]}")
        raise SearchCapacityValidationError(
            "Candidate A upload must align exactly to the prepared model frame: "
            + "; ".join(detail)
        )
    ordered = (
        uploaded.set_index(["period_start", "market"]).loc[expected_keys].reset_index()
    )

    # No hidden resampling: the supplied weekly grid must be explicit and
    # chronological within each market.
    for market, group in ordered.groupby("market", sort=False):
        dates = pd.to_datetime(group["period_start"])
        if len(dates) > 1 and not (dates.diff().dropna() == pd.Timedelta(days=7)).all():
            raise SearchCapacityValidationError(
                f"Candidate A observations for market {market!r} are not a complete weekly grid"
            )

    delivery = _number_column(ordered, "paid_search_delivery")
    cap = _number_column(ordered, "paid_search_cap")
    organic = _number_column(ordered, "organic_search_capture")
    direct = _number_column(ordered, "direct_navigation_capture")
    if np.any(delivery > cap * float(spec.cap_to_delivery_scale) + 1e-8):
        raise SearchCapacityValidationError(
            "paid_search_delivery exceeds paid_search_cap after the governed "
            "cap-to-delivery scale; check cap units and mapping provenance"
        )

    anchor = google_trends_anchor
    if anchor is not None:
        row_weeks = tuple(ordered["period_start"])
        anchor = replace(anchor, model_weeks=row_weeks)

    return CandidateASearchFitInputs(
        spec=spec,
        demand_channel_names=list(demand_channel_names),
        paid_search_delivery=delivery,
        paid_search_cap=cap,
        organic_search_capture=organic,
        direct_navigation_capture=direct,
        search_objects=list(search_objects),
        google_trends_anchor=anchor,
        periods=tuple(ordered["period_start"]),
        markets=tuple(ordered["market"]),
    )


__all__ = [
    "CANDIDATE_A_UPLOAD_COLUMNS",
    "build_candidate_a_fit_inputs_from_frame",
]
