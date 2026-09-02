"""Reconciliation test for `REQ-FUTURE-001`'s 2026-08-30 addendum
(business-decision brief Decision 14: minimize manual assumption entry
in Scenario Planner) and its named WP2G reconciliation task."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_FUTURE_001_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-FUTURE-001.md"


def test_req_future_001_addendum_records_wp2g_reconciliation():
    text = REQ_FUTURE_001_PATH.read_text()
    assert "WP2G" in text
    assert "ScenarioValueAssumptions" in text
    assert "Phase D" in text


def test_req_future_001_addendum_does_not_change_shipped_ui():
    text = " ".join(REQ_FUTURE_001_PATH.read_text().split())
    assert "No change to WP2G's shipped UI or defaults" in text


def test_req_future_001_indexed():
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req for req in data["requirements"] if req["requirement_id"] == "REQ-FUTURE-001"
    ]
    assert len(matches) == 1
    assert REQ_FUTURE_001_PATH.exists()
