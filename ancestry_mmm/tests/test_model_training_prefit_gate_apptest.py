"""AppTest coverage for `REQ-PREFIT-001`'s mandatory pre-fit gate on the
official "Build & fit model" button (Work Package 1 correction): the gate
must consult the one consolidated `core.prefit_run.PrefitRun` readiness
state, and must remain fail-closed - absent, blocked, or under-reviewed
pre-fit evidence must keep the button from ever rendering for an official
frame. No live MCMC fit is run here (see tests/AGENTS.md); the real,
lightweight prior-predictive preview is exercised via its own button click
so this test proves the *pre-fit* half of the gate in isolation.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.prefit_run import build_prefit_run
from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "05_Model_Training.py"

CHANNELS = ["TV", "Radio"]
OUTCOME_ID = "fh_new_gsa"


def _frame(n_obs: int = 16, **overrides):
    rng = np.random.default_rng(11)
    dates = pd.date_range("2024-01-01", periods=n_obs, freq="W")
    x_media = rng.uniform(0, 100, size=(n_obs, 2))
    Y = rng.uniform(5, 30, size=(n_obs, 1))
    frame = {
        "Y": Y,
        "X_media": x_media,
        "X_controls": np.zeros((n_obs, 0)),
        "control_names": [],
        "markets": ["UK"],
        "market_bounds": [(0, n_obs)],
        "market_idx": np.zeros(n_obs, dtype=int),
        "promo": np.zeros((n_obs, 1)),
        "trend": np.arange(n_obs, dtype=float),
        "fourier": np.zeros((n_obs, 4)),
        "outcome_ids": [OUTCOME_ID],
        "channels": CHANNELS,
        "dna_channel_idx": [],
        "dates": dates.to_numpy(),
        "preparation_mode": "official",
        "df": pd.DataFrame(
            {
                "date": dates,
                "market": "UK",
                "TV": x_media[:, 0],
                "Radio": x_media[:, 1],
                OUTCOME_ID: Y[:, 0],
            }
        ),
    }
    frame.update(overrides)
    return frame


def _spec_dict():
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": OUTCOME_ID},
        channels=CHANNELS,
    ).to_dict()


def _run_at(**extra_state):
    at = AppTest.from_file(str(PAGE), default_timeout=120)
    at.session_state["frame"] = _frame()
    at.session_state["model_spec"] = _spec_dict()
    at.session_state["mcmc_draws"] = 100
    at.session_state["mcmc_tune"] = 100
    at.session_state["mcmc_chains"] = 1
    at.session_state["mcmc_target_accept"] = 0.9
    for key, value in extra_state.items():
        at.session_state[key] = value
    at.run()
    return at


def _all_text(at: AppTest) -> str:
    parts = [(m.value or "") for m in at.markdown]
    parts += [(c.value or "") for c in at.caption]
    parts += [(e.value or "") for e in at.error]
    return "\n".join(parts)


def _with_fresh_preview(at: AppTest) -> AppTest:
    """Click the real (lightweight) prior-predictive preview button so the
    gate's separate preview-freshness condition is satisfied, isolating
    these tests to the pre-fit-evidence half of the gate."""
    button = next(
        b for b in at.button if b.label == "Preview prior predictive (no fitting)"
    )
    at = button.click().run()
    assert not at.exception, f"preview click raised: {at.exception}"
    return at


def _fit_button_present(at: AppTest) -> bool:
    return any(b.label == "Build & fit model" for b in at.button)


def _prefit_run_dict(*, readiness_scenario: str) -> dict:
    identifiability_report = {
        "status": "ready",
        "review_status": "ready",
        "fingerprints": {
            "candidate_spec_fingerprint": "cs",
            "prepared_frame_fingerprint": "pf",
            "causal_graph_fingerprint": "cg",
            "transform_config_fingerprint": "tc",
        },
        "prior_predictive": {"review_status": "ready"},
    }
    screening_report = {
        "status": "computed",
        "review_status": "ready"
        if readiness_scenario != "screening_blocked"
        else "blocked",
        "reconstruction_tier": "prepared_frame_only",
        "diagnostic_version": "prefit-screening-v1",
        "screen_grid_version": "bounded-adstock-hill-grid-v1",
        "folds": [{"fold_id": "prefit-fold-1"}],
        "analyst_review": {
            "status": "retained" if readiness_scenario == "ready" else "not_available",
            "rationale": "reviewed" if readiness_scenario == "ready" else None,
            "rationale_retained": readiness_scenario == "ready",
        },
    }
    run = build_prefit_run(
        product="Family History",
        model_name="Model A",
        identifiability_report=identifiability_report,
        screening_report=screening_report,
        fold_policy_version="v1",
        support_threshold_policy_version="support-diagnostic-v1",
        analyst_rationale_retained=readiness_scenario == "ready",
    )
    return run.to_dict()


def test_official_fit_blocked_when_no_prefit_run_recorded():
    at = _run_at()
    at = _with_fresh_preview(at)
    assert not _fit_button_present(at)
    assert "run the pre-fit support review" in _all_text(at)


def test_official_fit_blocked_when_prefit_run_is_blocked():
    at = _run_at(prefit_run=_prefit_run_dict(readiness_scenario="screening_blocked"))
    at = _with_fresh_preview(at)
    assert not _fit_button_present(at)
    assert "blocked" in _all_text(at).lower()


def test_official_fit_blocked_when_review_recommended_without_rationale():
    at = _run_at(prefit_run=_prefit_run_dict(readiness_scenario="no_rationale"))
    at = _with_fresh_preview(at)
    assert not _fit_button_present(at)
    assert "rationale" in _all_text(at).lower()


def test_official_fit_button_appears_when_prefit_run_is_ready():
    at = _run_at(prefit_run=_prefit_run_dict(readiness_scenario="ready"))
    at = _with_fresh_preview(at)
    assert not at.exception, f"page raised: {at.exception}"
    assert _fit_button_present(at)


def test_exploratory_frame_does_not_require_a_prefit_run():
    """A non-official frame is gated by preparation status, not by pre-fit
    evidence at all - REQ-PREFIT-001's exception boundary already covers
    this via `_frame_mode == "official"`; this is a regression guard that
    the pre-fit gate rewrite did not accidentally start requiring a
    PrefitRun for exploratory frames too."""
    at = _run_at(**{"frame": _frame(preparation_mode="exploratory")})
    at = _with_fresh_preview(at)
    assert "run the pre-fit support review" not in _all_text(at)


# --- UX-017 regression coverage -------------------------------------------
#
# Before this fix, `_official_fit_gate_blocked` in 05_Model_Training.py
# evaluated `_frame_mode != "official"` (rather than `== "official"`) and
# never inspected `official_preparation_result["ready"]` at all - so an
# exploratory frame was unconditionally blocked from ever fitting the
# moment any structure existed (regardless of whether official preparation
# was actually unresolved), directly contradicting Model Setup's own
# "available for investigation only" copy for that frame. Meanwhile an
# official frame whose own official preparation was genuinely unresolved
# was never blocked by this specific check at all. These tests exercise the
# exact code path the pre-existing
# `test_exploratory_frame_does_not_require_a_prefit_run` test could not
# reach, because its `_run_at()` helper never populates
# `official_preparation_result` in session state.


def test_exploratory_frame_is_fittable_even_when_official_preparation_is_unresolved():
    """The bug this finding described: an exploratory frame must remain
    fittable for investigation regardless of whether official preparation
    (a concept that does not apply to it at all) is resolved."""
    at = _run_at(
        **{
            "frame": _frame(preparation_mode="exploratory"),
            "official_preparation_result": {"status": "blocked", "ready": False},
        }
    )
    at = _with_fresh_preview(at)
    assert not at.exception, f"page raised: {at.exception}"
    assert _fit_button_present(at)
    assert "official preparation is unresolved" not in _all_text(at)


def test_official_frame_blocked_when_official_preparation_is_unresolved():
    """The genuine governance intent this gate exists for (per its own error
    message, unchanged by this fix): an official frame may not fit an
    official run while official preparation is unresolved."""
    at = _run_at(
        prefit_run=_prefit_run_dict(readiness_scenario="ready"),
        official_preparation_result={"status": "blocked", "ready": False},
    )
    at = _with_fresh_preview(at)
    assert not _fit_button_present(at)
    assert "official preparation is unresolved" in _all_text(at)


def test_official_frame_not_blocked_by_this_gate_once_official_preparation_is_ready():
    """Once official preparation genuinely resolves to ready, this specific
    gate must stop blocking the official frame (the pre-fit gate remains a
    separate, independent check, satisfied here by a ready PrefitRun)."""
    at = _run_at(
        prefit_run=_prefit_run_dict(readiness_scenario="ready"),
        official_preparation_result={"status": "ready", "ready": True},
    )
    at = _with_fresh_preview(at)
    assert not at.exception, f"page raised: {at.exception}"
    assert _fit_button_present(at)
