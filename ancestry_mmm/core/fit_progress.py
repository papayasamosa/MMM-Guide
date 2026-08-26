"""Live fit-sampling progress instrumentation - framework-independent (no
Streamlit import, matching `core.market_data_capability`'s own convention),
reusable by any caller (fold-refit backtest scripts, future Streamlit pages)
that wants visibility into a long-running `core.models.fit_model` call
instead of discovering only after it finishes - or after waiting silently
for hours - whether it is making progress at all.

Motivated directly by the WP2.11 item-5 backtest incident (2026-08-26): a
fold-refit run sat silent for 6+ hours with no visible output because (a)
its wrapper script's stdout was fully block-buffered, so even PyMC's own
progress bar text was invisible until the process exited, and (b)
`core.models.fit_model`'s own `progress_callback` only ever exposed
`(n_done, n_total)`, never the underlying NUTS geometry (step size, tree
depth, divergences) that would have explained *why* it was slow. This
module addresses both: every line is emitted through an explicit `emit`
callable (default `print(..., flush=True)`, forcing a flush regardless of
the process's own buffering mode - a caller never needs to remember to set
an environment variable for this to work), and every line carries the real
NUTS stats PyMC's own step method already computes (`core.models.
fit_model`'s `stats_callback` dict) - never a second, independently-derived
approximation of the sampler's own geometry.

Purely additive instrumentation: nothing here changes a model's
specification, priors, or fitting methodology, and every entry point that
uses it (`application.fold_refit_service`) does so through a new
`on_progress_line: Optional[Callable[[str], None]] = None` parameter that
defaults to `None` - existing callers see byte-for-byte unchanged behaviour.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


def _emit_flushed(line: str) -> None:
    print(line, flush=True)


@dataclass(frozen=True)
class FoldFitContext:
    """Static, pre-sampling context for one fold's fit - reported once
    before sampling starts, so a caller knows what is about to run (and how
    much data it has to work with) before waiting on it."""

    fold_id: str
    model_label: str
    train_start: Optional[str]
    train_end: Optional[str]
    n_obs: int
    build_seconds: float


def format_fold_fit_context_line(context: FoldFitContext) -> str:
    return (
        f"[{context.fold_id}] {context.model_label}: training "
        f"{context.train_start}..{context.train_end} ({context.n_obs} obs), "
        f"model build took {context.build_seconds:.1f}s"
    )


class SamplingProgressReporter:
    """Rate-limited formatter/emitter for `core.models.fit_model`'s
    `stats_callback` dicts.

    Emits at most one line per `min_interval_seconds` under normal sampling,
    but a divergence, a max-treedepth hit, or the very first/last draw is
    always emitted regardless of the rate limit - those are exactly the
    signals a caller investigating a slow-looking fit needs to see, and
    throttling them away would recreate the same "no idea what is happening"
    problem this module exists to fix.
    """

    def __init__(
        self,
        fold_id: str,
        model_label: str = "",
        min_interval_seconds: float = 5.0,
        emit: Callable[[str], None] = _emit_flushed,
    ) -> None:
        self._fold_id = fold_id
        self._model_label = model_label
        self._min_interval = min_interval_seconds
        self._emit = emit
        self._start = time.monotonic()
        self._last_emit = 0.0

    def __call__(self, stats: Dict[str, Any]) -> None:
        now = time.monotonic()
        is_notable = bool(stats.get("diverging")) or bool(
            stats.get("reached_max_treedepth")
        )
        completed = stats.get("completed")
        total = stats.get("total")
        is_boundary = completed in (1, total)
        if (
            not (is_notable or is_boundary)
            and (now - self._last_emit) < self._min_interval
        ):
            return
        self._last_emit = now
        self._emit(self._format(stats, elapsed=now - self._start))

    def _format(self, stats: Dict[str, Any], elapsed: float) -> str:
        completed = max(stats.get("completed", 0) or 0, 1)
        rate = elapsed / completed
        phase = "tune" if stats.get("tuning") else "sample"
        step_size = stats.get("step_size")
        step_size_str = f"{step_size:.4g}" if step_size is not None else "n/a"
        return (
            f"[{self._fold_id}] {self._model_label} "
            f"chain={stats.get('chain')} draw={stats.get('draw_idx')} "
            f"({phase}) {stats.get('completed')}/{stats.get('total')} "
            f"elapsed={elapsed:.1f}s ({rate:.2f}s/draw) "
            f"step_size={step_size_str} tree_depth={stats.get('tree_depth')} "
            f"tree_size={stats.get('tree_size')} "
            f"diverging={stats.get('diverging')} "
            f"max_treedepth_hit={stats.get('reached_max_treedepth')}"
        )
