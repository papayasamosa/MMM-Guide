"""Reconciliation tests for `REQ-FX-002`/`REQ-FX-003`'s 2026-08-30
addenda (business-decision brief Decision 13: Finance constant-dollar FX
as the default governed method)."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = REPO_ROOT / "docs" / "approved_requirements" / "index.json"
REQ_FX_002_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-FX-002.md"
REQ_FX_003_PATH = REPO_ROOT / "docs" / "approved_requirements" / "REQ-FX-003.md"
WP7_PACKAGE_PATH = REPO_ROOT / "docs" / "wp7_governed_fx_finance_decision_package.md"


def test_req_fx_002_adds_annual_frequency():
    text = REQ_FX_002_PATH.read_text()
    assert "`annual`" in text
    assert "financial_year" in text


def test_req_fx_003_adds_finance_constant_dollar_annual_method():
    text = REQ_FX_003_PATH.read_text()
    assert "finance_constant_dollar_annual" in text
    assert "DEFAULT" in text


def test_req_fx_003_does_not_invent_actual_rate_values():
    """Decision 13 explicitly forbids inventing rates - the addendum must
    say so plainly."""
    text = REQ_FX_003_PATH.read_text()
    assert "no actual" in text.lower() and "rate" in text.lower()


def test_req_fx_003_addendum_leaves_budget_and_constant_currency_basis_open():
    """Items 7 (budget-planning rate) and 8 (constant-currency basis) are
    related to, but not resolved by, the annual-default approval."""
    text = REQ_FX_003_PATH.read_text()
    assert "item 7" in text.lower() or "budget-planning" in text.lower()
    assert "item 8" in text.lower() or "constant-currency basis" in text.lower()


def test_wp7_package_records_items_1_and_6_resolved():
    text = WP7_PACKAGE_PATH.read_text()
    assert "Item 1" in text and "resolved" in text
    assert "Item 6" in text
    assert (
        "Items 2, 3, 4, 5, 7, 8, 9, 10, 11, and 12 remain fully open" in text
    )


def test_req_fx_002_and_003_indexed():
    data = json.loads(INDEX_PATH.read_text())
    ids = {req["requirement_id"] for req in data["requirements"]}
    assert "REQ-FX-002" in ids
    assert "REQ-FX-003" in ids
