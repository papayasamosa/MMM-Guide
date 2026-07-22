"""
Funnel-coherence diagnostics (PR E.2, requirement #7).

Sign-ups and GSAs (or any other upstream/downstream KPI pair, e.g. a DNA
kit purchase preceding a later cross-sell) are fitted as independent
Negative-Binomial outcome equations (`core.hierarchical_model`,
`core.market_specific_model`) - a valid first production approach, but one
that does not enforce `downstream <= upstream` or model the conversion
between them. **This module adds diagnostics and warnings only** - it does
NOT build a constrained funnel model (that remains a documented future
extension, see docs/decision_log.md and the module-level note at the
bottom of this file). Nothing here changes what gets fitted; it only flags
when the two independently-fitted equations look incoherent together.

`FunnelLink` is how an analyst tells these diagnostics which two
outcome_ids form a funnel pair - the model itself has no notion of this
relationship, so it must be configured explicitly (never inferred from
outcome_id naming).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


@dataclass
class FunnelLink:
    """One declared upstream -> downstream funnel relationship, e.g.
    `FunnelLink(upstream_outcome_id="fh_new_signup", downstream_outcome_id="fh_new_gsa")`.
    Every GSA has signed up, but not every sign-up becomes a GSA - so a
    coherent pair should always show `downstream <= upstream`, in both
    observed data and predictions, with an implied conversion rate in
    [0, 1]. Persisted and fingerprinted like the outcome catalogue itself
    (`funnel_links_fingerprint_payload`) - editing a funnel link is a
    calculation-relevant configuration change even though it never affects
    what gets fitted."""

    upstream_outcome_id: str
    downstream_outcome_id: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FunnelLink":
        return cls(
            upstream_outcome_id=d["upstream_outcome_id"],
            downstream_outcome_id=d["downstream_outcome_id"],
        )


def validate_funnel_links(links: List[FunnelLink], outcome_ids: Sequence[str]) -> List[str]:
    """
    Rejects (returns non-empty error list, never raises):

    - a link whose upstream_outcome_id/downstream_outcome_id isn't a known
      outcome_id
    - a link from an outcome_id to itself
    - a duplicate (upstream, downstream) pair
    """
    errors: List[str] = []
    known_ids = set(outcome_ids)
    seen = set()
    for link in links:
        if link.upstream_outcome_id == link.downstream_outcome_id:
            errors.append(
                f"Funnel link cannot use the same outcome_id ('{link.upstream_outcome_id}') as both "
                "upstream and downstream."
            )
        if link.upstream_outcome_id not in known_ids:
            errors.append(f"Funnel link references unknown upstream outcome_id '{link.upstream_outcome_id}'.")
        if link.downstream_outcome_id not in known_ids:
            errors.append(f"Funnel link references unknown downstream outcome_id '{link.downstream_outcome_id}'.")
        pair = (link.upstream_outcome_id, link.downstream_outcome_id)
        if pair in seen:
            errors.append(f"Duplicate funnel link: {link.upstream_outcome_id} -> {link.downstream_outcome_id}.")
        seen.add(pair)
    return errors


_FUNNEL_LINK_FINGERPRINT_FIELDS = ("upstream_outcome_id", "downstream_outcome_id")


def funnel_links_fingerprint_payload(links: List[FunnelLink]) -> List[dict]:
    """The calculation-relevant (here: all of it - a `FunnelLink` has only
    two fields) payload for `core.fingerprint.fingerprint_model_spec`,
    sorted so two link lists with the same pairs in a different order
    fingerprint identically."""
    return [
        {f: getattr(link, f) for f in _FUNNEL_LINK_FINGERPRINT_FIELDS}
        for link in sorted(links, key=lambda link: (link.upstream_outcome_id, link.downstream_outcome_id))
    ]


def funnel_coherence_diagnostics(
    link: FunnelLink,
    upstream_values: np.ndarray,
    downstream_values: np.ndarray,
    *,
    period_labels: Optional[Sequence[Any]] = None,
    conversion_cv_threshold: float = 0.75,
) -> Dict[str, Any]:
    """
    Diagnostics/warnings only (never raises, never blocks a fit or a
    scenario) for one funnel pair over a series of aligned periods
    (e.g. one row per (market, week) - `upstream_values`/`downstream_values`
    must be the same length and in the same period order). Checks:

    - `downstream > upstream` in a period ("GSA > sign-up") - a coherence
      violation regardless of whether the values are observed or predicted.
    - implied conversion rate (`downstream / upstream`) outside [0, 1] -
      only evaluated where `upstream > 0` (undefined otherwise, not "0").
    - an unstable conversion rate across periods - flagged when its
      coefficient of variation exceeds `conversion_cv_threshold` (a
      documented default, not validated against real Ancestry data).

    Returns a plain dict (never a status enum) so a caller can display every
    number, not just a boolean - `has_any_warning` is a convenience roll-up.
    `period_labels` (e.g. dates or (market, date) tuples), if given, names
    which periods actually violated, so the UI can point at exactly which
    weeks/markets look wrong.
    """
    upstream_values = np.asarray(upstream_values, dtype=float)
    downstream_values = np.asarray(downstream_values, dtype=float)
    if upstream_values.shape != downstream_values.shape:
        raise ValueError(
            f"upstream_values and downstream_values must be the same shape, got "
            f"{upstream_values.shape} and {downstream_values.shape}."
        )
    n = int(upstream_values.shape[0])

    violation_mask = downstream_values > upstream_values
    n_violations = int(violation_mask.sum())

    with np.errstate(divide="ignore", invalid="ignore"):
        conversion_rate = np.where(upstream_values > 0, downstream_values / upstream_values, np.nan)
    valid_rates = conversion_rate[~np.isnan(conversion_rate)]
    out_of_range_mask = ~np.isnan(conversion_rate) & ((conversion_rate < 0) | (conversion_rate > 1))
    n_out_of_range = int(out_of_range_mask.sum())

    conversion_rate_mean = float(np.mean(valid_rates)) if len(valid_rates) else None
    conversion_rate_cv = (
        float(np.std(valid_rates) / conversion_rate_mean)
        if conversion_rate_mean is not None and conversion_rate_mean > 0 and len(valid_rates) > 1
        else None
    )
    unstable = conversion_rate_cv is not None and conversion_rate_cv > conversion_cv_threshold

    def _labels(mask: np.ndarray) -> Optional[List[Any]]:
        if period_labels is None:
            return None
        idx = np.where(mask)[0]
        return [period_labels[i] for i in idx]

    return {
        "upstream_outcome_id": link.upstream_outcome_id,
        "downstream_outcome_id": link.downstream_outcome_id,
        "n_periods": n,
        "n_violations": n_violations,
        "violation_rate": (n_violations / n) if n else 0.0,
        "violation_periods": _labels(violation_mask),
        "conversion_rate_mean": conversion_rate_mean,
        "conversion_rate_out_of_range_count": n_out_of_range,
        "conversion_rate_out_of_range_periods": _labels(out_of_range_mask),
        "conversion_rate_cv": conversion_rate_cv,
        "conversion_rate_unstable": unstable,
        "has_any_warning": n_violations > 0 or n_out_of_range > 0 or unstable,
    }


def funnel_channel_attribution_consistency(
    link: FunnelLink, channel_summary_df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Diagnostic-only check for "media attribution inconsistent across funnel
    stages": flags a channel whose contribution sign differs between the
    upstream and downstream outcome of `link` (positive for one, negative
    for the other) - a channel genuinely acting through the funnel
    shouldn't credibly drive one stage up and the other down. This is a
    descriptive divergence check, not a claim about the true causal channel
    ordering (see this module's docstring: the fits are parallel outcome
    equations, each with its own independently estimated channel
    coefficients - a difference here does not by itself prove an error).

    `channel_summary_df` is the shape `core.attribution.outcome_channel_summary`/
    `core.market_specific_attribution.outcome_channel_market_summary` produce
    (columns include at least `channel`, `outcome_id`, `volume_contribution`).
    """
    up = (
        channel_summary_df[channel_summary_df["outcome_id"] == link.upstream_outcome_id]
        .groupby("channel")["volume_contribution"].sum()
    )
    down = (
        channel_summary_df[channel_summary_df["outcome_id"] == link.downstream_outcome_id]
        .groupby("channel")["volume_contribution"].sum()
    )
    channels = sorted(set(up.index) | set(down.index))
    up_total = float(up.sum()) if len(up) else 0.0
    down_total = float(down.sum()) if len(down) else 0.0

    inconsistent_channels = []
    for ch in channels:
        up_val = float(up.get(ch, 0.0))
        down_val = float(down.get(ch, 0.0))
        if up_val == 0.0 and down_val == 0.0:
            continue
        if (up_val > 0) != (down_val > 0):
            inconsistent_channels.append({
                "channel": ch,
                "upstream_contribution": up_val,
                "downstream_contribution": down_val,
                "upstream_share": (up_val / up_total) if up_total else None,
                "downstream_share": (down_val / down_total) if down_total else None,
                "reason": "sign_mismatch",
            })

    return {
        "upstream_outcome_id": link.upstream_outcome_id,
        "downstream_outcome_id": link.downstream_outcome_id,
        "inconsistent_channels": inconsistent_channels,
        "has_any_warning": bool(inconsistent_channels),
    }


# ---------------------------------------------------------------------------
# Explicitly out of scope for PR E.2 (documented per the instruction
# document's "do not build the full funnel model" requirement):
#
#   sign-ups model
#   conversion model conditional on sign-ups
#   GSA = sign-ups x conversion probability
#
# A future constrained funnel model may use exactly that structure, but only
# after real-data diagnostics (this module) and identifiability work - see
# docs/decision_log.md. The current fits remain independent parallel outcome
# equations; nothing here changes that.
# ---------------------------------------------------------------------------
