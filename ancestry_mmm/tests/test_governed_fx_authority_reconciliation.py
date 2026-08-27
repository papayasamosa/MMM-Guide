"""Anti-drift tests for Work Package 7's governed-FX authority
reconciliation: `REQ-FX-001` through `REQ-FX-006` and the companion
`docs/wp7_governed_fx_finance_decision_package.md`.

Mirrors `test_structural_causal_authority_reconciliation.py`'s pattern
for a set of target-state-only records tied to one decision package, but
scoped to a single standalone addendum document
(`docs/PRD/Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md`)
rather than a multi-part PRD overlay - no per-part version table exists
for FX, so this file does not replicate the structural-causal file's
per-part overlay-table checks.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
AUTHORITY_PATH = REPO_ROOT / "docs" / "specification_authority.md"
DECISION_PACKAGE_PATH = (
    REPO_ROOT / "docs" / "wp7_governed_fx_finance_decision_package.md"
)
ADDENDUM_PATH = (
    REPO_ROOT
    / "docs"
    / "PRD"
    / "Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md"
)

FX_RECORD_IDS = tuple(f"REQ-FX-{n:03d}" for n in range(1, 7))


def _load_index() -> dict:
    return json.loads(INDEX_PATH.read_text())


def _find_requirement(data: dict, requirement_id: str) -> dict:
    matches = [
        req for req in data["requirements"] if req["requirement_id"] == requirement_id
    ]
    assert len(matches) == 1, (
        f"expected exactly one {requirement_id} entry in index.json, found {len(matches)}"
    )
    return matches[0]


def _markdown_table_rows(section_text: str) -> list[list[str]]:
    """Parse `| a | b | c |` rows from a Markdown section, skipping the
    header and `---` separator rows. Mirrors
    `test_outcome_approval.py::TestAuthorityConsistency._markdown_table_rows`."""
    rows = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= {"-", ":"} for c in cells):
            continue  # separator row
        rows.append(cells)
    return rows[1:]  # drop the header row


class TestGovernedFXOverlayReconciled:
    def test_all_six_records_indexed_and_files_exist(self):
        data = _load_index()
        for requirement_id in FX_RECORD_IDS:
            req = _find_requirement(data, requirement_id)
            assert req["status"] == "approved_for_implementation"
            record_path = REPO_ROOT / req["record_path"]
            assert record_path.exists(), f"missing record file: {record_path}"

    def test_req_fx_001_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-FX-001")

    def test_req_fx_002_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-FX-002")

    def test_req_fx_003_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-FX-003")

    def test_req_fx_004_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-FX-004")

    def test_req_fx_005_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-FX-005")

    def test_req_fx_006_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-FX-006")

    @staticmethod
    def _assert_gap_row_classified_incomplete(requirement_id: str) -> None:
        content = AUTHORITY_PATH.read_text()
        gaps_section = content.split(
            "## Current implementation gaps requiring decision records", 1
        )[1].split("## Approved requirement records already implemented", 1)[0]
        gap_rows = _markdown_table_rows(gaps_section)
        own_rows = [row for row in gap_rows if requirement_id in row[0]]
        assert own_rows, f"no implementation-gaps row references {requirement_id}"
        for row in own_rows:
            assert row[1] == "Requirement exists but capability incomplete", (
                f"{requirement_id}'s own capability row is classified "
                f"{row[1]!r}, expected 'Requirement exists but capability incomplete': {row}"
            )

    def test_all_six_records_named_in_implemented_section(self):
        content = AUTHORITY_PATH.read_text()
        implemented_section = content.split(
            "## Approved requirement records already implemented", 1
        )[1]
        for requirement_id in FX_RECORD_IDS:
            assert requirement_id in implemented_section, (
                f"{requirement_id} not referenced in the "
                "'Approved requirement records already implemented' section"
            )

    def test_decision_package_exists_and_makes_no_decision(self):
        assert DECISION_PACKAGE_PATH.exists()
        package_text = DECISION_PACKAGE_PATH.read_text()
        assert "This package makes no decision." in package_text
        assert "Decision package recorded; no decision made." in package_text

    def test_all_six_records_reference_the_decision_package(self):
        for requirement_id in FX_RECORD_IDS:
            record_path = (
                REPO_ROOT / "docs" / "approved_requirements" / f"{requirement_id}.md"
            )
            text = record_path.read_text()
            assert "wp7_governed_fx_finance_decision_package.md" in text, (
                f"{requirement_id} does not reference the companion decision package"
            )

    def test_decision_package_covers_every_addendum_section_20_item(self):
        """Section 20 of the addendum lists 10 Finance-approval items by
        number - the decision package must not silently drop any of
        them."""
        package_text = DECISION_PACKAGE_PATH.read_text()
        for item_number in range(1, 11):
            marker = f"### {item_number}. "
            assert marker in package_text, (
                f"decision package is missing an entry for addendum "
                f"Section 20 item {item_number}"
            )

    def test_addendum_source_file_exists_and_is_untouched_by_this_package(self):
        """This work package reconciles the addendum's architecture into
        repository authority; it must not edit the addendum itself, which
        remains the upstream source document."""
        assert ADDENDUM_PATH.exists()
        text = ADDENDUM_PATH.read_text()
        assert "Proposed requirements and technical design" in text
        assert "subject to Finance confirmation" in text

    def test_readme_documents_the_req_fx_category(self):
        readme_path = REPO_ROOT / "docs" / "approved_requirements" / "README.md"
        text = readme_path.read_text()
        assert "`REQ-FX-*`" in text
