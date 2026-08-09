"""Structural sanity tests for core.market_specific_model ("Model C").

Matches the project's existing convention (see core.hierarchical_model,
core.models, core.predict - none of which have a PyMC-model-construction
test either) of not building/compiling an actual PyMC model in the test
suite, since that's slow and already covered by manual/offline verification
(docs/decision_log.md). What *is* cheap and worth covering here is the
early, pre-PyMC validation this module adds on top of Model A's contract.

TestSingleChannelSurvivesPmDraw is a deliberate, narrow exception to that
convention (REQ-VAL-001 corrective package) - see its own docstring for why
a real `pm.Model` + `pm.draw` (not `pm.sample`) is required there.
"""

import numpy as np
import pytest

from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.schema import ModelSpec


def _single_market_frame():
    return {
        "markets": ["UK"],
        "market_idx": np.array([0, 0]),
        "market_bounds": [(0, 2)],
        "channels": ["TV"],
        "dna_channel_idx": [],
        "outcome_ids": ["fh_new"],
        "X_media": np.array([[100.0], [200.0]]),
        "Y": np.array([[10.0], [12.0]]),
        "promo": np.zeros((2, 1)),
        "X_controls": np.zeros((2, 0)),
        "control_names": [],
        "fourier": np.zeros((2, 2)),
        "trend": np.array([1.0, 1.1]),
        "unpooled_markets": [],
    }


class TestRequiresAtLeastTwoMarkets:
    def test_raises_valueerror_for_a_single_market(self):
        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV"],
        )
        with pytest.raises(ValueError, match="at least 2 markets"):
            build_fh_market_specific_model(_single_market_frame(), spec)

    def test_error_message_points_at_model_a_for_the_single_market_case(self):
        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV"],
        )
        with pytest.raises(ValueError, match="build_fh_hierarchical_model"):
            build_fh_market_specific_model(_single_market_frame(), spec)


def _two_market_frame_with_dna_channel():
    return {
        "markets": ["UK", "US"],
        "market_idx": np.array([0, 0, 1, 1]),
        "market_bounds": [(0, 2), (2, 4)],
        "channels": ["TV", "DNA_Ad"],
        "dna_channel_idx": [1],
        "outcome_ids": ["fh_new"],
        "X_media": np.array(
            [[100.0, 50.0], [200.0, 60.0], [110.0, 55.0], [210.0, 65.0]]
        ),
        "Y": np.array([[10.0], [12.0], [11.0], [13.0]]),
        "promo": np.zeros((4, 1)),
        "X_controls": np.zeros((4, 0)),
        "control_names": [],
        "fourier": np.zeros((4, 2)),
        "trend": np.array([1.0, 1.1, 1.0, 1.1]),
        "unpooled_markets": [],
    }


class TestModelAModelCParityOnExplicitDnaCrossSellRequirement:
    """PR E.1 test case: "Model A and Model C parity" - the explicit
    fh_dna_cross_sell_outcome_id requirement (replacing substring inference)
    must behave identically for both model builders, since they share the
    same `_default_dna_outcome_id` helper. Cheap to test without building an
    actual PyMC model: the ValueError is raised before `pm.Model()` is
    entered, for both builders."""

    def test_model_c_raises_without_explicit_dna_outcome_id_when_dna_channels_present(
        self,
    ):
        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK", "US"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV", "DNA_Ad"],
            dna_channels=["DNA_Ad"],
        )
        with pytest.raises(ValueError, match="explicit"):
            build_fh_market_specific_model(_two_market_frame_with_dna_channel(), spec)

    def test_model_a_and_model_c_raise_the_same_way(self):
        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model

        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV", "DNA_Ad"],
            dna_channels=["DNA_Ad"],
        )
        single_market_dna_frame = {
            "markets": ["UK"],
            "market_idx": np.array([0, 0]),
            "market_bounds": [(0, 2)],
            "channels": ["TV", "DNA_Ad"],
            "dna_channel_idx": [1],
            "outcome_ids": ["fh_new"],
            "X_media": np.array([[100.0, 50.0], [200.0, 60.0]]),
            "Y": np.array([[10.0], [12.0]]),
            "promo": np.zeros((2, 1)),
            "X_controls": np.zeros((2, 0)),
            "control_names": [],
            "fourier": np.zeros((2, 2)),
            "trend": np.array([1.0, 1.1]),
            "unpooled_markets": [],
        }
        with pytest.raises(ValueError, match="explicit") as exc_a:
            build_fh_hierarchical_model(single_market_dna_frame, spec)
        with pytest.raises(ValueError, match="explicit") as exc_c:
            build_fh_market_specific_model(_two_market_frame_with_dna_channel(), spec)
        # Same underlying helper - the substantive part of the message
        # (what to do about it) must be identical for both model types.
        assert "dna_outcome_id" in str(exc_a.value) and "dna_outcome_id" in str(
            exc_c.value
        )


class TestSingleChannelSurvivesPmDraw:
    """REQ-VAL-001 corrective package: a single-channel frame made the
    shared `core.transformations.pt_geometric_adstock_matrix` helper's
    internal `scan` Op raise `TypeError: Inconsistency in the inner graph
    of scan` whenever PyMC's compile path cloned it (`pm.draw`, or
    `pm.sample` initialising >1 chain/core) - Model C calls the exact same
    helper as Model A (`core.hierarchical_model`) per-market, so a
    single-channel (any market count - Model C requires >= 2, see
    `TestRequiresAtLeastTwoMarkets` above) frame hits it too. Intentionally
    builds a real `pm.Model` (an exception to this file's module
    docstring's usual "don't build a PyMC model" convention - a hand-built
    standalone tensor graph cannot reproduce the RV-into-scan condition
    that actually triggered this) but stays fast via `pm.draw` rather than
    `pm.sample`, so it doesn't reintroduce the slow-MCMC concern that
    convention exists to avoid."""

    @staticmethod
    def _two_market_single_channel_frame():
        return {
            "markets": ["UK", "AU"],
            "market_idx": np.array([0, 0, 1, 1]),
            "market_bounds": [(0, 2), (2, 4)],
            "channels": ["TV"],
            "dna_channel_idx": [],
            "outcome_ids": ["fh_new"],
            "X_media": np.array([[100.0], [200.0], [110.0], [210.0]]),
            "Y": np.array([[10.0], [12.0], [11.0], [13.0]]),
            "promo": np.zeros((4, 1)),
            "X_controls": np.zeros((4, 0)),
            "control_names": [],
            "fourier": np.zeros((4, 2)),
            "trend": np.array([1.0, 1.1, 1.0, 1.1]),
            "unpooled_markets": [],
        }

    def test_sat_media_survives_pm_draw_cloning(self):
        import pymc as pm

        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK", "AU"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV"],
        )
        model, _meta = build_fh_market_specific_model(
            self._two_market_single_channel_frame(), spec
        )
        with model:
            val = pm.draw(model.named_vars["sat_media"], draws=1, random_seed=0)
        assert np.asarray(val).shape == (4, 1)
