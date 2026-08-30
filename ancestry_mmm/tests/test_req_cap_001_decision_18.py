"""Reconciliation test for `REQ-CAP-001`'s 2026-08-30 addendum
(business-decision brief Decision 18: real-world capacity constraints in
the optimiser). Confirms the addendum does not prematurely select G1 vs
G3 or S1/S2/S3, which remain genuinely open engineering decisions."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_CAP_001_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-CAP-001.md"


def test_req_cap_001_addendum_does_not_select_g1_over_g3():
    text = REQ_CAP_001_PATH.read_text()
    assert "does **not** select G1 over G3" in text


def test_req_cap_001_addendum_leaves_cap_hit_vocabulary_open():
    text = REQ_CAP_001_PATH.read_text()
    assert "also remains fully open" in text


def test_req_cap_001_addendum_cross_references_req_opt_001():
    text = REQ_CAP_001_PATH.read_text()
    assert "REQ-OPT-001" in text


def test_req_cap_001_indexed():
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req for req in data["requirements"] if req["requirement_id"] == "REQ-CAP-001"
    ]
    assert len(matches) == 1
    assert REQ_CAP_001_PATH.exists()
