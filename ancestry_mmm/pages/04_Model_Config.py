"""Page 4: interface-driven model configuration - hierarchy, adstock/saturation priors, DNA halo lag, MCMC settings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, clear_model_state, DEFAULT_FH_PRIORS, format_number, FIELD_HELP
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.outcomes import resolve_outcome_definitions, dna_kit_outcome_columns
from ancestry_mmm.data import prepare_fh_modeling_frame

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
    prior_config["dna_halo_sigma"] = st.slider(
        "DNA halo strength prior (non-DNA segments) - kept tight by default ('smaller effect elsewhere')",
        0.05, 1.0, float(prior_config["dna_halo_sigma"]), 0.05,
    )
    dna_lag_weeks = st.number_input(
        "DNA halo lag (weeks) - decision-time lag beyond adstock carryover",
        min_value=0, max_value=12, value=int(get_state("dna_lag_weeks", 4)), help=FIELD_HELP["dna_halo_lag"],
    )

st.markdown("---")
st.markdown("### Promotional sensitivity prior")
prior_config["promo_sigma"] = st.slider("Promo sensitivity prior sd (per segment)", 0.05, 1.5, float(prior_config["promo_sigma"]), 0.05)

st.markdown("---")
with st.expander("Advanced settings: MCMC sampling"):
    st.caption("Reasonable defaults are pre-filled. Increase draws/tune for a more reliable fit; reduce them for a quicker check.")
    c1, c2, c3, c4 = st.columns(4)
    mcmc_draws = c1.number_input("Draws", min_value=200, max_value=5000, value=int(get_state("mcmc_draws", 2000)), step=200, key="mcmc_draws_input")
    mcmc_tune = c2.number_input("Tune", min_value=200, max_value=5000, value=int(get_state("mcmc_tune", 1000)), step=200, key="mcmc_tune_input")
    mcmc_chains = c3.number_input("Chains", min_value=1, max_value=8, value=int(get_state("mcmc_chains", 4)), key="mcmc_chains_input")
    mcmc_target_accept = c4.slider("Target accept", 0.7, 0.99, float(get_state("mcmc_target_accept", 0.9)), 0.01, key="mcmc_target_accept_input")

outcome_definitions = resolve_outcome_definitions(get_state("outcome_definitions"), spec.segment_outcomes, spec.segment_ltv)
excluded_outcome_ids = set(get_state("excluded_outcome_ids") or [])
included_outcome_definitions = [o for o in outcome_definitions if o.outcome_id not in excluded_outcome_ids]
dna_kit_outcomes = dna_kit_outcome_columns(included_outcome_definitions)
dna_kit_outcomes = {seg: col for seg, col in dna_kit_outcomes.items() if col in df.columns}
excluded_dna_outcomes = [o for o in outcome_definitions if o.outcome_id in excluded_outcome_ids]

st.markdown("---")
if excluded_dna_outcomes:
    st.caption(
        f"Excluded from this fit (see Structure): {', '.join(o.segment for o in excluded_dna_outcomes)}."
    )
if dna_kit_outcomes:
    st.info(
        f"DNA outcomes mapped on Structure will be included in this fit: {', '.join(dna_kit_outcomes)}. "
        "DNA-targeted media gets full direct response on these segments, same as the FH DNA-cross-sell "
        "segment - see docs/dna_fh_causal_structure.md."
    )
else:
    st.caption(
        "No DNA outcomes mapped (or their columns aren't in the current data) - fitting Family "
        "History segments only. Map DNA kit columns on Structure: Segments & Markets to include them."
    )

if st.button("Prepare modelling frame", type="primary"):
    try:
        frame = prepare_fh_modeling_frame(df, spec, dna_kit_outcomes=dna_kit_outcomes)
        set_state("frame", frame)
        set_state("prior_config", prior_config)
        set_state("dna_lag_weeks", int(dna_lag_weeks))
        set_state("mcmc_draws", int(mcmc_draws))
        set_state("mcmc_tune", int(mcmc_tune))
        set_state("mcmc_chains", int(mcmc_chains))
        set_state("mcmc_target_accept", float(mcmc_target_accept))
        set_state("model_type", model_type)
        set_state("direct_dna_segments", list(dna_kit_outcomes.keys()))
        clear_model_state()
        set_state("frame", frame)  # clear_model_state wipes frame too - reset after
        st.success(
            f"Frame prepared: {format_number(frame['X_media'].shape[0])} observations, "
            f"{len(frame['channels'])} channels, {len(frame['segments'])} segments, "
            f"{len(frame['markets'])} market(s). Model structure: {model_type_labels[model_type]}."
        )
    except ValueError as e:
        st.error(f"Could not prepare the modelling frame: {e} Review the structure and try again.")

if get_state("frame") is not None:
    render_next_step("model_config")
