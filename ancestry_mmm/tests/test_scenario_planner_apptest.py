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
from ancestry_mmm.core.planning.value import CurrencyContext, OutcomeValueMapping
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.scenario_governance import CounterfactualPolicy
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


def test_compatible_stored_value_mapping_is_preserved_not_overwritten():
    """Fresh review finding (P2): a stored value mapping (e.g. from an
    import) that's still compatible with the current objective's target
    outcome set and currency must be preserved, including any custom
    mapping_id/source or curated values - re-deriving from the catalogue
    every rerun would silently discard governed/curated evidence the
    analyst never asked to change."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    governed_mapping = OutcomeValueMapping(
        value_by_outcome_id={"New": 99.0},
        currency_by_outcome_id={"New": "GBP"},
        mapping_id="custom-governed",
        source="manual_override",
    )
    at.session_state["value_mapping"] = governed_mapping.to_dict()
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    objective_radio = [r for r in at.radio if r.label == "Optimisation objective"]
    objective_radio[0].set_value("expected_value").run()
    assert not at.exception, f"selecting expected_value raised: {at.exception}"

    stored = at.session_state["value_mapping"]
    assert stored["mapping_id"] == "custom-governed"
    assert stored["value_by_outcome_id"]["New"] == 99.0


def test_incompatible_stored_value_mapping_is_replaced_by_fresh_derivation():
    """A stored value mapping whose target outcome set no longer matches
    the current objective (e.g. left over from a different project/
    objective) doesn't describe this objective at all - re-deriving fresh
    from the catalogue is correct here, not a preservation concern."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    stale_mapping = OutcomeValueMapping(
        value_by_outcome_id={"Other": 1.0},
        currency_by_outcome_id={"Other": "GBP"},
        mapping_id="from-a-different-project",
    )
    at.session_state["value_mapping"] = stale_mapping.to_dict()
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    objective_radio = [r for r in at.radio if r.label == "Optimisation objective"]
    objective_radio[0].set_value("expected_value").run()
    assert not at.exception, f"selecting expected_value raised: {at.exception}"

    stored = at.session_state["value_mapping"]
    assert stored["mapping_id"] == "outcome-catalogue"
    assert "New" in stored["value_by_outcome_id"]


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


def test_saving_a_manual_scenario_persists_cost_mapping_governance_dependency():
    """PR 122: drives the real "Save this scenario" button (the other tests
    in this file pre-seed `st.session_state["scenarios"]` directly rather
    than exercising the save path itself) and proves the saved scenario's
    `governance_dependencies.cost_mapping_fingerprint` matches the governed
    `CostMappingRegistry` actually used to evaluate it."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    registry = CostMappingRegistry(
        [
            IdentitySpendMapping(
                mapping_id="uk-tv-brand",
                market="UK",
                channel="TV_Brand",
                currency="GBP",
                approval_status="approved",
                approved_by="finance-owner",
                approved_at="2026-01-01",
                owner="media-finance",
                approval_note="approved for test",
                last_reviewed_at="2026-01-01",
            )
        ]
    )
    at.session_state["media_cost_mappings"] = registry.to_dict()
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    save_button = next(b for b in at.button if b.label == "Save this scenario")
    save_button.click().run()
    assert not at.exception, f"save click raised: {at.exception}"
    assert any("Saved scenario" in (s.value or "") for s in at.success)

    saved_scenarios = at.session_state["scenarios"]
    assert len(saved_scenarios) == 1
    saved = saved_scenarios[0]
    assert saved["governance_mode"] == "official"
    assert (
        saved["governance_dependencies"]["cost_mapping_fingerprint"]
        == registry.fingerprint()
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


def test_representable_imported_counterfactual_policy_round_trips_unchanged():
    """PR 125A: a stored project-level policy whose demand_capture_rule is
    already one of this page's two radio options round-trips through the
    page unchanged, including fields the widget never edits."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    imported_policy = CounterfactualPolicy(
        demand_capture_rule="zero", fixed_activity_rule="explicit"
    )
    at.session_state["counterfactual_policy"] = imported_policy.to_dict()
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    stored = at.session_state["counterfactual_policy"]
    assert stored["demand_capture_rule"] == "zero"
    # fixed_activity_rule isn't exposed by any widget on this page - must
    # survive the rerun exactly as imported, not reset to the dataclass
    # default ("hold_plan").
    assert stored["fixed_activity_rule"] == "explicit"


def test_unsupported_imported_demand_capture_rule_is_preserved_not_narrowed():
    """Corrective review finding (P1): CounterfactualPolicy's own default
    demand_capture_rule is "require_explicit" - a value this page's radio
    (hold_plan / zero) cannot represent. Previously, merely loading this
    page with such a policy already in session state (e.g. just imported)
    silently narrowed it to "hold_plan" on first render, staling every
    official scenario that depended on the real policy - with no explicit
    choice behind the change. The stored policy must survive untouched
    until the analyst explicitly clicks the replace button."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    unsupported_policy = (
        CounterfactualPolicy()
    )  # demand_capture_rule="require_explicit"
    at.session_state["counterfactual_policy"] = unsupported_policy.to_dict()
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    stored = at.session_state["counterfactual_policy"]
    assert stored["demand_capture_rule"] == "require_explicit"
    assert stored == unsupported_policy.to_dict()
    warnings = " ".join(w.value for w in at.warning)
    assert "does not offer" in warnings


def test_stored_currency_context_extra_fields_survive_a_rerun():
    """Corrective review finding (P1): market_reporting_currency/
    value_currency are genuinely re-derived from the current objective's
    target outcomes every rerun, but group_reporting_currency,
    model_currency, and any governed FX rate-set identity are never derived
    by this page at all - only ever restored from an import. Previously,
    merely rendering this page with such a context already stored replaced
    it with a fresh minimal CurrencyContext(market_reporting_currency=...,
    value_currency=...), discarding those fields the moment the page
    loaded, with no analyst choice behind it."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    imported_context = CurrencyContext(
        market_reporting_currency="GBP",
        value_currency="GBP",
        group_reporting_currency="USD",
        model_currency="GBP",
        historical_fx_rate_set_id="fx-set-1",
        historical_fx_rate_set_fingerprint="fx-set-1-fp",
    )
    at.session_state["currency_context"] = imported_context.to_dict()
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    stored = at.session_state["currency_context"]
    assert stored["market_reporting_currency"] == "GBP"
    assert stored["group_reporting_currency"] == "USD"
    assert stored["historical_fx_rate_set_id"] == "fx-set-1"
    assert stored["historical_fx_rate_set_fingerprint"] == "fx-set-1-fp"


def test_malformed_stored_counterfactual_policy_does_not_crash_page():
    """Corrective review finding (P2): config/counterfactual_policy.json
    round-trips through import_project() as whatever JSON value it actually
    contains - a structurally malformed file (e.g. a JSON array, not an
    object) previously crashed this page's `.get()` call with an
    AttributeError instead of failing closed with a warning."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.session_state["counterfactual_policy"] = ["not", "a", "mapping"]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    warnings = " ".join(w.value for w in at.warning)
    assert "malformed" in warnings


def test_malformed_stored_currency_context_does_not_crash_page():
    """Same fail-closed contract as the counterfactual-policy case above,
    for config/currency_context.json."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.session_state["currency_context"] = "not-a-mapping"
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    warnings = " ".join(w.value for w in at.warning)
    assert "malformed" in warnings


def test_structurally_valid_but_invalid_counterfactual_policy_is_preserved_not_narrowed():
    """Corrective review finding (P2): a stored policy can be a
    structurally valid mapping with a representable demand_capture_rule
    while still being an invalid CounterfactualPolicy overall (e.g. an
    unrecognised fixed_activity_rule) - checking demand_capture_rule
    membership alone let this reach an unguarded
    CounterfactualPolicy.from_dict() call and crash the page. The whole
    dict must be validated, not just the one field this page's widget
    edits, and the invalid policy must be preserved untouched (same
    explicit-replace contract as the unsupported-value case)."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    invalid_policy_dict = {
        "demand_capture_rule": "hold_plan",
        "fixed_activity_rule": "not-a-real-rule",
    }
    at.session_state["counterfactual_policy"] = invalid_policy_dict
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert at.session_state["counterfactual_policy"] == invalid_policy_dict
    warnings = " ".join(w.value for w in at.warning)
    assert "is invalid and cannot be used" in warnings
    # Fresh review finding: preserving the invalid dict isn't enough on its
    # own - the planning workflow itself must stop (st.stop()) rather than
    # silently continue to evaluate/save/optimise against a substitute
    # policy the analyst never chose. "Governance mode" is rendered well
    # after the counterfactual-policy block; its absence proves the script
    # actually halted there rather than merely warning and carrying on.
    errors = " ".join(e.value for e in at.error)
    assert "Planning is blocked" in errors
    assert "Governance mode" not in [r.label for r in at.radio]


def test_invalid_currency_context_blocks_instead_of_replacing_stored_state():
    """Corrective review finding (P2): the earlier fix for preserving a
    valid stored currency context's extra fields still fell back, on
    validation failure, to constructing-and-persisting a fresh minimal
    CurrencyContext - silently discarding the stored context's other
    fields via a different path than the one already fixed. A malformed
    stored context must block (preserved untouched in session state), not
    be quietly replaced with a stripped-down one - and, per a further
    review finding, must actually stop the planning workflow (st.stop()),
    not just decline to persist the fallback while still evaluating,
    saving, and optimising against it."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    invalid_context_dict = {
        "market_reporting_currency": "GBP",
        "value_currency": "GBP",
        "group_reporting_currency": "not-iso",
    }
    at.session_state["currency_context"] = invalid_context_dict
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert at.session_state["currency_context"] == invalid_context_dict
    errors = " ".join(e.value for e in at.error)
    assert "Planning is blocked" in errors
    assert "is invalid and cannot be combined" in errors
    # "Saved scenarios" is the last section on the page - its absence proves
    # the script actually halted rather than merely erroring and continuing.
    assert "Saved scenarios" not in " ".join(m.value for m in at.markdown)


def test_stale_cached_constrained_result_invalidated_when_counterfactual_policy_changes():
    """Corrective review finding (P2): a cached optimiser result was only
    ever invalidated on a governance_mode change - changing the
    counterfactual-policy radio after running an optimisation left the
    stale result (still carrying the OLD policy's fingerprint) fully
    displayable and saveable under the project's now-different policy."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.session_state["counterfactual_policy"] = CounterfactualPolicy(
        demand_capture_rule="hold_plan"
    ).to_dict()
    stale_fingerprint = CounterfactualPolicy(demand_capture_rule="zero").fingerprint()
    at.session_state["constrained_result"] = {
        "governance_mode": "official",
        "counterfactual_policy_fingerprint": stale_fingerprint,
    }
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert at.session_state["constrained_result"] is None
    infos = " ".join(i.value for i in at.info)
    assert "counterfactual policy changed" in infos


def test_saved_scenario_excluded_when_counterfactual_policy_has_changed():
    """Corrective review finding (P2): the saved-scenario staleness
    comparison only ever checked cost mappings - a scenario saved under a
    since-changed counterfactual policy predicted totals under a
    demand-capture rule the project no longer uses, but was never excluded
    or flagged, indistinguishable from a genuinely current scenario."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.session_state["counterfactual_policy"] = CounterfactualPolicy(
        demand_capture_rule="hold_plan"
    ).to_dict()
    stale_fingerprint = CounterfactualPolicy(demand_capture_rule="zero").fingerprint()
    at.session_state["scenarios"] = [
        {
            "name": "stale-scenario",
            "governance_dependencies": {
                "counterfactual_policy_fingerprint": stale_fingerprint
            },
        }
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    warnings = " ".join(w.value for w in at.warning)
    assert "counterfactual policy has since changed" in warnings
    assert "stale-scenario" in warnings


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
    new call site.

    WP5 (`Media-Mix-Lab: Coding LLM Next Steps Post PR262`): the sequential
    manual evaluation call site (evaluate_manual_sequential) is a fifth
    consumer of the same scenario_governance_kwargs dict."""
    source = PAGE.read_text(encoding="utf-8")
    assert source.count("load_threshold_policy(") == 1
    assert source.count("load_approval_readiness(") == 1
    assert "ThresholdPolicy.from_dict(" not in source
    assert "ApprovalReadiness.from_dict(" not in source
    # The same scenario_governance_kwargs dict (built from current_policy/
    # current_readiness) must be spread into every planning/uncertainty call.
    assert source.count("**scenario_governance_kwargs") == 5


def test_exploratory_result_invalidated_when_switched_back_to_official():
    """Exploratory-mode results must never silently be displayed/saved under
    an official label once governance mode changes - a cached optimisation
    result computed in exploratory mode is invalidated the moment the radio
    is switched to official, exercising the pre-existing governance_mode
    mismatch guard through the now-service-routed optimisation path."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()
    governance_radio = next(r for r in at.radio if r.label == "Planning use")
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
        "Planning use changed since this result was computed" in (i.value or "")
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


# ---------------------------------------------------------------------------
# Phase 6 UI overhaul: allocation-desk visual separation (SectionCard groups
# for the editable decision grid vs. calculated outputs vs. constraints vs.
# assumptions, plus the prominent steady-state-approximation label). Purely
# presentational - no scenario/optimisation logic under test here beyond
# "the page still renders and the plan/prediction flow still works", which
# the fixture's approval-matching identity already exercises end-to-end.
# ---------------------------------------------------------------------------


def test_opening_banner_does_not_claim_steady_state_only():
    """UI-WP2: the page-level opening banner must describe the planner
    generically - it must not claim (as it once did) that every scenario
    uses steady-state monthly evaluation, since sequential weekly is a fully
    implemented, selectable method for the manual tab."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    info_texts = [i.value or "" for i in at.info]
    assert not any(
        "Steady-state monthly approximation.** Each month is evaluated as a "
        "steady monthly state" in text
        for text in info_texts
    )
    assert any("Two evaluation methods are available" in text for text in info_texts)


def test_evaluation_method_selection_shows_method_specific_detail():
    """UI-WP2: once an evaluation method is chosen, its own characteristics
    must be shown inline (not only in a hover tooltip), and switching methods
    must switch the visible detail - never leaving stale steady-state detail
    visible while sequential weekly is selected, or vice versa."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    info_texts = [i.value or "" for i in at.info]
    assert any(
        "Steady-state monthly approximation** is selected" in text
        for text in info_texts
    )
    steady_detail = next(
        text
        for text in info_texts
        if "Steady-state monthly approximation** is selected" in text
    )
    assert "does not reproduce starting carryover" in steady_detail
    assert "Sequential weekly** is selected" not in " ".join(info_texts)

    method_radio = next(
        r for r in at.radio if r.label == "Manual plan evaluation method"
    )
    method_radio.set_value("sequential_weekly").run()
    assert not at.exception, f"selecting sequential_weekly raised: {at.exception}"

    info_texts = [i.value or "" for i in at.info]
    assert not any(
        "Steady-state monthly approximation** is selected" in text
        for text in info_texts
    )
    sequential_detail = next(
        text for text in info_texts if "Sequential weekly** is selected" in text
    )
    assert "week-by-week media carryover" in sequential_detail
    assert "terminal carryover" in sequential_detail
    assert "steady-state-monthly only" in sequential_detail


def test_optimiser_tabs_state_their_evaluation_method():
    """UI-WP2: the constrained and unconstrained optimiser tabs must state
    they use steady-state monthly evaluation, since neither supports
    sequential weekly."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    caption_texts = [c.value or "" for c in at.caption]
    matching = [
        text
        for text in caption_texts
        if "Evaluation method" in text and "steady-state monthly" in text
    ]
    assert len(matching) >= 2, caption_texts


def test_spend_plan_grid_is_labelled_as_the_editable_decision():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Spend plan - editable decision" in (m.value or "") for m in at.markdown)
    assert any("Calculated output (read-only)" in (m.value or "") for m in at.markdown)


def test_constraints_are_visually_distinct_from_assumptions():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Planning assumptions & use" in (m.value or "") for m in at.markdown)
    assert any(
        "Constraints (distinct from the assumptions above)" in (m.value or "")
        for m in at.markdown
    )
    assert any(r.label == "Planning use" for r in at.radio)
    assert any(
        r.label
        == "How should demand-capture activity behave in the comparison baseline?"
        for r in at.radio
    )
    assert any("Economics by month" in (m.value or "") for m in at.markdown)
    assert all(
        "outcome_id" not in getattr(dataframe.value, "columns", [])
        for dataframe in at.dataframe
    )


def test_saved_scenarios_are_labelled_as_persisted_state():
    """The section title itself stays exactly "Saved scenarios" (the real,
    already-running browser-lifecycle journey
    (test_official_lifecycle_browser.py) asserts on this exact heading text)
    - the "persisted state" framing that distinguishes it from the proposed-
    but-not-yet-saved plans above lives in the section's caption instead."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Saved scenarios" in (m.value or "") for m in at.markdown)
    assert not any(
        "Saved scenarios - persisted state" in (m.value or "") for m in at.markdown
    )
    assert any("Persisted state:" in (c.value or "") for c in at.caption)


# ---------------------------------------------------------------------------
# WP5 (`Media-Mix-Lab: Coding LLM Next Steps Post PR262`): sequential-weekly
# manual plan evaluation method on the "Edited plan and calculated result"
# tab.
# ---------------------------------------------------------------------------


# WP0 (`Media-Mix-Lab: Coding LLM Next Steps After PR #267`): the sequential
# tab must not calculate or show any result until the analyst has explicitly
# acknowledged every assumption this method would otherwise apply
# automatically (a plan-start-month reassignment, an exploratory hold-last-
# observed switch for fitted exogenous controls, and a zero-promotion
# default) - see `_render_sequential_manual_tab`'s acknowledgment gates.
_SEQUENTIAL_ACK_LABEL_PREFIXES = (
    "I understand my entered monthly values will be reassigned",
    "I explicitly choose to hold each exogenous control",
    "I explicitly confirm no promotion is planned",
)


def _check_sequential_acknowledgment_gates(at) -> None:
    for checkbox in at.checkbox:
        if checkbox.label and any(
            checkbox.label.startswith(prefix)
            for prefix in _SEQUENTIAL_ACK_LABEL_PREFIXES
        ):
            checkbox.check()


def test_sequential_weekly_manual_tab_blocks_until_assumptions_acknowledged():
    """Selecting 'Sequential weekly' must not calculate or render any result
    while a required assumption checkbox remains unchecked - never an
    automatic page default standing in for analyst consent."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()

    method_radio = next(
        r for r in at.radio if r.label == "Manual plan evaluation method"
    )
    method_radio.set_value("sequential_weekly").run()
    assert not at.exception, f"selecting sequential_weekly raised: {at.exception}"

    markdown_text = [m.value or "" for m in at.markdown]
    assert not any("Weekly incremental outcome" in text for text in markdown_text)
    assert any(
        "Confirm the assumption(s) above" in (info.value or "") for info in at.info
    )


def test_sequential_weekly_manual_tab_renders_without_exception():
    """Selecting 'Sequential weekly' on the manual-plan evaluation-method
    radio, then acknowledging every required assumption, must route the
    manual tab through ScenarioService.evaluate_manual_sequential and
    render its weekly/monthly incremental tables and horizon metrics,
    instead of the default steady-state monthly path - without raising."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    method_radio = next(
        r for r in at.radio if r.label == "Manual plan evaluation method"
    )
    assert method_radio.value == "steady_state_monthly"
    method_radio.set_value("sequential_weekly").run()
    assert not at.exception, f"selecting sequential_weekly raised: {at.exception}"

    _check_sequential_acknowledgment_gates(at)
    at.run()
    assert not at.exception, f"acknowledging assumptions raised: {at.exception}"

    markdown_text = [m.value or "" for m in at.markdown]
    assert any("Weekly incremental outcome" in text for text in markdown_text)
    assert any("Monthly incremental outcome" in text for text in markdown_text)
    assert any("Response horizons" in text for text in markdown_text)


def test_sequential_weekly_manual_tab_renders_terminal_carryover_section():
    """WP5 (`Media-Mix-Lab: Coding LLM Next Steps After PR #267`): the
    sequential tab must render a structurally separate terminal-carryover
    section (never merged into the plan-window tables above) once the
    required assumptions are acknowledged - terminal_future_context is
    always built regardless of whether a posterior trace is available."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()

    method_radio = next(
        r for r in at.radio if r.label == "Manual plan evaluation method"
    )
    method_radio.set_value("sequential_weekly").run()
    _check_sequential_acknowledgment_gates(at)
    at.run()
    assert not at.exception, f"acknowledging assumptions raised: {at.exception}"

    markdown_text = [m.value or "" for m in at.markdown]
    assert any("Terminal carryover" in text for text in markdown_text)
    assert any("Posterior uncertainty" in text for text in markdown_text)

    uncertainty_checkbox = next(
        (
            c
            for c in at.checkbox
            if c.label
            and c.label.startswith(
                "Show posterior uncertainty for this sequential plan"
            )
        ),
        None,
    )
    assert uncertainty_checkbox is not None
    uncertainty_checkbox.check()
    at.run()
    assert not at.exception, (
        f"enabling sequential posterior uncertainty raised: {at.exception}"
    )

    markdown_text = [m.value or "" for m in at.markdown]
    assert any(
        "Plan-window total incremental outcome, per sampled posterior draw" in text
        for text in markdown_text
    )


def test_sequential_weekly_manual_tab_can_save_a_scenario():
    """WP5 part 4: saving a sequential-weekly scenario must append a
    calculation_method="sequential_weekly" dict to the same `scenarios`
    session-state list a steady-state scenario is saved to, and the
    "Saved scenarios" section must render it (separately from the
    steady-state-only comparison table, which requires a `predicted`
    DataFrame no sequential scenario dict carries) without raising."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()

    method_radio = next(
        r for r in at.radio if r.label == "Manual plan evaluation method"
    )
    method_radio.set_value("sequential_weekly").run()
    _check_sequential_acknowledgment_gates(at)
    at.run()
    assert not at.exception, f"acknowledging assumptions raised: {at.exception}"

    save_button = next(b for b in at.button if b.label == "Save this scenario")
    save_button.click().run()
    assert not at.exception, f"saving the sequential scenario raised: {at.exception}"

    scenarios = at.session_state["scenarios"]
    assert len(scenarios) == 1
    assert scenarios[0]["calculation_method"] == "sequential_weekly"
    assert "predicted" not in scenarios[0]
    assert "sequential_evaluation" in scenarios[0]

    markdown_text = [m.value or "" for m in at.markdown]
    assert any("Saved sequential-weekly scenarios" in text for text in markdown_text)

    captions = [c.value or "" for c in at.caption]
    assert any(text.startswith("Plan window:") for text in captions)

    metric_labels = {metric.label for metric in at.metric}
    assert any("Short-horizon incremental" in label for label in metric_labels)
    assert any("Long-horizon incremental" in label for label in metric_labels)


def test_steady_state_manual_tab_still_renders_by_default():
    """The default evaluation method stays steady-state monthly - switching
    the radio to sequential and back (or simply never touching it) must
    still render the pre-existing steady-state content unchanged."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "Predicted outcomes for the spend plan" in (m.value or "") for m in at.markdown
    )


def test_allocation_desk_separates_editable_proposed_and_saved_state():
    """Phase 5: the planner presents an allocation-desk state model without
    changing the existing evaluator or optimiser contracts."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at, value_currency="GBP")
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    markdown = [m.value or "" for m in at.markdown]
    captions = [c.value or "" for c in at.caption]
    assert any("Allocation desk" in text for text in markdown)
    assert any("Decision outputs" in text for text in markdown)
    assert any("Planning assumptions & use" in text for text in markdown)
    assert any("Saved scenarios" in text for text in markdown)
    assert any("current reference plan" in text for text in captions)
    assert [tab.label for tab in at.tabs] == [
        "Edited plan and calculated result",
        "Constrained proposal",
        "Unconstrained benchmark",
    ]
    metric_labels = {metric.label for metric in at.metric}
    assert {
        "Model approval",
        "Plan state",
        "Evaluation method",
        "Saved scenarios",
    } <= metric_labels
