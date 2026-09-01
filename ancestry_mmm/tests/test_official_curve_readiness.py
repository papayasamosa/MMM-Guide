"""Unit tests for application.official_curve_readiness (Phase 6 UI overhaul).

Covers every blocker resolve_generation_blockers can raise, restating the
same completeness conditions 13_Official_Curve_Generation.py's Generate
click handler already checks - so a missing requirement is visible before
the button is pressed. See test_official_curve_generation_page_apptest.py
for the end-to-end page-level assertion that the panel actually renders and
the button is disabled.
"""

from ancestry_mmm.application.official_curve_readiness import (
    resolve_generation_blockers,
)

_BASE_KWARGS = dict(
    eligible_outcomes_count=1,
    selected_markets=["UK"],
    curve_type="model_input",
    cost_mapping_registry_present=False,
    currency_by_market={},
    reporting_currency="",
    reference_context_confirmed={"UK": True},
    invalid_support_cells=[],
    artifact_id="artifact-1",
)


def test_fully_ready_state_has_no_blockers():
    assert resolve_generation_blockers(**_BASE_KWARGS) == []


def test_no_eligible_outcome_blocks():
    kwargs = {**_BASE_KWARGS, "eligible_outcomes_count": 0}
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "no_eligible_outcome" for b in blockers)


def test_no_selected_markets_blocks():
    kwargs = {**_BASE_KWARGS, "selected_markets": []}
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "no_markets" for b in blockers)


def test_unconfirmed_reference_context_blocks():
    kwargs = {**_BASE_KWARGS, "reference_context_confirmed": {"UK": False}}
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "reference_context_unconfirmed" for b in blockers)
    assert "UK" in next(
        b.message for b in blockers if b.code == "reference_context_unconfirmed"
    )


def test_missing_reference_context_entry_treated_as_unconfirmed():
    kwargs = {**_BASE_KWARGS, "reference_context_confirmed": {}}
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "reference_context_unconfirmed" for b in blockers)


def test_blank_artifact_id_blocks():
    kwargs = {**_BASE_KWARGS, "artifact_id": "   "}
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "blank_artifact_id" for b in blockers)


def test_invalid_support_cells_block():
    kwargs = {**_BASE_KWARGS, "invalid_support_cells": ["UK/TV_Brand"]}
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "invalid_support_cells" for b in blockers)


def test_model_input_curve_never_requires_cost_mapping_or_currency():
    """Model-input curves have no cost-mapping/currency requirement at all -
    the monetary-only blockers must never fire for curve_type='model_input'."""
    kwargs = {
        **_BASE_KWARGS,
        "curve_type": "model_input",
        "cost_mapping_registry_present": False,
        "currency_by_market": {},
        "reporting_currency": "",
    }
    blockers = resolve_generation_blockers(**kwargs)
    codes = {b.code for b in blockers}
    assert "no_cost_mappings" not in codes
    assert "missing_local_currency" not in codes
    assert "missing_reporting_currency" not in codes


def test_monetary_curve_without_cost_mapping_blocks():
    kwargs = {
        **_BASE_KWARGS,
        "curve_type": "monetary",
        "cost_mapping_registry_present": False,
        "currency_by_market": {"UK": "GBP"},
        "reporting_currency": "GBP",
    }
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "no_cost_mappings" for b in blockers)


def test_monetary_curve_missing_local_currency_for_a_market_blocks():
    kwargs = {
        **_BASE_KWARGS,
        "curve_type": "monetary",
        "cost_mapping_registry_present": True,
        "currency_by_market": {"UK": ""},
        "reporting_currency": "GBP",
    }
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "missing_local_currency" for b in blockers)
    assert "UK" in next(
        b.message for b in blockers if b.code == "missing_local_currency"
    )


def test_monetary_curve_missing_reporting_currency_blocks():
    kwargs = {
        **_BASE_KWARGS,
        "curve_type": "monetary",
        "cost_mapping_registry_present": True,
        "currency_by_market": {"UK": "GBP"},
        "reporting_currency": "",
    }
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "missing_reporting_currency" for b in blockers)


def test_monetary_curve_fully_satisfied_is_not_blocked_on_monetary_grounds():
    kwargs = {
        **_BASE_KWARGS,
        "curve_type": "monetary",
        "cost_mapping_registry_present": True,
        "currency_by_market": {"UK": "GBP"},
        "reporting_currency": "GBP",
    }
    blockers = resolve_generation_blockers(**kwargs)
    codes = {b.code for b in blockers}
    assert "no_cost_mappings" not in codes
    assert "missing_local_currency" not in codes
    assert "missing_reporting_currency" not in codes


def test_monetary_curve_missing_fx_pair_blocks_before_generation():
    kwargs = {
        **_BASE_KWARGS,
        "curve_type": "monetary",
        "cost_mapping_registry_present": True,
        "currency_by_market": {"UK": "GBP"},
        "reporting_currency": "USD",
        "missing_fx_pairs": ["GBP->USD"],
    }
    blockers = resolve_generation_blockers(**kwargs)
    assert any(b.code == "missing_fx_rate" for b in blockers)
    assert "GBP->USD" in next(
        b.message for b in blockers if b.code == "missing_fx_rate"
    )


def test_multiple_blockers_all_reported_not_just_the_first():
    kwargs = {
        **_BASE_KWARGS,
        "eligible_outcomes_count": 0,
        "selected_markets": [],
        "artifact_id": "",
    }
    blockers = resolve_generation_blockers(**kwargs)
    codes = {b.code for b in blockers}
    assert {"no_eligible_outcome", "no_markets", "blank_artifact_id"}.issubset(codes)
