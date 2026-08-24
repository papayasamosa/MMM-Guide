"""Contracts for reusable pre-fit support and prior-predictive evidence."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.persistence import export_project, import_project
from ancestry_mmm.core.prefit_identifiability import (
    PriorPredictiveThresholdPolicy,
    build_prefit_fingerprints,
    build_prefit_identifiability_report,
    classify_short_sampler_screen,
    compute_channel_support_diagnostics,
    prefit_diagnostic_freshness,
    prior_predictive_plausibility,
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


def test_missing_values_are_not_zero_filled():
    data = _data({"TV": [1.0, np.nan, 2.0]})
    with pytest.raises(ValueError, match="finite"):
        compute_channel_support_diagnostics(data, ["TV"])


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
        "support_identifiability": "computed",
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


def test_prefit_diagnostics_round_trip_in_generic_project_diagnostics(tmp_path):
    report = build_prefit_identifiability_report(
        _data({"TV": [1.0, 2.0, 3.0]}),
        ["TV"],
        product="Family History",
        model_name="Model A",
        date_col="date",
        market_col="market",
        transform_config=_config(),
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
        diagnostics={"prefit_identifiability": report},
    )
    imported = import_project(bundle)
    assert imported["diagnostics"]["prefit_identifiability"] == report
