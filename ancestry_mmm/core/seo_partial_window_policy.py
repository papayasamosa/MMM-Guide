"""Governed SEO partial-window handling policy (`REQ-SEO-001`; Decision 3
of the "Post-UI/UX Implementation Instructions: Approved Business
Decisions" brief).

See `docs/seo_partial_window_handling_decision_record.md` for the full
options-considered decision record (PyMC/PyMC-Marketing documentation
consulted via Context7, and why this architecture was chosen).

Summary (see the decision record for full reasoning):

1. A partially-observed SEO predictor is NOT natively imputed via PyMC's
   `observed=`-masked-array mechanism (confirmed via official PyMC
   documentation to be a real, native feature - but one that applies to
   whichever variable is passed as `observed=`, and using it for a
   *predictor* would require committing to an unvalidatable generative
   prior for periods with no SEO tracking at all and no ground truth to
   check recovery against). This module does not implement that
   candidate.
2. Instead, the approved architecture direction (`SEO_GATED_
   REGRESSOR_ARCHITECTURE`) is a windowed/gated regressor: the SEO
   contribution term is only structurally active during SEO's valid
   data window; the full MMM's time index, other channels/controls, and
   final-outcome likelihood are completely unaffected for every period.
   This module records that direction as governed metadata; it does not
   implement the actual PyMC/PyTensor gating code (a separate, materially
   statistical fit-time integration requiring its own prior-predictive
   and synthetic-recovery validation).
3. The valid window itself is determined deterministically from a
   supplied SEO coverage-state series, reusing `core.coverage`'s
   existing eight-state missingness vocabulary directly rather than
   inventing a parallel one: a week counts as "within window" if it was
   actually queried (coverage_state is `None`, i.e. an ordinary observed
   fact per `core.seo_visibility`'s own convention, or `observed_zero`,
   a confirmed zero-impression week) - `missing_expected`/
   `unavailable_source`/`unknown` all mean "never queried," i.e. outside
   any window.
4. The SEO contribution's official-use eligibility fails closed by
   default (`assess_seo_contribution_window_eligibility`) - no minimum
   window-length threshold is invented here; the exact number is
   deferred to `REQ-DATASUPPORT-001`, mirroring that record's own
   deliberately-`None`-defaulted `SupportThresholds` fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple, cast

from .coverage import (
    COVERAGE_STATES,
    STATE_MISSING_EXPECTED,
    STATE_UNAVAILABLE_SOURCE,
    STATE_UNKNOWN,
)

SEO_PARTIAL_WINDOW_POLICY_SCHEMA_VERSION = 1

# Coverage states that mean "this week was never queried at all" - the
# complement (None, i.e. an ordinary observed fact, or STATE_OBSERVED_ZERO)
# means real SEO source data exists for that week (W3 of the decision
# record).
NEVER_QUERIED_COVERAGE_STATES = (
    STATE_MISSING_EXPECTED,
    STATE_UNAVAILABLE_SOURCE,
    STATE_UNKNOWN,
)

WEEK_CLASSIFICATION_BEFORE_WINDOW = "before_window"
WEEK_CLASSIFICATION_WITHIN_WINDOW = "within_window"
WEEK_CLASSIFICATION_AFTER_WINDOW = "after_window"
WEEK_CLASSIFICATION_NO_WINDOW_DATA = "no_window_data"

WEEK_CLASSIFICATIONS = (
    WEEK_CLASSIFICATION_BEFORE_WINDOW,
    WEEK_CLASSIFICATION_WITHIN_WINDOW,
    WEEK_CLASSIFICATION_AFTER_WINDOW,
    WEEK_CLASSIFICATION_NO_WINDOW_DATA,
)

ELIGIBILITY_STATUS_ELIGIBLE = "eligible"
ELIGIBILITY_STATUS_NO_WINDOW = "no_window_no_data_observed"
ELIGIBILITY_STATUS_INSUFFICIENT_NO_THRESHOLD = (
    "insufficient_evidence_no_approved_threshold"
)
ELIGIBILITY_STATUS_BELOW_APPROVED_THRESHOLD = "below_approved_threshold"

ELIGIBILITY_STATUSES = (
    ELIGIBILITY_STATUS_ELIGIBLE,
    ELIGIBILITY_STATUS_NO_WINDOW,
    ELIGIBILITY_STATUS_INSUFFICIENT_NO_THRESHOLD,
    ELIGIBILITY_STATUS_BELOW_APPROVED_THRESHOLD,
)

SEO_PARTIAL_WINDOW_DISCLAIMER = (
    "This diagnostic determines the SEO contribution's valid data window "
    "and a fail-closed official-use eligibility status from that window's "
    "length alone. It does not itself estimate, fit, or validate any SEO "
    "causal contribution, and it does not supply or approve a minimum "
    "window-length threshold (deferred to REQ-DATASUPPORT-001) - a missing "
    "approved threshold means this record can never return 'eligible', by "
    "design."
)

# W2-B: the approved architecture direction for a future fit-time
# integration. Structured, documented metadata only - never executable
# PyTensor/PyMC code. A future session implementing this must still run
# its own prior-predictive and synthetic-recovery validation
# (REQ-LATENT-001 Requirement 4's equivalent standard) before this
# architecture is eligible for official use.
SEO_GATED_REGRESSOR_ARCHITECTURE: Mapping[str, Any] = {
    "architecture_id": "seo_windowed_gated_regressor_v1",
    "candidate": "W2-B",
    "summary": (
        "The SEO contribution term is structurally active only during "
        "SEO's valid data window (see SeoValidEstimationWindow); the full "
        "MMM's time index, every other channel/control, and the "
        "final-outcome likelihood are unaffected for every period, "
        "in-window or not."
    ),
    "rejected_alternative": {
        "candidate": "W2-A",
        "summary": (
            "Native PyMC observed=-masked-array imputation of the SEO "
            "predictor itself, treated as its own generative random "
            "variable. Rejected as the primary mechanism: requires an "
            "unvalidatable generative prior for periods with no SEO "
            "tracking and no ground truth to check recovery against."
        ),
    },
    "placeholder_value_note": (
        "Any internal PyTensor placeholder needed purely to keep a "
        "gating/switch tensor operation numerically defined at excluded "
        "positions is an internal computational device only - it must "
        "never be stored, reported, or interpreted as the observed SEO "
        "visibility value for that week."
    ),
    "not_yet_implemented": True,
}


@dataclass(frozen=True)
class SeoValidEstimationWindow:
    """The governed valid data window for one market's SEO contribution
    (W3). `start_week`/`end_week` are both `None` together when SEO data
    has never been observed for this market (a valid, representable
    state, not an error). `weeks_observed` counts only weeks actually
    classified as within-window (see `determine_valid_estimation_window`)
    - it is NOT simply the calendar span between `start_week` and
    `end_week`, since within-window weeks are not required to be
    contiguous (a market could have a queried-then-temporarily-
    unavailable-then-queried-again SEO source, still within one
    determined window bounded by its first and last observed weeks)."""

    market: str
    start_week: Optional[str]
    end_week: Optional[str]
    weeks_observed: int
    schema_version: int = SEO_PARTIAL_WINDOW_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.market:
            raise ValueError("SeoValidEstimationWindow requires a market.")
        if (self.start_week is None) != (self.end_week is None):
            raise ValueError(
                "SeoValidEstimationWindow: start_week and end_week must be "
                "present or absent together."
            )
        if self.start_week is not None and self.end_week is not None:
            if self.end_week < self.start_week:
                raise ValueError(
                    "SeoValidEstimationWindow: end_week must not precede start_week."
                )
        if self.weeks_observed < 0:
            raise ValueError(
                "SeoValidEstimationWindow.weeks_observed must be non-negative."
            )
        if self.start_week is None and self.weeks_observed != 0:
            raise ValueError(
                "SeoValidEstimationWindow: weeks_observed must be 0 when no "
                "window exists (start_week/end_week are None)."
            )

    @property
    def has_window(self) -> bool:
        return self.start_week is not None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SeoValidEstimationWindow":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


def _week_was_queried(coverage_state: Optional[str]) -> bool:
    """A week was actually queried (real SEO source data exists) unless
    its coverage_state is one of the "never queried" states. `None`
    (ordinary observed fact, per `core.seo_visibility`'s convention) and
    `observed_zero` (confirmed zero-impression week) both count as
    queried."""
    if coverage_state is None:
        return True
    if coverage_state not in COVERAGE_STATES:
        raise ValueError(
            f"unknown coverage_state {coverage_state!r} (expected one of "
            f"{COVERAGE_STATES} or None)."
        )
    return coverage_state not in NEVER_QUERIED_COVERAGE_STATES


def determine_valid_estimation_window(
    market: str,
    weekly_coverage_states: Sequence[Tuple[str, Optional[str]]],
) -> SeoValidEstimationWindow:
    """Deterministically determine `market`'s valid SEO estimation window
    (W3) from a supplied `(week, coverage_state)` series covering
    whatever weeks the caller has coverage information for. `weeks_
    observed` counts every queried week found (see `_week_was_queried`),
    not merely the calendar span - a market whose SEO source went
    temporarily unavailable and later resumed still has one window
    bounded by its first and last queried weeks."""
    if not market:
        raise ValueError("determine_valid_estimation_window requires a market.")

    weeks_seen: dict = {}
    for week, coverage_state in weekly_coverage_states:
        if not week:
            raise ValueError(
                "determine_valid_estimation_window: every entry requires a "
                "non-empty week."
            )
        if week in weeks_seen:
            raise ValueError(
                f"determine_valid_estimation_window: duplicate week {week!r} "
                f"for market {market!r}."
            )
        weeks_seen[week] = coverage_state

    queried_weeks = sorted(
        week for week, state in weeks_seen.items() if _week_was_queried(state)
    )

    if not queried_weeks:
        return SeoValidEstimationWindow(
            market=market, start_week=None, end_week=None, weeks_observed=0
        )

    return SeoValidEstimationWindow(
        market=market,
        start_week=queried_weeks[0],
        end_week=queried_weeks[-1],
        weeks_observed=len(queried_weeks),
    )


def classify_week_relative_to_window(
    week: str, window: SeoValidEstimationWindow
) -> str:
    """Classify one week relative to `window` for diagnostics display
    ("mark the valid estimation window clearly in diagnostics"). Returns
    one of `WEEK_CLASSIFICATIONS`. This function does not check whether
    `week` was itself actually queried - it only reports the week's
    position relative to the window's bounds; combine with the caller's
    own coverage_state if a finer distinction is needed."""
    if not week:
        raise ValueError("classify_week_relative_to_window requires a week.")
    if not window.has_window:
        return WEEK_CLASSIFICATION_NO_WINDOW_DATA
    assert window.start_week is not None and window.end_week is not None
    if week < window.start_week:
        return WEEK_CLASSIFICATION_BEFORE_WINDOW
    if week > window.end_week:
        return WEEK_CLASSIFICATION_AFTER_WINDOW
    return WEEK_CLASSIFICATION_WITHIN_WINDOW


@dataclass(frozen=True)
class SeoContributionEligibility:
    """The fail-closed official-use eligibility result for one market's
    SEO contribution (W4), mirroring `core.latent_state_identification`'s
    "never a bare boolean, always a disclaimer" pattern."""

    market: str
    status: str
    window: SeoValidEstimationWindow
    approved_minimum_weeks_threshold: Optional[int]
    limitations: Tuple[str, ...] = ()
    disclaimer: str = SEO_PARTIAL_WINDOW_DISCLAIMER

    def __post_init__(self) -> None:
        if not self.market:
            raise ValueError("SeoContributionEligibility requires a market.")
        if self.status not in ELIGIBILITY_STATUSES:
            raise ValueError(
                f"invalid status {self.status!r}; must be one of {ELIGIBILITY_STATUSES}"
            )

    @property
    def is_eligible(self) -> bool:
        return self.status == ELIGIBILITY_STATUS_ELIGIBLE

    def to_dict(self) -> dict:
        payload = asdict(self)
        return payload


def assess_seo_contribution_window_eligibility(
    market: str,
    window: SeoValidEstimationWindow,
    *,
    approved_minimum_weeks_threshold: Optional[int] = None,
) -> SeoContributionEligibility:
    """Assess whether `market`'s SEO contribution is eligible for
    official reporting/planning/optimisation, purely from its valid
    window's length (W4). Fails closed:

    - no window at all -> `no_window_no_data_observed`;
    - a window exists but `approved_minimum_weeks_threshold` is `None`
      (no approved threshold exists yet, per `REQ-DATASUPPORT-001`'s own
      deliberately-deferred numeric thresholds) ->
      `insufficient_evidence_no_approved_threshold` - this function can
      never return `eligible` until a threshold is actually supplied;
    - a window exists, a threshold is supplied, but `weeks_observed` is
      below it -> `below_approved_threshold`;
    - a window exists, a threshold is supplied, and `weeks_observed`
      meets or exceeds it -> `eligible`.
    """
    if not market:
        raise ValueError(
            "assess_seo_contribution_window_eligibility requires a market."
        )
    if window.market != market:
        raise ValueError(
            f"window.market {window.market!r} does not match market {market!r}."
        )
    if (
        approved_minimum_weeks_threshold is not None
        and approved_minimum_weeks_threshold < 1
    ):
        raise ValueError("approved_minimum_weeks_threshold must be >= 1 when supplied.")

    if not window.has_window:
        return SeoContributionEligibility(
            market=market,
            status=ELIGIBILITY_STATUS_NO_WINDOW,
            window=window,
            approved_minimum_weeks_threshold=approved_minimum_weeks_threshold,
            limitations=(
                "No SEO source data has ever been queried and returned for "
                "this market - there is no window to assess.",
            ),
        )

    if approved_minimum_weeks_threshold is None:
        return SeoContributionEligibility(
            market=market,
            status=ELIGIBILITY_STATUS_INSUFFICIENT_NO_THRESHOLD,
            window=window,
            approved_minimum_weeks_threshold=None,
            limitations=(
                "A valid window exists, but no minimum-window-length "
                "threshold has been approved yet (REQ-DATASUPPORT-001) - "
                "this status can never become 'eligible' until one is "
                "supplied; this is a deliberate fail-closed default, not a "
                "missing feature.",
            ),
        )

    if window.weeks_observed < approved_minimum_weeks_threshold:
        return SeoContributionEligibility(
            market=market,
            status=ELIGIBILITY_STATUS_BELOW_APPROVED_THRESHOLD,
            window=window,
            approved_minimum_weeks_threshold=approved_minimum_weeks_threshold,
            limitations=(
                f"Window has {window.weeks_observed} observed week(s), "
                f"below the approved minimum of "
                f"{approved_minimum_weeks_threshold}.",
            ),
        )

    return SeoContributionEligibility(
        market=market,
        status=ELIGIBILITY_STATUS_ELIGIBLE,
        window=window,
        approved_minimum_weeks_threshold=approved_minimum_weeks_threshold,
        limitations=(
            "Meeting the minimum-window-length threshold establishes only "
            "that enough weeks exist to attempt estimation - it does not "
            "itself validate model fit, identification, or causal "
            "robustness for the SEO pathway.",
        ),
    )


@dataclass(frozen=True)
class SeoWindowDiagnosticPoint:
    """One diagnostic point pairing a week with its classification
    relative to the determined window, for display alongside the raw SEO
    observation series."""

    week: str
    classification: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_window_diagnostic_series(
    weeks: Sequence[str], window: SeoValidEstimationWindow
) -> List[SeoWindowDiagnosticPoint]:
    """Classify every week in `weeks` (the full MMM's weekly grid, not
    merely SEO's own observed weeks) relative to `window`, in the
    supplied order - satisfies "mark the valid estimation window clearly
    in diagnostics" for the full modelling history, not only the SEO
    subset of it."""
    return [
        SeoWindowDiagnosticPoint(
            week=week, classification=classify_week_relative_to_window(week, window)
        )
        for week in weeks
    ]
