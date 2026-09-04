"""Governed Google Trends brand-demand identifying anchor: query-set
definition, raw-series observation, deterministic normalisation, and the
`REQ-LATENT-001` identifying-anchor declaration for Candidate A's
`candidate_a_latent_branded_search_demand` latent state (Decision 9 of
the "Post-UI/UX Implementation Instructions: Approved Business
Decisions" brief).

See `docs/google_trends_brand_demand_anchor_decision_record.md` for the
full options-considered decision record (sources consulted - Google's
own Trends Help Center FAQ - and why this formula was chosen).

Formula summary (see the decision record for full reasoning):

1. Raw Google Trends field consumed: the weekly ``interest_over_time``
   index value, an ALREADY-normalised 0-100 relative index for the
   governed query set's stated geography/time-range/category window -
   confirmed by Google's own Trends Help Center FAQ ("each data point is
   divided by the total searches ... then scaled on a range of 0 to 100
   based on a topic's proportion to all searches"). This is a relative
   index, never an absolute search count (Decision 9's own explicit
   caution, reaffirmed by `REQ-LATENT-001`'s 2026-08-30 addendum).
2. A single extraction call must cover one query set's entire series in
   one request; rows carrying different `query_set_id`s must never be
   combined into one computed series (Google re-peaks its own 0-100
   scale to each request's own geography/time-range/comparison-term
   selection - silently combining two separate extractions would
   silently corrupt the series). `compute_anchor_series` enforces this
   as a hard validation error.
3. Missingness: Google's own FAQ states "Trends only shows data for
   popular terms, so search terms with low volume appear as '0'" - a
   raw `0` is therefore a real, transcribed source number, NOT a
   confirmed observed zero and NOT an undefined ratio (unlike GSC's
   impressions field). This module keeps the raw zero as real evidence
   but marks the week `coverage_state = STATE_SUPPRESSED`, never
   `STATE_OBSERVED_ZERO` and never `None`/discarded.
4. Normalisation for use as an identifying anchor:
   ``anchor_value = raw_index / 100.0`` - a purely linear rescaling onto
   [0, 1] that preserves every relative relationship in Google's own
   already internally-consistent 0-100 basis (deterministic, documented,
   reversible).
5. Identifying constraint: `STRATEGY_ANCHORED_TO_OBSERVED` with the
   loading between `candidate_a_latent_branded_search_demand` and this
   anchor series FIXED at `GOOGLE_TRENDS_ANCHOR_FIXED_LOADING` (1.0,
   never estimated) - the standard single-indicator scale-identification
   device for a latent state with otherwise-free upstream/downstream
   regression coefficients (`REQ-LATENT-001` Requirement 1's second
   listed strategy). This fixes what one unit of the latent state means:
   one point of this governed, rescaled, relative Google Trends index
   for the approved branded query set - explicitly NOT one search, one
   click, or any absolute search volume.

This module does NOT implement a Google Trends API client/ingestion
mechanism (out of scope, mirrors `core.seo_visibility`'s equivalent
scope boundary).  It does provide the governed fit-time observation
boundary consumed by `core.search_capacity`: Candidate A uses a fixed
one-unit loading for the relative Trends index and estimates a separate
translation scale into observed capture units.  The query set, complete
weekly coverage, and measurement uncertainty are persisted with the fit
inputs; missing live series data remains a fail-closed external-data
condition.  The compiler-blocking and full synthetic-recovery items in
`REQ-LATENT-001` remain evidence gates rather than being silently marked
as passed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple, cast

import numpy as np

from .coverage import COVERAGE_STATES, STATE_SUPPRESSED
from .latent_state_identification import (
    STRATEGY_ANCHORED_TO_OBSERVED,
    LatentStateIdentificationDeclaration,
)

GOOGLE_TRENDS_ANCHOR_SCHEMA_VERSION = 1

# Matches `diagnostics_service.CANDIDATE_A_LATENT_DEMAND_STATE_ID` exactly -
# duplicated as a literal (not imported) to avoid a core -> application
# dependency; a test guards the two stay in sync.
CANDIDATE_A_LATENT_DEMAND_STATE_ID = "candidate_a_latent_branded_search_demand"

# G5 (decision record): the identifying constraint fixes this loading at
# exactly 1.0 - never estimated. Changing this value would be a new
# statistical modelling decision, not a configuration tweak.
GOOGLE_TRENDS_ANCHOR_FIXED_LOADING = 1.0

GOOGLE_TRENDS_ANCHOR_DISCLAIMER = (
    "This anchor value is a rescaled Google Trends relative search-interest "
    "index (raw index / 100), not an absolute search volume or count. One "
    "unit of the latent state anchored to it means one point of this "
    "governed, relative index for the approved branded query set - never a "
    "count of searches, clicks, or any other absolute quantity."
)

# Approved UK Brand Demand anchor expression. The repeated ``ancestry`` is
# intentional and must survive validation/provenance unchanged.
UK_BRAND_DEMAND_QUERY_SET_ID = "uk_brand_demand_v1"
UK_BRAND_DEMAND_QUERY_EXPRESSION = (
    "ancestry + ancestory + ancestery + ansectry + anscestry + ancestry"
)
UK_BRAND_DEMAND_TERMS = tuple(UK_BRAND_DEMAND_QUERY_EXPRESSION.split(" + "))


@dataclass(frozen=True)
class GoogleTrendsQuerySetDefinition:
    """One governed Google Trends query-set definition (`REQ-LATENT-001`'s
    2026-08-30 addendum: "the branded query set feeding the Google Trends
    series must be a governed definition, not an ad-hoc keyword list
    assembled at extraction time"). `time_range_start`/`time_range_end`
    and `extraction_date` are ISO date strings (``YYYY-MM-DD``); this
    class does not itself validate calendar semantics beyond ordering,
    mirroring this repository's existing lightweight date-as-string
    convention (`core.seo_visibility`'s `week` field)."""

    query_set_id: str
    branded_terms: Tuple[str, ...]
    geography: str
    time_range_start: str
    time_range_end: str
    category: str = "all_categories"
    search_property: str = "web_search"
    extraction_date: Optional[str] = None
    methodology_version: str = "1.0.0"
    schema_version: int = GOOGLE_TRENDS_ANCHOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.query_set_id:
            raise ValueError("GoogleTrendsQuerySetDefinition requires a query_set_id.")
        if not self.branded_terms:
            raise ValueError(
                "GoogleTrendsQuerySetDefinition requires at least one "
                "branded term - an empty query set is not a governed "
                "definition."
            )
        if any(not term for term in self.branded_terms):
            raise ValueError(
                "GoogleTrendsQuerySetDefinition.branded_terms must not "
                "contain an empty term."
            )
        if not self.geography:
            raise ValueError(
                "GoogleTrendsQuerySetDefinition requires a geography "
                "(REQ-LATENT-001's addendum: geography must be recorded "
                "alongside the series)."
            )
        if not self.time_range_start or not self.time_range_end:
            raise ValueError(
                "GoogleTrendsQuerySetDefinition requires both "
                "time_range_start and time_range_end (REQ-LATENT-001's "
                "addendum: time range must be recorded alongside the "
                "series)."
            )
        if self.time_range_end < self.time_range_start:
            raise ValueError(
                "GoogleTrendsQuerySetDefinition.time_range_end must not "
                "precede time_range_start."
            )

    @property
    def query_expression(self) -> str:
        """Return the exact supplied expression, including duplicates."""
        return " + ".join(self.branded_terms)

    @property
    def duplicate_terms(self) -> Tuple[str, ...]:
        seen: set[str] = set()
        duplicates: list[str] = []
        for term in self.branded_terms:
            if term in seen and term not in duplicates:
                duplicates.append(term)
            seen.add(term)
        return tuple(duplicates)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["branded_terms"] = list(self.branded_terms)
        return payload

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "GoogleTrendsQuerySetDefinition":
        payload = dict(values)
        if "branded_terms" in payload:
            payload["branded_terms"] = tuple(payload["branded_terms"] or ())
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in payload.items() if k in known}))


@dataclass(frozen=True)
class GoogleTrendsRawObservation:
    """One raw weekly Google Trends interest-over-time row - the shape a
    single-request Trends extraction returns per period, for exactly one
    `query_set_id`'s whole estimation window (see module docstring point
    2: a single extraction call, never stitched). `raw_index` is
    Google's own 0-100 relative scale, kept verbatim as required evidence
    (design requirement 3 - "the raw ... series must be kept as
    evidence, never discarded after use")."""

    query_set_id: str
    week: str
    raw_index: float

    def __post_init__(self) -> None:
        if not self.query_set_id:
            raise ValueError("GoogleTrendsRawObservation requires a query_set_id.")
        if not self.week:
            raise ValueError("GoogleTrendsRawObservation requires a week.")
        if not (0.0 <= self.raw_index <= 100.0):
            raise ValueError(
                "GoogleTrendsRawObservation.raw_index must be within Google "
                "Trends' own documented [0, 100] scale."
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "GoogleTrendsRawObservation":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


@dataclass(frozen=True)
class GoogleTrendsAnchorObservation:
    """One governed anchor-series observation for one `query_set_id`/week,
    after this record's deterministic 0-1 rescaling (G4) and
    suppressed-zero missingness treatment (G3). `raw_index` is retained
    verbatim alongside the computed `anchor_value` - the raw series is
    never discarded. `coverage_state` is `STATE_SUPPRESSED` for a raw
    zero (Google's own documented "low volume appears as 0" behaviour -
    a real but untrustworthy-as-precise source number, not a confirmed
    zero and not an undefined ratio) and `None` for an ordinary,
    non-zero, directly observed week - mirroring `core.seo_visibility`'s
    equivalent judgement that an ordinary observed source fact should
    not be forced into `estimated`/`modelled`."""

    query_set_id: str
    week: str
    raw_index: float
    anchor_value: float
    coverage_state: Optional[str] = None
    schema_version: int = GOOGLE_TRENDS_ANCHOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.query_set_id:
            raise ValueError("GoogleTrendsAnchorObservation requires a query_set_id.")
        if not self.week:
            raise ValueError("GoogleTrendsAnchorObservation requires a week.")
        if not (0.0 <= self.raw_index <= 100.0):
            raise ValueError(
                "GoogleTrendsAnchorObservation.raw_index must be within "
                "Google Trends' own documented [0, 100] scale."
            )
        expected_anchor = self.raw_index / 100.0
        if abs(self.anchor_value - expected_anchor) > 1e-9:
            raise ValueError(
                "GoogleTrendsAnchorObservation.anchor_value does not equal "
                "raw_index / 100.0 (this record's approved rescaling, G4)."
            )
        if (
            self.coverage_state is not None
            and self.coverage_state not in COVERAGE_STATES
        ):
            raise ValueError(
                f"GoogleTrendsAnchorObservation: unknown coverage_state "
                f"'{self.coverage_state}' (expected one of {COVERAGE_STATES} "
                "or None)."
            )
        if self.raw_index == 0.0 and self.coverage_state != STATE_SUPPRESSED:
            raise ValueError(
                "GoogleTrendsAnchorObservation: a raw_index of 0 must carry "
                "coverage_state='suppressed' (Google's own documented "
                "low-volume floor behaviour, G3) - it must never be treated "
                "as an ordinary observed value."
            )
        if self.raw_index != 0.0 and self.coverage_state == STATE_SUPPRESSED:
            raise ValueError(
                "GoogleTrendsAnchorObservation: coverage_state='suppressed' "
                "requires raw_index == 0.0."
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "GoogleTrendsAnchorObservation":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


@dataclass(frozen=True)
class GoogleTrendsAnchorFitInputs:
    """The fit-time Google Trends observation boundary for Candidate A.

    ``observations`` must cover the complete model window in one governed
    query-set extraction.  ``model_weeks`` is supplied separately because a
    multi-market fit can contain more than one row for the same calendar
    week.  The builder expands the one weekly anchor value to each matching
    model row; it never interpolates, forward-fills, or silently drops a
    missing week.

    The observation likelihood uses a fixed loading of one: the latent
    Candidate A demand state is measured in the same rescaled relative-index
    units as ``anchor_value``.  ``measurement_sigma`` is an explicitly
    configured observation uncertainty, not a free scale/loading parameter.
    """

    query_set: GoogleTrendsQuerySetDefinition
    observations: Tuple[GoogleTrendsAnchorObservation, ...]
    model_weeks: Tuple[str, ...]
    measurement_sigma: float = 0.15

    def __post_init__(self) -> None:
        if not self.observations:
            raise ValueError(
                "GoogleTrendsAnchorFitInputs requires at least one observation."
            )
        if not self.model_weeks:
            raise ValueError(
                "GoogleTrendsAnchorFitInputs requires at least one model week."
            )
        if not np.isfinite(self.measurement_sigma) or self.measurement_sigma <= 0:
            raise ValueError(
                "GoogleTrendsAnchorFitInputs.measurement_sigma must be finite "
                "and strictly positive."
            )
        query_ids = {item.query_set_id for item in self.observations}
        if query_ids != {self.query_set.query_set_id}:
            raise ValueError(
                "GoogleTrendsAnchorFitInputs observations must all belong to "
                "the supplied governed query set."
            )
        observed_weeks = [item.week for item in self.observations]
        if len(set(observed_weeks)) != len(observed_weeks):
            raise ValueError(
                "GoogleTrendsAnchorFitInputs observations must have unique weeks."
            )
        missing = sorted(set(self.model_weeks) - set(observed_weeks))
        if missing:
            raise ValueError(
                "GoogleTrendsAnchorFitInputs is missing anchor observations for "
                f"model week(s): {missing}. A Candidate A fit must not infer "
                "or fill an absent Trends week."
            )

    def values_for_model_weeks(self) -> np.ndarray:
        """Return anchor values aligned to ``model_weeks`` exactly."""

        by_week = {item.week: item.anchor_value for item in self.observations}
        return np.asarray([by_week[week] for week in self.model_weeks], dtype=float)

    def coverage_states_for_model_weeks(self) -> Tuple[Optional[str], ...]:
        by_week = {item.week: item.coverage_state for item in self.observations}
        return tuple(by_week[week] for week in self.model_weeks)

    def to_dict(self) -> dict:
        return {
            "query_set": self.query_set.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
            "model_weeks": list(self.model_weeks),
            "measurement_sigma": self.measurement_sigma,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "GoogleTrendsAnchorFitInputs":
        query_set = GoogleTrendsQuerySetDefinition.from_dict(values["query_set"])
        observations = tuple(
            GoogleTrendsAnchorObservation.from_dict(item)
            for item in values.get("observations") or ()
        )
        return cls(
            query_set=query_set,
            observations=observations,
            model_weeks=tuple(str(item) for item in values.get("model_weeks") or ()),
            measurement_sigma=float(values.get("measurement_sigma", 0.15)),
        )


def compute_anchor_series(
    query_set_id: str,
    raw_observations: Sequence[GoogleTrendsRawObservation],
) -> List[GoogleTrendsAnchorObservation]:
    """Deterministically compute one query set's governed anchor series
    from its raw Google Trends rows (G2, G3, G4 of the decision record).

    Every supplied row must carry the same `query_set_id` as the one
    passed explicitly here - combining rows from more than one query set
    (e.g. two separate extraction calls) into a single series is a hard
    validation error (G2: Google re-peaks its own 0-100 scale per
    request, so silently combining extractions would silently corrupt
    the series). A caller that genuinely needs to extend a series beyond
    one extraction's window must first define and approve an explicit
    overlap-rescaling method - not guessed here.
    """
    if not query_set_id:
        raise ValueError("compute_anchor_series requires a query_set_id.")
    mismatched = [
        row.query_set_id for row in raw_observations if row.query_set_id != query_set_id
    ]
    if mismatched:
        raise ValueError(
            "compute_anchor_series: all raw_observations must share the "
            f"requested query_set_id {query_set_id!r}; found other "
            f"query_set_id(s) {sorted(set(mismatched))!r} - combining rows "
            "from more than one extraction/query set into a single series "
            "is not permitted without an approved overlap-rescaling method "
            "(decision record G2)."
        )

    weeks_seen: dict = {}
    for row in raw_observations:
        if row.week in weeks_seen:
            raise ValueError(
                f"compute_anchor_series: duplicate week {row.week!r} in "
                f"raw_observations for query_set_id {query_set_id!r}."
            )
        weeks_seen[row.week] = row

    results = []
    for week in sorted(weeks_seen):
        row = weeks_seen[week]
        anchor_value = row.raw_index / 100.0
        coverage_state = STATE_SUPPRESSED if row.raw_index == 0.0 else None
        results.append(
            GoogleTrendsAnchorObservation(
                query_set_id=query_set_id,
                week=week,
                raw_index=row.raw_index,
                anchor_value=anchor_value,
                coverage_state=coverage_state,
            )
        )
    return results


def build_google_trends_identification_declaration(
    query_set: GoogleTrendsQuerySetDefinition,
    *,
    latent_state_id: str = CANDIDATE_A_LATENT_DEMAND_STATE_ID,
) -> LatentStateIdentificationDeclaration:
    """Build the `REQ-LATENT-001` identifying-anchor declaration (G5) for
    Candidate A's latent branded-search demand, anchored to `query_set`
    at a fixed loading of `GOOGLE_TRENDS_ANCHOR_FIXED_LOADING`.

    This function only assembles a declaration record for
    `core.latent_state_identification.assess_latent_state_identification`
    to consume - it does not itself impose the constraint inside any
    PyMC model (deferred, see module docstring), and it never modifies
    `core.latent_state_identification`.
    """
    anchor_reference = (
        f"google_trends:{query_set.query_set_id}"
        f":loading={GOOGLE_TRENDS_ANCHOR_FIXED_LOADING}"
    )
    description = (
        "latent_branded_search_demand is anchored to the governed Google "
        f"Trends query set '{query_set.query_set_id}' "
        f"(terms={list(query_set.branded_terms)}; "
        f"geography={query_set.geography}; "
        f"window={query_set.time_range_start}..{query_set.time_range_end}) "
        f"at a FIXED loading of {GOOGLE_TRENDS_ANCHOR_FIXED_LOADING} (never "
        "estimated) between the latent state and this query set's "
        "rescaled anchor_value (raw Google Trends index / 100). One unit "
        "of the resulting latent state means one point of this governed, "
        "rescaled, relative Google Trends index for the approved branded "
        "query set - NOT one search, one click, or any absolute search "
        "volume (Decision 9's own explicit caution, reaffirmed by "
        "REQ-LATENT-001's 2026-08-30 addendum)."
    )
    return LatentStateIdentificationDeclaration(
        latent_state_id=latent_state_id,
        strategy_kind=STRATEGY_ANCHORED_TO_OBSERVED,
        description=description,
        anchor_reference=anchor_reference,
        metadata={
            "query_set_id": query_set.query_set_id,
            "fixed_loading": GOOGLE_TRENDS_ANCHOR_FIXED_LOADING,
            "geography": query_set.geography,
            "time_range_start": query_set.time_range_start,
            "time_range_end": query_set.time_range_end,
        },
    )


@dataclass(frozen=True)
class GoogleTrendsAnchorComparisonPoint:
    """One diagnostic comparison point pairing the governed anchor series
    with a caller-supplied fitted latent-state value for the same week
    (G6: "the branded-demand trend must be shown in diagnostics in a
    form comparable to the observed Google Trends series"). This module
    performs no fitting itself - `fitted_latent_value` is whatever the
    caller supplies (e.g. a posterior median per week), mirroring
    `core.structural_stability`'s "the caller supplies the fold-local
    computation" pattern already reused by `core.latent_state_
    identification`."""

    week: str
    anchor_value: float
    coverage_state: Optional[str]
    fitted_latent_value: Optional[float]

    def to_dict(self) -> dict:
        return asdict(self)


def compare_anchor_to_fitted_latent_series(
    anchor_series: Sequence[GoogleTrendsAnchorObservation],
    fitted_latent_by_week: Mapping[str, float],
) -> List[GoogleTrendsAnchorComparisonPoint]:
    """Pair `anchor_series` with a caller-supplied `{week: fitted_latent_
    value}` mapping for diagnostic display (G6). A week present in
    `anchor_series` but absent from `fitted_latent_by_week` yields
    `fitted_latent_value=None` - this function never fabricates a fitted
    value; it only reports what the caller actually supplied."""
    return [
        GoogleTrendsAnchorComparisonPoint(
            week=obs.week,
            anchor_value=obs.anchor_value,
            coverage_state=obs.coverage_state,
            fitted_latent_value=fitted_latent_by_week.get(obs.week),
        )
        for obs in anchor_series
    ]
