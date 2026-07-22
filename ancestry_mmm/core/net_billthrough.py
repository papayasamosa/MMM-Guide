"""
Deterministic Family History net bill-through transformation (PR G1).

`fh_net_billthrough_count` (core.outcomes.METRIC_KEY_FH_NET_BILLTHROUGH_COUNT)
is a genuinely different kind of number from `fh_gsa_finance_date`
(core.outcomes.METRIC_KEY_FH_GSA_FINANCE_DATE) even though both eventually
describe "how many Family History subscriptions stuck", and this module is
what keeps them from ever being confused or merged:

- `fh_gsa_finance_date` is booked on the date the billing/finance event
  itself happened - a normal source-column outcome, unaffected by anything
  in this module.
- `fh_net_billthrough_count` is booked BACK to `signup_date` -
  `date_basis="signup_date_attributed"` (core.outcomes.DATE_BASIS_VALUES) -
  so it lines up on the same axis media spend does (a signup driven by a
  given week's media should have its eventual bill-through outcome
  attributed to that week, not to whichever later week the customer's trial
  happened to convert or lapse). This is a genuine "which axis of time" the
  metric registry (docs/outcomes.md) already flags as inherently ambiguous
  for this metric_key, and this module resolves it: always signup-date, by
  construction, never event-date.

This is a deterministic transformation, not a fitted or inferred one - the
maturity window that decides whether a cohort's outcome is safe to report
yet (`NetBillthroughOfferRule.maturity_days`) is analyst-configured, matching
`core.pathways.MediaOutcomePathway`'s convention of explicit config over
fitted heuristics elsewhere in this codebase. A cohort younger than its
offer's maturity window is EXCLUDED from `net_billthrough_weekly_series` by
default, never zero-filled or extrapolated - see that function's docstring.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Tuple

import pandas as pd


@dataclass
class NetBillthroughOfferRule:
    """Deterministic, analyst-configured billing/cancellation rule for one
    `(market, offer_id)` - not a fitted or inferred parameter. `maturity_days`
    is how many days after `signup_date` this offer's eventual net
    bill-through outcome (did the customer stick around past their
    trial/refund window) is considered determined; a cohort younger than
    that has a genuinely unknown outcome, not merely an unobserved one."""
    offer_id: str
    market: str
    maturity_days: int
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "NetBillthroughOfferRule":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def validate(self) -> List[str]:
        errors = []
        label = self.offer_id or "(unnamed)"
        if not self.offer_id:
            errors.append("Every net bill-through offer rule needs an offer_id.")
        if not self.market:
            errors.append(f"Offer rule '{label}' has no market set.")
        if self.maturity_days is None or self.maturity_days < 0:
            errors.append(f"Offer rule '{label}' needs a non-negative maturity_days, got {self.maturity_days!r}.")
        return errors


def validate_offer_rules(rules: List[NetBillthroughOfferRule]) -> List[str]:
    errors: List[str] = []
    for r in rules:
        errors.extend(r.validate())
    seen = set()
    for r in rules:
        key = (r.market, r.offer_id)
        if key in seen:
            errors.append(f"Duplicate net bill-through offer rule for market '{r.market}', offer_id '{r.offer_id}'.")
        seen.add(key)
    return errors


def _rule_lookup(rules: List[NetBillthroughOfferRule]) -> Dict[Tuple[str, str], NetBillthroughOfferRule]:
    return {(r.market, r.offer_id): r for r in rules}


def cohort_maturity_status(
    cohorts: pd.DataFrame,
    offer_rules: List[NetBillthroughOfferRule],
    as_of_date: str,
) -> pd.DataFrame:
    """
    Adds `maturity_days`/`matures_on`/`is_mature` columns to `cohorts`
    (must have `market`/`signup_date`/`offer_id` columns) - a cohort is
    mature once `as_of_date >= signup_date + maturity_days` for its offer
    rule.

    Raises if any `(market, offer_id)` pair in `cohorts` has no matching
    rule - fails closed rather than silently assuming a maturity window,
    since there is no safe default maturity window to fall back to.
    """
    lookup = _rule_lookup(offer_rules)
    as_of = pd.Timestamp(as_of_date)

    out = cohorts.copy()
    out["signup_date"] = pd.to_datetime(out["signup_date"])

    missing = sorted({
        (m, o) for m, o in zip(out["market"], out["offer_id"])
        if (m, o) not in lookup
    })
    if missing:
        raise ValueError(
            f"No net bill-through offer rule configured for (market, offer_id) pairs: {missing}. "
            "Every cohort's maturity window must be explicitly configured - there is no safe default."
        )

    out["maturity_days"] = [lookup[(m, o)].maturity_days for m, o in zip(out["market"], out["offer_id"])]
    out["matures_on"] = out["signup_date"] + pd.to_timedelta(out["maturity_days"], unit="D")
    out["is_mature"] = out["matures_on"] <= as_of
    return out


def compute_net_billthrough_cohorts(
    signups: pd.DataFrame,
    cancellations: pd.DataFrame,
    offer_rules: List[NetBillthroughOfferRule],
    as_of_date: str,
) -> pd.DataFrame:
    """
    Deterministic net bill-through per `(market, signup_date, offer_id)`
    cohort: `gross_signups - cancellations`, attributed BACK to
    `signup_date` - never to whenever a cancellation happened to occur. This
    is what makes net bill-through comparable to media spend on the same
    signup-date axis a GSA/sign-up count already uses, instead of mixing an
    attribution basis with a raw event-date basis.

    `signups` needs `market`/`signup_date`/`offer_id`/`gross_signups`
    columns; `cancellations` needs `market`/`signup_date`/`offer_id`/
    `cancellations` - the caller is responsible for `cancellations` already
    being attributed back to each customer's original `signup_date` (a join
    on customer_id upstream of this function, not something this function
    re-derives).

    Returns one row per `(market, signup_date, offer_id)` with
    `gross_signups`, `cancellations`, `net_billthroughs` (`gross_signups -
    cancellations`, clipped at 0 - a cancellation count exceeding that
    cohort's own gross signups indicates a data/join error upstream, not a
    valid negative net bill-through), plus `maturity_days`/`matures_on`/
    `is_mature` from `cohort_maturity_status`.
    """
    merge_keys = ["market", "signup_date", "offer_id"]
    s = signups.copy()
    s["signup_date"] = pd.to_datetime(s["signup_date"])
    c = cancellations.copy()
    c["signup_date"] = pd.to_datetime(c["signup_date"])

    merged = s.merge(c, on=merge_keys, how="outer")
    merged["gross_signups"] = merged["gross_signups"].fillna(0.0)
    merged["cancellations"] = merged["cancellations"].fillna(0.0)
    merged["net_billthroughs"] = (merged["gross_signups"] - merged["cancellations"]).clip(lower=0.0)

    return cohort_maturity_status(merged, offer_rules, as_of_date)


def net_billthrough_weekly_series(
    cohorts: pd.DataFrame,
    *,
    include_immature: bool = False,
) -> pd.DataFrame:
    """
    Weekly `(market, week_start)` net bill-through series attributed to
    `signup_date` - the `fh_net_billthrough_count` metric
    (`core.outcomes.METRIC_KEY_FH_NET_BILLTHROUGH_COUNT`) with
    `date_basis="signup_date_attributed"` (`core.outcomes.DATE_BASIS_VALUES`).

    Immature cohorts (`is_mature=False`) are EXCLUDED by default, never
    zero-filled or extrapolated - a signup cohort that hasn't had time to
    mature genuinely has an unknown net bill-through outcome yet, and
    reporting it as 0 (or any other guessed value) would be a fabricated
    number, not a deterministic transformation. Pass `include_immature=True`
    only for an explicitly-labelled "provisional/incomplete" view (e.g. a
    diagnostics page visualising the still-maturing tail); never for
    anything feeding the model or a headline report - see
    `immature_cohort_summary` for the counterpart transparency view of
    exactly what got excluded.

    Weeks are Sunday-anchored (`W-SUN`), matching this codebase's existing
    weekly-aggregation convention elsewhere in the pipeline.
    """
    df = cohorts if include_immature else cohorts[cohorts["is_mature"]]
    if df.empty:
        return pd.DataFrame(columns=["market", "week_start", "fh_net_billthrough_count"])

    week_start = df["signup_date"].dt.to_period("W-SUN").dt.start_time
    grouped = (
        df.assign(week_start=week_start)
        .groupby(["market", "week_start"], as_index=False)["net_billthroughs"]
        .sum()
    )
    return grouped.rename(columns={"net_billthroughs": "fh_net_billthrough_count"})


def immature_cohort_summary(cohorts: pd.DataFrame) -> pd.DataFrame:
    """The excluded (not-yet-mature) cohorts, for transparency - the
    counterpart to `net_billthrough_weekly_series`'s default exclusion, so a
    caller/UI can show "N cohorts totalling M signups are still maturing and
    excluded from this series" instead of that exclusion being invisible."""
    immature = cohorts[~cohorts["is_mature"]]
    return (
        immature[["market", "signup_date", "offer_id", "gross_signups", "matures_on"]]
        .sort_values(["market", "signup_date"])
        .reset_index(drop=True)
    )
