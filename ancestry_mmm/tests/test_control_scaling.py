"""Tests for the Model A control-scaling/replay contract."""

import numpy as np

from ancestry_mmm.core.control_scaling import (
    apply_control_mapping_scaling,
    apply_control_scaling,
    fit_control_scaling,
)


def test_control_scaling_is_centred_unit_sd_and_reversible():
    raw = np.array([[40.0, 2.0], [50.0, 4.0], [60.0, 6.0]])
    scaled, contract = fit_control_scaling(raw, ["trends", "price"])

    np.testing.assert_allclose(scaled.mean(axis=0), [0.0, 0.0])
    np.testing.assert_allclose(scaled.std(axis=0), [1.0, 1.0])
    np.testing.assert_allclose(
        apply_control_scaling(raw, ["trends", "price"], contract), scaled
    )


def test_constant_control_has_a_finite_zero_variance_contract():
    raw = np.full((4, 1), 79.0)
    scaled, contract = fit_control_scaling(raw, ["price"])

    np.testing.assert_allclose(scaled, 0.0)
    assert contract["price"]["scale"] == 1.0


def test_named_planning_context_uses_the_same_fitted_scaling_contract():
    raw = np.array([[40.0], [50.0], [60.0]])
    _scaled, contract = fit_control_scaling(raw, ["trends"])

    result = apply_control_mapping_scaling({"trends": 60.0}, ["trends"], contract)
    np.testing.assert_allclose(result["trends"], (60.0 - 50.0) / np.std(raw))
