"""Tests for ancestry_mmm.application.curve_service (REQ-CURVE-001, PR 93B).

Fixture shapes (meta/trace/reference context) mirror the established
patterns in test_canonical_curves.py, reduced to a single market/channel/
outcome since these tests exercise the *governance* gate, not the curve
mathematics (already covered by test_canonical_curves.py).
"""

import json

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.application.curve_service import (
    OFFICIAL_CURVE_ARTIFACT_SCHEMA_VERSION,
    CurveGovernanceBlockedError,
    CurveGovernanceEvidence,
    CurveService,
    ExploratoryCurveResult,
    MalformedCurveArtifactError,
    OfficialCurveArtifact,
    export_curve_artifact,
    import_curve_artifact,
    load_all_curve_artifacts,
)
from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact
from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.canonical_curves import CurveReferenceContext
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.media_costs import MediaInputSpec, MediaInputSupport
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    OutcomeApprovalBlockedError,
    fingerprint_outcome_definition,
)
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
)
from ancestry_mmm.core.validation_policy import ApprovalReadiness, ThresholdPolicy

MARKET = "UK"
CHANNEL = "TV"
OUTCOME_ID = "fh_new"


# ---------------------------------------------------------------------------
# Curve-generation fixtures (single market/channel/outcome)
# ---------------------------------------------------------------------------


def _broadcast(value, n_draw=4):
    value = np.asarray(value, dtype=float)
    return np.broadcast_to(value, (1, n_draw) + value.shape).copy()


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=[MARKET],
        outcome_ids=[OUTCOME_ID],
        channels=[CHANNEL],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id=OUTCOME_ID,
        dna_lag_weeks=0,
        unpooled_markets=[],
        control_names=[],
        outcome_id_to_product={OUTCOME_ID: FAMILY_HISTORY},
        outcome_id_to_segment={OUTCOME_ID: "New"},
        outcome_id_to_metric_key={OUTCOME_ID: METRIC_KEY_FH_GSA},
        outcome_id_to_unit={OUTCOME_ID: "count"},
    )


def _trace() -> az.InferenceData:
    posterior = {
        "decay_rate": _broadcast([0.5]),
        "hill_K": _broadcast([100.0]),
        "hill_S": _broadcast([1.0]),
        "beta": _broadcast([[0.2]]),
        "active_cross_product_strength": _broadcast([[0.0]]),
        "promo_coef": _broadcast([0.25]),
        "market_offset": _broadcast([[0.0]]),
        "intercept": _broadcast([3.0]),
        "trend_coef": _broadcast([0.2]),
        "gamma_fourier": _broadcast([[0.1]]),
        "alpha": _broadcast([5.0]),
        "control_coef": _broadcast(np.zeros(0)),
    }
    coords = {
        "outcome": [OUTCOME_ID],
        "channel": [CHANNEL],
        "market": [MARKET],
        "fourier": [0],
        "control": [],
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "beta": ["outcome", "channel"],
        "active_cross_product_strength": ["outcome", "channel"],
        "promo_coef": ["outcome"],
        "market_offset": ["market", "outcome"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "gamma_fourier": ["fourier", "outcome"],
        "alpha": ["outcome"],
        "control_coef": ["control"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


def _contexts() -> dict:
    return {
        MARKET: CurveReferenceContext(
            reference_context_id=f"{MARKET}-recent",
            mode="recent_average",
            market=MARKET,
            trend=0.5,
            fourier=(0.25,),
            promo={OUTCOME_ID: 0.0},
            controls={},
            outcome_controls={},
            other_channel_media_input={CHANNEL: 20.0},
            counterfactual_value=0.0,
            counterfactual_axis_type="model_input",
            reference_period_start="2026-04-01",
            reference_period_end="2026-06-30",
        )
    }


def _media_input_specs() -> dict:
    return {
        (MARKET, CHANNEL): MediaInputSpec(
            market=MARKET,
            channel=CHANNEL,
            column="tv_impressions",
            unit="thousand_impressions",
            unit_scale=1000.0,
        )
    }


def _support(*, missing: bool = False) -> dict:
    if missing:
        return {}
    return {
        (MARKET, CHANNEL): MediaInputSupport(
            market=MARKET,
            channel=CHANNEL,
            unit="thousand_impressions",
            current=50.0,
            observed_min=0.0,
            observed_max=100.0,
            planning_min=0.0,
            planning_max=150.0,
            current_method="last_4_week_average",
            source="model frame",
            provenance="test:X_media",
        )
    }


def _draw_kwargs(
    meta: FHModelMeta, *, model_run_id: str = "run-93b-1", support=None
) -> dict:
    return dict(
        model_run_id=model_run_id,
        meta=meta,
        trace=_trace(),
        reference_contexts=_contexts(),
        n_draws=2,
        spend_points=[0.0, 50.0],
        curve_type="model_input",
        media_input_specs=_media_input_specs(),
        support_by_market_channel=_support() if support is None else support,
    )


# ---------------------------------------------------------------------------
# Governance-evidence fixtures
# ---------------------------------------------------------------------------


def _model_identity(model_run_id: str = "run-93b-1") -> ModelIdentity:
    return ModelIdentity(
        model_run_id=model_run_id,
        data_fingerprint="data-fp-1",
        model_spec_fingerprint="spec-fp-1",
        posterior_fingerprint="posterior-fp-1",
    )


def _threshold_policy() -> ThresholdPolicy:
    return ThresholdPolicy(
        policy_id="pol-curve-1",
        version="1.0.0",
        scope="curve-official",
        owner="platform-governance",
    )


def _diagnostics_artefact(identity: ModelIdentity, **overrides) -> DiagnosticsArtefact:
    kwargs = dict(
        artefact_id="diag-1",
        schema_version=2,
        model_identity_fingerprint=identity.fingerprint(),
        legacy_incomplete=False,
    )
    kwargs.update(overrides)
    return DiagnosticsArtefact(**kwargs)


def _approval_readiness(
    identity: ModelIdentity,
    policy: ThresholdPolicy,
    diagnostics: DiagnosticsArtefact,
    **overrides,
) -> ApprovalReadiness:
    kwargs = dict(
        readiness_artefact_id="ready-1",
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_fingerprint=policy.fingerprint(),
        model_identity_fingerprint=identity.fingerprint(),
        diagnostic_artefact_id=diagnostics.artefact_id,
        diagnostic_artefact_fingerprint=diagnostics.fingerprint(),
        overall_ready=True,
    )
    kwargs.update(overrides)
    return ApprovalReadiness(**kwargs)


def _model_approval(
    identity: ModelIdentity,
    policy: ThresholdPolicy,
    readiness: ApprovalReadiness,
    **overrides,
) -> ModelApproval:
    kwargs = dict(
        approved_by="reviewer",
        model_run_id=identity.model_run_id,
        data_fingerprint=identity.data_fingerprint,
        model_spec_fingerprint=identity.model_spec_fingerprint,
        posterior_fingerprint=identity.posterior_fingerprint,
        validation_policy_id=policy.policy_id,
        validation_policy_version=policy.version,
        validation_policy_fingerprint=policy.fingerprint(),
        readiness_artefact_id=readiness.readiness_artefact_id,
        readiness_fingerprint=readiness.fingerprint(),
    )
    kwargs.update(overrides)
    return ModelApproval(**kwargs)


def _outcome_definition() -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id=OUTCOME_ID,
        product=FAMILY_HISTORY,
        segment="New",
        metric="GSA",
        metric_key=METRIC_KEY_FH_GSA,
        source_column="GSA_New",
        unit="GSA",
        aggregation_type="count",
        event_definition="A qualifying action",
        date_basis="event_date",
        cohort_or_attribution_basis="signup_cohort",
        completeness_or_maturity_policy="Mature after 12 weeks",
        exclusions="None",
        reconciliation_source="Finance report",
        business_owner="Analytics",
        definition_version="1.0",
    )


def _outcome_approval(outcome: OutcomeDefinition, **overrides) -> OutcomeApproval:
    kwargs = dict(
        approval_id="apr-curve-1",
        outcome_id=outcome.outcome_id,
        definition_fingerprint=fingerprint_outcome_definition(outcome),
        status="approved",
        allowed_uses=("curve_publication",),
        approved_by="Jane Analyst",
        approved_at="2026-01-01",
    )
    kwargs.update(overrides)
    return OutcomeApproval(**kwargs)


def _activity_definition(**overrides) -> ActivityDefinition:
    kwargs = dict(
        activity_id="tv-paid",
        channel=CHANNEL,
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        source="media plan",
        approval_status="approved",
        approved_by="reviewer",
        approved_at="2026-01-01",
    )
    kwargs.update(overrides)
    return ActivityDefinition(**kwargs)


def _valid_evidence(model_run_id: str = "run-93b-1") -> CurveGovernanceEvidence:
    identity = _model_identity(model_run_id)
    policy = _threshold_policy()
    diagnostics = _diagnostics_artefact(identity)
    readiness = _approval_readiness(identity, policy, diagnostics)
    approval = _model_approval(identity, policy, readiness)
    outcome = _outcome_definition()
    outcome_approval = _outcome_approval(outcome)
    return CurveGovernanceEvidence(
        model_identity=identity,
        model_approval=approval,
        threshold_policy=policy,
        approval_readiness=readiness,
        diagnostics_artefact=diagnostics,
        outcome=outcome,
        outcome_approval=outcome_approval,
        activity_definitions=(_activity_definition(),),
    )


# ---------------------------------------------------------------------------
# Governance omission -> TypeError (the structural fix)
# ---------------------------------------------------------------------------


class TestGovernanceEvidenceIsStructurallyRequired:
    def test_omitting_activity_definitions_is_a_type_error(self):
        """The direct regression test for the PR #87 / REQ-CURVE-001 defect:
        generate_canonical_curve_draws(governance_mode="official") silently
        skips its activity-approval check when activity_definitions is
        omitted. CurveGovernanceEvidence has no such escape hatch."""
        identity = _model_identity()
        policy = _threshold_policy()
        diagnostics = _diagnostics_artefact(identity)
        readiness = _approval_readiness(identity, policy, diagnostics)
        approval = _model_approval(identity, policy, readiness)
        outcome = _outcome_definition()
        outcome_approval = _outcome_approval(outcome)
        with pytest.raises(TypeError):
            CurveGovernanceEvidence(
                model_identity=identity,
                model_approval=approval,
                threshold_policy=policy,
                approval_readiness=readiness,
                diagnostics_artefact=diagnostics,
                outcome=outcome,
                outcome_approval=outcome_approval,
                # activity_definitions omitted on purpose
            )

    @pytest.mark.parametrize(
        "omitted_field",
        [
            "model_identity",
            "model_approval",
            "threshold_policy",
            "approval_readiness",
            "diagnostics_artefact",
            "outcome",
            "outcome_approval",
            "activity_definitions",
        ],
    )
    def test_omitting_any_governance_field_is_a_type_error(self, omitted_field):
        identity = _model_identity()
        policy = _threshold_policy()
        diagnostics = _diagnostics_artefact(identity)
        readiness = _approval_readiness(identity, policy, diagnostics)
        approval = _model_approval(identity, policy, readiness)
        outcome = _outcome_definition()
        outcome_approval = _outcome_approval(outcome)
        fields = dict(
            model_identity=identity,
            model_approval=approval,
            threshold_policy=policy,
            approval_readiness=readiness,
            diagnostics_artefact=diagnostics,
            outcome=outcome,
            outcome_approval=outcome_approval,
            activity_definitions=(_activity_definition(),),
        )
        del fields[omitted_field]
        with pytest.raises(TypeError):
            CurveGovernanceEvidence(**fields)


# ---------------------------------------------------------------------------
# Individual governance failure modes
# ---------------------------------------------------------------------------


class TestGovernanceContentValidation:
    def test_full_valid_chain_succeeds(self, meta):
        artifact = CurveService().generate_official_curve(
            evidence=_valid_evidence(), **_draw_kwargs(meta)
        )
        assert isinstance(artifact, OfficialCurveArtifact)
        assert artifact.is_official is True
        assert artifact.governance_chain_fingerprint
        assert artifact.schema_version == OFFICIAL_CURVE_ARTIFACT_SCHEMA_VERSION
        assert not artifact.draws.empty

    def test_mismatched_model_approval_raises(self, meta):
        evidence = _valid_evidence()
        other_identity = _model_identity(model_run_id="a-different-run")
        bad_approval = _model_approval(
            other_identity, _threshold_policy(), evidence.approval_readiness
        )
        evidence = CurveGovernanceEvidence(
            model_identity=evidence.model_identity,
            model_approval=bad_approval,
            threshold_policy=evidence.threshold_policy,
            approval_readiness=evidence.approval_readiness,
            diagnostics_artefact=evidence.diagnostics_artefact,
            outcome=evidence.outcome,
            outcome_approval=evidence.outcome_approval,
            activity_definitions=evidence.activity_definitions,
        )
        with pytest.raises(ApprovalMismatchError):
            CurveService().generate_official_curve(
                evidence=evidence, **_draw_kwargs(meta)
            )

    def test_model_approval_not_policy_backed_raises(self, meta):
        identity = _model_identity()
        policy = _threshold_policy()
        diagnostics = _diagnostics_artefact(identity)
        readiness = _approval_readiness(identity, policy, diagnostics)
        unbound_approval = ModelApproval(
            approved_by="reviewer",
            model_run_id=identity.model_run_id,
            data_fingerprint=identity.data_fingerprint,
            model_spec_fingerprint=identity.model_spec_fingerprint,
            posterior_fingerprint=identity.posterior_fingerprint,
            # validation_policy_id left blank on purpose
        )
        outcome = _outcome_definition()
        evidence = CurveGovernanceEvidence(
            model_identity=identity,
            model_approval=unbound_approval,
            threshold_policy=policy,
            approval_readiness=readiness,
            diagnostics_artefact=diagnostics,
            outcome=outcome,
            outcome_approval=_outcome_approval(outcome),
            activity_definitions=(_activity_definition(),),
        )
        with pytest.raises(CurveGovernanceBlockedError, match="validation policy"):
            CurveService().generate_official_curve(
                evidence=evidence, **_draw_kwargs(meta)
            )

    def test_stale_readiness_raises(self, meta):
        """require_matching_approval already catches a readiness whose own
        model_identity_fingerprint has drifted (as ApprovalMismatchError/
        ValidationPolicyBlockedError) - so this targets the one staleness
        gap it does *not* cover: the diagnostics artefact being regenerated
        (a new fingerprint) after readiness was evaluated, with model
        identity and policy unchanged. That's exactly what
        readiness_matches_current_evidence exists to catch."""
        identity = _model_identity()
        policy = _threshold_policy()
        old_diagnostics = _diagnostics_artefact(
            identity, artefact_id="diag-old", diagnostics_version="2.0.0"
        )
        readiness = _approval_readiness(identity, policy, old_diagnostics)
        approval = _model_approval(identity, policy, readiness)
        new_diagnostics = _diagnostics_artefact(
            identity, artefact_id="diag-new", diagnostics_version="2.0.1"
        )
        outcome = _outcome_definition()
        evidence = CurveGovernanceEvidence(
            model_identity=identity,
            model_approval=approval,
            threshold_policy=policy,
            approval_readiness=readiness,
            diagnostics_artefact=new_diagnostics,
            outcome=outcome,
            outcome_approval=_outcome_approval(outcome),
            activity_definitions=(_activity_definition(),),
        )
        with pytest.raises(CurveGovernanceBlockedError, match="no longer reflects"):
            CurveService().generate_official_curve(
                evidence=evidence, **_draw_kwargs(meta)
            )

    def test_diagnostics_artefact_identity_mismatch_raises(self, meta):
        evidence = _valid_evidence()
        wrong_diagnostics = _diagnostics_artefact(
            _model_identity(model_run_id="unrelated-run")
        )
        evidence = CurveGovernanceEvidence(
            model_identity=evidence.model_identity,
            model_approval=evidence.model_approval,
            threshold_policy=evidence.threshold_policy,
            approval_readiness=evidence.approval_readiness,
            diagnostics_artefact=wrong_diagnostics,
            outcome=evidence.outcome,
            outcome_approval=evidence.outcome_approval,
            activity_definitions=evidence.activity_definitions,
        )
        with pytest.raises(CurveGovernanceBlockedError):
            CurveService().generate_official_curve(
                evidence=evidence, **_draw_kwargs(meta)
            )

    def test_legacy_incomplete_diagnostics_artefact_raises(self, meta):
        evidence = _valid_evidence()
        legacy_diagnostics = _diagnostics_artefact(
            evidence.model_identity, legacy_incomplete=True
        )
        readiness = _approval_readiness(
            evidence.model_identity, evidence.threshold_policy, legacy_diagnostics
        )
        approval = _model_approval(
            evidence.model_identity, evidence.threshold_policy, readiness
        )
        evidence = CurveGovernanceEvidence(
            model_identity=evidence.model_identity,
            model_approval=approval,
            threshold_policy=evidence.threshold_policy,
            approval_readiness=readiness,
            diagnostics_artefact=legacy_diagnostics,
            outcome=evidence.outcome,
            outcome_approval=evidence.outcome_approval,
            activity_definitions=evidence.activity_definitions,
        )
        with pytest.raises(CurveGovernanceBlockedError, match="legacy/incomplete"):
            CurveService().generate_official_curve(
                evidence=evidence, **_draw_kwargs(meta)
            )

    def test_missing_outcome_approval_raises(self, meta):
        evidence = _valid_evidence()
        evidence = CurveGovernanceEvidence(
            model_identity=evidence.model_identity,
            model_approval=evidence.model_approval,
            threshold_policy=evidence.threshold_policy,
            approval_readiness=evidence.approval_readiness,
            diagnostics_artefact=evidence.diagnostics_artefact,
            outcome=evidence.outcome,
            outcome_approval=_outcome_approval(evidence.outcome, status="draft"),
            activity_definitions=evidence.activity_definitions,
        )
        with pytest.raises(OutcomeApprovalBlockedError):
            CurveService().generate_official_curve(
                evidence=evidence, **_draw_kwargs(meta)
            )

    def test_outcome_approval_missing_curve_publication_use_raises(self, meta):
        evidence = _valid_evidence()
        evidence = CurveGovernanceEvidence(
            model_identity=evidence.model_identity,
            model_approval=evidence.model_approval,
            threshold_policy=evidence.threshold_policy,
            approval_readiness=evidence.approval_readiness,
            diagnostics_artefact=evidence.diagnostics_artefact,
            outcome=evidence.outcome,
            outcome_approval=_outcome_approval(
                evidence.outcome, allowed_uses=("planning",)
            ),
            activity_definitions=evidence.activity_definitions,
        )
        with pytest.raises(OutcomeApprovalBlockedError):
            CurveService().generate_official_curve(
                evidence=evidence, **_draw_kwargs(meta)
            )

    def test_one_unapproved_activity_among_channels_blocks(self, meta):
        evidence = _valid_evidence()
        evidence = CurveGovernanceEvidence(
            model_identity=evidence.model_identity,
            model_approval=evidence.model_approval,
            threshold_policy=evidence.threshold_policy,
            approval_readiness=evidence.approval_readiness,
            diagnostics_artefact=evidence.diagnostics_artefact,
            outcome=evidence.outcome,
            outcome_approval=evidence.outcome_approval,
            activity_definitions=(_activity_definition(approval_status="draft"),),
        )
        with pytest.raises(CurveGovernanceBlockedError, match="activity governance"):
            CurveService().generate_official_curve(
                evidence=evidence, **_draw_kwargs(meta)
            )

    def test_passing_governance_mode_directly_is_rejected(self, meta):
        with pytest.raises(TypeError):
            CurveService().generate_official_curve(
                evidence=_valid_evidence(),
                governance_mode="official",
                **_draw_kwargs(meta),
            )


# ---------------------------------------------------------------------------
# Exploratory path
# ---------------------------------------------------------------------------


class TestExploratoryCurve:
    def test_no_governance_evidence_required(self, meta):
        result = CurveService().generate_exploratory_curve(**_draw_kwargs(meta))
        assert isinstance(result, ExploratoryCurveResult)
        assert result.is_official is False
        assert not result.draws.empty

    def test_exploratory_result_is_a_different_type_than_official(self, meta):
        exploratory = CurveService().generate_exploratory_curve(**_draw_kwargs(meta))
        assert not isinstance(exploratory, OfficialCurveArtifact)


# ---------------------------------------------------------------------------
# planning_eligible derivation
# ---------------------------------------------------------------------------


class TestPlanningEligible:
    def test_complete_support_is_eligible(self, meta):
        artifact = CurveService().generate_official_curve(
            evidence=_valid_evidence(), **_draw_kwargs(meta)
        )
        assert artifact.planning_eligible == {(MARKET, CHANNEL): True}

    def test_missing_support_is_not_eligible_and_not_fabricated(self, meta):
        artifact = CurveService().generate_official_curve(
            evidence=_valid_evidence(),
            **_draw_kwargs(meta, support={}),
        )
        assert artifact.planning_eligible == {(MARKET, CHANNEL): False}


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


class TestPersistenceRoundTrip:
    def test_export_then_import_reproduces_the_artifact(self, meta, tmp_path):
        artifact = CurveService().generate_official_curve(
            evidence=_valid_evidence(), **_draw_kwargs(meta)
        )
        directory = tmp_path / "artifact-1"
        export_curve_artifact(artifact, directory)
        reloaded = import_curve_artifact(directory)
        pd.testing.assert_frame_equal(reloaded.draws, artifact.draws)
        pd.testing.assert_frame_equal(reloaded.summaries, artifact.summaries)
        assert reloaded.manifest() == artifact.manifest()

    def test_newer_schema_version_on_import_raises_cleanly(self, meta, tmp_path):
        artifact = CurveService().generate_official_curve(
            evidence=_valid_evidence(), **_draw_kwargs(meta)
        )
        directory = tmp_path / "artifact-future"
        export_curve_artifact(artifact, directory)
        manifest_path = directory / "official_curve_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["schema_version"] = OFFICIAL_CURVE_ARTIFACT_SCHEMA_VERSION + 1
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="newer than"):
            import_curve_artifact(directory)

    def test_malformed_manifest_raises_not_silent(self, tmp_path):
        directory = tmp_path / "artifact-bad"
        directory.mkdir()
        (directory / "official_curve_manifest.json").write_text("{not valid json")
        (directory / "official_curve_draws.parquet").write_bytes(b"")
        (directory / "official_curve_summaries.parquet").write_bytes(b"")
        with pytest.raises(MalformedCurveArtifactError):
            import_curve_artifact(directory)

    def test_missing_files_raises_not_silent(self, tmp_path):
        directory = tmp_path / "artifact-empty"
        directory.mkdir()
        with pytest.raises(MalformedCurveArtifactError):
            import_curve_artifact(directory)

    def test_unknown_future_manifest_field_is_preserved_through_round_trip(
        self, meta, tmp_path
    ):
        artifact = CurveService().generate_official_curve(
            evidence=_valid_evidence(), **_draw_kwargs(meta)
        )
        directory = tmp_path / "artifact-extra-field"
        export_curve_artifact(artifact, directory)
        manifest_path = directory / "official_curve_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["a_future_field_this_code_does_not_know_about"] = "keep me"
        manifest_path.write_text(json.dumps(manifest))

        reloaded = import_curve_artifact(directory)
        assert (
            reloaded.extra_manifest_fields[
                "a_future_field_this_code_does_not_know_about"
            ]
            == "keep me"
        )
        # Re-exporting must round-trip the unknown field too, not drop it.
        second_directory = tmp_path / "artifact-extra-field-reexported"
        export_curve_artifact(reloaded, second_directory)
        second_manifest = json.loads(
            (second_directory / "official_curve_manifest.json").read_text()
        )
        assert (
            second_manifest["a_future_field_this_code_does_not_know_about"] == "keep me"
        )


# ---------------------------------------------------------------------------
# Bulk loader / audit
# ---------------------------------------------------------------------------


class TestLoadAllCurveArtifacts:
    def test_one_good_and_one_malformed_produces_one_artifact_and_one_audit_entry(
        self, meta, tmp_path
    ):
        artifact = CurveService().generate_official_curve(
            evidence=_valid_evidence(), **_draw_kwargs(meta)
        )
        export_curve_artifact(artifact, tmp_path / "good")
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir()
        (bad_dir / "official_curve_manifest.json").write_text("not json")
        (bad_dir / "official_curve_draws.parquet").write_bytes(b"")
        (bad_dir / "official_curve_summaries.parquet").write_bytes(b"")

        artifacts, audit = load_all_curve_artifacts(tmp_path)
        assert len(artifacts) == 1
        assert len(audit) == 1
        assert audit[0].path == bad_dir

    def test_missing_directory_returns_empty_not_an_error(self, tmp_path):
        artifacts, audit = load_all_curve_artifacts(tmp_path / "does-not-exist")
        assert artifacts == []
        assert audit == []
