"""Governed weekly aggregate outcome-valuation input contract (REQ-ECON-002).

Family History projected LTR and DNA revenue are supplied as aggregate
monetary totals by ``market x week x segment`` - never per-customer or
per-kit. This module governs that input's identity, currency metadata,
denominator linkage, and fail-closed missingness contract only. It
deliberately contains no rate-derivation, posterior-join, or ROI
arithmetic (see REQ-ECON-003 for that engine) and no reporting-period
aggregation (see REQ-ECON-004).

The upstream LTR/revenue methodology itself is authoritative and is
never reproduced, modified, or re-derived here (REQ-ECON-002
Requirement 2).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, cast

import pandas as pd

from .coverage import (
    COVERAGE_STATES,
    STATE_ESTIMATED,
    STATE_MISSING_EXPECTED,
    STATE_MODELLED,
    STATE_NOT_APPLICABLE,
    STATE_OBSERVED_ZERO,
    STATE_SUPPRESSED,
    STATE_UNAVAILABLE_SOURCE,
    STATE_UNKNOWN,
)
from .outcomes import SEGMENT_DIMENSIONS, SEGMENT_DIMENSION_UNSPECIFIED

VALUATION_KIND_FH_LTR = "fh_ltr"
VALUATION_KIND_DNA_REVENUE = "dna_revenue"
VALUATION_KINDS = (VALUATION_KIND_FH_LTR, VALUATION_KIND_DNA_REVENUE)

_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

# States for which a supplied aggregate_value is expected (a real,
# meaningful number, including a genuine zero: observed_zero). estimated/
# modelled likewise carry a number, even though REQ-ECON-002's fail-closed
# missingness policy means production FH/DNA valuation data is not
# expected to legitimately use them (no interpolation/estimation is
# permitted) - they remain structurally valid per the shared
# REQ-COVERAGE-001 vocabulary. All other states (missing_expected,
# not_applicable, unavailable_source, suppressed, unknown) denote an
# absent record - aggregate_value must be None, never a fabricated number.
_STATES_REQUIRING_A_VALUE = frozenset(
    {STATE_OBSERVED_ZERO, STATE_ESTIMATED, STATE_MODELLED}
)
_STATES_DENOTING_ABSENCE = frozenset(
    {
        STATE_MISSING_EXPECTED,
        STATE_NOT_APPLICABLE,
        STATE_UNAVAILABLE_SOURCE,
        STATE_SUPPRESSED,
        STATE_UNKNOWN,
    }
)
assert _STATES_REQUIRING_A_VALUE | _STATES_DENOTING_ABSENCE == frozenset(
    COVERAGE_STATES
)


@dataclass(frozen=True)
class WeeklyOutcomeValuationRecord:
    """One governed ``market x week x segment`` aggregate valuation cell.

    REQ-ECON-002 Requirements 2-8. ``valuation_kind`` distinguishes FH
    projected LTR from DNA revenue - the two are never represented by a
    shared object (Requirement 1). ``denominator_outcome_id`` must
    reference an existing, approved outcome; no default is ever inferred
    (Requirements 3, 5). ``currency`` is mandatory whenever a value is
    present and is never inferred from ``market`` (Requirement 7).
    ``quality_status`` uses the existing `core.coverage` canonical
    missingness vocabulary rather than a bespoke boolean (Requirement 8).
    """

    valuation_kind: str
    market: str
    week: str
    segment: str
    denominator_outcome_id: str
    quality_status: str
    segment_dimension: str = SEGMENT_DIMENSION_UNSPECIFIED
    aggregate_value: Optional[float] = None
    currency: Optional[str] = None
    source: str = ""
    source_version: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.valuation_kind not in VALUATION_KINDS:
            raise ValueError(
                f"WeeklyOutcomeValuationRecord: unknown valuation_kind "
                f"'{self.valuation_kind}' (expected one of {VALUATION_KINDS})."
            )
        if not self.market:
            raise ValueError("WeeklyOutcomeValuationRecord requires a market.")
        try:
            pd.Timestamp(self.week)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"WeeklyOutcomeValuationRecord: invalid week '{self.week}'."
            ) from exc
        if not self.segment:
            raise ValueError("WeeklyOutcomeValuationRecord requires a segment.")
        if self.segment_dimension not in SEGMENT_DIMENSIONS:
            raise ValueError(
                f"WeeklyOutcomeValuationRecord: unknown segment_dimension "
                f"'{self.segment_dimension}' (expected one of {SEGMENT_DIMENSIONS})."
            )
        if not self.denominator_outcome_id:
            # REQ-ECON-002 Requirements 3/5: no default denominator is ever
            # authorised - an explicit, non-empty reference is mandatory.
            raise ValueError(
                "WeeklyOutcomeValuationRecord requires an explicit "
                "denominator_outcome_id - no default denominator (e.g. GSA) "
                "is ever inferred."
            )
        if self.quality_status not in COVERAGE_STATES:
            raise ValueError(
                f"WeeklyOutcomeValuationRecord: unknown quality_status "
                f"'{self.quality_status}' (expected one of {COVERAGE_STATES})."
            )

        value_expected = self.quality_status in _STATES_REQUIRING_A_VALUE
        if value_expected and self.aggregate_value is None:
            raise ValueError(
                f"WeeklyOutcomeValuationRecord: quality_status "
                f"'{self.quality_status}' requires a non-None aggregate_value."
            )
        if not value_expected and self.aggregate_value is not None:
            raise ValueError(
                f"WeeklyOutcomeValuationRecord: quality_status "
                f"'{self.quality_status}' denotes an absent record - "
                f"aggregate_value must be None, never a fabricated number."
            )
        if self.aggregate_value is not None:
            if self.aggregate_value < 0:
                raise ValueError(
                    "WeeklyOutcomeValuationRecord: aggregate_value must be "
                    "non-negative (until Finance approves negative value "
                    "semantics, mirroring OutcomeValueMapping's existing rule)."
                )
            # REQ-ECON-002 Requirement 7: currency is mandatory whenever a
            # value is present, and never inferred from market.
            if not self.currency:
                raise ValueError(
                    "WeeklyOutcomeValuationRecord: currency is required "
                    "whenever aggregate_value is supplied - it is never "
                    "inferred from market."
                )
        if self.currency is not None and not _ISO_CURRENCY_RE.match(self.currency):
            raise ValueError(
                f"WeeklyOutcomeValuationRecord: currency '{self.currency}' is "
                "not a valid ISO-3 uppercase currency code."
            )
        if self.quality_status == STATE_OBSERVED_ZERO and self.aggregate_value not in (
            0,
            0.0,
        ):
            raise ValueError(
                "WeeklyOutcomeValuationRecord: quality_status 'observed_zero' "
                f"requires aggregate_value == 0, got {self.aggregate_value!r}."
            )

    def cell_key(self) -> tuple:
        """Identity key for uniqueness checks: one record per valuation
        kind/market/week/segment cell."""
        return (self.valuation_kind, self.market, self.week, self.segment)

    def fingerprint(self) -> str:
        """Deterministic fingerprint over this record's identity and
        content fields - excludes nothing administrative, since every
        field here is fit/value-relevant (unlike REQ-SEARCH-001's
        governance-only exclusions, this object has no purely
        administrative field yet)."""
        payload: Dict[str, object] = asdict(self)
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WeeklyOutcomeValuationRecord":
        known = cls.__dataclass_fields__
        return cls(**cast(Any, {k: v for k, v in value.items() if k in known}))


def _outcome_value(outcome: object, key: str, default=None):
    if isinstance(outcome, dict):
        return outcome.get(key, default)
    return getattr(outcome, key, default)


def validate_weekly_outcome_valuation_catalogue(
    records: Sequence[WeeklyOutcomeValuationRecord],
    outcome_definitions: Sequence[object],
) -> List[str]:
    """Structural, fail-closed validation across a full catalogue of
    supplied weekly valuation records (REQ-ECON-002 Requirements 1-8).

    This validates the *supplied catalogue's own* internal consistency and
    its denominator references against the governed outcome registry. It
    does not compute, derive, or validate any rate, join, or posterior
    quantity - see REQ-ECON-003 for that engine's own validation.
    """
    issues: List[str] = []

    outcome_ids = {str(_outcome_value(o, "outcome_id")) for o in outcome_definitions}
    outcome_by_id = {
        str(_outcome_value(o, "outcome_id")): o for o in outcome_definitions
    }

    seen_cells: Dict[tuple, int] = {}
    seen_currencies_by_kind: Dict[str, set] = {}

    for index, record in enumerate(records):
        cell = record.cell_key()
        if cell in seen_cells:
            issues.append(
                f"Duplicate weekly outcome valuation record for "
                f"valuation_kind='{record.valuation_kind}', "
                f"market='{record.market}', week='{record.week}', "
                f"segment='{record.segment}' (rows {seen_cells[cell]} and {index})."
            )
        else:
            seen_cells[cell] = index

        if record.denominator_outcome_id not in outcome_ids:
            issues.append(
                f"Row {index}: denominator_outcome_id "
                f"'{record.denominator_outcome_id}' does not reference any "
                f"approved outcome definition - no default denominator is "
                f"ever substituted (e.g. GSA must never be assumed)."
            )
        else:
            denominator = outcome_by_id[record.denominator_outcome_id]
            denominator_aggregation = _outcome_value(
                denominator, "aggregation_type", ""
            )
            if denominator_aggregation and denominator_aggregation != "count":
                issues.append(
                    f"Row {index}: denominator_outcome_id "
                    f"'{record.denominator_outcome_id}' is not a count-type "
                    f"outcome (aggregation_type="
                    f"'{denominator_aggregation}') - a valuation rate "
                    f"denominator must be a count."
                )

        if record.aggregate_value is not None:
            seen_currencies_by_kind.setdefault(record.valuation_kind, set()).add(
                record.currency
            )

    # REQ-ECON-002 Requirement 7: currency is per-record, never assumed
    # uniform - but flag (not block) when a single valuation_kind mixes
    # currencies across the catalogue, since that is unusual enough to
    # warrant explicit analyst attention rather than silent pass-through.
    for kind, currencies in seen_currencies_by_kind.items():
        if len(currencies) > 1:
            issues.append(
                f"valuation_kind '{kind}' has records in more than one "
                f"currency ({sorted(currencies)}) - confirm this is "
                f"intentional (e.g. multi-market supply), not a data error."
            )

    return issues


def cross_validate_against_observed_denominator(
    records: Sequence[WeeklyOutcomeValuationRecord],
    observed_denominator_counts: pd.DataFrame,
    *,
    market_column: str = "market",
    week_column: str = "week",
    segment_column: str = "segment",
    outcome_id_column: str = "outcome_id",
    count_column: str = "count",
) -> List[str]:
    """Cross-check supplied valuation records against already-ingested
    observed denominator-outcome counts for the same market/week/segment
    (REQ-ECON-002 Requirement 8's fail-closed missingness contract, and
    its explicit zero/zero carve-out).

    ``observed_denominator_counts`` is the already-governed outcome data
    this application has already ingested for the referenced
    ``denominator_outcome_id`` - never re-derived or fabricated here.

    This does not consult the fitted model's posterior incremental
    outcome (REQ-ECON-003 Requirement 2 covers that, at rate-derivation
    time, once a model exists) - only the raw observed count available at
    upload/validation time.
    """
    issues: List[str] = []
    frame = observed_denominator_counts.copy()
    frame[week_column] = pd.to_datetime(frame[week_column], errors="coerce")

    lookup: Dict[tuple, float] = {}
    for _, row in frame.iterrows():
        key = (
            str(row[outcome_id_column]),
            str(row[market_column]),
            pd.Timestamp(row[week_column]).normalize(),
            str(row[segment_column]),
        )
        lookup[key] = row[count_column]

    for index, record in enumerate(records):
        try:
            week_ts = pd.Timestamp(record.week).normalize()
        except (TypeError, ValueError):
            continue  # already reported by __post_init__/catalogue validation
        key = (record.denominator_outcome_id, record.market, week_ts, record.segment)
        if key not in lookup:
            continue  # no observed data supplied for this cell - not this function's concern
        observed_count = lookup[key]

        denominator_is_zero = pd.notna(observed_count) and observed_count == 0
        denominator_missing = pd.isna(observed_count)

        if record.aggregate_value is None:
            # A missing valuation record is only unremarkable when the
            # observed denominator is itself genuinely zero (nothing to
            # value) - any other case (a non-zero or missing denominator
            # with no supplied value) must be surfaced.
            if not denominator_is_zero:
                issues.append(
                    f"Row {index}: valuation is missing for "
                    f"market='{record.market}', week='{record.week}', "
                    f"segment='{record.segment}', but the observed "
                    f"denominator outcome is "
                    f"{'missing' if denominator_missing else observed_count} "
                    f"(not a genuine zero) - this must be surfaced, not "
                    f"silently treated as an unremarkable gap."
                )
        else:
            if denominator_is_zero and record.aggregate_value != 0:
                issues.append(
                    f"Row {index}: market='{record.market}', "
                    f"week='{record.week}', segment='{record.segment}' has "
                    f"a genuinely zero observed denominator outcome but a "
                    f"non-zero supplied value ({record.aggregate_value}) - "
                    f"an inconsistent case requiring a valuation rate from "
                    f"a zero denominator, surfaced rather than guessed."
                )
            if denominator_missing:
                issues.append(
                    f"Row {index}: market='{record.market}', "
                    f"week='{record.week}', segment='{record.segment}' has "
                    f"a supplied value but the observed denominator outcome "
                    f"is missing - a valuation rate cannot be derived; "
                    f"surfaced rather than guessed."
                )

    return issues
