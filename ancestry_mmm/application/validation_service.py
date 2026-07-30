"""
Validation service — orchestrates validation-policy evaluation for model
approval readiness.

PR 72B: ValidationService now consumes DiagnosticsArtefact for schema-v2
validation. Gate evaluator IDs are mapped to artefact section values via
the metric accessor. The service does not recalculate diagnostics when a
valid artefact is provided.

PR 82B: ``ValidationInput.evidence_mode`` makes that "does not recalculate"
guarantee explicit and total for official use. ``"official_canonical"``
never invokes a live evaluator - any gate whose metric is not present in
a valid artefact fails closed. ``"live_exploratory"`` (default) preserves
the artefact-first/live-fallback behaviour for exploratory review.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import arviz as az

from ancestry_mmm.core.validation_policy import (
    ARTEFACT_METRIC_ALIASES,
    ApprovalReadiness,
    ThresholdPolicy,
    ValidationEvidenceContext,
    ValidationGate,
    ValidationResult,
    ValidationWaiverReference,
    classify_boolean_gate,
    classify_numeric_gate,
    evaluate_approval_readiness,
    evaluate_legacy_readiness,
    get_evaluator,
    readiness_to_dict,
    validate_gate_config,
    validate_policy_config,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact


class MalformedArtefactEvidenceError(Exception):
    """A diagnostics-artefact section claims ``status="computed"`` but is
    missing a required key or holds a non-finite/wrong-typed value.

    This is a data-integrity problem, not "this metric isn't in the
    artefact" - callers must fail the gate closed rather than falling back
    to live recalculation, since a value of ``0.0`` (or any other silent
    default) could make corrupt evidence look like a passing metric.
    """


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
    # PR 82B: "official_canonical" (used for policy-backed model approval)
    # never reads a live evaluator - a gate whose metric is not present in
    # a valid, identity-matching artefact fails closed instead of silently
    # recomputing it live, so official evidence never mixes persisted and
    # recomputed values. "live_exploratory" (default) preserves the prior
    # behaviour: artefact-first, falling through to a live evaluator when
    # the artefact genuinely does not have the metric.
    evidence_mode: Literal["official_canonical", "live_exploratory"] = (
        "live_exploratory"
    )


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
    def _require_finite(value: Any, *, context: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MalformedArtefactEvidenceError(
                f"{context} is not a finite number: {value!r}"
            )
        numeric_value: float = float(value)
        if not math.isfinite(numeric_value):
            raise MalformedArtefactEvidenceError(
                f"{context} is non-finite: {numeric_value!r}"
            )
        return numeric_value

    @staticmethod
    def _get_artefact_metric(
        evaluator_id: str, artefact: DiagnosticsArtefact
    ) -> Optional[float]:
        """Read a gate metric from the diagnostics artefact.

        ``evaluator_id`` is normalised through ``ARTEFACT_METRIC_ALIASES``
        first, so any evaluator ID a policy uses (``rhat``, ``ess``,
        ``min_ess``, ``ppc``, ...) resolves to the same canonical artefact
        section a synonym would - a gate never silently falls back to live
        recomputation just because the policy used a different alias for
        the same metric.

        Returns the numeric value, or ``None`` if the section is genuinely
        not available (unknown evaluator ID, or section status is not
        ``"computed"`` - e.g. ``not_computed``/``failed``/``not_applicable``,
        which is a legitimate "not evaluated" state, not corruption).

        Raises ``MalformedArtefactEvidenceError`` if the section claims
        ``status="computed"`` but is missing the key this metric needs, or
        the value is not a finite number - never substitutes a default
        (e.g. ``0.0``) for missing/invalid evidence.
        """
        if artefact.schema_version < 2 or artefact.legacy_incomplete:
            return None
        canonical_id = ARTEFACT_METRIC_ALIASES.get(evaluator_id)
        if canonical_id is None:
            return None

        if canonical_id in ("convergence_rhat", "convergence_ess", "divergences"):
            section = artefact.convergence
            if section.status != "computed":
                return None
            if not isinstance(section.payload, dict):
                raise MalformedArtefactEvidenceError(
                    "Convergence section is 'computed' but its payload is not a dict."
                )
            if canonical_id == "convergence_rhat":
                if "max_rhat" not in section.payload:
                    raise MalformedArtefactEvidenceError(
                        "Convergence section is 'computed' but missing 'max_rhat'."
                    )
                return ValidationService._require_finite(
                    section.payload["max_rhat"], context="convergence.max_rhat"
                )
            if canonical_id == "convergence_ess":
                if "min_ess" not in section.payload:
                    raise MalformedArtefactEvidenceError(
                        "Convergence section is 'computed' but missing 'min_ess'."
                    )
                return ValidationService._require_finite(
                    section.payload["min_ess"], context="convergence.min_ess"
                )
            # canonical_id == "divergences"
            if "has_divergences" not in section.payload:
                raise MalformedArtefactEvidenceError(
                    "Convergence section is 'computed' but missing 'has_divergences'."
                )
            has_div = section.payload["has_divergences"]
            if not isinstance(has_div, bool):
                raise MalformedArtefactEvidenceError(
                    f"convergence.has_divergences is not a bool: {has_div!r}"
                )
            return 1.0 if has_div else 0.0

        if canonical_id == "ppc_coverage":
            section = artefact.posterior_predictive
            if section.status != "computed":
                return None
            if not isinstance(section.payload, list) or not section.payload:
                raise MalformedArtefactEvidenceError(
                    "PPC section is 'computed' but has no rows."
                )
            values = []
            for row in section.payload:
                if not isinstance(row, dict) or "coverage_pct" not in row:
                    raise MalformedArtefactEvidenceError(
                        "PPC row is 'computed' but missing 'coverage_pct'."
                    )
                values.append(
                    ValidationService._require_finite(
                        row["coverage_pct"], context="posterior_predictive.coverage_pct"
                    )
                )
            return sum(values) / len(values)

        if canonical_id == "backtest_mape":
            section = artefact.backtest
            if section.status != "computed":
                return None
            if not isinstance(section.payload, list) or not section.payload:
                raise MalformedArtefactEvidenceError(
                    "Backtest section is 'computed' but has no rows."
                )
            values = []
            for row in section.payload:
                if not isinstance(row, dict) or "mape_pct" not in row:
                    raise MalformedArtefactEvidenceError(
                        "Backtest row is 'computed' but missing 'mape_pct'."
                    )
                values.append(
                    ValidationService._require_finite(
                        row["mape_pct"], context="backtest.mape_pct"
                    )
                )
            return sum(values) / len(values)

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

        # PR 79A (WP6): no unconditional trace requirement here - a complete,
        # identity-matching schema-v2 artefact can satisfy every gate in a
        # policy without a trace at all. Each gate's own evaluator declares
        # which of trace/frame/meta it actually needs (_evaluate_gate below),
        # so a gate that cannot be resolved from the artefact and has no live
        # inputs available fails individually and closed, rather than the
        # whole request being rejected up front.

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
        # PR 79A (WP5): a genuine identity mismatch is not "fall back to
        # live evaluation" - it means the evidence on hand cannot be trusted
        # at all, so no gate is evaluated (live or from the artefact) and no
        # approval can result. This is distinct from "no artefact was
        # supplied", which still permits ordinary live evaluation.
        artefact_mismatch = False
        if use_artefact:
            # Narrow type for mypy
            assert artefact is not None
            identity_fp = (
                v_input.model_identity.fingerprint() if v_input.model_identity else ""
            )
            if identity_fp and artefact.model_identity_fingerprint != identity_fp:
                errors.append(
                    "Diagnostics artefact model identity fingerprint does not "
                    "match the current model identity. Evidence is stale: no "
                    "gate was evaluated (live or from the artefact) and no "
                    "approval can be created from this readiness result."
                )
                artefact_mismatch = True
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

        if artefact_mismatch and v_input.model_identity is not None:
            # Record which (rejected) artefact was mismatched, purely as an
            # audit identifier - not trusted as evidence, since every gate
            # result below is empty regardless of what the artefact claims.
            assert artefact is not None
            mismatched_artefact_id = artefact.artefact_id or "mismatched-artefact"
            mismatched_artefact_fp = artefact.fingerprint()
            try:
                evidence_ctx = ValidationEvidenceContext(
                    model_identity=v_input.model_identity,
                    policy=policy,
                    diagnostic_artefact_id=mismatched_artefact_id,
                    diagnostic_artefact_fingerprint=mismatched_artefact_fp,
                    model_type=model_type,
                    market=v_input.market,
                    intended_use=v_input.intended_use,
                )
                # Empty results: every applicable required gate is reported
                # as missing, so overall_ready is False without evaluating
                # (live or artefact-backed) a single gate.
                readiness = evaluate_approval_readiness(
                    [],
                    policy,
                    v_input.model_identity,
                    diagnostic_artefact_id=mismatched_artefact_id,
                    diagnostic_artefact_fingerprint=mismatched_artefact_fp,
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
                results=[],
                errors=errors,
                warnings=warnings,
            )

        # --- Evaluate each gate with identity binding ---
        # `use_artefact` was resolved above (identity match verified); a
        # mismatched or otherwise unusable artefact is passed as None here
        # so gate evaluation can never fall back to reading stale artefact
        # values on its own.
        usable_artefact = artefact if use_artefact else None
        for gate in policy.gates:
            try:
                result = self._evaluate_gate(gate, v_input, usable_artefact)
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
        usable_artefact: Optional[DiagnosticsArtefact],
    ) -> ValidationResult:
        """Evaluate a single validation gate.

        PR 72B: When a schema-v2 diagnostics artefact is available and its
        model identity matches, the gate value is read from the artefact
        via ``_get_artefact_metric`` instead of recomputing from
        trace/frame/meta.

        ``usable_artefact`` is the identity-verified artefact resolved by
        ``evaluate_readiness`` — it is ``None`` whenever the artefact is
        missing, legacy, or its model identity fingerprint does not match
        the current model, so this method never re-derives artefact
        usability from ``v_input.diagnostics_artefact`` on its own and can
        never silently fall back to a stale artefact.
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

        # Look up the evaluator once - its registered output_type ("numeric"
        # vs "boolean") is used to classify the value with the exact same
        # semantics whether the value came from the artefact or a live
        # recomputation, so the two paths can never classify differently.
        entry = get_evaluator(evaluator_id)
        output_type = entry[0].output_type if entry is not None else "numeric"

        # PR 82B: official canonical-evidence mode never touches the live
        # evaluator registry, in either direction - no usable artefact at
        # all, or a usable artefact that is missing this specific metric,
        # both fail the gate closed rather than mixing in a recomputed
        # value. This is a hard branch, not a fallthrough guard, so it can
        # never accidentally share code paths with the live/exploratory
        # branch below.
        if v_input.evidence_mode == "official_canonical":
            if usable_artefact is None:
                return ValidationResult(
                    gate_name=gate.name,
                    status="fail",
                    message=(
                        "Official canonical-evidence mode requires a valid, "
                        "identity-matching diagnostics artefact; none is "
                        "available for this gate."
                    ),
                )
            try:
                metric_value = self._get_artefact_metric(evaluator_id, usable_artefact)
            except MalformedArtefactEvidenceError as exc:
                return ValidationResult(
                    gate_name=gate.name,
                    status="fail",
                    message=(
                        f"Malformed diagnostics-artefact evidence for "
                        f"'{evaluator_id}': {exc}"
                    ),
                )
            if metric_value is None:
                return ValidationResult(
                    gate_name=gate.name,
                    status="fail",
                    message=(
                        f"Required evidence '{evaluator_id}' is not present "
                        "in the canonical diagnostics artefact. Official "
                        "canonical-evidence mode does not recompute missing "
                        "evidence live."
                    ),
                )
            gate_status = (
                classify_boolean_gate(bool(metric_value), gate)
                if output_type == "boolean"
                else classify_numeric_gate(metric_value, gate)
            )
            return ValidationResult(
                gate_name=gate.name,
                status=gate_status,
                value=metric_value,
                message=f"Read from diagnostics artefact ({evaluator_id}={metric_value})",
            )

        # --- live_exploratory (default): artefact-first, live fallback ---
        if usable_artefact is not None:
            try:
                metric_value = self._get_artefact_metric(evaluator_id, usable_artefact)
            except MalformedArtefactEvidenceError as exc:
                return ValidationResult(
                    gate_name=gate.name,
                    status="fail",
                    message=(
                        f"Malformed diagnostics-artefact evidence for "
                        f"'{evaluator_id}': {exc}"
                    ),
                )
            if metric_value is not None:
                gate_status = (
                    classify_boolean_gate(bool(metric_value), gate)
                    if output_type == "boolean"
                    else classify_numeric_gate(metric_value, gate)
                )
                return ValidationResult(
                    gate_name=gate.name,
                    status=gate_status,
                    value=metric_value,
                    message=f"Read from diagnostics artefact ({evaluator_id}={metric_value})",
                )
            # Metric not in artefact (genuinely not computed) — fall through
            # to the live evaluator registry.

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
