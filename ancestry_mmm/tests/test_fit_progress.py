"""Tests for `core.fit_progress` (2026-08-26 analyst follow-up to
WP2.11): the rate-limited, always-flushed sampler-progress reporter built
after a fold-refit backtest sat silent for 6+ hours with no visible
output. Pure-Python unit tests - no PyMC fit required."""

from __future__ import annotations

from ancestry_mmm.core.fit_progress import (
    FoldFitContext,
    SamplingProgressReporter,
    format_fold_fit_context_line,
)


def _stats(**overrides):
    base = dict(
        chain=0,
        draw_idx=0,
        tuning=True,
        completed=1,
        total=100,
        diverging=False,
        tree_depth=5,
        tree_size=31.0,
        step_size=0.01,
        reached_max_treedepth=False,
    )
    base.update(overrides)
    return base


class TestFormatFoldFitContextLine:
    def test_includes_fold_id_window_and_build_time(self):
        context = FoldFitContext(
            fold_id="fold_1",
            model_label="shared",
            train_start="2024-01-01",
            train_end="2024-05-12",
            n_obs=72,
            build_seconds=0.2,
        )
        line = format_fold_fit_context_line(context)
        assert "fold_1" in line
        assert "2024-01-01" in line and "2024-05-12" in line
        assert "72 obs" in line
        assert "0.2s" in line


class TestSamplingProgressReporterRateLimiting:
    def test_first_draw_is_always_emitted(self):
        lines = []
        reporter = SamplingProgressReporter("fold_1", emit=lines.append)
        reporter(_stats(completed=1, total=100))
        assert len(lines) == 1

    def test_last_draw_is_always_emitted_even_if_recent(self):
        lines = []
        reporter = SamplingProgressReporter(
            "fold_1", min_interval_seconds=9999, emit=lines.append
        )
        reporter(_stats(completed=1, total=100))
        reporter(_stats(completed=100, total=100))
        assert len(lines) == 2

    def test_intermediate_draws_are_throttled(self):
        lines = []
        reporter = SamplingProgressReporter(
            "fold_1", min_interval_seconds=9999, emit=lines.append
        )
        reporter(_stats(completed=1, total=100))
        for i in range(2, 50):
            reporter(_stats(completed=i, total=100))
        assert len(lines) == 1

    def test_a_divergence_is_never_throttled(self):
        lines = []
        reporter = SamplingProgressReporter(
            "fold_1", min_interval_seconds=9999, emit=lines.append
        )
        reporter(_stats(completed=1, total=100))
        reporter(_stats(completed=2, total=100, diverging=True))
        reporter(_stats(completed=3, total=100, diverging=True))
        assert len(lines) == 3

    def test_a_max_treedepth_hit_is_never_throttled(self):
        lines = []
        reporter = SamplingProgressReporter(
            "fold_1", min_interval_seconds=9999, emit=lines.append
        )
        reporter(_stats(completed=1, total=100))
        reporter(_stats(completed=2, total=100, reached_max_treedepth=True))
        assert len(lines) == 2

    def test_emitted_line_carries_the_real_nuts_geometry_not_only_progress(self):
        lines = []
        reporter = SamplingProgressReporter(
            "fold_7", model_label="shared", emit=lines.append
        )
        reporter(
            _stats(chain=1, draw_idx=3, step_size=0.0081, tree_depth=8, tree_size=255.0)
        )
        line = lines[0]
        assert "fold_7" in line
        assert "chain=1" in line
        assert "step_size=0.0081" in line
        assert "tree_depth=8" in line
        assert "tree_size=255" in line

    def test_step_size_none_does_not_crash_formatting(self):
        lines = []
        reporter = SamplingProgressReporter("fold_1", emit=lines.append)
        reporter(_stats(step_size=None))
        assert "step_size=n/a" in lines[0]
