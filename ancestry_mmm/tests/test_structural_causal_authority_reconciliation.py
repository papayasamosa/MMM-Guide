"""Anti-drift tests for Work Package 0's structural-causal authority
reconciliation: `REQ-ENGINE-001`, `REQ-SCENGINE-001`, `REQ-SCEFFECT-001`,
`REQ-CAUSALROBUST-001`, `REQ-SCCURVE-001`, and the companion
`docs/wp_structural_causal_engine_decision_package.md`.

These tests check the reconciled *source/version scope this work package
actually reconciled* against the actual local PRD suite where present, and
against `docs/specification_authority.md`'s own recorded reconciliation
where the local PRD suite is not present (it is untracked, `.git/info/
exclude`-protected, and never available in CI). No test here hard-codes a
fabricated "full suite" version, and no test asserts a missing Part 5
v1.6's content - only that the gap is honestly recorded.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
AUTHORITY_PATH = REPO_ROOT / "docs" / "specification_authority.md"
DECISION_PACKAGE_PATH = REPO_ROOT / "docs" / "wp_structural_causal_engine_decision_package.md"
PRD_DIR = REPO_ROOT / "docs" / "PRD"


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


class TestStructuralCausalEngineOverlayReconciled:
    NEW_RECORD_IDS = (
        "REQ-ENGINE-001",
        "REQ-SCENGINE-001",
        "REQ-SCEFFECT-001",
        "REQ-CAUSALROBUST-001",
        "REQ-SCCURVE-001",
    )

    def test_all_five_records_indexed_and_files_exist(self):
        data = _load_index()
        for requirement_id in self.NEW_RECORD_IDS:
            req = _find_requirement(data, requirement_id)
            assert req["status"] == "approved_for_implementation"
            record_path = REPO_ROOT / req["record_path"]
            assert record_path.exists(), f"missing record file: {record_path}"

    def test_req_engine_001_indexed_and_no_meridian_import(self):
        """REQ-ENGINE-001 reconciles an already-true implementation fact
        (PyMC is the primary engine) - guard that the "zero migration
        impact" claim actually holds by confirming Meridian is not
        imported anywhere in the application package."""
        data = _load_index()
        _find_requirement(data, "REQ-ENGINE-001")

        ancestry_mmm_dir = REPO_ROOT / "ancestry_mmm"
        meridian_hits = []
        for py_file in ancestry_mmm_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("import meridian") or stripped.startswith(
                    "from meridian"
                ):
                    meridian_hits.append(str(py_file))
        assert not meridian_hits, (
            f"REQ-ENGINE-001 claims zero Meridian usage, but found import(s) in: {meridian_hits}"
        )

    def test_req_scengine_001_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-SCENGINE-001")

    def test_req_sceffect_001_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-SCEFFECT-001")

    def test_req_causalrobust_001_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-CAUSALROBUST-001")

    def test_req_sccurve_001_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-SCCURVE-001")

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

    def test_req_engine_001_named_in_implemented_section_not_gaps(self):
        """Unlike the other four, REQ-ENGINE-001 reconciles an
        already-resolved decision with zero implementation gap - it must
        appear in the "already implemented" section, never as its own row
        in the gaps table."""
        content = AUTHORITY_PATH.read_text()
        gaps_section = content.split(
            "## Current implementation gaps requiring decision records", 1
        )[1].split("## Approved requirement records already implemented", 1)[0]
        gap_rows = _markdown_table_rows(gaps_section)
        own_rows = [row for row in gap_rows if "REQ-ENGINE-001" in row[0]]
        assert not own_rows, (
            f"REQ-ENGINE-001 should not have its own row in the gaps table "
            f"(zero implementation gap): {own_rows}"
        )

        implemented_section = content.split(
            "## Approved requirement records already implemented", 1
        )[1]
        assert "REQ-ENGINE-001" in implemented_section

    def test_decision_package_exists_and_is_referenced(self):
        assert DECISION_PACKAGE_PATH.exists()
        package_text = DECISION_PACKAGE_PATH.read_text()
        # No candidate is chosen - the package must describe options without
        # picking one.
        assert "Status: decision support only" in package_text

    def test_decision_package_referenced_by_req_scengine_001(self):
        record_text = (
            REPO_ROOT / "docs" / "approved_requirements" / "REQ-SCENGINE-001.md"
        ).read_text()
        assert "wp_structural_causal_engine_decision_package.md" in record_text

    def test_all_four_target_state_records_reference_decision_package(self):
        for requirement_id in (
            "REQ-SCENGINE-001",
            "REQ-SCEFFECT-001",
            "REQ-CAUSALROBUST-001",
            "REQ-SCCURVE-001",
        ):
            record_path = (
                REPO_ROOT / "docs" / "approved_requirements" / f"{requirement_id}.md"
            )
            text = record_path.read_text()
            assert "wp_structural_causal_engine_decision_package.md" in text, (
                f"{requirement_id} does not reference the companion decision package"
            )

    def test_decision_package_names_the_prd_decision_register_items(self):
        """The decision package must cite the PRD's own decision-register
        item IDs (not invent new ones), so a future reviewer can trace each
        excluded item back to its exact PRD source."""
        package_text = DECISION_PACKAGE_PATH.read_text()
        for decision_item in ("MD-022", "VL-028", "VL-029", "UX-031", "UX-032", "UX-033"):
            assert decision_item in package_text, (
                f"decision package does not cite PRD decision-register item {decision_item}"
            )

    def test_overlay_table_covers_all_eleven_parts_without_fabricating_full_suite_bump(
        self,
    ):
        """The new "focused structural-causal engine integration overlay"
        table must record a full Part 1-11 row set, and must not claim
        Part 1, 2, or 5 moved to any version introduced by this overlay -
        those three remain retained/unreconciled by this specific overlay."""
        content = AUTHORITY_PATH.read_text()
        overlay_section = content.split(
            "## Version history: focused structural-causal engine integration overlay",
            1,
        )[1].split("## Historical status of earlier documents", 1)[0]
        rows = _markdown_table_rows(overlay_section)
        assert rows, "no rows parsed from the structural-causal overlay table"

        by_part = {cells[0]: cells[1] for cells in rows}
        assert set(by_part) == {f"Part {n}" for n in range(1, 12)}, sorted(by_part)

        # Parts actually reconciled by this overlay carry a "focused
        # overlay" version note.
        for part in ("Part 3", "Part 4", "Part 6", "Part 7", "Part 8", "Part 9", "Part 10", "Part 11"):
            assert "focused overlay" in by_part[part], (
                f"{part}'s row does not read as a focused overlay: {by_part[part]!r}"
            )

        # Parts NOT touched by this overlay must not be described as one.
        for part in ("Part 1", "Part 2", "Part 5"):
            assert "focused overlay" not in by_part[part], (
                f"{part}'s row falsely claims a focused overlay from this "
                f"reconciliation: {by_part[part]!r}"
            )

        # The exact reconciled version for each touched part - guards
        # against silently reconciling against a stale or fabricated
        # version label.
        expected_versions = {
            "Part 3": "v1.10",
            "Part 4": "v1.6",
            "Part 6": "v1.8",
            "Part 7": "v1.7",
            "Part 8": "v1.5",
            "Part 9": "v1.6",
            "Part 10": "v1.8",
            "Part 11": "v1.7",
        }
        for part, expected_version in expected_versions.items():
            assert expected_version in by_part[part], (
                f"{part}'s row is {by_part[part]!r}, expected to contain {expected_version!r}"
            )

    def test_known_version_reference_gap_records_part_5_only(self):
        """The reconciliation must explicitly record that Part 5 v1.6 is
        referenced-but-absent locally (only Part 5 v1.4 is present) -
        never silently promoting the present Part 5 v1.4 file, and never
        claiming the local PRD set is fully self-contained."""
        content = AUTHORITY_PATH.read_text()
        gaps_note_section = content.split("### Known version-reference gaps", 1)[1].split(
            "## Historical status of earlier documents", 1
        )[0]
        assert "Part 5 v1.6" in gaps_note_section
        assert "not supplied" in gaps_note_section
        assert "does not infer Part 5 v1.6" in gaps_note_section

    def test_part_9_row_notes_supersession_not_new_capability(self):
        """Part 9's version label advanced (v1.5 -> v1.6 focused overlay)
        purely for the structural-causal reporting alignment; the row must
        make clear this does not disturb the earlier validation overlay's
        already-approved capabilities (REQ-LEAK-001 etc.), consistent with
        how the Part 3 v1.6->v1.7 supersession was recorded earlier in the
        same document."""
        content = AUTHORITY_PATH.read_text()
        overlay_section = content.split(
            "## Version history: focused structural-causal engine integration overlay",
            1,
        )[1].split("## Historical status of earlier documents", 1)[0]
        assert "supersedes the v1.5 focused Bayesian-validation overlay" in overlay_section
        assert "REQ-LEAK-001" in overlay_section

    def test_local_prd_directory_remains_untracked_when_present(self):
        """If the local PRD traceability set happens to be present in this
        checkout (it never is in CI - untracked and `.git/info/exclude`-
        protected), it must not be staged/tracked by git. Skipped
        entirely when absent, which is the expected CI state."""
        if not PRD_DIR.exists():
            return  # expected in CI; nothing to check
        import subprocess

        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "docs/PRD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            "docs/PRD appears to be tracked by git - it must remain "
            "local-only traceability material, never committed"
        )
