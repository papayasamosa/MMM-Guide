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
    curve = pd.DataFrame(
        {
            "spend": [10.0, 20.0],
            "overall_response": [1.0, 2.0],
            "fh_response": [1.0, 2.0],
            "fh_net_billthrough_response": [2.0, 4.0],
        }
    )
    result = compute_cpa_by_product(curve)
    assert "channel_incremental_cost_per_fh_net_billthrough" in result
    assert result["channel_incremental_cost_per_fh_net_billthrough"].iloc[-1] == 5.0


def test_actual_pymc_cross_product_deterministics_match_manual_mixed_lags():
    import pymc as pm

    from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
    from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
    from ancestry_mmm.core.predict import lag_frame
    from ancestry_mmm.core.schema import ModelSpec

    frame = {
        "dates": pd.date_range("2024-01-01", periods=3, freq="7D")
        .append(pd.date_range("2024-01-01", periods=3, freq="7D"))
        .to_numpy(),
        "markets": ["UK", "US"],
        "market_idx": np.array([0, 0, 0, 1, 1, 1]),
        "market_bounds": [(0, 3), (3, 6)],
        "channels": ["TV", "Radio"],
        "dna_channel_idx": [],
        "outcome_ids": ["new", "winback"],
        "outcomes": [],
        "X_media": np.array(
            [
                [1.0, 2.0],
                [2.0, 3.0],
                [3.0, 4.0],
                [1.5, 2.5],
                [2.5, 3.5],
                [3.5, 4.5],
            ]
        ),
        "Y": np.ones((6, 2)),
        "promo": np.zeros((6, 2)),
        "X_controls": np.zeros((6, 0)),
        "control_names": [],
        "fourier": np.zeros((6, 2)),
        "trend": np.tile(np.linspace(0, 1, 3), 2),
        "unpooled_markets": [],
        "media_outcome_pathways": [
            MediaOutcomePathway(
                "TV",
                "Family History",
                "new",
                role="active_cross_product",
                component_type="cross_product",
                lag_type="none",
                lag_weeks=None,
            ),
            MediaOutcomePathway(
                "Radio",
                "Family History",
                "new",
                role="active_cross_product",
                component_type="cross_product",
                lag_type="fixed_weeks",
                lag_weeks=1,
            ),
            MediaOutcomePathway(
                "TV",
                "Family History",
                "winback",
                role="active_cross_product",
                component_type="cross_product",
                lag_type="fixed_weeks",
                lag_weeks=2,
            ),
        ],
    }
    spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK", "US"],
        segment_outcomes={"new": "new", "winback": "winback"},
        channels=["TV", "Radio"],
    )

    for builder, market_specific in (
        (build_fh_hierarchical_model, False),
        (build_fh_market_specific_model, True),
    ):
        model, meta = builder(frame, spec)
        with model:
            prior = pm.sample_prior_predictive(
                draws=1,
                var_names=[
                    "eta_active_cross_product",
                    "sat_media",
                    "beta",
                    "active_cross_product_strength",
                ],
                random_seed=12,
            ).prior

        def draw(name):
            return prior[name].isel(chain=0, draw=0).values

        actual = draw("eta_active_cross_product")
        saturated = draw("sat_media")
        beta = draw("beta")
        strength = draw("active_cross_product_strength")
        expected = np.zeros_like(actual)
        for oi, ci in meta.pathway_masks.active_cells(meta.outcome_ids, meta.channels):
            lagged = lag_frame(
                saturated,
                frame["market_bounds"],
                meta.pathway_masks.lag_for_cell((oi, ci)),
            )[:, ci]
            coefficient = (
                beta[frame["market_idx"], oi, ci] if market_specific else beta[oi, ci]
            )
            expected[:, oi] += lagged * coefficient * strength[oi, ci]
        np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10)


def test_shared_and_market_specific_curves_emit_nbt_response_and_cpa():
    from ancestry_mmm.core.market_specific_predict import generate_market_channel_curve
    from ancestry_mmm.core.media_units import compute_cpa_by_product
    from ancestry_mmm.core.predict import generate_channel_curve

    masks = resolve_pathway_masks(
        ["nbt"],
        ["TV"],
        [],
        dna_channel_idx=[],
        dna_outcome_id=None,
        direct_dna_outcome_ids=[],
        dna_lag_weeks=0,
    )
    meta = SimpleNamespace(
        outcome_ids=["nbt"],
        channels=["TV"],
        pathway_masks=masks,
        outcome_id_to_metric_key={"nbt": "fh_net_billthrough_count"},
        outcome_id_to_eligibility={"nbt": {"include_in_default_reporting": True}},
        outcome_id_to_product={"nbt": "Family History"},
        outcome_id_to_metric={"nbt": "Net bill-through count"},
        kit_only_outcome_ids=[],
    )
    shared_params = SimpleNamespace(
        hill_K={"TV": 10.0},
        hill_S={"TV": 1.0},
        beta={"nbt": {"TV": 2.0}},
        pathway_strength={"nbt": {"TV": 0.0}},
    )
    market_params = SimpleNamespace(
        hill_K={"UK": {"TV": 10.0}},
        hill_S={"TV": 1.0},
        beta={"UK": {"nbt": {"TV": 2.0}}},
        pathway_strength={"nbt": {"TV": 0.0}},
    )
    shared = generate_channel_curve(
        "TV", meta, shared_params, spend_range=np.array([0.0, 10.0, 20.0])
    )
    market = generate_market_channel_curve(
        "UK", "TV", meta, market_params, spend_range=np.array([0.0, 10.0, 20.0])
    )
    for curve in (shared, market):
        assert curve["fh_net_billthrough_response"].iloc[-1] > 0
        cpa = compute_cpa_by_product(curve)
        assert "channel_incremental_cost_per_fh_net_billthrough" in cpa
        assert "channel_incremental_marginal_cost_per_fh_net_billthrough" in cpa
