"""Contracts for reusable pre-fit support and prior-predictive evidence."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.persistence import export_project, import_project
from ancestry_mmm.core.prefit_identifiability import (
    PriorPredictiveThresholdPolicy,
    SupportThresholdPolicy,
    build_prefit_fingerprints,
    build_prefit_identifiability_report,
    classify_short_sampler_screen,
    compute_channel_support_diagnostics,
    prefit_diagnostic_freshness,
    prior_predictive_plausibility,
)
from ancestry_mmm.core.prefit_identifiability import (
    _channel_support_status,
    _grouped_adstock,
)
from ancestry_mmm.core.prefit_screening import (
    build_leakage_safe_folds,
    build_prefit_screening_report,
    record_prefit_analyst_review,
)


def _data(values: dict[str, list[float]], *, n: int | None = None) -> pd.DataFrame:
    length = n or len(next(iter(values.values())))
    frame = {
        "date": pd.date_range("2023-01-01", periods=length, freq="7D"),
        "market": ["UK"] * length,
    }
    frame.update(values)
    return pd.DataFrame(frame)


def _config() -> dict[str, object]:
    return {
        "media_input_scale_method": "none",
        "decay_mu": 0.5,
        "decay_sigma": 0.2,
        "K_scale": 1.0,
        "K_alpha": 3.0,
        "S_alpha": 4.0,
        "S_beta": 4.0,
    }


@pytest.mark.parametrize(
    ("values", "expected_status", "expected_review"),
    [
        ([0.0] * 12, "very_weak", "blocked"),
        ([0.0, 10.0] + [0.0] * 10, "very_weak", "review_recommended"),
        ([0.0, 10.0, 20.0, 30.0] + [0.0] * 8, "very_weak", "review_recommended"),
        ([5.0] * 12, "very_weak", "review_recommended"),
    ],
)
def test_sparse_one_active_and_constant_support_are_diagnostic_only(
    values, expected_status, expected_review
):
    result = compute_channel_support_diagnostics(
        _data({"TV": values}),
        ["TV"],
        date_col="date",
        market_col="market",
        target_start="2023-01-01",
        target_end="2023-03-19",
        transform_config=_config(),
    )
    row = result["rows"][0]
    assert row["support_status"] == expected_status
    assert row["review_recommendation"]["review_status"] == expected_review
    assert row["review_recommendation"]["diagnostic_only"] is True
    assert result["classification_is_diagnostic_only"] is True


def test_continuous_and_mid_window_support_preserve_target_window_and_history():
    data = _data(
        {
            "TV": [100.0, 110.0, 90.0, 120.0, 115.0, 130.0, 125.0, 140.0],
            "OOH": [0.0, 0.0, 50.0, 50.0, 50.0, 0.0, 0.0, 0.0],
        }
    )
    result = compute_channel_support_diagnostics(
        data,
        ["TV", "OOH"],
        date_col="date",
        market_col="market",
        target_start="2023-01-15",
        target_end="2023-02-19",
        transform_config=_config(),
        units={"TV": "GRPs", "OOH": "impressions"},
    )
    assert result["target_window"]["target_weeks"] == 6
    assert result["target_window"]["history_rows_retained_for_adstock"] == 2
    tv, ooh = result["rows"]
    assert tv["target_weeks"] == 6
    assert tv["model_input_unit"] == "GRPs"
    assert ooh["positive_weeks"] == 3
    assert ooh["longest_zero_run"] == 3
    assert tv["current_transform_priors"]["decay_rate"]["reference"] == 0.5
    assert tv["response_domain_adstock_over_K"]["q50"] is not None


def test_support_classification_covers_continuous_channel_without_a_fixed_window():
    values = [float(10 + (index % 23) * 3) for index in range(72)]
    result = compute_channel_support_diagnostics(
        _data({"TV": values}, n=72),
        ["TV"],
        date_col="date",
        market_col="market",
        target_start="2023-01-01",
        target_end="2024-05-19",
        units={"TV": "GRPs"},
        transform_config=_config(),
    )
    row = result["rows"][0]
    assert row["target_weeks"] == 72
    assert row["support_status"] == "strong"
    assert "Strong support" in row["review_recommendation"]["interpretation"]
    assert row["current_transform_priors"]["hill_K"]["beta"] > 0


def test_market_grouped_adstock_does_not_carry_one_market_into_another():
    data = pd.DataFrame(
        {
            "date": list(pd.date_range("2023-01-01", periods=4, freq="7D")) * 2,
            "market": ["UK"] * 4 + ["IE"] * 4,
            "TV": [100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
    )
    effective = _grouped_adstock(
        data[["TV"]].to_numpy(),
        data,
        np.array([0.8]),
        market_col="market",
    )
    # IE has no activity and must not inherit UK's carry-in value.
    assert np.allclose(effective[4:, 0], 0.0)


def test_missing_values_are_not_zero_filled():
    data = _data({"TV": [1.0, np.nan, 2.0]})
    with pytest.raises(ValueError, match="finite"):
        compute_channel_support_diagnostics(data, ["TV"])


def test_support_diagnostic_does_not_mutate_arbitrary_input_data():
    data = _data({"TV": [1.0, 2.0, 3.0]})
    before = data.copy(deep=True)
    compute_channel_support_diagnostics(
        data,
        ["TV"],
        date_col="date",
        market_col="market",
        transform_config=_config(),
    )
    pd.testing.assert_frame_equal(data, before)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {
                "positive_weeks": 60,
                "distinct_positive_values": 20,
                "effective_adstock_cv": 0.25,
            },
            "strong",
        ),
        (
            {
                "positive_weeks": 30,
                "distinct_positive_values": 10,
                "effective_adstock_cv": 0.10,
            },
            "moderate",
        ),
        (
            {
                "positive_weeks": 10,
                "distinct_positive_values": 4,
                "effective_adstock_cv": 0.0,
            },
            "weak",
        ),
    ],
)
def test_support_threshold_boundaries_are_versioned_and_interpretable(row, expected):
    policy = SupportThresholdPolicy()
    assert _channel_support_status(row, policy) == expected
    assert policy.version == "support-diagnostic-v1"


def test_no_posterior_evidence_is_explicit_and_does_not_change_support():
    result = compute_channel_support_diagnostics(
        _data({"TV": [1.0, 2.0, 3.0]}),
        ["TV"],
        transform_config=_config(),
    )
    row = result["rows"][0]
    assert row["posterior_evidence"]["status"] == "unavailable"
    assert row["recovery_evidence"]["status"] == "unavailable"


def test_prior_predictive_finite_without_policy_is_reviewable():
    result = prior_predictive_plausibility(
        np.arange(20.0).reshape(5, 4),
        np.array([2.0, 3.0, 4.0, 5.0]),
    )
    assert result["status"] == "computed"
    assert result["threshold_policy_status"] == "not_approved"
    assert result["rows"][0]["status"] == "wide_but_reviewable"
    assert result["rows"][0]["review_status"] == "review_recommended"
    row = result["rows"][0]
    assert row["predictive_quantiles"]["max"] == 19.0
    assert row["observed_quantiles"]["mean"] == 3.5
    assert "q95_to_observed_median" in row["observed_scale_ratios"]
    assert "q99_to_observed_max" in row["observed_scale_ratios"]


def test_prior_predictive_nonfinite_is_blocked():
    result = prior_predictive_plausibility(
        np.array([[1.0, np.nan], [2.0, 3.0]]),
        np.array([1.0, 2.0]),
    )
    assert result["status"] == "numerically_invalid"
    assert result["review_status"] == "blocked"
    assert result["rows"][0]["status"] == "numerically_invalid"


def test_prior_predictive_invalid_likelihood_evidence_is_explicitly_blocked():
    result = prior_predictive_plausibility(
        np.ones((3, 4)),
        validity_evidence={
            "invalid_likelihood_values": True,
            "warnings": ["synthetic invalid likelihood warning"],
        },
    )
    assert result["status"] == "numerically_invalid"
    assert result["layer_a_evidence"]["invalid_likelihood_values"] is True
    assert result["layer_a_evidence"]["warnings"]


def test_prior_predictive_without_observed_values_remains_reviewable():
    result = prior_predictive_plausibility(np.ones((4, 3)))
    assert result["rows"][0]["observed_quantiles"] is None
    assert result["rows"][0]["status"] == "wide_but_reviewable"


def test_prior_predictive_policy_distinguishes_plausible_wide_and_extreme():
    policy = PriorPredictiveThresholdPolicy(version="test-v1")
    observed = np.arange(1.0, 21.0)
    plausible = prior_predictive_plausibility(
        np.tile(observed, (4, 1)),
        observed,
        threshold_policy=policy,
    )
    wide = prior_predictive_plausibility(
        np.tile(observed * 20.0, (4, 1)),
        observed,
        threshold_policy=policy,
    )
    extreme = prior_predictive_plausibility(
        np.tile(observed * 200.0, (4, 1)),
        observed,
        threshold_policy=policy,
    )
    assert plausible["rows"][0]["status"] == "plausible"
    assert wide["rows"][0]["status"] == "wide_but_reviewable"
    assert extreme["rows"][0]["status"] == "implausibly_extreme"


def test_prior_predictive_multi_outcome_and_component_decomposition():
    result = prior_predictive_plausibility(
        {
            "New": np.ones((10, 4)),
            "Winback": np.ones((10, 4)) * 2,
        },
        {"New": np.ones(4), "Winback": np.ones(4) * 2},
        component_draws={"intercept": np.ones(10), "media": np.ones(10) * 2},
    )
    assert [row["outcome_id"] for row in result["rows"]] == ["New", "Winback"]
    assert result["component_decomposition"]["status"] == "available"
    assert "media" in result["component_decomposition"]["components"]


def test_fingerprints_and_staleness_cover_every_prefit_identity_dimension():
    data = _data({"TV": [1.0, 2.0, 3.0]})
    kwargs = dict(
        channels=["TV"],
        date_col="date",
        market_col="market",
        target_start="2023-01-01",
        target_end="2023-01-15",
        transform_config=_config(),
    )
    fingerprints = build_prefit_fingerprints(data, **kwargs)
    report = build_prefit_identifiability_report(
        data,
        ["TV"],
        product="Family History",
        model_name="Model A",
        **{key: value for key, value in kwargs.items() if key != "channels"},
    )
    assert prefit_diagnostic_freshness(report, fingerprints)["status"] == "current"
    for key in fingerprints:
        changed = dict(fingerprints)
        changed[key] = "changed"
        freshness = prefit_diagnostic_freshness(report, changed)
        assert freshness["status"] == "stale"
        assert key in freshness["mismatches"]


def test_optional_candidate_prepared_and_causal_fingerprints_are_freshness_bound():
    data = _data({"TV": [1.0, 2.0, 3.0]})
    fingerprints = build_prefit_fingerprints(
        data,
        channels=["TV"],
        date_col="date",
        market_col="market",
        target_start=None,
        target_end=None,
        transform_config=_config(),
        candidate_spec={"channels": ["TV"]},
        prepared_frame={"shape": [3, 1]},
        causal_graph={"version": "g1"},
    )
    assert {
        "candidate_spec_fingerprint",
        "prepared_frame_fingerprint",
        "causal_graph_fingerprint",
    } <= fingerprints.keys()
    report = {"fingerprints": fingerprints}
    changed = dict(fingerprints)
    changed["causal_graph_fingerprint"] = "changed"
    assert prefit_diagnostic_freshness(report, changed)["status"] == "stale"
    complete_report = build_prefit_identifiability_report(
        data,
        ["TV"],
        product="Family History",
        model_name="Model A",
        date_col="date",
        market_col="market",
        transform_config=_config(),
        candidate_spec={"channels": ["TV"]},
        prepared_frame={"shape": [3, 1]},
        causal_graph={"version": "g1"},
    )
    assert set(fingerprints) <= set(complete_report["fingerprints"])


def test_prefit_report_keeps_state_semantics_separate():
    report = build_prefit_identifiability_report(
        _data({"TV": [1.0, 2.0, 3.0]}),
        ["TV"],
        product="Family History",
        model_name="Model A",
        date_col="date",
        market_col="market",
        transform_config=_config(),
    )
    assert report["state_semantics"] == {
        "static_readiness": "computed",
        "support_identifiability": "review_recommended",
        "prior_predictive": "not_run",
        "short_sampler_screen": "not_run",
        "production_convergence": "not_assessed",
        "postfit_validation": "not_run",
        "reporting_eligibility": "not_eligible",
    }
    assert report["model_mutation_applied"] is False


def test_short_sampler_zero_divergence_is_not_convergence():
    result = classify_short_sampler_screen(
        divergences=0,
        rhat_max=1.02,
        ess_min=20.0,
        bfmi_min=0.9,
        chains=2,
        tune=150,
        draws=100,
    )
    assert result["divergence_smoke_test"] == "passed"
    assert result["mixing_status"] == "inconclusive"
    assert result["production_convergence_assessed"] is False
    assert result["production_candidate"] is False
    assert "production convergence was not assessed" in result["interpretation"]


def test_short_sampler_divergence_failure_is_still_diagnostic_only():
    result = classify_short_sampler_screen(
        divergences=2,
        rhat_max=1.4,
        ess_min=3.0,
        bfmi_min=0.1,
        chains=1,
        tune=20,
        draws=20,
    )
    assert result["divergence_smoke_test"] == "failed"
    assert result["production_convergence_assessed"] is False
    assert result["diagnostic_only"] is True


def _screen_frame(n_obs: int = 30):
    dates = pd.date_range("2023-01-01", periods=n_obs, freq="7D")
    index = np.arange(n_obs, dtype=float)
    return {
        "dates": dates,
        "markets": np.array(["UK"] * n_obs),
        "X_media": np.column_stack([10 + index % 9, 5 + (index * 2) % 11]),
        "Y": np.column_stack([20 + index * 0.2, 8 + (index % 5)]),
        "channels": ["TV", "Paid Search"],
        "outcome_ids": ["New", "Winback"],
        "trend": index,
        "fourier": np.column_stack([np.sin(index / 3), np.cos(index / 4)]),
        "X_controls": np.zeros((n_obs, 0)),
    }


def _multi_market_screen_frame(n_per_market: int = 20):
    """The real governed frame contract (data.preprocessor.
    prepare_fh_modeling_frame): `markets` is the short list of *distinct*
    market names, and `market_idx` is the separate per-row integer group
    key - never a per-row array of market names itself. A real multi-week,
    multi-market frame is the case that surfaced this: `frame["markets"]`
    (2 elements) fed directly into row-indexed grouping raised
    `ValueError: frame['markets'] must have one value per row` the moment
    n_obs != len(markets)."""
    n_obs = n_per_market * 2
    dates = pd.date_range("2023-01-01", periods=n_per_market, freq="7D")
    index = np.arange(n_per_market, dtype=float)
    return {
        "dates": np.concatenate([dates.to_numpy(), dates.to_numpy()]),
        "markets": ["UK", "IE"],
        "market_idx": np.concatenate(
            [np.zeros(n_per_market, dtype=int), np.ones(n_per_market, dtype=int)]
        ),
        "market_bounds": [(0, n_per_market), (n_per_market, n_obs)],
        "X_media": np.tile(
            np.column_stack([10 + index % 9, 5 + (index * 2) % 11]), (2, 1)
        ),
        "Y": np.tile(np.column_stack([20 + index * 0.2, 8 + (index % 5)]), (2, 1)),
        "channels": ["TV", "Paid Search"],
        "outcome_ids": ["New", "Winback"],
        "trend": np.tile(index, 2),
        "fourier": np.tile(
            np.column_stack([np.sin(index / 3), np.cos(index / 4)]), (2, 1)
        ),
        "X_controls": np.zeros((n_obs, 0)),
    }


def test_deterministic_screen_handles_the_real_multi_market_frame_contract():
    result = build_prefit_screening_report(
        _multi_market_screen_frame(), n_folds=2, min_train_periods=10
    )
    assert result["status"] == "computed"
    assert result["diagnostic_only"] is True


def test_deterministic_screen_records_folds_surrogates_stability_and_safeguards():
    folds = build_leakage_safe_folds(
        _screen_frame()["dates"], n_folds=2, min_train_periods=8
    )
    assert len(folds) == 2
    assert all(fold["leakage_safe"] for fold in folds)
    assert all(fold["train_end"] < fold["test_start"] for fold in folds)
    result = build_prefit_screening_report(
        _screen_frame(),
        n_folds=2,
        min_train_periods=8,
        transform_config={
            "prefit_decay_grid": (0.0, 0.5),
            "prefit_hill_s_grid": (1.0,),
        },
        fingerprints={"candidate_spec_fingerprint": "candidate"},
    )
    assert result["status"] == "computed"
    assert result["review_status"] == "review_recommended"
    assert {row["surrogate"] for row in result["surrogate_results"]} == {
        "ridge",
        "elastic_net",
    }
    assert all(
        "baseline_context_only" in row and "baseline_context_plus_media" in row
        for row in result["surrogate_results"]
    )
    assert result["channel_stability"]
    assert result["transform_stability"]
    assert result["timing_refutation"]["future_to_past_is_not_a_production_predictor"]
    assert result["same_sample_prior_safeguards"]["transform_fit_on_training_rows_only"]
    assert result["official_eligibility"] is False
    assert result["model_mutation_applied"] is False
    assert result["analyst_review"]["rationale"] is None
    # REQ-PREFIT-001 (Work Package 1 correction): the review vocabulary is
    # exactly ready/review_recommended/blocked (result["review_status"],
    # asserted above) - there is no separate `submission_gate` vocabulary.
    # "Can this run support official submission" is answered by
    # core.prefit_run.official_submission_allowed on the consolidated
    # PrefitRun, not by a second field on this report alone.
    assert "submission_gate" not in result
    assert result["reconstruction_tier"] == "prepared_frame_only"


def test_analyst_rationale_is_retained_without_granting_official_eligibility():
    report = build_prefit_screening_report(
        _screen_frame(), n_folds=2, min_train_periods=8
    )
    with pytest.raises(ValueError, match="rationale is required"):
        record_prefit_analyst_review(report, " ")
    reviewed = record_prefit_analyst_review(
        report, "Retain current transforms for analyst sensitivity review."
    )
    assert reviewed["analyst_review"]["status"] == "retained"
    assert reviewed["analyst_review"]["rationale_retained"] is True
    # Retaining rationale satisfies REQ-PREFIT-001's precondition for
    # review_recommended evidence to support submission; it does not
    # change the evidence's own quality, so review_status is unchanged.
    assert reviewed["review_status"] == report["review_status"]
    assert reviewed["official_eligibility"] is False


def test_deterministic_screen_blocks_without_enough_ordered_history():
    result = build_prefit_screening_report(_screen_frame(6), min_train_periods=8)
    assert result["status"] == "blocked"
    assert result["diagnostic_only"] is True


def test_prefit_diagnostics_round_trip_in_generic_project_diagnostics(tmp_path):
    prior = prior_predictive_plausibility(
        np.ones((4, 3)),
        np.ones(3),
    )
    report = build_prefit_identifiability_report(
        _data({"TV": [1.0, 2.0, 3.0]}),
        ["TV"],
        product="Family History",
        model_name="Model A",
        date_col="date",
        market_col="market",
        transform_config=_config(),
        prior_predictive=prior,
    )
    bundle = export_project(
        tmp_path / "prefit.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config={},
        dna_lag_weeks=4,
        trace=None,
        scenarios=[],
        diagnostics={
            "prefit_identifiability": report,
            "prior_predictive": prior,
            "prefit_screening": {
                "status": "review_recommended",
                "diagnostic_only": True,
                "official_eligibility": False,
            },
        },
    )
    imported = import_project(bundle)
    assert imported["diagnostics"]["prefit_identifiability"] == report
    assert (
        imported["diagnostics"]["prefit_identifiability"]["prior_predictive"] == prior
    )
    assert imported["diagnostics"]["prefit_screening"]["official_eligibility"] is False
