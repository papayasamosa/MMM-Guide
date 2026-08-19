# REQ-EVENT-001: Governed Named-Event Occurrence, Family and Response-Definition Data Contracts

## PRD source

Ancestry MMM PRD, named-event focused overlay, reconciled by Work
Package 0 of `Media-Mix-Lab: Coding LLM Next Steps Post PR #297`
(2026-08-19). Source files (local traceability set, untracked and
never pushed):

- Part 3, Cross-Document Coherent v1.11 (`Focused v1.11 update:
  governed named-event temporal response`; cumulative — retains the
  v1.10, v1.9 and v1.8 content in the same file):
  `Ancestry_MMM_PRD_Part_3_Coherent_v1_11_Governed_Named_Event_Functional_Coherence.md`,
  SHA-256 prefix `1A27675D69187E99`
- Part 5, Cross-Document Coherent v1.5 (`Focused v1.5 update:
  governed named-event occurrence and temporal-response data
  contracts`; preserves the v1.4 canonical data architecture):
  `Ancestry_MMM_PRD_Part_5_Coherent_v1_5_Governed_Named_Event_Data_Contracts.md`,
  SHA-256 prefix `660F14BCA251C87F`
- Part 11, Cross-Document Coherent v1.6 (`Focused v1.6 update:
  governed named-event service and API contracts`; preserves v1.5
  content):
  `Ancestry_MMM_PRD_Part_11_Coherent_v1_6_Governed_Named_Event_Service_and_API_Contracts.md`,
  SHA-256 prefix `BC1408608391EB1B`

Source-identity notes this record makes part of repository authority:

- The label "Part 8 v1.5" now denotes **two distinct focused
  updates** of Part 8 that each preserve v1.4 content: the structural
  intervention-curves overlay already reconciled by `REQ-SCCURVE-001`,
  and the governed named-event scenario-replay overlay reconciled by
  `REQ-EVENT-002`. They are distinguished by focused-update title,
  filename and content hash, never by part+version alone.
- Part 9 v1.6 Final (`964EEB444DD4663D`) contains **no** dedicated
  named-event reporting contract. None is assumed or invented here.
- Part 5 v1.5 is now supplied locally. Part 5 v1.6 (still referenced
  by Part 4 v1.6 and retained content in Part 6 v1.9) remains absent;
  this record does not assume its content.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-19). Target-state contract only. Extends the
existing optional Context `events` table groundwork inside the
`REQ-DATAIN-001` source-domain contract — it does **not** create a new
logical source domain and does not change the three-required-domains
source contract. Applies `REQ-STALE-001`'s staleness semantics to the
new resources. No statistical response method is approved by this
record.

## Capability status

Zero governed named-event resource set exists. The only current
implementation is raw-source groundwork: the optional Context
`events` table (`ancestry_mmm/data/templates.py`) carrying only
`event_id`, `event_name`, `start_date`, `end_date`, retained by
`ancestry_mmm/data/source_inventory.py` as "irregular events". There
is no event-family identity, no event-response definition, no governed
classification, and no event-relative feature construction.

## Requirement

### 1. Factual occurrence identity and dates

An individual event occurrence has a stable `event_id`, factual start
and end dates, source lineage and market scope. The factual source
date/interval must never be shifted earlier (or later) to represent
pre-event or post-event purchasing. Pre/post-event response is created
through a governed, versioned event-response definition and
transformation, never by mutating the occurrence.

### 2. Governed family identity, never text inference

Repeated occurrences of the same conceptual occasion may share a
stable `event_family_id` while each occurrence retains its own
`event_id`. Event-family classification and temporal treatment are
governed and must never be inferred solely from free-text
`event_name`. The platform must not automatically classify an event
as gifting, commercial, holiday or cultural from its label, and must
not assume an anticipatory treatment for Mother's Day, Father's Day,
Christmas or any other family.

### 3. Closed temporal-treatment vocabulary

An approved event-response definition declares exactly one temporal
treatment from the closed vocabulary:

```text
contemporaneous
anticipatory
post_event
anticipatory_and_post_event
```

No other treatment labels may be introduced without a separately
approved requirement change.

### 4. Response-definition identity, version, scope and support

An `event_response_definition` has a stable identity and version, the
declared temporal treatment, explicit **maximum lead and lag support**
(a permitted window is support only, never evidence that every period
inside it has a material effect), market/product/outcome scope, and a
versioned transformation-method reference for deterministic
event-relative feature construction. Fitted event-response weights or
posterior parameters are separate model artefacts governed by Part 6 —
never conflated with the occurrence or the definition.

### 5. Deterministic event-relative construction from the factual occurrence

The prepared modelling layer generates deterministic relative-time or
basis features from the factual occurrence date. Negative
event-relative periods (time before the event) are generated from the
future/historical occurrence date without mutating that date.

### 6. Separation from promotion, price, media, adstock and seasonality

Named-event response must remain distinguishable from promotion
treatment, price, media activity, media adstock and smooth (Fourier)
seasonality where those mechanisms overlap. Anticipatory event
response is an event lead/response mechanism, never reverse media
adstock and never a manufactured pre-event flag substituted for the
fitted treatment.

### 7. Analytical event versus application domain event

A named business/calendar event (analytical resource with factual
occurrence and optional governed temporal response) and an application
domain event (software message such as `model_run.completed`) use
different resource types, schemas and identifiers. A named calendar
event must never be represented only as an outbox/domain-event
message, and domain events announce named-event resource changes
without becoming the analytical source of truth.

### 8. Staleness through the normal dependency graph

Changing an event occurrence, family mapping, event-response
definition, temporal support or transformation version must stale the
affected prepared data, model fits, validation records and downstream
planning/reporting artefacts through the normal dependency graph
(`REQ-STALE-001`), never silently.

### 9. Persistence, export, restore and fail-closed future schemas

The event family, occurrence and event-response-definition resources
must persist through the project bundle with schema versioning,
export/import round trips, source lineage, and fail-closed handling of
future schema versions, following the existing governed-resource
patterns (e.g. `REQ-SEARCH-001`, `REQ-EXPMODE-001`).

### 10. Governance separation is unchanged

A named-event response being fitted in the model, visible in analyst
attribution, approved for headline reporting, eligible for planning,
or eligible for optimisation are separate statuses. None of the later
statuses is granted by this record or by the data contracts it
approves.

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp2_named_event_statistical_method_decision_package.md`. In
summary, this record does not approve:

- a kernel family or basis family for the event-response
  transformation;
- fixed versus estimated versus partially pooled response structure;
- priors or regularisation strength for estimated structures;
- pooling or heterogeneity (market/product/outcome) choices;
- family-specific lead/lag support values;
- validation thresholds for recurrence support, timing sensitivity or
  separation;
- planning-eligibility or optimisation-eligibility thresholds;
- the classification of any concrete real-world event family (the
  mechanism is required; no family is pre-classified by this record).

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record): the optional Context `events`
contract in `data/templates.py`/`data/source_inventory.py`/`data/
pipeline.py`; a governed event-family/occurrence/response-definition
registry in `core/`; `core/persistence.py` (bundle schema, export/
import); `core/fingerprint.py` (staleness participation);
`application/validation_service.py`; `pages/01_Data_Upload.py` and
related review/edit UI.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_named_event_authority_reconciliation.py::TestNamedEventOverlayReconciled::test_req_event_001_indexed_and_classified_incomplete`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp2_named_event_statistical_method_decision_package.md`.

## Owner

Modelling / Product

## Approval date

2026-08-19
