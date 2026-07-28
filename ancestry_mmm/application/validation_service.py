"""
Validation service — orchestrates validation-policy evaluation for model
approval readiness.

PR 6: Separates validation orchestration from Streamlit page rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import arviz as az

from ancestry_mmm.core.validation_policy import (
    ApprovalReadiness,
    ThresholdPolicy,
    ValidationGate,
    ValidationResult,
    ValidationWaiverReference,
    evaluate_approval_readiness,
    readiness_to_dict,
)
from ancestry_mmm.core.diagnostics import (
    posterior_predictive_coverage,
)
from ancestry_mmm.core.model_identity import ModelIdentity


@dataclass
class ValidationInput:
    """Input for validation readiness evaluation.

    PR 53B: ``model_identity`` and ``policy`` are required for producing
    identity-bound validation results. Without them, results will have
    empty identity fields and be treated as stale by the readiness evaluator.
    """

    trace: Optional[az.InferenceData] = None
    frame: Optional[Dict[str, Any]] = None
    meta: Optional[Any] = None
    policy: Optional[ThresholdPolicy] = None
    model_identity: Optional["ModelIdentity"] = None  # noqa: F821
    waivers: Optional[List[ValidationWaiverReference]] = None
    as_of: Optional[datetime] = None
    credible_mass: float = 0.9
    diagnostic_artefact_id: Optional[str] = None
    diagnostic_artefact_fingerprint: Optional[str] = None


@dataclass
class ValidationServiceResult:
    """Structured validation output."""

    readiness: Optional[ApprovalReadiness] = None
    readiness_dict: Optional[Dict[str, Any]] = None
    results: List[ValidationResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class ValidationService:
    """Application service for model validation and approval readiness.

    Usage::

        service = ValidationService()
        result = service.evaluate_readiness(input_data)
        if result.errors:
            # handle errors
        if result.readiness and result.readiness.overall_ready:
            # approval ready
    """

    def __init__(self, default_policy: Optional[ThresholdPolicy] = None):
        self._default_policy = default_policy

    def evaluate_readiness(self, v_input: ValidationInput) -> ValidationServiceResult:
        """Evaluate model diagnostics against a validation policy.

        Produces identity-bound ``ValidationResult`` objects for each gate
        and aggregates them into an ``ApprovalReadiness`` using the current
        model identity for staleness checking.

        Does not mutate approvals, access Streamlit state, or render UI.
        """
        errors: List[str] = []
        warnings: List[str] = []
        results: List[ValidationResult] = []

        policy = v_input.policy or self._default_policy
        if policy is None:
            errors.append("No validation policy provided and no default configured.")
            return ValidationServiceResult(errors=errors)

        if v_input.trace is None:
            errors.append("No posterior trace provided for validation.")
            return ValidationServiceResult(errors=errors)

        # --- Evaluate each gate with identity binding ---
        for gate in policy.gates:
            try:
                result = self._evaluate_gate(gate, v_input)
                # Bind identity fields from the input
                if v_input.model_identity is not None:
                    result = ValidationResult(
                        gate_name=result.gate_name,
                        status=result.status,
                        value=result.value,
                        message=result.message,
                        artefact_id=v_input.diagnostic_artefact_id
                        or result.artefact_id,
                        evaluated_at=result.evaluated_at,
                        model_run_id=v_input.model_identity.model_run_id,
                        data_fingerprint=v_input.model_identity.data_fingerprint,
                        model_spec_fingerprint=v_input.model_identity.model_spec_fingerprint,
                        posterior_fingerprint=v_input.model_identity.posterior_fingerprint,
                        policy_id=policy.policy_id,
                        policy_version=policy.version,
                        gate_fingerprint=gate.fingerprint(),
                    )
                results.append(result)
            except Exception as exc:
                errors.append(f"Gate '{gate.name}' evaluation failed: {exc}")

        # --- Aggregate into readiness with current identity ---
        try:
            readiness = evaluate_approval_readiness(
                results,
                policy,
                current_model_identity=v_input.model_identity,
                waivers=v_input.waivers,
                as_of=v_input.as_of,
            )
            readiness_dict = readiness_to_dict(readiness)
        except Exception as exc:
            errors.append(f"Readiness evaluation failed: {exc}")
            readiness = None
            readiness_dict = None

        return ValidationServiceResult(
            readiness=readiness,
            readiness_dict=readiness_dict,
            results=results,
            errors=errors,
            warnings=warnings,
        )

    def _evaluate_gate(
        self,
        gate: ValidationGate,
        v_input: ValidationInput,
    ) -> ValidationResult:
        """Evaluate a single validation gate.

        PR 51C: No hard-coded thresholds. Every gate must have an
        ``evaluator_id`` and its thresholds come from the gate definition.
        Unknown evaluator IDs fail closed (status=fail, blocking).
        """
        trace = v_input.trace
        frame = v_input.frame
        meta = v_input.meta

        # Resolve evaluator ID — fall back to gate name if not set
        evaluator_id = gate.evaluator_id or gate.name

        if evaluator_id == "convergence_rhat" or evaluator_id == "rhat":
            rhat = az.rhat(trace, var_names=["mu", "beta", "hill_K", "alpha"])
            max_val = float("-inf")
            for var_data in rhat.values():
                if hasattr(var_data, "values"):
                    max_val = max(max_val, float(var_data.values.max()))
            status = self._classify_numeric_value(max_val, gate)
            return ValidationResult(
                gate_name=gate.name,
                status=status,
                value=max_val,
                message=f"Max R-hat = {max_val:.4f}",
            )

        elif evaluator_id in ("min_ess", "ess"):
            ess = az.ess(trace, var_names=["mu", "beta", "hill_K", "alpha"])
            min_val = float("inf")
            for var_data in ess.values():
                if hasattr(var_data, "values"):
                    min_val = min(min_val, float(var_data.values.min()))
            status = self._classify_numeric_value(min_val, gate)
            return ValidationResult(
                gate_name=gate.name,
                status=status,
                value=min_val,
                message=f"Min ESS = {min_val:.1f}",
            )

        elif evaluator_id == "divergences":
            has_div = False
            if hasattr(trace, "sample_stats") and "diverging" in trace.sample_stats:
                has_div = bool(trace.sample_stats["diverging"].values.any())
            status = "pass" if not has_div else "fail"
            return ValidationResult(
                gate_name=gate.name,
                status=status,
                value=float(has_div),
                message="No divergences" if not has_div else "Divergences detected",
            )

        elif evaluator_id in ("ppc_coverage", "ppc"):
            if frame is None or meta is None:
                return ValidationResult(
                    gate_name=gate.name,
                    status="fail",
                    message="Missing frame or meta for PPC evaluation",
                )
            ppc = posterior_predictive_coverage(
                trace,
                frame,
                meta,
                credible_mass=v_input.credible_mass,
                random_seed=42,
            )
            mean_cov = float(ppc["coverage_pct"].mean())
            status = self._classify_numeric_value(mean_cov, gate)
            return ValidationResult(
                gate_name=gate.name,
                status=status,
                value=mean_cov,
                message=f"Mean PPC coverage = {mean_cov:.1f}%",
            )

        else:
            # Unknown evaluator — fail closed
            return ValidationResult(
                gate_name=gate.name,
                status="fail",
                message=f"Unknown evaluator: {evaluator_id!r} — no evaluator registered",
            )

    @staticmethod
    def _classify_numeric_value(value: float, gate: ValidationGate) -> str:
        """Classify a numeric value against a gate's pass/review/fail bands.

        Returns ``"pass"``, ``"review"``, or ``"fail"``.
        """
        if gate.acceptable_range is None:
            # PR 53C: Missing thresholds on a numeric gate is a configuration
            # error, not a pass. The gate must define acceptable_range.
            return "fail"

        lo, hi = gate.acceptable_range

        # Validate threshold values are finite
        import math

        if not (math.isfinite(lo) and math.isfinite(hi)):
            return "fail"
        if lo > hi:
            return "fail"

        if gate.direction == "lower_is_better":
            if value <= hi:
                return "pass"
            if gate.review_range is not None:
                _rlo, rhi = gate.review_range
                if value <= rhi:
                    return "review"
            return "fail"
        else:  # higher_is_better
            if value >= lo:
                return "pass"
            if gate.review_range is not None:
                rlo, _rhi = gate.review_range
                if value >= rlo:
                    return "review"
            return "fail"
