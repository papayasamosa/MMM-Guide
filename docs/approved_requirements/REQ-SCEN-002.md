# REQ-SCEN-002: Monthly-to-weekly phasing and future-context contract

## Approval and traceability

Approved for implementation by the task-specific implementation brief
`Media-Mix-Lab: Coding LLM Next Steps Post WP5` (2026-08-16), per this
repository's standard authority hierarchy ("1. the task-specific
implementation brief"). Depends on `REQ-STATE-001` (the `WeeklyPlan`
contract this phasing produces inputs for) and `REQ-SCEN-001` (the
evaluation contract those weekly plans feed). The core phasing contract is
implemented and tested (WP1 of that brief, `core.planning.phasing`, merged
as PR #262) - see "Owner and status" below for the precise implemented
versus not-yet-implemented boundary.

This record approves the contract. The phasing module (WP1) plus the
future-context builder, governed `WeeklyPlan` construction boundary, and
terminal candidate/reference evaluator (Work Package 4 of `Media-Mix-Lab:
Coding LLM Next Steps Post PR262`) together implement it at the core-module
level - see "Owner and status" below for the precise boundary. No
`application/` service or Streamlit page consumes any of this yet; that
remains a separate, dependent work package.

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
- `ancestry_mmm/core/planning/future_context.py` (implemented, WP4 -
  trend/Fourier continuation, promotion/control future-path resolution,
  official/exploratory mode gating)
- `ancestry_mmm/core/planning/weekly_plan_builder.py` (implemented, WP4 -
  governed `WeeklyPlan` construction boundary above phased allocations +
  future context)
- `ancestry_mmm/core/planning/terminal_response.py` (implemented, WP4 -
  terminal candidate/reference evaluator; see `REQ-SCEN-003` for the
  response-horizon/terminal-reporting contract this feeds)
- `ancestry_mmm/core/frequency_alignment.py` (`CanonicalCalendar` reused
  directly - no competing calendar representation created)
- `ancestry_mmm/core/media_costs.py` (`CostMappingRegistry.resolve(...,
  as_of=...)` reused for weekly/period-specific cost mapping)
- `ancestry_mmm/tests/test_phasing.py`,
  `ancestry_mmm/tests/test_future_context.py`,
  `ancestry_mmm/tests/test_weekly_plan_builder.py`,
  `ancestry_mmm/tests/test_terminal_response.py`
- Not yet touched: any `application/` service or Streamlit page - a
  separate, dependent work package.

## Owner and status

**Owner:** Data Science / Platform engineering.

**Status:** Implemented and tested at the core-module level:

- Core phasing contract (WP1, `core.planning.phasing`):
  `calendar_day_overlap_v1` with per-month conservation to strict
  numerical tolerance and auditable boundary-week attribution, an
  explicit weekly-schedule override with its own reconciliation check
  (weeks are attributed to *tracked* months only, in proportion to each
  tracked month's share of the week's day-overlap - not diluted by an
  untracked adjacent month), separate monetary (phase-then-convert,
  per-week cost-mapping resolution) and model-input (no cost conversion)
  paths, and a typed `HorizonConfiguration` contract (`REQ-SCEN-003`'s
  dependency). A week with exactly zero phased spend requires no cost
  mapping (unambiguously zero regardless of cost) - this matters because
  `CanonicalCalendar` is typically a project's full, multi-year window,
  not just the months being planned.
- Future-context builder (WP4, `core.planning.future_context`): trend
  continued via the exact per-market row-index-normalized formula
  `data.preprocessor.prepare_fh_modeling_frame` uses at fit time (mirrored,
  not imported - `core` must not depend on `data`, see that module's own
  import of `core.schema`/`core.outcomes`; kept numerically identical by
  test), Fourier/seasonality continued via the same calendar-anchored
  (day-of-year) formula `data.preprocessor.create_fourier_features_from_calendar`
  uses, official-mode fail-closed missing-promo/control checks (no
  relaxation for promotions/events in any mode), and exploratory-mode
  labelled/fingerprinted/decision-excluded `hold_last_observed` for an
  explicitly eligible, explicitly opted-in control.
- Governed `WeeklyPlan` construction boundary (WP4,
  `core.planning.weekly_plan_builder`): validates exact canonical week
  order, exact expected channel set (no unknown channel silently ignored),
  finite non-negative allocation values even on direct construction, and
  Fourier/outcome/control shape and identity against the fitted model
  before constructing `core.sequential_simulation.WeeklyPlan`; stores
  construction provenance/fingerprint. Does not duplicate
  `application.scenario_service.ScenarioPlan` (the steady-state method's
  own input type).
- Terminal candidate/reference evaluator (WP4,
  `core.planning.terminal_response`): extends candidate and reference over
  the SAME future calendar sharing ONE real future non-decision context
  (trend/seasonality/controls/promotions - never `core.sequential_
  simulation.zero_media_extension_plan`'s all-zero low-level fixture),
  zero future decision media for the initial residual-carryover policy,
  and reports `candidate - reference` as a structurally separate
  `TerminalIncrementalResult` - never folded into a plan-window result or
  an optimisation objective.

**Not yet implemented:** any `application/` service (`application/
scenario_service.py`) or Streamlit page (`pages/08_Scenario_Planner.py`)
consuming any of the above - a separate, dependent work package.
