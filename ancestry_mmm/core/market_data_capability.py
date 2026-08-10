"""
REQ-COVERAGE-001 S6: whether the current PyMC hierarchical/market-specific
engine's rectangular market x channel data requirement is validly satisfied
for a given `ModelSpec`'s markets/channels, using the governed variable
coverage matrix (`core.coverage`) as the sole source of truth for
per-(market, channel) support - never inferring support from the prepared
data's own zero/null values (REQ-COVERAGE-001 S1: "missing is not zero").

`core.hierarchical_model.build_fh_hierarchical_model` and
`core.market_specific_model.build_fh_market_specific_model` both consume a
single `X_media` matrix built from `data.preprocessor.prepare_fh_modeling_
frame`, where `spec.channels` supplies one shared column set applied to
every market's rows (`market_bounds` only slices which *rows* belong to
which market, never which *columns* apply). The engine therefore only
validly supports the rectangular case: every requested channel genuinely
observed, for every requested market. `FR-MOD-015` (market-specific/ragged
predictor sets - letting a market skip a channel it never had, without
fabricating a zero/observed value for it) is explicitly **not resolved**
here (REQ-COVERAGE-001 S6): no masking strategy, missing-data likelihood,
or per-market predictor-set restructuring is implemented or approved by
this module. It only reports whether the rectangular subset already
supported today is satisfied, and if not, exactly which (market, channel)
cells are missing governed support and what decision closing that gap
would require - mirroring `core.graph_model_compiler.check_engine_
capability`'s shape (REQ-GRAPH-001) for the same reason: never silently
drop, approximate, or mask what the engine cannot express; always name the
specific unsupported cells rather than a bare rejection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .coverage import VariableCoverageMatrix, VariableCoverageRecord

ENGINE_PYMC_RECTANGULAR = "pymc_hierarchical_rectangular"

# REQ-COVERAGE-001 S6 point 4: "surface, as a report rather than a silent
# choice, the exact modelling decision required to implement FR-MOD-015
# fully." Fixed text, not a template with any invented specifics filled
# in - the actual decision (which masking/likelihood/restructuring
# approach) is exactly what this record declines to invent.
FR_MOD_015_DECISION_REPORT = (
    "FR-MOD-015 (market-specific/ragged predictor sets) is not resolved by "
    "REQ-COVERAGE-001 S6 - no masking strategy, missing-data likelihood, "
    "zeroing convention, or per-market predictor-set restructuring is "
    "approved. Closing the gap listed above requires a separately-approved "
    "modelling decision for how the likelihood should treat an observation "
    "cell for a (market, channel) pair with no genuine coverage - for "
    "example (not a recommendation, just naming the shape of the decision "
    "needed): a masked/marginalised likelihood term for that cell, "
    "restructuring X_media/market_bounds construction so each market "
    "supplies only its own supported channel subset instead of one shared "
    "column set, or an explicit, governed zero-fill convention with its "
    "own recorded assumptions. See the brief's Work Package 5."
)


@dataclass(frozen=True)
class MarketChannelCapabilityIssue:
    """One (market, channel) cell the current engine cannot validly
    include in a rectangular fit, and why."""

    market: str
    channel: str
    reason: str

    def to_dict(self) -> dict:
        return {"market": self.market, "channel": self.channel, "reason": self.reason}


@dataclass(frozen=True)
class EngineCapabilityResult:
    """A deterministic report of whether `engine` can validly fit
    `markets` x `channels` today (REQ-COVERAGE-001 S6 point 3: "a
    deterministic engine-capability result - labelling the unsupported
    request exploratory/unsupported"). `supported=True` iff every
    requested (market, channel) cell has governed, officially-resolved
    coverage - never iff the prepared data merely contains no nulls,
    which would silently trust a zero-filled or otherwise fabricated
    value the same way REQ-COVERAGE-001 forbids elsewhere."""

    engine: str
    markets: Tuple[str, ...]
    channels: Tuple[str, ...]
    issues: Tuple[MarketChannelCapabilityIssue, ...]

    @property
    def supported(self) -> bool:
        return not self.issues

    @property
    def decision_report(self) -> str:
        """REQ-COVERAGE-001 S6 point 4's report - only meaningful, and
        only ever non-empty, when `issues` is non-empty; a fully-supported
        request has no gap for FR-MOD-015 to close."""
        return FR_MOD_015_DECISION_REPORT if self.issues else ""

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "markets": list(self.markets),
            "channels": list(self.channels),
            "supported": self.supported,
            "issues": [issue.to_dict() for issue in self.issues],
            "decision_report": self.decision_report,
        }


def check_market_channel_capability(
    markets: Sequence[str],
    channels: Sequence[str],
    coverage_matrix: Optional[VariableCoverageMatrix],
    *,
    engine: str = ENGINE_PYMC_RECTANGULAR,
) -> EngineCapabilityResult:
    """
    REQ-COVERAGE-001 S6 points 1-3: compile the rectangular (market,
    channel) subset `engine` already validly supports, using `coverage_matrix`
    (built on the Data Coverage page, `core.coverage.build_coverage_matrix_
    from_frame`) as the sole source of truth - never the prepared data's own
    values. A (market, channel) cell is unsupported when either:

    - no `VariableCoverageRecord` exists at all for that `(channel, market)`
      pair (REQ-COVERAGE-001 S3: "every candidate model must expose a
      variable coverage matrix before fitting" - a channel the coverage
      matrix was never built for cannot be certified as genuinely
      observed, whatever values happen to sit in the prepared frame); or
    - any matching record's `has_unapproved_non_observed_coverage` is true.
      Deliberately broader than `is_officially_unresolved` (REQ-COVERAGE-001
      S5's narrower "unknown/missing_expected must not become official fit
      input silently" check for the Data Coverage review UI): this capability
      report needs "is every segment a genuinely observed, directly usable
      number", so `not_applicable`/`unavailable_source`/`suppressed`/
      `estimated`/`modelled` all count as unsupported the same way `unknown`/
      `missing_expected` do (REQ-COVERAGE-001 S1: "missing is not zero",
      "unavailable source is not zero", "not applicable is not zero"; S2: "a
      latent/modelled value must never be stored or displayed as though it
      were an observed source fact") - unless the record has an explicit
      `approved_for_official_use` treatment.

    When a coverage matrix has product/segment-scoped records for the same
    (channel, market) key (the Data Coverage page's optional `product_col`/
    `segment_col` grouping), *every* matching record must be resolved for
    the cell to count as supported - channels are not product/segment-
    scoped in `ModelSpec`, so there is no approved rule here for picking
    only one of several scoped records to trust; requiring all of them
    resolved is the fail-closed reading, not an invented one.

    `coverage_matrix=None` (no matrix built yet at all) marks every
    requested cell unsupported - "no coverage matrix" is never treated as
    "no problem, assume support".
    """
    markets = tuple(markets)
    channels = tuple(channels)
    issues: List[MarketChannelCapabilityIssue] = []

    if coverage_matrix is None:
        issues.extend(
            MarketChannelCapabilityIssue(
                market=market,
                channel=channel,
                reason=(
                    "No coverage matrix has been built yet (REQ-COVERAGE-001 "
                    "S3: every candidate model must expose a variable "
                    "coverage matrix before fitting) - build one on the Data "
                    "Coverage page first."
                ),
            )
            for market in markets
            for channel in channels
        )
        return EngineCapabilityResult(
            engine=engine, markets=markets, channels=channels, issues=tuple(issues)
        )

    records_by_channel_market: Dict[Tuple[str, str], List[VariableCoverageRecord]] = {}
    for record in coverage_matrix.records:
        records_by_channel_market.setdefault(
            (record.variable_id, record.market), []
        ).append(record)

    for market in markets:
        for channel in channels:
            matching = records_by_channel_market.get((channel, market), [])
            if not matching:
                issues.append(
                    MarketChannelCapabilityIssue(
                        market=market,
                        channel=channel,
                        reason=(
                            f"No coverage record for '{channel}' in market "
                            f"'{market}' - the engine's rectangular X_media "
                            "requires governed coverage for every requested "
                            "channel in every requested market."
                        ),
                    )
                )
                continue
            unresolved = [r for r in matching if r.has_unapproved_non_observed_coverage]
            if unresolved:
                issues.append(
                    MarketChannelCapabilityIssue(
                        market=market,
                        channel=channel,
                        reason=(
                            f"'{channel}' in market '{market}' has coverage that "
                            "is not a genuinely observed number (or approved "
                            "for official use) for every segment - unresolved "
                            "unknown/missing_expected coverage, or a "
                            "not_applicable/unavailable_source/suppressed/"
                            "estimated/modelled segment without an approved "
                            "treatment, must not become official fit input "
                            "silently (REQ-COVERAGE-001 S1, S2, S5)."
                        ),
                    )
                )

    return EngineCapabilityResult(
        engine=engine, markets=markets, channels=channels, issues=tuple(issues)
    )
