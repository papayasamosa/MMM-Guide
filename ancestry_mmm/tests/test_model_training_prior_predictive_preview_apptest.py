"""AppTest coverage for the Model Training page's pre-fit "Preview: prior
predictive check (before fitting)" section (REQ-VAL-001 Work Package 4):
binds the existing prior-predictive validation service to the pre-fit
workflow via a proposed-model-identity fingerprint, so a user can inspect
what the PROPOSED model's declared priors imply before committing to a
(potentially long) MCMC fit - and is warned, not silently shown stale
evidence, if the proposal changes after previewing.

Two channels (never one) throughout: a single-channel, single-market frame
triggers a pre-existing PyTensor scan shape inconsistency in
`core.transformations.pt_geometric_adstock_matrix`, reproducible directly
against `build_fh_hierarchical_model` with no Streamlit/prior-predictive
involvement at all (see `test_diagnostics_approval_apptest.py`'s identical
note) - a real but separate, out-of-scope defect; two channels sidesteps it.
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


def _click_preview(at):
    button = next(
        b for b in at.button if b.label == "Preview prior predictive (no fitting)"
    )
    return button.click().run()


def test_preview_computes_real_prior_predictive_evidence():
    at = _run_at()
    assert not at.exception, f"page raised: {at.exception}"
    at = _click_preview(at)
    assert not at.exception, f"preview click raised: {at.exception}"

    preview = at.session_state["prior_predictive_preview"]
    assert preview["status"] == "computed"
    assert preview["model_type"] == "shared"
    assert preview["payload"]["n_samples"] == 500
    assert len(preview["payload"]["rows"]) == 1  # 1 market x 1 outcome_id
    assert preview["proposed_model_fingerprint"]
    assert not any(
        "Prior predictive sampling failed" in (e.value or "") for e in at.error
    )


def test_preview_never_touches_trace_or_fit_state():
    """This is a priors-only preview - REQ-VAL-001: no MCMC, no trace.
    Clicking it must never write model/model_trained/trace/posterior_params,
    which only the real 'Build & fit model' action below may write."""
    at = _run_at()
    at = _click_preview(at)
    assert not at.exception, f"preview click raised: {at.exception}"
    assert "trace" not in at.session_state or at.session_state["trace"] is None
    assert (
        "model_trained" not in at.session_state or not at.session_state["model_trained"]
    )
    assert (
        "posterior_params" not in at.session_state
        or at.session_state["posterior_params"] is None
    )


def test_preview_becomes_stale_after_prior_config_changes():
    at = _run_at()
    at = _click_preview(at)
    assert not at.exception, f"preview click raised: {at.exception}"
    assert not any("no longer reflects" in (w.value or "") for w in at.warning)

    # Change a prior-relevant input after previewing - the shown evidence no
    # longer describes what would actually be fit now.
    changed_priors = dict(at.session_state["prior_config"])
    changed_priors["decay_mu"] = 0.9
    at.session_state["prior_config"] = changed_priors
    at.run()

    assert not at.exception, f"page raised: {at.exception}"
    assert any("no longer reflects" in (w.value or "") for w in at.warning)


def test_preview_is_not_stale_on_a_plain_rerun_with_no_changes():
    at = _run_at()
    at = _click_preview(at)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert not any("no longer reflects" in (w.value or "") for w in at.warning)


def test_preview_build_failure_is_reported_not_silently_swallowed():
    """A DNA-targeted channel is present in the frame, but no FH DNA
    cross-sell outcome is configured - build_fh_hierarchical_model raises a
    ValueError (mirrors the corresponding failure path already covered on
    'Build & fit model'); the preview action must surface it explicitly."""
    frame = _frame()
    frame["dna_channel_idx"] = [0]  # "TV"
    spec_dict = _spec_dict()
    spec_dict["fh_dna_cross_sell_outcome_id"] = None
    at = _run_at(frame=frame, model_spec=spec_dict)
    at = _click_preview(at)
    assert not at.exception, f"preview click raised: {at.exception}"
    preview = at.session_state["prior_predictive_preview"]
    assert preview["status"] == "failed"
    assert "Could not build the proposed model" in preview["error"]
    assert any(
        "Could not build the proposed model" in (e.value or "") for e in at.error
    )


def test_proposed_fingerprint_is_deterministic_and_reused_verbatim():
    """Previewing twice in a row with nothing changed in between must
    produce the exact same proposed-model-identity fingerprint - the
    binding this whole feature rests on would be meaningless if the same
    proposal could hash to two different values."""
    at = _run_at()
    at = _click_preview(at)
    assert not at.exception, f"first preview click raised: {at.exception}"
    first_fingerprint = at.session_state["prior_predictive_preview"][
        "proposed_model_fingerprint"
    ]

    at = _click_preview(at)
    assert not at.exception, f"second preview click raised: {at.exception}"
    second_fingerprint = at.session_state["prior_predictive_preview"][
        "proposed_model_fingerprint"
    ]

    assert first_fingerprint == second_fingerprint
    assert not any("no longer reflects" in (w.value or "") for w in at.warning)
