"""Page 4: interface-driven model configuration - hierarchy, adstock/saturation priors, DNA halo lag, MCMC settings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, clear_model_state, DEFAULT_FH_PRIORS
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.data import prepare_fh_modeling_frame

st.set_page_config(page_title="Model Configuration - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()

st.title("⚙️ Model Configuration")
st.caption(
    "Configuration is interface-driven, not hand-edited model code: hierarchy, adstock/saturation "
    "priors and DNA halo lag are all set here."
)

spec_dict = get_state("model_spec")
df = get_state("transformed_data")
if not spec_dict or df is None:
    st.warning("Define the structure first on **Structure: Segments & Markets**.")
    st.stop()

spec = ModelSpec.from_dict(spec_dict)

st.markdown("### Geo hierarchy")
st.info(
    f"Markets: {', '.join(spec.markets)}. "
    f"Partially pooled: {', '.join(m for m in spec.markets if m not in spec.unpooled_markets) or '(none)'}. "
    f"Unpooled: {', '.join(spec.unpooled_markets) or '(none)'} "
    "- change this back on the Structure page."
)

st.markdown("---")
st.markdown("### Shared adstock & saturation curve priors")
st.caption("Stage 1 core: geometric adstock + Hill saturation, shared across segments and markets per channel.")

prior_config = dict(get_state("prior_config") or DEFAULT_FH_PRIORS)

c1, c2 = st.columns(2)
with c1:
    prior_config["decay_mu"] = st.slider("Adstock decay - prior mean", 0.05, 0.95, float(prior_config["decay_mu"]), 0.05)
    prior_config["decay_sigma"] = st.slider("Adstock decay - prior sd", 0.05, 0.5, float(prior_config["decay_sigma"]), 0.05)
    prior_config["K_scale"] = st.slider(
        "Saturation half-point (K) - prior mean, as a multiple of average spend",
        0.3, 3.0, float(prior_config["K_scale"]), 0.1,
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
        0.05, 1.0, float(prior_config["pooling_sigma_prior"]), 0.05,
    )
    prior_config["market_pool_sigma_prior"] = st.slider(
        "Market pooling prior (partially-pooled markets)", 0.05, 1.0, float(prior_config["market_pool_sigma_prior"]), 0.05,
    )
with c2:
    prior_config["dna_halo_sigma"] = st.slider(
        "DNA halo strength prior (non-DNA segments) - kept tight by default ('smaller effect elsewhere')",
        0.05, 1.0, float(prior_config["dna_halo_sigma"]), 0.05,
    )
    dna_lag_weeks = st.number_input(
        "DNA halo lag (weeks) - decision-time lag beyond adstock carryover",
        min_value=0, max_value=12, value=int(get_state("dna_lag_weeks", 4)),
    )

st.markdown("---")
st.markdown("### Promotional sensitivity prior")
prior_config["promo_sigma"] = st.slider("Promo sensitivity prior sd (per segment)", 0.05, 1.5, float(prior_config["promo_sigma"]), 0.05)

st.markdown("---")
st.markdown("### MCMC settings")
c1, c2, c3, c4 = st.columns(4)
mcmc_draws = c1.number_input("Draws", min_value=200, max_value=5000, value=int(get_state("mcmc_draws", 2000)), step=200)
mcmc_tune = c2.number_input("Tune", min_value=200, max_value=5000, value=int(get_state("mcmc_tune", 1000)), step=200)
mcmc_chains = c3.number_input("Chains", min_value=1, max_value=8, value=int(get_state("mcmc_chains", 4)))
mcmc_target_accept = c4.slider("Target accept", 0.7, 0.99, float(get_state("mcmc_target_accept", 0.9)), 0.01)

st.markdown("---")
if st.button("Prepare modelling frame", type="primary"):
    try:
        frame = prepare_fh_modeling_frame(df, spec)
        set_state("frame", frame)
        set_state("prior_config", prior_config)
        set_state("dna_lag_weeks", int(dna_lag_weeks))
        set_state("mcmc_draws", int(mcmc_draws))
        set_state("mcmc_tune", int(mcmc_tune))
        set_state("mcmc_chains", int(mcmc_chains))
        set_state("mcmc_target_accept", float(mcmc_target_accept))
        clear_model_state()
        set_state("frame", frame)  # clear_model_state wipes frame too - reset after
        st.success(
            f"Frame prepared: {frame['X_media'].shape[0]} observations, "
            f"{len(frame['channels'])} channels, {len(frame['segments'])} segments, "
            f"{len(frame['markets'])} market(s)."
        )
    except ValueError as e:
        st.error(str(e))

if get_state("frame") is not None:
    st.markdown("---")
    if st.button("Continue to Model Training →", type="primary"):
        st.switch_page("pages/05_Model_Training.py")
