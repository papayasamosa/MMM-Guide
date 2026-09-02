"""Fast structural tests (real `pm.Model` + `pm.draw`, never `pm.sample` -
mirrors `test_hierarchical_model.py`'s own `TestSingleChannelSingleMarket
SurvivesPmDraw` exception to its "don't build a PyMC model in tests"
convention) confirming `core.hierarchical_model.build_fh_hierarchical_
model`'s new `named_event_fit_inputs` parameter (Decision 12) is wired
correctly into the real production builder:

- `named_event_fit_inputs=None` (the default) must add nothing to the
  model graph at all - no `event_*` variable exists, and `FHModelMeta`'s
  new provenance fields stay empty/blank. This is the backward-
  compatibility guarantee: every project with no named event opted in
  fits byte-for-byte identically to before this parameter existed.
- A real, supplied `NamedEventFitInputs` must add exactly the expected
  `event_tau_<family>`/`event_coefs_<family>_<market>`/`eta_events`
  variables, with the expected shapes, and `FHModelMeta` must record
  which response definition was actually consumed.
- Outcome scope must actually restrict which outcome's `eta` receives the
  event contribution - not silently apply to every outcome.

The real posterior-recovery evidence that this wiring lets a fitted model
actually recover a planted event effect (not just "the code runs without
error") lives in the separate, slower
`test_named_event_response_recovery_posterior.py` (schedule/manual-only,
mirroring `test_search_candidate_a_recovery_posterior.py`'s own
precedent - real NUTS sampling is too slow for this fast structural
file)."""

from __future__ import annotations

import numpy as np
import pymc as pm

from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.named_event_fit_inputs import build_named_event_fit_inputs
from ancestry_mmm.core.named_event_response import NAMED_EVENT_RESPONSE_STRUCTURE
from ancestry_mmm.core.named_events import (
    DEFAULT_EVENT_EVIDENCE_STATUS,
    EventResponseDefinition,
    NamedEventFamily,
    NamedEventOccurrence,
)
from ancestry_mmm.core.schema import ModelSpec


def _frame(n_weeks: int = 16, outcomes=("fh_new",)):
    dates = np.array(
        [f"2026-{1 + (i // 4):02d}-{1 + 7 * (i % 4):02d}" for i in range(n_weeks)],
        dtype="datetime64[ns]",
    )
    n_outcomes = len(outcomes)
    return {
        "markets": ["UK"],
        "market_idx": np.zeros(n_weeks, dtype=int),
        "market_bounds": [(0, n_weeks)],
        "dates": dates,
        "channels": ["TV"],
        "dna_channel_idx": [],
        "outcome_ids": list(outcomes),
        "X_media": np.full((n_weeks, 1), 100.0),
        "Y": np.full((n_weeks, n_outcomes), 10.0),
        "promo": np.zeros((n_weeks, n_outcomes)),
        "X_controls": np.zeros((n_weeks, 0)),
        "control_names": [],
        "fourier": np.zeros((n_weeks, 2)),
        "trend": np.linspace(1.0, 1.1, n_weeks),
        "unpooled_markets": [],
    }


def _spec(outcomes=("fh_new",)):
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={o: f"{o}_gsa" for o in outcomes},
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
        "max_lead": 2,
        "max_lag": 0,
        "transformation_method_reference": NAMED_EVENT_RESPONSE_STRUCTURE,
    }
    values.update(overrides)
    return EventResponseDefinition(**values)


class TestNoFitInputsIsByteIdenticalToBefore:
    def test_default_none_adds_no_event_variables(self):
        frame = _frame()
        model, meta = build_fh_hierarchical_model(frame, _spec())
        event_vars = [name for name in model.named_vars if name.startswith("event_")]
        assert event_vars == []
        assert "eta_events" not in model.named_vars
        assert meta.named_event_response_definitions_at_fit == []
        assert meta.named_event_response_method_version == ""

    def test_explicit_none_is_identical_to_omitting_the_argument(self):
        frame = _frame()
        model_a, meta_a = build_fh_hierarchical_model(frame, _spec())
        model_b, meta_b = build_fh_hierarchical_model(
            frame, _spec(), named_event_fit_inputs=None
        )
        assert set(model_a.named_vars) == set(model_b.named_vars)
        assert meta_a.named_event_response_definitions_at_fit == (
            meta_b.named_event_response_definitions_at_fit
        )


class TestSuppliedFitInputsWireIntoTheRealModel:
    def _built(self, outcomes=("fh_new",), outcome_scope=()):
        frame = _frame(outcomes=outcomes)
        fit_inputs = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[_occurrence()],
            response_definitions=[_definition(outcome_scope=outcome_scope)],
        )
        assert fit_inputs is not None
        model, meta = build_fh_hierarchical_model(
            frame, _spec(outcomes=outcomes), named_event_fit_inputs=fit_inputs
        )
        return model, meta, frame

    def test_expected_event_variables_are_created(self):
        model, _meta, _frame_dict = self._built()
        assert "event_tau_mothers_day" in model.named_vars
        assert "event_coefs_mothers_day_UK" in model.named_vars
        assert "eta_events" in model.named_vars

    def test_meta_records_the_consumed_response_definition(self):
        _model, meta, _frame_dict = self._built()
        assert meta.named_event_response_definitions_at_fit == [("md-def", 1)]
        assert (
            meta.named_event_response_method_version == NAMED_EVENT_RESPONSE_STRUCTURE
        )

    def test_eta_events_has_the_right_shape_and_is_not_trivially_zero(self):
        model, _meta, frame = self._built()
        with model:
            val = np.asarray(
                pm.draw(model.named_vars["eta_events"], draws=1, random_seed=0)
            )
        n_weeks = len(frame["dates"])
        assert val.shape == (n_weeks, 1)
        assert np.any(val != 0.0)

    def test_unscoped_definition_applies_to_every_outcome(self):
        model, _meta, frame = self._built(outcomes=("fh_new", "fh_other"))
        with model:
            val = np.asarray(
                pm.draw(model.named_vars["eta_events"], draws=1, random_seed=0)
            )
        assert val.shape == (len(frame["dates"]), 2)
        # Both outcome columns share the identical contribution when no
        # outcome_scope restricts it - same coefficients, same design.
        np.testing.assert_allclose(val[:, 0], val[:, 1])

    def test_scoped_definition_only_affects_the_named_outcome(self):
        model, _meta, frame = self._built(
            outcomes=("fh_new", "fh_other"), outcome_scope=("fh_new",)
        )
        with model:
            val = np.asarray(
                pm.draw(model.named_vars["eta_events"], draws=1, random_seed=0)
            )
        assert np.any(val[:, 0] != 0.0)
        assert np.all(val[:, 1] == 0.0)


class TestPoolingIsUnpooledPerMarketByDefault:
    def test_two_markets_get_independent_coefficient_vectors(self):
        n_weeks_per_market = 16
        frame = {
            "markets": ["UK", "AU"],
            "market_idx": np.array([0] * n_weeks_per_market + [1] * n_weeks_per_market),
            "market_bounds": [
                (0, n_weeks_per_market),
                (n_weeks_per_market, 2 * n_weeks_per_market),
            ],
            "dates": np.concatenate(
                [
                    _frame(n_weeks_per_market)["dates"],
                    _frame(n_weeks_per_market)["dates"],
                ]
            ),
            "channels": ["TV"],
            "dna_channel_idx": [],
            "outcome_ids": ["fh_new"],
            "X_media": np.full((2 * n_weeks_per_market, 1), 100.0),
            "Y": np.full((2 * n_weeks_per_market, 1), 10.0),
            "promo": np.zeros((2 * n_weeks_per_market, 1)),
            "X_controls": np.zeros((2 * n_weeks_per_market, 0)),
            "control_names": [],
            "fourier": np.zeros((2 * n_weeks_per_market, 2)),
            "trend": np.linspace(1.0, 1.1, 2 * n_weeks_per_market),
            "unpooled_markets": [],
        }
        spec = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK", "AU"],
            segment_outcomes={"fh_new": "fh_new_gsa"},
            channels=["TV"],
        )
        fit_inputs = build_named_event_fit_inputs(
            frame,
            families=[_family()],
            occurrences=[
                _occurrence(event_id="md-uk", market_scope=("UK",)),
                _occurrence(event_id="md-au", market_scope=("AU",)),
            ],
            response_definitions=[_definition()],
        )
        assert fit_inputs is not None
        model, _meta = build_fh_hierarchical_model(
            frame, spec, named_event_fit_inputs=fit_inputs
        )
        assert "event_coefs_mothers_day_UK" in model.named_vars
        assert "event_coefs_mothers_day_AU" in model.named_vars
        # One shared tau per family - not per market.
        assert "event_tau_mothers_day" in model.named_vars
        assert "event_tau_mothers_day_UK" not in model.named_vars
