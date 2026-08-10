import pandas as pd
import pytest

from ancestry_mmm.data.pipeline import (
    TransformStep,
    UnsafeExpressionError,
    apply_pipeline,
    apply_step,
    join_sources,
    join_sources_with_diagnostics,
    safe_eval_expression,
)


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="W"),
            "Search_Brand": [10.0, 20.0, 30.0, 40.0],
            "Search_NonBrand": [1.0, 2.0, 3.0, 4.0],
            "GSAs": [5.0, 6.0, 7.0, 8.0],
        }
    )


class TestSafeEvalExpression:
    def test_arithmetic_on_columns(self, df):
        result = safe_eval_expression("Search_Brand + Search_NonBrand", df)
        pd.testing.assert_series_equal(
            result, df["Search_Brand"] + df["Search_NonBrand"], check_names=False
        )

    def test_whitelisted_function_call(self, df):
        import numpy as np

        result = safe_eval_expression("log(Search_Brand)", df)
        np.testing.assert_allclose(
            result.to_numpy(), np.log(df["Search_Brand"].to_numpy())
        )

    def test_constant_and_precedence(self, df):
        result = safe_eval_expression("Search_Brand * 2 + 1", df)
        pd.testing.assert_series_equal(
            result, df["Search_Brand"] * 2 + 1, check_names=False
        )

    def test_unknown_column_rejected(self, df):
        with pytest.raises(UnsafeExpressionError):
            safe_eval_expression("nonexistent_column + 1", df)

    @pytest.mark.parametrize(
        "expr",
        [
            "__import__('os').system('echo pwned')",
            "().__class__.__bases__[0]",
            "[x for x in range(10)]",
            "open('/etc/passwd').read()",
            "eval('1+1')",
            "exec('1+1')",
            "Search_Brand if True else Search_NonBrand",
            "lambda x: x",
        ],
    )
    def test_unsafe_or_unsupported_expressions_rejected(self, df, expr):
        with pytest.raises(UnsafeExpressionError):
            safe_eval_expression(expr, df)

    def test_non_whitelisted_function_rejected(self, df):
        with pytest.raises(UnsafeExpressionError):
            safe_eval_expression("os.system('echo hi')", df)


class TestPipelineReplay:
    def test_calculated_column_step(self, df):
        step = TransformStep(
            op="calculated_column",
            params={
                "new_column": "Search_Total",
                "expression": "Search_Brand + Search_NonBrand",
            },
        )
        result = apply_step(df, step)
        pd.testing.assert_series_equal(
            result["Search_Total"],
            df["Search_Brand"] + df["Search_NonBrand"],
            check_names=False,
        )

    def test_pipeline_is_replayable_on_refreshed_data(self, df):
        steps = [
            TransformStep(
                op="calculated_column",
                params={
                    "new_column": "Search_Total",
                    "expression": "Search_Brand + Search_NonBrand",
                },
            ),
            TransformStep(
                op="event_flag",
                params={
                    "date_col": "date",
                    "new_column": "promo",
                    "start": "2024-01-01",
                    "end": "2024-01-14",
                },
            ),
        ]
        result_1 = apply_pipeline(df, steps)
        # A second, differently-valued dataset with the same shape/columns -
        # replaying the same recorded steps must not require rebuilding them.
        df_refreshed = df.copy()
        df_refreshed["Search_Brand"] = df_refreshed["Search_Brand"] * 10
        result_2 = apply_pipeline(df_refreshed, steps)

        assert list(result_1.columns) == list(result_2.columns)
        assert result_1["promo"].tolist() == result_2["promo"].tolist()
        assert result_2["Search_Total"].iloc[0] == pytest.approx(10 * 10.0 + 1.0)

    def test_unknown_op_raises(self, df):
        step = TransformStep(op="not_a_real_op", params={})
        with pytest.raises(ValueError):
            apply_step(df, step)


class TestPromotionEventOp:
    """`promotion_event` steps are produced by
    core.promotions.promotion_events_to_transform_steps, not hand-built
    through the Transform Pipeline page (it's deliberately excluded from
    SUPPORTED_OPS) - but apply_step/apply_pipeline replay them the same way
    as every other op."""

    def _step(self, **event_overrides):
        event = {
            "event_name": "Christmas Sale",
            "start_date": "2024-01-01",
            "end_date": "2024-01-14",
            "segment": "New",
            "discount_depth": 0.2,
            "sale_price": None,
            "intensity": 1.0,
            "event_id": "abc123",
            "product": None,
            "affected_outcome_ids": [],
            "market": None,
            "transformation_version": 1,
        }
        event.update(event_overrides)
        return TransformStep(
            op="promotion_event",
            params={
                "event": event,
                "date_col": "date",
                "column_prefix": "_promo_event_",
            },
        )

    def test_creates_a_column_named_after_the_segment(self, df):
        result = apply_step(df, self._step())
        assert "_promo_event_New" in result.columns

    def test_intensity_applies_only_inside_the_event_window(self, df):
        result = apply_step(df, self._step())
        in_window = (df["date"] >= pd.Timestamp("2024-01-01")) & (
            df["date"] <= pd.Timestamp("2024-01-14")
        )
        assert (result.loc[in_window, "_promo_event_New"] == 1.0).all()
        assert (result.loc[~in_window, "_promo_event_New"] == 0.0).all()

    def test_two_events_for_the_same_segment_compound(self, df):
        steps = [
            self._step(
                event_id="a",
                intensity=1.0,
                start_date="2024-01-01",
                end_date="2024-01-28",
            ),
            self._step(
                event_id="b",
                intensity=0.5,
                start_date="2024-01-14",
                end_date="2024-01-28",
            ),
        ]
        result = apply_pipeline(df, steps)
        overlap = df["date"] == pd.Timestamp("2024-01-14")
        assert result.loc[overlap, "_promo_event_New"].iloc[0] == pytest.approx(1.5)

    def test_replaying_the_same_steps_twice_from_a_clean_base_is_idempotent(self, df):
        steps = [self._step()]
        result_1 = apply_pipeline(df, steps)
        result_2 = apply_pipeline(df, steps)
        assert (
            result_1["_promo_event_New"].tolist()
            == result_2["_promo_event_New"].tolist()
        )

    def test_events_for_different_segments_get_independent_columns(self, df):
        steps = [
            self._step(event_id="a", segment="New"),
            self._step(event_id="b", segment="Existing FH Customer"),
        ]
        result = apply_pipeline(df, steps)
        assert "_promo_event_New" in result.columns
        assert "_promo_event_Existing FH Customer" in result.columns


def test_join_sources_rejects_colliding_column_names():
    media = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=2), "TV": [1, 2]})
    outcomes = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=2), "TV": [3, 4]}
    )
    with pytest.raises(ValueError):
        join_sources({"media": media, "outcomes": outcomes}, date_col="date")


def test_join_sources_merges_on_date():
    media = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=2), "TV": [1, 2]})
    outcomes = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=2), "GSAs": [3, 4]}
    )
    joined = join_sources({"media": media, "outcomes": outcomes}, date_col="date")
    assert list(joined.columns) == ["date", "TV", "GSAs"]
    assert len(joined) == 2


# ---------------------------------------------------------------------------
# join_sources_with_diagnostics (REQ-COVERAGE-001 S4: join mode, unmatched-
# row policy and resulting coverage loss must be explicit and diagnosable)
# ---------------------------------------------------------------------------


class TestJoinSourcesWithDiagnostics:
    def test_matching_dates_report_zero_loss_on_every_source(self):
        media = pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=3), "TV": [1, 2, 3]}
        )
        outcomes = pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=3), "GSAs": [4, 5, 6]}
        )
        joined, diagnostics = join_sources_with_diagnostics(
            {"media": media, "outcomes": outcomes}, date_col="date"
        )
        assert len(joined) == 3
        assert diagnostics.join_mode == "inner"
        assert diagnostics.output_rows == 3
        assert diagnostics.has_loss is False
        by_name = {s.source_name: s for s in diagnostics.per_source}
        assert by_name["media"].input_rows == 3
        assert by_name["media"].matched_keys == 3
        assert by_name["media"].dropped_keys == 0
        assert by_name["outcomes"].dropped_keys == 0

    def test_inner_join_reports_the_dropped_keys_per_source(self):
        # media has 2024-01-01..03; outcomes only has 2024-01-02..04 - an
        # inner join keeps only 01-02/01-03, silently dropping media's
        # 01-01 and outcomes' 01-04 unless this is diagnosed.
        media = pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=3), "TV": [1, 2, 3]}
        )
        outcomes = pd.DataFrame(
            {"date": pd.date_range("2024-01-02", periods=3), "GSAs": [4, 5, 6]}
        )
        joined, diagnostics = join_sources_with_diagnostics(
            {"media": media, "outcomes": outcomes}, date_col="date", how="inner"
        )
        assert len(joined) == 2
        assert diagnostics.has_loss is True
        by_name = {s.source_name: s for s in diagnostics.per_source}
        assert by_name["media"].input_keys == 3
        assert by_name["media"].matched_keys == 2
        assert by_name["media"].dropped_keys == 1
        assert by_name["outcomes"].dropped_keys == 1

    def test_outer_join_reports_zero_loss_for_the_same_mismatched_dates(self):
        """The same mismatched-date scenario as the inner-join test above -
        an outer join keeps every key from every source, so nothing is
        dropped (REQ-COVERAGE-001 S1: never automatically truncate to the
        narrowest common window)."""
        media = pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=3), "TV": [1, 2, 3]}
        )
        outcomes = pd.DataFrame(
            {"date": pd.date_range("2024-01-02", periods=3), "GSAs": [4, 5, 6]}
        )
        joined, diagnostics = join_sources_with_diagnostics(
            {"media": media, "outcomes": outcomes}, date_col="date", how="outer"
        )
        assert len(joined) == 4
        assert diagnostics.has_loss is False
        by_name = {s.source_name: s for s in diagnostics.per_source}
        assert by_name["media"].dropped_keys == 0
        assert by_name["outcomes"].dropped_keys == 0

    def test_join_mode_defaults_to_inner_matching_join_sources(self):
        media = pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=2), "TV": [1, 2]}
        )
        outcomes = pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=2), "GSAs": [3, 4]}
        )
        _, diagnostics = join_sources_with_diagnostics(
            {"media": media, "outcomes": outcomes}, date_col="date"
        )
        assert diagnostics.join_mode == "inner"

    def test_diagnostics_and_join_sources_produce_the_same_joined_frame(self):
        media = pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=3), "TV": [1, 2, 3]}
        )
        outcomes = pd.DataFrame(
            {"date": pd.date_range("2024-01-02", periods=3), "GSAs": [4, 5, 6]}
        )
        directly = join_sources({"media": media, "outcomes": outcomes}, date_col="date")
        via_diagnostics, _ = join_sources_with_diagnostics(
            {"media": media, "outcomes": outcomes}, date_col="date"
        )
        pd.testing.assert_frame_equal(directly, via_diagnostics)

    def test_market_scoped_keys_are_diagnosed_per_date_and_market(self):
        media = pd.DataFrame(
            {
                "date": list(pd.date_range("2024-01-01", periods=2)) * 2,
                "market": ["UK", "UK", "AU", "AU"],
                "TV": [1, 2, 3, 4],
            }
        )
        outcomes = pd.DataFrame(
            {
                "date": list(pd.date_range("2024-01-01", periods=2)),
                "market": ["UK", "UK"],
                "GSAs": [5, 6],
            }
        )
        joined, diagnostics = join_sources_with_diagnostics(
            {"media": media, "outcomes": outcomes},
            date_col="date",
            market_col="market",
            how="inner",
        )
        assert len(joined) == 2
        by_name = {s.source_name: s for s in diagnostics.per_source}
        # AU's 2 media rows never appear in outcomes at all - both dropped.
        assert by_name["media"].dropped_keys == 2
        assert by_name["outcomes"].dropped_keys == 0

    def test_to_dict_is_json_shaped(self):
        media = pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=2), "TV": [1, 2]}
        )
        outcomes = pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=2), "GSAs": [3, 4]}
        )
        _, diagnostics = join_sources_with_diagnostics(
            {"media": media, "outcomes": outcomes}, date_col="date"
        )
        payload = diagnostics.to_dict()
        assert payload["join_mode"] == "inner"
        assert payload["keys"] == ["date"]
        assert payload["output_rows"] == 2
        assert isinstance(payload["per_source"], list)
        assert payload["per_source"][0]["source_name"] in {"media", "outcomes"}
