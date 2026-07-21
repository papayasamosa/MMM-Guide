"""
Generalised outcome schema - PR2 of the DNA/FH architecture work (see the
instruction document's section 4.1: "Refactor the schema so outcomes are
defined using explicit dimensions rather than assuming all outcomes are FH
segments").

Scope boundary (important): this module defines, validates, derives, and
persists outcome definitions. It does **not** change what the fitted model
predicts. A DNA-product `OutcomeDefinition` is captured data, not a modelled
one, until PR3 ("DNA model equations and integrated halo") builds the actual
DNA response equations - see `outcome_is_modelled` below and
`docs/outcomes.md` for the full rationale. Every place this module's output
reaches the UI must show that distinction plainly (Definition of Done: "the
app visibly labels assumptions and limitations") rather than implying a DNA
outcome is already being predicted.

`ModelSpec` (`core.schema`) is unchanged and remains the single source of
truth for what the joint FH model actually fits - `segment_outcomes` there
still means exactly what it always has. `OutcomeDefinition` is an additive,
descriptive catalogue layered on top of it, not a replacement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import pandas as pd

FAMILY_HISTORY = "Family History"
DNA = "DNA"

DNA_SEGMENT_NEW = "New Customer"
DNA_SEGMENT_EXISTING_FH = "Existing FH Customer"
# Fallback when source data can't support the New/Existing split - an
# explicit, visible substitution, not a silent approximation (section 4:
# "Where source data cannot support the two DNA segments, permit a
# configurable single DNA kit outcome and show a visible limitation").
DNA_SEGMENT_COMBINED = "Combined"

KNOWN_PRODUCTS = (FAMILY_HISTORY, DNA)


@dataclass
class OutcomeDefinition:
    """One measurable outcome the business cares about, along explicit
    dimensions rather than an assumed "FH segment" shape - `product`
    distinguishes Family History from DNA, `segment` is the customer
    segment within that product, `metric` is what's being counted
    (e.g. "GSA", "Kit sale"), `column` is the source data column, and
    `value_weight` is an optional per-unit value (LTV for FH, an analogous
    per-kit value for DNA) used by value-weighted optimisation."""

    outcome_id: str
    product: str
    segment: str
    metric: str
    column: str
    value_weight: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeDefinition":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


def outcome_is_modelled(outcome: OutcomeDefinition) -> bool:
    """True if this outcome is actually fed into a fitted model today.
    Only Family History outcomes are - DNA outcomes are captured/persisted
    from PR2 onward but not modelled until PR3's DNA equations land. This is
    the single place that boundary is encoded, so UI/report callers never
    have to hardcode `product == FAMILY_HISTORY` themselves."""
    return outcome.product == FAMILY_HISTORY


def validate_outcome_definitions(outcomes: List[OutcomeDefinition]) -> List[str]:
    errors: List[str] = []
    seen_ids = set()
    for o in outcomes:
        if not o.outcome_id:
            errors.append("Every outcome must have an outcome_id.")
            continue
        if o.outcome_id in seen_ids:
            errors.append(f"Duplicate outcome_id '{o.outcome_id}'.")
        seen_ids.add(o.outcome_id)
        if not o.column:
            errors.append(f"Outcome '{o.outcome_id}' has no source column mapped.")
        if not o.segment:
            errors.append(f"Outcome '{o.outcome_id}' has no segment set.")
        if o.product not in KNOWN_PRODUCTS:
            errors.append(
                f"Outcome '{o.outcome_id}' has unknown product '{o.product}' "
                f"(expected one of {', '.join(KNOWN_PRODUCTS)})."
            )

    dna_segments = {o.segment for o in outcomes if o.product == DNA}
    if DNA_SEGMENT_COMBINED in dna_segments and len(dna_segments) > 1:
        errors.append(
            "A combined DNA outcome cannot be mixed with split New Customer/Existing FH "
            "Customer DNA outcomes - choose one or the other."
        )
    return errors


def fh_outcomes_from_spec(
    segment_outcomes: Dict[str, str], segment_ltv: Optional[Dict[str, float]] = None,
) -> List[OutcomeDefinition]:
    """Derive the Family History OutcomeDefinitions implied by a ModelSpec's
    `segment_outcomes`/`segment_ltv`. This is what makes the outcome
    catalogue backward compatible with every existing FH-only project: a
    project (or an imported bundle) that predates this schema still gets a
    correct, equivalent outcome set, computed here rather than needing to
    have been saved with one explicitly."""
    segment_ltv = segment_ltv or {}
    return [
        OutcomeDefinition(
            outcome_id=f"fh_{seg.lower()}",
            product=FAMILY_HISTORY,
            segment=seg,
            metric="GSA",
            column=col,
            value_weight=segment_ltv.get(seg),
        )
        for seg, col in segment_outcomes.items()
    ]


def dna_outcomes_from_columns(
    new_customer_column: Optional[str] = None,
    existing_fh_column: Optional[str] = None,
    combined_column: Optional[str] = None,
    value_weight_new: Optional[float] = None,
    value_weight_existing: Optional[float] = None,
    value_weight_combined: Optional[float] = None,
) -> List[OutcomeDefinition]:
    """
    Build DNA-product OutcomeDefinitions from mapped data columns.

    The target architecture wants two separate DNA outcomes - kit purchases
    from new customers vs. from existing Family History customers - since
    they have different economics and, once PR3 lands, different halo
    linkages to FH. Where source data can't support that split,
    `combined_column` gives a single DNA outcome instead
    (`DNA_SEGMENT_COMBINED`) - an explicit, visible fallback: its presence
    in the result is the caller's signal to show the corresponding
    limitation, not a silently degraded split.

    `combined_column` takes precedence if given alongside the split
    columns - `validate_outcome_definitions` rejects mixing them, so callers
    should treat this as "either/or" in their own UI too.
    """
    if combined_column:
        return [OutcomeDefinition(
            outcome_id="dna_combined_kit", product=DNA, segment=DNA_SEGMENT_COMBINED,
            metric="Kit sale", column=combined_column, value_weight=value_weight_combined,
        )]

    outcomes = []
    if new_customer_column:
        outcomes.append(OutcomeDefinition(
            outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW,
            metric="Kit sale", column=new_customer_column, value_weight=value_weight_new,
        ))
    if existing_fh_column:
        outcomes.append(OutcomeDefinition(
            outcome_id="dna_existing_fh_kit", product=DNA, segment=DNA_SEGMENT_EXISTING_FH,
            metric="Kit sale", column=existing_fh_column, value_weight=value_weight_existing,
        ))
    return outcomes


def resolve_outcome_definitions(
    outcome_definitions: Optional[List[dict]],
    segment_outcomes: Dict[str, str],
    segment_ltv: Optional[Dict[str, float]] = None,
) -> List[OutcomeDefinition]:
    """
    The single place every caller (UI, report, persistence) goes to get
    "this project's current outcome catalogue". If the project was saved
    with an explicit outcome set (any project that has been through the
    Structure page since this schema shipped), that wins - it already
    includes both the FH outcomes and any mapped DNA outcomes. Otherwise
    (every project created before this schema existed, or that has never
    touched the DNA outcomes section) an equivalent FH-only set is derived
    live from `segment_outcomes`, so a generalised outcome view is available
    for *any* project, not only ones an analyst has explicitly configured
    for it.
    """
    if outcome_definitions:
        return [OutcomeDefinition.from_dict(d) for d in outcome_definitions]
    return fh_outcomes_from_spec(segment_outcomes, segment_ltv)


def outcomes_to_dataframe(outcomes: List[OutcomeDefinition]) -> pd.DataFrame:
    """Flat table for display/export - one row per outcome, with a
    `modelled_today` column so a viewer never has to infer the
    captured-vs-modelled boundary from `product` themselves."""
    if not outcomes:
        return pd.DataFrame(columns=["outcome_id", "product", "segment", "metric", "column", "value_weight", "modelled_today"])
    return pd.DataFrame([
        {**o.to_dict(), "modelled_today": outcome_is_modelled(o)}
        for o in outcomes
    ])
