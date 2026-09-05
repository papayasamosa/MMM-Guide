"""Tests for `core.search_intent_taxonomy` (REQ-SEARCH-004, Decisions 2/4):
the approved minimum Brand/Non-Brand taxonomy content, the governed
Google/Bing platform axis, taxonomy cross-validation against an activity
catalogue, and the reporting roll-up hierarchy.
"""

import pytest

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.search_intent_taxonomy import (
    APPROVED_MINIMUM_SEARCH_INTENT_GROUPS,
    BRAND_CLASS_BRAND,
    BRAND_CLASS_GENERIC_NON_BRAND,
    BRAND_SEARCH_INTENT_GROUP,
    NON_BRAND_SEARCH_INTENT_GROUP,
    NON_PAID_SEARCH_CAMPAIGN_TYPES,
    SEARCH_INTENT_GROUP_ID_BRAND,
    SEARCH_INTENT_GROUP_ID_NON_BRAND,
    SEARCH_PLATFORM_BING,
    SEARCH_PLATFORM_GOOGLE,
    SEARCH_PLATFORMS,
    PaidSearchReportingRollup,
    SearchIntentGroup,
    SearchReportingCell,
    new_search_intent_group_version,
    roll_up_paid_search_reporting,
    roll_up_paid_search_reporting_hierarchy,
    resolve_search_model_input_columns,
    resolve_imported_search_intent_group_versions,
    search_intent_taxonomy_fit_fingerprint,
    validate_activity_search_taxonomy,
)


class TestApprovedMinimumTaxonomy:
    def test_exactly_two_top_level_groups(self):
        """Decision 2: the approved minimum content is exactly Brand and
        Non-Brand, no more."""
        assert len(APPROVED_MINIMUM_SEARCH_INTENT_GROUPS) == 2

    def test_brand_and_non_brand_are_distinct_brand_classes(self):
        assert BRAND_SEARCH_INTENT_GROUP.brand_class == BRAND_CLASS_BRAND
        assert (
            NON_BRAND_SEARCH_INTENT_GROUP.brand_class == BRAND_CLASS_GENERIC_NON_BRAND
        )

    def test_both_groups_are_approved(self):
        for group in APPROVED_MINIMUM_SEARCH_INTENT_GROUPS:
            assert group.approval_status == "approved"
            assert group.approved_by
            assert group.approved_at

    def test_both_groups_are_cross_route_comparable(self):
        """REQ-SEARCH-004 §5: sharable across paid and organic routes."""
        for group in APPROVED_MINIMUM_SEARCH_INTENT_GROUPS:
            assert group.cross_route_comparable_flag is True

    def test_neither_group_has_a_parent(self):
        """Both are top-level per REQ-SEARCH-004's addendum."""
        for group in APPROVED_MINIMUM_SEARCH_INTENT_GROUPS:
            assert group.parent_search_intent_group_id is None


class TestSearchIntentGroupConstruction:
    def test_unknown_brand_class_rejected(self):
        with pytest.raises(ValueError, match="unknown brand_class"):
            SearchIntentGroup(
                search_intent_group_id="x",
                search_intent_group_name="X",
                brand_class="not_a_real_class",
            )

    def test_cannot_be_its_own_parent(self):
        with pytest.raises(ValueError, match="cannot be its own parent"):
            SearchIntentGroup(
                search_intent_group_id="x",
                search_intent_group_name="X",
                brand_class=BRAND_CLASS_BRAND,
                parent_search_intent_group_id="x",
            )

    def test_approved_requires_approver_metadata(self):
        with pytest.raises(ValueError, match="require approved_by"):
            SearchIntentGroup(
                search_intent_group_id="x",
                search_intent_group_name="X",
                brand_class=BRAND_CLASS_BRAND,
                approval_status="approved",
            )

    def test_future_deeper_non_brand_group_can_nest_without_schema_change(self):
        """A future Non-Brand keyword/search-term group (D4, still open)
        can already reference Non-Brand as its parent with the existing
        schema - no redesign needed when that split is eventually
        approved."""
        future_group = SearchIntentGroup(
            search_intent_group_id="non_brand_generic_keywords",
            search_intent_group_name="Non-Brand: Generic Keywords",
            brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
            parent_search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
        )
        assert (
            future_group.parent_search_intent_group_id
            == SEARCH_INTENT_GROUP_ID_NON_BRAND
        )

    def test_round_trip_through_dict(self):
        restored = SearchIntentGroup.from_dict(BRAND_SEARCH_INTENT_GROUP.to_dict())
        assert restored == BRAND_SEARCH_INTENT_GROUP


class TestNewSearchIntentGroupVersion:
    def test_bumps_version_and_resets_to_draft(self):
        edited = new_search_intent_group_version(
            BRAND_SEARCH_INTENT_GROUP, business_description="Updated description"
        )
        assert edited.search_intent_group_version == 2
        assert edited.approval_status == "draft"
        assert edited.approved_by is None
        assert edited.approved_at is None
        assert edited.business_description == "Updated description"
        # Original is untouched - never an in-place mutation.
        assert BRAND_SEARCH_INTENT_GROUP.search_intent_group_version == 1
        assert BRAND_SEARCH_INTENT_GROUP.approval_status == "approved"

    def test_cannot_smuggle_in_a_fabricated_approval(self):
        with pytest.raises(ValueError, match="must not receive"):
            new_search_intent_group_version(
                BRAND_SEARCH_INTENT_GROUP, approval_status="approved"
            )


def test_malformed_imported_taxonomy_history_is_quarantined_without_losing_valid_rows():
    child = SearchIntentGroup(
        search_intent_group_id="non_brand_genealogy",
        search_intent_group_name="Genealogy",
        brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
        parent_search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
    )
    valid = child.to_dict()
    malformed_version = {**valid, "search_intent_group_version": "not-an-int"}
    malformed_lineage = {
        **valid,
        "search_intent_group_version": 2,
        "supersedes_search_intent_group_id": "missing-group",
    }

    restored, warnings = resolve_imported_search_intent_group_versions(
        [valid, malformed_version, malformed_lineage],
        current_groups=[child],
    )

    assert restored == [valid]
    assert len(warnings) == 2
    assert all("quarantined" in warning for warning in warnings)


def test_history_lineage_cannot_rely_on_a_quarantined_record():
    child = SearchIntentGroup(
        search_intent_group_id="non_brand_genealogy",
        search_intent_group_name="Genealogy",
        brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
        parent_search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
    )
    dependent = {
        **child.to_dict(),
        "search_intent_group_id": "dependent",
        "supersedes_search_intent_group_id": "quarantined",
    }
    quarantined = {
        **child.to_dict(),
        "search_intent_group_id": "quarantined",
        "parent_search_intent_group_id": "missing-parent",
    }

    restored, warnings = resolve_imported_search_intent_group_versions(
        [dependent, quarantined], current_groups=[child]
    )

    assert restored == []
    assert len(warnings) == 2


class _FakeActivity:
    def __init__(
        self,
        activity_id,
        search_intent_group_id=None,
        search_platform="",
        campaign_type="",
        planning_eligibility="excluded",
        economic_treatment="response_only",
        model_input_column="",
        channel="search_input",
    ):
        self.activity_id = activity_id
        self.search_intent_group_id = search_intent_group_id
        self.search_platform = search_platform
        self.campaign_type = campaign_type
        self.planning_eligibility = planning_eligibility
        self.economic_treatment = economic_treatment
        self.model_input_column = model_input_column
        self.channel = channel


class TestValidateActivitySearchTaxonomy:
    def test_valid_references_pass(self):
        activities = [
            _FakeActivity(
                "g-brand", SEARCH_INTENT_GROUP_ID_BRAND, SEARCH_PLATFORM_GOOGLE
            ),
            _FakeActivity(
                "b-nonbrand", SEARCH_INTENT_GROUP_ID_NON_BRAND, SEARCH_PLATFORM_BING
            ),
        ]
        assert validate_activity_search_taxonomy(activities) == []

    def test_unknown_group_id_rejected(self):
        activities = [_FakeActivity("x", "not_a_real_group", SEARCH_PLATFORM_GOOGLE)]
        issues = validate_activity_search_taxonomy(activities)
        assert any("unknown search_intent_group_id" in i for i in issues)

    def test_unknown_platform_rejected(self):
        activities = [_FakeActivity("x", SEARCH_INTENT_GROUP_ID_BRAND, "yahoo")]
        issues = validate_activity_search_taxonomy(activities)
        assert any("unknown search_platform" in i for i in issues)

    @pytest.mark.parametrize("campaign_type", NON_PAID_SEARCH_CAMPAIGN_TYPES)
    def test_pmax_demand_gen_youtube_excluded(self, campaign_type):
        """Decision 2: PMax/Demand Gen/YouTube must never enter this
        taxonomy even if a source system labels them similarly."""
        activities = [
            _FakeActivity(
                "x",
                SEARCH_INTENT_GROUP_ID_BRAND,
                SEARCH_PLATFORM_GOOGLE,
                campaign_type=campaign_type,
            )
        ]
        issues = validate_activity_search_taxonomy(activities)
        assert any("excluded from the Paid Search taxonomy" in i for i in issues)

    def test_pmax_without_taxonomy_reference_is_fine(self):
        """Excluding PMax from the taxonomy does not mean PMax activities
        are themselves invalid - only that they must not carry a taxonomy
        reference."""
        activities = [_FakeActivity("x", campaign_type="pmax")]
        assert validate_activity_search_taxonomy(activities) == []

    def test_deeper_child_planning_and_cost_economics_fail_closed(self):
        child = SearchIntentGroup(
            search_intent_group_id="non_brand_generic_keywords",
            search_intent_group_name="Non-Brand: Generic Keywords",
            brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
            parent_search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
        )
        activity = _FakeActivity(
            "child",
            child.search_intent_group_id,
            SEARCH_PLATFORM_GOOGLE,
            planning_eligibility="optimisable",
            economic_treatment="paid_media_cost",
        )
        issues = validate_activity_search_taxonomy(
            [activity], (*APPROVED_MINIMUM_SEARCH_INTENT_GROUPS, child)
        )
        assert any("planning remains excluded" in issue for issue in issues)
        assert any("cost-bearing economic_treatment" in issue for issue in issues)


def test_search_taxonomy_fit_fingerprint_binds_consumed_group_metadata():
    child = SearchIntentGroup(
        search_intent_group_id="non_brand_generic_keywords",
        search_intent_group_name="Non-Brand: Generic Keywords",
        brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
        parent_search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
    )
    activity = _FakeActivity(
        "child", child.search_intent_group_id, model_input_column="search_input"
    )
    first = search_intent_taxonomy_fit_fingerprint(
        [activity],
        [child],
        [child.to_dict()],
        consumed_model_input_columns=["search_input"],
    )
    changed = SearchIntentGroup(
        **{**child.to_dict(), "search_intent_group_name": "Changed name"}
    )
    second = search_intent_taxonomy_fit_fingerprint(
        [activity],
        [changed],
        [changed.to_dict()],
        consumed_model_input_columns=["search_input"],
    )
    assert first != second


class TestPaidSearchReportingRollup:
    def _cells(self, google_brand=0.0, bing_brand=0.0, google_nb=0.0, bing_nb=0.0):
        cells = []
        if google_brand:
            cells.append(
                SearchReportingCell(
                    SEARCH_INTENT_GROUP_ID_BRAND, SEARCH_PLATFORM_GOOGLE, google_brand
                )
            )
        if bing_brand:
            cells.append(
                SearchReportingCell(
                    SEARCH_INTENT_GROUP_ID_BRAND, SEARCH_PLATFORM_BING, bing_brand
                )
            )
        if google_nb:
            cells.append(
                SearchReportingCell(
                    SEARCH_INTENT_GROUP_ID_NON_BRAND, SEARCH_PLATFORM_GOOGLE, google_nb
                )
            )
        if bing_nb:
            cells.append(
                SearchReportingCell(
                    SEARCH_INTENT_GROUP_ID_NON_BRAND, SEARCH_PLATFORM_BING, bing_nb
                )
            )
        return cells

    def test_google_brand_plus_bing_brand_equals_brand_search(self):
        rollup = roll_up_paid_search_reporting(
            self._cells(google_brand=100.0, bing_brand=25.0)
        )
        assert rollup.brand_search == pytest.approx(125.0)

    def test_brand_plus_non_brand_equals_total_paid_search(self):
        rollup = roll_up_paid_search_reporting(
            self._cells(
                google_brand=100.0, bing_brand=25.0, google_nb=200.0, bing_nb=50.0
            )
        )
        assert rollup.brand_search == pytest.approx(125.0)
        assert rollup.non_brand_search == pytest.approx(250.0)
        assert rollup.total_paid_search == pytest.approx(375.0)

    def test_four_minimum_groups_are_the_required_leaves(self):
        """The four minimum groups (Google Brand, Google Non-Brand, Bing
        Brand, Bing Non-Brand) are exactly the leaves this hierarchy
        recognises."""
        rollup = roll_up_paid_search_reporting([])
        as_dict = rollup.to_dict()
        for leaf in (
            "google_brand",
            "bing_brand",
            "google_non_brand",
            "bing_non_brand",
        ):
            assert leaf in as_dict

    def test_missing_leaf_defaults_to_zero_not_error(self):
        """Ragged coverage (a market with only Brand data) is valid -
        an absent leaf combination contributes zero via ordinary
        summation, it does not block the roll-up."""
        rollup = roll_up_paid_search_reporting(self._cells(google_brand=100.0))
        assert rollup.bing_brand == 0.0
        assert rollup.non_brand_search == 0.0
        assert rollup.total_paid_search == pytest.approx(100.0)

    def test_unrecognised_combination_fails_closed(self):
        """A fifth (search_intent_group_id, platform) combination - e.g. a
        future deeper Non-Brand keyword group not yet part of this
        hierarchy - is a hard error, never silently dropped or
        misattributed."""
        bad_cells = [
            SearchReportingCell(
                "non_brand_generic_keywords", SEARCH_PLATFORM_GOOGLE, 10.0
            )
        ]
        with pytest.raises(ValueError, match="unrecognised"):
            roll_up_paid_search_reporting(bad_cells)

    def test_parent_totals_are_never_pre_supplied(self):
        """Decision 4: parent totals are computed, never accepted as an
        input - PaidSearchReportingRollup has no field a caller could set
        to override the computed brand_search/non_brand_search/
        total_paid_search values; they are derived properties."""
        assert "brand_search" not in {
            f.name for f in PaidSearchReportingRollup.__dataclass_fields__.values()
        }
        assert "total_paid_search" not in {
            f.name for f in PaidSearchReportingRollup.__dataclass_fields__.values()
        }


class TestPlatformAxisIsOrthogonal:
    def test_platforms_are_exactly_google_and_bing(self):
        assert set(SEARCH_PLATFORMS) == {SEARCH_PLATFORM_GOOGLE, SEARCH_PLATFORM_BING}

    def test_platform_values_never_combine_intent_group_into_one_enum(self):
        """The REQ-SEARCH-004 addendum's explicit instruction: platform and
        intent-group are two independent dimensions, never one combined
        value like 'google_brand'."""
        for platform in SEARCH_PLATFORMS:
            assert "brand" not in platform


class TestHierarchicalPaidSearchReporting:
    def test_parent_and_child_inputs_fail_closed_to_prevent_double_counting(self):
        child = SearchIntentGroup(
            search_intent_group_id="non_brand_generic_keywords",
            search_intent_group_name="Non-Brand: Generic Keywords",
            brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
            parent_search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
        )
        cells = [
            SearchReportingCell(
                SEARCH_INTENT_GROUP_ID_NON_BRAND, SEARCH_PLATFORM_GOOGLE, 100.0
            ),
            SearchReportingCell(
                child.search_intent_group_id, SEARCH_PLATFORM_GOOGLE, 25.0
            ),
        ]
        with pytest.raises(ValueError, match="double counting"):
            roll_up_paid_search_reporting_hierarchy(
                cells, (*APPROVED_MINIMUM_SEARCH_INTENT_GROUPS, child)
            )


def _search_activity(activity_id: str, column: str, group_id: str):
    return ActivityDefinition(
        activity_id=activity_id,
        channel=column,
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="excluded",
        source="test",
        model_input_column=column,
        search_intent_group_id=group_id,
        search_platform=SEARCH_PLATFORM_GOOGLE,
    )


class TestSearchModelInputResolution:
    def test_selected_grain_is_applied_before_model_construction(self):
        child = SearchIntentGroup(
            search_intent_group_id="non_brand_search_genealogy",
            search_intent_group_name="Genealogy Non-Brand",
            brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
            parent_search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
        )
        groups = (*APPROVED_MINIMUM_SEARCH_INTENT_GROUPS, child)
        activities = [
            _search_activity("brand", "paid_brand", SEARCH_INTENT_GROUP_ID_BRAND),
            _search_activity("child", "paid_genealogy", child.search_intent_group_id),
        ]

        assert resolve_search_model_input_columns(
            ["paid_brand", "paid_genealogy", "TV"],
            [SEARCH_INTENT_GROUP_ID_BRAND],
            groups,
            activities,
        ) == ("paid_brand", "TV")
        assert resolve_search_model_input_columns(
            ["paid_brand", "paid_genealogy", "TV"],
            [child.search_intent_group_id],
            groups,
            activities,
        ) == ("paid_genealogy", "TV")

    def test_shared_physical_input_fails_closed_for_mixed_search_grains(self):
        activities = [
            _search_activity("brand", "paid_search", SEARCH_INTENT_GROUP_ID_BRAND),
            _search_activity(
                "non-brand", "paid_search", SEARCH_INTENT_GROUP_ID_NON_BRAND
            ),
        ]

        with pytest.raises(ValueError, match="both selected Search grain"):
            resolve_search_model_input_columns(
                ["paid_search", "TV"],
                [SEARCH_INTENT_GROUP_ID_BRAND],
                APPROVED_MINIMUM_SEARCH_INTENT_GROUPS,
                activities,
            )
