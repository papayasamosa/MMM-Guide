import pytest

from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_node_id,
    governed_activities_in_model_scope,
    activity_definitions_fingerprint,
    activity_fit_fingerprint,
    activity_invalidation,
    activity_reporting_fingerprint,
    resolve_graph_activity_predictor,
)
from ancestry_mmm.core.media_costs import monetary_governance_fingerprint


def _activity(**overrides):
    values = {
        "activity_id": "organic-social",
        "channel": "Organic Social",
        "activity_ownership": "owned",
        "model_role": "intervention",
        "economic_treatment": "response_only",
        "planning_eligibility": "scenario_only",
        "source": "social analytics",
    }
    values.update(overrides)
    return ActivityDefinition(**values)


def test_organic_social_is_response_only_without_fake_cpa():
    activity = _activity()
    assert activity.economics_status(has_approved_cost_basis=False) == "response_only"


def test_promotional_crm_can_use_fully_loaded_cost():
    crm = _activity(
        activity_id="promo-email",
        channel="Promotional Email",
        model_role="intervention",
        economic_treatment="fully_loaded_cost",
        planning_eligibility="scenario_only",
    )
    assert crm.economics_status(has_approved_cost_basis=False) == "mapping_missing"
    assert (
        crm.economics_status(has_approved_cost_basis=True)
        == "fully_loaded_economics_available"
    )


@pytest.mark.parametrize(
    ("activity_id", "model_role", "planning_eligibility"),
    [
        ("lifecycle-email", "mediator", "fixed"),
        ("transactional-email", "control", "excluded"),
        ("named-pr-event", "event", "scenario_only"),
    ],
)
def test_non_acquisition_activities_are_not_freely_optimisable(
    activity_id, model_role, planning_eligibility
):
    definition = _activity(
        activity_id=activity_id,
        channel=activity_id,
        activity_ownership=("earned" if activity_id == "named-pr-event" else "owned"),
        model_role=model_role,
        economic_treatment="response_only",
        planning_eligibility=planning_eligibility,
    )
    assert definition.planning_eligibility != "optimisable"


def test_mediator_and_event_cannot_be_marked_optimisable():
    with pytest.raises(ValueError, match="cannot be freely optimised"):
        _activity(model_role="mediator", planning_eligibility="optimisable")


def test_activity_fingerprint_changes_with_economic_treatment():
    response_only = _activity()
    costed = _activity(economic_treatment="fully_loaded_cost")
    assert activity_definitions_fingerprint(
        [response_only]
    ) != activity_definitions_fingerprint([costed])


def test_activity_round_trip_preserves_governance():
    activity = _activity(
        evidence_status="directional",
        governance_notes="Response per 1,000 organic impressions",
    )
    assert ActivityDefinition.from_dict(activity.to_dict()) == activity


def test_monetary_governance_fingerprint_covers_every_economic_input():
    base = {
        "cost_mappings": {"id": "cost-v1"},
        "activity_definitions": {"economic_treatment": "paid_media_cost"},
        "fx_metadata": {"GBP": 1.0},
        "planning_support": {"max": 100.0},
    }
    original = monetary_governance_fingerprint(**base)

    for field, replacement in {
        "cost_mappings": {"id": "cost-v2"},
        "activity_definitions": {"economic_treatment": "fully_loaded_cost"},
        "fx_metadata": {"GBP": 1.25},
        "planning_support": {"max": 120.0},
    }.items():
        changed = dict(base)
        changed[field] = replacement
        assert monetary_governance_fingerprint(**changed) != original


# ---------------------------------------------------------------------------
# REQ-DATAIN-001: pooling_group_id (schema v3)
# ---------------------------------------------------------------------------


class TestPoolingGroupId:
    def test_defaults_to_none(self):
        assert _activity().pooling_group_id is None

    def test_current_schema_version_is_4(self):
        assert _activity().schema_version == 4

    def test_accepts_an_explicit_value(self):
        activity = _activity(pooling_group_id="tv-brand-uk-au")
        assert activity.pooling_group_id == "tv-brand-uk-au"

    def test_to_dict_from_dict_round_trip(self):
        activity = _activity(pooling_group_id="tv-brand-uk-au")
        restored = ActivityDefinition.from_dict(activity.to_dict())
        assert restored == activity
        assert restored.pooling_group_id == "tv-brand-uk-au"

    def test_legacy_payload_with_no_key_at_all_resolves_to_none(self):
        """A payload predating this field entirely (dict with no
        pooling_group_id key) resolves to None, not fabricated, and its
        schema_version is migrated to the current taxonomy shape."""
        payload = {
            "activity_id": "organic-social",
            "channel": "Organic Social",
            "activity_ownership": "owned",
            "model_role": "intervention",
            "economic_treatment": "response_only",
            "planning_eligibility": "scenario_only",
            "source": "social analytics",
        }
        restored = ActivityDefinition.from_dict(payload)
        assert restored.pooling_group_id is None
        assert restored.schema_version == 4

    def test_does_not_trigger_any_invalidation_flag(self):
        """REQ-DATAIN-001: pooling_group_id's presence must never, by
        itself, force, imply, or default to parameter pooling - editing it
        alone must never trigger a refit/rebuild prompt, which would
        itself imply the field has a fit-relevant effect."""
        before = _activity(pooling_group_id=None)
        after = _activity(pooling_group_id="tv-brand-uk-au")
        result = activity_invalidation(before, after)
        assert result.refit_model is False
        assert result.rebuild_curves is False
        assert result.rebuild_economics is False
        assert result.rebuild_scenarios is False
        assert result.changed_fields == ()

    def test_excluded_from_fit_fingerprint(self):
        """pooling_group_id must never influence what actually gets fit -
        activity_fit_fingerprint (which gates model refit) must not change
        when only pooling_group_id changes."""
        before = [_activity(pooling_group_id=None)]
        after = [_activity(pooling_group_id="tv-brand-uk-au")]
        assert activity_fit_fingerprint(before) == activity_fit_fingerprint(after)

    def test_excluded_from_general_governance_fingerprint(self):
        """activity_definitions_fingerprint is a hard blocking gate for
        curve-artifact use (CurveArtifactService.validate_for_use) and
        scenario staleness (core.optimization), not a soft audit signal -
        it must not change when only pooling_group_id changes, or a
        pooling-identity edit would silently invalidate curves/scenarios
        that changed nothing fit-relevant."""
        before = [_activity(pooling_group_id=None)]
        after = [_activity(pooling_group_id="tv-brand-uk-au")]
        assert activity_definitions_fingerprint(
            before
        ) == activity_definitions_fingerprint(after)


# ---------------------------------------------------------------------------
# REQ-ACTIVITY-001: explicit reporting taxonomy (schema v4)
# ---------------------------------------------------------------------------


class TestActivityTaxonomy:
    def test_legacy_payload_defaults_without_name_inference(self):
        payload = _activity(
            activity_id="meta-performance-prospecting",
            channel="Paid Social",
            platform="Meta",
        ).to_dict()
        payload.pop("funnel_stage")
        payload.pop("marketing_objective")
        payload["schema_version"] = 3

        restored = ActivityDefinition.from_dict(payload)

        assert restored.funnel_stage == "unclassified"
        assert restored.marketing_objective == ""
        assert restored.schema_version == 4

    def test_unversioned_legacy_payload_migrates_to_explicit_defaults(self):
        payload = {
            "activity_id": "email-winback",
            "channel": "CRM",
            "platform": "Email",
            "campaign_type": "winback",
            "message_type": "offer/discount",
            "activity_ownership": "owned",
            "model_role": "intervention",
            "economic_treatment": "response_only",
            "planning_eligibility": "scenario_only",
            "source": "crm export",
        }

        restored = ActivityDefinition.from_dict(payload)

        assert restored.funnel_stage == "unclassified"
        assert restored.marketing_objective == ""
        assert restored.schema_version == 4

    @pytest.mark.parametrize("value", ["brand", "upper", "performance", None])
    def test_funnel_stage_vocabulary_is_closed(self, value):
        with pytest.raises(ValueError, match="invalid funnel_stage"):
            _activity(funnel_stage=value)

    def test_taxonomy_fields_round_trip(self):
        activity = _activity(
            marketing_objective="retention/lifecycle",
            funnel_stage="mid_funnel",
            pooling_group_id="crm-uk-au",
            platform="Meta",
            campaign_type="lifecycle",
            message_type="educational",
        )

        restored = ActivityDefinition.from_dict(activity.to_dict())

        assert restored == activity
        assert restored.to_dict()["funnel_stage"] == "mid_funnel"
        assert restored.to_dict()["marketing_objective"] == "retention/lifecycle"

    def test_taxonomy_changes_reporting_but_not_fit_or_hard_curve_fingerprints(self):
        before = _activity(
            funnel_stage="brand_upper", marketing_objective="brand awareness"
        )
        after = _activity(
            funnel_stage="performance_lower",
            marketing_objective="acquisition/performance",
        )

        assert activity_reporting_fingerprint(
            [before]
        ) != activity_reporting_fingerprint([after])
        assert activity_fit_fingerprint([before]) == activity_fit_fingerprint([after])

    def test_meta_activities_share_reporting_channel_but_keep_distinct_identity(self):
        activities = [
            _activity(
                activity_id="meta-brand-video",
                channel="Paid Social",
                platform="Meta",
                model_input_column="meta_brand_video",
                marketing_objective="brand awareness",
                funnel_stage="brand_upper",
            ),
            _activity(
                activity_id="meta-consideration",
                channel="Paid Social",
                platform="Meta",
                model_input_column="meta_consideration",
                marketing_objective="consideration",
                funnel_stage="mid_funnel",
            ),
            _activity(
                activity_id="meta-performance-prospecting",
                channel="Paid Social",
                platform="Meta",
                model_input_column="meta_performance",
                marketing_objective="acquisition/performance",
                funnel_stage="performance_lower",
            ),
        ]

        assert {item.channel for item in activities} == {"Paid Social"}
        assert {item.platform for item in activities} == {"Meta"}
        assert len({item.activity_id for item in activities}) == 3
        assert {item.funnel_stage for item in activities} == {
            "brand_upper",
            "mid_funnel",
            "performance_lower",
        }

    def test_crm_activities_keep_campaign_message_objective_and_funnel_separate(self):
        activities = [
            _activity(
                activity_id="crm-brand-editorial",
                channel="CRM",
                platform="Email",
                campaign_type="newsletter",
                message_type="brand/editorial",
                marketing_objective="brand awareness",
                funnel_stage="brand_upper",
            ),
            _activity(
                activity_id="crm-lifecycle",
                channel="CRM",
                platform="Email",
                campaign_type="lifecycle",
                message_type="reminder",
                marketing_objective="retention/lifecycle",
                funnel_stage="mid_funnel",
            ),
            _activity(
                activity_id="crm-promotional",
                channel="CRM",
                platform="Email",
                campaign_type="promotional",
                message_type="offer/discount",
                marketing_objective="promotion",
                funnel_stage="performance_lower",
            ),
            _activity(
                activity_id="crm-winback",
                channel="CRM",
                platform="Email",
                campaign_type="winback",
                message_type="offer/discount",
                marketing_objective="winback",
                funnel_stage="performance_lower",
            ),
            _activity(
                activity_id="crm-transactional",
                channel="CRM",
                platform="Email",
                campaign_type="transactional",
                message_type="service/transactional",
                marketing_objective="service/transactional",
                funnel_stage="not_applicable",
            ),
        ]

        assert {item.channel for item in activities} == {"CRM"}
        assert len({item.campaign_type for item in activities}) == 5
        assert len({item.activity_id for item in activities}) == 5


def test_activity_node_identity_is_scoped_to_market():
    assert activity_node_id(market="UK", activity_id="paid-social") != activity_node_id(
        market="AU", activity_id="paid-social"
    )


def test_model_scope_resolves_two_same_reporting_channel_activities():
    paid = _activity(
        activity_id="meta-paid",
        channel="Paid Social",
        model_input_column="meta_paid",
        activity_ownership="paid",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        platform="Meta",
        funnel_stage="performance_lower",
    )
    owned = _activity(
        activity_id="meta-owned",
        channel="Paid Social",
        model_input_column="meta_owned",
        funnel_stage="mid_funnel",
    )
    scoped = governed_activities_in_model_scope(
        [paid, owned], markets=["UK"], model_input_columns=["meta_paid", "meta_owned"]
    )
    assert [(market, item.activity_id) for market, item in scoped] == [
        ("UK", "meta-paid"),
        ("UK", "meta-owned"),
    ]


def test_graph_activity_resolver_uses_registry_not_free_form_metadata():
    definition = _activity(
        activity_id="meta-paid",
        channel="Paid Social",
        model_input_column="meta_paid",
        activity_ownership="paid",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        market="UK",
    )

    class Node:
        node_id = "activity:UK:meta-paid"
        market = "UK"
        metadata = {
            "activity_id": "meta-paid",
            "activity_market": "UK",
            "funnel_stage": "brand_upper",
            "model_input_column": "not_authoritative",
        }

    predictor, resolved = resolve_graph_activity_predictor(Node(), [definition])
    assert predictor == "meta_paid"
    assert resolved == definition
