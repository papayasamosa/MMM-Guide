# REQ-DATAIN-001: Data Input Contract — Logical Source Domains and Cross-Market Activity Identity

## PRD source

User-supplied approval, in-session, 2026-08-11:

```text
I approve the Ancestry MMM Data Input Contract and Repository Alignment
Review as the approved source-input contract. The three required logical
domains are Outcomes, Activity and Media, and Context and External
Factors, with Experiment Evidence optional. pooling_group_id should be
used as the stable cross-market activity identity, without automatically
forcing pooling.
```

The underlying external document — "Ancestry MMM Data Input Contract and
Repository Alignment Review", dated 10 August 2026, status "Draft PRD
amendment for human review" at the time this record was created — is not
independently held by the repository or the coding agent that produced
this record beyond the summary supplied in the task-specific implementation
brief that introduced it. This record translates that summary, as
explicitly approved above, into repository authority. It does not
independently reinterpret the external document's full text (root
`AGENTS.md`: "Coding agents must not independently interpret ... the
external Ancestry MMM PRD").

The summarised proposal this record approves:

1. Three **required** logical source domains: Outcomes; Activity and
   Media; Context and External Factors. One **optional** logical domain:
   Experiment Evidence.
2. An arbitrary number of physical source files may exist beneath each
   logical domain (not one file per domain).
3. Market is a row/dimension within uploaded data, not inferred from a
   hidden file-naming convention.
4. `pooling_group_id`: a stable, governed cross-market activity identity,
   explicitly confirmed by the user **not** to automatically force
   parameter pooling merely by being present — pooling remains a separate,
   already-governed modelling choice (root `AGENTS.md`'s pooling
   invariants; `docs/decision_log.md`'s 2026-07-20/21 pooling decisions).
5. Separate model-input, spend, and response-unit semantics for an
   activity.
6. Paid, owned, and earned activity governed within the same activity
   domain.
7. Native-frequency input accepted without forcing the analyst to
   fabricate rows at a target modelling frequency.
8. Standard template downloads and end-to-end template-pack tests.

## Capability status

Not implemented. This record establishes the authority/vocabulary
contract only. It approves *what may be built*; it builds no code.
Dependent, separately-scoped implementation packages (this brief's Work
Package E1–E6) implement the domain objects, schema changes, template
pack, and UI against this record — not against the external document's
example schema literally (this record's approval is of the *decisions
above*, not a license to copy the external document's field names,
file formats, or example structures verbatim where they conflict with
this repository's existing conventions).

### What already exists today (do not duplicate)

- `core.coverage.SourceDefinition`/`SourceVersion`: a named, stable source
  identity plus immutable per-upload version capture (checksum, filename,
  size). Has no logical-domain field. A dependent requirement adds one
  rather than replacing this contract.
- `core.activities.ActivityDefinition`: already has `activity_ownership`
  (`paid`/`owned`/`earned`/`external_event`, item 6 above), `source`,
  `model_input_column` (item 5's model-input half). It has no
  `pooling_group_id` field, and no dedicated response-unit-mapping field
  distinct from `model_input_column` — `core.media_units`/
  `core.media_costs` already own cost/unit-mapping semantics separately;
  a dependent requirement must map onto those, not duplicate them
  (mirrors `REQ-COVERAGE-001`'s own "do not duplicate" precedent).
- `data.loader.load_file_with_source_version`/`pages/01_Data_Upload.py`:
  free-text `source_name` input (placeholder examples "media, outcomes,
  controls") with no logical-domain grouping, validation against the
  three required domains, or template download. A dependent requirement
  adds domain selection and templates on top; it does not replace the
  existing checksum/version-capture contract.
- `core.coverage.build_coverage_matrix_from_frame`: already computes an
  expected calendar from the joined frame's own observed dates, not from
  a per-source native-frequency declaration honoured at upload time (item
  7). `core.coverage.FrequencyMetadata` already captures
  `native_frequency`/`target_frequency` per variable but is metadata only
  (does not itself accept or convert native-frequency rows at upload).

## Requirement

### 1. Standing invariants (approved now)

- A source belongs to exactly one of the three required logical domains
  (Outcomes; Activity and Media; Context and External Factors), or the
  optional Experiment Evidence domain. A logical domain is not a physical
  file — any number of physical source files/versions may exist under one
  domain.
- Market is represented as a row-level dimension in uploaded data, not
  inferred from a source's file name or upload label.
- `pooling_group_id` is a stable identity a governed `ActivityDefinition`
  may declare, identifying "the same activity across markets" for later
  cross-market analysis/reporting purposes. **Its presence must never, by
  itself, force, imply, or default to parameter pooling** for that
  activity in any model — pooling remains governed exclusively by the
  model's own hierarchy configuration (existing pooling invariants;
  `core.market_specific_model`, `docs/market_hierarchy.md`). A dependent
  implementation must not read `pooling_group_id` anywhere in modelling
  code as an instruction to pool; it is descriptive/identity metadata
  only until (and unless) a separate, explicitly-approved modelling
  decision says otherwise.
- An activity's model-input semantics, spend semantics, and response-unit
  semantics are represented as distinct, explicitly-mapped fields — never
  inferred from one column serving double duty. Where existing
  `core.media_costs`/`core.media_units` registries already govern
  cost/unit mappings, a dependent requirement integrates with them rather
  than inventing a second, competing mapping surface.
- Paid, owned, and earned activity are governed within one activity
  domain — already satisfied by `core.activities.ActivityDefinition.
  activity_ownership`; a dependent requirement must not fork this into
  separate paid-only and organic-only domain objects.
- A source may be uploaded at its own native frequency without the
  analyst manually fabricating rows at a target modelling frequency to
  satisfy an upload-time validation rule. This is an *upload-time*
  invariant (accept the native-frequency shape as given); it does not by
  itself resolve *how* that native-frequency data is later aligned to a
  modelling calendar — that is `REQ-COVERAGE-001` S4 / `core.
  frequency_alignment`'s job (Work Package C/D), explicitly out of scope
  here.
- Standard, versioned template files exist for the required (and
  optional) logical domains, downloadable from the Data Upload page, and
  an end-to-end test proves a standard template pack can be uploaded,
  mapped, coverage-reviewed, prepared, exported, and re-imported without
  silently changing semantics.

### 2. Explicitly out of scope (not approved by this record)

- The external document's literal example schema (specific column names,
  file layouts) beyond the decisions in §1 above — a dependent
  implementation package designs the concrete representation against this
  repository's existing conventions.
- Any change to how pooling is actually configured or executed in model
  code — `pooling_group_id` is identity metadata only (§1).
- Any frequency-conversion method or canonical-calendar wiring — governed
  entirely by `REQ-COVERAGE-001` S4 and `core.frequency_alignment`, not
  by this record.
- Any change to `core.media_costs`/`core.media_units`'s own cost-mapping
  mathematics or schema beyond what integrating `pooling_group_id`/
  domain metadata requires.
- A migration that silently reclassifies an existing project's uploaded
  sources into the new logical-domain vocabulary — a dependent
  implementation must define an explicit, reviewable migration/defaulting
  rule for legacy projects, not infer one silently.

## Traces to

```text
User-supplied in-session approval, 2026-08-11
Ancestry MMM Data Input Contract and Repository Alignment Review (external,
  draft at time of reference; approved by the user as summarised above)
REQ-COVERAGE-001 (source/coverage identity this record extends, not
  replaces)
```

## Affected modules

- `docs/approved_requirements/REQ-DATAIN-001.md` (new)
- `docs/approved_requirements/index.json` (new entry)
- `docs/approved_requirements/README.md` (new `REQ-DATAIN-*` category)
- `docs/decision_log.md` (approval entry)

No `ancestry_mmm/` source, schema, or test-fixture behaviour changes as a
result of this record. Dependent, separately-scoped packages (Work
Package E1–E6) implement against it.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None. No existing schema, model, persisted artefact, or application
behaviour changes as a result of this record.

## Unresolved decisions

- The exact domain-object shape for a logical-source-domain field (which
  object owns it — `SourceDefinition`, a new object, or session
  configuration — and its persistence/migration representation) —
  deferred to the dependent implementation package (Work Package E1).
- The exact `pooling_group_id` field shape on `ActivityDefinition`
  (optional string, its validation rules, uniqueness scope) and its
  schema-version bump/migration — deferred to Work Package E3.
- The exact response-unit-mapping field(s) distinct from
  `model_input_column`, and how they integrate with `core.media_units` —
  deferred to Work Package E2.
- The exact template-pack file formats, column layouts, and download
  mechanism — deferred to Work Package E4.
- The exact legacy-project migration/defaulting rule for sources uploaded
  before logical domains existed — deferred to the dependent
  implementation package that adds the domain field.

## Owner

Data Science / Platform engineering (approved by the user in-session).

## Approval date

2026-08-11
