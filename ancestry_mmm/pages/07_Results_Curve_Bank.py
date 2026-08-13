"""Page 7: segment + total-FH contributions, ROAS/CPA, LTV-weighted value, and the versioned curve bank."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    curve_bank_dir,
    curve_artifact_store_dir,
    dataframe_column_config,
    format_date,
    FIELD_HELP,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_drift_status,
    render_workspace_note,
    render_decision_help,
    render_technical_details,
    SectionCard,
)
from ancestry_mmm.core.approval import (
    ApprovalMismatchError,
    ModelApproval,
    ValidationPolicyBlockedError,
    require_matching_approval,
)
from ancestry_mmm.core.validation_policy import (
    load_approval_readiness,
    load_threshold_policy,
)
from ancestry_mmm.core.activities import ActivityDefinition, activity_fit_fingerprint
from ancestry_mmm.core.search_objects import (
    SearchObjectDefinition,
    search_object_fit_fingerprint,
)
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.canonical_curves import (
    resolve_curve_axis_column,
    resolve_curve_axis_label,
    summarize_component_response_by_draw,
)
from ancestry_mmm.core.curve_artifact import (
    CurveArtifactError,
    governed_context_fields,
    load_curve_artifact_store,
)
from ancestry_mmm.core.outcome_approval import OutcomeApproval
from ancestry_mmm.application.curve_service import (
    CurveGovernanceError,
    CurveService,
)
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.causal_graph import current_structural_fingerprint_for_identity
from ancestry_mmm.core.outcomes import (
    fh_gsa_outcome_ids,
    fh_signup_outcome_ids,
    dna_kit_sale_outcome_ids,
    outcome_catalogue_fingerprint_payload,
    resolve_outcome_definitions,
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.market_config import MarketSpecConfig
from ancestry_mmm.core.attribution import (
    compute_shapley_contributions,
    outcome_channel_summary,
    total_fh_contribution,
    contribution_waterfall,
)
from ancestry_mmm.core.market_specific_attribution import (
    compute_shapley_contributions_market_specific,
    outcome_channel_market_summary,
    total_contribution_market_specific,
)
from ancestry_mmm.core import curve_bank as cb
from ancestry_mmm.core.evidence_tiers import (
    classify_all_markets,
    classify_market_evidence,
)
from ancestry_mmm.core.predict import generate_channel_curve
from ancestry_mmm.core.market_specific_predict import generate_market_channel_curve
from ancestry_mmm.core.uncertainty import (
    generate_channel_curve_with_uncertainty,
    generate_market_channel_curve_with_uncertainty,
)
from ancestry_mmm.core.media_units import (
    compute_cpa_by_product,
    cpa_stability_flags,
    extract_cost_per_unit_series,
    historical_cost_trend,
    response_unit_curve,
    equivalent_delivery,
    equivalent_response,
)
from ancestry_mmm.components.charts import (
    create_waterfall_chart,
    create_response_curve,
    create_response_curve_with_band,
    create_annotated_response_curve,
)
from ancestry_mmm.application.curve_annotations import (
    annotation_from_legacy_curve,
    annotation_from_official_support,
)

st.set_page_config(
    page_title="Results & Response Curves | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("curve_bank")
render_page_header(
    "curve_bank",
    task_prompt="Which response evidence is ready for analysis or governed use?",
)
render_workspace_note(
    "Evidence and authority",
    "Inspect observed support, uncertainty, and evidence tier before using a curve; official artifacts are governed separately from exploratory snapshots.",
    kind="governed",
)
render_decision_help(
    "What this chart shows",
    controls="The fitted response as one channel's media input changes, with the other channels held at the reference conditions used for this curve.",
    why="This is a channel-level response view, not a whole-plan result. It helps you see the observed support, uncertainty, and how average and marginal economics change near saturation.",
    options={
        "Observed support": "The shaded or marked range shows where this channel has historical input data; it is not invented from a saturation parameter.",
        "Current point": "The diamond marks the current historical average input used as the reference point for this view.",
        "Average CPA": "Spend divided by incremental outcomes at a point on the curve.",
        "Marginal CPA": "The change in spend divided by the change in incremental outcomes between nearby points.",
        "Unavailable economics": "CPA or ROI is left unavailable when a governed cost translation or a positive response change is not available.",
    },
    normal_path="Use exploratory curves to understand response evidence, then use the separate Planning Curves workflow when a governed planning curve is required.",
    downstream="The selected outcome, market context, support, and cost mapping determine which response and economic views are shown.",
    invalidates="Changing the fit, outcome definition, mapping, or governed context can make a curve snapshot stale; official curves require their own readiness and approval checks.",
)
render_technical_details(
    details={
        "Curve source": "Exploratory views are generated from the current fitted posterior and model frame; official curve artifacts are rendered separately with governance checks.",
        "Economic units": "Monetary CPA/ROI is shown only when an approved cost translation maps the model-input units to currency. TVRs, impressions, clicks, GRPs, and spend are not treated as interchangeable.",
        "Uncertainty": "Posterior bands use sampled posterior draws when requested; the displayed support range remains historical observed support.",
    }
)

_dashboard_meta = get_state("model_meta")
_dashboard_trained = all(
    get_state(key) is not None
    for key in ("trace", "frame", "model_meta", "posterior_params")
)
with st.container(border=True):
    st.markdown("### Results dashboard")
    _fit_label = (
        "Market-specific" if get_state("model_type") == "market_specific" else "Shared"
    )
    _result_status = st.columns(4)
    _result_status[0].metric(
        "Fit state", "Trained" if _dashboard_trained else "Not ready"
    )
    _result_status[1].metric("Model type", _fit_label)
    _result_status[2].metric(
        "Markets in fit", len(_dashboard_meta.markets) if _dashboard_meta else "-"
    )
    _result_status[3].metric(
        "Outcomes in fit", len(_dashboard_meta.outcome_ids) if _dashboard_meta else "-"
    )
    st.caption(
        "Use the contribution summary for fitted attribution and the response curve library "
        "for exploratory response evidence. Official curve artifacts remain a separate, "
        "governance-checked view; monetary CPA/ROI appears only where its cost mapping is valid."
    )


def _render_curve_with_cpa(
    curve_df: pd.DataFrame,
    title: str,
    *,
    spend_history=None,
    status_label=None,
) -> None:
    """Annotated response chart + CPA table (docs/media_units_and_inflation.md,
    Phase 6 UI overhaul) for any curve DataFrame - shared by both model
    types since core.predict.generate_channel_curve and
    core.market_specific_predict.generate_market_channel_curve produce the
    same column shape.

    ``spend_history``/``status_label`` are the caller's real, already-
    available historical model-input series and evidence/curve-status label
    for this (market, channel) - see
    ``application.curve_annotations.annotation_from_legacy_curve``; when
    omitted, the chart renders with no annotation layer (identical to the
    pre-Phase-6 chart).
    """
    cpa_df = compute_cpa_by_product(curve_df)
    annotation = annotation_from_legacy_curve(
        curve_df, cpa_df, spend_history or [], status_label=status_label
    )
    st.plotly_chart(
        create_annotated_response_curve(
            curve_df["spend"].to_numpy(),
            curve_df["overall_response"].to_numpy(),
            title,
            current_x=annotation.current_x,
            observed_min=annotation.observed_min,
            observed_max=annotation.observed_max,
            annotation_lines=annotation.annotation_lines(),
        ),
        width="stretch",
    )
    if annotation.current_x is not None:
        st.caption(
            "Diamond marker = current model input (historical average); shaded "
            "band = observed historical support range - both from this channel's "
            "own fitted data, never a saturation-parameter-derived range. "
            "Annotation text (top-left) surfaces evidence/curve status and the "
            "average/marginal economics already shown in the table below, at "
            "the current point."
        )
    st.markdown("**Spend curve with CPA**")
    st.caption(
        "**Channel view:** this channel's incremental response as its media input changes, "
        "holding other channels at the reference conditions. It is not a whole-plan result. "
        "Average CPA is spend divided by incremental outcomes; marginal CPA is the change in "
        "spend divided by the change in incremental outcomes. They diverge near saturation and "
        "are shown separately for each approved outcome. Economics are unavailable when the "
        "response change is zero or negative, or when a valid cost translation is missing."
    )
    st.dataframe(cpa_df, width="stretch", column_config=dataframe_column_config(cpa_df))
    for f in cpa_stability_flags(curve_df)[:5]:
        st.warning(f["message"])


def _pathway_strength_table(meta, params) -> pd.DataFrame:
    """One row per active_cross_product/exploratory_cross_product
    (outcome, channel) cell (PR G1 - core.pathways.resolve_pathway_masks) -
    the general replacement for the old DNA-only "halo strength by outcome"
    table, since a cross-product cell can now exist on any channel, and more
    than one channel can have a distinct cell for the same outcome."""
    rows = []
    for oid in meta.outcome_ids:
        active = set(meta.pathway_masks.active_channels_by_outcome.get(oid, []))
        exploratory = set(
            meta.pathway_masks.exploratory_channels_by_outcome.get(oid, [])
        )
        for ch in active | exploratory:
            rows.append(
                {
                    "outcome_id": oid,
                    "channel": ch,
                    "role": "active_cross_product"
                    if ch in active
                    else "exploratory_cross_product",
                    "strength": params.pathway_strength.get(oid, {}).get(ch),
                }
            )
    return pd.DataFrame(rows, columns=["outcome_id", "channel", "role", "strength"])


def _render_media_unit_section(
    curve_df: pd.DataFrame, market_config: MarketSpecConfig, market: str, channel: str
) -> None:
    """Historical cost trend, response-unit curve, and equivalent delivery/
    response calculators for one (market, channel) - only shown where a
    media-unit mapping exists (Media Mapping page)."""
    config = market_config.get_media_unit_config(market, channel)
    if not (config and config.has_media_unit()):
        st.caption(
            f"No media-unit mapping for {market} / {channel} yet - add one on Media Mapping "
            "to see a response-unit curve, historical cost trend, and delivery/response equivalence "
            "calculators here."
        )
        return

    try:
        cost_df = extract_cost_per_unit_series(
            frame["df"], spec.date_col, spec.market_col, market, config
        )
    except ValueError as e:
        st.warning(
            f"Could not compute a cost-per-unit history for {market} / {channel}: {e}"
        )
        return

    trend = historical_cost_trend(cost_df, spec.date_col)
    if trend["avg_cost_per_unit"] is None:
        st.caption(f"No valid cost-per-unit observations for {market} / {channel} yet.")
        return

    unit_label = config.unit_type or "units"
    st.markdown(f"**Historical cost per {unit_label}**")
    c1, c2 = st.columns(2)
    c1.metric(f"Average cost per {unit_label}", f"{trend['avg_cost_per_unit']:,.2f}")
    c2.metric(
        "Year-on-year inflation",
        f"{trend['yoy_inflation_pct']:.1f}%"
        if trend["yoy_inflation_pct"] is not None
        else "n/a (< 2 years of data)",
    )
    st.dataframe(
        trend["indexed_trend"],
        width="stretch",
        column_config=dataframe_column_config(trend["indexed_trend"]),
    )
    st.caption(
        "`indexed` = cost per unit relative to the first year with data (100 = that year's average)."
    )

    st.markdown(f"**Response-unit curve ({unit_label})**")
    ru_df = response_unit_curve(curve_df, trend["avg_cost_per_unit"])
    st.plotly_chart(
        create_response_curve(
            ru_df["media_units"].to_numpy(),
            ru_df["overall_response"].to_numpy(),
            f"{channel} ({unit_label})",
        ),
        width="stretch",
    )
    st.caption(
        "Derived from the spend curve using the average historical cost per unit - a documented "
        "simplification, not an independently observed "
        "spend-to-delivery relationship at every spend level."
    )

    st.markdown("**Equivalent delivery / response**")
    key_suffix = f"{market}_{channel}"
    c1, c2 = st.columns(2)
    with c1:
        st.caption(f"How much to spend to buy a target number of {unit_label}?")
        target_units = st.number_input(
            f"Target {unit_label}",
            min_value=0.0,
            value=100.0,
            key=f"target_units_{key_suffix}",
        )
        future_cost = st.number_input(
            f"Assumed future cost per {unit_label}",
            min_value=0.0,
            value=float(trend["avg_cost_per_unit"]),
            key=f"future_cost_{key_suffix}",
        )
        st.metric(
            "Required spend", f"{equivalent_delivery(target_units, future_cost):,.0f}"
        )
    with c2:
        st.caption(f"What response would a target number of {unit_label} produce?")
        target_units2 = st.number_input(
            f"Target {unit_label} (response)",
            min_value=0.0,
            value=100.0,
            key=f"target_units2_{key_suffix}",
        )
        cost_assumption = st.number_input(
            f"Cost per {unit_label} assumption",
            min_value=0.0,
            value=float(trend["avg_cost_per_unit"]),
            key=f"cost_assumption_{key_suffix}",
        )
        has_dna = (
            "dna_response" in curve_df.columns and (curve_df["dna_response"] > 0).any()
        )
        has_signup = (
            "fh_signup_response" in curve_df.columns
            and (curve_df["fh_signup_response"] > 0).any()
        )
        fh_response = equivalent_response(
            target_units2, cost_assumption, curve_df, "fh_response"
        )
        st.metric("Modelled response (Family History GSAs)", f"{fh_response:,.1f}")
        if has_signup:
            fh_signup_response = equivalent_response(
                target_units2, cost_assumption, curve_df, "fh_signup_response"
            )
            st.metric(
                "Modelled response (Family History sign-ups)",
                f"{fh_signup_response:,.1f}",
            )
        if has_dna:
            dna_response = equivalent_response(
                target_units2, cost_assumption, curve_df, "dna_response"
            )
            st.metric("Modelled response (DNA kits)", f"{dna_response:,.1f}")


# --- Official curve artifacts (REQ-CURVE-001 / PR 95E) -----------------------
# Rendering helpers for the governed official curve artifact store. Every
# artifact is revalidated against *current* governance before display; an
# artifact that cannot be resolved or authorized is shown as blocked, never
# rendered as an official curve (fail closed).

_CURVE_SERVICE = CurveService()


def _official_artifact_governance(
    artifact,
    current_identity,
    approval_dict,
    current_policy,
    current_readiness,
    current_diagnostics_artefact,
    activity_definitions,
    outcome_definitions,
    outcome_approvals,
):
    """Resolve current governance for one official artifact.

    Thin call-through to ``CurveService.resolve_current_governance`` (the
    shared resolution path also used by the Project Export page's
    report/Excel authorization-status exposure) - kept as a page-local
    wrapper only to avoid touching every call site above.
    """
    return _CURVE_SERVICE.resolve_current_governance(
        artifact,
        current_identity=current_identity,
        approval_dict=approval_dict,
        current_policy=current_policy,
        current_readiness=current_readiness,
        current_diagnostics_artefact=current_diagnostics_artefact,
        activity_definitions=activity_definitions,
        outcome_definitions=outcome_definitions,
        outcome_approvals=outcome_approvals,
    )


def _render_official_artifact_curves(artifact):
    """Render the incremental-response curve (posterior mean + credible
    interval) for one official artifact.

    Corrective PR D1: sums component rows (direct + cross-product) within
    each posterior_draw first, then computes the mean/interval across
    draw-level totals - never a flat mean straight across every component
    and draw row combined, which understates the true channel-total
    response by roughly the number of distinct component_type/
    posterior_draw combinations folded together (direct and cross-product
    response are additive, so summing then averaging is correct; averaging
    first is not).
    """
    draws = artifact.draws
    x_col = resolve_curve_axis_column(draws)
    required = {"incremental_response", "market", "channel", "posterior_draw"}
    if draws.empty or x_col is None or not required.issubset(draws.columns):
        st.caption(
            "This artifact does not carry plottable incremental-response curves "
            "(missing market/channel/spend/response/posterior_draw columns)."
        )
        return
    outcome_snapshot = artifact.metadata.outcome_definition_snapshot or {}
    outcome_id = outcome_snapshot.get("outcome_id")
    definition_version = outcome_snapshot.get("definition_version")
    support_rows = (artifact.metadata.support_snapshot or {}).get("rows") or []
    summaries = artifact.summaries
    for (market, channel), group in draws.groupby(["market", "channel"]):
        stats = summarize_component_response_by_draw(
            group, by=[], x_col=x_col
        ).sort_values(x_col)
        title = f"Official curve - {market} / {channel} - {outcome_id}"
        if definition_version:
            title += f" (v{definition_version})"
        curve_type = (
            str(group["curve_type"].iloc[0])
            if "curve_type" in group.columns and not group.empty
            else "model_input"
        )
        economics_row = None
        if (
            summaries is not None
            and not summaries.empty
            and {"market", "channel"}.issubset(summaries.columns)
        ):
            econ_rows = summaries[
                (summaries["market"] == market) & (summaries["channel"] == channel)
            ]
            if not econ_rows.empty:
                economics_row = econ_rows.iloc[0].to_dict()
        annotation = annotation_from_official_support(
            support_rows,
            market,
            channel,
            curve_type=curve_type,
            economics_row=economics_row,
        )
        st.plotly_chart(
            create_annotated_response_curve(
                stats[x_col].to_numpy(dtype=float),
                stats["posterior_mean"].to_numpy(dtype=float),
                title,
                lower_values=stats["lower_interval"].to_numpy(dtype=float),
                upper_values=stats["upper_interval"].to_numpy(dtype=float),
                current_x=annotation.current_x,
                observed_min=annotation.observed_min,
                observed_max=annotation.observed_max,
                annotation_lines=annotation.annotation_lines(),
                # Corrective PR E2.4: an official model-input curve's axis
                # is a governed media-input unit (TVRs, impressions,
                # clicks, ...), never spend - resolved from this artifact's
                # own evidence, never hard-coded or inferred from the
                # chart function's name.
                x_axis_label=resolve_curve_axis_label(x_col, group),
            ),
            width="stretch",
        )
        if annotation.monetary_blocked and annotation.monetary_blocked_reason:
            st.caption(annotation.monetary_blocked_reason)


def _render_official_artifact(
    artifact,
    current_identity,
    approval_dict,
    current_policy,
    current_readiness,
    current_diagnostics_artefact,
    activity_definitions,
    outcome_definitions,
    outcome_approvals,
):
    """Render one official artifact, revalidated against current governance."""
    md = artifact.metadata
    st.markdown(f"#### Artifact `{md.artifact_id}`")
    governance = _official_artifact_governance(
        artifact,
        current_identity,
        approval_dict,
        current_policy,
        current_readiness,
        current_diagnostics_artefact,
        activity_definitions,
        outcome_definitions,
        outcome_approvals,
    )
    if governance is None:
        st.warning(
            "Current governance for this artifact cannot be resolved (missing "
            "current model identity, model approval, or a matching current outcome "
            "approval). It is **not** displayed as an official curve (fail closed)."
        )
        return
    try:
        authorization = _CURVE_SERVICE.authorize_use(
            artifact, "headline_reporting", current_governance=governance
        )
    except CurveGovernanceError as exc:
        st.warning(f"Not currently authorized for headline reporting: {exc}")
        return
    if not authorization.authorized:
        st.warning(
            f"Not currently authorized for headline reporting: {authorization.reason}"
        )
        return
    planning_support = (
        bool(artifact.draws["planning_support_eligible"].all())
        if (
            not artifact.draws.empty
            and "planning_support_eligible" in artifact.draws.columns
        )
        else "n/a"
    )
    meta_df = pd.DataFrame(
        [
            {
                "artifact_id": md.artifact_id,
                "created": md.creation_timestamp,
                "schema_version": md.schema_version,
                "outcome": (md.outcome_definition_snapshot or {}).get("outcome_id"),
                "reference_context_id": (md.reference_context_snapshot or {}).get(
                    "reference_context_id"
                ),
                "format_status": md.format_status,
                "historical_integrity": md.historical_integrity,
                "current_authorization": (authorization.current_authorization_status),
                "requested_use_eligibility": (authorization.requested_use_eligibility),
                "planning_support_eligible": planning_support,
                # Corrective PR D4/D5: the governed context REQ-CURVE-001
                # requires alongside a rendered official curve, beyond bare
                # artifact_id/outcome_id - already captured in the
                # artifact's own creation-time snapshots, just not
                # previously surfaced here.
                **governed_context_fields(md),
            }
        ]
    )
    st.dataframe(
        meta_df,
        width="stretch",
        column_config=dataframe_column_config(meta_df),
    )
    _render_official_artifact_curves(artifact)


def _render_official_artifact_section(
    current_identity,
    approval_dict,
    current_policy,
    current_readiness,
    current_diagnostics_artefact,
    activity_definitions,
    outcome_definitions,
    outcome_approvals,
):
    """Render the official curve artifact store section (fail closed)."""
    st.markdown("---")
    with SectionCard(
        "Official curve artifacts",
        description=(
            "The governed official response-curve artifact store. "
            "Each artifact is revalidated against current governance at display "
            "time (curve_publication approval, current model, outcome, and "
            "activities). Legacy point-estimate curves - a structurally distinct "
            "concept, never blended with these - remain available in the "
            "exploratory viewers above and the curve bank below."
        ),
    ):
        store_dir = curve_artifact_store_dir()
        try:
            load_result = load_curve_artifact_store(store_dir, raise_on_malformed=False)
        except CurveArtifactError as exc:
            st.warning(f"Official curve artifact store could not be read: {exc}")
            return
        if load_result.malformed:
            st.warning(
                f"{len(load_result.malformed)} malformed or unsupported official "
                "curve artifact(s) were found and are reported below - they are "
                "never silently skipped."
            )
            with st.expander("Show malformed-artifact audit"):
                audit_df = pd.DataFrame(
                    [
                        {
                            "artifact_dir": str(e.artifact_dir),
                            "status": e.status,
                            "error": e.error,
                        }
                        for e in load_result.malformed
                    ]
                )
                st.dataframe(
                    audit_df,
                    width="stretch",
                    column_config=dataframe_column_config(audit_df),
                )
        if not load_result.loaded:
            st.info(
                "No official curve artifacts exist for this project yet. Official "
                "curves are produced through the governance-enforcing CurveService "
                f"and stored in `{store_dir}`."
            )
            return
        for artifact in load_result.loaded:
            _render_official_artifact(
                artifact,
                current_identity,
                approval_dict,
                current_policy,
                current_readiness,
                current_diagnostics_artefact,
                activity_definitions,
                outcome_definitions,
                outcome_approvals,
            )


trace = get_state("trace")
frame = get_state("frame")
meta = get_state("model_meta")
params = get_state("posterior_params")
spec_dict = get_state("model_spec")
activity_definitions = [
    ActivityDefinition.from_dict(item)
    for item in (get_state("activity_definitions") or [])
]
search_objects = [
    SearchObjectDefinition.from_dict(item)
    for item in (get_state("search_objects") or [])
]
coverage_matrix_dict = get_state("variable_coverage_matrix")
if trace is None or frame is None or meta is None or params is None:
    st.markdown("---")
    render_empty_state(
        "No fitted model yet. Complete Fit Model first.",
        button_label="Go to Fit Model",
        target_key="model_training",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
ltv = spec.segment_ltv
render_drift_status(
    resolve_outcome_definitions(
        get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv
    ),
    meta,
)
model_type = get_state("model_type", "shared")
market_config = MarketSpecConfig.from_dict(get_state("market_spec_config"))

st.markdown("### Contribution summary")

if model_type == "market_specific":
    st.markdown("---")
    with st.spinner("Computing market-aware Shapley contributions..."):
        ms_contributions = compute_shapley_contributions_market_specific(
            frame, meta, params, n_permutations=100
        )

    st.markdown("#### Total contribution by channel")
    fh_gsa_ids = fh_gsa_outcome_ids(meta)
    fh_signup_ids = fh_signup_outcome_ids(meta)
    dna_kit_outcomes_in_fit = dna_kit_sale_outcome_ids(meta)
    if dna_kit_outcomes_in_fit or fh_signup_ids:
        st.caption(
            f"Total impact per channel across FH GSA outcomes only ({', '.join(fh_gsa_ids) or '(none)'}) - "
            f"FH sign-up outcomes ({', '.join(fh_signup_ids) or '(none)'}) and DNA-product outcomes "
            f"({', '.join(dna_kit_outcomes_in_fit) or '(none)'}) are excluded from this total since a "
            "sign-up count, a kit-sale count and a GSA count aren't the same unit; see their own rows "
            "in the market x outcome x channel detail below."
        )
    else:
        st.caption(
            "Total impact per channel across all markets and outcomes, plus LTV-weighted value."
        )
    by_market_total = st.checkbox("Break totals out by market", value=False)
    ms_total_df = total_contribution_market_specific(
        frame,
        meta,
        params,
        ms_contributions,
        ltv,
        outcome_ids=fh_gsa_ids,
        by_market=by_market_total,
    )
    st.dataframe(
        ms_total_df, width="stretch", column_config=dataframe_column_config(ms_total_df)
    )

    st.markdown("---")
    st.markdown("#### Market x segment x channel detail")
    ms_seg_df = outcome_channel_market_summary(
        frame, meta, params, ms_contributions, ltv
    )
    st.dataframe(
        ms_seg_df, width="stretch", column_config=dataframe_column_config(ms_seg_df)
    )

    st.markdown("---")
    st.markdown("#### Contribution waterfall")
    c1, c2 = st.columns(2)
    waterfall_market = c1.selectbox("Market", meta.markets, key="ms_waterfall_market")
    waterfall_scope = c2.selectbox(
        "Scope", ["Total FH"] + meta.outcome_ids, key="ms_waterfall_scope"
    )
    outcome_id_arg = None if waterfall_scope == "Total FH" else waterfall_scope
    market_row_mask = ms_contributions["market_idx"] == meta.markets.index(
        waterfall_market
    )
    market_contributions = {
        "baseline": ms_contributions["baseline"][market_row_mask],
        "channel_contributions": {
            ch: arr[market_row_mask]
            for ch, arr in ms_contributions["channel_contributions"].items()
        },
        "mu_total": ms_contributions["mu_total"][market_row_mask],
    }
    # `contributions` is always given below, so `frame` is unused by
    # contribution_waterfall in that path - passed only to satisfy its signature.
    waterfall_df = contribution_waterfall(
        frame,
        meta,
        params,
        outcome_id=outcome_id_arg,
        contributions=market_contributions,
    )
    st.plotly_chart(
        create_waterfall_chart(
            waterfall_df["category"].tolist(),
            waterfall_df["value"].tolist(),
            title=f"{waterfall_market} - {waterfall_scope} contribution waterfall",
        ),
        width="stretch",
    )

    st.markdown("---")
    st.markdown("### Response curve library")
    st.caption(
        "Selected context: choose one market and channel below. This viewer is exploratory "
        "evidence from the fitted model; it is not an official published curve artifact."
    )
    st.markdown("#### Market-specific channel response curve")
    st.caption(
        "Exploratory / legacy (point estimates): spend -> incremental response for one "
        "market and channel, per segment and overall (overall = sum of segment responses). "
        "These curves are not part of the governed official artifact store - use the "
        "Official curve artifacts section for governed curves."
    )
    c1, c2 = st.columns(2)
    viewer_market = c1.selectbox("Market", meta.markets)
    viewer_channel = c2.selectbox("Channel", meta.channels)

    show_uncertainty = st.checkbox(
        "Show posterior uncertainty band (re-runs the curve once per sampled draw - slower)",
        value=False,
        key="ms_curve_uncertainty",
    )
    if show_uncertainty:
        n_draws = st.slider(
            "Posterior draws to sample", 20, 200, 50, step=10, key="ms_curve_n_draws"
        )
        with st.spinner(
            f"Computing curve uncertainty from {n_draws} posterior draws..."
        ):
            band_df = generate_market_channel_curve_with_uncertainty(
                viewer_market,
                viewer_channel,
                meta,
                trace,
                n_draws=n_draws,
            )
        st.plotly_chart(
            create_response_curve_with_band(
                band_df["spend"].to_numpy(),
                band_df["overall_response_mean"].to_numpy(),
                band_df["overall_response_lower"].to_numpy(),
                band_df["overall_response_upper"].to_numpy(),
                f"{viewer_market} - {viewer_channel}",
            ),
            width="stretch",
        )
        st.caption(
            f"Shaded band = 90% credible interval across {n_draws} sampled posterior draws "
            "This is a subsample of the full posterior for speed, not the full "
            "posterior itself."
        )
        st.dataframe(
            band_df, width="stretch", column_config=dataframe_column_config(band_df)
        )
        curve_df = generate_market_channel_curve(
            viewer_market, viewer_channel, meta, params
        )
    else:
        curve_df = generate_market_channel_curve(
            viewer_market, viewer_channel, meta, params
        )
        try:
            _viewer_evidence_tier = classify_market_evidence(
                trace, frame, meta, viewer_market, viewer_channel
            )
        except (KeyError, ValueError):
            _viewer_evidence_tier = None
        _viewer_channel_idx = meta.channels.index(viewer_channel)
        _viewer_market_mask = frame["df"][spec.market_col] == viewer_market
        _viewer_spend_history = frame["X_media"][
            _viewer_market_mask.to_numpy(), _viewer_channel_idx
        ].tolist()
        _render_curve_with_cpa(
            curve_df,
            f"{viewer_market} - {viewer_channel}",
            spend_history=_viewer_spend_history,
            status_label=_viewer_evidence_tier,
        )
        st.dataframe(
            curve_df, width="stretch", column_config=dataframe_column_config(curve_df)
        )

    st.markdown("---")
    st.markdown("#### Media units & inflation")
    _render_media_unit_section(curve_df, market_config, viewer_market, viewer_channel)

    st.markdown("---")
    st.markdown("#### Cross-product pathway strength")
    st.caption(
        "Shared across markets in this model structure (only K and beta are market-specific). "
        "Estimated multiplier for each active/exploratory cross-product (outcome, channel) cell "
        "(core.pathways.resolve_pathway_masks) - generalises the old DNA-only halo pathway to any "
        "channel a pathway catalogue routes there."
    )
    pathway_df = _pathway_strength_table(meta, params)
    st.dataframe(
        pathway_df, width="stretch", column_config=dataframe_column_config(pathway_df)
    )

else:
    st.markdown("---")
    with st.spinner("Computing Shapley contributions..."):
        contributions = compute_shapley_contributions(
            frame, meta, params, n_permutations=100
        )

    st.markdown("#### Total-FH contribution by channel")
    fh_gsa_ids = fh_gsa_outcome_ids(meta)
    fh_signup_ids = fh_signup_outcome_ids(meta)
    dna_kit_outcomes_in_fit = dna_kit_sale_outcome_ids(meta)
    if dna_kit_outcomes_in_fit or fh_signup_ids:
        st.caption(
            f"Total impact per FH channel across FH GSA outcomes only ({', '.join(fh_gsa_ids) or '(none)'}) - "
            f"FH sign-up outcomes ({', '.join(fh_signup_ids) or '(none)'}) and DNA-product outcomes "
            f"({', '.join(dna_kit_outcomes_in_fit) or '(none)'}) are excluded from this total since a "
            "sign-up count, a kit-sale count and a GSA count aren't the same unit; see their own rows "
            "in the outcome x channel detail below."
        )
    else:
        st.caption(
            "Total impact per channel across all outcomes, plus which outcome that impact falls into and LTV-weighted value."
        )
    total_df = total_fh_contribution(
        frame, meta, params, contributions, ltv, outcome_ids=fh_gsa_ids
    )
    st.dataframe(
        total_df, width="stretch", column_config=dataframe_column_config(total_df)
    )

    st.markdown("---")
    st.markdown("#### Outcome x channel detail")
    seg_df = outcome_channel_summary(frame, meta, params, contributions, ltv)
    st.dataframe(seg_df, width="stretch", column_config=dataframe_column_config(seg_df))

    st.markdown("---")
    st.markdown("#### Contribution waterfall")
    waterfall_scope = st.selectbox("Scope", ["Total FH"] + meta.outcome_ids)
    outcome_id_arg = None if waterfall_scope == "Total FH" else waterfall_scope
    waterfall_df = contribution_waterfall(
        frame, meta, params, outcome_id=outcome_id_arg, contributions=contributions
    )
    st.plotly_chart(
        create_waterfall_chart(
            waterfall_df["category"].tolist(),
            waterfall_df["value"].tolist(),
            title=f"{waterfall_scope} contribution waterfall",
        ),
        width="stretch",
    )

    st.markdown("---")
    st.markdown("### Response curve library")
    st.caption(
        "Selected context: choose a channel and reference market below. This viewer is "
        "exploratory evidence from the fitted model; official published curve artifacts "
        "are shown separately below."
    )
    st.markdown("#### Channel response curve")
    st.caption(
        "Exploratory / legacy (point estimates): spend -> incremental response for one "
        "channel, per segment and overall (overall = sum of segment responses) - the same "
        "curve every market uses, since it's shared across markets in this model structure. "
        "These curves are not part of the governed official artifact store - use the "
        "Official curve artifacts section for governed curves."
    )
    viewer_channel = st.selectbox("Channel", meta.channels)

    show_uncertainty = st.checkbox(
        "Show posterior uncertainty band (re-runs the curve once per sampled draw - slower)",
        value=False,
        key="shared_curve_uncertainty",
    )
    if show_uncertainty:
        n_draws = st.slider(
            "Posterior draws to sample",
            20,
            200,
            50,
            step=10,
            key="shared_curve_n_draws",
        )
        with st.spinner(
            f"Computing curve uncertainty from {n_draws} posterior draws..."
        ):
            band_df = generate_channel_curve_with_uncertainty(
                viewer_channel, meta, trace, n_draws=n_draws
            )
        st.plotly_chart(
            create_response_curve_with_band(
                band_df["spend"].to_numpy(),
                band_df["overall_response_mean"].to_numpy(),
                band_df["overall_response_lower"].to_numpy(),
                band_df["overall_response_upper"].to_numpy(),
                viewer_channel,
            ),
            width="stretch",
        )
        st.caption(
            f"Shaded band = 90% credible interval across {n_draws} sampled posterior draws "
            "This is a subsample of the full posterior for speed, not the full "
            "posterior itself."
        )
        st.dataframe(
            band_df, width="stretch", column_config=dataframe_column_config(band_df)
        )
        curve_df = generate_channel_curve(viewer_channel, meta, params)
    else:
        curve_df = generate_channel_curve(viewer_channel, meta, params)
        _viewer_channel_idx = meta.channels.index(viewer_channel)
        # Shared curve = shared across every market by construction (see
        # docs/decision_log.md's CURVE_STATUS_SHARED decision), so "current"
        # and observed support are the historical average/range across every
        # fitted market's data for this channel, not one market's.
        _viewer_spend_history = frame["X_media"][:, _viewer_channel_idx].tolist()
        _render_curve_with_cpa(
            curve_df,
            viewer_channel,
            spend_history=_viewer_spend_history,
            status_label=cb.CURVE_STATUS_SHARED,
        )
        st.dataframe(
            curve_df, width="stretch", column_config=dataframe_column_config(curve_df)
        )

    st.markdown("---")
    st.markdown("#### Media units & inflation")
    st.caption(
        "Cost-per-unit history is inherently market-specific, even though the curve above is shared "
        "across markets - choose a reference market to see its own cost data."
    )
    viewer_market = st.selectbox("Reference market (for cost data)", meta.markets)
    _render_media_unit_section(curve_df, market_config, viewer_market, viewer_channel)

    st.markdown("---")
    st.markdown("#### Cross-product pathway strength")
    pathway_df = _pathway_strength_table(meta, params)
    st.dataframe(
        pathway_df, width="stretch", column_config=dataframe_column_config(pathway_df)
    )
    st.caption(
        "Estimated multiplier for each active/exploratory cross-product (outcome, channel) cell "
        "(core.pathways.resolve_pathway_masks) - shrunk toward zero by prior default (tighter for "
        "exploratory cells) and only pulled away from zero where the data supports it. A "
        "primary_direct cell (e.g. the DNA cross-sell outcome's own direct pathway from DNA media) "
        "isn't shown here - it's fixed at full weight (beta itself), not a separate strength "
        "multiplier."
    )

# --- Curve bank: available for both model types - a market-
# specific fit saves one set of curves per market, each labelled with its
# own evidence tier (docs/market_hierarchy.md section 4); a shared-curve
# fit saves one set of curves labelled "Shared". Media-unit curve entries
# are only auto-saved for a market-specific fit - a shared
# curve's cost-per-unit context is inherently market-specific, so there's
# no single market to attribute it to at save time (see docs/decision_log.md);
# the viewer above still shows media-unit context for a chosen reference
# market, it just isn't persisted to the curve bank for a shared curve.
st.markdown("---")
st.markdown("## Curve bank snapshots")
st.caption(FIELD_HELP["curve_bank"])
st.caption(
    "Curve bank entries are **fitted parameter snapshots** (Hill/decay/beta "
    "point estimates for one market/channel/segment), not evaluated curves. "
    "They remain loadable and usable for calibration tracking and "
    "evidence-tier display, but are never presented as current official "
    "response curves - official curves are rendered only in the "
    "'Official curve artifacts' section."
)
approval_dict = get_state("model_approval")
model_run_id = get_state("model_run_id")
prior_config = get_state("prior_config") or {}
dna_lag_weeks = get_state("dna_lag_weeks", 4)

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
            direct_dna_outcome_ids=meta.direct_dna_outcome_ids
            if meta is not None
            else None,
            outcome_catalogue=outcome_catalogue_fingerprint_payload(
                meta.outcome_catalogue_at_fit
            )
            if meta is not None
            else None,
            funnel_links=get_state("funnel_links"),
            media_outcome_pathways=pathway_catalogue_fingerprint_payload(
                meta.pathway_catalogue_at_fit
            )
            if meta is not None
            else None,
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
            variable_coverage_fingerprint=(
                VariableCoverageMatrix.from_dict(coverage_matrix_dict).fingerprint()
                if coverage_matrix_dict
                else None
            ),
        ),
        "posterior_fingerprint": fingerprint_posterior(params),
    }

# PR 88A: routed through the shared fail-closed loaders (also used by
# Diagnostics, Scenario Planner, and Project Import) - a malformed policy or
# stored readiness is reported and treated as absent, never left to raise an
# uncaught TypeError/KeyError/AttributeError out of this page.
_validation_policy_dict = get_state("validation_policy")
current_policy, _policy_config_error = load_threshold_policy(_validation_policy_dict)
if _policy_config_error:
    st.warning(
        "The configured validation policy is malformed and cannot be used: "
        f"{_policy_config_error}"
    )

_approval_readiness_dict = get_state("approval_readiness")
current_readiness, _readiness_config_error = load_approval_readiness(
    _approval_readiness_dict
)
if _readiness_config_error:
    st.warning(
        f"The stored approval readiness is malformed and cannot be used: "
        f"{_readiness_config_error}"
    )

# REQ-CURVE-001 Work package A: OfficialCurveGovernance now requires a
# diagnostics_artefact (previously optional). Sourced the same way the
# Diagnostics page (06) leaves it in session state - not a dict, the
# DiagnosticsArtefact object itself. Absent here simply means official
# artifacts fail closed at the authorize_use gate below (never an uncaught
# error out of this page).
current_diagnostics_artefact = st.session_state.get("diagnostics_artefact")

# PR 82F: require_matching_approval (already enforced by cb.make_entries
# itself) re-verifies the FULL chain - model identity AND, for
# policy-backed approvals, that the bound readiness still exists, is
# still overall_ready, and its policy/model-identity fingerprints still
# match the current policy and model - not just model identity alone.
# This is strictly stronger than (and replaces) the bare
# matches_current_model() check this page used before, so an approval can
# no longer be displayed as valid here while cb.make_entries would
# actually reject it below (matching the PR 82B fix on Diagnostics).
approval_matches_current = False
approval_invalid_reason: str | None = None
if approval_dict is not None and current_identity is not None:
    try:
        require_matching_approval(
            ModelApproval.from_dict(approval_dict),
            approval_readiness=current_readiness,
            current_policy=current_policy,
            **current_identity,
        )
        approval_matches_current = True
    except (ApprovalMismatchError, ValidationPolicyBlockedError) as exc:
        approval_invalid_reason = str(exc)

if not approval_dict:
    st.markdown("---")
    render_empty_state(
        "This model hasn't been approved yet. Results above are still visible for review, but "
        "saving to the curve bank is blocked until the model is approved on Model Diagnostics.",
        button_label="Go to Model Diagnostics",
        target_key="diagnostics",
    )
elif not approval_matches_current:
    st.markdown("---")
    render_empty_state(
        "This model's approval no longer matches the current fitted model, policy, or "
        "readiness evidence (the data, specification, posterior, or run have changed since "
        "it was approved, or the bound policy/readiness has drifted)"
        + (f": {approval_invalid_reason}" if approval_invalid_reason else "")
        + ". Saving to the curve bank is blocked until it's reviewed and approved again.",
        button_label="Go to Model Diagnostics",
        target_key="diagnostics",
    )
else:
    approval = ModelApproval.from_dict(approval_dict)
    st.caption(
        f"Model approved by **{approval.approved_by}** - saving to the curve bank will record this approval on every curve entry (fitted parameter snapshot) saved."
    )

    c1, c2 = st.columns(2)
    run_label = c1.text_input(
        "Run label *", value=f"{spec.markets and spec.markets[0] or 'run'}-v1"
    )
    notes = c2.text_input("Notes (optional)")

    if st.button("Save current curves to curve bank", type="primary"):
        data_window = (
            str(pd.Timestamp(frame["dates"].min()).date()),
            str(pd.Timestamp(frame["dates"].max()).date()),
        )
        try:
            if model_type == "market_specific":
                with st.spinner("Classifying market evidence tiers..."):
                    evidence_tiers = classify_all_markets(trace, frame, meta)
                currency_by_market = {
                    m: market_config.get_profile(m).currency.local_currency
                    for m in meta.markets
                    if market_config.get_profile(m).currency.local_currency
                }
                entries = cb.make_entries(
                    meta,
                    params,
                    data_window,
                    run_label,
                    approval,
                    model_type=model_type,
                    evidence_tiers=evidence_tiers,
                    currency_by_market=currency_by_market,
                    notes=notes,
                    approval_readiness=current_readiness,
                    current_policy=current_policy,
                    **current_identity,
                )
                media_unit_info = {}
                for m in meta.markets:
                    for ch in meta.channels:
                        cfg = market_config.get_media_unit_config(m, ch)
                        if not (cfg and cfg.has_media_unit()):
                            continue
                        try:
                            cost_df = extract_cost_per_unit_series(
                                frame["df"], spec.date_col, spec.market_col, m, cfg
                            )
                            trend = historical_cost_trend(cost_df, spec.date_col)
                        except ValueError:
                            continue
                        if trend["avg_cost_per_unit"] is None:
                            continue
                        media_unit_info[(m, ch)] = {
                            "unit_type": cfg.unit_type,
                            "currency": cfg.currency or currency_by_market.get(m),
                            "avg_cost_per_unit": trend["avg_cost_per_unit"],
                        }
                if media_unit_info:
                    entries = entries + cb.make_media_unit_entries(
                        entries, media_unit_info
                    )
            else:
                entries = cb.make_entries(
                    meta,
                    params,
                    data_window,
                    run_label,
                    approval,
                    model_type=model_type,
                    notes=notes,
                    approval_readiness=current_readiness,
                    current_policy=current_policy,
                    **current_identity,
                )
        except (ApprovalMismatchError, ValidationPolicyBlockedError) as e:
            st.error(f"Could not save to the curve bank: {e}")
        else:
            paths = cb.save_entries(curve_bank_dir(), entries)
            set_state("curve_bank_entry_id", entries[0].entry_id if entries else None)
            st.success(
                f"Saved {len(entries)} curve bank entries to {curve_bank_dir()}."
            )

# Official curve artifacts (REQ-CURVE-001 / PR 95E) - rendered after the
# legacy curve bank save block so that current_identity / current_policy /
# current_readiness are already available; the section itself is fail-closed.
_render_official_artifact_section(
    current_identity,
    approval_dict,
    current_policy,
    current_readiness,
    current_diagnostics_artefact,
    activity_definitions,
    resolve_outcome_definitions(
        get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv
    ),
    [OutcomeApproval.from_dict(d) for d in (get_state("outcome_approvals") or [])],
)

entries = cb.load_all_entries(curve_bank_dir())
if entries:
    st.markdown("#### Curve bank history")
    entries_df = cb.entries_to_dataframe(entries)

    f1, f2, f3, f4 = st.columns(4)
    market_filter = f1.multiselect(
        "Filter: market", sorted(entries_df["market"].unique())
    )
    channel_filter = f2.multiselect(
        "Filter: channel", sorted(entries_df["channel"].unique())
    )
    segment_filter = f3.multiselect(
        "Filter: segment", sorted(entries_df["segment_or_overall"].unique())
    )
    status_filter = f4.multiselect(
        "Filter: curve status", sorted(entries_df["curve_status"].unique())
    )

    filtered_df = entries_df
    if market_filter:
        filtered_df = filtered_df[filtered_df["market"].isin(market_filter)]
    if channel_filter:
        filtered_df = filtered_df[filtered_df["channel"].isin(channel_filter)]
    if segment_filter:
        filtered_df = filtered_df[
            filtered_df["segment_or_overall"].isin(segment_filter)
        ]
    if status_filter:
        filtered_df = filtered_df[filtered_df["curve_status"].isin(status_filter)]

    st.dataframe(
        filtered_df, width="stretch", column_config=dataframe_column_config(filtered_df)
    )
    if entries_df["legacy_approval"].any():
        st.caption(
            "Rows marked `legacy_approval = True` were saved before curve bank entries were "
            "bound to a verified model run - their approval could not be checked against a "
            "specific fitted model."
        )
    if entries_df["legacy_format"].any():
        st.caption(
            "Rows marked `legacy_format = True` were saved before curves were stored one-per-market/"
            "channel/segment - each was one shared, run-level record, expanded into this "
            "table's shape for display; their `curve_status` is always `Legacy`."
        )

    st.markdown("#### Log a geo-test / in-platform calibration result")
    entry_options = {
        f"{e.run_label} - {e.market or '(shared)'} / {e.channel} / {e.segment_or_overall} / {e.input_type} "
        f"({e.entry_id[:8]}, {format_date(pd.Timestamp.fromtimestamp(e.created_at))})": e.entry_id
        for e in entries
    }
    chosen_label = st.selectbox("Curve bank entry", list(entry_options.keys()))
    chosen_entry = next(e for e in entries if e.entry_id == entry_options[chosen_label])

    c1, c2 = st.columns(2)
    test_type = c1.selectbox("Test type", ["geo", "in_platform"])
    model_estimate = c2.number_input(
        "Model estimate (e.g. ROAS)", value=float(chosen_entry.beta)
    )
    c1, c2 = st.columns(2)
    test_estimate = c1.number_input("Test estimate", value=0.0)
    tolerance = c2.slider("Agreement tolerance (%)", 5, 100, 25)

    if st.button("Log calibration result"):
        record = cb.record_calibration(
            curve_bank_dir(),
            chosen_entry.entry_id,
            chosen_entry.channel,
            chosen_entry.segment_or_overall,
            test_type,
            model_estimate,
            test_estimate,
            tolerance_pct=tolerance,
        )
        st.success(f"Logged calibration result: **{record.agreement}**")

    calibrations = cb.load_all_calibrations(curve_bank_dir())
    if calibrations:
        st.markdown("#### Calibration history")
        cal_df = cb.calibrations_to_dataframe(calibrations)
        st.dataframe(
            cal_df, width="stretch", column_config=dataframe_column_config(cal_df)
        )
else:
    st.info("No curve bank entries saved yet.")

render_next_step("curve_bank")
