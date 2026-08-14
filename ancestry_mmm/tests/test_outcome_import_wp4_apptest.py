"""Streamlit AppTest coverage for WP4 source-review UX."""

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.outcome_import import interpret_outcome_source
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
    SEGMENT_DIMENSION_FH_CUSTOMER,
)

st.page_link = lambda *args, **kwargs: None

PAGE = Path(__file__).parent.parent / "pages" / "01_Data_Upload.py"


def _definition(outcome_id: str, source_column: str) -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id=outcome_id,
        product=FAMILY_HISTORY,
        segment="New",
        metric="GSA",
        metric_key=METRIC_KEY_FH_GSA,
        segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
        source_column=source_column,
    )


def _run(**state):
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    return at


def test_v1_source_review_is_explicitly_incomplete_and_has_no_draft():
    imported = interpret_outcome_source(
        schema_version="standard-source-pack-v1",
        source_warnings=("legacy source warning",),
    )
    at = _run(outcome_source_import_status=imported.to_dict())

    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "older file is missing information" in (warning.value or "")
        for warning in at.warning
    )
    assert at.session_state["outcome_source_draft"] is None


def test_existing_catalogue_requires_explicit_draft_adoption():
    current = _definition("fh_gsa_new", "old_gsa")
    imported = interpret_outcome_source(
        schema_version="standard-source-pack-v2",
        outcome_definitions=(_definition("fh_gsa_new", "new_gsa"),),
        current_outcomes=(current,),
    )
    at = _run(
        outcome_definitions=[current.to_dict()],
        outcome_source_import_status=imported.to_dict(),
        outcome_source_draft=[item.to_dict() for item in imported.outcome_definitions],
        outcome_source_draft_groups=[],
        outcome_source_draft_reconciliation_groups=[],
    )

    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        button.label == "Use imported definitions as a draft" for button in at.button
    )
    assert at.session_state["outcome_definitions"] == [current.to_dict()]

    next(
        button
        for button in at.button
        if button.label == "Use imported definitions as a draft"
    ).click().run()

    assert not at.exception, f"adoption raised: {at.exception}"
    assert at.session_state["outcome_definitions"] == [
        item.to_dict() for item in imported.outcome_definitions
    ]
    assert (
        "outcome_approvals" not in at.session_state
        or at.session_state["outcome_approvals"] == []
    )
    assert any("No outcome approval was created" in (m.value or "") for m in at.success)
