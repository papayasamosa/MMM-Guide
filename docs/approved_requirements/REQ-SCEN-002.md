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
level - see "Owner and status" below for the precise boundary. The manual
"Sequential weekly" tab on `pages/08_Scenario_Planner.py` (WP5 part 2 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR262`) is the first consumer;
constrained/unconstrained optimisation remain steady-state-only.

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
- `ancestry_mmm/core/sequential_scenario_evaluation.py` (implemented,
  WP5 - orchestrates phased/governed weekly plans through candidate/
  reference evaluation, monthly aggregation, horizons, terminal, posterior)
- `ancestry_mmm/application/scenario_service.py`
  (`SequentialManualScenarioInput`, `ScenarioService.
  evaluate_manual_sequential`, implemented, WP5)
- `ancestry_mmm/pages/08_Scenario_Planner.py` (implemented, WP5 part 2 -
  "Manual plan evaluation method" toggle on the "Edited plan and
  calculated result" tab only; constrained/unconstrained optimisation
  remain steady-state-only. The sequential plan window always starts the
  Monday immediately after the market's last historical week, continuing
  the exact same weekly cadence with no gap - never at the steady-state
  tab's user-chosen start month. Because that first sequential month is
  therefore necessarily partial, and `calendar_day_overlap_v1`/its
  explicit-override sibling can each only reconcile a month `calendar`
  fully covers (or, for the override, only when every month sharing a week
  is itself tracked - see "Owner and status" below), the page phases that
  first month directly with the same day-overlap formula, scoped to the
  covered days only, and phases every subsequent whole month through the
  unmodified governed function, summing the two per week - `phasing.py`
  itself is unchanged.)
- `ancestry_mmm/tests/test_phasing.py`,
  `ancestry_mmm/tests/test_future_context.py`,
  `ancestry_mmm/tests/test_weekly_plan_builder.py`,
  `ancestry_mmm/tests/test_terminal_response.py`,
  `ancestry_mmm/tests/test_sequential_scenario_evaluation.py`,
  `ancestry_mmm/tests/test_scenario_service_sequential.py`,
  `ancestry_mmm/tests/test_scenario_planner_apptest.py`

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

- Sequential scenario evaluation service (WP5,
  `core.sequential_scenario_evaluation`,
  `application.scenario_service.ScenarioService.evaluate_manual_sequential`):
  orchestrates already-governed candidate/reference `WeeklyPlan`s through
  historical-state reconstruction, one shared `SequentialEvaluationContext`,
  weekly incrementality, monthly aggregation, short/long horizon response,
  terminal incremental carryover (structurally separate), and optional
  fully draw-consistent posterior evaluation - reusing the same governance/
  economics machinery (`resolve_planning_governance`, `resolve_scenario_plan`)
  the steady-state path uses, stamping `SEQUENTIAL_WEEKLY_PLANNING_
  EVALUATION_SEMANTICS` rather than the steady-state constant.
  `core.optimization.validate_scenario_dependencies`'s
  `planning_semantics_fingerprint` staleness check was made engine-aware in
  the same package (previously hard-coded to only recognise the
  steady-state constant as "current" - a sequential scenario would have
  appeared permanently stale).

- Streamlit UI (WP5 part 2, `pages/08_Scenario_Planner.py`): a "Manual
  plan evaluation method" radio (steady-state monthly / sequential
  weekly), applying only to the "Edited plan and calculated result" tab.
  Reuses the existing monthly spend-plan grid and governance inputs
  unchanged - re-seats the analyst's ordered monthly values onto the real
  calendar months starting at the historical-continuation Monday, resolves
  the reference/counterfactual plan via the existing
  `core.scenario_governance.resolve_counterfactual` at monthly grain before
  re-seating (identically to the candidate), phases both through
  `core.planning.phasing` (partial-first-month handling above), builds a
  future context (official mode unless the fit has exogenous controls, in
  which case exploratory `hold_last_observed` with an explicit
  not-decision-ready warning), builds governed `WeeklyPlan`s, and routes
  through `ScenarioService.evaluate_manual_sequential`. Renders weekly and
  monthly incremental tables, short/long response-horizon metrics, and
  provenance fingerprints. WP5 part 3 (2026-08-18) additionally builds a
  `terminal_future_context` (reusing the assumptions already acknowledged
  for the plan window) and renders `result.terminal` separately from the
  plan-window tables, plus an opt-in checkbox that renders a plan-window-
  total credible-interval summary from `result.posterior_weekly_
  incremental` when a fitted trace is available.

**Not yet implemented:** sequential-weekly constrained/unconstrained
optimisation (both optimiser tabs remain steady-state-only), and saving/
exporting a sequential scenario (only steady-state monthly scenarios can
be saved in this release) - explicitly disclosed in the UI, not silently
absent.
