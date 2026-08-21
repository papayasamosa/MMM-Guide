"""Synthetic checks for the historical remediation gate (WP0)."""

from __future__ import annotations

import pandas as pd

from scripts.run_historical_mmm_remediation import (
    _classify_structural_zero,
    write_prefit_summary,
)


def test_structural_zero_classifier_distinguishes_pre_and_post_campaign() -> None:
    approved = pd.DataFrame(
        {
            "period_start": pd.to_datetime(
                ["2023-01-01", "2023-01-08", "2023-02-01"]
            ),
            "measure": [0.0, 10.0, 0.0],
        }
    )

    assert (
        _classify_structural_zero(
            pd.Timestamp("2022-12-25"), approved, "measure"
        )
        == "structural_zero_pre_launch"
    )
    assert (
        _classify_structural_zero(
            pd.Timestamp("2023-02-05"), approved, "measure"
        )
        == "structural_zero_post_campaign"
    )


def test_optional_unprepared_context_does_not_block_fit_summary(tmp_path) -> None:
    summary = write_prefit_summary(
        tmp_path,
        {"genuine_missing_required_fit_observations": 0},
        {"status": "resolved"},
        {
            "variables": [
                {"included_in_fit": False, "prepared": False},
            ]
        },
        {"status": "corrected_capability_not_real_data_approved"},
        {"status": "draft"},
        {"status": "computed_for_review"},
    )

    assert summary["recommendation"] == "2. governance/graph approval required"
    assert not any("context" in reason for reason in summary["blocking_reasons"])


def test_unprepared_required_context_is_reported_as_a_blocker(tmp_path) -> None:
    summary = write_prefit_summary(
        tmp_path,
        {"genuine_missing_required_fit_observations": 0},
        {"status": "resolved"},
        {
            "variables": [
                {"included_in_fit": True, "prepared": False},
            ]
        },
        {"status": "corrected_capability_not_real_data_approved"},
        {"status": "draft"},
        {"status": "computed_for_review"},
    )

    assert any("context" in reason for reason in summary["blocking_reasons"])
