"""Acceptance checks for the 2026-09-04 UK production implementation brief."""

from pathlib import Path

import pytest

from ancestry_mmm.core.google_trends_anchor import (
    UK_BRAND_DEMAND_QUERY_EXPRESSION,
    UK_BRAND_DEMAND_TERMS,
    GoogleTrendsQuerySetDefinition,
)
from ancestry_mmm.core.outcomes import LEGACY_NBT_OUTCOME_ID_ALIASES
from ancestry_mmm.core.search_intent_taxonomy import (
    BRAND_CLASS_GENERIC_NON_BRAND,
    SearchIntentGroup,
    resolve_search_intent_model_grain,
    validate_search_intent_group_catalogue,
)


def test_current_uk_production_uses_supplied_nbt_ids():
    assert tuple(LEGACY_NBT_OUTCOME_ID_ALIASES.values()) == (
        "fh_net_billthrough_count_new",
        "fh_net_billthrough_count_dna_cross_sell",
        "fh_net_billthrough_count_winback",
    )
    structure_page = (
        Path(__file__).parents[1] / "pages" / "03_Structure_Segments_Markets.py"
    )
    text = structure_page.read_text(encoding="utf-8")
    assert "Current UK production authority" in text
    assert "GSA remains a distinct secondary/context" in text
    assert "14-day" not in text


def test_google_trends_expression_preserves_duplicate_term():
    assert UK_BRAND_DEMAND_QUERY_EXPRESSION == (
        "ancestry + ancestory + ancestery + ansectry + anscestry + ancestry"
    )
    assert UK_BRAND_DEMAND_TERMS.count("ancestry") == 2
    definition = GoogleTrendsQuerySetDefinition(
        query_set_id="uk_brand_demand_v1",
        branded_terms=UK_BRAND_DEMAND_TERMS,
        geography="GB",
        time_range_start="2024-01-01",
        time_range_end="2024-12-30",
    )
    assert definition.query_expression == UK_BRAND_DEMAND_QUERY_EXPRESSION
    assert definition.duplicate_terms == ("ancestry",)


def test_search_taxonomy_requires_explicit_deeper_child_parent():
    child = SearchIntentGroup(
        search_intent_group_id="non_brand_genealogy",
        search_intent_group_name="Genealogy",
        brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
        parent_search_intent_group_id="not_non_brand_search",
    )
    issues = validate_search_intent_group_catalogue((child,))
    assert any("unknown parent" in issue for issue in issues)
    assert any("must be governed under Non-Brand" in issue for issue in issues)


def test_search_model_grain_rejects_parent_and_child_double_fit():
    child = SearchIntentGroup(
        search_intent_group_id="non_brand_genealogy",
        search_intent_group_name="Genealogy",
        brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
        parent_search_intent_group_id="non_brand_search",
    )
    with pytest.raises(ValueError, match="parent and its deeper child"):
        resolve_search_intent_model_grain(
            ("non_brand_search", "non_brand_genealogy"),
            (child,),
        )


def _ragged_market_child() -> SearchIntentGroup:
    return SearchIntentGroup(
        search_intent_group_id="non_brand_genealogy",
        search_intent_group_name="Genealogy",
        brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
        parent_search_intent_group_id="non_brand_search",
    )


def test_search_model_grain_allows_ragged_parent_and_child_across_markets():
    """REQ-SEARCH-004 §4 / REQ-SEARCH-005 §2: one market may use the
    approved Non-Brand parent while a different market uses an approved
    deeper child - a project-wide selection covering both must not be
    rejected merely because it spans both grains somewhere in the project.
    """
    child = _ragged_market_child()
    activities = [
        {"market": "GB", "search_intent_group_id": "non_brand_search"},
        {"market": "US", "search_intent_group_id": "non_brand_genealogy"},
    ]
    resolved = resolve_search_intent_model_grain(
        ("non_brand_search", "non_brand_genealogy"),
        (child,),
        activities,
    )
    assert set(resolved) == {"non_brand_search", "non_brand_genealogy"}


def test_search_model_grain_rejects_parent_and_child_in_the_same_market():
    """The double-fit risk is real when one market's own activities resolve
    to both the parent and the child - ragged coverage does not excuse an
    overlap that is not actually ragged."""
    child = _ragged_market_child()
    activities = [
        {"market": "GB", "search_intent_group_id": "non_brand_search"},
        {"market": "GB", "search_intent_group_id": "non_brand_genealogy"},
    ]
    with pytest.raises(ValueError, match="same market"):
        resolve_search_intent_model_grain(
            ("non_brand_search", "non_brand_genealogy"),
            (child,),
            activities,
        )


def test_search_model_grain_rejects_wildcard_market_overlap_with_any_market():
    """A ``market='*'`` activity applies to every market, so it still
    conflicts with a deeper child selected for one specific market."""
    child = _ragged_market_child()
    activities = [
        {"market": "*", "search_intent_group_id": "non_brand_search"},
        {"market": "GB", "search_intent_group_id": "non_brand_genealogy"},
    ]
    with pytest.raises(ValueError, match="same market"):
        resolve_search_intent_model_grain(
            ("non_brand_search", "non_brand_genealogy"),
            (child,),
            activities,
        )
