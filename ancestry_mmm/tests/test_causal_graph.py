"""Tests for core.causal_graph (REQ-GRAPH-001) - the UI-independent causal
graph domain: typed nodes/edges/layout, structural-vs-layout fingerprints,
deterministic validation, model-plan preview, and invalidation propagation.
"""

from dataclasses import replace

import pytest

from ancestry_mmm.core.causal_graph import (
    CAUSAL_GRAPH_SCHEMA_VERSION,
    EDGE_ROLE_CAPACITY_CONSTRAINED,
    EDGE_ROLE_CROSS_PRODUCT_HALO,
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
    EDGE_ROLE_MODERATED,
    GRAPH_STATUS_APPROVED,
    GRAPH_STATUS_DRAFT,
    NODE_ROLE_CAPACITY_OR_CAP,
    NODE_ROLE_CONTROL_OR_CONFOUNDER,
    NODE_ROLE_EXCLUDED,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_MEDIATOR,
    NODE_ROLE_OUTCOME,
    CausalEdge,
    CausalGraph,
    CausalGraphDependencyIssue,
    CausalNode,
    EngineCapabilities,
    GraphLayout,
    NodePosition,
    build_compilation_plan_preview,
    current_structural_fingerprint_for_identity,
    graph_dependency_issues,
    graph_versions_for_export,
    validate_causal_graph,
)


def _minimal_valid_graph(**overrides) -> CausalGraph:
    nodes = overrides.pop("nodes", None) or [
        CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION),
        CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
    ]
    edges = overrides.pop("edges", None) or [
        CausalEdge(
            source_node_id="tv_spend", target_node_id="fh_new", role=EDGE_ROLE_DIRECT
        ),
    ]
    defaults = dict(graph_id="g1", graph_version=1, nodes=nodes, edges=edges)
    defaults.update(overrides)
    return CausalGraph(**defaults)


class TestCausalNodeRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        node = CausalNode(
            node_id="tv_spend",
            label="TV Spend",
            role=NODE_ROLE_INTERVENTION,
            product="family_history",
            segment="uk",
            market="uk",
            metadata={"colour": "blue"},
        )
        restored = CausalNode.from_dict(node.to_dict())
        assert restored == node


class TestCausalEdgeRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        edge = CausalEdge(
            source_node_id="tv_spend",
            target_node_id="fh_new",
            role=EDGE_ROLE_DIRECT,
            lag_type="fixed_weeks",
            lag_weeks=2,
        )
        restored = CausalEdge.from_dict(edge.to_dict())
        assert restored == edge

    def test_edge_id_is_deterministic(self):
        a = CausalEdge(
            source_node_id="tv_spend", target_node_id="fh_new", role=EDGE_ROLE_DIRECT
        )
        b = CausalEdge(
            source_node_id="tv_spend", target_node_id="fh_new", role=EDGE_ROLE_DIRECT
        )
        assert a.edge_id == b.edge_id
        assert a.edge_id != ""

    def test_edge_id_differs_by_role(self):
        a = CausalEdge(
            source_node_id="tv_spend", target_node_id="fh_new", role=EDGE_ROLE_DIRECT
        )
        b = CausalEdge(
            source_node_id="tv_spend",
            target_node_id="fh_new",
            role=EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
        )
        assert a.edge_id != b.edge_id


class TestGraphLayoutRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        layout = GraphLayout(
            positions={"tv_spend": NodePosition(x=10.0, y=20.0)},
            metadata={"zoom": 1.5},
        )
        restored = GraphLayout.from_dict(layout.to_dict())
        assert restored == layout

    def test_from_dict_none_gives_empty_layout(self):
        assert GraphLayout.from_dict(None) == GraphLayout()


class TestCausalGraphRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        graph = _minimal_valid_graph(status=GRAPH_STATUS_APPROVED, created_by="analyst")
        restored = CausalGraph.from_dict(graph.to_dict())
        assert restored == graph

    def test_missing_graph_id_raises(self):
        with pytest.raises(KeyError):
            CausalGraph.from_dict({"nodes": [], "edges": []})

    def test_future_schema_version_raises(self):
        payload = _minimal_valid_graph().to_dict()
        payload["schema_version"] = CAUSAL_GRAPH_SCHEMA_VERSION + 1
        with pytest.raises(ValueError, match="Unsupported causal graph schema_version"):
            CausalGraph.from_dict(payload)

    def test_missing_schema_version_defaults_to_current(self):
        payload = _minimal_valid_graph().to_dict()
        del payload["schema_version"]
        restored = CausalGraph.from_dict(payload)
        assert restored.schema_version == CAUSAL_GRAPH_SCHEMA_VERSION


class TestFingerprintDeterminism:
    def test_structural_fingerprint_is_deterministic(self):
        graph = _minimal_valid_graph()
        assert graph.structural_fingerprint() == graph.structural_fingerprint()

    def test_structural_fingerprint_independent_of_node_and_edge_order(self):
        n1 = CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION)
        n2 = CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME)
        e = CausalEdge(
            source_node_id="tv_spend", target_node_id="fh_new", role=EDGE_ROLE_DIRECT
        )
        a = _minimal_valid_graph(nodes=[n1, n2], edges=[e])
        b = _minimal_valid_graph(nodes=[n2, n1], edges=[e])
        assert a.structural_fingerprint() == b.structural_fingerprint()

    def test_layout_only_edit_does_not_change_structural_fingerprint(self):
        graph = _minimal_valid_graph()
        before = graph.structural_fingerprint()
        graph.layout = GraphLayout(positions={"tv_spend": NodePosition(x=1.0, y=2.0)})
        after = graph.structural_fingerprint()
        assert before == after

    def test_layout_only_edit_changes_layout_fingerprint(self):
        graph = _minimal_valid_graph()
        before = graph.layout_fingerprint()
        graph.layout = GraphLayout(positions={"tv_spend": NodePosition(x=1.0, y=2.0)})
        after = graph.layout_fingerprint()
        assert before != after

    def test_structural_edit_changes_structural_fingerprint(self):
        graph = _minimal_valid_graph()
        before = graph.structural_fingerprint()
        graph.nodes.append(
            CausalNode(node_id="search_spend", role=NODE_ROLE_INTERVENTION)
        )
        after = graph.structural_fingerprint()
        assert before != after

    def test_structural_edit_does_not_change_layout_fingerprint(self):
        graph = _minimal_valid_graph()
        before = graph.layout_fingerprint()
        graph.nodes.append(
            CausalNode(node_id="search_spend", role=NODE_ROLE_INTERVENTION)
        )
        after = graph.layout_fingerprint()
        assert before == after

    def test_status_change_does_not_change_structural_fingerprint(self):
        graph = _minimal_valid_graph(status=GRAPH_STATUS_DRAFT)
        before = graph.structural_fingerprint()
        graph.status = GRAPH_STATUS_APPROVED
        after = graph.structural_fingerprint()
        assert before == after


class TestValidateCausalGraphStructure:
    def test_minimal_valid_graph_has_no_errors(self):
        result = validate_causal_graph(_minimal_valid_graph())
        assert result.is_valid
        assert result.errors == ()

    def test_duplicate_node_id_is_an_error(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="tv_spend", role=NODE_ROLE_OUTCOME),
            ],
            edges=[],
        )
        result = validate_causal_graph(graph)
        assert any("duplicate node_id" in e.lower() for e in result.errors)

    def test_duplicate_edge_id_is_an_error(self):
        edge = CausalEdge(
            source_node_id="tv_spend", target_node_id="fh_new", role=EDGE_ROLE_DIRECT
        )
        duplicate = CausalEdge(
            source_node_id="tv_spend",
            target_node_id="fh_new",
            role=EDGE_ROLE_DIRECT,
            edge_id=edge.edge_id,
        )
        graph = _minimal_valid_graph(edges=[edge, duplicate])
        result = validate_causal_graph(graph)
        assert any("duplicate edge_id" in e.lower() for e in result.errors)

    def test_edge_with_unknown_source_is_an_error(self):
        graph = _minimal_valid_graph(
            edges=[
                CausalEdge(
                    source_node_id="does_not_exist",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                )
            ]
        )
        result = validate_causal_graph(graph)
        assert any("unknown source node_id" in e.lower() for e in result.errors)

    def test_edge_with_unknown_target_is_an_error(self):
        graph = _minimal_valid_graph(
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="does_not_exist",
                    role=EDGE_ROLE_DIRECT,
                )
            ]
        )
        result = validate_causal_graph(graph)
        assert any("unknown target node_id" in e.lower() for e in result.errors)

    def test_unknown_node_role_is_an_error(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="tv_spend", role="not_a_real_role"),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            ]
        )
        result = validate_causal_graph(graph)
        assert any("unknown role" in e.lower() for e in result.errors)

    def test_unknown_edge_role_is_an_error(self):
        graph = _minimal_valid_graph(
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role="not_a_real_role",
                )
            ]
        )
        result = validate_causal_graph(graph)
        assert any("unknown role" in e.lower() for e in result.errors)

    def test_missing_outcome_node_is_an_error(self):
        graph = _minimal_valid_graph(
            nodes=[CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION)],
            edges=[],
        )
        result = validate_causal_graph(graph)
        assert any("at least one outcome node" in e.lower() for e in result.errors)


class TestProhibitedEdgeDirection:
    def test_edge_targeting_intervention_is_an_error(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="fh_new",
                    target_node_id="tv_spend",
                    role=EDGE_ROLE_DIRECT,
                )
            ],
        )
        result = validate_causal_graph(graph)
        assert any("targets an intervention node" in e.lower() for e in result.errors)

    def test_structural_edge_from_outcome_is_an_error(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
                CausalNode(node_id="fh_gsa", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="fh_new",
                    target_node_id="fh_gsa",
                    role=EDGE_ROLE_DIRECT,
                )
            ],
        )
        result = validate_causal_graph(graph)
        assert any(
            "originates from an outcome node" in e.lower() for e in result.errors
        )

    def test_diagnostic_only_edge_from_outcome_is_allowed(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
                CausalNode(node_id="fh_gsa", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="fh_new",
                    target_node_id="fh_gsa",
                    role=EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
                )
            ],
        )
        result = validate_causal_graph(graph)
        assert result.is_valid


class TestIncompatibleRoleChecks:
    def test_capacity_constrained_edge_must_target_capacity_node(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_CAPACITY_CONSTRAINED,
                )
            ],
        )
        result = validate_causal_graph(graph)
        assert any("capacity_constrained" in e for e in result.errors)

    def test_capacity_constrained_edge_targeting_capacity_node_is_valid(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="search_cap", role=NODE_ROLE_CAPACITY_OR_CAP),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="search_cap",
                    role=EDGE_ROLE_CAPACITY_CONSTRAINED,
                ),
                CausalEdge(
                    source_node_id="search_cap",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                ),
            ],
        )
        result = validate_causal_graph(graph)
        assert result.is_valid

    def test_moderated_edge_must_originate_from_moderator_node(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_MODERATED,
                )
            ],
        )
        result = validate_causal_graph(graph)
        assert any("moderated" in e for e in result.errors)

    def test_cross_product_halo_edge_same_product_is_an_error(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="dna_kit", role=NODE_ROLE_MEDIATOR, product="dna"),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME, product="dna"),
            ],
            edges=[
                CausalEdge(
                    source_node_id="dna_kit",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_CROSS_PRODUCT_HALO,
                )
            ],
        )
        result = validate_causal_graph(graph)
        assert any("cross_product_halo" in e for e in result.errors)

    def test_cross_product_halo_edge_different_product_is_valid(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="dna_kit", role=NODE_ROLE_MEDIATOR, product="dna"),
                CausalNode(
                    node_id="fh_new", role=NODE_ROLE_OUTCOME, product="family_history"
                ),
            ],
            edges=[
                CausalEdge(
                    source_node_id="dna_kit",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_CROSS_PRODUCT_HALO,
                )
            ],
        )
        result = validate_causal_graph(graph)
        assert result.is_valid

    def test_excluded_node_with_non_excluded_edge_is_an_error(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="tv_spend", role=NODE_ROLE_EXCLUDED),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                )
            ],
        )
        result = validate_causal_graph(graph)
        assert any("excluded" in e.lower() for e in result.errors)

    def test_excluded_diagnostic_edge_with_planning_metadata_is_an_error(self):
        graph = _minimal_valid_graph(
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
                    metadata={"include_in_planning": True},
                )
            ]
        )
        result = validate_causal_graph(graph)
        assert any("planning-eligible metadata" in e.lower() for e in result.errors)


class TestBadControlCheck:
    def test_control_between_intervention_and_outcome_is_a_bad_control(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="mid", role=NODE_ROLE_CONTROL_OR_CONFOUNDER),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="mid",
                    role=EDGE_ROLE_DIRECT,
                ),
                CausalEdge(
                    source_node_id="mid", target_node_id="fh_new", role=EDGE_ROLE_DIRECT
                ),
            ],
        )
        result = validate_causal_graph(graph)
        assert any("bad control" in e.lower() for e in result.errors)

    def test_control_not_on_a_path_is_not_flagged(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="tv_spend", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="season", role=NODE_ROLE_CONTROL_OR_CONFOUNDER),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                ),
            ],
        )
        result = validate_causal_graph(graph)
        assert result.is_valid


class TestCycleDetection:
    def test_diagnostic_only_back_edge_is_not_a_structural_cycle(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="a", role=NODE_ROLE_MEDIATOR),
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="a", target_node_id="fh_new", role=EDGE_ROLE_DIRECT
                ),
                CausalEdge(
                    source_node_id="fh_new",
                    target_node_id="a",
                    role=EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
                ),
            ],
        )
        # the diagnostic-only edge back to `a` is excluded from the
        # structural subgraph, so this is NOT actually a cycle - sanity
        # check that diagnostic-only edges don't participate in cycle
        # detection.
        result = validate_causal_graph(graph)
        assert not any("directed cycle" in e.lower() for e in result.errors)

    def test_genuine_structural_cycle_is_an_error(self):
        a = CausalNode(node_id="a", role=NODE_ROLE_MEDIATOR)
        b = CausalNode(node_id="b", role=NODE_ROLE_MEDIATOR)
        outcome = CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME)
        graph = _minimal_valid_graph(
            nodes=[a, b, outcome],
            edges=[
                CausalEdge(
                    source_node_id="a", target_node_id="b", role=EDGE_ROLE_DIRECT
                ),
                CausalEdge(
                    source_node_id="b", target_node_id="a", role=EDGE_ROLE_DIRECT
                ),
                CausalEdge(
                    source_node_id="b", target_node_id="fh_new", role=EDGE_ROLE_DIRECT
                ),
            ],
        )
        result = validate_causal_graph(graph)
        assert any("directed cycle" in e.lower() for e in result.errors)

    def test_capacity_only_cycle_relaxed_when_engine_capability_allows(self):
        cap_a = CausalNode(node_id="cap_a", role=NODE_ROLE_CAPACITY_OR_CAP)
        cap_b = CausalNode(node_id="cap_b", role=NODE_ROLE_CAPACITY_OR_CAP)
        outcome = CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME)
        graph = _minimal_valid_graph(
            nodes=[cap_a, cap_b, outcome],
            edges=[
                CausalEdge(
                    source_node_id="cap_a",
                    target_node_id="cap_b",
                    role=EDGE_ROLE_DIRECT,
                ),
                CausalEdge(
                    source_node_id="cap_b",
                    target_node_id="cap_a",
                    role=EDGE_ROLE_DIRECT,
                ),
                CausalEdge(
                    source_node_id="cap_b",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                ),
            ],
        )
        blocked = validate_causal_graph(graph)
        assert any("directed cycle" in e.lower() for e in blocked.errors)

        relaxed = validate_causal_graph(
            graph,
            engine_capabilities=EngineCapabilities(allow_capacity_only_cycles=True),
        )
        assert not any("directed cycle" in e.lower() for e in relaxed.errors)

    def test_capacity_only_cycle_not_relaxed_by_default(self):
        cap_a = CausalNode(node_id="cap_a", role=NODE_ROLE_CAPACITY_OR_CAP)
        cap_b = CausalNode(node_id="cap_b", role=NODE_ROLE_CAPACITY_OR_CAP)
        outcome = CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME)
        graph = _minimal_valid_graph(
            nodes=[cap_a, cap_b, outcome],
            edges=[
                CausalEdge(
                    source_node_id="cap_a",
                    target_node_id="cap_b",
                    role=EDGE_ROLE_DIRECT,
                ),
                CausalEdge(
                    source_node_id="cap_b",
                    target_node_id="cap_a",
                    role=EDGE_ROLE_DIRECT,
                ),
                CausalEdge(
                    source_node_id="cap_b",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                ),
            ],
        )
        # default EngineCapabilities() - never permissive by default.
        result = validate_causal_graph(graph)
        assert any("directed cycle" in e.lower() for e in result.errors)


class TestLagValidation:
    def test_unknown_lag_type_is_an_error(self):
        graph = _minimal_valid_graph(
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                    lag_type="not_a_real_lag_type",
                )
            ]
        )
        result = validate_causal_graph(graph)
        assert any("unknown lag_type" in e.lower() for e in result.errors)

    def test_fixed_weeks_without_lag_weeks_is_an_error(self):
        graph = _minimal_valid_graph(
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                    lag_type="fixed_weeks",
                    lag_weeks=None,
                )
            ]
        )
        result = validate_causal_graph(graph)
        assert any(
            "no valid" in e.lower() and "lag_weeks" in e.lower() for e in result.errors
        )

    def test_negative_lag_weeks_is_an_error(self):
        graph = _minimal_valid_graph(
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                    lag_type="fixed_weeks",
                    lag_weeks=-1,
                )
            ]
        )
        result = validate_causal_graph(graph)
        assert any(
            "no valid" in e.lower() and "lag_weeks" in e.lower() for e in result.errors
        )

    def test_none_lag_type_needs_no_lag_weeks(self):
        graph = _minimal_valid_graph(
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                    lag_type="none",
                    lag_weeks=None,
                )
            ]
        )
        result = validate_causal_graph(graph)
        assert result.is_valid


class TestCompilationPlanPreview:
    def test_valid_graph_produces_a_plan(self):
        graph = _minimal_valid_graph()
        plan = build_compilation_plan_preview(graph)
        assert plan.outcome_ids == ("fh_new",)
        assert plan.modelling_columns == ("tv_spend",)
        assert plan.pathway_mask_preview == (
            {
                "source_node_id": "tv_spend",
                "target_node_id": "fh_new",
                "role": EDGE_ROLE_DIRECT,
            },
        )
        assert plan.lag_structure[0]["source_node_id"] == "tv_spend"

    def test_diagnostic_only_edges_excluded_from_preview(self):
        graph = _minimal_valid_graph(
            nodes=[
                CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
                CausalNode(node_id="fh_gsa", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="fh_new",
                    target_node_id="fh_gsa",
                    role=EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
                )
            ],
        )
        plan = build_compilation_plan_preview(graph)
        assert plan.pathway_mask_preview == ()

    def test_invalid_graph_raises(self):
        graph = _minimal_valid_graph(
            edges=[
                CausalEdge(
                    source_node_id="does_not_exist",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                )
            ]
        )
        with pytest.raises(ValueError, match="invalid graph"):
            build_compilation_plan_preview(graph)

    def test_plan_to_dict(self):
        graph = _minimal_valid_graph()
        plan = build_compilation_plan_preview(graph)
        d = plan.to_dict()
        assert d["outcome_ids"] == ["fh_new"]
        assert d["modelling_columns"] == ["tv_spend"]


class TestGraphDependencyIssues:
    def test_matching_fingerprint_produces_no_issues(self):
        graph = _minimal_valid_graph()
        fp = graph.structural_fingerprint()
        dependents = [
            {
                "artefact_type": "model_spec",
                "artefact_id": "spec-1",
                "bound_structural_fingerprint": fp,
            }
        ]
        assert graph_dependency_issues(fp, dependents) == []

    def test_stale_fingerprint_is_flagged(self):
        graph = _minimal_valid_graph()
        fp = graph.structural_fingerprint()
        graph.nodes.append(
            CausalNode(node_id="search_spend", role=NODE_ROLE_INTERVENTION)
        )
        new_fp = graph.structural_fingerprint()
        dependents = [
            {
                "artefact_type": "official_curve",
                "artefact_id": "curve-1",
                "bound_structural_fingerprint": fp,
            }
        ]
        issues = graph_dependency_issues(new_fp, dependents)
        assert len(issues) == 1
        assert issues[0] == CausalGraphDependencyIssue(
            artefact_type="official_curve",
            artefact_id="curve-1",
            issue_type="stale",
            detail=issues[0].detail,
        )
        assert issues[0].issue_type == "stale"

    def test_missing_bound_fingerprint_is_flagged(self):
        dependents = [{"artefact_type": "scenario", "artefact_id": "scn-1"}]
        issues = graph_dependency_issues("some-fingerprint", dependents)
        assert len(issues) == 1
        assert issues[0].issue_type == "missing"

    def test_layout_only_edit_produces_no_dependency_issues(self):
        graph = _minimal_valid_graph()
        fp_before = graph.structural_fingerprint()
        dependents = [
            {
                "artefact_type": "fitted_model",
                "artefact_id": "model-1",
                "bound_structural_fingerprint": fp_before,
            }
        ]
        graph.layout = GraphLayout(positions={"tv_spend": NodePosition(x=5.0, y=5.0)})
        fp_after = graph.structural_fingerprint()
        assert fp_after == fp_before
        assert graph_dependency_issues(fp_after, dependents) == []


class TestCurrentStructuralFingerprintForIdentity:
    """REQ-GRAPH-001 work package: the shared rule every page computing a
    current ModelIdentity must use so a live structural graph edit stales a
    previously-granted approval/curve/scenario without requiring a refit,
    while a layout-only edit never does."""

    def test_no_graph_used_at_fit_returns_none(self):
        # fingerprint_model_spec treats None as "" - omitted from identity
        # entirely, so a graph drafted after a non-graph fit can't affect it.
        assert (
            current_structural_fingerprint_for_identity(
                fit_time_structural_fingerprint="",
                live_graph_dict=_minimal_valid_graph().to_dict(),
            )
            is None
        )

    def test_graph_used_at_fit_reads_the_live_graph_not_the_fit_time_value(self):
        fit_time_graph = _minimal_valid_graph()
        live_graph = _minimal_valid_graph()
        live_graph.edges.append(
            CausalEdge(
                source_node_id="tv_spend",
                target_node_id="fh_new",
                role=EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
                metadata={"note": "distinguishing edge"},
            )
        )
        result = current_structural_fingerprint_for_identity(
            fit_time_structural_fingerprint=fit_time_graph.structural_fingerprint(),
            live_graph_dict=live_graph.to_dict(),
        )
        assert result == live_graph.structural_fingerprint()
        assert result != fit_time_graph.structural_fingerprint()

    def test_layout_only_live_edit_does_not_change_the_result(self):
        fit_time_graph = _minimal_valid_graph()
        live_graph = _minimal_valid_graph()
        before = current_structural_fingerprint_for_identity(
            fit_time_structural_fingerprint=fit_time_graph.structural_fingerprint(),
            live_graph_dict=live_graph.to_dict(),
        )
        live_graph.layout = GraphLayout(
            positions={"tv_spend": NodePosition(x=42.0, y=7.0)}
        )
        after = current_structural_fingerprint_for_identity(
            fit_time_structural_fingerprint=fit_time_graph.structural_fingerprint(),
            live_graph_dict=live_graph.to_dict(),
        )
        assert before == after == fit_time_graph.structural_fingerprint()

    def test_missing_live_graph_fails_closed_to_empty_string(self):
        fit_time_graph = _minimal_valid_graph()
        result = current_structural_fingerprint_for_identity(
            fit_time_structural_fingerprint=fit_time_graph.structural_fingerprint(),
            live_graph_dict=None,
        )
        assert result == ""
        assert result != fit_time_graph.structural_fingerprint()


class TestGraphVersionsForExport:
    """REQ-GRAPH-001 work package (graph portability): the shared rule for
    what a project export bundle's causal_graphs.json should contain -
    every saved version plus the current live graph, deduplicated by
    unambiguous (graph_id, graph_version) identity."""

    def test_combines_saved_history_and_current_live_graph(self):
        v1 = _minimal_valid_graph(graph_version=1).to_dict()
        current = _minimal_valid_graph(graph_version=2).to_dict()
        result = graph_versions_for_export(
            current_graph_dict=current, version_history=[v1]
        )
        assert {(r["graph_id"], r["graph_version"]) for r in result} == {
            ("g1", 1),
            ("g1", 2),
        }

    def test_current_graph_deduplicates_against_matching_history_entry(self):
        v1 = _minimal_valid_graph(graph_version=1).to_dict()
        result = graph_versions_for_export(current_graph_dict=v1, version_history=[v1])
        assert len(result) == 1

    def test_no_current_graph_returns_history_only(self):
        v1 = _minimal_valid_graph(graph_version=1).to_dict()
        result = graph_versions_for_export(
            current_graph_dict=None, version_history=[v1]
        )
        assert result == [v1]

    def test_no_history_and_no_current_graph_returns_empty(self):
        assert (
            graph_versions_for_export(current_graph_dict=None, version_history=None)
            == []
        )

    def test_current_graph_never_overwrites_a_differently_structured_saved_version(
        self,
    ):
        """Regression: the Causal Graph page's own _mark_draft() lets an
        analyst edit an approved graph's edge (e.g. its lag) without
        clicking Save draft/Approve again - the live graph then shares its
        saved (graph_id, graph_version) key with a *differently structured*
        history entry (status reverted to draft in place, edges changed).
        The saved, approved record must never be silently overwritten by
        that unsaved edit."""
        saved_approved = replace(
            _minimal_valid_graph(graph_version=1), status=GRAPH_STATUS_APPROVED
        )
        live_unsaved_edit = replace(
            saved_approved,
            status=GRAPH_STATUS_DRAFT,
            edges=[
                CausalEdge(
                    source_node_id="tv_spend",
                    target_node_id="fh_new",
                    role=EDGE_ROLE_DIRECT,
                    lag_type="fixed_weeks",
                    lag_weeks=3,
                )
            ],
        )
        result = graph_versions_for_export(
            current_graph_dict=live_unsaved_edit.to_dict(),
            version_history=[saved_approved.to_dict()],
        )
        assert len(result) == 1
        assert result[0] == saved_approved.to_dict()

    def test_current_graph_is_kept_when_its_key_was_never_saved(self):
        # A brand-new graph, never Saved/Approved yet - version_history is
        # still empty, so the live graph is the only worthwhile record.
        current = _minimal_valid_graph(graph_version=1).to_dict()
        result = graph_versions_for_export(
            current_graph_dict=current, version_history=[]
        )
        assert result == [current]
