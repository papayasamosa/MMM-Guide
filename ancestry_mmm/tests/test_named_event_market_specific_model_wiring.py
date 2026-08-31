"""Fast structural tests (real `pm.Model` + `pm.draw`, never `pm.sample`)
confirming `core.market_specific_model.build_fh_market_specific_model`'s
new `named_event_fit_inputs` parameter (Decision 12) is wired identically
to `core.hierarchical_model.build_fh_hierarchical_model`'s own wiring -
see `test_named_event_hierarchical_model_wiring.py` for the full set of
scenarios covered on Model A; this file checks the same contract holds on
Model C (market-specific, >= 2 markets), which needs its own frame shape
(partial pooling requires at least two markets)."""

from __future__ import annotations

import numpy as np
import pymc as pm

from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.named_event_fit_inputs import build_named_event_fit_inputs
from ancestry_mmm.core.named_event_response import NAMED_EVENT_RESPONSE_STRUCTURE
from ancestry_mmm.core.named_events import (
    DEFAULT_EVENT_EVIDENCE_STATUS,
    EventResponseDefinition,
    NamedEventFamily,
    NamedEventOccurrence,
)
from ancestry_mmm.core.schema import ModelSpec


def _two_market_frame(n_weeks_per_market: int = 16):
    markets = ["UK", "AU"]
    dates_uk = np.array(
        [
            f"2026-{1 + (i // 4):02d}-{1 + 7 * (i % 4):02d}"
            for i in range(n_weeks_per_market)
        ],
        dtype="datetime64[ns]",
    )
    dates = np.concatenate([dates_uk, dates_uk])
    n_obs = 2 * n_weeks_per_market
    return {
        "markets": markets,
        "market_idx": np.array([0] * n_weeks_per_market + [1] * n_weeks_per_market),
        "market_bounds": [
            (0, n_weeks_per_market),
            (n_weeks_per_market, n_obs),
        ],
        "dates": dates,
        "channels": ["TV"],
        "dna_channel_idx": [],
        "outcome_ids": ["fh_new"],
        "X_media": np.full((n_obs, 1), 100.0),
        "Y": np.full((n_obs, 1), 10.0),
        "promo": np.zeros((n_obs, 1)),
        "X_controls": np.zeros((n_obs, 0)),
        "control_names": [],
        "fourier": np.zeros((n_obs, 2)),
        "trend": np.linspace(1.0, 1.1, n_obs),
        "unpooled_markets": [],
    }


def _spec():
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK", "AU"],
        segment_outcomes={"fh_new": "fh_new_gsa"},
        channels=["TV"],
    )


def _family():
    return NamedEventFamily(
        family_id="mothers_day",
        family_version=1,
        display_name="Mother's Day",
        classification="gifting",
        classification_status=DEFAULT_EVENT_EVIDENCE_STATUS,
    )


def _occurrence(**overrides):
    values = {
        "event_id": "md-2026",
        "event_version": 1,
        "display_name": "Mother's Day 2026",
        "start_date": "2026-02-08",
        "end_date": "2026-02-08",
        "market_scope": ("UK", "AU"),
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
        "max_lead": 2,
        "max_lag": 0,
        "transformation_method_reference": NAMED_EVENT_RESPONSE_STRUCTURE,
    }
    values.update(overrides)
    return EventResponseDefinition(**values)


class TestNoFitInputsIsByteIdenticalToBefore:
    def test_default_none_adds_no_event_variables(self):
        frame = _two_market_frame()
        model, meta = build_fh_market_specific_model(frame, _spec())
        event_vars = [name for name in model.named_vars if name.startswith("event_")]
        assert event_vars == []
        assert "eta_events" not in model.named_vars
        assert meta.named_event_response_definitions_at_fit == []
        assert meta.named_event_response_method_version == ""


class TestSuppliedFitInputsWireIntoTheRealModel:
    def test_two_markets_each_get_independent_event_coefficients(self):
        frame = _two_market_frame()
        fit_inputs = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[_definition()],
        )
        assert fit_inputs is not None
        model, meta = build_fh_market_specific_model(
            frame, _spec(), named_event_fit_inputs=fit_inputs
        )
        assert "event_coefs_mothers_day_UK" in model.named_vars
        assert "event_coefs_mothers_day_AU" in model.named_vars
        assert "event_tau_mothers_day" in model.named_vars
        assert "eta_events" in model.named_vars
        assert meta.named_event_response_definitions_at_fit == [("md-def", 1)]
        assert (
            meta.named_event_response_method_version == NAMED_EVENT_RESPONSE_STRUCTURE
        )

    def test_eta_events_is_zero_outside_the_events_market_row_range(self):
        """Unpooled-by-default: an occurrence scoped to UK only must never
        leak a nonzero contribution into AU's rows on Model C either."""
        frame = _two_market_frame()
        fit_inputs = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence(market_scope=("UK",))],
            response_definitions=[_definition()],
        )
        assert fit_inputs is not None
        model, _meta = build_fh_market_specific_model(
            frame, _spec(), named_event_fit_inputs=fit_inputs
        )
        with model:
            val = np.asarray(
                pm.draw(model.named_vars["eta_events"], draws=1, random_seed=0)
            )
        au_start, au_end = frame["market_bounds"][1]
        assert np.all(val[au_start:au_end, :] == 0.0)
