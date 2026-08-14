"""Tests for the Phase 1 source inventory and preparation boundary helpers."""

import pandas as pd

from ancestry_mmm.data.loader import load_realistic_sample_sources
from ancestry_mmm.data.source_inventory import (
    inspect_source_layout,
    is_realistic_source_pack_demo,
    summarise_source_inventory,
)


def test_realistic_pack_is_source_native_and_not_rectangular_joinable():
    frames, error = load_realistic_sample_sources()
    frames.pop("segment_ltv")
    assert error is None

    layout = inspect_source_layout(
        frames,
        demo_source_pack="realistic-source-pack-v2",
    )

    assert layout.kind == "realistic_source_pack"
    assert layout.is_source_native
    assert not layout.can_use_rectangular_join
    assert len(layout.table_names) == 7


def test_inventory_keeps_tables_separate_from_uploaded_workbooks():
    frames, error = load_realistic_sample_sources()
    frames.pop("segment_ltv")
    assert error is None

    definitions = [
        {"source_id": name, "name": name, "logical_domain": domain}
        for name, domain in {
            "activity_data": "activity_and_media",
            "activity_dictionary": "activity_and_media",
            "outcomes": "outcomes",
            "outcome_dictionary": "outcomes",
            "context_data": "context_and_external_factors",
            "variable_dictionary": "context_and_external_factors",
            "events": "context_and_external_factors",
        }.items()
    ]
    inventory = summarise_source_inventory(
        frames,
        definitions,
        demo_source_pack="realistic-source-pack-v2",
    )

    assert inventory.uploaded_file_count == 0
    assert inventory.active_source_version_count == 0
    assert inventory.table_count == 7
    assert inventory.data_category_count == 3
    assert inventory.recognised_standard_table_count == 7


def test_rectangular_inputs_remain_available_to_the_join_page():
    frames = {
        "media": pd.DataFrame({"date": ["2025-01-01"], "spend": [1.0]}),
        "outcomes": pd.DataFrame({"date": ["2025-01-01"], "signups": [2]}),
    }

    layout = inspect_source_layout(frames)

    assert layout.kind == "rectangular"
    assert not layout.is_source_native
    assert layout.can_use_rectangular_join


def test_realistic_demo_identity_is_version_aware_but_does_not_guess_uploads():
    assert is_realistic_source_pack_demo("realistic-source-pack-v1")
    assert is_realistic_source_pack_demo("realistic-source-pack-v2")
    assert is_realistic_source_pack_demo("realistic-source-pack-v12")
    assert not is_realistic_source_pack_demo("realistic-source-pack")
    assert not is_realistic_source_pack_demo("realistic-source-pack-v2.xlsx")
    assert not is_realistic_source_pack_demo("arbitrary-upload-v2")
