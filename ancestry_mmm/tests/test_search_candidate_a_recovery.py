"""WP2 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`): Candidate A
synthetic generator and prior-predictive plausibility against the
*integrated* production model - fast checks only (`pm.draw`/
`pm.sample_prior_predictive`, no NUTS), run in ordinary CI.

The real `pm.sample` NUTS posterior-recovery evidence lives in the separate
`test_search_candidate_a_recovery_posterior.py`, matching this repository's
established convention for MCMC-cost tests (see `test_simulation_recovery.py`'s
module docstring and the `deterministic-recovery` GitHub Actions job,
`schedule`/`workflow_dispatch` only): that file is excluded from the
ordinary Python 3.11/3.12 test jobs and run instead by the dedicated
`candidate-a-recovery` schedule/manual-only job.
"""

import numpy as np
import pytest

from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.search_capacity import identify_candidate_a_search
from ancestry_mmm.core.search_candidate_a_recovery import (
    CAP_REGIME_FREQUENTLY_BINDS,
    CAP_REGIME_NEVER_BINDS,
    CAP_REGIME_SOMETIMES_BINDS,
    CandidateARecoveryScenario,
    CandidateARecoveryTruth,
    ChannelTruth,
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


class TestSyntheticGeneratorContract:
    """The generator's own structural invariants - independent of any PyMC
    fit. Reconciliation and cap-regime calibration must hold by
    construction for every scenario the recovery tests below will use."""

    @pytest.mark.parametrize(
        "scenario", default_recovery_scenarios(), ids=lambda s: s.name
    )
    def test_reconciliation_and_cap_regime_hold_for_every_default_scenario(
        self, scenario
    ):
        data = generate_candidate_a_synthetic_data(scenario)
        assert data.frame["X_media"].shape == (
            scenario.n_periods,
            len(scenario.channels),
        )
        assert data.ground_truth["mean_unmet_demand"] >= -1e-6
        binding_rate = data.ground_truth["cap_binding_rate"]
        if scenario.cap_regime == CAP_REGIME_NEVER_BINDS:
            assert binding_rate < 0.05
        elif scenario.cap_regime == CAP_REGIME_FREQUENTLY_BINDS:
            assert binding_rate > 0.5
        else:
            assert 0.05 <= binding_rate <= 0.9

    def test_non_binding_cap_scenario_never_caps_delivery_below_opportunity(self):
        """AGENTS.md invariant, at the data-generation level: a cap set far
        above true opportunity must not itself manufacture a shortfall."""
        scenario = CandidateARecoveryScenario(
            name="never_binds_check",
            channels=[
                ChannelTruth(
                    name="SearchBrand",
                    decay_rate=0.3,
                    hill_K=500.0,
                    hill_S=1.2,
                    demand_beta=0.4,
                )
            ],
            demand_channel_names=["SearchBrand"],
            cap_regime=CAP_REGIME_NEVER_BINDS,
            seed=3,
        )
        data = generate_candidate_a_synthetic_data(scenario)
        assert data.ground_truth["cap_binding_rate"] == pytest.approx(0.0, abs=1e-6)

    def test_rejects_capture_shares_that_would_make_unmet_demand_negative(self):
        truth = CandidateARecoveryTruth(
            capture_share_paid=0.6, capture_share_organic=0.5, capture_share_direct=0.1
        )
        scenario = CandidateARecoveryScenario(
            name="invalid_shares",
            channels=[
                ChannelTruth(
                    name="SearchBrand",
                    decay_rate=0.3,
                    hill_K=500.0,
                    hill_S=1.2,
                    demand_beta=0.4,
                )
            ],
            demand_channel_names=["SearchBrand"],
            truth=truth,
        )
        with pytest.raises(AssertionError):
            generate_candidate_a_synthetic_data(scenario)


class TestPriorPredictivePlausibility:
    """Fast: samples from the proposed model's priors (no NUTS) and checks
    outcome/demand/delivery ranges are not explosive - the AGENTS.md
    requirement that "prior defaults must not produce implausible
    explosive demand or outcome ranges" (brief WP2, "Prior predictive
    checks"), scoped to what's tractable without a real fit."""

    def test_prior_predictive_ranges_are_plausible_for_the_integrated_model(self):
        import pymc as pm

        scenario = CandidateARecoveryScenario(
            name="prior_predictive_check",
            channels=[
                ChannelTruth(
                    name="SearchBrand",
                    decay_rate=0.3,
                    hill_K=500.0,
                    hill_S=1.2,
                    demand_beta=0.4,
                ),
                ChannelTruth(
                    name="TV", decay_rate=0.5, hill_K=800.0, hill_S=1.4, direct_beta=0.1
                ),
            ],
            demand_channel_names=["SearchBrand", "TV"],
            n_periods=20,
        )
        data = generate_candidate_a_synthetic_data(scenario)
        model, _meta = build_fh_hierarchical_model(
            data.frame,
            _model_spec(data.frame["channels"]),
            causal_graph=data.graph,
            search_candidate_a=data.fit_inputs,
        )
        with model:
            prior = pm.sample_prior_predictive(draws=200, random_seed=0)
        mu = prior.prior["mu"].values
        demand = prior.prior["search_latent_branded_demand"].values
        assert np.all(np.isfinite(mu))
        assert np.all(np.isfinite(demand))
        # "Explosive" here means orders of magnitude beyond the synthetic
        # outcome's own scale (~tens to low hundreds) - a loose plausibility
        # band, not a tight prior-elicitation claim.
        outcome_scale = float(np.mean(data.frame["Y"]))
        assert np.median(mu) < max(outcome_scale, 1.0) * 1000
        assert (
            np.median(demand)
            < max(float(np.mean(data.fit_inputs.paid_search_cap)), 1.0) * 1000
        )


class TestIdentificationSensitivity:
    """Brief WP2's "identification sensitivity" requirement: vary cap
    variation, binding regime, and market-support length; document where
    Candidate A becomes weakly identified via
    `core.search_capacity.identify_candidate_a_search` (already the single
    fail-closed identification gate - this class does not invent a second
    one). Deliberately does not convert any one threshold crossing here
    into a universal causal-identification rule - see that function's own
    docstring on this point."""

    def _identify(self, scenario: CandidateARecoveryScenario):
        data = generate_candidate_a_synthetic_data(scenario)
        market_labels = [data.frame["markets"][m] for m in data.frame["market_idx"]]
        return identify_candidate_a_search(
            data.fit_inputs.paid_search_cap,
            data.fit_inputs.paid_search_delivery,
            market_labels=market_labels,
            cap_provenance=data.fit_inputs.spec.cap_provenance,
            cap_mapping_resolved=True,
            capture_mappings_resolved=True,
        )

    def _channel(self):
        return ChannelTruth(
            name="SearchBrand",
            decay_rate=0.3,
            hill_K=500.0,
            hill_S=1.2,
            demand_beta=0.4,
        )

    @pytest.mark.parametrize(
        "cap_variation,expect_variation_reason",
        [(0.0, True), (0.01, True), (0.35, False)],
    )
    def test_low_cap_variation_is_flagged_insufficient_for_identification(
        self, cap_variation, expect_variation_reason
    ):
        scenario = CandidateARecoveryScenario(
            name=f"cap_var_{cap_variation}",
            channels=[self._channel()],
            demand_channel_names=["SearchBrand"],
            cap_regime=CAP_REGIME_SOMETIMES_BINDS,
            cap_variation=cap_variation,
            n_periods=60,
            seed=1,
        )
        report = self._identify(scenario)
        has_variation_reason = any(
            "variation" in reason for reason in report.blocking_reasons
        )
        assert has_variation_reason is expect_variation_reason

    @pytest.mark.parametrize(
        "cap_regime,expected_missing_support",
        [
            (CAP_REGIME_NEVER_BINDS, "binding"),
            (CAP_REGIME_FREQUENTLY_BINDS, "non-binding"),
        ],
    )
    def test_extreme_cap_regimes_are_flagged_for_the_missing_support_side(
        self, cap_regime, expected_missing_support
    ):
        """A cap that (almost) never binds has no binding-period evidence;
        a cap that (almost) always binds has no non-binding-period
        evidence - Candidate A needs both to separate latent demand from
        the cap (AGENTS.md: "expected unused cap must remain a
        representable, non-zero possibility"). Observation noise is set to
        zero here deliberately - this test isolates the structural cap
        regime's effect on identification, not the separate (real, but
        different) question of noisy delivery measurement masking true
        binding status: `identify_candidate_a_search`'s binding check is an
        exact `np.isclose(..., rtol=1e-8, atol=1e-8)`, so even small
        observation noise on an always-binding cap flips roughly half the
        periods to "not close enough to call binding" - a genuine,
        separate identification-sensitivity finding (measurement noise
        degrades cap-hit detection), not something this structural-regime
        test conflates in."""
        scenario = CandidateARecoveryScenario(
            name=f"regime_{cap_regime}",
            channels=[self._channel()],
            demand_channel_names=["SearchBrand"],
            cap_regime=cap_regime,
            cap_variation=0.05,
            n_periods=60,
            seed=2,
            truth=CandidateARecoveryTruth(
                delivery_observation_noise=0.0, capture_observation_noise=0.0
            ),
        )
        report = self._identify(scenario)
        assert any(
            expected_missing_support in reason for reason in report.blocking_reasons
        )
        assert not report.official_eligible

    def test_sometimes_binding_regime_with_real_variation_is_not_blocked_by_support(
        self,
    ):
        scenario = CandidateARecoveryScenario(
            name="sometimes_binds_well_identified",
            channels=[self._channel()],
            demand_channel_names=["SearchBrand"],
            cap_regime=CAP_REGIME_SOMETIMES_BINDS,
            cap_variation=0.4,
            n_periods=60,
            seed=3,
        )
        report = self._identify(scenario)
        assert not any("variation" in reason for reason in report.blocking_reasons)
        assert not any("binding" in reason for reason in report.blocking_reasons)

    @pytest.mark.parametrize(
        "n_periods,n_markets,expect_sparse", [(60, 1, False), (12, 4, True)]
    )
    def test_short_per_market_history_is_flagged_as_sparse_market_support(
        self, n_periods, n_markets, expect_sparse
    ):
        scenario = CandidateARecoveryScenario(
            name=f"market_support_{n_periods}_{n_markets}",
            channels=[self._channel()],
            demand_channel_names=["SearchBrand"],
            cap_regime=CAP_REGIME_SOMETIMES_BINDS,
            cap_variation=0.35,
            n_periods=n_periods,
            n_markets=n_markets,
            seed=4,
        )
        report = self._identify(scenario)
        has_sparse_reason = any(
            "sparse" in reason for reason in report.blocking_reasons
        )
        assert has_sparse_reason is expect_sparse
