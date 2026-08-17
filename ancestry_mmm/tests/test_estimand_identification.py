"""REQ-IDENT-001 (Work Package 3): tests for
core.estimand_identification."""

from __future__ import annotations

import pytest

from ancestry_mmm.core.causal_graph import CausalEdge, CausalGraph, CausalNode
from ancestry_mmm.core.estimand_identification import (
    EFFECT_TYPE_DIRECT,
    GRAPHICAL_IDENTIFICATION_DISCLAIMER,
    IDENTIFICATION_STATUS_GRAPH_COMPATIBLE,
    IDENTIFICATION_STATUS_NOT_APPLICABLE,
    IDENTIFICATION_STATUS_NOT_IDENTIFIED_UNDER_GRAPH,
    IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER,
    EstimandIdentificationResult,
    assess_backdoor_identification,
)


def _node(node_id: str) -> CausalNode:
    return CausalNode(node_id=node_id, label=node_id)


def _edge(source: str, target: str) -> CausalEdge:
    return CausalEdge(source_node_id=source, target_node_id=target)


def _graph(node_ids: tuple, edges: tuple) -> CausalGraph:
    return CausalGraph(
        graph_id="test-graph",
        graph_version=1,
        nodes=[_node(n) for n in node_ids],
        edges=[_edge(s, t) for s, t in edges],
    )


# ---------------------------------------------------------------------------
# Simple confounder (classic back-door scenario)
# ---------------------------------------------------------------------------


class TestSimpleConfounder:
    """X <- Z -> Y, X -> Y: Z is a confounder on the only backdoor path."""

    def _graph(self) -> CausalGraph:
        return _graph(
            ("X", "Y", "Z"),
            (("Z", "X"), ("Z", "Y"), ("X", "Y")),
        )

    def test_empty_adjustment_set_leaves_backdoor_path_open(self):
        result = assess_backdoor_identification(
            self._graph(), treatment="X", outcome="Y", proposed_adjustment_set=()
        )
        assert result.status == IDENTIFICATION_STATUS_NOT_IDENTIFIED_UNDER_GRAPH

    def test_adjusting_for_confounder_is_graph_compatible(self):
        result = assess_backdoor_identification(
            self._graph(), treatment="X", outcome="Y", proposed_adjustment_set=("Z",)
        )
        assert result.status == IDENTIFICATION_STATUS_GRAPH_COMPATIBLE
        assert result.treatment_descendants_in_adjustment_set == ()
        assert result.likely_collider_members == ()

    def test_minimal_adjustment_set_recovers_the_confounder(self):
        result = assess_backdoor_identification(
            self._graph(), treatment="X", outcome="Y", proposed_adjustment_set=()
        )
        assert result.minimal_adjustment_set == ("Z",)

    def test_disclaimer_always_present(self):
        result = assess_backdoor_identification(
            self._graph(), treatment="X", outcome="Y", proposed_adjustment_set=("Z",)
        )
        assert result.disclaimer == GRAPHICAL_IDENTIFICATION_DISCLAIMER


# ---------------------------------------------------------------------------
# Treatment descendants must never be proposed (Pearl's second condition)
# ---------------------------------------------------------------------------


class TestTreatmentDescendantExclusion:
    """X -> M -> Y (M is a mediator, a descendant of X): adjusting for M
    is invalid for a total-effect estimand even though it "looks like" it
    blocks a path - Pearl's back-door criterion explicitly forbids
    conditioning on a descendant of treatment."""

    def _graph(self) -> CausalGraph:
        return _graph(
            ("X", "Y", "M", "Z"),
            (("X", "M"), ("M", "Y"), ("X", "Y"), ("Z", "X"), ("Z", "Y")),
        )

    def test_mediator_in_adjustment_set_is_flagged_and_blocks(self):
        result = assess_backdoor_identification(
            self._graph(), treatment="X", outcome="Y", proposed_adjustment_set=("M",)
        )
        assert result.status == IDENTIFICATION_STATUS_NOT_IDENTIFIED_UNDER_GRAPH
        assert result.treatment_descendants_in_adjustment_set == ("M",)

    def test_minimal_adjustment_set_never_includes_a_treatment_descendant(self):
        result = assess_backdoor_identification(
            self._graph(), treatment="X", outcome="Y", proposed_adjustment_set=("M",)
        )
        assert result.minimal_adjustment_set is not None
        assert "M" not in result.minimal_adjustment_set
        assert "Z" in result.minimal_adjustment_set


# ---------------------------------------------------------------------------
# Collider: conditioning on it OPENS a path that was already blocked
# ---------------------------------------------------------------------------


class TestColliderOpensPath:
    """X<-U1->C<-U2->Y is already blocked by the collider C by default.
    Conditioning on C (a mistake) opens it. A separate real confounder Z
    (X<-Z->Y) must still be adjusted for. Proposing {Z, C} should fail
    and flag C - never Z - as the problematic member."""

    def _graph(self) -> CausalGraph:
        return _graph(
            ("X", "Y", "Z", "U1", "U2", "C"),
            (
                ("Z", "X"),
                ("Z", "Y"),
                ("U1", "X"),
                ("U1", "C"),
                ("U2", "Y"),
                ("U2", "C"),
                ("X", "Y"),
            ),
        )

    def test_z_alone_is_graph_compatible(self):
        result = assess_backdoor_identification(
            self._graph(), treatment="X", outcome="Y", proposed_adjustment_set=("Z",)
        )
        assert result.status == IDENTIFICATION_STATUS_GRAPH_COMPATIBLE

    def test_adjusting_for_the_collider_too_reopens_the_path(self):
        result = assess_backdoor_identification(
            self._graph(),
            treatment="X",
            outcome="Y",
            proposed_adjustment_set=("Z", "C"),
        )
        assert result.status == IDENTIFICATION_STATUS_NOT_IDENTIFIED_UNDER_GRAPH
        assert result.likely_collider_members == ("C",)

    def test_collider_alone_without_the_real_confounder_also_fails(self):
        result = assess_backdoor_identification(
            self._graph(), treatment="X", outcome="Y", proposed_adjustment_set=("C",)
        )
        assert result.status == IDENTIFICATION_STATUS_NOT_IDENTIFIED_UNDER_GRAPH


# ---------------------------------------------------------------------------
# Scope boundaries
# ---------------------------------------------------------------------------


class TestScopeBoundaries:
    def test_direct_effect_type_is_unsupported(self):
        graph = _graph(("X", "Y"), (("X", "Y"),))
        result = assess_backdoor_identification(
            graph, treatment="X", outcome="Y", effect_type=EFFECT_TYPE_DIRECT
        )
        assert result.status == IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER
        assert result.limitations

    def test_treatment_not_in_graph_is_not_applicable(self):
        graph = _graph(("Y",), ())
        result = assess_backdoor_identification(
            graph, treatment="does_not_exist", outcome="Y"
        )
        assert result.status == IDENTIFICATION_STATUS_NOT_APPLICABLE

    def test_result_always_carries_an_availability_limitation(self):
        """The checker can never determine whether a graph node
        corresponds to an observed variable - every result must disclose
        this, not only failing ones."""
        graph = _graph(("X", "Y"), (("X", "Y"),))
        result = assess_backdoor_identification(
            graph, treatment="X", outcome="Y", proposed_adjustment_set=()
        )
        assert any("observed" in limitation for limitation in result.limitations)

    def test_cyclic_graph_is_unsupported_not_silently_wrong(self):
        graph = _graph(("X", "Y"), (("X", "Y"), ("Y", "X")))
        result = assess_backdoor_identification(graph, treatment="X", outcome="Y")
        assert result.status == IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER

    def test_excluded_diagnostic_only_edges_are_not_part_of_the_causal_graph(self):
        """An excluded_diagnostic_only edge compiles to nothing
        (REQ-GRAPH-001) - it must not participate in backdoor-path
        analysis as though it were a real causal relationship."""
        graph = CausalGraph(
            graph_id="test-graph",
            graph_version=1,
            nodes=[_node("X"), _node("Y"), _node("Z")],
            edges=[
                _edge("X", "Y"),
                CausalEdge(
                    source_node_id="Z",
                    target_node_id="X",
                    role="excluded_diagnostic_only",
                ),
            ],
        )
        # If the excluded edge were treated as real, Z would be a
        # confounder requiring adjustment; since it is not, the empty
        # adjustment set must already be graph-compatible.
        result = assess_backdoor_identification(
            graph, treatment="X", outcome="Y", proposed_adjustment_set=()
        )
        assert result.status == IDENTIFICATION_STATUS_GRAPH_COMPATIBLE


# ---------------------------------------------------------------------------
# EstimandIdentificationResult validation / round-trip
# ---------------------------------------------------------------------------


class TestEstimandIdentificationResultValidation:
    def test_requires_treatment_and_outcome(self):
        with pytest.raises(ValueError, match="treatment and outcome are required"):
            EstimandIdentificationResult(
                treatment="",
                outcome="Y",
                effect_type="total",
                graph_id="g",
                graph_version=1,
                status=IDENTIFICATION_STATUS_GRAPH_COMPATIBLE,
                proposed_adjustment_set=(),
            )

    def test_rejects_invalid_effect_type(self):
        with pytest.raises(ValueError, match="invalid effect_type"):
            EstimandIdentificationResult(
                treatment="X",
                outcome="Y",
                effect_type="not_a_type",
                graph_id="g",
                graph_version=1,
                status=IDENTIFICATION_STATUS_GRAPH_COMPATIBLE,
                proposed_adjustment_set=(),
            )

    def test_rejects_invalid_status(self):
        with pytest.raises(ValueError, match="invalid status"):
            EstimandIdentificationResult(
                treatment="X",
                outcome="Y",
                effect_type="total",
                graph_id="g",
                graph_version=1,
                status="not_a_status",
                proposed_adjustment_set=(),
            )

    def test_round_trip(self):
        original = assess_backdoor_identification(
            _graph(("X", "Y", "Z"), (("Z", "X"), ("Z", "Y"), ("X", "Y"))),
            treatment="X",
            outcome="Y",
            proposed_adjustment_set=("Z",),
        )
        restored = EstimandIdentificationResult.from_dict(original.to_dict())
        assert restored == original
