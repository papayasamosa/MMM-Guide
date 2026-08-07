"""Tests for the application-layer ProjectService (PR 82D): the governance
evidence chain established in PR 82B (validation_policy, diagnostics_artefact,
validation_results, approval_readiness) round-trips through
ProjectExportInput/ProjectService.export(), and an imported readiness is
never trusted unless it verifiably still matches the imported policy,
diagnostics artefact, and reconstructed model identity.
"""

import dataclasses
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
from ancestry_mmm.core.approval import create_policy_backed_model_approval
from ancestry_mmm.core.curve_artifact import (
    CurveArtifactMetadata,
    compute_curve_artifact_fingerprints,
    write_curve_artifact,
)
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.planning.value import CurrencyContext
from ancestry_mmm.core.scenario_governance import CounterfactualPolicy
from ancestry_mmm.core.persistence import (
    export_project,
    import_project,
    reconstruct_model_state,
    verify_imported_approval,
)
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.validation_policy import (
    ApprovalReadiness,
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


@pytest.fixture
def governed_project_with_approval(governed_project):
    """``governed_project`` extended with a policy-backed ``model_approval``
    bound to the exact same policy/readiness/model identity - the full
    evidence chain PR 88A's import-time restoration must verify as a whole,
    not policy/readiness/approval independently."""
    identity = ModelIdentity(
        model_run_id=governed_project["model_run_id"],
        data_fingerprint=fingerprint_dataframe(
            prepare_fh_modeling_frame(
                governed_project["transformed_data"],
                ModelSpec.from_dict(governed_project["model_spec"]),
            )["df"]
        ),
        model_spec_fingerprint=fingerprint_model_spec(
            governed_project["model_spec"],
            governed_project["prior_config"],
            governed_project["dna_lag_weeks"],
            direct_dna_outcome_ids=governed_project[
                "model_meta"
            ].direct_dna_outcome_ids,
        ),
        posterior_fingerprint=fingerprint_posterior(
            extract_posterior_params(
                governed_project["trace"], governed_project["model_meta"]
            )
        ),
    )
    policy = ThresholdPolicy.from_dict(governed_project["validation_policy"])
    readiness = ApprovalReadiness.from_dict(governed_project["approval_readiness"])
    approval = create_policy_backed_model_approval(
        approved_by="Jane Analyst",
        readiness=readiness,
        current_policy=policy,
        model_run_id=identity.model_run_id,
        data_fingerprint=identity.data_fingerprint,
        model_spec_fingerprint=identity.model_spec_fingerprint,
        posterior_fingerprint=identity.posterior_fingerprint,
    )
    project = dict(governed_project)
    project["model_approval"] = approval.to_dict()
    return project


class TestImportedApprovalChainRestoration:
    """PR 88A: a policy-backed ``model_approval`` must not be restored as
    current official authority when its bound readiness is rejected as
    unverified. Before this fix, ``verify_imported_approval`` only checked
    model identity (``matches_current_model``) - a policy-backed approval
    whose readiness had just been rejected by ``verify_imported_readiness``
    (evaluated completely independently) could still come back "verified"
    on identity alone."""

    def test_valid_bundle_restores_the_complete_chain(
        self, tmp_path, governed_project_with_approval
    ):
        output_path = export_project(
            tmp_path / "bundle.zip", **governed_project_with_approval
        )
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        verified_readiness_dict, readiness_message = verify_imported_readiness(
            imported, reconstructed
        )
        assert verified_readiness_dict is not None, readiness_message
        current_policy = ThresholdPolicy.from_dict(imported["validation_policy"])
        readiness_obj = ApprovalReadiness.from_dict(verified_readiness_dict)

        approval, approval_message = verify_imported_approval(
            imported,
            reconstructed,
            current_policy=current_policy,
            approval_readiness=readiness_obj,
        )
        assert approval is not None, approval_message
        assert approval.validation_policy_id == current_policy.policy_id

    def test_rejected_readiness_blocks_policy_backed_approval_restoration(
        self, tmp_path, governed_project_with_approval
    ):
        output_path = export_project(
            tmp_path / "bundle.zip", **governed_project_with_approval
        )
        imported = import_project(output_path)
        # Simulate the diagnostics artefact having drifted since the
        # readiness was evaluated (e.g. a backtest updated it) - readiness
        # verification must now reject it.
        imported["diagnostics_artefact"]["market_scope"] = "US"
        reconstructed = reconstruct_model_state(imported)

        verified_readiness_dict, readiness_message = verify_imported_readiness(
            imported, reconstructed
        )
        assert verified_readiness_dict is None, (
            "test setup should have made readiness verification fail"
        )
        current_policy = ThresholdPolicy.from_dict(imported["validation_policy"])

        # This mirrors exactly what pages/09_Project_Export.py now passes:
        # the (rejected -> None) verified readiness, never the raw imported
        # dict, and never skipping the check just because identity matches.
        approval, approval_message = verify_imported_approval(
            imported,
            reconstructed,
            current_policy=current_policy,
            approval_readiness=None,
        )
        assert approval is None
        assert "policy-backed" in approval_message.lower()
        assert "readiness" in approval_message.lower()


class TestDiagnosticsArtefactStructuredPersistence:
    """PR 88A part A: DiagnosticsArtefact must round-trip through export as
    structured JSON, never as an opaque string from json.dumps's default=str
    fallback (which is what happens if the raw domain object - rather than
    its .to_dict() - reaches export_project()), and must be restored via
    DiagnosticsArtefact.from_dict() on import, not left as a raw dict."""

    def test_diagnostics_artefact_round_trips_as_structured_json(
        self, tmp_path, governed_project
    ):
        output_path = export_project(tmp_path / "bundle.zip", **governed_project)
        imported = import_project(output_path)

        # Structured JSON with directly addressable fields - not a single
        # opaque string (json.dumps(<object>, default=str) would produce a
        # str, and json.loads() of that bundle entry would then also be a
        # str, never a dict).
        assert isinstance(imported["diagnostics_artefact"], dict)
        assert imported["diagnostics_artefact"]["artefact_id"] == "artefact-1"
        assert imported["diagnostics_artefact"]["model_type"] == "shared"

        rehydrated = DiagnosticsArtefact.from_dict(imported["diagnostics_artefact"])
        original = DiagnosticsArtefact.from_dict(
            governed_project["diagnostics_artefact"]
        )
        assert rehydrated.fingerprint() == original.fingerprint()
        # The object a page relies on for attribute access (e.g.
        # `.identification.status`), not a plain dict.
        assert rehydrated.identification.status == "not_computed"


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


class TestProjectExportInputCounterfactualAndCurrencyContext:
    """PR 125A: counterfactual_policy / currency_context - the project-level
    planning dependencies newly threaded through ProjectExportInput ->
    ProjectService.export() -> export_project(), mirroring the governance
    fields above."""

    def test_export_passes_fields_through_to_the_bundle(
        self, tmp_path, governed_project
    ):
        governed_project = dict(governed_project)
        governed_project["counterfactual_policy"] = CounterfactualPolicy().to_dict()
        governed_project["currency_context"] = CurrencyContext(
            market_reporting_currency="GBP", value_currency="GBP"
        ).to_dict()
        exp_input = ProjectExportInput(
            output_path=str(tmp_path / "bundle.zip"),
            **governed_project,
        )
        result = ProjectService().export(exp_input)

        assert result.success, result.errors
        imported = import_project(result.actual_export_path)
        assert (
            imported["counterfactual_policy"]
            == governed_project["counterfactual_policy"]
        )
        assert imported["currency_context"] == governed_project["currency_context"]

    def test_export_omits_fields_when_none(self, tmp_path, governed_project):
        exp_input = ProjectExportInput(
            output_path=str(tmp_path / "bundle.zip"),
            **governed_project,
        )
        result = ProjectService().export(exp_input)

        assert result.success, result.errors
        imported = import_project(result.actual_export_path)
        assert imported["counterfactual_policy"] is None
        assert imported["currency_context"] is None


class TestProjectExportInputCausalGraphs:
    """REQ-GRAPH-001 work package (graph portability): causal_graphs - the
    new ProjectExportInput field mirroring counterfactual_policy/
    currency_context above, threaded through ProjectService.export() to
    export_project()."""

    def test_export_passes_field_through_to_the_bundle(
        self, tmp_path, governed_project
    ):
        from ancestry_mmm.core.causal_graph import CausalGraph, CausalNode

        graph = CausalGraph(
            graph_id="g1",
            graph_version=1,
            nodes=[
                CausalNode(node_id="tv_spend", role="intervention"),
                CausalNode(node_id="fh_new", role="outcome"),
            ],
        )
        governed_project = dict(governed_project)
        governed_project["causal_graphs"] = [graph.to_dict()]
        exp_input = ProjectExportInput(
            output_path=str(tmp_path / "bundle.zip"),
            **governed_project,
        )
        result = ProjectService().export(exp_input)

        assert result.success, result.errors
        imported = import_project(result.actual_export_path)
        assert imported["causal_graphs"] == governed_project["causal_graphs"]

    def test_export_omits_field_when_none(self, tmp_path, governed_project):
        exp_input = ProjectExportInput(
            output_path=str(tmp_path / "bundle.zip"),
            **governed_project,
        )
        result = ProjectService().export(exp_input)

        assert result.success, result.errors
        imported = import_project(result.actual_export_path)
        assert imported["causal_graphs"] is None


class TestProjectExportInputCurveArtifactStore:
    """PR 96B: curve_artifact_store_source_dir - a new ProjectExportInput
    field mirroring the pre-existing curve_bank_source_dir, threaded
    through ProjectService.export() to export_project()."""

    @staticmethod
    def _write_minimal_artifact(directory):
        metadata = CurveArtifactMetadata(
            artifact_id="art-1",
            creation_timestamp="2026-08-01T00:00:00+00:00",
            model_identity_snapshot={"model_run_id": "run-1"},
            outcome_definition_snapshot={
                "outcome_id": "fh_new_gsa",
                "definition_version": "1.0",
            },
            outcome_approval_snapshot={
                "approval_id": "apr-1",
                "allowed_uses": ["curve_publication"],
            },
        )
        metadata = dataclasses.replace(
            metadata,
            fingerprints=dict(compute_curve_artifact_fingerprints(metadata)),
        )
        draws = pd.DataFrame(
            [
                {
                    "model_run_id": "run-1",
                    "reference_context_id": "ctx-1",
                    "market": "UK",
                    "product": "fh",
                    "segment": "New",
                    "outcome_id": "fh_new_gsa",
                    "metric_key": "fh_gsa",
                    "channel": "TV",
                    "component_type": "direct",
                    "pathway_role": "primary",
                    "spend_point": 0,
                    "posterior_draw": 0,
                    "incremental_response": 1.0,
                }
            ]
        )
        summaries = pd.DataFrame(
            [
                {
                    "model_run_id": "run-1",
                    "reference_context_id": "ctx-1",
                    "market": "UK",
                    "product": "fh",
                    "segment": "New",
                    "outcome_id": "fh_new_gsa",
                    "metric_key": "fh_gsa",
                    "channel": "TV",
                    "component_type": "direct",
                    "pathway_role": "primary",
                    "spend_point": 0,
                    "incremental_response": 1.0,
                }
            ]
        )
        write_curve_artifact(
            directory, metadata=metadata, draws=draws, summaries=summaries
        )

    def test_export_passes_curve_artifact_store_through_to_the_bundle(
        self, tmp_path, governed_project
    ):
        store_dir = tmp_path / "artifact-store"
        self._write_minimal_artifact(store_dir / "art-1")
        project = dict(governed_project)
        project["curve_artifact_store_source_dir"] = str(store_dir)
        exp_input = ProjectExportInput(
            output_path=str(tmp_path / "bundle.zip"),
            **project,
        )
        result = ProjectService().export(exp_input)

        assert result.success, result.errors
        imported = import_project(result.actual_export_path)
        assert imported["manifest"]["contains"]["official_curve_artifacts"] is True
        assert any(
            key.endswith("curve_artifact_metadata.json")
            for key in imported["curve_artifact_files"]
        )

    def test_export_omits_curve_artifact_store_when_none(
        self, tmp_path, governed_project
    ):
        exp_input = ProjectExportInput(
            output_path=str(tmp_path / "bundle.zip"),
            **governed_project,
        )
        result = ProjectService().export(exp_input)

        assert result.success, result.errors
        imported = import_project(result.actual_export_path)
        assert imported["manifest"]["contains"]["official_curve_artifacts"] is False
        assert imported["curve_artifact_files"] == {}


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
