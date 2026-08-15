"""Synthetic decision evidence for the unresolved Search model choice."""

import numpy as np
import pytest

from ancestry_mmm.core.search_decision_package import (
    SEARCH_SCENARIOS,
    conditional_demand_posterior_recovery,
    generate_search_synthetic_panel,
    run_search_recovery_suite,
    simulate_structural_hard_cap,
    summarize_search_effects,
)


@pytest.mark.parametrize("scenario", SEARCH_SCENARIOS)
def test_synthetic_panel_preserves_search_object_identities_and_reconciles(
    scenario,
):
    panel = generate_search_synthetic_panel(scenario)

    assert panel.observed_columns == (
        "upstream_media",
        "paid_search_spend",
        "paid_search_delivery",
        "paid_search_cap",
        "organic_search_capture",
        "direct_navigation_capture",
        "final_outcome",
    )
    assert "latent_demand" not in panel.observed_columns
    assert "residual_paid_search_incrementality" in panel.derived_columns
    assert np.allclose(
        panel.captured_demand_truth + panel.unmet_demand_truth,
        panel.latent_demand_truth,
    )
    assert np.all(panel.paid_search_delivery <= panel.paid_search_cap + 1e-12)


def test_structural_candidate_recovers_all_known_truth_scenarios():
    evidence = run_search_recovery_suite()

    assert len(evidence) == len(SEARCH_SCENARIOS)
    for result in evidence:
        assert result.max_latent_demand_error == pytest.approx(0.0)
        assert result.max_paid_delivery_error == pytest.approx(0.0)
        assert result.max_captured_demand_error == pytest.approx(0.0)
        assert result.max_unmet_demand_error == pytest.approx(0.0)
        assert result.max_total_effect_error == pytest.approx(0.0)
        assert result.cap_raise_nonbinding_invariant
        assert result.reconciliation_invariant


def test_raising_a_nonbinding_cap_does_not_create_incremental_delivery():
    panel = generate_search_synthetic_panel("cap_never_binds")
    baseline = simulate_structural_hard_cap(panel)
    raised = simulate_structural_hard_cap(
        panel, cap_override=panel.paid_search_cap * 10.0
    )

    assert np.allclose(baseline["paid_search_delivery"], raised["paid_search_delivery"])
    assert np.allclose(baseline["captured_demand"], raised["captured_demand"])


def test_heavy_binding_exposes_unmet_demand_without_double_counting_total():
    panel = generate_search_synthetic_panel("cap_binds_heavily")
    effects = summarize_search_effects(panel)

    assert np.all(panel.cap_hit)
    assert effects.unmet_demand_effect > 0.0
    assert effects.unconstrained_potential_outcome_effect > effects.total_outcome_effect
    assert effects.unconstrained_potential_outcome_effect == pytest.approx(
        effects.total_outcome_effect
        + effects.unmet_demand_effect * panel.truth.captured_demand_outcome_coefficient
    )


def test_apparent_paid_association_can_be_high_while_incremental_capture_is_low():
    panel = generate_search_synthetic_panel(
        "apparent_paid_association_low_incrementality"
    )
    association = float(
        np.corrcoef(panel.upstream_media, panel.paid_search_delivery)[0, 1]
    )
    effects = summarize_search_effects(panel)

    assert association > 0.8
    assert effects.mediated_outcome_effect < effects.direct_outcome_effect


def test_realised_total_effect_is_direct_plus_realised_mediated_effect():
    panel = generate_search_synthetic_panel("upstream_media_cap_limited")
    effects = summarize_search_effects(panel)

    assert effects.total_outcome_effect == pytest.approx(
        effects.direct_outcome_effect + effects.mediated_outcome_effect
    )
    assert effects.total_outcome_effect == pytest.approx(
        np.sum(panel.final_outcome - panel.outcome_without_upstream_media)
    )


@pytest.mark.parametrize("scenario", SEARCH_SCENARIOS)
def test_noisy_simulation_preserves_cap_and_separate_observed_search_objects(scenario):
    panel = generate_search_synthetic_panel(scenario, noisy=True, seed=20260815)

    assert np.all(panel.paid_search_delivery <= panel.paid_search_cap + 1e-12)
    assert panel.paid_search_spend.shape == panel.paid_search_delivery.shape
    assert np.all(panel.organic_search_capture >= 0)
    assert np.all(panel.direct_navigation_capture >= 0)
    assert np.all(panel.final_outcome >= 0)


def test_noisy_conditional_posterior_recovers_latent_demand_media_parameter():
    panel = generate_search_synthetic_panel(
        "cap_sometimes_binds", noisy=True, seed=20260815, periods=104
    )
    evidence = conditional_demand_posterior_recovery(panel, draws=1200)

    assert evidence.conditional_on_capture_mapping
    assert evidence.parameter == "demand_media_coefficient"
    assert evidence.recovered
    assert evidence.posterior_interval[0] <= evidence.true_value <= evidence.posterior_interval[1]
