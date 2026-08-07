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
        "joined_data": None,
        "data_loaded": False,
        "project_name": "ancestry-fh-uk",
        # Transformation pipeline
        "pipeline_steps": [],  # list of TransformStep dicts
        "transformed_data": None,
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
        # REQ-SEARCH-001: governed SearchObjectDefinition records (branded-
        # search demand, Paid Search spend/delivery/cap, organic-search
        # capture, direct-navigation capture) - core.search_objects.
        "search_objects": [],
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
        # Model configuration
        "prior_config": dict(DEFAULT_FH_PRIORS),
        "dna_lag_weeks": DEFAULT_DNA_LAG_WEEKS,
        "mcmc_draws": DEFAULT_PARAMS["mcmc_draws"],
        "mcmc_tune": DEFAULT_PARAMS["mcmc_tune"],
        "mcmc_chains": DEFAULT_PARAMS["mcmc_chains"],
        "mcmc_target_accept": DEFAULT_PARAMS["mcmc_target_accept"],
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
    """
    for key in (
        "validation_results",
        "approval_readiness",
        "validation_service_result",
        "model_approval",
    ):
        st.session_state[key] = None


def get_workflow_progress() -> "tuple[int, int]":
    """Get current workflow progress (current_step, total_steps).

    Steps 4 (Channel & Media-Unit Mapping), 5 (Market Descriptors) and 8
    (Compare Models) are optional - nothing downstream requires them - so
    there's no session-state signal to gate on. Reaching the step after an
    optional one doesn't require having visited the optional step first;
    this just points the user at the first optional step as the next
    recommended stop once the previous required step is done.
    """
    total_steps = 12

    if not get_state("data_loaded"):
        return 1, total_steps
    if get_state("transformed_data") is None:
        return 2, total_steps
    if not get_state("model_spec"):
        return 3, total_steps
    if get_state("frame") is None:
        return 4, total_steps
    if not get_state("model_trained"):
        return 7, total_steps
    if not get_state("scorecard"):
        return 8, total_steps
    if not get_state("curve_bank_entry_id"):
        return 10, total_steps
    if not get_state("scenarios"):
        return 11, total_steps

    return 12, total_steps


def is_step_complete(step: int) -> bool:
    current, _ = get_workflow_progress()
    return current > step
