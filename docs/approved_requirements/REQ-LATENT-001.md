# REQ-LATENT-001: Latent-State Scale and Location Identification

## PRD source

Ancestry MMM PRD Part 6 v1.6 (intro bullet 3, §16.1, §16.5, §30.1, §30.3, §37
`MD-021`, §38 AC-09), Part 7 v1.5 (§0.15 intro bullet 5, §9.1, §20.7, §39
blocking condition #6, §48 `VL-026`), and Part 10 v1.6 (`FCH-02`, §17.7
"Latent-state identification", §44, §47 `UX-028`) — reconciled by Work
Package 0 of `Media-Mix-Lab: Coding LLM Next Steps Post PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17). Candidate A latent branded-search demand
(`REQ-SEARCH-002`) is the first concrete integration target for this record,
per the brief's own instruction; this record does not itself approve a
specific identification strategy for that state.

No module in this repository currently declares or validates a scale/
location identification strategy for a fitted latent state. `core.
search_capacity`'s latent demand state has no recorded identifying
constraint.

## Capability status

Not yet implemented. Target-state contract only.

## Requirement

### 1. Every fitted latent causal state needs an identifying strategy

Every fitted latent mediator, latent demand pool, or other latent state that
enters a causal pathway (including Candidate A's latent branded-search
demand, and any future latent baseline state) must declare how its scale and
orientation are identified, using one of:

- fixing one measurement or structural loading;
- anchoring the latent state to an observed quantity with a defined unit;
- constraining a reference variance or scale;
- a validated measurement model with an identified loading structure;
- another approved identifying constraint with equivalent statistical
  effect.

### 2. The identifying choice is substantive, not cosmetic

The identifying choice determines what one unit of the latent state means.
It must be stored in the model specification and effect metadata, not left
implicit in code. Prior regularisation alone must not be described as
resolving structural non-identification.

### 3. Compiler-level rejection of unresolved rescaling/sign indeterminacy

The model compiler must reject a latent structure that remains invariant
under an arbitrary rescaling or sign reversal that could be offset by
another free parameter, unless the intended posterior quantity is otherwise
identified. This extends `core.graph_model_compiler`'s blocking-error
contract (`REQ-GRAPH-001` §7): a fitted latent mediator or latent demand
state with no valid scale-identification strategy is a compiler-level
blocking error, not a warning.

### 4. Validation must confirm the anchor holds under sampling

Validation must confirm: the anchor or constraint is present in the compiled
model; the resulting scale is interpretable for the requested estimand;
posterior sampling does not reveal unresolved scale or sign indeterminacy;
synthetic recovery succeeds for custom/advanced latent structures; changes to
the identification choice do not create unexplained decision instability.

### 5. Reporting and use-eligibility gate

A latent mediator or latent demand state without an approved identifying
scale or anchor must remain visibly unsuitable for official causal
reporting, curve publication, planning, or optimisation for the affected
pathway — this is a fail-closed gate, consistent with the existing Search
fail-closed pattern (`core.predict.predict_mu`/`core.attribution.
compute_shapley_contributions` already fail closed for an unwired Candidate
A pathway under `REQ-SEARCH-002`; this record extends the same fail-closed
principle to identification specifically, not only to wiring).

### 6. Separate evidence dimension

Latent-state identification status must be reported separately from
estimand-specific graphical identification (`REQ-IDENT-001`), predictive
validation, and structural stability — never collapsed into one
undifferentiated status.

## Explicitly excluded (decision-required, not approved by this record)

- for each specific approved latent mediator or latent demand state
  (including Candidate A), the actual substantive scale anchor, measurement
  model, or identifying constraint, and the business interpretation of one
  unit of that state (Part 6 §37 `MD-021`);
- the accepted general-purpose identification-strategy taxonomy where it
  extends beyond the five listed in Requirement 1 (Part 7 §48 `VL-026`);
- business/technical labels for identification status (Part 10 §47
  `UX-028`).

## Affected modules (target)

- `ancestry_mmm/core/search_capacity.py` (Candidate A's latent demand state
  — first concrete integration target, per PRD reconciliation instruction)
- `ancestry_mmm/core/graph_model_compiler.py` (extend blocking-error
  contract for unresolved latent-state identification)
- a shared latent-state identification domain object (module TBD)
- `docs/approved_requirements/REQ-LATENT-001.md` (new)
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

None yet. Implementing Requirement 3 against Candidate A will require
`core.search_capacity`'s latent-demand construction to declare an
identification strategy — a fit-relevant change requiring re-fit and
fingerprint invalidation for any project with an existing Candidate A fit,
once implemented.

## Unresolved decisions

- Candidate A's actual identifying anchor/constraint (`MD-021`) — statistical
  modelling decision, not resolvable by this reconciliation record.
- Whether identification validation runs at fit time, as a separate
  Diagnostics check, or both.

## Owner

Modelling

## Approval date

2026-08-17
