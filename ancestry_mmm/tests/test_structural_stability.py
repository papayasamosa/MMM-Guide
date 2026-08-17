"""REQ-STAB-001 (Work Package 2, part 2): tests for
core.structural_stability."""

from __future__ import annotations

import pytest

from ancestry_mmm.core.structural_stability import (
    FoldParameterSnapshot,
    ParameterFoldComparison,
    StructuralStabilityArtefact,
    assess_structural_stability,
)
from ancestry_mmm.core.validation_folds import build_expanding_window_folds
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# FoldParameterSnapshot
# ---------------------------------------------------------------------------


class TestFoldParameterSnapshot:
    def test_requires_fold_id(self):
        with pytest.raises(ValueError, match="fold_id is required"):
            FoldParameterSnapshot(fold_id="")

    def test_round_trip(self):
        original = FoldParameterSnapshot(
            fold_id="fold_1",
            point_values={"hill_K__TV": 1.05, "adstock_decay__TV": 0.55},
            draws={"hill_K__TV": (1.0, 1.05, 1.1)},
        )
        restored = FoldParameterSnapshot.from_dict(original.to_dict())
        assert restored == original

    def test_defaults_to_empty(self):
        snap = FoldParameterSnapshot(fold_id="fold_1")
        assert snap.point_values == {}
        assert snap.draws == {}


# ---------------------------------------------------------------------------
# ParameterFoldComparison
# ---------------------------------------------------------------------------


class TestParameterFoldComparison:
    def test_requires_parameter_name(self):
        with pytest.raises(ValueError, match="parameter_name is required"):
            ParameterFoldComparison(parameter_name="", fold_point_values=())

    def test_point_range_is_max_minus_min(self):
        comparison = ParameterFoldComparison(
            parameter_name="hill_K__TV",
            fold_point_values=(("fold_1", 1.0), ("fold_2", 1.5), ("fold_3", 0.8)),
        )
        assert comparison.point_range == pytest.approx(0.7)

    def test_point_range_is_zero_for_a_perfectly_stable_parameter(self):
        comparison = ParameterFoldComparison(
            parameter_name="hill_K__TV",
            fold_point_values=(("fold_1", 1.0), ("fold_2", 1.0), ("fold_3", 1.0)),
        )
        assert comparison.point_range == pytest.approx(0.0)

    def test_point_range_is_nan_when_no_folds_reported_it(self):
        comparison = ParameterFoldComparison(
            parameter_name="hill_K__TV", fold_point_values=()
        )
        assert np.isnan(comparison.point_range)

    def test_round_trip(self):
        original = ParameterFoldComparison(
            parameter_name="hill_K__TV",
            fold_point_values=(("fold_1", 1.0), ("fold_2", 1.5)),
            fold_draws={"fold_1": (0.9, 1.0, 1.1)},
        )
        restored = ParameterFoldComparison.from_dict(original.to_dict())
        assert restored == original

    def test_no_threshold_or_verdict_field_exists(self):
        """REQ-STAB-001 requirement 3: this record does not approve one
        opaque aggregate health score. `to_dict` must expose only
        descriptive fields, never a pass/fail/status verdict."""
        comparison = ParameterFoldComparison(
            parameter_name="hill_K__TV",
            fold_point_values=(("fold_1", 1.0), ("fold_2", 100.0)),
        )
        payload = comparison.to_dict()
        for forbidden in ("status", "verdict", "pass", "fail", "stable", "unstable"):
            assert forbidden not in payload


# ---------------------------------------------------------------------------
# StructuralStabilityArtefact / assess_structural_stability
# ---------------------------------------------------------------------------


class TestAssessStructuralStability:
    def test_rejects_empty_snapshots(self):
        with pytest.raises(ValueError, match="snapshots must not be empty"):
            assess_structural_stability(())

    def test_rejects_duplicate_fold_ids(self):
        snapshots = (
            FoldParameterSnapshot(fold_id="fold_1", point_values={"hill_K__TV": 1.0}),
            FoldParameterSnapshot(fold_id="fold_1", point_values={"hill_K__TV": 1.1}),
        )
        with pytest.raises(ValueError, match="duplicate fold_id"):
            assess_structural_stability(snapshots)

    def test_stable_parameter_has_near_zero_point_range(self):
        """A parameter that genuinely does not move across folds must be
        reported with a near-zero range - not obscured behind, or
        confused with, any pass/fail interpretation."""
        snapshots = tuple(
            FoldParameterSnapshot(fold_id=f"fold_{i}", point_values={"hill_K__TV": 1.0})
            for i in range(1, 5)
        )
        artefact = assess_structural_stability(snapshots)
        assert len(artefact.per_parameter) == 1
        assert artefact.per_parameter[0].point_range == pytest.approx(0.0)
        assert artefact.limitations == ()

    def test_drifting_parameter_has_large_point_range_reported_descriptively(self):
        """A parameter that genuinely drifts across folds (e.g. a
        synthetic regime change) must show a correspondingly large range -
        reported as evidence, with no threshold applied and no verdict
        rendered by this module."""
        drift_values = [1.0, 1.0, 5.0, 5.0]  # a synthetic regime shift
        snapshots = tuple(
            FoldParameterSnapshot(fold_id=f"fold_{i}", point_values={"hill_K__TV": v})
            for i, v in enumerate(drift_values, start=1)
        )
        artefact = assess_structural_stability(snapshots)
        comparison = artefact.per_parameter[0]
        assert comparison.point_range == pytest.approx(4.0)
        assert comparison.fold_point_values == (
            ("fold_1", 1.0),
            ("fold_2", 1.0),
            ("fold_3", 5.0),
            ("fold_4", 5.0),
        )

    def test_multiple_parameters_compared_independently(self):
        snapshots = (
            FoldParameterSnapshot(
                fold_id="fold_1",
                point_values={"hill_K__TV": 1.0, "adstock_decay__TV": 0.5},
            ),
            FoldParameterSnapshot(
                fold_id="fold_2",
                point_values={"hill_K__TV": 1.2, "adstock_decay__TV": 0.5},
            ),
        )
        artefact = assess_structural_stability(snapshots)
        by_name = {p.parameter_name: p for p in artefact.per_parameter}
        assert by_name["hill_K__TV"].point_range == pytest.approx(0.2)
        assert by_name["adstock_decay__TV"].point_range == pytest.approx(0.0)

    def test_missing_parameter_in_one_fold_records_a_limitation(self):
        """A parameter present in some folds but not others must never be
        silently dropped or backfilled - it must appear as a recorded
        limitation, and the comparison for that parameter must only
        include the folds that actually reported it."""
        snapshots = (
            FoldParameterSnapshot(
                fold_id="fold_1", point_values={"hill_K__TV": 1.0, "hill_K__Radio": 2.0}
            ),
            FoldParameterSnapshot(fold_id="fold_2", point_values={"hill_K__TV": 1.1}),
        )
        artefact = assess_structural_stability(snapshots)
        assert len(artefact.limitations) == 1
        assert "hill_K__Radio" in artefact.limitations[0]
        assert "fold_2" in artefact.limitations[0]

        by_name = {p.parameter_name: p for p in artefact.per_parameter}
        assert len(by_name["hill_K__Radio"].fold_point_values) == 1
        assert by_name["hill_K__Radio"].fold_point_values[0][0] == "fold_1"

    def test_posterior_draws_preserved_per_fold_not_reduced_to_point(self):
        """Requirement 3: the comparison must preserve posterior
        uncertainty per fold - it must not reduce every fold to a bare
        point estimate when draws are available."""
        snapshots = (
            FoldParameterSnapshot(
                fold_id="fold_1",
                point_values={"hill_K__TV": 1.0},
                draws={"hill_K__TV": (0.9, 1.0, 1.1)},
            ),
            FoldParameterSnapshot(
                fold_id="fold_2",
                point_values={"hill_K__TV": 1.2},
                draws={"hill_K__TV": (1.1, 1.2, 1.3)},
            ),
        )
        artefact = assess_structural_stability(snapshots)
        comparison = artefact.per_parameter[0]
        assert comparison.fold_draws["fold_1"] == (0.9, 1.0, 1.1)
        assert comparison.fold_draws["fold_2"] == (1.1, 1.2, 1.3)

    def test_artefact_round_trip(self):
        snapshots = (
            FoldParameterSnapshot(fold_id="fold_1", point_values={"hill_K__TV": 1.0}),
            FoldParameterSnapshot(fold_id="fold_2", point_values={"hill_K__TV": 1.1}),
        )
        artefact = assess_structural_stability(snapshots)
        restored = StructuralStabilityArtefact.from_dict(artefact.to_dict())
        assert restored == artefact


# ---------------------------------------------------------------------------
# Integration with core.validation_folds (REQ-STAB-001 requirement 6: the
# two records share one notion of what a historical fold is)
# ---------------------------------------------------------------------------


class TestSharedFoldIdentityWithValidationFolds:
    def test_fold_ids_from_validation_folds_flow_through_unchanged(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="W")
        df = pd.DataFrame({"date": dates})
        folds = build_expanding_window_folds(df, "date", n_folds=3, min_train_frac=0.5)

        snapshots = tuple(
            FoldParameterSnapshot(
                fold_id=fold.fold_id, point_values={"hill_K__TV": 1.0 + i * 0.1}
            )
            for i, fold in enumerate(folds)
        )
        artefact = assess_structural_stability(snapshots)
        assert artefact.fold_ids == tuple(f.fold_id for f in folds)
