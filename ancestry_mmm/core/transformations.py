"""Marketing mix model transformations: adstock and saturation functions."""

import numpy as np
from typing import Optional, Union
import pytensor
import pytensor.tensor as pt


def geometric_adstock(
    x: np.ndarray,
    decay_rate: float,
    normalize: bool = True,
    initial_state: float = 0.0,
) -> np.ndarray:
    """
    Apply geometric adstock transformation.

    The adstock effect models the carryover of advertising impact over time.
    Each period's effect is the current spend plus a decayed portion of
    the previous period's adstocked value.

    Args:
        x: Array of spend values, shape (n_periods,)
        decay_rate: Decay rate between 0 and 1. Higher values = longer carryover.
        normalize: Whether to normalize by (1 - decay_rate) to maintain scale.
        initial_state: The raw (pre-normalize) recursion value carried in from
            before `x[0]` - `0.0` (the default) reproduces this function's
            original from-scratch behaviour exactly. WP5 (`Media-Mix-Lab:
            Coding LLM Next Steps After PR #253`, sequential simulation
            kernel) uses a non-zero value to seed a weekly plan's adstock
            recursion with the real ending state reconstructed from
            historical media, rather than assuming a plan horizon starts
            from zero carryover. This is a raw accumulator value - the same
            one this recursion already carries internally before the
            `normalize` scaling is applied to the output - not an
            already-normalized/saturated quantity. Because `normalize` is
            an elementwise scaling of each already-computed raw value, this
            is mathematically exact (not an approximation): continuing the
            recursion from a real ending state and normalizing only the new
            segment gives bit-identical results to normalizing the entire
            concatenated (history + new segment) series in one call and
            slicing off the new segment - see
            `TestGeometricAdstockInitialState` in test_transformations.py.
    """
    n = len(x)
    adstocked = np.zeros(n)
    adstocked_prev = float(initial_state)

    for t in range(n):
        adstocked_prev = x[t] + decay_rate * adstocked_prev
        adstocked[t] = adstocked_prev

    if normalize:
        adstocked = adstocked * (1 - decay_rate)

    return adstocked


def geometric_adstock_matrix(
    X: np.ndarray,
    decay_rates: Union[float, np.ndarray],
    normalize: bool = True,
    initial_state: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Apply geometric adstock to multiple channels.

    Args:
        X: Array of spend values, shape (n_periods, n_channels)
        decay_rates: Single decay rate or array of rates per channel
        normalize: Whether to normalize
        initial_state: Per-channel raw carry-in state, shape (n_channels,) -
            `None` (the default) means every channel starts from zero,
            reproducing this function's original behaviour exactly. See
            `geometric_adstock`'s `initial_state` parameter.

    Returns:
        Adstocked values, same shape as input.
    """
    n_periods, n_channels = X.shape

    if isinstance(decay_rates, (int, float)):
        decay_rates = np.full(n_channels, decay_rates)
    if initial_state is None:
        initial_state = np.zeros(n_channels)

    result = np.zeros_like(X)
    for j in range(n_channels):
        result[:, j] = geometric_adstock(
            X[:, j], decay_rates[j], normalize, initial_state=initial_state[j]
        )

    return result


def hill_function(
    x: np.ndarray,
    K: Union[float, np.ndarray],
    S: Union[float, np.ndarray],
) -> np.ndarray:
    """
    Apply Hill function (saturation/diminishing returns).

    The Hill function models diminishing returns as spend increases.
    It's an S-curve that starts at 0, increases, and asymptotes to 1.

    Args:
        x: Input values (typically adstocked spend)
        K: Half-saturation point (spend level at 50% saturation) - a scalar,
            or a per-channel array broadcastable against `x`'s trailing
            axis (every existing caller with a multi-channel `x` - e.g.
            `core.predict.adstock_saturate_frame` - already passes an
            array here; the parameter type previously only documented the
            single-channel call shape).
        S: Shape parameter (steepness of the curve) - same scalar-or-array
            contract as `K`.

    Returns:
        Saturated values in [0, 1] range.
    """
    return x**S / (K**S + x**S)


def hill_function_scaled(
    x: np.ndarray,
    K: float,
    S: float,
    max_effect: float = 1.0,
) -> np.ndarray:
    """
    Apply Hill function with scaling.

    Args:
        x: Input values
        K: Half-saturation point
        S: Shape parameter
        max_effect: Maximum effect (scales the output)

    Returns:
        Scaled saturated values.
    """
    return max_effect * hill_function(x, K, S)


def log_transform(
    x: np.ndarray,
    offset: float = 1.0,
) -> np.ndarray:
    """
    Apply log transformation with offset.

    Used in log-log models to handle zeros and enable
    interpretation as elasticities.

    Args:
        x: Input values
        offset: Offset to add before log (handles zeros)

    Returns:
        Log-transformed values.
    """
    return np.log(x + offset)


def inverse_log_transform(
    x: np.ndarray,
    offset: float = 1.0,
) -> np.ndarray:
    """
    Inverse of log transformation.

    Args:
        x: Log-transformed values
        offset: Offset used in forward transform

    Returns:
        Original scale values.
    """
    return np.exp(x) - offset


# PyTensor versions for use in PyMC models


def pt_geometric_adstock(
    x: pt.TensorVariable,
    decay_rate: pt.TensorVariable,
    normalize: bool = True,
) -> pt.TensorVariable:
    """
    PyTensor version of geometric adstock for PyMC models.

    Uses scan for the recursive computation.
    """

    def step(x_t, adstock_prev, decay):
        return x_t + decay * adstock_prev

    adstocked, _ = pytensor.scan(
        fn=step,
        sequences=[x],
        outputs_info=[pt.zeros(())],
        non_sequences=[decay_rate],
    )

    if normalize:
        adstocked = adstocked * (1 - decay_rate)

    return adstocked


def pt_geometric_adstock_matrix(
    X: pt.TensorVariable,
    decay_rates: pt.TensorVariable,
    normalize: bool = True,
) -> pt.TensorVariable:
    """
    PyTensor multi-channel geometric adstock: one scan over time, vectorised
    across channels, so a whole market's media block can be adstocked with a
    single scan call instead of one per channel.

    Args:
        X: Spend tensor, shape (n_periods, n_channels)
        decay_rates: Per-channel decay rate tensor, shape (n_channels,)

    A single-channel `X` (n_channels == 1) makes `outputs_info`'s initial
    carry (`zeros_like(X[0])`) statically shaped `(1,)`, but `scan` does not
    propagate that static "1" into the per-step sequence slice inside its
    inner graph, so the step function's own output infers as dynamically
    shaped `(?,)`. `scan.op.validate_inner_graph` requires the recurrent
    state's input and output types to match exactly, so this mismatch
    doesn't surface at graph-construction time - only when the scan Op is
    cloned (e.g. `pm.draw`, or `pm.sample` with >1 chain/core), where it
    raises `TypeError: Inconsistency in the inner graph of scan`. This
    reproduces directly against `build_fh_hierarchical_model` with a real
    1-market, 1-channel frame - a pre-existing defect independent of any
    prior-predictive/diagnostics work (REQ-VAL-001). `n_channels >= 2` never
    hits this: only a statically-known size-1 dimension gets the
    "broadcastable" treatment that creates the divergent inner-graph types
    (see PyTensor's broadcasting docs, `doc/tutorial/broadcasting.rst`).

    Fix: re-assert the step output's shape against `X`'s own statically
    known channel count (`n_channels_static`, `None` if not statically
    known) via `specify_shape` inside the step function - this narrows the
    output type to match the input's, rather than trying to broaden the
    input (which PyTensor does not allow: `specify_shape` can only narrow a
    type, never discard already-known static shape information, so
    asserting `(None,)` on the zeros-initialised carry is a no-op and does
    not fix this). A `None` channel count (X's shape not statically known)
    makes this `specify_shape` call itself a no-op, leaving that case
    exactly as before. Verified against the real `build_fh_hierarchical_model`
    (Model A) and `build_fh_market_specific_model` (Model C) builders for
    1/2/3-channel, 1/2-market synthetic frames, including full multi-chain
    `pm.sample` (the path that triggers the Op-cloning that originally
    raised) - see `ancestry_mmm/tests/test_transformations.py`.
    """
    n_channels_static = X.type.shape[1]
    decay_rates = pt.specify_shape(decay_rates, (n_channels_static,))

    def step(x_t, adstock_prev, decay):
        result = x_t + decay * adstock_prev
        return pt.specify_shape(result, (n_channels_static,))

    adstocked, _ = pytensor.scan(
        fn=step,
        sequences=[X],
        outputs_info=[pt.zeros_like(X[0])],
        non_sequences=[decay_rates],
    )

    if normalize:
        adstocked = adstocked * (1 - decay_rates)

    return adstocked


def pt_hill_function(
    x: pt.TensorVariable,
    K: pt.TensorVariable,
    S: pt.TensorVariable,
    epsilon: float = 1e-8,
) -> pt.TensorVariable:
    """
    PyTensor version of Hill function for PyMC models.

    `x` is floored at `epsilon` before the power: x**S differentiated w.r.t.
    S goes through x**S * log(x), and log(0) = -inf produces NaN gradients
    at exactly-zero spend (a real, common case - flighted channels have
    off weeks) and stalls/diverges NUTS. The floor is numerically
    negligible (spend is in the thousands) but keeps autodiff finite.
    """
    x_safe = pt.maximum(x, epsilon)
    return x_safe**S / (K**S + x_safe**S)
