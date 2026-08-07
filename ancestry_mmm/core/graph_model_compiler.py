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
to a `ResolvedPathwayMasks` when a graph is supplied. When no graph is
supplied - every project today, since no graph editor exists yet -
`resolve_pathway_masks_preferring_graph` below is a byte-for-byte passthrough
to `core.pathways.resolve_validated_pathway_masks`.

The current engine cannot compile every structure the graph domain's role
vocabulary can express (REQ-GRAPH-001 S4/S5): `core.hierarchical_model`/
`core.market_specific_model` only understand a flat (outcome_id, channel)
cell system with three equation-gating roles (primary_direct/
active_cross_product/exploratory_cross_product) plus exclusion - there is
no multi-hop mediation, capacity-constraint, moderation, or
residual-interaction pathway in either builder yet. `check_engine_capability`
below says so explicitly and blocks compilation of anything it cannot
express, rather than silently dropping or approximating it (AGENTS.md: do
not imply a dependency natively supports a capability it does not).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .causal_graph import (
    CausalGraph,
    EDGE_ROLE_CROSS_PRODUCT_HALO,
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
    GRAPH_STATUS_APPROVED,
    GraphCompilationPlan,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_OUTCOME,
    build_compilation_plan_preview,
    validate_causal_graph,
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
    graph: CausalGraph, *, engine: str = GRAPH_ENGINE_PYMC_HIERARCHICAL
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
    capability_reasons = tuple(check_engine_capability(graph, engine=engine))
    return GraphApprovalEligibility(
        is_eligible=not capability_reasons,
        validation_errors=(),
        capability_reasons=capability_reasons,
    )


def check_engine_capability(
    graph: CausalGraph, *, engine: str = GRAPH_ENGINE_PYMC_HIERARCHICAL
) -> List[str]:
    """Reasons the current engine cannot compile this (already
    structurally-valid) graph. Empty list = supported. Does not repeat
    `validate_causal_graph`'s own checks - call that first."""
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


def resolved_pathway_masks_from_graph(graph: CausalGraph) -> ResolvedPathwayMasks:
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
    components: List[ResolvedPathwayComponent] = []
    for edge in graph.edges:
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
        components.append(
            ResolvedPathwayComponent(
                outcome_id=edge.target_node_id,
                channel=edge.source_node_id,
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
            )
        )
    return ResolvedPathwayMasks(components=components)


@dataclass(frozen=True)
class GraphCompilationResult:
    plan: GraphCompilationPlan
    pathway_masks: ResolvedPathwayMasks
    causal_graph_structural_fingerprint: str


class GraphModelCompiler:
    """The one graph-to-model boundary (REQ-GRAPH-001 work package D).
    Never mutates the graph it compiles."""

    def __init__(self, engine: str = GRAPH_ENGINE_PYMC_HIERARCHICAL) -> None:
        self.engine = engine

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
        capability_issues = check_engine_capability(graph, engine=self.engine)
        if capability_issues:
            raise UnsupportedGraphStructureError(
                f"Graph is not supported by engine '{self.engine}': "
                + "; ".join(capability_issues)
            )
        plan = build_compilation_plan_preview(graph)
        pathway_masks = resolved_pathway_masks_from_graph(graph)
        return GraphCompilationResult(
            plan=plan,
            pathway_masks=pathway_masks,
            causal_graph_structural_fingerprint=graph.structural_fingerprint(),
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
) -> ResolvedPathwayMasks:
    """The one place both `core.hierarchical_model` and
    `core.market_specific_model` resolve pathway masks. If an approved
    `causal_graph` is supplied, it is authoritative and `pathways` is never
    consulted - a graph and the legacy `MediaOutcomePathway` catalogue can
    never silently disagree in a compiled result, because only one of them
    is ever read for it (REQ-GRAPH-001: "no second hidden relationship
    configuration"). If no graph is supplied - every project today, since
    no graph editor exists yet - this is a byte-for-byte passthrough to
    `core.pathways.resolve_validated_pathway_masks`, identical to what
    every existing caller already gets.
    """
    if causal_graph is not None:
        return GraphModelCompiler().compile(causal_graph).pathway_masks
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
