"""
REQ-GRAPH-001: UI-independent causal graph domain.

A `CausalGraph` is one immutable version of a variable-level causal
structure: typed `CausalNode`s and `CausalEdge`s plus a `GraphLayout` that
carries only presentational (canvas) position data. This module is the
first graph domain object in the repository - it does not yet replace
`core.pathways.MediaOutcomePathway`/`core.funnel.FunnelLink` as the
compilation input (that is a dependent requirement); it defines the typed
representation, deterministic validation, fingerprinting and
persistence/invalidation contract those dependents build on.

Two independent fingerprints are the load-bearing contract (REQ-GRAPH-001
S3/S4):

- `structural_fingerprint()` covers only node roles/scopes and edge
  endpoints/roles/lag - anything that changes what would compile.
- `layout_fingerprint()` covers only `GraphLayout` - anything that changes
  only how the graph is drawn.

A layout-only edit changes the layout fingerprint and leaves the structural
fingerprint untouched; a structural edit changes the structural fingerprint.
No other notion of "did the graph change" exists in this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .pathways import LAG_TYPES

# --- Node roles (REQ-GRAPH-001 S4) -----------------------------------------

NODE_ROLE_OUTCOME = "outcome"
NODE_ROLE_INTERVENTION = "intervention"
NODE_ROLE_MEDIATOR = "mediator"
NODE_ROLE_DEMAND_CAPTURE = "demand_capture"
NODE_ROLE_CAPACITY_OR_CAP = "capacity_or_cap"
NODE_ROLE_MODERATOR = "moderator"
NODE_ROLE_CONTROL_OR_CONFOUNDER = "control_or_confounder"
NODE_ROLE_DIAGNOSTIC = "diagnostic"
NODE_ROLE_EXCLUDED = "excluded"

NODE_ROLES = (
    NODE_ROLE_OUTCOME,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_MEDIATOR,
    NODE_ROLE_DEMAND_CAPTURE,
    NODE_ROLE_CAPACITY_OR_CAP,
    NODE_ROLE_MODERATOR,
    NODE_ROLE_CONTROL_OR_CONFOUNDER,
    NODE_ROLE_DIAGNOSTIC,
    NODE_ROLE_EXCLUDED,
)

# --- Edge/pathway roles (REQ-GRAPH-001 S5 - full AGENTS.md taxonomy) -------

EDGE_ROLE_DIRECT = "direct"
EDGE_ROLE_MEDIATED = "mediated"
EDGE_ROLE_CAPACITY_CONSTRAINED = "capacity_constrained"
EDGE_ROLE_CROSS_PRODUCT_HALO = "cross_product_halo"
EDGE_ROLE_MODERATED = "moderated"
EDGE_ROLE_RESIDUAL_INTERACTION = "residual_interaction"
EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY = "excluded_diagnostic_only"

EDGE_ROLES = (
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_MEDIATED,
    EDGE_ROLE_CAPACITY_CONSTRAINED,
    EDGE_ROLE_CROSS_PRODUCT_HALO,
    EDGE_ROLE_MODERATED,
    EDGE_ROLE_RESIDUAL_INTERACTION,
    EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY,
)

# --- Graph status vocabulary (docs/approved_requirements/README.md) -------

GRAPH_STATUS_DRAFT = "draft"
GRAPH_STATUS_APPROVED = "approved"
GRAPH_STATUS_SUPERSEDED = "superseded"
GRAPH_STATUS_DEPRECATED = "deprecated"

GRAPH_STATUSES = (
    GRAPH_STATUS_DRAFT,
    GRAPH_STATUS_APPROVED,
    GRAPH_STATUS_SUPERSEDED,
    GRAPH_STATUS_DEPRECATED,
)

CAUSAL_GRAPH_SCHEMA_VERSION = 1


def _fingerprint_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _deterministic_edge_id(source_node_id: str, target_node_id: str, role: str) -> str:
    key = f"{source_node_id}\x1f{target_node_id}\x1f{role}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


# --- Domain records ---------------------------------------------------------


@dataclass
class CausalNode:
    """One variable in the causal graph.

    `metadata` is a free-form bag for forward-compatible, not-yet-typed
    fields; it is deliberately excluded from `CausalGraph.structural_
    fingerprint()`, same as review-notes-style fields are excluded from
    `core.outcome_approval.fingerprint_outcome_definition` - it never
    determines compiled structure by construction, only calculation-relevant
    typed fields (`role`, `product`, `segment`, `market`) do.
    """

    node_id: str
    label: str = ""
    role: str = NODE_ROLE_DIAGNOSTIC
    product: str = ""
    segment: str = ""
    market: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "CausalNode":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in d.items() if k in known}
        payload.setdefault("metadata", {})
        return cls(**payload)


@dataclass
class CausalEdge:
    """One directed causal relationship between two `CausalNode`s.

    `edge_id` is deterministic when not supplied - a truncated SHA-256 of
    the (source, target, role) natural key, the same pattern
    `core.pathways._deterministic_pathway_id` uses for `pathway_id` - so two
    independently constructed edges for the same relationship compare equal
    without a shared counter or database round-trip.
    """

    source_node_id: str
    target_node_id: str
    role: str = EDGE_ROLE_DIRECT
    lag_type: str = "none"
    lag_weeks: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    edge_id: str = ""

    def __post_init__(self) -> None:
        if not self.edge_id and self.source_node_id and self.target_node_id:
            self.edge_id = _deterministic_edge_id(
                self.source_node_id, self.target_node_id, self.role
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "CausalEdge":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in d.items() if k in known}
        payload.setdefault("metadata", {})
        return cls(**payload)


@dataclass
class NodePosition:
    x: float = 0.0
    y: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "NodePosition":
        return cls(x=float(d.get("x", 0.0)), y=float(d.get("y", 0.0)))


@dataclass
class GraphLayout:
    """Canvas-only presentation state. Never contributes to
    `CausalGraph.structural_fingerprint()` - only to `layout_fingerprint()`.
    """

    positions: Dict[str, NodePosition] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "positions": {
                node_id: pos.to_dict() for node_id, pos in self.positions.items()
            },
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Optional[Mapping[str, Any]]) -> "GraphLayout":
        if not d:
            return cls()
        positions = {
            str(node_id): NodePosition.from_dict(pos)
            for node_id, pos in (d.get("positions") or {}).items()
        }
        return cls(positions=positions, metadata=dict(d.get("metadata") or {}))


@dataclass
class CausalGraph:
    """One immutable version of a causal graph.

    `graph_id` identifies the lineage (the same logical graph across
    versions); `graph_version` is a version number within that lineage.
    Every save is a new `CausalGraph` instance with an incremented
    `graph_version` - this type never mutates history in place (REQ-GRAPH-001
    S2); a caller wanting "the graph over time" holds a list of these,
    ordered by `graph_version`.
    """

    graph_id: str
    graph_version: int = 1
    nodes: List[CausalNode] = field(default_factory=list)
    edges: List[CausalEdge] = field(default_factory=list)
    layout: GraphLayout = field(default_factory=GraphLayout)
    status: str = GRAPH_STATUS_DRAFT
    schema_version: int = CAUSAL_GRAPH_SCHEMA_VERSION
    created_by: str = ""
    created_at: str = ""
    approved_by: str = ""
    approved_at: str = ""

    def to_dict(self) -> dict:
        return {
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "layout": self.layout.to_dict(),
            "status": self.status,
            "schema_version": self.schema_version,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "CausalGraph":
        """Raises ValueError for a schema_version newer than this build
        understands - refuses to guess at an unrecognised future schema
        (REQ-GRAPH-001 S10). Callers importing untrusted bundle content
        should catch this alongside TypeError/KeyError/AttributeError and
        quarantine the record, mirroring
        core.persistence.resolve_imported_outcome_approvals's contract -
        see core.persistence.resolve_imported_causal_graphs.
        """
        schema_version = int(d.get("schema_version", CAUSAL_GRAPH_SCHEMA_VERSION))
        if schema_version > CAUSAL_GRAPH_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported causal graph schema_version {schema_version} - "
                f"this build only understands up to "
                f"{CAUSAL_GRAPH_SCHEMA_VERSION}."
            )
        return cls(
            graph_id=d["graph_id"],
            graph_version=int(d.get("graph_version", 1)),
            nodes=[CausalNode.from_dict(n) for n in d.get("nodes") or []],
            edges=[CausalEdge.from_dict(e) for e in d.get("edges") or []],
            layout=GraphLayout.from_dict(d.get("layout")),
            status=d.get("status", GRAPH_STATUS_DRAFT),
            schema_version=schema_version,
            created_by=d.get("created_by", ""),
            created_at=d.get("created_at", ""),
            approved_by=d.get("approved_by", ""),
            approved_at=d.get("approved_at", ""),
        )

    def structural_fingerprint(self) -> str:
        """Deterministic SHA-256 over only calculation-relevant fields:
        node id/role/product/segment/market, edge id/endpoints/role/lag.
        Independent of node order, edge order, `status`, approval metadata,
        and `layout` entirely."""
        payload = {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "role": n.role,
                    "product": n.product,
                    "segment": n.segment,
                    "market": n.market,
                }
                for n in sorted(self.nodes, key=lambda n: n.node_id)
            ],
            "edges": [
                {
                    "edge_id": e.edge_id,
                    "source_node_id": e.source_node_id,
                    "target_node_id": e.target_node_id,
                    "role": e.role,
                    "lag_type": e.lag_type,
                    "lag_weeks": e.lag_weeks,
                }
                for e in sorted(
                    self.edges,
                    key=lambda e: (
                        e.source_node_id,
                        e.target_node_id,
                        e.role,
                        e.edge_id,
                    ),
                )
            ],
        }
        return _fingerprint_payload(payload)

    def layout_fingerprint(self) -> str:
        """Deterministic SHA-256 over only `layout`. Independent of nodes,
        edges, `status`, and approval metadata entirely."""
        payload = {
            "positions": {
                node_id: pos.to_dict()
                for node_id, pos in sorted(self.layout.positions.items())
            },
            "metadata": self.layout.metadata,
        }
        return _fingerprint_payload(payload)


# --- Deterministic validation (REQ-GRAPH-001 S6) ---------------------------


@dataclass(frozen=True)
class GraphValidationResult:
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict:
        return {"errors": list(self.errors), "warnings": list(self.warnings)}


@dataclass(frozen=True)
class EngineCapabilities:
    """Minimal declaration of what a compilation target engine can express.

    Extended by the dependent graph-model-compiler requirement (REQ-GRAPH-001
    S7); for now this only gates the one relaxation the validator itself
    needs - acyclicity is never relaxed unless explicitly declared
    (REQ-GRAPH-001 S6), never permissive by default.
    """

    allow_capacity_only_cycles: bool = False


def _structural_adjacency(
    edges: Sequence[CausalEdge], node_by_id: Mapping[str, CausalNode]
) -> Dict[str, List[str]]:
    adjacency: Dict[str, List[str]] = {}
    for edge in edges:
        if edge.role == EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY:
            continue
        if (
            edge.source_node_id not in node_by_id
            or edge.target_node_id not in node_by_id
        ):
            continue
        adjacency.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    return adjacency


def _reachable(
    start_ids: Sequence[str], adjacency: Mapping[str, List[str]]
) -> Set[str]:
    seen: Set[str] = set()
    stack: List[str] = list(start_ids)
    while stack:
        current = stack.pop()
        for nxt in adjacency.get(current, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _bad_control_errors(
    nodes: Sequence[CausalNode],
    edges: Sequence[CausalEdge],
    node_by_id: Mapping[str, CausalNode],
) -> List[str]:
    """A control_or_confounder node that lies on a causal path from an
    intervention to an outcome is a mediator or collider misclassified as a
    control (REQ-GRAPH-001 S6)."""
    adjacency = _structural_adjacency(edges, node_by_id)
    reverse_adjacency: Dict[str, List[str]] = {}
    for src, targets in adjacency.items():
        for tgt in targets:
            reverse_adjacency.setdefault(tgt, []).append(src)

    intervention_ids = [n.node_id for n in nodes if n.role == NODE_ROLE_INTERVENTION]
    outcome_ids = [n.node_id for n in nodes if n.role == NODE_ROLE_OUTCOME]
    downstream_of_intervention = _reachable(intervention_ids, adjacency)
    upstream_of_outcome = _reachable(outcome_ids, reverse_adjacency)

    errors: List[str] = []
    for node in nodes:
        if (
            node.role == NODE_ROLE_CONTROL_OR_CONFOUNDER
            and node.node_id in downstream_of_intervention
            and node.node_id in upstream_of_outcome
        ):
            errors.append(
                f"Node '{node.node_id}' is marked "
                f"'{NODE_ROLE_CONTROL_OR_CONFOUNDER}' but lies on a causal "
                "path from an intervention to an outcome - this is a bad "
                "control (a mediator or collider misclassified as a "
                "control)."
            )
    return errors


def _strongly_connected_components(
    adjacency: Mapping[str, List[str]], node_ids: Sequence[str]
) -> List[List[str]]:
    """Tarjan's SCC algorithm. A component of size > 1, or a single node
    with a self-loop, indicates a directed cycle."""
    index_counter = [0]
    stack: List[str] = []
    lowlink: Dict[str, int] = {}
    index: Dict[str, int] = {}
    on_stack: Dict[str, bool] = {}
    result: List[List[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in adjacency.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w):
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            component: List[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.append(w)
                if w == v:
                    break
            result.append(component)

    for node_id in node_ids:
        if node_id not in index:
            strongconnect(node_id)
    return result


def _cycle_errors(
    nodes: Sequence[CausalNode],
    edges: Sequence[CausalEdge],
    node_by_id: Mapping[str, CausalNode],
    capabilities: EngineCapabilities,
) -> List[str]:
    adjacency = _structural_adjacency(edges, node_by_id)
    node_ids = [n.node_id for n in nodes]
    errors: List[str] = []
    for component in _strongly_connected_components(adjacency, node_ids):
        has_self_loop = len(component) == 1 and component[0] in adjacency.get(
            component[0], []
        )
        if len(component) <= 1 and not has_self_loop:
            continue
        component_roles = {
            node_by_id[nid].role for nid in component if nid in node_by_id
        }
        relaxable = component_roles <= {NODE_ROLE_CAPACITY_OR_CAP, NODE_ROLE_DIAGNOSTIC}
        if relaxable and capabilities.allow_capacity_only_cycles:
            continue
        errors.append(
            f"The graph contains a directed cycle among nodes: {sorted(component)}."
        )
    return errors


def validate_causal_graph(
    graph: CausalGraph,
    *,
    engine_capabilities: Optional[EngineCapabilities] = None,
) -> GraphValidationResult:
    """Deterministic validator run on every save/approve (REQ-GRAPH-001 S6).
    Rejects (returns a non-empty `errors` tuple, never raises): duplicate
    node/edge ids, edges referencing unknown nodes, unknown node/edge roles,
    prohibited edge direction, bad controls, incompatible node/edge role
    combinations, directed cycles (unless explicitly relaxed via
    `engine_capabilities`), a missing outcome node, and invalid lag
    configuration."""
    errors: List[str] = []
    warnings: List[str] = []
    capabilities = engine_capabilities or EngineCapabilities()

    seen_node_ids: Set[str] = set()
    node_by_id: Dict[str, CausalNode] = {}
    for node in graph.nodes:
        label = node.node_id or "(no node_id)"
        if not node.node_id:
            errors.append("Every node must have a node_id.")
        elif node.node_id in seen_node_ids:
            errors.append(f"Duplicate node_id '{node.node_id}'.")
        seen_node_ids.add(node.node_id)
        if node.role not in NODE_ROLES:
            errors.append(f"Node '{label}' has unknown role '{node.role}'.")
        node_by_id[node.node_id] = node

    seen_edge_ids: Set[str] = set()
    seen_edge_keys: Set[Tuple[str, str, str]] = set()
    for edge in graph.edges:
        label = edge.edge_id or "(no edge_id)"
        if not edge.edge_id:
            errors.append("Every edge must have an edge_id.")
        elif edge.edge_id in seen_edge_ids:
            errors.append(f"Duplicate edge_id '{edge.edge_id}'.")
        seen_edge_ids.add(edge.edge_id)

        key = (edge.source_node_id, edge.target_node_id, edge.role)
        if key in seen_edge_keys:
            errors.append(
                f"Duplicate edge '{edge.source_node_id}' -> "
                f"'{edge.target_node_id}' with role '{edge.role}'."
            )
        seen_edge_keys.add(key)

        if edge.role not in EDGE_ROLES:
            errors.append(f"Edge '{label}' has unknown role '{edge.role}'.")

        source = node_by_id.get(edge.source_node_id)
        target = node_by_id.get(edge.target_node_id)
        if source is None:
            errors.append(
                f"Edge '{label}' references unknown source node_id "
                f"'{edge.source_node_id}'."
            )
        if target is None:
            errors.append(
                f"Edge '{label}' references unknown target node_id "
                f"'{edge.target_node_id}'."
            )

        if edge.lag_type not in LAG_TYPES:
            errors.append(f"Edge '{label}' has unknown lag_type '{edge.lag_type}'.")
        if edge.lag_type in ("fixed_weeks", "delayed_adstock") and (
            edge.lag_weeks is None or edge.lag_weeks < 0
        ):
            errors.append(
                f"Edge '{label}' has lag_type '{edge.lag_type}' but no valid "
                "non-negative lag_weeks."
            )

        if source is None or target is None or edge.role not in EDGE_ROLES:
            continue  # remaining role-interaction checks need both endpoints and a known role

        if target.role == NODE_ROLE_INTERVENTION:
            errors.append(
                f"Edge '{label}' targets an intervention node "
                f"'{target.node_id}' - interventions are exogenous and "
                "cannot be caused within the graph."
            )
        if (
            source.role == NODE_ROLE_OUTCOME
            and edge.role != EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY
        ):
            errors.append(
                f"Edge '{label}' originates from an outcome node "
                f"'{source.node_id}' with a structural role "
                f"('{edge.role}') - an outcome may only originate a "
                f"'{EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY}' edge."
            )
        if (
            edge.role == EDGE_ROLE_CAPACITY_CONSTRAINED
            and target.role != NODE_ROLE_CAPACITY_OR_CAP
        ):
            errors.append(
                f"Edge '{label}' has role '{EDGE_ROLE_CAPACITY_CONSTRAINED}' "
                f"but its target node '{target.node_id}' is not a "
                f"'{NODE_ROLE_CAPACITY_OR_CAP}' node."
            )
        if edge.role == EDGE_ROLE_MODERATED and source.role != NODE_ROLE_MODERATOR:
            errors.append(
                f"Edge '{label}' has role '{EDGE_ROLE_MODERATED}' but its "
                f"source node '{source.node_id}' is not a "
                f"'{NODE_ROLE_MODERATOR}' node."
            )
        if (
            edge.role == EDGE_ROLE_CROSS_PRODUCT_HALO
            and source.product
            and target.product
            and source.product == target.product
        ):
            errors.append(
                f"Edge '{label}' has role '{EDGE_ROLE_CROSS_PRODUCT_HALO}' "
                f"but source '{source.node_id}' and target "
                f"'{target.node_id}' share the same product "
                f"('{source.product}')."
            )
        if edge.role != EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY and (
            source.role == NODE_ROLE_EXCLUDED or target.role == NODE_ROLE_EXCLUDED
        ):
            errors.append(
                f"Edge '{label}' connects an '{NODE_ROLE_EXCLUDED}' node "
                f"but is not itself role '{EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY}'."
            )
        if edge.role == EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY and edge.metadata.get(
            "include_in_planning"
        ):
            errors.append(
                f"Edge '{label}' is role "
                f"'{EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY}' but carries "
                "planning-eligible metadata ('include_in_planning' is "
                "truthy)."
            )

    if not any(node.role == NODE_ROLE_OUTCOME for node in graph.nodes):
        errors.append("The graph must contain at least one outcome node.")

    errors.extend(_bad_control_errors(graph.nodes, graph.edges, node_by_id))
    errors.extend(_cycle_errors(graph.nodes, graph.edges, node_by_id, capabilities))

    return GraphValidationResult(errors=tuple(errors), warnings=tuple(warnings))


# --- Model-plan preview (REQ-GRAPH-001 S7) ----------------------------------


@dataclass(frozen=True)
class GraphCompilationPlan:
    """A pure preview of what an approved graph would compile to. Does not
    perform or require an engine-capability check - full engine-gated
    compilation is a dependent requirement (REQ-GRAPH-001 S7/S9)."""

    outcome_ids: Tuple[str, ...] = ()
    modelling_columns: Tuple[str, ...] = ()
    pathway_mask_preview: Tuple[Dict[str, Any], ...] = ()
    lag_structure: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self) -> dict:
        return {
            "outcome_ids": list(self.outcome_ids),
            "modelling_columns": list(self.modelling_columns),
            "pathway_mask_preview": [dict(p) for p in self.pathway_mask_preview],
            "lag_structure": [dict(entry) for entry in self.lag_structure],
        }


_MODELLING_COLUMN_ROLES = (
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_MEDIATOR,
    NODE_ROLE_DEMAND_CAPTURE,
    NODE_ROLE_CAPACITY_OR_CAP,
    NODE_ROLE_MODERATOR,
    NODE_ROLE_CONTROL_OR_CONFOUNDER,
)


def build_compilation_plan_preview(graph: CausalGraph) -> GraphCompilationPlan:
    """Raises ValueError if `graph` has any blocking validation error - a
    preview of an invalid graph is not meaningful."""
    result = validate_causal_graph(graph)
    if not result.is_valid:
        raise ValueError(
            "Cannot build a compilation plan preview for an invalid graph: "
            + "; ".join(result.errors)
        )

    outcome_ids = tuple(
        sorted(node.node_id for node in graph.nodes if node.role == NODE_ROLE_OUTCOME)
    )
    modelling_columns = tuple(
        sorted(
            node.node_id for node in graph.nodes if node.role in _MODELLING_COLUMN_ROLES
        )
    )
    structural_edges = sorted(
        (e for e in graph.edges if e.role != EDGE_ROLE_EXCLUDED_DIAGNOSTIC_ONLY),
        key=lambda e: (e.source_node_id, e.target_node_id, e.role),
    )
    pathway_mask_preview = tuple(
        {
            "source_node_id": e.source_node_id,
            "target_node_id": e.target_node_id,
            "role": e.role,
        }
        for e in structural_edges
    )
    lag_structure = tuple(
        {
            "edge_id": e.edge_id,
            "source_node_id": e.source_node_id,
            "target_node_id": e.target_node_id,
            "lag_type": e.lag_type,
            "lag_weeks": e.lag_weeks,
        }
        for e in structural_edges
    )
    return GraphCompilationPlan(
        outcome_ids=outcome_ids,
        modelling_columns=modelling_columns,
        pathway_mask_preview=pathway_mask_preview,
        lag_structure=lag_structure,
    )


# --- Invalidation propagation (REQ-GRAPH-001 S3/S9) -------------------------


@dataclass(frozen=True)
class CausalGraphDependencyIssue:
    """One detected staleness issue in an artefact bound to a causal
    graph's structural fingerprint. Mirrors
    `core.planning.value.ScenarioDependencyIssue`'s shape."""

    artefact_type: str
    artefact_id: str
    issue_type: str  # "stale" | "missing"
    detail: str


def graph_dependency_issues(
    current_structural_fingerprint: str,
    dependents: Sequence[Mapping[str, Any]],
) -> List[CausalGraphDependencyIssue]:
    """For each dependent artefact record - a mapping with at least
    `artefact_type`, `artefact_id`, and `bound_structural_fingerprint` -
    compare its bound structural fingerprint to the graph's current one.

    A layout-only edit never changes `current_structural_fingerprint`
    (`CausalGraph.structural_fingerprint()` is independent of
    `CausalGraph.layout_fingerprint()`), so it never produces an issue here
    - only a structural edit changes what this function reports
    (REQ-GRAPH-001 S3). This is the general-purpose mechanism; wiring it
    against real model-spec/fitted-model/official-curve/scenario records -
    none of which yet reference a causal graph - is a dependent
    requirement's job, not this one's.
    """
    issues: List[CausalGraphDependencyIssue] = []
    for dependent in dependents:
        artefact_type = str(dependent.get("artefact_type", "unknown"))
        artefact_id = str(dependent.get("artefact_id", "<unknown>"))
        bound_fingerprint = dependent.get("bound_structural_fingerprint")
        if not bound_fingerprint:
            issues.append(
                CausalGraphDependencyIssue(
                    artefact_type=artefact_type,
                    artefact_id=artefact_id,
                    issue_type="missing",
                    detail=(
                        "This artefact records no bound structural "
                        "fingerprint - its dependency on any causal graph "
                        "cannot be verified."
                    ),
                )
            )
            continue
        if bound_fingerprint != current_structural_fingerprint:
            issues.append(
                CausalGraphDependencyIssue(
                    artefact_type=artefact_type,
                    artefact_id=artefact_id,
                    issue_type="stale",
                    detail=(
                        f"Bound structural fingerprint {bound_fingerprint!r} "
                        "does not match the graph's current structural "
                        f"fingerprint {current_structural_fingerprint!r} - a "
                        "structural edit occurred since this artefact was "
                        "produced."
                    ),
                )
            )
    return issues
