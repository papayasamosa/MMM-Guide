"""Coverage fabric: a time x variable x market visual-surface derivation
layered on top of an already-governed ``VariableCoverageMatrix``
(REQ-COVERAGE-001) for ``pages/15_Data_Coverage.py``'s fabric visualisation
(Phase 3 of the Streamlit UI/UX overhaul - see docs/decision_log.md).

Framework-independent (no Streamlit/Plotly import here - root AGENTS.md:
"Do not import Streamlit from ancestry_mmm/core"). The page/component layer
turns this module's plain dataclasses into the actual chart; this module
only derives what to draw and what to say about it.

Two guarantees this module exists to keep:

1. Every cell's ``state`` is exactly one of REQ-COVERAGE-001's eight
   canonical missingness states, or the explicit ``FABRIC_LABEL_COVERED``
   sentinel for a period with no recorded gap segment at all -
   ``FABRIC_LABEL_COVERED`` is deliberately *not* added to
   ``core.coverage.COVERAGE_STATES``; it is a presentation-only "no gap
   recorded here" label, never a ninth governance state.
2. Every sentence ``fabric_summary_sentences`` returns is mechanically
   counted from the actual ``VariableCoverageMatrix`` passed in - never
   speculative or templated prose describing something not directly
   computed from the data.

This module never alters governance state - it only reads an already-built,
already-reviewed ``VariableCoverageMatrix``. Selection/filtering built on
top of it (the page layer) must remain read-only for the same reason
(REQ-COVERAGE-001 S5: coverage/treatment approval stays the existing,
explicit, separately-gated control surface).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, List, Mapping, Optional, Sequence

from ancestry_mmm.core.coverage import VariableCoverageMatrix, VariableCoverageRecord

# Sentinel label for a period covered by no recorded gap segment at all -
# i.e. the variable's own governed frequency expected data there and the
# joined frame had a non-null value. Deliberately distinct from
# `core.coverage.COVERAGE_STATES` (never merged into that vocabulary): it
# describes "no gap was ever recorded here", not a REQ-COVERAGE-001
# missingness classification of an actual gap.
FABRIC_LABEL_COVERED = "covered"


@dataclass(frozen=True)
class FabricRowKey:
    """One row of the coverage fabric - a governed variable at
    market x product_or_none x segment_or_none grain, mirroring
    ``VariableCoverageRecord.variable_key``."""

    variable_id: str
    market: str
    product: Optional[str] = None
    segment: Optional[str] = None

    @property
    def row_label(self) -> str:
        parts = [self.variable_id, self.market]
        if self.product:
            parts.append(str(self.product))
        if self.segment:
            parts.append(str(self.segment))
        return " / ".join(parts)


@dataclass(frozen=True)
class FabricCell:
    """One chronologically-scoped cell of the fabric: a row, a period span,
    and its state (one of ``core.coverage.COVERAGE_STATES`` or
    ``FABRIC_LABEL_COVERED``). ``record`` is the full backing
    ``VariableCoverageRecord`` so a caller can render complete hover/
    inspector detail (native frequency, source/version, observed/expected
    window, treatment, official-use status) without a second lookup."""

    row: FabricRowKey
    period_start: str
    period_end: str
    state: str
    record: VariableCoverageRecord


def build_fabric_cells(matrix: VariableCoverageMatrix) -> List[FabricCell]:
    """Derive the full set of fabric cells for every record in ``matrix``.

    For each record, every recorded ``CoverageSegment`` becomes one cell at
    its own state. The complementary sub-ranges of
    ``[expected_start, expected_end]`` not covered by any recorded segment
    become ``FABRIC_LABEL_COVERED`` cells - never fabricated beyond the
    record's own governed expected window, and never emitted at all for a
    record with no expected window recorded (nothing to safely infer a
    "covered" span from).
    """
    cells: List[FabricCell] = []
    for record in matrix.records:
        row = FabricRowKey(
            record.variable_id, record.market, record.product, record.segment
        )
        ordered_segments = sorted(
            record.coverage_segments, key=lambda s: s.period_start
        )
        if not record.expected_start or not record.expected_end:
            for segment in ordered_segments:
                cells.append(
                    FabricCell(
                        row,
                        segment.period_start,
                        segment.period_end,
                        segment.state,
                        record,
                    )
                )
            continue

        cursor = date.fromisoformat(record.expected_start)
        window_end = date.fromisoformat(record.expected_end)
        for segment in ordered_segments:
            seg_start = date.fromisoformat(segment.period_start)
            seg_end = date.fromisoformat(segment.period_end)
            if seg_start > cursor:
                cells.append(
                    FabricCell(
                        row,
                        cursor.isoformat(),
                        (seg_start - timedelta(days=1)).isoformat(),
                        FABRIC_LABEL_COVERED,
                        record,
                    )
                )
            cells.append(
                FabricCell(
                    row, segment.period_start, segment.period_end, segment.state, record
                )
            )
            cursor = max(cursor, seg_end + timedelta(days=1))
        if cursor <= window_end:
            cells.append(
                FabricCell(
                    row,
                    cursor.isoformat(),
                    window_end.isoformat(),
                    FABRIC_LABEL_COVERED,
                    record,
                )
            )
    return cells


def filter_cells_by_states(
    cells: Sequence[FabricCell], states: Sequence[str]
) -> List[FabricCell]:
    """Read-only isolation of cells whose state is in ``states`` - used by
    the page's "isolate unresolved/unavailable/estimated/stale evidence"
    filter. Never mutates a cell or its backing record; an empty ``states``
    returns every cell unfiltered (no filter selected = show everything)."""
    if not states:
        return list(cells)
    allowed = set(states)
    return [c for c in cells if c.state in allowed]


def cells_matching_points(
    cells: Sequence[FabricCell], points: Sequence[Mapping[str, Any]]
) -> List[FabricCell]:
    """Resolve a Plotly ``on_select`` event's ``points`` (each a plain dict
    with at least ``y`` - the row label - and ``customdata``, whose index 4
    is the cell's own ``period_start`` per
    ``components.charts.create_coverage_fabric_chart``'s customdata order)
    back to the exact ``FabricCell`` each point represents.

    Read-only: this never mutates a cell or the governance state behind it
    (REQ-COVERAGE-001 S5 / this module's own docstring - selection must
    never itself alter governance state). A point with no matching cell is
    silently skipped rather than raising, since a stale selection from a
    since-rebuilt matrix should degrade to "nothing selected", not an error.
    """
    matches = []
    for point in points:
        row_label = point.get("y")
        customdata = point.get("customdata") or []
        period_start = customdata[4] if len(customdata) > 4 else None
        for cell in cells:
            if cell.row.row_label == row_label and cell.period_start == period_start:
                matches.append(cell)
                break
    return matches


def fabric_summary_sentences(matrix: VariableCoverageMatrix) -> List[str]:
    """Short, deterministic analytical summary sentences, each mechanically
    counted from ``matrix`` - never speculative or freehand text. Every
    sentence states only a fact directly derivable from the coverage
    records passed in (REQ-COVERAGE-001 S1/S2: state is metadata *about* the
    data, never inferred beyond what was actually recorded).

    Returns an empty list for an empty matrix - a caller should not render
    a summary panel in that case rather than showing a placeholder claim.
    """
    records = matrix.records
    if not records:
        return []

    sentences: List[str] = []

    total_by_market: "dict[str, int]" = defaultdict(int)
    full_window_by_market: "dict[str, int]" = defaultdict(int)
    blocking_by_market: "dict[str, int]" = defaultdict(int)
    late_start_by_market: "dict[str, int]" = defaultdict(int)

    for record in records:
        total_by_market[record.market] += 1
        if not record.coverage_segments:
            full_window_by_market[record.market] += 1
        if record.is_officially_unresolved:
            blocking_by_market[record.market] += 1
        if (
            record.observed_start
            and record.expected_start
            and record.observed_start > record.expected_start
        ):
            late_start_by_market[record.market] += 1

    for market in sorted(total_by_market):
        total = total_by_market[market]
        full = full_window_by_market[market]
        if full == total:
            sentences.append(
                f"{market}: all {total} governed variable record(s) cover the full "
                "expected window with no recorded gap."
            )
        elif full > 0:
            sentences.append(
                f"{market}: {full} of {total} governed variable record(s) cover the "
                "full expected window; the rest have at least one recorded gap."
            )
        else:
            sentences.append(
                f"{market}: none of {total} governed variable record(s) cover the "
                "full expected window - every one has at least one recorded gap."
            )

    for market in sorted(late_start_by_market):
        n = late_start_by_market[market]
        sentences.append(
            f"{market} has {n} variable(s) whose observed history starts later "
            "than the project's expected window."
        )

    for market in sorted(blocking_by_market):
        n = blocking_by_market[market]
        sentences.append(
            f"{market} has {n} of {total_by_market[market]} variable record(s) with "
            "unresolved coverage not yet approved for official use."
        )

    state_counts = Counter(
        segment.state for record in records for segment in record.coverage_segments
    )
    if state_counts:
        top_state, top_count = state_counts.most_common(1)[0]
        sentences.append(
            f"The most common recorded gap state across all variables is "
            f"'{top_state}' ({top_count} segment(s))."
        )

    return sentences
