"""Diagnostics domain-health summary (Phase 5 of the Streamlit UI/UX
overhaul - see docs/decision_log.md; REQ-VAL-001).

Pure, framework-independent derivation (no Streamlit import here, mirroring
``core.coverage_fabric``'s "derive what to say, let the page draw it"
convention) of the material the redesigned Diagnostics page needs to answer
one question first: "Can this fitted model be trusted for the requested
use?" - before showing the full technical detail.

Everything here reads *already-computed* evidence (the scorecard dict, the
canonical ``DiagnosticsArtefact``, the engine-capability check, an evaluated
``ApprovalReadiness``) and reshapes it into a small, fixed set of domain
rows plus one top-line status. It never computes a new diagnostic, invents a
threshold, or decides approval itself - a domain's ``status`` is either read
directly from an already-evaluated policy gate result (matched to the
domain via the gate's own ``evaluator_id``, using exactly the evaluator IDs
registered in ``core.validation_policy``), or from a boolean/level already
computed by ``core.diagnostics``/``core.identification_diagnostics``/
``core.market_data_capability``. Where neither exists (e.g.
``residual_diagnostics``, which REQ-VAL-001 explicitly gives no blocking
threshold), the domain is reported as descriptive evidence only - never
given a fabricated pass/fail.

A domain row - or the whole rail - rendering "pass" is presentation of
already-computed evidence, never itself an approval: the top-line status
distinguishes "ready" (readiness evaluation says every gate passes) from
"approved_for_planning" (an actual, matching ``ModelApproval`` exists), and
the page must always read real approval state for the latter, never infer
it from a rendered chart or badge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ancestry_mmm.core.market_data_capability import EngineCapabilityResult
from ancestry_mmm.core.validation_policy import ApprovalReadiness, ThresholdPolicy

# ---------------------------------------------------------------------------
# Domain <-> evaluator_id mapping
# ---------------------------------------------------------------------------
#
# Exactly the evaluator IDs the app's evaluator registry
# (core.validation_policy) actually registers today: "rhat"/"convergence_rhat",
# "ess"/"min_ess"/"convergence_ess", "divergences" (convergence);
# "ppc"/"ppc_coverage", "backtest_mape" (predictive fit);
# "market_channel_capability" (coverage capability). A gate is matched to a
# domain by looking up its ``evaluator_id`` on the active policy - never by
# guessing from the gate's free-text ``name``, which a policy author can set
# to anything.

_CONVERGENCE_EVALUATOR_IDS = {
    "rhat",
    "convergence_rhat",
    "ess",
    "min_ess",
    "convergence_ess",
    "divergences",
}
_PREDICTIVE_FIT_EVALUATOR_IDS = {"ppc", "ppc_coverage", "backtest_mape"}
_CAPABILITY_EVALUATOR_IDS = {"market_channel_capability"}

_STATUS_RANK = {"fail": 3, "review": 2, "pass": 1}


@dataclass(frozen=True)
class DomainHealth:
    """One row of the domain-health rail: a fixed evidence domain the app
    already computes, its current status, and a one-line, deterministically
    derived detail. ``status`` is one of ``"pass"``, ``"review"``,
    ``"fail"`` (an evaluated gate or an existing boolean/level check),
    ``"reported"`` (evidence exists, no threshold applies to it),
    ``"not_computed"`` (evidence not yet computed this session), or
    ``"failed"`` (the computation itself errored, not an evidence
    judgement)."""

    domain: str
    status: str
    detail: str


@dataclass(frozen=True)
class TopLineReadiness:
    """The single top-of-page answer to "can this model be trusted for the
    requested use?", plus a count of outstanding issues. ``status_key`` is a
    key from ``ancestry_mmm.components.status.STATUS_BADGES``."""

    status_key: str
    headline: str
    issue_count: int
    detail: str


def _gate_results_for(
    readiness: Optional[ApprovalReadiness],
    policy: Optional[ThresholdPolicy],
    evaluator_ids: Iterable[str],
) -> list:
    if readiness is None or policy is None:
        return []
    matched = []
    for result in readiness.gate_results:
        gate = policy.get_gate(result.gate_name)
        if gate is not None and gate.evaluator_id in evaluator_ids:
            matched.append(result)
    return matched


def _worst_gate_status(results: Sequence) -> Optional[str]:
    statuses: List[str] = [r.status for r in results if r.status in _STATUS_RANK]
    if not statuses:
        return None
    return max(statuses, key=lambda s: _STATUS_RANK[s])


def _gate_detail(results: Sequence) -> str:
    if not results:
        return ""
    parts = [
        f"{r.gate_name}: {r.message}" if r.message else r.gate_name for r in results
    ]
    return "; ".join(parts)


def _convergence_domain(
    scorecard: Optional[Dict[str, Any]],
    readiness: Optional[ApprovalReadiness],
    policy: Optional[ThresholdPolicy],
) -> DomainHealth:
    matched = _gate_results_for(readiness, policy, _CONVERGENCE_EVALUATOR_IDS)
    worst = _worst_gate_status(matched)
    if worst is not None:
        return DomainHealth("Convergence", worst, _gate_detail(matched))
    conv = (scorecard or {}).get("convergence")
    if not conv:
        return DomainHealth(
            "Convergence", "not_computed", "Compute the scorecard to see convergence."
        )
    status = "pass" if conv.get("converged") else "fail"
    rhat = conv.get("max_rhat", conv.get("rhat_max"))
    ess = conv.get("min_ess", conv.get("ess_min"))
    div = conv.get("divergences")
    if rhat is not None and ess is not None and div is not None:
        detail = f"max R-hat {rhat:.3f}, min ESS {ess:,.0f}, {div} divergence(s)."
    else:
        detail = "Convergence computed."
    return DomainHealth("Convergence", status, detail)


def _predictive_fit_domain(
    scorecard: Optional[Dict[str, Any]],
    readiness: Optional[ApprovalReadiness],
    policy: Optional[ThresholdPolicy],
) -> DomainHealth:
    matched = _gate_results_for(readiness, policy, _PREDICTIVE_FIT_EVALUATOR_IDS)
    worst = _worst_gate_status(matched)
    if worst is not None:
        return DomainHealth("Predictive fit", worst, _gate_detail(matched))
    in_sample = (scorecard or {}).get("in_sample_fit") or []
    ppc = (scorecard or {}).get("ppc_coverage") or []
    if not in_sample and not ppc:
        return DomainHealth(
            "Predictive fit",
            "not_computed",
            "Compute the scorecard to see in-sample fit and posterior predictive coverage.",
        )
    r2_vals = [r["r_squared"] for r in in_sample if r.get("r_squared") is not None]
    cov_vals = [r["coverage_pct"] for r in ppc if r.get("coverage_pct") is not None]
    parts = []
    if r2_vals:
        parts.append(f"mean R² {sum(r2_vals) / len(r2_vals):.2f}")
    if cov_vals:
        parts.append(f"mean PPC coverage {sum(cov_vals) / len(cov_vals):.0f}%")
    detail = (
        (", ".join(parts) + " across outcome(s)")
        if parts
        else "In-sample fit and coverage computed"
    ) + " - no automatic gate configured for this evidence in the active policy."
    return DomainHealth("Predictive fit", "reported", detail)


def _residual_behaviour_domain(diag_artefact: Any) -> DomainHealth:
    section = getattr(diag_artefact, "residual_diagnostics", None)
    if section is None or section.status == "not_computed":
        return DomainHealth(
            "Residual behaviour",
            "not_computed",
            "Compute the scorecard to see residual autocorrelation and Durbin-Watson evidence.",
        )
    if section.status == "failed":
        return DomainHealth(
            "Residual behaviour",
            "failed",
            section.error or "Residual diagnostics failed.",
        )
    n = len(section.payload) if isinstance(section.payload, list) else None
    prefix = (
        f"Lag-1 autocorrelation and Durbin-Watson computed for {n} market x outcome cell(s)"
        if n
        else "Computed"
    )
    return DomainHealth(
        "Residual behaviour",
        "reported",
        f"{prefix} - descriptive evidence only, no blocking threshold (REQ-VAL-001).",
    )


def _identification_domain(diag_artefact: Any) -> DomainHealth:
    section = getattr(diag_artefact, "identification", None)
    if section is None or section.status == "not_computed":
        return DomainHealth(
            "Identification & collinearity",
            "not_computed",
            "Compute the scorecard to see multicollinearity and weak-identification evidence.",
        )
    if section.status == "failed":
        return DomainHealth(
            "Identification & collinearity",
            "failed",
            section.error or "Identification diagnostics failed.",
        )
    flags = (section.payload or {}).get("flags", [])
    if any(f.get("level") == "error" for f in flags):
        status = "fail"
    elif any(f.get("level") == "warning" for f in flags):
        status = "review"
    else:
        status = "pass"
    if flags:
        shown = "; ".join(
            f"{f.get('channel', '')}: {f.get('message', '')}" for f in flags[:2]
        )
        detail = f"{len(flags)} flag(s): {shown}" + (" ..." if len(flags) > 2 else "")
    else:
        detail = "No multicollinearity or weak-identification flags raised."
    return DomainHealth("Identification & collinearity", status, detail)


def _coverage_capability_domain(
    capability_result: Optional[EngineCapabilityResult],
    readiness: Optional[ApprovalReadiness],
    policy: Optional[ThresholdPolicy],
) -> DomainHealth:
    matched = _gate_results_for(readiness, policy, _CAPABILITY_EVALUATOR_IDS)
    worst = _worst_gate_status(matched)
    if worst is not None:
        return DomainHealth("Coverage capability", worst, _gate_detail(matched))
    if capability_result is None:
        return DomainHealth(
            "Coverage capability",
            "not_computed",
            "Not available yet - model specification not resolved.",
        )
    if capability_result.supported:
        return DomainHealth(
            "Coverage capability",
            "pass",
            f"Every requested market x channel cell has governed coverage for the "
            f"{capability_result.engine} engine.",
        )
    return DomainHealth(
        "Coverage capability",
        "review",
        f"{len(capability_result.issues)} market x channel cell(s) go beyond governed "
        "coverage - exploratory review remains available.",
    )


def _plausibility_domain(scorecard: Optional[Dict[str, Any]]) -> DomainHealth:
    if scorecard is None or "plausibility_flags" not in scorecard:
        return DomainHealth(
            "Plausibility",
            "not_computed",
            "Compute the scorecard to see curve and ROI plausibility flags.",
        )
    flags = scorecard["plausibility_flags"] or []
    if not flags:
        return DomainHealth("Plausibility", "pass", "No plausibility flags raised.")
    shown = "; ".join(
        f"{f.get('channel', '')}: {f.get('message', '')}" for f in flags[:2]
    )
    return DomainHealth(
        "Plausibility",
        "review",
        f"{len(flags)} flag(s): {shown}" + (" ..." if len(flags) > 2 else ""),
    )


def _approval_evidence_domain(readiness: Optional[ApprovalReadiness]) -> DomainHealth:
    if readiness is None:
        return DomainHealth(
            "Approval evidence",
            "not_computed",
            "Readiness has not been evaluated against a validation policy yet.",
        )
    if readiness.overall_ready:
        return DomainHealth(
            "Approval evidence",
            "pass",
            "All required gates pass under the active policy.",
        )
    n_blocking = len(readiness.blocking_failures) + len(
        readiness.missing_required_gates
    )
    if n_blocking:
        return DomainHealth(
            "Approval evidence",
            "fail",
            f"{n_blocking} blocking issue(s) under the active policy.",
        )
    if readiness.review_items:
        return DomainHealth(
            "Approval evidence",
            "review",
            f"{len(readiness.review_items)} review item(s) under the active policy.",
        )
    return DomainHealth(
        "Approval evidence", "fail", "Not ready under the active policy."
    )


def compute_domain_health(
    *,
    scorecard: Optional[Dict[str, Any]],
    diag_artefact: Any,
    capability_result: Optional[EngineCapabilityResult],
    readiness: Optional[ApprovalReadiness],
    policy: Optional[ThresholdPolicy],
) -> List[DomainHealth]:
    """The fixed, ordered set of evidence domains the app already computes
    for a fitted model. ``readiness`` must already be the *current* (not
    stale) evaluated readiness, or ``None`` - callers are responsible for
    that staleness check (mirrors the page's own pre-existing
    ``readiness_matches_current_evidence`` gate); this function does not
    re-derive staleness itself."""
    return [
        _convergence_domain(scorecard, readiness, policy),
        _predictive_fit_domain(scorecard, readiness, policy),
        _residual_behaviour_domain(diag_artefact),
        _identification_domain(diag_artefact),
        _coverage_capability_domain(capability_result, readiness, policy),
        _plausibility_domain(scorecard),
        _approval_evidence_domain(readiness),
    ]


def compute_top_line_status(
    *,
    readiness: Optional[ApprovalReadiness],
    scorecard_computed: bool,
) -> TopLineReadiness:
    """The single top-of-page answer, derived from the existing
    approval-readiness evaluation (REQ-VAL-001's ``evaluate_approval_
    readiness``/``ApprovalReadiness``) - never from whether a chart or
    domain-rail row happened to render. This deliberately stops short of
    "approved": a passing readiness means every configured gate passes, not
    that a reviewer has actually approved this model run - the real
    ``ModelApproval`` state (Model approval, below) is the only source of
    approval truth, per REQ-VAL-001 and root AGENTS.md's governance rules."""
    if readiness is not None:
        n_blocking = len(readiness.blocking_failures) + len(
            readiness.missing_required_gates
        )
        n_review = len(readiness.review_items)
        if readiness.overall_ready:
            detail = (
                f"{n_review} review item(s) outstanding - not yet approved."
                if n_review
                else "No outstanding issues under the active policy - not yet approved."
            )
            return TopLineReadiness("ready", "Ready for planning", n_review, detail)
        return TopLineReadiness(
            "blocked",
            "Not yet ready",
            n_blocking,
            f"{n_blocking} blocking issue(s), {n_review} review item(s) under the active policy.",
        )
    if scorecard_computed:
        return TopLineReadiness(
            "current",
            "Evidence computed - readiness not yet evaluated",
            0,
            "Evaluate readiness against a validation policy below.",
        )
    return TopLineReadiness(
        "not_started", "Not yet assessed", 0, "Compute the scorecard to begin."
    )


def derive_primary_concern(
    *,
    readiness: Optional[ApprovalReadiness],
    diag_artefact: Any,
    scorecard: Optional[Dict[str, Any]],
    capability_result: Optional[EngineCapabilityResult],
) -> Optional[str]:
    """The single most significant issue, as a plain-language sentence
    deterministically derived from already-computed evidence, in a fixed
    severity order (policy blocking failure > missing required gate >
    identification error flag > non-convergence > coverage-capability gap >
    identification warning flag > plausibility flag > policy review item).
    Returns ``None`` - never a fabricated sentence - once none of these
    apply, e.g. before anything has been computed."""
    if readiness is not None and readiness.blocking_failures:
        r = readiness.blocking_failures[0]
        return (
            f"Main concern: '{r.gate_name}' does not pass under the active policy"
            + (f" - {r.message}" if r.message else ".")
        )
    if readiness is not None and readiness.missing_required_gates:
        return (
            f"Main concern: required gate '{readiness.missing_required_gates[0]}' "
            "has no result yet under the active policy."
        )
    ident_section = getattr(diag_artefact, "identification", None)
    ident_flags = []
    if ident_section is not None and ident_section.status == "computed":
        ident_flags = (ident_section.payload or {}).get("flags", [])
    error_flags = [f for f in ident_flags if f.get("level") == "error"]
    if error_flags:
        f = error_flags[0]
        return f"Main concern: weak identification for {f.get('channel', '')} - {f.get('message', '')}"
    conv = (scorecard or {}).get("convergence")
    if conv and conv.get("converged") is False:
        rhat = conv.get("max_rhat", conv.get("rhat_max"))
        if rhat is not None:
            return (
                "Main concern: convergence diagnostics are outside typical thresholds "
                f"(max R-hat {rhat:.3f})."
            )
        return "Main concern: convergence diagnostics are outside typical thresholds."
    if capability_result is not None and not capability_result.supported:
        issue = capability_result.issues[0]
        return f"Main concern: {issue.market} / {issue.channel} - {issue.reason}"
    warning_flags = [f for f in ident_flags if f.get("level") == "warning"]
    if warning_flags:
        f = warning_flags[0]
        return f"Main concern: {f.get('channel', '')} - {f.get('message', '')}"
    plausibility_flags = (scorecard or {}).get("plausibility_flags") or []
    if plausibility_flags:
        f = plausibility_flags[0]
        return f"Main concern: {f.get('channel', '')} - {f.get('message', '')}"
    if readiness is not None and readiness.review_items:
        r = readiness.review_items[0]
        return f"Main concern: '{r.gate_name}' needs review" + (
            f" - {r.message}" if r.message else "."
        )
    return None
