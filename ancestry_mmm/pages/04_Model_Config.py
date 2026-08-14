"""Page 4: interface-driven model configuration - hierarchy, adstock/saturation priors, DNA halo lag, MCMC settings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    clear_model_state,
    DEFAULT_FH_PRIORS,
    format_number,
    FIELD_HELP,
    readable_label,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_drift_status,
    page_readiness,
    render_workspace_note,
    render_definition_help,
    render_decision_help,
    render_technical_details,
    render_status_badges,
    SectionCard,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.outcomes import (
    resolve_outcome_definitions,
    dna_kit_outcome_columns,
    included_outcomes,
)
from ancestry_mmm.core.brand_search import (
    BrandSearchConfig,
    MODE_ASSUMPTION_BASED_REALLOCATION,
    MODE_DEMAND_CAPTURE_MEDIATOR,
    MODE_DIRECT_CHANNEL,
    MODE_EXCLUDED,
    MODE_EXPERIMENTAL_FITTED_MEDIATION,
    MODE_EXPERIMENT_CALIBRATED_INCREMENTAL,
    validate_brand_search_configs,
)
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.fingerprint import fingerprint_dataframe
from ancestry_mmm.core.frequency_alignment import assess_official_preparation
from ancestry_mmm.core.market_data_capability import check_market_channel_capability
from ancestry_mmm.core.official_preparation import (
    build_official_capability_report,
    prepare_canonical_native_frame,
    OfficialPreparationDataError,
)
from ancestry_mmm.data import (
    adopted_model_input_frame,
    adopted_model_input_sources,
    prepare_fh_modeling_frame,
)
import pandas as pd

BRAND_SEARCH_MODE_LABELS = {
    MODE_DIRECT_CHANNEL: "Treat as direct paid Search",
    MODE_EXCLUDED: "Exclude from the fit",
    MODE_ASSUMPTION_BASED_REALLOCATION: "Assumption-adjusted demand capture (diagnostic)",
    MODE_DEMAND_CAPTURE_MEDIATOR: "Demand-capture sensitivity (diagnostic)",
    MODE_EXPERIMENTAL_FITTED_MEDIATION: "Experimental fitted mediation (not production)",
    MODE_EXPERIMENT_CALIBRATED_INCREMENTAL: "Experiment-calibrated incrementality",
}
BRAND_SEARCH_MODE_BY_LABEL = {
    label: mode for mode, label in BRAND_SEARCH_MODE_LABELS.items()
}

CAPABILITY_STATUS_LABELS = {
    "supported": "Ready",
    "unsupported": "Needs review",
}

st.set_page_config(
    page_title="Model Setup | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("model_config")
render_page_header(
    "model_config",
    task_prompt="Which modelling assumptions should this fit use?",
    badges=[page_readiness("model_config")],
)
render_workspace_note(
    "Fit assumptions",
    "Market and outcome scope is read from Structure. Edit pooling, curve, prior, and sampling assumptions here.",
    kind="editable",
)

spec_dict = get_state("model_spec")
df = get_state("transformed_data")
if df is None:
    df = adopted_model_input_frame(
        outcome_data=get_state("standard_outcome_data"),
        activity_model_input=get_state("standard_activity_model_input"),
        context_model_input=get_state("standard_context_data"),
    )
if not spec_dict or df is None:
    st.markdown("---")
    render_empty_state(
        "No model structure defined yet. Complete Model Structure first.",
        button_label="Go to Model Structure",
        target_key="structure",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
outcome_definitions = resolve_outcome_definitions(
    get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv
)


def _outcome_display_label(outcome) -> str:
    label = " · ".join(
        str(part).strip()
        for part in (outcome.product, outcome.segment, outcome.metric)
        if str(part).strip()
    )
    if outcome.definition_version:
        label += f" (definition {outcome.definition_version})"
    return label or readable_label(outcome.outcome_id)


outcome_display_labels = {
    outcome.outcome_id: _outcome_display_label(outcome)
    for outcome in outcome_definitions
}

with st.container(border=True):
    st.markdown("### Model setup summary")
    st.caption(
        "A read-only snapshot of the current structure and prepared-frame state. Routine choices are below; advanced statistical controls are kept separate."
    )
    summary_cols = st.columns(4)
    summary_cols[0].metric("Markets", len(spec.markets))
    summary_cols[1].metric(
        "Outcomes in scope",
        sum(1 for outcome in outcome_definitions if outcome.included_in_fit),
    )
    summary_cols[2].metric("Model inputs", len(spec.channels))
    summary_cols[3].metric(
        "Prepared frame", "Ready" if get_state("frame") is not None else "Not prepared"
    )
    st.caption(
        "Pooling strategy: "
        f"{'Market-specific' if get_state('model_type') == 'market_specific' else 'Shared'} · "
        "change it in Model strategy below."
    )

st.markdown("---")
with SectionCard(
    "Model strategy · market pooling",
    description="Read-only here - change markets/pooling on the Structure page.",
):
    st.info(
        f"Markets: {', '.join(spec.markets)}. "
        f"Partially pooled: {', '.join(m for m in spec.markets if m not in spec.unpooled_markets) or '(none)'}. "
        f"Unpooled: {', '.join(spec.unpooled_markets) or '(none)'} "
        "- change this back on the Structure page."
    )

st.markdown("---")
_model_structure_section = SectionCard(
    "Model strategy",
    description="Shared curve across markets, or market-specific partially-pooled curves.",
)
_model_structure_section.__enter__()
render_definition_help(
    "partial pooling",
    "Markets get their own response estimates while borrowing strength from the other markets, so smaller markets are less likely to produce unstable curves.",
)
render_decision_help(
    "How should I choose the model strategy?",
    controls="Whether channel response is shared across markets or allowed to vary with partial pooling.",
    why="The choice balances stability against local market differences. More flexibility is useful only when the data can identify it.",
    options={
        "Shared response": "Use when a common curve is a reasonable starting point or market-level data are limited.",
        "Market-specific with partial pooling": "Use when markets may differ but should still borrow strength; this is often the practical middle path.",
        "Unpooled market response": "Available through Structure for an approved use case where markets are structurally distinct and well supported.",
    },
    normal_path="Start with the shared or partially pooled strategy, inspect convergence, predictive fit, coverage, and plausibility, then decide what to take forward.",
    downstream="It changes the parameter structure, the curves available by market, and the evidence that Diagnostics and Planning Curves can review.",
    invalidates="Changing the strategy changes the model identity. Fit again, recompute diagnostics, and repeat approval before governed reporting or planning.",
)
n_markets = len(spec.markets)
model_type_options = ["shared", "market_specific"]
model_type_labels = {
    "shared": "Shared response across markets",
    "market_specific": "Market-specific response with partial pooling",
}
current_model_type = get_state("model_type", "shared")
if n_markets < 2 and current_model_type == "market_specific":
    st.warning(
        "Market-specific curves need at least 2 markets; this project has 1. Falling back to the "
        "shared-curve model. Add another market on Model Structure to use "
        "market-specific curves."
    )
    current_model_type = "shared"
model_type = st.radio(
    "Choose how channel response curves are estimated across markets",
    model_type_options,
    index=model_type_options.index(current_model_type),
    format_func=lambda t: model_type_labels[t],
    disabled=(n_markets < 2),
    help=FIELD_HELP["model_type_shared"]
    if current_model_type == "shared"
    else FIELD_HELP["model_type_market_specific"],
)
if n_markets < 2:
    st.caption(
        "Only 1 market in this project - market-specific curves are unavailable until there are at least 2."
    )
st.caption(
    FIELD_HELP["model_type_market_specific"]
    if model_type == "market_specific"
    else FIELD_HELP["model_type_shared"]
)
_model_structure_section.__exit__(None, None, None)

st.markdown("---")
_priors_section = SectionCard(
    "Media response assumptions",
    description="Response curves, cross-product effects, promotions, and Search treatment for the next fit.",
)
_priors_section.__enter__()
st.markdown("#### Response curve assumptions")
st.caption(FIELD_HELP["priors"])

prior_config = {
    **DEFAULT_FH_PRIORS,
    **(get_state("prior_config") or {}),
}

with st.expander("Advanced model assumptions", expanded=False):
    st.caption(
        "These controls set the model's starting assumptions. Most analysts can keep the defaults; open this area when the data or an approved modelling decision calls for a change."
    )
    st.markdown("#### Media carryover and saturation")
    c1, c2 = st.columns(2)
    with c1:
        prior_config["decay_mu"] = st.slider(
            "Typical media carryover",
            0.05,
            0.95,
            float(prior_config["decay_mu"]),
            0.05,
            help=FIELD_HELP["adstock_decay"]
            + " Technical name: adstock decay prior mean.",
        )
        prior_config["decay_sigma"] = st.slider(
            "How uncertain is carryover?",
            0.05,
            0.5,
            float(prior_config["decay_sigma"]),
            0.05,
            help="Technical name: adstock decay prior standard deviation.",
        )
        prior_config["K_scale"] = st.slider(
            "Spend level where saturation starts",
            0.3,
            3.0,
            float(prior_config["K_scale"]),
            0.1,
            help=FIELD_HELP["hill_saturation"]
            + " Technical name: saturation half-point K prior mean.",
        )
    with c2:
        prior_config["S_alpha"] = st.slider(
            "Saturation curve shape",
            1.0,
            10.0,
            float(prior_config["S_alpha"]),
            0.5,
            help="Technical name: saturation-shape Gamma alpha.",
        )
        prior_config["S_beta"] = st.slider(
            "Saturation curve uncertainty",
            1.0,
            10.0,
            float(prior_config["S_beta"]),
            0.5,
            help="Technical name: saturation-shape Gamma beta.",
        )

    st.markdown("#### How much markets and segments may differ")
    st.caption(
        "These settings control how strongly related markets, segments, and cross-product pathways share information."
    )
    c1, c2 = st.columns(2)
    with c1:
        prior_config["pooling_sigma_prior"] = st.slider(
            "How much segments may differ",
            0.05,
            1.0,
            float(prior_config["pooling_sigma_prior"]),
            0.05,
            help=FIELD_HELP["partial_pooling"]
            + " Technical name: pooling sigma prior.",
        )
        prior_config["market_pool_sigma_prior"] = st.slider(
            "How much market responses may differ",
            0.05,
            1.0,
            float(prior_config["market_pool_sigma_prior"]),
            0.05,
            help=FIELD_HELP["partial_pooling"]
            + " Technical name: market pooling sigma prior.",
        )
    with c2:
        prior_config["active_cross_product_sigma"] = st.slider(
            "Strength allowed for active cross-product effects",
            0.05,
            1.0,
            float(prior_config.get("active_cross_product_sigma", 0.25)),
            0.05,
            help="Kept tight by default because cross-product effects should be smaller unless the pathway catalogue marks them active.",
        )
        prior_config["exploratory_cross_product_sigma"] = st.slider(
            "Strength allowed for exploratory cross-product effects",
            0.02,
            0.5,
            float(prior_config.get("exploratory_cross_product_sigma", 0.08)),
            0.02,
            help="Strongly shrunk toward zero by default and not trusted for planning. Technical name: exploratory cross-product sigma.",
        )
        dna_lag_weeks = st.number_input(
            "Extra DNA cross-product delay (weeks)",
            min_value=0,
            max_value=12,
            value=int(get_state("dna_lag_weeks", 4)),
            help=FIELD_HELP["dna_halo_lag"],
        )

    st.markdown("#### Promotion sensitivity")
    prior_config["promo_sigma"] = st.slider(
        "How much promotions may change response",
        0.05,
        1.5,
        float(prior_config["promo_sigma"]),
        0.05,
        help="Technical name: promotion sensitivity prior standard deviation.",
    )

render_technical_details(
    details={
        "Response model": "Stage 1 uses geometric adstock followed by Hill saturation for the fitted response terms, shared across segments and markets per channel.",
        "Media transformation": "The current model uses the configured adstock carryover and Hill saturation assumptions for fitted response terms.",
        "Pooling controls": "The advanced controls set prior scales for segment differences, market differences, active cross-product effects, and exploratory cross-product effects.",
        "Exact values": "The saved prior configuration, DNA lag, Search treatment, and model strategy are retained in the model specification and fingerprint.",
    }
)

st.markdown("#### Search treatment")
render_decision_help(
    "How should I treat Paid Search?",
    controls="Whether Search is fitted as a direct channel, excluded, shown as a diagnostic demand-capture view, or calibrated with experiment evidence.",
    why="Search demand, paid delivery, paid spend, organic traffic, direct navigation, and a cap represent different parts of the funnel. A post-hoc reallocation is not fitted mediation.",
    options={
        "Direct paid Search": "Use when the selected Search input is treated as a direct channel in the fit.",
        "Excluded": "Use when Search should not be fitted; the governed Search and pathway records still need to be coherent.",
        "Diagnostic or calibrated view": "Use for assumption-based demand capture, experimental mediation, or experiment-calibrated incrementality; these labels do not make the view production mediation.",
    },
    normal_path="Choose the treatment that matches the approved causal interpretation, keep its Search objects mapped separately, then review the evidence before planning use.",
    downstream="The choice changes the fitted or diagnostic outputs and the pathways that can be considered for attribution, planning, or optimisation.",
    invalidates="Changing Search treatment changes the model specification or its evidence interpretation. Refit and repeat the relevant diagnostics and approvals.",
)
st.caption(
    "Choose an explicit interpretation for paid Search. Direct and excluded are fit choices; demand-capture and experiment-calibrated options are labelled sensitivity or calibration views. "
    "A post-hoc demand-capture reallocation is not production mediation, and excluding Search from the fit still requires the matching pathway role on Model Structure."
)
if "brand_search_configs" not in st.session_state:
    st.session_state["brand_search_configs"] = get_state("brand_search_configs") or []
if st.session_state["brand_search_configs"]:
    # mediator_of is stored as a real list (BrandSearchConfig.mediator_of) -
    # st.column_config.TextColumn can't bind to a list-typed column, so it's
    # rendered/edited as a comma-joined string and parsed back to a list below.
    _brand_search_default_df = pd.DataFrame(
        [
            {**row, "mediator_of": ", ".join(row.get("mediator_of") or [])}
            for row in st.session_state["brand_search_configs"]
        ]
    )
else:
    _brand_search_default_df = pd.DataFrame(
        columns=[
            "channel",
            "mode",
            "mediator_of",
            "mediation_share",
            "calibration_factor",
            "notes",
        ]
    )
if not _brand_search_default_df.empty:
    _brand_search_default_df["mode"] = _brand_search_default_df["mode"].map(
        lambda mode: BRAND_SEARCH_MODE_LABELS.get(mode, mode)
    )
brand_search_df = st.data_editor(
    _brand_search_default_df,
    num_rows="dynamic",
    column_config={
        "channel": st.column_config.SelectboxColumn(
            "Search channel", options=spec.channels, required=True
        ),
        "mode": st.column_config.SelectboxColumn(
            "Treatment", options=list(BRAND_SEARCH_MODE_LABELS.values()), required=True
        ),
        "mediator_of": st.column_config.TextColumn(
            "Upstream channels",
            help="Comma-separated channels whose demand this Search treatment is intended to capture; only used for the demand-capture sensitivity view.",
        ),
        "mediation_share": st.column_config.NumberColumn(
            "Demand-capture share",
            min_value=0.0,
            max_value=1.0,
            help="Only used for the demand-capture sensitivity view.",
        ),
        "calibration_factor": st.column_config.NumberColumn(
            "Experiment calibration factor",
            min_value=0.0,
            max_value=1.0,
            help="Only used when an experiment-calibrated incrementality view is selected.",
        ),
        "notes": st.column_config.TextColumn("Analyst notes"),
    },
    key="brand_search_config_editor",
    width="stretch",
)
brand_search_configs = []
for row in brand_search_df.to_dict("records"):
    if not (row.get("channel") and row.get("mode")):
        continue  # a blank row added by the editor but never filled in
    mode = BRAND_SEARCH_MODE_BY_LABEL.get(str(row["mode"]), str(row["mode"]))
    mediator_of = [
        c.strip() for c in str(row.get("mediator_of") or "").split(",") if c.strip()
    ]
    brand_search_configs.append(
        BrandSearchConfig(
            channel=row["channel"],
            mode=mode,
            mediator_of=mediator_of,
            mediation_share=row.get("mediation_share"),
            calibration_factor=row.get("calibration_factor"),
            notes=row.get("notes") or "",
        )
    )
brand_search_errors = validate_brand_search_configs(
    brand_search_configs, known_channels=spec.channels
)
for e in brand_search_errors:
    st.error(e)
_priors_section.__exit__(None, None, None)

st.markdown("---")
with st.expander("Advanced sampling", expanded=False):
    st.caption(
        "Reasonable defaults are pre-filled. Increase draws/tune for a more reliable fit; reduce them for a quicker check."
    )
    c1, c2, c3, c4 = st.columns(4)
    mcmc_draws = c1.number_input(
        "Draws",
        min_value=200,
        max_value=5000,
        value=int(get_state("mcmc_draws", 2000)),
        step=200,
        key="mcmc_draws_input",
    )
    mcmc_tune = c2.number_input(
        "Tune",
        min_value=200,
        max_value=5000,
        value=int(get_state("mcmc_tune", 1000)),
        step=200,
        key="mcmc_tune_input",
    )
    mcmc_chains = c3.number_input(
        "Chains",
        min_value=1,
        max_value=8,
        value=int(get_state("mcmc_chains", 4)),
        key="mcmc_chains_input",
    )
    mcmc_target_accept = c4.slider(
        "Target accept",
        0.7,
        0.99,
        float(get_state("mcmc_target_accept", 0.9)),
        0.01,
        key="mcmc_target_accept_input",
    )

render_decision_help(
    "How should I choose sampling settings?",
    controls="The number of posterior draws, tuning steps, chains, and the target acceptance rate used when fitting.",
    why="More sampling can improve the reliability of convergence evidence but costs time. These controls do not change the business definition of an outcome.",
    options={
        "Default settings": "Use for the normal fit when the model is behaving as expected.",
        "More draws or tuning": "Use when convergence or effective sample size needs more evidence and the fit can take longer.",
        "Higher target acceptance": "Use as a diagnostic response to sampling problems, with the trade-off of slower sampling.",
    },
    normal_path="Start with the defaults, then respond to Diagnostics evidence rather than changing settings speculatively.",
    downstream="Sampling settings change the posterior evidence and therefore the model identity and downstream diagnostics.",
    invalidates="Changing them requires a new fit and fresh diagnostics; an existing approval cannot be carried across a changed fit.",
)

render_drift_status(
    outcome_definitions, get_state("model_meta"), available_columns=set(df.columns)
)
included_outcome_definitions = included_outcomes(outcome_definitions)
dna_kit_outcomes = dna_kit_outcome_columns(included_outcome_definitions)
dna_kit_outcomes = {
    oid: col for oid, col in dna_kit_outcomes.items() if col in df.columns
}
excluded_dna_outcomes = [o for o in outcome_definitions if not o.included_in_fit]

st.markdown("---")
_included_outcomes_section = SectionCard(
    "Included outcomes & current scope",
    description="Which outcomes and DNA-kit segments this fit will actually cover.",
)
_included_outcomes_section.__enter__()
if excluded_dna_outcomes:
    st.caption(
        "Excluded from this fit (see Structure): "
        + ", ".join(
            outcome_display_labels.get(
                outcome.outcome_id, readable_label(outcome.outcome_id)
            )
            for outcome in excluded_dna_outcomes
        )
        + "."
    )
if dna_kit_outcomes:
    st.info(
        "DNA outcomes mapped on Structure will be included in this fit: "
        + ", ".join(
            outcome_display_labels.get(outcome_id, readable_label(outcome_id))
            for outcome_id in dna_kit_outcomes
        )
        + ". "
        "DNA-targeted media gets full direct response on these outcomes, same as the FH DNA-cross-sell "
        "outcome, separate from the cross-product halo pathway used for other outcomes."
    )
else:
    st.caption(
        "No DNA outcomes mapped (or their columns aren't in the current data) - fitting Family "
        "History segments only. Map DNA kit columns on Model Structure to include them."
    )
if spec.dna_channels and not spec.fh_dna_cross_sell_outcome_id:
    st.warning(
        "DNA-targeted media is configured but no FH DNA cross-sell outcome was selected on the "
        "Model Structure - Fit Model will stop until one is chosen there (automatic "
        "name-based inference is no longer used for a live fit)."
    )
_included_outcomes_section.__exit__(None, None, None)

st.markdown("---")
_coverage_section = SectionCard(
    "Data coverage & fit support",
    description="Whether this market × channel configuration is supported by the current fit path.",
)
_coverage_section.__enter__()
st.caption(
    "The current fit supports a complete market × channel matrix: every "
    "requested channel must be genuinely observed in every requested "
    "market. This support check does not block exploratory preparation or "
    "fitting; it reports whether the configuration is within today's "
    "supported fit scope. The governed coverage matrix is the source of "
    "truth - never the prepared data's own zero/null values."
)
_coverage_matrix_dict = get_state("variable_coverage_matrix")
_coverage_matrix = (
    VariableCoverageMatrix.from_dict(_coverage_matrix_dict)
    if _coverage_matrix_dict
    else None
)
# Review finding (PR #158): always run the same check, even with no matrix
# at all - "no coverage matrix" must be classified exploratory/unsupported
# (REQ-COVERAGE-001 S6 point 3), not silently skipped. The no-matrix branch
# below stays a calm st.info (not st.warning) since this is every project's
# normal starting state (Data Coverage is optional) - severity is about
# tone, not about hiding that the configuration is genuinely unsupported.
_capability = check_market_channel_capability(
    spec.markets, spec.channels, _coverage_matrix
)
if _coverage_matrix is None:
    st.info(
        "No coverage matrix built yet for this project - every requested "
        "market/channel combination is therefore exploratory/unsupported "
        "today. Build one on the Coverage & Gaps page "
        "to see whether this configuration is within today's supported fit "
        "scope before fitting."
    )
elif _capability.supported:
    # Review finding (PR #158): a matrix built against an earlier Transform
    # Pipeline join (or restored from an imported project bundle) can drift
    # out of sync with the *current* joined data - mirrors the live
    # fingerprint comparison on the Data Coverage page (pages/15_Data_
    # Coverage.py) rather than baking a build-time fingerprint into the
    # portable matrix itself, so it also catches a data change made after
    # the matrix was last built.
    _built_against_fingerprint = get_state(
        "variable_coverage_matrix_built_against_fingerprint"
    )
    if _built_against_fingerprint != fingerprint_dataframe(df):
        st.warning(
            "This configuration's coverage matrix may be stale: the prepared "
            "inputs have changed (or this matrix was restored from an "
            "imported project) since it was last built. Rebuild it on the "
            "Data Coverage page to confirm this configuration is still "
            "within today's supported fit scope."
        )
    else:
        st.success(
            "Every requested market/channel combination has governed, "
            "officially-resolved coverage - this configuration is within "
            "today's supported fit scope."
        )
else:
    st.warning(
        "This configuration goes beyond today's supported market/channel "
        "coverage - treat any resulting fit as exploratory, not "
        "official, until every cell below is resolved (Data Coverage "
        "page) or approved for official use:\n\n"
        + "\n".join(
            f"- **{issue.market} / {issue.channel}**: {issue.reason}"
            for issue in _capability.issues
        )
    )
    st.caption(_capability.decision_report)
_coverage_section.__exit__(None, None, None)

st.markdown("---")
_frequency_section = SectionCard(
    "Official preparation · mixed-frequency review",
    description=(
        "Official preparation must use an approved, variable-class-specific "
        "frequency method. Native source data and the exploratory Transform "
        "Pipeline remain unchanged while that decision is unresolved. "
        "Exploratory preparation is clearly separate and never approves "
        "frequency treatment for official modelling."
    ),
)
_frequency_section.__enter__()
_canonical_calendar = get_state("canonical_calendar") or {}
st.caption(
    "Set the project calendar explicitly before official preparation. The "
    "calendar is not inferred from the shortest source, the current inner "
    "join, or observed dates."
)
_calendar_start_col, _calendar_end_col, _calendar_frequency_col = st.columns(3)
_calendar_start = _calendar_start_col.text_input(
    "Governed start (YYYY-MM-DD)", value=str(_canonical_calendar.get("start") or "")
)
_calendar_end = _calendar_end_col.text_input(
    "Governed end (YYYY-MM-DD)", value=str(_canonical_calendar.get("end") or "")
)
_calendar_frequency_options = ["weekly"]
_calendar_frequency = _calendar_frequency_col.selectbox(
    "Governed frequency (current official path)",
    _calendar_frequency_options,
    index=(
        _calendar_frequency_options.index(
            str(_canonical_calendar.get("frequency") or "weekly").lower()
        )
        if str(_canonical_calendar.get("frequency") or "weekly").lower()
        in _calendar_frequency_options
        else 0
    ),
)
if st.button("Save governed calendar"):
    try:
        from ancestry_mmm.core.frequency_alignment import resolve_canonical_calendar

        _saved_calendar = resolve_canonical_calendar(
            governed_start=_calendar_start.strip(),
            governed_end=_calendar_end.strip(),
            governed_frequency=_calendar_frequency,
        ).to_dict()
        if _canonical_calendar.get("as_of"):
            _saved_calendar["as_of"] = _canonical_calendar["as_of"]
        set_state("canonical_calendar", _saved_calendar)
        clear_model_state()
        st.success(
            "Governed project calendar saved. Re-run official preparation review."
        )
        _canonical_calendar = _saved_calendar
    except (TypeError, ValueError) as exc:
        st.error(f"Governed calendar was not saved: {exc}")

_official_capability_report = build_official_capability_report(
    spec,
    outcome_definitions,
    _coverage_matrix,
    activity_definitions=get_state("activity_definitions") or [],
    search_objects=get_state("search_objects") or [],
    pipeline_steps=get_state("pipeline_steps") or [],
)
set_state("official_capability_report", _official_capability_report.to_dict())
_official_preparation = assess_official_preparation(
    _coverage_matrix,
    governed_start=_canonical_calendar.get("start"),
    governed_end=_canonical_calendar.get("end"),
    governed_frequency=_canonical_calendar.get("frequency"),
    as_of=_canonical_calendar.get("as_of"),
    consumed_variable_ids=tuple(
        item.variable_id for item in _official_capability_report.consumed_variables
    ),
    capability_evidence=_official_capability_report.to_dict(),
)
set_state("official_preparation_result", _official_preparation.to_dict())

if _official_preparation.ready:
    _official_status_label = "Official preparation ready"
    _official_status_badge = "ready"
    _official_status_reason = (
        "The reviewed variables are already at the governed target frequency, "
        "so no frequency conversion is needed."
    )
elif _official_preparation.status == "unsupported_no_approved_method":
    _official_status_label = "Official preparation unavailable"
    _official_status_badge = "blocked"
    _official_status_reason = (
        "No approved method currently exists for converting one or more source "
        "frequencies for official modelling."
    )
elif _official_preparation.status == "method_available":
    _official_status_label = "Official preparation blocked"
    _official_status_badge = "blocked"
    _official_status_reason = (
        "An approved frequency method is available, but the governed conversion "
        "executor has not been validated for official modelling yet."
    )
elif _official_preparation.status == "unsupported_definition_break":
    _official_status_label = "Official preparation blocked"
    _official_status_badge = "blocked"
    _official_status_reason = (
        "The reviewed frequency definition changes across the available source "
        "support, so official preparation needs an explicit resolution."
    )
elif _official_preparation.status == "unsupported_leakage":
    _official_status_label = "Official preparation blocked"
    _official_status_badge = "blocked"
    _official_status_reason = (
        "The reviewed frequency treatment would use information outside the "
        "approved preparation boundary. Resolve the frequency decision before "
        "official modelling."
    )
else:
    _official_status_label = "Official preparation blocked"
    _official_status_badge = "blocked"
    _official_status_reason = (
        "Required coverage, calendar, or frequency decisions are still needed "
        "before official modelling can be prepared."
    )

_status_col, _conversion_col = st.columns(2)
with _status_col:
    render_status_badges([_official_status_badge])
    st.markdown(f"**{_official_status_label}**")
    st.caption(_official_status_reason)
with _conversion_col:
    _conversion_classes = _official_preparation.conversion_variable_classes
    st.metric(
        "Frequency conversion needed",
        "Yes" if _conversion_classes else "No",
    )
    if _conversion_classes:
        st.caption(
            "Reviewed variable classes: "
            + ", ".join(
                str(variable_class).replace("_", " ").title()
                for variable_class in _conversion_classes
            )
        )

st.markdown("**Next action**")
if _official_preparation.ready:
    st.caption("Prepare the official modelling frame below.")
else:
    st.caption(
        "Resolve the decisions listed below before official modelling. You may "
        "prepare an exploratory frame for investigation, but it remains "
        "restricted from official reporting, planning, and optimisation."
    )
if _official_preparation.decisions_required:
    with st.expander("Decisions needed before official preparation"):
        st.caption(
            "These are governance decisions, not defaults. No interpolation, "
            "allocation, forward-fill, or other frequency conversion is "
            "performed by this page."
        )
        for _decision in _official_preparation.decisions_required:
            st.markdown(f"- {_decision}")

with st.expander("Consumed-variable capability evidence"):
    st.caption(
        "Only source-backed variables used by the compiled proposal can block "
        "official preparation. Gaps on unconsumed variables remain visible in "
        "Data Coverage but do not block this fit. Fourier and trend terms are "
        "reported as deterministic generated terms, not source coverage."
    )
    _capability_rows = [
        {
            "Variable": item.variable_id,
            "Role(s)": ", ".join(item.roles),
            "Status": CAPABILITY_STATUS_LABELS.get(
                item.status, readable_label(item.status)
            ),
            "Issues": "; ".join(item.issues),
        }
        for item in _official_capability_report.consumed_variables
    ]
    if _capability_rows:
        st.dataframe(pd.DataFrame(_capability_rows), width="stretch", hide_index=True)
    else:
        st.caption("No source-backed variables are resolved from the current proposal.")

st.caption(
    "Native-frequency source rows and missingness are preserved. The "
    "Transform Pipeline remains available for explicitly exploratory work "
    "only; it does not approve an official frequency alignment or unlock "
    "official reporting, planning, or optimisation."
)
render_technical_details(
    details={
        "Preparation status key": _official_preparation.status,
        "Assessor detail": _official_preparation.reason,
    }
)
_frequency_section.__exit__(None, None, None)

st.markdown("---")
_prepare_frame_section = SectionCard(
    "Prepared-frame readiness",
    description=(
        "Prepare an official modelling frame when the frequency gate is ready. "
        "An exploratory frame is available for investigation only and does not "
        "satisfy official preparation or approve frequency treatment."
    ),
)
_prepare_frame_section.__enter__()
if brand_search_errors:
    st.caption(
        "Fix the Brand Search configuration errors above before preparing the modelling frame."
    )
else:
    _official_requested = st.button("Prepare official modelling frame", type="primary")
    _exploratory_requested = st.button("Prepare exploratory modelling frame")
    if _official_requested and not _official_preparation.ready:
        st.error(
            "Official modelling frame not created. Resolve the official "
            "preparation decisions above first. Native data and exploratory "
            "output were not changed."
        )
    elif _official_requested or _exploratory_requested:
        try:
            if _official_requested:
                try:
                    _adopted_sources = adopted_model_input_sources(
                        outcome_data=get_state("standard_outcome_data"),
                        activity_model_input=get_state("standard_activity_model_input"),
                        context_model_input=get_state("standard_context_data"),
                        context_variable_metadata=get_state("context_variable_metadata")
                        or [],
                    )
                except ValueError as exc:
                    raise OfficialPreparationDataError(str(exc)) from exc
                _official_sources = _adopted_sources or (get_state("raw_sources") or {})
                if not _official_sources:
                    raise OfficialPreparationDataError(
                        "Official preparation requires the durable raw source "
                        "tables; the exploratory joined frame is not an official fallback."
                    )
                _canonical_frame = prepare_canonical_native_frame(
                    _official_sources,
                    date_col=spec.date_col,
                    market_col=spec.market_col,
                    governed_start=str(_canonical_calendar["start"]),
                    governed_end=str(_canonical_calendar["end"]),
                    governed_frequency=str(_canonical_calendar["frequency"]),
                    pipeline_steps=get_state("pipeline_steps") or [],
                )
                _frame_input = _canonical_frame.frame
            else:
                _canonical_frame = None
                _frame_input = df
            frame = prepare_fh_modeling_frame(
                _frame_input,
                spec,
                outcomes=outcome_definitions,
                media_outcome_pathways=get_state("media_outcome_pathways") or [],
                activity_definitions=get_state("activity_definitions") or [],
                net_billthrough_metadata=get_state("net_billthrough_metadata"),
            )
            frame["preparation_mode"] = (
                "official" if _official_requested else "exploratory"
            )
            if _canonical_frame is not None:
                frame["official_union_periods"] = list(_canonical_frame.union_periods)
                frame["official_join_diagnostics"] = _canonical_frame.join_diagnostics
                set_state("official_prepared_data", _canonical_frame.frame)
                set_state(
                    "official_join_diagnostics", _canonical_frame.join_diagnostics
                )
                set_state(
                    "official_prepared_data_fingerprint",
                    fingerprint_dataframe(_canonical_frame.frame),
                )
            set_state("frame", frame)
            set_state("prior_config", prior_config)
            set_state("dna_lag_weeks", int(dna_lag_weeks))
            set_state("mcmc_draws", int(mcmc_draws))
            set_state("mcmc_tune", int(mcmc_tune))
            set_state("mcmc_chains", int(mcmc_chains))
            set_state("mcmc_target_accept", float(mcmc_target_accept))
            set_state("model_type", model_type)
            set_state("direct_dna_outcome_ids", list(dna_kit_outcomes.keys()))
            set_state(
                "brand_search_configs", [c.to_dict() for c in brand_search_configs]
            )
            clear_model_state()
            set_state("official_preparation_result", _official_preparation.to_dict())
            set_state(
                "official_capability_report", _official_capability_report.to_dict()
            )
            if _canonical_frame is not None:
                set_state("official_prepared_data", _canonical_frame.frame)
                set_state(
                    "official_join_diagnostics", _canonical_frame.join_diagnostics
                )
                set_state(
                    "official_prepared_data_fingerprint",
                    fingerprint_dataframe(_canonical_frame.frame),
                )
            set_state("frame", frame)  # clear_model_state wipes frame too - reset after
            _frame_mode = "official" if _official_requested else "exploratory"
            st.success(
                f"{_frame_mode.capitalize()} modelling frame prepared: "
                f"{format_number(frame['X_media'].shape[0])} observations, "
                f"{len(frame['channels'])} channels, {len(frame['outcome_ids'])} outcomes, "
                f"{len(frame['markets'])} market(s). Model structure: {model_type_labels[model_type]}."
            )
        except (OfficialPreparationDataError, ValueError) as e:
            st.error(
                f"Could not prepare the modelling frame: {e} Review the structure and try again."
            )
_prepare_frame_section.__exit__(None, None, None)

if get_state("frame") is not None:
    render_next_step("model_config")
