"""AppTest coverage for pages/02_Transform_Pipeline.py's Phase 3 UI overhaul
changes: the readiness badge, the "Join setup" / "Join health" panel split, and the transformation-
step list. Complements the pre-existing join-diagnostics assertions in
test_transform_pipeline_page_apptest.py, which this file does not duplicate
and whose exact warning/success text this file leaves untouched.
"""

from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "02_Transform_Pipeline.py"


def _matching_sources():
    media = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=4, freq="W"), "TV": [1, 2, 3, 4]}
    )
    outcomes = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="W"),
            "GSAs": [5, 6, 7, 8],
        }
    )
    return {"media": media, "outcomes": outcomes}


def _run_at(**extra_state):
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    for key, value in extra_state.items():
        at.session_state[key] = value
    at.run()
    return at


def test_no_sources_shows_awaiting_data_badge():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Awaiting data" in (m.value or "") for m in at.markdown)


def test_sources_loaded_but_not_joined_shows_source_alignment_section():
    at = _run_at(raw_sources=_matching_sources())
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Join setup" in (m.value or "") for m in at.markdown)


def test_after_join_shows_diagnostics_panel_as_a_distinct_section():
    at = _run_at(raw_sources=_matching_sources())
    join_button = next(b for b in at.button if b.label == "Join sources")
    join_button.click().run()
    assert not at.exception, f"join click raised: {at.exception}"
    assert any("Join health" in (m.value or "") for m in at.markdown)


def test_joined_but_not_yet_transformed_shows_in_progress_badge():
    """Direct state seeding (joined_data set, transformed_data explicitly
    absent) rather than a live click flow: with zero pipeline steps,
    apply_pipeline always succeeds and sets transformed_data within the same
    script run as the join itself, so this intermediate state is not
    observable through a live click - it is a real, reachable state though
    (e.g. a project bundle that restored joined_data but not
    transformed_data), so it's tested by seeding it directly."""
    at = _run_at(
        raw_sources=_matching_sources(),
        joined_data=pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=4, freq="W"),
                "TV": [1, 2, 3, 4],
            }
        ),
        date_col="date",
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any("In progress" in (m.value or "") for m in at.markdown)


def test_ordered_transformation_steps_render_as_a_numbered_list():
    at = _run_at(
        raw_sources=_matching_sources(),
        joined_data=pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=4, freq="W"),
                "TV": [1, 2, 3, 4],
                "GSAs": [5, 6, 7, 8],
            }
        ),
        pipeline_steps=[
            {
                "op": "rename_column",
                "params": {"old": "TV", "new": "tv_spend"},
                "description": "Rename TV -> tv_spend",
            }
        ],
        date_col="date",
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Transformation sequence" in (m.value or "") for m in at.markdown)
    assert any("**1.**" in (m.value or "") for m in at.markdown)


def test_transformed_preview_and_save_replay_panel_render():
    at = _run_at(
        raw_sources=_matching_sources(),
        joined_data=pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=4, freq="W"),
                "TV": [1, 2, 3, 4],
                "GSAs": [5, 6, 7, 8],
            }
        ),
        pipeline_steps=[],
        date_col="date",
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Output preview" in (m.value or "") for m in at.markdown)
    assert any("Save and replay" in (m.value or "") for m in at.markdown)

    # A second run now sees transformed_data populated from the first run,
    # which flips the header badge to "ready".
    at.run()
    assert not at.exception, f"second run raised: {at.exception}"
    assert any("Ready" in (m.value or "") for m in at.markdown)
