"""AppTest coverage for the net bill-through offer rule editor on the
Structure page (PR G1 - core.net_billthrough)."""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "03_Structure_Segments_Markets.py"


def _transformed_data() -> pd.DataFrame:
    n = 20
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="W"),
        "market": ["UK"] * n,
        "New": rng.poisson(50, n).astype(float),
        "tv_spend": rng.uniform(1000, 5000, n),
    })


def test_page_renders_with_no_offer_rules_configured():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = _transformed_data()
    at.session_state["date_col"] = "date"
    at.session_state["market_col"] = "market"
    at.run()
    assert not at.exception, f"page raised: {at.exception}"


def test_page_renders_with_an_offer_rule_already_configured():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = _transformed_data()
    at.session_state["date_col"] = "date"
    at.session_state["market_col"] = "market"
    at.session_state["net_billthrough_offer_rules"] = [
        {"offer_id": "trial-30", "market": "UK", "maturity_days": 30, "description": "Free trial"},
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
