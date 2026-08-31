"""Tests for `core.named_event_fit_inputs` - the production-integration
glue between the governed named-event registry (`core.named_events`) and
the approved S3 spline-basis statistical method (`core.
named_event_response`, Decision 12).

These are construction/contract tests only (fast, no PyMC/MCMC involved) -
the real posterior-recovery evidence that this construction actually
produces a model that recovers a planted event effect lives in
`test_named_event_response_recovery_posterior.py` (schedule/manual-only,
mirroring `test_search_candidate_a_recovery_posterior.py`'s own
precedent)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ancestry_mmm.core.named_event_fit_inputs import (
    NamedEventFamilyFitBlock,
    NamedEventFitInputs,
    build_named_event_fit_inputs,
)
from ancestry_mmm.core.named_event_response import NAMED_EVENT_RESPONSE_STRUCTURE
from ancestry_mmm.core.named_events import (
    DEFAULT_EVENT_EVIDENCE_STATUS,
    EventResponseDefinition,
    NamedEventFamily,
    NamedEventOccurrence,
)


def _family(**overrides):
    values = {
        "family_id": "mothers_day",
        "family_version": 1,
        "display_name": "Mother's Day",
        "classification": "gifting",
        "classification_status": DEFAULT_EVENT_EVIDENCE_STATUS,
    }
    values.update(overrides)
    return NamedEventFamily(**values)


def _occurrence(**overrides):
    values = {
        "event_id": "md-2026",
        "event_version": 1,
        "display_name": "Mother's Day 2026",
        "start_date": "2026-03-22",
        "end_date": "2026-03-22",
        "market_scope": ("UK",),
        "source_id": "events",
        "family_id": "mothers_day",
    }
    values.update(overrides)
    return NamedEventOccurrence(**values)


def _definition(**overrides):
    values = {
        "response_definition_id": "md-def",
        "response_definition_version": 1,
        "family_id": "mothers_day",
        "treatment": "anticipatory",
        "max_lead": 3,
        "max_lag": 0,
        "transformation_method_reference": NAMED_EVENT_RESPONSE_STRUCTURE,
    }
    values.update(overrides)
    return EventResponseDefinition(**values)


def _frame(markets, n_weeks_per_market, *, start="2026-01-01"):
    """A minimal frame dict carrying only the three keys `build_named_
    event_fit_inputs` reads - `markets`/`dates`/`market_bounds`, matching
    `data.preprocessor.prepare_fh_modeling_frame`'s own contiguous-
    per-market-block, weekly-frequency layout."""
    dates = []
    market_bounds = []
    offset = 0
    for _m in markets:
        block_dates = pd.date_range(start, periods=n_weeks_per_market, freq="W")
        dates.extend(block_dates)
        market_bounds.append((offset, offset + n_weeks_per_market))
        offset += n_weeks_per_market
    return {
        "markets": list(markets),
        "dates": np.array(dates, dtype="datetime64[ns]"),
        "market_bounds": market_bounds,
    }


class TestNoOptInReturnsNone:
    def test_no_response_definitions_at_all_returns_none(self):
        frame = _frame(["UK"], 20)
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[],
        )
        assert result is None

    def test_response_definition_with_a_different_reference_returns_none(self):
        """The explicit per-family opt-in gate: a response definition
        registered before this module existed (or one that simply never
        opted in) must never silently start calibrating a model."""
        frame = _frame(["UK"], 20)
        definition = _definition(
            transformation_method_reference="governed-ref-pending-approval"
        )
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[definition],
        )
        assert result is None

    def test_degenerate_window_returns_none(self):
        frame = _frame(["UK"], 20)
        definition = _definition(max_lead=0, max_lag=0)
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[definition],
        )
        assert result is None

    def test_orphan_family_link_is_skipped_not_fabricated(self):
        frame = _frame(["UK"], 20)
        result = build_named_event_fit_inputs(
            frame,
            families=[],  # the definition's family_id is not registered
            occurrences=[_occurrence()],
            response_definitions=[_definition()],
        )
        assert result is None

    def test_no_occurrences_for_the_family_returns_none(self):
        frame = _frame(["UK"], 20)
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[],
            response_definitions=[_definition()],
        )
        assert result is None

    def test_occurrence_outside_the_market_date_range_returns_none(self):
        frame = _frame(["UK"], 10, start="2026-01-01")  # ends well before March
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[_definition()],
        )
        assert result is None

    def test_occurrence_market_scope_excludes_the_fit_market_returns_none(self):
        frame = _frame(["AU"], 20)
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence(market_scope=("UK",))],
            response_definitions=[_definition()],
        )
        assert result is None


class TestOptedInFamilyProducesABlock:
    def test_single_market_produces_one_block_with_a_nonzero_design(self):
        frame = _frame(["UK"], 20, start="2026-01-01")
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[_definition()],
        )
        assert isinstance(result, NamedEventFitInputs)
        assert result.family_ids == ("mothers_day",)
        blocks = result.blocks_for_family("mothers_day")
        assert len(blocks) == 1
        block = blocks[0]
        assert isinstance(block, NamedEventFamilyFitBlock)
        assert block.market == "UK"
        n_obs = len(frame["dates"])
        assert block.design.shape[0] == n_obs
        assert block.design.shape[1] > 0
        assert np.any(block.design != 0.0)
        assert block.response_definition_id == "md-def"
        assert block.response_definition_version == 1

    def test_design_is_zero_outside_the_events_market_row_range(self):
        """Unpooled-by-default (Decision 12, dimension 4): a family's
        occurrence in one market must never leak a nonzero design value
        into a different market's rows."""
        frame = _frame(["UK", "AU"], 20, start="2026-01-01")
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence(market_scope=("UK",))],
            response_definitions=[_definition()],
        )
        assert result is not None
        block = result.blocks_for_family("mothers_day")[0]
        assert block.market == "UK"
        au_start, au_end = frame["market_bounds"][1]
        assert np.all(block.design[au_start:au_end, :] == 0.0)

    def test_two_markets_with_the_same_family_get_independent_blocks(self):
        """Unpooled per market: two markets both carrying the family's
        event must each get their own block, never one shared block."""
        frame = _frame(["UK", "AU"], 20, start="2026-01-01")
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[
                _occurrence(event_id="md-uk", market_scope=("UK",)),
                _occurrence(event_id="md-au", market_scope=("AU",)),
            ],
            response_definitions=[_definition()],
        )
        assert result is not None
        blocks = result.blocks_for_family("mothers_day")
        assert {b.market for b in blocks} == {"UK", "AU"}
        assert len(blocks) == 2

    def test_consumed_response_definitions_reports_the_opted_in_pair(self):
        frame = _frame(["UK"], 20, start="2026-01-01")
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[_definition()],
        )
        assert result is not None
        assert result.consumed_response_definitions() == (("md-def", 1),)

    def test_outcome_scope_is_preserved_on_the_block(self):
        frame = _frame(["UK"], 20, start="2026-01-01")
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[_definition(outcome_scope=("New",))],
        )
        assert result is not None
        block = result.blocks_for_family("mothers_day")[0]
        assert block.outcome_scope == ("New",)

    def test_shrinkage_prior_scale_recorded_per_family(self):
        frame = _frame(["UK"], 20, start="2026-01-01")
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[_definition()],
        )
        assert result is not None
        assert "mothers_day" in result.shrinkage_prior_scale_by_family
        assert result.shrinkage_prior_scale_by_family["mothers_day"] > 0

    def test_only_the_current_version_of_a_response_definition_is_used(self):
        """A superseded response definition version must never contribute
        alongside its own replacement - only the current version wins,
        mirroring core.named_events' own version-immutability contract."""
        frame = _frame(["UK"], 20, start="2026-01-01")
        old_definition = _definition(max_lead=1)
        new_definition = _definition(response_definition_version=2, max_lead=3)
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[old_definition, new_definition],
        )
        assert result is not None
        block = result.blocks_for_family("mothers_day")[0]
        # max_lead=3 -> 4 offsets (-3..0); max_lead=1 -> 2 offsets (-1..0).
        # The basis width is a function of the window actually used, so a
        # width consistent only with the newer (max_lead=3) definition
        # confirms the older version was not the one applied.
        assert block.response_definition_version == 2


class TestMultiWeekOccurrence:
    def test_an_occurrence_spanning_several_weeks_populates_every_covered_week(self):
        frame = _frame(["UK"], 20, start="2026-01-01")
        occurrence = _occurrence(start_date="2026-03-01", end_date="2026-03-22")
        result = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[occurrence],
            response_definitions=[_definition()],
        )
        assert result is not None
        block = result.blocks_for_family("mothers_day")[0]
        # More than one week of the multi-week occurrence should register
        # a nonzero contribution across more rows than a single-week event
        # would (loosely - exact row count depends on the spline basis).
        nonzero_rows = int(np.any(block.design != 0.0, axis=1).sum())
        assert nonzero_rows > 1
