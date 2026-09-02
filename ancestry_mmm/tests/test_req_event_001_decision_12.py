"""Reconciliation tests for `REQ-EVENT-001`'s 2026-08-30 addendum
(business-decision brief Decision 12: event-family-specific timing).
Also guards against literal reverse-adstock ever being implemented, per
Decision 12's explicit prohibition."""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_EVENT_001_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-EVENT-001.md"
WP2_PACKAGE_PATH = (
    REPO_ROOT / "docs" / "wp2_named_event_statistical_method_decision_package.md"
)
NAMED_EVENTS_MODULE = REPO_ROOT / "ancestry_mmm" / "core" / "named_events.py"


def test_req_event_001_addendum_maps_all_three_families():
    text = REQ_EVENT_001_PATH.read_text()
    for family in ("Gifting", "Remembrance", "Promotional"):
        assert family in text
    assert "anticipatory" in text
    assert "contemporaneous" in text
    assert "post_event" in text


def test_req_event_001_addendum_does_not_move_factual_dates():
    text = REQ_EVENT_001_PATH.read_text()
    assert "factual event date remains factual" in text or "remains factual" in text


def test_req_event_001_addendum_does_not_select_response_structure():
    """Dimensions 1-4, 6, 7 of the decision package remain open - the
    addendum must say so explicitly, not silently imply a structure."""
    text = REQ_EVENT_001_PATH.read_text()
    assert "Still genuinely open" in text
    assert "S1-S4" in text or "response *structure*" in text.lower().replace("*", "")


def test_no_reverse_adstock_implemented_in_named_events_module():
    """Decision 12: 'reverse adstock' describes the business idea only -
    it must never be literally implemented."""
    if not NAMED_EVENTS_MODULE.exists():
        return
    text = NAMED_EVENTS_MODULE.read_text(encoding="utf-8", errors="ignore")
    assert not re.search(r"reverse[\s_-]*adstock", text, re.IGNORECASE)


def test_wp2_package_records_partial_dimension_5_resolution():
    text = WP2_PACKAGE_PATH.read_text()
    assert "dimension 5" in text.lower()
    assert "qualitative direction" in text.lower()


def test_req_event_001_indexed():
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req for req in data["requirements"] if req["requirement_id"] == "REQ-EVENT-001"
    ]
    assert len(matches) == 1
    assert REQ_EVENT_001_PATH.exists()
