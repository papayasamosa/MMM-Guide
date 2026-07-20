"""
Shared, JSON-serialisable structural schema for the Ancestry FH model.

This is the single definition of "what the model is about" - markets,
segments, channels, DNA halo pathway, promo columns, LTV weights - that
the data pipeline, model builder, attribution, curve bank and scenario
planner all read from. Keeping it as one plain-dict-backed schema (rather
than scattering these choices across pages) is what makes it possible to
serialise a project as human-readable JSON per the persistence requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


DEFAULT_SEGMENTS = ["New", "DNA_CrossSell", "Winback"]


@dataclass
class ModelSpec:
    date_col: str
    market_col: str
    markets: List[str] = field(default_factory=list)
    unpooled_markets: List[str] = field(default_factory=list)

    # segment key -> outcome column name (weekly GSAs for that segment)
    segment_outcomes: Dict[str, str] = field(default_factory=dict)

    channels: List[str] = field(default_factory=list)
    # subset of `channels` treated as DNA-targeted media for the halo pathway
    dna_channels: List[str] = field(default_factory=list)

    # segment key -> promo flag/intensity column (optional per segment)
    promo_cols: Dict[str, str] = field(default_factory=dict)

    # other numeric controls applied to all segments (e.g. consumer confidence)
    control_cols: List[str] = field(default_factory=list)
    # controls that apply to a single segment only, e.g. DNA kit price -> DNA_CrossSell
    segment_control_cols: Dict[str, List[str]] = field(default_factory=dict)

    # segment key -> LTV weight used by the optimiser's value objective
    segment_ltv: Dict[str, float] = field(default_factory=dict)

    aggregation: str = "Weekly"
    seasonal_period: int = 52
    fourier_harmonics: int = 3

    def segments(self) -> List[str]:
        return list(self.segment_outcomes.keys())

    def pooled_markets(self) -> List[str]:
        return [m for m in self.markets if m not in self.unpooled_markets]

    def validate(self) -> List[str]:
        errors = []
        if not self.date_col:
            errors.append("Date column is not set.")
        if not self.markets:
            errors.append("At least one market must be defined.")
        if len(self.segment_outcomes) == 0:
            errors.append("At least one FH segment outcome column must be mapped.")
        if not self.channels:
            errors.append("At least one media channel must be selected.")
        for ch in self.dna_channels:
            if ch not in self.channels:
                errors.append(f"DNA channel '{ch}' is not in the selected channel list.")
        for seg in self.segment_ltv:
            if seg not in self.segment_outcomes:
                errors.append(f"LTV defined for unknown segment '{seg}'.")
        return errors

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelSpec":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
