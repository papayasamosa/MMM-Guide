import pandas as pd
import pytest

from ancestry_mmm.data.pipeline import (
    TransformStep,
    UnsafeExpressionError,
    apply_pipeline,
    apply_step,
    join_sources,
    safe_eval_expression,
)


@pytest.fixture
def df():
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=4, freq="W"),
        "Search_Brand": [10.0, 20.0, 30.0, 40.0],
        "Search_NonBrand": [1.0, 2.0, 3.0, 4.0],
        "GSAs": [5.0, 6.0, 7.0, 8.0],
    })


class TestSafeEvalExpression:
    def test_arithmetic_on_columns(self, df):
        result = safe_eval_expression("Search_Brand + Search_NonBrand", df)
        pd.testing.assert_series_equal(result, df["Search_Brand"] + df["Search_NonBrand"], check_names=False)

    def test_whitelisted_function_call(self, df):
        import numpy as np
        result = safe_eval_expression("log(Search_Brand)", df)
        np.testing.assert_allclose(result.to_numpy(), np.log(df["Search_Brand"].to_numpy()))

    def test_constant_and_precedence(self, df):
        result = safe_eval_expression("Search_Brand * 2 + 1", df)
        pd.testing.assert_series_equal(result, df["Search_Brand"] * 2 + 1, check_names=False)

    def test_unknown_column_rejected(self, df):
        with pytest.raises(UnsafeExpressionError):
            safe_eval_expression("nonexistent_column + 1", df)

    @pytest.mark.parametrize("expr", [
        "__import__('os').system('echo pwned')",
        "().__class__.__bases__[0]",
        "[x for x in range(10)]",
        "open('/etc/passwd').read()",
        "eval('1+1')",
        "exec('1+1')",
        "Search_Brand if True else Search_NonBrand",
        "lambda x: x",
    ])
    def test_unsafe_or_unsupported_expressions_rejected(self, df, expr):
        with pytest.raises(UnsafeExpressionError):
            safe_eval_expression(expr, df)

    def test_non_whitelisted_function_rejected(self, df):
        with pytest.raises(UnsafeExpressionError):
            safe_eval_expression("os.system('echo hi')", df)


class TestPipelineReplay:
    def test_calculated_column_step(self, df):
        step = TransformStep(op="calculated_column", params={
            "new_column": "Search_Total", "expression": "Search_Brand + Search_NonBrand",
        })
        result = apply_step(df, step)
        pd.testing.assert_series_equal(
            result["Search_Total"], df["Search_Brand"] + df["Search_NonBrand"], check_names=False,
        )

    def test_pipeline_is_replayable_on_refreshed_data(self, df):
        steps = [
            TransformStep(op="calculated_column", params={
                "new_column": "Search_Total", "expression": "Search_Brand + Search_NonBrand",
            }),
            TransformStep(op="event_flag", params={
                "date_col": "date", "new_column": "promo",
                "start": "2024-01-01", "end": "2024-01-14",
            }),
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
            "event_name": "Christmas Sale", "start_date": "2024-01-01", "end_date": "2024-01-14",
            "segment": "New", "discount_depth": 0.2, "sale_price": None, "intensity": 1.0,
            "event_id": "abc123", "product": None, "affected_outcome_ids": [], "market": None,
            "transformation_version": 1,
        }
        event.update(event_overrides)
        return TransformStep(op="promotion_event", params={"event": event, "date_col": "date", "column_prefix": "_promo_event_"})

    def test_creates_a_column_named_after_the_segment(self, df):
        result = apply_step(df, self._step())
        assert "_promo_event_New" in result.columns

    def test_intensity_applies_only_inside_the_event_window(self, df):
        result = apply_step(df, self._step())
        in_window = (df["date"] >= pd.Timestamp("2024-01-01")) & (df["date"] <= pd.Timestamp("2024-01-14"))
        assert (result.loc[in_window, "_promo_event_New"] == 1.0).all()
        assert (result.loc[~in_window, "_promo_event_New"] == 0.0).all()

    def test_two_events_for_the_same_segment_compound(self, df):
        steps = [
            self._step(event_id="a", intensity=1.0, start_date="2024-01-01", end_date="2024-01-28"),
            self._step(event_id="b", intensity=0.5, start_date="2024-01-14", end_date="2024-01-28"),
        ]
        result = apply_pipeline(df, steps)
        overlap = df["date"] == pd.Timestamp("2024-01-14")
        assert result.loc[overlap, "_promo_event_New"].iloc[0] == pytest.approx(1.5)

    def test_replaying_the_same_steps_twice_from_a_clean_base_is_idempotent(self, df):
        steps = [self._step()]
        result_1 = apply_pipeline(df, steps)
        result_2 = apply_pipeline(df, steps)
        assert result_1["_promo_event_New"].tolist() == result_2["_promo_event_New"].tolist()

    def test_events_for_different_segments_get_independent_columns(self, df):
        steps = [self._step(event_id="a", segment="New"), self._step(event_id="b", segment="Existing FH Customer")]
        result = apply_pipeline(df, steps)
        assert "_promo_event_New" in result.columns
        assert "_promo_event_Existing FH Customer" in result.columns


def test_join_sources_rejects_colliding_column_names():
    media = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=2), "TV": [1, 2]})
    outcomes = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=2), "TV": [3, 4]})
    with pytest.raises(ValueError):
        join_sources({"media": media, "outcomes": outcomes}, date_col="date")


def test_join_sources_merges_on_date():
    media = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=2), "TV": [1, 2]})
    outcomes = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=2), "GSAs": [3, 4]})
    joined = join_sources({"media": media, "outcomes": outcomes}, date_col="date")
    assert list(joined.columns) == ["date", "TV", "GSAs"]
    assert len(joined) == 2
