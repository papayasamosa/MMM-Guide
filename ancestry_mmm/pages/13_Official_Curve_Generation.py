"""Page 13: generate and persist a governed official curve artifact
(REQ-CURVE-001) - the CurveService.create_official_artifact application
boundary, driven from the UI for the first time. Supports both model-input
curves and monetary curves (governed cost mappings + currency/FX evidence).
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    curve_artifact_store_dir,
    dataframe_column_config,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
)
from ancestry_mmm.core.activities import ActivityDefinition, activity_fit_fingerprint
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.canonical_curves import CONTEXT_MODES, CurveReferenceContext
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
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
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcome_approval import OutcomeApproval
from ancestry_mmm.core.outcomes import (
    outcome_catalogue_fingerprint_payload,
    resolve_outcome_definitions,
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.schema import ModelSpec
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
from ancestry_mmm.components.charts import create_response_curve_with_band

_COST_MAPPING_TYPES = {
    "identity_spend": IdentitySpendMapping,
    "fixed_cost_per_unit": FixedCostPerUnitMapping,
    "piecewise_linear": PiecewiseLinearCostMapping,
    "uploaded_plan": UploadedPlanCostMapping,
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
]


def _knots_from_text(text: str) -> tuple:
    return tuple(float(v.strip()) for v in str(text).split(",") if v.strip())


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
    )
    if method == "identity_spend":
        return IdentitySpendMapping(**common)
    if method == "fixed_cost_per_unit":
        return FixedCostPerUnitMapping(
            **common, cost_per_media_input=float(row["cost_per_media_input"])
        )
    if method == "piecewise_linear":
        return PiecewiseLinearCostMapping(
            **common,
            spend_knots=_knots_from_text(row.get("spend_knots", "")),
            media_input_knots=_knots_from_text(row.get("media_input_knots", "")),
        )
    return UploadedPlanCostMapping(
        **common,
        spend_knots=_knots_from_text(row.get("spend_knots", "")),
        media_input_knots=_knots_from_text(row.get("media_input_knots", "")),
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
    page_title="Official Curve Generation - Ancestry FH MMM",
    page_icon="🧬",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("official_curve_generation")
render_page_header("official_curve_generation")
st.caption(
    "Produces a governed, evaluated official curve artifact through "
    "CurveService.create_official_artifact - distinct from the legacy curve "
    "bank's fitted-parameter snapshots (Results & Curve Bank), which are "
    "never official evaluated curves. Supports both model-input curves and "
    "monetary curves (an approved, effective cost mapping plus currency/FX "
    "evidence is required for the latter)."
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
    st.markdown("---")
    render_empty_state(
        "No trained model yet. Complete Model Training first.",
        button_label="Go to Model Training",
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
outcome_approvals = [
    OutcomeApproval.from_dict(d) for d in (get_state("outcome_approvals") or [])
]

if not current_identity or not approval_dict:
    st.markdown("---")
    render_empty_state(
        "No current model identity/approval available - approve this model "
        "on Diagnostics first.",
        button_label="Go to Diagnostics",
        target_key="diagnostics",
    )
    st.stop()

# ---------------------------------------------------------------------------
# 1. Outcome and use selection
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 1. Outcome and use")
st.caption(
    "Only outcomes with a current, approved outcome approval covering "
    "curve_publication can become official curves (REQ-CURVE-001)."
)
eligible: list[tuple[OutcomeApproval, object]] = []
for outcome_approval in outcome_approvals:
    if outcome_approval.status != "approved":
        continue
    if "curve_publication" not in outcome_approval.allowed_uses:
        continue
    outcome = next(
        (o for o in outcome_definitions if o.outcome_id == outcome_approval.outcome_id),
        None,
    )
    if outcome is not None:
        eligible.append((outcome_approval, outcome))

if not eligible:
    render_empty_state(
        "No outcome is currently approved for curve_publication. Review "
        "outcome approvals on Structure -> Outcome Governance first.",
        button_label="Go to Structure: Segments & Markets",
        target_key="structure",
    )
    st.stop()

outcome_labels = [outcome.outcome_id for _, outcome in eligible]
selected_label = st.selectbox("Outcome", outcome_labels, key="ocg_outcome")
selected_outcome_approval, selected_outcome = next(
    (oa, o) for oa, o in eligible if o.outcome_id == selected_label
)

requested_use = st.selectbox(
    "Requested use to check immediately after generation",
    ["headline_reporting", "planning", "optimisation", "external_distribution"],
    key="ocg_requested_use",
)

# ---------------------------------------------------------------------------
# 2. Markets to include
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 2. Markets")
selected_markets = st.multiselect(
    "Markets to generate a curve for",
    meta.markets,
    default=meta.markets,
    key="ocg_markets",
)
if not selected_markets:
    st.info("Select at least one market to continue.")
    st.stop()

fourier_length = len(next(iter(params.gamma_fourier.values())))

# ---------------------------------------------------------------------------
# 2b. Curve type, and, if monetary, governed cost mappings and currency/FX
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 2b. Curve type")
curve_type_label = st.radio(
    "Curve type",
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
fx_as_of_date_value = ""
fx_source_value = ""

if curve_type == "monetary":
    st.caption(
        "Monetary curves require an approved, effective cost mapping for "
        "every (market, channel) plus explicit currency/FX evidence "
        "(REQ-CURVE-001)."
    )
    st.markdown("**Governed cost mappings**")
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
            }
            for market in selected_markets
            for channel in meta.channels
        ]
    cost_editor = st.data_editor(
        pd.DataFrame(grid_rows).reindex(columns=_COST_MAPPING_GRID_COLUMNS),
        num_rows="dynamic",
        width="stretch",
        key="ocg_cost_mapping_editor",
        column_config={
            "market": st.column_config.SelectboxColumn(
                "Market", options=selected_markets, required=True
            ),
            "channel": st.column_config.SelectboxColumn(
                "Channel", options=meta.channels, required=True
            ),
            "method": st.column_config.SelectboxColumn(
                "Method", options=sorted(SUPPORTED_METHODS), required=True
            ),
            "approval_status": st.column_config.SelectboxColumn(
                "Approval", options=_COST_MAPPING_APPROVAL_STATUSES, required=True
            ),
        },
    )
    cost_mapping_rows = cost_editor.fillna("").to_dict("records")
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
                "mapping(s)."
            )
    cost_mapping_registry = CostMappingRegistry.from_dict(
        get_state("media_cost_mappings")
    )

    st.markdown("**Currency & FX**")
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
    distinct_locals = sorted(
        {cur for cur in currency_by_market.values() if cur} - {reporting_currency}
    )
    for local_currency in distinct_locals:
        currency_rates[(local_currency, reporting_currency)] = st.number_input(
            f"FX rate: 1 {local_currency} -> {reporting_currency}",
            value=1.0,
            min_value=0.0,
            key=f"ocg_fx_rate_{local_currency}",
        )

# ---------------------------------------------------------------------------
# 3. Reference context per market
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 3. Reference context per market")
st.caption(
    "Every field below is required explicitly - REQ-CURVE-001 forbids an "
    "implicit zero, historical mean, or unstated default standing in for a "
    "reference-context value."
)
reference_contexts: dict[str, CurveReferenceContext] = {}
for market in selected_markets:
    with st.expander(f"Reference context - {market}", expanded=False):
        mode = st.selectbox("Mode", sorted(CONTEXT_MODES), key=f"ocg_mode_{market}")
        reference_context_id = st.text_input(
            "Reference context ID",
            value=f"{market}-{mode}",
            key=f"ocg_ctx_id_{market}",
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
                outcome_id, value=0.0, key=f"ocg_promo_{market}_{outcome_id}"
            )
            for outcome_id in meta.outcome_ids
        }
        st.markdown("**Common controls**")
        controls = {
            name: st.number_input(name, value=0.0, key=f"ocg_control_{market}_{name}")
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
                    f"{outcome_id} / {name}",
                    value=0.0,
                    key=f"ocg_outcome_control_{market}_{outcome_id}_{name}",
                )
                for name in fitted_names
            }
        st.markdown("**Other-channel model input** (every fitted channel)")
        other_channel_media_input = {
            channel: st.number_input(
                channel, value=0.0, key=f"ocg_other_channel_{market}_{channel}"
            )
            for channel in meta.channels
        }
        c1, c2 = st.columns(2)
        counterfactual_value = c1.number_input(
            "Counterfactual value", value=0.0, key=f"ocg_cf_value_{market}"
        )
        c2.text_input(
            "Counterfactual axis type",
            value=curve_type,
            disabled=True,
            key=f"ocg_cf_axis_{market}",
        )
        p1, p2 = st.columns(2)
        reference_period_start = p1.date_input(
            "Reference period start", value=date.today(), key=f"ocg_ref_start_{market}"
        )
        reference_period_end = p2.date_input(
            "Reference period end", value=date.today(), key=f"ocg_ref_end_{market}"
        )
        reference_contexts[market] = CurveReferenceContext(
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

# ---------------------------------------------------------------------------
# 4. Model-input support (optional per market/channel - enables planning
#    eligibility for that cell; omitted cells generate but are not
#    planning-support-eligible).
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 4. Model-input support")
st.caption(
    "Model-input identity/unit metadata (column, unit, unit scale) is "
    "required for every channel below - generation itself needs it to know "
    "what unit spend_points are expressed in. The observed/planning support "
    "range is optional per (market, channel): providing it marks that cell "
    "planning-support-eligible; an omitted range still generates a curve but "
    "blocks it from planning/optimisation use."
)
media_input_specs: dict[tuple[str, str], MediaInputSpec] = {}
support_by_market_channel: dict[tuple[str, str], MediaInputSupport] = {}
for market in selected_markets:
    for channel in meta.channels:
        key_prefix = f"ocg_support_{market}_{channel}"
        with st.expander(f"Model input - {market} / {channel}", expanded=False):
            unit = st.text_input("Unit", value="impressions", key=f"{key_prefix}_unit")
            unit_scale = st.number_input(
                "Unit scale", value=1.0, min_value=1e-9, key=f"{key_prefix}_scale"
            )
            media_input_specs[(market, channel)] = MediaInputSpec(
                market=market,
                channel=channel,
                column=channel,
                unit=unit,
                unit_scale=unit_scale,
            )

            include_support = st.checkbox(
                "Also record observed/planning support for this cell "
                "(enables planning eligibility)",
                value=False,
                key=f"{key_prefix}_include",
            )
            if not include_support:
                continue
            s1, s2, s3 = st.columns(3)
            current = s1.number_input("Current", value=0.0, key=f"{key_prefix}_current")
            observed_min = s2.number_input(
                "Observed min", value=0.0, key=f"{key_prefix}_obs_min"
            )
            observed_max = s3.number_input(
                "Observed max", value=0.0, key=f"{key_prefix}_obs_max"
            )
            s4, s5 = st.columns(2)
            planning_min = s4.number_input(
                "Planning min", value=0.0, key=f"{key_prefix}_plan_min"
            )
            planning_max = s5.number_input(
                "Planning max", value=0.0, key=f"{key_prefix}_plan_max"
            )
            current_method = st.selectbox(
                "Current method",
                [
                    "latest_complete_week",
                    "last_4_week_average",
                    "last_13_week_average",
                    "selected_period_average",
                    "uploaded_plan",
                ],
                key=f"{key_prefix}_method",
            )
            source = st.text_input(
                "Source", value="model frame", key=f"{key_prefix}_source"
            )
            provenance = st.text_input(
                "Provenance", value="", key=f"{key_prefix}_provenance"
            )
            support_by_market_channel[(market, channel)] = MediaInputSupport(
                market=market,
                channel=channel,
                unit=unit,
                current=current,
                observed_min=observed_min,
                observed_max=observed_max,
                planning_min=planning_min,
                planning_max=planning_max,
                current_method=current_method,
                source=source,
                provenance=provenance,
            )

st.markdown(
    "**Diagnostic spend axis** (required for any cell without an "
    "observed support range above)"
)
spend_points_text = st.text_input(
    "Spend points (comma-separated)",
    value="0, 50, 100, 150, 200",
    key="ocg_spend_points",
)
try:
    spend_points = [float(v.strip()) for v in spend_points_text.split(",") if v.strip()]
except ValueError:
    st.error("Spend points must be a comma-separated list of numbers.")
    st.stop()

# ---------------------------------------------------------------------------
# 5. Posterior draw count
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 5. Posterior draw count")
n_draws = st.slider(
    "Posterior draws to sample", 20, 200, 50, step=10, key="ocg_n_draws"
)

# ---------------------------------------------------------------------------
# 6. Generate and persist
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 6. Generate and save")
artifact_id = st.text_input(
    "Artifact ID",
    value=f"{selected_outcome.outcome_id}-{date.today().isoformat()}",
    key="ocg_artifact_id",
)

if st.button("Generate and save official curve artifact", type="primary"):
    if not artifact_id.strip():
        st.error("Artifact ID must be non-blank.")
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
            }
            if curve_type == "monetary"
            else {}
        )
        result = _CURVE_SERVICE.create_official_artifact(
            governance,
            artifact_id=artifact_id.strip(),
            store_dir=curve_artifact_store_dir(),
            meta=meta,
            trace=trace,
            reference_contexts=reference_contexts,
            model_type=model_type,
            curve_type=curve_type,
            media_input_specs=media_input_specs or None,
            support_by_market_channel=support_by_market_channel or None,
            spend_points=spend_points,
            n_draws=n_draws,
            **monetary_kwargs,
        )
    except (CurveGovernanceError, CurveArtifactError, ValueError, TypeError) as exc:
        st.error(f"Could not generate the official curve artifact: {exc}")
    else:
        st.success(f"Saved official curve artifact `{result.artifact_id}`.")

        # 7. Authorization and planning-support status
        st.markdown("#### Authorization and planning-support status")
        try:
            authorization = _CURVE_SERVICE.authorize_use(
                result.artifact, requested_use, current_governance=governance
            )
        except CurveGovernanceError as exc:
            st.warning(f"Not currently authorized for {requested_use}: {exc}")
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
                        "artifact_id": result.artifact_id,
                        "current_authorization": authorization.current_authorization_status,
                        "requested_use_eligibility": authorization.requested_use_eligibility,
                        "planning_support_eligible": planning_support,
                    }
                ]
            )
            st.dataframe(
                status_df,
                width="stretch",
                column_config=dataframe_column_config(status_df),
            )

        # 8. Posterior interval display + average/marginal economics
        st.markdown("#### Posterior interval and economics")
        summaries = result.artifact.summaries
        if (
            summaries.empty
            or "spend_point" not in summaries.columns
            or "market" not in summaries.columns
            or "channel" not in summaries.columns
        ):
            st.caption("No plottable posterior summaries on this artifact.")
        else:
            for (curve_market, curve_channel), group in summaries.groupby(
                ["market", "channel"], observed=True
            ):
                group = group.sort_values("spend_point")
                if "incremental_response_posterior_mean" in group.columns:
                    st.plotly_chart(
                        create_response_curve_with_band(
                            group["spend_point"].to_numpy(dtype=float),
                            group["incremental_response_posterior_mean"].to_numpy(
                                dtype=float
                            ),
                            group["incremental_response_lower_interval"].to_numpy(
                                dtype=float
                            ),
                            group["incremental_response_upper_interval"].to_numpy(
                                dtype=float
                            ),
                            f"{curve_market} - {curve_channel}",
                        ),
                        width="stretch",
                    )
                economics_cols = [
                    c
                    for c in group.columns
                    if c.startswith(
                        ("average_cpa", "marginal_cpa", "average_roi", "marginal_roi")
                    )
                ]
                if economics_cols:
                    st.dataframe(
                        group[["spend_point", *economics_cols]],
                        width="stretch",
                    )

render_next_step("official_curve_generation")
