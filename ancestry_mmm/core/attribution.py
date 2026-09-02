"""
Segment-level and total-FH attribution for the joint hierarchical model.

Because the model is multiplicative in mu = exp(baseline + sum_c channel_term_c
+ ...), a channel's "contribution" isn't a well-defined single number without
a decomposition rule - removing channels one at a time and summing the
differences depends on removal order. We use a Shapley decomposition
(averaged over random removal orders) so contributions are fair and sum
exactly to (total predicted outcome - baseline), rather than an arbitrary
last-channel-in/first-channel-out convention.

Generic (non-FH-specific) helpers - compute_shapley_values, decompose_sales -
are kept from the original single-KPI implementation for reuse.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

import numpy as np
import pandas as pd

from .hierarchical_model import FHModelMeta
from .control_scaling import apply_control_scaling
from .predict import (
    FHPosteriorParams,
    _cross_product_strength_matrix,
    _candidate_a_eta_contribution,
    _seo_eta_contribution,
    adstock_saturate_frame,
    lag_frame,
    predict_mu,
)
from .outcome_group_totals import (
    aggregate_attribution_group_rows,
    selected_reporting_ids,
)
from .outcomes import OutcomeGroupDefinition, OutcomeGroupTreatment
from .search_capacity import SEARCH_CANDIDATE_A_ENGINE


class CandidateAAttributionNotSupportedError(ValueError):
    """Raised when Candidate A attribution lacks fit-time replay evidence.

    Candidate A is now supported by the ordinary analyst-facing attribution
    path when the posterior contains its complete demand/capture/outcome-link
    parameters and the fit-time historical cap.  This exception remains the
    fail-closed boundary for an incomplete or malformed Candidate A fit; it
    prevents a plausible-looking decomposition that silently omits the
    search-mediated outcome contribution.
    """


# ---------------------------------------------------------------------------
# Joint hierarchical FH model attribution
# ---------------------------------------------------------------------------


def _baseline_eta(
    frame: Dict, meta: FHModelMeta, params: FHPosteriorParams
) -> np.ndarray:
    """Everything in eta except the media-channel terms: intercept, market, trend, season, promo, controls."""
    outcome_ids = meta.outcome_ids

    intercept = np.array([params.intercept[s] for s in outcome_ids])
    market_offset_matrix = np.array(
        [[params.market_offset[m][s] for s in outcome_ids] for m in meta.markets]
    )
    eta_market = market_offset_matrix[frame["market_idx"]]

    trend_coef = np.array([params.trend_coef[s] for s in outcome_ids])
    eta_trend = frame["trend"][:, None] * trend_coef[None, :]

    gamma_fourier_matrix = np.column_stack(
        [params.gamma_fourier[s] for s in outcome_ids]
    )
    eta_season = frame["fourier"] @ gamma_fourier_matrix

    promo_coef = np.array([params.promo_coef[s] for s in outcome_ids])
    eta_promo = frame["promo"] * promo_coef[None, :]

    eta = intercept[None, :] + eta_market + eta_trend + eta_season + eta_promo

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

    return np.asarray(eta, dtype=float)


def _channel_log_terms(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    *,
    purpose: str = "attribution",
) -> Dict[str, np.ndarray]:
    """Per-channel additive log-mu contribution, shape (n_obs, n_outcomes), before the final exp().

    Mirrors `core.predict.predict_mu`'s pathway-masked construction (PR G1 -
    `core.pathways.resolve_pathway_masks`) channel by channel: a channel's
    term for outcome_id `oid` is `beta[oid][channel] * primary_mask[oid,
    channel] * sat_media[:, channel]` (the undelayed `primary_direct`
    pathway) plus `beta[oid][channel] * pathway_strength[oid][channel] *
    cross_product_lag_media[:, channel]` (the `active_cross_product`/
    `exploratory_cross_product` pathway, on the shared cross-product lag) -
    the same two genuinely separate media inputs the PyMC likelihood uses,
    not one shared lagged series (docs/dna_fh_causal_structure.md). Both
    pathways are summed into the channel's single term here (Shapley permutes
    whole channels, not pathways within a channel), so a cell that's both
    `primary_direct` and cross-product at once (e.g. the DNA cross-sell
    outcome's own DNA channel, by legacy default) correctly gets credit for
    both without either being double-counted."""
    outcome_ids = meta.outcome_ids
    n_obs = frame["X_media"].shape[0]
    n_out = len(outcome_ids)

    sat_media = adstock_saturate_frame(
        frame["X_media"], frame["market_bounds"], meta, params
    )
    primary_mask = meta.resolved_pathway_masks.primary_matrix(
        outcome_ids, meta.channels
    )  # (O, C)

    cross_cells = meta.resolved_pathway_masks.active_cells(
        outcome_ids, meta.channels
    ) + meta.resolved_pathway_masks.exploratory_cells(outcome_ids, meta.channels)
    if cross_cells:
        cross_product_lag_media = {
            lag: lag_frame(sat_media, frame["market_bounds"], lag)
            for lag in {
                meta.resolved_pathway_masks.lag_for_component(
                    outcome_ids[cell[0]], meta.channels[cell[1]]
                )
                for cell in cross_cells
            }
        }
        strength_matrix = _cross_product_strength_matrix(meta, params)
    else:
        cross_product_lag_media = None
        strength_matrix = None

    terms: Dict[str, np.ndarray] = {}
    for ci, ch in enumerate(meta.channels):
        term = np.zeros((n_obs, n_out))
        for si, oid in enumerate(outcome_ids):
            b = params.beta[oid][ch]
            direct_visible = meta.resolved_pathway_masks.component_eligible(
                oid, ch, "direct", purpose
            )
            value = b * primary_mask[si, ci] * direct_visible * sat_media[:, ci]
            cross_visible = meta.resolved_pathway_masks.component_eligible(
                oid, ch, "cross_product", purpose
            )
            if (
                cross_visible
                and strength_matrix is not None
                and strength_matrix[si, ci]
            ):
                value = (
                    value
                    + b
                    * strength_matrix[si, ci]
                    * cross_product_lag_media[
                        meta.resolved_pathway_masks.lag_for_component(oid, ch)
                    ][:, ci]
                )
            term[:, si] = value
        terms[ch] = term
    return terms


def _candidate_a_mu_from_eta(
    base_mu: np.ndarray, candidate_eta: np.ndarray
) -> np.ndarray:
    """Apply one Candidate A replay contribution on the outcome scale."""

    return np.clip(base_mu * np.exp(np.clip(candidate_eta, -50, 50)), 1e-6, 1e9)


def _candidate_a_mediated_shapley(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    *,
    base_mu: np.ndarray,
    sat_media: np.ndarray,
    historical_cap: np.ndarray,
    n_permutations: int,
    rng: np.random.Generator,
) -> Dict[str, Any]:
    """Attribute Candidate A's upstream-media effect by posterior draw.

    The value function replays the complete demand -> cap -> capture ->
    outcome chain for each coalition of demand-driving media channels.  This
    is deliberately a second Shapley decomposition: an upstream channel's
    mediated effect is its marginal effect on the *final outcome*, not a
    spend/click-share allocation of a Search residual.  In particular, the
    no-upstream coalition retains the fitted Search demand intercept and
    therefore separates non-media Search demand from media-mediated Search.
    """

    replay = params.candidate_a_replay_params
    if replay is None:
        raise CandidateAAttributionNotSupportedError(
            "Candidate A attribution requires complete posterior replay "
            "parameters for the demand/capture/outcome chain."
        )
    demand_channels = list(replay.demand_channel_names)
    if not demand_channels:
        raise CandidateAAttributionNotSupportedError(
            "Candidate A attribution requires at least one demand-driving "
            "upstream channel."
        )
    unknown = [channel for channel in demand_channels if channel not in meta.channels]
    if unknown:
        raise CandidateAAttributionNotSupportedError(
            "Candidate A replay demand channel(s) are not in the fitted "
            f"channel set: {unknown}."
        )
    channel_indices = {
        channel: meta.channels.index(channel) for channel in demand_channels
    }

    def coalition_mu(active_channels: set[str]) -> np.ndarray:
        coalition_media = sat_media.copy()
        inactive_indices = [
            channel_indices[channel]
            for channel in demand_channels
            if channel not in active_channels
        ]
        if inactive_indices:
            coalition_media[:, inactive_indices] = 0.0
        candidate_eta = _candidate_a_eta_contribution(
            frame=frame,
            meta=meta,
            params=params,
            sat_media=coalition_media,
            n_obs=base_mu.shape[0],
            explicit_cap=historical_cap,
        )
        return _candidate_a_mu_from_eta(base_mu, candidate_eta)

    if n_permutations < 1:
        raise ValueError("n_permutations must be at least 1.")
    coalition_values: Dict[frozenset[str], np.ndarray] = {}

    def coalition_value(active_channels: set[str]) -> np.ndarray:
        key = frozenset(active_channels)
        if key not in coalition_values:
            coalition_values[key] = coalition_mu(active_channels)
        return coalition_values[key]

    mu_without_upstream_media = coalition_value(set())
    mediated = {
        channel: np.zeros_like(base_mu) for channel in demand_channels
    }
    # Exact coalition-weighted Shapley values keep identical/correlated
    # upstream channels symmetric while retaining the full nonlinear cap
    # replay.  Sampling remains the bounded fallback for unusually large
    # demand-channel sets.
    if len(demand_channels) <= 8:
        factorial_n = math.factorial(len(demand_channels))
        for channel in demand_channels:
            others = [item for item in demand_channels if item != channel]
            for size in range(len(others) + 1):
                for subset in combinations(others, size):
                    active = set(subset)
                    weight = (
                        math.factorial(size)
                        * math.factorial(len(demand_channels) - size - 1)
                        / factorial_n
                    )
                    mediated[channel] += weight * (
                        coalition_value(active | {channel}) - coalition_value(active)
                    )
    else:
        for _ in range(n_permutations):
            active = set()
            current = mu_without_upstream_media
            for channel_value in rng.permutation(demand_channels):
                channel = str(channel_value)
                active.add(channel)
                updated = coalition_mu(active)
                mediated[channel] += updated - current
                current = updated
        for channel in demand_channels:
            mediated[channel] /= n_permutations

    mu_with_upstream_media = coalition_value(set(demand_channels))
    return {
        "mu_without_upstream_media": mu_without_upstream_media,
        "mu_with_upstream_media": mu_with_upstream_media,
        "mediated_by_channel": mediated,
    }


def compute_shapley_contributions(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    n_permutations: int = 200,
    seed: int = 42,
    purpose: str = "attribution",
) -> Dict[str, np.ndarray]:
    """
    Row-and-outcome_id-level Shapley decomposition of predicted mu into a
    baseline and per-channel contributions (outcome units), averaged over
    `n_permutations` random channel removal orders. Contributions sum
    exactly to (mu_total - mu_baseline) for every row/outcome_id.

    Candidate A adds a posterior-draw Shapley decomposition of the upstream
    media effect realised through Search.  Direct, mediated-via-Search, and
    total channel effects are kept separate; the Search pathway row is a
    non-additive reporting view and is never counted again in channel totals.
    """
    rng = np.random.default_rng(seed)
    channels = meta.channels
    n_obs = frame["X_media"].shape[0]
    n_out = len(meta.outcome_ids)

    baseline_eta = _baseline_eta(frame, meta, params)
    mu_baseline = np.exp(np.clip(baseline_eta, -50, 50))
    if purpose not in {"attribution", "headline"}:
        raise ValueError("purpose must be 'attribution' or 'headline'.")
    channel_terms = _channel_log_terms(frame, meta, params, purpose=purpose)

    contributions = {c: np.zeros((n_obs, n_out)) for c in channels}
    for _ in range(n_permutations):
        order = rng.permutation(channels)
        current = mu_baseline.copy()
        for c in order:
            new = current * np.exp(np.clip(channel_terms[c], -50, 50))
            contributions[c] += new - current
            current = new
    for c in channels:
        contributions[c] /= n_permutations

    mu_direct = mu_baseline.copy()
    for c in channels:
        mu_direct = mu_direct + contributions[c]

    mu_total = mu_direct.copy()
    result = {
        "baseline": mu_baseline,
        "channel_contributions": contributions,
        "mu_total": mu_total,
        "outcome_ids": meta.outcome_ids,
        "channels": channels,
    }
    if getattr(meta, "seo_fit_inputs_at_fit", None):
        seo_eta = _seo_eta_contribution(
            frame=frame,
            meta=meta,
            params=params,
            n_obs=n_obs,
            explicit_values=None,
            explicit_active_mask=None,
        )
        mu_with_seo = np.clip(mu_total * np.exp(np.clip(seo_eta, -50, 50)), 1e-6, 1e9)
        result["seo_visibility_contribution"] = mu_with_seo - mu_total
        mu_total = mu_with_seo
    if meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
        historical_cap = np.asarray(
            getattr(meta, "candidate_a_historical_paid_search_cap", ()),
            dtype=float,
        )
        if historical_cap.shape != (n_obs,):
            raise CandidateAAttributionNotSupportedError(
                "Candidate A attribution requires the fit-time historical "
                "paid-search cap recorded with the posterior."
            )
        mu_before_candidate_a = mu_total.copy()
        sat_media = adstock_saturate_frame(
            frame["X_media"], frame["market_bounds"], meta, params
        )
        candidate_a_attribution = _candidate_a_mediated_shapley(
            frame,
            meta,
            params,
            base_mu=mu_total,
            sat_media=sat_media,
            historical_cap=historical_cap,
            n_permutations=n_permutations,
            rng=rng,
        )
        mu_total = predict_mu(
            frame,
            meta,
            params,
            candidate_a_paid_search_cap=historical_cap,
        )
        replay_mu = candidate_a_attribution["mu_with_upstream_media"]
        if not np.allclose(mu_total, replay_mu, rtol=1e-7, atol=1e-8):
            raise CandidateAAttributionNotSupportedError(
                "Candidate A attribution replay does not reconcile with the "
                "full model prediction; refusing an incomplete decomposition."
            )
        result["search_without_upstream_media_mu"] = candidate_a_attribution[
            "mu_without_upstream_media"
        ]
        result["search_non_media_contribution"] = (
            candidate_a_attribution["mu_without_upstream_media"]
            - mu_before_candidate_a
        )
        result["search_mediated_channel_contributions"] = candidate_a_attribution[
            "mediated_by_channel"
        ]
        result["channel_total_contributions"] = {
            channel: contributions[channel]
            + candidate_a_attribution["mediated_by_channel"].get(
                channel, np.zeros_like(contributions[channel])
            )
            for channel in channels
        }
        result["search_mediated_contribution"] = (
            mu_total - candidate_a_attribution["mu_without_upstream_media"]
        )

    result["mu_total"] = mu_total

    return result


def outcome_channel_summary(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    contributions: Optional[Dict] = None,
    ltv: Optional[Dict[str, float]] = None,
    n_permutations: int = 200,
    outcome_groups: Optional[Sequence[OutcomeGroupDefinition]] = None,
    outcome_group_treatments: Optional[Sequence[OutcomeGroupTreatment]] = None,
) -> pd.DataFrame:
    """
    Channel x outcome_id summary: total volume contribution, spend, ROAS/CPA,
    and (if `ltv` is given) LTV-weighted value contribution and value ROAS.
    `ltv` is keyed by outcome_id.

    No `ltv` entry for an outcome_id - whether `ltv` is entirely omitted or
    only partially populated - never silently treats it as weight 1.0
    (PR E.2 - "stop calling raw units value": a GSA/sign-up/kit count is not
    monetary value, so it must never be silently presented as one just
    because no pricing was configured). `value_contribution`/`value_roas`
    are `NaN` for any unpriced outcome_id, regardless of whether `ltv` was
    omitted entirely or only partially covers this fit's outcome_ids.
    """
    contributions = contributions or compute_shapley_contributions(
        frame, meta, params, n_permutations
    )
    ltv = ltv or {}
    mediated_by_channel = cast(
        Dict[str, np.ndarray],
        contributions.get("search_mediated_channel_contributions", {}),
    )
    rows = []
    for ci, ch in enumerate(meta.channels):
        total_spend = float(frame["X_media"][:, ci].sum())
        for si, oid in enumerate(meta.outcome_ids):
            direct = float(contributions["channel_contributions"][ch][:, si].sum())
            mediated = float(
                mediated_by_channel.get(
                    ch, np.zeros_like(contributions["channel_contributions"][ch])
                )[:, si].sum()
            )
            vol = direct + mediated
            weight = ltv[oid] if oid in ltv else np.nan
            value = vol * weight
            rows.append(
                {
                    "channel": ch,
                    "outcome_id": oid,
                    "spend": total_spend,
                    "component_type": "channel_total",
                    "additive_to_media_total": True,
                    "direct_effect": direct,
                    "mediated_via_search_effect": mediated,
                    "total_effect": vol,
                    "volume_contribution": vol,
                    "roas": vol / total_spend if total_spend > 0 else np.nan,
                    "cpa": total_spend / vol if vol > 0 else np.nan,
                    "ltv": ltv.get(oid),
                    "value_contribution": value,
                    "value_roas": value / total_spend if total_spend > 0 else np.nan,
                }
            )
    if "search_mediated_contribution" in contributions:
        for si, oid in enumerate(meta.outcome_ids):
            volume = float(contributions["search_mediated_contribution"][:, si].sum())
            weight = ltv[oid] if oid in ltv else np.nan
            rows.append(
                {
                    "channel": "Search-mediated Candidate A",
                    "outcome_id": oid,
                    "spend": np.nan,
                    "component_type": "search_pathway_view",
                    "additive_to_media_total": False,
                    "direct_effect": np.nan,
                    "mediated_via_search_effect": volume,
                    "total_effect": np.nan,
                    "volume_contribution": volume,
                    "roas": np.nan,
                    "cpa": np.nan,
                    "ltv": ltv.get(oid),
                    "value_contribution": volume * weight,
                    "value_roas": np.nan,
                }
            )
    if "search_non_media_contribution" in contributions:
        for si, oid in enumerate(meta.outcome_ids):
            volume = float(contributions["search_non_media_contribution"][:, si].sum())
            weight = ltv[oid] if oid in ltv else np.nan
            rows.append(
                {
                    "channel": "Search baseline (non-media)",
                    "outcome_id": oid,
                    "spend": np.nan,
                    "component_type": "non_media_pathway_view",
                    "additive_to_media_total": False,
                    "direct_effect": np.nan,
                    "mediated_via_search_effect": np.nan,
                    "total_effect": np.nan,
                    "volume_contribution": volume,
                    "roas": np.nan,
                    "cpa": np.nan,
                    "ltv": ltv.get(oid),
                    "value_contribution": volume * weight,
                    "value_roas": np.nan,
                }
            )
    if "seo_visibility_contribution" in contributions:
        for si, oid in enumerate(meta.outcome_ids):
            volume = float(contributions["seo_visibility_contribution"][:, si].sum())
            weight = ltv[oid] if oid in ltv else np.nan
            rows.append(
                {
                    "channel": "SEO visibility (windowed)",
                    "outcome_id": oid,
                    "spend": np.nan,
                    "component_type": "seo_pathway_view",
                    "additive_to_media_total": False,
                    "direct_effect": np.nan,
                    "mediated_via_search_effect": np.nan,
                    "total_effect": np.nan,
                    "volume_contribution": volume,
                    "roas": np.nan,
                    "cpa": np.nan,
                    "ltv": ltv.get(oid),
                    "value_contribution": volume * weight,
                    "value_roas": np.nan,
                }
            )
    result = pd.DataFrame(rows)
    fit_groups: Optional[Sequence[OutcomeGroupDefinition]] = (
        getattr(meta, "outcome_groups_at_fit", None)
        if outcome_groups is None
        else outcome_groups
    )
    fit_treatments: Optional[Sequence[OutcomeGroupTreatment]] = (
        getattr(meta, "outcome_group_treatments_at_fit", None)
        if outcome_group_treatments is None
        else outcome_group_treatments
    )
    if fit_groups:
        result = aggregate_attribution_group_rows(
            result,
            fit_groups,
            fit_treatments,
            by=["channel"],
        )
    return result


# Deprecated alias (PR E.1 segment-era rename) - see core.predict's identical
# alias pattern for steady_state_outcome_response.
segment_channel_summary = outcome_channel_summary


def total_fh_contribution(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    contributions: Optional[Dict] = None,
    ltv: Optional[Dict[str, float]] = None,
    n_permutations: int = 200,
    outcome_ids: Optional[List[str]] = None,
    outcome_groups: Optional[Sequence[OutcomeGroupDefinition]] = None,
    outcome_group_treatments: Optional[Sequence[OutcomeGroupTreatment]] = None,
) -> pd.DataFrame:
    """
    Total-FH (all Family History outcome_ids summed) view per channel, plus
    which outcome_id the impact falls into.

    `outcome_ids` restricts which of `meta.outcome_ids` are summed into the
    total - pass the Family History outcome_id subset when the fitted model
    also includes DNA-product outcomes (core.outcomes), so a GSA count and a
    kit-sale count are never summed into one meaningless combined number.
    Defaults to every outcome_id in `meta.outcome_ids`, preserving existing
    behaviour for a fit with no DNA outcomes (where "every outcome_id"
    already means "every FH outcome_id").
    """
    summary = outcome_channel_summary(
        frame,
        meta,
        params,
        contributions,
        ltv,
        n_permutations,
        outcome_groups=outcome_groups,
        outcome_group_treatments=outcome_group_treatments,
    )
    if outcome_ids is not None:
        fit_groups = cast(
            Optional[Sequence[OutcomeGroupDefinition]],
            getattr(meta, "outcome_groups_at_fit", None)
            if outcome_groups is None
            else outcome_groups,
        )
        fit_treatments = cast(
            Optional[Sequence[OutcomeGroupTreatment]],
            getattr(meta, "outcome_group_treatments_at_fit", None)
            if outcome_group_treatments is None
            else outcome_group_treatments,
        )
        summary = summary[
            summary["outcome_id"].isin(
                selected_reporting_ids(outcome_ids, fit_groups, fit_treatments)
            )
        ]
    if "component_type" in summary.columns:
        summary = summary[summary["component_type"] == "channel_total"]
    total = (
        summary.groupby("channel")
        .agg(
            spend=("spend", "first"),
            volume_contribution=("volume_contribution", "sum"),
            value_contribution=("value_contribution", "sum"),
        )
        .reset_index()
    )
    total["roas"] = total["volume_contribution"] / total["spend"].replace(0, np.nan)
    total["value_roas"] = total["value_contribution"] / total["spend"].replace(
        0, np.nan
    )

    pivot = summary.pivot(
        index="channel", columns="outcome_id", values="volume_contribution"
    )
    pivot = pivot.div(pivot.sum(axis=1), axis=0).add_suffix("_share")
    return total.merge(pivot.reset_index(), on="channel", how="left")


def contribution_waterfall(
    frame: Dict,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    outcome_id: Optional[str] = None,
    contributions: Optional[Dict] = None,
    n_permutations: int = 200,
    outcome_groups: Optional[List[object]] = None,
    outcome_group_treatments: Optional[List[object]] = None,
) -> pd.DataFrame:
    """
    Waterfall rows: baseline, then each channel's contribution, then total.
    If `outcome_id` is None, sums across all outcome_ids (total FH);
    otherwise a single outcome_id's waterfall.
    """
    contributions = contributions or compute_shapley_contributions(
        frame, meta, params, n_permutations
    )
    fit_groups: Optional[Sequence[OutcomeGroupDefinition]] = (
        getattr(meta, "outcome_groups_at_fit", None)
        if outcome_groups is None
        else outcome_groups
    )
    treatment_records: Sequence[OutcomeGroupTreatment] = (
        outcome_group_treatments
        if outcome_group_treatments is not None
        else getattr(meta, "outcome_group_treatments_at_fit", None) or []
    )
    group_members: Dict[str, tuple[str, ...]] = {
        group.group_id: tuple(group.member_outcome_ids) for group in (fit_groups or [])
    }
    treatment_by_group = {
        treatment.group_id: treatment.treatment for treatment in treatment_records
    }
    for group in fit_groups or []:
        if (
            group.group_id == outcome_id
            and treatment_by_group.get(group.group_id) == "total_only"
            and group.supplied_total_outcome_id
        ):
            group_members[group.group_id] = (group.supplied_total_outcome_id,)
    selected_ids = group_members.get(outcome_id, ()) if outcome_id else ()
    selected_indices = (
        [
            meta.outcome_ids.index(item)
            for item in selected_ids
            if item in meta.outcome_ids
        ]
        if selected_ids
        else ([meta.outcome_ids.index(outcome_id)] if outcome_id else None)
    )

    def total(arr: np.ndarray) -> float:
        if selected_indices is not None:
            return float(arr[:, selected_indices].sum())
        return float(arr.sum())

    rows = [{"category": "Baseline", "value": total(contributions["baseline"])}]
    for ch in meta.channels:
        rows.append(
            {
                "category": ch,
                # Candidate A's separate Search row carries the mediated
                # increment in this bridge.  Using channel totals here would
                # count that same mediated draw effect twice.
                "value": total(contributions["channel_contributions"][ch]),
            }
        )
    if "seo_visibility_contribution" in contributions:
        rows.append(
            {
                "category": "SEO visibility (windowed)",
                "value": total(contributions["seo_visibility_contribution"]),
            }
        )
    if "search_non_media_contribution" in contributions:
        rows.append(
            {
                "category": "Search baseline (non-media)",
                "value": total(contributions["search_non_media_contribution"]),
            }
        )
    if "search_mediated_contribution" in contributions:
        rows.append(
            {
                "category": "Search-mediated Candidate A",
                "value": total(contributions["search_mediated_contribution"]),
            }
        )
    rows.append({"category": "Total", "value": total(contributions["mu_total"])})
    return pd.DataFrame(rows)


def calculate_roi(
    channel_contributions: Dict[str, float],
    channel_spend: Dict[str, float],
    credible_intervals: Optional[Dict[str, Tuple[float, float]]] = None,
) -> pd.DataFrame:
    """Generic ROI table for pages that already have flat contribution/spend dicts."""
    data = []
    for channel in channel_contributions:
        contrib = channel_contributions[channel]
        spend = channel_spend.get(channel, 0)
        roi = contrib / spend if spend > 0 else 0
        row = {"channel": channel, "spend": spend, "contribution": contrib, "roi": roi}
        if credible_intervals and channel in credible_intervals:
            ci_low, ci_high = credible_intervals[channel]
            row["roi_ci_lower"] = ci_low / spend if spend > 0 else 0
            row["roi_ci_upper"] = ci_high / spend if spend > 0 else 0
        data.append(row)
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# Generic helpers (kept from the original single-KPI implementation)
# ---------------------------------------------------------------------------


def compute_shapley_values(
    baseline: float,
    channel_effects: Dict[str, float],
) -> Dict[str, float]:
    """Shapley values for an additive value function (single-KPI, non-FH use)."""
    channels = list(channel_effects.keys())
    n = len(channels)

    if n == 0:
        return {}

    if n > 10:
        return _shapley_sampling(baseline, channel_effects, n_samples=1000)

    shapley = {ch: 0.0 for ch in channels}

    def value_function(coalition: set) -> float:
        if not coalition:
            return baseline
        total = baseline
        for ch in coalition:
            total += channel_effects[ch]
        return total

    for channel in channels:
        marginal_sum = 0.0
        others = [ch for ch in channels if ch != channel]

        for k in range(len(others) + 1):
            for subset in combinations(others, k):
                subset_set = set(subset)
                with_channel = subset_set | {channel}
                marginal = value_function(with_channel) - value_function(subset_set)
                weight = (
                    math.factorial(len(subset_set))
                    * math.factorial(n - len(subset_set) - 1)
                    / math.factorial(n)
                )
                marginal_sum += weight * marginal

        shapley[channel] = marginal_sum

    return shapley


def _shapley_sampling(
    baseline: float,
    channel_effects: Dict[str, float],
    n_samples: int = 1000,
) -> Dict[str, float]:
    channels = list(channel_effects.keys())
    shapley = {ch: 0.0 for ch in channels}
    rng = np.random.default_rng(42)

    for _ in range(n_samples):
        perm = rng.permutation(channels)
        current_value = baseline
        for channel in perm:
            new_value = current_value + channel_effects[channel]
            shapley[channel] += new_value - current_value
            current_value = new_value

    for ch in channels:
        shapley[ch] /= n_samples

    return shapley


def decompose_sales(
    y: np.ndarray,
    baseline: np.ndarray,
    channel_contributions: Dict[str, np.ndarray],
    seasonality: Optional[np.ndarray] = None,
    trend: Optional[np.ndarray] = None,
) -> pd.DataFrame:
    n = len(y)
    data = {
        "actual": y,
        "baseline": baseline if len(baseline) == n else np.full(n, baseline),
    }
    for channel, contrib in channel_contributions.items():
        data[f"channel_{channel}"] = contrib
    if seasonality is not None:
        data["seasonality"] = seasonality
    if trend is not None:
        data["trend"] = trend

    fitted = data["baseline"].copy()
    for key in data:
        if key.startswith("channel_") or key in ["seasonality", "trend"]:
            fitted = fitted + data[key]

    data["fitted"] = fitted
    data["residual"] = y - fitted
    return pd.DataFrame(data)
