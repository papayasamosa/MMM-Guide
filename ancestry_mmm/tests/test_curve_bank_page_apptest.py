"""AppTest coverage for PR 82F: the Curve Bank page's approval-validity gate.

Before this PR, 07_Results_Curve_Bank.py gated "can I save to the curve
bank" with a bare ModelApproval.matches_current_model() check - the exact
"weaker, identity-only check" PR 82B replaced on Diagnostics with
require_matching_approval() (which additionally verifies a policy-backed
approval's bound readiness is still overall_ready and still matches the
current policy/model). core.curve_bank.make_entries() itself already calls
require_matching_approval() and accepts approval_readiness/current_policy -
but the page never supplied them, so a policy-backed approval would pass
the page's own (too-permissive) display gate and then raise an uncaught
ValidationPolicyBlockedError inside make_entries() when the analyst
actually clicked "Save".

These tests seed a real fitted model (mirroring
test_scenario_planner_apptest.py's fixture recipe, since 08_Scenario_Planner
and 07_Results_Curve_Bank compute "current_identity" identically) and drive
the real page end-to-end.
"""

from pathlib import Path

import arviz as az
import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.approval import (
    ModelApproval,
    create_policy_backed_model_approval,
)
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
    outcome_catalogue_fingerprint_payload,
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.validation_policy import (
    ThresholdPolicy,
    ValidationEvidenceContext,
    ValidationGate,
    ValidationResult,
    evaluate_approval_readiness,
)
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "07_Results_Curve_Bank.py"


def _meta() -> FHModelMeta:
    outcome_def = OutcomeDefinition(
        outcome_id="New",
        product=FAMILY_HISTORY,
        segment="New",
        metric="GSA",
        metric_key=METRIC_KEY_FH_GSA,
        source_column="fh_new_gsa",
        unit="GSA",
        aggregation_type="count",
        event_definition="A new subscriber",
        date_basis="event_date",
        cohort_or_attribution_basis="signup_cohort",
        completeness_or_maturity_policy="Mature after 12 weeks",
        exclusions="Excludes internal test accounts",
        reconciliation_source="Finance report",
        business_owner="Analytics",
        definition_version="1.0",
    )
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=["New"],
        channels=["TV_Brand"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="New",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
        outcome_catalogue_at_fit=[outcome_def],
    )


def _trace(meta: FHModelMeta, n_fourier: int = 6, chains: int = 2, draws: int = 10):
    rng = np.random.default_rng(0)
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
    coords = {
        "channel": meta.channels,
        "outcome": meta.outcome_ids,
        "market": meta.markets,
        "fourier": list(range(n_fourier)),
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "promo_coef": ["outcome"],
        "alpha": ["outcome"],
        "beta": ["outcome", "channel"],
        "market_offset": ["market", "outcome"],
        "gamma_fourier": ["fourier", "outcome"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


def _seed_consistent_session_state(at: AppTest) -> None:
    """A real fitted model whose legacy approval's identity fingerprints
    match exactly how the page itself recomputes "current_identity"."""
    meta = _meta()
    trace = _trace(meta)
    transformed_data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=16, freq="W"),
            "market": ["UK"] * 16,
            "TV_Brand": np.linspace(100.0, 250.0, 16),
            "fh_new_gsa": np.linspace(10.0, 16.0, 16),
        }
    )
    model_spec_dict = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=["TV_Brand"],
    ).to_dict()
    prior_config = {"decay_mu": 0.5}
    dna_lag_weeks = 4
    spec = ModelSpec.from_dict(model_spec_dict)
    frame = prepare_fh_modeling_frame(transformed_data, spec)
    posterior_params = extract_posterior_params(trace, meta)

    model_run_id = "run-curve-bank-apptest"
    approval = ModelApproval(
        approved_by="Jane Analyst",
        model_run_id=model_run_id,
        data_fingerprint=fingerprint_dataframe(frame["df"]),
        model_spec_fingerprint=fingerprint_model_spec(
            model_spec_dict,
            prior_config,
            dna_lag_weeks,
            model_type="shared",
            pipeline_steps=[],
            market_spec_config=None,
            direct_dna_outcome_ids=meta.direct_dna_outcome_ids,
            outcome_catalogue=outcome_catalogue_fingerprint_payload(
                meta.outcome_catalogue_at_fit
            ),
            funnel_links=None,
            media_outcome_pathways=pathway_catalogue_fingerprint_payload(
                meta.pathway_catalogue_at_fit
            ),
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
    at.session_state["outcome_definitions"] = [
        o.to_dict() for o in meta.outcome_catalogue_at_fit
    ]
    at.session_state["activity_definitions"] = []


def _policy_backed_governance(model_run_id, data_fp, spec_fp, posterior_fp):
    """Mirrors test_scenario_planner_apptest.py's helper of the same name:
    a matching (policy, readiness, approval) triple for the given identity."""
    identity = ModelIdentity(
        model_run_id=model_run_id,
        data_fingerprint=data_fp,
        model_spec_fingerprint=spec_fp,
        posterior_fingerprint=posterior_fp,
    )
    gate = ValidationGate(
        name="divergences",
        description="No divergences",
        evaluator_id="divergences",
        expected_state=False,
    )
    policy = ThresholdPolicy(
        policy_id="curve-bank-policy",
        version="1.0",
        scope="all_models",
        owner="Test",
        gates=[gate],
    )
    result = ValidationResult(
        gate_name="divergences",
        status="pass",
        value=0,
        message="No divergences",
        model_run_id=model_run_id,
        data_fingerprint=data_fp,
        model_spec_fingerprint=spec_fp,
        posterior_fingerprint=posterior_fp,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_fingerprint=policy.fingerprint(),
        model_identity_fingerprint=identity.fingerprint(),
        gate_fingerprint=gate.fingerprint(),
        diagnostic_artefact_fingerprint="diag-fp-curve-bank",
        artefact_id="diag-curve-bank",
    )
    ctx = ValidationEvidenceContext(
        model_identity=identity,
        policy=policy,
        diagnostic_artefact_id="diag-curve-bank",
        diagnostic_artefact_fingerprint="diag-fp-curve-bank",
        model_type="shared",
        intended_use="model_approval",
    )
    readiness = evaluate_approval_readiness(
        [result],
        policy,
        identity,
        diagnostic_artefact_id="diag-curve-bank",
        diagnostic_artefact_fingerprint="diag-fp-curve-bank",
        evidence_context=ctx,
    )
    approval = create_policy_backed_model_approval(
        approved_by="Jane Analyst",
        readiness=readiness,
        current_policy=policy,
        model_run_id=model_run_id,
        data_fingerprint=data_fp,
        model_spec_fingerprint=spec_fp,
        posterior_fingerprint=posterior_fp,
    )
    return policy, readiness, approval


def _seed_official_governance_state(at: AppTest) -> None:
    _seed_consistent_session_state(at)
    legacy_approval_dict = at.session_state["model_approval"]
    policy, readiness, approval = _policy_backed_governance(
        legacy_approval_dict["model_run_id"],
        legacy_approval_dict["data_fingerprint"],
        legacy_approval_dict["model_spec_fingerprint"],
        legacy_approval_dict["posterior_fingerprint"],
    )
    at.session_state["model_approval"] = approval.to_dict()
    at.session_state["validation_policy"] = policy.to_dict()
    at.session_state["approval_readiness"] = readiness.to_dict()


def test_official_approval_with_matching_policy_and_readiness_allows_save():
    """A policy-backed approval whose bound readiness/policy fingerprints
    all still match the current model must pass the curve-bank gate (not
    be flagged as 'no longer matches')."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "will record this approval on every curve saved" in (c.value or "")
        for c in at.caption
    )
    assert not any(
        "no longer matches the current fitted model" in (i.value or "") for i in at.info
    )


def test_missing_readiness_blocks_save_instead_of_crashing():
    """A policy-backed approval with no matching approval_readiness in
    session state must block curve-bank saving gracefully (require_matching_
    approval raises ValidationPolicyBlockedError, caught by the page's own
    gate) rather than let the page proceed as if the approval were valid,
    and rather than crash later inside cb.make_entries()."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.session_state["approval_readiness"] = None
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "no longer matches the current fitted model, policy, or readiness evidence"
        in (i.value or "")
        for i in at.info
    )
    # The save button/run-label input must not render past the blocked gate.
    assert not any(ti.label == "Run label *" for ti in at.text_input)


def test_policy_mismatch_blocks_save_instead_of_crashing():
    """A policy-backed approval whose bound readiness was evaluated against
    a different policy than the one currently configured must block saving
    - a policy edit since approval must not silently continue to authorise
    curve-bank writes."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    mismatched_policy = dict(at.session_state["validation_policy"])
    mismatched_policy["version"] = "2.0"
    at.session_state["validation_policy"] = mismatched_policy
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "no longer matches the current fitted model, policy, or readiness evidence"
        in (i.value or "")
        for i in at.info
    )


def test_page_no_longer_uses_bare_matches_current_model_for_display_gate():
    """PR 82F: the page's own approval-validity gate must go through
    require_matching_approval (which also verifies policy/readiness
    binding), not a direct matches_current_model() call - the exact
    weaker-check-replaced-by-stronger-check pattern PR 82B applied to
    06_Diagnostics.py."""
    source = "\n".join(
        line
        for line in PAGE.read_text(encoding="utf-8").split("\n")
        if not line.strip().startswith("#")
    )
    assert "require_matching_approval(" in source
    assert ".matches_current_model(" not in source


def test_both_make_entries_calls_thread_readiness_and_policy():
    """PR 82F: cb.make_entries() already enforces require_matching_approval
    internally and accepts approval_readiness/current_policy - both call
    sites (market_specific and shared) must actually supply them, or a
    policy-backed approval raises an uncaught ValidationPolicyBlockedError
    when the analyst clicks Save."""
    source = "\n".join(
        line
        for line in PAGE.read_text(encoding="utf-8").split("\n")
        if not line.strip().startswith("#")
    )
    assert source.count("cb.make_entries(") == 2
    # 3 = the display-gate require_matching_approval() call + both
    # cb.make_entries() call sites.
    assert source.count("approval_readiness=current_readiness") == 3
    assert source.count("current_policy=current_policy") == 3
    assert "ValidationPolicyBlockedError" in source
