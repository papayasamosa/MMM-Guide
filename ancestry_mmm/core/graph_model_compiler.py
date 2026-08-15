"""
REQ-GRAPH-001: the one graph-to-model boundary. Accepts an approved
`core.causal_graph.CausalGraph`, revalidates it, checks it against the
current engine's declared capability, and compiles it into the exact same
operational object `core.hierarchical_model`/`core.market_specific_model`/
`core.predict` already consume - `core.pathways.ResolvedPathwayMasks` - so
no downstream fitting/prediction/attribution code needs to change to make
an approved graph authoritative.

No drag-and-drop editor and no MMM mathematics change here (REQ-GRAPH-001's
own package boundary): this module only replaces *which object* resolves
to a `ResolvedPathwayMasks` when a graph is supplied. The drag-and-drop
editor lives at `ancestry_mmm/pages/14_Causal_Graph.py`. When no graph is
supplied - a project with no approved causal graph configured, which
remains every project's default until an analyst builds and approves one -
`resolve_pathway_masks_preferring_graph` below is a byte-for-byte passthrough
to `core.pathways.resolve_validated_pathway_masks`.

The ordinary PyMC-hierarchical/market-specific engines cannot compile every
structure the graph domain's role vocabulary can express
(REQ-GRAPH-001 S4/S5): they understand a flat (outcome_id, channel) cell
system with three equation-gating roles (primary_direct/
active_cross_product/exploratory_cross_product) plus exclusion. The
explicit Candidate A Search linked engine below adds one narrowly typed
mediated/capacity structure; moderation, residual interaction, and every
other mediated/capacity structure remain blocked rather than silently
dropped or approximated (AGENTS.md: do not imply a dependency natively
supports a capability it does not).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .activities import ActivityDefinition, resolve_graph_activity_predictor
from .causal_graph import (
    CausalGraph,
    CausalNode,
    EDGE_ROLE_CROSS_PRODUCT_HALO,
    EDGE_ROLE_CAPACITY_CONSTRAINED,
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
    EDGE_ROLE_MEDIATED,
    GRAPH_STATUS_APPROVED,
    GraphCompilationPlan,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_OUTCOME,
    NODE_ROLE_CAPACITY_OR_CAP,
    NODE_ROLE_DEMAND_CAPTURE,
    build_compilation_plan_preview,
    validate_causal_graph,
)
from .search_capacity import (
    SEARCH_CANDIDATE_A_ENGINE,
)
from .search_objects import (
    SEARCH_ROLE_DEMAND,
    SEARCH_ROLE_DIRECT_NAV_CAPTURE,
    SEARCH_ROLE_ORGANIC_CAPTURE,
    SEARCH_ROLE_PAID_CAP,
    SEARCH_ROLE_PAID_DELIVERY,
    SEARCH_ROLE_PAID_SPEND,
    SearchObjectDefinition,
    current_search_object_versions,
)
from .pathways import (
    PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
    PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT,
    PATHWAY_ROLE_PRIMARY_DIRECT,
    MediaOutcomePathway,
    ResolvedPathwayComponent,
    ResolvedPathwayMasks,
    resolve_validated_pathway_masks,
)

GRAPH_ENGINE_PYMC_HIERARCHICAL = "pymc_hierarchical"

# The only edge roles the current PyMC hierarchical/market-specific engine
# can compile. `excluded_diagnostic_only` is always supported (it compiles
# to nothing - a zero-contribution cell, same as an omitted pathway).
_SUPPORTED_EDGE_ROLES = (
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_CROSS_PRODUCT_HALO,
    EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
)


class UnsupportedGraphStructureError(ValueError):
    """Raised when a graph is not approved, fails validation, or contains a
    structure the target engine cannot express. Always carries the specific
    reason(s) - never a bare rejection."""


@dataclass(frozen=True)
class SearchCandidateAGraphPlan:
    """The only mediated/capacity graph shape authorised by REQ-SEARCH-002."""

    outcome_node_id: str
    demand_node_id: str
    cap_node_id: str
    organic_capture_node_id: str
    direct_navigation_node_id: str
    upstream_intervention_node_ids: Tuple[str, ...]
    mediated_edge_ids: Tuple[str, ...]
    capacity_edge_ids: Tuple[str, ...]
    search_capture_edge_ids: Tuple[str, ...]
    formulation_id: str = "candidate_a_v1"

    def to_dict(self) -> dict:
        return {
            "outcome_node_id": self.outcome_node_id,
            "demand_node_id": self.demand_node_id,
            "cap_node_id": self.cap_node_id,
            "organic_capture_node_id": self.organic_capture_node_id,
            "direct_navigation_node_id": self.direct_navigation_node_id,
            "upstream_intervention_node_ids": list(self.upstream_intervention_node_ids),
            "mediated_edge_ids": list(self.mediated_edge_ids),
            "capacity_edge_ids": list(self.capacity_edge_ids),
            "search_capture_edge_ids": list(self.search_capture_edge_ids),
            "formulation_id": self.formulation_id,
        }


def _current_search_object_by_id(
    search_objects: Iterable[SearchObjectDefinition | Mapping[str, object]],
) -> dict[str, SearchObjectDefinition]:
    return {
        item.search_object_id: item
        for item in current_search_object_versions(search_objects)
    }


def candidate_a_graph_issues(
    graph: CausalGraph,
    *,
    search_objects: Iterable[SearchObjectDefinition | Mapping[str, object]] = (),
) -> tuple[str, ...]:
    """Validate only the typed Candidate A Search graph contract.

    Metadata labels and node names are not used as a substitute for governed
    Search identities. Every Search node is bound by ``search_object_id`` and
    the separate delivery object remains descriptive context, not a graph
    node of its own.
    """

    issues: list[str] = []
    definitions = _current_search_object_by_id(search_objects)
    if not definitions:
        return ("Candidate A requires governed Search object definitions",)
    node_by_id = {node.node_id: node for node in graph.nodes}
    outcomes = [node for node in graph.nodes if node.role == NODE_ROLE_OUTCOME]
    if len(outcomes) != 1:
        issues.append("Candidate A requires exactly one fitted final-outcome node")
    outcome = outcomes[0] if len(outcomes) == 1 else None

    required = {
        SEARCH_ROLE_DEMAND: NODE_ROLE_DEMAND_CAPTURE,
        SEARCH_ROLE_PAID_CAP: NODE_ROLE_CAPACITY_OR_CAP,
        SEARCH_ROLE_ORGANIC_CAPTURE: NODE_ROLE_DEMAND_CAPTURE,
        SEARCH_ROLE_DIRECT_NAV_CAPTURE: NODE_ROLE_DEMAND_CAPTURE,
    }
    nodes_by_role: dict[str, list[CausalNode]] = {role: [] for role in required}
    for node in graph.nodes:
        if node.search_object_id in definitions:
            definition = definitions[node.search_object_id]
            if definition.search_role in nodes_by_role:
                nodes_by_role[definition.search_role].append(node)
            elif definition.search_role in {
                SEARCH_ROLE_PAID_SPEND,
                SEARCH_ROLE_PAID_DELIVERY,
            }:
                # Paid spend/delivery remain separate governed objects. Paid
                # delivery is not a graph node; paid spend may be present only
                # as a normal intervention if a separate pathway is declared.
                pass
            else:
                issues.append(
                    f"Node '{node.node_id}' is bound to unsupported Search role "
                    f"'{definition.search_role}'"
                )
        elif node.search_object_id:
            issues.append(
                f"Node '{node.node_id}' references unknown governed Search object "
                f"'{node.search_object_id}'"
            )
    for role, node_role in required.items():
        nodes = nodes_by_role[role]
        if len(nodes) != 1:
            issues.append(
                f"Candidate A requires exactly one '{role}' node with graph role "
                f"'{node_role}'"
            )
        elif nodes[0].role != node_role:
            issues.append(
                f"Search object '{nodes[0].search_object_id}' must use graph role "
                f"'{node_role}'"
            )
    for role in (SEARCH_ROLE_PAID_SPEND, SEARCH_ROLE_PAID_DELIVERY):
        if not any(item.search_role == role for item in definitions.values()):
            issues.append(f"governed Search object for '{role}' is missing")

    if issues or outcome is None:
        return tuple(issues)
    demand = nodes_by_role[SEARCH_ROLE_DEMAND][0]
    cap = nodes_by_role[SEARCH_ROLE_PAID_CAP][0]
    organic = nodes_by_role[SEARCH_ROLE_ORGANIC_CAPTURE][0]
    direct_navigation = nodes_by_role[SEARCH_ROLE_DIRECT_NAV_CAPTURE][0]
    upstream = [
        node
        for node in graph.nodes
        if node.role == NODE_ROLE_INTERVENTION and not node.search_object_id
    ]
    if not upstream:
        issues.append("Candidate A requires at least one upstream intervention")

    mediated = [edge for edge in graph.edges if edge.role == EDGE_ROLE_MEDIATED]
    capacity = [
        edge for edge in graph.edges if edge.role == EDGE_ROLE_CAPACITY_CONSTRAINED
    ]
    expected_upstream_mediated = {(node.node_id, demand.node_id) for node in upstream}
    actual_upstream_mediated = {
        (edge.source_node_id, edge.target_node_id)
        for edge in mediated
        if (edge.source_node_id, edge.target_node_id) in expected_upstream_mediated
    }
    if actual_upstream_mediated != expected_upstream_mediated:
        issues.append(
            "each upstream intervention must have exactly one mediated edge to "
            "latent branded-search demand"
        )
    demand_to_outcome = [
        edge
        for edge in mediated
        if edge.source_node_id == demand.node_id
        and edge.target_node_id == outcome.node_id
    ]
    if len(demand_to_outcome) != 1:
        issues.append(
            "Candidate A requires exactly one mediated branded-demand to final-"
            "outcome edge for realised Search capture"
        )
    demand_to_cap = [
        edge
        for edge in capacity
        if edge.source_node_id == demand.node_id and edge.target_node_id == cap.node_id
    ]
    if len(demand_to_cap) != 1:
        issues.append(
            "Candidate A requires exactly one branded-demand to Paid Search cap "
            "capacity-constrained edge"
        )
    for node in (organic, direct_navigation):
        matching = [
            edge
            for edge in graph.edges
            if edge.source_node_id == node.node_id
            and edge.target_node_id == outcome.node_id
            and edge.role == EDGE_ROLE_DIRECT
        ]
        if len(matching) != 1:
            issues.append(
                f"Search capture node '{node.node_id}' must have exactly one "
                "separate direct edge to the final outcome"
            )
    for node in upstream:
        matching = [
            edge
            for edge in graph.edges
            if edge.source_node_id == node.node_id
            and edge.target_node_id == outcome.node_id
            and edge.role == EDGE_ROLE_DIRECT
        ]
        if len(matching) != 1:
            issues.append(
                f"upstream intervention '{node.node_id}' must retain a separate "
                "direct media-to-outcome pathway"
            )

    allowed = {
        EDGE_ROLE_DIRECT,
        EDGE_ROLE_MEDIATED,
        EDGE_ROLE_CAPACITY_CONSTRAINED,
        EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
    }
    authorised_mediated = expected_upstream_mediated | {
        (demand.node_id, outcome.node_id)
    }
    authorised_capacity = {(demand.node_id, cap.node_id)}
    authorised_capture_direct = {
        (organic.node_id, outcome.node_id),
        (direct_navigation.node_id, outcome.node_id),
    }
    for edge in graph.edges:
        if edge.role not in allowed:
            issues.append(
                f"Candidate A does not support edge role '{edge.role}' in this graph"
            )
            continue
        pair = (edge.source_node_id, edge.target_node_id)
        if edge.role == EDGE_ROLE_DIRECT:
            source = node_by_id.get(edge.source_node_id)
            if pair not in authorised_capture_direct and not (
                source is not None
                and source.role == NODE_ROLE_INTERVENTION
                and edge.target_node_id == outcome.node_id
            ):
                issues.append(
                    f"Candidate A direct edge '{edge.edge_id}' is outside the "
                    "authorised capture or upstream-to-outcome structure"
                )
        if edge.role == EDGE_ROLE_MEDIATED and pair not in authorised_mediated:
            issues.append(
                f"Candidate A mediated edge '{edge.edge_id}' is outside the "
                "authorised upstream/demand/capture structure"
            )
        if (
            edge.role == EDGE_ROLE_CAPACITY_CONSTRAINED
            and pair not in authorised_capacity
        ):
            issues.append(
                f"Candidate A capacity edge '{edge.edge_id}' is outside the authorised "
                "demand-to-cap structure"
            )
    return tuple(dict.fromkeys(issues))


def compile_candidate_a_search_graph(
    graph: CausalGraph,
    *,
    search_objects: Iterable[SearchObjectDefinition | Mapping[str, object]] = (),
) -> SearchCandidateAGraphPlan:
    issues = candidate_a_graph_issues(graph, search_objects=search_objects)
    if issues:
        raise UnsupportedGraphStructureError(
            "Graph is not supported by Candidate A Search engine: " + "; ".join(issues)
        )
    definitions = _current_search_object_by_id(search_objects)
    nodes_by_role = {
        role: next(
            node
            for node in graph.nodes
            if node.search_object_id
            and definitions.get(node.search_object_id, None) is not None
            and definitions[node.search_object_id].search_role == role
        )
        for role in (
            SEARCH_ROLE_DEMAND,
            SEARCH_ROLE_PAID_CAP,
            SEARCH_ROLE_ORGANIC_CAPTURE,
            SEARCH_ROLE_DIRECT_NAV_CAPTURE,
        )
    }
    outcome = next(node for node in graph.nodes if node.role == NODE_ROLE_OUTCOME)
    upstream = tuple(
        node.node_id
        for node in graph.nodes
        if node.role == NODE_ROLE_INTERVENTION and not node.search_object_id
    )
    mediated_ids = tuple(
        edge.edge_id for edge in graph.edges if edge.role == EDGE_ROLE_MEDIATED
    )
    capacity_ids = tuple(
        edge.edge_id
        for edge in graph.edges
        if edge.role == EDGE_ROLE_CAPACITY_CONSTRAINED
    )
    search_capture_ids = tuple(
        edge.edge_id
        for edge in graph.edges
        if edge.source_node_id
        in {
            nodes_by_role[SEARCH_ROLE_DEMAND].node_id,
            nodes_by_role[SEARCH_ROLE_ORGANIC_CAPTURE].node_id,
            nodes_by_role[SEARCH_ROLE_DIRECT_NAV_CAPTURE].node_id,
        }
    )
    return SearchCandidateAGraphPlan(
        outcome_node_id=outcome.node_id,
        demand_node_id=nodes_by_role[SEARCH_ROLE_DEMAND].node_id,
        cap_node_id=nodes_by_role[SEARCH_ROLE_PAID_CAP].node_id,
        organic_capture_node_id=nodes_by_role[SEARCH_ROLE_ORGANIC_CAPTURE].node_id,
        direct_navigation_node_id=nodes_by_role[SEARCH_ROLE_DIRECT_NAV_CAPTURE].node_id,
        upstream_intervention_node_ids=upstream,
        mediated_edge_ids=mediated_ids,
        capacity_edge_ids=capacity_ids,
        search_capture_edge_ids=search_capture_ids,
    )


@dataclass(frozen=True)
class GraphApprovalEligibility:
    """The one reusable "can this graph be approved right now" check
    (REQ-GRAPH-001 work package: engine-ready approval). Combines
    `validate_causal_graph` (structural correctness) and
    `check_engine_capability` (target-engine expressiveness) so a UI never
    has to gate Approve on structural validity alone - a structurally valid
    graph the current engine cannot compile (multi-hop mediation, capacity
    constraints, moderation, residual interaction) must not become
    `GRAPH_STATUS_APPROVED` in the first place; discovering that only at
    "Prepare model configuration" time is too late (REQ-GRAPH-001: reject
    unsupported structures before approval, not only after)."""

    is_eligible: bool
    validation_errors: Tuple[str, ...] = ()
    capability_reasons: Tuple[str, ...] = ()

    @property
    def reasons(self) -> Tuple[str, ...]:
        """Every blocking reason - structural first, then capability - in the
        order a reader should fix them: a structurally invalid graph's
        capability reasons aren't meaningful yet, so capability is only
        checked once validation passes (see
        `check_graph_approval_eligibility`)."""
        return self.validation_errors + self.capability_reasons

    def to_dict(self) -> dict:
        return {
            "is_eligible": self.is_eligible,
            "validation_errors": list(self.validation_errors),
            "capability_reasons": list(self.capability_reasons),
        }


def check_graph_approval_eligibility(
    graph: CausalGraph,
    *,
    engine: str = GRAPH_ENGINE_PYMC_HIERARCHICAL,
    search_objects: Iterable[SearchObjectDefinition | Mapping[str, object]] = (),
) -> GraphApprovalEligibility:
    """The single path a UI or service should call to decide whether Approve
    may be enabled for `graph` against `engine` - never structural validity
    alone. Capability is only evaluated once `graph` is structurally valid
    (an invalid graph's edges/roles aren't reliable enough to reason about
    engine support), mirroring `GraphModelCompiler.compile`'s own two-stage
    check."""
    validation = validate_causal_graph(graph)
    if not validation.is_valid:
        return GraphApprovalEligibility(
            is_eligible=False, validation_errors=validation.errors
        )
    capability_reasons = tuple(
        check_engine_capability(graph, engine=engine, search_objects=search_objects)
    )
    return GraphApprovalEligibility(
        is_eligible=not capability_reasons,
        validation_errors=(),
        capability_reasons=capability_reasons,
    )


def check_engine_capability(
    graph: CausalGraph,
    *,
    engine: str = GRAPH_ENGINE_PYMC_HIERARCHICAL,
    search_objects: Iterable[SearchObjectDefinition | Mapping[str, object]] = (),
) -> List[str]:
    """Reasons the current engine cannot compile this (already
    structurally-valid) graph. Empty list = supported. Does not repeat
    `validate_causal_graph`'s own checks - call that first."""
    if engine == SEARCH_CANDIDATE_A_ENGINE:
        return list(candidate_a_graph_issues(graph, search_objects=search_objects))
    reasons: List[str] = []
    node_by_id = {n.node_id: n for n in graph.nodes}
    for edge in graph.edges:
        if edge.role not in _SUPPORTED_EDGE_ROLES:
            reasons.append(
                f"Edge '{edge.edge_id}' has role '{edge.role}', which "
                f"engine '{engine}' cannot compile - only direct "
                "spend-to-outcome and cross-product halo pathways are "
                "supported today."
            )
            continue
        if edge.role == EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY:
            continue
        source = node_by_id.get(edge.source_node_id)
        target = node_by_id.get(edge.target_node_id)
        if source is None or target is None:
            continue  # validate_causal_graph already reports unknown endpoints
        if source.role != NODE_ROLE_INTERVENTION:
            reasons.append(
                f"Edge '{edge.edge_id}' originates from a '{source.role}' "
                f"node - engine '{engine}' only compiles edges originating "
                f"from an '{NODE_ROLE_INTERVENTION}' node (no multi-hop "
                "mediation support yet)."
            )
        if target.role != NODE_ROLE_OUTCOME:
            reasons.append(
                f"Edge '{edge.edge_id}' targets a '{target.role}' node - "
                f"engine '{engine}' only compiles edges targeting an "
                f"'{NODE_ROLE_OUTCOME}' node directly."
            )
    return reasons


def resolved_pathway_masks_from_graph(
    graph: CausalGraph,
    *,
    activity_definitions: Optional[
        Sequence[ActivityDefinition | Mapping[str, object]]
    ] = None,
    excluded_edge_ids: Optional[set[str]] = None,
) -> ResolvedPathwayMasks:
    """Compiles a graph's structural edges directly into a
    `ResolvedPathwayMasks` - the same operational object
    `resolve_validated_pathway_masks` produces from a `MediaOutcomePathway`
    catalogue. Does not itself validate the graph or check engine
    capability - call `validate_causal_graph`/`check_engine_capability`
    first, or use `GraphModelCompiler.compile`, which does both.

    An edge's `source_node_id` is read as the channel and its
    `target_node_id` as the outcome_id - engine-supported edges always run
    intervention -> outcome (see `check_engine_capability`), so this is a
    direct (channel, outcome_id) cell mapping, not a graph traversal.
    `direct` compiles to `primary_direct`/component_type "direct".
    `cross_product_halo` compiles to `active_cross_product` by default, or
    `exploratory_cross_product` when the edge's metadata sets
    `cross_product_tier: "exploratory"` - the graph domain has no separate
    edge role for this (REQ-GRAPH-001 S5 does not define one); it is a
    governance/evidence-tier distinction carried in metadata, mirroring how
    `MediaOutcomePathway.evidence_status` already works.
    """
    node_by_id = {node.node_id: node for node in graph.nodes}
    components: List[ResolvedPathwayComponent] = []
    for edge in graph.edges:
        if excluded_edge_ids and edge.edge_id in excluded_edge_ids:
            continue
        if edge.role == EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY:
            continue
        if edge.role == EDGE_ROLE_DIRECT:
            role = PATHWAY_ROLE_PRIMARY_DIRECT
            component_type = "direct"
            lag_weeks = 0
        elif edge.role == EDGE_ROLE_CROSS_PRODUCT_HALO:
            tier = edge.metadata.get("cross_product_tier", "active")
            role = (
                PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT
                if tier == "exploratory"
                else PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT
            )
            component_type = "cross_product"
            lag_weeks = edge.lag_weeks or 0
        else:
            raise UnsupportedGraphStructureError(
                f"Edge '{edge.edge_id}' has role '{edge.role}', which "
                "cannot be compiled - call check_engine_capability first."
            )
        source_node = node_by_id[edge.source_node_id]
        predictor, definition = resolve_graph_activity_predictor(
            source_node, activity_definitions or []
        )
        components.append(
            ResolvedPathwayComponent(
                outcome_id=edge.target_node_id,
                channel=predictor,
                component_type=component_type,
                role=role,
                lag_weeks=lag_weeks,
                prior_scale=edge.metadata.get("prior_scale"),
                include_in_attribution=bool(
                    edge.metadata.get("include_in_attribution", True)
                ),
                include_in_planning=bool(
                    edge.metadata.get("include_in_planning", True)
                ),
                include_in_headline=bool(
                    edge.metadata.get("include_in_headline", False)
                ),
                headline_approval_status=edge.metadata.get(
                    "headline_approval_status", "not_reviewed"
                ),
                evidence_status=edge.metadata.get("evidence_status", "unreviewed"),
                included_in_fit=True,
                activity_id=definition.activity_id if definition else "",
                activity_market=(
                    str(
                        source_node.metadata.get("activity_market")
                        or source_node.market
                    )
                    if definition
                    else ""
                ),
            )
        )
    return ResolvedPathwayMasks(components=components)


@dataclass(frozen=True)
class GraphCompilationResult:
    plan: GraphCompilationPlan
    pathway_masks: ResolvedPathwayMasks
    causal_graph_structural_fingerprint: str
    search_candidate_a: Optional[SearchCandidateAGraphPlan] = None


class GraphModelCompiler:
    """The one graph-to-model boundary (REQ-GRAPH-001 work package D).
    Never mutates the graph it compiles."""

    def __init__(
        self,
        engine: str = GRAPH_ENGINE_PYMC_HIERARCHICAL,
        *,
        activity_definitions: Optional[
            Sequence[ActivityDefinition | Mapping[str, object]]
        ] = None,
        search_objects: Optional[
            Sequence[SearchObjectDefinition | Mapping[str, object]]
        ] = None,
    ) -> None:
        self.engine = engine
        self.activity_definitions = activity_definitions
        self.search_objects = search_objects or []

    def compile(self, graph: CausalGraph) -> GraphCompilationResult:
        """Raises UnsupportedGraphStructureError - always with the specific
        reason(s) - if `graph` is not approved, fails validation, or
        contains a structure `self.engine` cannot express. Never partially
        compiles: either every structural edge is captured in the returned
        `ResolvedPathwayMasks`, or nothing is returned at all."""
        if graph.status != GRAPH_STATUS_APPROVED:
            raise UnsupportedGraphStructureError(
                f"Only an approved graph is authoritative for compilation - "
                f"graph '{graph.graph_id}' v{graph.graph_version} has "
                f"status '{graph.status}'."
            )
        validation = validate_causal_graph(graph)
        if not validation.is_valid:
            raise UnsupportedGraphStructureError(
                "Graph failed validation: " + "; ".join(validation.errors)
            )
        capability_issues = check_engine_capability(
            graph, engine=self.engine, search_objects=self.search_objects
        )
        if capability_issues:
            raise UnsupportedGraphStructureError(
                f"Graph is not supported by engine '{self.engine}': "
                + "; ".join(capability_issues)
            )
        plan = build_compilation_plan_preview(
            graph, activity_definitions=self.activity_definitions
        )
        search_candidate_a = None
        if self.engine == SEARCH_CANDIDATE_A_ENGINE:
            search_candidate_a = compile_candidate_a_search_graph(
                graph, search_objects=self.search_objects
            )
            pathway_masks = resolved_pathway_masks_from_graph(
                graph,
                activity_definitions=self.activity_definitions,
                excluded_edge_ids=(
                    set(search_candidate_a.search_capture_edge_ids)
                    | set(search_candidate_a.mediated_edge_ids)
                    | set(search_candidate_a.capacity_edge_ids)
                ),
            )
        else:
            pathway_masks = resolved_pathway_masks_from_graph(
                graph, activity_definitions=self.activity_definitions
            )
        return GraphCompilationResult(
            plan=plan,
            pathway_masks=pathway_masks,
            causal_graph_structural_fingerprint=graph.structural_fingerprint(),
            search_candidate_a=search_candidate_a,
        )


def resolve_pathway_masks_preferring_graph(
    *,
    causal_graph: Optional[CausalGraph],
    outcome_ids: Sequence[str],
    channels: Sequence[str],
    pathways: List[MediaOutcomePathway],
    channel_products: Dict[str, str],
    outcome_products: Dict[str, str],
    fitted_outcome_ids: Sequence[str],
    diagnostic_only_outcome_ids: Sequence[str],
    dna_channel_idx: Sequence[int],
    dna_outcome_id: Optional[str],
    direct_dna_outcome_ids: Sequence[str],
    dna_lag_weeks: int,
    activity_definitions: Optional[
        Sequence[ActivityDefinition | Mapping[str, object]]
    ] = None,
) -> ResolvedPathwayMasks:
    """The one place both `core.hierarchical_model` and
    `core.market_specific_model` resolve pathway masks. If an approved
    `causal_graph` is supplied, it is authoritative and `pathways` is never
    consulted - a graph and the legacy `MediaOutcomePathway` catalogue can
    never silently disagree in a compiled result, because only one of them
    is ever read for it (REQ-GRAPH-001: "no second hidden relationship
    configuration"). If no graph is supplied - a project with no approved
    causal graph configured - this is a byte-for-byte passthrough to
    `core.pathways.resolve_validated_pathway_masks`, identical to what
    every existing caller already gets.
    """
    if causal_graph is not None:
        graph_nodes = {node.node_id: node for node in causal_graph.nodes}
        unknown_targets = sorted(
            {
                edge.target_node_id
                for edge in causal_graph.edges
                if edge.role != EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY
                and graph_nodes.get(edge.target_node_id) is not None
                and graph_nodes[edge.target_node_id].role == NODE_ROLE_OUTCOME
                and edge.target_node_id not in set(outcome_ids)
            }
        )
        if unknown_targets:
            raise UnsupportedGraphStructureError(
                "Approved graph targets outcome ID(s) that are not in the "
                f"fitted outcome catalogue: {unknown_targets}. Adopt and "
                "govern the outcome definition before fitting."
            )
        return (
            GraphModelCompiler(activity_definitions=activity_definitions)
            .compile(causal_graph)
            .pathway_masks
        )
    return resolve_validated_pathway_masks(
        outcome_ids,
        channels,
        pathways,
        channel_products=channel_products,
        outcome_products=outcome_products,
        fitted_outcome_ids=fitted_outcome_ids,
        diagnostic_only_outcome_ids=diagnostic_only_outcome_ids,
        dna_channel_idx=dna_channel_idx,
        dna_outcome_id=dna_outcome_id,
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        dna_lag_weeks=dna_lag_weeks,
    )
