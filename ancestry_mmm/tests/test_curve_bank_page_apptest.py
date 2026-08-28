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
from typing import Sequence

import arviz as az
import dataclasses
import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.approval import (
    ModelApproval,
    create_policy_backed_model_approval,
)
from ancestry_mmm.core.activities import (
    ActivityDefinition,
    activity_definitions_fingerprint,
    activity_fit_fingerprint,
)
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


def _seed_consistent_session_state(
    at: AppTest, *, activities: Sequence[ActivityDefinition] | None = None
) -> None:
    """A real fitted model whose legacy approval's identity fingerprints
    match exactly how the page itself recomputes "current_identity".

    When ``activities`` is provided they are stored in session state and
    their fit fingerprint is included in the approval's spec fingerprint -
    exactly like the page's current_identity recomputation (PR 95E needs
    approved activities for the official artifact section)."""
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
    activity_definitions = list(activities or [])
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
            activity_fit_fingerprint=(
                activity_fit_fingerprint(activity_definitions)
                if activity_definitions
                else None
            ),
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
    at.session_state["activity_definitions"] = [
        a.to_dict() for a in activity_definitions
    ]


def _policy_backed_governance(model_run_id, data_fp, spec_fp, posterior_fp):
    """Mirrors test_scenario_planner_apptest.py's helper of the same name:
    a matching (policy, readiness, approval) triple for the given identity.

    PR 96A: also builds and returns the real ``DiagnosticsArtefact`` the
    readiness is bound to (rather than a bare hardcoded fingerprint string) -
    ``OfficialCurveGovernance`` now requires an actual diagnostics artefact
    object and ``CurveService`` verifies it matches the readiness binding
    and current model identity."""
    identity = ModelIdentity(
        model_run_id=model_run_id,
        data_fingerprint=data_fp,
        model_spec_fingerprint=spec_fp,
        posterior_fingerprint=posterior_fp,
    )
    diagnostics = DiagnosticsArtefact(
        artefact_id="diag-curve-bank",
        model_identity_fingerprint=identity.fingerprint(),
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


def _upgrade_to_policy_backed(at: AppTest) -> None:
    """Rebuild the already-seeded legacy model approval into a matching
    (policy, readiness, approval, diagnostics) tuple without touching any
    other state."""
    legacy_approval_dict = at.session_state["model_approval"]
    policy, readiness, approval, diagnostics = _policy_backed_governance(
        legacy_approval_dict["model_run_id"],
        legacy_approval_dict["data_fingerprint"],
        legacy_approval_dict["model_spec_fingerprint"],
        legacy_approval_dict["posterior_fingerprint"],
    )
    at.session_state["model_approval"] = approval.to_dict()
    at.session_state["validation_policy"] = policy.to_dict()
    at.session_state["approval_readiness"] = readiness.to_dict()
    at.session_state["diagnostics_artefact"] = diagnostics


def _seed_official_governance_state(at: AppTest) -> None:
    _seed_consistent_session_state(at)
    _upgrade_to_policy_backed(at)


def test_official_approval_with_matching_policy_and_readiness_allows_save():
    """A policy-backed approval whose bound readiness/policy fingerprints
    all still match the current model must pass the curve-bank gate (not
    be flagged as 'no longer matches')."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_governance_state(at)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "this approval will be recorded with each saved parameter snapshot"
        in (c.value or "")
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


def test_malformed_policy_does_not_crash_curve_bank_page():
    """PR 88A: a validation_policy dict whose 'gates' value isn't a list
    (e.g. corrupted session state) previously raised an uncaught TypeError
    out of ThresholdPolicy.from_dict's own ValidationGate.from_dict() call
    (iterating over a string's characters) - this page's inline handler
    only caught ValueError. Must now be reported and treated as no-policy,
    never crash the page."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at)
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


def test_malformed_readiness_does_not_crash_curve_bank_page():
    """A stored approval_readiness dict that fails to deserialize (here,
    'gate_results' isn't a list of gate-result dicts) must not crash the
    page - ApprovalReadiness.from_dict() was previously called here with no
    exception handling at all."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at)
    at.session_state["approval_readiness"] = {"gate_results": "not-a-list"}
    at.run()
    assert not at.exception, f"page raised: {at.exception}"


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
    # cb.make_entries() call sites. The PR 95E official-artifact governance
    # resolution (PR 96B: now a thin call-through to
    # CurveService.resolve_current_governance) threads the same readiness/
    # policy evidence through differently-named keywords
    # (current_readiness=/current_policy=), counted separately below.
    assert source.count("approval_readiness=current_readiness") == 3
    assert source.count("current_policy=current_policy") == 4
    assert source.count("current_readiness=current_readiness") == 1
    assert "ValidationPolicyBlockedError" in source


def test_curve_bank_section_labels_entries_as_parameter_snapshots_not_official():
    """PR 95F (REQ-CURVE-001): the page must present legacy curve bank entries
    as fitted parameter snapshots (the required qualifier) and must never
    attach 'official' labelling to the legacy curve bank itself - official
    rendering is confined to the 'Official curve artifacts' section."""
    source = "\n".join(
        line
        for line in PAGE.read_text(encoding="utf-8").split("\n")
        if not line.strip().startswith("#")
    )
    # Section caption under "## Curve bank" carries the qualifier.
    assert "fitted parameter snapshots" in source
    # The save flow labels what is saved as a fitted parameter snapshot.
    assert "saved parameter snapshot" in source
    # The legacy curve bank is never called official.
    assert "official curve bank" not in source
    # The qualifier caption points to the official section as the only
    # official rendering path.
    assert "Approved response curves" in source


# ---------------------------------------------------------------------------
# PR 95E: the "Official curve artifacts" section (REQ-CURVE-001 UI wiring)
# ---------------------------------------------------------------------------
#
# The page renders the governed official curve artifact store through the
# fail-closed store loader and revalidates every artifact against *current*
# governance via CurveService.authorize_use() before displaying it. The
# store root is patched to a pytest tmp_path so the AppTest never touches
# the real `.curve_artifact_store` directory.


def _patch_store_root(monkeypatch, tmp_path) -> Path:
    """Point the page's per-project store root at a throwaway directory."""
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", Path(tmp_path))
    return Path(tmp_path)


def _official_activity_dict() -> dict:
    """One approved activity matching the seeded fitted model (TV_Brand)."""
    return ActivityDefinition(
        activity_id="tv-paid",
        channel="TV_Brand",
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="optimisable",
        source="media plan",
        approval_status="approved",
        approved_by="reviewer",
        approved_at="2026-01-01",
    ).to_dict()


def _write_official_artifact(store_dir: Path, approval_dict: dict) -> None:
    """Write one loadable official artifact whose identity snapshot matches
    the seeded model approval (and therefore the page's current_identity)."""
    metadata = CurveArtifactMetadata(
        artifact_id="art-official-1",
        creation_timestamp="2026-07-01T00:00:00+00:00",
        model_identity_snapshot={
            "model_run_id": approval_dict["model_run_id"],
            "data_fingerprint": approval_dict["data_fingerprint"],
            "model_spec_fingerprint": approval_dict["model_spec_fingerprint"],
            "posterior_fingerprint": approval_dict["posterior_fingerprint"],
        },
        outcome_definition_snapshot={
            "outcome_id": "New",
            "definition_version": "1.0",
        },
        outcome_approval_snapshot={
            "approval_id": "apr-official-1",
            "allowed_uses": ["curve_publication", "headline_reporting"],
        },
        activity_governance_snapshot={
            "activities": ["tv-paid"],
            "fingerprint": activity_definitions_fingerprint(
                [ActivityDefinition.from_dict(_official_activity_dict())]
            ),
        },
    )
    metadata = dataclasses.replace(
        metadata,
        fingerprints=dict(compute_curve_artifact_fingerprints(metadata)),
    )
    draws = pd.DataFrame(
        {
            "model_run_id": [approval_dict["model_run_id"]] * 4,
            "reference_context_id": ["ref-official"] * 4,
            "market": ["UK"] * 4,
            "product": ["Family History"] * 4,
            "segment": ["New"] * 4,
            "outcome_id": ["New"] * 4,
            "metric_key": ["GSA"] * 4,
            "channel": ["TV_Brand"] * 4,
            "component_type": ["media"] * 4,
            "pathway_role": ["direct"] * 4,
            "spend_point": [0.0, 100.0, 200.0, 300.0],
            "local_spend": [0.0, 100.0, 200.0, 300.0],
            "posterior_draw": [0] * 4,
            "incremental_response": [0.0, 2.0, 3.0, 3.5],
            "planning_support_eligible": [True] * 4,
            "planning_blocked_reason": [""] * 4,
        }
    )
    summaries = draws.drop(
        columns=[
            "local_spend",
            "posterior_draw",
            "incremental_response",
            "planning_support_eligible",
            "planning_blocked_reason",
        ]
    )
    write_curve_artifact(store_dir, metadata=metadata, draws=draws, summaries=summaries)


def _seed_official_artifact_governance(at: AppTest) -> None:
    """Full current governance for the official section: policy-backed model
    approval (with the activity fit fingerprint, matching the page's
    current_identity recomputation), a matching outcome approval, and
    approved activities."""
    _seed_consistent_session_state(
        at, activities=[ActivityDefinition.from_dict(_official_activity_dict())]
    )
    _upgrade_to_policy_backed(at)
    at.session_state["project_name"] = "test-project"
    outcome_def = _meta().outcome_catalogue_at_fit[0]
    at.session_state["outcome_approvals"] = [
        OutcomeApproval(
            approval_id="apr-official-1",
            outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(outcome_def),
            status="approved",
            allowed_uses=("curve_publication", "headline_reporting"),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        ).to_dict()
    ]


def test_official_curve_artifact_renders_when_authorized(monkeypatch, tmp_path):
    """A fully governed store artifact (matching current identity, outcome,
    outcome approval, activities) must render as an official curve after
    authorize_use() revalidation - not be blocked or crashed."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_artifact_governance(at)
    _patch_store_root(monkeypatch, tmp_path)
    _write_official_artifact(
        Path(tmp_path) / "test-project", at.session_state["model_approval"]
    )
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("Saved response curves approved" in (c.value or "") for c in at.caption)
    assert any("art-official-1" in (markdown.value or "") for markdown in at.markdown)
    # Exploratory viewers stay clearly separate from official response curves.
    assert any(
        "Exploratory response curve (point estimates)" in (c.value or "")
        for c in at.caption
    )
    assert [
        tab.label
        for tab in at.tabs
        if tab.label
        in {
            "Where in the funnel?",
            "Which channel or supplier?",
            "Which activity?",
        }
    ] == [
        "Where in the funnel?",
        "Which channel or supplier?",
        "Which activity?",
    ]
    reporting_tables = [
        dataframe.value
        for dataframe in at.dataframe
        if "Effect component" in getattr(dataframe.value, "columns", [])
    ]
    assert reporting_tables, "expected the reporting views to render"
    assert all("outcome_id" not in dataframe.columns for dataframe in reporting_tables)


def test_official_section_empty_store_shows_info(monkeypatch, tmp_path):
    """An empty (or missing) store directory must show the informational
    empty state, never an exception or a silent section."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_artifact_governance(at)
    _patch_store_root(monkeypatch, tmp_path)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "No approved response curves have been saved" in (i.value or "")
        for i in at.info
    )


def test_official_artifact_blocked_without_outcome_approval(monkeypatch, tmp_path):
    """When current outcome approval is missing, the artifact must be shown
    as blocked (governance cannot be resolved) - fail closed, never rendered
    as an official curve."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_artifact_governance(at)
    at.session_state["outcome_approvals"] = []
    _patch_store_root(monkeypatch, tmp_path)
    _write_official_artifact(
        Path(tmp_path) / "test-project", at.session_state["model_approval"]
    )
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "cannot be shown as official evidence" in (w.value or "") for w in at.warning
    )


def test_official_section_reports_malformed_artifact(monkeypatch, tmp_path):
    """A malformed artifact directory must surface in the audit warning
    (never silently skipped) while the page keeps running."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_artifact_governance(at)
    _patch_store_root(monkeypatch, tmp_path)
    bad_dir = Path(tmp_path) / "test-project" / "bad-artifact"
    bad_dir.mkdir(parents=True)
    (bad_dir / "curve_artifact_metadata.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("could not be read" in (w.value or "") for w in at.warning)


def test_official_artifact_blocked_when_approval_lacks_curve_publication(
    monkeypatch, tmp_path
):
    """ledger-D finding 1 / Corrective PR B1: an approval that still grants
    headline_reporting but no longer grants curve_publication must block
    rendering as an official curve - curve_publication (the artifact's own
    official status) is checked independently of the requested use, not
    only whichever use is actually being requested."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_artifact_governance(at)
    outcome_def = _meta().outcome_catalogue_at_fit[0]
    at.session_state["outcome_approvals"] = [
        OutcomeApproval(
            approval_id="apr-official-1",
            outcome_id="New",
            definition_fingerprint=fingerprint_outcome_definition(outcome_def),
            status="approved",
            allowed_uses=("headline_reporting",),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        ).to_dict()
    ]
    _patch_store_root(monkeypatch, tmp_path)
    _write_official_artifact(
        Path(tmp_path) / "test-project", at.session_state["model_approval"]
    )
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "not currently approved for headline reporting" in (w.value or "")
        for w in at.warning
    )
    assert not any(
        "art-official-1" in (markdown.value or "") for markdown in at.markdown
    )


def test_official_curve_chart_renders_for_model_input_curve_with_two_components(
    monkeypatch, tmp_path
):
    """Corrective PR D1/D2: a model-input curve with two components
    (direct + cross_product) sharing the same spend_point/posterior_draw,
    and an all-NaN local_spend column (as every model-input curve has),
    must still resolve a plottable axis and render - not silently fall back
    to the "no plottable curves" caption the way a bare column-existence
    axis probe or a flat mean across component rows would allow."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_artifact_governance(at)
    _patch_store_root(monkeypatch, tmp_path)
    store_dir = Path(tmp_path) / "test-project"
    approval_dict = at.session_state["model_approval"]
    metadata = CurveArtifactMetadata(
        artifact_id="art-multi-component",
        creation_timestamp="2026-07-01T00:00:00+00:00",
        model_identity_snapshot={
            "model_run_id": approval_dict["model_run_id"],
            "data_fingerprint": approval_dict["data_fingerprint"],
            "model_spec_fingerprint": approval_dict["model_spec_fingerprint"],
            "posterior_fingerprint": approval_dict["posterior_fingerprint"],
        },
        outcome_definition_snapshot={
            "outcome_id": "New",
            "definition_version": "1.0",
            "segment": "NewSegment",
            "product": "Family History",
        },
        outcome_approval_snapshot={
            "approval_id": "apr-official-1",
            "status": "approved",
            "allowed_uses": ["curve_publication", "headline_reporting"],
        },
        activity_governance_snapshot={
            "activities": ["tv-paid"],
            "fingerprint": activity_definitions_fingerprint(
                [ActivityDefinition.from_dict(_official_activity_dict())]
            ),
        },
    )
    metadata = dataclasses.replace(
        metadata, fingerprints=dict(compute_curve_artifact_fingerprints(metadata))
    )
    draws = pd.DataFrame(
        {
            "model_run_id": [approval_dict["model_run_id"]] * 4,
            "reference_context_id": ["ref-official"] * 4,
            "market": ["UK"] * 4,
            "product": ["Family History"] * 4,
            "segment": ["New"] * 4,
            "outcome_id": ["New"] * 4,
            "metric_key": ["GSA"] * 4,
            "channel": ["TV_Brand"] * 4,
            "component_type": ["direct", "cross_product", "direct", "cross_product"],
            "pathway_role": ["direct", "cross_product", "direct", "cross_product"],
            "curve_type": ["model_input"] * 4,
            "spend_point": [0.0, 0.0, 100.0, 100.0],
            "local_spend": [np.nan] * 4,
            "media_input": [0.0, 0.0, 100.0, 100.0],
            "posterior_draw": [0, 0, 1, 1],
            "incremental_response": [1.0, 0.5, 2.0, 1.0],
            "planning_support_eligible": [True] * 4,
            "planning_blocked_reason": [""] * 4,
        }
    )
    summaries = draws.drop(
        columns=[
            "local_spend",
            "media_input",
            "posterior_draw",
            "incremental_response",
            "planning_support_eligible",
            "planning_blocked_reason",
            "curve_type",
        ]
    )
    write_curve_artifact(store_dir, metadata=metadata, draws=draws, summaries=summaries)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert not any("does not carry plottable" in (c.value or "") for c in at.caption)
    # Corrective PR D4/D5: the governed-context fields must actually appear
    # in the rendered metadata table - checked on the DataFrame itself
    # (str() truncates a 20-column single-row frame in the middle) -
    # "NewSegment" only ever comes from the new outcome_definition_
    # snapshot.segment field, never the pre-existing bare outcome_id
    # ("New") the table already showed.
    meta_dataframes = [
        df.value for df in at.dataframe if "Curve" in getattr(df.value, "columns", [])
    ]
    assert meta_dataframes, "expected the official response-curve summary to render"
    assert meta_dataframes[0]["Curve"].iloc[0] == "Approved response curve"
    assert any("NewSegment" in (markdown.value or "") for markdown in at.markdown)


# ---------------------------------------------------------------------------
# Phase 6 UI overhaul: on-curve annotation (application.curve_annotations)
# gates monetary economics on curve_type - a model-input official curve
# artifact must never show monetary CPA/ROI, a monetary one may (see
# test_official_curve_generation_page_apptest.py for the generation-time
# gate; these two tests exercise the *display* gate on this page).
# ---------------------------------------------------------------------------


def _write_annotated_artifact(store_dir: Path, approval_dict: dict, *, curve_type: str):
    artifact_id = f"art-annotated-{curve_type}"
    metadata = CurveArtifactMetadata(
        artifact_id=artifact_id,
        creation_timestamp="2026-07-01T00:00:00+00:00",
        model_identity_snapshot={
            "model_run_id": approval_dict["model_run_id"],
            "data_fingerprint": approval_dict["data_fingerprint"],
            "model_spec_fingerprint": approval_dict["model_spec_fingerprint"],
            "posterior_fingerprint": approval_dict["posterior_fingerprint"],
        },
        outcome_definition_snapshot={
            "outcome_id": "New",
            "definition_version": "1.0",
        },
        outcome_approval_snapshot={
            "approval_id": "apr-official-1",
            "allowed_uses": ["curve_publication", "headline_reporting"],
        },
        activity_governance_snapshot={
            "activities": ["tv-paid"],
            "fingerprint": activity_definitions_fingerprint(
                [ActivityDefinition.from_dict(_official_activity_dict())]
            ),
        },
        support_snapshot={
            "rows": [
                {
                    "market": "UK",
                    "channel": "TV_Brand",
                    "current": 100.0,
                    "observed_min": 0.0,
                    "observed_max": 300.0,
                    "is_extrapolated": False,
                }
            ]
        },
    )
    metadata = dataclasses.replace(
        metadata, fingerprints=dict(compute_curve_artifact_fingerprints(metadata))
    )
    draws = pd.DataFrame(
        {
            "model_run_id": [approval_dict["model_run_id"]] * 4,
            "reference_context_id": ["ref-official"] * 4,
            "market": ["UK"] * 4,
            "product": ["Family History"] * 4,
            "segment": ["New"] * 4,
            "outcome_id": ["New"] * 4,
            "metric_key": ["GSA"] * 4,
            "channel": ["TV_Brand"] * 4,
            "component_type": ["media"] * 4,
            "pathway_role": ["direct"] * 4,
            "curve_type": [curve_type] * 4,
            "spend_point": [0.0, 100.0, 200.0, 300.0],
            "local_spend": [0.0, 100.0, 200.0, 300.0],
            "posterior_draw": [0] * 4,
            "incremental_response": [0.0, 2.0, 3.0, 3.5],
            "planning_support_eligible": [True] * 4,
            "planning_blocked_reason": [""] * 4,
        }
    )
    summaries = draws.drop(
        columns=[
            "local_spend",
            "posterior_draw",
            "incremental_response",
            "planning_support_eligible",
            "planning_blocked_reason",
        ]
    ).drop_duplicates()
    summaries["average_cpa"] = 12.5
    summaries["marginal_cpa"] = 15.0
    write_curve_artifact(store_dir, metadata=metadata, draws=draws, summaries=summaries)
    return artifact_id


def test_model_input_official_curve_blocks_monetary_annotation(monkeypatch, tmp_path):
    """A model-input official artifact (curve_type='model_input') must never
    annotate the curve with monetary CPA/ROI, even though the artifact's own
    summaries table carries average_cpa/marginal_cpa columns - curve_type is
    the sole governing signal (pages/AGENTS.md Curve UI rule)."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_artifact_governance(at)
    _patch_store_root(monkeypatch, tmp_path)
    store_dir = Path(tmp_path) / "test-project"
    _write_annotated_artifact(
        store_dir, at.session_state["model_approval"], curve_type="model_input"
    )
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("monetary CPA/ROI is not shown" in (c.value or "") for c in at.caption)


def test_monetary_official_curve_does_not_show_blocked_caption(monkeypatch, tmp_path):
    """A monetary official artifact (a governed cost mapping was applied at
    generation time) must not show the model-input monetary-blocked caption
    - its economics are drawn directly onto the chart annotation instead."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_official_artifact_governance(at)
    _patch_store_root(monkeypatch, tmp_path)
    store_dir = Path(tmp_path) / "test-project"
    _write_annotated_artifact(
        store_dir, at.session_state["model_approval"], curve_type="monetary"
    )
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert not any(
        "monetary CPA/ROI is not shown" in (c.value or "") for c in at.caption
    )


def test_channel_viewer_selector_uses_governed_activity_label_display_only():
    """UI-WP7: the channel response-curve viewer's selector must prefer the
    governed activity's reporting channel over the raw model-input column
    name, while the underlying selected value used to drive the curve
    computation remains the raw column (`meta.channels` entry) - display
    only, never a persisted/identity change."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(
        at,
        activities=[
            ActivityDefinition(
                activity_id="tv-paid",
                channel="Linear_TV",
                activity_ownership="paid",
                model_role="intervention",
                economic_treatment="paid_media_cost",
                planning_eligibility="optimisable",
                source="media plan",
                model_input_column="TV_Brand",
            )
        ],
    )
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    channel_boxes = [box for box in at.selectbox if box.label == "Channel"]
    assert channel_boxes, "expected a Channel selector on the curve viewer"
    for box in channel_boxes:
        assert "Linear TV" in box.options
        assert "TV_Brand" not in box.options
        # The raw model-input column name remains the actual selected value
        # driving computation - only its displayed label changed.
        assert box.value == "TV_Brand"


def test_results_dashboard_separates_summary_and_exploratory_curve_context():
    """Phase 5: the results page surfaces the decision context before the
    detailed tables while keeping exploratory curves distinct from official
    artifacts (implementation brief, Results & Response Curves)."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_consistent_session_state(at)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    markdown = [m.value or "" for m in at.markdown]
    captions = [c.value or "" for c in at.caption]
    assert any("Results dashboard" in text for text in markdown)
    assert any("Contribution summary" in text for text in markdown)
    assert any("Exploratory response curves" in text for text in markdown)
    assert any("Approved response curves" in text for text in markdown)
    assert any(
        "exploratory evidence" in text and "approved response curves" in text
        for text in captions
    )
    assert not any("core.pathways" in text for text in captions)
    scope_selectors = [box for box in at.selectbox if box.label == "Outcome view"]
    assert scope_selectors, "expected contribution waterfall outcome selectors"
    assert all(
        any(
            "Family History · New · GSA (definition 1.0)" in str(option)
            for option in box.options
        )
        for box in scope_selectors
    )
    metric_labels = {metric.label for metric in at.metric}
    assert all(
        any(
            "Business total" in str(option) and "Total Family History" in str(option)
            for option in box.options
        )
        for box in scope_selectors
    )
    assert {
        "Fit state",
        "Model type",
        "Markets in fit",
        "Outcomes in fit",
    } <= metric_labels
