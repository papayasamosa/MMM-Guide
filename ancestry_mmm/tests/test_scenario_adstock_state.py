"""Tests for PR 82E: adstock carry-in disclosure.

``zero_carry_in_adstock_state`` makes an existing, previously-undisclosed
fact of the prediction code (every scenario starts each channel's adstock
at zero — ``geometric_adstock_matrix`` has no initial-state parameter)
into an explicit, fingerprinted governance record on official-mode
``evaluate_manual_scenario``/``optimize_scenario`` calls. No prediction
math changes: the fingerprint is a disclosure of existing behaviour, not
a new input to it.
"""

import numpy as np
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.optimization import (
    PlanningObjective,
    evaluate_manual_scenario,
    governance_deps_from_optimizer_result,
    optimize_scenario,
)
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
)
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    fingerprint_outcome_definition,
)
from ancestry_mmm.core.planning.value import (
    AdstockState,
    ScenarioGovernanceDependencies,
    zero_carry_in_adstock_state,
)
from ancestry_mmm.core.predict import FHPosteriorParams

IDENTITY = dict(
    model_run_id="run-abc123",
    data_fingerprint="data-fp-1",
    model_spec_fingerprint="spec-fp-1",
    posterior_fingerprint="posterior-fp-1",
)


class TestZeroCarryInAdstockState:
    def test_every_channel_starts_at_zero(self):
        state = zero_carry_in_adstock_state(["TV_Brand", "Search_Paid"], "2024-01")
        assert dict(state.channel_adstock_start) == {
            "TV_Brand": 0.0,
            "Search_Paid": 0.0,
        }
        assert state.channel_adstock_terminal == ()
        assert state.as_of_date == "2024-01"

    def test_channel_order_does_not_affect_fingerprint(self):
        a = zero_carry_in_adstock_state(["TV_Brand", "Search_Paid"], "2024-01")
        b = zero_carry_in_adstock_state(["Search_Paid", "TV_Brand"], "2024-01")
        assert a.fingerprint() == b.fingerprint()

    def test_different_channel_set_changes_fingerprint(self):
        a = zero_carry_in_adstock_state(["TV_Brand"], "2024-01")
        b = zero_carry_in_adstock_state(["TV_Brand", "Search_Paid"], "2024-01")
        assert a.fingerprint() != b.fingerprint()

    def test_different_as_of_date_changes_fingerprint(self):
        a = zero_carry_in_adstock_state(["TV_Brand"], "2024-01")
        b = zero_carry_in_adstock_state(["TV_Brand"], "2024-02")
        assert a.fingerprint() != b.fingerprint()

    def test_empty_channels_is_well_defined(self):
        state = zero_carry_in_adstock_state([], "2024-01")
        assert state.channel_adstock_start == ()
        assert state.fingerprint()  # does not raise, deterministic non-empty hash


class TestScenarioGovernanceDependenciesAdstockField:
    def test_round_trips_through_to_dict_from_dict(self):
        state = zero_carry_in_adstock_state(["TV_Brand"], "2024-01")
        deps = ScenarioGovernanceDependencies(
            model_run_id="run-1",
            model_approval_fingerprint="maf-1",
            data_fingerprint="d-1",
            model_spec_fingerprint="s-1",
            posterior_fingerprint="p-1",
            planning_objective_fingerprint="obj-1",
            outcome_authorisations=(),
            adstock_state_fingerprint=state.fingerprint(),
        )
        restored = ScenarioGovernanceDependencies.from_dict(deps.to_dict())
        assert restored.adstock_state_fingerprint == state.fingerprint()

    def test_defaults_to_empty_string(self):
        deps = ScenarioGovernanceDependencies(
            model_run_id="run-1",
            model_approval_fingerprint="maf-1",
            data_fingerprint="d-1",
            model_spec_fingerprint="s-1",
            posterior_fingerprint="p-1",
            planning_objective_fingerprint="obj-1",
            outcome_authorisations=(),
        )
        assert deps.adstock_state_fingerprint == ""
        assert (
            ScenarioGovernanceDependencies.from_dict(
                deps.to_dict()
            ).adstock_state_fingerprint
            == ""
        )


class TestGovernanceDepsFromOptimizerResultAdstockField:
    def test_extracts_populated_fingerprint(self):
        deps = governance_deps_from_optimizer_result(
            {"adstock_state_fingerprint": "abc123"}
        )
        assert deps["adstock_state_fingerprint"] == "abc123"

    def test_missing_fingerprint_defaults_to_empty_string(self):
        deps = governance_deps_from_optimizer_result({})
        assert deps["adstock_state_fingerprint"] == ""

    def test_none_fingerprint_defaults_to_empty_string(self):
        deps = governance_deps_from_optimizer_result(
            {"adstock_state_fingerprint": None}
        )
        assert deps["adstock_state_fingerprint"] == ""


@pytest.fixture
def gsa_outcome() -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id="New",
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
        completeness_or_maturity_policy="Mature after 12 weeks",
        exclusions="Excludes internal/test accounts",
        reconciliation_source="Finance report",
        business_owner="Analytics",
        definition_version="1.0",
    )


@pytest.fixture
def gsa_meta(gsa_outcome) -> FHModelMeta:
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
        outcome_catalogue_at_fit=[gsa_outcome],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.5},
        hill_K={"TV_Brand": 1000.0},
        hill_S={"TV_Brand": 1.0},
        beta={"New": {"TV_Brand": 0.1}},
        pathway_strength={},
        promo_coef={"New": 0.1},
        market_offset={"UK": {"New": 0.0}},
        intercept={"New": 3.0},
        trend_coef={"New": 0.0},
        gamma_fourier={"New": np.zeros(6)},
        alpha={"New": 5.0},
        control_coef={},
        outcome_control_coef={},
    )


@pytest.fixture
def approval() -> ModelApproval:
    return ModelApproval(approved_by="Jane Analyst", **IDENTITY)


@pytest.fixture
def reference_context():
    return {
        "2024-01": {
            "trend": 1.0,
            "fourier": np.zeros(6),
            "promo": {"New": 0.0},
            "controls": {},
            "outcome_controls": {},
        }
    }


@pytest.fixture
def spend_plan():
    return {"2024-01": {"TV_Brand": 1000.0}}


@pytest.fixture
def outcome_approval(gsa_outcome) -> OutcomeApproval:
    return OutcomeApproval(
        approval_id="apr-new-gsa",
        outcome_id="New",
        definition_fingerprint=fingerprint_outcome_definition(gsa_outcome),
        status="approved",
        allowed_uses=("planning", "optimisation"),
        approved_by="Jane Analyst",
        approved_at="2026-01-01",
    )


@pytest.fixture
def planning_objective() -> PlanningObjective:
    return PlanningObjective(
        estimand="incremental_outcome",
        metric_key=METRIC_KEY_FH_GSA,
        target_outcome_ids=("New",),
    )


class TestEvaluateManualScenarioAdstockDisclosure:
    def test_official_mode_populates_adstock_state(
        self,
        gsa_meta,
        params,
        approval,
        reference_context,
        spend_plan,
        outcome_approval,
        planning_objective,
    ):
        result = evaluate_manual_scenario(
            spend_plan,
            "UK",
            gsa_meta,
            params,
            reference_context,
            planning_objective=planning_objective,
            outcome_approvals=[outcome_approval],
            approval=approval,
            **IDENTITY,
        )
        assert isinstance(result.adstock_state, AdstockState)
        expected = zero_carry_in_adstock_state(gsa_meta.channels, as_of_date="2024-01")
        assert result.adstock_state.fingerprint() == expected.fingerprint()
        assert result.assumptions_fingerprint == expected.fingerprint()
        assert (
            result.governance_dependencies.adstock_state_fingerprint
            == expected.fingerprint()
        )

    def test_exploratory_mode_leaves_adstock_state_unset(
        self,
        gsa_meta,
        params,
        approval,
        reference_context,
        spend_plan,
        planning_objective,
    ):
        result = evaluate_manual_scenario(
            spend_plan,
            "UK",
            gsa_meta,
            params,
            reference_context,
            planning_objective=planning_objective,
            approval=approval,
            governance_mode="exploratory",
            **IDENTITY,
        )
        assert result.adstock_state is None
        assert result.assumptions_fingerprint == ""
        assert result.governance_dependencies is None


class TestOptimizeScenarioAdstockDisclosure:
    def test_official_mode_populates_adstock_state_fingerprint(
        self,
        gsa_meta,
        params,
        approval,
        reference_context,
        spend_plan,
        outcome_approval,
        planning_objective,
    ):
        result = optimize_scenario(
            spend_plan,
            ["2024-01"],
            ["TV_Brand"],
            "UK",
            gsa_meta,
            params,
            reference_context,
            planning_objective=planning_objective,
            outcome_approvals=[outcome_approval],
            approval=approval,
            artefact_kind="unconstrained_benchmark",
            **IDENTITY,
        )
        expected = zero_carry_in_adstock_state(["TV_Brand"], as_of_date="2024-01")
        assert result["adstock_state_fingerprint"] == expected.fingerprint()
        deps = governance_deps_from_optimizer_result(result)
        assert deps["adstock_state_fingerprint"] == expected.fingerprint()

    def test_exploratory_mode_leaves_adstock_state_fingerprint_none(
        self,
        gsa_meta,
        params,
        approval,
        reference_context,
        spend_plan,
        planning_objective,
    ):
        result = optimize_scenario(
            spend_plan,
            ["2024-01"],
            ["TV_Brand"],
            "UK",
            gsa_meta,
            params,
            reference_context,
            planning_objective=planning_objective,
            approval=approval,
            governance_mode="exploratory",
            artefact_kind="unconstrained_benchmark",
            **IDENTITY,
        )
        assert result["adstock_state_fingerprint"] is None
