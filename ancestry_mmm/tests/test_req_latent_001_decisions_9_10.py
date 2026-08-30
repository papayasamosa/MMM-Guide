"""Reconciliation tests for `REQ-LATENT-001`'s 2026-08-30 addenda
(business-decision brief Decisions 9 and 10: Google Trends brand-demand
anchor; Search capacity-cap principle)."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_LATENT_001_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-LATENT-001.md"


def test_req_latent_001_approves_google_trends_as_anchor_source():
    text = REQ_LATENT_001_PATH.read_text()
    assert "Google Trends" in text
    assert "MD-021" in text


def test_req_latent_001_forbids_absolute_search_count_interpretation():
    text = " ".join(REQ_LATENT_001_PATH.read_text().split())
    assert "relative index, not an absolute volume" in text


def test_req_latent_001_does_not_resolve_full_md_021():
    text = REQ_LATENT_001_PATH.read_text()
    assert "Still genuinely open" in text


def test_req_latent_001_indexed():
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req for req in data["requirements"] if req["requirement_id"] == "REQ-LATENT-001"
    ]
    assert len(matches) == 1
    assert REQ_LATENT_001_PATH.exists()
