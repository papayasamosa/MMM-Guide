"""WP4 governed reporting roll-up tests (Next Steps brief, Work Package 4)."""

import pandas as pd
import pytest

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.reporting_rollups import (
    ReportingEnrichmentError,
    build_reporting_views,
    enrich_reporting_rows,
    roll_up_reporting_draws,
    roll_up_paid_search_reporting_draws,
    summarize_reporting_draws,
)
from ancestry_mmm.core.search_intent_taxonomy import (
    SEARCH_INTENT_GROUP_ID_BRAND,
    SEARCH_INTENT_GROUP_ID_NON_BRAND,
)


def _activity(activity_id, *, stage, platform="Meta", campaign_type="prospecting"):
    return ActivityDefinition(
        activity_id=activity_id,
        channel="Paid Social",
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        source="approved activity mapping",
        market="UK",
        platform=platform,
        campaign_type=campaign_type,
        product_advertised="Family History",
        marketing_objective={
            "meta-brand": "brand awareness",
            "meta-mid": "consideration",
            "meta-performance": "acquisition/performance",
            "crm-promotional": "promotion",
            "crm-lifecycle": "retention/lifecycle",
        }.get(activity_id, "acquisition/performance"),
        message_type="always-on",
        model_input_column=f"media_{activity_id}",
        funnel_stage=stage,
    )


@pytest.fixture
def activities():
    return [
        _activity("meta-brand", stage="brand_upper"),
        _activity("meta-mid", stage="mid_funnel"),
        _activity("meta-performance", stage="performance_lower"),
        _activity(
            "crm-promotional",
            stage="mid_funnel",
            platform="CRM",
            campaign_type="promotional",
        ),
        _activity(
            "crm-lifecycle",
            stage="performance_lower",
            platform="CRM",
            campaign_type="lifecycle",
        ),
    ]


def test_meta_activity_rows_enrich_and_roll_up_by_channel_and_funnel(activities):
    rows = pd.DataFrame(
        [
            {
                "market": "UK",
                "activity_id": activity_id,
                "outcome_id": "fh_new",
                "posterior_draw": draw,
                "incremental_response": response,
                "pathway_role": "direct",
            }
            for draw, response in ((0, 10.0), (1, 14.0))
            for activity_id in ("meta-brand", "meta-mid", "meta-performance")
        ]
    )

    enriched = enrich_reporting_rows(rows, activities, strict=True)
    assert set(enriched["funnel_stage"]) == {
        "brand_upper",
        "mid_funnel",
        "performance_lower",
    }
    assert set(enriched["reporting_channel"]) == {"Paid Social"}

    rollup = roll_up_reporting_draws(
        rows,
        by=["reporting_channel", "funnel_stage", "market", "outcome_id"],
        activity_definitions=activities,
        strict=True,
    )
    assert len(rollup) == 6  # three funnel buckets x two posterior draws
    assert set(rollup["effect_type"]) == {"direct"}
    assert rollup["funnel_rollup_status"].eq("complete").all()


def test_summary_sums_activities_within_each_draw_before_intervals(activities):
    rows = pd.DataFrame(
        [
            {
                "market": "UK",
                "activity_id": "meta-brand",
                "outcome_id": "fh_new",
                "posterior_draw": 0,
                "incremental_response": 10.0,
                "pathway_role": "direct",
            },
            {
                "market": "UK",
                "activity_id": "meta-mid",
                "outcome_id": "fh_new",
                "posterior_draw": 0,
                "incremental_response": 20.0,
                "pathway_role": "direct",
            },
            {
                "market": "UK",
                "activity_id": "meta-brand",
                "outcome_id": "fh_new",
                "posterior_draw": 1,
                "incremental_response": 30.0,
                "pathway_role": "direct",
            },
            {
                "market": "UK",
                "activity_id": "meta-mid",
                "outcome_id": "fh_new",
                "posterior_draw": 1,
                "incremental_response": 40.0,
                "pathway_role": "direct",
            },
        ]
    )
    draws = roll_up_reporting_draws(
        rows,
        by=["market", "outcome_id"],
        activity_definitions=activities,
        strict=True,
    )
    summary = summarize_reporting_draws(
        draws, by=["market", "outcome_id", "effect_type"]
    )
    row = summary.iloc[0]
    assert row["incremental_response_posterior_mean"] == 50.0
    assert row["incremental_response_posterior_median"] == 50.0
    assert row["incremental_response_lower_interval"] == 32.0
    assert row["incremental_response_upper_interval"] == 68.0


def test_crm_roll_up_retains_platform_campaign_and_objective(activities):
    rows = pd.DataFrame(
        [
            {
                "market": "UK",
                "activity_id": "crm-promotional",
                "outcome_id": "fh_new",
                "posterior_draw": 0,
                "incremental_response": 5.0,
            },
            {
                "market": "UK",
                "activity_id": "crm-lifecycle",
                "outcome_id": "fh_new",
                "posterior_draw": 0,
                "incremental_response": 7.0,
            },
        ]
    )
    enriched = enrich_reporting_rows(rows, activities, strict=True)
    channel_platform = roll_up_reporting_draws(
        enriched,
        by=["platform", "campaign_type", "marketing_objective"],
        activity_definitions=activities,
        strict=True,
    )
    assert set(channel_platform["platform"]) == {"CRM"}
    assert set(channel_platform["campaign_type"]) == {"promotional", "lifecycle"}
    assert set(channel_platform["marketing_objective"]) == {
        "promotion",
        "retention/lifecycle",
    }
    views = build_reporting_views(rows, activities, strict=True)
    assert set(views) == {"funnel", "channel_platform", "activity"}
    assert set(views["activity"]["activity_id"]) == {
        "crm-promotional",
        "crm-lifecycle",
    }


def test_direct_and_mediated_effects_are_separate_from_funnel_stage(activities):
    rows = pd.DataFrame(
        [
            {
                "market": "UK",
                "activity_id": "meta-brand",
                "outcome_id": "fh_new",
                "posterior_draw": 0,
                "incremental_response": 10.0,
                "pathway_role": "direct",
            },
            {
                "market": "UK",
                "activity_id": "meta-brand",
                "outcome_id": "fh_new",
                "posterior_draw": 0,
                "incremental_response": 4.0,
                "pathway_role": "mediated",
            },
        ]
    )
    rollup = roll_up_reporting_draws(
        rows,
        by=["funnel_stage", "market", "outcome_id"],
        activity_definitions=activities,
        strict=True,
    )
    assert set(rollup["effect_type"]) == {"direct", "mediated"}
    assert rollup["incremental_response"].sum() == 14.0
    assert "total" not in set(rollup["effect_type"])


def test_unclassified_rows_are_retained_and_mark_rollup_incomplete(activities):
    rows = pd.DataFrame(
        [
            {
                "market": "UK",
                "channel": "unmapped_source",
                "outcome_id": "fh_new",
                "posterior_draw": 0,
                "incremental_response": 2.0,
            }
        ]
    )
    rollup = roll_up_reporting_draws(
        rows,
        by=["funnel_stage", "market", "outcome_id"],
        activity_definitions=activities,
    )
    assert len(rollup) == 1
    assert rollup.loc[0, "funnel_stage"] == "unclassified"
    assert rollup.loc[0, "funnel_rollup_status"] == "contains_unclassified"
    assert rollup.loc[0, "incremental_response"] == 2.0


def test_ambiguous_legacy_reporting_channel_fails_closed(activities):
    rows = pd.DataFrame(
        [
            {
                "market": "UK",
                "channel": "Paid Social",
                "posterior_draw": 0,
                "incremental_response": 3.0,
            }
        ]
    )
    with pytest.raises(ReportingEnrichmentError, match="ambiguous"):
        enrich_reporting_rows(rows, activities, strict=True)


def test_paid_search_reporting_hierarchy_rolls_up_each_posterior_draw():
    """REQ-SEARCH-004: taxonomy roll-up is draw-safe and four-leaf complete."""
    activities = [
        ActivityDefinition(
            activity_id="google-brand",
            channel="Paid Search",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="approved activity mapping",
            market="UK",
            platform="Google",
            campaign_type="paid_search",
            model_input_column="paid_search_google_brand",
            funnel_stage="performance_lower",
            search_intent_group_id=SEARCH_INTENT_GROUP_ID_BRAND,
            search_platform="google",
        ),
        ActivityDefinition(
            activity_id="bing-non-brand",
            channel="Paid Search",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="approved activity mapping",
            market="UK",
            platform="Bing",
            campaign_type="paid_search",
            model_input_column="paid_search_bing_non_brand",
            funnel_stage="performance_lower",
            search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
            search_platform="bing",
        ),
    ]
    rows = pd.DataFrame(
        [
            {
                "market": "UK",
                "activity_id": activity_id,
                "outcome_id": "fh_new",
                "posterior_draw": draw,
                "incremental_response": value,
                "pathway_role": "direct",
            }
            for draw, values in ((0, (10.0, 4.0)), (1, (14.0, 6.0)))
            for activity_id, value in zip(("google-brand", "bing-non-brand"), values)
        ]
    )

    rolled = roll_up_paid_search_reporting_draws(rows, activities, strict=True)

    assert len(rolled) == 2
    assert rolled.set_index("posterior_draw").loc[0, "google_brand"] == 10.0
    assert rolled.set_index("posterior_draw").loc[0, "bing_non_brand"] == 4.0
    assert rolled.set_index("posterior_draw").loc[1, "total_paid_search"] == 20.0
