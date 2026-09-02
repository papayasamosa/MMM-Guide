"""Tests for `core.fh_subscription_events` - the reference implementation
of REQ-OUT-003's approved GSA/Net Bill Through event-level derivation
rules (Decision 1). See that module's docstring for the governance
boundary: this is a tested reference/reconciliation utility, not wired
into any default ingestion or model-training path.

Covers the nine required scenarios named by the business-decision brief:
hard-offer same-day GSA; free-trial GSA on the later bill-through date;
free-trial NBT pulled back to signup date; an unsuccessful trial excluded
from both; a refunded subscriber excluded from NBT (but not GSA); New /
Winback / DNA Cross-sell remaining distinct; the 120-day DNA Cross-sell
rule when derivation is genuinely needed; the 48-month LTR horizon; and
GSA/NBT never silently swapping identity.
"""

import pandas as pd
import pytest

from ancestry_mmm.core.fh_subscription_events import (
    FhComputedOutcome,
    FhSubscriptionEvent,
    OFFER_TYPE_FREE_TRIAL,
    OFFER_TYPE_HARD,
    aggregate_weekly_fh_outcomes,
    compute_fh_outcomes,
    compute_gsa_date,
    compute_net_billthrough_date,
    derive_fh_segment,
)
from ancestry_mmm.core.outcomes import (
    DNA_CROSS_SELL_WINDOW_DAYS,
    FH_LTR_HORIZON_MONTHS,
    FH_SEGMENT_DNA_CROSS_SELL,
    FH_SEGMENT_NEW,
    FH_SEGMENT_WINBACK,
    METRIC_KEY_FH_GSA,
    METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
)


def _hard_offer(**overrides) -> FhSubscriptionEvent:
    values = dict(
        subscriber_id="s1",
        market="UK",
        signup_date="2025-01-06",
        offer_type=OFFER_TYPE_HARD,
        supplied_segment=FH_SEGMENT_NEW,
    )
    values.update(overrides)
    return FhSubscriptionEvent(**values)


def _free_trial(**overrides) -> FhSubscriptionEvent:
    values = dict(
        subscriber_id="s2",
        market="UK",
        signup_date="2025-01-06",
        offer_type=OFFER_TYPE_FREE_TRIAL,
        trial_billthrough_date="2025-01-20",
        supplied_segment=FH_SEGMENT_NEW,
    )
    values.update(overrides)
    return FhSubscriptionEvent(**values)


class TestEventConstruction:
    def test_hard_offer_cannot_carry_a_trial_billthrough_date(self):
        with pytest.raises(ValueError, match="must not carry"):
            _hard_offer(trial_billthrough_date="2025-01-20")

    def test_unknown_offer_type_rejected(self):
        with pytest.raises(ValueError, match="unknown offer_type"):
            _hard_offer(offer_type="something_else")

    def test_unknown_supplied_segment_rejected(self):
        with pytest.raises(ValueError, match="unknown supplied_segment"):
            _hard_offer(supplied_segment="Reactivated")


class TestGsaDate:
    def test_hard_offer_counted_same_day_as_signup(self):
        """Scenario: hard offer counted on sign-up/bill-through date."""
        event = _hard_offer(signup_date="2025-03-10")
        assert compute_gsa_date(event) == pd.Timestamp("2025-03-10")

    def test_successful_free_trial_counted_on_later_gsa_date(self):
        """Scenario: successful free trial counted on the later GSA
        (bill-through) date, not the signup date."""
        event = _free_trial(
            signup_date="2025-01-06", trial_billthrough_date="2025-01-20"
        )
        assert compute_gsa_date(event) == pd.Timestamp("2025-01-20")

    def test_unsuccessful_trial_excluded_from_gsa(self):
        """Scenario: a trial that never bills through is not a GSA."""
        event = _free_trial(trial_billthrough_date=None)
        assert compute_gsa_date(event) is None

    def test_refund_does_not_affect_gsa(self):
        """GSA is a gross acquisition count - refund status is irrelevant
        to it (only NBT nets out refunds)."""
        event = _hard_offer(refunded=True)
        assert compute_gsa_date(event) == pd.Timestamp(event.signup_date)


class TestNetBillthroughDate:
    def test_successful_free_trial_pulled_back_to_signup_date(self):
        """Scenario: for NBT, a successful free trial's date is moved BACK
        to the original sign-up date, not the later bill-through date."""
        event = _free_trial(
            signup_date="2025-01-06", trial_billthrough_date="2025-01-20"
        )
        assert compute_net_billthrough_date(event) == pd.Timestamp("2025-01-06")

    def test_hard_offer_dates_already_align(self):
        event = _hard_offer(signup_date="2025-03-10")
        assert compute_net_billthrough_date(event) == pd.Timestamp("2025-03-10")

    def test_unsuccessful_trial_excluded_from_nbt(self):
        """Scenario: an unsuccessful trial is excluded from NBT too - it
        never became a GSA, so it cannot be netted."""
        event = _free_trial(trial_billthrough_date=None)
        assert compute_net_billthrough_date(event) is None

    def test_refunded_subscriber_excluded_from_nbt(self):
        """Scenario: a refunded subscription is excluded from NBT even
        though it was a genuine GSA - this is what makes NBT "net"."""
        event = _hard_offer(refunded=True)
        assert compute_gsa_date(event) is not None
        assert compute_net_billthrough_date(event) is None

    def test_non_refunded_free_trial_gsa_is_included_in_nbt(self):
        event = _free_trial(refunded=False)
        assert compute_net_billthrough_date(event) == pd.Timestamp(event.signup_date)


class TestSegmentDerivation:
    def test_supplied_segment_is_authoritative(self):
        """REQ-OUT-003 §2: a supplied segment is never independently
        re-derived, even if raw fields would suggest otherwise."""
        event = _hard_offer(
            supplied_segment=FH_SEGMENT_WINBACK,
            dna_kit_purchase_date="2025-01-01",  # would suggest cross-sell if derived
        )
        assert derive_fh_segment(event) == FH_SEGMENT_WINBACK

    def test_new_winback_and_dna_cross_sell_remain_distinct(self):
        """Scenario: New / Winback / DNA Cross-sell remain distinct
        segments."""
        segments = {
            derive_fh_segment(_hard_offer(supplied_segment=FH_SEGMENT_NEW)),
            derive_fh_segment(_hard_offer(supplied_segment=FH_SEGMENT_WINBACK)),
            derive_fh_segment(_hard_offer(supplied_segment=FH_SEGMENT_DNA_CROSS_SELL)),
        }
        assert segments == {
            FH_SEGMENT_NEW,
            FH_SEGMENT_WINBACK,
            FH_SEGMENT_DNA_CROSS_SELL,
        }

    def test_dna_cross_sell_derivation_uses_120_day_window(self):
        """Scenario: DNA Cross-sell uses the 120-day rule when derivation
        is genuinely needed (no supplied segment)."""
        assert DNA_CROSS_SELL_WINDOW_DAYS == 120
        within_window = _hard_offer(
            supplied_segment=None,
            signup_date="2025-05-01",
            dna_kit_purchase_date="2025-01-01",  # 120 days before signup exactly
            prior_fh_subscription=False,
        )
        gap = (pd.Timestamp("2025-05-01") - pd.Timestamp("2025-01-01")).days
        assert gap == 120
        assert derive_fh_segment(within_window) == FH_SEGMENT_DNA_CROSS_SELL

    def test_dna_cross_sell_derivation_excludes_beyond_120_days(self):
        beyond_window = _hard_offer(
            supplied_segment=None,
            signup_date="2025-06-01",
            dna_kit_purchase_date="2025-01-01",  # > 120 days before signup
            prior_fh_subscription=False,
        )
        assert derive_fh_segment(beyond_window) == FH_SEGMENT_NEW

    def test_new_vs_winback_derivation_without_dna_kit(self):
        new_event = _hard_offer(supplied_segment=None, prior_fh_subscription=False)
        winback_event = _hard_offer(supplied_segment=None, prior_fh_subscription=True)
        assert derive_fh_segment(new_event) == FH_SEGMENT_NEW
        assert derive_fh_segment(winback_event) == FH_SEGMENT_WINBACK

    def test_derivation_fails_closed_when_ambiguous(self):
        """No supplied segment, no DNA kit date, no prior-subscription
        flag: refuses to guess rather than defaulting to New."""
        event = _hard_offer(supplied_segment=None, prior_fh_subscription=None)
        with pytest.raises(ValueError, match="refusing to guess"):
            derive_fh_segment(event)

    def test_derivation_fails_closed_on_impossible_dates(self):
        event = _hard_offer(
            supplied_segment=None,
            signup_date="2025-01-01",
            dna_kit_purchase_date="2025-06-01",  # kit purchased AFTER signup
            prior_fh_subscription=False,
        )
        with pytest.raises(ValueError, match="ambiguous"):
            derive_fh_segment(event)

    def test_never_returns_a_fourth_segment(self):
        for event in (
            _hard_offer(supplied_segment=FH_SEGMENT_NEW),
            _hard_offer(supplied_segment=None, prior_fh_subscription=True),
        ):
            assert derive_fh_segment(event) in (
                FH_SEGMENT_NEW,
                FH_SEGMENT_WINBACK,
                FH_SEGMENT_DNA_CROSS_SELL,
            )


class TestComputeFhOutcomes:
    def test_computes_all_events(self):
        events = [_hard_offer(subscriber_id="a"), _free_trial(subscriber_id="b")]
        results = compute_fh_outcomes(events)
        assert len(results) == 2
        assert all(isinstance(r, FhComputedOutcome) for r in results)

    def test_gsa_and_nbt_cannot_be_silently_swapped(self):
        """Scenario: GSA and NBT are two independently-computed dates on
        the same computed-outcome record, never aliased to each other -
        a successful free trial has genuinely different GSA and NBT
        dates."""
        event = _free_trial(
            signup_date="2025-01-06", trial_billthrough_date="2025-01-20"
        )
        [result] = compute_fh_outcomes([event])
        assert result.gsa_date != result.net_billthrough_date
        assert result.gsa_date == pd.Timestamp("2025-01-20")
        assert result.net_billthrough_date == pd.Timestamp("2025-01-06")


class TestWeeklyAggregation:
    def test_aggregates_into_metric_key_vocabulary(self):
        events = [
            _hard_offer(subscriber_id="a", signup_date="2025-01-06"),
            _hard_offer(subscriber_id="b", signup_date="2025-01-07"),
            _free_trial(
                subscriber_id="c",
                signup_date="2025-01-06",
                trial_billthrough_date="2025-01-20",
            ),
        ]
        outcomes = compute_fh_outcomes(events)
        frame = aggregate_weekly_fh_outcomes(outcomes)
        gsa_rows = frame[frame["metric_key"] == METRIC_KEY_FH_GSA]
        nbt_rows = frame[frame["metric_key"] == METRIC_KEY_FH_NET_BILLTHROUGH_COUNT]
        # Two hard-offer GSAs land in the week of 2025-01-06 (Monday); the
        # free trial's GSA lands in the week of 2025-01-20.
        week_of_6th = pd.Timestamp("2025-01-06")
        assert gsa_rows[gsa_rows["week_start"] == week_of_6th]["count"].sum() == 2
        assert (
            gsa_rows[gsa_rows["week_start"] == pd.Timestamp("2025-01-20")][
                "count"
            ].sum()
            == 1
        )
        # All three NBT dates (both hard offers + the trial pulled back to
        # signup) land in the week of 2025-01-06.
        assert nbt_rows[nbt_rows["week_start"] == week_of_6th]["count"].sum() == 3

    def test_missing_is_not_zero(self):
        """A market/segment/metric with zero events is absent, not a
        fabricated zero row (REQ-COVERAGE-001 convention)."""
        outcomes = compute_fh_outcomes([_hard_offer()])
        frame = aggregate_weekly_fh_outcomes(outcomes)
        assert (frame["metric_key"] == METRIC_KEY_FH_NET_BILLTHROUGH_COUNT).any()
        # No row claims a count of 0 anywhere.
        assert not (frame["count"] == 0).any()

    def test_empty_input_returns_empty_frame_with_expected_columns(self):
        frame = aggregate_weekly_fh_outcomes([])
        assert list(frame.columns) == [
            "week_start",
            "market",
            "segment",
            "metric_key",
            "count",
        ]
        assert frame.empty

    def test_week_anchor_buckets_relative_to_supplied_anchor(self):
        events = [_hard_offer(signup_date="2025-01-10")]
        outcomes = compute_fh_outcomes(events)
        frame = aggregate_weekly_fh_outcomes(outcomes, week_anchor="2025-01-06")
        gsa_rows = frame[frame["metric_key"] == METRIC_KEY_FH_GSA]
        assert (gsa_rows["week_start"] == pd.Timestamp("2025-01-06")).all()


class TestFhLtrHorizon:
    def test_48_month_horizon_constant(self):
        """Scenario: the 48-month LTR horizon is used (REQ-OUT-003 §1)."""
        assert FH_LTR_HORIZON_MONTHS == 48
