# REQ-CAP-001: Capacity and Cap Semantics

## PRD source

Ancestry MMM PRD reconciliation of `AGENTS.md`'s "Capacity and cap
invariants" section - a standing repository invariant, not itself sourced
from a specific PRD Part/section the way `REQ-SCEN-*`/`REQ-FORECAST-001`
are. Reconciled by Work Package 11 of `Media-Mix-Lab: Coding LLM Next
Steps After PR #267 and Latest PRD Validation Updates`.

## Approval and traceability

Reconciled into repository authority by Work Package 11 (2026-08-18),
per this repository's standard authority hierarchy. Depends on
`REQ-SEARCH-002` (the only existing concrete capacity-constrained
pathway - Candidate A's latent-demand/capture/cap chain,
`core.search_capacity`) and `REQ-GRAPH-001` (whose own governed-edge-role
table already states `capacity_constrained` is "Supported only by the
explicit Candidate A Search linked engine for its authorised Search
structure; unsupported for every other structure" - confirming this gap's
exact boundary from the graph-compiler side).

This record reconciles the already-flagged gap
(`docs/specification_authority.md`: "Capacity and cap semantics
(`REQ-CAP-001`) — No approved requirement/decision yet... no `REQ-CAP-001`
record yet translates it into an approved modelling contract") into a
formal requirement record - it does **not** approve an implementation.
Inspecting Candidate A's existing implementation against `AGENTS.md`'s
invariants surfaced concrete, specific gaps (not merely an absent
record): `core.search_capacity.candidate_a_forward`'s `cap_binding` field
is a strict two-value boolean (`np.isclose(paid, cap, ...)`), while
`AGENTS.md` requires four values (capped / uncapped / ambiguous /
unavailable); neither "ambiguous" nor "unavailable" is represented
anywhere in the current code. Genuinely unresolved questions block any
implementation and are recorded below as decision-required, per this
program's own governing instruction: do not implement directly from an
unapproved gap, and if a genuine statistical/causal/business/governance
decision is required, create a decision package and stop that workstream
rather than guessing. See `docs/wp11_capacity_cap_semantics_decision_
package.md`.

## Capability status

Not yet implemented as a pathway-agnostic contract. Blocked pending the
decision package referenced above - this is a target-state contract
only, reconciling `AGENTS.md`'s own standing invariant (already partially
realised, non-uniformly, inside Candidate A specifically) into repository
authority, without approving any specific cap-hit vocabulary
implementation, module-sharing architecture, or cap-governance mechanism
beyond what Candidate A already has.

## Requirement (target state - not yet approved for implementation)

### 1. Cap is never realised spend/delivery

`AGENTS.md`'s existing rule ("A Paid Search (or other lower-funnel) cap
must not be labelled or entered as realised spend") and Candidate A's own
structural enforcement (`core.search_capacity.candidate_a_forward`'s
`realised_paid_search_delivery = min(paid_opportunity, cap)`, never the
cap value itself) are inherited unchanged, not re-decided here.

### 2. A non-binding cap must not manufacture incremental value

`AGENTS.md`'s existing rule is inherited unchanged: raising a cap that is
not binding must have no effect on realised delivery, captured demand, or
final outcome. Candidate A's `min(...)` construction already satisfies
this mechanically for its own pathway; any future capacity-constrained
pathway approved under this record must preserve the same property,
whatever its specific algebraic form.

### 3. Captured plus unmet demand must reconcile to latent demand

`AGENTS.md`'s existing reconciliation identity is inherited unchanged.
Candidate A's `total_captured_demand + unmet_demand == latent_branded_
search_demand` (enforced structurally, `core.search_capacity.py` lines
310-317) is the one existing concrete instance; whether this exact
algebraic form is the general contract for any future pathway, or
whether `AGENTS.md`'s own "not one frozen algebraic form" caution permits
a different reconciliation shape, is decision-required (see Explicitly
excluded).

## Explicitly excluded (decision-required, not approved by this record)

- **The cap-hit status vocabulary's concrete definition.** `AGENTS.md`
  requires four values (capped / uncapped / ambiguous / unavailable);
  Candidate A's current code implements only two (a strict boolean).
  What "ambiguous" (a posterior-uncertainty-driven near-boundary status,
  as opposed to a point-estimate tolerance check) and "unavailable" (no
  governed cap value at all, distinct from a supplied cap of zero) mean
  operationally, and whether the vocabulary is a single mandatory
  categorical field or a disclosed set of evidence facets, is not decided
  by this record.
- **Whether the contract is generalised into a shared, pathway-agnostic
  module now, or deferred until a second capacity-constrained pathway
  exists to compare against.** `EDGE_ROLE_CAPACITY_CONSTRAINED` is
  already generic graph vocabulary, but the only compiler logic that
  exists for it is Candidate-A-specific structural validation
  (`core.graph_model_compiler`). Generalising from one existing example
  risks encoding accidental Candidate-A-specific assumptions; deferring
  leaves the gap `REQ-GRAPH-001` already names unimplementable in any
  pathway-agnostic sense.
- **What "a governed source and a versioned cap-hit rule" requires**
  beyond the cap object's own existing identity/versioning already
  provided by `core.search_objects` for Candidate A specifically -
  whether the thresholding/tolerance logic itself (e.g. the `rtol`/`atol`
  constants currently hard-coded in `core.search_capacity`) also needs
  independent governance/versioning is not decided.
- **Whether Candidate A's exact reconciliation-identity algebraic form
  generalises unchanged to a future pathway**, or whether a different
  pathway may reconcile demand differently under `AGENTS.md`'s own
  "do not prescribe one exact... mechanism" caution.

## Affected modules (target - not yet touched)

- a pathway-agnostic capacity/cap module (module TBD; depends on the
  generalisation-timing decision above, not yet implemented)
- `ancestry_mmm/core/search_capacity.py` (read-only reference for this
  record - the one existing concrete implementation this record's
  candidates would extend, refactor, or leave unchanged, not itself
  modified by this record)
- `ancestry_mmm/core/graph_model_compiler.py` (read-only reference - the
  existing Candidate-A-only `capacity_constrained` compiler logic, not
  itself modified by this record)
- `docs/wp11_capacity_cap_semantics_decision_package.md` (new)
- `docs/approved_requirements/REQ-CAP-001.md` (this record)
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

- The cap-hit status vocabulary's concrete operational definition
  (particularly "ambiguous" and "unavailable").
- Whether the contract is generalised into a shared module now or
  deferred until a second capacity-constrained pathway exists.
- What cap-data governance/versioning requires beyond the existing
  `core.search_objects` object-identity contract.
- Whether Candidate A's reconciliation-identity algebraic form is the
  intended general form for any future pathway.

All four are recorded in `docs/wp11_capacity_cap_semantics_decision_
package.md` with candidate approaches and their tradeoffs - none selected
by this coding pass.

## Owner

Modelling

## Approval date

2026-08-18

## Addendum, 2026-08-30: generalisation direction approved (Decision 18), G1/G2/G3 remains genuinely open

The business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (Decision 18, "Real-world capacity
constraints belong in the optimiser") approves the *business
requirement* that capacity constraints must be flexible, user-editable,
and shared consistently across Scenario Planner, Optimiser, and
Search-specific capped contribution — this is directionally **Candidate
G1** ("generalise now: a shared module") from `docs/wp11_capacity_cap_
semantics_decision_package.md`, since a Candidate-A-scoped-only module
(G2) cannot serve TV inventory, sponsorship inventory, or any other
non-Search capacity example Decision 18 names.

This addendum does **not** select G1 over G3 (approve the vocabulary now,
defer only the shared module) — both remain compatible with Decision
18's business requirement, and the engineering-risk tradeoff between them
(encoding accidental Candidate-A-specific assumptions into a premature
generalisation, vs. leaving the gap unimplementable in any pathway-
agnostic sense) is exactly the kind of question this package's own text
reserves for a future implementation-time decision, not a business
policy this brief settles. **Candidate S1/S2/S3 (the cap-hit status
vocabulary's concrete definition) also remains fully open** — Decision
18 does not specify how "ambiguous" or "unavailable" should be
represented.

**What this addendum does approve, at the contract level:** capacity
constraints must be expressible for at least the categories Decision 18
names (spend limits, delivery/exposure limits, availability on/off,
fixed commitments, minimum/maximum ranges) and usable by Scenario
Planner, Optimiser (see `REQ-OPT-001`'s Requirement 4, which cross-
references this record rather than duplicating it), and Search-specific
capped contribution from one governed source — never three independently
diverging capacity representations. A non-money-denominated limit (e.g.
impressions) must never be silently treated as a spend cap absent a
valid, governed mapping — reaffirming, not changing, `AGENTS.md`'s
existing invariant this record's §1 already cites. The optimisation
result must disclose which constraints (of any kind) were binding, per
`REQ-OPT-001`'s Requirement 5.

No code, schema, or module is created by this addendum. Phase E
implementation must still resolve G1/G2/G3 and S1/S2/S3 via
`docs/wp11_capacity_cap_semantics_decision_package.md` before building
anything.

## Addendum, 2026-08-30 (Phase C/E): cap-hit vocabulary and shared module implemented (Decisions 10/18)

The user's 2026-08-29 "Post-UI/UX Implementation Instructions" brief,
confirmed in-session 2026-08-30, explicitly delegates this record's
S1-S3/G1-G3 technical selection (previously reserved by
`docs/wp11_capacity_cap_semantics_decision_package.md`) to research and
validation, while retaining ownership of the business questions
(Decisions 10 and 18, already answered). This addendum records the
resulting resolution: full decision record in
`docs/capacity_cap_semantics_decision_record.md`; implementation in the
new `ancestry_mmm/core/capacity.py`.

**Resolved:**

- the cap-hit status vocabulary's concrete operational definition
  (`unavailable` = no governed cap value at all, distinct from a
  supplied finite cap of zero; `ambiguous` = only reachable from
  posterior-draw evidence, via an explicit, documented `0.20`
  probability-of-binding ambiguity band around 0.5; `capped`/`uncapped`
  otherwise) - S1, extended so the full underlying probability/point
  evidence is always retained and disclosed alongside the categorical
  label, never replaced by it;
- the module-sharing timing - G1, scoped precisely to the cap-hit
  vocabulary, the governed `CapacityLimitDefinition` object (spanning
  Decision 18's named categories: spend limits, delivery/exposure
  limits, availability toggles, fixed commitments, bounded ranges), and
  the generalised reconciliation identity
  (`verify_capacity_reconciliation`) - NOT `core.graph_model_compiler`'s
  `capacity_constrained` structural validation, which remains
  Candidate-A-only until a second concrete capacity-constrained pathway
  actually exists to validate against (a narrower, still-legitimate
  deferral, not a re-reservation);
- what "a governed source and versioned cap-hit rule" requires beyond
  the cap object's own existing identity/versioning: the classification
  RULE itself (the ambiguity band and point-evaluation tolerance) is now
  independently versioned (`CAP_HIT_CLASSIFICATION_RULE_VERSION`);
- whether Candidate A's reconciliation identity generalises: yes, as
  `realised + unmet == potential`, grounded in PyMC's own official
  `Censored` distribution (confirmed via Context7) as a recognised
  statistical pattern for the underlying min/censoring relationship,
  without prescribing any specific likelihood family (`AGENTS.md`'s "not
  one frozen algebraic form" caution preserved).

`ancestry_mmm/core/search_capacity.py` is extended, not replaced: a new
`candidate_a_cap_hit_status` function computes the four-value
classification from Candidate A's existing cap/binding-evidence inputs
via `core.capacity`'s shared function. `CandidateAForwardState.cap_
binding` and `CandidateAPosteriorOutputs.probability_cap_binding`
(the existing boolean/probability fields) are completely unchanged -
verified by dedicated regression tests.

**Still not resolved / deliberately out of scope:** `core.graph_model_
compiler`'s compiler-level support for a second capacity-constrained
pathway (no such pathway exists yet); any actual capacity VALUE for a
real market/channel (this addendum supplies the governed shape, never
invents a number); wiring `CapacityLimitDefinition` into the Scenario
Planner/Optimiser UI (a separate integration pass, `REQ-OPT-001`'s own
scope).
