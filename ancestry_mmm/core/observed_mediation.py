"""PyMC observed-mediator model for governed Paid Brand Search tests.

This is a deliberately small engine capability, not a post-hoc attribution
reallocation.  It fits three linked pieces in one PyMC model:

* upstream intervention -> observed Paid Brand Search delivery;
* upstream intervention -> final outcome (direct pathway);
* observed Paid Brand Search delivery -> final outcome (mediated pathway).

Spend and delivery stay separate.  The observed mediator is used at its
governed lag in the outcome likelihood, while the model-generated mediator
state is used for outcome-scale intervention deterministics.  The causal
graph is compiled before the model is built and its structural fingerprint is
stored on the model for stale-fit detection.

This capability intentionally does not fabricate branded demand, organic
search, direct navigation, or a cap.  Those are different Search objects and
remain outside this historical observed-mediator formulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from .causal_graph import CausalGraph
from .graph_model_compiler import (
    GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION,
    GraphModelCompiler,
    ObservedMediationGraphPlan,
)


class ObservedMediationValidationError(ValueError):
    """Raised when the observed-mediator contract cannot be fitted safely."""


@dataclass(frozen=True)
class ObservedMediationFitSpec:
    """Explicit array and graph identity for one observed-mediator fit."""

    upstream_names: tuple[str, ...]
    mediator_name: str
    outcome_name: str
    mediator_lag_weeks: int = 0
    upstream_unit: str = "governed_delivery"
    mediator_unit: str = "clicks"
    spend_column: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.upstream_names:
            raise ObservedMediationValidationError(
                "at least one upstream intervention is required"
            )
        if len(set(self.upstream_names)) != len(self.upstream_names):
            raise ObservedMediationValidationError("upstream names must be unique")
        if not self.mediator_name or not self.outcome_name:
            raise ObservedMediationValidationError(
                "mediator_name and outcome_name are required"
            )
        if self.mediator_lag_weeks < 0:
            raise ObservedMediationValidationError(
                "mediator_lag_weeks must be non-negative"
            )
        if self.spend_column is not None and not str(self.spend_column).strip():
            raise ObservedMediationValidationError(
                "spend_column must be non-empty when supplied"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "upstream_names": list(self.upstream_names),
            "mediator_name": self.mediator_name,
            "outcome_name": self.outcome_name,
            "mediator_lag_weeks": self.mediator_lag_weeks,
            "upstream_unit": self.upstream_unit,
            "mediator_unit": self.mediator_unit,
            "spend_column": self.spend_column,
        }


def compile_observed_mediation_plan(
    graph: CausalGraph,
    *,
    mediator_node_id: Optional[str] = None,
    activity_definitions: Optional[Sequence[Any]] = None,
) -> tuple[ObservedMediationGraphPlan, str, int]:
    """Compile and fingerprint the approved graph for this model."""

    result = GraphModelCompiler(
        engine=GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION,
        activity_definitions=activity_definitions,
    ).compile(graph)
    if result.observed_mediation is None:  # pragma: no cover - compiler invariant
        raise ObservedMediationValidationError(
            "observed mediation compiler returned no observed-mediation plan"
        )
    edges_by_id = {edge.edge_id: edge for edge in graph.edges}
    lag_values = {
        int(edges_by_id[edge_id].lag_weeks or 0)
        for edge_id in result.observed_mediation.upstream_to_mediator_edge_ids
    }
    if len(lag_values) != 1:
        raise ObservedMediationValidationError(
            "all upstream-to-mediator edges must use the same lag in the "
            "current observed-mediation engine"
        )
    return (
        result.observed_mediation,
        result.causal_graph_structural_fingerprint,
        next(iter(lag_values)),
    )


def _as_matrix(value: Sequence[Sequence[float]] | np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != 2 or array.shape[0] < 4 or array.shape[1] < 1:
        raise ObservedMediationValidationError(
            f"{name} must be a two-dimensional array with at least four rows "
            "and one column"
        )
    if not np.isfinite(array).all() or np.any(array < 0):
        raise ObservedMediationValidationError(
            f"{name} must contain finite non-negative values"
        )
    return array


def _as_vector(value: Sequence[float] | np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != 1 or array.size < 4:
        raise ObservedMediationValidationError(
            f"{name} must be a one-dimensional vector with at least four rows"
        )
    if not np.isfinite(array).all() or np.any(array < 0):
        raise ObservedMediationValidationError(
            f"{name} must contain finite non-negative values"
        )
    return array


def _market_lag_indices(
    n_obs: int, market_bounds: Sequence[tuple[int, int]], lag_weeks: int
) -> np.ndarray:
    if lag_weeks < 0:
        raise ObservedMediationValidationError("lag_weeks must be non-negative")
    result = np.zeros(n_obs, dtype=int)
    for start, end in market_bounds:
        if start < 0 or end > n_obs or end <= start:
            raise ObservedMediationValidationError("invalid market bounds")
        for index in range(start, end):
            result[index] = max(start, index - lag_weeks)
    return result


def build_observed_mediation_model(
    *,
    upstream_media: Sequence[Sequence[float]] | np.ndarray,
    observed_mediator: Sequence[float] | np.ndarray,
    final_outcome: Sequence[float] | np.ndarray,
    search_spend: Optional[Sequence[float] | np.ndarray] = None,
    market_bounds: Sequence[tuple[int, int]],
    graph: CausalGraph,
    fit_spec: ObservedMediationFitSpec,
    mediator_node_id: Optional[str] = None,
    prior_config: Optional[Mapping[str, float]] = None,
):
    """Build the supported PyMC observed-mediator model.

    ``upstream_media`` is a governed physical model-input matrix.  Paid Brand
    Search spend is a separate optional predictor of the observed mediator;
    it is never substituted for the delivery matrix or entered as a direct
    final-outcome intervention.  When a governed spend column is available,
    callers must provide it explicitly through ``search_spend`` and
    ``fit_spec.spend_column``.
    """

    import pymc as pm
    import pytensor.tensor as pt

    plan, graph_fingerprint, graph_lag = compile_observed_mediation_plan(
        graph, mediator_node_id=mediator_node_id
    )
    if tuple(plan.upstream_intervention_node_ids) != fit_spec.upstream_names:
        raise ObservedMediationValidationError(
            "fit_spec.upstream_names must match the compiled graph's upstream "
            "intervention node order"
        )
    if plan.mediator_node_id != fit_spec.mediator_name:
        raise ObservedMediationValidationError(
            "fit_spec.mediator_name must match the compiled graph mediator node"
        )
    if plan.outcome_node_id != fit_spec.outcome_name:
        raise ObservedMediationValidationError(
            "fit_spec.outcome_name must match the compiled graph outcome node"
        )
    if fit_spec.mediator_lag_weeks != graph_lag:
        raise ObservedMediationValidationError(
            "fit_spec.mediator_lag_weeks must match the graph edge lag"
        )

    X = _as_matrix(upstream_media, "upstream_media")
    mediator = _as_vector(observed_mediator, "observed_mediator")
    outcome = _as_vector(final_outcome, "final_outcome")
    spend = None if search_spend is None else _as_vector(search_spend, "search_spend")
    if fit_spec.spend_column is not None and spend is None:
        raise ObservedMediationValidationError(
            "fit_spec.spend_column is governed but search_spend was not supplied"
        )
    if spend is not None and fit_spec.spend_column is None:
        raise ObservedMediationValidationError(
            "search_spend requires fit_spec.spend_column so spend and delivery "
            "retain distinct governed identities"
        )
    if not (X.shape[0] == mediator.size == outcome.size):
        raise ObservedMediationValidationError(
            "upstream_media, observed_mediator, and final_outcome must share rows"
        )
    if spend is not None and spend.size != X.shape[0]:
        raise ObservedMediationValidationError(
            "search_spend must have the same rows as upstream_media"
        )
    if len(market_bounds) == 0:
        raise ObservedMediationValidationError("market_bounds must not be empty")
    if sum(end - start for start, end in market_bounds) != X.shape[0]:
        raise ObservedMediationValidationError(
            "market_bounds must cover every observation exactly once"
        )

    lag_index = _market_lag_indices(X.shape[0], market_bounds, graph_lag)
    x_mean = X.mean(axis=0)
    x_scale = X.std(axis=0)
    x_scale = np.where(x_scale > 0, x_scale, 1.0)
    X_std = (X - x_mean) / x_scale
    mediator_log = np.log1p(mediator)
    mediator_center = float(mediator_log.mean())
    mediator_scale = float(mediator_log.std())
    mediator_scale = mediator_scale if mediator_scale > 0 else 1.0
    mediator_observed_std = (mediator_log - mediator_center) / mediator_scale
    spend_center = spend_scale = None
    spend_observed_std = None
    if spend is not None:
        spend_log = np.log1p(spend)
        spend_center = float(spend_log.mean())
        spend_scale = float(spend_log.std())
        spend_scale = spend_scale if spend_scale > 0 else 1.0
        spend_observed_std = (spend_log - spend_center) / spend_scale
    y_mean = max(float(outcome.mean()), 1.0)
    prior = dict(prior_config or {})

    with pm.Model() as model:
        model.add_coord("obs", np.arange(X.shape[0]))
        model.add_coord("upstream", list(fit_spec.upstream_names))

        upstream_mediator_beta = pm.HalfNormal(
            "upstream_mediator_beta",
            sigma=float(prior.get("upstream_mediator_sigma", 0.5)),
            dims="upstream",
        )
        mediator_intercept = pm.Normal(
            "mediator_intercept",
            mu=float(np.log(max(mediator.mean(), 1.0))),
            sigma=float(prior.get("mediator_intercept_sigma", 1.0)),
        )
        mediator_eta = mediator_intercept + pm.math.dot(
            pt.as_tensor_variable(X_std), upstream_mediator_beta
        )
        if spend_observed_std is not None:
            mediator_spend_beta = pm.HalfNormal(
                "mediator_spend_beta",
                sigma=float(prior.get("mediator_spend_sigma", 0.5)),
            )
            mediator_eta = mediator_eta + mediator_spend_beta * pt.as_tensor_variable(
                spend_observed_std
            )
        mediator_mu = pm.Deterministic(
            "mediator_mu", pt.clip(pt.exp(mediator_eta), 1e-6, 1e12), dims="obs"
        )
        mediator_alpha = pm.Gamma(
            "mediator_alpha",
            alpha=float(prior.get("mediator_alpha_shape", 2.0)),
            beta=float(prior.get("mediator_alpha_rate", 0.1)),
        )
        pm.NegativeBinomial(
            "mediator_obs",
            mu=mediator_mu,
            alpha=mediator_alpha,
            observed=np.rint(mediator).astype(int),
            dims="obs",
        )

        direct_beta = pm.HalfNormal(
            "direct_upstream_beta",
            sigma=float(prior.get("direct_upstream_sigma", 0.5)),
            dims="upstream",
        )
        outcome_mediator_beta = pm.HalfNormal(
            "outcome_mediator_beta",
            sigma=float(prior.get("outcome_mediator_sigma", 0.5)),
        )
        outcome_intercept = pm.Normal(
            "outcome_intercept",
            mu=float(np.log(y_mean)),
            sigma=float(prior.get("outcome_intercept_sigma", 1.0)),
        )
        direct_eta = pm.math.dot(pt.as_tensor_variable(X_std), direct_beta)
        # The observed outcome likelihood and all intervention deterministics
        # use the same market-safe lag index.  A previous prototype used
        # contemporaneous observed clicks in this likelihood while using
        # lagged generated clicks for intervention reporting, which made the
        # fitted estimand and reported effect disagree.
        observed_mediator_lagged = pt.as_tensor_variable(mediator_observed_std)[lag_index]
        outcome_eta = outcome_intercept + direct_eta + (
            outcome_mediator_beta * observed_mediator_lagged
        )
        mu = pm.Deterministic(
            "mu", pt.clip(pt.exp(outcome_eta), 1e-6, 1e12), dims="obs"
        )
        outcome_alpha = pm.Gamma(
            "outcome_alpha",
            alpha=float(prior.get("outcome_alpha_shape", 2.0)),
            beta=float(prior.get("outcome_alpha_rate", 0.1)),
        )
        pm.NegativeBinomial(
            "outcome_obs",
            mu=mu,
            alpha=outcome_alpha,
            observed=np.rint(outcome).astype(int),
            dims="obs",
        )

        # The model-generated mediator is used for intervention deterministics;
        # observed clicks are used only in the fitted outcome likelihood.  The
        # baseline is the no-upstream mediator state, with the same lag rule.
        mediator_mu_lagged = mediator_mu[lag_index]
        mediator_baseline = pt.ones(X.shape[0]) * pt.exp(mediator_intercept)
        mediator_baseline_lagged = mediator_baseline[lag_index]
        mediator_scale_tensor = pt.as_tensor_variable(mediator_scale)
        mediator_center_tensor = pt.as_tensor_variable(mediator_center)
        generated_mediator_std = (
            pt.log1p(mediator_mu_lagged) - mediator_center_tensor
        ) / mediator_scale_tensor
        baseline_mediator_std = (
            pt.log1p(mediator_baseline_lagged) - mediator_center_tensor
        ) / mediator_scale_tensor
        mu_without_upstream = pm.Deterministic(
            "mu_without_upstream",
            pt.clip(
                pt.exp(outcome_intercept + outcome_mediator_beta * baseline_mediator_std),
                1e-6,
                1e12,
            ),
            dims="obs",
        )
        mu_direct_only = pm.Deterministic(
            "mu_direct_only",
            pt.clip(
                pt.exp(
                    outcome_intercept
                    + direct_eta
                    + outcome_mediator_beta * baseline_mediator_std
                ),
                1e-6,
                1e12,
            ),
            dims="obs",
        )
        mu_generated = pm.Deterministic(
            "mu_generated_mediator",
            pt.clip(
                pt.exp(
                    outcome_intercept
                    + direct_eta
                    + outcome_mediator_beta * generated_mediator_std
                ),
                1e-6,
                1e12,
            ),
            dims="obs",
        )
        pm.Deterministic(
            "direct_media_effect",
            mu_direct_only - mu_without_upstream,
            dims="obs",
        )
        pm.Deterministic(
            "mediated_search_effect",
            mu_generated - mu_direct_only,
            dims="obs",
        )
        pm.Deterministic(
            "total_media_effect",
            mu_generated - mu_without_upstream,
            dims="obs",
        )

    model._observed_mediation_metadata = {
        "engine": GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION,
        "formulation_id": "observed_mediation_v1",
        "graph_plan": plan.to_dict(),
        "causal_graph_structural_fingerprint": graph_fingerprint,
        "fit_spec": fit_spec.to_dict(),
        "upstream_mean": x_mean.tolist(),
        "upstream_scale": x_scale.tolist(),
        "mediator_center": mediator_center,
        "mediator_scale": mediator_scale,
        "spend_column": fit_spec.spend_column,
        "spend_center": spend_center,
        "spend_scale": spend_scale,
        "search_spend_entered_mediator_likelihood": spend is not None,
        "mediator_lag_index": lag_index.tolist(),
        "planning_eligible": False,
        "optimisation_eligible": False,
    }
    return model


__all__ = [
    "ObservedMediationFitSpec",
    "ObservedMediationValidationError",
    "build_observed_mediation_model",
    "compile_observed_mediation_plan",
]
