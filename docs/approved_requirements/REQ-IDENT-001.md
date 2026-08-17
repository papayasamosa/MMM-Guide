# REQ-IDENT-001: Estimand-Specific Graphical Identification

## PRD source

Ancestry MMM PRD Part 6 v1.6 (intro bullets 1–2, §4.1 including
`REQ-4.1-04`/`REQ-4.1-05`, §30.1, §38 AC-07), Part 7 v1.5 (§0.15 intro bullet
4, §9, §9.1, §20.6, §39 blocking condition #7, §48 `VL-026`), and Part 10
v1.6 (`FCH-01`, §17.6, §17.7 including the mandated disclaimer, §23.4, §23.8,
§47 `UX-028`) — reconciled by Work Package 0 of `Media-Mix-Lab: Coding LLM
Next Steps Post PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17). Depends on `REQ-GRAPH-001` (the approved causal graph
remains the authoritative structural input; this record adds an
estimand-specific diagnostic layered on top of it, not a replacement for
graph structural validation).

`core.causal_graph.validate_causal_graph` (implemented under `REQ-GRAPH-001`)
checks graph structure, roles, bad controls, cycles, and edge directions.
`core.identification_diagnostics` checks correlation, condition number,
posterior coefficient variation, and sensitivity on a fitted model. Neither
performs backdoor-path analysis, proposes or validates an adjustment set for
a *requested estimand*, or reports treatment descendants/colliders relative
to that estimand. This record's contract is a distinct, additional
diagnostic layer; it does not replace either existing check.

## Capability status

Not yet implemented. Target-state contract only.

## Requirement

### 1. A diagnostic, not a proof

A graph-compatible adjustment set is necessary evidence for an
adjustment-based estimand; it is not sufficient evidence that the causal
effect is valid. Passing a backdoor/d-separation/adjustment-set check
validates the requested adjustment logic *under the assumed graph*. Every
surface (technical or business) that displays this result must not state or
imply that it proves: the graph itself is correct; there is no unobserved
confounding; timing or measurement is correct; the functional form is valid;
or the effect is empirically well identified. This disclaimer is a
functional requirement of the diagnostic's presentation, not optional
UX copy.

### 2. Diagnostic scope, where adjustment-set logic applies

Where the requested effect can be assessed using graphical adjustment logic
against the approved causal graph, before treating the resulting effect as
identified the diagnostic must assess and record, per requested estimand:

- open backdoor paths;
- the proposed adjustment set and whether a minimal valid adjustment set
  exists;
- treatment descendants included (incorrectly) as controls;
- colliders or collider descendants opened by the proposed conditioning;
- whether the requested effect type (direct vs. total) is compatible with
  the proposed conditioning set;
- whether a required confounder is unavailable or unmeasured under the
  graph.

### 3. Explicit status vocabulary

The diagnostic must resolve to one of an explicit, closed status vocabulary
per requested estimand — at minimum: `graph_compatible`; `review_required`;
`not_identified_under_graph`; `unsupported_by_current_checker`; `not_
applicable`. A status must never be inferred from the presence of an edge
alone; it is tied to the specific requested treatment, outcome, and effect
type.

### 4. Structural/linked-model estimands use a different identification path

Where the requested estimand is identified through a full structural or
linked model rather than ordinary covariate adjustment (e.g. a
capacity-constrained or mediated pathway compiled through
`core.graph_model_compiler`), this record's diagnostic does not apply as the
sole identification evidence. The identification plan must instead state the
structural equations, observed measurements, identifying constraints, and
assumptions that replace an adjustment-set argument. A structural model must
not be labelled "graph-identified" merely because an adjustment set exists
for a different estimand, and a failed adjustment-set test does not
automatically invalidate a correctly specified structural system targeting a
different estimand with its own approved identification strategy.

### 5. Compiler-level blocking

Official model compilation must fail when a requested adjustment-based
estimand uses a conditioning set incompatible with the approved graph and no
approved alternative identification strategy exists — extending
`core.graph_model_compiler`'s existing blocking-error contract
(`REQ-GRAPH-001` §7), not superseding it.

### 6. Reporting separation

Graphical-identification status must be reported as a separate evidence
dimension from predictive validation, structural stability (`REQ-STAB-001`),
and latent-state identification (`REQ-LATENT-001`) — never collapsed into
one undifferentiated "identified"/"not identified" flag.

## Explicitly excluded (decision-required, not approved by this record)

- the full set of graphical-identification statuses, when graph checks are
  required versus optional, and the accepted identification strategies for
  structural/linked estimands (Part 7 §48 `VL-026`);
- the business and technical labels used for each status (Part 10 §47
  `UX-028`).

## Affected modules (target)

- `ancestry_mmm/core/identification_diagnostics.py` (extend, or a new sibling
  module for estimand-specific graphical checks — module boundary to be
  decided at implementation time)
- `ancestry_mmm/core/causal_graph.py` (read-only consumer of the approved
  graph; this record must not add a second, divergent structural validator)
- `ancestry_mmm/pages/14_Causal_Graph.py` / `ancestry_mmm/pages/06_
  Diagnostics.py` (surface the diagnostic and its mandated disclaimer)
- `docs/approved_requirements/REQ-IDENT-001.md` (new)
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

None yet.

## Unresolved decisions

- Graph-library/algorithm choice for backdoor-path and adjustment-set
  computation (Context7/upstream-reference workflow required before
  selection, per root `AGENTS.md`).
- Whether this diagnostic is computed synchronously at graph-approval time,
  at model-compile time, or both.

## Owner

Modelling

## Approval date

2026-08-17
