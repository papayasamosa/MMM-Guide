"""
Scenario planning and budget optimisation for the joint hierarchical FH model.

Three modes, matching how Ancestry actually plans budgets rather than just
producing a mathematically optimal split:

- Manual: edit spend directly, see predicted outcomes update (evaluate_scenario).
- Constrained: optimise subject to locked cells, fixed channel/month totals,
  bounded movement from the current plan, and minimum-spend floors
  (optimize_scenario with constraints).
- Unconstrained benchmark: optimise the same total budget with none of the
  above constraints - a theoretical-optimum comparison point, not a plan.

All three evaluate expected outcomes with the steady-state response
approximation in core.predict (see that module's docstring): spend held
constant within a month is treated as having reached its adstock
steady-state, so a month's expected outcome is a closed-form function of
that month's channel spend - no MCMC in the optimisation loop.

Works against either model type (Phase 3c) via `model_type`: `"shared"`
(Model A, the default - `steady_state_outcome_response`, `params` an
`FHPosteriorParams`) or `"market_specific"` (Model C -
`steady_state_outcome_response_market_specific`, `params` an
`FHMarketSpecificPosteriorParams`). Both functions have the identical
`(market, spend_by_channel, meta, params, reference_context) -> {outcome_id:
rate}` contract - `market` already selects the right market-specific
baseline/K/beta for Model C the same way it already selected the right
market baseline for Model A - so nothing else in this module's planning
math (constraints, bounds, the optimiser objective) needs to know which
model type it's driving.

evaluate_scenario and optimize_scenario are the core planning entry points,
and both require a ModelApproval that matches the exact model run supplying
`meta`/`params` (model_run_id plus data/spec/posterior fingerprints - see
core.fingerprint and core.approval). This is enforced here, not only by the
Streamlit Scenario Planner page's own checks, so a direct call to either
function - bypassing the page - still requires a valid, matching approval.

Kept from the original single-KPI implementation for reuse:
calculate_marginal_roi_loglog, optimize_budget_marginal_roi, calculate_expected_lift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from scipy.optimize import minimize, LinearConstraint

from .approval import ModelApproval, require_matching_approval
from .hierarchical_model import FHModelMeta
from .outcomes import fh_gsa_outcome_ids, fh_signup_outcome_ids, dna_kit_sale_outcome_ids, select_outcome_ids
from .predict import FHPosteriorParams, steady_state_outcome_response
from .market_specific_predict import FHMarketSpecificPosteriorParams, steady_state_outcome_response_market_specific

WEEKS_PER_MONTH = 365.25 / 12 / 7  # ~4.348

AnyPosteriorParams = Union[FHPosteriorParams, FHMarketSpecificPosteriorParams]


def _steady_state_response_fn(model_type: str):
    if model_type not in ("shared", "market_specific"):
        raise ValueError(f"model_type must be 'shared' or 'market_specific', got {model_type!r}")
    return steady_state_outcome_response_market_specific if model_type == "market_specific" else steady_state_outcome_response


# ---------------------------------------------------------------------------
# Scenario evaluation (manual mode)
# ---------------------------------------------------------------------------

def evaluate_scenario(
    spend_plan: Dict[str, Dict[str, float]],
    market: str,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    *,
    model_type: str = "shared",
    approval: ModelApproval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
) -> pd.DataFrame:
    """
    Predicted monthly outcomes for a spend plan: {month_label: {channel: spend}}.

    Returns one row per (month, outcome_id) with predicted units (weekly
    steady-state rate x weeks/month) and LTV-weighted value if `ltv` is given.
    `ltv` is keyed by outcome_id.

    Metric-aware (PR E.1), same denominator discipline as
    core.media_units.compute_cpa_by_product: `fh_gsa`/`fh_signups`/`dna_kits`
    are each summed via `core.outcomes.fh_gsa_outcome_ids`/
    `fh_signup_outcome_ids`/`dna_kit_sale_outcome_ids` - explicit
    product+metric selectors, never "every outcome_id that isn't a DNA-kit
    outcome" (the confirmed defect this replaces: that would silently sum a
    Family History sign-up outcome into what's labelled `fh_gsa`). Each row
    repeats these month-level totals (same "duplicated scalar per outcome_id
    row" shape `total_spend` already used):

    - `fh_gsa` / `fh_signups` / `dna_kits`: that month's total predicted
      units for each named metric, never combined with each other.
    - `avg_cpa` (alias `cost_per_fh_gsa`): `total_spend / fh_gsa` (`None`
      where `fh_gsa` is zero or negative, same "never compute CPA on a
      non-positive base" rule as core.media_units.compute_cpa).
    - `fh_signup_avg_cpa` (alias `cost_per_fh_signup`): `total_spend /
      fh_signups`, `None` where `fh_signups` is zero/negative or the model
      has no sign-up outcomes.
    - `dna_avg_cpa` (alias `cost_per_dna_kit`): `total_spend / dna_kits`,
      `None` where `dna_kits` is zero/negative or the model has no DNA-kit
      outcomes at all.
    - `value`/`total_value`: LTV-weighted value. A missing `ltv` entry for
      an outcome_id is NEVER silently treated as weight 1.0 (the confirmed
      defect this replaces - that could turn a raw sign-up/GSA/kit count
      into a fake common-currency total) - that outcome_id's `value` is
      `None` and it is excluded from `total_value`, which is flagged via
      `total_value_is_complete=False` whenever any outcome_id that month
      had no value weight, so a caller can show an explicit
      incomplete-value warning rather than silently under/over-counting.

    `model_type` selects which model's steady-state response function
    drives the evaluation - `"shared"` (Model A, default) or
    `"market_specific"` (Model C) - see module docstring.

    Raises ApprovalMismatchError unless `approval` matches the current model
    run identity (`model_run_id` plus the three fingerprints) - see
    core.approval.require_matching_approval.
    """
    require_matching_approval(
        approval,
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    )
    response_fn = _steady_state_response_fn(model_type)
    ltv = ltv or {}
    gsa_ids = set(fh_gsa_outcome_ids(meta))
    signup_ids = set(fh_signup_outcome_ids(meta))
    dna_ids = set(dna_kit_sale_outcome_ids(meta))
    rows = []
    for month, spend_by_channel in spend_plan.items():
        ref = reference_context_by_month.get(month, {})
        weekly_rate = response_fn(market, spend_by_channel, meta, params, ref)
        total_spend = sum(spend_by_channel.values())
        monthly_outcome_by_id = {oid: rate * WEEKS_PER_MONTH for oid, rate in weekly_rate.items()}
        fh_gsa = sum(v for oid, v in monthly_outcome_by_id.items() if oid in gsa_ids)
        fh_signups = sum(v for oid, v in monthly_outcome_by_id.items() if oid in signup_ids)
        dna_kits = sum(v for oid, v in monthly_outcome_by_id.items() if oid in dna_ids)
        avg_cpa = (total_spend / fh_gsa) if fh_gsa > 0 else None
        fh_signup_avg_cpa = (total_spend / fh_signups) if fh_signups > 0 else None
        dna_avg_cpa = (total_spend / dna_kits) if dna_kits > 0 else None
        if ltv:
            # A *partial* ltv (some outcome_ids priced, others not) is the
            # confirmed defect: a missing entry must never be silently
            # treated as weight 1.0. `total_value_is_complete=False` flags
            # exactly this case for the caller to warn about.
            total_value_is_complete = all(oid in ltv for oid in monthly_outcome_by_id)
            total_value = sum(v * ltv[oid] for oid, v in monthly_outcome_by_id.items() if oid in ltv)
        else:
            # No value weights given at all is not the defect above - it is
            # the documented "no $-weighting requested" case, where `value`
            # is simply the raw predicted units (uniform weight 1.0),
            # unchanged from this function's behaviour before PR E.1.
            total_value_is_complete = True
            total_value = sum(monthly_outcome_by_id.values())
        for oid, monthly_outcome in monthly_outcome_by_id.items():
            value = (monthly_outcome * ltv[oid] if oid in ltv else None) if ltv else monthly_outcome
            rows.append({
                "month": month,
                "outcome_id": oid,
                "predicted_outcome": monthly_outcome,
                "value": value,
                "total_spend": total_spend,
                "fh_gsa": fh_gsa,
                "fh_signups": fh_signups,
                "dna_kits": dna_kits,
                "avg_cpa": avg_cpa,
                "cost_per_fh_gsa": avg_cpa,
                "fh_signup_avg_cpa": fh_signup_avg_cpa,
                "cost_per_fh_signup": fh_signup_avg_cpa,
                "dna_avg_cpa": dna_avg_cpa,
                "cost_per_dna_kit": dna_avg_cpa,
                "total_value": total_value,
                "total_value_is_complete": total_value_is_complete,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

@dataclass
class SpendConstraint:
    kind: str  # "locked_cell" | "channel_total" | "month_total" | "bounded_movement" | "min_spend_floor"
    channel: Optional[str] = None
    month: Optional[str] = None
    months: Optional[List[str]] = None
    value: Optional[float] = None
    max_pct_move: Optional[float] = None
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "channel": self.channel, "month": self.month,
            "months": self.months, "value": self.value,
            "max_pct_move": self.max_pct_move, "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpendConstraint":
        return cls(**d)


def _flatten(spend_plan: Dict[str, Dict[str, float]], months: List[str], channels: List[str]) -> np.ndarray:
    return np.array([spend_plan[m].get(c, 0.0) for m in months for c in channels])


def _unflatten(x: np.ndarray, months: List[str], channels: List[str]) -> Dict[str, Dict[str, float]]:
    n_ch = len(channels)
    return {
        m: {c: float(x[mi * n_ch + ci]) for ci, c in enumerate(channels)}
        for mi, m in enumerate(months)
    }


def _cell_index(month: str, channel: str, months: List[str], channels: List[str]) -> int:
    return months.index(month) * len(channels) + channels.index(channel)


def build_bounds_and_constraints(
    months: List[str],
    channels: List[str],
    current_spend: np.ndarray,
    constraints: List[SpendConstraint],
    default_max_pct_move: Optional[float] = None,
) -> Tuple[List[Tuple[float, float]], List[LinearConstraint]]:
    """Translate SpendConstraint objects into scipy bounds + LinearConstraints."""
    n = len(current_spend)
    lower = np.zeros(n)
    upper = np.full(n, np.inf)

    if default_max_pct_move is not None:
        lower = np.maximum(0, current_spend * (1 - default_max_pct_move))
        upper = current_spend * (1 + default_max_pct_move)

    linear_constraints: List[LinearConstraint] = []

    for c in constraints:
        if c.kind == "locked_cell":
            idx = _cell_index(c.month, c.channel, months, channels)
            val = c.value if c.value is not None else current_spend[idx]
            lower[idx] = upper[idx] = val

        elif c.kind == "bounded_movement":
            pct = c.max_pct_move if c.max_pct_move is not None else default_max_pct_move
            if pct is None:
                continue
            if c.channel and c.month:
                idx = _cell_index(c.month, c.channel, months, channels)
                lower[idx] = max(0, current_spend[idx] * (1 - pct))
                upper[idx] = current_spend[idx] * (1 + pct)
            elif c.channel:
                for m in months:
                    idx = _cell_index(m, c.channel, months, channels)
                    lower[idx] = max(0, current_spend[idx] * (1 - pct))
                    upper[idx] = current_spend[idx] * (1 + pct)
            else:
                lower = np.maximum(0, current_spend * (1 - pct))
                upper = current_spend * (1 + pct)

        elif c.kind == "min_spend_floor":
            months_set = c.months or ([c.month] if c.month else months)
            for m in months_set:
                idx = _cell_index(m, c.channel, months, channels)
                lower[idx] = max(lower[idx], c.value or 0.0)

        elif c.kind == "channel_total":
            row = np.zeros(n)
            for m in months:
                row[_cell_index(m, c.channel, months, channels)] = 1
            target = c.value if c.value is not None else float(
                sum(current_spend[_cell_index(m, c.channel, months, channels)] for m in months)
            )
            linear_constraints.append(LinearConstraint(row, lb=target, ub=target))

        elif c.kind == "month_total":
            row = np.zeros(n)
            for ch in channels:
                row[_cell_index(c.month, ch, months, channels)] = 1
            target = c.value if c.value is not None else float(
                sum(current_spend[_cell_index(c.month, ch, months, channels)] for ch in channels)
            )
            linear_constraints.append(LinearConstraint(row, lb=target, ub=target))

        else:
            raise ValueError(f"Unknown constraint kind: {c.kind}")

    bounds = list(zip(lower, upper))
    return bounds, linear_constraints


# ---------------------------------------------------------------------------
# Optimiser
# ---------------------------------------------------------------------------

VALID_OBJECTIVES = ("fh_gsa", "fh_signups", "dna_kits", "weighted_mix", "expected_value")


def _objective_weight(
    objective: str,
    meta: FHModelMeta,
    ltv: Optional[Dict[str, float]],
    target_outcome_ids: Optional[List[str]],
    weights: Optional[Dict[str, float]],
) -> Dict[str, float]:
    """
    Per-outcome_id weight for the optimiser's scalar objective - the
    instruction document's "optimisation objectives must be explicit" /
    "block generic raw-volume optimisation when mixed metric types are
    present" requirement. `objective` must be one of VALID_OBJECTIVES:
    there is no "maximise everything, whatever unit it's in" option, and an
    outcome_id outside the objective's scope gets weight 0 (excluded), never
    an implicit 1 (silently counted as if it were the same unit as
    everything else - the confirmed defect this replaces: `"fh_gsa"` used to
    mean "every outcome_id that isn't a DNA-kit outcome", which would
    silently fold a Family History sign-up outcome into a GSA objective).

    - `"fh_gsa"`: Family History GSA outcomes - `core.outcomes.fh_gsa_outcome_ids`
      (product=Family History, metric=GSA), or just `target_outcome_ids` if
      given (e.g. a single FH outcome - "maximise FH New GSA").
    - `"fh_signups"`: Family History sign-up outcomes -
      `core.outcomes.fh_signup_outcome_ids` (product=Family History,
      metric=Sign-up), or just `target_outcome_ids` if given. Raises if the
      model has none - distinct from `"fh_gsa"` even when both share a
      segment.
    - `"dna_kits"`: DNA kit sales - `core.outcomes.dna_kit_sale_outcome_ids`,
      or just `target_outcome_ids` if given. Raises if the model has none.
    - `"weighted_mix"`: an analyst-supplied per-outcome_id `weights` dict -
      required explicitly; there is no default mix to fall back to.
    - `"expected_value"`: LTV-weighted total value across every eligible
      (role="primary", or just `target_outcome_ids` if given) outcome_id -
      requires `ltv` to have a finite, non-negative entry for every one of
      them. Fails closed (raises) rather than silently treating a missing
      weight as 0 or 1 - the confirmed "missing value_weight defaults to
      1.0" defect this replaces.
    """
    if objective not in VALID_OBJECTIVES:
        raise ValueError(
            f"objective must be one of {VALID_OBJECTIVES}, got {objective!r}. Generic unlabelled "
            "volume optimisation is not supported here - it would silently combine Family History "
            "GSAs, sign-ups and DNA kit sales into one meaningless total."
        )
    if objective == "fh_gsa":
        eligible = set(target_outcome_ids) if target_outcome_ids else set(fh_gsa_outcome_ids(meta))
        return {s: 1.0 for s in eligible}
    if objective == "fh_signups":
        eligible = set(target_outcome_ids) if target_outcome_ids else set(fh_signup_outcome_ids(meta))
        if not eligible:
            raise ValueError("objective='fh_signups' but this model has no Family History sign-up outcomes.")
        return {s: 1.0 for s in eligible}
    if objective == "dna_kits":
        eligible = set(target_outcome_ids) if target_outcome_ids else set(dna_kit_sale_outcome_ids(meta))
        if not eligible:
            raise ValueError("objective='dna_kits' but this model has no DNA-kit outcomes.")
        return {s: 1.0 for s in eligible}
    if objective == "weighted_mix":
        if not weights:
            raise ValueError("objective='weighted_mix' requires an explicit weights={outcome_id: weight} dict - there is no default mix.")
        return weights
    # objective == "expected_value"
    if not ltv:
        raise ValueError("objective='expected_value' requires ltv={outcome_id: value} - it is the LTV-weighted total across every outcome_id.")
    eligible = set(target_outcome_ids) if target_outcome_ids else set(select_outcome_ids(meta, role="primary"))
    missing = sorted(oid for oid in eligible if oid not in ltv)
    if missing:
        raise ValueError(
            f"objective='expected_value' requires a value weight for every eligible outcome_id, but "
            f"{missing} have none in ltv - a missing weight must never be silently treated as 0 or 1. "
            "Provide ltv entries for all of them, or pass target_outcome_ids to restrict the objective."
        )
    invalid = sorted(oid for oid in eligible if not (isinstance(ltv[oid], (int, float)) and np.isfinite(ltv[oid]) and ltv[oid] >= 0))
    if invalid:
        raise ValueError(
            f"objective='expected_value' requires finite, non-negative value weights; invalid for: {invalid}."
        )
    return {oid: ltv[oid] for oid in eligible}


def _objective_factory(
    months: List[str], channels: List[str], market: str,
    meta: FHModelMeta, params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]], objective: str,
    model_type: str = "shared",
    target_outcome_ids: Optional[List[str]] = None,
    weights: Optional[Dict[str, float]] = None,
):
    weight = _objective_weight(objective, meta, ltv, target_outcome_ids, weights)
    response_fn = _steady_state_response_fn(model_type)

    def neg_total(x: np.ndarray) -> float:
        spend_plan = _unflatten(x, months, channels)
        total = 0.0
        for m in months:
            ref = reference_context_by_month.get(m, {})
            rates = response_fn(market, spend_plan[m], meta, params, ref)
            for oid, rate in rates.items():
                total += rate * WEEKS_PER_MONTH * weight.get(oid, 0.0)
        return -total

    return neg_total


def optimize_scenario(
    current_spend_plan: Dict[str, Dict[str, float]],
    months: List[str],
    channels: List[str],
    market: str,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    objective: str = "fh_gsa",
    constraints: Optional[List[SpendConstraint]] = None,
    conserve_total_budget: bool = True,
    max_iter: int = 200,
    *,
    model_type: str = "shared",
    target_outcome_ids: Optional[List[str]] = None,
    weights: Optional[Dict[str, float]] = None,
    approval: ModelApproval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
) -> Dict:
    """
    Optimise a spend plan. `constraints=None` (or empty) + conserve_total_budget=True
    is the "unconstrained benchmark" mode: reallocate the same total budget
    freely, ignoring locks/floors/bounded-movement - a theoretical-optimum
    comparison point, not a recommended plan. Pass `constraints` for the
    constrained-planning mode analysts will actually use.

    `objective` must be one of `VALID_OBJECTIVES` - see `_objective_weight`'s
    docstring for what each one maximises and what `target_outcome_ids`/
    `weights` do. There is deliberately no generic "maximise volume"
    objective (the instruction document's audit-confirmed defect this
    replaces): every objective states exactly what it sums, and an
    outcome_id outside its scope contributes 0, never an implicit 1.

    `model_type` selects which model's steady-state response function drives
    optimisation and evaluation - `"shared"` (Model A, default) or
    `"market_specific"` (Model C) - see module docstring.

    Raises ApprovalMismatchError unless `approval` matches the current model
    run identity - checked up front, before running the (potentially slow)
    SLSQP optimisation, not just when the final predicted outcomes are
    computed via evaluate_scenario below. Raises ValueError up front too if
    `objective` (plus `target_outcome_ids`/`weights`/`ltv`) isn't resolvable -
    same "fail before the slow optimisation runs" reasoning.
    """
    require_matching_approval(
        approval,
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    )
    constraints = constraints or []
    current_spend = _flatten(current_spend_plan, months, channels)

    bounds, linear_constraints = build_bounds_and_constraints(months, channels, current_spend, constraints)

    if conserve_total_budget:
        total_row = np.ones(len(current_spend))
        linear_constraints.append(LinearConstraint(total_row, lb=current_spend.sum(), ub=current_spend.sum()))

    objective_fn = _objective_factory(
        months, channels, market, meta, params, reference_context_by_month, ltv, objective, model_type,
        target_outcome_ids=target_outcome_ids, weights=weights,
    )

    result = minimize(
        objective_fn,
        current_spend,
        method="SLSQP",
        bounds=bounds,
        constraints=linear_constraints,
        options={"maxiter": max_iter, "ftol": 1e-8},
    )

    optimized_plan = _unflatten(np.clip(result.x, 0, None), months, channels)
    identity_kwargs = dict(
        model_type=model_type, approval=approval, model_run_id=model_run_id, data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint, posterior_fingerprint=posterior_fingerprint,
    )
    predicted = evaluate_scenario(optimized_plan, market, meta, params, reference_context_by_month, ltv, **identity_kwargs)
    current_predicted = evaluate_scenario(current_spend_plan, market, meta, params, reference_context_by_month, ltv, **identity_kwargs)

    # Evaluated via the same objective_fn used for optimisation (not
    # re-derived from the predicted DataFrames) so "current" and "optimised"
    # totals are guaranteed to use the identical weighting - no risk of the
    # two diverging from a second, hand-written copy of the eligibility logic.
    current_objective_value = -float(objective_fn(current_spend))

    return {
        "success": bool(result.success),
        "message": str(result.message),
        "spend_plan": optimized_plan,
        "predicted": predicted,
        "current_predicted": current_predicted,
        "objective_value": -float(result.fun),
        "current_objective_value": current_objective_value,
    }


# ---------------------------------------------------------------------------
# Scenario save/reload
# ---------------------------------------------------------------------------

def scenario_to_dict(
    name: str, market: str, spend_plan: Dict[str, Dict[str, float]],
    objective: str, constraints: List[SpendConstraint], notes: str = "",
) -> dict:
    return {
        "name": name, "market": market, "spend_plan": spend_plan,
        "objective": objective, "constraints": [c.to_dict() for c in constraints], "notes": notes,
    }


def scenario_from_dict(d: dict) -> dict:
    d = dict(d)
    d["constraints"] = [SpendConstraint.from_dict(c) for c in d.get("constraints", [])]
    return d


def compare_scenarios(scenarios: List[Dict], predicted_key: str = "predicted") -> pd.DataFrame:
    """
    Compare total predicted value/volume and spend across saved scenarios.

    `total_value` sums `pred["value"]` skipping any row with no value weight
    (`value is None` - see evaluate_scenario's docstring) - `total_value_is_complete`
    is `False` if any scenario-month had an incomplete-coverage row, so a
    caller can flag the total as a partial sum rather than presenting it as
    exact. `total_gsa` would sum Family History outcomes, sign-ups and DNA
    kit sales into one meaningless count if combined - split into
    `total_fh_gsa`/`total_fh_signups`/`total_dna_kits` instead (never
    combined), same metric-aware discipline as
    core.optimization.evaluate_scenario. `fh_gsa`/`fh_signups`/`dna_kits` are
    month-level totals *duplicated* across every outcome_id row within a
    month (see evaluate_scenario's docstring), so they're deduplicated by
    month before summing across a scenario's months - directly summing them
    across every row would overcount by the number of outcome_ids in each
    month.
    """
    rows = []
    for s in scenarios:
        pred = s[predicted_key]
        total_spend = sum(sum(ch.values()) for ch in s["spend_plan"].values())
        has_product_split = "fh_gsa" in pred.columns and "dna_kits" in pred.columns
        if has_product_split:
            dedup_cols = ["fh_gsa", "dna_kits"] + (["fh_signups"] if "fh_signups" in pred.columns else [])
            by_month = pred.groupby("month")[dedup_cols].first()
            total_fh_gsa = float(by_month["fh_gsa"].sum())
            total_fh_signups = float(by_month["fh_signups"].sum()) if "fh_signups" in dedup_cols else 0.0
            total_dna_kits = float(by_month["dna_kits"].sum())
        else:
            total_fh_gsa = float(pred["predicted_outcome"].sum())
            total_fh_signups = 0.0
            total_dna_kits = 0.0
        total_value_is_complete = (
            bool(pred["total_value_is_complete"].all()) if "total_value_is_complete" in pred else True
        )
        rows.append({
            "scenario": s["name"],
            "market": s.get("market"),
            "total_spend": total_spend,
            "total_value": pred["value"].sum() if "value" in pred else np.nan,
            "total_value_is_complete": total_value_is_complete,
            "total_fh_gsa": total_fh_gsa,
            "total_fh_signups": total_fh_signups,
            "total_dna_kits": total_dna_kits,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Generic single-KPI helpers, kept for reuse
# ---------------------------------------------------------------------------

def calculate_marginal_roi_loglog(
    current_spend: float,
    elasticity: float,
    avg_sales: float,
    avg_spend: float,
) -> float:
    if current_spend <= 0:
        return 0
    return elasticity * (avg_sales / current_spend)


def optimize_budget_marginal_roi(
    total_budget: float,
    channels: List[str],
    elasticities: Dict[str, float],
    current_spend: Dict[str, float],
    avg_sales: float,
    constraints: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, float]:
    n_channels = len(channels)
    constraints = constraints or {}
    default_min, default_max = 0.05, 0.80

    min_bounds, max_bounds = [], []
    for ch in channels:
        min_pct, max_pct = constraints.get(ch, (default_min, default_max))
        min_bounds.append(min_pct * total_budget)
        max_bounds.append(max_pct * total_budget)

    def objective(x):
        total_effect = 0
        for i, ch in enumerate(channels):
            if x[i] > 0:
                total_effect += elasticities[ch] * np.log(x[i])
        return -total_effect

    def gradient(x):
        grad = np.zeros(n_channels)
        for i, ch in enumerate(channels):
            if x[i] > 0:
                grad[i] = -elasticities[ch] / x[i]
        return grad

    bounds = list(zip(min_bounds, max_bounds))
    total_current = sum(current_spend.values())
    if total_current > 0:
        x0 = np.array([
            current_spend.get(ch, total_budget / n_channels) / total_current * total_budget
            for ch in channels
        ])
    else:
        x0 = np.full(n_channels, total_budget / n_channels)
    x0 = np.clip(x0, min_bounds, max_bounds)
    x0 = x0 / x0.sum() * total_budget

    result = minimize(
        objective, x0, method='SLSQP', jac=gradient, bounds=bounds,
        constraints={'type': 'eq', 'fun': lambda x: x.sum() - total_budget},
        options={'maxiter': 1000, 'ftol': 1e-10},
    )

    optimal_spend = {ch: max(0, result.x[i]) for i, ch in enumerate(channels)}
    total_allocated = sum(optimal_spend.values())
    if total_allocated > 0:
        for ch in channels:
            optimal_spend[ch] = optimal_spend[ch] / total_allocated * total_budget
    return optimal_spend


def calculate_expected_lift(
    current_spend: Dict[str, float],
    optimal_spend: Dict[str, float],
    elasticities: Dict[str, float],
    current_sales: float,
) -> Dict[str, float]:
    total_pct_change = 0
    for channel in elasticities:
        curr = current_spend.get(channel, 0)
        opt = optimal_spend.get(channel, 0)
        if curr > 0:
            pct_change_spend = (opt - curr) / curr
            total_pct_change += elasticities[channel] * pct_change_spend

    expected_sales = current_sales * (1 + total_pct_change)
    return {
        'current_sales': current_sales,
        'expected_sales': expected_sales,
        'lift': expected_sales - current_sales,
        'lift_pct': total_pct_change * 100,
    }
