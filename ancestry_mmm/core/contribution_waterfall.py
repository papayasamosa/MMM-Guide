"""Period-over-period contribution waterfall (WP2F implementation),
following `docs/wp2f_contribution_waterfall_design_note.md`'s
**authoritative** Section 13.3 refinement of Section 5.2 - not Section
5.2's original player list, which Section 13.3 itself supersedes.

Generalises `core.attribution.compute_shapley_contributions`'s
already-shipped, already-tested channel-only Shapley decomposition to
the model's genuinely time-varying additive `eta` terms - trend,
season, promotions, controls, and each channel's existing combined
direct+halo term - Shapley-decomposed exactly as that function already
does. `intercept` and `market` are fused into one shared,
period-invariant reference point (`mu_reference = exp(intercept +
eta_market)`) rather than being separate Shapley players, exactly as
Section 13.3 specifies: a shared reference cannot, by definition,
contribute to the difference between two evaluations that both start
from it.

**Implementation-time correction beyond the design note:** Section
13.3's own worked proof (and Section 4/9/11's original claim) implicitly
assumes Period A and Period B cover the same number of weeks. Numerical
verification during implementation (see `test_contribution_waterfall.py
::TestComputeContributionWaterfallBridge::
test_reconciliation_holds_with_unequal_period_lengths`) showed that
whenever `mu_reference` is excluded from the bridge sum entirely, the
reconciliation invariant (Section 8) fails by exactly `(n_B_weeks -
n_A_weeks) * mu_reference` for an unequal-length comparison - the
"extra" (or "missing") weeks' worth of reference-level outcome is real
and was not being accounted for anywhere. This module therefore keeps
`mu_reference` as its own explicit, always-computed **`baseline`**
bridge component (`contribution = mu_reference` per row, not
Shapley-split, since it is common to every permutation before any
player is inserted) rather than discarding it - this is a strictly more
complete implementation of the same design intent (Section 5.3: "which
components are required for exact reconciliation" is exactly the kind
of technical determination a design note - or, here, evidence gathered
while implementing one - is authorised to resolve). For an equal-length
comparison `baseline`'s bridge is exactly zero, recovering Section
4/9/11's original claim exactly; for an unequal-length comparison it is
the honest, non-zero "this period simply covers a different number of
weeks" component, which is real information, not noise - so it is
never hidden from the presented chart, only naturally sorted alongside
every other component by magnitude (Section 9).

Per Section 10, the bridge is built entirely on `mu` (posterior
expected outcome) - never on raw observed `Y` or posterior-predictive
draws, both of which would force an undecomposable sampling-noise
residual into the decomposition.

Per Section 12, this module reads `eta_trend`/`eta_season`/
`eta_promo`/`eta_controls`/`eta_market`/`intercept` directly from
`trace.posterior` by name (mirroring `core.predict.
extract_posterior_params`'s per-draw extraction pattern) rather than
recomputing them via a NumPy replay, and fails closed with a specific,
named error if any expected Deterministic is absent - e.g. a bundle
saved under an older schema/pytensor version - never silently omitting
a component from the reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .attribution import CandidateAAttributionNotSupportedError, _channel_log_terms
from .hierarchical_model import FHModelMeta
from .outcome_valuation_reporting import resolve_market_week_row_indices
from .predict import FHPosteriorParams, extract_posterior_params
from .search_capacity import SEARCH_CANDIDATE_A_ENGINE
from .uncertainty import (
    DEFAULT_CRED_MASS,
    DEFAULT_N_DRAWS,
    sample_draw_indices,
    summarize_distribution,
)

DEFAULT_WATERFALL_N_PERMUTATIONS = 20

BASELINE_COMPONENT = "baseline"

# Section 3: the exhaustive, non-channel additive eta terms. `intercept`
# is a free RV (dims="outcome" only, no "obs" dim); the other five are
# `pm.Deterministic`s already shaped (obs, outcome) in the fitted model
# (`core/hierarchical_model.py`).
REQUIRED_GENERALISED_ETA_VARS: Tuple[str, ...] = (
    "intercept",
    "eta_market",
    "eta_trend",
    "eta_season",
    "eta_promo",
    "eta_controls",
)

# Section 5.2's original terms that Section 13.3 fuses into the shared
# `mu_reference` starting point instead of Shapley-decomposing separately.
_REFERENCE_TERMS = ("intercept", "market")

# The genuinely time-varying structural terms Section 13.3 Shapley-decomposes.
_DECOMPOSED_STRUCTURAL_TERMS = ("trend", "season", "promo", "controls")


class MissingGeneralisedEtaComponentError(ValueError):
    """Raised when a fitted model's trace is missing one of the named
    posterior Deterministics the generalised Shapley decomposition
    requires (Section 12) - e.g. a bundle saved under an older schema/
    pytensor version. Fail closed: never silently omit a component from
    the reconciliation."""


def _verify_generalised_eta_components_present(trace) -> None:
    missing = [v for v in REQUIRED_GENERALISED_ETA_VARS if v not in trace.posterior]
    if missing:
        raise MissingGeneralisedEtaComponentError(
            "This fitted model's trace is missing the following posterior "
            f"Deterministic(s) required for the generalised Shapley "
            f"contribution waterfall: {missing}. The waterfall cannot be "
            "computed without fabricating a missing component."
        )


def extract_generalised_eta_terms(
    trace,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    at: Optional[tuple] = None,
) -> Dict[str, np.ndarray]:
    """The five non-channel structural eta terms, each shape
    `(n_obs, n_outcomes)`, at one posterior draw (`at=(chain, draw)`) or
    the posterior mean (`at=None`) - mirrors `extract_posterior_params`'s
    own per-draw extraction pattern (Section 14).

    `intercept`'s value is read via `params.intercept` (already the
    exact same `trace.posterior["intercept"]` value `extract_posterior_
    params` extracts for this identical `at`) rather than a second,
    redundant direct read - same source, same draw, one calculation
    path. Its *presence* in the trace is still explicitly verified here
    (`_verify_generalised_eta_components_present`), independent of
    whichever function later reads its value.
    """
    _verify_generalised_eta_components_present(trace)
    post = trace.posterior

    def _read(var: str) -> np.ndarray:
        da = post[var]
        if at is not None:
            return np.asarray(da.isel(chain=at[0], draw=at[1]).values)
        return np.asarray(da.mean(dim=["chain", "draw"]).values)

    eta_market = _read("eta_market")
    n_obs = eta_market.shape[0]
    intercept_vec = np.array([params.intercept[s] for s in meta.outcome_ids])

    return {
        "intercept": np.broadcast_to(
            intercept_vec[None, :], (n_obs, len(meta.outcome_ids))
        ).copy(),
        "market": eta_market,
        "trend": _read("eta_trend"),
        "season": _read("eta_season"),
        "promo": _read("eta_promo"),
        "controls": _read("eta_controls"),
    }


def compute_generalised_shapley_contributions(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    trace,
    at: Optional[tuple] = None,
    n_permutations: int = DEFAULT_WATERFALL_N_PERMUTATIONS,
    seed: int = 42,
    purpose: str = "attribution",
) -> Dict:
    """Generalised Shapley decomposition (Section 13.3's authoritative
    refinement of Section 5.2): `trend`, `season`, `promo`, `controls`,
    and each channel are co-equal Shapley players, starting from the
    shared, period-invariant reference `mu_reference = exp(intercept +
    eta_market)` - not `intercept`/`market` as separate players, and not
    `mu = 1`.

    A **new**, separate function from `core.attribution.
    compute_shapley_contributions` (Section 14) - that function, its
    existing callers, and its `mu_baseline`-anchored reference are left
    completely unchanged.

    Returns `{"contributions": {player: (n_obs, n_outcomes) array},
    "mu_reference": (n_obs, n_outcomes), "mu_total": (n_obs,
    n_outcomes), "players": [...], "outcome_ids": [...]}`, where
    `"players"` includes `"baseline"` (the reference itself, exposed as
    its own component - see this module's docstring for why) alongside
    `trend`/`season`/`promo`/`controls`/channels. `mu_reference +
    sum(contributions[p] for p in players if p != "baseline") ==
    mu_total` exactly, regardless of `n_permutations` (Section 8) - the
    same telescoping-sum guarantee `compute_shapley_contributions`
    already relies on, applied to this player list.
    """
    if meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
        raise CandidateAAttributionNotSupportedError(
            "compute_generalised_shapley_contributions does not yet "
            "represent Candidate A's search-mediated pathway - see "
            "docs/wp2f_contribution_waterfall_design_note.md Section 1."
        )
    structural_terms = extract_generalised_eta_terms(trace, meta, params, at=at)
    channel_terms = _channel_log_terms(frame, meta, params, purpose=purpose)

    reference_eta = structural_terms["intercept"] + structural_terms["market"]
    mu_reference = np.exp(np.clip(reference_eta, -50, 50))

    decomposed_terms: Dict[str, np.ndarray] = {
        name: structural_terms[name] for name in _DECOMPOSED_STRUCTURAL_TERMS
    }
    decomposed_terms.update(channel_terms)
    players: List[str] = list(_DECOMPOSED_STRUCTURAL_TERMS) + list(meta.channels)

    n_obs, n_out = mu_reference.shape
    rng = np.random.default_rng(seed)
    contributions = {p: np.zeros((n_obs, n_out)) for p in players}
    for _ in range(n_permutations):
        order = rng.permutation(np.array(players, dtype=object))
        current = mu_reference.copy()
        for p in order:
            new = current * np.exp(np.clip(decomposed_terms[p], -50, 50))
            contributions[p] += new - current
            current = new
    for p in players:
        contributions[p] /= n_permutations

    # The reference itself, exposed as its own component (this module's
    # docstring: required for exact reconciliation across unequal-length
    # periods, not a Shapley split of anything).
    contributions[BASELINE_COMPONENT] = mu_reference
    players = [BASELINE_COMPONENT] + players

    mu_total = mu_reference.copy()
    for p in players:
        if p == BASELINE_COMPONENT:
            continue
        mu_total = mu_total + contributions[p]

    return {
        "contributions": contributions,
        "mu_reference": mu_reference,
        "mu_total": mu_total,
        "players": players,
        "outcome_ids": meta.outcome_ids,
    }


@dataclass(frozen=True)
class ContributionBridgeComponent:
    """One player's Period A -> Period B bridge contribution, with
    posterior uncertainty. Every component is presentable (Section
    13.3's fused reference removes the need for an excluded-but-
    computed "always zero" category) - `"baseline"`'s bridge is exactly
    zero for an equal-length period comparison and non-zero (honestly)
    for an unequal-length one."""

    component: str
    period_a_mean: float
    period_b_mean: float
    bridge_mean: float
    bridge_median: float
    bridge_lower: float
    bridge_upper: float


@dataclass(frozen=True)
class ContributionWaterfallBridge:
    """The full period-over-period contribution waterfall (WP2F),
    posterior-uncertainty-aware. `components` sums exactly to
    `period_b_outcome_mean - period_a_outcome_mean` (Section 8) -
    every component is presentable, none is silently excluded."""

    market: str
    outcome_ids: Tuple[str, ...]
    period_a_weeks: Tuple[str, ...]
    period_b_weeks: Tuple[str, ...]
    period_a_outcome_mean: float
    period_b_outcome_mean: float
    components: Tuple[ContributionBridgeComponent, ...]
    reconciliation_error_mean: float
    credible_mass: float
    n_draws: int


def sorted_presented_components(
    components: Sequence[ContributionBridgeComponent],
) -> List[ContributionBridgeComponent]:
    """Section 9's recommended presentation order: positive bridge
    contributions descending by magnitude (largest boost, leftmost),
    then negative contributions ascending by magnitude (smallest drag
    first, largest drag rightmost). Purely cosmetic - reordering never
    changes reconciliation, since addition is commutative."""
    positive = sorted(
        (c for c in components if c.bridge_mean >= 0),
        key=lambda c: c.bridge_mean,
        reverse=True,
    )
    negative = sorted(
        (c for c in components if c.bridge_mean < 0),
        key=lambda c: c.bridge_mean,
        reverse=True,
    )
    return positive + negative


def compute_contribution_waterfall_bridge(
    trace,
    frame: Dict,
    meta: FHModelMeta,
    *,
    market: str,
    outcome_ids: Sequence[str],
    period_a_weeks: Sequence[str],
    period_b_weeks: Sequence[str],
    n_draws: int = DEFAULT_N_DRAWS,
    n_permutations: int = DEFAULT_WATERFALL_N_PERMUTATIONS,
    seed: int = 42,
    credible_mass: float = DEFAULT_CRED_MASS,
    purpose: str = "attribution",
) -> ContributionWaterfallBridge:
    """The full WP2F bridge: Period A's outcome, every component's
    Period A -> Period B delta with posterior uncertainty, and Period
    B's outcome - reconciling exactly (Section 8) for every posterior
    draw, for equal- or unequal-length periods alike.

    Reuses `core.outcome_valuation_reporting.
    resolve_market_week_row_indices` for the identical week -> frame-row
    lookup WP2D-ui/WP2E already use - one lookup path. Fails closed
    (raises) if either period's weeks are not fully covered by this
    market's fitted rows, or if an unknown outcome_id/market is
    requested, exactly like that function.
    """
    if not outcome_ids:
        raise ValueError("No outcome_ids supplied - cannot select a reporting slice.")
    unknown_outcomes = sorted(set(outcome_ids) - set(meta.outcome_ids))
    if unknown_outcomes:
        raise ValueError(
            f"outcome_id(s) {unknown_outcomes} are not part of this fit's "
            f"outcome_ids {list(meta.outcome_ids)}."
        )
    row_indices_a = resolve_market_week_row_indices(frame, meta, market, period_a_weeks)
    row_indices_b = resolve_market_week_row_indices(frame, meta, market, period_b_weeks)
    outcome_col_indices = [meta.outcome_ids.index(oid) for oid in outcome_ids]

    def _period_total(row_indices: List[int], arr: np.ndarray) -> float:
        return float(arr[np.ix_(row_indices, outcome_col_indices)].sum())

    draw_indices = sample_draw_indices(trace, n_draws, seed)
    outcome_a_draws: List[float] = []
    outcome_b_draws: List[float] = []
    reconciliation_error_draws: List[float] = []
    bridge_draws: Dict[str, List[float]] = {}
    period_a_draws: Dict[str, List[float]] = {}
    period_b_draws: Dict[str, List[float]] = {}
    players: List[str] = []

    for draw_index in draw_indices:
        params = extract_posterior_params(trace, meta, at=draw_index)
        result = compute_generalised_shapley_contributions(
            frame,
            meta,
            params,
            trace,
            at=draw_index,
            n_permutations=n_permutations,
            seed=seed,
            purpose=purpose,
        )
        contributions = result["contributions"]
        mu_total = result["mu_total"]
        players = result["players"]

        outcome_a = _period_total(row_indices_a, mu_total)
        outcome_b = _period_total(row_indices_b, mu_total)
        outcome_a_draws.append(outcome_a)
        outcome_b_draws.append(outcome_b)

        bridge_sum = 0.0
        for p in players:
            contrib_a = _period_total(row_indices_a, contributions[p])
            contrib_b = _period_total(row_indices_b, contributions[p])
            delta = contrib_b - contrib_a
            bridge_draws.setdefault(p, []).append(delta)
            period_a_draws.setdefault(p, []).append(contrib_a)
            period_b_draws.setdefault(p, []).append(contrib_b)
            bridge_sum += delta
        reconciliation_error_draws.append((outcome_b - outcome_a) - bridge_sum)

    components = []
    for p in players:
        bridge_summary = summarize_distribution(
            np.array(bridge_draws[p]), cred_mass=credible_mass
        )
        components.append(
            ContributionBridgeComponent(
                component=p,
                period_a_mean=float(np.mean(period_a_draws[p])),
                period_b_mean=float(np.mean(period_b_draws[p])),
                bridge_mean=bridge_summary["mean"],
                bridge_median=bridge_summary["median"],
                bridge_lower=bridge_summary["lower"],
                bridge_upper=bridge_summary["upper"],
            )
        )

    return ContributionWaterfallBridge(
        market=market,
        outcome_ids=tuple(outcome_ids),
        period_a_weeks=tuple(period_a_weeks),
        period_b_weeks=tuple(period_b_weeks),
        period_a_outcome_mean=float(np.mean(outcome_a_draws)),
        period_b_outcome_mean=float(np.mean(outcome_b_draws)),
        components=tuple(components),
        reconciliation_error_mean=float(np.mean(reconciliation_error_draws)),
        credible_mass=credible_mass,
        n_draws=len(draw_indices),
    )
