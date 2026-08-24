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
    CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
    CURRENT_DIAGNOSTICS_VERSION,
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


class TestPriorPredictiveComponentDecomposition:
    """WP2.5 (real UK evidence review, 2026-08-24): the observed q95
    prior-predictive tail is around 1.2-1.25 billion against observed
    weekly outcomes in the thousands. `component_var_names` exposes each
    named additive log-linear-predictor term
    (`core.hierarchical_model.build_fh_hierarchical_model`'s
    `eta_trend`/`eta_season`/`eta_market`/`eta_promo`/`eta_controls`/
    `eta_channels`, plus `intercept`/`alpha`) so the dominant term can be
    identified without changing any prior - diagnostic-only, opt-in
    (omitting the parameter reproduces every pre-existing test above
    unchanged)."""

    COMPONENT_NAMES = [
        "intercept",
        "eta_trend",
        "eta_season",
        "eta_market",
        "eta_promo",
        "eta_controls",
        "eta_channels",
        "mu",
        "alpha",
    ]

    def test_omitted_by_default_matches_pre_existing_behaviour(self):
        frame = _small_frame()
        spec = _spec()
        model, meta = build_fh_hierarchical_model(frame, spec)

        result = prior_predictive_summary(
            model, frame, meta, n_samples=10, random_seed=7
        )

        assert (
            result["plausibility"]["component_decomposition"]["status"] == "unavailable"
        )

    def test_requested_components_are_summarised_without_error(self):
        frame = _small_frame()
        spec = _spec()
        model, meta = build_fh_hierarchical_model(frame, spec)

        result = prior_predictive_summary(
            model,
            frame,
            meta,
            n_samples=20,
            random_seed=7,
            component_var_names=self.COMPONENT_NAMES,
        )

        decomposition = result["plausibility"]["component_decomposition"]
        assert decomposition["status"] == "available"
        assert set(decomposition["components"]) == set(self.COMPONENT_NAMES)
        for name in self.COMPONENT_NAMES:
            component = decomposition["components"][name]
            assert component["finite"] is True
            assert component["n_values"] > 0

    def test_a_component_name_the_model_does_not_declare_is_silently_skipped(self):
        """Never raises for a name that doesn't exist on this particular
        model (e.g. requesting a Model-A-only term against Model C, or a
        typo) - it is simply absent from the returned components, so a
        caller requesting a broad, shared name list against either builder
        never has to know which names each one declares."""
        frame = _small_frame()
        spec = _spec()
        model, meta = build_fh_hierarchical_model(frame, spec)

        result = prior_predictive_summary(
            model,
            frame,
            meta,
            n_samples=10,
            random_seed=7,
            component_var_names=["intercept", "not_a_real_variable_name"],
        )

        components = result["plausibility"]["component_decomposition"]["components"]
        assert "intercept" in components
        assert "not_a_real_variable_name" not in components

    def test_deterministic_wrapping_does_not_change_y_obs_evidence(self):
        """Wrapping eta_trend/eta_season/eta_market/eta_promo/eta_controls
        in pm.Deterministic is a pure read-only exposure - it must not
        change the model's actual computed eta/mu/y_obs values at all.
        Same seed, same model construction, with vs. without requesting the
        extra component names: the y_obs rows must be identical."""
        frame = _small_frame()
        spec = _spec()

        model_a, meta_a = build_fh_hierarchical_model(frame, spec)
        without_components = prior_predictive_summary(
            model_a, frame, meta_a, n_samples=15, random_seed=5
        )

        model_b, meta_b = build_fh_hierarchical_model(frame, spec)
        with_components = prior_predictive_summary(
            model_b,
            frame,
            meta_b,
            n_samples=15,
            random_seed=5,
            component_var_names=self.COMPONENT_NAMES,
        )

        assert without_components["rows"] == with_components["rows"]

    def test_market_c_builder_silently_skips_model_a_only_component_names(self):
        frame = _small_frame()
        spec = _spec()
        model, meta = build_fh_market_specific_model(frame, spec)

        result = prior_predictive_summary(
            model,
            frame,
            meta,
            n_samples=10,
            random_seed=7,
            component_var_names=self.COMPONENT_NAMES,
        )

        # Whatever subset Model C actually declares (if any) is summarised
        # without error; none of this asserts Model C exposes the same
        # decomposition as Model A.
        assert result["plausibility"]["component_decomposition"]["status"] in {
            "available",
            "unavailable",
        }


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


class TestPriorPredictiveUpgradesPreV4Artefacts:
    """Codex review (P1, PR #147): dataclasses.replace alone preserves a
    pre-existing artefact's schema_version, so adding a real
    prior_predictive section to a v2/v3-origin artefact without also
    upgrading schema_version left an internally inconsistent object -
    to_dict()/from_dict() would then discard that evidence on the next
    round trip, since from_dict treats prior_predictive as unavailable for
    schema_version < 4. Both run_prior_predictive_check (computed/failed)
    and record_prior_predictive_failure (the page's own rebuild-failure
    path) must upgrade schema_version/diagnostics_version at the same time
    as replacing the section, and the evidence must survive a real
    to_dict/from_dict round trip afterwards."""

    def test_computed_result_upgrades_a_v3_origin_artefact_and_survives_round_trip(
        self,
    ):
        frame = _small_frame()
        spec = _spec()
        model, meta = build_fh_hierarchical_model(frame, spec)
        v3_artefact = DiagnosticsArtefact(schema_version=3, diagnostics_version="3.1.0")

        updated = DiagnosticsService().run_prior_predictive_check(
            v3_artefact,
            model=model,
            frame=frame,
            meta=meta,
            model_type="shared",
            n_samples=5,
            random_seed=1,
        )

        assert updated.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert updated.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION
        assert updated.prior_predictive.status == "computed"

        restored = DiagnosticsArtefact.from_dict(updated.to_dict())
        assert restored.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert restored.prior_predictive.status == "computed"
        assert restored.prior_predictive.payload == updated.prior_predictive.payload
        assert restored.fingerprint() == updated.fingerprint()

    def test_failed_result_also_upgrades_a_v2_origin_artefact_and_survives_round_trip(
        self,
    ):
        v2_artefact = DiagnosticsArtefact(schema_version=2, diagnostics_version="2.0.0")

        updated = DiagnosticsService().run_prior_predictive_check(
            v2_artefact,
            model=None,  # forces the failure path
            frame={"markets": [], "market_bounds": []},
            meta=None,
            model_type="shared",
        )

        assert updated.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert updated.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION
        assert updated.prior_predictive.status == "failed"

        restored = DiagnosticsArtefact.from_dict(updated.to_dict())
        assert restored.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert restored.prior_predictive.status == "failed"
        assert restored.prior_predictive.error == updated.prior_predictive.error

    def test_record_prior_predictive_failure_upgrades_a_v3_origin_artefact(self):
        v3_artefact = DiagnosticsArtefact(schema_version=3, diagnostics_version="3.1.0")

        updated = DiagnosticsService().record_prior_predictive_failure(
            v3_artefact, "could not rebuild the model"
        )

        assert updated.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert updated.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION
        assert updated.prior_predictive.status == "failed"
        assert updated.prior_predictive.error == "could not rebuild the model"

        restored = DiagnosticsArtefact.from_dict(updated.to_dict())
        assert restored.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert restored.prior_predictive.status == "failed"

    def test_an_already_current_schema_artefact_is_not_downgraded_or_altered(self):
        current_artefact = DiagnosticsArtefact()
        assert current_artefact.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION

        updated = DiagnosticsService().record_prior_predictive_failure(
            current_artefact, "x"
        )

        assert updated.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert updated.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION
