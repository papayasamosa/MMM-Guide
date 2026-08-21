"""Focused tests for the local UK production-fit orchestration boundary."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


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
