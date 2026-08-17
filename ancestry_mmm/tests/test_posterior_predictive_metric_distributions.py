"""REQ-PPD-001 (Work Package 2): tests for posterior_predictive_metric_
distributions (Model A) and its Model C counterpart."""

from __future__ import annotations

import arviz as az
import numpy as np
import pytest

from ancestry_mmm.core.diagnostics import (
    error_metrics_by_outcome,
    posterior_predictive_metric_distributions,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_diagnostics import (
    error_metrics_by_outcome_market_specific,
    posterior_predictive_metric_distributions_market_specific,
)
from ancestry_mmm.core.market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    predict_mu_market_specific,
)
from ancestry_mmm.core.pathways import resolve_pathway_masks
from ancestry_mmm.core.predict import extract_posterior_params, predict_mu


def _trace_frame_meta_params(*, n_obs=16, n_chain=2, n_draw=20, noise_sd=0.5, seed=11):
    """A minimal, single-outcome, single-channel real trace/frame/meta
    triple, mirroring `test_diagnostics_artefact.py`'s
    `_minimal_trace_frame_meta` fixture (kept local rather than imported,
    matching this repository's per-file fixture convention).

    Unlike that fixture (whose fabricated `mu` posterior is unrelated to
    `predict_mu(frame, meta, params)`'s own recomputation from the other
    posterior variables - fine for exercising unrelated plumbing, but
    wrong for a test that needs the two to agree), this fixture sets the
    fabricated `mu` draws to `predict_mu`'s own deterministic output plus
    noise, so a `noise_sd=0.0` fixture genuinely collapses the per-draw
    metric distribution onto the point value.
    """
    rng = np.random.default_rng(seed)
    oids = ["fh_new_gsa"]
    chs = ["TV"]

    Y = rng.uniform(5, 30, size=(n_obs, 1))
    frame = {
        "Y": Y,
        "X_media": rng.uniform(0, 100, size=(n_obs, 1)),
        "markets": ["UK"],
        "market_bounds": [(0, n_obs)],
        "market_idx": np.zeros(n_obs, dtype=int),
        "promo": np.zeros((n_obs, 1)),
        "trend": np.arange(n_obs, dtype=float),
        "fourier": np.zeros((n_obs, 4)),
    }
    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=oids,
        channels=chs,
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id=oids[0],
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
        pathway_masks=resolve_pathway_masks(
            oids,
            chs,
            [],
            dna_channel_idx=[],
            dna_outcome_id=oids[0],
            direct_dna_outcome_ids=[],
            dna_lag_weeks=1,
        ),
    )

    def _posterior_dict(mu_values):
        return {
            "mu": mu_values,
            "alpha": np.full((n_chain, n_draw, 1), 8.0),
            "decay_rate": np.full((n_chain, n_draw, 1), 0.5),
            "hill_K": np.ones((n_chain, n_draw, 1)),
            "hill_S": np.full((n_chain, n_draw, 1), 4.0),
            "beta": np.ones((n_chain, n_draw, 1, 1)),
            "intercept": np.zeros((n_chain, n_draw, 1)),
            "trend_coef": np.zeros((n_chain, n_draw, 1)),
            "promo_coef": np.zeros((n_chain, n_draw, 1)),
            "market_offset": np.zeros((n_chain, n_draw, 1, 1)),
            "gamma_fourier": np.zeros((n_chain, n_draw, 4, 1)),
        }

    coords = {
        "obs": list(range(n_obs)),
        "outcome": oids,
        "channel": chs,
        "market": ["UK"],
        "fourier": list(range(4)),
    }
    dims = {
        "mu": ["obs", "outcome"],
        "alpha": ["outcome"],
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "beta": ["outcome", "channel"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "promo_coef": ["outcome"],
        "market_offset": ["market", "outcome"],
        "gamma_fourier": ["fourier", "outcome"],
    }
    sample_stats = {"diverging": np.zeros((n_chain, n_draw), dtype=bool)}

    # First pass: build a trace with a placeholder mu just to extract the
    # constant (non-mu) posterior variables into params, then compute
    # predict_mu's own deterministic output from those params.
    placeholder_trace = az.from_dict(
        posterior=_posterior_dict(np.zeros((n_chain, n_draw, n_obs, 1))),
        coords=coords,
        dims=dims,
        sample_stats=sample_stats,
    )
    params = extract_posterior_params(placeholder_trace, meta)
    deterministic_mu = predict_mu(frame, meta, params)  # (n_obs, 1)

    mu_values = np.maximum(
        deterministic_mu[None, None, :, 0]
        + rng.normal(0, noise_sd, size=(n_chain, n_draw, n_obs)),
        0.1,
    )[..., None]
    trace = az.from_dict(
        posterior=_posterior_dict(mu_values),
        coords=coords,
        dims=dims,
        sample_stats=sample_stats,
    )
    return trace, frame, meta, params


class TestPosteriorPredictiveMetricDistributions:
    def test_returns_one_row_per_outcome_with_expected_columns(self):
        trace, frame, meta, params = _trace_frame_meta_params()
        result = posterior_predictive_metric_distributions(trace, frame, meta, params)
        assert len(result) == len(meta.outcome_ids)
        for metric in ("mae", "rmse", "smape_pct", "wape_pct", "bias"):
            for suffix in ("point", "mean", "median", "lower", "upper"):
                assert f"{metric}_{suffix}" in result.columns
        assert "draw_count" in result.columns
        assert "credible_mass" in result.columns

    def test_draw_count_matches_chains_times_draws(self):
        trace, frame, meta, params = _trace_frame_meta_params(n_chain=3, n_draw=25)
        result = posterior_predictive_metric_distributions(trace, frame, meta, params)
        assert result.iloc[0]["draw_count"] == 3 * 25

    def test_point_value_matches_error_metrics_by_outcome_exactly(self):
        """The point column must reuse error_metrics_by_outcome's own
        value unchanged, never an independently recomputed approximation
        of it - the two must never silently diverge."""
        trace, frame, meta, params = _trace_frame_meta_params()
        result = posterior_predictive_metric_distributions(
            trace, frame, meta, params
        ).set_index("outcome_id")
        point_only = error_metrics_by_outcome(frame, meta, params).set_index(
            "outcome_id"
        )
        for oid in meta.outcome_ids:
            for metric in ("mae", "rmse", "smape_pct", "wape_pct", "bias"):
                assert result.loc[oid, f"{metric}_point"] == pytest.approx(
                    point_only.loc[oid, metric]
                )

    def test_distribution_mean_differs_from_point_for_nonlinear_metric_under_noise(
        self,
    ):
        """For a genuinely noisy posterior, RMSE's metric-of-the-mean and
        mean-of-the-metric must not be forced into equality - this is the
        substantive distinction REQ-PPD-001 exists to preserve, not an
        implementation detail that happens to coincide."""
        trace, frame, meta, params = _trace_frame_meta_params(
            noise_sd=3.0, n_chain=4, n_draw=200, seed=7
        )
        result = posterior_predictive_metric_distributions(
            trace, frame, meta, params
        ).iloc[0]
        assert result["rmse_point"] != pytest.approx(result["rmse_mean"], rel=1e-6)

    def test_credible_interval_bounds_the_distribution_mean(self):
        trace, frame, meta, params = _trace_frame_meta_params(
            noise_sd=2.0, n_chain=4, n_draw=200
        )
        result = posterior_predictive_metric_distributions(
            trace, frame, meta, params, credible_mass=0.9
        ).iloc[0]
        for metric in ("mae", "rmse", "wape_pct"):
            assert result[f"{metric}_lower"] <= result[f"{metric}_mean"]
            assert result[f"{metric}_mean"] <= result[f"{metric}_upper"]

    def test_zero_noise_draws_collapse_distribution_to_a_point(self):
        """With no posterior noise, every draw's mu is identical, so the
        per-draw metric distribution should have (numerically) zero
        spread and should equal the point value."""
        trace, frame, meta, params = _trace_frame_meta_params(noise_sd=0.0)
        result = posterior_predictive_metric_distributions(
            trace, frame, meta, params
        ).iloc[0]
        for metric in ("mae", "rmse", "wape_pct", "bias"):
            assert result[f"{metric}_mean"] == pytest.approx(
                result[f"{metric}_point"], abs=1e-9
            )
            assert result[f"{metric}_lower"] == pytest.approx(
                result[f"{metric}_upper"], abs=1e-9
            )

    def test_rejects_trace_without_mu(self):
        trace, frame, meta, params = _trace_frame_meta_params()
        stripped = az.from_dict(
            posterior={
                k: v.values if hasattr(v, "values") else v
                for k, v in trace.posterior.data_vars.items()
                if k != "mu"
            }
        )
        with pytest.raises(ValueError, match="no 'mu' variable"):
            posterior_predictive_metric_distributions(stripped, frame, meta, params)


def _market_specific_trace_frame_meta_params(
    *, n_obs=16, n_chain=2, n_draw=20, noise_sd=0.5, seed=13
):
    """A minimal, single-market, single-outcome, single-channel Model C
    fixture - hand-built `FHMarketSpecificPosteriorParams` (mirroring
    `test_market_specific_diagnostics.py`'s own fixture pattern), never
    extracted from a Model-A-shaped trace (`FHMarketSpecificPosteriorParams`
    needs market-indexed `hill_K`/`beta`, which a Model A trace's
    channel-only-indexed variables cannot supply)."""
    rng = np.random.default_rng(seed)
    oids = ["fh_new_gsa"]
    chs = ["TV"]
    markets = ["UK"]

    Y = rng.uniform(5, 30, size=(n_obs, 1))
    frame = {
        "Y": Y,
        "X_media": rng.uniform(0, 100, size=(n_obs, 1)),
        "markets": markets,
        "market_bounds": [(0, n_obs)],
        "market_idx": np.zeros(n_obs, dtype=int),
        "promo": np.zeros((n_obs, 1)),
        "trend": np.arange(n_obs, dtype=float),
        "fourier": np.zeros((n_obs, 4)),
        "control_names": [],
        "X_controls": np.zeros((n_obs, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }
    meta = FHModelMeta(
        markets=markets,
        outcome_ids=oids,
        channels=chs,
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id=oids[0],
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
        pathway_masks=resolve_pathway_masks(
            oids,
            chs,
            [],
            dna_channel_idx=[],
            dna_outcome_id=oids[0],
            direct_dna_outcome_ids=[],
            dna_lag_weeks=1,
        ),
    )
    params = FHMarketSpecificPosteriorParams(
        decay_rate={"TV": 0.5},
        hill_K={"UK": {"TV": 1.0}},
        hill_S={"TV": 4.0},
        beta={"UK": {"fh_new_gsa": {"TV": 1.0}}},
        pathway_strength={},
        promo_coef={"fh_new_gsa": 0.0},
        market_offset={"UK": {"fh_new_gsa": 0.0}},
        intercept={"fh_new_gsa": 0.0},
        trend_coef={"fh_new_gsa": 0.0},
        gamma_fourier={"fh_new_gsa": np.zeros(4)},
        alpha={"fh_new_gsa": 8.0},
        control_coef={},
        outcome_control_coef={},
    )
    deterministic_mu = predict_mu_market_specific(frame, meta, params)  # (n_obs, 1)

    mu_values = np.maximum(
        deterministic_mu[None, None, :, 0]
        + rng.normal(0, noise_sd, size=(n_chain, n_draw, n_obs)),
        0.1,
    )[..., None]
    trace = az.from_dict(
        posterior={"mu": mu_values},
        coords={"obs": list(range(n_obs)), "outcome": oids},
        dims={"mu": ["obs", "outcome"]},
        sample_stats={"diverging": np.zeros((n_chain, n_draw), dtype=bool)},
    )
    return trace, frame, meta, params


class TestPosteriorPredictiveMetricDistributionsMarketSpecific:
    def test_returns_one_row_per_outcome_with_expected_columns(self):
        trace, frame, meta, params = _market_specific_trace_frame_meta_params()
        result = posterior_predictive_metric_distributions_market_specific(
            trace, frame, meta, params
        )
        assert len(result) == len(meta.outcome_ids)
        for metric in ("mae", "rmse", "smape_pct", "wape_pct", "bias"):
            for suffix in ("point", "mean", "median", "lower", "upper"):
                assert f"{metric}_{suffix}" in result.columns

    def test_point_value_matches_market_specific_error_metrics_exactly(self):
        trace, frame, meta, params = _market_specific_trace_frame_meta_params()
        result = posterior_predictive_metric_distributions_market_specific(
            trace, frame, meta, params
        ).set_index("outcome_id")
        point_only = error_metrics_by_outcome_market_specific(
            frame, meta, params
        ).set_index("outcome_id")
        for oid in meta.outcome_ids:
            for metric in ("mae", "rmse", "smape_pct", "wape_pct", "bias"):
                assert result.loc[oid, f"{metric}_point"] == pytest.approx(
                    point_only.loc[oid, metric]
                )

    def test_zero_noise_draws_collapse_distribution_to_a_point(self):
        trace, frame, meta, params = _market_specific_trace_frame_meta_params(
            noise_sd=0.0
        )
        result = posterior_predictive_metric_distributions_market_specific(
            trace, frame, meta, params
        ).iloc[0]
        for metric in ("mae", "rmse", "wape_pct", "bias"):
            assert result[f"{metric}_mean"] == pytest.approx(
                result[f"{metric}_point"], abs=1e-9
            )
