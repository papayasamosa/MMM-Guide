"""Tests for PR G1's pathway-masked replay in core.predict - proving the
NumPy replay (predict_mu, steady_state_outcome_response, generate_channel_curve)
correctly honours an explicit ResolvedPathwayMasks, not just the legacy
DNA-only default already covered by test_predict.py's
TestPredictMuDirectHaloSeparation. core.pathways.resolve_pathway_masks's own
pure-Python resolution logic is tested in isolation in test_pathways.py -
this file proves the *replay* side actually applies whatever masks it's
given, using hand-built ResolvedPathwayMasks so the two concerns (resolving
a catalogue vs. replaying resolved masks) stay independently testable."""

import numpy as np
import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.pathways import ResolvedPathwayMasks
from ancestry_mmm.core.predict import FHPosteriorParams, generate_channel_curve, predict_mu, steady_state_outcome_response

OUTCOME_IDS = ["A", "B"]
CHANNELS = ["TV", "Radio"]


def _meta(pathway_masks: ResolvedPathwayMasks) -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], outcome_ids=OUTCOME_IDS, channels=CHANNELS,
        dna_channels=[], dna_channel_idx=[], non_dna_idx=[0, 1],
        dna_outcome_id="A", dna_lag_weeks=0, unpooled_markets=[], control_names=[],
        pathway_masks=pathway_masks,
    )


def _params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV": 0.0, "Radio": 0.0}, hill_K={"TV": 1000.0, "Radio": 1000.0},
        hill_S={"TV": 1.0, "Radio": 1.0},
        beta={"A": {"TV": 1.0, "Radio": 1.0}, "B": {"TV": 1.0, "Radio": 1.0}},
        pathway_strength={"A": {"Radio": 0.4}, "B": {"Radio": 0.4}},
        promo_coef={"A": 0.0, "B": 0.0},
        market_offset={"UK": {"A": 0.0, "B": 0.0}},
        intercept={"A": 0.0, "B": 0.0}, trend_coef={"A": 0.0, "B": 0.0},
        gamma_fourier={"A": np.zeros(4), "B": np.zeros(4)}, alpha={"A": 5.0, "B": 5.0},
        control_coef={}, outcome_control_coef={},
    )


def _frame():
    n = 6
    X_media = np.zeros((n, 2))
    X_media[2] = [500.0, 500.0]
    return {
        "markets": ["UK"], "market_idx": np.zeros(n, dtype=int), "market_bounds": [(0, n)],
        "X_media": X_media, "promo": np.zeros((n, len(OUTCOME_IDS))),
        "trend": np.zeros(n), "fourier": np.zeros((n, 4)),
        "control_names": [], "X_controls": np.zeros((n, 0)),
        "outcome_controls": {}, "outcome_control_names": {},
    }


class TestExcludedPathwayGivesZeroContribution:
    """Required test case: "excluded pathway -> zero contribution" at the
    NumPy replay level - Radio is excluded entirely for outcome B (absent
    from all three of B's role buckets), present as primary_direct for A."""

    def _masks(self) -> ResolvedPathwayMasks:
        return ResolvedPathwayMasks(
            primary_channels_by_outcome={"A": ["TV", "Radio"], "B": ["TV"]},
            active_channels_by_outcome={}, exploratory_channels_by_outcome={},
        )

    def test_predict_mu_excluded_channel_never_contributes(self):
        meta = _meta(self._masks())
        params = _params()
        mu = predict_mu(_frame(), meta, params)
        frame_no_radio = _frame()
        frame_no_radio["X_media"][:, 1] = 0.0
        mu_no_radio = predict_mu(frame_no_radio, meta, params)
        b_idx = meta.outcome_ids.index("B")
        # B is excluded from Radio, so Radio spend must not move B's mu at all.
        np.testing.assert_allclose(mu[:, b_idx], mu_no_radio[:, b_idx])

    def test_predict_mu_non_excluded_channel_still_contributes(self):
        # Not vacuous: A (Radio is primary_direct there) DOES respond to
        # Radio spend, proving B's zero response above is specifically the
        # excluded pathway, not some unrelated bug zeroing everything.
        meta = _meta(self._masks())
        params = _params()
        mu = predict_mu(_frame(), meta, params)
        frame_no_radio = _frame()
        frame_no_radio["X_media"][:, 1] = 0.0
        mu_no_radio = predict_mu(frame_no_radio, meta, params)
        a_idx = meta.outcome_ids.index("A")
        assert not np.allclose(mu[:, a_idx], mu_no_radio[:, a_idx])

    def test_steady_state_response_excluded_channel_has_zero_weight(self):
        meta = _meta(self._masks())
        params = _params()
        result = steady_state_outcome_response("UK", {"TV": 0.0, "Radio": 500.0}, meta, params)
        result_no_radio = steady_state_outcome_response("UK", {"TV": 0.0, "Radio": 0.0}, meta, params)
        assert result["B"] == pytest.approx(result_no_radio["B"])
        assert result["A"] != pytest.approx(result_no_radio["A"])

    def test_generate_channel_curve_excluded_outcome_is_flat_at_zero(self):
        meta = _meta(self._masks())
        params = _params()
        df = generate_channel_curve("Radio", meta, params, spend_range=np.array([0.0, 500.0, 1000.0]))
        assert (df["B_response"] == 0.0).all()
        assert (df["A_response"].iloc[1:] > 0.0).all()


class TestExploratoryCellReplaysIdenticallyToActive:
    """Required test case: "exploratory -> tighter prior" is enforced at
    PyMC-build time (test_hierarchical_model.py's source-inspection test
    confirms the 0.08 vs 0.25 default sigma - a tighter prior is not
    independently observable once a strength value has already been fit).
    What replay must get right is applying *whichever* strength a cell
    resolved to identically regardless of whether it came from the active or
    exploratory bucket - proving `_pathway_weight`/`_cross_product_strength_matrix`
    don't accidentally special-case, drop, or double-apply one bucket."""

    def _masks(self) -> ResolvedPathwayMasks:
        return ResolvedPathwayMasks(
            primary_channels_by_outcome={"A": ["TV"], "B": ["TV"]},
            active_channels_by_outcome={"A": ["Radio"]},
            exploratory_channels_by_outcome={"B": ["Radio"]},
            cross_product_lag_weeks=0,
        )

    def test_active_and_exploratory_cells_with_equal_strength_replay_identically(self):
        meta = _meta(self._masks())
        params = _params()  # pathway_strength["A"]["Radio"] == pathway_strength["B"]["Radio"] == 0.4
        mu = predict_mu(_frame(), meta, params)
        a_idx, b_idx = meta.outcome_ids.index("A"), meta.outcome_ids.index("B")
        # Identical beta/primary/strength for A (active) and B (exploratory) -
        # their predicted mu must match exactly if the two buckets are
        # replayed through the same code path, as designed.
        np.testing.assert_allclose(mu[:, a_idx], mu[:, b_idx])


class TestFHModelMetaAutoResolvesLegacyDefaultForPredict:
    """A FHModelMeta built without an explicit pathway_masks (e.g. a
    hand-built test fixture, or a bundle saved before PR G1 with no such key
    at all) must still replay non-trivially - proving __post_init__'s
    None-sentinel default (hierarchical_model.py) never leaves predict.py
    replaying against an all-cells-excluded ResolvedPathwayMasks(), which
    would silently zero out every channel's contribution."""

    def test_meta_without_pathway_masks_still_produces_responsive_predictions(self):
        meta = FHModelMeta(
            markets=["UK"], outcome_ids=OUTCOME_IDS, channels=CHANNELS,
            dna_channels=[], dna_channel_idx=[], non_dna_idx=[0, 1],
            dna_outcome_id="A", dna_lag_weeks=0, unpooled_markets=[], control_names=[],
        )  # pathway_masks intentionally omitted
        params = _params()
        mu = predict_mu(_frame(), meta, params)
        zero_spend_frame = _frame()
        zero_spend_frame["X_media"][:] = 0.0
        baseline = predict_mu(zero_spend_frame, meta, params)
        assert np.all(mu >= baseline)
        assert not np.allclose(mu, baseline)
