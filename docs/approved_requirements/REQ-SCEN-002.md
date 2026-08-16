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

## Affected modules

- `ancestry_mmm/core/planning/phasing.py` (implemented, WP1)
- `ancestry_mmm/core/frequency_alignment.py` (`CanonicalCalendar` reused
  directly - no competing calendar representation created)
- `ancestry_mmm/core/media_costs.py` (`CostMappingRegistry.resolve(...,
  as_of=...)` reused for weekly/period-specific cost mapping)
- `ancestry_mmm/tests/test_phasing.py` (implemented, WP1)
- Not yet touched: `ancestry_mmm/core/sequential_simulation.py`
  (`WeeklyPlan` construction from a `WeeklyAllocationResult` is an
  application-layer wiring step, not yet implemented), the future-context
  builder (trend/Fourier/promotions/controls generation - explicitly
  deferred, see "Not yet implemented" below), any `application/` service
  or Streamlit page.

## Owner and status

**Owner:** Data Science / Platform engineering.

**Status:** Core phasing contract implemented and tested (WP1,
`core.planning.phasing`): `calendar_day_overlap_v1` with per-month
conservation to strict numerical tolerance and auditable boundary-week
attribution, an explicit weekly-schedule override with its own
reconciliation check (weeks are attributed to *tracked* months only, in
proportion to each tracked month's share of the week's day-overlap - not
diluted by an untracked adjacent month), separate monetary
(phase-then-convert, per-week cost-mapping resolution) and model-input
(no cost conversion) paths, and a typed `HorizonConfiguration` contract
(`REQ-SCEN-003`'s dependency). A week with exactly zero phased spend
requires no cost mapping (unambiguously zero regardless of cost) - this
matters because `CanonicalCalendar` is typically a project's full,
multi-year window, not just the months being planned.

**Not yet implemented:** the future-context builder (trend/Fourier from
the canonical future calendar, explicit promotions/events, official-mode
fail-closed missing-control checks, exploratory-mode labelled
hold-last-observed assumption) - deliberately deferred as a separate,
dependent work package, not bundled into this phasing-only record's
implementation; wiring a phased `WeeklyAllocationResult` into
`core.sequential_simulation.WeeklyPlan`; any `application/` service or
Streamlit page.
