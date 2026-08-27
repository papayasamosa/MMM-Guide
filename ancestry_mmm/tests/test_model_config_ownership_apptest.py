"""UI-WP4: Model Setup separates inherited scope from editable response
assumptions. Regression coverage for the ownership-confusion fix - the page
previously had two adjacent sections both named "Model strategy" (one
read-only, inherited from Structure; one editable), which implied
conflicting ownership. This asserts the renamed sections exist, are
distinct, and that no ambiguous duplicate label remains."""

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
    outcome_defs = [
        OutcomeDefinition(
            outcome_id="fh_new",
            product=FAMILY_HISTORY,
            segment="New",
            metric=METRIC_GSA,
            source_column="New",
        ).to_dict(),
    ]
    return df, spec, outcome_defs


def _run_at():
    df, spec, outcome_defs = _base_state()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = df
    at.session_state["model_spec"] = spec.to_dict()
    at.session_state["outcome_definitions"] = outcome_defs
    at.run()
    return at


def test_inherited_market_scope_and_editable_response_strategy_are_distinct_sections():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"

    markdown_texts = [m.value or "" for m in at.markdown]
    assert any("Market scope and hierarchy" in text for text in markdown_texts)
    assert any("Response strategy" in text for text in markdown_texts)

    # The two sections must never share the ambiguous "Model strategy" label
    # that previously appeared on both a read-only and an editable section.
    assert not any(text.strip() == "### Model strategy" for text in markdown_texts)
    assert not any("Model strategy · market pooling" in text for text in markdown_texts)


def test_market_scope_section_is_explicitly_read_only():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    markdown_texts = [m.value or "" for m in at.markdown]
    assert any(
        "Market scope and hierarchy" in text and "Read-only" not in text
        for text in markdown_texts
    ) or any(
        "Read-only here - inherited from Structure" in text for text in markdown_texts
    )


def test_summary_caption_points_to_response_strategy_not_ambiguous_pooling():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    caption_texts = [c.value or "" for c in at.caption]
    assert any(
        "Response strategy" in text and "change it in Response strategy below" in text
        for text in caption_texts
    )
    assert not any(text.startswith("Pooling strategy:") for text in caption_texts)


def test_sampling_settings_has_its_own_labelled_section():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    markdown_texts = [m.value or "" for m in at.markdown]
    assert any("Sampling settings" in text for text in markdown_texts)
    expander_labels = {e.label for e in at.expander}
    assert "Advanced sampling" in expander_labels
