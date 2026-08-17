"""
Sequential (weekly, state-transition) simulation kernel.

WP5 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`). This module
sits alongside - it never replaces - the existing steady-state planner
(`core.optimization`, `core.predict.steady_state_outcome_response`,
`core.market_specific_predict.steady_state_outcome_response_market_specific`).
See `core/AGENTS.md`'s "Steady-state versus sequential" section: steady-
state curves and planner outputs must never be used to answer 0-3 month
response, 3-12 month response, terminal carryover, or month-by-month
optimisation - those require sequential impulse-response simulation, which
is what this module provides. `core.planning.value.
SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS` is this engine's own
truthful governance disclosure, parallel to (never instead of)
`CURRENT_PLANNING_EVALUATION_SEMANTICS` (steady-state monthly).

Upstream reference (AGENTS.md's required upstream-reference workflow):
`pymc-labs/pymc-marketing` 0.18.1's `GeometricAdstock` uses a *finite*
`l_max`-truncated convolution (typical `l_max` 6-8 for weekly data), and its
own forward-simulation notebooks
(`mmm_brand_metrics_long_term.ipynb`, `mmm_budget_allocation_example.ipynb`)
prime that finite window by prepending `l_max` extra "warm-up" periods into
the same array, rather than passing an explicit carry-in state. This
repo's `core.transformations.geometric_adstock` is a genuinely infinite-
horizon recursive filter (`adstock[t] = x[t] + decay*adstock[t-1]`,
`normalize=True`) - not `l_max`-windowed - a pre-existing, already-
documented divergence from PyMC Marketing's `GeometricAdstock` (not
introduced by this work package: `build_fh_hierarchical_model` has no
`l_max` at all). Reproducing upstream's "prepend warm-up periods" pattern
here would silently truncate the decay to a finite window, diverging from
what was actually fit. The correct carry-in mechanism for this repo's own
infinite-horizon recursion is therefore an explicit starting-state scalar
carried through the exact same recursive formula already used at fit time
and in `core.predict`'s NumPy replay - see
`transformations.geometric_adstock`'s `initial_state` parameter - not a
warm-up-window prepend. Equivalence with today's zero-start behaviour, and
with the existing batch replay, is tested directly (see
`test_sequential_simulation.py` and `TestGeometricAdstockInitialState` in
`test_transformations.py`).

Design: this kernel reuses the existing adstock/saturation/prediction
mathematics rather than creating a parallel implementation (AGENTS.md).
The only genuinely new primitive is `_simulate_sat_media_sequence`, a
carry-in-seeded call to the *same* `geometric_adstock_matrix`/
`hill_function` transformations `core.predict.adstock_saturate_frame`
already uses. Once the future weeks' `sat_media` is computed, the non-
media eta terms (baseline, market, trend, seasonality, promotions,
controls) and the direct/cross-product pathway-masked combination are
delegated straight to `core.predict.predict_mu`/
`core.market_specific_predict.predict_mu_market_specific` via their new
`precomputed_sat_media` parameter - so this module can never silently
diverge from what those already-tested functions compute for every non-
adstock term.

Candidate A Search (WP3 boundary, unchanged): `simulate_sequential_outcomes`
raises `CandidateAReplayNotSupportedError` for a Candidate A engine fit,
exactly like `predict_mu` - the outcome-level replay still has no
representation for `search_eta_contribution`, and wiring one in is a
genuine unresolved modelling design question (REPO_REVIEW_AND_NEXT_STEPS.md,
Work Package 3 entry), not a mechanical extension in scope here. What WP5
*does* add is a bounded, explicitly diagnostic-only capability the brief
calls for: `simulate_candidate_a_mediator_state_sequentially` replays the
demand/capture/cap chain (not the final outcome) week by week for a
hypothetical plan, reusing `core.search_capacity.candidate_a_forward`
directly. This grants no planning or optimisation eligibility - Search
planning eligibility remains governed separately
(`core.search_capacity.candidate_a_use_gate`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .hierarchical_model import FHModelMeta
from .market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    predict_mu_market_specific,
)
from .planning.value import AdstockState
from .predict import (
    CandidateAReplayNotSupportedError,
    FHPosteriorParams,
    predict_mu,
)
from .search_capacity import (
    SEARCH_CANDIDATE_A_ENGINE,
    CandidateAForwardState,
    CandidateASequentialDrawParams,
    candidate_a_forward,
)
from .transformations import geometric_adstock_matrix, hill_function
from .uncertainty import DEFAULT_N_DRAWS, sample_draw_indices


# ---------------------------------------------------------------------------
# Carry-in state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SequentialCarryInState:
    """One market's starting (or, after a run, ending) state for a
    sequential weekly simulation.

    `starting_adstock` is the "fitted adstock state" the brief's State
    section requires: the RAW (pre-`normalize`) geometric-adstock
    accumulator value per channel - the same internal quantity
    `core.transformations.geometric_adstock` already carries between
    periods, just made an explicit, inspectable, carry-in-able value
    instead of always starting at zero.

    `lag_context_sat_media` is the "historical carry-in media state" the
    brief's State section separately requires: the real historical
    adstocked-and-saturated media tail (`lag_context_length` periods,
    channel-ordered) needed to serve the cross-product/halo lag term
    (`core.predict.lag_frame`) for the first few weeks of a plan horizon -
    without it, those weeks would see a lag_frame zero-pad exactly as if
    the market's history began at the plan horizon, which is precisely the
    "do not assume zero" carry-in violation the brief prohibits.
    """

    market: str
    channels: Tuple[str, ...]
    starting_adstock: Dict[str, float]
    lag_context_sat_media: np.ndarray  # (lag_context_length, n_channels)
    lag_context_length: int
    as_of_period_label: str = ""
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "channels": list(self.channels),
            "starting_adstock": dict(self.starting_adstock),
            "lag_context_sat_media": self.lag_context_sat_media.tolist(),
            "lag_context_length": self.lag_context_length,
            "as_of_period_label": self.as_of_period_label,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SequentialCarryInState":
        channels = list(d.get("channels", []))
        return cls(
            market=d.get("market", ""),
            channels=tuple(channels),
            starting_adstock=dict(d.get("starting_adstock", {})),
            lag_context_sat_media=np.array(
                d.get("lag_context_sat_media", np.zeros((0, len(channels))))
            ),
            lag_context_length=int(d.get("lag_context_length", 0)),
            as_of_period_label=d.get("as_of_period_label", ""),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_adstock_state(
        self, terminal: Optional["SequentialCarryInState"] = None
    ) -> AdstockState:
        """Project this (starting) state, and an optional ending/terminal
        carry-in state from a later `simulate_sequential_outcomes` call,
        down to `core.planning.value.AdstockState`'s existing governance-
        disclosure shape (channel -> float pairs only, no lag-context
        buffer) - reusing the value object PR 72F/82E already defined for
        exactly this purpose (`AdstockState` was kept, unused, anticipating
        this) rather than inventing a second one."""
        return AdstockState(
            channel_adstock_start=tuple(sorted(self.starting_adstock.items())),
            channel_adstock_terminal=(
                tuple(sorted(terminal.starting_adstock.items())) if terminal else ()
            ),
            as_of_date=self.as_of_period_label,
        )


def _max_cross_product_lag_weeks(meta: FHModelMeta) -> int:
    """Max `lag_for_component()` over every active/exploratory cross-
    product cell - `0` if this fit has no cross-product/halo pathway at
    all."""
    masks = meta.resolved_pathway_masks
    cells = masks.active_cells(
        meta.outcome_ids, meta.channels
    ) + masks.exploratory_cells(meta.outcome_ids, meta.channels)
    if not cells:
        return 0
    return max(
        masks.lag_for_component(meta.outcome_ids[oi], meta.channels[ci])
        for oi, ci in cells
    )


def _resolve_and_validate_market_history(
    historical_frame: Dict[str, Any], meta: FHModelMeta, market: str
) -> Tuple[int, int]:
    """Safely resolve `market`'s own historical-row slice from a full
    production-style frame, and fail closed on malformed frame metadata
    rather than silently reconstructing carry-in state from another
    market's history (WP3, brief §9.6 - "Historical-state safety"). An
    unchecked `market_bounds[meta.markets.index(market)]` lookup (the
    kernel's pre-WP3 behaviour) could raise an unhelpful `IndexError` on a
    too-short `market_bounds`, silently read past the end of `X_media` on
    an out-of-range bound, or - the genuinely dangerous case - return a
    slice whose rows do not actually all belong to `market` if
    `market_bounds` and `market_idx` disagree, which would leak another
    market's history into this carry-in reconstruction without any error
    at all."""
    if market not in meta.markets:
        raise ValueError(
            f"'{market}' is not one of this model's markets: {meta.markets}"
        )
    market_pos = meta.markets.index(market)

    market_bounds = historical_frame.get("market_bounds")
    if market_bounds is None or len(market_bounds) != len(meta.markets):
        got = 0 if market_bounds is None else len(market_bounds)
        raise ValueError(
            "historical_frame['market_bounds'] must have exactly one "
            f"(start, end) entry per this fit's market ({len(meta.markets)} "
            f"expected, for markets {list(meta.markets)}), got {got}."
        )
    start, end = market_bounds[market_pos]

    X_media = historical_frame.get("X_media")
    if X_media is None:
        raise ValueError("historical_frame['X_media'] is required.")
    n_rows = len(X_media)
    if not (0 <= start <= end <= n_rows):
        raise ValueError(
            f"historical_frame['market_bounds'][{market_pos}] = ({start}, "
            f"{end}) is not a valid slice of X_media ({n_rows} rows) for "
            f"market {market!r}."
        )

    market_idx = historical_frame.get("market_idx")
    if market_idx is None or len(market_idx) != n_rows:
        raise ValueError(
            "historical_frame['market_idx'] must have exactly one entry per "
            "X_media row."
        )
    block = np.asarray(market_idx[start:end])
    if block.size > 0 and not np.all(block == market_pos):
        raise ValueError(
            f"historical_frame['market_bounds'][{market_pos}] for market "
            f"{market!r} does not correspond to rows whose market_idx is "
            f"consistently {market_pos} - this frame's market_bounds/"
            "market_idx metadata is inconsistent, which would otherwise "
            "leak another market's history into this market's carry-in "
            "reconstruction. Refusing to proceed."
        )
    return int(start), int(end)


def _reconstruct_starting_state(
    historical_frame: Dict[str, Any],
    meta: FHModelMeta,
    market: str,
    as_of_period_label: str,
    *,
    decay: np.ndarray,
    K: np.ndarray,
    S: np.ndarray,
) -> SequentialCarryInState:
    start, end = _resolve_and_validate_market_history(historical_frame, meta, market)
    X_hist = historical_frame["X_media"][start:end]

    # Reconstruct starting adstock from the actual historical media
    # immediately before the plan horizon - never assumed zero, never
    # assumed steady state (the brief's explicit prohibition): this is the
    # real recursion (normalize=False keeps the raw accumulator) over this
    # market's own full observed history, matching market_bounds' existing
    # "never let carryover cross market boundaries" scoping exactly.
    raw_adstock = geometric_adstock_matrix(X_hist, decay, normalize=False)
    starting_adstock = {
        c: float(raw_adstock[-1, j]) for j, c in enumerate(meta.channels)
    }

    lag_context_length = _max_cross_product_lag_weeks(meta)
    if lag_context_length > 0 and X_hist.shape[0] > 0:
        sat_hist = hill_function(raw_adstock * (1 - decay)[None, :], K, S)
        tail_len = min(lag_context_length, sat_hist.shape[0])
        lag_context_sat_media = sat_hist[-tail_len:]
        if tail_len < lag_context_length:
            pad = np.zeros((lag_context_length - tail_len, len(meta.channels)))
            lag_context_sat_media = np.concatenate([pad, lag_context_sat_media], axis=0)
    else:
        lag_context_sat_media = np.zeros((lag_context_length, len(meta.channels)))

    return SequentialCarryInState(
        market=market,
        channels=tuple(meta.channels),
        starting_adstock=starting_adstock,
        lag_context_sat_media=lag_context_sat_media,
        lag_context_length=lag_context_length,
        as_of_period_label=as_of_period_label,
    )


def reconstruct_starting_state(
    historical_frame: Dict[str, Any],
    meta: FHModelMeta,
    params: FHPosteriorParams,
    market: str,
    as_of_period_label: str = "",
) -> SequentialCarryInState:
    """Model A (shared) starting-state reconstruction - see
    `SequentialCarryInState`.

    `historical_frame` must be a full production-style frame (every market
    the fit covers, `market_bounds[i]` the contiguous block for
    `meta.markets[i]`) - the same `market_bounds`-ordered-like-`meta.markets`
    convention `core.predict.predict_mu` already relies on via `market_idx`.
    A frame containing only `market`'s own rows at a `market_bounds` index
    other than `meta.markets.index(market)` will look up the wrong block.
    """
    decay = np.array([params.decay_rate[c] for c in meta.channels])
    K = np.array([params.hill_K[c] for c in meta.channels])
    S = np.array([params.hill_S[c] for c in meta.channels])
    return _reconstruct_starting_state(
        historical_frame, meta, market, as_of_period_label, decay=decay, K=K, S=S
    )


def reconstruct_starting_state_market_specific(
    historical_frame: Dict[str, Any],
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
    market: str,
    as_of_period_label: str = "",
) -> SequentialCarryInState:
    """Model C (market-specific) starting-state reconstruction - same
    contract as `reconstruct_starting_state` (including its `historical_frame`
    market_bounds-ordering requirement), using this market's own `hill_K`
    (market-specific channels of `FHMarketSpecificPosteriorParams` are
    indexed by market; `decay_rate`/`hill_S` stay shared, matching Model
    C's own structure everywhere else)."""
    decay = np.array([params.decay_rate[c] for c in meta.channels])
    K = np.array([params.hill_K[market][c] for c in meta.channels])
    S = np.array([params.hill_S[c] for c in meta.channels])
    return _reconstruct_starting_state(
        historical_frame, meta, market, as_of_period_label, decay=decay, K=K, S=S
    )


# ---------------------------------------------------------------------------
# Weekly plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WeeklyPlan:
    """An explicit weekly media plan for one market.

    WP5 takes this as input; it never decides how a coarser (e.g. monthly)
    plan spreads across weeks - that phasing decision is WP6's scope
    (`core.sequential_simulation` does not hide a monthly-to-weekly
    allocation assumption inside the mathematical kernel).

    `media_by_channel` must have an entry for every one of the fit's
    channels (model-input units, not spend - see `core/AGENTS.md`'s media-
    input-versus-monetary-spend rule) - a plan is explicit, not partial
    with an invented default for an unmentioned channel.
    """

    market: str
    period_labels: Tuple[str, ...]
    media_by_channel: Dict[str, np.ndarray]
    promo: np.ndarray  # (n_weeks, n_outcomes)
    trend: np.ndarray  # (n_weeks,)
    fourier: np.ndarray  # (n_weeks, n_fourier)
    control_names: Tuple[str, ...] = ()
    X_controls: Optional[np.ndarray] = None  # (n_weeks, len(control_names))
    outcome_controls: Dict[str, np.ndarray] = field(default_factory=dict)
    outcome_control_names: Dict[str, List[str]] = field(default_factory=dict)
    # Diagnostic-only Candidate A future cap assumption - a cap is a
    # decision/constraint, never inferred (AGENTS.md's capacity and cap
    # invariants) - see simulate_candidate_a_mediator_state_sequentially.
    candidate_a_paid_search_cap: Optional[np.ndarray] = None

    def __post_init__(self) -> None:
        n_weeks = len(self.period_labels)
        if n_weeks == 0:
            raise ValueError("WeeklyPlan requires at least one period.")
        if len(set(self.period_labels)) != n_weeks:
            raise ValueError("WeeklyPlan.period_labels must be unique.")
        for name, arr in self.media_by_channel.items():
            if len(arr) != n_weeks:
                raise ValueError(
                    f"media_by_channel[{name!r}] has length {len(arr)}, "
                    f"expected {n_weeks} (one value per period_labels entry)."
                )
        if self.promo.shape[0] != n_weeks:
            raise ValueError("WeeklyPlan.promo must have one row per period.")
        if self.trend.shape[0] != n_weeks:
            raise ValueError("WeeklyPlan.trend must have one row per period.")
        if self.fourier.shape[0] != n_weeks:
            raise ValueError("WeeklyPlan.fourier must have one row per period.")
        if self.control_names:
            expected_shape = (n_weeks, len(self.control_names))
            if (
                self.X_controls is None
                or tuple(self.X_controls.shape) != expected_shape
            ):
                raise ValueError(
                    "WeeklyPlan.X_controls must be an explicit array of shape "
                    f"{expected_shape} when control_names is non-empty."
                )
        if (
            self.candidate_a_paid_search_cap is not None
            and len(self.candidate_a_paid_search_cap) != n_weeks
        ):
            raise ValueError(
                "WeeklyPlan.candidate_a_paid_search_cap must have one value per period."
            )

    def to_media_matrix(self, channels: Sequence[str]) -> np.ndarray:
        missing = [c for c in channels if c not in self.media_by_channel]
        if missing:
            raise ValueError(
                f"WeeklyPlan is missing planned weekly media for channel(s): "
                f"{missing} - an explicit weekly plan requires every channel."
            )
        return np.column_stack(
            [np.asarray(self.media_by_channel[c], dtype=float) for c in channels]
        )


def zero_media_extension_plan(
    market: str,
    period_labels: Sequence[str],
    meta: FHModelMeta,
    n_fourier: int,
) -> WeeklyPlan:
    """The default terminal-carryover extension: zero planned media for
    every channel, zero promo/trend/seasonality/controls - "continue
    simulation beyond the formal plan window with zero ... future media".
    Pass an explicitly-built `WeeklyPlan` to `simulate_terminal_carryover`
    instead when an explicitly supplied (non-zero) future media assumption
    is required."""
    n_weeks = len(period_labels)
    return WeeklyPlan(
        market=market,
        period_labels=tuple(period_labels),
        media_by_channel={c: np.zeros(n_weeks) for c in meta.channels},
        promo=np.zeros((n_weeks, len(meta.outcome_ids))),
        trend=np.zeros(n_weeks),
        fourier=np.zeros((n_weeks, n_fourier)),
    )


def _validate_plan_matches_carry_in(
    plan: WeeklyPlan, carry_in: SequentialCarryInState, meta: FHModelMeta
) -> None:
    if plan.market != carry_in.market:
        raise ValueError(
            f"WeeklyPlan.market ({plan.market!r}) does not match the carry-in "
            f"state's market ({carry_in.market!r}) - candidate and reference "
            "runs, and any carried-forward state, must stay within one market "
            "(no carryover may cross market boundaries)."
        )
    if carry_in.channels != tuple(meta.channels):
        raise ValueError("Carry-in state's channels do not match this fit's channels.")
    if plan.market not in meta.markets:
        raise ValueError(f"'{plan.market}' is not one of this model's markets.")


# ---------------------------------------------------------------------------
# Weekly recursion
# ---------------------------------------------------------------------------


def _simulate_sat_media_sequence(
    plan: WeeklyPlan,
    carry_in: SequentialCarryInState,
    channels: Sequence[str],
    *,
    decay: np.ndarray,
    K: np.ndarray,
    S: np.ndarray,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """The one genuinely new piece of math in this module: propagate the
    carried-in adstock state, add each week's planned media, update
    adstock, apply saturation - via the *same*
    `geometric_adstock_matrix`/`hill_function` transformations
    `core.predict.adstock_saturate_frame` already uses, extended with the
    `initial_state` carry-in parameter. Returns `(sat_media, ending_adstock)`."""
    X_future = plan.to_media_matrix(channels)
    initial_state = np.array([carry_in.starting_adstock[c] for c in channels])

    raw_adstock = geometric_adstock_matrix(
        X_future, decay, normalize=False, initial_state=initial_state
    )
    sat_media = hill_function(raw_adstock * (1 - decay)[None, :], K, S)
    ending_adstock = {c: float(raw_adstock[-1, j]) for j, c in enumerate(channels)}
    return sat_media, ending_adstock


@dataclass(frozen=True)
class SequentialSimulationResult:
    """One market's weekly-recursion output over a plan horizon (or a
    terminal-carryover extension - see `simulate_terminal_carryover`)."""

    market: str
    period_labels: Tuple[str, ...]
    outcome_ids: Tuple[str, ...]
    mu: np.ndarray  # (n_weeks, n_outcomes) - final outcome through the full link
    sat_media: (
        np.ndarray
    )  # (n_weeks, n_channels) - adstocked+saturated media, for inspection
    ending_state: SequentialCarryInState  # this run's ending adstock + lag context


def _assemble_replay_frame(
    plan: WeeklyPlan,
    carry_in: SequentialCarryInState,
    meta: FHModelMeta,
    sat_media_future: np.ndarray,
    *,
    market_idx_value: int,
) -> Tuple[Dict[str, Any], np.ndarray, int]:
    """Concatenate the carry-in lag-context tail with the plan horizon so
    `core.predict.lag_frame`'s within-market-block shift can reach real
    historical `sat_media` for the cross-product/halo lag, instead of
    zero-padding the first `lag_context_length` weeks as if the market's
    history began at the plan horizon. Tail rows' non-media covariates
    (trend/season/promo/controls) are never read by anything that affects
    a future row's output - every one of `predict_mu`'s non-lag terms is
    computed independently per row - so they are filled with zeros rather
    than requiring the caller to supply real historical covariate values
    for rows this function discards before returning.

    `market_idx_value` - the single market index every row of this one-
    market replay frame should carry. This is deliberately a caller-
    supplied value rather than derived here: `predict_mu` (Model A) indexes
    `market_offset` by position in `meta.markets` (the fit's full market
    list), while `predict_mu_market_specific` (Model C) indexes it by
    position in `frame["markets"]` (a list this function's Model C caller
    sets to `[plan.market]` alone) - the same integer would be wrong for
    one of the two callers if computed with one hardcoded formula here.
    """
    tail_len = carry_in.lag_context_length
    n_weeks = len(plan.period_labels)
    n_outcomes = len(meta.outcome_ids)
    n_total = tail_len + n_weeks

    sat_media_replay = np.concatenate(
        [carry_in.lag_context_sat_media, sat_media_future], axis=0
    )

    n_fourier = plan.fourier.shape[1]
    n_controls = len(plan.control_names)

    frame: Dict[str, Any] = {
        "X_media": np.zeros(
            (n_total, len(meta.channels))
        ),  # unused: precomputed_sat_media bypasses this
        "market_bounds": [(0, n_total)],
        "market_idx": np.full(n_total, market_idx_value, dtype=int),
        "promo": np.concatenate([np.zeros((tail_len, n_outcomes)), plan.promo], axis=0),
        "trend": np.concatenate([np.zeros(tail_len), plan.trend]),
        "fourier": np.concatenate(
            [np.zeros((tail_len, n_fourier)), plan.fourier], axis=0
        ),
        "control_names": list(plan.control_names),
        "X_controls": (
            np.concatenate([np.zeros((tail_len, n_controls)), plan.X_controls], axis=0)
            if plan.control_names
            else np.zeros((n_total, 0))
        ),
        "outcome_controls": {
            oid: np.concatenate([np.zeros((tail_len,) + arr.shape[1:]), arr], axis=0)
            for oid, arr in plan.outcome_controls.items()
        },
        "outcome_control_names": dict(plan.outcome_control_names),
    }
    return frame, sat_media_replay, tail_len


def simulate_sequential_outcomes(
    plan: WeeklyPlan,
    carry_in: SequentialCarryInState,
    meta: FHModelMeta,
    params: FHPosteriorParams,
) -> SequentialSimulationResult:
    """Model A (shared) weekly recursion over `plan`'s horizon, seeded by
    `carry_in`. Raises `CandidateAReplayNotSupportedError` for a Candidate A
    engine fit - see module docstring; use
    `simulate_candidate_a_mediator_state_sequentially` for the bounded
    diagnostic mediator-state replay instead."""
    if meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
        raise CandidateAReplayNotSupportedError(
            "simulate_sequential_outcomes does not represent Candidate A's "
            "search-mediated pathway (search_eta_contribution) in the final "
            "outcome - same boundary as core.predict.predict_mu (WP3). See "
            "simulate_candidate_a_mediator_state_sequentially for the "
            "bounded diagnostic mediator-state replay."
        )
    _validate_plan_matches_carry_in(plan, carry_in, meta)

    decay = np.array([params.decay_rate[c] for c in meta.channels])
    K = np.array([params.hill_K[c] for c in meta.channels])
    S = np.array([params.hill_S[c] for c in meta.channels])
    sat_media_future, ending_adstock = _simulate_sat_media_sequence(
        plan, carry_in, meta.channels, decay=decay, K=K, S=S
    )

    replay_frame, sat_media_replay, tail_len = _assemble_replay_frame(
        plan,
        carry_in,
        meta,
        sat_media_future,
        market_idx_value=meta.markets.index(plan.market),
    )
    mu_replay = predict_mu(
        replay_frame, meta, params, precomputed_sat_media=sat_media_replay
    )
    mu_future = mu_replay[tail_len:]

    ending_state = SequentialCarryInState(
        market=carry_in.market,
        channels=carry_in.channels,
        starting_adstock=ending_adstock,
        lag_context_sat_media=(
            sat_media_replay[-tail_len:]
            if tail_len > 0
            else carry_in.lag_context_sat_media
        ),
        lag_context_length=tail_len,
        as_of_period_label=plan.period_labels[-1],
    )

    return SequentialSimulationResult(
        market=plan.market,
        period_labels=plan.period_labels,
        outcome_ids=tuple(meta.outcome_ids),
        mu=mu_future,
        sat_media=sat_media_future,
        ending_state=ending_state,
    )


def simulate_sequential_outcomes_market_specific(
    plan: WeeklyPlan,
    carry_in: SequentialCarryInState,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
) -> SequentialSimulationResult:
    """Model C (market-specific) mirror of `simulate_sequential_outcomes` -
    same contract, using this market's own `hill_K` and `predict_mu_market_specific`."""
    _validate_plan_matches_carry_in(plan, carry_in, meta)

    decay = np.array([params.decay_rate[c] for c in meta.channels])
    K = np.array([params.hill_K[plan.market][c] for c in meta.channels])
    S = np.array([params.hill_S[c] for c in meta.channels])
    sat_media_future, ending_adstock = _simulate_sat_media_sequence(
        plan, carry_in, meta.channels, decay=decay, K=K, S=S
    )

    replay_frame, sat_media_replay, tail_len = _assemble_replay_frame(
        plan, carry_in, meta, sat_media_future, market_idx_value=0
    )
    replay_frame["markets"] = [plan.market]
    mu_replay = predict_mu_market_specific(
        replay_frame, meta, params, precomputed_sat_media=sat_media_replay
    )
    mu_future = mu_replay[tail_len:]

    ending_state = SequentialCarryInState(
        market=carry_in.market,
        channels=carry_in.channels,
        starting_adstock=ending_adstock,
        lag_context_sat_media=(
            sat_media_replay[-tail_len:]
            if tail_len > 0
            else carry_in.lag_context_sat_media
        ),
        lag_context_length=tail_len,
        as_of_period_label=plan.period_labels[-1],
    )

    return SequentialSimulationResult(
        market=plan.market,
        period_labels=plan.period_labels,
        outcome_ids=tuple(meta.outcome_ids),
        mu=mu_future,
        sat_media=sat_media_future,
        ending_state=ending_state,
    )


def simulate_terminal_carryover(
    extension_plan: WeeklyPlan,
    ending_state: SequentialCarryInState,
    meta: FHModelMeta,
    params: FHPosteriorParams,
) -> SequentialSimulationResult:
    """Continue the recursion beyond the plan horizon - typically with
    `zero_media_extension_plan`'s all-zero media, or an explicitly supplied
    future media assumption in `extension_plan` - so residual response can
    be measured. Seeded from `ending_state`, the ending adstock/lag-context
    state of a prior `simulate_sequential_outcomes` call.

    Returns a SEPARATE `SequentialSimulationResult` - report it separately.
    Nothing in this module, or in `core.optimization`'s objective
    functions, folds a terminal-carryover result into an optimisation
    objective; callers must not either."""
    return simulate_sequential_outcomes(extension_plan, ending_state, meta, params)


def simulate_terminal_carryover_market_specific(
    extension_plan: WeeklyPlan,
    ending_state: SequentialCarryInState,
    meta: FHModelMeta,
    params: FHMarketSpecificPosteriorParams,
) -> SequentialSimulationResult:
    """Model C mirror of `simulate_terminal_carryover`."""
    return simulate_sequential_outcomes_market_specific(
        extension_plan, ending_state, meta, params
    )


# ---------------------------------------------------------------------------
# Candidate/reference contract
# ---------------------------------------------------------------------------


def compute_incremental_outcome(
    candidate: SequentialSimulationResult, reference: SequentialSimulationResult
) -> np.ndarray:
    """`candidate outcome - reference outcome`, shape (n_weeks, n_outcomes).

    Candidate and reference must have been evaluated with the same
    simulator and the same non-decision assumptions (this function checks
    market/period/outcome identity as a structural guard, but the deeper
    "same simulator, same non-decision assumptions" requirement is the
    caller's responsibility: pass the same `meta`/`params`/carry-in to both
    `simulate_sequential_outcomes` calls). A no-change candidate and
    reference plan must produce a result within numerical tolerance of
    zero - this is release blocking (see `test_sequential_simulation.py`'s
    `test_no_change_scenario_invariant_is_zero`).
    """
    if candidate.market != reference.market:
        raise ValueError("Candidate and reference results are for different markets.")
    if candidate.period_labels != reference.period_labels:
        raise ValueError(
            "Candidate and reference results cover different simulation periods."
        )
    if candidate.outcome_ids != reference.outcome_ids:
        raise ValueError("Candidate and reference results have different outcome_ids.")
    return candidate.mu - reference.mu


# ---------------------------------------------------------------------------
# Posterior handling
# ---------------------------------------------------------------------------


def simulate_sequential_outcomes_posterior(
    plan: WeeklyPlan,
    carry_in: SequentialCarryInState,
    trace: Any,
    meta: FHModelMeta,
    *,
    n_draws: int = DEFAULT_N_DRAWS,
    seed: int = 42,
) -> np.ndarray:
    """Every sampled posterior draw run through the FULL weekly recursion
    independently - shape (n_draws, n_weeks, n_outcomes). Deliberately
    returns the full per-draw array, not a summary: "aggregate draws before
    posterior summaries... do not add independently summarised medians"
    (AGENTS.md) means aggregation (mean/median/credible interval) is the
    caller's job, performed on this array's draw axis (0) - never inside
    this function, and never per-component before this array exists.

    Conditional on one shared `carry_in`, reused for every draw (WP3, brief
    §5.4/§9.1): this varies each draw's own decay/Hill parameters through
    the *future* recursion, but historical starting-adstock uncertainty is
    not propagated, because `carry_in` was reconstructed once (typically
    from posterior-mean parameters) rather than per draw. See
    `simulate_sequential_outcomes_posterior_draw_consistent` for the fully
    draw-consistent evaluator that reconstructs `carry_in` per draw too -
    prefer that one for an application-facing posterior-uncertainty claim.
    This fixed-carry-in function remains available as a documented,
    explicitly conditional API (e.g. for a caller that has already fixed a
    specific historical state by design, or for interactive speed)."""
    from .predict import extract_posterior_params

    draws = []
    for chain, draw in sample_draw_indices(trace, n_draws, seed):
        params = extract_posterior_params(trace, meta, at=(chain, draw))
        result = simulate_sequential_outcomes(plan, carry_in, meta, params)
        draws.append(result.mu)
    stacked: np.ndarray = np.stack(draws, axis=0)
    return stacked


def simulate_sequential_outcomes_posterior_draw_consistent(
    plan: WeeklyPlan,
    historical_frame: Dict[str, Any],
    trace: Any,
    meta: FHModelMeta,
    market: str,
    *,
    as_of_period_label: str = "",
    n_draws: int = DEFAULT_N_DRAWS,
    seed: int = 42,
) -> np.ndarray:
    """Model A (shared) fully draw-consistent posterior evaluator (WP3,
    closes `REQ-STATE-001`'s "Not yet covered" draw-consistent carry-in
    gap): for every selected posterior draw, extracts that draw's own
    parameters, reconstructs `SequentialCarryInState` from `historical_frame`
    using those SAME parameters (`reconstruct_starting_state` already
    accepts per-draw `FHPosteriorParams` - this function is the missing
    per-draw caller loop around it, not new carry-in mathematics), and only
    then evaluates the future plan - so early-horizon output reflects each
    draw's own historical adstock/saturation trajectory, not one state
    shared across every draw. Returns the same
    shape-`(n_draws, n_weeks, n_outcomes)` full per-draw array as
    `simulate_sequential_outcomes_posterior` - aggregation remains the
    caller's job, on the draw axis, after this full array exists."""
    from .predict import extract_posterior_params

    draws = []
    for chain, draw in sample_draw_indices(trace, n_draws, seed):
        params = extract_posterior_params(trace, meta, at=(chain, draw))
        carry_in = reconstruct_starting_state(
            historical_frame, meta, params, market, as_of_period_label
        )
        result = simulate_sequential_outcomes(plan, carry_in, meta, params)
        draws.append(result.mu)
    stacked: np.ndarray = np.stack(draws, axis=0)
    return stacked


def simulate_sequential_outcomes_posterior_market_specific(
    plan: WeeklyPlan,
    carry_in: SequentialCarryInState,
    trace: Any,
    meta: FHModelMeta,
    *,
    n_draws: int = DEFAULT_N_DRAWS,
    seed: int = 42,
) -> np.ndarray:
    """Model C (market-specific) mirror of
    `simulate_sequential_outcomes_posterior` (WP3, closes `REQ-STATE-001`'s
    "Not yet covered" Model C posterior-parity gap at the fixed-carry-in
    level) - same conditional-on-one-shared-`carry_in` contract, using
    `extract_market_specific_posterior_params` and
    `simulate_sequential_outcomes_market_specific`. See
    `simulate_sequential_outcomes_posterior_market_specific_draw_consistent`
    for the fully draw-consistent Model C evaluator."""
    from .market_specific_predict import extract_market_specific_posterior_params

    draws = []
    for chain, draw in sample_draw_indices(trace, n_draws, seed):
        params = extract_market_specific_posterior_params(trace, meta, at=(chain, draw))
        result = simulate_sequential_outcomes_market_specific(
            plan, carry_in, meta, params
        )
        draws.append(result.mu)
    stacked: np.ndarray = np.stack(draws, axis=0)
    return stacked


def simulate_sequential_outcomes_posterior_market_specific_draw_consistent(
    plan: WeeklyPlan,
    historical_frame: Dict[str, Any],
    trace: Any,
    meta: FHModelMeta,
    market: str,
    *,
    as_of_period_label: str = "",
    n_draws: int = DEFAULT_N_DRAWS,
    seed: int = 42,
) -> np.ndarray:
    """Model C (market-specific) mirror of
    `simulate_sequential_outcomes_posterior_draw_consistent` - same fully
    draw-consistent contract (draw-specific parameters used for both
    historical carry-in reconstruction and the future recursion), using
    `extract_market_specific_posterior_params`,
    `reconstruct_starting_state_market_specific`, and
    `simulate_sequential_outcomes_market_specific`."""
    from .market_specific_predict import extract_market_specific_posterior_params

    draws = []
    for chain, draw in sample_draw_indices(trace, n_draws, seed):
        params = extract_market_specific_posterior_params(trace, meta, at=(chain, draw))
        carry_in = reconstruct_starting_state_market_specific(
            historical_frame, meta, params, market, as_of_period_label
        )
        result = simulate_sequential_outcomes_market_specific(
            plan, carry_in, meta, params
        )
        draws.append(result.mu)
    stacked: np.ndarray = np.stack(draws, axis=0)
    return stacked


# ---------------------------------------------------------------------------
# Candidate A diagnostic mediator-state replay (bounded - see module docstring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateASequentialMediatorState:
    """Diagnostic-only sequential replay of Candidate A's demand/capture/cap
    chain for a hypothetical weekly plan - NOT an outcome-level (`mu`)
    result, and grants no planning or optimisation eligibility (see module
    docstring and `core.search_capacity.candidate_a_use_gate`, which
    remains the sole official-use decision)."""

    market: str
    period_labels: Tuple[str, ...]
    forward: CandidateAForwardState

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "period_labels": list(self.period_labels),
            "forward": self.forward.to_dict(),
        }


def simulate_candidate_a_mediator_state_sequentially(
    plan: WeeklyPlan,
    carry_in: SequentialCarryInState,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    candidate_a_params: CandidateASequentialDrawParams,
) -> CandidateASequentialMediatorState:
    """Diagnostic/manual sequential replay of Candidate A's latent-demand/
    capture/cap chain only - see module docstring's Candidate A section.
    Requires `plan.candidate_a_paid_search_cap`: a cap is a decision/
    constraint, never inferred (AGENTS.md's capacity and cap invariants).

    Reuses `core.search_capacity.candidate_a_forward` directly - the exact
    same function `core.search_capacity`'s own forward/reconciliation
    contract already guarantees `captured + unmet == demand` for - applied
    to a per-week `latent_branded_search_demand` series computed from this
    plan's own carry-in-seeded `sat_media` for the demand-driving channels,
    exactly reproducing `attach_candidate_a_demand_capture_chain`'s fit-time
    demand equation (`exp(intercept + market_offset + dot(sat_media[demand],
    beta))`).
    """
    if plan.candidate_a_paid_search_cap is None:
        raise ValueError(
            "Candidate A diagnostic sequential replay requires an explicit "
            "plan.candidate_a_paid_search_cap."
        )
    unknown = [
        c for c in candidate_a_params.demand_channel_names if c not in meta.channels
    ]
    if unknown:
        raise ValueError(
            f"Candidate A demand channel(s) not in this fit's channels: {unknown}"
        )

    decay = np.array([params.decay_rate[c] for c in meta.channels])
    K = np.array([params.hill_K[c] for c in meta.channels])
    S = np.array([params.hill_S[c] for c in meta.channels])
    sat_media_future, _ending_adstock = _simulate_sat_media_sequence(
        plan, carry_in, meta.channels, decay=decay, K=K, S=S
    )

    demand_idx = [
        meta.channels.index(c) for c in candidate_a_params.demand_channel_names
    ]
    market_offset = candidate_a_params.demand_market_offset.get(plan.market, 0.0)
    beta = np.array(
        [
            candidate_a_params.demand_media_beta[c]
            for c in candidate_a_params.demand_channel_names
        ]
    )
    demand = np.exp(
        candidate_a_params.demand_intercept
        + market_offset
        + sat_media_future[:, demand_idx] @ beta
    )

    forward = candidate_a_forward(
        latent_branded_search_demand=demand,
        paid_capture_share=candidate_a_params.capture_share["paid"],
        organic_capture_share=candidate_a_params.capture_share["organic"],
        direct_navigation_capture_share=candidate_a_params.capture_share["direct"],
        paid_search_cap=plan.candidate_a_paid_search_cap,
    )
    return CandidateASequentialMediatorState(
        market=plan.market, period_labels=plan.period_labels, forward=forward
    )


__all__ = [
    "CandidateASequentialMediatorState",
    "SequentialCarryInState",
    "SequentialSimulationResult",
    "WeeklyPlan",
    "compute_incremental_outcome",
    "reconstruct_starting_state",
    "reconstruct_starting_state_market_specific",
    "simulate_candidate_a_mediator_state_sequentially",
    "simulate_sequential_outcomes",
    "simulate_sequential_outcomes_market_specific",
    "simulate_sequential_outcomes_posterior",
    "simulate_sequential_outcomes_posterior_draw_consistent",
    "simulate_sequential_outcomes_posterior_market_specific",
    "simulate_sequential_outcomes_posterior_market_specific_draw_consistent",
    "simulate_terminal_carryover",
    "simulate_terminal_carryover_market_specific",
    "zero_media_extension_plan",
]
