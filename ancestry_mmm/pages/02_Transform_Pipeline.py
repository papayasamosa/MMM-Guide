"""Page 2: join sources, build an ordered/auditable/replayable transformation pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    clear_model_state,
    dataframe_column_config,
    readable_label,
    OPERATION_LABELS,
    OPERATION_DESCRIPTIONS,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_workspace_note,
    SectionCard,
    InfoPanel,
)
from ancestry_mmm.data import (
    join_sources_with_diagnostics,
    TransformStep,
    SUPPORTED_OPS,
    apply_pipeline,
    pipeline_to_json,
    pipeline_from_json,
    UnsafeExpressionError,
    inspect_source_layout,
    source_table_name,
    source_table_role,
)

JOIN_MODE_OPTIONS = ["inner", "outer", "left", "right"]
JOIN_MODE_HELP = {
    "inner": "Keep only rows whose date (and market) exists in every source. "
    "Any key unique to one source is dropped.",
    "outer": "Keep every row from every source, filling missing values with "
    "blanks where a source has no matching row. This keeps the full time "
    "window visible for review.",
    "left": "Keep every row from the first-listed source, dropping rows from "
    "later sources that don't match it.",
    "right": "Keep every row from the last-listed source, dropping rows from "
    "earlier sources that don't match it.",
}

FILL_STRATEGY_LABELS = {
    "zero": "Fill with zero",
    "mean": "Fill with mean",
    "median": "Fill with median",
    "ffill": "Forward fill",
    "interpolate": "Interpolate",
    "drop_rows": "Drop affected rows",
}


def _step_display(step: TransformStep) -> str:
    """Summarise a saved step without exposing session-state or raw keys."""

    params = step.params
    if step.op == "rename_column":
        return (
            f"Rename {readable_label(params.get('old', 'column'))} to "
            f"{readable_label(params.get('new', 'new column'))}"
        )
    if step.op == "cast_type":
        return (
            f"Change {readable_label(params.get('column', 'column'))} to "
            f"{readable_label(params.get('dtype', 'selected type'))}"
        )
    if step.op == "calculated_column":
        return f"Create {readable_label(params.get('new_column', 'calculated column'))}"
    if step.op == "lag_variable":
        return (
            f"Create a delayed version of {readable_label(params.get('column', 'column'))} "
            f"({params.get('periods', 1)} period(s))"
        )
    if step.op == "fill_missing":
        strategy = FILL_STRATEGY_LABELS.get(
            str(params.get("strategy")), "Selected treatment"
        )
        return (
            f"{strategy} for missing values in "
            f"{readable_label(params.get('column', 'column'))}"
        )
    if step.op == "drop_columns":
        columns = params.get("columns") or ()
        return "Remove " + ", ".join(readable_label(column) for column in columns)
    if step.op == "event_flag":
        return f"Create an event flag named {readable_label(params.get('new_column', 'event flag'))}"
    return str(OPERATION_LABELS.get(step.op, "Saved transformation"))


st.set_page_config(
    page_title="Prepare Data | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("transform_pipeline")

# Header badge reflects where this page's own workflow actually is:
# nothing loaded yet (blocked, checked below), joined but not yet
# transformed (in progress), or a transformed dataset already exists.
sources = get_state("raw_sources") or {}
source_layout = inspect_source_layout(
    sources,
    source_versions=get_state("source_versions") or [],
    active_upload_versions=get_state("active_source_upload_version") or {},
    demo_source_pack=get_state("demo_source_pack"),
)
if get_state("transformed_data") is not None:
    _header_badges = ["ready"]
elif get_state("joined_data") is not None:
    _header_badges = ["current"]
elif sources:
    _header_badges = ["blocked" if source_layout.is_source_native else "not_started"]
else:
    _header_badges = ["awaiting_data"]

render_page_header(
    "transform_pipeline",
    task_prompt=(
        "Review the source-native preparation boundary before modelling."
        if source_layout.is_source_native
        else "Can these sources be joined without losing or inventing rows?"
    ),
    description=source_layout.description,
    badges=_header_badges,
)

render_workspace_note(
    "Review source inputs" if source_layout.is_source_native else "Edit here",
    (
        "The source pack has been ingested, but its dictionaries, irregular events, "
        "and native-frequency tables are not one rectangular join input."
        if source_layout.is_source_native
        else "Choose the join keys and add auditable transformations. The preview below is calculated from those choices."
    ),
    kind="governed" if source_layout.is_source_native else "editable",
)

if not sources:
    st.markdown("---")
    render_empty_state(
        "No data sources loaded yet. Add sources in Data Sources first.",
        button_label="Go to Data Sources",
        target_key="data_upload",
    )
    st.stop()

if source_layout.is_source_native:
    with SectionCard(
        "Source-native preparation boundary",
        description=(
            "Ingestion is complete. Tables that describe the source pack are "
            "kept separate from time-series inputs."
        ),
    ):
        table_rows = []
        for source_id, frame in sources.items():
            table_name = source_table_name(source_id)
            role = source_table_role(source_id)
            if role in {
                "Activity metadata",
                "Outcome metadata",
                "Variable metadata",
            }:
                treatment = "Metadata; not a join input"
            elif role == "Irregular events":
                treatment = "Irregular event table; kept separate"
            elif role == "Experiment evidence":
                treatment = "Evidence table; kept separate"
            else:
                treatment = "Native table; no end-to-end join available"
            table_rows.append(
                {
                    "Table": table_name,
                    "Purpose": role,
                    "Rows": len(frame),
                    "Preparation treatment": treatment,
                }
            )
        st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)
        st.warning(
            "The current application does not have an approved end-to-end "
            "preparation method for this source-native layout. No weekly/monthly "
            "conversion, interpolation, allocation, or fill is applied here."
        )
        st.info(
            "This demo validates the ingestion contract rather than a full model "
            "run. Use Quick demo or upload compatible rectangular model inputs "
            "when you need to continue through the current modelling workflow."
        )
        if st.button("Return to Data Sources", key="source_native_return"):
            st.switch_page("pages/01_Data_Upload.py")
    st.stop()

st.markdown("---")
with SectionCard(
    "1. Join setup",
    description="Choose shared keys and an explicit join mode so row loss and gaps can be reviewed.",
):
    all_columns = sorted(set(c for df in sources.values() for c in df.columns))
    c1, c2 = st.columns(2)
    date_col = c1.selectbox(
        "Shared date column *",
        all_columns,
        index=all_columns.index("date") if "date" in all_columns else 0,
        format_func=readable_label,
    )
    has_market = c2.checkbox(
        "Data has a market/geography column", value="market" in all_columns
    )
    market_col = None
    if has_market:
        market_col = c2.selectbox(
            "Shared market column *",
            all_columns,
            index=all_columns.index("market") if "market" in all_columns else 0,
            format_func=readable_label,
        )

    _saved_join_mode = get_state("join_mode")
    join_mode = st.selectbox(
        "Join mode *",
        JOIN_MODE_OPTIONS,
        index=(
            JOIN_MODE_OPTIONS.index(_saved_join_mode)
            if _saved_join_mode in JOIN_MODE_OPTIONS
            else 0
        ),
        format_func=lambda m: m.capitalize(),
        help="The join mode is an explicit choice. Review row loss and gaps before using the joined data.\n\n"
        + "\n\n".join(f"**{m.capitalize()}**: {h}" for m, h in JOIN_MODE_HELP.items()),
    )

    if st.button("Join sources", type="primary"):
        try:
            joined, join_diagnostics = join_sources_with_diagnostics(
                sources, date_col=date_col, market_col=market_col, how=join_mode
            )
            set_state("joined_data", joined)
            set_state("join_mode", join_mode)
            set_state("join_diagnostics", join_diagnostics.to_dict())
            set_state("date_col", date_col)
            set_state("market_col", market_col)
            clear_model_state()
            st.success(
                f"Joined {len(sources)} source(s) into {joined.shape[0]} rows x {joined.shape[1]} columns."
            )
        except ValueError as e:
            st.error(
                f"Could not join sources: {e} Check that the selected date/market columns exist in every source."
            )

joined = get_state("joined_data")
if joined is None:
    st.info("Join your sources above to continue.")
    st.stop()

join_diagnostics = get_state("join_diagnostics")
if join_diagnostics:
    with SectionCard(
        "Join health",
        description="Row loss and coverage gaps from the join above, kept "
        "visually separate from the join controls themselves.",
    ):
        health_cols = st.columns(3)
        health_cols[0].metric("Joined rows", f"{join_diagnostics['output_rows']:,}")
        health_cols[1].metric("Sources checked", len(join_diagnostics["per_source"]))
        health_cols[2].metric(
            "Sources with row loss",
            sum(s["dropped_keys"] > 0 for s in join_diagnostics["per_source"]),
        )
        st.caption(
            f"Join mode: **{join_diagnostics['join_mode']}** - "
            f"{join_diagnostics['output_rows']} row(s) in the joined result."
        )
        diagnostics_df = pd.DataFrame(join_diagnostics["per_source"])
        diagnostics_df = diagnostics_df.rename(
            columns={
                "source_name": "Source",
                "input_rows": "Rows supplied",
                "input_keys": "Keys supplied",
                "matched_keys": "Keys retained",
                "dropped_keys": "Keys lost",
                "unmatched_keys": "Keys without a match",
            }
        )
        diagnostics_df["Needs attention"] = diagnostics_df.apply(
            lambda row: (
                "Review"
                if row["Keys lost"] > 0 or row["Keys without a match"] > 0
                else "No"
            ),
            axis=1,
        )
        st.dataframe(diagnostics_df, width="stretch", hide_index=True)
        lossy_sources = [
            s for s in join_diagnostics["per_source"] if s["dropped_keys"] > 0
        ]
        if lossy_sources:
            st.warning(
                "This join dropped rows that existed in at least one source. "
                "Review the loss before using the joined data: "
                + "; ".join(
                    f"{s['source_name']} lost {s['dropped_keys']} of "
                    f"{s['input_keys']} row(s)"
                    for s in lossy_sources
                )
            )
        # Review finding (PR #157): an "outer"/"left"/"right" join can keep
        # every row while still leaving some of them without a counterpart in
        # every source (null columns from whichever source didn't have that
        # row) - dropped_keys alone would report this join as loss-free, which
        # is technically true but hides exactly the coverage gap REQ-COVERAGE-001
        # S4 requires be diagnosable. Surfaced as a separate warning from row
        # loss, since "the row is missing" and "the row is present but
        # incomplete" call for different analyst action.
        gappy_sources = [
            s for s in join_diagnostics["per_source"] if s["unmatched_keys"] > 0
        ]
        if gappy_sources:
            st.warning(
                "Some rows in the joined result have no counterpart in every "
                "source, so at least one source's columns will be null for "
                "them: "
                + "; ".join(
                    f"{s['source_name']} has {s['unmatched_keys']} of "
                    f"{s['input_keys']} row(s) without a match in every "
                    "other source"
                    for s in gappy_sources
                )
            )

st.caption("Joined preview (first 10 rows)")
st.dataframe(
    joined.head(10),
    width="stretch",
    column_config=dataframe_column_config(joined.head(10)),
)

st.markdown("---")
st.markdown("### Transformation sequence")
st.caption(
    "Add a step, review its preview, and keep the ordered sequence saved with the project."
)
st.info(
    "Exploratory transformations remain available here for analyst investigation. "
    "They do not approve an official mixed-frequency conversion: interpolation, "
    "allocation, forward-fill, and other fill choices must not be treated as an "
    "official method."
)

steps_json = get_state("pipeline_steps") or []
steps = pipeline_from_json(steps_json)

with st.popover("Add transformation"):
    op = st.selectbox(
        "Operation",
        SUPPORTED_OPS,
        format_func=lambda o: OPERATION_LABELS.get(o, readable_label(o)),
    )
    st.caption(OPERATION_DESCRIPTIONS.get(op, ""))
    params = {}
    description = ""

    if op == "rename_column":
        params["old"] = st.selectbox(
            "Column to rename", list(joined.columns), format_func=readable_label
        )
        params["new"] = st.text_input("New name", placeholder="e.g. tv_brand_spend")
        description = f"Rename {params['old']} -> {params['new']}"

    elif op == "cast_type":
        params["column"] = st.selectbox(
            "Column", list(joined.columns), format_func=readable_label
        )
        params["dtype"] = st.selectbox(
            "New type", ["float", "int", "datetime", "category"]
        )
        description = f"Cast {params['column']} to {params['dtype']}"

    elif op == "calculated_column":
        params["new_column"] = st.text_input("New column name", value="calculated_col")
        params["expression"] = st.text_input(
            "Expression",
            value="",
            placeholder="e.g. Search_Brand + Search_NonBrand",
            help="Column names and arithmetic only (+, -, *, /, parentheses) - no arbitrary code execution.",
        )
        description = f"{params['new_column']} = {params['expression']}"

    elif op == "lag_variable":
        params["column"] = st.selectbox(
            "Column to lag", list(joined.columns), format_func=readable_label
        )
        params["new_column"] = st.text_input("New column name", value="lagged_col")
        params["periods"] = st.number_input("Periods to lag", min_value=1, value=1)
        if market_col:
            params["group_col"] = market_col
        description = (
            f"{params['new_column']} = lag({params['column']}, {params['periods']})"
        )

    elif op == "fill_missing":
        params["column"] = st.selectbox(
            "Column", list(joined.columns), format_func=readable_label
        )
        params["strategy"] = st.selectbox(
            "Missing-value treatment",
            list(FILL_STRATEGY_LABELS),
            format_func=lambda strategy: FILL_STRATEGY_LABELS[strategy],
        )
        if market_col:
            params["group_col"] = market_col
        description = (
            f"{FILL_STRATEGY_LABELS[params['strategy']]} for missing values in "
            f"{readable_label(params['column'])}"
        )

    elif op == "drop_columns":
        params["columns"] = st.multiselect(
            "Columns to drop", list(joined.columns), format_func=readable_label
        )
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
            st.error(
                f"Expression rejected: {e} Use only column names and arithmetic operators (+, -, *, /)."
            )
        except (KeyError, ValueError) as e:
            st.error(
                f"Could not apply this transformation: {e} Check the selected column(s) and settings above."
            )

if steps:
    with SectionCard(
        "Transformation sequence",
        description="The exact sequence applied, in order - each step is "
        "saved and replayed in this order, never reordered implicitly.",
    ):
        for i, step in enumerate(steps):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{i + 1}.** {_step_display(step)}")
            if c2.button("Remove", key=f"remove_step_{i}"):
                steps.pop(i)
                set_state("pipeline_steps", pipeline_to_json(steps))
                st.rerun()

try:
    transformed = apply_pipeline(joined, steps)
    set_state("transformed_data", transformed)
    st.markdown("---")
    with SectionCard(
        "Output preview",
        description="The result of applying every step above, in order, to "
        "the joined data.",
    ):
        st.dataframe(
            transformed.head(10),
            width="stretch",
            column_config=dataframe_column_config(transformed.head(10)),
        )
        st.caption(
            f"{transformed.shape[0]:,} rows x {transformed.shape[1]} columns after {len(steps)} step(s)."
        )

    with InfoPanel(
        "Save and replay",
        description="This pipeline is saved automatically as you add or remove steps.",
    ):
        st.caption(
            "Every step above is stored with the project and replayed in order "
            "whenever this page reruns or the project is re-imported on Export & "
            "Recovery. The sequence is auditable and reusable."
        )

    render_next_step("transform_pipeline")
except (KeyError, ValueError, UnsafeExpressionError) as e:
    st.error(
        f"Pipeline failed to apply: {e} Remove or fix the offending step above, then try again."
    )
