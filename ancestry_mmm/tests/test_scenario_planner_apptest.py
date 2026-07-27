"""AppTest coverage for the Scenario Planner page's value-mapping/currency
wiring (G2A.7a.10, brief section 14.9).

The general smoke test (test_streamlit_smoke.py) only drives this page with
an *empty* session state, which short-circuits at the "no trained model yet"
guard before any of the objective/value-mapping/currency logic this brief
changed ever executes. These tests populate a genuinely consistent session
state (a real fitted frame/posterior/approval, matching fingerprints exactly
the way the page itself recomputes them) so the expected-value objective
path - CurrencyContext derived from selected targets, OutcomeValueMapping
threaded into manual evaluation - is actually exercised end-to-end through
the real page, not just at the core-function level."""

from pathlib import Path

import arviz as az
import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.outcome_approval import OutcomeApproval, fingerprint_outcome_definition
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
    outcome_catalogue_fingerprint_payload,
    outcome_eligibility,
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "08_Scenario_Planner.py"


def _meta(outcome_catalogue) -> FHModelMeta:
    outcome_ids = [o.outcome_id for o in outcome_catalogue]
    return FHModelMeta(
        markets=["UK"], outcome_ids=outcome_ids, channels=["TV_Brand"],
        dna_channels=[], dna_channel_idx=[], non_dna_idx=[0],
        dna_outcome_id=outcome_ids[0], dna_lag_weeks=4, unpooled_markets=[], control_names=[],
        outcome_catalogue_at_fit=outcome_catalogue,
        # eligible_outcome_ids() (core.outcomes) reads this map, not the
        # OutcomeDefinition's own include_in_value/include_in_optimisation
        # fields directly - without it every outcome falls back to the
        # "primary" role default (eligible for everything).
        outcome_id_to_eligibility={
            o.outcome_id: outcome_eligibility(o) for o in outcome_catalogue
        },
    )


def _trace(meta: FHModelMeta, n_fourier: int = 6, chains: int = 2, draws: int = 10, seed: int = 0) -> az.InferenceData:
    rng = np.random.default_rng(seed)
    n_ch, n_seg, n_mkt = len(meta.channels), len(meta.outcome_ids), len(meta.markets)
    posterior = {
        "decay_rate": rng.uniform(0.1, 0.9, size=(chains, draws, n_ch)),
        "hill_K": rng.uniform(500, 2000, size=(chains, draws, n_ch)),
        "hill_S": rng.uniform(0.5, 2.0, size=(chains, draws, n_ch)),
        "intercept": rng.normal(size=(chains, draws, n_seg)),
        "trend_coef": rng.normal(size=(chains, draws, n_seg)),
        "promo_coef": rng.uniform(0, 1, size=(chains, draws, n_seg)),
        "alpha": rng.uniform(1, 10, size=(chains, draws, n_seg)),
        "beta": rng.normal(size=(chains, draws, n_seg, n_ch)),
        "market_offset": rng.normal(size=(chains, draws, n_mkt, n_seg)),
        "gamma_fourier": rng.normal(size=(chains, draws, n_fourier, n_seg)),
    }
    coords = {"channel": meta.channels, "outcome": meta.outcome_ids, "market": meta.markets, "fourier": list(range(n_fourier))}
    dims = {
        "decay_rate": ["channel"], "hill_K": ["channel"], "hill_S": ["channel"],
        "intercept": ["outcome"], "trend_coef": ["outcome"], "promo_coef": ["outcome"],
        "alpha": ["outcome"], "beta": ["outcome", "channel"],
        "market_offset": ["market", "outcome"], "gamma_fourier": ["fourier", "outcome"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


def _seed_consistent_session_state(
    at: AppTest, *, value_currency: str, non_target_outcome_currency: str | None = None,
) -> None:
    """Populate session state with a real, internally consistent fitted
    model - the approval's identity fingerprints are computed the exact
    same way the page itself recomputes "current_identity", so
    approval_matches_current is True and the page proceeds past its
    approval-gate st.stop() calls.

    When ``non_target_outcome_currency`` is given, a second outcome is added
    with ``include_in_value=False`` (so it is never a target for the
    "expected_value" objective) priced in that currency - brief section
    14.6/10.1: a non-target outcome in another currency must never block an
    otherwise single-currency objective."""
    outcome_def = OutcomeDefinition(
        outcome_id="New", product=FAMILY_HISTORY, segment="New", metric="GSA",
        metric_key=METRIC_KEY_FH_GSA, source_column="fh_new_gsa", unit="GSA",
        aggregation_type="count", event_definition="A new subscriber",
        date_basis="event_date", cohort_or_attribution_basis="signup_cohort",
        completeness_or_maturity_policy="Mature after 12 weeks",
        exclusions="Excludes internal test accounts",
        reconciliation_source="Finance report", business_owner="Analytics",
        definition_version="1.0",
        value_weight=5.0, value_currency=value_currency,
        include_in_value=True, include_in_optimisation=True,
    )
    outcome_defs = [outcome_def]
    segment_outcomes = {"New": "fh_new_gsa"}
    source_columns = {"fh_new_gsa": np.linspace(10.0, 16.0, 16)}
    if non_target_outcome_currency is not None:
        non_target_def = OutcomeDefinition(
            outcome_id="Winback", product=FAMILY_HISTORY, segment="Winback", metric="GSA",
            metric_key=METRIC_KEY_FH_GSA, source_column="fh_winback_gsa", unit="GSA",
            aggregation_type="count", event_definition="A winback subscriber",
            date_basis="event_date", cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            exclusions="Excludes internal test accounts",
            reconciliation_source="Finance report", business_owner="Analytics",
            definition_version="1.0",
            value_weight=3.0, value_currency=non_target_outcome_currency,
            include_in_value=False, include_in_optimisation=False,
        )
        outcome_defs.append(non_target_def)
        segment_outcomes["Winback"] = "fh_winback_gsa"
        source_columns["fh_winback_gsa"] = np.linspace(4.0, 7.0, 16)

    meta = _meta(outcome_defs)
    trace = _trace(meta)
    transformed_data = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=16, freq="W"),
        "market": ["UK"] * 16,
        "TV_Brand": np.linspace(100.0, 250.0, 16),
        **source_columns,
    })
    model_spec_dict = ModelSpec(
        date_col="date", market_col="market", markets=["UK"],
        segment_outcomes=segment_outcomes, channels=["TV_Brand"],
    ).to_dict()
    prior_config = {"decay_mu": 0.5}
    dna_lag_weeks = 4
    spec = ModelSpec.from_dict(model_spec_dict)
    frame = prepare_fh_modeling_frame(transformed_data, spec)
    posterior_params = extract_posterior_params(trace, meta)

    model_run_id = "run-scenario-planner-apptest"
    # Must match exactly how the page itself recomputes "current_identity"
    # (08_Scenario_Planner.py) - same helper calls, same arguments (empty
    # activity_definitions/None market_spec_config/None funnel_links, since
    # this fixture doesn't set those session-state keys).
    approval = ModelApproval(
        approved_by="Jane Analyst",
        model_run_id=model_run_id,
        data_fingerprint=fingerprint_dataframe(frame["df"]),
        model_spec_fingerprint=fingerprint_model_spec(
            model_spec_dict, prior_config, dna_lag_weeks, model_type="shared",
            pipeline_steps=[], market_spec_config=None,
            direct_dna_outcome_ids=meta.direct_dna_outcome_ids,
            outcome_catalogue=outcome_catalogue_fingerprint_payload(meta.outcome_catalogue_at_fit),
            funnel_links=None,
            media_outcome_pathways=pathway_catalogue_fingerprint_payload(meta.pathway_catalogue_at_fit),
            activity_fit_fingerprint=None,
        ),
        posterior_fingerprint=fingerprint_posterior(posterior_params),
    )

    at.session_state["frame"] = frame
    at.session_state["model_meta"] = meta
    at.session_state["posterior_params"] = posterior_params
    at.session_state["model_spec"] = model_spec_dict
    at.session_state["trace"] = trace
    at.session_state["model_type"] = "shared"
    at.session_state["model_run_id"] = model_run_id
    at.session_state["prior_config"] = prior_config
    at.session_state["dna_lag_weeks"] = dna_lag_weeks
    at.session_state["model_approval"] = approval.to_dict()
    at.session_state["outcome_definitions"] = [o.to_dict() for o in outcome_defs]
    outcome_approvals = [
        OutcomeApproval(
            approval_id=f"apr-{o.outcome_id}", outcome_id=o.outcome_id,
            definition_fingerprint=fingerprint_outcome_definition(o),
            status="approved", allowed_uses=("planning", "optimisation"),
            approved_by="Jane Analyst", approved_at="2026-01-01",
        )
        for o in outcome_defs
    ]
    at.session_state["outcome_approvals"] = [a.to_dict() for a in outcome_approvals]
    at.session_state["activity_definitions"] = []
    at.session_state["media_cost_mappings"] = None


def test_expected_value_objective_derives_currency_and_evaluates_manual_tab():
    """G2A.7a.10 sections 9-11: with a real fitted model whose only target
    outcome has value_weight=5.0/value_currency="GBP", selecting "Maximise
    LTV-weighted expected value" must derive GBP from the target (not crash
    for lack of a whole-catalogue-derived currency), build a real
    OutcomeValueMapping, and the manual tab must evaluate without raising."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    objective_radio = [r for r in at.radio if r.label == "Optimisation objective"]
    assert objective_radio, "objective radio not found"
    objective_radio[0].set_value("expected_value").run()
    assert not at.exception, f"selecting expected_value raised: {at.exception}"

    # Currency derived from the target outcome, not the whole catalogue.
    captions = [c.value for c in at.caption]
    assert any("GBP" in c for c in captions if c), (
        f"expected a GBP value-currency caption, got: {captions}"
    )
    # No "no value weights configured" warning - the catalogue-sourced
    # OutcomeValueMapping covers the only target outcome.
    warnings_text = [w.value for w in at.warning]
    assert not any("value mapping" in (w or "") for w in warnings_text), warnings_text


@pytest.mark.parametrize("value_currency", ["USD"])
def test_non_gbp_target_currency_also_resolves(value_currency):
    """A single governed non-GBP target currency (brief section 14.6: "selected
    USD targets succeed") must resolve just as cleanly as GBP - nothing on
    the page hard-codes a currency."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency=value_currency)
    at.run()
    assert not at.exception

    objective_radio = [r for r in at.radio if r.label == "Optimisation objective"]
    objective_radio[0].set_value("expected_value").run()
    assert not at.exception, f"selecting expected_value raised: {at.exception}"

    captions = [c.value for c in at.caption]
    assert any(value_currency in c for c in captions if c), captions


def test_non_target_outcome_in_another_currency_does_not_block():
    """G2A.7a.10 (brief sections 10.1, 14.6): a non-target outcome priced in
    a different currency (include_in_value=False, so it's never resolved as
    an expected-value target) must not null out the target outcome's own
    single-currency resolution - the old whole-catalogue-derived currency
    logic would have seen {"GBP", "USD"} and given up with None."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(
        at, value_currency="GBP", non_target_outcome_currency="USD",
    )
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    objective_radio = [r for r in at.radio if r.label == "Optimisation objective"]
    objective_radio[0].set_value("expected_value").run()
    assert not at.exception, f"selecting expected_value raised: {at.exception}"

    captions = [c.value for c in at.caption]
    assert any("GBP" in c for c in captions if c), (
        f"expected GBP to resolve despite the non-target USD outcome, got: {captions}"
    )
    warnings_text = [w.value for w in at.warning]
    assert not any("value mapping" in (w or "") for w in warnings_text), warnings_text
