"""
REQ-SEARCH-001 Work Package 1, Correction C: proves the single existing
model-identity invalidation chain - `core.fingerprint.fingerprint_model_spec`
-> `ModelIdentity`/`ModelApproval` matching -> `CurveService.authorize_use`
-> `core.optimization.validate_scenario_dependencies` -> export/import
reconstruction (`current_model_identity_fingerprints`) - actually behaves
correctly for a Search object a fit consumes, per the corrected
`search_object_fit_fingerprint` (governance version excluded, fit-relevant
content included). This complements `test_search_objects.py`'s and
`test_fingerprint.py`'s isolated fingerprint-helper tests with the real,
already-governed chain those fingerprints feed - no second Search-specific
staleness mechanism is introduced; every check below reuses the exact
mechanism `test_official_lifecycle_integration.py` already proves for
activities and cost mappings.

No live MCMC/NUTS sampling - reuses the shared deterministic
`ancestry_mmm.tests.support.lifecycle_fixture` builders.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ancestry_mmm.application.curve_service import (
    CurveService,
    CurveUseNotAuthorizedError,
)
from ancestry_mmm.core.optimization import validate_scenario_dependencies
from ancestry_mmm.core.persistence import current_model_identity_fingerprints
from ancestry_mmm.core.search_objects import (
    SEARCH_ROLE_PAID_SPEND,
    UNIT_MONETARY,
    SearchObjectDefinition,
    new_search_object_version,
)
from ancestry_mmm.tests.support.lifecycle_fixture import (
    CHANNEL,
    MARKET,
    build_lifecycle_project,
    build_saved_scenario_dict,
    build_scenario_validation_context,
    create_official_artifacts,
    evaluate_official_manual_scenario,
    recompute_model_spec_fingerprint,
)


def _consumed_search_object() -> SearchObjectDefinition:
    """A Search object whose `model_input_column` exactly matches the
    lifecycle fixture's fitted `CHANNEL` - i.e. genuinely *consumed* by the
    fit, not merely registered (REQ-SEARCH-001 S7/S13)."""
    return SearchObjectDefinition(
        search_object_id="uk_paid_search_spend",
        search_role=SEARCH_ROLE_PAID_SPEND,
        source_column="paid_search_gbp_spend",
        unit=UNIT_MONETARY,
        currency="GBP",
        market=MARKET,
        model_input_column=CHANNEL,
    )


class TestAdministrativeEditDoesNotStale:
    """REQ-SEARCH-001 required invariant: an administrative-only sanctioned
    edit changes the Search object's own governance version but never the
    fit-relevant fingerprint bound into model identity."""

    def test_model_identity_fingerprint_unchanged(self):
        search_object = _consumed_search_object()
        project = build_lifecycle_project(search_objects=[search_object])

        admin_edited = new_search_object_version(
            search_object, planning_eligibility="scenario_only"
        )
        assert admin_edited.search_object_version == 2

        recomputed_fp = recompute_model_spec_fingerprint(
            project.fitted, search_objects=[admin_edited]
        )
        assert recomputed_fp == project.fitted.model_spec_fingerprint

    def test_official_curve_current_use_still_authorized(self, tmp_path):
        search_object = _consumed_search_object()
        project = build_lifecycle_project(search_objects=[search_object])
        admin_edited = new_search_object_version(
            search_object, planning_eligibility="scenario_only"
        )
        recomputed_fp = recompute_model_spec_fingerprint(
            project.fitted, search_objects=[admin_edited]
        )

        model_input_result, _ = create_official_artifacts(
            project, tmp_path / "curve-artifacts"
        )
        current_governance = replace(
            project.governance,
            model_identity=replace(
                project.governance.model_identity,
                model_spec_fingerprint=recomputed_fp,
            ),
        )
        authorization = CurveService().authorize_use(
            model_input_result.artifact,
            "headline_reporting",
            current_governance=current_governance,
        )
        assert authorization.authorized is True

    def test_saved_scenario_still_current(self, tmp_path):
        search_object = _consumed_search_object()
        project = build_lifecycle_project(search_objects=[search_object])
        admin_edited = new_search_object_version(
            search_object, planning_eligibility="scenario_only"
        )
        recomputed_fp = recompute_model_spec_fingerprint(
            project.fitted, search_objects=[admin_edited]
        )

        scenario_result = evaluate_official_manual_scenario(project)
        scenario_dict = build_saved_scenario_dict(project, scenario_result)
        context = replace(
            build_scenario_validation_context(project, scenario_dict),
            model_spec_fingerprint=recomputed_fp,
        )
        issues = validate_scenario_dependencies(scenario_dict, context=context)
        assert issues == []


class TestFitRelevantEditStales:
    """The mirror-image invariant: a sanctioned edit to a fit-relevant field
    (source_column here) changes the fit fingerprint and, through it, every
    dependent governance check - model identity, official curve current-use,
    and saved-scenario currency."""

    def test_model_identity_fingerprint_changes(self):
        search_object = _consumed_search_object()
        project = build_lifecycle_project(search_objects=[search_object])

        fit_relevant_edit = new_search_object_version(
            search_object, source_column="a_different_raw_column"
        )
        recomputed_fp = recompute_model_spec_fingerprint(
            project.fitted, search_objects=[fit_relevant_edit]
        )
        assert recomputed_fp != project.fitted.model_spec_fingerprint

    def test_official_curve_current_use_rejected(self, tmp_path):
        search_object = _consumed_search_object()
        project = build_lifecycle_project(search_objects=[search_object])
        fit_relevant_edit = new_search_object_version(
            search_object, source_column="a_different_raw_column"
        )
        recomputed_fp = recompute_model_spec_fingerprint(
            project.fitted, search_objects=[fit_relevant_edit]
        )

        model_input_result, _ = create_official_artifacts(
            project, tmp_path / "curve-artifacts"
        )
        stale_governance = replace(
            project.governance,
            model_identity=replace(
                project.governance.model_identity,
                model_spec_fingerprint=recomputed_fp,
            ),
        )
        with pytest.raises(CurveUseNotAuthorizedError):
            CurveService().authorize_use(
                model_input_result.artifact,
                "headline_reporting",
                current_governance=stale_governance,
            )

    def test_saved_scenario_flagged_stale(self, tmp_path):
        search_object = _consumed_search_object()
        project = build_lifecycle_project(search_objects=[search_object])
        fit_relevant_edit = new_search_object_version(
            search_object, source_column="a_different_raw_column"
        )
        recomputed_fp = recompute_model_spec_fingerprint(
            project.fitted, search_objects=[fit_relevant_edit]
        )

        scenario_result = evaluate_official_manual_scenario(project)
        scenario_dict = build_saved_scenario_dict(project, scenario_result)
        context = replace(
            build_scenario_validation_context(project, scenario_dict),
            model_spec_fingerprint=recomputed_fp,
        )
        issues = validate_scenario_dependencies(scenario_dict, context=context)
        assert any(
            issue.issue_type == "stale" and "Model spec fingerprint" in issue.detail
            for issue in issues
        )


class TestUnconsumedSearchObjectNeverStales:
    """REQ-SEARCH-001 S7/S13: registering (or editing) a Search object that
    no fit consumes must never change that fit's identity - proved here
    through the same real chain, not only the isolated fingerprint
    helper."""

    def test_model_identity_fingerprint_unaffected_by_unconsumed_edit(self):
        unconsumed = SearchObjectDefinition(
            search_object_id="uk_search_demand",
            search_role="search_demand",
            source_column="branded_query_index",
            unit="index",
            market=MARKET,
            # model_input_column deliberately blank/unmatched - never
            # consumed by the fitted ModelSpec.channels ([CHANNEL]).
        )
        project = build_lifecycle_project(search_objects=[unconsumed])
        edited = new_search_object_version(
            unconsumed, source_column="a_completely_different_column"
        )
        recomputed_fp = recompute_model_spec_fingerprint(
            project.fitted, search_objects=[edited]
        )
        assert recomputed_fp == project.fitted.model_spec_fingerprint


def test_export_import_reconstruction_preserves_administrative_edit_non_staleness(
    tmp_path,
):
    """Export/import reconstruction (`current_model_identity_fingerprints`):
    a project bundle whose registered Search catalogue reflects an
    administrative-only edit (post-fit) must still reconstruct the exact
    fit-time `model_spec_fingerprint` from the imported bundle's own
    `search_objects` field - proving the invariant survives a real
    export/import round trip, not only an in-memory recomputation."""
    from ancestry_mmm.core.persistence import export_project, import_project

    search_object = _consumed_search_object()
    project = build_lifecycle_project(search_objects=[search_object])
    admin_edited = new_search_object_version(
        search_object, planning_eligibility="scenario_only"
    )

    bundle_path = export_project(
        tmp_path / "bundle.zip",
        raw_sources={"joined": project.fitted.transformed_data.copy()},
        transformed_data=project.fitted.transformed_data,
        pipeline_steps=[],
        model_spec=project.fitted.model_spec_dict,
        prior_config=project.fitted.prior_config,
        dna_lag_weeks=project.fitted.dna_lag_weeks,
        trace=project.fitted.trace,
        scenarios=[],
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
        search_objects=[admin_edited.to_dict()],
    )
    imported = import_project(bundle_path)

    from ancestry_mmm.core.persistence import reconstruct_model_state

    reconstructed = reconstruct_model_state(imported)
    assert reconstructed["frame"] is not None
    assert reconstructed["posterior_params"] is not None

    _, spec_fp, _ = current_model_identity_fingerprints(imported, reconstructed)
    assert spec_fp == project.fitted.model_spec_fingerprint
