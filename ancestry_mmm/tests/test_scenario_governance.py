import numpy as np
import pytest

from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_by_model_input,
    activity_invalidation,
)
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.media_costs import (
    CostMappingRegistry,
    IdentitySpendMapping,
)
from ancestry_mmm.core.optimization import PlanningObjective, evaluate_scenario
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.scenario_governance import (
    CounterfactualPolicy,
    ScenarioPlan,
    classify_activity_plan,
    resolve_counterfactual,
    resolve_scenario_plan,
)

IDENTITY = {
    "model_run_id": "run-g2a5",
    "data_fingerprint": "data-g2a5",
    "model_spec_fingerprint": "spec-g2a5",
    "posterior_fingerprint": "posterior-g2a5",
}


def _activity(
    activity_id,
    model_input,
    *,
    channel=None,
    market="UK",
    ownership="paid",
    role="intervention",
    economics="paid_media_cost",
    planning="optimisable",
):
    return ActivityDefinition(
        activity_id=activity_id,
        market=market,
        channel=channel or model_input,
        model_input_column=model_input,
        activity_ownership=ownership,
        model_role=role,
        economic_treatment=economics,
        planning_eligibility=planning,
        source="test governance",
    )


def _identity_mapping(channel):
    return IdentitySpendMapping(
        mapping_id=f"uk-{channel}",
        market="UK",
        channel=channel,
        currency="GBP",
        cost_context_id="base-plan",
        source="finance",
        effective_period_start="2026-01-01",
        effective_period_end="2026-12-31",
        assumptions="net cost",
        approval_status="approved",
        approved_by="finance",
        approved_at="2026-01-01T00:00:00Z",
        owner="finance",
        approval_note="approved",
        last_reviewed_at="2026-01-01",
    )


def test_activity_grain_supports_multiple_activities_in_one_channel():
    paid = _activity("meta-paid", "meta_paid", channel="Meta")
    organic = _activity(
        "meta-organic",
        "meta_organic",
        channel="Meta",
        ownership="owned",
        economics="response_only",
        planning="scenario_only",
    )
    resolved = activity_by_model_input([paid, organic], "UK")

    assert set(resolved) == {"meta_paid", "meta_organic"}
    assert {item.channel for item in resolved.values()} == {"Meta"}


def test_counterfactual_holds_fixed_mediator_control_and_event():
    activities = [
        _activity("paid-tv", "tv"),
        _activity(
            "crm",
            "crm",
            ownership="owned",
            role="mediator",
            economics="response_only",
            planning="fixed",
        ),
        _activity(
            "pr-event",
            "pr",
            ownership="earned",
            role="event",
            economics="response_only",
            planning="scenario_only",
        ),
    ]
    plan = {"2026-03": {"tv": 100.0, "crm": 20.0, "pr": 1.0}}
    resolved = resolve_counterfactual(
        plan,
        market="UK",
        activity_definitions=activities,
        policy=CounterfactualPolicy(),
    )

    assert resolved == {"2026-03": {"tv": 0.0, "crm": 20.0, "pr": 1.0}}


def test_demand_capture_requires_an_explicit_governed_rule():
    search = _activity(
        "brand-search",
        "search",
        role="demand_capture",
    )
    with pytest.raises(ValueError, match="requires an explicit value"):
        resolve_counterfactual(
            {"2026-03": {"search": 25.0}},
            market="UK",
            activity_definitions=[search],
            policy=CounterfactualPolicy(),
        )

    held = resolve_counterfactual(
        {"2026-03": {"search": 25.0}},
        market="UK",
        activity_definitions=[search],
        policy=CounterfactualPolicy(demand_capture_rule="hold_plan"),
    )
    assert held["2026-03"]["search"] == 25.0


def test_response_only_activity_needs_no_artificial_cost_mapping():
    organic = _activity(
        "organic-social",
        "organic",
        ownership="owned",
        economics="response_only",
        planning="scenario_only",
    )
    plan = ScenarioPlan(
        monetary_decisions_by_period={},
        activity_quantity_assumptions_by_period={
            "2026-03": {"organic-social": 42.0}
        },
    )
    model_input, costs, coverage = resolve_scenario_plan(
        plan,
        market="UK",
        activity_definitions=[organic],
    )

    assert model_input == {"2026-03": {"organic": 42.0}}
    assert not any(costs.values())
    assert coverage["economics_status"] == "response_only"


def test_flat_optimizer_plan_is_classified_before_economics():
    activities = [
        _activity("paid-tv", "tv", channel="TV"),
        _activity(
            "organic-social",
            "organic",
            channel="Social",
            ownership="owned",
            economics="response_only",
            planning="scenario_only",
        ),
    ]
    plan = classify_activity_plan(
        {"2026-03": {"tv": 100.0, "organic": 42.0}},
        market="UK",
        activity_definitions=activities,
    )

    assert plan.monetary_decisions_by_period == {
        "2026-03": {"tv": 100.0}
    }
    assert plan.activity_quantity_assumptions_by_period == {
        "2026-03": {"organic": 42.0}
    }


def test_only_unmapped_monetary_activity_is_blocked():
    paid = _activity("paid-tv", "tv", channel="TV")
    organic = _activity(
        "organic-social",
        "organic",
        ownership="owned",
        economics="response_only",
        planning="scenario_only",
    )
    plan = ScenarioPlan(
        monetary_decisions_by_period={"2026-03": {"paid-tv": 100.0}},
        activity_quantity_assumptions_by_period={
            "2026-03": {"organic-social": 10.0}
        },
    )
    with pytest.raises(ValueError, match=r"\['paid-tv'\]"):
        resolve_scenario_plan(
            plan,
            market="UK",
            activity_definitions=[paid, organic],
        )


def test_mixed_plan_preserves_paid_media_economics():
    activities = [
        _activity("paid-tv", "tv", channel="TV"),
        _activity(
            "organic-social",
            "organic",
            channel="Social",
            ownership="owned",
            economics="response_only",
            planning="scenario_only",
        ),
    ]
    plan = ScenarioPlan(
        monetary_decisions_by_period={"2026-03": {"paid-tv": 100.0}},
        activity_quantity_assumptions_by_period={
            "2026-03": {"organic-social": 20.0}
        },
    )
    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=["fh"],
        channels=["tv", "organic"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0, 1],
        dna_outcome_id="fh",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
    )
    params = FHPosteriorParams(
        decay_rate={"tv": 0.5, "organic": 0.5},
        hill_K={"tv": 100.0, "organic": 20.0},
        hill_S={"tv": 1.0, "organic": 1.0},
        beta={"fh": {"tv": 0.2, "organic": 0.1}},
        pathway_strength={},
        promo_coef={"fh": 0.0},
        market_offset={"UK": {"fh": 0.0}},
        intercept={"fh": 3.0},
        trend_coef={"fh": 0.0},
        gamma_fourier={"fh": np.zeros(6)},
        alpha={"fh": 5.0},
        control_coef={},
        outcome_control_coef={},
    )
    approval = ModelApproval(approved_by="reviewer", **IDENTITY)
    result = evaluate_scenario(
        {"2026-03": {"tv": 100.0, "organic": 20.0}},
        "UK",
        meta,
        params,
        {
            "2026-03": {
                "trend": 0.0,
                "fourier": np.zeros(6),
                "promo": {"fh": 0.0},
                "controls": {},
                "outcome_controls": {},
            }
        },
        scenario_plan=plan,
        activity_definitions=activities,
        counterfactual_policy=CounterfactualPolicy(),
        cost_mapping_registry=CostMappingRegistry(
            [_identity_mapping("TV")]
        ),
        cost_context_id="base-plan",
        cost_as_of_by_month={"2026-03": "2026-03-01"},
        approval=approval,
        **IDENTITY,
    )

    row = result.iloc[0]
    assert row["economics_availability_status"] == (
        "mixed_cost_and_response_only"
    )
    assert row["paid_spend"] == 100.0
    assert row["non_costed_activity_present"]
    assert row["incremental_outcome_response_only_activities"] == pytest.approx(
        0.0
    )
    assert row["paid_media_incremental_cpa"] is not None


def test_unimplemented_marginal_value_estimand_is_rejected():
    with pytest.raises(ValueError, match="Unsupported planning estimand"):
        PlanningObjective(
            estimand="marginal_incremental_value",
            value_currency="GBP",
        )


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("economic_treatment", (False, True, True, True)),
        ("planning_eligibility", (False, False, False, True)),
        ("activity_ownership", (False, True, True, True)),
        ("model_role", (True, True, True, True)),
        ("model_input_column", (True, True, True, True)),
    ],
)
def test_activity_invalidation_matrix(field, expected):
    previous = _activity("paid-tv", "tv")
    replacements = {
        "economic_treatment": {"economic_treatment": "campaign_cost"},
        "planning_eligibility": {"planning_eligibility": "fixed"},
        "activity_ownership": {"activity_ownership": "owned"},
        "model_role": {
            "model_role": "mediator",
            "planning_eligibility": "fixed",
        },
        "model_input_column": {"model_input_column": "tv_new"},
    }
    values = previous.to_dict()
    values.update(replacements[field])
    current = ActivityDefinition.from_dict(values)
    impact = activity_invalidation(previous, current)

    assert (
        impact.refit_model,
        impact.rebuild_curves,
        impact.rebuild_economics,
        impact.rebuild_scenarios,
    ) == expected
