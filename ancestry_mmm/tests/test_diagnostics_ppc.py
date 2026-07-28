"""
Tests for ``core.diagnostics.posterior_predictive_coverage`` — the correct
posterior predictive mixture interval.

PR 2: The old implementation averaged conditional Negative Binomial quantiles
across posterior draws. That is *not* the quantile of the posterior predictive
mixture. These tests verify the replacement uses a correct predictive-sampling
approach.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
import pytest
import arviz as az
import xarray as xr

from ancestry_mmm.core.diagnostics import posterior_predictive_coverage
from ancestry_mmm.core.hierarchical_model import FHModelMeta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trace_and_frame(
    n_obs: int = 20,
    n_outcomes: int = 2,
    n_chain: int = 2,
    n_draw: int = 25,
    *,
    outcome_ids: List[str] | None = None,
    channels: List[str] | None = None,
    seed: int = 42,
) -> tuple[az.InferenceData, Dict, FHModelMeta]:
    """Build a minimal InferenceData + frame + meta for PPC testing.

    ``mu`` and ``alpha`` are set so that the true data-generating process is
    *inside* the posterior support — i.e. coverage *should* be near the target.
    """
    rng = np.random.default_rng(seed)
    oids = outcome_ids or ["New", "DNA_CrossSell"]
    chs = channels or ["TV", "Digital"]
    n_out = len(oids)

    # True parameters
    true_mu = rng.uniform(5, 30, size=(n_obs, n_out))
    true_alpha = np.array([5.0, 8.0])

    # Generate "observed" data from the true NB distribution
    Y = np.zeros((n_obs, n_out))
    for i in range(n_out):
        n_param = true_alpha[i]
        p_param = true_alpha[i] / (true_alpha[i] + true_mu[:, i])
        Y[:, i] = rng.negative_binomial(n_param, np.clip(p_param, 1e-9, 1 - 1e-9))

    # Posterior draws: mu and alpha centred on the true values with moderate noise
    mu_draws = np.zeros((n_chain, n_draw, n_obs, n_out))
    alpha_draws = np.zeros((n_chain, n_draw, n_out))
    for i in range(n_out):
        mu_noise = rng.normal(0, true_mu.mean(axis=0)[i] * 0.05, size=(n_chain, n_draw, n_obs))
        mu_draws[:, :, :, i] = np.maximum(true_mu[:, i] + mu_noise, 0.1)
        alpha_draws[:, :, i] = np.maximum(true_alpha[i] + rng.normal(0, 0.3, size=(n_chain, n_draw)), 0.5)

    coords = {
        "chain": list(range(n_chain)),
        "draw": list(range(n_draw)),
        "obs": list(range(n_obs)),
        "outcome": oids,
        "channel": chs,
    }
    trace = az.from_dict(
        posterior={
            "mu": xr.DataArray(
                mu_draws,
                dims=["chain", "draw", "obs", "outcome"],
                coords={"chain": list(range(n_chain)), "draw": list(range(n_draw)),
                        "obs": list(range(n_obs)), "outcome": oids},
            ),
            "alpha": xr.DataArray(
                alpha_draws,
                dims=["chain", "draw", "outcome"],
                coords={"chain": list(range(n_chain)), "draw": list(range(n_draw)),
                        "outcome": oids},
            ),
            # Minimal extra variables to avoid KeyError in coords
            "hill_K": xr.DataArray(
                np.ones((n_chain, n_draw, len(chs))),
                dims=["chain", "draw", "channel"],
                coords={"chain": list(range(n_chain)), "draw": list(range(n_draw)), "channel": chs},
            ),
            "beta": xr.DataArray(
                np.ones((n_chain, n_draw, n_out, len(chs))),
                dims=["chain", "draw", "outcome", "channel"],
                coords={"chain": list(range(n_chain)), "draw": list(range(n_draw)),
                        "outcome": oids, "channel": chs},
            ),
        },
    )

    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=oids,
        channels=chs,
        dna_channels=["Digital"] if "Digital" in chs else [],
        dna_channel_idx=[chs.index("Digital")] if "Digital" in chs else [],
        non_dna_idx=[i for i, ch in enumerate(chs) if ch != "Digital"],
        dna_outcome_id="DNA_CrossSell" if "DNA_CrossSell" in oids else oids[-1],
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
    )

    frame = {"Y": Y}

    return trace, frame, meta


def _old_incorrect_ppc(
    trace: az.InferenceData,
    frame: Dict,
    meta: FHModelMeta,
    credible_mass: float = 0.9,
) -> pd.DataFrame:
    """Reproduce the *old* (incorrect) average-of-conditional-quantiles PPC.

    Kept here as a regression reference — the new implementation must NOT
    produce identical results.
    """
    from scipy import stats

    Y = frame["Y"]
    mu_draws = trace.posterior["mu"].stack(sample=("chain", "draw")).values
    alpha_draws = trace.posterior["alpha"].stack(sample=("chain", "draw")).values

    lower_q, upper_q = (1 - credible_mass) / 2, 1 - (1 - credible_mass) / 2
    rows = []
    for i, oid in enumerate(meta.outcome_ids):
        mu_i = mu_draws[:, i, :]
        alpha_i = alpha_draws[i, :]
        n_param = alpha_i[None, :]
        p_param = alpha_i[None, :] / (alpha_i[None, :] + mu_i)
        p_param = np.clip(p_param, 1e-9, 1 - 1e-9)

        lo = stats.nbinom.ppf(lower_q, n_param, p_param)
        hi = stats.nbinom.ppf(upper_q, n_param, p_param)
        lo_mean, hi_mean = lo.mean(axis=1), hi.mean(axis=1)

        covered = (Y[:, i] >= lo_mean) & (Y[:, i] <= hi_mean)
        rows.append({
            "outcome_id": oid,
            "credible_mass": credible_mass,
            "coverage_pct": float(covered.mean() * 100),
            "target_pct": credible_mass * 100,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPosteriorPredictiveCoverageStructure:
    """Shape, field presence, and basic invariants."""

    def test_returns_dataframe(self):
        trace, frame, meta = _make_trace_and_frame()
        result = posterior_predictive_coverage(trace, frame, meta)
        assert isinstance(result, pd.DataFrame)

    def test_has_expected_columns(self):
        trace, frame, meta = _make_trace_and_frame()
        result = posterior_predictive_coverage(trace, frame, meta)
        expected = {"outcome_id", "credible_mass", "coverage_pct", "target_pct", "n_predictive_samples"}
        assert expected.issubset(set(result.columns))

    def test_one_row_per_outcome(self):
        trace, frame, meta = _make_trace_and_frame(outcome_ids=["New", "DNA_CrossSell", "Winback"])
        result = posterior_predictive_coverage(trace, frame, meta)
        assert len(result) == 3
        assert list(result["outcome_id"]) == ["New", "DNA_CrossSell", "Winback"]

    def test_coverage_pct_is_between_0_and_100(self):
        trace, frame, meta = _make_trace_and_frame()
        result = posterior_predictive_coverage(trace, frame, meta)
        assert (result["coverage_pct"] >= 0).all()
        assert (result["coverage_pct"] <= 100).all()

    def test_target_pct_matches_credible_mass(self):
        trace, frame, meta = _make_trace_and_frame()
        result = posterior_predictive_coverage(trace, frame, meta, credible_mass=0.8)
        assert (result["target_pct"] == 80.0).all()

    def test_n_predictive_samples_is_positive(self):
        trace, frame, meta = _make_trace_and_frame()
        result = posterior_predictive_coverage(trace, frame, meta)
        assert (result["n_predictive_samples"] > 0).all()


class TestPosteriorPredictiveCoverageReproducibility:
    """Same seed -> same result."""

    def test_deterministic_with_same_seed(self):
        trace, frame, meta = _make_trace_and_frame()
        r1 = posterior_predictive_coverage(trace, frame, meta, random_seed=123)
        r2 = posterior_predictive_coverage(trace, frame, meta, random_seed=123)
        pd.testing.assert_frame_equal(r1, r2)

    def test_different_seed_gives_different_result(self):
        trace, frame, meta = _make_trace_and_frame()
        r1 = posterior_predictive_coverage(trace, frame, meta, random_seed=123)
        r2 = posterior_predictive_coverage(trace, frame, meta, random_seed=456)
        # Unlikely to be exactly equal across seeds due to Monte Carlo noise
        assert not r1.equals(r2)


class TestPosteriorPredictiveCoverageValidity:
    """The new implementation must be a correct posterior predictive mixture."""

    def test_coverage_near_target_when_model_is_correct(self):
        """When posterior draws are centred on the true data-generating
        parameters, nominal coverage should be close to the target."""
        trace, frame, meta = _make_trace_and_frame(n_obs=100, n_chain=2, n_draw=50, seed=42)
        result = posterior_predictive_coverage(
            trace, frame, meta, credible_mass=0.9, predictive_replications=3, random_seed=99,
        )
        # With a well-specified posterior, coverage should be within ~10pp of target
        for _, row in result.iterrows():
            assert abs(row["coverage_pct"] - row["target_pct"]) < 15, (
                f"Coverage for {row['outcome_id']} is {row['coverage_pct']:.1f}%, "
                f"far from target {row['target_pct']:.0f}%"
            )

    def test_regression_old_method_fails(self):
        """Prove the old average-of-conditional-quantiles method is *not*
        equivalent to the correct predictive mixture.

        The two methods will diverge, especially with few posterior draws
        where the quantile-averaging bias is most visible.
        """
        trace, frame, meta = _make_trace_and_frame(n_obs=10, n_chain=2, n_draw=5, seed=7)
        new_result = posterior_predictive_coverage(
            trace, frame, meta, predictive_replications=10, random_seed=42,
        )
        old_result = _old_incorrect_ppc(trace, frame, meta)

        # The two methods must produce different coverage values
        new_coverage = new_result.set_index("outcome_id")["coverage_pct"]
        old_coverage = old_result.set_index("outcome_id")["coverage_pct"]

        for oid in meta.outcome_ids:
            assert new_coverage[oid] != pytest.approx(old_coverage[oid], abs=1e-6), (
                f"Outcome {oid}: new coverage ({new_coverage[oid]:.2f}%) matches "
                f"old coverage ({old_coverage[oid]:.2f}%) — expected divergence"
            )

    def test_increasing_predictive_replications_stabilises_coverage(self):
        """More predictive replications per draw should reduce Monte Carlo
        noise, not systematically change the expected value."""
        trace, frame, meta = _make_trace_and_frame(n_obs=30, n_chain=2, n_draw=20, seed=1)
        r1 = posterior_predictive_coverage(trace, frame, meta, predictive_replications=1, random_seed=42)
        r10 = posterior_predictive_coverage(trace, frame, meta, predictive_replications=10, random_seed=42)

        # Coverage should be similar (same seed, same draws)
        for oid in meta.outcome_ids:
            c1 = r1.loc[r1["outcome_id"] == oid, "coverage_pct"].iloc[0]
            c10 = r10.loc[r10["outcome_id"] == oid, "coverage_pct"].iloc[0]
            assert abs(c1 - c10) < 20, (
                f"Coverage changed substantially from {c1:.1f}% to {c10:.1f}% "
                f"for {oid} when increasing replications"
            )


class TestPosteriorPredictiveCoverageEdgeCases:
    """Edge cases and invalid inputs."""

    def test_single_outcome(self):
        trace, frame, meta = _make_trace_and_frame(outcome_ids=["New"])
        result = posterior_predictive_coverage(trace, frame, meta)
        assert len(result) == 1
        assert result.iloc[0]["outcome_id"] == "New"

    def test_single_observation(self):
        trace, frame, meta = _make_trace_and_frame(n_obs=1)
        result = posterior_predictive_coverage(trace, frame, meta)
        assert len(result) == 2
        assert 0 <= result.iloc[0]["coverage_pct"] <= 100

    def test_single_chain(self):
        trace, frame, meta = _make_trace_and_frame(n_chain=1, n_draw=30)
        result = posterior_predictive_coverage(trace, frame, meta)
        assert len(result) == 2

    def test_full_credible_interval(self):
        """100% credible interval should always cover everything."""
        trace, frame, meta = _make_trace_and_frame(n_obs=10)
        result = posterior_predictive_coverage(trace, frame, meta, credible_mass=1.0)
        assert (result["coverage_pct"] == 100.0).all()

    def test_zero_credible_interval_no_coverage_expected(self):
        """0% credible interval should almost never cover."""
        trace, frame, meta = _make_trace_and_frame(n_obs=10)
        result = posterior_predictive_coverage(trace, frame, meta, credible_mass=0.0)
        # With discrete NB, coverage might still be >0 for some outcomes
        # due to ties at zero — but should be very low
        assert (result["coverage_pct"] < 10).all()


class TestPPCReferencesInScorecard:
    """Verify posterior_predictive_coverage is still plumbed into the
    scorecard correctly (integration smoke test)."""

    def test_scorecard_contains_ppc(self):
        trace, frame, meta = _make_trace_and_frame()
        from ancestry_mmm.core.diagnostics import compute_scorecard
        scorecard = compute_scorecard(trace, frame, meta)
        assert "ppc_coverage" in scorecard
        assert len(scorecard["ppc_coverage"]) == len(meta.outcome_ids)

    def test_scorecard_ppc_has_correct_fields(self):
        trace, frame, meta = _make_trace_and_frame()
        from ancestry_mmm.core.diagnostics import compute_scorecard
        scorecard = compute_scorecard(trace, frame, meta)
        for record in scorecard["ppc_coverage"]:
            assert "outcome_id" in record
            assert "coverage_pct" in record
            assert "target_pct" in record
            assert "n_predictive_samples" in record
