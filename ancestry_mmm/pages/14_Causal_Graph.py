"""Page 14: graph-first causal configuration (REQ-GRAPH-001 work package E).

A drag-and-drop causal graph editor - the first graph-first relationship
configuration surface in the app. Node and edge creation/removal, role and
lag editing, deterministic validation, model-plan preview, draft/approval
lifecycle, and preparing a compiled model configuration through
GraphModelCompiler all live here. Every capability the canvas offers also
has a keyboard-accessible, non-drag equivalent below it (the Add-node form
and the structured node/edge property panel) - no capability exists only as
a mouse-drag gesture.

This page does not implement a second, independently editable relationship
source: it is a UI over core.causal_graph/core.graph_model_compiler only,
never inline logic (ancestry_mmm/pages/AGENTS.md). It does not replace or
remove Structure: Segments & Markets' MediaOutcomePathway catalogue - that
remains usable, but once an approved causal graph exists it is the sole
authoritative structural input the model builders read
(resolve_pathway_masks_preferring_graph, work package D); a project with no
approved graph simply keeps using the pathway catalogue exactly as before.
"""

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
from streamlit_flow import streamlit_flow
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
from streamlit_flow.layouts import ManualLayout
from streamlit_flow.state import StreamlitFlowState

from ancestry_mmm.utils import get_state, init_session_state, set_state
from ancestry_mmm.components import (
    apply_theme,
    render_next_step,
    render_page_header,
    render_sidebar,
    render_status_badge,
    page_readiness,
    SectionCard,
    InfoPanel,
    WarningPanel,
)
from ancestry_mmm.core.causal_graph import (
    CAUSAL_GRAPH_SCHEMA_VERSION,
    EDGE_ROLE_DIRECT,
    EDGE_ROLES,
    GRAPH_STATUS_APPROVED,
    NODE_ROLES,
    CausalEdge,
    CausalGraph,
    CausalNode,
    GraphLayout,
    NodePosition,
    approve_version,
    build_compilation_plan_preview,
    mark_draft_if_approved,
    save_draft_version,
    validate_causal_graph,
)
from ancestry_mmm.core.graph_model_compiler import (
    GRAPH_ENGINE_PYMC_HIERARCHICAL,
    GraphModelCompiler,
    UnsupportedGraphStructureError,
    check_graph_approval_eligibility,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.search_objects import (
    SearchObjectDefinition,
    graph_node_role_for_search_object,
)

_NODE_ROLE_COLORS = {
    "outcome": "#f4a460",
    "intervention": "#4c9be8",
    "mediator": "#9b6bd6",
    "demand_capture": "#5fc79e",
    "capacity_or_cap": "#e0b03a",
    "moderator": "#e07ab0",
    "control_or_confounder": "#9aa0a6",
    "diagnostic": "#c9c9c9",
    "excluded": "#e05a4e",
}


def _new_graph_id() -> str:
    import uuid

    return f"graph-{uuid.uuid4().hex[:12]}"


def _graph_from_state() -> CausalGraph:
    stored = get_state("causal_graph")
    if stored:
        return CausalGraph.from_dict(stored)
    return CausalGraph(graph_id=_new_graph_id(), graph_version=1)


def _persist_graph(graph: CausalGraph) -> None:
    set_state("causal_graph", graph.to_dict())


def _node_label(node: CausalNode) -> str:
    label = node.label or node.node_id
    return f"**{label}**\n\n_{node.role}_"


def _edge_label(edge: CausalEdge) -> str:
    lag = f" ({edge.lag_type}={edge.lag_weeks})" if edge.lag_type != "none" else ""
    return f"{edge.role}{lag}"


def _build_flow_state(graph: CausalGraph) -> StreamlitFlowState:
    nodes = [
        StreamlitFlowNode(
            node.node_id,
            (
                graph.layout.positions.get(node.node_id, NodePosition()).x,
                graph.layout.positions.get(node.node_id, NodePosition()).y,
            ),
            {"content": _node_label(node)},
            "default",
            "right",
            "left",
            draggable=True,
            selectable=True,
            connectable=True,
            deletable=True,
            style={
                "background": _NODE_ROLE_COLORS.get(node.role, "#ffffff"),
                "color": "#1a1a1a",
                "border": "1px solid #333",
            },
        )
        for node in graph.nodes
    ]
    edges = [
        StreamlitFlowEdge(
            edge.edge_id,
            edge.source_node_id,
            edge.target_node_id,
            label=_edge_label(edge),
            animated=False,
            deletable=True,
            marker_end={"type": "arrowclosed"},
        )
        for edge in graph.edges
    ]
    return StreamlitFlowState(nodes=nodes, edges=edges)


def _reconcile_graph_from_flow_state(
    graph: CausalGraph,
    flow_state: StreamlitFlowState,
    removed_edge_ids=frozenset(),
) -> CausalGraph:
    """Update layout positions from the canvas's returned state, and add
    any brand-new edge it reports (drawn by dragging between two node
    handles) as a `direct` edge - the property panel is where its role/lag
    are then set. Never removes a node or edge based on the canvas's
    reported *absence* of one: `graph` (Python) is always authoritative for
    presence; removal only ever happens through the property panel's
    explicit Remove buttons, which mutate `graph` directly. This
    component is genuinely bidirectional (`StreamlitFlowState` carries its
    own `timestamp`-based sync protocol per its changelog) and its echoed
    state can race a few renders behind a just-applied Python-side removal
    or edit - trusting an echoed *absence* as ground truth would silently
    undo a removal/edit that already correctly happened. Trusting only
    additions and positions is safe in both directions: a stale echo can at
    worst re-report a position that hasn't changed, never fabricate or
    erase a node/edge Python already committed.

    `removed_edge_ids` is a tombstone set (session-state-persisted,
    accumulated by every explicit property-panel removal this session) -
    an edge id that has ever been explicitly removed is never re-added
    from a canvas echo, even one this function would otherwise read as
    "brand new" (an id it does not currently recognise). Deterministic
    edge ids are derived only from (source, target, role) - a still-stale
    frontend echo of an edge Python already removed is, by construction,
    indistinguishable from a genuinely new edge unless this tombstone is
    checked."""
    node_by_id = {n.node_id: n for n in graph.nodes}
    edge_by_id = {e.edge_id: e for e in graph.edges}

    positions = {
        sfn.id: NodePosition(
            x=round(float(sfn.position["x"]), 1), y=round(float(sfn.position["y"]), 1)
        )
        for sfn in flow_state.nodes
        if sfn.id in node_by_id
    }

    new_edges = list(graph.edges)
    for sfe in flow_state.edges:
        if sfe.id in edge_by_id or sfe.id in removed_edge_ids:
            continue
        if sfe.source in node_by_id and sfe.target in node_by_id:
            new_edges.append(
                CausalEdge(
                    source_node_id=sfe.source,
                    target_node_id=sfe.target,
                    role=EDGE_ROLE_DIRECT,
                )
            )

    layout = GraphLayout(positions=positions, metadata=graph.layout.metadata)
    return replace(graph, edges=new_edges, layout=layout)


def _reset_property_panel_selection() -> None:
    """Adding or removing a node/edge can invalidate the property panel's
    selectbox-cached selection (a widget `key`'s session-state value that is
    no longer one of the current `options` raises StreamlitAPIException on
    the next rerun) - call this alongside any node/edge id set change.
    A same-id edit (role/lag save) never needs this: the id is preserved."""
    st.session_state.pop("cg_selected_node", None)
    st.session_state.pop("cg_selected_edge", None)


def _graph_change_state(
    graph: CausalGraph, versions: list
) -> "tuple[bool, bool, bool]":
    """Presentation-only derivation of "has this draft changed since it was
    last saved, and was that change structural or layout-only" - reads only
    the two independent fingerprints REQ-GRAPH-001 S3 already defines
    (structural_fingerprint/layout_fingerprint), never a third invented
    notion of change. Compares against the most recently saved version in
    `causal_graph_versions` (Save draft/Approve both append to it); with no
    saved version yet, the current in-memory draft counts as having
    unsaved structural content the moment it has any node or edge.

    Returns (has_unsaved_structural_change, has_unsaved_layout_change,
    has_any_saved_version).
    """
    if not versions:
        return (bool(graph.nodes or graph.edges), bool(graph.layout.positions), False)
    last = CausalGraph.from_dict(versions[-1])
    structural_changed = graph.structural_fingerprint() != last.structural_fingerprint()
    layout_changed = graph.layout_fingerprint() != last.layout_fingerprint()
    return (structural_changed, layout_changed, True)


st.set_page_config(
    page_title="Causal Graph - Ancestry FH MMM",
    page_icon="🕸️",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("causal_graph")

graph = _graph_from_state()
# Tombstone set: every edge_id ever explicitly removed via the property
# panel this session - see _reconcile_graph_from_flow_state's docstring.
removed_edge_ids = set(get_state("cg_removed_edge_ids") or [])
_saved_versions = get_state("causal_graph_versions") or []
_structural_unsaved, _layout_unsaved, _has_saved_version = _graph_change_state(
    graph, _saved_versions
)

render_page_header(
    "causal_graph",
    badges=[page_readiness("causal_graph"), graph.status],
)
st.caption(
    "REQ-GRAPH-001: build the variable-level causal graph node by node and "
    "edge by edge. Every canvas capability also has a keyboard-accessible, "
    "non-drag equivalent below (the Add-node form and the structured "
    "property panel) - nothing here exists only as a mouse-drag gesture. "
    "The workbench below is a three-pane layout - variable library, canvas, "
    "and inspector - all reading and writing the exact same graph state; "
    "the model-plan preview and save/approve/compile controls are full-width "
    "sections beneath it."
)

with InfoPanel(
    "Graph status",
    description="Draft/approved lifecycle and whether this session's edits are structural (would restale a compiled configuration) or layout-only.",
):
    status_summary_cols = st.columns(4)
    status_summary_cols[0].metric("Status", graph.status)
    status_summary_cols[0].caption(
        "draft = editable, not authoritative; approved = authoritative for compilation"
    )
    status_summary_cols[1].metric("Version", graph.graph_version)
    if not _has_saved_version:
        status_summary_cols[2].metric(
            "Structural change",
            "Unsaved (new)" if graph.nodes or graph.edges else "None",
        )
    else:
        status_summary_cols[2].metric(
            "Structural change",
            "Unsaved" if _structural_unsaved else "None since last save",
        )
    status_summary_cols[2].caption(
        "Structural = stales any compiled model configuration once saved/approved."
    )
    if not _has_saved_version:
        status_summary_cols[3].metric(
            "Layout change", "Unsaved (new)" if graph.layout.positions else "None"
        )
    else:
        status_summary_cols[3].metric(
            "Layout change", "Unsaved" if _layout_unsaved else "None since last save"
        )
    status_summary_cols[3].caption(
        "Layout-only = canvas position only, never stales a compiled configuration."
    )

if _structural_unsaved:
    with WarningPanel(
        "Unsaved structural changes",
        description="This edit is continuously kept in the project's session state, but no explicit graph version has recorded it yet.",
    ):
        st.caption(
            "Use Save draft (section 3 below) to record an auditable version, "
            "or Approve once validation and engine readiness both pass."
        )

st.markdown("---")
st.markdown("### 1. Nodes and edges")
st.caption(
    "Drag from a node's edge handle to another node to draw a new edge "
    "(defaults to role 'direct' - set its real role in the inspector), "
    "or drag a node to reposition it. Use the inspector's property panel "
    "to edit a role or lag, or to remove a node or edge - removal always "
    "goes through the property panel, never the canvas directly, so it is "
    "never lost to a delayed canvas update. The Add-node/Add-edge forms "
    "and the property panel work fully with a keyboard or screen reader. "
    "Three panes below - variable library, canvas, inspector - all read "
    "and write the exact same graph state."
)
_workbench_lib_col, _workbench_canvas_col, _workbench_inspector_col = st.columns(
    [1, 1.6, 1.4]
)

_lib_section = SectionCard(
    "Variable library",
    description="Keyboard-accessible node/edge creation - equivalent to a canvas drop or drag-to-connect.",
)
_workbench_lib_col.__enter__()
_lib_section.__enter__()

with st.expander("Seed nodes from current Structure (optional)"):
    spec_dict = get_state("model_spec")
    outcome_defs = get_state("outcome_definitions") or []
    seed_channels = ModelSpec.from_dict(spec_dict).channels if spec_dict else []
    seed_outcome_ids = [
        item.get("outcome_id") for item in outcome_defs if item.get("outcome_id")
    ]
    seed_search_objects = [
        SearchObjectDefinition.from_dict(item)
        for item in (get_state("search_objects") or [])
    ]
    # REQ-SEARCH-001 S8: paid_search_delivery has no graph node of its own
    # (descriptive spend-to-delivery context) - only objects with a
    # resolved node role are seedable here.
    seedable_search_objects = [
        defn for defn in seed_search_objects if graph_node_role_for_search_object(defn)
    ]
    st.caption(
        f"Detected {len(seed_channels)} channel(s), {len(seed_outcome_ids)} "
        f"outcome(s), and {len(seedable_search_objects)} governed Search "
        "object(s) from Structure: Segments & Markets / Channel & Media "
        "Units. Adds one node per item, with the role REQ-SEARCH-001 maps "
        "each Search object to - no edges are inferred or invented."
    )
    if st.button(
        "Add these as nodes",
        disabled=not (seed_channels or seed_outcome_ids or seedable_search_objects),
        key="cg_seed_button",
    ):
        existing_ids = {n.node_id for n in graph.nodes}
        added_nodes = list(graph.nodes)
        positions = dict(graph.layout.positions)
        for index, channel in enumerate(seed_channels):
            if channel in existing_ids:
                continue
            added_nodes.append(CausalNode(node_id=channel, role="intervention"))
            positions[channel] = NodePosition(x=0.0, y=float(index) * 90.0)
        for index, outcome_id in enumerate(seed_outcome_ids):
            if outcome_id in existing_ids:
                continue
            added_nodes.append(CausalNode(node_id=outcome_id, role="outcome"))
            positions[outcome_id] = NodePosition(x=400.0, y=float(index) * 90.0)
        for index, search_defn in enumerate(seedable_search_objects):
            if search_defn.search_object_id in existing_ids:
                continue
            added_nodes.append(
                CausalNode(
                    node_id=search_defn.search_object_id,
                    role=graph_node_role_for_search_object(search_defn),
                    product=search_defn.product,
                    market=search_defn.market if search_defn.market != "*" else "",
                )
            )
            positions[search_defn.search_object_id] = NodePosition(
                x=200.0, y=float(index) * 90.0
            )
        graph = mark_draft_if_approved(
            replace(
                graph,
                nodes=added_nodes,
                layout=GraphLayout(positions=positions, metadata=graph.layout.metadata),
            )
        )
        _persist_graph(graph)
        st.session_state.pop(f"cg_flow_state_{graph.graph_id}", None)
        _reset_property_panel_selection()
        st.rerun()

with st.form("cg_add_node_form", clear_on_submit=True):
    st.caption("Keyboard-accessible node creation (equivalent to a canvas drop).")
    add_cols = st.columns([2, 2, 2])
    new_node_id = add_cols[0].text_input("Node id")
    new_node_role = add_cols[1].selectbox("Role", NODE_ROLES)
    new_node_label = add_cols[2].text_input("Label (optional)")
    if st.form_submit_button("Add node"):
        if not new_node_id:
            st.error("Node id is required.")
        elif new_node_id in {n.node_id for n in graph.nodes}:
            st.error(f"Node id '{new_node_id}' already exists.")
        else:
            graph = mark_draft_if_approved(
                replace(
                    graph,
                    nodes=graph.nodes
                    + [
                        CausalNode(
                            node_id=new_node_id,
                            role=new_node_role,
                            label=new_node_label,
                        )
                    ],
                )
            )
            _persist_graph(graph)
            st.session_state.pop(f"cg_flow_state_{graph.graph_id}", None)
            _reset_property_panel_selection()
            st.rerun()

with st.form("cg_add_edge_form", clear_on_submit=True):
    st.caption(
        "Keyboard-accessible edge creation (equivalent to dragging between "
        "two nodes' handles on the canvas)."
    )
    node_ids = [n.node_id for n in graph.nodes]
    edge_cols = st.columns([2, 2, 2])
    new_edge_source = edge_cols[0].selectbox(
        "Source node", node_ids or ["(add a node first)"]
    )
    new_edge_target = edge_cols[1].selectbox(
        "Target node", node_ids or ["(add a node first)"]
    )
    new_edge_role = edge_cols[2].selectbox("Role", EDGE_ROLES)
    if st.form_submit_button("Add edge"):
        if not node_ids:
            st.error("Add at least one node before adding an edge.")
        else:
            graph = mark_draft_if_approved(
                replace(
                    graph,
                    edges=graph.edges
                    + [
                        CausalEdge(
                            source_node_id=new_edge_source,
                            target_node_id=new_edge_target,
                            role=new_edge_role,
                        )
                    ],
                )
            )
            _persist_graph(graph)
            st.session_state.pop(f"cg_flow_state_{graph.graph_id}", None)
            _reset_property_panel_selection()
            st.rerun()
_lib_section.__exit__(None, None, None)
_workbench_lib_col.__exit__(None, None, None)

_canvas_section = SectionCard(
    "Canvas",
    description="Drag from a node's edge handle to another node to draw a new edge (defaults to role 'direct' - set its real role in the inspector), or drag a node to reposition it.",
)
_workbench_canvas_col.__enter__()
_canvas_section.__enter__()

# Keyed by structural fingerprint (never layout fingerprint) so the
# bidirectional canvas component fully remounts - discarding any stale,
# still-in-flight echo of a just-superseded state - whenever a node/edge is
# added, removed, or has its role/lag changed via a form or the property
# panel. A pure layout edit (dragging a node) does not change this key, so
# an in-progress drag is never disrupted by a remount.
_canvas_state_id = f"{graph.graph_id}_{graph.structural_fingerprint()[:12]}"
flow_state_key = f"cg_flow_state_{_canvas_state_id}"
if flow_state_key not in st.session_state:
    st.session_state[flow_state_key] = _build_flow_state(graph)

st.session_state[flow_state_key] = streamlit_flow(
    key=f"cg_canvas_{_canvas_state_id}",
    state=st.session_state[flow_state_key],
    layout=ManualLayout(),
    fit_view=True,
    height=480,
    show_controls=True,
    allow_new_edges=True,
    get_node_on_click=True,
    get_edge_on_click=True,
    enable_node_menu=True,
    enable_edge_menu=True,
)

reconciled = _reconcile_graph_from_flow_state(
    graph, st.session_state[flow_state_key], removed_edge_ids
)
if reconciled != graph:
    graph = mark_draft_if_approved(reconciled)
    _persist_graph(graph)
_canvas_section.__exit__(None, None, None)
_workbench_canvas_col.__exit__(None, None, None)

_inspector_section = SectionCard(
    "Inspector",
    description="Selected node/edge properties, validation, and engine readiness - reads and writes the exact same graph state as the canvas.",
)
_workbench_inspector_col.__enter__()
_inspector_section.__enter__()
st.markdown("#### Property panel")
st.caption(
    "Structured, keyboard-accessible editing for the selected node or edge "
    "- reads and writes the exact same graph state as the canvas."
)

node_options = ["(none)"] + [n.node_id for n in graph.nodes]
edge_options = ["(none)"] + [e.edge_id for e in graph.edges]
edge_option_labels = {
    e.edge_id: f"{e.source_node_id} -> {e.target_node_id} ({e.role})"
    for e in graph.edges
}
edge_option_labels["(none)"] = "(none)"
selected_kind = st.radio("Edit", ["Node", "Edge"], horizontal=True, key="cg_edit_kind")

if selected_kind == "Node" and len(node_options) > 1:
    selected_node_id = st.selectbox("Node", node_options, key="cg_selected_node")
    if selected_node_id != "(none)":
        node = next(n for n in graph.nodes if n.node_id == selected_node_id)
        with st.form("cg_node_form"):
            label = st.text_input("Label", value=node.label)
            role = st.selectbox("Role", NODE_ROLES, index=NODE_ROLES.index(node.role))
            product = st.text_input("Product", value=node.product)
            segment = st.text_input("Segment", value=node.segment)
            market = st.text_input("Market", value=node.market)
            col_save, col_remove = st.columns(2)
            save_clicked = col_save.form_submit_button("Save node")
            remove_clicked = col_remove.form_submit_button("Remove node")
        if save_clicked:
            updated = replace(
                node,
                label=label,
                role=role,
                product=product,
                segment=segment,
                market=market,
            )
            graph = mark_draft_if_approved(
                replace(
                    graph,
                    nodes=[
                        updated if n.node_id == node.node_id else n for n in graph.nodes
                    ],
                )
            )
            _persist_graph(graph)
            del st.session_state[flow_state_key]
            st.rerun()
        if remove_clicked:
            cascaded_edge_ids = {
                e.edge_id
                for e in graph.edges
                if node.node_id in (e.source_node_id, e.target_node_id)
            }
            graph = mark_draft_if_approved(
                replace(
                    graph,
                    nodes=[n for n in graph.nodes if n.node_id != node.node_id],
                    edges=[
                        e for e in graph.edges if e.edge_id not in cascaded_edge_ids
                    ],
                )
            )
            _persist_graph(graph)
            set_state("cg_removed_edge_ids", list(removed_edge_ids | cascaded_edge_ids))
            del st.session_state[flow_state_key]
            _reset_property_panel_selection()
            st.rerun()
elif selected_kind == "Edge" and len(edge_options) > 1:
    selected_edge_id = st.selectbox(
        "Edge",
        edge_options,
        format_func=lambda eid: edge_option_labels.get(eid, eid),
        key="cg_selected_edge",
    )
    if selected_edge_id != "(none)":
        edge = next(e for e in graph.edges if e.edge_id == selected_edge_id)
        with st.form("cg_edge_form"):
            st.caption(f"{edge.source_node_id} -> {edge.target_node_id}")
            role = st.selectbox("Role", EDGE_ROLES, index=EDGE_ROLES.index(edge.role))
            lag_type = st.selectbox(
                "Lag type",
                ["none", "fixed_weeks", "adstock_only", "delayed_adstock"],
                index=["none", "fixed_weeks", "adstock_only", "delayed_adstock"].index(
                    edge.lag_type
                ),
            )
            lag_weeks = st.number_input(
                "Lag weeks", min_value=0, value=edge.lag_weeks or 0, step=1
            )
            col_save, col_remove = st.columns(2)
            save_clicked = col_save.form_submit_button("Save edge")
            remove_clicked = col_remove.form_submit_button("Remove edge")
        if save_clicked:
            updated = replace(
                edge,
                role=role,
                lag_type=lag_type,
                lag_weeks=lag_weeks if lag_type != "none" else None,
            )
            graph = mark_draft_if_approved(
                replace(
                    graph,
                    edges=[
                        updated if e.edge_id == edge.edge_id else e for e in graph.edges
                    ],
                )
            )
            _persist_graph(graph)
            del st.session_state[flow_state_key]
            st.rerun()
        if remove_clicked:
            graph = mark_draft_if_approved(
                replace(
                    graph, edges=[e for e in graph.edges if e.edge_id != edge.edge_id]
                )
            )
            _persist_graph(graph)
            set_state("cg_removed_edge_ids", list(removed_edge_ids | {edge.edge_id}))
            del st.session_state[flow_state_key]
            _reset_property_panel_selection()
            st.rerun()
else:
    st.caption("No nodes/edges of this kind yet.")

st.markdown("---")
st.markdown("#### Validation")
validation = validate_causal_graph(graph)
if validation.is_valid:
    st.success("Graph passes deterministic validation.")
else:
    st.error(
        "Graph failed validation - fix these before approving:\n\n"
        + "\n".join(f"- {error}" for error in validation.errors)
    )
for warning in validation.warnings:
    st.warning(warning)

st.markdown("#### Engine readiness")
st.caption(
    f"Whether engine '{GRAPH_ENGINE_PYMC_HIERARCHICAL}' - the current "
    "production fitting engine - can compile this graph. Checked before "
    "Approve is enabled, not only when preparing a model configuration "
    "afterwards, so an unsupported structure is never approved in the "
    "first place."
)
approval_eligibility = check_graph_approval_eligibility(
    graph, engine=GRAPH_ENGINE_PYMC_HIERARCHICAL
)
if not validation.is_valid:
    st.info("Fix validation errors above before engine readiness can be checked.")
elif approval_eligibility.is_eligible:
    st.success(f"Engine '{GRAPH_ENGINE_PYMC_HIERARCHICAL}' can compile this graph.")
else:
    st.error(
        "This graph is structurally valid but the current engine cannot "
        "compile it - fix these before approving:\n\n"
        + "\n".join(f"- {reason}" for reason in approval_eligibility.capability_reasons)
    )
_inspector_section.__exit__(None, None, None)
_workbench_inspector_col.__exit__(None, None, None)

st.markdown("---")
st.markdown("### 2. Model-plan preview")
st.caption(
    "A pure preview of what this graph would compile to - no engine "
    "capability check yet (see section 6 for that)."
)
if validation.is_valid:
    plan = build_compilation_plan_preview(graph)
    preview_cols = st.columns(2)
    preview_cols[0].markdown("**Outcome ordering**")
    preview_cols[0].write(list(plan.outcome_ids))
    preview_cols[1].markdown("**Modelling columns**")
    preview_cols[1].write(list(plan.modelling_columns))
    st.markdown("**Pathway mask preview**")
    st.dataframe(plan.to_dict()["pathway_mask_preview"], use_container_width=True)
    st.markdown("**Lag structure**")
    st.dataframe(plan.to_dict()["lag_structure"], use_container_width=True)
else:
    st.info("Fix validation errors above to see the model-plan preview.")

st.markdown("---")
st.markdown("### 3. Save, approve and compile")
status_cols = st.columns(3)
with status_cols[0]:
    # Consistent status-badge vocabulary (Phase 7 QA, docs/decision_log.md):
    # graph.status is one of core.causal_graph.GRAPH_STATUSES
    # (draft/approved/superseded/deprecated), each an exact STATUS_BADGES
    # key - render the same way the header badge above already does,
    # instead of a plain st.metric value.
    st.caption("Status")
    render_status_badge(graph.status)
status_cols[1].metric("Version", graph.graph_version)
status_cols[2].metric(
    "Structural fingerprint", graph.structural_fingerprint()[:12] + "…"
)

save_col, approve_col, compile_col = st.columns(3)
if save_col.button("Save draft"):
    saved = save_draft_version(graph)
    _persist_graph(saved)
    versions = get_state("causal_graph_versions") or []
    set_state("causal_graph_versions", versions + [saved.to_dict()])
    st.rerun()

if approve_col.button("Approve", disabled=not approval_eligibility.is_eligible):
    from datetime import datetime, timezone

    approved = approve_version(
        graph,
        approved_by="analyst",
        approved_at=datetime.now(timezone.utc).isoformat(),
    )
    _persist_graph(approved)
    versions = get_state("causal_graph_versions") or []
    set_state("causal_graph_versions", versions + [approved.to_dict()])
    st.rerun()

if compile_col.button(
    "Prepare model configuration", disabled=graph.status != GRAPH_STATUS_APPROVED
):
    try:
        result = GraphModelCompiler().compile(graph)
    except UnsupportedGraphStructureError as exc:
        st.error(f"The current engine cannot compile this graph: {exc}")
    else:
        set_state(
            "causal_graph_compiled_structural_fingerprint",
            result.causal_graph_structural_fingerprint,
        )
        st.success(
            "Model configuration prepared. Structural fingerprint bound: "
            f"{result.causal_graph_structural_fingerprint[:12]}…"
        )

compiled_fp = get_state("causal_graph_compiled_structural_fingerprint")
if compiled_fp:
    current_fp = graph.structural_fingerprint()
    if compiled_fp == current_fp:
        st.success(
            "The prepared model configuration is current with this graph's structure."
        )
    else:
        st.warning(
            "This graph's structure has changed since the model "
            "configuration was prepared - it is now stale. Re-approve and "
            "prepare again before using it for a fit."
        )

with st.expander("Graph version history"):
    for version in get_state("causal_graph_versions") or []:
        st.write(
            f"v{version.get('graph_version')} - {version.get('status')} - "
            f"{version.get('approved_at') or 'not approved'}"
        )

st.caption(
    f"Schema version: {CAUSAL_GRAPH_SCHEMA_VERSION}. Graph id: {graph.graph_id}."
)

render_next_step("causal_graph")
