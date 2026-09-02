"""Anti-drift tests for `REQ-OPT-001` (optimiser objective-kind and
constraint-kind vocabulary contract, business-decision brief Decisions
16 and 18). Target-state contract only - these tests check the record's
own text, not any implementation (none exists yet by design)."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_OPT_001_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-OPT-001.md"


def test_objective_kind_vocabulary_is_closed_and_named():
    text = REQ_OPT_001_PATH.read_text()
    for kind in (
        "maximise_outcome",
        "maximise_revenue",
        "maximise_profit",
        "maximise_roi",
        "minimise_cpa",
    ):
        assert kind in text


def test_constraint_kind_vocabulary_extends_existing_five_kinds():
    text = REQ_OPT_001_PATH.read_text()
    for existing_kind in (
        "locked_cell",
        "channel_total",
        "month_total",
        "bounded_movement",
        "min_spend_floor",
    ):
        assert existing_kind in text
    for new_kind in (
        "percentage_change_from_reference",
        "absolute_change_from_reference",
        "zero_spend",
        "required_minimum_activity",
        "unavailable",
    ):
        assert new_kind in text


def test_seo_excluded_from_cost_based_objectives():
    text = " ".join(REQ_OPT_001_PATH.read_text().split())
    assert "SEO" in text
    assert "must never be included in a cost-based objective" in text


def test_req_opt_001_does_not_invent_numeric_defaults():
    text = " ".join(REQ_OPT_001_PATH.read_text().split())
    assert "none is approved or invented by this record" in text


def test_req_opt_001_indexed():
    data = json.loads(INDEX_PATH.read_text())
    matches = [
        req for req in data["requirements"] if req["requirement_id"] == "REQ-OPT-001"
    ]
    assert len(matches) == 1
    assert REQ_OPT_001_PATH.exists()
