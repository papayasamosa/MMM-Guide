"""Unit tests for application.curve_annotations (Phase 6 UI overhaul).

Covers: annotation_from_legacy_curve's real-history-derived current/observed
support and reuse of already-computed CPA; annotation_from_official_support's
model-input-vs-monetary gating (REQ-CURVE-001 / pages/AGENTS.md Curve UI
rule: never display monetary CPA/ROI without a valid monetary mapping) -
explicitly with and without a monetary mapping, confirming the model-input
fallback path blocks monetary display when no mapping/curve_type="monetary"
economics exist.
"""

import math

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.application.curve_annotations import (
    CurveAnnotation,
    annotation_from_legacy_curve,
    annotation_from_official_support,
)
from ancestry_mmm.core.canonical_curves import SUPPORT_AVAILABLE, SUPPORT_MISSING


def _curve_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "spend": [0.0, 50.0, 100.0, 150.0, 200.0],
            "overall_response": [0.0, 5.0, 9.0, 11.0, 12.0],
            "fh_response": [0.0, 5.0, 9.0, 11.0, 12.0],
        }
    )


def _cpa_df(curve_df: pd.DataFrame) -> pd.DataFrame:
    out = curve_df.copy()
    out["avg_cpa"] = np.where(
        out["fh_response"] > 0, out["spend"] / out["fh_response"], np.nan
    )
    marginal = out["fh_response"].diff() / out["spend"].diff()
    out["marginal_cpa"] = np.where(marginal > 0, 1.0 / marginal, np.nan)
    return out


class TestAnnotationFromLegacyCurve:
    def test_empty_history_returns_no_point_annotation(self):
        curve_df = _curve_df()
        annotation = annotation_from_legacy_curve(curve_df, _cpa_df(curve_df), [])
        assert annotation.current_x is None
        assert annotation.observed_min is None
        assert annotation.observed_max is None
        assert annotation.annotation_lines() == []

    def test_current_and_support_are_real_history_mean_min_max(self):
        curve_df = _curve_df()
        history = [40.0, 60.0, 80.0]
        annotation = annotation_from_legacy_curve(
            curve_df, _cpa_df(curve_df), history, status_label="Shared"
        )
        assert annotation.current_x == pytest.approx(60.0)
        assert annotation.observed_min == pytest.approx(40.0)
        assert annotation.observed_max == pytest.approx(80.0)
        assert annotation.status_label == "Shared"

    def test_economics_labels_come_from_supplied_cpa_df_never_recomputed(self):
        curve_df = _curve_df()
        cpa_df = _cpa_df(curve_df)
        annotation = annotation_from_legacy_curve(curve_df, cpa_df, [100.0])
        # Nearest curve point to spend=100 is exactly row index 2.
        expected_row = cpa_df.iloc[2]
        assert annotation.average_economics_label is not None
        assert (
            f"{float(expected_row['avg_cpa']):,.2f}"
            in annotation.average_economics_label
        )
        assert annotation.marginal_economics_label is not None
        assert (
            f"{float(expected_row['marginal_cpa']):,.2f}"
            in annotation.marginal_economics_label
        )

    def test_extrapolation_flagged_when_curve_extends_past_observed_max(self):
        curve_df = _curve_df()  # max spend point = 200.0
        annotation = annotation_from_legacy_curve(
            curve_df, _cpa_df(curve_df), [10.0, 20.0, 30.0]
        )
        assert annotation.observed_max == pytest.approx(30.0)
        assert annotation.is_extrapolated is True
        assert "Beyond observed support (extrapolated)" in annotation.annotation_lines()

    def test_no_extrapolation_when_curve_stays_within_observed_range(self):
        curve_df = _curve_df()
        annotation = annotation_from_legacy_curve(
            curve_df, _cpa_df(curve_df), [0.0, 100.0, 200.0, 300.0]
        )
        assert annotation.is_extrapolated is False

    def test_non_finite_history_values_are_ignored_not_fabricated(self):
        curve_df = _curve_df()
        annotation = annotation_from_legacy_curve(
            curve_df, _cpa_df(curve_df), [float("nan"), None, "not-a-number", 50.0]
        )
        assert annotation.current_x == pytest.approx(50.0)


class TestAnnotationFromOfficialSupport:
    _SUPPORT_ROWS = [
        {
            "market": "UK",
            "channel": "TV_Brand",
            "current": 120.0,
            "observed_min": 10.0,
            "observed_max": 300.0,
            "is_extrapolated": False,
        }
    ]

    def test_rejects_unknown_curve_type(self):
        with pytest.raises(ValueError):
            annotation_from_official_support(
                self._SUPPORT_ROWS, "UK", "TV_Brand", curve_type="not_a_type"
            )

    def test_model_input_curve_never_shows_monetary_economics(self):
        """The model-input fallback path: no cost mapping applies, so
        monetary CPA/ROI must never be shown, even if an economics_row is
        (incorrectly) supplied - curve_type is the sole governing signal."""
        annotation = annotation_from_official_support(
            self._SUPPORT_ROWS,
            "UK",
            "TV_Brand",
            curve_type="model_input",
            economics_row={"average_cpa": 12.5, "marginal_cpa": 15.0},
        )
        assert annotation.monetary_blocked is True
        assert annotation.monetary_blocked_reason is not None
        assert annotation.average_economics_label is None
        assert annotation.marginal_economics_label is None
        assert any(
            "monetary CPA/ROI is not shown" in line
            for line in annotation.annotation_lines()
        )
        # Support/current-point evidence is still shown - only economics is gated.
        assert annotation.current_x == pytest.approx(120.0)
        assert annotation.observed_min == pytest.approx(10.0)
        assert annotation.observed_max == pytest.approx(300.0)

    def test_monetary_curve_with_governed_mapping_shows_economics(self):
        annotation = annotation_from_official_support(
            self._SUPPORT_ROWS,
            "UK",
            "TV_Brand",
            curve_type="monetary",
            economics_row={"average_cpa": 12.5, "marginal_cpa": 15.0},
        )
        assert annotation.monetary_blocked is False
        assert annotation.monetary_blocked_reason is None
        assert annotation.average_economics_label is not None
        assert "12.50" in annotation.average_economics_label
        assert annotation.marginal_economics_label is not None
        assert "15.00" in annotation.marginal_economics_label

    def test_monetary_curve_without_economics_row_shows_no_fabricated_numbers(self):
        annotation = annotation_from_official_support(
            self._SUPPORT_ROWS, "UK", "TV_Brand", curve_type="monetary"
        )
        assert annotation.monetary_blocked is False
        assert annotation.average_economics_label is None
        assert annotation.marginal_economics_label is None

    def test_no_matching_support_row_yields_no_point_but_still_resolves_type(self):
        annotation = annotation_from_official_support(
            [], "UK", "TV_Brand", curve_type="monetary"
        )
        assert annotation.current_x is None
        assert annotation.observed_min is None
        assert annotation.observed_max is None

    def test_nan_economics_values_are_never_shown(self):
        annotation = annotation_from_official_support(
            self._SUPPORT_ROWS,
            "UK",
            "TV_Brand",
            curve_type="monetary",
            economics_row={"average_cpa": math.nan, "marginal_cpa": None},
        )
        assert annotation.average_economics_label is None
        assert annotation.marginal_economics_label is None


class TestAnnotationFromOfficialSupportStatusLabel:
    """Production-integration follow-up (Results/exports disclosure
    labels): `observed_support_status` was read off the support row for
    `is_extrapolated` but its own value was silently dropped before
    reaching the chart annotation - `status_label` stayed None for every
    official artifact curve. This fixes that by deriving `status_label`
    from `observed_support_status` when the caller does not supply one."""

    _SUPPORT_ROWS = TestAnnotationFromOfficialSupport._SUPPORT_ROWS

    def test_support_available_derives_a_status_label(self):
        rows = [
            {
                "market": "UK",
                "channel": "TV_Brand",
                "current": 120.0,
                "observed_min": 10.0,
                "observed_max": 300.0,
                "is_extrapolated": False,
                "observed_support_status": SUPPORT_AVAILABLE,
            }
        ]
        annotation = annotation_from_official_support(
            rows, "UK", "TV_Brand", curve_type="model_input"
        )
        assert annotation.status_label is not None
        assert "historical data observed" in annotation.status_label
        assert annotation.status_label in annotation.annotation_lines()

    def test_support_missing_derives_a_support_limited_label(self):
        rows = [
            {
                "market": "UK",
                "channel": "OOH",
                "observed_support_status": SUPPORT_MISSING,
            }
        ]
        annotation = annotation_from_official_support(
            rows, "UK", "OOH", curve_type="model_input"
        )
        assert annotation.status_label is not None
        assert "support-limited" in annotation.status_label

    def test_caller_supplied_status_label_still_overrides_the_derived_default(self):
        rows = [
            {
                "market": "UK",
                "channel": "TV_Brand",
                "observed_support_status": SUPPORT_AVAILABLE,
            }
        ]
        annotation = annotation_from_official_support(
            rows,
            "UK",
            "TV_Brand",
            curve_type="model_input",
            status_label="A different evidence tier label",
        )
        assert annotation.status_label == "A different evidence tier label"

    def test_no_observed_support_status_on_the_row_yields_no_label(self):
        """Matches the module's existing rows (no `observed_support_status`
        key at all) - must stay exactly as before: no fabricated label."""
        annotation = annotation_from_official_support(
            self._SUPPORT_ROWS, "UK", "TV_Brand", curve_type="model_input"
        )
        assert annotation.status_label is None


class TestCurveAnnotationLineOrdering:
    def test_annotation_lines_have_fixed_order(self):
        annotation = CurveAnnotation(
            status_label="Locally estimated",
            is_extrapolated=True,
            average_economics_label="Average CPA at current spend: 1.00",
            marginal_economics_label="Marginal CPA at current spend: 2.00",
        )
        assert annotation.annotation_lines() == [
            "Locally estimated",
            "Beyond observed support (extrapolated)",
            "Average CPA at current spend: 1.00",
            "Marginal CPA at current spend: 2.00",
        ]
