from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.attribution import compute_shapley_contributions
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.net_billthrough import (
    NetBillthroughCompletenessMetadata,
    assert_model_frame_net_billthrough_complete,
)
from ancestry_mmm.core.outcomes import FAMILY_HISTORY, OutcomeDefinition
from ancestry_mmm.core.pathways import (
    MediaOutcomePathway,
    ResolvedPathwayMasks,
    resolve_pathway_masks,
    validate_media_outcome_pathways,
)
from ancestry_mmm.core.optimization import WEEKS_PER_MONTH, evaluate_scenario
from ancestry_mmm.core.predict import (
    FHPosteriorParams,
    steady_state_outcome_response,
)
from ancestry_mmm.core.schema import ModelSpec


def _pathway(**overrides):
    values = {
        "channel": "TV",
        "source_product": "Family History",
        "target_outcome_id": "fh",
    }
    values.update(overrides)
    return MediaOutcomePathway(**values)


def test_component_collection_rejects_disagreeing_legacy_cache():
    resolved = resolve_pathway_masks(
        ["fh"],
        ["TV"],
        [_pathway()],
        dna_channel_idx=[],
        dna_outcome_id=None,
        direct_dna_outcome_ids=[],
        dna_lag_weeks=0,
    )
    payload = resolved.to_dict()
    payload["primary_channels_by_outcome"] = {"fh": []}
    with pytest.raises(ValueError, match="authoritative component collection"):
        ResolvedPathwayMasks.from_dict(payload)


def test_components_and_compatibility_caches_cannot_be_mutated_independently():
    resolved = resolve_pathway_masks(
        ["fh"],
        ["TV"],
        [_pathway()],
        dna_channel_idx=[],
        dna_outcome_id=None,
        direct_dna_outcome_ids=[],
        dna_lag_weeks=0,
    )
    with pytest.raises(AttributeError, match="immutable"):
        resolved.primary_channels_by_outcome = {}
    with pytest.raises(TypeError, match="read-only"):
        resolved.primary_channels_by_outcome["fh"] = []
    with pytest.raises(TypeError, match="read-only"):
        resolved.primary_channels_by_outcome["fh"].append("Radio")
    with pytest.raises(TypeError, match="read-only"):
        resolved.components.append(resolved.components[0])
    with pytest.raises(FrozenInstanceError):
        resolved.components[0].include_in_planning = False

    copied = deepcopy(resolved)
    assert copied.to_dict() == resolved.to_dict()
    assert asdict(resolved)["components"][0]["channel"] == "TV"


def test_old_mask_only_bundle_is_migrated_to_read_only_compatibility_views():
    restored = ResolvedPathwayMasks.from_dict(
        {
            "primary_channels_by_outcome": {"fh": ["TV"]},
            "active_channels_by_outcome": {},
            "exploratory_channels_by_outcome": {},
            "cross_product_lag_weeks": 4,
            "lag_weeks_by_cell": {},
            "prior_scale_by_cell": {},
            "planning_by_cell": {},
        }
    )
    assert restored.primary_matrix(["fh"], ["TV"])[0, 0] == 1.0
    with pytest.raises(TypeError, match="read-only"):
        restored.primary_channels_by_outcome["fh"].clear()


def test_legacy_catalogue_migrates_headline_decision_and_unused_direct_prior():
    migrated = MediaOutcomePathway.from_dict(
        {
            "channel": "TV",
            "source_product": "Family History",
            "target_outcome_id": "fh",
            "role": "primary_direct",
            "prior_scale": 1.0,
            "include_in_attribution": True,
            "evidence_status": "model_supported",
        }
    )
    assert migrated.prior_scale is None
    assert migrated.include_in_headline
    assert migrated.headline_approval_status == "approved"
    assert migrated.approved_by == "legacy_migration"
    assert validate_media_outcome_pathways([migrated]) == []


def test_headline_approval_is_separate_from_evidence_and_mediation_is_diagnostic():
    evidence_only = _pathway(
        evidence_status="model_supported",
        include_in_headline=True,
    )
    assert any(
        "without explicit approval" in error
        for error in validate_media_outcome_pathways([evidence_only])
    )

    mediated = _pathway(
        role="active_cross_product",
        component_type="mediated",
        include_in_planning=True,
        include_in_headline=True,
        headline_approval_status="approved",
        approved_by="Analyst",
        approved_at="2026-07-23",
    )
    errors = validate_media_outcome_pathways([mediated])
    assert any("cannot be planning-enabled" in error for error in errors)
    assert any("cannot be headline-enabled" in error for error in errors)


def test_attribution_headline_and_planning_views_sum_only_eligible_components():
    direct = _pathway(
        include_in_attribution=True,
        include_in_planning=True,
        include_in_headline=True,
        headline_approval_status="approved",
        approved_by="Analyst",
        approved_at="2026-07-23",
    )
    delayed = _pathway(
        role="active_cross_product",
        component_type="cross_product",
        lag_type="fixed_weeks",
        lag_weeks=1,
        prior_scale=0.2,
        include_in_attribution=True,
        include_in_planning=False,
        include_in_headline=False,
    )
    masks = resolve_pathway_masks(
        ["fh"],
        ["TV"],
        [direct, delayed],
        dna_channel_idx=[],
        dna_outcome_id=None,
        direct_dna_outcome_ids=[],
        dna_lag_weeks=0,
    )
    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=["fh"],
        channels=["TV"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="fh",
        dna_lag_weeks=0,
        unpooled_markets=[],
        control_names=[],
        pathway_masks=masks,
    )
    params = FHPosteriorParams(
        decay_rate={"TV": 0.0},
        hill_K={"TV": 100.0},
        hill_S={"TV": 1.0},
        beta={"fh": {"TV": 1.0}},
        pathway_strength={"fh": {"TV": 0.5}},
        promo_coef={"fh": 0.0},
        market_offset={"UK": {"fh": 0.0}},
        intercept={"fh": 0.0},
        trend_coef={"fh": 0.0},
        gamma_fourier={"fh": np.zeros(2)},
        alpha={"fh": 5.0},
        control_coef={},
        outcome_control_coef={},
    )
    frame = {
        "markets": ["UK"],
        "market_idx": np.zeros(3, dtype=int),
        "market_bounds": [(0, 3)],
        "X_media": np.array([[50.0], [0.0], [0.0]]),
        "promo": np.zeros((3, 1)),
        "trend": np.zeros(3),
        "fourier": np.zeros((3, 2)),
        "control_names": [],
        "X_controls": np.zeros((3, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }

    attribution = compute_shapley_contributions(
        frame, meta, params, n_permutations=1, purpose="attribution"
    )
    headline = compute_shapley_contributions(
        frame, meta, params, n_permutations=1, purpose="headline"
    )
    assert attribution["channel_contributions"]["TV"][1, 0] > 0
    assert headline["channel_contributions"]["TV"][1, 0] == pytest.approx(0.0)
    np.testing.assert_allclose(
        headline["baseline"] + headline["channel_contributions"]["TV"],
        headline["mu_total"],
    )

    full = steady_state_outcome_response(
        "UK", {"TV": 50.0}, meta, params, planning_only=False
    )
    planning = steady_state_outcome_response(
        "UK", {"TV": 50.0}, meta, params, planning_only=True
    )
    direct_only_params = SimpleNamespace(
        **{
            **params.__dict__,
            "pathway_strength": {"fh": {"TV": 0.0}},
        }
    )
    direct_only = steady_state_outcome_response(
        "UK", {"TV": 50.0}, meta, direct_only_params, planning_only=False
    )
    assert full["fh"] > planning["fh"]
    assert planning["fh"] == pytest.approx(direct_only["fh"])

    identity = {
        "model_run_id": "g114-parity",
        "data_fingerprint": "data",
        "model_spec_fingerprint": "spec",
        "posterior_fingerprint": "posterior",
    }
    scenario = evaluate_scenario(
        {"2026-07": {"TV": 50.0}},
        "UK",
        meta,
        params,
        {
            "2026-07": {
                "trend": 0.0,
                "fourier": np.zeros(2),
                "promo": {"fh": 0.0},
                "controls": {},
                "outcome_controls": {},
            }
        },
        approval=ModelApproval(approved_by="Analyst", **identity),
        **identity,
    )
    assert scenario.loc[0, "predicted_outcome"] == pytest.approx(
        planning["fh"] * WEEKS_PER_MONTH
    )


def test_both_model_builders_defensively_revalidate_prepared_nbt_values():
    outcome = OutcomeDefinition(
        outcome_id="fh_nbt",
        product=FAMILY_HISTORY,
        segment="New",
        metric="Net bill-through count",
        source_column="NBT_New",
    )
    metadata = NetBillthroughCompletenessMetadata(
        data_as_of_date="2026-07-31",
        model_start_week="2026-07-06",
        model_end_week="2026-07-20",
        latest_complete_net_billthrough_week="2026-07-20",
        maturity_rule_description="authoritative upstream finalisation",
        source_owner="Finance Analytics",
    )
    frame = {
        "outcomes": [outcome],
        "outcome_ids": ["fh_nbt"],
        "Y": np.array([[1.0], [-1.0], [3.0]]),
        "dates": pd.date_range("2026-07-06", periods=3, freq="7D").to_numpy(),
        "market_idx": np.zeros(3, dtype=int),
        "markets": ["UK"],
        "net_billthrough_metadata": metadata,
    }
    with pytest.raises(ValueError, match="training blocked"):
        assert_model_frame_net_billthrough_complete(frame)

    spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "NBT_New"},
        channels=["TV"],
    )
    for builder in (
        build_fh_hierarchical_model,
        build_fh_market_specific_model,
    ):
        with pytest.raises(ValueError, match="training blocked"):
            builder(frame, spec)
