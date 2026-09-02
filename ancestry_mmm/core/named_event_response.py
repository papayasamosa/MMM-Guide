"""Named-event statistical response method (`REQ-EVENT-001`/
`REQ-EVENT-002`; Decision 12 of the "Post-UI/UX Implementation
Instructions: Approved Business Decisions" brief).

See `docs/named_event_response_method_decision_record.md` for the full
options-considered decision record, including the Work Package 2
synthetic-evidence findings this decision relies on (recorded in this
repository's own named-event response evidence document, cited in full
inside that decision record).

Summary (see the decision record for full reasoning):

1. Response structure: S3, a regularised distributed basis (cubic
   B-spline over the family's lead/lag window, coefficients shrunk
   toward zero by a shared prior scale) - selected over S1 (poor
   amplitude recovery), S2 (larger leakage, does not extend cleanly to
   partial pooling), and S4 (PRD-discouraged as a default), per WP2's
   recorded evidence.
2. Kernel/basis family: cubic B-spline, degree 3, two interior knots at
   1/4 and 3/4 of the total window span - the exact family WP2's
   evidence measured, generalised from that evidence run's fixed
   +/-4-week testbed (interior knots at -2/+2) to an arbitrary
   family-specific window. Knots are placed as fractions of the TOTAL
   span (not each side's own midpoint independently) specifically so the
   basis remains well-defined for an asymmetric, single-sided window
   (e.g. the gifting family's max_lag_weeks=0) - each side's own
   midpoint would coincide with a boundary knot in that case.
3. Priors: `event_coefs ~ Normal(0, tau)`, `tau ~ HalfNormal(1.0)` - the
   exact prior structure WP2's evidence used, recorded as a disclosed
   STARTING default requiring real-data prior-predictive recalibration
   before production use (`EVENT_RESPONSE_SHRINKAGE_PRIOR_REQUIRES_
   RECALIBRATION = True`), never silently treated as final.
4. Pooling: unpooled per market/family by default; partial pooling is
   gated fail-closed on an APPROVED minimum repeated-occurrence
   threshold that this module does not invent (mirrors `core.
   seo_partial_window_policy`'s eligibility-gate pattern).
5. Family-specific lead/lag windows: gifting (anticipatory, 6-week
   lead), remembrance/commemorative (contemporaneous/post_event, 2-week
   lag), promotional (post_event, bounded to the actual promotion's own
   declared window, never a fixed generic number) - grounded in general
   retail-seasonality research, disclosed as a starting default, not an
   Ancestry-validated final business number.

This module implements the deterministic basis-construction and
window-policy CONTRACT only. It does not build, fit, or wire any real
PyMC model - actually integrating this into a real named-event causal
pathway is a separate, materially statistical follow-up requiring its
own synthetic-recovery validation at the real family-specific windows
(WP2's own evidence used a generic testbed window, not these), mirroring
every other Phase B/C step's "declare the contract, defer fit-time
wiring" scope boundary already established in this repository (`core.
google_trends_anchor`, `core.seo_partial_window_policy`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple, cast

import numpy as np

NAMED_EVENT_RESPONSE_SCHEMA_VERSION = 1

# --- Decisions 1-3: response structure, kernel family, priors --------------

NAMED_EVENT_RESPONSE_STRUCTURE = "S3_regularised_spline_basis"
EVENT_RESPONSE_KERNEL_FAMILY = "cubic_b_spline"
EVENT_RESPONSE_SPLINE_DEGREE = 3
# Fractions of the TOTAL window span, measured from the lead boundary
# (never from each side's own length independently - that placement
# degenerates to a knot coincident with a boundary knot whenever one
# side of the window has zero weeks, e.g. the gifting family's
# max_lag_weeks=0). For the symmetric +/-4-week window WP2's evidence
# used, these fractions reproduce that evidence's exact interior knots
# (-2, +2) exactly: span=8, boundary_low=-4 => -4+0.25*8=-2, -4+0.75*8=2.
EVENT_RESPONSE_INTERIOR_KNOT_FRACTIONS: Tuple[float, float] = (0.25, 0.75)
EVENT_RESPONSE_SHRINKAGE_PRIOR_FAMILY = "half_normal_on_coefficient_scale"
EVENT_RESPONSE_SHRINKAGE_PRIOR_DEFAULT_SCALE = 1.0
# Explicit, disclosed flag - this is the WP2 evidence run's validated
# STARTING value, not a business-approved final constant (see decision
# record, dimension 3). A future session fitting real data must run its
# own prior-predictive check at that data's actual scale first.
EVENT_RESPONSE_SHRINKAGE_PRIOR_REQUIRES_RECALIBRATION = True

# --- Temporal-treatment vocabulary (matches REQ-EVENT-001's own closed set) -

TEMPORAL_TREATMENT_CONTEMPORANEOUS = "contemporaneous"
TEMPORAL_TREATMENT_ANTICIPATORY = "anticipatory"
TEMPORAL_TREATMENT_POST_EVENT = "post_event"
TEMPORAL_TREATMENT_ANTICIPATORY_AND_POST_EVENT = "anticipatory_and_post_event"

TEMPORAL_TREATMENTS = (
    TEMPORAL_TREATMENT_CONTEMPORANEOUS,
    TEMPORAL_TREATMENT_ANTICIPATORY,
    TEMPORAL_TREATMENT_POST_EVENT,
    TEMPORAL_TREATMENT_ANTICIPATORY_AND_POST_EVENT,
)


@dataclass(frozen=True)
class NamedEventFamilyWindowPolicy:
    """The governed, per-family maximum lead/lag support window
    (decision 5). `max_lag_weeks=None` means "bounded to the actual
    declared active period of the specific event/promotion instance,
    not a fixed generic number" (the promotional family's own case) -
    distinct from `0` (no lag permitted at all)."""

    family: str
    temporal_treatment: str
    max_lead_weeks: int
    max_lag_weeks: Optional[int]
    basis: str
    schema_version: int = NAMED_EVENT_RESPONSE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.family:
            raise ValueError("NamedEventFamilyWindowPolicy requires a family.")
        if self.temporal_treatment not in TEMPORAL_TREATMENTS:
            raise ValueError(
                f"NamedEventFamilyWindowPolicy: unknown temporal_treatment "
                f"'{self.temporal_treatment}' (expected one of "
                f"{TEMPORAL_TREATMENTS})."
            )
        if self.max_lead_weeks < 0:
            raise ValueError(
                "NamedEventFamilyWindowPolicy.max_lead_weeks cannot be negative."
            )
        if self.max_lag_weeks is not None and self.max_lag_weeks < 0:
            raise ValueError(
                "NamedEventFamilyWindowPolicy.max_lag_weeks cannot be negative."
            )
        if not self.basis:
            raise ValueError(
                "NamedEventFamilyWindowPolicy requires a basis (the "
                "provenance of this window choice - never left implicit)."
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "NamedEventFamilyWindowPolicy":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


GIFTING_WINDOW_POLICY = NamedEventFamilyWindowPolicy(
    family="gifting",
    temporal_treatment=TEMPORAL_TREATMENT_ANTICIPATORY,
    max_lead_weeks=6,
    max_lag_weeks=0,
    basis=(
        "General retail-industry seasonality research: online gift-purchase "
        "search/consideration activity for major gifting occasions commonly "
        "rises in a 4-6 week pre-event window, with the final 1-2 weeks "
        "carrying the largest share of the effect. Disclosed starting "
        "default, not an Ancestry-validated final business number."
    ),
)

REMEMBRANCE_WINDOW_POLICY = NamedEventFamilyWindowPolicy(
    family="remembrance",
    temporal_treatment=TEMPORAL_TREATMENT_CONTEMPORANEOUS,
    max_lead_weeks=0,
    max_lag_weeks=2,
    basis=(
        "Commemorative-date spikes (anniversaries, remembrance dates) are "
        "typically sharp and concentrated at or shortly after the date "
        "itself, rather than anticipated in advance. Disclosed starting "
        "default, not an Ancestry-validated final business number."
    ),
)

PROMOTIONAL_WINDOW_POLICY = NamedEventFamilyWindowPolicy(
    family="promotional",
    temporal_treatment=TEMPORAL_TREATMENT_POST_EVENT,
    max_lead_weeks=0,
    max_lag_weeks=None,
    basis=(
        "Decision 12 requires the promotional-family window be bounded to "
        "the actual declared active period of the specific promotion "
        "instance - a per-promotion data-driven bound, never a fixed "
        "generic number this record could invent."
    ),
)

DEFAULT_FAMILY_WINDOW_POLICIES: Mapping[str, NamedEventFamilyWindowPolicy] = {
    "gifting": GIFTING_WINDOW_POLICY,
    "remembrance": REMEMBRANCE_WINDOW_POLICY,
    "promotional": PROMOTIONAL_WINDOW_POLICY,
}


def build_event_relative_design_matrix(
    event_weeks: Sequence[int],
    n_weeks: int,
    *,
    max_lead_weeks: int,
    max_lag_weeks: int,
) -> np.ndarray:
    """The deterministic event-relative indicator design matrix `E`
    (shape `(n_weeks, max_lead_weeks + max_lag_weeks + 1)`): row `t`,
    column `k` is `1.0` when week `t` lies exactly `offsets[k]` weeks
    from some occurrence's factual week (`offsets` runs from
    `-max_lead_weeks` to `+max_lag_weeks`). Generalises the event-design
    construction validated by this module's own decision record (see
    the module docstring's "Work Package 2" evidence citation above) to
    an arbitrary family-specific window.

    `event_weeks` are the factual occurrence week INDICES - never
    shifted or mutated by this function (REQ-EVENT-001's own invariant);
    only the relative OFFSET grid used to populate the design matrix
    varies by family.
    """
    if n_weeks <= 0:
        raise ValueError("build_event_relative_design_matrix requires n_weeks > 0.")
    if max_lead_weeks < 0 or max_lag_weeks < 0:
        raise ValueError(
            "build_event_relative_design_matrix: max_lead_weeks/"
            "max_lag_weeks cannot be negative."
        )
    offsets = np.arange(-max_lead_weeks, max_lag_weeks + 1)
    design = np.zeros((n_weeks, len(offsets)))
    for week in event_weeks:
        for k, offset in enumerate(offsets):
            target = week + offset
            if 0 <= target < n_weeks:
                design[target, k] = 1.0
    return design


def build_spline_basis(
    *,
    max_lead_weeks: int,
    max_lag_weeks: int,
    degree: int = EVENT_RESPONSE_SPLINE_DEGREE,
) -> np.ndarray:
    """The deterministic cubic B-spline basis matrix over a family's own
    `(-max_lead_weeks, +max_lag_weeks)` relative-offset grid, with
    interior knots at the window's own lead/lag midpoints (decision 2).
    Generalises the spline-basis construction validated by this
    module's own decision record's Work Package 2 evidence citation
    (fixed +/-4-week testbed, interior knots at -2/+2) to an arbitrary
    family-specific window, preserving the same relative knot PLACEMENT
    (interior knots at the midpoints of the lead and lag sides) rather
    than the same absolute week numbers.

    Returns an `(n_offsets, n_basis_functions)` matrix; `n_basis_
    functions = len(interior_knots) + degree + 1` (6 for the default
    2-interior-knot, degree-3 configuration, matching WP2's evidence
    exactly when `max_lead_weeks == max_lag_weeks == 4`).
    """
    if max_lead_weeks < 0 or max_lag_weeks < 0:
        raise ValueError("build_spline_basis: window weeks cannot be negative.")
    if max_lead_weeks == 0 and max_lag_weeks == 0:
        raise ValueError(
            "build_spline_basis: a spline basis requires a non-degenerate "
            "window (max_lead_weeks and max_lag_weeks cannot both be 0)."
        )
    from scipy.interpolate import BSpline

    offsets = np.arange(-max_lead_weeks, max_lag_weeks + 1, dtype=float)
    boundary_low = -float(max_lead_weeks)
    boundary_high = float(max_lag_weeks)
    span = boundary_high - boundary_low
    interior_knots = [
        boundary_low + fraction * span
        for fraction in EVENT_RESPONSE_INTERIOR_KNOT_FRACTIONS
    ]
    knots = np.array(
        [boundary_low] * (degree + 1)
        + sorted(interior_knots)
        + [boundary_high] * (degree + 1)
    )
    n_basis = len(interior_knots) + degree + 1
    design = np.zeros((len(offsets), n_basis))
    for i in range(n_basis):
        coef = np.zeros(n_basis)
        coef[i] = 1.0
        design[:, i] = BSpline(knots, coef, degree, extrapolate=False)(offsets)
    return np.nan_to_num(design, nan=0.0)


POOLING_ELIGIBILITY_ELIGIBLE = "eligible"
POOLING_ELIGIBILITY_INSUFFICIENT_NO_THRESHOLD = (
    "insufficient_evidence_no_approved_threshold"
)
POOLING_ELIGIBILITY_BELOW_APPROVED_THRESHOLD = "below_approved_threshold"

POOLING_ELIGIBILITY_STATUSES = (
    POOLING_ELIGIBILITY_ELIGIBLE,
    POOLING_ELIGIBILITY_INSUFFICIENT_NO_THRESHOLD,
    POOLING_ELIGIBILITY_BELOW_APPROVED_THRESHOLD,
)

POOLING_ELIGIBILITY_DISCLAIMER = (
    "This gate determines only whether enough repeated occurrences exist to "
    "consider partial pooling across markets for one event family - it does "
    "not itself validate that pooling improves fit, and it does not supply "
    "or approve the minimum-occurrence threshold (deferred, matching "
    "REQ-DATASUPPORT-001's own deliberately-deferred numeric thresholds). A "
    "missing approved threshold means this gate can never return 'eligible', "
    "by design."
)


@dataclass(frozen=True)
class PoolingEligibility:
    """Decision 4's fail-closed pooling gate result for one event
    family/market combination."""

    family: str
    occurrence_count: int
    status: str
    approved_minimum_occurrences_threshold: Optional[int]
    disclaimer: str = POOLING_ELIGIBILITY_DISCLAIMER

    def __post_init__(self) -> None:
        if not self.family:
            raise ValueError("PoolingEligibility requires a family.")
        if self.occurrence_count < 0:
            raise ValueError("PoolingEligibility.occurrence_count cannot be negative.")
        if self.status not in POOLING_ELIGIBILITY_STATUSES:
            raise ValueError(
                f"invalid status {self.status!r}; must be one of "
                f"{POOLING_ELIGIBILITY_STATUSES}"
            )

    @property
    def is_eligible(self) -> bool:
        return self.status == POOLING_ELIGIBILITY_ELIGIBLE

    def to_dict(self) -> dict:
        return asdict(self)


def assess_family_pooling_eligibility(
    family: str,
    occurrence_count: int,
    *,
    approved_minimum_occurrences_threshold: Optional[int] = None,
) -> PoolingEligibility:
    """Assess whether `family` has enough repeated occurrences to be
    considered for partial pooling across markets (decision 4). Fails
    closed exactly like `core.seo_partial_window_policy.assess_seo_
    contribution_window_eligibility`: no approved threshold means never
    eligible."""
    if not family:
        raise ValueError("assess_family_pooling_eligibility requires a family.")
    if occurrence_count < 0:
        raise ValueError(
            "assess_family_pooling_eligibility: occurrence_count cannot be negative."
        )
    if (
        approved_minimum_occurrences_threshold is not None
        and approved_minimum_occurrences_threshold < 1
    ):
        raise ValueError(
            "approved_minimum_occurrences_threshold must be >= 1 when supplied."
        )

    if approved_minimum_occurrences_threshold is None:
        status = POOLING_ELIGIBILITY_INSUFFICIENT_NO_THRESHOLD
    elif occurrence_count < approved_minimum_occurrences_threshold:
        status = POOLING_ELIGIBILITY_BELOW_APPROVED_THRESHOLD
    else:
        status = POOLING_ELIGIBILITY_ELIGIBLE

    return PoolingEligibility(
        family=family,
        occurrence_count=occurrence_count,
        status=status,
        approved_minimum_occurrences_threshold=approved_minimum_occurrences_threshold,
    )
