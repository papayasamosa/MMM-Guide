"""Page 1: upload media / outcomes / controls sources, or load the synthetic demo."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, clear_model_state, dataframe_column_config
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state
from ancestry_mmm.data import load_file, load_all_sample_sources, get_data_summary

st.set_page_config(page_title="Data Upload - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("data_upload")
render_page_header("data_upload")

st.markdown("---")
st.session_state.setdefault("project_name", "ancestry-fh-uk")
st.session_state["project_name"] = st.text_input(
    "Project name",
    value=st.session_state["project_name"],
    help="Used to namespace the curve bank and exported project bundles for this project.",
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
            st.success(f"Loaded demo sources: {', '.join(f'{k} ({v.shape[0]} rows x {v.shape[1]} cols)' for k, v in frames.items())}")

with tab_upload:
    st.markdown("Upload one file per source. You can add more sources later (e.g. a second controls file).")
    source_name = st.text_input("Source name *", value="media", help="e.g. media, outcomes, controls")
    uploaded = st.file_uploader("Choose a CSV or Excel file *", type=["csv", "xlsx", "xls"], key="uploader")

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
            st.success(f"Loaded {df.shape[0]} rows from {uploaded.name} as source '{source_name}'.")

sources = st.session_state.get("raw_sources") or {}
if sources:
    st.markdown("---")
    st.markdown("### Loaded sources")
    for name, df in sources.items():
        with st.expander(f"**{name}** - {df.shape[0]} rows x {df.shape[1]} columns", expanded=False):
            summary = get_data_summary(df)
            c1, c2, c3 = st.columns(3)
            c1.metric("Rows", f"{summary['rows']:,}")
            c2.metric("Columns", summary["columns"])
            c3.metric("Missing values", f"{int(summary['missing_values']):,}")
            preview = df.head(20)
            st.dataframe(preview, width="stretch", column_config=dataframe_column_config(preview))
            if st.button(f"Remove '{name}'", key=f"remove_{name}"):
                sources.pop(name)
                st.session_state["raw_sources"] = sources
                st.rerun()

    render_next_step("data_upload")
else:
    render_empty_state("No sources loaded yet. Load the demo data or upload a file above to get started.")
