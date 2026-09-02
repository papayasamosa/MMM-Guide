"""G2A.7a.1 (REQ-AUTH-001, section 13.2): executable conformance check for
`docs/approved_requirements/index.json` - every `required_tests` entry must
be a real, collectable pytest node, not a shortened path pytest cannot
resolve. Uses batched `pytest --collect-only` invocations (chunked well
under the OS command-line length limit - Windows' `CreateProcess` caps a
command line at 32767 characters, and this repository's `required_tests`
list has grown past what fits in a single invocation) rather than one
subprocess per node.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"


def _load_index() -> dict:
    return json.loads(INDEX_PATH.read_text())


def test_requirement_ids_are_unique():
    data = _load_index()
    ids = [req["requirement_id"] for req in data["requirements"]]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"Duplicate requirement_id(s): {duplicates}"


def test_every_record_path_exists():
    data = _load_index()
    missing = [
        req["record_path"]
        for req in data["requirements"]
        if not (REPO_ROOT / req["record_path"]).exists()
    ]
    assert not missing, f"Missing requirement record file(s): {missing}"


def test_every_indexed_test_node_is_collectable():
    """Every `required_tests` entry must be a full, collectable pytest node
    id (`path/to/test_file.py::Class::test_name` or
    `path/to/test_file.py::test_name`), not a shortened `test_file.py::test_name`
    pytest cannot resolve from the repository root."""
    data = _load_index()
    all_nodes = sorted(
        {node for req in data["requirements"] for node in req.get("required_tests", [])}
    )
    assert all_nodes, "index.json lists no required_tests at all"

    # Every node must start with a real path pytest can resolve from repo
    # root - reject the old shortened "test_file.py::test_name" form (no
    # ancestry_mmm/tests/ prefix) up front with a clear message, rather than
    # letting it silently fail collection alongside genuine typos.
    malformed = [
        n
        for n in all_nodes
        if "::" not in n or not n.split("::")[0].startswith("ancestry_mmm/")
    ]
    assert not malformed, (
        f"Non-fully-qualified test node id(s) in index.json: {malformed}"
    )

    # Batch into chunks well under Windows' ~32767-character CreateProcess
    # command-line limit (a single invocation with the full node list
    # already exceeds this once `required_tests` grows past a few hundred
    # entries - confirmed 2026-08-30 at 357 nodes / ~44KB). 100 nodes per
    # batch keeps every batch's assembled command line comfortably under
    # the limit even for long node ids, while still using real subprocess
    # collection (not the in-process pytest API) so this test observes the
    # same collection behaviour a CI invocation would.
    batch_size = 100
    failures = []
    for start in range(0, len(all_nodes), batch_size):
        batch = all_nodes[start : start + batch_size]
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *batch],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            failures.append(
                f"Batch {start}-{start + len(batch)} failed to collect:\n"
                f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
            )
    if failures:
        pytest.fail(
            "One or more index.json required_tests node(s) failed to collect:\n"
            + "\n".join(failures)
        )


# REQ-COVERAGE-001's exact FR-* trace set, as supplied by the task-specific
# implementation brief that created the record - kept here (not re-derived
# from the record's Markdown prose) so a regression that silently drops or
# adds a trace target in index.json is caught by a structured field
# comparison, not a substring search of the record file.
_REQ_COVERAGE_001_REQUIRED_TRACES = frozenset(
    {
        "FR-DAT-006",
        "FR-DAT-010",
        "FR-DAT-011",
        "FR-QLT-010",
        "FR-QLT-011",
        "FR-QLT-012",
        "FR-TRN-003",
        "FR-TRN-004",
        "FR-TRN-005",
        "FR-TRN-013",
        "FR-TRN-014",
        "FR-TRN-015",
        "FR-TRN-016",
        "FR-TRN-017",
        "FR-VAR-006",
        "FR-MOD-015",
        "Part 3 v1.6 acceptance scenario 26.2",
    }
)

_CANONICAL_MISSINGNESS_STATES = (
    "observed_zero",
    "missing_expected",
    "not_applicable",
    "unavailable_source",
    "suppressed",
    "estimated",
    "modelled",
    "unknown",
)


def _find_requirement(data: dict, requirement_id: str) -> dict:
    matches = [
        req for req in data["requirements"] if req["requirement_id"] == requirement_id
    ]
    assert len(matches) == 1, (
        f"expected exactly one {requirement_id} entry, found {len(matches)}"
    )
    return matches[0]


def test_req_coverage_001_traces_to_matches_brief_fr_ids():
    """REQ-COVERAGE-001: index.json's `traces_to` field for the record must
    match the brief's exact FR-* trace set - no more, no fewer - checked as
    a structured field, not by grepping the record's prose."""
    data = _load_index()
    req = _find_requirement(data, "REQ-COVERAGE-001")
    traces_to = req.get("traces_to")
    assert traces_to, "REQ-COVERAGE-001 has no traces_to field in index.json"
    assert set(traces_to) == _REQ_COVERAGE_001_REQUIRED_TRACES, (
        f"traces_to mismatch: missing={_REQ_COVERAGE_001_REQUIRED_TRACES - set(traces_to)}, "
        f"unexpected={set(traces_to) - _REQ_COVERAGE_001_REQUIRED_TRACES}"
    )


def test_req_coverage_001_missingness_states_match_canonical_vocabulary():
    """REQ-COVERAGE-001: index.json's `missingness_states` field must
    exactly match Part 3 v1.6's canonical eight-state vocabulary, in the
    order the brief and the record define it - a collapsed or reordered set
    would silently change what a dependent requirement is allowed to
    represent."""
    data = _load_index()
    req = _find_requirement(data, "REQ-COVERAGE-001")
    states = req.get("missingness_states")
    assert states, "REQ-COVERAGE-001 has no missingness_states field in index.json"
    assert tuple(states) == _CANONICAL_MISSINGNESS_STATES, (
        f"missingness_states mismatch: got {tuple(states)}, "
        f"expected {_CANONICAL_MISSINGNESS_STATES}"
    )
