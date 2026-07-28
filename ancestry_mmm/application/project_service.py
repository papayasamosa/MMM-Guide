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
from typing import Any, Dict, List, Optional

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

        # Resolve curve_bank_source_dir to Path if provided
        cb_path = (
            Path(exp_input.curve_bank_source_dir)
            if exp_input.curve_bank_source_dir
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
