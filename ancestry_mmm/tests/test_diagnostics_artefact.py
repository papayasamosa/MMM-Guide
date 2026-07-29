"""Tests for the canonical diagnostics evidence artefact (PR 72B).

Covers:
- DiagnosticSection states and validation
- DiagnosticsArtefact schema v2 round-trip and fingerprint
- Schema v1 → v2 compatibility
- DiagnosticsService evaluate with artefact sections
- ValidationService artefact consumption
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import arviz as az

from ancestry_mmm.application.diagnostics_service import (
    DiagnosticSection,
    DiagnosticsArtefact,
    DiagnosticsInput,
    DiagnosticsService,
)
from ancestry_mmm.application.validation_service import (
    MalformedArtefactEvidenceError,
    ValidationInput,
    ValidationService,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.validation_policy import ThresholdPolicy, ValidationGate
from ancestry_mmm.core.diagnostics import (
    curve_plausibility_checks as _real_curve_plausibility_checks,
    posterior_predictive_coverage as _real_posterior_predictive_coverage,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.pathways import resolve_pathway_masks


def _minimal_trace_frame_meta():
    """A minimal, single-outcome, single-channel real trace/frame/meta
    triple - enough to exercise DiagnosticsService.evaluate() end to end
    without mocking arviz/numpy internals."""
    rng = np.random.default_rng(11)
    n_obs, n_chain, n_draw = 16, 2, 20
    oids = ["fh_new_gsa"]
    chs = ["TV"]

    Y = rng.uniform(5, 30, size=(n_obs, 1))
    trace = az.from_dict(
        posterior={
            "mu": np.maximum(
                Y[None, None, :, 0] + rng.normal(0, 0.5, size=(n_chain, n_draw, n_obs)),
                0.1,
            )[..., None],
            "alpha": np.full((n_chain, n_draw, 1), 8.0),
            "decay_rate": np.full((n_chain, n_draw, 1), 0.5),
            "hill_K": np.ones((n_chain, n_draw, 1)),
            "hill_S": np.full((n_chain, n_draw, 1), 4.0),
            "beta": np.ones((n_chain, n_draw, 1, 1)),
            "intercept": np.zeros((n_chain, n_draw, 1)),
            "trend_coef": np.zeros((n_chain, n_draw, 1)),
            "promo_coef": np.zeros((n_chain, n_draw, 1)),
            "market_offset": np.zeros((n_chain, n_draw, 1, 1)),
            "gamma_fourier": np.zeros((n_chain, n_draw, 4, 1)),
        },
        coords={
            "obs": list(range(n_obs)),
            "outcome": oids,
            "channel": chs,
            "market": ["UK"],
            "fourier": list(range(4)),
        },
        dims={
            "mu": ["obs", "outcome"],
            "alpha": ["outcome"],
            "decay_rate": ["channel"],
            "hill_K": ["channel"],
            "hill_S": ["channel"],
            "beta": ["outcome", "channel"],
            "intercept": ["outcome"],
            "trend_coef": ["outcome"],
            "promo_coef": ["outcome"],
            "market_offset": ["market", "outcome"],
            "gamma_fourier": ["fourier", "outcome"],
        },
        sample_stats={"diverging": np.zeros((n_chain, n_draw), dtype=bool)},
    )

    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=oids,
        channels=chs,
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id=oids[0],
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
        pathway_masks=resolve_pathway_masks(
            oids,
            chs,
            [],
            dna_channel_idx=[],
            dna_outcome_id=oids[0],
            direct_dna_outcome_ids=[],
            dna_lag_weeks=1,
        ),
    )

    frame = {
        "Y": Y,
        "X_media": rng.uniform(0, 100, size=(n_obs, 1)),
        "market_bounds": [(0, n_obs)],
        "market_idx": np.zeros(n_obs, dtype=int),
        "promo": np.zeros((n_obs, 1)),
        "trend": np.arange(n_obs, dtype=float),
        "fourier": np.zeros((n_obs, 4)),
    }
    return trace, frame, meta


# =========================================================================
# DiagnosticSection
# =========================================================================


class TestDiagnosticSection:
    def test_computed_requires_payload(self):
        DiagnosticSection(status="computed", payload={"key": 1.0})  # ok

    def test_computed_without_payload_raises(self):
        with pytest.raises(ValueError, match="must have a non-None payload"):
            DiagnosticSection(status="computed", payload=None)

    def test_failed_requires_error(self):
        DiagnosticSection(status="failed", payload=None, error="something broke")

    def test_failed_without_error_raises(self):
        with pytest.raises(ValueError, match="must have a non-blank error"):
            DiagnosticSection(status="failed", payload=None, error="")

    def test_not_computed_no_payload(self):
        sec = DiagnosticSection(status="not_computed", payload=None)
        assert sec.status == "not_computed"

    def test_not_applicable_no_payload(self):
        sec = DiagnosticSection(
            status="not_applicable", payload=None, error="Only for market-specific"
        )
        assert sec.status == "not_applicable"

    def test_to_dict_round_trip(self):
        sec = DiagnosticSection(
            status="computed",
            payload={"value": 42.0, "label": "test"},
            warnings=("warn1",),
        )
        d = sec.to_dict()
        restored = DiagnosticSection.from_dict(d)
        assert restored.status == sec.status
        assert restored.payload == sec.payload
        assert restored.warnings == sec.warnings

    def test_fingerprint_changes_with_payload(self):
        sec1 = DiagnosticSection(status="computed", payload={"v": 1.0})
        sec2 = DiagnosticSection(status="computed", payload={"v": 2.0})
        assert sec1.fingerprint_payload() != sec2.fingerprint_payload()

    def test_fingerprint_changes_with_warnings(self):
        sec1 = DiagnosticSection(status="computed", payload={"v": 1.0}, warnings=())
        sec2 = DiagnosticSection(
            status="computed", payload={"v": 1.0}, warnings=("warn",)
        )
        assert sec1.fingerprint_payload() != sec2.fingerprint_payload()

    def test_fingerprint_changes_with_status(self):
        sec1 = DiagnosticSection(status="computed", payload={"v": 1.0})
        sec2 = DiagnosticSection(status="failed", payload=None, error="err")
        assert sec1.fingerprint_payload() != sec2.fingerprint_payload()


# =========================================================================
# DiagnosticsArtefact schema v2
# =========================================================================


class TestDiagnosticsArtefactV2:
    def test_default_artefact(self):
        artefact = DiagnosticsArtefact()
        assert artefact.schema_version == 2
        assert artefact.diagnostics_version == "2.0.0"
        assert artefact.convergence.status == "not_computed"
        assert artefact.legacy_incomplete is False

    def test_to_dict_has_all_sections(self):
        artefact = DiagnosticsArtefact(artefact_id="test-id")
        d = artefact.to_dict()
        assert d["schema_version"] == 2
        assert d["artefact_id"] == "test-id"
        for section in (
            "convergence",
            "in_sample_fit",
            "posterior_predictive",
            "plausibility",
            "identification",
            "coefficient_stability",
            "backtest",
        ):
            assert section in d
            assert "status" in d[section]

    def test_round_trip_preserves_all_fields(self):
        convergence = DiagnosticSection(
            status="computed",
            payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
        )
        original = DiagnosticsArtefact(
            artefact_id=uuid.uuid4().hex,
            diagnostics_version="2.0.0",
            schema_version=2,
            model_identity_fingerprint="fp123",
            evaluated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
            model_type="shared",
            convergence=convergence,
            posterior_predictive=DiagnosticSection(
                status="computed",
                payload=[{"coverage_pct": 95.0}],
            ),
            global_warnings=("warn1",),
            global_errors=("err1",),
            settings=(("credible_mass", "0.9"),),
        )
        d = original.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.artefact_id == original.artefact_id
        assert restored.schema_version == original.schema_version
        assert (
            restored.model_identity_fingerprint == original.model_identity_fingerprint
        )
        assert restored.convergence.status == "computed"
        assert restored.convergence.payload["max_rhat"] == 1.02
        assert restored.posterior_predictive.payload[0]["coverage_pct"] == 95.0
        assert restored.global_warnings == ("warn1",)
        assert restored.global_errors == ("err1",)
        assert restored.legacy_incomplete is False

    def test_deterministic_fingerprint(self):
        ts = datetime(2026, 7, 29, tzinfo=timezone.utc)
        a1 = DiagnosticsArtefact(
            artefact_id="same",
            evaluated_at=ts,
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02},
            ),
        )
        a2 = DiagnosticsArtefact(
            artefact_id="same",
            evaluated_at=ts,
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02},
            ),
        )
        assert a1.fingerprint() == a2.fingerprint()

    def test_fingerprint_changes_on_payload_change(self):
        a1 = DiagnosticsArtefact(
            artefact_id="id1",
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02},
            ),
        )
        a2 = DiagnosticsArtefact(
            artefact_id="id1",
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.05},
            ),
        )
        assert a1.fingerprint() != a2.fingerprint()

    def test_fingerprint_changes_on_section_status(self):
        a1 = DiagnosticsArtefact(
            convergence=DiagnosticSection(status="computed", payload={"v": 1.0}),
        )
        a2 = DiagnosticsArtefact(
            convergence=DiagnosticSection(status="failed", payload=None, error="err"),
        )
        assert a1.fingerprint() != a2.fingerprint()


# =========================================================================
# Schema v1 compatibility
# =========================================================================


class TestSchemaV1Compatibility:
    def test_v1_loads_as_legacy_incomplete(self):
        v1_dict = {
            "artefact_id": "v1-artefact",
            "diagnostics_version": "1.0.0",
            "schema_version": 1,
            "model_identity_fingerprint": "",
            "evaluated_at": "2026-07-29T00:00:00+00:00",
            "max_rhat": 1.02,
            "min_ess": 400,
            "has_divergences": False,
            "mean_ppc_coverage_pct": 89.0,
            "scorecard_fields": ["r_squared"],
            "plausibility_issues": 0,
            "identification_condition_number": 0.0,
            "backtest_folds": 0,
            "backtest_mean_mape": None,
            "settings": [],
        }
        artefact = DiagnosticsArtefact.from_dict(v1_dict)
        assert artefact.schema_version == 1
        assert artefact.legacy_incomplete is True
        assert artefact.convergence.status == "computed"
        assert artefact.convergence.payload["max_rhat"] == 1.02
        assert artefact.in_sample_fit.status == "not_computed"
        assert artefact.posterior_predictive.payload["mean_ppc_coverage_pct"] == 89.0

    def test_v1_cannot_support_official_approval(self):
        v1_dict = {
            "schema_version": 1,
            "evaluated_at": "2026-07-29T00:00:00+00:00",
        }
        artefact = DiagnosticsArtefact.from_dict(v1_dict)
        assert artefact.legacy_incomplete is True
        # Official validation should reject legacy_incomplete artefacts
        assert artefact.schema_version < 2

    def test_unsupported_schema_raises(self):
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            DiagnosticsArtefact.from_dict({"schema_version": 99})


# =========================================================================
# ValidationService artefact consumption
# =========================================================================


class TestValidationServiceArtefactConsumption:
    def test_get_artefact_metric_convergence_rhat(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
            ),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("convergence_rhat", artefact)
        assert metric == 1.02

    def test_get_artefact_metric_convergence_ess(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
            ),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("convergence_ess", artefact)
        assert metric == 400

    def test_get_artefact_metric_divergences(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": True},
            ),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("divergences", artefact)
        assert metric == 1.0

    def test_get_artefact_metric_ppc_coverage(self):
        artefact = DiagnosticsArtefact(
            posterior_predictive=DiagnosticSection(
                status="computed",
                payload=[{"coverage_pct": 95.0}, {"coverage_pct": 85.0}],
            ),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("ppc_coverage", artefact)
        assert metric == 90.0  # mean of 95 and 85

    def test_get_artefact_metric_unknown_evaluator(self):
        artefact = DiagnosticsArtefact()
        service = ValidationService()
        metric = service._get_artefact_metric("unknown_evaluator", artefact)
        assert metric is None

    def test_get_artefact_metric_not_computed_section(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(status="not_computed"),
        )
        service = ValidationService()
        metric = service._get_artefact_metric("convergence_rhat", artefact)
        assert metric is None

    def test_get_artefact_metric_legacy_v1_returns_none(self):
        v1_dict = {
            "schema_version": 1,
            "evaluated_at": "2026-07-29T00:00:00+00:00",
        }
        artefact = DiagnosticsArtefact.from_dict(v1_dict)
        service = ValidationService()
        metric = service._get_artefact_metric("convergence_rhat", artefact)
        assert metric is None

    def test_validation_input_accepts_artefact(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
            ),
        )
        v_input = ValidationInput(
            diagnostics_artefact=artefact,
        )
        assert v_input.diagnostics_artefact is artefact

    # -- PR 79A (WP2): evaluator-ID aliases resolve to the same metric ----

    @pytest.mark.parametrize(
        "alias,expected",
        [("rhat", 1.02), ("convergence_rhat", 1.02)],
    )
    def test_rhat_aliases_resolve_identically(self, alias, expected):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
            ),
        )
        service = ValidationService()
        assert service._get_artefact_metric(alias, artefact) == expected

    @pytest.mark.parametrize(
        "alias,expected",
        [("ess", 400), ("min_ess", 400), ("convergence_ess", 400)],
    )
    def test_ess_aliases_resolve_identically(self, alias, expected):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
            ),
        )
        service = ValidationService()
        assert service._get_artefact_metric(alias, artefact) == expected

    @pytest.mark.parametrize("alias", ["ppc", "ppc_coverage"])
    def test_ppc_aliases_resolve_identically(self, alias):
        artefact = DiagnosticsArtefact(
            posterior_predictive=DiagnosticSection(
                status="computed",
                payload=[{"coverage_pct": 90.0}, {"coverage_pct": 80.0}],
            ),
        )
        service = ValidationService()
        assert service._get_artefact_metric(alias, artefact) == 85.0

    # -- PR 79A (WP4): malformed 'computed' evidence fails closed, never 0.0 --

    def test_computed_convergence_missing_max_rhat_raises(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"min_ess": 400, "has_divergences": False},
            ),
        )
        service = ValidationService()
        with pytest.raises(MalformedArtefactEvidenceError, match="max_rhat"):
            service._get_artefact_metric("convergence_rhat", artefact)

    def test_computed_convergence_non_finite_rhat_raises(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={
                    "max_rhat": float("nan"),
                    "min_ess": 400,
                    "has_divergences": False,
                },
            ),
        )
        service = ValidationService()
        with pytest.raises(MalformedArtefactEvidenceError, match="non-finite"):
            service._get_artefact_metric("convergence_rhat", artefact)

    def test_computed_ppc_missing_coverage_pct_raises(self):
        artefact = DiagnosticsArtefact(
            posterior_predictive=DiagnosticSection(
                status="computed",
                payload=[{"outcome_id": "fh_new_gsa"}],
            ),
        )
        service = ValidationService()
        with pytest.raises(MalformedArtefactEvidenceError, match="coverage_pct"):
            service._get_artefact_metric("ppc_coverage", artefact)

    def test_malformed_evidence_fails_the_gate_without_recomputing(self):
        """A gate backed by malformed 'computed' evidence must fail closed
        via _evaluate_gate, not silently fall through to a live
        recomputation (which could paper over the corruption)."""
        artefact = DiagnosticsArtefact(
            artefact_id="artefact-1",
            schema_version=2,
            model_identity_fingerprint="",
            legacy_incomplete=False,
            convergence=DiagnosticSection(
                status="computed",
                payload={"min_ess": 400, "has_divergences": False},  # missing max_rhat
            ),
        )
        policy = ThresholdPolicy(
            policy_id="p1",
            version="1.0",
            scope="all_models",
            owner="Test",
            gates=[
                ValidationGate(
                    name="convergence_rhat",
                    description="R-hat",
                    evaluator_id="convergence_rhat",
                    acceptable_range=(0.0, 1.01),
                )
            ],
        )
        service = ValidationService()
        v_input = ValidationInput(
            trace=None,
            policy=policy,
            diagnostics_artefact=artefact,
        )
        result = service.evaluate_readiness(v_input)
        assert len(result.results) == 1
        assert result.results[0].status == "fail"
        assert "Malformed" in result.results[0].message

    # -- PR 79A (WP3): artefact path uses canonical classification ---------

    def test_artefact_value_in_review_band_is_review_not_pass_or_fail(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.03, "min_ess": 400, "has_divergences": False},
            ),
        )
        gate = ValidationGate(
            name="convergence_rhat",
            description="R-hat",
            evaluator_id="convergence_rhat",
            acceptable_range=(0.0, 1.01),
            review_range=(0.0, 1.05),
            direction="lower_is_better",
        )
        policy = ThresholdPolicy(
            policy_id="p1",
            version="1.0",
            scope="all_models",
            owner="Test",
            gates=[gate],
        )
        service = ValidationService()
        result = service.evaluate_readiness(
            ValidationInput(policy=policy, diagnostics_artefact=artefact)
        )
        assert result.results[0].status == "review"

    def test_artefact_boolean_gate_uses_expected_state_not_range(self):
        artefact = DiagnosticsArtefact(
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.0, "min_ess": 400, "has_divergences": True},
            ),
        )
        gate = ValidationGate(
            name="divergences",
            description="Divergences",
            evaluator_id="divergences",
            expected_state=True,  # this policy expects divergences to be present
        )
        policy = ThresholdPolicy(
            policy_id="p1",
            version="1.0",
            scope="all_models",
            owner="Test",
            gates=[gate],
        )
        service = ValidationService()
        result = service.evaluate_readiness(
            ValidationInput(policy=policy, diagnostics_artefact=artefact)
        )
        # has_divergences=True matches expected_state=True -> pass, even
        # though a naive lo<=value<=hi range check has no range to apply.
        assert result.results[0].status == "pass"

    # -- PR 79A (WP6): complete artefact-only validation needs no trace ----

    def test_complete_artefact_validates_without_a_trace(self):
        identity = ModelIdentity("run-1", "data-1", "spec-1", "post-1")
        artefact = DiagnosticsArtefact(
            artefact_id="a1",
            schema_version=2,
            model_identity_fingerprint=identity.fingerprint(),
            legacy_incomplete=False,
            convergence=DiagnosticSection(
                status="computed",
                payload={"max_rhat": 1.0, "min_ess": 400, "has_divergences": False},
            ),
            posterior_predictive=DiagnosticSection(
                status="computed",
                payload=[{"coverage_pct": 91.0}],
            ),
        )
        policy = ThresholdPolicy(
            policy_id="p1",
            version="1.0",
            scope="all_models",
            owner="Test",
            gates=[
                ValidationGate(
                    name="convergence_rhat",
                    description="R-hat",
                    evaluator_id="convergence_rhat",
                    acceptable_range=(0.0, 1.01),
                ),
                ValidationGate(
                    name="ppc_coverage",
                    description="PPC",
                    evaluator_id="ppc_coverage",
                    acceptable_range=(85.0, 100.0),
                ),
            ],
        )
        service = ValidationService()
        v_input = ValidationInput(
            trace=None,
            policy=policy,
            model_identity=identity,
            diagnostics_artefact=artefact,
            model_type="shared",
        )
        result = service.evaluate_readiness(v_input)
        assert not result.errors, result.errors
        assert [r.status for r in result.results] == ["pass", "pass"]
        assert result.readiness is not None
        assert result.readiness.overall_ready is True


# =========================================================================
# DiagnosticsService computes each diagnostic exactly once (PR 79A, WP C)
# =========================================================================


class TestDiagnosticsServiceComputesEachSectionOnce:
    """Before this fix, DiagnosticsService.evaluate() called
    compute_scorecard() (which internally recomputes convergence, PPC and
    plausibility) for the in_sample_fit section, *and* separately called
    posterior_predictive_coverage()/curve_plausibility_checks() again for
    their own sections - so PPC and plausibility were each computed twice,
    and the in_sample_fit section's payload was the whole nested scorecard
    dict rather than fit-only rows."""

    def test_ppc_and_plausibility_each_computed_exactly_once(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)

        with (
            patch(
                "ancestry_mmm.application.diagnostics_service.posterior_predictive_coverage",
                wraps=_real_posterior_predictive_coverage,
            ) as mock_ppc,
            patch(
                "ancestry_mmm.application.diagnostics_service.curve_plausibility_checks",
                wraps=_real_curve_plausibility_checks,
            ) as mock_plaus,
        ):
            result = DiagnosticsService().evaluate(diag_input)

        assert mock_ppc.call_count == 1
        assert mock_plaus.call_count == 1
        assert not result.errors, result.errors

    def test_in_sample_fit_section_contains_only_fit_rows(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        result = DiagnosticsService().evaluate(diag_input)

        fit_section = result.diagnostics_artefact.in_sample_fit
        assert fit_section.status == "computed"
        # A fit row has exactly the in_sample_fit() columns - no nested
        # "convergence"/"ppc_coverage"/"plausibility_flags" keys leaking in
        # from a bundled compute_scorecard() payload.
        assert set(fit_section.payload[0].keys()) == {
            "outcome_id",
            "r_squared",
            "mape_pct",
            "actual_mean",
            "predicted_mean",
        }

    def test_displayed_scorecard_matches_artefact_exactly(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        result = DiagnosticsService().evaluate(diag_input)

        artefact = result.diagnostics_artefact
        assert result.scorecard["convergence"] == artefact.convergence.payload
        assert result.scorecard["in_sample_fit"] == artefact.in_sample_fit.payload
        assert result.scorecard["ppc_coverage"] == artefact.posterior_predictive.payload
        assert result.scorecard["plausibility_flags"] == artefact.plausibility.payload


# =========================================================================
# Backtest ModelSpec contract (PR 80A)
# =========================================================================


class TestBacktestRequiresRealModelSpec:
    """Before this fix, the backtest section passed ``diag_input.meta``
    (an FHModelMeta, which has no ``date_col``) to
    ``expanding_window_backtest`` as its ``spec`` argument. That call always
    raised AttributeError, silently swallowed into a generic "failed"
    section - so the backtest feature never worked and never told anyone
    why. DiagnosticsInput now has an explicit ``raw_model_spec: ModelSpec``
    field that must be supplied for a backtest to run at all."""

    @staticmethod
    def _bt_dataframe():
        dates = pd.date_range("2024-01-01", periods=20, freq="W")
        return pd.DataFrame(
            {
                "date": dates,
                "market": ["UK"] * len(dates),
                "spend": np.arange(len(dates), dtype=float),
                "gsa": np.arange(len(dates), dtype=float) + 10.0,
            }
        )

    @staticmethod
    def _fit_fold_fn(train_df, test_df):
        return {"fh_new_gsa": 0.8}, {"fh_new_gsa": 12.5}

    def test_backtest_without_raw_model_spec_fails_closed_with_clear_error(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(
            trace=trace,
            frame=frame,
            meta=meta,
            backtest_folds=1,
            fit_fold_fn=self._fit_fold_fn,
            raw_model_dataframe=self._bt_dataframe(),
        )
        result = DiagnosticsService().evaluate(diag_input)

        bt_sec = result.diagnostics_artefact.backtest
        assert bt_sec.status == "failed"
        assert "raw_model_spec is required" in bt_sec.error

    def test_backtest_with_raw_model_spec_computes(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        spec = ModelSpec(date_col="date", market_col="market")
        diag_input = DiagnosticsInput(
            trace=trace,
            frame=frame,
            meta=meta,
            backtest_folds=1,
            fit_fold_fn=self._fit_fold_fn,
            raw_model_dataframe=self._bt_dataframe(),
            raw_model_spec=spec,
        )
        result = DiagnosticsService().evaluate(diag_input)

        bt_sec = result.diagnostics_artefact.backtest
        assert bt_sec.status == "computed", bt_sec.error
        assert bt_sec.payload
        assert bt_sec.payload[0]["outcome_id"] == "fh_new_gsa"
        assert result.backtest_results is not None
        assert not result.backtest_results.empty
