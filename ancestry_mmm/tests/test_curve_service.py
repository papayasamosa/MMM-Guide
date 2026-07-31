"""Tests for the CurveService boundary (PR 95A / REQ-CURVE-001).

Covers the official-governance validation the boundary must enforce:
- official status requires a current, matching outcome approval for
  ``curve_publication`` — never ``model_fit``/``technical_reporting`` alone;
- the model approval chain is required and must match the current model;
- activity definitions cannot be omitted (non-omission);
- the generation and current-use-revalidation wiring points are explicitly
  deferred to PR 95B / PR 95C.
"""

import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.activities import ActivityDefinition
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
from ancestry_mmm.application.curve_service import (
    CurveGovernanceMissingError,
    CurveModelApprovalError,
    CurvePublicationApprovalError,
    CurveService,
    OfficialCurveGovernance,
)

IDENTITY = {
    "model_run_id": "run-123",
    "data_fingerprint": "data-abc",
    "model_spec_fingerprint": "spec-def",
    "posterior_fingerprint": "post-ghi",
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


def _governance(**overrides: object) -> OfficialCurveGovernance:
    values: dict = {
        "model_identity": _identity(),
        "model_approval": _model_approval(),
        "outcome_definition": _outcome(),
        "outcome_approval": _outcome_approval(),
        "activity_definitions": [_activity()],
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
# Boundary wiring points (deferred to later PRs)
# ---------------------------------------------------------------------------


class TestBoundaryWiringPoints:
    def test_generation_is_deferred_to_pr95b(self):
        with pytest.raises(NotImplementedError, match="PR 95B"):
            CurveService().generate_official_curve(_governance())

    def test_current_use_revalidation_is_deferred_to_pr95c(self):
        with pytest.raises(NotImplementedError, match="PR 95C"):
            CurveService().authorize_use(object(), "planning")
