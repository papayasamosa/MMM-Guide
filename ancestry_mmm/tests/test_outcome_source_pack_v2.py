"""REQ-DATAIN-002 WP2 tests for Outcomes source-pack v2 and v1 migration."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from ancestry_mmm.core.outcome_approval import fingerprint_outcome_definition
from ancestry_mmm.core.outcomes import (
    DNA,
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    SEGMENT_DIMENSION_FH_CUSTOMER,
    SEGMENT_DIMENSION_UNSPECIFIED,
    OutcomeDefinition,
)
from ancestry_mmm.data.templates import (
    OUTCOMES_TEMPLATE_SCHEMA_VERSION,
    STANDARD_TEMPLATE_SCHEMA_VERSION,
    canonicalize_standard_workbook,
    outcome_completeness_metadata_from_table,
    outcome_definitions_from_dictionary,
    outcome_groups_from_dictionary,
    parse_standard_workbook,
)


def _write_workbook(tables: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, table in tables.items():
            table.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()


def _outcomes_frame(*columns: str) -> pd.DataFrame:
    values = {"period_start": ["2026-01-05", "2026-01-12"], "market": ["UK", "AU"]}
    values.update({column: [10, 12] for column in columns})
    return pd.DataFrame(values)


def _v2_dictionary(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _fh_gsa_rows() -> list[dict[str, object]]:
    return [
        {
            "outcome_id": "fh_gsa_new",
            "source_column": "fh_gsa_new",
            "product": FAMILY_HISTORY,
            "metric_key": METRIC_KEY_FH_GSA,
            "metric": "GSA",
            "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
            "segment": "New",
            "outcome_group_id": "fh_gsa_by_customer_segment",
            "outcome_group_label": "Family History GSA",
            "outcome_family_key": METRIC_KEY_FH_GSA,
            "group_aggregation": "sum",
            "definition_version": "1.0",
        },
        {
            "outcome_id": "fh_gsa_dna_cross_sell",
            "source_column": "fh_gsa_dna_cross_sell",
            "product": FAMILY_HISTORY,
            "metric_key": METRIC_KEY_FH_GSA,
            "metric": "GSA",
            "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
            "segment": "DNA cross-sell",
            "outcome_group_id": "fh_gsa_by_customer_segment",
            "outcome_group_label": "Family History GSA",
            "outcome_family_key": METRIC_KEY_FH_GSA,
            "group_aggregation": "sum",
            "definition_version": "1.0",
        },
        {
            "outcome_id": "fh_gsa_winback",
            "source_column": "fh_gsa_winback",
            "product": FAMILY_HISTORY,
            "metric_key": METRIC_KEY_FH_GSA,
            "metric": "GSA",
            "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
            "segment": "Winback",
            "outcome_group_id": "fh_gsa_by_customer_segment",
            "outcome_group_label": "Family History GSA",
            "outcome_family_key": METRIC_KEY_FH_GSA,
            "group_aggregation": "sum",
            "definition_version": "1.0",
        },
    ]


def test_v2_dictionary_builds_canonical_definitions_and_semantic_group():
    dictionary = _v2_dictionary(_fh_gsa_rows())
    outcomes = _outcomes_frame("fh_gsa_new", "fh_gsa_dna_cross_sell", "fh_gsa_winback")
    workbook = parse_standard_workbook(
        _write_workbook({"outcomes": outcomes, "outcome_dictionary": dictionary}),
        source_id="outcomes-v2",
        filename="outcomes-v2.xlsx",
        logical_domain="outcomes",
    )

    assert workbook.manifest.valid_standard_template
    assert workbook.manifest.template_schema_version == OUTCOMES_TEMPLATE_SCHEMA_VERSION
    bundle = canonicalize_standard_workbook(workbook)
    assert [outcome.outcome_id for outcome in bundle.outcome_definitions] == [
        "fh_gsa_new",
        "fh_gsa_dna_cross_sell",
        "fh_gsa_winback",
    ]
    assert all(
        outcome.segment_dimension == SEGMENT_DIMENSION_FH_CUSTOMER
        for outcome in bundle.outcome_definitions
    )
    assert len(bundle.outcome_groups) == 1
    assert bundle.outcome_groups[0].member_outcome_ids == (
        "fh_gsa_new",
        "fh_gsa_dna_cross_sell",
        "fh_gsa_winback",
    )
    assert "outcome_dictionary" in bundle.raw_tables


def test_explicit_supplied_total_derives_diagnostic_reconciliation_only():
    rows = _fh_gsa_rows()
    for row in rows:
        row["supplied_total_outcome_id"] = "fh_gsa_total"
    total = rows[0].copy()
    total.update(
        outcome_id="fh_gsa_total",
        source_column="fh_gsa_total",
        segment="All",
        outcome_group_id="",
        outcome_group_label="",
        outcome_family_key="",
        group_aggregation="",
        supplied_total_outcome_id="",
    )
    rows.append(total)
    columns = [
        "fh_gsa_new",
        "fh_gsa_dna_cross_sell",
        "fh_gsa_winback",
        "fh_gsa_total",
    ]
    workbook = parse_standard_workbook(
        _write_workbook(
            {
                "outcomes": _outcomes_frame(*columns),
                "outcome_dictionary": _v2_dictionary(rows),
            }
        ),
        source_id="outcomes-total",
        filename="outcomes-total.xlsx",
        logical_domain="outcomes",
    )
    bundle = canonicalize_standard_workbook(workbook)
    assert len(bundle.outcome_reconciliation_groups) == 1
    reconciliation = bundle.outcome_reconciliation_groups[0]
    assert reconciliation.group_id == "fh_gsa_by_customer_segment"
    assert reconciliation.component_outcome_ids == columns[:3]
    assert reconciliation.total_outcome_id == "fh_gsa_total"


def test_v1_dictionary_remains_loadable_but_is_incomplete_and_does_not_infer_ids():
    dictionary = pd.DataFrame(
        {"outcome_id": ["fh_gsa_new"], "source_column": ["fh_gsa_new"]}
    )
    workbook = parse_standard_workbook(
        _write_workbook(
            {
                "outcomes": _outcomes_frame("fh_gsa_new"),
                "outcome_dictionary": dictionary,
            }
        ),
        source_id="outcomes-v1",
        filename="outcomes-v1.xlsx",
        logical_domain="outcomes",
    )

    assert workbook.manifest.valid_standard_template
    assert workbook.manifest.template_schema_version == STANDARD_TEMPLATE_SCHEMA_VERSION
    assert any("legacy v1" in warning for warning in workbook.manifest.warnings)
    bundle = canonicalize_standard_workbook(workbook)
    legacy = bundle.outcome_definitions[0]
    assert legacy.product == ""
    assert legacy.metric == ""
    assert legacy.metric_key == "custom"
    assert legacy.segment_dimension == SEGMENT_DIMENSION_UNSPECIFIED
    assert legacy.included_in_fit is False
    assert bundle.outcome_groups == ()


def test_outcomes_without_a_dictionary_remain_loadable_as_legacy_incomplete():
    workbook = parse_standard_workbook(
        _write_workbook({"outcomes": _outcomes_frame("fh_gsa_new")}),
        source_id="outcomes-no-dictionary",
        filename="outcomes-no-dictionary.xlsx",
        logical_domain="outcomes",
    )
    assert workbook.manifest.valid_standard_template
    assert workbook.manifest.template_schema_version == STANDARD_TEMPLATE_SCHEMA_VERSION
    assert any(
        "no outcome_dictionary" in warning for warning in workbook.manifest.warnings
    )


def test_v2_parser_rejects_missing_source_column_clearly():
    row = _fh_gsa_rows()[0] | {"source_column": "not_in_outcomes"}
    dictionary = _v2_dictionary([row])
    with pytest.raises(ValueError, match="missing from the outcomes sheet"):
        outcome_definitions_from_dictionary(
            dictionary,
            outcomes=_outcomes_frame("fh_gsa_new"),
            schema_version="standard-source-pack-v2",
        )


def test_v2_parser_rejects_duplicate_outcome_id():
    rows = _fh_gsa_rows()[:1] * 2
    with pytest.raises(ValueError, match="duplicate outcome_id"):
        outcome_definitions_from_dictionary(
            _v2_dictionary(rows), outcomes=_outcomes_frame("fh_gsa_new")
        )


def test_v2_parser_rejects_incompatible_source_reuse_and_product_metric_mismatch():
    first = _fh_gsa_rows()[0]
    reused = first | {
        "outcome_id": "fh_signup_new",
        "metric_key": "fh_signup",
        "metric": "Sign-up",
        "source_column": "fh_gsa_new",
    }
    with pytest.raises(ValueError, match="incompatible outcome definitions"):
        outcome_definitions_from_dictionary(
            _v2_dictionary([first, reused]),
            outcomes=_outcomes_frame("fh_gsa_new"),
        )

    mismatch = first | {
        "outcome_id": "dna_bad_gsa",
        "source_column": "dna_bad_gsa",
        "product": DNA,
    }
    with pytest.raises(ValueError, match="governed for product"):
        outcome_definitions_from_dictionary(
            _v2_dictionary([mismatch]), outcomes=_outcomes_frame("dna_bad_gsa")
        )


def test_group_parser_keeps_gsa_signup_and_nbt_groups_separate():
    rows = []
    for metric_key, metric, group_id, label, outcome_id in (
        (
            METRIC_KEY_FH_GSA,
            "GSA",
            "fh_gsa_by_customer_segment",
            "Family History GSA",
            "gsa_new",
        ),
        (
            "fh_signup",
            "Sign-up",
            "fh_signup_by_customer_segment",
            "Family History sign-ups",
            "signup_new",
        ),
        (
            METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
            "Net Bill Through count",
            "fh_nbt_by_customer_segment",
            "Family History Net Bill Through",
            "nbt_new",
        ),
    ):
        row = _fh_gsa_rows()[0].copy()
        row.update(
            outcome_id=f"fh_{outcome_id}",
            source_column=f"fh_{outcome_id}",
            metric_key=metric_key,
            metric=metric,
            outcome_group_id=group_id,
            outcome_group_label=label,
            outcome_family_key=metric_key,
            definition_version="1.0",
        )
        rows.append(row)
    dictionary = _v2_dictionary(rows)
    outcomes = _outcomes_frame("fh_gsa_new", "fh_signup_new", "fh_nbt_new")
    definitions = outcome_definitions_from_dictionary(dictionary, outcomes=outcomes)
    groups = outcome_groups_from_dictionary(dictionary, outcomes=definitions)
    assert {group.group_id for group in groups} == {
        "fh_gsa_by_customer_segment",
        "fh_signup_by_customer_segment",
        "fh_nbt_by_customer_segment",
    }
    assert {group.outcome_family_key for group in groups} == {
        METRIC_KEY_FH_GSA,
        "fh_signup",
        METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    }


def test_optional_group_is_explicitly_blank_not_inferred():
    row = _fh_gsa_rows()[0].copy()
    row.update(
        outcome_id="dna_purchase_recipient_self",
        source_column="dna_purchase_recipient_self",
        product=DNA,
        metric_key="dna_kit_sale",
        metric="Kit sale",
        segment_dimension="dna_purchase_recipient",
        segment="Self",
        outcome_group_id="",
        outcome_group_label="",
        outcome_family_key="",
        group_aggregation="",
    )
    dictionary = _v2_dictionary([row])
    definitions = outcome_definitions_from_dictionary(
        dictionary, outcomes=_outcomes_frame("dna_purchase_recipient_self")
    )
    assert outcome_groups_from_dictionary(dictionary, outcomes=definitions) == ()


def test_completeness_binds_to_current_nbt_definition_without_creating_approval():
    outcome = OutcomeDefinition(
        outcome_id="fh_nbt_winback",
        product=FAMILY_HISTORY,
        segment="Winback",
        metric="Net Bill Through count",
        metric_key=METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
        source_column="fh_nbt_winback",
        segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
        definition_version="1.0",
        event_definition="Supplied mature NBT count",
        date_basis="signup_date_attributed",
        cohort_or_attribution_basis="signup cohort",
        completeness_or_maturity_policy="12-week maturity",
        exclusions="Test accounts",
        reconciliation_source="Finance supplied extract",
        business_owner="Finance",
    )
    table = pd.DataFrame(
        {
            "outcome_id": ["fh_nbt_winback"],
            "data_as_of_date": ["2026-01-19"],
            "model_start_week": ["2026-01-05"],
            "model_end_week": ["2026-01-12"],
            "latest_complete_net_billthrough_week": ["2026-01-12"],
            "maturity_rule_description": ["12-week maturity"],
            "source_owner": ["Finance"],
        }
    )
    metadata = outcome_completeness_metadata_from_table(table, [outcome])
    assert metadata[
        "fh_nbt_winback"
    ].definition_fingerprint == fingerprint_outcome_definition(outcome)
    assert metadata["fh_nbt_winback"].definition_version == "1.0"
    assert metadata["fh_nbt_winback"].outcome_id == "fh_nbt_winback"


def test_segment_dimension_participates_in_approval_definition_fingerprint():
    base = OutcomeDefinition(
        outcome_id="fh_gsa_new",
        product=FAMILY_HISTORY,
        segment="New",
        metric="GSA",
        metric_key=METRIC_KEY_FH_GSA,
        source_column="fh_gsa_new",
        segment_dimension=SEGMENT_DIMENSION_FH_CUSTOMER,
    )
    changed = OutcomeDefinition.from_dict(
        base.to_dict() | {"segment_dimension": "custom"}
    )
    assert fingerprint_outcome_definition(base) != fingerprint_outcome_definition(
        changed
    )
