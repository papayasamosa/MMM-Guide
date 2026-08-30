"""Reconciliation and stale-dependency guard tests for `REQ-SCENGINE-001`'s
2026-08-30 addendum (business-decision brief Decision 19: defer PathMC,
not reject)."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_SCENGINE_001_PATH = (
    REPO_ROOT / "docs" / "approved_requirements" / "REQ-SCENGINE-001.md"
)
WP_PACKAGE_PATH = REPO_ROOT / "docs" / "wp_structural_causal_engine_decision_package.md"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def test_req_scengine_001_addendum_resolves_d1_as_d1_b():
    text = REQ_SCENGINE_001_PATH.read_text()
    assert "D1-B" in text
    assert "not rejected" in text.lower() or "deferred, not rejected" in text.lower()


def test_wp_package_records_d1_resolution():
    text = WP_PACKAGE_PATH.read_text()
    assert "D1 resolved as D1-B" in text


def test_no_pathmc_runtime_dependency():
    """Decision 19: no new PathMC runtime dependency may be added."""
    if not PYPROJECT_PATH.exists():
        return
    text = PYPROJECT_PATH.read_text(encoding="utf-8", errors="ignore").lower()
    assert "pathmc" not in text


def test_req_scengine_001_indexed():
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req
        for req in data["requirements"]
        if req["requirement_id"] == "REQ-SCENGINE-001"
    ]
    assert len(matches) == 1
    assert REQ_SCENGINE_001_PATH.exists()
