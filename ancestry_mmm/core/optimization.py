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
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize, LinearConstraint

from .approval import ModelApproval, require_matching_approval
from .hierarchical_model import FHModelMeta
from .predict import FHPosteriorParams, steady_state_segment_response

WEEKS_PER_MONTH = 365.25 / 12 / 7  # ~4.348


# ---------------------------------------------------------------------------
# Scenario evaluation (manual mode)
# ---------------------------------------------------------------------------

def evaluate_scenario(
    spend_plan: Dict[str, Dict[str, float]],
    market: str,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    *,
    approval: ModelApproval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
) -> pd.DataFrame:
    """
    Predicted monthly outcomes for a spend plan: {month_label: {channel: spend}}.

    Returns one row per (month, segment) with predicted GSAs (weekly steady-
    state rate x weeks/month) and LTV-weighted value if `ltv` is given.

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
    ltv = ltv or {}
    rows = []
    for month, spend_by_channel in spend_plan.items():
        ref = reference_context_by_month.get(month, {})
        weekly_rate = steady_state_segment_response(market, spend_by_channel, meta, params, ref)
        for seg, rate in weekly_rate.items():
            monthly_gsa = rate * WEEKS_PER_MONTH
            rows.append({
                "month": month,
                "segment": seg,
                "predicted_gsa": monthly_gsa,
                "value": monthly_gsa * ltv.get(seg, 1.0),
                "total_spend": sum(spend_by_channel.values()),
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

def _objective_factory(
    months: List[str], channels: List[str], market: str,
    meta: FHModelMeta, params: FHPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]], objective: str,
):
    weight = ltv if objective == "value" and ltv else {s: 1.0 for s in meta.segments}

    def neg_total(x: np.ndarray) -> float:
        spend_plan = _unflatten(x, months, channels)
        total = 0.0
        for m in months:
            ref = reference_context_by_month.get(m, {})
            rates = steady_state_segment_response(market, spend_plan[m], meta, params, ref)
            for seg, rate in rates.items():
                total += rate * WEEKS_PER_MONTH * weight.get(seg, 1.0)
        return -total

    return neg_total


def optimize_scenario(
    current_spend_plan: Dict[str, Dict[str, float]],
    months: List[str],
    channels: List[str],
    market: str,
    meta: FHModelMeta,
    params: FHPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    objective: str = "value",
    constraints: Optional[List[SpendConstraint]] = None,
    conserve_total_budget: bool = True,
    max_iter: int = 200,
    *,
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

    Raises ApprovalMismatchError unless `approval` matches the current model
    run identity - checked up front, before running the (potentially slow)
    SLSQP optimisation, not just when the final predicted outcomes are
    computed via evaluate_scenario below.
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

    objective_fn = _objective_factory(months, channels, market, meta, params, reference_context_by_month, ltv, objective)

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
        approval=approval, model_run_id=model_run_id, data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint, posterior_fingerprint=posterior_fingerprint,
    )
    predicted = evaluate_scenario(optimized_plan, market, meta, params, reference_context_by_month, ltv, **identity_kwargs)
    current_predicted = evaluate_scenario(current_spend_plan, market, meta, params, reference_context_by_month, ltv, **identity_kwargs)

    return {
        "success": bool(result.success),
        "message": str(result.message),
        "spend_plan": optimized_plan,
        "predicted": predicted,
        "current_predicted": current_predicted,
        "objective_value": -float(result.fun),
        "current_objective_value": float(current_predicted["value"].sum() if objective == "value" else current_predicted["predicted_gsa"].sum()),
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
    """Compare total predicted value/volume and spend across saved scenarios."""
    rows = []
    for s in scenarios:
        pred = s[predicted_key]
        total_spend = sum(sum(ch.values()) for ch in s["spend_plan"].values())
        rows.append({
            "scenario": s["name"],
            "market": s.get("market"),
            "total_spend": total_spend,
            "total_value": pred["value"].sum() if "value" in pred else np.nan,
            "total_gsa": pred["predicted_gsa"].sum(),
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
