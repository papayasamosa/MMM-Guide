"""WP7 regression coverage for DNA dimensions and graph-target semantics."""

import pytest

from ancestry_mmm.core.causal_graph import (
    EDGE_ROLE_CROSS_PRODUCT_HALO,
    GRAPH_STATUS_APPROVED,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_OUTCOME,
    CausalEdge,
    CausalGraph,
    CausalNode,
)
from ancestry_mmm.core.graph_model_compiler import (
    UnsupportedGraphStructureError,
    resolve_pathway_masks_preferring_graph,
)
from ancestry_mmm.core.outcomes import (
    DNA,
    METRIC_KEY_DNA_KIT_SALE,
    SEGMENT_DIMENSION_DNA_ACTIVATION_STATUS,
    SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
    SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
    SEGMENT_DIMENSION_UNSPECIFIED,
    OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
    OutcomeDefinition,
    OutcomeGroupDefinition,
    OutcomeGroupTreatment,
    validate_outcome_group_definitions,
    validate_outcome_group_treatments,
)
from ancestry_mmm.core.pathways import MediaOutcomePathway


def _dna_outcome(
    outcome_id: str,
    segment: str,
    segment_dimension: str,
    *,
    role: str = "primary",
) -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id=outcome_id,
        product=DNA,
        segment=segment,
        metric="Kit sale",
        source_column=outcome_id,
        unit="kit",
        role=role,
        segment_dimension=segment_dimension,
    )


def _dna_group(
    group_id: str,
    label: str,
    segment_dimension: str,
    members: tuple[str, ...],
) -> OutcomeGroupDefinition:
    return OutcomeGroupDefinition(
        group_id=group_id,
        group_label=label,
        product=DNA,
        outcome_family_key=METRIC_KEY_DNA_KIT_SALE,
        segment_dimension=segment_dimension,
        member_outcome_ids=members,
    )


def test_customer_relationship_purchase_recipient_and_activation_groups_are_distinct():
    outcomes = [
        _dna_outcome(
            "dna_existing_fh",
            "Existing Family History Customer",
            SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
        ),
        _dna_outcome(
            "dna_someone_else",
            "Someone Else",
            SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
        ),
        _dna_outcome(
            "dna_self_activated",
            "Self-activated",
            SEGMENT_DIMENSION_DNA_ACTIVATION_STATUS,
        ),
    ]
    groups = [
        _dna_group(
            "dna_by_relationship",
            "DNA kit sales by customer relationship",
            SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
            ("dna_existing_fh",),
        ),
        _dna_group(
            "dna_by_recipient",
            "DNA kit sales by purchase recipient",
            SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
            ("dna_someone_else",),
        ),
        _dna_group(
            "dna_by_activation",
            "DNA kit sales by activation status",
            SEGMENT_DIMENSION_DNA_ACTIVATION_STATUS,
            ("dna_self_activated",),
        ),
    ]

    assert validate_outcome_group_definitions(groups, outcomes=outcomes) == []


def test_purchase_recipient_member_cannot_be_relabelled_as_activation_status():
    outcome = _dna_outcome(
        "dna_someone_else",
        "Someone Else",
        SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
    )
    activation_group = _dna_group(
        "dna_by_activation",
        "DNA kit sales by activation status",
        SEGMENT_DIMENSION_DNA_ACTIVATION_STATUS,
        (outcome.outcome_id,),
    )

    errors = validate_outcome_group_definitions([activation_group], outcomes=[outcome])

    assert any("segment_dimension" in error for error in errors)


def test_alternative_dna_partitions_cannot_both_be_additive():
    outcomes = [
        _dna_outcome(
            "dna_existing_fh",
            "Existing Family History Customer",
            SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
        ),
        _dna_outcome(
            "dna_someone_else",
            "Someone Else",
            SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
        ),
    ]
    groups = [
        _dna_group(
            "dna_by_relationship",
            "DNA kit sales by customer relationship",
            SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
            ("dna_existing_fh",),
        ),
        _dna_group(
            "dna_by_recipient",
            "DNA kit sales by purchase recipient",
            SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
            ("dna_someone_else",),
        ),
    ]
    treatments = [
        OutcomeGroupTreatment(
            group_id=group.group_id,
            treatment=OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
        )
        for group in groups
    ]

    errors = validate_outcome_group_treatments(
        treatments, groups=groups, outcomes=outcomes
    )

    assert any("alternative outcome groups" in error for error in errors)


def test_unresolved_or_diagnostic_dna_members_are_not_silently_additive():
    outcome = _dna_outcome(
        "dna_unresolved",
        "Unresolved",
        SEGMENT_DIMENSION_UNSPECIFIED,
        role="diagnostic",
    )
    group = _dna_group(
        "dna_unresolved_group",
        "DNA unresolved states",
        SEGMENT_DIMENSION_UNSPECIFIED,
        (outcome.outcome_id,),
    )
    treatment = OutcomeGroupTreatment(
        group_id=group.group_id,
        treatment=OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
    )

    errors = validate_outcome_group_treatments(
        [treatment], groups=[group], outcomes=[outcome]
    )

    assert any("unresolved or diagnostic" in error for error in errors)


def _multi_target_halo_graph() -> CausalGraph:
    return CausalGraph(
        graph_id="dna-multi-target-halo",
        graph_version=1,
        status=GRAPH_STATUS_APPROVED,
        nodes=[
            CausalNode(node_id="DNA_Media", role=NODE_ROLE_INTERVENTION, product=DNA),
            CausalNode(
                node_id="fh_gsa_dna_cross_sell",
                role=NODE_ROLE_OUTCOME,
                product="Family History",
            ),
            CausalNode(
                node_id="fh_nbt_dna_cross_sell",
                role=NODE_ROLE_OUTCOME,
                product="Family History",
            ),
        ],
        edges=[
            CausalEdge(
                source_node_id="DNA_Media",
                target_node_id="fh_gsa_dna_cross_sell",
                role=EDGE_ROLE_CROSS_PRODUCT_HALO,
                lag_type="fixed_weeks",
                lag_weeks=4,
            ),
            CausalEdge(
                source_node_id="DNA_Media",
                target_node_id="fh_nbt_dna_cross_sell",
                role=EDGE_ROLE_CROSS_PRODUCT_HALO,
                lag_type="fixed_weeks",
                lag_weeks=4,
            ),
        ],
    )


def test_approved_graph_keeps_multiple_fh_halo_targets_distinct():
    graph = _multi_target_halo_graph()
    masks = resolve_pathway_masks_preferring_graph(
        causal_graph=graph,
        outcome_ids=["fh_gsa_dna_cross_sell", "fh_nbt_dna_cross_sell"],
        channels=["DNA_Media"],
        pathways=[
            MediaOutcomePathway(
                channel="DNA_Media",
                source_product=DNA,
                target_outcome_id="legacy_single_target",
                component_type="excluded",
                role="excluded",
            )
        ],
        channel_products={"DNA_Media": DNA},
        outcome_products={
            "fh_gsa_dna_cross_sell": "Family History",
            "fh_nbt_dna_cross_sell": "Family History",
        },
        fitted_outcome_ids=["fh_gsa_dna_cross_sell", "fh_nbt_dna_cross_sell"],
        diagnostic_only_outcome_ids=[],
        dna_channel_idx=[0],
        dna_outcome_id="fh_gsa_dna_cross_sell",
        direct_dna_outcome_ids=["fh_gsa_dna_cross_sell"],
        dna_lag_weeks=4,
    )

    assert masks.active_channels_by_outcome == {
        "fh_gsa_dna_cross_sell": ["DNA_Media"],
        "fh_nbt_dna_cross_sell": ["DNA_Media"],
    }
    assert {component.outcome_id for component in masks.components} == {
        "fh_gsa_dna_cross_sell",
        "fh_nbt_dna_cross_sell",
    }


def test_graph_target_missing_from_fit_is_blocked_before_model_compilation():
    graph = _multi_target_halo_graph()

    with pytest.raises(UnsupportedGraphStructureError, match="not in the fitted"):
        resolve_pathway_masks_preferring_graph(
            causal_graph=graph,
            outcome_ids=["fh_gsa_dna_cross_sell"],
            channels=["DNA_Media"],
            pathways=[],
            channel_products={"DNA_Media": DNA},
            outcome_products={"fh_gsa_dna_cross_sell": "Family History"},
            fitted_outcome_ids=["fh_gsa_dna_cross_sell"],
            diagnostic_only_outcome_ids=[],
            dna_channel_idx=[0],
            dna_outcome_id="fh_gsa_dna_cross_sell",
            direct_dna_outcome_ids=["fh_gsa_dna_cross_sell"],
            dna_lag_weeks=4,
        )


def test_no_graph_keeps_legacy_single_target_pathway_compatibility():
    pathway = MediaOutcomePathway(
        channel="DNA_Media",
        source_product=DNA,
        target_outcome_id="fh_gsa_dna_cross_sell",
        component_type="cross_product",
        role="active_cross_product",
        lag_type="fixed_weeks",
        lag_weeks=4,
    )
    masks = resolve_pathway_masks_preferring_graph(
        causal_graph=None,
        outcome_ids=["fh_gsa_dna_cross_sell"],
        channels=["DNA_Media"],
        pathways=[pathway],
        channel_products={"DNA_Media": DNA},
        outcome_products={"fh_gsa_dna_cross_sell": "Family History"},
        fitted_outcome_ids=["fh_gsa_dna_cross_sell"],
        diagnostic_only_outcome_ids=[],
        dna_channel_idx=[0],
        dna_outcome_id="fh_gsa_dna_cross_sell",
        direct_dna_outcome_ids=["fh_gsa_dna_cross_sell"],
        dna_lag_weeks=4,
    )

    assert masks.active_channels_by_outcome == {"fh_gsa_dna_cross_sell": ["DNA_Media"]}
