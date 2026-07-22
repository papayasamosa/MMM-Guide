"""Tests for core.promotions - structured DNA promotion events
(docs/dna_fh_causal_structure.md, docs/outcomes.md)."""

import pandas as pd
import pytest

from ancestry_mmm.core.promotions import (
    PROMOTION_EVENT_OP,
    PromotionEvent,
    apply_promotion_events_to_frame,
    promotion_events_to_dataframe,
    promotion_events_to_transform_steps,
    promotion_weekly_series,
    transform_steps_to_promotion_events,
    validate_promotion_events,
)
from ancestry_mmm.data.pipeline import TransformStep, apply_pipeline


def _event(**overrides) -> PromotionEvent:
    defaults = dict(
        event_name="Christmas Sale", start_date="2024-12-01", end_date="2024-12-25",
        segment="New Customer", discount_depth=0.2, sale_price=None, intensity=1.0,
    )
    defaults.update(overrides)
    return PromotionEvent(**defaults)


class TestPromotionEventRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        event = _event()
        assert PromotionEvent.from_dict(event.to_dict()) == event

    def test_duration_days_is_inclusive(self):
        event = _event(start_date="2024-12-01", end_date="2024-12-02")
        assert event.duration_days() == 2

    def test_duration_days_returns_none_for_unparseable_dates(self):
        event = _event(start_date="not-a-date", end_date="2024-12-25")
        assert event.duration_days() is None


class TestPromotionEventValidate:
    def test_well_formed_event_has_no_errors(self):
        assert _event().validate() == []

    def test_missing_name_is_an_error(self):
        errors = _event(event_name="").validate()
        assert any("name" in e for e in errors)

    def test_missing_segment_is_an_error(self):
        errors = _event(segment="").validate()
        assert any("segment" in e for e in errors)

    def test_end_before_start_is_an_error(self):
        errors = _event(start_date="2024-12-25", end_date="2024-12-01").validate()
        assert any("before its start date" in e for e in errors)

    def test_unparseable_date_is_an_error(self):
        errors = _event(start_date="not-a-date").validate()
        assert any("unparseable" in e for e in errors)

    def test_discount_depth_out_of_range_is_an_error(self):
        errors = _event(discount_depth=1.5).validate()
        assert any("discount_depth" in e for e in errors)

    def test_discount_depth_none_is_not_an_error(self):
        assert _event(discount_depth=None).validate() == []


class TestValidatePromotionEvents:
    def test_aggregates_errors_across_events(self):
        events = [_event(event_name=""), _event()]
        errors = validate_promotion_events(events)
        assert len(errors) == 1

    def test_empty_list_has_no_errors(self):
        assert validate_promotion_events([]) == []


class TestPromotionWeeklySeries:
    DATES = pd.date_range("2024-11-25", periods=6, freq="W-MON")  # 2024-11-25 .. 2024-12-30

    def test_zero_outside_the_event_window(self):
        series = promotion_weekly_series([_event()], self.DATES, "New Customer")
        assert series[0] == 0.0  # 2024-11-25, before the event starts

    def test_intensity_inside_the_event_window(self):
        series = promotion_weekly_series([_event(intensity=0.5)], self.DATES, "New Customer")
        in_window = (self.DATES >= pd.Timestamp("2024-12-01")) & (self.DATES <= pd.Timestamp("2024-12-25"))
        assert (series[in_window] == 0.5).all()

    def test_only_returns_series_for_the_requested_segment(self):
        events = [_event(segment="New Customer"), _event(segment="Existing FH Customer", intensity=2.0)]
        series = promotion_weekly_series(events, self.DATES, "Existing FH Customer")
        assert series.max() == 2.0

    def test_overlapping_events_for_the_same_segment_compound(self):
        events = [
            _event(event_name="A", intensity=1.0, start_date="2024-12-01", end_date="2024-12-31"),
            _event(event_name="B", intensity=0.5, start_date="2024-12-08", end_date="2024-12-31"),
        ]
        series = promotion_weekly_series(events, self.DATES, "New Customer")
        # 2024-12-09 falls inside both events' windows
        idx = list(self.DATES).index(pd.Timestamp("2024-12-09"))
        assert series[idx] == pytest.approx(1.5)

    def test_no_events_gives_all_zeros(self):
        series = promotion_weekly_series([], self.DATES, "New Customer")
        assert (series == 0.0).all()


class TestApplyPromotionEventsToFrame:
    def test_adds_one_column_per_segment_with_events(self):
        df = pd.DataFrame({"date": pd.date_range("2024-11-25", periods=6, freq="W-MON")})
        events = [_event(segment="New Customer"), _event(segment="Existing FH Customer")]
        out, column_by_segment = apply_promotion_events_to_frame(df, "date", events)
        assert set(column_by_segment) == {"New Customer", "Existing FH Customer"}
        for col in column_by_segment.values():
            assert col in out.columns

    def test_does_not_mutate_the_input_dataframe(self):
        df = pd.DataFrame({"date": pd.date_range("2024-11-25", periods=6, freq="W-MON")})
        original_columns = list(df.columns)
        apply_promotion_events_to_frame(df, "date", [_event()])
        assert list(df.columns) == original_columns

    def test_no_events_gives_no_derived_columns(self):
        df = pd.DataFrame({"date": pd.date_range("2024-11-25", periods=6, freq="W-MON")})
        out, column_by_segment = apply_promotion_events_to_frame(df, "date", [])
        assert column_by_segment == {}
        assert list(out.columns) == list(df.columns)

    def test_derived_column_values_match_promotion_weekly_series(self):
        df = pd.DataFrame({"date": pd.date_range("2024-11-25", periods=6, freq="W-MON")})
        events = [_event(segment="New Customer", intensity=0.7)]
        out, column_by_segment = apply_promotion_events_to_frame(df, "date", events)
        expected = promotion_weekly_series(events, df["date"], "New Customer")
        assert (out[column_by_segment["New Customer"]].to_numpy() == expected).all()


class TestPromotionEventsToDataframe:
    def test_empty_list_gives_empty_dataframe_with_expected_columns(self):
        df = promotion_events_to_dataframe([])
        assert df.empty
        assert "event_name" in df.columns

    def test_has_one_row_per_event(self):
        df = promotion_events_to_dataframe([_event(), _event(event_name="New Year Sale")])
        assert len(df) == 2
        assert set(df["event_name"]) == {"Christmas Sale", "New Year Sale"}


class TestPromotionEventIdentityAndNewFields:
    def test_event_id_is_auto_generated_and_unique(self):
        a, b = _event(), _event()
        assert a.event_id and b.event_id
        assert a.event_id != b.event_id

    def test_explicit_event_id_is_preserved(self):
        event = _event(event_id="fixed-id")
        assert event.event_id == "fixed-id"

    def test_new_fields_default_to_unset(self):
        event = _event()
        assert event.product is None
        assert event.affected_outcome_ids == []
        assert event.market is None
        assert event.transformation_version == 1


class TestPromotionEventsToTransformSteps:
    """PR E.2 #11 - promotion events must become replayable pipeline steps."""

    def test_one_step_per_event(self):
        events = [_event(), _event(event_name="New Year Sale")]
        steps = promotion_events_to_transform_steps(events, date_col="date")
        assert len(steps) == 2
        assert all(isinstance(s, TransformStep) for s in steps)
        assert all(s.op == PROMOTION_EVENT_OP for s in steps)

    def test_step_params_carry_the_full_event_and_date_col(self):
        event = _event(product="Family History", market="UK")
        [step] = promotion_events_to_transform_steps([event], date_col="date")
        assert step.params["event"] == event.to_dict()
        assert step.params["date_col"] == "date"

    def test_no_events_gives_no_steps(self):
        assert promotion_events_to_transform_steps([], date_col="date") == []


class TestTransformStepsToPromotionEvents:
    def test_round_trips_the_event_list(self):
        events = [_event(), _event(event_name="New Year Sale", segment="Existing FH Customer")]
        steps = promotion_events_to_transform_steps(events, date_col="date")
        recovered = transform_steps_to_promotion_events(steps)
        assert recovered == events

    def test_ignores_non_promotion_event_steps(self):
        events = [_event()]
        steps = promotion_events_to_transform_steps(events, date_col="date")
        other_step = TransformStep(op="event_flag", params={"date_col": "date", "new_column": "x", "start": "2024-01-01", "end": "2024-01-02"})
        recovered = transform_steps_to_promotion_events([other_step] + steps)
        assert recovered == events

    def test_empty_steps_gives_empty_events(self):
        assert transform_steps_to_promotion_events([]) == []


class TestResaveReplacesStalePromotionEventSteps:
    """Mirrors the Structure page's Save handler: every save fully replaces
    the prior promotion_event steps with the current event list (filter out
    old promotion_event steps, append fresh ones), while leaving any other
    step type (e.g. from the Transform Pipeline page) untouched. Makes
    re-saving the same or an edited event list idempotent rather than
    accumulating duplicate/stale steps forever."""

    def test_other_step_types_survive_a_resave(self):
        other_step = TransformStep(op="calculated_column", params={"new_column": "x", "expression": "1"})
        old_promo_steps = promotion_events_to_transform_steps([_event()], date_col="date")
        existing = [other_step] + old_promo_steps

        non_promo = [s for s in existing if s.op != PROMOTION_EVENT_OP]
        resaved = non_promo + promotion_events_to_transform_steps([_event(event_name="Updated")], date_col="date")

        assert other_step in resaved
        assert len([s for s in resaved if s.op == PROMOTION_EVENT_OP]) == 1

    def test_removing_all_events_and_resaving_clears_promotion_event_steps(self):
        existing = promotion_events_to_transform_steps([_event()], date_col="date")
        non_promo = [s for s in existing if s.op != PROMOTION_EVENT_OP]
        resaved = non_promo + promotion_events_to_transform_steps([], date_col="date")
        assert resaved == []


class TestPromotionEventPipelineReplay:
    """Required test case: replaying promotion-event pipeline steps against
    raw data reproduces the same derived columns as applying the event list
    directly - the whole point of encoding events as TransformSteps."""

    def test_replay_reproduces_apply_promotion_events_to_frame(self):
        df = pd.DataFrame({"date": pd.date_range("2024-11-25", periods=8, freq="W-MON")})
        events = [
            _event(segment="New Customer", intensity=1.0, start_date="2024-12-01", end_date="2025-01-05"),
            _event(event_name="Boxing Day", segment="New Customer", intensity=0.5, start_date="2024-12-26", end_date="2025-01-05"),
            _event(event_name="FH Sale", segment="Existing FH Customer", intensity=0.3, start_date="2024-12-01", end_date="2024-12-31"),
        ]

        direct, column_by_segment = apply_promotion_events_to_frame(df, "date", events)

        steps = promotion_events_to_transform_steps(events, date_col="date")
        replayed = apply_pipeline(df, steps)

        for seg, col in column_by_segment.items():
            assert (replayed[col].to_numpy() == direct[col].to_numpy()).all(), seg

    def test_replay_is_reproducible_on_refreshed_raw_data(self):
        # The same recorded steps applied to a differently-shaped (but same
        # date range) refreshed raw frame must reproduce the same promo
        # series - the whole point of a *replayable* step, vs. a one-way
        # mutation baked into a specific transformed_data snapshot.
        df = pd.DataFrame({"date": pd.date_range("2024-11-25", periods=6, freq="W-MON"), "spend": [1.0] * 6})
        events = [_event(segment="New Customer", start_date="2024-12-01", end_date="2024-12-31")]
        steps = promotion_events_to_transform_steps(events, date_col="date")

        result_1 = apply_pipeline(df, steps)
        df_refreshed = df.copy()
        df_refreshed["spend"] = df_refreshed["spend"] * 100
        result_2 = apply_pipeline(df_refreshed, steps)

        assert result_1["_promo_event_New Customer"].tolist() == result_2["_promo_event_New Customer"].tolist()
