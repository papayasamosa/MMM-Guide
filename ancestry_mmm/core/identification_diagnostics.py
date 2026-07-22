"""
Multicollinearity and weak-identification diagnostics (PR G1) - the layer
above core.diagnostics's single-model scorecard (convergence/fit/PPC/
plausibility): whether a fitted model's channel coefficients are trustworthy
enough to plan against at all, independent of whether the model converged
and fits the training data well. A model can converge cleanly and fit
beautifully while still having two channels whose individual coefficients
are essentially unidentifiable, because their spend moves together - none
of convergence, in-sample fit, or PPC coverage would ever surface that.

Four independent signals, each cheap enough to compute from an already-fit
model/trace (no new PyMC fit required, matching this codebase's "slow
fitting stays page-level and user-paced" convention -
core.diagnostics.expanding_window_backtest's `fit_fold_fn` injection pattern
is reused here for `leave_one_channel_out_sensitivity`, the one signal that
genuinely does require a caller-supplied refit):

- `channel_spend_correlation_matrix` / `high_correlation_pairs`: pairwise
  correlation of channel spend series - the most direct multicollinearity
  symptom (two channels whose spend moves together can't have their
  individual effects cleanly separated by the data, independent of anything
  about the model itself).
- `design_matrix_condition_number`: the condition number of the media
  design matrix - the standard numerical diagnostic for near-collinearity
  across every channel jointly, not just pairwise.
- `posterior_coefficient_stability`: per-`(outcome, channel)` coefficient's
  posterior coefficient of variation (std/mean across draws) - a Bayesian
  weak-identification signal that needs no refit at all.
- `leave_one_channel_out_sensitivity`: how much a channel's own coefficient
  moves when a correlated channel is dropped from the fit entirely -
  requires an actual refit per channel, so (like
  `expanding_window_backtest`) the caller supplies a `fit_without_channel_fn`
  rather than this module fitting anything itself.

`identification_report` bundles all four into one structured,
severity-ranked recommendation list - the same `{"level", "channel",
"message"}` shape `core.diagnostics.curve_plausibility_checks` already
uses, so a UI page can render both lists identically.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import arviz as az
import numpy as np
import pandas as pd

from .hierarchical_model import FHModelMeta

# Econometric rule-of-thumb thresholds (docs/decision_log.md) - "concerning"
# vs. "severe", not hard cutoffs; identification_report labels accordingly.
CORRELATION_WARNING_THRESHOLD = 0.7
CORRELATION_SEVERE_THRESHOLD = 0.9
CONDITION_NUMBER_WARNING_THRESHOLD = 30.0
CONDITION_NUMBER_SEVERE_THRESHOLD = 100.0
CV_WARNING_THRESHOLD = 0.5
CV_SEVERE_THRESHOLD = 1.0
SENSITIVITY_WARNING_PCT = 30.0
SENSITIVITY_SEVERE_PCT = 75.0


def channel_spend_correlation_matrix(frame: Dict, meta: FHModelMeta) -> pd.DataFrame:
    """Pairwise Pearson correlation of each channel's raw spend series
    (`frame["X_media"]`), channel x channel. The most direct
    multicollinearity symptom in an MMM: two channels whose spend moves
    together (a joint campaign, a shared seasonal budget pattern) cannot
    have their individual effects cleanly separated by the data alone,
    independent of anything about the model itself."""
    X = frame["X_media"]
    corr = np.corrcoef(X, rowvar=False)
    return pd.DataFrame(corr, index=meta.channels, columns=meta.channels)


def high_correlation_pairs(corr: pd.DataFrame, threshold: float = CORRELATION_WARNING_THRESHOLD) -> List[Tuple[str, str, float]]:
    """`(channel_a, channel_b, correlation)` triples with `abs(correlation)
    >= threshold`, upper triangle only - each pair reported once, never a
    channel against itself."""
    pairs = []
    channels = list(corr.columns)
    for i, a in enumerate(channels):
        for b in channels[i + 1:]:
            r = corr.loc[a, b]
            if abs(r) >= threshold:
                pairs.append((a, b, float(r)))
    return pairs


def design_matrix_condition_number(frame: Dict) -> float:
    """Condition number (ratio of largest to smallest singular value) of
    the raw media design matrix - the standard numerical multicollinearity
    diagnostic, sensitive to joint (not just pairwise) near-collinearity
    across every channel together. Returns `inf` for a degenerate (all-zero,
    or exactly rank-deficient) design matrix rather than raising - that is
    itself the most severe possible identification failure, not an error
    case to hide. Deliberately does not clip away a merely tiny (but
    nonzero) smallest singular value before taking the ratio - a
    near-duplicate pair of channels produces exactly that tiny-but-nonzero
    smallest singular value, and it is the whole point of this diagnostic to
    let it blow the condition number up."""
    X = frame["X_media"]
    singular_values = np.linalg.svd(X, compute_uv=False)
    largest, smallest = float(singular_values.max()), float(singular_values.min())
    if largest == 0.0 or smallest == 0.0:
        return float("inf")
    return largest / smallest


def posterior_coefficient_stability(trace: az.InferenceData, meta: FHModelMeta) -> pd.DataFrame:
    """Per-`(outcome, channel)` `beta`'s posterior mean/std/coefficient-of-
    variation (`std/mean`) - a Bayesian weak-identification signal that
    needs no refit: a channel whose data can't pin down its own effect
    shows up as a wide, high-CV posterior even within a single
    well-converged fit. `coefficient_of_variation` is `NaN` wherever
    `beta_mean <= 0` (a CV ratio is meaningless there, not silently zero)."""
    beta = trace.posterior["beta"]
    mean = beta.mean(dim=["chain", "draw"])
    std = beta.std(dim=["chain", "draw"])
    rows = []
    for oid in meta.outcome_ids:
        for ch in meta.channels:
            m = float(mean.sel(outcome=oid, channel=ch).values)
            s = float(std.sel(outcome=oid, channel=ch).values)
            cv = (s / m) if m > 0 else float("nan")
            rows.append({
                "outcome_id": oid, "channel": ch,
                "beta_mean": m, "beta_std": s, "coefficient_of_variation": cv,
            })
    return pd.DataFrame(rows)


def leave_one_channel_out_sensitivity(
    channels: List[str],
    fit_without_channel_fn: Callable[[str], Dict[str, float]],
    baseline_beta: Dict[str, float],
) -> pd.DataFrame:
    """
    How much each REMAINING channel's own coefficient moves when a given
    channel is dropped from the fit entirely - the strongest available
    signal that two channels are competing for the same credit: if dropping
    channel A barely changes channel B's coefficient, A and B are not
    meaningfully entangled; if B's coefficient jumps, the data alone cannot
    reliably tell them apart.

    Requires an actual refit per dropped channel, so - matching
    `core.diagnostics.expanding_window_backtest`'s `fit_fold_fn` injection -
    the caller supplies `fit_without_channel_fn(dropped_channel) ->
    {remaining_channel: beta}` (typically a page-level wrapper that slices
    the channel out of the frame/spec and refits); this module has no
    dependency on how long that takes. `baseline_beta` is the full model's
    own per-channel beta (any one outcome_id's row, or an aggregate - the
    caller decides what "beta" means for a channel here) to compare
    against.

    Returns one row per `(dropped_channel, remaining_channel)` pair with
    `baseline_beta`/`refit_beta`/`pct_change` (`NaN` wherever
    `baseline_beta` is missing or zero - a percentage change from zero is
    undefined, not silently infinite or zero).
    """
    rows = []
    for dropped in channels:
        refit_beta = fit_without_channel_fn(dropped)
        for remaining, new_beta in refit_beta.items():
            if remaining == dropped:
                continue
            old_beta = baseline_beta.get(remaining)
            if not old_beta:
                pct_change = float("nan")
            else:
                pct_change = (new_beta - old_beta) / abs(old_beta) * 100.0
            rows.append({
                "dropped_channel": dropped, "remaining_channel": remaining,
                "baseline_beta": old_beta, "refit_beta": new_beta, "pct_change": pct_change,
            })
    return pd.DataFrame(rows)


def identification_report(
    frame: Dict,
    meta: FHModelMeta,
    trace: az.InferenceData,
    *,
    sensitivity_df: Optional[pd.DataFrame] = None,
    correlation_threshold: float = CORRELATION_WARNING_THRESHOLD,
) -> List[Dict[str, str]]:
    """
    Structured, severity-ranked recommendation list combining every signal
    above - same `{"level", "channel", "message"}` shape as
    `core.diagnostics.curve_plausibility_checks`, so a UI page can render
    both lists identically. `sensitivity_df` (from
    `leave_one_channel_out_sensitivity`) is optional, since it requires an
    expensive refit the caller may not have run yet - the other three
    signals are always available from a single fitted trace.
    """
    flags: List[Dict[str, str]] = []

    corr = channel_spend_correlation_matrix(frame, meta)
    for a, b, r in high_correlation_pairs(corr, threshold=correlation_threshold):
        level = "error" if abs(r) >= CORRELATION_SEVERE_THRESHOLD else "warning"
        flags.append({
            "level": level, "channel": f"{a} / {b}",
            "message": f"'{a}' and '{b}' spend are highly correlated (r={r:.2f}) - their individual "
                       "effects may not be cleanly separable from the data alone.",
        })

    cond = design_matrix_condition_number(frame)
    if cond >= CONDITION_NUMBER_SEVERE_THRESHOLD:
        flags.append({
            "level": "error", "channel": "(all channels)",
            "message": f"Media design matrix condition number is severe ({cond:,.0f}) - channel effects "
                       "across this fit are jointly weakly identified.",
        })
    elif cond >= CONDITION_NUMBER_WARNING_THRESHOLD:
        flags.append({
            "level": "warning", "channel": "(all channels)",
            "message": f"Media design matrix condition number is elevated ({cond:,.0f}) - some channel "
                       "effects may be only weakly identified jointly.",
        })

    stability = posterior_coefficient_stability(trace, meta)
    for _, row in stability.iterrows():
        cv = row["coefficient_of_variation"]
        if pd.isna(cv):
            continue
        if cv >= CV_SEVERE_THRESHOLD:
            flags.append({
                "level": "error", "channel": row["channel"],
                "message": f"'{row['channel']}' effect on outcome '{row['outcome_id']}' has a very high "
                           f"posterior coefficient of variation ({cv:.2f}) - treat this coefficient as unreliable.",
            })
        elif cv >= CV_WARNING_THRESHOLD:
            flags.append({
                "level": "warning", "channel": row["channel"],
                "message": f"'{row['channel']}' effect on outcome '{row['outcome_id']}' has an elevated "
                           f"posterior coefficient of variation ({cv:.2f}).",
            })

    if sensitivity_df is not None:
        for _, row in sensitivity_df.iterrows():
            pct = row["pct_change"]
            if pd.isna(pct):
                continue
            if abs(pct) >= SENSITIVITY_SEVERE_PCT:
                flags.append({
                    "level": "error", "channel": row["remaining_channel"],
                    "message": f"Dropping '{row['dropped_channel']}' shifts '{row['remaining_channel']}'s "
                               f"coefficient by {pct:+.0f}% - these two channels are competing for the same "
                               "credit and are not reliably distinguishable.",
                })
            elif abs(pct) >= SENSITIVITY_WARNING_PCT:
                flags.append({
                    "level": "warning", "channel": row["remaining_channel"],
                    "message": f"Dropping '{row['dropped_channel']}' shifts '{row['remaining_channel']}'s "
                               f"coefficient by {pct:+.0f}%.",
                })

    return flags
