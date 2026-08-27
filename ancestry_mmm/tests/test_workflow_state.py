"""Phase 1 workflow-state regression tests.

These tests enforce the UX/UI implementation brief's acceptance criteria:
presentation state must distinguish access, lifecycle evidence, staleness and
optional pages without changing analytical or governance authority.
"""

from types import SimpleNamespace

import pandas as pd

from ancestry_mmm.core.causal_graph import CausalGraph
from ancestry_mmm.core.fingerprint import fingerprint_dataframe
from ancestry_mmm.utils.workflow_state import (
    is_registered_step_complete,
    next_workflow_step_key,
    resolve_workflow_navigation,
    workflow_page_state,
    workflow_progress,
)


def _getter(state):
    return lambda key, default=None: state.get(key, default)


def test_empty_project_has_blocked_access_and_canonical_progress():
    getter = _getter({})

    assert (
        workflow_page_state("data_upload", getter=getter).display_status
        == "not_started"
    )
    assert (
        workflow_page_state("transform_pipeline", getter=getter).display_status
        == "blocked"
    )
    assert (
        workflow_page_state("causal_graph", getter=getter).display_status == "optional"
    )
    assert next_workflow_step_key(getter=getter) == "data_upload"
    assert workflow_progress(getter=getter) == (1, 15)


def test_configured_structure_skips_optional_pages():
    getter = _getter(
        {
            "data_loaded": True,
            "transformed_data": object(),
            "model_spec": {"markets": ["UK"]},
            "activity_definitions": [{"activity_id": "uk-tv"}],
        }
    )

    assert (
        workflow_page_state("structure", getter=getter).display_status == "configured"
    )
    assert (
        workflow_page_state("channel_media_units", getter=getter).display_status
        == "configured"
    )
    assert next_workflow_step_key(getter=getter) == "model_config"


def test_coverage_is_optional_for_exploratory_work_but_explains_official_need():
    state = workflow_page_state(
        "data_coverage",
        getter=_getter({"transformed_data": object()}),
    )

    assert state.display_status == "exploratory"
    assert state.optional
    assert state.satisfied
    assert "required before official preparation" in state.reason


def test_coverage_without_any_prepared_data_is_optional():
    state = workflow_page_state("data_coverage", getter=_getter({}))

    assert state.display_status == "optional"
    assert state.optional
    assert state.satisfied


def test_coverage_matrix_built_against_older_inputs_is_stale():
    frame = pd.DataFrame({"value": [1, 2]})
    state = workflow_page_state(
        "data_coverage",
        getter=_getter(
            {
                "transformed_data": frame,
                "variable_coverage_matrix": {"matrix_id": "m1"},
                "variable_coverage_matrix_built_against_fingerprint": "old",
            }
        ),
    )

    assert state.display_status == "stale"
    assert state.optional
    assert fingerprint_dataframe(frame) != "old"


def test_model_setup_distinguishes_exploratory_frame_from_official_readiness():
    state = workflow_page_state(
        "model_config",
        getter=_getter(
            {
                "model_spec": {"markets": ["UK"]},
                "frame": object(),
                "official_preparation_result": {
                    "status": "unsupported_no_approved_method",
                    "ready": False,
                },
            }
        ),
    )

    assert state.display_status == "exploratory"
    assert state.satisfied
    assert "does not satisfy official preparation" in state.reason
    assert "no approved method" in state.reason


def test_model_setup_is_complete_only_when_official_preparation_is_ready():
    state = workflow_page_state(
        "model_config",
        getter=_getter(
            {
                "model_spec": {"markets": ["UK"]},
                "frame": object(),
                "official_preparation_result": {
                    "status": "ready",
                    "ready": True,
                },
            }
        ),
    )

    assert state.display_status == "complete"
    assert state.satisfied


def test_model_setup_surfaces_official_blocker_before_a_frame_exists():
    state = workflow_page_state(
        "model_config",
        getter=_getter(
            {
                "model_spec": {"markets": ["UK"]},
                "official_preparation_result": {
                    "status": "decision_required",
                    "ready": False,
                },
            }
        ),
    )

    assert state.display_status == "blocked"
    assert not state.satisfied
    assert "Official preparation remains blocked" in state.reason


def test_graph_draft_and_structural_staleness_are_not_ready():
    graph = CausalGraph(graph_id="graph-1")
    getter = _getter({"causal_graph": graph.to_dict()})

    assert workflow_page_state("causal_graph", getter=getter).display_status == "draft"

    stale_getter = _getter(
        {
            "causal_graph": graph.to_dict(),
            "causal_graph_compiled_structural_fingerprint": "older-fingerprint",
        }
    )
    stale = workflow_page_state("causal_graph", getter=stale_getter)
    assert stale.display_status == "stale"
    assert stale.optional


def test_diagnostics_scorecard_does_not_imply_readiness_or_approval():
    base = {"model_trained": True, "scorecard": {"fit": "reported"}}
    configured = workflow_page_state("diagnostics", getter=_getter(base))
    assert configured.display_status == "configured"
    assert not configured.satisfied

    artefact = SimpleNamespace(fingerprint=lambda: "diagnostics-fp")
    blocked = workflow_page_state(
        "diagnostics",
        getter=_getter(
            {
                **base,
                "diagnostics_artefact": artefact,
                "approval_readiness": {
                    "diagnostic_artefact_fingerprint": "diagnostics-fp",
                    "overall_ready": False,
                },
            }
        ),
    )
    assert blocked.display_status == "blocked"
    assert not blocked.satisfied


def test_official_curve_artifact_can_be_current_or_stale(monkeypatch):
    import ancestry_mmm.utils.workflow_state as state_module

    approval = {"status": "approved", "model_run_id": "run-2"}
    getter = _getter({"model_approval": approval, "model_run_id": "run-2"})
    current_artifact = SimpleNamespace(
        metadata=SimpleNamespace(
            format_status="current",
            historical_integrity="intact",
            model_identity_snapshot={"model_run_id": "run-2"},
        )
    )
    monkeypatch.setattr(
        state_module,
        "load_curve_artifact_store",
        lambda *_args, **_kwargs: SimpleNamespace(loaded=(current_artifact,), audit=()),
    )
    assert (
        workflow_page_state("official_curve_generation", getter=getter).display_status
        == "complete"
    )

    stale_artifact = SimpleNamespace(
        metadata=SimpleNamespace(
            format_status="current",
            historical_integrity="intact",
            model_identity_snapshot={"model_run_id": "run-1"},
        )
    )
    monkeypatch.setattr(
        state_module,
        "load_curve_artifact_store",
        lambda *_args, **_kwargs: SimpleNamespace(loaded=(stale_artifact,), audit=()),
    )
    assert (
        workflow_page_state("official_curve_generation", getter=getter).display_status
        == "stale"
    )


def test_export_state_reflects_an_export_action_not_page_availability():
    state = {"data_loaded": True}
    not_started = workflow_page_state("export", getter=_getter(state))
    assert not_started.display_status == "not_started"
    assert not not_started.satisfied

    state["export_last_bundle_summary"] = {"checkpoint": "scenarios"}
    complete = workflow_page_state("export", getter=_getter(state))
    assert complete.display_status == "complete"
    assert complete.satisfied


def test_numeric_completion_checks_page_state_not_position():
    getter = _getter({"data_loaded": True})
    assert is_registered_step_complete(1, getter=getter)
    assert not is_registered_step_complete(2, getter=getter)
    assert not is_registered_step_complete(16, getter=getter)


# UI-WP1: resolve_workflow_navigation is the single shared resolver behind
# both Home's "next recommended action" and every page footer's "NEXT STEP"
# panel, so an optional page (Coverage & Gaps, Causal Graph, Model
# Comparison, ...) can never be presented as the required next step, and a
# required page that is still blocked is named honestly instead of offered
# as a dead-end continue button.


def test_new_project_resolves_to_data_upload_as_the_required_start():
    nav = resolve_workflow_navigation(None, getter=_getter({}))

    assert nav.kind == "required"
    assert nav.target.key == "data_upload"
    assert nav.optional_targets == ()
    # Home's next_recommended_step_key is a thin wrapper around the same
    # resolver call, so the two must always agree.
    assert next_workflow_step_key(getter=_getter({})) == nav.target.key


def test_exploratory_continuation_offers_coverage_as_optional_not_required():
    getter = _getter({"transformed_data": object()})

    nav = resolve_workflow_navigation("transform_pipeline", getter=getter)

    assert nav.kind == "required"
    assert nav.target.key == "channel_media_units"
    assert [t.key for t in nav.optional_targets] == ["data_coverage"]


def test_model_comparison_with_one_candidate_stays_optional():
    getter = _getter(
        {"model_trained": True, "model_comparison_candidates": ["candidate-a"]}
    )

    nav = resolve_workflow_navigation("model_training", getter=getter)

    assert nav.kind == "required"
    assert nav.target.key == "diagnostics"
    assert [t.key for t in nav.optional_targets] == ["compare_models"]


def test_causal_graph_not_required_when_no_approved_graph_exists():
    getter = _getter(
        {
            "transformed_data": object(),
            "model_spec": {"markets": ["UK"]},
            "activity_definitions": [{"activity_id": "uk-tv"}],
        }
    )

    nav = resolve_workflow_navigation("structure", getter=getter)

    assert nav.kind == "required"
    assert nav.target.key == "model_config"
    assert [t.key for t in nav.optional_targets] == [
        "causal_graph",
        "market_descriptors",
    ]


def test_blocked_prerequisite_is_named_but_not_offered_as_a_dead_end():
    nav = resolve_workflow_navigation("model_training", getter=_getter({}))

    assert nav.kind == "blocked"
    assert nav.target.key == "diagnostics"
    assert "Fit the model" in nav.target.reason


def test_end_of_workflow_has_no_further_required_target():
    nav = resolve_workflow_navigation("export", getter=_getter({}))

    assert nav.kind == "done"
    assert nav.target is None
    assert nav.optional_targets == ()
