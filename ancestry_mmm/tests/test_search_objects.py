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
    SEARCH_OBJECT_SCHEMA_VERSION,
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
    current_search_object_versions,
    graph_node_role_for_search_object,
    new_search_object_version,
    search_object_fit_fingerprint,
    search_object_versions_for_export,
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


class TestEffectivePeriod:
    """REQ-SEARCH-001 S10: every Search object carries an effective-period
    window, mirroring core.media_costs.MediaInputSpec/GovernedCostMapping."""

    def test_round_trips_exact_values(self):
        obj = _spend(
            effective_period_start="2026-01-01", effective_period_end="2026-12-31"
        )
        restored = SearchObjectDefinition.from_dict(obj.to_dict())
        assert restored.effective_period_start == "2026-01-01"
        assert restored.effective_period_end == "2026-12-31"

    def test_blank_period_is_the_default(self):
        obj = _spend()
        assert obj.effective_period_start is None
        assert obj.effective_period_end is None

    def test_start_after_end_is_rejected(self):
        with pytest.raises(ValueError, match="must not be after"):
            _spend(
                effective_period_start="2026-06-01", effective_period_end="2026-01-01"
            )

    def test_start_equal_to_end_is_accepted(self):
        obj = _spend(
            effective_period_start="2026-01-01", effective_period_end="2026-01-01"
        )
        assert obj.effective_period_start == obj.effective_period_end

    def test_malformed_start_date_is_rejected(self):
        with pytest.raises(ValueError):
            _spend(effective_period_start="not-a-date")

    def test_malformed_end_date_is_rejected(self):
        with pytest.raises(ValueError):
            _spend(effective_period_end="2026-13-40")

    def test_only_start_declared_is_valid(self):
        obj = _spend(effective_period_start="2026-01-01")
        assert obj.effective_period_start == "2026-01-01"
        assert obj.effective_period_end is None


class TestVersionLifecycle:
    """REQ-SEARCH-001 S10: an edit to a governed Search object creates a new
    version - never an in-place mutation of an approved record."""

    def test_new_definition_starts_at_version_one(self):
        assert _spend().search_object_version == 1

    def test_new_search_object_version_increments_version(self):
        original = _spend()
        edited = new_search_object_version(original, source_column="new_column")
        assert edited.search_object_version == 2
        assert original.search_object_version == 1

    def test_new_search_object_version_does_not_mutate_the_original(self):
        original = _spend(source_column="original_column")
        new_search_object_version(original, source_column="new_column")
        assert original.source_column == "original_column"

    def test_editing_an_approved_record_resets_it_to_draft(self):
        approved = _spend(
            approval_status="approved", approved_by="analyst", approved_at="2026-01-01"
        )
        edited = new_search_object_version(approved, source_column="new_column")
        assert edited.approval_status == "draft"
        assert edited.approved_by is None
        assert edited.approved_at is None
        # The old, approved version remains exactly as it was - auditable.
        assert approved.approval_status == "approved"
        assert approved.search_object_version == 1

    def test_cannot_change_lineage_identity_via_new_version(self):
        original = _spend()
        with pytest.raises(ValueError, match="lineage/version identity"):
            new_search_object_version(original, search_object_id="a_different_id")
        with pytest.raises(ValueError, match="lineage/version identity"):
            new_search_object_version(original, market="AU")
        with pytest.raises(ValueError, match="lineage/version identity"):
            new_search_object_version(original, search_object_version=5)

    def test_search_object_version_below_one_is_rejected(self):
        with pytest.raises(ValueError, match="search_object_version must be >= 1"):
            _spend(search_object_version=0)

    def test_duplicate_version_within_same_lineage_is_flagged(self):
        a = _spend()
        b = _spend(source_column="a_different_column")
        # Both default to search_object_version=1 - a genuine collision.
        issues = validate_search_object_catalogue([a, b])
        assert len(issues) == 1
        assert issues[0].issue_type == "duplicate_identity"

    def test_two_versions_of_the_same_lineage_are_not_a_duplicate_identity_issue(self):
        v1 = _spend()
        v2 = new_search_object_version(v1, source_column="new_column")
        issues = validate_search_object_catalogue([v1, v2])
        assert not any(i.issue_type == "duplicate_identity" for i in issues)


class TestCurrentSearchObjectVersions:
    """REQ-SEARCH-001 S10: latest/current version resolution."""

    def test_empty_catalogue_resolves_to_empty(self):
        assert current_search_object_versions([]) == []

    def test_single_version_lineage_resolves_to_itself(self):
        obj = _spend()
        assert current_search_object_versions([obj]) == [obj]

    def test_resolves_the_highest_version_per_lineage(self):
        v1 = _spend()
        v2 = new_search_object_version(v1, source_column="new_column")
        v3 = new_search_object_version(v2, source_column="newer_column")
        current = current_search_object_versions([v1, v2, v3])
        assert len(current) == 1
        assert current[0].search_object_version == 3
        assert current[0].source_column == "newer_column"

    def test_order_independent(self):
        v1 = _spend()
        v2 = new_search_object_version(v1, source_column="new_column")
        forward = current_search_object_versions([v1, v2])
        backward = current_search_object_versions([v2, v1])
        assert forward == backward

    def test_resolves_independently_per_lineage(self):
        spend = _spend()
        demand = _demand()
        current = current_search_object_versions([spend, demand])
        assert {d.search_object_key for d in current} == {
            spend.search_object_key,
            demand.search_object_key,
        }

    def test_accepts_plain_dicts(self):
        obj = _spend()
        assert current_search_object_versions([obj.to_dict()]) == [obj]

    def test_superseded_version_never_triggers_a_false_column_alias_conflict(self):
        """A record edited to a new search_role must not have its own
        superseded version flagged as conflicting with itself."""
        v1 = _delivery()
        v2 = new_search_object_version(v1, search_role=SEARCH_ROLE_PAID_CAP)
        issues = validate_search_object_catalogue([v1, v2])
        assert not any(i.issue_type == "incompatible_column_alias" for i in issues)

    def test_superseded_cap_never_counts_toward_duplicate_cap_relationship(self):
        spend = _spend(channel="paid_search")
        cap_v1 = _cap(channel="paid_search")
        cap_v2 = new_search_object_version(cap_v1, source_column="revised_cap_column")
        issues = validate_search_object_catalogue([spend, cap_v1, cap_v2])
        assert not any(i.issue_type == "duplicate_cap_relationship" for i in issues)
        assert not any(i.issue_type == "missing_cap_counterpart" for i in issues)


class TestSchemaVersionFailClosed:
    """REQ-SEARCH-001 S11: a malformed or unknown-schema imported record
    fails closed."""

    def test_default_schema_version_is_current(self):
        assert _spend().schema_version == SEARCH_OBJECT_SCHEMA_VERSION

    def test_future_schema_version_is_rejected(self):
        payload = _spend().to_dict()
        payload["schema_version"] = SEARCH_OBJECT_SCHEMA_VERSION + 1
        with pytest.raises(
            ValueError, match="Unsupported search object schema_version"
        ):
            SearchObjectDefinition.from_dict(payload)

    def test_malformed_schema_version_is_rejected(self):
        payload = _spend().to_dict()
        payload["schema_version"] = "not-a-number"
        with pytest.raises(ValueError):
            SearchObjectDefinition.from_dict(payload)

    @pytest.mark.parametrize(
        "raw_schema_version",
        [
            "2",  # numeric string - int(...) coercion would silently accept this
            2.5,  # float - int(...) coercion would silently truncate this
            2.0,  # float equal to a supported version - still not an int
            True,  # bool is an int subclass in Python - must still be rejected
            False,
            0,
            -1,
            None,  # explicitly supplied null, distinct from an absent key
        ],
    )
    def test_non_integer_or_out_of_range_schema_version_is_rejected(
        self, raw_schema_version
    ):
        """REQ-SEARCH-001 S11 / Work Package 1 Correction A: `int(...)`
        coercion is not validation - a numeric string, a float (even one
        that equals a supported version), a bool, zero, a negative value, or
        an explicit `null` must all fail closed, never be silently accepted
        as an actual schema-version integer."""
        payload = _spend().to_dict()
        payload["schema_version"] = raw_schema_version
        with pytest.raises(ValueError):
            SearchObjectDefinition.from_dict(payload)

    def test_absent_schema_version_key_still_uses_documented_legacy_default(self):
        """Only a genuinely *missing* schema_version key takes the legacy
        default - the strict validator above only runs when the key is
        actually present (including as an explicit null, which is
        rejected)."""
        payload = _spend().to_dict()
        del payload["schema_version"]
        restored = SearchObjectDefinition.from_dict(payload)
        assert restored.schema_version == SEARCH_OBJECT_SCHEMA_VERSION

    def test_legacy_record_with_no_lifecycle_fields_migrates_cleanly(self):
        """A record predating schema_version 2 (no effective_period_*/
        search_object_version keys at all) is not "unknown" - it is a
        legacy record that migrates to the documented defaults."""
        legacy_payload = {
            "search_object_id": "uk_paid_search_spend",
            "search_role": SEARCH_ROLE_PAID_SPEND,
            "source_column": "paid_search_gbp_spend",
            "unit": UNIT_MONETARY,
            "currency": "GBP",
            "market": "UK",
            "schema_version": 1,
        }
        restored = SearchObjectDefinition.from_dict(legacy_payload)
        assert restored.effective_period_start is None
        assert restored.effective_period_end is None
        assert restored.search_object_version == 1
        assert restored.schema_version == 1

    def test_no_fabricated_version_evidence_on_legacy_migration(self):
        """A legacy record must migrate to the documented default (version
        1, no declared period) - never a fabricated non-default value."""
        legacy_payload = {
            "search_object_id": "uk_search_demand",
            "search_role": SEARCH_ROLE_DEMAND,
            "source_column": "branded_query_index",
            "unit": UNIT_INDEX,
            "market": "UK",
        }
        restored = SearchObjectDefinition.from_dict(legacy_payload)
        assert restored.to_dict() == _demand().to_dict()


class TestSearchObjectVersionsForExport:
    """Mirrors core.causal_graph.graph_versions_for_export's contract."""

    def test_no_history_no_current_is_empty(self):
        assert (
            search_object_versions_for_export(
                current_definitions=None, version_history=None
            )
            == []
        )

    def test_current_only_is_included_when_never_saved(self):
        current = [_spend().to_dict()]
        result = search_object_versions_for_export(
            current_definitions=current, version_history=None
        )
        assert result == current

    def test_history_is_authoritative_for_a_key_it_already_contains(self):
        saved = _spend().to_dict()
        saved["approval_status"] = "approved"
        saved["approved_by"] = "analyst"
        saved["approved_at"] = "2026-01-01"
        stale_current = _spend().to_dict()  # same key, draft (unsaved edit)
        result = search_object_versions_for_export(
            current_definitions=[stale_current], version_history=[saved]
        )
        assert len(result) == 1
        assert result[0]["approval_status"] == "approved"

    def test_history_and_current_versions_are_both_kept(self):
        v1 = _spend().to_dict()
        v2 = new_search_object_version(
            SearchObjectDefinition.from_dict(v1), source_column="new_column"
        ).to_dict()
        result = search_object_versions_for_export(
            current_definitions=[v2], version_history=[v1]
        )
        keys = {
            (item["market"], item["search_object_id"], item["search_object_version"])
            for item in result
        }
        assert keys == {
            ("UK", "uk_paid_search_spend", 1),
            ("UK", "uk_paid_search_spend", 2),
        }


class TestSearchObjectFitFingerprint:
    """REQ-SEARCH-001 fit-identity closure: only Search objects a fit
    actually consumes (a current-version, non-blank model_input_column
    matching one of the fit's own channels) participate, and only their
    fit-relevant fields."""

    def test_empty_catalogue_is_deterministic(self):
        assert search_object_fit_fingerprint([]) == search_object_fit_fingerprint([])

    def test_unconsumed_definition_is_excluded(self):
        obj = _spend(model_input_column="paid_search_gbp_spend")
        # consumed_model_input_columns does not include this object's column.
        fp = search_object_fit_fingerprint(
            [obj], consumed_model_input_columns=["tv_spend"]
        )
        assert fp == search_object_fit_fingerprint([])

    def test_definition_with_blank_model_input_column_is_never_consumed(self):
        obj = _spend(model_input_column="")
        fp = search_object_fit_fingerprint(
            [obj], consumed_model_input_columns=["paid_search_gbp_spend"]
        )
        assert fp == search_object_fit_fingerprint([])

    def test_consumed_definition_is_included(self):
        obj = _spend(model_input_column="paid_search_gbp_spend")
        fp = search_object_fit_fingerprint(
            [obj], consumed_model_input_columns=["paid_search_gbp_spend"]
        )
        assert fp != search_object_fit_fingerprint([])

    def test_deterministic_and_order_invariant(self):
        spend = _spend(model_input_column="paid_search_gbp_spend")
        cap = _cap(model_input_column="daily_budget_cap_gbp")
        columns = ["paid_search_gbp_spend", "daily_budget_cap_gbp"]
        a = search_object_fit_fingerprint(
            [spend, cap], consumed_model_input_columns=columns
        )
        b = search_object_fit_fingerprint(
            [cap, spend], consumed_model_input_columns=columns
        )
        assert a == b
        assert a == search_object_fit_fingerprint(
            [spend, cap], consumed_model_input_columns=columns
        )

    def test_fit_relevant_field_change_changes_the_fingerprint(self):
        columns = ["paid_search_gbp_spend"]
        before = _spend(model_input_column="paid_search_gbp_spend")
        after = _spend(
            model_input_column="paid_search_gbp_spend",
            source_column="a_different_source_column",
        )
        fp_before = search_object_fit_fingerprint(
            [before], consumed_model_input_columns=columns
        )
        fp_after = search_object_fit_fingerprint(
            [after], consumed_model_input_columns=columns
        )
        assert fp_before != fp_after

    def test_version_bump_alone_does_not_change_the_fingerprint(self):
        """Work Package 1 Correction B: `search_object_version` is
        governance/audit identity, not fit-relevant mathematical identity.
        Two versions of the same lineage with identical fit-relevant field
        values (e.g. a version bump with no field changes, or a fit-relevant
        edit reverted in a later version) correctly fingerprint identically
        here - the fit-relevant inputs a model would actually be built from
        are, at that point, literally the same. (Superseded from this test's
        prior form, which asserted the opposite and was the exact
        false-staleness contradiction this corrective PR closes: every
        sanctioned edit via `new_search_object_version` - including a purely
        administrative one - bumps `search_object_version`, so hashing it
        here would stale a fit on an administrative-only edit.)"""
        columns = ["paid_search_gbp_spend"]
        v1 = _spend(model_input_column="paid_search_gbp_spend")
        v2 = new_search_object_version(v1)  # no field changes, only version
        assert v2.search_object_version == 2
        fp_v1 = search_object_fit_fingerprint(
            [v1], consumed_model_input_columns=columns
        )
        fp_v2 = search_object_fit_fingerprint(
            [v2], consumed_model_input_columns=columns
        )
        assert fp_v1 == fp_v2

    def test_superseded_version_is_excluded_even_if_still_present_in_input(self):
        """Only the current version of a consumed lineage participates -
        passing both an old and new version (e.g. full export history) must
        fingerprint identically to passing only the current one."""
        columns = ["paid_search_gbp_spend"]
        v1 = _spend(model_input_column="paid_search_gbp_spend")
        v2 = new_search_object_version(v1, source_column="revised_column")
        fp_history = search_object_fit_fingerprint(
            [v1, v2], consumed_model_input_columns=columns
        )
        fp_current_only = search_object_fit_fingerprint(
            [v2], consumed_model_input_columns=columns
        )
        assert fp_history == fp_current_only

    def test_channel_change_does_not_change_the_fingerprint(self):
        """channel is a cap-counterpart governance relationship only - no
        fitting mechanism reads it, mirroring activity_fit_fingerprint's
        exclusion of ActivityDefinition.channel."""
        columns = ["paid_search_gbp_spend"]
        no_channel = _spend(model_input_column="paid_search_gbp_spend", channel="")
        with_channel = _spend(
            model_input_column="paid_search_gbp_spend", channel="paid_search"
        )
        fp_a = search_object_fit_fingerprint(
            [no_channel], consumed_model_input_columns=columns
        )
        fp_b = search_object_fit_fingerprint(
            [with_channel], consumed_model_input_columns=columns
        )
        assert fp_a == fp_b

    def test_effective_period_change_does_not_change_the_fingerprint(self):
        """Not yet fit-relevant: no model builder gates consumed data by a
        Search object's declared effective period (REQ-SEARCH-001 S7)."""
        columns = ["paid_search_gbp_spend"]
        no_period = _spend(model_input_column="paid_search_gbp_spend")
        with_period = _spend(
            model_input_column="paid_search_gbp_spend",
            effective_period_start="2026-01-01",
            effective_period_end="2026-12-31",
        )
        fp_a = search_object_fit_fingerprint(
            [no_period], consumed_model_input_columns=columns
        )
        fp_b = search_object_fit_fingerprint(
            [with_period], consumed_model_input_columns=columns
        )
        assert fp_a == fp_b

    def test_administrative_field_change_does_not_change_the_fingerprint(self):
        columns = ["paid_search_gbp_spend"]
        draft = _spend(model_input_column="paid_search_gbp_spend")
        approved = _spend(
            model_input_column="paid_search_gbp_spend",
            planning_eligibility="scenario_only",
            approval_status="approved",
            approved_by="reviewer",
            approved_at="2026-01-01",
        )
        fp_draft = search_object_fit_fingerprint(
            [draft], consumed_model_input_columns=columns
        )
        fp_approved = search_object_fit_fingerprint(
            [approved], consumed_model_input_columns=columns
        )
        assert fp_draft == fp_approved

    def test_accepts_plain_dicts(self):
        obj = _spend(model_input_column="paid_search_gbp_spend")
        columns = ["paid_search_gbp_spend"]
        assert search_object_fit_fingerprint(
            [obj], consumed_model_input_columns=columns
        ) == search_object_fit_fingerprint(
            [obj.to_dict()], consumed_model_input_columns=columns
        )
