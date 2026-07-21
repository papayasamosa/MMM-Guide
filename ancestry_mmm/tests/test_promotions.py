"""Tests for core.promotions - structured DNA promotion events
(docs/dna_fh_causal_structure.md, docs/outcomes.md)."""

import pandas as pd
import pytest

from ancestry_mmm.core.promotions import (
    PromotionEvent,
    apply_promotion_events_to_frame,
    promotion_events_to_dataframe,
    promotion_weekly_series,
    validate_promotion_events,
)


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
