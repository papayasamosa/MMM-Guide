import numpy as np
import pytest

from ancestry_mmm.core.media_costs import (
    CostMappingRegistry,
    FixedCostPerUnitMapping,
    IdentitySpendMapping,
    MediaInputSpec,
    MediaInputSupport,
    MonetarySpendSupport,
    PiecewiseLinearCostMapping,
    UploadedPlanCostMapping,
    cost_mapping_from_dict,
    derive_monetary_support,
)
from ancestry_mmm.core.optimization import (
    monetary_plan_to_media_input,
    require_current_cost_mapping,
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
        "approved_at": "2026-01-01T10:00:00Z",
        "owner": "media-finance",
        "approval_note": "Approved net media rate",
        "last_reviewed_at": "2026-01-01",
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
    support = MediaInputSupport(
        market="UK",
        channel="TV",
        unit="GRP",
        current=50,
        observed_min=0,
        observed_max=100,
        planning_min=0,
        planning_max=120,
        current_method="last_4_week_average",
        source="frame",
        provenance="X_media",
    )
    assert MediaInputSupport.from_dict(support.to_dict()) == support


def test_legacy_approval_requires_governance_migration():
    legacy = {
        "mapping_id": "legacy",
        "method": "identity_spend",
        "market": "UK",
        "channel": "TV",
        "currency": "GBP",
        "approval_status": "approved",
        "approved_by": "old-owner",
        "schema_version": 1,
    }
    restored = cost_mapping_from_dict(legacy)
    assert restored.approval_status == "migration_required"
    assert not restored.is_valid_for(as_of="2026-01-01")


def test_monetary_plan_conversion_blocks_unmapped_cells():
    mapping = FixedCostPerUnitMapping(
        **_governance(),
        cost_per_media_input=2.0,
    )
    registry = CostMappingRegistry([mapping])
    converted = monetary_plan_to_media_input(
        {"2026-03": {"TV": 100.0}},
        market="UK",
        registry=registry,
        cost_context_id="base-plan",
        as_of_by_period={"2026-03": "2026-03-01"},
    )
    assert converted == {"2026-03": {"TV": 50.0}}
    with pytest.raises(ValueError, match="blocked"):
        monetary_plan_to_media_input(
            {"2026-03": {"Search": 100.0}},
            market="UK",
            registry=registry,
            cost_context_id="base-plan",
            as_of_by_period={"2026-03": "2026-03-01"},
        )


def test_mapping_fingerprint_invalidates_stale_artifact():
    registry = CostMappingRegistry(
        [
            FixedCostPerUnitMapping(
                **_governance(),
                cost_per_media_input=2.0,
            )
        ]
    )
    artifact = {"cost_mapping_fingerprint": registry.fingerprint()}
    require_current_cost_mapping(artifact, registry.fingerprint())
    changed = CostMappingRegistry(
        [
            FixedCostPerUnitMapping(
                **_governance(mapping_id="replacement"),
                cost_per_media_input=3.0,
                supersedes_mapping_id="uk-tv-2026",
            )
        ]
    )
    with pytest.raises(ValueError, match="stale"):
        require_current_cost_mapping(artifact, changed.fingerprint())


def test_derived_monetary_support_round_trips():
    mapping = FixedCostPerUnitMapping(
        **_governance(), cost_per_media_input=2.0
    )
    media = MediaInputSupport(
        market="UK", channel="TV", unit="TVR", current=50,
        observed_min=0, observed_max=100, planning_min=0,
        planning_max=120, current_method="current", source="frame",
        provenance="X_media",
    )
    monetary = derive_monetary_support(
        media,
        mapping,
        reporting_currency="GBP",
        fx_rate=1.0,
        mapping_fingerprint="abc",
    )
    assert monetary.observed_local_max == 200
    assert MonetarySpendSupport.from_dict(monetary.to_dict()) == monetary
