"""
Structured DNA promotion events - the DNA/FH architecture work's explicit
promotion requirement: "DNA promotions must support event name, start and
end dates, discount depth, sale price, promotion duration, interaction with
customer segment where justified. Do not allow promotion spikes to be
absorbed automatically into media."

A `PromotionEvent` describes one promotional event with real business
metadata, rather than requiring an analyst to hand-engineer a 0/1 flag
column before they can capture it. `promotion_weekly_series` derives that
flag/intensity series from the event calendar for a given date range;
`apply_promotion_events_to_frame` materialises one derived column per
segment that has events, so it can be plugged straight into
`ModelSpec.promo_cols` exactly like a hand-built column would be. Promo is
a structurally separate additive term from media response in both PyMC
model builders (`core.hierarchical_model`, `core.market_specific_model`),
so a promotion's effect - whether captured as a hand-built column or a
`PromotionEvent`-derived one - is never silently absorbed into a segment's
media coefficients; that separation is what "do not allow promotion spikes
to be absorbed automatically into media" means mechanically.

Not FH-specific - nothing here assumes a DNA segment - but this module
exists because DNA promotions were the first place a structured event
calendar (vs. a plain flag column) was actually required (docs/outcomes.md,
docs/dna_fh_causal_structure.md).

**Replayable pipeline steps (PR E.2 requirement #11):** the confirmed
pitfall this closes is that promotion events used to modify
`transformed_data` directly from the Structure page - a one-way mutation,
not reproducible from anything durable. `event_id`/`product`/
`affected_outcome_ids`/`market`/`transformation_version` (below) make each
event a stable, versioned unit; `promotion_events_to_transform_steps`/
`transform_steps_to_promotion_events` convert to/from
`data.pipeline.TransformStep(op="promotion_event", ...)` entries in the
same `pipeline_steps` list the rest of the transform pipeline uses, so
re-importing a project (or refreshing raw data) can *replay* the event
list to reproduce the derived promo columns, rather than trusting whatever
values happen to already be sitting in an exported parquet.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from ..data.pipeline import TransformStep

# Schema version for the promotion-event pipeline-step encoding - bumped
# whenever the fields captured or their replay semantics change, so a step
# written by an older version of this codebase can be told apart from the
# current one (docs/decision_log.md's "explicit migration, not silent
# reinterpretation" convention).
PROMOTION_EVENT_TRANSFORMATION_VERSION = 1


def _new_event_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class PromotionEvent:
    """One promotional event. `segment` is required (not inferred) - which
    segment's promo_coef this event's derived series feeds. `intensity` is
    the weekly series value while the event is active (1.0 for a simple
    on/off flag; a fractional value for a partial-strength promotion).

    `event_id` is this event's stable identity (auto-generated if left
    blank) - what a re-save/re-import matches on to update rather than
    duplicate an event, distinct from `event_name` (a free-text display
    label that can change without changing identity). `product`/
    `affected_outcome_ids`/`market` are optional, more precise targeting
    than the legacy `segment` string alone - `affected_outcome_ids`, once
    set, is what `promotion_weekly_series` prefers when deriving which
    outcome_ids' promo columns this event should feed (see that function).
    `transformation_version` records which version of this encoding/replay
    semantics produced this event, for forward compatibility."""

    event_name: str
    start_date: str  # ISO 'YYYY-MM-DD'
    end_date: str
    segment: str
    discount_depth: Optional[float] = None  # e.g. 0.20 for 20% off
    sale_price: Optional[float] = None
    intensity: float = 1.0
    event_id: str = field(default_factory=_new_event_id)
    product: Optional[str] = None
    affected_outcome_ids: List[str] = field(default_factory=list)
    market: Optional[str] = None
    transformation_version: int = PROMOTION_EVENT_TRANSFORMATION_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PromotionEvent":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def duration_days(self) -> Optional[int]:
        try:
            return int((pd.Timestamp(self.end_date) - pd.Timestamp(self.start_date)).days) + 1
        except (ValueError, TypeError):
            return None

    def validate(self) -> List[str]:
        errors = []
        if not self.event_name:
            errors.append("Every promotion event needs a name.")
        label = self.event_name or "(unnamed)"
        if not self.segment:
            errors.append(f"Promotion '{label}' has no segment set.")
        try:
            start, end = pd.Timestamp(self.start_date), pd.Timestamp(self.end_date)
            if end < start:
                errors.append(f"Promotion '{label}' end date is before its start date.")
        except (ValueError, TypeError):
            errors.append(f"Promotion '{label}' has an unparseable start/end date.")
        if self.discount_depth is not None and not (0.0 <= self.discount_depth <= 1.0):
            errors.append(f"Promotion '{label}' discount_depth should be a 0-1 fraction, got {self.discount_depth}.")
        return errors


def validate_promotion_events(events: List[PromotionEvent]) -> List[str]:
    errors: List[str] = []
    for e in events:
        errors.extend(e.validate())
    return errors


def promotion_weekly_series(events: List[PromotionEvent], dates, segment: str) -> np.ndarray:
    """
    Weekly promo intensity series for `segment` over `dates` (any date-like
    array/Series/Index) - 0.0 for periods outside every applicable event's
    `[start_date, end_date]` window, else the sum of every active event's
    `intensity`. Overlapping promotions for the same segment compound
    (summed), an explicit choice rather than one silently masking another.
    """
    dates_arr = pd.to_datetime(pd.Series(list(dates))).to_numpy()
    series = np.zeros(len(dates_arr), dtype=float)
    for e in events:
        if e.segment != segment:
            continue
        start = pd.Timestamp(e.start_date).to_datetime64()
        end = pd.Timestamp(e.end_date).to_datetime64()
        mask = (dates_arr >= start) & (dates_arr <= end)
        series[mask] += e.intensity
    return series


def apply_promotion_events_to_frame(
    df: pd.DataFrame, date_col: str, events: List[PromotionEvent], column_prefix: str = "_promo_event_",
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    Materialise one derived promo column per segment that has events, so it
    can be plugged straight into `ModelSpec.promo_cols[segment]` exactly
    like a hand-built flag column. Returns `(df_with_derived_columns,
    {segment: derived_column_name})`. `df` is not mutated - a copy with the
    new columns is returned. A segment with no events gets no column (and
    no entry in the returned mapping) - `promo_cols` simply omits it, same
    as "no promo mapped" today.
    """
    segments = sorted({e.segment for e in events})
    out = df.copy()
    column_by_segment: Dict[str, str] = {}
    for seg in segments:
        col_name = f"{column_prefix}{seg}"
        out[col_name] = promotion_weekly_series(events, out[date_col], seg)
        column_by_segment[seg] = col_name
    return out, column_by_segment


def promotion_events_to_dataframe(events: List[PromotionEvent]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(columns=list(PromotionEvent.__dataclass_fields__))
    return pd.DataFrame([e.to_dict() for e in events])


# ---------------------------------------------------------------------------
# Replayable pipeline steps (PR E.2 requirement #11)
# ---------------------------------------------------------------------------

PROMOTION_EVENT_OP = "promotion_event"


def promotion_events_to_transform_steps(
    events: List[PromotionEvent], date_col: str, column_prefix: str = "_promo_event_",
) -> List["TransformStep"]:
    """
    Encode each event as one `TransformStep(op="promotion_event", ...)`, in
    the same `pipeline_steps` list the rest of the transform pipeline uses.
    One step per event (not one step per segment) - `event_id` is each
    step's stable identity, so re-saving the same event updates its step in
    place (see the Structure page's save handler) rather than duplicating
    it. `apply_step` gives every event op a matching derived column name
    (`{column_prefix}{segment}`) and adds to it, so events replay with the
    same compounding-overlap semantics as `promotion_weekly_series`.
    """
    from ..data.pipeline import TransformStep

    steps = []
    for e in events:
        steps.append(
            TransformStep(
                op=PROMOTION_EVENT_OP,
                params={"event": e.to_dict(), "date_col": date_col, "column_prefix": column_prefix},
                description=f"Promotion event: {e.event_name or '(unnamed)'} ({e.segment})",
            )
        )
    return steps


def transform_steps_to_promotion_events(steps: List["TransformStep"]) -> List[PromotionEvent]:
    """Recover the `PromotionEvent` list encoded by `promotion_events_to_transform_steps`,
    ignoring any non-`promotion_event` steps in the same pipeline."""
    return [
        PromotionEvent.from_dict(step.params["event"])
        for step in steps
        if step.op == PROMOTION_EVENT_OP
    ]
