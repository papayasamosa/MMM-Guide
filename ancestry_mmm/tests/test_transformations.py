import numpy as np
import pytest

from ancestry_mmm.core.transformations import (
    geometric_adstock,
    geometric_adstock_matrix,
    hill_function,
)


def test_geometric_adstock_unnormalized_matches_hand_computation():
    x = np.array([10.0, 0.0, 0.0, 0.0])
    result = geometric_adstock(x, decay_rate=0.5, normalize=False)
    # adstocked[0] = 10; adstocked[t] = x[t] + 0.5 * adstocked[t-1]
    np.testing.assert_allclose(result, [10.0, 5.0, 2.5, 1.25])


def test_geometric_adstock_normalized_scales_by_one_minus_decay():
    x = np.array([10.0, 0.0, 0.0, 0.0])
    unnorm = geometric_adstock(x, decay_rate=0.5, normalize=False)
    norm = geometric_adstock(x, decay_rate=0.5, normalize=True)
    np.testing.assert_allclose(norm, unnorm * 0.5)


def test_geometric_adstock_zero_decay_is_identity():
    x = np.array([3.0, 1.0, 4.0, 1.0, 5.0])
    result = geometric_adstock(x, decay_rate=0.0, normalize=False)
    np.testing.assert_allclose(result, x)


def test_geometric_adstock_matrix_matches_per_channel_calls():
    X = np.array([[10.0, 1.0], [0.0, 1.0], [0.0, 1.0]])
    decay_rates = np.array([0.5, 0.25])
    result = geometric_adstock_matrix(X, decay_rates, normalize=True)
    expected_col0 = geometric_adstock(X[:, 0], 0.5, normalize=True)
    expected_col1 = geometric_adstock(X[:, 1], 0.25, normalize=True)
    np.testing.assert_allclose(result[:, 0], expected_col0)
    np.testing.assert_allclose(result[:, 1], expected_col1)


def test_hill_function_at_half_saturation_point_is_one_half():
    # By construction, x**S / (K**S + x**S) == 0.5 when x == K, for any S > 0.
    for K, S in [(100.0, 1.0), (5000.0, 0.8), (12.0, 2.5)]:
        result = hill_function(np.array([K]), K=K, S=S)
        np.testing.assert_allclose(result, [0.5])


def test_hill_function_is_monotonically_increasing():
    x = np.linspace(0.0, 1000.0, 50)
    result = hill_function(x, K=200.0, S=1.2)
    assert np.all(np.diff(result) >= 0)


def test_hill_function_approaches_zero_and_one_at_extremes():
    result_low = hill_function(np.array([1e-9]), K=100.0, S=1.0)
    result_high = hill_function(np.array([1e9]), K=100.0, S=1.0)
    assert result_low[0] == pytest.approx(0.0, abs=1e-6)
    assert result_high[0] == pytest.approx(1.0, abs=1e-6)
