"""Canonical presentation state for the analyst workflow.

This module is deliberately independent of Streamlit.  It translates the
authoritative project objects and persisted artefacts into two separate
concepts:

* ``access_status`` - whether a page is available, blocked by a prerequisite,
  or optional; and
* ``lifecycle_status`` - what evidence exists for that page (not started,
  configured, draft, approved, validated, complete, saved, stale, ...).

The same state is consumed by the sidebar, page headers, Home, and the
legacy workflow-progress persistence field.  It is presentation state only;
it does not grant analytical or governance authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ancestry_mmm.core.causal_graph import CausalGraph
from ancestry_mmm.core.curve_artifact import load_curve_artifact_store
from ancestry_mmm.core.fingerprint import fingerprint_dataframe
from ancestry_mmm.core.market_config import MarketSpecConfig
from ancestry_mmm.utils.config import CURVE_ARTIFACT_ROOT

from .workflow import TOTAL_STEPS, WORKFLOW_STEPS, step_number

StateGetter = Callable[[str, Any], Any]

_OPTIONAL_PAGES = {
    "data_coverage",
    "causal_graph",
    "market_descriptors",
    "compare_models",
}

_APPROVAL_IDENTITY_FIELDS = (
    "model_run_id",
    "data_fingerprint",
    "model_spec_fingerprint",
    "posterior_fingerprint",
)


@dataclass(frozen=True)
class WorkflowPageState:
    """Presentation state for one workflow page.

    ``satisfied`` is the routing/completion decision for the page's existing
    lifecycle.  It is intentionally separate from ``lifecycle_status`` so a
    draft or merely configured optional page can be shown honestly without
    becoming a prerequisite for the next required action.
    """

    key: str
    access_status: str
    lifecycle_status: str
    satisfied: bool
    optional: bool = False
    reason: str = ""

    @property
    def display_status(self) -> str:
        """The shared status-badge key used by all shell surfaces."""

        return (
            self.access_status
            if self.access_status == "blocked"
            else self.lifecycle_status
        )


def _get(getter: StateGetter, key: str, default: Any = None) -> Any:
    """Read a state value while keeping test/integration getters flexible."""

    try:
        return getter(key, default)
    except TypeError:
        return getter(key)  # type: ignore[misc]


def _state(
    key: str,
    lifecycle_status: str,
    *,
    satisfied: bool,
    access_status: str = "available",
    optional: bool = False,
    reason: str = "",
) -> WorkflowPageState:
    return WorkflowPageState(
        key=key,
        access_status=access_status,
        lifecycle_status=lifecycle_status,
        satisfied=satisfied,
        optional=optional,
        reason=reason,
    )


def _official_preparation_summary(getter: StateGetter) -> tuple[Optional[str], str]:
    """Return presentation-only official-preparation state for workflow UI.

    The frequency assessor remains the authority for the raw decision.  This
    helper only turns its persisted result into the small vocabulary consumed
    by page readiness and Home/sidebar copy; it never changes whether a frame
    may be prepared.
    """

    result = _get(getter, "official_preparation_result")
    if not isinstance(result, dict) or not result:
        return None, ""
    if result.get("ready") is True or result.get("status") == "ready":
        return "ready", "Official preparation is ready."

    status = result.get("status")
    if status == "unsupported_no_approved_method":
        return (
            "blocked",
            "Official preparation is unavailable because no approved method "
            "currently exists for converting one or more source frequencies "
            "for official modelling.",
        )
    if status == "method_available":
        return (
            "blocked",
            "Official preparation remains blocked until the governed frequency "
            "conversion executor is validated.",
        )
    if status == "unsupported_definition_break":
        return (
            "blocked",
            "Official preparation remains blocked by a frequency definition "
            "break that needs an explicit resolution.",
        )
    if status == "unsupported_leakage":
        return (
            "blocked",
            "Official preparation remains blocked by a frequency treatment "
            "that is outside the approved preparation boundary.",
        )
    return (
        "blocked",
        "Official preparation remains blocked until the required coverage, "
        "calendar, or frequency decisions are resolved.",
    )


def _data_coverage_status(getter: StateGetter, key: str) -> WorkflowPageState:
    matrix = _get(getter, "variable_coverage_matrix")
    transformed = _get(getter, "official_prepared_data")
    if transformed is None:
        transformed = _get(getter, "transformed_data")
    if matrix is None:
        if transformed is None:
            return _state(
                key,
                "optional",
                satisfied=True,
                access_status="optional",
                optional=True,
                reason="Coverage review is optional for the current workflow.",
            )
        return _state(
            key,
            "exploratory",
            satisfied=True,
            access_status="optional",
            optional=True,
            reason=(
                "Coverage review remains optional for exploratory continuation, "
                "but a reviewed matrix is required before official preparation."
            ),
        )

    built_against = _get(getter, "variable_coverage_matrix_built_against_fingerprint")
    if built_against and transformed is not None:
        try:
            current = fingerprint_dataframe(transformed)
        except (TypeError, ValueError, KeyError):
            current = None
        if current and current != built_against:
            return _state(
                key,
                "stale",
                satisfied=True,
                optional=True,
                reason="The coverage matrix was built against an older transformed dataset.",
            )
    return _state(
        key,
        "configured",
        satisfied=True,
        optional=True,
        reason="A coverage matrix exists; freshness is shown when its source fingerprint is available.",
    )


def _causal_graph_status(getter: StateGetter, key: str) -> WorkflowPageState:
    graph_dict = _get(getter, "causal_graph")
    if not graph_dict:
        return _state(
            key,
            "optional",
            satisfied=True,
            access_status="optional",
            optional=True,
            reason="The causal graph is optional for the current workflow.",
        )
    try:
        graph = CausalGraph.from_dict(graph_dict)
    except (TypeError, ValueError, KeyError):
        return _state(
            key,
            "unavailable",
            satisfied=True,
            optional=True,
            reason="The saved causal graph could not be read safely.",
        )

    compiled = _get(getter, "causal_graph_compiled_structural_fingerprint")
    if compiled and compiled != graph.structural_fingerprint():
        return _state(
            key,
            "stale",
            satisfied=True,
            optional=True,
            reason="The graph structure changed after model configuration was prepared.",
        )
    return _state(
        key,
        graph.status,
        satisfied=True,
        optional=True,
        reason=(
            "Approved graph version is current."
            if graph.status == "approved"
            else "A draft graph exists; it is not the approved structural authority."
        ),
    )


def _model_approval_is_current(getter: StateGetter) -> bool:
    approval = _get(getter, "model_approval")
    if not isinstance(approval, dict) or not approval:
        return False

    # Some deterministic fixtures carry an explicit status.  Honour that
    # explicit lifecycle value, while still checking a bound run when one is
    # present.  Real ModelApproval records use the four identity fields below.
    if approval.get("status"):
        if approval.get("status") != "approved":
            return False
        current_run = _get(getter, "model_run_id")
        bound_run = approval.get("model_run_id")
        return not current_run or not bound_run or bound_run == current_run

    if not all(approval.get(field) for field in _APPROVAL_IDENTITY_FIELDS):
        return False
    current_run = _get(getter, "model_run_id")
    return bool(current_run and approval.get("model_run_id") == current_run)


def _diagnostics_status(getter: StateGetter, key: str) -> WorkflowPageState:
    trained = bool(_get(getter, "model_trained"))
    if not trained:
        return _state(
            key,
            "blocked",
            satisfied=False,
            access_status="blocked",
            reason="Fit the model before computing diagnostics.",
        )

    artefact = _get(getter, "diagnostics_artefact")
    scorecard = _get(getter, "scorecard")
    readiness = _get(getter, "approval_readiness")
    if artefact is None and scorecard is None:
        return _state(
            key,
            "not_started",
            satisfied=False,
            reason="Diagnostics evidence has not been computed for this fit.",
        )

    if artefact is None:
        return _state(
            key,
            "configured",
            satisfied=False,
            reason="A scorecard exists, but the canonical diagnostics artefact is unavailable.",
        )

    artefact_fingerprint = getattr(artefact, "fingerprint", None)
    if callable(artefact_fingerprint):
        artefact_fingerprint = artefact_fingerprint()
    if isinstance(readiness, dict):
        readiness_fp = readiness.get(
            "diagnostic_artefact_fingerprint"
        ) or readiness.get("diagnostics_artefact_fingerprint")
        if (
            readiness_fp
            and artefact_fingerprint
            and readiness_fp != artefact_fingerprint
        ):
            return _state(
                key,
                "stale",
                satisfied=False,
                reason="Readiness evidence was evaluated against an older diagnostics artefact.",
            )

        overall_ready = readiness.get("overall_ready")
        if overall_ready is True:
            if _model_approval_is_current(getter):
                return _state(
                    key,
                    "validated",
                    satisfied=True,
                    reason="Diagnostics and approval evidence are current for this fit.",
                )
            return _state(
                key,
                "review",
                satisfied=False,
                reason="Readiness passes; review and record model approval on Diagnostics.",
            )
        if overall_ready is False:
            return _state(
                key,
                "blocked",
                satisfied=False,
                reason="One or more validation gates still block model approval.",
            )

    return _state(
        key,
        "configured",
        satisfied=False,
        reason="Diagnostics evidence exists; evaluate readiness before approval.",
    )


def _official_curve_status(getter: StateGetter, key: str) -> WorkflowPageState:
    if not _model_approval_is_current(getter):
        return _state(
            key,
            "blocked",
            satisfied=False,
            access_status="blocked",
            reason="An approved current model is required before official curve generation.",
        )

    project_name = _get(getter, "project_name", "default") or "default"
    store_dir = Path(CURVE_ARTIFACT_ROOT) / str(project_name)
    try:
        store = load_curve_artifact_store(store_dir, raise_on_malformed=False)
    except (OSError, TypeError, ValueError):
        return _state(
            key,
            "unavailable",
            satisfied=False,
            reason="The official curve artifact store could not be read.",
        )

    if not store.loaded:
        if store.audit:
            return _state(
                key,
                "stale",
                satisfied=False,
                reason="An official curve artifact exists but could not be loaded as current evidence.",
            )
        return _state(
            key,
            "not_started",
            satisfied=False,
            reason="No official curve artifact has been generated for this project.",
        )

    current_run = _get(getter, "model_run_id")
    approval = _get(getter, "model_approval") or {}
    for artifact in store.loaded:
        metadata = artifact.metadata
        snapshot = metadata.model_identity_snapshot or {}
        if (
            metadata.format_status == "current"
            and metadata.historical_integrity == "intact"
            and current_run
            and snapshot.get("model_run_id") == current_run
            and all(
                not approval.get(field) or snapshot.get(field) == approval.get(field)
                for field in _APPROVAL_IDENTITY_FIELDS
            )
        ):
            return _state(
                key,
                "complete",
                satisfied=True,
                reason="A current official curve artifact is present in the governed store.",
            )
    return _state(
        key,
        "stale",
        satisfied=False,
        reason="Only older or mismatched official curve artifacts were found.",
    )


def _scenario_status(getter: StateGetter, key: str) -> WorkflowPageState:
    if not _model_approval_is_current(getter):
        return _state(
            key,
            "blocked",
            satisfied=False,
            access_status="blocked",
            reason="Approve the current model on Diagnostics before planning.",
        )
    scenarios = _get(getter, "scenarios") or []
    if not scenarios:
        return _state(
            key,
            "not_started",
            satisfied=False,
            reason="No scenario has been saved yet.",
        )
    if any(
        isinstance(scenario, dict)
        and (
            scenario.get("stale") is True
            or scenario.get("status") in {"stale", "invalid", "legacy_unverified"}
        )
        for scenario in scenarios
    ):
        return _state(
            key,
            "stale",
            satisfied=False,
            reason="At least one saved scenario is marked stale or invalid.",
        )
    return _state(
        key,
        "saved",
        satisfied=True,
        reason="At least one saved scenario is present.",
    )


def workflow_page_state(
    key: str,
    *,
    getter: Optional[StateGetter] = None,
) -> WorkflowPageState:
    """Evaluate one page from existing project state and artefacts."""

    if getter is None:
        from .session_state import get_state

        getter = get_state

    data_loaded = bool(_get(getter, "data_loaded"))
    transformed = _get(getter, "transformed_data") is not None
    spec = bool(_get(getter, "model_spec"))
    frame = _get(getter, "frame") is not None
    trained = bool(_get(getter, "model_trained"))
    approved = _model_approval_is_current(getter)

    if key == "data_upload":
        return _state(
            key, "complete" if data_loaded else "not_started", satisfied=data_loaded
        )
    if key == "transform_pipeline":
        if transformed:
            return _state(key, "complete", satisfied=True)
        # Merge-readiness pass (2026-08-29): this canonical status previously
        # had no vocabulary for "sources joined but not yet transformed" - it
        # collapsed straight from "blocked"/"not_started" to "complete", so
        # it fell back to "not_started" for this intermediate state even
        # though the page's own header badge (02_Transform_Pipeline.py,
        # `_header_badges = ["current"]` once `joined_data` is set)
        # correctly renders "In progress" for the same state. Once the
        # overnight UI/UX pass's UX-004 fix made this page's header update
        # immediately after "Join sources" (previously it lagged one rerun
        # behind), this mismatch became a same-view, every-time
        # contradiction - "· Not started" and "· In progress" badges shown
        # side by side - rather than a rare, click-order-dependent artefact.
        # Recognising "current" here for the same condition the page itself
        # already uses removes the caller/canonical mismatch at its source,
        # matching UX-013's Causal Graph badge-dedup fix. Presentation only:
        # does not change `satisfied` (still False - the page's downstream
        # gating is unaffected), and pages the reason string only.
        joined = _get(getter, "joined_data") is not None
        if joined and data_loaded:
            return _state(key, "current", satisfied=False)
        return _state(
            key,
            "not_started" if data_loaded else "blocked",
            satisfied=False,
            access_status="available" if data_loaded else "blocked",
            reason="Load data before joining and transforming sources."
            if not data_loaded
            else "",
        )
    if key == "data_coverage":
        return _data_coverage_status(getter, key)
    if key == "structure":
        if spec:
            return _state(key, "configured", satisfied=True)
        activities = bool(_get(getter, "activity_definitions"))
        return _state(
            key,
            "not_started" if transformed else "blocked",
            satisfied=False,
            access_status="available" if transformed else "blocked",
            reason=(
                "Transform the joined data before defining model structure."
                if not transformed
                else "Map at least one governed activity before defining model structure."
                if not activities
                else ""
            ),
        )
    if key == "causal_graph":
        return _causal_graph_status(getter, key)
    if key == "channel_media_units":
        configured = bool(_get(getter, "activity_definitions"))
        return _state(
            key,
            "configured" if configured else "not_started" if transformed else "blocked",
            satisfied=configured,
            access_status="available" if transformed else "blocked",
            optional=False,
            reason=(
                "Prepare the joined data before mapping activities."
                if not transformed
                else "Create and save governed activity mappings before Model Structure."
                if not configured
                else "Activity and variable mappings are available."
            ),
        )
    if key == "market_descriptors":
        config = MarketSpecConfig.from_dict(_get(getter, "market_spec_config"))
        configured = bool(config.market_profiles)
        return _state(
            key,
            "configured" if configured else "optional",
            satisfied=True,
            access_status="available" if configured else "optional",
            optional=True,
            reason="Market profile configuration exists."
            if configured
            else "Optional context page.",
        )
    if key == "model_config":
        official_status, official_reason = _official_preparation_summary(getter)
        if frame and official_status == "blocked":
            return _state(
                key,
                "exploratory",
                satisfied=True,
                access_status="available" if spec else "blocked",
                reason=(
                    "An exploratory modelling frame exists, but it does not "
                    "satisfy official preparation. " + official_reason
                ),
            )
        if frame:
            return _state(
                key,
                "complete",
                satisfied=True,
                access_status="available" if spec else "blocked",
                reason="Official preparation is ready for this model frame."
                if official_status == "ready"
                else "A prepared model frame exists.",
            )
        if spec and official_status == "blocked":
            return _state(
                key,
                "blocked",
                satisfied=False,
                access_status="available",
                reason=official_reason,
            )
        return _state(
            key,
            "not_started" if spec else "blocked",
            satisfied=frame,
            access_status="available" if spec else "blocked",
            reason="Define model structure before preparing the model."
            if not spec
            else "",
        )
    if key == "model_training":
        return _state(
            key,
            "complete" if trained else "not_started" if frame else "blocked",
            satisfied=trained,
            access_status="available" if frame else "blocked",
            reason="Prepare the model before fitting it." if not frame else "",
        )
    if key == "compare_models":
        configured = bool(_get(getter, "model_comparison_candidates"))
        return _state(
            key,
            "configured" if configured else "optional",
            satisfied=True,
            access_status="available" if configured else "optional",
            optional=True,
            reason="Candidate model comparisons exist."
            if configured
            else "Optional comparison page.",
        )
    if key == "diagnostics":
        return _diagnostics_status(getter, key)
    if key == "curve_bank":
        if not approved:
            return _state(
                key,
                "blocked",
                satisfied=False,
                access_status="blocked",
                reason="Approve the current model before saving curve-bank entries.",
            )
        has_entry = bool(_get(getter, "curve_bank_entry_id"))
        return _state(
            key, "complete" if has_entry else "not_started", satisfied=has_entry
        )
    if key == "official_curve_generation":
        return _official_curve_status(getter, key)
    if key == "scenario_planner":
        return _scenario_status(getter, key)
    if key == "export":
        exported = bool(
            _get(getter, "export_last_bundle_summary")
            or _get(getter, "export_last_import_summary")
        )
        return _state(
            key,
            "complete" if exported else "not_started",
            satisfied=exported,
            reason="Build or import a project bundle to record an export checkpoint."
            if not exported
            else "",
        )
    return _state(key, "not_started", satisfied=False)


def workflow_page_states(
    *, getter: Optional[StateGetter] = None
) -> tuple[WorkflowPageState, ...]:
    """Evaluate all registered workflow pages in canonical order."""

    return tuple(
        workflow_page_state(step["key"], getter=getter) for step in WORKFLOW_STEPS
    )


@dataclass(frozen=True)
class WorkflowNavigationTarget:
    """One page a navigation resolver may point the analyst toward."""

    key: str
    label: str
    reason: str = ""


@dataclass(frozen=True)
class WorkflowNavigation:
    """What an analyst should do next, resolved from a point in the workflow
    (or from the very start, for Home) against the same page-state evidence
    that drives the sidebar and readiness badges.

    ``kind`` is one of:

    * ``"required"`` - `target` is the next required page, and it is
      currently available.
    * ``"blocked"`` - `target` is the next required page, but it is not yet
      available; `target.reason` names the unmet prerequisite. This lets a
      caller name the real next requirement without offering a dead-end
      continue action for it.
    * ``"done"`` - no required page remains unsatisfied; `target` is None.

    An optional page is never returned as `target` - it can only appear in
    `optional_targets`, the optional pages encountered between the resolved
    starting point and `target` (or the end of the workflow, for "done").
    This is what keeps an optional page such as Coverage & Gaps, Causal
    Graph or Model Comparison from ever being presented as the required next
    step (see docs/decision_log.md, UI-WP1).
    """

    kind: str
    target: Optional[WorkflowNavigationTarget]
    optional_targets: tuple[WorkflowNavigationTarget, ...] = ()


def resolve_workflow_navigation(
    current_key: Optional[str] = None, *, getter: Optional[StateGetter] = None
) -> WorkflowNavigation:
    """The single navigation resolver shared by Home and every page footer.

    Scans WORKFLOW_STEPS forward from just after `current_key`'s position
    (or from the very first page when `current_key` is None or not a
    registered step - e.g. Home) for the next required page that is not yet
    satisfied. Optional pages encountered along the way are collected into
    `optional_targets` instead of ever becoming the primary target.
    """

    start_index = 0
    for i, step in enumerate(WORKFLOW_STEPS):
        if step["key"] == current_key:
            start_index = i + 1
            break

    optional_targets: list[WorkflowNavigationTarget] = []
    for step in WORKFLOW_STEPS[start_index:]:
        state = workflow_page_state(step["key"], getter=getter)
        if state.optional:
            optional_targets.append(
                WorkflowNavigationTarget(
                    key=step["key"], label=step["label"], reason=state.reason
                )
            )
            continue
        if state.satisfied:
            continue
        target = WorkflowNavigationTarget(
            key=step["key"], label=step["label"], reason=state.reason
        )
        kind = "blocked" if state.access_status == "blocked" else "required"
        return WorkflowNavigation(
            kind=kind, target=target, optional_targets=tuple(optional_targets)
        )

    return WorkflowNavigation(
        kind="done", target=None, optional_targets=tuple(optional_targets)
    )


def next_workflow_step_key(*, getter: Optional[StateGetter] = None) -> Optional[str]:
    """Return the first unsatisfied required page in canonical order.

    A thin compatibility wrapper around `resolve_workflow_navigation` (called
    from the start of the workflow) for callers that only need the key.
    """

    nav = resolve_workflow_navigation(None, getter=getter)
    return nav.target.key if nav.target is not None else None


def workflow_progress(*, getter: Optional[StateGetter] = None) -> tuple[int, int]:
    """Return a compatibility progress tuple derived from the registry.

    The numeric tuple remains only for saved-bundle compatibility.  It is not
    a claim that the analyst follows a linear course; the shell presents
    lifecycle and workflow-area state instead.
    """

    next_key = next_workflow_step_key(getter=getter)
    if next_key is None:
        return TOTAL_STEPS, TOTAL_STEPS
    return step_number(next_key) or TOTAL_STEPS, TOTAL_STEPS


def is_registered_step_complete(
    step: int, *, getter: Optional[StateGetter] = None
) -> bool:
    """Check completion by canonical page state, not by numeric position."""

    if step < 1 or step > len(WORKFLOW_STEPS):
        return False
    key = WORKFLOW_STEPS[step - 1]["key"]
    return workflow_page_state(key, getter=getter).satisfied
