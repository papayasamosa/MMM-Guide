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

import hashlib
from copy import deepcopy
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

# Closed vocabularies used by validation and the pathway editor.
LAG_TYPES = ("none", "fixed_weeks", "adstock_only", "delayed_adstock")
EVIDENCE_STATUSES = (
    "business_assumption",
    "experiment_supported",
    "model_supported",
    "weak_evidence",
    "contradicted",
    "unreviewed",
)
LEGACY_EVIDENCE_STATUSES = ("untested", "supported", "inconclusive")
COMPONENT_TYPES = ("direct", "cross_product", "mediated", "excluded")
HEADLINE_APPROVAL_STATUSES = (
    "not_reviewed",
    "approved",
    "rejected",
    "not_applicable",
)
SUGGESTED_LAG_TYPES = LAG_TYPES
SUGGESTED_EVIDENCE_STATUSES = EVIDENCE_STATUSES

# Ancestry's documented default pathway expectations (roadmap "PR F: pathway
# catalogue" section) - reference data for the UI's quick-start defaults,
# not enforced by validation (an analyst's actual data may differ).
DEFAULT_PATHWAY_EXPECTATIONS = (
    {
        "source_product": DNA,
        "role": PATHWAY_ROLE_PRIMARY_DIRECT,
        "description": "DNA media -> DNA kits",
    },
    {
        "source_product": DNA,
        "role": PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
        "description": "DNA media -> FH outcomes (delayed halo)",
    },
    {
        "source_product": FAMILY_HISTORY,
        "role": PATHWAY_ROLE_PRIMARY_DIRECT,
        "description": "FH media -> FH outcomes",
    },
    {
        "source_product": FAMILY_HISTORY,
        "role": PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT,
        "description": "FH media -> DNA kits (tight prior, planning=false)",
    },
)


def pathway_natural_key(
    channel: str, target_outcome_id: str, component_type: str
) -> str:
    return f"{channel}\x1f{target_outcome_id}\x1f{component_type}"


def _deterministic_pathway_id(
    channel: str, target_outcome_id: str, component_type: str
) -> str:
    return hashlib.sha256(
        pathway_natural_key(channel, target_outcome_id, component_type).encode()
    ).hexdigest()[:12]


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
    `prior_scale` controls the HalfNormal pathway-strength prior for fitted
    `cross_product` components only. Direct effects use the model's
    hierarchical beta prior, so their pathway-level `prior_scale` must be
    unset. Mediated and excluded components are governance/diagnostic
    records and do not enter the standard MMM likelihood.

    Attribution, planning, and headline reporting are independent decisions.
    Evidence status describes the evidence; it never grants headline
    approval. Headline reporting requires both `include_in_headline=True`
    and `headline_approval_status="approved"`, with the reviewer metadata
    retained for audit."""

    channel: str
    source_product: str
    target_outcome_id: str
    role: str = PATHWAY_ROLE_PRIMARY_DIRECT
    lag_type: str = "none"
    lag_weeks: Optional[int] = None
    prior_scale: Optional[float] = None
    include_in_attribution: bool = True
    include_in_planning: bool = True
    include_in_headline: bool = False
    headline_approval_status: str = "not_reviewed"
    headline_approval_note: str = ""
    approved_by: str = ""
    approved_at: str = ""
    evidence_status: str = "untested"
    component_type: str = "direct"
    allow_same_product_cross_product: bool = False
    allow_cross_product_primary: bool = False
    planning_eligibility_confirmed: bool = False
    pathway_id: str = ""

    def __post_init__(self) -> None:
        # Constructor-level compatibility with catalogues created before
        # component_type existed (from_dict performs the same migration).
        if self.component_type == "direct" and self.role in {
            PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
            PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT,
        }:
            self.component_type = "cross_product"
        elif self.component_type == "direct" and self.role == PATHWAY_ROLE_EXCLUDED:
            self.component_type = "excluded"
        if not self.pathway_id and self.channel and self.target_outcome_id:
            self.pathway_id = _deterministic_pathway_id(
                self.channel, self.target_outcome_id, self.component_type
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MediaOutcomePathway":
        d = dict(d)
        if "component_type" not in d:
            d["component_type"] = (
                "excluded"
                if d.get("role") == PATHWAY_ROLE_EXCLUDED
                else "cross_product"
                if d.get("role")
                in (
                    PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
                    PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT,
                )
                else "direct"
            )
        # Bundles written before G1.1.3 inferred headline visibility from
        # evidence. Preserve that result once during migration, then make
        # approval explicit and independent for all future saves.
        if "include_in_headline" not in d:
            inferred = bool(
                d.get("include_in_attribution", True)
                and d.get("component_type") in {"direct", "cross_product"}
                and d.get("role") != PATHWAY_ROLE_EXCLUDED
                and d.get("evidence_status")
                in {"experiment_supported", "model_supported", "supported"}
            )
            d["include_in_headline"] = inferred
            d["headline_approval_status"] = "approved" if inferred else "not_reviewed"
            if inferred:
                d["headline_approval_note"] = (
                    "Migrated from pre-G1.1.3 evidence-based headline eligibility."
                )
                d["approved_by"] = "legacy_migration"
                d["approved_at"] = "legacy_bundle"
        # Old editors populated 1.0 for direct/excluded rows even though the
        # value never affected a parameter. Remove that misleading legacy
        # value during bundle/session migration.
        if d.get("component_type") != "cross_product":
            d["prior_scale"] = None
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
    - a missing/non-positive cross-product `prior_scale`, or a misleading
      `prior_scale` on a component where it is not operational
    - a duplicate `(channel, target_outcome_id, component_type)` natural key
    - mediated/excluded components enabled for fit-dependent outputs
    - headline inclusion without an explicit approval record
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
            errors.append(
                f"Pathway '{label}' references unknown channel '{p.channel}'."
            )

        if p.source_product not in KNOWN_PRODUCTS:
            errors.append(
                f"Pathway '{label}' has unknown source_product '{p.source_product}' "
                f"(expected one of {', '.join(KNOWN_PRODUCTS)})."
            )
        if channel_products is not None:
            owner = channel_products.get(p.channel)
            if owner not in KNOWN_PRODUCTS:
                errors.append(
                    f"Pathway '{label}' has unknown channel-product ownership for '{p.channel}'."
                )
            elif owner != p.source_product:
                errors.append(
                    f"Pathway '{label}' source_product '{p.source_product}' does not match channel ownership '{owner}'."
                )

        if not p.target_outcome_id:
            errors.append(f"Pathway '{label}' has no target_outcome_id set.")
        elif (
            known_outcome_ids is not None
            and p.target_outcome_id not in known_outcome_ids
        ):
            errors.append(
                f"Pathway '{label}' references unknown target_outcome_id '{p.target_outcome_id}'."
            )

        if p.role not in PATHWAY_ROLES:
            errors.append(
                f"Pathway '{label}' has unknown role '{p.role}' (expected one of {', '.join(PATHWAY_ROLES)})."
            )
        target_product = (
            outcome_products.get(p.target_outcome_id) if outcome_products else None
        )
        is_cross = p.role in (
            PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
            PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT,
        )
        if target_product in KNOWN_PRODUCTS:
            if (
                is_cross
                and target_product == p.source_product
                and not p.allow_same_product_cross_product
            ):
                errors.append(
                    f"Pathway '{label}' uses a cross-product role within the same product without an explicit override."
                )
            if (
                p.role == PATHWAY_ROLE_PRIMARY_DIRECT
                and target_product != p.source_product
                and not p.allow_cross_product_primary
            ):
                errors.append(
                    f"Pathway '{label}' uses primary-direct across products without explicit approval."
                )
        if (
            p.role == PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT
            and p.include_in_planning
            and not p.planning_eligibility_confirmed
        ):
            errors.append(
                f"Pathway '{label}' is exploratory with planning enabled but has no explicit confirmation."
            )
        if (
            fitted_outcome_ids is not None
            and p.role != PATHWAY_ROLE_EXCLUDED
            and p.target_outcome_id not in fitted_outcome_ids
        ):
            errors.append(
                f"Pathway '{label}' is active but its target outcome is excluded from fit."
            )
        if (
            diagnostic_only_outcome_ids is not None
            and p.include_in_planning
            and p.target_outcome_id in diagnostic_only_outcome_ids
        ):
            errors.append(
                f"Pathway '{label}' enables planning for a diagnostic-only outcome."
            )

        if p.component_type not in COMPONENT_TYPES:
            errors.append(
                f"Pathway '{label}' has unknown component_type '{p.component_type}' (expected one of {', '.join(COMPONENT_TYPES)})."
            )
        role_components = {
            PATHWAY_ROLE_PRIMARY_DIRECT: {"direct"},
            PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT: {"cross_product", "mediated"},
            PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT: {"cross_product", "mediated"},
            PATHWAY_ROLE_EXCLUDED: {"excluded"},
        }
        if (
            p.role in role_components
            and p.component_type not in role_components[p.role]
        ):
            errors.append(
                f"Pathway '{label}' has incompatible role '{p.role}' and "
                f"component_type '{p.component_type}'."
            )
        if p.lag_type not in LAG_TYPES:
            errors.append(
                f"Pathway '{label}' has unknown lag_type '{p.lag_type}' (expected one of {', '.join(LAG_TYPES)})."
            )
        if p.evidence_status not in EVIDENCE_STATUSES + LEGACY_EVIDENCE_STATUSES:
            errors.append(
                f"Pathway '{label}' has unknown evidence_status '{p.evidence_status}' (expected one of {', '.join(EVIDENCE_STATUSES)})."
            )
        if p.lag_type in ("fixed_weeks", "delayed_adstock") and (
            p.lag_weeks is None or p.lag_weeks <= 0
        ):
            errors.append(
                f"Pathway '{label}' uses {p.lag_type} and needs a positive lag_weeks value."
            )
        if p.lag_type in ("none", "adstock_only") and p.lag_weeks not in (None, 0):
            errors.append(
                f"Pathway '{label}' uses {p.lag_type} and cannot have a positive lag_weeks value."
            )
        if p.lag_weeks is not None and p.lag_weeks < 0:
            errors.append(
                f"Pathway '{label}' has a negative lag_weeks ({p.lag_weeks})."
            )

        if p.prior_scale is not None and p.prior_scale <= 0:
            errors.append(
                f"Pathway '{label}' has a non-positive prior_scale ({p.prior_scale})."
            )
        if p.component_type != "cross_product" and p.prior_scale is not None:
            errors.append(
                f"Pathway '{label}' has prior_scale set, but that field only controls "
                "the fitted cross-product pathway-strength prior."
            )

        if p.headline_approval_status not in HEADLINE_APPROVAL_STATUSES:
            errors.append(
                f"Pathway '{label}' has unknown headline_approval_status "
                f"'{p.headline_approval_status}' (expected one of "
                f"{', '.join(HEADLINE_APPROVAL_STATUSES)})."
            )
        if p.include_in_headline and p.headline_approval_status != "approved":
            errors.append(
                f"Pathway '{label}' is headline-enabled without explicit approval."
            )
        if p.include_in_headline and not p.include_in_attribution:
            errors.append(
                f"Pathway '{label}' cannot be headline-enabled while attribution is disabled."
            )
        if p.headline_approval_status == "approved" and not p.approved_by:
            errors.append(
                f"Pathway '{label}' has headline approval but no approved_by reviewer."
            )
        if p.headline_approval_status == "approved" and not p.approved_at:
            errors.append(
                f"Pathway '{label}' has headline approval but no approved_at timestamp."
            )
        if p.component_type in {"mediated", "excluded"}:
            if p.include_in_planning:
                errors.append(
                    f"Pathway '{label}' is {p.component_type} and cannot be planning-enabled."
                )
            if p.include_in_headline:
                errors.append(
                    f"Pathway '{label}' is {p.component_type} and cannot be headline-enabled."
                )

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


class _ReadOnlyList(list):
    """JSON-compatible list that rejects mutation after construction."""

    @staticmethod
    def _blocked(*_args, **_kwargs):
        raise TypeError("Resolved pathway compatibility views are read-only.")

    __setitem__ = _blocked
    __delitem__ = _blocked
    __iadd__ = _blocked
    __imul__ = _blocked
    append = _blocked
    clear = _blocked
    extend = _blocked
    insert = _blocked
    pop = _blocked
    remove = _blocked
    reverse = _blocked
    sort = _blocked

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        copied = type(self)(deepcopy(list(self), memo))
        memo[id(self)] = copied
        return copied


class _ReadOnlyDict(dict):
    """JSON-compatible dict that rejects mutation after construction."""

    @staticmethod
    def _blocked(*_args, **_kwargs):
        raise TypeError("Resolved pathway compatibility views are read-only.")

    __setitem__ = _blocked
    __delitem__ = _blocked
    __ior__ = _blocked
    clear = _blocked
    pop = _blocked
    popitem = _blocked
    setdefault = _blocked
    update = _blocked

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        copied = type(self)(
            (deepcopy(key, memo), deepcopy(value, memo))
            for key, value in self.items()
        )
        memo[id(self)] = copied
        return copied


@dataclass(frozen=True)
class ResolvedPathwayComponent:
    """One resolved equation component and its downstream governance.

    Mediated and excluded records remain visible in fit metadata but do not
    enter the ordinary media equation.
    """

    outcome_id: str
    channel: str
    component_type: str
    role: str
    lag_weeks: int = 0
    prior_scale: Optional[float] = None
    include_in_attribution: bool = True
    include_in_planning: bool = True
    include_in_headline: bool = False
    headline_approval_status: str = "not_reviewed"
    headline_approval_note: str = ""
    approved_by: str = ""
    approved_at: str = ""
    evidence_status: str = "unreviewed"
    included_in_fit: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "ResolvedPathwayComponent":
        value = dict(value)
        if value.get("include_in_headline") and "headline_approval_status" not in value:
            value.update(
                headline_approval_status="approved",
                headline_approval_note=(
                    "Migrated from pre-G1.1.3 resolved-component metadata."
                ),
                approved_by="legacy_migration",
                approved_at="legacy_bundle",
            )
        known = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in value.items() if key in known})


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
    `components` is authoritative. The named masks and cell dictionaries are
    deterministic compatibility caches for older bundle readers; every
    calculation method derives from `components`. Per-component lag,
    prior, attribution, headline, and planning decisions are operational."""

    primary_channels_by_outcome: Dict[str, List[str]] = field(default_factory=dict)
    active_channels_by_outcome: Dict[str, List[str]] = field(default_factory=dict)
    exploratory_channels_by_outcome: Dict[str, List[str]] = field(default_factory=dict)
    cross_product_lag_weeks: int = 0
    components: List[ResolvedPathwayComponent] = field(default_factory=list)
    # Keys are ``outcome_index:channel_index``. Values follow the stable
    # active-cells then exploratory-cells ordering used by both model types.
    lag_weeks_by_cell: Dict[str, int] = field(default_factory=dict)
    prior_scale_by_cell: Dict[str, float] = field(default_factory=dict)
    planning_by_cell: Dict[str, bool] = field(default_factory=dict)

    _IMMUTABLE_FIELDS = {
        "primary_channels_by_outcome",
        "active_channels_by_outcome",
        "exploratory_channels_by_outcome",
        "cross_product_lag_weeks",
        "components",
        "lag_weeks_by_cell",
        "prior_scale_by_cell",
        "planning_by_cell",
    }

    def __setattr__(self, name, value) -> None:
        if (
            name in self._IMMUTABLE_FIELDS
            and getattr(self, "_compatibility_views_frozen", False)
        ):
            raise AttributeError(
                "Resolved pathway components and compatibility views are "
                "immutable; resolve a new component collection instead."
            )
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        if self.components:
            self._refresh_compatibility_caches()
        else:
            self._freeze_current_compatibility_views()
        object.__setattr__(self, "_compatibility_views_frozen", True)

    @staticmethod
    def _readonly_channel_map(value: Dict[str, List[str]]) -> _ReadOnlyDict:
        return _ReadOnlyDict(
            {key: _ReadOnlyList(channels) for key, channels in value.items()}
        )

    def _freeze_current_compatibility_views(self) -> None:
        object.__setattr__(
            self,
            "primary_channels_by_outcome",
            self._readonly_channel_map(self.primary_channels_by_outcome),
        )
        object.__setattr__(
            self,
            "active_channels_by_outcome",
            self._readonly_channel_map(self.active_channels_by_outcome),
        )
        object.__setattr__(
            self,
            "exploratory_channels_by_outcome",
            self._readonly_channel_map(self.exploratory_channels_by_outcome),
        )
        object.__setattr__(self, "components", _ReadOnlyList(self.components))
        object.__setattr__(
            self, "lag_weeks_by_cell", _ReadOnlyDict(self.lag_weeks_by_cell)
        )
        object.__setattr__(
            self, "prior_scale_by_cell", _ReadOnlyDict(self.prior_scale_by_cell)
        )
        object.__setattr__(
            self, "planning_by_cell", _ReadOnlyDict(self.planning_by_cell)
        )

    def _refresh_compatibility_caches(self) -> None:
        """Rebuild every legacy mask/cache from authoritative components."""
        primary: Dict[str, List[str]] = {}
        active: Dict[str, List[str]] = {}
        exploratory: Dict[str, List[str]] = {}
        cross_components = [
            item
            for item in self.components
            if item.included_in_fit and item.component_type == "cross_product"
        ]
        for item in self.components:
            if not item.included_in_fit:
                continue
            if item.role == PATHWAY_ROLE_PRIMARY_DIRECT:
                primary.setdefault(item.outcome_id, []).append(item.channel)
            elif item.role == PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT:
                active.setdefault(item.outcome_id, []).append(item.channel)
            elif item.role == PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT:
                exploratory.setdefault(item.outcome_id, []).append(item.channel)
        object.__setattr__(
            self,
            "primary_channels_by_outcome",
            self._readonly_channel_map(primary),
        )
        object.__setattr__(
            self,
            "active_channels_by_outcome",
            self._readonly_channel_map(active),
        )
        object.__setattr__(
            self,
            "exploratory_channels_by_outcome",
            self._readonly_channel_map(exploratory),
        )
        object.__setattr__(self, "components", _ReadOnlyList(self.components))
        # Index-keyed caches require the stable outcome/channel order encoded
        # by the compatibility masks. Preserve first-seen component order,
        # which is resolve_pathway_masks' outcome-then-channel order.
        outcomes = list(dict.fromkeys(item.outcome_id for item in self.components))
        channels = list(dict.fromkeys(item.channel for item in self.components))
        outcome_pos = {value: index for index, value in enumerate(outcomes)}
        channel_pos = {value: index for index, value in enumerate(channels)}
        lag_by_cell: Dict[str, int] = {}
        prior_by_cell: Dict[str, float] = {}
        planning_by_cell: Dict[str, bool] = {}
        for item in cross_components:
            key = self.cell_key(
                (outcome_pos[item.outcome_id], channel_pos[item.channel])
            )
            lag_by_cell[key] = int(item.lag_weeks)
            if item.prior_scale is not None:
                prior_by_cell[key] = float(item.prior_scale)
            planning_by_cell[key] = bool(item.include_in_planning)
        object.__setattr__(self, "lag_weeks_by_cell", _ReadOnlyDict(lag_by_cell))
        object.__setattr__(
            self, "prior_scale_by_cell", _ReadOnlyDict(prior_by_cell)
        )
        object.__setattr__(
            self, "planning_by_cell", _ReadOnlyDict(planning_by_cell)
        )

    def to_dict(self) -> dict:
        return {
            "primary_channels_by_outcome": {
                key: list(value)
                for key, value in self.primary_channels_by_outcome.items()
            },
            "active_channels_by_outcome": {
                key: list(value)
                for key, value in self.active_channels_by_outcome.items()
            },
            "exploratory_channels_by_outcome": {
                key: list(value)
                for key, value in self.exploratory_channels_by_outcome.items()
            },
            "cross_product_lag_weeks": self.cross_product_lag_weeks,
            "components": [component.to_dict() for component in self.components],
            "lag_weeks_by_cell": dict(self.lag_weeks_by_cell),
            "prior_scale_by_cell": dict(self.prior_scale_by_cell),
            "planning_by_cell": dict(self.planning_by_cell),
        }

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "ResolvedPathwayMasks":
        if not d:
            return cls()
        known = set(cls.__dataclass_fields__)
        values = {k: v for k, v in d.items() if k in known}
        values["components"] = [
            item
            if isinstance(item, ResolvedPathwayComponent)
            else ResolvedPathwayComponent.from_dict(item)
            for item in values.get("components", [])
        ]
        supplied_caches = {
            key: values.get(key)
            for key in (
                "primary_channels_by_outcome",
                "active_channels_by_outcome",
                "exploratory_channels_by_outcome",
                "lag_weeks_by_cell",
                "prior_scale_by_cell",
                "planning_by_cell",
            )
            if key in d
        }
        result = cls(**values)
        if result.components:
            canonical = result.to_dict()
            mismatches = [
                key
                for key, supplied in supplied_caches.items()
                if supplied != canonical.get(key)
            ]
            if mismatches:
                raise ValueError(
                    "Resolved pathway compatibility caches disagree with the "
                    "authoritative component collection: " + ", ".join(mismatches)
                )
        return result

    def component(
        self, outcome_id: str, channel: str, component_type: str
    ) -> Optional[ResolvedPathwayComponent]:
        return next(
            (
                item
                for item in self.components
                if item.outcome_id == outcome_id
                and item.channel == channel
                and item.component_type == component_type
            ),
            None,
        )

    def component_eligible(
        self, outcome_id: str, channel: str, component_type: str, purpose: str
    ) -> bool:
        """Eligibility for the fitted, attribution, headline, or planning view."""
        if purpose not in {"fit", "attribution", "headline", "planning"}:
            raise ValueError(f"Unknown component eligibility purpose '{purpose}'.")
        item = self.component(outcome_id, channel, component_type)
        if item is None:
            # Old bundles have masks but no component collection. Preserve
            # their historical all-visible behaviour.
            return not self.components
        if purpose == "fit":
            return item.included_in_fit
        if purpose == "attribution":
            return item.included_in_fit and item.include_in_attribution
        if purpose == "headline":
            return (
                item.included_in_fit
                and item.include_in_headline
                and item.headline_approval_status == "approved"
            )
        return item.included_in_fit and item.include_in_planning

    def primary_matrix(self, outcome_ids: Sequence[str], channels: Sequence[str]):
        """`(n_outcome, n_channel)` float array, `1.0` where that channel is
        `primary_direct` for that outcome, else `0.0`. Local numpy import so
        this module stays importable without numpy for pure schema/UI use
        (matches this module's existing pandas-only dependency footprint)."""
        import numpy as np

        mat = np.zeros((len(outcome_ids), len(channels)), dtype=float)
        outcome_pos = {value: index for index, value in enumerate(outcome_ids)}
        channel_pos = {value: index for index, value in enumerate(channels)}
        if self.components:
            for item in self.components:
                if (
                    item.included_in_fit
                    and item.component_type == "direct"
                    and item.role == PATHWAY_ROLE_PRIMARY_DIRECT
                    and item.outcome_id in outcome_pos
                    and item.channel in channel_pos
                ):
                    mat[outcome_pos[item.outcome_id], channel_pos[item.channel]] = 1.0
            return mat
        for oi, oid in enumerate(outcome_ids):
            for channel in self.primary_channels_by_outcome.get(oid, []):
                if channel in channel_pos:
                    mat[oi, channel_pos[channel]] = 1.0
        return mat

    def _cells(
        self,
        by_outcome: Dict[str, List[str]],
        outcome_ids: Sequence[str],
        channels: Sequence[str],
    ) -> List[tuple]:
        outcome_pos = {o: i for i, o in enumerate(outcome_ids)}
        channel_pos = {c: i for i, c in enumerate(channels)}
        cells = []
        for oid in outcome_ids:
            for ch in by_outcome.get(oid, []):
                if ch in channel_pos:
                    cells.append((outcome_pos[oid], channel_pos[ch]))
        return cells

    def active_cells(
        self, outcome_ids: Sequence[str], channels: Sequence[str]
    ) -> List[tuple]:
        """`(outcome_idx, channel_idx)` pairs needing an `active_cross_product`
        strength parameter, in a stable order (iterates `outcome_ids` then
        each outcome's own channel list) - the order every caller sizing a
        parameter vector to `len(...)` and scattering into it must agree on."""
        return self._component_cells(
            PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT, outcome_ids, channels
        )

    def exploratory_cells(
        self, outcome_ids: Sequence[str], channels: Sequence[str]
    ) -> List[tuple]:
        """Same contract as `active_cells`, for `exploratory_cross_product`."""
        return self._component_cells(
            PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT, outcome_ids, channels
        )

    def _component_cells(
        self,
        role: str,
        outcome_ids: Sequence[str],
        channels: Sequence[str],
    ) -> List[tuple]:
        if not self.components:
            legacy = (
                self.active_channels_by_outcome
                if role == PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT
                else self.exploratory_channels_by_outcome
            )
            return self._cells(legacy, outcome_ids, channels)
        outcome_pos = {value: index for index, value in enumerate(outcome_ids)}
        channel_pos = {value: index for index, value in enumerate(channels)}
        return [
            (outcome_pos[item.outcome_id], channel_pos[item.channel])
            for item in self.components
            if item.included_in_fit
            and item.component_type == "cross_product"
            and item.role == role
            and item.outcome_id in outcome_pos
            and item.channel in channel_pos
        ]

    @staticmethod
    def cell_key(cell: tuple) -> str:
        return f"{cell[0]}:{cell[1]}"

    def lag_for_cell(self, cell: tuple) -> int:
        if self.components:
            outcomes = list(dict.fromkeys(item.outcome_id for item in self.components))
            channels = list(dict.fromkeys(item.channel for item in self.components))
            if cell[0] < len(outcomes) and cell[1] < len(channels):
                item = self.component(
                    outcomes[cell[0]], channels[cell[1]], "cross_product"
                )
                if item is not None:
                    return int(item.lag_weeks)
        return int(
            self.lag_weeks_by_cell.get(
                self.cell_key(cell), self.cross_product_lag_weeks
            )
        )

    def prior_for_cell(self, cell: tuple, default: float) -> float:
        if self.components:
            outcomes = list(dict.fromkeys(item.outcome_id for item in self.components))
            channels = list(dict.fromkeys(item.channel for item in self.components))
            if cell[0] < len(outcomes) and cell[1] < len(channels):
                item = self.component(
                    outcomes[cell[0]], channels[cell[1]], "cross_product"
                )
                if item is not None and item.prior_scale is not None:
                    return float(item.prior_scale)
        return float(self.prior_scale_by_cell.get(self.cell_key(cell), default))

    def eligibility_matrix(
        self,
        outcome_ids: Sequence[str],
        channels: Sequence[str],
        purpose: str,
    ):
        """Total component eligibility by cell for an explicit output view."""
        import numpy as np

        result = np.zeros((len(outcome_ids), len(channels)), dtype=float)
        for oi, outcome_id in enumerate(outcome_ids):
            for ci, channel in enumerate(channels):
                result[oi, ci] = float(
                    any(
                        self.component_eligible(
                            outcome_id, channel, component_type, purpose
                        )
                        for component_type in ("direct", "cross_product")
                    )
                )
        return result

    def planning_matrix(self, outcome_ids: Sequence[str], channels: Sequence[str]):
        import numpy as np

        result = np.zeros((len(outcome_ids), len(channels)), dtype=float)
        for cell in self.active_cells(outcome_ids, channels) + self.exploratory_cells(
            outcome_ids, channels
        ):
            oi, ci = cell
            result[cell] = float(
                self.component_eligible(
                    outcome_ids[oi], channels[ci], "cross_product", "planning"
                )
            )
        primary = self.primary_matrix(outcome_ids, channels)
        for oi, oid in enumerate(outcome_ids):
            for ci, ch in enumerate(channels):
                if primary[oi, ci] and self.component_eligible(
                    oid, ch, "direct", "planning"
                ):
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
    """Resolve the catalogue into one authoritative component collection.

    Explicit records are keyed by outcome, channel, and component type, so a
    direct effect and delayed halo can coexist without overwriting each
    other's lag, prior, attribution, or planning governance. Legacy defaults
    are materialised as components for projects without explicit records.
    Mediated components are retained but never enter the ordinary equation.
    """
    explicit: Dict[tuple, List[MediaOutcomePathway]] = {}
    for pathway in pathways:
        explicit.setdefault((pathway.target_outcome_id, pathway.channel), []).append(
            pathway
        )

    dna_channels = {channels[i] for i in dna_channel_idx if 0 <= i < len(channels)}
    direct_dna = set(direct_dna_outcome_ids)
    components: List[ResolvedPathwayComponent] = []

    def add_component(
        oid: str,
        channel: str,
        component_type: str,
        role: str,
        *,
        lag_weeks: int = 0,
        prior_scale: Optional[float] = None,
        include_in_attribution: bool = True,
        include_in_planning: bool = True,
        include_in_headline: bool = False,
        headline_approval_status: str = "not_reviewed",
        headline_approval_note: str = "",
        approved_by: str = "",
        approved_at: str = "",
        evidence_status: str = "unreviewed",
    ) -> None:
        included_in_fit = (
            component_type in {"direct", "cross_product"}
            and role != PATHWAY_ROLE_EXCLUDED
        )
        if component_type in {"mediated", "excluded"}:
            include_in_planning = False
            include_in_headline = False
        components.append(
            ResolvedPathwayComponent(
                outcome_id=oid,
                channel=channel,
                component_type=component_type,
                role=role,
                lag_weeks=int(lag_weeks),
                prior_scale=(
                    float(prior_scale)
                    if component_type == "cross_product" and prior_scale is not None
                    else None
                ),
                include_in_attribution=bool(include_in_attribution),
                include_in_planning=bool(include_in_planning),
                include_in_headline=include_in_headline,
                headline_approval_status=headline_approval_status,
                headline_approval_note=headline_approval_note,
                approved_by=approved_by,
                approved_at=approved_at,
                evidence_status=evidence_status,
                included_in_fit=included_in_fit,
            )
        )

    for oid in outcome_ids:
        for channel in channels:
            configured = explicit.get((oid, channel))
            if configured:
                for pathway in configured:
                    add_component(
                        oid,
                        channel,
                        pathway.component_type,
                        pathway.role,
                        lag_weeks=pathway.lag_weeks or 0,
                        prior_scale=pathway.prior_scale,
                        include_in_attribution=pathway.include_in_attribution,
                        include_in_planning=pathway.include_in_planning,
                        include_in_headline=pathway.include_in_headline,
                        headline_approval_status=pathway.headline_approval_status,
                        headline_approval_note=pathway.headline_approval_note,
                        approved_by=pathway.approved_by,
                        approved_at=pathway.approved_at,
                        evidence_status=pathway.evidence_status,
                    )
                continue

            if channel not in dna_channels:
                add_component(oid, channel, "direct", PATHWAY_ROLE_PRIMARY_DIRECT)
            elif oid in direct_dna and oid != dna_outcome_id:
                add_component(oid, channel, "direct", PATHWAY_ROLE_PRIMARY_DIRECT)
            elif oid == dna_outcome_id:
                add_component(oid, channel, "direct", PATHWAY_ROLE_PRIMARY_DIRECT)
                add_component(
                    oid,
                    channel,
                    "cross_product",
                    PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
                    lag_weeks=dna_lag_weeks,
                )
            else:
                add_component(
                    oid,
                    channel,
                    "cross_product",
                    PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
                    lag_weeks=dna_lag_weeks,
                )

    return ResolvedPathwayMasks(
        cross_product_lag_weeks=dna_lag_weeks,
        components=components,
    )


def resolve_validated_pathway_masks(
    outcome_ids: Sequence[str],
    channels: Sequence[str],
    pathways: List[MediaOutcomePathway],
    *,
    channel_products: Dict[str, str],
    outcome_products: Dict[str, str],
    fitted_outcome_ids: Sequence[str],
    diagnostic_only_outcome_ids: Sequence[str],
    dna_channel_idx: Sequence[int],
    dna_outcome_id: Optional[str],
    direct_dna_outcome_ids: Sequence[str],
    dna_lag_weeks: int,
) -> ResolvedPathwayMasks:
    """Validate the complete pathway context, then resolve model components.

    Model builders call this before creating a PyMC model. It deliberately
    requires ownership, fit, and diagnostic context so builder validation
    cannot silently degrade to channel/outcome-name checks only.
    """
    errors = validate_media_outcome_pathways(
        pathways,
        channels=channels,
        outcome_ids=outcome_ids,
        channel_products=channel_products,
        outcome_products=outcome_products,
        fitted_outcome_ids=fitted_outcome_ids,
        diagnostic_only_outcome_ids=diagnostic_only_outcome_ids,
    )
    if errors:
        raise ValueError(
            "Invalid media-outcome pathway catalogue: " + "; ".join(errors)
        )
    return resolve_pathway_masks(
        outcome_ids,
        channels,
        pathways,
        dna_channel_idx=dna_channel_idx,
        dna_outcome_id=dna_outcome_id,
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        dna_lag_weeks=dna_lag_weeks,
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
    "channel",
    "source_product",
    "target_outcome_id",
    "component_type",
    "role",
    "lag_type",
    "lag_weeks",
    "prior_scale",
    "include_in_attribution",
    "include_in_planning",
    "include_in_headline",
    "headline_approval_status",
    "headline_approval_note",
    "approved_by",
    "approved_at",
    "evidence_status",
    "allow_same_product_cross_product",
    "allow_cross_product_primary",
    "planning_eligibility_confirmed",
)


def pathway_catalogue_fingerprint_payload(
    pathways: List[MediaOutcomePathway],
) -> List[dict]:
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
        for p in sorted(
            pathways,
            key=lambda p: (p.channel, p.target_outcome_id, p.component_type, p.role),
        )
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


def pathway_catalogue_at_fit_by_id(
    model_meta: Optional[object],
) -> Dict[str, MediaOutcomePathway]:
    """`{pathway_id: MediaOutcomePathway}` from
    `model_meta.pathway_catalogue_at_fit` - `{}` if there is no fitted model
    this session, or the fit predates that field (an old fit has nothing to
    compare drift against, or never had a pathway catalogue configured)."""
    if model_meta is None:
        return {}
    catalogue = getattr(model_meta, "pathway_catalogue_at_fit", None) or []
    return {
        pathway_natural_key(p.channel, p.target_outcome_id, p.component_type): p
        for p in catalogue
    }


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
        getattr(pathway, f) != getattr(fit_time_pathway, f)
        for f in _PATHWAY_DRIFT_TRACKED_FIELDS
    )
    return "Changed since fit" if changed else "Fitted and current"


def pathways_drift_dataframe(
    pathways: List[MediaOutcomePathway],
    model_meta: Optional[object],
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
    current_by_id = {
        pathway_natural_key(p.channel, p.target_outcome_id, p.component_type): p
        for p in pathways
    }
    all_ids = list(dict.fromkeys(list(current_by_id) + list(fit_by_id)))
    rows = []
    for pid in all_ids:
        current = current_by_id.get(pid)
        fit_time = fit_by_id.get(pid)
        status = pathway_drift_status(current, fit_time)
        row = (current or fit_time).to_dict()
        row["pathway_id"] = _deterministic_pathway_id(
            row["channel"], row["target_outcome_id"], row["component_type"]
        )
        row["natural_key"] = pid
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
    groups: List[OutcomeReconciliationGroup],
    *,
    outcome_ids: Optional[Sequence[str]] = None,
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

        if (
            g.total_outcome_id is not None
            and g.total_outcome_id in g.component_outcome_ids
        ):
            errors.append(
                f"Reconciliation group '{label}' has total_outcome_id "
                f"'{g.total_outcome_id}' listed as one of its own component_outcome_ids."
            )

        if known_outcome_ids is not None:
            if (
                g.total_outcome_id is not None
                and g.total_outcome_id not in known_outcome_ids
            ):
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
    component_values = [
        values_by_outcome_id.get(oid) for oid in group.component_outcome_ids
    ]
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
    elif (
        group.relation == "ratio"
        and group.total_outcome_id is not None
        and len(group.component_outcome_ids) == 1
    ):
        numerator = values_by_outcome_id.get(group.total_outcome_id)
        denominator = component_values[0]
        result["total_value"] = numerator
        if numerator is not None and denominator:
            result["implied_ratio"] = numerator / denominator

    return result


def accumulate_cross_product_eta_numpy(
    lagged_media_by_weeks, beta, strength, cells, lag_for_cell
):
    """Reference Model A/C algebra: accumulate every resolved component once."""
    import numpy as np

    media = next(iter(lagged_media_by_weeks.values()))
    eta = np.zeros((media.shape[0], beta.shape[-2]), dtype=float)
    for outcome_index, channel_index in cells:
        lagged = lagged_media_by_weeks[lag_for_cell[(outcome_index, channel_index)]][
            :, channel_index
        ]
        coefficient = (
            beta[outcome_index, channel_index]
            if beta.ndim == 2
            else beta[:, outcome_index, channel_index]
        )
        eta[:, outcome_index] += (
            lagged * coefficient * strength[outcome_index, channel_index]
        )
    return eta
