# REQ-CAUSALROBUST-001: Causal Robustness Evidence Contract

## PRD source

Ancestry MMM PRD Part 3 v1.10 (retained v1.8 section, refinement bullets on
empirical causal-structure diagnostics), Part 6 v1.8 (intro bullets on DAG
falsification, placebo/permutation refutation, and unmeasured-confounding
sensitivity), Part 7 v1.7 (intro bullets on the same three evidence
dimensions plus the "a graph that is not falsified is not proven true" /
"a graph-compatible adjustment strategy is not proof of no unobserved
confounding" language, §48 decision items `VL-028`/`VL-029`), Part 9 v1.6
Final ("a graph that is not falsified must not be described as proven
correct; a successful placebo diagnostic must not be described as proof of
causality; and a sensitivity analysis must not be described as proof that
unmeasured confounding is absent"), and Part 10 v1.8 Final (§47 `UX-031`
causal-robustness evidence presentation) — reconciled by Work Package 0 of
`Media-Mix-Lab: Coding LLM Next Steps After PR #286`. (Part 5 v1.6 remains
referenced-but-absent locally, per `REQ-SCENGINE-001`'s PRD source note;
no content of this record depends on it.)

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-18). Target-state evidence-contract only. Depends on
`REQ-IDENT-001` (this record adds *empirical* causal-structure evidence,
distinct from — and never a replacement for — `REQ-IDENT-001`'s
*graphical* backdoor-identification diagnostic) and `REQ-LATENT-001`
(likewise distinct from latent-state identification evidence).

## Capability status

Zero implementation. No DAG-falsification, placebo/permutation
refutation, or unmeasured-confounding-sensitivity check exists anywhere
in this repository. `core.estimand_identification` (`REQ-IDENT-001`)
performs graphical backdoor analysis only; it does not challenge whether
the graph itself is empirically consistent with the data, nor does it run
a placebo/permutation test or a confounding-sensitivity analysis.

## Requirement

### 1. Three distinct evidence dimensions, never collapsed into one score

Where methodologically applicable and computationally feasible, causal
robustness evidence may include, as three separate, independently
reported dimensions:

- **DAG falsification** — testing the approved causal graph's testable
  conditional-independence implications against observed data;
- **placebo or permutation refutation** — testing whether an
  effect-estimation pipeline manufactures an apparent effect after the
  treatment-outcome relationship has been deliberately severed;
- **unmeasured-confounding sensitivity** — showing how strong a
  hypothetical unmeasured confounder would need to be to materially
  change the causal conclusion.

These three, together with `REQ-IDENT-001`'s graphical identification and
`REQ-LATENT-001`'s latent-state identification, must never be combined
into one undifferentiated causal-credibility score or single pass/fail
flag. Each is reported as its own evidence artefact with its own status
and limitations.

### 2. Mandatory non-proof disclaimer

Every surface (technical or business) presenting any of the three
evidence dimensions above must not state or imply that:

- a graph not rejected by a falsification test is proven true;
- a passed placebo/permutation test is proof of causality;
- a low sensitivity to hypothetical confounding is proof that no
  unobserved confounding exists.

This mirrors and extends `REQ-IDENT-001`'s `GRAPHICAL_IDENTIFICATION_
DISCLAIMER` requirement to the three empirical dimensions above; a
distinct disclaimer per dimension is required, not a single reused
sentence stretched to cover all four (graphical + three empirical)
evidence types.

### 3. Distinguishing an informative test from an uninformative one

A DAG-falsification or placebo/permutation result must distinguish an
informative test (one capable of detecting a real violation given the
graph's structure and the available data) from a test that is effectively
uninformative — e.g. a graph too sparse, or a dataset too small, for the
test to have meaningfully rejected a false graph. A test that cannot fail
in practice must not be reported as though it had passed a meaningful
check.

### 4. No universal blocking threshold

This record does not define, and no implementation may invent, a
universal pass/fail threshold for any of the three dimensions. Part 7 §48
`VL-028` explicitly reserves "which estimands and approval levels require
[this evidence]... define interpretation, materiality and blocking
consequences" as a separate, unresolved decision. Absent that decision,
these three dimensions are evidence to be disclosed, not gates that block
or pass a model.

### 5. Structural-effect validation, not primary-MMM replacement

Causal robustness evidence under this record applies to a structural
causal engine's own outputs (per `REQ-SCENGINE-001`/`REQ-SCEFFECT-001`).
It must not replace, or be presented as equivalent to, the validation
already required for the primary hierarchical MMM, Candidate A, or
approved media-transformation semantics (`AGENTS.md`'s upstream-reference
and required-test-class sections).

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp_structural_causal_engine_decision_package.md`. In summary,
this record does not approve:

- the exact DAG-falsification test/statistic (Part 7 §48 `VL-028`/
  `VL-029`);
- the exact placebo/permutation refutation method (Part 7 §48 `VL-028`/
  `VL-029`);
- the exact unmeasured-confounding sensitivity method (Part 7 §48
  `VL-028`/`VL-029`);
- which estimands/approval levels require this evidence, or any
  materiality/blocking threshold (Part 7 §48 `VL-028`);
- business/technical labels and drill-down presentation for any of the
  three dimensions (Part 10 §47 `UX-031`).

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record): a future `core.causal_robustness`
(or equivalently named) diagnostic module analogous in structure to
`core.estimand_identification`/`core.latent_state_identification`
(explicit status vocabulary, mandatory disclaimer, "caller supplies the
computation" pattern), and `core.graph_model_compiler`/Diagnostics-page
wiring once that module exists.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_structural_causal_authority_reconciliation.py::TestStructuralCausalEngineOverlayReconciled::test_req_causalrobust_001_indexed_and_classified_incomplete`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp_structural_causal_engine_decision_package.md`.

## Owner

Modelling

## Approval date

2026-08-18
