"""
NumPy replay of the joint hierarchical FH model's math, driven by posterior
parameter estimates rather than PyMC/PyTensor.

Two different jobs need to evaluate "what would the model predict for these
inputs" *outside* of an active MCMC run:

1. Out-of-sample diagnostics (rolling-origin backtest) - predict a held-out
   period from parameters fit on an earlier period.
2. Scenario planning - predict expected outcomes for a hypothetical spend
   allocation, fast enough to sit inside an optimiser's objective function.

Both use the same steady-state approximation for (2): under spend held
constant at a given weekly level, geometric adstock converges to that same
level (that's what the `normalize=True` scaling is for), so the channel's
contribution simplifies to the Hill saturation curve evaluated at that
spend level directly - no need to simulate the week-by-week adstock
recursion. This is the standard approximation response-curve-based MMM
budget optimisers use; it is documented here rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

import numpy as np
import pandas as pd
import arviz as az

from .transformations import (
    apply_media_input_scale,
    apply_media_input_scales,
    geometric_adstock_matrix,
    hill_function,
)
from .hierarchical_model import FHModelMeta
from .control_scaling import apply_control_mapping_scaling, apply_control_scaling
from .named_event_fit_inputs import NamedEventFitInputs
from .outcomes import (
    dna_kit_sale_outcome_ids,
    fh_gsa_outcome_ids,
    fh_net_billthrough_outcome_ids,
    fh_signup_outcome_ids,
)
from .search_capacity import (
    SEARCH_CANDIDATE_A_ENGINE,
    CandidateAReplayParams,
    candidate_a_forward,
    extract_candidate_a_replay_params,
)


class CandidateAReplayNotSupportedError(ValueError):
    """Raised when Candidate A replay lacks required fit or plan evidence.

    Candidate A's demand/capture/cap chain is now replayed on the outcome
    scale for historical attribution, official curves, sequential scenarios,
    and sequential optimisation. This exception remains the fail-closed
    boundary for an incomplete posterior, a missing fit-time cap, or a
    future/scenario replay without an explicit cap; it prevents downstream
    callers from producing a plausible result that omits the mediated Search
    contribution or silently turns a historical cap into a future assumption.
    """


class NamedEventReplayNotSupportedError(ValueError):
    """Raised by `predict_mu` (and therefore every caller: curves, scenario
    planning, backtest, optimisation) for a fit that consumed a named-event
    response term (`core.named_event_fit_inputs`, Decision 12) -
    `meta.named_event_response_definitions_at_fit` non-empty - UNLESS the
    caller also supplies this call's `named_event_fit_inputs` parameter
    (a `core.named_event_fit_inputs.NamedEventFitInputs` built for the
    frame being replayed, typically via `core.named_event_fit_inputs.
    build_named_event_fit_inputs_for_replay`).

    This NumPy replay reconstructs `eta` from intercept/market/trend/
    season/channels/promo/controls (plus, when supplied, the named-event
    term below) only - it has no way to recompute the `event_coefs_
    <family>_<market>` contribution `core.hierarchical_model`/
    `core.market_specific_model` add at fit time from `frame` alone: doing
    so needs the governed registry itself (which family/occurrences/
    response definitions applied), which this function is never given by
    default - unlike every other term, it is not a pure function of
    `frame`/`meta`/`params`. Before this guard existed, curves/scenario
    planning/backtest/optimisation for any project using named events
    would silently evaluate a `mu` missing that entire pathway's
    contribution - never raising, never warning, and biased specifically
    in the weeks that matter most (the planted event windows). A caller
    that does not (yet) supply `named_event_fit_inputs` still gets this
    hard failure rather than a plausible-but-wrong number; a caller that
    does gets the correct, already-fitted-coefficient replay (including
    correctly into a scenario frame that extends into future weeks - see
    `build_named_event_fit_inputs_for_replay`'s own docstring for why that
    needs no new decision: the governed registry's occurrence dates,
    including future/planned ones, drive the same relative-offset spline
    basis used at fit time either way).
    """


@dataclass
class FHPosteriorParams:
    """Posterior point estimates (defaults to the mean) needed to replay the model."""

    decay_rate: Dict[str, float]
    hill_K: Dict[str, float]
    hill_S: Dict[str, float]
    beta: Dict[str, Dict[str, float]]  # beta[outcome_id][channel]
    pathway_strength: Dict[
        str, Dict[str, float]
    ]  # pathway_strength[outcome_id][channel] - PR G1,
    # generalises the old per-outcome-only `halo_strength` to per-(outcome,
    # channel): the fitted active_cross_product/exploratory_cross_product
    # multiplier for that cell, 0.0 for a primary_direct/excluded cell (see
    # core.pathways.resolve_pathway_masks). Whichever of the two roles a
    # cell actually has, its strength value lives here uniformly - callers
    # don't need to know which sub-role produced it, only which cells
    # (meta.resolved_pathway_masks.active_cells()/.exploratory_cells()) to apply it to.
    promo_coef: Dict[str, float]  # promo_coef[outcome_id]
    market_offset: Dict[str, Dict[str, float]]  # market_offset[market][outcome_id]
    intercept: Dict[str, float]
    trend_coef: Dict[str, float]
    gamma_fourier: Dict[str, np.ndarray]  # gamma_fourier[outcome_id] -> (n_fourier,)
    alpha: Dict[str, float]
    control_coef: Dict[str, float]
    outcome_control_coef: Dict[str, Dict[str, float]]  # [outcome_id][control_name]
    # Production integration (predict/scenario-replay gap closure, Decision
    # 12): event_coefs[family_id][market] -> the fitted `event_coefs_
    # <family_id>_<market>` posterior vector (n_basis,). Empty dict (never
    # populated) for any fit before this field existed, or any fit that
    # never consumed a named-event response term - see `predict_mu`'s own
    # handling of `meta.named_event_fit_blocks`.
    event_coefs: Dict[str, Dict[str, np.ndarray]] = field(default_factory=dict)
    # Present only for a Candidate A fit.  Keeping this on the extracted
    # posterior object makes every downstream consumer (curves, scenarios,
    # attribution and optimisation) use the same draw-level replay math.
    candidate_a_replay_params: Optional[CandidateAReplayParams] = None
    # Present only for a fit that consumed the governed SEO visibility
    # predictor.  It is kept draw-aligned with the rest of this object so the
    # gated treatment contributes uncertainty to every fitted-frame replay.
    seo_visibility_beta: Optional[np.ndarray] = None


def extract_event_coefs(
    trace: az.InferenceData,
    meta: FHModelMeta,
    at: Optional[tuple[int, int]] = None,
) -> Dict[str, Dict[str, np.ndarray]]:
    """`event_coefs[family_id][market]` (predict/scenario-replay gap
    closure, Decision 12) - the fitted `event_coefs_<family_id>_<market>`
    posterior vector for every `(family_id, market)` pair actually fit
    (`meta.named_event_fit_blocks` - set once, at fit time, from
    `named_event_fit_inputs.blocks`; never reconstructed by parsing the
    variable name back apart, which would be ambiguous whenever a
    family_id or market itself contains an underscore).

    Shared by `extract_posterior_params` (Model A) and `core.
    market_specific_predict.extract_market_specific_posterior_params`
    (Model C) - the variable is named and fit identically by both model
    builders (`core.hierarchical_model.build_fh_hierarchical_model`/
    `core.market_specific_model.build_fh_market_specific_model`)."""
    post = trace.posterior

    def _reduce(da):
        if at is not None:
            return da.isel(chain=at[0], draw=at[1])
        return da.mean(dim=["chain", "draw"])

    event_coefs: Dict[str, Dict[str, np.ndarray]] = {}
    for family_id, market in meta.named_event_fit_blocks:
        var_name = f"event_coefs_{family_id}_{market}"
        if var_name not in post:
            continue
        event_coefs.setdefault(family_id, {})[market] = np.asarray(
            _reduce(post[var_name]).values
        )
    return event_coefs


def extract_pathway_strength(
    trace: az.InferenceData,
    meta: FHModelMeta,
    at: Optional[tuple[int, int]] = None,
) -> Dict[str, Dict[str, float]]:
    """`pathway_strength[outcome_id][channel]` (PR G1) - shared by both
    `extract_posterior_params` (Model A) and `core.market_specific_predict.
    extract_market_specific_posterior_params` (Model C), since
    `active_cross_product_strength`/`exploratory_cross_product_strength` are
    fit with `dims=("outcome", "channel")` in *both* PyMC builders (no market
    dimension - see hierarchical_model.py/market_specific_model.py's matching
    comment). Missing from the trace (no active/exploratory cells at fit
    time) reads as all-zero rather than raising, same as any other absent-
    deterministic lookup in this module.

    A cell is at most one of active_cross_product/exploratory_cross_product
    (`core.pathways.resolve_pathway_masks`), so summing the two named
    deterministics is safe - exactly one is ever nonzero for a given cell,
    and both are zero for primary_direct/excluded cells.
    """
    post = trace.posterior

    def _reduce(da):
        if at is not None:
            return da.isel(chain=at[0], draw=at[1])
        return da.mean(dim=["chain", "draw"])

    def _pathway_strength_var(var_name: str) -> Dict[str, Dict[str, float]]:
        if var_name not in post:
            return {s: {c: 0.0 for c in meta.channels} for s in meta.outcome_ids}
        reduced = _reduce(post[var_name])
        return {
            s: {
                c: float(reduced.sel(outcome=s, channel=c).values)
                for c in meta.channels
            }
            for s in meta.outcome_ids
        }

    active_strength = _pathway_strength_var("active_cross_product_strength")
    exploratory_strength = _pathway_strength_var("exploratory_cross_product_strength")
    return {
        s: {
            c: active_strength[s][c] + exploratory_strength[s][c] for c in meta.channels
        }
        for s in meta.outcome_ids
    }


def extract_posterior_params(
    trace: az.InferenceData,
    meta: FHModelMeta,
    at: Optional[tuple[int, int]] = None,
) -> FHPosteriorParams:
    """
    Pull posterior values into plain dicts keyed by name - the posterior
    mean (across every chain and draw) by default, or one specific
    `(chain, draw)` index pair when `at` is given.

    `at` is what makes per-draw uncertainty calculations possible
    (`core.uncertainty`): calling this once per sampled draw index produces
    a genuine posterior sample of `FHPosteriorParams`, not just the point
    estimate every other caller (curve bank, scenario planner) uses.
    """
    post = trace.posterior

    def _reduce(da):
        if at is not None:
            return da.isel(chain=at[0], draw=at[1])
        return da.mean(dim=["chain", "draw"])

    def by_coord(var: str, coord: str, labels: List[str]) -> Dict[str, float]:
        da = post[var]
        vals = (
            da.isel(chain=at[0], draw=at[1])
            if at is not None
            else da.mean(dim=[d for d in da.dims if d not in (coord,)])
        )
        return {label: float(vals.sel({coord: label}).values) for label in labels}

    decay_rate = by_coord("decay_rate", "channel", meta.channels)
    hill_K = by_coord("hill_K", "channel", meta.channels)
    hill_S = by_coord("hill_S", "channel", meta.channels)
    intercept = by_coord("intercept", "outcome", meta.outcome_ids)
    trend_coef = by_coord("trend_coef", "outcome", meta.outcome_ids)
    promo_coef = by_coord("promo_coef", "outcome", meta.outcome_ids)
    alpha = by_coord("alpha", "outcome", meta.outcome_ids)

    pathway_strength = extract_pathway_strength(trace, meta, at=at)

    beta_reduced = _reduce(post["beta"])
    beta = {
        s: {
            c: float(beta_reduced.sel(outcome=s, channel=c).values)
            for c in meta.channels
        }
        for s in meta.outcome_ids
    }

    market_offset_reduced = _reduce(post["market_offset"])
    market_offset = {
        m: {
            s: float(market_offset_reduced.sel(market=m, outcome=s).values)
            for s in meta.outcome_ids
        }
        for m in meta.markets
    }

    gamma_fourier_reduced = _reduce(post["gamma_fourier"])
    gamma_fourier = {
        s: gamma_fourier_reduced.sel(outcome=s).values for s in meta.outcome_ids
    }

    control_coef = {}
    if meta.control_names and "control_coef" in post:
        cc_reduced = _reduce(post["control_coef"])
        control_coef = {
            c: float(cc_reduced.sel(control=c).values) for c in meta.control_names
        }

    outcome_control_coef: Dict[str, Dict[str, float]] = {}
    for oid, names in meta.outcome_control_names.items():
        var_name = f"outcome_control_coef_{oid}"
        if var_name in post:
            coord_name = f"{oid}_control"
            v_reduced = _reduce(post[var_name])
            outcome_control_coef[oid] = {
                n: float(v_reduced.sel({coord_name: n}).values) for n in names
            }

    event_coefs = extract_event_coefs(trace, meta, at=at)
    candidate_a_replay_params = None
    if meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
        candidate_a_replay_params = extract_candidate_a_replay_params(
            trace, meta, at=at
        )
    seo_visibility_beta = None
    if getattr(meta, "seo_fit_inputs_at_fit", None):
        if "seo_visibility_beta" not in post:
            raise CandidateAReplayNotSupportedError(
                "This fit records SEO visibility inputs but its trace is missing "
                "seo_visibility_beta; SEO replay is unavailable."
            )
        seo_visibility_beta = np.asarray(_reduce(post["seo_visibility_beta"]).values)

    return FHPosteriorParams(
        decay_rate=decay_rate,
        hill_K=hill_K,
        hill_S=hill_S,
        beta=beta,
        pathway_strength=pathway_strength,
        promo_coef=promo_coef,
        market_offset=market_offset,
        intercept=intercept,
        trend_coef=trend_coef,
        gamma_fourier=gamma_fourier,
        alpha=alpha,
        control_coef=control_coef,
        outcome_control_coef=outcome_control_coef,
        event_coefs=event_coefs,
        candidate_a_replay_params=candidate_a_replay_params,
        seo_visibility_beta=seo_visibility_beta,
    )


def adstock_saturate_frame(
    X_media: np.ndarray,
    market_bounds: List[tuple],
    meta: FHModelMeta,
    params: FHPosteriorParams,
) -> np.ndarray:
    """NumPy adstock + Hill saturation per market block, matching the PyMC model exactly."""
    X_media = apply_media_input_scales(X_media, meta.channels, meta.media_input_scales)
    decay = np.array([params.decay_rate[c] for c in meta.channels])
    K = np.array([params.hill_K[c] for c in meta.channels])
    S = np.array([params.hill_S[c] for c in meta.channels])

    out = np.zeros_like(X_media, dtype=float)
    for start, end in market_bounds:
        adstocked = geometric_adstock_matrix(X_media[start:end], decay, normalize=True)
        out[start:end] = hill_function(adstocked, K, S)
    return out


def lag_frame(X: np.ndarray, market_bounds: List[tuple], lag_weeks: int) -> np.ndarray:
    out = np.zeros_like(X, dtype=float)
    for start, end in market_bounds:
        n = end - start
        if lag_weeks <= 0:
            out[start:end] = X[start:end]
        elif lag_weeks >= n:
            continue  # stays zero
        else:
            out[start + lag_weeks : end] = X[start : end - lag_weeks]
    return out


class _HasEventCoefs(Protocol):
    """Structural type both `FHPosteriorParams` (Model A) and
    `core.market_specific_predict.FHMarketSpecificPosteriorParams` (Model
    C) satisfy - only `event_coefs` is needed by `_named_event_eta_
    contribution`, mirroring `_HasPathwayStrength`'s identical role/reason
    just below."""

    event_coefs: Dict[str, Dict[str, np.ndarray]]


def _named_event_eta_contribution(
    meta: FHModelMeta,
    params: _HasEventCoefs,
    named_event_fit_inputs: NamedEventFitInputs,
    n_obs: int,
    outcome_ids: List[str],
) -> np.ndarray:
    """The additive named-event `eta` contribution, replaying already-
    fitted `event_coefs_<family_id>_<market>` posterior coefficients
    against `named_event_fit_inputs`'s design blocks for THIS replay
    frame - the exact mirror of `core.hierarchical_model.
    build_fh_hierarchical_model`'s fit-time `eta_events` construction
    (same design-times-coefficients dot product, same outcome-scope
    restriction), just in NumPy against a fixed coefficient vector
    instead of PyMC against a random variable.

    A block whose `(family_id, market)` was never actually fit (not in
    `meta.named_event_fit_blocks`, or the trace was missing that specific
    variable at extraction time) contributes zero, never fabricated or
    borrowed from another market - see `build_named_event_fit_inputs_
    for_replay`'s docstring for why this is a mechanical consequence of
    Decision 12's own already-approved unpooled-by-default choice, not a
    new business decision.
    """
    fit_blocks = {tuple(pair) for pair in meta.named_event_fit_blocks}
    eta_events = np.zeros((n_obs, len(outcome_ids)))
    for event_block in named_event_fit_inputs.blocks:
        if (event_block.family_id, event_block.market) not in fit_blocks:
            continue
        coefs = params.event_coefs.get(event_block.family_id, {}).get(
            event_block.market
        )
        if coefs is None:
            continue
        contrib = event_block.design @ coefs
        if event_block.outcome_scope:
            for scoped_outcome in event_block.outcome_scope:
                if scoped_outcome not in outcome_ids:
                    continue
                o_idx = outcome_ids.index(scoped_outcome)
                eta_events[:, o_idx] += contrib
        else:
            eta_events += contrib[:, None]
    return eta_events


def _candidate_a_paid_search_cap_for_frame(
    frame: Dict,
    meta: FHModelMeta,
    n_obs: int,
    explicit_cap: Optional[float | np.ndarray | List[float]],
) -> np.ndarray:
    """Resolve the Candidate A cap for one replay frame.

    A fitted frame may use its durable historical cap from ``FHModelMeta``.
    Any other frame must provide an explicit future/scenario cap.  In
    particular, a historical last value is never silently carried into a
    future plan.
    """

    if explicit_cap is not None:
        cap = np.asarray(explicit_cap, dtype=float)
        if cap.ndim == 0:
            cap = np.full(n_obs, float(cap))
        elif cap.shape != (n_obs,):
            raise CandidateAReplayNotSupportedError(
                "Candidate A replay cap must be one value per replay period."
            )
    else:
        historical_cap = np.asarray(
            getattr(meta, "candidate_a_historical_paid_search_cap", ()),
            dtype=float,
        )
        fit_periods = tuple(getattr(meta, "candidate_a_fit_period_labels", ()))
        frame_periods = tuple(
            str(pd.Timestamp(value).date()) for value in frame.get("dates", ())
        )
        if (
            historical_cap.shape != (n_obs,)
            or not fit_periods
            or frame_periods != fit_periods
        ):
            raise CandidateAReplayNotSupportedError(
                "Candidate A replay requires an explicit paid-search cap for "
                "scenario/future periods; historical caps are only valid for "
                "the exact fitted frame."
            )
        cap = historical_cap
    if not np.all(np.isfinite(cap)) or np.any(cap < 0):
        raise CandidateAReplayNotSupportedError(
            "Candidate A replay cap must contain finite, non-negative values."
        )
    return cap


def _candidate_a_eta_contribution(
    *,
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    sat_media: np.ndarray,
    n_obs: int,
    explicit_cap: Optional[float | np.ndarray | List[float]],
) -> np.ndarray:
    """Replay Candidate A's full demand/capture/cap chain on outcome scale.

    The chain is evaluated once per extracted posterior draw.  The paid cap
    is applied before the captured-demand term is converted to an additive
    log-link contribution, preserving the fitted model's non-linearity and
    posterior uncertainty semantics.
    """

    replay = params.candidate_a_replay_params
    if replay is None:
        raise CandidateAReplayNotSupportedError(
            "Candidate A posterior replay parameters are unavailable; the "
            "fit must be rebuilt from a trace containing the complete Search "
            "demand/capture/outcome-link variables."
        )
    unknown = [
        channel
        for channel in replay.demand_channel_names
        if channel not in meta.channels
    ]
    if unknown:
        raise CandidateAReplayNotSupportedError(
            "Candidate A replay demand channel(s) are not in the fitted "
            f"channel set: {unknown}."
        )
    demand_idx = [
        meta.channels.index(channel) for channel in replay.demand_channel_names
    ]
    demand_beta = np.asarray(
        [replay.demand_media_beta[channel] for channel in replay.demand_channel_names],
        dtype=float,
    )
    market_offsets = np.asarray(
        [replay.demand_market_offset.get(market, 0.0) for market in meta.markets],
        dtype=float,
    )
    market_idx = np.asarray(frame["market_idx"], dtype=int)
    if (
        market_idx.shape != (n_obs,)
        or np.any(market_idx < 0)
        or np.any(market_idx >= len(meta.markets))
    ):
        raise CandidateAReplayNotSupportedError(
            "Candidate A replay frame has an invalid market index vector."
        )
    demand_eta = (
        float(replay.demand_intercept)
        + market_offsets[market_idx]
        + sat_media[:, demand_idx] @ demand_beta
    )
    latent_demand = np.exp(np.clip(demand_eta, -50.0, 50.0)) * float(
        replay.demand_to_capture_scale
    )
    cap = _candidate_a_paid_search_cap_for_frame(frame, meta, n_obs, explicit_cap)
    forward = candidate_a_forward(
        latent_demand,
        replay.capture_share["paid"],
        replay.capture_share["organic"],
        replay.capture_share["direct"],
        cap,
    )
    eta = np.zeros((n_obs, len(meta.outcome_ids)), dtype=float)
    for outcome_index, outcome_id in enumerate(meta.outcome_ids):
        paid_beta = replay.paid_capture_outcome_beta.get(outcome_id)
        organic_beta = replay.organic_capture_outcome_beta.get(outcome_id)
        direct_beta = replay.direct_navigation_capture_outcome_beta.get(outcome_id)
        if paid_beta is None or organic_beta is None or direct_beta is None:
            raise CandidateAReplayNotSupportedError(
                f"Candidate A replay is missing an outcome-link coefficient "
                f"for '{outcome_id}'."
            )
        eta[:, outcome_index] = (
            float(paid_beta) * forward.realised_paid_search_delivery
            + float(organic_beta) * forward.organic_capture
            + float(direct_beta) * forward.direct_navigation_capture
        ) / float(replay.capture_scale)
    return eta


def _seo_eta_contribution(
    *,
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    n_obs: int,
    explicit_values: Optional[np.ndarray],
    explicit_active_mask: Optional[np.ndarray],
    allow_reference_for_future: bool = False,
) -> np.ndarray:
    """Replay the row-aligned, window-gated SEO visibility treatment.

    Without explicit future SEO values, the exact fitted row grid is used for
    historical replay. Planning/optimisation callers may explicitly opt into
    the governed fitted-window reference state; they never extrapolate SEO
    visibility or treat missing history as zero.
    """

    payload = getattr(meta, "seo_fit_inputs_at_fit", None) or {}
    if not payload:
        return np.zeros((n_obs, len(meta.outcome_ids)), dtype=float)
    if params.seo_visibility_beta is None:
        raise CandidateAReplayNotSupportedError(
            "SEO visibility was consumed by this fit but no posterior SEO "
            "coefficient is available for replay."
        )
    if (explicit_values is None) != (explicit_active_mask is None):
        raise CandidateAReplayNotSupportedError(
            "SEO replay requires both visibility values and their active mask."
        )
    if explicit_values is None:
        row_markets = tuple(
            meta.markets[int(index)] for index in np.asarray(frame["market_idx"])
        )
        row_weeks = tuple(
            str(pd.Timestamp(value).date()) for value in frame.get("dates", ())
        )
        if (
            tuple(payload.get("model_markets") or ()) != row_markets
            or tuple(payload.get("model_weeks") or ()) != row_weeks
        ):
            if allow_reference_for_future:
                return np.broadcast_to(
                    _seo_reference_eta_contribution(meta, params),
                    (n_obs, len(meta.outcome_ids)),
                ).copy()
            raise CandidateAReplayNotSupportedError(
                "SEO replay requires the exact fitted SEO window or an explicit "
                "row-aligned SEO predictor; future SEO intervention values are "
                "not approved for planning."
            )
        values = np.asarray(payload.get("standardized_visibility") or (), dtype=float)
        active = np.asarray(payload.get("active_mask") or (), dtype=float)
    else:
        values = np.asarray(explicit_values, dtype=float)
        active = np.asarray(explicit_active_mask, dtype=float)
    if values.shape != (n_obs,) or active.shape != (n_obs,):
        raise CandidateAReplayNotSupportedError(
            "SEO replay values and active mask must have one value per row."
        )
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(active)):
        raise CandidateAReplayNotSupportedError(
            "SEO replay values and active mask must be finite."
        )
    if np.any((active != 0) & (active != 1)):
        raise CandidateAReplayNotSupportedError(
            "SEO replay active mask must contain only zero or one."
        )
    beta = np.asarray(params.seo_visibility_beta, dtype=float)
    if beta.shape != (len(meta.outcome_ids),):
        raise CandidateAReplayNotSupportedError(
            "SEO replay posterior coefficient shape does not match outcomes."
        )
    return values[:, None] * active[:, None] * beta[None, :]


def _seo_reference_eta_contribution(meta: FHModelMeta, params) -> np.ndarray:
    """Return the governed model-reference SEO state for steady-state paths.

    SEO has no approved controllable intervention.  Steady-state curves and
    planning therefore hold it at the fitted active-window reference, rather
    than asking the analyst to invent a future ranking assumption.
    """

    payload = getattr(meta, "seo_fit_inputs_at_fit", None) or {}
    beta = getattr(params, "seo_visibility_beta", None)
    if not payload or beta is None:
        return np.zeros(len(meta.outcome_ids), dtype=float)
    values = np.asarray(payload.get("standardized_visibility") or (), dtype=float)
    active = np.asarray(payload.get("active_mask") or (), dtype=float)
    if values.shape != active.shape or not values.size or not np.any(active > 0):
        raise CandidateAReplayNotSupportedError(
            "SEO steady-state replay has no valid observed reference state."
        )
    reference = float(np.mean(values[active > 0]))
    return reference * np.asarray(beta, dtype=float)


class _HasPathwayStrength(Protocol):
    """Structural type both `FHPosteriorParams` (Model A) and
    `core.market_specific_predict.FHMarketSpecificPosteriorParams` (Model C)
    satisfy - only `pathway_strength` is needed by the two helpers below, so
    they work for either model's posterior params without predict.py having
    to import market_specific_predict (which itself imports FROM predict.py -
    a real import cycle, not just a style preference)."""

    pathway_strength: Dict[str, Dict[str, float]]


def _cross_product_strength_matrix(
    meta: FHModelMeta, params: _HasPathwayStrength
) -> np.ndarray:
    """`(n_outcome, n_channel)` array: `params.pathway_strength[outcome_id][channel]`
    at every `active_cross_product`/`exploratory_cross_product` cell
    (`core.pathways.resolve_pathway_masks`), `0.0` everywhere else -
    structurally masked (not just trusting `params` to already be zero
    elsewhere), same discipline the old `halo_eligible`-masked lookup used.
    Shared by `predict_mu` (full replay) and the steady-state functions
    below (via `_pathway_weight`, which adds the `primary_direct` `1.0`)."""
    outcome_ids, channels = meta.outcome_ids, meta.channels
    mat = np.zeros((len(outcome_ids), len(channels)), dtype=float)
    for oi, ci in meta.resolved_pathway_masks.active_cells(
        outcome_ids, channels
    ) + meta.resolved_pathway_masks.exploratory_cells(outcome_ids, channels):
        mat[oi, ci] = params.pathway_strength.get(outcome_ids[oi], {}).get(
            channels[ci], 0.0
        )
    return mat


def _pathway_weight(
    meta: FHModelMeta,
    params: _HasPathwayStrength,
    outcome_id: str,
    channel: str,
    *,
    planning_only: bool = False,
) -> float:
    """Total multiplier for one `(outcome_id, channel)` cell's channel
    contribution at STEADY STATE - constant spend converges lagged and
    unlagged media to the identical value, so the `primary_direct` and
    cross-product weights simply add (see `predict_mu` for the general,
    non-steady-state replay, which needs the lagged/unlagged media kept
    separate). `1.0` if `channel` is `primary_direct` for `outcome_id`,
    plus `params.pathway_strength[...]` if it's also (or instead)
    `active_cross_product`/`exploratory_cross_product`, `0.0` for an
    excluded cell (in neither)."""
    weight = 0.0
    is_direct = channel in meta.resolved_pathway_masks.primary_channels_by_outcome.get(
        outcome_id, []
    )
    direct_eligible = (
        not planning_only
        or meta.resolved_pathway_masks.component_eligible(
            outcome_id, channel, "direct", "planning"
        )
    )
    if is_direct and direct_eligible:
        weight = 1.0
    is_active = channel in meta.resolved_pathway_masks.active_channels_by_outcome.get(
        outcome_id, []
    )
    is_exploratory = (
        channel
        in meta.resolved_pathway_masks.exploratory_channels_by_outcome.get(
            outcome_id, []
        )
    )
    cross_eligible = (
        not planning_only
        or meta.resolved_pathway_masks.component_eligible(
            outcome_id, channel, "cross_product", "planning"
        )
    )
    if cross_eligible and (is_active or is_exploratory):
        weight += params.pathway_strength.get(outcome_id, {}).get(channel, 0.0)
    return weight


def predict_mu(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    *,
    precomputed_sat_media: Optional[np.ndarray] = None,
    named_event_fit_inputs: Optional[NamedEventFitInputs] = None,
    candidate_a_paid_search_cap: Optional[float | np.ndarray | List[float]] = None,
    seo_visibility_values: Optional[np.ndarray] = None,
    seo_visibility_active_mask: Optional[np.ndarray] = None,
    seo_use_reference_for_future: bool = False,
) -> np.ndarray:
    """
    Replay the model's full linear predictor in NumPy for an arbitrary frame
    (historical, held-out, or a hypothetical scenario built with the same
    structure as data.preprocessor.prepare_fh_modeling_frame's output).

    Returns mu, shape (n_obs, n_outcomes), matching frame["outcome_ids"] order.

    Candidate A fits require an explicit cap for scenario/future frames. The
    exact fitted frame may use its durable historical cap from ``meta``;
    this distinction prevents historical cap values from becoming silent
    future assumptions.

    Raises `NamedEventReplayNotSupportedError` for a fit that consumed a
    named-event response term UNLESS `named_event_fit_inputs` is supplied
    (typically built via `core.named_event_fit_inputs.
    build_named_event_fit_inputs_for_replay` against this same `frame`) -
    see that exception's docstring for the full reasoning and
    `_named_event_eta_contribution` for how the supplied design blocks are
    replayed against `params.event_coefs`.

    `precomputed_sat_media` (WP5, `Media-Mix-Lab: Coding LLM Next Steps
    After PR #253`, sequential simulation kernel): when given, this exact
    (n_obs, n_channels) adstocked-and-saturated array is used in place of
    calling `adstock_saturate_frame` on `frame["X_media"]` - every other
    term (baseline/market/trend/season/promo/controls, and the direct/
    cross-product pathway-masked combination of the media term) is
    unchanged, so a caller with its own sequentially-computed (carry-in-
    seeded) `sat_media` - `core.sequential_simulation` - gets bit-identical
    non-media math to the batch replay, rather than a second, parallel
    eta-assembly implementation. `frame["X_media"]` is not read at all in
    this case (it still may be needed by the caller to build
    `precomputed_sat_media` itself).
    """
    if (
        meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE
        and params.candidate_a_replay_params is None
    ):
        raise CandidateAReplayNotSupportedError(
            "Candidate A posterior replay parameters are unavailable; the "
            "fit must be rebuilt from a complete Candidate A trace."
        )
    if meta.named_event_response_definitions_at_fit and named_event_fit_inputs is None:
        raise NamedEventReplayNotSupportedError(
            "predict_mu does not represent this fit's named-event response "
            "term (event_coefs_<family>_<market>) unless the caller supplies "
            "named_event_fit_inputs (see core.named_event_fit_inputs."
            "build_named_event_fit_inputs_for_replay) - curves, scenario "
            "planning, backtest, and optimisation are not available for a "
            "fit that consumed a named-event response definition without "
            f"it. Consumed: {meta.named_event_response_definitions_at_fit!r}."
        )
    outcome_ids = meta.outcome_ids
    n_obs = (
        frame["X_media"].shape[0]
        if precomputed_sat_media is None
        else (precomputed_sat_media.shape[0])
    )
    n_out = len(outcome_ids)

    sat_media = (
        precomputed_sat_media
        if precomputed_sat_media is not None
        else adstock_saturate_frame(
            frame["X_media"], frame["market_bounds"], meta, params
        )
    )

    beta_matrix = np.array(
        [[params.beta[s][c] for c in meta.channels] for s in outcome_ids]
    )  # (O, C)

    # Pathway-masked replay (PR G1) - mirrors core.hierarchical_model.
    # build_fh_hierarchical_model's eta_primary/eta_active/eta_exploratory
    # construction exactly (same masks, same media, same beta multiplication)
    # so this NumPy replay can never silently diverge from what was fit.
    primary_mask = meta.resolved_pathway_masks.primary_matrix(
        outcome_ids, meta.channels
    )  # (O, C)
    eta_primary = sat_media @ (beta_matrix * primary_mask).T

    cross_cells = meta.resolved_pathway_masks.active_cells(
        outcome_ids, meta.channels
    ) + meta.resolved_pathway_masks.exploratory_cells(outcome_ids, meta.channels)
    eta_cross = np.zeros((n_obs, n_out))
    if cross_cells:
        strength_matrix = _cross_product_strength_matrix(meta, params)
        lagged = {
            lag: lag_frame(sat_media, frame["market_bounds"], lag)
            for lag in {
                meta.resolved_pathway_masks.lag_for_component(
                    outcome_ids[cell[0]], meta.channels[cell[1]]
                )
                for cell in cross_cells
            }
        }
        for oi, ci in cross_cells:
            component_lag = meta.resolved_pathway_masks.lag_for_component(
                outcome_ids[oi], meta.channels[ci]
            )
            eta_cross[:, oi] += (
                lagged[component_lag][:, ci]
                * beta_matrix[oi, ci]
                * strength_matrix[oi, ci]
            )

    eta_channels = eta_primary + eta_cross

    promo_coef = np.array([params.promo_coef[s] for s in outcome_ids])
    eta_promo = frame["promo"] * promo_coef[None, :]

    market_idx = frame["market_idx"]
    market_offset_matrix = np.array(
        [[params.market_offset[m][s] for s in outcome_ids] for m in meta.markets]
    )
    eta_market = market_offset_matrix[market_idx]

    intercept = np.array([params.intercept[s] for s in outcome_ids])
    trend_coef = np.array([params.trend_coef[s] for s in outcome_ids])
    eta_trend = frame["trend"][:, None] * trend_coef[None, :]

    gamma_fourier_matrix = np.column_stack(
        [params.gamma_fourier[s] for s in outcome_ids]
    )  # (F, O)
    eta_season = frame["fourier"] @ gamma_fourier_matrix

    eta = (
        intercept[None, :]
        + eta_market
        + eta_trend
        + eta_season
        + eta_channels
        + eta_promo
    )

    if meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
        eta = eta + _candidate_a_eta_contribution(
            frame=frame,
            meta=meta,
            params=params,
            sat_media=sat_media,
            n_obs=n_obs,
            explicit_cap=candidate_a_paid_search_cap,
        )

    eta = eta + _seo_eta_contribution(
        frame=frame,
        meta=meta,
        params=params,
        n_obs=n_obs,
        explicit_values=seo_visibility_values,
        explicit_active_mask=seo_visibility_active_mask,
        allow_reference_for_future=seo_use_reference_for_future,
    )

    outcome_controls = frame.get("outcome_controls") or {}
    outcome_control_names = frame.get("outcome_control_names") or {}
    for oid, arr in outcome_controls.items():
        if oid not in outcome_ids or oid not in params.outcome_control_coef:
            continue
        o_idx = outcome_ids.index(oid)
        names = outcome_control_names.get(oid, [])
        coefs = np.array([params.outcome_control_coef[oid].get(n, 0.0) for n in names])
        scaled_arr = apply_control_scaling(
            arr,
            names,
            (meta.outcome_control_scaling or {}).get(oid),
        )
        eta[:, o_idx] += scaled_arr @ coefs

    control_names = frame.get("control_names") or []
    if control_names and params.control_coef:
        coefs = np.array([params.control_coef.get(n, 0.0) for n in control_names])
        scaled_controls = apply_control_scaling(
            frame["X_controls"],
            control_names,
            meta.control_scaling,
        )
        eta += (scaled_controls @ coefs)[:, None]

    if named_event_fit_inputs is not None:
        eta = eta + _named_event_eta_contribution(
            meta, params, named_event_fit_inputs, n_obs, outcome_ids
        )

    mu = np.clip(np.exp(eta), 1e-6, 1e9)
    return mu


def steady_state_outcome_response(
    market: str,
    spend_by_channel: Dict[str, float],
    meta: FHModelMeta,
    params: FHPosteriorParams,
    reference_context: Optional[Dict] = None,
    *,
    planning_only: bool = False,
    candidate_a_paid_search_cap: Optional[float] = None,
) -> Dict[str, float]:
    """
    Expected weekly outcome per outcome_id for spend held constant at
    `spend_by_channel` levels in `market`, holding trend/seasonality/promo/
    controls at reference (typically recent-average) levels. This is the
    steady-state approximation used by the scenario planner - see module
    docstring.
    """
    reference_context = reference_context or {}
    outcome_ids = meta.outcome_ids
    # Keep replay compatible with lightweight legacy metadata objects that
    # predate the optional media-input scaling contract. FHModelMeta itself
    # supplies the same empty mapping by default.
    media_input_scales = getattr(meta, "media_input_scales", {})

    sat = {}
    for c in meta.channels:
        x = spend_by_channel.get(c, 0.0)
        sat[c] = hill_function(
            np.array([apply_media_input_scale(x, c, media_input_scales)]),
            params.hill_K[c],
            params.hill_S[c],
        )[0]

    eta = {}
    for s in outcome_ids:
        val = params.intercept[s]
        val += params.market_offset.get(market, {}).get(s, 0.0)
        val += params.trend_coef[s] * reference_context.get("trend", 1.0)
        gamma = params.gamma_fourier[s]
        fourier_ref = reference_context.get("fourier", np.zeros_like(gamma))
        val += float(np.dot(gamma, fourier_ref))
        val += params.promo_coef[s] * reference_context.get("promo", {}).get(s, 0.0)

        for c in meta.channels:
            # At steady state, spend held constant forever converges the
            # primary (unlagged) and cross-product (lagged) media to the
            # identical value `sat[c]`, so `_pathway_weight`'s
            # primary-plus-cross-product weight can be applied to one
            # `sat[c]` term directly instead of needing two separate media
            # series - see predict_mu for the general, non-steady-state
            # replay where they must stay separate.
            val += (
                params.beta[s][c]
                * sat[c]
                * _pathway_weight(meta, params, s, c, planning_only=planning_only)
            )

        if meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
            if candidate_a_paid_search_cap is None:
                raise CandidateAReplayNotSupportedError(
                    "Candidate A steady-state replay requires an explicit "
                    "paid-search cap; no future cap assumption is inferred."
                )
            candidate_eta = _candidate_a_eta_contribution(
                frame={
                    "market_idx": np.array([meta.markets.index(market)]),
                    "dates": [],
                },
                meta=meta,
                params=params,
                sat_media=np.asarray(
                    [[sat.get(channel, 0.0) for channel in meta.channels]],
                    dtype=float,
                ),
                n_obs=1,
                explicit_cap=float(candidate_a_paid_search_cap),
            )
            val += float(candidate_eta[0, outcome_ids.index(s)])

        val += float(
            _seo_reference_eta_contribution(meta, params)[outcome_ids.index(s)]
        )

        scaled_controls = apply_control_mapping_scaling(
            reference_context.get("controls", {}),
            tuple(params.control_coef),
            meta.control_scaling,
        )
        for name, coef in params.control_coef.items():
            val += coef * scaled_controls.get(name, 0.0)
        if s in params.outcome_control_coef:
            scaled_outcome_controls = apply_control_mapping_scaling(
                reference_context.get("outcome_controls", {}).get(s, {}),
                tuple(params.outcome_control_coef[s]),
                (meta.outcome_control_scaling or {}).get(s),
            )
            for name, coef in params.outcome_control_coef[s].items():
                val += coef * scaled_outcome_controls.get(name, 0.0)

        eta[s] = val

    return {s: float(np.clip(np.exp(v), 1e-6, 1e9)) for s, v in eta.items()}


# Deprecated alias (PR E.1 segment-era rename) - kept because this name is
# part of this module's public API surface (core/__init__.py re-exports it)
# and may still be imported by external/legacy callers. Prefer
# steady_state_outcome_response in new code.
steady_state_segment_response = steady_state_outcome_response


def generate_channel_curve(
    channel: str,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    spend_range: Optional[np.ndarray] = None,
    n_points: int = 25,
    max_spend: Optional[float] = None,
) -> pd.DataFrame:
    """
    Spend -> incremental response curve for one channel, per outcome_id and
    overall - the Model A ("shared curve") equivalent of
    core.market_specific_predict.generate_market_channel_curve, kept
    symmetric with it (same column shape: spend, saturation,
    {outcome_id}_response..., overall_response, fh_response, dna_response) so
    downstream consumers - core.media_units's CPA/media-unit calculations,
    the curve bank - can work on either model type's curve without
    branching on which one produced it.

    `fh_response`/`fh_signup_response`/`dna_response` split `overall_response`
    by product AND metric (PR E.1 - docs/dna_fh_causal_structure.md's "never
    sum kits and GSAs as one volume", extended to "never sum sign-ups and
    GSAs as one volume" either, since both can now be independently fitted
    outcome_ids on the same segment): `dna_response` is the sum over
    outcome_ids with `product == DNA` (`core.outcomes.dna_kit_sale_outcome_ids`),
    `fh_response` is the sum over outcome_ids with `product == Family History
    and metric == "GSA"` (`core.outcomes.fh_gsa_outcome_ids`) - NOT "every
    other outcome_id" as before, which silently included any FH sign-up
    outcome in what was labelled a GSA total. `fh_signup_response` is the
    analogous sum for `metric == "Sign-up"`
    (`core.outcomes.fh_signup_outcome_ids`). `overall_response` remains the
    sum of every outcome_id regardless of product/metric/role, unchanged in
    value - it is not removed, since plenty of existing callers (and the
    curve bank) still want "this channel's total modelled response" as one
    number; it is never used as a CPA/objective denominator on its own
    (`core.media_units.compute_cpa` blocks that when the curve genuinely
    mixes products). For the overwhelming majority of curves (no DNA-kit
    outcomes, no distinct sign-up outcome), `dna_response`/`fh_signup_response`
    are identically zero and `overall_response == fh_response`, unchanged
    from before this split existed.

    Steady-state approximation (see module docstring): channels don't
    interact in this model's linear predictor, so a channel's own curve
    doesn't depend on any other channel's spend level - each point is just
    that channel's own Hill saturation curve, scaled by each outcome_id's
    beta (and, for a DNA channel, that outcome_id's direct-plus-halo weight
    - see steady_state_outcome_response). Point estimates only (posterior
    means), same convention as steady_state_outcome_response.
    """
    if channel not in meta.channels:
        raise ValueError(
            f"'{channel}' is not one of this model's channels: {meta.channels}"
        )

    K = params.hill_K[channel]
    S = params.hill_S[channel]
    if spend_range is None:
        scale = (meta.media_input_scales or {}).get(channel, 1.0)
        cap = max_spend if max_spend is not None else max(K * 3 * scale, 1.0)
        spend_range = np.linspace(0.0, cap, n_points)

    gsa_ids = set(fh_gsa_outcome_ids(meta))
    nbt_ids = set(fh_net_billthrough_outcome_ids(meta))
    signup_ids = set(fh_signup_outcome_ids(meta))
    dna_ids = set(dna_kit_sale_outcome_ids(meta))
    rows = []
    for spend in spend_range:
        sat = float(
            hill_function(
                np.array(
                    [
                        apply_media_input_scale(
                            float(spend), channel, meta.media_input_scales
                        )
                    ]
                ),
                K,
                S,
            )[0]
        )
        row = {"channel": channel, "spend": float(spend), "saturation": sat}
        overall = 0.0
        dna_total = 0.0
        fh_gsa_total = 0.0
        fh_nbt_total = 0.0
        fh_signup_total = 0.0
        for oid in meta.outcome_ids:
            # Same steady-state collapse as steady_state_outcome_response:
            # constant spend converges the primary and cross-product media to
            # the same `sat` value, so `_pathway_weight`'s combined weight
            # applies to this single curve point directly.
            beta_val = params.beta[oid][channel] * _pathway_weight(
                meta, params, oid, channel
            )
            value = beta_val * sat
            row[f"{oid}_response"] = value
            overall += value
            if oid in dna_ids:
                dna_total += value
            elif oid in gsa_ids:
                fh_gsa_total += value
            elif oid in nbt_ids:
                fh_nbt_total += value
            elif oid in signup_ids:
                fh_signup_total += value
        row["overall_response"] = overall
        row["dna_response"] = dna_total
        row["fh_response"] = fh_gsa_total
        row["fh_net_billthrough_response"] = fh_nbt_total
        row["fh_signup_response"] = fh_signup_total
        rows.append(row)

    return pd.DataFrame(rows)
