import numpy as np
import pytest

from ancestry_mmm.core.media_costs import (
    CostMappingRegistry,
    FixedCostPerUnitMapping,
    IdentitySpendMapping,
    MediaInputSpec,
    PiecewiseLinearCostMapping,
    UploadedPlanCostMapping,
)


def _governance(**overrides):
    values = {
        "mapping_id": "uk-tv-2026",
        "market": "UK",
        "channel": "TV",
        "currency": "GBP",
        "cost_context_id": "base-plan",
        "source": "finance rate card",
        "effective_period_start": "2026-01-01",
        "effective_period_end": "2026-12-31",
        "assumptions": "net media cost",
        "approval_status": "approved",
        "approved_by": "finance-owner",
    }
    values.update(overrides)
    return values


def test_identity_and_fixed_cost_mappings_are_invertible():
    identity = IdentitySpendMapping(**_governance())
    fixed = FixedCostPerUnitMapping(
        **_governance(mapping_id="au-search", market="AU", currency="AUD"),
        cost_per_media_input=2.5,
    )
    spend = np.array([0.0, 25.0, 100.0])
    assert np.allclose(identity.media_input_to_spend(spend), spend)
    assert np.allclose(
        fixed.media_input_to_spend(fixed.spend_to_media_input(spend)), spend
    )
    assert np.allclose(fixed.marginal_cost_per_media_input([1, 2]), 2.5)
    assert np.allclose(fixed.marginal_media_input_per_currency(spend), 0.4)


def test_piecewise_mapping_uses_local_segment_marginal_cost():
    mapping = PiecewiseLinearCostMapping(
        **_governance(),
        spend_knots=(0.0, 100.0, 300.0),
        media_input_knots=(0.0, 1000.0, 1800.0),
    )
    assert mapping.spend_to_media_input(50.0) == pytest.approx(500.0)
    assert mapping.spend_to_media_input(200.0) == pytest.approx(1400.0)
    assert mapping.media_input_to_spend(1400.0) == pytest.approx(200.0)
    assert mapping.marginal_media_input_per_currency(50.0) == 10.0
    assert mapping.marginal_media_input_per_currency(200.0) == 4.0
    assert mapping.marginal_cost_per_media_input(1400.0) == 0.25
    with pytest.raises(ValueError, match="outside"):
        mapping.spend_to_media_input(301.0)


def test_uploaded_plan_and_registry_round_trip_preserve_governance():
    mapping = UploadedPlanCostMapping(
        **_governance(mapping_id="plan-map"),
        spend_knots=(0.0, 100.0),
        media_input_knots=(0.0, 250.0),
        plan_id="plan-42",
    )
    registry = CostMappingRegistry([mapping])
    restored = CostMappingRegistry.from_dict(registry.to_dict())
    selected = restored.resolve(
        "UK", "TV", "base-plan", as_of="2026-07-01"
    )
    assert isinstance(selected, UploadedPlanCostMapping)
    assert selected.plan_id == "plan-42"
    assert restored.resolve(
        "UK", "TV", "base-plan", as_of="2027-01-01"
    ) is None


def test_registry_selects_different_costs_by_effective_period():
    first = FixedCostPerUnitMapping(
        **_governance(
            mapping_id="h1",
            effective_period_start="2026-01-01",
            effective_period_end="2026-06-30",
        ),
        cost_per_media_input=2.0,
    )
    second = FixedCostPerUnitMapping(
        **_governance(
            mapping_id="h2",
            effective_period_start="2026-07-01",
            effective_period_end="2026-12-31",
        ),
        cost_per_media_input=3.0,
    )
    registry = CostMappingRegistry([first, second])
    assert registry.resolve(
        "UK", "TV", "base-plan", as_of="2026-03-01"
    ).mapping_id == "h1"
    assert registry.resolve(
        "UK", "TV", "base-plan", as_of="2026-09-01"
    ).mapping_id == "h2"
    with pytest.raises(ValueError, match="ambiguous"):
        registry.resolve("UK", "TV", "base-plan")


def test_draft_mapping_is_not_valid_and_media_spec_round_trips():
    draft = IdentitySpendMapping(
        **_governance(approval_status="draft", approved_by=None)
    )
    assert not draft.is_valid_for(as_of="2026-06-01")
    spec = MediaInputSpec(
        market="UK",
        channel="TV",
        column="tv_grps",
        unit="GRP",
        unit_scale=1.0,
        source="weekly delivery file",
    )
    assert MediaInputSpec.from_dict(spec.to_dict()) == spec
