"""
Canonical outcome schema (PR E, "make OutcomeDefinition the source of
truth" - see docs/decision_log.md for the full rationale).

`OutcomeDefinition` is now the single fitting schema: a fitted model's
identity dimension is `outcome_id`, not segment. This is what makes it
possible to fit two distinct KPIs on the same customer segment - e.g. a
Family History **sign-up** and a Family History **GSA** for segment "New"
- as two independent outcome_ids with independent response curves, rather
than conflating them because they happen to share a segment name. Every
place that used to ask "is this outcome's *segment* in the fitted model's
segment set" now asks "is this outcome's *outcome_id* in the fitted
model's outcome_id set" - segment membership is never used as the test
for whether an outcome was fitted (docs/decision_log.md).

`ModelSpec.segment_outcomes` (`core.schema`) still exists, but only as a
migration source: `fh_outcomes_from_spec` derives an equivalent outcome
catalogue from it for any project that predates this schema. The actual
frame-preparation and model-building path
(`data.preprocessor.prepare_fh_modeling_frame`,
`core.hierarchical_model.build_fh_hierarchical_model`,
`core.market_specific_model.build_fh_market_specific_model`) takes an
explicit outcome catalogue (`List[OutcomeDefinition]`) as its structural
input, not `spec.segment_outcomes` directly.
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
# explicit, visible substitution, not a silent approximation.
DNA_SEGMENT_COMBINED = "Combined"

KNOWN_PRODUCTS = (FAMILY_HISTORY, DNA)

# Canonical metric strings for the three named totals the instruction
# document requires (PR E.1): a sign-up and a GSA are different KPIs and
# must never be aggregated together just because they share a product or a
# segment. These are the values `fh_outcomes_from_spec`/the Structure page's
# general outcome editor use for "the metric this is a count of" - not a
# closed enum (an analyst can type any metric string for a custom outcome),
# but the three names every built-in selector/named total matches on.
METRIC_GSA = "GSA"
METRIC_SIGNUP = "Sign-up"
METRIC_KIT_SALE = "Kit sale"

# Validated role vocabulary - what an outcome's numbers are *for*, not
# whether it was included in a fit (that's `included_in_fit`, a separate
# axis). "primary" is every outcome's default and the only role that
# counted toward totals/objectives before this field existed, so it's the
# correct default for both new outcomes and migrated legacy ones.
OUTCOME_ROLES = ("primary", "secondary", "funnel_intermediate", "diagnostic")


# ---------------------------------------------------------------------------
# Canonical metric registry (PR E.2)
#
# Confirmed pitfall this closes: `select_outcome_ids`/the named totals used
# to match on the free-text `metric` display string exactly ("GSA",
# "Sign-up", "Kit sale") - an analyst typing "Signup" or "Kit Sale" produced
# an outcome that silently fell out of every selector, total and objective.
# `metric_key` is the stable value all matching logic now uses; `metric`
# stays a free-text display label, normalised into a `metric_key` only
# through the small known-variant table below - never fuzzy-guessed into a
# business KPI. `unit` defaults are also driven from here (not from
# `product` alone - see `OutcomeDefinition.__post_init__`), since a Family
# History *sign-up* outcome defaulting to unit "GSA" was itself a confirmed
# pitfall.
# ---------------------------------------------------------------------------

METRIC_KEY_FH_GSA = "fh_gsa"
METRIC_KEY_FH_SIGNUP = "fh_signup"
METRIC_KEY_DNA_KIT_SALE = "dna_kit_sale"
METRIC_KEY_CUSTOM = "custom"


@dataclass(frozen=True)
class MetricDefinition:
    """One entry in `METRIC_REGISTRY`: what a stable `metric_key` means -
    its default display label, its default unit, and (optionally) the one
    product it's valid for."""

    metric_key: str
    display_name: str
    default_unit: str
    product: Optional[str] = None


METRIC_REGISTRY: Dict[str, MetricDefinition] = {
    METRIC_KEY_FH_GSA: MetricDefinition(
        metric_key=METRIC_KEY_FH_GSA, display_name=METRIC_GSA, default_unit="GSA", product=FAMILY_HISTORY,
    ),
    METRIC_KEY_FH_SIGNUP: MetricDefinition(
        metric_key=METRIC_KEY_FH_SIGNUP, display_name=METRIC_SIGNUP, default_unit="sign-up",
        product=FAMILY_HISTORY,
    ),
    METRIC_KEY_DNA_KIT_SALE: MetricDefinition(
        metric_key=METRIC_KEY_DNA_KIT_SALE, display_name=METRIC_KIT_SALE, default_unit="kit", product=DNA,
    ),
}

# Known free-text display variants -> stable metric_key. Deliberately a
# small, explicit table, not fuzzy matching: an unrecognised metric string
# always normalises to METRIC_KEY_CUSTOM, never guessed into one of the
# three built-in KPIs.
_METRIC_LABEL_VARIANTS: Dict[str, str] = {
    "gsa": METRIC_KEY_FH_GSA,
    "family history gsa": METRIC_KEY_FH_GSA,
    "fh gsa": METRIC_KEY_FH_GSA,
    "sign-up": METRIC_KEY_FH_SIGNUP,
    "sign up": METRIC_KEY_FH_SIGNUP,
    "signup": METRIC_KEY_FH_SIGNUP,
    "sign-ups": METRIC_KEY_FH_SIGNUP,
    "sign ups": METRIC_KEY_FH_SIGNUP,
    "signups": METRIC_KEY_FH_SIGNUP,
    "kit sale": METRIC_KEY_DNA_KIT_SALE,
    "kit sales": METRIC_KEY_DNA_KIT_SALE,
    "kitsale": METRIC_KEY_DNA_KIT_SALE,
    "dna kit sale": METRIC_KEY_DNA_KIT_SALE,
    "dna kit sales": METRIC_KEY_DNA_KIT_SALE,
}


def normalize_metric_key(metric: str) -> str:
    """Map a free-text `metric` display label to a stable `metric_key`,
    case/whitespace-insensitively, through the small known-variant table
    above. Anything not recognised - including genuinely custom KPIs -
    normalises to `METRIC_KEY_CUSTOM`, never a guess at one of the three
    built-in metrics."""
    return _METRIC_LABEL_VARIANTS.get((metric or "").strip().lower(), METRIC_KEY_CUSTOM)


@dataclass
class OutcomeDefinition:
    """
    One measurable outcome the business cares about, along explicit
    dimensions rather than an assumed "FH segment" shape.

    `outcome_id` is this outcome's stable identity - the dimension every
    fitted model, curve, attribution, scenario, and persisted bundle keys
    on. `segment` is a *descriptive* grouping (the customer segment this
    outcome belongs to) - it is no longer unique: a Family History
    sign-up and a Family History GSA can both have `segment="New"` while
    being two entirely independent `outcome_id`s with independent fitted
    response curves. `product` distinguishes Family History from DNA.
    `metric` is a free-text *display* label for what's being counted (e.g.
    "GSA", "Sign-up", "Kit sale", or any custom KPI name) - kept distinct
    from `segment` specifically so "New/Sign-up" and "New/GSA" are never
    conflated by sharing a segment. `metric_key` (PR E.2) is the stable
    value all matching logic (`select_outcome_ids`, the named totals) uses
    instead of `metric` itself - derived automatically from `metric` via
    `normalize_metric_key` if left blank, so a display label typo/variant
    ("Signup" vs "Sign-up") can no longer make an outcome silently
    disappear from a selector; see `METRIC_REGISTRY`. `source_column` is
    the source data column. `unit` is the counting unit this outcome's raw
    numbers are in - derived from `metric_key` via `METRIC_REGISTRY` if not
    given (see `__post_init__`; a custom/unrecognised metric_key gets no
    default and must set `unit` explicitly) - so nothing is ever silently
    summed with something in a different unit, and a Family History
    sign-up outcome never defaults to unit "GSA" just because it's a
    Family History outcome. `value_weight` is an optional per-unit value
    (LTV for FH, an analogous per-kit value for DNA); `value_currency`
    names the currency it's denominated in (e.g. "USD") - both persisted so
    a value objective's interpretation is recorded, not just its number.
    `role` is one of `OUTCOME_ROLES` and drives the *default* eligibility
    flags below when they're left unset (PR E.1 introduced the vocabulary;
    PR E.2 makes it a set of *defaults*, not the sole switch - see
    `outcome_eligibility`): `"primary"` outcomes default to eligible for
    everything; `"secondary"` outcomes default to reported/valued but
    excluded from the official total and optimisation; `"funnel_intermediate"`
    outcomes (e.g. a sign-up that precedes a GSA) default to reported in
    their *own* metric's total/CPA but excluded from the official total,
    value and optimisation; `"diagnostic"` outcomes default to excluded from
    everything. Fitting eligibility remains controlled separately by
    `included_in_fit` - `role` never affects whether an outcome is part of a
    fit, only how its numbers are aggregated afterwards.
    `include_in_default_reporting`/`include_in_official_total`/
    `include_in_value`/`include_in_optimisation` (PR E.2) are the four
    independent eligibility axes the instruction document requires,
    replacing the old single role=="primary" gate: each is `None` by
    default (meaning "use this outcome's role default"), but can be set
    explicitly per outcome to override the role default in either
    direction - e.g. a `secondary` outcome with `include_in_optimisation=True`
    explicitly opted back in. Always resolve them through
    `outcome_eligibility(outcome)`, never by reading a field directly (a
    `None` there does not mean "excluded").
    `included_in_fit` is whether this outcome should be part of the *next*
    fit - the persisted replacement for the session-only
    `excluded_outcome_ids` mechanism (docs/decision_log.md); `False`
    outcomes are still captured, validated, and displayed, just excluded
    from `prepare_fh_modeling_frame`. `exclusion_reason` is an optional
    free-text note for why, shown wherever the catalogue is displayed.
    """

    outcome_id: str
    product: str
    segment: str
    metric: str
    source_column: str
    unit: str = ""
    value_weight: Optional[float] = None
    value_currency: Optional[str] = None
    role: str = "primary"
    included_in_fit: bool = True
    exclusion_reason: Optional[str] = None
    metric_key: str = ""
    include_in_default_reporting: Optional[bool] = None
    include_in_official_total: Optional[bool] = None
    include_in_value: Optional[bool] = None
    include_in_optimisation: Optional[bool] = None

    def __post_init__(self) -> None:
        # metric_key first: unit's default (below) is looked up by
        # metric_key, not by product alone (PR E.2 - a Family History
        # sign-up outcome must never default to unit "GSA" just because
        # it's a Family History outcome).
        if not self.metric_key:
            self.metric_key = normalize_metric_key(self.metric)
        if not self.unit:
            definition = METRIC_REGISTRY.get(self.metric_key)
            if definition is not None:
                self.unit = definition.default_unit
            # else: a custom/unrecognised metric - unit stays blank rather
            # than guessed; validate_outcome_definitions's "no unit set"
            # check requires the analyst to set it explicitly.

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeDefinition":
        # Migration: a bundle saved before this schema's fields existed
        # simply doesn't have them - dataclass defaults apply automatically
        # (derived `unit`, "primary" `role`, `included_in_fit=True`), so an
        # old bundle loads as an equivalent, correctly-classified outcome
        # rather than erroring or needing an explicit migration step.
        # `column` -> `source_column`: this PR's rename of the field itself;
        # a bundle written before the rename has `column`, not
        # `source_column` - translate it rather than silently dropping it.
        d = dict(d)
        if "column" in d and "source_column" not in d:
            d["source_column"] = d.pop("column")
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Four-axis eligibility model (PR E.2)
#
# Confirmed pitfall this replaces: every named total/CPA/objective used to
# gate on a single `role == "primary"` check, which meant a Family History
# sign-up marked `funnel_intermediate` could be fitted but then vanish from
# its *own* `fh_signups` total and cost-per-sign-up reporting - reporting
# eligibility and "counts toward the official/headline total" eligibility
# were never actually the same question. These four flags separate them;
# `_ROLE_ELIGIBILITY_DEFAULTS` is exactly the table the instruction document
# specifies, used only when a flag is left `None` (not explicitly configured
# on the `OutcomeDefinition`).
# ---------------------------------------------------------------------------

ELIGIBILITY_FLAGS = (
    "include_in_default_reporting",
    "include_in_official_total",
    "include_in_value",
    "include_in_optimisation",
)

_ROLE_ELIGIBILITY_DEFAULTS: Dict[str, Dict[str, bool]] = {
    "primary": {
        "include_in_default_reporting": True,
        "include_in_official_total": True,
        "include_in_value": True,
        "include_in_optimisation": True,
    },
    "secondary": {
        "include_in_default_reporting": True,
        "include_in_official_total": False,
        "include_in_value": True,
        "include_in_optimisation": False,
    },
    "funnel_intermediate": {
        "include_in_default_reporting": True,
        "include_in_official_total": False,
        "include_in_value": False,
        "include_in_optimisation": False,
    },
    "diagnostic": {
        "include_in_default_reporting": False,
        "include_in_official_total": False,
        "include_in_value": False,
        "include_in_optimisation": False,
    },
}


def outcome_eligibility(outcome: OutcomeDefinition) -> Dict[str, bool]:
    """Resolve all four eligibility flags for `outcome`: an explicitly-set
    field (`True`/`False`) always wins; `None` (the field's default - "not
    explicitly configured") falls back to `outcome.role`'s entry in
    `_ROLE_ELIGIBILITY_DEFAULTS`. An unrecognised role falls back to the
    "primary" row (matches `OutcomeDefinition.role`'s own "primary"
    default) rather than raising - `validate_outcome_definitions` is where
    an invalid role is actually rejected."""
    defaults = _ROLE_ELIGIBILITY_DEFAULTS.get(outcome.role, _ROLE_ELIGIBILITY_DEFAULTS["primary"])
    return {
        flag: (getattr(outcome, flag) if getattr(outcome, flag) is not None else defaults[flag])
        for flag in ELIGIBILITY_FLAGS
    }


def outcome_requires_opt_in(outcome: OutcomeDefinition) -> bool:
    """True if this outcome needs an explicit mapping step before it can
    ever be part of a fit - DNA-product outcomes do; Family History
    outcomes never do, they're always part of every fit with no extra
    configuration. A static, catalogue-level question - it does NOT answer
    "was this specific outcome actually included in a specific fitted
    run" (that's `outcome_was_modelled`) or "will it be included in the
    *next* fit" (that's `outcome.included_in_fit`)."""
    return outcome.product != FAMILY_HISTORY


def outcome_was_modelled(outcome: OutcomeDefinition, model_meta: Optional[object]) -> bool:
    """True if `outcome`'s `outcome_id` is actually present in a *specific
    fitted* model's outcome-id set - the run-aware counterpart to
    `outcome_requires_opt_in`. Pass the `FHModelMeta` of the trace actually
    being displayed or reported on; `None` (no fitted model this session,
    or none loaded) always returns False, never a guess. Keyed on
    `outcome_id`, never `segment` - two outcomes can share a segment and
    still need to be distinguishable here (a sign-up outcome must not
    read as "modelled" just because its sibling GSA outcome on the same
    segment was)."""
    if model_meta is None:
        return False
    return outcome.outcome_id in model_meta.outcome_ids


# ---------------------------------------------------------------------------
# Metric-aware outcome selection (PR E.1)
#
# The confirmed defect this closes: the canonical outcome refactor (PR E)
# made it possible to fit a Family History sign-up and a Family History GSA
# as independent outcome_ids, but aggregation/CPA/objective code kept
# treating every non-DNA-kit outcome_id as "the GSA total" - so a fit with
# both a sign-up and a GSA outcome on the same segment would silently sum
# them together and label the result "fh_gsa". `select_outcome_ids` and the
# three named totals below are the single place that decision is made from
# now on, always from explicit fit-time metadata (product/metric/unit/role),
# never inferred from "not a DNA-kit outcome".
# ---------------------------------------------------------------------------

def select_outcome_ids(
    model_meta: object,
    *,
    product: Optional[str] = None,
    metric: Optional[str] = None,
    metric_key: Optional[str] = None,
    unit: Optional[str] = None,
    role: Optional[str] = None,
) -> List[str]:
    """
    Select outcome_ids from a fitted model's metadata (`FHModelMeta`) by
    explicit dimensions - the central helper every total/CPA/objective in
    this codebase must go through instead of hand-rolling a
    "not a DNA-kit outcome" style filter. `None` on any dimension means "no
    filter on that dimension"; passing none of them returns every fitted
    outcome_id, in `model_meta.outcome_ids` order (so callers get a stable,
    deterministic ordering rather than dict-iteration order).

    Reads `model_meta.outcome_id_to_product`/`_metric`/`_unit`/`_role` -
    populated from the exact outcome catalogue a fit was built from
    (`FHModelMeta.outcome_catalogue_at_fit`), so this is always answering
    "what was this outcome_id's catalogue entry at fit time", not re-deriving
    it from a possibly-since-changed live catalogue.

    `metric` (free-text display string, PR E.1) and `metric_key` (stable key,
    PR E.2) are independent filters - prefer `metric_key` in new code, since
    it's immune to display-label variants ("Signup" vs "Sign-up"). When
    `metric_key` is given, this reads `model_meta.outcome_id_to_metric_key`
    if present for an outcome_id; otherwise it derives the key live via
    `normalize_metric_key(outcome_id_to_metric[...])`, so a `FHModelMeta` (or
    test fixture) that only ever populated `outcome_id_to_metric` still
    matches correctly.
    """
    ids = list(model_meta.outcome_ids)
    if product is not None:
        ids = [o for o in ids if model_meta.outcome_id_to_product.get(o) == product]
    if metric is not None:
        ids = [o for o in ids if model_meta.outcome_id_to_metric.get(o) == metric]
    if metric_key is not None:
        explicit_keys = getattr(model_meta, "outcome_id_to_metric_key", {}) or {}
        display_metrics = getattr(model_meta, "outcome_id_to_metric", {}) or {}

        def _metric_key_for(oid: str) -> str:
            explicit = explicit_keys.get(oid)
            if explicit:
                return explicit
            return normalize_metric_key(display_metrics.get(oid, ""))

        ids = [o for o in ids if _metric_key_for(o) == metric_key]
    if unit is not None:
        ids = [o for o in ids if model_meta.outcome_id_to_unit.get(o) == unit]
    if role is not None:
        # Default to "primary" for an outcome_id missing from outcome_id_to_role
        # (a fit from before outcome_catalogue_at_fit was captured) - matching
        # OutcomeDefinition.role's own default, so a legacy fit's outcomes are
        # still selectable by role="primary" rather than silently excluded.
        ids = [o for o in ids if model_meta.outcome_id_to_role.get(o, "primary") == role]
    return ids


def eligible_outcome_ids(model_meta: object, ids: List[str], flag: str) -> List[str]:
    """Filter `ids` by one resolved eligibility flag (PR E.2 - replaces the
    old role=="primary"-only `_primary_role_only` gate). Reads
    `model_meta.outcome_id_to_eligibility` (the exact `outcome_eligibility()`
    result captured at fit time) for an outcome_id when present; otherwise
    re-derives the role-based default live from `outcome_id_to_role`, so a
    `FHModelMeta` built before this field existed (or a hand-built test
    fixture that only sets `outcome_id_to_role`) still gets correct
    role-based behaviour - just without any per-outcome override that might
    have been configured on the live catalogue."""
    eligibility_map = getattr(model_meta, "outcome_id_to_eligibility", {}) or {}
    role_map = getattr(model_meta, "outcome_id_to_role", {}) or {}
    out = []
    for o in ids:
        resolved = eligibility_map.get(o)
        if resolved is not None:
            include = resolved.get(flag, True)
        else:
            role = role_map.get(o, "primary")
            include = _ROLE_ELIGIBILITY_DEFAULTS.get(role, _ROLE_ELIGIBILITY_DEFAULTS["primary"])[flag]
        if include:
            out.append(o)
    return out


def _has_catalogue_metadata(model_meta: object) -> bool:
    """False for a fit with no outcome-catalogue metadata at all -
    `outcome_id_to_product` empty - which only happens for a `FHModelMeta`
    reconstructed from a bundle exported before `outcome_catalogue_at_fit`
    existed, or one hand-built without it (as plenty of this codebase's own
    unit tests do). Every fit built by `build_fh_hierarchical_model`/
    `build_fh_market_specific_model` populates this fully."""
    return bool(model_meta.outcome_id_to_product)


def fh_gsa_outcome_ids(model_meta: object) -> List[str]:
    """`metric_key=fh_gsa` - the instruction document's named `fh_gsa`
    total. Deliberately NOT "every outcome_id that isn't a DNA-kit outcome" -
    a Family History sign-up outcome must never be silently counted in this
    total just because it also isn't a DNA-kit outcome (the confirmed defect
    PR E.1 replaced). Gated by `include_in_default_reporting` (PR E.2 -
    replaces the old role=="primary"-only gate: a `funnel_intermediate`
    outcome now still appears in its own metric's default total; see
    `official_total_outcome_ids` for the stricter, official-total-only gate).

    Legacy fallback: if `model_meta` has no catalogue metadata at all
    (`_has_catalogue_metadata` False), every outcome_id that isn't
    structurally DNA-kit-only (`model_meta.kit_only_outcome_ids`) is treated
    as an FH GSA outcome - `segment_outcomes`/`fh_outcomes_from_spec` have
    only ever meant "FH weekly GSA columns" in this codebase, so this
    preserves the pre-PR-E.1 "every non-DNA-kit outcome is the GSA total"
    behaviour exactly for a fit with no distinct sign-up outcome to
    disambiguate from, rather than returning nothing."""
    if not _has_catalogue_metadata(model_meta):
        kit_only = set(getattr(model_meta, "kit_only_outcome_ids", []))
        return [o for o in model_meta.outcome_ids if o not in kit_only]
    ids = select_outcome_ids(model_meta, metric_key=METRIC_KEY_FH_GSA)
    return eligible_outcome_ids(model_meta, ids, "include_in_default_reporting")


def fh_signup_outcome_ids(model_meta: object) -> List[str]:
    """`metric_key=fh_signup` - the instruction document's named
    `fh_signups` total, always disjoint from `fh_gsa_outcome_ids` even when
    both share a `segment`. Gated by `include_in_default_reporting` - a
    `funnel_intermediate` sign-up (fitted, but marked as feeding a later
    GSA) still appears here by default, since it's still eligible for its
    *own* metric's reporting (PR E.2 requirement); it's excluded only from
    the stricter `official_total_outcome_ids`. A fit with no catalogue
    metadata at all (see `fh_gsa_outcome_ids`'s legacy fallback) never had a
    distinct sign-up outcome to report, so this returns `[]` for it, not a
    guess."""
    if not _has_catalogue_metadata(model_meta):
        return []
    ids = select_outcome_ids(model_meta, metric_key=METRIC_KEY_FH_SIGNUP)
    return eligible_outcome_ids(model_meta, ids, "include_in_default_reporting")


def dna_kit_sale_outcome_ids(model_meta: object) -> List[str]:
    """`metric_key=dna_kit_sale` - the instruction document's named
    `DNA kits` total. Named distinctly from `FHModelMeta.kit_only_outcome_ids`
    (a *structural* pathway concept - which outcome_ids get only the direct,
    non-halo DNA-media pathway) even though the two sets coincide for every
    outcome this codebase's own UI produces: this one is derived from the
    catalogue's metric_key, the structural one from pathway configuration -
    they are conceptually independent, and a hand-built or future outcome
    could in principle diverge them. Gated by `include_in_default_reporting`.
    Falls back to `model_meta.kit_only_outcome_ids` directly when there is no
    catalogue metadata at all (see `fh_gsa_outcome_ids`'s legacy fallback)."""
    if not _has_catalogue_metadata(model_meta):
        return list(getattr(model_meta, "kit_only_outcome_ids", []))
    ids = select_outcome_ids(model_meta, metric_key=METRIC_KEY_DNA_KIT_SALE)
    return eligible_outcome_ids(model_meta, ids, "include_in_default_reporting")


def official_total_outcome_ids(model_meta: object, *, metric_key: Optional[str] = None) -> List[str]:
    """Outcome_ids eligible for a cross-reporting *official* total (PR E.2) -
    gated by `include_in_official_total`, a stricter flag than the per-metric
    named totals above (which gate on `include_in_default_reporting`). A
    `funnel_intermediate` outcome, for instance, appears in its own metric's
    default reporting total (`fh_signup_outcome_ids`, say) but never in the
    official total - the instruction document's "funnel-intermediate
    sign-ups stay out of official GSA totals" requirement, generalised: they
    stay out of *any* metric's official total, not just GSA's. `metric_key=
    None` returns every officially-eligible outcome_id regardless of metric;
    pass a `METRIC_KEY_*` constant to scope to one metric. Legacy fallback:
    with no catalogue metadata at all, every non-DNA-kit outcome_id is
    treated as officially eligible (mirrors `fh_gsa_outcome_ids`'s
    fallback), since a pre-PR-E.1 fit's outcomes were always "primary"."""
    if not _has_catalogue_metadata(model_meta):
        if metric_key not in (None, METRIC_KEY_FH_GSA):
            return []
        kit_only = set(getattr(model_meta, "kit_only_outcome_ids", []))
        return [o for o in model_meta.outcome_ids if o not in kit_only]
    ids = (
        select_outcome_ids(model_meta, metric_key=metric_key)
        if metric_key is not None
        else list(model_meta.outcome_ids)
    )
    return eligible_outcome_ids(model_meta, ids, "include_in_official_total")


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
    available_columns: Optional[set] = None,
    frame_outcome_ids: Optional[List[str]] = None,
    model_meta_outcome_ids: Optional[List[str]] = None,
) -> str:
    """
    Exactly one of `OUTCOME_STATUSES` - never collapsed into a single
    boolean.

    `available_columns`: the *current* data's column names, to detect a
    mapped column that no longer exists. `frame_outcome_ids`/
    `model_meta_outcome_ids`: the outcome-id sets of whatever's *currently*
    prepared/fitted this session, if anything - not necessarily built from
    this exact outcome catalogue, which is what lets "stale" be detected: a
    column that used to back a prepared-or-fitted outcome and has since
    vanished from the data is a configuration-drift signal ("stale"), not a
    fresh gap ("missing source column", never yet prepared or fit at all).

    `excluded` is read from `outcome.included_in_fit` directly (not a
    separate parameter) - exclusion is now a persisted property of the
    outcome itself, not session-only state passed in from outside.

    Known limitation: staleness is detected by the *column disappearing*,
    not by the mapping changing to a different (still-present) column -
    that would need the exact column used at fit time recorded on
    `FHModelMeta`, which `outcome_catalogue_at_fit` now does capture, but
    this function doesn't yet cross-check against it.
    """
    was_fit = model_meta_outcome_ids is not None and outcome.outcome_id in model_meta_outcome_ids
    was_prepared = frame_outcome_ids is not None and outcome.outcome_id in frame_outcome_ids
    column_missing = available_columns is not None and outcome.source_column not in available_columns

    if column_missing:
        return "Stale after configuration changes" if (was_fit or was_prepared) else "Missing source column"
    if not outcome.included_in_fit:
        return "Excluded"
    if was_fit:
        return "Included in fitted run"
    if was_prepared:
        return "Included in prepared frame"
    return "Configured"


def _implies_conflicting_metric_label(outcome: OutcomeDefinition) -> bool:
    """Heuristic guard against the exact business-context risk the
    instruction document warns about: a KPI label that implies GSA when
    the source is sign-up data, or vice versa. String-based, so it can
    only catch cases where the outcome_id/source_column names literally
    say "signup"/"sign_up" while the metric says "GSA" (or the reverse) -
    documented limitation, not a semantic understanding of the data."""
    text = f"{outcome.outcome_id} {outcome.source_column}".lower()
    metric = outcome.metric.lower()
    mentions_signup = "signup" in text or "sign_up" in text or "sign-up" in text
    mentions_gsa = "gsa" in text
    if "gsa" in metric and mentions_signup and not mentions_gsa:
        return True
    if "sign" in metric and mentions_gsa and not mentions_signup:
        return True
    return False


def validate_outcome_definitions(
    outcomes: List[OutcomeDefinition], *, available_columns: Optional[set] = None,
) -> List[str]:
    """
    Rejects (returns non-empty error list, never raises):

    - duplicate outcome_ids
    - missing outcome_id / source_column / segment
    - unknown product / unknown role
    - blank metric or unit
    - duplicate (product, segment, metric) definitions mapped to
      conflicting source columns
    - one source column mapped to outcomes with incompatible
      (product, metric) - the same raw column can't honestly be both a
      GSA count and a sign-up count, for instance
    - an outcome with `included_in_fit=True` whose source column is
      missing from `available_columns` (only checked when given - this
      needs live data to evaluate, so it's opt-in via the parameter)
    - mixed combined and split DNA outcomes
    - a KPI label that implies GSA when the source looks like sign-up
      data, or vice versa (see `_implies_conflicting_metric_label`)
    - no outcome at all, or none `included_in_fit` (PR E.2 - this is now
      the single place "does this project have anything to fit" is
      enforced, since `ModelSpec.segment_outcomes` is no longer a required
      field - a sign-up-only or GSA-only project is valid as long as its
      outcome catalogue has at least one included outcome)
    """
    errors: List[str] = []
    if not any(o.included_in_fit for o in outcomes):
        errors.append(
            "At least one outcome must be configured and included in the fit - the outcome catalogue "
            "is empty, or every outcome in it is excluded."
        )
    seen_ids = set()
    for o in outcomes:
        if not o.outcome_id:
            errors.append("Every outcome must have an outcome_id.")
            continue
        if o.outcome_id in seen_ids:
            errors.append(f"Duplicate outcome_id '{o.outcome_id}'.")
        seen_ids.add(o.outcome_id)
        if not o.source_column:
            errors.append(f"Outcome '{o.outcome_id}' has no source column mapped.")
        if not o.segment:
            errors.append(f"Outcome '{o.outcome_id}' has no segment set.")
        if not o.metric:
            errors.append(f"Outcome '{o.outcome_id}' has no metric set.")
        if not o.unit:
            errors.append(f"Outcome '{o.outcome_id}' has no unit set.")
        if o.product not in KNOWN_PRODUCTS:
            errors.append(
                f"Outcome '{o.outcome_id}' has unknown product '{o.product}' "
                f"(expected one of {', '.join(KNOWN_PRODUCTS)})."
            )
        if o.role not in OUTCOME_ROLES:
            errors.append(
                f"Outcome '{o.outcome_id}' has unknown role '{o.role}' "
                f"(expected one of {', '.join(OUTCOME_ROLES)})."
            )
        if available_columns is not None and o.included_in_fit and o.source_column not in available_columns:
            errors.append(
                f"Outcome '{o.outcome_id}' is included in the fit but its source column "
                f"'{o.source_column}' is not in the current data."
            )
        if _implies_conflicting_metric_label(o):
            errors.append(
                f"Outcome '{o.outcome_id}' has metric '{o.metric}' but its id/column suggests a "
                "different KPI (sign-up vs. GSA) - sign-ups and GSAs must never be labelled as "
                "each other."
            )

    by_definition: Dict[tuple, set] = {}
    by_column: Dict[str, set] = {}
    for o in outcomes:
        by_definition.setdefault((o.product, o.segment, o.metric), set()).add(o.source_column)
        by_column.setdefault(o.source_column, set()).add((o.product, o.metric))
    for (product, segment, metric), columns in by_definition.items():
        if len(columns) > 1:
            errors.append(
                f"'{product}/{segment}/{metric}' is mapped to conflicting source columns: "
                f"{', '.join(sorted(columns))}."
            )
    for column, pairs in by_column.items():
        if len(pairs) > 1:
            errors.append(
                f"Source column '{column}' is mapped to incompatible outcomes: "
                f"{', '.join(f'{p}/{m}' for p, m in sorted(pairs))}."
            )

    dna_segments = {o.segment for o in outcomes if o.product == DNA}
    if DNA_SEGMENT_COMBINED in dna_segments and len(dna_segments) > 1:
        errors.append(
            "A combined DNA outcome cannot be mixed with split New Customer/Existing FH "
            "Customer DNA outcomes - choose one or the other."
        )
    return errors


# ---------------------------------------------------------------------------
# Explicit FH DNA cross-sell target (PR E.1)
#
# Replaces `core.hierarchical_model._default_dna_outcome_id`'s old
# substring-match fallback ("the first outcome_id containing 'dna'") - with
# DNA-product kit-sale outcomes now also present in the catalogue, substring
# matching on "dna" is genuinely ambiguous (a DNA-kit outcome_id like
# "dna_new_kit" also contains "dna") and was never validated to point at a
# Family History outcome at all. Production configuration must set this
# explicitly; string matching survives only as an opt-in *migration*
# suggestion for legacy projects (`infer_legacy_fh_dna_cross_sell_outcome_id`),
# never as a silent runtime fallback inside the model builders.
# ---------------------------------------------------------------------------

def validate_fh_dna_cross_sell_outcome_id(
    outcome_id: Optional[str], outcomes: List[OutcomeDefinition],
) -> List[str]:
    """
    Validate a candidate `fh_dna_cross_sell_outcome_id` (`ModelSpec` field)
    against the current outcome catalogue. Returns a non-empty error list
    (never raises) unless `outcome_id` exists among `outcomes`, is included
    in the fit, belongs to Family History, and is not a DNA-product
    kit-sale outcome (a kit sale has no halo pathway onto itself - see
    `docs/dna_fh_causal_structure.md`). `outcome_id=None` is valid here (no
    errors) precisely when there is no candidate at all yet - callers that
    require one when DNA channels are configured enforce that separately
    (the model builders raise if a DNA-targeted channel is configured and
    no `dna_outcome_id` is resolvable).
    """
    if outcome_id is None:
        return []
    by_id = {o.outcome_id: o for o in outcomes}
    if outcome_id not in by_id:
        return [f"fh_dna_cross_sell_outcome_id '{outcome_id}' is not one of this project's outcomes."]
    o = by_id[outcome_id]
    errors = []
    if not o.included_in_fit:
        errors.append(f"fh_dna_cross_sell_outcome_id '{outcome_id}' is excluded from the fit.")
    if o.product != FAMILY_HISTORY:
        errors.append(
            f"fh_dna_cross_sell_outcome_id '{outcome_id}' has product '{o.product}', expected "
            f"'{FAMILY_HISTORY}' - the FH DNA cross-sell target must be a Family History outcome, "
            "not a DNA-product kit-sale outcome (which has no halo pathway onto itself)."
        )
    return errors


def infer_legacy_fh_dna_cross_sell_outcome_id(
    outcomes: List[OutcomeDefinition],
) -> "tuple[Optional[str], Optional[str]]":
    """
    Migration-only helper: guess the FH DNA cross-sell outcome for a legacy
    project that predates the explicit `fh_dna_cross_sell_outcome_id` field,
    the same substring heuristic the model builders used to apply silently.
    Returns `(candidate_outcome_id_or_None, warning_message_or_None)` -
    callers (the Structure/Model Config pages) show the warning and let the
    analyst confirm or override the candidate; this is never called from
    inside the model-building path itself.

    Zero matches: `(None, None)` - nothing to suggest, not an error (a
    project with no DNA channels configured at all doesn't need this).
    Exactly one Family-History match: `(candidate, warning)` - a usable
    suggestion, but still flagged, since silent inference is exactly what
    this migration path replaces. More than one match: `(None, warning)` -
    ambiguous, explicit configuration is required, no guess is offered.
    """
    candidates = [
        o.outcome_id for o in outcomes
        if o.product == FAMILY_HISTORY and "dna" in o.outcome_id.lower()
    ]
    if not candidates:
        return None, None
    if len(candidates) == 1:
        return candidates[0], (
            f"No fh_dna_cross_sell_outcome_id was configured for this legacy project - "
            f"'{candidates[0]}' was inferred from its name (contains 'dna'). Confirm or change this "
            "on the Structure page; automatic substring inference is not used once this is set."
        )
    return None, (
        "No fh_dna_cross_sell_outcome_id was configured for this legacy project, and more than one "
        f"outcome name suggests it could be the DNA cross-sell target ({', '.join(sorted(candidates))}) "
        "- set fh_dna_cross_sell_outcome_id explicitly on the Structure page before fitting."
    )


# ---------------------------------------------------------------------------
# Canonical outcome catalogue fingerprint payload (PR E.1)
# ---------------------------------------------------------------------------

_FINGERPRINT_FIELDS = (
    "outcome_id", "product", "segment", "metric", "metric_key", "unit", "source_column",
    "role", "included_in_fit", "value_weight", "value_currency",
    "include_in_default_reporting", "include_in_official_total",
    "include_in_value", "include_in_optimisation",
)


def outcome_catalogue_fingerprint_payload(outcomes: List[OutcomeDefinition]) -> List[dict]:
    """
    The calculation-relevant subset of an outcome catalogue, sorted by
    `outcome_id`, for `core.fingerprint.fingerprint_model_spec`. Every field
    here changes what a fit or a downstream calculation actually does if
    edited - adding/removing a non-DNA FH outcome, changing sign-up to GSA,
    changing unit, source column, role, inclusion, or the value weight used
    in planning - so a change to any of them must invalidate approval
    (the confirmed gap this closes: the old fingerprint only covered
    `direct_dna_outcome_ids`, a bare list of ids with none of this detail).
    Sorted so two catalogues with the same outcomes in a different list
    order fingerprint identically.
    """
    return [
        {f: getattr(o, f) for f in _FINGERPRINT_FIELDS}
        for o in sorted(outcomes, key=lambda o: o.outcome_id)
    ]


# ---------------------------------------------------------------------------
# Exact fit-time drift detection (PR E.1)
#
# `outcome_status` above only detects a mapped source column *disappearing*.
# It does not detect the mapping changing to a different, still-present
# column (or any other tracked field changing) - a documented limitation of
# that function. These use `FHModelMeta.outcome_catalogue_at_fit` (the exact
# `OutcomeDefinition` list a specific fit was built from) to close that gap.
# ---------------------------------------------------------------------------

DRIFT_STATUSES = (
    "Fitted and current",
    "Excluded from next fit",
    "Changed since fit",
    "Missing source column",
    "New since fit",
    "Removed since fit",
)

_DRIFT_TRACKED_FIELDS = (
    "source_column", "product", "segment", "metric", "metric_key", "unit", "role", "included_in_fit",
    "value_weight", "include_in_default_reporting", "include_in_official_total",
    "include_in_value", "include_in_optimisation",
)


def outcome_catalogue_at_fit_by_id(model_meta: Optional[object]) -> Dict[str, OutcomeDefinition]:
    """`{outcome_id: OutcomeDefinition}` from `model_meta.outcome_catalogue_at_fit` -
    `{}` if there is no fitted model this session, or the fit predates that
    field (an old fit has nothing to compare drift against)."""
    if model_meta is None:
        return {}
    catalogue = getattr(model_meta, "outcome_catalogue_at_fit", None) or []
    return {o.outcome_id: o for o in catalogue}


def outcome_drift_status(
    outcome: Optional[OutcomeDefinition],
    fit_time_outcome: Optional[OutcomeDefinition],
    *,
    available_columns: Optional[set] = None,
) -> str:
    """
    Exact drift status for one outcome_id: compares the *current* catalogue
    entry (`outcome`) against the exact `OutcomeDefinition` a specific fit
    was built from (`fit_time_outcome`, from `outcome_catalogue_at_fit_by_id`).
    Unlike `outcome_status` (column-disappearing only), this also detects the
    mapping changing to a still-present, different column - or any other
    tracked field changing (product/segment/metric/unit/role/inclusion/value
    weight) - as `"Changed since fit"`, not silently treated as unchanged.

    Exactly one of `DRIFT_STATUSES`. `outcome=None` (the outcome_id no longer
    exists in the current catalogue at all) is `"Removed since fit"`;
    `fit_time_outcome=None` (this outcome_id wasn't part of the fit being
    compared against) is `"New since fit"`.
    """
    if outcome is None and fit_time_outcome is None:
        raise ValueError("At least one of outcome/fit_time_outcome must be given.")
    if outcome is None:
        return "Removed since fit"
    if fit_time_outcome is None:
        return "New since fit"
    if available_columns is not None and outcome.source_column not in available_columns:
        return "Missing source column"
    if not outcome.included_in_fit:
        return "Excluded from next fit"
    changed = any(getattr(outcome, f) != getattr(fit_time_outcome, f) for f in _DRIFT_TRACKED_FIELDS)
    if changed:
        return "Changed since fit"
    return "Fitted and current"


def outcomes_drift_dataframe(
    outcomes: List[OutcomeDefinition],
    model_meta: Optional[object],
    *,
    available_columns: Optional[set] = None,
) -> pd.DataFrame:
    """
    One row per outcome_id across the union of the current catalogue and
    `model_meta`'s fit-time catalogue (so a since-removed outcome still gets
    a row), with a `drift_status` column (one of `DRIFT_STATUSES`).
    `model_meta=None` (no fitted model to compare against) returns an empty
    DataFrame - there is nothing to detect drift relative to.
    """
    if model_meta is None:
        return pd.DataFrame(columns=["outcome_id", "drift_status"])
    fit_by_id = outcome_catalogue_at_fit_by_id(model_meta)
    current_by_id = {o.outcome_id: o for o in outcomes}
    all_ids = list(dict.fromkeys(list(current_by_id) + list(fit_by_id)))
    rows = []
    for oid in all_ids:
        current = current_by_id.get(oid)
        fit_time = fit_by_id.get(oid)
        status = outcome_drift_status(current, fit_time, available_columns=available_columns)
        row = (current or fit_time).to_dict()
        row["outcome_id"] = oid
        row["drift_status"] = status
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Drift status as a first-class, blocking check (PR E.2 requirement #10)
#
# PR E.1 built exact drift detection (outcome_drift_status/
# outcomes_drift_dataframe) but no page actually consumed it. This makes
# "calculation-relevant drift" an explicit, reusable predicate every
# downstream page (Structure/Model Config/Model Training/Diagnostics/
# Results/Scenario Planner/Export) can check, and specifically what
# Scenario Planner uses to block planning outright - a stale in-memory
# trace must not be plannable against once the catalogue backing it has
# genuinely changed, even though the trace object itself is unaffected.
# ---------------------------------------------------------------------------

BLOCKING_DRIFT_STATUSES = ("Changed since fit", "Removed since fit")


def has_blocking_drift(
    outcomes: List[OutcomeDefinition],
    model_meta: Optional[object],
    *,
    available_columns: Optional[set] = None,
) -> bool:
    """
    True if any outcome_id's catalogue entry has drifted from what
    `model_meta` was actually fit on in a way that should block planning
    against it (`BLOCKING_DRIFT_STATUSES` - a changed or removed outcome).
    `"New since fit"` (not yet part of any fit) and `"Excluded from next
    fit"` (a *future*-fit concern) deliberately do NOT block - they don't
    make the *existing* fitted model's numbers wrong, only its catalogue
    incomplete relative to what a *next* fit would use.

    `model_meta=None` (no fitted model at all) returns `False` - there is
    nothing to have drifted from yet; a caller checks this after already
    establishing a fit exists.
    """
    if model_meta is None:
        return False
    drift_df = outcomes_drift_dataframe(outcomes, model_meta, available_columns=available_columns)
    if drift_df.empty:
        return False
    return bool(drift_df["drift_status"].isin(BLOCKING_DRIFT_STATUSES).any())


def fh_outcomes_from_spec(
    segment_outcomes: Dict[str, str], segment_ltv: Optional[Dict[str, float]] = None,
) -> List[OutcomeDefinition]:
    """Derive the Family History OutcomeDefinitions implied by a ModelSpec's
    `segment_outcomes`/`segment_ltv` - the migration path for any project
    (or imported bundle) that predates the canonical outcome catalogue.
    `segment_outcomes` has only ever meant "FH segment weekly GSA columns"
    in this codebase, so `metric="GSA"` is the correct, specific migration
    default here - it does not preclude a project's Structure page from
    also capturing a distinct sign-up outcome on the same segment."""
    segment_ltv = segment_ltv or {}
    return [
        OutcomeDefinition(
            outcome_id=f"fh_{seg.lower()}",
            product=FAMILY_HISTORY,
            segment=seg,
            metric=METRIC_GSA,
            source_column=col,
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
    they have different economics and different halo linkages to FH. Where
    source data can't support that split, `combined_column` gives a single
    DNA outcome instead (`DNA_SEGMENT_COMBINED`) - an explicit, visible
    fallback: its presence in the result is the caller's signal to show
    the corresponding limitation, not a silently degraded split.

    `combined_column` takes precedence if given alongside the split
    columns - `validate_outcome_definitions` rejects mixing them, so callers
    should treat this as "either/or" in their own UI too.
    """
    if combined_column:
        return [OutcomeDefinition(
            outcome_id="dna_combined_kit", product=DNA, segment=DNA_SEGMENT_COMBINED,
            metric=METRIC_KIT_SALE, source_column=combined_column, value_weight=value_weight_combined,
        )]

    outcomes = []
    if new_customer_column:
        outcomes.append(OutcomeDefinition(
            outcome_id="dna_new_kit", product=DNA, segment=DNA_SEGMENT_NEW,
            metric=METRIC_KIT_SALE, source_column=new_customer_column, value_weight=value_weight_new,
        ))
    if existing_fh_column:
        outcomes.append(OutcomeDefinition(
            outcome_id="dna_existing_fh_kit", product=DNA, segment=DNA_SEGMENT_EXISTING_FH,
            metric=METRIC_KIT_SALE, source_column=existing_fh_column, value_weight=value_weight_existing,
        ))
    return outcomes


def resolve_outcome_definitions(
    outcome_definitions: Optional[List[dict]],
    segment_outcomes: Dict[str, str],
    segment_ltv: Optional[Dict[str, float]] = None,
) -> List[OutcomeDefinition]:
    """
    The single place every caller (UI, report, persistence, model
    building) goes to get "this project's current outcome catalogue". If
    the project was saved with an explicit outcome set (any project that
    has been through the Structure page since this schema shipped), that
    wins - it already includes both the FH outcomes and any mapped DNA
    outcomes. Otherwise (every project created before this schema existed,
    or that has never touched the outcomes section) an equivalent FH-only
    set is derived live from `segment_outcomes`, so a generalised outcome
    view - and a buildable model - is available for *any* project, not
    only ones an analyst has explicitly configured for it.
    """
    if outcome_definitions:
        return [OutcomeDefinition.from_dict(d) for d in outcome_definitions]
    return fh_outcomes_from_spec(segment_outcomes, segment_ltv)


def included_outcomes(outcomes: List[OutcomeDefinition]) -> List[OutcomeDefinition]:
    """Every outcome with `included_in_fit=True` - what
    `prepare_fh_modeling_frame` and the model builders actually fit.
    Excluded outcomes remain in the catalogue (still captured, validated,
    displayed) but never reach model-building."""
    return [o for o in outcomes if o.included_in_fit]


def dna_kit_outcome_columns(outcomes: List[OutcomeDefinition]) -> Dict[str, str]:
    """
    `{outcome_id: source_column}` for every DNA-product outcome in
    `outcomes` - keyed by `outcome_id`, not `segment`, since `segment` is
    no longer unique. This is the shape
    `data.preprocessor.prepare_fh_modeling_frame` and
    `core.hierarchical_model.build_fh_hierarchical_model`'s
    `direct_dna_outcome_ids` (via `list(...)`) both expect.
    """
    return {o.outcome_id: o.source_column for o in outcomes if o.product == DNA}


def outcomes_to_dataframe(
    outcomes: List[OutcomeDefinition],
    *,
    available_columns: Optional[set] = None,
    frame_outcome_ids: Optional[List[str]] = None,
    model_meta_outcome_ids: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Flat table for display/export - one row per outcome, with a `status`
    column (one of `OUTCOME_STATUSES`) instead of a single collapsed
    boolean. All keyword args are optional and independently omittable -
    passing none of them still gives every outcome a status ("Configured"
    or "Excluded" per `outcome.included_in_fit`), just without the
    frame/fit/column context to distinguish the other four."""
    if not outcomes:
        return pd.DataFrame(columns=[
            "outcome_id", "product", "segment", "metric", "source_column", "unit",
            "value_weight", "role", "included_in_fit", "exclusion_reason", "status",
        ])
    return pd.DataFrame([
        {
            **o.to_dict(),
            "status": outcome_status(
                o, available_columns=available_columns,
                frame_outcome_ids=frame_outcome_ids, model_meta_outcome_ids=model_meta_outcome_ids,
            ),
        }
        for o in outcomes
    ])
