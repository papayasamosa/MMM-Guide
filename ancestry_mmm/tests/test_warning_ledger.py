"""PR 125B: the "invalid value encountered in scalar divide" RuntimeWarning
used to have a repo-wide `pyproject.toml` `filterwarnings` ignore entry -
any occurrence of that exact message, from any source, anywhere in the
suite, was silently swallowed. It is now suppressed only around the one
known third-party call site (ArviZ's own rank-normalised R-hat, see
`compute_model_diagnostics` in `ancestry_mmm/core/models.py`). These tests
prove both halves of that scoping actually hold.
"""

import arviz as az
import numpy as np
import pytest

from ancestry_mmm.core.models import compute_model_diagnostics


def test_degenerate_trace_rhat_does_not_raise():
    """A perfectly constant chain has zero within- and between-chain
    variance, reproducing ArviZ's own 0/0 "invalid value encountered in
    scalar divide" inside `az.rhat`. Proves the local suppression around
    that one call site in `compute_model_diagnostics` actually covers the
    case it exists for.
    """
    trace = az.from_dict(posterior={"x": np.ones((2, 50))})
    diagnostics = compute_model_diagnostics(trace)
    assert "rhat" in diagnostics
    assert np.isnan(diagnostics["rhat"]["x"])


def test_non_arviz_scalar_divide_still_fails():
    """Simulates a hypothetical *application* bug producing the exact same
    warning message from somewhere other than the one known, deliberately
    scoped ArviZ call site. The project's warning ledger (`pyproject.toml`
    `filterwarnings = ["error", ...]`) must still turn this into a hard
    failure here - proving the old repo-wide ignore this PR removed was
    capable of hiding a genuine application bug wearing the same message,
    and that its narrower replacement does not reopen that hole.
    """
    with pytest.raises(
        RuntimeWarning, match="invalid value encountered in scalar divide"
    ):
        zero = np.float64(0.0)
        _ = zero / zero
