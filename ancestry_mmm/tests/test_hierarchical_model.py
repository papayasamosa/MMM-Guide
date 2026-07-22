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
"""

import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta, _resolve_direct_dna_outcome_ids


def _meta(**overrides) -> FHModelMeta:
    defaults = dict(
        markets=["UK"], outcome_ids=["fh_new", "fh_dna_crosssell", "fh_winback"], channels=["TV", "DNA_Media"],
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_outcome_id="fh_dna_crosssell", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
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
        meta = _meta(direct_dna_outcome_ids=["fh_dna_crosssell", "dna_new_kit"], outcome_ids=["fh_new", "fh_dna_crosssell", "fh_winback", "dna_new_kit"])
        assert set(meta.halo_eligible_outcome_ids) == {"fh_new", "fh_dna_crosssell", "fh_winback"}
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

        pathway = MediaOutcomePathway(channel="DNA_Media", source_product="DNA", target_outcome_id="dna_new_kit")
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
        from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model

        source_a = inspect.getsource(build_fh_hierarchical_model)
        source_c = inspect.getsource(build_fh_market_specific_model)

        for field_expr in (
            "outcome_id_to_metric_key={o.outcome_id: o.metric_key for o in outcome_catalogue},",
            "outcome_id_to_eligibility={o.outcome_id: outcome_eligibility(o) for o in outcome_catalogue},",
            "pathway_catalogue_at_fit=pathway_catalogue,",
            "pathway_masks=pathway_masks,",
        ):
            assert field_expr in source_a, f"Model A missing: {field_expr}"
            assert field_expr in source_c, f"Model C missing: {field_expr}"

    def test_both_builders_resolve_pathway_masks_identically(self):
        """PR G1 required test case: "Model A and Model C parity" for the
        operational pathway masking itself - both builders must call
        resolve_pathway_masks with the same arguments and derive the same
        primary/active/exploratory masks from beta before summing over
        channels, not just share the metadata-population lines checked
        above."""
        import inspect

        from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
        from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model

        source_a = inspect.getsource(build_fh_hierarchical_model)
        source_c = inspect.getsource(build_fh_market_specific_model)

        for field_expr in (
            "pathway_masks = resolve_pathway_masks(",
            "outcome_ids, channels, pathway_catalogue,",
            "dna_channel_idx=dna_channel_idx, dna_outcome_id=dna_outcome_id,",
            "direct_dna_outcome_ids=direct_dna_outcome_ids, dna_lag_weeks=dna_lag_weeks,",
            "primary_mask = pt.constant(pathway_masks.primary_matrix(outcome_ids, channels))",
            "active_cells = pathway_masks.active_cells(outcome_ids, channels)",
            "exploratory_cells = pathway_masks.exploratory_cells(outcome_ids, channels)",
            'prior_config.get("active_cross_product_sigma", 0.25)',
            'prior_config.get("exploratory_cross_product_sigma", 0.08)',
        ):
            assert field_expr in source_a, f"Model A missing: {field_expr}"
            assert field_expr in source_c, f"Model C missing: {field_expr}"


class TestResolveDirectDnaOutcomeIds:
    OUTCOME_IDS = ["fh_new", "fh_dna_crosssell", "fh_winback", "dna_new_kit", "dna_existing_fh_kit"]

    def test_none_defaults_to_just_dna_outcome_id(self):
        assert _resolve_direct_dna_outcome_ids(self.OUTCOME_IDS, "fh_dna_crosssell", None) == ["fh_dna_crosssell"]

    def test_dna_outcome_id_is_always_included_even_if_omitted_from_the_explicit_list(self):
        resolved = _resolve_direct_dna_outcome_ids(self.OUTCOME_IDS, "fh_dna_crosssell", ["dna_new_kit"])
        assert set(resolved) == {"fh_dna_crosssell", "dna_new_kit"}

    def test_explicit_list_already_containing_dna_outcome_id_is_not_duplicated(self):
        resolved = _resolve_direct_dna_outcome_ids(
            self.OUTCOME_IDS, "fh_dna_crosssell", ["fh_dna_crosssell", "dna_new_kit", "dna_existing_fh_kit"],
        )
        assert resolved.count("fh_dna_crosssell") == 1
        assert set(resolved) == {"fh_dna_crosssell", "dna_new_kit", "dna_existing_fh_kit"}

    def test_unknown_outcome_id_raises(self):
        with pytest.raises(ValueError, match="unknown outcome_id"):
            _resolve_direct_dna_outcome_ids(self.OUTCOME_IDS, "fh_dna_crosssell", ["Not A Real Outcome"])
