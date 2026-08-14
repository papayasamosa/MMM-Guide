"""WP3 persistence, fit identity, and staleness contracts."""

from dataclasses import replace

import pandas as pd

from ancestry_mmm.core.fingerprint import fingerprint_model_spec
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
    OUTCOME_GROUP_TREATMENT_TOTAL_ONLY,
    SEGMENT_DIMENSION_FH_CUSTOMER,
    OutcomeDefinition,
    OutcomeGroupDefinition,
    OutcomeGroupTreatment,
    has_blocking_drift,
    outcome_group_drift_status,
    outcome_group_fingerprint_payload,
    outcome_group_treatment_drift_status,
    outcome_groups_drift_dataframe,
)
from ancestry_mmm.core.pathways import OutcomeReconciliationGroup
from ancestry_mmm.core.persistence import (
    PROJECT_BUNDLE_SCHEMA_VERSION,
    export_project,
    import_project,
    reconstruct_model_state,
    resolve_imported_outcome_group_treatments,
    resolve_imported_outcome_groups,
    resolve_imported_outcome_reconciliation_groups,
)


def _group(label: str = "Family History GSA") -> OutcomeGroupDefinition:
    return OutcomeGroupDefinition(
        group_id="fh-gsa",
        group_label=label,
        product=FAMILY_HISTORY,
        outcome_family_key="gsa",
        segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
        member_outcome_ids=("fh_new_gsa", "fh_cross_sell_gsa", "fh_winback_gsa"),
    )


def _meta(
    group: OutcomeGroupDefinition, treatment: OutcomeGroupTreatment
) -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=["fh_new_gsa"],
        channels=["TV"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="fh_new_gsa",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
        outcome_groups_at_fit=[group],
        outcome_group_treatments_at_fit=[treatment],
    )


def test_group_and_treatment_fingerprints_are_calculation_relevant():
    group_payload = outcome_group_fingerprint_payload([_group()])
    joint_payload = [
        OutcomeGroupTreatment(
            group_id="fh-gsa", treatment=OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT
        ).to_dict()
    ]
    total_payload = [
        OutcomeGroupTreatment(
            group_id="fh-gsa", treatment=OUTCOME_GROUP_TREATMENT_TOTAL_ONLY
        ).to_dict()
    ]

    joint = fingerprint_model_spec(
        {}, {}, 4, outcome_groups=group_payload, outcome_group_treatments=joint_payload
    )
    total = fingerprint_model_spec(
        {}, {}, 4, outcome_groups=group_payload, outcome_group_treatments=total_payload
    )
    relabelled = fingerprint_model_spec(
        {},
        {},
        4,
        outcome_groups=outcome_group_fingerprint_payload(
            [replace(_group(), group_label="Renamed display label")]
        ),
        outcome_group_treatments=joint_payload,
    )

    assert joint != total
    assert joint == relabelled


def test_outcome_group_and_treatment_records_round_trip(tmp_path):
    group = _group()
    treatment = OutcomeGroupTreatment(
        group_id=group.group_id,
        treatment=OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
    )
    reconciliation = OutcomeReconciliationGroup(
        group_id=group.group_id,
        component_outcome_ids=list(group.member_outcome_ids),
        total_outcome_id="fh_gsa_total",
    )
    outcome = OutcomeDefinition(
        outcome_id="fh_new_gsa",
        product=FAMILY_HISTORY,
        metric="GSA",
        segment="New",
        source_column="fh_new_gsa",
        segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
    )
    meta = _meta(group, treatment)

    bundle = export_project(
        tmp_path / "groups.zip",
        raw_sources={},
        transformed_data=pd.DataFrame({"fh_new_gsa": [1]}),
        pipeline_steps=[],
        model_spec=None,
        prior_config={},
        dna_lag_weeks=4,
        trace=None,
        scenarios=[],
        model_meta=meta,
        outcome_definitions=[outcome.to_dict()],
        outcome_groups=[group],
        outcome_group_treatments=[treatment],
        outcome_reconciliation_groups=[reconciliation],
    )

    imported = import_project(bundle)
    assert imported["manifest"]["schema_version"] == PROJECT_BUNDLE_SCHEMA_VERSION
    assert imported["outcome_groups"] == [group.to_dict()]
    assert imported["outcome_group_treatments"] == [treatment.to_dict()]
    assert imported["outcome_reconciliation_groups"] == [reconciliation.to_dict()]

    restored = reconstruct_model_state(imported)["model_meta"]
    assert restored.outcome_groups_at_fit == [group]
    assert restored.outcome_group_treatments_at_fit == [treatment]


def test_legacy_meta_defaults_to_no_groups_without_inference(tmp_path):
    bundle = export_project(
        tmp_path / "legacy.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config={},
        dna_lag_weeks=4,
        trace=None,
        scenarios=[],
    )
    imported = import_project(bundle)
    assert imported["outcome_groups"] is None
    assert imported["outcome_group_treatments"] is None
    assert imported["outcome_reconciliation_groups"] is None


def test_malformed_group_records_are_quarantined():
    groups, group_warnings = resolve_imported_outcome_groups(
        {"outcome_groups": [{"group_id": "missing-required-fields"}]}
    )
    treatments, treatment_warnings = resolve_imported_outcome_group_treatments(
        {"outcome_group_treatments": [{"group_id": "fh-gsa", "treatment": "invented"}]}
    )
    reconciliations, reconciliation_warnings = (
        resolve_imported_outcome_reconciliation_groups(
            {
                "outcome_reconciliation_groups": [
                    {
                        "group_id": "too-short",
                        "component_outcome_ids": ["one"],
                    }
                ]
            }
        )
    )

    assert groups == [] and group_warnings
    assert treatments == [] and treatment_warnings
    assert reconciliations == [] and reconciliation_warnings


def test_group_drift_ignores_labels_but_stales_membership_and_treatment():
    fit_group = _group()
    renamed = replace(fit_group, group_label="New display wording")
    changed = replace(fit_group, member_outcome_ids=("fh_new_gsa", "fh_other"))
    fit_treatment = OutcomeGroupTreatment(
        group_id="fh-gsa", treatment=OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT
    )
    changed_treatment = replace(
        fit_treatment, treatment=OUTCOME_GROUP_TREATMENT_TOTAL_ONLY
    )
    meta = _meta(fit_group, fit_treatment)

    assert outcome_group_drift_status(renamed, fit_group) == "Fitted and current"
    assert outcome_group_drift_status(changed, fit_group) == "Changed since fit"
    assert (
        outcome_group_treatment_drift_status(changed_treatment, fit_treatment)
        == "Changed since fit"
    )
    assert outcome_groups_drift_dataframe([renamed], meta).iloc[0]["drift_status"] == (
        "Fitted and current"
    )
    assert has_blocking_drift(
        [],
        meta,
        outcome_groups=[changed],
        outcome_group_treatments=[changed_treatment],
    )
