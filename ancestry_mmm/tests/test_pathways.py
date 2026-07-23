"""Tests for core.pathways - the explicit MediaOutcomePathway catalogue
(PR F) and outcome reconciliation groups. Schema/validation/fingerprint/
drift only - see module docstring for why no new model equations are
introduced here."""

from types import SimpleNamespace

import pytest

from ancestry_mmm.core.outcomes import DNA, FAMILY_HISTORY
from ancestry_mmm.core.pathways import (
    PATHWAY_DRIFT_STATUSES,
    PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
    PATHWAY_ROLE_EXCLUDED,
    PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT,
    PATHWAY_ROLE_PRIMARY_DIRECT,
    PATHWAY_ROLES,
    RECONCILIATION_RELATIONS,
    MediaOutcomePathway,
    OutcomeReconciliationGroup,
    ResolvedPathwayMasks,
    pathway_catalogue_at_fit_by_id,
    pathway_catalogue_fingerprint_payload,
    pathway_drift_status,
    pathways_drift_dataframe,
    reconciliation_group_diagnostics,
    resolve_pathway_masks,
    validate_media_outcome_pathways,
    validate_reconciliation_groups,
)


def _pathway(**overrides) -> MediaOutcomePathway:
    defaults = dict(
        channel="DNA_Media", source_product=DNA, target_outcome_id="dna_kit_sale_self_activated",
        role=PATHWAY_ROLE_PRIMARY_DIRECT,
    )
    defaults.update(overrides)
    return MediaOutcomePathway(**defaults)


class TestMediaOutcomePathwayRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        pathway = _pathway()
        restored = MediaOutcomePathway.from_dict(pathway.to_dict())
        assert restored == pathway

    def test_pathway_id_is_deterministic_for_natural_key(self):
        a, b = _pathway(), _pathway()
        assert a.pathway_id and b.pathway_id
        assert a.pathway_id == b.pathway_id

    def test_explicit_pathway_id_is_preserved(self):
        pathway = _pathway(pathway_id="fixed-id")
        assert pathway.pathway_id == "fixed-id"

    def test_defaults_match_a_primary_direct_pathway(self):
        pathway = _pathway()
        assert pathway.role == PATHWAY_ROLE_PRIMARY_DIRECT
        assert pathway.lag_type == "none"
        assert pathway.lag_weeks is None
        assert pathway.prior_scale == 1.0
        assert pathway.include_in_attribution is True
        assert pathway.include_in_planning is True
        assert pathway.evidence_status == "untested"


class TestPathwayRolesCoverRoadmapVocabulary:
    def test_all_four_roles_present(self):
        assert set(PATHWAY_ROLES) == {
            PATHWAY_ROLE_PRIMARY_DIRECT, PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
            PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT, PATHWAY_ROLE_EXCLUDED,
        }


class TestValidateMediaOutcomePathways:
    def test_well_formed_pathway_has_no_errors(self):
        pathway = _pathway()
        errors = validate_media_outcome_pathways(
            [pathway], channels=["DNA_Media"], outcome_ids=["dna_kit_sale_self_activated"],
        )
        assert errors == []

    def test_unknown_channel_is_an_error(self):
        pathway = _pathway(channel="Not_A_Real_Channel")
        errors = validate_media_outcome_pathways([pathway], channels=["DNA_Media"])
        assert any("unknown channel" in e for e in errors)

    def test_channel_not_checked_when_channels_omitted(self):
        pathway = _pathway(channel="Whatever")
        errors = validate_media_outcome_pathways([pathway])
        assert not any("unknown channel" in e for e in errors)

    def test_unknown_source_product_is_an_error(self):
        pathway = _pathway(source_product="Not A Product")
        errors = validate_media_outcome_pathways([pathway])
        assert any("unknown source_product" in e for e in errors)

    def test_unknown_target_outcome_id_is_an_error_when_outcome_ids_given(self):
        pathway = _pathway(target_outcome_id="does_not_exist")
        errors = validate_media_outcome_pathways([pathway], outcome_ids=["fh_new_gsa"])
        assert any("unknown target_outcome_id" in e for e in errors)

    def test_target_outcome_id_not_checked_when_outcome_ids_omitted(self):
        pathway = _pathway(target_outcome_id="fh_net_billthrough_count")
        errors = validate_media_outcome_pathways([pathway])
        assert errors == []

    def test_unknown_role_is_an_error(self):
        pathway = _pathway(role="not_a_real_role")
        errors = validate_media_outcome_pathways([pathway])
        assert any("unknown role" in e for e in errors)

    def test_negative_lag_weeks_is_an_error(self):
        pathway = _pathway(lag_type="fixed_weeks", lag_weeks=-1)
        errors = validate_media_outcome_pathways([pathway])
        assert any("negative lag_weeks" in e for e in errors)

    def test_non_positive_prior_scale_is_an_error(self):
        pathway = _pathway(prior_scale=0.0)
        errors = validate_media_outcome_pathways([pathway])
        assert any("non-positive prior_scale" in e for e in errors)

    def test_duplicate_pathway_id_is_an_error(self):
        a = _pathway(pathway_id="dup")
        b = _pathway(pathway_id="dup", target_outcome_id="dna_kit_sale_gifted_activated")
        errors = validate_media_outcome_pathways([a, b])
        assert any("Duplicate pathway_id" in e for e in errors)

    def test_duplicate_channel_outcome_pair_is_an_error(self):
        a = _pathway(channel="DNA_Media", target_outcome_id="dna_kit_sale_self_activated")
        b = _pathway(channel="DNA_Media", target_outcome_id="dna_kit_sale_self_activated")
        errors = validate_media_outcome_pathways([a, b])
        assert any("Duplicate pathway for channel" in e for e in errors)

    def test_same_channel_different_outcomes_is_not_a_duplicate(self):
        a = _pathway(channel="DNA_Media", target_outcome_id="dna_kit_sale_self_activated")
        b = _pathway(channel="DNA_Media", target_outcome_id="dna_kit_sale_gifted_activated")
        errors = validate_media_outcome_pathways([a, b])
        assert not any("Duplicate pathway for channel" in e for e in errors)

    def test_missing_pathway_id_is_deterministically_resolved(self):
        pathway = _pathway(pathway_id="")
        assert pathway.pathway_id


class TestPathwaysCanTargetTheExpandedFutureOutcomeCatalogue:
    """Required test case - the pathway schema must be able to target
    fh_net_billthrough_count, dna_kit_sale_total, dna_kit_sale_self_activated,
    dna_kit_sale_gifted_activated and dna_kit_sale_unactivated (the roadmap's
    expanded outcome catalogue) without any hard-coded assumption that every
    FH KPI is a GSA or every DNA KPI is a generic kit-sale total."""

    FUTURE_OUTCOME_IDS = [
        "fh_net_billthrough_count", "fh_gsa_finance_date", "fh_signup_count",
        "dna_kit_sale_total", "dna_kit_sale_self_activated",
        "dna_kit_sale_gifted_activated", "dna_kit_sale_unactivated",
    ]

    def test_pathways_targeting_every_future_outcome_id_validate_cleanly(self):
        pathways = [
            _pathway(channel=f"channel_{i}", target_outcome_id=oid, source_product=DNA if "dna" in oid else FAMILY_HISTORY)
            for i, oid in enumerate(self.FUTURE_OUTCOME_IDS)
        ]
        errors = validate_media_outcome_pathways(
            pathways, channels=[p.channel for p in pathways], outcome_ids=self.FUTURE_OUTCOME_IDS,
        )
        assert errors == []

    def test_dna_media_to_fh_net_billthrough_is_a_valid_active_cross_product_pathway(self):
        pathway = _pathway(
            channel="DNA_Media", source_product=DNA, target_outcome_id="fh_net_billthrough_count",
            role=PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT, component_type="cross_product",
        )
        errors = validate_media_outcome_pathways([pathway], outcome_ids=["fh_net_billthrough_count"])
        assert errors == []

    def test_fh_media_to_dna_kit_total_is_a_valid_exploratory_pathway(self):
        pathway = _pathway(
            channel="TV", source_product=FAMILY_HISTORY, target_outcome_id="dna_kit_sale_total",
            role=PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT, component_type="cross_product", include_in_planning=False, prior_scale=0.1,
        )
        errors = validate_media_outcome_pathways([pathway], outcome_ids=["dna_kit_sale_total"])
        assert errors == []


class TestPathwayCatalogueFingerprintPayload:
    def test_sorted_by_channel_and_target_outcome_id(self):
        a = _pathway(channel="TV", target_outcome_id="fh_new_gsa")
        b = _pathway(channel="DNA_Media", target_outcome_id="dna_kit_sale_self_activated")
        payload = pathway_catalogue_fingerprint_payload([a, b])
        assert [p["channel"] for p in payload] == ["DNA_Media", "TV"]

    def test_order_independent(self):
        a = _pathway(channel="TV", target_outcome_id="fh_new_gsa")
        b = _pathway(channel="DNA_Media", target_outcome_id="dna_kit_sale_self_activated")
        assert pathway_catalogue_fingerprint_payload([a, b]) == pathway_catalogue_fingerprint_payload([b, a])

    def test_pathway_id_is_excluded_from_the_payload(self):
        pathway = _pathway()
        [payload] = pathway_catalogue_fingerprint_payload([pathway])
        assert "pathway_id" not in payload

    def test_two_pathways_differing_only_by_pathway_id_fingerprint_identically(self):
        a = _pathway(pathway_id="id-a")
        b = _pathway(pathway_id="id-b")
        assert pathway_catalogue_fingerprint_payload([a]) == pathway_catalogue_fingerprint_payload([b])

    def test_changing_role_changes_the_payload(self):
        a = _pathway(role=PATHWAY_ROLE_PRIMARY_DIRECT)
        b = _pathway(role=PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT)
        assert pathway_catalogue_fingerprint_payload([a]) != pathway_catalogue_fingerprint_payload([b])


class TestPathwayDriftStatus:
    def test_unchanged_pathway_is_fitted_and_current(self):
        pathway = _pathway(pathway_id="p1")
        assert pathway_drift_status(pathway, pathway) == "Fitted and current"

    def test_changed_role_is_changed_since_fit(self):
        fit_time = _pathway(pathway_id="p1", role=PATHWAY_ROLE_PRIMARY_DIRECT)
        current = _pathway(pathway_id="p1", role=PATHWAY_ROLE_EXCLUDED)
        assert pathway_drift_status(current, fit_time) == "Changed since fit"

    def test_no_fit_time_pathway_is_new_since_fit(self):
        pathway = _pathway(pathway_id="p1")
        assert pathway_drift_status(pathway, None) == "New since fit"

    def test_no_current_pathway_is_removed_since_fit(self):
        pathway = _pathway(pathway_id="p1")
        assert pathway_drift_status(None, pathway) == "Removed since fit"

    def test_both_none_raises(self):
        with pytest.raises(ValueError):
            pathway_drift_status(None, None)

    def test_all_statuses_are_the_documented_four(self):
        assert set(PATHWAY_DRIFT_STATUSES) == {
            "Fitted and current", "Changed since fit", "New since fit", "Removed since fit",
        }


class TestPathwayCatalogueAtFitById:
    def test_none_model_meta_gives_empty_dict(self):
        assert pathway_catalogue_at_fit_by_id(None) == {}

    def test_keyed_by_pathway_id(self):
        pathway = _pathway(pathway_id="p1")
        meta = SimpleNamespace(pathway_catalogue_at_fit=[pathway])
        assert list(pathway_catalogue_at_fit_by_id(meta).values()) == [pathway]

    def test_missing_attribute_gives_empty_dict(self):
        meta = SimpleNamespace()
        assert pathway_catalogue_at_fit_by_id(meta) == {}


class TestPathwaysDriftDataframe:
    def test_none_model_meta_gives_empty_dataframe(self):
        df = pathways_drift_dataframe([_pathway()], None)
        assert df.empty
        assert list(df.columns) == ["pathway_id", "drift_status"]

    def test_includes_removed_pathway_not_in_current_catalogue(self):
        fit_time_pathway = _pathway(pathway_id="p1")
        meta = SimpleNamespace(pathway_catalogue_at_fit=[fit_time_pathway])
        df = pathways_drift_dataframe([], meta)
        assert len(df) == 1
        assert df.iloc[0]["drift_status"] == "Removed since fit"

    def test_includes_new_pathway_not_in_fit_time_catalogue(self):
        meta = SimpleNamespace(pathway_catalogue_at_fit=[])
        pathway = _pathway(pathway_id="p1")
        df = pathways_drift_dataframe([pathway], meta)
        assert len(df) == 1
        assert df.iloc[0]["drift_status"] == "New since fit"


def _reconciliation_group(**overrides) -> OutcomeReconciliationGroup:
    defaults = dict(
        group_id="dna_total_reconciliation",
        component_outcome_ids=["dna_kit_sale_self_activated", "dna_kit_sale_gifted_activated", "dna_kit_sale_unactivated"],
        relation="sum", total_outcome_id="dna_kit_sale_total",
    )
    defaults.update(overrides)
    return OutcomeReconciliationGroup(**defaults)


class TestOutcomeReconciliationGroupRoundTrip:
    def test_to_dict_from_dict_round_trips(self):
        group = _reconciliation_group()
        assert OutcomeReconciliationGroup.from_dict(group.to_dict()) == group


class TestValidateReconciliationGroups:
    def test_well_formed_group_has_no_errors(self):
        group = _reconciliation_group()
        errors = validate_reconciliation_groups(
            [group],
            outcome_ids=["dna_kit_sale_self_activated", "dna_kit_sale_gifted_activated", "dna_kit_sale_unactivated", "dna_kit_sale_total"],
        )
        assert errors == []

    def test_missing_group_id_is_an_error(self):
        group = _reconciliation_group(group_id="")
        errors = validate_reconciliation_groups([group])
        assert any("must have a group_id" in e for e in errors)

    def test_duplicate_group_id_is_an_error(self):
        a = _reconciliation_group(group_id="dup")
        b = _reconciliation_group(group_id="dup")
        errors = validate_reconciliation_groups([a, b])
        assert any("Duplicate reconciliation group_id" in e for e in errors)

    def test_unknown_relation_is_an_error(self):
        group = _reconciliation_group(relation="not_a_real_relation")
        errors = validate_reconciliation_groups([group])
        assert any("unknown relation" in e for e in errors)

    def test_fewer_than_two_components_is_an_error(self):
        group = _reconciliation_group(component_outcome_ids=["only_one"])
        errors = validate_reconciliation_groups([group])
        assert any("at least 2 component_outcome_ids" in e for e in errors)

    def test_total_outcome_id_in_its_own_components_is_an_error(self):
        group = _reconciliation_group(
            total_outcome_id="dna_kit_sale_self_activated",
            component_outcome_ids=["dna_kit_sale_self_activated", "dna_kit_sale_gifted_activated"],
        )
        errors = validate_reconciliation_groups([group])
        assert any("listed as one of its own component_outcome_ids" in e for e in errors)

    def test_unknown_component_outcome_id_is_an_error_when_outcome_ids_given(self):
        group = _reconciliation_group()
        errors = validate_reconciliation_groups([group], outcome_ids=["dna_kit_sale_total"])
        assert any("unknown component_outcome_id" in e for e in errors)

    def test_unknown_total_outcome_id_is_an_error_when_outcome_ids_given(self):
        group = _reconciliation_group()
        errors = validate_reconciliation_groups(
            [group], outcome_ids=["dna_kit_sale_self_activated", "dna_kit_sale_gifted_activated", "dna_kit_sale_unactivated"],
        )
        assert any("unknown total_outcome_id" in e for e in errors)

    def test_outcome_ids_not_checked_when_omitted(self):
        group = _reconciliation_group()
        errors = validate_reconciliation_groups([group])
        assert errors == []

    def test_relations_constant_matches_expected_vocabulary(self):
        assert set(RECONCILIATION_RELATIONS) == {"sum", "ratio"}


class TestReconciliationGroupDiagnostics:
    def test_sum_relation_reconciles_when_total_equals_component_sum(self):
        group = _reconciliation_group()
        values = {
            "dna_kit_sale_self_activated": 10.0, "dna_kit_sale_gifted_activated": 5.0,
            "dna_kit_sale_unactivated": 3.0, "dna_kit_sale_total": 18.0,
        }
        result = reconciliation_group_diagnostics(group, values)
        assert result["component_sum"] == 18.0
        assert result["reconciles"] is True
        assert result["difference"] == 0.0

    def test_sum_relation_does_not_reconcile_when_total_differs(self):
        group = _reconciliation_group()
        values = {
            "dna_kit_sale_self_activated": 10.0, "dna_kit_sale_gifted_activated": 5.0,
            "dna_kit_sale_unactivated": 3.0, "dna_kit_sale_total": 100.0,
        }
        result = reconciliation_group_diagnostics(group, values)
        assert result["reconciles"] is False
        assert result["difference"] == pytest.approx(100.0 - 18.0)

    def test_missing_values_give_none_not_zero(self):
        group = _reconciliation_group()
        result = reconciliation_group_diagnostics(group, {})
        assert result["component_sum"] is None
        assert result["total_value"] is None
        assert result["reconciles"] is None

    def test_ratio_relation_computes_implied_ratio(self):
        group = OutcomeReconciliationGroup(
            group_id="net_billthrough_rate", relation="ratio",
            total_outcome_id="fh_net_billthrough_count", component_outcome_ids=["fh_signup_count"],
        )
        values = {"fh_net_billthrough_count": 40.0, "fh_signup_count": 100.0}
        result = reconciliation_group_diagnostics(group, values)
        assert result["implied_ratio"] == pytest.approx(0.4)

    def test_ratio_relation_with_zero_denominator_gives_no_implied_ratio(self):
        group = OutcomeReconciliationGroup(
            group_id="net_billthrough_rate", relation="ratio",
            total_outcome_id="fh_net_billthrough_count", component_outcome_ids=["fh_signup_count"],
        )
        values = {"fh_net_billthrough_count": 40.0, "fh_signup_count": 0.0}
        result = reconciliation_group_diagnostics(group, values)
        assert "implied_ratio" not in result


# ---------------------------------------------------------------------------
# resolve_pathway_masks (PR G1) - the legacy-default equivalence proven here
# is what "no pathway catalogue configured" backward compatibility rests on;
# core.hierarchical_model/core.market_specific_model call this exact
# function to build the operational masks.
# ---------------------------------------------------------------------------

OUTCOME_IDS = ["fh_new", "fh_dna_crosssell", "fh_winback", "dna_new_kit"]
CHANNELS = ["TV", "Search", "DNA_Media"]
DNA_CHANNEL_IDX = [2]  # "DNA_Media"
DNA_OUTCOME_ID = "fh_dna_crosssell"
DIRECT_DNA_OUTCOME_IDS = ["fh_dna_crosssell", "dna_new_kit"]
DNA_LAG_WEEKS = 4


def _resolve(pathways=None):
    return resolve_pathway_masks(
        OUTCOME_IDS, CHANNELS, pathways or [],
        dna_channel_idx=DNA_CHANNEL_IDX, dna_outcome_id=DNA_OUTCOME_ID,
        direct_dna_outcome_ids=DIRECT_DNA_OUTCOME_IDS, dna_lag_weeks=DNA_LAG_WEEKS,
    )


class TestResolvePathwayMasksLegacyDefaults:
    """No pathway catalogue configured - every cell must resolve to exactly
    what this codebase fit before PR G1 (the backward-compatibility
    guarantee the whole design rests on)."""

    def test_non_dna_channel_is_primary_direct_for_every_outcome(self):
        masks = _resolve()
        for oid in OUTCOME_IDS:
            assert "TV" in masks.primary_channels_by_outcome.get(oid, [])
            assert "Search" in masks.primary_channels_by_outcome.get(oid, [])
            assert "TV" not in masks.active_channels_by_outcome.get(oid, [])
            assert "TV" not in masks.exploratory_channels_by_outcome.get(oid, [])

    def test_dna_channel_kit_only_outcome_is_primary_only(self):
        masks = _resolve()
        assert "DNA_Media" in masks.primary_channels_by_outcome.get("dna_new_kit", [])
        assert "DNA_Media" not in masks.active_channels_by_outcome.get("dna_new_kit", [])

    def test_dna_channel_dna_outcome_id_gets_both_primary_and_active(self):
        masks = _resolve()
        assert "DNA_Media" in masks.primary_channels_by_outcome.get(DNA_OUTCOME_ID, [])
        assert "DNA_Media" in masks.active_channels_by_outcome.get(DNA_OUTCOME_ID, [])

    def test_dna_channel_ordinary_outcome_is_active_only(self):
        masks = _resolve()
        assert "DNA_Media" not in masks.primary_channels_by_outcome.get("fh_new", [])
        assert "DNA_Media" in masks.active_channels_by_outcome.get("fh_new", [])
        assert "DNA_Media" not in masks.primary_channels_by_outcome.get("fh_winback", [])
        assert "DNA_Media" in masks.active_channels_by_outcome.get("fh_winback", [])

    def test_no_exploratory_cells_by_default(self):
        masks = _resolve()
        assert masks.exploratory_channels_by_outcome == {}

    def test_cross_product_lag_weeks_matches_dna_lag_weeks(self):
        assert _resolve().cross_product_lag_weeks == DNA_LAG_WEEKS

    def test_no_dna_channels_at_all_is_primary_direct_everywhere(self):
        masks = resolve_pathway_masks(
            OUTCOME_IDS, CHANNELS, [], dna_channel_idx=[], dna_outcome_id=None,
            direct_dna_outcome_ids=[], dna_lag_weeks=DNA_LAG_WEEKS,
        )
        for oid in OUTCOME_IDS:
            assert set(masks.primary_channels_by_outcome.get(oid, [])) == set(CHANNELS)
        assert masks.active_channels_by_outcome == {}


class TestResolvePathwayMasksExplicitOverrides:
    def test_explicit_excluded_pathway_removes_cell_from_every_bucket(self):
        pathway = MediaOutcomePathway(channel="TV", source_product=FAMILY_HISTORY, target_outcome_id="fh_new", role=PATHWAY_ROLE_EXCLUDED)
        masks = _resolve([pathway])
        assert "TV" not in masks.primary_channels_by_outcome.get("fh_new", [])
        assert "TV" not in masks.active_channels_by_outcome.get("fh_new", [])
        assert "TV" not in masks.exploratory_channels_by_outcome.get("fh_new", [])
        # Every other (outcome, TV) cell is untouched by this one exclusion.
        assert "TV" in masks.primary_channels_by_outcome.get("fh_winback", [])

    def test_explicit_exploratory_pathway_on_a_non_dna_channel(self):
        pathway = MediaOutcomePathway(
            channel="TV", source_product=FAMILY_HISTORY, target_outcome_id="dna_new_kit",
            role=PATHWAY_ROLE_EXPLORATORY_CROSS_PRODUCT,
        )
        masks = _resolve([pathway])
        assert "TV" in masks.exploratory_channels_by_outcome.get("dna_new_kit", [])
        assert "TV" not in masks.primary_channels_by_outcome.get("dna_new_kit", [])
        # Untouched: TV -> dna_new_kit was primary_direct by legacy default
        # for every OTHER outcome (non-DNA channel), unaffected by this
        # single-cell override.
        assert "TV" in masks.primary_channels_by_outcome.get("fh_new", [])

    def test_explicit_pathway_on_a_dna_cell_replaces_the_legacy_combined_default(self):
        # dna_outcome_id x DNA_Media legacy-defaults to BOTH primary and
        # active; an explicit pathway for that exact cell reduces it to just
        # the one specified role (documented simplification).
        pathway = MediaOutcomePathway(
            channel="DNA_Media", source_product=DNA, target_outcome_id=DNA_OUTCOME_ID,
            role=PATHWAY_ROLE_ACTIVE_CROSS_PRODUCT,
        )
        masks = _resolve([pathway])
        assert "DNA_Media" in masks.active_channels_by_outcome.get(DNA_OUTCOME_ID, [])
        assert "DNA_Media" not in masks.primary_channels_by_outcome.get(DNA_OUTCOME_ID, [])

    def test_explicit_primary_direct_pathway_is_a_no_op_when_it_matches_the_legacy_default(self):
        pathway = MediaOutcomePathway(channel="TV", source_product=FAMILY_HISTORY, target_outcome_id="fh_new", role=PATHWAY_ROLE_PRIMARY_DIRECT)
        assert _resolve([pathway]).primary_channels_by_outcome == _resolve([]).primary_channels_by_outcome


class TestResolvedPathwayMasksConversionHelpers:
    def test_primary_matrix_shape_and_values(self):
        masks = _resolve()
        mat = masks.primary_matrix(OUTCOME_IDS, CHANNELS)
        assert mat.shape == (len(OUTCOME_IDS), len(CHANNELS))
        # fh_new / TV -> primary (1.0)
        assert mat[OUTCOME_IDS.index("fh_new"), CHANNELS.index("TV")] == 1.0
        # fh_new / DNA_Media -> not primary (0.0)
        assert mat[OUTCOME_IDS.index("fh_new"), CHANNELS.index("DNA_Media")] == 0.0

    def test_active_cells_are_outcome_channel_index_pairs(self):
        masks = _resolve()
        cells = masks.active_cells(OUTCOME_IDS, CHANNELS)
        expected = {
            (OUTCOME_IDS.index("fh_new"), CHANNELS.index("DNA_Media")),
            (OUTCOME_IDS.index(DNA_OUTCOME_ID), CHANNELS.index("DNA_Media")),
            (OUTCOME_IDS.index("fh_winback"), CHANNELS.index("DNA_Media")),
        }
        assert set(cells) == expected

    def test_exploratory_cells_empty_by_default(self):
        assert _resolve().exploratory_cells(OUTCOME_IDS, CHANNELS) == []

    def test_to_dict_from_dict_round_trips(self):
        masks = _resolve()
        restored = ResolvedPathwayMasks.from_dict(masks.to_dict())
        assert restored == masks

    def test_from_dict_none_gives_empty_masks(self):
        assert ResolvedPathwayMasks.from_dict(None) == ResolvedPathwayMasks()
