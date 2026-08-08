"""Tests for core.search_objects (REQ-SEARCH-001) - governed identity for
branded-search demand, Paid Search spend/delivery/cap, organic-search
capture, and direct-navigation capture."""

import pytest

from ancestry_mmm.core.causal_graph import (
    NODE_ROLE_CAPACITY_OR_CAP,
    NODE_ROLE_DEMAND_CAPTURE,
    NODE_ROLE_INTERVENTION,
)
from ancestry_mmm.core.search_objects import (
    SEARCH_ROLE_DEMAND,
    SEARCH_ROLE_DIRECT_NAV_CAPTURE,
    SEARCH_ROLE_ORGANIC_CAPTURE,
    SEARCH_ROLE_PAID_CAP,
    SEARCH_ROLE_PAID_DELIVERY,
    SEARCH_ROLE_PAID_SPEND,
    UNIT_EXPOSURE_COUNT,
    UNIT_INDEX,
    UNIT_MONETARY,
    UNIT_RESPONSE_COUNT,
    SearchObjectDefinition,
    graph_node_role_for_search_object,
    search_objects_fingerprint,
    validate_search_object_catalogue,
)


def _spend(**overrides):
    values = dict(
        search_object_id="uk_paid_search_spend",
        search_role=SEARCH_ROLE_PAID_SPEND,
        source_column="paid_search_gbp_spend",
        unit=UNIT_MONETARY,
        currency="GBP",
        market="UK",
        planning_eligibility="optimisable",
    )
    values.update(overrides)
    return SearchObjectDefinition(**values)


def _demand(**overrides):
    values = dict(
        search_object_id="uk_search_demand",
        search_role=SEARCH_ROLE_DEMAND,
        source_column="branded_query_index",
        unit=UNIT_INDEX,
        market="UK",
    )
    values.update(overrides)
    return SearchObjectDefinition(**values)


class TestSearchObjectDefinitionValidation:
    def test_valid_paid_spend_object_constructs(self):
        obj = _spend()
        assert obj.search_role == SEARCH_ROLE_PAID_SPEND
        assert obj.currency == "GBP"

    def test_valid_demand_object_constructs(self):
        obj = _demand()
        assert obj.unit == UNIT_INDEX

    def test_unknown_search_role_is_rejected(self):
        with pytest.raises(ValueError, match="invalid search_role"):
            _demand(search_role="not_a_real_role")

    def test_monetary_unit_rejected_for_search_demand(self):
        """REQ-SEARCH-001 S14 example: a GBP spend column can never be
        branded-search demand."""
        with pytest.raises(ValueError, match="cannot be denominated in"):
            _demand(unit=UNIT_MONETARY, currency="GBP")

    def test_exposure_unit_rejected_for_paid_search_spend(self):
        with pytest.raises(ValueError, match="cannot be denominated in"):
            _spend(unit=UNIT_EXPOSURE_COUNT, currency="")

    def test_response_count_rejected_for_paid_search_delivery(self):
        """REQ-SEARCH-001 S14 example: organic traffic is not Paid Search
        delivery - delivery must be an exposure count, not a response
        count."""
        with pytest.raises(ValueError, match="cannot be denominated in"):
            SearchObjectDefinition(
                search_object_id="uk_paid_search_delivery",
                search_role=SEARCH_ROLE_PAID_DELIVERY,
                source_column="organic_sessions",
                unit=UNIT_RESPONSE_COUNT,
                market="UK",
            )

    def test_currency_required_when_unit_is_monetary(self):
        with pytest.raises(ValueError, match="currency is required"):
            _spend(currency="")

    def test_currency_must_be_blank_when_unit_is_not_monetary(self):
        with pytest.raises(ValueError, match="currency must be blank"):
            _demand(currency="GBP")

    def test_paid_search_cap_may_be_monetary_or_exposure(self):
        monetary_cap = SearchObjectDefinition(
            search_object_id="uk_paid_search_budget_cap",
            search_role=SEARCH_ROLE_PAID_CAP,
            source_column="daily_budget_cap_gbp",
            unit=UNIT_MONETARY,
            currency="GBP",
            market="UK",
        )
        exposure_cap = SearchObjectDefinition(
            search_object_id="uk_paid_search_delivery_cap",
            search_role=SEARCH_ROLE_PAID_CAP,
            source_column="daily_impression_cap",
            unit=UNIT_EXPOSURE_COUNT,
            market="UK",
        )
        assert monetary_cap.unit == UNIT_MONETARY
        assert exposure_cap.unit == UNIT_EXPOSURE_COUNT

    def test_demand_capture_role_can_never_be_optimisable(self):
        with pytest.raises(ValueError, match="can never be 'optimisable'"):
            _demand(planning_eligibility="optimisable")

    def test_organic_capture_can_never_be_optimisable(self):
        with pytest.raises(ValueError, match="can never be 'optimisable'"):
            SearchObjectDefinition(
                search_object_id="uk_organic_search",
                search_role=SEARCH_ROLE_ORGANIC_CAPTURE,
                source_column="organic_search_sessions",
                unit=UNIT_RESPONSE_COUNT,
                market="UK",
                planning_eligibility="optimisable",
            )

    def test_paid_search_cap_can_never_be_optimisable(self):
        with pytest.raises(ValueError, match="can never be 'optimisable'"):
            SearchObjectDefinition(
                search_object_id="uk_paid_search_cap",
                search_role=SEARCH_ROLE_PAID_CAP,
                source_column="daily_budget_cap_gbp",
                unit=UNIT_MONETARY,
                currency="GBP",
                market="UK",
                planning_eligibility="optimisable",
            )

    def test_paid_search_spend_may_be_optimisable(self):
        obj = _spend(planning_eligibility="optimisable")
        assert obj.planning_eligibility == "optimisable"

    def test_approved_requires_approved_by_and_approved_at(self):
        with pytest.raises(ValueError, match="require approved_by and approved_at"):
            _spend(approval_status="approved")

    def test_approved_with_full_metadata_constructs(self):
        obj = _spend(
            approval_status="approved",
            approved_by="analyst",
            approved_at="2026-08-07T00:00:00+00:00",
        )
        assert obj.approval_status == "approved"

    def test_round_trip_through_to_dict_from_dict(self):
        obj = _spend()
        restored = SearchObjectDefinition.from_dict(obj.to_dict())
        assert restored == obj


class TestGraphNodeRoleForSearchObject:
    def test_demand_roles_map_to_demand_capture(self):
        assert graph_node_role_for_search_object(_demand()) == NODE_ROLE_DEMAND_CAPTURE

    def test_organic_capture_maps_to_demand_capture(self):
        obj = SearchObjectDefinition(
            search_object_id="uk_organic_search",
            search_role=SEARCH_ROLE_ORGANIC_CAPTURE,
            source_column="organic_search_sessions",
            unit=UNIT_RESPONSE_COUNT,
            market="UK",
        )
        assert graph_node_role_for_search_object(obj) == NODE_ROLE_DEMAND_CAPTURE

    def test_direct_navigation_capture_maps_to_demand_capture(self):
        obj = SearchObjectDefinition(
            search_object_id="uk_direct_nav",
            search_role=SEARCH_ROLE_DIRECT_NAV_CAPTURE,
            source_column="direct_sessions",
            unit=UNIT_RESPONSE_COUNT,
            market="UK",
        )
        assert graph_node_role_for_search_object(obj) == NODE_ROLE_DEMAND_CAPTURE

    def test_paid_spend_maps_to_intervention(self):
        assert graph_node_role_for_search_object(_spend()) == NODE_ROLE_INTERVENTION

    def test_paid_cap_maps_to_capacity_or_cap(self):
        obj = SearchObjectDefinition(
            search_object_id="uk_paid_search_cap",
            search_role=SEARCH_ROLE_PAID_CAP,
            source_column="daily_budget_cap_gbp",
            unit=UNIT_MONETARY,
            currency="GBP",
            market="UK",
        )
        assert graph_node_role_for_search_object(obj) == NODE_ROLE_CAPACITY_OR_CAP

    def test_paid_delivery_has_no_graph_node_role(self):
        obj = SearchObjectDefinition(
            search_object_id="uk_paid_search_delivery",
            search_role=SEARCH_ROLE_PAID_DELIVERY,
            source_column="paid_search_clicks",
            unit=UNIT_EXPOSURE_COUNT,
            market="UK",
        )
        assert graph_node_role_for_search_object(obj) is None


class TestValidateSearchObjectCatalogue:
    def test_empty_catalogue_has_no_issues(self):
        assert validate_search_object_catalogue([]) == []

    def test_distinct_objects_have_no_issues(self):
        issues = validate_search_object_catalogue([_spend(), _demand()])
        assert issues == []

    def test_duplicate_identity_is_flagged(self):
        a = _spend()
        b = _spend(source_column="a_different_column")
        issues = validate_search_object_catalogue([a, b])
        assert len(issues) == 1
        assert issues[0].issue_type == "duplicate_identity"

    def test_same_column_under_two_different_roles_is_rejected(self):
        """REQ-SEARCH-001 S14 example: a click column already governed as
        paid_search_delivery cannot also be registered as paid_search_cap."""
        delivery = SearchObjectDefinition(
            search_object_id="uk_paid_search_delivery",
            search_role=SEARCH_ROLE_PAID_DELIVERY,
            source_column="paid_search_clicks",
            unit=UNIT_EXPOSURE_COUNT,
            market="UK",
            channel="paid_search",
        )
        cap_reusing_same_column = SearchObjectDefinition(
            search_object_id="uk_paid_search_cap",
            search_role=SEARCH_ROLE_PAID_CAP,
            source_column="paid_search_clicks",
            unit=UNIT_EXPOSURE_COUNT,
            market="UK",
            channel="paid_search",
        )
        issues = validate_search_object_catalogue([delivery, cap_reusing_same_column])
        # Both conflicting records are flagged - neither is arbitrarily kept.
        assert len(issues) == 2
        assert {issue.search_object_id for issue in issues} == {
            "uk_paid_search_delivery",
            "uk_paid_search_cap",
        }
        assert issues[0].issue_type == "incompatible_column_alias"

    def test_same_column_same_role_twice_is_not_a_column_alias_issue(self):
        # Two records for the same role/column would already collide on
        # duplicate_identity if they share a search_object_id; distinct ids
        # sharing (market, column, role) is not the alias issue this checks.
        a = SearchObjectDefinition(
            search_object_id="uk_demand_a",
            search_role=SEARCH_ROLE_DEMAND,
            source_column="branded_query_index",
            unit=UNIT_INDEX,
            market="UK",
        )
        b = SearchObjectDefinition(
            search_object_id="uk_demand_b",
            search_role=SEARCH_ROLE_DEMAND,
            source_column="branded_query_index",
            unit=UNIT_INDEX,
            market="UK",
        )
        issues = validate_search_object_catalogue([a, b])
        assert not any(i.issue_type == "incompatible_column_alias" for i in issues)

    def test_same_column_different_market_is_not_flagged(self):
        uk = _demand(market="UK")
        au = _demand(search_object_id="au_search_demand", market="AU")
        issues = validate_search_object_catalogue([uk, au])
        assert issues == []


def _cap(**overrides):
    values = dict(
        search_object_id="uk_paid_search_cap",
        search_role=SEARCH_ROLE_PAID_CAP,
        source_column="daily_budget_cap_gbp",
        unit=UNIT_MONETARY,
        currency="GBP",
        market="UK",
    )
    values.update(overrides)
    return SearchObjectDefinition(**values)


def _delivery(**overrides):
    values = dict(
        search_object_id="uk_paid_search_delivery",
        search_role=SEARCH_ROLE_PAID_DELIVERY,
        source_column="paid_search_clicks",
        unit=UNIT_EXPOSURE_COUNT,
        market="UK",
    )
    values.update(overrides)
    return SearchObjectDefinition(**values)


class TestPaidSearchCapCounterpart:
    """REQ-SEARCH-001 S14 last bullet: a paid_search_cap record must have a
    corresponding paid_search_spend or paid_search_delivery record in the
    same market x channel to constrain."""

    def test_monetary_cap_with_matching_spend_passes(self):
        cap = _cap(unit=UNIT_MONETARY, currency="GBP", channel="paid_search")
        spend = _spend(channel="paid_search")
        assert validate_search_object_catalogue([cap, spend]) == []

    def test_exposure_cap_with_matching_delivery_passes(self):
        cap = _cap(unit=UNIT_EXPOSURE_COUNT, currency="", channel="paid_search")
        delivery = _delivery(channel="paid_search")
        assert validate_search_object_catalogue([cap, delivery]) == []

    def test_cap_with_no_counterpart_fails(self):
        cap = _cap(channel="paid_search")
        issues = validate_search_object_catalogue([cap])
        assert len(issues) == 1
        assert issues[0].issue_type == "missing_cap_counterpart"
        assert issues[0].search_object_id == "uk_paid_search_cap"

    def test_cap_with_no_channel_declared_fails(self):
        cap = _cap()
        spend = _spend(channel="paid_search")
        issues = validate_search_object_catalogue([cap, spend])
        assert any(i.issue_type == "missing_cap_counterpart" for i in issues)

    def test_wrong_channel_counterpart_fails(self):
        cap = _cap(channel="paid_search_brand")
        spend = _spend(channel="paid_search_generic")
        issues = validate_search_object_catalogue([cap, spend])
        assert len(issues) == 1
        assert issues[0].issue_type == "missing_cap_counterpart"

    def test_incompatible_cap_unit_fails_when_only_wrong_role_present(self):
        """A monetary cap is not satisfied merely because a delivery record
        shares its channel - it needs a paid_search_spend counterpart."""
        cap = _cap(unit=UNIT_MONETARY, currency="GBP", channel="paid_search")
        delivery = _delivery(channel="paid_search")
        issues = validate_search_object_catalogue([cap, delivery])
        assert len(issues) == 1
        assert issues[0].issue_type == "missing_cap_counterpart"

    def test_duplicate_cap_relationship_fails(self):
        cap_a = _cap(channel="paid_search")
        cap_b = _cap(
            search_object_id="uk_paid_search_cap_2",
            source_column="daily_budget_cap_gbp_2",
            channel="paid_search",
        )
        spend = _spend(channel="paid_search")
        issues = validate_search_object_catalogue([cap_a, cap_b, spend])
        assert {i.issue_type for i in issues} == {"duplicate_cap_relationship"}
        assert {i.search_object_id for i in issues} == {
            "uk_paid_search_cap",
            "uk_paid_search_cap_2",
        }

    def test_same_channel_id_in_different_markets_does_not_leak(self):
        uk_cap = _cap(channel="paid_search")
        au_spend = _spend(
            search_object_id="au_paid_search_spend", market="AU", channel="paid_search"
        )
        issues = validate_search_object_catalogue([uk_cap, au_spend])
        assert len(issues) == 1
        assert issues[0].issue_type == "missing_cap_counterpart"
        assert issues[0].market == "UK"

    def test_round_trip_preserves_channel(self):
        cap = _cap(channel="paid_search")
        restored = SearchObjectDefinition.from_dict(cap.to_dict())
        assert restored == cap
        assert restored.channel == "paid_search"


class TestSearchObjectsFingerprint:
    def test_deterministic(self):
        objs = [_spend(), _demand()]
        assert search_objects_fingerprint(objs) == search_objects_fingerprint(objs)

    def test_independent_of_order(self):
        a = search_objects_fingerprint([_spend(), _demand()])
        b = search_objects_fingerprint([_demand(), _spend()])
        assert a == b

    def test_changes_when_a_field_changes(self):
        before = search_objects_fingerprint([_spend()])
        after = search_objects_fingerprint(
            [_spend(planning_eligibility="scenario_only")]
        )
        assert before != after

    def test_accepts_plain_dicts(self):
        obj = _spend()
        assert search_objects_fingerprint([obj]) == search_objects_fingerprint(
            [obj.to_dict()]
        )
