"""Page 5: build and fit the joint hierarchical FH model, with a live progress indicator."""

import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    clear_model_state,
    format_number,
    dataframe_column_config,
    readable_label,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_drift_status,
    render_workspace_note,
    SectionCard,
    InfoPanel,
    render_status_badge,
    render_decision_help,
    render_technical_details,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.causal_graph import GRAPH_STATUS_APPROVED, CausalGraph
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.application.model_fit_service import (
    SEARCH_CANDIDATE_A_ENGINE,
    ModelFitServiceError,
    build_model_for_spec,
    resolve_engine,
)
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.market_specific_predict import (
    extract_market_specific_posterior_params,
)
from ancestry_mmm.core.model_comparison import ModelComparisonCandidate
from ancestry_mmm.core.market_specific_diagnostics import (
    compute_scorecard_market_specific,
)
from ancestry_mmm.core.diagnostics import compute_scorecard, prior_predictive_summary
from ancestry_mmm.core.prefit_run import official_submission_allowed
from ancestry_mmm.core.fingerprint import fingerprint_dataframe, fingerprint_model_spec
from ancestry_mmm.core.outcomes import (
    outcome_catalogue_fingerprint_payload,
    resolve_outcome_definitions,
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.activities import activity_fit_fingerprint
from ancestry_mmm.core.search_objects import search_object_fit_fingerprint
from ancestry_mmm.core.search_capacity import (
    CandidateASearchFitInputs,
    SearchCandidateASpec,
    SearchCapacityValidationError,
)
from ancestry_mmm.application.candidate_a_input_service import (
    CANDIDATE_A_UPLOAD_COLUMNS,
    build_candidate_a_fit_inputs_from_frame,
)
from ancestry_mmm.core.google_trends_anchor import (
    GoogleTrendsAnchorFitInputs,
    GoogleTrendsQuerySetDefinition,
    GoogleTrendsRawObservation,
    compute_anchor_series,
)
from ancestry_mmm.core.seo_visibility import (
    GscPositionRow,
    SeoModelFitInputs,
    compute_weekly_positional_visibility_series,
)
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.data import (
    TEMPLATE_MIME_TYPE,
    build_candidate_a_template,
)
from ancestry_mmm.core.named_event_fit_inputs import build_named_event_fit_inputs
from ancestry_mmm.core.named_events import (
    EventResponseDefinition,
    NamedEventFamily,
    NamedEventOccurrence,
)
from ancestry_mmm.core.experiments import (
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
    CompatibilityAssessment,
    ExperimentRecord,
    ExperimentToModelUse,
)
from ancestry_mmm.core.experiment_lift_test_mapping import (
    ModelLiftTestCalibrationInput,
    build_lift_test_calibration_row,
    calibration_inputs_fingerprint,
)

MODEL_TYPE_LABELS = {
    "shared": "Shared response across markets (Model A)",
    "market_specific": "Market-specific response with partial pooling (Model C)",
}


def _outcome_display_label(outcome) -> str:
    label = f"{outcome.product} · {outcome.segment} · {outcome.metric}"
    if outcome.definition_version:
        label += f" (definition {outcome.definition_version})"
    return label


st.set_page_config(
    page_title="Fit Model | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("model_training")
render_page_header(
    "model_training",
    task_prompt="Is the prepared frame ready for an honest fit?",
)
render_workspace_note(
    "Proposed fit",
    "The prepared frame is read-only here; fitting creates the posterior evidence reviewed in Diagnostics.",
    kind="derived",
)

frame = get_state("frame")
spec_dict = get_state("model_spec")
if frame is None or not spec_dict:
    render_empty_state(
        "No modelling frame ready yet. Complete Model Setup first.",
        button_label="Go to Model Setup",
        target_key="model_config",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
outcome_definitions = resolve_outcome_definitions(
    get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv
)
outcome_display_labels = {
    alias: _outcome_display_label(outcome)
    for outcome in outcome_definitions
    for alias in (outcome.outcome_id, outcome.source_column)
}
if get_state("model_meta") is not None:
    render_drift_status(frame.get("outcomes") or [], get_state("model_meta"))
model_type = get_state("model_type", "shared")
if model_type == "market_specific" and len(frame["markets"]) < 2:
    st.warning(
        "This project has only 1 market, so market-specific curves aren't available - fitting the "
        "shared-curve model instead. Change this on Model Setup for future fits."
    )
    model_type = "shared"

dna_kit_outcome_ids = get_state("direct_dna_outcome_ids") or []

with st.container(border=True):
    st.markdown("### Fit dashboard")
    st.caption(
        "The prepared frame is the current fit input. Review the proposal and sampling plan, then run the fit when the configuration is ready."
    )
    summary_cols = st.columns(4)
    summary_cols[0].metric(
        "Model type", "Market-specific" if model_type == "market_specific" else "Shared"
    )
    summary_cols[1].metric("Observations", format_number(frame["X_media"].shape[0]))
    summary_cols[2].metric("Markets", len(frame["markets"]))
    summary_cols[3].metric(
        "Fit state", "Trained" if get_state("model_trained") else "Ready to fit"
    )

with SectionCard(
    "Fit proposal",
    description="The model identity and scope that will be used if you start fitting.",
):
    st.caption(f"Markets: {', '.join(frame['markets'])}")
    st.caption(
        "Outcomes: "
        + ", ".join(
            outcome_display_labels.get(outcome_id, outcome_id)
            for outcome_id in frame["outcome_ids"]
        )
    )
    st.caption(f"Model-input channels: {', '.join(frame['channels'])}")
    if dna_kit_outcome_ids:
        st.caption(
            "DNA-product outcomes with direct media response: "
            + ", ".join(
                outcome_display_labels.get(outcome_id, readable_label(outcome_id))
                for outcome_id in dna_kit_outcome_ids
            )
        )
    st.caption(
        "DNA-targeted channels: "
        + (", ".join(frame["channels"][i] for i in frame["dna_channel_idx"]) or "none")
    )

with InfoPanel(
    "Sampling plan",
    description="Sequential single-core sampling; live progress is shown only from the fitter's callback.",
):
    st.markdown(f"""
- **MCMC draws:** {format_number(get_state("mcmc_draws"))}
- **Tune steps:** {format_number(get_state("mcmc_tune"))}
- **Chains:** {get_state("mcmc_chains")}
""")
    st.caption(
        "A full run with several thousand draws can take from a few minutes to significantly "
        "longer depending on data size and hardware - this does not block the rest of the app "
        "once started."
    )


def _resolve_causal_graph():
    # REQ-GRAPH-001 work package D/E: an approved causal graph, when one
    # exists for this project, is the sole authoritative structural input -
    # resolve_pathway_masks_preferring_graph (inside both builders below)
    # ignores the raw MediaOutcomePathway catalogue entirely once this is
    # supplied. None (every project without a graph, or with only a draft
    # graph) reproduces exactly today's pathway-catalogue-driven behaviour.
    causal_graph_dict = get_state("causal_graph")
    if causal_graph_dict and causal_graph_dict.get("status") == GRAPH_STATUS_APPROVED:
        return CausalGraph.from_dict(causal_graph_dict)
    return None


def _model_week_labels() -> tuple[str, ...]:
    return tuple(str(pd.Timestamp(value).date()) for value in frame["dates"])


def _seo_fit_inputs_for_current_frame():
    payload = get_state("seo_fit_inputs")
    if payload is None:
        return None
    if isinstance(payload, SeoModelFitInputs):
        fit_inputs = payload
    else:
        if not isinstance(payload, dict):
            raise ValueError("seo_fit_inputs must be a serialized mapping")
        fit_inputs = SeoModelFitInputs.from_dict(payload)
    fit_inputs.validate_frame(
        markets=[frame["markets"][int(index)] for index in frame["market_idx"]],
        weeks=_model_week_labels(),
    )
    return fit_inputs


def _candidate_a_fit_inputs_for_current_frame():
    """Resolve the optional serialized Candidate A observations.

    Search arrays remain governed inputs assembled by the data-preparation
    workflow. This boundary adds the approved Google Trends anchor to that
    object without fabricating any Search observations or silently using a
    stale anchor from another frame.
    """
    payload = get_state("candidate_a_fit_inputs")
    if payload is None:
        return None
    if isinstance(payload, CandidateASearchFitInputs):
        fit_inputs = payload
    else:
        if not isinstance(payload, dict):
            raise ValueError("candidate_a_fit_inputs must be a serialized mapping")
        fit_inputs = CandidateASearchFitInputs.from_dict(payload)
    anchor_payload = get_state("google_trends_anchor")
    if not anchor_payload:
        return fit_inputs
    anchor = GoogleTrendsAnchorFitInputs.from_dict(anchor_payload)
    if tuple(anchor.model_weeks) != _model_week_labels():
        raise ValueError(
            "The Google Trends Candidate A anchor does not cover the current "
            "model frame; upload one governed extraction for this frame."
        )
    from dataclasses import replace

    return replace(fit_inputs, google_trends_anchor=anchor)


def _calibration_inputs_for_current_fit():
    """Build model calibration rows from the governed registry.

    The affected likelihood field uses the explicit adapter target format
    ``direct:<channel>:<outcome_id>``. This avoids guessing an outcome in the
    joint MMM. A declaration with another shape is rejected at fit time and
    remains visible in Diagnostics for correction.
    """
    records = [
        ExperimentRecord.from_dict(item)
        for item in (get_state("experiment_records") or [])
    ]
    uses = [
        ExperimentToModelUse.from_dict(item)
        for item in (get_state("experiment_model_uses") or [])
    ]
    assessments = {
        item["experiment_id"]: CompatibilityAssessment.from_dict(item)
        for item in (get_state("experiment_compatibility_assessments") or [])
    }
    records_by_key = {
        (record.experiment_id, record.experiment_version): record for record in records
    }
    fit_start = pd.Timestamp(frame["dates"][0])
    fit_end = pd.Timestamp(frame["dates"][-1])
    model_markets = set(frame.get("markets") or [])
    inputs = []
    for use in uses:
        if use.evidence_mode != EVIDENCE_MODE_LIKELIHOOD_CALIBRATION:
            continue
        target = use.affected_likelihood_term_name or ""
        parts = target.split(":", 2)
        if len(parts) != 3 or parts[0] != "direct" or not parts[1] or not parts[2]:
            raise ValueError(
                "Likelihood calibration target must use direct:<channel>:<outcome_id>."
            )
        record = records_by_key.get((use.experiment_id, use.experiment_version))
        assessment = assessments.get(use.experiment_id)
        if record is None or assessment is None:
            raise ValueError(
                f"Calibration use {use.experiment_id!r} has no matching "
                "experiment record and compatibility assessment."
            )
        if assessment.is_local or not model_markets.issubset(set(record.market_scope)):
            raise ValueError(
                f"Experiment {record.experiment_id!r} is scoped to "
                f"{record.market_scope}, not the full fitted market set "
                f"{sorted(model_markets)}; the current calibration adapter "
                "cannot safely aggregate a local experiment into a global fit."
            )
        if record.applicability_period_start and record.applicability_period_end:
            applicability_start = pd.Timestamp(record.applicability_period_start)
            applicability_end = pd.Timestamp(record.applicability_period_end)
            if applicability_end < fit_start or applicability_start > fit_end:
                raise ValueError(
                    f"Experiment {record.experiment_id!r} is outside its "
                    "declared applicability period for this model frame."
                )
        row = build_lift_test_calibration_row(record, use, assessment, channel=parts[1])
        inputs.append(ModelLiftTestCalibrationInput(row=row, outcome_id=parts[2]))
    return inputs or None


def _render_google_trends_candidate_a_boundary() -> None:
    """Collect and validate the external Candidate A anchor, if supplied."""
    with st.expander("Google Trends Candidate A — Brand Demand anchor", expanded=False):
        st.caption(
            "Candidate A uses Google Trends Candidate A as the approved Brand Demand "
            "anchor. Uploading is optional at this screen, but a Candidate A fit "
            "cannot run until a complete governed weekly series and Search inputs "
            "are present. Trends values are relative 0–100 indices, never search counts."
        )
        current_anchor = get_state("google_trends_anchor")
        if current_anchor:
            anchor = GoogleTrendsAnchorFitInputs.from_dict(current_anchor)
            st.success(
                f"Anchor loaded: `{anchor.query_set.query_set_id}`; "
                f"{len(anchor.observations)} weekly observations; "
                f"extraction {anchor.query_set.extraction_date or 'date not recorded'}."
            )
        upload = st.file_uploader(
            "Google Trends CSV (columns: week, raw_index)",
            type=["csv"],
            key="google_trends_candidate_a_upload",
        )
        meta_cols = st.columns(3)
        query_set_id = meta_cols[0].text_input("Query-set ID", key="gt_query_set_id")
        geography = meta_cols[1].text_input("Geography", key="gt_geography")
        terms_text = meta_cols[2].text_input(
            "Approved branded terms (comma-separated)", key="gt_branded_terms"
        )
        detail_cols = st.columns(3)
        category = detail_cols[0].text_input(
            "Category", value="all_categories", key="gt_category"
        )
        search_property = detail_cols[1].text_input(
            "Search property", value="web_search", key="gt_search_property"
        )
        extraction_date = detail_cols[2].text_input(
            "Extraction date (YYYY-MM-DD)", key="gt_extraction_date"
        )
        sigma = st.number_input(
            "Trend measurement sigma",
            min_value=0.001,
            value=0.15,
            step=0.01,
            key="gt_sigma",
        )
        if st.button("Validate and load Google Trends anchor", key="load_gt_anchor"):
            if upload is None:
                st.error("Choose a Google Trends CSV first.")
            elif (
                not query_set_id.strip()
                or not geography.strip()
                or not terms_text.strip()
            ):
                st.error(
                    "Query-set ID, geography, and the approved branded term list are required."
                )
            else:
                try:
                    trends_frame = pd.read_csv(upload.getvalue())
                    required = {"week", "raw_index"}
                    if not required.issubset(trends_frame.columns):
                        raise ValueError("CSV must contain week and raw_index columns")
                    query_set = GoogleTrendsQuerySetDefinition(
                        query_set_id=query_set_id.strip(),
                        branded_terms=tuple(
                            term.strip()
                            for term in terms_text.split(",")
                            if term.strip()
                        ),
                        geography=geography.strip(),
                        time_range_start=_model_week_labels()[0],
                        time_range_end=_model_week_labels()[-1],
                        category=category.strip(),
                        search_property=search_property.strip(),
                        extraction_date=extraction_date.strip() or None,
                    )
                    raw = [
                        GoogleTrendsRawObservation(
                            query_set_id=query_set.query_set_id,
                            week=str(pd.Timestamp(row.week).date()),
                            raw_index=float(row.raw_index),
                        )
                        for row in trends_frame.itertuples(index=False)
                    ]
                    observations = tuple(
                        compute_anchor_series(query_set.query_set_id, raw)
                    )
                    anchor = GoogleTrendsAnchorFitInputs(
                        query_set=query_set,
                        observations=observations,
                        model_weeks=_model_week_labels(),
                        measurement_sigma=float(sigma),
                    )
                    set_state("google_trends_anchor", anchor.to_dict())
                    st.success(
                        "Google Trends anchor validated and attached to the current "
                        "project; it will be included in the next fit and bundle."
                    )
                    st.rerun()
                except (ValueError, TypeError, KeyError) as exc:
                    st.error(f"Google Trends anchor validation failed: {exc}")


_render_google_trends_candidate_a_boundary()


def _render_candidate_a_observation_boundary() -> None:
    """Attach the governed, row-aligned Candidate A Search observations.

    The approved Search object/spec identity is deliberately not inferred
    from column names.  An analyst can upload observations once that identity
    has been approved and restored in the project; otherwise this screen
    explains the missing prerequisite and keeps the engine fail-closed.
    """
    with st.expander("Candidate A Search observations", expanded=False):
        st.caption(
            "Upload one exact weekly row per prepared model row. Required fields: "
            + ", ".join(f"`{column}`" for column in CANDIDATE_A_UPLOAD_COLUMNS)
            + ". Cap values stay in their governed cap unit and are translated only "
            "by the approved cap-to-delivery mapping. Missing rows, cap derivation, "
            "and zero-filling are rejected."
        )
        st.download_button(
            "Download Candidate A observation template",
            data=build_candidate_a_template(),
            file_name="ancestry-mmm-candidate-a-observations-template.xlsx",
            mime=TEMPLATE_MIME_TYPE,
            key="download_candidate_a_observations_template",
        )
        payload = get_state("candidate_a_fit_inputs")
        if payload:
            try:
                current = (
                    payload
                    if isinstance(payload, CandidateASearchFitInputs)
                    else CandidateASearchFitInputs.from_dict(payload)
                )
            except (TypeError, ValueError) as exc:
                current = None
                st.error(f"Stored Candidate A observations are invalid: {exc}")
        else:
            current = None

        if current is not None:
            st.success(
                f"Candidate A observations loaded: {len(current.paid_search_delivery):,} "
                f"aligned rows; cap unit `{current.spec.cap_unit}`; "
                f"scale `{current.spec.cap_to_delivery_scale:g}`."
            )
            spec = current.spec
            demand_channels = list(current.demand_channel_names)
            search_objects = list(current.search_objects)
        else:
            spec_payload = get_state("search_candidate_a_spec")
            spec = (
                SearchCandidateASpec.from_dict(spec_payload) if spec_payload else None
            )
            demand_channels = []
            search_objects = list(get_state("search_objects") or [])
            if spec is None:
                st.info(
                    "No approved Candidate A specification is attached to this "
                    "project. Restore the governed Search spec and object mapping "
                    "first; the observation upload will not invent object IDs, "
                    "cap provenance, or upstream demand channels."
                )
        upload = st.file_uploader(
            "Candidate A observations CSV",
            type=["csv"],
            key="candidate_a_observations_upload",
        )
        if spec is not None and current is None:
            demand_text = st.text_input(
                "Approved upstream demand channel IDs (comma-separated)",
                key="candidate_a_demand_channels",
                help="Use the exact model-input channel IDs approved by the causal graph.",
            )
            demand_channels = [
                item.strip() for item in demand_text.split(",") if item.strip()
            ]
        if st.button(
            "Validate and load Candidate A observations",
            key="load_candidate_a_observations",
            disabled=upload is None or spec is None or not demand_channels,
        ):
            try:
                uploaded = pd.read_csv(upload.getvalue())
                fit_inputs = build_candidate_a_fit_inputs_from_frame(
                    uploaded,
                    model_frame=frame,
                    spec=spec,
                    demand_channel_names=demand_channels,
                    search_objects=search_objects,
                    google_trends_anchor=(
                        GoogleTrendsAnchorFitInputs.from_dict(
                            get_state("google_trends_anchor")
                        )
                        if get_state("google_trends_anchor")
                        else None
                    ),
                )
                set_state("candidate_a_fit_inputs", fit_inputs.to_dict())
                set_state("search_candidate_a_spec", fit_inputs.spec.to_dict())
                clear_model_state()
                st.success(
                    f"Loaded {len(fit_inputs.paid_search_delivery):,} governed "
                    "Candidate A rows. No model fit was started."
                )
                st.rerun()
            except (
                ValueError,
                TypeError,
                KeyError,
                SearchCapacityValidationError,
            ) as exc:
                st.error(f"Candidate A observation validation failed: {exc}")


_render_candidate_a_observation_boundary()


def _render_seo_visibility_boundary() -> None:
    """Load the governed GSC positional-visibility treatment boundary.

    The upload is intentionally raw-row based: absent market/week cells stay
    absent and therefore inactive in the fitted MMM.  No missing SEO history
    is converted to zero and no SEO cost/ROI is created here.
    """
    with st.expander("SEO visibility / ranking pathway", expanded=False):
        st.caption(
            "Upload GSC rows with market, week, dimension_label, position, "
            "impressions and optional clicks. The app computes the approved "
            "impression-weighted positional-visibility index and fits it only "
            "inside the observed window; missing weeks are not zero-filled. "
            "SEO remains outside spend-based CPA/ROI and optimisation."
        )
        current = get_state("seo_fit_inputs")
        if current:
            loaded = (
                current
                if isinstance(current, SeoModelFitInputs)
                else SeoModelFitInputs.from_dict(current)
            )
            observed = int(sum(loaded.active_mask))
            st.success(
                f"SEO visibility boundary loaded: {observed} active row(s) across "
                f"{len(loaded.window_by_market)} market(s)."
            )
        upload = st.file_uploader(
            "GSC CSV (market, week, dimension_label, position, impressions, clicks)",
            type=["csv"],
            key="seo_visibility_upload",
        )
        if st.button("Validate and load SEO visibility", key="load_seo_visibility"):
            if upload is None:
                st.error("Choose a GSC positional-visibility CSV first.")
            else:
                try:
                    seo_frame = pd.read_csv(upload.getvalue())
                    required = {
                        "market",
                        "week",
                        "dimension_label",
                        "position",
                        "impressions",
                    }
                    missing = sorted(required - set(seo_frame.columns))
                    if missing:
                        raise ValueError(
                            "GSC CSV is missing required source fields: "
                            + ", ".join(missing)
                        )
                    rows_by_market_week = {}
                    model_markets = [
                        frame["markets"][int(index)] for index in frame["market_idx"]
                    ]
                    model_weeks = list(_model_week_labels())
                    for row in seo_frame.to_dict("records"):
                        market = str(row["market"]).strip()
                        week = str(pd.Timestamp(row["week"]).date())
                        if market not in frame["markets"]:
                            raise ValueError(
                                f"GSC row market {market!r} is not in the model frame."
                            )
                        rows_by_market_week.setdefault((market, week), []).append(
                            GscPositionRow(
                                dimension_label=str(row["dimension_label"]),
                                position=float(row["position"]),
                                impressions=float(row["impressions"]),
                                clicks=float(row.get("clicks", 0.0) or 0.0),
                            )
                        )
                    observations = compute_weekly_positional_visibility_series(
                        rows_by_market_week
                    )
                    fit_inputs = SeoModelFitInputs.from_observations(
                        observations,
                        model_markets=model_markets,
                        model_weeks=model_weeks,
                    )
                    set_state("seo_fit_inputs", fit_inputs.to_dict())
                    st.success(
                        "SEO visibility validated and attached to the next fit. "
                        f"Observed window cells: {len(observations)}."
                    )
                    st.rerun()
                except (ValueError, TypeError, KeyError) as exc:
                    st.error(f"SEO visibility validation failed: {exc}")


_render_seo_visibility_boundary()


def _build_proposed_model(build_model_type: str):
    """Build the unfit `(model, meta)` for the CURRENT proposed
    configuration (live `model_spec`/`prior_config`/`dna_lag_weeks`/causal
    graph) - the exact same call "Build & fit model" below uses, just never
    followed by `fit_model`. Shared by the pre-fit prior predictive preview
    and the real fit so they can never silently diverge on what "the
    proposed model" means.

    WP1 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`): delegates
    engine selection to `application.model_fit_service` instead of an
    inline shared/market-specific ternary. Candidate A Search observations
    and the optional Google Trends anchor are resolved from the governed fit
    boundary here; a required but incomplete boundary fails closed with a
    specific `ModelFitServiceError` rather than silently falling back to the
    ordinary builder.
    """
    prior_config = get_state("prior_config")
    dna_lag_weeks = get_state("dna_lag_weeks", 4)
    direct_dna_outcome_ids = get_state("direct_dna_outcome_ids") or None
    causal_graph = _resolve_causal_graph()
    search_objects = get_state("search_objects") or []
    named_event_fit_inputs = _named_event_fit_inputs_for_current_frame()
    candidate_a_fit_inputs = _candidate_a_fit_inputs_for_current_frame()
    seo_fit_inputs = _seo_fit_inputs_for_current_frame()
    calibration_inputs = _calibration_inputs_for_current_fit()
    result = build_model_for_spec(
        frame=frame,
        model_spec=spec,
        model_type=build_model_type,
        dna_lag_weeks=dna_lag_weeks,
        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
        prior_config=prior_config,
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        causal_graph=causal_graph,
        search_objects=search_objects,
        candidate_a_fit_inputs=candidate_a_fit_inputs,
        named_event_fit_inputs=named_event_fit_inputs,
        calibration_inputs=calibration_inputs,
        seo_fit_inputs=seo_fit_inputs,
    )
    return result.model, result.meta


def _named_event_fit_inputs_for_current_frame():
    """Resolve the current governed event registry for the actual fit frame.

    The model-training page owns the fit-time boundary: event definitions are
    read from the project snapshot and converted into the same deterministic
    basis used by the model builder.  An opted-out or empty registry returns
    ``None``, preserving the ordinary model graph exactly.
    """
    families = [
        NamedEventFamily.from_dict(item)
        for item in (get_state("named_event_families") or [])
    ]
    occurrences = [
        NamedEventOccurrence.from_dict(item)
        for item in (get_state("named_event_occurrences") or [])
    ]
    definitions = [
        EventResponseDefinition.from_dict(item)
        for item in (get_state("named_event_response_definitions") or [])
    ]
    return build_named_event_fit_inputs(
        frame,
        families=families,
        occurrences=occurrences,
        response_definitions=definitions,
    )


def _proposed_model_fingerprint(fingerprint_model_type: str) -> str:
    """The pre-fit analogue of `06_Diagnostics.py`'s `ModelIdentity`
    construction - the same `fingerprint_model_spec` call it uses for
    `model_spec_fingerprint`, fed with exactly the values a build right now
    would use (read directly from live session state and `frame`'s own
    snapshotted `outcomes`/`media_outcome_pathways` -
    `core.hierarchical_model.build_fh_hierarchical_model` derives
    `outcome_catalogue_at_fit`/`pathway_catalogue_at_fit` from those exact
    frame keys, never from live `get_state` directly), combined with
    `fingerprint_dataframe(frame["df"])` - the same `data_fingerprint`
    component `ModelIdentity` binds separately alongside `model_spec_
    fingerprint`. Both matter here: the builders derive the default
    intercept prior from `Y`, and the sampled prior predictive distribution
    depends on the frame's media/controls too, so a spec/prior match alone
    is not enough to certify this preview still describes the current
    proposal - a re-uploaded or re-transformed dataset with an unchanged
    spec must also mark a previous preview stale. Cheap to recompute on
    every rerun (hashing only, no PyMC model build) purely to detect
    whether the proposal has since changed."""
    causal_graph = _resolve_causal_graph()
    activity_definitions = get_state("activity_definitions") or []
    search_objects = get_state("search_objects") or []
    coverage_matrix_dict = get_state("variable_coverage_matrix")
    named_event_fit_inputs = _named_event_fit_inputs_for_current_frame()
    calibration_inputs = _calibration_inputs_for_current_fit()
    model_spec_fingerprint = fingerprint_model_spec(
        spec_dict,
        get_state("prior_config") or {},
        int(get_state("dna_lag_weeks", 4)),
        model_type=fingerprint_model_type,
        pipeline_steps=get_state("pipeline_steps") or [],
        market_spec_config=get_state("market_spec_config"),
        direct_dna_outcome_ids=get_state("direct_dna_outcome_ids") or None,
        outcome_catalogue=outcome_catalogue_fingerprint_payload(
            frame.get("outcomes") or []
        ),
        funnel_links=get_state("funnel_links"),
        media_outcome_pathways=pathway_catalogue_fingerprint_payload(
            frame.get("media_outcome_pathways") or []
        ),
        activity_fit_fingerprint=(
            activity_fit_fingerprint(activity_definitions)
            if activity_definitions
            else None
        ),
        causal_graph_structural_fingerprint=(
            causal_graph.structural_fingerprint() if causal_graph is not None else ""
        ),
        search_object_fit_fingerprint=(
            search_object_fit_fingerprint(
                search_objects, consumed_model_input_columns=spec.channels
            )
            if search_objects
            else None
        ),
        variable_coverage_fingerprint=(
            VariableCoverageMatrix.from_dict(coverage_matrix_dict).fingerprint()
            if coverage_matrix_dict
            else None
        ),
        official_preparation_evidence=get_state("official_preparation_result"),
        named_event_fit_fingerprint=(
            named_event_fit_inputs.fingerprint()
            if named_event_fit_inputs is not None
            else None
        ),
        calibration_fit_fingerprint=calibration_inputs_fingerprint(calibration_inputs),
    )
    return f"{fingerprint_dataframe(frame['df'])}:{model_spec_fingerprint}"


try:
    _resolved_engine = resolve_engine(
        causal_graph=_resolve_causal_graph(),
        search_objects=get_state("search_objects") or [],
    )
except ModelFitServiceError as _engine_error:
    _resolved_engine = None
    st.error(f"This project's approved graph cannot be fit: {_engine_error}")
if _resolved_engine == SEARCH_CANDIDATE_A_ENGINE:
    st.info(
        "This project's approved causal graph requires the **Candidate A Search "
        "mediation/capacity engine** (REQ-SEARCH-002), not the ordinary shared/"
        "market-specific engine. Candidate A Search planning and cap optimisation "
        "remain disabled regardless of fit outcome; see "
        "`REPO_REVIEW_AND_NEXT_STEPS.md` for current integration status."
    )

st.markdown("---")
st.markdown("### Pre-fit prior check")
render_decision_help(
    "What does the prior check do?",
    controls="It samples from the proposed model's prior assumptions before fitting.",
    why="It helps reveal implausible outcome ranges or warnings early, before time is spent fitting the posterior.",
    options={
        "Run it before fitting": "Use it after changing structure or priors and before starting a fit.",
        "Read the outcome-scale ranges": "Look for values or warnings that are inconsistent with the business context.",
        "Treat it as a preview": "It does not fit the model, validate posterior behaviour, or create approval evidence.",
    },
    normal_path="Check the preview, adjust an approved configuration if needed, then build and fit the model.",
    downstream="Changing the setup or priors makes the preview stale. A fit creates separate posterior and diagnostics evidence.",
    invalidates="The preview itself does not invalidate an existing fit, but changing the configuration does; the next fit and approval must use the changed identity.",
)
st.caption(
    "Samples from the proposed model's priors before fitting. This helps you "
    "spot implausible ranges and warnings before committing to a run. It does "
    "not fit the model and does not replace the evidence created by the fitted "
    "model on Model Diagnostics. Run it again after changing the setup or priors."
)
render_technical_details(
    details={
        "Preview method": "Prior-predictive sampling from the proposed model before MCMC fitting; no posterior trace is used.",
        "Freshness": "The preview is bound to the proposed data and model-configuration fingerprint and is marked stale when those inputs change.",
        "Evidence boundary": "Preview output is diagnostic context only. It does not create a model run, readiness result, or approval.",
    }
)
preview_col1, preview_col2 = st.columns(2)
preview_n_samples = preview_col1.number_input(
    "Prior draws",
    min_value=50,
    max_value=5000,
    value=500,
    step=50,
    key="preview_prior_predictive_n_samples",
)
preview_seed = preview_col2.number_input(
    "Random seed",
    min_value=0,
    max_value=2**31 - 1,
    value=42,
    step=1,
    key="preview_prior_predictive_seed",
)
if st.button("Preview prior predictive (no fitting)"):
    try:
        with st.spinner("Building proposed model..."):
            preview_model, preview_meta = _build_proposed_model(model_type)
    except ValueError as e:
        set_state(
            "prior_predictive_preview",
            {
                "status": "failed",
                "error": f"Could not build the proposed model: {e} Set the FH DNA cross-sell outcome on the Structure page if needed, and try again.",
            },
        )
    else:
        try:
            with st.spinner("Sampling priors..."):
                preview_result = prior_predictive_summary(
                    preview_model,
                    frame,
                    preview_meta,
                    n_samples=int(preview_n_samples),
                    random_seed=int(preview_seed),
                )
        except Exception as e:
            set_state(
                "prior_predictive_preview",
                {
                    "status": "failed",
                    "error": f"Prior predictive sampling failed: {e}",
                },
            )
        else:
            set_state(
                "prior_predictive_preview",
                {
                    "status": "computed",
                    "model_type": model_type,
                    "payload": preview_result,
                    "proposed_model_fingerprint": _proposed_model_fingerprint(
                        model_type
                    ),
                },
            )
            _prefit_report = get_state("prefit_identifiability")
            if isinstance(_prefit_report, dict):
                _prefit_report = dict(_prefit_report)
                _prefit_report["prior_predictive"] = preview_result.get(
                    "plausibility",
                    {
                        "status": "not_run",
                        "review_status": "not_run",
                        "diagnostic_only": True,
                    },
                )
                _prefit_states = dict(_prefit_report.get("state_semantics") or {})
                _prefit_states["prior_predictive"] = str(
                    _prefit_report["prior_predictive"].get(
                        "review_status", "review_recommended"
                    )
                )
                _prefit_report["state_semantics"] = _prefit_states
                set_state("prefit_identifiability", _prefit_report)

_preview = get_state("prior_predictive_preview")
# Prior-predictive preview status badge - reuses the exact same staleness
# signal the warning/detail below already computed (proposed_model_
# fingerprint vs. _proposed_model_fingerprint(model_type)); no new
# staleness check is invented here.
if not _preview:
    render_status_badge("not_configured", label="Preview: not yet run")
elif _preview.get("status") == "failed":
    render_status_badge("failed", label="Preview: failed")
elif _preview.get("proposed_model_fingerprint") != _proposed_model_fingerprint(
    model_type
):
    render_status_badge("stale", label="Preview: stale")
else:
    render_status_badge("validated", label="Preview: current")

if _preview and _preview.get("status") == "failed":
    st.error(_preview["error"])
elif _preview and _preview.get("status") == "computed":
    if _preview.get("proposed_model_fingerprint") != _proposed_model_fingerprint(
        model_type
    ):
        st.warning(
            "This preview no longer reflects the current proposed "
            "configuration - the spec, priors, DNA lag, causal graph, or "
            "another model-identity input changed since it was run. "
            "Re-run the preview above to see priors for what would "
            "actually be fit now."
        )
    else:
        _preview_payload = _preview["payload"]
        st.caption(
            f"Model type: {MODEL_TYPE_LABELS.get(_preview['model_type'], _preview['model_type'])} | "
            f"Prior draws: {format_number(_preview_payload.get('n_samples'))} | "
            f"Seed: {_preview_payload.get('random_seed')}"
        )
        _preview_df = pd.DataFrame(_preview_payload["rows"])
        st.dataframe(
            _preview_df,
            width="stretch",
            column_config=dataframe_column_config(_preview_df),
        )
        for w in _preview_payload.get("warnings", []):
            st.caption(f"Sampling warning: {w}")

        _plausibility = _preview_payload.get("plausibility") or {}
        if _plausibility:
            st.markdown("### Prior-predictive observed-scale review")
            st.caption(
                "This is diagnostic evidence from the proposed priors. "
                "No approved threshold policy is applied by default, so finite "
                "results remain review-recommended until an analyst-approved "
                "policy exists."
            )
            _plausibility_rows = [
                {
                    "Outcome": row.get("outcome_id"),
                    "Finite": row.get("finite"),
                    "Status": row.get("status"),
                    "Review": row.get("review_status"),
                    "Observed min": (row.get("observed_quantiles") or {}).get("min"),
                    "Observed median": (row.get("observed_quantiles") or {}).get("q50"),
                    "Observed mean": (row.get("observed_quantiles") or {}).get("mean"),
                    "Observed max": (row.get("observed_quantiles") or {}).get("max"),
                    "Prior q01": (row.get("predictive_quantiles") or {}).get("q01"),
                    "Prior q05": (row.get("predictive_quantiles") or {}).get("q05"),
                    "Prior median": (row.get("predictive_quantiles") or {}).get("q50"),
                    "Prior q95": (row.get("predictive_quantiles") or {}).get("q95"),
                    "Prior q99": (row.get("predictive_quantiles") or {}).get("q99"),
                    "Prior max": (row.get("predictive_quantiles") or {}).get("max"),
                    "q95 / observed median": (
                        row.get("observed_scale_ratios") or {}
                    ).get("q95_to_observed_median"),
                    "q99 / observed max": (row.get("observed_scale_ratios") or {}).get(
                        "q99_to_observed_max"
                    ),
                    "Median / observed median": (
                        row.get("observed_scale_ratios") or {}
                    ).get("median_to_observed_median"),
                }
                for row in _plausibility.get("rows", [])
            ]
            if _plausibility_rows:
                st.dataframe(
                    pd.DataFrame(_plausibility_rows),
                    width="stretch",
                    hide_index=True,
                )
            if _plausibility.get("component_decomposition", {}).get("status") == (
                "unavailable"
            ):
                st.caption(
                    "Component decomposition is unavailable because the current "
                    "prior preview retains outcome draws only."
                )

st.markdown("### Fit action")
st.caption(
    "Build the proposed model and start sampling. A new fit creates a new run identity and clears any previous approval."
)
_official_result = get_state("official_preparation_result")
_frame_mode = frame.get("preparation_mode")
# UX-017 fix: this gate exists to block an *official* fit while official
# preparation is itself unresolved (per this block's own error message
# below, and REQ-PREFIT-001's scope of "official production-fit
# submission"). It must not apply to an exploratory frame at all - Model
# Setup's "Prepare exploratory modelling frame" button explicitly describes
# that frame as "available for investigation only", and the sibling
# `_prefit_gate_reasons` check immediately below already correctly scopes
# itself to `_frame_mode == "official"` only. Before this fix,
# `_frame_mode != "official"` meant the opposite of the intended scoping -
# it blocked every exploratory frame unconditionally (regardless of whether
# official preparation was actually unresolved) and never blocked an
# official frame whose own official preparation was genuinely unresolved
# but merely absent from session state. Checking `.get("ready", False)`
# (from `OfficialPreparationResult.to_dict()`) rather than mere dict
# presence/truthiness also matches this block's own wording ("while
# official preparation is unresolved") to what is actually evaluated.
_official_fit_gate_blocked = (
    _frame_mode == "official"
    and isinstance(_official_result, dict)
    and bool(_official_result)
    and not _official_result.get("ready", False)
)
_prefit_gate_reasons = []
if _frame_mode == "official":
    # REQ-PREFIT-001 (Work Package 1 correction): consult the one governed
    # PrefitRun (core.prefit_run) rather than re-deriving a blocking
    # decision from scattered sub-fields of two independently-shaped
    # evidence dicts - see pages/04_Model_Config.py, which (re)builds this
    # object any time either evidence report changes.
    _prefit_run_for_gate = get_state("prefit_run")
    if not isinstance(_prefit_run_for_gate, dict):
        _prefit_gate_reasons.append(
            "run the pre-fit support review and deterministic screen on Model Setup"
        )
    else:
        _allowed, _reason = official_submission_allowed(_prefit_run_for_gate)
        if not _allowed:
            _prefit_gate_reasons.append(_reason)
    if not (
        isinstance(_preview, dict)
        and _preview.get("status") == "computed"
        and _preview.get("proposed_model_fingerprint")
        == _proposed_model_fingerprint(model_type)
    ):
        _prefit_gate_reasons.append(
            "run a current prior-predictive preview before fitting"
        )
if _prefit_gate_reasons:
    _official_fit_gate_blocked = True
if _official_fit_gate_blocked:
    if _prefit_gate_reasons:
        st.error(
            "Official fitting is blocked by the mandatory pre-fit gate: "
            + "; ".join(_prefit_gate_reasons)
            + "."
        )
    else:
        st.error(
            "Fitting is blocked for this official frame because official "
            "preparation is unresolved. Return to Model Setup and resolve the "
            "official preparation review before fitting an official run."
        )
if (not _official_fit_gate_blocked) and st.button("Build & fit model", type="primary"):
    try:
        with st.spinner("Building model..."):
            model, meta = _build_proposed_model(model_type)
    except ValueError as e:
        st.error(
            f"Could not build the model: {e} Set the FH DNA cross-sell outcome on the Structure page if needed, and try again."
        )
        st.stop()
    st.success(f"Model built ({MODEL_TYPE_LABELS[model_type]}).")

    # Read MCMC settings on the main thread: st.session_state (get_state) is
    # bound to Streamlit's script-run context, which a plain background
    # thread doesn't have - calling get_state() from inside _run() silently
    # returns None instead of the real value.
    mcmc_draws = get_state("mcmc_draws")
    mcmc_tune = get_state("mcmc_tune")
    mcmc_chains = get_state("mcmc_chains")
    mcmc_target_accept = get_state("mcmc_target_accept")

    progress_state = {"done": 0, "total": 1, "error": None, "trace": None}

    def _run():
        try:
            trace = fit_model(
                model,
                draws=mcmc_draws,
                tune=mcmc_tune,
                chains=mcmc_chains,
                target_accept=mcmc_target_accept,
                progress_callback=lambda done, total: progress_state.update(
                    done=done, total=total
                ),
                cores=1,
            )
            progress_state["trace"] = trace
        except Exception as e:  # surfaced in the UI, not swallowed
            progress_state["error"] = str(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    progress_bar = st.progress(0.0)
    status = st.empty()
    while thread.is_alive():
        frac = min(1.0, progress_state["done"] / max(progress_state["total"], 1))
        progress_bar.progress(frac)
        status.caption(
            f"Sampling: {format_number(progress_state['done'])} / {format_number(progress_state['total'])} draws"
        )
        time.sleep(0.5)
    thread.join()
    progress_bar.progress(1.0)

    if progress_state["error"]:
        st.error(
            f"Sampling failed: {progress_state['error']} Try fewer draws/chains, or simplify the hierarchy, and fit again."
        )
    else:
        trace = progress_state["trace"]
        posterior_params = (
            extract_market_specific_posterior_params(trace, meta)
            if model_type == "market_specific"
            else extract_posterior_params(trace, meta)
        )
        set_state("model", model)
        set_state("model_meta", meta)
        set_state("trace", trace)
        set_state("model_trained", True)
        set_state("posterior_params", posterior_params)
        set_state("model_type", model_type)
        # A fresh fit is a new model run, full stop - mint a new identity and
        # drop any approval that was sitting in session state, even if this
        # is a re-run of the same spec on the same data (retraining always
        # invalidates the previous approval; clear_model_state() covers the
        # "upstream config changed" path, this covers "user just refit").
        set_state("model_run_id", str(uuid.uuid4()))
        set_state("model_approval", None)
        migration_review = get_state("migration_review")
        if (
            isinstance(migration_review, dict)
            and migration_review.get("migration_review_status")
            == "reviewed_refit_required"
        ):
            migration_review = dict(migration_review)
            migration_review.update(
                migration_review_status="refit_completed",
                replacement_model_run_id=get_state("model_run_id"),
            )
            set_state("migration_review", migration_review)
        st.success(f"Model trained ({MODEL_TYPE_LABELS[model_type]}).")

if get_state("model_trained"):
    st.markdown("---")
    with SectionCard(
        "Completed fit",
        description="The identity of the model run currently in session.",
    ):
        render_status_badge("validated", label="Trained")
        _completed_run_id = get_state("model_run_id") or ""
        st.markdown(f"""
- **Model structure:** {MODEL_TYPE_LABELS[get_state("model_type")]}
- **Approval status:** {"Approved" if get_state("model_approval") else "Not yet approved"}
""")
        render_technical_details(
            details={
                "Model run ID": _completed_run_id or "Unknown",
                "Sampling configuration": f"{format_number(get_state('mcmc_draws'))} draws, {format_number(get_state('mcmc_tune'))} tune, {get_state('mcmc_chains')} chains",
                "Posterior identity": "The run ID, data fingerprint, model specification, and posterior artefact identity bind the fit to its diagnostics and approval evidence.",
            }
        )

    st.markdown("### Save as a comparison candidate")
    st.caption(
        "Optional: record this fit's scorecard so it can be compared side by side with other "
        "candidates (a different model structure, or the same structure on a different market "
        "selection) on Compare Models."
    )
    candidate_label = st.text_input(
        "Candidate label",
        value=f"{MODEL_TYPE_LABELS[get_state('model_type')]} - {', '.join(frame['markets'])}",
    )
    if st.button("Save this fit as a comparison candidate"):
        trace = get_state("trace")
        current_meta = get_state("model_meta")
        current_type = get_state("model_type")
        with st.spinner("Computing scorecard for comparison..."):
            scorecard = (
                compute_scorecard_market_specific(trace, frame, current_meta)
                if current_type == "market_specific"
                else compute_scorecard(trace, frame, current_meta)
            )
        candidate = ModelComparisonCandidate.from_scorecard(
            model_type="C" if current_type == "market_specific" else "A",
            label=candidate_label,
            model_run_id=get_state("model_run_id"),
            fitted_at=time.time(),
            scorecard=scorecard,
            market=frame["markets"][0] if len(frame["markets"]) == 1 else None,
        )
        candidates = get_state("model_comparison_candidates") or []
        candidates.append(candidate.to_dict())
        set_state("model_comparison_candidates", candidates)
        st.success(f"Saved '{candidate_label}' as a comparison candidate.")

    render_next_step("model_training")
