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
