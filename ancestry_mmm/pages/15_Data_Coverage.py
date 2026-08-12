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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    get_state,
    init_session_state,
    readable_label,
    set_state,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
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
from ancestry_mmm.data import detect_column_types

FREQUENCY_OPTIONS = ["daily", "weekly", "monthly", "quarterly", "irregular"]

st.set_page_config(
    page_title="Data Coverage | Ancestry Family History & DNA MMM",
    page_icon="🧬",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("data_coverage")

df = get_state("transformed_data")
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
        "Review each governed variable's coverage and missingness by "
        "market, then propose and approve a treatment before this data is "
        "eligible for official use."
    ),
    badges=_header_badges,
)

if not _data_ready:
    st.markdown("---")
    render_empty_state(
        "No joined data with a market column yet. Complete Transform "
        "Pipeline first - the coverage matrix is built per market, so a "
        "market column is required.",
        button_label="Go to Transform Pipeline",
        target_key="transform_pipeline",
        what_for=(
            "Reviewing each governed variable's coverage and missingness "
            "by market before defining model structure (REQ-COVERAGE-001)."
        ),
        dependency="A joined dataset with a market column (Transform Pipeline).",
        next_action="Go to Transform Pipeline to join your sources and select a market column.",
    )
    st.stop()

st.markdown("---")
st.caption(
    "REQ-COVERAGE-001: every candidate model must expose a variable "
    "coverage matrix before fitting. This page builds that matrix from the "
    "joined data and lets you review, and propose/approve treatments for, "
    "each variable's coverage before model preparation. It never classifies "
    "*why* a gap exists for you - every gap starts as 'unknown' until you "
    "reclassify it; a state is never inferred merely because a value is "
    "absent."
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


st.markdown("### 1. Build or refresh the coverage matrix")
variable_columns = st.multiselect(
    "Governed variables",
    all_columns,
    default=numeric_cols,
    format_func=readable_label,
    help="Columns to include in the coverage matrix - typically media, "
    "outcome and control columns, never the date/market columns "
    "themselves.",
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
    st.markdown("#### Per-variable frequency, class and source")
    st.caption(
        "REQ-COVERAGE-001 S4: variable class gates which frequency-"
        "conversion methods are eligible - never one default applied "
        "across classes. Source ID/version identify which governed upload "
        "(Data Upload page) this variable's values came from."
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
                "source_id": default_source_id,
                "source_version": default_source_version,
            }
        )
    metadata_editor = st.data_editor(
        pd.DataFrame(metadata_rows),
        width="stretch",
        hide_index=True,
        key="coverage_variable_metadata_editor",
        column_config={
            "variable": st.column_config.TextColumn("Variable", disabled=True),
            "native_frequency": st.column_config.SelectboxColumn(
                "Native frequency", options=FREQUENCY_OPTIONS, required=True
            ),
            "target_frequency": st.column_config.SelectboxColumn(
                "Target frequency", options=FREQUENCY_OPTIONS, required=True
            ),
            "variable_class": st.column_config.SelectboxColumn(
                "Variable class", options=sorted(VARIABLE_CLASSES), required=True
            ),
            "source_id": st.column_config.TextColumn("Source ID", required=True),
            "source_version": st.column_config.NumberColumn(
                "Source version", min_value=1, step=1, required=True
            ),
        },
    )

    if st.button("Build coverage matrix", type="primary"):
        try:
            frequency_metadata = {
                str(row["variable"]): FrequencyMetadata(
                    native_frequency=str(row["native_frequency"]),
                    target_frequency=str(row["target_frequency"]),
                    variable_class=str(row["variable_class"]),
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

current_matrix_dict = get_state("variable_coverage_matrix")
if current_matrix_dict is None:
    st.info("Build a coverage matrix above to review it.")
    render_next_step("data_coverage")
    st.stop()

matrix = VariableCoverageMatrix.from_dict(current_matrix_dict)

st.markdown("---")
st.markdown("### 2. Coverage fabric")
st.caption(
    "A time x variable x market visual surface built from the coverage "
    "matrix above (REQ-COVERAGE-001 S2's canonical missingness-state "
    "vocabulary). Selecting or filtering here never changes governance "
    "state - state classification and treatment approval remain the "
    "explicit controls in section 4 below."
)

_fabric_cells = build_fabric_cells(matrix)
_fabric_summary = fabric_summary_sentences(matrix)
if _fabric_summary:
    with InfoPanel("Coverage summary"):
        st.markdown("\n".join(f"- {s}" for s in _fabric_summary))

if not _fabric_cells:
    st.caption(
        "No coverage-fabric cells to render yet - every governed variable's "
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
        "unresolved (unknown/missing_expected), unavailable_source, or "
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
            ic2.metric("Source", f"{_r.source_id} v{_r.source_version}")
            ic2.metric(
                "Observed window",
                f"{_r.observed_start or 'n/a'} to {_r.observed_end or 'n/a'}",
            )
            ic3.metric("Treatment status", _r.treatment_status)
            ic3.metric(
                "Approved for official use",
                "Yes" if _r.approved_for_official_use else "No",
            )
            if _r.approved_treatment:
                st.caption(f"Approved treatment: {_r.approved_treatment}")
    else:
        st.caption(
            "Click or box-select a segment above to inspect its full detail here."
        )

st.markdown("---")
st.markdown("### 3. Review coverage")
st.caption(
    f"Matrix `{matrix.matrix_id}` v{matrix.matrix_version} - generated "
    f"{matrix.generated_at} - {len(matrix.records)} record(s)."
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
        "This matrix may be stale: the joined data has changed (or this "
        "matrix was restored from an imported project) since it was last "
        "built. Rebuild above to confirm the coverage below still matches "
        "the current data."
    )

blocking_issues = matrix.blocking_issues
if blocking_issues:
    st.warning(
        "The following variables have unresolved coverage not yet "
        "approved for official use (REQ-COVERAGE-001 S5):"
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
        "observed_start": record.observed_start or "",
        "observed_end": record.observed_end or "",
        "expected_start": record.expected_start or "",
        "expected_end": record.expected_end or "",
        "gap_segments": len(record.coverage_segments),
        "gap_states": ", ".join(sorted({s.state for s in record.coverage_segments})),
        "officially_unresolved": record.is_officially_unresolved,
    }
    for record in matrix.records
]
st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)

st.markdown("#### Gap segment classification")
st.caption(
    "A gap is never inferred as anything beyond 'unknown' (REQ-COVERAGE-001 "
    "S1/S2) - reclassify each one here to the state that actually applies "
    "(missing_expected, not_applicable, unavailable_source, suppressed, "
    "estimated, modelled, or a genuine structural observed_zero) before "
    "approving a treatment for it below. A structural-zero segment requires "
    "state='observed_zero' and a non-empty justification - pre-launch may "
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
    segment_editor = st.data_editor(
        pd.DataFrame(segment_rows),
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
                "State", options=sorted(COVERAGE_STATES), required=True
            ),
        },
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
        "Unresolved unknown/missing_expected coverage never becomes official "
        "fit input silently (REQ-COVERAGE-001 S5) - a variable stays "
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
treatment_editor = st.data_editor(
    pd.DataFrame(treatment_rows),
    width="stretch",
    hide_index=True,
    disabled=["variable", "market", "product", "segment"],
    key="coverage_treatment_editor",
    column_config={
        "treatment_status": st.column_config.SelectboxColumn(
            "Status", options=sorted(TREATMENT_STATUSES), required=True
        ),
        "treatment_approved_at": st.column_config.TextColumn(
            "Approved on (YYYY-MM-DD)"
        ),
    },
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
