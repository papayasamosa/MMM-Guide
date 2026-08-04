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
from ancestry_mmm.core.media_costs import CostMappingRegistry, IdentitySpendMapping
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    fingerprint_outcome_definition,
)
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
from ancestry_mmm.core.validation_policy import (
    ApprovalReadiness,
    ThresholdPolicy,
    ValidationEvidenceContext,
    ValidationGate,
    ValidationResult,
    evaluate_approval_readiness,
)
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "08_Scenario_Planner.py"


def _meta(outcome_catalogue) -> FHModelMeta:
    outcome_ids = [o.outcome_id for o in outcome_catalogue]
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=outcome_ids,
        channels=["TV_Brand"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id=outcome_ids[0],
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
        outcome_catalogue_at_fit=outcome_catalogue,
        # eligible_outcome_ids() (core.outcomes) reads this map, not the
        # OutcomeDefinition's own include_in_value/include_in_optimisation
        # fields directly - without it every outcome falls back to the
        # "primary" role default (eligible for everything).
        outcome_id_to_eligibility={
            o.outcome_id: outcome_eligibility(o) for o in outcome_catalogue
        },
    )


def _trace(
    meta: FHModelMeta,
    n_fourier: int = 6,
    chains: int = 2,
    draws: int = 10,
    seed: int = 0,
) -> az.InferenceData:
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


def _seed_consistent_session_state(
    at: AppTest,
    *,
    value_currency: str,
    non_target_outcome_currency: str | None = None,
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
        value_weight=5.0,
        value_currency=value_currency,
        include_in_value=True,
        include_in_optimisation=True,
    )
    outcome_defs = [outcome_def]
    segment_outcomes = {"New": "fh_new_gsa"}
    source_columns = {"fh_new_gsa": np.linspace(10.0, 16.0, 16)}
    if non_target_outcome_currency is not None:
        non_target_def = OutcomeDefinition(
            outcome_id="Winback",
            product=FAMILY_HISTORY,
            segment="Winback",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="fh_winback_gsa",
            unit="GSA",
            aggregation_type="count",
            event_definition="A winback subscriber",
            date_basis="event_date",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            exclusions="Excludes internal test accounts",
            reconciliation_source="Finance report",
            business_owner="Analytics",
            definition_version="1.0",
            value_weight=3.0,
            value_currency=non_target_outcome_currency,
            include_in_value=False,
            include_in_optimisation=False,
        )
        outcome_defs.append(non_target_def)
        segment_outcomes["Winback"] = "fh_winback_gsa"
        source_columns["fh_winback_gsa"] = np.linspace(4.0, 7.0, 16)

    meta = _meta(outcome_defs)
    trace = _trace(meta)
    transformed_data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=16, freq="W"),
            "market": ["UK"] * 16,
            "TV_Brand": np.linspace(100.0, 250.0, 16),
            **source_columns,
        }
    )
    model_spec_dict = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes=segment_outcomes,
        channels=["TV_Brand"],
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
    at.session_state["outcome_definitions"] = [o.to_dict() for o in outcome_defs]
    outcome_approvals = [
        OutcomeApproval(
            approval_id=f"apr-{o.outcome_id}",
            outcome_id=o.outcome_id,
            definition_fingerprint=fingerprint_outcome_definition(o),
            status="approved",
            allowed_uses=("planning", "optimisation"),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
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
        at,
        value_currency="GBP",
        non_target_outcome_currency="USD",
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


# ---------------------------------------------------------------------------
# PR 82C: ScenarioService routing, canonical state keys, governance-proof
# invalidation
# ---------------------------------------------------------------------------


def _policy_backed_governance(
    model_run_id: str, data_fp: str, spec_fp: str, posterior_fp: str
) -> tuple[ThresholdPolicy, ApprovalReadiness, ModelApproval]:
    """Build a matching (policy, readiness, approval) triple for the given
    model identity - the readiness is hand-built via
    evaluate_approval_readiness with a single trivially-passing gate
    (mirroring test_validation_policy.py's pattern), so this needs no real
    diagnostics computation."""
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
        policy_id="scenario-planner-policy",
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
        diagnostic_artefact_fingerprint="diag-fp-scenario-planner",
        artefact_id="diag-scenario-planner",
    )
    ctx = ValidationEvidenceContext(
        model_identity=identity,
        policy=policy,
        diagnostic_artefact_id="diag-scenario-planner",
        diagnostic_artefact_fingerprint="diag-fp-scenario-planner",
        model_type="shared",
        intended_use="model_approval",
    )
    readiness = evaluate_approval_readiness(
        [result],
        policy,
        identity,
        diagnostic_artefact_id="diag-scenario-planner",
        diagnostic_artefact_fingerprint="diag-fp-scenario-planner",
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


def _seed_official_governance_state(
    at: AppTest, *, value_currency: str = "GBP"
) -> None:
    """Seed the same consistent fitted model as _seed_consistent_session_state,
    but replace the legacy (policy-unbound) approval with a real policy-backed
    triple: model_approval, validation_policy and approval_readiness all bound
    to the exact same model identity and to each other."""
    _seed_consistent_session_state(at, value_currency=value_currency)
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


def test_official_manual_scenario_succeeds_with_matching_policy_readiness_approval():
    """A policy-backed approval whose bound readiness/policy fingerprints
    all still match the current model must pass the approval gate and let
    the manual tab evaluate normally through ScenarioService."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    # Reaching the manual tab's predicted-outcomes table means the approval
    # gate did not st.stop() the page.
    assert not any(
        "no longer matches the current fitted model" in (w.value or "")
        for w in at.warning
    )
    assert any(
        "Predicted outcomes for the spend plan" in (m.value or "") for m in at.markdown
    )


def test_official_scenario_blocked_with_missing_readiness():
    """A policy-backed approval with no matching approval_readiness in
    session state must block the whole page (require_matching_approval
    raises "no readiness assessment was provided") rather than let planning
    proceed ungoverned."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.session_state["approval_readiness"] = None
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "no longer matches the current fitted model, policy, or readiness evidence"
        in (w.value or "")
        for w in at.warning
    )
    # The page st.stop()s at the gate - the plan-setup UI further down must
    # never render.
    assert not any(r.label == "Market *" for r in at.selectbox)


def test_official_scenario_blocked_with_policy_mismatch():
    """A policy-backed approval whose bound readiness was evaluated against
    a different policy than the one currently configured must block the
    whole page - a policy edit since approval must not silently continue to
    authorise planning."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    mismatched_policy = dict(at.session_state["validation_policy"])
    mismatched_policy["version"] = "2.0"  # same policy_id, different fingerprint
    at.session_state["validation_policy"] = mismatched_policy
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "no longer matches the current fitted model, policy, or readiness evidence"
        in (w.value or "")
        for w in at.warning
    )
    assert not any(r.label == "Market *" for r in at.selectbox)


def test_malformed_policy_does_not_crash_scenario_planner_page():
    """PR 88A: a validation_policy dict whose 'gates' value isn't a list
    (e.g. corrupted session state) previously raised an uncaught TypeError
    out of ThresholdPolicy.from_dict's own ValidationGate.from_dict() call
    (iterating over a string's characters) - this page's inline handler
    only caught ValueError. Must now be reported and treated as no-policy,
    never crash the page."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.session_state["validation_policy"] = {
        "policy_id": "bad",
        "version": "1.0",
        "scope": "all_models",
        "owner": "Test",
        "approval_date": "2026-01-01T00:00:00+00:00",
        "gates": "not-a-list",
    }
    at.run()
    assert not at.exception, f"page raised: {at.exception}"


def test_malformed_readiness_does_not_crash_scenario_planner_page():
    """A stored approval_readiness dict that fails to deserialize (here,
    'gate_results' isn't a list of gate-result dicts) must not crash the
    page. This page's isinstance(dict) guard alone is not enough - the
    value here passes isinstance(dict) but still fails to deserialize."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.session_state["approval_readiness"] = {"gate_results": "not-a-list"}
    at.run()
    assert not at.exception, f"page raised: {at.exception}"


def test_page_reads_no_deprecated_state_keys():
    """PR 82C: validation_policy / approval_readiness are the sole policy/
    readiness state keys - the deprecated validation_readiness /
    (bare) current_policy state-key reads must be fully gone."""
    source = "\n".join(
        line
        for line in PAGE.read_text(encoding="utf-8").split("\n")
        if not line.strip().startswith("#")
    )
    assert 'get_state("validation_readiness")' not in source
    assert 'get_state("current_policy")' not in source


def test_page_never_calls_core_planning_functions_directly():
    """PR 82C: manual evaluation and both optimiser modes are routed through
    ScenarioService - the page must not call evaluate_manual_scenario() or
    optimize_scenario() directly any more."""
    source = "\n".join(
        line
        for line in PAGE.read_text(encoding="utf-8").split("\n")
        if not line.strip().startswith("#")
    )
    assert "evaluate_manual_scenario(" not in source
    assert "optimize_scenario(" not in source


def test_page_resolves_policy_and_readiness_exactly_once():
    """PR 82C: one governance proof (current_policy/current_readiness) is
    resolved once and reused by the approval gate, manual evaluation, both
    optimiser modes, and posterior uncertainty - never re-derived
    independently for different calls in the same rerun.

    PR 88A: resolution now goes through the shared fail-closed loaders
    (load_threshold_policy/load_approval_readiness) rather than calling
    ThresholdPolicy.from_dict()/ApprovalReadiness.from_dict() directly - the
    "exactly once" invariant this test protects is unchanged, just via the
    new call site."""
    source = PAGE.read_text(encoding="utf-8")
    assert source.count("load_threshold_policy(") == 1
    assert source.count("load_approval_readiness(") == 1
    assert "ThresholdPolicy.from_dict(" not in source
    assert "ApprovalReadiness.from_dict(" not in source
    # The same scenario_governance_kwargs dict (built from current_policy/
    # current_readiness) must be spread into every planning/uncertainty call.
    assert source.count("**scenario_governance_kwargs") == 4


def test_exploratory_result_invalidated_when_switched_back_to_official():
    """Exploratory-mode results must never silently be displayed/saved under
    an official label once governance mode changes - a cached optimisation
    result computed in exploratory mode is invalidated the moment the radio
    is switched to official, exercising the pre-existing governance_mode
    mismatch guard through the now-service-routed optimisation path."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()
    governance_radio = next(r for r in at.radio if r.label == "Governance mode")
    governance_radio.set_value("exploratory").run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Exploratory mode" in (w.value or "") for w in at.warning), (
        "exploratory mode must be visibly labelled"
    )

    run_button = next(b for b in at.button if b.label == "Run unconstrained benchmark")
    run_button.click().run()
    assert not at.exception, f"page raised after exploratory run: {at.exception}"
    assert at.session_state["unconstrained_result"] is not None
    assert at.session_state["unconstrained_result"]["governance_mode"] == "exploratory"

    # Switch back to official without re-running - the cached exploratory
    # result must be invalidated, never silently redisplayed as official.
    governance_radio.set_value("official").run()
    assert not at.exception, f"page raised: {at.exception}"
    assert at.session_state["unconstrained_result"] is None
    assert any(
        "Governance mode changed since this result was computed" in (i.value or "")
        for i in at.info
    )


def test_saved_scenarios_excludes_and_warns_about_a_stale_cost_mapping():
    """Corrective PR C9: a scenario saved under a since-edited cost mapping
    predicts totals that no longer reflect the governed mapping in effect
    now - comparing it alongside current scenarios would be indistinguishable
    from a current comparison. It must be excluded from the comparison table
    and named in a warning instead."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")

    current_registry = CostMappingRegistry(
        [
            IdentitySpendMapping(
                mapping_id="UK-TV_Brand-cost",
                market="UK",
                channel="TV_Brand",
                currency="GBP",
                cost_context_id="default",
                approval_status="approved",
                approved_by="reviewer",
                approved_at="2026-01-01",
                owner="Analytics",
                approval_note="approved for test",
                last_reviewed_at="2026-01-01",
            )
        ]
    )
    at.session_state["media_cost_mappings"] = current_registry.to_dict()

    predicted = pd.DataFrame({"month": ["2026-01"], "predicted_outcome": [100.0]})
    at.session_state["scenarios"] = [
        {
            "name": "Current Scenario",
            "market": "UK",
            "spend_plan": {"TV_Brand": {"2026-01": 100.0}},
            "predicted": predicted,
            "cost_mapping_fingerprint": current_registry.fingerprint(),
        },
        {
            "name": "Stale Scenario",
            "market": "UK",
            "spend_plan": {"TV_Brand": {"2026-01": 100.0}},
            "predicted": predicted,
            "cost_mapping_fingerprint": "fingerprint-of-a-cost-mapping-that-no-longer-exists",
        },
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    assert any("Stale Scenario" in (w.value or "") for w in at.warning), [
        w.value for w in at.warning
    ]
    dataframe_texts = [str(df.value) for df in at.dataframe]
    assert any("Current Scenario" in text for text in dataframe_texts)
    assert not any("Stale Scenario" in text for text in dataframe_texts)


def test_saved_scenarios_without_a_cost_mapping_dependency_are_never_flagged_stale():
    """A scenario that never depended on a cost mapping (cost_mapping_
    fingerprint never set) has nothing to go stale - it must still appear in
    the comparison, never excluded or warned about."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.session_state["media_cost_mappings"] = CostMappingRegistry().to_dict()

    predicted = pd.DataFrame({"month": ["2026-01"], "predicted_outcome": [100.0]})
    at.session_state["scenarios"] = [
        {
            "name": "No Cost Mapping Scenario",
            "market": "UK",
            "spend_plan": {"TV_Brand": {"2026-01": 100.0}},
            "predicted": predicted,
            "cost_mapping_fingerprint": None,
        },
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    assert not any("No Cost Mapping Scenario" in (w.value or "") for w in at.warning)
    dataframe_texts = [str(df.value) for df in at.dataframe]
    assert any("No Cost Mapping Scenario" in text for text in dataframe_texts)


def test_normal_saved_scenario_with_only_a_nested_governance_dependency_is_flagged_stale():
    """Corrective PR E2.1 (PR #111 review): a normal scenario save from
    this page passes governance_dependencies=gov_deps to scenario_to_dict
    without also passing the top-level cost_mapping_fingerprint kwarg, so
    the top-level field is None even though
    governance_dependencies.cost_mapping_fingerprint carries the real
    dependency - exactly reproduced here rather than via the legacy flat
    field the other two tests above use. It must still be excluded from
    the comparison and named in the warning once the cost mapping changes,
    not silently treated as dependency-free."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")

    current_registry = CostMappingRegistry(
        [
            IdentitySpendMapping(
                mapping_id="UK-TV_Brand-cost",
                market="UK",
                channel="TV_Brand",
                currency="GBP",
                cost_context_id="default",
                approval_status="approved",
                approved_by="reviewer",
                approved_at="2026-01-01",
                owner="Analytics",
                approval_note="approved for test",
                last_reviewed_at="2026-01-01",
            )
        ]
    )
    at.session_state["media_cost_mappings"] = current_registry.to_dict()

    predicted = pd.DataFrame({"month": ["2026-01"], "predicted_outcome": [100.0]})
    at.session_state["scenarios"] = [
        {
            "name": "Current Normal Save",
            "market": "UK",
            "spend_plan": {"TV_Brand": {"2026-01": 100.0}},
            "predicted": predicted,
            "cost_mapping_fingerprint": None,
            "governance_dependencies": {
                "cost_mapping_fingerprint": current_registry.fingerprint()
            },
        },
        {
            "name": "Stale Normal Save",
            "market": "UK",
            "spend_plan": {"TV_Brand": {"2026-01": 100.0}},
            "predicted": predicted,
            "cost_mapping_fingerprint": None,
            "governance_dependencies": {
                "cost_mapping_fingerprint": "fingerprint-of-a-cost-mapping-that-no-longer-exists"
            },
        },
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    assert any("Stale Normal Save" in (w.value or "") for w in at.warning), [
        w.value for w in at.warning
    ]
    dataframe_texts = [str(df.value) for df in at.dataframe]
    assert any("Current Normal Save" in text for text in dataframe_texts)
    assert not any("Stale Normal Save" in text for text in dataframe_texts)
