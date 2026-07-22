"""AppTest coverage for the Brand Search treatment mode section on the
Model Configuration page (PR G1 - core.brand_search)."""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.outcomes import FAMILY_HISTORY, METRIC_GSA, OutcomeDefinition
from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "04_Model_Config.py"


def _base_state():
    n = 12
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="W"),
        "market": ["UK"] * n,
        "New": np.arange(n, dtype=float) + 10,
        "tv_spend": np.arange(n, dtype=float) * 100 + 500,
        "brand_search_spend": np.arange(n, dtype=float) * 20 + 50,
    })
    spec = ModelSpec(
        date_col="date", market_col="market", markets=["UK"],
        channels=["tv_spend", "brand_search_spend"], segment_outcomes={"New": "New"},
    )
    outcome_defs = [
        OutcomeDefinition(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA, source_column="New").to_dict(),
    ]
    return df, spec, outcome_defs


def test_page_renders_with_no_brand_search_config_configured():
    df, spec, outcome_defs = _base_state()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = df
    at.session_state["model_spec"] = spec.to_dict()
    at.session_state["outcome_definitions"] = outcome_defs
    at.run()
    assert not at.exception, f"page raised: {at.exception}"


def test_valid_direct_channel_config_shows_no_errors():
    df, spec, outcome_defs = _base_state()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = df
    at.session_state["model_spec"] = spec.to_dict()
    at.session_state["outcome_definitions"] = outcome_defs
    at.session_state["brand_search_configs"] = [
        {"channel": "brand_search_spend", "mode": "direct_channel", "mediator_of": [], "mediation_share": None, "calibration_factor": None, "notes": ""},
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert len(at.error) == 0


def test_demand_capture_mediator_missing_mediation_share_shows_error():
    df, spec, outcome_defs = _base_state()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = df
    at.session_state["model_spec"] = spec.to_dict()
    at.session_state["outcome_definitions"] = outcome_defs
    at.session_state["brand_search_configs"] = [
        {
            "channel": "brand_search_spend", "mode": "demand_capture_mediator",
            "mediator_of": ["tv_spend"], "mediation_share": None, "calibration_factor": None, "notes": "",
        },
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("mediation_share" in e.value for e in at.error)
