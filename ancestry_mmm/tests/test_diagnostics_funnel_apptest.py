"""AppTest coverage for the Diagnostics page's funnel-coherence diagnostics
section (PR E.2 requirement #7, required test case 10: "funnel-coherence
warnings")."""

from pathlib import Path

import numpy as np
import streamlit as st
from streamlit.testing.v1 import AppTest

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "06_Diagnostics.py"


def _frame_with_one_violation():
    n = 12
    upstream = np.full(n, 100.0)
    downstream = np.array([40, 42, 38, 41, 110, 39, 40, 41, 42, 38, 39, 40], dtype=float)
    return {
        "outcome_ids": ["fh_new_signup", "fh_new_gsa"],
        "Y": np.column_stack([upstream, downstream]),
        "dates": np.array([f"2024-01-{i + 1:02d}" for i in range(n)], dtype="datetime64[D]"),
        "df": None,
    }


def _minimal_meta(outcome_ids):
    from types import SimpleNamespace
    return SimpleNamespace(outcome_ids=outcome_ids, direct_dna_outcome_ids=[], outcome_catalogue_at_fit=[])


def test_no_funnel_links_shows_info_not_a_crash():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    frame = _frame_with_one_violation()
    at.session_state["trace"] = object()
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = _minimal_meta(frame["outcome_ids"])
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("No funnel links configured" in (i.value or "") for i in at.info)


def test_funnel_link_with_a_violation_shows_warning_icon_and_metrics():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    frame = _frame_with_one_violation()
    at.session_state["trace"] = object()
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = _minimal_meta(frame["outcome_ids"])
    at.session_state["funnel_links"] = [
        {"upstream_outcome_id": "fh_new_signup", "downstream_outcome_id": "fh_new_gsa"},
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    warning_markdown = [m.value for m in at.markdown if "fh_new_signup -> fh_new_gsa" in (m.value or "")]
    assert warning_markdown, "funnel link heading not rendered"
    assert "⚠️" in warning_markdown[0]

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Coherence violations"] == "1 / 12"
    assert metrics["Out-of-range periods"] == "1"


def test_funnel_link_referencing_unknown_outcome_id_warns_without_crashing():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    frame = _frame_with_one_violation()
    at.session_state["trace"] = object()
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = _minimal_meta(frame["outcome_ids"])
    at.session_state["funnel_links"] = [
        {"upstream_outcome_id": "fh_new_signup", "downstream_outcome_id": "does_not_exist"},
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("references an outcome_id not in this fit" in (w.value or "") for w in at.warning)
