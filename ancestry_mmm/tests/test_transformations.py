import numpy as np
import pytensor
import pytensor.tensor as pt
import pytest

from ancestry_mmm.core.transformations import (
    apply_media_input_scale,
    apply_media_input_scales,
    geometric_adstock,
    geometric_adstock_matrix,
    hill_function,
    pt_geometric_adstock_matrix,
)


def test_media_input_scaling_is_channel_specific_and_preserves_zeros():
    X = np.array([[0.0, 10.0], [200.0, 0.0]])
    scaled = apply_media_input_scales(X, ["TV", "Email"], {"TV": 100.0, "Email": 10.0})
    np.testing.assert_allclose(scaled, [[0.0, 1.0], [2.0, 0.0]])
    assert apply_media_input_scale(200.0, "TV", {"TV": 100.0}) == pytest.approx(2.0)


def test_media_input_scaling_rejects_missing_or_nonpositive_scales():
    with pytest.raises(ValueError, match="missing channel"):
        apply_media_input_scales(np.ones((2, 1)), ["TV"], {"Email": 1.0})
    with pytest.raises(ValueError, match="strictly positive"):
        apply_media_input_scales(np.ones((2, 1)), ["TV"], {"TV": 0.0})


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


class TestGeometricAdstockInitialState:
    """WP5 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`, sequential
    simulation kernel): `initial_state` seeds the recursion with a carried-
    in raw accumulator value instead of implicitly starting at zero. These
    tests prove the two required properties: (1) the default reproduces
    today's from-scratch behaviour exactly (backward compatibility), and
    (2) continuing the recursion from a real ending state is mathematically
    exact - not an approximation - versus running the whole concatenated
    series through the original zero-start call and slicing off the tail."""

    def test_default_initial_state_matches_original_zero_start_behaviour(self):
        x = np.array([3.0, 1.0, 4.0, 1.0, 5.0, 0.0, 2.0])
        original = geometric_adstock(x, decay_rate=0.6, normalize=True)
        explicit_zero = geometric_adstock(
            x, decay_rate=0.6, normalize=True, initial_state=0.0
        )
        np.testing.assert_allclose(original, explicit_zero)

    def test_matrix_default_initial_state_matches_original_zero_start_behaviour(self):
        X = np.array([[10.0, 1.0], [0.0, 1.0], [5.0, 1.0]])
        decay_rates = np.array([0.5, 0.25])
        original = geometric_adstock_matrix(X, decay_rates, normalize=True)
        explicit_zero = geometric_adstock_matrix(
            X, decay_rates, normalize=True, initial_state=np.zeros(2)
        )
        np.testing.assert_allclose(original, explicit_zero)

    def test_continuing_from_real_ending_state_matches_full_batch_computation(self):
        # "Adstock equivalence to current batch transformation": splitting
        # one continuous series into a "historical" prefix and a "future"
        # suffix, reconstructing the ending raw state from the prefix, and
        # continuing the future suffix from that state must give bit-
        # identical results to running the whole series through the
        # existing batch transformation in one call and slicing.
        rng = np.random.default_rng(0)
        full = rng.uniform(0.0, 100.0, size=20)
        decay = 0.7
        n_hist = 12

        full_batch = geometric_adstock(full, decay_rate=decay, normalize=True)
        expected_future = full_batch[n_hist:]

        hist_raw = geometric_adstock(full[:n_hist], decay_rate=decay, normalize=False)
        starting_state = hist_raw[-1]
        future_result = geometric_adstock(
            full[n_hist:],
            decay_rate=decay,
            normalize=True,
            initial_state=starting_state,
        )
        np.testing.assert_allclose(future_result, expected_future, rtol=1e-12)

    def test_matrix_continuing_from_real_ending_state_matches_full_batch_computation(
        self,
    ):
        rng = np.random.default_rng(1)
        full = rng.uniform(0.0, 100.0, size=(20, 3))
        decay_rates = np.array([0.7, 0.3, 0.5])
        n_hist = 8

        full_batch = geometric_adstock_matrix(full, decay_rates, normalize=True)
        expected_future = full_batch[n_hist:]

        hist_raw = geometric_adstock_matrix(full[:n_hist], decay_rates, normalize=False)
        starting_state = hist_raw[-1]
        future_result = geometric_adstock_matrix(
            full[n_hist:],
            decay_rates,
            normalize=True,
            initial_state=starting_state,
        )
        np.testing.assert_allclose(future_result, expected_future, rtol=1e-12)

    def test_nonzero_initial_state_changes_first_period_output(self):
        x = np.array([0.0, 0.0, 0.0])
        zero_start = geometric_adstock(x, decay_rate=0.5, normalize=True)
        carried_in = geometric_adstock(
            x, decay_rate=0.5, normalize=True, initial_state=10.0
        )
        assert zero_start[0] == pytest.approx(0.0)
        # raw[0] = x[0] + decay*initial_state = 0 + 0.5*10 = 5; normalize
        # scales the whole output by (1 - decay) = 0.5 afterwards -> 2.5.
        assert carried_in[0] == pytest.approx(0.5 * (0.5 * 10.0))
        assert np.all(carried_in > zero_start)


def test_geometric_adstock_matches_pymc_marketing_unnormalized():
    """Guard the portion of the upstream transform we intentionally match."""
    pytest.importorskip("pymc_marketing")
    import inspect

    import pytensor.tensor as pt
    from pymc_marketing.mmm.transformers import (
        geometric_adstock as upstream_geometric_adstock,
    )

    values = np.array([10.0, 0.0, 4.0, 1.0, 0.0])
    alpha = 0.35
    upstream_kwargs = {
        "alpha": alpha,
        "l_max": len(values),
        "normalize": False,
    }
    upstream_input = pt.as_tensor_variable(values)
    if "dim" in inspect.signature(upstream_geometric_adstock).parameters:
        import pytensor.xtensor as ptx

        upstream_input = ptx.as_xtensor(upstream_input, dims=("time",))
        upstream_kwargs["dim"] = "time"
    upstream = upstream_geometric_adstock(
        upstream_input,
        **upstream_kwargs,
    ).eval()
    np.testing.assert_allclose(
        geometric_adstock(values, alpha, normalize=False),
        upstream,
        rtol=1e-12,
        atol=1e-12,
    )


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


# ---------------------------------------------------------------------------
# REQ-VAL-001 corrective package: pt_geometric_adstock_matrix single-channel
# scan shape defect (docs/approved_requirements/REQ-VAL-001.md, "Discovered
# but explicitly out of scope for this closure").
# ---------------------------------------------------------------------------


class TestPtGeometricAdstockMatrixMatchesNumpyReference:
    """Numeric parity between the PyTensor and NumPy implementations across
    channel counts, including the single-channel case the scan defect
    affected. Shape correctness alone would not have caught the original
    defect (it only surfaced when the scan Op was cloned - see the class
    below); this guards the actual math the fix must not change."""

    @pytest.mark.parametrize("n_channels", [1, 2, 3, 5])
    def test_parity(self, n_channels):
        rng = np.random.default_rng(1)
        X = rng.uniform(0, 100, size=(20, n_channels))
        decay_rates = rng.uniform(0.1, 0.9, size=n_channels)

        pt_out = pt_geometric_adstock_matrix(
            pt.as_tensor_variable(X), pt.as_tensor_variable(decay_rates)
        )
        pt_result = pytensor.function([], pt_out)()
        np_result = geometric_adstock_matrix(X, decay_rates, normalize=True)
        np.testing.assert_allclose(pt_result, np_result, rtol=1e-10)


class TestPtGeometricAdstockMatrixSurvivesScanCloning:
    """A single-channel `X` made `pt_geometric_adstock_matrix`'s internal
    `scan` Op raise `TypeError: Inconsistency in the inner graph of scan`
    whenever that Op was cloned - which a plain `pytensor.function([], out)`
    call does NOT trigger (that path passed even before the fix), but
    PyMC's own compile path does whenever the scan's non-sequence is a real
    PyMC random variable needing its default update spliced in (`pm.draw`,
    or `pm.sample` initialising a multi-chain/core NUTS run) - exactly what
    `core.hierarchical_model.build_fh_hierarchical_model`'s `decay_rate =
    pm.Beta(..., dims="channel")` is. This intentionally builds a minimal
    real `pm.Model` (an exception to this project's usual "don't build a
    PyMC model in tests" convention - see `test_hierarchical_model.py`'s
    module docstring) because that RV-into-scan condition is exactly what a
    hand-built standalone tensor graph cannot reproduce; it stays fast
    (`pm.draw`, not `pm.sample`) so it doesn't reintroduce the slow-MCMC
    concern that convention exists to avoid.
    """

    @pytest.mark.parametrize("n_channels", [1, 2, 3])
    def test_pt_geometric_adstock_matrix_survives_pm_draw(self, n_channels):
        import pymc as pm

        rng = np.random.default_rng(2)
        X_np = rng.uniform(0, 100, size=(15, n_channels))

        with pm.Model() as model:
            model.add_coord("channel", [f"ch{i}" for i in range(n_channels)])
            decay_rate = pm.Beta("decay_rate", mu=0.5, sigma=0.2, dims="channel")
            X = pt.as_tensor_variable(X_np)
            out = pt_geometric_adstock_matrix(X, decay_rate, normalize=True)
            pm.Deterministic("sat_media", out)

            val = pm.draw(model.named_vars["sat_media"], draws=1, random_seed=0)

        assert np.asarray(val).shape == (15, n_channels)
