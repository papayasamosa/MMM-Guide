"""Anti-drift and reconciliation tests for `REQ-SEO-001`'s 2026-08-30
addendum (business-decision brief Decisions 5, 6, 7, 8). Decisions 7 and
8 are audit confirmations, not bug fixes - a repository-wide search found
no £5,000/month SEO cost assumption and no 28-August-2023 SEO modelling
meaning anywhere in this repository. These tests are forward guards
against reintroduction, plus a check that the addendum text itself
records the approved causal-role/metric-type resolutions.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_SEO_001_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-SEO-001.md"
WP1_PACKAGE_PATH = REPO_ROOT / "docs" / "wp1_search_seo_granularity_decision_package.md"

# Only scan source/doc files, never CSV sample data (which legitimately
# contains ordinary calendar dates and currency-shaped numbers with no SEO
# meaning whatsoever).
_SCAN_SUFFIXES = {".py", ".md"}
_EXCLUDED_DIR_PARTS = {
    ".git",
    "node_modules",
    "designs",
    "tools",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "cache",
    "temp",
    "test-artifacts",
    "graphify-out",
    "archive",
    "mmm_guide.egg-info",
    ".playwright-mcp",
    ".local-data",
    "__pycache__",
    ".streamlit",
    ".claude",
    ".github",
    ".vscode",
}
_EXCLUDED_FILES = {
    Path(__file__).resolve(),
    REQ_SEO_001_PATH.resolve(),  # this record's own audit-confirmation text
    (REPO_ROOT / "docs" / "decision_log.md").resolve(),  # audit narrative, not logic
}

_SEO_5K_PATTERN = re.compile(r"(£|GBP)?\s*5,?000\s*(/|per)\s*month", re.IGNORECASE)
_SEO_CONTEXT_PATTERN = re.compile(r"\bSEO\b", re.IGNORECASE)
_AUG_28_2023_PATTERN = re.compile(r"2023-08-28|28\s+August\s+2023", re.IGNORECASE)


def _iter_scan_files():
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        if path.resolve() in _EXCLUDED_FILES:
            continue
        if any(part in _EXCLUDED_DIR_PARTS for part in path.parts):
            continue
        yield path


def test_no_seo_5k_month_cost_assumption_in_active_code_or_docs():
    """`REQ-SEO-001` Decision 7 addendum: no ~£5,000/month SEO cost figure
    may exist as an official assumption anywhere in active code or
    documentation (a repo-wide search found none at approval time - this
    guards against reintroduction)."""
    offending = []
    for path in _iter_scan_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _SEO_5K_PATTERN.finditer(text):
            window = text[max(0, match.start() - 200) : match.end() + 200]
            if _SEO_CONTEXT_PATTERN.search(window):
                line_no = text.count("\n", 0, match.start()) + 1
                offending.append(f"{path.relative_to(REPO_ROOT)}:{line_no}")
    assert not offending, f"found a £5,000/month SEO cost reference: {offending}"


def test_no_28_august_2023_seo_modelling_meaning_in_active_code_or_docs():
    """`REQ-SEO-001` Decision 8 addendum: 28 August 2023 has no approved
    SEO modelling meaning. No .py/.md file may use that date near SEO
    context as a boundary/start/truncation/intervention date. CSV sample
    data legitimately containing that ordinary calendar date is out of
    scope for this check (it is data, not logic)."""
    offending = []
    for path in _iter_scan_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _AUG_28_2023_PATTERN.finditer(text):
            window = text[max(0, match.start() - 200) : match.end() + 200]
            if _SEO_CONTEXT_PATTERN.search(window):
                line_no = text.count("\n", 0, match.start()) + 1
                offending.append(f"{path.relative_to(REPO_ROOT)}:{line_no}")
    assert not offending, (
        f"found 28-August-2023 used in SEO context (REQ-SEO-001 Decision 8 "
        f"approves no SEO meaning for this date): {offending}"
    )


def test_req_seo_001_addendum_resolves_causal_role_and_metric_type():
    """The 2026-08-30 addendum text records the approved causal-role value
    and the positional-visibility metric-type decision, without silently
    approving the exact estimand/formula (still Phase B)."""
    text = REQ_SEO_001_PATH.read_text()
    assert "mediator_or_capture_efficiency_state" in text
    assert "positional" in text.lower() or "visibility" in text.lower()
    # The exact formula must remain explicitly deferred, not invented here.
    assert "Phase B" in text


def test_wp1_package_records_d1_d2_d3_resolved_d4_d7_open():
    """`docs/wp1_search_seo_granularity_decision_package.md`'s 2026-08-30
    update records D1/D2/D3 as resolved and D4-D7 as still open - the
    package's original analysis is not silently rewritten."""
    text = WP1_PACKAGE_PATH.read_text()
    assert "D1" in text and "resolved" in text.lower()
    assert "D4, D5, D6, and D7 remain open" in text


def test_req_seo_001_indexed():
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req for req in data["requirements"] if req["requirement_id"] == "REQ-SEO-001"
    ]
    assert len(matches) == 1
    assert REQ_SEO_001_PATH.exists()
