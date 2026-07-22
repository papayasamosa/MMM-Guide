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

**This module is schema, validation, persistence, fingerprinting, fit-time
metadata and drift detection only.** Nothing here changes what gets fitted
or how attribution/scenario numbers are computed - `dna_channels`/
`direct_dna_outcome_ids` remain the actual structural inputs the PyMC model
builders (`core.hierarchical_model`, `core.market_specific_model`) read.
A `MediaOutcomePathway` catalogue is captured, validated and carried through
to `FHModelMeta.pathway_catalogue_at_fit` purely as forward-looking,
versioned metadata - proving the schema can already describe the pathways a
future estimation PR (PR G) will actually use, before that PR exists. See
docs/media_outcome_pathways.md for the full design record and roadmap.

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
SUGGESTED_LAG_TYPES = ("none", "fixed_weeks", "distributed")
SUGGESTED_EVIDENCE_STATUSES = ("untested", "supported", "inconclusive", "contradicted")

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
    prior_scale: float = 1.0
    include_in_attribution: bool = True
    include_in_planning: bool = True
    evidence_status: str = "untested"
    pathway_id: str = field(default_factory=_new_pathway_id)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MediaOutcomePathway":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


def validate_media_outcome_pathways(
    pathways: List[MediaOutcomePathway],
    *,
    channels: Optional[Sequence[str]] = None,
    outcome_ids: Optional[Sequence[str]] = None,
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

        if p.lag_weeks is not None and p.lag_weeks < 0:
            errors.append(f"Pathway '{label}' has a negative lag_weeks ({p.lag_weeks}).")

        if p.prior_scale <= 0:
            errors.append(f"Pathway '{label}' has a non-positive prior_scale ({p.prior_scale}).")

        pair = (p.channel, p.target_outcome_id)
        if pair in seen_pairs:
            errors.append(
                f"Duplicate pathway for channel '{p.channel}' -> outcome '{p.target_outcome_id}' - "
                "at most one pathway should describe a given channel/outcome relationship."
            )
        seen_pairs.add(pair)

    return errors


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
    "channel", "source_product", "target_outcome_id", "role", "lag_type", "lag_weeks",
    "prior_scale", "include_in_attribution", "include_in_planning", "evidence_status",
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
