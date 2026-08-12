"""Official Curve Generation pre-flight readiness (Phase 6 of the Streamlit
UI/UX overhaul - see docs/decision_log.md; REQ-CURVE-001).

Pure, framework-independent derivation (no Streamlit import here, mirroring
``core.coverage_fabric``/``application.diagnostics_summary``/
``application.curve_annotations``'s "derive what to say, let the page draw
it" convention) of what would block ``CurveService.create_official_artifact``
before the analyst presses Generate, so a missing requirement is visible as
an explicit blocker up front rather than only as an ``st.error`` after the
click.

This module does not duplicate ``CurveService``'s own governance checks (the
generation-time validation - outcome approval, model approval, threshold
policy, readiness, diagnostics, activity/pathway governance - remains the
single source of truth and still runs unconditionally when Generate is
pressed, unchanged). It only restates, ahead of time, the page-local
completeness conditions ``13_Official_Curve_Generation.py`` already checks
right before calling the service (reference-context confirmation per
market, resolvable cost mapping/currency evidence for a monetary curve,
support-cell validity, a non-blank artifact ID) - the exact same conditions,
just surfaced earlier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Sequence


@dataclass(frozen=True)
class GenerationBlocker:
    """One reason official curve generation cannot proceed yet."""

    code: str
    message: str


def resolve_generation_blockers(
    *,
    eligible_outcomes_count: int,
    selected_markets: Sequence[str],
    curve_type: str,
    cost_mapping_registry_present: bool,
    currency_by_market: Mapping[str, str],
    reporting_currency: str,
    reference_context_confirmed: Mapping[str, bool],
    invalid_support_cells: Sequence[str],
    artifact_id: str,
) -> "List[GenerationBlocker]":
    """Every reason Generate would currently fail, in a fixed, deterministic
    order - never a single generic "cannot generate" message. Returns an
    empty list when nothing currently blocks generation (not proof that
    ``CurveService.create_official_artifact``'s own governance chain will
    also pass - that remains the authoritative, unconditional check)."""
    blockers: "List[GenerationBlocker]" = []

    if eligible_outcomes_count <= 0:
        blockers.append(
            GenerationBlocker(
                "no_eligible_outcome",
                "No outcome is currently approved for curve_publication.",
            )
        )

    if not selected_markets:
        blockers.append(GenerationBlocker("no_markets", "Select at least one market."))

    if curve_type == "monetary":
        if not cost_mapping_registry_present:
            blockers.append(
                GenerationBlocker(
                    "no_cost_mappings",
                    "Save at least one governed cost mapping before generating "
                    "a monetary curve.",
                )
            )
        missing_currency_markets = sorted(
            m for m in selected_markets if not currency_by_market.get(m)
        )
        if missing_currency_markets:
            blockers.append(
                GenerationBlocker(
                    "missing_local_currency",
                    "Local currency is missing for: "
                    f"{', '.join(missing_currency_markets)}.",
                )
            )
        if not reporting_currency:
            blockers.append(
                GenerationBlocker(
                    "missing_reporting_currency",
                    "Reporting currency is not set.",
                )
            )

    unconfirmed_markets = sorted(
        m for m in selected_markets if not reference_context_confirmed.get(m)
    )
    if unconfirmed_markets:
        blockers.append(
            GenerationBlocker(
                "reference_context_unconfirmed",
                "Reference context is not yet reviewed and confirmed for: "
                f"{', '.join(unconfirmed_markets)}.",
            )
        )

    if invalid_support_cells:
        blockers.append(
            GenerationBlocker(
                "invalid_support_cells",
                "Monetary support is out of the governed cost mapping's "
                f"domain for: {', '.join(sorted(invalid_support_cells))}.",
            )
        )

    if not artifact_id.strip():
        blockers.append(
            GenerationBlocker("blank_artifact_id", "Artifact ID must be non-blank.")
        )

    return blockers
