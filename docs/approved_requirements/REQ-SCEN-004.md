# REQ-SCEN-004: Sequential-Weekly Optimisation

## Approval and traceability

Reconciled into repository authority by Work Package 6 of `Media-Mix-Lab:
Coding LLM Next Steps After PR #267 and Latest PRD Validation Updates`
(2026-08-18), per this repository's standard authority hierarchy. Depends
on `REQ-SCEN-001` (sequential candidate/reference evaluation contract),
`REQ-SCEN-002` (monthly-to-weekly phasing), and `REQ-SCEN-003` (response-
horizon/terminal reporting) - all three already implemented for the
*manual* sequential-weekly evaluation path (`pages/08_Scenario_
Planner.py`'s "Sequential weekly" method on the manual tab, Work
Packages 5 parts 2-4). Both constrained and unconstrained-benchmark
optimiser tabs, and `core.optimization`'s objective, remain steady-
state-monthly-only - `REQ-SCEN-001`'s own "Not yet covered" section and
`REQ-SCEN-002`'s "Not yet implemented" note both name this as a
separate, not-yet-approved follow-up.

This record reconciles that already-flagged gap into a formal
requirement record - it does **not** approve an implementation. Two
genuinely unresolved questions block any implementation and are recorded
below as decision-required, per this program's own governing
instruction: do not implement directly from an unapproved gap, and if a
genuine statistical/causal/business/governance decision is required,
create a decision package and stop that workstream rather than guessing.
See `docs/wp6_sequential_optimisation_decision_package.md`.

## Capability status

Not yet implemented. Blocked pending the decision package referenced
above - this is a target-state contract only, reconciling PRD-level
authority (the same Part 3/6/7/9/10 sequential-planning sections
`REQ-SCEN-001`/`002`/`003` already cite) that a sequential-weekly
optimisation capability must eventually exist, without approving any
specific objective definition or evaluation strategy for it.

## Requirement (target state - not yet approved for implementation)

### 1. A sequential-weekly optimisation engine choice must exist

Mirroring the manual-evaluation split already implemented (`REQ-SCEN-
001` item 7: `planning_semantics` always stamped explicitly, never
silently switched), both the constrained and unconstrained-benchmark
optimiser tabs must eventually offer a sequential-weekly engine choice
alongside the existing steady-state-monthly approximation - never a
silent default, never a result presented as timing-aware unless it was
actually produced by the sequential contract.

### 2. Terminal carryover stays reporting-only unless separately approved

`REQ-SCEN-003`'s own text already governs this and is not reopened here:
terminal carryover "must be reported separately from the formal plan-
window incremental outcome - never automatically included in the
optimisation objective in the first sequential-planning release. A
later, separately approved requirement may authorise terminal value in
the objective." Any sequential-weekly optimisation implementation must
continue to honour this - it is inherited, not re-decided by this
record.

### 3. Posterior-aware search is explicitly out of scope until decided

`REQ-SCEN-003`'s "Posterior aggregation" section requires that when
sequential uncertainty is reported, it is calculated draw by draw
without breaking draw alignment. Whether an optimisation *search loop*
itself needs to be posterior-aware (as opposed to a single, deterministic
posterior-mean-parameter evaluation per candidate plan, with uncertainty
reported only for the final chosen plan) is itself a decision-required
question - see the decision package.

## Explicitly excluded (decision-required, not approved by this record)

- **The optimisation objective definition.** The sequential evaluation
  contract natively produces at least three distinct incremental-outcome
  quantities per candidate plan (short-horizon, long-horizon, and - kept
  reporting-only per item 2 above - terminal carryover). Which becomes
  the scalar an optimiser search maximises/minimises, and whether that
  differs from what is displayed to an analyst as "the result," is not
  decided by this record.
- **The evaluation/search tractability strategy.** `core.optimization.
  optimize_scenario`'s existing search (`scipy.optimize.minimize`,
  method `SLSQP`, gradient-free-supplied so SciPy finite-differences the
  objective) calls its analytic, per-month, state-independent steady-
  state objective potentially hundreds to low thousands of times per
  optimisation run. `core.sequential_scenario_evaluation.evaluate_
  manual_scenario_sequential` performs a full week-by-week state-
  transition (adstock carry-in) simulation per call - each week depends
  on the previous week's state, so no partial/incremental re-evaluation
  is possible - and optionally loops that full simulation once per
  requested posterior draw. Calling it directly inside SLSQP's finite-
  difference inner loop is a materially more expensive computational
  problem than today's analytic objective, not a mechanical swap of one
  function reference for another, and may not be tractable at
  interactive UI latency. Candidate strategies (direct replay, a
  reduced-evaluation-budget search algorithm, a two-stage steady-state-
  search-then-sequential-report approach, or a validated fast surrogate
  approximation used only inside the search loop with the exact kernel
  reserved for final reporting) are laid out, not chosen, in the
  decision package.
- Whether an approved sequential-weekly optimisation strategy also
  requires its own new response-horizon/terminal reporting contract
  changes beyond what `REQ-SCEN-003` already specifies for the manual
  path.

## Affected modules (target - not yet touched)

- `ancestry_mmm/core/optimization.py` (`optimize_scenario`, `_objective_
  factory`, `_steady_state_response_fn` - not yet touched)
- `ancestry_mmm/core/sequential_scenario_evaluation.py` (read-only
  reference for this record - the existing manual-evaluation contract
  this future optimisation capability would need to reuse or adapt, not
  itself modified by this record)
- `ancestry_mmm/pages/08_Scenario_Planner.py` (constrained/unconstrained-
  benchmark optimiser tabs - not yet touched)
- `docs/wp6_sequential_optimisation_decision_package.md` (new)
- `docs/approved_requirements/REQ-SCEN-004.md` (this record)
- `docs/approved_requirements/index.json` (new entry)

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None. No code changes accompany this record.

## Unresolved decisions

- The optimisation objective definition (which incremental-outcome
  quantity, or combination, becomes the optimised scalar).
- The evaluation/search tractability strategy for running (or
  approximating) the sequential kernel inside a numerical optimisation
  search loop.
- Whether optimisation search itself must be posterior-aware, or only
  the final chosen plan's reported uncertainty.

Both first two are recorded in
`docs/wp6_sequential_optimisation_decision_package.md` with candidate
approaches and their tradeoffs - none selected by this coding pass.

## Owner

Modelling

## Approval date

2026-08-18


## Addendum, 2026-08-30 (Phase E): tractability/objective/posterior-awareness resolved (Decision 16)

This record's own "Explicitly excluded" section tracked "the
optimisation objective definition" and "the evaluation/search
tractability strategy" via `docs/wp6_sequential_optimisation_decision_
package.md`. The user's 2026-08-29 brief, confirmed in-session
2026-08-30, explicitly delegates this to benchmarking. This addendum
records the resulting resolution: full decision record, including the
actual benchmark methodology and measured figures, in
`docs/sequential_optimisation_tractability_decision_record.md`;
implementation in the new
`ancestry_mmm/core/sequential_optimisation_tractability.py`.

**Resolved:** the tractability strategy (T1, direct replay of the exact
sequential kernel at point-estimate parameters, refined to call the raw
numerical kernel rather than the full governance-wrapper function
inside the tight search loop) - selected on real, in-session benchmark
evidence (0.3-0.5 ms per call at realistic plan sizes, extrapolating to
under 8 seconds for a demanding 100-iteration SLSQP run at 10 channels
across a 52-week plan window, and a gradient-smoothness check finding
no numerical noise) that directly contradicts this record's own
previously-hypothesised tractability concern; the objective definition
(O1, plan-window total - the direct sequential analogue of steady-
state's existing objective, requiring no new business input); and that
the search itself is not posterior-aware (posterior uncertainty for the
final chosen plan is computed once, as a separate opt-in step,
mirroring the manual tab's own already-established pattern).

**Still not resolved:** the actual rewiring of `core.optimization.py`'s
SLSQP call sites to use the sequential kernel in place of the existing
steady-state objective - a separate, substantial engineering
integration (bounds/constraints translation, `REQ-OPT-001`'s objective-
kind vocabulary wiring) requiring its own end-to-end validation, not
attempted here. `core.optimization.py` remains completely unchanged;
sequential-weekly optimisation stays out of the production contract
exactly as this record's own text already states, pending that
integration.

## Addendum, 2026-09-01: production route wired

The delegated integration is now wired through the Scenario Planner and
`ScenarioService`: `sequential_weekly` is the application default, and the
manual evaluation and optimiser use the same governed weekly carry-in replay.
The steady-state monthly calculation remains available only when explicitly
selected as a diagnostic/legacy comparison. It is not the default production
recommendation path. Candidate A Search is blocked in steady-state mode so an
incomplete final-outcome replay cannot be presented as an optimisation result.
