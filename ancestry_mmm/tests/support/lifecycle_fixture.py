"""
PR 122: shared builders for one deterministic, already-fitted synthetic
project that proves the official curve-to-scenario lifecycle end to end -
governance validation, official curve artifact creation (model-input and
monetary), fingerprint verification, use authorisation, export/import,
transactional artifact-store replacement, reauthorisation, official
scenario evaluation, and staleness on a cost/FX change.

No live MCMC/NUTS sampling anywhere: the trace is a structurally-valid but
synthetic posterior, the same recipe as `test_persistence.py`'s
`_make_consistent_meta()`/`_make_trace()` and the AppTest suites'
`_meta()`/`_trace()` helpers - consolidated here into one shared builder so
a third hand-rolled copy never exists. A plain pytest integration test and
an AppTest both seed from these same builder functions (the AppTest seeds
`at.session_state` directly rather than using fixture injection, but calls
the identical builders).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Optional, Tuple

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.application.curve_service import CurveService, OfficialCurveGovernance
from ancestry_mmm.application.diagnostics_service import DiagnosticsArtefact
from ancestry_mmm.application.scenario_service import (
    ManualScenarioInput,
    ScenarioService,
    ScenarioServiceResult,
)
from ancestry_mmm.core.activities import ActivityDefinition, activity_fit_fingerprint
from ancestry_mmm.core.approval import (
    ModelApproval,
    create_policy_backed_model_approval,
    fingerprint_model_approval,
)
from ancestry_mmm.core.canonical_curves import CurveReferenceContext
from ancestry_mmm.core.curve_artifact import (
    CurveArtifactMetadata,
    compute_curve_artifact_fingerprints,
    write_curve_artifact,
)
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.media_costs import (
    CostMappingRegistry,
    FixedCostPerUnitMapping,
    MediaInputSpec,
    MediaInputSupport,
    MonetarySpendSupport,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.optimization import scenario_to_dict
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
from ancestry_mmm.core.planning.value import (
    CurrencyContext,
    PlanningObjective,
    ScenarioValidationContext,
)
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

MARKET = "UK"
CHANNEL = "TV_Brand"
OUTCOME_ID = "New"
MODEL_RUN_ID = "run-lifecycle-1"
PROJECT_NAME = "lifecycle-test-project"
SCENARIO_MONTH = "2024-01"
N_FOURIER = 6

UNRELATED_ARTIFACT_ID = "unrelated-pre-existing-art"


# ---------------------------------------------------------------------------
# Outcome / model structure
# ---------------------------------------------------------------------------


def build_outcome_definition() -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id=OUTCOME_ID,
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


def build_meta(outcome_definition: Optional[OutcomeDefinition] = None) -> FHModelMeta:
    outcome_definition = outcome_definition or build_outcome_definition()
    return FHModelMeta(
        markets=[MARKET],
        outcome_ids=[OUTCOME_ID],
        channels=[CHANNEL],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id=OUTCOME_ID,
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
        outcome_catalogue_at_fit=[outcome_definition],
    )


def build_trace(
    meta: FHModelMeta,
    *,
    n_fourier: int = N_FOURIER,
    chains: int = 2,
    draws: int = 10,
    seed: int = 0,
) -> az.InferenceData:
    """A structurally-valid (never live-sampled) trace carrying exactly the
    variables/dims `extract_posterior_params(trace, meta)` needs - the same
    recipe as `test_persistence.py`'s `_make_trace()` and the curve/scenario
    AppTest suites' `_trace()` helpers."""
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


def build_transformed_data(*, weeks: int = 16) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": d,
                "market": MARKET,
                CHANNEL: 100.0 + i * 10.0,
                "fh_new_gsa": 10.0 + i * 0.5,
            }
            for i, d in enumerate(pd.date_range("2024-01-01", periods=weeks, freq="W"))
        ]
    )


def build_model_spec_dict() -> dict:
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=[MARKET],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=[CHANNEL],
    ).to_dict()


def build_activity_definitions() -> list[ActivityDefinition]:
    return [
        ActivityDefinition(
            activity_id="tv-brand-paid",
            channel=CHANNEL,
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


@dataclass
class FittedModel:
    outcome_definition: OutcomeDefinition
    meta: FHModelMeta
    trace: az.InferenceData
    transformed_data: pd.DataFrame
    model_spec_dict: dict
    prior_config: dict
    dna_lag_weeks: int
    frame: dict
    posterior_params: object
    activity_definitions: list[ActivityDefinition]
    model_run_id: str
    data_fingerprint: str
    model_spec_fingerprint: str
    posterior_fingerprint: str


def build_fitted_model() -> FittedModel:
    """Deterministically build a complete, internally-consistent fitted
    model: transformed frame, model spec, structurally-valid trace, derived
    posterior params, and the fingerprints that must match for governance
    (`ModelApproval`, `ApprovalReadiness`) to bind to it."""
    outcome_definition = build_outcome_definition()
    meta = build_meta(outcome_definition)
    trace = build_trace(meta)
    transformed_data = build_transformed_data()
    model_spec_dict = build_model_spec_dict()
    prior_config = {"decay_mu": 0.5}
    dna_lag_weeks = 4
    spec = ModelSpec.from_dict(model_spec_dict)
    frame = prepare_fh_modeling_frame(transformed_data, spec)
    posterior_params = extract_posterior_params(trace, meta)
    activity_definitions = build_activity_definitions()

    data_fingerprint = fingerprint_dataframe(frame["df"])
    model_spec_fingerprint = fingerprint_model_spec(
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
    posterior_fingerprint = fingerprint_posterior(posterior_params)

    return FittedModel(
        outcome_definition=outcome_definition,
        meta=meta,
        trace=trace,
        transformed_data=transformed_data,
        model_spec_dict=model_spec_dict,
        prior_config=prior_config,
        dna_lag_weeks=dna_lag_weeks,
        frame=frame,
        posterior_params=posterior_params,
        activity_definitions=activity_definitions,
        model_run_id=MODEL_RUN_ID,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    )


# ---------------------------------------------------------------------------
# Model approval / validation policy / diagnostics
# ---------------------------------------------------------------------------


def build_policy_backed_governance(
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
) -> Tuple[ThresholdPolicy, ApprovalReadiness, ModelApproval, DiagnosticsArtefact]:
    """A deterministic, fingerprint-consistent (policy, readiness, approval,
    diagnostics) quadruple - the same recipe as
    `test_curve_bank_page_apptest.py`'s and
    `test_official_curve_generation_page_apptest.py`'s
    `_policy_backed_governance()`."""
    identity = ModelIdentity(
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    )
    diagnostics = DiagnosticsArtefact(
        artefact_id="diag-lifecycle",
        model_identity_fingerprint=identity.fingerprint(),
    )
    gate = ValidationGate(
        name="divergences",
        description="No divergences",
        evaluator_id="divergences",
        expected_state=False,
    )
    policy = ThresholdPolicy(
        policy_id="lifecycle-policy",
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
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
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
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    )
    return policy, readiness, approval, diagnostics


def build_outcome_approval(outcome_definition: OutcomeDefinition) -> OutcomeApproval:
    return OutcomeApproval(
        approval_id="apr-lifecycle-outcome",
        outcome_id=outcome_definition.outcome_id,
        definition_fingerprint=fingerprint_outcome_definition(outcome_definition),
        status="approved",
        allowed_uses=(
            "curve_publication",
            "headline_reporting",
            "planning",
            "optimisation",
        ),
        approved_by="Jane Analyst",
        approved_at="2026-01-01",
    )


# ---------------------------------------------------------------------------
# Media inputs, cost mapping, currency
# ---------------------------------------------------------------------------


def build_cost_mapping_registry(
    *, cost_per_media_input: float = 2.0
) -> CostMappingRegistry:
    mapping = FixedCostPerUnitMapping(
        mapping_id="uk-tv-brand-cost",
        market=MARKET,
        channel=CHANNEL,
        currency="GBP",
        cost_context_id="default",
        source="finance rate card",
        cost_per_media_input=cost_per_media_input,
        approval_status="approved",
        approved_by="finance-owner",
        approved_at="2026-01-01",
        owner="media-finance",
        approval_note="approved for lifecycle test",
        last_reviewed_at="2026-01-01",
    )
    return CostMappingRegistry([mapping])


def build_media_input_specs() -> Dict[Tuple[str, str], MediaInputSpec]:
    return {
        (MARKET, CHANNEL): MediaInputSpec(
            market=MARKET,
            channel=CHANNEL,
            column="tv_brand_impressions",
            unit="thousand_impressions",
            unit_scale=1000.0,
        )
    }


def build_media_support(
    specs: Optional[Dict[Tuple[str, str], MediaInputSpec]] = None,
) -> Dict[Tuple[str, str], MediaInputSupport]:
    specs = specs or build_media_input_specs()
    return {
        key: MediaInputSupport(
            market=key[0],
            channel=key[1],
            unit=spec.unit,
            current=50.0,
            observed_min=0.0,
            observed_max=100.0,
            planning_min=0.0,
            planning_max=150.0,
            current_method="last_4_week_average",
            source="model frame",
            provenance="test:X_media",
        )
        for key, spec in specs.items()
    }


def build_monetary_support(
    cost_registry: Optional[CostMappingRegistry] = None,
) -> Dict[Tuple[str, str], MonetarySpendSupport]:
    cost_registry = cost_registry or build_cost_mapping_registry()
    mapping = cost_registry.resolve(MARKET, CHANNEL, "default")
    return {
        (MARKET, CHANNEL): MonetarySpendSupport(
            market=MARKET,
            channel=CHANNEL,
            local_currency=mapping.currency,
            reporting_currency="GBP",
            current_local=100.0,
            observed_local_min=0.0,
            observed_local_max=200.0,
            planning_local_min=0.0,
            planning_local_max=300.0,
            fx_rate=1.0,
            current_method="last_4_week_average",
            source="model frame",
            provenance="test:X_spend",
            cost_mapping_id=mapping.mapping_id,
            cost_mapping_fingerprint=cost_registry.fingerprint(),
            approved_by="reviewer",
            approved_at="2026-01-01",
            owner="Analytics",
            approval_note="approved for test",
        )
    }


def build_currency_context() -> CurrencyContext:
    return CurrencyContext(
        market_reporting_currency="GBP",
        value_currency="GBP",
        group_reporting_currency="GBP",
        model_currency="GBP",
        historical_fx_rate_set_id="fx-set-2026-07",
        historical_fx_rate_set_fingerprint="fx-set-2026-07-fp",
        future_fx_assumption_id="fx-future-2026",
        future_fx_assumption_fingerprint="fx-future-2026-fp",
    )


def build_reference_contexts(
    meta: FHModelMeta,
    *,
    n_fourier: int = N_FOURIER,
    counterfactual_axis_type: str = "model_input",
) -> Dict[str, CurveReferenceContext]:
    return {
        MARKET: CurveReferenceContext(
            reference_context_id=f"{MARKET}-recent",
            mode="recent_average",
            market=MARKET,
            trend=0.5,
            fourier=tuple(0.1 for _ in range(n_fourier)),
            promo={oid: 0.0 for oid in meta.outcome_ids},
            controls={},
            outcome_controls={},
            other_channel_media_input={CHANNEL: 50.0},
            counterfactual_value=0.0,
            counterfactual_axis_type=counterfactual_axis_type,
            reference_period_start="2024-01-01",
            reference_period_end="2024-04-21",
        )
    }


def build_planning_objective(
    outcome_definition: Optional[OutcomeDefinition] = None,
) -> PlanningObjective:
    outcome_definition = outcome_definition or build_outcome_definition()
    return PlanningObjective(
        estimand="incremental_outcome",
        metric_key=outcome_definition.metric_key,
        target_outcome_ids=(outcome_definition.outcome_id,),
    )


# ---------------------------------------------------------------------------
# Official curve governance bundle
# ---------------------------------------------------------------------------


def build_official_curve_governance(
    fitted: FittedModel,
    *,
    policy: ThresholdPolicy,
    readiness: ApprovalReadiness,
    approval: ModelApproval,
    diagnostics: DiagnosticsArtefact,
    outcome_approval: OutcomeApproval,
) -> OfficialCurveGovernance:
    identity = ModelIdentity(
        model_run_id=fitted.model_run_id,
        data_fingerprint=fitted.data_fingerprint,
        model_spec_fingerprint=fitted.model_spec_fingerprint,
        posterior_fingerprint=fitted.posterior_fingerprint,
    )
    return OfficialCurveGovernance(
        model_identity=identity,
        model_approval=approval,
        outcome_definition=fitted.outcome_definition,
        outcome_approval=outcome_approval,
        threshold_policy=policy,
        approval_readiness=readiness,
        diagnostics_artefact=diagnostics,
        activity_definitions=fitted.activity_definitions,
        outcome_approvals=(outcome_approval,),
    )


# ---------------------------------------------------------------------------
# Full bundle
# ---------------------------------------------------------------------------


@dataclass
class LifecycleProject:
    fitted: FittedModel
    policy: ThresholdPolicy
    readiness: ApprovalReadiness
    approval: ModelApproval
    diagnostics: DiagnosticsArtefact
    outcome_approval: OutcomeApproval
    governance: OfficialCurveGovernance
    cost_mapping_registry: CostMappingRegistry
    media_input_specs: Dict[Tuple[str, str], MediaInputSpec]
    media_support: Dict[Tuple[str, str], MediaInputSupport]
    monetary_support: Dict[Tuple[str, str], MonetarySpendSupport]
    currency_context: CurrencyContext
    reference_contexts: Dict[str, CurveReferenceContext]
    planning_objective: PlanningObjective


def build_lifecycle_project() -> LifecycleProject:
    """The one builder that assembles the complete, deterministic,
    already-fitted synthetic project: fitted model, policy-backed model
    approval, approved outcome/activities, cost mapping registry, currency
    context, and official curve governance - everything needed to prove the
    official curve-to-scenario lifecycle end to end."""
    fitted = build_fitted_model()
    policy, readiness, approval, diagnostics = build_policy_backed_governance(
        fitted.model_run_id,
        fitted.data_fingerprint,
        fitted.model_spec_fingerprint,
        fitted.posterior_fingerprint,
    )
    outcome_approval = build_outcome_approval(fitted.outcome_definition)
    governance = build_official_curve_governance(
        fitted,
        policy=policy,
        readiness=readiness,
        approval=approval,
        diagnostics=diagnostics,
        outcome_approval=outcome_approval,
    )
    cost_mapping_registry = build_cost_mapping_registry()
    media_input_specs = build_media_input_specs()
    media_support = build_media_support(media_input_specs)
    monetary_support = build_monetary_support(cost_mapping_registry)
    currency_context = build_currency_context()
    reference_contexts = build_reference_contexts(fitted.meta)
    planning_objective = build_planning_objective(fitted.outcome_definition)
    return LifecycleProject(
        fitted=fitted,
        policy=policy,
        readiness=readiness,
        approval=approval,
        diagnostics=diagnostics,
        outcome_approval=outcome_approval,
        governance=governance,
        cost_mapping_registry=cost_mapping_registry,
        media_input_specs=media_input_specs,
        media_support=media_support,
        monetary_support=monetary_support,
        currency_context=currency_context,
        reference_contexts=reference_contexts,
        planning_objective=planning_objective,
    )


@pytest.fixture
def lifecycle_project() -> LifecycleProject:
    return build_lifecycle_project()


# ---------------------------------------------------------------------------
# Curve generation kwargs (model-input vs monetary)
# ---------------------------------------------------------------------------


def build_model_input_generation_kwargs(project: LifecycleProject) -> dict:
    return {
        "curve_type": "model_input",
        "media_input_specs": project.media_input_specs,
        "support_by_market_channel": project.media_support,
        "n_draws": 2,
        "spend_points": [0.0, 50.0, 100.0],
    }


def build_monetary_generation_kwargs(project: LifecycleProject) -> dict:
    mapping = project.cost_mapping_registry.resolve(MARKET, CHANNEL, "default")
    return {
        "curve_type": "monetary",
        "media_input_specs": project.media_input_specs,
        "support_by_market_channel": project.monetary_support,
        "cost_mappings": {(MARKET, CHANNEL): mapping},
        "currency_by_market": {MARKET: "GBP"},
        "reporting_currency": "GBP",
        "currency_rates": {},
        "fx_as_of_date": "2026-07-01",
        "fx_source": "test-fx-provider",
        "n_draws": 2,
        "spend_points": [0.0, 50.0, 100.0],
    }


# ---------------------------------------------------------------------------
# Unrelated pre-existing artifact (destination-store seed)
# ---------------------------------------------------------------------------


def _unrelated_artifact_metadata(
    artifact_id: str = UNRELATED_ARTIFACT_ID,
) -> CurveArtifactMetadata:
    base = CurveArtifactMetadata(
        artifact_id=artifact_id,
        creation_timestamp="2026-01-01T00:00:00+00:00",
        model_identity_snapshot={
            "model_run_id": "run-unrelated",
            "data_fingerprint": "d-unrelated",
            "model_spec_fingerprint": "s-unrelated",
            "posterior_fingerprint": "p-unrelated",
        },
        approval_snapshot={"approval_id": "apr-unrelated", "status": "approved"},
        threshold_policy_snapshot={"policy_id": "pol-unrelated", "version": "1.0"},
        readiness_snapshot={"readiness_id": "rd-unrelated", "overall_ready": True},
        diagnostics_snapshot={"artefact_id": "diag-unrelated", "schema_version": 2},
        outcome_definition_snapshot={
            "outcome_id": "unrelated_outcome",
            "definition_version": "1.0",
        },
        outcome_approval_snapshot={
            "approval_id": "apr-unrelated-o1",
            "allowed_uses": ["curve_publication"],
        },
        activity_governance_snapshot={"activities": ["unrelated-channel"]},
        pathway_governance_snapshot={"pathways": ["direct"]},
        reference_context_snapshot={"market": "US", "mode": "steady_state_reference"},
        support_snapshot={"observed_support_status": "available"},
        cost_currency_snapshot={"currency": "USD", "fx_as_of_date": "2026-01-01"},
    )
    return replace(base, fingerprints=dict(compute_curve_artifact_fingerprints(base)))


def _unrelated_artifact_draws() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_run_id": "run-unrelated",
                "reference_context_id": "ctx-unrelated",
                "market": "US",
                "product": "DNA",
                "segment": "New",
                "outcome_id": "unrelated_outcome",
                "metric_key": "dna_kit_sale",
                "channel": "Unrelated_Channel",
                "component_type": "direct",
                "pathway_role": "primary",
                "spend_point": 0,
                "posterior_draw": 0,
                "incremental_response": 1.0,
            }
        ]
    )


def _unrelated_artifact_summaries() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_run_id": "run-unrelated",
                "reference_context_id": "ctx-unrelated",
                "market": "US",
                "product": "DNA",
                "segment": "New",
                "outcome_id": "unrelated_outcome",
                "metric_key": "dna_kit_sale",
                "channel": "Unrelated_Channel",
                "component_type": "direct",
                "pathway_role": "primary",
                "spend_point": 0,
                "incremental_response": 1.0,
            }
        ]
    )


def write_unrelated_artifact(
    store_dir: Path, artifact_id: str = UNRELATED_ARTIFACT_ID
) -> Path:
    """Write ONE unrelated pre-existing curve artifact directly into
    `store_dir` via `write_curve_artifact` - the same minimal, non-governed
    pattern as `test_persistence.py`'s `_write_official_artifact()`. Its
    governance evidence is deliberately unrelated to `LifecycleProject`'s
    own chain, so it can never be confused with an imported artifact; it
    exists only to prove `replace_curve_artifact_store` replaces rather
    than merges."""
    directory = store_dir / artifact_id
    write_curve_artifact(
        directory,
        metadata=_unrelated_artifact_metadata(artifact_id),
        draws=_unrelated_artifact_draws(),
        summaries=_unrelated_artifact_summaries(),
    )
    return directory


# ---------------------------------------------------------------------------
# Official manual scenario evaluation / persistence
# ---------------------------------------------------------------------------


def build_counterfactual_policy() -> CounterfactualPolicy:
    return CounterfactualPolicy()


def build_reference_context_by_month(*, n_fourier: int = N_FOURIER) -> Dict[str, dict]:
    return {
        SCENARIO_MONTH: {
            "trend": 0.5,
            "fourier": np.full(n_fourier, 0.1),
            "promo": {OUTCOME_ID: 0.0},
            "controls": {},
            "outcome_controls": {},
        }
    }


def build_manual_scenario_input(
    project: LifecycleProject,
    *,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
) -> ManualScenarioInput:
    fitted = project.fitted
    return ManualScenarioInput(
        market=MARKET,
        spend_plan={SCENARIO_MONTH: {CHANNEL: 100.0}},
        meta=fitted.meta,
        params=fitted.posterior_params,
        reference_context_by_month=build_reference_context_by_month(),
        model_type="shared",
        approval=project.approval,
        model_run_id=fitted.model_run_id,
        data_fingerprint=fitted.data_fingerprint,
        model_spec_fingerprint=fitted.model_spec_fingerprint,
        posterior_fingerprint=fitted.posterior_fingerprint,
        cost_mapping_registry=cost_mapping_registry or project.cost_mapping_registry,
        cost_context_id="default",
        cost_as_of_by_month={SCENARIO_MONTH: "2024-01-01"},
        planning_objective=project.planning_objective,
        activity_definitions=fitted.activity_definitions,
        outcome_approvals=[project.outcome_approval],
        governance_mode="official",
        currency_context=project.currency_context,
        counterfactual_policy=build_counterfactual_policy(),
        approval_readiness=project.readiness,
        current_policy=project.policy,
    )


def evaluate_official_manual_scenario(
    project: LifecycleProject,
    *,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
) -> ScenarioServiceResult:
    sc_input = build_manual_scenario_input(
        project, cost_mapping_registry=cost_mapping_registry
    )
    return ScenarioService().evaluate_manual(sc_input)


def build_saved_scenario_dict(
    project: LifecycleProject, result: ScenarioServiceResult
) -> dict:
    """Build the persisted scenario dict (schema v4) with
    `ScenarioGovernanceDependencies` capturing the cost mapping's current
    fingerprint - `core.optimization.scenario_to_dict` is the single
    supported persistence path (there is no `Scenario`/`SavedScenario`
    dataclass in this codebase)."""
    assert result.evaluation is not None
    scenario = scenario_to_dict(
        name="lifecycle-manual-uk",
        market=MARKET,
        spend_plan={SCENARIO_MONTH: {CHANNEL: 100.0}},
        objective="fh_gsa",
        constraints=[],
        notes="PR 122 lifecycle integration",
        governance_mode="official",
        artefact_kind="manual_scenario",
        planning_objective=project.planning_objective,
        governance_dependencies=result.evaluation.governance_dependencies,
    )
    scenario["predicted"] = result.evaluation.predicted
    return scenario


def build_scenario_validation_context(
    project: LifecycleProject,
    scenario: dict,
    *,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
) -> ScenarioValidationContext:
    """The complete current-state context `validate_scenario_dependencies`
    needs to decide whether `scenario` is current, stale, or invalid -
    `cost_mapping_registry` defaults to the project's own (unchanged)
    registry; callers proving a cost/FX-driven staleness pass the mutated
    registry instead."""
    cost_mapping_registry = cost_mapping_registry or project.cost_mapping_registry
    return ScenarioValidationContext(
        model_run_id=project.fitted.model_run_id,
        model_approval_fingerprint=fingerprint_model_approval(project.approval),
        data_fingerprint=project.fitted.data_fingerprint,
        model_spec_fingerprint=project.fitted.model_spec_fingerprint,
        posterior_fingerprint=project.fitted.posterior_fingerprint,
        planning_objective=project.planning_objective,
        outcome_definitions=(project.fitted.outcome_definition.to_dict(),),
        outcome_approvals=(project.outcome_approval.to_dict(),),
        counterfactual_fingerprint=build_counterfactual_policy().fingerprint(),
        currency_context_fingerprint=project.currency_context.fingerprint(),
        activity_fingerprint=scenario.get("activity_definitions_fingerprint"),
        cost_fingerprint=cost_mapping_registry.fingerprint(),
    )


def build_lifecycle_project_bundle(
    bundle_path: Path,
    *,
    project: Optional["LifecycleProject"] = None,
    store_dir: Optional[Path] = None,
) -> Path:
    """Build the complete deterministic project bundle `.zip` at
    `bundle_path`: both official curve artifacts, an official manual
    scenario save, and every governance record `export_project` accepts -
    the same construction `test_official_lifecycle_integration.py` proves
    step-by-step, reused here so the Playwright browser journey exercises
    the real `Project Import` file-upload path against an identical bundle
    rather than a hand-rolled duplicate.

    `raw_sources` carries the fixture's own transformed frame (there is no
    separate pre-pipeline table here - `pipeline_steps=[]` already means
    "transformed_data is the raw upload, unmodified"). Without it,
    `audit_project_resumability()`'s "scenarios" checkpoint reports
    `raw_sources` missing and the real Project Import page warns that the
    bundle cannot actually resume its saved scenario - exactly the
    officially-resumable claim this fixture exists to prove end to end."""
    from ancestry_mmm.core.persistence import export_project

    project = project or build_lifecycle_project()
    store_dir = store_dir or (bundle_path.parent / "curve-artifacts")
    create_official_artifacts(project, store_dir)
    scenario_result = evaluate_official_manual_scenario(project)
    scenario_dict = build_saved_scenario_dict(project, scenario_result)
    return export_project(
        bundle_path,
        raw_sources={"joined": project.fitted.transformed_data.copy()},
        transformed_data=project.fitted.transformed_data,
        pipeline_steps=[],
        model_spec=project.fitted.model_spec_dict,
        prior_config=project.fitted.prior_config,
        dna_lag_weeks=project.fitted.dna_lag_weeks,
        trace=project.fitted.trace,
        scenarios=[scenario_dict],
        curve_artifact_store_source_dir=store_dir,
        model_approval=project.approval.to_dict(),
        model_run_id=project.fitted.model_run_id,
        model_meta=project.fitted.meta,
        outcome_definitions=[project.fitted.outcome_definition.to_dict()],
        activity_definitions=[a.to_dict() for a in project.fitted.activity_definitions],
        outcome_approvals=[project.outcome_approval.to_dict()],
        validation_policy=project.policy.to_dict(),
        diagnostics_artefact=project.diagnostics.to_dict(),
        approval_readiness=project.readiness.to_dict(),
        media_cost_mappings=project.cost_mapping_registry.to_dict(),
        # PR 125A: the project-level policy/context this scenario's saved
        # counterfactual_policy_fingerprint / currency_context_fingerprint
        # (see build_scenario_validation_context above) must be verifiable
        # against on import - without these, this bundle is a genuine
        # "technically but not officially resumable" case, exactly the gap
        # PR 125A closes.
        counterfactual_policy=build_counterfactual_policy().to_dict(),
        currency_context=project.currency_context.to_dict(),
    )


def create_official_artifacts(
    project: LifecycleProject,
    store_dir: Path,
    *,
    model_input_artifact_id: str = "lifecycle-model-input",
    monetary_artifact_id: str = "lifecycle-monetary",
    value_per_response: Optional[Dict[str, float]] = None,
):
    """Create both the model-input and the monetary official curve
    artifacts for `project` in `store_dir` via `CurveService`, returning
    `(model_input_result, monetary_result)`."""
    service = CurveService()
    model_input_result = service.create_official_artifact(
        project.governance,
        artifact_id=model_input_artifact_id,
        store_dir=store_dir,
        meta=project.fitted.meta,
        trace=project.fitted.trace,
        reference_contexts=build_reference_contexts(
            project.fitted.meta, counterfactual_axis_type="model_input"
        ),
        **build_model_input_generation_kwargs(project),
    )
    monetary_result = service.create_official_artifact(
        project.governance,
        artifact_id=monetary_artifact_id,
        store_dir=store_dir,
        meta=project.fitted.meta,
        trace=project.fitted.trace,
        reference_contexts=build_reference_contexts(
            project.fitted.meta, counterfactual_axis_type="monetary"
        ),
        value_per_response=value_per_response or {OUTCOME_ID: 25.0},
        **build_monetary_generation_kwargs(project),
    )
    return model_input_result, monetary_result
