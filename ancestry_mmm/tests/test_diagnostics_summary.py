"""Unit tests for ancestry_mmm.application.diagnostics_summary (Phase 5 of
the Streamlit UI/UX overhaul; REQ-VAL-001) - the pure domain-health-rail /
top-line-readiness derivation behind the redesigned Diagnostics page.

No Streamlit involved: these test the plain-Python derivation only, mirroring
the "framework-independent, test the derivation directly" convention already
used for core.coverage_fabric (see test_coverage_fabric.py).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from ancestry_mmm.application.diagnostics_summary import (
    compute_domain_health,
    compute_top_line_status,
    derive_primary_concern,
)
from ancestry_mmm.core.market_data_capability import (
    EngineCapabilityResult,
    MarketChannelCapabilityIssue,
)
from ancestry_mmm.core.validation_policy import (
    ApprovalReadiness,
    ThresholdPolicy,
    ValidationGate,
    ValidationResult,
)


def _section(status: str, payload: Any = None, error: str = "") -> SimpleNamespace:
    """A minimal DiagnosticSection duck-type (status/payload/error) - avoids
    depending on application.diagnostics_service's full DiagnosticsArtefact
    construction contract for a purely presentational unit test."""
    return SimpleNamespace(status=status, payload=payload, error=error)


def _artefact(**sections: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(**sections)


def _policy(gates) -> ThresholdPolicy:
    return ThresholdPolicy(
        policy_id="pol-1",
        version="1.0.0",
        scope="all_models",
        gates=gates,
        owner="Modelling",
        approval_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _readiness(
    *, gate_results=(), blocking=(), review=(), passes=(), missing=(), ready
) -> ApprovalReadiness:
    return ApprovalReadiness(
        readiness_artefact_id="ra-1",
        policy_id="pol-1",
        policy_version="1.0.0",
        gate_results=tuple(gate_results),
        blocking_failures=tuple(blocking),
        review_items=tuple(review),
        passes=tuple(passes),
        missing_required_gates=tuple(missing),
        overall_ready=ready,
        schema_version=3,
    )


class TestConvergenceDomain:
    def test_not_computed_without_scorecard(self):
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=None,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        conv = next(r for r in rows if r.domain == "Convergence")
        assert conv.status == "not_computed"

    def test_pass_when_converged(self):
        scorecard = {
            "convergence": {
                "max_rhat": 1.01,
                "min_ess": 500,
                "divergences": 0,
                "converged": True,
            }
        }
        rows = compute_domain_health(
            scorecard=scorecard,
            diag_artefact=None,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        conv = next(r for r in rows if r.domain == "Convergence")
        assert conv.status == "pass"
        assert "1.010" in conv.detail

    def test_fail_when_not_converged(self):
        scorecard = {
            "convergence": {
                "max_rhat": 1.5,
                "min_ess": 10,
                "divergences": 5,
                "converged": False,
            }
        }
        rows = compute_domain_health(
            scorecard=scorecard,
            diag_artefact=None,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        conv = next(r for r in rows if r.domain == "Convergence")
        assert conv.status == "fail"

    def test_gate_result_overrides_scorecard(self):
        gate = ValidationGate(
            name="rhat_gate", description="R-hat", evaluator_id="convergence_rhat"
        )
        policy = _policy([gate])
        result = ValidationResult(
            gate_name="rhat_gate", status="review", message="borderline"
        )
        readiness = _readiness(gate_results=[result], review=[result], ready=False)
        scorecard = {
            "convergence": {
                "max_rhat": 1.0,
                "min_ess": 500,
                "divergences": 0,
                "converged": True,
            }
        }
        rows = compute_domain_health(
            scorecard=scorecard,
            diag_artefact=None,
            capability_result=None,
            readiness=readiness,
            policy=policy,
        )
        conv = next(r for r in rows if r.domain == "Convergence")
        # The evaluated gate ("review") takes priority over the raw boolean
        # ("pass") - the gate is the actual governed judgement.
        assert conv.status == "review"
        assert "borderline" in conv.detail


class TestPredictiveFitDomain:
    def test_reported_when_no_gate_configured(self):
        scorecard = {
            "in_sample_fit": [{"outcome_id": "a", "r_squared": 0.8}],
            "ppc_coverage": [{"outcome_id": "a", "coverage_pct": 92.0}],
        }
        rows = compute_domain_health(
            scorecard=scorecard,
            diag_artefact=None,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        pf = next(r for r in rows if r.domain == "Predictive fit")
        assert pf.status == "reported"
        assert "0.80" in pf.detail

    def test_not_computed_without_evidence(self):
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=None,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        pf = next(r for r in rows if r.domain == "Predictive fit")
        assert pf.status == "not_computed"


class TestResidualBehaviourDomain:
    def test_never_pass_fail_only_reported(self):
        artefact = _artefact(
            residual_diagnostics=_section("computed", payload=[{"market": "UK"}])
        )
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=artefact,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        rb = next(r for r in rows if r.domain == "Residual behaviour")
        assert rb.status == "reported"
        assert "no blocking threshold" in rb.detail

    def test_failed_computation_is_distinct_from_evidence_fail(self):
        artefact = _artefact(residual_diagnostics=_section("failed", error="boom"))
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=artefact,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        rb = next(r for r in rows if r.domain == "Residual behaviour")
        assert rb.status == "failed"
        assert rb.detail == "boom"


class TestIdentificationDomain:
    def test_pass_with_no_flags(self):
        artefact = _artefact(
            identification=_section(
                "computed",
                payload={
                    "flags": [],
                    "correlation_matrix": {},
                    "condition_number": 5.0,
                },
            )
        )
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=artefact,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        ident = next(r for r in rows if r.domain == "Identification & collinearity")
        assert ident.status == "pass"

    def test_review_when_error_flag_present(self):
        """Overnight UI/UX pass (2026-08-29): an "error"-severity
        identification flag is a stronger review signal than a "warning"-
        severity one, but identification/collinearity is never a
        validation-policy gate (nothing in core.validation_policy reads
        it), so it must never reach "fail" - that status is reserved for a
        domain whose evidence actually blocks approval (see
        test_fail_with_blocking_failures for the "Approval evidence"
        domain, which is a real gate). Using "fail" here would render with
        the same blocking-severity treatment as a genuine stop condition,
        which is the "do not upgrade a warning to an error simply because
        a number looks unusual" anti-pattern the UX guidance prohibits."""
        artefact = _artefact(
            identification=_section(
                "computed",
                payload={
                    "flags": [
                        {"level": "warning", "channel": "TV", "message": "mild"},
                        {"level": "error", "channel": "Radio", "message": "severe"},
                    ],
                    "correlation_matrix": {},
                    "condition_number": 150.0,
                },
            )
        )
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=artefact,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        ident = next(r for r in rows if r.domain == "Identification & collinearity")
        assert ident.status == "review"

    def test_review_when_only_warning_flags(self):
        artefact = _artefact(
            identification=_section(
                "computed",
                payload={
                    "flags": [{"level": "warning", "channel": "TV", "message": "mild"}],
                    "correlation_matrix": {},
                    "condition_number": 40.0,
                },
            )
        )
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=artefact,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        ident = next(r for r in rows if r.domain == "Identification & collinearity")
        assert ident.status == "review"


class TestCoverageCapabilityDomain:
    def test_pass_when_supported(self):
        cap = EngineCapabilityResult(
            engine="e", markets=("UK",), channels=("TV",), issues=()
        )
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=None,
            capability_result=cap,
            readiness=None,
            policy=None,
        )
        cov = next(r for r in rows if r.domain == "Coverage capability")
        assert cov.status == "pass"

    def test_review_not_fail_when_unsupported_and_no_gate(self):
        cap = EngineCapabilityResult(
            engine="e",
            markets=("UK",),
            channels=("TV",),
            issues=(
                MarketChannelCapabilityIssue(
                    market="UK", channel="TV", reason="no coverage"
                ),
            ),
        )
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=None,
            capability_result=cap,
            readiness=None,
            policy=None,
        )
        cov = next(r for r in rows if r.domain == "Coverage capability")
        assert cov.status == "review"


class TestPlausibilityDomain:
    def test_pass_with_no_flags(self):
        rows = compute_domain_health(
            scorecard={"plausibility_flags": []},
            diag_artefact=None,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        pl = next(r for r in rows if r.domain == "Plausibility")
        assert pl.status == "pass"

    def test_review_never_fail_with_flags(self):
        rows = compute_domain_health(
            scorecard={
                "plausibility_flags": [
                    {"level": "warning", "channel": "TV", "message": "high ROI"}
                ]
            },
            diag_artefact=None,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        pl = next(r for r in rows if r.domain == "Plausibility")
        assert pl.status == "review"


class TestApprovalEvidenceDomain:
    def test_not_computed_without_readiness(self):
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=None,
            capability_result=None,
            readiness=None,
            policy=None,
        )
        ae = next(r for r in rows if r.domain == "Approval evidence")
        assert ae.status == "not_computed"

    def test_pass_when_overall_ready(self):
        readiness = _readiness(ready=True)
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=None,
            capability_result=None,
            readiness=readiness,
            policy=None,
        )
        ae = next(r for r in rows if r.domain == "Approval evidence")
        assert ae.status == "pass"

    def test_fail_with_blocking_failures(self):
        gate = ValidationGate(name="g", description="d", evaluator_id="x")
        result = ValidationResult(gate_name="g", status="fail")
        readiness = _readiness(gate_results=[result], blocking=[result], ready=False)
        rows = compute_domain_health(
            scorecard=None,
            diag_artefact=None,
            capability_result=None,
            readiness=readiness,
            policy=_policy([gate]),
        )
        ae = next(r for r in rows if r.domain == "Approval evidence")
        assert ae.status == "fail"


class TestTopLineStatus:
    def test_not_started_before_anything_computed(self):
        top = compute_top_line_status(readiness=None, scorecard_computed=False)
        assert top.status_key == "not_started"
        assert top.issue_count == 0

    def test_evidence_computed_readiness_pending(self):
        top = compute_top_line_status(readiness=None, scorecard_computed=True)
        assert top.status_key == "current"

    def test_ready_reflects_readiness_overall_ready(self):
        readiness = _readiness(ready=True)
        top = compute_top_line_status(readiness=readiness, scorecard_computed=True)
        assert top.status_key == "ready"
        assert top.issue_count == 0

    def test_blocked_counts_blocking_and_missing(self):
        result = ValidationResult(gate_name="g", status="fail")
        readiness = _readiness(
            gate_results=[result],
            blocking=[result],
            missing=("other_gate",),
            ready=False,
        )
        top = compute_top_line_status(readiness=readiness, scorecard_computed=True)
        assert top.status_key == "blocked"
        assert top.issue_count == 2  # 1 blocking failure + 1 missing gate


class TestPrimaryConcern:
    def test_none_when_nothing_to_report(self):
        assert (
            derive_primary_concern(
                readiness=None,
                diag_artefact=None,
                scorecard=None,
                capability_result=None,
            )
            is None
        )

    def test_blocking_failure_takes_priority(self):
        result = ValidationResult(
            gate_name="g", status="fail", message="R-hat too high"
        )
        readiness = _readiness(gate_results=[result], blocking=[result], ready=False)
        artefact = _artefact(
            identification=_section(
                "computed",
                payload={
                    "flags": [
                        {"level": "error", "channel": "TV", "message": "collinear"}
                    ]
                },
            )
        )
        sentence = derive_primary_concern(
            readiness=readiness,
            diag_artefact=artefact,
            scorecard=None,
            capability_result=None,
        )
        assert sentence is not None
        assert "g" in sentence
        assert "R-hat too high" in sentence

    def test_falls_back_to_identification_error_flag(self):
        artefact = _artefact(
            identification=_section(
                "computed",
                payload={
                    "flags": [
                        {
                            "level": "error",
                            "channel": "Radio",
                            "message": "collinear with TV",
                        }
                    ]
                },
            )
        )
        sentence = derive_primary_concern(
            readiness=None,
            diag_artefact=artefact,
            scorecard=None,
            capability_result=None,
        )
        assert sentence is not None
        assert "Radio" in sentence
        assert "collinear with TV" in sentence

    def test_falls_back_to_non_convergence(self):
        scorecard = {
            "convergence": {
                "max_rhat": 1.8,
                "min_ess": 5,
                "divergences": 3,
                "converged": False,
            }
        }
        sentence = derive_primary_concern(
            readiness=None,
            diag_artefact=None,
            scorecard=scorecard,
            capability_result=None,
        )
        assert sentence is not None
        assert "convergence" in sentence.lower()

    def test_deterministic_same_inputs_same_output(self):
        scorecard = {
            "plausibility_flags": [
                {"level": "warning", "channel": "TV", "message": "high ROI"}
            ]
        }
        s1 = derive_primary_concern(
            readiness=None,
            diag_artefact=None,
            scorecard=scorecard,
            capability_result=None,
        )
        s2 = derive_primary_concern(
            readiness=None,
            diag_artefact=None,
            scorecard=scorecard,
            capability_result=None,
        )
        assert s1 == s2 is not None
