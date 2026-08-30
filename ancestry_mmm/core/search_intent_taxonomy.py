"""Governed Search intent taxonomy and platform-axis reporting hierarchy
(REQ-SEARCH-004, Decisions 2 and 4 of the "Post-UI/UX Implementation
Instructions: Approved Business Decisions" brief).

This module implements the Phase B work the `REQ-SEARCH-004` addendum
(2026-08-30) explicitly named as not yet built:

1. The approved minimum `search_intent_group` taxonomy content (Brand /
   Non-Brand) as governed records, per `REQ-SEARCH-004` §1's schema.
2. A governed `platform` (Google / Bing) axis, orthogonal to the intent-
   group axis - the addendum was explicit that these must remain two
   independent dimensions of the same reporting hierarchy, never
   conflated into one combined enum (e.g. never a single
   `"google_brand"` value standing in for both).
3. Reporting roll-up helpers computing: Total Paid Search -> {Brand
   Search, Non-Brand Search} -> {Google Brand, Bing Brand} under Brand
   Search, {Google Non-Brand, Bing Non-Brand} under Non-Brand Search -
   every parent total derived by summing its governed children, never
   accepted as a pre-computed input (Decision 4: "the business must
   never manually add detailed categories to obtain a parent total").

Explicitly NOT built here (per the addendum's own scope, and Decision 2's
"D4 remains open" instruction): any deeper Non-Brand keyword/search-term
group, or the evidence threshold that would promote one to separately
reportable. `SearchIntentGroup.parent_search_intent_group_id` already
supports a future group nesting under Non-Brand without a schema change
when that threshold work (reusing `REQ-VAL-001`'s per-artefact
threshold-policy-record mechanism) is eventually done - this module does
not anticipate that by inventing a third hierarchy level or a numeric
threshold now.

PMax, Demand Gen, and YouTube are confirmed excluded from this taxonomy
(Decision 2: "do not classify them as PPC simply because of the source
system") - `validate_activity_search_taxonomy` rejects an activity that
carries both a taxonomy reference and one of those campaign types.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

SEARCH_INTENT_TAXONOMY_SCHEMA_VERSION = 1

# --- Brand-class vocabulary (REQ-SEARCH-004 §1) -----------------------------

BRAND_CLASS_BRAND = "brand"
BRAND_CLASS_GENERIC_NON_BRAND = "generic_non_brand"
BRAND_CLASS_MIXED_OR_AMBIGUOUS = "mixed_or_ambiguous"
BRAND_CLASS_NOT_APPLICABLE = "not_applicable"
BRAND_CLASSES = (
    BRAND_CLASS_BRAND,
    BRAND_CLASS_GENERIC_NON_BRAND,
    BRAND_CLASS_MIXED_OR_AMBIGUOUS,
    BRAND_CLASS_NOT_APPLICABLE,
)


@dataclass(frozen=True)
class SearchIntentGroup:
    """One governed `search_intent_group` record (`REQ-SEARCH-004` §1).

    Mirrors `core.search_objects.SearchObjectDefinition`'s immutable-
    versioned-lineage pattern: `search_intent_group_id` is the lineage
    identity, `search_intent_group_version` is the version within it - an
    edit is always a new version via `new_search_intent_group_version`,
    never an in-place mutation of an approved record.
    """

    search_intent_group_id: str
    search_intent_group_name: str
    brand_class: str
    parent_search_intent_group_id: Optional[str] = None
    business_description: str = ""
    product_scope: str = ""
    intent_type: Optional[str] = None
    cross_route_comparable_flag: bool = False
    owner: str = ""
    approval_status: str = "draft"
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    effective_period_start: Optional[str] = None
    effective_period_end: Optional[str] = None
    supersedes_search_intent_group_id: Optional[str] = None
    search_intent_group_version: int = 1
    schema_version: int = SEARCH_INTENT_TAXONOMY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.search_intent_group_id:
            raise ValueError("SearchIntentGroup requires a search_intent_group_id.")
        if not self.search_intent_group_name:
            raise ValueError("SearchIntentGroup requires a search_intent_group_name.")
        if self.brand_class not in BRAND_CLASSES:
            raise ValueError(
                f"SearchIntentGroup: unknown brand_class '{self.brand_class}' "
                f"(expected one of {BRAND_CLASSES})."
            )
        if self.search_intent_group_version < 1:
            raise ValueError("search_intent_group_version must be >= 1.")
        if self.parent_search_intent_group_id == self.search_intent_group_id:
            raise ValueError(
                f"SearchIntentGroup '{self.search_intent_group_id}' cannot be "
                "its own parent."
            )
        if self.approval_status == "approved" and (
            not self.approved_by or not self.approved_at
        ):
            raise ValueError(
                "approved search intent groups require approved_by and approved_at"
            )

    @property
    def lineage_key(self) -> str:
        """The same logical group across every version."""
        return self.search_intent_group_id

    @property
    def version_key(self) -> Tuple[str, int]:
        return (self.search_intent_group_id, self.search_intent_group_version)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SearchIntentGroup":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


def new_search_intent_group_version(
    group: SearchIntentGroup, **changes: Any
) -> SearchIntentGroup:
    """Apply an edit to a governed search intent group as a new version -
    never an in-place mutation of history, mirroring
    `core.search_objects.new_search_object_version`. Resets
    `approval_status`/`approved_by`/`approved_at` to draft; the caller must
    not pass those in `changes` (raises if attempted, to avoid silently
    fabricating an approval for the new version)."""
    for reset_field in ("approval_status", "approved_by", "approved_at"):
        if reset_field in changes:
            raise ValueError(
                f"new_search_intent_group_version must not receive "
                f"'{reset_field}' - a new version always starts as draft."
            )
    return replace(
        group,
        **changes,
        search_intent_group_version=group.search_intent_group_version + 1,
        approval_status="draft",
        approved_by=None,
        approved_at=None,
    )


# ---------------------------------------------------------------------------
# Approved minimum taxonomy content (REQ-SEARCH-004 addendum, 2026-08-30,
# Decision 2). Two top-level governed groups only - this is the entire
# approved content; a deeper split remains open (D4).
# ---------------------------------------------------------------------------

SEARCH_INTENT_GROUP_ID_BRAND = "brand_search"
SEARCH_INTENT_GROUP_ID_NON_BRAND = "non_brand_search"

BRAND_SEARCH_INTENT_GROUP = SearchIntentGroup(
    search_intent_group_id=SEARCH_INTENT_GROUP_ID_BRAND,
    search_intent_group_name="Brand",
    brand_class=BRAND_CLASS_BRAND,
    business_description="Paid Search activity targeting Ancestry's own brand terms.",
    cross_route_comparable_flag=True,
    owner="Modelling / Product-Marketing",
    approval_status="approved",
    approved_by="Post-UI/UX Implementation Instructions: Approved Business Decisions (Decision 2)",
    approved_at="2026-08-30",
)
NON_BRAND_SEARCH_INTENT_GROUP = SearchIntentGroup(
    search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
    search_intent_group_name="Non-Brand",
    brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
    business_description="Paid Search activity targeting generic, non-brand terms.",
    cross_route_comparable_flag=True,
    owner="Modelling / Product-Marketing",
    approval_status="approved",
    approved_by="Post-UI/UX Implementation Instructions: Approved Business Decisions (Decision 2)",
    approved_at="2026-08-30",
)

# The single source of truth for "what taxonomy groups are approved today" -
# callers validating an activity catalogue should pass this (or a superset
# that still contains these two) rather than hand-rolling their own set.
APPROVED_MINIMUM_SEARCH_INTENT_GROUPS: Tuple[SearchIntentGroup, ...] = (
    BRAND_SEARCH_INTENT_GROUP,
    NON_BRAND_SEARCH_INTENT_GROUP,
)


# ---------------------------------------------------------------------------
# Platform axis (orthogonal to intent group; Phase B implementation work
# named, but not done, by the REQ-SEARCH-004 addendum).
# ---------------------------------------------------------------------------

SEARCH_PLATFORM_GOOGLE = "google"
SEARCH_PLATFORM_BING = "bing"
SEARCH_PLATFORMS = (SEARCH_PLATFORM_GOOGLE, SEARCH_PLATFORM_BING)

# Campaign types confirmed excluded from the Paid Search taxonomy even
# though they may appear in a source system such as SA360 (Decision 2).
# Compared case-insensitively against `ActivityDefinition.campaign_type`.
NON_PAID_SEARCH_CAMPAIGN_TYPES = (
    "pmax",
    "performance_max",
    "demand_gen",
    "youtube",
)


def validate_activity_search_taxonomy(
    activities: Sequence[object],
    groups: Sequence[SearchIntentGroup] = APPROVED_MINIMUM_SEARCH_INTENT_GROUPS,
) -> List[str]:
    """Cross-check activities' `search_intent_group_id`/`search_platform`
    against a governed taxonomy catalogue (default: the approved minimum
    two-group taxonomy). Returns a list of specific, attributable issues -
    never silently drops or reclassifies a bad reference.

    Checks:
    - `search_intent_group_id`, when set, must reference a known group.
    - `search_platform`, when set, must be one of `SEARCH_PLATFORMS`.
    - An activity whose `campaign_type` is one of
      `NON_PAID_SEARCH_CAMPAIGN_TYPES` must not also carry a
      `search_intent_group_id` or `search_platform` (Decision 2's PMax/
      Demand Gen/YouTube exclusion).
    """
    issues: List[str] = []
    group_ids = {g.search_intent_group_id for g in groups}

    for activity in activities:
        activity_id = _attr(activity, "activity_id", "<unknown>")
        group_id = _attr(activity, "search_intent_group_id", None)
        platform = _attr(activity, "search_platform", "") or ""
        campaign_type = str(_attr(activity, "campaign_type", "") or "").strip().lower()

        if group_id and group_id not in group_ids:
            issues.append(
                f"Activity '{activity_id}' references unknown "
                f"search_intent_group_id '{group_id}' - not in the supplied "
                "governed taxonomy."
            )
        if platform and platform not in SEARCH_PLATFORMS:
            issues.append(
                f"Activity '{activity_id}' has unknown search_platform "
                f"'{platform}' (expected one of {SEARCH_PLATFORMS})."
            )
        if campaign_type in NON_PAID_SEARCH_CAMPAIGN_TYPES and (group_id or platform):
            issues.append(
                f"Activity '{activity_id}' has campaign_type "
                f"'{campaign_type}', which is excluded from the Paid Search "
                "taxonomy (Decision 2) - it must not carry a "
                "search_intent_group_id or search_platform."
            )
    return issues


def _attr(obj: object, key: str, default: Any) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Reporting roll-up hierarchy (Decision 4 / REQ-SEARCH-004 addendum).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchReportingCell:
    """One governed leaf reporting cell: a value (spend, or any other
    additive Search metric) at one `(search_intent_group_id, platform)`
    combination. Multiple cells for the same combination (e.g. one per
    market or week) are summed by the caller before calling
    `roll_up_paid_search_reporting`, or passed as separate cells - either
    way, this dataclass carries no market/week grain of its own; it is
    intentionally minimal so this module stays agnostic to whatever grain
    the caller is reporting at."""

    search_intent_group_id: str
    platform: str
    value: float


@dataclass(frozen=True)
class PaidSearchReportingRollup:
    """The full governed roll-up hierarchy, every level computed by
    summing its governed children - never accepted as a pre-supplied
    input (Decision 4). Only the four approved minimum leaf combinations
    (Google/Bing x Brand/Non-Brand) are recognised; an unrecognised
    combination is a validation error, not a silently-dropped or
    silently-included row (see `roll_up_paid_search_reporting`)."""

    google_brand: float
    bing_brand: float
    google_non_brand: float
    bing_non_brand: float

    @property
    def brand_search(self) -> float:
        return self.google_brand + self.bing_brand

    @property
    def non_brand_search(self) -> float:
        return self.google_non_brand + self.bing_non_brand

    @property
    def total_paid_search(self) -> float:
        return self.brand_search + self.non_brand_search

    def to_dict(self) -> dict:
        return {
            "google_brand": self.google_brand,
            "bing_brand": self.bing_brand,
            "google_non_brand": self.google_non_brand,
            "bing_non_brand": self.bing_non_brand,
            "brand_search": self.brand_search,
            "non_brand_search": self.non_brand_search,
            "total_paid_search": self.total_paid_search,
        }


_LEAF_COMBINATIONS: Dict[Tuple[str, str], str] = {
    (SEARCH_INTENT_GROUP_ID_BRAND, SEARCH_PLATFORM_GOOGLE): "google_brand",
    (SEARCH_INTENT_GROUP_ID_BRAND, SEARCH_PLATFORM_BING): "bing_brand",
    (SEARCH_INTENT_GROUP_ID_NON_BRAND, SEARCH_PLATFORM_GOOGLE): "google_non_brand",
    (SEARCH_INTENT_GROUP_ID_NON_BRAND, SEARCH_PLATFORM_BING): "bing_non_brand",
}


def roll_up_paid_search_reporting(
    cells: Sequence[SearchReportingCell],
) -> PaidSearchReportingRollup:
    """Compute the full roll-up hierarchy purely by summing governed leaf
    cells: Total Paid Search -> {Brand Search, Non-Brand Search} ->
    {Google Brand, Bing Brand} / {Google Non-Brand, Bing Non-Brand}
    (Decision 4). A market/segment absent from `cells` for a given leaf
    contributes zero to that leaf via ordinary summation over an empty
    set - this is standard additive roll-up behaviour, not a "missing is
    zero" fabrication (contrast `core.coverage`'s missingness vocabulary,
    which governs whether an *individual observed metric* is legitimately
    absent; this function only sums whatever cells the caller supplies).

    Raises `ValueError` naming every unrecognised `(search_intent_group_id,
    platform)` combination rather than silently ignoring or misattributing
    it - the four leaf combinations above are the entire currently-approved
    minimum split (Decision 2); a fifth combination (e.g. a future deeper
    Non-Brand keyword group) requires this function to be extended once
    that split is approved, not a caller silently working around it here.
    """
    totals = {label: 0.0 for label in _LEAF_COMBINATIONS.values()}
    unrecognised: set = set()
    for cell in cells:
        label = _LEAF_COMBINATIONS.get((cell.search_intent_group_id, cell.platform))
        if label is None:
            unrecognised.add((cell.search_intent_group_id, cell.platform))
            continue
        totals[label] += cell.value

    if unrecognised:
        raise ValueError(
            "roll_up_paid_search_reporting: unrecognised "
            "(search_intent_group_id, platform) combination(s) - not part "
            f"of the four approved minimum leaf groups: {sorted(unrecognised)}."
        )

    return PaidSearchReportingRollup(**totals)
