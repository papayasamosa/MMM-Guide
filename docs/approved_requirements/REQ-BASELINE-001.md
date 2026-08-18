# REQ-BASELINE-001: Time-Varying Latent Baseline

## PRD source

Ancestry MMM PRD reconciliation of `AGENTS.md`'s future-variable-role #5
("latent baseline state — the time-varying intercept, projected from its
own fitted statistical process, never treated as an ordinary external
control") - a standing repository invariant, not itself sourced from a
specific PRD Part/section the way `REQ-SCEN-*`/`REQ-FORECAST-001` are.
Reconciled by Work Package 10 of `Media-Mix-Lab: Coding LLM Next Steps
After PR #267 and Latest PRD Validation Updates`.

## Approval and traceability

Reconciled into repository authority by Work Package 10 (2026-08-18),
per this repository's standard authority hierarchy. Depends on
`REQ-LATENT-001` (every fitted latent state entering a causal pathway,
"including... any future latent baseline state," must declare an
identifying strategy - `REQ-LATENT-001.md` Requirement 1) and `core.
planning.future_context` (`REQ-SCEN-002`), which already deterministically
continues the fitted trend and calendar Fourier seasonality forward for
planning - the upstream-recommended alternative to a time-varying-
intercept Gaussian Process for anything beyond in-sample decomposition
(see the decision package's upstream citation below).

Per this repository's "Required upstream-reference workflow", the
closest relevant upstream implementation was inspected before writing
this record: `pymc-labs/pymc-marketing`'s `MMM` class supports
`time_varying_intercept=True` (a Hilbert Space Gaussian Process modelling
the intercept's percentage deviation from a fitted baseline). Upstream's
own documentation states this component "reverts to \[its] prior mean and
exhibit\[s] rapidly growing uncertainty beyond the training data window"
and recommends trend/Fourier continuation instead for forecasting or
scenario planning beyond a short horizon - directly relevant to, and in
tension with, `AGENTS.md` role #5's "projected... for planning" language.

This record reconciles the already-flagged gap
(`docs/specification_authority.md`: "Time-varying baseline — No approved
requirement/decision yet") into a formal requirement record - it does
**not** approve an implementation. Three genuinely unresolved questions
block any implementation and are recorded below as decision-required,
per this program's own governing instruction: do not implement directly
from an unapproved gap, and if a genuine statistical/causal/business/
governance decision is required, create a decision package and stop that
workstream rather than guessing. See `docs/wp10_time_varying_baseline_
decision_package.md`.

## Capability status

Not yet implemented. Blocked pending the decision package referenced
above - this is a target-state contract only, reconciling `AGENTS.md`'s
own standing future-variable-role invariant that a time-varying latent
baseline must eventually exist as a distinct role, without approving any
specific statistical process, identification strategy, or forward-
projection mechanism for it.

## Requirement (target state - not yet approved for implementation)

### 1. A time-varying baseline is a distinct future-variable role

Per `AGENTS.md`'s six-role taxonomy, any approved latent baseline
capability must be assigned role #5 exactly - never conflated with role
2 (exogenous forecastable control, which an ordinary Chronos-2-eligible
series would use) or role 4 (endogenous funnel state, which a mediator
such as Candidate A's branded-search demand already uses under
`REQ-SEARCH-002`). `AGENTS.md`'s existing rule ("A latent baseline must
not be configured as a Chronos or any ordinary external forecast
target") is inherited unchanged, not re-decided here.

### 2. Identification is required before any official use

Mirroring `REQ-LATENT-001`'s existing Requirement 1 (already anticipating
"any future latent baseline state"), a fitted time-varying baseline must
declare an identifying strategy via `core.latent_state_identification`
and pass `is_eligible_for_official_use` before any official-mode plan,
scenario, or optimisation may read it - never an implicit assumption of
identifiability.

### 3. Forward projection, if any, must be explicit and disclosed

If an approved strategy permits any planning use at all (not decided by
this record - see Explicitly excluded below), the projection assumption
used for a future period must be as explicit and disclosed as `core.
planning.future_context`'s existing `FutureControlAssumption` contract
already requires for exogenous controls - never a silent default, and
never presented as decision-ready if the projection method itself carries
the kind of unbounded/reverting uncertainty upstream's own documentation
describes for a naive Gaussian-Process extrapolation.

## Explicitly excluded (decision-required, not approved by this record)

- **Whether a genuinely new baseline capability is warranted at all**,
  versus concluding `core.hierarchical_model`'s existing deterministic
  trend/Fourier continuation (already forward-projected by `core.
  planning.future_context`) already satisfies role #5's planning intent,
  and any new time-varying-baseline capability should be scoped to in-
  sample measurement/diagnostics only.
- **The statistical process itself** (a Hilbert Space Gaussian Process
  mirroring `pymc-marketing`'s built-in `time_varying_intercept`; a
  discrete-time random-walk-style process; or no new process at all).
- **The identifying strategy** a baseline process would declare under
  `REQ-LATENT-001` - unlike Candidate A's capture-share Dirichlet anchor,
  a baseline has no obvious analogous anchor, and this record does not
  supply one.
- **Whether, and how, the baseline is projected forward for planning** -
  no planning use at all; holding at the fitted process's own implied
  steady-state/prior-mean value (mirroring, but not identical to,
  `hold_last_observed`); or restricting to a process with validated
  extrapolation behaviour first. Upstream's own documentation directly
  cautions against the most obvious default (naive GP extrapolation)
  for this exact use case.

## Affected modules (target - not yet touched)

- a time-varying-baseline module (module TBD; depends on the process
  decision above, not yet implemented)
- `ancestry_mmm/core/hierarchical_model.py` (`build_fh_hierarchical_
  model`'s static `intercept` term - not yet touched)
- `ancestry_mmm/core/market_specific_model.py` (`build_fh_market_
  specific_model`'s static `intercept` term - not yet touched)
- `ancestry_mmm/core/latent_state_identification.py` (read-only reference
  for this record - the existing identification contract a baseline
  process would need to satisfy, not itself modified by this record)
- `ancestry_mmm/core/planning/future_context.py` (read-only reference -
  the existing trend/Fourier continuation this record's Candidate T3/P1
  options would leave as the sole planning-relevant mechanism, not
  itself modified by this record)
- `docs/wp10_time_varying_baseline_decision_package.md` (new)
- `docs/approved_requirements/REQ-BASELINE-001.md` (this record)
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

- Whether a new time-varying-baseline capability is warranted at all,
  versus relying on existing trend/Fourier continuation.
- The statistical process (Gaussian Process, random walk, or none).
- The identifying strategy under `REQ-LATENT-001`.
- The forward-projection mechanism for planning use, if any is approved.

All four are recorded in `docs/wp10_time_varying_baseline_decision_
package.md` with candidate approaches and their tradeoffs - none selected
by this coding pass.

## Owner

Modelling

## Approval date

2026-08-18
