"""AppTest coverage for pages/15_Data_Coverage.py (REQ-COVERAGE-001 Work
Package 3 Phase 3b-ii: the coverage-matrix review page). st.data_editor
cell edits can't be driven by AppTest (same limitation as st.file_uploader
elsewhere in this suite - see test_channel_media_units_search_objects_
apptest.py) - these tests exercise the page's real Build/Save button
handlers against the data_editor's default (unedited) content, which is
itself derived from real session state, not fabricated.
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


def test_page_shows_empty_state_without_joined_data():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Transform Pipeline" in (i.value or "") for i in at.info)


def test_page_renders_the_build_section_with_data_and_market_col():
    df = _base_df()
    at = _run_at(
        transformed_data=df,
        date_col="date",
        market_col="market",
        raw_sources={"media": df},
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "Build or refresh the coverage matrix" in (h.value or "") for h in at.markdown
    )


def test_build_button_creates_a_matrix_with_one_record_per_variable_and_market():
    df = _base_df()
    at = _run_at(
        transformed_data=df,
        date_col="date",
        market_col="market",
        raw_sources={"media": df},
    )
    build_button = next(b for b in at.button if b.label == "Build coverage matrix")
    build_button.click().run()
    assert not at.exception, f"build click raised: {at.exception}"

    matrix_dict = at.session_state["variable_coverage_matrix"]
    assert matrix_dict is not None
    matrix = VariableCoverageMatrix.from_dict(matrix_dict)
    assert matrix.matrix_version == 1
    variable_ids = {r.variable_id for r in matrix.records}
    assert variable_ids == {"tv_spend", "fh_new_gsa"}
    assert all(r.market == "UK" for r in matrix.records)
    assert all(r.source_id == "media" for r in matrix.records)


def _matrix_with_one_approved_record(matrix_id: str) -> VariableCoverageMatrix:
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
        proposed_treatment="use as-is",
        approved_treatment="use as-is",
        treatment_status="approved",
        treatment_approved_by="reviewer",
        treatment_approved_at="2026-01-01",
        approved_for_official_use=True,
    )
    return VariableCoverageMatrix(
        matrix_id=matrix_id,
        matrix_version=1,
        generated_at="2026-01-01",
        records=(record,),
    )


def test_rebuilding_carries_forward_an_approved_treatment_for_an_unchanged_variable():
    df = _base_df()
    matrix_id = "coverage-ancestry-fh-uk"
    existing = _matrix_with_one_approved_record(matrix_id)
    at = _run_at(
        transformed_data=df,
        date_col="date",
        market_col="market",
        raw_sources={"media": df},
        project_name="ancestry-fh-uk",
        variable_coverage_matrix=existing.to_dict(),
    )
    build_button = next(b for b in at.button if b.label == "Build coverage matrix")
    build_button.click().run()
    assert not at.exception, f"rebuild click raised: {at.exception}"

    matrix = VariableCoverageMatrix.from_dict(
        at.session_state["variable_coverage_matrix"]
    )
    assert matrix.matrix_version == 2
    tv_record = next(r for r in matrix.records if r.variable_id == "tv_spend")
    # tv_spend's frequency/source didn't change across the rebuild, so its
    # previously-approved treatment must survive - not silently reset.
    assert tv_record.treatment_status == "approved"
    assert tv_record.approved_for_official_use is True
    # A prior version must be preserved in history, not discarded.
    history = at.session_state["variable_coverage_matrix_versions"]
    assert any(v["matrix_version"] == 1 for v in history)


def test_save_treatment_decisions_bumps_the_matrix_version():
    matrix = _matrix_with_one_approved_record("coverage-test")
    at = _run_at(
        transformed_data=_base_df(),
        date_col="date",
        market_col="market",
        variable_coverage_matrix=matrix.to_dict(),
    )
    save_button = next(b for b in at.button if b.label == "Save treatment decisions")
    save_button.click().run()
    assert not at.exception, f"save click raised: {at.exception}"
    assert any(
        s.value.startswith("Saved treatment decisions as matrix version")
        for s in at.success
    )
    saved = VariableCoverageMatrix.from_dict(
        at.session_state["variable_coverage_matrix"]
    )
    assert saved.matrix_version == 2
    # The unedited data_editor content matches the existing approved record,
    # so the treatment decision itself is preserved across the save.
    tv_record = next(r for r in saved.records if r.variable_id == "tv_spend")
    assert tv_record.treatment_status == "approved"
    assert tv_record.approved_for_official_use is True


def test_unresolved_gap_shows_a_blocking_warning():
    frequency = FrequencyMetadata(
        native_frequency="weekly",
        target_frequency="weekly",
        variable_class="flow_count",
    )
    unresolved_record = VariableCoverageRecord(
        variable_id="tv_spend",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=frequency,
        coverage_segments=(
            CoverageSegment(
                period_start="2024-01-01", period_end="2024-01-08", state="unknown"
            ),
        ),
    )
    matrix = VariableCoverageMatrix(
        matrix_id="coverage-test",
        matrix_version=1,
        generated_at="2026-01-01",
        records=(unresolved_record,),
    )
    at = _run_at(
        transformed_data=_base_df(),
        date_col="date",
        market_col="market",
        variable_coverage_matrix=matrix.to_dict(),
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert len(at.warning) >= 1
    assert any("unresolved coverage" in (w.value or "") for w in at.warning)
