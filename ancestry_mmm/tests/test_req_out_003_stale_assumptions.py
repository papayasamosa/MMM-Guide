"""Anti-drift tests for `REQ-OUT-003` (Family History LTR horizon and DNA
cross-sell window). These tests guard the repo-wide stale-assumption
sweep the business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (Decision 1) requires: a repository-wide
search found zero existing occurrences of a 36-month Family History LTR
assumption anywhere, so this is a *forward guard* against reintroduction,
not a fix for an existing bug.
"""

import json
import re
from pathlib import Path

import pytest

from ancestry_mmm.core.outcomes import (
    METRIC_KEY_FH_GSA,
    METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    METRIC_KEY_FH_SIGNUP,
)
from ancestry_mmm.core.schema import DEFAULT_SEGMENTS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_OUT_003_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-OUT-003.md"

# Directories that are legitimately excluded from the "active code/current
# documentation" sweep: git internals, the decision log itself (a historical
# record of what was decided *when*, not active logic), and this test file's
# own docstring/pattern definitions.
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
    (REPO_ROOT / "docs" / "decision_log.md").resolve(),
    REQ_OUT_003_PATH.resolve(),
}

# Matches a Family-History-LTR-flavoured 36-month reference: the number 36
# co-occurring with "month" within a short window, near FH/LTR/lifetime
# vocabulary. Deliberately narrow so it does not flag unrelated uses of the
# number 36 (random seeds, unrelated durations, page numbers, etc.) per the
# brief's own "do not mechanically change unrelated uses of 36 months"
# instruction.
_36_MONTH_PATTERN = re.compile(r"36[\s-]*month", re.IGNORECASE)
_FH_LTR_CONTEXT_PATTERN = re.compile(
    r"(family\s*history|fh_).{0,80}(ltr|lifetime)|"
    r"(ltr|lifetime).{0,80}(family\s*history|fh_)",
    re.IGNORECASE,
)

_TEXT_SUFFIXES = {".py", ".md", ".json", ".csv", ".txt", ".yaml", ".yml"}


def _iter_repo_text_files():
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if path.resolve() in _EXCLUDED_FILES:
            continue
        if any(part in _EXCLUDED_DIR_PARTS for part in path.parts):
            continue
        yield path


def test_no_36_month_fh_ltr_reference_in_active_code_or_docs():
    """`REQ-OUT-003` §1: the approved FH LTR horizon is 48 months. No
    active code, test, fixture, or current documentation may assume 36
    months for this specific business definition. A 36-month reference
    with no nearby FH/LTR/lifetime context is not flagged - the brief
    explicitly warns against mechanically changing unrelated uses of the
    number 36."""
    offending: list[str] = []
    for path in _iter_repo_text_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _36_MONTH_PATTERN.finditer(text):
            window_start = max(0, match.start() - 200)
            window_end = min(len(text), match.end() + 200)
            window = text[window_start:window_end]
            if _FH_LTR_CONTEXT_PATTERN.search(window):
                line_no = text.count("\n", 0, match.start()) + 1
                offending.append(f"{path.relative_to(REPO_ROOT)}:{line_no}")
    assert not offending, (
        "found a 36-month reference in FH-LTR context (REQ-OUT-003 approves "
        f"48 months): {offending}"
    )


def test_no_fourth_fh_segment_defined():
    """`REQ-OUT-003` §3: exactly three Family History segments - New,
    Winback, DNA Cross-sell - never a fourth."""
    assert set(DEFAULT_SEGMENTS) == {"New", "DNA_CrossSell", "Winback"}
    assert len(DEFAULT_SEGMENTS) == 3


def test_gsa_and_net_bill_through_remain_distinct_metric_keys():
    """`REQ-OUT-003` §4 (reaffirming `REQ-OUT-001`): GSA and Net Bill
    Through must never collapse to the same stable metric key, and
    Sign-up must remain a third, independent identity."""
    keys = {
        METRIC_KEY_FH_GSA,
        METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
        METRIC_KEY_FH_SIGNUP,
    }
    assert len(keys) == 3, f"expected 3 distinct metric keys, found {keys}"
    assert METRIC_KEY_FH_GSA != METRIC_KEY_FH_NET_BILLTHROUGH_COUNT


def test_req_out_003_indexed_and_classified():
    """`REQ-OUT-003` is indexed in `index.json`, its record file exists,
    and it approves the 48-month/120-day figures rather than leaving them
    as unresolved decisions (both are supplied directly by the business-
    decision brief, not left open)."""
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req for req in data["requirements"] if req["requirement_id"] == "REQ-OUT-003"
    ]
    assert len(matches) == 1
    assert matches[0]["status"] == "approved_for_implementation"
    assert REQ_OUT_003_PATH.exists()
    text = REQ_OUT_003_PATH.read_text()
    assert "48 months" in text or "48 months (4 years)" in text
    assert "120 days" in text


@pytest.mark.parametrize("forbidden_alias", ["fh_gsa == fh_net_billthrough_count"])
def test_metric_keys_are_strings_not_aliased_via_equality(forbidden_alias):
    """Belt-and-braces: the two outcome-type identities are different
    Python string values, not merely different variable names bound to
    the same underlying value (which would silently alias them)."""
    assert METRIC_KEY_FH_GSA != METRIC_KEY_FH_NET_BILLTHROUGH_COUNT
    assert isinstance(METRIC_KEY_FH_GSA, str)
    assert isinstance(METRIC_KEY_FH_NET_BILLTHROUGH_COUNT, str)
