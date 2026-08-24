"""Anti-drift tests for Work Package 0's governed named-event authority
reconciliation: `REQ-EVENT-001`, `REQ-EVENT-002`, and the companion
`docs/wp2_named_event_statistical_method_decision_package.md`.

These tests check the reconciled *source/version scope this work
package actually reconciled* against `docs/specification_authority.md`'s
own recorded reconciliation. The local PRD suite is untracked
(`.git/info/exclude`-protected) and never available in CI, so no test
here opens a PRD file and no test hard-codes fabricated PRD content -
only that the recorded source identities (part/version/focused-update
title/filename/hash prefix) and invariants are honestly recorded in the
tracked authority documents.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
AUTHORITY_PATH = REPO_ROOT / "docs" / "specification_authority.md"
DECISION_PACKAGE_PATH = (
    REPO_ROOT / "docs" / "wp2_named_event_statistical_method_decision_package.md"
)
REQ_EVENT_001_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-EVENT-001.md"
REQ_EVENT_002_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-EVENT-002.md"

# Closed temporal-treatment vocabulary approved by REQ-EVENT-001, in the
# order the record defines it. Kept here (not re-derived from the
# record's prose) so a regression that collapses or reorders the set is
# caught by a structured comparison.
_CANONICAL_EVENT_TREATMENTS = (
    "contemporaneous",
    "anticipatory",
    "post_event",
    "anticipatory_and_post_event",
)


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


class TestNamedEventOverlayReconciled:
    NEW_RECORD_IDS = ("REQ-EVENT-001", "REQ-EVENT-002")

    def test_all_named_event_records_indexed_and_files_exist(self):
        data = _load_index()
        for requirement_id in self.NEW_RECORD_IDS:
            req = _find_requirement(data, requirement_id)
            assert req["status"] == "approved_for_implementation"
            record_path = REPO_ROOT / req["record_path"]
            assert record_path.exists(), f"missing record file: {record_path}"

    def test_req_event_001_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-EVENT-001")

    def test_req_event_002_indexed_and_classified_incomplete(self):
        self._assert_gap_row_classified_incomplete("REQ-EVENT-002")

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

    def test_authority_records_named_event_overlay_per_part(self):
        """specification_authority.md records the named-event overlay with
        a per-part version table: Part 3 v1.11, Part 5 v1.5, Part 6 v1.9,
        Part 7 v1.8, Part 8 v1.5 (named-event), Part 10 v1.6, Part 11
        v1.6 - and explicitly does not move Parts 1, 2, 4, 9."""
        content = AUTHORITY_PATH.read_text()
        overlay_section = content.split(
            "## Version history: focused governed named-event overlay", 1
        )[1].split("### Known version-reference gaps", 1)[0]
        rows = {
            cells[0]: cells[1]
            for cells in _markdown_table_rows(overlay_section)
            if cells
        }
        assert rows["Part 3"] == "v1.11 focused overlay"
        assert rows["Part 5"] == "v1.5 focused overlay"
        assert rows["Part 6"] == "v1.9 focused overlay"
        assert rows["Part 7"] == "v1.8 focused overlay"
        assert rows["Part 8"] == "v1.5 focused overlay (named-event scenario replay)"
        assert rows["Part 10"] == "v1.6 focused overlay (named-event UX)"
        assert (
            rows["Part 11"]
            == "v1.6 focused overlay (named-event service/API contracts)"
        )
        for retained in ("Part 1", "Part 2", "Part 4", "Part 9"):
            assert "Retained" in rows[retained], f"{retained} row: {rows[retained]}"

    def test_part8_v15_source_collision_recorded_with_both_identities(self):
        """The Part 8 v1.5 label denotes two distinct focused updates.
        specification_authority.md must record both focused-update titles
        and both filenames, and must not downgrade the structural-causal
        v1.8/v1.7 Part 10/11 overlays."""
        content = AUTHORITY_PATH.read_text()
        # Markdown prose wraps; check the two focus titles as wrapped
        # fragments rather than one exact long string.
        assert "structural intervention curves" in content
        assert "causal-engine use" in content
        assert "governed named-event scenario replay" in content
        assert (
            "Ancestry_MMM_PRD_Part_8_Coherent_v1_5_Governed_Named_Event_Scenario_Replay.md"
            in content
        )
        assert "837858F9BCEF6AF0" in content
        assert "REQ-SCCURVE-001" in content
        assert "Part 10 v1.8" in content and "Part 11 v1.7" in content

    def test_part5_gap_updated_without_claiming_v16(self):
        """The stale 'only Part 5 v1.4 is present' statement is updated to
        record Part 5 v1.5 as supplied, while Part 5 v1.6 remains absent
        (as recorded at this overlay's own 2026-08-19 reconciliation date)
        and is not claimed to have existed at that time."""
        content = AUTHORITY_PATH.read_text()
        gaps_subsection = content.split("### Known version-reference gaps", 1)[1]
        assert "Part 5 v1.5" in gaps_subsection
        assert "only Part 5 v1.4 is present" not in content
        assert (
            "Part 5 v1.6" in gaps_subsection and "remains absent" in gaps_subsection
        ) or ("Part 5 v1.6 remains" in gaps_subsection and "absent" in gaps_subsection)

    def test_part5_v16_gap_later_closed_without_rewriting_history(self):
        """A later (2026-08-24) reconciliation pass supplied Part 5 v1.6
        locally. That later record must say so explicitly - closing the gap
        as a documentation fact - without deleting or rewriting this
        overlay's own honest 2026-08-19 'referenced but absent' record."""
        content = AUTHORITY_PATH.read_text()
        closure_section = content.split(
            "### Known version-reference gaps: Part 5 v1.6 gap closed as a documentation fact",
            1,
        )[1]
        assert "supplied locally" in closure_section
        assert "closing that specific gap as" in closure_section
        assert "does not retroactively approve or\nreconcile Part 5 v1.6" in closure_section or (
            "does not retroactively approve" in closure_section
            and "Part 5 v1.6" in closure_section
        )
        # The original 2026-08-19 "remains absent" record must still be
        # present verbatim elsewhere in the document - history is not
        # rewritten just because a later pass closed the gap.
        gaps_subsection = content.split("### Known version-reference gaps", 1)[1]
        assert "Part 5 v1.6" in gaps_subsection and "remains absent" in gaps_subsection

    def test_part9_named_event_reporting_not_invented(self):
        """Part 9 v1.6 Final contains no dedicated named-event reporting
        contract; the reconciliation must say so rather than invent one."""
        content = AUTHORITY_PATH.read_text()
        overlay_section = content.split(
            "## Version history: focused governed named-event overlay", 1
        )[1].split("### Known version-reference gaps", 1)[0]
        assert "no dedicated named-event reporting contract" in overlay_section
        assert "Part 9" in overlay_section

    def test_req_event_001_records_closed_temporal_vocabulary(self):
        """REQ-EVENT-001 section 3 records exactly the four approved
        treatments in a fenced list - no more, no fewer."""
        record = REQ_EVENT_001_PATH.read_text()
        section = record.split("### 3. Closed temporal-treatment vocabulary", 1)[1]
        section = section.split("### 4.", 1)[0]
        fenced = [s for s in section.split("```")[1::2]]
        assert fenced, "no fenced vocabulary block found in section 3"
        raw_tokens = [line.strip() for line in fenced[0].splitlines() if line.strip()]
        # Drop the fence info string (`text`) - only the fence body is the
        # governed vocabulary. The four treatments are all-lowercase, so
        # filter on the known info string, never on lowercase-ness.
        tokens = [t for t in raw_tokens if t != "text"]
        assert tuple(tokens) == _CANONICAL_EVENT_TREATMENTS, (
            f"temporal-treatment vocabulary mismatch: got {tuple(tokens)}, "
            f"expected {_CANONICAL_EVENT_TREATMENTS}"
        )

    def test_req_event_001_records_no_reverse_adstock_no_text_inference(self):
        """REQ-EVENT-001 must record the factual-date, no-reverse-adstock,
        no-text-inference and separation invariants verbatim enough for a
        reviewer to find them."""
        record = REQ_EVENT_001_PATH.read_text()
        assert "never be shifted earlier" in record
        assert "never reverse media\nadstock" in record
        assert "never be inferred solely from free-text" in record
        assert "never conflated with the occurrence or the definition" in record
        assert "separate model artefacts governed by Part 6" in record

    def test_req_event_002_records_fixed_dates_non_decision(self):
        """REQ-EVENT-002 must record that fixed external calendar dates
        are non-decision context the optimiser must not move, and that
        deliberate variation is an explicit sensitivity case."""
        record = REQ_EVENT_002_PATH.read_text()
        # Normalise prose wrapping before asserting sentence fragments.
        flattened = " ".join(record.split())
        assert "non-decision context" in flattened
        assert "must not choose or move fixed calendar event dates" in flattened
        assert "explicit sensitivity" in flattened

    def test_decision_package_exists_and_selects_no_candidate(self):
        assert DECISION_PACKAGE_PATH.exists()
        content = DECISION_PACKAGE_PATH.read_text()
        assert "decision support only" in content
        assert (
            "no candidate approach below is enabled, selected, or implemented"
            in content
        )
        for required in (
            "S1 - Fixed governed profile",
            "S2 - Low-dimensional parametric kernel",
            "S3 - Regularised distributed basis",
            "S4 - Unconstrained weekly lead/lag dummies",
        ):
            assert required in content, (
                f"decision package missing candidate row {required!r}"
            )
        assert "Work Package 2" in content
