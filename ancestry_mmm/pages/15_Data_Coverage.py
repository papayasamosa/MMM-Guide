"""Page 15: build and review each governed variable's coverage and
missingness by market before defining model structure (REQ-COVERAGE-001,
Work Package 3 Phase 3b) - reviewable before model preparation, never
surfaced only after fitting (REQ-COVERAGE-001 S3/S5). Optional: nothing
downstream yet consumes this matrix's treatment decisions to alter prepared
data (FR-MOD-015 is unresolved - see REQ-COVERAGE-001 S6), but its
fingerprint is already bound into model identity (core.fingerprint) so a
fit-relevant coverage/treatment edit correctly stales dependent
fits/approvals once that consumption exists.
"""

import sys
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    get_state,
    init_session_state,
    readable_label,
    set_state,
    display_enum_frame,
    display_enum_options,
    restore_enum_frame,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_workspace_note,
    render_status_badges,
    render_technical_details,
    SectionCard,
    InfoPanel,
    create_coverage_fabric_chart,
    STATE_VISUALS,
)
from ancestry_mmm.core.coverage import (
    COVERAGE_STATES,
    TREATMENT_STATUSES,
    VARIABLE_CLASSES,
    CoverageSegment,
    FrequencyMetadata,
    VariableCoverageMatrix,
    build_coverage_matrix_from_frame,
    carry_forward_treatment_decisions,
    current_source_versions,
    new_variable_coverage_matrix_version,
)
from ancestry_mmm.core.coverage_fabric import (
    build_fabric_cells,
    cells_matching_points,
    fabric_summary_sentences,
    filter_cells_by_states,
)
from ancestry_mmm.core.fingerprint import fingerprint_dataframe
from ancestry_mmm.core.frequency_conversion import available_method_ids
from ancestry_mmm.data import adopted_model_input_frame, detect_column_types

FREQUENCY_OPTIONS = ["daily", "weekly", "monthly", "quarterly", "irregular"]
_METHOD_OPTIONS = [
    "",
    *sorted(
        {
            method_id
            for variable_class in VARIABLE_CLASSES
            for method_id in available_method_ids(variable_class)
        }
    ),
]

st.set_page_config(
    page_title="Coverage & Gaps | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("data_coverage")

_official_prepared_data = get_state("official_prepared_data")
_exploratory_data = get_state("transformed_data")
if _official_prepared_data is not None:
    df = _official_prepared_data
    _coverage_source = "official"
elif _exploratory_data is not None:
    df = _exploratory_data
    _coverage_source = (
        "adopted"
        if get_state("transformed_data_origin") == "standard_source_pack"
        else "exploratory"
    )
else:
    # Standard source-pack adoption keeps model inputs separate from the raw
    # workbook tables.  This outer-joined convenience view is useful for
    # coverage review, but remains exploratory until Model Setup creates the
    # official prepared frame.
    df = adopted_model_input_frame(
        outcome_data=get_state("standard_outcome_data"),
        activity_model_input=get_state("standard_activity_model_input"),
        context_model_input=get_state("standard_context_data"),
    )
    _coverage_source = "adopted" if df is not None else "none"
date_col = get_state("date_col")
market_col = get_state("market_col")
_data_ready = df is not None and bool(date_col) and bool(market_col)
_matrix_exists = get_state("variable_coverage_matrix") is not None
if not _data_ready:
    _header_badges = ["awaiting_data"]
elif _matrix_exists:
    _header_badges = ["ready"]
else:
    _header_badges = ["not_started"]

render_page_header(
    "data_coverage",
    task_prompt="Which variables are complete enough, and what treatment is approved for gaps?",
    description=(
        "Review each model input's coverage and missingness by "
        "market, then propose and approve a treatment before this data is "
        "eligible for official use."
    ),
    badges=_header_badges,
)
render_workspace_note(
    "Review and approve",
    "Every gap starts as unknown. Propose a treatment only when its source and rationale are understood.",
    kind="governed",
)

if not _data_ready:
    st.markdown("---")
    render_empty_state(
        "No prepared model inputs with a market column yet. Complete "
        "Prepare Data first - the coverage matrix is built per market, "
        "so a market column is required.",
        button_label="Go to Prepare Data",
        target_key="transform_pipeline",
        what_for=(
            "Reviewing each variable's coverage and missingness "
            "by market before defining model structure."
        ),
        dependency="Prepared data with a market column (Prepare Data).",
        next_action=(
            "Go to Prepare Data to review or prepare model inputs and select "
            "a market column."
        ),
    )
    st.stop()

st.markdown("---")
st.caption(
    "Review model-input coverage before fitting. This page builds a coverage "
    "matrix from the prepared inputs and lets you review and propose treatments for each "
    "variable before model preparation. It never decides *why* a gap exists - "
    "every gap starts as unknown until you reclassify it, and a state is never "
    "inferred merely because a value is absent."
)
if _coverage_source == "official":
    st.info("Reviewing official prepared data. Missing values remain missing.")
elif _coverage_source == "adopted":
    st.info(
        "Reviewing adopted model inputs before official preparation. "
        "This view does not certify official readiness."
    )
elif _coverage_source == "exploratory":
    st.warning(
        "Reviewing exploratory joined data. It can guide investigation but "
        "does not certify official readiness."
    )

all_columns = [c for c in df.columns if c not in (date_col, market_col)]
numeric_cols = [c for c in detect_column_types(df)["numeric"] if c in all_columns]

raw_sources = get_state("raw_sources") or {}
known_versions_by_source = {
    v.source_id: v.version
    for v in current_source_versions(get_state("source_versions") or [])
}
existing_matrix_dict_for_defaults = get_state("variable_coverage_matrix")
existing_matrix_for_defaults = (
    VariableCoverageMatrix.from_dict(existing_matrix_dict_for_defaults)
    if existing_matrix_dict_for_defaults
    else None
)
# Review finding (PR #156): re-deriving source_id/version from scratch on
# every rebuild meant a variable with no recorded SourceVersion (e.g.
# synthetic demo data) silently defaulted to "1" every time, so
# carry_forward_treatment_decisions' "same facts" check could spuriously
# match two rebuilds purely by coincidence, never because the analyst
# actually confirmed the same provenance. Pre-filling from whatever this
# variable was already declared as (frequency and source alike) makes the
# default *stable* across a rebuild instead of re-derived - still fully
# editable, but no longer a fresh guess every time.
existing_frequency_by_variable = (
    {r.variable_id: r.frequency for r in existing_matrix_for_defaults.records}
    if existing_matrix_for_defaults is not None
    else {}
)
existing_source_by_variable = (
    {
        r.variable_id: (r.source_id, r.source_version)
        for r in existing_matrix_for_defaults.records
    }
    if existing_matrix_for_defaults is not None
    else {}
)


def _default_source_id(column: str) -> str:
    for name, source_df in raw_sources.items():
        if column in source_df.columns:
            return name
    return ""


def _default_source(column: str) -> "tuple[str, int]":
    if column in existing_source_by_variable:
        return existing_source_by_variable[column]
    source_id = _default_source_id(column)
    return source_id, known_versions_by_source.get(source_id, 1)


setup_expander = st.expander(
    "Matrix setup and refresh",
    expanded=existing_matrix_for_defaults is None,
)
setup_expander.__enter__()
st.markdown("### Build or refresh the coverage matrix")
variable_columns = st.multiselect(
    "Variables to review",
    all_columns,
    default=numeric_cols,
    format_func=readable_label,
    help="Choose media, outcome, and control columns to review. Date and "
    "market columns are handled separately.",
)

c1, c2 = st.columns(2)
product_col_choice = c1.selectbox(
    "Product/line column (optional)",
    ["(none)"] + all_columns,
    format_func=lambda c: c if c == "(none)" else readable_label(c),
    help="Only needed if this joined frame stacks more than one product's "
    "data under the same variable column names.",
)
segment_col_choice = c2.selectbox(
    "Segment column (optional)",
    ["(none)"] + all_columns,
    format_func=lambda c: c if c == "(none)" else readable_label(c),
)
product_col = None if product_col_choice == "(none)" else product_col_choice
segment_col = None if segment_col_choice == "(none)" else segment_col_choice

if variable_columns:
    st.markdown("#### Per-variable frequency, type and source")
    st.caption(
        "Variable type gates which frequency-alignment methods are eligible - "
        "never one default applied across types. Source and version identify "
        "which upload (Data Sources page) this variable's values came from."
    )
    metadata_rows = []
    for column in variable_columns:
        default_source_id, default_source_version = _default_source(column)
        default_frequency = existing_frequency_by_variable.get(column)
        metadata_rows.append(
            {
                "variable": column,
                "native_frequency": (
                    default_frequency.native_frequency
                    if default_frequency
                    else "weekly"
                ),
                "target_frequency": (
                    default_frequency.target_frequency
                    if default_frequency
                    else "weekly"
                ),
                "variable_class": (
                    default_frequency.variable_class
                    if default_frequency
                    else "flow_count"
                ),
                "method": (default_frequency.method if default_frequency else ""),
                "method_version": (
                    default_frequency.method_version if default_frequency else None
                ),
                "method_parameters_json": json.dumps(
                    default_frequency.method_parameters if default_frequency else {},
                    sort_keys=True,
                ),
                "publication_lag_periods": (
                    default_frequency.publication_lag_periods
                    if default_frequency
                    else 0
                ),
                "publication_timing_json": json.dumps(
                    default_frequency.publication_timing if default_frequency else {},
                    sort_keys=True,
                ),
                "reconciliation_rule": (
                    default_frequency.reconciliation_rule if default_frequency else ""
                ),
                "source_id": default_source_id,
                "source_version": default_source_version,
            }
        )
    _metadata_enum_values = {
        "native_frequency": FREQUENCY_OPTIONS,
        "target_frequency": FREQUENCY_OPTIONS,
        "variable_class": VARIABLE_CLASSES,
        "method": _METHOD_OPTIONS,
    }
    _metadata_editor_df = display_enum_frame(
        pd.DataFrame(metadata_rows), _metadata_enum_values.keys()
    )
    metadata_editor = st.data_editor(
        _metadata_editor_df,
        width="stretch",
        hide_index=True,
        key="coverage_variable_metadata_editor",
        column_config={
            "variable": st.column_config.TextColumn("Variable", disabled=True),
            "native_frequency": st.column_config.SelectboxColumn(
                "Source frequency",
                options=display_enum_options(FREQUENCY_OPTIONS),
                required=True,
            ),
            "target_frequency": st.column_config.SelectboxColumn(
                "Model frequency",
                options=display_enum_options(FREQUENCY_OPTIONS),
                required=True,
            ),
            "variable_class": st.column_config.SelectboxColumn(
                "Data type",
                options=display_enum_options(sorted(VARIABLE_CLASSES)),
                required=True,
            ),
            "method": st.column_config.SelectboxColumn(
                "Approved method (explicit)",
                options=_METHOD_OPTIONS,
                help=(
                    "Select an exact method for mixed-frequency variables. "
                    "Blank is deliberate and remains blocked until reviewed."
                ),
            ),
            "method_version": st.column_config.NumberColumn(
                "Method version",
                min_value=1,
                step=1,
                help="Version of the approved method implementation.",
            ),
            "method_parameters_json": st.column_config.TextColumn(
                "Method parameters (JSON)",
                help="Explicit method parameters; use {} when none are required.",
            ),
            "publication_lag_periods": st.column_config.NumberColumn(
                "Publication lag (periods)",
                min_value=0,
                step=1,
            ),
            "publication_timing_json": st.column_config.TextColumn(
                "Publication timing (JSON)",
                help='For example {"release_date_column": "released_on"}.',
            ),
            "reconciliation_rule": st.column_config.TextColumn(
                "Reconciliation rule",
                help="Describe the source-to-target reconciliation rule.",
            ),
            "source_id": st.column_config.TextColumn("Source", required=True),
            "source_version": st.column_config.NumberColumn(
                "Source version",
                min_value=1,
                step=1,
                required=True,
                help="Version of the governed source containing this variable.",
            ),
        },
    )
    metadata_editor = restore_enum_frame(
        metadata_editor,
        _metadata_enum_values.keys(),
        _metadata_enum_values,
    )

    if st.button("Build coverage matrix", type="primary"):
        try:
            frequency_metadata = {
                str(row["variable"]): FrequencyMetadata(
                    native_frequency=str(row["native_frequency"]),
                    target_frequency=str(row["target_frequency"]),
                    variable_class=str(row["variable_class"]),
                    method=str(row.get("method") or "").strip(),
                    method_version=(
                        None
                        if pd.isna(row.get("method_version"))
                        or not str(row.get("method_version") or "").strip()
                        else int(row["method_version"])
                    ),
                    method_parameters=json.loads(
                        str(row.get("method_parameters_json") or "{}")
                    ),
                    publication_lag_periods=int(
                        row.get("publication_lag_periods") or 0
                    ),
                    publication_timing=json.loads(
                        str(row.get("publication_timing_json") or "{}")
                    ),
                    reconciliation_rule=str(
                        row.get("reconciliation_rule") or ""
                    ).strip(),
                )
                for _, row in metadata_editor.iterrows()
            }
            variable_sources = {
                str(row["variable"]): (
                    str(row["source_id"]),
                    int(row["source_version"]),
                )
                for _, row in metadata_editor.iterrows()
            }
            existing = existing_matrix_for_defaults
            matrix_id = (
                existing.matrix_id
                if existing is not None
                else f"coverage-{get_state('project_name', 'default')}"
            )
            generated_at = datetime.now(timezone.utc).isoformat()
            built = build_coverage_matrix_from_frame(
                df,
                date_col=date_col,
                market_col=market_col,
                variable_columns=variable_columns,
                frequency_metadata=frequency_metadata,
                variable_sources=variable_sources,
                matrix_id=matrix_id,
                matrix_version=(existing.matrix_version if existing else 0) + 1,
                generated_at=generated_at,
                product_col=product_col,
                segment_col=segment_col,
            )
            new_records = (
                carry_forward_treatment_decisions(built.records, existing.records)
                if existing is not None
                else built.records
            )
            if existing is not None:
                new_matrix = new_variable_coverage_matrix_version(
                    existing, records=new_records, generated_at=generated_at
                )
                set_state(
                    "variable_coverage_matrix_versions",
                    (get_state("variable_coverage_matrix_versions") or [])
                    + [existing.to_dict()],
                )
            else:
                new_matrix = VariableCoverageMatrix(
                    matrix_id=matrix_id,
                    matrix_version=1,
                    generated_at=generated_at,
                    records=new_records,
                )
            set_state("variable_coverage_matrix", new_matrix.to_dict())
            # Review finding (PR #156): record which joined dataframe this
            # matrix was actually built against, so a later edit to
            # Transform Pipeline (or a project import, which never restores
            # this session-only key) can be detected and flagged as
            # staleness below - mirrors causal_graph_compiled_structural_
            # fingerprint's live-comparison pattern rather than baking a
            # build-environment fingerprint into the portable matrix itself.
            set_state(
                "variable_coverage_matrix_built_against_fingerprint",
                fingerprint_dataframe(df),
            )
            st.success(
                f"Built coverage matrix version {new_matrix.matrix_version} "
                f"with {len(new_matrix.records)} record(s)."
            )
        except ValueError as e:
            st.error(f"Could not build the coverage matrix: {e}")

setup_expander.__exit__(None, None, None)

current_matrix_dict = get_state("variable_coverage_matrix")
if current_matrix_dict is None:
    st.info("Build a coverage matrix above to review it.")
    render_next_step("data_coverage")
    st.stop()

matrix = VariableCoverageMatrix.from_dict(current_matrix_dict)

st.markdown("---")
with st.container(border=True):
    st.markdown("### Coverage summary")
    summary_cols = st.columns(4)
    summary_cols[0].metric("Variables", len({r.variable_id for r in matrix.records}))
    summary_cols[1].metric("Markets", len({r.market for r in matrix.records}))
    summary_cols[2].metric(
        "Gap segments", sum(len(r.coverage_segments) for r in matrix.records)
    )
    summary_cols[3].metric("Unresolved", len(matrix.blocking_issues))
    render_status_badges(["blocked" if matrix.blocking_issues else "ready"])
    st.caption(
        "Review the fabric and unresolved gaps below. Matrix setup is secondary and remains available above."
    )

st.markdown("### Coverage fabric")
st.caption(
    "A time-by-variable-by-market view built from the coverage matrix above. "
    "Selecting or filtering here never changes the review state; classification "
    "and treatment approval remain explicit controls below."
)

_fabric_cells = build_fabric_cells(matrix)
_fabric_summary = fabric_summary_sentences(matrix)
if _fabric_summary:
    with InfoPanel("Coverage summary"):
        st.markdown("\n".join(f"- {s}" for s in _fabric_summary))

if not _fabric_cells:
    st.caption(
        "No coverage-fabric cells to render yet - every variable's "
        "expected window (or, absent one, every recorded gap segment) is "
        "empty for this matrix."
    )
else:
    _fabric_states_present = sorted({c.state for c in _fabric_cells})
    _fabric_state_labels = {s: STATE_VISUALS[s][0] for s in _fabric_states_present}
    _fabric_selected_states = st.multiselect(
        "Isolate state(s)",
        _fabric_states_present,
        format_func=lambda s: _fabric_state_labels[s],
        help="Filter the fabric below to only the selected state(s) - e.g. "
        "unknown or expected data missing, source unavailable, or "
        "estimated evidence. This never changes governance state, only "
        "what's shown.",
        key="coverage_fabric_state_filter",
    )
    _fabric_filtered_cells = filter_cells_by_states(
        _fabric_cells, _fabric_selected_states
    )
    _fabric_fig = create_coverage_fabric_chart(_fabric_filtered_cells)
    _fabric_event = st.plotly_chart(
        _fabric_fig,
        width="stretch",
        on_select="rerun",
        selection_mode="points",
        key="coverage_fabric_chart",
    )
    _fabric_points = (
        (_fabric_event.get("selection") or {}).get("points") or []
        if _fabric_event
        else []
    )
    _fabric_selected_cells = cells_matching_points(
        _fabric_filtered_cells, _fabric_points
    )
    if _fabric_selected_cells:
        _inspected = _fabric_selected_cells[0]
        _r = _inspected.record
        with SectionCard(f"Inspector: {_inspected.row.row_label}"):
            st.caption(
                f"Segment {_inspected.period_start} to {_inspected.period_end} - "
                f"state **{STATE_VISUALS.get(_inspected.state, (_inspected.state,))[0]}**"
            )
            ic1, ic2, ic3 = st.columns(3)
            ic1.metric("Native frequency", _r.frequency.native_frequency)
            ic1.metric("Target frequency", _r.frequency.target_frequency)
            ic1.metric("Approved method", _r.frequency.method or "Not selected")
            ic2.metric("Source", f"{_r.source_id} v{_r.source_version}")
            ic2.metric(
                "Observed window",
                f"{_r.observed_start or 'n/a'} to {_r.observed_end or 'n/a'}",
            )
            ic3.metric("Treatment status", readable_label(_r.treatment_status))
            ic3.metric(
                "Approved for official use",
                "Yes" if _r.approved_for_official_use else "No",
            )
            st.caption(
                "Method version: "
                + (
                    str(_r.frequency.method_version)
                    if _r.frequency.method_version is not None
                    else "not selected"
                )
                + "; publication lag: "
                + str(_r.frequency.publication_lag_periods)
                + " period(s); reconciliation: "
                + (_r.frequency.reconciliation_rule or "not recorded")
            )
            render_technical_details(
                details={
                    "Method parameters": json.dumps(
                        _r.frequency.method_parameters, sort_keys=True
                    ),
                    "Publication timing": json.dumps(
                        _r.frequency.publication_timing, sort_keys=True
                    ),
                    "Definition breaks": "; ".join(
                        f"{item.break_date}: {item.description}"
                        for item in _r.definition_breaks
                    )
                    or "None recorded",
                }
            )
            if _r.approved_treatment:
                st.caption(
                    f"Approved treatment: {readable_label(_r.approved_treatment)}"
                )
    else:
        st.caption(
            "Click or box-select a segment above to inspect its full detail here."
        )

st.markdown("---")
st.markdown("### 3. Review coverage")
st.caption(f"Reviewing {len(matrix.records)} variable-by-market records.")
render_technical_details(
    details={
        "Matrix ID": matrix.matrix_id,
        "Version": str(matrix.matrix_version),
        "Generated": matrix.generated_at,
        "Records": str(len(matrix.records)),
    }
)

# Review finding (PR #156): a matrix built against an earlier Transform
# Pipeline join (or restored from an imported project bundle, which never
# carries this session-only key) can silently drift out of sync with the
# *current* joined data - the observed/expected windows and gap segments
# below would then describe data that no longer matches what a fit would
# actually use. Comparing live rather than baking the check into the build
# step is deliberate: it also catches a data change made *after* this
# matrix was last built, not only a stale build itself.
built_against_fingerprint = get_state(
    "variable_coverage_matrix_built_against_fingerprint"
)
if built_against_fingerprint != fingerprint_dataframe(df):
    st.warning(
        "This matrix may be stale: the prepared inputs have changed (or this "
        "matrix was restored from an imported project) since it was last "
        "built. Rebuild above to confirm the coverage below still matches "
        "the current data."
    )

blocking_issues = matrix.blocking_issues
if blocking_issues:
    st.warning(
        "The following variables have unresolved coverage not yet "
        "approved for official use:"
    )
    st.markdown("\n".join(f"- {issue}" for issue in blocking_issues))
else:
    st.success(
        "No unresolved blocking coverage - every record is either fully "
        "covered or has an approved official-use treatment."
    )

summary_rows = [
    {
        "variable": record.variable_id,
        "market": record.market,
        "product": record.product or "",
        "segment": record.segment or "",
        "native_frequency": record.frequency.native_frequency,
        "target_frequency": record.frequency.target_frequency,
        "method": record.frequency.method or "",
        "method_version": record.frequency.method_version or "",
        "publication_lag_periods": record.frequency.publication_lag_periods,
        "reconciliation_rule": record.frequency.reconciliation_rule,
        "observed_start": record.observed_start or "",
        "observed_end": record.observed_end or "",
        "expected_start": record.expected_start or "",
        "expected_end": record.expected_end or "",
        "gap_segments": len(record.coverage_segments),
        "gap_states": ", ".join(
            readable_label(state)
            for state in sorted({segment.state for segment in record.coverage_segments})
        ),
        "officially_unresolved": record.is_officially_unresolved,
    }
    for record in matrix.records
]
summary_df = pd.DataFrame(summary_rows).rename(
    columns={
        "variable": "Variable",
        "market": "Market",
        "product": "Product",
        "segment": "Customer segment",
        "native_frequency": "Source frequency",
        "target_frequency": "Model frequency",
        "method": "Approved method",
        "method_version": "Method version",
        "publication_lag_periods": "Publication lag",
        "reconciliation_rule": "Reconciliation rule",
        "observed_start": "Observed start",
        "observed_end": "Observed end",
        "expected_start": "Expected start",
        "expected_end": "Expected end",
        "gap_segments": "Gap segments",
        "gap_states": "Gap states",
        "officially_unresolved": "Official use",
    }
)
summary_df["Official use"] = summary_df["Official use"].map(
    lambda unresolved: "Review" if unresolved else "Ready"
)
st.dataframe(summary_df, width="stretch", hide_index=True)

st.markdown("#### Gap segment classification")
st.caption(
    "A gap is never inferred as anything beyond 'unknown' - reclassify each "
    "one here to the state that actually applies "
    "(expected data missing, not applicable, source unavailable, suppressed, "
    "estimated, modelled, or a genuine structural zero) before approving a "
    "treatment for it below. A structural-zero segment requires selecting "
    "Observed zero and providing a non-empty justification - pre-launch may "
    "be structural zero only when the activity genuinely did not exist, "
    "never merely because a source lacks history."
)
segment_rows = []
segment_record_indices = []
for record_index, record in enumerate(matrix.records):
    for segment in record.coverage_segments:
        segment_rows.append(
            {
                "variable": record.variable_id,
                "market": record.market,
                "product": record.product or "",
                "segment": record.segment or "",
                "period_start": segment.period_start,
                "period_end": segment.period_end,
                "state": segment.state,
                "structural_zero": segment.structural_zero,
                "justification": segment.justification,
            }
        )
        segment_record_indices.append(record_index)

if not segment_rows:
    st.caption("Every variable is fully covered - no gap segments to classify.")
else:
    _segment_enum_values = {"state": COVERAGE_STATES}
    _segment_editor_df = display_enum_frame(
        pd.DataFrame(segment_rows), _segment_enum_values.keys()
    )
    segment_editor = st.data_editor(
        _segment_editor_df,
        width="stretch",
        hide_index=True,
        disabled=[
            "variable",
            "market",
            "product",
            "segment",
            "period_start",
            "period_end",
        ],
        key="coverage_segment_editor",
        column_config={
            "state": st.column_config.SelectboxColumn(
                "Coverage state",
                options=display_enum_options(COVERAGE_STATES),
                required=True,
            ),
            "variable": st.column_config.TextColumn("Variable", disabled=True),
            "market": st.column_config.TextColumn("Market", disabled=True),
            "product": st.column_config.TextColumn("Product", disabled=True),
            "segment": st.column_config.TextColumn("Customer segment", disabled=True),
            "period_start": st.column_config.TextColumn("Gap starts", disabled=True),
            "period_end": st.column_config.TextColumn("Gap ends", disabled=True),
            "structural_zero": st.column_config.CheckboxColumn(
                "Genuine structural zero"
            ),
            "justification": st.column_config.TextColumn("Reason / justification"),
        },
    )
    segment_editor = restore_enum_frame(
        segment_editor, _segment_enum_values.keys(), _segment_enum_values
    )

    if st.button("Save gap classifications", type="primary"):
        segment_errors = []
        segments_by_record: "dict[int, list[CoverageSegment]]" = defaultdict(list)
        for record_index, (_, row) in zip(
            segment_record_indices, segment_editor.fillna("").iterrows()
        ):
            try:
                segments_by_record[record_index].append(
                    CoverageSegment(
                        period_start=str(row["period_start"]),
                        period_end=str(row["period_end"]),
                        state=str(row["state"]),
                        structural_zero=bool(row["structural_zero"]),
                        justification=str(row["justification"]),
                    )
                )
            except ValueError as e:
                offending = matrix.records[record_index]
                segment_errors.append(
                    f"{offending.variable_id} ({offending.market}) "
                    f"{row['period_start']}..{row['period_end']}: {e}"
                )
        for error in segment_errors:
            st.error(error)
        if not segment_errors:
            new_records = [
                (
                    replace(
                        record,
                        coverage_segments=tuple(segments_by_record[record_index]),
                    )
                    if record_index in segments_by_record
                    else record
                )
                for record_index, record in enumerate(matrix.records)
            ]
            generated_at = datetime.now(timezone.utc).isoformat()
            new_matrix = new_variable_coverage_matrix_version(
                matrix, records=tuple(new_records), generated_at=generated_at
            )
            set_state(
                "variable_coverage_matrix_versions",
                (get_state("variable_coverage_matrix_versions") or [])
                + [matrix.to_dict()],
            )
            set_state("variable_coverage_matrix", new_matrix.to_dict())
            st.success(
                f"Saved gap classifications as matrix version "
                f"{new_matrix.matrix_version}."
            )

st.markdown("---")
_treatment_section = SectionCard(
    "4. Propose and approve treatments",
    description=(
        "Unresolved unknown or expected-data-missing coverage never becomes "
        "official fit input silently - a variable stays "
        "exploratory until you approve a treatment for it here. "
        "'Approved for official use' requires an approved treatment, an "
        "approver and an approval date."
    ),
)
# Manual __enter__/__exit__ (matched below, before the version-history
# expander) rather than an indented `with` block - this section's existing
# button/data_editor code is already deeply nested with early-exit
# branches; re-indenting all of it to fit under a `with` would balloon this
# migration's diff for a purely cosmetic wrapper. SectionCard's context
# manager protocol is unchanged either way (see components/ui.py).
_treatment_section.__enter__()
treatment_rows = [
    {
        "variable": record.variable_id,
        "market": record.market,
        "product": record.product or "",
        "segment": record.segment or "",
        "proposed_treatment": record.proposed_treatment,
        "treatment_status": record.treatment_status,
        "approved_treatment": record.approved_treatment or "",
        "treatment_approved_by": record.treatment_approved_by or "",
        "treatment_approved_at": record.treatment_approved_at or "",
        "approved_for_official_use": record.approved_for_official_use,
    }
    for record in matrix.records
]
_treatment_enum_values = {"treatment_status": TREATMENT_STATUSES}
_treatment_editor_df = display_enum_frame(
    pd.DataFrame(treatment_rows), _treatment_enum_values.keys()
)
treatment_editor = st.data_editor(
    _treatment_editor_df,
    width="stretch",
    hide_index=True,
    disabled=["variable", "market", "product", "segment"],
    key="coverage_treatment_editor",
    column_config={
        "treatment_status": st.column_config.SelectboxColumn(
            "Treatment status",
            options=display_enum_options(sorted(TREATMENT_STATUSES)),
            required=True,
        ),
        "variable": st.column_config.TextColumn("Variable", disabled=True),
        "market": st.column_config.TextColumn("Market", disabled=True),
        "product": st.column_config.TextColumn("Product", disabled=True),
        "segment": st.column_config.TextColumn("Customer segment", disabled=True),
        "proposed_treatment": st.column_config.TextColumn("Proposed treatment"),
        "approved_treatment": st.column_config.TextColumn("Approved treatment"),
        "treatment_approved_by": st.column_config.TextColumn("Approved by"),
        "treatment_approved_at": st.column_config.TextColumn(
            "Approved on (YYYY-MM-DD)"
        ),
        "approved_for_official_use": st.column_config.CheckboxColumn(
            "Approved for official use"
        ),
    },
)
treatment_editor = restore_enum_frame(
    treatment_editor, _treatment_enum_values.keys(), _treatment_enum_values
)

if st.button("Save treatment decisions", type="primary"):
    treatment_errors = []
    new_records = []
    for record, (_, row) in zip(matrix.records, treatment_editor.fillna("").iterrows()):
        try:
            new_records.append(
                replace(
                    record,
                    proposed_treatment=str(row["proposed_treatment"]),
                    treatment_status=str(row["treatment_status"] or "proposed"),
                    approved_treatment=str(row["approved_treatment"]) or None,
                    treatment_approved_by=str(row["treatment_approved_by"]) or None,
                    treatment_approved_at=str(row["treatment_approved_at"]) or None,
                    approved_for_official_use=bool(row["approved_for_official_use"]),
                )
            )
        except ValueError as e:
            treatment_errors.append(f"{record.variable_id} ({record.market}): {e}")
    for error in treatment_errors:
        st.error(error)
    if not treatment_errors:
        generated_at = datetime.now(timezone.utc).isoformat()
        new_matrix = new_variable_coverage_matrix_version(
            matrix, records=tuple(new_records), generated_at=generated_at
        )
        set_state(
            "variable_coverage_matrix_versions",
            (get_state("variable_coverage_matrix_versions") or []) + [matrix.to_dict()],
        )
        set_state("variable_coverage_matrix", new_matrix.to_dict())
        st.success(
            f"Saved treatment decisions as matrix version {new_matrix.matrix_version}."
        )
_treatment_section.__exit__(None, None, None)

with st.expander("Coverage matrix version history"):
    history = get_state("variable_coverage_matrix_versions") or []
    if not history:
        st.caption("No saved coverage matrix versions yet.")
    for version in sorted(history, key=lambda m: int(m.get("matrix_version", 0))):
        v_matrix = VariableCoverageMatrix.from_dict(version)
        st.text(
            f"{v_matrix.matrix_id} v{v_matrix.matrix_version} - "
            f"{v_matrix.generated_at} - {len(v_matrix.records)} record(s) - "
            f"{len(v_matrix.blocking_issues)} blocking issue(s)"
        )

render_next_step("data_coverage")
