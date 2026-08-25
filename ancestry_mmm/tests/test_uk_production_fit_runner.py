"""Focused tests for the local UK production-fit orchestration boundary."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _runner_module():
    path = Path(__file__).parents[2] / "scripts" / "run_uk_production_fit.py"
    spec = importlib.util.spec_from_file_location("run_uk_production_fit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runner_json_default_supports_numpy_boolean() -> None:
    runner = _runner_module()

    assert runner._json_default(np.bool_(True)) is True


def test_no_target_window_variation_identifies_constant_inputs() -> None:
    runner = _runner_module()
    frame = pd.DataFrame(
        {
            "period_start": pd.date_range("2023-01-01", periods=3, freq="7D"),
            "market": "UK",
            "constant_zero": [0.0, 0.0, 0.0],
            "constant_positive": [2.0, 2.0, 2.0],
            "varying": [0.0, 1.0, 0.0],
        }
    )

    assert runner._no_target_window_variation(frame) == [
        "constant_positive",
        "constant_zero",
    ]


def test_approved_prior_config_matches_req_control_001() -> None:
    runner = _runner_module()

    assert runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG == {
        "control_sigma": 0.20,
        "enable_control_scaling": True,
    }
    assert runner.APPROVED_STANDARDISED_CONTROL_NAMES == {
        "fh_category_demand_google_trends",
        "dna_category_demand_google_trends",
    }


def test_control_scaling_scope_is_a_noop_when_scaling_is_disabled() -> None:
    runner = _runner_module()
    frame = {"control_names": ["anything_at_all"], "outcome_controls": {"oid": object()}}

    runner._validate_approved_control_scaling_scope(
        "family_history", frame, {"enable_control_scaling": False}
    )


def test_control_scaling_scope_allows_the_approved_controls() -> None:
    runner = _runner_module()
    frame = {
        "control_names": ["fh_category_demand_google_trends"],
        "outcome_controls": {},
    }

    runner._validate_approved_control_scaling_scope(
        "family_history", frame, runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG
    )


def test_control_scaling_scope_blocks_an_unapproved_control_name() -> None:
    runner = _runner_module()
    frame = {
        "control_names": ["fh_category_demand_google_trends", "some_new_control"],
        "outcome_controls": {},
    }

    with pytest.raises(runner.FitGateError, match="some_new_control"):
        runner._validate_approved_control_scaling_scope(
            "family_history", frame, runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG
        )


def test_control_scaling_scope_blocks_nonempty_outcome_controls() -> None:
    runner = _runner_module()
    frame = {
        "control_names": ["fh_category_demand_google_trends"],
        "outcome_controls": {"UK::fh_net_billthrough_count_new": np.zeros((3, 1))},
    }

    with pytest.raises(runner.FitGateError, match="outcome_controls"):
        runner._validate_approved_control_scaling_scope(
            "family_history", frame, runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG
        )
