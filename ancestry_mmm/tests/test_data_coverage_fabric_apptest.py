"""AppTest coverage for pages/15_Data_Coverage.py's Phase 3 UI overhaul
addition: the coverage-fabric section (REQ-COVERAGE-001). AppTest cannot
drive a live Plotly `on_select` click event (no programmatic simulation API,
same class of limitation the suite already documents for
`st.data_editor`/`st.file_uploader`) - these tests exercise the fabric
section's real data-derived content (summary sentences, state filter,
inspector fallback caption) rather than click interaction itself, which is
covered by Playwright per the CI wait discipline / testing plan.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.coverage import (
    CoverageSegment,
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "15_Data_Coverage.py"


def _base_df() -> pd.DataFrame:
    n = 12
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="W-MON"),
            "market": ["UK"] * n,
            "tv_spend": np.arange(n, dtype=float) * 100 + 500,
            "fh_new_gsa": np.arange(n, dtype=float) + 10,
        }
    )


def _run_at(**extra_state):
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    for key, value in extra_state.items():
        at.session_state[key] = value
    at.run()
    return at


def _matrix_with_gap() -> VariableCoverageMatrix:
    frequency = FrequencyMetadata(
        native_frequency="weekly",
        target_frequency="weekly",
        variable_class="flow_count",
    )
    record = VariableCoverageRecord(
        variable_id="tv_spend",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=frequency,
        coverage_segments=(
            CoverageSegment(
                period_start="2024-01-08", period_end="2024-01-15", state="unknown"
            ),
        ),
        observed_start="2024-01-22",
        observed_end="2024-03-18",
        expected_start="2024-01-01",
        expected_end="2024-03-18",
    )
    return VariableCoverageMatrix(
        matrix_id="coverage-test",
        matrix_version=1,
        generated_at="2026-01-01",
        records=(record,),
    )


def test_fabric_section_renders_with_a_built_matrix():
    df = _base_df()
    matrix = _matrix_with_gap()
    at = _run_at(
        transformed_data=df,
        date_col="date",
        market_col="market",
        variable_coverage_matrix=matrix.to_dict(),
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Coverage fabric" in (m.value or "") for m in at.markdown)
    assert any("Isolate state(s)" == ms.label for ms in at.multiselect)
    visible_help = "\n".join(
        (element.help or "") for element in at.multiselect if hasattr(element, "help")
    )
    assert "missing_expected" not in visible_help
    assert "unavailable_source" not in visible_help
    summary_tables = [
        table.value
        for table in at.dataframe
        if "gap_states" in getattr(table.value, "columns", [])
    ]
    assert summary_tables and "Unknown" in summary_tables[0]["gap_states"].tolist()


def test_summary_sentences_render_and_mention_the_actual_market():
    df = _base_df()
    matrix = _matrix_with_gap()
    at = _run_at(
        transformed_data=df,
        date_col="date",
        market_col="market",
        variable_coverage_matrix=matrix.to_dict(),
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Coverage summary" in (m.value or "") for m in at.markdown)
    assert any("UK" in (m.value or "") for m in at.markdown)


def test_no_selection_shows_the_inspector_fallback_caption():
    df = _base_df()
    matrix = _matrix_with_gap()
    at = _run_at(
        transformed_data=df,
        date_col="date",
        market_col="market",
        variable_coverage_matrix=matrix.to_dict(),
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "Click or box-select a segment above to inspect" in (c.value or "")
        for c in at.caption
    )


def test_review_coverage_section_is_renumbered_after_the_fabric():
    df = _base_df()
    matrix = _matrix_with_gap()
    at = _run_at(
        transformed_data=df,
        date_col="date",
        market_col="market",
        variable_coverage_matrix=matrix.to_dict(),
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any("3. Review coverage" in (m.value or "") for m in at.markdown)
    assert any(
        "4. Propose and approve treatments" in (m.value or "") for m in at.markdown
    )


def test_fully_covered_matrix_still_renders_the_fabric_section():
    df = _base_df()
    frequency = FrequencyMetadata(
        native_frequency="weekly",
        target_frequency="weekly",
        variable_class="flow_count",
    )
    record = VariableCoverageRecord(
        variable_id="tv_spend",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=frequency,
        coverage_segments=(),
        observed_start="2024-01-01",
        observed_end="2024-03-18",
        expected_start="2024-01-01",
        expected_end="2024-03-18",
    )
    matrix = VariableCoverageMatrix(
        matrix_id="coverage-test",
        matrix_version=1,
        generated_at="2026-01-01",
        records=(record,),
    )
    at = _run_at(
        transformed_data=df,
        date_col="date",
        market_col="market",
        variable_coverage_matrix=matrix.to_dict(),
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "all 1 governed variable record(s) cover the full expected window"
        in (m.value or "")
        for m in at.markdown
    )
