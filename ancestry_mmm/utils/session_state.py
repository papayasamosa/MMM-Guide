"""Session state management for the Ancestry FH MMM app."""

import streamlit as st
from typing import Any
from pathlib import Path

from .config import (
    DEFAULT_FH_PRIORS,
    DEFAULT_DNA_LAG_WEEKS,
    DEFAULT_PARAMS,
    CURVE_BANK_ROOT,
    CURVE_ARTIFACT_ROOT,
)


def init_session_state():
    """Initialize all session state variables with defaults."""
    defaults = {
        # Raw sources: {"media": df, "outcomes": df, "controls": df, ...}
        "raw_sources": {},
        # REQ-COVERAGE-001 S3: append-only immutable source-version history
        # (core.coverage.SourceVersion.to_dict() dicts, any order) - one
        # entry per real upload (never for synthetic demo data, which has no
        # meaningful checksum/provenance to capture). Removing a source from
        # "raw_sources" (the active working set) does not remove its
        # history here - a SourceVersion is a permanent record of what was
        # uploaded, not of what is currently in use.
        "source_versions": [],
        # {source_id: version} - which SourceVersion (if any) actually
        # produced the CURRENT raw_sources[source_id] frame. Distinct from
        # "the latest history entry for this name": loading synthetic demo
        # data replaces raw_sources wholesale without a real upload, so a
        # name that previously had a real upload must not keep displaying
        # that upload's provenance against the now-demo frame. Cleared for
        # a name whenever that name's active frame stops being backed by a
        # real upload (demo load, remove).
        "active_source_upload_version": {},
        "joined_data": None,
        # REQ-COVERAGE-001 S4: the join mode ("inner"/"outer"/"left"/
        # "right") chosen on the most recent "Join sources" click - read
        # back to default the page's Join mode selectbox to what was
        # actually used last time, rather than always resetting to
        # "inner". "join_diagnostics" is the resulting per-source row
        # loss/coverage-gap report (data.pipeline.JoinDiagnostics.to_dict())
        # - never surfaced only implicitly via the joined row count. Both
        # None until a join has been run.
        "join_mode": None,
        "join_diagnostics": None,
        "data_loaded": False,
        "project_name": "ancestry-fh-uk",
        # Transformation pipeline
        "pipeline_steps": [],  # list of TransformStep dicts
        "transformed_data": None,
        "transformed_data_origin": None,
        "standard_joined_data": None,
        # WP2: the official native-frequency frame is kept separate from the
        # exploratory Transform Pipeline output.  It is rebuilt from the
        # source union under an explicit governed calendar and never silently
        # aliases an inner-joined exploratory frame.
        "official_prepared_data": None,
        "official_join_diagnostics": None,
        "official_prepared_data_fingerprint": None,
        "validation_issues": [],
        # Structural model spec (core.schema.ModelSpec as a dict)
        "model_spec": None,
        # Market-specific redesign, Phase 1: market descriptors, currency and
        # channel media-unit mappings (core.market_config.MarketSpecConfig as
        # a dict). Optional and not yet consumed by the fitting pipeline -
        # see docs/market_hierarchy.md.
        "market_spec_config": None,
        # Explicit model-input identity and governed spend mappings (G2A.2).
        "media_input_specs": [],
        "media_cost_mappings": None,
        "media_input_support": [],
        "monetary_spend_support": [],
        "activity_definitions": [],
        # WP2D-ui: the governed weekly outcome-valuation catalogue
        # (core.outcome_valuation.WeeklyOutcomeValuationRecord, REQ-ECON-002)
        # feeding historical Results economic reporting. Append/edit only via
        # the Results page's own editor, which re-validates the whole
        # catalogue (validate_weekly_outcome_valuation_catalogue) before
        # persisting - never silently accepted.
        "outcome_valuation_records": [],
        # Canonical standard source-pack adoption remains separate from the
        # exploratory transformed frame. Activity model inputs are wide only
        # at their explicit model-input boundary; context remains native tidy
        # data plus portable variable metadata.
        "standard_activity_model_input": None,
        "standard_outcome_data": None,
        "standard_context_data": None,
        "context_variable_metadata": [],
        "source_domain_semantics": [],
        # REQ-EXPMODE-001: the durable Experiment Evidence workflow. Source
        # rows ("experiment_evidence_rows") are what the canonical standard
        # source pack carried; the governed registry ("experiment_records" /
        # "experiment_model_uses" / "experiment_compatibility_assessments")
        # is what the analyst explicitly adopted. Rows never auto-adopt; the
        # registry is append-only and survives source replacement.
        "experiment_evidence_rows": [],
        "experiment_records": [],
        "experiment_model_uses": [],
        "experiment_compatibility_assessments": [],
        # REQ-EVENT-001: the governed named-event registry. Occurrences are
        # adopted explicitly from uploaded Context `events` rows; families
        # and response definitions are governed registrations. All three
        # are append-only versioned history and survive source replacement
        # (same category as the experiment registry above).
        "named_event_families": [],
        "named_event_occurrences": [],
        "named_event_response_definitions": [],
        # Canonical outcome catalogue plus semantic groups.  Source import
        # drafts live separately so an existing catalogue is never silently
        # overwritten by a newly uploaded workbook.
        "outcome_definitions": [],
        "outcome_approvals": [],
        "outcome_groups": [],
        "outcome_group_treatments": [],
        "outcome_reconciliation_groups": [],
        "outcome_source_draft": None,
        "outcome_source_draft_groups": [],
        "outcome_source_draft_reconciliation_groups": [],
        "outcome_source_import_status": None,
        # REQ-SEARCH-001: governed SearchObjectDefinition records (branded-
        # search demand, Paid Search spend/delivery/cap, organic-search
        # capture, direct-navigation capture) - core.search_objects. This is
        # always the *current* record per (market, search_object_id) lineage
        # - "search_object_versions" (REQ-SEARCH-001 S10) is the append-only
        # saved version history (list of dicts, oldest first), mirroring
        # "causal_graph"/"causal_graph_versions" below.
        "search_objects": [],
        "search_object_versions": [],
        # REQ-SEARCH-004/005: explicit user-defined intent-group lineage.
        # The approved minimum Brand/Non-Brand records live in core; this
        # list stores only project-specific deeper children and their drafts.
        "search_intent_groups": [],
        "search_intent_group_versions": [],
        "search_intent_model_grain": [],
        # Optional Candidate A identity restored separately from its
        # observations so the analyst can attach a new exact observation
        # upload without inventing a Search object mapping.
        "search_candidate_a_spec": None,
        # REQ-GRAPH-001: the current CausalGraph version being edited (draft
        # or approved), as a dict (core.causal_graph.CausalGraph.to_dict()).
        # None until a graph is first saved on the Causal Graph page -
        # every project today, since this is optional and MediaOutcomePathway/
        # FunnelLink above remain the sole compilation input until a graph
        # is approved. "causal_graph_versions" is the append-only saved
        # version history (list of dicts, oldest first). Neither is cleared
        # by clear_model_state() - a graph is analyst-declared structural
        # configuration, not a fit-derived artefact, same category as
        # model_spec/media_outcome_pathways. "causal_graph_compiled_
        # structural_fingerprint" is the structural fingerprint bound the
        # last time "Prepare model configuration" succeeded - compared
        # against the live graph's current structural fingerprint to show
        # whether the compiled configuration is still current or has gone
        # stale since a structural edit.
        "causal_graph": None,
        "causal_graph_versions": [],
        "causal_graph_compiled_structural_fingerprint": None,
        # REQ-COVERAGE-001 S1/S3: the current VariableCoverageMatrix version
        # (core.coverage.VariableCoverageMatrix.to_dict()), reviewable before
        # model preparation. None until first built on the Data Coverage
        # page - every project today, since this is optional and nothing
        # downstream yet consumes it to alter prepared data (WP5/
        # FR-MOD-015 is unresolved - see REQ-COVERAGE-001 S6).
        # "variable_coverage_matrix_versions" is the append-only saved
        # version history (list of dicts, oldest first), mirroring
        # "causal_graph"/"causal_graph_versions" above. Neither is cleared
        # by clear_model_state() - a coverage matrix is analyst-declared
        # data governance, not a fit-derived artefact, same category as
        # causal_graph/search_objects.
        "variable_coverage_matrix": None,
        "variable_coverage_matrix_versions": [],
        # PR #156: session-only (never exported/imported) fingerprint of
        # the transformed_data the current variable_coverage_matrix was
        # actually built against - compared live on the Data Coverage page
        # against the current transformed_data's own fingerprint to detect
        # a matrix that has gone stale relative to a later Transform
        # Pipeline edit, or that was restored from an imported project
        # bundle (which never carries this key). Mirrors
        # causal_graph_compiled_structural_fingerprint's live-comparison
        # staleness pattern.
        "variable_coverage_matrix_built_against_fingerprint": None,
        # WP6: last read-only official-preparation decision. This is a
        # derived review result, never a source-data or conversion artefact;
        # it is cleared whenever model/data state is invalidated.
        "official_preparation_result": None,
        "official_capability_report": None,
        # Reusable pre-fit support/transform and prior-predictive evidence.
        # This is diagnostic-only and is independently fingerprinted; it is
        # not a fit, convergence result, or reporting approval.
        "prefit_identifiability": None,
        # Deterministic, leakage-safe surrogate evidence.  This is separate
        # from Bayesian prior-predictive and sampler evidence and is never a
        # fit, channel-selection rule, or production approval.
        "prefit_screening": None,
        "prefit_analyst_rationale_input": "",
        # Optional explicit project-calendar configuration. It is intentionally
        # empty by default: official preparation must not infer a calendar
        # from source intersection or observed dates.
        "canonical_calendar": None,
        # Model configuration
        "prior_config": dict(DEFAULT_FH_PRIORS),
        "dna_lag_weeks": DEFAULT_DNA_LAG_WEEKS,
        "mcmc_draws": DEFAULT_PARAMS["mcmc_draws"],
        "mcmc_tune": DEFAULT_PARAMS["mcmc_tune"],
        "mcmc_chains": DEFAULT_PARAMS["mcmc_chains"],
        "mcmc_target_accept": DEFAULT_PARAMS["mcmc_target_accept"],
        # Durable fit identity: the worker records this seed with the
        # sampler settings so a completed artifact is reproducible/auditable.
        "mcmc_random_seed": 42,
        # "shared" (Model A, core.hierarchical_model) or "market_specific"
        # (Model C, core.market_specific_model) - a user preference like the
        # priors above, not a per-fit artifact, so clear_model_state() does
        # not reset it: retraining under the same chosen structure is the
        # common case. See docs/model_validation.md.
        "model_type": "shared",
        # Snapshots of fitted models' scorecards for side-by-side comparison
        # (core.model_comparison.ModelComparisonCandidate dicts) - accumulated
        # one at a time as the user fits candidates, not auto-populated.
        "model_comparison_candidates": [],
        # Model artifacts
        "frame": None,  # output of prepare_fh_modeling_frame
        "model": None,
        "model_meta": None,  # FHModelMeta
        "trace": None,
        "model_trained": False,
        "posterior_params": None,
        # Fresh UUID minted on every successful fit (see pages/05_Model_Training.py) -
        # part of a model run's identity alongside the data/spec/posterior
        # fingerprints computed on demand from the artifacts above (core.fingerprint).
        "model_run_id": None,
        # Diagnostics
        "scorecard": None,
        "backtest_results": None,
        # PR 82B: canonical diagnostics/validation evidence chain, centrally
        # initialised so every reader can rely on the key existing rather
        # than falling back to get_state()'s own default=None each time.
        # "diagnostics_artefact" (application.diagnostics_service.
        # DiagnosticsArtefact) is the canonical evidence container;
        # "diag_result" is the full DiagnosticsResult wrapper for this
        # session's transient UI messages. "validation_policy" is the
        # configured ThresholdPolicy (as a dict); "validation_results" is
        # the list of per-gate ValidationResult dicts; "approval_readiness"
        # is the serialised ApprovalReadiness domain object (the only key
        # any other page or persistence layer should read for readiness);
        # "validation_service_result" is the full ValidationServiceResult
        # wrapper for this session's own transient UI messages.
        "diagnostics_artefact": None,
        "diag_result": None,
        "validation_policy": None,
        "validation_results": None,
        "approval_readiness": None,
        "validation_service_result": None,
        # Model approval gate (core.approval.ModelApproval as a dict) - required
        # before a model's curves can be saved to the curve bank or used to plan
        # scenarios; reset by clear_model_state() whenever the model changes.
        "model_approval": None,
        # Separate audit trail for mask-only pathway migration review.
        "migration_review": None,
        # Curve bank
        "curve_bank_entry_id": None,
        "calibration_records": [],
        # Scenario planning
        "scenarios": [],
        "active_scenario": None,
        "project_notes": "",
        # Session-only bundle activity checkpoints.  These are evidence that
        # an export/import action occurred, not a proxy for page availability.
        "export_last_bundle_summary": None,
        "export_last_import_summary": None,
        # UI state
        "current_page": 0,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_state(key: str, default: Any = None) -> Any:
    return st.session_state.get(key, default)


def set_state(key: str, value: Any) -> None:
    st.session_state[key] = value


def update_state(**kwargs) -> None:
    for key, value in kwargs.items():
        st.session_state[key] = value


def curve_bank_dir() -> Path:
    """Per-project curve bank directory (created on first write)."""
    name = get_state("project_name", "default")
    return CURVE_BANK_ROOT / name


def curve_artifact_store_dir() -> Path:
    """Per-project official curve artifact store directory (created on first write)."""
    name = get_state("project_name", "default")
    return CURVE_ARTIFACT_ROOT / name


def clear_model_state() -> None:
    """Clear all model-related state (useful when data or spec changes)."""
    model_keys = [
        "frame",
        "official_prepared_data",
        "official_join_diagnostics",
        "official_prepared_data_fingerprint",
        "model",
        "model_meta",
        "trace",
        "model_trained",
        "posterior_params",
        "scorecard",
        "backtest_results",
        "curve_bank_entry_id",
        # A retrained (or newly loaded) model has not been reviewed yet -
        # any prior approval no longer applies to it. model_run_id resets too,
        # since it identifies a specific fit event, not just "a model exists".
        "model_approval",
        "model_run_id",
        # PR 82B: diagnostics/validation evidence is bound to the model run
        # it was computed for - a retrained model must not keep displaying
        # (or letting readiness/approval trust) evidence for the previous
        # fit. "validation_policy" is deliberately NOT cleared here - it is
        # project-level configuration, not derived from any particular fit.
        "diagnostics_artefact",
        "diag_result",
        "validation_results",
        "approval_readiness",
        "validation_service_result",
        "official_preparation_result",
        "official_capability_report",
        "prefit_identifiability",
        "prefit_screening",
        "prefit_analyst_rationale_input",
    ]
    for key in model_keys:
        st.session_state[key] = None
    st.session_state["model_trained"] = False


def invalidate_governance_evidence() -> None:
    """Clear the four keys that represent evidence/approval evaluated
    against a specific diagnostics artefact/policy/model-identity
    combination: ``validation_results``, ``approval_readiness``,
    ``validation_service_result``, ``model_approval``.

    Narrower than ``clear_model_state()`` - deliberately does NOT touch
    ``diagnostics_artefact`` itself (the caller just replaced or is about to
    replace it), nor the trace/frame/posterior/model_run_id artefacts a full
    retrain would invalidate. Call this in the same action that recomputes
    the scorecard, replaces the diagnostics artefact via a backtest, or
    otherwise changes what evidence the four cleared keys were bound to -
    a stale approval or readiness must never survive to the next rerun.

    UX-018 (overnight UI/UX review, third pass): every call site of this
    function recomputes/replaces the diagnostics artefact (Compute
    scorecard, prior predictive check, backtest, historical validation,
    etc.) on a page an analyst may already have approved. Before this fix,
    an existing named ``model_approval`` (reviewer, date, notes) was wiped
    here with no on-screen trace at all - the analyst would simply find an
    empty "Approve this model" form where a "Approved by <name>" confirmation
    used to be, with nothing explaining that their own prior action (e.g.
    clicking "Compute scorecard") was what caused it. The page's own
    "no longer matches the current model, policy, or readiness evidence"
    messages only cover the *separate* case where staleness is caught lazily
    on a later rerun (see ``readiness_matches_current_evidence`` /
    ``require_matching_approval`` in ``core.validation_policy`` /
    ``core.approval``) - they never fire here because this function already
    clears ``model_approval`` before that downstream check ever runs. Warning
    once, centrally, here (rather than duplicating the message at each of the
    six call sites in ``pages/06_Diagnostics.py``) guarantees an analyst is
    told exactly what was lost and why, every time, without changing which
    keys are cleared or when - presentation only, no governance/timing change.
    """
    _had_approval = bool(st.session_state.get("model_approval"))
    _approved_by = (
        st.session_state["model_approval"].get("approved_by") if _had_approval else None
    )
    for key in (
        "validation_results",
        "approval_readiness",
        "validation_service_result",
        "model_approval",
    ):
        st.session_state[key] = None
    if _had_approval:
        st.warning(
            "This action produced new diagnostics evidence, so the "
            "previous model approval"
            + (f" (by **{_approved_by}**)" if _approved_by else "")
            + " and any evaluated readiness no longer apply and have been "
            "cleared. Review the updated evidence and re-approve below if "
            "it is still appropriate."
        )


def get_workflow_progress() -> "tuple[int, int]":
    """Get the registry-derived compatibility progress tuple.

    The shell no longer presents this as a course-style counter.  The tuple
    is retained because the portable project bundle records it, but its
    values now come from the same lifecycle state used by Home, the sidebar,
    and page headers; there is no separately maintained step map.
    """
    from .workflow_state import workflow_progress

    return workflow_progress(getter=get_state)


def is_step_complete(step: int) -> bool:
    from .workflow_state import is_registered_step_complete

    return is_registered_step_complete(step, getter=get_state)
