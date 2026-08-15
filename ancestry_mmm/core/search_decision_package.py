"""Synthetic evidence for the Search mediation/capacity model decision.

This module is a Candidate A simulation/replay harness. It keeps
the Search object identities from REQ-SEARCH-001 visible while generating
small panels with known structural truth. The harness tests forward equations
and reconciliation contracts; it does not grant planning or optimisation
eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Sequence, cast

import numpy as np

SearchScenario = Literal[
    "cap_never_binds",
    "cap_sometimes_binds",
    "cap_binds_heavily",
    "upstream_media_cap_limited",
    "organic_direct_absorption",
    "apparent_paid_association_low_incrementality",
]
CandidateId = Literal[
    "structural_hard_cap",
    "probabilistic_capture_cap",
    "reduced_form_benchmark",
]

SEARCH_SCENARIOS: tuple[SearchScenario, ...] = (
    "cap_never_binds",
    "cap_sometimes_binds",
    "cap_binds_heavily",
    "upstream_media_cap_limited",
    "organic_direct_absorption",
    "apparent_paid_association_low_incrementality",
)


@dataclass(frozen=True)
class SearchSyntheticTruth:
    """Generating values for one synthetic panel.

    ``paid_capture_share`` is the share of latent demand that could be
    captured by Paid Search before the cap. It is not a spend share and does
    not turn a cap into realised spend.
    """

    baseline_demand: float = 120.0
    seasonal_demand_amplitude: float = 6.0
    demand_media_coefficient: float = 0.75
    organic_capture_share: float = 0.20
    direct_capture_share: float = 0.15
    paid_capture_share: float = 0.65
    baseline_outcome: float = 220.0
    direct_media_outcome_coefficient: float = 0.20
    captured_demand_outcome_coefficient: float = 0.55
    paid_delivery_cost: float = 1.25
    observation_noise_sigma: float = 0.0
    outcome_dispersion: float = 40.0


@dataclass(frozen=True)
class SearchSyntheticPanel:
    """Observed and ground-truth series for a synthetic Search scenario."""

    scenario: SearchScenario
    periods: np.ndarray
    upstream_media: np.ndarray
    paid_search_spend: np.ndarray
    paid_search_delivery: np.ndarray
    paid_search_cap: np.ndarray
    organic_search_capture: np.ndarray
    direct_navigation_capture: np.ndarray
    final_outcome: np.ndarray
    latent_demand_truth: np.ndarray
    paid_search_potential_truth: np.ndarray
    captured_demand_truth: np.ndarray
    unmet_demand_truth: np.ndarray
    outcome_without_upstream_media: np.ndarray
    truth: SearchSyntheticTruth

    @property
    def cap_hit(self) -> np.ndarray:
        """Whether the realised delivery is at the configured cap."""

        return cast(
            np.ndarray, np.isclose(self.paid_search_delivery, self.paid_search_cap)
        )

    @property
    def observed_columns(self) -> tuple[str, ...]:
        """Source identities that are observed in this fixture."""

        return (
            "upstream_media",
            "paid_search_spend",
            "paid_search_delivery",
            "paid_search_cap",
            "organic_search_capture",
            "direct_navigation_capture",
            "final_outcome",
        )

    @property
    def derived_columns(self) -> tuple[str, ...]:
        """Quantities derived by the candidate structure, not raw sources."""

        return (
            "latent_demand",
            "captured_demand",
            "unmet_demand",
            "residual_paid_search_incrementality",
        )

    def observed_series(self) -> Mapping[str, np.ndarray]:
        """Return source-like series without exposing latent truth as input."""

        return {
            name: getattr(self, name)
            for name in self.observed_columns
            if hasattr(self, name)
        }


@dataclass(frozen=True)
class SearchEffectSummary:
    """Outcome-scale and demand-volume effects for an upstream intervention."""

    direct_outcome_effect: float
    mediated_outcome_effect: float
    captured_demand_effect: float
    unmet_demand_effect: float
    total_outcome_effect: float
    unconstrained_potential_outcome_effect: float


@dataclass(frozen=True)
class CandidateRecoveryEvidence:
    """Deterministic forward-recovery evidence for one candidate/scenario."""

    candidate: CandidateId
    scenario: SearchScenario
    max_latent_demand_error: float | None
    max_paid_delivery_error: float | None
    max_captured_demand_error: float | None
    max_unmet_demand_error: float | None
    max_total_effect_error: float | None
    cap_raise_nonbinding_invariant: bool
    reconciliation_invariant: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConditionalPosteriorRecovery:
    """Posterior recovery evidence for the identifiable demand stage.

    This is deliberately labelled conditional: it conditions on the
    governed organic/direct capture-share calibration so it can isolate
    latent-demand recovery in a noisy simulation. It is not a substitute for
    the full linked posterior or the official-use gate.
    """

    parameter: str
    posterior_mean: float
    posterior_interval: tuple[float, float]
    true_value: float
    recovered: bool
    conditional_on_capture_mapping: bool = True


def _validate_scenario(scenario: str) -> SearchScenario:
    if scenario not in SEARCH_SCENARIOS:
        raise ValueError(
            f"Unknown Search synthetic scenario {scenario!r}; "
            f"expected one of {SEARCH_SCENARIOS}."
        )
    return scenario


def _scenario_truth(scenario: SearchScenario) -> SearchSyntheticTruth:
    if scenario == "organic_direct_absorption":
        return SearchSyntheticTruth(
            organic_capture_share=0.42,
            direct_capture_share=0.30,
            paid_capture_share=0.28,
        )
    if scenario == "apparent_paid_association_low_incrementality":
        return SearchSyntheticTruth(
            captured_demand_outcome_coefficient=0.04,
            direct_media_outcome_coefficient=0.18,
        )
    return SearchSyntheticTruth()


def _cap_schedule(scenario: SearchScenario, paid_potential: np.ndarray) -> np.ndarray:
    if scenario == "cap_never_binds":
        return np.asarray(paid_potential.max() * 1.25 + np.zeros_like(paid_potential))
    if scenario == "cap_sometimes_binds":
        multiplier = np.where(np.arange(paid_potential.size) % 8 < 4, 0.72, 1.30)
        return np.asarray(paid_potential * multiplier)
    if scenario == "cap_binds_heavily":
        return np.asarray(paid_potential * 0.28)
    if scenario == "upstream_media_cap_limited":
        multiplier = np.where(paid_potential > np.median(paid_potential), 0.42, 1.20)
        return np.asarray(paid_potential * multiplier)
    return np.asarray(paid_potential.max() * 1.25 + np.zeros_like(paid_potential))


def _forward_components(
    media: np.ndarray,
    periods: np.ndarray,
    cap: np.ndarray,
    truth: SearchSyntheticTruth,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    latent = (
        truth.baseline_demand
        + truth.seasonal_demand_amplitude * np.cos(periods / 5.0)
        + truth.demand_media_coefficient * media
    )
    organic = latent * truth.organic_capture_share
    direct = latent * truth.direct_capture_share
    paid_potential = latent * truth.paid_capture_share
    paid_delivery = np.minimum(paid_potential, cap)
    captured = organic + direct + paid_delivery
    unmet = latent - captured
    return (
        cast(np.ndarray, latent),
        cast(np.ndarray, paid_potential),
        cast(np.ndarray, paid_delivery),
        cast(np.ndarray, captured),
        cast(np.ndarray, unmet),
    )


def generate_search_synthetic_panel(
    scenario: str,
    *,
    periods: int = 52,
    seed: int = 20260815,
    noisy: bool = False,
) -> SearchSyntheticPanel:
    """Generate a known-truth panel, optionally with noisy observations.

    The default remains noiseless so contract tests isolate causal structure.
    ``noisy=True`` adds bounded capture/delivery measurement noise and draws
    final outcomes from a Negative Binomial with the same count-link family
    used by the existing outcome engine.
    """

    resolved_scenario = _validate_scenario(scenario)
    if periods < 8:
        raise ValueError("Search synthetic panels require at least 8 periods.")
    truth = _scenario_truth(resolved_scenario)
    if noisy:
        truth = SearchSyntheticTruth(
            **{
                **truth.__dict__,
                "observation_noise_sigma": 2.0,
            }
        )
    rng = np.random.default_rng(seed)
    period_index: np.ndarray = np.arange(periods, dtype=float)
    media = 42.0 + 18.0 * np.sin(period_index / 4.0) + rng.normal(0.0, 3.0, periods)
    media = np.maximum(media, 5.0)
    zero_cap = np.zeros(periods)
    _, paid_potential_for_cap, _, _, _ = _forward_components(
        media, period_index, zero_cap, truth
    )
    cap = _cap_schedule(resolved_scenario, paid_potential_for_cap)
    latent, paid_potential, paid_delivery, captured, unmet = _forward_components(
        media, period_index, cap, truth
    )
    media_zero_latent, _, _, media_zero_captured, _ = _forward_components(
        np.zeros(periods), period_index, cap, truth
    )
    organic = latent * truth.organic_capture_share
    direct = latent * truth.direct_capture_share
    outcome_mean = (
        truth.baseline_outcome
        + truth.direct_media_outcome_coefficient * media
        + truth.captured_demand_outcome_coefficient * captured
    )
    outcome_without_media = (
        truth.baseline_outcome
        + truth.captured_demand_outcome_coefficient * media_zero_captured
    )
    if noisy:
        noise = truth.observation_noise_sigma
        observed_delivery = np.minimum(
            np.maximum(paid_delivery + rng.normal(0.0, noise, periods), 0.0), cap
        )
        observed_organic = np.maximum(
            organic + rng.normal(0.0, noise, periods), 0.0
        )
        observed_direct = np.maximum(
            direct + rng.normal(0.0, noise, periods), 0.0
        )
        alpha = truth.outcome_dispersion
        probability = alpha / (alpha + np.maximum(outcome_mean, 1e-6))
        outcome = rng.negative_binomial(alpha, probability).astype(float)
    else:
        observed_delivery = paid_delivery
        observed_organic = organic
        observed_direct = direct
        outcome = outcome_mean
    del zero_cap, media_zero_latent
    return SearchSyntheticPanel(
        scenario=resolved_scenario,
        periods=period_index,
        upstream_media=media,
        paid_search_spend=paid_delivery * truth.paid_delivery_cost,
        paid_search_delivery=observed_delivery,
        paid_search_cap=cap,
        organic_search_capture=observed_organic,
        direct_navigation_capture=observed_direct,
        final_outcome=outcome,
        latent_demand_truth=latent,
        paid_search_potential_truth=paid_potential,
        captured_demand_truth=captured,
        unmet_demand_truth=unmet,
        outcome_without_upstream_media=outcome_without_media,
        truth=truth,
    )


def conditional_demand_posterior_recovery(
    panel: SearchSyntheticPanel,
    *,
    draws: int = 2000,
    seed: int = 20260815,
) -> ConditionalPosteriorRecovery:
    """Recover the latent-demand media coefficient from a noisy panel.

    The conditional likelihood uses the separately governed organic and
    direct captures to form a demand proxy, includes the known seasonal
    basis used by the generator, and applies a proper Gaussian posterior for
    the conditional linear demand stage. This supplies fast posterior parameter-
    recovery evidence without pretending that it identifies the full linked
    Search model when cap variation or capture mappings are weak.
    """

    if draws < 100:
        raise ValueError("posterior recovery requires at least 100 draws")
    denominator = panel.truth.organic_capture_share + panel.truth.direct_capture_share
    if denominator <= 0:
        raise ValueError("conditional recovery requires positive organic/direct capture")
    proxy = np.maximum(
        (panel.organic_search_capture + panel.direct_navigation_capture) / denominator,
        1e-6,
    )
    design = np.column_stack(
        [
            np.ones(panel.periods.size),
            np.cos(panel.periods / 5.0),
            panel.upstream_media,
        ]
    )
    response = proxy
    ols = np.linalg.lstsq(design, response, rcond=None)[0]
    residual = response - design @ ols
    variance = max(float(np.sum(residual**2) / max(panel.periods.size - design.shape[1], 1)), 1e-4)
    prior_variance = np.array([10_000.0, 100.0, 4.0])
    precision = (design.T @ design) / variance + np.diag(1.0 / prior_variance)
    covariance = np.linalg.inv(precision)
    mean = covariance @ ((design.T @ response) / variance)
    posterior_draws = np.random.default_rng(seed).multivariate_normal(mean, covariance, draws)
    lower, upper = np.quantile(posterior_draws[:, 2], [0.025, 0.975])
    posterior_mean = float(np.mean(posterior_draws[:, 2]))
    true_value = panel.truth.demand_media_coefficient
    return ConditionalPosteriorRecovery(
        parameter="demand_media_coefficient",
        posterior_mean=posterior_mean,
        posterior_interval=(float(lower), float(upper)),
        true_value=true_value,
        recovered=bool(lower <= true_value <= upper and abs(posterior_mean - true_value) < 0.15),
    )


def simulate_structural_hard_cap(
    panel: SearchSyntheticPanel,
    *,
    cap_override: Sequence[float] | np.ndarray | None = None,
) -> Mapping[str, np.ndarray]:
    """Forward-simulate Candidate A from upstream media and a cap decision."""

    cap = (
        panel.paid_search_cap
        if cap_override is None
        else np.asarray(cap_override, dtype=float)
    )
    if cap.shape != panel.paid_search_cap.shape:
        raise ValueError("cap_override must have one value per synthetic period.")
    latent, paid_potential, paid_delivery, captured, unmet = _forward_components(
        panel.upstream_media, panel.periods, cap, panel.truth
    )
    return {
        "latent_demand": latent,
        "paid_search_potential": paid_potential,
        "paid_search_delivery": paid_delivery,
        "organic_search_capture": latent * panel.truth.organic_capture_share,
        "direct_navigation_capture": latent * panel.truth.direct_capture_share,
        "captured_demand": captured,
        "unmet_demand": unmet,
    }


def summarize_search_effects(panel: SearchSyntheticPanel) -> SearchEffectSummary:
    """Summarise the generator's intervention effects on the outcome scale."""

    zero_latent, _, _, zero_captured, _ = _forward_components(
        np.zeros_like(panel.upstream_media),
        panel.periods,
        panel.paid_search_cap,
        panel.truth,
    )
    captured_change = panel.captured_demand_truth - zero_captured
    latent_change = panel.latent_demand_truth - zero_latent
    direct_effect = float(
        np.sum(panel.truth.direct_media_outcome_coefficient * panel.upstream_media)
    )
    mediated_effect = float(
        np.sum(panel.truth.captured_demand_outcome_coefficient * captured_change)
    )
    total_effect = direct_effect + mediated_effect
    unconstrained = direct_effect + float(
        np.sum(panel.truth.captured_demand_outcome_coefficient * latent_change)
    )
    return SearchEffectSummary(
        direct_outcome_effect=direct_effect,
        mediated_outcome_effect=mediated_effect,
        captured_demand_effect=float(np.sum(captured_change)),
        unmet_demand_effect=float(np.sum(latent_change - captured_change)),
        total_outcome_effect=total_effect,
        unconstrained_potential_outcome_effect=unconstrained,
    )


def evaluate_structural_recovery(
    panel: SearchSyntheticPanel,
) -> CandidateRecoveryEvidence:
    """Compare Candidate A's forward equations with known generator truth."""

    predicted = simulate_structural_hard_cap(panel)
    truth_effect = summarize_search_effects(panel)
    predicted_zero = _forward_components(
        np.zeros_like(panel.upstream_media),
        panel.periods,
        panel.paid_search_cap,
        panel.truth,
    )
    predicted_captured_change = predicted["captured_demand"] - predicted_zero[3]
    predicted_total = float(
        np.sum(panel.truth.direct_media_outcome_coefficient * panel.upstream_media)
        + np.sum(
            panel.truth.captured_demand_outcome_coefficient * predicted_captured_change
        )
    )
    raised = simulate_structural_hard_cap(
        panel, cap_override=panel.paid_search_cap * 2.0
    )
    nonbinding = ~panel.cap_hit
    nonbinding_ok = bool(
        np.allclose(
            raised["paid_search_delivery"][nonbinding],
            panel.paid_search_delivery[nonbinding],
        )
    )
    reconciliation_ok = bool(
        np.allclose(
            predicted["captured_demand"] + predicted["unmet_demand"],
            predicted["latent_demand"],
        )
    )
    return CandidateRecoveryEvidence(
        candidate="structural_hard_cap",
        scenario=panel.scenario,
        max_latent_demand_error=float(
            np.max(np.abs(predicted["latent_demand"] - panel.latent_demand_truth))
        ),
        max_paid_delivery_error=float(
            np.max(
                np.abs(predicted["paid_search_delivery"] - panel.paid_search_delivery)
            )
        ),
        max_captured_demand_error=float(
            np.max(np.abs(predicted["captured_demand"] - panel.captured_demand_truth))
        ),
        max_unmet_demand_error=float(
            np.max(np.abs(predicted["unmet_demand"] - panel.unmet_demand_truth))
        ),
        max_total_effect_error=abs(predicted_total - truth_effect.total_outcome_effect),
        cap_raise_nonbinding_invariant=nonbinding_ok,
        reconciliation_invariant=reconciliation_ok,
        notes=(
            "Forward recovery only: no posterior inference or identifiability claim.",
            "Unmet outcome potential is diagnostic and is not added to realised total effect.",
        ),
    )


def run_search_recovery_suite(
    *,
    scenarios: Sequence[SearchScenario] = SEARCH_SCENARIOS,
) -> tuple[CandidateRecoveryEvidence, ...]:
    """Run Candidate A's deterministic recovery contract across scenarios."""

    return tuple(
        evaluate_structural_recovery(
            generate_search_synthetic_panel(scenario, seed=20260815 + index)
        )
        for index, scenario in enumerate(scenarios)
    )
