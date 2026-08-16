# REQ-SCEN-002: Monthly-to-weekly phasing and future-context contract

## Approval and traceability

Approved for implementation by the task-specific implementation brief
`Media-Mix-Lab: Coding LLM Next Steps Post WP5` (2026-08-16), per this
repository's standard authority hierarchy ("1. the task-specific
implementation brief"). Depends on `REQ-STATE-001` (the `WeeklyPlan`
contract this phasing produces inputs for) and `REQ-SCEN-001` (the
evaluation contract those weekly plans feed). Not yet implemented -
`REPO_REVIEW_AND_NEXT_STEPS.md` records this as "WP6" ("`WeeklyPlan`... it
never decides how a coarser plan spreads across weeks, deferred to WP6").

This record approves the contract; it does not itself implement
`ancestry_mmm/core/sequential_simulation.py`'s `WeeklyPlan` producer. That
implementation is a separate, dependent work package and must cite this
record.

## Planning interface and calculation grain

The business-facing plan is monthly. The calculation engine is weekly, at
the canonical model week. Steady-state planning remains available only as a
clearly labelled exploratory/strategic approximation - never presented as
timing-aware. Sequential evaluation (`REQ-SCEN-001`) is required for
month-by-month timing, starting adstock, carryover, terminal response,
short/long response horizons, and sequential optimisation.

## Approved phasing method: `calendar_day_overlap_v1`

For a monthly total representing a flow quantity (monthly monetary media
spend, or a monthly model-input quantity) with no explicit weekly flighting
schedule supplied:

1. Identify every canonical model week overlapping the month.
2. Calculate the calendar-day count of each month/week intersection.
3. Allocate the monthly total proportionally to those intersection-day
   counts.
4. Weekly allocations must sum back exactly to the original monthly total
   within strict numerical tolerance, for every market/activity/month.

A week spanning two months may contain allocated quantities from both
months - this is expected and must remain auditable back to each source
month. Never shift a boundary week wholly into one month for display
convenience.

**Stored provenance:** method ID, method version, parameters, canonical
calendar identity, source monthly-plan fingerprint, generated weekly-plan
fingerprint.

## Explicit weekly schedule override

If an analyst supplies an explicit weekly flighting schedule, use it
instead of `calendar_day_overlap_v1`. Where the plan is defined as
monthly-total-constrained, the explicit weekly values must reconcile to the
monthly total; if they do not, block rather than silently normalising.

## Official versus exploratory use

Official planning: the phasing method must be explicitly recorded and
confirmed in the saved scenario - no hidden method selection. Exploratory
planning: the UI may preselect `calendar_day_overlap_v1`, but it must
remain visible and editable.

## Spend-to-delivery order

For a monetary monthly media plan: phase monthly spend into weekly spend
first, then apply the governed weekly/period-specific cost mapping to
derive weekly model-input quantity/delivery, then send that quantity into
the sequential simulator. Do not convert monthly spend using one average
cost and then phase the resulting delivery if weekly cost assumptions
differ. For a monthly plan already expressed in model-input units, phase
the model-input quantity directly. Monetary and physical-unit values must
never share one generic value column.

## Promotions, events and controls (excluded from this phasing method)

`calendar_day_overlap_v1` must not be used to distribute promotions, event
flags, exogenous controls, price, caps, or latent baseline state - these
have separate future-state semantics. Trend and Fourier/seasonality terms
must be generated deterministically from the future canonical calendar
using the same model definition the fitted model used. Promotions/events
require explicit planned periods or an approved event schedule.

For required future exogenous controls in official mode: require an
explicit future path for every required period; fail closed if absent. In
exploratory mode only, a user may explicitly choose a labelled assumption
(e.g. hold-last-observed); that assumption must be visible, stored,
fingerprinted, and excluded from decision-ready status. Never silently
hold-last-observed a future control. Do not introduce Chronos-2 or any
other external forecaster in this contract.

## Candidate/reference semantics

Candidate and reference plans must be phased with the same policy, the same
calendar, the same non-decision future assumptions, the same model/
posterior, and the same cost mapping, except where cost itself is an
explicitly varied assumption - consistent with `REQ-SCEN-001`'s
candidate/reference contract.

## Affected modules (future implementation)

- A new phasing module (e.g. `ancestry_mmm/core/planning/phasing.py`)
- `ancestry_mmm/core/sequential_simulation.py` (`WeeklyPlan` construction)
- `ancestry_mmm/core/frequency_alignment.py` /
  `ancestry_mmm/core/frequency_conversion.py` (reuse the canonical
  calendar; do not create a competing calendar representation)
- `ancestry_mmm/core/media_costs.py`, `ancestry_mmm/core/media_units.py`
  (weekly/period-specific cost mapping reuse)

## Owner and status

**Owner:** Data Science / Platform engineering.

**Status:** Approved for implementation; not yet implemented. Required
tests before this record's status may change to reflect implementation:
exact monthly conservation, explicit-override reconciliation and mismatch
blocking, monetary-versus-model-input path separation, missing-required-
control blocking in official mode, and fingerprint/serialisation round
trip - see the implementation brief's Work Package 1 test list.
