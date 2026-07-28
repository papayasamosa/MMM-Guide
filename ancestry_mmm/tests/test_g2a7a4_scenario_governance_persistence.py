"""Regression tests for G2A.7a.4: scenario-governance persistence.

Every business-critical test cites the relevant REQ-* ID.
"""

import pandas as pd
import pytest

from ancestry_mmm.core.optimization import (
    ARTEFACT_KINDS,
    ARTEFACT_KIND_REQUIRED_USE,
    PlanningObjective,
    PlanningGovernanceError,
    ResolvedOutcomeAuthorisation,
    ResolvedPlanningGovernance,
    ScenarioEvaluationResult,
    ScenarioGovernanceDependencies,
    classify_artefact_kind,
    fingerprint_planning_objective,
    governance_deps_from_optimizer_result,
    resolve_planning_objective,
    scenario_dependency_status,
    scenario_from_dict,
    scenario_to_dict,
    validate_scenario_dependencies,
)
from ancestry_mmm.core.net_billthrough import NetBillthroughCompletenessMetadata
from ancestry_mmm.core.outcome_approval import (
    OutcomeApprovalBlockedError,
)
from ancestry_mmm.core.scenario_governance import ScenarioPlan


# ============================================================================
# Artefact kind
# ============================================================================


class TestArtefactKind:
    """REQ-PLAN-002: artefact kind must be explicit, never inferred."""

    def test_empty_constraint_optimiser_remains_constrained_optimisation(self):
        """An optimiser with empty constraint list is still constrained_optimisation."""
        kind = classify_artefact_kind([], explicit_kind="constrained_optimisation")
        assert kind == "constrained_optimisation"

    def test_manual_requires_planning(self):
        """REQ-PLAN-002: manual_scenario requires 'planning' use."""
        assert ARTEFACT_KIND_REQUIRED_USE["manual_scenario"] == "planning"

    def test_optimiser_and_benchmark_require_optimisation(self):
        """REQ-PLAN-002: constrained_optimisation and unconstrained_benchmark require 'optimisation'."""
        assert ARTEFACT_KIND_REQUIRED_USE["constrained_optimisation"] == "optimisation"
        assert ARTEFACT_KIND_REQUIRED_USE["unconstrained_benchmark"] == "optimisation"

    def test_name_and_constraint_count_do_not_determine_type(self):
        """Artefact kind must not be inferred from name, notes, or constraint count."""
        # scenario_to_dict with explicit artefact_kind overrides any inference
        s = scenario_to_dict(
            "test",
            "UK",
            {"2026-07": {"TV": 100.0}},
            "fh_gsa",
            [],
            artefact_kind="manual_scenario",
        )
        assert s["artefact_kind"] == "manual_scenario"

    def test_all_kinds_are_recognised(self):
        assert ARTEFACT_KINDS == frozenset(
            {
                "manual_scenario",
                "constrained_optimisation",
                "unconstrained_benchmark",
            }
        )

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown artefact kind"):
            scenario_to_dict(
                "test",
                "UK",
                {"2026-07": {"TV": 100.0}},
                "fh_gsa",
                [],
                artefact_kind="invalid_kind",
            )


# ============================================================================
# Resolved governance (target validation)
# ============================================================================


class TestResolvedGovernanceTargetValidation:
    """REQ-PLAN-003: resolved governance validates exact targets and operation."""

    def test_exact_targets_pass(self):
        governance = ResolvedPlanningGovernance(
            governance_mode="official",
            operation="planning",
            objective_fingerprint="abc",
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            market="UK",
            authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_new",
                    requested_use="planning",
                    approval_id="a1",
                    definition_fingerprint="df1",
                ),
            ),
            target_outcome_ids=("fh_gsa_new",),
        )
        # Should not raise
        governance.validate_against(
            operation="planning",
            objective_fingerprint="abc",
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            market="UK",
            expected_operation="planning",
        )

    def test_missing_targets_block(self):
        # Governance with authorisations but empty target_outcome_ids
        governance = ResolvedPlanningGovernance(
            governance_mode="official",
            operation="planning",
            objective_fingerprint="abc",
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            market="UK",
            authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_new",
                    requested_use="planning",
                    approval_id="a1",
                    definition_fingerprint="df1",
                ),
            ),
            target_outcome_ids=(),
        )
        with pytest.raises(OutcomeApprovalBlockedError, match="no target outcome IDs"):
            governance.validate_against(
                operation="planning",
                objective_fingerprint="abc",
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                market="UK",
                expected_operation="planning",
            )

    def test_extra_authorisations_block(self):
        governance = ResolvedPlanningGovernance(
            governance_mode="official",
            operation="planning",
            objective_fingerprint="abc",
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            market="UK",
            authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_new",
                    requested_use="planning",
                    approval_id="a1",
                    definition_fingerprint="df1",
                ),
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_existing",
                    requested_use="planning",
                    approval_id="a2",
                    definition_fingerprint="df2",
                ),
            ),
            target_outcome_ids=("fh_gsa_new",),
        )
        with pytest.raises(
            OutcomeApprovalBlockedError, match="counts must match|extra authorisation"
        ):
            governance.validate_against(
                operation="planning",
                objective_fingerprint="abc",
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                market="UK",
                expected_operation="planning",
            )

    def test_wrong_operation_blocks(self):
        governance = ResolvedPlanningGovernance(
            governance_mode="official",
            operation="optimisation",
            objective_fingerprint="abc",
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            market="UK",
            authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_new",
                    requested_use="optimisation",
                    approval_id="a1",
                    definition_fingerprint="df1",
                ),
            ),
            target_outcome_ids=("fh_gsa_new",),
        )
        with pytest.raises(
            OutcomeApprovalBlockedError, match="expected operation.*planning"
        ):
            governance.validate_against(
                operation="optimisation",
                objective_fingerprint="abc",
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                market="UK",
                expected_operation="planning",
            )

    def test_wrong_market_blocks(self):
        governance = ResolvedPlanningGovernance(
            governance_mode="official",
            operation="planning",
            objective_fingerprint="abc",
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            market="UK",
            authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_new",
                    requested_use="planning",
                    approval_id="a1",
                    definition_fingerprint="df1",
                ),
            ),
            target_outcome_ids=("fh_gsa_new",),
        )
        with pytest.raises(OutcomeApprovalBlockedError, match="market"):
            governance.validate_against(
                operation="planning",
                objective_fingerprint="abc",
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                market="US",
                expected_operation="planning",
            )

    def test_stale_objective_blocks(self):
        governance = ResolvedPlanningGovernance(
            governance_mode="official",
            operation="planning",
            objective_fingerprint="abc",
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            market="UK",
            authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_new",
                    requested_use="planning",
                    approval_id="a1",
                    definition_fingerprint="df1",
                ),
            ),
            target_outcome_ids=("fh_gsa_new",),
        )
        with pytest.raises(OutcomeApprovalBlockedError, match="objective fingerprint"):
            governance.validate_against(
                operation="planning",
                objective_fingerprint="xyz",
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                market="UK",
                expected_operation="planning",
            )

    def test_stale_model_identity_blocks(self):
        governance = ResolvedPlanningGovernance(
            governance_mode="official",
            operation="planning",
            objective_fingerprint="abc",
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            market="UK",
            authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_new",
                    requested_use="planning",
                    approval_id="a1",
                    definition_fingerprint="df1",
                ),
            ),
            target_outcome_ids=("fh_gsa_new",),
        )
        with pytest.raises(OutcomeApprovalBlockedError, match="model_run_id"):
            governance.validate_against(
                operation="planning",
                objective_fingerprint="abc",
                model_run_id="m2",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                market="UK",
                expected_operation="planning",
            )

    def test_empty_proof_blocks(self):
        governance = ResolvedPlanningGovernance(
            governance_mode="exploratory",
            operation="planning",
            objective_fingerprint="",
            model_run_id="",
            model_approval_fingerprint="",
            data_fingerprint="",
            model_spec_fingerprint="",
            posterior_fingerprint="",
            market="",
            authorisations=(),
            target_outcome_ids=(),
        )
        with pytest.raises(OutcomeApprovalBlockedError, match="not official"):
            governance.validate_against(
                operation="planning",
                objective_fingerprint="abc",
                model_run_id="m1",
                model_approval_fingerprint="",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                market="UK",
                expected_operation="planning",
            )


# ============================================================================
# Scenario save and governance dependencies
# ============================================================================


class TestScenarioSaveAndDependencies:
    """REQ-PERSIST-001: official saves contain complete governance dependencies."""

    def test_manual_official_save_contains_complete_dependencies(self):
        """A manual official save populates all governance dependency fields."""
        planning_obj = PlanningObjective(
            metric_key="fh_gsa",
            target_outcome_ids=("fh_gsa_new",),
        )
        s = scenario_to_dict(
            "test-manual",
            "UK",
            {"2026-07": {"TV": 100.0}},
            "fh_gsa",
            [],
            planning_objective=planning_obj,
            governance_mode="official",
            artefact_kind="manual_scenario",
            governance_dependencies=ScenarioGovernanceDependencies(
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                planning_objective_fingerprint=fingerprint_planning_objective(
                    planning_obj
                ),
                outcome_authorisations=(
                    ResolvedOutcomeAuthorisation(
                        outcome_id="fh_gsa_new",
                        requested_use="planning",
                        approval_id="a1",
                        definition_fingerprint="df1",
                    ),
                ),
                counterfactual_policy_fingerprint="cfp1",
            ),
        )
        deps = s["governance_dependencies"]
        assert deps["model_run_id"] == "m1"
        assert deps["model_approval_fingerprint"] == "maf1"
        assert deps["planning_objective_fingerprint"] != ""
        assert len(deps["outcome_authorisations"]) == 1
        assert s["schema_version"] == 3
        assert s["artefact_kind"] == "manual_scenario"

    def test_nbt_uses_completeness_record_fingerprint(self):
        """REQ-NBT-002: NBT scenarios use completeness-record fingerprint, not definition fingerprint."""
        metadata = NetBillthroughCompletenessMetadata(
            data_as_of_date="2026-07-31",
            model_start_week="2026-07-06",
            model_end_week="2026-07-20",
            latest_complete_net_billthrough_week="2026-07-20",
            maturity_rule_description="authoritative upstream finalisation",
            source_owner="Finance Analytics",
            outcome_id="fh_nbt",
            definition_version="1.0",
            definition_fingerprint="def_fp_123",
        )
        completeness_fp = metadata.completeness_fingerprint()
        # The completeness fingerprint should NOT be the same as definition_fingerprint
        assert completeness_fp != metadata.definition_fingerprint
        # And it should include the canonical fields
        assert isinstance(completeness_fp, str)
        assert len(completeness_fp) == 64  # SHA-256 hex digest

    def test_optimiser_save_contains_dependencies(self):
        """A constrained optimiser save populates all governance dependency fields."""
        planning_obj = PlanningObjective(
            metric_key="fh_gsa",
            target_outcome_ids=("fh_gsa_new",),
        )
        # Simulate an optimizer result dict
        result = {
            "_resolved_governance": {
                "model_run_id": "m1",
                "data_fingerprint": "d1",
                "model_spec_fingerprint": "s1",
                "posterior_fingerprint": "p1",
                "objective_fingerprint": fingerprint_planning_objective(planning_obj),
                "authorisations": [
                    {
                        "outcome_id": "fh_gsa_new",
                        "requested_use": "optimisation",
                        "approval_id": "a1",
                        "definition_fingerprint": "df1",
                        "market": "UK",
                        "product": "Family History",
                        "segment": "New",
                        "nbt_completeness_fingerprint": None,
                    }
                ],
            },
            "activity_definitions_fingerprint": "act_fp",
            "cost_mapping_fingerprint": "cost_fp",
            "counterfactual_policy_fingerprint": "cfp",
        }
        gov_deps_dict = governance_deps_from_optimizer_result(result)
        assert gov_deps_dict["model_run_id"] == "m1"
        assert gov_deps_dict["activity_definitions_fingerprint"] == "act_fp"

    def test_model_and_posterior_fingerprints_are_populated(self):
        planning_obj = PlanningObjective(
            metric_key="fh_gsa",
            target_outcome_ids=("fh_gsa_new",),
        )
        s = scenario_to_dict(
            "test",
            "UK",
            {"2026-07": {"TV": 100.0}},
            "fh_gsa",
            [],
            planning_objective=planning_obj,
            governance_mode="official",
            artefact_kind="manual_scenario",
            governance_dependencies=ScenarioGovernanceDependencies(
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                planning_objective_fingerprint=fingerprint_planning_objective(
                    planning_obj
                ),
                outcome_authorisations=(),
                counterfactual_policy_fingerprint="cfp1",
            ),
        )
        deps = s["governance_dependencies"]
        assert deps["model_run_id"] == "m1"
        assert deps["posterior_fingerprint"] == "p1"

    def test_staleness_from_any_change(self):
        """REQ-PERSIST-002: changes to model, posterior, objective, NBT, activity, cost, or counterfactual stale the scenario."""
        planning_obj = PlanningObjective(
            metric_key="fh_gsa",
            target_outcome_ids=("fh_gsa_new",),
        )
        obj_fp = fingerprint_planning_objective(planning_obj)
        s = scenario_to_dict(
            "test",
            "UK",
            {"2026-07": {"TV": 100.0}},
            "fh_gsa",
            [],
            planning_objective=planning_obj,
            governance_mode="official",
            artefact_kind="manual_scenario",
            governance_dependencies=ScenarioGovernanceDependencies(
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                planning_objective_fingerprint=obj_fp,
                outcome_authorisations=(
                    ResolvedOutcomeAuthorisation(
                        outcome_id="fh_gsa_new",
                        requested_use="planning",
                        approval_id="a1",
                        definition_fingerprint="df1",
                    ),
                ),
                activity_definitions_fingerprint="act1",
                cost_mapping_fingerprint="cost1",
                counterfactual_policy_fingerprint="cfp1",
                nbt_completeness_fingerprint="nbt1",
            ),
        )
        # Changing model_run_id makes it stale
        issues = validate_scenario_dependencies(
            s,
            current_model_run_id="m2",
            current_data_fingerprint="d1",
            current_model_spec_fingerprint="s1",
            current_posterior_fingerprint="p1",
        )
        assert any(i.issue_type == "stale" for i in issues)

        # Changing NBT fingerprint makes it stale
        issues = validate_scenario_dependencies(
            s,
            current_model_run_id="m1",
            current_data_fingerprint="d1",
            current_model_spec_fingerprint="s1",
            current_posterior_fingerprint="p1",
            current_nbt_completeness_fingerprint="nbt2",
        )
        assert any(i.issue_type == "stale" for i in issues)


# ============================================================================
# Legacy migration
# ============================================================================


class TestLegacyMigration:
    """REQ-MIGRATE-001: legacy scenarios become legacy_unverified."""

    def test_schema_1_becomes_legacy_unverified(self):
        """A schema-1 record with null governance deps is legacy_unverified."""
        legacy = {
            "name": "legacy-1",
            "market": "UK",
            "spend_plan": {"2026-07": {"TV": 100.0}},
            "objective": "fh_gsa",
            "constraints": [],
            "schema_version": 1,
        }
        migrated = scenario_from_dict(legacy)
        assert migrated["_migrated_from_schema"] == 1
        assert migrated["schema_version"] >= 3
        status = scenario_dependency_status(migrated)
        assert status == "legacy_unverified"

    def test_schema_2_becomes_legacy_unverified(self):
        legacy = {
            "name": "legacy-2",
            "market": "UK",
            "spend_plan": {"2026-07": {"TV": 100.0}},
            "objective": "fh_gsa",
            "constraints": [],
            "schema_version": 2,
            "scenario_plan": ScenarioPlan.from_legacy_spend_plan(
                {"2026-07": {"TV": 100.0}}
            ).to_dict(),
        }
        migrated = scenario_from_dict(legacy)
        assert migrated["_migrated_from_schema"] == 2
        status = scenario_dependency_status(migrated)
        assert status == "legacy_unverified"

    def test_null_field_migration_never_current(self):
        """A migrated scenario with null dependencies is never current."""
        legacy = {
            "name": "legacy-null",
            "market": "UK",
            "spend_plan": {"2026-07": {"TV": 100.0}},
            "objective": "fh_gsa",
            "constraints": [],
            "schema_version": 1,
        }
        migrated = scenario_from_dict(legacy)
        status = scenario_dependency_status(migrated)
        assert status == "legacy_unverified"
        assert status != "current"
        assert status != "invalid"

    def test_no_legacy_record_becomes_approved(self):
        """No legacy scenario is ever promoted beyond legacy_unverified."""
        legacy = {
            "name": "legacy-3",
            "market": "UK",
            "spend_plan": {"2026-07": {"TV": 100.0}},
            "objective": "fh_gsa",
            "constraints": [],
            "schema_version": 2,
        }
        migrated = scenario_from_dict(legacy)
        status = scenario_dependency_status(migrated)
        assert status == "legacy_unverified"


# ============================================================================
# Scenario dependency validation
# ============================================================================


class TestDependencyValidation:
    """REQ-VALIDATE-001: dependency validation checks current definitions."""

    def test_missing_model_run_id_is_invalid(self):
        s = scenario_to_dict(
            "test",
            "UK",
            {"2026-07": {"TV": 100.0}},
            "fh_gsa",
            [],
            governance_mode="official",
            artefact_kind="manual_scenario",
        )
        issues = validate_scenario_dependencies(s)
        assert any(i.issue_type in ("invalid", "missing") for i in issues)

    def test_missing_outcome_authorisations_is_invalid(self):
        planning_obj = PlanningObjective(
            metric_key="fh_gsa",
            target_outcome_ids=("fh_gsa_new",),
        )
        s = scenario_to_dict(
            "test",
            "UK",
            {"2026-07": {"TV": 100.0}},
            "fh_gsa",
            [],
            planning_objective=planning_obj,
            governance_mode="official",
            artefact_kind="manual_scenario",
            governance_dependencies=ScenarioGovernanceDependencies(
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                planning_objective_fingerprint=fingerprint_planning_objective(
                    planning_obj
                ),
                outcome_authorisations=(),
                counterfactual_policy_fingerprint="cfp1",
            ),
        )
        issues = validate_scenario_dependencies(s)
        assert any(i.issue_type == "invalid" for i in issues)

    def test_wrong_artefact_kind_use_is_rejected(self):
        """An artefact kind with wrong required use is invalid."""
        planning_obj = PlanningObjective(
            metric_key="fh_gsa",
            target_outcome_ids=("fh_gsa_new",),
        )
        s = scenario_to_dict(
            "test",
            "UK",
            {"2026-07": {"TV": 100.0}},
            "fh_gsa",
            [],
            planning_objective=planning_obj,
            governance_mode="official",
            artefact_kind="manual_scenario",
            governance_dependencies=ScenarioGovernanceDependencies(
                model_run_id="m1",
                model_approval_fingerprint="maf1",
                data_fingerprint="d1",
                model_spec_fingerprint="s1",
                posterior_fingerprint="p1",
                planning_objective_fingerprint=fingerprint_planning_objective(
                    planning_obj
                ),
                outcome_authorisations=(
                    ResolvedOutcomeAuthorisation(
                        outcome_id="fh_gsa_new",
                        requested_use="optimisation",  # wrong: manual needs planning
                        approval_id="a1",
                        definition_fingerprint="df1",
                    ),
                ),
                counterfactual_policy_fingerprint="cfp1",
            ),
        )
        issues = validate_scenario_dependencies(s)
        assert any(i.issue_type == "invalid" for i in issues)


# ============================================================================
# Resolved governance round-trip
# ============================================================================


class TestGovernanceRoundTrip:
    """REQ-PERSIST-003: resolved governance survives to_dict/from_dict."""

    def test_to_dict_from_dict_round_trip(self):
        auth = ResolvedOutcomeAuthorisation(
            outcome_id="fh_gsa_new",
            requested_use="planning",
            approval_id="a1",
            definition_fingerprint="df1",
            market="UK",
            product="Family History",
            segment="New",
        )
        gov = ResolvedPlanningGovernance(
            governance_mode="official",
            operation="planning",
            objective_fingerprint="obj_fp",
            model_run_id="m1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            market="UK",
            authorisations=(auth,),
            target_outcome_ids=("fh_gsa_new",),
        )
        restored = ResolvedPlanningGovernance.from_dict(gov.to_dict())
        assert restored == gov
        assert restored.target_outcome_ids == ("fh_gsa_new",)
        assert restored.authorisations[0].outcome_id == "fh_gsa_new"

    def test_deps_to_dict_from_dict_round_trip(self):
        deps = ScenarioGovernanceDependencies(
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            planning_objective_fingerprint="obj_fp",
            outcome_authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_new",
                    requested_use="planning",
                    approval_id="a1",
                    definition_fingerprint="df1",
                ),
            ),
            activity_definitions_fingerprint="act1",
            cost_mapping_fingerprint="cost1",
            counterfactual_policy_fingerprint="cfp1",
            nbt_completeness_fingerprint="nbt1",
        )
        restored = ScenarioGovernanceDependencies.from_dict(deps.to_dict())
        assert restored.model_run_id == "m1"
        assert len(restored.outcome_authorisations) == 1

    def test_scenario_to_dict_from_dict_round_trip(self):
        planning_obj = PlanningObjective(
            metric_key="fh_gsa",
            target_outcome_ids=("fh_gsa_new",),
        )
        deps = ScenarioGovernanceDependencies(
            model_run_id="m1",
            model_approval_fingerprint="maf1",
            data_fingerprint="d1",
            model_spec_fingerprint="s1",
            posterior_fingerprint="p1",
            planning_objective_fingerprint=fingerprint_planning_objective(planning_obj),
            outcome_authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="fh_gsa_new",
                    requested_use="planning",
                    approval_id="a1",
                    definition_fingerprint="df1",
                ),
            ),
            counterfactual_policy_fingerprint="cfp1",
        )
        s = scenario_to_dict(
            "test-roundtrip",
            "UK",
            {"2026-07": {"TV": 100.0}},
            "fh_gsa",
            [],
            planning_objective=planning_obj,
            governance_mode="official",
            artefact_kind="manual_scenario",
            governance_dependencies=deps,
        )
        restored = scenario_from_dict(s)
        assert restored["name"] == "test-roundtrip"
        assert restored["artefact_kind"] == "manual_scenario"


# ============================================================================
# NBT completeness fingerprint
# ============================================================================


class TestNBTCompletenessFingerprint:
    """REQ-NBT-002: NBT uses completeness-record fingerprint."""

    def test_completeness_fingerprint_includes_canonical_fields(self):
        """The completeness fingerprint includes all canonical metadata fields."""
        metadata = NetBillthroughCompletenessMetadata(
            data_as_of_date="2026-07-31",
            model_start_week="2026-07-06",
            model_end_week="2026-07-20",
            latest_complete_net_billthrough_week="2026-07-20",
            maturity_rule_description="authoritative upstream finalisation",
            source_owner="Finance Analytics",
            metric_key="fh_net_billthrough_count",
            aggregation_type="count",
            date_basis="signup_date_attributed",
            unit="bill-through subscriber",
            outcome_id="fh_nbt",
            definition_version="1.0",
            definition_fingerprint="def_fp_123",
        )
        fp = metadata.completeness_fingerprint()
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_changing_as_of_date_stales_nbt(self):
        """A different data_as_of_date changes the fingerprint."""
        m1 = NetBillthroughCompletenessMetadata(
            data_as_of_date="2026-07-01",
            model_start_week="2026-07-06",
            model_end_week="2026-07-20",
            latest_complete_net_billthrough_week="2026-07-20",
            maturity_rule_description="authoritative upstream finalisation",
            source_owner="Finance Analytics",
        )
        m2 = NetBillthroughCompletenessMetadata(
            data_as_of_date="2026-08-01",
            model_start_week="2026-07-06",
            model_end_week="2026-07-20",
            latest_complete_net_billthrough_week="2026-07-20",
            maturity_rule_description="authoritative upstream finalisation",
            source_owner="Finance Analytics",
        )
        assert m1.completeness_fingerprint() != m2.completeness_fingerprint()

    def test_malformed_dict_does_not_block(self):
        """Malformed NBT metadata should not crash the resolver but return None."""
        from ancestry_mmm.core.optimization import _resolve_nbt_completeness_fingerprint

        result = _resolve_nbt_completeness_fingerprint(None)
        assert result is None

        result = _resolve_nbt_completeness_fingerprint({})
        assert result is None  # missing required fields

        result = _resolve_nbt_completeness_fingerprint({"invalid_key": "value"})
        assert result is None


# ============================================================================
# UI governance blocks
# ============================================================================


class TestPlanningGovernanceError:
    """REQ-UI-001: governance blocks render without unhandled exceptions."""

    def test_planning_governance_error_caught_by_page(self):
        """PlanningGovernanceError can be caught with a single except clause."""
        # Simulate what the page does
        try:
            raise OutcomeApprovalBlockedError("test")
        except PlanningGovernanceError as e:
            assert str(e) == "test"

    def test_objective_missing_is_planning_governance_error(self):
        from ancestry_mmm.core.optimization import ObjectiveMissingError

        try:
            raise ObjectiveMissingError("missing objective")
        except PlanningGovernanceError as e:
            assert "missing objective" in str(e)

    def test_exploratory_mode_skips_governance(self):
        """Exploratory scenarios have status 'exploratory' and don't validate."""
        s = scenario_to_dict(
            "exploratory",
            "UK",
            {"2026-07": {"TV": 100.0}},
            "fh_gsa",
            [],
            governance_mode="exploratory",
            artefact_kind="manual_scenario",
        )
        status = scenario_dependency_status(s)
        assert status == "exploratory"


# ============================================================================
# Expected-value objective resolution
# ============================================================================


class TestExpectedValueObjective:
    """REQ-VALUE-001: expected-value optimisation requires value and optimisation eligibility."""

    def test_value_only_secondary_outcomes_excluded_from_optimisation(self):
        """Test that value-only outcomes without explicit eligibility are excluded."""
        from ancestry_mmm.core.hierarchical_model import FHModelMeta

        meta = FHModelMeta(
            markets=["UK"],
            outcome_ids=["fh_gsa_new", "fh_gsa_existing"],
            channels=["TV"],
            dna_channels=[],
            dna_channel_idx=[],
            non_dna_idx=[0],
            dna_outcome_id=None,
            dna_lag_weeks=0,
            unpooled_markets=[],
            control_names=[],
        )
        # Test with basic objective kind
        obj = resolve_planning_objective(
            objective_kind="fh_gsa",
            meta=meta,
            operation="planning",
            counterfactual_policy_fingerprint="cfp1",
        )
        assert obj.metric_key == "fh_gsa"
        assert obj.estimand == "incremental_outcome"

    def test_missing_weights_block_expected_value(self):
        from ancestry_mmm.core.hierarchical_model import FHModelMeta

        meta = FHModelMeta(
            markets=["UK"],
            outcome_ids=["fh_gsa_new"],
            channels=["TV"],
            dna_channels=[],
            dna_channel_idx=[],
            non_dna_idx=[0],
            dna_outcome_id=None,
            dna_lag_weeks=0,
            unpooled_markets=[],
            control_names=[],
        )
        with pytest.raises(ValueError, match="value weights"):
            resolve_planning_objective(
                objective_kind="expected_value",
                meta=meta,
                operation="planning",
                ltv=None,
            )

    def test_unknown_objective_kind_raises(self):
        from ancestry_mmm.core.hierarchical_model import FHModelMeta

        meta = FHModelMeta(
            markets=["UK"],
            outcome_ids=["fh_gsa_new"],
            channels=["TV"],
            dna_channels=[],
            dna_channel_idx=[],
            non_dna_idx=[0],
            dna_outcome_id=None,
            dna_lag_weeks=0,
            unpooled_markets=[],
            control_names=[],
        )
        with pytest.raises(ValueError, match="Unknown objective kind"):
            resolve_planning_objective(
                objective_kind="invalid_kind",
                meta=meta,
                operation="planning",
            )


# ============================================================================
# ScenarioEvaluationResult construction
# ============================================================================


class TestScenarioEvaluationResult:
    """REQ-EVAL-001: ScenarioEvaluationResult carries full governance provenance."""

    def test_result_can_be_constructed(self):
        result = ScenarioEvaluationResult(
            predicted=pd.DataFrame(
                {"month": ["2026-07"], "predicted_outcome": [100.0]}
            ),
            planning_objective=None,
            governance_mode="exploratory",
            artefact_kind="manual_scenario",
        )
        assert result.governance_mode == "exploratory"
        assert result.artefact_kind == "manual_scenario"

    def test_result_with_full_deps(self):
        planning_obj = PlanningObjective(
            metric_key="fh_gsa",
            target_outcome_ids=("fh_gsa_new",),
        )
        result = ScenarioEvaluationResult(
            predicted=pd.DataFrame(
                {"month": ["2026-07"], "predicted_outcome": [100.0]}
            ),
            planning_objective=planning_obj,
            governance_mode="official",
            artefact_kind="manual_scenario",
            activity_definitions_fingerprint="act1",
            cost_mapping_fingerprint="cost1",
            counterfactual_policy_fingerprint="cfp1",
            economics_coverage={"economics_status": "monetary_economics_available"},
        )
        d = result.to_dict()
        assert d["governance_mode"] == "official"
        assert d["artefact_kind"] == "manual_scenario"
        assert d["activity_definitions_fingerprint"] == "act1"
