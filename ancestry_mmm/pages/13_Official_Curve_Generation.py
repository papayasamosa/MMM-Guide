"""Page 13: generate and persist a governed Planning Curve
(REQ-CURVE-001) - the CurveService.create_official_artifact application
boundary, driven from the UI for the first time. Supports both model-input
curves and monetary curves (governed cost mappings + currency/FX evidence).
"""

import hashlib
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Mapping, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    curve_artifact_store_dir,
    dataframe_column_config,
    readable_label,
    model_input_display_label,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_workspace_note,
    render_definition_help,
    render_decision_help,
    render_technical_details,
    SectionCard,
    BlockingPanel,
)
from ancestry_mmm.application.official_curve_readiness import (
    GenerationBlocker,
    resolve_generation_blockers,
)
from ancestry_mmm.core.activities import ActivityDefinition, activity_fit_fingerprint
from ancestry_mmm.core.search_objects import (
    SearchObjectDefinition,
    search_object_fit_fingerprint,
)
from ancestry_mmm.core.search_intent_taxonomy import (
    search_intent_taxonomy_fit_fingerprint,
)
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.canonical_curves import (
    CONTEXT_MODES,
    CurveReferenceContext,
    reference_context_from_model_frame,
    resolve_curve_axis_column,
    resolve_curve_axis_label,
    summarize_component_response_by_draw,
    support_from_model_frame,
)
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.causal_graph import current_structural_fingerprint_for_identity
from ancestry_mmm.core.media_costs import (
    MediaCostMapping,
    MediaInputSpec,
    MediaInputSupport,
    CostMappingRegistry,
    IdentitySpendMapping,
    FixedCostPerUnitMapping,
    PiecewiseLinearCostMapping,
    UploadedPlanCostMapping,
    SUPPORTED_METHODS,
    derive_monetary_support,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcome_approval import OutcomeApproval
from ancestry_mmm.core.outcomes import (
    outcome_catalogue_fingerprint_payload,
    resolve_outcome_definitions,
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.seo_visibility import seo_fit_inputs_fingerprint
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.search_capacity import SEARCH_CANDIDATE_A_ENGINE
from ancestry_mmm.core.validation_policy import (
    load_approval_readiness,
    load_threshold_policy,
)
from ancestry_mmm.application.curve_service import (
    CurveArtifactError,
    CurveGovernanceError,
    CurveService,
    OfficialCurveGovernance,
)
from ancestry_mmm.application.fx_service import (
    FXUploadValidationError,
    resolve_approved_fx_rate,
    validate_persisted_fx_rate_set,
)
from ancestry_mmm.components.charts import create_response_curve_with_band

_COST_MAPPING_TYPES = {
    "identity_spend": IdentitySpendMapping,
    "fixed_cost_per_unit": FixedCostPerUnitMapping,
    "piecewise_linear": PiecewiseLinearCostMapping,
    "uploaded_plan": UploadedPlanCostMapping,
}


def _outcome_display_label(outcome) -> str:
    label = f"{outcome.product} · {outcome.segment} · {outcome.metric}"
    if outcome.definition_version:
        label += f" (definition {outcome.definition_version})"
    return label


_CONTEXT_MODE_LABELS = {
    "recent_average": "Recent average",
    "period_average": "Selected period average",
    "specific_week": "Specific week",
    "specific_scenario": "Specific scenario",
    "steady_state_reference": "Steady-state reference",
}
_CURRENT_SPEND_METHOD_LABELS = {
    "latest_complete_week": "Latest complete week",
    "last_4_week_average": "Last 4-week average",
    "last_13_week_average": "Last 13-week average",
    "selected_period_average": "Selected period average",
}


def _planning_curve_reference(outcome, as_of: date) -> str:
    """Create a readable default reference without exposing a stable outcome ID."""
    parts = [outcome.product, outcome.segment, outcome.metric]
    if outcome.definition_version:
        parts.append(f"definition-{outcome.definition_version}")
    readable_parts = [
        str(part).strip().lower().replace(" ", "-")
        for part in parts
        if str(part).strip()
    ]
    return "-".join([*readable_parts, as_of.isoformat()])


def _humanise_reference_context_preview(
    context, outcome_display_labels, *, activity_definitions=None, market=None
):
    """Prepare a display-only context preview while preserving stored keys."""
    return {
        "trend": context.trend,
        "fourier": context.fourier,
        "promo": {
            outcome_display_labels.get(outcome_id, readable_label(outcome_id)): value
            for outcome_id, value in context.promo.items()
        },
        "controls": {
            readable_label(name): value for name, value in context.controls.items()
        },
        "outcome_controls": {
            outcome_display_labels.get(outcome_id, readable_label(outcome_id)): {
                readable_label(name): value for name, value in values.items()
            }
            for outcome_id, values in context.outcome_controls.items()
        },
        "other_channel_model_input": {
            model_input_display_label(
                channel, activity_definitions=activity_definitions, market=market
            ): value
            for channel, value in context.other_channel_media_input.items()
        },
        "reference_period_start": context.reference_period_start,
        "reference_period_end": context.reference_period_end,
    }


_COST_MAPPING_APPROVAL_STATUSES = [
    "draft",
    "approved",
    "rejected",
    "migration_required",
]
_COST_MAPPING_GRID_COLUMNS = [
    "mapping_id",
    "market",
    "channel",
    "cost_context_id",
    "currency",
    "method",
    "cost_per_media_input",
    "spend_knots",
    "media_input_knots",
    "allow_extrapolation",
    "plan_id",
    "source",
    "effective_period_start",
    "effective_period_end",
    "assumptions",
    "approval_status",
    "approved_by",
    "approved_at",
    "owner",
    "approval_note",
    "last_reviewed_at",
    "supersedes_mapping_id",
]
_COST_MAPPING_PRIMARY_COLUMNS = [
    "market",
    "channel",
    "method",
    "currency",
    "effective_period_start",
    "effective_period_end",
    "approval_status",
]
_COST_MAPPING_ADVANCED_COLUMNS = [
    column
    for column in _COST_MAPPING_GRID_COLUMNS
    if column not in _COST_MAPPING_PRIMARY_COLUMNS
]
_REQUESTED_USE_LABELS = {
    "curve_publication": "Planning Curve creation",
    "headline_reporting": "Headline reporting",
    "planning": "Planning",
    "optimisation": "Optimisation",
    "external_distribution": "External distribution",
}
_REQUESTED_USE_KEYS_BY_LABEL = {
    label: key for key, label in _REQUESTED_USE_LABELS.items()
}
_AUTHORIZATION_STATUS_LABELS = {
    "authorized": "Authorised",
    "not_authorized": "Not authorised",
    "eligible": "Eligible",
    "ineligible": "Not eligible",
}


def _permission_label(permission_key: str) -> str:
    """Return the analyst-facing label for a stored use/permission key."""
    return _REQUESTED_USE_LABELS.get(
        permission_key, permission_key.replace("_", " ").title()
    )


def _humanise_permission_text(message: str) -> str:
    """Keep stored permission keys out of routine Planning Curve messages."""
    humanised = str(message)
    for key, label in _REQUESTED_USE_LABELS.items():
        humanised = humanised.replace(key, label)
    return humanised


def _status_label(status: str) -> str:
    return _AUTHORIZATION_STATUS_LABELS.get(
        status, str(status).replace("_", " ").title()
    )


def _merge_cost_mapping_rows(
    original_rows: list[dict],
    primary_rows: list[dict],
    advanced_rows: Optional[list[dict]] = None,
) -> list[dict]:
    """Merge the compact and advanced editors without dropping stored fields.

    The primary editor is intentionally small for the normal path. Advanced
    fields remain editable in a secondary disclosure and are merged by row
    position, preserving the durable mapping schema on every save.
    """
    merged: list[dict] = []
    for index, primary in enumerate(primary_rows):
        row = dict(original_rows[index]) if index < len(original_rows) else {}
        row.update(
            {
                column: primary.get(column, "")
                for column in _COST_MAPPING_PRIMARY_COLUMNS
            }
        )
        if advanced_rows is not None and index < len(advanced_rows):
            row.update(
                {
                    column: advanced_rows[index].get(column, "")
                    for column in _COST_MAPPING_ADVANCED_COLUMNS
                }
            )
        if not str(row.get("mapping_id") or "").strip():
            row["mapping_id"] = (
                f"{row.get('market', 'market')}-{row.get('channel', 'channel')}"
                f"-cost-{index + 1}"
            )
        merged.append(row)
    return merged


def _context_confirmation_fingerprint(
    *,
    market: str,
    context: Optional[CurveReferenceContext],
    curve_type: str,
    mode: str,
    period_start: Optional[str],
    period_end: Optional[str],
    specific_week: Optional[str],
    model_identity: Optional[Mapping[str, str]],
) -> str:
    """Deterministic fingerprint of everything a reference-context
    confirmation actually depends on (Corrective PR E2.2).

    A plain module-level function (not a UI closure) so it is directly
    unit-testable. Covers the complete reference-context values, the
    fitted model identity, market, curve type, and the reference-context
    method plus its source-period inputs (period/week selection is not
    itself part of ``context.to_dict()`` once derivation has already
    happened, so it must be included explicitly). Changing any of these
    must invalidate a prior confirmation - the confirmation checkbox's
    own widget key embeds this fingerprint (Streamlit renders a fresh,
    unchecked widget under a new key rather than preserving a stale
    checked state), and generation additionally requires the persisted
    confirmed fingerprint to still equal this current one, so invalidation
    never depends solely on one Streamlit rerun clearing a checkbox.
    """
    payload = {
        "market": market,
        "curve_type": curve_type,
        "mode": mode,
        "period_start": period_start,
        "period_end": period_end,
        "specific_week": specific_week,
        "model_identity": dict(model_identity) if model_identity else None,
        "context": context.to_dict() if context is not None else None,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _knots_from_text(text: str) -> tuple:
    return tuple(float(v.strip()) for v in str(text).split(",") if v.strip())


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _cost_mapping_from_row(row: dict) -> MediaCostMapping:
    """Reconstruct one governed cost mapping from a cost-mapping grid row.

    A plain module-level function (not a UI closure) so the reconstruction
    logic - including the method dispatch and knot parsing - is directly
    unit-testable without driving ``st.data_editor``.
    """
    method = str(row.get("method") or "")
    if method not in _COST_MAPPING_TYPES:
        raise ValueError(f"Unsupported cost mapping method: {method!r}")
    common = dict(
        mapping_id=str(row["mapping_id"]),
        market=str(row["market"]),
        channel=str(row["channel"]),
        currency=str(row["currency"]).upper(),
        cost_context_id=str(row.get("cost_context_id") or "default"),
        source=str(row.get("source") or ""),
        effective_period_start=(str(row["effective_period_start"]) or None)
        if row.get("effective_period_start")
        else None,
        effective_period_end=(str(row["effective_period_end"]) or None)
        if row.get("effective_period_end")
        else None,
        assumptions=str(row.get("assumptions") or ""),
        approval_status=str(row.get("approval_status") or "draft"),
        approved_by=str(row["approved_by"]) or None if row.get("approved_by") else None,
        approved_at=str(row["approved_at"]) or None if row.get("approved_at") else None,
        owner=str(row["owner"]) or None if row.get("owner") else None,
        approval_note=str(row["approval_note"]) or None
        if row.get("approval_note")
        else None,
        last_reviewed_at=str(row["last_reviewed_at"]) or None
        if row.get("last_reviewed_at")
        else None,
        supersedes_mapping_id=str(row["supersedes_mapping_id"]) or None
        if row.get("supersedes_mapping_id")
        else None,
    )
    if method == "identity_spend":
        return IdentitySpendMapping(**common)
    if method == "fixed_cost_per_unit":
        return FixedCostPerUnitMapping(
            **common, cost_per_media_input=float(row["cost_per_media_input"])
        )
    allow_extrapolation = _as_bool(row.get("allow_extrapolation", False))
    if method == "piecewise_linear":
        return PiecewiseLinearCostMapping(
            **common,
            spend_knots=_knots_from_text(row.get("spend_knots", "")),
            media_input_knots=_knots_from_text(row.get("media_input_knots", "")),
            allow_extrapolation=allow_extrapolation,
        )
    return UploadedPlanCostMapping(
        **common,
        spend_knots=_knots_from_text(row.get("spend_knots", "")),
        media_input_knots=_knots_from_text(row.get("media_input_knots", "")),
        allow_extrapolation=allow_extrapolation,
        plan_id=str(row.get("plan_id") or ""),
    )


def _build_cost_mapping_registry(
    rows,
) -> "tuple[CostMappingRegistry, list[str]]":
    """Build a CostMappingRegistry from grid rows, accumulating row errors
    instead of raising - the caller decides whether to save or block on
    errors, mirroring pages/10_Channel_Media_Units.py's activity-grid
    pattern."""
    registry = CostMappingRegistry()
    errors: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        try:
            registry.add(_cost_mapping_from_row(row))
        except (ValueError, KeyError) as error:
            errors.append(f"Row {row_number}: {error}")
    return registry, errors


st.set_page_config(
    page_title="Planning Curves | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("official_curve_generation")
render_page_header(
    "official_curve_generation",
    task_prompt="Can this approved fit support a governed Planning Curve?",
)
render_workspace_note(
    "Create Planning Curves",
    "Create an evaluated Planning Curve only when fit identity, outcome approval, evidence, and cost mappings satisfy their gates.",
    kind="governed",
)
st.caption(
    "Create an evaluated Planning Curve from the approved fit. It is distinct "
    "from exploratory fitted-parameter snapshots in Results & Response Curves. "
    "Supports both model-input curves and "
    "monetary curves (an approved, effective cost mapping plus currency/FX "
    "evidence is required for the latter)."
)
render_definition_help(
    "observed support",
    "The range of model-input values represented in the source data for the selected market, channel, and reference context. A curve should not be treated as equally supported outside that range.",
)
render_decision_help(
    "How should I generate a Planning Curve?",
    controls="The approved outcome, market/reference context, observed support, curve representation, and any monetary cost translation used by the Planning Curve.",
    why="A Planning Curve is intended for governed planning use, so its outcome and conditions must be explicit and its support must be adequate.",
    options={
        "Model-input curve": "Use when the curve should remain in the fitted input units and no approved cost translation is required.",
        "Monetary curve": "Use only when every selected market/channel has an effective approved cost mapping and the currency/FX evidence is complete.",
        "Reference context": "Review and confirm the historical or explicitly hypothetical conditions that the curve represents.",
        "Downstream use": "Check whether the resulting Planning Curve is authorised for planning, reporting, optimisation, or external distribution.",
    },
    normal_path="Confirm model approval, choose the outcome, select markets, choose the representation, review support and context, resolve blockers, then save and review the Planning Curve.",
    downstream="The Planning Curve records its outcome definition, market context, support, evidence, cost mapping, and permission state; it is separate from exploratory curves in Results.",
    invalidates="A changed fit, outcome approval, context, support, cost mapping, or policy invalidates the affected Planning Curve or its use permission and requires a fresh generation/review.",
)
render_technical_details(
    details={
        "Planning Curve record": "The saved Planning Curve carries a durable record ID, model identity, outcome definition, reference context, support evidence, and governance dependencies.",
        "Generation boundary": "The UI delegates governed generation to the application curve-generation service; the technical entry point is available here for audit without being part of the routine workflow.",
        "Monetary restriction": "Currency/FX evidence and an effective approved cost mapping are required for monetary curves; model-input curves remain in their observed input units.",
    }
)

_dashboard_trained = all(
    get_state(key) is not None
    for key in ("trace", "frame", "model_meta", "posterior_params")
)
with st.container(border=True):
    st.markdown("### Planning Curves dashboard")
    _curve_status = st.columns(4)
    _curve_status[0].metric(
        "Fit state", "Trained" if _dashboard_trained else "Not ready"
    )
    _curve_status[1].metric(
        "Model type",
        "Market-specific" if get_state("model_type") == "market_specific" else "Shared",
    )
    _curve_status[2].metric(
        "Model approval", "Current" if get_state("model_approval") else "Needs review"
    )
    _curve_status[3].metric(
        "Planning Curve state",
        "Configure and review" if _dashboard_trained else "Blocked",
    )
    st.caption(
        "This page creates approved, evaluated Planning Curves. Readiness blockers are "
        "shown before saving; the saved curve carries its own outcome definition, "
        "reference context, support, evidence, and permission state."
    )

_CURVE_SERVICE = CurveService()

trace = get_state("trace")
frame = get_state("frame")
meta = get_state("model_meta")
params = get_state("posterior_params")
spec_dict = get_state("model_spec")
if (
    trace is None
    or frame is None
    or meta is None
    or params is None
    or spec_dict is None
):
    render_empty_state(
        "No fitted model yet. Complete Fit Model first.",
        button_label="Go to Fit Model",
        target_key="model_training",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
model_type = get_state("model_type", "shared")
model_run_id = get_state("model_run_id")
prior_config = get_state("prior_config") or {}
dna_lag_weeks = get_state("dna_lag_weeks", 4)
activity_definitions = [
    ActivityDefinition.from_dict(item)
    for item in (get_state("activity_definitions") or [])
]
search_objects = [
    SearchObjectDefinition.from_dict(item)
    for item in (get_state("search_objects") or [])
]
coverage_matrix_dict = get_state("variable_coverage_matrix")
approval_dict = get_state("model_approval")

current_identity = None
if model_run_id and spec_dict is not None:
    current_identity = {
        "model_run_id": model_run_id,
        "data_fingerprint": fingerprint_dataframe(frame["df"]),
        "model_spec_fingerprint": fingerprint_model_spec(
            spec_dict,
            prior_config,
            dna_lag_weeks,
            model_type=model_type,
            pipeline_steps=get_state("pipeline_steps") or [],
            market_spec_config=get_state("market_spec_config"),
            direct_dna_outcome_ids=meta.direct_dna_outcome_ids,
            outcome_catalogue=outcome_catalogue_fingerprint_payload(
                meta.outcome_catalogue_at_fit
            ),
            funnel_links=get_state("funnel_links"),
            media_outcome_pathways=pathway_catalogue_fingerprint_payload(
                meta.pathway_catalogue_at_fit
            ),
            activity_fit_fingerprint=(
                activity_fit_fingerprint(activity_definitions)
                if activity_definitions
                else None
            ),
            causal_graph_structural_fingerprint=current_structural_fingerprint_for_identity(
                fit_time_structural_fingerprint=(
                    getattr(meta, "causal_graph_structural_fingerprint", "") or ""
                )
                if meta is not None
                else "",
                live_graph_dict=get_state("causal_graph"),
            ),
            search_object_fit_fingerprint=(
                search_object_fit_fingerprint(
                    search_objects,
                    consumed_model_input_columns=spec_dict.get("channels") or [],
                )
                if search_objects
                else None
            ),
            search_intent_taxonomy_fit_fingerprint=search_intent_taxonomy_fit_fingerprint(
                activity_definitions,
                get_state("search_intent_groups") or [],
                get_state("search_intent_group_versions") or [],
                consumed_model_input_columns=spec_dict.get("channels") or [],
            ),
            variable_coverage_fingerprint=(
                VariableCoverageMatrix.from_dict(coverage_matrix_dict).fingerprint()
                if coverage_matrix_dict
                else None
            ),
            official_preparation_evidence=get_state("official_preparation_result"),
            seo_fit_fingerprint=seo_fit_inputs_fingerprint(
                get_state("seo_fit_inputs")
                or getattr(meta, "seo_fit_inputs_at_fit", None)
            ),
            calibration_fit_fingerprint=(
                getattr(meta, "calibration_fit_fingerprint", "") or None
            ),
        ),
        "posterior_fingerprint": fingerprint_posterior(params),
    }

current_policy, _policy_config_error = load_threshold_policy(
    get_state("validation_policy")
)
if _policy_config_error:
    st.warning(
        f"The configured validation policy is malformed and cannot be used: "
        f"{_policy_config_error}"
    )
current_readiness, _readiness_config_error = load_approval_readiness(
    get_state("approval_readiness")
)
if _readiness_config_error:
    st.warning(
        f"The stored approval readiness is malformed and cannot be used: "
        f"{_readiness_config_error}"
    )
current_diagnostics_artefact = get_state("diagnostics_artefact")

outcome_definitions = resolve_outcome_definitions(
    get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv
)
outcome_display_labels = {
    outcome.outcome_id: _outcome_display_label(outcome)
    for outcome in outcome_definitions
}
outcome_approvals = [
    OutcomeApproval.from_dict(d) for d in (get_state("outcome_approvals") or [])
]

if not current_identity or not approval_dict:
    st.markdown("---")
    render_empty_state(
        "No current model identity/approval available - approve this model "
        "on Model Diagnostics first.",
        button_label="Go to Model Diagnostics",
        target_key="diagnostics",
    )
    st.stop()

# ---------------------------------------------------------------------------
# Outcome and use selection
# ---------------------------------------------------------------------------
with SectionCard(
    "Outcome and use",
    description=(
        "Only outcomes with a current, approved outcome approval covering "
        "Planning Curve creation can be used here."
    ),
):
    eligible: list[tuple[OutcomeApproval, object]] = []
    for outcome_approval in outcome_approvals:
        if outcome_approval.status != "approved":
            continue
        if "curve_publication" not in outcome_approval.allowed_uses:
            continue
        outcome = next(
            (
                o
                for o in outcome_definitions
                if o.outcome_id == outcome_approval.outcome_id
            ),
            None,
        )
        if outcome is not None:
            eligible.append((outcome_approval, outcome))

    if not eligible:
        render_empty_state(
            "No outcome is currently approved for Planning Curve creation. Review "
            "outcome approvals on Structure -> Outcome Governance first.",
            button_label="Go to Model Structure",
            target_key="structure",
        )
        st.stop()

    outcome_ids = [outcome.outcome_id for _, outcome in eligible]
    selected_outcome_id = st.selectbox(
        "Outcome",
        outcome_ids,
        format_func=lambda outcome_id: outcome_display_labels.get(
            outcome_id, outcome_id
        ),
        key="ocg_outcome",
    )
    selected_outcome_approval, selected_outcome = next(
        (oa, o) for oa, o in eligible if o.outcome_id == selected_outcome_id
    )

    st.caption(
        f"Selected outcome: {_outcome_display_label(selected_outcome)}. "
        "Its approval and maturity rules travel with the saved Planning Curve."
    )
    st.caption(
        "The selector uses the approved business outcome label; the stored outcome "
        "identifier remains available in Technical details for audit."
    )
    requested_use_label = st.selectbox(
        "Use to check after saving",
        [
            _REQUESTED_USE_LABELS[key]
            for key in (
                "headline_reporting",
                "planning",
                "optimisation",
                "external_distribution",
            )
        ],
        key="ocg_requested_use",
    )
    requested_use = _REQUESTED_USE_KEYS_BY_LABEL[requested_use_label]

# ---------------------------------------------------------------------------
# 2. Markets to include
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### Markets in this Planning Curve")
selected_markets = st.multiselect(
    "Markets to include",
    meta.markets,
    default=meta.markets,
    key="ocg_markets",
)
if not selected_markets:
    st.info("Select at least one market to continue.")
    st.stop()
# Generation must only ever cover the markets the analyst actually selected
# (Corrective PR C4) - meta.markets governs both the completeness checks and
# the (market, channel) iteration inside generate_canonical_curve_draws, so
# passing the full fitted meta through would either require every
# deselected market's inputs too or silently generate for markets nobody
# asked for.
meta_selected = replace(meta, markets=selected_markets)

# Candidate A's final-outcome replay is now available to official curves, but
# its capacity input remains an explicit planning constraint.  Never reuse a
# historical cap or default a missing cap to zero: an omitted cap must block
# generation and explain the exact missing input.
candidate_a_curve_caps: dict[str, float] = {}
candidate_a_missing_curve_caps: list[str] = []
if meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE:
    with st.expander("Candidate A Search capacity for this curve", expanded=True):
        st.caption(
            "Enter one explicit future Paid Search delivery cap per selected "
            "market. This is a capacity constraint in capture units, never "
            "realised spend, demand, or an inferred historical value."
        )
        stored_curve_caps = dict(get_state("candidate_a_curve_cap_by_market") or {})
        for curve_market in selected_markets:
            supplied = st.checkbox(
                f"Supply a future Paid Search cap for {curve_market}",
                value=curve_market in stored_curve_caps,
                key=f"ocg_candidate_a_cap_supplied_{curve_market}",
            )
            if supplied:
                cap_value = st.number_input(
                    f"Future Paid Search delivery cap - {curve_market} "
                    "(capture units per week)",
                    min_value=0.0,
                    value=float(stored_curve_caps.get(curve_market, 0.0)),
                    step=1.0,
                    key=f"ocg_candidate_a_curve_cap_{curve_market}",
                )
                candidate_a_curve_caps[curve_market] = float(cap_value)
                stored_curve_caps[curve_market] = float(cap_value)
            else:
                stored_curve_caps.pop(curve_market, None)
                candidate_a_missing_curve_caps.append(curve_market)
        set_state("candidate_a_curve_cap_by_market", stored_curve_caps)

fourier_length = len(next(iter(params.gamma_fourier.values())))

# ---------------------------------------------------------------------------
# 2b. Curve type, and, if monetary, governed cost mappings and currency/FX
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### Planning Curve representation")
curve_type_label = st.radio(
    "How should the curve be expressed?",
    [
        "Model-input curve (no cost data)",
        "Monetary curve (requires an approved cost mapping)",
    ],
    key="ocg_curve_type",
)
curve_type = "monetary" if curve_type_label.startswith("Monetary") else "model_input"

cost_mapping_registry = None
currency_by_market: dict[str, str] = {}
reporting_currency = ""
currency_rates: dict[tuple[str, str], float] = {}
missing_fx_pairs: list[str] = []
fx_as_of_date_value = ""
fx_source_value = ""
cost_as_of_date_value = ""

_approved_fx_rate_set = None
_approved_fx_records = []
_stored_fx_rate_set = get_state("fx_rate_set")
_stored_fx_records = get_state("fx_rate_records") or []
if _stored_fx_rate_set is not None:
    try:
        _loaded_fx_rate_set, _loaded_fx_records = validate_persisted_fx_rate_set(
            _stored_fx_rate_set, _stored_fx_records
        )
    except (FXUploadValidationError, TypeError, ValueError) as exc:
        st.error(
            "The stored Finance FX rate set is invalid and cannot be used for "
            f"monetary curves: {exc}"
        )
    else:
        if _loaded_fx_rate_set.approval_status == "approved":
            _approved_fx_rate_set = _loaded_fx_rate_set
            _approved_fx_records = _loaded_fx_records

if curve_type == "monetary":
    st.caption(
        "Monetary curves require an approved, effective cost mapping for "
        "every (market, channel) plus explicit currency/FX evidence."
    )
    st.markdown("**Core cost-mapping details**")
    st.caption(
        "Review the market, activity, cost method, currency, effective dates, "
        "and approval state here. Technical IDs, knot arrays, and audit fields "
        "are available only when you need to inspect or amend them."
    )
    existing_registry = CostMappingRegistry.from_dict(get_state("media_cost_mappings"))
    existing_rows = existing_registry.to_dict()["mappings"]
    if existing_rows:
        grid_rows = [
            {col: row.get(col, "") for col in _COST_MAPPING_GRID_COLUMNS}
            for row in existing_rows
        ]
        for row, source_row in zip(grid_rows, existing_rows):
            for knot_col in ("spend_knots", "media_input_knots"):
                if source_row.get(knot_col):
                    row[knot_col] = ", ".join(str(v) for v in source_row[knot_col])
    else:
        grid_rows = [
            {
                **{col: "" for col in _COST_MAPPING_GRID_COLUMNS},
                "mapping_id": f"{market}-{channel}-cost",
                "market": market,
                "channel": channel,
                "cost_context_id": "default",
                "method": "identity_spend",
                "currency": "",
                "approval_status": "draft",
                "allow_extrapolation": False,
            }
            for market in selected_markets
            for channel in meta.channels
        ]
    primary_editor = st.data_editor(
        pd.DataFrame(grid_rows).reindex(columns=_COST_MAPPING_PRIMARY_COLUMNS),
        num_rows="dynamic",
        width="stretch",
        key="ocg_cost_mapping_primary_editor",
        column_config={
            "market": st.column_config.SelectboxColumn(
                "Market", options=selected_markets, required=True
            ),
            "channel": st.column_config.SelectboxColumn(
                "Activity / channel", options=meta.channels, required=True
            ),
            "method": st.column_config.SelectboxColumn(
                "Cost method", options=sorted(SUPPORTED_METHODS), required=True
            ),
            "currency": st.column_config.TextColumn("Currency (ISO)", required=True),
            "effective_period_start": st.column_config.TextColumn("Effective from"),
            "effective_period_end": st.column_config.TextColumn("Effective to"),
            "approval_status": st.column_config.SelectboxColumn(
                "Approval state", options=_COST_MAPPING_APPROVAL_STATUSES, required=True
            ),
        },
    )
    primary_rows = primary_editor.fillna("").to_dict("records")
    advanced_rows: Optional[list[dict]] = None
    with st.expander("Advanced cost-mapping details", expanded=False):
        st.caption(
            "Use these fields for mapping identity, piecewise knots, uploaded-plan "
            "metadata, extrapolation rules, and audit history. They remain part "
            "of the saved mapping even when this section stays closed."
        )
        advanced_editor = st.data_editor(
            pd.DataFrame(grid_rows).reindex(columns=_COST_MAPPING_ADVANCED_COLUMNS),
            num_rows="dynamic",
            width="stretch",
            key="ocg_cost_mapping_advanced_editor",
            column_config={
                "mapping_id": st.column_config.TextColumn(
                    "Technical mapping ID", required=True
                ),
                "cost_context_id": st.column_config.TextColumn("Cost context ID"),
                "allow_extrapolation": st.column_config.CheckboxColumn(
                    "Allow extrapolation", default=False
                ),
            },
        )
        advanced_rows = advanced_editor.fillna("").to_dict("records")
    cost_mapping_rows = _merge_cost_mapping_rows(grid_rows, primary_rows, advanced_rows)
    cost_registry_preview, cost_mapping_errors = _build_cost_mapping_registry(
        cost_mapping_rows
    )
    for error in cost_mapping_errors:
        st.error(error)
    if st.button("Save cost mappings"):
        if cost_mapping_errors:
            st.error("Nothing was saved. Resolve every row error first.")
        else:
            set_state("media_cost_mappings", cost_registry_preview.to_dict())
            st.success(
                f"Saved {len(cost_registry_preview.to_dict()['mappings'])} cost "
                "mapping(s) for future monetary Planning Curves."
            )
    cost_mapping_registry = CostMappingRegistry.from_dict(
        get_state("media_cost_mappings")
    )
    cost_as_of_date_value = str(
        st.date_input(
            "Cost mapping as-of date",
            value=date.today(),
            key="ocg_cost_as_of_date",
            help=(
                "Resolves which effective cost mapping applies for every "
                "(market, channel) - distinct from the FX as-of date below. "
                "Required whenever more than one effective mapping could "
                "otherwise exist for the same cell."
            ),
        )
    )

    st.markdown("**Currency & FX**")
    if _stored_fx_rate_set is None:
        st.info(
            "No governed Finance FX rate set is loaded. Same-currency identity "
            "conversion remains available; cross-currency curves require an "
            "explicit rate and source below, and no rate is prefilled."
        )
    elif _approved_fx_rate_set is not None:
        st.success(
            "Approved Finance FX rate set available: "
            f"{_approved_fx_rate_set.rate_set_id} v{_approved_fx_rate_set.rate_set_version}. "
            "Applicable rates will be resolved automatically for the selected "
            "FX as-of date."
        )
    else:
        st.warning(
            "The loaded Finance FX rate set is not approved. It is retained in "
            "the project, but cannot supply official monetary-curve FX evidence."
        )
    for market in selected_markets:
        currency_by_market[market] = st.text_input(
            f"Local currency - {market} (ISO code)",
            value="",
            key=f"ocg_local_currency_{market}",
        )
    c1, c2, c3 = st.columns(3)
    reporting_currency = c1.text_input(
        "Reporting currency (ISO code)", value="", key="ocg_reporting_currency"
    )
    fx_as_of_date_value = str(
        c2.date_input("FX as-of date", value=date.today(), key="ocg_fx_as_of_date")
    )
    fx_source_value = c3.text_input("FX source", value="", key="ocg_fx_source")
    if _approved_fx_rate_set is not None and not fx_source_value:
        fx_source_value = (
            f"{_approved_fx_rate_set.provider}/"
            f"{_approved_fx_rate_set.rate_set_id}/v"
            f"{_approved_fx_rate_set.rate_set_version}"
        )
    distinct_pairs = sorted(
        {
            (cur, reporting_currency or cur)
            for cur in currency_by_market.values()
            if cur and cur != (reporting_currency or cur)
        }
    )
    for local_currency, target_currency in distinct_pairs:
        resolved_rate = None
        if _approved_fx_rate_set is not None:
            try:
                resolved_rate = resolve_approved_fx_rate(
                    _approved_fx_rate_set,
                    _approved_fx_records,
                    source_currency=local_currency,
                    target_currency=target_currency,
                    as_of_date=fx_as_of_date_value,
                )
            except FXUploadValidationError as exc:
                st.error(f"Cannot use the approved Finance FX set: {exc}")
        if resolved_rate is not None:
            currency_rates[(local_currency, target_currency)] = float(resolved_rate)
            st.caption(
                f"Using approved rate 1 {local_currency} -> {target_currency}: "
                f"{resolved_rate}"
            )
        else:
            if _approved_fx_rate_set is not None:
                st.error(
                    f"The approved Finance FX set has no applicable "
                    f"{local_currency}->{target_currency} rate on or before "
                    f"{fx_as_of_date_value}."
                )
            rate = st.number_input(
                f"Explicit FX rate: 1 {local_currency} -> {target_currency} "
                "(no default)",
                value=0.0,
                min_value=0.0,
                key=f"ocg_fx_rate_{local_currency}",
            )
            if rate > 0:
                currency_rates[(local_currency, target_currency)] = rate
            else:
                missing_fx_pairs.append(f"{local_currency}->{target_currency}")

# ---------------------------------------------------------------------------
# 3. Reference context per market
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### Reference context")
st.caption(
    "Every reference-context method except Specific scenario is derived directly from the "
    "prepared model frame's actual history for that market - never an "
    "implicit zero or unstated default. Specific scenario "
    "remains fully explicit by design. Either way, an analyst must review "
    "and explicitly confirm each market's context below before it can be "
    "used to generate - an unreviewed context, derived or not, can never be "
    "silently accepted."
)
reference_contexts: dict[str, CurveReferenceContext] = {}
reference_context_confirmed: dict[str, bool] = {}
confirmed_context_fingerprints: dict[str, str] = {}
for market in selected_markets:
    with st.expander(f"Reference context - {market}", expanded=False):
        mode = st.selectbox(
            "Reference context method",
            sorted(CONTEXT_MODES),
            format_func=lambda value: _CONTEXT_MODE_LABELS.get(
                value, readable_label(value)
            ),
            key=f"ocg_mode_{market}",
        )
        reference_context_id = st.text_input(
            "Reference context name",
            value=f"{market}-{_CONTEXT_MODE_LABELS.get(mode, readable_label(mode))}",
            key=f"ocg_ctx_id_{market}",
        )
        counterfactual_value = st.number_input(
            "Counterfactual value", value=0.0, key=f"ocg_cf_value_{market}"
        )

        context: Optional[CurveReferenceContext] = None
        # Corrective PR E2.2: always fresh per market/iteration - the
        # `else` branch below only reassigns these when mode is not
        # "specific_scenario", so without resetting them here the
        # confirmation fingerprint could otherwise pick up a stale value
        # left over from a previous market's iteration of this loop.
        period_start = period_end = specific_week = None
        if mode == "specific_scenario":
            st.caption(
                "Explicit hypothetical scenario - every value below is "
                "entered directly; nothing is derived from the model frame."
            )
            trend = st.number_input("Trend", value=0.0, key=f"ocg_trend_{market}")
            st.markdown("**Fourier terms** (must match the fitted dimension)")
            fourier_cols = st.columns(max(fourier_length, 1))
            fourier = tuple(
                fourier_cols[i].number_input(
                    f"Fourier[{i}]", value=0.0, key=f"ocg_fourier_{market}_{i}"
                )
                for i in range(fourier_length)
            )
            st.markdown("**Promotion reference value per outcome**")
            promo = {
                outcome_id: st.number_input(
                    outcome_display_labels.get(outcome_id, readable_label(outcome_id)),
                    value=0.0,
                    key=f"ocg_promo_{market}_{outcome_id}",
                )
                for outcome_id in meta.outcome_ids
            }
            st.markdown("**Common controls**")
            controls = {
                name: st.number_input(
                    readable_label(name),
                    value=0.0,
                    key=f"ocg_control_{market}_{name}",
                )
                for name in params.control_coef
            }
            st.markdown("**Outcome-specific controls**")
            # Only outcomes that actually appear in params.outcome_control_coef
            # may appear here at all - validate_reference_context_completeness
            # treats any other outcome key as an unknown extra (core/
            # canonical_curves.py's exact-key-set-coverage rule), even an
            # outcome that is otherwise perfectly valid for every other field.
            outcome_controls = {}
            for outcome_id, fitted_names in params.outcome_control_coef.items():
                if not fitted_names:
                    outcome_controls[outcome_id] = {}
                    continue
                outcome_controls[outcome_id] = {
                    name: st.number_input(
                        f"{outcome_display_labels.get(outcome_id, readable_label(outcome_id))} · {readable_label(name)}",
                        value=0.0,
                        key=f"ocg_outcome_control_{market}_{outcome_id}_{name}",
                    )
                    for name in fitted_names
                }
            st.markdown("**Other-channel model input** (every fitted channel)")
            other_channel_media_input = {
                channel: st.number_input(
                    model_input_display_label(
                        channel,
                        activity_definitions=activity_definitions,
                        market=market,
                    ),
                    value=0.0,
                    key=f"ocg_other_channel_{market}_{channel}",
                )
                for channel in meta.channels
            }
            p1, p2 = st.columns(2)
            reference_period_start = p1.date_input(
                "Reference period start",
                value=date.today(),
                key=f"ocg_ref_start_{market}",
            )
            reference_period_end = p2.date_input(
                "Reference period end", value=date.today(), key=f"ocg_ref_end_{market}"
            )
            context = CurveReferenceContext(
                reference_context_id=reference_context_id,
                mode=mode,
                market=market,
                trend=trend,
                fourier=fourier,
                promo=promo,
                controls=controls,
                outcome_controls=outcome_controls,
                other_channel_media_input=other_channel_media_input,
                counterfactual_value=counterfactual_value,
                counterfactual_axis_type=curve_type,
                reference_period_start=str(reference_period_start),
                reference_period_end=str(reference_period_end),
            )
        else:
            # market (not meta_selected.markets) is looked up as a position
            # into meta.markets, matching frame["market_idx"]'s original
            # fit-time market encoding - the subset meta built for C4 must
            # never be used for a frame-derived lookup like this one.
            period_start = period_end = specific_week = None
            if mode == "period_average":
                pp1, pp2 = st.columns(2)
                period_start = str(
                    pp1.date_input(
                        "Period start",
                        value=date.today(),
                        key=f"ocg_period_start_{market}",
                    )
                )
                period_end = str(
                    pp2.date_input(
                        "Period end", value=date.today(), key=f"ocg_period_end_{market}"
                    )
                )
            elif mode == "specific_week":
                specific_week = str(
                    st.date_input(
                        "Specific week",
                        value=date.today(),
                        key=f"ocg_specific_week_{market}",
                    )
                )
            try:
                context = reference_context_from_model_frame(
                    frame,
                    meta,
                    market=market,
                    mode=mode,
                    reference_context_id=reference_context_id,
                    period_start=period_start,
                    period_end=period_end,
                    specific_week=specific_week,
                    counterfactual_value=counterfactual_value,
                    counterfactual_axis_type=curve_type,
                )
            except ValueError as exc:
                st.error(f"Could not derive a reference context for {market}: {exc}")
            else:
                st.markdown(
                    "**Derived from the model frame** (review before confirming)"
                )
                st.write(
                    _humanise_reference_context_preview(
                        context,
                        outcome_display_labels,
                        activity_definitions=activity_definitions,
                        market=market,
                    )
                )

        # Corrective PR E2.2: the checkbox's own widget key embeds a
        # fingerprint of everything the confirmation actually depends on
        # (complete context values, model identity, market, curve type,
        # mode, and source period/week). Changing any of those changes the
        # key, so Streamlit renders a fresh, unchecked widget rather than
        # preserving a stale checked state carried over from a materially
        # different context - never relying solely on clearing a checkbox
        # during one rerun.
        context_fingerprint = _context_confirmation_fingerprint(
            market=market,
            context=context,
            curve_type=curve_type,
            mode=mode,
            period_start=period_start,
            period_end=period_end,
            specific_week=specific_week,
            model_identity=current_identity,
        )
        confirmed = st.checkbox(
            f"I have reviewed and confirm the {market} reference context above is correct",
            value=False,
            key=f"ocg_ctx_confirmed_{market}_{context_fingerprint}",
            disabled=context is None,
        )
        if context is not None and confirmed:
            confirmed_context_fingerprints[market] = context_fingerprint
        # Explicit, testable defense in depth alongside the key-based reset
        # above: generation later requires this persisted fingerprint to
        # still equal the current one, rather than trusting the checkbox's
        # boolean value alone.
        reference_context_confirmed[market] = (
            context is not None
            and confirmed
            and confirmed_context_fingerprints.get(market) == context_fingerprint
        )
        if context is not None:
            reference_contexts[market] = context

# ---------------------------------------------------------------------------
# 4. Model-input support (optional per market/channel - enables planning
#    eligibility for that cell; omitted cells generate but are not
#    planning-support-eligible).
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### Observed support for Planning Curve use")
st.caption(
    "Model-input identity/unit metadata (column, unit, unit scale) is "
    "required for every channel below - generation itself needs it to know "
    "what unit spend_points are expressed in. Observed current/min/max "
    "support is always derived from the prepared model frame's actual "
    "history; self-declared observed ranges are not accepted. Only "
    "the forward-looking planning min/max remain an explicit analyst "
    "choice. The support range is optional per (market, channel): providing "
    "it marks that cell planning-support-eligible; an omitted range still "
    "generates a curve but blocks it from planning/optimisation use."
)
derivation_method = st.selectbox(
    "Current-spend method (applies to every cell below that "
    "opts in to a support range)",
    list(_CURRENT_SPEND_METHOD_LABELS),
    format_func=lambda value: _CURRENT_SPEND_METHOD_LABELS.get(
        value, readable_label(value)
    ),
    key="ocg_support_method",
)
support_period_start = support_period_end = None
if derivation_method == "selected_period_average":
    sp1, sp2 = st.columns(2)
    support_period_start = str(
        sp1.date_input(
            "Support period start", value=date.today(), key="ocg_support_period_start"
        )
    )
    support_period_end = str(
        sp2.date_input(
            "Support period end", value=date.today(), key="ocg_support_period_end"
        )
    )

media_input_specs: dict[tuple[str, str], MediaInputSpec] = {}
_all_media_input_specs: dict[tuple[str, str], MediaInputSpec] = {}
for market in meta.markets:
    for channel in meta.channels:
        if market in selected_markets:
            key_prefix = f"ocg_support_{market}_{channel}"
            channel_label = model_input_display_label(
                channel, activity_definitions=activity_definitions, market=market
            )
            unit = st.text_input(
                f"Unit - {market}/{channel_label}",
                value="impressions",
                key=f"{key_prefix}_unit",
            )
            unit_scale = st.number_input(
                f"Unit scale - {market}/{channel_label}",
                value=1.0,
                min_value=1e-9,
                key=f"{key_prefix}_scale",
            )
            spec = MediaInputSpec(
                market=market,
                channel=channel,
                column=channel,
                unit=unit,
                unit_scale=unit_scale,
            )
            media_input_specs[(market, channel)] = spec
        else:
            # support_from_model_frame requires a spec for every market in
            # the *original* fitted meta - never the C4 market subset, since
            # its market-position mask indexing only lines up against
            # meta.markets in fit-time order. A deselected market's
            # placeholder here is never surfaced or used for generation.
            spec = MediaInputSpec(
                market=market,
                channel=channel,
                column=channel,
                unit="units",
                unit_scale=1.0,
            )
        _all_media_input_specs[(market, channel)] = spec

try:
    derived_support = support_from_model_frame(
        frame,
        meta,
        current_spend_method=derivation_method,
        selected_period_start=support_period_start,
        selected_period_end=support_period_end,
        media_input_specs=_all_media_input_specs,
    )
except ValueError as exc:
    st.error(f"Could not derive support from the model frame: {exc}")
    derived_support = {}

support_by_market_channel: dict[tuple[str, str], object] = {}
# Corrective PR E2.3: a market/channel cell the analyst opted into but
# whose monetary conversion is out of the governed cost mapping's domain
# (allow_extrapolation=False) must render an actionable blocking message
# and prevent official generation, never crash the whole page - and never
# silently permit extrapolation to make the error go away.
invalid_support_cells: list[str] = []
for market in selected_markets:
    for channel in meta.channels:
        key_prefix = f"ocg_support_{market}_{channel}"
        with st.expander(
            f"Model input - {market} / "
            f"{model_input_display_label(channel, activity_definitions=activity_definitions, market=market)}",
            expanded=False,
        ):
            include_support = st.checkbox(
                "Also record observed/planning support for this cell "
                "(enables planning eligibility)",
                value=False,
                key=f"{key_prefix}_include",
            )
            if not include_support:
                continue
            derived = derived_support.get((market, channel))
            if derived is None:
                st.warning(
                    "No observed data for this market/channel in the "
                    "prepared model frame; support cannot be derived."
                )
                continue
            st.markdown("**Derived from the model frame** (review before use)")
            d1, d2, d3 = st.columns(3)
            d1.metric("Current", f"{derived.current:,.2f}")
            d2.metric("Observed min", f"{derived.observed_min:,.2f}")
            d3.metric("Observed max", f"{derived.observed_max:,.2f}")
            s4, s5 = st.columns(2)
            planning_min = s4.number_input(
                "Planning min", value=derived.observed_min, key=f"{key_prefix}_plan_min"
            )
            planning_max = s5.number_input(
                "Planning max", value=derived.observed_max, key=f"{key_prefix}_plan_max"
            )
            media_support = MediaInputSupport(
                market=market,
                channel=channel,
                unit=derived.unit,
                current=derived.current,
                observed_min=derived.observed_min,
                observed_max=derived.observed_max,
                planning_min=planning_min,
                planning_max=planning_max,
                current_method=derived.current_method,
                source=derived.source,
                provenance=derived.provenance,
                effective_period_start=derived.effective_period_start,
                effective_period_end=derived.effective_period_end,
            )
            if curve_type == "model_input":
                support_by_market_channel[(market, channel)] = media_support
                continue
            # Monetary curves require MonetarySpendSupport, never
            # MediaInputSupport - _normalise_support rejects the latter
            # outright for a monetary curve (Corrective PR C5).
            cost_mapping = (
                cost_mapping_registry.resolve(
                    market, channel, "default", as_of=cost_as_of_date_value or None
                )
                if cost_mapping_registry is not None
                else None
            )
            if cost_mapping is None:
                st.error(
                    f"No approved, effective cost mapping for {market} / "
                    f"{model_input_display_label(channel, activity_definitions=activity_definitions, market=market)} "
                    "as of the cost as-of date above; cannot build monetary support."
                )
                continue
            local_currency = currency_by_market.get(market)
            reporting = reporting_currency or local_currency
            rate = (
                1.0
                if local_currency == reporting
                else currency_rates.get((local_currency, reporting))
            )
            if not rate:
                st.error(
                    f"No valid FX rate {local_currency}->{reporting} for {market} / "
                    f"{model_input_display_label(channel, activity_definitions=activity_definitions, market=market)}; cannot build monetary support."
                )
                continue
            try:
                support_by_market_channel[(market, channel)] = derive_monetary_support(
                    media_support,
                    cost_mapping,
                    reporting_currency=reporting,
                    fx_rate=rate,
                    mapping_fingerprint=cost_mapping_registry.fingerprint(),
                )
            except ValueError as exc:
                # A non-extrapolating piecewise/uploaded-plan mapping does
                # not cover the fitted or planning support range -
                # actionable and blocking, never a crashed page and never
                # silently extrapolated to make the error disappear.
                invalid_support_cells.append(f"{market}/{channel}")
                st.error(
                    f"Cannot derive monetary support for {market} / "
                    f"{model_input_display_label(channel, activity_definitions=activity_definitions, market=market)}: "
                    f"{exc}. Adjust the planning min/max above, or the cost "
                    "mapping's knots/allow_extrapolation on the Media Costs "
                    "page, then retry."
                )

st.markdown("**Curve axis**")
st.caption(
    "Leave blank to derive each channel's axis from its own observed/"
    "planning support range (a unit-specific axis per channel). A comma-"
    "separated list overrides that and applies the same axis, in the same "
    "model-input or monetary units, to every channel; every cell without a "
    "support range above then requires this override."
)
spend_points_text = st.text_input(
    "Curve-axis values (comma-separated, optional)",
    value="",
    key="ocg_spend_points",
)
try:
    spend_points = (
        [float(v.strip()) for v in spend_points_text.split(",") if v.strip()]
        if spend_points_text.strip()
        else None
    )
except ValueError:
    st.error("Spend points must be a comma-separated list of numbers.")
    st.stop()

# ---------------------------------------------------------------------------
# 5. Posterior draw count
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### Uncertainty plan")
n_draws = st.slider(
    "Posterior draws to include", 20, 200, 50, step=10, key="ocg_n_draws"
)

# ---------------------------------------------------------------------------
# 6. Generate and persist
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### Save this Planning Curve")
st.caption(
    "Review the readiness state below, then save a governed Planning Curve. The action "
    "does not change the fitted model or invent a new response calculation."
)
artifact_id = st.text_input(
    "Planning Curve name or reference",
    value=_planning_curve_reference(selected_outcome, date.today()),
    key="ocg_artifact_id",
)

# Pre-flight readiness (Phase 6 UI overhaul): restates, before the button is
# pressed, the exact same completeness conditions the click handler below
# already checks - a missing requirement is visible as an explicit blocker
# up front, not only as an st.error after the click. CurveService's own
# governance chain (outcome/model approval, threshold policy, readiness,
# diagnostics, activity/pathway governance) remains the authoritative,
# unconditional check and still runs unchanged when Generate is pressed.
_generation_blockers = resolve_generation_blockers(
    eligible_outcomes_count=len(eligible),
    selected_markets=selected_markets,
    curve_type=curve_type,
    cost_mapping_registry_present=bool(
        cost_mapping_registry is not None
        and cost_mapping_registry.to_dict()["mappings"]
    ),
    currency_by_market=currency_by_market,
    reporting_currency=reporting_currency,
    reference_context_confirmed=reference_context_confirmed,
    invalid_support_cells=invalid_support_cells,
    missing_fx_pairs=missing_fx_pairs,
    artifact_id=artifact_id,
)
if candidate_a_missing_curve_caps:
    _generation_blockers.append(
        GenerationBlocker(
            "candidate_a_missing_paid_search_cap",
            "Candidate A official curves require an explicit future Paid "
            "Search delivery cap for: "
            f"{', '.join(sorted(candidate_a_missing_curve_caps))}.",
        )
    )
if _generation_blockers:
    with BlockingPanel(
        "Not ready to generate",
        description="Resolve every item below before Generate is enabled.",
    ):
        for _blocker in _generation_blockers:
            st.markdown(f"- {_blocker.message}")
else:
    st.caption("All readiness checks pass - ready to save the Planning Curve.")

if st.button(
    "Save Planning Curve",
    type="primary",
    disabled=bool(_generation_blockers),
):
    if not artifact_id.strip():
        st.error("Planning Curve name or reference must be non-blank.")
        st.stop()
    unconfirmed_markets = sorted(
        m for m in selected_markets if not reference_context_confirmed.get(m)
    )
    if unconfirmed_markets:
        st.error(
            "Review and confirm the reference context for every selected "
            f"market before generating: {unconfirmed_markets}"
        )
        st.stop()
    if invalid_support_cells:
        # Corrective PR E2.3: a cell whose monetary conversion is out of
        # the governed cost mapping's domain must block generation, not
        # merely display an error above that the analyst could ignore.
        st.error(
            "Cannot generate: monetary support is out of the governed cost "
            "mapping's domain for "
            f"{sorted(invalid_support_cells)}. Correct it above before "
            "generating."
        )
        st.stop()
    governance = OfficialCurveGovernance(
        model_identity=ModelIdentity(**current_identity),
        model_approval=ModelApproval.from_dict(approval_dict),
        outcome_definition=selected_outcome,
        outcome_approval=selected_outcome_approval,
        threshold_policy=current_policy,
        approval_readiness=current_readiness,
        diagnostics_artefact=current_diagnostics_artefact,
        activity_definitions=activity_definitions,
        outcome_approvals=outcome_approvals,
    )
    try:
        monetary_kwargs = (
            {
                "cost_mapping_registry": cost_mapping_registry,
                "currency_by_market": currency_by_market or None,
                "reporting_currency": reporting_currency or None,
                "currency_rates": currency_rates or None,
                "fx_as_of_date": fx_as_of_date_value or None,
                "fx_source": fx_source_value or None,
                "cost_as_of_date": cost_as_of_date_value or None,
            }
            if curve_type == "monetary"
            else {}
        )
        result = _CURVE_SERVICE.create_official_artifact(
            governance,
            artifact_id=artifact_id.strip(),
            store_dir=curve_artifact_store_dir(),
            meta=meta_selected,
            trace=trace,
            reference_contexts=reference_contexts,
            model_type=model_type,
            curve_type=curve_type,
            media_input_specs=media_input_specs or None,
            support_by_market_channel=support_by_market_channel or None,
            spend_points=spend_points,
            n_draws=n_draws,
            candidate_a_paid_search_cap_by_market=(
                candidate_a_curve_caps
                if meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE
                else None
            ),
            **monetary_kwargs,
        )
    except (CurveGovernanceError, CurveArtifactError, ValueError, TypeError) as exc:
        st.error(f"Could not save the Planning Curve: {_humanise_permission_text(exc)}")
    else:
        st.success(
            "Saved Planning Curve. Review its response evidence and permitted uses below."
        )

        st.markdown("#### Planning Curve saved")
        # Permission and planning-support status
        st.markdown("#### Where this Planning Curve can be used")
        try:
            authorization = _CURVE_SERVICE.authorize_use(
                result.artifact, requested_use, current_governance=governance
            )
        except CurveGovernanceError as exc:
            st.warning(
                f"Not currently approved for {requested_use_label}: "
                f"{_humanise_permission_text(exc)}"
            )
        else:
            planning_support = (
                bool(result.artifact.draws["planning_support_eligible"].all())
                if (
                    not result.artifact.draws.empty
                    and "planning_support_eligible" in result.artifact.draws.columns
                )
                else "n/a"
            )
            status_df = pd.DataFrame(
                [
                    {
                        "Current permission": _status_label(
                            authorization.current_authorization_status
                        ),
                        "Checked use": requested_use_label,
                        "Use permission": _status_label(
                            authorization.requested_use_eligibility
                        ),
                        "Planning support": (
                            "Eligible"
                            if planning_support is True
                            else "Not eligible"
                            if planning_support is False
                            else "Not assessed"
                        ),
                    }
                ]
            )
            st.dataframe(
                status_df,
                width="stretch",
                column_config=dataframe_column_config(status_df),
            )
            render_technical_details(
                title="Technical details · saved Planning Curve",
                details={
                    "Saved curve ID": result.artifact_id,
                    "Stored requested-use key": requested_use,
                    "Stored authorization status": authorization.current_authorization_status,
                    "Stored requested-use eligibility": authorization.requested_use_eligibility,
                },
            )

        # 8. Posterior interval display + average/marginal economics
        st.markdown("#### Response evidence and economics")
        summaries = result.artifact.summaries
        draws = result.artifact.draws
        # Corrective PR E2a: the persisted summary grain's "spend_point" is
        # an ordinal point identifier (0, 1, 2, ...), never the real
        # media_input/local_spend/reporting_currency_spend axis - plotting
        # it under a real-unit label displayed point indexes as though they
        # were TVRs, impressions, GBP, etc. The real axis only lives on the
        # draws (aggregate_curve_draws, which builds the persisted summary
        # grain, does not carry media_input through at all, and only ever
        # carries local_spend - never a channel/spend_point-safe axis for a
        # model-input curve). Resolve the axis and summarise the same way
        # the Curve Bank display does (resolve_curve_axis_column +
        # summarize_component_response_by_draw on the draws), so both pages
        # share one canonical curve-axis resolution - never a second,
        # page-specific posterior summarisation.
        chart_required = {"incremental_response", "market", "channel", "posterior_draw"}
        x_col = resolve_curve_axis_column(draws)
        if draws.empty or x_col is None or not chart_required.issubset(draws.columns):
            st.caption(
                "This Planning Curve does not carry a plottable posterior response "
                "curve (missing market/channel/axis/response/posterior_draw "
                "columns)."
            )
        else:
            for (curve_market, curve_channel), draws_group in draws.groupby(
                ["market", "channel"], observed=True
            ):
                stats = summarize_component_response_by_draw(
                    draws_group, by=[], x_col=x_col
                ).sort_values(x_col)
                st.plotly_chart(
                    create_response_curve_with_band(
                        stats[x_col].to_numpy(dtype=float),
                        stats["posterior_mean"].to_numpy(dtype=float),
                        stats["lower_interval"].to_numpy(dtype=float),
                        stats["upper_interval"].to_numpy(dtype=float),
                        f"{curve_market} · "
                        f"{model_input_display_label(curve_channel, activity_definitions=activity_definitions, market=curve_market)}",
                        x_axis_label=resolve_curve_axis_label(x_col, draws_group),
                    ),
                    width="stretch",
                )
                if not summaries.empty and {
                    "market",
                    "channel",
                    "spend_point",
                }.issubset(summaries.columns):
                    econ_group = summaries[
                        (summaries["market"] == curve_market)
                        & (summaries["channel"] == curve_channel)
                    ].sort_values("spend_point")
                    economics_cols = [
                        c
                        for c in econ_group.columns
                        if c.startswith(
                            (
                                "average_cpa",
                                "marginal_cpa",
                                "average_roi",
                                "marginal_roi",
                            )
                        )
                    ]
                    if economics_cols and curve_type == "monetary":
                        display_economics = econ_group[
                            ["spend_point", *economics_cols]
                        ].rename(
                            columns={
                                "spend_point": "Curve point",
                                "average_cpa": "Average CPA",
                                "marginal_cpa": "Marginal CPA",
                                "average_roi": "Average ROI",
                                "marginal_roi": "Marginal ROI",
                            }
                        )
                        st.dataframe(
                            display_economics,
                            width="stretch",
                        )
                        st.caption(
                            "Average and marginal economics are shown in the "
                            f"reporting currency ({reporting_currency or 'as saved in the curve'}), "
                            "at channel-total scope, with uncertainty carried by the posterior summaries."
                        )
                    elif curve_type == "model_input":
                        st.caption(
                            "Monetary CPA and ROI are not shown: this Planning Curve "
                            "remains in model-input units until an approved cost mapping "
                            "and currency evidence are supplied."
                        )

render_next_step("official_curve_generation")
