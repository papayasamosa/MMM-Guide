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
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class PromotionEvent:
    """One promotional event. `segment` is required (not inferred) - which
    segment's promo_coef this event's derived series feeds. `intensity` is
    the weekly series value while the event is active (1.0 for a simple
    on/off flag; a fractional value for a partial-strength promotion)."""

    event_name: str
    start_date: str  # ISO 'YYYY-MM-DD'
    end_date: str
    segment: str
    discount_depth: Optional[float] = None  # e.g. 0.20 for 20% off
    sale_price: Optional[float] = None
    intensity: float = 1.0

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
        return pd.DataFrame(columns=["event_name", "start_date", "end_date", "segment", "discount_depth", "sale_price", "intensity"])
    return pd.DataFrame([e.to_dict() for e in events])
