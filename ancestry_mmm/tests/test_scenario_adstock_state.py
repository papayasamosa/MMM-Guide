"""Tests for PR 82E's adstock carry-in disclosure, and PR 88B's replacement
of it with truthful planning-evaluation-semantics disclosure.

``zero_carry_in_adstock_state`` makes an existing, previously-undisclosed
fact of the prediction code (every scenario starts each channel's adstock
at zero — ``geometric_adstock_matrix`` has no initial-state parameter)
into an explicit, fingerprinted governance record. The function and
``AdstockState`` are preserved for a future sequential planning engine, but
PR 88B stops calling them from ``evaluate_manual_scenario``/
``optimize_scenario``'s steady-state official-mode governance evidence:
disclosing "zero carry-in" implied a carry-in concept steady-state
evaluation does not actually model (no time-stepped simulation). The
replacement, ``PlanningEvaluationSemantics``, states the engine's actual
temporal semantics directly instead. No prediction math changes in either
PR: both are disclosures of existing behaviour, not new inputs to it.
"""

import numpy as np
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.optimization import (
    CURRENT_PLANNING_EVALUATION_SEMANTICS,
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
    PLANNING_SEMANTICS_SCHEMA_VERSION,
    PlanningEvaluationSemantics,
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


class TestEvaluateManualScenarioAdstockDisclosureDeprecated:
    """PR 88B: evaluate_manual_scenario no longer populates the PR 82E
    adstock disclosure fields for steady-state evaluation - they mis-
    characterised the calculation as having a carry-in concept it does not
    model. See TestEvaluateManualScenarioPlanningSemanticsDisclosure below
    for the replacement."""

    def test_official_mode_no_longer_populates_adstock_state(
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
        assert result.adstock_state is None
        assert result.assumptions_fingerprint == ""
        assert result.governance_dependencies.adstock_state_fingerprint == ""

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


class TestOptimizeScenarioAdstockDisclosureDeprecated:
    """PR 88B: optimize_scenario no longer populates adstock_state_
    fingerprint - see TestOptimizeScenarioPlanningSemanticsDisclosure
    below for the replacement."""

    def test_official_mode_no_longer_populates_adstock_state_fingerprint(
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
        assert result.get("adstock_state_fingerprint") is None
        deps = governance_deps_from_optimizer_result(result)
        assert deps["adstock_state_fingerprint"] == ""

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
        assert result.get("adstock_state_fingerprint") is None


class TestEvaluateManualScenarioPlanningSemanticsDisclosure:
    """PR 88B: evaluate_manual_scenario discloses PlanningEvaluationSemantics
    (truthful engine/temporal/carry-in-applicability facts) in place of the
    deprecated adstock-state disclosure."""

    def test_official_mode_populates_planning_semantics(
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
        assert result.planning_semantics == CURRENT_PLANNING_EVALUATION_SEMANTICS
        assert result.planning_semantics.engine == "steady_state_monthly"
        assert result.planning_semantics.carry_in_state_applicable is False
        assert result.planning_semantics.terminal_state_applicable is False
        assert (
            result.governance_dependencies.planning_semantics_fingerprint
            == CURRENT_PLANNING_EVALUATION_SEMANTICS.fingerprint()
        )

    def test_exploratory_mode_leaves_planning_semantics_unset(
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
        assert result.planning_semantics is None


class TestOptimizeScenarioPlanningSemanticsDisclosure:
    """PR 88B: optimize_scenario discloses the same PlanningEvaluationSemantics
    as evaluate_manual_scenario."""

    def test_official_mode_populates_planning_semantics_fingerprint(
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
        assert (
            result["planning_semantics_fingerprint"]
            == CURRENT_PLANNING_EVALUATION_SEMANTICS.fingerprint()
        )
        deps = governance_deps_from_optimizer_result(result)
        assert (
            deps["planning_semantics_fingerprint"]
            == CURRENT_PLANNING_EVALUATION_SEMANTICS.fingerprint()
        )

    def test_exploratory_mode_leaves_planning_semantics_fingerprint_none(
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
        assert result["planning_semantics_fingerprint"] is None


class TestManualAndOptimisationShareIdenticalSemantics:
    """PR 88B requirement: manual evaluation and optimisation must disclose
    the exact same planning semantics - a scenario saved from either entry
    point must be interchangeable evidence, never two different "current"
    definitions of what the engine does."""

    def test_manual_and_optimizer_fingerprints_match(
        self,
        gsa_meta,
        params,
        approval,
        reference_context,
        spend_plan,
        outcome_approval,
        planning_objective,
    ):
        manual_result = evaluate_manual_scenario(
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
        optimizer_result = optimize_scenario(
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
        assert (
            manual_result.governance_dependencies.planning_semantics_fingerprint
            == optimizer_result["planning_semantics_fingerprint"]
        )


# ---------------------------------------------------------------------------
# PR 91A: PlanningEvaluationSemantics payload schema versioning
# ---------------------------------------------------------------------------


class TestPlanningEvaluationSemanticsSchemaVersioning:
    """PR 91A: PlanningEvaluationSemantics.to_dict()/from_dict() previously
    had no schema version of their own - prediction_function_version
    describes the calculation the semantics disclose, not the shape of the
    serialized payload. schema_version now versions that payload shape
    explicitly, distinct from both prediction_function_version and a saved
    scenario's own governance-dependencies schema version (bumped 3 -> 4 in
    core.scenario_governance when planning_semantics_fingerprint was
    added)."""

    def _semantics(self, **overrides) -> PlanningEvaluationSemantics:
        defaults = dict(
            engine="steady_state_monthly",
            temporal_resolution="monthly",
            within_period_media_assumption="constant_to_steady_state",
            carry_in_state_applicable=False,
            terminal_state_applicable=False,
            prediction_function_version="1.0.0",
        )
        defaults.update(overrides)
        return PlanningEvaluationSemantics(**defaults)

    def test_current_round_trip_preserves_schema_version(self):
        semantics = self._semantics()
        assert semantics.schema_version == PLANNING_SEMANTICS_SCHEMA_VERSION
        payload = semantics.to_dict()
        assert payload["schema_version"] == PLANNING_SEMANTICS_SCHEMA_VERSION
        restored = PlanningEvaluationSemantics.from_dict(payload)
        assert restored == semantics
        assert restored.schema_version == PLANNING_SEMANTICS_SCHEMA_VERSION

    def test_unversioned_legacy_payload_migrates_to_schema_version_1(self):
        """Every payload written before PR 91A has no schema_version key at
        all - from_dict must migrate it cleanly rather than raising."""
        legacy_payload = {
            "engine": "steady_state_monthly",
            "temporal_resolution": "monthly",
            "within_period_media_assumption": "constant_to_steady_state",
            "carry_in_state_applicable": False,
            "terminal_state_applicable": False,
            "prediction_function_version": "1.0.0",
        }
        assert "schema_version" not in legacy_payload
        restored = PlanningEvaluationSemantics.from_dict(legacy_payload)
        assert restored.schema_version == 1
        assert restored.engine == "steady_state_monthly"
        assert restored.prediction_function_version == "1.0.0"

    def test_unsupported_future_schema_version_is_rejected_fail_closed(self):
        future_payload = self._semantics().to_dict()
        future_payload["schema_version"] = PLANNING_SEMANTICS_SCHEMA_VERSION + 1
        with pytest.raises(ValueError, match="schema_version"):
            PlanningEvaluationSemantics.from_dict(future_payload)

    def test_prediction_function_version_remains_distinct_from_schema_version(self):
        """Bumping the calculation version must not require, or imply, a
        payload schema_version bump, and vice versa."""
        semantics = self._semantics(prediction_function_version="2.0.0")
        assert semantics.schema_version == PLANNING_SEMANTICS_SCHEMA_VERSION
        assert semantics.prediction_function_version == "2.0.0"
        payload = semantics.to_dict()
        assert payload["prediction_function_version"] == "2.0.0"
        assert payload["schema_version"] == PLANNING_SEMANTICS_SCHEMA_VERSION

    def test_fingerprint_excludes_schema_version(self):
        """A legacy-migrated payload (schema_version implicitly -> 1) and an
        explicitly-versioned one with identical calculation semantics must
        fingerprint identically - migrating the payload shape alone must
        not stale a scenario evaluated under an unchanged calculation."""
        migrated = PlanningEvaluationSemantics.from_dict(
            {
                "engine": "steady_state_monthly",
                "temporal_resolution": "monthly",
                "within_period_media_assumption": "constant_to_steady_state",
                "carry_in_state_applicable": False,
                "terminal_state_applicable": False,
                "prediction_function_version": "1.0.0",
            }
        )
        explicit = self._semantics()
        assert migrated.fingerprint() == explicit.fingerprint()

    def test_scenario_governance_dependencies_schema_v4_round_trip_unaffected(
        self,
        gsa_meta,
        params,
        approval,
        reference_context,
        spend_plan,
        outcome_approval,
        planning_objective,
    ):
        """PR 91A must not disturb the scenario governance-dependencies
        schema (independently at v4 since PR 88B added
        planning_semantics_fingerprint) - a manually evaluated scenario's
        governance_dependencies still round-trips through to_dict/from_dict
        with a populated planning_semantics_fingerprint."""
        manual_result = evaluate_manual_scenario(
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
        deps = manual_result.governance_dependencies
        assert (
            deps.planning_semantics_fingerprint
            == CURRENT_PLANNING_EVALUATION_SEMANTICS.fingerprint()
        )
        round_tripped = ScenarioGovernanceDependencies.from_dict(deps.to_dict())
        assert (
            round_tripped.planning_semantics_fingerprint
            == deps.planning_semantics_fingerprint
        )

    def test_current_semantics_fingerprint_is_pinned(self):
        """PR 92A is an encoding-only fix to schema_version validation - it
        must not change what the calculation fingerprint hashes. Pinning the
        literal value guards against an accidental change to fingerprint()'s
        included fields alongside the schema_version validation fix."""
        assert (
            CURRENT_PLANNING_EVALUATION_SEMANTICS.fingerprint()
            == "41b0bbcd57f067a39319d62aebb12ce815e289569eb51a598741baeef0099497"
        )

    # PR 92A: non-mapping payloads must be rejected outright by from_dict -
    # none of these can be interpreted as a legacy or current payload shape.
    # `{}` is deliberately excluded here: it IS a mapping, and exercises the
    # legacy-migration path (covered by
    # test_unversioned_legacy_payload_migrates_to_schema_version_1-style
    # absent-key behaviour), not the non-mapping rejection path.
    @pytest.mark.parametrize(
        "payload", [1.5, True, False, "1", "01", None, 0, -1, 2, []]
    )
    def test_from_dict_rejects_non_mapping_payload(self, payload):
        with pytest.raises((TypeError, ValueError)):
            PlanningEvaluationSemantics.from_dict(payload)

    # PR 92A: each of these, as the schema_version field of an otherwise
    # valid payload, must be rejected. `None` here is the explicit-null
    # case (key present, value None) - distinct from a genuinely absent key,
    # which migrates instead of raising.
    @pytest.mark.parametrize(
        "raw_version", [1.5, True, False, "1", "01", None, 0, -1, 2]
    )
    def test_from_dict_rejects_invalid_schema_version_field(self, raw_version):
        payload = self._semantics().to_dict()
        payload["schema_version"] = raw_version
        assert "schema_version" in payload
        with pytest.raises(ValueError, match="schema_version"):
            PlanningEvaluationSemantics.from_dict(payload)

    @pytest.mark.parametrize("invalid_schema_version", [0, True, 2, -1])
    def test_direct_construction_rejects_invalid_schema_version(
        self, invalid_schema_version
    ):
        with pytest.raises(ValueError, match="schema_version"):
            self._semantics(schema_version=invalid_schema_version)

    def test_direct_construction_with_current_schema_version_succeeds(self):
        semantics = self._semantics(schema_version=PLANNING_SEMANTICS_SCHEMA_VERSION)
        assert semantics.schema_version == PLANNING_SEMANTICS_SCHEMA_VERSION
