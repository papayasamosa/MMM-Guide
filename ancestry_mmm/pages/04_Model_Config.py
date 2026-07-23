"""Page 4: interface-driven model configuration - hierarchy, adstock/saturation priors, DNA halo lag, MCMC settings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, clear_model_state, DEFAULT_FH_PRIORS, format_number, FIELD_HELP
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state, render_drift_status
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.outcomes import resolve_outcome_definitions, dna_kit_outcome_columns, included_outcomes
from ancestry_mmm.core.brand_search import BRAND_SEARCH_MODES, BrandSearchConfig, validate_brand_search_configs
from ancestry_mmm.data import prepare_fh_modeling_frame
import pandas as pd

st.set_page_config(page_title="Model Configuration - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("model_config")
render_page_header("model_config")

spec_dict = get_state("model_spec")
df = get_state("transformed_data")
if not spec_dict or df is None:
    st.markdown("---")
    render_empty_state(
        "No structure defined yet. Complete Structure: Segments & Markets first.",
        button_label="Go to Structure: Segments & Markets", target_key="structure",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)

st.markdown("---")
st.markdown("### Geo hierarchy")
st.info(
    f"Markets: {', '.join(spec.markets)}. "
    f"Partially pooled: {', '.join(m for m in spec.markets if m not in spec.unpooled_markets) or '(none)'}. "
    f"Unpooled: {', '.join(spec.unpooled_markets) or '(none)'} "
    "- change this back on the Structure page."
)

st.markdown("---")
st.markdown("### Model structure")
n_markets = len(spec.markets)
model_type_options = ["shared", "market_specific"]
model_type_labels = {
    "shared": "Shared curve across markets (Model A)",
    "market_specific": "Market-specific, partially pooled (Model C)",
}
current_model_type = get_state("model_type", "shared")
if n_markets < 2 and current_model_type == "market_specific":
    st.warning(
        "Market-specific curves need at least 2 markets; this project has 1. Falling back to the "
        "shared-curve model. Add another market on Structure: Segments & Markets to use "
        "market-specific curves."
    )
    current_model_type = "shared"
model_type = st.radio(
    "Choose how channel response curves are estimated across markets",
    model_type_options, index=model_type_options.index(current_model_type),
    format_func=lambda t: model_type_labels[t],
    disabled=(n_markets < 2),
    help=FIELD_HELP["model_type_shared"] if current_model_type == "shared" else FIELD_HELP["model_type_market_specific"],
)
if n_markets < 2:
    st.caption("Only 1 market in this project - market-specific curves are unavailable until there are at least 2.")
st.caption(
    FIELD_HELP["model_type_market_specific"] if model_type == "market_specific" else FIELD_HELP["model_type_shared"]
)

st.markdown("---")
st.markdown("### Shared adstock & saturation curve priors")
st.caption(FIELD_HELP["priors"] + " Stage 1 core: geometric adstock + Hill saturation, shared across segments and markets per channel.")

prior_config = dict(get_state("prior_config") or DEFAULT_FH_PRIORS)

c1, c2 = st.columns(2)
with c1:
    prior_config["decay_mu"] = st.slider(
        "Adstock decay - prior mean", 0.05, 0.95, float(prior_config["decay_mu"]), 0.05, help=FIELD_HELP["adstock_decay"],
    )
    prior_config["decay_sigma"] = st.slider("Adstock decay - prior sd", 0.05, 0.5, float(prior_config["decay_sigma"]), 0.05)
    prior_config["K_scale"] = st.slider(
        "Saturation half-point (K) - prior mean, as a multiple of average spend",
        0.3, 3.0, float(prior_config["K_scale"]), 0.1, help=FIELD_HELP["hill_saturation"],
    )
with c2:
    prior_config["S_alpha"] = st.slider("Saturation shape (S) - Gamma alpha", 1.0, 10.0, float(prior_config["S_alpha"]), 0.5)
    prior_config["S_beta"] = st.slider("Saturation shape (S) - Gamma beta", 1.0, 10.0, float(prior_config["S_beta"]), 0.5)

st.markdown("---")
st.markdown("### Segment partial pooling & DNA halo")
c1, c2 = st.columns(2)
with c1:
    prior_config["pooling_sigma_prior"] = st.slider(
        "Segment divergence prior (sigma_pool) - larger = segments allowed to diverge more freely",
        0.05, 1.0, float(prior_config["pooling_sigma_prior"]), 0.05, help=FIELD_HELP["partial_pooling"],
    )
    prior_config["market_pool_sigma_prior"] = st.slider(
        "Market pooling prior (partially-pooled markets)", 0.05, 1.0, float(prior_config["market_pool_sigma_prior"]), 0.05,
        help=FIELD_HELP["partial_pooling"],
    )
with c2:
    prior_config["active_cross_product_sigma"] = st.slider(
        "Active cross-product strength prior - the DNA halo pathway's prior by default, kept tight "
        "('smaller effect elsewhere'); PR G1 generalises this beyond DNA channels for any pathway "
        "catalogue cell explicitly marked active_cross_product (core.pathways).",
        0.05, 1.0, float(prior_config.get("active_cross_product_sigma", 0.25)), 0.05,
    )
    prior_config["exploratory_cross_product_sigma"] = st.slider(
        "Exploratory cross-product strength prior - strongly shrunk toward zero by default; applies "
        "only to pathway catalogue cells explicitly marked exploratory_cross_product, never trusted "
        "for planning by default (see Structure page's pathway catalogue).",
        0.02, 0.5, float(prior_config.get("exploratory_cross_product_sigma", 0.08)), 0.02,
    )
    dna_lag_weeks = st.number_input(
        "DNA halo lag (weeks) - decision-time lag beyond adstock carryover, shared by every "
        "active/exploratory cross-product cell (core.pathways.ResolvedPathwayMasks.cross_product_lag_weeks)",
        min_value=0, max_value=12, value=int(get_state("dna_lag_weeks", 4)), help=FIELD_HELP["dna_halo_lag"],
    )

st.markdown("---")
st.markdown("### Promotional sensitivity prior")
prior_config["promo_sigma"] = st.slider("Promo sensitivity prior sd (per segment)", 0.05, 1.5, float(prior_config["promo_sigma"]), 0.05)

st.markdown("---")
st.markdown("### Brand Search treatment mode")
st.caption(
    "How each Brand Search channel's known ambiguity (some of its response is genuinely incremental, "
    "some is upper-funnel demand it just happens to capture last-click) is treated - four explicit "
    "modes (core.brand_search), never a silent default assumption about which is 'true'. "
    "`direct_channel`/`demand_capture_mediator`/`experiment_calibrated_incremental` all fit as an "
    "ordinary primary_direct channel; `excluded` needs a matching `role=excluded` row for this "
    "channel on the Structure page's pathway catalogue to actually drop it from the fit - this table "
    "only controls how a channel's ALREADY-fitted contribution is reported/reallocated afterwards, it "
    "does not by itself change fitting."
)
if "brand_search_configs" not in st.session_state:
    st.session_state["brand_search_configs"] = get_state("brand_search_configs") or []
if st.session_state["brand_search_configs"]:
    # mediator_of is stored as a real list (BrandSearchConfig.mediator_of) -
    # st.column_config.TextColumn can't bind to a list-typed column, so it's
    # rendered/edited as a comma-joined string and parsed back to a list below.
    _brand_search_default_df = pd.DataFrame([
        {**row, "mediator_of": ", ".join(row.get("mediator_of") or [])}
        for row in st.session_state["brand_search_configs"]
    ])
else:
    _brand_search_default_df = pd.DataFrame(
        columns=["channel", "mode", "mediator_of", "mediation_share", "calibration_factor", "notes"]
    )
brand_search_df = st.data_editor(
    _brand_search_default_df,
    num_rows="dynamic",
    column_config={
        "channel": st.column_config.SelectboxColumn("channel", options=spec.channels, required=True),
        "mode": st.column_config.SelectboxColumn("mode", options=list(BRAND_SEARCH_MODES), required=True),
        "mediator_of": st.column_config.TextColumn(
            "mediator_of", help="Comma-separated upstream channels this Brand Search channel mediates "
            "(demand_capture_mediator only) - e.g. 'TV, YouTube'.",
        ),
        "mediation_share": st.column_config.NumberColumn(
            "mediation_share", min_value=0.0, max_value=1.0, help="demand_capture_mediator only.",
        ),
        "calibration_factor": st.column_config.NumberColumn(
            "calibration_factor", min_value=0.0, max_value=1.0, help="experiment_calibrated_incremental only.",
        ),
        "notes": st.column_config.TextColumn("notes"),
    },
    key="brand_search_config_editor",
    width="stretch",
)
brand_search_configs = []
for row in brand_search_df.to_dict("records"):
    if not (row.get("channel") and row.get("mode")):
        continue  # a blank row added by the editor but never filled in
    mediator_of = [c.strip() for c in str(row.get("mediator_of") or "").split(",") if c.strip()]
    brand_search_configs.append(BrandSearchConfig(
        channel=row["channel"], mode=row["mode"], mediator_of=mediator_of,
        mediation_share=row.get("mediation_share"), calibration_factor=row.get("calibration_factor"),
        notes=row.get("notes") or "",
    ))
brand_search_errors = validate_brand_search_configs(brand_search_configs, known_channels=spec.channels)
for e in brand_search_errors:
    st.error(e)

st.markdown("---")
with st.expander("Advanced settings: MCMC sampling"):
    st.caption("Reasonable defaults are pre-filled. Increase draws/tune for a more reliable fit; reduce them for a quicker check.")
    c1, c2, c3, c4 = st.columns(4)
    mcmc_draws = c1.number_input("Draws", min_value=200, max_value=5000, value=int(get_state("mcmc_draws", 2000)), step=200, key="mcmc_draws_input")
    mcmc_tune = c2.number_input("Tune", min_value=200, max_value=5000, value=int(get_state("mcmc_tune", 1000)), step=200, key="mcmc_tune_input")
    mcmc_chains = c3.number_input("Chains", min_value=1, max_value=8, value=int(get_state("mcmc_chains", 4)), key="mcmc_chains_input")
    mcmc_target_accept = c4.slider("Target accept", 0.7, 0.99, float(get_state("mcmc_target_accept", 0.9)), 0.01, key="mcmc_target_accept_input")

outcome_definitions = resolve_outcome_definitions(get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv)
render_drift_status(outcome_definitions, get_state("model_meta"), available_columns=set(df.columns))
included_outcome_definitions = included_outcomes(outcome_definitions)
dna_kit_outcomes = dna_kit_outcome_columns(included_outcome_definitions)
dna_kit_outcomes = {oid: col for oid, col in dna_kit_outcomes.items() if col in df.columns}
excluded_dna_outcomes = [o for o in outcome_definitions if not o.included_in_fit]

st.markdown("---")
if excluded_dna_outcomes:
    st.caption(
        f"Excluded from this fit (see Structure): {', '.join(o.outcome_id for o in excluded_dna_outcomes)}."
    )
if dna_kit_outcomes:
    st.info(
        f"DNA outcomes mapped on Structure will be included in this fit: {', '.join(dna_kit_outcomes)}. "
        "DNA-targeted media gets full direct response on these outcomes, same as the FH DNA-cross-sell "
        "outcome - see docs/dna_fh_causal_structure.md."
    )
else:
    st.caption(
        "No DNA outcomes mapped (or their columns aren't in the current data) - fitting Family "
        "History segments only. Map DNA kit columns on Structure: Segments & Markets to include them."
    )
if spec.dna_channels and not spec.fh_dna_cross_sell_outcome_id:
    st.warning(
        "DNA-targeted media is configured but no FH DNA cross-sell outcome was selected on the "
        "Structure page - Model Training will fail to fit until one is chosen there (automatic "
        "name-based inference is no longer used for a live fit)."
    )

if brand_search_errors:
    st.caption("Fix the Brand Search configuration errors above before preparing the modelling frame.")
elif st.button("Prepare modelling frame", type="primary"):
    try:
        frame = prepare_fh_modeling_frame(
            df, spec, outcomes=outcome_definitions,
            net_billthrough_metadata=get_state("net_billthrough_metadata"),
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
        set_state("brand_search_configs", [c.to_dict() for c in brand_search_configs])
        clear_model_state()
        set_state("frame", frame)  # clear_model_state wipes frame too - reset after
        st.success(
            f"Frame prepared: {format_number(frame['X_media'].shape[0])} observations, "
            f"{len(frame['channels'])} channels, {len(frame['outcome_ids'])} outcomes, "
            f"{len(frame['markets'])} market(s). Model structure: {model_type_labels[model_type]}."
        )
    except ValueError as e:
        st.error(f"Could not prepare the modelling frame: {e} Review the structure and try again.")

if get_state("frame") is not None:
    render_next_step("model_config")
