"""Work Package 2 (`Media-Mix-Lab: Coding LLM Next Steps After PR #291`):
AppTest coverage for the Experiment Evidence registry workflow wired into
pages/01_Data_Upload.py - source rows wait for explicit analyst adoption,
the registry is immutable, and the page never runs calibration mathematics."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    SourceDefinition,
)
from ancestry_mmm.core.experiments import (
    EXPERIMENT_DESIGN_GEO_TEST,
    ExperimentRecord,
)

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "01_Data_Upload.py"


def _frame() -> pd.DataFrame:
    n = 8
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-01-06", periods=n, freq="W"),
            "market": ["UK"] * n,
            "value": rng.uniform(100, 500, n),
        }
    )


def _evidence_row() -> dict:
    return {
        "experiment_id": "exp-geo-1",
        "activity_id": "TV_Brand",
        "market": "UK",
        "start_date": "2026-01-05",
        "end_date": "2026-02-01",
    }


def _registered_record() -> dict:
    return ExperimentRecord(
        experiment_id="exp-geo-1",
        experiment_version=1,
        design=EXPERIMENT_DESIGN_GEO_TEST,
        start_date="2026-01-05",
        end_date="2026-02-01",
        market_scope=("UK",),
        estimand="incremental GSA acquisitions",
        observed_effect_estimate=0.12,
        effect_uncertainty=0.04,
        method="difference-in-differences",
        source="geo-test platform export",
        evidence_status="draft_review_required",
    ).to_dict()


def _run_at(**extra_state):
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["raw_sources"] = {"media": _frame()}
    at.session_state["source_definitions"] = [
        SourceDefinition(
            source_id="media",
            name="media",
            logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
        ).to_dict()
    ]
    at.session_state["data_loaded"] = True
    for key, value in extra_state.items():
        at.session_state[key] = value
    at.run()
    return at


def _all_text(at: AppTest) -> str:
    parts = [(m.value or "") for m in at.markdown]
    parts += [(c.value or "") for c in at.caption]
    parts += [(i.value or "") for i in at.info]
    parts += [(s.value or "") for s in at.success]
    return "\n".join(parts)


def test_registry_section_shows_explicit_empty_state():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    text = _all_text(at)
    assert "Experiment Evidence registry" in text
    assert "No experiments have been adopted into the governed registry yet." in text


def test_source_rows_are_listed_but_never_auto_adopted():
    at = _run_at(experiment_evidence_rows=[_evidence_row()])
    assert not at.exception, f"page raised: {at.exception}"
    # The row renders in the awaiting-adoption table, but the registry stays
    # empty until the analyst explicitly adopts it.
    assert at.session_state["experiment_records"] == []
    text = _all_text(at)
    assert "Source rows awaiting adoption" in text


def test_adopting_a_completed_row_registers_a_version_1_record():
    at = _run_at(experiment_evidence_rows=[_evidence_row()])
    assert not at.exception, f"page raised: {at.exception}"

    at.text_input(key="exp_adopt_estimand").set_value("incremental GSA acquisitions")
    at.number_input(key="exp_adopt_effect").set_value(0.12)
    at.number_input(key="exp_adopt_uncertainty").set_value(0.04)
    at.text_input(key="exp_adopt_method").set_value("difference-in-differences")
    at.text_input(key="exp_adopt_source").set_value("geo-test platform export")
    at.run()

    submit = next(b for b in at.button if b.label == "Adopt into registry")
    submit.click().run()
    assert not at.exception, f"page raised after adopting: {at.exception}"
    records = at.session_state["experiment_records"]
    assert len(records) == 1
    assert records[0]["experiment_id"] == "exp-geo-1"
    assert records[0]["experiment_version"] == 1
    assert records[0]["evidence_status"] == "draft_review_required"
    text = _all_text(at)
    assert "adopted as version 1" in text


def test_adopting_without_required_fields_fails_closed():
    at = _run_at(experiment_evidence_rows=[_evidence_row()])
    assert not at.exception, f"page raised: {at.exception}"

    # No analyst metadata supplied at all - adoption must fail closed with
    # the missing fields named, and the registry must stay empty.
    submit = next(b for b in at.button if b.label == "Adopt into registry")
    submit.click().run()
    assert not at.exception, f"page raised after adopting: {at.exception}"
    assert at.session_state["experiment_records"] == []
    assert any("missing required field" in (e.value or "") for e in at.error)


def test_registered_experiments_render_with_their_versions():
    at = _run_at(experiment_records=[_registered_record()])
    assert not at.exception, f"page raised: {at.exception}"
    text = _all_text(at)
    assert "Registered experiments" in text
