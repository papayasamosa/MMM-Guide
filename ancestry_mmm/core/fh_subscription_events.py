"""Reference implementation of the approved Family History GSA / Net Bill
Through event-level derivation rules (REQ-OUT-003, "Post-UI/UX
Implementation Instructions: Approved Business Decisions" Decision 1).

Governance boundary - read before using this module
-----------------------------------------------------
This repository's existing authority is explicit that the MMM application
must **not** reconstruct customer-level billing events, payment maturity,
or subscription history by default:

- `docs/net_billthrough.md` and `ancestry_mmm/core/net_billthrough.py`'s own
  module docstring: "Net bill-through is an input KPI, not a transformation
  performed by the MMM. This module deliberately contains no signup,
  billing, cancellation, refund, offer or maturity-estimation logic."
- `REQ-NBT-002`: "the MMM does not reconstruct customer-level maturity when
  the authoritative feed satisfies this contract... Modelling code must not
  invent customer-level exclusion logic."
- `docs/PRD/Ancestry_MMM_PRD_Part_5_...md` ("Net Bill Through working data
  contract"): "The MMM application must ingest and validate the supplied
  outcome. It must not reconstruct customer-level billing events, payment
  maturity or subscription history by default. A separate customer-level
  maturity use case may be introduced only through an approved requirement
  and privacy review."

A repository-wide audit for this Phase B pass confirmed no raw, event-level
(one-row-per-subscriber) Family History data shape exists anywhere in this
repo's ingestion code, schemas, or sample data - every FH data shape in the
application is pre-aggregated to `week x market x segment`. There is
therefore no data source this module could be silently wired into even if
that were desired.

This module exists for two narrower, explicitly non-default purposes:

1. A precise, tested reference implementation of Decision 1's governed
   business rules (hard-offer vs. free-trial GSA timing, the NBT
   signup-date pull-back, refund exclusion, and the 120-day DNA Cross-sell
   window), ready to be wired into a *future* approved event-level
   ingestion path without re-deriving the rules from scratch - if and when
   such a path is authorised through its own approved requirement and
   privacy review, per the PRD passage above.
2. An optional, out-of-band reconciliation/QA utility an analyst may run
   against a raw extract to sanity-check a supplied aggregate GSA/NBT feed.
   This is never a replacement for `core.net_billthrough`'s supplied-feed
   validation, and nothing in this module is imported by
   `core.net_billthrough`, `data.preprocessor`, or any default
   ingestion/model-training path.

`FhSubscriptionEvent` is a well-specified *synthetic* input shape defined by
this module, not an adaptation of any existing raw data contract (none
exists to adapt).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

import pandas as pd

from .outcomes import (
    DNA_CROSS_SELL_WINDOW_DAYS,
    FH_SEGMENT_DNA_CROSS_SELL,
    FH_SEGMENT_NEW,
    FH_SEGMENT_WINBACK,
    FH_SEGMENTS,
    METRIC_KEY_FH_GSA,
    METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
)

OFFER_TYPE_HARD = "hard_offer"
OFFER_TYPE_FREE_TRIAL = "free_trial"
OFFER_TYPES = (OFFER_TYPE_HARD, OFFER_TYPE_FREE_TRIAL)


@dataclass(frozen=True)
class FhSubscriptionEvent:
    """One raw subscriber-level Family History subscription record - the
    well-defined synthetic input shape this module operates on (see module
    docstring: no such raw shape currently exists in this repo's real data
    contracts).

    `offer_type` must be one of `OFFER_TYPES`. `trial_billthrough_date` is
    only meaningful for a free trial; a hard offer bills through at signup
    by definition and must not carry one. `supplied_segment`, when present,
    is authoritative and is never independently re-derived (REQ-OUT-003
    §2). `prior_fh_subscription` and `dna_kit_purchase_date` are the raw
    fields `derive_fh_segment` uses only when `supplied_segment` is absent.
    """

    subscriber_id: str
    market: str
    signup_date: str
    offer_type: str
    trial_billthrough_date: Optional[str] = None
    refunded: bool = False
    supplied_segment: Optional[str] = None
    prior_fh_subscription: Optional[bool] = None
    dna_kit_purchase_date: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.subscriber_id:
            raise ValueError("FhSubscriptionEvent requires a subscriber_id.")
        if not self.market:
            raise ValueError("FhSubscriptionEvent requires a market.")
        if self.offer_type not in OFFER_TYPES:
            raise ValueError(
                f"FhSubscriptionEvent: unknown offer_type '{self.offer_type}' "
                f"(expected one of {OFFER_TYPES})."
            )
        try:
            pd.Timestamp(self.signup_date)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"FhSubscriptionEvent: invalid signup_date '{self.signup_date}'."
            ) from exc
        if (
            self.offer_type == OFFER_TYPE_HARD
            and self.trial_billthrough_date is not None
        ):
            raise ValueError(
                "FhSubscriptionEvent: a hard offer must not carry a "
                "trial_billthrough_date - it bills through at signup by "
                "definition, it has no separate trial-conversion date."
            )
        if self.trial_billthrough_date is not None:
            try:
                pd.Timestamp(self.trial_billthrough_date)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "FhSubscriptionEvent: invalid trial_billthrough_date "
                    f"'{self.trial_billthrough_date}'."
                ) from exc
        if (
            self.supplied_segment is not None
            and self.supplied_segment not in FH_SEGMENTS
        ):
            raise ValueError(
                f"FhSubscriptionEvent: unknown supplied_segment "
                f"'{self.supplied_segment}' (expected one of {FH_SEGMENTS})."
            )
        if self.dna_kit_purchase_date is not None:
            try:
                pd.Timestamp(self.dna_kit_purchase_date)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "FhSubscriptionEvent: invalid dna_kit_purchase_date "
                    f"'{self.dna_kit_purchase_date}'."
                ) from exc


def derive_fh_segment(event: FhSubscriptionEvent) -> str:
    """Resolve `event`'s Family History segment (REQ-OUT-003 §2/§3).

    Prefers `event.supplied_segment` when present - a source-supplied
    classification is authoritative and is never independently re-derived
    or overridden. Only derives a segment from raw fields when no supplied
    segment exists, and fails closed (raises `ValueError`) when the
    required fields are missing or ambiguous, rather than guessing. Never
    returns a fourth segment - the return value is always one of
    `FH_SEGMENTS`.
    """
    if event.supplied_segment is not None:
        return event.supplied_segment

    dna_cross_sell = False
    if event.dna_kit_purchase_date is not None:
        kit_date = pd.Timestamp(event.dna_kit_purchase_date).normalize()
        signup = pd.Timestamp(event.signup_date).normalize()
        if signup < kit_date:
            raise ValueError(
                f"FhSubscriptionEvent {event.subscriber_id!r}: signup_date "
                "is before dna_kit_purchase_date - ambiguous DNA Cross-sell "
                "derivation; refusing to guess."
            )
        gap_days = (signup - kit_date).days
        dna_cross_sell = gap_days <= DNA_CROSS_SELL_WINDOW_DAYS

    if dna_cross_sell:
        return FH_SEGMENT_DNA_CROSS_SELL

    if event.prior_fh_subscription is None:
        raise ValueError(
            f"FhSubscriptionEvent {event.subscriber_id!r}: cannot derive "
            "New vs. Winback without a supplied_segment or an explicit "
            "prior_fh_subscription flag - refusing to guess (fail closed "
            "per REQ-OUT-003)."
        )
    return FH_SEGMENT_WINBACK if event.prior_fh_subscription else FH_SEGMENT_NEW


def compute_gsa_date(event: FhSubscriptionEvent) -> Optional[pd.Timestamp]:
    """The date `event` counts as a GSA, or `None` if it never becomes one.

    Hard offers count on the signup date. Free trials count only on the
    date they successfully bill through; a trial that never bills through
    (`trial_billthrough_date is None`) is not a GSA at all. Refund status
    does not affect GSA - GSA is a gross acquisition count (Decision 1);
    only Net Bill Through nets out refunds.
    """
    if event.offer_type == OFFER_TYPE_HARD:
        return pd.Timestamp(event.signup_date).normalize()
    if event.trial_billthrough_date is not None:
        return pd.Timestamp(event.trial_billthrough_date).normalize()
    return None


def compute_net_billthrough_date(event: FhSubscriptionEvent) -> Optional[pd.Timestamp]:
    """The date `event` counts as a Net Bill Through, or `None` if it never
    qualifies.

    Starts from the population that eventually became a GSA
    (`compute_gsa_date` is not `None`); a refunded subscription is then
    excluded entirely - this is what makes it "net" (Decision 1). For a
    qualifying free trial, the date is moved BACK to the original signup
    date rather than the later bill-through date; a hard offer's date
    already aligns (signup date == bill-through date), so nothing changes
    for it.
    """
    if compute_gsa_date(event) is None:
        return None
    if event.refunded:
        return None
    return pd.Timestamp(event.signup_date).normalize()


@dataclass(frozen=True)
class FhComputedOutcome:
    """One subscriber event's resolved GSA/NBT dates and segment - the
    per-event output of this module's computation, before weekly
    aggregation."""

    subscriber_id: str
    market: str
    segment: str
    gsa_date: Optional[pd.Timestamp]
    net_billthrough_date: Optional[pd.Timestamp]


def compute_fh_outcomes(
    events: Sequence[FhSubscriptionEvent],
) -> List[FhComputedOutcome]:
    """Resolve GSA date, Net Bill Through date, and segment for every event
    in `events`, applying REQ-OUT-003's governed rules event-by-event.
    Fails closed (raises) on the first event whose segment cannot be
    safely determined - never emits a partially-classified result set."""
    results: List[FhComputedOutcome] = []
    for event in events:
        segment = derive_fh_segment(event)
        results.append(
            FhComputedOutcome(
                subscriber_id=event.subscriber_id,
                market=event.market,
                segment=segment,
                gsa_date=compute_gsa_date(event),
                net_billthrough_date=compute_net_billthrough_date(event),
            )
        )
    return results


def _week_start(date: pd.Timestamp, anchor: Optional[pd.Timestamp]) -> pd.Timestamp:
    """Bucket `date` into its week-start.

    With no `anchor`, uses a Monday-start ISO week (this codebase's default
    weekly convention). With an explicit `anchor` (e.g. a supplied feed's
    `model_start_week`), buckets into 7-day windows starting from that
    anchor instead, matching `core.net_billthrough`'s
    ``pd.date_range(start, end, freq="7D")`` convention so this module's
    output can align with an existing weekly grid rather than its own
    independent one.
    """
    date = pd.Timestamp(date).normalize()
    if anchor is None:
        return date - pd.Timedelta(days=date.weekday())
    anchor_ts = pd.Timestamp(anchor).normalize()
    weeks_since_anchor = (date - anchor_ts).days // 7
    return anchor_ts + pd.Timedelta(days=7 * int(weeks_since_anchor))


def aggregate_weekly_fh_outcomes(
    outcomes: Sequence[FhComputedOutcome],
    *,
    week_anchor: Optional[str] = None,
) -> pd.DataFrame:
    """Bucket per-event GSA/NBT outcomes into `week x market x segment`
    counts, in the same `metric_key` vocabulary
    (`METRIC_KEY_FH_GSA`/`METRIC_KEY_FH_NET_BILLTHROUGH_COUNT`) the rest of
    this codebase uses - so a caller with an approved event-level source
    could feed this into the same downstream shape a supplied weekly feed
    already uses (`core.net_billthrough`), without a further ad-hoc
    reshaping step.

    `week_anchor`, if given, is a date string; weeks are bucketed as 7-day
    windows starting from it (matching a specific model's
    `model_start_week`). With no anchor, Monday-start ISO weeks are used.

    A market/segment/metric combination with zero events in a given week is
    absent from the result, never a fabricated zero row - matching this
    codebase's "missing is not zero" convention (`REQ-COVERAGE-001`). A
    caller producing a dense weekly frame is responsible for its own
    explicit missing-vs-zero reconciliation against that convention.
    """
    anchor_ts = pd.Timestamp(week_anchor) if week_anchor is not None else None
    rows = []
    for outcome in outcomes:
        if outcome.gsa_date is not None:
            rows.append(
                {
                    "week_start": _week_start(outcome.gsa_date, anchor_ts),
                    "market": outcome.market,
                    "segment": outcome.segment,
                    "metric_key": METRIC_KEY_FH_GSA,
                }
            )
        if outcome.net_billthrough_date is not None:
            rows.append(
                {
                    "week_start": _week_start(outcome.net_billthrough_date, anchor_ts),
                    "market": outcome.market,
                    "segment": outcome.segment,
                    "metric_key": METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=["week_start", "market", "segment", "metric_key", "count"]
        )
    frame = pd.DataFrame(rows)
    grouped = frame.groupby(
        ["week_start", "market", "segment", "metric_key"], as_index=False
    ).size()
    grouped = grouped.rename(columns={"size": "count"})
    return grouped.sort_values(
        ["week_start", "market", "segment", "metric_key"]
    ).reset_index(drop=True)
