# REQ-COVERAGE-001: Variable Coverage and Mixed-Frequency Data Authority

## PRD source

Task-specific implementation brief (2026-08-09), translating the focused
source:

```text
Ancestry MMM PRD Part 3
Cross-Document Coherent v1.6
Variable Coverage and Mixed Frequency
```

This is a **focused overlay/replacement for Part 3 only** — see
`docs/specification_authority.md`'s "Version history: focused Part 3 v1.6
overlay" table. It does not move any other PRD part to v1.6, and this
record does not independently reinterpret the external PRD text beyond
what the task-specific brief itself already translated.

## Capability status

**Status at approval (2026-08-09):** Not implemented. This record
establishes the authority/vocabulary contract only. It approves *what may
be built* and *how the vocabulary is defined*; it builds no code.
Dependent, separately-scoped packages implement the domain objects,
transformation contracts, UI, and (where an approved modelling contract
permits) engine changes against this record — not against the PRD text
directly. The "What already exists today (do not duplicate)" subsection
below describes the baseline as of this approval date; see the
2026-08-11 update immediately below for what has since been built on top
of it.

### Historical status as of 2026-08-11 (after PRs #151-#159)

This is a dated implementation snapshot, retained for traceability and
superseded by the later status sections below. At that point, dependent,
separately-scoped packages had delivered:

- `core.coverage`: `SourceDefinition`, `SourceVersion`, `FrequencyMetadata`,
  `DefinitionBreak`, `VariableCoverageRecord`, `VariableCoverageMatrix`,
  strict `schema_version` guards, and `build_coverage_matrix_from_frame`
  (generates a coverage matrix from a real joined frame, classifying every
  gap `unknown` until a human reclassifies it — never inferring
  `not_applicable`/`unavailable_source`/structural `observed_zero` from an
  absent value).
- `variable_coverage_records_fingerprint`/`VariableCoverageRecord.
  fit_relevant_fields`: a fit-relevant versus presentation-only coverage
  fingerprint, bound into model identity and project export/import.
- immutable source-version capture on upload (checksum, original filename,
  size, parsed-representation version; CSV/XLS/XLSX/XLSM/Parquet) — see
  `data.loader` and `compute_checksum`.
- explicit join-mode and join-loss/unmatched-key diagnostics —
  `data.pipeline.join_sources_with_diagnostics` (§4's join-diagnosability
  invariant). `join_sources` itself, and its `how="inner"` default, are
  unchanged, per this record's own "do not duplicate" note below.
- the Data Coverage review UI (`pages/15_Data_Coverage.py`): coverage-state
  review, treatment proposal/approval, and versioned matrix save.
- `core.market_data_capability.check_market_channel_capability`: a
  deterministic market x channel engine-capability report (§6 point 3),
  bound into model staleness and the pre-fit prior-predictive workflow.

At that historical point, the following were not yet implemented: execution
of any approved frequency-conversion method
(§4 — no method is approved by this record itself; see "Out of scope"
below), a canonical-calendar mixed-frequency alignment service, a
fit-consumed-variable capability report beyond market x channel (outcome
source columns, controls, promotions, and other compiled predictors), and
an official-use governance gate binding coverage/capability results to
policy-backed model approval (current results are informational only).
`FR-MOD-015` (§6) remains explicitly unresolved — no masking strategy,
missing-data likelihood, or per-market predictor-set restructuring is
approved.

### Historical status as of 2026-08-13 (after Work Package 6)

The official-preparation governance boundary is now implemented through
`core.frequency_alignment.assess_official_preparation` and the separate
official action on Model Configuration. It resolves an explicit governed
canonical calendar, checks the existing coverage contract, and evaluates
mixed-frequency requests against the conversion registry without changing a
DataFrame. The registry remains empty: no concrete method is approved or
executed, so mixed-frequency official preparation returns
`unsupported_no_approved_method` (or a more specific leakage/definition-break
blocker), while missing governance returns `decision_required`. The
exploratory Transform Pipeline remains available and is not an official
frequency-alignment path.

At that historical point, the following remained not implemented: execution of an approved
frequency-conversion method and the broader policy-backed approval gate
described above. The current WP2 native weekly path is intentionally limited
to already-canonical inputs and does not resolve mixed-frequency conversion.
See
`docs/decision_required_frequency_methods.md` for the exact open choices by
variable class.

### Status as of 2026-08-14 (after WP2 official preparation)

The official path now has a framework-independent canonical native-frequency
service in `core.official_preparation`. It uses an explicit governed weekly
calendar and an outer join over the union of governed source periods; it
preserves missingness and rejects exploratory fill/drop operations. The
exploratory Transform Pipeline still retains its explicit join modes and
missing-value operations, but it is not an official fallback.

The official capability report now covers every source-backed variable
consumed by the compiled proposal: included outcomes, media/model inputs,
global/product/segment/outcome controls, promotions, and Search predictors.
Fourier, trend, and deterministic pipeline terms are reported separately from
source coverage. Unresolved or missing coverage for a consumed variable, an
unsupported engine shape, or an unresolved frequency decision blocks the
official frame and fit; gaps on unconsumed variables do not. Calendar,
alignment, capability, and official-frame evidence are persisted and included
in model identity.

### Existing contracts and exploratory boundaries (do not duplicate)

- `data.pipeline.join_sources`: the exploratory source join remains
  available, including its explicit join modes and diagnostics. Official
  native preparation uses `core.official_preparation` and does not call the
  exploratory inner-join path.
- The generic Transform Pipeline missing-value operations
  (`zero`/`mean`/`median`/`ffill`/`interpolate`/`drop_rows`): free-form,
  column-agnostic, with no variable-class, coverage-state, or leakage
  awareness. Remains valid as an *exploratory* tool under this record (see
  §7); a dependent requirement must not delete it, only gate its use for
  *official* frequency alignment behind the contract this record defines.
- `data.loader`: CSV/XLS/XLSM/Parquet import into an in-memory `DataFrame`,
  with immutable source-version identity (checksum, original filename, size,
  and parsed-representation version) captured at upload.
- `core.market_config`, `core.fingerprint.fingerprint_model_spec`: the
  existing project-identity and fit-relevant-fingerprint mechanisms a
  dependent requirement's coverage/treatment metadata must integrate with,
  not duplicate.

This record's job is to give the v1.6 concepts below an unambiguous
identity and invariant set that dependent requirements build *from* —
never a competing one, and never a resolution of `FR-MOD-015` (§6).

## Requirement

### 1. Standing invariants (approved now)

The following are approved, binding invariants for every dependent
requirement and its implementation:

- Markets do not need identical variables.
- Markets do not need identical observed history.
- Never automatically truncate all markets to the narrowest common date
  window.
- Never automatically reduce all markets to the smallest common variable
  set.
- Missing is not zero.
- Unavailable source is not zero.
- Not applicable is not zero.
- Pre-launch may be structural zero only when the activity genuinely did
  not exist — never merely because a source lacks history.
- Monthly/quarterly/irregular series require variable-class-specific,
  leakage-safe treatment — never one default conversion method applied to
  every class.
- A source-definition or methodology break inside the model window must be
  made explicit, never silently interpolated through.
- Every candidate model must expose a variable coverage matrix before
  fitting.
- Coverage decisions must be versioned and portable (survive project
  export/import exactly).
- A partial-window variable retains explicit support limits — its
  unsupported history is not backfilled.
- An unsupported treatment request returns exploratory/unsupported status,
  never fabricated data or a forced estimate.

### 2. Canonical missingness-state vocabulary (approved now)

Every dependent requirement's coverage/treatment metadata must represent
state using exactly this vocabulary — never collapsed into a nullable
boolean or a single generic `missing` flag:

```text
observed_zero
missing_expected
not_applicable
unavailable_source
suppressed
estimated
modelled
unknown
```

A latent/modelled value (`estimated`/`modelled`) must never be stored or
displayed as though it were an observed source fact.

### 3. Data / source / coverage semantics (approved now)

- A source and its coverage metadata are distinct from a model's fitted
  data — coverage classification (§2) is metadata *about* a variable's
  history, never inferred after the fact from "the value happens to be 0
  or NaN."
- A dependent requirement must define an immutable source-version identity
  (at minimum: original filename, checksum, size, parsed-representation
  version) sufficient to reproduce a prepared dataset's provenance, without
  requiring original bytes be embedded in the portable project bundle if
  that is inappropriate for size/security reasons — a documented local
  artefact/reference contract is an acceptable alternative, provided it is
  explicit rather than silently treating the parsed `DataFrame` as the
  original file.
- A variable coverage matrix (variable × market × product/segment where
  applicable) must be a versioned, persisted artefact reviewable *before*
  model preparation — never surfaced only after fitting.

### 4. Frequency-transformation semantics (approved now)

- A frequency conversion is a versioned, typed decision distinct from a
  generic fill operation: source frequency, target frequency, method,
  parameters, market scope, effective period, publication/release timing
  where relevant, reconciliation rule, and support boundary.
- Variable class (e.g. flow/count, stock/level, rate/index,
  survey/measurement release, event/flag) determines which conversion
  methods are even eligible — a single default method must never be
  applied across classes.
- A historical transformation may only use information that was actually
  available as of the reconstructed period where a source has a
  publication lag or revision vintage — no forward-filling backward into
  pre-publication history.
- Interpolation must not cross a declared source-definition break unless
  an approved bridge treatment explicitly allows it.
- A join across sources of differing native frequency must not silently
  collapse to an inner-intersection window — join mode, unmatched-row
  policy, and resulting coverage loss must be explicit and diagnosable
  before the joined data is used officially.

### 5. UI / coverage-matrix behaviour (approved now)

- The coverage matrix (§3) must be reviewable before model preparation,
  distinguishing the §2 states visually — never merged into one generic
  "missing" indicator.
- Unresolved `unknown`/`missing_expected` coverage must not become
  official fit input silently — it must fail closed or remain visibly
  exploratory until an explicit treatment is approved for it.
- A coverage or treatment change that alters prepared-data semantics must
  change prepared-data/model identity (staling downstream fits/approvals
  through the existing fingerprint mechanism); a purely presentational
  metadata change must not.

### 6. Model-engine mathematics — explicitly not approved by this record

`FR-MOD-015` (market-specific/ragged predictor sets inside the
hierarchical model equations) is **not resolved here**. No masking
strategy, missing-data likelihood, zeroing convention, or separate
per-market coefficient treatment is approved by this record. A dependent
requirement may:

1. preserve a market-aware prepared-data representation (market support,
   period support, coverage state, per-predictor eligibility) without
   fabricating observed values for a market that lacks a variable;
2. compile the rectangular subset the current engine already validly
   supports;
3. return a deterministic engine-capability result — labelling the
   unsupported request exploratory/unsupported — for anything beyond that
   subset;
4. surface, as a report rather than a silent choice, the exact modelling
   decision required to implement `FR-MOD-015` fully (see the brief's
   Work Package 5, §10).

No dependent requirement may invent the statistical answer to close this
gap merely to keep an implementation sequence moving.

### 7. Relationship to existing exploratory tooling

The existing free-form Transform Pipeline fill operations remain valid for
exploratory/manual data repair. A dependent requirement must not delete
them; it must instead require coverage-state and method compatibility
(§4) before any such operation may produce *official* frequency-aligned
data, and must record every official transformation's version per §4.

## Out of scope (not approved by this record)

None of the following is invented or approved by *this* record. Each
remains available for a future, separately-approved requirement to
resolve — including a dependent requirement this record itself
anticipates (§4's approved bridge treatment, §6's modelling-contract
report) — this section blocks invention now, not approval later:

- Any specific imputation formula, interpolation kernel, or default fill
  method not named in §4.
- Any specific validation threshold, coverage-percentage cutoff, or
  approval rule.
- Any specific prior, causal direction, or mediator equation.
- Any Search-capacity equation (governed separately — see
  `REQ-SEARCH-001`).
- FX policy.
- Time-varying baseline process selection.
- Any future-variable-role assignment not already covered by root
  `AGENTS.md`.
- Any optimisation-objective change.
- `FR-MOD-015`'s model-engine mathematics (§6) — remains unresolved until
  a separately-approved modelling contract exists; not a permanent
  prohibition on ever resolving it.
- A new database-extract connector (a future connector feeding an approved
  `DataFrame`/source version through this same contract is in scope for a
  later, separately-approved record; inventing a database dependency now
  is not).

## Traces to

```text
FR-DAT-006
FR-DAT-010
FR-DAT-011
FR-QLT-010
FR-QLT-011
FR-QLT-012
FR-TRN-003
FR-TRN-004
FR-TRN-005
FR-TRN-013
FR-TRN-014
FR-TRN-015
FR-TRN-016
FR-TRN-017
FR-VAR-006
FR-MOD-015 (reserved — not resolved by this record; see §6)
Part 3 v1.6 acceptance scenario 26.2
```

This record does not independently derive what each `FR-*` ID requires
beyond the invariants, vocabulary, and scope separation in §1–§7 above,
which are exactly what the task-specific implementation brief supplied;
a dependent requirement citing one of these IDs for a specific
implementation detail must trace that detail back to this record's
explicit text, not to an independent reading of the external PRD.

## Affected modules

- `docs/specification_authority.md` (Part 3 v1.6 overlay version table)
- `docs/approved_requirements/REQ-COVERAGE-001.md` (new)
- `docs/approved_requirements/index.json` (new entry)
- `docs/approved_requirements/README.md` (new `REQ-COVERAGE-*` category)

No `ancestry_mmm/` source, schema, or test-fixture behaviour changes as a
result of this record.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_part3_v16_overlay_table_scopes_only_part_three`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_req_coverage_001_traces_to_matches_brief_fr_ids`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_req_coverage_001_missingness_states_match_canonical_vocabulary`

## Migration impact

None. No existing schema, model, persisted artefact, or application
behaviour changes as a result of this record.

## Unresolved decisions

- `FR-MOD-015`'s model-engine mathematics (§6) — deferred to a
  separately-approved modelling contract; the brief's Work Package 5 stops
  and reports the decision options rather than choosing one.
- §4's frequency-conversion method, per variable class — deferred to a
  separately-approved modelling/statistics contract; the brief's Work
  Package D produced a decision-support survey of candidate methods
  (`docs/frequency_conversion_method_options.md`) without selecting one,
  mirroring the FR-MOD-015 precedent above. `core.frequency_alignment`'s
  conversion-method registry (Work Package C, PR #162) remains empty
  until that decision is made.
- The exact domain-object shape for `SourceDefinition`/`SourceVersion`/
  `VariableCoverageRecord`/`VariableCoverageMatrix` (field types, storage
  location, persistence file layout) — deferred to the dependent
  data-contract implementation package; this record fixes the *vocabulary
  and invariants* those objects must satisfy (§1–§5), not their concrete
  representation. **Resolved in PR #151 (2026-08-09):** see `core.coverage`
  for the concrete shape.
- Whether/how an approved database-extract connector is added — explicitly
  deferred (see "Out of scope").
- Exact structural-zero governance mechanism (how a "genuine pre-launch"
  decision is recorded and by whom) — deferred to the dependent
  implementation package; §1's invariant ("pre-launch may be structural
  zero only when the activity genuinely did not exist") is binding
  regardless of which mechanism is chosen. **Resolved in PR #151
  (2026-08-09):** `core.coverage.CoverageSegment.structural_zero`, gated on
  a required non-empty `justification`.

## Work Package A update (2026-08-11)

This section records a documentation-only reconciliation PR, distinct from
the record's original 2026-08-09 approval (see "Affected modules"/
"Required tests"/"Migration impact" above, which describe that original
PR's own scope and remain historically accurate for it).

Additional affected modules:

- `docs/decision_log.md` (new entry recording this reconciliation)
- `ancestry_mmm/tests/test_outcome_approval.py` (new
  `TestAuthorityConsistency` tests below)
- `README.md` (workflow order and feature-list corrections)

Additional required tests:

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_req_coverage_001_gap_row_reflects_delivered_capability`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_req_coverage_001_named_in_implemented_section`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_req_coverage_001_record_states_dated_implementation_history`

No `ancestry_mmm/` source, schema, model, or persisted-artefact behaviour
changes as a result of this update either — documentation and tests only.

## Owner

Data Science / Platform engineering

## Approval date

2026-08-09
