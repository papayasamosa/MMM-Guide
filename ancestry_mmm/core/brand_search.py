"""
Brand Search treatment modes (PR G1).

Brand Search spend is a notoriously ambiguous MMM channel: some of its
"response" is genuinely incremental (a Brand Search ad captures a converting
visitor who wouldn't have found the site otherwise), and some is demand that
upper-funnel channels (TV, YouTube, etc.) already created - Brand Search
just happens to be the last click before conversion, effectively
double-counting media credit those upper-funnel channels already earned.
Fitting the "true" causal split requires either an incrementality experiment
(a geo holdout) or a full causal DAG (out of scope for PR G1 - "do not yet
build ... causal DAG", docs/decision_log.md). What PR G1 ships instead is
four explicit, analyst-chosen TREATMENT MODES for Brand Search, each with
transparent, documented mechanics - never a silent default assumption about
which one is "true":

- `direct_channel`: Brand Search is an ordinary `primary_direct` media
  channel (`core.pathways`) - its fitted coefficient captures its full
  observed association with the outcome, including any upper-funnel demand
  it captures. Known bias: this OVERSTATES Brand Search's true incremental
  value whenever upper-funnel channels genuinely drive some of its clicks.
- `excluded`: Brand Search spend is excluded entirely (`core.pathways`
  `excluded` role - zero contribution, deterministically). Conservative:
  never overstates Brand Search, but understates total measured media
  impact if Brand Search actually has some genuinely incremental effect of
  its own.
- `demand_capture_mediator`: Brand Search is fit exactly like
  `direct_channel` (same `primary_direct` mechanics, same fitted beta), but
  its REPORTED contribution is decomposed post-hoc: `mediation_share` (an
  analyst-supplied fraction, not fitted) of its contribution is reallocated
  onto the specific upper-funnel channels declared in `mediator_of`
  ("analyst-approved edges only" - never auto-detected) in proportion to
  each channel's own contribution that period; the rest stays with Brand
  Search as genuinely incremental. See `mediator_reallocation`.
- `experiment_calibrated_incremental`: Brand Search's reported contribution
  is scaled by `calibration_factor` (a ratio in `[0, 1]`), supplied from an
  external incrementality test (a geo holdout, a platform-run conversion
  lift study) - the fitted coefficient still exists (Brand Search remains a
  `primary_direct` channel in the model, same fitting mechanics as
  `direct_channel`), but `apply_experiment_calibration` scales its raw
  contribution down to the test-measured incremental share before it's used
  for reporting or planning.

None of these change how the PyMC likelihood is built beyond the existing
`primary_direct`/`excluded` pathway roles (`core.pathways`) -
`brand_search_pathway_role` is the only touchpoint into fitting;
everything else here operates on already-fitted contribution series at
report/attribution time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import pandas as pd

MODE_DIRECT_CHANNEL = "direct_channel"
MODE_EXCLUDED = "excluded"
MODE_ASSUMPTION_BASED_REALLOCATION = "assumption_based_demand_capture_reallocation"
# Deprecated persisted key; normalised on load and never presented as mediation.
MODE_DEMAND_CAPTURE_MEDIATOR = "demand_capture_mediator"
MODE_EXPERIMENTAL_FITTED_MEDIATION = "experimental_fitted_mediation"
MODE_EXPERIMENT_CALIBRATED_INCREMENTAL = "experiment_calibrated_incremental"

BRAND_SEARCH_MODES = (
    MODE_DIRECT_CHANNEL,
    MODE_EXCLUDED,
    MODE_ASSUMPTION_BASED_REALLOCATION,
    MODE_DEMAND_CAPTURE_MEDIATOR,
    MODE_EXPERIMENTAL_FITTED_MEDIATION,
    MODE_EXPERIMENT_CALIBRATED_INCREMENTAL,
)


@dataclass
class BrandSearchConfig:
    """One Brand Search channel's treatment mode and mode-specific
    parameters. `mediator_of`/`mediation_share` are only meaningful (and
    required, see `validate`) for `demand_capture_mediator`;
    `calibration_factor` only for `experiment_calibrated_incremental` -
    fields not required by the chosen `mode` are simply left `None`/empty."""
    channel: str
    mode: str
    mediator_of: List[str] = field(default_factory=list)
    mediation_share: Optional[float] = None
    calibration_factor: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BrandSearchConfig":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def validate(self, known_channels: Optional[List[str]] = None) -> List[str]:
        errors: List[str] = []
        label = self.channel or "(unnamed)"
        if not self.channel:
            errors.append("Every Brand Search config needs a channel.")
        if self.mode not in BRAND_SEARCH_MODES:
            errors.append(f"'{label}' has unknown Brand Search mode '{self.mode}' (expected one of {BRAND_SEARCH_MODES}).")
            return errors  # nothing further to validate against an unrecognised mode

        if self.mode in (MODE_DEMAND_CAPTURE_MEDIATOR, MODE_ASSUMPTION_BASED_REALLOCATION, MODE_EXPERIMENTAL_FITTED_MEDIATION):
            if not self.mediator_of:
                errors.append(
                    f"'{label}' is set to {MODE_DEMAND_CAPTURE_MEDIATOR} but has no mediator_of channels "
                    "declared - which upstream channels it mediates must be explicit (analyst-approved), never inferred."
                )
            if self.channel in self.mediator_of:
                errors.append(f"'{label}' cannot be listed as its own mediator_of channel.")
            if known_channels is not None:
                unknown = [c for c in self.mediator_of if c not in known_channels]
                if unknown:
                    errors.append(f"'{label}' mediator_of references unknown channel(s): {unknown}.")
            if self.mediation_share is None:
                errors.append(
                    f"'{label}' is set to {MODE_DEMAND_CAPTURE_MEDIATOR} but has no mediation_share - the "
                    "assumed fraction of its contribution attributable to upstream demand capture must be "
                    "supplied explicitly, there is no safe default."
                )
            elif not (0.0 <= self.mediation_share <= 1.0):
                errors.append(f"'{label}' mediation_share must be within [0, 1], got {self.mediation_share}.")

        if self.mode == MODE_EXPERIMENT_CALIBRATED_INCREMENTAL:
            if self.calibration_factor is None:
                errors.append(
                    f"'{label}' is set to {MODE_EXPERIMENT_CALIBRATED_INCREMENTAL} but has no calibration_factor - "
                    "an external incrementality test result must be supplied explicitly, there is no safe default."
                )
            elif not (0.0 <= self.calibration_factor <= 1.0):
                errors.append(f"'{label}' calibration_factor must be within [0, 1], got {self.calibration_factor}.")

        return errors


def validate_brand_search_configs(
    configs: List[BrandSearchConfig], known_channels: Optional[List[str]] = None,
) -> List[str]:
    errors: List[str] = []
    for c in configs:
        errors.extend(c.validate(known_channels))
    seen = set()
    for c in configs:
        if c.channel in seen:
            errors.append(f"Duplicate Brand Search config for channel '{c.channel}'.")
        seen.add(c.channel)
    return errors


def brand_search_pathway_role(mode: str) -> str:
    """Which `core.pathways` role this Brand Search mode maps onto for
    fitting - `direct_channel`/`demand_capture_mediator`/
    `experiment_calibrated_incremental` all fit as `primary_direct` (they
    only differ in how the fitted contribution is REPORTED afterwards, not
    in how it's fit); `excluded` maps to the `excluded` role, dropping the
    channel from the likelihood's media term entirely."""
    if mode not in BRAND_SEARCH_MODES:
        raise ValueError(f"Unknown Brand Search mode '{mode}' (expected one of {BRAND_SEARCH_MODES}).")
    return "excluded" if mode == MODE_EXCLUDED else "primary_direct"


def mediator_reallocation(
    config: BrandSearchConfig,
    brand_search_contribution: pd.Series,
    upstream_contributions: Dict[str, pd.Series],
) -> pd.DataFrame:
    """
    Deterministic post-hoc reallocation for `demand_capture_mediator` mode.
    `config.mediation_share` of `brand_search_contribution` is treated as
    demand-captured (mediated) rather than genuinely incremental, and split
    across `config.mediator_of` in proportion to each channel's OWN
    contribution that period (a bigger upstream driver is assumed to
    generate proportionally more of the demand Brand Search later
    captures) - an explicit, documented rule, not a fitted causal estimate.
    A period where every declared mediator has zero (or negative, clipped)
    contribution has nothing to allocate its mediated share to, so that
    share folds back onto `direct` for that period rather than being
    silently discarded.

    Returns a DataFrame with a `direct` column and one `mediated_by_<channel>`
    column per `mediator_of` entry, indexed like `brand_search_contribution`.
    Reconciles exactly - `direct + sum(mediated_by_*) ==
    brand_search_contribution` for every row (required test case: "mediator
    decomposition reconciles") - since every reallocated amount comes out of
    the same total, never an independent estimate that could over- or
    under-shoot it.
    """
    if config.mode not in (MODE_DEMAND_CAPTURE_MEDIATOR, MODE_ASSUMPTION_BASED_REALLOCATION):
        raise ValueError(f"mediator_reallocation only applies to '{MODE_DEMAND_CAPTURE_MEDIATOR}' mode, got '{config.mode}'.")

    mediator_of = config.mediator_of
    mediated_pool = brand_search_contribution * config.mediation_share
    direct = brand_search_contribution - mediated_pool

    upstream_total = sum(upstream_contributions[c].clip(lower=0.0) for c in mediator_of)
    safe_upstream_total = upstream_total.where(upstream_total > 0)

    result = pd.DataFrame(index=brand_search_contribution.index)
    mediated_assigned = pd.Series(0.0, index=brand_search_contribution.index)
    for c in mediator_of:
        share = (upstream_contributions[c].clip(lower=0.0) / safe_upstream_total).fillna(0.0)
        col = f"mediated_by_{c}"
        result[col] = share * mediated_pool
        mediated_assigned = mediated_assigned + result[col]

    # Any period with zero upstream activity across every declared mediator
    # has nothing to allocate its mediated pool to - fold it back onto
    # direct so reconciliation holds exactly for every row.
    unassigned = mediated_pool - mediated_assigned
    result["direct"] = direct + unassigned
    return result[["direct"] + [f"mediated_by_{c}" for c in mediator_of]]


def apply_experiment_calibration(config: BrandSearchConfig, raw_contribution: pd.Series) -> pd.Series:
    """Scale a Brand Search channel's raw fitted contribution by its
    external incrementality test's `calibration_factor` - only meaningful
    for `experiment_calibrated_incremental` mode."""
    if config.mode != MODE_EXPERIMENT_CALIBRATED_INCREMENTAL:
        raise ValueError(
            f"apply_experiment_calibration only applies to '{MODE_EXPERIMENT_CALIBRATED_INCREMENTAL}' mode, got '{config.mode}'."
        )
    return raw_contribution * config.calibration_factor


@dataclass(frozen=True)
class FittedMediationResult:
    """Experimental two-equation mediation estimates (not production default)."""
    direct_effect: Dict[str, float]
    indirect_effect: Dict[str, float]
    total_effect: Dict[str, float]
    residual_brand_search_effect: float
    credible_intervals: Dict[str, tuple]


def fit_experimental_brand_search_mediation(brand_search, outcome, upstream_media, *, permitted_upstream_edges, controls=None):
    """Fit the explicit two-equation linear mediation specification.

    Only analyst-permitted columns enter equation one. Confidence intervals
    use a normal approximation and are clearly returned as experimental.
    """
    import numpy as np
    names = list(permitted_upstream_edges)
    if not names:
        raise ValueError("Experimental fitted mediation requires explicit permitted upstream edges.")
    missing = [n for n in names if n not in upstream_media]
    if missing:
        raise ValueError(f"Unknown permitted upstream edges: {missing}")
    x = np.column_stack([np.asarray(upstream_media[n], float) for n in names])
    c = np.asarray(controls, float) if controls is not None else np.empty((len(outcome), 0))
    if c.ndim == 1: c = c[:, None]
    design_m = np.column_stack([np.ones(len(outcome)), x, c])
    mediator_coef, *_ = np.linalg.lstsq(design_m, np.asarray(brand_search, float), rcond=None)
    design_y = np.column_stack([np.ones(len(outcome)), x, np.asarray(brand_search, float), c])
    outcome_coef, *_ = np.linalg.lstsq(design_y, np.asarray(outcome, float), rcond=None)
    mediator_effect = float(outcome_coef[1 + len(names)])
    direct = {n: float(outcome_coef[1+i]) for i, n in enumerate(names)}
    indirect = {n: float(mediator_coef[1+i] * mediator_effect) for i, n in enumerate(names)}
    total = {n: direct[n] + indirect[n] for n in names}
    intervals = {n: (total[n], total[n]) for n in names}
    return FittedMediationResult(direct, indirect, total, mediator_effect, intervals)
