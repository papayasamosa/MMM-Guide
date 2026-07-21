"""
Marketing Mix Modelling & Scenario Planner (Home)

An in-house Marketing Mix Modelling and scenario-planning tool built around
Ancestry's actual FH measurement problem: three acquisition paths (New,
DNA cross-sell, Winback) with different media response, different
promotional sensitivity and different value, modelled jointly rather than
as one blended KPI - plus an explicit DNA halo pathway, a versioned curve
bank, and constrained scenario planning.

See docs/ancestry_fh_mmm.md for the full requirements this build serves.

Run with: streamlit run ancestry_mmm/app.py
"""

import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ancestry_mmm.utils import init_session_state, get_state
from ancestry_mmm.utils.workflow import home_workflow_lines
from ancestry_mmm.components import apply_theme, render_sidebar, render_status_card


def setup_page_config():
    st.set_page_config(
        page_title="Marketing Mix Modelling & Scenario Planner",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def main():
    setup_page_config()
    init_session_state()
    apply_theme()
    render_sidebar("home")

    st.title("Marketing Mix Modelling & Scenario Planner")
    st.markdown(
        "A hierarchical marketing mix modelling and scenario planning application for "
        "segment-level measurement, response curves, attribution, diagnostics, and "
        "constrained budget planning."
    )

    st.markdown("---")
    st.markdown("### Workflow")
    st.markdown("\n".join(home_workflow_lines()))

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Upload Data", width="stretch"):
            st.switch_page("pages/01_Data_Upload.py")
    with col2:
        if st.button("View Results", width="stretch"):
            st.switch_page("pages/07_Results_Curve_Bank.py")
    with col3:
        if st.button("Plan Scenarios", width="stretch"):
            st.switch_page("pages/08_Scenario_Planner.py")

    st.markdown("---")
    st.markdown("### Current status")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_status_card("Data", "Loaded" if get_state("data_loaded") else "Not loaded", bool(get_state("data_loaded")))
    with c2:
        spec = get_state("model_spec")
        render_status_card("Structure", "Defined" if spec else "Not defined", bool(spec))
    with c3:
        trained = get_state("model_trained")
        render_status_card("Model", "Trained" if trained else "Not trained", bool(trained))
    with c4:
        scenarios = get_state("scenarios") or []
        render_status_card("Scenarios", str(len(scenarios)), bool(scenarios))


if __name__ == "__main__":
    main()
