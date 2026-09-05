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

The approved reporting content remains the two top-level Brand and
Non-Brand groups. This module now permits explicitly supplied deeper
Non-Brand draft groups, as requested by the current implementation brief,
but does not approve, auto-invent, auto-fit, or promote them. The evidence
threshold that would make a child separately reportable remains open; this
module does not invent a numeric threshold or a third hierarchy level.

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
        if type(self.search_intent_group_version) is not int:
            raise ValueError("search_intent_group_version must be an integer.")
        if self.search_intent_group_version < 1:
            raise ValueError("search_intent_group_version must be >= 1.")
        if (
            type(self.schema_version) is not int
            or self.schema_version != SEARCH_INTENT_TAXONOMY_SCHEMA_VERSION
        ):
            raise ValueError(
                "unsupported or malformed search intent taxonomy schema_version."
            )
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
# Decision 2). Two top-level governed groups are the approved content;
# explicitly supplied deeper draft children may be added without changing
# that minimum.
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


def validate_search_intent_group_catalogue(
    groups: Sequence[SearchIntentGroup],
) -> List[str]:
    """Validate an explicit parent/child taxonomy without inventing groups."""
    issues: List[str] = []
    by_id: Dict[str, SearchIntentGroup] = {}
    for group in groups:
        if group.search_intent_group_id in by_id:
            issues.append(
                f"Duplicate search intent group id '{group.search_intent_group_id}'."
            )
        by_id[group.search_intent_group_id] = group
    for group in groups:
        parent = group.parent_search_intent_group_id
        if parent and parent not in by_id:
            issues.append(
                f"Search intent group '{group.search_intent_group_id}' references unknown parent '{parent}'."
            )
        if parent and parent != SEARCH_INTENT_GROUP_ID_NON_BRAND:
            issues.append(
                f"Deeper search intent group '{group.search_intent_group_id}' must be governed under Non-Brand Search."
            )
    for group in groups:
        seen = {group.search_intent_group_id}
        parent = group.parent_search_intent_group_id
        while parent:
            if parent in seen:
                issues.append(f"Search intent group parent cycle includes '{parent}'.")
                break
            seen.add(parent)
            ancestor = by_id.get(parent)
            parent = (
                ancestor.parent_search_intent_group_id if ancestor is not None else None
            )
    return issues


def governed_search_intent_groups(
    additional_groups: Sequence[SearchIntentGroup] = (),
) -> Tuple[SearchIntentGroup, ...]:
    """Merge the approved minimum with explicitly supplied governed children."""
    by_id = {
        group.search_intent_group_id: group
        for group in APPROVED_MINIMUM_SEARCH_INTENT_GROUPS
    }
    for group in additional_groups:
        by_id[group.search_intent_group_id] = group
    issues = validate_search_intent_group_catalogue(tuple(by_id.values()))
    if issues:
        raise ValueError("Invalid search intent taxonomy: " + "; ".join(issues))
    return tuple(sorted(by_id.values(), key=lambda group: group.search_intent_group_id))


def resolve_imported_search_intent_groups(
    values: Sequence[SearchIntentGroup | Mapping[str, Any]],
) -> Tuple[SearchIntentGroup, ...]:
    """Restore imported custom groups on top of repository-approved parents.

    Project bundles intentionally persist custom children only.  The approved
    Brand and Non-Brand parents are repository authority and are merged before
    parent/child validation, so a valid child is not quarantined merely
    because its approved parent was omitted from the bundle.
    """

    imported: list[SearchIntentGroup] = []
    for value in values:
        if isinstance(value, SearchIntentGroup):
            imported.append(value)
        elif isinstance(value, Mapping):
            imported.append(SearchIntentGroup.from_dict(value))
    custom_groups = tuple(
        group
        for group in imported
        if group.search_intent_group_id
        not in {SEARCH_INTENT_GROUP_ID_BRAND, SEARCH_INTENT_GROUP_ID_NON_BRAND}
    )
    return governed_search_intent_groups(custom_groups)


def resolve_imported_search_intent_group_versions(
    values: Sequence[SearchIntentGroup | Mapping[str, Any]] | None,
    *,
    current_groups: Sequence[SearchIntentGroup] = (),
) -> Tuple[List[dict], List[str]]:
    """Validate the append-only Search taxonomy version history on import.

    Current taxonomy records and their history have different purposes: the
    approved Brand/Non-Brand parents and the current custom children are the
    live catalogue, while this collection is an audit trail.  A malformed
    history record must therefore be quarantined without discarding an
    otherwise valid current catalogue.  In particular, do not let JSON type
    coercion turn an invalid version or lineage reference into a usable
    record that can later break the editor or be re-exported.
    """

    warnings: List[str] = []
    if values is None or values == []:
        return [], warnings
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        return [], [
            "Search intent taxonomy version history is not a sequence and was "
            "quarantined (dropped, not silently kept)."
        ]

    known_ids = {
        group.search_intent_group_id for group in APPROVED_MINIMUM_SEARCH_INTENT_GROUPS
    }
    known_ids.update(group.search_intent_group_id for group in current_groups)
    parsed: List[tuple[int, SearchIntentGroup]] = []
    seen_keys: set[Tuple[str, int]] = set()

    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            warnings.append(
                f"Search intent taxonomy version record {index} is not a mapping "
                "and was quarantined (dropped, not silently kept)."
            )
            continue
        try:
            group = SearchIntentGroup.from_dict(value)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            group_id = value.get("search_intent_group_id", "<unknown>")
            warnings.append(
                f"Search intent taxonomy version record {index} "
                f"(search_intent_group_id={group_id!r}) was malformed and was "
                f"quarantined (dropped, not silently kept): {exc}"
            )
            continue
        key = group.version_key
        if key in seen_keys:
            warnings.append(
                f"Search intent taxonomy version record {index} "
                f"({key[0]!r}, version {key[1]}) duplicated an existing history "
                "record and was quarantined (dropped, not silently kept)."
            )
            continue
        seen_keys.add(key)
        known_ids.add(group.search_intent_group_id)
        parsed.append((index, group))

    normalised: List[dict] = []
    for index, group in parsed:
        parent = group.parent_search_intent_group_id
        supersedes = group.supersedes_search_intent_group_id
        issue: str | None = None
        if parent and parent not in known_ids:
            issue = f"references unknown parent {parent!r}"
        elif parent and parent != SEARCH_INTENT_GROUP_ID_NON_BRAND:
            issue = "has a deeper-group parent other than Non-Brand Search"
        elif supersedes is not None and (
            not isinstance(supersedes, str)
            or not supersedes.strip()
            or supersedes not in known_ids
        ):
            issue = f"references unknown superseded group {supersedes!r}"
        if issue:
            warnings.append(
                f"Search intent taxonomy version record {index} "
                f"({group.search_intent_group_id!r}, version "
                f"{group.search_intent_group_version}) {issue} and was "
                "quarantined (dropped, not silently kept)."
            )
            continue
        normalised.append(group.to_dict())
    return normalised, warnings


def resolve_search_intent_model_grain(
    requested_group_ids: Sequence[str],
    groups: Sequence[SearchIntentGroup],
) -> Tuple[str, ...]:
    """Resolve an explicit Search model grain without parent/child double fit.

    An empty selection means the approved parent grain. A deeper child is
    usable only when it is selected explicitly; selecting both that child and
    its parent is rejected. This helper does not infer child economics or
    planning eligibility from taxonomy membership.
    """
    catalogue = governed_search_intent_groups(groups)
    by_id = {group.search_intent_group_id: group for group in catalogue}
    requested = tuple(
        dict.fromkeys(
            str(value).strip() for value in requested_group_ids if str(value).strip()
        )
    )
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise ValueError(f"Unknown Search model-grain group(s): {', '.join(unknown)}")
    if not requested:
        return (SEARCH_INTENT_GROUP_ID_BRAND, SEARCH_INTENT_GROUP_ID_NON_BRAND)
    parents = {
        group.parent_search_intent_group_id
        for group in (by_id[group_id] for group_id in requested)
        if group.parent_search_intent_group_id
    }
    overlap = sorted(set(requested) & parents)
    if overlap:
        raise ValueError(
            "Search model grain cannot select a parent and its deeper child "
            f"together: {', '.join(overlap)}"
        )
    return requested


def resolve_search_model_input_columns(
    model_input_columns: Sequence[str],
    requested_group_ids: Sequence[str],
    groups: Sequence[SearchIntentGroup],
    activity_definitions: Sequence[Any] = (),
) -> Tuple[str, ...]:
    """Resolve fitted model inputs for one explicit Search grain.

    ``ModelSpec.channels`` is the engine's physical input boundary, while
    ``ActivityDefinition.search_intent_group_id`` is the governed Search
    taxonomy reference.  This adapter applies the latter to the former before
    model construction.  A physical input shared by selected and unselected
    Search groups is rejected because the current engine boundary cannot
    represent a market-specific split of one column without double counting.
    Non-Search or unclassified inputs remain in the fit.
    """

    catalogue = governed_search_intent_groups(groups)
    selected = set(resolve_search_intent_model_grain(requested_group_ids, catalogue))
    known_ids = {group.search_intent_group_id for group in catalogue}
    input_groups: Dict[str, set[str]] = {}
    for activity in activity_definitions:
        if isinstance(activity, Mapping):
            input_column = str(
                activity.get("model_input_column") or activity.get("channel") or ""
            )
            group_id = activity.get("search_intent_group_id")
        else:
            input_column = str(
                getattr(activity, "resolved_model_input_column", "") or ""
            )
            group_id = getattr(activity, "search_intent_group_id", None)
        if not input_column or input_column not in model_input_columns or not group_id:
            continue
        group_id = str(group_id)
        if group_id not in known_ids:
            raise ValueError(
                f"Activity input '{input_column}' references unknown Search intent "
                f"group '{group_id}'."
            )
        input_groups.setdefault(input_column, set()).add(group_id)

    resolved: list[str] = []
    for column in model_input_columns:
        groups_for_input = input_groups.get(column)
        if not groups_for_input:
            resolved.append(column)
            continue
        selected_groups = groups_for_input & selected
        unselected_groups = groups_for_input - selected
        if selected_groups and unselected_groups:
            raise ValueError(
                f"Model input '{column}' is mapped to both selected Search grain "
                f"{sorted(selected_groups)} and unselected grain "
                f"{sorted(unselected_groups)}; split the physical inputs before fitting."
            )
        if selected_groups:
            resolved.append(column)
    if not resolved:
        raise ValueError(
            "The selected Search model grain does not resolve to any model input "
            "column."
        )
    return tuple(resolved)


# ---------------------------------------------------------------------------
# Platform axis (orthogonal to intent group; Google/Bing are the governed
# current values).
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
    - A deeper Non-Brand child cannot be marked `optimisable` until it has
      child-level observed and governed cost support.
    """
    issues: List[str] = []
    catalogue = governed_search_intent_groups(groups)
    by_id = {g.search_intent_group_id: g for g in catalogue}
    group_ids = set(by_id)

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
        referenced_group = by_id.get(group_id) if group_id else None
        if (
            referenced_group is not None
            and referenced_group.parent_search_intent_group_id is not None
            and _attr(activity, "planning_eligibility", "excluded") == "optimisable"
        ):
            issues.append(
                f"Activity '{activity_id}' references deeper Search intent group "
                f"'{group_id}' but is marked optimisable. Deeper child economics "
                "and planning remain unavailable until child-level observed and "
                "governed cost evidence is supplied."
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


def roll_up_paid_search_reporting_hierarchy(
    cells: Sequence[SearchReportingCell],
    groups: Sequence[SearchIntentGroup],
) -> dict:
    """Roll up ragged parent/child intent coverage without parent duplication.

    The existing ``PaidSearchReportingRollup`` remains the stable four-leaf
    API.  This general form is used when explicitly governed deeper
    Non-Brand children are present; economics/planning eligibility is not
    inferred from their existence.
    """
    catalogue = governed_search_intent_groups(groups)
    by_id = {group.search_intent_group_id: group for group in catalogue}
    leaf_totals: Dict[Tuple[str, str], float] = {}
    supplied_by_platform: Dict[str, set[str]] = {}
    for cell in cells:
        if cell.search_intent_group_id not in by_id:
            raise ValueError(
                f"Unknown governed Search intent group '{cell.search_intent_group_id}'."
            )
        if cell.platform not in SEARCH_PLATFORMS:
            raise ValueError(f"Unknown Search platform '{cell.platform}'.")
        supplied_by_platform.setdefault(cell.platform, set()).add(
            cell.search_intent_group_id
        )
        key = (cell.search_intent_group_id, cell.platform)
        leaf_totals[key] = leaf_totals.get(key, 0.0) + float(cell.value)
    for platform, supplied_ids in supplied_by_platform.items():
        for parent in by_id.values():
            child_ids = {
                group.search_intent_group_id
                for group in by_id.values()
                if group.parent_search_intent_group_id == parent.search_intent_group_id
            }
            overlap = sorted({parent.search_intent_group_id} & supplied_ids)
            if overlap and child_ids & supplied_ids:
                raise ValueError(
                    f"Search hierarchy input for platform '{platform}' contains "
                    f"parent '{parent.search_intent_group_id}' and child group(s) "
                    f"{sorted(child_ids & supplied_ids)}; provide one governed "
                    "model/reporting grain to prevent double counting."
                )
    group_totals: Dict[str, float] = {
        group.search_intent_group_id: 0.0 for group in catalogue
    }
    for (group_id, _platform), value in leaf_totals.items():
        current: Optional[str] = group_id
        while current is not None:
            group = by_id.get(current)
            if group is None:
                break
            group_totals[current] += value
            current = group.parent_search_intent_group_id
    non_brand_children = [
        group.search_intent_group_id
        for group in catalogue
        if group.parent_search_intent_group_id == SEARCH_INTENT_GROUP_ID_NON_BRAND
    ]
    return {
        "leaves": {
            f"{group_id}:{platform}": value
            for (group_id, platform), value in sorted(leaf_totals.items())
        },
        "groups": group_totals,
        "total_paid_search": group_totals[SEARCH_INTENT_GROUP_ID_BRAND]
        + group_totals[SEARCH_INTENT_GROUP_ID_NON_BRAND],
        "non_brand_children": non_brand_children,
    }
