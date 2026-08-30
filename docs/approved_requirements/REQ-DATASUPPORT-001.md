# REQ-DATASUPPORT-001: Evidence-Based Per-Channel Data-Support Classification

## PRD source

Business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (decision date 2026-08-29), Decision 17
("Determine minimum data support using PyMC guidance and diagnostics").

## Approval and traceability

Approved for implementation by the business-decision brief cited above.
Target-state consolidation contract only — no numeric threshold is
approved or implemented by this record. Reconciles a genuine gap:
`docs/specification_authority.md` records no approved requirement for a
consolidated per-channel data-support classification, distinct from
`REQ-COVERAGE-001`'s market×channel *capability* report and distinct
from `FR-MOD-015`'s still-unresolved ragged-predictor-set question.

## Capability status

Real diagnostic capability already exists, split across three
unconsolidated modules, confirmed by repository audit:

- `core.prefit_identifiability` already provides a four-tier
  `_channel_support_status()` classification (`strong`/`moderate`/
  `weak`/`very_weak`), finer-grained than this decision's own three-state
  ask, and a `SupportThresholds` dataclass whose fields already
  deliberately default to `None` — the analyst explicitly prohibited
  inventing a numeric threshold while current UK activity data is under
  separate review (Work Package 2.11);
- `core.coverage` provides the canonical missingness-state vocabulary and
  `VariableCoverageMatrix`;
- `core.market_data_capability.check_market_channel_capability` provides
  a market×channel engine-capability report (`REQ-COVERAGE-001`);
- collinearity assessment exists separately again in `core.
  identification_diagnostics`.

No single governed record consolidates these into one per-channel
classification decision, and no record approves the concrete evidence
weighting or thresholds Decision 17 itself declines to invent.

## Requirement (target state — not yet approved for implementation)

### 1. A consolidated per-channel data-support classification

A channel's data support for separate coefficient estimation must be
classified into one of three practical states — **sufficient to attempt
estimation**, **weak/support-limited**, or **not sufficient for a
separate coefficient** — drawing on evidence from all of the following
dimensions, per Decision 17's own list, wherever relevant to the channel
and available in the data:

```text
total observed weeks
non-zero / active weeks
number of separate activity periods
spend/exposure variation
long runs of zeros
missingness
collinearity with other channels
correlation with trend/seasonality
market coverage
segment coverage
changes in scale
ability to identify adstock/saturation parameters
```

This is a consolidation of evidence already computed (in part) by
`core.prefit_identifiability`, `core.coverage`, and `core.
identification_diagnostics` into one governed classification result —
not a fourth, independently-computed diagnostic system.

### 2. No universal numeric rule

Per Decision 17's own explicit instruction, this record does not assume
a universal rule (such as "N weeks means a channel is valid") unless
evidence actually supports it for the specific data/model context. Any
concrete threshold must be documented with the evidence used to choose
it, mirroring `REQ-VAL-001`'s existing "no universal production
threshold, a per-artefact `Threshold policy record`" principle.

### 3. Governed responses to weak support, never silent

Where support is classified weak or insufficient, the governed response
must be one of the following, explicitly recorded — never a silent drop
and never a precise ROI/attribution reported for a channel the model
cannot identify:

- grouping the activity into a higher-level channel;
- stronger regularisation;
- partial pooling where statistically justified;
- excluding the channel from separate estimation while retaining it in a
  transparent aggregate.

### 4. Warnings and blocking rules are diagnostics-backed

A warning or a block on official use of a channel's estimate must cite
the specific evidence dimension(s) that triggered it, never an
unexplained categorical status.

## Explicitly excluded (decision-required, not approved by this record)

- The concrete numeric threshold for every evidence dimension above
  (minimum weeks, minimum active-week fraction, maximum acceptable
  collinearity, etc.) — an evidence-gathering exercise this record does
  not perform, mirroring Work Package 2.11's own explicit deferral while
  current UK activity data is under review.
- The exact weighting or combination rule across dimensions when they
  disagree (e.g. adequate weeks but severe collinearity) — not decided by
  this record.
- Which of `core.prefit_identifiability`'s existing four-tier states maps
  onto which of this record's three practical states, and the precise
  module/function consolidation architecture — Phase B/C implementation
  work, not decided here.
- Whether `REQ-COVERAGE-001`'s market×channel capability report and this
  record's per-channel classification become one artefact or two
  cross-referenced artefacts.

A new decision package should record the evidence-gathering exercise and
candidate consolidation architectures before implementation, mirroring
`docs/wp2_8_missing_sampler_configuration_decision_package_20260825.md`
and `docs/wp2_11_hierarchy_decision_package_20260826.md`'s existing
"gather real evidence before deciding a threshold" discipline.

## Affected modules (target — not yet touched)

- `ancestry_mmm/core/prefit_identifiability.py` (read-only reference —
  the most complete existing implementation, not itself modified by this
  record)
- `ancestry_mmm/core/coverage.py`, `ancestry_mmm/core/market_data_
  capability.py`, `ancestry_mmm/core/identification_diagnostics.py`
  (read-only references — the other existing partial-coverage modules)
- A future consolidation module (module TBD, not created by this record)
- `docs/approved_requirements/REQ-DATASUPPORT-001.md` (this record)
- `docs/approved_requirements/index.json` (new entry)

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_req_datasupport_001.py::test_three_state_classification_named_and_no_threshold_invented`
- `ancestry_mmm/tests/test_req_datasupport_001.py::test_all_twelve_evidence_dimensions_named`
- `ancestry_mmm/tests/test_req_datasupport_001.py::test_req_datasupport_001_indexed`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, to be tracked by a future
decision package before Phase B/C implementation.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-30
