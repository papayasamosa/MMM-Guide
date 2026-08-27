"""AppTest coverage for the Diagnostics page's Phase 5 redesign (REQ-VAL-001,
docs/decision_log.md): the top-line answer, domain-health rail, and primary-
concern sentence that now lead the page, replacing the old four-equal-
st.metric convergence block. Exercises a passing evidence state and a
blocked (failing gate) state, plus the pre-scorecard state, mirroring the
fixture pattern already used by test_diagnostics_approval_apptest.py.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import arviz as az
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.pathways import resolve_pathway_masks
from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "06_Diagnostics.py"


def _trace_frame_meta():
    """A minimal, single-outcome, single-channel real trace/frame/meta
    triple - enough for DiagnosticsService.evaluate() to run for real,
    without raising (same construction as
    test_diagnostics_approval_apptest.py's fixture)."""
    rng = np.random.default_rng(11)
    n_obs, n_chain, n_draw = 16, 2, 20
    oids = ["fh_new_gsa"]
    chs = ["TV"]

    Y = rng.uniform(5, 30, size=(n_obs, 1))
    trace = az.from_dict(
        posterior={
            "mu": np.maximum(
                Y[None, None, :, 0] + rng.normal(0, 0.5, size=(n_chain, n_draw, n_obs)),
                0.1,
            )[..., None],
            "alpha": np.full((n_chain, n_draw, 1), 8.0),
            "decay_rate": np.full((n_chain, n_draw, 1), 0.5),
            "hill_K": np.ones((n_chain, n_draw, 1)),
            "hill_S": np.full((n_chain, n_draw, 1), 4.0),
            "beta": np.ones((n_chain, n_draw, 1, 1)),
            "intercept": np.zeros((n_chain, n_draw, 1)),
            "trend_coef": np.zeros((n_chain, n_draw, 1)),
            "promo_coef": np.zeros((n_chain, n_draw, 1)),
            "market_offset": np.zeros((n_chain, n_draw, 1, 1)),
            "gamma_fourier": np.zeros((n_chain, n_draw, 4, 1)),
        },
        coords={
            "obs": list(range(n_obs)),
            "outcome": oids,
            "channel": chs,
            "market": ["UK"],
            "fourier": list(range(4)),
        },
        dims={
            "mu": ["obs", "outcome"],
            "alpha": ["outcome"],
            "decay_rate": ["channel"],
            "hill_K": ["channel"],
            "hill_S": ["channel"],
            "beta": ["outcome", "channel"],
            "intercept": ["outcome"],
            "trend_coef": ["outcome"],
            "promo_coef": ["outcome"],
            "market_offset": ["market", "outcome"],
            "gamma_fourier": ["fourier", "outcome"],
        },
        sample_stats={"diverging": np.zeros((n_chain, n_draw), dtype=bool)},
    )

    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=oids,
        channels=chs,
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id=oids[0],
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
        pathway_masks=resolve_pathway_masks(
            oids,
            chs,
            [],
            dna_channel_idx=[],
            dna_outcome_id=oids[0],
            direct_dna_outcome_ids=[],
            dna_lag_weeks=1,
        ),
    )

    dates = pd.date_range("2024-01-01", periods=n_obs, freq="W")
    x_media = rng.uniform(0, 100, size=(n_obs, 1))
    frame = {
        "Y": Y,
        "X_media": x_media,
        "markets": ["UK"],
        "market_bounds": [(0, n_obs)],
        "market_idx": np.zeros(n_obs, dtype=int),
        "promo": np.zeros((n_obs, 1)),
        "trend": np.arange(n_obs, dtype=float),
        "fourier": np.zeros((n_obs, 4)),
        "outcome_ids": oids,
        "dates": dates.to_numpy(),
        "df": pd.DataFrame(
            {"date": dates, "market": "UK", "TV": x_media[:, 0], "fh_new_gsa": Y[:, 0]}
        ),
    }
    return trace, frame, meta


def _seed_fully_identified_model(at: AppTest) -> None:
    trace, frame, meta = _trace_frame_meta()
    at.session_state["trace"] = trace
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = meta
    at.session_state["model_spec"] = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=["TV"],
    ).to_dict()
    at.session_state["posterior_params"] = {"beta": [[1.0]]}
    at.session_state["model_run_id"] = "run-test-rail-1"
    at.session_state["activity_definitions"] = [
        ActivityDefinition(
            activity_id="a1",
            channel="TV",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="test",
            approval_status="approved",
            approved_by="Test Reviewer",
            approved_at="2026-07-29T00:00:00+00:00",
        ).to_dict()
    ]


def _all_markdown_text(at: AppTest) -> str:
    """Every st.markdown AND st.caption value rendered on the page, flattened
    to one string - the domain-health rail renders domain names via
    st.caption and status badges via st.markdown, so a text-presence check
    needs both element collections, not markdown alone."""
    parts = [(m.value or "") for m in at.markdown]
    parts += [(c.value or "") for c in at.caption]
    return "\n".join(parts)


def test_before_scorecard_top_line_says_not_yet_assessed():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.run()
    assert not at.exception, f"page raised on initial load: {at.exception}"
    text = _all_markdown_text(at)
    assert "Diagnostics state" in text
    assert "Not yet assessed" in text


def test_passing_evidence_shows_ready_top_line_and_pass_domain_rows():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    # Deterministically satisfied by this fixture's trace (no divergences).
    at.session_state["validation_policy"] = {
        "policy_id": "policy-pass",
        "version": "1.0",
        "scope": "all_models",
        "owner": "Test",
        "approval_date": "2026-01-01T00:00:00+00:00",
        "gates": [
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    }
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"

    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    assert not at.exception, f"page raised after evaluating readiness: {at.exception}"
    assert at.session_state["approval_readiness"]["overall_ready"] is True

    text = _all_markdown_text(at)
    assert "Ready for planning" in text
    # The domain-health rail must show every one of the seven domains -
    # never four equal st.metric cards.
    for domain in [
        "Convergence",
        "Predictive fit",
        "Residual behaviour",
        "Identification & collinearity",
        "Coverage capability",
        "Plausibility",
        "Approval evidence",
    ]:
        assert domain in text, f"domain-health rail is missing '{domain}'"
    # Approval evidence reflects the real readiness state (pass), not an
    # inferred "a chart rendered so it must be fine" signal.
    assert "Pass" in text


def test_blocked_evidence_shows_not_yet_ready_top_line_and_fail_domain_row():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    # Deterministically fails: the fixture's trace has NO divergences, but
    # this gate expects divergences to be present.
    at.session_state["validation_policy"] = {
        "policy_id": "policy-fail",
        "version": "1.0",
        "scope": "all_models",
        "owner": "Test",
        "approval_date": "2026-01-01T00:00:00+00:00",
        "gates": [
            {
                "name": "divergences",
                "description": "Forced failing gate for this test",
                "evaluator_id": "divergences",
                "expected_state": True,
            }
        ],
    }
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"

    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    assert not at.exception, f"page raised after evaluating readiness: {at.exception}"
    assert at.session_state["approval_readiness"]["overall_ready"] is False

    text = _all_markdown_text(at)
    assert "Not yet ready" in text
    assert "Fail" in text
    # Approval must never be silently granted from a blocked readiness -
    # the approve form must not have created an approval.
    assert at.session_state["model_approval"] is None


def test_top_line_never_claims_approved_without_a_real_approval():
    """A passing readiness must render as "Ready for planning", never as
    approved - approval only ever comes from an actual ModelApproval, per
    REQ-VAL-001 and root AGENTS.md's governance rules."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = {
        "policy_id": "policy-pass-2",
        "version": "1.0",
        "scope": "all_models",
        "owner": "Test",
        "approval_date": "2026-01-01T00:00:00+00:00",
        "gates": [
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    }
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    assert at.session_state["model_approval"] is None
    text = _all_markdown_text(at)
    assert "Approved for planning" not in text


def test_degenerate_convergence_evidence_never_crashes_the_page():
    """A trace missing the 'mu' variable ArviZ's R-hat/ESS check needs
    (e.g. a structurally-valid-but-never-sampled synthetic trace, the same
    shape ancestry_mmm.tests.support.lifecycle_fixture.build_trace produces
    for the official-lifecycle Playwright journey) makes
    DiagnosticsService's own convergence check fail closed to NaN, by
    design - REQ-VAL-001's 'missing evidence is never encoded as zero'.
    The page must render that NaN safely (top-line, domain rail, AND the
    'Full diagnostic detail' Convergence tab's st.metric) rather than
    crashing - round(nan) raises ValueError, which is exactly what a prior
    version of this page's Convergence tab did before this regression test
    was added."""
    trace, frame, meta = _trace_frame_meta()
    del trace.posterior["mu"]
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["trace"] = trace
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = meta
    at.session_state["model_spec"] = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=["TV"],
    ).to_dict()
    at.session_state["posterior_params"] = {"beta": [[1.0]]}
    at.session_state["model_run_id"] = "run-test-nan-1"
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    at = compute_button.click().run()
    assert not at.exception, (
        f"page raised on a degenerate/NaN convergence trace: {at.exception}"
    )
    assert not any(
        "cannot convert float NaN to integer" in (e.value or "") for e in at.error
    )
    text = _all_markdown_text(at)
    assert "Fail" in text  # converged=False for a failed convergence check


# ---------------------------------------------------------------------------
# UI-WP5: specialised evidence is grouped under one clearly labelled,
# collapsed-by-default area, while the primary review flow (top-line summary
# -> domain rail -> primary concern -> full diagnostic detail tabs ->
# validation readiness -> approval) remains plain, unwrapped page content.
# ---------------------------------------------------------------------------


def test_specialised_evidence_sections_are_collapsed_expanders():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.run()
    assert not at.exception, f"page raised on initial load: {at.exception}"

    markdown_texts = [m.value or "" for m in at.markdown]
    assert any("Specialised evidence" in text for text in markdown_texts)

    expander_labels = {e.label for e in at.expander}
    for title in (
        "Prior predictive check",
        "Predictive density (PSIS-LOO / WAIC)",
        "Out-of-sample accuracy (expanding-window backtest)",
        "Funnel-coherence diagnostics",
        "Posterior predictive metric distributions",
        "Historical validation & structural stability",
        "Estimand-specific graphical identification",
        "Latent-state scale/location identification",
        "Experiment & calibration evidence",
    ):
        assert title in expander_labels, title


def test_validation_readiness_and_approval_remain_unwrapped_and_prominent():
    """The primary decision (readiness, then approval) must never itself be
    collapsed behind an expander alongside the specialised evidence - only
    the secondary/optional sections after it are."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.run()
    assert not at.exception, f"page raised on initial load: {at.exception}"

    markdown_texts = [m.value or "" for m in at.markdown]
    assert any(text.strip() == "### Validation readiness" for text in markdown_texts)
    assert any(text.strip() == "### Model approval" for text in markdown_texts)

    expander_labels = {e.label for e in at.expander}
    assert "Validation readiness" not in expander_labels
    assert "Model approval" not in expander_labels
