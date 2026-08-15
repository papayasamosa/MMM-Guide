"""REQ-SEARCH-002 Candidate A engine and fail-closed governance tests."""

import numpy as np
import pytest

from ancestry_mmm.core.causal_graph import (
    EDGE_ROLE_CAPACITY_CONSTRAINED,
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_MEDIATED,
    GRAPH_STATUS_APPROVED,
    NODE_ROLE_CAPACITY_OR_CAP,
    NODE_ROLE_DEMAND_CAPTURE,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_OUTCOME,
    CausalEdge,
    CausalGraph,
    CausalNode,
    validate_causal_graph,
)
from ancestry_mmm.core.graph_model_compiler import (
    GraphModelCompiler,
    candidate_a_graph_issues,
    check_engine_capability,
)
from ancestry_mmm.core.search_capacity import (
    CANDIDATE_A_CAPTURE_SHARE_COMPONENTS,
    SEARCH_CANDIDATE_A_ENGINE,
    SearchCandidateASpec,
    SearchCapacityValidationError,
    build_candidate_a_search_model,
    candidate_a_forward,
    candidate_a_use_gate,
    counterfactual_search_effects,
    extract_candidate_a_search_posterior_summary,
    identify_candidate_a_search,
    posterior_outputs_from_forward_draws,
    validate_candidate_a_spec,
)
from ancestry_mmm.core.search_objects import (
    SEARCH_ROLE_DEMAND,
    SEARCH_ROLE_DIRECT_NAV_CAPTURE,
    SEARCH_ROLE_ORGANIC_CAPTURE,
    SEARCH_ROLE_PAID_CAP,
    SEARCH_ROLE_PAID_DELIVERY,
    SEARCH_ROLE_PAID_SPEND,
    UNIT_EXPOSURE_COUNT,
    UNIT_INDEX,
    UNIT_MONETARY,
    UNIT_RESPONSE_COUNT,
    SearchObjectDefinition,
)


def _search_objects() -> list[SearchObjectDefinition]:
    common = dict(
        market="UK",
        state="observed",
        approval_status="approved",
        approved_by="test",
        approved_at="2026-08-15",
    )
    return [
        SearchObjectDefinition(
            search_object_id="demand",
            search_role=SEARCH_ROLE_DEMAND,
            source_column="search_demand",
            unit=UNIT_INDEX,
            **common,
        ),
        SearchObjectDefinition(
            search_object_id="spend",
            search_role=SEARCH_ROLE_PAID_SPEND,
            source_column="paid_spend",
            unit=UNIT_MONETARY,
            currency="GBP",
            channel="paid-search",
            planning_eligibility="optimisable",
            **common,
        ),
        SearchObjectDefinition(
            search_object_id="delivery",
            search_role=SEARCH_ROLE_PAID_DELIVERY,
            source_column="paid_delivery",
            unit=UNIT_EXPOSURE_COUNT,
            channel="paid-search",
            **common,
        ),
        SearchObjectDefinition(
            search_object_id="cap",
            search_role=SEARCH_ROLE_PAID_CAP,
            source_column="paid_cap",
            unit=UNIT_EXPOSURE_COUNT,
            channel="paid-search",
            **common,
        ),
        SearchObjectDefinition(
            search_object_id="organic",
            search_role=SEARCH_ROLE_ORGANIC_CAPTURE,
            source_column="organic_capture",
            unit=UNIT_RESPONSE_COUNT,
            **common,
        ),
        SearchObjectDefinition(
            search_object_id="direct",
            search_role=SEARCH_ROLE_DIRECT_NAV_CAPTURE,
            source_column="direct_capture",
            unit=UNIT_RESPONSE_COUNT,
            **common,
        ),
    ]


def _spec(**changes) -> SearchCandidateASpec:
    values = dict(
        outcome_definition_id="fh_new_sign_up_v1",
        outcome_definition_version="1",
        outcome_definition_fingerprint="outcome-fingerprint",
        market_scope="UK",
        demand_object_id="demand",
        paid_spend_object_id="spend",
        paid_delivery_object_id="delivery",
        paid_cap_object_id="cap",
        organic_capture_object_id="organic",
        direct_navigation_object_id="direct",
        cap_provenance="observed_platform",
        cap_provenance_status="resolved",
    )
    values.update(changes)
    return SearchCandidateASpec(**values)


def _candidate_graph() -> CausalGraph:
    nodes = [
        CausalNode(node_id="tv", role=NODE_ROLE_INTERVENTION),
        CausalNode(
            node_id="demand", role=NODE_ROLE_DEMAND_CAPTURE, search_object_id="demand"
        ),
        CausalNode(
            node_id="cap", role=NODE_ROLE_CAPACITY_OR_CAP, search_object_id="cap"
        ),
        CausalNode(
            node_id="organic", role=NODE_ROLE_DEMAND_CAPTURE, search_object_id="organic"
        ),
        CausalNode(
            node_id="direct", role=NODE_ROLE_DEMAND_CAPTURE, search_object_id="direct"
        ),
        CausalNode(node_id="outcome", role=NODE_ROLE_OUTCOME),
    ]
    edges = [
        CausalEdge(
            source_node_id="tv", target_node_id="demand", role=EDGE_ROLE_MEDIATED
        ),
        CausalEdge(
            source_node_id="demand", target_node_id="outcome", role=EDGE_ROLE_MEDIATED
        ),
        CausalEdge(
            source_node_id="demand",
            target_node_id="cap",
            role=EDGE_ROLE_CAPACITY_CONSTRAINED,
        ),
        CausalEdge(
            source_node_id="organic", target_node_id="outcome", role=EDGE_ROLE_DIRECT
        ),
        CausalEdge(
            source_node_id="direct", target_node_id="outcome", role=EDGE_ROLE_DIRECT
        ),
        CausalEdge(
            source_node_id="tv", target_node_id="outcome", role=EDGE_ROLE_DIRECT
        ),
    ]
    return CausalGraph(
        graph_id="candidate-a",
        status=GRAPH_STATUS_APPROVED,
        nodes=nodes,
        edges=edges,
    )


def test_candidate_a_reconciles_and_nonbinding_cap_raise_is_invariant():
    state = candidate_a_forward(
        [100.0, 120.0],
        paid_capture_share=0.5,
        organic_capture_share=0.2,
        direct_navigation_capture_share=0.1,
        paid_search_cap=[100.0, 10.0],
    )
    raised = candidate_a_forward(
        [100.0, 120.0],
        paid_capture_share=0.5,
        organic_capture_share=0.2,
        direct_navigation_capture_share=0.1,
        paid_search_cap=[1000.0, 10.0],
    )
    assert np.allclose(
        state.total_captured_demand + state.unmet_demand,
        state.latent_branded_search_demand,
    )
    assert np.allclose(
        state.realised_paid_search_delivery[0], raised.realised_paid_search_delivery[0]
    )
    assert np.allclose(state.total_captured_demand[0], raised.total_captured_demand[0])
    assert np.all(state.realised_paid_search_delivery <= np.array([100.0, 10.0]) + 1e-9)


def test_candidate_a_rejects_capture_shares_that_double_count_demand():
    with pytest.raises(ValueError, match="cannot exceed latent demand"):
        candidate_a_forward([100.0], 0.6, 0.3, 0.2, [100.0])


def test_candidate_a_identification_gate_fails_closed_without_cap_support():
    cap = np.full(20, 100.0)
    report = identify_candidate_a_search(
        cap,
        np.full(20, 50.0),
        cap_provenance="observed_platform",
    )
    assert report.official_eligible is False
    assert any("cap variation" in reason for reason in report.blocking_reasons)


def test_candidate_a_identification_gate_fails_closed_for_sparse_market():
    cap = np.tile([50.0, 100.0, 150.0, 100.0], 4)
    delivery = np.tile([50.0, 60.0, 150.0, 70.0], 4)
    report = identify_candidate_a_search(
        cap,
        delivery,
        market_labels=["UK"] * 16 + ["DE"] * 0,
        cap_provenance="observed_platform",
        min_periods_per_market=20,
    )
    assert report.official_eligible is False
    assert any("market support" in reason for reason in report.blocking_reasons)


def test_candidate_a_spec_requires_separate_governed_objects_and_keeps_use_closed():
    assert validate_candidate_a_spec(_spec(), _search_objects()) == ()
    assert validate_candidate_a_spec(
        _spec(paid_delivery_object_id="demand"), _search_objects()
    )
    identification = identify_candidate_a_search(
        np.tile([50.0, 100.0, 150.0, 100.0], 13),
        np.tile([50.0, 60.0, 150.0, 70.0], 13),
        cap_provenance="observed_platform",
    )
    gate = candidate_a_use_gate(_spec(), identification)
    assert gate.engine_available is True
    assert gate.planning_eligible is False
    assert gate.optimisation_eligible is False
    assert gate.official_use_eligible is False


def test_candidate_a_effects_are_outcome_scale_and_reconcile_before_summary():
    effects = counterfactual_search_effects(
        np.array([[130.0, 140.0]]),
        np.array([[120.0, 125.0]]),
        np.array([[100.0, 100.0]]),
        np.array([[150.0, 160.0]]),
    )
    assert np.allclose(
        effects.total_realised_media_effect,
        effects.direct_media_effect + effects.realised_mediated_search_effect,
    )
    assert np.all(effects.unrealised_potential > 0)


def test_candidate_a_posterior_outputs_keep_unmet_and_unrealised_separate():
    states = [
        candidate_a_forward([100.0, 110.0], 0.5, 0.2, 0.1, [30.0, 100.0]),
        candidate_a_forward([102.0, 108.0], 0.5, 0.2, 0.1, [32.0, 100.0]),
    ]
    effects = counterfactual_search_effects(
        [[130.0, 140.0], [132.0, 142.0]],
        [[120.0, 125.0], [121.0, 126.0]],
        [[100.0, 100.0], [101.0, 101.0]],
        [[150.0, 160.0], [152.0, 162.0]],
    )
    outputs = posterior_outputs_from_forward_draws(states, effects)
    assert outputs.probability_cap_binding[0] == pytest.approx(1.0)
    assert np.allclose(
        outputs.total_captured_demand + outputs.unmet_demand,
        outputs.latent_branded_search_demand,
    )
    assert np.all(outputs.unrealised_potential > 0)


def test_candidate_a_graph_is_the_only_new_engine_structure():
    graph = _candidate_graph()
    objects = _search_objects()
    assert validate_causal_graph(graph).is_valid
    assert check_engine_capability(graph, search_objects=objects)
    assert (
        check_engine_capability(
            graph, engine=SEARCH_CANDIDATE_A_ENGINE, search_objects=objects
        )
        == []
    )
    result = GraphModelCompiler(
        engine=SEARCH_CANDIDATE_A_ENGINE, search_objects=objects
    ).compile(graph)
    assert result.search_candidate_a is not None
    assert result.pathway_masks.primary_channels_by_outcome == {"outcome": ["tv"]}


def test_candidate_a_graph_rejects_another_mediated_structure():
    graph = _candidate_graph()
    graph.edges.append(
        CausalEdge(
            source_node_id="tv", target_node_id="organic", role=EDGE_ROLE_MEDIATED
        )
    )
    issues = candidate_a_graph_issues(graph, search_objects=_search_objects())
    assert any("outside the authorised" in issue for issue in issues)


def test_candidate_a_pymc_engine_exposes_required_posterior_deterministics():
    periods = np.arange(12, dtype=float)
    model = build_candidate_a_search_model(
        upstream_media=40.0 + periods,
        paid_search_delivery=np.full(12, 20.0),
        paid_search_cap=np.full(12, 30.0),
        organic_search_capture=np.full(12, 15.0),
        direct_navigation_capture=np.full(12, 10.0),
        final_outcome=np.full(12, 240.0),
        outcome_definition_id="fh_new_sign_up_v1",
        outcome_definition_version="1",
        outcome_definition_fingerprint="fingerprint",
    )
    required = {
        "latent_branded_search_demand",
        "unconstrained_paid_search_opportunity",
        "realised_paid_search_delivery",
        "organic_capture",
        "direct_navigation_capture",
        "total_captured_demand",
        "unmet_demand",
        "probability_cap_binding",
        "unused_capacity",
        "direct_media_effect",
        "realised_mediated_search_effect",
        "total_realised_media_effect",
        "unrealised_potential",
    }
    assert required.issubset(model.named_vars)
    assert model._candidate_a_metadata["planning_eligible"] is False
    assert model._candidate_a_metadata["optimisation_eligible"] is False


class TestExtractCandidateASearchPosteriorSummary:
    """WP3 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`):
    posterior-evidence extraction for a fitted Candidate A trace. Builds a
    synthetic `az.InferenceData` directly (rather than a real `pm.sample`
    fit - too slow for this suite, and covered by
    test_search_candidate_a_recovery_posterior.py's real NUTS fits) with
    the exact variable/coord shapes `attach_candidate_a_demand_capture_chain`
    produces, so the extraction/indexing logic itself is tested without
    MCMC cost."""

    @staticmethod
    def _fake_trace(n_obs=6, outcome_ids=("fh_new",), demand_channels=("SearchBrand",)):
        import arviz as az

        n_chain, n_draw = 2, 5
        rng = np.random.default_rng(0)
        n_outcome = len(outcome_ids)

        demand = np.abs(rng.normal(50, 5, size=(n_chain, n_draw, n_obs)))
        paid_opportunity = demand * 0.4
        organic = demand * 0.3
        direct = demand * 0.2
        cap = np.full((n_chain, n_draw, n_obs), 1000.0)
        realised_paid = np.minimum(paid_opportunity, cap)
        captured = organic + direct + realised_paid
        unmet = demand - captured

        posterior = {
            "search_demand_market_pool_sigma": rng.normal(0.3, 0.05, (n_chain, n_draw)),
            "search_demand_market_raw": rng.normal(0, 1, (n_chain, n_draw, 1)),
            "search_demand_market_offset": rng.normal(0, 0.1, (n_chain, n_draw, 1)),
            "search_demand_intercept": rng.normal(2.0, 0.1, (n_chain, n_draw)),
            "search_demand_media_beta": np.abs(
                rng.normal(0.4, 0.05, (n_chain, n_draw, len(demand_channels)))
            ),
            "search_latent_branded_demand": demand,
            "search_capture_shares": np.abs(
                rng.normal(0.25, 0.02, (n_chain, n_draw, 4))
            ),
            "search_unconstrained_paid_opportunity": paid_opportunity,
            "search_realised_paid_delivery": realised_paid,
            "search_organic_capture_expected": organic,
            "search_direct_navigation_capture_expected": direct,
            "search_total_captured_demand": captured,
            "search_unmet_demand": unmet,
            "search_cap_binding_probability": np.zeros((n_chain, n_draw, n_obs)),
            "search_unused_capacity": cap - realised_paid,
            "search_paid_delivery_observation_sigma": np.abs(
                rng.normal(2, 0.5, (n_chain, n_draw))
            ),
            "search_capture_observation_sigma": np.abs(
                rng.normal(2, 0.5, (n_chain, n_draw))
            ),
            "search_paid_capture_outcome_beta": np.abs(
                rng.normal(0.4, 0.05, (n_chain, n_draw, n_outcome))
            ),
            "search_organic_capture_outcome_beta": np.abs(
                rng.normal(0.3, 0.05, (n_chain, n_draw, n_outcome))
            ),
            "search_direct_navigation_capture_outcome_beta": np.abs(
                rng.normal(0.3, 0.05, (n_chain, n_draw, n_outcome))
            ),
            "search_eta_contribution": rng.normal(
                0, 0.1, (n_chain, n_draw, n_obs, n_outcome)
            ),
        }
        dims = {
            "search_demand_market_raw": ["market"],
            "search_demand_market_offset": ["market"],
            "search_demand_media_beta": ["search_demand_channel"],
            "search_latent_branded_demand": ["obs"],
            "search_capture_shares": ["search_capture_share_component"],
            "search_unconstrained_paid_opportunity": ["obs"],
            "search_realised_paid_delivery": ["obs"],
            "search_organic_capture_expected": ["obs"],
            "search_direct_navigation_capture_expected": ["obs"],
            "search_total_captured_demand": ["obs"],
            "search_unmet_demand": ["obs"],
            "search_cap_binding_probability": ["obs"],
            "search_unused_capacity": ["obs"],
            "search_paid_capture_outcome_beta": ["outcome"],
            "search_organic_capture_outcome_beta": ["outcome"],
            "search_direct_navigation_capture_outcome_beta": ["outcome"],
            "search_eta_contribution": ["obs", "outcome"],
        }
        coords = {
            "market": ["MKT0"],
            "search_demand_channel": list(demand_channels),
            "search_capture_share_component": list(
                CANDIDATE_A_CAPTURE_SHARE_COMPONENTS
            ),
            "obs": list(range(n_obs)),
            "outcome": list(outcome_ids),
        }
        return az.from_dict(posterior=posterior, coords=coords, dims=dims)

    def test_extracts_summary_with_correct_shapes_and_reconciliation(self):
        trace = self._fake_trace()
        summary = extract_candidate_a_search_posterior_summary(
            trace, outcome_ids=["fh_new"]
        )
        assert summary.demand_channel_names == ["SearchBrand"]
        assert set(summary.demand_media_beta_mean) == {"SearchBrand"}
        assert set(summary.capture_share_mean) == {"paid", "organic", "direct", "unmet"}
        assert set(summary.paid_capture_outcome_beta) == {"fh_new"}
        # Reconciliation holds by construction in the synthetic trace above.
        assert summary.reconciliation_max_abs_error < 1e-6
        assert summary.cap_binding_probability_mean == pytest.approx(0.0)
        assert np.isfinite(summary.rhat_max)
        assert np.isfinite(summary.ess_bulk_min)

    def test_raises_on_a_trace_missing_candidate_a_variables(self):
        import arviz as az

        ordinary_trace = az.from_dict(
            posterior={"beta": np.zeros((1, 2, 1, 1))},
            dims={"beta": ["outcome", "channel"]},
            coords={"outcome": ["fh_new"], "channel": ["TV"]},
        )
        with pytest.raises(SearchCapacityValidationError):
            extract_candidate_a_search_posterior_summary(
                ordinary_trace, outcome_ids=["fh_new"]
            )
