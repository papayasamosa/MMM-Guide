"""AppTest coverage for the Model Training page's Phase 5 shell application
(docs/decision_log.md): the prior-predictive preview status badge (not yet
run / stale / current, reusing the page's own existing staleness signal -
see test_model_training_prior_predictive_preview_apptest.py for the
underlying staleness logic itself) and the "Completed fit" identity summary
shown once a model has trained. No fitting/prediction logic is exercised or
changed here - this is presentation only.
"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.application.fit_job_service import FitJobStore, FitJobSubmission
from ancestry_mmm.application.model_fit_service import SEARCH_CANDIDATE_A_ENGINE
from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.search_intent_taxonomy import (
    SEARCH_INTENT_GROUP_ID_BRAND,
    SEARCH_INTENT_GROUP_ID_NON_BRAND,
)
from ancestry_mmm.core.seo_visibility import (
    GscPositionRow,
    SeoModelFitInputs,
    compute_weekly_positional_visibility_series,
)
from ancestry_mmm.core.google_trends_anchor import (
    GoogleTrendsAnchorFitInputs,
    GoogleTrendsAnchorObservation,
    GoogleTrendsQuerySetDefinition,
    UK_BRAND_DEMAND_QUERY_EXPRESSION,
    UK_BRAND_DEMAND_QUERY_SET_ID,
)

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


def test_adopted_durable_fit_remains_available_for_fingerprint_verified_recovery(
    monkeypatch, tmp_path
):
    """A refreshed session must still expose an already-adopted job."""

    project_name = "UK Production 2026"
    monkeypatch.setenv("ANCESTRY_MMM_FIT_JOB_ROOT", str(tmp_path))
    store = FitJobStore(tmp_path, project_name)
    record = store.create(
        FitJobSubmission(
            project_id=project_name,
            project_display_name=project_name,
            engine="pymc",
            model_type="shared",
            sampler_settings={"draws": 4, "tune": 2, "chains": 1},
            random_seed=42,
            data_fingerprint="data-fp",
            model_spec_fingerprint="spec-fp",
            fit_input_fingerprints={"seo": "seo-fp", "frame": "frame-fp"},
            build_kwargs={"frame": {"values": [1]}, "model_spec": {"x": 1}},
        )
    )
    store.transition(record.job_id, "running")
    store.transition(record.job_id, "succeeded")
    store.mark_adopted(record.job_id, "old-session-run")

    at = _run_at(project_name=project_name)

    assert not at.exception, f"page raised: {at.exception}"
    assert any(button.label == "Re-adopt completed fit" for button in at.button)


def test_adopting_durable_fit_restores_the_frozen_search_grain_frame(
    monkeypatch, tmp_path
):
    """Downstream replay must use the same sliced frame the worker fitted."""

    project_name = "grain-project"
    monkeypatch.setenv("ANCESTRY_MMM_FIT_JOB_ROOT", str(tmp_path))
    base_frame = _frame()
    frozen_frame = dict(base_frame)
    frozen_frame["channels"] = ["TV"]
    frozen_frame["X_media"] = base_frame["X_media"][:, :1]
    frozen_spec = _spec_dict()
    frozen_spec["channels"] = ["TV"]
    store = FitJobStore(tmp_path, project_name)
    record = store.create(
        FitJobSubmission(
            project_id=project_name,
            project_display_name=project_name,
            engine="pymc",
            model_type="shared",
            sampler_settings={
                "draws": 4,
                "tune": 2,
                "chains": 1,
                "target_accept": 0.83,
            },
            random_seed=42,
            data_fingerprint="data-fp",
            model_spec_fingerprint="spec-fp",
            fit_input_fingerprints={"seo": "seo-fp", "frame": "data-fp"},
            build_kwargs={"frame": frozen_frame, "model_spec": frozen_spec},
        )
    )
    store.transition(record.job_id, "running")
    store.transition(record.job_id, "succeeded")
    fitted_meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=[OUTCOME_ID],
        channels=["TV"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id=OUTCOME_ID,
        dna_lag_weeks=0,
        unpooled_markets=[],
        control_names=[],
    )

    def fake_load_succeeded_fit(backend, job_id, **kwargs):
        return object(), fitted_meta, backend.store.get(job_id)

    monkeypatch.setattr(
        "ancestry_mmm.application.fit_job_service.LocalFitJobBackend.load_succeeded_fit",
        fake_load_succeeded_fit,
    )
    import ancestry_mmm.core.predict as predict

    monkeypatch.setattr(predict, "extract_posterior_params", lambda *args: {"ok": 1})

    at = _run_at(project_name=project_name, frame=base_frame)
    adopt = next(
        button for button in at.button if button.label == "Adopt completed fit"
    )
    at = adopt.click().run()

    assert not at.exception, f"fit adoption raised: {at.exception}"
    assert at.session_state["frame"]["channels"] == ["TV"]
    assert at.session_state["frame"]["X_media"].shape == (len(base_frame["X_media"]), 1)
    assert at.session_state["model_spec"]["channels"] == ["TV"]
    assert at.session_state["mcmc_draws"] == 4
    assert at.session_state["mcmc_tune"] == 2
    assert at.session_state["mcmc_chains"] == 1
    assert at.session_state["mcmc_target_accept"] == 0.83
    assert at.session_state["mcmc_random_seed"] == 42


def test_changed_seo_boundary_clears_adopted_fit_and_downstream_evidence():
    """Replacing SEO observations cannot leave a stale posterior approved."""

    weeks = [str(pd.Timestamp(week).date()) for week in _frame()["dates"]]
    existing_seo = SeoModelFitInputs.from_observations(
        compute_weekly_positional_visibility_series(
            {("UK", week): [GscPositionRow("ancestry", 1.0, 100.0)] for week in weeks}
        ),
        model_markets=["UK"] * len(weeks),
        model_weeks=weeks,
    )
    at = _run_at(
        model_trained=True,
        model_type="shared",
        model_run_id="old-run",
        trace=object(),
        posterior_params={"old": 1},
        model_approval={"approved_by": "old reviewer"},
        seo_fit_inputs=existing_seo.to_dict(),
    )
    uploader = next(
        item for item in at.file_uploader if "GSC CSV" in (item.label or "")
    )
    rows = [
        "market,week,impressions,dimension_label,position",
        *(
            f"UK,{pd.Timestamp(week).date()},100,ancestry,{1 if index % 2 == 0 else 2}"
            for index, week in enumerate(_frame()["dates"])
        ),
    ]
    uploader.set_value(("gsc.csv", "\n".join(rows).encode(), "text/csv")).run()
    next(
        button
        for button in at.button
        if button.label == "Validate and load SEO visibility"
    ).click().run()

    assert not at.exception, f"SEO upload raised: {at.exception}"
    assert "seo_fit_inputs" in at.session_state, [error.value for error in at.error]
    assert at.session_state["model_trained"] is False
    assert at.session_state["trace"] is None
    assert at.session_state["posterior_params"] is None
    assert at.session_state["model_approval"] is None
    assert any(
        "SEO visibility boundary changed" in (warning.value or "")
        for warning in at.warning
    )


def _google_trends_anchor(raw_offset: float = 0.0):
    weeks = [str(pd.Timestamp(week).date()) for week in _frame()["dates"]]
    query_set = GoogleTrendsQuerySetDefinition(
        query_set_id=UK_BRAND_DEMAND_QUERY_SET_ID,
        branded_terms=tuple(UK_BRAND_DEMAND_QUERY_EXPRESSION.split(" + ")),
        geography="GB",
        time_range_start=weeks[0],
        time_range_end=weeks[-1],
    )
    observations = tuple(
        GoogleTrendsAnchorObservation(
            query_set_id=query_set.query_set_id,
            week=week,
            raw_index=40.0 + index + raw_offset,
            anchor_value=(40.0 + index + raw_offset) / 100.0,
        )
        for index, week in enumerate(weeks)
    )
    return GoogleTrendsAnchorFitInputs(
        query_set=query_set,
        observations=observations,
        model_weeks=tuple(weeks),
    )


def test_changed_candidate_a_trends_anchor_clears_fit_and_downstream_evidence():
    at = _run_at(
        model_trained=True,
        trace=object(),
        posterior_params={"old": 1},
        model_meta=SimpleNamespace(causal_graph_engine=SEARCH_CANDIDATE_A_ENGINE),
        model_approval={"approved_by": "old reviewer"},
        google_trends_anchor=_google_trends_anchor().to_dict(),
        gt_geography="GB",
    )
    uploader = next(
        item for item in at.file_uploader if "Google Trends CSV" in (item.label or "")
    )
    rows = "week,raw_index\n" + "\n".join(
        f"{week},{50 + index}" for index, week in enumerate(_frame()["dates"])
    )
    uploader.set_value(("trends.csv", rows.encode(), "text/csv")).run()
    at = (
        next(
            button
            for button in at.button
            if button.label == "Validate and load Google Trends anchor"
        )
        .click()
        .run()
    )

    assert not at.exception, f"Trends upload raised: {at.exception}"
    assert at.session_state["model_trained"] is False
    assert at.session_state["trace"] is None
    assert at.session_state["posterior_params"] is None
    assert at.session_state["model_approval"] is None
    assert any(
        "Google Trends Candidate A anchor changed" in (warning.value or "")
        for warning in at.warning
    )


def test_non_approved_candidate_a_trends_identity_is_rejected():
    at = _run_at(gt_query_set_id="ad_hoc_query_set", gt_geography="GB")
    uploader = next(
        item for item in at.file_uploader if "Google Trends CSV" in (item.label or "")
    )
    rows = "week,raw_index\n" + "\n".join(
        f"{week},{50 + index}" for index, week in enumerate(_frame()["dates"])
    )
    uploader.set_value(("trends.csv", rows.encode(), "text/csv")).run()
    at = (
        next(
            button
            for button in at.button
            if button.label == "Validate and load Google Trends anchor"
        )
        .click()
        .run()
    )

    assert not at.exception, f"Trends validation raised: {at.exception}"
    assert any(
        "approved UK Google Trends query-set ID" in (error.value or "")
        for error in at.error
    )


def test_search_model_grain_reaches_the_proposed_model_builder(monkeypatch):
    """The selected Search grain changes the physical fit input boundary."""

    base = _frame()
    values = np.column_stack((base["X_media"], base["X_media"][:, :1] * 0.5))
    base["X_media"] = values
    base["channels"] = ["PaidBrand", "PaidNonBrand", "TV"]
    base["df"] = base["df"].copy()
    base["df"]["PaidBrand"] = values[:, 0]
    base["df"]["PaidNonBrand"] = values[:, 1]
    base["df"]["TV"] = values[:, 2]
    spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": OUTCOME_ID},
        channels=base["channels"],
    ).to_dict()
    activities = [
        ActivityDefinition(
            activity_id="paid-brand",
            channel="PaidBrand",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="excluded",
            source="test",
            model_input_column="PaidBrand",
            search_intent_group_id=SEARCH_INTENT_GROUP_ID_BRAND,
            search_platform="google",
        ).to_dict(),
        ActivityDefinition(
            activity_id="paid-non-brand",
            channel="PaidNonBrand",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="excluded",
            source="test",
            model_input_column="PaidNonBrand",
            search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
            search_platform="google",
        ).to_dict(),
    ]
    captured = {}

    def fake_build_model_for_spec(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(model=object(), meta={})

    import ancestry_mmm.application.model_fit_service as fit_service
    import ancestry_mmm.core.diagnostics as diagnostics

    monkeypatch.setattr(fit_service, "build_model_for_spec", fake_build_model_for_spec)
    monkeypatch.setattr(
        diagnostics,
        "prior_predictive_summary",
        lambda *args, **kwargs: {
            "n_samples": kwargs["n_samples"],
            "random_seed": kwargs["random_seed"],
            "rows": [],
            "warnings": [],
        },
    )

    at = _run_at(
        frame=base,
        model_spec=spec,
        activity_definitions=activities,
        search_intent_model_grain=[SEARCH_INTENT_GROUP_ID_BRAND],
    )
    at = (
        next(
            button
            for button in at.button
            if button.label == "Preview prior predictive (no fitting)"
        )
        .click()
        .run()
    )

    assert not at.exception, f"preview raised: {at.exception}"
    assert captured["model_spec"].channels == ["PaidBrand", "TV"]
    assert captured["frame"]["channels"] == ["PaidBrand", "TV"]
    assert captured["frame"]["X_media"].shape == (len(base["X_media"]), 2)
