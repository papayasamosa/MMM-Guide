"""Page 1: upload media / outcomes / controls sources, or load the synthetic demo."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, clear_model_state
from ancestry_mmm.data import load_file, load_all_sample_sources, get_data_summary

st.set_page_config(page_title="Data Upload - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()

st.title("📤 Data Upload")
st.markdown(
    "Upload separate **media**, **outcomes** and **controls** sources (CSV/Excel), each sharing a "
    "date column and (if multi-market) a market column - or start from the synthetic demo dataset."
)

st.session_state.setdefault("project_name", "ancestry-fh-uk")
st.session_state["project_name"] = st.text_input(
    "Project name (used to namespace the curve bank and exports)",
    value=st.session_state["project_name"],
)

tab_demo, tab_upload = st.tabs(["Use synthetic demo data", "Upload your own sources"])

with tab_demo:
    st.markdown(
        "A synthetic weekly UK / Australia / Canada dataset shaped like Ancestry's FH problem - "
        "three segment outcomes, a DNA-targeted media channel with a halo effect, promo flags "
        "per segment, and DNA kit pricing. **Not real Ancestry data** - it exists so the tool is "
        "runnable end-to-end before real data is connected."
    )
    if st.button("Load synthetic demo sources", type="primary"):
        frames, err = load_all_sample_sources()
        if err:
            st.error(err)
        else:
            ltv_df = frames.pop("ltv")
            st.session_state["raw_sources"] = frames
            st.session_state["sample_ltv"] = {row.segment: row.ltv for row in ltv_df.itertuples()}
            st.session_state["data_loaded"] = True
            clear_model_state()
            st.success(f"Loaded demo sources: {', '.join(f'{k} ({v.shape[0]}x{v.shape[1]})' for k, v in frames.items())}")

with tab_upload:
    st.markdown("Upload one file per source. You can add more sources later (e.g. a second controls file).")
    source_name = st.text_input("Source name", value="media", help="e.g. media, outcomes, controls")
    uploaded = st.file_uploader("Choose a CSV or Excel file", type=["csv", "xlsx", "xls"], key="uploader")

    if uploaded is not None and st.button("Add source"):
        df, err = load_file(uploaded)
        if err:
            st.error(err)
        else:
            sources = dict(st.session_state.get("raw_sources") or {})
            sources[source_name] = df
            st.session_state["raw_sources"] = sources
            st.session_state["data_loaded"] = True
            clear_model_state()
            st.success(f"Added source '{source_name}': {df.shape[0]} rows x {df.shape[1]} columns")

sources = st.session_state.get("raw_sources") or {}
if sources:
    st.markdown("---")
    st.markdown("### Loaded sources")
    for name, df in sources.items():
        with st.expander(f"**{name}** - {df.shape[0]} rows x {df.shape[1]} columns", expanded=False):
            summary = get_data_summary(df)
            c1, c2, c3 = st.columns(3)
            c1.metric("Rows", summary["rows"])
            c2.metric("Columns", summary["columns"])
            c3.metric("Missing values", int(summary["missing_values"]))
            st.dataframe(df.head(20), width="stretch")
            if st.button(f"Remove '{name}'", key=f"remove_{name}"):
                sources.pop(name)
                st.session_state["raw_sources"] = sources
                st.rerun()

    st.markdown("---")
    st.info("Next: **Transform Pipeline** to join sources and record any data transforms.")
    if st.button("Continue to Transform Pipeline →", type="primary"):
        st.switch_page("pages/02_Transform_Pipeline.py")
else:
    st.warning("No sources loaded yet. Load the demo data or upload a file to get started.")
