"""Anti-drift tests for the outcome-valuation/joined-ROI authority,
architecture, and gap-analysis package: `REQ-ECON-001` through
`REQ-ECON-004` and the companion
`docs/wp2_outcome_valuation_gap_analysis.md` /
`docs/wp2_outcome_valuation_decision_package.md`.

`REQ-ECON-001` reconciles an already-true, already-implemented fact (the
existing CPA/ROI arithmetic and value-join principle) rather than a
target-state contract — mirroring `REQ-ENGINE-001`'s precedent. It
carries no row of its own in the implementation-gaps table.

`REQ-ECON-002` (input contract), `REQ-ECON-003` (rate-derivation/
posterior-join contract), and `REQ-ECON-004` (reporting-period/
aggregation/comparison contract) reconcile the 2026-08-28 business-
decision brief "Outcome valuation and time-varying ROI: approved
business decisions," which closed most of the original decision
package's D1-D10. Each target-state record carries its own gaps-table
row ("Requirement exists but capability incomplete"), since none has
been implemented yet (WP2A-WP2E remain future PRs). Only two items
remain genuinely unresolved after the business-decision update — the
waterfall's exact computation method (D5) and FX conversion policy (D7)
— and they share one narrower gap-table row, since neither is covered
by any `REQ-ECON-*` record.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
AUTHORITY_PATH = REPO_ROOT / "docs" / "specification_authority.md"
GAP_ANALYSIS_PATH = REPO_ROOT / "docs" / "wp2_outcome_valuation_gap_analysis.md"
DECISION_PACKAGE_PATH = REPO_ROOT / "docs" / "wp2_outcome_valuation_decision_package.md"

TARGET_STATE_RECORD_IDS = ("REQ-ECON-002", "REQ-ECON-003", "REQ-ECON-004")


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


def _record_text(requirement_id: str) -> str:
    return (
        REPO_ROOT / "docs" / "approved_requirements" / f"{requirement_id}.md"
    ).read_text()


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


def _gap_row_for(requirement_id: str) -> list[str]:
    gap_rows = _markdown_table_rows(_gaps_section())
    own_rows = [row for row in gap_rows if requirement_id in row[0]]
    assert own_rows, f"no implementation-gaps row references {requirement_id}"
    return own_rows[0]


class TestOutcomeValuationAuthority:
    # -- REQ-ECON-001 (already-true reconciliation, no gap row) ---------

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

    def test_req_econ_001_reconciles_the_ratio_form_not_net_of_investment(self):
        """REQ-ECON-001 must explicitly reconcile ROI as a value/cost
        ratio and explicitly rule out a net-of-investment (value -
        cost)/cost alternative — guards against a future edit silently
        redefining the approved formula."""
        normalised = " ".join(_record_text("REQ-ECON-001").split())
        assert "incremental_outcome * value_per_unit / spend" in normalised
        assert "never a net-of-investment" in normalised

    def test_req_econ_001_approves_monetary_presentation(self):
        """The 2026-08-28 revision must add the monetary ROI-presentation
        requirement (item 11 of the business-decision brief) without
        altering the original arithmetic requirements."""
        normalised = " ".join(_record_text("REQ-ECON-001").split())
        assert "### 7. Monetary presentation" in normalised
        assert "returned per" in normalised
        assert "Revision history" in normalised

    def test_req_econ_001_references_the_decision_package(self):
        assert "wp2_outcome_valuation_decision_package.md" in _record_text(
            "REQ-ECON-001"
        )

    # -- REQ-ECON-002/003/004 (target-state, each its own gap row) ------

    def test_all_three_target_state_records_indexed_and_files_exist(self):
        data = _load_index()
        for requirement_id in TARGET_STATE_RECORD_IDS:
            req = _find_requirement(data, requirement_id)
            assert req["status"] == "approved_for_implementation"
            record_path = REPO_ROOT / req["record_path"]
            assert record_path.exists(), f"missing record file: {record_path}"

    def test_req_econ_002_indexed_and_classified_incomplete(self):
        row = _gap_row_for("REQ-ECON-002")
        assert row[1] == "Requirement exists but capability incomplete", row

    def test_req_econ_003_indexed_and_classified_incomplete(self):
        row = _gap_row_for("REQ-ECON-003")
        assert row[1] == "Requirement exists but capability incomplete", row

    def test_req_econ_004_indexed_and_classified_incomplete(self):
        row = _gap_row_for("REQ-ECON-004")
        assert row[1] == "Requirement exists but capability incomplete", row

    def test_all_three_target_state_records_named_in_implemented_section(self):
        content = AUTHORITY_PATH.read_text()
        implemented_section = content.split(
            "## Approved requirement records already implemented", 1
        )[1]
        for requirement_id in TARGET_STATE_RECORD_IDS:
            assert requirement_id in implemented_section

    def test_req_econ_002_never_defaults_fh_denominator(self):
        """Guards against a future edit silently hard-coding GSA (or any
        other outcome) as the FH LTR denominator — the business decision
        explicitly forbids this."""
        normalised = " ".join(_record_text("REQ-ECON-002").split())
        assert "No default denominator is authorised by this record" in normalised
        assert "Do not arbitrarily substitute GSA" in normalised

    def test_req_econ_002_requires_never_inferred_currency(self):
        normalised = " ".join(_record_text("REQ-ECON-002").split())
        assert "Never infer currency from market" in normalised

    def test_req_econ_003_requires_weekly_grain_before_aggregation(self):
        """Guards against a regression to computing period totals by
        multiplying a total incremental outcome by an average rate,
        which the business decision explicitly forbids."""
        normalised = " ".join(_record_text("REQ-ECON-003").split())
        assert "Never calculate historical quarterly" in normalised
        assert (
            "by multiplying total incremental outcomes by a simple "
            "average LTR/revenue rate" in normalised
        )

    def test_req_econ_003_fixes_value_uncertainty_treatment(self):
        normalised = " ".join(_record_text("REQ-ECON-003").split())
        assert (
            "Do not manufacture uncertainty around those supplied values" in normalised
        )
        assert "summarize_distribution" in normalised

    def test_req_econ_004_forbids_partial_period_scaling(self):
        normalised = " ".join(_record_text("REQ-ECON-004").split())
        assert "Do not annualise or scale partial periods to full periods" in normalised
        assert "Q1 Jan-Mar" in normalised

    def test_req_econ_004_excludes_the_waterfall(self):
        normalised = " ".join(_record_text("REQ-ECON-004").split())
        assert "Explicitly not covered" in normalised
        assert "gated behind a required design note" in normalised

    def test_all_three_target_state_records_reference_the_decision_package(self):
        for requirement_id in TARGET_STATE_RECORD_IDS:
            assert "wp2_outcome_valuation_decision_package.md" in _record_text(
                requirement_id
            )

    # -- The narrower remaining gap row (waterfall method + FX policy) --

    def test_remaining_waterfall_and_fx_gap_has_its_own_unresolved_row(self):
        """After the business-decision update, only the waterfall's exact
        computation method and FX conversion policy remain genuinely
        unresolved. This row must stay classified 'No approved
        requirement/decision yet' since no REQ-ECON-* record covers
        either."""
        gap_rows = _markdown_table_rows(_gaps_section())
        matching = [
            row
            for row in gap_rows
            if "waterfall" in row[0].lower() and "fx" in row[0].lower()
        ]
        assert matching, (
            "no gaps-table row found for the waterfall-method/FX-policy gap"
        )
        for row in matching:
            assert row[1] == "No approved requirement/decision yet", (
                f"waterfall/FX gap row is classified {row[1]!r}, expected "
                f"'No approved requirement/decision yet': {row}"
            )
            assert "wp2_outcome_valuation_decision_package.md" in row[2]

    # -- Decision package: business decisions recorded -------------------

    def test_decision_package_exists(self):
        assert GAP_ANALYSIS_PATH.exists()
        assert DECISION_PACKAGE_PATH.exists()

    def test_decision_package_records_business_decisions_approved_section(self):
        package_text = DECISION_PACKAGE_PATH.read_text()
        assert "## Business decisions approved (2026-08-28)" in package_text
        for closed_item in ("D1", "D2", "D3", "D4", "D6", "D8", "D9", "D10"):
            assert f"### {closed_item} " in package_text, (
                f"decision package does not record a resolution heading for {closed_item}"
            )

    def test_decision_package_leaves_d5_and_d7_open(self):
        normalised = " ".join(DECISION_PACKAGE_PATH.read_text().split())
        assert (
            "D5 (waterfall computation method) and D7 (FX conversion policy) remain"
            in normalised
        )
        assert (
            "D7" in normalised and "remains open, Finance-owned, blocked" in normalised
        )

    def test_decision_package_original_analysis_not_rewritten(self):
        """The original D1-D10 candidate analysis and PRD-citation block
        must still be present verbatim as the historical record, even
        though most items are now resolved — mirrors this repository's
        established 'add a dated update, never rewrite' convention."""
        package_text = DECISION_PACKAGE_PATH.read_text()
        assert "This package does not choose among any candidate below." in package_text
        assert "Candidate D1-A" in package_text
        assert "Candidate D7-B" in package_text

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

    def test_gap_analysis_notes_decisions_approved(self):
        text = GAP_ANALYSIS_PATH.read_text()
        assert "2026-08-28 update" in text
        assert "wp2_outcome_valuation_decision_package.md" in text
