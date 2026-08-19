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
    CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
    CURRENT_DIAGNOSTICS_VERSION,
    DiagnosticSection,
    DiagnosticsArtefact,
    DiagnosticsInput,
    DiagnosticsResult,
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
from ancestry_mmm.core.identification_diagnostics import (
    channel_spend_correlation_matrix as _real_channel_spend_correlation_matrix,
    design_matrix_condition_number as _real_design_matrix_condition_number,
    identification_report as _real_identification_report,
    posterior_coefficient_stability as _real_posterior_coefficient_stability,
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
        "markets": ["UK"],
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


class TestDiagnosticsArtefactV3:
    def test_default_artefact(self):
        artefact = DiagnosticsArtefact()
        assert artefact.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert artefact.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION
        assert artefact.convergence.status == "not_computed"
        assert artefact.error_metrics.status == "not_computed"
        assert artefact.residual_diagnostics.status == "not_computed"
        assert artefact.legacy_incomplete is False

    def test_to_dict_has_all_sections(self):
        artefact = DiagnosticsArtefact(artefact_id="test-id")
        d = artefact.to_dict()
        assert d["schema_version"] == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert d["artefact_id"] == "test-id"
        for section in (
            "convergence",
            "in_sample_fit",
            "posterior_predictive",
            "plausibility",
            "identification",
            "coefficient_stability",
            "backtest",
            "error_metrics",
            "residual_diagnostics",
            "prior_predictive",
            "predictive_density",
        ):
            assert section in d
            assert "status" in d[section]

    def test_round_trip_preserves_all_fields(self):
        convergence = DiagnosticSection(
            status="computed",
            payload={"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
        )
        error_metrics = DiagnosticSection(
            status="computed",
            payload=[{"outcome_id": "fh_new_gsa", "mae": 1.5, "bias": -0.2}],
        )
        residual_diagnostics = DiagnosticSection(
            status="computed",
            payload=[{"outcome_id": "fh_new_gsa", "lag1_autocorrelation": 0.1}],
        )
        original = DiagnosticsArtefact(
            artefact_id=uuid.uuid4().hex,
            diagnostics_version="3.0.0",
            schema_version=3,
            model_identity_fingerprint="fp123",
            evaluated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
            model_type="shared",
            convergence=convergence,
            posterior_predictive=DiagnosticSection(
                status="computed",
                payload=[{"coverage_pct": 95.0}],
            ),
            error_metrics=error_metrics,
            residual_diagnostics=residual_diagnostics,
            global_warnings=("warn1",),
            global_errors=("err1",),
            settings=(("credible_mass", "0.9"),),
        )
        d = original.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.artefact_id == original.artefact_id
        assert restored.schema_version == original.schema_version
        # Work Package 1: an explicit historical "3.0.0" (pre-WP2 residual-
        # diagnostics fix) must round-trip exactly as persisted, never
        # silently upgraded to the current-code default.
        assert restored.diagnostics_version == "3.0.0"
        assert (
            restored.model_identity_fingerprint == original.model_identity_fingerprint
        )
        assert restored.convergence.status == "computed"
        assert restored.convergence.payload["max_rhat"] == 1.02
        assert restored.posterior_predictive.payload[0]["coverage_pct"] == 95.0
        assert restored.error_metrics.payload[0]["mae"] == 1.5
        assert restored.residual_diagnostics.payload[0]["lag1_autocorrelation"] == 0.1
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
# Diagnostics version authority (Work Package 1)
# =========================================================================


class TestDiagnosticsVersionAuthority:
    """Every current-code diagnostics_version default/emission must trace
    back to the single CURRENT_DIAGNOSTICS_VERSION/CURRENT_DIAGNOSTICS_
    SCHEMA_VERSION source of truth - a direct construction, the no-trace/
    error evaluate() path, and a successful evaluate() call must never be
    able to silently disagree with each other."""

    def test_current_version_constants_are_consistent(self):
        assert CURRENT_DIAGNOSTICS_VERSION == "8.0.0"
        assert CURRENT_DIAGNOSTICS_SCHEMA_VERSION == 8

    def test_default_diagnostics_result_uses_current_version(self):
        result = DiagnosticsResult(
            scorecard={},
            max_rhat=float("nan"),
            min_ess=float("nan"),
            has_divergences=False,
            mean_ppc_coverage_pct=float("nan"),
        )
        assert result.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION

    def test_no_trace_error_result_does_not_emit_an_obsolete_version(self):
        """DiagnosticsService.evaluate()'s no-trace early return builds a
        DiagnosticsResult without an explicit diagnostics_version - before
        this fix that silently fell back to the dataclass default "2.0.0",
        an obsolete version distinct from a successful evaluation's
        "3.1.0". It must report the current version, not a stale one."""
        diag_input = DiagnosticsInput(
            trace=None,
            frame={},
            meta=FHModelMeta(
                markets=["UK"],
                outcome_ids=["fh_new_gsa"],
                channels=["TV"],
                dna_channels=[],
                dna_channel_idx=[],
                non_dna_idx=[0],
                dna_outcome_id="fh_new_gsa",
                dna_lag_weeks=1,
                unpooled_markets=[],
                control_names=[],
            ),
        )
        result = DiagnosticsService().evaluate(diag_input)
        assert result.errors, "no-trace input should report an error"
        assert result.diagnostics_artefact is None
        assert result.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION
        assert result.diagnostics_version != "2.0.0"

    def test_successful_evaluate_uses_current_version_on_both_result_and_artefact(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        result = DiagnosticsService().evaluate(diag_input)
        assert result.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION
        assert (
            result.diagnostics_artefact.diagnostics_version
            == CURRENT_DIAGNOSTICS_VERSION
        )
        assert (
            result.diagnostics_artefact.schema_version
            == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        )

    def test_historical_v1_version_is_not_upgraded_to_current(self):
        artefact = DiagnosticsArtefact.from_dict(
            {"evaluated_at": "2026-07-29T00:00:00+00:00"}
        )
        assert artefact.diagnostics_version == "1.0.0"
        assert artefact.diagnostics_version != CURRENT_DIAGNOSTICS_VERSION

    def test_historical_v2_version_is_not_upgraded_to_current(self):
        artefact = DiagnosticsArtefact.from_dict(TestSchemaV2Compatibility()._v2_dict())
        assert artefact.diagnostics_version == "2.0.0"
        assert artefact.diagnostics_version != CURRENT_DIAGNOSTICS_VERSION


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

    @pytest.mark.parametrize(
        "raw_schema_version",
        [
            True,  # bool is an int subclass - True == 1 must not silently
            # resolve to schema v1 (legacy_incomplete)
            False,
            2.0,  # float equal to a supported version - 2.0 == 2/in (2, 3)
            # must not silently resolve to schema v2
            3.0,
            "2",  # numeric string
            0,
            -1,
        ],
    )
    def test_non_integer_or_out_of_range_schema_version_is_rejected(
        self, raw_schema_version
    ):
        """Work Package 2 corrective fix: plain `==`/`in` dispatch let a
        bool or a numerically-equal float silently masquerade as an actual
        integer schema version (`True == 1`, `2.0 in (2, 3)`). Each of
        these must fail closed instead."""
        with pytest.raises(ValueError):
            DiagnosticsArtefact.from_dict({"schema_version": raw_schema_version})

    def test_absent_schema_version_key_still_uses_documented_legacy_default(self):
        """A genuinely missing schema_version key (an artefact predating
        schema versioning entirely) still resolves to the documented v1
        legacy default - only a *present* schema_version is validated
        strictly."""
        artefact = DiagnosticsArtefact.from_dict(
            {"evaluated_at": "2026-07-29T00:00:00+00:00"}
        )
        assert artefact.schema_version == 1
        assert artefact.legacy_incomplete is True


# =========================================================================
# Schema v2 -> v3 compatibility (REQ-VAL-001 UK-pilot evidence expansion)
# =========================================================================


class TestSchemaV2Compatibility:
    def _v2_dict(self) -> dict:
        not_computed = {
            "status": "not_computed",
            "payload": None,
            "error": "",
            "warnings": [],
        }
        return {
            "artefact_id": "v2-artefact",
            "diagnostics_version": "2.0.0",
            "schema_version": 2,
            "model_identity_fingerprint": "fp-v2",
            "evaluated_at": "2026-07-29T00:00:00+00:00",
            "model_type": "shared",
            "convergence": {
                "status": "computed",
                "payload": {"max_rhat": 1.02, "min_ess": 400, "has_divergences": False},
                "error": "",
                "warnings": [],
            },
            "in_sample_fit": not_computed,
            "posterior_predictive": not_computed,
            "plausibility": not_computed,
            "identification": not_computed,
            "coefficient_stability": not_computed,
            "backtest": not_computed,
            "settings": [],
            "legacy_incomplete": False,
        }

    def test_v2_upgrades_with_new_sections_not_computed(self):
        artefact = DiagnosticsArtefact.from_dict(self._v2_dict())
        assert artefact.error_metrics.status == "not_computed"
        assert artefact.residual_diagnostics.status == "not_computed"
        assert artefact.error_metrics.error != ""
        assert artefact.residual_diagnostics.error != ""

    def test_v2_upgrade_preserves_schema_version_and_is_not_legacy_incomplete(self):
        """A schema-v2 artefact predating error_metrics/residual_diagnostics
        is not the same thing as a v1 artefact that silently dropped
        evidence it claimed to have - it must not be marked
        legacy_incomplete, and its stored schema_version is preserved as
        the truthful record of what evidence it actually has (mirrors how
        _from_v1 preserves schema_version=1, never bumping it)."""
        artefact = DiagnosticsArtefact.from_dict(self._v2_dict())
        assert artefact.schema_version == 2
        assert artefact.legacy_incomplete is False

    def test_v2_upgrade_preserves_existing_sections(self):
        artefact = DiagnosticsArtefact.from_dict(self._v2_dict())
        assert artefact.convergence.status == "computed"
        assert artefact.convergence.payload["max_rhat"] == 1.02

    def test_v2_upgraded_artefact_still_usable_for_official_canonical_evidence(self):
        """The >= 2 gate in ValidationService (not == 2) is what makes this
        forward-compatible - a v2-origin artefact must not be treated as
        untrustworthy just because it predates this additive category."""
        artefact = DiagnosticsArtefact.from_dict(self._v2_dict())
        assert artefact.schema_version >= 2
        assert not artefact.legacy_incomplete

    def test_v2_round_trip_through_to_dict_is_stable(self):
        artefact = DiagnosticsArtefact.from_dict(self._v2_dict())
        d = artefact.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.schema_version == artefact.schema_version
        assert restored.error_metrics.status == "not_computed"
        assert restored.fingerprint() == artefact.fingerprint()


# =========================================================================
# Schema v3 -> v4 compatibility (REQ-VAL-001 Work Package 2: prior
# predictive evidence)
# =========================================================================


class TestSchemaV3ToV4Compatibility:
    def _v3_dict(self) -> dict:
        not_computed = {
            "status": "not_computed",
            "payload": None,
            "error": "",
            "warnings": [],
        }
        computed_error_metrics = {
            "status": "computed",
            "payload": [{"outcome_id": "fh_new", "mae": 1.2}],
            "error": "",
            "warnings": [],
        }
        return {
            "artefact_id": "v3-artefact",
            "diagnostics_version": "3.1.0",
            "schema_version": 3,
            "model_identity_fingerprint": "fp-v3",
            "evaluated_at": "2026-08-01T00:00:00+00:00",
            "model_type": "shared",
            "convergence": {
                "status": "computed",
                "payload": {"max_rhat": 1.01, "min_ess": 600, "has_divergences": False},
                "error": "",
                "warnings": [],
            },
            "in_sample_fit": not_computed,
            "posterior_predictive": not_computed,
            "plausibility": not_computed,
            "identification": not_computed,
            "coefficient_stability": not_computed,
            "backtest": not_computed,
            "error_metrics": computed_error_metrics,
            "residual_diagnostics": not_computed,
            "settings": [],
            "legacy_incomplete": False,
        }

    def test_v3_upgrades_with_prior_predictive_not_computed(self):
        artefact = DiagnosticsArtefact.from_dict(self._v3_dict())
        assert artefact.prior_predictive.status == "not_computed"
        assert artefact.prior_predictive.error != ""
        assert "schema v4" in artefact.prior_predictive.error

    def test_v3_upgrade_preserves_schema_version_and_is_not_legacy_incomplete(self):
        """Mirrors the v2 -> v3 precedent directly above: a schema-v3
        artefact predating prior_predictive evidence is not the same thing
        as a v1 artefact that silently dropped evidence it claimed to have
        - its stored schema_version is preserved as the truthful record of
        what evidence it actually has."""
        artefact = DiagnosticsArtefact.from_dict(self._v3_dict())
        assert artefact.schema_version == 3
        assert artefact.legacy_incomplete is False

    def test_v3_upgrade_preserves_existing_sections(self):
        artefact = DiagnosticsArtefact.from_dict(self._v3_dict())
        assert artefact.convergence.status == "computed"
        assert artefact.convergence.payload["max_rhat"] == 1.01
        assert artefact.error_metrics.status == "computed"
        assert artefact.error_metrics.payload == [{"outcome_id": "fh_new", "mae": 1.2}]

    def test_v3_upgraded_artefact_still_usable_for_official_canonical_evidence(self):
        """The >= 2 gate in ValidationService (not == schema_version) is
        what makes this forward-compatible - a v3-origin artefact must not
        be treated as untrustworthy just because it predates prior
        predictive evidence."""
        artefact = DiagnosticsArtefact.from_dict(self._v3_dict())
        assert artefact.schema_version >= 2
        assert not artefact.legacy_incomplete

    def test_v3_round_trip_through_to_dict_is_stable(self):
        artefact = DiagnosticsArtefact.from_dict(self._v3_dict())
        d = artefact.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.schema_version == artefact.schema_version
        assert restored.prior_predictive.status == "not_computed"
        assert restored.fingerprint() == artefact.fingerprint()

    def test_historical_v3_version_is_not_upgraded_to_current(self):
        artefact = DiagnosticsArtefact.from_dict(self._v3_dict())
        assert artefact.diagnostics_version == "3.1.0"
        assert artefact.diagnostics_version != CURRENT_DIAGNOSTICS_VERSION


# =========================================================================
# Schema v4 -> v5 compatibility (REQ-VAL-001 Work Package 3: predictive-
# density evidence)
# =========================================================================


class TestSchemaV4ToV5Compatibility:
    def _v4_dict(self) -> dict:
        not_computed = {
            "status": "not_computed",
            "payload": None,
            "error": "",
            "warnings": [],
        }
        computed_prior_predictive = {
            "status": "computed",
            "payload": {"model_type": "shared", "n_samples": 100, "rows": []},
            "error": "",
            "warnings": [],
        }
        return {
            "artefact_id": "v4-artefact",
            "diagnostics_version": "4.0.0",
            "schema_version": 4,
            "model_identity_fingerprint": "fp-v4",
            "evaluated_at": "2026-08-08T00:00:00+00:00",
            "model_type": "shared",
            "convergence": {
                "status": "computed",
                "payload": {"max_rhat": 1.01, "min_ess": 600, "has_divergences": False},
                "error": "",
                "warnings": [],
            },
            "in_sample_fit": not_computed,
            "posterior_predictive": not_computed,
            "plausibility": not_computed,
            "identification": not_computed,
            "coefficient_stability": not_computed,
            "backtest": not_computed,
            "error_metrics": not_computed,
            "residual_diagnostics": not_computed,
            "prior_predictive": computed_prior_predictive,
            "settings": [],
            "legacy_incomplete": False,
        }

    def test_v4_upgrades_with_predictive_density_not_computed(self):
        artefact = DiagnosticsArtefact.from_dict(self._v4_dict())
        assert artefact.predictive_density.status == "not_computed"
        assert artefact.predictive_density.error != ""
        assert "schema v5" in artefact.predictive_density.error

    def test_v4_upgrade_preserves_schema_version_and_is_not_legacy_incomplete(self):
        artefact = DiagnosticsArtefact.from_dict(self._v4_dict())
        assert artefact.schema_version == 4
        assert artefact.legacy_incomplete is False

    def test_v4_upgrade_preserves_existing_sections(self):
        artefact = DiagnosticsArtefact.from_dict(self._v4_dict())
        assert artefact.convergence.payload["max_rhat"] == 1.01
        assert artefact.prior_predictive.status == "computed"
        assert artefact.prior_predictive.payload["n_samples"] == 100

    def test_v4_round_trip_through_to_dict_is_stable(self):
        artefact = DiagnosticsArtefact.from_dict(self._v4_dict())
        d = artefact.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.schema_version == artefact.schema_version
        assert restored.predictive_density.status == "not_computed"
        assert restored.fingerprint() == artefact.fingerprint()

    def test_historical_v4_version_is_not_upgraded_to_current(self):
        artefact = DiagnosticsArtefact.from_dict(self._v4_dict())
        assert artefact.diagnostics_version == "4.0.0"
        assert artefact.diagnostics_version != CURRENT_DIAGNOSTICS_VERSION


# =========================================================================
# Schema v5 - a freshly computed artefact carries prior_predictive and
# predictive_density evidence
# =========================================================================


class TestSchemaV5FreshArtefact:
    def test_current_defaults_are_at_least_schema_v5(self):
        """Schema v5 introduced prior_predictive/predictive_density; a later
        Work Package B bump to v6 (market_channel_capability) does not
        regress those - CURRENT_DIAGNOSTICS_SCHEMA_VERSION only ever moves
        forward from the version this class's name documents."""
        assert CURRENT_DIAGNOSTICS_SCHEMA_VERSION >= 5

    def test_freshly_constructed_artefact_has_not_computed_prior_predictive(self):
        artefact = DiagnosticsArtefact()
        assert artefact.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert artefact.prior_predictive.status == "not_computed"

    def test_freshly_constructed_artefact_has_not_computed_predictive_density(self):
        artefact = DiagnosticsArtefact()
        assert artefact.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert artefact.predictive_density.status == "not_computed"

    def test_computed_prior_predictive_round_trips_through_to_dict(self):
        computed = DiagnosticSection(
            status="computed",
            payload={
                "model_type": "shared",
                "n_samples": 200,
                "random_seed": 42,
                "rows": [
                    {
                        "market": "UK",
                        "outcome_id": "fh_new",
                        "n_observations": 10,
                        "n_draws": 2000,
                        "finite_count": 2000,
                        "non_finite_count": 0,
                        "mean": 5.0,
                        "median": 4.5,
                        "q05": 1.0,
                        "q95": 12.0,
                        "min": 0.0,
                        "max": 30.0,
                    }
                ],
            },
            warnings=("a sampling warning",),
        )
        artefact = DiagnosticsArtefact(prior_predictive=computed)
        d = artefact.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.prior_predictive.status == "computed"
        assert restored.prior_predictive.payload == computed.payload
        assert restored.prior_predictive.warnings == computed.warnings
        assert restored.fingerprint() == artefact.fingerprint()

    def test_computed_predictive_density_round_trips_through_to_dict(self):
        computed = DiagnosticSection(
            status="computed",
            payload={
                "model_type": "shared",
                "elpd_loo": -24.55,
                "elpd_loo_se": 0.61,
                "p_loo": 0.8,
                "loo_good_k_threshold": 0.5,
                "elpd_waic": -24.56,
                "elpd_waic_se": 0.61,
                "p_waic": 0.81,
                "n_data_points": 12,
                "rows": [
                    {
                        "market": "UK",
                        "outcome_id": "fh_new",
                        "n_observations": 3,
                        "mean_pareto_k": 0.39,
                        "max_pareto_k": 0.56,
                        "n_good_pareto_k": 2,
                        "n_bad_pareto_k": 1,
                        "n_very_bad_pareto_k": 0,
                        "mean_elpd_loo_i": -1.93,
                        "mean_elpd_waic_i": -1.93,
                    }
                ],
            },
            warnings=("a Pareto-k warning",),
        )
        artefact = DiagnosticsArtefact(predictive_density=computed)
        d = artefact.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.predictive_density.status == "computed"
        assert restored.predictive_density.payload == computed.payload
        assert restored.predictive_density.warnings == computed.warnings
        assert restored.fingerprint() == artefact.fingerprint()

    def test_prior_predictive_section_change_is_covered_by_fingerprint(self):
        base = DiagnosticsArtefact()
        with_evidence = DiagnosticsArtefact(
            prior_predictive=DiagnosticSection(status="computed", payload={"rows": []})
        )
        assert base.fingerprint() != with_evidence.fingerprint()

    def test_predictive_density_section_change_is_covered_by_fingerprint(self):
        base = DiagnosticsArtefact()
        with_evidence = DiagnosticsArtefact(
            predictive_density=DiagnosticSection(
                status="computed", payload={"rows": []}
            )
        )
        assert base.fingerprint() != with_evidence.fingerprint()


# =========================================================================
# Historical v2 fingerprint/readiness compatibility audit (Work Package 2)
# =========================================================================


# =========================================================================
# Schema v5 -> v6 compatibility (Work Package B, REQ-COVERAGE-001 S6):
# market_channel_capability added
# =========================================================================


class TestSchemaV5ToV6Compatibility:
    def _v5_dict(self) -> dict:
        not_computed = {
            "status": "not_computed",
            "payload": None,
            "error": "",
            "warnings": [],
        }
        computed_predictive_density = {
            "status": "computed",
            "payload": {"model_type": "shared", "rows": []},
            "error": "",
            "warnings": [],
        }
        return {
            "artefact_id": "v5-artefact",
            "diagnostics_version": "5.0.0",
            "schema_version": 5,
            "model_identity_fingerprint": "fp-v5",
            "evaluated_at": "2026-08-09T00:00:00+00:00",
            "model_type": "shared",
            "convergence": {
                "status": "computed",
                "payload": {"max_rhat": 1.01, "min_ess": 600, "has_divergences": False},
                "error": "",
                "warnings": [],
            },
            "in_sample_fit": not_computed,
            "posterior_predictive": not_computed,
            "plausibility": not_computed,
            "identification": not_computed,
            "coefficient_stability": not_computed,
            "backtest": not_computed,
            "error_metrics": not_computed,
            "residual_diagnostics": not_computed,
            "prior_predictive": not_computed,
            "predictive_density": computed_predictive_density,
            "settings": [],
            "legacy_incomplete": False,
        }

    def test_v5_upgrades_with_market_channel_capability_not_computed(self):
        artefact = DiagnosticsArtefact.from_dict(self._v5_dict())
        assert artefact.market_channel_capability.status == "not_computed"
        assert artefact.market_channel_capability.error != ""
        assert "schema v6" in artefact.market_channel_capability.error

    def test_v5_upgrade_preserves_schema_version_and_is_not_legacy_incomplete(self):
        artefact = DiagnosticsArtefact.from_dict(self._v5_dict())
        assert artefact.schema_version == 5
        assert artefact.legacy_incomplete is False

    def test_v5_upgrade_preserves_existing_sections(self):
        artefact = DiagnosticsArtefact.from_dict(self._v5_dict())
        assert artefact.convergence.payload["max_rhat"] == 1.01
        assert artefact.predictive_density.status == "computed"

    def test_v5_round_trip_through_to_dict_is_stable(self):
        artefact = DiagnosticsArtefact.from_dict(self._v5_dict())
        d = artefact.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.schema_version == artefact.schema_version
        assert restored.market_channel_capability.status == "not_computed"
        assert restored.fingerprint() == artefact.fingerprint()

    def test_historical_v5_version_is_not_upgraded_to_current(self):
        artefact = DiagnosticsArtefact.from_dict(self._v5_dict())
        assert artefact.diagnostics_version == "5.0.0"
        assert artefact.diagnostics_version != CURRENT_DIAGNOSTICS_VERSION


class TestSchemaV6FreshArtefact:
    def test_current_defaults_are_schema_v6(self):
        # Work Package 2 (canonical Diagnostics evidence integration,
        # `Media-Mix-Lab: Coding LLM Next Steps After PR #286`) bumped the
        # schema to v8 (posterior_predictive_metric_distributions,
        # historical_validation, structural_stability,
        # graphical_identification, latent_state_identification,
        # experiment_calibration sections) - this test's name is kept as
        # historical continuity with the v6 introduction, but its
        # assertion must track the live constants, same as every other
        # version-authority test in this file.
        assert CURRENT_DIAGNOSTICS_SCHEMA_VERSION == 8
        assert CURRENT_DIAGNOSTICS_VERSION.startswith("8.")

    def test_freshly_constructed_artefact_has_not_computed_market_channel_capability(
        self,
    ):
        artefact = DiagnosticsArtefact()
        assert artefact.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert artefact.market_channel_capability.status == "not_computed"

    def test_computed_market_channel_capability_round_trips_through_to_dict(self):
        computed = DiagnosticSection(
            status="computed",
            payload={
                "engine": "pymc_hierarchical_rectangular",
                "markets": ["UK"],
                "channels": ["TV"],
                "supported": False,
                "issues": [
                    {
                        "market": "UK",
                        "channel": "TV",
                        "reason": "No coverage record for 'TV' in market 'UK'.",
                    }
                ],
                "decision_report": "FR-MOD-015 is not resolved...",
            },
        )
        artefact = DiagnosticsArtefact(market_channel_capability=computed)
        d = artefact.to_dict()
        restored = DiagnosticsArtefact.from_dict(d)
        assert restored.market_channel_capability.status == "computed"
        assert restored.market_channel_capability.payload == computed.payload
        assert restored.fingerprint() == artefact.fingerprint()

    def test_market_channel_capability_section_change_is_covered_by_fingerprint(self):
        base = DiagnosticsArtefact()
        with_evidence = DiagnosticsArtefact(
            market_channel_capability=DiagnosticSection(
                status="computed", payload={"supported": True}
            )
        )
        assert base.fingerprint() != with_evidence.fingerprint()


class TestHistoricalV2FingerprintCompatibility:
    """A schema-v2 artefact fixture shaped exactly as it existed before PR
    #141 added the error_metrics/residual_diagnostics fields to
    DiagnosticsArtefact - no error_metrics/residual_diagnostics keys in the
    dict at all (the fixture TestSchemaV2Compatibility._v2_dict() already
    reproduces this shape). A readiness proof's diagnostic_artefact_fingerprint
    stored *before* PR #141 was computed under a fingerprint payload that
    never included error_metrics/residual_diagnostics keys at all. Today's
    loader always upgrades a v2 dict in memory to carry not_computed
    sections for both, and DiagnosticsArtefact.fingerprint() always hashes
    all nine sections - so recomputing today's fingerprint from that exact
    same v2 evidence can never reproduce a fingerprint computed by the
    pre-#141 formula. This must never be silently treated as "still
    verified" - it must fail the existing fingerprint-equality check
    (core.validation_policy.readiness_matches_current_evidence) and require
    re-evaluation, exactly like any other evidence drift."""

    @staticmethod
    def _v2_dict() -> dict:
        return TestSchemaV2Compatibility()._v2_dict()

    @staticmethod
    def _pre_pr141_fingerprint(artefact: DiagnosticsArtefact) -> str:
        """Independently reproduces the exact pre-PR-#141 fingerprint
        formula: the same payload DiagnosticsArtefact.fingerprint() builds
        today, minus the error_metrics/residual_diagnostics keys that did
        not exist in that formula at all - never calling today's
        .fingerprint() (which would trivially "match itself")."""
        import hashlib
        import json

        payload = {
            "schema_version": artefact.schema_version,
            "diagnostics_version": artefact.diagnostics_version,
            "model_identity_fingerprint": artefact.model_identity_fingerprint,
            "evaluated_at": artefact.evaluated_at.isoformat(),
            "model_type": artefact.model_type,
            "market_scope": artefact.market_scope,
            "convergence": artefact.convergence.fingerprint_payload(),
            "in_sample_fit": artefact.in_sample_fit.fingerprint_payload(),
            "posterior_predictive": artefact.posterior_predictive.fingerprint_payload(),
            "plausibility": artefact.plausibility.fingerprint_payload(),
            "identification": artefact.identification.fingerprint_payload(),
            "coefficient_stability": artefact.coefficient_stability.fingerprint_payload(),
            "backtest": artefact.backtest.fingerprint_payload(),
            "global_warnings": sorted(artefact.global_warnings),
            "global_errors": sorted(artefact.global_errors),
            "settings": tuple(sorted(artefact.settings)),
            "legacy_incomplete": artefact.legacy_incomplete,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def test_pre_pr141_fingerprint_does_not_match_current_loader_fingerprint(self):
        """Documents the identity gap explicitly: loading the exact same v2
        evidence today produces a different fingerprint than the formula
        that predated error_metrics/residual_diagnostics."""
        artefact = DiagnosticsArtefact.from_dict(self._v2_dict())
        historical_fingerprint = self._pre_pr141_fingerprint(artefact)
        assert historical_fingerprint != artefact.fingerprint()

    def test_stale_historical_fingerprint_fails_readiness_match_and_requires_reevaluation(
        self,
    ):
        """The one existing generic mechanism that decides whether a stored
        readiness proof still describes current evidence - a plain
        fingerprint-equality comparison, no artefact-shape special-casing -
        already fails this closed: a readiness carrying the pre-#141
        fingerprint never matches today's recomputation, so it is correctly
        excluded from being treated as current and must be re-evaluated. No
        second readiness system is introduced to handle this case."""
        from ancestry_mmm.core.validation_policy import (
            ApprovalReadiness,
            readiness_matches_current_evidence,
        )

        artefact = DiagnosticsArtefact.from_dict(self._v2_dict())
        historical_fingerprint = self._pre_pr141_fingerprint(artefact)

        readiness = ApprovalReadiness(
            readiness_artefact_id="historical-readiness",
            policy_id="pol-1",
            policy_version="1.0",
            policy_fingerprint="policy-fp",
            model_identity_fingerprint="identity-fp",
            diagnostic_artefact_fingerprint=historical_fingerprint,
            overall_ready=True,
        )

        # Re-verifying against the *same underlying evidence*, recomputed
        # by today's loader/fingerprint formula - must not match.
        assert not readiness_matches_current_evidence(
            readiness,
            policy_fingerprint="policy-fp",
            model_identity_fingerprint="identity-fp",
            diagnostic_artefact_fingerprint=artefact.fingerprint(),
        )


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

    def test_identification_diagnostics_each_computed_exactly_once(self):
        """PR 82B: identification, correlation matrix, condition number and
        coefficient stability were previously computed directly by the
        Diagnostics page (never by DiagnosticsService, always "not_computed"
        in the artefact). Each of the four underlying functions must now be
        called exactly once by evaluate() - never twice (e.g. once inside
        identification_report() and again separately for display), and
        never by the page."""
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)

        with (
            patch(
                "ancestry_mmm.application.diagnostics_service.channel_spend_correlation_matrix",
                wraps=_real_channel_spend_correlation_matrix,
            ) as mock_corr,
            patch(
                "ancestry_mmm.application.diagnostics_service.design_matrix_condition_number",
                wraps=_real_design_matrix_condition_number,
            ) as mock_cond,
            patch(
                "ancestry_mmm.application.diagnostics_service.identification_report",
                wraps=_real_identification_report,
            ) as mock_report,
            patch(
                "ancestry_mmm.application.diagnostics_service.posterior_coefficient_stability",
                wraps=_real_posterior_coefficient_stability,
            ) as mock_stability,
        ):
            result = DiagnosticsService().evaluate(diag_input)

        assert mock_corr.call_count == 1
        assert mock_cond.call_count == 1
        assert mock_report.call_count == 1
        assert mock_stability.call_count == 1
        assert not result.errors, result.errors

    def test_identification_section_is_computed_with_full_payload(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        result = DiagnosticsService().evaluate(diag_input)

        ident = result.diagnostics_artefact.identification
        assert ident.status == "computed", ident.error
        assert set(ident.payload.keys()) == {
            "flags",
            "correlation_matrix",
            "condition_number",
        }
        assert "TV" in ident.payload["correlation_matrix"]

    def test_coefficient_stability_section_is_computed_with_full_payload(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        result = DiagnosticsService().evaluate(diag_input)

        stability = result.diagnostics_artefact.coefficient_stability
        assert stability.status == "computed", stability.error
        assert stability.payload
        assert set(stability.payload[0].keys()) == {
            "outcome_id",
            "channel",
            "beta_mean",
            "beta_std",
            "coefficient_of_variation",
        }


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


# =========================================================================
# DiagnosticsService.run_backtest() - pure artefact update (PR 82B)
# =========================================================================


class TestRunBacktestUpdatesArtefactImmutably:
    """The Diagnostics page previously ran expanding_window_backtest()
    directly and stored a separate, untracked backtest_results state key -
    the canonical artefact was never updated, so readiness could keep
    reporting evidence from before the backtest ran. run_backtest() must
    instead return a new artefact with only the backtest section replaced,
    every other already-computed section carried over byte-for-byte, and a
    fingerprint that changes as a result."""

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

    def _base_artefact(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        return DiagnosticsService().evaluate(diag_input).diagnostics_artefact

    def test_backtest_section_updated_other_sections_unchanged(self):
        base = self._base_artefact()
        assert base.backtest.status == "not_computed"

        updated = DiagnosticsService().run_backtest(
            base,
            raw_model_dataframe=self._bt_dataframe(),
            raw_model_spec=ModelSpec(date_col="date", market_col="market"),
            fit_fold_fn=self._fit_fold_fn,
            n_folds=1,
        )

        assert updated.backtest.status == "computed", updated.backtest.error
        assert updated.backtest.payload[0]["outcome_id"] == "fh_new_gsa"
        # Every other section is the exact same object/value - never
        # recomputed by run_backtest().
        assert updated.convergence == base.convergence
        assert updated.in_sample_fit == base.in_sample_fit
        assert updated.posterior_predictive == base.posterior_predictive
        assert updated.plausibility == base.plausibility
        assert updated.identification == base.identification
        assert updated.coefficient_stability == base.coefficient_stability
        assert updated.artefact_id == base.artefact_id
        assert updated.model_identity_fingerprint == base.model_identity_fingerprint

    def test_backtest_update_changes_fingerprint(self):
        base = self._base_artefact()
        updated = DiagnosticsService().run_backtest(
            base,
            raw_model_dataframe=self._bt_dataframe(),
            raw_model_spec=ModelSpec(date_col="date", market_col="market"),
            fit_fold_fn=self._fit_fold_fn,
            n_folds=1,
        )
        assert updated.fingerprint() != base.fingerprint()

    def test_backtest_update_does_not_recompute_unrelated_diagnostics(self):
        base = self._base_artefact()
        with (
            patch(
                "ancestry_mmm.application.diagnostics_service.posterior_predictive_coverage",
                wraps=_real_posterior_predictive_coverage,
            ) as mock_ppc,
            patch(
                "ancestry_mmm.application.diagnostics_service.identification_report",
                wraps=_real_identification_report,
            ) as mock_report,
        ):
            DiagnosticsService().run_backtest(
                base,
                raw_model_dataframe=self._bt_dataframe(),
                raw_model_spec=ModelSpec(date_col="date", market_col="market"),
                fit_fold_fn=self._fit_fold_fn,
                n_folds=1,
            )
        assert mock_ppc.call_count == 0
        assert mock_report.call_count == 0

    def test_backtest_failure_replaces_section_with_failed_status(self):
        base = self._base_artefact()

        def _raising_fit_fold_fn(train_df, test_df):
            raise RuntimeError("fold fit exploded")

        updated = DiagnosticsService().run_backtest(
            base,
            raw_model_dataframe=self._bt_dataframe(),
            raw_model_spec=ModelSpec(date_col="date", market_col="market"),
            fit_fold_fn=_raising_fit_fold_fn,
            n_folds=1,
        )
        assert updated.backtest.status == "failed"
        assert "fold fit exploded" in updated.backtest.error
        # Unrelated sections still carried over unchanged even on failure.
        assert updated.convergence == base.convergence


# =========================================================================
# search_capacity section (schema v7, WP3 - Media-Mix-Lab: Coding LLM Next
# Steps After PR #253)
# =========================================================================


def _minimal_candidate_a_trace_frame_meta():
    """Extends `_minimal_trace_frame_meta`'s ordinary variables with the
    full Candidate A search_* variable set, and marks `meta` as a
    Candidate A fit - enough to exercise `DiagnosticsService.evaluate()`'s
    section 9 end to end without mocking arviz/numpy internals."""
    import dataclasses

    from ancestry_mmm.core.search_capacity import (
        CANDIDATE_A_CAPTURE_SHARE_COMPONENTS,
        SEARCH_CANDIDATE_A_ENGINE,
    )

    trace, frame, meta = _minimal_trace_frame_meta()
    n_chain = trace.posterior.sizes["chain"]
    n_draw = trace.posterior.sizes["draw"]
    n_obs = trace.posterior.sizes["obs"]
    n_outcome = len(meta.outcome_ids)
    rng = np.random.default_rng(3)

    demand = np.abs(rng.normal(50, 5, size=(n_chain, n_draw, n_obs)))
    paid_opportunity = demand * 0.4
    organic = demand * 0.3
    direct = demand * 0.2
    cap = np.full((n_chain, n_draw, n_obs), 1000.0)
    realised_paid = np.minimum(paid_opportunity, cap)
    captured = organic + direct + realised_paid
    unmet = demand - captured

    search_posterior = {
        "search_demand_market_pool_sigma": np.abs(
            rng.normal(0.3, 0.05, (n_chain, n_draw))
        ),
        "search_demand_market_raw": rng.normal(0, 1, (n_chain, n_draw, 1)),
        "search_demand_market_offset": rng.normal(0, 0.1, (n_chain, n_draw, 1)),
        "search_demand_intercept": rng.normal(2.0, 0.1, (n_chain, n_draw)),
        "search_demand_media_beta": np.abs(rng.normal(0.4, 0.05, (n_chain, n_draw, 1))),
        "search_latent_branded_demand": demand,
        "search_capture_shares": np.abs(rng.normal(0.25, 0.02, (n_chain, n_draw, 4))),
        "search_unconstrained_paid_opportunity": paid_opportunity,
        "search_realised_paid_delivery": realised_paid,
        "search_organic_capture_expected": organic,
        "search_direct_navigation_capture_expected": direct,
        "search_total_captured_demand": captured,
        "search_unmet_demand": unmet,
        "search_cap_binding_probability": np.zeros((n_chain, n_draw, n_obs)),
        "search_unused_capacity": cap - realised_paid,
        "search_paid_delivery_observation_sigma": np.abs(
            rng.normal(2, 0.5, (n_chain, n_draw))
        ),
        "search_capture_observation_sigma": np.abs(
            rng.normal(2, 0.5, (n_chain, n_draw))
        ),
        "search_paid_capture_outcome_beta": np.abs(
            rng.normal(0.4, 0.05, (n_chain, n_draw, n_outcome))
        ),
        "search_organic_capture_outcome_beta": np.abs(
            rng.normal(0.3, 0.05, (n_chain, n_draw, n_outcome))
        ),
        "search_direct_navigation_capture_outcome_beta": np.abs(
            rng.normal(0.3, 0.05, (n_chain, n_draw, n_outcome))
        ),
        "search_eta_contribution": rng.normal(
            0, 0.1, (n_chain, n_draw, n_obs, n_outcome)
        ),
    }
    search_dims = {
        "search_demand_market_raw": ["market"],
        "search_demand_market_offset": ["market"],
        "search_demand_media_beta": ["search_demand_channel"],
        "search_latent_branded_demand": ["obs"],
        "search_capture_shares": ["search_capture_share_component"],
        "search_unconstrained_paid_opportunity": ["obs"],
        "search_realised_paid_delivery": ["obs"],
        "search_organic_capture_expected": ["obs"],
        "search_direct_navigation_capture_expected": ["obs"],
        "search_total_captured_demand": ["obs"],
        "search_unmet_demand": ["obs"],
        "search_cap_binding_probability": ["obs"],
        "search_unused_capacity": ["obs"],
        "search_paid_capture_outcome_beta": ["outcome"],
        "search_organic_capture_outcome_beta": ["outcome"],
        "search_direct_navigation_capture_outcome_beta": ["outcome"],
        "search_eta_contribution": ["obs", "outcome"],
    }
    merged_posterior = {
        **{k: v.values for k, v in trace.posterior.data_vars.items()},
        **search_posterior,
    }
    merged_coords = {
        **{k: v.values for k, v in trace.posterior.coords.items()},
        "search_demand_channel": ["SearchBrand"],
        "search_capture_share_component": list(CANDIDATE_A_CAPTURE_SHARE_COMPONENTS),
    }
    ordinary_dims = {
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
    }
    candidate_a_trace = az.from_dict(
        posterior=merged_posterior,
        coords=merged_coords,
        dims={**ordinary_dims, **search_dims},
        sample_stats={"diverging": np.zeros((n_chain, n_draw), dtype=bool)},
    )
    candidate_a_meta = dataclasses.replace(
        meta, causal_graph_engine=SEARCH_CANDIDATE_A_ENGINE
    )
    return candidate_a_trace, frame, candidate_a_meta


class TestSearchCapacitySection:
    def test_ordinary_fit_reports_not_applicable(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        result = DiagnosticsService().evaluate(diag_input)
        assert result.diagnostics_artefact.search_capacity.status == "not_applicable"

    def test_candidate_a_fit_computes_posterior_summary(self):
        trace, frame, meta = _minimal_candidate_a_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        result = DiagnosticsService().evaluate(diag_input)

        section = result.diagnostics_artefact.search_capacity
        assert section.status == "computed", section.error
        assert section.payload["engine"] == "pymc_search_candidate_a"
        assert "posterior_summary" in section.payload
        assert section.payload["spec_issues"] is None
        assert any("No Candidate A SearchCandidateASpec" in w for w in section.warnings)

    def test_search_capacity_section_round_trips_and_is_fingerprinted(self):
        trace, frame, meta = _minimal_candidate_a_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact

        restored = DiagnosticsArtefact.from_dict(artefact.to_dict())
        assert restored.search_capacity.status == "computed"
        assert restored.fingerprint() == artefact.fingerprint()

        # Changing only search_capacity's payload must change the overall
        # fingerprint - proves it is actually included in fingerprint(),
        # not merely serialised.
        import dataclasses as dc

        mutated = dc.replace(
            artefact,
            search_capacity=DiagnosticSection(
                status="computed", payload={"engine": "different"}
            ),
        )
        assert mutated.fingerprint() != artefact.fingerprint()

    def test_schema_v6_artefact_upgrades_search_capacity_to_not_computed(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        v6_dict = {**artefact.to_dict(), "schema_version": 6}
        del v6_dict["search_capacity"]

        restored = DiagnosticsArtefact.from_dict(v6_dict)
        assert restored.schema_version == 6
        assert restored.search_capacity.status == "not_computed"
        assert "schema v7" in restored.search_capacity.error


# =========================================================================
# Work Package 2 (canonical Diagnostics evidence integration,
# `Media-Mix-Lab: Coding LLM Next Steps After PR #286`): schema v8 -
# posterior_predictive_metric_distributions (REQ-PPD-001),
# historical_validation / structural_stability (REQ-LEAK-001 /
# REQ-STAB-001), graphical_identification (REQ-IDENT-001),
# latent_state_identification (REQ-LATENT-001), experiment_calibration
# (REQ-EXPMODE-001 / REQ-CALIB-001).
# =========================================================================


def _minimal_market_specific_trace_frame_meta():
    """A minimal, single-market, single-outcome, single-channel Model C
    trace/frame/meta triple - the Model C equivalent of
    `_minimal_trace_frame_meta`, carrying every posterior variable
    `DiagnosticsService.evaluate()`'s market_specific path touches
    (market-indexed hill_K/beta, mu/alpha, decay_rate/hill_S/promo_coef/
    market_offset/intercept/trend_coef/gamma_fourier - mirroring
    `test_market_specific_diagnostics.py`'s own full `trace` fixture,
    scoped down to one market/outcome/channel) so the full evaluate()
    pipeline succeeds end to end, not only one function under test."""
    rng = np.random.default_rng(23)
    n_obs, n_chain, n_draw = 16, 2, 20
    oids = ["fh_new_gsa"]
    chs = ["TV"]
    markets = ["UK"]

    Y = rng.uniform(5, 30, size=(n_obs, 1))
    frame = {
        "Y": Y,
        "X_media": rng.uniform(0, 100, size=(n_obs, 1)),
        "markets": markets,
        "market_bounds": [(0, n_obs)],
        "market_idx": np.zeros(n_obs, dtype=int),
        "promo": np.zeros((n_obs, 1)),
        "trend": np.arange(n_obs, dtype=float),
        "fourier": np.zeros((n_obs, 4)),
        "control_names": [],
        "X_controls": np.zeros((n_obs, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }
    meta = FHModelMeta(
        markets=markets,
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

    posterior = {
        "hill_K": np.ones((n_chain, n_draw, 1, 1)),
        "beta": np.ones((n_chain, n_draw, 1, 1, 1)),
        "hill_S": np.full((n_chain, n_draw, 1), 4.0),
        "alpha": np.full((n_chain, n_draw, 1), 8.0),
        "mu": np.maximum(
            Y[None, None, :, 0] + rng.normal(0, 0.5, size=(n_chain, n_draw, n_obs)),
            0.1,
        )[..., None],
        "decay_rate": np.full((n_chain, n_draw, 1), 0.5),
        "promo_coef": np.zeros((n_chain, n_draw, 1)),
        "market_offset": np.zeros((n_chain, n_draw, 1, 1)),
        "intercept": np.zeros((n_chain, n_draw, 1)),
        "trend_coef": np.zeros((n_chain, n_draw, 1)),
        "gamma_fourier": np.zeros((n_chain, n_draw, 4, 1)),
    }
    dims = {
        "hill_K": ["market", "channel"],
        "beta": ["market", "outcome", "channel"],
        "hill_S": ["channel"],
        "alpha": ["outcome"],
        "mu": ["obs", "outcome"],
        "decay_rate": ["channel"],
        "promo_coef": ["outcome"],
        "market_offset": ["market", "outcome"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"],
    }
    coords = {
        "obs": list(range(n_obs)),
        "outcome": oids,
        "channel": chs,
        "market": markets,
        "fourier": list(range(4)),
    }
    trace = az.from_dict(
        posterior=posterior,
        coords=coords,
        dims=dims,
        sample_stats={"diverging": np.zeros((n_chain, n_draw), dtype=bool)},
    )
    return trace, frame, meta


def _simple_confounder_graph():
    """X <- Z -> Y, X -> Y: Z is a confounder on the only backdoor path -
    the same minimal scenario `test_estimand_identification.py` uses."""
    from ancestry_mmm.core.causal_graph import CausalEdge, CausalGraph, CausalNode

    return CausalGraph(
        graph_id="wp2-diagnostics-test-graph",
        graph_version=1,
        nodes=[CausalNode(node_id=n, label=n) for n in ("X", "Y", "Z")],
        edges=[
            CausalEdge(source_node_id="Z", target_node_id="X"),
            CausalEdge(source_node_id="Z", target_node_id="Y"),
            CausalEdge(source_node_id="X", target_node_id="Y"),
        ],
    )


class TestSchemaV8Migration:
    def test_v7_artefact_upgrades_all_six_new_sections_to_not_computed(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        v7_dict = {**artefact.to_dict(), "schema_version": 7}
        for key in (
            "posterior_predictive_metric_distributions",
            "historical_validation",
            "structural_stability",
            "graphical_identification",
            "latent_state_identification",
            "experiment_calibration",
        ):
            del v7_dict[key]

        restored = DiagnosticsArtefact.from_dict(v7_dict)
        assert restored.schema_version == 7
        assert restored.legacy_incomplete is False
        for section, name in (
            (restored.posterior_predictive_metric_distributions, "REQ-PPD-001"),
            (restored.historical_validation, "REQ-LEAK-001"),
            (restored.structural_stability, "REQ-STAB-001"),
            (restored.graphical_identification, "REQ-IDENT-001"),
            (restored.latent_state_identification, "REQ-LATENT-001"),
            (restored.experiment_calibration, "REQ-EXPMODE-001"),
        ):
            assert section.status == "not_computed"
            assert "schema v8" in section.error
            assert name in section.error

    def test_v7_upgrade_preserves_existing_sections(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        v7_dict = {**artefact.to_dict(), "schema_version": 7}
        for key in (
            "posterior_predictive_metric_distributions",
            "historical_validation",
            "structural_stability",
            "graphical_identification",
            "latent_state_identification",
            "experiment_calibration",
        ):
            del v7_dict[key]

        restored = DiagnosticsArtefact.from_dict(v7_dict)
        assert restored.convergence.status == "computed"
        assert restored.error_metrics.status == "computed"

    def test_v7_round_trip_through_to_dict_is_stable(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        v7_dict = {**artefact.to_dict(), "schema_version": 7}
        for key in (
            "posterior_predictive_metric_distributions",
            "historical_validation",
            "structural_stability",
            "graphical_identification",
            "latent_state_identification",
            "experiment_calibration",
        ):
            del v7_dict[key]

        restored = DiagnosticsArtefact.from_dict(v7_dict)
        round_tripped = DiagnosticsArtefact.from_dict(restored.to_dict())
        assert round_tripped.schema_version == restored.schema_version
        assert round_tripped.fingerprint() == restored.fingerprint()

    def test_unsupported_future_schema_version_is_rejected(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        future_dict = {**artefact.to_dict(), "schema_version": 9}
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            DiagnosticsArtefact.from_dict(future_dict)


class TestSchemaV8FreshArtefact:
    def test_current_defaults_are_schema_v8(self):
        assert CURRENT_DIAGNOSTICS_SCHEMA_VERSION == 8
        assert CURRENT_DIAGNOSTICS_VERSION == "8.0.0"

    def test_freshly_constructed_artefact_has_not_computed_new_sections(self):
        artefact = DiagnosticsArtefact()
        assert artefact.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        for section in (
            artefact.posterior_predictive_metric_distributions,
            artefact.historical_validation,
            artefact.structural_stability,
            artefact.graphical_identification,
            artefact.latent_state_identification,
            artefact.experiment_calibration,
        ):
            assert section.status == "not_computed"

    @pytest.mark.parametrize(
        "field_name",
        [
            "posterior_predictive_metric_distributions",
            "historical_validation",
            "structural_stability",
            "graphical_identification",
            "latent_state_identification",
            "experiment_calibration",
        ],
    )
    def test_each_new_section_change_is_covered_by_fingerprint(self, field_name):
        import dataclasses as dc

        base = DiagnosticsArtefact()
        mutated = dc.replace(
            base,
            **{
                field_name: DiagnosticSection(
                    status="computed", payload={"evidence": 1}
                )
            },
        )
        assert base.fingerprint() != mutated.fingerprint()


class TestEvaluatePosteriorPredictiveMetricDistributions:
    """REQ-PPD-001 wired into DiagnosticsService.evaluate() - Model A and
    Model C, computed inline from the same trace/frame/meta/params already
    used for error_metrics (no extra fit)."""

    def test_model_a_computes_the_section(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact

        section = artefact.posterior_predictive_metric_distributions
        assert section.status == "computed", section.error
        assert len(section.payload) == len(meta.outcome_ids)
        row = section.payload[0]
        for metric in ("mae", "rmse", "smape_pct", "wape_pct", "bias"):
            for suffix in ("point", "mean", "median", "lower", "upper"):
                assert f"{metric}_{suffix}" in row

    def test_model_c_computes_the_section(self):
        trace, frame, meta = _minimal_market_specific_trace_frame_meta()
        diag_input = DiagnosticsInput(
            trace=trace, frame=frame, meta=meta, model_type="market_specific"
        )
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact

        section = artefact.posterior_predictive_metric_distributions
        assert section.status == "computed", section.error
        assert len(section.payload) == len(meta.outcome_ids)

    def test_section_round_trips_and_is_fingerprinted(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact

        restored = DiagnosticsArtefact.from_dict(artefact.to_dict())
        assert restored.fingerprint() == artefact.fingerprint()
        assert (
            restored.posterior_predictive_metric_distributions.payload
            == artefact.posterior_predictive_metric_distributions.payload
        )


class TestEvaluateGraphicalIdentification:
    """REQ-IDENT-001 wired into DiagnosticsService.evaluate()."""

    def test_no_graph_or_requests_is_not_computed(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        assert artefact.graphical_identification.status == "not_computed"

    def test_graph_compatible_total_effect_request_is_computed(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(
            trace=trace,
            frame=frame,
            meta=meta,
            causal_graph=_simple_confounder_graph(),
            identification_requests=[
                {
                    "treatment": "X",
                    "outcome": "Y",
                    "effect_type": "total",
                    "proposed_adjustment_set": ("Z",),
                }
            ],
        )
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        section = artefact.graphical_identification
        assert section.status == "computed", section.error
        results = section.payload["results"]
        assert len(results) == 1
        assert results[0]["status"] == "graph_compatible"
        assert "does not prove" in results[0]["disclaimer"]

    def test_unsupported_direct_effect_request_is_rejected_not_silently_allowed(self):
        """REQ-IDENT-001: a direct-effect request must never be silently
        treated as identified by the total-effect backdoor checker - it
        must resolve to unsupported_by_current_checker."""
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(
            trace=trace,
            frame=frame,
            meta=meta,
            causal_graph=_simple_confounder_graph(),
            identification_requests=[
                {
                    "treatment": "X",
                    "outcome": "Y",
                    "effect_type": "direct",
                    "proposed_adjustment_set": ("Z",),
                }
            ],
        )
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        section = artefact.graphical_identification
        assert section.status == "computed", section.error
        results = section.payload["results"]
        assert results[0]["status"] == "unsupported_by_current_checker"
        assert results[0]["effect_type"] == "direct"

    def test_section_round_trips_and_is_fingerprinted(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(
            trace=trace,
            frame=frame,
            meta=meta,
            causal_graph=_simple_confounder_graph(),
            identification_requests=[
                {"treatment": "X", "outcome": "Y", "proposed_adjustment_set": ("Z",)}
            ],
        )
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        restored = DiagnosticsArtefact.from_dict(artefact.to_dict())
        assert restored.fingerprint() == artefact.fingerprint()
        assert restored.graphical_identification.status == "computed"


class TestEvaluateLatentStateIdentification:
    """REQ-LATENT-001 wired into DiagnosticsService.evaluate()."""

    def test_ordinary_fit_is_not_applicable(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        assert artefact.latent_state_identification.status == "not_applicable"

    def test_candidate_a_fit_with_no_declaration_is_not_identified(self):
        """REQ-LATENT-001's fail-closed contract: no declaration means
        not_identified, never a fabricated pass."""
        trace, frame, meta = _minimal_candidate_a_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact

        section = artefact.latent_state_identification
        assert section.status == "computed", section.error
        results = {r["latent_state_id"]: r for r in section.payload["results"]}
        assert (
            results["candidate_a_latent_branded_search_demand"]["status"]
            == "not_identified"
        )
        assert (
            "does not prove"
            in results["candidate_a_latent_branded_search_demand"]["disclaimer"]
        )

    def test_candidate_a_fit_with_declaration_but_no_chain_draws_is_review_required(
        self,
    ):
        """A declared identifying strategy that has not yet been
        empirically checked under sampling is review_required, not a
        fabricated pass."""
        from ancestry_mmm.core.latent_state_identification import (
            LatentStateIdentificationDeclaration,
        )

        trace, frame, meta = _minimal_candidate_a_trace_frame_meta()
        declaration = LatentStateIdentificationDeclaration(
            latent_state_id="candidate_a_latent_branded_search_demand",
            strategy_kind="anchored_to_observed",
            description="Anchored to observed branded-search impressions.",
        )
        diag_input = DiagnosticsInput(
            trace=trace,
            frame=frame,
            meta=meta,
            latent_state_declarations=[declaration],
        )
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact

        section = artefact.latent_state_identification
        assert section.status == "computed", section.error
        results = {r["latent_state_id"]: r for r in section.payload["results"]}
        assert (
            results["candidate_a_latent_branded_search_demand"]["status"]
            == "review_required"
        )

    def test_section_round_trips_and_is_fingerprinted(self):
        trace, frame, meta = _minimal_candidate_a_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        restored = DiagnosticsArtefact.from_dict(artefact.to_dict())
        assert restored.fingerprint() == artefact.fingerprint()
        assert restored.latent_state_identification.status == "computed"


class TestEvaluateExperimentCalibration:
    """REQ-EXPMODE-001 / REQ-CALIB-001 wired into
    DiagnosticsService.evaluate()."""

    def test_no_evidence_supplied_is_not_applicable(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        assert artefact.experiment_calibration.status == "not_applicable"

    def test_experiment_provenance_report_is_computed_and_kept_separate(self):
        from ancestry_mmm.core.experiments import (
            ExperimentProvenanceEntry,
            ExperimentProvenanceReport,
        )

        report = ExperimentProvenanceReport(
            model_id="model-1",
            model_version="1",
            entries=(
                ExperimentProvenanceEntry(
                    experiment_id="exp-1",
                    experiment_version=1,
                    evidence_mode="validation_only",
                    estimand="total_effect_tv_on_new",
                    observed_effect_estimate=0.12,
                    effect_uncertainty=0.03,
                ),
            ),
        )
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(
            trace=trace,
            frame=frame,
            meta=meta,
            experiment_provenance_report=report,
        )
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact

        section = artefact.experiment_calibration
        assert section.status == "computed", section.error
        assert section.payload["experiments"]["entries"][0]["experiment_id"] == "exp-1"
        # Never collapsed into an average - each entry retains its own
        # estimand/uncertainty individually.
        assert "effect_uncertainty" in section.payload["experiments"]["entries"][0]
        assert section.payload["calibration_comparison"] is None

    def test_section_round_trips_and_is_fingerprinted(self):
        from ancestry_mmm.core.experiments import (
            ExperimentProvenanceEntry,
            ExperimentProvenanceReport,
        )

        report = ExperimentProvenanceReport(
            model_id="model-1",
            model_version="1",
            entries=(
                ExperimentProvenanceEntry(
                    experiment_id="exp-1",
                    experiment_version=1,
                    evidence_mode="validation_only",
                    estimand="total_effect_tv_on_new",
                    observed_effect_estimate=0.12,
                    effect_uncertainty=0.03,
                ),
            ),
        )
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(
            trace=trace,
            frame=frame,
            meta=meta,
            experiment_provenance_report=report,
        )
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact
        restored = DiagnosticsArtefact.from_dict(artefact.to_dict())
        assert restored.fingerprint() == artefact.fingerprint()


class TestRunHistoricalAndStructuralValidationCheck:
    """REQ-LEAK-001 / REQ-STAB-001 wired into DiagnosticsService via
    `run_historical_and_structural_validation_check` - the same pure,
    immutable "replace one section, carry the rest" pattern as
    `run_backtest`/`run_prior_predictive_check`."""

    def _fold(self, fold_id: str):
        from ancestry_mmm.core.validation_folds import ValidationFold

        return ValidationFold(
            fold_id=fold_id,
            fold_manifest_version=1,
            train_start="2024-01-01",
            train_end="2024-06-01",
            test_start="2024-06-08",
            test_end="2024-07-01",
        )

    def _safe_assessment(self, fold_id: str):
        from ancestry_mmm.core.validation_folds import (
            LEAKAGE_STATUS_SAFE,
            FoldReconstructionAssessment,
            VariableReconstructionAssessment,
        )

        return FoldReconstructionAssessment(
            fold_id=fold_id,
            per_variable=(
                VariableReconstructionAssessment(
                    variable_id="tv_spend",
                    market="UK",
                    status=LEAKAGE_STATUS_SAFE,
                    reason="Source version pinned before fold cutoff.",
                ),
            ),
        )

    def _unsafe_assessment(self, fold_id: str):
        from ancestry_mmm.core.validation_folds import (
            LEAKAGE_STATUS_CANNOT_VERIFY,
            FoldReconstructionAssessment,
            VariableReconstructionAssessment,
        )

        return FoldReconstructionAssessment(
            fold_id=fold_id,
            per_variable=(
                VariableReconstructionAssessment(
                    variable_id="tv_spend",
                    market="UK",
                    status=LEAKAGE_STATUS_CANNOT_VERIFY,
                    reason="Source version pinned after fold cutoff.",
                ),
            ),
            limitations=("Cannot verify a later source version.",),
        )

    def _snapshot(self, fold_id: str, value: float):
        from ancestry_mmm.core.structural_stability import FoldParameterSnapshot

        return FoldParameterSnapshot(
            fold_id=fold_id, point_values={"hill_K__TV": value}
        )

    def test_missing_fold_history_is_not_computed(self):
        """No folds supplied at all (e.g. a project with no historical
        support yet) - both sections must be not_computed, never a
        fabricated evidence payload."""
        base = DiagnosticsArtefact()
        result = DiagnosticsService().run_historical_and_structural_validation_check(
            base,
            results_df=pd.DataFrame(),
            folds=(),
            assessments=(),
            snapshots=(),
        )
        assert result.historical_validation.status == "not_computed"
        assert result.structural_stability.status == "not_computed"

    def test_folds_assessed_but_none_leakage_safe_is_still_computed_evidence(self):
        """Every fold rejected is still genuine evidence - not_computed
        would silently hide that the evaluation actually ran."""
        fold = self._fold("fold-1")
        base = DiagnosticsArtefact()
        result = DiagnosticsService().run_historical_and_structural_validation_check(
            base,
            results_df=pd.DataFrame(
                [
                    {
                        "fold_id": "fold-1",
                        "outcome_id": None,
                        "leakage_safe": False,
                        "skipped_reason": "cannot_verify",
                    }
                ]
            ),
            folds=(fold,),
            assessments=(self._unsafe_assessment("fold-1"),),
            snapshots=(),
        )
        assert result.historical_validation.status == "computed"
        assert result.historical_validation.payload["n_folds_leakage_safe"] == 0
        # No fold cleared, so no snapshot exists - structural stability
        # cannot be computed, and must say so explicitly.
        assert result.structural_stability.status == "not_computed"

    def test_folds_with_snapshots_compute_both_sections_from_one_fit(self):
        fold_a, fold_b = self._fold("fold-1"), self._fold("fold-2")
        base = DiagnosticsArtefact()
        result = DiagnosticsService().run_historical_and_structural_validation_check(
            base,
            results_df=pd.DataFrame(
                [
                    {
                        "fold_id": "fold-1",
                        "outcome_id": "fh_new_gsa",
                        "r_squared": 0.8,
                        "mape_pct": 12.0,
                        "leakage_safe": True,
                        "skipped_reason": None,
                    },
                    {
                        "fold_id": "fold-2",
                        "outcome_id": "fh_new_gsa",
                        "r_squared": 0.75,
                        "mape_pct": 14.0,
                        "leakage_safe": True,
                        "skipped_reason": None,
                    },
                ]
            ),
            folds=(fold_a, fold_b),
            assessments=(
                self._safe_assessment("fold-1"),
                self._safe_assessment("fold-2"),
            ),
            snapshots=(
                self._snapshot("fold-1", 100.0),
                self._snapshot("fold-2", 110.0),
            ),
        )
        assert result.historical_validation.status == "computed"
        assert result.historical_validation.payload["n_folds_leakage_safe"] == 2
        assert result.structural_stability.status == "computed"
        per_param = result.structural_stability.payload["per_parameter"]
        assert len(per_param) == 1
        assert per_param[0]["parameter_name"] == "hill_K__TV"
        assert per_param[0]["point_range"] == pytest.approx(10.0)
        # REQ-STAB-001: never a status/verdict/pass/fail field.
        for forbidden in ("status", "verdict", "pass", "fail", "stable", "unstable"):
            assert forbidden not in per_param[0]

    def test_update_is_pure_and_carries_other_sections_over_unchanged(self):
        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact

        fold = self._fold("fold-1")
        updated = DiagnosticsService().run_historical_and_structural_validation_check(
            artefact,
            results_df=pd.DataFrame(
                [
                    {
                        "fold_id": "fold-1",
                        "outcome_id": "fh_new_gsa",
                        "r_squared": 0.8,
                        "mape_pct": 12.0,
                        "leakage_safe": True,
                        "skipped_reason": None,
                    }
                ]
            ),
            folds=(fold,),
            assessments=(self._safe_assessment("fold-1"),),
            snapshots=(self._snapshot("fold-1", 100.0),),
        )
        # The original artefact object is untouched.
        assert artefact.historical_validation.status == "not_computed"
        # Every other already-computed section carries over unchanged.
        assert updated.convergence.payload == artefact.convergence.payload
        assert updated.error_metrics.payload == artefact.error_metrics.payload
        assert updated.historical_validation.status == "computed"
        assert updated.structural_stability.status == "computed"
        assert updated.fingerprint() != artefact.fingerprint()

    def test_upgrades_a_pre_v8_artefact_schema_version(self):
        """Mirrors run_prior_predictive_check's own upgrade contract: an
        artefact computed before schema v8 must be upgraded to current so
        to_dict()/from_dict() can round-trip the newly-added evidence."""
        pre_v8 = DiagnosticsArtefact(schema_version=7)
        fold = self._fold("fold-1")
        updated = DiagnosticsService().run_historical_and_structural_validation_check(
            pre_v8,
            results_df=pd.DataFrame(
                [{"fold_id": "fold-1", "leakage_safe": True, "skipped_reason": None}]
            ),
            folds=(fold,),
            assessments=(self._safe_assessment("fold-1"),),
            snapshots=(self._snapshot("fold-1", 100.0),),
        )
        assert updated.schema_version == CURRENT_DIAGNOSTICS_SCHEMA_VERSION
        assert updated.diagnostics_version == CURRENT_DIAGNOSTICS_VERSION

        round_tripped = DiagnosticsArtefact.from_dict(updated.to_dict())
        assert round_tripped.historical_validation.status == "computed"
        assert round_tripped.fingerprint() == updated.fingerprint()


class TestSchemaV8StalenessAndReadiness:
    """REQ-VAL-001's existing `diagnostic_artefact_fingerprint` staleness
    mechanism (`core.validation_policy.readiness_matches_current_evidence`,
    `ApprovalReadiness`) must react to schema-v8 evidence changes
    automatically - no new policy/threshold code is introduced by this
    work package."""

    def test_readiness_becomes_stale_when_historical_validation_evidence_is_added(
        self,
    ):
        from ancestry_mmm.core.validation_policy import (
            ApprovalReadiness,
            readiness_matches_current_evidence,
        )
        from ancestry_mmm.core.validation_folds import ValidationFold
        from ancestry_mmm.core.validation_folds import (
            LEAKAGE_STATUS_SAFE,
            FoldReconstructionAssessment,
            VariableReconstructionAssessment,
        )
        from ancestry_mmm.core.structural_stability import FoldParameterSnapshot

        trace, frame, meta = _minimal_trace_frame_meta()
        diag_input = DiagnosticsInput(trace=trace, frame=frame, meta=meta)
        artefact = DiagnosticsService().evaluate(diag_input).diagnostics_artefact

        readiness = ApprovalReadiness(
            readiness_artefact_id="r1",
            policy_fingerprint="policy-fp",
            model_identity_fingerprint="model-fp",
            diagnostic_artefact_fingerprint=artefact.fingerprint(),
            overall_ready=True,
        )
        # Bound to the artefact's fingerprint as it stood before WP2
        # evidence was added - still current.
        assert readiness_matches_current_evidence(
            readiness,
            policy_fingerprint="policy-fp",
            model_identity_fingerprint="model-fp",
            diagnostic_artefact_fingerprint=artefact.fingerprint(),
        )

        fold = ValidationFold(
            fold_id="fold-1",
            fold_manifest_version=1,
            train_start="2024-01-01",
            train_end="2024-06-01",
            test_start="2024-06-08",
            test_end="2024-07-01",
        )
        assessment = FoldReconstructionAssessment(
            fold_id="fold-1",
            per_variable=(
                VariableReconstructionAssessment(
                    variable_id="tv_spend",
                    market="UK",
                    status=LEAKAGE_STATUS_SAFE,
                    reason="Source version pinned before fold cutoff.",
                ),
            ),
        )
        snapshot = FoldParameterSnapshot(
            fold_id="fold-1", point_values={"hill_K__TV": 100.0}
        )
        updated_artefact = (
            DiagnosticsService().run_historical_and_structural_validation_check(
                artefact,
                results_df=pd.DataFrame(
                    [
                        {
                            "fold_id": "fold-1",
                            "leakage_safe": True,
                            "skipped_reason": None,
                        }
                    ]
                ),
                folds=(fold,),
                assessments=(assessment,),
                snapshots=(snapshot,),
            )
        )

        # The stored readiness was evaluated against the artefact before
        # this new evidence existed - it must now be stale.
        assert not readiness_matches_current_evidence(
            readiness,
            policy_fingerprint="policy-fp",
            model_identity_fingerprint="model-fp",
            diagnostic_artefact_fingerprint=updated_artefact.fingerprint(),
        )
