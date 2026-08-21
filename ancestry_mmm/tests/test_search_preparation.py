"""REQ-SEARCH-003 contracts for product-specific Search preparation and graph safety."""

from __future__ import annotations

import numpy as np
import pandas as pd
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
from ancestry_mmm.core.search_preparation import (
    ProductSearchGraphContract,
    SEARCH_PRODUCT_DNA,
    SEARCH_PRODUCT_FAMILY_HISTORY,
    apply_search_mediator_adstock,
    build_product_search_objects,
    mediator_adstock_parameter_name,
    product_search_binding,
    resolve_product_search_spend_coverage,
    search_mediator_equation_diagnostics,
    validate_product_search_graph,
    validate_product_search_objects,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2025-04-06", "2025-04-13", "2025-04-20"]),
            "market": "UK",
            "activity_id": "fh_brand_search",
            "spend": [100.0, np.nan, np.nan],
            "clicks": [10.0, 0.0, np.nan],
        }
    )


def test_fh_and_dna_search_objects_are_distinct_even_with_shared_source_columns():
    fh = build_product_search_objects(SEARCH_PRODUCT_FAMILY_HISTORY)
    dna = build_product_search_objects(SEARCH_PRODUCT_DNA)
    definitions = [*fh, *dna]

    assert fh[0].source_column == dna[0].source_column == "spend"
    assert fh[1].source_column == dna[1].source_column == "clicks"
    assert {item.search_object_id for item in definitions} == {
        "fh_paid_brand_search_spend",
        "fh_paid_brand_search_clicks",
        "dna_paid_brand_search_spend",
        "dna_paid_brand_search_clicks",
    }
    assert validate_product_search_objects(definitions) == ()


def test_missing_spend_is_not_zero_filled_from_zero_clicks():
    prepared, resolution = resolve_product_search_spend_coverage(
        _frame(),
        pd.to_datetime(["2025-04-06", "2025-04-13", "2025-04-20"]),
        product_search_binding(SEARCH_PRODUCT_FAMILY_HISTORY),
    )

    assert prepared.loc[1, "spend_status"] == "missing_spend"
    assert pd.isna(prepared.loc[1, "spend"])
    assert prepared.loc[1, "clicks"] == 0.0
    assert resolution.is_resolved is False
    assert resolution.zero_click_with_unresolved_spend_dates == ("2025-04-13",)


def test_explicit_structural_zero_evidence_resolves_missing_spend_only():
    prepared, resolution = resolve_product_search_spend_coverage(
        _frame(),
        pd.to_datetime(["2025-04-06", "2025-04-13", "2025-04-20"]),
        product_search_binding(SEARCH_PRODUCT_FAMILY_HISTORY),
        structural_zero_dates=["2025-04-13", "2025-04-20"],
    )

    assert prepared["spend"].tolist() == [100.0, 0.0, 0.0]
    assert resolution.is_resolved is True
    assert resolution.structural_zero_dates == ("2025-04-13", "2025-04-20")


def test_search_mediator_adstock_has_its_own_parameter_namespace():
    values = apply_search_mediator_adstock([1.0, 0.0, 0.0], decay_rate=0.5)

    assert values.tolist() == [0.5, 0.25, 0.125]
    assert mediator_adstock_parameter_name("family_history", "brand_tv") == (
        "search_mediator_adstock_decay__family_history__brand_tv"
    )
    assert mediator_adstock_parameter_name("family_history", "brand_tv") != (
        "adstock_decay__brand_tv"
    )


def test_search_equation_diagnostics_reports_flight_overlap_without_deleting_columns():
    result = search_mediator_equation_diagnostics(
        np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]),
        labels=["brand_tv", "radio"],
    )

    assert "vif" in result
    assert result["flight_overlap"] == result["temporal_overlap"]
    assert result["automatic_variable_deletion"] is False


def _graph(*, direct_spend_edge: bool = False) -> CausalGraph:
    nodes = [
        CausalNode(
            node_id="fh_paid_brand_search_spend",
            role=NODE_ROLE_INTERVENTION,
            product="Family History",
            search_object_id="fh_paid_brand_search_spend",
        ),
        CausalNode(
            node_id="fh_paid_brand_search_clicks",
            role=NODE_ROLE_MEDIATOR,
            product="Family History",
            search_object_id="fh_paid_brand_search_clicks",
        ),
        CausalNode(
            node_id="fh_new",
            role=NODE_ROLE_OUTCOME,
            product="Family History",
        ),
    ]
    edges = [
        CausalEdge(
            source_node_id="fh_paid_brand_search_spend",
            target_node_id="fh_paid_brand_search_clicks",
            role=EDGE_ROLE_MEDIATED,
        ),
        CausalEdge(
            source_node_id="fh_paid_brand_search_clicks",
            target_node_id="fh_new",
            role=EDGE_ROLE_MEDIATED,
        ),
    ]
    if direct_spend_edge:
        edges.append(
            CausalEdge(
                source_node_id="fh_paid_brand_search_spend",
                target_node_id="fh_new",
                role=EDGE_ROLE_DIRECT,
            )
        )
    return CausalGraph(
        graph_id="uk-fh-search-contract",
        nodes=nodes,
        edges=edges,
        status=GRAPH_STATUS_APPROVED,
    )


def test_product_search_graph_contract_forbids_spend_direct_path():
    contract = ProductSearchGraphContract(
        binding=product_search_binding(SEARCH_PRODUCT_FAMILY_HISTORY),
        outcome_node_ids=("fh_new",),
    )

    assert validate_product_search_graph(_graph(), contract) == ()
    issues = validate_product_search_graph(_graph(direct_spend_edge=True), contract)
    assert any(
        "Search spend cannot have a direct outcome edge" in issue for issue in issues
    )


def test_observed_mediation_compiler_keeps_product_spend_out_of_direct_upstream_paths():
    binding = product_search_binding(SEARCH_PRODUCT_FAMILY_HISTORY)
    spend, clicks = build_product_search_objects(SEARCH_PRODUCT_FAMILY_HISTORY)
    nodes = [
        CausalNode(
            node_id=binding.spend_object_id,
            role=NODE_ROLE_INTERVENTION,
            product=binding.product_label,
            search_object_id=binding.spend_object_id,
        ),
        CausalNode(
            node_id=binding.delivery_object_id,
            role=NODE_ROLE_MEDIATOR,
            product=binding.product_label,
            search_object_id=binding.delivery_object_id,
        ),
        CausalNode(node_id="brand_tv", role=NODE_ROLE_INTERVENTION),
        CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME, product="Family History"),
    ]
    graph = CausalGraph(
        graph_id="uk-fh-search-compiler",
        nodes=nodes,
        edges=[
            CausalEdge(
                source_node_id=binding.spend_object_id,
                target_node_id=binding.delivery_object_id,
                role=EDGE_ROLE_MEDIATED,
            ),
            CausalEdge(
                source_node_id="brand_tv",
                target_node_id=binding.delivery_object_id,
                role=EDGE_ROLE_MEDIATED,
                lag_type="fixed_weeks",
                lag_weeks=1,
            ),
            CausalEdge(
                source_node_id=binding.delivery_object_id,
                target_node_id="fh_new",
                role=EDGE_ROLE_MEDIATED,
            ),
            CausalEdge(
                source_node_id="brand_tv",
                target_node_id="fh_new",
                role=EDGE_ROLE_DIRECT,
            ),
        ],
        status=GRAPH_STATUS_APPROVED,
    )
    result = GraphModelCompiler(
        engine=GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION,
        search_objects=[spend, clicks],
    ).compile(graph)

    assert result.observed_mediation is not None
    assert result.observed_mediation.spend_node_id == binding.spend_object_id
    assert result.observed_mediation.upstream_intervention_node_ids == ("brand_tv",)
    assert result.observed_mediation.direct_edge_ids == (
        next(
            edge.edge_id
            for edge in graph.edges
            if edge.source_node_id == "brand_tv" and edge.target_node_id == "fh_new"
        ),
    )

    bad_graph = CausalGraph.from_dict(graph.to_dict())
    bad_graph.edges.append(
        CausalEdge(
            source_node_id=binding.spend_object_id,
            target_node_id="fh_new",
            role=EDGE_ROLE_DIRECT,
        )
    )
    with pytest.raises(UnsupportedGraphStructureError):
        GraphModelCompiler(
            engine=GRAPH_ENGINE_PYMC_OBSERVED_MEDIATION,
            search_objects=[spend, clicks],
        ).compile(bad_graph)
