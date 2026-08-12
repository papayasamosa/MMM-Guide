"""Page (step 8 of 12): compare fitted candidate models side by side before
choosing which to take forward to Diagnostics for approval - the model
comparison workflow from docs/model_validation.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    dataframe_column_config,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_glossary,
    SectionCard,
    render_status_badge,
)
from ancestry_mmm.core.model_comparison import (
    ModelComparisonCandidate,
    candidates_decision_summary_dataframe,
    candidates_to_dataframe,
)

st.set_page_config(
    page_title="Compare Models - Ancestry FH MMM", page_icon="🧬", layout="wide"
)
init_session_state()
apply_theme()
render_sidebar("compare_models")
render_page_header("compare_models")
render_glossary(
    ["Model comparison", "Market-specific curve", "Shrinkage", "Partial pooling"]
)

st.markdown("---")
st.markdown(
    "Three candidate model structures are worth comparing before trusting a market-specific fit: "
    "**Model A** (one shared curve across markets), **Model B** (an independent fit per market), "
    "and **Model C** (partially pooled, market-specific curves). The partially pooled model isn't "
    "adopted just for being more sophisticated - it should show comparable-or-better prediction, "
    "credible market differentiation, and acceptable diagnostics."
)
st.caption(
    "To get a Model B candidate: go to Structure: Segments & Markets, select a single market, save, "
    "then fit and save a candidate on Model Training as usual - fitting the shared-curve model "
    "(Model A) against one market's data *is* an independent per-market fit."
)

candidate_dicts = get_state("model_comparison_candidates") or []
if not candidate_dicts:
    st.info(
        "No comparison candidates saved yet. Fit a model on Model Training, then use "
        '"Save this fit as a comparison candidate" to add it here.'
    )
else:
    candidates = [ModelComparisonCandidate.from_dict(d) for d in candidate_dicts]

    with SectionCard(
        "Candidates at a glance",
        description=(
            "The dimensions that help decide what to inspect next - not a ranking. Deeper "
            "evidence (R-hat, ESS, mean R-squared/MAPE, PPC coverage) is available below."
        ),
    ):
        summary_table = candidates_decision_summary_dataframe(candidates)
        st.dataframe(
            summary_table,
            width="stretch",
            column_config=dataframe_column_config(summary_table),
        )
        st.caption(
            "Shown separately by design: convergence, predictive fit, and plausibility are "
            "independent dimensions - a model that converges cleanly can still fit poorly, and a "
            "model that fits well can still raise plausibility flags. No composite score collapses "
            "them into one ranking number."
        )

    with st.expander("Full comparison table (R-hat, ESS, mean R-squared/MAPE, PPC coverage)"):
        table = candidates_to_dataframe(candidates)
        st.dataframe(table, width="stretch", column_config=dataframe_column_config(table))

    st.markdown("---")
    st.markdown("### Candidate detail")
    labels = [c.label for c in candidates]
    chosen_label = st.selectbox("Candidate", labels)
    chosen = next(c for c in candidates if c.label == chosen_label)
    st.caption(
        f"Model run: `{chosen.model_run_id[:8]}` - {chosen.n_plausibility_flags} plausibility flag(s)."
    )

    tab_conv, tab_fit, tab_ppc = st.tabs(
        ["Convergence", "In-sample fit", "Posterior predictive coverage"]
    )
    with tab_conv:
        render_status_badge(
            "validated" if chosen.convergence.get("converged") else "failed",
            label="Converged" if chosen.convergence.get("converged") else "Not converged",
        )
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Max R-hat",
            f"{chosen.convergence.get('rhat_max', float('nan')):.3f}"
            if chosen.convergence.get("rhat_max") is not None
            else "n/a",
        )
        c2.metric(
            "Min ESS",
            f"{chosen.convergence.get('ess_min', 0):.0f}"
            if chosen.convergence.get("ess_min") is not None
            else "n/a",
        )
        c3.metric("Divergences", chosen.convergence.get("divergences", "n/a"))

    with tab_fit:
        if chosen.in_sample_fit:
            st.dataframe(pd.DataFrame(chosen.in_sample_fit), width="stretch")
        else:
            st.info("No in-sample fit evidence recorded for this candidate.")

    with tab_ppc:
        if chosen.ppc_coverage:
            st.dataframe(pd.DataFrame(chosen.ppc_coverage), width="stretch")
        else:
            st.info("No posterior predictive coverage evidence recorded for this candidate.")

    if st.button(f"Remove '{chosen_label}'"):
        candidate_dicts = [d for d in candidate_dicts if d.get("label") != chosen_label]
        set_state("model_comparison_candidates", candidate_dicts)
        st.rerun()

render_next_step("compare_models")
