"""Work Package 1 part 1 (`Media-Mix-Lab: Coding LLM Next Steps After PR
#284`): tests for `application.fold_refit_service` - the first real (if
tiny) PyMC fit ever driven through `core.validation_folds`'s leakage-safe
fold contract, and the first real `FoldParameterSnapshot`s ever produced
for `core.structural_stability`.

Deliberately paced for normal blocking CI: exactly one real MCMC fit
(shared/Model A, tiny draws/tune, module-scoped so every test in this file
reuses it - matching test_predictive_density.py's established "pay the
real-fit cost once" pattern), plus assessment-only tests that never fit
anything. Market-specific (Model C) real-fit coverage, the single-market
fallback path, and genuine multi-fold structural-stability evidence (a
second real fit) are deliberately deferred to
test_fold_refit_service_recovery.py, the schedule/manual-only companion -
mirroring test_search_candidate_a_recovery_posterior.py's own split from
its fast-checks-only sibling.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.application.fold_refit_service import (
    run_leakage_safe_fold_refit,
)
from ancestry_mmm.application.model_fit_service import MODEL_TYPE_SHARED
from ancestry_mmm.core.coverage import (
    STATE_UNAVAILABLE_SOURCE,
    VARIABLE_CLASS_FLOW_COUNT,
    CoverageSegment,
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.structural_stability import (
    FoldParameterSnapshot,
    assess_structural_stability,
)

FIT_KWARGS = dict(
    draws=15, tune=15, chains=2, cores=1, target_accept=0.8, random_seed=1
)


def _raw_dataframe(n_weeks: int = 40) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n_weeks, freq="W")
    frames = []
    for i, market in enumerate(["UK", "US"]):
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "market": market,
                    "TV_Brand": np.linspace(100.0 + i * 10, 900.0 + i * 10, n_weeks),
                    "GSA_New": np.linspace(20.0 + i * 5, 120.0 + i * 5, n_weeks),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _spec() -> ModelSpec:
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK", "US"],
        segment_outcomes={"New": "GSA_New"},
        channels=["TV_Brand"],
    )


def _empty_coverage_matrix() -> VariableCoverageMatrix:
    """No records at all - vacuously leakage-safe for every fold (`all(...)`
    over an empty per_variable tuple, no limitations recorded), the
    simplest fixture that exercises the "fold cleared assessment, fit it"
    path without asserting anything about coverage-assessment logic
    itself (already covered by test_validation_folds.py)."""
    return VariableCoverageMatrix(
        matrix_id="empty-matrix",
        matrix_version=1,
        generated_at="2026-08-18",
        records=(),
    )


def _unsafe_coverage_matrix() -> VariableCoverageMatrix:
    """One record with an unavailable-source coverage segment overlapping
    the whole date range, so the fold's training window overlaps it and
    is assessed cannot_verify - reusing exactly the mechanism
    test_validation_folds.py already tests, only to prove this module's
    own orchestration loop actually respects it (and never fits anything
    for it - no real MCMC cost in this test)."""
    record = VariableCoverageRecord(
        variable_id="TV_Brand",
        source_id="src-1",
        source_version=1,
        market="UK",
        frequency=FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class=VARIABLE_CLASS_FLOW_COUNT,
            publication_lag_periods=0,
        ),
        coverage_segments=(
            CoverageSegment(
                period_start="2024-01-01",
                period_end="2025-12-31",
                state=STATE_UNAVAILABLE_SOURCE,
            ),
        ),
    )
    return VariableCoverageMatrix(
        matrix_id="unsafe-matrix",
        matrix_version=1,
        generated_at="2026-08-18",
        records=(record,),
    )


@pytest.fixture(scope="module")
def shared_refit_result():
    """The one real (tiny) MCMC fit this file pays for - reused by every
    test below via this module-scoped fixture."""
    return run_leakage_safe_fold_refit(
        _raw_dataframe(n_weeks=40),
        _spec(),
        _empty_coverage_matrix(),
        model_type=MODEL_TYPE_SHARED,
        n_folds=1,
        min_train_frac=0.7,
        posterior_draw_subsample=5,
        **FIT_KWARGS,
    )


class TestRunLeakageSafeFoldRefitSafePath:
    def test_safe_fold_is_fit_and_produces_one_snapshot(self, shared_refit_result):
        result = shared_refit_result
        assert len(result.folds) == 1
        assert len(result.snapshots) == 1
        assert result.snapshots[0].fold_id == result.folds[0].fold_id
        assert not result.results_df.empty
        assert (result.results_df["leakage_safe"] == True).all()  # noqa: E712

    def test_r2_and_mape_are_real_finite_numbers(self, shared_refit_result):
        row = shared_refit_result.results_df.iloc[0]
        assert row["outcome_id"] == "fh_new"
        assert np.isfinite(row["r_squared"])
        assert np.isfinite(row["mape_pct"])

    def test_snapshot_uses_documented_naming_and_has_draws(self, shared_refit_result):
        snapshot = shared_refit_result.snapshots[0]

        for expected_key in (
            "adstock_decay__TV_Brand",
            "hill_K__TV_Brand",
            "hill_S__TV_Brand",
            "beta__TV_Brand__fh_new",
            "intercept__fh_new",
        ):
            assert expected_key in snapshot.point_values, expected_key
            assert np.isfinite(snapshot.point_values[expected_key])

        # Not market-qualified for the shared model - both markets share one curve.
        assert not any(k.startswith("hill_K__UK__") for k in snapshot.point_values)

        assert set(snapshot.draws) == set(snapshot.point_values)
        assert len(snapshot.draws["hill_K__TV_Brand"]) == 5
        assert all(np.isfinite(v) for v in snapshot.draws["hill_K__TV_Brand"])


class TestRunLeakageSafeFoldRefitUnsafePath:
    def test_unsafe_fold_is_never_fit(self):
        result = run_leakage_safe_fold_refit(
            _raw_dataframe(n_weeks=40),
            _spec(),
            _unsafe_coverage_matrix(),
            model_type=MODEL_TYPE_SHARED,
            n_folds=1,
            min_train_frac=0.7,
            posterior_draw_subsample=5,
            **FIT_KWARGS,
        )

        assert len(result.snapshots) == 0
        assert not result.assessments[0].is_leakage_safe
        row = result.results_df.iloc[0]
        assert row["leakage_safe"] == False  # noqa: E712
        assert row["skipped_reason"]
        assert pd.isna(row["r_squared"])


class TestRealSnapshotIntegratesWithStructuralStability:
    def test_real_snapshot_plus_a_second_fold_compares_without_error(
        self, shared_refit_result
    ):
        """Proves the real snapshot this module produces is usable as
        genuine `assess_structural_stability` input, without paying for a
        second real MCMC fit here - a second, independently-constructed
        snapshot for the same parameter names stands in for "another
        fold". Real multi-fold (two real fits) coverage lives in the
        schedule/manual-only companion."""
        real_snapshot = shared_refit_result.snapshots[0]
        other_fold = FoldParameterSnapshot(
            fold_id="synthetic_comparison_fold",
            point_values={
                name: value * 1.1 for name, value in real_snapshot.point_values.items()
            },
        )

        artefact = assess_structural_stability((real_snapshot, other_fold))

        assert set(artefact.fold_ids) == {
            real_snapshot.fold_id,
            "synthetic_comparison_fold",
        }
        by_name = {p.parameter_name: p for p in artefact.per_parameter}
        assert "hill_K__TV_Brand" in by_name
        assert np.isfinite(by_name["hill_K__TV_Brand"].point_range)
        assert by_name["hill_K__TV_Brand"].point_range > 0
