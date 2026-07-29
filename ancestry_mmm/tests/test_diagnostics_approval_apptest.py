"""AppTest coverage for the Diagnostics page's model-approval control flow
(PR 79A, work package K).

Before this fix, when a configured validation policy was missing/malformed,
or when policy-backed approval failed for any other reason, the page fell
back to creating a standard, policy-unbound ``ModelApproval`` and reported
it to the user identically to a real approval (``st.success``) - silently
turning a blocked/failed governance check into an approved model. These
tests pin the fail-closed replacement: approval is blocked, with a clear
message, and no ``model_approval`` is ever written to session state.
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
    triple - enough for DiagnosticsService.evaluate() and the page's
    identification-diagnostics section to run for real, without raising."""
    rng = np.random.default_rng(7)
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
    """Populate session state so the page reaches the model-approval
    section with a non-blocking activity-governance state and a fully
    resolvable current_model_identity - i.e. every guard before this
    session's work-package-K checks passes."""
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
    at.session_state["model_run_id"] = "run-test-1"
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


def test_approval_blocked_without_validation_policy():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    # No "validation_policy" in session state at all.
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    # Compute the scorecard so the approval section's "not scorecard" guard
    # doesn't mask the check this test targets.
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"
    assert any(
        "No validation policy is configured" in (w.value or "") for w in at.warning
    )
    assert at.session_state["model_approval"] is None


def test_readiness_blocked_without_validation_policy():
    """PR 79A (WP7): clicking 'Evaluate readiness' with no policy configured
    must not silently evaluate against a zero-gate default policy (which
    would trivially report overall_ready=True) - it must warn and leave
    validation_readiness unset."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "No validation policy is configured" in (w.value or "") for w in at.warning
    )
    assert "validation_readiness" not in at.session_state or (
        at.session_state["validation_readiness"] is None
    )


def test_approval_blocked_with_malformed_validation_policy():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    # A policy dict missing each gate's required "name" field is malformed
    # per ValidationGate.from_dict and must block approval, not silently
    # downgrade to an unbound approval.
    at.session_state["validation_policy"] = {
        "policy_id": "bad-policy",
        "version": "1.0",
        "scope": "all_models",
        "owner": "Test",
        "gates": [{"description": "no name field"}],
    }
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"
    assert any(
        "malformed" in (e.value or "") and "approval is blocked" in (e.value or "")
        for e in at.error
    )
    assert at.session_state["model_approval"] is None


def test_passing_evidence_creates_policy_backed_approval_end_to_end():
    """PR 79A (WP10): the full happy path - a valid policy, readiness that
    evaluates to ready, and a submitted approval form must produce a real
    policy-backed ModelApproval (validation_policy_id set, bound to the
    current model identity) with no 'falling back' message anywhere."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    # A single boolean gate that is deterministically satisfied by this
    # fixture's trace (sample_stats.diverging is all-False).
    at.session_state["validation_policy"] = {
        "policy_id": "policy-1",
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

    approved_by_input = next(
        t for t in at.text_input if t.label == "Approved by (name) *"
    )
    approved_by_input.set_value("Test Reviewer").run()
    approve_button = next(
        b for b in at.button if b.label == "Approve this model for planning"
    )
    approve_button.click().run()
    assert not at.exception, f"page raised after approving: {at.exception}"

    approval = at.session_state["model_approval"]
    assert approval is not None
    assert approval["validation_policy_id"] == "policy-1"
    assert approval["approved_by"] == "Test Reviewer"
    # The page reruns (st.rerun()) right after a successful approval, so the
    # transient "Policy-backed model approved" message is replaced by the
    # persistent "Approved by ..." display in the final captured state.
    assert any("Approved by" in (s.value or "") for s in at.success)
    assert not any("Falling back" in (i.value or "") for i in at.info)
    assert not any("Falling back" in (e.value or "") for e in at.error)
    assert not any("Policy-backed approval failed" in (e.value or "") for e in at.error)
