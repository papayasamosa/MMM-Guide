from __future__ import annotations

import os

import numpy as np
import pytest

from ancestry_mmm.core.causal_graph import (
    CausalEdge,
    CausalGraph,
    CausalNode,
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_MEDIATED,
    GRAPH_STATUS_APPROVED,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_MEDIATOR,
    NODE_ROLE_OUTCOME,
)
from ancestry_mmm.core.graph_model_compiler import (
    GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION,
    GraphModelCompiler,
    UnsupportedGraphStructureError,
)
from ancestry_mmm.core.observed_mediation import (
    ObservedMediationFitSpec,
    build_observed_mediation_model,
)


def _graph(*, reverse: bool = False, lag: int = 1) -> CausalGraph:
    nodes = [
        CausalNode(node_id="tv", role=NODE_ROLE_INTERVENTION),
        CausalNode(node_id="display", role=NODE_ROLE_INTERVENTION),
        CausalNode(node_id="paid_brand_search_clicks", role=NODE_ROLE_MEDIATOR),
        CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
    ]
    edges = [
        CausalEdge(
            source_node_id="tv",
            target_node_id="paid_brand_search_clicks",
            role=EDGE_ROLE_MEDIATED,
            lag_type="fixed_weeks",
            lag_weeks=lag,
        ),
        CausalEdge(
            source_node_id="display",
            target_node_id="paid_brand_search_clicks",
            role=EDGE_ROLE_MEDIATED,
            lag_type="fixed_weeks",
            lag_weeks=lag,
        ),
        CausalEdge(
            source_node_id="paid_brand_search_clicks",
            target_node_id="fh_new",
            role=EDGE_ROLE_MEDIATED,
        ),
        CausalEdge(
            source_node_id="tv",
            target_node_id="fh_new",
            role=EDGE_ROLE_DIRECT,
        ),
        CausalEdge(
            source_node_id="display",
            target_node_id="fh_new",
            role=EDGE_ROLE_DIRECT,
        ),
    ]
    if reverse:
        edges.append(
            CausalEdge(
                source_node_id="fh_new",
                target_node_id="paid_brand_search_clicks",
                role=EDGE_ROLE_MEDIATED,
            )
        )
    return CausalGraph(
        graph_id="synthetic-observed-search",
        graph_version=1,
        nodes=nodes,
        edges=edges,
        status=GRAPH_STATUS_APPROVED,
    )


def test_observed_mediation_compiles_direct_and_mediated_edges() -> None:
    result = GraphModelCompiler(engine=GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION).compile(
        _graph()
    )
    assert result.observed_mediation is not None
    assert result.observed_mediation.mediator_node_id == "paid_brand_search_clicks"
    assert set(result.observed_mediation.upstream_intervention_node_ids) == {
        "tv",
        "display",
    }
    # Only the direct intervention cells enter the ordinary pathway masks;
    # mediated edges are consumed by the observed-mediator model itself.
    assert len(result.pathway_masks.components) == 2
    assert result.causal_graph_structural_fingerprint


def test_observed_mediation_graph_change_changes_fit_identity() -> None:
    first = GraphModelCompiler(engine=GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION).compile(
        _graph(lag=1)
    )
    changed = GraphModelCompiler(engine=GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION).compile(
        _graph(lag=2)
    )
    assert (
        first.causal_graph_structural_fingerprint
        != changed.causal_graph_structural_fingerprint
    )


def test_observed_mediation_rejects_reverse_direction_and_missing_direct_path() -> None:
    with pytest.raises(
        UnsupportedGraphStructureError,
        match="(does not support edge|originates from an outcome)",
    ):
        GraphModelCompiler(engine=GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION).compile(
            _graph(reverse=True)
        )

    graph = _graph()
    graph.edges = [
        edge
        for edge in graph.edges
        if not (edge.source_node_id == "display" and edge.target_node_id == "fh_new")
    ]
    with pytest.raises(UnsupportedGraphStructureError, match="lacks its direct edge"):
        GraphModelCompiler(engine=GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION).compile(graph)


def test_observed_mediation_model_has_fitted_mediator_and_outcome_likelihoods() -> None:
    rng = np.random.default_rng(7)
    X = rng.uniform(0.0, 1.0, size=(12, 2))
    mediator = np.rint(np.exp(2.0 + 0.8 * X[:, 0] + 0.4 * X[:, 1])).astype(float)
    outcome = np.rint(np.exp(2.2 + 0.4 * X[:, 0] + 0.7 * np.log1p(mediator))).astype(
        float
    )
    model = build_observed_mediation_model(
        upstream_media=X,
        observed_mediator=mediator,
        final_outcome=outcome,
        search_spend=np.linspace(10.0, 40.0, len(X)),
        market_bounds=[(0, len(X))],
        graph=_graph(lag=1),
        fit_spec=ObservedMediationFitSpec(
            upstream_names=("tv", "display"),
            mediator_name="paid_brand_search_clicks",
            outcome_name="fh_new",
            mediator_lag_weeks=1,
            spend_column="fh_brand_search_spend",
        ),
    )
    assert {"mediator_obs", "outcome_obs"} <= {
        variable.name for variable in model.observed_RVs
    }
    assert {
        "direct_media_effect",
        "mediated_search_effect",
        "total_media_effect",
    } <= {variable.name for variable in model.deterministics}
    assert "mediator_spend_beta" in {variable.name for variable in model.free_RVs}
    assert (
        model._observed_mediation_metadata["search_spend_entered_mediator_likelihood"]
        is True
    )
    assert model._observed_mediation_metadata["mediator_lag_index"][:3] == [0, 0, 1]


@pytest.mark.parametrize("lag", [0, 1, 3])
def test_observed_mediation_lag_index_is_consistent_and_market_safe(lag: int) -> None:
    rng = np.random.default_rng(12 + lag)
    X = rng.uniform(0.0, 1.0, size=(10, 2))
    mediator = np.rint(np.exp(2.0 + X[:, 0])).astype(float)
    outcome = np.rint(np.exp(2.2 + 0.4 * X[:, 1] + 0.3 * np.log1p(mediator))).astype(
        float
    )
    graph = _graph(lag=lag)
    model = build_observed_mediation_model(
        upstream_media=X,
        observed_mediator=mediator,
        final_outcome=outcome,
        market_bounds=[(0, 5), (5, 10)],
        graph=graph,
        fit_spec=ObservedMediationFitSpec(
            upstream_names=("tv", "display"),
            mediator_name="paid_brand_search_clicks",
            outcome_name="fh_new",
            mediator_lag_weeks=lag,
        ),
    )
    indices = model._observed_mediation_metadata["mediator_lag_index"]
    assert indices[0] == 0
    assert indices[5] == 5
    assert all(0 <= index < 5 for index in indices[:5])
    assert all(5 <= index < 10 for index in indices[5:])
    for row, index in enumerate(indices):
        start = 0 if row < 5 else 5
        assert index == max(start, row - lag)
    assert model._observed_mediation_metadata["planning_eligible"] is False


@pytest.mark.skipif(
    os.environ.get("RUN_SLOW_MEDIATION_RECOVERY") != "1",
    reason="set RUN_SLOW_MEDIATION_RECOVERY=1 for the PyMC synthetic recovery fit",
)
def test_observed_mediation_synthetic_recovery() -> None:
    """Small posterior recovery smoke test for all three structural paths."""

    import pymc as pm

    rng = np.random.default_rng(31)
    n = 28
    X = rng.uniform(0.0, 2.0, size=(n, 2))
    mediator_mu = np.exp(2.1 + 0.9 * X[:, 0] + 0.5 * X[:, 1])
    mediator = rng.negative_binomial(12.0, 12.0 / (12.0 + mediator_mu)).astype(float)
    outcome_mu = np.exp(
        2.0
        + 0.35 * X[:, 0]
        + 0.25 * X[:, 1]
        + 0.75 * (np.log1p(mediator) - np.log1p(mediator).mean())
    )
    outcome = rng.negative_binomial(15.0, 15.0 / (15.0 + outcome_mu)).astype(float)
    model = build_observed_mediation_model(
        upstream_media=X,
        observed_mediator=mediator,
        final_outcome=outcome,
        market_bounds=[(0, n)],
        graph=_graph(lag=0),
        fit_spec=ObservedMediationFitSpec(
            upstream_names=("tv", "display"),
            mediator_name="paid_brand_search_clicks",
            outcome_name="fh_new",
        ),
    )
    with model:
        trace = pm.sample(
            draws=100,
            tune=100,
            chains=2,
            cores=1,
            target_accept=0.9,
            random_seed=32,
            progressbar=False,
        )
    assert float(trace.posterior["upstream_mediator_beta"].mean()) > 0.0
    assert float(trace.posterior["outcome_mediator_beta"].mean()) > 0.0
    assert float(trace.posterior["direct_upstream_beta"].mean()) > 0.0
