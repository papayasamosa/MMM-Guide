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
            "date": pd.date_range("2024-01-07", periods=n, freq="W-SUN"),
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
    assert any("Prepare Data" in (i.value or "") for i in at.info)


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


def test_adopted_standard_inputs_render_without_a_generic_join_empty_state():
    base = _base_df().rename(columns={"date": "period_start"})
    at = _run_at(
        date_col="period_start",
        market_col="market",
        standard_outcome_data=base[["period_start", "market", "fh_new_gsa"]],
        standard_activity_model_input=base[["period_start", "market", "tv_spend"]],
        standard_context_data=base[["period_start", "market"]],
    )
    assert not at.exception, f"adopted inputs raised: {at.exception}"
    assert any(
        "Build or refresh the coverage matrix" in (h.value or "") for h in at.markdown
    )
    assert any(
        "Reviewing adopted model inputs before official preparation" in (i.value or "")
        for i in at.info
    )
    assert not any("No prepared model inputs" in (i.value or "") for i in at.info)


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
        observed_start="2024-01-07",
        observed_end="2024-03-24",
        expected_start="2024-01-07",
        expected_end="2024-03-24",
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
    # Overnight UI/UX pass (2026-08-29, UX-010): the save handler now calls
    # st.rerun() after st.success() so the "Coverage summary" metrics above
    # (computed earlier in the script) reflect the save in the same view,
    # matching the already-fixed pattern elsewhere. The transient success
    # message from the pre-rerun pass is not retained across the rerun -
    # assert on the actually-persisted matrix state below instead.
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


def test_rebuild_without_a_matching_raw_source_still_preserves_prior_provenance():
    """Review finding (PR #156): with no raw source containing the column
    (so _default_source_id alone would fall back to "") and no recorded
    SourceVersion (so known_versions_by_source alone would fall back to 1),
    a rebuild must still default the metadata editor from the *existing*
    matrix's own recorded source_id/version - never silently reset to
    ""/1, which would make carry_forward_treatment_decisions' "same facts"
    match purely coincidental rather than a real confirmation."""
    df = _base_df()
    existing = _matrix_with_one_approved_record("coverage-test")
    existing = VariableCoverageMatrix.from_dict(
        {
            **existing.to_dict(),
            "records": [
                {
                    **existing.records[0].to_dict(),
                    "source_id": "governed_source",
                    "source_version": 3,
                }
            ],
        }
    )
    at = _run_at(
        transformed_data=df,
        date_col="date",
        market_col="market",
        raw_sources={},  # no raw source contains "tv_spend" at all
        variable_coverage_matrix=existing.to_dict(),
    )
    build_button = next(b for b in at.button if b.label == "Build coverage matrix")
    build_button.click().run()
    assert not at.exception, f"rebuild click raised: {at.exception}"

    matrix = VariableCoverageMatrix.from_dict(
        at.session_state["variable_coverage_matrix"]
    )
    tv_record = next(r for r in matrix.records if r.variable_id == "tv_spend")
    assert tv_record.source_id == "governed_source"
    assert tv_record.source_version == 3
    # Because the facts (including source) matched, the prior approval must
    # still be carried forward.
    assert tv_record.treatment_status == "approved"
    assert tv_record.approved_for_official_use is True


def test_no_staleness_warning_immediately_after_building():
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
    assert not any("may be stale" in (w.value or "") for w in at.warning)


def test_staleness_warning_shown_when_built_against_fingerprint_is_missing():
    """A matrix restored from an imported project bundle never carries the
    session-only variable_coverage_matrix_built_against_fingerprint key -
    that must read as "possibly stale", not silently "fine"."""
    matrix = _matrix_with_one_approved_record("coverage-test")
    at = _run_at(
        transformed_data=_base_df(),
        date_col="date",
        market_col="market",
        variable_coverage_matrix=matrix.to_dict(),
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any("may be stale" in (w.value or "") for w in at.warning)


def test_segment_classification_section_saves_and_bumps_version():
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
    assert any("Gap segment classification" in (h.value or "") for h in at.markdown)
    save_button = next(b for b in at.button if b.label == "Save gap classifications")
    save_button.click().run()
    assert not at.exception, f"save click raised: {at.exception}"
    # UX-010 (see test_save_treatment_decisions_bumps_the_matrix_version
    # above): same rerun-after-success trade-off - assert on persisted
    # state rather than the transient message.
    saved = VariableCoverageMatrix.from_dict(
        at.session_state["variable_coverage_matrix"]
    )
    assert saved.matrix_version == 2


def test_a_reclassified_segment_no_longer_blocks_official_use():
    """The mechanism the reviewer flagged as missing: once a segment is
    reclassified away from unknown/missing_expected, the record must stop
    appearing in blocking_issues - proven here against an already-
    reclassified record (AppTest cannot drive a live data_editor cell
    edit), which exercises the exact same round-trip the Save button uses
    for a live edit."""
    frequency = FrequencyMetadata(
        native_frequency="weekly",
        target_frequency="weekly",
        variable_class="flow_count",
    )
    reclassified_record = VariableCoverageRecord(
        variable_id="tv_spend",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=frequency,
        coverage_segments=(
            CoverageSegment(
                period_start="2024-01-01",
                period_end="2024-01-08",
                state="not_applicable",
            ),
        ),
    )
    matrix = VariableCoverageMatrix(
        matrix_id="coverage-test",
        matrix_version=1,
        generated_at="2026-01-01",
        records=(reclassified_record,),
    )
    at = _run_at(
        transformed_data=_base_df(),
        date_col="date",
        market_col="market",
        variable_coverage_matrix=matrix.to_dict(),
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert not any("unresolved coverage" in (w.value or "") for w in at.warning)

    save_button = next(b for b in at.button if b.label == "Save gap classifications")
    save_button.click().run()
    assert not at.exception, f"save click raised: {at.exception}"
    saved = VariableCoverageMatrix.from_dict(
        at.session_state["variable_coverage_matrix"]
    )
    tv_record = next(r for r in saved.records if r.variable_id == "tv_spend")
    assert tv_record.coverage_segments[0].state == "not_applicable"
    assert saved.blocking_issues == []
