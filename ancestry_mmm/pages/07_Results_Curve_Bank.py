"""Page 7: fitted contribution evidence, response curves, and saved parameter snapshots."""

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
    format_currency,
    format_date,
    format_roi_statement,
    readable_label,
    model_input_display_label,
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
from ancestry_mmm.core.search_intent_taxonomy import (
    search_intent_taxonomy_fit_fingerprint,
)
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.canonical_curves import (
    resolve_curve_axis_column,
    resolve_curve_axis_label,
    summarize_component_response_by_draw,
)
from ancestry_mmm.core.reporting_rollups import (
    ReportingEnrichmentError,
    build_reporting_views,
    roll_up_paid_search_reporting_draws,
    summarize_reporting_draws,
)
from ancestry_mmm.core.outcome_group_totals import reporting_group_options
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
    FH_LTR_HORIZON_MONTHS,
    fh_gsa_outcome_ids,
    fh_signup_outcome_ids,
    dna_kit_sale_outcome_ids,
    outcome_catalogue_fingerprint_payload,
    resolve_outcome_definitions,
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.seo_visibility import seo_fit_inputs_fingerprint
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
from ancestry_mmm.core.coverage import COVERAGE_STATES
from ancestry_mmm.core.outcome_valuation import (
    VALUATION_KIND_DNA_REVENUE,
    VALUATION_KIND_FH_LTR,
    VALUATION_KINDS,
    WeeklyOutcomeValuationRecord,
    validate_weekly_outcome_valuation_catalogue,
)
from ancestry_mmm.core.outcome_valuation_periods import (
    PERIOD_GRAIN_CUSTOM,
    PERIOD_GRAIN_MONTH,
    PERIOD_GRAIN_QUARTER,
    PERIOD_GRAIN_WEEK,
    PERIOD_GRAIN_YEAR,
    distinct_calendar_periods,
)
from ancestry_mmm.core.outcome_valuation_reporting import (
    OutcomeValuationReportingCoverageError,
    available_weeks_for_market,
)
from ancestry_mmm.application.outcome_valuation_reporting_service import (
    HistoricalOutcomeValuationRequest,
    OutcomeValuationReportingService,
)
from ancestry_mmm.application.contribution_waterfall_service import (
    ContributionWaterfallPeriodRequest,
    ContributionWaterfallRequest,
    ContributionWaterfallService,
)
from ancestry_mmm.core.contribution_waterfall import sorted_presented_components


_EFFECT_TYPE_LABELS = {
    "direct": "Direct effect",
    "mediated": "Mediated effect",
    "halo": "Cross-product halo effect",
    "cross_product": "Cross-product effect",
    "interaction": "Residual interaction",
    "total": "Total effect",
}

_REPORTING_VIEW_TABS = (
    "Where in the funnel?",
    "Which channel or supplier?",
    "Which activity?",
)


def _outcome_display_labels(outcome_definitions):
    """Return analyst-readable, versioned outcome labels without changing IDs."""

    def _label(outcome):
        label = " · ".join(
            str(part).strip()
            for part in (outcome.product, outcome.segment, outcome.metric)
            if str(part).strip()
        ) or readable_label(outcome.outcome_id)
        definition_version = str(outcome.definition_version or "").strip()
        if definition_version:
            label += f" (definition {definition_version})"
        return label

    return {outcome.outcome_id: _label(outcome) for outcome in outcome_definitions}


_EV_VALUATION_KIND_LABELS = {
    "Family History (projected LTR)": VALUATION_KIND_FH_LTR,
    "DNA (kit revenue)": VALUATION_KIND_DNA_REVENUE,
}
_EV_GRAIN_LABELS = {
    "Week": PERIOD_GRAIN_WEEK,
    "Month": PERIOD_GRAIN_MONTH,
    "Quarter": PERIOD_GRAIN_QUARTER,
    "Year": PERIOD_GRAIN_YEAR,
    "Custom range": PERIOD_GRAIN_CUSTOM,
}


def _outcome_valuation_editor_df(records):
    columns = [
        "valuation_kind",
        "market",
        "week",
        "segment",
        "denominator_outcome_id",
        "quality_status",
        "aggregate_value",
        "currency",
    ]
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(
        [
            {
                "valuation_kind": r.valuation_kind,
                "market": r.market,
                "week": r.week,
                "segment": r.segment,
                "denominator_outcome_id": r.denominator_outcome_id,
                "quality_status": r.quality_status,
                "aggregate_value": r.aggregate_value,
                "currency": r.currency,
            }
            for r in records
        ]
    )


def _render_outcome_valuation_catalogue_editor(meta, outcome_definitions, records):
    """The governed weekly outcome-valuation catalogue editor
    (REQ-ECON-002). Fail-closed: an edited catalogue is only persisted to
    session state once every row constructs a valid
    `WeeklyOutcomeValuationRecord` AND the whole catalogue passes
    `validate_weekly_outcome_valuation_catalogue` - otherwise the prior,
    already-governed catalogue is left untouched and every issue is
    shown."""
    st.caption(
        "One row per valuation kind / market / week / segment cell. "
        "Family History rows value projected LTR against an approved "
        "outcome (e.g. sign-ups); DNA rows value revenue against an "
        "approved outcome (e.g. kit sales). Leave 'Value' blank only for "
        "a quality status that denotes a genuinely absent value. Family "
        f"History LTR rows always use the approved {FH_LTR_HORIZON_MONTHS}"
        "-month lifetime-value horizon (REQ-OUT-003) - this is applied "
        "automatically, not an editable field."
    )
    edited_df = st.data_editor(
        _outcome_valuation_editor_df(records),
        num_rows="dynamic",
        key="outcome_valuation_records_editor",
        column_config={
            "valuation_kind": st.column_config.SelectboxColumn(
                "Valuation kind", options=list(VALUATION_KINDS), required=True
            ),
            "market": st.column_config.SelectboxColumn(
                "Market", options=list(meta.markets), required=True
            ),
            "week": st.column_config.TextColumn("Week (YYYY-MM-DD)", required=True),
            "segment": st.column_config.TextColumn("Segment", required=True),
            "denominator_outcome_id": st.column_config.SelectboxColumn(
                "Denominator outcome",
                options=list(meta.outcome_ids),
                required=True,
            ),
            "quality_status": st.column_config.SelectboxColumn(
                "Quality status",
                options=list(COVERAGE_STATES),
                required=True,
            ),
            "aggregate_value": st.column_config.NumberColumn("Value", min_value=0.0),
            "currency": st.column_config.TextColumn("Currency (ISO-3)"),
        },
    )
    if st.button("Validate and save catalogue", key="outcome_valuation_save"):
        build_errors: list[str] = []
        candidate_records: list[WeeklyOutcomeValuationRecord] = []
        for idx, row in edited_df.reset_index(drop=True).iterrows():
            if (
                not row.get("valuation_kind")
                or not row.get("market")
                or not row.get("week")
            ):
                continue  # a still-blank new row, not a submitted record
            agg_value = row.get("aggregate_value")
            agg_value = None if pd.isna(agg_value) else float(agg_value)
            currency = row.get("currency")
            currency = None if pd.isna(currency) or not currency else str(currency)
            valuation_kind = str(row["valuation_kind"])
            # REQ-OUT-003 sections 1/6: the FH LTR horizon is a fixed governed
            # fact, not an analyst-typed number - applied automatically so
            # it can never be mistyped or silently omitted. DNA revenue
            # rows carry no horizon concept at all.
            horizon_months = (
                FH_LTR_HORIZON_MONTHS
                if valuation_kind == VALUATION_KIND_FH_LTR
                else None
            )
            try:
                candidate_records.append(
                    WeeklyOutcomeValuationRecord(
                        valuation_kind=valuation_kind,
                        market=str(row["market"]),
                        week=str(row["week"]),
                        segment=str(row["segment"]),
                        denominator_outcome_id=str(row["denominator_outcome_id"]),
                        quality_status=str(row["quality_status"]),
                        aggregate_value=agg_value,
                        currency=currency,
                        horizon_months=horizon_months,
                    )
                )
            except ValueError as exc:
                build_errors.append(f"Row {idx}: {exc}")
        issues = build_errors + validate_weekly_outcome_valuation_catalogue(
            candidate_records, outcome_definitions
        )
        if issues:
            for issue in issues:
                st.error(issue)
        else:
            set_state(
                "outcome_valuation_records",
                [r.to_dict() for r in candidate_records],
            )
            st.success(f"Saved {len(candidate_records)} valuation record(s).")
            st.rerun()


_EV_PERIOD_SELECTOR_UNRESOLVABLE = object()


def _render_period_selector(available_weeks, market, key_prefix, *, columns=None):
    """Shared week/month/quarter/year/custom-range period selector
    (WP2D-ui/WP2E). Returns `(grain, period_label, custom_start,
    custom_end)`, or `_EV_PERIOD_SELECTOR_UNRESOLVABLE` after already
    rendering its own explicit empty state when a calendar grain has no
    periods available for `market` - callers must check for that
    sentinel and return early without rendering anything further.
    `key_prefix` keeps widget keys unique across the single-period view
    and each side of a two-period comparison."""
    c3, c4 = columns or st.columns(2)
    grain_label = c3.selectbox(
        "Period", list(_EV_GRAIN_LABELS), key=f"{key_prefix}_grain"
    )
    grain = _EV_GRAIN_LABELS[grain_label]

    period_label = None
    custom_start = None
    custom_end = None
    if grain == PERIOD_GRAIN_WEEK:
        period_label = c4.selectbox(
            "Week",
            available_weeks,
            index=len(available_weeks) - 1,
            key=f"{key_prefix}_week",
        )
    elif grain == PERIOD_GRAIN_CUSTOM:
        d1, d2 = st.columns(2)
        custom_start = d1.selectbox(
            "From week", available_weeks, key=f"{key_prefix}_custom_start"
        )
        custom_end = d2.selectbox(
            "To week",
            available_weeks,
            index=len(available_weeks) - 1,
            key=f"{key_prefix}_custom_end",
        )
    else:
        period_options = distinct_calendar_periods(available_weeks, grain)
        if not period_options:
            render_empty_state(
                f"No {grain_label.lower()}s are available for market '{market}' yet."
            )
            return _EV_PERIOD_SELECTOR_UNRESOLVABLE
        period_label = c4.selectbox(
            grain_label,
            period_options,
            index=len(period_options) - 1,
            key=f"{key_prefix}_period",
        )
    return grain, period_label, custom_start, custom_end


def _render_economic_valuation_reporting(meta, trace, frame, records):
    """Historical ROI/incremental-value reporting (WP2D-ui). Routes every
    calculation through `OutcomeValuationReportingService` - one join
    path, never a shortcut computed directly in this page."""
    c1, c2 = st.columns(2)
    report_market = c1.selectbox("Market", meta.markets, key="ev_report_market")
    valuation_kind_label = c2.selectbox(
        "Valuation kind",
        list(_EV_VALUATION_KIND_LABELS),
        key="ev_report_kind",
    )
    valuation_kind = _EV_VALUATION_KIND_LABELS[valuation_kind_label]

    segment_options = sorted(
        {
            r.segment
            for r in records
            if r.market == report_market and r.valuation_kind == valuation_kind
        }
    )
    if not segment_options:
        render_empty_state(
            f"No governed '{valuation_kind_label}' valuation records for "
            f"market '{report_market}' yet - add catalogue rows above for "
            "this market and valuation kind before reporting ROI."
        )
        return
    report_segment = st.selectbox("Segment", segment_options, key="ev_report_segment")

    denominator_ids = sorted(
        {
            r.denominator_outcome_id
            for r in records
            if r.market == report_market
            and r.valuation_kind == valuation_kind
            and r.segment == report_segment
        }
    )

    try:
        available_weeks = available_weeks_for_market(frame, meta, report_market)
    except OutcomeValuationReportingCoverageError as exc:
        st.error(str(exc))
        return

    period_selection = _render_period_selector(
        available_weeks, report_market, "ev_report"
    )
    if period_selection is _EV_PERIOD_SELECTOR_UNRESOLVABLE:
        return
    grain, period_label, custom_start, custom_end = period_selection

    st.markdown("#### Reporting dimension")
    dim1, dim2 = st.columns(2)
    dimension = dim1.radio(
        "Break out by",
        ["Total (all media)", "Single channel"],
        key="ev_report_dimension",
    )
    channel = None
    if dimension == "Single channel":
        channel = dim2.selectbox("Channel", meta.channels, key="ev_report_channel")
    st.caption(
        "Funnel-stage breakdown is not yet available for economic "
        "reporting - only Total and single-channel views are currently "
        "governed (REQ-ECON-003/004)."
    )

    request = HistoricalOutcomeValuationRequest(
        market=report_market,
        grain=grain,
        trace=trace,
        frame=frame,
        meta=meta,
        outcome_ids=denominator_ids,
        segment=report_segment,
        valuation_kind=valuation_kind,
        weekly_valuation_records=records,
        channel=channel,
        period_label=period_label,
        custom_range_start=custom_start,
        custom_range_end=custom_end,
    )
    with st.spinner("Computing posterior incremental value..."):
        result = OutcomeValuationReportingService().evaluate_period(request)

    _render_valuation_result(result)


def _render_valuation_result(result, *, heading=None, key_suffix=""):
    """Shared single-period result card (WP2D-ui/WP2E): resolved-week
    disclosure, headline metrics, and a posterior-uncertainty detail
    expander. Reused for the single-period view and for each side of a
    two-period comparison so both present the identical governed
    numbers, never a second formatting/rounding path."""
    if heading:
        st.markdown(f"**{heading}**")
    if result.errors:
        for error in result.errors:
            st.error(error)
        return

    attribution = result.attribution
    st.caption(
        f"{len(result.resolved_weeks)} week(s) covered: "
        f"{result.resolved_weeks[0]} to {result.resolved_weeks[-1]}."
    )
    m1, m2, m3 = st.columns(3)
    m1.metric(
        "Incremental value",
        format_currency(attribution.incremental_value_mean, attribution.currency),
    )
    m2.metric(
        "Attributable spend",
        format_currency(attribution.spend, attribution.currency)
        if attribution.spend is not None
        else "-",
    )
    roi_statement = format_roi_statement(attribution.roi_mean, attribution.currency)
    m3.metric("ROI", roi_statement if roi_statement else "Not available")

    with st.expander("Posterior uncertainty and detail", key=f"ev_detail{key_suffix}"):
        st.write(
            f"{attribution.credible_mass:.0%} credible interval: "
            f"{format_currency(attribution.incremental_value_lower, attribution.currency)} "
            f"to {format_currency(attribution.incremental_value_upper, attribution.currency)} "
            f"({attribution.incremental_value_n_draws} posterior draws)."
        )
        if attribution.roi_mean is not None:
            st.write(
                f"ROI {attribution.credible_mass:.0%} credible interval: "
                f"{attribution.roi_lower:.2f}x to {attribution.roi_upper:.2f}x."
            )
        else:
            st.caption(
                "ROI is not shown - attributable spend for this selection "
                "is zero or unavailable."
            )


def _render_metric_comparison_row(label, comparison, currency, *, is_roi=False):
    if comparison is None:
        st.write(f"{label}: not available for both periods.")
        return
    formatter = (
        (lambda v: format_roi_statement(v, currency) or "Not available")
        if is_roi
        else (lambda v: format_currency(v, currency))
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{label} - Period A", formatter(comparison.period_a_value))
    c2.metric(f"{label} - Period B", formatter(comparison.period_b_value))
    c3.metric(f"{label} - change", formatter(comparison.absolute_change))
    if comparison.percentage_change is not None:
        c4.metric(f"{label} - % change", f"{comparison.percentage_change:+.1%}")
    else:
        c4.metric(f"{label} - % change", "Not available")
        c4.caption(comparison.percentage_change_unavailable_reason or "")


def _render_period_comparison(meta, trace, frame, records):
    """Explicit two-period comparison (WP2E). Shares the market/
    valuation-kind/segment/dimension selection across both periods -
    only "when", not "what", varies - and routes both periods through
    `OutcomeValuationReportingService.compare_periods()`, which itself
    calls the identical `evaluate_period()` used by the single-period
    view above."""
    c1, c2 = st.columns(2)
    cmp_market = c1.selectbox("Market", meta.markets, key="ev_cmp_market")
    cmp_kind_label = c2.selectbox(
        "Valuation kind", list(_EV_VALUATION_KIND_LABELS), key="ev_cmp_kind"
    )
    cmp_valuation_kind = _EV_VALUATION_KIND_LABELS[cmp_kind_label]

    segment_options = sorted(
        {
            r.segment
            for r in records
            if r.market == cmp_market and r.valuation_kind == cmp_valuation_kind
        }
    )
    if not segment_options:
        render_empty_state(
            f"No governed '{cmp_kind_label}' valuation records for market "
            f"'{cmp_market}' yet - add catalogue rows above before "
            "comparing periods."
        )
        return
    cmp_segment = st.selectbox("Segment", segment_options, key="ev_cmp_segment")

    denominator_ids = sorted(
        {
            r.denominator_outcome_id
            for r in records
            if r.market == cmp_market
            and r.valuation_kind == cmp_valuation_kind
            and r.segment == cmp_segment
        }
    )

    dim1, dim2 = st.columns(2)
    dimension = dim1.radio(
        "Break out by",
        ["Total (all media)", "Single channel"],
        key="ev_cmp_dimension",
    )
    channel = None
    if dimension == "Single channel":
        channel = dim2.selectbox("Channel", meta.channels, key="ev_cmp_channel")

    try:
        available_weeks = available_weeks_for_market(frame, meta, cmp_market)
    except OutcomeValuationReportingCoverageError as exc:
        st.error(str(exc))
        return

    pa_col, pb_col = st.columns(2)
    with pa_col:
        st.markdown("**Period A**")
        selection_a = _render_period_selector(
            available_weeks, cmp_market, "ev_cmp_a", columns=st.columns(2)
        )
    with pb_col:
        st.markdown("**Period B**")
        selection_b = _render_period_selector(
            available_weeks, cmp_market, "ev_cmp_b", columns=st.columns(2)
        )
    if (
        selection_a is _EV_PERIOD_SELECTOR_UNRESOLVABLE
        or selection_b is _EV_PERIOD_SELECTOR_UNRESOLVABLE
    ):
        return
    grain_a, period_label_a, custom_start_a, custom_end_a = selection_a
    grain_b, period_label_b, custom_start_b, custom_end_b = selection_b

    common = dict(
        market=cmp_market,
        trace=trace,
        frame=frame,
        meta=meta,
        outcome_ids=denominator_ids,
        segment=cmp_segment,
        valuation_kind=cmp_valuation_kind,
        weekly_valuation_records=records,
        channel=channel,
    )
    request_a = HistoricalOutcomeValuationRequest(
        grain=grain_a,
        period_label=period_label_a,
        custom_range_start=custom_start_a,
        custom_range_end=custom_end_a,
        **common,
    )
    request_b = HistoricalOutcomeValuationRequest(
        grain=grain_b,
        period_label=period_label_b,
        custom_range_start=custom_start_b,
        custom_range_end=custom_end_b,
        **common,
    )
    with st.spinner("Computing posterior incremental value for both periods..."):
        comparison = OutcomeValuationReportingService().compare_periods(
            request_a, request_b
        )

    pa_col, pb_col = st.columns(2)
    with pa_col:
        _render_valuation_result(
            comparison.period_a, heading="Period A", key_suffix="_cmp_a"
        )
    with pb_col:
        _render_valuation_result(
            comparison.period_b, heading="Period B", key_suffix="_cmp_b"
        )

    if (
        comparison.period_a.attribution is None
        or comparison.period_b.attribution is None
    ):
        return

    st.markdown("#### Change from Period A to Period B")
    currency = comparison.period_a.attribution.currency
    _render_metric_comparison_row(
        "Incremental outcome", comparison.incremental_outcome, currency
    )
    _render_metric_comparison_row(
        "Incremental value", comparison.incremental_value, currency
    )
    _render_metric_comparison_row("Attributable spend", comparison.spend, currency)
    _render_metric_comparison_row("ROI", comparison.roi, currency, is_roi=True)

    st.markdown("#### Contribution waterfall")
    st.caption(
        "How Period A's outcome bridges to Period B's, broken down by "
        "media/channel, seasonality, trend, promotions, and controls "
        "(WP2F). Reuses the same market and periods selected above."
    )
    _render_contribution_waterfall(
        meta,
        trace,
        frame,
        market=cmp_market,
        outcome_ids=denominator_ids,
        period_a=ContributionWaterfallPeriodRequest(
            grain=grain_a,
            period_label=period_label_a,
            custom_range_start=custom_start_a,
            custom_range_end=custom_end_a,
        ),
        period_b=ContributionWaterfallPeriodRequest(
            grain=grain_b,
            period_label=period_label_b,
            custom_range_start=custom_start_b,
            custom_range_end=custom_end_b,
        ),
    )


def _render_contribution_waterfall(
    meta, trace, frame, *, market, outcome_ids, period_a, period_b
):
    """WP2F: the generalised-Shapley period-over-period contribution
    waterfall. Routes every calculation through
    `ContributionWaterfallService` - one bridge-construction path,
    never a shortcut computed directly in this page."""
    request = ContributionWaterfallRequest(
        market=market,
        trace=trace,
        frame=frame,
        meta=meta,
        outcome_ids=outcome_ids,
        period_a=period_a,
        period_b=period_b,
    )
    with st.spinner("Computing the contribution waterfall..."):
        result = ContributionWaterfallService().compute(request)

    if result.errors:
        for error in result.errors:
            st.error(error)
        return

    bridge = result.bridge
    ordered = sorted_presented_components(bridge.components)
    categories = ["Period A"] + [c.component for c in ordered] + ["Period B"]
    values = (
        [bridge.period_a_outcome_mean]
        + [c.bridge_mean for c in ordered]
        + [bridge.period_b_outcome_mean]
    )
    st.plotly_chart(
        create_waterfall_chart(
            categories,
            values,
            title=f"{market} - contribution waterfall",
        ),
        width="stretch",
    )
    with st.expander("Posterior uncertainty by component"):
        detail_df = pd.DataFrame(
            [
                {
                    "Component": c.component,
                    "Period A": c.period_a_mean,
                    "Period B": c.period_b_mean,
                    "Bridge (mean)": c.bridge_mean,
                    f"Bridge ({bridge.credible_mass:.0%} lower)": c.bridge_lower,
                    f"Bridge ({bridge.credible_mass:.0%} upper)": c.bridge_upper,
                }
                for c in ordered
            ]
        )
        st.dataframe(detail_df, width="stretch")
        st.caption(
            f"Reconciliation check (expected ~0): "
            f"{bridge.reconciliation_error_mean:.6g}. Based on "
            f"{bridge.n_draws} posterior draw(s)."
        )


def _render_economic_valuation_section(meta, trace, frame, outcome_definitions):
    st.markdown("---")
    st.markdown("## Economic outcome valuation & ROI")
    st.caption(
        "Historical incremental value and ROI, joined from the governed "
        "weekly outcome-valuation catalogue (REQ-ECON-002/003/004) - never "
        "a raw outcome count presented as money."
    )
    records = [
        WeeklyOutcomeValuationRecord.from_dict(item)
        for item in (get_state("outcome_valuation_records") or [])
    ]
    with st.expander("Governed valuation catalogue (Finance-supplied inputs)"):
        _render_outcome_valuation_catalogue_editor(meta, outcome_definitions, records)

    if not records:
        render_empty_state(
            "No governed outcome-valuation records yet. Add rows to the "
            "catalogue above to enable historical ROI reporting."
        )
        return

    _render_economic_valuation_reporting(meta, trace, frame, records)

    st.markdown("#### Compare two periods")
    st.caption(
        "Explicit period-over-period comparison (e.g. Q1 2025 vs Q1 2026) "
        "- reuses the identical single-period calculation above for both "
        "periods, never a second calculation path."
    )
    _render_period_comparison(meta, trace, frame, records)


def _display_outcome(value, outcome_labels):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    return outcome_labels.get(str(value), readable_label(str(value)))


def _humanise_outcome_columns(dataframe, outcome_labels):
    """Use human outcome labels in visible tables, keeping IDs for calculations."""
    displayed = dataframe.copy()
    if "outcome_id" in displayed.columns:
        displayed["Outcome"] = displayed["outcome_id"].map(
            lambda value: _display_outcome(value, outcome_labels)
        )
        displayed = displayed.drop(columns=["outcome_id"])
    return displayed


def _humanise_pathway_table(dataframe, outcome_labels):
    displayed = _humanise_outcome_columns(dataframe, outcome_labels)
    if "role" in displayed.columns:
        displayed["Pathway status"] = (
            displayed["role"]
            .map(
                {
                    "active_cross_product": "Active cross-product pathway",
                    "exploratory_cross_product": "Exploratory cross-product pathway",
                }
            )
            .fillna(displayed["role"])
        )
        displayed = displayed.drop(columns=["role"])
    return displayed


def _humanise_reporting_summary(dataframe, outcome_labels):
    """Trim roll-up internals from the normal table while retaining measures."""
    displayed = dataframe.copy()
    if "outcome_id" in displayed.columns:
        displayed["Outcome"] = displayed["outcome_id"].map(
            lambda value: _display_outcome(value, outcome_labels)
        )
    if "funnel_stage_label" in displayed.columns:
        displayed["Funnel reporting group"] = displayed["funnel_stage_label"]
    if "effect_type" in displayed.columns:
        displayed["Effect component"] = displayed["effect_type"].map(
            lambda value: _EFFECT_TYPE_LABELS.get(
                str(value), str(value).replace("_", " ").title()
            )
        )

    technical_columns = {
        "outcome_id",
        "funnel_stage",
        "funnel_stage_label",
        "effect_type",
        "pathway_role",
        "reporting_enrichment_status",
        "reporting_enrichment_issue",
        "reporting_taxonomy_fingerprint",
        "funnel_rollup_status",
        "spend_scope",
        "posterior_aggregation_status",
        "activity_market",
    }
    displayed = displayed.drop(
        columns=[column for column in technical_columns if column in displayed.columns]
    )
    rename = {
        "reporting_channel": "Reporting channel",
        "platform": "Platform / supplier",
        "search_intent_group_id": "Search intent group",
        "search_platform": "Search platform",
        "activity_id": "Activity",
        "market": "Market",
        "segment": "Segment",
        "curve_type": "Curve basis",
        "metric_key": "Metric",
        "incremental_response_posterior_mean": "Incremental response · mean",
        "incremental_response_posterior_median": "Incremental response · median",
        "incremental_response_lower_interval": "Incremental response · lower",
        "incremental_response_upper_interval": "Incremental response · upper",
        "reporting_currency_spend_posterior_mean": "Reporting-currency spend · mean",
        "reporting_currency_spend_posterior_median": "Reporting-currency spend · median",
        "reporting_currency_spend_lower_interval": "Reporting-currency spend · lower",
        "reporting_currency_spend_upper_interval": "Reporting-currency spend · upper",
        "spend_point": "Input point",
        "Outcome": "Outcome",
        "Funnel reporting group": "Funnel reporting group",
        "Effect component": "Effect component",
    }
    displayed = displayed.rename(
        columns={
            key: value for key, value in rename.items() if key in displayed.columns
        }
    )
    preferred = [
        "Funnel reporting group",
        "Reporting channel",
        "Platform / supplier",
        "Search intent group",
        "Search platform",
        "Activity",
        "Market",
        "Outcome",
        "Segment",
        "Effect component",
        "Curve basis",
        "Metric",
        "Input point",
        "Incremental response · mean",
        "Incremental response · median",
        "Incremental response · lower",
        "Incremental response · upper",
        "Reporting-currency spend · mean",
        "Reporting-currency spend · median",
        "Reporting-currency spend · lower",
        "Reporting-currency spend · upper",
    ]
    ordered = [column for column in preferred if column in displayed.columns]
    ordered.extend(column for column in displayed.columns if column not in ordered)
    return displayed[ordered]


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
    "Inspect observed support, uncertainty, and evidence tier before using a curve; approved response curves are kept separate from exploratory views and saved parameter snapshots.",
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
        "Use the contribution summary for fitted attribution and the exploratory response curves "
        "for exploratory response evidence. Approved response curves remain a separate, "
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
    media-unit mapping exists on Activity Mapping."""
    config = market_config.get_media_unit_config(market, channel)
    if not (config and config.has_media_unit()):
        st.caption(
            f"No media-unit mapping for {market} / {channel} yet - add one on Activity Mapping "
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


def _render_official_artifact_curves(artifact, outcome_labels):
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
    outcome_label = _display_outcome(outcome_id, outcome_labels)
    definition_version = outcome_snapshot.get("definition_version")
    support_rows = (artifact.metadata.support_snapshot or {}).get("rows") or []
    summaries = artifact.summaries
    for (market, channel), group in draws.groupby(["market", "channel"]):
        stats = summarize_component_response_by_draw(
            group, by=[], x_col=x_col
        ).sort_values(x_col)
        title = f"Approved response curve · {market} · {channel} · {outcome_label}"
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


def _render_official_reporting_views(artifact, activity_definitions, outcome_labels):
    """Render governed funnel/channel/activity drill-downs from artifact draws."""
    draws = artifact.draws
    if draws.empty or "posterior_draw" not in draws.columns:
        return
    st.markdown("#### Reporting views")
    st.caption(
        "Choose the level that answers your question: funnel group for broad "
        "reporting, channel and platform for investment context, or activity "
        "for detail. Funnel groups are reporting buckets, not causal or "
        "mediation labels; direct, mediated, halo, and total effects remain "
        "separate."
    )
    try:
        views = build_reporting_views(
            draws,
            activity_definitions,
            strict=True,
        )
    except ReportingEnrichmentError as exc:
        st.error(
            "This artifact cannot be rendered as a governed activity report "
            f"until its activity mapping is resolved: {exc}"
        )
        return

    tabs = st.tabs(_REPORTING_VIEW_TABS)
    for tab, (_view_name, view) in zip(tabs, views.items()):
        with tab:
            summary = summarize_reporting_draws(view)
            if summary.empty:
                st.info("No rows are available for this reporting view.")
                continue
            displayed_summary = _humanise_reporting_summary(summary, outcome_labels)
            st.dataframe(
                displayed_summary,
                width="stretch",
                column_config=dataframe_column_config(displayed_summary),
            )
            if _view_name == "channel_platform":
                try:
                    paid_search_draws = roll_up_paid_search_reporting_draws(
                        draws,
                        activity_definitions,
                        measure="incremental_response",
                        strict=True,
                    )
                except ReportingEnrichmentError as exc:
                    st.error(
                        "Paid Search hierarchy cannot be rendered until its "
                        f"taxonomy is resolved: {exc}"
                    )
                else:
                    if not paid_search_draws.empty:
                        search_dimensions = [
                            column
                            for column in (
                                "market",
                                "outcome_id",
                                "effect_type",
                            )
                            if column in paid_search_draws.columns
                        ]
                        search_summary = summarize_reporting_draws(
                            paid_search_draws,
                            by=search_dimensions,
                        )
                        st.markdown("**Paid Search reporting hierarchy**")
                        st.caption(
                            "Incremental response is aggregated within each "
                            "posterior draw, then rolled up as Google/Bing × "
                            "Brand/Non-Brand → Brand/Non-Brand → Total Paid Search."
                        )
                        st.dataframe(
                            search_summary,
                            width="stretch",
                            column_config=dataframe_column_config(search_summary),
                        )
            if view["funnel_rollup_status"].eq("contains_unclassified").any():
                st.warning(
                    "Some activity results are grouped as Unclassified because "
                    "their activity mapping does not yet define a funnel group. "
                    "This does not change the fitted effects, but the funnel "
                    "view is not a complete reporting breakdown until the "
                    "mapping is reviewed."
                )
            render_technical_details(
                title="Technical details · reporting view",
                details={
                    "Posterior aggregation": "Rows are combined within each posterior draw before the displayed uncertainty summary.",
                    "Reporting taxonomy": "Funnel, channel/platform, and activity are reporting dimensions; they do not redefine causal pathway roles.",
                },
            )


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
    outcome_labels = _outcome_display_labels(outcome_definitions)
    outcome_id = (md.outcome_definition_snapshot or {}).get("outcome_id")
    outcome_label = _display_outcome(outcome_id, outcome_labels)
    st.markdown(f"#### Approved response curve · {outcome_label}")
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
            "This saved response curve cannot be shown as official evidence "
            "because its current model, approval, or outcome approval could "
            "not be confirmed. Review the model and outcome approvals before "
            "using it for headline reporting."
        )
        return
    try:
        authorization = _CURVE_SERVICE.authorize_use(
            artifact, "headline_reporting", current_governance=governance
        )
    except CurveGovernanceError as exc:
        st.warning(
            f"This response curve is not currently approved for headline reporting: {exc}"
        )
        return
    if not authorization.authorized:
        st.warning(
            "This response curve is not currently approved for headline reporting: "
            f"{authorization.reason}"
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
    curve_type = (
        str(artifact.draws["curve_type"].iloc[0])
        if "curve_type" in artifact.draws.columns and not artifact.draws.empty
        else "model_input"
    )
    meta_df = pd.DataFrame(
        [
            {
                "Curve": "Approved response curve",
                "Created": md.creation_timestamp,
                "Outcome": outcome_label,
                "Curve basis": "Monetary units"
                if curve_type == "monetary"
                else "Model-input units",
                "Current status": "Approved for headline reporting",
                "Planning use": "Eligible"
                if planning_support is True
                else "Review required",
            }
        ]
    )
    st.dataframe(
        meta_df,
        width="stretch",
        column_config=dataframe_column_config(meta_df),
    )
    _governed_context = governed_context_fields(md)
    # Production-integration follow-up (Results/exports disclosure labels):
    # a compact, prominent caption alongside the meta table - not buried in
    # the "Technical details" expander below, which stays the place for the
    # full governed-context dump. Every disclosure here is read straight
    # from `_governed_context` (computed once, reused below too); nothing
    # is recomputed or asserted beyond what that dict already reports, and
    # a disclosure line is only shown when there is something real to say -
    # "not_applicable" (the honest, common case for experiment/Search-
    # capacity evidence today - see governed_context_fields' own docstring)
    # renders no line at all, never a fabricated "N/A" or "0".
    _outcome_metric_label = _governed_context.get("outcome_metric_label")
    if _outcome_metric_label:
        st.caption(f"Outcome definition: {_outcome_metric_label}")
    if _governed_context.get("experiment_calibration_status") == "computed":
        _n_experiments = _governed_context.get("linked_experiment_count") or 0
        st.caption(
            f"Calibrated: this model has {_n_experiments} registered experiment "
            "use(s) linked at creation time (see Diagnostics for evidence detail)."
        )
    if _governed_context.get("search_capacity_status") == "computed":
        if _governed_context.get("search_capacity_official_use_eligible") is False:
            st.warning(
                "Search capacity: this model's Candidate A Search evidence did "
                "not clear the official-use gate at creation time (see "
                "Diagnostics · Candidate A Search for the blocking reason)."
            )
        else:
            st.caption(
                "Search capacity: Candidate A Search evidence was assessed for "
                "this model (see Diagnostics · Candidate A Search for detail)."
            )
    render_technical_details(
        title="Technical details · saved response curve",
        details={
            "Saved curve ID": md.artifact_id,
            "Outcome ID": outcome_id,
            "Schema version": str(md.schema_version),
            "Reference context ID": (md.reference_context_snapshot or {}).get(
                "reference_context_id"
            ),
            "Format status": md.format_status,
            "Historical integrity": md.historical_integrity,
            "Current authorization status": authorization.current_authorization_status,
            "Requested-use eligibility": authorization.requested_use_eligibility,
            **{key: value for key, value in _governed_context.items()},
        },
    )
    _render_official_artifact_curves(artifact, outcome_labels)
    _render_official_reporting_views(artifact, activity_definitions, outcome_labels)


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
        "Approved response curves",
        description=(
            "Saved response curves approved for governed use after the required model, outcome, "
            "activity, and approval checks. They remain separate from exploratory "
            "response curves and saved parameter snapshots."
        ),
    ):
        store_dir = curve_artifact_store_dir()
        try:
            load_result = load_curve_artifact_store(store_dir, raise_on_malformed=False)
        except CurveArtifactError as exc:
            st.warning(f"Saved approved response curves could not be read: {exc}")
            return
        if load_result.malformed:
            st.warning(
                f"{len(load_result.malformed)} saved approved response curve record(s) "
                "could not be read and are listed in the technical audit below."
            )
            with st.expander("Technical details · saved curve audit"):
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
                "No approved response curves have been saved for this project yet. "
                "Use the Planning Curves workflow after the required approval checks "
                "are complete."
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
outcome_definitions = resolve_outcome_definitions(
    get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv
)
outcome_labels = _outcome_display_labels(outcome_definitions)
outcome_groups_at_fit = getattr(meta, "outcome_groups_at_fit", None) or []
outcome_group_treatments_at_fit = (
    getattr(meta, "outcome_group_treatments_at_fit", None) or []
)
for _outcome_group in outcome_groups_at_fit:
    if getattr(_outcome_group, "group_id", None):
        outcome_labels[_outcome_group.group_id] = _outcome_group.group_label
render_drift_status(
    outcome_definitions,
    meta,
)
model_type = get_state("model_type", "shared")
market_config = MarketSpecConfig.from_dict(get_state("market_spec_config"))

st.markdown("### Contribution summary")
st.caption(
    "See where the fitted model attributes incremental outcomes. The views below "
    "describe reporting groupings; they do not replace the causal pathway definitions."
)
render_decision_help(
    "How should I read the outcome views?",
    controls="Business totals, configured outcome groups, and individual outcomes are separate views of the fitted results.",
    why="The outcome units are not interchangeable, so a total is not a licence to add sign-ups, kit sales, and GSA counts together.",
    options={
        "Business total": "A broad Family History total used for the channel overview.",
        "Outcome group": "A configured additive reporting total whose member outcomes are not counted again.",
        "Individual outcome": "One approved outcome definition, shown in its own units.",
    },
    normal_path="Start with the business total, inspect configured groups, then use an individual outcome when the unit or segment needs detail.",
    downstream="The selected view changes the reporting slice only; it does not change fitted pathways, effects, or stored outcome IDs.",
    invalidates="Changing the fitted outcome catalogue or group treatment can change which reporting views are available.",
)

if model_type == "market_specific":
    st.markdown("---")
    with st.spinner("Computing market-aware Shapley contributions..."):
        ms_contributions = compute_shapley_contributions_market_specific(
            frame, meta, params, n_permutations=100
        )

    st.markdown("#### Contribution by reporting channel")
    fh_gsa_ids = fh_gsa_outcome_ids(meta)
    fh_signup_ids = fh_signup_outcome_ids(meta)
    dna_kit_outcomes_in_fit = dna_kit_sale_outcome_ids(meta)
    if dna_kit_outcomes_in_fit or fh_signup_ids:
        st.caption(
            "Channel totals use Family History GSA outcomes; sign-ups and DNA kits remain separate because their units differ."
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
        outcome_groups=outcome_groups_at_fit,
        outcome_group_treatments=outcome_group_treatments_at_fit,
    )
    ms_total_display = _humanise_outcome_columns(ms_total_df, outcome_labels)
    st.dataframe(
        ms_total_display,
        width="stretch",
        column_config=dataframe_column_config(ms_total_display),
    )

    st.markdown("---")
    st.markdown("#### Market and outcome detail")
    ms_seg_df = outcome_channel_market_summary(
        frame,
        meta,
        params,
        ms_contributions,
        ltv,
        outcome_groups=outcome_groups_at_fit,
        outcome_group_treatments=outcome_group_treatments_at_fit,
    )
    ms_seg_display = _humanise_outcome_columns(ms_seg_df, outcome_labels)
    st.dataframe(
        ms_seg_display,
        width="stretch",
        column_config=dataframe_column_config(ms_seg_display),
    )

    st.markdown("---")
    st.markdown("#### Contribution waterfall")
    c1, c2 = st.columns(2)
    waterfall_market = c1.selectbox("Market", meta.markets, key="ms_waterfall_market")
    waterfall_options = {"Business total · Total Family History": None}
    waterfall_options.update(
        {
            f"Outcome group · {label}": group_id
            for group_id, label in reporting_group_options(
                meta.outcome_ids,
                outcome_groups_at_fit,
                outcome_group_treatments_at_fit,
            )
        }
    )
    waterfall_options.update(
        {
            f"Individual outcome · {_display_outcome(outcome_id, outcome_labels)}": outcome_id
            for outcome_id in meta.outcome_ids
        }
    )
    waterfall_scope_label = c2.selectbox(
        "Outcome view", list(waterfall_options), key="ms_waterfall_scope"
    )
    outcome_id_arg = waterfall_options[waterfall_scope_label]
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
        outcome_groups=outcome_groups_at_fit,
        outcome_group_treatments=outcome_group_treatments_at_fit,
    )
    st.plotly_chart(
        create_waterfall_chart(
            waterfall_df["category"].tolist(),
            waterfall_df["value"].tolist(),
            title=f"{waterfall_market} · {waterfall_scope_label} contribution waterfall",
        ),
        width="stretch",
    )

    st.markdown("---")
    st.markdown("### Exploratory response curves")
    st.caption(
        "Selected context: choose one market and channel below. This viewer is exploratory "
        "evidence from the fitted model; it is not an approved response curve for headline reporting."
    )
    st.markdown("#### Market-specific channel response curve")
    st.caption(
        "Exploratory response curve (point estimates): spend -> incremental response for one "
        "market and channel, per segment and overall (overall = sum of segment responses). "
        "These curves are for analysis; use the Approved response curves section for "
        "governed evidence."
    )
    c1, c2 = st.columns(2)
    viewer_market = c1.selectbox("Market", meta.markets)
    viewer_channel = c2.selectbox(
        "Channel",
        meta.channels,
        format_func=lambda c: model_input_display_label(
            c, activity_definitions=activity_definitions, market=viewer_market
        ),
    )

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
        "Estimated cross-product effect strength for each outcome and channel. It is shrunk "
        "toward zero by default and only pulled away from zero where the data supports it. "
        "The pathway catalogue can route this effect to any eligible channel."
    )
    pathway_df = _humanise_pathway_table(
        _pathway_strength_table(meta, params), outcome_labels
    )
    st.dataframe(
        pathway_df, width="stretch", column_config=dataframe_column_config(pathway_df)
    )

else:
    st.markdown("---")
    with st.spinner("Computing Shapley contributions..."):
        contributions = compute_shapley_contributions(
            frame, meta, params, n_permutations=100
        )

    st.markdown("#### Family History contribution by channel")
    fh_gsa_ids = fh_gsa_outcome_ids(meta)
    fh_signup_ids = fh_signup_outcome_ids(meta)
    dna_kit_outcomes_in_fit = dna_kit_sale_outcome_ids(meta)
    if dna_kit_outcomes_in_fit or fh_signup_ids:
        st.caption(
            "Channel totals use Family History GSA outcomes; sign-ups and DNA kits remain separate because their units differ."
        )
    else:
        st.caption(
            "Total impact per channel across all outcomes, plus which outcome that impact falls into and LTV-weighted value."
        )
    total_df = total_fh_contribution(
        frame,
        meta,
        params,
        contributions,
        ltv,
        outcome_ids=fh_gsa_ids,
        outcome_groups=outcome_groups_at_fit,
        outcome_group_treatments=outcome_group_treatments_at_fit,
    )
    total_display = _humanise_outcome_columns(total_df, outcome_labels)
    st.dataframe(
        total_display,
        width="stretch",
        column_config=dataframe_column_config(total_display),
    )

    st.markdown("---")
    st.markdown("#### Outcome and channel detail")
    seg_df = outcome_channel_summary(
        frame,
        meta,
        params,
        contributions,
        ltv,
        outcome_groups=outcome_groups_at_fit,
        outcome_group_treatments=outcome_group_treatments_at_fit,
    )
    seg_display = _humanise_outcome_columns(seg_df, outcome_labels)
    st.dataframe(
        seg_display, width="stretch", column_config=dataframe_column_config(seg_display)
    )

    st.markdown("---")
    st.markdown("#### Contribution waterfall")
    waterfall_options = {"Business total · Total Family History": None}
    waterfall_options.update(
        {
            f"Outcome group · {label}": group_id
            for group_id, label in reporting_group_options(
                meta.outcome_ids,
                outcome_groups_at_fit,
                outcome_group_treatments_at_fit,
            )
        }
    )
    waterfall_options.update(
        {
            f"Individual outcome · {_display_outcome(outcome_id, outcome_labels)}": outcome_id
            for outcome_id in meta.outcome_ids
        }
    )
    waterfall_scope_label = st.selectbox(
        "Outcome view", list(waterfall_options), key="shared_waterfall_scope"
    )
    outcome_id_arg = waterfall_options[waterfall_scope_label]
    waterfall_df = contribution_waterfall(
        frame,
        meta,
        params,
        outcome_id=outcome_id_arg,
        contributions=contributions,
        outcome_groups=outcome_groups_at_fit,
        outcome_group_treatments=outcome_group_treatments_at_fit,
    )
    st.plotly_chart(
        create_waterfall_chart(
            waterfall_df["category"].tolist(),
            waterfall_df["value"].tolist(),
            title=f"{waterfall_scope_label} contribution waterfall",
        ),
        width="stretch",
    )

    st.markdown("---")
    st.markdown("### Exploratory response curves")
    st.caption(
        "Selected context: choose a channel and reference market below. This viewer is "
        "exploratory evidence from the fitted model; approved response curves for "
        "governed use are shown separately below."
    )
    st.markdown("#### Channel response curve")
    st.caption(
        "Exploratory response curve (point estimates): spend -> incremental response for one "
        "channel, per segment and overall (overall = sum of segment responses) - the same "
        "curve every market uses, since it's shared across markets in this model structure. "
        "These curves are for analysis; use the Approved response curves section for "
        "governed evidence."
    )
    viewer_channel = st.selectbox(
        "Channel",
        meta.channels,
        format_func=lambda c: model_input_display_label(
            c, activity_definitions=activity_definitions
        ),
    )

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
    pathway_df = _humanise_pathway_table(
        _pathway_strength_table(meta, params), outcome_labels
    )
    st.dataframe(
        pathway_df, width="stretch", column_config=dataframe_column_config(pathway_df)
    )
    st.caption(
        "Estimated cross-product effect strength for each outcome and channel. It is shrunk "
        "toward zero by default (more tightly for exploratory cells) and only pulled away from "
        "zero where the data supports it. An outcome's own direct media pathway, such as the "
        "DNA cross-sell outcome's direct DNA-media response, is not shown here because its "
        "weight is represented by the response coefficient rather than a separate strength "
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
_render_economic_valuation_section(meta, trace, frame, outcome_definitions)

st.markdown("---")
st.markdown("## Saved parameter snapshots")
st.caption(
    "Review saved parameter snapshots for calibration tracking and evidence review. "
    "Use Planning Curves when a governed response curve is required."
)
st.caption(
    "These saved records are **fitted parameter snapshots** (Hill/decay/beta "
    "point estimates for one market/channel/segment), not evaluated curves. "
    "They support calibration tracking and evidence review, but are not the "
    "same thing as a current approved response curve."
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
        "saving a parameter snapshot is blocked until the model is approved on Model Diagnostics.",
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
        + ". Saving a parameter snapshot is blocked until it's reviewed and approved again.",
        button_label="Go to Model Diagnostics",
        target_key="diagnostics",
    )
else:
    approval = ModelApproval.from_dict(approval_dict)
    st.caption(
        f"Model approved by **{approval.approved_by}** - this approval will be recorded with each saved parameter snapshot."
    )

    c1, c2 = st.columns(2)
    run_label = c1.text_input(
        "Run label *", value=f"{spec.markets and spec.markets[0] or 'run'}-v1"
    )
    notes = c2.text_input("Notes (optional)")

    if st.button("Save current response-curve parameters", type="primary"):
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
            st.error(f"Could not save the response-curve parameters: {e}")
        else:
            paths = cb.save_entries(curve_bank_dir(), entries)
            set_state("curve_bank_entry_id", entries[0].entry_id if entries else None)
            st.success(f"Saved {len(entries)} response-curve parameter snapshot(s).")

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
    st.markdown("#### Saved parameter history")
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
        "Filter: evidence status", sorted(entries_df["curve_status"].unique())
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

    snapshot_display = filtered_df.rename(
        columns={
            "run_label": "Run",
            "created_at": "Saved",
            "data_window_start": "Data from",
            "data_window_end": "Data to",
            "market": "Market",
            "channel": "Channel",
            "segment_or_overall": "Segment / total",
            "curve_status": "Evidence status",
            "input_type": "Input basis",
            "currency": "Currency",
            "unit_type": "Media unit",
            "cost_per_unit": "Cost per unit",
            "decay_rate": "Carryover",
            "hill_K": "Saturation scale",
            "hill_S": "Saturation shape",
            "beta": "Response coefficient",
            "halo_strength": "Cross-product strength",
            "approved_by": "Approved by",
            "approved_at": "Approved at",
        }
    ).drop(
        columns=[
            "entry_id",
            "model_type",
            "model_run_id",
            "legacy_approval",
            "legacy_format",
        ],
        errors="ignore",
    )
    st.dataframe(
        snapshot_display,
        width="stretch",
        column_config=dataframe_column_config(snapshot_display),
    )
    if entries_df["legacy_approval"].any() or entries_df["legacy_format"].any():
        render_technical_details(
            title="Technical details · saved parameter history",
            body=(
                "Some saved parameter snapshots use an older record format or predate "
                "model-run approval binding. Their evidence status is retained for audit "
                "and should be reviewed before relying on them."
            ),
        )

    st.markdown("#### Record a calibration result")
    entry_options = {
        f"Snapshot {index + 1} · {e.run_label} · {e.market or 'Shared'} · "
        f"{model_input_display_label(e.channel, activity_definitions=activity_definitions, market=e.market)}"
        f" · {e.segment_or_overall} · {e.input_type} · "
        f"{format_date(pd.Timestamp.fromtimestamp(e.created_at))}": e.entry_id
        for index, e in enumerate(entries)
    }
    chosen_label = st.selectbox("Saved parameter snapshot", list(entry_options.keys()))
    chosen_entry = next(e for e in entries if e.entry_id == entry_options[chosen_label])

    c1, c2 = st.columns(2)
    test_type_labels = {"Geo test": "geo", "In-platform test": "in_platform"}
    test_type_label = c1.selectbox("Test type", list(test_type_labels))
    test_type = test_type_labels[test_type_label]
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
    st.info("No saved parameter snapshots yet.")

render_next_step("curve_bank")
