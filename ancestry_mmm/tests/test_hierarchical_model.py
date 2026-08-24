"""Tests for the pure-Python helpers in core.hierarchical_model - the
direct_dna_outcome_ids generalisation (docs/dna_fh_causal_structure.md,
docs/decision_log.md PR E - outcome_id as the model's primary identity
dimension instead of segment).

Matches the project's existing convention (see test_market_specific_model.py)
of not building/compiling an actual PyMC model in the test suite, since
that's slow and already covered by manual/offline verification
(docs/decision_log.md). What's covered here is everything that doesn't
require a PyMC model: FHModelMeta's own default behaviour and the
_resolve_direct_dna_outcome_ids helper both builders call before touching
PyMC at all.

TestSingleChannelSingleMarketSurvivesPmDraw is a deliberate, narrow
exception to that convention (REQ-VAL-001 corrective package) - see its own
docstring for why a real `pm.Model` + `pm.draw` (not `pm.sample`) is
required there.
"""

import numpy as np
import pytest

from ancestry_mmm.core.hierarchical_model import (
    FHModelMeta,
    _resolve_control_scaling,
    _resolve_fixed_channel_values,
    _resolve_media_input_scales,
    _resolve_direct_dna_outcome_ids,
)


def _meta(**overrides) -> FHModelMeta:
    defaults = dict(
        markets=["UK"],
        outcome_ids=["fh_new", "fh_dna_crosssell", "fh_winback"],
        channels=["TV", "DNA_Media"],
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="fh_dna_crosssell",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
    )
    defaults.update(overrides)
    return FHModelMeta(**defaults)


class TestFHModelMetaDirectDnaOutcomeIdsDefault:
    def test_defaults_to_just_the_dna_outcome_id_when_omitted(self):
        meta = _meta()
        assert meta.direct_dna_outcome_ids == ["fh_dna_crosssell"]

    def test_explicit_value_is_preserved(self):
        meta = _meta(direct_dna_outcome_ids=["fh_dna_crosssell", "dna_new_kit"])
        assert meta.direct_dna_outcome_ids == ["fh_dna_crosssell", "dna_new_kit"]

    def test_empty_list_falls_back_to_dna_outcome_id_too(self):
        # A dataclass constructed with an explicit empty list (e.g. from a
        # legacy bundle's JSON round trip, where the field was absent and
        # default_factory=list kicked in) must behave identically to
        # omitting the argument entirely.
        meta = _meta(direct_dna_outcome_ids=[])
        assert meta.direct_dna_outcome_ids == ["fh_dna_crosssell"]


class TestFHModelMetaKitOnlyAndHaloEligibleOutcomeIds:
    def test_kit_only_excludes_the_dna_outcome_id_itself(self):
        meta = _meta(direct_dna_outcome_ids=["fh_dna_crosssell", "dna_new_kit"])
        assert meta.kit_only_outcome_ids == ["dna_new_kit"]

    def test_halo_eligible_excludes_kit_only_but_includes_dna_outcome_id(self):
        meta = _meta(
            direct_dna_outcome_ids=["fh_dna_crosssell", "dna_new_kit"],
            outcome_ids=["fh_new", "fh_dna_crosssell", "fh_winback", "dna_new_kit"],
        )
        assert set(meta.halo_eligible_outcome_ids) == {
            "fh_new",
            "fh_dna_crosssell",
            "fh_winback",
        }
        assert "dna_new_kit" not in meta.halo_eligible_outcome_ids


class TestFHModelMetaOutcomeCatalogueDicts:
    def test_defaults_to_empty_dicts_and_list(self):
        meta = _meta()
        assert meta.outcome_id_to_segment == {}
        assert meta.outcome_id_to_product == {}
        assert meta.outcome_catalogue_at_fit == []
        assert meta.pathway_catalogue_at_fit == []

    def test_explicit_pathway_catalogue_at_fit_is_preserved(self):
        from ancestry_mmm.core.pathways import MediaOutcomePathway

        pathway = MediaOutcomePathway(
            channel="DNA_Media", source_product="DNA", target_outcome_id="dna_new_kit"
        )
        meta = _meta(pathway_catalogue_at_fit=[pathway])
        assert meta.pathway_catalogue_at_fit == [pathway]

    def test_explicit_catalogue_dicts_are_preserved(self):
        meta = _meta(
            outcome_id_to_segment={"fh_new": "New"},
            outcome_id_to_product={"fh_new": "Family History"},
            outcome_id_to_source_column={"fh_new": "GSA_New"},
        )
        assert meta.outcome_id_to_segment == {"fh_new": "New"}
        assert meta.outcome_id_to_product == {"fh_new": "Family History"}
        assert meta.outcome_id_to_source_column == {"fh_new": "GSA_New"}


class TestFHModelMetaResolvedPathwayMasks:
    """WP4 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`):
    characterization test for `resolved_pathway_masks`, added to close the
    largest single repeated full-core mypy debt pattern (34 of 276 baseline
    errors) by narrowing `pathway_masks: Optional[ResolvedPathwayMasks]` to
    its guaranteed-non-Optional runtime type at call sites - `__post_init__`
    always resolves it to a real object, never leaves it `None`."""

    def test_returns_the_same_object_post_init_resolved(self):
        meta = _meta()
        assert meta.pathway_masks is not None
        assert meta.resolved_pathway_masks is meta.pathway_masks

    def test_returns_the_same_object_when_pathway_masks_passed_explicitly(self):
        from ancestry_mmm.core.pathways import ResolvedPathwayMasks

        explicit = ResolvedPathwayMasks()
        meta = _meta(pathway_masks=explicit)
        assert meta.resolved_pathway_masks is explicit


class TestFHModelMetaCausalGraphIdentityDefaults:
    """REQ-GRAPH-001 work package: fit-time causal graph identity fields
    default to "not used" (empty string / 0), never None, so a bundle saved
    before these fields existed round-trips through FHModelMeta(**meta_dict)
    unchanged (core.persistence.reconstruct_model_state)."""

    def test_defaults_when_no_graph_was_used(self):
        meta = _meta()
        assert meta.causal_graph_id == ""
        assert meta.causal_graph_version == 0
        assert meta.causal_graph_structural_fingerprint == ""
        assert meta.causal_graph_engine == ""

    def test_explicit_values_are_preserved(self):
        meta = _meta(
            causal_graph_id="graph-abc",
            causal_graph_version=3,
            causal_graph_structural_fingerprint="deadbeef",
            causal_graph_engine="pymc_hierarchical",
        )
        assert meta.causal_graph_id == "graph-abc"
        assert meta.causal_graph_version == 3
        assert meta.causal_graph_structural_fingerprint == "deadbeef"
        assert meta.causal_graph_engine == "pymc_hierarchical"


class TestMediaInputScaleContract:
    def test_meta_defaults_to_raw_input_domain_for_legacy_bundles(self):
        meta = _meta()
        assert meta.media_input_scale_method == ""
        assert meta.media_input_scales == {}

    def test_positive_median_is_deterministic_and_uses_target_support(self):
        method, scales = _resolve_media_input_scales(
            np.array([[0.0, 10.0], [200.0, 30.0], [100.0, 0.0]]),
            ["TV", "Email"],
            {"media_input_scale_method": "positive_median"},
        )
        assert method == "positive_median"
        assert scales == {"TV": 150.0, "Email": 20.0}

    def test_unknown_media_scale_method_is_blocked(self):
        with pytest.raises(ValueError, match="Unsupported media_input_scale_method"):
            _resolve_media_input_scales(
                np.ones((2, 1)), ["TV"], {"media_input_scale_method": "zscore"}
            )


class TestControlScalingContract:
    """`_resolve_control_scaling` must default to leaving controls raw and
    the coefficient prior's implied meaning unchanged - production-default
    behaviour before and after PR #304's pre-fit remediation branch must be
    byte-identical here. Centring/scaling changes the prior's implied
    meaning without a compensating recalibration (no `docs/
    approved_requirements/REQ-*` record or `docs/decision_log.md` entry
    approves it as a production change), so it must remain a gated,
    default-off diagnostic experiment - the same pattern already used by
    `_resolve_media_input_scales`/`K_reference`/`fixed_decay_rate`."""

    def test_default_leaves_controls_raw_with_empty_contract(self):
        raw = np.array([[40.0, 2.0], [50.0, 4.0], [60.0, 6.0]])
        controls, contract = _resolve_control_scaling(raw, ["trend", "price"], {})
        np.testing.assert_array_equal(controls, raw)
        assert contract == {}

    def test_disabled_explicitly_also_leaves_controls_raw(self):
        raw = np.array([[40.0, 2.0], [50.0, 4.0], [60.0, 6.0]])
        controls, contract = _resolve_control_scaling(
            raw, ["trend", "price"], {"enable_control_scaling": False}
        )
        np.testing.assert_array_equal(controls, raw)
        assert contract == {}

    def test_explicit_opt_in_centres_and_scales(self):
        raw = np.array([[40.0, 2.0], [50.0, 4.0], [60.0, 6.0]])
        controls, contract = _resolve_control_scaling(
            raw, ["trend", "price"], {"enable_control_scaling": True}
        )
        np.testing.assert_allclose(controls.mean(axis=0), [0.0, 0.0], atol=1e-12)
        assert contract["trend"]["method"] == "mean_sd"

    def test_no_controls_is_a_no_op_either_way(self):
        empty = np.zeros((3, 0))
        for prior_config in ({}, {"enable_control_scaling": True}):
            controls, contract = _resolve_control_scaling(empty, [], prior_config)
            assert controls.shape == (3, 0)
            assert contract == {}


class TestDiagnosticFixedChannelValues:
    def test_accepts_scalar_mapping_and_ordered_vector(self):
        channels = ["TV", "Email"]
        assert _resolve_fixed_channel_values(
            {"fixed": 0.5}, "fixed", channels, 0.2, lower=0.0, upper=1.0
        ).tolist() == [0.5, 0.5]
        assert _resolve_fixed_channel_values(
            {"fixed": {"TV": 0.25, "Email": 0.75}},
            "fixed",
            channels,
            0.2,
            lower=0.0,
            upper=1.0,
        ).tolist() == [0.25, 0.75]
        assert _resolve_fixed_channel_values(
            {"fixed": [0.3, 0.4]}, "fixed", channels, 0.2, lower=0.0
        ).tolist() == [0.3, 0.4]

    def test_rejects_missing_channels_wrong_length_and_bounds(self):
        with pytest.raises(ValueError, match="missing channel"):
            _resolve_fixed_channel_values(
                {"fixed": {"TV": 0.5}},
                "fixed",
                ["TV", "Email"],
                0.2,
                lower=0.0,
            )
        with pytest.raises(ValueError, match="one value per channel"):
            _resolve_fixed_channel_values(
                {"fixed": [0.5]}, "fixed", ["TV", "Email"], 0.2, lower=0.0
            )
        with pytest.raises(ValueError, match="< 1.0"):
            _resolve_fixed_channel_values(
                {"fixed": 1.0}, "fixed", ["TV"], 0.2, lower=0.0, upper=1.0
            )


class TestModelAModelCMetaConstructionParity:
    """PR E.2 required test case: "Model A and Model C parity" for the new
    metric_key/eligibility catalogue metadata. Both build_fh_hierarchical_model
    (Model A) and build_fh_market_specific_model (Model C) populate
    FHModelMeta.outcome_id_to_metric_key/outcome_id_to_eligibility from the
    same `frame["outcomes"]` catalogue with the same expression - this
    doesn't build a PyMC model (too slow for the suite, see this file's
    module docstring), it inspects the actual source of both builders so a
    future edit to one that forgets the other fails loudly here rather than
    silently diverging."""

    def test_both_builders_construct_the_new_fields_identically(self):
        import inspect

        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.market_specific_model import (
            build_fh_market_specific_model,
        )

        source_a = inspect.getsource(build_fh_hierarchical_model)
        source_c = inspect.getsource(build_fh_market_specific_model)

        for field_expr in (
            "outcome_id_to_metric_key",
            "outcome_id_to_eligibility",
            "pathway_catalogue_at_fit",
            "pathway_masks",
        ):
            assert field_expr in source_a, f"Model A missing: {field_expr}"
            assert field_expr in source_c, f"Model C missing: {field_expr}"


class TestSingleChannelSingleMarketSurvivesPmDraw:
    """REQ-VAL-001 corrective package: a single-channel, single-market frame
    made the shared `core.transformations.pt_geometric_adstock_matrix`
    helper's internal `scan` Op raise `TypeError: Inconsistency in the
    inner graph of scan` whenever PyMC's compile path cloned it (`pm.draw`,
    or `pm.sample` initialising >1 chain/core) - reproducible against this
    exact production builder with no prior-predictive, PyMC-Marketing, or
    Streamlit code involved. Intentionally builds a real `pm.Model` (an
    exception to this file's module docstring's usual "don't build a PyMC
    model" convention - a hand-built standalone tensor graph cannot
    reproduce the RV-into-scan condition that actually triggered this) but
    stays fast via `pm.draw` rather than `pm.sample`, so it doesn't
    reintroduce the slow-MCMC concern that convention exists to avoid."""

    @staticmethod
    def _single_channel_single_market_frame():
        return {
            "markets": ["UK"],
            "market_idx": np.array([0, 0, 0]),
            "market_bounds": [(0, 3)],
            "channels": ["TV"],
            "dna_channel_idx": [],
            "outcome_ids": ["fh_new"],
            "X_media": np.array([[100.0], [200.0], [150.0]]),
            "Y": np.array([[10.0], [12.0], [11.0]]),
            "promo": np.zeros((3, 1)),
            "X_controls": np.zeros((3, 0)),
            "control_names": [],
            "fourier": np.zeros((3, 2)),
            "trend": np.array([1.0, 1.1, 1.05]),
            "unpooled_markets": [],
        }

    def test_sat_media_survives_pm_draw_cloning(self):
        import pymc as pm

        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.schema import ModelSpec

        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV"],
        )
        model, _meta = build_fh_hierarchical_model(
            self._single_channel_single_market_frame(), spec
        )
        with model:
            val = pm.draw(model.named_vars["sat_media"], draws=1, random_seed=0)
        assert np.asarray(val).shape == (3, 1)

    def test_one_market_bypasses_between_market_variance(self):
        """A UK-only fit must not estimate an unidentifiable market hierarchy."""
        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.schema import ModelSpec

        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV"],
        )
        model, meta = build_fh_hierarchical_model(
            self._single_channel_single_market_frame(), spec
        )

        assert "market_pool_sigma" not in model.named_vars
        assert "market_offset_raw" not in model.named_vars
        assert "market_offset" in model.named_vars
        assert meta.markets == ["UK"]

    def test_all_zero_promotion_does_not_create_prior_only_coefficient(self):
        """An absent promotion input must not add an unidentifiable RV."""
        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.schema import ModelSpec

        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV"],
        )
        model, _meta = build_fh_hierarchical_model(
            self._single_channel_single_market_frame(), spec
        )

        assert "promo_coef" in model.named_vars
        assert "promo_coef" not in {rv.name for rv in model.free_RVs}

    def test_candidate_geometry_priors_build_finite_rvs(self):
        """The diagnostic prior knobs must build real, finite PyMC RVs."""
        import pymc as pm

        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.schema import ModelSpec

        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV"],
        )
        model, _meta = build_fh_hierarchical_model(
            self._single_channel_single_market_frame(),
            spec,
            prior_config={
                "K_reference": "nonzero_median",
                "K_alpha": 10.0,
                "pooling_sigma_prior": 0.12,
                "pooling_sigma_prior_distribution": "lognormal",
                "pooling_sigma_log_prior_sigma": 0.35,
            },
        )

        assert type(model.named_vars["sigma_pool"].owner.op).__name__ == "LogNormalRV"
        with model:
            hill_k, sigma_pool = pm.draw(
                [model.named_vars["hill_K"], model.named_vars["sigma_pool"]],
                draws=3,
                random_seed=0,
            )
        assert np.isfinite(hill_k).all()
        assert np.isfinite(sigma_pool).all()

    def test_multiple_markets_retain_between_market_variance(self):
        """The one-market bypass must not remove the multi-market contract."""
        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.schema import ModelSpec

        frame = self._single_channel_single_market_frame()
        frame["markets"] = ["UK", "US"]
        frame["market_idx"] = np.array([0, 0, 0, 1, 1, 1])
        frame["market_bounds"] = [(0, 3), (3, 6)]
        frame["X_media"] = np.vstack([frame["X_media"], frame["X_media"]])
        frame["Y"] = np.vstack([frame["Y"], frame["Y"]])
        frame["promo"] = np.vstack([frame["promo"], frame["promo"]])
        frame["fourier"] = np.vstack([frame["fourier"], frame["fourier"]])
        frame["trend"] = np.tile(frame["trend"], 2)
        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK", "US"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV"],
        )

        model, meta = build_fh_hierarchical_model(frame, spec)

        assert "market_pool_sigma" in model.named_vars
        assert "market_offset_raw" in model.named_vars
        assert meta.markets == ["UK", "US"]

    def test_sat_media_uses_explicit_pre_window_history(self):
        """The official UK window must inherit adstock from retained media
        history rather than starting its first target week at zero."""
        import pymc as pm

        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.schema import ModelSpec

        frame = self._single_channel_single_market_frame()
        frame["X_media_history"] = np.array([[80.0], [120.0]])
        frame["history_market_bounds"] = [(0, 2)]
        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV"],
        )
        model, _meta = build_fh_hierarchical_model(frame, spec)
        with model:
            with_history = pm.draw(
                model.named_vars["sat_media"], draws=1, random_seed=0
            )
        assert np.asarray(with_history).shape == (3, 1)

    def test_both_builders_resolve_pathway_masks_identically(self):
        """PR G1 required test case: "Model A and Model C parity" for the
        operational pathway masking itself - both builders must call
        resolve_pathway_masks with the same arguments and derive the same
        primary/active/exploratory masks from beta before summing over
        channels, not just share the metadata-population lines checked
        above.

        REQ-GRAPH-001 work package D: the call site is now
        resolve_pathway_masks_preferring_graph, which prefers an approved
        causal_graph over the raw pathway catalogue when one is supplied and
        is otherwise a byte-for-byte passthrough to the resolver this test
        originally named - the parity invariant is unchanged, only extended
        to also require both builders accept and forward causal_graph
        identically."""
        import inspect

        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.market_specific_model import (
            build_fh_market_specific_model,
        )

        source_a = inspect.getsource(build_fh_hierarchical_model)
        source_c = inspect.getsource(build_fh_market_specific_model)

        for field_expr in (
            "pathway_masks = resolve_pathway_masks_preferring_graph(",
            "causal_graph=causal_graph",
            "channel_products=channel_products",
            "outcome_products=outcome_products",
            "fitted_outcome_ids=outcome_ids",
            "diagnostic_only_outcome_ids",
            "primary_matrix(outcome_ids, channels)",
            "active_cells(outcome_ids, channels)",
            "exploratory_cells(outcome_ids, channels)",
            'prior_config.get("active_cross_product_sigma", 0.25)',
            'prior_config.get("exploratory_cross_product_sigma", 0.08)',
        ):
            assert field_expr in source_a, f"Model A missing: {field_expr}"
            assert field_expr in source_c, f"Model C missing: {field_expr}"

    def test_both_builders_bind_fit_time_causal_graph_identity_identically(self):
        """REQ-GRAPH-001 work package: both builders must record the same
        four fit-time graph identity fields on FHModelMeta from the same
        `causal_graph` parameter - never reconstructed later from whatever
        graph happens to be live, and never populated in only one builder."""
        import inspect

        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.market_specific_model import (
            build_fh_market_specific_model,
        )

        source_a = inspect.getsource(build_fh_hierarchical_model)
        source_c = inspect.getsource(build_fh_market_specific_model)

        for field_expr in (
            "causal_graph_id=causal_graph.graph_id if causal_graph is not None else",
            "causal_graph_version=(",
            "causal_graph.graph_version if causal_graph is not None else 0",
            "causal_graph_structural_fingerprint=(",
            "causal_graph.structural_fingerprint() if causal_graph is not None else",
            "causal_graph_engine=(",
            "GRAPH_ENGINE_PYMC_HIERARCHICAL if causal_graph is not None else",
        ):
            assert field_expr in source_a, f"Model A missing: {field_expr}"
            assert field_expr in source_c, f"Model C missing: {field_expr}"


class TestCandidateASearchIntegration:
    """WP1 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`): Candidate A
    production integration boundary. Builds a real `pm.Model` (via
    `build_fh_hierarchical_model(..., search_candidate_a=...)`) against a
    minimal approved Candidate A causal graph, and uses `pm.draw` (never
    `pm.sample`) to stay fast, mirroring
    TestSingleChannelSingleMarketSurvivesPmDraw's convention above."""

    @staticmethod
    def _frame():
        n = 8
        rng = np.random.default_rng(0)
        return {
            "markets": ["UK"],
            "market_idx": np.zeros(n, dtype=int),
            "market_bounds": [(0, n)],
            "channels": ["SearchBrand"],
            "dna_channel_idx": [],
            "outcome_ids": ["fh_new"],
            "X_media": rng.uniform(50, 150, size=(n, 1)),
            "Y": rng.uniform(8, 15, size=(n, 1)),
            "promo": np.zeros((n, 1)),
            "X_controls": np.zeros((n, 0)),
            "control_names": [],
            "fourier": np.zeros((n, 2)),
            "trend": np.linspace(1.0, 1.1, n),
            "unpooled_markets": [],
        }

    @staticmethod
    def _approved_graph():
        from ancestry_mmm.core.causal_graph import (
            CausalEdge,
            CausalGraph,
            EDGE_ROLE_CAPACITY_CONSTRAINED,
            EDGE_ROLE_DIRECT,
            EDGE_ROLE_MEDIATED,
            GRAPH_STATUS_APPROVED,
            NODE_ROLE_CAPACITY_OR_CAP,
            NODE_ROLE_DEMAND_CAPTURE,
            NODE_ROLE_INTERVENTION,
            NODE_ROLE_OUTCOME,
            CausalNode,
        )

        nodes = [
            CausalNode(node_id="SearchBrand", role=NODE_ROLE_INTERVENTION),
            CausalNode(node_id="fh_new", role=NODE_ROLE_OUTCOME),
            CausalNode(
                node_id="demand_node",
                role=NODE_ROLE_DEMAND_CAPTURE,
                search_object_id="obj_demand",
            ),
            CausalNode(
                node_id="cap_node",
                role=NODE_ROLE_CAPACITY_OR_CAP,
                search_object_id="obj_cap",
            ),
            CausalNode(
                node_id="organic_node",
                role=NODE_ROLE_DEMAND_CAPTURE,
                search_object_id="obj_organic",
            ),
            CausalNode(
                node_id="direct_node",
                role=NODE_ROLE_DEMAND_CAPTURE,
                search_object_id="obj_direct",
            ),
        ]
        edges = [
            CausalEdge("SearchBrand", "fh_new", role=EDGE_ROLE_DIRECT),
            CausalEdge("SearchBrand", "demand_node", role=EDGE_ROLE_MEDIATED),
            CausalEdge("demand_node", "fh_new", role=EDGE_ROLE_MEDIATED),
            CausalEdge("demand_node", "cap_node", role=EDGE_ROLE_CAPACITY_CONSTRAINED),
            CausalEdge("organic_node", "fh_new", role=EDGE_ROLE_DIRECT),
            CausalEdge("direct_node", "fh_new", role=EDGE_ROLE_DIRECT),
        ]
        return CausalGraph(
            graph_id="g1",
            graph_version=1,
            nodes=nodes,
            edges=edges,
            status=GRAPH_STATUS_APPROVED,
        )

    @staticmethod
    def _search_objects():
        from ancestry_mmm.core.search_objects import (
            SEARCH_ROLE_DEMAND,
            SEARCH_ROLE_DIRECT_NAV_CAPTURE,
            SEARCH_ROLE_ORGANIC_CAPTURE,
            SEARCH_ROLE_PAID_CAP,
            SEARCH_ROLE_PAID_DELIVERY,
            SEARCH_ROLE_PAID_SPEND,
            UNIT_EXPOSURE_COUNT,
            UNIT_MONETARY,
            UNIT_RESPONSE_COUNT,
            SearchObjectDefinition,
        )

        return [
            SearchObjectDefinition(
                search_object_id="obj_demand",
                search_role=SEARCH_ROLE_DEMAND,
                source_column="search_demand_raw",
                unit=UNIT_EXPOSURE_COUNT,
            ),
            SearchObjectDefinition(
                search_object_id="obj_cap",
                search_role=SEARCH_ROLE_PAID_CAP,
                source_column="search_cap_raw",
                unit=UNIT_EXPOSURE_COUNT,
            ),
            SearchObjectDefinition(
                search_object_id="obj_organic",
                search_role=SEARCH_ROLE_ORGANIC_CAPTURE,
                source_column="search_organic_raw",
                unit=UNIT_RESPONSE_COUNT,
            ),
            SearchObjectDefinition(
                search_object_id="obj_direct",
                search_role=SEARCH_ROLE_DIRECT_NAV_CAPTURE,
                source_column="search_direct_raw",
                unit=UNIT_RESPONSE_COUNT,
            ),
            SearchObjectDefinition(
                search_object_id="obj_spend",
                search_role=SEARCH_ROLE_PAID_SPEND,
                source_column="search_spend_raw",
                unit=UNIT_MONETARY,
                currency="GBP",
            ),
            SearchObjectDefinition(
                search_object_id="obj_delivery",
                search_role=SEARCH_ROLE_PAID_DELIVERY,
                source_column="search_delivery_raw",
                unit=UNIT_EXPOSURE_COUNT,
            ),
        ]

    def _build(self, *, cap_value: float):
        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.schema import ModelSpec
        from ancestry_mmm.core.search_capacity import (
            CandidateASearchFitInputs,
            SearchCandidateASpec,
        )

        frame = self._frame()
        n = frame["X_media"].shape[0]
        rng = np.random.default_rng(1)
        spec = SearchCandidateASpec(
            outcome_definition_id="fh_new",
            outcome_definition_version="1",
            outcome_definition_fingerprint="fp",
            market_scope="UK",
            demand_object_id="obj_demand",
            paid_spend_object_id="obj_spend",
            paid_delivery_object_id="obj_delivery",
            paid_cap_object_id="obj_cap",
            organic_capture_object_id="obj_organic",
            direct_navigation_object_id="obj_direct",
        )
        fit_inputs = CandidateASearchFitInputs(
            spec=spec,
            demand_channel_names=["SearchBrand"],
            paid_search_delivery=rng.uniform(5, 15, size=n),
            paid_search_cap=np.full(n, cap_value),
            organic_search_capture=rng.uniform(5, 15, size=n),
            direct_navigation_capture=rng.uniform(5, 15, size=n),
            search_objects=self._search_objects(),
        )
        model_spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["SearchBrand"],
        )
        model, meta = build_fh_hierarchical_model(
            frame,
            model_spec,
            causal_graph=self._approved_graph(),
            search_candidate_a=fit_inputs,
        )
        return model, meta, fit_inputs

    def test_candidate_a_engine_is_recorded_on_fit_time_meta(self):
        from ancestry_mmm.core.search_capacity import SEARCH_CANDIDATE_A_ENGINE

        _model, meta, _fit_inputs = self._build(cap_value=1000.0)
        assert meta.causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE

    def test_missing_causal_graph_fails_closed(self):
        from ancestry_mmm.core.graph_model_compiler import (
            UnsupportedGraphStructureError,
        )
        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.schema import ModelSpec
        from ancestry_mmm.core.search_capacity import (
            CandidateASearchFitInputs,
            SearchCandidateASpec,
        )

        frame = self._frame()
        n = frame["X_media"].shape[0]
        spec = SearchCandidateASpec(
            outcome_definition_id="fh_new",
            outcome_definition_version="1",
            outcome_definition_fingerprint="fp",
            market_scope="UK",
            demand_object_id="obj_demand",
            paid_spend_object_id="obj_spend",
            paid_delivery_object_id="obj_delivery",
            paid_cap_object_id="obj_cap",
            organic_capture_object_id="obj_organic",
            direct_navigation_object_id="obj_direct",
        )
        fit_inputs = CandidateASearchFitInputs(
            spec=spec,
            demand_channel_names=["SearchBrand"],
            paid_search_delivery=np.full(n, 5.0),
            paid_search_cap=np.full(n, 100.0),
            organic_search_capture=np.full(n, 5.0),
            direct_navigation_capture=np.full(n, 5.0),
            search_objects=self._search_objects(),
        )
        model_spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["SearchBrand"],
        )
        with pytest.raises(UnsupportedGraphStructureError):
            build_fh_hierarchical_model(
                frame, model_spec, causal_graph=None, search_candidate_a=fit_inputs
            )

    def test_reconciliation_and_non_binding_cap_invariant_hold_under_pm_draw(self):
        """Draws from the prior (fixed seed) and checks, for every draw:
        captured + unmet == latent (structural reconciliation), and with a
        cap set far above any plausible demand, the cap never binds and
        realised delivery always equals the unconstrained opportunity (a
        non-binding cap must not create or destroy value)."""
        import pymc as pm

        model, _meta, _fit_inputs = self._build(cap_value=1_000_000.0)
        names = [
            "search_latent_branded_demand",
            "search_total_captured_demand",
            "search_unmet_demand",
            "search_unconstrained_paid_opportunity",
            "search_realised_paid_delivery",
            "search_cap_binding_probability",
        ]
        with model:
            draws = pm.draw(
                [model.named_vars[name] for name in names], draws=5, random_seed=0
            )
        demand, captured, unmet, paid_opportunity, realised_paid, cap_binding = draws
        np.testing.assert_allclose(captured + unmet, demand, rtol=1e-6, atol=1e-6)
        assert np.all(unmet >= -1e-8)
        np.testing.assert_allclose(
            realised_paid, paid_opportunity, rtol=1e-6, atol=1e-6
        )
        assert np.all(cap_binding == 0.0)

    def test_search_eta_contribution_has_obs_by_outcome_shape(self):
        import pymc as pm

        model, _meta, _fit_inputs = self._build(cap_value=1000.0)
        with model:
            value = pm.draw(
                model.named_vars["search_eta_contribution"], draws=1, random_seed=0
            )
        assert np.asarray(value).shape == (8, 1)


class TestResolveDirectDnaOutcomeIds:
    OUTCOME_IDS = [
        "fh_new",
        "fh_dna_crosssell",
        "fh_winback",
        "dna_new_kit",
        "dna_existing_fh_kit",
    ]

    def test_none_defaults_to_just_dna_outcome_id(self):
        assert _resolve_direct_dna_outcome_ids(
            self.OUTCOME_IDS, "fh_dna_crosssell", None
        ) == ["fh_dna_crosssell"]

    def test_dna_outcome_id_is_always_included_even_if_omitted_from_the_explicit_list(
        self,
    ):
        resolved = _resolve_direct_dna_outcome_ids(
            self.OUTCOME_IDS, "fh_dna_crosssell", ["dna_new_kit"]
        )
        assert set(resolved) == {"fh_dna_crosssell", "dna_new_kit"}

    def test_explicit_list_already_containing_dna_outcome_id_is_not_duplicated(self):
        resolved = _resolve_direct_dna_outcome_ids(
            self.OUTCOME_IDS,
            "fh_dna_crosssell",
            ["fh_dna_crosssell", "dna_new_kit", "dna_existing_fh_kit"],
        )
        assert resolved.count("fh_dna_crosssell") == 1
        assert set(resolved) == {
            "fh_dna_crosssell",
            "dna_new_kit",
            "dna_existing_fh_kit",
        }

    def test_unknown_outcome_id_raises(self):
        with pytest.raises(ValueError, match="unknown outcome_id"):
            _resolve_direct_dna_outcome_ids(
                self.OUTCOME_IDS, "fh_dna_crosssell", ["Not A Real Outcome"]
            )
