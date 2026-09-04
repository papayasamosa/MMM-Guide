"""Anti-drift tests for Work Package 1's Search-granularity/SEO-visibility
authority reconciliation: `REQ-SEARCH-004`, `REQ-SEARCH-005`,
`REQ-SEO-001`, and the companion
`docs/wp1_search_seo_granularity_decision_package.md`.

This is the deferred second half of the reconciliation Work Package 0
(2026-08-24) deliberately left undone -
`test_search_granularity_overlay_reconciliation.py` already covers WP0's
version-table-only pass and is not duplicated here. These tests check
only what Work Package 1 actually added: three new target-state
architecture records (no candidate approach, taxonomy content, causal
role, or threshold chosen by any of them) and the decision package that
collects everything they exclude, following the same pattern already
established by `test_governed_fx_authority_reconciliation.py` and
`test_structural_causal_authority_reconciliation.py`.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
AUTHORITY_PATH = REPO_ROOT / "docs" / "specification_authority.md"
DECISION_PACKAGE_PATH = (
    REPO_ROOT / "docs" / "wp1_search_seo_granularity_decision_package.md"
)

NEW_RECORD_IDS = ("REQ-SEARCH-004", "REQ-SEARCH-005", "REQ-SEO-001")


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


class TestSearchSeoGranularityOverlayReconciled:
    def test_all_three_records_indexed_and_files_exist(self):
        data = _load_index()
        for requirement_id in NEW_RECORD_IDS:
            req = _find_requirement(data, requirement_id)
            assert req["status"] == "approved_for_implementation"
            record_path = REPO_ROOT / req["record_path"]
            assert record_path.exists(), f"missing record file: {record_path}"

    def test_req_search_004_indexed_and_classified_partial(self):
        self._assert_gap_row_classified_partial("REQ-SEARCH-004")

    def test_req_search_005_indexed_and_classified_partial(self):
        self._assert_gap_row_classified_partial("REQ-SEARCH-005")

    def test_req_seo_001_indexed_and_classified_partial(self):
        self._assert_gap_row_classified_partial("REQ-SEO-001")

    @staticmethod
    def _assert_gap_row_classified_partial(requirement_id: str) -> None:
        content = AUTHORITY_PATH.read_text()
        gaps_section = content.split(
            "## Current implementation gaps requiring decision records", 1
        )[1].split("## Approved requirement records already implemented", 1)[0]
        gap_rows = _markdown_table_rows(gaps_section)
        own_rows = [row for row in gap_rows if requirement_id in row[0]]
        assert own_rows, f"no implementation-gaps row references {requirement_id}"
        for row in own_rows:
            assert row[1] == "Requirement exists and is partially implemented", (
                f"{requirement_id}'s own capability row is classified "
                f"{row[1]!r}, expected 'Requirement exists and is partially implemented': {row}"
            )

    def test_all_three_records_named_in_implemented_section(self):
        content = AUTHORITY_PATH.read_text()
        implemented_section = content.split(
            "## Approved requirement records already implemented", 1
        )[1]
        for requirement_id in NEW_RECORD_IDS:
            assert requirement_id in implemented_section, (
                f"{requirement_id} not referenced in the "
                "'Approved requirement records already implemented' section"
            )

    def test_decision_package_exists_and_makes_no_decision(self):
        assert DECISION_PACKAGE_PATH.exists()
        package_text = DECISION_PACKAGE_PATH.read_text()
        assert "Status: decision support only." in package_text
        assert "This package does not choose among any candidate below." in package_text

    def test_all_three_records_reference_the_decision_package(self):
        for requirement_id in NEW_RECORD_IDS:
            record_path = (
                REPO_ROOT / "docs" / "approved_requirements" / f"{requirement_id}.md"
            )
            text = record_path.read_text()
            assert "wp1_search_seo_granularity_decision_package.md" in text, (
                f"{requirement_id} does not reference the companion decision package"
            )

    def test_decision_package_names_the_prd_decision_register_items(self):
        """The decision package must cite the PRD's own per-part
        decision-register item IDs (not invent new ones), so a future
        reviewer can trace each excluded item back to its exact PRD
        source."""
        package_text = DECISION_PACKAGE_PATH.read_text()
        for decision_item in (
            "DD-020",
            "MD-008A",
            "MD-008B",
            "MD-008C",
            "VL-032",
            "VL-033",
            "VL-034",
            "PL-027",
            "PL-028",
            "RP-030",
            "RP-031",
            "RP-032",
            "API-029",
            "FR-CAU-015",
        ):
            assert decision_item in package_text, (
                f"decision package does not cite PRD decision-register item {decision_item}"
            )

    def test_req_seo_001_records_approved_fit_role_and_open_estimand_direction(
        self,
    ):
        """The dated Decision 6 addendum approves the fit-time
        mediator/capture-efficiency role while retaining an explicit
        estimand-specific direction sentinel."""
        text = (
            REPO_ROOT / "docs" / "approved_requirements" / "REQ-SEO-001.md"
        ).read_text()
        normalised = " ".join(text.split())
        assert "not_yet_approved" in normalised
        assert (
            "Decision 6: causal role approved as `mediator_or_capture_efficiency_state`"
            in normalised
        )

    def test_req_search_005_defines_six_independent_eligibility_axes(self):
        text = (
            REPO_ROOT / "docs" / "approved_requirements" / "REQ-SEARCH-005.md"
        ).read_text()
        for axis in (
            "model_eligible",
            "contribution_eligible",
            "curve_eligible",
            "economics_eligible",
            "planning_eligible",
            "optimisation_eligible",
        ):
            assert axis in text, f"REQ-SEARCH-005 does not name eligibility axis {axis}"

    def test_wp1_update_present_without_rewriting_original_wp0_disclaimer(self):
        """Work Package 1's new subsection must coexist with, not replace,
        the original 2026-08-24 WP0 disclaimer text that
        `test_search_granularity_overlay_reconciliation.py` already pins -
        this repository's established pattern is to add a dated update,
        never rewrite an earlier point-in-time record."""
        content = AUTHORITY_PATH.read_text()
        overlay_section = content.split(
            "## Version history: focused optional Search granularity, "
            "Paid Search intent and SEO visibility overlay",
            1,
        )[1].split("## Historical status of earlier documents", 1)[0]

        # Original WP0 disclaimers must still be present, verbatim.
        normalised = " ".join(overlay_section.split())
        assert "approves no requirement, no statistical method, no causal" in normalised
        assert (
            "does not select, approve, or rule out any candidate approach" in normalised
        )
        assert "No `docs/approved_requirements/` record reconciles" in normalised

        # The new WP1 update subsection must also be present.
        assert (
            "### Work Package 1 update (2026-08-28): partial reconciliation "
            "into approved requirements" in overlay_section
        )
        assert "REQ-SEARCH-004" in overlay_section
        assert "REQ-SEARCH-005" in overlay_section
        assert "REQ-SEO-001" in overlay_section
        assert "No candidate in that package is chosen" in overlay_section

    def test_readme_documents_the_req_seo_category(self):
        readme_path = REPO_ROOT / "docs" / "approved_requirements" / "README.md"
        text = readme_path.read_text()
        assert "`REQ-SEO-*`" in text
