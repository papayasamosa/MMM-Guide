"""Tests for REQ-VAL-001 predictive-density evidence (Work Package 3):

- ``core.diagnostics.predictive_density_summary`` (``pm.compute_log_likelihood``
  + ArviZ PSIS-LOO/WAIC) against a real, small, actually-fitted Model A
  trace.
- ``application.diagnostics_service.DiagnosticsService.
  run_predictive_density_check``, the pure/immutable artefact-update path.

Unlike prior-predictive evidence (test_prior_predictive.py), this needs a
real fitted trace, not just an unfit model - a genuine (small) MCMC fit is
unavoidable to prove the real builder/trace pair actually produces this
evidence. The fit itself is deliberately tiny (few draws/tune, matching this
project's existing convention for a fast-but-real check, e.g.
docs/decision_log.md's Model C recovery check) and shared across every test
in this module via a module-scoped fixture, so the CI cost of the one real
fit is paid exactly once, not once per assertion.
"""

from __future__ import annotations

import numpy as np
import pytest

from ancestry_mmm.application.diagnostics_service import (
    CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
    CURRENT_DIAGNOSTICS_VERSION,
    DiagnosticSection,
    DiagnosticsArtefact,
    DiagnosticsService,
)
from ancestry_mmm.core.diagnostics import predictive_density_summary
from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.schema import ModelSpec

BUILDERS = [build_fh_hierarchical_model, build_fh_market_specific_model]


def _small_frame() -> dict:
    """Same minimal 2-market, 2-channel, 2-outcome shape as
    test_prior_predictive.py._small_frame - reused rather than inventing a
    second fixture shape."""
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


@pytest.fixture(scope="module")
def fitted_model_and_trace():
    """One real, tiny fit (build_fh_hierarchical_model), shared by every
    test in this module - the real-fit cost is paid exactly once."""
    frame = _small_frame()
    spec = _spec()
    model, meta = build_fh_hierarchical_model(frame, spec)
    trace = fit_model(
        model, draws=20, tune=20, chains=2, cores=1, target_accept=0.8, random_seed=1
    )
    return model, meta, frame, trace


class TestPredictiveDensitySummaryRealBuilder:
    def test_returns_overall_and_pointwise_evidence(self, fitted_model_and_trace):
        model, meta, frame, trace = fitted_model_and_trace

        result = predictive_density_summary(model, trace, frame, meta)

        assert isinstance(result["elpd_loo"], float)
        assert isinstance(result["elpd_waic"], float)
        assert result["n_data_points"] == 6 * 2  # n_obs x n_outcome
        rows = result["rows"]
        assert len(rows) == len(frame["markets"]) * len(meta.outcome_ids)
        keys = {(r["market"], r["outcome_id"]) for r in rows}
        assert keys == {(m, o) for m in frame["markets"] for o in meta.outcome_ids}

    def test_pointwise_rows_reconcile_observation_counts(self, fitted_model_and_trace):
        model, meta, frame, trace = fitted_model_and_trace

        result = predictive_density_summary(model, trace, frame, meta)

        for row in result["rows"]:
            assert row["n_observations"] == 3  # each market has 3 rows
            assert (
                row["n_good_pareto_k"]
                + row["n_bad_pareto_k"]
                + row["n_very_bad_pareto_k"]
                == row["n_observations"]
            )

    def test_does_not_mutate_the_original_trace(self, fitted_model_and_trace):
        """core.diagnostics.predictive_density_summary must never mutate the
        caller's trace - pm.compute_log_likelihood(extend_inferencedata=True)
        (the default) mutates whatever InferenceData it's given in place, so
        this function must operate on its own copy."""
        model, meta, frame, trace = fitted_model_and_trace
        groups_before = list(trace.groups())

        predictive_density_summary(model, trace, frame, meta)

        assert list(trace.groups()) == groups_before
        assert "log_likelihood" not in trace.groups()

    def test_repeated_calls_are_stable(self, fitted_model_and_trace):
        model, meta, frame, trace = fitted_model_and_trace

        first = predictive_density_summary(model, trace, frame, meta)
        second = predictive_density_summary(model, trace, frame, meta)

        assert first["elpd_loo"] == second["elpd_loo"]
        assert first["rows"] == second["rows"]


class TestRunPredictiveDensityCheck:
    def test_computed_path_replaces_only_the_predictive_density_section(
        self, fitted_model_and_trace
    ):
        model, meta, frame, trace = fitted_model_and_trace
        convergence = DiagnosticSection(
            status="computed", payload={"max_rhat": 1.0, "min_ess": 500.0}
        )
        artefact = DiagnosticsArtefact(convergence=convergence)

        updated = DiagnosticsService().run_predictive_density_check(
            artefact,
            model=model,
            trace=trace,
            frame=frame,
            meta=meta,
            model_type="shared",
        )

        assert updated.predictive_density.status == "computed"
        assert updated.predictive_density.payload["model_type"] == "shared"
        assert len(updated.predictive_density.payload["rows"]) == 4
        assert updated.convergence == artefact.convergence

    def test_failure_is_explicit_not_fabricated_zero_evidence(
        self, fitted_model_and_trace
    ):
        _, meta, frame, trace = fitted_model_and_trace
        artefact = DiagnosticsArtefact()

        updated = DiagnosticsService().run_predictive_density_check(
            artefact,
            model=None,  # not a real pm.Model - forces an explicit failure
            trace=trace,
            frame=frame,
            meta=meta,
            model_type="shared",
        )

        assert updated.predictive_density.status == "failed"
        assert updated.predictive_density.error
        assert updated.predictive_density.payload is None

    def test_default_artefact_section_is_not_computed(self):
        assert DiagnosticsArtefact().predictive_density.status == "not_computed"

    def test_upgrades_a_pre_v5_artefact_and_survives_round_trip(
        self, fitted_model_and_trace
    ):
        model, meta, frame, trace = fitted_model_and_trace
        v4_artefact = DiagnosticsArtefact(schema_version=4, diagnostics_version="4.0.0")

        updated = DiagnosticsService().run_predictive_density_check(
            v4_artefact,
            model=model,
            trace=trace,
            frame=frame,
            meta=meta,
            model_type="shared",
        )

        assert updated.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert updated.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION
        assert updated.predictive_density.status == "computed"

        restored = DiagnosticsArtefact.from_dict(updated.to_dict())
        assert restored.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert restored.predictive_density.status == "computed"
        assert restored.predictive_density.payload == updated.predictive_density.payload
        assert restored.fingerprint() == updated.fingerprint()

    def test_record_predictive_density_failure_upgrades_a_v4_origin_artefact(self):
        v4_artefact = DiagnosticsArtefact(schema_version=4, diagnostics_version="4.0.0")

        updated = DiagnosticsService().record_predictive_density_failure(
            v4_artefact, "could not rebuild the model"
        )

        assert updated.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert updated.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION
        assert updated.predictive_density.status == "failed"

        restored = DiagnosticsArtefact.from_dict(updated.to_dict())
        assert restored.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert restored.predictive_density.status == "failed"

    def test_fingerprint_changes_when_section_changes(self, fitted_model_and_trace):
        model, meta, frame, trace = fitted_model_and_trace
        artefact = DiagnosticsArtefact()
        before_fp = artefact.fingerprint()

        updated = DiagnosticsService().run_predictive_density_check(
            artefact,
            model=model,
            trace=trace,
            frame=frame,
            meta=meta,
            model_type="shared",
        )

        assert updated.fingerprint() != before_fp
