"""Session state management for the Ancestry FH MMM app."""

import streamlit as st
from typing import Any
from pathlib import Path

from .config import DEFAULT_FH_PRIORS, DEFAULT_DNA_LAG_WEEKS, DEFAULT_PARAMS, CURVE_BANK_ROOT


def init_session_state():
    """Initialize all session state variables with defaults."""
    defaults = {
        # Raw sources: {"media": df, "outcomes": df, "controls": df, ...}
        "raw_sources": {},
        "joined_data": None,
        "data_loaded": False,
        "project_name": "ancestry-fh-uk",

        # Transformation pipeline
        "pipeline_steps": [],   # list of TransformStep dicts
        "transformed_data": None,
        "validation_issues": [],

        # Structural model spec (core.schema.ModelSpec as a dict)
        "model_spec": None,

        # Model configuration
        "prior_config": dict(DEFAULT_FH_PRIORS),
        "dna_lag_weeks": DEFAULT_DNA_LAG_WEEKS,
        "mcmc_draws": DEFAULT_PARAMS["mcmc_draws"],
        "mcmc_tune": DEFAULT_PARAMS["mcmc_tune"],
        "mcmc_chains": DEFAULT_PARAMS["mcmc_chains"],
        "mcmc_target_accept": DEFAULT_PARAMS["mcmc_target_accept"],

        # Model artifacts
        "frame": None,           # output of prepare_fh_modeling_frame
        "model": None,
        "model_meta": None,      # FHModelMeta
        "trace": None,
        "model_trained": False,
        "posterior_params": None,

        # Diagnostics
        "scorecard": None,
        "backtest_results": None,

        # Model approval gate (core.approval.ModelApproval as a dict) - required
        # before a model's curves can be saved to the curve bank or used to plan
        # scenarios; reset by clear_model_state() whenever the model changes.
        "model_approval": None,

        # Curve bank
        "curve_bank_entry_id": None,
        "calibration_records": [],

        # Scenario planning
        "scenarios": [],
        "active_scenario": None,

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


def clear_model_state() -> None:
    """Clear all model-related state (useful when data or spec changes)."""
    model_keys = [
        "frame", "model", "model_meta", "trace", "model_trained", "posterior_params",
        "scorecard", "backtest_results", "curve_bank_entry_id",
        # A retrained (or newly loaded) model has not been reviewed yet -
        # any prior approval no longer applies to it.
        "model_approval",
    ]
    for key in model_keys:
        st.session_state[key] = None
    st.session_state["model_trained"] = False


def get_workflow_progress() -> "tuple[int, int]":
    """Get current workflow progress (current_step, total_steps)."""
    total_steps = 9

    if not get_state("data_loaded"):
        return 1, total_steps
    if get_state("transformed_data") is None:
        return 2, total_steps
    if not get_state("model_spec"):
        return 3, total_steps
    if get_state("frame") is None:
        return 4, total_steps
    if not get_state("model_trained"):
        return 5, total_steps
    if not get_state("scorecard"):
        return 6, total_steps
    if not get_state("curve_bank_entry_id"):
        return 7, total_steps
    if not get_state("scenarios"):
        return 8, total_steps

    return 9, total_steps


def is_step_complete(step: int) -> bool:
    current, _ = get_workflow_progress()
    return current > step
