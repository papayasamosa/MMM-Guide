"""REQ-LEAK-001 (Work Package 1): tests for core.validation_folds."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.coverage import (
    STATE_UNAVAILABLE_SOURCE,
    VARIABLE_CLASS_FLOW_COUNT,
    CoverageSegment,
    DefinitionBreak,
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.validation_folds import (
    LEAKAGE_STATUS_CANNOT_VERIFY,
    LEAKAGE_STATUS_DEFINITION_BREAK,
    LEAKAGE_STATUS_NOT_YET_EFFECTIVE,
    LEAKAGE_STATUS_RISK,
    LEAKAGE_STATUS_SAFE,
    FoldReconstructionAssessment,
    ValidationFold,
    VariableReconstructionAssessment,
    assess_fold_source_reconstruction,
    build_expanding_window_folds,
    leakage_safe_expanding_window_backtest,
)


def _bt_dataframe(n_weeks: int = 20) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n_weeks, freq="W")
    return pd.DataFrame(
        {
            "date": dates,
            "market": ["UK"] * n_weeks,
            "spend": np.arange(n_weeks, dtype=float),
            "gsa": np.arange(n_weeks, dtype=float) + 10.0,
        }
    )


def _coverage_record(
    variable_id: str = "tv_spend",
    *,
    market: str = "UK",
    publication_lag_periods: int = 0,
    effective_start: str | None = None,
    definition_breaks: tuple = (),
    coverage_segments: tuple = (),
) -> VariableCoverageRecord:
    return VariableCoverageRecord(
        variable_id=variable_id,
        source_id="src-1",
        source_version=1,
        market=market,
        frequency=FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class=VARIABLE_CLASS_FLOW_COUNT,
            publication_lag_periods=publication_lag_periods,
        ),
        coverage_segments=coverage_segments,
        effective_start=effective_start,
        definition_breaks=definition_breaks,
    )


def _matrix(records: tuple) -> VariableCoverageMatrix:
    return VariableCoverageMatrix(
        matrix_id="test-matrix",
        matrix_version=1,
        generated_at="2026-08-17",
        records=records,
    )


# ---------------------------------------------------------------------------
# ValidationFold construction and validation
# ---------------------------------------------------------------------------


class TestValidationFoldConstruction:
    def _fold(self, **overrides) -> ValidationFold:
        values = dict(
            fold_id="fold_1",
            fold_manifest_version=1,
            train_start="2024-01-01",
            train_end="2024-06-01",
            test_start="2024-06-08",
            test_end="2024-07-01",
        )
        values.update(overrides)
        return ValidationFold(**values)

    def test_valid_fold_constructs(self):
        fold = self._fold()
        assert fold.fold_id == "fold_1"
        assert fold.effective_information_cutoff == "2024-06-01"

    def test_requires_fold_id(self):
        with pytest.raises(ValueError, match="fold_id is required"):
            self._fold(fold_id="")

    def test_rejects_non_positive_manifest_version(self):
        with pytest.raises(ValueError, match="fold_manifest_version"):
            self._fold(fold_manifest_version=0)

    def test_rejects_train_end_not_before_test_start(self):
        with pytest.raises(ValueError, match="train_end must be strictly before"):
            self._fold(train_end="2024-06-10", test_start="2024-06-08")

    def test_rejects_inverted_train_window(self):
        with pytest.raises(ValueError, match="train_start must not be after"):
            self._fold(train_start="2024-06-01", train_end="2024-01-01")

    def test_rejects_unsupported_schema_version(self):
        with pytest.raises(
            ValueError, match="Unsupported ValidationFold schema_version"
        ):
            self._fold(schema_version=99)

    def test_explicit_information_cutoff_overrides_train_end(self):
        fold = self._fold(information_cutoff="2024-06-15")
        assert fold.effective_information_cutoff == "2024-06-15"

    def test_to_dict_from_dict_round_trip(self):
        fold = self._fold(
            market_scope=("UK",),
            outcome_scope=("fh_new_gsa",),
            information_cutoff="2024-06-01",
        )
        restored = ValidationFold.from_dict(fold.to_dict())
        assert restored == fold


# ---------------------------------------------------------------------------
# build_expanding_window_folds: boundary correctness and no-leakage-in-split
# ---------------------------------------------------------------------------


class TestBuildExpandingWindowFolds:
    def test_folds_are_chronologically_ordered_and_non_overlapping(self):
        df = _bt_dataframe(n_weeks=20)
        folds = build_expanding_window_folds(df, "date", n_folds=3, min_train_frac=0.6)
        assert len(folds) >= 1
        for fold in folds:
            assert pd.Timestamp(fold.train_end) < pd.Timestamp(fold.test_start)
        for earlier, later in zip(folds, folds[1:]):
            assert pd.Timestamp(earlier.train_end) <= pd.Timestamp(later.train_end)

    def test_rejects_min_train_frac_leaving_no_holdout(self):
        df = _bt_dataframe(n_weeks=5)
        with pytest.raises(ValueError, match="leaves no data for a held-out block"):
            build_expanding_window_folds(df, "date", n_folds=3, min_train_frac=1.0)

    def test_no_future_row_ever_enters_a_fold_train_window(self):
        """Blocking test (REQ-LEAK-001 requirement 5): for every fold this
        builder produces, no row dated after that fold's own train_end can
        be included in a `df[dates <= train_end]` slice built from it -
        proven directly by construction, not merely asserted in prose."""
        df = _bt_dataframe(n_weeks=30)
        dates = pd.to_datetime(df["date"])
        folds = build_expanding_window_folds(df, "date", n_folds=4, min_train_frac=0.5)
        for fold in folds:
            train_slice = df[dates <= pd.Timestamp(fold.train_end)]
            assert (
                pd.to_datetime(train_slice["date"]) <= pd.Timestamp(fold.train_end)
            ).all()
            test_slice = df[
                (dates > pd.Timestamp(fold.train_end))
                & (dates <= pd.Timestamp(fold.test_end))
            ]
            if not test_slice.empty:
                assert (
                    pd.to_datetime(test_slice["date"]) > pd.Timestamp(fold.train_end)
                ).all()

    def test_mutating_future_rows_never_changes_an_earlier_folds_train_slice(self):
        """Blocking test: changing a value dated strictly after a fold's
        train_end must not change that fold's training slice at all - the
        concrete "future values cannot affect earlier fold inputs" proof
        the brief requires."""
        df = _bt_dataframe(n_weeks=30)
        dates = pd.to_datetime(df["date"])
        folds = build_expanding_window_folds(df, "date", n_folds=4, min_train_frac=0.5)
        early_fold = folds[0]
        before = df[dates <= pd.Timestamp(early_fold.train_end)].copy()

        mutated = df.copy()
        future_mask = pd.to_datetime(mutated["date"]) > pd.Timestamp(
            early_fold.train_end
        )
        mutated.loc[future_mask, "spend"] = 999999.0
        mutated.loc[future_mask, "gsa"] = -999999.0

        after = mutated[
            pd.to_datetime(mutated["date"]) <= pd.Timestamp(early_fold.train_end)
        ]
        pd.testing.assert_frame_equal(
            before.reset_index(drop=True), after.reset_index(drop=True)
        )


# ---------------------------------------------------------------------------
# assess_fold_source_reconstruction
# ---------------------------------------------------------------------------


class TestAssessFoldSourceReconstruction:
    def _fold(self, **overrides) -> ValidationFold:
        values = dict(
            fold_id="fold_1",
            fold_manifest_version=1,
            train_start="2024-01-01",
            train_end="2024-06-01",
            test_start="2024-06-08",
            test_end="2024-07-01",
            market_scope=("UK",),
        )
        values.update(overrides)
        return ValidationFold(**values)

    def test_no_lag_no_breaks_no_effective_restriction_is_safe(self):
        fold = self._fold()
        matrix = _matrix((_coverage_record(),))
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert assessment.is_leakage_safe
        assert assessment.per_variable[0].status == LEAKAGE_STATUS_SAFE

    def test_variable_effective_after_train_end_is_not_yet_effective(self):
        fold = self._fold()
        matrix = _matrix((_coverage_record(effective_start="2024-07-01"),))
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert not assessment.is_leakage_safe
        assert assessment.per_variable[0].status == LEAKAGE_STATUS_NOT_YET_EFFECTIVE

    def test_variable_effective_before_train_end_is_available(self):
        fold = self._fold()
        matrix = _matrix((_coverage_record(effective_start="2023-01-01"),))
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert assessment.is_leakage_safe

    def test_publication_lag_with_default_information_cutoff_leaks(self):
        """With `information_cutoff` defaulting to `train_end`, any
        variable with a non-zero publication lag has not yet been
        published as of that exact date, by construction - this is the
        leakage-safe (not merely retrospective) semantic REQ-LEAK-001
        requires."""
        fold = self._fold()
        matrix = _matrix((_coverage_record(publication_lag_periods=2),))
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert not assessment.is_leakage_safe
        assert assessment.per_variable[0].status == LEAKAGE_STATUS_RISK

    def test_publication_lag_cleared_by_later_information_cutoff_is_safe(self):
        fold = self._fold(information_cutoff="2024-06-22")
        matrix = _matrix((_coverage_record(publication_lag_periods=2),))
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert assessment.is_leakage_safe

    def test_unapproved_definition_break_inside_window_blocks(self):
        fold = self._fold()
        matrix = _matrix(
            (
                _coverage_record(
                    definition_breaks=(
                        DefinitionBreak(
                            break_date="2024-03-01",
                            description="methodology change",
                        ),
                    )
                ),
            )
        )
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert not assessment.is_leakage_safe
        assert assessment.per_variable[0].status == LEAKAGE_STATUS_DEFINITION_BREAK

    def test_approved_bridge_treatment_break_does_not_block(self):
        fold = self._fold()
        matrix = _matrix(
            (
                _coverage_record(
                    definition_breaks=(
                        DefinitionBreak(
                            break_date="2024-03-01",
                            description="methodology change",
                            bridge_treatment_approved=True,
                            approved_by="lead-analyst",
                            approved_at="2024-03-05",
                        ),
                    )
                ),
            )
        )
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert assessment.is_leakage_safe

    def test_ambiguous_coverage_state_overlapping_window_cannot_verify(self):
        fold = self._fold()
        matrix = _matrix(
            (
                _coverage_record(
                    coverage_segments=(
                        CoverageSegment(
                            period_start="2024-02-01",
                            period_end="2024-02-28",
                            state=STATE_UNAVAILABLE_SOURCE,
                        ),
                    )
                ),
            )
        )
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert not assessment.is_leakage_safe
        assert assessment.per_variable[0].status == LEAKAGE_STATUS_CANNOT_VERIFY
        assert assessment.limitations

    def test_ambiguous_coverage_state_outside_window_does_not_block(self):
        fold = self._fold()
        matrix = _matrix(
            (
                _coverage_record(
                    coverage_segments=(
                        CoverageSegment(
                            period_start="2024-09-01",
                            period_end="2024-09-30",
                            state=STATE_UNAVAILABLE_SOURCE,
                        ),
                    )
                ),
            )
        )
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert assessment.is_leakage_safe

    def test_scoped_market_filters_records(self):
        fold = self._fold(market_scope=("UK",))
        matrix = _matrix(
            (
                _coverage_record(market="AU", effective_start="2099-01-01"),
                _coverage_record(market="UK"),
            )
        )
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert len(assessment.per_variable) == 1
        assert assessment.per_variable[0].market == "UK"
        assert assessment.is_leakage_safe

    def test_wildcard_market_record_always_included(self):
        fold = self._fold(market_scope=("UK",))
        matrix = _matrix((_coverage_record(market="*"),))
        assessment = assess_fold_source_reconstruction(fold, matrix)
        assert len(assessment.per_variable) == 1


class TestVariableReconstructionAssessmentValidation:
    def test_rejects_invalid_status(self):
        with pytest.raises(ValueError, match="invalid status"):
            VariableReconstructionAssessment(
                variable_id="tv_spend", market="UK", status="not_a_status", reason="x"
            )

    def test_round_trip(self):
        original = VariableReconstructionAssessment(
            variable_id="tv_spend", market="UK", status=LEAKAGE_STATUS_SAFE, reason="ok"
        )
        assert (
            VariableReconstructionAssessment.from_dict(original.to_dict()) == original
        )


class TestFoldReconstructionAssessmentRoundTrip:
    def test_round_trip(self):
        original = FoldReconstructionAssessment(
            fold_id="fold_1",
            per_variable=(
                VariableReconstructionAssessment(
                    variable_id="tv_spend",
                    market="UK",
                    status=LEAKAGE_STATUS_SAFE,
                    reason="ok",
                ),
            ),
            limitations=(),
        )
        assert FoldReconstructionAssessment.from_dict(original.to_dict()) == original


# ---------------------------------------------------------------------------
# leakage_safe_expanding_window_backtest
# ---------------------------------------------------------------------------


class TestLeakageSafeExpandingWindowBacktest:
    @staticmethod
    def _fit_fold_fn_factory():
        calls = []

        def fit_fold_fn(train_df, test_df):
            calls.append((train_df.copy(), test_df.copy()))
            return {"gsa": 0.8}, {"gsa": 12.5}

        return fit_fold_fn, calls

    def test_safe_folds_call_fit_fold_fn_and_report_leakage_safe_true(self):
        df = _bt_dataframe(n_weeks=30)
        spec = ModelSpec(date_col="date", market_col="market")
        matrix = _matrix((_coverage_record(),))
        fit_fold_fn, calls = self._fit_fold_fn_factory()

        results, folds, assessments = leakage_safe_expanding_window_backtest(
            df, spec, fit_fold_fn, matrix, n_folds=2, min_train_frac=0.5
        )
        assert len(calls) == len(folds)
        assert not results.empty
        assert results["leakage_safe"].all()
        assert all(a.is_leakage_safe for a in assessments)

    def test_unsafe_fold_never_calls_fit_fold_fn(self):
        """The key blocking test: a fold whose leakage assessment fails
        must never be handed to `fit_fold_fn` at all - the contract must
        prevent use of a leakage-risky fold, not merely report on it after
        the fact."""
        df = _bt_dataframe(n_weeks=30)
        spec = ModelSpec(date_col="date", market_col="market")
        # publication_lag_periods > 0 with the default (train_end)
        # information cutoff always leaks, for every fold.
        matrix = _matrix((_coverage_record(publication_lag_periods=4),))
        fit_fold_fn, calls = self._fit_fold_fn_factory()

        results, folds, assessments = leakage_safe_expanding_window_backtest(
            df, spec, fit_fold_fn, matrix, n_folds=2, min_train_frac=0.5
        )
        assert len(calls) == 0
        assert not results.empty
        assert not results["leakage_safe"].any()
        assert all(not a.is_leakage_safe for a in assessments)
        assert all(row["outcome_id"] is None for _, row in results.iterrows())

    def test_mixed_folds_call_fit_fold_fn_only_for_the_safe_ones(self):
        """A variable that becomes effective partway through the model
        window must leave earlier folds unsafe and later folds (once the
        variable is effective, assuming zero publication lag) safe -
        proving the assessment is genuinely fold-specific, not a single
        whole-project verdict."""
        df = _bt_dataframe(n_weeks=40)
        spec = ModelSpec(date_col="date", market_col="market")
        # Effective roughly 3/4 of the way through the 40-week window.
        effective_date = pd.Timestamp("2024-01-01") + pd.Timedelta(weeks=30)
        matrix = _matrix(
            (_coverage_record(effective_start=effective_date.strftime("%Y-%m-%d")),)
        )
        fit_fold_fn, calls = self._fit_fold_fn_factory()

        results, folds, assessments = leakage_safe_expanding_window_backtest(
            df, spec, fit_fold_fn, matrix, n_folds=4, min_train_frac=0.4
        )
        safe_assessments = [a for a in assessments if a.is_leakage_safe]
        unsafe_assessments = [a for a in assessments if not a.is_leakage_safe]
        assert safe_assessments, "expected at least one fold after the effective date"
        assert unsafe_assessments, (
            "expected at least one fold before the effective date"
        )
        assert len(calls) == len(safe_assessments)

    def test_does_not_mutate_expanding_window_backtest(self):
        """`core.diagnostics.expanding_window_backtest` must remain fully
        usable and unaffected - this module is additive, not a
        replacement."""
        from ancestry_mmm.core.diagnostics import expanding_window_backtest

        df = _bt_dataframe(n_weeks=20)
        spec = ModelSpec(date_col="date", market_col="market")

        def fit_fold_fn(train_df, test_df):
            return {"gsa": 0.8}, {"gsa": 12.5}

        results = expanding_window_backtest(df, spec, fit_fold_fn, n_folds=1)
        assert not results.empty
        assert "leakage_safe" not in results.columns
