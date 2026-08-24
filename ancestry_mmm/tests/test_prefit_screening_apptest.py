"""AppTest coverage for the deterministic pre-fit screen entry point."""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_GSA,
    OutcomeDefinition,
)
from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "04_Model_Config.py"


def _run_at():
    n_obs = 12
    dates = pd.date_range("2024-01-07", periods=n_obs, freq="7D")
    media = np.arange(n_obs, dtype=float)[:, None] + 1
    data = pd.DataFrame(
        {
            "date": dates,
            "market": ["UK"] * n_obs,
            "New": np.arange(n_obs, dtype=float) + 10,
            "tv_grps": media[:, 0],
        }
    )
    spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        channels=["tv_grps"],
        segment_outcomes={"New": "New"},
    )
    outcome_defs = [
        OutcomeDefinition(
            outcome_id="fh_new",
            product=FAMILY_HISTORY,
            segment="New",
            metric=METRIC_GSA,
            source_column="New",
        ).to_dict()
    ]
    frame = {
        "Y": data[["New"]].to_numpy(),
        "X_media": media,
        "X_controls": np.zeros((n_obs, 0)),
        "control_names": [],
        "markets": np.array(["UK"] * n_obs),
        "market_bounds": [(0, n_obs)],
        "market_idx": np.zeros(n_obs, dtype=int),
        "promo": np.zeros((n_obs, 1)),
        "trend": np.arange(n_obs, dtype=float),
        "fourier": np.zeros((n_obs, 0)),
        "outcome_ids": ["fh_new"],
        "channels": ["tv_grps"],
        "dna_channel_idx": [],
        "dates": dates.to_numpy(),
    }
    at = AppTest.from_file(str(PAGE), default_timeout=120)
    at.session_state["transformed_data"] = data
    at.session_state["model_spec"] = spec.to_dict()
    at.session_state["outcome_definitions"] = outcome_defs
    at.session_state["frame"] = frame
    at.run()
    return at


def test_deterministic_screen_is_available_and_remains_non_production():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    button = next(
        b
        for b in at.button
        if b.label == "Run deterministic pre-fit screen (no Bayesian fitting)"
    )
    at = button.click().run()
    assert not at.exception, f"screen click raised: {at.exception}"
    result = at.session_state["prefit_screening"]
    assert result["diagnostic_only"] is True
    assert result["official_eligibility"] is False
    assert result["model_mutation_applied"] is False
    assert any(
        "Deterministic pre-fit screen completed" in (success.value or "")
        for success in at.success
    )


def test_analyst_rationale_can_be_retained_without_approving_the_fit():
    at = _run_at()
    at = next(
        b
        for b in at.button
        if b.label == "Run deterministic pre-fit screen (no Bayesian fitting)"
    ).click().run()
    assert not at.exception, f"screen click raised: {at.exception}"
    rationale = next(
        item
        for item in at.text_area
        if item.label.startswith("Analyst review rationale")
    )
    at = rationale.input("Retain the current diagnostic scope for review.").run()
    save = next(b for b in at.button if b.label == "Save pre-fit analyst rationale")
    at = save.click().run()
    assert not at.exception, f"rationale save raised: {at.exception}"
    result = at.session_state["prefit_screening"]
    assert result["analyst_review"]["rationale_retained"] is True
    assert result["official_eligibility"] is False
