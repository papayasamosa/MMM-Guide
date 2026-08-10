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
)
from ancestry_mmm.core.coverage import (
    TREATMENT_STATUSES,
    VARIABLE_CLASSES,
    FrequencyMetadata,
    VariableCoverageMatrix,
    build_coverage_matrix_from_frame,
    carry_forward_treatment_decisions,
    current_source_versions,
    new_variable_coverage_matrix_version,
)
from ancestry_mmm.data import detect_column_types

FREQUENCY_OPTIONS = ["daily", "weekly", "monthly", "quarterly", "irregular"]

st.set_page_config(
    page_title="Data Coverage - Ancestry FH MMM", page_icon="🧬", layout="wide"
)
init_session_state()
apply_theme()
render_sidebar("data_coverage")
render_page_header("data_coverage")

df = get_state("transformed_data")
date_col = get_state("date_col")
market_col = get_state("market_col")
if df is None or not date_col or not market_col:
    st.markdown("---")
    render_empty_state(
        "No joined data with a market column yet. Complete Transform "
        "Pipeline first - the coverage matrix is built per market, so a "
        "market column is required.",
        button_label="Go to Transform Pipeline",
        target_key="transform_pipeline",
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


def _default_source_id(column: str) -> str:
    for name, source_df in raw_sources.items():
        if column in source_df.columns:
            return name
    return ""


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
        default_source = _default_source_id(column)
        metadata_rows.append(
            {
                "variable": column,
                "native_frequency": "weekly",
                "target_frequency": "weekly",
                "variable_class": "flow_count",
                "source_id": default_source,
                "source_version": known_versions_by_source.get(default_source, 1),
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
            existing_dict = get_state("variable_coverage_matrix")
            existing = (
                VariableCoverageMatrix.from_dict(existing_dict)
                if existing_dict
                else None
            )
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
st.markdown("### 2. Review coverage")
st.caption(
    f"Matrix `{matrix.matrix_id}` v{matrix.matrix_version} - generated "
    f"{matrix.generated_at} - {len(matrix.records)} record(s)."
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

with st.expander("Gap segment detail"):
    any_segments = False
    for record in matrix.records:
        if not record.coverage_segments:
            continue
        any_segments = True
        label = record.variable_id + f" ({record.market}"
        if record.product:
            label += f" / {record.product}"
        if record.segment:
            label += f" / {record.segment}"
        label += ")"
        st.markdown(f"**{label}**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "period_start": s.period_start,
                        "period_end": s.period_end,
                        "state": s.state,
                        "structural_zero": s.structural_zero,
                    }
                    for s in record.coverage_segments
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    if not any_segments:
        st.caption("Every variable is fully covered - no gap segments.")

st.markdown("---")
st.markdown("### 3. Propose and approve treatments")
st.caption(
    "Unresolved unknown/missing_expected coverage never becomes official "
    "fit input silently (REQ-COVERAGE-001 S5) - a variable stays "
    "exploratory until you approve a treatment for it here. "
    "'Approved for official use' requires an approved treatment, an "
    "approver and an approval date."
)
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
