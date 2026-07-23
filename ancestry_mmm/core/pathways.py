"""
Explicit media-to-outcome pathway catalogue (PR F).

The confirmed pitfall this replaces: `ModelSpec.dna_channels` (plus
`FHModelMeta.direct_dna_outcome_ids`/`kit_only_outcome_ids`/
`halo_eligible_outcome_ids`) is currently the *only* structural statement
this codebase makes about which channels drive which outcomes through which
causal pathway - and it only distinguishes "direct" vs. "halo" for DNA
media. There is no explicit catalogue of every `(channel, target outcome)`
relationship this project believes exists, what kind of relationship it is
(a primary direct effect, a cross-product halo, a speculative/exploratory
effect not yet trusted for planning), or how confident the evidence for it
is. `MediaOutcomePathway` is that catalogue.

**PR F built this module as schema, validation, persistence, fingerprinting
and fit-time metadata only - nothing read it to change fitting.** PR G1
("segment-level estimation and curve correctness" - docs/decision_log.md)
makes it operational: `resolve_pathway_masks` below is what both PyMC model
builders (`core.hierarchical_model`, `core.market_specific_model`) now call
to decide, per `(outcome, channel)` cell, whether that channel's response
for that outcome is a normal-strength `primary_direct` effect, a
tighter-but-real `active_cross_product` effect, a strongly-shrunk
`exploratory_cross_product` effect, or `excluded` (zero contribution,
deterministically - not just a tight prior). `core.predict`/
`core.market_specific_predict`/`core.attribution`/
`core.market_specific_attribution` call the same function to replay the
identical structure in NumPy, so a fitted model's curves/attribution/
scenario numbers can never silently diverge from what was actually fit -
see docs/media_outcome_pathways.md and docs/decision_log.md's PR G1 entry
for the full design record, including the deliberate backward-compatibility
guarantee (a project with no pathway catalogue configured for a given cell
gets exactly the same legacy DNA-direct/halo-or-unconstrained-primary
default this codebase has always used).

Deliberately designed against the *expanded* future outcome catalogue (net
bill-through, finance-date GSA, DNA purchase-type segmentation - see
core.outcomes' "planned metric keys" and docs/media_outcome_pathways.md),
not just today's `fh_gsa`/generic DNA-kit outcomes: `target_outcome_id` is
validated against whatever outcome_ids a project's *current* catalogue
actually has, so a pathway can target `fh_net_billthrough_count` or
`dna_kit_sale_self_activated` today, the moment an analyst has captured an
`OutcomeDefinition` for one (even manually, ahead of any dedicated
transformation existing) - nothing here hard-codes "every FH KPI is GSA" or
"every DNA KPI is a generic kit-sale total".
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from .outcomes import DNA, FAMILY_HISTORY, KNOWN_PRODUCTS

# ---------------------------------------------------------------------------
# Pathway role vocabulary (matches the roadmap's "PR F: pathway catalogue"
# section verbatim)
# ---------------------------------------------------------------------------

PATHWAY_ROLE_PRIMARY_DIRECT = "primary_direct"
PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT = "active_cross_product"
PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT = "exploratory_cross_product"
PATHWAY_ROLE_EXCLUDED = "excluded"

PATHWAY_ROLES = (
    PATHWAY_ROLE_PRIMARY_DIRECT,
    PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
    PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT,
    PATHWAY_ROLE_EXCLUDED,
)

# Suggested values for the UI - not a closed, validated vocabulary (the
# roadmap doesn't specify one for either field, unlike `role` above).
LAG_TYPES = ("none", "fixed_weeks", "adstock_only", "delayed_adstock")
EVIDENCE_STATUSES = (
    "business_assumption", "experiment_supported", "model_supported",
    "weak_evidence", "contradicted", "unreviewed",
)
LEGACY_EVIDENCE_STATUSES = ("untested", "supported", "inconclusive")
COMPONENT_TYPES = ("direct", "cross_product", "mediated", "excluded")
SUGGESTED_LAG_TYPES = LAG_TYPES
SUGGESTED_EVIDENCE_STATUSES = EVIDENCE_STATUSES

# Ancestry's documented default pathway expectations (roadmap "PR F: pathway
# catalogue" section) - reference data for the UI's quick-start defaults,
# not enforced by validation (an analyst's actual data may differ).
DEFAULT_PATHWAY_EXPECTATIONS = (
    {"source_product": DNA, "role": PATHWAY_ROLE_PRIMARY_DIRECT, "description": "DNA media -> DNA kits"},
    {"source_product": DNA, "role": PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT, "description": "DNA media -> FH outcomes (delayed halo)"},
    {"source_product": FAMILY_HISTORY, "role": PATHWAY_ROLE_PRIMARY_DIRECT, "description": "FH media -> FH outcomes"},
    {"source_product": FAMILY_HISTORY, "role": PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT, "description": "FH media -> DNA kits (tight prior, planning=false)"},
)


def _new_pathway_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class MediaOutcomePathway:
    """One declared `(channel, target_outcome_id)` causal relationship this
    project believes exists, with an explicit role, lag treatment, prior
    tightness, and attribution/planning eligibility - never inferred from
    channel naming or `dna_channels` membership alone.

    `pathway_id` is this pathway's stable identity (auto-generated if left
    blank) - what a re-save matches on to update in place rather than
    duplicate, and what drift detection (`pathway_drift_status`) compares
    across a fit. `channel`/`source_product` describe which media is doing
    the influencing; `target_outcome_id` is the outcome_id it's believed to
    affect - validated against the project's *current* outcome catalogue
    (`validate_media_outcome_pathways`), so this can reference any outcome
    the catalogue has, including the planned net-bill-through/DNA
    purchase-type metrics. `role` is one of `PATHWAY_ROLES`:
    `primary_direct` (the channel's own product's main effect),
    `active_cross_product` (a trusted, currently-estimated cross-product
    effect, e.g. DNA media's halo onto FH), `exploratory_cross_product` (a
    speculative effect under a tight prior, not yet trusted for planning -
    `include_in_planning` should be `False`), or `excluded` (explicitly
    ruled out, kept in the catalogue as a documented decision rather than
    silently absent). `lag_type`/`lag_weeks` describe the assumed temporal
    relationship (e.g. `"fixed_weeks"`/`4` for a fixed delayed response);
    `prior_scale` records how tight a future estimation prior should be for
    this pathway (a `exploratory_cross_product` pathway should use a small
    value). `include_in_attribution`/`include_in_planning` are independent
    downstream-eligibility flags, matching the four-flag eligibility
    pattern this codebase already uses for outcomes (core.outcomes) rather
    than overloading `role` to control everything. `evidence_status` is a
    free-text label (see `SUGGESTED_EVIDENCE_STATUSES` for the UI's
    suggestions - not a closed, validated vocabulary) for what evidence, if
    any, currently supports this pathway."""

    channel: str
    source_product: str
    target_outcome_id: str
    role: str = PATHWAY_ROLE_PRIMARY_DIRECT
    lag_type: str = "none"
    lag_weeks: Optional[int] = None
    prior_scale: Optional[float] = 1.0
    include_in_attribution: bool = True
    include_in_planning: bool = True
    evidence_status: str = "untested"
    component_type: str = "direct"
    allow_same_product_cross_product: bool = False
    allow_cross_product_primary: bool = False
    planning_eligibility_confirmed: bool = False
    pathway_id: str = field(default_factory=_new_pathway_id)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MediaOutcomePathway":
        d = dict(d)
        if "component_type" not in d:
            d["component_type"] = (
                "excluded" if d.get("role") == PATHWAY_ROLE_EXCLUDED else
                "cross_product" if d.get("role") in (PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT, PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT) else
                "direct"
            )
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


def validate_media_outcome_pathways(
    pathways: List[MediaOutcomePathway],
    *,
    channels: Optional[Sequence[str]] = None,
    outcome_ids: Optional[Sequence[str]] = None,
    channel_products: Optional[Dict[str, str]] = None,
    outcome_products: Optional[Dict[str, str]] = None,
    fitted_outcome_ids: Optional[Sequence[str]] = None,
    diagnostic_only_outcome_ids: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Rejects (returns non-empty error list, never raises):

    - missing/duplicate `pathway_id`
    - a `channel` not in `channels` (only checked when given)
    - an unknown `source_product` (not one of `KNOWN_PRODUCTS`)
    - a `target_outcome_id` not in `outcome_ids` (only checked when given -
      needs the live catalogue to evaluate, so opt-in via the parameter,
      same convention as `validate_outcome_definitions`'s
      `available_columns`)
    - an unknown `role` (not one of `PATHWAY_ROLES`)
    - a negative `lag_weeks`
    - a non-positive `prior_scale`
    - a duplicate `(channel, target_outcome_id)` pair - at most one pathway
      should describe a given channel's relationship to a given outcome;
      two rows for the same pair is ambiguous about which role/lag/prior
      actually applies
    """
    errors: List[str] = []
    seen_ids = set()
    seen_pairs = set()
    known_channels = set(channels) if channels is not None else None
    known_outcome_ids = set(outcome_ids) if outcome_ids is not None else None

    for p in pathways:
        label = p.pathway_id or "(no pathway_id)"
        if not p.pathway_id:
            errors.append("Every media-outcome pathway must have a pathway_id.")
        elif p.pathway_id in seen_ids:
            errors.append(f"Duplicate pathway_id '{p.pathway_id}'.")
        seen_ids.add(p.pathway_id)

        if not p.channel:
            errors.append(f"Pathway '{label}' has no channel set.")
        elif known_channels is not None and p.channel not in known_channels:
            errors.append(f"Pathway '{label}' references unknown channel '{p.channel}'.")

        if p.source_product not in KNOWN_PRODUCTS:
            errors.append(
                f"Pathway '{label}' has unknown source_product '{p.source_product}' "
                f"(expected one of {', '.join(KNOWN_PRODUCTS)})."
            )
        if channel_products is not None:
            owner = channel_products.get(p.channel)
            if owner not in KNOWN_PRODUCTS:
                errors.append(f"Pathway '{label}' has unknown channel-product ownership for '{p.channel}'.")
            elif owner != p.source_product:
                errors.append(f"Pathway '{label}' source_product '{p.source_product}' does not match channel ownership '{owner}'.")

        if not p.target_outcome_id:
            errors.append(f"Pathway '{label}' has no target_outcome_id set.")
        elif known_outcome_ids is not None and p.target_outcome_id not in known_outcome_ids:
            errors.append(
                f"Pathway '{label}' references unknown target_outcome_id '{p.target_outcome_id}'."
            )

        if p.role not in PATHWAY_ROLES:
            errors.append(
                f"Pathway '{label}' has unknown role '{p.role}' (expected one of {', '.join(PATHWAY_ROLES)})."
            )
        target_product = outcome_products.get(p.target_outcome_id) if outcome_products else None
        is_cross = p.role in (PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT, PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT)
        if target_product in KNOWN_PRODUCTS:
            if is_cross and target_product == p.source_product and not p.allow_same_product_cross_product:
                errors.append(f"Pathway '{label}' uses a cross-product role within the same product without an explicit override.")
            if p.role == PATHWAY_ROLE_PRIMARY_DIRECT and target_product != p.source_product and not p.allow_cross_product_primary:
                errors.append(f"Pathway '{label}' uses primary-direct across products without explicit approval.")
        if p.role == PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT and p.include_in_planning and not p.planning_eligibility_confirmed:
            errors.append(f"Pathway '{label}' is exploratory with planning enabled but has no explicit confirmation.")
        if fitted_outcome_ids is not None and p.role != PATHWAY_ROLE_EXCLUDED and p.target_outcome_id not in fitted_outcome_ids:
            errors.append(f"Pathway '{label}' is active but its target outcome is excluded from fit.")
        if diagnostic_only_outcome_ids is not None and p.include_in_planning and p.target_outcome_id in diagnostic_only_outcome_ids:
            errors.append(f"Pathway '{label}' enables planning for a diagnostic-only outcome.")

        if p.component_type not in COMPONENT_TYPES:
            errors.append(f"Pathway '{label}' has unknown component_type '{p.component_type}' (expected one of {', '.join(COMPONENT_TYPES)}).")
        if p.lag_type not in LAG_TYPES:
            errors.append(f"Pathway '{label}' has unknown lag_type '{p.lag_type}' (expected one of {', '.join(LAG_TYPES)}).")
        if p.evidence_status not in EVIDENCE_STATUSES + LEGACY_EVIDENCE_STATUSES:
            errors.append(f"Pathway '{label}' has unknown evidence_status '{p.evidence_status}' (expected one of {', '.join(EVIDENCE_STATUSES)}).")
        if p.lag_type in ("fixed_weeks", "delayed_adstock") and (p.lag_weeks is None or p.lag_weeks <= 0):
            errors.append(f"Pathway '{label}' uses {p.lag_type} and needs a positive lag_weeks value.")
        if p.lag_type in ("none", "adstock_only") and p.lag_weeks not in (None, 0):
            errors.append(f"Pathway '{label}' uses {p.lag_type} and cannot have a positive lag_weeks value.")
        if p.lag_weeks is not None and p.lag_weeks < 0:
            errors.append(f"Pathway '{label}' has a negative lag_weeks ({p.lag_weeks}).")

        if p.prior_scale is not None and p.prior_scale <= 0:
            errors.append(f"Pathway '{label}' has a non-positive prior_scale ({p.prior_scale}).")

        pair = (p.channel, p.target_outcome_id, p.component_type)
        if pair in seen_pairs:
            errors.append(
                f"Duplicate pathway for channel '{p.channel}' -> outcome '{p.target_outcome_id}' "
                f"component '{p.component_type}'."
            )
        seen_pairs.add(pair)

    return errors


# ---------------------------------------------------------------------------
# Operational pathway masks (PR G1)
#
# The single place that decides, for every (outcome, channel) cell, which of
# the four roles actually governs that cell's fitted contribution - called
# identically by both PyMC model builders (to build the right priors/masks)
# and by both NumPy replay modules (to reproduce the identical structure for
# curves/attribution/scenario planning). Keeping this resolution logic in
# ONE place (rather than each of those ~6 call sites re-deriving it, which is
# exactly the duplication that existed before this PR - core.predict,
# core.market_specific_predict, core.attribution and
# core.market_specific_attribution each separately re-implemented the same
# "is this a DNA channel" direct/halo branching) is what guarantees a fitted
# model's downstream numbers can never silently diverge from what was
# actually fit, and is also what makes Model A/Model C parity checkable by
# construction rather than by convention.
# ---------------------------------------------------------------------------

@dataclass
class ResolvedPathwayMasks:
    """The result of resolving a project's `MediaOutcomePathway` catalogue
    (plus the legacy DNA direct/halo defaults for any cell it doesn't cover)
    against a specific fit's `outcome_ids`/`channels`. JSON-safe (plain
    dict-of-lists), so it can be stored directly on `FHModelMeta` and
    round-tripped through project export/import without special handling.

    `primary_channels_by_outcome[outcome_id]` - channels contributing a
    normal-strength, standard-prior effect to that outcome.
    `active_channels_by_outcome[outcome_id]` - channels contributing a
    real-but-distinctly-regularised effect (generalises the old DNA halo
    pathway beyond DNA channels).
    `exploratory_channels_by_outcome[outcome_id]` - channels contributing a
    strongly-shrunk-toward-zero, not-trusted-for-planning-by-default effect.
    A channel absent from all three lists for a given outcome is `excluded`
    for that cell - zero contribution, not merely a tight prior.
    `cross_product_lag_weeks` - the single shared lag (in weeks, beyond
    ordinary adstock carryover) applied to every `active_channels_by_outcome`/
    `exploratory_channels_by_outcome` cell before its saturated media enters
    that cell's contribution - generalises `dna_lag_weeks` beyond DNA
    channels specifically. Per-pathway custom lag values remain a documented
    future extension (docs/media_outcome_pathways.md); every cross-product
    cell currently shares this one lag."""

    primary_channels_by_outcome: Dict[str, List[str]] = field(default_factory=dict)
    active_channels_by_outcome: Dict[str, List[str]] = field(default_factory=dict)
    exploratory_channels_by_outcome: Dict[str, List[str]] = field(default_factory=dict)
    cross_product_lag_weeks: int = 0
    # Keys are ``outcome_index:channel_index``. Values follow the stable
    # active-cells then exploratory-cells ordering used by both model types.
    lag_weeks_by_cell: Dict[str, int] = field(default_factory=dict)
    prior_scale_by_cell: Dict[str, float] = field(default_factory=dict)
    planning_by_cell: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "ResolvedPathwayMasks":
        if not d:
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def primary_matrix(self, outcome_ids: Sequence[str], channels: Sequence[str]):
        """`(n_outcome, n_channel)` float array, `1.0` where that channel is
        `primary_direct` for that outcome, else `0.0`. Local numpy import so
        this module stays importable without numpy for pure schema/UI use
        (matches this module's existing pandas-only dependency footprint)."""
        import numpy as np

        channel_pos = {c: i for i, c in enumerate(channels)}
        mat = np.zeros((len(outcome_ids), len(channels)), dtype=float)
        for oi, oid in enumerate(outcome_ids):
            for ch in self.primary_channels_by_outcome.get(oid, []):
                ci = channel_pos.get(ch)
                if ci is not None:
                    mat[oi, ci] = 1.0
        return mat

    def _cells(self, by_outcome: Dict[str, List[str]], outcome_ids: Sequence[str], channels: Sequence[str]) -> List[tuple]:
        outcome_pos = {o: i for i, o in enumerate(outcome_ids)}
        channel_pos = {c: i for i, c in enumerate(channels)}
        cells = []
        for oid in outcome_ids:
            for ch in by_outcome.get(oid, []):
                if ch in channel_pos:
                    cells.append((outcome_pos[oid], channel_pos[ch]))
        return cells

    def active_cells(self, outcome_ids: Sequence[str], channels: Sequence[str]) -> List[tuple]:
        """`(outcome_idx, channel_idx)` pairs needing an `active_cross_product`
        strength parameter, in a stable order (iterates `outcome_ids` then
        each outcome's own channel list) - the order every caller sizing a
        parameter vector to `len(...)` and scattering into it must agree on."""
        return self._cells(self.active_channels_by_outcome, outcome_ids, channels)

    def exploratory_cells(self, outcome_ids: Sequence[str], channels: Sequence[str]) -> List[tuple]:
        """Same contract as `active_cells`, for `exploratory_cross_product`."""
        return self._cells(self.exploratory_channels_by_outcome, outcome_ids, channels)

    @staticmethod
    def cell_key(cell: tuple) -> str:
        return f"{cell[0]}:{cell[1]}"

    def lag_for_cell(self, cell: tuple) -> int:
        return int(self.lag_weeks_by_cell.get(self.cell_key(cell), self.cross_product_lag_weeks))

    def prior_for_cell(self, cell: tuple, default: float) -> float:
        return float(self.prior_scale_by_cell.get(self.cell_key(cell), default))

    def planning_matrix(self, outcome_ids: Sequence[str], channels: Sequence[str]):
        import numpy as np
        result = np.zeros((len(outcome_ids), len(channels)), dtype=float)
        for cell in self.active_cells(outcome_ids, channels) + self.exploratory_cells(outcome_ids, channels):
            result[cell] = float(self.planning_by_cell.get(self.cell_key(cell), True))
        primary = self.primary_matrix(outcome_ids, channels)
        for oi, oid in enumerate(outcome_ids):
            for ci, ch in enumerate(channels):
                if primary[oi, ci] and self.planning_by_cell.get(self.cell_key((oi, ci)), True):
                    result[oi, ci] = 1.0
        return result


def resolve_pathway_masks(
    outcome_ids: Sequence[str],
    channels: Sequence[str],
    pathways: List[MediaOutcomePathway],
    *,
    dna_channel_idx: Sequence[int],
    dna_outcome_id: Optional[str],
    direct_dna_outcome_ids: Sequence[str],
    dna_lag_weeks: int,
) -> ResolvedPathwayMasks:
    """
    Resolve every `(outcome, channel)` cell to exactly one role: an explicit
    `MediaOutcomePathway` for that exact `(channel, target_outcome_id)` pair
    wins outright (its `role` fully replaces whatever the legacy default
    would have been for that one cell - including the legacy "both direct
    and halo" case for `dna_outcome_id` below, which an explicit pathway
    reduces to a single specified role); every other cell falls back to this
    codebase's pre-PR-G1 default, so a project with no pathway catalogue
    configured for a given cell fits identically to before this PR:

    - a non-DNA channel: `primary_direct` for every outcome (unconstrained,
      matching this codebase's original behaviour - every channel could
      always freely affect every outcome via `beta[outcome, channel]|)
    - a DNA channel, `direct_dna_outcome_ids` member other than
      `dna_outcome_id` (a DNA-product kit-sale outcome): `primary_direct`
      only - a kit sale has no halo pathway onto itself
      (docs/dna_fh_causal_structure.md)
    - a DNA channel, `dna_outcome_id` itself: BOTH `primary_direct` (the
      direct component) AND `active_cross_product` with
      `cross_product_lag_weeks=dna_lag_weeks` (the halo component) - the one
      case a single cell legitimately gets two simultaneous terms, since the
      FH DNA-cross-sell outcome may plausibly respond to DNA media both
      immediately and with a delay
    - a DNA channel, every other outcome_id: `active_cross_product` only
      (`cross_product_lag_weeks=dna_lag_weeks`) - exactly the old
      unconditional halo pathway

    An explicit `role="excluded"` pathway removes that cell from every list
    (zero contribution). `lag_weeks` is read from the first pathway
    requesting a delay (`lag_type` not `"none"`/blank, or `lag_weeks` set
    explicitly) - see `cross_product_lag_weeks`'s docstring on why this is
    currently one shared value, not per-pathway.
    """
    explicit: Dict[tuple, List[MediaOutcomePathway]] = {}
    for p in pathways:
        explicit.setdefault((p.target_outcome_id, p.channel), []).append(p)
    dna_channel_set = {channels[i] for i in dna_channel_idx if 0 <= i < len(channels)}
    direct_set = set(direct_dna_outcome_ids)

    primary: Dict[str, List[str]] = {}
    active: Dict[str, List[str]] = {}
    exploratory: Dict[str, List[str]] = {}
    cross_product_lag_weeks = dna_lag_weeks
    lag_weeks_by_cell: Dict[str, int] = {}
    prior_scale_by_cell: Dict[str, float] = {}
    planning_by_cell: Dict[str, bool] = {}

    def _add(bucket: Dict[str, List[str]], oid: str, ch: str) -> None:
        bucket.setdefault(oid, []).append(ch)

    for oid in outcome_ids:
        for ch in channels:
            key = (oid, ch)
            if key in explicit:
                for p in explicit[key]:
                    if p.role == PATHWAY_ROLE_PRIMARY_DIRECT:
                        _add(primary, oid, ch)
                    elif p.role == PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT:
                        _add(active, oid, ch)
                    elif p.role == PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT:
                        _add(exploratory, oid, ch)
                    cell_key = f"{outcome_ids.index(oid)}:{channels.index(ch)}"
                    lag_weeks_by_cell[cell_key] = int(p.lag_weeks or 0)
                    if p.prior_scale is not None:
                        prior_scale_by_cell[cell_key] = float(p.prior_scale)
                    planning_by_cell[cell_key] = bool(p.include_in_planning)
                # PATHWAY_ROLE_EXCLUDED: added to no bucket - zero contribution.
                continue

            if ch not in dna_channel_set:
                _add(primary, oid, ch)
            elif oid in direct_set and oid != dna_outcome_id:
                _add(primary, oid, ch)
            elif oid == dna_outcome_id:
                _add(primary, oid, ch)
                _add(active, oid, ch)
            else:
                _add(active, oid, ch)

    return ResolvedPathwayMasks(
        primary_channels_by_outcome=primary,
        active_channels_by_outcome=active,
        exploratory_channels_by_outcome=exploratory,
        cross_product_lag_weeks=cross_product_lag_weeks,
        lag_weeks_by_cell=lag_weeks_by_cell,
        prior_scale_by_cell=prior_scale_by_cell,
        planning_by_cell=planning_by_cell,
    )


# ---------------------------------------------------------------------------
# Fingerprint payload
#
# Sorted/keyed by (channel, target_outcome_id) - the pair
# validate_media_outcome_pathways treats as the natural uniqueness key - not
# by pathway_id (an internal, auto-generated identity label that two
# independently-constructed but logically-identical catalogues would not
# share, and which is not itself calculation-relevant - the same reasoning
# `core.promotions.PromotionEvent.event_id` is never itself fingerprinted).
# ---------------------------------------------------------------------------

_PATHWAY_FINGERPRINT_FIELDS = (
    "channel", "source_product", "target_outcome_id", "component_type", "role", "lag_type", "lag_weeks",
    "prior_scale", "include_in_attribution", "include_in_planning", "evidence_status",
    "allow_same_product_cross_product", "allow_cross_product_primary", "planning_eligibility_confirmed",
)


def pathway_catalogue_fingerprint_payload(pathways: List[MediaOutcomePathway]) -> List[dict]:
    """The calculation-adjacent subset of a pathway catalogue for
    `core.fingerprint.fingerprint_model_spec`, sorted by
    `(channel, target_outcome_id)` so two catalogues listing the same
    pathways in a different order fingerprint identically. Nothing here
    actually changes what gets fitted (see this module's docstring) - it is
    fingerprinted anyway because it is calculation-*adjacent* configuration
    a future estimation PR will read, the same treatment given to
    `core.funnel.FunnelLink`."""
    return [
        {f: getattr(p, f) for f in _PATHWAY_FINGERPRINT_FIELDS}
        for p in sorted(pathways, key=lambda p: (p.channel, p.target_outcome_id))
    ]


# ---------------------------------------------------------------------------
# Fit-time drift detection - mirrors core.outcomes.outcome_drift_status /
# outcomes_drift_dataframe, keyed by pathway_id (this catalogue's stable
# identity, like outcome_id for OutcomeDefinition).
# ---------------------------------------------------------------------------

PATHWAY_DRIFT_STATUSES = (
    "Fitted and current",
    "Changed since fit",
    "New since fit",
    "Removed since fit",
)

_PATHWAY_DRIFT_TRACKED_FIELDS = _PATHWAY_FINGERPRINT_FIELDS


def pathway_catalogue_at_fit_by_id(model_meta: Optional[object]) -> Dict[str, MediaOutcomePathway]:
    """`{pathway_id: MediaOutcomePathway}` from
    `model_meta.pathway_catalogue_at_fit` - `{}` if there is no fitted model
    this session, or the fit predates that field (an old fit has nothing to
    compare drift against, or never had a pathway catalogue configured)."""
    if model_meta is None:
        return {}
    catalogue = getattr(model_meta, "pathway_catalogue_at_fit", None) or []
    return {p.pathway_id: p for p in catalogue}


def pathway_drift_status(
    pathway: Optional[MediaOutcomePathway],
    fit_time_pathway: Optional[MediaOutcomePathway],
) -> str:
    """
    Exact drift status for one pathway_id: compares the *current* catalogue
    entry against the exact `MediaOutcomePathway` a specific fit's metadata
    was captured from. Exactly one of `PATHWAY_DRIFT_STATUSES`.
    `pathway=None` (no longer in the current catalogue) is `"Removed since
    fit"`; `fit_time_pathway=None` (wasn't part of the fit's metadata) is
    `"New since fit"`.
    """
    if pathway is None and fit_time_pathway is None:
        raise ValueError("At least one of pathway/fit_time_pathway must be given.")
    if pathway is None:
        return "Removed since fit"
    if fit_time_pathway is None:
        return "New since fit"
    changed = any(
        getattr(pathway, f) != getattr(fit_time_pathway, f) for f in _PATHWAY_DRIFT_TRACKED_FIELDS
    )
    return "Changed since fit" if changed else "Fitted and current"


def pathways_drift_dataframe(
    pathways: List[MediaOutcomePathway], model_meta: Optional[object],
) -> pd.DataFrame:
    """
    One row per pathway_id across the union of the current catalogue and
    `model_meta`'s fit-time pathway metadata (so a since-removed pathway
    still gets a row), with a `drift_status` column (one of
    `PATHWAY_DRIFT_STATUSES`). `model_meta=None` returns an empty
    DataFrame - there is nothing to detect drift relative to.
    """
    if model_meta is None:
        return pd.DataFrame(columns=["pathway_id", "drift_status"])
    fit_by_id = pathway_catalogue_at_fit_by_id(model_meta)
    current_by_id = {p.pathway_id: p for p in pathways}
    all_ids = list(dict.fromkeys(list(current_by_id) + list(fit_by_id)))
    rows = []
    for pid in all_ids:
        current = current_by_id.get(pid)
        fit_time = fit_by_id.get(pid)
        status = pathway_drift_status(current, fit_time)
        row = (current or fit_time).to_dict()
        row["pathway_id"] = pid
        row["drift_status"] = status
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Outcome reconciliation groups (PR F - "reconciliation groups"; diagnostics
# and validation only, not constrained estimation - see roadmap's "Initially
# use this for validation and diagnostics, not necessarily constrained
# estimation.")
#
# Deliberately NOT fingerprinted (unlike the pathway catalogue above):
# nothing downstream reads a reconciliation group to compute anything - it
# exists purely to describe/check an arithmetic relationship between
# already-modelled outcomes, the same "descriptive, not calculation-relevant"
# reasoning `core.market_config.MarketDescriptors` is deliberately excluded
# from the fingerprint for (see core/fingerprint.py's
# `_model_relevant_market_config` docstring). If a future PR makes
# reconciliation groups feed a constrained estimation step, that is itself a
# fingerprint-breaking change to make at that time, same as any other new
# model-relevant field.
# ---------------------------------------------------------------------------

RECONCILIATION_RELATIONS = ("sum", "ratio")


@dataclass
class OutcomeReconciliationGroup:
    """Describes an arithmetic relationship between outcome_ids that should
    hold if the catalogue is internally consistent, e.g. "DNA total = self
    activated + gifted activated + unactivated" (`relation="sum"`) or "FH net
    bill-through rate = FH net bill-through count / FH eligible sign-ups"
    (`relation="ratio"`). `total_outcome_id` is optional - a `"sum"` relation
    may describe components that reconcile to a total that isn't itself a
    fitted outcome (e.g. a rate's denominator). `component_outcome_ids` is
    the list of outcome_ids on the other side of the relation."""

    group_id: str
    component_outcome_ids: List[str]
    relation: str = "sum"
    total_outcome_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeReconciliationGroup":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


def validate_reconciliation_groups(
    groups: List[OutcomeReconciliationGroup], *, outcome_ids: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Rejects (returns non-empty error list, never raises):

    - missing/duplicate `group_id`
    - an unknown `relation` (not one of `RECONCILIATION_RELATIONS`)
    - fewer than 2 `component_outcome_ids` (a reconciliation needs at least
      two components to relate)
    - a `total_outcome_id`/`component_outcome_ids` entry not in
      `outcome_ids` (only checked when given, same opt-in convention as
      `validate_media_outcome_pathways`)
    - a `total_outcome_id` that is also one of its own `component_outcome_ids`
    """
    errors: List[str] = []
    seen_ids = set()
    known_outcome_ids = set(outcome_ids) if outcome_ids is not None else None

    for g in groups:
        label = g.group_id or "(no group_id)"
        if not g.group_id:
            errors.append("Every reconciliation group must have a group_id.")
        elif g.group_id in seen_ids:
            errors.append(f"Duplicate reconciliation group_id '{g.group_id}'.")
        seen_ids.add(g.group_id)

        if g.relation not in RECONCILIATION_RELATIONS:
            errors.append(
                f"Reconciliation group '{label}' has unknown relation '{g.relation}' "
                f"(expected one of {', '.join(RECONCILIATION_RELATIONS)})."
            )

        if len(g.component_outcome_ids) < 2:
            errors.append(
                f"Reconciliation group '{label}' needs at least 2 component_outcome_ids, "
                f"got {len(g.component_outcome_ids)}."
            )

        if g.total_outcome_id is not None and g.total_outcome_id in g.component_outcome_ids:
            errors.append(
                f"Reconciliation group '{label}' has total_outcome_id "
                f"'{g.total_outcome_id}' listed as one of its own component_outcome_ids."
            )

        if known_outcome_ids is not None:
            if g.total_outcome_id is not None and g.total_outcome_id not in known_outcome_ids:
                errors.append(
                    f"Reconciliation group '{label}' references unknown total_outcome_id "
                    f"'{g.total_outcome_id}'."
                )
            for oid in g.component_outcome_ids:
                if oid not in known_outcome_ids:
                    errors.append(
                        f"Reconciliation group '{label}' references unknown component_outcome_id '{oid}'."
                    )

    return errors


def reconciliation_group_diagnostics(
    group: OutcomeReconciliationGroup,
    values_by_outcome_id: Dict[str, Any],
    *,
    tolerance: float = 1e-6,
) -> Dict[str, Any]:
    """
    Diagnostic-only check (never raises, never blocks a fit or a scenario)
    for one reconciliation group: for `relation="sum"`, compares
    `total_outcome_id`'s value (if given - otherwise the sum of components
    is reported with no target to check against) to the sum of
    `component_outcome_ids`' values; for `relation="ratio"`,
    `total_outcome_id` is treated as the ratio's numerator, and the (single)
    component as its denominator - reports the implied ratio only, since
    there is nothing else to reconcile it against. `values_by_outcome_id`
    maps outcome_id -> a scalar (e.g. one period's total); missing
    outcome_ids are treated as `None` (not zero) - the diagnostic reports
    `None` values it couldn't evaluate rather than guessing.
    """
    component_values = [values_by_outcome_id.get(oid) for oid in group.component_outcome_ids]
    has_all_components = all(v is not None for v in component_values)
    component_sum = sum(component_values) if has_all_components else None

    result: Dict[str, Any] = {
        "group_id": group.group_id,
        "relation": group.relation,
        "component_outcome_ids": group.component_outcome_ids,
        "total_outcome_id": group.total_outcome_id,
        "component_sum": component_sum,
        "total_value": None,
        "difference": None,
        "reconciles": None,
    }

    if group.relation == "sum":
        if group.total_outcome_id is not None:
            total_value = values_by_outcome_id.get(group.total_outcome_id)
            result["total_value"] = total_value
            if total_value is not None and component_sum is not None:
                difference = total_value - component_sum
                result["difference"] = difference
                result["reconciles"] = abs(difference) <= tolerance
    elif group.relation == "ratio" and group.total_outcome_id is not None and len(group.component_outcome_ids) == 1:
        numerator = values_by_outcome_id.get(group.total_outcome_id)
        denominator = component_values[0]
        result["total_value"] = numerator
        if numerator is not None and denominator:
            result["implied_ratio"] = numerator / denominator

    return result
