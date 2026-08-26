"""Tests for `core.models.fit_model`'s `stats_callback` (2026-08-26
analyst follow-up to WP2.11): live per-draw NUTS geometry, added after a
fold-refit backtest sat silent for 6+ hours with no visibility into
whether it was still making progress. `stats_callback` is a purely
additive optional parameter, so this file exists alongside (not instead
of) every other `fit_model` caller's existing tests, none of which pass it
and must therefore see byte-for-byte unchanged behaviour.

Deliberately paced for normal blocking CI: exactly one real MCMC fit,
module-scoped so every test in this file reuses it - matching
test_fold_refit_service.py/test_predictive_density.py's established "pay
the real-fit cost once" pattern."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from ancestry_mmm.core.models import build_loglog_model, fit_model


def _tiny_model():
    rng = np.random.default_rng(0)
    n_obs, n_channels = 24, 2
    X_media = rng.uniform(10, 100, size=(n_obs, n_channels))
    X_fourier = rng.normal(size=(n_obs, 4))
    trend = np.linspace(0, 1, n_obs)
    y = 50 + X_media.sum(axis=1) * 0.5 + rng.normal(scale=2, size=n_obs)
    return build_loglog_model(
        X_media, X_fourier, trend, y, channel_names=["tv", "radio"]
    )


@pytest.fixture(scope="module")
def fit_with_both_callbacks():
    """The one real (tiny) fit this file pays for, with both
    `progress_callback` and `stats_callback` supplied together so a single
    fit proves both keep working side by side."""
    progress_events = []
    stats_events = []
    trace = fit_model(
        _tiny_model(),
        draws=10,
        tune=10,
        chains=1,
        cores=1,
        random_seed=1,
        progress_callback=lambda done, total: progress_events.append((done, total)),
        stats_callback=stats_events.append,
    )
    return trace, progress_events, stats_events


class TestStatsCallbackIsPurelyAdditive:
    def test_stats_callback_defaults_to_none(self):
        # No fit needed to prove this - a signature-level guarantee that
        # every pre-existing fit_model caller sees unchanged behaviour.
        assert inspect.signature(fit_model).parameters["stats_callback"].default is None

    def test_a_fit_with_callbacks_still_returns_a_normal_trace(
        self, fit_with_both_callbacks
    ):
        trace, _, _ = fit_with_both_callbacks
        assert "posterior" in trace.groups()

    def test_progress_callback_still_works_alongside_stats_callback(
        self, fit_with_both_callbacks
    ):
        _, progress_events, _ = fit_with_both_callbacks
        assert len(progress_events) > 0
        assert progress_events[-1][1] == 20  # (draws + tune) * chains


class TestStatsCallbackCarriesRealNutsGeometry:
    def test_fires_once_per_draw_with_expected_keys(self, fit_with_both_callbacks):
        _, _, events = fit_with_both_callbacks
        assert len(events) == 20  # (draws + tune) * chains
        for e in events:
            for key in (
                "chain",
                "draw_idx",
                "tuning",
                "completed",
                "total",
                "diverging",
                "tree_depth",
                "tree_size",
                "step_size",
                "reached_max_treedepth",
            ):
                assert key in e
            assert isinstance(e["diverging"], bool)
            assert isinstance(e["reached_max_treedepth"], bool)
            assert e["tree_depth"] is not None
            assert e["step_size"] is not None

    def test_tuning_flag_transitions_from_true_to_false(self, fit_with_both_callbacks):
        _, _, events = fit_with_both_callbacks
        tune_flags = [e["tuning"] for e in events]
        assert tune_flags[0] is True
        assert tune_flags[-1] is False

    def test_both_callbacks_produce_the_same_event_count(self, fit_with_both_callbacks):
        _, progress_events, stats_events = fit_with_both_callbacks
        assert len(progress_events) == len(stats_events)
