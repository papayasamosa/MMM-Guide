"""
Generalised outcome schema (see the instruction document's section 4.1:
"Refactor the schema so outcomes are defined using explicit dimensions
rather than assuming all outcomes are FH segments").

This module defines, validates, derives, and persists outcome definitions.
It does not itself change `ModelSpec` (`core.schema`) - `segment_outcomes`
there still means exactly what it always has, and `OutcomeDefinition` is an
additive, descriptive catalogue layered on top of it, not a replacement.

A DNA-product `OutcomeDefinition` is opt-in, not automatic: once mapped on
Structure: Segments & Markets, it is picked up automatically the next time
the modelling frame is prepared on Model Configuration
(`core.outcomes.dna_kit_outcome_columns` -> `data.preprocessor.
prepare_fh_modeling_frame`'s `dna_kit_outcomes` parameter -> `core.
hierarchical_model.build_fh_hierarchical_model`'s `direct_dna_segments`),
where DNA-targeted media gets full direct response on it, not the shrunk
halo pathway other segments get - see docs/dna_fh_causal_structure.md.
`outcome_requires_opt_in` below reflects that opt-in distinction: Family
History segments are always part of every fit; DNA-product segments are
only part of a fit an analyst has actually configured for them by mapping
DNA columns. `outcome_status`/`outcome_was_modelled` answer the separate,
run-aware question of whether a *specific* outcome was actually included
in a *specific* fitted model, rather than collapsing "requires opt-in" and
"was modelled this run" into one boolean (docs/decision_log.md).
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
    (e.g. "GSA", "Kit sale"), `column` is the source data column, `unit` is
    the counting unit this outcome's raw numbers are in (derived from
    `product` if not given explicitly - see `__post_init__` - so a GSA is
    never silently added to a kit sale as if they were the same unit
    anywhere that reads `unit`), `value_weight` is an optional per-unit
    value (LTV for FH, an analogous per-kit value for DNA) used by
    value-weighted optimisation, and `role` distinguishes an outcome that
    counts toward this product's official totals/objectives ("primary",
    the default - every outcome today) from one that doesn't (reserved for
    a future diagnostic/secondary-outcome distinction; the total-building
    helpers in `core.attribution`/`core.market_specific_attribution` filter
    on it already, so a non-"primary" outcome added later is excluded from
    totals without needing those helpers changed again)."""

    outcome_id: str
    product: str
    segment: str
    metric: str
    column: str
    unit: str = ""
    value_weight: Optional[float] = None
    role: str = "primary"

    def __post_init__(self) -> None:
        if not self.unit:
            self.unit = "GSA" if self.product == FAMILY_HISTORY else "kit"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeDefinition":
        # Migration: bundles saved before `unit`/`role` existed simply don't
        # have those keys - the dataclass defaults (derived `unit`, "primary"
        # `role`) apply automatically, so an old bundle loads as an
        # equivalent, correctly-classified outcome rather than erroring or
        # needing an explicit migration step.
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


def outcome_requires_opt_in(outcome: OutcomeDefinition) -> bool:
    """True if this outcome needs an explicit mapping step before it can
    ever be part of a fit - DNA-product outcomes do (see the module
    docstring); Family History outcomes never do, they're always part of
    every fit with no extra configuration. This answers "does this outcome
    *type* require an extra step" - a static, catalogue-level question. It
    does NOT answer "was this specific outcome actually included in a
    specific fitted run" - that's `outcome_was_modelled`, which needs an
    actual `FHModelMeta` to check against. Collapsing these two questions
    into one boolean (the pre-existing `outcome_is_modelled`, removed) was
    misleading: it read as answering the run-aware question but only ever
    answered the static one - see docs/outcomes.md and docs/decision_log.md."""
    return outcome.product != FAMILY_HISTORY


def outcome_was_modelled(outcome: OutcomeDefinition, model_meta: Optional[object]) -> bool:
    """True if `outcome`'s segment is actually present in a *specific
    fitted* model's segment set - the run-aware counterpart to
    `outcome_requires_opt_in`. Pass the `FHModelMeta` of the trace actually
    being displayed or reported on; `None` (no fitted model this session,
    or none loaded) always returns False, never a guess."""
    if model_meta is None:
        return False
    return outcome.segment in model_meta.segments


OUTCOME_STATUSES = (
    "Configured",
    "Included in prepared frame",
    "Included in fitted run",
    "Missing source column",
    "Excluded",
    "Stale after configuration changes",
)


def outcome_status(
    outcome: OutcomeDefinition,
    *,
    excluded: bool = False,
    available_columns: Optional[set] = None,
    frame_segments: Optional[List[str]] = None,
    model_meta_segments: Optional[List[str]] = None,
) -> str:
    """
    Exactly one of `OUTCOME_STATUSES` - never collapsed into a single
    boolean (the instruction document's explicit ask, docs/decision_log.md).

    `available_columns`: the *current* data's column names, to detect a
    mapped column that no longer exists. `frame_segments`/
    `model_meta_segments`: the segment sets of whatever's *currently*
    prepared/fitted this session, if anything - not necessarily built from
    this exact outcome catalogue, which is what lets "stale" be detected: a
    column that used to back a prepared-or-fitted outcome and has since
    vanished from the data is a configuration-drift signal ("stale"), not a
    fresh gap ("missing source column", never yet prepared or fit at all).

    Known limitation: staleness is detected by the *column disappearing*,
    not by the mapping changing to a different (still-present) column -
    that would need the exact column used at fit time recorded on
    `FHModelMeta`, which it isn't today. Documented, not silently assumed
    away - see docs/dna_fh_causal_structure.md.
    """
    was_fit = model_meta_segments is not None and outcome.segment in model_meta_segments
    was_prepared = frame_segments is not None and outcome.segment in frame_segments
    column_missing = available_columns is not None and outcome.column not in available_columns

    if column_missing:
        return "Stale after configuration changes" if (was_fit or was_prepared) else "Missing source column"
    if excluded:
        return "Excluded"
    if was_fit:
        return "Included in fitted run"
    if was_prepared:
        return "Included in prepared frame"
    return "Configured"


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


def dna_kit_outcome_columns(outcomes: List[OutcomeDefinition]) -> Dict[str, str]:
    """
    `{segment: column}` for every DNA-product outcome in `outcomes` - the
    shape `data.preprocessor.prepare_fh_modeling_frame`'s `dna_kit_outcomes`
    parameter and `core.hierarchical_model.build_fh_hierarchical_model`'s
    `direct_dna_segments` (via `list(...)`) both expect, so a project's
    saved outcome catalogue can be fed straight into model fitting without
    the analyst mapping DNA columns a second time.
    """
    return {o.segment: o.column for o in outcomes if o.product == DNA}


def outcomes_to_dataframe(
    outcomes: List[OutcomeDefinition],
    *,
    excluded_outcome_ids: Optional[List[str]] = None,
    available_columns: Optional[set] = None,
    frame_segments: Optional[List[str]] = None,
    model_meta_segments: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Flat table for display/export - one row per outcome, with a `status`
    column (one of `OUTCOME_STATUSES`) instead of a single collapsed
    boolean, so a viewer never has to infer the captured-vs-modelled
    boundary from `product` themselves, and can actually tell "mapped but
    never fit" from "fit in the currently-loaded model" from "used to be
    fit, now stale". All keyword args are optional and independently
    omittable - passing none of them still gives every outcome a status
    ("Configured" or "Excluded"), just without the frame/fit/column context
    to distinguish the other four."""
    excluded_ids = set(excluded_outcome_ids or [])
    if not outcomes:
        return pd.DataFrame(columns=["outcome_id", "product", "segment", "metric", "column", "unit", "value_weight", "role", "status"])
    return pd.DataFrame([
        {
            **o.to_dict(),
            "status": outcome_status(
                o, excluded=o.outcome_id in excluded_ids, available_columns=available_columns,
                frame_segments=frame_segments, model_meta_segments=model_meta_segments,
            ),
        }
        for o in outcomes
    ])
