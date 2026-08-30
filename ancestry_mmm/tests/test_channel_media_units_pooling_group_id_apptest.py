"""AppTest coverage for REQ-DATAIN-001's pooling_group_id survival through
pages/10_Channel_Media_Units.py's "Save activity mapping" flow.

Regression for a PR #167 review finding: pooling_group_id must survive the
activity mapping save flow - an unrelated edit must not silently reset the
stable cross-market identity. The Phase 2 workspace now uses a compact
overview plus a selected-activity detail form rather than a giant governance
grid.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "10_Channel_Media_Units.py"


def _base_state():
    n = 12
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="W"),
            "market": ["UK"] * n,
            "New": np.arange(n, dtype=float) + 10,
            "tv_spend": np.arange(n, dtype=float) * 100 + 500,
        }
    )
    spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        channels=["tv_spend"],
        segment_outcomes={"New": "New"},
    )
    return df, spec


def _run_at(df, spec, **extra_state):
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = df
    at.session_state["model_spec"] = spec.to_dict()
    for key, value in extra_state.items():
        at.session_state[key] = value
    at.run()
    return at


def test_save_preserves_pooling_group_id_through_an_unrelated_edit():
    df, spec = _base_state()
    existing = ActivityDefinition(
        activity_id="UK:tv_spend",
        market="UK",
        channel="tv_spend",
        model_input_column="tv_spend",
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        pooling_group_id="tv-brand-uk-au",
        marketing_objective="brand awareness",
        funnel_stage="brand_upper",
        source="activity governance UI",
    )
    at = _run_at(df, spec, activity_definitions=[existing.to_dict()])
    assert not at.exception, f"page raised: {at.exception}"

    save_button = next(b for b in at.button if b.label == "Save activity mapping")
    save_button.click().run()
    assert not at.exception, f"save click raised: {at.exception}"

    saved = at.session_state["activity_definitions"]
    assert len(saved) == 1
    assert saved[0]["pooling_group_id"] == "tv-brand-uk-au"
    assert saved[0]["marketing_objective"] == "brand awareness"
    assert saved[0]["funnel_stage"] == "brand_upper"

    # Codex review (PR #348, P2): the save handler persists its confirmation
    # via `activity_mapping_notice` rather than calling st.success() directly,
    # specifically so it survives the st.rerun() the save triggers (UX-009)
    # instead of being discarded before ever being shown - AppTest processes
    # that rerun within this single `.click().run()` call, so a message lost
    # to the rerun would simply never appear in `at.success` here.
    assert any("Activity mapping saved." in (s.value or "") for s in at.success), (
        "the save confirmation must survive the st.rerun() this save triggers"
    )
    # Shown once: an unrelated later rerun must not keep re-showing it.
    at.run()
    assert not any("Activity mapping saved." in (s.value or "") for s in at.success), (
        "the notice must not persist across later, unrelated reruns"
    )


def test_save_does_not_fabricate_pooling_group_id_for_a_new_row():
    df, spec = _base_state()
    at = _run_at(df, spec)
    assert not at.exception, f"page raised: {at.exception}"

    save_button = next(b for b in at.button if b.label == "Save activity mapping")
    save_button.click().run()
    assert not at.exception, f"save click raised: {at.exception}"

    saved = at.session_state["activity_definitions"]
    assert len(saved) == 1
    assert saved[0]["pooling_group_id"] is None


def test_activity_mapping_is_reachable_before_model_structure():
    df, _ = _base_state()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = df
    at.session_state["date_col"] = "date"
    at.session_state["market_col"] = "market"
    at.run()

    assert not at.exception, f"pre-structure mapping page raised: {at.exception}"
    assert any(item.label == "Save activity mapping" for item in at.button)
    assert any("No governed activities exist yet" in item.value for item in at.info)


def test_activity_mapping_uses_compact_overview_and_detail_form():
    df, spec = _base_state()
    existing = ActivityDefinition(
        activity_id="UK:tv_spend",
        market="UK",
        channel="TV",
        model_input_column="tv_spend",
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        source="activity governance UI",
        funnel_stage="brand_upper",
    )
    at = _run_at(df, spec, activity_definitions=[existing.to_dict()])

    assert not at.exception, f"compact activity mapping raised: {at.exception}"
    assert any("Activity mapping" in (m.value or "") for m in at.markdown)
    assert any("Selected activity" == select.label for select in at.selectbox)
    assert any(
        "Technical and provenance" in (expander.label or "") for expander in at.expander
    )
    assert any(
        set(table.value.columns)
        == {
            "Market",
            "Reporting channel",
            "Delivery measure",
            "Unit",
            "Cost basis",
            "Currency",
            "Mapping status",
        }
        for table in at.dataframe
    )
