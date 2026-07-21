"""Structural sanity tests for core.market_specific_model ("Model C").

Matches the project's existing convention (see core.hierarchical_model,
core.models, core.predict - none of which have a PyMC-model-construction
test either) of not building/compiling an actual PyMC model in the test
suite, since that's slow and already covered by manual/offline verification
(docs/decision_log.md). What *is* cheap and worth covering here is the
early, pre-PyMC validation this module adds on top of Model A's contract.
"""

import numpy as np
import pytest

from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.schema import ModelSpec


def _single_market_frame():
    return {
        "markets": ["UK"], "market_idx": np.array([0, 0]), "market_bounds": [(0, 2)],
        "channels": ["TV"], "dna_channel_idx": [], "segments": ["New"],
        "X_media": np.array([[100.0], [200.0]]), "Y": np.array([[10.0], [12.0]]),
        "promo": np.zeros((2, 1)), "X_controls": np.zeros((2, 0)), "control_names": [],
        "fourier": np.zeros((2, 2)), "trend": np.array([1.0, 1.1]), "unpooled_markets": [],
    }


class TestRequiresAtLeastTwoMarkets:
    def test_raises_valueerror_for_a_single_market(self):
        spec = ModelSpec(
            date_col="date", market_col="market", markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"}, channels=["TV"],
        )
        with pytest.raises(ValueError, match="at least 2 markets"):
            build_fh_market_specific_model(_single_market_frame(), spec)

    def test_error_message_points_at_model_a_for_the_single_market_case(self):
        spec = ModelSpec(
            date_col="date", market_col="market", markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"}, channels=["TV"],
        )
        with pytest.raises(ValueError, match="build_fh_hierarchical_model"):
            build_fh_market_specific_model(_single_market_frame(), spec)
