"""
Posterior uncertainty for response curves, CPA, and scenario outcomes - the
instruction document's section 6 ("Add posterior uncertainty to decision
outputs"). Point estimates (posterior means) remain what every other
curve/CPA/scenario function in this codebase produces by default
(core.predict, core.market_specific_predict, core.media_units,
core.optimization) - this module is a second, opt-in path: re-run the same
calculation once per sampled posterior draw and summarize the resulting
distribution, rather than replacing the point-estimate path.

Documented approximation: `n_draws` subsamples the posterior (typically
50-200 draws out of several thousand) for speed - a control that trades
calculation speed against how well the subsample represents the full
posterior, per the brief's "controls to balance calculation speed and
posterior draw count". This is not a further *modelling* approximation
beyond what the point-estimate path already makes (steady-state response,
etc.) - it is the exact same calculation, run more than once with different
posterior draws, then summarized.
"""

from __future__ import annotations

import warnings
from typing import Dict, List, Optional

import arviz as az
import numpy as np
import pandas as pd

from .hierarchical_model import FHModelMeta
from .market_specific_predict import (
    extract_market_specific_posterior_params,
    generate_market_channel_curve,
)
from .media_units import compute_cpa_by_product
from .optimization import (
    AnyPosteriorParams,
    PlanningObjective,
    evaluate_scenario,
)
from .outcomes import (
    METRIC_KEY_DNA_KIT_SALE,
    METRIC_KEY_FH_GSA,
    METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    METRIC_KEY_FH_SIGNUP,
    dna_kit_sale_outcome_ids,
    fh_gsa_outcome_ids,
    fh_net_billthrough_outcome_ids,
    fh_signup_outcome_ids,
)
from .predict import extract_posterior_params, generate_channel_curve
from .activities import ActivityDefinition
from .media_costs import CostMappingRegistry
from .scenario_governance import CounterfactualPolicy, ScenarioPlan

DEFAULT_N_DRAWS = 100
DEFAULT_CRED_MASS = 0.9


def sample_draw_indices(trace: az.InferenceData, n_draws: int = DEFAULT_N_DRAWS, seed: int = 42) -> List[tuple]:
    """
    `n_draws` distinct `(chain, draw)` index pairs sampled without
    replacement from `trace.posterior` - every draw, if the posterior has
    fewer than `n_draws` total. Sampling (not "the first n") avoids bias
    from MCMC's within-chain autocorrelation being concentrated early or
    late in a chain.
    """
    post = trace.posterior
    n_chain = post.sizes["chain"]
    n_draw = post.sizes["draw"]
    all_pairs = [(c, d) for c in range(n_chain) for d in range(n_draw)]
    if n_draws >= len(all_pairs):
        return all_pairs
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(all_pairs), size=n_draws, replace=False)
    return [all_pairs[i] for i in idx]


def summarize_distribution(values: np.ndarray, cred_mass: float = DEFAULT_CRED_MASS) -> Dict[str, float]:
    """
    Mean, median, and a `cred_mass` central credible interval (default 90%:
    5th/95th percentile) from an array of per-draw values. NaNs (e.g. CPA
    undefined at a zero-or-negative-response point) are dropped before
    summarizing; returns all-NaN with `n_draws=0` if every value is NaN.
    """
    values = np.asarray(values, dtype=float)
    valid = values[~np.isnan(values)]
    if len(valid) == 0:
        return {"mean": float("nan"), "median": float("nan"), "lower": float("nan"), "upper": float("nan"), "n_draws": 0}
    tail = (1.0 - cred_mass) / 2.0
    return {
        "mean": float(np.mean(valid)),
        "median": float(np.median(valid)),
        "lower": float(np.quantile(valid, tail)),
        "upper": float(np.quantile(valid, 1.0 - tail)),
        "n_draws": int(len(valid)),
    }


def _summarize_curve_draws(draw_dfs: List[pd.DataFrame], cred_mass: float, identity_cols: List[str]) -> pd.DataFrame:
    """Every draw's curve DataFrame shares the same `identity_cols` (spend
    axis, channel/market labels - identical across draws by construction,
    see the callers below) and the same row order/length. Every other
    column gets summarized point-by-point across draws into
    `<column>_mean`/`_median`/`_lower`/`_upper`."""
    base = draw_dfs[0]
    value_cols = [c for c in base.columns if c not in identity_cols]
    out = base[identity_cols].copy()
    tail = (1.0 - cred_mass) / 2.0
    with warnings.catch_warnings():
        # A spend point where every draw's value is legitimately NaN (e.g.
        # marginal CPA at spend=0, undefined for every draw the same way
        # core.media_units.compute_cpa already leaves it NaN for a single
        # draw) makes an all-NaN column-slice, which nanmean/nanquantile
        # warn about even though NaN-out is exactly the correct answer here.
        warnings.filterwarnings("ignore", message="Mean of empty slice")
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        for col in value_cols:
            stacked = np.array([df[col].to_numpy(dtype=float) for df in draw_dfs])  # (n_draws, n_points)
            out[f"{col}_mean"] = np.nanmean(stacked, axis=0)
            out[f"{col}_median"] = np.nanmedian(stacked, axis=0)
            out[f"{col}_lower"] = np.nanquantile(stacked, tail, axis=0)
            out[f"{col}_upper"] = np.nanquantile(stacked, 1.0 - tail, axis=0)
    return out


def generate_channel_curve_with_uncertainty(
    channel: str,
    meta: FHModelMeta,
    trace: az.InferenceData,
    n_draws: int = DEFAULT_N_DRAWS,
    seed: int = 42,
    cred_mass: float = DEFAULT_CRED_MASS,
    spend_range: Optional[np.ndarray] = None,
    n_points: int = 25,
    max_spend: Optional[float] = None,
) -> pd.DataFrame:
    """
    Model A per-draw response + CPA curve: `generate_channel_curve` and
    `core.media_units.compute_cpa_by_product` run once per sampled
    posterior draw over a *fixed* spend axis (computed once from the
    posterior mean if not given, so every draw is evaluated at the same
    spend points - required for the per-point summary below to compare
    like with like), then summarized into `saturation_*`,
    `{outcome_id}_response_*`, `overall_response_*`, `fh_response_*`,
    `dna_response_*`, `avg_cpa_*` (against FH GSAs), `marginal_cpa_*`, and
    - where the channel has a mapped DNA-kit outcome - `dna_avg_cpa_*`/
    `dna_marginal_cpa_*` (against DNA kits) columns.
    """
    if spend_range is None:
        mean_params = extract_posterior_params(trace, meta)
        cap = max_spend if max_spend is not None else max(mean_params.hill_K[channel] * 3, 1.0)
        spend_range = np.linspace(0.0, cap, n_points)

    draw_dfs = []
    for at in sample_draw_indices(trace, n_draws, seed):
        params = extract_posterior_params(trace, meta, at=at)
        curve = generate_channel_curve(channel, meta, params, spend_range=spend_range)
        draw_dfs.append(compute_cpa_by_product(curve))

    return _summarize_curve_draws(draw_dfs, cred_mass, identity_cols=["channel", "spend"])


def generate_market_channel_curve_with_uncertainty(
    market: str,
    channel: str,
    meta: FHModelMeta,
    trace: az.InferenceData,
    n_draws: int = DEFAULT_N_DRAWS,
    seed: int = 42,
    cred_mass: float = DEFAULT_CRED_MASS,
    spend_range: Optional[np.ndarray] = None,
    n_points: int = 25,
    max_spend: Optional[float] = None,
) -> pd.DataFrame:
    """Model C equivalent of `generate_channel_curve_with_uncertainty` -
    same fixed-spend-axis-then-summarize approach, using `market`'s own
    per-draw `hill_K`/`beta`."""
    if spend_range is None:
        mean_params = extract_market_specific_posterior_params(trace, meta)
        cap = max_spend if max_spend is not None else max(mean_params.hill_K[market][channel] * 3, 1.0)
        spend_range = np.linspace(0.0, cap, n_points)

    draw_dfs = []
    for at in sample_draw_indices(trace, n_draws, seed):
        params = extract_market_specific_posterior_params(trace, meta, at=at)
        curve = generate_market_channel_curve(market, channel, meta, params, spend_range=spend_range)
        draw_dfs.append(compute_cpa_by_product(curve))

    return _summarize_curve_draws(draw_dfs, cred_mass, identity_cols=["market", "channel", "spend"])


def _summarize_scenario_draws(draws: List[pd.DataFrame], cred_mass: float) -> pd.DataFrame:
    """Per (month, outcome_id) draw summary. `avg_cpa`/`fh_signup_avg_cpa`/
    `dna_avg_cpa` are metric-aware (see core.optimization.evaluate_scenario's
    docstring, PR E.1) - each summarized independently across draws, never
    combined into one number here either. `total_value_is_complete` is a
    per-row flag (not a per-draw distribution), so it's carried through via
    "min" (False if any draw's row was incomplete) rather than mean/median/
    quantile."""
    tail = (1.0 - cred_mass) / 2.0
    combined = pd.concat(draws, ignore_index=True)
    grouped = combined.groupby(["month", "outcome_id"], sort=False)
    summary = grouped.agg(
        predicted_outcome_mean=("predicted_outcome", "mean"),
        predicted_outcome_median=("predicted_outcome", "median"),
        predicted_outcome_lower=("predicted_outcome", lambda s: s.quantile(tail)),
        predicted_outcome_upper=("predicted_outcome", lambda s: s.quantile(1.0 - tail)),
        incremental_outcome_mean=("incremental_outcome", "mean"),
        incremental_outcome_median=("incremental_outcome", "median"),
        incremental_outcome_lower=(
            "incremental_outcome",
            lambda s: s.quantile(tail),
        ),
        incremental_outcome_upper=(
            "incremental_outcome",
            lambda s: s.quantile(1.0 - tail),
        ),
        probability_incremental_positive=(
            "incremental_outcome",
            lambda s: float((s > 0).mean()),
        ),
        value_mean=("value", "mean"),
        value_median=("value", "median"),
        value_lower=("value", lambda s: s.quantile(tail)),
        value_upper=("value", lambda s: s.quantile(1.0 - tail)),
        avg_cpa_mean=("avg_cpa", "mean"),
        avg_cpa_median=("avg_cpa", "median"),
        avg_cpa_lower=("avg_cpa", lambda s: s.quantile(tail)),
        avg_cpa_upper=("avg_cpa", lambda s: s.quantile(1.0 - tail)),
        fh_signup_avg_cpa_mean=("fh_signup_avg_cpa", "mean"),
        fh_signup_avg_cpa_median=("fh_signup_avg_cpa", "median"),
        fh_signup_avg_cpa_lower=("fh_signup_avg_cpa", lambda s: s.quantile(tail)),
        fh_signup_avg_cpa_upper=("fh_signup_avg_cpa", lambda s: s.quantile(1.0 - tail)),
        dna_avg_cpa_mean=("dna_avg_cpa", "mean"),
        dna_avg_cpa_median=("dna_avg_cpa", "median"),
        dna_avg_cpa_lower=("dna_avg_cpa", lambda s: s.quantile(tail)),
        dna_avg_cpa_upper=("dna_avg_cpa", lambda s: s.quantile(1.0 - tail)),
        incremental_nbt_cpa_mean=("whole_plan_incremental_nbt_cpa", "mean"),
        incremental_nbt_cpa_median=(
            "whole_plan_incremental_nbt_cpa",
            "median",
        ),
        incremental_nbt_cpa_lower=(
            "whole_plan_incremental_nbt_cpa",
            lambda s: s.quantile(tail),
        ),
        incremental_nbt_cpa_upper=(
            "whole_plan_incremental_nbt_cpa",
            lambda s: s.quantile(1.0 - tail),
        ),
        incremental_roi_mean=("whole_plan_incremental_roi", "mean"),
        incremental_roi_median=("whole_plan_incremental_roi", "median"),
        incremental_roi_lower=(
            "whole_plan_incremental_roi",
            lambda s: s.quantile(tail),
        ),
        incremental_roi_upper=(
            "whole_plan_incremental_roi",
            lambda s: s.quantile(1.0 - tail),
        ),
        total_value_mean=("total_value", "mean"),
        total_value_median=("total_value", "median"),
        total_value_lower=("total_value", lambda s: s.quantile(tail)),
        total_value_upper=("total_value", lambda s: s.quantile(1.0 - tail)),
        total_value_is_complete=("total_value_is_complete", "min"),
    ).reset_index()
    return summary


def evaluate_scenario_with_uncertainty(
    spend_plan: Dict[str, Dict[str, float]],
    market: str,
    meta: FHModelMeta,
    trace: az.InferenceData,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    *,
    model_type: str = "shared",
    n_draws: int = DEFAULT_N_DRAWS,
    seed: int = 42,
    cred_mass: float = DEFAULT_CRED_MASS,
    approval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    baseline_spend_plan: Optional[Dict[str, Dict[str, float]]] = None,
    scenario_plan: Optional[ScenarioPlan] = None,
    baseline_scenario_plan: Optional[ScenarioPlan] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
    planning_objective: Optional[PlanningObjective] = None,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_month: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    """
    Per-draw scenario evaluation: `core.optimization.evaluate_scenario` run
    once per sampled posterior draw, summarized into
    `predicted_outcome`/`value`/`avg_cpa` `_mean`/`_median`/`_lower`/`_upper`
    per (month, outcome_id).

    If `baseline_spend_plan` is given (typically the current/live plan), it
    is evaluated under the *same* draw indices as `spend_plan` (paired, not
    independently resampled - comparing two independently-resampled
    distributions would overstate the apparent uncertainty in their
    difference, since it would include sampling noise from two separate
    draws instead of one shared draw per comparison) - `prob_outperforms_baseline`
    is then the fraction of paired draws where `spend_plan`'s total value
    exceeds `baseline_spend_plan`'s.

    Returns `{"summary": DataFrame, "prob_outperforms_baseline": float or
    None, "n_draws": int}`. Raises `ApprovalMismatchError` exactly as
    `evaluate_scenario` does (checked once per draw - cheap, and avoids
    duplicating that logic here).
    """
    extract_fn = extract_market_specific_posterior_params if model_type == "market_specific" else extract_posterior_params

    def _evaluate(
        plan: Dict[str, Dict[str, float]],
        params: AnyPosteriorParams,
        typed_plan: Optional[ScenarioPlan],
    ) -> pd.DataFrame:
        return evaluate_scenario(
            plan, market, meta, params, reference_context_by_month, ltv,
            model_type=model_type, approval=approval, model_run_id=model_run_id,
            data_fingerprint=data_fingerprint, model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            scenario_plan=typed_plan,
            activity_definitions=activity_definitions,
            counterfactual_policy=counterfactual_policy,
            planning_objective=planning_objective,
            cost_mapping_registry=cost_mapping_registry,
            cost_context_id=cost_context_id,
            cost_as_of_by_month=cost_as_of_by_month,
        )

    draw_indices = sample_draw_indices(trace, n_draws, seed)
    proposed_draws: List[pd.DataFrame] = []
    baseline_draws: List[pd.DataFrame] = []
    draw_frames: List[pd.DataFrame] = []
    for draw_id, at in enumerate(draw_indices):
        params = extract_fn(trace, meta, at=at)
        proposed = _evaluate(spend_plan, params, scenario_plan)
        proposed_draws.append(proposed)
        draw_frame = proposed.copy()
        draw_frame["posterior_draw"] = draw_id
        draw_frame["chain_index"] = at[0]
        draw_frame["draw_index"] = at[1]
        draw_frames.append(draw_frame)
        if baseline_spend_plan is not None:
            baseline_draws.append(
                _evaluate(
                    baseline_spend_plan,
                    params,
                    baseline_scenario_plan,
                )
            )

    summary = _summarize_scenario_draws(proposed_draws, cred_mass)

    prob_outperforms_baseline = None
    comparison_column = None
    if baseline_draws:
        use_value = all(
            frame["total_value_is_complete"].all()
            for frame in [*proposed_draws, *baseline_draws]
        )
        metric_columns = {
            METRIC_KEY_FH_GSA: "incremental_fh_gsa",
            METRIC_KEY_FH_SIGNUP: "incremental_fh_signups",
            METRIC_KEY_FH_NET_BILLTHROUGH_COUNT: (
                "incremental_fh_net_billthrough"
            ),
            METRIC_KEY_DNA_KIT_SALE: "incremental_dna_kits",
        }
        if (
            planning_objective is not None
            and planning_objective.estimand == "incremental_value"
        ):
            if not use_value:
                raise ValueError(
                    "candidate-versus-current value probability requires "
                    "complete value coverage"
                )
            comparison_column = "incremental_total_value"
        elif planning_objective is not None:
            comparison_column = metric_columns.get(
                planning_objective.metric_key
            )
            if comparison_column is None:
                raise ValueError(
                    "candidate-versus-current probability does not support "
                    f"metric {planning_objective.metric_key!r}"
                )
        elif use_value:
            comparison_column = "incremental_total_value"
        elif fh_net_billthrough_outcome_ids(meta):
            comparison_column = "incremental_fh_net_billthrough"
        elif fh_gsa_outcome_ids(meta):
            comparison_column = "incremental_fh_gsa"
        elif fh_signup_outcome_ids(meta):
            comparison_column = "incremental_fh_signups"
        elif dna_kit_sale_outcome_ids(meta):
            comparison_column = "incremental_dna_kits"
        else:
            raise ValueError(
                "candidate-versus-current probability requires an explicit "
                "supported PlanningObjective"
            )
        proposed_totals = np.array(
            [
                frame.groupby("month")[comparison_column].first().sum()
                for frame in proposed_draws
            ]
        )
        baseline_totals = np.array(
            [
                frame.groupby("month")[comparison_column].first().sum()
                for frame in baseline_draws
            ]
        )
        prob_outperforms_baseline = float(np.mean(proposed_totals > baseline_totals))

    return {
        "summary": summary,
        "draws": pd.concat(draw_frames, ignore_index=True),
        "prob_outperforms_baseline": prob_outperforms_baseline,
        "comparison_metric": comparison_column,
        "n_draws": len(draw_indices),
        "cred_mass": cred_mass,
    }
