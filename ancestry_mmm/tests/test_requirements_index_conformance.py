"""G2A.7a.1 (REQ-AUTH-001, section 13.2): executable conformance check for
`docs/approved_requirements/index.json` - every `required_tests` entry must
be a real, collectable pytest node, not a shortened path pytest cannot
resolve. Uses a single batched `pytest --collect-only` invocation rather
than one subprocess per node.
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

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *all_nodes],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            "One or more index.json required_tests node(s) failed to collect:\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
