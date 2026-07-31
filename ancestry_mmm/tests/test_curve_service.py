"""Tests for the CurveService (PR 95A/95B / REQ-CURVE-001).

PR 95A: official-governance validation — official status requires a current,
matching outcome approval for ``curve_publication`` (never ``model_fit``/
``technical_reporting`` alone), the model approval chain must match, and
activity definitions cannot be omitted.

PR 95B: official generation is routed through the service — every reference
context is validated for completeness against the fitted model structure,
``generate_canonical_curve_draws`` is called in official mode with the
activity definitions bound, and the strictest ``planning_support_eligible``
state is preserved/enforced.
"""

import dataclasses
from types import SimpleNamespace

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.canonical_curves import CurveReferenceContext
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.media_costs import MediaInputSpec, MediaInputSupport
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
from ancestry_mmm.application.curve_service import (
    CurveGovernanceError,
    CurveGovernanceMissingError,
    CurveModelApprovalError,
    CurvePlanningIneligibleError,
    CurvePublicationApprovalError,
    CurveReferenceContextIncompleteError,
    CurveService,
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


def _trace():
    beta = np.array([[0.20, 0.10], [0.15, 0.00], [0.00, 0.30]])
    posterior = {
        "decay_rate": _broadcast([0.5, 0.4]),
        "hill_K": _broadcast([100.0, 80.0]),
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


def _contexts():
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
            counterfactual_axis_type="model_input",
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _identity() -> ModelIdentity:
    return ModelIdentity(**IDENTITY)


def _model_approval(**overrides: object) -> ModelApproval:
    values: dict = {"approved_by": "Jane Analyst", **IDENTITY}
    values.update(overrides)
    return ModelApproval(**values)


def _outcome() -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id="fh_new_gsa",
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
        "outcome_id": "fh_new_gsa",
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
    values: dict = {
        "model_identity": _identity(),
        "model_approval": _model_approval(),
        "outcome_definition": _outcome(),
        "outcome_approval": _outcome_approval(),
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
            model_approval=_model_approval(posterior_fingerprint="wrong-post")
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


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Boundary wiring points (current-use revalidation is deferred to PR 95C)
# ---------------------------------------------------------------------------


class TestBoundaryWiringPoints:
    def test_current_use_revalidation_is_deferred_to_pr95c(self):
        with pytest.raises(NotImplementedError, match="PR 95C"):
            CurveService().authorize_use(object(), "planning")


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
