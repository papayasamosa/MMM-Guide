"""Tests for the CurveService (PR 95A-95C, PR 96A / REQ-CURVE-001).

PR 95A/95B: official-governance validation — official status requires a
current, matching outcome approval for ``curve_publication`` (never
``model_fit``/``technical_reporting`` alone), the model approval chain must
match, and activity definitions cannot be omitted; official generation is
routed through the service with every reference context validated for
completeness, ``generate_canonical_curve_draws`` called in official mode
with activity definitions bound, and the strictest
``planning_support_eligible`` state preserved/enforced.

PR 96A: the governance chain is now structurally complete, not optional —
``threshold_policy``, ``approval_readiness``, ``diagnostics_artefact``, and
``activity_definitions`` are required fields, a model-bound-but-not-
policy-backed ``ModelApproval`` is rejected, and the diagnostics artefact
must match the readiness binding and current model identity. PR 96A also
adds ``CurveService.create_official_artifact`` — the one application
boundary for generating and persisting a new official curve artifact.
"""

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.approval import (
    ModelApproval,
    create_policy_backed_model_approval,
)
from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_definitions_fingerprint,
)
from ancestry_mmm.core.canonical_curves import CurveReferenceContext
from ancestry_mmm.core.curve_artifact import (
    CURVE_ARTIFACT_DRAWS_FILENAME,
    CURVE_ARTIFACT_METADATA_FILENAME,
    CURVE_ARTIFACT_SNAPSHOT_FIELDS,
    CURVE_ARTIFACT_SUMMARIES_FILENAME,
    CurveArtifact,
    CurveArtifactError,
    CurveArtifactMetadata,
    compute_curve_artifact_fingerprints,
    read_curve_artifact,
    verify_curve_artifact_fingerprints,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.media_costs import (
    FixedCostPerUnitMapping,
    MediaInputSpec,
    MediaInputSupport,
    MonetarySpendSupport,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    fingerprint_outcome_definition,
)
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
)
from ancestry_mmm.core.pathways import MediaOutcomePathway, resolve_pathway_masks
from ancestry_mmm.core.validation_policy import (
    ApprovalReadiness,
    ThresholdPolicy,
    ValidationEvidenceContext,
    ValidationGate,
    ValidationResult,
    evaluate_approval_readiness,
)
from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact
from ancestry_mmm.application.curve_service import (
    CurveArtifactAlreadyExistsError,
    CurveArtifactUnsafeIdError,
    CurveDiagnosticsArtefactError,
    CurveGovernanceError,
    CurveGovernanceMissingError,
    CurveModelApprovalError,
    CurvePlanningIneligibleError,
    CurvePublicationApprovalError,
    CurveReferenceContextIncompleteError,
    CurveService,
    CurveUseAuthorization,
    CurveUseNotAuthorizedError,
    OfficialArtifactCreationResult,
    OfficialCurveGovernance,
)

IDENTITY = {
    "model_run_id": "run-123",
    "data_fingerprint": "data-abc",
    "model_spec_fingerprint": "spec-def",
    "posterior_fingerprint": "post-ghi",
}

# Canonical-model fixtures (mirroring test_canonical_curves.py so the service
# tests exercise the real generation path).
_OUTCOMES = ["fh_new", "fh_returning", "dna_kit"]
_CHANNELS = ["TV", "DNA"]
_MARKETS = ["UK", "AU"]


def _broadcast(value, n_draw=4):
    value = np.asarray(value, dtype=float)
    return np.broadcast_to(value, (1, n_draw) + value.shape).copy()


def _trace(market_specific: bool = False):
    beta = np.array([[0.20, 0.10], [0.15, 0.00], [0.00, 0.30]])
    if market_specific:
        beta = np.stack([beta, beta * 0.7])
        hill_K = [[100.0, 80.0], [70.0, 50.0]]
    else:
        hill_K = [100.0, 80.0]
    posterior = {
        "decay_rate": _broadcast([0.5, 0.4]),
        "hill_K": _broadcast(hill_K),
        "hill_S": _broadcast([1.0, 1.2]),
        "beta": _broadcast(beta)
        * np.array([1.0, 1.1, 0.9, 1.2]).reshape((1, 4) + (1,) * beta.ndim),
        "active_cross_product_strength": _broadcast(
            [[0.0, 0.4], [0.0, 0.0], [0.0, 0.0]]
        ),
        "promo_coef": _broadcast([0.25, 0.10, 0.05]),
        "market_offset": _broadcast([[0.0, 0.0, 0.0], [0.3, -0.1, 0.2]]),
        "intercept": _broadcast([3.0, 2.5, 2.0]),
        "trend_coef": _broadcast([0.2, 0.1, 0.05]),
        "gamma_fourier": _broadcast([[0.15, -0.05, 0.1]]),
        "alpha": _broadcast([5.0, 5.0, 5.0]),
        "control_coef": _broadcast([0.12]),
    }
    coords = {
        "outcome": _OUTCOMES,
        "channel": _CHANNELS,
        "market": _MARKETS,
        "fourier": [0],
        "control": ["macro"],
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["market", "channel"] if market_specific else ["channel"],
        "hill_S": ["channel"],
        "beta": (
            ["market", "outcome", "channel"]
            if market_specific
            else ["outcome", "channel"]
        ),
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


def _contexts(counterfactual_axis_type: str = "model_input"):
    return {
        market: CurveReferenceContext(
            reference_context_id=f"{market}-recent",
            mode="recent_average",
            market=market,
            trend=0.5,
            fourier=(0.25,),
            promo={oid: 0.0 for oid in _OUTCOMES},
            controls={"macro": 0.4},
            outcome_controls={},
            other_channel_media_input={"TV": 20.0, "DNA": 30.0},
            counterfactual_value=0.0,
            counterfactual_axis_type=counterfactual_axis_type,
            reference_period_start="2026-04-01",
            reference_period_end="2026-06-30",
        )
        for market in _MARKETS
    }


def _meta():
    pathways = [
        MediaOutcomePathway(
            channel="TV",
            source_product="Family History",
            target_outcome_id="fh_new",
            component_type="direct",
            role="primary_direct",
            include_in_headline=True,
            headline_approval_status="approved",
            approved_by="reviewer",
            approved_at="2026-01-01",
        ),
        MediaOutcomePathway(
            channel="DNA",
            source_product="DNA",
            target_outcome_id="fh_new",
            component_type="direct",
            role="primary_direct",
            allow_cross_product_primary=True,
        ),
        MediaOutcomePathway(
            channel="DNA",
            source_product="DNA",
            target_outcome_id="fh_new",
            component_type="cross_product",
            role="active_cross_product",
            lag_type="fixed_weeks",
            lag_weeks=2,
            include_in_planning=True,
        ),
        MediaOutcomePathway(
            channel="TV",
            source_product="Family History",
            target_outcome_id="fh_returning",
            component_type="direct",
            role="primary_direct",
        ),
        MediaOutcomePathway(
            channel="DNA",
            source_product="DNA",
            target_outcome_id="dna_kit",
            component_type="direct",
            role="primary_direct",
        ),
    ]
    masks = resolve_pathway_masks(
        _OUTCOMES,
        _CHANNELS,
        pathways,
        dna_channel_idx=[1],
        dna_outcome_id="fh_new",
        direct_dna_outcome_ids=["fh_new", "dna_kit"],
        dna_lag_weeks=2,
    )
    return FHModelMeta(
        markets=_MARKETS,
        outcome_ids=_OUTCOMES,
        channels=_CHANNELS,
        dna_channels=["DNA"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="fh_new",
        dna_lag_weeks=2,
        unpooled_markets=[],
        control_names=["macro"],
        pathway_masks=masks,
        outcome_id_to_product={
            "fh_new": "Family History",
            "fh_returning": "Family History",
            "dna_kit": "DNA",
        },
        outcome_id_to_segment={
            "fh_new": "New",
            "fh_returning": "Returning",
            "dna_kit": "New",
        },
        outcome_id_to_metric_key={oid: "count" for oid in _OUTCOMES},
        outcome_id_to_unit={oid: "count" for oid in _OUTCOMES},
    )


def _specs():
    return {
        (market, channel): MediaInputSpec(
            market=market,
            channel=channel,
            column=f"{channel.lower()}_impressions",
            unit="thousand_impressions",
            unit_scale=1000.0,
        )
        for market in _MARKETS
        for channel in _CHANNELS
    }


def _media_support(specs):
    return {
        key: MediaInputSupport(
            market=key[0],
            channel=key[1],
            unit=spec.unit,
            current=50.0,
            observed_min=0.0,
            observed_max=100.0,
            planning_min=0.0,
            planning_max=150.0,
            current_method="last_4_week_average",
            source="model frame",
            provenance="test:X_media",
        )
        for key, spec in specs.items()
    }


def _generation_kwargs():
    return {
        "curve_type": "model_input",
        "media_input_specs": _specs(),
        "support_by_market_channel": _media_support(_specs()),
        "n_draws": 2,
        "spend_points": [0.0, 50.0],
    }


_LOCAL_CURRENCY_BY_MARKET = {"UK": "GBP", "AU": "AUD"}


def _cost_mappings():
    return {
        (market, channel): FixedCostPerUnitMapping(
            mapping_id=f"{market}-{channel}-cost",
            market=market,
            channel=channel,
            currency=_LOCAL_CURRENCY_BY_MARKET[market],
            cost_per_media_input=2.0,
            approval_status="approved",
            approved_by="reviewer",
            approved_at="2026-01-01",
            owner="Analytics",
            approval_note="approved for test",
            last_reviewed_at="2026-01-01",
        )
        for market in _MARKETS
        for channel in _CHANNELS
    }


def _monetary_support(cost_mappings):
    return {
        key: MonetarySpendSupport(
            market=key[0],
            channel=key[1],
            local_currency=mapping.currency,
            reporting_currency="GBP",
            current_local=100.0,
            observed_local_min=0.0,
            observed_local_max=200.0,
            planning_local_min=0.0,
            planning_local_max=300.0,
            fx_rate=1.0 if key[0] == "UK" else 0.5,
            current_method="last_4_week_average",
            source="model frame",
            provenance="test:X_spend",
            cost_mapping_id=mapping.mapping_id,
            cost_mapping_fingerprint="test-cost-mapping-fp",
            approved_by="reviewer",
            approved_at="2026-01-01",
            owner="Analytics",
            approval_note="approved for test",
        )
        for key, mapping in cost_mappings.items()
    }


def _monetary_generation_kwargs():
    cost_mappings = _cost_mappings()
    return {
        "curve_type": "monetary",
        "media_input_specs": _specs(),
        "support_by_market_channel": _monetary_support(cost_mappings),
        "cost_mappings": cost_mappings,
        "currency_by_market": {"UK": "GBP", "AU": "AUD"},
        "reporting_currency": "GBP",
        "currency_rates": {("AUD", "GBP"): 0.5},
        "fx_as_of_date": "2026-07-01",
        "fx_source": "test-fx-provider",
        "n_draws": 2,
        "spend_points": [0.0, 50.0],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _identity(**overrides: object) -> ModelIdentity:
    values: dict = dict(IDENTITY)
    values.update(overrides)
    return ModelIdentity(**values)


def _bare_model_approval(**overrides: object) -> ModelApproval:
    """A model-bound approval with no ``validation_policy_id`` (never
    policy-backed) - REQ-CURVE-001 Work package A rejects this for official
    status even though it passes the bare identity-matching check."""
    values: dict = {"approved_by": "Jane Analyst", **IDENTITY}
    values.update(overrides)
    return ModelApproval(**values)


def _gate(**overrides: object) -> ValidationGate:
    values: dict = {
        "name": "divergences",
        "description": "No divergences",
        "evaluator_id": "divergences",
        "expected_state": False,
    }
    values.update(overrides)
    return ValidationGate(**values)


def _policy(**overrides: object) -> ThresholdPolicy:
    values: dict = {
        "policy_id": "curve-policy",
        "version": "1.0",
        "scope": "all_models",
        "owner": "Test",
        "gates": [_gate()],
    }
    values.update(overrides)
    return ThresholdPolicy(**values)


def _diagnostics(
    identity: ModelIdentity | None = None, **overrides: object
) -> DiagnosticsArtefact:
    values: dict = {
        "artefact_id": "diag-1",
        "model_identity_fingerprint": (identity or _identity()).fingerprint(),
    }
    values.update(overrides)
    return DiagnosticsArtefact(**values)


def _readiness(
    *,
    identity: ModelIdentity | None = None,
    policy: ThresholdPolicy | None = None,
    diagnostics: DiagnosticsArtefact | None = None,
    gate_status: str = "pass",
    as_of: "datetime | None" = None,
) -> ApprovalReadiness:
    """A real, fingerprint-consistent ``ApprovalReadiness`` bound to
    ``identity``/``policy``/``diagnostics`` (each independently overridable
    so tests can construct a deliberately mismatched chain)."""
    identity = identity or _identity()
    policy = policy or _policy()
    diagnostics = diagnostics or _diagnostics(identity)
    gate = policy.gates[0]
    result = ValidationResult(
        gate_name=gate.name,
        status=gate_status,
        value=0,
        message="result",
        model_run_id=identity.model_run_id,
        data_fingerprint=identity.data_fingerprint,
        model_spec_fingerprint=identity.model_spec_fingerprint,
        posterior_fingerprint=identity.posterior_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_fingerprint=policy.fingerprint(),
        model_identity_fingerprint=identity.fingerprint(),
        gate_fingerprint=gate.fingerprint(),
        diagnostic_artefact_fingerprint=diagnostics.fingerprint(),
        artefact_id=diagnostics.artefact_id,
    )
    ctx = ValidationEvidenceContext(
        model_identity=identity,
        policy=policy,
        diagnostic_artefact_id=diagnostics.artefact_id,
        diagnostic_artefact_fingerprint=diagnostics.fingerprint(),
        model_type="shared",
        intended_use="model_approval",
    )
    return evaluate_approval_readiness(
        [result],
        policy,
        identity,
        diagnostic_artefact_id=diagnostics.artefact_id,
        diagnostic_artefact_fingerprint=diagnostics.fingerprint(),
        evidence_context=ctx,
        as_of=as_of,
    )


def _policy_backed_approval(
    *,
    identity: ModelIdentity | None = None,
    policy: ThresholdPolicy | None = None,
    readiness: ApprovalReadiness | None = None,
) -> ModelApproval:
    identity = identity or _identity()
    policy = policy or _policy()
    readiness = readiness or _readiness(identity=identity, policy=policy)
    return create_policy_backed_model_approval(
        approved_by="Jane Analyst",
        readiness=readiness,
        current_policy=policy,
        model_run_id=identity.model_run_id,
        data_fingerprint=identity.data_fingerprint,
        model_spec_fingerprint=identity.model_spec_fingerprint,
        posterior_fingerprint=identity.posterior_fingerprint,
    )


def _manual_policy_backed_approval(
    *, identity: ModelIdentity, policy: ThresholdPolicy, readiness: ApprovalReadiness
) -> ModelApproval:
    """Build a policy-backed ``ModelApproval`` with proof fields copied
    directly from ``policy``/``readiness``, bypassing
    ``create_policy_backed_model_approval``'s own stricter binding checks
    (which would refuse to construct an approval bound to an inactive
    policy, a not-ready readiness, or a readiness/model-identity mismatch).
    Needed to build deliberately mismatched governance-chain fixtures where
    the mismatch must be caught by ``require_matching_approval`` at
    *validation* time, not refused at fixture-construction time."""
    return ModelApproval(
        approved_by="Jane Analyst",
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


def _outcome() -> OutcomeDefinition:
    # outcome_id must be one of _meta()'s actual fitted outcome_ids
    # ("fh_new") - not an unrelated business-outcome id - since
    # generate_official_curve now binds official generation to exactly this
    # outcome_id within the fitted model (Corrective PR B2).
    return OutcomeDefinition(
        outcome_id="fh_new",
        product=FAMILY_HISTORY,
        segment="New",
        metric="GSA",
        metric_key=METRIC_KEY_FH_GSA,
        source_column="GSA_New",
        unit="GSA",
        aggregation_type="count",
        event_definition="A new subscriber",
        date_basis="event_date",
        cohort_or_attribution_basis="signup_cohort",
        completeness_or_maturity_policy="Fully mature after 12 weeks",
        exclusions="Excludes internal/test accounts",
        reconciliation_source="Finance report",
        business_owner="Analytics",
        definition_version="1.0",
    )


def _outcome_approval(
    allowed_uses: tuple = ("curve_publication",),
    status: str = "approved",
    expires_at: str | None = None,
    **overrides: object,
) -> OutcomeApproval:
    values: dict = {
        "approval_id": "apr-o1",
        "outcome_id": "fh_new",
        "definition_fingerprint": fingerprint_outcome_definition(_outcome()),
        "status": status,
        "allowed_uses": allowed_uses,
        "approved_by": "Jane Analyst",
        "approved_at": "2026-01-01",
        "expires_at": expires_at,
    }
    values.update(overrides)
    return OutcomeApproval(**values)


def _activity() -> ActivityDefinition:
    return ActivityDefinition(
        activity_id="tv-paid",
        channel="TV",
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        source="media plan",
        approval_status="approved",
        approved_by="reviewer",
        approved_at="2026-01-01",
    )


def _activities() -> list:
    """Approved activities covering every fitted (market, channel) model input."""
    return [
        _activity(),
        ActivityDefinition(
            activity_id="dna-paid",
            channel="DNA",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="media plan",
            approval_status="approved",
            approved_by="reviewer",
            approved_at="2026-01-01",
        ),
    ]


def _governance(**overrides: object) -> OfficialCurveGovernance:
    """A complete, real policy-backed governance chain (REQ-CURVE-001): the
    approval, its bound readiness, the policy it was evaluated against, and
    the diagnostics artefact the readiness references all agree with each
    other and with ``model_identity`` - this is the "valid complete
    policy-backed chain" fixture, not a bare model-bound approval."""
    policy = _policy()
    diagnostics = _diagnostics()
    readiness = _readiness(policy=policy, diagnostics=diagnostics)
    approval = _policy_backed_approval(policy=policy, readiness=readiness)
    values: dict = {
        "model_identity": _identity(),
        "model_approval": approval,
        "outcome_definition": _outcome(),
        "outcome_approval": _outcome_approval(),
        "threshold_policy": policy,
        "approval_readiness": readiness,
        "diagnostics_artefact": diagnostics,
        "activity_definitions": _activities(),
    }
    values.update(overrides)
    return OfficialCurveGovernance(**values)


# ---------------------------------------------------------------------------
# Official governance validation
# ---------------------------------------------------------------------------


class TestValidateOfficialGovernance:
    def test_complete_chain_passes(self):
        CurveService().validate_official_governance(_governance())  # must not raise

    def test_blocks_without_curve_publication(self):
        """Official status requires curve_publication (Work package A)."""
        governance = _governance(
            outcome_approval=_outcome_approval(allowed_uses=("model_fit",))
        )
        with pytest.raises(CurvePublicationApprovalError, match="curve_publication"):
            CurveService().validate_official_governance(governance)

    def test_blocks_technical_reporting_only(self):
        governance = _governance(
            outcome_approval=_outcome_approval(allowed_uses=("technical_reporting",))
        )
        with pytest.raises(CurvePublicationApprovalError):
            CurveService().validate_official_governance(governance)

    def test_blocks_expired_curve_publication_approval(self):
        governance = _governance(
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication",),
                expires_at="2026-06-01",
            )
        )
        with pytest.raises(CurvePublicationApprovalError, match="not active"):
            CurveService().validate_official_governance(governance)

    def test_blocks_rejected_outcome_approval(self):
        governance = _governance(
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication",), status="rejected"
            )
        )
        with pytest.raises(CurvePublicationApprovalError):
            CurveService().validate_official_governance(governance)

    def test_blocks_mismatched_model_approval(self):
        governance = _governance(
            model_approval=_policy_backed_approval(
                identity=_identity(posterior_fingerprint="wrong-post")
            )
        )
        with pytest.raises(CurveModelApprovalError, match="does not match"):
            CurveService().validate_official_governance(governance)

    def test_blocks_unbound_model_approval(self):
        governance = _governance(
            model_approval=ModelApproval(approved_by="Jane Analyst")
        )
        with pytest.raises(CurveModelApprovalError, match="predates"):
            CurveService().validate_official_governance(governance)

    def test_blocks_missing_activity_definitions(self):
        """Omitting an optional argument must never bypass an official gate."""
        governance = _governance(activity_definitions=None)
        with pytest.raises(CurveGovernanceMissingError, match="activity_definitions"):
            CurveService().validate_official_governance(governance)

    def test_blocks_unapproved_activity_governance(self):
        """Activity definitions present but not all approved must still block
        (distinct from the omitted-entirely case above)."""
        draft = dataclasses.replace(_activity(), approval_status="draft")
        governance = _governance(activity_definitions=[draft])
        with pytest.raises(CurveGovernanceMissingError, match="not approved"):
            CurveService().validate_official_governance(governance)

    # -- PR 96A: the four previously-optional governance fields are now
    # -- structurally required -----------------------------------------

    def test_blocks_missing_threshold_policy(self):
        governance = _governance(threshold_policy=None)
        with pytest.raises(CurveGovernanceMissingError, match="threshold_policy"):
            CurveService().validate_official_governance(governance)

    def test_blocks_missing_approval_readiness(self):
        governance = _governance(approval_readiness=None)
        with pytest.raises(CurveGovernanceMissingError, match="approval_readiness"):
            CurveService().validate_official_governance(governance)

    def test_blocks_missing_diagnostics_artefact(self):
        governance = _governance(diagnostics_artefact=None)
        with pytest.raises(CurveGovernanceMissingError, match="diagnostics_artefact"):
            CurveService().validate_official_governance(governance)

    def test_blocks_non_policy_backed_model_approval(self):
        """A model-bound approval with a blank validation_policy_id is never
        sufficient for official status, even though it matches the current
        model identity (the exact defect this PR closes)."""
        governance = _governance(model_approval=_bare_model_approval())
        with pytest.raises(CurveModelApprovalError, match="policy-backed"):
            CurveService().validate_official_governance(governance)

    def test_blocks_policy_backed_approval_missing_proof_field(self):
        base_governance = _governance()
        incomplete_approval = dataclasses.replace(
            base_governance.model_approval, validation_policy_version=""
        )
        governance = dataclasses.replace(
            base_governance, model_approval=incomplete_approval
        )
        with pytest.raises(
            CurveModelApprovalError, match="missing required evidence fields"
        ):
            CurveService().validate_official_governance(governance)

    def test_blocks_inactive_policy(self):
        """The policy was active when the approval/readiness were created but
        is not active now (expired) - creation-time and current-use active
        checks are the same gate here."""
        identity = _identity()
        diagnostics = _diagnostics(identity)
        expired_policy = _policy(expiry=datetime(2020, 1, 1, tzinfo=timezone.utc))
        # Evaluated back when the policy was still active; require_matching_
        # approval's is_active() check (real wall-clock "now") sees it as
        # expired regardless - historical evidence never rewrites current
        # authorization state.
        readiness = _readiness(
            identity=identity,
            policy=expired_policy,
            diagnostics=diagnostics,
            as_of=datetime(2019, 6, 1, tzinfo=timezone.utc),
        )
        approval = _manual_policy_backed_approval(
            identity=identity, policy=expired_policy, readiness=readiness
        )
        governance = _governance(
            model_approval=approval,
            threshold_policy=expired_policy,
            approval_readiness=readiness,
            diagnostics_artefact=diagnostics,
        )
        with pytest.raises(CurveModelApprovalError, match="no longer active"):
            CurveService().validate_official_governance(governance)

    def test_blocks_policy_fingerprint_differs(self):
        identity = _identity()
        diagnostics = _diagnostics(identity)
        original_policy = _policy(owner="Original Team")
        readiness = _readiness(
            identity=identity, policy=original_policy, diagnostics=diagnostics
        )
        approval = _manual_policy_backed_approval(
            identity=identity, policy=original_policy, readiness=readiness
        )
        # Same policy_id/version, different owner -> different fingerprint.
        different_policy = _policy(owner="Different Team")
        governance = _governance(
            model_approval=approval,
            threshold_policy=different_policy,
            approval_readiness=readiness,
            diagnostics_artefact=diagnostics,
        )
        with pytest.raises(CurveModelApprovalError, match="fingerprint"):
            CurveService().validate_official_governance(governance)

    def test_blocks_readiness_not_ready(self):
        identity = _identity()
        policy = _policy()
        diagnostics = _diagnostics(identity)
        readiness = _readiness(
            identity=identity,
            policy=policy,
            diagnostics=diagnostics,
            gate_status="fail",
        )
        assert not readiness.overall_ready
        approval = _manual_policy_backed_approval(
            identity=identity, policy=policy, readiness=readiness
        )
        governance = _governance(
            model_approval=approval,
            threshold_policy=policy,
            approval_readiness=readiness,
            diagnostics_artefact=diagnostics,
        )
        with pytest.raises(CurveModelApprovalError, match="not satisfied"):
            CurveService().validate_official_governance(governance)

    def test_blocks_readiness_model_identity_differs(self):
        identity = _identity()
        wrong_identity = _identity(posterior_fingerprint="wrong-post-for-readiness")
        policy = _policy()
        diagnostics = _diagnostics(identity)
        readiness = _readiness(
            identity=wrong_identity, policy=policy, diagnostics=diagnostics
        )
        approval = _manual_policy_backed_approval(
            identity=identity, policy=policy, readiness=readiness
        )
        governance = _governance(
            model_approval=approval,
            threshold_policy=policy,
            approval_readiness=readiness,
            diagnostics_artefact=diagnostics,
        )
        with pytest.raises(CurveModelApprovalError, match="model identity fingerprint"):
            CurveService().validate_official_governance(governance)

    def test_blocks_readiness_diagnostics_id_differs(self):
        identity = _identity()
        policy = _policy()
        diag_a = _diagnostics(identity, artefact_id="diag-a")
        diag_b = _diagnostics(identity, artefact_id="diag-b")
        readiness = _readiness(identity=identity, policy=policy, diagnostics=diag_a)
        approval = _manual_policy_backed_approval(
            identity=identity, policy=policy, readiness=readiness
        )
        governance = _governance(
            model_approval=approval,
            threshold_policy=policy,
            approval_readiness=readiness,
            diagnostics_artefact=diag_b,
        )
        with pytest.raises(
            CurveDiagnosticsArtefactError, match="diagnostic_artefact_id"
        ):
            CurveService().validate_official_governance(governance)

    def test_blocks_readiness_diagnostics_fingerprint_differs(self):
        identity = _identity()
        policy = _policy()
        diag_evaluated = _diagnostics(
            identity, artefact_id="diag-1", model_type="shared"
        )
        diag_supplied = _diagnostics(
            identity, artefact_id="diag-1", model_type="market_specific"
        )
        assert diag_evaluated.fingerprint() != diag_supplied.fingerprint()
        readiness = _readiness(
            identity=identity, policy=policy, diagnostics=diag_evaluated
        )
        approval = _manual_policy_backed_approval(
            identity=identity, policy=policy, readiness=readiness
        )
        governance = _governance(
            model_approval=approval,
            threshold_policy=policy,
            approval_readiness=readiness,
            diagnostics_artefact=diag_supplied,
        )
        with pytest.raises(
            CurveDiagnosticsArtefactError, match="diagnostic_artefact_fingerprint"
        ):
            CurveService().validate_official_governance(governance)

    def test_blocks_diagnostics_artefact_model_identity_differs(self):
        identity = _identity()
        wrong_identity = _identity(posterior_fingerprint="wrong-post-for-diagnostics")
        policy = _policy()
        diagnostics = _diagnostics(wrong_identity)
        readiness = _readiness(
            identity=identity, policy=policy, diagnostics=diagnostics
        )
        approval = _manual_policy_backed_approval(
            identity=identity, policy=policy, readiness=readiness
        )
        governance = _governance(
            model_approval=approval,
            threshold_policy=policy,
            approval_readiness=readiness,
            diagnostics_artefact=diagnostics,
        )
        with pytest.raises(CurveDiagnosticsArtefactError, match="model identity"):
            CurveService().validate_official_governance(governance)


# ---------------------------------------------------------------------------
# PR 95C: current-use revalidation (authorize_use)
# ---------------------------------------------------------------------------


def _artifact(planning_eligible=True, **metadata_overrides):
    """A CurveArtifact whose historical snapshot matches the test governance."""
    base = CurveArtifactMetadata(
        artifact_id="art-1",
        creation_timestamp="2026-07-01T00:00:00+00:00",
        model_identity_snapshot=dict(IDENTITY),
        approval_snapshot={"approval_id": "apr-1", "status": "approved"},
        outcome_definition_snapshot={
            "outcome_id": "fh_new",
            "definition_version": "1.0",
        },
        outcome_approval_snapshot={
            "approval_id": "apr-o1",
            "allowed_uses": ["curve_publication"],
        },
        activity_governance_snapshot={
            "activities": ["tv-paid", "dna-paid"],
            "fingerprint": activity_definitions_fingerprint(_activities()),
        },
    )
    metadata = dataclasses.replace(base, **metadata_overrides)
    if "fingerprints" not in metadata_overrides:
        metadata = dataclasses.replace(
            metadata, fingerprints=dict(compute_curve_artifact_fingerprints(metadata))
        )
    draws = pd.DataFrame(
        {
            "planning_support_eligible": [planning_eligible],
            "planning_blocked_reason": [
                "" if planning_eligible else "observed_support_missing"
            ],
        }
    )
    return CurveArtifact(metadata=metadata, draws=draws, summaries=pd.DataFrame())


class TestAuthorizeUse:
    @staticmethod
    def _governance_for_use(
        allowed_uses=("curve_publication", "headline_reporting"),
        **overrides,
    ):
        return _governance(
            outcome_approval=_outcome_approval(allowed_uses=allowed_uses),
            **overrides,
        )

    def test_authorizes_current_use(self):
        result = CurveService().authorize_use(
            _artifact(),
            "headline_reporting",
            current_governance=self._governance_for_use(),
        )
        assert isinstance(result, CurveUseAuthorization)
        assert result.authorized
        assert result.current_authorization_status == "authorized"
        assert result.requested_use_eligibility == "eligible"

    def test_authorizes_planning_use_when_eligible(self):
        governance = self._governance_for_use(
            allowed_uses=("curve_publication", "planning")
        )
        result = CurveService().authorize_use(
            _artifact(), "planning", current_governance=governance
        )
        assert result.authorized

    def test_blocks_when_artifact_model_is_stale(self):
        artifact = _artifact(
            model_identity_snapshot={**IDENTITY, "model_run_id": "run-OLD"}
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="stale"):
            CurveService().authorize_use(
                artifact,
                "headline_reporting",
                current_governance=self._governance_for_use(),
            )

    def test_blocks_when_current_model_approval_mismatched(self):
        governance = _governance(
            model_approval=_policy_backed_approval(
                identity=_identity(posterior_fingerprint="wrong-post")
            ),
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication", "headline_reporting")
            ),
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="does not match"):
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )

    def test_blocks_when_outcome_definition_changed(self):
        artifact = _artifact(
            outcome_definition_snapshot={
                "outcome_id": "fh_new",
                "definition_version": "0.9",
            }
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="changed since creation"):
            CurveService().authorize_use(
                artifact,
                "headline_reporting",
                current_governance=self._governance_for_use(),
            )

    def test_blocks_when_requested_use_not_approved(self):
        governance = self._governance_for_use(allowed_uses=("curve_publication",))
        with pytest.raises(CurveUseNotAuthorizedError, match="planning"):
            CurveService().authorize_use(
                _artifact(), "planning", current_governance=governance
            )

    def test_blocks_planning_when_support_missing(self):
        governance = self._governance_for_use(
            allowed_uses=("curve_publication", "planning")
        )
        with pytest.raises(CurvePlanningIneligibleError, match="planning"):
            CurveService().authorize_use(
                _artifact(planning_eligible=False),
                "planning",
                current_governance=governance,
            )

    def test_blocks_when_current_approval_not_policy_backed(self):
        """Current-use revalidation applies the same structural gate as
        generation time - a non-policy-backed current approval fails closed
        here too, not only at creation."""
        governance = _governance(
            model_approval=_bare_model_approval(),
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication", "headline_reporting")
            ),
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="policy-backed"):
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )

    def test_blocks_when_current_diagnostics_artefact_missing(self):
        governance = self._governance_for_use(diagnostics_artefact=None)
        with pytest.raises(CurveUseNotAuthorizedError, match="diagnostics_artefact"):
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )

    def test_blocks_when_activity_governance_unavailable(self):
        governance = _governance(
            activity_definitions=None,
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication", "headline_reporting")
            ),
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="cannot be resolved"):
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )

    def test_blocks_when_current_activities_unapproved(self):
        draft = dataclasses.replace(_activity(), approval_status="draft")
        governance = _governance(
            activity_definitions=[draft],
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication", "headline_reporting")
            ),
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="not approved"):
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )

    def test_blocks_when_predates_staleness_cutoff(self):
        with pytest.raises(CurveUseNotAuthorizedError, match="predates"):
            CurveService().authorize_use(
                _artifact(),
                "headline_reporting",
                current_governance=self._governance_for_use(),
                staleness_cutoff="2026-12-31T00:00:00+00:00",
            )

    def test_blocks_when_historical_integrity_tampered(self):
        artifact = _artifact()
        tampered = dataclasses.replace(
            artifact,
            metadata=dataclasses.replace(
                artifact.metadata,
                approval_snapshot={
                    **artifact.metadata.approval_snapshot,
                    "status": "rejected",
                },
            ),
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="integrity"):
            CurveService().authorize_use(
                tampered,
                "headline_reporting",
                current_governance=self._governance_for_use(),
            )

    def test_blocks_when_bad_staleness_cutoff(self):
        with pytest.raises(CurveUseNotAuthorizedError, match="Cannot resolve"):
            CurveService().authorize_use(
                _artifact(),
                "headline_reporting",
                current_governance=self._governance_for_use(),
                staleness_cutoff="not-a-date",
            )

    # -----------------------------------------------------------------
    # Corrective PR B1: curve_publication must be independently current,
    # not merely implied by the requested use also being approved.
    # -----------------------------------------------------------------

    def test_blocks_when_curve_publication_no_longer_current(self):
        # The replacement approval grants "planning" but has dropped
        # curve_publication entirely - official status itself is no longer
        # current, even though the requested use is technically approved.
        governance = _governance(
            outcome_approval=_outcome_approval(allowed_uses=("planning",))
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="curve_publication"):
            CurveService().authorize_use(
                _artifact(), "planning", current_governance=governance
            )

    def test_curve_publication_check_runs_even_when_requested_use_is_curve_publication(
        self,
    ):
        governance = _governance(
            outcome_approval=_outcome_approval(allowed_uses=("planning",))
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="curve_publication"):
            CurveService().authorize_use(
                _artifact(), "curve_publication", current_governance=governance
            )

    # -----------------------------------------------------------------
    # Corrective PR B3: the approval's scope must cover every distinct
    # market/product/segment the artifact's own rows actually span.
    # -----------------------------------------------------------------

    def _multi_market_artifact(self):
        base = _artifact()
        draws = pd.DataFrame(
            {
                "market": ["UK", "AU"],
                "product": ["Family History", "Family History"],
                "segment": ["New", "New"],
                "planning_support_eligible": [True, True],
                "planning_blocked_reason": ["", ""],
            }
        )
        return dataclasses.replace(base, draws=draws)

    def test_authorizes_when_approval_scope_covers_every_artifact_market(self):
        governance = self._governance_for_use(
            allowed_uses=("curve_publication", "headline_reporting")
        )  # unscoped approval covers every market
        result = CurveService().authorize_use(
            self._multi_market_artifact(),
            "headline_reporting",
            current_governance=governance,
        )
        assert result.authorized

    def test_blocks_when_approval_scope_excludes_one_of_the_artifacts_markets(self):
        governance = _governance(
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication", "headline_reporting"),
                market_scope=("UK",),
            )
        )
        with pytest.raises(CurveUseNotAuthorizedError):
            CurveService().authorize_use(
                self._multi_market_artifact(),
                "headline_reporting",
                current_governance=governance,
            )

    # -----------------------------------------------------------------
    # Corrective PR E1: current-use approval resolution is per-scope and
    # per-use against the *complete* candidate set (governance.
    # outcome_approvals), never one pre-selected record required to cover
    # the whole artifact.
    # -----------------------------------------------------------------

    def _multi_product_artifact(self):
        base = _artifact()
        draws = pd.DataFrame(
            {
                "market": ["UK", "UK"],
                "product": ["Family History", "DNA"],
                "segment": ["New", "New"],
                "planning_support_eligible": [True, True],
                "planning_blocked_reason": ["", ""],
            }
        )
        return dataclasses.replace(base, draws=draws)

    def test_one_broad_approval_authorises_every_scope(self):
        broad = _outcome_approval(
            allowed_uses=("curve_publication", "headline_reporting")
        )
        governance = _governance(outcome_approval=broad, outcome_approvals=[broad])
        result = CurveService().authorize_use(
            self._multi_market_artifact(),
            "headline_reporting",
            current_governance=governance,
        )
        assert result.authorized

    def test_separate_scoped_approvals_jointly_authorise_a_multi_market_artifact(self):
        """E1.1: a UK approval and a separate AU approval must each be able
        to authorize their own scope - one record is never required to
        cover the whole multi-market artifact."""
        uk = _outcome_approval(
            approval_id="apr-uk",
            allowed_uses=("curve_publication", "headline_reporting"),
            market_scope=("UK",),
        )
        au = _outcome_approval(
            approval_id="apr-au",
            allowed_uses=("curve_publication", "headline_reporting"),
            market_scope=("AU",),
        )
        governance = _governance(outcome_approval=uk, outcome_approvals=[uk, au])
        result = CurveService().authorize_use(
            self._multi_market_artifact(),
            "headline_reporting",
            current_governance=governance,
        )
        assert result.authorized

    def test_uk_only_approval_cannot_authorise_au(self):
        uk_only = _outcome_approval(
            allowed_uses=("curve_publication", "headline_reporting"),
            market_scope=("UK",),
        )
        governance = _governance(outcome_approval=uk_only, outcome_approvals=[uk_only])
        with pytest.raises(CurveUseNotAuthorizedError):
            CurveService().authorize_use(
                self._multi_market_artifact(),
                "headline_reporting",
                current_governance=governance,
            )

    def test_newer_expired_approval_does_not_hide_an_older_active_approval(self):
        """E1.2: an approval that was approved more recently but has
        already lapsed must not shadow an older approval that is still
        active."""
        older_active = _outcome_approval(
            approval_id="apr-older-active",
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_at="2026-01-01",
        )
        newer_expired = _outcome_approval(
            approval_id="apr-newer-expired",
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_at="2026-02-01",
            expires_at="2026-03-01",
        )
        governance = _governance(
            outcome_approval=newer_expired,
            outcome_approvals=[older_active, newer_expired],
        )
        result = CurveService().authorize_use(
            _artifact(), "headline_reporting", current_governance=governance
        )
        assert result.authorized

    def test_newer_planning_only_approval_does_not_hide_a_valid_curve_publication_approval(
        self,
    ):
        curve_pub = _outcome_approval(
            approval_id="apr-curve-pub",
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_at="2026-01-01",
        )
        newer_planning_only = _outcome_approval(
            approval_id="apr-newer-planning",
            allowed_uses=("planning",),
            approved_at="2026-06-01",
        )
        governance = _governance(
            outcome_approval=newer_planning_only,
            outcome_approvals=[curve_pub, newer_planning_only],
        )
        result = CurveService().authorize_use(
            _artifact(), "headline_reporting", current_governance=governance
        )
        assert result.authorized

    def test_separate_curve_publication_and_planning_records_jointly_authorise_planning(
        self,
    ):
        curve_pub_only = _outcome_approval(
            approval_id="apr-curve-pub-only", allowed_uses=("curve_publication",)
        )
        planning_only = _outcome_approval(
            approval_id="apr-planning-only", allowed_uses=("planning",)
        )
        governance = _governance(
            outcome_approval=curve_pub_only,
            outcome_approvals=[curve_pub_only, planning_only],
        )
        result = CurveService().authorize_use(
            _artifact(), "planning", current_governance=governance
        )
        assert result.authorized

    def test_reporting_approval_cannot_authorise_planning(self):
        reporting_only = _outcome_approval(
            allowed_uses=("curve_publication", "headline_reporting")
        )
        governance = _governance(
            outcome_approval=reporting_only, outcome_approvals=[reporting_only]
        )
        with pytest.raises(CurveUseNotAuthorizedError):
            CurveService().authorize_use(
                _artifact(), "planning", current_governance=governance
            )

    def test_stale_definition_fingerprint_cannot_authorise_any_use(self):
        stale_fingerprint = _outcome_approval(
            allowed_uses=("curve_publication", "headline_reporting"),
            definition_fingerprint="not-the-current-fingerprint",
        )
        governance = _governance(
            outcome_approval=stale_fingerprint,
            outcome_approvals=[stale_fingerprint],
        )
        with pytest.raises(CurveUseNotAuthorizedError):
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )

    def test_approval_outside_effective_period_cannot_authorise_use(self):
        future_dated = _outcome_approval(
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_at="2099-01-01",
        )
        governance = _governance(
            outcome_approval=future_dated, outcome_approvals=[future_dated]
        )
        with pytest.raises(CurveUseNotAuthorizedError):
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )

    def test_product_and_segment_scope_are_matched(self):
        fh_only = _outcome_approval(
            approval_id="apr-fh",
            allowed_uses=("curve_publication", "headline_reporting"),
            product_scope=("Family History",),
        )
        governance = _governance(outcome_approval=fh_only, outcome_approvals=[fh_only])
        with pytest.raises(CurveUseNotAuthorizedError):
            CurveService().authorize_use(
                self._multi_product_artifact(),
                "headline_reporting",
                current_governance=governance,
            )
        fh_and_dna = _outcome_approval(
            approval_id="apr-fh-dna",
            allowed_uses=("curve_publication", "headline_reporting"),
            product_scope=("Family History", "DNA"),
        )
        governance_both = _governance(
            outcome_approval=fh_and_dna, outcome_approvals=[fh_and_dna]
        )
        result = CurveService().authorize_use(
            self._multi_product_artifact(),
            "headline_reporting",
            current_governance=governance_both,
        )
        assert result.authorized

    def test_resolve_current_governance_and_authorize_use_share_the_same_per_scope_path(
        self,
    ):
        """Both the Curve Bank and Project Export pages resolve governance
        via resolve_current_governance() then call authorize_use() - proving
        the separate-scoped-approvals case works through that exact shared
        path (not only when a test constructs OfficialCurveGovernance
        directly) demonstrates display and export share the same matching
        path."""
        policy = _policy()
        diagnostics = _diagnostics()
        readiness = _readiness(policy=policy, diagnostics=diagnostics)
        model_approval = _policy_backed_approval(policy=policy, readiness=readiness)
        uk = _outcome_approval(
            approval_id="apr-uk",
            allowed_uses=("curve_publication", "headline_reporting"),
            market_scope=("UK",),
        )
        au = _outcome_approval(
            approval_id="apr-au",
            allowed_uses=("curve_publication", "headline_reporting"),
            market_scope=("AU",),
        )
        governance = CurveService().resolve_current_governance(
            self._multi_market_artifact(),
            current_identity=dict(IDENTITY),
            approval_dict=model_approval.to_dict(),
            current_policy=policy,
            current_readiness=readiness,
            current_diagnostics_artefact=diagnostics,
            activity_definitions=_activities(),
            outcome_definitions=[_outcome()],
            outcome_approvals=[uk, au],
        )
        assert isinstance(governance, OfficialCurveGovernance)
        result = CurveService().authorize_use(
            self._multi_market_artifact(),
            "headline_reporting",
            current_governance=governance,
        )
        assert result.authorized

    def test_no_matching_approval_fails_closed_with_an_actionable_reason(self):
        unrelated_use = _outcome_approval(allowed_uses=("model_fit",))
        governance = _governance(
            outcome_approval=unrelated_use, outcome_approvals=[unrelated_use]
        )
        with pytest.raises(CurveUseNotAuthorizedError) as excinfo:
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )
        message = str(excinfo.value)
        assert "fh_new" in message
        assert "curve_publication" in message

    # -----------------------------------------------------------------
    # Corrective PR B4: the supplied activities must be the artifact's OWN
    # activities, not merely approved activities of any kind.
    # -----------------------------------------------------------------

    def test_blocks_when_current_activities_are_unrelated_to_the_artifact(self):
        # Both approved, but a different activity than the artifact was
        # actually generated against ("tv-paid"/"dna-paid" per _artifact()'s
        # activity_governance_snapshot).
        unrelated = ActivityDefinition(
            activity_id="radio-paid",
            channel="Radio",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="media plan",
            approval_status="approved",
            approved_by="reviewer",
            approved_at="2026-01-01",
        )
        governance = _governance(
            activity_definitions=[unrelated],
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication", "headline_reporting")
            ),
        )
        with pytest.raises(CurveUseNotAuthorizedError, match="activity"):
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )

    # -----------------------------------------------------------------
    # Corrective PR B7: staleness_cutoff comparison must never raise an
    # uncaught TypeError for a naive/aware timestamp mismatch.
    # -----------------------------------------------------------------

    def test_naive_staleness_cutoff_against_aware_creation_timestamp_does_not_crash(
        self,
    ):
        # _artifact()'s creation_timestamp is "2026-07-01T00:00:00+00:00"
        # (aware); a naive cutoff must still compare cleanly (normalised to
        # UTC) and raise the documented error, never a bare TypeError.
        with pytest.raises(CurveUseNotAuthorizedError, match="predates"):
            CurveService().authorize_use(
                _artifact(),
                "headline_reporting",
                current_governance=self._governance_for_use(),
                staleness_cutoff="2026-12-31T00:00:00",
            )

    def test_naive_staleness_cutoff_before_creation_authorizes(self):
        result = CurveService().authorize_use(
            _artifact(),
            "headline_reporting",
            current_governance=self._governance_for_use(),
            staleness_cutoff="2026-01-01T00:00:00",
        )
        assert result.authorized


# ---------------------------------------------------------------------------
# PR 96B: resolve_current_governance - the shared resolution path used by
# both Results / Curve Bank and Project Export's report/Excel exposure.
# ---------------------------------------------------------------------------


class TestResolveCurrentGovernance:
    @staticmethod
    def _resolve(artifact, **overrides):
        policy = _policy()
        diagnostics = _diagnostics()
        readiness = _readiness(policy=policy, diagnostics=diagnostics)
        approval = _policy_backed_approval(policy=policy, readiness=readiness)
        kwargs: dict = dict(
            current_identity=dict(IDENTITY),
            approval_dict=approval.to_dict(),
            current_policy=policy,
            current_readiness=readiness,
            current_diagnostics_artefact=diagnostics,
            activity_definitions=_activities(),
            outcome_definitions=[_outcome()],
            outcome_approvals=[
                _outcome_approval(
                    allowed_uses=("curve_publication", "headline_reporting")
                )
            ],
        )
        kwargs.update(overrides)
        return CurveService().resolve_current_governance(artifact, **kwargs)

    def test_complete_evidence_resolves_a_usable_governance(self):
        governance = self._resolve(_artifact())
        assert isinstance(governance, OfficialCurveGovernance)
        # The resolved governance must actually satisfy authorize_use, not
        # merely construct without error.
        authorization = CurveService().authorize_use(
            _artifact(), "headline_reporting", current_governance=governance
        )
        assert authorization.authorized

    def test_missing_current_identity_returns_none(self):
        assert self._resolve(_artifact(), current_identity=None) is None

    def test_missing_approval_dict_returns_none(self):
        assert self._resolve(_artifact(), approval_dict=None) is None

    def test_no_outcome_definitions_returns_none(self):
        assert self._resolve(_artifact(), outcome_definitions=[]) is None

    def test_no_matching_outcome_definition_returns_none(self):
        other_outcome = dataclasses.replace(_outcome(), outcome_id="other_outcome")
        assert self._resolve(_artifact(), outcome_definitions=[other_outcome]) is None

    def test_no_matching_outcome_approval_returns_none(self):
        assert self._resolve(_artifact(), outcome_approvals=[]) is None

    def test_expired_candidate_alone_returns_none(self):
        """Corrective PR E1: the broad existence check now also requires
        current validity, not merely status == 'approved' - a lapsed-only
        candidate must not make resolve_current_governance construct a
        governance object at all."""
        expired = _outcome_approval(approved_at="2026-01-01", expires_at="2026-02-01")
        assert self._resolve(_artifact(), outcome_approvals=[expired]) is None

    def test_newer_expired_candidate_does_not_prevent_resolution_when_an_older_active_one_exists(
        self,
    ):
        """Corrective PR E1 (E1.2): resolve_current_governance must still
        construct a governance object - carrying the *complete* candidate
        set - when an older approval is genuinely active, even though a
        newer, already-expired candidate for the same outcome also exists."""
        older_active = _outcome_approval(
            approval_id="apr-older-active",
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_at="2026-01-01",
        )
        newer_expired = _outcome_approval(
            approval_id="apr-newer-expired",
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_at="2026-02-01",
            expires_at="2026-03-01",
        )
        governance = self._resolve(
            _artifact(), outcome_approvals=[older_active, newer_expired]
        )
        assert isinstance(governance, OfficialCurveGovernance)
        assert list(governance.outcome_approvals) == [older_active, newer_expired]
        # The complete candidate set (not just the resolver's single pick)
        # is what authorize_use actually matches against.
        authorization = CurveService().authorize_use(
            _artifact(), "headline_reporting", current_governance=governance
        )
        assert authorization.authorized

    def test_selects_the_currently_valid_approval_not_merely_the_first_in_list_order(
        self,
    ):
        """Corrective PR D4: a stale/rejected approval that happens to
        iterate before a later valid one must never be picked over it - a
        naive first-match-by-outcome_id scan could wrongly resolve to (and
        downstream, wrongly block on) an approval that is not actually
        current, even though a valid approval for the same outcome exists."""
        stale = _outcome_approval(
            approval_id="apr-stale",
            status="rejected",
            approved_at="2025-01-01",
        )
        valid = _outcome_approval(
            approval_id="apr-valid",
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_at="2026-06-01",
        )
        governance = self._resolve(_artifact(), outcome_approvals=[stale, valid])
        assert isinstance(governance, OfficialCurveGovernance)
        assert governance.outcome_approval.approval_id == "apr-valid"

    def test_selects_the_latest_approved_at_among_multiple_valid_approvals(self):
        """Deterministic tiebreak: among several equally-valid (approved,
        fingerprint-matching) candidates, the latest approved_at wins -
        matching find_matching_outcome_approval's own tiebreak."""
        older = _outcome_approval(
            approval_id="apr-older",
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_at="2026-01-01",
        )
        newer = _outcome_approval(
            approval_id="apr-newer",
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_at="2026-06-01",
        )
        governance = self._resolve(_artifact(), outcome_approvals=[newer, older])
        assert governance.outcome_approval.approval_id == "apr-newer"

    def test_ignores_an_approval_for_a_stale_outcome_definition_fingerprint(self):
        """An approval whose definition_fingerprint no longer matches the
        current outcome definition must never be selected, even when it is
        the only candidate sharing the outcome_id."""
        stale_fingerprint_approval = _outcome_approval(
            definition_fingerprint="not-the-current-fingerprint",
        )
        assert (
            self._resolve(_artifact(), outcome_approvals=[stale_fingerprint_approval])
            is None
        )

    def test_missing_policy_readiness_diagnostics_still_resolves_but_fails_authorize_use(
        self,
    ):
        """Deliberately-incomplete evidence (no policy/readiness/diagnostics)
        does not collapse into the same generic "cannot be resolved" message
        as missing identity/approval/outcome - it resolves to a governance
        object so authorize_use raises the specific
        CurveGovernanceMissingError (e.g. "require threshold_policy")."""
        governance = self._resolve(
            _artifact(),
            current_policy=None,
            current_readiness=None,
            current_diagnostics_artefact=None,
        )
        assert isinstance(governance, OfficialCurveGovernance)
        with pytest.raises(CurveUseNotAuthorizedError, match="threshold_policy"):
            CurveService().authorize_use(
                _artifact(), "headline_reporting", current_governance=governance
            )


# ---------------------------------------------------------------------------
# PR 95B: official generation through the service
# ---------------------------------------------------------------------------


class TestGenerateOfficialCurve:
    def test_generates_model_input_official_curve(self):
        service = CurveService()
        draws = service.generate_official_curve(
            _governance(),
            meta=_meta(),
            trace=_trace(),
            reference_contexts=_contexts(),
            **_generation_kwargs(),
        )
        assert not draws.empty
        assert draws["curve_type"].eq("model_input").all()
        assert draws["planning_support_eligible"].notna().all()

    def test_blocks_incomplete_reference_context(self):
        contexts = _contexts()
        bad = dataclasses.replace(contexts["UK"], promo={})
        with pytest.raises(CurveReferenceContextIncompleteError, match="UK-recent"):
            CurveService().generate_official_curve(
                _governance(),
                meta=_meta(),
                trace=_trace(),
                reference_contexts={"UK": bad},
                **_generation_kwargs(),
            )

    def test_blocks_without_curve_publication_before_generation(self):
        governance = _governance(
            outcome_approval=_outcome_approval(allowed_uses=("model_fit",))
        )
        with pytest.raises(CurvePublicationApprovalError, match="curve_publication"):
            CurveService().generate_official_curve(
                governance,
                meta=_meta(),
                trace=_trace(),
                reference_contexts=_contexts(),
                **_generation_kwargs(),
            )

    def test_forces_official_mode_and_binds_activity_definitions(self, monkeypatch):
        captured = {}

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return pd.DataFrame(
                {
                    "planning_support_eligible": [True],
                    "planning_blocked_reason": [""],
                }
            )

        monkeypatch.setattr(
            "ancestry_mmm.application.curve_service.generate_canonical_curve_draws",
            fake_generate,
        )
        governance = _governance()
        CurveService().generate_official_curve(
            governance,
            meta=_meta(),
            trace=_trace(),
            reference_contexts=_contexts(),
            governance_mode="exploratory",  # must be overridden to official
            activity_definitions=None,  # must be overridden with governance's
            **_generation_kwargs(),
        )
        assert captured["governance_mode"] == "official"
        assert captured["activity_definitions"] is governance.activity_definitions
        assert captured["model_run_id"] == "run-123"

    # -----------------------------------------------------------------
    # Corrective PR B2: bind approval to each generated outcome - one
    # official artifact represents exactly the one approved outcome, never
    # every outcome the jointly-fitted model happens to also cover.
    # -----------------------------------------------------------------

    def test_restricts_generated_draws_to_the_approved_outcome_only(self):
        # _meta()'s fitted model covers three outcomes (fh_new, fh_returning,
        # dna_kit); _governance()'s single approval is for "fh_new" only.
        draws = CurveService().generate_official_curve(
            _governance(),
            meta=_meta(),
            trace=_trace(),
            reference_contexts=_contexts(),
            **_generation_kwargs(),
        )
        assert set(draws["outcome_id"]) == {"fh_new"}

    def test_blocks_when_approved_outcome_is_not_in_the_fitted_model(self):
        missing_outcome = dataclasses.replace(
            _outcome(), outcome_id="not-in-fitted-model"
        )
        governance = _governance(
            outcome_definition=missing_outcome,
            outcome_approval=_outcome_approval(
                outcome_id="not-in-fitted-model",
                definition_fingerprint=fingerprint_outcome_definition(missing_outcome),
            ),
        )
        with pytest.raises(CurveGovernanceMissingError, match="not-in-fitted-model"):
            CurveService().generate_official_curve(
                governance,
                meta=_meta(),
                trace=_trace(),
                reference_contexts=_contexts(),
                **_generation_kwargs(),
            )

    def test_generate_official_curve_no_longer_accepts_a_params_override(self):
        # Corrective PR B, finding 10: the params override was removed
        # entirely - official generation always derives parameters fresh
        # from trace/meta, since generate_canonical_curve_draws ignores any
        # caller-supplied params anyway (it independently re-extracts its
        # own per draw), so a validation-only override could only
        # desynchronise completeness-checking from what is actually
        # generated.
        with pytest.raises(TypeError):
            CurveService().generate_official_curve(
                _governance(),
                meta=_meta(),
                trace=_trace(),
                reference_contexts=_contexts(),
                params=object(),
                **_generation_kwargs(),
            )


# ---------------------------------------------------------------------------
# PR 95B: planning-support state and enforcement
# ---------------------------------------------------------------------------


class TestPlanningSupportState:
    @staticmethod
    def _draws(eligible, reason=""):
        return pd.DataFrame(
            {
                "planning_support_eligible": [eligible],
                "planning_blocked_reason": [reason],
            }
        )

    def test_all_eligible(self):
        assert CurveService().planning_support_state(self._draws(True)) == (True, "")

    def test_ineligible_returns_strictest_state(self):
        draws = pd.DataFrame(
            {
                "planning_support_eligible": [True, False],
                "planning_blocked_reason": ["", "observed_support_missing"],
            }
        )
        assert CurveService().planning_support_state(draws) == (
            False,
            "observed_support_missing",
        )

    def test_missing_field_raises(self):
        with pytest.raises(CurveGovernanceError, match="planning_support_eligible"):
            CurveService().planning_support_state(pd.DataFrame({"a": [1]}))

    def test_ineligible_row_with_empty_reason_raises(self):
        with pytest.raises(CurvePlanningIneligibleError, match="non-empty"):
            CurveService().planning_support_state(self._draws(False))


class TestEnforcePlanningSupport:
    @staticmethod
    def _draws(eligible):
        return pd.DataFrame(
            {
                "planning_support_eligible": [eligible],
                "planning_blocked_reason": [
                    "" if eligible else "observed_support_missing"
                ],
            }
        )

    def test_planning_use_blocked_when_ineligible(self):
        with pytest.raises(CurvePlanningIneligibleError, match="planning"):
            CurveService().enforce_planning_support(
                self._draws(False), requested_use="planning"
            )

    def test_optimisation_use_blocked_when_ineligible(self):
        with pytest.raises(CurvePlanningIneligibleError, match="optimisation"):
            CurveService().enforce_planning_support(
                self._draws(False), requested_use="optimisation"
            )

    def test_planning_use_passes_when_eligible(self):
        assert CurveService().enforce_planning_support(
            self._draws(True), requested_use="planning"
        )

    def test_reporting_use_not_gated_on_planning_flag(self):
        assert not CurveService().enforce_planning_support(
            self._draws(False), requested_use="reporting"
        )


# ---------------------------------------------------------------------------
# PR 95B: reference-context completeness wrapping in the service
# ---------------------------------------------------------------------------


class TestValidateReferenceContextsWrapping:
    def test_incomplete_context_is_wrapped(self):
        meta = SimpleNamespace(markets=["UK"], channels=["TV", "DNA"])
        params = SimpleNamespace(
            promo_coef={"fh_new": 0.1},
            control_coef={"macro": 0.1},
            outcome_control_coef={},
            gamma_fourier={"fh_new": np.array([0.1])},
        )
        context = CurveReferenceContext(
            reference_context_id="ctx-1",
            mode="recent_average",
            market="FR",  # wrong market -> incomplete
            trend=0.5,
            fourier=(0.25,),
            promo={},
            controls={},
            outcome_controls={},
            other_channel_media_input={"TV": 1.0, "DNA": 1.0},
        )
        with pytest.raises(CurveReferenceContextIncompleteError, match="ctx-1"):
            CurveService().validate_reference_contexts({"ctx-1": context}, meta, params)

    def test_complete_contexts_pass(self):
        from ancestry_mmm.core.predict import extract_posterior_params

        meta = _meta()
        params = extract_posterior_params(_trace(), meta)
        CurveService().validate_reference_contexts(_contexts(), meta, params)


# ---------------------------------------------------------------------------
# PR 96A: official artifact creation and persistence
# (CurveService.create_official_artifact, Work packages B/C)
# ---------------------------------------------------------------------------


class TestCreateOfficialArtifact:
    @staticmethod
    def _create(
        tmp_path,
        *,
        artifact_id: str = "art-1",
        model_type: str = "shared",
        governance: OfficialCurveGovernance | None = None,
        **overrides,
    ) -> OfficialArtifactCreationResult:
        kwargs: dict = dict(
            meta=_meta(),
            trace=_trace(model_type == "market_specific"),
            reference_contexts=_contexts(),
            model_type=model_type,
            **_generation_kwargs(),
        )
        kwargs.update(overrides)
        return CurveService().create_official_artifact(
            governance or _governance(),
            artifact_id=artifact_id,
            store_dir=tmp_path,
            **kwargs,
        )

    def test_creates_shared_model_artifact(self, tmp_path):
        result = self._create(tmp_path, artifact_id="art-shared")
        assert isinstance(result, OfficialArtifactCreationResult)
        assert result.artifact_id == "art-shared"
        assert result.directory == tmp_path / "art-shared"
        assert isinstance(result.artifact, CurveArtifact)

    def test_creates_market_specific_artifact(self, tmp_path):
        result = self._create(
            tmp_path, artifact_id="art-market", model_type="market_specific"
        )
        assert not result.artifact.draws.empty

    def test_model_input_curve_artifact(self, tmp_path):
        result = self._create(tmp_path, artifact_id="art-model-input")
        assert result.artifact.draws["curve_type"].eq("model_input").all()

    def test_monetary_curve_artifact_with_governed_mapping_and_currency(self, tmp_path):
        result = self._create(
            tmp_path,
            artifact_id="art-monetary",
            reference_contexts=_contexts(counterfactual_axis_type="monetary"),
            **_monetary_generation_kwargs(),
        )
        assert result.artifact.draws["curve_type"].eq("monetary").all()
        assert result.artifact.draws["cost_mapping_id"].notna().all()
        assert result.artifact.draws["reporting_currency"].eq("GBP").all()
        assert result.artifact.draws["fx_source"].eq("test-fx-provider").all()
        cost_currency_rows = result.artifact.metadata.cost_currency_snapshot["rows"]
        assert all(row["fx_source"] == "test-fx-provider" for row in cost_currency_rows)

    def test_generated_artifact_has_nonempty_draws_and_summaries(self, tmp_path):
        result = self._create(tmp_path, artifact_id="art-nonempty")
        assert not result.artifact.draws.empty
        assert not result.artifact.summaries.empty

    def test_metadata_contains_every_required_snapshot(self, tmp_path):
        result = self._create(tmp_path, artifact_id="art-snapshots")
        metadata = result.artifact.metadata
        for name in CURVE_ARTIFACT_SNAPSHOT_FIELDS:
            assert getattr(metadata, name), f"{name} snapshot must be non-empty"

    def test_metadata_fingerprints_verify(self, tmp_path):
        result = self._create(tmp_path, artifact_id="art-fp")
        verify_curve_artifact_fingerprints(result.artifact.metadata)  # must not raise

    def test_written_artifact_reads_back_identically(self, tmp_path):
        result = self._create(tmp_path, artifact_id="art-refresh")
        reloaded = read_curve_artifact(result.directory)  # re-verifies fingerprints
        assert reloaded.metadata == result.artifact.metadata
        pd.testing.assert_frame_equal(reloaded.draws, result.artifact.draws)
        pd.testing.assert_frame_equal(reloaded.summaries, result.artifact.summaries)

    def test_returned_artifact_id_and_paths_match_final_storage(self, tmp_path):
        result = self._create(tmp_path, artifact_id="art-paths")
        assert result.artifact_id == "art-paths"
        assert result.directory == tmp_path / "art-paths"
        assert (
            result.metadata_path == result.directory / CURVE_ARTIFACT_METADATA_FILENAME
        )
        assert result.draws_path == result.directory / CURVE_ARTIFACT_DRAWS_FILENAME
        assert (
            result.summaries_path
            == result.directory / CURVE_ARTIFACT_SUMMARIES_FILENAME
        )
        assert result.metadata_path.exists()
        assert result.draws_path.exists()
        assert result.summaries_path.exists()

    # -----------------------------------------------------------------
    # Corrective PR E1 follow-up (PR #113 review): generation-time
    # validation must be as scope-aware as authorize_use, not just the
    # single, unscoped governance.outcome_approval - and every approval
    # that actually authorized a generated scope must be captured in the
    # artifact's own immutable creation evidence.
    # -----------------------------------------------------------------

    def test_blocks_persistence_when_a_generated_scope_lacks_curve_publication_approval(
        self, tmp_path
    ):
        """A UK-only approval must not let a UK+AU artifact actually be
        generated and persisted - generation-time validation was
        previously scope-blind (only the single, unscoped
        governance.outcome_approval was checked, and matches_scope treats
        an omitted dimension as unrestricted)."""
        uk_only = _outcome_approval(
            allowed_uses=("curve_publication",), market_scope=("UK",)
        )
        governance = _governance(outcome_approval=uk_only, outcome_approvals=[uk_only])
        with pytest.raises(CurvePublicationApprovalError, match="AU"):
            self._create(tmp_path, artifact_id="art-blocked", governance=governance)
        assert not (tmp_path / "art-blocked").exists()

    def test_separate_scoped_approvals_jointly_authorise_generation_and_are_both_snapshotted(
        self, tmp_path
    ):
        uk = _outcome_approval(
            approval_id="apr-uk",
            allowed_uses=("curve_publication",),
            market_scope=("UK",),
        )
        au = _outcome_approval(
            approval_id="apr-au",
            allowed_uses=("curve_publication",),
            market_scope=("AU",),
        )
        governance = _governance(outcome_approval=uk, outcome_approvals=[uk, au])
        result = self._create(tmp_path, artifact_id="art-joint", governance=governance)
        snapshot_ids = {
            row["approval_id"]
            for row in result.artifact.metadata.extra["outcome_approvals_snapshot"]
        }
        assert snapshot_ids == {"apr-uk", "apr-au"}

    def test_single_candidate_fallback_still_generates_and_is_snapshotted(
        self, tmp_path
    ):
        """No explicit outcome_approvals list supplied (older-caller
        fallback): the single outcome_approval is the sole candidate,
        matches every scope (unscoped), and is captured in the new
        snapshot."""
        result = self._create(tmp_path, artifact_id="art-single")
        snapshot = result.artifact.metadata.extra["outcome_approvals_snapshot"]
        assert len(snapshot) == 1
        assert snapshot[0]["approval_id"] == "apr-o1"

    def test_metadata_fingerprints_verify_with_scope_approvals_snapshot(self, tmp_path):
        result = self._create(tmp_path, artifact_id="art-fp-scope")
        verify_curve_artifact_fingerprints(result.artifact.metadata)  # must not raise
        reloaded = read_curve_artifact(result.directory)
        assert (
            reloaded.metadata.extra["outcome_approvals_snapshot"]
            == result.artifact.metadata.extra["outcome_approvals_snapshot"]
        )

    def test_preserves_both_distinct_approvals_when_their_ids_collide(self, tmp_path):
        """REQ-CURVE-001 "Historical artifact integrity (reproducibility)"
        (docs/approved_requirements/REQ-CURVE-001.md) requires the
        persisted artifact carry *complete* immutable evidence of what was
        true at creation, including the outcome definition and approval
        snapshot. OutcomeApproval.approval_id uniqueness is not enforced
        anywhere upstream (record construction, import), so two distinct
        records can legitimately share an id while each independently
        authorizes a different generated scope - deduplicating by id alone
        would silently drop one record's evidence even though both remain
        individually valid, active approvals. REQ-CURVE-001's fail-closed
        rule governs current official-use authorization, not this
        creation-time completeness question, so it is not authority for
        blocking generation over an id coincidence: both records must be
        preserved in the snapshot instead, and generation must still
        succeed."""
        dup_uk = _outcome_approval(
            approval_id="apr-dup",
            allowed_uses=("curve_publication",),
            market_scope=("UK",),
        )
        dup_au = _outcome_approval(
            approval_id="apr-dup",
            allowed_uses=("curve_publication",),
            market_scope=("AU",),
        )
        governance = _governance(
            outcome_approval=dup_uk, outcome_approvals=[dup_uk, dup_au]
        )
        result = self._create(
            tmp_path, artifact_id="art-collision", governance=governance
        )
        snapshot = result.artifact.metadata.extra["outcome_approvals_snapshot"]
        assert len(snapshot) == 2
        market_scopes = {tuple(row["market_scope"]) for row in snapshot}
        assert market_scopes == {("UK",), ("AU",)}

    def test_planning_ineligible_draws_preserved_and_block_planning_use(self, tmp_path):
        specs = _specs()
        support = _media_support(specs)
        del support[("AU", "DNA")]  # missing observed support for one channel
        result = self._create(
            tmp_path,
            artifact_id="art-planning-ineligible",
            support_by_market_channel=support,
        )
        assert (~result.artifact.draws["planning_support_eligible"]).any()
        governance = _governance(
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication", "planning")
            )
        )
        with pytest.raises(CurvePlanningIneligibleError):
            CurveService().authorize_use(
                result.artifact, "planning", current_governance=governance
            )

    def test_reporting_eligible_but_planning_ineligible_remain_distinguishable(
        self, tmp_path
    ):
        specs = _specs()
        support = _media_support(specs)
        del support[("AU", "DNA")]
        result = self._create(
            tmp_path,
            artifact_id="art-distinguish",
            support_by_market_channel=support,
        )
        governance = _governance(
            outcome_approval=_outcome_approval(
                allowed_uses=("curve_publication", "headline_reporting")
            )
        )
        authorization = CurveService().authorize_use(
            result.artifact, "headline_reporting", current_governance=governance
        )
        assert authorization.authorized  # reporting is not gated on planning support

    @pytest.mark.parametrize(
        "unsafe_artifact_id",
        [
            "../escape",
            "..\\escape",
            "../../etc/passwd",
            "/absolute/path",
            "C:/evil",
            "C:\\evil",
            "..",
            ".",
            "sub/dir",
            "sub\\dir",
            "CON",
            "con.json",
            "  ",
        ],
    )
    def test_rejects_unsafe_artifact_ids(self, tmp_path, unsafe_artifact_id):
        # Review-debt finding 8 (PR #103, Corrective PR A1): artifact_id
        # must be a single safe path component - path traversal, absolute
        # paths, drive prefixes, separators, and reserved device names must
        # all be rejected before anything touches disk.
        with pytest.raises(CurveArtifactUnsafeIdError):
            self._create(tmp_path, artifact_id=unsafe_artifact_id)
        # Nothing must have been written outside (or inside) the store.
        assert list(tmp_path.iterdir()) == []

    def test_unsafe_artifact_id_cannot_escape_configured_store(self, tmp_path):
        store_dir = tmp_path / "store"
        sibling = tmp_path / "sibling-marker"
        with pytest.raises(CurveArtifactUnsafeIdError):
            self._create(store_dir, artifact_id="../sibling-marker")
        assert not sibling.exists()

    def test_safe_artifact_id_with_dots_and_dashes_is_accepted(self, tmp_path):
        # A realistic artifact_id (containing dots/dashes but not a
        # traversal sequence or reserved name) must still work.
        result = self._create(tmp_path, artifact_id="art-2026.08.04-v1")
        assert result.artifact_id == "art-2026.08.04-v1"
        assert result.directory == tmp_path / "art-2026.08.04-v1"

    def test_existing_artifact_id_is_not_overwritten(self, tmp_path):
        self._create(tmp_path, artifact_id="art-dup")
        marker = (tmp_path / "art-dup" / CURVE_ARTIFACT_METADATA_FILENAME).read_text(
            encoding="utf-8"
        )
        with pytest.raises(CurveArtifactAlreadyExistsError):
            self._create(tmp_path, artifact_id="art-dup")
        assert (tmp_path / "art-dup" / CURVE_ARTIFACT_METADATA_FILENAME).read_text(
            encoding="utf-8"
        ) == marker

    def test_failure_during_draws_write_leaves_no_partial_final_directory(
        self, tmp_path, monkeypatch
    ):
        def failing_to_parquet(self, *args, **kwargs):
            raise OSError("simulated draws write failure")

        monkeypatch.setattr(pd.DataFrame, "to_parquet", failing_to_parquet)
        with pytest.raises(OSError, match="simulated draws write failure"):
            self._create(tmp_path, artifact_id="art-fail-draws")
        assert not (tmp_path / "art-fail-draws").exists()
        assert list(tmp_path.iterdir()) == []

    def test_failure_during_summaries_write_leaves_no_partial_final_directory(
        self, tmp_path, monkeypatch
    ):
        original_to_parquet = pd.DataFrame.to_parquet
        calls = {"n": 0}

        def flaky_to_parquet(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return original_to_parquet(self, *args, **kwargs)
            raise OSError("simulated summaries write failure")

        monkeypatch.setattr(pd.DataFrame, "to_parquet", flaky_to_parquet)
        with pytest.raises(OSError, match="simulated summaries write failure"):
            self._create(tmp_path, artifact_id="art-fail-summaries")
        assert not (tmp_path / "art-fail-summaries").exists()
        assert list(tmp_path.iterdir()) == []

    def test_failure_during_metadata_write_leaves_no_partial_final_directory(
        self, tmp_path, monkeypatch
    ):
        original_write_text = Path.write_text

        def failing_write_text(self, *args, **kwargs):
            if self.name == CURVE_ARTIFACT_METADATA_FILENAME:
                raise OSError("simulated metadata write failure")
            return original_write_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", failing_write_text)
        with pytest.raises(OSError, match="simulated metadata write failure"):
            self._create(tmp_path, artifact_id="art-fail-metadata")
        assert not (tmp_path / "art-fail-metadata").exists()
        assert list(tmp_path.iterdir()) == []

    def test_readback_verification_failure_removes_temp_directory(
        self, tmp_path, monkeypatch
    ):
        import ancestry_mmm.application.curve_service as svc

        def failing_read(directory):
            raise CurveArtifactError("simulated verify failure")

        monkeypatch.setattr(svc, "read_curve_artifact", failing_read)
        with pytest.raises(CurveArtifactError, match="simulated verify failure"):
            self._create(tmp_path, artifact_id="art-fail-verify")
        assert not (tmp_path / "art-fail-verify").exists()
        assert list(tmp_path.iterdir()) == []

    def test_final_verification_failure_removes_promoted_directory(
        self, tmp_path, monkeypatch
    ):
        # Review-debt finding 9 (PR #103, Corrective PR A4): unlike
        # test_readback_verification_failure_removes_temp_directory (which
        # only exercises the PRE-promotion read on tmp_dir, since that
        # monkeypatch fails unconditionally and execution never reaches
        # rename()), this makes the first read_curve_artifact call succeed
        # (the tmp_dir check) and only the SECOND call (post-promotion, on
        # final_dir) fail - the scenario the finding describes.
        import ancestry_mmm.application.curve_service as svc

        original_read = svc.read_curve_artifact
        calls = {"n": 0}

        def flaky_read(directory):
            calls["n"] += 1
            if calls["n"] == 1:
                return original_read(directory)
            raise CurveArtifactError("simulated post-promotion verify failure")

        monkeypatch.setattr(svc, "read_curve_artifact", flaky_read)
        with pytest.raises(
            CurveArtifactError, match="simulated post-promotion verify failure"
        ):
            self._create(tmp_path, artifact_id="art-fail-final-verify")
        # The promoted directory must not survive the failure...
        assert not (tmp_path / "art-fail-final-verify").exists()
        assert list(tmp_path.iterdir()) == []
        # ...so a retry with the same artifact_id is not permanently blocked.
        monkeypatch.setattr(svc, "read_curve_artifact", original_read)
        result = self._create(tmp_path, artifact_id="art-fail-final-verify")
        assert result.artifact_id == "art-fail-final-verify"

    def test_unknown_metadata_tampering_after_creation_is_detected(self, tmp_path):
        """Complements test_curve_artifact.py::TestUnknownMetadataIntegrity,
        which covers key/value tampering and round-trip preservation
        directly; this exercises the same guarantee through the actual
        creation transaction's output."""
        result = self._create(tmp_path, artifact_id="art-tamper")
        envelope = json.loads(result.metadata_path.read_text(encoding="utf-8"))
        envelope["metadata"]["unexpected_future_field"] = "sneaky"
        result.metadata_path.write_text(json.dumps(envelope), encoding="utf-8")
        with pytest.raises(CurveArtifactError, match="fingerprint mismatch"):
            read_curve_artifact(result.directory)
