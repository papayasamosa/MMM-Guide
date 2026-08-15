"""WP2 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`): Candidate A
synthetic generator and evidence-grade contracts for the *integrated*
production model (`core.hierarchical_model.build_fh_hierarchical_model(...,
search_candidate_a=...)`), not the standalone builder's own conditional
recovery fixtures in `core.search_decision_package`/`test_search_capacity.py`.

Independent-coded forward simulation: this generator computes the Candidate
A forward equations directly in NumPy using the same reference adstock/Hill
functions the production builder uses (`core.transformations.
geometric_adstock`/`hill_function` - the NumPy definitions, never a second,
divergent implementation), but never calls
`core.search_capacity.attach_candidate_a_demand_capture_chain` or any
PyTensor/PyMC code to produce ground truth - a genuine mismatch between the
approved equations and the PyMC implementation must be able to show up as a
recovery failure, not be hidden by replaying the same code twice.

Evidence-grade policy (versioned; see `CANDIDATE_A_RECOVERY_POLICY` below):
this module records interval-coverage-style recovery evidence, not exact
point recovery - AGENTS.md and REQ-SEARCH-002 both require identification
diagnostics and recovery evidence before official use, but do not mandate
one specific coverage threshold, and this module does not invent official
eligibility on the model's behalf (`core.search_capacity.
candidate_a_use_gate` remains the single official-use gate; passing this
module's checks only supplies one of its required evidence inputs -
`noisy_recovery_passed` - a human/process decision still sets that flag).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np

from .causal_graph import (
    CausalEdge,
    CausalGraph,
    EDGE_ROLE_CAPACITY_CONSTRAINED,
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_MEDIATED,
    GRAPH_STATUS_APPROVED,
    NODE_ROLE_CAPACITY_OR_CAP,
    NODE_ROLE_DEMAND_CAPTURE,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_OUTCOME,
    CausalNode,
)
from .search_capacity import CandidateASearchFitInputs, SearchCandidateASpec
from .search_objects import (
    SEARCH_ROLE_DEMAND,
    SEARCH_ROLE_DIRECT_NAV_CAPTURE,
    SEARCH_ROLE_ORGANIC_CAPTURE,
    SEARCH_ROLE_PAID_CAP,
    SEARCH_ROLE_PAID_DELIVERY,
    SEARCH_ROLE_PAID_SPEND,
    UNIT_EXPOSURE_COUNT,
    UNIT_MONETARY,
    UNIT_RESPONSE_COUNT,
    SearchObjectDefinition,
)
from .transformations import geometric_adstock, hill_function

CAP_REGIME_NEVER_BINDS = "never_binds"
CAP_REGIME_SOMETIMES_BINDS = "sometimes_binds"
CAP_REGIME_FREQUENTLY_BINDS = "frequently_binds"
CAP_REGIMES = (
    CAP_REGIME_NEVER_BINDS,
    CAP_REGIME_SOMETIMES_BINDS,
    CAP_REGIME_FREQUENTLY_BINDS,
)


@dataclass(frozen=True)
class CandidateARecoveryPolicy:
    """Versioned evidence-grade thresholds this module's checks are graded
    against. A ceiling/floor here is an engineering evidence bar, not a
    universal causal-identification guarantee (mirrors
    `core.search_capacity.identify_candidate_a_search`'s own docstring on
    this point)."""

    version: str
    rationale: str
    scope: str
    review_owner: str
    # Interval-coverage evidence grade: fraction of scenarios where the true
    # value falls inside the reported credible interval, at the stated
    # width. Not a point-recovery requirement.
    min_interval_coverage: float = 0.6
    credible_interval_width: float = 0.9


CANDIDATE_A_RECOVERY_POLICY = CandidateARecoveryPolicy(
    version="wp2-v1",
    rationale=(
        "First recovery-evidence pass for the integrated Candidate A model "
        "(WP2). Coverage requirement is deliberately loose (60% of "
        "scenarios hit their 90% interval) because MCMC draws are kept "
        "small for CI tractability (see test_search_candidate_a_recovery.py) "
        "and several scenarios are deliberately weakly identified by "
        "design (per REQ-SEARCH-002's own required evidence: weak/absent "
        "cap variation must be diagnosed, not hidden by a lax threshold "
        "elsewhere)."
    ),
    scope="Candidate A engine capability evidence only - not an official-use approval.",
    review_owner="Data Science / Platform engineering",
)


@dataclass(frozen=True)
class ChannelTruth:
    """Ground-truth generative parameters for one upstream channel."""

    name: str
    decay_rate: float
    hill_K: float
    hill_S: float
    direct_beta: float = 0.0
    demand_beta: float = 0.0
    spend_mean: float = 500.0
    spend_sd: float = 150.0


@dataclass(frozen=True)
class CandidateARecoveryTruth:
    """Ground-truth generative parameters for the Search demand/capture
    chain and outcome equation, independent of any PyMC variable name."""

    demand_intercept: float = 1.5
    capture_share_paid: float = 0.35
    capture_share_organic: float = 0.2
    capture_share_direct: float = 0.15
    beta_paid_capture: float = 0.4
    beta_organic_capture: float = 0.3
    beta_direct_capture: float = 0.3
    outcome_intercept: float = 2.5
    alpha_dispersion: float = 8.0
    delivery_observation_noise: float = 2.0
    capture_observation_noise: float = 2.0


@dataclass(frozen=True)
class CandidateARecoveryScenario:
    """One synthetic-data configuration. `channels` must list every
    upstream channel; `demand_channel_names` must currently equal the same
    set (see `__post_init__` - the approved Candidate A graph contract
    requires every intervention node to mediate into demand). A
    "direct-only" channel is expressed via `ChannelTruth(demand_beta=0.0)`,
    not by omission from `demand_channel_names`."""

    name: str
    channels: Sequence[ChannelTruth]
    demand_channel_names: Sequence[str]
    n_periods: int = 60
    n_markets: int = 1
    cap_regime: str = CAP_REGIME_SOMETIMES_BINDS
    cap_variation: float = 0.35
    noise_scale: float = 0.05
    seed: int = 0
    truth: CandidateARecoveryTruth = field(default_factory=CandidateARecoveryTruth)

    def __post_init__(self) -> None:
        if self.cap_regime not in CAP_REGIMES:
            raise ValueError(f"unsupported cap_regime {self.cap_regime!r}")
        names = {c.name for c in self.channels}
        unknown = [c for c in self.demand_channel_names if c not in names]
        if unknown:
            raise ValueError(f"demand_channel_names not in channels: {unknown}")
        if not self.demand_channel_names:
            raise ValueError("Candidate A requires at least one demand-driving channel")
        # core.graph_model_compiler.candidate_a_graph_issues (REQ-SEARCH-002,
        # approved by PR #253) requires EVERY upstream intervention node to
        # carry a mediated edge to latent demand - a graph cannot mix
        # demand-mediating and plain-direct-only intervention nodes. A
        # "direct-only" channel is expressed via ChannelTruth(demand_beta=0.0)
        # instead - the mediated edge still exists structurally, but that
        # channel's true effect on demand is zero, which is itself a
        # meaningful recovery target (the model should recover a near-zero
        # demand_beta, not merely "not be asked about" that channel).
        if set(self.demand_channel_names) != names:
            raise ValueError(
                "The approved Candidate A graph contract requires every "
                "channel to be a demand_channel_name (with demand_beta=0.0 "
                "in ChannelTruth for a channel that should behave as "
                f"direct-only in the ground truth); got channels={sorted(names)} "
                f"demand_channel_names={sorted(self.demand_channel_names)}."
            )


@dataclass(frozen=True)
class CandidateASyntheticData:
    """Everything needed to fit the integrated production model against
    this scenario, plus the ground truth to compare recovered posteriors
    against."""

    frame: Dict[str, Any]
    fit_inputs: CandidateASearchFitInputs
    graph: CausalGraph
    search_objects: List[SearchObjectDefinition | Mapping[str, Any]]
    ground_truth: Dict[str, float]


def _market_slices(n_periods: int, n_markets: int) -> List[tuple]:
    per_market = n_periods // n_markets
    bounds = []
    start = 0
    for m in range(n_markets):
        end = start + per_market if m < n_markets - 1 else n_periods
        bounds.append((start, end))
        start = end
    return bounds


def generate_candidate_a_synthetic_data(
    scenario: CandidateARecoveryScenario,
) -> CandidateASyntheticData:
    """Independently simulate a full multi-channel Candidate A dataset
    shaped exactly like `data.preprocessor.prepare_fh_modeling_frame`'s
    output, plus Search observations, a minimal approved Candidate A graph,
    and governed Search object definitions - everything
    `core.hierarchical_model.build_fh_hierarchical_model(...,
    search_candidate_a=...)` needs."""

    rng = np.random.default_rng(scenario.seed)
    n = scenario.n_periods
    channels = list(scenario.channels)
    channel_names = [c.name for c in channels]
    truth = scenario.truth
    market_bounds = _market_slices(n, scenario.n_markets)
    market_idx = np.zeros(n, dtype=int)
    for m, (start, end) in enumerate(market_bounds):
        market_idx[start:end] = m
    markets = [f"MKT{m}" for m in range(scenario.n_markets)]

    # --- upstream media, per market (adstock/saturation reset per market) ---
    X_media = np.zeros((n, len(channels)))
    sat_media = np.zeros((n, len(channels)))
    for ci, channel in enumerate(channels):
        for start, end in market_bounds:
            block = np.maximum(
                rng.normal(channel.spend_mean, channel.spend_sd, end - start), 0.0
            )
            X_media[start:end, ci] = block
            adstocked = geometric_adstock(block, channel.decay_rate, normalize=True)
            sat_media[start:end, ci] = hill_function(
                adstocked, channel.hill_K, channel.hill_S
            )

    # --- direct upstream-media contribution to the outcome ---
    eta_direct = np.zeros(n)
    for ci, channel in enumerate(channels):
        eta_direct += channel.direct_beta * sat_media[:, ci]

    # --- latent demand, driven only by the designated demand channels ---
    demand_idx = [
        i for i, c in enumerate(channels) if c.name in scenario.demand_channel_names
    ]
    eta_demand = truth.demand_intercept + sum(
        channels[i].demand_beta * sat_media[:, i] for i in demand_idx
    )
    latent_demand = np.exp(eta_demand)

    # --- capture shares (paid / organic / direct / implicit unmet) ---
    paid_opportunity = latent_demand * truth.capture_share_paid
    organic_expected = latent_demand * truth.capture_share_organic
    direct_expected = latent_demand * truth.capture_share_direct

    # --- cap, calibrated to the regime relative to true paid opportunity ---
    if scenario.cap_regime == CAP_REGIME_NEVER_BINDS:
        cap_ratio_mean = 3.0
    elif scenario.cap_regime == CAP_REGIME_FREQUENTLY_BINDS:
        cap_ratio_mean = 0.6
    else:
        cap_ratio_mean = 1.0
    cap_ratio = np.clip(
        rng.normal(cap_ratio_mean, scenario.cap_variation, n), 0.1, None
    )
    cap = paid_opportunity * cap_ratio
    realised_paid = np.minimum(paid_opportunity, cap)
    total_captured = organic_expected + direct_expected + realised_paid
    unmet_demand = latent_demand - total_captured
    if np.any(unmet_demand < -1e-6):
        raise AssertionError(
            "synthetic generator produced negative unmet demand - capture "
            "shares must sum to <= 1"
        )

    capture_scale = max(
        float(np.mean(realised_paid + organic_expected + direct_expected)), 1.0
    )
    eta_search = (
        truth.beta_paid_capture * (realised_paid / capture_scale)
        + truth.beta_organic_capture * (organic_expected / capture_scale)
        + truth.beta_direct_capture * (direct_expected / capture_scale)
    )

    eta_total = truth.outcome_intercept + eta_direct + eta_search
    mu = np.clip(np.exp(eta_total), 1e-6, 1e9)
    # Negative Binomial via Gamma-Poisson mixture, matching the production
    # NegativeBinomial(mu, alpha) parameterisation.
    gamma_shape = truth.alpha_dispersion
    gamma_scale = mu / gamma_shape
    lam = rng.gamma(gamma_shape, gamma_scale)
    Y = rng.poisson(lam).astype(float).reshape(-1, 1)

    delivery_obs = np.maximum(
        realised_paid + rng.normal(0, truth.delivery_observation_noise, n), 0.0
    )
    organic_obs = np.maximum(
        organic_expected + rng.normal(0, truth.capture_observation_noise, n), 0.0
    )
    direct_obs = np.maximum(
        direct_expected + rng.normal(0, truth.capture_observation_noise, n), 0.0
    )
    # Structural invariant (observed delivery <= observed cap) required by
    # CandidateASearchFitInputs/validate_candidate_a_spec - clip rather than
    # reject, since real-world measurement noise can push either side.
    delivery_obs = np.minimum(delivery_obs, cap)

    frame = {
        "markets": markets,
        "market_idx": market_idx,
        "market_bounds": market_bounds,
        "channels": channel_names,
        "dna_channel_idx": [],
        "outcome_ids": ["synthetic_outcome"],
        "X_media": X_media,
        "Y": Y,
        "promo": np.zeros((n, 1)),
        "X_controls": np.zeros((n, 0)),
        "control_names": [],
        "fourier": np.zeros((n, 2)),
        "trend": np.ones(n),
        "unpooled_markets": [],
    }

    spec = SearchCandidateASpec(
        outcome_definition_id="synthetic_outcome",
        outcome_definition_version="1",
        outcome_definition_fingerprint="synthetic",
        market_scope=markets[0] if scenario.n_markets == 1 else "*",
        demand_object_id="obj_demand",
        paid_spend_object_id="obj_spend",
        paid_delivery_object_id="obj_delivery",
        paid_cap_object_id="obj_cap",
        organic_capture_object_id="obj_organic",
        direct_navigation_object_id="obj_direct",
        cap_provenance="analyst_declared",
        cap_provenance_status="resolved",
    )
    search_objects: List[SearchObjectDefinition | Mapping[str, Any]] = [
        SearchObjectDefinition(
            search_object_id="obj_demand",
            search_role=SEARCH_ROLE_DEMAND,
            source_column="search_demand_raw",
            unit=UNIT_EXPOSURE_COUNT,
        ),
        SearchObjectDefinition(
            search_object_id="obj_cap",
            search_role=SEARCH_ROLE_PAID_CAP,
            source_column="search_cap_raw",
            unit=UNIT_EXPOSURE_COUNT,
        ),
        SearchObjectDefinition(
            search_object_id="obj_organic",
            search_role=SEARCH_ROLE_ORGANIC_CAPTURE,
            source_column="search_organic_raw",
            unit=UNIT_RESPONSE_COUNT,
        ),
        SearchObjectDefinition(
            search_object_id="obj_direct",
            search_role=SEARCH_ROLE_DIRECT_NAV_CAPTURE,
            source_column="search_direct_raw",
            unit=UNIT_RESPONSE_COUNT,
        ),
        SearchObjectDefinition(
            search_object_id="obj_spend",
            search_role=SEARCH_ROLE_PAID_SPEND,
            source_column="search_spend_raw",
            unit=UNIT_MONETARY,
            currency="GBP",
        ),
        SearchObjectDefinition(
            search_object_id="obj_delivery",
            search_role=SEARCH_ROLE_PAID_DELIVERY,
            source_column="search_delivery_raw",
            unit=UNIT_EXPOSURE_COUNT,
        ),
    ]
    fit_inputs = CandidateASearchFitInputs(
        spec=spec,
        demand_channel_names=list(scenario.demand_channel_names),
        paid_search_delivery=delivery_obs,
        paid_search_cap=cap,
        organic_search_capture=organic_obs,
        direct_navigation_capture=direct_obs,
        search_objects=search_objects,
    )

    nodes = [
        CausalNode(node_id=name, role=NODE_ROLE_INTERVENTION) for name in channel_names
    ]
    nodes += [
        CausalNode(node_id="fh_outcome", role=NODE_ROLE_OUTCOME),
        CausalNode(
            node_id="demand_node",
            role=NODE_ROLE_DEMAND_CAPTURE,
            search_object_id="obj_demand",
        ),
        CausalNode(
            node_id="cap_node",
            role=NODE_ROLE_CAPACITY_OR_CAP,
            search_object_id="obj_cap",
        ),
        CausalNode(
            node_id="organic_node",
            role=NODE_ROLE_DEMAND_CAPTURE,
            search_object_id="obj_organic",
        ),
        CausalNode(
            node_id="direct_node",
            role=NODE_ROLE_DEMAND_CAPTURE,
            search_object_id="obj_direct",
        ),
    ]
    edges = [
        CausalEdge(name, "fh_outcome", role=EDGE_ROLE_DIRECT) for name in channel_names
    ]
    edges += [
        CausalEdge(name, "demand_node", role=EDGE_ROLE_MEDIATED)
        for name in scenario.demand_channel_names
    ]
    edges += [
        CausalEdge("demand_node", "fh_outcome", role=EDGE_ROLE_MEDIATED),
        CausalEdge("demand_node", "cap_node", role=EDGE_ROLE_CAPACITY_CONSTRAINED),
        CausalEdge("organic_node", "fh_outcome", role=EDGE_ROLE_DIRECT),
        CausalEdge("direct_node", "fh_outcome", role=EDGE_ROLE_DIRECT),
    ]
    graph = CausalGraph(
        graph_id=f"synthetic_{scenario.name}",
        nodes=nodes,
        edges=edges,
        status=GRAPH_STATUS_APPROVED,
    )

    ground_truth = {
        "search_demand_intercept": truth.demand_intercept,
        "search_paid_capture_outcome_beta": truth.beta_paid_capture,
        "search_organic_capture_outcome_beta": truth.beta_organic_capture,
        "search_direct_navigation_capture_outcome_beta": truth.beta_direct_capture,
        "capture_share_paid": truth.capture_share_paid,
        "capture_share_organic": truth.capture_share_organic,
        "capture_share_direct": truth.capture_share_direct,
        "mean_unmet_demand": float(np.mean(unmet_demand)),
        "mean_latent_demand": float(np.mean(latent_demand)),
        "cap_binding_rate": float(np.mean(np.isclose(realised_paid, cap, rtol=1e-6))),
    }
    for channel in channels:
        ground_truth[f"demand_beta[{channel.name}]"] = channel.demand_beta
        ground_truth[f"direct_beta[{channel.name}]"] = channel.direct_beta

    return CandidateASyntheticData(
        frame=frame,
        fit_inputs=fit_inputs,
        graph=graph,
        search_objects=search_objects,
        ground_truth=ground_truth,
    )


def default_recovery_scenarios() -> List[CandidateARecoveryScenario]:
    """A representative, not exhaustive, scenario matrix - covers a
    mediated-only channel, a direct-only channel, a channel with both, and
    the three cap regimes. `generate_candidate_a_synthetic_data` supports a
    wider parameter space (multi-market, custom noise/variation) than this
    default set exercises; see test_search_candidate_a_recovery.py for
    which of these are actually fit in CI vs scheduled-only."""

    mediated_only = ChannelTruth(
        name="SearchBrand",
        decay_rate=0.3,
        hill_K=600.0,
        hill_S=1.3,
        direct_beta=0.0,
        demand_beta=0.5,
    )
    direct_only = ChannelTruth(
        name="TV",
        decay_rate=0.5,
        hill_K=900.0,
        hill_S=1.5,
        direct_beta=0.12,
        demand_beta=0.0,
    )
    both = ChannelTruth(
        name="Social",
        decay_rate=0.2,
        hill_K=400.0,
        hill_S=1.1,
        direct_beta=0.05,
        demand_beta=0.25,
    )

    scenarios = []
    for regime in CAP_REGIMES:
        scenarios.append(
            CandidateARecoveryScenario(
                name=f"mixed_channels_{regime}",
                channels=[mediated_only, direct_only, both],
                demand_channel_names=["SearchBrand", "TV", "Social"],
                cap_regime=regime,
                seed=hash(regime) % 1000,
            )
        )
    scenarios.append(
        CandidateARecoveryScenario(
            name="multi_market_sometimes_binds",
            channels=[mediated_only, direct_only],
            demand_channel_names=["SearchBrand", "TV"],
            n_markets=2,
            n_periods=80,
            cap_regime=CAP_REGIME_SOMETIMES_BINDS,
            seed=7,
        )
    )
    return scenarios


__all__ = [
    "CANDIDATE_A_RECOVERY_POLICY",
    "CAP_REGIMES",
    "CAP_REGIME_FREQUENTLY_BINDS",
    "CAP_REGIME_NEVER_BINDS",
    "CAP_REGIME_SOMETIMES_BINDS",
    "CandidateARecoveryPolicy",
    "CandidateARecoveryScenario",
    "CandidateARecoveryTruth",
    "CandidateASyntheticData",
    "ChannelTruth",
    "default_recovery_scenarios",
    "generate_candidate_a_synthetic_data",
]
