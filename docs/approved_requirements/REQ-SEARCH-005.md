# REQ-SEARCH-005: Search Granularity Capability and Multi-Axis Eligibility Contract

## PRD source

Ancestry MMM PRD Part 3 v1.13 `FR-SEA-005`, `FR-SEA-006`, and the v1.13
preamble's "separate eligibility states" invariant; Part 5 v1.6 §17.6
(`fact_search_granularity_capability`); Part 7 v1.10 §22.13 ("Search
use-eligibility summary"); Part 8 v1.6 §3.9, §18.5, §25.6, §30.6; Part 9
v1.7 (labelling consistency for eligibility-gated content); Part 11 v1.8
§16.19, `API-029` — reconciled by Work Package 1 of `Media-Mix-Lab Coding
LLM Next Steps 2026-08-27`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-28). The current implementation adds explicit
parent/child model-grain selection, ragged reporting, and fail-closed child
planning validation while preserving the existing single-valued eligibility
pattern
(`ActivityDefinition.planning_eligibility`, `REQ-SEARCH-001` §9's
`optimisable`/never-`optimisable` rule) to a governed, market x
search-route x platform x parent-activity record carrying six
independent boolean eligibility axes. It does not approve any evidence
threshold that would ever set one of those axes to true — see
`docs/wp1_search_seo_granularity_decision_package.md`.

Depends on `REQ-SEARCH-004` (the taxonomy and parent-child identities
this record's axes are keyed against) and `REQ-SEARCH-001` (the existing
single-valued eligibility precedent this record extends, never
replaces, for the six original Search objects).

## Capability status

Partial implementation. Explicit parent/child model-grain selection,
ragged reporting, and the child planning/economics fail-closed boundary are
implemented. The full six-axis capability record and any evidence threshold
that could promote a child to economics, planning, or optimisation remain
unimplemented; only the existing single-valued `planning_eligibility` enum
is otherwise available.

## Requirement

### 1. Multi-axis capability record

A governed record keyed at `market x search_route x platform x
parent_activity_id` (Part 5 §17.6), carrying: `highest_available_grain`,
`highest_approved_model_grain`, `highest_approved_reporting_grain`, and
six independent boolean flags — `model_eligible`, `contribution_eligible`,
`curve_eligible`, `economics_eligible`, `planning_eligible`,
`optimisation_eligible`. Each flag is independently settable; no flag's
value may be inferred from another.

### 2. Ragged coverage is valid, not a defect

One market may support intent-group contribution and economics; another,
intent-group contribution but parent-level economics only; another,
aggregate Search only. Part 5 §17.6 states this explicitly: "This is
valid ragged coverage rather than a data defect." A dependent workflow
must never surface ragged Search-granularity coverage as an error or
remediation prompt.

### 3. Five non-interchangeable planning/reporting states

Per Part 8 §25.6, a child intent group occupies exactly one of five
states — `contribution only`, `response curve only`, `response curve
plus economics`, `scenario planning eligible`, `optimisation eligible` —
and occupying one state never implies eligibility for the next. A
dependent workflow must read and act on the exact state, never assume
progression.

### 4. Default-excluded posture

Any intent group, SEO-visibility object (`REQ-SEO-001`), or granularity
level not yet separately validated defaults every axis in Requirement 1
to `false`/ineligible (Part 8 §18.5, §30.6; Part 7 §22.13). Paid Search
spend's existing `optimisable` eligibility (`REQ-SEARCH-001` §9) is
unaffected and continues under its own existing contract. This record
establishes the default-excluded posture and the record shape that would
flip a flag; it does not itself define the evidence bar for flipping one.

### 5. Versioning, persistence, staleness

Same governed-record contract as `REQ-SEARCH-004` §7: `schema_version`,
immutable version lineage, export/import round-trip with
quarantine-on-malformed, and fit/curve/scenario staleness wired through
the existing fingerprint mechanism.

## Out of scope (decision-required, not approved by this record)

See `docs/wp1_search_seo_granularity_decision_package.md`. In summary,
this record does not approve:

- the evidence or threshold criteria that would ever set
  `contribution_eligible`, `curve_eligible`, `economics_eligible`,
  `planning_eligible`, or `optimisation_eligible` to `true` for an
  intent group (Part 7 `VL-032`, Part 8 `PL-027`);
- the same, for an SEO-visibility object, plus the prior question of
  whether any controllable SEO intervention exists at all to make
  `planning_eligible`/`optimisation_eligible` meaningful (Part 8
  `PL-028`);
- any parent-to-child cost-allocation method that `economics_eligible`
  would depend on (`REQ-SEARCH-004`'s "Out of scope"; Part 6 `MD-008B`,
  Part 7 `VL-033`).

## Affected modules

- `ancestry_mmm/core/search_objects.py` (or a new capability-registry
  module)
- `ancestry_mmm/core/activities.py` (referencing `parent_activity_id`)
- `ancestry_mmm/core/persistence.py`

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_search_seo_granularity_authority_reconciliation.py::TestSearchSeoGranularityOverlayReconciled::test_req_search_005_indexed_and_classified_incomplete`
- `ancestry_mmm/tests/test_search_seo_granularity_authority_reconciliation.py::TestSearchSeoGranularityOverlayReconciled::test_all_records_reference_the_decision_package`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Out of scope" above, tracked by
`docs/wp1_search_seo_granularity_decision_package.md`.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-28

## Implementation update, 2026-09-04

Explicit parent/child model-grain selection, parent/child double-fit
prevention, ragged reporting, and the default-excluded deeper-child planning/
economics boundary are implemented. The full market × route × platform
multi-axis capability registry and evidence thresholds remain decision-required.
