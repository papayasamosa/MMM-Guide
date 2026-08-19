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
    run_leakage_safe_fold_refit_from_sources,
)
from ancestry_mmm.application.model_fit_service import MODEL_TYPE_SHARED
from ancestry_mmm.core.coverage import (
    STATE_UNAVAILABLE_SOURCE,
    VARIABLE_CLASS_FLOW_COUNT,
    CoverageSegment,
    FrequencyMetadata,
    SourceVersion,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.outcomes import FAMILY_HISTORY, METRIC_GSA, OutcomeDefinition
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.structural_stability import (
    FoldParameterSnapshot,
    assess_structural_stability,
)
from ancestry_mmm.core.validation_folds import (
    RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
    RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL,
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

    def test_result_records_the_coverage_metadata_only_tier(self, shared_refit_result):
        """The dataframe-slicing path must record its evidence tier as
        `coverage_metadata_only` - never the deeper fold-local tier, and
        never an absent/ambiguous tier."""
        assert (
            shared_refit_result.reconstruction_tier
            == RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY
        )


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


# ---------------------------------------------------------------------------
# Work Package 1 part 2: run_leakage_safe_fold_refit_from_sources -
# point-in-time reconstruction from raw native per-source tables, never one
# already-prepared/date-sliced dataframe.
# ---------------------------------------------------------------------------


def _source_frames(n_weeks: int = 40) -> dict:
    dates = pd.date_range("2024-01-01", periods=n_weeks, freq="W")
    outcome_frames, media_frames = [], []
    for i, market in enumerate(["UK", "US"]):
        outcome_frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "market": market,
                    "GSA_New": np.linspace(20.0 + i * 5, 120.0 + i * 5, n_weeks),
                }
            )
        )
        media_frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "market": market,
                    "TV_Brand": np.linspace(100.0 + i * 10, 900.0 + i * 10, n_weeks),
                }
            )
        )
    return {
        "outcomes-src": pd.concat(outcome_frames, ignore_index=True),
        "media-src": pd.concat(media_frames, ignore_index=True),
    }


def _sources_spec() -> ModelSpec:
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK", "US"],
        segment_outcomes={"New": "GSA_New"},
        channels=["TV_Brand"],
    )


def _sources_outcomes() -> list:
    """Matches exactly what `core.outcomes.fh_outcomes_from_spec` would
    derive from `_sources_spec().segment_outcomes` - `fit_fold_with_real_
    model` calls `prepare_fh_modeling_frame(train_df, spec)` without an
    explicit `outcomes` list, so that internal auto-derivation and this
    module's explicit `outcomes` argument (needed for the capability/
    consumed-variable resolution `build_official_capability_report`
    requires) must resolve to the same outcome_id/source_column."""
    return [
        OutcomeDefinition(
            outcome_id="fh_new",
            product=FAMILY_HISTORY,
            segment="New",
            metric=METRIC_GSA,
            source_column="GSA_New",
        )
    ]


def _sources_coverage_matrix(
    *,
    tv_brand_segments_by_market: dict | None = None,
    tv_brand_publication_lag: int = 0,
) -> VariableCoverageMatrix:
    tv_brand_segments_by_market = tv_brand_segments_by_market or {}
    records = [
        VariableCoverageRecord(
            variable_id="GSA_New",
            source_id="outcomes-src",
            source_version=1,
            market="*",
            frequency=FrequencyMetadata(
                native_frequency="weekly",
                target_frequency="weekly",
                variable_class=VARIABLE_CLASS_FLOW_COUNT,
            ),
            coverage_segments=(),
        )
    ]
    for market in ("UK", "US"):
        records.append(
            VariableCoverageRecord(
                variable_id="TV_Brand",
                source_id="media-src",
                source_version=1,
                market=market,
                frequency=FrequencyMetadata(
                    native_frequency="weekly",
                    target_frequency="weekly",
                    variable_class=VARIABLE_CLASS_FLOW_COUNT,
                    publication_lag_periods=tv_brand_publication_lag,
                ),
                coverage_segments=tv_brand_segments_by_market.get(market, ()),
            )
        )
    return VariableCoverageMatrix(
        matrix_id="sources-matrix",
        matrix_version=1,
        generated_at="2026-08-18",
        records=tuple(records),
    )


@pytest.fixture(scope="module")
def shared_sources_refit_result():
    """The one real (tiny) MCMC fit this section pays for, driven through
    fold-local `core.official_preparation.prepare_canonical_native_frame`
    reconstruction rather than a date-sliced already-prepared frame."""
    return run_leakage_safe_fold_refit_from_sources(
        _source_frames(n_weeks=40),
        _sources_spec(),
        _sources_coverage_matrix(),
        _sources_outcomes(),
        model_type=MODEL_TYPE_SHARED,
        n_folds=1,
        min_train_frac=0.7,
        posterior_draw_subsample=5,
        **FIT_KWARGS,
    )


class TestRunLeakageSafeFoldRefitFromSourcesSafePath:
    def test_safe_fold_is_fit_and_produces_one_snapshot(
        self, shared_sources_refit_result
    ):
        result = shared_sources_refit_result
        assert len(result.folds) == 1
        assert len(result.snapshots) == 1
        assert result.snapshots[0].fold_id == result.folds[0].fold_id
        assert not result.results_df.empty
        assert (result.results_df["leakage_safe"] == True).all()  # noqa: E712

    def test_r2_and_mape_are_real_finite_numbers(self, shared_sources_refit_result):
        row = shared_sources_refit_result.results_df.iloc[0]
        assert row["outcome_id"] == "fh_new"
        assert np.isfinite(row["r_squared"])
        assert np.isfinite(row["mape_pct"])

    def test_structural_snapshot_matches_predictive_evidence_fit(
        self, shared_sources_refit_result
    ):
        """The snapshot and the R²/MAPE row for this fold both came from
        the exact same `fit_fold_with_real_model` call - one fit, not two
        divergent ones."""
        result = shared_sources_refit_result
        assert result.snapshots[0].fold_id == result.results_df.iloc[0]["fold_id"]

    def test_result_records_the_source_version_aware_tier(
        self, shared_sources_refit_result
    ):
        """The fold-local source-reconstruction path must record its
        evidence tier as `source_version_aware_fold_local` - distinguishable
        from the shallower coverage-metadata-only tier by downstream
        consumers and fingerprints."""
        assert (
            shared_sources_refit_result.reconstruction_tier
            == RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL
        )


class TestRunLeakageSafeFoldRefitFromSourcesBlockedPaths:
    """Every case below must never call `fit_fold_with_real_model` -
    asserted indirectly by `len(result.snapshots) == 0` with no real MCMC
    cost paid (draws/tune from FIT_KWARGS are irrelevant if unreached)."""

    def test_unresolved_coverage_blocks_the_whole_fold_without_fitting(self):
        """One market's TV_Brand is unavailable_source - the fold is
        rejected entirely, never partially fit with the other market's
        data and a zero/blank standing in for the unavailable one."""
        matrix = _sources_coverage_matrix(
            tv_brand_segments_by_market={
                "UK": (
                    CoverageSegment(
                        period_start="2024-01-01",
                        period_end="2025-12-31",
                        state=STATE_UNAVAILABLE_SOURCE,
                    ),
                )
            }
        )
        result = run_leakage_safe_fold_refit_from_sources(
            _source_frames(n_weeks=40),
            _sources_spec(),
            matrix,
            _sources_outcomes(),
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

    def test_publication_lag_blocks_without_fitting(self):
        """A later publication cannot leak backward into this fold's
        training reconstruction - proven end-to-end through the fold-local
        official-preparation orchestration, not only at the
        `assess_fold_source_reconstruction` unit level."""
        matrix = _sources_coverage_matrix(tv_brand_publication_lag=4)
        result = run_leakage_safe_fold_refit_from_sources(
            _source_frames(n_weeks=40),
            _sources_spec(),
            matrix,
            _sources_outcomes(),
            model_type=MODEL_TYPE_SHARED,
            n_folds=1,
            min_train_frac=0.7,
            posterior_draw_subsample=5,
            **FIT_KWARGS,
        )
        assert len(result.snapshots) == 0
        assert not result.assessments[0].is_leakage_safe

    def test_later_source_version_blocks_without_fitting(self):
        """The pinned SourceVersion for the media source was uploaded
        after this fold's train_end - the fold must never be fit against
        content that could not have existed as of that point (REQ-LEAK-001
        requirement 4)."""
        matrix = _sources_coverage_matrix()
        dates = pd.date_range("2024-01-01", periods=40, freq="W")
        train_end = dates[int(40 * 0.7)]
        versions = (
            SourceVersion(
                source_id="media-src",
                version=1,
                original_filename="media.csv",
                checksum="a" * 64,
                size_bytes=100,
                uploaded_at=(train_end + pd.Timedelta(days=30)).strftime("%Y-%m-%d"),
                parsed_representation_version="v1",
            ),
        )
        result = run_leakage_safe_fold_refit_from_sources(
            _source_frames(n_weeks=40),
            _sources_spec(),
            matrix,
            _sources_outcomes(),
            source_versions=versions,
            model_type=MODEL_TYPE_SHARED,
            n_folds=1,
            min_train_frac=0.7,
            posterior_draw_subsample=5,
            **FIT_KWARGS,
        )
        assert len(result.snapshots) == 0
        assert not result.assessments[0].is_leakage_safe

    def test_earlier_source_version_does_not_block(self):
        """Sanity check: an uploaded-in-time SourceVersion never blocks a
        fold merely because `source_versions` was supplied."""
        matrix = _sources_coverage_matrix()
        versions = (
            SourceVersion(
                source_id="media-src",
                version=1,
                original_filename="media.csv",
                checksum="a" * 64,
                size_bytes=100,
                uploaded_at="2023-06-01",
                parsed_representation_version="v1",
            ),
            SourceVersion(
                source_id="outcomes-src",
                version=1,
                original_filename="outcomes.csv",
                checksum="b" * 64,
                size_bytes=100,
                uploaded_at="2023-06-01",
                parsed_representation_version="v1",
            ),
        )
        result = run_leakage_safe_fold_refit_from_sources(
            _source_frames(n_weeks=40),
            _sources_spec(),
            matrix,
            _sources_outcomes(),
            source_versions=versions,
            model_type=MODEL_TYPE_SHARED,
            n_folds=1,
            min_train_frac=0.7,
            posterior_draw_subsample=5,
            **FIT_KWARGS,
        )
        assert result.assessments[0].is_leakage_safe
