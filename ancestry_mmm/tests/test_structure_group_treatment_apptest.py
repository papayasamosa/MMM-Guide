"""WP5 AppTest coverage for the human-readable Structure group treatment UI."""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
    SEGMENT_DIMENSION_FH_CUSTOMER,
    OutcomeGroupDefinition,
)
from ancestry_mmm.core.activities import ActivityDefinition

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "03_Structure_Segments_Markets.py"
st.page_link = lambda *args, **kwargs: None


def _catalogue() -> list[dict[str, object]]:
    rows = []
    for outcome_id, segment, source_column in (
        ("fh_new_gsa", "New", "New"),
        ("fh_cross_sell_gsa", "DNA cross-sell", "DNA_CrossSell"),
        ("fh_winback_gsa", "Winback", "Winback"),
    ):
        rows.append(
            {
                "outcome_id": outcome_id,
                "product": FAMILY_HISTORY,
                "segment": segment,
                "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
                "metric": "GSA",
                "metric_key": METRIC_KEY_FH_GSA,
                "source_column": source_column,
                "included_in_fit": True,
            }
        )
    return rows


def _data() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=20, freq="W"),
            "market": ["UK"] * 20,
            "New": rng.poisson(50, 20).astype(float),
            "DNA_CrossSell": rng.poisson(20, 20).astype(float),
            "Winback": rng.poisson(15, 20).astype(float),
            "tv_spend": rng.uniform(1000, 5000, 20),
        }
    )


def test_structure_renders_human_group_summary_and_persists_selected_treatment():
    group = OutcomeGroupDefinition(
        group_id="fh_gsa_by_customer_segment",
        group_label="Family History GSA",
        product=FAMILY_HISTORY,
        outcome_family_key=METRIC_KEY_FH_GSA,
        segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
        member_outcome_ids=("fh_new_gsa", "fh_cross_sell_gsa", "fh_winback_gsa"),
    )
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = _data()
    at.session_state["date_col"] = "date"
    at.session_state["market_col"] = "market"
    at.session_state["activity_definitions"] = [
        ActivityDefinition(
            activity_id="tv",
            market="UK",
            channel="TV",
            model_input_column="tv_spend",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="test",
        ).to_dict()
    ]
    at.session_state["outcome_definitions"] = _catalogue()
    at.session_state["outcome_groups"] = [group.to_dict()]
    at.session_state["outcome_group_treatments"] = []
    at.run()

    assert not at.exception, f"group treatment UI raised: {at.exception}"
    treatment = next(
        item
        for item in at.selectbox
        if item.label == "Model treatment · Family History GSA"
    )
    assert "Components jointly" in treatment.options
    assert "Supplied total only" in treatment.options
    assert "Descriptive only" in treatment.options
    assert any(item.label == "Breakdown" for item in at.metric)

    treatment.select(OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT).run()
    save = next(
        item for item in at.button if item.label == "Save structure and validate"
    )
    save.click().run()

    assert not at.exception, f"saving group treatment raised: {at.exception}"
    assert at.session_state["outcome_group_treatments"] == [
        {
            "group_id": group.group_id,
            "treatment": OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
            "schema_version": 1,
        }
    ]
