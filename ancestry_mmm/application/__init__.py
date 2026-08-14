"""
Application-service layer (PR 6).

Makes Streamlit a client of the analytical platform rather than the platform
itself. Services own orchestration, identity resolution, validation, and
staleness checks — pages own presentation and input binding.

Services are callable from Streamlit, tests, and later API or notebook
workflows without importing ``streamlit``.
"""

from __future__ import annotations

from .uk_readiness import (
    DEFAULT_READINESS_OUTPUT_DIR,
    ReadinessInputError,
    ReadinessStage,
    UKReadinessReport,
    ensure_d_drive_path,
    run_uk_readiness,
)

__all__ = [
    "DEFAULT_READINESS_OUTPUT_DIR",
    "ReadinessInputError",
    "ReadinessStage",
    "UKReadinessReport",
    "ensure_d_drive_path",
    "run_uk_readiness",
]
