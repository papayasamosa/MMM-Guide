"""Tests for the application-layer ProjectService (PR 82D): the governance
evidence chain established in PR 82B (validation_policy, diagnostics_artefact,
validation_results, approval_readiness) round-trips through
ProjectExportInput/ProjectService.export(), and an imported readiness is
never trusted unless it verifiably still matches the imported policy,
diagnostics artefact, and reconstructed model identity.
"""

from datetime import datetime, timezone

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact
from ancestry_mmm.application.project_service import (
    ProjectExportInput,
    ProjectService,
    verify_imported_readiness,
)
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.persistence import (
    export_project,
    import_project,
    reconstruct_model_state,
)
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.validation_policy import (
    ThresholdPolicy,
    ValidationEvidenceContext,
    evaluate_approval_readiness,
)
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame


def _make_meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=["New"],
        channels=["TV_Brand"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="New",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
    )


def _make_trace(
    meta: FHModelMeta,
    n_fourier: int = 6,
    chains: int = 2,
    draws: int = 10,
    seed: int = 0,
) -> az.InferenceData:
    """A structurally-valid (but not really fitted) trace - same recipe as
    test_persistence.py's `_make_trace`, kept local so this file doesn't
    depend on another test module's internals."""
    rng = np.random.default_rng(seed)
    n_ch, n_seg, n_mkt = len(meta.channels), len(meta.outcome_ids), len(meta.markets)
    posterior = {
        "decay_rate": rng.uniform(0.1, 0.9, size=(chains, draws, n_ch)),
        "hill_K": rng.uniform(500, 2000, size=(chains, draws, n_ch)),
        "hill_S": rng.uniform(0.5, 2.0, size=(chains, draws, n_ch)),
        "intercept": rng.normal(size=(chains, draws, n_seg)),
        "trend_coef": rng.normal(size=(chains, draws, n_seg)),
        "promo_coef": rng.uniform(0, 1, size=(chains, draws, n_seg)),
        "alpha": rng.uniform(1, 10, size=(chains, draws, n_seg)),
        "beta": rng.normal(size=(chains, draws, n_seg, n_ch)),
        "market_offset": rng.normal(size=(chains, draws, n_mkt, n_seg)),
        "gamma_fourier": rng.normal(size=(chains, draws, n_fourier, n_seg)),
    }
    coords = {
        "channel": meta.channels,
        "outcome": meta.outcome_ids,
        "market": meta.markets,
        "fourier": list(range(n_fourier)),
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
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


@pytest.fixture
def meta() -> FHModelMeta:
    return _make_meta()


@pytest.fixture
def trace(meta) -> az.InferenceData:
    return _make_trace(meta)


@pytest.fixture
def governed_project(meta, trace):
    """A project bundle whose validation_policy / diagnostics_artefact /
    approval_readiness evidence chain genuinely matches the model identity
    being exported alongside it - the same "internally consistent" recipe
    test_persistence.py's `consistent_project` fixture uses for
    `model_approval`, extended with PR 82B's governance evidence chain."""
    transformed_data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=8, freq="W"),
            "market": ["UK"] * 8,
            "TV_Brand": [100.0, 120.0, 90.0, 110.0, 130.0, 95.0, 105.0, 115.0],
            "fh_new_gsa": [10, 12, 9, 11, 13, 9, 10, 11],
        }
    )
    model_spec_dict = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=["TV_Brand"],
    ).to_dict()
    prior_config = {"decay_mu": 0.5}
    dna_lag_weeks = 4

    spec = ModelSpec.from_dict(model_spec_dict)
    frame = prepare_fh_modeling_frame(transformed_data, spec)
    posterior_params = extract_posterior_params(trace, meta)

    model_run_id = "run-governed-1"
    identity = ModelIdentity(
        model_run_id=model_run_id,
        data_fingerprint=fingerprint_dataframe(frame["df"]),
        model_spec_fingerprint=fingerprint_model_spec(
            model_spec_dict,
            prior_config,
            dna_lag_weeks,
            direct_dna_outcome_ids=meta.direct_dna_outcome_ids,
        ),
        posterior_fingerprint=fingerprint_posterior(posterior_params),
    )

    artefact = DiagnosticsArtefact(
        artefact_id="artefact-1",
        model_identity_fingerprint=identity.fingerprint(),
        model_type="shared",
        market_scope="UK",
    )
    policy = ThresholdPolicy(
        policy_id="pol-1",
        version="1.0.0",
        scope="official",
        gates=[],
        owner="QA Team",
        approval_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    readiness = evaluate_approval_readiness(
        [],
        policy,
        identity,
        diagnostic_artefact_id=artefact.artefact_id,
        diagnostic_artefact_fingerprint=artefact.fingerprint(),
        evidence_context=ValidationEvidenceContext(
            model_identity=identity,
            policy=policy,
            diagnostic_artefact_id=artefact.artefact_id,
            diagnostic_artefact_fingerprint=artefact.fingerprint(),
            model_type="shared",
        ),
    )

    return dict(
        raw_sources={},
        transformed_data=transformed_data,
        pipeline_steps=[],
        model_spec=model_spec_dict,
        prior_config=prior_config,
        dna_lag_weeks=dna_lag_weeks,
        trace=trace,
        scenarios=[],
        model_run_id=model_run_id,
        model_meta=meta,
        validation_policy=policy.to_dict(),
        diagnostics_artefact=artefact.to_dict(),
        validation_results=[],
        approval_readiness=readiness.to_dict(),
    )


class TestProjectExportInputGovernanceFields:
    def test_export_passes_governance_fields_through_to_the_bundle(
        self, tmp_path, governed_project
    ):
        exp_input = ProjectExportInput(
            output_path=str(tmp_path / "bundle.zip"),
            **governed_project,
        )
        result = ProjectService().export(exp_input)

        assert result.success, result.errors
        imported = import_project(result.actual_export_path)
        assert imported["validation_policy"] == governed_project["validation_policy"]
        assert (
            imported["diagnostics_artefact"] == governed_project["diagnostics_artefact"]
        )
        assert imported["validation_results"] == []
        assert imported["approval_readiness"] == governed_project["approval_readiness"]

    def test_export_omits_governance_fields_when_none(self, tmp_path, governed_project):
        governed_project = dict(governed_project)
        governed_project["validation_policy"] = None
        governed_project["diagnostics_artefact"] = None
        governed_project["validation_results"] = None
        governed_project["approval_readiness"] = None
        exp_input = ProjectExportInput(
            output_path=str(tmp_path / "bundle.zip"),
            **governed_project,
        )
        result = ProjectService().export(exp_input)

        assert result.success, result.errors
        imported = import_project(result.actual_export_path)
        assert imported["validation_policy"] is None
        assert imported["diagnostics_artefact"] is None
        assert imported["validation_results"] is None
        assert imported["approval_readiness"] is None


class TestVerifyImportedReadiness:
    def test_matching_imported_readiness_is_verified(self, tmp_path, governed_project):
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        readiness, message = verify_imported_readiness(imported, reconstructed)

        assert readiness is not None
        assert readiness == governed_project["approval_readiness"]
        assert "verified" in message.lower()

    def test_no_readiness_in_bundle_returns_none(self, tmp_path, governed_project):
        governed_project = dict(governed_project)
        governed_project["approval_readiness"] = None
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        readiness, message = verify_imported_readiness(imported, reconstructed)

        assert readiness is None
        assert "no approval readiness" in message.lower()

    def test_readiness_without_accompanying_policy_is_rejected(
        self, tmp_path, governed_project
    ):
        governed_project = dict(governed_project)
        governed_project["validation_policy"] = None
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        readiness, message = verify_imported_readiness(imported, reconstructed)

        assert readiness is None
        assert "missing its accompanying" in message.lower()

    def test_readiness_without_accompanying_artefact_is_rejected(
        self, tmp_path, governed_project
    ):
        governed_project = dict(governed_project)
        governed_project["diagnostics_artefact"] = None
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        readiness, message = verify_imported_readiness(imported, reconstructed)

        assert readiness is None
        assert "missing its accompanying" in message.lower()

    def test_rejected_when_diagnostics_artefact_since_drifted(
        self, tmp_path, governed_project
    ):
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)
        # Simulate the diagnostics artefact having been updated (e.g. by a
        # backtest, PR 82B) after the readiness was evaluated against it -
        # its fingerprint no longer matches the readiness's recorded one.
        imported["diagnostics_artefact"]["market_scope"] = "US"
        reconstructed = reconstruct_model_state(imported)

        readiness, message = verify_imported_readiness(imported, reconstructed)

        assert readiness is None
        assert "does not match" in message.lower()

    def test_rejected_when_policy_since_drifted(self, tmp_path, governed_project):
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)
        imported["validation_policy"]["version"] = "2.0.0"
        reconstructed = reconstruct_model_state(imported)

        readiness, message = verify_imported_readiness(imported, reconstructed)

        assert readiness is None
        assert "does not match" in message.lower()

    def test_rejected_when_imported_model_data_differs(
        self, tmp_path, governed_project
    ):
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)
        imported["transformed_data"].loc[0, "TV_Brand"] = 999999.0
        reconstructed = reconstruct_model_state(imported)

        readiness, message = verify_imported_readiness(imported, reconstructed)

        assert readiness is None
        assert "does not match" in message.lower()

    def test_no_reconstruction_possible_returns_none(self, tmp_path, governed_project):
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)
        reconstructed = {"frame": None, "model_meta": None, "posterior_params": None}

        readiness, message = verify_imported_readiness(imported, reconstructed)

        assert readiness is None
        assert "could not reconstruct" in message.lower()

    def test_malformed_evidence_is_never_trusted(self, tmp_path, governed_project):
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)
        # A gate_results list of non-dict entries cannot be parsed back
        # into ApprovalReadiness - must be discarded, never raised to the
        # caller uncaught and never silently trusted.
        imported["approval_readiness"]["gate_results"] = [1, 2, 3]
        reconstructed = reconstruct_model_state(imported)

        readiness, message = verify_imported_readiness(imported, reconstructed)

        assert readiness is None
        assert message
