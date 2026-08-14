# REQ-DATAIN-002: Governed Outcomes Workbook Semantics and Grouping

## Authority source

User-supplied task-specific implementation brief:

```text
Ancestry MMM Outcome Workbook, Dictionary, Grouping and DNA/FH Outcome
Semantics - fresh implementation brief after repository review on
2026-08-14.
```

This record registers the approved implementation vocabulary from that
brief. It does not independently reinterpret the external Ancestry MMM
PRD.

## Capability status

Approved for implementation. Work Package 0 registers this contract only;
runtime behaviour remains unchanged until the separately scoped packages
listed below are implemented and merged.

## Decision

The Outcomes logical domain remains a wide source table: one row is a
`period_start x market` observation and each measured outcome is a source
column. A governed version-2 Outcomes workbook has:

- required `outcomes` and `outcome_dictionary` sheets;
- optional `outcome_completeness` metadata for supplied outcomes such as
  Net Bill Through;
- explicit dictionary fields for `outcome_id`, `source_column`, `product`,
  `metric_key`, `metric`, `segment_dimension`, `segment`,
  `outcome_group_id`, `outcome_group_label`, `outcome_family_key`, and
  `group_aggregation`;
- canonical `OutcomeDefinition` fields where supplied, using the existing
  outcome registry and approval gates.

`standard-source-pack-v1` keeps its historical meaning. V1 dictionaries
remain loadable as legacy/incomplete semantic mappings, but the application
must not infer product, metric, breakdown, segment dimension, or grouping
from an `outcome_id`. V2 is the first contract that carries governed
outcome semantics explicitly.

Product, metric, breakdown (`segment_dimension`), and segment are separate
concepts. The canonical field supports at least:

```text
fh_customer_segment
dna_customer_relationship
dna_purchase_recipient
dna_activation_status
combined
custom
unspecified
```

Legacy outcomes migrate to `unspecified`, which requires review before newly
governed official use. The field is calculation-relevant and must survive
fit metadata and bundle round trips.

The semantic grouping registry is a distinct, versioned,
framework-independent `OutcomeGroupDefinition`. It identifies compatible
component outcomes for a business measure. It is not an
`OutcomeReconciliationGroup`, does not grant approval, and does not choose
fit treatment. Reconciliation remains an arithmetic source check, while
`components_joint`, `total_only`, `descriptive_only`, and `unconfigured`
remain analyst model-configuration choices.

DNA customer relationship, purchase recipient, and activation status are
separate dimensions. Purchase recipient must never be mapped to activation
status, and alternative DNA partitions must not be silently added together.
DNA halo remains explicit causal-graph/pathway configuration; an outcome
dictionary never creates a causal edge. Import may seed draft definitions
and groups, but never creates `OutcomeApproval` records.

NBT remains a supplied outcome. If present, completeness metadata binds to
the canonical definition and existing NBT completeness and approval gates
remain independently required. No billing reconstruction is introduced.

## Work package scope

The implementation follows the brief's sequential packages:

1. WP1 - canonical outcome semantics, grouping, validation, fingerprints,
   and legacy migration;
2. WP2 - Outcomes v2 parsing, source binding, canonical bundle semantics,
   and optional completeness metadata;
3. WP3 - persistence, fit-time identity, and staleness;
4. WP4 - Data Sources import and draft catalogue seeding;
5. WP5 - Model Structure group treatment;
6. WP6 - draw-level grouped totals and downstream reporting;
7. WP7 - DNA alternative partitions and multi-target halo regression;
8. WP8 - templates, realistic demo data, and end-to-end UX.

No package may silently replace `OutcomeDefinition`, infer groups from ID
names, make NBT the default, or move causal semantics into the dictionary.

## Affected modules

- `ancestry_mmm/core/outcomes.py`
- `ancestry_mmm/core/fingerprint.py`
- `ancestry_mmm/core/persistence.py`
- Outcomes source/template modules under `ancestry_mmm/data/`
- Data Sources and Model Structure pages
- Causal graph/pathway target presentation and regression tests

## Required tests

WP0 has no runtime change and therefore requires the authority conformance
suite only:

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

The later work packages own the parsing, grouping, posterior aggregation,
DNA, NBT, persistence, graph, UX, template, and regression tests required
by the implementation brief.

## Migration impact

None in WP0. No schema, model, persisted artefact, or application behaviour
changes in this authority registration. Later packages must preserve v1
and legacy bundle loading with explicit incomplete/`unspecified` semantics,
not guessed business meaning.

## Owner

Data Science / Platform engineering.

## Approval date

2026-08-14
