"""Tests for REQ-VAL-001 prior predictive evidence (Work Package 2):

- ``core.diagnostics.prior_predictive_summary`` against the real Model A
  (``build_fh_hierarchical_model``) and Model C
  (``build_fh_market_specific_model``) builders.
- ``application.diagnostics_service.DiagnosticsService.
  run_prior_predictive_check``, the pure/immutable artefact-update path.

Builds a real (unfit) PyMC model and calls the real
``pm.sample_prior_predictive`` - deliberately not skipped, unlike this
project's usual "no PyMC model in the test suite" convention for full MCMC
recovery checks (test_hierarchical_model.py's docstring): prior predictive
sampling needs no MCMC and is fast, and REQ-VAL-001 requires evidence that
the real model builders can actually produce this evidence, not only that
the summarisation math is correct in isolation.
"""

from __future__ import annotations

import numpy as np
import pytest

from ancestry_mmm.application.diagnostics_service import (
    DiagnosticSection,
    DiagnosticsArtefact,
    DiagnosticsService,
)
from ancestry_mmm.core.diagnostics import prior_predictive_summary
from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.schema import ModelSpec

BUILDERS = [build_fh_hierarchical_model, build_fh_market_specific_model]


def _small_frame() -> dict:
    """A minimal 2-market, 2-channel, 2-outcome frame - the same shape
    test_g111_hotfix.py already uses successfully against both real
    builders, reused here rather than inventing a second fixture shape."""
    return {
        "markets": ["UK", "US"],
        "market_idx": np.array([0, 0, 0, 1, 1, 1]),
        "market_bounds": [(0, 3), (3, 6)],
        "channels": ["TV", "Radio"],
        "dna_channel_idx": [],
        "outcome_ids": ["new", "winback"],
        "outcomes": [],
        "X_media": np.array(
            [
                [1.0, 2.0],
                [2.0, 3.0],
                [3.0, 4.0],
                [1.5, 2.5],
                [2.5, 3.5],
                [3.5, 4.5],
            ]
        ),
        "Y": np.array(
            [
                [3.0, 5.0],
                [4.0, 6.0],
                [5.0, 7.0],
                [3.5, 5.5],
                [4.5, 6.5],
                [5.5, 7.5],
            ]
        ),
        "promo": np.zeros((6, 2)),
        "X_controls": np.zeros((6, 0)),
        "control_names": [],
        "fourier": np.zeros((6, 2)),
        "trend": np.tile(np.linspace(0, 1, 3), 2),
        "unpooled_markets": [],
        "media_outcome_pathways": [],
    }


def _spec() -> ModelSpec:
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK", "US"],
        segment_outcomes={"new": "new", "winback": "winback"},
        channels=["TV", "Radio"],
    )


class TestPriorPredictiveSummaryRealBuilders:
    @pytest.mark.parametrize("builder", BUILDERS)
    def test_produces_one_row_per_market_x_outcome(self, builder):
        frame = _small_frame()
        spec = _spec()
        model, meta = builder(frame, spec)

        result = prior_predictive_summary(
            model, frame, meta, n_samples=10, random_seed=7
        )

        assert result["n_samples"] == 10
        assert result["random_seed"] == 7
        rows = result["rows"]
        assert len(rows) == len(frame["markets"]) * len(meta.outcome_ids)
        keys = {(r["market"], r["outcome_id"]) for r in rows}
        assert keys == {(m, o) for m in frame["markets"] for o in meta.outcome_ids}

    @pytest.mark.parametrize("builder", BUILDERS)
    def test_row_draw_counts_and_finiteness_reconcile(self, builder):
        frame = _small_frame()
        spec = _spec()
        model, meta = builder(frame, spec)

        result = prior_predictive_summary(
            model, frame, meta, n_samples=10, random_seed=7
        )

        for row in result["rows"]:
            assert row["n_draws"] == 10 * row["n_observations"]
            assert row["finite_count"] + row["non_finite_count"] == row["n_draws"]
            # y_obs is a NegativeBinomial draw - outcome counts are never negative.
            if row["finite_count"] > 0:
                assert row["min"] >= 0

    def test_same_seed_on_freshly_built_models_is_deterministic(self):
        frame = _small_frame()
        spec = _spec()

        model_a, meta_a = build_fh_hierarchical_model(frame, spec)
        result_a = prior_predictive_summary(
            model_a, frame, meta_a, n_samples=20, random_seed=42
        )

        model_b, meta_b = build_fh_hierarchical_model(frame, spec)
        result_b = prior_predictive_summary(
            model_b, frame, meta_b, n_samples=20, random_seed=42
        )

        assert result_a["rows"] == result_b["rows"]

    def test_repeated_calls_on_the_same_model_are_stable(self):
        """No prior is changed by running the diagnostic: calling it twice
        on the exact same (unfit) model with the same seed must give
        identical evidence, not drifting state."""
        frame = _small_frame()
        spec = _spec()
        model, meta = build_fh_hierarchical_model(frame, spec)

        first = prior_predictive_summary(
            model, frame, meta, n_samples=8, random_seed=99
        )
        second = prior_predictive_summary(
            model, frame, meta, n_samples=8, random_seed=99
        )

        assert first["rows"] == second["rows"]

    def test_different_seeds_give_different_draws(self):
        frame = _small_frame()
        spec = _spec()
        model, meta = build_fh_hierarchical_model(frame, spec)

        first = prior_predictive_summary(
            model, frame, meta, n_samples=50, random_seed=1
        )
        second = prior_predictive_summary(
            model, frame, meta, n_samples=50, random_seed=2
        )

        assert first["rows"] != second["rows"]


class TestRunPriorPredictiveCheck:
    def test_computed_path_replaces_only_the_prior_predictive_section(self):
        frame = _small_frame()
        spec = _spec()
        model, meta = build_fh_hierarchical_model(frame, spec)

        convergence = DiagnosticSection(
            status="computed", payload={"max_rhat": 1.0, "min_ess": 500.0}
        )
        artefact = DiagnosticsArtefact(convergence=convergence)

        updated = DiagnosticsService().run_prior_predictive_check(
            artefact,
            model=model,
            frame=frame,
            meta=meta,
            model_type="shared",
            n_samples=5,
            random_seed=3,
        )

        assert updated.prior_predictive.status == "computed"
        assert updated.prior_predictive.payload["model_type"] == "shared"
        assert updated.prior_predictive.payload["n_samples"] == 5
        assert updated.prior_predictive.payload["random_seed"] == 3
        assert (
            len(updated.prior_predictive.payload["rows"]) == 4
        )  # 2 markets x 2 outcomes
        # Every other section is carried over unchanged (pure update, same
        # contract as run_backtest).
        assert updated.convergence == artefact.convergence
        assert updated.in_sample_fit == artefact.in_sample_fit

    def test_sampling_failure_is_explicit_not_fabricated_zero_evidence(self):
        frame = _small_frame()
        spec = _spec()
        _, meta = build_fh_hierarchical_model(frame, spec)
        artefact = DiagnosticsArtefact()

        updated = DiagnosticsService().run_prior_predictive_check(
            artefact,
            model=None,  # not a real pm.Model - forces an explicit failure
            frame=frame,
            meta=meta,
            model_type="shared",
        )

        assert updated.prior_predictive.status == "failed"
        assert updated.prior_predictive.error
        assert updated.prior_predictive.payload is None

    def test_default_artefact_section_is_not_computed(self):
        assert DiagnosticsArtefact().prior_predictive.status == "not_computed"

    def test_fingerprint_changes_when_prior_predictive_section_changes(self):
        frame = _small_frame()
        spec = _spec()
        model, meta = build_fh_hierarchical_model(frame, spec)
        artefact = DiagnosticsArtefact()
        before_fp = artefact.fingerprint()

        updated = DiagnosticsService().run_prior_predictive_check(
            artefact,
            model=model,
            frame=frame,
            meta=meta,
            model_type="shared",
            n_samples=3,
        )

        assert updated.fingerprint() != before_fp
