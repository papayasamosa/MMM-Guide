"""
Project service — orchestrates project export, import, and resumability
checks without Streamlit dependencies.

PR 51B: Correctly calls ``export_project()`` with explicit artefact
parameters (not a ``project_state`` dict). Uses ``import_project()``
which returns a flat dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import arviz as az

from ancestry_mmm.core.hierarchical_model import FHModelMeta


@dataclass
class ProjectExportInput:
    """Typed input for project export.

    Matches the ``export_project()`` signature exactly.
    """

    output_path: str
    raw_sources: Dict[str, pd.DataFrame]
    transformed_data: Optional[pd.DataFrame]
    pipeline_steps: List[dict]
    model_spec: Optional[dict]
    prior_config: Optional[dict]
    dna_lag_weeks: int
    trace: Optional[az.InferenceData]
    scenarios: List[dict]
    curve_bank_source_dir: Optional[str] = None
    curve_artifact_store_source_dir: Optional[str] = None
    model_approval: Optional[dict] = None
    model_run_id: Optional[str] = None
    model_meta: Optional[FHModelMeta] = None
    market_spec_config: Optional[dict] = None
    model_type: Optional[str] = None
    outcome_definitions: Optional[List[dict]] = None
    funnel_links: Optional[List[dict]] = None
    media_outcome_pathways: Optional[List[dict]] = None
    net_billthrough_metadata: Optional[dict] = None
    workflow_state: Optional[dict] = None
    diagnostics: Optional[dict] = None
    notes: Optional[str] = None
    calibration_records: Optional[List[dict]] = None
    model_comparison_candidates: Optional[List[dict]] = None
    migration_review: Optional[dict] = None
    media_input_specs: Optional[List[dict]] = None
    media_cost_mappings: Optional[dict] = None
    media_input_support: Optional[List[dict]] = None
    monetary_spend_support: Optional[List[dict]] = None
    activity_definitions: Optional[List[dict]] = None
    outcome_approvals: Optional[List[dict]] = None
    validation_policy: Optional[dict] = None
    diagnostics_artefact: Optional[dict] = None
    validation_results: Optional[List[dict]] = None
    approval_readiness: Optional[dict] = None
    counterfactual_policy: Optional[dict] = None
    currency_context: Optional[dict] = None
    include_excel: bool = False
    excel_sheets: Optional[Dict[str, Optional[pd.DataFrame]]] = None
    excel_output_path: Optional[str] = None


@dataclass
class ProjectImportInput:
    """Typed input for project import."""

    bundle_path: str


@dataclass
class ProjectServiceResult:
    """Structured project operation result."""

    success: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    project_state: Optional[Dict[str, Any]] = None
    model_state: Optional[Dict[str, Any]] = None
    resumability: Optional[Dict[str, Any]] = None
    export_paths: Optional[List[str]] = None
    actual_export_path: Optional[str] = None


class ProjectService:
    """Application service for project persistence operations.

    Usage::

        service = ProjectService()
        result = service.export(input_data)
        if result.success:
            # bundle exported at result.actual_export_path
    """

    def export(self, exp_input: ProjectExportInput) -> ProjectServiceResult:
        """Export the current project to a bundle.

        Delegates to ``core.persistence.export_project`` with explicit
        artefact parameters. Optionally also exports an Excel summary.
        """
        errors: List[str] = []
        warnings: List[str] = []

        from ancestry_mmm.core.persistence import export_project, export_excel_summary

        try:
            output_path = Path(exp_input.output_path)
        except Exception as exc:
            errors.append(f"Invalid output path: {exc}")
            return ProjectServiceResult(success=False, errors=errors)

        # Resolve curve_bank_source_dir / curve_artifact_store_source_dir to
        # Path if provided
        cb_path = (
            Path(exp_input.curve_bank_source_dir)
            if exp_input.curve_bank_source_dir
            else None
        )
        curve_artifact_store_path = (
            Path(exp_input.curve_artifact_store_source_dir)
            if exp_input.curve_artifact_store_source_dir
            else None
        )

        try:
            actual_path = export_project(
                output_path,
                exp_input.raw_sources,
                exp_input.transformed_data,
                exp_input.pipeline_steps,
                exp_input.model_spec,
                exp_input.prior_config,
                exp_input.dna_lag_weeks,
                exp_input.trace,
                exp_input.scenarios,
                curve_bank_source_dir=cb_path,
                curve_artifact_store_source_dir=curve_artifact_store_path,
                model_approval=exp_input.model_approval,
                model_run_id=exp_input.model_run_id,
                model_meta=exp_input.model_meta,
                market_spec_config=exp_input.market_spec_config,
                model_type=exp_input.model_type,
                outcome_definitions=exp_input.outcome_definitions,
                funnel_links=exp_input.funnel_links,
                media_outcome_pathways=exp_input.media_outcome_pathways,
                net_billthrough_metadata=exp_input.net_billthrough_metadata,
                workflow_state=exp_input.workflow_state,
                diagnostics=exp_input.diagnostics,
                notes=exp_input.notes,
                calibration_records=exp_input.calibration_records,
                model_comparison_candidates=exp_input.model_comparison_candidates,
                migration_review=exp_input.migration_review,
                media_input_specs=exp_input.media_input_specs,
                media_cost_mappings=exp_input.media_cost_mappings,
                media_input_support=exp_input.media_input_support,
                monetary_spend_support=exp_input.monetary_spend_support,
                activity_definitions=exp_input.activity_definitions,
                outcome_approvals=exp_input.outcome_approvals,
                validation_policy=exp_input.validation_policy,
                diagnostics_artefact=exp_input.diagnostics_artefact,
                validation_results=exp_input.validation_results,
                approval_readiness=exp_input.approval_readiness,
                counterfactual_policy=exp_input.counterfactual_policy,
                currency_context=exp_input.currency_context,
            )
        except Exception as exc:
            errors.append(f"Project export failed: {exc}")
            return ProjectServiceResult(success=False, errors=errors)

        export_paths = [str(actual_path)]

        # Optional Excel export
        if (
            exp_input.include_excel
            and exp_input.excel_output_path
            and exp_input.excel_sheets
        ):
            try:
                excel_path = export_excel_summary(
                    Path(exp_input.excel_output_path),
                    exp_input.excel_sheets,
                )
                export_paths.append(str(excel_path))
            except Exception as exc:
                warnings.append(f"Excel export failed (non-fatal): {exc}")

        return ProjectServiceResult(
            success=True,
            errors=errors,
            warnings=warnings,
            export_paths=export_paths,
            actual_export_path=str(actual_path),
        )

    def import_bundle(self, imp_input: ProjectImportInput) -> ProjectServiceResult:
        """Import a project bundle.

        Delegates to ``core.persistence.import_project`` and
        ``reconstruct_model_state``.
        """
        errors: List[str] = []
        warnings: List[str] = []

        from ancestry_mmm.core.persistence import (
            import_project,
            reconstruct_model_state,
        )

        bundle_path = Path(imp_input.bundle_path)
        if not bundle_path.exists():
            errors.append(f"Bundle not found: {imp_input.bundle_path}")
            return ProjectServiceResult(success=False, errors=errors)

        try:
            project_state = import_project(bundle_path)
        except Exception as exc:
            errors.append(f"Project import failed: {exc}")
            return ProjectServiceResult(success=False, errors=errors)

        # Attempt model state reconstruction (non-fatal if fails)
        model_state = None
        try:
            model_state = reconstruct_model_state(project_state)
        except Exception as exc:
            warnings.append(f"Model state reconstruction failed: {exc}")

        return ProjectServiceResult(
            success=True,
            errors=errors,
            warnings=warnings,
            project_state=project_state,
            model_state=model_state,
        )

    def audit_resumability(self, project_state: Dict[str, Any]) -> ProjectServiceResult:
        """Audit whether a project is resumable for official use.

        Delegates to ``core.persistence.audit_project_resumability``.
        """
        errors: List[str] = []

        from ancestry_mmm.core.persistence import audit_project_resumability

        try:
            audit = audit_project_resumability(project_state)
        except Exception as exc:
            errors.append(f"Resumability audit failed: {exc}")
            return ProjectServiceResult(success=False, errors=errors)

        return ProjectServiceResult(
            success=True,
            errors=errors,
            resumability=audit,
        )


def verify_imported_readiness(
    imported: Dict[str, Any],
    reconstructed: Dict[str, Any],
) -> Tuple[Optional[dict], str]:
    """Decide whether an imported project's approval readiness evidence
    (``validation_policy`` + ``diagnostics_artefact`` + ``approval_readiness``)
    is still internally consistent, i.e. the readiness's own recorded
    fingerprints actually match the policy, diagnostics artefact, and model
    identity that were exported alongside it in the same bundle.

    Mirrors ``core.persistence.verify_imported_approval``'s never-trust-
    silently contract: always returns an explanatory message for the caller
    to show the user. Returns ``(None, reason)`` when the readiness must NOT
    be restored as current evidence; ``(readiness_dict, reason)`` when it is
    verified.

    Lives in the application layer (not ``core.persistence``) because
    ``DiagnosticsArtefact`` is an application-layer type
    (``application.diagnostics_service``) that ``core`` must not import.
    """
    from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact
    from ancestry_mmm.core.model_identity import ModelIdentity
    from ancestry_mmm.core.persistence import current_model_identity_fingerprints
    from ancestry_mmm.core.validation_policy import (
        ApprovalReadiness,
        ThresholdPolicy,
        readiness_matches_current_evidence,
    )

    readiness_dict = imported.get("approval_readiness")
    if readiness_dict is None:
        return (
            None,
            "No approval readiness evidence was included in this project bundle.",
        )

    policy_dict = imported.get("validation_policy")
    artefact_dict = imported.get("diagnostics_artefact")
    if policy_dict is None or artefact_dict is None:
        return None, (
            "The imported readiness evidence is missing its accompanying validation "
            "policy or diagnostics artefact - treated as unverified. Readiness must "
            "be re-evaluated."
        )

    frame = reconstructed.get("frame")
    posterior_params = reconstructed.get("posterior_params")
    current_run_id = imported.get("model_run_id")
    if frame is None or posterior_params is None or not current_run_id:
        return None, (
            "Could not reconstruct this project's model artefacts (data, "
            "specification, posterior, or run ID) well enough to verify its "
            "readiness evidence - treated as unverified. Readiness must be "
            "re-evaluated."
        )

    try:
        readiness = ApprovalReadiness.from_dict(readiness_dict)
        policy = ThresholdPolicy.from_dict(policy_dict)
        artefact = DiagnosticsArtefact.from_dict(artefact_dict)
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        return None, (
            "The imported readiness evidence, policy, or diagnostics artefact was "
            f"malformed and was discarded: {exc}"
        )

    data_fp, spec_fp, posterior_fp = current_model_identity_fingerprints(
        imported, reconstructed
    )
    model_identity_fingerprint = ModelIdentity(
        model_run_id=current_run_id,
        data_fingerprint=data_fp,
        model_spec_fingerprint=spec_fp,
        posterior_fingerprint=posterior_fp,
    ).fingerprint()

    if readiness_matches_current_evidence(
        readiness,
        policy_fingerprint=policy.fingerprint(),
        model_identity_fingerprint=model_identity_fingerprint,
        diagnostic_artefact_fingerprint=artefact.fingerprint(),
    ):
        return readiness_dict, (
            "Imported approval readiness verified: matches the imported policy, "
            "diagnostics artefact, and model artefacts."
        )

    return None, (
        "The imported approval readiness does not match the imported policy, "
        "diagnostics artefact, or model identity - it must be re-evaluated."
    )
