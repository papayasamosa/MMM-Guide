"""AppTest coverage for pages/14_Causal_Graph.py (REQ-GRAPH-001 work
package E)."""

from pathlib import Path

import streamlit as st
import streamlit_flow as _streamlit_flow_module
from streamlit.testing.v1 import AppTest

st.page_link = lambda *a, **k: None

# streamlit_flow is a genuinely bidirectional custom component: its real
# implementation blocks the script run waiting for a component value only a
# live browser frontend can ever send back, which AppTest's bare-mode
# simulation cannot provide (a run reliably times out after 60s otherwise).
# Patched to a passthrough here, the same way this codebase already shims
# st.page_link above for the same category of reason - AppTest verifies the
# page's own logic (state reconciliation, validation, save/approve/compile),
# not the third-party component's frontend, which the required Playwright
# journey (test_causal_graph_editor_browser.py) exercises for real.
_streamlit_flow_module.streamlit_flow = lambda key, state, **kwargs: state

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "14_Causal_Graph.py"


def test_empty_state_loads_without_error():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    assert any(expander.label == "Role legend" for expander in at.expander)
    assert any("Node roles:" in (caption.value or "") for caption in at.caption)
    node_role_select = next(select for select in at.selectbox if select.label == "Role")
    assert "Planned intervention" in node_role_select.options


def _add_node_form_submit_button(at):
    return next(b for b in at.button if b.label == "Add node")


def test_add_node_via_form_creates_a_node():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception

    next(ti for ti in at.text_input if ti.label == "Node id").set_value("TV")
    next(sb for sb in at.selectbox if sb.label == "Role").set_value("intervention")
    _add_node_form_submit_button(at).click().run()

    assert not at.exception, f"page raised: {at.exception}"
    stored = at.session_state["causal_graph"]
    assert stored is not None
    assert [n["node_id"] for n in stored["nodes"]] == ["TV"]


def test_duplicate_node_id_is_rejected_with_an_error():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    next(ti for ti in at.text_input if ti.label == "Node id").set_value("TV")
    _add_node_form_submit_button(at).click().run()
    next(ti for ti in at.text_input if ti.label == "Node id").set_value("TV")
    _add_node_form_submit_button(at).click().run()

    assert not at.exception
    assert any("already exists" in e.value for e in at.error)


def test_missing_outcome_node_shows_a_validation_error():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    next(ti for ti in at.text_input if ti.label == "Node id").set_value("TV")
    next(sb for sb in at.selectbox if sb.label == "Role").set_value("intervention")
    _add_node_form_submit_button(at).click().run()

    assert not at.exception
    assert any("at least one outcome node" in e.value for e in at.error)


def _add_two_nodes(at):
    next(ti for ti in at.text_input if ti.label == "Node id").set_value("TV")
    next(sb for sb in at.selectbox if sb.label == "Role").set_value("intervention")
    _add_node_form_submit_button(at).click().run()
    next(ti for ti in at.text_input if ti.label == "Node id").set_value("fh_new")
    next(sb for sb in at.selectbox if sb.label == "Role").set_value("outcome")
    _add_node_form_submit_button(at).click().run()


def test_add_edge_via_form_creates_an_edge_and_passes_validation():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    _add_two_nodes(at)

    next(sb for sb in at.selectbox if sb.label == "Source node").set_value("TV")
    next(sb for sb in at.selectbox if sb.label == "Target node").set_value("fh_new")
    next(b for b in at.button if b.label == "Add edge").click().run()

    assert not at.exception, f"page raised: {at.exception}"
    stored = at.session_state["causal_graph"]
    assert len(stored["edges"]) == 1
    assert stored["edges"][0]["source_node_id"] == "TV"
    assert stored["edges"][0]["target_node_id"] == "fh_new"
    assert any(s.value == "Graph passes deterministic validation." for s in at.success)

    next(radio for radio in at.radio if radio.label == "Edit").set_value("Edge").run()
    edge_select = next(select for select in at.selectbox if select.label == "Edge")
    assert any("Direct" in option for option in edge_select.options)
    edge_select.set_value(stored["edges"][0]["edge_id"]).run()
    captions = " ".join(caption.value or "" for caption in at.caption)
    assert "TV → fh new" in captions
    assert "TV -> fh_new" not in captions
    lag_select = next(select for select in at.selectbox if select.label == "Lag type")
    assert "Fixed delay" in lag_select.options
    metric_labels = {metric.label for metric in at.metric}
    assert {"Outcome nodes", "Model inputs", "Structural links"} <= metric_labels
    assert any(
        expander.label == "Technical details · compilation plan"
        for expander in at.expander
    )


def test_approve_is_disabled_until_valid_then_enabled():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    approve_button = next(b for b in at.button if b.label == "Approve")
    assert approve_button.disabled

    _add_two_nodes(at)
    next(sb for sb in at.selectbox if sb.label == "Source node").set_value("TV")
    next(sb for sb in at.selectbox if sb.label == "Target node").set_value("fh_new")
    next(b for b in at.button if b.label == "Add edge").click().run()

    approve_button = next(b for b in at.button if b.label == "Approve")
    assert not approve_button.disabled


def test_approve_is_disabled_for_structurally_valid_but_engine_unsupported_graph():
    """REQ-GRAPH-001 work package: a structurally valid graph the current
    engine cannot compile (here, a mediated edge - multi-hop mediation has
    no engine support yet) must never become approvable - discovering that
    only later, when preparing a model configuration, is too late."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    _add_two_nodes(at)

    next(sb for sb in at.selectbox if sb.label == "Source node").set_value("TV")
    next(sb for sb in at.selectbox if sb.label == "Target node").set_value("fh_new")
    # Two "Role" selectboxes coexist at this point (Add-node form, Add-edge
    # form) - the second is the edge form's.
    edge_role_selectbox = [sb for sb in at.selectbox if sb.label == "Role"][1]
    edge_role_selectbox.set_value("mediated")
    next(b for b in at.button if b.label == "Add edge").click().run()

    assert not at.exception, f"page raised: {at.exception}"
    assert any(s.value == "Graph passes deterministic validation." for s in at.success)
    assert any("cannot compile" in e.value for e in at.error)
    approve_button = next(b for b in at.button if b.label == "Approve")
    assert approve_button.disabled


def test_seed_button_adds_nodes_from_governed_search_objects():
    """REQ-SEARCH-001 work package (graph integration): a governed
    paid_search_spend object seeds an intervention node and a
    paid_search_cap object seeds a capacity_or_cap node - the exact role
    mapping core.search_objects.graph_node_role_for_search_object defines.
    paid_search_delivery has no graph node role and must not be seeded."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["search_objects"] = [
        {
            "search_object_id": "uk_paid_search_spend",
            "search_role": "paid_search_spend",
            "source_column": "paid_search_gbp_spend",
            "unit": "monetary",
            "currency": "GBP",
            "market": "UK",
            "planning_eligibility": "optimisable",
        },
        {
            "search_object_id": "uk_paid_search_cap",
            "search_role": "paid_search_cap",
            "source_column": "daily_budget_cap_gbp",
            "unit": "monetary",
            "currency": "GBP",
            "market": "UK",
        },
        {
            "search_object_id": "uk_paid_search_delivery",
            "search_role": "paid_search_delivery",
            "source_column": "paid_search_clicks",
            "unit": "exposure_count",
            "market": "UK",
        },
    ]
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    next(b for b in at.button if b.label == "Add these as nodes").click().run()
    assert not at.exception, f"seed click raised: {at.exception}"

    stored = at.session_state["causal_graph"]
    nodes_by_id = {n["node_id"]: n for n in stored["nodes"]}
    assert nodes_by_id["uk_paid_search_spend"]["role"] == "intervention"
    assert nodes_by_id["uk_paid_search_cap"]["role"] == "capacity_or_cap"
    assert "uk_paid_search_delivery" not in nodes_by_id
