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
from ancestry_mmm.core.coverage import (
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.identification_diagnostics import (
    channel_spend_correlation_matrix,
    design_matrix_condition_number,
    identification_report,
    posterior_coefficient_stability,
)
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


def test_approval_blocked_with_non_valueerror_malformed_policy():
    """PR 88A: the page's old inline handler only caught ValueError around
    ThresholdPolicy.from_dict() - a policy dict whose 'gates' isn't a list
    (e.g. a string, from corrupted session state or a bad import) raises a
    TypeError instead (ValidationGate.from_dict() indexing a single
    character of the string), which used to crash the page with an
    uncaught exception before the fail-closed gate ever ran. Must now be
    reported and treated as malformed, never crash."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = {
        "policy_id": "bad-policy-type-error",
        "version": "1.0",
        "scope": "all_models",
        "owner": "Test",
        "approval_date": "2026-01-01T00:00:00+00:00",
        "gates": "not-a-list",
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


def test_malformed_stored_readiness_does_not_crash_page():
    """A stored approval_readiness dict that fails to deserialize (here,
    'gate_results' isn't a list of gate-result dicts, so ValidationResult.
    from_dict raises a TypeError constructing the required gate_name field)
    must not crash the page - ApprovalReadiness.from_dict() was previously
    called here with no exception handling at all."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["approval_readiness"] = {"gate_results": "not-a-list"}
    at.run()
    assert not at.exception, f"page raised: {at.exception}"


def test_malformed_gate_applicability_readiness_does_not_crash_and_clears_evidence():
    """PR 91A: the exact defect shape from the brief -
    {"gate_applicability": [[]]} - previously raised an uncaught IndexError
    out of ApprovalReadiness.from_dict deep inside load_approval_readiness's
    call on this page. Must not crash, and (since a malformed stored
    readiness can never be "current") must invalidate all four governance-
    evidence keys, not just approval_readiness."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["approval_readiness"] = {"gate_applicability": [[]]}
    at.session_state["validation_results"] = [{"gate_name": "stale"}]
    at.session_state["validation_service_result"] = object()
    at.session_state["model_approval"] = {"approved_by": "stale-approver"}
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert at.session_state["approval_readiness"] is None
    assert at.session_state["validation_results"] is None
    assert at.session_state["validation_service_result"] is None
    assert at.session_state["model_approval"] is None


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


# ---------------------------------------------------------------------------
# PR 82B: canonical diagnostics evidence and state invalidation
# ---------------------------------------------------------------------------


class TestPageNeverRecomputesDiagnosticsDirectly:
    """Identification, correlation matrix, condition number and coefficient
    stability must be computed exactly once, by DiagnosticsService - the
    page renders artefact evidence only. Source-inspection is the most
    direct proof there is no second, independent computation path left on
    the page that could diverge from the artefact."""

    def test_page_does_not_call_identification_functions_directly(self):
        # Comment lines may legitimately *mention* these function names
        # (e.g. explaining what the page no longer does) - only reject an
        # actual call appearing in real code.
        source = "\n".join(
            line
            for line in PAGE.read_text(encoding="utf-8").split("\n")
            if not line.strip().startswith("#")
        )
        for forbidden in (
            "identification_report(",
            "channel_spend_correlation_matrix(",
            "design_matrix_condition_number(",
            "posterior_coefficient_stability(",
            "expanding_window_backtest(",
        ):
            assert forbidden not in source, (
                f"06_Diagnostics.py still calls {forbidden} directly - it must "
                "read from diag_artefact / route through DiagnosticsService instead."
            )


def test_page_artefact_identification_evidence_matches_direct_computation():
    """The artefact stored in session state after 'Compute scorecard' must
    equal what calling the underlying functions directly on the exact same
    (deterministically seeded) trace/frame/meta would produce - proving the
    page's displayed evidence can never diverge from a second, independent
    computation, since there no longer is one."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised: {at.exception}"

    artefact = at.session_state["diagnostics_artefact"]
    trace, frame, meta = _trace_frame_meta()  # same seed -> identical inputs
    expected_flags = identification_report(frame, meta, trace)
    expected_corr = channel_spend_correlation_matrix(frame, meta)
    expected_cond = design_matrix_condition_number(frame)
    expected_stability = posterior_coefficient_stability(trace, meta)

    assert artefact.identification.status == "computed", artefact.identification.error
    assert artefact.identification.payload["flags"] == expected_flags
    assert artefact.identification.payload["condition_number"] == expected_cond
    reconstructed_corr = pd.DataFrame(
        artefact.identification.payload["correlation_matrix"]
    ).T
    assert set(reconstructed_corr.columns) == set(expected_corr.columns)
    assert np.allclose(
        reconstructed_corr.loc[expected_corr.index, expected_corr.columns].values,
        expected_corr.values,
    )

    assert artefact.coefficient_stability.status == "computed", (
        artefact.coefficient_stability.error
    )
    assert artefact.coefficient_stability.payload == expected_stability.to_dict(
        orient="records"
    )


def _minimal_gate_policy(*, policy_id: str, gates: list, **overrides) -> dict:
    policy = {
        "policy_id": policy_id,
        "version": "1.0",
        "scope": "all_models",
        "owner": "Test",
        "approval_date": "2026-01-01T00:00:00+00:00",
        "gates": gates,
    }
    policy.update(overrides)
    return policy


def test_failing_gate_blocks_readiness_and_approval():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = _minimal_gate_policy(
        policy_id="failing-policy",
        gates=[
            {
                # This fixture's trace has no divergences, so requiring
                # divergences=True is deliberately unattainable.
                "name": "divergences",
                "description": "Divergences required (deliberately unattainable)",
                "evaluator_id": "divergences",
                "expected_state": True,
            }
        ],
    )
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    assert at.session_state["approval_readiness"]["overall_ready"] is False
    assert at.session_state["model_approval"] is None


def test_expired_policy_blocks_readiness_and_approval():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = _minimal_gate_policy(
        policy_id="expired-policy",
        approval_date="2020-01-01T00:00:00+00:00",
        expiry="2020-06-01T00:00:00+00:00",
        gates=[
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    )
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    assert at.session_state["approval_readiness"]["overall_ready"] is False
    assert at.session_state["model_approval"] is None


def test_backtest_required_gate_blocks_before_backtest_runs():
    """A policy gate needing backtest_mape must fail closed under the
    official canonical-evidence mode before any backtest has been run - the
    artefact's backtest section is 'not_computed' immediately after
    'Compute scorecard', and official mode must not silently fall back to a
    live recomputation to satisfy it."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = _minimal_gate_policy(
        policy_id="backtest-required-policy",
        gates=[
            {
                "name": "backtest_mape",
                "description": "Backtest MAPE",
                "evaluator_id": "backtest_mape",
                "acceptable_range": [0.0, 10.0],
                "direction": "lower_is_better",
            }
        ],
    )
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert at.session_state["diagnostics_artefact"].backtest.status == "not_computed"

    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    assert at.session_state["approval_readiness"]["overall_ready"] is False
    assert any(
        "not present in the canonical diagnostics artefact" in r["message"]
        for r in at.session_state["approval_readiness"]["gate_results"]
    )
    assert at.session_state["model_approval"] is None


def test_policy_change_invalidates_previously_evaluated_readiness_and_approval():
    """PR 82B: editing the validation policy after readiness/approval were
    granted must invalidate both automatically on the next page load - not
    leave them displayed as still current until someone happens to
    re-evaluate."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    policy_v1 = _minimal_gate_policy(
        policy_id="policy-stale-test",
        gates=[
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    )
    at.session_state["validation_policy"] = dict(policy_v1)
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    assert at.session_state["approval_readiness"]["overall_ready"] is True

    approved_by_input = next(
        t for t in at.text_input if t.label == "Approved by (name) *"
    )
    approved_by_input.set_value("Test Reviewer").run()
    approve_button = next(
        b for b in at.button if b.label == "Approve this model for planning"
    )
    approve_button.click().run()
    assert at.session_state["model_approval"] is not None

    assert at.session_state["validation_results"]

    # Simulate a policy edit since the approval was granted (version bump -
    # same policy_id, different fingerprint).
    policy_v2 = dict(policy_v1)
    policy_v2["version"] = "2.0"
    at.session_state["validation_policy"] = policy_v2
    at.run()

    assert not at.exception, f"page raised after policy change: {at.exception}"
    assert at.session_state["approval_readiness"] is None
    assert any("no longer matches" in (i.value or "") for i in at.info)
    assert at.session_state["model_approval"] is None
    # PR 91A: before this fix, the stale-evidence branch only cleared
    # approval_readiness and validation_service_result directly - it left
    # validation_results (and, only incidentally, model_approval via a
    # downstream re-verification) stale. All four governance-evidence keys
    # must clear together, in the same rerun.
    assert at.session_state["validation_results"] is None
    assert at.session_state["validation_service_result"] is None
    # PR 91A: with model_approval cleared upfront (alongside the other three
    # keys) by the same invalidate_governance_evidence() call, the page's
    # separate downstream require_matching_approval re-verification never
    # sees a still-populated stale approval_dict to reject - so it no
    # longer emits its own "no longer matches the current model, policy, or
    # readiness evidence" warning on top of the info message above. That
    # second warning was a symptom of the incomplete clear (model_approval
    # surviving long enough to be caught downstream); asserting its absence
    # here pins the improved, single-message behaviour.
    assert not any(
        "no longer matches the current model, policy, or readiness evidence"
        in (w.value or "")
        for w in at.warning
    )
    assert not any(w.value for w in at.success)


def test_model_identity_change_invalidates_all_governance_evidence():
    """The same stale-evidence branch as the policy-change test above, but
    triggered by the model identity drifting (e.g. a fresh page load after
    a project import restored a different fitted model) rather than the
    policy changing. Must clear all four governance-evidence keys, not just
    approval_readiness/validation_service_result."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    policy = _minimal_gate_policy(
        policy_id="policy-identity-stale-test",
        gates=[
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    )
    at.session_state["validation_policy"] = dict(policy)
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    assert at.session_state["approval_readiness"]["overall_ready"] is True

    approved_by_input = next(
        t for t in at.text_input if t.label == "Approved by (name) *"
    )
    approved_by_input.set_value("Test Reviewer").run()
    approve_button = next(
        b for b in at.button if b.label == "Approve this model for planning"
    )
    approve_button.click().run()
    assert at.session_state["model_approval"] is not None
    assert at.session_state["validation_results"]

    # Simulate the model run identity changing without going through
    # clear_model_state() (e.g. a fresh page load after a project import
    # restored a different fitted model's run ID).
    at.session_state["model_run_id"] = "run-test-DIFFERENT"
    at.run()

    assert not at.exception, f"page raised after model identity change: {at.exception}"
    assert at.session_state["approval_readiness"] is None
    assert at.session_state["model_approval"] is None
    assert at.session_state["validation_results"] is None
    assert at.session_state["validation_service_result"] is None


# ---------------------------------------------------------------------------
# PR 88A: governance evidence serialization and invalidation
# ---------------------------------------------------------------------------


def test_evaluate_readiness_persists_validation_results():
    """Before this fix, 'validation_results' was never written by this page
    (only the aggregate 'approval_readiness' dict was) - a project bundle's
    validation_results parameter was always None even right after a real
    'Evaluate readiness' click. Clicking it must now persist the full
    per-gate evidence list, using ValidationResult's own to_dict()."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = _minimal_gate_policy(
        policy_id="policy-validation-results",
        gates=[
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    )
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    validation_results = at.session_state["validation_results"]
    assert validation_results, "validation_results was not populated"
    assert all(isinstance(r, dict) for r in validation_results)
    assert {r["gate_name"] for r in validation_results} == {"divergences"}
    assert validation_results[0]["status"] == "pass"
    assert len(validation_results) == len(
        at.session_state["approval_readiness"]["gate_results"]
    )


def test_scorecard_recompute_immediately_clears_prior_governance_evidence():
    """Recomputing the scorecard produces a brand new diagnostics artefact -
    any readiness/validation-results/approval evaluated against the previous
    artefact must be cleared in the same action, not left stale until the
    next rerun's mismatch check happens to catch it."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = _minimal_gate_policy(
        policy_id="policy-recompute-clear",
        gates=[
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    )
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    approved_by_input = next(
        t for t in at.text_input if t.label == "Approved by (name) *"
    )
    approved_by_input.set_value("Test Reviewer").run()
    approve_button = next(
        b for b in at.button if b.label == "Approve this model for planning"
    )
    approve_button.click().run()
    assert at.session_state["model_approval"] is not None
    assert at.session_state["validation_results"]

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    assert at.session_state["model_approval"] is None
    assert at.session_state["validation_results"] is None
    assert at.session_state["approval_readiness"] is None
    assert at.session_state["validation_service_result"] is None


def test_backtest_failure_immediately_clears_approval_and_validation_results():
    """PR 88A: before this fix, a backtest completing (or failing) cleared
    only approval_readiness/validation_service_result in the same action -
    model_approval and validation_results were left stale for one extra
    rerun (only cleared indirectly, the next time require_matching_approval
    happened to be re-evaluated). Triggers the backtest's failure path
    (no transformed_data seeded, so expanding_window_backtest raises
    immediately) since that is deterministic and fast - the fix clears all
    four governance-evidence keys unconditionally, before branching on
    whether the backtest itself succeeded."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = _minimal_gate_policy(
        policy_id="policy-backtest-clear",
        gates=[
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    )
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    approved_by_input = next(
        t for t in at.text_input if t.label == "Approved by (name) *"
    )
    approved_by_input.set_value("Test Reviewer").run()
    approve_button = next(
        b for b in at.button if b.label == "Approve this model for planning"
    )
    approve_button.click().run()
    assert at.session_state["model_approval"] is not None
    assert at.session_state["validation_results"]
    assert at.session_state["approval_readiness"] is not None

    # No "transformed_data" seeded - expanding_window_backtest raises
    # immediately (df[spec.date_col] on None), so DiagnosticsService.
    # run_backtest() catches it and returns a "failed" backtest section -
    # exercising the invalidation path without a real (slow) model refit.
    backtest_button = next(b for b in at.button if b.label == "Run backtest")
    backtest_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    assert any("Backtest failed" in (e.value or "") for e in at.error)
    assert at.session_state["model_approval"] is None
    assert at.session_state["validation_results"] is None
    assert at.session_state["approval_readiness"] is None
    assert at.session_state["validation_service_result"] is None


def test_prior_predictive_check_computes_real_evidence_end_to_end():
    """REQ-VAL-001 Work Package 2: the success path - proving the page's own
    glue code (spec/causal-graph/dna_lag_weeks/prior_config assembly) is
    wired correctly end to end, not only that the underlying service/core
    functions work in isolation (test_prior_predictive.py).

    Uses two channels rather than _trace_frame_meta()'s single-channel
    fixture: a single-channel, single-market frame triggers a pre-existing
    PyTensor scan shape inconsistency in
    core.transformations.pt_geometric_adstock_matrix, reproducible directly
    against build_fh_hierarchical_model with no PyMC-Marketing or Streamlit
    involvement at all - a real but separate defect, out of this PR's
    REQ-VAL-001 scope (adstock/saturation changes have their own required
    upstream-reference workflow, root AGENTS.md); reported separately.
    Two channels sidesteps it without masking it."""
    n_obs = 16
    rng = np.random.default_rng(11)
    channels = ["TV", "Radio"]
    oids = ["fh_new_gsa"]
    x_media = rng.uniform(0, 100, size=(n_obs, 2))

    at = AppTest.from_file(str(PAGE), default_timeout=120)
    _seed_fully_identified_model(at)
    at.session_state["model_spec"] = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=channels,
    ).to_dict()
    frame = dict(at.session_state["frame"])
    frame["channels"] = channels
    frame["dna_channel_idx"] = []
    frame["X_media"] = x_media
    frame["X_controls"] = np.zeros((n_obs, 0))
    frame["control_names"] = []
    at.session_state["frame"] = frame
    meta = at.session_state["model_meta"]
    meta.channels = channels
    meta.dna_channels = []
    meta.dna_channel_idx = []
    meta.non_dna_idx = [0, 1]
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised: {at.exception}"

    # Default "Prior draws" (500) is used as-is - fast enough for this tiny
    # 1-market/2-channel/1-outcome model with no MCMC involved.
    prior_predictive_button = next(
        b for b in at.button if b.label == "Run prior predictive check"
    )
    prior_predictive_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    pp_section = at.session_state["diagnostics_artefact"].prior_predictive
    assert pp_section.status == "computed", pp_section.error
    assert pp_section.payload["model_type"] == "shared"
    assert pp_section.payload["n_samples"] == 500
    assert len(pp_section.payload["rows"]) == len(meta.markets) * len(oids)
    assert any("Prior predictive check computed" in (s.value or "") for s in at.success)


def test_prior_predictive_check_fails_closed_when_fit_time_graph_version_is_unavailable():
    """Codex review (P1, PR #147): before this fix, the page rebuilt the
    prior-predictive model from whatever causal graph was *live* in session
    state, not the exact version `meta` recorded as having been used at fit
    time - a graph edit since the fit (including a layout-only edit, which
    REQ-GRAPH-001 reverts an approved graph to draft) silently fell back to
    the no-graph/legacy-pathway model structure while still being stored as
    "this fit's" prior evidence. `meta.causal_graph_id` is set here but
    "causal_graph_versions" has no matching entry, so the exact fit-time
    version cannot be reconstructed - this must fail closed with a specific
    message, never silently substitute a different structure."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    meta = at.session_state["model_meta"]
    meta.causal_graph_id = "graph-1"
    meta.causal_graph_version = 2
    meta.causal_graph_structural_fingerprint = "fp-graph-1-v2"
    # No "causal_graph_versions" seeded at all - the fit-time version is
    # unavailable, whether because it was never saved to history or this
    # project bundle simply doesn't have it.
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised: {at.exception}"

    prior_predictive_button = next(
        b for b in at.button if b.label == "Run prior predictive check"
    )
    prior_predictive_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    pp_section = at.session_state["diagnostics_artefact"].prior_predictive
    assert pp_section.status == "failed"
    assert "graph-1" in pp_section.error
    assert "no longer available" in pp_section.error


def test_prior_predictive_check_failure_immediately_clears_approval_and_validation_results():
    """REQ-VAL-001 Work Package 2: mirrors
    test_backtest_failure_immediately_clears_approval_and_validation_results
    above exactly, but for the new "Run prior predictive check" section.
    _trace_frame_meta()'s hand-built frame (deliberately minimal - just
    enough for DiagnosticsService.evaluate() and the identification-
    diagnostics section) has no "channels"/"dna_channel_idx"/"X_controls"/
    "control_names" keys, so rebuilding the real model raises a KeyError
    immediately - exercising the page's own rebuild-failure handling and the
    same governance-evidence invalidation without a real (slower) model
    build/sample. See test_prior_predictive_check_computes_real_evidence_
    end_to_end below for the success path against a build-compatible frame."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = _minimal_gate_policy(
        policy_id="policy-prior-predictive-clear",
        gates=[
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    )
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    approved_by_input = next(
        t for t in at.text_input if t.label == "Approved by (name) *"
    )
    approved_by_input.set_value("Test Reviewer").run()
    approve_button = next(
        b for b in at.button if b.label == "Approve this model for planning"
    )
    approve_button.click().run()
    assert at.session_state["model_approval"] is not None
    assert at.session_state["validation_results"]
    assert at.session_state["approval_readiness"] is not None

    prior_predictive_button = next(
        b for b in at.button if b.label == "Run prior predictive check"
    )
    prior_predictive_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    assert any("Prior predictive check failed" in (e.value or "") for e in at.error)
    # The rebuild failure is itself recorded as explicit "failed" canonical
    # evidence (never fabricated as computed, never silently dropped as if
    # nothing happened).
    pp_section = at.session_state["diagnostics_artefact"].prior_predictive
    assert pp_section.status == "failed"
    assert "Could not rebuild the model to sample its priors" in pp_section.error
    assert at.session_state["model_approval"] is None
    assert at.session_state["validation_results"] is None
    assert at.session_state["approval_readiness"] is None
    assert at.session_state["validation_service_result"] is None


# ---------------------------------------------------------------------------
# REQ-COVERAGE-001 S6, Work Package 5 (review finding, PR #158): informational
# engine-capability display in the Model approval section.
# ---------------------------------------------------------------------------


def test_unsupported_capability_shows_informational_message_and_does_not_block_approval():
    """No coverage matrix at all means this fit's (market, channel)
    combination is unsupported (REQ-COVERAGE-001 S6) - the page must say so
    near approval, but purely informationally: approval itself must still
    succeed, since hard-gating official use on this check is a business
    decision this PR declines to invent."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = _minimal_gate_policy(
        policy_id="policy-capability-info",
        gates=[
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    )
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "goes beyond today's supported market/channel coverage" in (i.value or "")
        for i in at.info
    )

    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    approved_by_input = next(
        t for t in at.text_input if t.label == "Approved by (name) *"
    )
    approved_by_input.set_value("Test Reviewer").run()
    approve_button = next(
        b for b in at.button if b.label == "Approve this model for planning"
    )
    approve_button.click().run()
    assert not at.exception, f"page raised after approving: {at.exception}"
    assert at.session_state["model_approval"] is not None


def test_supported_capability_shows_no_informational_message():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    record = VariableCoverageRecord(
        variable_id="TV",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class="flow_count",
        ),
        coverage_segments=(),
    )
    at.session_state["variable_coverage_matrix"] = VariableCoverageMatrix(
        matrix_id="m1", matrix_version=1, generated_at="2026-01-01", records=(record,)
    ).to_dict()
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert not any(
        "goes beyond today's supported market/channel coverage" in (i.value or "")
        for i in at.info
    )


def test_predictive_density_check_failure_immediately_clears_approval_and_validation_results():
    """REQ-VAL-001 Work Package 3: mirrors
    test_prior_predictive_check_failure_immediately_clears_approval_and_
    validation_results exactly, but for the new "Run predictive density
    check" section, which shares the same page-level model-rebuild helper
    (_rebuild_fit_time_model) and so fails for the same reason (the fixture
    frame is missing keys build_fh_hierarchical_model needs). The success
    path (real pm.compute_log_likelihood + az.loo/az.waic against a real
    fitted trace, real Model A and Model C builders) is covered directly in
    test_predictive_density.py, which uses a genuine small MCMC fit rather
    than this fixture's hand-built fake trace - a stronger test of the
    actual computation than an AppTest could give without constructing a
    second full fake-trace fixture shaped for a build-compatible model; this
    AppTest instead proves the page's own button/service/governance wiring
    behaves correctly, sharing the same _rebuild_fit_time_model() helper
    already proven end-to-end by test_prior_predictive_check_computes_real_
    evidence_end_to_end above."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["validation_policy"] = _minimal_gate_policy(
        policy_id="policy-predictive-density-clear",
        gates=[
            {
                "name": "divergences",
                "description": "No divergences",
                "evaluator_id": "divergences",
                "expected_state": False,
            }
        ],
    )
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    readiness_button = next(b for b in at.button if b.label == "Evaluate readiness")
    readiness_button.click().run()
    approved_by_input = next(
        t for t in at.text_input if t.label == "Approved by (name) *"
    )
    approved_by_input.set_value("Test Reviewer").run()
    approve_button = next(
        b for b in at.button if b.label == "Approve this model for planning"
    )
    approve_button.click().run()
    assert at.session_state["model_approval"] is not None
    assert at.session_state["validation_results"]
    assert at.session_state["approval_readiness"] is not None

    predictive_density_button = next(
        b for b in at.button if b.label == "Run predictive density check"
    )
    predictive_density_button.click().run()

    assert not at.exception, f"page raised: {at.exception}"
    assert any("Predictive density check failed" in (e.value or "") for e in at.error)
    pd_section = at.session_state["diagnostics_artefact"].predictive_density
    assert pd_section.status == "failed"
    assert (
        "Could not rebuild the model to compute predictive density" in pd_section.error
    )
    assert at.session_state["model_approval"] is None
    assert at.session_state["validation_results"] is None
    assert at.session_state["approval_readiness"] is None
    assert at.session_state["validation_service_result"] is None
