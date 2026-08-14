"""AppTest coverage for pages/01_Data_Upload.py's Phase 3 UI overhaul
changes (REQ-DATAIN-001): the "Sources by logical domain" grouping (several
physical files under one logical domain, supplied-vs-missing required
domains) and the header's readiness badge. Complements the pre-existing
provenance/domain-caption tests in test_data_upload_source_version_apptest.py,
which this file does not duplicate.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_OUTCOMES,
    SourceDefinition,
)
from ancestry_mmm.data.loader import load_realistic_sample_sources

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


def _run_at(**extra_state):
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    for key, value in extra_state.items():
        at.session_state[key] = value
    at.run()
    return at


def test_no_sources_loaded_shows_awaiting_data_badge_and_empty_state():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Awaiting data" in (m.value or "") for m in at.markdown)
    assert any("No sources loaded yet" in (i.value or "") for i in at.info)


def test_standard_template_downloads_are_exposed_with_plain_language_help():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    labels = {button.label for button in at.download_button}
    assert labels == {
        "Download Outcomes (v2) template",
        "Download Activity and Media template",
        "Download Context and External Factors template",
        "Download Experiment Evidence template",
    }
    assert any("Required sheets are listed below" in (i.value or "") for i in at.info)


def test_partial_domain_coverage_lists_missing_required_domains():
    at = _run_at(
        raw_sources={"media": _frame()},
        source_definitions=[
            SourceDefinition(
                source_id="media",
                name="media",
                logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
            ).to_dict()
        ],
        data_loaded=True,
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Data by category" in (m.value or "") for m in at.markdown)
    assert any(
        "Missing required data categories" in (w.value or "") for w in at.warning
    )
    assert any("Outcomes" in (w.value or "") for w in at.warning)


def test_multiple_physical_files_group_under_one_logical_domain():
    """REQ-DATAIN-001: any number of physical source files may exist under
    one logical domain - never one file per domain."""
    at = _run_at(
        raw_sources={"tv_media": _frame(), "digital_media": _frame()},
        source_definitions=[
            SourceDefinition(
                source_id="tv_media",
                name="tv_media",
                logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
            ).to_dict(),
            SourceDefinition(
                source_id="digital_media",
                name="digital_media",
                logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
            ).to_dict(),
        ],
        data_loaded=True,
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "2 table(s) supplied under this category" in (m.value or "") for m in at.caption
    )


def test_source_semantic_adoption_status_is_visible():
    at = _run_at(
        raw_sources={"media": _frame()},
        source_definitions=[
            SourceDefinition(
                source_id="media",
                name="media",
                logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
            ).to_dict()
        ],
        source_domain_semantics=[
            {
                "source_id": "media-pack",
                "logical_domain": DOMAIN_ACTIVITY_AND_MEDIA,
                "schema_version": "standard-source-pack-v2",
                "status": "adopted_with_physical_mapping_review",
                "table_ids": ["activity_data", "activity_dictionary"],
                "adopted_objects": ["ActivityDefinition", "model_input_frame"],
                "unsupported_mappings": [
                    "currency: review the existing cost mapping contract"
                ],
                "next_action": "Review Activity Mapping.",
            }
        ],
        data_loaded=True,
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "What was recognised from your files?" in (m.value or "") for m in at.markdown
    )
    assert any(
        "Ready for mapping review" in str(cell)
        for table in at.dataframe
        for cell in table.value.values.flatten()
    )


def test_all_three_required_domains_supplied_shows_ready_badge():
    at = _run_at(
        raw_sources={"media": _frame(), "outcomes": _frame(), "controls": _frame()},
        source_definitions=[
            SourceDefinition(
                source_id="media",
                name="media",
                logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
            ).to_dict(),
            SourceDefinition(
                source_id="outcomes", name="outcomes", logical_domain=DOMAIN_OUTCOMES
            ).to_dict(),
            SourceDefinition(
                source_id="controls",
                name="controls",
                logical_domain="context_and_external_factors",
            ).to_dict(),
        ],
        data_loaded=True,
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert not any(
        "Missing required data categories" in (w.value or "") for w in at.warning
    )
    assert any("Ready" in (m.value or "") for m in at.markdown)


def test_realistic_source_pack_demo_loads_as_separate_governed_sources():
    at = _run_at()
    realistic_button = next(
        button for button in at.button if button.label == "Load realistic source pack"
    )
    realistic_button.click().run()

    assert not at.exception, f"realistic demo click raised: {at.exception}"
    frames, error = load_realistic_sample_sources()
    frames.pop("segment_ltv")
    assert error is None
    assert set(at.session_state["raw_sources"]) == set(frames)
    assert at.session_state["demo_source_pack"] == "realistic-source-pack-v2"
    assert len(at.session_state["source_definitions"]) == len(frames)
    assert at.session_state["active_source_upload_version"] == {}
