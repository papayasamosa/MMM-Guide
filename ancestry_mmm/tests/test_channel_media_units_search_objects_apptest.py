"""AppTest coverage for the "governed Search objects" section on
pages/10_Channel_Media_Units.py (REQ-SEARCH-001 work package: Search object
governance)."""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

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
            "paid_search_gbp_spend": np.arange(n, dtype=float) * 20 + 50,
        }
    )
    spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        channels=["tv_spend", "paid_search_gbp_spend"],
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


def test_page_renders_with_no_search_objects_configured():
    df, spec = _base_state()
    at = _run_at(df, spec)
    assert not at.exception, f"page raised: {at.exception}"
    assert any("governed Search objects" in (h.value or "") for h in at.markdown)


def test_existing_search_object_loads_without_error():
    df, spec = _base_state()
    at = _run_at(
        df,
        spec,
        search_objects=[
            {
                "search_object_id": "uk_paid_search_spend",
                "search_role": "paid_search_spend",
                "source_column": "paid_search_gbp_spend",
                "unit": "monetary",
                "currency": "GBP",
                "market": "UK",
                "planning_eligibility": "optimisable",
            }
        ],
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert len(at.error) == 0


def test_save_button_persists_valid_search_object_rows():
    df, spec = _base_state()
    at = _run_at(
        df,
        spec,
        search_objects=[
            {
                "search_object_id": "uk_paid_search_spend",
                "search_role": "paid_search_spend",
                "source_column": "paid_search_gbp_spend",
                "unit": "monetary",
                "currency": "GBP",
                "market": "UK",
                "planning_eligibility": "optimisable",
            }
        ],
    )
    assert not at.exception

    save_button = next(
        b for b in at.button if b.label == "Save Search object governance"
    )
    save_button.click().run()
    assert not at.exception, f"save click raised: {at.exception}"
    assert any(s.value == "Search object governance saved." for s in at.success)
    saved = at.session_state["search_objects"]
    assert len(saved) == 1
    assert saved[0]["search_object_id"] == "uk_paid_search_spend"


def test_incompatible_column_alias_blocks_save():
    """REQ-SEARCH-001 S14: a click column already governed as
    paid_search_delivery cannot also be registered as paid_search_cap - the
    real Save button must refuse to persist either row."""
    df, spec = _base_state()
    at = _run_at(
        df,
        spec,
        search_objects=[
            {
                "search_object_id": "uk_paid_search_delivery",
                "search_role": "paid_search_delivery",
                "source_column": "paid_search_clicks",
                "unit": "exposure_count",
                "market": "UK",
            },
            {
                "search_object_id": "uk_paid_search_cap",
                "search_role": "paid_search_cap",
                "source_column": "paid_search_clicks",
                "unit": "exposure_count",
                "market": "UK",
            },
        ],
    )
    assert not at.exception
    assert any("claimed by conflicting search roles" in e.value for e in at.error)

    save_button = next(
        b for b in at.button if b.label == "Save Search object governance"
    )
    save_button.click().run()
    assert not at.exception, f"save click raised: {at.exception}"
    assert any("Nothing was saved" in (s.value or "") for s in at.error)
