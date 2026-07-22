"""AppTest coverage for drift status on the Model Configuration page (PR E.2
requirement #10 - "make drift status first-class in the UI" - Model
Configuration is one of the seven pages required to consume it).

Uses `AppTest.from_file` (loads the full page script) rather than
`AppTest.from_function` - a fresh, isolated single-function script has
shown flaky pandas/pyarrow-in-a-thread crashes when it's the very first
DataFrame construction in that process (see test_drift_status_component.py's
docstring); a full page always constructs several DataFrames before
reaching the drift panel, which does not reproduce that issue."""

from pathlib import Path
from types import SimpleNamespace

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
    })
    spec = ModelSpec(date_col="date", market_col="market", markets=["UK"], channels=["tv_spend"], segment_outcomes={"New": "New"})
    outcome_defs = [
        OutcomeDefinition(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA, source_column="New").to_dict(),
    ]
    return df, spec, outcome_defs


def test_no_model_meta_shows_no_drift_warning():
    df, spec, outcome_defs = _base_state()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = df
    at.session_state["model_spec"] = spec.to_dict()
    at.session_state["outcome_definitions"] = outcome_defs
    at.run()
    assert not at.exception
    assert len(at.warning) == 0


def test_changed_catalogue_shows_drift_warning_with_exact_field():
    df, spec, outcome_defs = _base_state()
    fit_time_outcome = OutcomeDefinition(
        outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA, source_column="New", unit="count",
    )
    meta = SimpleNamespace(outcome_catalogue_at_fit=[fit_time_outcome])

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = df
    at.session_state["model_spec"] = spec.to_dict()
    at.session_state["outcome_definitions"] = outcome_defs
    at.session_state["model_meta"] = meta
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    assert len(at.warning) == 1
    assert "fh_new" in at.warning[0].value
    assert "Changed since fit" in at.warning[0].value
