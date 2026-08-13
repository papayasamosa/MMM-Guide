"""Page 3: define markets, FH segments, channels, DNA channels, promo columns and LTV as explicit structural dimensions."""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    clear_model_state,
    readable_label,
    FIELD_HELP,
    dataframe_column_config,
    display_enum_frame,
    display_enum_options,
    restore_enum_frame,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_drift_status,
    render_workspace_note,
    render_definition_help,
    render_decision_help,
    render_technical_details,
    page_readiness,
    SectionCard,
)
from ancestry_mmm.core.schema import ModelSpec, DEFAULT_SEGMENTS
from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_by_model_input,
    legacy_activity_definitions_from_model_spec,
    resolve_activity_definition,
    resolve_activity_model_input,
)

from ancestry_mmm.core.outcomes import (
    DNA_SEGMENT_NEW,
    DNA_SEGMENT_EXISTING_FH,
    DNA_SEGMENT_COMBINED,
    DNA,
    FAMILY_HISTORY,
    KNOWN_PRODUCTS,
    OUTCOME_ROLES,
    METRIC_GSA,
    METRIC_SIGNUP,
    METRIC_KIT_SALE,
    OutcomeDefinition,
    fh_outcomes_from_spec,
    dna_outcomes_from_columns,
    validate_outcome_definitions,
    outcomes_to_dataframe,
    validate_fh_dna_cross_sell_outcome_id,
    infer_legacy_fh_dna_cross_sell_outcome_id,
)
from ancestry_mmm.core.promotions import (
    PromotionEvent,
    validate_promotion_events,
    apply_promotion_events_to_frame,
    promotion_events_to_transform_steps,
    PROMOTION_EVENT_OP,
)
from ancestry_mmm.core.funnel import FunnelLink, validate_funnel_links
from ancestry_mmm.core.pathways import (
    COMPONENT_TYPES,
    EVIDENCE_STATUSES,
    HEADLINE_APPROVAL_STATUSES,
    LEGACY_EVIDENCE_STATUSES,
    LAG_TYPES,
    PATHWAY_ROLES,
    MediaOutcomePathway,
    migrate_pathways_to_activity_identity,
    legacy_governance_review_catalogue,
    legacy_governance_change_summary,
    pathways_drift_dataframe,
    resolve_pathway_masks,
    validate_legacy_governance_review,
    validate_media_outcome_pathways,
)
from ancestry_mmm.core.net_billthrough import NBT_METRIC_KEY
from ancestry_mmm.data import (
    validate_modeling_frame,
    detect_column_types,
    pipeline_to_json,
    pipeline_from_json,
)
import pandas as pd

st.set_page_config(
    page_title="Model Structure | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("structure")
render_page_header(
    "structure",
    task_prompt="Which outcomes, segments, markets, and activities belong in this model?",
    badges=[page_readiness("structure")],
)
render_workspace_note(
    "Model structure",
    "These choices define markets, outcomes, segments, and activities; saving a change can stale downstream fit evidence.",
    kind="governed",
)
st.caption(
    "Markets, outcomes, segments, activities, and pathways are configured here as durable model "
    "scope. The saved-state summary below is read-only; edits become durable only after validation."
)

df = get_state("transformed_data")
if df is None:
    st.markdown("---")
    render_empty_state(
        "No prepared data yet. Complete Prepare Data first.",
        button_label="Go to Prepare Data",
        target_key="transform_pipeline",
    )
    st.stop()

render_definition_help(
    "an outcome",
    "A measurable event or value definition that is fitted separately, such as a sign-up, GSA, or DNA kit sale. Outcomes are not interchangeable just because they share a segment.",
)
render_decision_help(
    "How should I choose market pooling?",
    controls="Whether response curves share information across markets or are estimated with market-level differences.",
    why="Pooling can stabilise estimates when markets have limited data; allowing differences can preserve meaningful local behaviour.",
    options={
        "Shared response": "Use when the available evidence does not justify distinct market curves.",
        "Market-specific with partial pooling": "Use when markets may differ but should still borrow strength from one another.",
        "Unpooled market response": "Use only when an approved decision and strong data support structurally distinct markets.",
    },
    normal_path="Start with shared or partially pooled responses, then review evidence before making a market fully unpooled.",
    downstream="The choice changes the fitted response parameters and the evidence available for market-level curves, attribution, and planning.",
    invalidates="Saving a changed structure makes downstream fit evidence stale; refit and repeat the required readiness and approval checks.",
)
render_technical_details(
    details={
        "Saved identifiers": "Outcome IDs, pathway IDs, source columns, and enum values remain unchanged for validation, persistence, joins, and model fingerprints.",
        "Fit scope": "Only rows marked Included in next fit are passed to the next model fit; excluded rows remain in the governed catalogue.",
    }
)

_saved_spec_dict = get_state("model_spec")
_saved_spec = ModelSpec.from_dict(_saved_spec_dict) if _saved_spec_dict else None
_saved_outcome_rows = get_state("outcome_definitions") or []
_saved_pathway_rows = get_state("media_outcome_pathways") or []
_saved_activity_rows = get_state("activity_definitions") or []
_governed_activity_definitions = [
    ActivityDefinition.from_dict(item) for item in _saved_activity_rows
]
_legacy_activity_compatibility = False
if not _governed_activity_definitions and _saved_spec is not None:
    _governed_activity_definitions = legacy_activity_definitions_from_model_spec(
        _saved_spec
    )
    _legacy_activity_compatibility = bool(_governed_activity_definitions)
_legacy_model_input_candidates = []
if not _governed_activity_definitions:
    _legacy_meta = get_state("model_meta")
    _legacy_masks = getattr(_legacy_meta, "pathway_masks", None)
    for _mapping_name in (
        "primary_channels_by_outcome",
        "active_channels_by_outcome",
        "exploratory_channels_by_outcome",
    ):
        _mapping = getattr(_legacy_masks, _mapping_name, {}) or {}
        for _legacy_channels in _mapping.values():
            for _legacy_channel in _legacy_channels:
                if _legacy_channel not in _legacy_model_input_candidates:
                    _legacy_model_input_candidates.append(_legacy_channel)
    for _pathway in _saved_pathway_rows:
        _legacy_channel = str(_pathway.get("channel") or "")
        if _legacy_channel and _legacy_channel not in _legacy_model_input_candidates:
            _legacy_model_input_candidates.append(_legacy_channel)
    if _legacy_model_input_candidates:
        _legacy_activity_compatibility = True
with st.container(border=True):
    st.markdown("### Saved structure summary")
    st.caption(
        "A compact read-only snapshot of the last saved structure. It does not imply that unsaved edits are complete."
    )
    summary_cols = st.columns(6)
    summary_cols[0].metric("Markets", len(_saved_spec.markets) if _saved_spec else "—")
    summary_cols[1].metric("Outcomes", len(_saved_outcome_rows) if _saved_spec else "—")
    summary_cols[2].metric(
        "Governed activities",
        len(_governed_activity_definitions) if _saved_spec else "—",
    )
    summary_cols[3].metric(
        "Model-input columns",
        len(_saved_spec.model_input_columns) if _saved_spec else "—",
    )
    summary_cols[4].metric(
        "Reporting channels",
        len({item.channel for item in _governed_activity_definitions})
        if _saved_spec
        else "—",
    )
    summary_cols[5].metric(
        "Pathways",
        len(_saved_pathway_rows) if _saved_spec else "—",
    )
    st.caption(f"Saved state: {'Configured' if _saved_spec else 'Not saved'}")
    if _legacy_activity_compatibility:
        st.info(
            "This saved project predates governed activity mapping. Its historical "
            "ModelSpec inputs are shown through an explicit compatibility adapter; "
            "review them in Activity Mapping before the next governed save."
        )

date_col = get_state("date_col")
market_col = get_state("market_col")
hints = detect_column_types(df)
numeric_cols = hints["numeric"]

st.markdown("---")
_markets_section = SectionCard(
    "Project scope · markets",
    description="Which markets this project fits, and where market-specific estimation is appropriate.",
)
_markets_section.__enter__()
if market_col:
    available_markets = sorted(df[market_col].dropna().unique().tolist())
    markets = st.multiselect(
        "Markets to include *", available_markets, default=available_markets
    )
    unpooled_markets = st.multiselect(
        "Markets to model unpooled (structurally too different to share strength)",
        markets,
        default=[],
        help="Everything else defaults to partial pooling across markets. "
        + FIELD_HELP["partial_pooling"],
    )
else:
    st.info("No market column was set - treating this as a single implicit market.")
    df = df.copy()
    df["_market"] = "default"
    market_col = "_market"
    markets = ["default"]
    unpooled_markets = []
_markets_section.__exit__(None, None, None)

st.markdown("---")
_media_section = SectionCard(
    "Project scope · activities",
    description="Which model-input columns and DNA-targeted activities are in scope.",
)
_media_section.__enter__()
if _governed_activity_definitions:
    _activity_choice_by_key = {
        f"{definition.market}::{definition.activity_id}": definition
        for definition in _governed_activity_definitions
    }

    def _activity_choice_label(key: str) -> str:
        definition = _activity_choice_by_key[key]
        return (
            f"{readable_label(definition.activity_id)} / "
            f"{readable_label(definition.channel)} / "
            f"{readable_label(definition.resolved_model_input_column)}"
        )

    _activity_choice_keys = list(_activity_choice_by_key)
    _saved_input_set = set(_saved_spec.model_input_columns if _saved_spec else ())
    _default_activity_choices = [
        key
        for key, definition in _activity_choice_by_key.items()
        if not _saved_input_set
        or definition.resolved_model_input_column in _saved_input_set
    ]
    selected_activity_keys = st.multiselect(
        "Governed activities in this model *",
        _activity_choice_keys,
        default=_default_activity_choices,
        format_func=_activity_choice_label,
        help=(
            "Select governed activity identities. The engine-compatible model "
            "input column is resolved from each selected ActivityDefinition; "
            "the reporting channel is not used as the fitted predictor."
        ),
    )
    _selected_activity_definitions = [
        _activity_choice_by_key[key] for key in selected_activity_keys
    ]
    _saved_dna_input_set = set(_saved_spec.dna_channels if _saved_spec else ())
    _dna_default_keys = [
        key
        for key in selected_activity_keys
        if _activity_choice_by_key[key].resolved_model_input_column
        in _saved_dna_input_set
    ]
    _selected_dna_activity_keys = st.multiselect(
        "DNA-targeted activities",
        selected_activity_keys,
        default=_dna_default_keys,
        format_func=_activity_choice_label,
        help=(
            "Explicitly select governed activities that drive the DNA halo. "
            "This does not infer a DNA role from the activity or column name."
        ),
    )
    _selected_dna_activity_key_set = set(_selected_dna_activity_keys)
    for market in markets:
        try:
            activity_by_model_input(_governed_activity_definitions, market)
        except ValueError as error:
            st.error(str(error))
    _resolved_activity_definitions = []
    _resolution_errors = []
    for key in selected_activity_keys:
        definition = _activity_choice_by_key[key]
        target_markets = (
            markets
            if definition.market == "*"
            else [definition.market]
            if definition.market in markets
            else []
        )
        for market in target_markets:
            try:
                _resolved_activity_definitions.append(
                    resolve_activity_definition(
                        _governed_activity_definitions,
                        market=market,
                        activity_id=definition.activity_id,
                    )
                )
            except (KeyError, ValueError) as error:
                _resolution_errors.append(str(error))
    for error in sorted(set(_resolution_errors)):
        st.error(error)
    channels = list(
        dict.fromkeys(
            definition.resolved_model_input_column
            for definition in _resolved_activity_definitions
        )
    )
    dna_channels = list(
        dict.fromkeys(
            definition.resolved_model_input_column
            for definition in _resolved_activity_definitions
            if f"{definition.market}::{definition.activity_id}"
            in _selected_dna_activity_key_set
            or f"*::{definition.activity_id}" in _selected_dna_activity_key_set
        )
    )
else:
    channels = list(_legacy_model_input_candidates)
    dna_channels = []
    if channels:
        st.info(
            "This legacy pathway configuration has no governed activity rows. "
            "Its explicitly stored model-input identities are available through "
            "a compatibility path; review them in Activity Mapping before a new save."
        )
    else:
        st.warning(
            "No governed activities are available. Complete Activity Mapping first; "
            "Model Structure will not classify numeric columns as media."
        )
_media_section.__exit__(None, None, None)

st.markdown("---")
_outcome_section = SectionCard(
    "Outcomes & segment mapping",
    description="The primary outcome catalogue, with segment and product scope kept explicit.",
)
_outcome_section.__enter__()
render_decision_help(
    "How should I define outcomes?",
    controls="Which measurable events or values are tracked, their segment/product scope, and whether each row is included in the next fit.",
    why="A model, curve, scenario, and approval must each refer to a specific approved outcome definition; a sign-up, GSA, and kit sale are separate measures.",
    options={
        "Include in next fit": "Use for an outcome with a valid source column and an approved definition you want the next fit to estimate.",
        "Exclude from next fit": "Use to retain and validate a governed outcome without fitting it in the next run.",
        "DNA purchase outcome": "Use a New Customer / Existing Family History split when the source data supports it; otherwise use the explicitly labelled combined fallback.",
    },
    normal_path="Define the outcome row, validate it, save the catalogue, then review the resulting scope on Model Setup before fitting.",
    downstream="Included rows shape the model likelihood and every downstream result. DNA rows also determine which direct DNA responses are available.",
    invalidates="Changing a saved outcome definition or fit inclusion makes model evidence stale and requires a refit before governed use.",
)
st.caption(
    "The main configuration surface for what this project fits - one row per measurable outcome, "
    "not one weekly GSA column per segment. A sign-up measure and a GSA measure on the same segment "
    "are separate outcomes and remain independent throughout the model. Add, edit, or remove rows "
    "directly below; the optional helpers are shortcuts, not a second configuration surface. "
    "Turning off Include in next fit keeps the outcome in the governed catalogue and holds it back "
    "from the next model run."
)

if "structure_outcome_rows" not in st.session_state:
    st.session_state["structure_outcome_rows"] = get_state("outcome_definitions") or []


def _merge_outcome_rows(new_rows: list) -> None:
    """Add/update rows in the session-state catalogue by outcome_id, without
    touching any other row an analyst may already have added or edited -
    the seeding wizards below call this rather than replacing the whole
    catalogue."""
    by_id = {r["outcome_id"]: r for r in st.session_state["structure_outcome_rows"]}
    for o in new_rows:
        by_id[o.outcome_id] = o.to_dict()
    st.session_state["structure_outcome_rows"] = list(by_id.values())
    st.session_state.pop("outcome_catalogue_editor", None)


with st.expander("Add standard Family History outcomes"):
    st.caption(
        "Optional shortcut for adding one weekly GSA outcome per Family History segment. A sign-up-only "
        "or GSA-only project can skip this and add rows directly above. Re-running this only "
        "adds/updates the standard GSA rows it creates; it never touches anything else in the "
        "catalogue."
    )
    n_segments = st.number_input(
        "Number of segments", min_value=1, max_value=6, value=3, key="wiz_n_segments"
    )
    wizard_segment_outcomes = {}
    default_keys = DEFAULT_SEGMENTS
    sample_ltv = get_state("sample_ltv") or {}
    wizard_ltv = {}
    for i in range(n_segments):
        c1, c2, c3 = st.columns(3)
        key = c1.text_input(
            f"Segment {i + 1} name",
            value=default_keys[i] if i < len(default_keys) else f"segment_{i + 1}",
            key=f"wiz_seg_key_{i}",
        )
        guess_idx = next(
            (
                j
                for j, c in enumerate(numeric_cols)
                if key.lower().replace("_", "") in c.lower().replace("_", "")
            ),
            0,
        )
        col = c2.selectbox(
            f"Outcome column for '{key}'",
            numeric_cols,
            index=guess_idx if numeric_cols else 0,
            key=f"wiz_seg_col_{i}",
            format_func=readable_label,
        )
        ltv_val = c3.number_input(
            f"LTV for '{key}'",
            min_value=0.0,
            value=float(sample_ltv.get(key, 100.0)),
            key=f"wiz_ltv_{i}",
        )
        if key:
            wizard_segment_outcomes[key] = col
            wizard_ltv[key] = ltv_val
    if st.button("Add standard Family History outcomes"):
        _merge_outcome_rows(fh_outcomes_from_spec(wizard_segment_outcomes, wizard_ltv))
        st.rerun()

with st.expander("Add DNA purchase outcomes"):
    render_definition_help(
        "a DNA purchase outcome",
        "A DNA kit-sale measure for a defined customer segment. It is a separate outcome from Family History sign-up, GSA, or cross-product halo effects.",
    )
    st.caption(
        "DNA kit purchases are a separate business outcome from any Family History outcome - a kit sale "
        "is never the same KPI as an FH sign-up or an FH GSA, even "
        "for the DNA cross-sell segment. Once added, they're **automatically included in the joint "
        "model fit** on Model Setup/Fit Model: DNA-targeted media gets direct response on these outcomes, "
        "separate from the cross-product halo pathway used for other outcomes."
    )
    dna_mode = st.radio(
        "Data available for DNA kit purchases",
        [
            "None yet",
            "Separate New Customer / Existing FH Customer columns",
            "Single combined column",
        ],
        horizontal=True,
    )
    dna_new_col = dna_existing_col = dna_combined_col = None
    dna_new_weight = dna_existing_weight = dna_combined_weight = None
    if dna_mode == "Separate New Customer / Existing FH Customer columns":
        c1, c2 = st.columns(2)
        dna_new_col = c1.selectbox(
            "New Customer DNA kit column",
            ["(none)"] + numeric_cols,
            format_func=lambda c: c if c == "(none)" else readable_label(c),
        )
        dna_new_col = None if dna_new_col == "(none)" else dna_new_col
        dna_new_weight = c1.number_input(
            "Value per kit (New Customer)", min_value=0.0, value=90.0
        )
        dna_existing_col = c2.selectbox(
            "Existing FH Customer DNA kit column",
            ["(none)"] + numeric_cols,
            format_func=lambda c: c if c == "(none)" else readable_label(c),
        )
        dna_existing_col = None if dna_existing_col == "(none)" else dna_existing_col
        dna_existing_weight = c2.number_input(
            "Value per kit (Existing FH Customer)", min_value=0.0, value=65.0
        )
    elif dna_mode == "Single combined column":
        dna_combined_col = st.selectbox(
            "Combined DNA kit column",
            ["(none)"] + numeric_cols,
            format_func=lambda c: c if c == "(none)" else readable_label(c),
        )
        dna_combined_col = None if dna_combined_col == "(none)" else dna_combined_col
        dna_combined_weight = st.number_input(
            "Value per kit (combined)", min_value=0.0, value=80.0
        )
        st.caption(
            "A single combined outcome is an explicit fallback for data that can't support the "
            "New/Existing split - it will be labelled as such wherever outcomes are shown."
        )
    if st.button("Add DNA kit outcomes to catalogue"):
        _merge_outcome_rows(
            dna_outcomes_from_columns(
                new_customer_column=dna_new_col,
                existing_fh_column=dna_existing_col,
                combined_column=dna_combined_col,
                value_weight_new=dna_new_weight,
                value_weight_existing=dna_existing_weight,
                value_weight_combined=dna_combined_weight,
            )
        )
        st.rerun()

_default_outcome_df = (
    pd.DataFrame(st.session_state["structure_outcome_rows"])
    if st.session_state["structure_outcome_rows"]
    else pd.DataFrame(
        columns=[
            "outcome_id",
            "product",
            "segment",
            "metric",
            "source_column",
            "unit",
            "value_weight",
            "value_currency",
            "role",
            "included_in_fit",
            "exclusion_reason",
        ]
    )
)
if st.button(
    "Clear outcome catalogue",
    help="Removes every row below - the optional shortcuts above can add standard rows again.",
):
    st.session_state["structure_outcome_rows"] = []
    st.session_state.pop("outcome_catalogue_editor", None)
    st.rerun()
_outcome_enum_values = {
    "product": KNOWN_PRODUCTS,
    "role": OUTCOME_ROLES,
}
_outcome_editor_df = display_enum_frame(
    _default_outcome_df, _outcome_enum_values.keys()
)
outcome_catalogue_editor = st.data_editor(
    _outcome_editor_df,
    num_rows="dynamic",
    column_config={
        "outcome_id": st.column_config.TextColumn(
            "Outcome ID", required=True, help="Stable identity - unique per outcome."
        ),
        "product": st.column_config.SelectboxColumn(
            "Product", options=display_enum_options(KNOWN_PRODUCTS), required=True
        ),
        "segment": st.column_config.TextColumn(
            "Customer segment",
            required=True,
            help="Descriptive customer-segment grouping - not unique.",
        ),
        "metric": st.column_config.TextColumn(
            "Outcome measure",
            required=True,
            help=f"What's being counted - e.g. '{METRIC_GSA}', '{METRIC_SIGNUP}', '{METRIC_KIT_SALE}'. "
            "A sign-up and a GSA must never share a metric value. Display label only - matching logic "
            "uses the stable metric_key derived from this automatically.",
        ),
        "source_column": st.column_config.SelectboxColumn(
            "Source column", options=numeric_cols, required=True
        ),
        "unit": st.column_config.TextColumn(
            "Counting unit",
            help="Counting unit - defaults from the metric registry if left blank; a custom metric needs one set explicitly.",
        ),
        "value_weight": st.column_config.NumberColumn(
            "Value per outcome",
            min_value=0.0,
            help="Per-unit value (LTV for FH, an analogous per-kit value for DNA).",
        ),
        "value_currency": st.column_config.TextColumn(
            "Value currency",
            help="e.g. USD - the currency value_weight is denominated in.",
        ),
        "role": st.column_config.SelectboxColumn(
            "Modelling role",
            options=display_enum_options(OUTCOME_ROLES),
            required=True,
        ),
        "included_in_fit": st.column_config.CheckboxColumn(
            "Include in next fit", default=True
        ),
        "exclusion_reason": st.column_config.TextColumn("Reason excluded"),
    },
    key="outcome_catalogue_editor",
    width="stretch",
)
outcome_catalogue_df = restore_enum_frame(
    outcome_catalogue_editor,
    _outcome_enum_values.keys(),
    _outcome_enum_values,
)

if get_state("model_meta") is not None:
    _preview_outcomes = [
        OutcomeDefinition.from_dict(r)
        for r in outcome_catalogue_df.to_dict("records")
        if r.get("outcome_id")
        and r.get("product")
        and r.get("segment")
        and r.get("metric")
        and r.get("source_column")
    ]
    render_drift_status(
        _preview_outcomes, get_state("model_meta"), available_columns=set(df.columns)
    )

_fh_candidate_ids = [
    r["outcome_id"]
    for r in outcome_catalogue_df.to_dict("records")
    if r.get("outcome_id") and r.get("product") == FAMILY_HISTORY
]
_legacy_candidate, _legacy_warning = infer_legacy_fh_dna_cross_sell_outcome_id(
    [
        OutcomeDefinition.from_dict(r)
        for r in outcome_catalogue_df.to_dict("records")
        if r.get("outcome_id")
        and r.get("product")
        and r.get("segment")
        and r.get("metric")
        and r.get("source_column")
    ]
)
if _legacy_warning:
    st.warning(_legacy_warning)
_cross_sell_options = ["(none)"] + _fh_candidate_ids
_cross_sell_default = (
    _legacy_candidate if _legacy_candidate in _fh_candidate_ids else "(none)"
)
fh_dna_cross_sell_outcome_id = st.selectbox(
    "FH DNA cross-sell outcome",
    _cross_sell_options,
    index=_cross_sell_options.index(_cross_sell_default)
    if _cross_sell_default in _cross_sell_options
    else 0,
    help="Which Family History outcome is the DNA halo pathway's target - required explicitly whenever "
    "DNA-targeted media is configured above. Automatic name-based inference is not used for a live fit "
    "(only offered here as a one-time migration suggestion for a legacy project).",
)
fh_dna_cross_sell_outcome_id = (
    None if fh_dna_cross_sell_outcome_id == "(none)" else fh_dna_cross_sell_outcome_id
)
_outcome_section.__exit__(None, None, None)

st.markdown("---")
_funnel_section = SectionCard(
    "Advanced causal links (optional)",
    description="For review and warnings only - not a constrained funnel model.",
)
_funnel_section.__enter__()
st.caption(
    "Declare which sign-up and GSA outcomes (or any other upstream/downstream pair) form a funnel, "
    "e.g. a sign-up that later converts to a GSA. Sign-ups and GSAs are still fitted as independent "
    "outcome equations - this is for review and warnings only (Model Diagnostics), not a constrained "
    "funnel model."
)
if "funnel_links" not in st.session_state:
    st.session_state["funnel_links"] = get_state("funnel_links") or []
_all_outcome_ids = [
    r["outcome_id"]
    for r in outcome_catalogue_df.to_dict("records")
    if r.get("outcome_id")
]
if len(_all_outcome_ids) < 2:
    st.info("Add at least two outcomes to the catalogue above to define a funnel link.")
else:
    c1, c2, c3 = st.columns([2, 2, 1])
    new_upstream = c1.selectbox(
        "Upstream outcome (e.g. sign-up)", _all_outcome_ids, key="new_funnel_upstream"
    )
    new_downstream = c2.selectbox(
        "Downstream outcome (e.g. GSA)", _all_outcome_ids, key="new_funnel_downstream"
    )
    if c3.button("Add funnel link"):
        if new_upstream == new_downstream:
            st.error("Upstream and downstream must be different outcomes.")
        else:
            pair = (new_upstream, new_downstream)
            existing_pairs = {
                (fl["upstream_outcome_id"], fl["downstream_outcome_id"])
                for fl in st.session_state["funnel_links"]
            }
            if pair not in existing_pairs:
                st.session_state["funnel_links"].append(
                    {
                        "upstream_outcome_id": new_upstream,
                        "downstream_outcome_id": new_downstream,
                    }
                )
            st.rerun()
    if st.session_state["funnel_links"]:
        for i, fl in enumerate(list(st.session_state["funnel_links"])):
            fc1, fc2 = st.columns([5, 1])
            fc1.write(f"{fl['upstream_outcome_id']} -> {fl['downstream_outcome_id']}")
            if fc2.button("Remove", key=f"remove_funnel_{i}"):
                st.session_state["funnel_links"].pop(i)
                st.rerun()
funnel_links = [FunnelLink.from_dict(fl) for fl in st.session_state["funnel_links"]]
_funnel_section.__exit__(None, None, None)

st.markdown("---")
_pathway_section = SectionCard(
    "Advanced pathway catalogue",
    description="Which (channel, target outcome) relationships this project believes exist, and their governance.",
)
_pathway_section.__enter__()
render_decision_help(
    "How should I use pathway roles?",
    controls="Whether a channel-to-outcome relationship is fitted, visible in attribution, eligible for headline reporting, or eligible for planning.",
    why="Known mechanisms such as direct response, cross-product halo, mediation, and exclusion have different evidence and governance requirements.",
    options={
        "Direct effect": "Use when the channel affects the outcome without a selected funnel mediator.",
        "Cross-product effect": "Use for a separately governed halo from one product into another outcome.",
        "Mediated diagnostic": "Use only for an explicitly selected mediator; it remains outside the standard likelihood and is not automatically planning-eligible.",
        "Excluded": "Use when the relationship is intentionally not fitted; keep the row when an auditable exclusion is useful.",
    },
    normal_path="Start with the known structural mechanism, set evidence and approval fields, then save and refit before relying on the changed catalogue.",
    downstream="Each role controls which coefficients are estimated and which outputs can be shown or used later; fitted does not mean approved for reporting or optimisation.",
    invalidates="Changing a pathway that belongs to a fitted model makes the fit and any bound approval stale. Review and refit before governed use.",
)
st.caption(
    "Use this catalogue to describe which media-to-outcome relationships the project believes exist: "
    "a direct effect, a delayed cross-product effect such as DNA media's halo onto Family History, "
    "an exploratory relationship, a diagnostic-only mediated assumption, or an excluded relationship. "
    "Mediated records remain outside the standard fit and cannot drive planning or headline reporting. "
    "If no row is set for a relationship, the existing default based on DNA-targeted media still applies. "
    "A pathway can target any outcome already defined above, including an outcome planned for a future fit."
)
if "media_outcome_pathways" not in st.session_state:
    st.session_state["media_outcome_pathways"] = (
        get_state("media_outcome_pathways") or []
    )
_current_model_meta = get_state("model_meta")
_current_pathway_masks = (
    getattr(_current_model_meta, "pathway_masks", None)
    if _current_model_meta is not None
    else None
)
_legacy_governance_review = bool(
    _current_pathway_masks is not None
    and getattr(_current_pathway_masks, "legacy_governance_mode", False)
)
_legacy_review_confirmed = False
_legacy_type_changes_confirmed = False
_legacy_sources_confirmed = False
_legacy_reviewed_by = ""
_legacy_review_note = ""
if _legacy_governance_review:
    st.warning(
        "This fit was restored from mask-only pathway metadata. Analyst attribution "
        "is available, but headline reporting and planning are blocked until every "
        "migrated component is reviewed here and the model is refit."
    )
    _legacy_review_draft = legacy_governance_review_catalogue(_current_model_meta)
    with st.expander("Review migrated pathways", expanded=True):
        for _migration_message in _current_pathway_masks.migration_report:
            st.write(f"- {_migration_message}")
        st.caption(
            "Load the reconstructed rows into the normal catalogue, then correct "
            "source product, role, lag, prior, evidence, planning, and headline "
            "approval. Mark rejected relationships as excluded instead of deleting "
            "them so the migration remains auditable."
        )
        st.dataframe(
            pd.DataFrame([pathway.to_dict() for pathway in _legacy_review_draft]),
            width="stretch",
        )
        if st.button(
            "Load migrated components into review catalogue",
            disabled=not bool(_legacy_review_draft),
        ):
            st.session_state["media_outcome_pathways"] = [
                pathway.to_dict() for pathway in _legacy_review_draft
            ]
            st.session_state.pop("pathway_catalogue_editor", None)
            st.rerun()
        if st.session_state["media_outcome_pathways"]:
            st.info(
                "Rows marked `source_product_inferred = true` were reconstructed "
                "from legacy DNA-channel membership. Confirm or correct each value."
            )
            _legacy_reviewed_by = st.text_input(
                "Migration reviewed by",
                key="legacy_pathway_reviewed_by",
            )
            _legacy_review_note = st.text_area(
                "Migration review note",
                key="legacy_pathway_review_note",
            )
            _legacy_sources_confirmed = st.checkbox(
                "I confirmed or corrected every inferred source product",
                key="legacy_source_products_confirmed",
            )
            _legacy_type_changes_confirmed = st.checkbox(
                "I explicitly confirm any direct/cross-product reclassification",
                key="legacy_component_type_changes_confirmed",
            )
            _legacy_review_confirmed = st.checkbox(
                "I reviewed every migrated pathway and its governance fields",
                help=(
                    "Saving clears the legacy fit and approval. Model Setup and Fit Model "
                    "must then be rerun before headline or planning use."
                ),
                key="legacy_pathway_review_confirmed",
            )
_pathway_identity_migration = migrate_pathways_to_activity_identity(
    st.session_state["media_outcome_pathways"],
    _governed_activity_definitions,
)
if _pathway_identity_migration.errors:
    st.warning(
        "Some pathway records still need explicit activity-identity migration. "
        "They remain review-required and cannot be saved as governed rows until "
        "the ambiguity is resolved."
    )
    for _migration_error in _pathway_identity_migration.errors:
        st.error(_migration_error)

_pathway_default_df = (
    pd.DataFrame(
        [pathway.to_dict() for pathway in _pathway_identity_migration.pathways]
    )
    if _pathway_identity_migration.pathways
    else pd.DataFrame(
        columns=[
            "pathway_id",
            "activity_id",
            "activity_market",
            "channel",
            "source_product",
            "target_outcome_id",
            "component_type",
            "role",
            "lag_type",
            "lag_weeks",
            "prior_scale",
            "include_in_attribution",
            "include_in_planning",
            "include_in_headline",
            "headline_approval_status",
            "headline_approval_note",
            "approved_by",
            "approved_at",
            "evidence_status",
            "source_product_inferred",
        ]
    )
)
_pathway_enum_values = {
    "source_product": KNOWN_PRODUCTS,
    "component_type": COMPONENT_TYPES,
    "role": PATHWAY_ROLES,
    "lag_type": LAG_TYPES,
    "headline_approval_status": HEADLINE_APPROVAL_STATUSES,
    "evidence_status": EVIDENCE_STATUSES + LEGACY_EVIDENCE_STATUSES,
}
_activity_ids = sorted(
    {definition.activity_id for definition in _governed_activity_definitions}
)
_activity_markets = sorted(
    {definition.market for definition in _governed_activity_definitions} | set(markets)
)
_pathway_editor_df = display_enum_frame(
    _pathway_default_df, _pathway_enum_values.keys()
)
pathway_catalogue_editor = st.data_editor(
    _pathway_editor_df,
    num_rows="dynamic",
    disabled=[
        "prior_scale",
        "include_in_planning",
        "include_in_headline",
        "headline_approval_status",
    ],
    column_config={
        "pathway_id": None,  # auto-managed identity, not hand-edited
        "activity_id": st.column_config.SelectboxColumn(
            "Governed activity",
            options=_activity_ids,
            required=False,
            help="Stable activity identity; funnel stage remains sourced from Activity Mapping.",
        ),
        "activity_market": st.column_config.SelectboxColumn(
            "Activity market",
            options=_activity_markets,
            required=False,
            help="Explicit market scope for the governed activity identity.",
        ),
        "channel": st.column_config.SelectboxColumn(
            "Physical model input",
            options=channels,
            required=True,
            help="Engine predictor resolved from the governed activity; it is not the reporting channel.",
        ),
        "source_product": st.column_config.SelectboxColumn(
            "Source product",
            options=display_enum_options(KNOWN_PRODUCTS),
            required=True,
        ),
        "target_outcome_id": st.column_config.SelectboxColumn(
            "Target outcome",
            options=[
                r["outcome_id"]
                for r in outcome_catalogue_df.to_dict("records")
                if r.get("outcome_id")
            ],
            required=True,
        ),
        "component_type": st.column_config.SelectboxColumn(
            "Pathway type",
            options=display_enum_options(COMPONENT_TYPES),
            required=True,
            default="direct",
            help="Direct effect, delayed/cross-product effect, diagnostic mediation, or exclusion.",
        ),
        "role": st.column_config.SelectboxColumn(
            "Planning/reporting role",
            options=display_enum_options(PATHWAY_ROLES),
            required=True,
            default=readable_label(PATHWAY_ROLES[0]),
        ),
        "lag_type": st.column_config.SelectboxColumn(
            "Timing assumption",
            options=display_enum_options(LAG_TYPES),
            required=True,
            default=readable_label("none"),
        ),
        "lag_weeks": st.column_config.NumberColumn(
            "Additional lag (weeks)",
            min_value=0,
            help="Only meaningful if lag_type implies a delay.",
        ),
        "prior_scale": st.column_config.NumberColumn(
            "Cross-product strength prior scale",
            min_value=0.0001,
            help="Operational only for cross_product: sigma of its HalfNormal pathway-strength prior. Leave blank for direct, mediated, and excluded rows.",
        ),
        "include_in_attribution": st.column_config.CheckboxColumn(
            "Show in analyst attribution", default=True
        ),
        "include_in_planning": st.column_config.CheckboxColumn(
            "Eligible for planning", default=True
        ),
        "include_in_headline": st.column_config.CheckboxColumn(
            "Eligible for headline reporting", default=False
        ),
        "headline_approval_status": st.column_config.SelectboxColumn(
            "Headline approval",
            options=display_enum_options(HEADLINE_APPROVAL_STATUSES),
            required=True,
            default="not_reviewed",
        ),
        "headline_approval_note": st.column_config.TextColumn("Approval note"),
        "approved_by": st.column_config.TextColumn("Approved by"),
        "approved_at": st.column_config.TextColumn(
            "Approved at", help="ISO date/time or governed approval reference."
        ),
        "evidence_status": st.column_config.SelectboxColumn(
            "Evidence status",
            options=display_enum_options(EVIDENCE_STATUSES + LEGACY_EVIDENCE_STATUSES),
            required=True,
            default="unreviewed",
        ),
    },
    key="pathway_catalogue_editor",
    width="stretch",
)
pathway_catalogue_df = restore_enum_frame(
    pathway_catalogue_editor,
    _pathway_enum_values.keys(),
    _pathway_enum_values,
)
st.caption(
    "Component-specific fields are read-only in the grid. Select a row below to edit them. "
    "Cross-product strength is available only for cross-product rows; other pathway types use "
    "their own governed settings."
)

if not pathway_catalogue_df.empty:
    _pathway_row_options = list(range(len(pathway_catalogue_df)))

    def _pathway_row_label(index: int) -> str:
        row = pathway_catalogue_df.iloc[index]
        activity = row.get("activity_id") or row.get("channel") or "(activity not set)"
        market = row.get("activity_market") or "*"
        outcome = row.get("target_outcome_id") or "(outcome not set)"
        component = row.get("component_type") or "direct"
        return f"Row {index + 1}: {activity} ({market}) -> {outcome} [{component}]"

    _selected_pathway_row = st.selectbox(
        "Component-specific pathway fields",
        options=_pathway_row_options,
        format_func=_pathway_row_label,
        key="pathway_component_field_row",
    )
    _selected_pathway = pathway_catalogue_df.iloc[_selected_pathway_row]
    _selected_component_type = _selected_pathway.get("component_type") or "direct"
    _is_cross_product = _selected_component_type == "cross_product"
    _is_governance_only = _selected_component_type in {"mediated", "excluded"}

    if _selected_component_type == "mediated":
        st.info(
            "Mediated components are diagnostic-only: they add no term to the standard "
            "MMM likelihood and cannot be used for planning or headline reporting."
        )
    elif _selected_component_type == "excluded":
        st.info(
            "Excluded components are governance-only and contribute zero to fitting, "
            "planning, and headline reporting."
        )

    _field_col_1, _field_col_2, _field_col_3, _field_col_4 = st.columns(4)
    _prior_value = _selected_pathway.get("prior_scale")
    if pd.isna(_prior_value):
        _prior_value = None
    _edited_prior_scale = _field_col_1.number_input(
        "Cross-product prior scale",
        min_value=0.0001,
        value=_prior_value if _is_cross_product else None,
        disabled=not _is_cross_product,
        help=(
            "Sigma of the HalfNormal prior on this cross-product component's "
            "pathway_strength multiplier."
        ),
        key=f"pathway_prior_scale_{_selected_pathway_row}_{_selected_component_type}",
    )
    _edited_planning = _field_col_2.checkbox(
        "Planning eligible",
        value=(
            bool(_selected_pathway.get("include_in_planning", True))
            if not _is_governance_only
            else False
        ),
        disabled=_is_governance_only,
        key=f"pathway_planning_{_selected_pathway_row}_{_selected_component_type}",
    )
    _edited_headline = _field_col_3.checkbox(
        "Headline eligible",
        value=(
            bool(_selected_pathway.get("include_in_headline", False))
            if not _is_governance_only
            else False
        ),
        disabled=_is_governance_only,
        key=f"pathway_headline_{_selected_pathway_row}_{_selected_component_type}",
    )
    _headline_status = _selected_pathway.get("headline_approval_status")
    if _headline_status not in HEADLINE_APPROVAL_STATUSES:
        _headline_status = "not_reviewed"
    _edited_headline_status = _field_col_4.selectbox(
        "Headline approval",
        options=list(HEADLINE_APPROVAL_STATUSES),
        index=list(HEADLINE_APPROVAL_STATUSES).index(
            "not_applicable" if _is_governance_only else _headline_status
        ),
        disabled=_is_governance_only,
        key=f"pathway_headline_status_{_selected_pathway_row}_{_selected_component_type}",
    )

    pathway_catalogue_df.at[_selected_pathway_row, "prior_scale"] = (
        _edited_prior_scale if _is_cross_product else None
    )
    pathway_catalogue_df.at[_selected_pathway_row, "include_in_planning"] = (
        _edited_planning if not _is_governance_only else False
    )
    pathway_catalogue_df.at[_selected_pathway_row, "include_in_headline"] = (
        _edited_headline if not _is_governance_only else False
    )
    pathway_catalogue_df.at[_selected_pathway_row, "headline_approval_status"] = (
        _edited_headline_status if not _is_governance_only else "not_applicable"
    )

# Resolve the engine predictor from the selected governed activity before
# constructing pathway records. The reporting channel is never used here.
_editor_identity_errors = []


def _pathway_from_editor_row(row: dict) -> MediaOutcomePathway:
    payload = dict(row)
    activity_id = payload.get("activity_id")
    activity_market = payload.get("activity_market")
    if pd.isna(activity_id):
        activity_id = ""
    if pd.isna(activity_market):
        activity_market = ""
    payload["activity_id"] = str(activity_id or "")
    payload["activity_market"] = str(activity_market or "")
    if payload["activity_id"] and payload["activity_market"]:
        try:
            payload["channel"] = resolve_activity_model_input(
                _governed_activity_definitions,
                market=payload["activity_market"],
                activity_id=payload["activity_id"],
            )
        except (KeyError, ValueError) as error:
            _editor_identity_errors.append(str(error))
    return MediaOutcomePathway.from_dict(payload)


# Enforce the UI contract for every row, including rows not currently selected.
# This prevents stale values from an older bundle or a component-type change from
# becoming operational merely because the grid retains a hidden cell value.
for _pathway_index, _pathway_row in pathway_catalogue_df.iterrows():
    _component_type = _pathway_row.get("component_type") or "direct"
    if _component_type != "cross_product":
        pathway_catalogue_df.at[_pathway_index, "prior_scale"] = None
    if _component_type in {"mediated", "excluded"}:
        pathway_catalogue_df.at[_pathway_index, "include_in_planning"] = False
        pathway_catalogue_df.at[_pathway_index, "include_in_headline"] = False
        pathway_catalogue_df.at[_pathway_index, "headline_approval_status"] = (
            "not_applicable"
        )
    if _component_type == "excluded":
        pathway_catalogue_df.at[_pathway_index, "include_in_attribution"] = False

_edited_pathways = [
    _pathway_from_editor_row(row)
    for row in pathway_catalogue_df.to_dict("records")
    if (row.get("channel") or row.get("activity_id")) and row.get("target_outcome_id")
]
_edited_identity_migration = migrate_pathways_to_activity_identity(
    _edited_pathways,
    _governed_activity_definitions,
)
_preview_errors = validate_media_outcome_pathways(
    list(_edited_identity_migration.pathways),
    channels=channels,
    outcome_ids=[
        row["outcome_id"]
        for row in outcome_catalogue_df.to_dict("records")
        if row.get("outcome_id")
    ],
)
_preview_errors += list(_edited_identity_migration.errors)
_preview_errors += sorted(set(_editor_identity_errors))
with st.expander("Resolved model-equation component preview", expanded=False):
    st.caption(
        "This is the authoritative component view used by fitting, replay, attribution, "
        "headline reporting, and planning. Evidence and headline approval are separate."
    )
    if _preview_errors:
        for error in _preview_errors:
            st.warning(error)
    else:
        _preview_outcomes = [
            row["outcome_id"]
            for row in outcome_catalogue_df.to_dict("records")
            if row.get("outcome_id")
        ]
        _dna_idx = [
            index for index, channel in enumerate(channels) if channel in dna_channels
        ]
        _direct_dna_ids = [
            row["outcome_id"]
            for row in outcome_catalogue_df.to_dict("records")
            if row.get("product") == DNA and row.get("outcome_id")
        ]
        if fh_dna_cross_sell_outcome_id:
            _direct_dna_ids.append(fh_dna_cross_sell_outcome_id)
        _resolved_preview = resolve_pathway_masks(
            _preview_outcomes,
            channels,
            list(_edited_identity_migration.pathways),
            dna_channel_idx=_dna_idx,
            dna_outcome_id=fh_dna_cross_sell_outcome_id or None,
            direct_dna_outcome_ids=list(dict.fromkeys(_direct_dna_ids)),
            dna_lag_weeks=int(get_state("dna_lag_weeks", 4)),
        )
        _preview_rows = []
        for component in _resolved_preview.components:
            if component.component_type == "direct":
                equation = "beta × saturated_media"
            elif component.component_type == "cross_product":
                equation = (
                    f"beta × pathway_strength × lag_{component.lag_weeks}"
                    "(saturated_media)"
                )
            else:
                equation = "diagnostic/governance only — no standard likelihood term"
            _preview_rows.append({**component.to_dict(), "equation_term": equation})
        st.dataframe(pd.DataFrame(_preview_rows), width="stretch")

if get_state("model_meta") is not None and st.session_state["media_outcome_pathways"]:
    _pathway_drift_df = pathways_drift_dataframe(
        _edited_pathways, get_state("model_meta")
    )
    if not _pathway_drift_df.empty:
        _changed_pathways = _pathway_drift_df[
            _pathway_drift_df["drift_status"] != "Fitted and current"
        ]
        if not _changed_pathways.empty:
            st.warning(
                f"{len(_changed_pathways)} pathway(s) differ from this fit's captured pathway metadata - "
                "the pathway catalogue drives which coefficients get estimated, so this fit's results no "
                "longer reflect the catalogue shown above. Re-run Fit Model to pick up "
                "the change."
            )
            with st.expander("Pathway drift detail"):
                st.dataframe(_pathway_drift_df, width="stretch")
_pathway_section.__exit__(None, None, None)

st.markdown("---")
_nbt_section = SectionCard(
    "Net bill-through completeness",
    description="Only shown when a net bill-through outcome is configured above.",
)
_nbt_section.__enter__()
st.caption(
    "Family History net bill-through is supplied as an authoritative weekly count. Configure and validate its completeness at upload; the app never reconstructs it from customer or billing events."
)
_saved_nbt = get_state("net_billthrough_metadata") or {}
_has_nbt = any(
    row.get("metric_key") == NBT_METRIC_KEY
    for row in outcome_catalogue_df.to_dict("records")
)
net_billthrough_metadata = None
if _has_nbt:
    n1, n2, n3 = st.columns(3)
    nbt_start = n1.text_input(
        "Model start week",
        value=str(_saved_nbt.get("model_start_week", "")),
        help="Weekly anchor, YYYY-MM-DD",
    )
    nbt_end = n2.text_input(
        "Model end week",
        value=str(_saved_nbt.get("model_end_week", "")),
        help="Inclusive, YYYY-MM-DD",
    )
    nbt_latest = n3.text_input(
        "Latest complete NBT week",
        value=str(_saved_nbt.get("latest_complete_net_billthrough_week", "")),
    )
    n4, n5 = st.columns(2)
    nbt_as_of = n4.text_input(
        "NBT data as-of date", value=str(_saved_nbt.get("data_as_of_date", ""))
    )
    nbt_owner = n5.text_input(
        "NBT source owner", value=str(_saved_nbt.get("source_owner", ""))
    )
    nbt_rule = st.text_input(
        "NBT maturity/finalisation rule",
        value=str(_saved_nbt.get("maturity_rule_description", "")),
    )
    net_billthrough_metadata = {
        "data_as_of_date": nbt_as_of,
        "model_start_week": nbt_start,
        "model_end_week": nbt_end,
        "latest_complete_net_billthrough_week": nbt_latest,
        "maturity_rule_description": nbt_rule,
        "source_owner": nbt_owner,
    }
else:
    st.caption("No fitted net bill-through outcome is currently configured.")
_nbt_section.__exit__(None, None, None)

# `segment_outcomes`/`segment_ltv` (ModelSpec migration fields) and per-segment
# promo/control mappings are now derived from the catalogue's own segments,
# not from a required separate mapping section - the catalogue is the single
# source of truth (PR E.2). A future PR moves promo/control mappings to
# outcome_id keys directly (docs/decision_log.md); segment-keyed is retained
# here as the current mapping granularity.
_catalogue_rows = outcome_catalogue_df.to_dict("records")
segment_outcomes = {
    r["segment"]: r["source_column"]
    for r in _catalogue_rows
    if r.get("segment")
    and r.get("source_column")
    and r.get("product") == FAMILY_HISTORY
}
segment_ltv = {}
for r in _catalogue_rows:
    seg = r.get("segment")
    weight = r.get("value_weight")
    if seg and weight is not None and seg not in segment_ltv:
        segment_ltv[seg] = float(weight)
_catalogue_segments = sorted(
    {r.get("segment") for r in _catalogue_rows if r.get("segment")}
)

st.markdown("---")
_promo_controls_section = SectionCard(
    "Promotions, controls & value inputs",
    description="Promo columns/calendar, global/product/segment controls, and per-outcome overrides - all optional.",
)
_promo_controls_section.__enter__()
st.markdown("#### Promotional flags (per segment, optional)")
promo_cols = {}
for seg in _catalogue_segments:
    col = st.selectbox(
        f"Promo column for '{seg}' (or None)",
        ["(none)"] + numeric_cols,
        key=f"promo_{seg}",
        index=(["(none)"] + numeric_cols).index(
            next(
                (
                    c
                    for c in numeric_cols
                    if "promo" in c.lower() and seg.lower()[:3] in c.lower()
                ),
                "(none)",
            )
        )
        if any("promo" in c.lower() for c in numeric_cols)
        else 0,
        format_func=lambda c: c if c == "(none)" else readable_label(c),
    )
    if col != "(none)":
        promo_cols[seg] = col

st.markdown("#### Controls")
remaining_numeric = [
    c for c in numeric_cols if c not in channels and c not in promo_cols.values()
]
control_cols = st.multiselect(
    "Global controls (apply to every outcome)",
    remaining_numeric,
    format_func=readable_label,
)

st.markdown(
    "**Product-level controls** (apply to every outcome of one product, e.g. every DNA-product outcome)"
)
product_control_cols = {}
for product in KNOWN_PRODUCTS:
    cols = st.multiselect(
        f"Controls specific to product '{product}'",
        [c for c in remaining_numeric if c not in control_cols],
        key=f"prodctrl_{product}",
        format_func=readable_label,
    )
    if cols:
        product_control_cols[product] = cols

st.markdown(
    "**Segment-specific controls** (optional - e.g. DNA kit price -> DNA cross-sell only)"
)
segment_control_cols = {}
for seg in _catalogue_segments:
    cols = st.multiselect(
        f"Controls specific to '{seg}'",
        [c for c in remaining_numeric if c not in control_cols],
        key=f"segctrl_{seg}",
        format_func=readable_label,
    )
    if cols:
        segment_control_cols[seg] = cols

_outcome_ids_by_segment: dict = {}
for r in _catalogue_rows:
    oid, seg = r.get("outcome_id"), r.get("segment")
    if oid and seg:
        _outcome_ids_by_segment.setdefault(seg, []).append(oid)
_multi_outcome_segments = {
    seg: oids for seg, oids in _outcome_ids_by_segment.items() if len(oids) > 1
}

outcome_promo_cols = {}
outcome_control_cols = {}
if _multi_outcome_segments:
    st.markdown("#### Outcome-level promo & control overrides (optional)")
    st.caption(
        "Segment-level mappings above apply to every outcome sharing that segment by default "
        "for the current configuration. Override per outcome_id here when two KPIs on the same segment (e.g. a "
        "sign-up and a GSA) need genuinely different promo timing or controls - an explicit "
        "outcome_id-keyed mapping always wins over the segment-level one above for that outcome_id. "
        "'Apply to every outcome in this segment' is an explicit bulk action, not implicit inheritance."
    )
    for seg, oids in _multi_outcome_segments.items():
        with st.expander(
            f"Outcome overrides for segment '{seg}' ({len(oids)} outcomes)"
        ):
            if st.button(
                f"Apply segment '{seg}' mapping to every outcome in it",
                key=f"bulk_apply_{seg}",
            ):
                seg_promo = promo_cols.get(seg)
                seg_controls = segment_control_cols.get(seg)
                for oid in oids:
                    if seg_promo:
                        st.session_state[f"outcome_promo_{oid}"] = seg_promo
                    if seg_controls:
                        st.session_state[f"outcome_ctrl_{oid}"] = seg_controls
                st.rerun()
            for oid in oids:
                c1, c2 = st.columns(2)
                promo_choice = c1.selectbox(
                    f"Promo column for '{oid}' (or None)",
                    ["(none)"] + numeric_cols,
                    key=f"outcome_promo_{oid}",
                    format_func=lambda c: c if c == "(none)" else readable_label(c),
                )
                if promo_choice != "(none)":
                    outcome_promo_cols[oid] = promo_choice
                ctrl_choice = c2.multiselect(
                    f"Extra controls for '{oid}'",
                    numeric_cols,
                    key=f"outcome_ctrl_{oid}",
                    format_func=readable_label,
                )
                if ctrl_choice:
                    outcome_control_cols[oid] = ctrl_choice

dna_segment_names = [
    s
    for s in _catalogue_segments
    if s in (DNA_SEGMENT_NEW, DNA_SEGMENT_EXISTING_FH, DNA_SEGMENT_COMBINED)
]
dna_promo_cols = {}
dna_segment_control_cols = {}
if dna_segment_names:
    st.markdown("#### DNA promotion calendar (optional, structured)")
    st.caption(
        "Alternative to a hand-built promo column above: define named promotion events (dates, "
        "discount depth, sale price) and a weekly intensity series is derived automatically - "
        "promo stays a term separate from media response either way, so a promotion is never "
        "silently absorbed into a channel's media coefficient. Takes precedence over the promo "
        "column above for the same segment when both are set."
    )
    st.caption(
        "`product`/`market` are optional, more precise targeting than `segment` alone - useful when "
        "a segment covers more than one product or the event is market-specific. `event_id` "
        "(stable identity across re-saves) and `transformation_version` are managed automatically."
    )
    dna_promo_events_df = st.data_editor(
        pd.DataFrame(
            columns=[
                "event_name",
                "segment",
                "product",
                "market",
                "start_date",
                "end_date",
                "discount_depth",
                "sale_price",
                "intensity",
            ]
        ),
        num_rows="dynamic",
        column_config={
            "segment": st.column_config.SelectboxColumn(
                "segment", options=dna_segment_names, required=True
            ),
            "product": st.column_config.SelectboxColumn(
                "product",
                options=[None] + list(KNOWN_PRODUCTS),
                help="Optional - narrows this event to one product.",
            ),
            "market": st.column_config.TextColumn(
                "market", help="Optional - narrows this event to one market."
            ),
            "start_date": st.column_config.TextColumn("start_date", help="YYYY-MM-DD"),
            "end_date": st.column_config.TextColumn("end_date", help="YYYY-MM-DD"),
            "discount_depth": st.column_config.NumberColumn(
                "discount_depth",
                help="0-1 fraction, e.g. 0.2 for 20% off",
                min_value=0.0,
                max_value=1.0,
            ),
            "intensity": st.column_config.NumberColumn(
                "intensity", help="Weekly series value while active", default=1.0
            ),
        },
        key="dna_promotion_events_editor",
    )
else:
    dna_promo_events_df = pd.DataFrame()
_promo_controls_section.__exit__(None, None, None)

st.markdown("---")
_validation_section = SectionCard(
    "Save & validate structure",
    description="Saves this structure and shows validation flags plus the current outcome catalogue status.",
)
_validation_section.__enter__()
if st.button("Save structure and validate", type="primary"):
    dna_promotion_events = []
    for row in dna_promo_events_df.to_dict("records"):
        if not (
            row.get("event_name")
            or row.get("segment")
            or row.get("start_date")
            or row.get("end_date")
        ):
            continue  # a blank row added by the editor but never filled in
        dna_promotion_events.append(
            PromotionEvent(
                event_name=row.get("event_name") or "",
                segment=row.get("segment") or "",
                start_date=row.get("start_date") or "",
                end_date=row.get("end_date") or "",
                discount_depth=row.get("discount_depth"),
                sale_price=row.get("sale_price"),
                intensity=row.get("intensity")
                if row.get("intensity") is not None
                else 1.0,
                product=row.get("product") or None,
                market=row.get("market") or None,
            )
        )

    merged_promo_cols = {**promo_cols, **dna_promo_cols}
    merged_segment_control_cols = {**segment_control_cols, **dna_segment_control_cols}

    promo_event_errors = validate_promotion_events(dna_promotion_events)
    updated_df = None
    if dna_promotion_events and not promo_event_errors:
        updated_df, derived_promo_cols = apply_promotion_events_to_frame(
            df, date_col, dna_promotion_events
        )
        merged_promo_cols.update(derived_promo_cols)

    # Persist promotion events as replayable TransformSteps (PR E.2 #11), not
    # just as a materialised column on transformed_data - re-importing this
    # project (or replaying the pipeline against refreshed raw data) then
    # reproduces the same derived promo columns from the versioned event
    # list rather than trusting whatever happens to be sitting in a parquet.
    # Every save fully replaces the prior promotion_event steps with the
    # current event list, so re-saving the same events is idempotent.
    existing_steps = pipeline_from_json(get_state("pipeline_steps") or [])
    non_promo_steps = [s for s in existing_steps if s.op != PROMOTION_EVENT_OP]
    new_promo_steps = promotion_events_to_transform_steps(
        dna_promotion_events, date_col
    )
    updated_pipeline_steps = non_promo_steps + new_promo_steps

    spec = ModelSpec(
        date_col=date_col,
        market_col=market_col,
        markets=markets,
        unpooled_markets=unpooled_markets,
        segment_outcomes=segment_outcomes,
        channels=channels,
        dna_channels=dna_channels,
        promo_cols=merged_promo_cols,
        outcome_promo_cols=outcome_promo_cols,
        control_cols=control_cols,
        product_control_cols=product_control_cols,
        segment_control_cols=merged_segment_control_cols,
        outcome_control_cols=outcome_control_cols,
        segment_ltv=segment_ltv,
        fh_dna_cross_sell_outcome_id=fh_dna_cross_sell_outcome_id,
    )
    errors = spec.validate() + promo_event_errors

    # The outcome catalogue editor above (not the FH segment/DNA mappings)
    # is the actual saved source of truth (PR E.1) - built from its edited
    # rows, not re-derived from segment_outcomes/dna_*_col, so an analyst's
    # added/edited rows (e.g. a distinct sign-up outcome on an FH segment)
    # are what gets persisted. A blank row added by num_rows="dynamic" but
    # never filled in is skipped, same convention as the promo-events editor
    # above.
    outcome_definitions = []
    for row in outcome_catalogue_df.to_dict("records"):
        if not (
            row.get("outcome_id")
            and row.get("product")
            and row.get("segment")
            and row.get("metric")
            and row.get("source_column")
        ):
            continue
        outcome_definitions.append(OutcomeDefinition.from_dict(row))
    errors += validate_outcome_definitions(
        outcome_definitions, available_columns=set(df.columns)
    )
    errors += validate_fh_dna_cross_sell_outcome_id(
        fh_dna_cross_sell_outcome_id, outcome_definitions
    )
    if dna_channels and not fh_dna_cross_sell_outcome_id:
        errors.append(
            "DNA-targeted media is configured but no FH DNA cross-sell outcome is selected above - "
            "required so the halo pathway has an explicit target (automatic name-based inference is "
            "no longer used for a live fit)."
        )
    errors += validate_funnel_links(
        funnel_links, [o.outcome_id for o in outcome_definitions]
    )

    media_outcome_pathways = []
    for row in pathway_catalogue_df.to_dict("records"):
        if not (
            (row.get("channel") or row.get("activity_id"))
            and row.get("source_product")
            and row.get("target_outcome_id")
        ):
            continue  # a blank row added by the editor but never filled in
        media_outcome_pathways.append(_pathway_from_editor_row(row))
    _save_identity_migration = migrate_pathways_to_activity_identity(
        media_outcome_pathways,
        _governed_activity_definitions,
    )
    errors += list(_save_identity_migration.errors)
    errors += sorted(set(_editor_identity_errors))
    media_outcome_pathways = list(_save_identity_migration.pathways)
    errors += validate_media_outcome_pathways(
        media_outcome_pathways,
        channels=channels,
        outcome_ids=[o.outcome_id for o in outcome_definitions],
        channel_products={
            channel: DNA if channel in dna_channels else FAMILY_HISTORY
            for channel in channels
        },
        outcome_products={
            outcome.outcome_id: outcome.product for outcome in outcome_definitions
        },
        fitted_outcome_ids=[
            outcome.outcome_id
            for outcome in outcome_definitions
            if outcome.included_in_fit
        ],
        diagnostic_only_outcome_ids=[
            outcome.outcome_id
            for outcome in outcome_definitions
            if outcome.role == "diagnostic"
        ],
    )
    errors += validate_legacy_governance_review(
        _current_model_meta,
        media_outcome_pathways,
        review_confirmed=_legacy_review_confirmed,
        component_type_changes_confirmed=_legacy_type_changes_confirmed,
        inferred_source_products_confirmed=_legacy_sources_confirmed,
    )
    if _legacy_governance_review and not _legacy_reviewed_by.strip():
        errors.append("Enter the migration reviewer's name before saving.")

    if errors:
        for e in errors:
            st.error(e)
    else:
        _completed_legacy_review = _legacy_governance_review
        _migration_source_run_id = get_state("model_run_id")
        _migration_change_summary = (
            legacy_governance_change_summary(
                _current_model_meta, media_outcome_pathways
            )
            if _completed_legacy_review
            else None
        )
        if updated_df is not None:
            set_state("transformed_data", updated_df)
        set_state("model_spec", spec.to_dict())
        set_state("outcome_definitions", [o.to_dict() for o in outcome_definitions])
        set_state("dna_promotion_events", [e.to_dict() for e in dna_promotion_events])
        set_state("pipeline_steps", pipeline_to_json(updated_pipeline_steps))
        set_state("funnel_links", [fl.to_dict() for fl in funnel_links])
        set_state(
            "media_outcome_pathways", [p.to_dict() for p in media_outcome_pathways]
        )
        set_state("net_billthrough_metadata", net_billthrough_metadata)
        clear_model_state()
        if _completed_legacy_review:
            set_state(
                "migration_review",
                {
                    "migration_review_status": "reviewed_refit_required",
                    "migration_reviewed_by": _legacy_reviewed_by.strip(),
                    "migration_reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "migration_review_note": _legacy_review_note.strip(),
                    "migrated_from_model_run_id": _migration_source_run_id,
                    "migration_change_summary": _migration_change_summary,
                    "model_invalidated": True,
                    "replacement_model_run_id": None,
                },
            )
        issues = validate_modeling_frame(
            df if market_col in df.columns else df.assign(**{market_col: "default"}),
            channels=channels,
            segment_outcomes=segment_outcomes,
            market_col=market_col,
        )
        set_state("validation_issues", issues)
        if _completed_legacy_review:
            st.success(
                "Legacy pathway review saved. The old fit and approval were invalidated; "
                "prepare the modelling frame and refit before headline reporting or planning."
            )
        else:
            st.success("Structure saved.")
        if issues:
            st.markdown("#### Validation flags")
            for issue in issues:
                (st.warning if issue["level"] == "warning" else st.error)(
                    issue["message"]
                )
        else:
            st.info("No validation issues flagged.")

        st.markdown("#### Outcome catalogue")
        st.caption(
            "Every outcome captured for this project, with its current status. `Configured` means captured "
            "here only; `Excluded` means captured "
            "but held back from the next fit; `Missing source column` means its mapped column isn't "
            "in the current data; `Included in prepared frame` / `Included in fitted run` reflect "
            "this session's actual Model Setup / Fit Model state, if any; `Stale after "
            "configuration changes` means it used to be prepared or fit but its column has since "
            "disappeared from the data."
        )
        outcomes_df = outcomes_to_dataframe(
            outcome_definitions,
            available_columns=set(df.columns),
            frame_outcome_ids=(get_state("frame") or {}).get("outcome_ids"),
            model_meta_outcome_ids=getattr(
                get_state("model_meta"), "outcome_ids", None
            ),
        )
        st.dataframe(
            outcomes_df,
            width="stretch",
            column_config=dataframe_column_config(outcomes_df),
        )
_validation_section.__exit__(None, None, None)

if get_state("model_spec"):
    render_next_step("structure")
