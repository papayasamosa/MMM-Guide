import json

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.canonical_curves import (
    ECONOMICS_CURRENCY_ERROR,
    ECONOMICS_MISSING_VALUE,
    ECONOMICS_NEAR_ZERO_MARGINAL,
    ECONOMICS_UNIT_ERROR,
    ECONOMICS_ZERO_SPEND,
    aggregate_curve_draws,
    canonical_governance_views,
    export_canonical_curve_bank,
    generate_canonical_curve_draws,
    summarize_curve_draws,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.pathways import (
    MediaOutcomePathway,
    resolve_pathway_masks,
)

OUTCOMES = ["fh_new", "fh_returning", "dna_kit"]
CHANNELS = ["TV", "DNA"]
MARKETS = ["UK", "AU"]


def _broadcast(value, n_draw=4):
    value = np.asarray(value, dtype=float)
    return np.broadcast_to(value, (1, n_draw) + value.shape).copy()


@pytest.fixture
def meta():
    pathways = [
        MediaOutcomePathway(
            channel="TV", source_product="Family History",
            target_outcome_id="fh_new", component_type="direct",
            role="primary_direct", include_in_headline=True,
            headline_approval_status="approved", approved_by="reviewer",
            approved_at="2026-01-01",
        ),
        MediaOutcomePathway(
            channel="DNA", source_product="DNA",
            target_outcome_id="fh_new", component_type="cross_product",
            role="active_cross_product", lag_type="fixed_weeks", lag_weeks=2,
            include_in_planning=True,
        ),
        MediaOutcomePathway(
            channel="TV", source_product="Family History",
            target_outcome_id="fh_returning", component_type="direct",
            role="primary_direct",
        ),
        MediaOutcomePathway(
            channel="DNA", source_product="DNA",
            target_outcome_id="dna_kit", component_type="direct",
            role="primary_direct",
        ),
    ]
    masks = resolve_pathway_masks(
        OUTCOMES, CHANNELS, pathways, dna_channel_idx=[1],
        dna_outcome_id="fh_new", direct_dna_outcome_ids=["fh_new", "dna_kit"],
        dna_lag_weeks=2,
    )
    return FHModelMeta(
        markets=MARKETS, outcome_ids=OUTCOMES, channels=CHANNELS,
        dna_channels=["DNA"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_outcome_id="fh_new", dna_lag_weeks=2, unpooled_markets=[],
        control_names=[], pathway_masks=masks,
        outcome_id_to_product={
            "fh_new": "Family History", "fh_returning": "Family History",
            "dna_kit": "DNA",
        },
        outcome_id_to_segment={
            "fh_new": "New", "fh_returning": "Returning", "dna_kit": "New",
        },
        outcome_id_to_metric_key={
            "fh_new": "fh_net_billthrough_count",
            "fh_returning": "fh_net_billthrough_count",
            "dna_kit": "dna_kit_sale_count",
        },
        outcome_id_to_unit={oid: "count" for oid in OUTCOMES},
    )


def _trace(market_specific=False):
    beta = np.array(
        [[0.20, 0.10], [0.15, 0.00], [0.00, 0.30]]
    )
    if market_specific:
        beta = np.stack([beta, beta * 0.7])
        hill_K = [[100.0, 80.0], [70.0, 50.0]]
    else:
        hill_K = [100.0, 80.0]
    posterior = {
        "decay_rate": _broadcast([0.5, 0.4]),
        "hill_K": _broadcast(hill_K),
        "hill_S": _broadcast([1.0, 1.2]),
        "beta": _broadcast(beta)
        * np.array([1.0, 1.1, 0.9, 1.2]).reshape(
            (1, 4) + (1,) * beta.ndim
        ),
        "active_cross_product_strength": _broadcast(
            [[0.0, 0.4], [0.0, 0.0], [0.0, 0.0]]
        ),
        "promo_coef": _broadcast([0.0, 0.0, 0.0]),
        "market_offset": _broadcast(np.zeros((2, 3))),
        "intercept": _broadcast([1.0, 1.0, 1.0]),
        "trend_coef": _broadcast([0.0, 0.0, 0.0]),
        "gamma_fourier": _broadcast(np.zeros((1, 3))),
        "alpha": _broadcast([5.0, 5.0, 5.0]),
    }
    coords = {
        "outcome": OUTCOMES, "channel": CHANNELS, "market": MARKETS,
        "fourier": [0],
    }
    dims = {
        "decay_rate": ["channel"], "hill_K": (
            ["market", "channel"] if market_specific else ["channel"]
        ),
        "hill_S": ["channel"], "beta": (
            ["market", "outcome", "channel"]
            if market_specific else ["outcome", "channel"]
        ),
        "active_cross_product_strength": ["outcome", "channel"],
        "promo_coef": ["outcome"], "market_offset": ["market", "outcome"],
        "intercept": ["outcome"], "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"], "alpha": ["outcome"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


def _generate(meta, *, model_type="shared", **kwargs):
    return generate_canonical_curve_draws(
        model_run_id="run-1", meta=meta,
        trace=_trace(model_type == "market_specific"),
        model_type=model_type, n_draws=4, spend_points=[0.0, 50.0, 150.0],
        currency_by_market={"UK": "GBP", "AU": "AUD"},
        reporting_currency="GBP",
        currency_rates={("AUD", "GBP"): 0.5},
        value_per_response={"fh_new": 10, "fh_returning": 8, "dna_kit": 20},
        support_by_market_channel={
            (market, channel): {
                "current_spend": 50, "observed_spend_min": 0,
                "observed_spend_max": 100, "planning_spend_max": 150,
            }
            for market in MARKETS for channel in CHANNELS
        },
        **kwargs,
    )


@pytest.mark.parametrize("model_type", ["shared", "market_specific"])
def test_shared_and_market_specific_contract(meta, model_type):
    draws = _generate(meta, model_type=model_type)
    required = {
        "model_run_id", "market", "product", "segment", "outcome_id",
        "metric_key", "channel", "component_type", "pathway_role",
        "spend_point", "posterior_draw", "response", "marginal_response",
        "current_spend", "observed_spend_min", "observed_spend_max",
        "planning_spend_min", "planning_spend_max", "adstock_parameter",
        "lag_weeks", "hill_K", "hill_S", "coefficient", "pathway_strength",
        "include_in_attribution", "include_in_headline",
        "include_in_planning", "evidence_status", "identification_label",
        "is_extrapolated", "average_cpa", "marginal_cpa",
        "average_roi", "marginal_roi", "economics_scope",
        "economics_denominator",
    }
    assert required <= set(draws.columns)
    assert set(draws["market"]) == set(MARKETS)
    assert draws["posterior_draw"].nunique() == 4
    if model_type == "market_specific":
        uk = draws.query("market == 'UK' and spend_point == 1")["response"].mean()
        au = draws.query("market == 'AU' and spend_point == 1")["response"].mean()
        assert uk != pytest.approx(au)


def test_direct_delayed_segments_nbt_and_governance_views(meta):
    draws = _generate(meta)
    delayed = draws.query("component_type == 'cross_product'")
    assert set(delayed["lag_weeks"]) == {2}
    assert set(draws["segment"]) >= {"New", "Returning"}
    views = canonical_governance_views(draws)
    nbt_source = draws.query("metric_key == 'fh_net_billthrough_count'")
    expected = nbt_source.groupby(
        ["market", "channel", "spend_point", "posterior_draw"]
    )["response"].sum()
    actual = views["fh_nbt_total"].set_index(
        ["market", "channel", "spend_point", "posterior_draw"]
    )["response"]
    pd.testing.assert_series_equal(
        actual.sort_index(), expected.sort_index(), check_names=False
    )
    assert set(views) == {
        "segment", "product", "market", "fh_nbt_total", "direct", "halo",
        "headline", "planning",
    }


def test_draw_aggregation_precedes_summary_and_propagates_uncertainty(meta):
    draws = _generate(meta)
    aggregated = aggregate_curve_draws(
        draws, by=["model_run_id", "market", "channel", "spend_point"]
    )
    summary = summarize_curve_draws(
        aggregated.rename(columns={"channel": "channel"})
    )
    source = aggregated.query(
        "market == 'UK' and channel == 'TV' and spend_point == 1"
    )["response"]
    row = summary.query(
        "market == 'UK' and channel == 'TV' and spend_point == 1"
    ).iloc[0]
    assert row["response_posterior_mean"] == pytest.approx(source.mean())
    assert row["response_lower_interval"] < row["response_upper_interval"]


def test_zero_spend_near_zero_marginal_and_extrapolation_status(meta):
    draws = _generate(meta)
    assert set(draws.query("spend_point == 0")["average_economics_status"]) == {
        ECONOMICS_ZERO_SPEND
    }
    zero_marginal = draws.query(
        "outcome_id == 'dna_kit' and channel == 'DNA' and spend_point == 0"
    )
    assert set(zero_marginal["marginal_economics_status"]) == {
        ECONOMICS_NEAR_ZERO_MARGINAL
    }
    assert draws.query("spend_point == 2")["is_extrapolated"].all()


def test_missing_values_units_and_currency_are_flagged(meta):
    no_value = generate_canonical_curve_draws(
        model_run_id="run", meta=meta, trace=_trace(), n_draws=1,
        spend_points=[10], currency_by_market={"UK": "GBP", "AU": "GBP"},
    )
    assert set(no_value["roi_status"]) == {ECONOMICS_MISSING_VALUE}
    bad_unit = generate_canonical_curve_draws(
        model_run_id="run", meta=meta, trace=_trace(), n_draws=1,
        spend_points=[10], spend_unit="bananas",
        currency_by_market={"UK": "GBP", "AU": "GBP"},
    )
    assert set(bad_unit["average_economics_status"]) == {ECONOMICS_UNIT_ERROR}
    bad_currency = generate_canonical_curve_draws(
        model_run_id="run", meta=meta, trace=_trace(), n_draws=1,
        spend_points=[10], currency_by_market={"UK": "GBP", "AU": "AUD"},
        reporting_currency="GBP",
    )
    assert set(
        bad_currency.query("market == 'AU'")["average_economics_status"]
    ) == {ECONOMICS_CURRENCY_ERROR}


def test_spend_unit_conversion_is_applied_to_spend_support_and_cpa(meta):
    draws = generate_canonical_curve_draws(
        model_run_id="run", meta=meta, trace=_trace(), n_draws=1,
        spend_points=[10], spend_unit="currency_thousands",
        spend_unit_scale=1000,
        currency_by_market={"UK": "GBP", "AU": "GBP"},
        value_per_response={"fh_new": 10, "fh_returning": 8, "dna_kit": 20},
    )
    assert set(draws["spend"]) == {10000}
    assert (draws["hill_K"] >= 50000).all()
    valid = draws[draws["response"] > 0]
    np.testing.assert_allclose(
        valid["average_cpa"], valid["spend"] / valid["response"]
    )


def test_serialization_and_curve_bank_export(meta, tmp_path):
    draws = _generate(meta)
    summary = summarize_curve_draws(draws)
    paths = export_canonical_curve_bank(draws, summary, tmp_path)
    restored = pd.read_parquet(paths[0])
    pd.testing.assert_frame_equal(restored, draws)
    schema = json.loads(paths[2].read_text())
    assert schema["version"] == "G2A-1"
    assert schema["draw_rows"] == len(draws)
