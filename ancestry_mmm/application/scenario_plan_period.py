"""UX-020: derive whether a Scenario Planner plan period lies inside, partly
beyond, or wholly beyond the fitted model's observed data - and what, if
anything, to disclose about it.

Pure, framework-independent derivation (no Streamlit import here), mirroring
``application.curve_annotations``/``application.diagnostics_summary``'s
"derive what to say, let the page draw it" convention, so the date-boundary
logic can be unit-tested directly rather than only through a Streamlit
AppTest driving a date-picker widget.

This module states a fact (part or all of the plan's dates fall after the
last observed period) and reminds the analyst of a mitigation the page
already implements elsewhere (the fitted trend is held flat at its last
observed level for any forecast month; only calendar seasonality varies -
see pages/08_Scenario_Planner.py's "Reference context per month" comment).
It never claims the model is invalid, and never claims future conditions are
known - see docs/decision_log.md's severity-semantics guidance: this is
Information ("the analyst should know this, but it is not a problem"), not a
Warning or a block, and reuses the same "Beyond observed support
(extrapolated)" concept already surfaced on curve pages
(application/curve_annotations.py) rather than inventing new terminology.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import pandas as pd

PLAN_PERIOD_STATUS_IN_SAMPLE = "in_sample"
PLAN_PERIOD_STATUS_PARTIAL_EXTRAPOLATION = "partial_extrapolation"
PLAN_PERIOD_STATUS_FULL_EXTRAPOLATION = "full_extrapolation"


@dataclass(frozen=True)
class PlanPeriodDisclosure:
    """What (if anything) to tell the analyst about how this plan's dates
    relate to the model's observed data. ``message`` is ``None`` exactly
    when ``status == PLAN_PERIOD_STATUS_IN_SAMPLE`` - a fully in-sample plan
    gets no caption at all, so normal, ordinary planning is never
    interrupted by a disclosure that does not apply to it."""

    status: str
    observed_end_date: pd.Timestamp
    plan_start_date: pd.Timestamp
    plan_end_date: pd.Timestamp
    message: Optional[str] = None


def derive_plan_period_disclosure(
    observed_dates: Sequence[object],
    plan_month_dates: Sequence[object],
    *,
    plan_start_label: str,
    plan_end_label: str,
) -> Optional[PlanPeriodDisclosure]:
    """Compare the plan's month range against the latest date actually
    observed in the fitted frame (for the selected market).

    Returns ``None`` only when there is no observed date at all to compare
    against (an edge case that should not occur for a trained model, but is
    handled rather than raising, consistent with this module's siblings).
    Otherwise always returns a ``PlanPeriodDisclosure`` - callers render its
    ``message`` (if not ``None``) and may also want ``observed_end_date`` for
    their own display, matching how Results & Response Curves already
    surfaces "historical average model input as of <date>" reusing an
    already-computed value rather than a new one.
    """
    if len(observed_dates) == 0 or len(plan_month_dates) == 0:
        return None

    observed_end_date = pd.Timestamp(max(observed_dates))
    plan_start_date = pd.Timestamp(plan_month_dates[0])
    plan_end_date = pd.Timestamp(plan_month_dates[-1])

    if plan_start_date > observed_end_date:
        status = PLAN_PERIOD_STATUS_FULL_EXTRAPOLATION
        message = (
            f"This entire plan ({plan_start_label} to {plan_end_label}) is beyond "
            f"the model's observed data (last observed period: "
            f"{observed_end_date:%B %Y}). Every month below holds the fitted trend "
            "flat at its last observed level and reuses the fitted seasonal "
            "pattern - read these outputs as extrapolation beyond the observed "
            "period, not a forecast of future conditions."
        )
    elif plan_end_date > observed_end_date:
        status = PLAN_PERIOD_STATUS_PARTIAL_EXTRAPOLATION
        message = (
            "Part of this plan extends beyond the model's observed data (last "
            f"observed period: {observed_end_date:%B %Y}). Months after that hold "
            "the fitted trend flat at its last observed level and reuse the "
            "fitted seasonal pattern - read those months' outputs as "
            "extrapolation beyond the observed period, not a forecast of future "
            "conditions."
        )
    else:
        status = PLAN_PERIOD_STATUS_IN_SAMPLE
        message = None

    return PlanPeriodDisclosure(
        status=status,
        observed_end_date=observed_end_date,
        plan_start_date=plan_start_date,
        plan_end_date=plan_end_date,
        message=message,
    )
