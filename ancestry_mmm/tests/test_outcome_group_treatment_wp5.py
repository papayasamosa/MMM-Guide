"""WP5 tests for governed outcome-group model treatment semantics."""

from ancestry_mmm.core.outcomes import (
    DNA,
    FAMILY_HISTORY,
    METRIC_KEY_DNA_KIT_SALE,
    METRIC_KEY_FH_GSA,
    OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
    OUTCOME_GROUP_TREATMENT_DESCRIPTIVE_ONLY,
    OUTCOME_GROUP_TREATMENT_TOTAL_ONLY,
    OUTCOME_GROUP_TREATMENT_UNCONFIGURED,
    OutcomeDefinition,
    OutcomeGroupDefinition,
    OutcomeGroupTreatment,
    SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
    SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
    SEGMENT_DIMENSION_FH_CUSTOMER,
    validate_outcome_group_treatments,
)


def _outcome(
    outcome_id: str,
    *,
    product: str = FAMILY_HISTORY,
    metric: str = "GSA",
    metric_key: str = METRIC_KEY_FH_GSA,
    segment: str = "New",
    segment_dimension: str = SEGMENT_DIMENSION_FH_CUSTOMER,
    included_in_fit: bool = True,
) -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id=outcome_id,
        product=product,
        segment=segment,
        metric=metric,
        metric_key=metric_key,
        source_column=outcome_id,
        segment_dimension=segment_dimension,
        included_in_fit=included_in_fit,
    )


def _fh_group(*, supplied_total: str | None = None) -> OutcomeGroupDefinition:
    return OutcomeGroupDefinition(
        group_id="fh_gsa_by_customer_segment",
        group_label="Family History GSA",
        product=FAMILY_HISTORY,
        outcome_family_key=METRIC_KEY_FH_GSA,
        segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
        member_outcome_ids=("fh_new", "fh_cross_sell", "fh_winback"),
        supplied_total_outcome_id=supplied_total,
    )


def test_components_joint_rejects_exact_supplied_total_in_same_fit():
    group = _fh_group(supplied_total="fh_total")
    outcomes = [
        _outcome("fh_new"),
        _outcome("fh_cross_sell", segment="DNA cross-sell"),
        _outcome("fh_winback", segment="Winback"),
        _outcome("fh_total", segment="All"),
    ]
    errors = validate_outcome_group_treatments(
        [
            OutcomeGroupTreatment(
                group_id=group.group_id,
                treatment=OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
            )
        ],
        groups=[group],
        outcomes=outcomes,
    )
    assert any("components_joint" in error and "fh_total" in error for error in errors)


def test_components_joint_can_keep_supplied_total_as_reconciliation_evidence():
    group = _fh_group(supplied_total="fh_total")
    outcomes = [
        _outcome("fh_new"),
        _outcome("fh_cross_sell", segment="DNA cross-sell"),
        _outcome("fh_winback", segment="Winback"),
        _outcome("fh_total", segment="All", included_in_fit=False),
    ]
    assert (
        validate_outcome_group_treatments(
            [
                OutcomeGroupTreatment(
                    group_id=group.group_id,
                    treatment=OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
                )
            ],
            groups=[group],
            outcomes=outcomes,
        )
        == []
    )


def test_total_only_requires_and_fits_the_supplied_total_without_components():
    group = _fh_group(supplied_total="fh_total")
    outcomes = [
        _outcome("fh_new", included_in_fit=False),
        _outcome("fh_cross_sell", segment="DNA cross-sell", included_in_fit=False),
        _outcome("fh_winback", segment="Winback", included_in_fit=False),
        _outcome("fh_total", segment="All"),
    ]
    assert (
        validate_outcome_group_treatments(
            [
                OutcomeGroupTreatment(
                    group_id=group.group_id,
                    treatment=OUTCOME_GROUP_TREATMENT_TOTAL_ONLY,
                )
            ],
            groups=[group],
            outcomes=outcomes,
        )
        == []
    )

    no_total = OutcomeGroupDefinition(
        group_id="no_total",
        group_label="No supplied total",
        product=FAMILY_HISTORY,
        outcome_family_key=METRIC_KEY_FH_GSA,
        segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
        member_outcome_ids=("fh_new",),
    )
    errors = validate_outcome_group_treatments(
        [
            OutcomeGroupTreatment(
                group_id=no_total.group_id,
                treatment=OUTCOME_GROUP_TREATMENT_TOTAL_ONLY,
            )
        ],
        groups=[no_total],
        outcomes=[_outcome("fh_new")],
    )
    assert any("total_only" in error and "supplied total" in error for error in errors)


def test_alternative_dna_partitions_cannot_both_be_additive():
    relationship = OutcomeGroupDefinition(
        group_id="dna_by_relationship",
        group_label="DNA kit sales by customer relationship",
        product=DNA,
        outcome_family_key=METRIC_KEY_DNA_KIT_SALE,
        segment_dimension=SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
        member_outcome_ids=("dna_new", "dna_existing"),
    )
    recipient = OutcomeGroupDefinition(
        group_id="dna_by_recipient",
        group_label="DNA kit sales by purchase recipient",
        product=DNA,
        outcome_family_key=METRIC_KEY_DNA_KIT_SALE,
        segment_dimension=SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
        member_outcome_ids=("dna_self", "dna_other"),
    )
    outcomes = [
        _outcome(
            "dna_new",
            product=DNA,
            metric="Kit sale",
            metric_key=METRIC_KEY_DNA_KIT_SALE,
            segment="New Customer",
            segment_dimension=SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
        ),
        _outcome(
            "dna_existing",
            product=DNA,
            metric="Kit sale",
            metric_key=METRIC_KEY_DNA_KIT_SALE,
            segment="Existing FH Customer",
            segment_dimension=SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
        ),
        _outcome(
            "dna_self",
            product=DNA,
            metric="Kit sale",
            metric_key=METRIC_KEY_DNA_KIT_SALE,
            segment="Self",
            segment_dimension=SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
        ),
        _outcome(
            "dna_other",
            product=DNA,
            metric="Kit sale",
            metric_key=METRIC_KEY_DNA_KIT_SALE,
            segment="Someone else",
            segment_dimension=SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
        ),
    ]
    treatments = [
        OutcomeGroupTreatment(
            group_id=relationship.group_id,
            treatment=OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
        ),
        OutcomeGroupTreatment(
            group_id=recipient.group_id,
            treatment=OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
        ),
    ]
    errors = validate_outcome_group_treatments(
        treatments, groups=[relationship, recipient], outcomes=outcomes
    )
    assert any("alternative outcome groups" in error for error in errors)

    descriptive = [
        treatments[0],
        OutcomeGroupTreatment(
            group_id=recipient.group_id,
            treatment=OUTCOME_GROUP_TREATMENT_DESCRIPTIVE_ONLY,
        ),
    ]
    assert (
        validate_outcome_group_treatments(
            descriptive, groups=[relationship, recipient], outcomes=outcomes
        )
        == []
    )


def test_unconfigured_is_safe_and_legacy_no_group_state_remains_valid():
    group = _fh_group()
    assert (
        validate_outcome_group_treatments(
            [
                OutcomeGroupTreatment(
                    group_id=group.group_id,
                    treatment=OUTCOME_GROUP_TREATMENT_UNCONFIGURED,
                )
            ],
            groups=[group],
            outcomes=[_outcome("fh_new")],
        )
        == []
    )
    assert validate_outcome_group_treatments([], groups=[], outcomes=[]) == []
