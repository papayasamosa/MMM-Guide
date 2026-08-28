# REQ-SEO-001: Governed SEO Visibility/Ranking Metric Definition and Observation Contract

## PRD source

Ancestry MMM PRD Part 2 v1.5 §4.6/§4.6.2 and §26.3 item 14; Part 3 v1.13
`FR-CAU-015` and §29 item 29; Part 5 v1.6 §17.9, §17.10, `DD-020`; Part 6
v1.11 §15.8, §15.9, §15.10, `MD-008C`; Part 7 v1.10 §16.6, §22.7,
`VL-034`; Part 8 v1.6 preamble, §18.5, §30.6, `PL-028`; Part 9 v1.7
§13.9-§13.11, §19.8, `RP-032`; Part 10 v1.8 §16.9, §17.3, §18.4; Part 11
v1.8 §16.20, §16.21, `API-029` — reconciled by Work Package 1 of
`Media-Mix-Lab Coding LLM Next Steps 2026-08-27`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-28). Target-state architecture contract for the
governed **data and provenance shape** of an SEO visibility/ranking
metric definition and its observed values, as objects distinct from —
and never a proxy for — organic Search capture (`REQ-SEARCH-001` §1.5).

This record approves the shape only. It does not approve, select, or
imply: which metric(s) are used; their source methodology; their causal
role (control / exposure / mediator / state / diagnostic / other); any
transformation; any estimand; or any controllable SEO intervention — all
deferred to `docs/wp1_search_seo_granularity_decision_package.md`.

Depends on `REQ-SEARCH-001` (the object-separation precedent this record
follows) and `REQ-GRAPH-001` (the node-role vocabulary a future approved
causal role would use — no new role is created by this record).
`REQ-SEARCH-005`'s eligibility record structurally applies to an SEO
object once one is registered (every axis defaults `false` per that
record's Requirement 4), but this record does not itself wire that
binding.

## Capability status

Zero implementation. No SEO-visibility object, metric-definition record,
or observation-fact table exists anywhere in this repository.

## Requirement

### 1. Metric definition record

`dim_seo_visibility_metric_definition` (Part 5 §17.9): `metric_name`,
`source_methodology`, `methodology_version`, `unit`, `directionality`,
`aggregation_rule`, `permitted_roles` (governed, closed set — empty and
unpopulated until a role is separately approved), `interpretation`,
`limitations`, `schema_version`, `effective_period_start`/
`effective_period_end`, `approval_status`.

### 2. Observation record

`fact_seo_visibility_observation` (Part 5 §17.9): `value`, market/scope
grain, `observation_date`, `methodology_version` at time of observation,
a quality/status flag. Per Part 11 §16.21: "an observed ranking or
visibility value remains an observed state. It is not an effect estimate
or intervention request."

### 3. Distinct from organic capture

An SEO visibility observation must never be pooled with, substituted
for, or silently relabelled as organic Search capture (`REQ-SEARCH-001`
§1.5). Aggregate organic Search contribution remains fully computable
and reportable with zero dependency on any SEO visibility object
existing (Part 5 §17.10's six-stage conceptual separation: demand ->
opportunity -> visibility state -> capture -> outcome -> separately
estimated SEO effect).

### 4. Not automatically an intervention or model input

Registering a metric definition or ingesting an observation changes no
fitting, causal-graph, planning, or optimisation behaviour by itself —
mirroring `REQ-SEARCH-001` §7's "registering a Search object changes no
fitting behaviour by itself." A causal role, if and when approved, is a
separate, explicit, later act — never implied by registration.

### 5. Causal-role field is governed but unpopulated

The metric-definition schema reserves a `causal_role` field (candidate
values per Part 6 §15.8: `diagnostic_only` | `observed_context_variable`
| `mediator_or_capture_efficiency_state` |
`structural_exposure_intervention`) and a `direction_relative_to_estimand`
field (Part 6 §15.10). Both fields exist in the schema and are set to an
explicit `not_yet_approved` sentinel by this record — never defaulted to
any of the four candidates, and never left silently absent (a missing
field and an explicit not-yet-approved sentinel are not the same state).

### 6. Reporting-label separation

Any report surfacing an SEO visibility observation, or a future approved
SEO effect, must use a label distinct from "organic Search contribution"
and from "Paid Search contribution" (Part 9 §13.9-§13.11/§19.8). A weak
or unapproved SEO effect must never suppress, qualify, or be conflated
with the separately valid aggregate organic-contribution figure.

### 7. Versioning, persistence, staleness

Same governed-record contract as `REQ-SEARCH-004` §7: `schema_version`,
immutable version lineage, export/import round-trip with
quarantine-on-malformed, and a metric-definition or methodology-version
change stales every downstream artefact that consumed it via the
existing fingerprint mechanism.

## Out of scope (decision-required, not approved by this record)

See `docs/wp1_search_seo_granularity_decision_package.md`. In summary,
this record does not approve:

- which SEO/ranking metric(s) are used, or their source methodology
  (Part 6 `MD-008C`, Part 7 `VL-034`);
- SEO visibility's causal role, or its direction relative to any given
  estimand (Part 6 `MD-008C`, Part 3 `FR-CAU-015`, Part 2 §26.3 item 14);
- any transformation of a non-linear ranking metric (e.g. average
  position) for use as a linear treatment (Part 6 v1.11 preamble);
- any controllable SEO intervention (unit, feasible range, cost, timing,
  operational mechanism) distinct from the observed metric (Part 8
  `PL-028`);
- any planning or optimisation eligibility for an SEO-derived effect
  (`REQ-SEARCH-005` §4; Part 8 §18.5/§30.6).

## Affected modules

- A new module, e.g. `ancestry_mmm/core/seo_visibility.py` (or added to
  `ancestry_mmm/core/search_objects.py`)
- `ancestry_mmm/core/causal_graph.py` (referenceable node once a role is
  approved — no new node role required per `REQ-GRAPH-001` §4's existing
  vocabulary; this record does not itself create a node)
- `ancestry_mmm/core/persistence.py`

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_search_seo_granularity_authority_reconciliation.py::TestSearchSeoGranularityOverlayReconciled::test_req_seo_001_indexed_and_classified_incomplete`
- `ancestry_mmm/tests/test_search_seo_granularity_authority_reconciliation.py::TestSearchSeoGranularityOverlayReconciled::test_all_records_reference_the_decision_package`
- `ancestry_mmm/tests/test_search_seo_granularity_authority_reconciliation.py::TestSearchSeoGranularityOverlayReconciled::test_req_seo_001_defers_causal_role`

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
