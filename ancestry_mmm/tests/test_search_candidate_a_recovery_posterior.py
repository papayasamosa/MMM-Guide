"""WP2 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`): real
`pm.sample` NUTS posterior-recovery evidence against the *integrated*
Candidate A production model
(`core.hierarchical_model.build_fh_hierarchical_model(...,
search_candidate_a=...)`), fit to the independent synthetic generator in
`core.search_candidate_a_recovery`.

Separated from `test_search_candidate_a_recovery.py` (fast checks only) so
this file can be excluded from the ordinary Python 3.11/3.12 test jobs and
run instead by the dedicated `candidate-a-recovery` schedule/manual-only
CI job - the same pattern `test_simulation_recovery.py`'s module docstring
describes and the `deterministic-recovery` job already uses for the
ordinary (non-Search) model's MCMC cost. Kept to modest draws/tune/chains
for tractability; still meaningfully slower than the rest of the suite.

Evidence, not an official-use approval: these tests supply one input
(`noisy_recovery_passed`) to `core.search_capacity.candidate_a_use_gate`'s
required evidence set. Passing here does not itself grant official Search
fit eligibility, planning eligibility, or optimisation eligibility - see
`core.search_candidate_a_recovery.CANDIDATE_A_RECOVERY_POLICY` for the
scope and review-owner this evidence is bound to.
"""

import numpy as np
import pytest

from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.search_candidate_a_recovery import (
    CAP_REGIME_SOMETIMES_BINDS,
    default_recovery_scenarios,
    generate_candidate_a_synthetic_data,
)


def _model_spec(channels):
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["MKT0"],
        segment_outcomes={"New": "synthetic_outcome"},
        channels=list(channels),
    )


def _fit(data, *, draws=250, tune=250, chains=2, seed=0):
    model, meta = build_fh_hierarchical_model(
        data.frame,
        _model_spec(data.frame["channels"]),
        causal_graph=data.graph,
        search_candidate_a=data.fit_inputs,
    )
    trace = fit_model(
        model,
        draws=draws,
        tune=tune,
        chains=chains,
        target_accept=0.9,
        cores=1,
        random_seed=seed,
    )
    return trace, meta


class TestPosteriorReconciliation:
    def test_reconciliation_holds_in_every_posterior_draw(self):
        """Not a point-recovery check: the structural invariant
        (captured + unmet = latent) must hold for every posterior draw,
        not just the prior."""
        scenario = next(
            s
            for s in default_recovery_scenarios()
            if s.name == "mixed_channels_sometimes_binds"
        )
        data = generate_candidate_a_synthetic_data(scenario)
        trace, _meta = _fit(data, draws=150, tune=150, chains=2)
        post = trace.posterior
        demand = post["search_latent_branded_demand"].values
        captured = post["search_total_captured_demand"].values
        unmet = post["search_unmet_demand"].values
        np.testing.assert_allclose(captured + unmet, demand, rtol=1e-4, atol=1e-4)
        assert np.all(unmet >= -1e-6)

    def test_non_binding_cap_scenario_recovers_near_zero_cap_binding_probability(self):
        """AGENTS.md invariant, at the posterior level: a cap set far above
        true opportunity must not manufacture binding probability."""
        scenario = next(
            s
            for s in default_recovery_scenarios()
            if s.name == "mixed_channels_never_binds"
        )
        data = generate_candidate_a_synthetic_data(scenario)
        trace, _meta = _fit(data, draws=150, tune=150, chains=2)
        binding_prob = trace.posterior["search_cap_binding_probability"].values
        assert float(np.mean(binding_prob)) < 0.1


class TestIntervalCoverageRecovery:
    """Interval-coverage evidence, not point recovery (brief WP2: "do not
    require exact point recovery for weakly identified parameters - instead
    define evidence grades"). A single scenario's pass/fail is not itself
    an official-use claim; see
    `CANDIDATE_A_RECOVERY_POLICY.min_interval_coverage` for the aggregate
    bar this feeds."""

    @pytest.mark.parametrize(
        "scenario",
        [
            s
            for s in default_recovery_scenarios()
            if s.cap_regime == CAP_REGIME_SOMETIMES_BINDS
        ],
        ids=lambda s: s.name,
    )
    def test_paid_capture_outcome_beta_credible_interval_covers_truth(self, scenario):
        data = generate_candidate_a_synthetic_data(scenario)
        trace, _meta = _fit(data, draws=250, tune=250, chains=2)
        draws = trace.posterior["search_paid_capture_outcome_beta"].values.reshape(-1)
        lo, hi = np.quantile(draws, [0.05, 0.95])
        truth = data.ground_truth["search_paid_capture_outcome_beta"]
        assert lo - 0.5 <= truth <= hi + 0.5, (
            f"90% interval [{lo:.3f}, {hi:.3f}] misses truth {truth:.3f} by "
            "more than the 0.5 slack band"
        )

    def test_demand_media_beta_credible_interval_covers_truth_for_the_mediated_only_channel(
        self,
    ):
        scenario = next(
            s
            for s in default_recovery_scenarios()
            if s.name == "mixed_channels_sometimes_binds"
        )
        data = generate_candidate_a_synthetic_data(scenario)
        trace, _meta = _fit(data, draws=250, tune=250, chains=2)
        demand_channels = list(trace.posterior["search_demand_channel"].values)
        idx = demand_channels.index("SearchBrand")
        draws = trace.posterior["search_demand_media_beta"].values[..., idx].reshape(-1)
        lo, hi = np.quantile(draws, [0.05, 0.95])
        truth = data.ground_truth["demand_beta[SearchBrand]"]
        assert lo - 0.5 <= truth <= hi + 0.5, (
            f"90% interval [{lo:.3f}, {hi:.3f}] misses truth {truth:.3f} by "
            "more than the 0.5 slack band"
        )
