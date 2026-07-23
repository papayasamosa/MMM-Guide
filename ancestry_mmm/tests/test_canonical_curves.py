import json

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.canonical_curves import (
    ECONOMICS_COMPONENT_COST_UNALLOCATED,
    ECONOMICS_MISSING_VALUE,
    ECONOMICS_ZERO_SPEND,
    SUPPORT_MISSING,
    ComponentCostAllocation,
    CurveReferenceContext,
    PortfolioPerturbation,
    aggregate_curve_draws,
    aggregate_portfolio_marginal,
    canonical_governance_views,
    export_canonical_curve_bank,
    generate_canonical_curve_draws,
    reconcile_curve_to_attribution,
    reference_context_from_model_frame,
    summarize_curve_draws,
    support_from_model_frame,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.media_costs import (
    FixedCostPerUnitMapping,
    MediaInputSpec,
)
from ancestry_mmm.core.pathways import MediaOutcomePathway, resolve_pathway_masks
from ancestry_mmm.core.predict import (
    extract_posterior_params,
    steady_state_outcome_response,
)

OUTCOMES = ["fh_new", "fh_returning", "dna_kit"]
CHANNELS = ["TV", "DNA"]
MARKETS = ["UK", "AU"]
VALUES = {"fh_new": 10, "fh_returning": 8, "dna_kit": 20}


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
            target_outcome_id="fh_new", component_type="direct",
            role="primary_direct", allow_cross_product_primary=True,
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
        control_names=["macro"], pathway_masks=masks,
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
    beta = np.array([[0.20, 0.10], [0.15, 0.00], [0.00, 0.30]])
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
        "promo_coef": _broadcast([0.25, 0.10, 0.05]),
        "market_offset": _broadcast(
            [[0.0, 0.0, 0.0], [0.3, -0.1, 0.2]]
        ),
        "intercept": _broadcast([3.0, 2.5, 2.0]),
        "trend_coef": _broadcast([0.2, 0.1, 0.05]),
        "gamma_fourier": _broadcast([[0.15, -0.05, 0.1]]),
        "alpha": _broadcast([5.0, 5.0, 5.0]),
        "control_coef": _broadcast([0.12]),
    }
    coords = {
        "outcome": OUTCOMES, "channel": CHANNELS, "market": MARKETS,
        "fourier": [0], "control": ["macro"],
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["market", "channel"] if market_specific else ["channel"],
        "hill_S": ["channel"],
        "beta": (
            ["market", "outcome", "channel"]
            if market_specific else ["outcome", "channel"]
        ),
        "active_cross_product_strength": ["outcome", "channel"],
        "promo_coef": ["outcome"], "market_offset": ["market", "outcome"],
        "intercept": ["outcome"], "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"], "alpha": ["outcome"],
        "control_coef": ["control"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


def _contexts(*, trend=0.5, fourier=0.25, promo=0.0, other_tv=20.0):
    return {
        market: CurveReferenceContext(
            reference_context_id=f"{market}-recent",
            mode="recent_average",
            market=market,
            trend=trend,
            fourier=(fourier,),
            promo={oid: promo for oid in OUTCOMES},
            controls={"macro": 0.4},
            outcome_controls={},
            other_channel_spend={"TV": other_tv, "DNA": 30.0},
            counterfactual_spend=0.0,
            reference_period_start="2026-04-01",
            reference_period_end="2026-06-30",
        )
        for market in MARKETS
    }


def _support():
    return {
        (market, channel): {
            "current_spend": 50,
            "observed_spend_min": 0,
            "observed_spend_max": 100,
            "planning_spend_min": 0,
            "planning_spend_max": 150,
            "current_spend_method": "last_4_week_average",
            "current_spend_reference_period_start": "2026-06-01",
            "current_spend_reference_period_end": "2026-06-30",
        }
        for market in MARKETS for channel in CHANNELS
    }


def _generate(meta, *, model_type="shared", contexts=None, **kwargs):
    value_map = kwargs.pop("value_per_response", VALUES)
    return generate_canonical_curve_draws(
        model_run_id="run-1", meta=meta,
        trace=_trace(model_type == "market_specific"),
        reference_contexts=contexts or _contexts(),
        model_type=model_type, n_draws=4,
        spend_points=[0.0, 50.0, 150.0],
        currency_by_market={"UK": "GBP", "AU": "AUD"},
        reporting_currency="GBP",
        currency_rates={("AUD", "GBP"): 0.5},
        fx_as_of_date="2026-07-01",
        value_per_response=value_map,
        support_by_market_channel=_support(),
        **kwargs,
    )


@pytest.mark.parametrize("model_type", ["shared", "market_specific"])
def test_contract_uses_outcome_scale_counterfactuals(meta, model_type):
    draws = _generate(meta, model_type=model_type)
    required = {
        "reference_context_id", "mu_with", "mu_without",
        "incremental_response", "media_eta_contribution",
        "marginal_incremental_response_per_currency_unit",
        "marginal_calculation_method", "marginal_delta_local_spend",
        "local_spend", "reporting_currency_spend", "fx_rate",
        "observed_support_status", "current_spend_method",
        "counterfactual_prediction_reconciliation_error",
    }
    assert required <= set(draws)
    assert np.allclose(
        draws.groupby(
            ["market", "outcome_id", "channel", "spend_point", "posterior_draw"]
        )["incremental_response"].sum(),
        draws.groupby(
            ["market", "outcome_id", "channel", "spend_point", "posterior_draw"]
        ).first()["mu_with"]
        - draws.groupby(
            ["market", "outcome_id", "channel", "spend_point", "posterior_draw"]
        ).first()["mu_without"],
    )
    assert (draws["counterfactual_prediction_reconciliation_error"] == 0).all()
    assert not np.allclose(
        draws["incremental_response"], draws["media_eta_contribution"]
    )


def test_matches_normal_prediction_function_exactly(meta):
    trace = _trace()
    draws = _generate(meta)
    params = extract_posterior_params(trace, meta, at=(0, 0))
    context = _contexts()["UK"]
    with_plan = dict(context.other_channel_spend)
    without_plan = dict(context.other_channel_spend)
    with_plan["TV"] = 50
    without_plan["TV"] = 0
    expected = steady_state_outcome_response(
        "UK", with_plan, meta, params, context.prediction_context()
    )["fh_new"] - steady_state_outcome_response(
        "UK", without_plan, meta, params, context.prediction_context()
    )["fh_new"]
    actual = draws.query(
        "market == 'UK' and channel == 'TV' and outcome_id == 'fh_new' "
        "and spend_point == 1 and posterior_draw == '0:0'"
    )["incremental_response"].sum()
    assert actual == pytest.approx(expected)


@pytest.mark.parametrize(
    ("changed", "contexts"),
    [
        ("baseline", _contexts(trend=1.0)),
        ("promotion", _contexts(promo=1.0)),
        ("seasonality", _contexts(fourier=1.0)),
        ("other_media", _contexts(other_tv=80.0)),
    ],
)
def test_context_changes_outcome_scale_response(meta, changed, contexts):
    baseline = _generate(meta)
    changed_draws = _generate(meta, contexts=contexts)
    assert not np.allclose(
        baseline["incremental_response"], changed_draws["incremental_response"]
    ), changed


def test_market_offsets_change_shared_model_outcome_counts(meta):
    draws = _generate(meta, model_type="shared")
    uk = draws.query(
        "market == 'UK' and channel == 'TV' and spend_point == 1"
    )["incremental_response"].sum()
    au = draws.query(
        "market == 'AU' and channel == 'TV' and spend_point == 1"
    )["incremental_response"].sum()
    assert uk != pytest.approx(au)


def test_direct_plus_halo_decomposition_and_no_component_cpa(meta):
    draws = _generate(meta)
    rows = draws.query(
        "market == 'UK' and channel == 'DNA' and outcome_id == 'fh_new' "
        "and spend_point == 1 and posterior_draw == '0:0'"
    )
    assert set(rows["component_type"]) == {"direct", "cross_product"}
    assert rows["incremental_response"].sum() == pytest.approx(
        rows["channel_total_incremental_response"].iloc[0]
    )
    assert rows["average_cpa"].isna().all()
    assert set(rows["average_economics_status"]) == {
        ECONOMICS_COMPONENT_COST_UNALLOCATED
    }


def test_explicit_component_cost_allocation_enables_component_economics(meta):
    grouped = {}
    for component in meta.pathway_masks.components:
        if component.included_in_fit and component.component_type in {
            "direct", "cross_product"
        }:
            grouped.setdefault(
                (component.outcome_id, component.channel), []
            ).append(component.component_type)
    shares = {
        (outcome_id, channel, component_type): 1 / len(component_types)
        for (outcome_id, channel), component_types in grouped.items()
        for component_type in component_types
    }
    shares[("fh_new", "DNA", "direct")] = 0.6
    shares[("fh_new", "DNA", "cross_product")] = 0.4
    allocation = ComponentCostAllocation(
        allocation_id="analyst-v1",
        shares=shares,
    )
    rows = _generate(meta, component_cost_allocation=allocation).query(
        "market == 'UK' and channel == 'DNA' and outcome_id == 'fh_new' "
        "and spend_point == 1"
    )
    assert set(rows["component_cost_share"]) == {0.6, 0.4}
    assert rows["average_cpa"].notna().all()
    assert set(rows["economics_scope"]) == {"component_allocated_cost"}


def test_channel_nbt_economics_count_spend_once(meta):
    draws = _generate(meta)
    channel = aggregate_curve_draws(
        draws,
        by=[
            "model_run_id", "reference_context_id", "market", "channel",
            "spend_point", "outcome_id", "metric_key",
        ],
        value_per_response=VALUES,
    )
    row = channel.query(
        "market == 'UK' and channel == 'DNA' and outcome_id == 'fh_new' "
        "and spend_point == 1 and posterior_draw == '0:0'"
    ).iloc[0]
    source = draws.query(
        "market == 'UK' and channel == 'DNA' and outcome_id == 'fh_new' "
        "and spend_point == 1 and posterior_draw == '0:0'"
    )
    assert row["spend"] == source["reporting_currency_spend"].iloc[0]
    assert row["incremental_response"] == pytest.approx(
        source["incremental_response"].sum()
    )
    assert row["average_cpa"] == pytest.approx(
        row["incremental_spend"] / row["incremental_response"]
    )
    assert row["average_roi"] == pytest.approx(
        row["incremental_response"] * VALUES["fh_new"]
        / row["incremental_spend"]
    )
    assert row["marginal_cpa"] == pytest.approx(
        1 / row["marginal_incremental_response_per_currency_unit"]
    )


def test_finite_difference_matches_log_link_analytic_derivative(meta):
    draws = _generate(meta, marginal_delta=1e-3)
    row = draws.query(
        "market == 'UK' and channel == 'TV' and outcome_id == 'fh_new' "
        "and spend_point == 1 and posterior_draw == '0:0'"
    ).iloc[0]
    params = extract_posterior_params(_trace(), meta, at=(0, 0))
    x = 50.0
    K = params.hill_K["TV"]
    S = params.hill_S["TV"]
    hill_derivative = S * K**S * x ** (S - 1) / (x**S + K**S) ** 2
    expected = row["mu_with"] * params.beta["fh_new"]["TV"] * hill_derivative
    assert row["channel_total_marginal_response"] == pytest.approx(
        expected, rel=1e-5
    )


def test_zero_spend_and_missing_value_status(meta):
    draws = _generate(meta, value_per_response={})
    channel = aggregate_curve_draws(
        draws,
        by=[
            "model_run_id", "reference_context_id", "market", "channel",
            "spend_point", "outcome_id",
        ],
    )
    assert set(channel.query("spend_point == 0")["average_economics_status"]) == {
        ECONOMICS_ZERO_SPEND
    }
    assert set(channel.query("spend_point == 1")["roi_status"]) == {
        ECONOMICS_MISSING_VALUE
    }


def test_missing_support_is_unknown_and_blocks_planning(meta):
    draws = generate_canonical_curve_draws(
        model_run_id="run", meta=meta, trace=_trace(), n_draws=1,
        reference_contexts=_contexts(), spend_points=[10],
        currency_by_market={"UK": "GBP", "AU": "GBP"},
        reporting_currency="GBP", fx_as_of_date="2026-07-01",
    )
    assert set(draws["observed_support_status"]) == {SUPPORT_MISSING}
    assert draws["is_extrapolated"].isna().all()
    assert not draws["planning_support_eligible"].any()
    assert not draws["include_in_planning"].any()
    with pytest.raises(ValueError, match="Observed support is missing"):
        generate_canonical_curve_draws(
            model_run_id="run", meta=meta, trace=_trace(), n_draws=1,
            reference_contexts=_contexts(),
            currency_by_market={"UK": "GBP", "AU": "GBP"},
            reporting_currency="GBP", fx_as_of_date="2026-07-01",
        )


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("latest_complete_week", 13.0),
        ("last_4_week_average", 11.5),
        ("last_13_week_average", 7.0),
    ],
)
def test_current_spend_definitions(meta, method, expected):
    frame = {
        "X_media": np.column_stack(
            [np.tile(np.arange(1.0, 14.0), 2), np.tile(np.arange(2.0, 15.0), 2)]
        ),
        "market_idx": np.repeat([0, 1], 13),
        "dates": np.tile(pd.date_range("2026-01-04", periods=13, freq="W"), 2),
    }
    support = support_from_model_frame(
        frame, meta, current_spend_method=method
    )
    assert support[("UK", "TV")]["current_spend"] == pytest.approx(expected)
    assert support[("UK", "TV")]["current_spend_method"] == method


def test_reference_context_builder_uses_prepared_business_context(meta):
    n = 14
    frame = {
        "X_media": np.column_stack(
            [np.tile(np.arange(1.0, n + 1), 2), np.tile(np.arange(2.0, n + 2), 2)]
        ),
        "market_idx": np.repeat([0, 1], n),
        "dates": np.tile(pd.date_range("2026-01-04", periods=n, freq="W"), 2),
        "trend": np.tile(np.linspace(0, 1, n), 2),
        "fourier": np.tile(np.linspace(-1, 1, n * 1).reshape(n, 1), (2, 1)),
        "promo": np.tile(np.zeros((n, len(OUTCOMES))), (2, 1)),
        "X_controls": np.tile(np.linspace(0, 1, n).reshape(n, 1), (2, 1)),
        "control_names": ["macro"],
        "outcome_controls": {},
        "outcome_control_names": {},
    }
    context = reference_context_from_model_frame(
        frame, meta, market="UK", mode="recent_average",
        reference_context_id="uk-recent",
    )
    assert context.reference_context_id == "uk-recent"
    assert context.other_channel_spend["TV"] == pytest.approx(8.0)
    assert context.reference_period_start == "2026-01-11"
    assert context.controls["macro"] > 0


def test_multi_market_currency_governance_and_conversion(meta):
    with pytest.raises(ValueError, match="explicit ISO currency"):
        generate_canonical_curve_draws(
            model_run_id="run", meta=meta, trace=_trace(), n_draws=1,
            reference_contexts=_contexts(), spend_points=[10],
        )
    with pytest.raises(ValueError, match="FX rate"):
        generate_canonical_curve_draws(
            model_run_id="run", meta=meta, trace=_trace(), n_draws=1,
            reference_contexts=_contexts(), spend_points=[10],
            currency_by_market={"UK": "GBP", "AU": "AUD"},
            reporting_currency="GBP", fx_as_of_date="2026-07-01",
        )
    draws = _generate(meta)
    au = draws.query("market == 'AU' and spend_point == 1")
    assert set(au["fx_rate"]) == {0.5}
    assert set(au["local_spend"]) == {50.0}
    assert set(au["reporting_currency_spend"]) == {25.0}


def test_cross_channel_aggregation_requires_explicit_portfolio_path(meta):
    draws = _generate(meta)
    with pytest.raises(ValueError, match="portfolio path"):
        aggregate_curve_draws(
            draws,
            by=["model_run_id", "market", "spend_point", "metric_key"],
        )


def test_portfolio_marginal_requires_path_and_perturbation(meta):
    draws = _generate(meta)
    channel = aggregate_curve_draws(
        draws,
        by=[
            "model_run_id", "reference_context_id", "market", "channel",
            "spend_point", "metric_key",
        ],
    )
    perturbation = PortfolioPerturbation(
        perturbation_id="current-mix",
        allocation_direction={"TV": 0.7, "DNA": 0.3},
        method="current_spend_proportional",
    )
    with pytest.raises(ValueError, match="portfolio_path_id"):
        aggregate_portfolio_marginal(
            channel, perturbation, by=["model_run_id", "market", "metric_key"]
        )
    channel = channel.query("spend_point == 1").copy()
    channel["portfolio_path_id"] = "path-1"
    portfolio = aggregate_portfolio_marginal(
        channel, perturbation, by=["model_run_id", "market", "metric_key"]
    )
    assert set(portfolio["portfolio_perturbation_id"]) == {"current-mix"}
    assert (
        portfolio["portfolio_marginal_cpa"]
        == 1 / portfolio["portfolio_marginal_response"]
    ).all()


def test_governance_views_are_channel_safe_and_labelled(meta):
    views = canonical_governance_views(
        _generate(meta), value_per_response=VALUES
    )
    assert set(views) == {
        "segment", "product", "market_channel_metric", "fh_nbt_total", "direct", "halo",
        "headline", "planning",
    }
    for purpose, view in views.items():
        assert "channel" in view
        assert set(view["governance_view"]) == {purpose}
    assert views["product"]["average_roi"].notna().any()


def test_uncertainty_summary_aggregates_draws_before_summary(meta):
    channel = aggregate_curve_draws(
        _generate(meta),
        by=[
            "model_run_id", "reference_context_id", "market", "channel",
            "spend_point", "outcome_id",
        ],
        value_per_response=VALUES,
    )
    summary = summarize_curve_draws(channel)
    source = channel.query(
        "market == 'UK' and channel == 'TV' and spend_point == 1 "
        "and outcome_id == 'fh_new'"
    )["incremental_response"]
    row = summary.query(
        "market == 'UK' and channel == 'TV' and spend_point == 1 "
        "and outcome_id == 'fh_new'"
    ).iloc[0]
    assert row["incremental_response_posterior_mean"] == pytest.approx(
        source.mean()
    )
    assert (
        row["incremental_response_lower_interval"]
        < row["incremental_response_upper_interval"]
    )


def test_attribution_reconciliation_and_serialization(meta, tmp_path):
    draws = _generate(meta)
    matched = (
        draws.groupby(["market", "channel", "outcome_id", "posterior_draw"])[
            "channel_total_incremental_response"
        ]
        .first()
        .groupby(["market", "channel", "outcome_id"])
        .mean()
        .to_dict()
    )
    reconciled = reconcile_curve_to_attribution(draws, matched)
    assert np.isfinite(reconciled["curve_attribution_reconciliation_error"]).all()
    summary = summarize_curve_draws(reconciled)
    paths = export_canonical_curve_bank(reconciled, summary, tmp_path)
    pd.testing.assert_frame_equal(pd.read_parquet(paths[0]), reconciled)
    schema = json.loads(paths[2].read_text())
    assert schema["version"] == "G2A.2-1"
    assert "mu(selected_channel_media_input)" in schema["response_definition"]


def _governed_inputs_and_costs(cost_per_unit=2.0):
    specs = {
        (market, channel): MediaInputSpec(
            market=market,
            channel=channel,
            column=f"{channel.lower()}_impressions",
            unit="thousand_impressions",
            unit_scale=1000.0,
        )
        for market in MARKETS
        for channel in CHANNELS
    }
    costs = {
        (market, channel): FixedCostPerUnitMapping(
            mapping_id=f"{market}-{channel}-cost",
            market=market,
            channel=channel,
            currency="GBP" if market == "UK" else "AUD",
            cost_context_id="curve",
            cost_per_media_input=cost_per_unit,
            source="approved rate card",
            approval_status="approved",
            approved_by="finance",
        )
        for market in MARKETS
        for channel in CHANNELS
    }
    return specs, costs


def test_model_input_curve_is_available_without_cost_economics(meta):
    specs, _ = _governed_inputs_and_costs()
    draws = generate_canonical_curve_draws(
        model_run_id="input-only",
        meta=meta,
        trace=_trace(),
        reference_contexts=_contexts(),
        n_draws=2,
        spend_points=[0.0, 50.0],
        support_by_market_channel=_support(),
        curve_type="model_input",
        media_input_specs=specs,
    )
    assert draws["curve_type"].eq("model_input").all()
    assert draws["media_input_unit"].eq("thousand_impressions").all()
    assert draws["reporting_currency_spend"].isna().all()
    assert draws["current_spend"].isna().all()
    assert draws["current_media_input"].eq(50.0).all()
    channel = aggregate_curve_draws(
        draws,
        by=[
            "model_run_id", "reference_context_id", "market", "channel",
            "spend_point", "outcome_id",
        ],
    )
    assert channel["average_cpa"].isna().all()
    assert channel["average_economics_status"].eq(
        "cost_mapping_missing"
    ).all()


def test_monetary_curve_maps_spend_and_stores_chain_rule_derivatives(meta):
    specs, costs = _governed_inputs_and_costs(cost_per_unit=2.0)
    draws = _generate(
        meta,
        curve_type="monetary",
        media_input_specs=specs,
        cost_mappings=costs,
        cost_context_id="curve",
    )
    first = draws[(draws["market"] == "UK") & (draws["spend_point"] == 1)]
    assert first["media_input"].eq(25.0).all()
    assert first["local_spend"].eq(50.0).all()
    assert first[
        "marginal_media_input_per_local_currency_unit"
    ].eq(0.5).all()
    assert np.allclose(
        first["marginal_incremental_response_per_currency_unit"],
        first["marginal_incremental_response_per_media_input_unit"] * 0.5,
    )
    au = draws[(draws["market"] == "AU") & (draws["spend_point"] == 1)]
    assert np.allclose(
        au["marginal_incremental_response_per_currency_unit"],
        au["marginal_incremental_response_per_media_input_unit"],
    )


def test_monetary_curve_is_blocked_without_approved_mapping(meta):
    specs, _ = _governed_inputs_and_costs()
    with pytest.raises(ValueError, match="blocked"):
        _generate(
            meta,
            curve_type="monetary",
            media_input_specs=specs,
            cost_context_id="curve",
        )


def test_direct_and_halo_governance_views_are_response_only(meta):
    views = canonical_governance_views(_generate(meta))
    for name in ("direct", "halo"):
        assert views[name]["average_cpa"].isna().all()
        assert views[name]["economics_scope"].eq(
            "decomposition_response_only"
        ).all()
