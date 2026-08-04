"""AppTest coverage for PR 96C: 13_Official_Curve_Generation.py - the first
UI path that calls CurveService.create_official_artifact.

Fixture recipe mirrors test_curve_bank_page_apptest.py's (same page-computed
"current_identity" convention, same policy-backed-governance helper), since
both pages resolve governance identically.
"""

from pathlib import Path

import arviz as az
import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.activities import ActivityDefinition, activity_fit_fingerprint
from ancestry_mmm.core.approval import create_policy_backed_model_approval
from ancestry_mmm.core.curve_artifact import load_curve_artifact_store
from ancestry_mmm.core.media_costs import (
    CostMappingRegistry,
    IdentitySpendMapping,
    PiecewiseLinearCostMapping,
)
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
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
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact
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
PAGE = ROOT / "pages" / "13_Official_Curve_Generation.py"


def _outcome_definition() -> OutcomeDefinition:
    return OutcomeDefinition(
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


def _meta(markets: list | None = None) -> FHModelMeta:
    return FHModelMeta(
        markets=markets or ["UK"],
        outcome_ids=["New"],
        channels=["TV_Brand"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="New",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
        outcome_catalogue_at_fit=[_outcome_definition()],
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


def _policy_backed_governance(model_run_id, data_fp, spec_fp, posterior_fp):
    identity = ModelIdentity(
        model_run_id=model_run_id,
        data_fingerprint=data_fp,
        model_spec_fingerprint=spec_fp,
        posterior_fingerprint=posterior_fp,
    )
    diagnostics = DiagnosticsArtefact(
        artefact_id="diag-ocg",
        model_identity_fingerprint=identity.fingerprint(),
    )
    gate = ValidationGate(
        name="divergences",
        description="No divergences",
        evaluator_id="divergences",
        expected_state=False,
    )
    policy = ThresholdPolicy(
        policy_id="ocg-policy",
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
        diagnostic_artefact_fingerprint=diagnostics.fingerprint(),
        artefact_id=diagnostics.artefact_id,
    )
    ctx = ValidationEvidenceContext(
        model_identity=identity,
        policy=policy,
        diagnostic_artefact_id=diagnostics.artefact_id,
        diagnostic_artefact_fingerprint=diagnostics.fingerprint(),
        model_type="shared",
        intended_use="model_approval",
    )
    readiness = evaluate_approval_readiness(
        [result],
        policy,
        identity,
        diagnostic_artefact_id=diagnostics.artefact_id,
        diagnostic_artefact_fingerprint=diagnostics.fingerprint(),
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
    return policy, readiness, approval, diagnostics


def _seed_governed_session_state(
    at: AppTest,
    *,
    allowed_uses=("curve_publication", "headline_reporting"),
    markets: list | None = None,
) -> None:
    markets = markets or ["UK"]
    meta = _meta(markets)
    trace = _trace(meta)
    transformed_data = pd.DataFrame(
        [
            {
                "date": d,
                "market": market,
                "TV_Brand": 100.0 + i * 10.0,
                "fh_new_gsa": 10.0 + i * 0.5,
            }
            for market in markets
            for i, d in enumerate(pd.date_range("2024-01-01", periods=16, freq="W"))
        ]
    )
    model_spec_dict = ModelSpec(
        date_col="date",
        market_col="market",
        markets=markets,
        segment_outcomes={"New": "fh_new_gsa"},
        channels=["TV_Brand"],
    ).to_dict()
    prior_config = {"decay_mu": 0.5}
    dna_lag_weeks = 4
    spec = ModelSpec.from_dict(model_spec_dict)
    frame = prepare_fh_modeling_frame(transformed_data, spec)
    posterior_params = extract_posterior_params(trace, meta)

    activity_definitions = [
        ActivityDefinition(
            activity_id="tv-brand-paid",
            channel="TV_Brand",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="media plan",
            approval_status="approved",
            approved_by="reviewer",
            approved_at="2026-01-01",
        )
    ]

    model_run_id = "run-ocg-apptest"
    data_fp = fingerprint_dataframe(frame["df"])
    spec_fp = fingerprint_model_spec(
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
        activity_fit_fingerprint=activity_fit_fingerprint(activity_definitions),
    )
    posterior_fp = fingerprint_posterior(posterior_params)

    policy, readiness, approval, diagnostics = _policy_backed_governance(
        model_run_id, data_fp, spec_fp, posterior_fp
    )

    outcome_def = _outcome_definition()
    outcome_approval = OutcomeApproval(
        approval_id="apr-o1",
        outcome_id="New",
        definition_fingerprint=fingerprint_outcome_definition(outcome_def),
        status="approved",
        allowed_uses=tuple(allowed_uses),
        approved_by="Jane Analyst",
        approved_at="2026-01-01",
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
    at.session_state["validation_policy"] = policy.to_dict()
    at.session_state["approval_readiness"] = readiness.to_dict()
    at.session_state["diagnostics_artefact"] = diagnostics
    at.session_state["outcome_definitions"] = [outcome_def.to_dict()]
    at.session_state["outcome_approvals"] = [outcome_approval.to_dict()]
    at.session_state["activity_definitions"] = [
        a.to_dict() for a in activity_definitions
    ]


def test_empty_state_loads_without_error():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"


def test_full_governance_generates_and_saves_an_artifact(monkeypatch, tmp_path):
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", tmp_path)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at)
    at.session_state["project_name"] = "ocg-test-project"
    # Corrective PR C1: generation is blocked without an explicit, reviewed
    # confirmation of the reference context for every selected market.
    # "recent_average" derives from the model frame unconditionally (unlike
    # the default "period_average", which needs an explicit period that
    # actually overlaps the fixture's dates).
    at.session_state["ocg_mode_UK"] = "recent_average"
    at.session_state["ocg_ctx_confirmed_UK"] = True
    at.session_state["ocg_spend_points"] = "0, 50, 100, 150, 200"
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    at.session_state["ocg_artifact_id"] = "art-ocg-1"
    generate_button = next(
        b for b in at.button if b.label == "Generate and save official curve artifact"
    )
    generate_button.click().run()
    assert not at.exception, f"generate click raised: {at.exception}"
    assert any("Saved official curve artifact" in (s.value or "") for s in at.success)

    store_dir = tmp_path / "ocg-test-project"
    result = load_curve_artifact_store(store_dir, raise_on_malformed=False)
    assert not result.malformed
    assert len(result.loaded) == 1
    assert result.loaded[0].metadata.artifact_id == "art-ocg-1"


def test_outcome_not_approved_for_curve_publication_blocks_generation(
    monkeypatch, tmp_path
):
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", tmp_path)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at, allowed_uses=("headline_reporting",))
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "No outcome is currently approved for curve_publication" in (i.value or "")
        for i in at.info
    )
    assert not any(
        b.label == "Generate and save official curve artifact" for b in at.button
    )


def test_artifact_id_collision_is_reported_not_raised(monkeypatch, tmp_path):
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", tmp_path)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at)
    at.session_state["project_name"] = "ocg-collision-project"
    at.session_state["ocg_mode_UK"] = "recent_average"
    at.session_state["ocg_ctx_confirmed_UK"] = True
    at.session_state["ocg_spend_points"] = "0, 50, 100, 150, 200"
    at.run()
    at.session_state["ocg_artifact_id"] = "art-dup"
    generate_button = next(
        b for b in at.button if b.label == "Generate and save official curve artifact"
    )
    generate_button.click().run()
    assert not at.exception
    assert any("Saved official curve artifact" in (s.value or "") for s in at.success)

    # Second attempt at the same artifact_id must be reported, not raised.
    at.session_state["ocg_artifact_id"] = "art-dup"
    generate_button = next(
        b for b in at.button if b.label == "Generate and save official curve artifact"
    )
    generate_button.click().run()
    assert not at.exception, f"collision click raised: {at.exception}"
    assert any(
        "Could not generate the official curve artifact" in (e.value or "")
        for e in at.error
    )


_MONETARY_RADIO_LABEL = "Monetary curve (requires an approved cost mapping)"


def _seed_approved_cost_mapping() -> dict:
    registry = CostMappingRegistry(
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
    return registry.to_dict()


def test_monetary_curve_with_approved_cost_mapping_generates_and_saves_an_artifact(
    monkeypatch, tmp_path
):
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", tmp_path)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at)
    at.session_state["project_name"] = "ocg-monetary-project"
    at.session_state["media_cost_mappings"] = _seed_approved_cost_mapping()
    at.session_state["ocg_curve_type"] = _MONETARY_RADIO_LABEL
    at.session_state["ocg_local_currency_UK"] = "GBP"
    at.session_state["ocg_reporting_currency"] = "GBP"
    at.session_state["ocg_fx_source"] = "test-fx-provider"
    at.session_state["ocg_mode_UK"] = "recent_average"
    at.session_state["ocg_ctx_confirmed_UK"] = True
    at.session_state["ocg_spend_points"] = "0, 50, 100, 150, 200"
    at.run()
    assert not at.exception, f"initial monetary load raised: {at.exception}"

    at.session_state["ocg_artifact_id"] = "art-monetary-1"
    generate_button = next(
        b for b in at.button if b.label == "Generate and save official curve artifact"
    )
    generate_button.click().run()
    assert not at.exception, f"monetary generate click raised: {at.exception}"
    assert any("Saved official curve artifact" in (s.value or "") for s in at.success)

    store_dir = tmp_path / "ocg-monetary-project"
    result = load_curve_artifact_store(store_dir, raise_on_malformed=False)
    assert not result.malformed
    assert len(result.loaded) == 1
    draws = result.loaded[0].draws
    assert draws["curve_type"].eq("monetary").all()
    assert draws["cost_mapping_id"].notna().all()
    assert draws["fx_source"].eq("test-fx-provider").all()


def test_monetary_curve_without_cost_mapping_blocks_generation(monkeypatch, tmp_path):
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", tmp_path)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at)
    at.session_state["project_name"] = "ocg-monetary-blocked-project"
    at.session_state["ocg_curve_type"] = _MONETARY_RADIO_LABEL
    at.session_state["ocg_local_currency_UK"] = "GBP"
    at.session_state["ocg_reporting_currency"] = "GBP"
    at.session_state["ocg_fx_source"] = "test-fx-provider"
    at.session_state["ocg_mode_UK"] = "recent_average"
    at.session_state["ocg_ctx_confirmed_UK"] = True
    at.session_state["ocg_spend_points"] = "0, 50, 100, 150, 200"
    at.run()
    assert not at.exception, f"initial monetary load raised: {at.exception}"

    at.session_state["ocg_artifact_id"] = "art-monetary-blocked"
    generate_button = next(
        b for b in at.button if b.label == "Generate and save official curve artifact"
    )
    generate_button.click().run()
    assert not at.exception, f"blocked monetary click raised: {at.exception}"
    assert any(
        "blocked without an approved, effective cost mapping" in (e.value or "")
        for e in at.error
    )


def test_cost_mapping_grid_reports_malformed_rows_without_raising(monkeypatch):
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at)
    at.session_state["ocg_curve_type"] = _MONETARY_RADIO_LABEL
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    # No cost mapping has been saved yet, so the default grid row (blank
    # currency) is surfaced as a row-level error, not raised out of the page.
    assert any("Row 1:" in (e.value or "") for e in at.error)


def test_reference_context_confirmation_is_required_before_generation(
    monkeypatch, tmp_path
):
    """Corrective PR C1: generation must be blocked until an analyst has
    explicitly reviewed and confirmed every selected market's reference
    context - never silently accepted, derived-from-frame or not."""
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", tmp_path)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at)
    at.session_state["project_name"] = "ocg-unconfirmed-project"
    at.session_state["ocg_spend_points"] = "0, 50, 100, 150, 200"
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    at.session_state["ocg_artifact_id"] = "art-unconfirmed"
    generate_button = next(
        b for b in at.button if b.label == "Generate and save official curve artifact"
    )
    generate_button.click().run()
    assert not at.exception, f"generate click raised: {at.exception}"
    assert any(
        "Review and confirm the reference context" in (e.value or "") for e in at.error
    )
    assert not any(
        "Saved official curve artifact" in (s.value or "") for s in at.success
    )


def test_blank_spend_axis_derives_per_channel_axis_from_support(monkeypatch, tmp_path):
    """Corrective PR C3: leaving the diagnostic spend axis blank derives each
    channel's axis from its own planning support range instead of forcing
    one axis, in one unit, onto every channel regardless of what it
    actually measures."""
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", tmp_path)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at)
    at.session_state["project_name"] = "ocg-per-channel-axis-project"
    at.session_state["ocg_mode_UK"] = "recent_average"
    at.session_state["ocg_ctx_confirmed_UK"] = True
    # ocg_spend_points is left at its blank default - the only axis source
    # is the derived support range opted into below.
    at.session_state["ocg_support_UK_TV_Brand_include"] = True
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    at.session_state["ocg_artifact_id"] = "art-per-channel-axis"
    generate_button = next(
        b for b in at.button if b.label == "Generate and save official curve artifact"
    )
    generate_button.click().run()
    assert not at.exception, f"generate click raised: {at.exception}"
    assert any("Saved official curve artifact" in (s.value or "") for s in at.success)


def test_deselecting_a_market_generates_only_for_the_selected_subset(
    monkeypatch, tmp_path
):
    """Corrective PR C4: generation must honor the analyst's market
    selection - deselecting a market previously still required that
    market's reference context/support and made generation fail outright
    with a ValueError from the fitted model's full market list."""
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", tmp_path)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at, markets=["UK", "AU"])
    at.session_state["project_name"] = "ocg-market-subset-project"
    at.session_state["ocg_markets"] = ["UK"]
    at.session_state["ocg_mode_UK"] = "recent_average"
    at.session_state["ocg_ctx_confirmed_UK"] = True
    at.session_state["ocg_spend_points"] = "0, 50, 100, 150, 200"
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    at.session_state["ocg_artifact_id"] = "art-market-subset"
    generate_button = next(
        b for b in at.button if b.label == "Generate and save official curve artifact"
    )
    generate_button.click().run()
    assert not at.exception, f"generate click raised: {at.exception}"
    assert any("Saved official curve artifact" in (s.value or "") for s in at.success)

    store_dir = tmp_path / "ocg-market-subset-project"
    result = load_curve_artifact_store(store_dir, raise_on_malformed=False)
    assert not result.malformed
    assert set(result.loaded[0].draws["market"]) == {"UK"}


def test_cost_mapping_editor_preserves_allow_extrapolation_and_supersedes_id(
    monkeypatch, tmp_path
):
    """Corrective PR C7: allow_extrapolation and supersedes_mapping_id must
    round-trip through the cost-mapping data_editor grid unedited - both
    previously reverted to their dataclass defaults on every save, even
    with no edit at all."""
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", tmp_path)

    registry = CostMappingRegistry(
        [
            PiecewiseLinearCostMapping(
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
                spend_knots=(0.0, 100.0),
                media_input_knots=(0.0, 1000.0),
                allow_extrapolation=True,
                supersedes_mapping_id="UK-TV_Brand-cost-v1",
            )
        ]
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_governed_session_state(at)
    at.session_state["media_cost_mappings"] = registry.to_dict()
    at.session_state["ocg_curve_type"] = _MONETARY_RADIO_LABEL
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    save_button = next(b for b in at.button if b.label == "Save cost mappings")
    save_button.click().run()
    assert not at.exception, f"save click raised: {at.exception}"

    saved = CostMappingRegistry.from_dict(at.session_state["media_cost_mappings"])
    saved_mapping = saved.resolve("UK", "TV_Brand", "default")
    assert saved_mapping is not None
    assert saved_mapping.allow_extrapolation is True
    assert saved_mapping.supersedes_mapping_id == "UK-TV_Brand-cost-v1"
