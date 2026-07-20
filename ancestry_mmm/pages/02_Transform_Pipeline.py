"""Page 2: join sources, build an ordered/auditable/replayable transformation pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import (
    init_session_state, get_state, set_state, clear_model_state,
    dataframe_column_config, readable_label, OPERATION_LABELS, OPERATION_DESCRIPTIONS,
)
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state
from ancestry_mmm.data import (
    join_sources, TransformStep, SUPPORTED_OPS, apply_pipeline,
    pipeline_to_json, pipeline_from_json, UnsafeExpressionError,
)

st.set_page_config(page_title="Transform Pipeline - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("transform_pipeline")
render_page_header("transform_pipeline")

sources = get_state("raw_sources") or {}
if not sources:
    st.markdown("---")
    render_empty_state(
        "No data sources loaded yet. Complete Data Upload first.",
        button_label="Go to Data Upload", target_key="data_upload",
    )
    st.stop()

st.markdown("---")
st.markdown("### 1. Join sources")
all_columns = sorted(set(c for df in sources.values() for c in df.columns))
c1, c2 = st.columns(2)
date_col = c1.selectbox(
    "Shared date column *", all_columns, index=all_columns.index("date") if "date" in all_columns else 0,
    format_func=readable_label,
)
has_market = c2.checkbox("Data has a market/geography column", value="market" in all_columns)
market_col = None
if has_market:
    market_col = c2.selectbox(
        "Shared market column *", all_columns, index=all_columns.index("market") if "market" in all_columns else 0,
        format_func=readable_label,
    )

if st.button("Join sources", type="primary"):
    try:
        joined = join_sources(sources, date_col=date_col, market_col=market_col)
        set_state("joined_data", joined)
        set_state("date_col", date_col)
        set_state("market_col", market_col)
        clear_model_state()
        st.success(f"Joined {len(sources)} source(s) into {joined.shape[0]} rows x {joined.shape[1]} columns.")
    except ValueError as e:
        st.error(f"Could not join sources: {e} Check that the selected date/market columns exist in every source.")

joined = get_state("joined_data")
if joined is None:
    st.info("Join your sources above to continue.")
    st.stop()

st.dataframe(joined.head(10), width="stretch", column_config=dataframe_column_config(joined.head(10)))

st.markdown("---")
st.markdown("### 2. Transformation pipeline")
st.caption("Each transformation is saved as a reusable step and can be replayed later.")

steps_json = get_state("pipeline_steps") or []
steps = pipeline_from_json(steps_json)

with st.expander("+ Add a transformation", expanded=len(steps) == 0):
    op = st.selectbox("Operation", SUPPORTED_OPS, format_func=lambda o: OPERATION_LABELS.get(o, readable_label(o)))
    st.caption(OPERATION_DESCRIPTIONS.get(op, ""))
    params = {}
    description = ""

    if op == "rename_column":
        params["old"] = st.selectbox("Column to rename", list(joined.columns), format_func=readable_label)
        params["new"] = st.text_input("New name", placeholder="e.g. tv_brand_spend")
        description = f"Rename {params['old']} -> {params['new']}"

    elif op == "cast_type":
        params["column"] = st.selectbox("Column", list(joined.columns), format_func=readable_label)
        params["dtype"] = st.selectbox("New type", ["float", "int", "datetime", "category"])
        description = f"Cast {params['column']} to {params['dtype']}"

    elif op == "calculated_column":
        params["new_column"] = st.text_input("New column name", value="calculated_col")
        params["expression"] = st.text_input(
            "Expression", value="", placeholder="e.g. Search_Brand + Search_NonBrand",
            help="Column names and arithmetic only (+, -, *, /, parentheses) - no arbitrary code execution.",
        )
        description = f"{params['new_column']} = {params['expression']}"

    elif op == "lag_variable":
        params["column"] = st.selectbox("Column to lag", list(joined.columns), format_func=readable_label)
        params["new_column"] = st.text_input("New column name", value="lagged_col")
        params["periods"] = st.number_input("Periods to lag", min_value=1, value=1)
        if market_col:
            params["group_col"] = market_col
        description = f"{params['new_column']} = lag({params['column']}, {params['periods']})"

    elif op == "fill_missing":
        params["column"] = st.selectbox("Column", list(joined.columns), format_func=readable_label)
        params["strategy"] = st.selectbox("Strategy", ["zero", "mean", "median", "ffill", "interpolate", "drop_rows"])
        if market_col:
            params["group_col"] = market_col
        description = f"Fill missing in {params['column']} with {params['strategy']}"

    elif op == "drop_columns":
        params["columns"] = st.multiselect("Columns to drop", list(joined.columns), format_func=readable_label)
        description = f"Drop {params['columns']}"

    elif op == "event_flag":
        params["date_col"] = date_col
        params["new_column"] = st.text_input("New flag column name", value="event_flag")
        c1, c2 = st.columns(2)
        start = c1.date_input("Start date")
        end = c2.date_input("End date")
        params["start"] = str(start)
        params["end"] = str(end)
        description = f"{params['new_column']} = 1 for [{start}, {end}]"

    step_note = st.text_input("Note (optional)", value=description)
    if st.button("Add transformation", type="primary"):
        try:
            new_step = TransformStep(op=op, params=params, description=step_note)
            preview_df = apply_pipeline(joined, steps + [new_step])
            steps.append(new_step)
            set_state("pipeline_steps", pipeline_to_json(steps))
            st.success(f"Transformation added: {OPERATION_LABELS.get(op, op)}.")
            st.rerun()
        except UnsafeExpressionError as e:
            st.error(f"Expression rejected: {e} Use only column names and arithmetic operators (+, -, *, /).")
        except (KeyError, ValueError) as e:
            st.error(f"Could not apply this transformation: {e} Check the selected column(s) and settings above.")

if steps:
    st.markdown("#### Current pipeline")
    for i, step in enumerate(steps):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**{i + 1}.** {OPERATION_LABELS.get(step.op, step.op)} - {step.description or step.params}")
        if c2.button("Remove", key=f"remove_step_{i}"):
            steps.pop(i)
            set_state("pipeline_steps", pipeline_to_json(steps))
            st.rerun()

try:
    transformed = apply_pipeline(joined, steps)
    set_state("transformed_data", transformed)
    st.markdown("---")
    st.markdown("### 3. Preview transformed data")
    st.dataframe(transformed.head(10), width="stretch", column_config=dataframe_column_config(transformed.head(10)))
    st.caption(f"{transformed.shape[0]:,} rows x {transformed.shape[1]} columns after {len(steps)} step(s).")

    render_next_step("transform_pipeline")
except (KeyError, ValueError, UnsafeExpressionError) as e:
    st.error(f"Pipeline failed to apply: {e} Remove or fix the offending step above, then try again.")
