"""Tests for `ancestry_mmm.core.optimization_objective_vocabulary`
(`REQ-OPT-001` Requirement 1; Decision 16). See
`docs/optimizer_objective_and_constraint_vocabulary_decision_record.md`.
"""

import pytest

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.optimization_objective_vocabulary import (
    OBJECTIVE_KIND_MAXIMISE_OUTCOME,
    OBJECTIVE_KIND_MAXIMISE_PROFIT,
    OBJECTIVE_KIND_MAXIMISE_REVENUE,
    OBJECTIVE_KIND_MAXIMISE_ROI,
    OBJECTIVE_KIND_MINIMISE_CPA,
    OBJECTIVE_KINDS,
    PROFIT_DEFINITION_MISSING_REASON,
    resolve_all_objective_kinds,
    resolve_objective_kind,
)


def _meta_with_value_weighted_outcome() -> FHModelMeta:
    # No outcome_catalogue_at_fit / outcome_id_to_eligibility set: matches
    # this test suite's established fixture pattern (test_optimization.py's
    # own `meta`/`meta_with_kit_segment` fixtures) - a bare FHModelMeta
    # defaults every outcome to role="primary", which core.outcomes'
    # eligibility defaults resolve as value/optimisation-eligible.
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


def _paid_activity(activity_id: str, channel: str) -> ActivityDefinition:
    return ActivityDefinition(
        activity_id=activity_id,
        channel=channel,
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        source="finance",
        approval_status="approved",
        approved_by="reviewer",
        approved_at="2026-01-01",
    )


def _response_only_activity(activity_id: str, channel: str) -> ActivityDefinition:
    return ActivityDefinition(
        activity_id=activity_id,
        channel=channel,
        activity_ownership="owned",
        model_role="intervention",
        economic_treatment="response_only",
        planning_eligibility="optimisable",
        source="seo team",
        approval_status="approved",
        approved_by="reviewer",
        approved_at="2026-01-01",
    )


class TestObjectiveKindVocabularyIsClosed:
    def test_vocabulary_matches_req_opt_001_requirement_1(self):
        assert OBJECTIVE_KINDS == (
            "maximise_outcome",
            "maximise_revenue",
            "maximise_profit",
            "maximise_roi",
            "minimise_cpa",
        )

    def test_unknown_kind_raises(self):
        meta = _meta_with_value_weighted_outcome()
        with pytest.raises(ValueError):
            resolve_objective_kind("maximise_everything", meta=meta)


class TestMaximiseOutcome:
    def test_requires_legacy_metric_kind(self):
        meta = _meta_with_value_weighted_outcome()
        result = resolve_objective_kind(OBJECTIVE_KIND_MAXIMISE_OUTCOME, meta=meta)
        assert result.ready is False
        assert "legacy_metric_kind" in result.reasons[0]

    def test_resolves_when_metric_kind_valid(self):
        meta = _meta_with_value_weighted_outcome()
        result = resolve_objective_kind(
            OBJECTIVE_KIND_MAXIMISE_OUTCOME, meta=meta, legacy_metric_kind="fh_gsa"
        )
        assert result.ready is True
        assert result.resolved_planning_objective is not None


class TestMaximiseProfitAlwaysBlocked:
    def test_profit_is_unconditionally_blocked(self):
        meta = _meta_with_value_weighted_outcome()
        result = resolve_objective_kind(OBJECTIVE_KIND_MAXIMISE_PROFIT, meta=meta)
        assert result.ready is False
        assert result.reasons == (PROFIT_DEFINITION_MISSING_REASON,)
        assert result.resolved_planning_objective is None


class TestMaximiseRevenue:
    def test_blocked_without_value_weights(self):
        meta = FHModelMeta(
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
        result = resolve_objective_kind(OBJECTIVE_KIND_MAXIMISE_REVENUE, meta=meta)
        assert result.ready is False
        assert result.reasons

    def test_ready_with_governed_value_weight_and_currency(self):
        meta = _meta_with_value_weighted_outcome()
        result = resolve_objective_kind(
            OBJECTIVE_KIND_MAXIMISE_REVENUE,
            meta=meta,
            ltv={"New": 25.0},
            value_currency="GBP",
        )
        assert result.ready is True
        assert result.resolved_planning_objective.metric_key == "expected_value"


class TestCostBasedObjectivesRequireCostBearingChannels:
    def test_blocked_without_considered_channels(self):
        meta = _meta_with_value_weighted_outcome()
        result = resolve_objective_kind(
            OBJECTIVE_KIND_MAXIMISE_ROI,
            meta=meta,
            ltv={"New": 25.0},
            value_currency="GBP",
        )
        assert result.ready is False

    def test_blocked_without_activities_supplied(self):
        meta = _meta_with_value_weighted_outcome()
        result = resolve_objective_kind(
            OBJECTIVE_KIND_MINIMISE_CPA,
            meta=meta,
            ltv={"New": 25.0},
            value_currency="GBP",
            considered_channels=["TV_Brand"],
        )
        assert result.ready is False
        assert "activity taxonomy" in result.reasons[0]

    def test_seo_channel_excluded_from_roi_objective(self):
        meta = _meta_with_value_weighted_outcome()
        activities = [
            _paid_activity("tv", "TV_Brand"),
            _response_only_activity("seo", "SEO"),
        ]
        result = resolve_objective_kind(
            OBJECTIVE_KIND_MAXIMISE_ROI,
            meta=meta,
            ltv={"New": 25.0},
            value_currency="GBP",
            considered_channels=["TV_Brand", "SEO"],
            activities=activities,
        )
        assert result.ready is False
        assert result.excluded_channels == ("SEO",)

    def test_ready_when_every_considered_channel_is_cost_bearing(self):
        meta = _meta_with_value_weighted_outcome()
        activities = [_paid_activity("tv", "TV_Brand")]
        result = resolve_objective_kind(
            OBJECTIVE_KIND_MAXIMISE_ROI,
            meta=meta,
            ltv={"New": 25.0},
            value_currency="GBP",
            considered_channels=["TV_Brand"],
            activities=activities,
        )
        assert result.ready is True

    def test_minimise_cpa_also_gated_the_same_way(self):
        meta = _meta_with_value_weighted_outcome()
        activities = [_response_only_activity("seo", "SEO")]
        result = resolve_objective_kind(
            OBJECTIVE_KIND_MINIMISE_CPA,
            meta=meta,
            ltv={"New": 25.0},
            value_currency="GBP",
            considered_channels=["SEO"],
            activities=activities,
        )
        assert result.ready is False
        assert result.excluded_channels == ("SEO",)


class TestResolveAllObjectiveKinds:
    def test_returns_one_resolution_per_kind_offered(self):
        meta = _meta_with_value_weighted_outcome()
        results = resolve_all_objective_kinds(
            meta=meta,
            ltv={"New": 25.0},
            value_currency="GBP",
            considered_channels=["TV_Brand"],
            activities=[_paid_activity("tv", "TV_Brand")],
        )
        kinds = [r.objective_kind for r in results]
        # 4 legacy maximise_outcome variants + revenue/profit/roi/cpa
        assert kinds.count(OBJECTIVE_KIND_MAXIMISE_OUTCOME) == 4
        assert OBJECTIVE_KIND_MAXIMISE_REVENUE in kinds
        assert OBJECTIVE_KIND_MAXIMISE_PROFIT in kinds
        by_kind = {
            r.objective_kind: r
            for r in results
            if r.objective_kind == OBJECTIVE_KIND_MAXIMISE_PROFIT
        }
        assert by_kind[OBJECTIVE_KIND_MAXIMISE_PROFIT].ready is False
