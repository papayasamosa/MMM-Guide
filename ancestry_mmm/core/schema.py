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
    # explicit outcome_id of the Family History DNA cross-sell outcome (the
    # halo pathway's traditional target) - PR E.1 replaces substring-based
    # inference ("the first outcome_id containing 'dna'") with this required,
    # validated field (core.outcomes.validate_fh_dna_cross_sell_outcome_id).
    # None until configured on the Structure page, or for legacy projects
    # that haven't been migrated yet.
    fh_dna_cross_sell_outcome_id: Optional[str] = None

    # segment key -> promo flag/intensity column (optional per segment) - LEGACY:
    # PR E.2 replaces this as the primary mapping with `outcome_promo_cols`
    # (outcome_id-keyed); kept only so every outcome sharing a legacy segment
    # doesn't lose its promo mapping on migration. An outcome_id present in
    # `outcome_promo_cols` always overrides this for that outcome_id.
    promo_cols: Dict[str, str] = field(default_factory=dict)
    # outcome_id -> promo flag/intensity column (PR E.2, canonical) - unlike
    # `promo_cols`, a sign-up and a GSA sharing a segment can have genuinely
    # different promo mappings (different business definition or timing).
    outcome_promo_cols: Dict[str, str] = field(default_factory=dict)

    # other numeric controls applied to all segments (e.g. consumer confidence)
    control_cols: List[str] = field(default_factory=list)
    # product ("Family History"/"DNA") -> controls applied to every outcome
    # of that product (PR E.2) - a level between global control_cols and
    # outcome-specific ones.
    product_control_cols: Dict[str, List[str]] = field(default_factory=dict)
    # controls that apply to a single segment only, e.g. DNA kit price -> DNA_CrossSell -
    # LEGACY: PR E.2 replaces this as the primary mapping with
    # `outcome_control_cols` (outcome_id-keyed); kept for migration. Both are
    # additive with `control_cols`/`product_control_cols` for a given
    # outcome_id, not mutually exclusive.
    segment_control_cols: Dict[str, List[str]] = field(default_factory=dict)
    # outcome_id -> extra controls specific to that exact outcome (PR E.2,
    # canonical) - e.g. a sign-up outcome needing a different competitive
    # control than its sibling GSA outcome on the same segment.
    outcome_control_cols: Dict[str, List[str]] = field(default_factory=dict)

    # segment key -> LTV weight used by the optimiser's value objective -
    # LEGACY migration field; `OutcomeDefinition.value_weight` (per
    # outcome_id, in the canonical outcome catalogue) is the actual source
    # of truth since PR E.1.
    segment_ltv: Dict[str, float] = field(default_factory=dict)

    aggregation: str = "Weekly"
    seasonal_period: int = 52
    fourier_harmonics: int = 3

    def segments(self) -> List[str]:
        return list(self.segment_outcomes.keys())

    def pooled_markets(self) -> List[str]:
        return [m for m in self.markets if m not in self.unpooled_markets]

    def validate(self) -> List[str]:
        """
        `segment_outcomes` is deliberately NOT required here (PR E.2 -
        "the canonical outcome catalogue is the primary Structure workflow,
        not a required legacy GSA mapping"): a sign-up-only or GSA-only
        project may have an empty `segment_outcomes` and still be perfectly
        valid, since the actual fitting source of truth is the outcome
        catalogue (`core.outcomes.OutcomeDefinition` list, validated
        separately via `validate_outcome_definitions` - the Structure page
        combines both error lists). `segment_outcomes` survives only as a
        migration source for `fh_outcomes_from_spec` and the "Create
        standard FH GSA outcomes" quick-start wizard.
        """
        errors = []
        if not self.date_col:
            errors.append("Date column is not set.")
        if not self.markets:
            errors.append("At least one market must be defined.")
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
