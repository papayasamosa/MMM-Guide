"""Tests for `core.seo_visibility`: the approved SEO positional-visibility
formula (REQ-SEO-001, Decision 5). See
`docs/seo_positional_visibility_metric_decision_record.md` for the full
options-considered record.
"""

import pytest

from ancestry_mmm.core.coverage import STATE_OBSERVED_ZERO
from ancestry_mmm.core.seo_visibility import (
    CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_EFFICIENCY_STATE,
    DIRECTIONALITY_HIGHER_IS_BETTER,
    SEO_POSITIONAL_VISIBILITY_METRIC,
    GscPositionRow,
    SeoPositionalVisibilityObservation,
    SeoVisibilityMetricDefinition,
    compute_weekly_positional_visibility,
    compute_weekly_positional_visibility_series,
)


class TestGscPositionRow:
    def test_position_must_be_at_least_one_when_impressions_positive(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            GscPositionRow("query a", position=0.5, impressions=10.0)

    def test_zero_impressions_allows_any_recorded_position_placeholder(self):
        # A row with zero impressions carries no real position information;
        # the dataclass does not reject an arbitrary placeholder for it,
        # since compute_weekly_positional_visibility ignores it either way
        # (it contributes 0 to both the numerator and denominator).
        row = GscPositionRow("query a", position=0.0, impressions=0.0)
        assert row.impressions == 0.0

    def test_negative_impressions_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            GscPositionRow("query a", position=1.0, impressions=-1.0)


class TestComputeWeeklyPositionalVisibility:
    def test_single_row_visibility_is_inverse_of_position(self):
        """A single query at position 4 has weighted_avg_position == 4.0
        and visibility_index == 0.25."""
        rows = [
            GscPositionRow("brand term", position=4.0, impressions=100.0, clicks=20.0)
        ]
        obs = compute_weekly_positional_visibility(rows, market="UK", week="2025-01-06")
        assert obs.weighted_avg_position == pytest.approx(4.0)
        assert obs.visibility_index == pytest.approx(0.25)
        assert obs.total_impressions == pytest.approx(100.0)
        assert obs.total_clicks == pytest.approx(20.0)
        assert obs.ctr == pytest.approx(0.2)
        assert obs.coverage_state is None

    def test_higher_is_better_direction(self):
        """Position 1 (best possible rank) yields the maximum visibility_index (1.0);
        a worse position yields a strictly lower value - direction is unambiguous."""
        best = compute_weekly_positional_visibility(
            [GscPositionRow("q", position=1.0, impressions=10.0)],
            market="UK",
            week="2025-01-06",
        )
        worse = compute_weekly_positional_visibility(
            [GscPositionRow("q", position=10.0, impressions=10.0)],
            market="UK",
            week="2025-01-06",
        )
        assert best.visibility_index == pytest.approx(1.0)
        assert worse.visibility_index < best.visibility_index

    def test_aggregation_is_impression_weighted_not_naive_mean(self):
        """The core regression this test guards against: a naive
        unweighted mean of per-row positions would give (2 + 20) / 2 = 11,
        but the impression-weighted average (matching Google's own
        official aggregation formula) correctly reflects that the
        high-impression query dominates the true visibility picture."""
        rows = [
            GscPositionRow("high volume query", position=2.0, impressions=9900.0),
            GscPositionRow("rare long-tail query", position=20.0, impressions=100.0),
        ]
        obs = compute_weekly_positional_visibility(rows, market="UK", week="2025-01-06")
        naive_mean = (2.0 + 20.0) / 2
        weighted = (2.0 * 9900.0 + 20.0 * 100.0) / (9900.0 + 100.0)
        assert obs.weighted_avg_position == pytest.approx(weighted)
        assert obs.weighted_avg_position != pytest.approx(naive_mean)
        assert obs.weighted_avg_position < 3.0  # dominated by the high-volume query

    def test_aggregation_matches_google_bigquery_export_formula_shape(self):
        """Cross-check against Google's own documented BigQuery export
        formula: avg_position = (sum(sum_top_position) / sum(impressions))
        + 1.0, where sum_top_position is 0-indexed. Reformulating our
        1-indexed rows as 0-indexed sum_top_position and re-deriving via
        that formula must agree with our weighted-average computation."""
        rows = [
            GscPositionRow("a", position=3.0, impressions=50.0),
            GscPositionRow("b", position=7.0, impressions=25.0),
        ]
        obs = compute_weekly_positional_visibility(rows, market="UK", week="2025-01-06")
        sum_top_position = sum((r.position - 1.0) * r.impressions for r in rows)
        total_impressions = sum(r.impressions for r in rows)
        google_formula_result = (sum_top_position / total_impressions) + 1.0
        assert obs.weighted_avg_position == pytest.approx(google_formula_result)

    def test_zero_total_impressions_is_missing_not_zero(self):
        """A confirmed zero-impression week: position/visibility are
        undefined (None), never fabricated as 0 or some sentinel."""
        rows = [GscPositionRow("q", position=0.0, impressions=0.0)]
        obs = compute_weekly_positional_visibility(rows, market="UK", week="2025-01-06")
        assert obs.weighted_avg_position is None
        assert obs.visibility_index is None
        assert obs.total_impressions == 0.0
        assert obs.total_clicks == 0.0
        assert obs.ctr is None
        assert obs.coverage_state == STATE_OBSERVED_ZERO

    def test_empty_rows_is_also_missing_not_zero_for_position(self):
        obs = compute_weekly_positional_visibility([], market="UK", week="2025-01-06")
        assert obs.weighted_avg_position is None
        assert obs.visibility_index is None
        assert obs.total_impressions == 0.0
        assert obs.coverage_state == STATE_OBSERVED_ZERO

    def test_visibility_index_bounded_between_zero_exclusive_and_one_inclusive(self):
        for position in (1.0, 2.5, 10.0, 100.0):
            obs = compute_weekly_positional_visibility(
                [GscPositionRow("q", position=position, impressions=1.0)],
                market="UK",
                week="2025-01-06",
            )
            assert 0.0 < obs.visibility_index <= 1.0

    def test_deterministic_and_reproducible(self):
        """Same input always produces the same output - no randomness,
        no hidden state."""
        rows = [
            GscPositionRow("a", position=3.0, impressions=50.0, clicks=5.0),
            GscPositionRow("b", position=7.0, impressions=25.0, clicks=1.0),
        ]
        first = compute_weekly_positional_visibility(
            rows, market="UK", week="2025-01-06"
        )
        second = compute_weekly_positional_visibility(
            rows, market="UK", week="2025-01-06"
        )
        assert first == second

    def test_partially_observed_window(self):
        """A week where only some days/queries have data still computes a
        valid, correctly weighted observation from whatever real rows
        exist - it is never padded with fabricated zero-impression days
        to fill out a 'complete' week. Full partial-window SEO coverage
        POLICY (Decision 3 - e.g. whether such a week should be flagged as
        lower-confidence for modelling) is a separate, later piece of work;
        this test only confirms the formula itself handles a genuinely
        incomplete row set correctly rather than mishandling it."""
        # Only 3 of a hypothetical 7 days in the week actually returned
        # rows (e.g. GSC processing lag for the rest) - the caller passes
        # exactly the rows that exist.
        partial_week_rows = [
            GscPositionRow("day1-query", position=5.0, impressions=40.0),
            GscPositionRow("day2-query", position=6.0, impressions=30.0),
            GscPositionRow("day3-query", position=4.0, impressions=30.0),
        ]
        obs = compute_weekly_positional_visibility(
            partial_week_rows, market="UK", week="2025-01-06"
        )
        expected = (5.0 * 40.0 + 6.0 * 30.0 + 4.0 * 30.0) / 100.0
        assert obs.weighted_avg_position == pytest.approx(expected)
        assert obs.total_impressions == pytest.approx(100.0)
        assert (
            obs.coverage_state is None
        )  # a real, if incomplete, observation - not missing


class TestSeoPositionalVisibilityObservationValidation:
    def test_position_and_visibility_must_be_present_or_absent_together(self):
        with pytest.raises(ValueError, match="present or absent together"):
            SeoPositionalVisibilityObservation(
                market="UK",
                week="2025-01-06",
                weighted_avg_position=5.0,
                visibility_index=None,
                total_impressions=10.0,
                total_clicks=1.0,
                ctr=0.1,
            )

    def test_visibility_must_equal_inverse_of_position(self):
        with pytest.raises(
            ValueError, match="does not equal 1 / weighted_avg_position"
        ):
            SeoPositionalVisibilityObservation(
                market="UK",
                week="2025-01-06",
                weighted_avg_position=4.0,
                visibility_index=0.9,  # wrong - should be 0.25
                total_impressions=10.0,
                total_clicks=1.0,
                ctr=0.1,
            )

    def test_observed_zero_requires_position_absent(self):
        with pytest.raises(ValueError, match="requires weighted_avg_position"):
            SeoPositionalVisibilityObservation(
                market="UK",
                week="2025-01-06",
                weighted_avg_position=4.0,
                visibility_index=0.25,
                total_impressions=0.0,
                total_clicks=0.0,
                ctr=None,
                coverage_state=STATE_OBSERVED_ZERO,
            )

    def test_unknown_coverage_state_rejected(self):
        with pytest.raises(ValueError, match="unknown coverage_state"):
            SeoPositionalVisibilityObservation(
                market="UK",
                week="2025-01-06",
                weighted_avg_position=None,
                visibility_index=None,
                total_impressions=0.0,
                total_clicks=0.0,
                ctr=None,
                coverage_state="not_a_real_state",
            )

    def test_round_trip_through_dict(self):
        obs = compute_weekly_positional_visibility(
            [GscPositionRow("q", position=3.0, impressions=10.0, clicks=1.0)],
            market="UK",
            week="2025-01-06",
        )
        restored = SeoPositionalVisibilityObservation.from_dict(obs.to_dict())
        assert restored == obs


class TestSeriesHelper:
    def test_computes_every_supplied_cell_in_sorted_order(self):
        rows_by_cell = {
            ("UK", "2025-01-13"): [GscPositionRow("q", position=2.0, impressions=10.0)],
            ("UK", "2025-01-06"): [GscPositionRow("q", position=3.0, impressions=10.0)],
            ("AU", "2025-01-06"): [GscPositionRow("q", position=5.0, impressions=10.0)],
        }
        series = compute_weekly_positional_visibility_series(rows_by_cell)
        assert [(o.market, o.week) for o in series] == [
            ("AU", "2025-01-06"),
            ("UK", "2025-01-06"),
            ("UK", "2025-01-13"),
        ]

    def test_never_invents_a_cell_not_supplied(self):
        series = compute_weekly_positional_visibility_series({})
        assert series == []


class TestGovernedMetricDefinition:
    def test_directionality_is_higher_is_better(self):
        """The metric's direction must be unambiguous - explicitly
        higher-is-better, not left for an analyst to infer from GSC's
        native lower-is-better position convention."""
        assert SEO_POSITIONAL_VISIBILITY_METRIC.directionality == (
            DIRECTIONALITY_HIGHER_IS_BETTER
        )

    def test_causal_role_matches_decision_6(self):
        assert SEO_POSITIONAL_VISIBILITY_METRIC.causal_role == (
            CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_EFFICIENCY_STATE
        )

    def test_direction_relative_to_estimand_stays_not_yet_approved(self):
        """Decision 6: estimand-specific per use, never a single global
        setting - the governed definition itself must not pre-decide it."""
        assert (
            SEO_POSITIONAL_VISIBILITY_METRIC.direction_relative_to_estimand
            == "not_yet_approved"
        )

    def test_metric_is_approved(self):
        assert SEO_POSITIONAL_VISIBILITY_METRIC.approval_status == "approved"

    def test_unknown_directionality_rejected(self):
        with pytest.raises(ValueError, match="unknown directionality"):
            SeoVisibilityMetricDefinition(
                metric_name="x",
                source_methodology="x",
                methodology_version="1.0.0",
                unit="index",
                directionality="sideways",
                aggregation_rule="x",
                causal_role=CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_EFFICIENCY_STATE,
            )

    def test_round_trip_through_dict(self):
        restored = SeoVisibilityMetricDefinition.from_dict(
            SEO_POSITIONAL_VISIBILITY_METRIC.to_dict()
        )
        assert restored == SEO_POSITIONAL_VISIBILITY_METRIC
