"""
Ancestry FH MMM & Scenario Planner

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

from ancestry_mmm.utils import init_session_state, get_workflow_progress


def setup_page_config():
    st.set_page_config(
        page_title="Ancestry FH MMM",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def apply_custom_css():
    st.markdown("""
    <style>
    .stApp { background-color: #0F172A; }
    [data-testid="stSidebar"] { background-color: #1E293B; }
    .metric-card {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 20px;
    }
    .stProgress > div > div { background-color: #4F46E5; }
    h1, h2, h3 { color: #F1F5F9; }
    .muted { color: #94A3B8; }
    .success { color: #10B981; }
    .error { color: #EF4444; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)


def render_sidebar():
    with st.sidebar:
        st.markdown("### 🧬 Ancestry FH MMM")
        st.caption("New · DNA cross-sell · Winback")
        st.markdown("---")

        st.markdown("**DATA**")
        st.page_link("pages/01_Data_Upload.py", label="Data Upload")
        st.page_link("pages/02_Transform_Pipeline.py", label="Transform Pipeline")
        st.page_link("pages/03_Structure_Segments_Markets.py", label="Structure: Segments & Markets")

        st.markdown("")
        st.markdown("**MODEL**")
        st.page_link("pages/04_Model_Config.py", label="Model Configuration")
        st.page_link("pages/05_Model_Training.py", label="Model Training")
        st.page_link("pages/06_Diagnostics.py", label="Diagnostics Scorecard")
        st.page_link("pages/07_Results_Curve_Bank.py", label="Results & Curve Bank")

        st.markdown("")
        st.markdown("**PLANNING**")
        st.page_link("pages/08_Scenario_Planner.py", label="Scenario Planner")
        st.page_link("pages/09_Project_Export.py", label="Project Export & Handover")

        st.markdown("---")
        current_step, total_steps = get_workflow_progress()
        st.markdown("**Workflow Progress**")
        st.progress(current_step / total_steps)
        st.caption(f"Step {current_step} of {total_steps}")


def main():
    setup_page_config()
    apply_custom_css()
    init_session_state()
    render_sidebar()

    st.title("Ancestry FH MMM & Scenario Planner")

    st.markdown("""
    A joint hierarchical model across Ancestry's three Family History acquisition
    paths - **New**, **DNA cross-sell** and **Winback** - not a single blended KPI.
    Channel-level adstock and saturation curves are shared; segment response
    strength, promotional sensitivity and the DNA halo pathway are estimated
    through partial pooling, so segments borrow strength where data is thin and
    diverge where the data supports it.

    ### Workflow

    1. **Data Upload** - media / outcomes / controls sources, or the built-in synthetic demo
    2. **Transform Pipeline** - ordered, auditable, replayable data transforms
    3. **Structure: Segments & Markets** - define markets, FH segments, DNA channels, promo columns, LTV
    4. **Model Configuration** - hierarchy, adstock/saturation priors, DNA halo lag
    5. **Model Training** - joint hierarchical Bayesian fit (PyMC / NUTS)
    6. **Diagnostics Scorecard** - convergence, fit, out-of-sample accuracy, plausibility flags
    7. **Results & Curve Bank** - segment + total-FH contributions, versioned curve storage
    8. **Scenario Planner** - manual / constrained / unconstrained-benchmark planning
    9. **Project Export & Handover** - Parquet + JSON + NetCDF bundle, Excel export
    """)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📤 Upload Data", width="stretch"):
            st.switch_page("pages/01_Data_Upload.py")
    with col2:
        if st.button("📊 View Results", width="stretch"):
            st.switch_page("pages/07_Results_Curve_Bank.py")
    with col3:
        if st.button("🎯 Plan Scenarios", width="stretch"):
            st.switch_page("pages/08_Scenario_Planner.py")

    st.markdown("---")
    st.markdown("### Current Status")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Data", "Loaded" if st.session_state.get("data_loaded") else "Not loaded")
    with c2:
        spec = st.session_state.get("model_spec")
        st.metric("Structure", "Defined" if spec else "Not defined")
    with c3:
        st.metric("Model", "Trained" if st.session_state.get("model_trained") else "Not trained")
    with c4:
        st.metric("Scenarios", str(len(st.session_state.get("scenarios") or [])))


if __name__ == "__main__":
    main()
