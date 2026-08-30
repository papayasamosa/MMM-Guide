"""Tests for core.model_comparison - frame slicing for Model B, and the
comparison-candidate bookkeeping used by pages/12_Compare_Models.py."""

import json

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.model_comparison import (
    ModelComparisonCandidate,
    candidates_decision_summary_dataframe,
    candidates_to_dataframe,
    slice_frame_to_market,
)
from ancestry_mmm.core.models import compute_model_diagnostics


@pytest.fixture
def two_market_frame():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6, freq="W"),
            "market": ["UK", "UK", "UK", "AU", "AU", "AU"],
        }
    )
    return {
        "markets": ["UK", "AU"],
        "market_idx": np.array([0, 0, 0, 1, 1, 1]),
        "market_bounds": [(0, 3), (3, 6)],
        "unpooled_markets": ["AU"],
        "X_media": np.arange(12.0).reshape(6, 2),
        "Y": np.arange(6.0).reshape(6, 1),
        "promo": np.zeros((6, 1)),
        "X_controls": np.zeros((6, 0)),
        "fourier": np.zeros((6, 2)),
        "trend": np.linspace(1.0, 1.5, 6),
        "dates": df["date"].to_numpy(),
        "segment_controls": {"New": np.zeros((6, 1))},
        "df": df,
        "channels": ["TV", "DNA_Media"],
        "segments": ["New"],
    }


class TestSliceFrameToMarket:
    def test_unknown_market_raises(self, two_market_frame):
        with pytest.raises(ValueError, match="not one of this frame's markets"):
            slice_frame_to_market(two_market_frame, "FR")

    def test_sliced_frame_has_a_single_market_starting_at_zero(self, two_market_frame):
        sliced = slice_frame_to_market(two_market_frame, "AU")
        assert sliced["markets"] == ["AU"]
        assert sliced["market_bounds"] == [(0, 3)]
        np.testing.assert_array_equal(sliced["market_idx"], np.zeros(3, dtype=int))

    def test_sliced_frame_carries_only_that_markets_rows(self, two_market_frame):
        sliced = slice_frame_to_market(two_market_frame, "UK")
        np.testing.assert_array_equal(
            sliced["X_media"], two_market_frame["X_media"][:3]
        )
        np.testing.assert_array_equal(sliced["Y"], two_market_frame["Y"][:3])
        assert len(sliced["df"]) == 3
        assert set(sliced["df"]["market"]) == {"UK"}

    def test_unpooled_markets_is_cleared_since_a_single_market_has_nothing_to_pool_with(
        self, two_market_frame
    ):
        sliced = slice_frame_to_market(two_market_frame, "AU")
        assert sliced["unpooled_markets"] == []

    def test_original_frame_is_not_mutated(self, two_market_frame):
        original_markets = list(two_market_frame["markets"])
        slice_frame_to_market(two_market_frame, "UK")
        assert two_market_frame["markets"] == original_markets


class TestModelComparisonCandidate:
    def test_to_dict_from_dict_round_trip(self):
        candidate = ModelComparisonCandidate(
            model_type="C",
            label="Model C - UK, AU",
            model_run_id="run-1",
            fitted_at=1700000000.0,
            market=None,
            convergence={"rhat_max": 1.01, "converged": True},
            in_sample_fit=[{"segment": "New", "r_squared": 0.9}],
            ppc_coverage=[{"segment": "New", "coverage_pct": 91.0}],
            n_plausibility_flags=2,
        )
        restored = ModelComparisonCandidate.from_dict(candidate.to_dict())
        assert restored == candidate

    def test_from_dict_ignores_unknown_keys(self):
        d = {
            "model_type": "A",
            "label": "Model A",
            "model_run_id": "run-2",
            "fitted_at": 1.0,
            "some_future_field": "ignored",
        }
        candidate = ModelComparisonCandidate.from_dict(d)
        assert candidate.model_type == "A"
        assert candidate.market is None

    def test_from_dict_migrates_legacy_stringified_converged_value(self):
        """Codex review, PR #348 (P2): a bundle saved before the UX-021 fix
        persisted `convergence["converged"]` as `numpy.bool_`, which
        `json.dumps(..., default=str)` stringified to the literal text
        "False" - truthy on naive read-back, and a value
        `candidates_decision_summary_dataframe`'s `pandas.astype("boolean")`
        cannot interpret and would raise on. `from_dict` must normalize that
        legacy string form to a real bool at the persistence boundary
        (core/AGENTS.md "Persistence boundaries": migrations belong here),
        for both "False" and "True", so the page renders correctly for
        exactly the historical bundles the UX-021 fix was meant to repair."""
        legacy_false = ModelComparisonCandidate.from_dict(
            {
                "model_type": "A",
                "label": "Model A (legacy bundle)",
                "model_run_id": "run-legacy-false",
                "fitted_at": 1.0,
                "convergence": {"rhat_max": 1.2, "converged": "False"},
            }
        )
        assert legacy_false.convergence["converged"] is False

        legacy_true = ModelComparisonCandidate.from_dict(
            {
                "model_type": "A",
                "label": "Model A (legacy bundle, converged)",
                "model_run_id": "run-legacy-true",
                "fitted_at": 1.0,
                "convergence": {"rhat_max": 1.0, "converged": "True"},
            }
        )
        assert legacy_true.convergence["converged"] is True

        # The actual regression this guards against: building the decision
        # summary table must not raise for a legacy-string candidate, and
        # must show the real (non-converged) status rather than a truthy
        # stringified one.
        df = candidates_decision_summary_dataframe([legacy_false, legacy_true])
        assert df.loc[0, "converged"] is False or df.loc[0, "converged"] == False  # noqa: E712
        assert df.loc[1, "converged"] is True or df.loc[1, "converged"] == True  # noqa: E712

    def test_from_scorecard_extracts_the_relevant_pieces(self):
        scorecard = {
            "convergence": {"rhat_max": 1.02, "converged": True},
            "in_sample_fit": [{"segment": "New", "r_squared": 0.8}],
            "ppc_coverage": [{"segment": "New", "coverage_pct": 88.0}],
            "plausibility_flags": [
                {"level": "warning", "channel": "TV", "message": "..."}
            ],
        }
        candidate = ModelComparisonCandidate.from_scorecard(
            model_type="B",
            label="Model B - UK",
            model_run_id="run-3",
            fitted_at=2.0,
            scorecard=scorecard,
            market="UK",
        )
        assert candidate.market == "UK"
        assert candidate.convergence == scorecard["convergence"]
        assert candidate.n_plausibility_flags == 1

    def test_from_scorecard_defaults_missing_scorecard_keys(self):
        candidate = ModelComparisonCandidate.from_scorecard(
            model_type="A",
            label="Model A",
            model_run_id="run-4",
            fitted_at=3.0,
            scorecard={},
        )
        assert candidate.convergence == {}
        assert candidate.in_sample_fit == []
        assert candidate.n_plausibility_flags == 0


class TestCandidatesToDataframe:
    def test_one_row_per_candidate_with_means_collapsed_across_segments(self):
        candidates = [
            ModelComparisonCandidate(
                model_type="A",
                label="Model A",
                model_run_id="run-1",
                fitted_at=1.0,
                convergence={
                    "rhat_max": 1.0,
                    "ess_min": 500,
                    "divergences": 0,
                    "converged": True,
                },
                in_sample_fit=[
                    {"segment": "New", "r_squared": 0.8},
                    {"segment": "Winback", "r_squared": 0.6},
                ],
                ppc_coverage=[
                    {"segment": "New", "coverage_pct": 90.0},
                    {"segment": "Winback", "coverage_pct": 88.0},
                ],
                n_plausibility_flags=0,
            ),
            ModelComparisonCandidate(
                model_type="C",
                label="Model C",
                model_run_id="run-2",
                fitted_at=2.0,
                convergence={},
                in_sample_fit=[],
                ppc_coverage=[],
                n_plausibility_flags=3,
            ),
        ]
        df = candidates_to_dataframe(candidates)
        assert len(df) == 2
        assert df.loc[0, "mean_r_squared"] == pytest.approx(0.7)
        assert df.loc[0, "mean_ppc_coverage_pct"] == pytest.approx(89.0)
        assert pd.isna(df.loc[1, "mean_r_squared"])
        assert df.loc[1, "market"] == "(all)"

    def test_market_column_shows_the_candidates_market_when_set(self):
        candidate = ModelComparisonCandidate(
            model_type="B",
            label="Model B - UK",
            model_run_id="run-1",
            fitted_at=1.0,
            market="UK",
        )
        df = candidates_to_dataframe([candidate])
        assert df.loc[0, "market"] == "UK"

    def test_empty_candidate_list_gives_empty_dataframe(self):
        df = candidates_to_dataframe([])
        assert df.empty

    def test_a_single_candidate_missing_ppc_coverage_shows_blank_not_the_word_none(
        self,
    ):
        """UX-022: reproduces the exact real-world case found reviewing a
        populated Compare Models page - one saved candidate with no
        posterior predictive coverage evidence recorded (e.g. a synthetic or
        otherwise limited trace). Before this fix, a column that is None for
        every row stays object-dtype, and dataframe_column_config falls back
        to a TextColumn that renders the literal word "None" in the
        analyst-facing table - exactly the kind of raw-value leak this
        review exists to catch."""
        candidate = ModelComparisonCandidate(
            model_type="A",
            label="Model A - shared curve (UK)",
            model_run_id="run-1",
            fitted_at=1.0,
            convergence={"rhat_max": 1.38, "ess_min": 9.0, "converged": False},
            in_sample_fit=[{"outcome_id": "New", "r_squared": 0.5, "mape_pct": 12.0}],
            ppc_coverage=[],  # no PPC evidence for this candidate at all
            n_plausibility_flags=0,
        )
        df = candidates_to_dataframe([candidate])
        assert pd.isna(df.loc[0, "mean_ppc_coverage_pct"])
        assert str(df["mean_ppc_coverage_pct"].dtype) == "Float64"
        assert str(df["converged"].dtype) == "boolean"
        assert bool(df.loc[0, "converged"]) is False


def _multi_channel_trace(*, chains: int = 2, draws: int = 10) -> az.InferenceData:
    """A trace with a >1-element variable (``decay_rate`` over 2 channels) -
    the shape that makes ``np.max``/``np.min`` (inside
    ``compute_model_diagnostics``) return a numpy scalar rather than a
    native Python float, which is what previously let a numpy type leak
    into ``rhat_max``/``ess_min``/``converged`` (UX-021)."""
    rng = np.random.default_rng(0)
    posterior = {
        "decay_rate": rng.uniform(0.1, 0.9, size=(chains, draws, 2)),
        "intercept": rng.normal(size=(chains, draws)),
    }
    return az.from_dict(
        posterior=posterior,
        coords={"channel": ["TV", "Radio"]},
        dims={"decay_rate": ["channel"]},
    )


class TestComputeModelDiagnosticsJsonSafety:
    """UX-021: a non-converged candidate's status must survive an
    export/import round-trip, not silently flip to "Converged". Root cause:
    ``compute_model_diagnostics`` returned ``numpy.float64``/``numpy.bool_``
    for ``rhat_max``/``ess_min``/``converged`` whenever any posterior
    variable had more than one element (the overwhelmingly common real-model
    case - any model with >1 channel, market, or outcome). Every one of
    those types is not natively JSON-serialisable; `core.persistence`'s
    ``export_project`` writes ``model_comparison_candidates`` via
    ``json.dumps(..., default=str)``, which silently stringifies a
    ``numpy.bool_(False)`` into the literal text ``"False"`` - a non-empty
    string, and therefore truthy on read-back. A candidate that genuinely
    did not converge would render "Converged" on Compare Models after any
    project export + re-import, which is precisely the kind of misleading
    precision this review exists to catch."""

    def test_rhat_max_and_ess_min_are_native_python_floats(self):
        diagnostics = compute_model_diagnostics(_multi_channel_trace())
        assert type(diagnostics["rhat_max"]) is float
        assert type(diagnostics["ess_min"]) is float

    def test_converged_is_a_native_python_bool_not_numpy_bool(self):
        diagnostics = compute_model_diagnostics(_multi_channel_trace())
        assert type(diagnostics["converged"]) is bool

    def test_diagnostics_dict_survives_a_default_str_json_round_trip(self):
        """Reproduces the exact serialisation core.persistence.export_project
        uses for model_comparison_candidates - a non-converged result must
        still read back as non-converged, not as the truthy string "False"."""
        diagnostics = compute_model_diagnostics(_multi_channel_trace())
        assert (
            diagnostics["converged"] is False
        )  # this fixture's tiny trace never converges

        candidate = ModelComparisonCandidate.from_scorecard(
            model_type="A",
            label="Model A - shared curve",
            model_run_id="run-ux021",
            fitted_at=1.0,
            scorecard={"convergence": diagnostics},
        )
        serialized = json.dumps(candidate.to_dict(), default=str)
        restored = ModelComparisonCandidate.from_dict(json.loads(serialized))
        # If `converged` had leaked through as the string "False" (the bug),
        # this identity check against the real Python singleton would fail -
        # a truthy non-empty string is not `is False`.
        assert restored.convergence["converged"] is False


class TestCandidatesDecisionSummaryDataframe:
    def test_only_the_decision_relevant_columns_are_present(self):
        candidate = ModelComparisonCandidate(
            model_type="A",
            label="Model A",
            model_run_id="run-1",
            fitted_at=1.0,
            convergence={"rhat_max": 1.0, "converged": True},
            n_plausibility_flags=2,
        )
        df = candidates_decision_summary_dataframe([candidate])
        assert list(df.columns) == [
            "label",
            "model_type",
            "market",
            "converged",
            "plausibility_flags",
        ]
        # No composite score column of any kind - convergence, predictive
        # fit and plausibility must never collapse into one ranking number.
        forbidden_substrings = ["score", "rank", "overall"]
        for col in df.columns:
            for forbidden in forbidden_substrings:
                assert forbidden not in col.lower()

    def test_reflects_converged_and_flag_count(self):
        candidates = [
            ModelComparisonCandidate(
                model_type="A",
                label="Model A",
                model_run_id="run-1",
                fitted_at=1.0,
                market=None,
                convergence={"converged": True},
                n_plausibility_flags=0,
            ),
            ModelComparisonCandidate(
                model_type="C",
                label="Model C - UK",
                model_run_id="run-2",
                fitted_at=2.0,
                market="UK",
                convergence={"converged": False},
                n_plausibility_flags=3,
            ),
        ]
        df = candidates_decision_summary_dataframe(candidates)
        assert bool(df.loc[0, "converged"]) is True
        assert df.loc[0, "market"] == "(all)"
        assert bool(df.loc[1, "converged"]) is False
        assert df.loc[1, "market"] == "UK"
        assert df.loc[1, "plausibility_flags"] == 3

    def test_missing_convergence_data_shows_as_none_not_a_score(self):
        candidate = ModelComparisonCandidate(
            model_type="A",
            label="Model A",
            model_run_id="run-1",
            fitted_at=1.0,
            convergence={},
            n_plausibility_flags=0,
        )
        df = candidates_decision_summary_dataframe([candidate])
        # UX-022: the "converged" column is forced onto pandas' nullable
        # "boolean" dtype specifically so this missing value renders as a
        # blank/indeterminate checkbox cell on the real page (via
        # utils.display.dataframe_column_config's dtype-based
        # CheckboxColumn selection), not the literal text "None" that an
        # object-dtype all-None column would otherwise fall back to
        # (dataframe_column_config picks TextColumn for object dtype). The
        # value itself is still "no score", just represented as pd.NA
        # rather than Python's `None` singleton.
        assert pd.isna(df.loc[0, "converged"])
        assert str(df["converged"].dtype) == "boolean"

    def test_empty_candidate_list_gives_empty_dataframe(self):
        df = candidates_decision_summary_dataframe([])
        assert df.empty
