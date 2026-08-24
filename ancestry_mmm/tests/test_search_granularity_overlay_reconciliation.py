"""Anti-drift tests for Work Package 0's optional Search granularity, Paid
Search intent and SEO visibility overlay reconciliation (2026-08-24).

This work package is a version/traceability reconciliation pass only. It
does not create or approve any new `docs/approved_requirements/` record,
does not select any candidate SEO-visibility identification strategy or
child-cost allocation policy, and does not implement any Search/SEO
granularity behaviour. These tests check that `docs/specification_
authority.md` records the new consolidated PRD version map and the new
overlay's per-part table honestly, closes the previously-recorded Part 5
v1.6 "absent" gap as a documentation fact without rewriting the earlier
overlays' own point-in-time records, and does not overclaim reconciliation
or approval anywhere in the new sections.

The local PRD suite is untracked (`.git/info/exclude`-protected) and never
available in CI, so no test here opens a PRD file or hard-codes fabricated
PRD content - only that the recorded source identities and invariants are
honestly recorded in the tracked authority documents.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
AUTHORITY_PATH = REPO_ROOT / "docs" / "specification_authority.md"
REQ_PREFIT_001_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-PREFIT-001.md"
GRAPHIFYIGNORE_PATH = REPO_ROOT / ".graphifyignore"


def _load_index() -> dict:
    return json.loads(INDEX_PATH.read_text())


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


class TestConsolidatedVersionMap:
    def _section(self) -> str:
        content = AUTHORITY_PATH.read_text()
        return content.split("## Current consolidated PRD version map", 1)[1].split(
            "## Version history: v1.4 to v1.5", 1
        )[0]

    def test_old_suite_table_retained_and_marked_historical(self):
        """The original 'Current PRD suite' table (v1.5, 28 July 2026) is
        not deleted or rewritten - it is marked superseded as a
        current-state description and pointed at the new map."""
        content = AUTHORITY_PATH.read_text()
        suite_section = content.split("## Current PRD suite", 1)[1].split(
            "## Current consolidated PRD version map", 1
        )[0]
        assert "Cross-Document Coherent v1.5" in suite_section
        assert "superseded" in suite_section

    def test_consolidated_map_states_every_part_version(self):
        rows = {cells[0]: cells[1] for cells in _markdown_table_rows(self._section())}
        expected = {
            "Part 1": "v1.4",
            "Part 2": "v1.5",
            "Part 3": "v1.13",
            "Part 4": "v1.8",
            "Part 5": "v1.6",
            "Part 6": "v1.11",
            "Part 7": "v1.10",
            "Part 8": "v1.6",
            "Part 9": "v1.7",
            "Part 10": "v1.8",
            "Part 11": "v1.8",
        }
        assert set(rows) == {f"Part {n}" for n in range(1, 12)}, sorted(rows)
        for part, version in expected.items():
            assert rows[part] == version, (
                f"{part} row is {rows[part]!r}, expected exactly {version!r}"
            )

    def test_fx_addendum_referenced_without_claiming_reconciliation(self):
        section = self._section()
        assert "Governed FX Translation" in section
        assert "REQ-FX-001" in section
        assert "remains unreconciled" in section

    def test_map_disclaims_approval_and_implementation(self):
        section = self._section()
        assert "does not itself approve, reject, or implement" in section
        assert "out of scope for" in section


class TestSearchGranularityOverlayReconciled:
    def _overlay_section(self) -> str:
        content = AUTHORITY_PATH.read_text()
        return content.split(
            "## Version history: focused optional Search granularity, Paid Search intent and SEO visibility overlay",
            1,
        )[1].split("## Historical status of earlier documents", 1)[0]

    def test_overlay_table_states_every_part_and_part1_untouched(self):
        rows = {
            cells[0]: cells[1]
            for cells in _markdown_table_rows(self._overlay_section())
        }
        assert set(rows) == {f"Part {n}" for n in range(1, 12)}, sorted(rows)
        assert "Retained" in rows["Part 1"]
        assert "focused overlay" not in rows["Part 1"]

        expected_versions = {
            "Part 2": "v1.5",
            "Part 3": "v1.13",
            "Part 4": "v1.8",
            "Part 5": "v1.6",
            "Part 6": "v1.11",
            "Part 7": "v1.10",
            "Part 8": "v1.6",
            "Part 9": "v1.7",
            "Part 10": "v1.8",
            "Part 11": "v1.8",
        }
        for part, version in expected_versions.items():
            assert "focused overlay" in rows[part], (
                f"{part}'s row does not read as a focused overlay: {rows[part]!r}"
            )
            assert version in rows[part], (
                f"{part}'s row is {rows[part]!r}, expected to contain {version!r}"
            )

    def test_overlay_does_not_claim_approval_or_selection(self):
        # Normalise Markdown hard-wrapping before substring checks - the
        # source prose wraps mid-sentence for readability.
        section = " ".join(self._overlay_section().split())
        assert "approves no requirement, no statistical method, no causal" in section
        assert "does not select, approve, or rule out any candidate approach" in section
        assert "No `docs/approved_requirements/` record reconciles" in section

    def test_part8_v16_distinguished_from_earlier_part8_v15_collision(self):
        """Part 8's new v1.6 label must not be confused with the earlier
        recorded 'two distinct Part 8 v1.5 sources' collision - the
        consolidated map's Part 8 row must reference the earlier
        source-collision note rather than silently reusing an ambiguous
        label."""
        content = AUTHORITY_PATH.read_text()
        map_section = content.split("## Current consolidated PRD version map", 1)[
            1
        ].split("## Version history: v1.4 to v1.5", 1)[0]
        assert "source-collision note below" in " ".join(map_section.split())

    def test_prefit_sub_overlay_noted_without_claiming_req_prefit_001_on_main(self):
        """The pre-fit diagnostics sub-overlay (Part 3 v1.12 etc.) is noted
        as a distinct, earlier sub-overlay whose reconciliation vehicle
        (REQ-PREFIT-001) is proposed on an open pull request only - not yet
        present on `main`. This test also pins that fact in the index/
        filesystem so a future merge of that PR is forced to update this
        record rather than silently going stale."""
        section = self._overlay_section()
        assert "REQ-PREFIT-001" in section
        assert "does not exist on `main`" in section
        assert not REQ_PREFIT_001_PATH.exists(), (
            "REQ-PREFIT-001.md now exists on this branch/main - the pre-fit "
            "sub-overlay note in docs/specification_authority.md must be "
            "updated (it currently asserts the record is not yet on main) "
            "as part of whatever work package merged it."
        )
        data = _load_index()
        prefit_ids = [
            req["requirement_id"]
            for req in data["requirements"]
            if req["requirement_id"] == "REQ-PREFIT-001"
        ]
        assert not prefit_ids, (
            "REQ-PREFIT-001 is now indexed - update the pre-fit sub-overlay "
            "note in docs/specification_authority.md to match."
        )

    def test_part5_v16_closure_note_present_in_overlay_section(self):
        section = self._overlay_section()
        assert (
            "### Known version-reference gaps: Part 5 v1.6 gap closed as a documentation fact"
            in section
        )
        assert "supplied locally" in section


class TestGraphifyExcludesLocalPrd:
    def test_graphifyignore_excludes_docs_prd(self):
        content = GRAPHIFYIGNORE_PATH.read_text()
        assert "docs/PRD/" in content
