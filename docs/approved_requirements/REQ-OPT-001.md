# REQ-OPT-001: Optimiser Objective-Kind and Constraint-Kind Vocabulary

## PRD source

Business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (decision date 2026-08-29), Decision 16
("Optimiser must support several goals and detailed monthly
constraints") and part of Decision 18 ("Real-world capacity constraints
belong in the optimiser").

## Approval and traceability

Approved for implementation by the business-decision brief cited above.
Target-state architecture contract only — no objective kind, constraint
kind, or numeric threshold is implemented by this record. Depends on
`REQ-PLAN-001` (a planning objective must explicitly identify its target
outcome — this record extends that with the *kind* of objective
function, not the target outcome itself) and `REQ-SCEN-004` (the
sequential-weekly evaluation/search-tractability question this record
does not duplicate or re-decide). Reconciles a genuine gap:
`docs/specification_authority.md` records no approved requirement for
either an optimiser objective-kind vocabulary or a constraint-kind
vocabulary beyond `core.optimization.SpendConstraint`'s existing five
kinds.

## Capability status

Partial foundations already exist, confirmed by repository audit:
`core.optimization.resolve_planning_objective()` already supports a
pluggable objective (metric-key objectives plus an expected-value/
value-weighted kind), and `SpendConstraint` already supports five
month×channel-granular kinds (`locked_cell`, `channel_total`,
`month_total`, `bounded_movement`, `min_spend_floor`). No REQ record
approves the broader objective-kind menu (revenue/profit/ROI/CPA) or the
remaining constraint kinds (percentage change, absolute change, zero/
unavailable, required minimum activity) Decision 16 names. No REQ record
approves a governed, cross-cutting capacity-constraint representation
(TV inventory, impression caps, sponsorship inventory, availability
windows) as Decision 18 requires.

## Requirement (target state — not yet approved for implementation)

### 1. Closed objective-kind vocabulary

An optimiser objective must declare exactly one kind from a closed,
versioned vocabulary:

```text
maximise_outcome        # e.g. maximise GSAs/sign-ups/kits — existing metric-key objective
maximise_revenue
maximise_profit
maximise_roi
minimise_cpa
```

Each kind beyond `maximise_outcome` requires its own valid economic-input
precondition before it may be offered or selected, per Decision 16's own
"do not offer an objective if the required economic inputs are missing"
instruction: `maximise_revenue`/`maximise_profit` require a valid,
governed value/profit definition for every included outcome
(`REQ-ECON-001`'s value-join principle); `maximise_roi`/`minimise_cpa`
require valid cost and return definitions for every included channel and
outcome. An outcome or channel lacking the required economic input must
be excluded from that objective kind or block the objective entirely,
fail-closed — never silently substituted with a proxy value. SEO (a
non-paid activity, `REQ-SEO-001`) must never be included in a
cost-based objective (`maximise_roi`, `minimise_cpa`) as if it had paid
media spend, per Decision 7's existing prohibition.

### 2. Extended closed constraint-kind vocabulary

A spend/activity constraint for a given channel×month cell must declare
exactly one kind from a closed, versioned vocabulary extending
`core.optimization.SpendConstraint`'s existing five kinds
(`locked_cell`, `channel_total`, `month_total`, `bounded_movement`,
`min_spend_floor`) with the remainder Decision 16 names:

```text
no_constraint
fixed_absolute_spend        # existing: locked_cell
minimum_spend                # existing: min_spend_floor
maximum_spend
spend_range                  # min and max together
percentage_change_from_reference   # +/- X% from a reference plan
absolute_change_from_reference     # +/- X currency units from a reference plan
zero_spend                   # channel switched off for this cell
required_minimum_activity    # distinct from a spend floor: a non-monetary activity minimum
unavailable                  # no available demand/activity in this month (distinct from zero_spend: zero_spend is a choice, unavailable is a fact)
```

This record does not decide whether each new kind is implemented as a
new `SpendConstraint` variant or a parallel structure — that is Phase E
implementation work. `unavailable` and `zero_spend` must remain
distinguishable states (a channel a planner chooses to switch off is not
the same fact as a channel with no addressable demand that month), per
Decision 16's own example list and consistent with `REQ-CAP-001`'s
existing cap-hit-state distinctions.

### 3. Same sequential kernel as Scenario Planning — cross-reference only

Per Decision 16's explicit instruction, an approved sequential-weekly
optimisation must use the same simulation kernel as Scenario Planning
(`core.sequential_simulation`/`core.sequential_scenario_evaluation`),
converting monthly constraints correctly into the weekly simulation
structure, never a contradictory shortcut. This record does not resolve
*how* — the evaluation/search-tractability strategy is `REQ-SCEN-004`'s
own explicitly-excluded, still-open item (`docs/wp6_sequential_
optimisation_decision_package.md`); this record only confirms the
objective/constraint vocabulary above must be expressible against
whichever tractability strategy that separate decision selects, and does
not duplicate or re-decide it.

### 4. Capacity constraints are a distinct constraint category (Decision 18)

A capacity constraint (TV inventory, maximum available impressions,
sponsorship inventory, or another delivery/exposure limit expressed in a
non-money unit) is governed by `REQ-CAP-001`, not invented as a sixth
`SpendConstraint`-family kind by this record. Where a capacity limit is
expressed in a non-money unit, it must not be treated as a spend cap
unless a valid, governed mapping exists (`REQ-CAP-001`'s own principle,
reaffirmed here). This record's constraint-kind vocabulary (Requirement
2) governs money/percentage-denominated constraints only; `REQ-CAP-001`
governs delivery/exposure/availability constraints; both must be usable
together by the same optimisation run, and the result must disclose
which constraints of either kind were binding.

### 5. Infeasibility must be reported, never silently relaxed

If the optimiser cannot satisfy every declared constraint simultaneously,
it must return a clear infeasibility result identifying which
constraints could not be jointly satisfied, never silently drop, widen,
or ignore one to force a solution.

## Explicitly excluded (decision-required, not approved by this record)

- The exact evaluation/search-tractability strategy for running (or
  approximating) the sequential kernel inside a numerical optimisation
  search loop — `REQ-SCEN-004`'s own unresolved item, not duplicated
  here.
- Which specific incremental-outcome quantity (short-horizon,
  long-horizon, or a weighted combination) each objective kind actually
  maximises/minimises when a sequential evaluation produces more than
  one candidate quantity — `REQ-SCEN-004`'s own unresolved item.
- The exact schema representation of the extended constraint-kind
  vocabulary (new `SpendConstraint` variant fields vs. a parallel
  structure) — Phase E implementation work.
- Any numeric default (a default percentage-change bound, a default
  minimum-activity floor, or any other threshold) — none is approved or
  invented by this record.
- `REQ-CAP-001`'s own still-open cap-hit-vocabulary and module-sharing
  generalisation questions (`docs/wp11_capacity_cap_semantics_decision_
  package.md`) — this record only confirms capacity constraints are a
  distinct category from the money/percentage constraints it governs.
- Whether posterior-aware search is required for the optimisation loop
  itself, versus only the final chosen plan's reported uncertainty —
  `REQ-SCEN-004`'s own unresolved item.

A new decision package should record the evidence and tradeoffs for the
still-open items above before Phase E implementation begins, per the
research agent's own explicit flag that this area needs its own
decision-support document, mirroring `docs/wp6_sequential_optimisation_
decision_package.md`'s existing pattern.

## Affected modules (target — not yet touched)

- `ancestry_mmm/core/optimization.py` (`resolve_planning_objective`,
  `SpendConstraint`, `PlanningObjective` — not yet touched)
- `ancestry_mmm/pages/08_Scenario_Planner.py` (constrained/unconstrained-
  benchmark optimiser tabs — not yet touched)
- A future Search/optimiser decision package (not created by this
  record)
- `docs/approved_requirements/REQ-OPT-001.md` (this record)
- `docs/approved_requirements/index.json` (new entry)

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_req_opt_001_optimizer_vocabulary.py::test_objective_kind_vocabulary_is_closed_and_named`
- `ancestry_mmm/tests/test_req_opt_001_optimizer_vocabulary.py::test_constraint_kind_vocabulary_extends_existing_five_kinds`
- `ancestry_mmm/tests/test_req_opt_001_optimizer_vocabulary.py::test_seo_excluded_from_cost_based_objectives`
- `ancestry_mmm/tests/test_req_opt_001_optimizer_vocabulary.py::test_req_opt_001_indexed`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, to be tracked by a future
decision package before Phase E implementation.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-30

## Addendum, 2026-08-31: objective-kind precondition gating and constraint-kind vocabulary implemented

The user's 2026-08-29 "Post-UI/UX Implementation Instructions" brief,
confirmed in-session, explicitly delegates the Phase E implementation
questions this record's own text leaves open ("Phase E implementation
work, not a business decision") to research-based technical resolution.
This addendum records the resulting implementation: full decision record
in `docs/optimizer_objective_and_constraint_vocabulary_decision_record.md`;
implementation in the new `ancestry_mmm/core/optimization_objective_
vocabulary.py` and `ancestry_mmm/core/optimization_constraint_
vocabulary.py`.

**Resolved:** Requirement 1's precondition gating - `maximise_outcome`/
`maximise_revenue` validated by literally calling the real, unmodified
`core.optimization.resolve_planning_objective` (never reimplemented, so
the two can never silently diverge); `maximise_profit` unconditionally
blocked (a repository-wide audit confirmed no governed profit/margin/
COGS definition exists anywhere in this codebase); `maximise_roi`/
`minimise_cpa` gated on every considered channel being cost-bearing
(`core.activities.ActivityDefinition.is_cost_bearing`), never inferred
from a channel's name, with SEO/non-paid channels excluded per Decision
7. Requirement 2's schema question - a parallel `GovernedSpendConstraint`
structure (not a `SpendConstraint` variant), translating the four
kinds with a direct existing equivalent into real `SpendConstraint`
instances resolved by the unmodified `build_bounds_and_constraints`, and
applying the remaining kinds as a direct bounds-tightening pass on that
function's own output shape. Requirement 5 (infeasibility reporting) -
`resolve_governed_constraints` reports any cell where the resolved lower
bound exceeds the upper bound, never silently clamping or dropping a
constraint.

**Still not resolved / deliberately out of scope:** actually rewiring
`core.optimization.optimize_scenario`'s SLSQP call sites to use either
vocabulary in a production run (both `core.optimization.py` and
`pages/08_Scenario_Planner.py` remain completely unchanged); the
sequential-weekly kernel integration (`REQ-SCEN-004`'s own still-open
item); any numeric default for any constraint or objective precondition.

## Addendum, 2026-09-01: sequential weekly is the application production default

The delegated production-integration work has now connected the selected
`sequential_weekly` method to the analyst-facing Scenario Planner and
`application.scenario_service.ScenarioService.optimise()` route. The same
carry-in-aware weekly replay is used for the SLSQP objective and the returned
current/optimised predictions. The UI presents `steady_state_monthly` only as
an explicit diagnostic/legacy choice; Candidate A Search is fail-closed in
that route because the legacy path cannot include its final-outcome replay.

The lower-level `core.optimization.optimize_scenario()` function retains its
steady-state default for direct backwards-compatible callers. A caller that
uses it for production optimisation must pass `evaluation_method=`
`"sequential_weekly"` and a `SequentialOptimisationContext`; the application
boundary does this by default. `maximise_profit` remains unavailable because
no approved COGS, margin, or profit definition is present.
