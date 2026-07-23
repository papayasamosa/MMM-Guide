from types import SimpleNamespace

import numpy as np
import pandas as pd

from ancestry_mmm.core.brand_search import run_brand_search_mediation_ols_prototype
from ancestry_mmm.core.net_billthrough import (
    NetBillthroughCompletenessMetadata,
    validate_supplied_net_billthrough,
)
from ancestry_mmm.core.pathways import (
    MediaOutcomePathway,
    accumulate_cross_product_eta_numpy,
    pathway_catalogue_fingerprint_payload,
    pathways_drift_dataframe,
    resolve_pathway_masks,
    validate_media_outcome_pathways,
)


def _metadata():
    return NetBillthroughCompletenessMetadata(
        data_as_of_date="2024-02-01",
        model_start_week="2024-01-01",
        model_end_week="2024-01-15",
        latest_complete_net_billthrough_week="2024-01-15",
        maturity_rule_description="upstream finalisation",
        source_owner="Finance Analytics",
    )


def test_three_mixed_lag_cells_are_accumulated_once_for_model_a_and_c():
    media = {
        0: np.array([[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]]),
        1: np.array([[10.0, 20.0, 30.0], [20.0, 30.0, 40.0]]),
        3: np.array([[100.0, 200.0, 300.0], [200.0, 300.0, 400.0]]),
    }
    cells = [(0, 0), (0, 1), (1, 2)]
    lags = {(0, 0): 0, (0, 1): 1, (1, 2): 3}
    strength = np.array([[0.5, 0.25, 0.0], [0.0, 0.0, 0.1]])
    beta_a = np.array([[2.0, 4.0, 0.0], [0.0, 0.0, 3.0]])
    expected = np.column_stack(
        [
            media[0][:, 0] * 2.0 * 0.5 + media[1][:, 1] * 4.0 * 0.25,
            media[3][:, 2] * 3.0 * 0.1,
        ]
    )
    np.testing.assert_allclose(
        accumulate_cross_product_eta_numpy(media, beta_a, strength, cells, lags),
        expected,
    )
    beta_c = np.repeat(beta_a[None, :, :], 2, axis=0)
    np.testing.assert_allclose(
        accumulate_cross_product_eta_numpy(media, beta_c, strength, cells, lags),
        expected,
    )


def test_component_governance_is_independent_and_fingerprint_order_independent():
    direct = MediaOutcomePathway(
        "TV",
        "Family History",
        "fh",
        component_type="direct",
        include_in_attribution=False,
        include_in_planning=True,
    )
    delayed = MediaOutcomePathway(
        "TV",
        "Family History",
        "fh",
        component_type="cross_product",
        role="active_cross_product",
        lag_type="fixed_weeks",
        lag_weeks=2,
        include_in_attribution=True,
        include_in_planning=False,
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
    assert not masks.component_eligible("fh", "TV", "direct", "attribution")
    assert masks.component_eligible("fh", "TV", "direct", "planning")
    assert masks.component_eligible("fh", "TV", "cross_product", "attribution")
    assert not masks.component_eligible("fh", "TV", "cross_product", "planning")
    assert pathway_catalogue_fingerprint_payload(
        [direct, delayed]
    ) == pathway_catalogue_fingerprint_payload([delayed, direct])


def test_logically_identical_components_do_not_drift_when_ids_differ():
    fitted = MediaOutcomePathway(
        "TV", "Family History", "fh", pathway_id="old-random-id"
    )
    current = MediaOutcomePathway("TV", "Family History", "fh", pathway_id="another-id")
    meta = SimpleNamespace(pathway_catalogue_at_fit=[fitted])
    assert pathways_drift_dataframe([current], meta)["drift_status"].tolist() == [
        "Fitted and current"
    ]


def test_invalid_role_component_combinations_are_rejected():
    invalid = MediaOutcomePathway(
        "TV",
        "Family History",
        "fh",
        component_type="cross_product",
        role="primary_direct",
    )
    assert any(
        "incompatible role" in error
        for error in validate_media_outcome_pathways([invalid])
    )


def test_nbt_wide_frame_and_configured_market_outcome_coverage():
    frame = pd.DataFrame(
        {
            "week_start": pd.date_range("2024-01-01", periods=3, freq="7D"),
            "market": ["UK"] * 3,
            "fh_net_billthrough_new": [1, 2, 3],
            "fh_net_billthrough_winback": [4, 5, 6],
        }
    )
    outcomes = [
        {
            "metric_key": "fh_net_billthrough_count",
            "source_column": "fh_net_billthrough_new",
            "segment": "new",
            "markets": ["UK"],
        },
        {
            "metric_key": "fh_net_billthrough_count",
            "source_column": "fh_net_billthrough_winback",
            "segment": "winback",
            "markets": ["UK"],
        },
    ]
    assert (
        validate_supplied_net_billthrough(
            frame, _metadata(), configured_outcomes=outcomes
        )
        == []
    )


def test_ols_mediation_is_a_prototype_without_interval_claims():
    x = np.arange(20.0)
    result = run_brand_search_mediation_ols_prototype(
        x, 2 * x, {"TV": x}, permitted_upstream_edges=["TV"]
    )
    assert not hasattr(result, "credible_intervals")
    assert "prototype" in type(result).__name__.lower()


def test_net_billthrough_has_explicit_objective_and_cpa_names():
    from ancestry_mmm.core.media_units import compute_cpa_by_product
    from ancestry_mmm.core.optimization import VALID_OBJECTIVES

    assert "fh_net_billthrough" in VALID_OBJECTIVES
    curve = pd.DataFrame({
        "spend": [10.0, 20.0],
        "overall_response": [1.0, 2.0],
        "fh_response": [1.0, 2.0],
        "fh_net_billthrough_response": [2.0, 4.0],
    })
    result = compute_cpa_by_product(curve)
    assert "channel_incremental_cost_per_fh_net_billthrough" in result
    assert result["channel_incremental_cost_per_fh_net_billthrough"].iloc[-1] == 5.0


def test_nbt_preprocessor_requires_and_persists_completeness_metadata():
    import pytest
    from ancestry_mmm.core.outcomes import FAMILY_HISTORY, OutcomeDefinition
    from ancestry_mmm.core.schema import ModelSpec
    from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame

    data = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=3, freq="7D"),
        "market": ["UK"] * 3, "TV": [1.0, 2.0, 3.0],
        "fh_nbt_new": [10, 11, 12],
    })
    spec = ModelSpec(date_col="date", market_col="market", markets=["UK"],
                     segment_outcomes={"New": "fh_nbt_new"}, channels=["TV"])
    outcomes = [OutcomeDefinition(
        outcome_id="fh_nbt_new", product=FAMILY_HISTORY, segment="New",
        metric="Net bill-through count", metric_key="fh_net_billthrough_count",
        source_column="fh_nbt_new", unit="bill-through subscriber",
    )]
    with pytest.raises(ValueError, match="completeness metadata is required"):
        prepare_fh_modeling_frame(data, spec, outcomes=outcomes)
    frame = prepare_fh_modeling_frame(
        data, spec, outcomes=outcomes, net_billthrough_metadata=_metadata().to_dict()
    )
    assert frame["net_billthrough_validated"]
    assert frame["net_billthrough_metadata"]["source_owner"] == "Finance Analytics"


def test_mediated_component_is_rejected_from_ordinary_equation():
    pathway = MediaOutcomePathway(
        "TV", "Family History", "fh", component_type="mediated",
        role="active_cross_product", mediation_specification="prototype",
    )
    errors = validate_media_outcome_pathways([pathway])
    assert any("cannot enter the ordinary cross-product equation" in error for error in errors)


def test_standard_shared_curve_emits_nbt_response_and_cpa():
    from ancestry_mmm.core.hierarchical_model import FHModelMeta
    from ancestry_mmm.core.media_units import compute_cpa_by_product
    from ancestry_mmm.core.predict import FHPosteriorParams, generate_channel_curve

    meta = FHModelMeta(
        markets=["UK"], outcome_ids=["nbt"], channels=["TV"], dna_channels=[],
        dna_channel_idx=[], non_dna_idx=[0], dna_outcome_id="nbt", dna_lag_weeks=0,
        unpooled_markets=[], control_names=[],
        outcome_id_to_product={"nbt": "Family History"},
        outcome_id_to_metric={"nbt": "Net bill-through count"},
        outcome_id_to_metric_key={"nbt": "fh_net_billthrough_count"},
        outcome_id_to_unit={"nbt": "bill-through subscriber"},
    )
    params = FHPosteriorParams(
        decay_rate={"TV": .5}, hill_K={"TV": 10.0}, hill_S={"TV": 1.0},
        beta={"nbt": {"TV": .2}}, pathway_strength={}, promo_coef={"nbt": 0.0},
        market_offset={"UK": {"nbt": 0.0}}, intercept={"nbt": 0.0},
        trend_coef={"nbt": 0.0}, gamma_fourier={"nbt": np.zeros(0)},
        alpha={"nbt": 1.0}, control_coef={}, outcome_control_coef={},
    )
    curve = generate_channel_curve("TV", meta, params, spend_range=np.array([0.0, 10.0]))
    assert curve["fh_net_billthrough_response"].iloc[1] > 0
    assert "channel_incremental_cost_per_fh_net_billthrough" in compute_cpa_by_product(curve)
