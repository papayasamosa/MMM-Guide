"""Tests for core.graph_model_compiler (REQ-GRAPH-001 work package D) - the
one graph-to-model boundary, plus the equivalence proof required before this
capability may merge: a synthetic approved graph and an equivalent legacy
MediaOutcomePathway catalogue must resolve to the same modelling columns,
outcome ordering, channels, pathway masks, lags, and deterministic
fixed-parameter prediction. Any unexplained difference blocks merge.
"""

import numpy as np
import pytest

from ancestry_mmm.core.causal_graph import (
    EDGE_ROLE_CROSS_PRODUCT_HALO,
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
    EDGE_ROLE_MEDIATED,
    GRAPH_STATUS_APPROVED,
    GRAPH_STATUS_DRAFT,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_MEDIATOR,
    NODE_ROLE_OUTCOME,
    CausalEdge,
    CausalGraph,
    CausalNode,
)
from ancestry_mmm.core.graph_model_compiler import (
    GraphModelCompiler,
    UnsupportedGraphStructureError,
    check_engine_capability,
    resolve_pathway_masks_preferring_graph,
    resolved_pathway_masks_from_graph,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.pathways import (
    PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
    PATHWAY_ROLE_EXCLUDED,
    PATHWAY_ROLE_PRIMARY_DIRECT,
    MediaOutcomePathway,
    resolve_pathway_masks,
)
from ancestry_mmm.core.predict import FHPosteriorParams, predict_mu


def _approved_direct_graph(**overrides) -> CausalGraph:
    nodes = overrides.pop("nodes", None) or [
        CausalNode(node_id="TV", role=NODE_ROLE_INTERVENTION),
        CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
    ]
    edges = overrides.pop("edges", None) or [
        CausalEdge(source_node_id="TV", target_node_id="A", role=EDGE_ROLE_DIRECT),
    ]
    defaults = dict(
        graph_id="g1",
        graph_version=1,
        nodes=nodes,
        edges=edges,
        status=GRAPH_STATUS_APPROVED,
    )
    defaults.update(overrides)
    return CausalGraph(**defaults)


class TestCheckEngineCapability:
    def test_direct_and_cross_product_halo_are_supported(self):
        graph = _approved_direct_graph(
            nodes=[
                CausalNode(node_id="TV", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="Radio", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="TV", target_node_id="A", role=EDGE_ROLE_DIRECT
                ),
                CausalEdge(
                    source_node_id="Radio",
                    target_node_id="A",
                    role=EDGE_ROLE_CROSS_PRODUCT_HALO,
                ),
            ],
        )
        assert check_engine_capability(graph) == []

    def test_mediated_role_is_unsupported(self):
        graph = _approved_direct_graph(
            nodes=[
                CausalNode(node_id="TV", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="mid", role=NODE_ROLE_MEDIATOR),
                CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="TV", target_node_id="mid", role=EDGE_ROLE_MEDIATED
                ),
            ],
        )
        reasons = check_engine_capability(graph)
        assert any("cannot compile" in r for r in reasons)

    def test_edge_not_originating_from_intervention_is_unsupported(self):
        graph = _approved_direct_graph(
            nodes=[
                CausalNode(node_id="mid", role=NODE_ROLE_MEDIATOR),
                CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="mid", target_node_id="A", role=EDGE_ROLE_DIRECT
                ),
            ],
        )
        reasons = check_engine_capability(graph)
        assert any("originates from" in r for r in reasons)

    def test_excluded_diagnostic_edge_never_flagged(self):
        graph = _approved_direct_graph(
            nodes=[
                CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
                CausalNode(node_id="B", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="A",
                    target_node_id="B",
                    role=EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
                ),
            ],
        )
        assert check_engine_capability(graph) == []


class TestResolvedPathwayMasksFromGraph:
    def test_direct_edge_compiles_to_primary_direct(self):
        graph = _approved_direct_graph()
        masks = resolved_pathway_masks_from_graph(graph)
        assert masks.primary_channels_by_outcome == {"A": ["TV"]}

    def test_cross_product_halo_defaults_to_active(self):
        graph = _approved_direct_graph(
            nodes=[
                CausalNode(node_id="Radio", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="Radio",
                    target_node_id="A",
                    role=EDGE_ROLE_CROSS_PRODUCT_HALO,
                    lag_type="fixed_weeks",
                    lag_weeks=3,
                ),
            ],
        )
        masks = resolved_pathway_masks_from_graph(graph)
        assert masks.active_channels_by_outcome == {"A": ["Radio"]}
        component = masks.components[0]
        assert component.lag_weeks == 3

    def test_cross_product_halo_with_exploratory_tier_metadata(self):
        graph = _approved_direct_graph(
            nodes=[
                CausalNode(node_id="Radio", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="Radio",
                    target_node_id="A",
                    role=EDGE_ROLE_CROSS_PRODUCT_HALO,
                    metadata={"cross_product_tier": "exploratory"},
                ),
            ],
        )
        masks = resolved_pathway_masks_from_graph(graph)
        assert masks.exploratory_channels_by_outcome == {"A": ["Radio"]}

    def test_excluded_diagnostic_edge_produces_no_component(self):
        graph = _approved_direct_graph(
            nodes=[
                CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
                CausalNode(node_id="B", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="A",
                    target_node_id="B",
                    role=EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
                ),
            ],
        )
        masks = resolved_pathway_masks_from_graph(graph)
        assert masks.components == []


class TestGraphModelCompiler:
    def test_draft_graph_is_rejected(self):
        graph = _approved_direct_graph(status=GRAPH_STATUS_DRAFT)
        with pytest.raises(UnsupportedGraphStructureError, match="approved"):
            GraphModelCompiler().compile(graph)

    def test_invalid_graph_is_rejected_with_reasons(self):
        graph = _approved_direct_graph(
            edges=[
                CausalEdge(
                    source_node_id="does_not_exist",
                    target_node_id="A",
                    role=EDGE_ROLE_DIRECT,
                )
            ]
        )
        with pytest.raises(UnsupportedGraphStructureError, match="failed validation"):
            GraphModelCompiler().compile(graph)

    def test_unsupported_structure_is_rejected_with_reasons(self):
        graph = _approved_direct_graph(
            nodes=[
                CausalNode(node_id="TV", role=NODE_ROLE_INTERVENTION),
                CausalNode(node_id="mid", role=NODE_ROLE_MEDIATOR),
                CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
            ],
            edges=[
                CausalEdge(
                    source_node_id="TV", target_node_id="mid", role=EDGE_ROLE_MEDIATED
                ),
                CausalEdge(
                    source_node_id="mid", target_node_id="A", role=EDGE_ROLE_DIRECT
                ),
            ],
        )
        with pytest.raises(
            UnsupportedGraphStructureError, match="not supported by engine"
        ):
            GraphModelCompiler().compile(graph)

    def test_valid_graph_compiles_and_binds_structural_fingerprint(self):
        graph = _approved_direct_graph()
        result = GraphModelCompiler().compile(graph)
        assert (
            result.causal_graph_structural_fingerprint == graph.structural_fingerprint()
        )
        assert result.plan.outcome_ids == ("A",)
        assert result.pathway_masks.primary_channels_by_outcome == {"A": ["TV"]}


class TestResolvePathwayMasksPreferringGraph:
    def test_none_graph_is_byte_for_byte_passthrough(self):
        pathways = [
            MediaOutcomePathway(
                channel="TV",
                source_product="Family History",
                target_outcome_id="A",
                role=PATHWAY_ROLE_PRIMARY_DIRECT,
                component_type="direct",
            )
        ]
        direct_kwargs = dict(
            channel_products={"TV": "Family History"},
            outcome_products={"A": "Family History"},
            fitted_outcome_ids=["A"],
            diagnostic_only_outcome_ids=[],
            dna_channel_idx=[],
            dna_outcome_id=None,
            direct_dna_outcome_ids=[],
            dna_lag_weeks=0,
        )
        via_wrapper = resolve_pathway_masks_preferring_graph(
            causal_graph=None,
            outcome_ids=["A"],
            channels=["TV"],
            pathways=pathways,
            **direct_kwargs,
        )
        via_legacy = resolve_pathway_masks(
            ["A"],
            ["TV"],
            pathways,
            dna_channel_idx=[],
            dna_outcome_id=None,
            direct_dna_outcome_ids=[],
            dna_lag_weeks=0,
        )
        assert via_wrapper.to_dict() == via_legacy.to_dict()

    def test_graph_present_ignores_raw_pathways_entirely(self):
        graph = _approved_direct_graph()
        # A deliberately contradictory raw catalogue - if it were consulted
        # at all, the result would differ from the graph-only compilation.
        contradictory_pathways = [
            MediaOutcomePathway(
                channel="TV",
                source_product="fh",
                target_outcome_id="A",
                role=PATHWAY_ROLE_EXCLUDED,
                component_type="excluded",
            )
        ]
        masks = resolve_pathway_masks_preferring_graph(
            causal_graph=graph,
            outcome_ids=["A"],
            channels=["TV"],
            pathways=contradictory_pathways,
            channel_products={"TV": "fh"},
            outcome_products={"A": "fh"},
            fitted_outcome_ids=["A"],
            diagnostic_only_outcome_ids=[],
            dna_channel_idx=[],
            dna_outcome_id=None,
            direct_dna_outcome_ids=[],
            dna_lag_weeks=0,
        )
        assert masks.primary_channels_by_outcome == {"A": ["TV"]}


# ---------------------------------------------------------------------------
# Equivalence proof (mandatory acceptance evidence, work package D)
# ---------------------------------------------------------------------------


def _equivalent_legacy_pathways():
    return [
        MediaOutcomePathway(
            channel="TV",
            source_product="fh",
            target_outcome_id="A",
            role=PATHWAY_ROLE_PRIMARY_DIRECT,
            component_type="direct",
        ),
        MediaOutcomePathway(
            channel="Radio",
            source_product="fh",
            target_outcome_id="A",
            role=PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
            component_type="cross_product",
            lag_weeks=2,
        ),
        MediaOutcomePathway(
            channel="TV",
            source_product="fh",
            target_outcome_id="B",
            role=PATHWAY_ROLE_PRIMARY_DIRECT,
            component_type="direct",
        ),
        MediaOutcomePathway(
            channel="Radio",
            source_product="fh",
            target_outcome_id="B",
            role=PATHWAY_ROLE_EXCLUDED,
            component_type="excluded",
        ),
    ]


def _equivalent_graph() -> CausalGraph:
    return CausalGraph(
        graph_id="equivalence-proof",
        graph_version=1,
        status=GRAPH_STATUS_APPROVED,
        nodes=[
            CausalNode(node_id="TV", role=NODE_ROLE_INTERVENTION),
            CausalNode(node_id="Radio", role=NODE_ROLE_INTERVENTION),
            CausalNode(node_id="A", role=NODE_ROLE_OUTCOME),
            CausalNode(node_id="B", role=NODE_ROLE_OUTCOME),
        ],
        edges=[
            CausalEdge(source_node_id="TV", target_node_id="A", role=EDGE_ROLE_DIRECT),
            CausalEdge(
                source_node_id="Radio",
                target_node_id="A",
                role=EDGE_ROLE_CROSS_PRODUCT_HALO,
                lag_type="fixed_weeks",
                lag_weeks=2,
            ),
            CausalEdge(source_node_id="TV", target_node_id="B", role=EDGE_ROLE_DIRECT),
            CausalEdge(
                source_node_id="Radio",
                target_node_id="B",
                role=EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
            ),
        ],
    )


def _plain_channel_map(mapping):
    return {key: sorted(value) for key, value in mapping.items()}


class TestEquivalenceProof:
    """A synthetic approved graph, built to represent the exact same
    standard model configuration as an equivalent legacy MediaOutcomePathway
    catalogue, must produce the same modelling columns, outcome ordering,
    channels, pathway masks, lags, and deterministic fixed-parameter
    prediction. Any unexplained difference here blocks merge."""

    def test_same_modelling_columns_and_outcome_ordering(self):
        plan = GraphModelCompiler().compile(_equivalent_graph()).plan
        assert plan.outcome_ids == ("A", "B")
        assert plan.modelling_columns == ("Radio", "TV")

    def test_same_pathway_masks(self):
        legacy_masks = resolve_pathway_masks(
            ["A", "B"],
            ["TV", "Radio"],
            _equivalent_legacy_pathways(),
            dna_channel_idx=[],
            dna_outcome_id=None,
            direct_dna_outcome_ids=[],
            dna_lag_weeks=0,
        )
        graph_masks = GraphModelCompiler().compile(_equivalent_graph()).pathway_masks

        assert _plain_channel_map(
            graph_masks.primary_channels_by_outcome
        ) == _plain_channel_map(legacy_masks.primary_channels_by_outcome)
        assert _plain_channel_map(
            graph_masks.active_channels_by_outcome
        ) == _plain_channel_map(legacy_masks.active_channels_by_outcome)
        assert _plain_channel_map(
            graph_masks.exploratory_channels_by_outcome
        ) == _plain_channel_map(legacy_masks.exploratory_channels_by_outcome)
        assert dict(graph_masks.lag_weeks_by_cell) == dict(
            legacy_masks.lag_weeks_by_cell
        )

    def test_same_deterministic_fixed_parameter_prediction(self):
        legacy_masks = resolve_pathway_masks(
            ["A", "B"],
            ["TV", "Radio"],
            _equivalent_legacy_pathways(),
            dna_channel_idx=[],
            dna_outcome_id=None,
            direct_dna_outcome_ids=[],
            dna_lag_weeks=0,
        )
        graph_masks = GraphModelCompiler().compile(_equivalent_graph()).pathway_masks

        def _meta(pathway_masks):
            return FHModelMeta(
                markets=["UK"],
                outcome_ids=["A", "B"],
                channels=["TV", "Radio"],
                dna_channels=[],
                dna_channel_idx=[],
                non_dna_idx=[0, 1],
                dna_outcome_id="A",
                dna_lag_weeks=0,
                unpooled_markets=[],
                control_names=[],
                pathway_masks=pathway_masks,
            )

        params = FHPosteriorParams(
            decay_rate={"TV": 0.0, "Radio": 0.0},
            hill_K={"TV": 1000.0, "Radio": 1000.0},
            hill_S={"TV": 1.0, "Radio": 1.0},
            beta={"A": {"TV": 1.0, "Radio": 1.0}, "B": {"TV": 1.0, "Radio": 1.0}},
            pathway_strength={"A": {"Radio": 0.4}, "B": {}},
            promo_coef={"A": 0.0, "B": 0.0},
            market_offset={"UK": {"A": 0.0, "B": 0.0}},
            intercept={"A": 0.0, "B": 0.0},
            trend_coef={"A": 0.0, "B": 0.0},
            gamma_fourier={"A": np.zeros(4), "B": np.zeros(4)},
            alpha={"A": 5.0, "B": 5.0},
            control_coef={},
            outcome_control_coef={},
        )
        n = 6
        x_media = np.zeros((n, 2))
        x_media[2] = [500.0, 500.0]
        frame = {
            "markets": ["UK"],
            "market_idx": np.zeros(n, dtype=int),
            "market_bounds": [(0, n)],
            "X_media": x_media,
            "promo": np.zeros((n, 2)),
            "trend": np.zeros(n),
            "fourier": np.zeros((n, 4)),
            "control_names": [],
            "X_controls": np.zeros((n, 0)),
            "outcome_controls": {},
            "outcome_control_names": {},
        }

        mu_legacy = predict_mu(frame, _meta(legacy_masks), params)
        mu_graph = predict_mu(frame, _meta(graph_masks), params)
        np.testing.assert_allclose(mu_legacy, mu_graph)
        # not vacuous: both channels actually move the prediction away from
        # a zero-spend baseline, so an all-zero coincidence is ruled out.
        zero_frame = dict(frame)
        zero_frame["X_media"] = np.zeros((n, 2))
        mu_zero = predict_mu(zero_frame, _meta(legacy_masks), params)
        assert not np.allclose(mu_legacy, mu_zero)
