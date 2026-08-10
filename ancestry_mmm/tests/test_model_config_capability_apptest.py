"""AppTest coverage for the "Data coverage & engine capability" section on
the Model Configuration page (REQ-COVERAGE-001 S6, Work Package 5).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.coverage import (
    CoverageSegment,
    FrequencyMetadata,
    STATE_UNKNOWN,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.fingerprint import fingerprint_dataframe
from ancestry_mmm.core.outcomes import FAMILY_HISTORY, METRIC_GSA, OutcomeDefinition
from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "04_Model_Config.py"


def _base_state():
    n = 12
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="W"),
            "market": ["UK"] * n,
            "New": np.arange(n, dtype=float) + 10,
            "tv_spend": np.arange(n, dtype=float) * 100 + 500,
        }
    )
    spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        channels=["tv_spend"],
        segment_outcomes={"New": "New"},
    )
    outcome_defs = [
        OutcomeDefinition(
            outcome_id="fh_new",
            product=FAMILY_HISTORY,
            segment="New",
            metric=METRIC_GSA,
            source_column="New",
        ).to_dict(),
    ]
    return df, spec, outcome_defs


def _resolved_matrix() -> VariableCoverageMatrix:
    record = VariableCoverageRecord(
        variable_id="tv_spend",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class="flow_count",
        ),
        coverage_segments=(),
    )
    return VariableCoverageMatrix(
        matrix_id="m1", matrix_version=1, generated_at="2026-01-01", records=(record,)
    )


def _unresolved_matrix() -> VariableCoverageMatrix:
    record = VariableCoverageRecord(
        variable_id="tv_spend",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class="flow_count",
        ),
        coverage_segments=(
            CoverageSegment(
                period_start="2024-01-01", period_end="2024-01-08", state=STATE_UNKNOWN
            ),
        ),
    )
    return VariableCoverageMatrix(
        matrix_id="m1", matrix_version=1, generated_at="2026-01-01", records=(record,)
    )


def _run_at(**extra_state):
    df, spec, outcome_defs = _base_state()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["transformed_data"] = df
    at.session_state["model_spec"] = spec.to_dict()
    at.session_state["outcome_definitions"] = outcome_defs
    for key, value in extra_state.items():
        at.session_state[key] = value
    at.run()
    return at


def test_no_coverage_matrix_shows_a_calm_nudge_not_a_warning():
    """A project that has never touched the (optional) Data Coverage page
    is this app's normal starting state - it must not produce a scary
    "every cell unsupported" warning by default, only a calm nudge. It
    must still honestly say the configuration is exploratory/unsupported
    (review finding, PR #158) rather than staying silent about it."""
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "exploratory/unsupported" in (i.value or "")
        and "No coverage matrix" in (i.value or "")
        for i in at.info
    )
    assert not any(
        "goes beyond what the engine can validly support" in (w.value or "")
        for w in at.warning
    )


def test_fully_resolved_coverage_shows_supported_success():
    df, _, _ = _base_state()
    at = _run_at(
        variable_coverage_matrix=_resolved_matrix().to_dict(),
        variable_coverage_matrix_built_against_fingerprint=fingerprint_dataframe(df),
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "within the engine's current rectangular capability" in (s.value or "")
        for s in at.success
    )
    assert not any(
        "goes beyond what the engine can validly support" in (w.value or "")
        for w in at.warning
    )
    assert not any("may be stale" in (w.value or "") for w in at.warning)


def test_resolved_coverage_with_stale_fingerprint_shows_stale_warning_not_success():
    """Review finding (PR #158): a matrix built against an earlier joined
    frame (or restored from an imported project bundle) must not be
    reported as confidently "supported" once the underlying data has
    since changed."""
    at = _run_at(
        variable_coverage_matrix=_resolved_matrix().to_dict(),
        variable_coverage_matrix_built_against_fingerprint="stale-fingerprint",
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert any("may be stale" in (w.value or "") for w in at.warning)
    assert not any(
        "within the engine's current rectangular capability" in (s.value or "")
        for s in at.success
    )


def test_unresolved_coverage_shows_unsupported_warning_with_decision_report():
    at = _run_at(variable_coverage_matrix=_unresolved_matrix().to_dict())
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "goes beyond what the engine can validly support" in (w.value or "")
        for w in at.warning
    )
    assert any("FR-MOD-015" in (c.value or "") for c in at.caption)


def test_capability_warning_never_blocks_preparing_the_frame():
    """REQ-COVERAGE-001 S6: this is a report, never a gate - an exploratory
    fit must remain available even when the engine-capability check fails."""
    at = _run_at(variable_coverage_matrix=_unresolved_matrix().to_dict())
    prepare_button = next(b for b in at.button if b.label == "Prepare modelling frame")
    prepare_button.click().run()
    assert not at.exception, f"prepare click raised: {at.exception}"
    assert at.session_state["frame"] is not None
