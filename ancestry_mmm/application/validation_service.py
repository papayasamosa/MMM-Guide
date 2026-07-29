"""
Validation service — orchestrates validation-policy evaluation for model
approval readiness.

PR 72B: ValidationService now consumes DiagnosticsArtefact for schema-v2
validation. Gate evaluator IDs are mapped to artefact section values via
the metric accessor. The service does not recalculate diagnostics when a
valid artefact is provided.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import arviz as az

from ancestry_mmm.core.validation_policy import (
    ApprovalReadiness,
    ThresholdPolicy,
    ValidationEvidenceContext,
    ValidationGate,
    ValidationResult,
    ValidationWaiverReference,
    evaluate_approval_readiness,
    evaluate_legacy_readiness,
    get_evaluator,
    readiness_to_dict,
    validate_gate_config,
    validate_policy_config,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.application.diagnostics_service import (
    DiagnosticsArtefact,
    DiagnosticSection,
)


@dataclass
class ValidationInput:
    """Input for validation readiness evaluation.

    PR 72B: Added ``diagnostics_artefact``. When a schema-v2 artefact is
    provided, gate metrics are read from it rather than recomputed from
    trace/frame/meta. The artefact's model identity must match the current
    model for official validation.
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
    model_type: Optional[str] = None
    market: Optional[str] = None
    intended_use: str = "model_approval"
    diagnostics_artefact: Optional[DiagnosticsArtefact] = None


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

    @staticmethod
    def _get_artefact_metric(
        evaluator_id: str, artefact: DiagnosticsArtefact
    ) -> Optional[float]:
        """Read a gate metric from the diagnostics artefact.

        Returns the numeric value or None if the section is not available
        or not in ``computed`` status. Unknown evaluator IDs return None
        (fail closed).
        """
        if artefact.schema_version < 2 or artefact.legacy_incomplete:
            return None
        section: Optional[DiagnosticSection] = None
        if evaluator_id == "convergence_rhat":
            section = artefact.convergence
            if section.status == "computed" and isinstance(section.payload, dict):
                return section.payload.get("max_rhat")
        elif evaluator_id == "convergence_ess":
            section = artefact.convergence
            if section.status == "computed" and isinstance(section.payload, dict):
                return section.payload.get("min_ess")
        elif evaluator_id == "divergences":
            section = artefact.convergence
            if section.status == "computed" and isinstance(section.payload, dict):
                has_div = section.payload.get("has_divergences", False)
                return 1.0 if has_div else 0.0
        elif evaluator_id == "ppc_coverage":
            section = artefact.posterior_predictive
            if section.status == "computed" and isinstance(section.payload, list):
                values = [
                    r.get("coverage_pct")
                    for r in section.payload
                    if r.get("coverage_pct") is not None
                ]
                if values:
                    return sum(values) / len(values)
            return None
        elif evaluator_id == "backtest_mape":
            section = artefact.backtest
            if section.status == "computed" and isinstance(section.payload, list):
                values = [
                    r.get("mape_pct")
                    for r in section.payload
                    if r.get("mape_pct") is not None
                ]
                if values:
                    return sum(values) / len(values)
            return None
        return None

    def evaluate_readiness(self, v_input: ValidationInput) -> ValidationServiceResult:
        """Evaluate model diagnostics against a validation policy.

        Produces identity-bound ``ValidationResult`` objects for each gate
        and aggregates them into an ``ApprovalReadiness`` using the current
        model identity for staleness checking.

        PR 62B:
        - Calls ``validate_policy_config()`` before any gate evaluation.
          When config errors exist, the readiness artefact is returned with
          ``config_errors`` set and ``overall_ready=False``.
        - Constructs a ``ValidationEvidenceContext`` for full evidence binding.

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

        # PR 65A: Official path requires explicit model type.
        # Narrow the Optional[str] to str after the guard for mypy.
        model_type: str
        if v_input.model_identity is not None:
            if v_input.model_type is None:
                errors.append(
                    "Official validation requires an explicit model_type "
                    "('shared' or 'market_specific')."
                )
                return ValidationServiceResult(errors=errors)
            model_type = v_input.model_type
        else:
            model_type = v_input.model_type or "shared"

        # --- PR 62B: Check policy config before any evaluation ---
        policy_config_errors = validate_policy_config(policy)
        if policy_config_errors:
            errors.extend(policy_config_errors)
            # We can still return a readiness with config errors if we have identity
            if v_input.model_identity is not None:
                try:
                    # Build minimal evidence context for config-errors path
                    _cfg_ctx = ValidationEvidenceContext(
                        model_identity=v_input.model_identity,
                        policy=policy,
                        diagnostic_artefact_id=v_input.diagnostic_artefact_id or "",
                        diagnostic_artefact_fingerprint=v_input.diagnostic_artefact_fingerprint
                        or "",
                        model_type=model_type,
                        market=v_input.market,
                        intended_use=v_input.intended_use,
                    )
                    readiness = evaluate_approval_readiness(
                        [],
                        policy,
                        v_input.model_identity,
                        diagnostic_artefact_id=v_input.diagnostic_artefact_id or "",
                        diagnostic_artefact_fingerprint=v_input.diagnostic_artefact_fingerprint
                        or "",
                        waivers=v_input.waivers,
                        as_of=v_input.as_of,
                        evidence_context=_cfg_ctx,
                    )
                    readiness_dict = readiness_to_dict(readiness)
                except Exception as exc:
                    errors.append(f"Readiness evaluation failed: {exc}")
                    readiness = None
                    readiness_dict = None
            else:
                readiness = None
                readiness_dict = None

            return ValidationServiceResult(
                readiness=readiness,
                readiness_dict=readiness_dict,
                results=results,
                errors=errors,
                warnings=warnings,
            )

        # --- PR 72B: Artefact-based validation (schema v2) ---
        artefact = v_input.diagnostics_artefact
        use_artefact = (
            artefact is not None
            and artefact.schema_version >= 2
            and not artefact.legacy_incomplete
        )
        if use_artefact:
            identity_fp = (
                v_input.model_identity.fingerprint() if v_input.model_identity else ""
            )
            if identity_fp and artefact.model_identity_fingerprint != identity_fp:
                errors.append(
                    "Diagnostics artefact model identity fingerprint does not "
                    "match the current model identity."
                )
                # Fall back to trace/frame/meta for safety
                use_artefact = False
            else:
                warnings.append(
                    "Using diagnostics artefact for gate evaluation (schema v2)."
                )
                v_input.diagnostic_artefact_fingerprint = artefact.fingerprint()
                v_input.diagnostic_artefact_id = artefact.artefact_id

        # --- Compute identity-dependent fingerprints once ---
        identity_fp = (
            v_input.model_identity.fingerprint() if v_input.model_identity else ""
        )
        diag_fp = v_input.diagnostic_artefact_fingerprint or ""

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
                        policy_fingerprint=policy.fingerprint(),
                        gate_fingerprint=gate.fingerprint(),
                        model_identity_fingerprint=identity_fp,
                        diagnostic_artefact_fingerprint=diag_fp,
                    )
                results.append(result)
            except Exception as exc:
                errors.append(f"Gate '{gate.name}' evaluation failed: {exc}")

        # --- Aggregate into readiness with current identity ---
        if v_input.model_identity is None:
            # PR 64A: No model identity — use legacy evaluator (schema v0, unverified)
            warnings.append(
                "No model identity provided. Using legacy readiness evaluator "
                "(schema v0, unverified, not usable for official approval)."
            )
            try:
                # Create a minimal identity for legacy evaluation
                from ancestry_mmm.core.model_identity import ModelIdentity as _MI

                _legacy_identity = _MI(
                    model_run_id="",
                    data_fingerprint="",
                    model_spec_fingerprint="",
                    posterior_fingerprint="",
                )
                readiness = evaluate_legacy_readiness(
                    results,
                    policy,
                    _legacy_identity,
                    diagnostic_artefact_id=v_input.diagnostic_artefact_id or "",
                    diagnostic_artefact_fingerprint=diag_fp,
                    waivers=v_input.waivers,
                    as_of=v_input.as_of,
                )
                readiness_dict = readiness_to_dict(readiness)
            except Exception as exc:
                errors.append(f"Legacy readiness evaluation failed: {exc}")
                readiness = None
                readiness_dict = None
        else:
            try:
                # PR 62B: Build evidence context for full binding
                evidence_ctx = ValidationEvidenceContext(
                    model_identity=v_input.model_identity,
                    policy=policy,
                    diagnostic_artefact_id=v_input.diagnostic_artefact_id or "",
                    diagnostic_artefact_fingerprint=diag_fp,
                    model_type=model_type,
                    market=v_input.market,
                    intended_use=v_input.intended_use,
                )
                readiness = evaluate_approval_readiness(
                    results,
                    policy,
                    v_input.model_identity,
                    diagnostic_artefact_id=v_input.diagnostic_artefact_id or "",
                    diagnostic_artefact_fingerprint=diag_fp,
                    waivers=v_input.waivers,
                    as_of=v_input.as_of,
                    evidence_context=evidence_ctx,
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

        PR 72B: When a schema-v2 diagnostics artefact is available and its
        model identity matches, the gate value is read from the artefact
        via ``_get_artefact_metric`` instead of recomputing from
        trace/frame/meta.
        """
        trace = v_input.trace
        frame = v_input.frame
        meta = v_input.meta

        # Resolve evaluator ID — fall back to gate name if not set
        evaluator_id = gate.evaluator_id or gate.name

        # Validate gate configuration first
        config_errors = validate_gate_config(gate)
        if config_errors:
            return ValidationResult(
                gate_name=gate.name,
                status="fail",
                message="; ".join(config_errors),
            )

        # PR 72B: Check artefact first (schema v2, non-legacy)
        artefact = v_input.diagnostics_artefact
        if (
            artefact is not None
            and artefact.schema_version >= 2
            and not artefact.legacy_incomplete
        ):
            metric_value = self._get_artefact_metric(evaluator_id, artefact)
            if metric_value is not None:
                # Value read from artefact — determine pass/fail by applying gate threshold
                threshold = gate.get_value()
                if threshold is not None:
                    gate_status = "pass" if metric_value <= threshold else "fail"
                else:
                    gate_status = "pass"
                return ValidationResult(
                    gate_name=gate.name,
                    status=gate_status,
                    value=metric_value,
                    message=f"Read from diagnostics artefact ({evaluator_id}={metric_value})",
                )
            # Metric not in artefact — fall through to evaluator registry

        # Look up evaluator in registry
        entry = get_evaluator(evaluator_id)
        if entry is None:
            return ValidationResult(
                gate_name=gate.name,
                status="fail",
                message=f"Unknown evaluator: {evaluator_id!r} — no evaluator registered",
            )

        meta_info, evaluator_fn = entry

        # Check required inputs
        for req in meta_info.required_inputs:
            if req == "trace" and trace is None:
                return ValidationResult(
                    gate_name=gate.name,
                    status="fail",
                    message=f"Evaluator '{evaluator_id}' requires trace but none provided.",
                )
            if req == "frame" and frame is None:
                return ValidationResult(
                    gate_name=gate.name,
                    status="fail",
                    message=f"Evaluator '{evaluator_id}' requires frame but none provided.",
                )
            if req == "meta" and meta is None:
                return ValidationResult(
                    gate_name=gate.name,
                    status="fail",
                    message=f"Evaluator '{evaluator_id}' requires meta but none provided.",
                )

        # Call the registered evaluator
        return evaluator_fn(
            gate,
            trace,
            frame,
            meta,
            v_input.credible_mass,
        )
