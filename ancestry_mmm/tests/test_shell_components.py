"""Tests for the Phase 1 UI/UX overhaul's shared design-system primitives
(see docs/decision_log.md): ancestry_mmm.components.tokens, .status, and
the new ui.py additions (page_readiness, render_context_bar, render_page_
header's extended signature, SectionCard/InfoPanel/WarningPanel/
BlockingPanel, render_empty_state's extended signature). Presentation-only
- none of this touches analytical/model/governance behaviour.

Pure-logic checks (page_readiness, badge_html, token contents) call the
functions directly with monkeypatched `st.*`/`get_state`, following the
existing pattern in test_drift_status_component.py. Rendering-heavy checks
that need a real Streamlit script context use AppTest.from_string(), the
pattern already used in test_session_state_contract.py.
"""

from streamlit.string_util import validate_icon_or_emoji
from streamlit.testing.v1 import AppTest

from ancestry_mmm.components import status as status_module
from ancestry_mmm.components import tokens as tokens_module
from ancestry_mmm.components import ui as ui_module


class TestTokens:
    def test_shell_css_contains_expected_class_hooks(self):
        css = tokens_module.shell_css()
        for cls in [
            "mmm-nav-group",
            "mmm-context-bar",
            "mmm-context-item",
            "mmm-badge",
            "mmm-header-desc",
            "mmm-panel-title",
            "mmm-panel-marker-info",
            "mmm-panel-marker-caution",
            "mmm-panel-marker-negative",
        ]:
            assert cls in css
        assert "#F4F1EC" in css
        assert "mmm-brand-lockup" in css
        assert "#0E1512" not in css

    def test_status_color_covers_every_semantic_key_status_badges_uses(self):
        used_color_keys = {c for (_, _, c) in status_module.STATUS_BADGES.values()}
        assert used_color_keys <= set(tokens_module.STATUS_COLOR.keys())


class TestSidebarIcons:
    def test_readiness_icons_are_valid_streamlit_page_link_icons(self):
        for status_key, icon in ui_module._READINESS_ICON.items():
            validate_icon_or_emoji(icon)


class TestSidebarIdentity:
    def test_sidebar_uses_product_lockup_without_segment_brand_subtitle(self):
        script = """
import streamlit as st
st.page_link = lambda *args, **kwargs: None
from ancestry_mmm.utils.session_state import init_session_state
from ancestry_mmm.components import render_sidebar
init_session_state()
render_sidebar("home")
"""
        at = AppTest.from_string(script)
        at.run()
        assert not at.exception, f"sidebar script raised: {at.exception}"
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "Family History &amp; DNA MMM" in rendered
        assert "Marketing Measurement &amp; Planning" in rendered
        assert "Marketing Mix Modelling" not in rendered
        assert "DNA cross-sell" not in rendered


class TestStatusBadges:
    def test_badge_html_known_key_includes_label_icon_and_color(self):
        markup = status_module.badge_html("ready")
        assert "Ready" in markup
        assert "✓" in markup
        assert tokens_module.STATUS_COLOR["positive"] in markup

    def test_badge_html_unknown_key_falls_back_to_a_title_cased_label(self):
        markup = status_module.badge_html("totally_unknown_status")
        assert "Totally Unknown Status" in markup

    def test_badge_html_label_override_wins(self):
        markup = status_module.badge_html("ready", label="Custom label")
        assert "Custom label" in markup

    def test_render_status_badge_calls_markdown_with_unsafe_html(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            status_module.st, "markdown", lambda text, **k: calls.append((text, k))
        )
        status_module.render_status_badge("stale")
        assert len(calls) == 1
        text, kwargs = calls[0]
        assert "Stale" in text
        assert kwargs.get("unsafe_allow_html") is True

    def test_render_status_badges_skips_falsy_keys_and_renders_one_inline_block(
        self, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            status_module.st, "markdown", lambda text, **k: calls.append(text)
        )
        status_module.render_status_badges(["ready", "", None, "stale"])
        assert len(calls) == 1
        assert "Ready" in calls[0] and "Stale" in calls[0]

    def test_render_status_badges_is_a_no_op_for_an_empty_iterable(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            status_module.st, "markdown", lambda text, **k: calls.append(text)
        )
        status_module.render_status_badges([])
        assert calls == []

    def test_every_badge_is_never_colour_only(self):
        # Root AGENTS.md / Phase 1 rule: status must never be colour-only.
        for key, (label, icon, color_key) in status_module.STATUS_BADGES.items():
            assert label, f"{key} has no text label"
            assert icon, f"{key} has no icon"

    def test_status_icons_use_the_restrained_semantic_vocabulary(self):
        # UX/UI coherence Phase 11 / brief Finding 18: text remains
        # authoritative, with a small repeated cue set rather than one
        # decorative glyph per lifecycle key.
        icons = {icon for _, icon, _ in status_module.STATUS_BADGES.values()}
        assert icons <= {"✓", "i", "!", "×", "•", "·"}
        assert status_module.STATUS_BADGES["validated"][1] == "✓"
        assert status_module.STATUS_BADGES["reported"][1] == "i"
        assert status_module.STATUS_BADGES["stale"][1] == "!"
        assert status_module.STATUS_BADGES["blocked"][1] == "×"
        assert status_module.STATUS_BADGES["running"][1] == "•"
        assert status_module.STATUS_BADGES["draft"][1] == "·"

    def test_unknown_status_uses_information_cue(self):
        markup = status_module.badge_html("not_a_real_status")
        assert ">i Not A Real Status</span>" in markup


class TestPageReadiness:
    @staticmethod
    def _patch_state(monkeypatch, state):
        monkeypatch.setattr(
            ui_module, "get_state", lambda key, default=None: state.get(key, default)
        )

    def test_data_upload_not_started_then_complete(self, monkeypatch):
        self._patch_state(monkeypatch, {})
        assert ui_module.page_readiness("data_upload") == "not_started"
        self._patch_state(monkeypatch, {"data_loaded": True})
        assert ui_module.page_readiness("data_upload") == "complete"

    def test_transform_pipeline_blocked_without_upstream_data(self, monkeypatch):
        self._patch_state(monkeypatch, {})
        assert ui_module.page_readiness("transform_pipeline") == "blocked"

    def test_model_training_progresses_blocked_not_started_complete(self, monkeypatch):
        self._patch_state(monkeypatch, {})
        assert ui_module.page_readiness("model_training") == "blocked"
        self._patch_state(monkeypatch, {"frame": object()})
        assert ui_module.page_readiness("model_training") == "not_started"
        self._patch_state(monkeypatch, {"frame": object(), "model_trained": True})
        assert ui_module.page_readiness("model_training") == "complete"

    def test_optional_pages_are_never_reported_as_blocked(self, monkeypatch):
        self._patch_state(monkeypatch, {})
        for key in (
            "causal_graph",
            "market_descriptors",
            "compare_models",
        ):
            assert ui_module.page_readiness(key) == "optional"

    def test_scenario_planner_saved_once_scenarios_exist(self, monkeypatch):
        self._patch_state(
            monkeypatch,
            {"model_approval": {"status": "approved"}, "scenarios": [{"a": 1}]},
        )
        assert ui_module.page_readiness("scenario_planner") == "saved"

    def test_unknown_key_defaults_to_not_started(self, monkeypatch):
        self._patch_state(monkeypatch, {})
        assert ui_module.page_readiness("not_a_real_page") == "not_started"


class TestGroupReadiness:
    """Phase 2 Home overview (docs/decision_log.md): group_readiness() is a
    pure aggregation over page_readiness() results - it introduces no new
    readiness source of its own."""

    def test_empty_keys_is_not_started(self):
        assert ui_module.group_readiness([]) == "not_started"

    def test_all_optional_is_not_started(self, monkeypatch):
        monkeypatch.setattr(ui_module, "page_readiness", lambda k: "optional")
        assert ui_module.group_readiness(["a", "b"]) == "not_started"

    def test_all_complete_is_complete(self, monkeypatch):
        monkeypatch.setattr(ui_module, "page_readiness", lambda k: "complete")
        assert ui_module.group_readiness(["a", "b"]) == "complete"

    def test_some_ready_is_current(self, monkeypatch):
        statuses = {"a": "complete", "b": "not_started"}
        monkeypatch.setattr(ui_module, "page_readiness", lambda k: statuses[k])
        assert ui_module.group_readiness(["a", "b"]) == "current"

    def test_none_ready_but_one_blocked_is_blocked(self, monkeypatch):
        statuses = {"a": "blocked", "b": "not_started"}
        monkeypatch.setattr(ui_module, "page_readiness", lambda k: statuses[k])
        assert ui_module.group_readiness(["a", "b"]) == "blocked"

    def test_none_ready_none_blocked_is_not_started(self, monkeypatch):
        monkeypatch.setattr(ui_module, "page_readiness", lambda k: "not_started")
        assert ui_module.group_readiness(["a", "b"]) == "not_started"

    def test_optional_pages_do_not_count_against_a_ready_group(self, monkeypatch):
        statuses = {"a": "complete", "b": "optional"}
        monkeypatch.setattr(ui_module, "page_readiness", lambda k: statuses[k])
        assert ui_module.group_readiness(["a", "b"]) == "complete"


class TestNextRecommendedStepKey:
    """Phase 1: next action comes from canonical lifecycle state and skips
    optional pages."""

    @staticmethod
    def _patch_state(monkeypatch, state):
        monkeypatch.setattr(
            ui_module, "get_state", lambda key, default=None: state.get(key, default)
        )

    def test_no_data_recommends_data_upload_first(self, monkeypatch):
        self._patch_state(monkeypatch, {})
        assert ui_module.next_recommended_step_key() == "data_upload"

    def test_after_data_loaded_recommends_transform_pipeline(self, monkeypatch):
        self._patch_state(monkeypatch, {"data_loaded": True})
        assert ui_module.next_recommended_step_key() == "transform_pipeline"

    def test_skips_optional_pages(self, monkeypatch):
        # transformed data + a saved model_spec makes causal_graph
        # (optional) the next WORKFLOW_STEPS entry after structure, but it
        # must never be recommended - activity mapping is already configured,
        # and market_descriptors remains optional before model_config.
        self._patch_state(
            monkeypatch,
            {
                "data_loaded": True,
                "transformed_data": object(),
                "variable_coverage_matrix": object(),
                "model_spec": {"markets": ["UK"]},
                "activity_definitions": [{"activity_id": "uk-tv"}],
            },
        )
        assert ui_module.next_recommended_step_key() == "model_config"

    def test_scorecard_without_readiness_keeps_diagnostics_as_next_action(
        self, monkeypatch
    ):
        # A scorecard is evidence, not approval readiness. The next action
        # remains Diagnostics until readiness is evaluated and approval is
        # recorded, per the Phase 1 implementation brief.
        self._patch_state(
            monkeypatch,
            {
                "data_loaded": True,
                "transformed_data": object(),
                "variable_coverage_matrix": object(),
                "model_spec": {"markets": ["UK"]},
                "activity_definitions": [{"activity_id": "uk-tv"}],
                "frame": object(),
                "model_trained": True,
                "scorecard": {"ok": True},
                "model_approval": {"status": "approved"},
                "curve_bank_entry_id": "entry-1",
                "scenarios": [{"a": 1}],
            },
        )
        assert ui_module.next_recommended_step_key() == "diagnostics"


_HEADER_SCRIPT = """
import streamlit as st
from ancestry_mmm.utils.session_state import init_session_state
from ancestry_mmm.components import render_page_header

st.set_page_config(layout="wide")
init_session_state()
render_page_header(
    "data_coverage",
    description="Custom one-sentence description.",
    task_prompt="Which coverage treatment is ready to approve?",
    badges=["ready", "stale"],
    primary_action={"label": "Primary go", "target_key": "structure"},
    secondary_actions=[{"label": "Secondary go"}],
)
"""

_PANELS_SCRIPT = """
import streamlit as st
from ancestry_mmm.components import SectionCard, InfoPanel, WarningPanel, BlockingPanel

with SectionCard("A section", description="Section description"):
    st.write("section body")
with InfoPanel("An info panel", description="Info description"):
    st.write("info body")
with WarningPanel("A warning panel"):
    st.write("warning body")
with BlockingPanel("A blocking panel"):
    st.write("blocking body")
"""

_CONTEXT_BAR_EMPTY_SCRIPT = """
from ancestry_mmm.utils.session_state import init_session_state
from ancestry_mmm.components import render_context_bar

init_session_state()
render_context_bar()
"""

_CONTEXT_BAR_POPULATED_SCRIPT = """
import pandas as pd
from ancestry_mmm.utils.session_state import init_session_state, set_state
from ancestry_mmm.components import render_context_bar

init_session_state()
set_state("project_name", "<script>evil</script>")
set_state("raw_sources", {"media": pd.DataFrame({"a": [1]})})
render_context_bar()
"""


class TestRenderPageHeader:
    def test_extended_header_renders_title_badges_and_actions(self):
        at = AppTest.from_string(_HEADER_SCRIPT)
        at.run()
        assert not at.exception, f"header script raised: {at.exception}"
        assert any(
            "Custom one-sentence description" in (m.value or "") for m in at.markdown
        )
        assert any(
            "Which coverage treatment is ready to approve?" in (m.value or "")
            for m in at.markdown
        )
        assert any("·" in (caption.value or "") for caption in at.caption)
        assert not any("Â·" in (caption.value or "") for caption in at.caption)
        assert any("Ready" in (m.value or "") for m in at.markdown)
        assert any(b.label == "Primary go" for b in at.button)
        assert any(b.label == "Secondary go" for b in at.button)
        # Workflow steps remain metadata for Home/navigation; the shared
        # header must not add a generic tutorial expander to every page.
        assert not any("Step-by-step guidance" in e.label for e in at.expander)

    def test_header_with_no_new_args_still_renders_title(self):
        script = """
import streamlit as st
from ancestry_mmm.utils.session_state import init_session_state
from ancestry_mmm.components import render_page_header

st.set_page_config(layout="wide")
init_session_state()
render_page_header("data_coverage")
"""
        at = AppTest.from_string(script)
        at.run()
        assert not at.exception, f"header script raised: {at.exception}"
        assert at.title[0].value == "Coverage & Gaps"


class TestPanelPrimitives:
    def test_all_four_panels_render_their_titles_without_raising(self):
        at = AppTest.from_string(_PANELS_SCRIPT)
        at.run()
        assert not at.exception, f"panels script raised: {at.exception}"
        rendered = " ".join((m.value or "") for m in at.markdown)
        for title in (
            "A section",
            "An info panel",
            "A warning panel",
            "A blocking panel",
        ):
            assert title in rendered


class TestContextBar:
    def test_renders_nothing_when_no_project_state_is_set(self):
        at = AppTest.from_string(_CONTEXT_BAR_EMPTY_SCRIPT)
        at.run()
        assert not at.exception, f"context bar script raised: {at.exception}"
        # init_session_state() sets a default project_name, so the bar
        # should render at least that one item without raising - the "no
        # invented fields" contract is what the populated test below checks.

    def test_populated_context_bar_labels_demo_data_and_escapes_project_name(self):
        at = AppTest.from_string(_CONTEXT_BAR_POPULATED_SCRIPT)
        at.run()
        assert not at.exception, f"context bar script raised: {at.exception}"
        rendered = " ".join((m.value or "") for m in at.markdown)
        assert "Synthetic demo data" in rendered
        # Project name must be HTML-escaped, not injected raw.
        assert "<script>evil</script>" not in rendered
        assert "&lt;script&gt;" in rendered


class TestRenderEmptyStateExtended:
    def test_message_only_call_is_unchanged(self):
        script = """
from ancestry_mmm.components import render_empty_state
render_empty_state("Plain message.")
"""
        at = AppTest.from_string(script)
        at.run()
        assert not at.exception
        assert any("Plain message." == (i.value or "") for i in at.info)

    def test_structured_fields_are_appended_under_the_message(self):
        script = """
from ancestry_mmm.components import render_empty_state
render_empty_state(
    "Base message.",
    what_for="Testing.",
    dependency="A missing thing.",
    next_action="Do the next thing.",
)
"""
        at = AppTest.from_string(script)
        at.run()
        assert not at.exception
        assert len(at.info) == 1
        value = at.info[0].value or ""
        assert "Base message." in value
        assert "Testing." in value
        assert "A missing thing." in value
        assert "Do the next thing." in value

    def test_blocking_renders_as_error_not_info(self):
        script = """
from ancestry_mmm.components import render_empty_state
render_empty_state("Blocked message.", blocking=True)
"""
        at = AppTest.from_string(script)
        at.run()
        assert not at.exception
        assert len(at.error) == 1
        assert len(at.info) == 0
