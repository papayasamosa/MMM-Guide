"""Reconciliation tests for `REQ-SEARCH-004`'s 2026-08-30 addendum
(business-decision brief Decisions 2 and 4: minimum Paid Search taxonomy
content and the required reporting roll-up hierarchy)."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_SEARCH_004_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-SEARCH-004.md"
WP1_PACKAGE_PATH = REPO_ROOT / "docs" / "wp1_search_seo_granularity_decision_package.md"


def test_req_search_004_addendum_names_brand_non_brand_taxonomy():
    text = REQ_SEARCH_004_PATH.read_text()
    assert '"Brand"' in text
    assert '"Non-Brand"' in text
    assert "brand_class" in text


def test_req_search_004_addendum_treats_platform_as_orthogonal_axis():
    text = REQ_SEARCH_004_PATH.read_text()
    assert "orthogonal" in text.lower() or "independent dimension" in text.lower()
    assert "Google" in text and "Bing" in text


def test_req_search_004_addendum_excludes_pmax_demand_gen_youtube():
    text = REQ_SEARCH_004_PATH.read_text()
    assert "PMax" in text
    assert "Demand Gen" in text
    assert "YouTube" in text
    assert "excluded" in text.lower()


def test_req_search_004_addendum_does_not_invent_d4_threshold():
    """Decision 2 supplies the gating *principle* for deeper Non-Brand
    keyword groups, not a numeric threshold - D4 remains genuinely open."""
    text = REQ_SEARCH_004_PATH.read_text()
    assert "no concrete numeric threshold is\napproved here".replace(
        "\n", " "
    ) in text.replace("\n", " ")


def test_req_search_004_indexed():
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req
        for req in data["requirements"]
        if req["requirement_id"] == "REQ-SEARCH-004"
    ]
    assert len(matches) == 1
    assert REQ_SEARCH_004_PATH.exists()
