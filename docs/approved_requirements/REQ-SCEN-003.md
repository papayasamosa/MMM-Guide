# REQ-SCEN-003: Response horizon and terminal reporting contract

## Approval and traceability

Approved for implementation by the task-specific implementation brief
`Media-Mix-Lab: Coding LLM Next Steps Post WP5` (2026-08-16), per this
repository's standard authority hierarchy. Depends on `REQ-STATE-001` (the
kernel already computes ending state and terminal carryover as structurally
separate results - `simulate_terminal_carryover`/
`simulate_terminal_carryover_market_specific`) and `REQ-SCEN-001`
(candidate/reference evaluation this reporting wraps). The kernel-level
mechanics this record reports on already exist; the horizon-configuration
and reporting/persistence contract below is new and not yet implemented at
the application layer.

## Starting and ending state reporting

An application surfacing sequential results must report starting carryover
(reconstructed from historical activity through the fit cut-off,
`REQ-STATE-001`) and ending carryover (remaining after the formal plan
window) as an analyst-readable summary - not raw state arrays as the
primary UI. Raw state may remain available in expandable technical detail.

## Short/long/terminal horizon configuration

A typed horizon configuration must be persisted with every sequential
scenario, containing:

- short horizon (initial standard preset: weeks 0-4)
- long horizon (initial standard preset: weeks 5-52)
- plan horizon (the formal plan window)
- terminal continuation horizon (initial standard preset: 52 weeks,
  configurable)

The core contract must accept explicit horizon values; UI presets are a
convenience default, never a hidden constant.

## Terminal carryover is reported separately

Terminal carryover must be reported separately from the formal plan-window
incremental outcome - never automatically included in the optimisation
objective in the first sequential-planning release. A later, separately
approved requirement may authorise terminal value in the objective; until
then, an optimiser or scenario summary that folds terminal carryover into
its headline incremental-outcome number violates this record.

## Posterior aggregation

Consistent with `REQ-SCEN-001` item 5: sequential uncertainty must be
calculated draw by draw. Do not simulate only posterior means and call the
result posterior uncertainty; do not add separately summarised
direct/halo/component medians; do not break draw alignment. Aggregate
draws only after the complete path (plan-window and, where reported,
terminal) has been evaluated per draw.

## Method labelling

Every result produced under this contract must record and display which
evaluation method (sequential weekly vs. steady-state monthly
approximation) produced it, consistent with `REQ-SCEN-001` item 7. A
result must never be presented as timing-aware (starting carryover,
month-by-month timing, short/long response, terminal carryover) unless it
was produced by the sequential contract.

## Affected modules

- `ancestry_mmm/core/sequential_simulation.py`
  (`simulate_terminal_carryover`/`simulate_terminal_carryover_market_specific`
  implemented at kernel level)
- `ancestry_mmm/core/planning/phasing.py` (`HorizonConfiguration` -
  implemented, WP1: short/long/plan/terminal horizons, explicit values
  required, no hidden UI-preset constants)
- `ancestry_mmm/core/planning/terminal_response.py` (implemented, WP4 of
  `...Post PR262`: the business-facing terminal candidate/reference
  evaluator - real shared future non-decision context, zero future
  decision media only, `TerminalIncrementalResult` reported as a
  structurally separate type from any plan-window result)
- `ancestry_mmm/core/sequential_scenario_evaluation.py` (implemented,
  WP5: `SequentialScenarioEvaluationResult.short_horizon_incremental`/
  `.long_horizon_incremental` computed from `HorizonConfiguration` over
  already-evaluated weekly incremental output; `.terminal` holds the
  `TerminalIncrementalResult` when a terminal future context is supplied,
  always structurally separate from the plan-window fields)
- `ancestry_mmm/application/scenario_service.py`
  (`ScenarioService.evaluate_manual_sequential`, implemented, WP5)
- `ancestry_mmm/tests/test_phasing.py` (implemented, WP1),
  `ancestry_mmm/tests/test_terminal_response.py` (implemented, WP4),
  `ancestry_mmm/tests/test_sequential_scenario_evaluation.py` (implemented,
  WP5)
- `ancestry_mmm/pages/08_Scenario_Planner.py` (implemented, WP5 part 2:
  the manual "Sequential weekly" tab renders short/long horizon metrics
  and labels the calculation method - but not terminal carryover or
  posterior uncertainty, both explicitly disclosed as not yet available in
  this UI rather than silently omitted)
- Not yet implemented: terminal carryover / posterior uncertainty in the
  UI (available via the core/service APIs directly), scenario persistence/
  staleness for a saved sequential scenario (`core.scenario_governance`,
  `core.persistence` - horizon configuration and terminal-carryover result
  must become part of the persisted, fingerprinted scenario record once
  that wiring exists)

## Owner and status

**Owner:** Data Science / Platform engineering.

**Status:** Kernel-level terminal-carryover mechanics (`REQ-STATE-001`),
the typed `HorizonConfiguration` contract (WP1,
`core.planning.phasing.HorizonConfiguration`), and the business-facing
terminal candidate/reference evaluator (WP4,
`core.planning.terminal_response`) are implemented and tested. Short/long
horizon reporting and method labelling are implemented in the Streamlit UI
(WP5 part 2). Persistence with a saved scenario, and terminal carryover/
posterior uncertainty in the UI, are approved but not yet implemented.
