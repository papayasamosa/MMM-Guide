"""WP6 draw-level semantic outcome-total regression tests."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.outcome_group_totals import (
    aggregate_attribution_group_rows,
    aggregate_outcome_group_draws,
    aggregate_outcome_groups,
    outcome_group_member_shares,
    selected_reporting_ids,
    summarize_outcome_group_draws,
)
from ancestry_mmm.core.attribution import outcome_channel_summary
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.outcomes import (
    DNA,
    FAMILY_HISTORY,
    METRIC_KEY_DNA_KIT_SALE,
    METRIC_KEY_FH_GSA,
    OutcomeGroupDefinition,
    OutcomeGroupTreatment,
)


def _group(*, group_id="fh_gsa_total", members=("fh_new", "fh_winback"), total=None):
    return OutcomeGroupDefinition(
        group_id=group_id,
        group_label="Family History GSA",
        product=FAMILY_HISTORY,
        outcome_family_key=METRIC_KEY_FH_GSA,
        segment_dimension="fh_customer_segment",
        member_outcome_ids=members,
        supplied_total_outcome_id=total,
    )


def _treatment(group_id, treatment):
    return OutcomeGroupTreatment(group_id=group_id, treatment=treatment)


def _draws():
    return pd.DataFrame(
        {
            "market": ["UK"] * 6,
            "channel": ["TV"] * 6,
            "posterior_draw": [0, 0, 0, 1, 1, 1],
            "outcome_id": [
                "fh_new",
                "fh_winback",
                "fh_gsa_supplied",
                "fh_new",
                "fh_winback",
                "fh_gsa_supplied",
            ],
            "incremental_response": [1.0, 10.0, 99.0, 3.0, 20.0, 99.0],
            "incremental_value": [2.0, 30.0, 99.0, 6.0, 60.0, 99.0],
            # The same channel spend is present on every outcome row; it must
            # remain one spend value in the grouped row.
            "reporting_currency_spend": [100.0] * 6,
        }
    )


def test_components_joint_aggregates_every_draw_before_summary():
    group = _group(total="fh_gsa_supplied")
    treatment = _treatment(group.group_id, "components_joint")
    grouped = aggregate_outcome_group_draws(
        _draws(), [group], [treatment], by=["market", "channel"]
    )
    totals = grouped[grouped["outcome_id"] == group.group_id].sort_values(
        "posterior_draw"
    )
    assert totals["incremental_response"].tolist() == [11.0, 23.0]
    assert totals["incremental_value"].tolist() == [32.0, 66.0]
    assert totals["reporting_currency_spend"].tolist() == [100.0, 100.0]

    summary = summarize_outcome_group_draws(
        _draws(),
        [group],
        [treatment],
        by=["market", "channel"],
        measures=["incremental_response"],
        cred_mass=0.5,
    )
    row = summary.iloc[0]
    assert row["incremental_response_posterior_mean"] == pytest.approx(17.0)
    assert row["incremental_response_posterior_median"] == pytest.approx(17.0)
    assert row["incremental_response_lower_interval"] == pytest.approx(
        11.0 + 0.25 * 12.0
    )
    assert row["incremental_response_upper_interval"] == pytest.approx(
        11.0 + 0.75 * 12.0
    )
    # Summing independently summarised members would give different interval
    # endpoints; only the two draw-level totals above are authoritative.
    assert row["incremental_response_upper_interval"] != pytest.approx(10.0 + 20.0)


def test_total_only_uses_supplied_total_and_excludes_exact_components():
    group = _group(total="fh_gsa_supplied")
    grouped = aggregate_outcome_group_draws(
        _draws(),
        [group],
        [_treatment(group.group_id, "total_only")],
        by=["market", "channel"],
        strict=True,
    )
    assert set(grouped["outcome_id"]) == {group.group_id}
    assert grouped["incremental_response"].tolist() == [99.0, 99.0]
    assert set(grouped["outcome_group_source"]) == {"supplied_total"}


def test_legacy_no_group_path_is_an_exact_copy():
    draws = _draws()
    result = aggregate_outcome_groups(draws)
    pd.testing.assert_frame_equal(result, draws)


def test_generic_dna_group_and_member_shares_reconcile():
    group = OutcomeGroupDefinition(
        group_id="dna_kit_by_relationship",
        group_label="DNA kit sales by customer relationship",
        product=DNA,
        outcome_family_key=METRIC_KEY_DNA_KIT_SALE,
        segment_dimension="dna_customer_relationship",
        member_outcome_ids=("dna_new", "dna_existing"),
    )
    draws = pd.DataFrame(
        {
            "market": ["UK", "UK", "UK", "UK"],
            "posterior_draw": [0, 0, 1, 1],
            "outcome_id": ["dna_new", "dna_existing", "dna_new", "dna_existing"],
            "incremental_response": [2.0, 3.0, 4.0, 6.0],
        }
    )
    grouped = aggregate_outcome_group_draws(
        draws,
        [group],
        [_treatment(group.group_id, "components_joint")],
        by=["market"],
    )
    assert grouped.query("outcome_id == 'dna_kit_by_relationship'")[
        "incremental_response"
    ].tolist() == [5.0, 10.0]
    shares = outcome_group_member_shares(draws, group, by=["market"])
    assert shares.groupby("posterior_draw")[
        "member_share"
    ].sum().to_numpy() == pytest.approx([1.0, 1.0])


def test_reporting_selection_replaces_members_without_double_counting():
    group = _group()
    selected = selected_reporting_ids(
        ["fh_new", "fh_winback"],
        [group],
        [_treatment(group.group_id, "components_joint")],
    )
    assert selected == {group.group_id}


def test_attribution_group_rows_sum_response_and_value_but_not_spend():
    group = _group()
    rows = pd.DataFrame(
        {
            "channel": ["TV", "TV"],
            "outcome_id": ["fh_new", "fh_winback"],
            "spend": [100.0, 100.0],
            "volume_contribution": [5.0, 7.0],
            "value_contribution": [10.0, 21.0],
            "ltv": [2.0, 3.0],
        }
    )
    result = aggregate_attribution_group_rows(
        rows,
        [group],
        [_treatment(group.group_id, "components_joint")],
        by=["channel"],
    )
    total = result[result["outcome_id"] == group.group_id].iloc[0]
    assert total["volume_contribution"] == pytest.approx(12.0)
    assert total["value_contribution"] == pytest.approx(31.0)
    assert total["spend"] == pytest.approx(100.0)
    assert total["cpa"] == pytest.approx(100.0 / 12.0)
    assert np.isnan(total["ltv"])


def test_attribution_summary_uses_fit_group_and_keeps_channel_spend_once():
    group = _group(total="fh_gsa_supplied")
    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=["fh_new", "fh_winback"],
        channels=["TV"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="fh_new",
        dna_lag_weeks=0,
        unpooled_markets=[],
        control_names=[],
        outcome_groups_at_fit=[group],
        outcome_group_treatments_at_fit=[
            _treatment(group.group_id, "components_joint")
        ],
    )
    contributions = {
        "channel_contributions": {"TV": np.array([[1.0, 2.0], [3.0, 4.0]])}
    }
    summary = outcome_channel_summary(
        {"X_media": np.ones((2, 1))},
        meta,
        None,
        contributions=contributions,
        ltv={"fh_new": 2.0, "fh_winback": 3.0},
    )
    total = summary[summary["outcome_id"] == group.group_id].iloc[0]
    assert total["volume_contribution"] == pytest.approx(10.0)
    assert total["spend"] == pytest.approx(2.0)
    assert total["cpa"] == pytest.approx(0.2)
