"""WP4 tests for outcome-source draft import and catalogue adoption."""

from ancestry_mmm.core.outcome_import import (
    OUTCOME_SOURCE_STATUS_V1_INCOMPLETE,
    OUTCOME_SOURCE_STATUS_V2_DRAFT,
    adopt_outcome_source_draft,
    compare_outcome_catalogues,
    interpret_outcome_source,
)
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
    OutcomeGroupDefinition,
    SEGMENT_DIMENSION_FH_CUSTOMER,
)


def _outcome(outcome_id: str, segment: str, column: str) -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id=outcome_id,
        product=FAMILY_HISTORY,
        segment=segment,
        metric="GSA",
        metric_key=METRIC_KEY_FH_GSA,
        segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
        source_column=column,
    )


def _catalogue() -> tuple[
    tuple[OutcomeDefinition, ...], tuple[OutcomeGroupDefinition, ...]
]:
    outcomes = (
        _outcome("fh_gsa_new", "New", "gsa_new"),
        _outcome("fh_gsa_dna_cross_sell", "DNA cross-sell", "gsa_dna"),
        _outcome("fh_gsa_winback", "Winback", "gsa_winback"),
    )
    groups = (
        OutcomeGroupDefinition(
            group_id="fh_gsa_by_customer_segment",
            group_label="Family History GSA",
            product=FAMILY_HISTORY,
            outcome_family_key=METRIC_KEY_FH_GSA,
            segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
            member_outcome_ids=tuple(item.outcome_id for item in outcomes),
        ),
    )
    return outcomes, groups


def test_v2_source_is_a_draft_and_never_approval() -> None:
    outcomes, groups = _catalogue()
    imported = interpret_outcome_source(
        schema_version="standard-source-pack-v2",
        outcome_definitions=outcomes,
        outcome_groups=groups,
    )

    assert imported.status == OUTCOME_SOURCE_STATUS_V2_DRAFT
    assert imported.is_seedable_draft
    assert imported.has_approval is False
    assert imported.outcome_definitions == outcomes
    assert imported.outcome_groups == groups

    adopted = adopt_outcome_source_draft(imported)
    assert adopted.outcome_definitions == outcomes
    assert adopted.outcome_groups == groups
    assert adopted.outcome_approvals == ()


def test_v1_source_is_clear_incomplete_state_and_not_seedable() -> None:
    imported = interpret_outcome_source(
        schema_version="standard-source-pack-v1",
        outcome_definitions=(
            OutcomeDefinition(
                outcome_id="legacy_name",
                product="",
                segment="",
                metric="",
                source_column="legacy_value",
                included_in_fit=False,
            ),
        ),
    )

    assert imported.status == OUTCOME_SOURCE_STATUS_V1_INCOMPLETE
    assert imported.is_seedable_draft is False
    assert imported.outcome_definitions == ()
    assert "legacy/incomplete v1" in " ".join(imported.warnings)


def test_existing_catalogue_preview_does_not_mutate_or_auto_adopt() -> None:
    current_outcomes, current_groups = _catalogue()
    source_outcomes = tuple(
        _outcome(item.outcome_id, item.segment, item.source_column)
        for item in current_outcomes
    )
    source_outcomes = source_outcomes + (
        _outcome("fh_gsa_new_customer", "New customer", "gsa_new_customer"),
    )
    source_groups = (
        OutcomeGroupDefinition(
            group_id=current_groups[0].group_id,
            group_label="Renamed for analysts",
            product=current_groups[0].product,
            outcome_family_key=current_groups[0].outcome_family_key,
            segment_dimension=current_groups[0].segment_dimension,
            member_outcome_ids=current_groups[0].member_outcome_ids,
        ),
    )
    preview = compare_outcome_catalogues(
        current_outcomes,
        source_outcomes,
        current_groups,
        source_groups,
    )

    assert preview.source_only_outcome_ids == ("fh_gsa_new_customer",)
    assert preview.changed_outcome_ids == ()
    assert preview.changed_group_ids == ()
    assert preview.has_changes
    assert [item.outcome_id for item in current_outcomes] == [
        "fh_gsa_new",
        "fh_gsa_dna_cross_sell",
        "fh_gsa_winback",
    ]


def test_calculation_relevant_source_change_is_previewed() -> None:
    current_outcomes, current_groups = _catalogue()
    changed = list(current_outcomes)
    changed[0] = _outcome("fh_gsa_new", "New", "gsa_new_v2")
    preview = compare_outcome_catalogues(
        current_outcomes,
        changed,
        current_groups,
        current_groups,
    )

    assert preview.changed_outcome_ids == ("fh_gsa_new",)
    assert preview.current_only_outcome_ids == ()
    assert preview.source_only_group_ids == ()
