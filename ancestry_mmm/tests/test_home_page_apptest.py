"""AppTest coverage for ancestry_mmm/app.py (Home) - Phase 2 of the
Streamlit UI/UX overhaul (docs/decision_log.md): the next-recommended-
action element, the per-workflow-area readiness strip, the deterministic
open-issues list, and the synthetic-demo entry point that replaced the
old flat 15-line workflow list and four generic KPI cards.

Follows the same AppTest.from_file + `st.page_link` stub pattern already
used for page-level tests (see test_data_coverage_page_apptest.py) -
render_sidebar() calls st.page_link(), which raises outside a real
multipage app context under AppTest.
"""

from pathlib import Path
from types import SimpleNamespace

import streamlit as st
from streamlit.testing.v1 import AppTest

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "app.py"


def _run_at(**extra_state):
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    for key, value in extra_state.items():
        at.session_state[key] = value
    at.run()
    return at


class TestNextRecommendedAction:
    def test_empty_state_offers_the_synthetic_demo_as_the_dominant_action(self):
        at = _run_at()
        assert not at.exception, f"page raised: {at.exception}"
        assert any("Next recommended action" in (m.value or "") for m in at.markdown)
        assert any(b.label == "Load demo data" for b in at.button)
        assert any(b.label == "Upload your own data" for b in at.button)
        # Synthetic label discipline (render_context_bar's own contract) -
        # never presented as though it were a real Ancestry upload.
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "synthetic demo" in rendered.lower()
        assert "not real Ancestry data" in rendered or "not real" in rendered.lower()

    def test_loading_the_demo_populates_state_and_updates_the_next_action(self):
        at = _run_at()
        demo_button = next(b for b in at.button if b.label == "Load demo data")
        demo_button.click().run()
        assert not at.exception, f"demo click raised: {at.exception}"
        assert at.session_state["data_loaded"] is True
        assert at.session_state["raw_sources"]
        # active_source_upload_version stays empty for demo data - the same
        # "never mistaken for a real upload" contract render_context_bar
        # already relies on (components/ui.py render_context_bar).
        assert at.session_state["active_source_upload_version"] == {}
        # With data loaded but nothing transformed yet, the next
        # recommended step is Transform Pipeline.
        assert any("Continue to Prepare Data" in (b.label or "") for b in at.button)

    def test_data_loaded_but_not_transformed_recommends_transform_pipeline(self):
        at = _run_at(data_loaded=True)
        assert not at.exception, f"page raised: {at.exception}"
        assert any("Continue to Prepare Data" in (b.label or "") for b in at.button)


class TestWorkflowReadinessStrip:
    def test_project_state_shows_overall_progress_in_the_opening_dashboard(self):
        at = _run_at()
        assert not at.exception, f"page raised: {at.exception}"
        rendered = " ".join((c.value or "") for c in at.caption)
        assert "Workflow: 0 of 11 stages complete" in rendered

    def test_shows_five_workflow_areas_not_the_overview_group(self):
        at = _run_at()
        assert not at.exception, f"page raised: {at.exception}"
        rendered = " ".join((c.value or "") for c in at.caption)
        for label in (
            "DATA",
            "MODEL DESIGN",
            "FIT & VALIDATE",
            "DECISION SUPPORT",
            "OPERATIONS",
        ):
            assert label in rendered
        assert "OVERVIEW" not in rendered

    def test_data_area_reflects_ready_state_once_data_is_loaded(self):
        at = _run_at(data_loaded=True)
        assert not at.exception, f"page raised: {at.exception}"
        # group_readiness treats "some ready, not all" as "current" (in
        # progress) - the DATA area badge should therefore say so, not
        # remain "Not started".
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "In progress" in rendered or "Ready" in rendered


class TestIssuesRequiringAttention:
    def test_no_issues_in_a_clean_empty_project(self):
        at = _run_at()
        assert not at.exception, f"page raised: {at.exception}"
        assert any("No open issues detected" in (c.value or "") for c in at.caption)

    def test_trained_but_not_approved_is_flagged(self):
        at = _run_at(
            model_trained=True,
            scorecard={"convergence": {}},
            model_approval=None,
            approval_readiness=None,
        )
        assert not at.exception, f"page raised: {at.exception}"
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "not yet approved for" in rendered

    def test_blocking_validation_gates_are_named(self):
        at = _run_at(
            model_trained=True,
            scorecard={"convergence": {}},
            model_approval=None,
            approval_readiness={
                "overall_ready": False,
                "blocking_failures": [{"gate_name": "max_rhat"}],
            },
        )
        assert not at.exception, f"page raised: {at.exception}"
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "blocking validation gate" in rendered
        assert "max_rhat" in rendered

    def test_approved_without_curve_bank_entry_is_flagged(self):
        at = _run_at(
            model_trained=True,
            scorecard={"convergence": {}},
            model_approval={"status": "approved"},
            approval_readiness={"overall_ready": True, "blocking_failures": []},
            curve_bank_entry_id=None,
        )
        assert not at.exception, f"page raised: {at.exception}"
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "no curves have been saved" in rendered

    def test_outcome_drift_relative_to_the_fitted_model_is_flagged(self):
        at = _run_at(
            model_spec={
                "date_col": "date",
                "market_col": "market",
                "markets": ["UK"],
                "segment_outcomes": {"New Customer": "fh_new_gsa"},
            },
            # An empty fit-time catalogue means every current outcome_id
            # is "New since fit" (core.outcomes.outcome_drift_status) -
            # a real, traceable drift condition, not a fabricated one.
            model_meta=SimpleNamespace(outcome_catalogue_at_fit=[]),
        )
        assert not at.exception, f"page raised: {at.exception}"
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "drifted from the fitted model's catalogue" in rendered


class TestLineagePanel:
    def test_omitted_before_any_model_has_been_fit(self):
        at = _run_at()
        assert not at.exception, f"page raised: {at.exception}"
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "Model lineage" not in rendered

    def test_shown_once_a_model_run_exists(self):
        at = _run_at(
            model_run_id="abcdef1234567890",
            model_trained=True,
            model_approval={"status": "approved"},
            curve_bank_entry_id="curve-entry-1",
            scenarios=[{"a": 1}],
        )
        assert not at.exception, f"page raised: {at.exception}"
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "Model lineage" in rendered
        assert "Current model lineage" not in rendered
        assert any(e.label == "Technical details" for e in at.expander)
        assert "Approved" in rendered
        assert "Scenarios saved:** 1" in rendered


class TestQuickLinksAndWorkflowGuide:
    def test_quick_links_are_present(self):
        at = _run_at()
        assert not at.exception, f"page raised: {at.exception}"
        labels = {b.label for b in at.button}
        assert "Data Sources" in labels
        assert "Model Diagnostics" in labels
        assert "Scenario Planner" in labels

    def test_home_uses_compact_workflow_map_instead_of_tutorial_expander(self):
        at = _run_at()
        assert not at.exception, f"page raised: {at.exception}"
        assert not any(
            "Full step-by-step workflow guide" in e.label for e in at.expander
        )
        # The old dominant flat numbered list must not appear as a bare
        # top-level "### Workflow" heading any more.
        assert not any((m.value or "").strip() == "### Workflow" for m in at.markdown)


class TestCommandPalette:
    def test_command_palette_button_is_present(self):
        at = _run_at()
        assert not at.exception, f"page raised: {at.exception}"
        assert any("Command palette" in (b.label or "") for b in at.button)
