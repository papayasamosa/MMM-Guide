"""Response-curve annotation derivation (Phase 6 of the Streamlit UI/UX
overhaul - see docs/decision_log.md).

Pure, framework-independent derivation (no Streamlit import here, mirroring
``core.coverage_fabric``/``application.diagnostics_summary``'s "derive what
to say, let the page draw it" convention) of what to annotate directly on a
response-curve chart: the current spend/model-input point, the observed
historical support boundary, average/marginal economics at that point, and
an evidence/status label - so Results & Curve Bank and Official Curve
Generation can draw the same annotation shape from two different evidence
sources without duplicating this logic.

Every field here is read from data a caller already computed
(``core.media_units.compute_cpa_by_product``'s output, a fitted model's own
historical spend/model-input series, ``core.curve_artifact``'s persisted
support snapshot, ``core.evidence_tiers``' evidence tier, or an official
artifact's own ``curve_type``) - this module never invents a "recommended"
point, a composite score, or an economics number that was not already
computed elsewhere.

Two entry points, matching the two curve sources this app has
(docs/decision_log.md's REQ-CURVE-001 "keep the legacy curve bank and the
official artifact store conceptually and visually distinct"):

- ``annotation_from_legacy_curve`` - the exploratory/legacy point-estimate
  curve viewer (``core.predict.generate_channel_curve`` /
  ``core.market_specific_predict.generate_market_channel_curve``), which has
  no governed cost-mapping concept at all; its "spend" axis and CPA are
  shown exactly as this page already, unconditionally, computes and
  displays them elsewhere on the same page (this module adds no new gate to
  pre-existing, already-displayed legacy CPA numbers).
- ``annotation_from_official_support`` - an official curve artifact
  (REQ-CURVE-001), which *does* carry a governed, explicit ``curve_type``
  ("model_input" or "monetary"). Per pages/AGENTS.md's Curve UI rule ("do
  not display monetary CPA/ROI unless a valid monetary mapping exists"),
  economics annotation is only ever populated for ``curve_type="monetary"``;
  a ``curve_type="model_input"`` artifact always reports
  ``monetary_blocked=True`` with an explicit reason instead of silently
  omitting the numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

import pandas as pd


@dataclass(frozen=True)
class CurveAnnotation:
    """What to draw on top of one response curve. Every field is optional -
    a caller with less evidence available simply gets fewer annotations,
    never a fabricated placeholder."""

    current_x: Optional[float] = None
    observed_min: Optional[float] = None
    observed_max: Optional[float] = None
    status_label: Optional[str] = None
    average_economics_label: Optional[str] = None
    marginal_economics_label: Optional[str] = None
    is_extrapolated: Optional[bool] = None
    monetary_blocked: bool = False
    monetary_blocked_reason: Optional[str] = None

    def annotation_lines(self) -> "list[str]":
        """The text lines a chart should overlay, in a fixed, deterministic
        order - never reordered by which fields happen to be populated."""
        lines = []
        if self.status_label:
            lines.append(self.status_label)
        if self.is_extrapolated:
            lines.append("Beyond observed support (extrapolated)")
        if self.average_economics_label:
            lines.append(self.average_economics_label)
        if self.marginal_economics_label:
            lines.append(self.marginal_economics_label)
        if self.monetary_blocked and self.monetary_blocked_reason:
            lines.append(self.monetary_blocked_reason)
        return lines


def _finite_floats(values: Sequence[object]) -> "list[float]":
    out = []
    for v in values:
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def annotation_from_legacy_curve(
    curve_df: pd.DataFrame,
    cpa_df: pd.DataFrame,
    spend_history: Sequence[object],
    *,
    x_col: str = "spend",
    status_label: Optional[str] = None,
) -> CurveAnnotation:
    """Annotation for the exploratory/legacy point-estimate curve viewer.

    ``current_x``/``observed_min``/``observed_max`` are the mean/min/max of
    ``spend_history`` (the fitted model's own historical model-input series
    for this market/channel - the same real observed data every other panel
    on this page already draws from, never a saturation-parameter-derived
    range - see root AGENTS.md "do not fabricate observed support from a
    posterior saturation parameter"). Economics labels are read from
    ``cpa_df`` (``core.media_units.compute_cpa_by_product``'s existing,
    already-displayed output) at the curve point nearest ``current_x`` -
    never recomputed here.
    """
    hist = _finite_floats(spend_history)
    if not hist:
        return CurveAnnotation(status_label=status_label)

    current_x = sum(hist) / len(hist)
    observed_min, observed_max = min(hist), max(hist)

    avg_label = marginal_label = None
    if (
        cpa_df is not None
        and not cpa_df.empty
        and x_col in cpa_df.columns
        and "avg_cpa" in cpa_df.columns
    ):
        nearest_idx = (cpa_df[x_col] - current_x).abs().idxmin()
        row = cpa_df.loc[nearest_idx]
        avg = row.get("avg_cpa")
        if avg is not None and not pd.isna(avg):
            avg_label = f"Average CPA at current spend: {float(avg):,.2f}"
        marginal = row.get("marginal_cpa")
        if marginal is not None and not pd.isna(marginal):
            marginal_label = f"Marginal CPA at current spend: {float(marginal):,.2f}"

    is_extrapolated: Optional[bool] = None
    if curve_df is not None and not curve_df.empty and x_col in curve_df.columns:
        curve_max = _finite_floats(curve_df[x_col].tolist())
        if curve_max:
            is_extrapolated = max(curve_max) > observed_max

    return CurveAnnotation(
        current_x=current_x,
        observed_min=observed_min,
        observed_max=observed_max,
        status_label=status_label,
        average_economics_label=avg_label,
        marginal_economics_label=marginal_label,
        is_extrapolated=is_extrapolated,
    )


def annotation_from_official_support(
    support_snapshot_rows: Sequence[Mapping[str, object]],
    market: str,
    channel: str,
    *,
    curve_type: str,
    economics_row: Optional[Mapping[str, object]] = None,
    status_label: Optional[str] = None,
) -> CurveAnnotation:
    """Annotation for an official curve artifact (REQ-CURVE-001).

    ``support_snapshot_rows`` is the artifact's own persisted
    ``support_snapshot["rows"]`` (immutable creation-time evidence - see
    ``core.curve_artifact.CurveArtifactMetadata``); ``economics_row`` is one
    row of the artifact's ``summaries`` table for this (market, channel),
    already carrying ``average_cpa``/``marginal_cpa``. Economics is only
    ever populated when ``curve_type == "monetary"`` - a model-input
    artifact reports ``monetary_blocked=True`` with an explicit reason
    instead (pages/AGENTS.md Curve UI rule: never display monetary CPA/ROI
    without a valid monetary mapping).
    """
    if curve_type not in {"model_input", "monetary"}:
        raise ValueError("curve_type must be 'model_input' or 'monetary'")

    row = next(
        (
            r
            for r in support_snapshot_rows
            if r.get("market") == market and r.get("channel") == channel
        ),
        None,
    )

    current_x = observed_min = observed_max = None
    is_extrapolated: Optional[bool] = None
    if row is not None:
        current_x = _first_finite(row.get("current"))
        observed_min = _first_finite(row.get("observed_min"))
        observed_max = _first_finite(row.get("observed_max"))
        raw_extrapolated = row.get("is_extrapolated")
        is_extrapolated = (
            bool(raw_extrapolated) if raw_extrapolated is not None else None
        )

    avg_label = marginal_label = None
    monetary_blocked = False
    monetary_blocked_reason: Optional[str] = None
    if curve_type == "monetary":
        if economics_row is not None:
            avg = economics_row.get("average_cpa")
            if avg is not None and not pd.isna(avg):
                avg_label = f"Average CPA at current spend: {float(avg):,.2f}"  # type: ignore[arg-type]
            marginal = economics_row.get("marginal_cpa")
            if marginal is not None and not pd.isna(marginal):
                marginal_label = (
                    f"Marginal CPA at current spend: {float(marginal):,.2f}"  # type: ignore[arg-type]
                )
    else:
        monetary_blocked = True
        monetary_blocked_reason = (
            "Model-input curve - no cost mapping applied; monetary CPA/ROI is "
            "not shown (pages/AGENTS.md Curve UI rule)."
        )

    return CurveAnnotation(
        current_x=current_x,
        observed_min=observed_min,
        observed_max=observed_max,
        status_label=status_label,
        average_economics_label=avg_label,
        marginal_economics_label=marginal_label,
        is_extrapolated=is_extrapolated,
        monetary_blocked=monetary_blocked,
        monetary_blocked_reason=monetary_blocked_reason,
    )


def _first_finite(value: object) -> Optional[float]:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None
