"""
PR 122: proves the official curve-to-scenario lifecycle end to end, using
ONE reusable deterministic synthetic fixture
(`ancestry_mmm.tests.support.lifecycle_fixture`). No live MCMC/NUTS
sampling anywhere - the fixture builds a structurally-valid but synthetic
posterior deterministically.

Sequence proved by `test_official_curve_to_scenario_lifecycle`:

1.  `CurveService.validate_official_governance` passes for the fixture's
    governance chain.
2.  `CurveService.create_official_artifact` creates the official
    model-input curve artifact.
3.  A second call creates the official monetary curve artifact (cost
    mapping applied) - its units/values differ meaningfully from the
    model-input curve's.
4.  Draws, summary, metadata and fingerprints on both written artifacts
    verify correctly (`verify_curve_artifact_fingerprints`).
5.  `CurveService.authorize_use` grants current authorisation for both
    artifacts against current governance.
6.  `export_project` exports a bundle containing the curve artifact store
    (both new artifacts) plus a saved official manual scenario.
7.  `import_project` imports that bundle into a DESTINATION store dir that
    already has one pre-existing unrelated artifact.
8.  `replace_curve_artifact_store` performs the transactional replacement -
    the old unrelated artifact is gone, the two imported artifacts are
    present (replacement, not merge).
9.  `CurveService.authorize_use` re-run against governance resolved from
    the imported/reconstructed evidence succeeds; a negative case with a
    mismatched model identity fails.
10. `ScenarioService.evaluate_manual` runs an official manual scenario
    evaluation using the imported governance and cost mapping.
11. The saved scenario carries `ScenarioGovernanceDependencies` capturing
    the cost mapping's fingerprint at save time.
12. The cost mapping is mutated to simulate a cost/FX change.
13. `validate_scenario_dependencies` marks the saved scenario stale on the
    changed cost mapping - excluded from a "current" comparison set but
    still retrievable for audit.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ancestry_mmm.application.curve_service import (
    CurveService,
    CurveUseNotAuthorizedError,
)
from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact
from ancestry_mmm.application.scenario_service import (
    ManualScenarioInput,
    ScenarioService,
)
from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.curve_artifact import (
    load_curve_artifact_store,
    verify_curve_artifact_fingerprints,
)
from ancestry_mmm.core.media_costs import CostMappingRegistry, FixedCostPerUnitMapping
from ancestry_mmm.core.optimization import validate_scenario_dependencies
from ancestry_mmm.core.outcome_approval import OutcomeApproval
from ancestry_mmm.core.outcomes import OutcomeDefinition
from ancestry_mmm.core.persistence import (
    audit_project_resumability,
    current_model_identity_fingerprints,
    export_project,
    import_project,
    reconstruct_model_state,
    replace_curve_artifact_store,
)
from ancestry_mmm.core.planning.value import PlanningObjective
from ancestry_mmm.core.validation_policy import ApprovalReadiness, ThresholdPolicy
from ancestry_mmm.tests.support.lifecycle_fixture import (
    CHANNEL,
    MARKET,
    SCENARIO_MONTH,
    UNRELATED_ARTIFACT_ID,
    build_lifecycle_project,
    build_reference_context_by_month,
    build_saved_scenario_dict,
    build_scenario_validation_context,
    create_official_artifacts,
    evaluate_official_manual_scenario,
    write_unrelated_artifact,
)


@pytest.fixture
def project():
    return build_lifecycle_project()


def test_official_curve_to_scenario_lifecycle(project, tmp_path):
    source_store = tmp_path / "source-curve-artifacts"
    destination_store = tmp_path / "destination-curve-artifacts"

    # --- Fixture: destination pre-populated with ONE unrelated artifact
    write_unrelated_artifact(destination_store)
    pre_existing = load_curve_artifact_store(destination_store)
    assert {a.metadata.artifact_id for a in pre_existing.loaded} == {
        UNRELATED_ARTIFACT_ID
    }

    # --- 1. Governance validation passes
    CurveService().validate_official_governance(project.governance)

    # --- 2-3. Create the model-input and monetary official artifacts
    model_input_result, monetary_result = create_official_artifacts(
        project, source_store
    )
    model_input_summary = model_input_result.artifact.summaries
    monetary_summary = monetary_result.artifact.summaries

    assert (model_input_summary["curve_type"] == "model_input").all()
    assert (monetary_summary["curve_type"] == "monetary").all()
    assert set(model_input_summary["spend_unit"].dropna().unique()).isdisjoint(
        set(monetary_summary["spend_unit"].dropna().unique())
    )
    assert model_input_summary["average_roi_posterior_mean"].isna().all()
    monetary_positive_spend = monetary_summary[
        monetary_summary["incremental_spend"] > 0
    ]
    assert monetary_positive_spend["average_roi_posterior_mean"].notna().any()

    # The disjoint-unit check above only proves the two curves are labelled
    # differently - it would still pass if a regression fed monetary £
    # spend straight into the model, ignoring the cost mapping entirely.
    # build_monetary_generation_kwargs's cost mapping is
    # cost_per_media_input=2.0 (build_cost_mapping_registry's default), so
    # the monetary curve's own local_spend=100 point (index 2) converts to
    # exactly 100/2=50 model-input units - the model-input curve's own
    # local_spend=50 point (index 1, from the identical
    # spend_points=[0, 50, 100] both curves were generated with). If the
    # monetary curve genuinely applies the cost mapping before evaluating
    # the same underlying response function, these must match exactly, not
    # just approximately - both are deterministic functions of the same
    # synthetic posterior.
    model_input_at_50_units = model_input_summary.iloc[1]
    monetary_at_gbp_100 = monetary_summary.iloc[2]
    assert model_input_at_50_units["spend_point"] == 1
    assert monetary_at_gbp_100["local_spend"] == 100.0
    assert (
        model_input_at_50_units["incremental_response_posterior_mean"]
        == monetary_at_gbp_100["incremental_response_posterior_mean"]
    )

    # --- 4. Draws, summary, metadata and fingerprints verify correctly
    for result in (model_input_result, monetary_result):
        verify_curve_artifact_fingerprints(result.artifact.metadata)
        assert not result.artifact.draws.empty
        assert not result.artifact.summaries.empty

    reloaded_source = load_curve_artifact_store(source_store)
    assert not reloaded_source.malformed
    assert {a.metadata.artifact_id for a in reloaded_source.loaded} == {
        "lifecycle-model-input",
        "lifecycle-monetary",
    }

    # --- 5. authorize_use grants current authorisation
    for result in (model_input_result, monetary_result):
        authorization = CurveService().authorize_use(
            result.artifact,
            "headline_reporting",
            current_governance=project.governance,
        )
        assert authorization.authorized is True

    # --- Official manual scenario evaluation + save (feeds the export)
    scenario_result = evaluate_official_manual_scenario(project)
    assert scenario_result.errors == []
    assert scenario_result.evaluation is not None
    scenario_dict = build_saved_scenario_dict(project, scenario_result)
    # --- 11. Saved scenario carries the cost mapping's fingerprint
    assert (
        scenario_dict["governance_dependencies"]["cost_mapping_fingerprint"]
        == project.cost_mapping_registry.fingerprint()
    )

    # --- 6. export_project bundles the curve artifact store + scenario
    # raw_sources carries the fixture's own transformed frame (there is no
    # separate pre-pipeline table here - pipeline_steps=[] already means
    # "transformed_data is the raw upload, unmodified"). An empty dict here
    # would leave audit_project_resumability()'s "scenarios" checkpoint
    # reporting raw_sources missing - a bundle this test calls a complete
    # round trip that a real re-import could never actually resume.
    bundle_path = export_project(
        tmp_path / "bundle.zip",
        raw_sources={"joined": project.fitted.transformed_data.copy()},
        transformed_data=project.fitted.transformed_data,
        pipeline_steps=[],
        model_spec=project.fitted.model_spec_dict,
        prior_config=project.fitted.prior_config,
        dna_lag_weeks=project.fitted.dna_lag_weeks,
        trace=project.fitted.trace,
        scenarios=[scenario_dict],
        curve_artifact_store_source_dir=source_store,
        model_approval=project.approval.to_dict(),
        model_run_id=project.fitted.model_run_id,
        model_meta=project.fitted.meta,
        outcome_definitions=[project.fitted.outcome_definition.to_dict()],
        activity_definitions=[a.to_dict() for a in project.fitted.activity_definitions],
        outcome_approvals=[project.outcome_approval.to_dict()],
        validation_policy=project.policy.to_dict(),
        diagnostics_artefact=project.diagnostics.to_dict(),
        approval_readiness=project.readiness.to_dict(),
        media_cost_mappings=project.cost_mapping_registry.to_dict(),
    )

    # --- 7. Import into the destination store dir (already has the
    # unrelated artifact from the fixture)
    imported = import_project(bundle_path)
    assert imported["scenarios"][0]["name"] == "lifecycle-manual-uk"
    assert (
        imported["scenarios"][0]["governance_dependencies"]["cost_mapping_fingerprint"]
        == project.cost_mapping_registry.fingerprint()
    )
    # This bundle is a genuinely complete "scenarios" checkpoint round trip
    # - not merely loadable, but proved resumable by the same audit the
    # real Project Import page runs.
    resumability = audit_project_resumability(imported)
    assert resumability["resumable"] is True, resumability["missing_required"]

    # --- 8. Transactional replacement - proves replacement, not a merge
    replace_curve_artifact_store(imported, destination_store)
    replaced = load_curve_artifact_store(destination_store)
    assert not replaced.malformed
    replaced_ids = {a.metadata.artifact_id for a in replaced.loaded}
    assert UNRELATED_ARTIFACT_ID not in replaced_ids
    assert replaced_ids == {"lifecycle-model-input", "lifecycle-monetary"}

    # --- 9. Reauthorisation of imported/reconstructed governance
    reconstructed = reconstruct_model_state(imported)
    assert reconstructed["frame"] is not None
    assert reconstructed["model_meta"] is not None
    assert reconstructed["posterior_params"] is not None
    data_fp, spec_fp, posterior_fp = current_model_identity_fingerprints(
        imported, reconstructed
    )
    assert data_fp == project.fitted.data_fingerprint
    assert spec_fp == project.fitted.model_spec_fingerprint
    assert posterior_fp == project.fitted.posterior_fingerprint

    imported_outcome_definitions = [
        OutcomeDefinition.from_dict(o) for o in imported["outcome_definitions"]
    ]
    imported_outcome_approvals = [
        OutcomeApproval.from_dict(a) for a in imported["outcome_approvals"]
    ]
    imported_activity_definitions = [
        ActivityDefinition.from_dict(a) for a in imported["activity_definitions"]
    ]
    imported_policy = ThresholdPolicy.from_dict(imported["validation_policy"])
    imported_readiness = ApprovalReadiness.from_dict(imported["approval_readiness"])
    imported_diagnostics = DiagnosticsArtefact.from_dict(
        imported["diagnostics_artefact"]
    )

    reloaded_model_input = next(
        a for a in replaced.loaded if a.metadata.artifact_id == "lifecycle-model-input"
    )
    imported_governance = CurveService().resolve_current_governance(
        reloaded_model_input,
        current_identity={
            "model_run_id": imported["model_run_id"],
            "data_fingerprint": data_fp,
            "model_spec_fingerprint": spec_fp,
            "posterior_fingerprint": posterior_fp,
        },
        approval_dict=imported["model_approval"],
        current_policy=imported_policy,
        current_readiness=imported_readiness,
        current_diagnostics_artefact=imported_diagnostics,
        activity_definitions=imported_activity_definitions,
        outcome_definitions=imported_outcome_definitions,
        outcome_approvals=imported_outcome_approvals,
    )
    assert imported_governance is not None

    reauthorization = CurveService().authorize_use(
        reloaded_model_input,
        "headline_reporting",
        current_governance=imported_governance,
    )
    assert reauthorization.authorized is True

    # Negative case: a mismatched model identity must fail reauthorisation -
    # proves this is a real re-verification, not a no-op.
    mismatched_governance = replace(
        imported_governance,
        model_identity=replace(
            imported_governance.model_identity,
            data_fingerprint="mismatched-fingerprint",
        ),
    )
    with pytest.raises(CurveUseNotAuthorizedError):
        CurveService().authorize_use(
            reloaded_model_input,
            "headline_reporting",
            current_governance=mismatched_governance,
        )

    # --- 10. Official manual scenario evaluation using the imported
    # governance and cost mapping
    imported_cost_registry = CostMappingRegistry.from_dict(
        imported["media_cost_mappings"]
    )
    assert (
        imported_cost_registry.fingerprint()
        == project.cost_mapping_registry.fingerprint()
    )
    imported_planning_objective = PlanningObjective.from_dict(
        imported["scenarios"][0]["planning_objective"]
    )
    reimport_sc_input = ManualScenarioInput(
        market=MARKET,
        spend_plan={SCENARIO_MONTH: {CHANNEL: 100.0}},
        meta=reconstructed["model_meta"],
        params=reconstructed["posterior_params"],
        reference_context_by_month=build_reference_context_by_month(),
        model_type="shared",
        approval=imported_governance.model_approval,
        model_run_id=imported["model_run_id"],
        data_fingerprint=data_fp,
        model_spec_fingerprint=spec_fp,
        posterior_fingerprint=posterior_fp,
        cost_mapping_registry=imported_cost_registry,
        cost_context_id="default",
        cost_as_of_by_month={SCENARIO_MONTH: "2024-01-01"},
        planning_objective=imported_planning_objective,
        activity_definitions=imported_activity_definitions,
        outcome_approvals=imported_outcome_approvals,
        governance_mode="official",
        currency_context=project.currency_context,
        approval_readiness=imported_readiness,
        current_policy=imported_policy,
    )
    reimport_result = ScenarioService().evaluate_manual(reimport_sc_input)
    assert reimport_result.errors == []
    assert reimport_result.evaluation is not None
    assert (
        reimport_result.evaluation.governance_dependencies.cost_mapping_fingerprint
        == project.cost_mapping_registry.fingerprint()
    )

    # --- 12. Mutate the cost mapping to simulate a cost/FX change
    changed_registry = CostMappingRegistry(
        [
            FixedCostPerUnitMapping(
                mapping_id="uk-tv-brand-cost",
                market=MARKET,
                channel=CHANNEL,
                currency="GBP",
                cost_context_id="default",
                source="finance rate card",
                cost_per_media_input=3.5,  # changed from 2.0
                approval_status="approved",
                approved_by="finance-owner",
                approved_at="2026-02-01",
                owner="media-finance",
                approval_note="revised rate card",
                last_reviewed_at="2026-02-01",
            )
        ]
    )
    assert changed_registry.fingerprint() != project.cost_mapping_registry.fingerprint()

    # --- 13. validate_scenario_dependencies marks the saved scenario stale
    context_before_change = build_scenario_validation_context(project, scenario_dict)
    issues_before_change = validate_scenario_dependencies(
        scenario_dict, context=context_before_change
    )
    assert issues_before_change == []

    context_after_change = build_scenario_validation_context(
        project, scenario_dict, cost_mapping_registry=changed_registry
    )
    issues_after_change = validate_scenario_dependencies(
        scenario_dict, context=context_after_change
    )
    assert any(
        issue.issue_type == "stale" and "Cost mapping" in issue.detail
        for issue in issues_after_change
    )

    # Excluded from a "current" comparison set, still retrievable for audit
    all_saved_scenarios = [scenario_dict]
    current_scenarios = [
        s
        for s in all_saved_scenarios
        if not validate_scenario_dependencies(s, context=context_after_change)
    ]
    assert current_scenarios == []
    assert all_saved_scenarios == [scenario_dict]
