"""Page 2: join sources, build an ordered/auditable/replayable transformation pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from ancestry_mmm.utils import init_session_state, get_state, set_state, clear_model_state
from ancestry_mmm.data import (
    join_sources, TransformStep, SUPPORTED_OPS, apply_pipeline,
    pipeline_to_json, pipeline_from_json, UnsafeExpressionError,
)

st.set_page_config(page_title="Transform Pipeline - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()

st.title("🔧 Transform Pipeline")

sources = get_state("raw_sources") or {}
if not sources:
    st.warning("No data sources loaded. Go to **Data Upload** first.")
    st.stop()

st.markdown("### 1. Join sources")
all_columns = sorted(set(c for df in sources.values() for c in df.columns))
c1, c2 = st.columns(2)
date_col = c1.selectbox("Shared date column", all_columns, index=all_columns.index("date") if "date" in all_columns else 0)
has_market = c2.checkbox("Data has a market/geography column", value="market" in all_columns)
market_col = None
if has_market:
    market_col = c2.selectbox("Shared market column", all_columns, index=all_columns.index("market") if "market" in all_columns else 0)

if st.button("Join sources", type="primary"):
    try:
        joined = join_sources(sources, date_col=date_col, market_col=market_col)
        set_state("joined_data", joined)
        set_state("date_col", date_col)
        set_state("market_col", market_col)
        clear_model_state()
        st.success(f"Joined into {joined.shape[0]} rows x {joined.shape[1]} columns.")
    except ValueError as e:
        st.error(str(e))

joined = get_state("joined_data")
if joined is None:
    st.info("Join your sources to continue.")
    st.stop()

st.dataframe(joined.head(10), width="stretch")

st.markdown("---")
st.markdown("### 2. Transformation pipeline")
st.caption(
    "Every transform is recorded as an ordered step, not applied silently - the same steps can be "
    "replayed on refreshed weekly data. Calculated-column expressions are parsed and restricted to "
    "arithmetic on existing columns (no arbitrary code execution)."
)

steps_json = get_state("pipeline_steps") or []
steps = pipeline_from_json(steps_json)

with st.expander("➕ Add a transform step", expanded=len(steps) == 0):
    op = st.selectbox("Operation", SUPPORTED_OPS)
    current_cols = list(joined.columns) if not steps else "computed after preview"
    params = {}
    description = ""

    if op == "rename_column":
        params["old"] = st.selectbox("Column to rename", list(joined.columns))
        params["new"] = st.text_input("New name")
        description = f"Rename {params['old']} -> {params['new']}"

    elif op == "cast_type":
        params["column"] = st.selectbox("Column", list(joined.columns))
        params["dtype"] = st.selectbox("New type", ["float", "int", "datetime", "category"])
        description = f"Cast {params['column']} to {params['dtype']}"

    elif op == "calculated_column":
        params["new_column"] = st.text_input("New column name", value="calculated_col")
        params["expression"] = st.text_input(
            "Expression (column names + arithmetic only, e.g. 'Search_Brand + Search_NonBrand')"
        )
        description = f"{params['new_column']} = {params['expression']}"

    elif op == "lag_variable":
        params["column"] = st.selectbox("Column to lag", list(joined.columns))
        params["new_column"] = st.text_input("New column name", value="lagged_col")
        params["periods"] = st.number_input("Periods to lag", min_value=1, value=1)
        if market_col:
            params["group_col"] = market_col
        description = f"{params['new_column']} = lag({params['column']}, {params['periods']})"

    elif op == "fill_missing":
        params["column"] = st.selectbox("Column", list(joined.columns))
        params["strategy"] = st.selectbox("Strategy", ["zero", "mean", "median", "ffill", "interpolate", "drop_rows"])
        if market_col:
            params["group_col"] = market_col
        description = f"Fill missing in {params['column']} with {params['strategy']}"

    elif op == "drop_columns":
        params["columns"] = st.multiselect("Columns to drop", list(joined.columns))
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
    if st.button("Add step"):
        try:
            new_step = TransformStep(op=op, params=params, description=step_note)
            preview_df = apply_pipeline(joined, steps + [new_step])
            steps.append(new_step)
            set_state("pipeline_steps", pipeline_to_json(steps))
            st.success("Step added.")
            st.rerun()
        except UnsafeExpressionError as e:
            st.error(f"Expression rejected: {e}")
        except (KeyError, ValueError) as e:
            st.error(f"Could not apply step: {e}")

if steps:
    st.markdown("#### Current pipeline")
    for i, step in enumerate(steps):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**{i + 1}.** `{step.op}` - {step.description or step.params}")
        if c2.button("Remove", key=f"remove_step_{i}"):
            steps.pop(i)
            set_state("pipeline_steps", pipeline_to_json(steps))
            st.rerun()

try:
    transformed = apply_pipeline(joined, steps)
    set_state("transformed_data", transformed)
    st.markdown("---")
    st.markdown("### 3. Preview transformed data")
    st.dataframe(transformed.head(10), width="stretch")
    st.caption(f"{transformed.shape[0]} rows x {transformed.shape[1]} columns after {len(steps)} step(s).")

    st.markdown("---")
    if st.button("Continue to Structure: Segments & Markets →", type="primary"):
        st.switch_page("pages/03_Structure_Segments_Markets.py")
except (KeyError, ValueError, UnsafeExpressionError) as e:
    st.error(f"Pipeline failed to apply: {e}")
