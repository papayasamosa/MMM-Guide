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
    assert any("Sources by logical domain" in (m.value or "") for m in at.markdown)
    assert any(
        "Missing required logical domain(s)" in (w.value or "") for w in at.warning
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
        "2 physical source file(s) supplied under this domain" in (m.value or "")
        for m in at.caption
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
        "Missing required logical domain(s)" in (w.value or "") for w in at.warning
    )
    assert any("Ready" in (m.value or "") for m in at.markdown)
