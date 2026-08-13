"""Regression tests for governed activity identity at the model boundary."""

import pytest

from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_by_model_input,
    legacy_activity_definitions_from_model_spec,
    resolve_activity_definition,
    resolve_activity_model_input,
)
from ancestry_mmm.core.schema import ModelSpec


def _activity(
    activity_id: str,
    *,
    market: str = "UK",
    channel: str = "Paid Social",
    model_input_column: str,
) -> ActivityDefinition:
    return ActivityDefinition(
        activity_id=activity_id,
        market=market,
        channel=channel,
        model_input_column=model_input_column,
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        source="test",
    )


def test_activity_id_resolves_to_model_input_not_reporting_channel():
    definitions = [
        _activity("meta_brand", model_input_column="meta_brand_input"),
        _activity("meta_performance", model_input_column="meta_performance_input"),
    ]

    assert (
        resolve_activity_model_input(definitions, market="UK", activity_id="meta_brand")
        == "meta_brand_input"
    )
    assert (
        resolve_activity_definition(
            definitions, market="UK", activity_id="meta_performance"
        ).channel
        == "Paid Social"
    )
    assert set(activity_by_model_input(definitions, "UK")) == {
        "meta_brand_input",
        "meta_performance_input",
    }


def test_market_specific_activity_overrides_wildcard_without_guessing():
    definitions = [
        _activity("crm", market="*", channel="CRM", model_input_column="crm_all"),
        _activity("crm", market="UK", channel="CRM", model_input_column="crm_uk"),
    ]

    assert (
        resolve_activity_model_input(definitions, market="UK", activity_id="crm")
        == "crm_uk"
    )
    assert (
        resolve_activity_model_input(definitions, market="Australia", activity_id="crm")
        == "crm_all"
    )


def test_ambiguous_activity_identity_fails_closed():
    definitions = [
        _activity("crm", model_input_column="crm_a"),
        _activity("crm", model_input_column="crm_b"),
    ]

    with pytest.raises(ValueError, match="duplicate activity definitions"):
        resolve_activity_definition(definitions, market="UK", activity_id="crm")


def test_legacy_model_spec_adapter_is_explicit_and_round_trips_inputs():
    spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        channels=["tv_spend", "paid_search"],
    )

    definitions = legacy_activity_definitions_from_model_spec(spec)

    assert [item.source for item in definitions] == [
        "legacy ModelSpec.channels compatibility adapter; review required",
        "legacy ModelSpec.channels compatibility adapter; review required",
    ]
    assert [item.resolved_model_input_column for item in definitions] == [
        "tv_spend",
        "paid_search",
    ]
    assert all(item.funnel_stage == "unclassified" for item in definitions)
