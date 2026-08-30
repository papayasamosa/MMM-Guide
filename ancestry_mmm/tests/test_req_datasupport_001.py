"""Anti-drift tests for `REQ-DATASUPPORT-001` (business-decision brief
Decision 17: evidence-based per-channel data-support classification).
Target-state contract only - no numeric threshold is approved here."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-DATASUPPORT-001.md"

_EVIDENCE_DIMENSIONS = (
    "total observed weeks",
    "non-zero",
    "separate activity periods",
    "spend/exposure variation",
    "long runs of zeros",
    "missingness",
    "collinearity",
    "correlation with trend/seasonality",
    "market coverage",
    "segment coverage",
    "changes in scale",
    "adstock/saturation",
)

_PRACTICAL_STATES = (
    "sufficient to attempt estimation",
    "weak/support-limited",
    "not sufficient for a separate coefficient",
)


def test_three_state_classification_named_and_no_threshold_invented():
    text = " ".join(REQ_PATH.read_text().replace("**", "").split())
    for state in _PRACTICAL_STATES:
        assert state in text
    assert "No universal numeric rule" in text
    assert "does not perform" in text  # the evidence-gathering exclusion


def test_all_twelve_evidence_dimensions_named():
    text = REQ_PATH.read_text().lower()
    for dimension in _EVIDENCE_DIMENSIONS:
        assert dimension.lower() in text


def test_req_datasupport_001_indexed():
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req
        for req in data["requirements"]
        if req["requirement_id"] == "REQ-DATASUPPORT-001"
    ]
    assert len(matches) == 1
    assert REQ_PATH.exists()
