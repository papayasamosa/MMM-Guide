"""AppTest coverage for the Diagnostics page's media-outcome pathway drift
info message (PR F)."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "06_Diagnostics.py"


def _frame():
    n = 12
    return {
        "outcome_ids": ["fh_new_gsa"],
        "Y": np.column_stack([np.full(n, 10.0)]),
        "dates": np.array([f"2024-01-{i + 1:02d}" for i in range(n)], dtype="datetime64[D]"),
        "df": None,
    }


def _pathway_dict(**overrides):
    d = {
        "pathway_id": "p1", "channel": "TV", "source_product": "Family History",
        "target_outcome_id": "fh_new_gsa", "role": "primary_direct", "lag_type": "none",
        "lag_weeks": None, "prior_scale": 1.0, "include_in_attribution": True,
        "include_in_planning": True, "evidence_status": "untested",
    }
    d.update(overrides)
    return d


def _meta(outcome_ids, pathway_catalogue_at_fit=None):
    return SimpleNamespace(
        outcome_ids=outcome_ids, direct_dna_outcome_ids=[], outcome_catalogue_at_fit=[],
        pathway_catalogue_at_fit=pathway_catalogue_at_fit or [],
    )


def _spec_dict():
    return ModelSpec(
        date_col="date", market_col="market", markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"}, channels=["TV"],
    ).to_dict()


def test_no_pathway_catalogue_shows_no_pathway_info():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    frame = _frame()
    at.session_state["trace"] = object()
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = _meta(frame["outcome_ids"])
    at.session_state["model_spec"] = _spec_dict()
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert not any("media-outcome pathway" in (i.value or "") for i in at.info)


def test_unchanged_pathway_shows_no_drift_info():
    from ancestry_mmm.core.pathways import MediaOutcomePathway

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    frame = _frame()
    fit_time_pathway = MediaOutcomePathway.from_dict(_pathway_dict())
    at.session_state["trace"] = object()
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = _meta(frame["outcome_ids"], pathway_catalogue_at_fit=[fit_time_pathway])
    at.session_state["media_outcome_pathways"] = [_pathway_dict()]
    at.session_state["model_spec"] = _spec_dict()
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert not any("media-outcome pathway" in (i.value or "") for i in at.info)


def test_changed_pathway_role_shows_drift_info():
    from ancestry_mmm.core.pathways import MediaOutcomePathway

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    frame = _frame()
    fit_time_pathway = MediaOutcomePathway.from_dict(_pathway_dict(role="primary_direct"))
    at.session_state["trace"] = object()
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = _meta(frame["outcome_ids"], pathway_catalogue_at_fit=[fit_time_pathway])
    at.session_state["media_outcome_pathways"] = [_pathway_dict(role="excluded")]
    at.session_state["model_spec"] = _spec_dict()
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("2 media-outcome pathway(s) differ" in (w.value or "") for w in at.warning)
