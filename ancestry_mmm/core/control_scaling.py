"""Stable scaling for additive model controls.

Controls are source variables, not media inputs.  They retain their raw
meaning in the prepared source frame, while the model consumes a centred,
unit-standard-deviation representation so a control such as a 0--100 index
does not create a badly scaled coefficient geometry under a log link.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np


def fit_control_scaling(
    values: np.ndarray,
    names: Sequence[str],
) -> tuple[np.ndarray, dict[str, dict[str, Any]]]:
    """Return centred/scaled values and the raw-scale replay contract."""

    array = np.asarray(values, dtype=float)
    if array.ndim != 2 or array.shape[1] != len(names):
        raise ValueError("Control values must be a 2D matrix matching control names.")
    if array.shape[1] == 0:
        return array.copy(), {}
    centre = np.mean(array, axis=0)
    scale = np.std(array, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 0), scale, 1.0)
    scaled = (array - centre[None, :]) / scale[None, :]
    contract = {
        str(name): {
            "method": "mean_sd",
            "centre": float(centre[index]),
            "scale": float(scale[index]),
        }
        for index, name in enumerate(names)
    }
    return scaled, contract


def apply_control_scaling(
    values: np.ndarray,
    names: Sequence[str],
    contract: Mapping[str, Mapping[str, Any]] | None,
) -> np.ndarray:
    """Replay a fitted control scaling contract on raw control values."""

    array = np.asarray(values, dtype=float)
    if array.ndim != 2 or array.shape[1] != len(names):
        raise ValueError("Control values must be a 2D matrix matching control names.")
    if array.shape[1] == 0 or not contract:
        return array.copy()
    centres = np.asarray([float(contract[str(name)]["centre"]) for name in names])
    scales = np.asarray([float(contract[str(name)]["scale"]) for name in names])
    if np.any(~np.isfinite(scales)) or np.any(scales <= 0):
        raise ValueError("Control scaling contract contains an invalid scale.")
    return (array - centres[None, :]) / scales[None, :]


def apply_control_mapping_scaling(
    values: Mapping[str, float],
    names: Sequence[str],
    contract: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, float]:
    """Scale a named raw-value context used by steady-state planning."""

    if not contract:
        return {str(name): float(values.get(name, 0.0)) for name in names}
    return {
        str(name): float(
            (float(values.get(name, 0.0)) - float(contract[str(name)]["centre"]))
            / float(contract[str(name)]["scale"])
        )
        for name in names
    }
