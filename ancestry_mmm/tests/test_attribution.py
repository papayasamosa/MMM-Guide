"""Tests for core.attribution - focused on the direct_dna_outcome_ids fix in
_channel_log_terms and the total_fh_contribution segments filter
(docs/dna_fh_causal_structure.md). Hand-constructed FHModelMeta/params/frame,
no PyMC/MCMC involved, matching test_market_specific_predict.py's
convention - this file does not attempt full existing-behaviour coverage of
compute_shapley_contributions (no test file existed for it before this PR)."""

import arviz as az
import numpy as np
import pytest

from ancestry_mmm.core.attribution import (
    contribution_waterfall,
    compute_shapley_contributions,
    outcome_channel_summary,
    segment_channel_summary,
    total_fh_contribution,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.predict import FHPosteriorParams, extract_posterior_params
from ancestry_mmm.core.search_capacity import SEARCH_CANDIDATE_A_ENGINE
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

OUTCOME_IDS = ["New", "DNA_CrossSell", "Winback", "New Customer"]
CHANNELS = ["TV", "DNA_Media"]


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell",
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
        direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV": 0.5, "DNA_Media": 0.4},
        hill_K={"TV": 1000.0, "DNA_Media": 500.0},
        hill_S={"TV": 1.0, "DNA_Media": 1.0},
        beta={
            "New": {"TV": 0.10, "DNA_Media": 0.05},
            "DNA_CrossSell": {"TV": 0.02, "DNA_Media": 0.20},
            "Winback": {"TV": 0.03, "DNA_Media": 0.06},
            "New Customer": {"TV": 0.01, "DNA_Media": 0.50},
        },
        # "New Customer" carries a low pathway_strength deliberately - when it's
        # NOT a direct segment (see the halo_meta variant below), this value
        # is what its DNA_Media contribution gets shrunk by; when it IS
        # direct, this value is bypassed entirely (full beta, no shrinkage).
        pathway_strength=pathway_strength_from_flat(
            {"New": 0.15, "DNA_CrossSell": 1.0, "Winback": 0.10, "New Customer": 0.2},
            "DNA_Media",
        ),
        promo_coef={
            "New": 0.0,
            "DNA_CrossSell": 0.0,
            "Winback": 0.0,
            "New Customer": 0.0,
        },
        market_offset={"UK": {s: 0.0 for s in OUTCOME_IDS}},
        intercept={
            "New": 3.0,
            "DNA_CrossSell": 2.0,
            "Winback": 1.5,
            "New Customer": 2.5,
        },
        trend_coef={s: 0.0 for s in OUTCOME_IDS},
        gamma_fourier={s: np.zeros(4) for s in OUTCOME_IDS},
        alpha={s: 5.0 for s in OUTCOME_IDS},
        control_coef={},
        outcome_control_coef={},
    )


@pytest.fixture
def frame():
    n = 8
    rng = np.random.default_rng(0)
    return {
        "markets": ["UK"],
        "market_idx": np.zeros(n, dtype=int),
        "market_bounds": [(0, n)],
        "X_media": rng.uniform(50, 500, size=(n, 2)),
        "promo": np.zeros((n, len(OUTCOME_IDS))),
        "trend": np.zeros(n),
        "fourier": np.zeros((n, 4)),
        "control_names": [],
        "X_controls": np.zeros((n, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }


class TestComputeShapleyContributionsDirectDnaSegments:
    def test_contributions_sum_to_mu_minus_baseline_with_a_dna_kit_segment_present(
        self, frame, meta, params
    ):
        # additivity holds regardless of which segments are halo-shrunk vs direct
        contributions = compute_shapley_contributions(
            frame, meta, params, n_permutations=20
        )
        total_channel_contrib = sum(
            contributions["channel_contributions"][ch] for ch in CHANNELS
        )
        reconstructed = contributions["baseline"] + total_channel_contrib
        np.testing.assert_allclose(
            reconstructed, contributions["mu_total"], rtol=1e-5, atol=1e-6
        )

    def test_dna_kit_segment_channel_contribution_uses_full_beta_not_halo_shrunk(
        self, frame, meta, params
    ):
        # Build a second meta where "New Customer" is NOT a direct segment,
        # and confirm its DNA_Media contribution is smaller there (halo-
        # shrunk) than when it's fit as a direct segment - the exact
        # regression this fix guards.
        contributions_direct = compute_shapley_contributions(
            frame, meta, params, n_permutations=20
        )

        halo_meta = FHModelMeta(
            markets=["UK"],
            outcome_ids=OUTCOME_IDS,
            channels=CHANNELS,
            dna_channels=["DNA_Media"],
            dna_channel_idx=[1],
            non_dna_idx=[0],
            dna_outcome_id="DNA_CrossSell",
            dna_lag_weeks=1,
            unpooled_markets=[],
            control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell"],  # "New Customer" NOT direct here
        )
        contributions_shrunk = compute_shapley_contributions(
            frame, halo_meta, params, n_permutations=20
        )

        seg_idx = OUTCOME_IDS.index("New Customer")
        direct_total = contributions_direct["channel_contributions"]["DNA_Media"][
            :, seg_idx
        ].sum()
        shrunk_total = contributions_shrunk["channel_contributions"]["DNA_Media"][
            :, seg_idx
        ].sum()
        assert direct_total > shrunk_total


class TestTotalFhContributionSegmentsFilter:
    def test_default_sums_every_segment(self, frame, meta, params):
        contributions = compute_shapley_contributions(
            frame, meta, params, n_permutations=20
        )
        total_all = total_fh_contribution(frame, meta, params, contributions, ltv=None)
        seg_summary = segment_channel_summary(
            frame, meta, params, contributions, ltv=None
        )
        expected = seg_summary.groupby("channel")["volume_contribution"].sum()
        for ch in CHANNELS:
            assert total_all.set_index("channel").loc[
                ch, "volume_contribution"
            ] == pytest.approx(expected[ch])

    def test_outcome_ids_filter_excludes_dna_kit_outcome_from_the_total(
        self, frame, meta, params
    ):
        contributions = compute_shapley_contributions(
            frame, meta, params, n_permutations=20
        )
        fh_only_outcome_ids = [s for s in OUTCOME_IDS if s != "New Customer"]
        total_fh_only = total_fh_contribution(
            frame,
            meta,
            params,
            contributions,
            ltv=None,
            outcome_ids=fh_only_outcome_ids,
        )
        total_all = total_fh_contribution(
            frame, meta, params, contributions, ltv=None, outcome_ids=None
        )

        # Excluding an outcome_id that gets non-zero DNA_Media contribution
        # must strictly reduce that channel's total.
        dna_media_fh_only = total_fh_only.set_index("channel").loc[
            "DNA_Media", "volume_contribution"
        ]
        dna_media_all = total_all.set_index("channel").loc[
            "DNA_Media", "volume_contribution"
        ]
        assert dna_media_fh_only < dna_media_all

    def test_outcome_ids_filter_matches_manual_sum_over_the_kept_outcome_ids(
        self, frame, meta, params
    ):
        contributions = compute_shapley_contributions(
            frame, meta, params, n_permutations=20
        )
        fh_only_outcome_ids = ["New", "DNA_CrossSell"]
        total_fh_only = total_fh_contribution(
            frame,
            meta,
            params,
            contributions,
            ltv=None,
            outcome_ids=fh_only_outcome_ids,
        )
        seg_summary = segment_channel_summary(
            frame, meta, params, contributions, ltv=None
        )
        expected = (
            seg_summary[seg_summary["outcome_id"].isin(fh_only_outcome_ids)]
            .groupby("channel")["volume_contribution"]
            .sum()
        )
        for ch in CHANNELS:
            assert total_fh_only.set_index("channel").loc[
                ch, "volume_contribution"
            ] == pytest.approx(expected[ch])


class TestShapleyDirectHaloSeparation:
    """Model A attribution equivalent of test_predict.py's
    TestPredictMuDirectHaloSeparation - proves the same four invariants at
    the Shapley-contribution level. A single-channel model (DNA_Media only)
    makes the Shapley decomposition deterministic (only one permutation
    order exists), so contributions can be checked exactly rather than
    averaged over random removal orders."""

    OUTCOME_IDS = ["New", "DNA_CrossSell", "New Customer"]
    CHANNELS = ["DNA_Media"]
    N_WEEKS = 10
    SPIKE_WEEK = 3

    def _meta(self, dna_lag_weeks: int) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"],
            outcome_ids=self.OUTCOME_IDS,
            channels=self.CHANNELS,
            dna_channels=["DNA_Media"],
            dna_channel_idx=[0],
            non_dna_idx=[],
            dna_outcome_id="DNA_CrossSell",
            dna_lag_weeks=dna_lag_weeks,
            unpooled_markets=[],
            control_names=[],
            direct_dna_outcome_ids=["DNA_CrossSell", "New Customer"],
        )

    def _params(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"DNA_Media": 0.0},
            hill_K={"DNA_Media": 1000.0},
            hill_S={"DNA_Media": 1.0},
            beta={
                "New": {"DNA_Media": 1.0},
                "DNA_CrossSell": {"DNA_Media": 1.0},
                "New Customer": {"DNA_Media": 1.0},
            },
            pathway_strength=pathway_strength_from_flat(
                {"New": 0.5, "DNA_CrossSell": 0.5, "New Customer": 0.0}, "DNA_Media"
            ),
            promo_coef={s: 0.0 for s in self.OUTCOME_IDS},
            market_offset={"UK": {s: 0.0 for s in self.OUTCOME_IDS}},
            intercept={s: 0.0 for s in self.OUTCOME_IDS},
            trend_coef={s: 0.0 for s in self.OUTCOME_IDS},
            gamma_fourier={s: np.zeros(4) for s in self.OUTCOME_IDS},
            alpha={s: 5.0 for s in self.OUTCOME_IDS},
            control_coef={},
            outcome_control_coef={},
        )

    def _frame(self):
        n = self.N_WEEKS
        X_media = np.zeros((n, 1))
        X_media[self.SPIKE_WEEK, 0] = 500.0
        return {
            "markets": ["UK"],
            "market_idx": np.zeros(n, dtype=int),
            "market_bounds": [(0, n)],
            "X_media": X_media,
            "promo": np.zeros((n, len(self.OUTCOME_IDS))),
            "trend": np.zeros(n),
            "fourier": np.zeros((n, 4)),
            "control_names": [],
            "X_controls": np.zeros((n, 0)),
            "outcome_controls": {},
            "outcome_control_names": {},
        }

    def test_kit_only_segment_contribution_does_not_inherit_the_extra_halo_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        contributions = compute_shapley_contributions(
            self._frame(), meta, self._params(), n_permutations=5
        )
        seg_idx = meta.outcome_ids.index("New Customer")
        contrib = contributions["channel_contributions"]["DNA_Media"][:, seg_idx]
        assert contrib[self.SPIKE_WEEK] > 0
        assert contrib[self.SPIKE_WEEK + lag] == pytest.approx(0.0, abs=1e-9)

    def test_fh_halo_segment_contribution_does_inherit_the_extra_lag(self):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        contributions = compute_shapley_contributions(
            self._frame(), meta, self._params(), n_permutations=5
        )
        seg_idx = meta.outcome_ids.index("New")
        contrib = contributions["channel_contributions"]["DNA_Media"][:, seg_idx]
        assert contrib[self.SPIKE_WEEK] == pytest.approx(0.0, abs=1e-9)
        assert contrib[self.SPIKE_WEEK + lag] > 0

    def test_changing_halo_lag_does_not_alter_the_direct_kit_contribution(self):
        params = self._params()
        frame = self._frame()
        seg_idx = self.OUTCOME_IDS.index("New Customer")
        c2 = compute_shapley_contributions(
            frame, self._meta(dna_lag_weeks=2), params, n_permutations=5
        )
        c5 = compute_shapley_contributions(
            frame, self._meta(dna_lag_weeks=5), params, n_permutations=5
        )
        np.testing.assert_allclose(
            c2["channel_contributions"]["DNA_Media"][:, seg_idx],
            c5["channel_contributions"]["DNA_Media"][:, seg_idx],
        )

    def test_dna_cross_sell_contribution_adds_direct_and_halo_without_double_counting(
        self,
    ):
        lag = 2
        meta = self._meta(dna_lag_weeks=lag)
        contributions = compute_shapley_contributions(
            self._frame(), meta, self._params(), n_permutations=5
        )
        contrib = contributions["channel_contributions"]["DNA_Media"]
        cross_idx = meta.outcome_ids.index("DNA_CrossSell")
        kit_idx = meta.outcome_ids.index("New Customer")
        halo_idx = meta.outcome_ids.index("New")

        assert contrib[self.SPIKE_WEEK, cross_idx] == pytest.approx(
            contrib[self.SPIKE_WEEK, kit_idx]
        )
        assert contrib[self.SPIKE_WEEK + lag, cross_idx] == pytest.approx(
            contrib[self.SPIKE_WEEK + lag, halo_idx]
        )
        assert contrib[self.SPIKE_WEEK + lag, kit_idx] == pytest.approx(0.0, abs=1e-9)

        # Additivity still holds exactly for this single-channel model too.
        reconstructed = contributions["baseline"] + contrib
        np.testing.assert_allclose(
            reconstructed, contributions["mu_total"], rtol=1e-6, atol=1e-6
        )


class TestComputeShapleyContributionsFailsClosedForCandidateA:
    """Candidate A attribution must still fail closed when replay evidence
    is absent; a Candidate A engine label alone must never produce an
    incomplete decomposition."""

    def test_raises_without_fit_time_cap_or_replay_evidence(self, meta, params, frame):
        import dataclasses

        from ancestry_mmm.core.attribution import (
            CandidateAAttributionNotSupportedError,
        )
        from ancestry_mmm.core.search_capacity import SEARCH_CANDIDATE_A_ENGINE

        candidate_a_meta = dataclasses.replace(
            meta, causal_graph_engine=SEARCH_CANDIDATE_A_ENGINE
        )
        with pytest.raises(CandidateAAttributionNotSupportedError):
            compute_shapley_contributions(frame, candidate_a_meta, params)


def _candidate_a_attribution_meta_and_trace():
    """Build two deterministic posterior draws for attribution regression tests."""

    channels = ["TV", "Social", "YouTube"]
    outcomes = ["New"]
    n_draws = 2
    posterior = {
        "decay_rate": np.zeros((1, n_draws, len(channels))),
        "hill_K": np.full((1, n_draws, len(channels)), 10.0),
        "hill_S": np.ones((1, n_draws, len(channels))),
        "intercept": np.full((1, n_draws, 1), 1.0),
        "trend_coef": np.zeros((1, n_draws, 1)),
        "promo_coef": np.zeros((1, n_draws, 1)),
        "alpha": np.full((1, n_draws, 1), 5.0),
        "beta": np.full((1, n_draws, 1, len(channels)), 0.01),
        "market_offset": np.zeros((1, n_draws, 1, 1)),
        "gamma_fourier": np.zeros((1, n_draws, 4, 1)),
        "search_demand_intercept": np.full((1, n_draws), 1.0),
        "search_demand_market_offset": np.zeros((1, n_draws, 1)),
        "search_demand_media_beta": np.array(
            [[[0.30, 0.30, 0.00], [0.30, 0.30, 0.30]]]
        ),
        "search_capture_shares": np.tile(
            np.array([0.60, 0.20, 0.10, 0.10]), (1, n_draws, 1)
        ),
        "search_paid_capture_outcome_beta": np.full((1, n_draws, 1), 0.08),
        "search_organic_capture_outcome_beta": np.full((1, n_draws, 1), 0.03),
        "search_direct_navigation_capture_outcome_beta": np.full(
            (1, n_draws, 1), 0.02
        ),
    }
    coords = {
        "channel": channels,
        "outcome": outcomes,
        "market": ["UK"],
        "fourier": list(range(4)),
        "search_demand_channel": channels,
        "search_capture_share_component": ["paid", "organic", "direct", "unmet"],
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "promo_coef": ["outcome"],
        "alpha": ["outcome"],
        "beta": ["outcome", "channel"],
        "market_offset": ["market", "outcome"],
        "gamma_fourier": ["fourier", "outcome"],
        "search_demand_market_offset": ["market"],
        "search_demand_media_beta": ["search_demand_channel"],
        "search_capture_shares": ["search_capture_share_component"],
        "search_paid_capture_outcome_beta": ["outcome"],
        "search_organic_capture_outcome_beta": ["outcome"],
        "search_direct_navigation_capture_outcome_beta": ["outcome"],
    }
    trace = az.from_dict(posterior=posterior, coords=coords, dims=dims)
    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=outcomes,
        channels=channels,
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=list(range(len(channels))),
        dna_outcome_id="New",
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
        causal_graph_engine=SEARCH_CANDIDATE_A_ENGINE,
        candidate_a_historical_paid_search_cap=[0.5, 0.5, 100.0, 100.0],
    )
    frame = {
        "markets": ["UK"],
        "market_idx": np.zeros(4, dtype=int),
        "market_bounds": [(0, 4)],
        # Identical upstream media makes the equal-beta Shapley allocations
        # directly testable without a spend/click-share allocation rule.
        "X_media": np.array(
            [[10.0, 10.0, 10.0], [20.0, 20.0, 20.0], [30.0, 30.0, 30.0], [40.0, 40.0, 40.0]]
        ),
        "promo": np.zeros((4, 1)),
        "trend": np.zeros(4),
        "fourier": np.zeros((4, 4)),
        "control_names": [],
        "X_controls": np.zeros((4, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }
    return meta, trace, frame


class TestCandidateAPosteriorDrawAttribution:
    """Candidate A attribution must reconcile at each posterior draw."""

    def test_direct_mediated_total_and_search_path_reconcile_without_double_counting(
        self,
    ):
        meta, trace, frame = _candidate_a_attribution_meta_and_trace()

        for draw in range(2):
            params = extract_posterior_params(trace, meta, at=(0, draw))
            contributions = compute_shapley_contributions(
                frame, meta, params, n_permutations=120, seed=draw
            )
            mediated = contributions["search_mediated_channel_contributions"]

            np.testing.assert_allclose(
                sum(mediated.values()),
                contributions["search_mediated_contribution"],
                rtol=1e-7,
                atol=1e-8,
            )
            np.testing.assert_allclose(
                contributions["baseline"]
                + sum(contributions["channel_total_contributions"].values())
                + contributions["search_non_media_contribution"],
                contributions["mu_total"],
                rtol=1e-7,
                atol=1e-8,
            )
            for channel in meta.channels:
                np.testing.assert_allclose(
                    contributions["channel_total_contributions"][channel],
                    contributions["channel_contributions"][channel]
                    + mediated.get(channel, 0.0),
                    rtol=1e-7,
                    atol=1e-8,
                )

            summary = outcome_channel_summary(
                frame, meta, params, contributions=contributions, ltv={"New": 1.0}
            )
            for channel in meta.channels:
                row = summary[summary["channel"] == channel].iloc[0]
                assert row["total_effect"] == pytest.approx(
                    row["direct_effect"] + row["mediated_via_search_effect"]
                )
                assert row["volume_contribution"] == pytest.approx(
                    row["total_effect"]
                )
            search_row = summary[
                summary["channel"] == "Search-mediated Candidate A"
            ].iloc[0]
            assert search_row["component_type"] == "search_pathway_view"
            assert not bool(search_row["additive_to_media_total"])

            total = total_fh_contribution(
                frame, meta, params, contributions=contributions, ltv={"New": 1.0}
            )
            assert set(total["channel"]) == set(meta.channels)
            for channel in meta.channels:
                expected = float(
                    contributions["channel_total_contributions"][channel].sum()
                )
                assert total.set_index("channel").loc[
                    channel, "volume_contribution"
                ] == pytest.approx(expected)

            waterfall = contribution_waterfall(
                frame, meta, params, contributions=contributions
            )
            assert waterfall.iloc[-1]["category"] == "Total"
            assert waterfall.iloc[:-1]["value"].sum() == pytest.approx(
                waterfall.iloc[-1]["value"]
            )

        # Draw 0 has no YouTube demand coefficient, so its mediated effect is
        # exactly zero even though YouTube has direct media response.
        draw_zero = extract_posterior_params(trace, meta, at=(0, 0))
        zero_effect = compute_shapley_contributions(
            frame, meta, draw_zero, n_permutations=120
        )
        np.testing.assert_allclose(
            zero_effect["search_mediated_channel_contributions"]["YouTube"],
            0.0,
            atol=1e-10,
        )
        assert np.any(
            zero_effect["search_mediated_channel_contributions"]["TV"] > 0
        )

        # Draw 1 has identical media and equal demand coefficients, so the
        # posterior-draw Shapley value is symmetric across all three players.
        draw_equal = extract_posterior_params(trace, meta, at=(0, 1))
        equal_effect = compute_shapley_contributions(
            frame, meta, draw_equal, n_permutations=120
        )
        np.testing.assert_allclose(
            equal_effect["search_mediated_channel_contributions"]["TV"],
            equal_effect["search_mediated_channel_contributions"]["Social"],
            rtol=1e-7,
            atol=1e-8,
        )
        np.testing.assert_allclose(
            equal_effect["search_mediated_channel_contributions"]["Social"],
            equal_effect["search_mediated_channel_contributions"]["YouTube"],
            rtol=1e-7,
            atol=1e-8,
        )

    def test_binding_cap_changes_mediated_final_outcome_effect(self):
        import dataclasses

        meta, trace, frame = _candidate_a_attribution_meta_and_trace()
        params = extract_posterior_params(trace, meta, at=(0, 1))
        binding_meta = dataclasses.replace(
            meta, candidate_a_historical_paid_search_cap=[0.5] * 4
        )
        nonbinding_meta = dataclasses.replace(
            meta, candidate_a_historical_paid_search_cap=[100.0] * 4
        )
        binding = compute_shapley_contributions(
            frame, binding_meta, params, n_permutations=120
        )
        nonbinding = compute_shapley_contributions(
            frame, nonbinding_meta, params, n_permutations=120
        )

        assert np.all(
            binding["search_mediated_contribution"]
            <= nonbinding["search_mediated_contribution"] + 1e-9
        )
        assert np.any(
            nonbinding["search_mediated_contribution"]
            > binding["search_mediated_contribution"] + 1e-8
        )

    def test_single_identified_upstream_channel_does_not_receive_other_channels_credit(
        self,
    ):
        import dataclasses

        meta, trace, frame = _candidate_a_attribution_meta_and_trace()
        params = extract_posterior_params(trace, meta, at=(0, 1))
        assert params.candidate_a_replay_params is not None
        single_replay = dataclasses.replace(
            params.candidate_a_replay_params,
            demand_channel_names=["TV"],
            demand_media_beta={
                "TV": params.candidate_a_replay_params.demand_media_beta["TV"]
            },
        )
        single_params = dataclasses.replace(
            params, candidate_a_replay_params=single_replay
        )
        contributions = compute_shapley_contributions(
            frame, meta, single_params, n_permutations=20
        )

        assert np.any(
            contributions["search_mediated_channel_contributions"]["TV"] > 0
        )
        np.testing.assert_allclose(
            contributions["search_mediated_channel_contributions"].get(
                "Social", 0.0
            ),
            0.0,
            atol=1e-10,
        )
        np.testing.assert_allclose(
            contributions["search_mediated_channel_contributions"].get(
                "YouTube", 0.0
            ),
            0.0,
            atol=1e-10,
        )
