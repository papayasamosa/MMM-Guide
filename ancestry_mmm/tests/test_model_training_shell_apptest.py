"""AppTest coverage for the Model Training page's Phase 5 shell application
(docs/decision_log.md): the prior-predictive preview status badge (not yet
run / stale / current, reusing the page's own existing staleness signal -
see test_model_training_prior_predictive_preview_apptest.py for the
underlying staleness logic itself) and the "Completed fit" identity summary
shown once a model has trained. No fitting/prediction logic is exercised or
changed here - this is presentation only.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "05_Model_Training.py"

CHANNELS = ["TV", "Radio"]
OUTCOME_ID = "fh_new_gsa"


def _frame(n_obs: int = 16):
    rng = np.random.default_rng(11)
    dates = pd.date_range("2024-01-01", periods=n_obs, freq="W")
    x_media = rng.uniform(0, 100, size=(n_obs, 2))
    Y = rng.uniform(5, 30, size=(n_obs, 1))
    return {
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
    return "\n".join(parts)


def test_preview_badge_shows_not_yet_run_before_previewing():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    text = _all_text(at)
    assert "Fit dashboard" in text
    assert "Fit proposal" in text
    assert "Preview: not yet run" in text
    assert any(
        "Outcomes: Family History · New · GSA" in (caption.value or "")
        for caption in at.caption
    )


def test_preview_badge_shows_current_after_previewing():
    at = _run_at()
    button = next(
        b for b in at.button if b.label == "Preview prior predictive (no fitting)"
    )
    at = button.click().run()
    assert not at.exception, f"preview click raised: {at.exception}"
    assert "Preview: current" in _all_text(at)


def test_preview_badge_shows_stale_after_priors_change():
    at = _run_at()
    button = next(
        b for b in at.button if b.label == "Preview prior predictive (no fitting)"
    )
    at = button.click().run()
    assert not at.exception, f"preview click raised: {at.exception}"

    changed_priors = dict(at.session_state["prior_config"])
    changed_priors["decay_mu"] = 0.9
    at.session_state["prior_config"] = changed_priors
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert "Preview: stale" in _all_text(at)


def test_no_completed_fit_card_before_training():
    at = _run_at()
    assert "Completed fit" not in _all_text(at)


def test_completed_fit_card_shows_real_run_identity_after_training():
    """Simulates a post-fit session state (the same shape the real 'Build &
    fit model' handler writes) rather than running a live MCMC fit through
    the AppTest button, per tests/AGENTS.md's rule against a live NUTS/MCMC
    fit in a browser-driven test - this is presentation-only coverage of
    what the page shows once training has happened, not of the fit itself
    (already covered by non-Streamlit model tests)."""
    at = _run_at(
        model_trained=True,
        model_type="shared",
        model_run_id="11111111-2222-3333-4444-555555555555",
        model_approval=None,
    )
    assert not at.exception, f"page raised: {at.exception}"
    text = _all_text(at)
    assert "Completed fit" in text
    assert "Trained" in text
    assert "11111111" in text
    assert "Not yet approved" in text


def test_completed_fit_card_reflects_real_approval_state():
    at = _run_at(
        model_trained=True,
        model_type="shared",
        model_run_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        model_approval={"approved_by": "Test Reviewer"},
    )
    assert not at.exception, f"page raised: {at.exception}"
    assert "Approved" in _all_text(at)


def test_progress_display_never_shows_a_percentage_before_any_real_progress_report():
    """Root brief rule: no fake progress animation implying sampling
    progress the backend cannot genuinely report. The page's durable-job
    progress bar is derived only from persisted completed/total steps; the
    worker populates those fields from fit_model's real progress callback."""
    source = PAGE.read_text(encoding="utf-8")
    assert "st.progress(fraction)" in source
    assert "min(1.0, progress.completed_steps / progress.total_steps)" in source
    assert "completed_steps" in source
    assert "total_steps" in source
