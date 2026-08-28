"""Anti-drift tests for the outcome-valuation/joined-ROI authority,
architecture, and gap-analysis package: `REQ-ECON-001` and the companion
`docs/wp2_outcome_valuation_gap_analysis.md` /
`docs/wp2_outcome_valuation_decision_package.md`.

Unlike the Search/SEO and FX packages, `REQ-ECON-001` reconciles an
already-true, already-implemented fact (the existing CPA/ROI arithmetic
and value-join principle) rather than a target-state contract — mirroring
`REQ-ENGINE-001`'s precedent. These tests therefore check that
`REQ-ECON-001` is named in the "already implemented" section and carries
NO row of its own in the implementation-gaps table, while the broader,
genuinely unresolved outcome-valuation capability does carry its own gap
row pointing at the decision package.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
AUTHORITY_PATH = REPO_ROOT / "docs" / "specification_authority.md"
GAP_ANALYSIS_PATH = REPO_ROOT / "docs" / "wp2_outcome_valuation_gap_analysis.md"
DECISION_PACKAGE_PATH = REPO_ROOT / "docs" / "wp2_outcome_valuation_decision_package.md"


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


def _gaps_section() -> str:
    content = AUTHORITY_PATH.read_text()
    return content.split(
        "## Current implementation gaps requiring decision records", 1
    )[1].split("## Approved requirement records already implemented", 1)[0]


class TestOutcomeValuationAuthority:
    def test_req_econ_001_indexed_and_implemented(self):
        data = _load_index()
        req = _find_requirement(data, "REQ-ECON-001")
        assert req["status"] == "approved_for_implementation"
        record_path = REPO_ROOT / req["record_path"]
        assert record_path.exists(), f"missing record file: {record_path}"

    def test_req_econ_001_has_no_row_of_its_own_in_gaps_table(self):
        """Mirrors test_structural_causal_authority_reconciliation.py's
        REQ-ENGINE-001 precedent: a record reconciling an already-true,
        zero-migration-impact fact must not carry its own gaps-table row."""
        gap_rows = _markdown_table_rows(_gaps_section())
        own_rows = [row for row in gap_rows if "REQ-ECON-001" in row[0]]
        assert not own_rows, (
            f"REQ-ECON-001 should not have its own row in the gaps table "
            f"(zero implementation gap): {own_rows}"
        )

    def test_req_econ_001_named_in_implemented_section(self):
        content = AUTHORITY_PATH.read_text()
        implemented_section = content.split(
            "## Approved requirement records already implemented", 1
        )[1]
        assert "REQ-ECON-001" in implemented_section

    def test_broader_valuation_capability_has_its_own_unresolved_gap_row(self):
        """The value-input architecture itself (LTR, DNA revenue,
        week/segment variation, waterfall, value-FX) remains a genuine
        gap distinct from REQ-ECON-001's narrow, resolved arithmetic
        scope, and must be classified 'No approved requirement/decision
        yet' with its own row pointing at the decision package."""
        gap_rows = _markdown_table_rows(_gaps_section())
        value_rows = [
            row
            for row in gap_rows
            if "outcome valuation" in row[0].lower() and "waterfall" in row[0].lower()
        ]
        assert value_rows, (
            "no gaps-table row found for the outcome-valuation capability"
        )
        for row in value_rows:
            assert row[1] == "No approved requirement/decision yet", (
                f"outcome-valuation gap row is classified {row[1]!r}, expected "
                f"'No approved requirement/decision yet': {row}"
            )
            assert "wp2_outcome_valuation_decision_package.md" in row[2]

    def test_req_econ_001_reconciles_the_ratio_form_not_net_of_investment(self):
        """REQ-ECON-001 must explicitly reconcile ROI as a value/cost
        ratio and explicitly rule out a net-of-investment (value -
        cost)/cost alternative — guards against a future edit silently
        redefining the approved formula."""
        text = (
            REPO_ROOT / "docs" / "approved_requirements" / "REQ-ECON-001.md"
        ).read_text()
        normalised = " ".join(text.split())
        assert "incremental_outcome * value_per_unit / spend" in normalised
        assert "never a net-of-investment" in normalised

    def test_gap_analysis_and_decision_package_exist(self):
        assert GAP_ANALYSIS_PATH.exists()
        assert DECISION_PACKAGE_PATH.exists()

    def test_decision_package_makes_no_decision(self):
        package_text = DECISION_PACKAGE_PATH.read_text()
        assert "This package does not choose among any candidate below." in package_text
        assert "Status: decision support only." in package_text

    def test_decision_package_resolves_roi_definition_explicitly(self):
        """The decision package must explicitly record the ROI-definition
        check the task required (ratio vs net-of-investment), not merely
        omit it as though it were never asked."""
        package_text = DECISION_PACKAGE_PATH.read_text()
        assert "D0." in package_text
        normalised = " ".join(package_text.split())
        assert "resolved, not decision-bound" in normalised

    def test_decision_package_names_the_prd_decision_register_items(self):
        package_text = DECISION_PACKAGE_PATH.read_text()
        for decision_item in (
            "DD-013",
            "MD-018",
            "MD-019",
            "MD-011",
            "PL-015",
            "PL-007",
            "PL-016",
            "PL-021",
            "RP-005",
            "RP-007",
            "RP-009",
            "VL-019",
            "API-018",
        ):
            assert decision_item in package_text, (
                f"decision package does not cite PRD decision-register item {decision_item}"
            )

    def test_req_econ_001_references_the_decision_package(self):
        text = (
            REPO_ROOT / "docs" / "approved_requirements" / "REQ-ECON-001.md"
        ).read_text()
        assert "wp2_outcome_valuation_decision_package.md" in text

    def test_readme_documents_the_req_econ_category(self):
        readme_path = REPO_ROOT / "docs" / "approved_requirements" / "README.md"
        text = readme_path.read_text()
        assert "`REQ-ECON-*`" in text

    def test_gap_analysis_flags_ltr_absent_from_codebase_and_prd(self):
        """Guards against a future edit silently asserting an LTR
        definition exists somewhere — the gap analysis's own confirmed
        finding is that the literal term never appears in either source."""
        text = GAP_ANALYSIS_PATH.read_text()
        assert '"LTR" appears nowhere' in text
