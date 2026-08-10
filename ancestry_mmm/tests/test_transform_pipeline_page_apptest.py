"""AppTest coverage for pages/02_Transform_Pipeline.py's join step
(REQ-COVERAGE-001 S4 Work Package 4: explicit join mode + join-loss
diagnostics, replacing the previous silent how="inner" default).
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


def _mismatched_sources():
    # media covers weeks 1-4, outcomes only weeks 2-5 - an inner join drops
    # media's week 1 and outcomes' week 5.
    media = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=4, freq="W"), "TV": [1, 2, 3, 4]}
    )
    outcomes = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-08", periods=4, freq="W"),
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


def test_join_mode_selectbox_defaults_to_inner():
    at = _run_at(raw_sources=_matching_sources())
    assert not at.exception, f"page raised: {at.exception}"
    join_mode_sb = next(sb for sb in at.selectbox if sb.label == "Join mode *")
    assert join_mode_sb.value == "inner"


def test_inner_join_on_matching_dates_shows_no_loss_warning():
    at = _run_at(raw_sources=_matching_sources())
    join_button = next(b for b in at.button if b.label == "Join sources")
    join_button.click().run()
    assert not at.exception, f"join click raised: {at.exception}"

    diagnostics = at.session_state["join_diagnostics"]
    assert diagnostics["join_mode"] == "inner"
    assert diagnostics["output_rows"] == 4
    assert all(s["dropped_keys"] == 0 for s in diagnostics["per_source"])
    assert not any("dropped rows" in (w.value or "") for w in at.warning)


def test_inner_join_on_mismatched_dates_shows_a_loss_warning():
    at = _run_at(raw_sources=_mismatched_sources())
    join_button = next(b for b in at.button if b.label == "Join sources")
    join_button.click().run()
    assert not at.exception, f"join click raised: {at.exception}"

    diagnostics = at.session_state["join_diagnostics"]
    assert diagnostics["join_mode"] == "inner"
    assert diagnostics["output_rows"] == 3
    dropped = {s["source_name"]: s["dropped_keys"] for s in diagnostics["per_source"]}
    assert dropped == {"media": 1, "outcomes": 1}
    assert any("dropped rows" in (w.value or "") for w in at.warning)
    assert len(at.dataframe) >= 1


def test_switching_to_outer_join_preserves_every_row_and_reports_no_loss():
    at = _run_at(raw_sources=_mismatched_sources())
    join_mode_sb = next(sb for sb in at.selectbox if sb.label == "Join mode *")
    join_mode_sb.select("outer").run()
    assert not at.exception, f"selecting outer raised: {at.exception}"

    join_button = next(b for b in at.button if b.label == "Join sources")
    join_button.click().run()
    assert not at.exception, f"join click raised: {at.exception}"

    diagnostics = at.session_state["join_diagnostics"]
    assert diagnostics["join_mode"] == "outer"
    assert diagnostics["output_rows"] == 5
    assert all(s["dropped_keys"] == 0 for s in diagnostics["per_source"])
    assert not any("dropped rows" in (w.value or "") for w in at.warning)

    joined = at.session_state["joined_data"]
    assert len(joined) == 5
