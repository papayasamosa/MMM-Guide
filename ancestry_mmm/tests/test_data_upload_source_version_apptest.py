"""AppTest coverage for the Data Upload page's REQ-COVERAGE-001 S3 source-
version display (WP3 Phase 2).

`st.file_uploader` isn't driveable through Streamlit's AppTest API (no
programmatic file-upload simulation), matching the same limitation
`test_structure_page_apptest.py` documents for `st.data_editor` - these
tests instead prime session state with the exact shape
`load_file_with_source_version` + the page's "Add source" handler would
have produced, then drive the rest of the page for real.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.coverage import (
    SourceVersion,
    SourceDefinition,
    DOMAIN_ACTIVITY_AND_MEDIA,
    compute_checksum,
)

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "01_Data_Upload.py"


def _media_frame() -> pd.DataFrame:
    n = 10
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-01-06", periods=n, freq="W"),
            "market": ["UK"] * n,
            "TV_spend": rng.uniform(1000, 5000, n),
        }
    )


def _source_version(source_id: str = "media", version: int = 1) -> SourceVersion:
    return SourceVersion(
        source_id=source_id,
        version=version,
        original_filename=f"media_v{version}.csv",
        checksum=compute_checksum(f"deterministic-test-bytes-v{version}".encode()),
        size_bytes=1234,
        uploaded_at="2026-08-09T00:00:00+00:00",
        parsed_representation_version="pandas-test",
    )


def test_page_loads_and_shows_source_version_caption_for_an_uploaded_source():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["raw_sources"] = {"media": _media_frame()}
    at.session_state["source_versions"] = [_source_version(version=1).to_dict()]
    at.session_state["active_source_upload_version"] = {"media": 1}
    at.session_state["data_loaded"] = True
    at.run()
    assert not at.exception, f"page load raised: {at.exception}"

    captions = [c.value for c in at.caption]
    assert any("Source version v1" in c for c in captions)
    assert any("media_v1.csv" in c for c in captions)
    checksum_prefix = compute_checksum(b"deterministic-test-bytes-v1")[:12]
    assert any(checksum_prefix in c for c in captions)


def test_page_loads_without_error_for_a_source_with_no_version_history():
    """A demo/sample-loaded source never gets a SourceVersion (only a real
    upload does) - the page must render without a checksum caption for it,
    not raise."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["raw_sources"] = {"media": _media_frame()}
    at.session_state["source_versions"] = []
    at.session_state["active_source_upload_version"] = {}
    at.session_state["data_loaded"] = True
    at.run()
    assert not at.exception, f"page load raised: {at.exception}"

    captions = [c.value for c in at.caption]
    assert not any("Source version" in c for c in captions)


def test_shows_the_active_version_not_merely_the_latest_in_history():
    """The active-frame's provenance can legitimately be an earlier version
    than the newest history entry has recorded elsewhere (e.g. after a
    "Remove" + re-add of an older file) - the caption must reflect what
    actually produced the current frame, not whichever history row has the
    highest version number."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["raw_sources"] = {"media": _media_frame()}
    at.session_state["source_versions"] = [
        _source_version(version=1).to_dict(),
        _source_version(version=2).to_dict(),
    ]
    at.session_state["active_source_upload_version"] = {"media": 1}
    at.session_state["data_loaded"] = True
    at.run()
    assert not at.exception, f"page load raised: {at.exception}"

    captions = [c.value for c in at.caption]
    assert any("Source version v1" in c for c in captions)
    assert not any("Source version v2" in c for c in captions)


def test_demo_data_does_not_inherit_a_prior_real_uploads_provenance():
    """P2 review finding on an earlier version of this page: loading
    synthetic demo data under a name that previously had a real upload
    (e.g. "media") must not display that upload's filename/checksum
    against the now-demo frame - the demo frame did not come from those
    bytes. active_source_upload_version being empty for "media" (as the
    demo-load handler now resets it) is what prevents this, even though
    source_versions history for "media" still exists."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["raw_sources"] = {"media": _media_frame()}
    at.session_state["source_versions"] = [_source_version(version=1).to_dict()]
    at.session_state["active_source_upload_version"] = {}
    at.session_state["data_loaded"] = True
    at.run()
    assert not at.exception, f"page load raised: {at.exception}"

    captions = [c.value for c in at.caption]
    assert not any("Source version" in c for c in captions)
    assert not any("media_v1.csv" in c for c in captions)


# ---------------------------------------------------------------------------
# REQ-DATAIN-001: logical source domain display
# ---------------------------------------------------------------------------


def test_shows_the_recorded_logical_domain_for_a_source():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["raw_sources"] = {"media": _media_frame()}
    at.session_state["source_versions"] = []
    at.session_state["active_source_upload_version"] = {}
    at.session_state["source_definitions"] = [
        SourceDefinition(
            source_id="media",
            name="media",
            logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
        ).to_dict()
    ]
    at.session_state["data_loaded"] = True
    at.run()
    assert not at.exception, f"page load raised: {at.exception}"

    captions = [c.value for c in at.caption]
    assert any("Activity and Media" in c for c in captions)


def test_shows_standard_workbook_schema_and_table_identity():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    table_id = "activity-pack__sheet__activity_data"
    at.session_state["raw_sources"] = {
        table_id: pd.DataFrame(
            {
                "period_start": ["2025-01-06"],
                "market": ["UK"],
                "activity_id": ["meta_brand"],
            }
        )
    }
    at.session_state["source_versions"] = [
        {
            **_source_version("activity-pack").to_dict(),
            "original_filename": "activity-pack.xlsx",
            "template_schema_version": "standard-source-pack-v1",
            "standard_template": True,
            "parsed_table_ids": ["activity_and_media:activity_data"],
            "workbook_sheet_names": ["activity_data", "activity_dictionary"],
            "template_warnings": [],
            "template_errors": [],
        }
    ]
    at.session_state["active_source_upload_version"] = {table_id: 1}
    at.session_state["source_definitions"] = [
        SourceDefinition(
            source_id=table_id,
            name="activity-pack/activity_data",
            logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
        ).to_dict()
    ]
    at.session_state["data_loaded"] = True
    at.run()
    assert not at.exception, f"page load raised: {at.exception}"

    captions = [c.value for c in at.caption]
    assert any("Standard workbook schema" in c for c in captions)
    assert any("activity_and_media:activity_data" in c for c in captions)


def test_shows_unclassified_for_a_source_with_no_recorded_domain():
    """A source with no SourceDefinition (e.g. a bundle imported before
    REQ-DATAIN-001 existed) must read as explicitly unclassified, never a
    guessed domain."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["raw_sources"] = {"media": _media_frame()}
    at.session_state["source_versions"] = []
    at.session_state["active_source_upload_version"] = {}
    at.session_state["source_definitions"] = []
    at.session_state["data_loaded"] = True
    at.run()
    assert not at.exception, f"page load raised: {at.exception}"

    captions = [c.value for c in at.caption]
    assert any("Unclassified" in c for c in captions)


def test_domain_selectbox_defaults_to_an_unselected_placeholder():
    """Review finding: a Streamlit selectbox pre-selects its first option,
    so listing the four real domains directly would let "Add source" be
    clicked without the analyst ever making the required classification.
    The default value must be a non-domain placeholder, never a real
    logical domain (which would silently persist an unauthorized default
    classification)."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"page load raised: {at.exception}"

    domain_selectbox = next(sb for sb in at.selectbox if sb.label == "Data category *")
    assert domain_selectbox.value not in (
        "outcomes",
        "activity_and_media",
        "context_and_external_factors",
        "experiment_evidence",
    )
