"""
Project service — orchestrates project export, import, and resumability
checks without Streamlit dependencies.

PR 6: Separates project persistence orchestration from Streamlit page
rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ProjectExportInput:
    """Typed input for project export."""
    export_dir: str
    project_state: Dict[str, Any]
    include_excel: bool = False
    excel_path: Optional[str] = None
    model_type: str = "shared"


@dataclass
class ProjectImportInput:
    """Typed input for project import."""
    bundle_path: str
    password: Optional[str] = None


@dataclass
class ProjectServiceResult:
    """Structured project operation result."""
    success: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    project_state: Optional[Dict[str, Any]] = None
    resumability: Optional[Dict[str, Any]] = None
    export_paths: Optional[List[str]] = None


class ProjectService:
    """Application service for project persistence operations.

    Usage::

        service = ProjectService()
        result = service.export(input_data)
        if result.success:
            # bundle exported
    """

    def export(self, exp_input: ProjectExportInput) -> ProjectServiceResult:
        """Export the current project to a bundle.

        Delegates to ``core.persistence.export_project`` and optionally
        ``export_excel_summary``.

        Does not access Streamlit session state or render UI.
        """
        errors: List[str] = []
        warnings: List[str] = []

        from ancestry_mmm.core.persistence import export_project

        try:
            export_project(
                project_state=exp_input.project_state,
                export_dir=exp_input.export_dir,
                model_type=exp_input.model_type,
            )
        except Exception as exc:
            errors.append(f"Project export failed: {exc}")
            return ProjectServiceResult(success=False, errors=errors)

        export_paths = [str(Path(exp_input.export_dir) / "project_bundle.zip")]

        # Optional Excel export
        if exp_input.include_excel and exp_input.excel_path:
            try:
                from ancestry_mmm.core.persistence import export_excel_summary
                export_excel_summary(
                    project_state=exp_input.project_state,
                    output_path=exp_input.excel_path,
                )
                export_paths.append(exp_input.excel_path)
            except Exception as exc:
                warnings.append(f"Excel export failed (non-fatal): {exc}")

        return ProjectServiceResult(
            success=True,
            errors=errors,
            warnings=warnings,
            export_paths=export_paths,
            project_state=exp_input.project_state,
        )

    def import_bundle(self, imp_input: ProjectImportInput) -> ProjectServiceResult:
        """Import a project bundle.

        Delegates to ``core.persistence.import_project`` and
        ``reconstruct_model_state``.

        Does not access Streamlit session state or render UI.
        """
        errors: List[str] = []
        warnings: List[str] = []

        from ancestry_mmm.core.persistence import import_project, reconstruct_model_state

        bundle_path = Path(imp_input.bundle_path)
        if not bundle_path.exists():
            errors.append(f"Bundle not found: {imp_input.bundle_path}")
            return ProjectServiceResult(success=False, errors=errors)

        try:
            project_state = import_project(str(bundle_path))
        except Exception as exc:
            errors.append(f"Project import failed: {exc}")
            return ProjectServiceResult(success=False, errors=errors)

        # Attempt model state reconstruction (non-fatal if fails)
        model_state = None
        try:
            model_state = reconstruct_model_state(project_state)
        except Exception as exc:
            warnings.append(f"Model state reconstruction failed: {exc}")

        if model_state:
            project_state["model_state"] = model_state

        return ProjectServiceResult(
            success=True,
            errors=errors,
            warnings=warnings,
            project_state=project_state,
        )

    def audit_resumability(self, project_state: Dict[str, Any]) -> ProjectServiceResult:
        """Audit whether a project is resumable for official use.

        Delegates to ``core.persistence.audit_project_resumability``.

        Does not access Streamlit session state or render UI.
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
