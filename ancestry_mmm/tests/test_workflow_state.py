"""Phase 1 workflow-state regression tests.

These tests enforce the UX/UI implementation brief's acceptance criteria:
presentation state must distinguish access, lifecycle evidence, staleness and
optional pages without changing analytical or governance authority.
"""

from types import SimpleNamespace

from ancestry_mmm.core.causal_graph import CausalGraph
from ancestry_mmm.utils.workflow_state import (
    is_registered_step_complete,
    next_workflow_step_key,
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
