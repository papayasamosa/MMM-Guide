"""
Reproducible project report - Phase 4 of the market-specific redesign
(docs/project_objectives.md, docs/model_validation.md item 14).

Builds a single document - objective, data, model, diagnostics, curves,
scenarios, known limitations, and a pointer to the decision log - from the
*current project's actual state* (the same artefacts `core.persistence`
exports: spec, frame, scorecard, approval, curve bank entries, scenarios,
market_spec_config), not a static copy of the `docs/` files. Re-running this
against a later state of the same project produces an updated report, which
is the "reproducible" part.

Deliberately has no dependency on `ancestry_mmm.utils` (the Streamlit-facing
display/formatting layer) or `streamlit` itself, matching every other `core`
module - this can be called from a script or a test with no UI running.

Two renderers - `render_markdown` and `render_html` - both consume the same
`build_report_sections(...)` output, so the two formats can never drift out
of sync with each other (no separate HTML template to keep in step with a
Markdown one).
"""

from __future__ import annotations

import html as html_lib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .approval import ModelApproval
from .curve_bank import CurveBankEntry, entries_to_dataframe
from .market_config import MarketSpecConfig
from .optimization import compare_scenarios
from .outcomes import DNA, resolve_outcome_definitions, outcomes_to_dataframe
from .schema import ModelSpec

MODEL_TYPE_LABELS = {
    "shared": "Model A - one shared response curve per channel, across every market",
    "market_specific": "Model C - market-specific, partially pooled response curves",
}


@dataclass
class ReportSection:
    title: str
    paragraphs: List[str] = field(default_factory=list)
    bullets: List[str] = field(default_factory=list)
    table: Optional[pd.DataFrame] = None
    table_caption: Optional[str] = None


def _fmt_num(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def _objective_section(spec: Optional[ModelSpec], model_type: str) -> ReportSection:
    if spec is None:
        return ReportSection(
            title="Objective",
            paragraphs=["No model specification is available yet - this report was generated before Structure: Segments & Markets was completed."],
        )
    segments = list(spec.segment_outcomes.keys())
    return ReportSection(
        title="Objective",
        paragraphs=[
            "This project models Family History acquisition across three segments - "
            f"{', '.join(segments) or '(none defined)'} - to answer channel budget allocation "
            "questions within and, where a market-specific model is fit, across markets.",
            f"Markets in scope: {', '.join(spec.markets) or '(none)'}. "
            f"Model structure: {MODEL_TYPE_LABELS.get(model_type, model_type)}.",
        ],
    )


def _data_section(
    spec: Optional[ModelSpec], pipeline_steps: List[Dict], data_window: Optional[Tuple[str, str]],
) -> ReportSection:
    bullets = []
    if spec is not None:
        bullets.append(f"Channels ({len(spec.channels)}): {', '.join(spec.channels) or '(none)'}")
        if spec.dna_channels:
            bullets.append(f"DNA-targeted channels: {', '.join(spec.dna_channels)}")
        bullets.append(f"Transformation pipeline steps applied: {len(pipeline_steps)}")
    if data_window:
        bullets.append(f"Data window: {data_window[0]} to {data_window[1]}")
    return ReportSection(
        title="Data",
        paragraphs=["Summary of the data that produced this project's fitted model, if any."],
        bullets=bullets,
    )


def _model_section(spec: Optional[ModelSpec], model_type: str, dna_lag_weeks: Optional[int]) -> ReportSection:
    if spec is None:
        return ReportSection(title="Model", paragraphs=["No model has been configured yet."])
    bullets = [
        f"Structure: {MODEL_TYPE_LABELS.get(model_type, model_type)}",
        f"Segments: {', '.join(spec.segment_outcomes.keys()) or '(none)'}",
        f"Markets: {', '.join(spec.markets) or '(none)'}"
        + (f" (unpooled: {', '.join(spec.unpooled_markets)})" if spec.unpooled_markets else ""),
    ]
    if dna_lag_weeks is not None:
        bullets.append(f"DNA halo decision-time lag: {dna_lag_weeks} week(s)")
    return ReportSection(
        title="Model",
        paragraphs=["See docs/modelling_methodology.md for the full structural specification."],
        bullets=bullets,
    )


def _outcomes_section(spec: Optional[ModelSpec], outcome_definitions: Optional[List[dict]]) -> ReportSection:
    if spec is None:
        return ReportSection(title="Outcomes", paragraphs=["No model specification is available yet."])
    outcomes = resolve_outcome_definitions(outcome_definitions, spec.segment_outcomes, spec.segment_ltv)
    table = outcomes_to_dataframe(outcomes)
    n_dna = sum(1 for o in outcomes if o.product == DNA)
    paragraphs = [
        f"{len(outcomes)} outcome(s) catalogued: {len(outcomes) - n_dna} Family History, {n_dna} DNA.",
    ]
    if n_dna:
        paragraphs.append(
            "DNA outcomes are opt-in: `modelled_today = False` means this outcome type isn't fit "
            "automatically the way Family History segments are, not that it can never be - mapping "
            "it on Structure and re-preparing the modelling frame includes it, with DNA-targeted "
            "media getting full direct response rather than the shrunk halo pathway other segments "
            "get. See docs/dna_fh_causal_structure.md."
        )
    return ReportSection(
        title="Outcomes", paragraphs=paragraphs,
        table=table, table_caption="Outcome catalogue (modelled_today = fit automatically, with no extra configuration)",
    )


def _diagnostics_section(scorecard: Optional[Dict[str, Any]]) -> ReportSection:
    if not scorecard:
        return ReportSection(
            title="Diagnostics",
            paragraphs=["No scorecard has been computed yet - see Diagnostics to compute one before approving this model."],
        )
    conv = scorecard.get("convergence", {})
    paragraphs = [
        f"Max R-hat: {_fmt_num(conv.get('rhat_max'))} | Min ESS: {_fmt_num(conv.get('ess_min'))} | "
        f"Divergences: {_fmt_num(conv.get('divergences'))} | "
        f"Converged (thresholds): {'Yes' if conv.get('converged') else 'No'}",
    ]
    flags = scorecard.get("plausibility_flags") or []
    paragraphs.append(f"Curve/ROI plausibility flags raised: {len(flags)}.")
    table = pd.DataFrame(scorecard.get("in_sample_fit") or [])
    return ReportSection(
        title="Diagnostics", paragraphs=paragraphs,
        table=table if not table.empty else None, table_caption="In-sample fit by segment",
    )


def _approval_section(approval: Optional[ModelApproval]) -> ReportSection:
    if approval is None:
        return ReportSection(title="Approval", paragraphs=["This model has not been approved yet."])
    approved_at = time.strftime("%Y-%m-%d", time.localtime(approval.approved_at))
    return ReportSection(
        title="Approval",
        paragraphs=[f"Approved by **{approval.approved_by}** on {approved_at}."],
        bullets=[
            f"Diagnostics reviewed: {', '.join(approval.diagnostics_accepted) or '(none recorded)'}",
            f"Notes: {approval.notes or '(none)'}",
            f"Known limitations recorded at approval time: {approval.known_limitations or '(none)'}",
        ],
    )


def _curve_bank_section(entries: List[CurveBankEntry]) -> ReportSection:
    if not entries:
        return ReportSection(title="Curve bank", paragraphs=["No curves have been saved to the curve bank yet."])
    df = entries_to_dataframe(entries)
    summary = (
        df.groupby(["market", "curve_status"], dropna=False)
        .size().reset_index(name="curves")
        .sort_values(["market", "curve_status"])
    )
    return ReportSection(
        title="Curve bank",
        paragraphs=[f"{len(entries)} curve(s) saved across {df['market'].nunique()} market grouping(s)."],
        table=summary, table_caption="Curves saved by market and curve status",
    )


def _scenarios_section(scenarios: List[Dict]) -> ReportSection:
    if not scenarios:
        return ReportSection(title="Scenarios", paragraphs=["No scenarios have been saved yet."])
    table = compare_scenarios(scenarios)
    return ReportSection(
        title="Scenarios",
        paragraphs=[f"{len(scenarios)} scenario(s) saved."],
        table=table, table_caption="Saved scenario comparison",
    )


def _limitations_section(model_type: str, market_spec_config: Optional[MarketSpecConfig]) -> ReportSection:
    bullets = [
        "Partial pooling shares statistical strength across markets; it cannot manufacture variation "
        "that isn't in the data (docs/limitations.md).",
        "Simulation-based recovery testing validates that the model *can* recover known ground truth "
        "under the assumed hierarchical structure, not that the structure is correct for real "
        "Ancestry data - real-data model comparison remains required (docs/model_validation.md).",
    ]
    if model_type == "market_specific":
        bullets.append(
            "decay[channel] and hill_S[channel] are shared across markets in this model version - "
            "only saturation (K) and response strength (beta) are market-specific "
            "(docs/modelling_methodology.md)."
        )
        bullets.append(
            "Evidence-tier thresholds (core.evidence_tiers) are reasonable defaults, not yet "
            "validated against real Ancestry data (docs/decision_log.md)."
        )
    bullets.append(
        "Posterior uncertainty for curves and scenario outcomes (core.uncertainty) re-runs the "
        "same point-estimate calculation once per sampled posterior draw (a subsample, typically "
        "20-200 out of several thousand, for speed) rather than the full posterior - it is opt-in "
        "and shown alongside, not in place of, the point estimate."
    )
    if market_spec_config and market_spec_config.channel_media_units:
        bullets.append(
            "Media-unit response curves and cost-per-unit trends use one constant average "
            "historical cost per unit, not a spend-level-varying relationship "
            "(docs/media_units_and_inflation.md)."
        )
    return ReportSection(
        title="Known limitations & assumptions",
        paragraphs=["See docs/limitations.md for the full, current list. Highlights relevant to this project's configuration:"],
        bullets=bullets,
    )


def _decision_log_section() -> ReportSection:
    return ReportSection(
        title="Decision log & further reading",
        paragraphs=[
            "Every material modelling and scope decision behind this tool - what was decided, why, "
            "what alternatives were considered, and its current status - is recorded in "
            "docs/decision_log.md. See also docs/modelling_methodology.md, docs/market_hierarchy.md, "
            "docs/curve_bank.md, docs/media_units_and_inflation.md, and docs/scenario_planner.md for "
            "the design records behind each part of this report.",
        ],
    )


def build_report_sections(
    *,
    spec: Optional[ModelSpec],
    model_type: str = "shared",
    pipeline_steps: Optional[List[Dict]] = None,
    data_window: Optional[Tuple[str, str]] = None,
    dna_lag_weeks: Optional[int] = None,
    scorecard: Optional[Dict[str, Any]] = None,
    approval: Optional[ModelApproval] = None,
    curve_bank_entries: Optional[List[CurveBankEntry]] = None,
    scenarios: Optional[List[Dict]] = None,
    market_spec_config: Optional[MarketSpecConfig] = None,
    outcome_definitions: Optional[List[dict]] = None,
) -> List[ReportSection]:
    """Assemble every section of the report, in display order. Every input is
    optional and independently missing-safe - a report can be generated at
    any point in the workflow, not only once every step is complete; each
    section says plainly what hasn't happened yet rather than erroring."""
    pipeline_steps = pipeline_steps or []
    curve_bank_entries = curve_bank_entries or []
    scenarios = scenarios or []

    return [
        _objective_section(spec, model_type),
        _data_section(spec, pipeline_steps, data_window),
        _model_section(spec, model_type, dna_lag_weeks),
        _outcomes_section(spec, outcome_definitions),
        _diagnostics_section(scorecard),
        _approval_section(approval),
        _curve_bank_section(curve_bank_entries),
        _scenarios_section(scenarios),
        _limitations_section(model_type, market_spec_config),
        _decision_log_section(),
    ]


def _df_to_markdown_table(df: pd.DataFrame) -> str:
    headers = list(df.columns)
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.tolist()) + " |")
    return "\n".join(lines)


def render_markdown(project_name: str, sections: List[ReportSection], generated_at: Optional[float] = None) -> str:
    """Render `sections` as a single Markdown document."""
    generated_at = generated_at if generated_at is not None else time.time()
    lines = [
        f"# {project_name} - MMM Project Report",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M', time.localtime(generated_at))}.",
        "",
    ]
    for section in sections:
        lines.append(f"## {section.title}")
        lines.append("")
        for p in section.paragraphs:
            lines.append(p)
            lines.append("")
        if section.bullets:
            for b in section.bullets:
                lines.append(f"- {b}")
            lines.append("")
        if section.table is not None and not section.table.empty:
            if section.table_caption:
                lines.append(f"**{section.table_caption}**")
                lines.append("")
            lines.append(_df_to_markdown_table(section.table))
            lines.append("")
    return "\n".join(lines)


def render_html(project_name: str, sections: List[ReportSection], generated_at: Optional[float] = None) -> str:
    """Render `sections` as a single, self-contained HTML document (inline
    CSS, no external assets or network requests)."""
    generated_at = generated_at if generated_at is not None else time.time()
    e = html_lib.escape
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{e(project_name)} - MMM Project Report</title>",
        "<style>",
        "body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;margin:2rem auto;"
        "padding:0 1rem;color:#1a1a1a;line-height:1.5}",
        "h1{color:#1b5e3a}h2{color:#1b5e3a;border-bottom:1px solid #ddd;padding-bottom:.25rem;"
        "margin-top:2rem}",
        "table{border-collapse:collapse;width:100%;margin:1rem 0}",
        "th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.9rem}",
        "th{background:#f0f5f2}caption{text-align:left;font-weight:600;margin-bottom:.3rem}",
        ".generated{color:#666;font-size:.9rem}",
        "</style></head><body>",
        f"<h1>{e(project_name)} - MMM Project Report</h1>",
        f"<p class='generated'>Generated {e(time.strftime('%Y-%m-%d %H:%M', time.localtime(generated_at)))}.</p>",
    ]
    for section in sections:
        parts.append(f"<h2>{e(section.title)}</h2>")
        for p in section.paragraphs:
            parts.append(f"<p>{e(p)}</p>")
        if section.bullets:
            parts.append("<ul>")
            for b in section.bullets:
                parts.append(f"<li>{e(b)}</li>")
            parts.append("</ul>")
        if section.table is not None and not section.table.empty:
            if section.table_caption:
                parts.append(f"<p><strong>{e(section.table_caption)}</strong></p>")
            parts.append(section.table.to_html(index=False, border=0, escape=True))
    parts.append("</body></html>")
    return "\n".join(parts)
