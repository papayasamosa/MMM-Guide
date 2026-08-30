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

Implemented (2026-08-19, Work Package 1 of the brief cited above):

- `core.named_events` provides the governed `NamedEventFamily`,
  `NamedEventOccurrence` and `EventResponseDefinition` records, the
  closed four-value temporal-treatment vocabulary, reference
  validation, version immutability and deterministic fingerprints;
- `application.event_service` provides the explicit adoption boundary
  from uploaded Context `events` rows (identity + factual dates +
  free-text display label only - market scope, source lineage and
  family link are analyst-supplied; nothing derives classification or
  treatment from `event_name`);
- the registry persists through the project bundle
  (`config/named_events.json` under `EVENT_REGISTRY_SCHEMA_VERSION`,
  manifest flag `named_event_registry`, quarantine-on-import via
  `core.persistence.resolve_imported_named_events`, future schema
  versions rejected) and has a review/adopt/edit UI on
  `pages/01_Data_Upload.py`.

Still not implemented (by design): event-relative feature
construction (requirement 5), any consumption of
`transformation_method_reference` by a model component, and every
statistical response method - those remain decision-required, see
"Explicitly excluded" below.

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

`core/named_events.py` (new), `application/event_service.py` (new),
`core/persistence.py` (`config/named_events.json` export/import,
`resolve_imported_named_events`, manifest flag),
`pages/01_Data_Upload.py` (review/adopt/edit UI),
`pages/09_Project_Export.py` (export payload and import restore),
`utils/session_state.py` (registry keys).

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_named_event_authority_reconciliation.py::TestNamedEventOverlayReconciled::test_req_event_001_indexed_and_classified_incomplete`
- `ancestry_mmm/tests/test_named_events.py::TestClosedTemporalVocabulary::test_closed_vocabulary_is_exactly_four_treatments`
- `ancestry_mmm/tests/test_named_events.py::TestFactualDatePreservation::test_occurrence_dates_round_trip_verbatim`
- `ancestry_mmm/tests/test_named_events.py::TestNoTextInference::test_family_classification_is_explicitly_supplied`
- `ancestry_mmm/tests/test_named_events.py::TestReferenceValidation::test_definition_must_reference_a_registered_family`
- `ancestry_mmm/tests/test_named_events.py::TestFingerprints::test_registry_fingerprint_changes_when_any_current_record_changes`
- `ancestry_mmm/tests/test_event_service.py::TestAdoptionBoundary::test_no_classification_or_treatment_is_derived`
- `ancestry_mmm/tests/test_event_service.py::TestRegistryImmutability::test_re_adopting_different_content_raises_never_mutates`
- `ancestry_mmm/tests/test_persistence.py::TestResolveImportedNamedEvents::test_factual_dates_survive_the_resolver_verbatim`
- `ancestry_mmm/tests/test_persistence.py::TestResolveImportedNamedEvents::test_future_schema_version_is_quarantined`
- `ancestry_mmm/tests/test_persistence.py::TestResolveImportedNamedEvents::test_bundle_without_registry_still_imports_with_no_warnings`
- `ancestry_mmm/tests/test_named_event_registry_apptest.py::test_adopting_a_row_registers_version_1_with_factual_dates`

## Migration impact

None for existing bundles: the registry is an optional additive bundle
file (`config/named_events.json`) with no project-bundle schema-version
bump, mirroring the experiment registry. Every older bundle imports
with an empty registry ("no registry yet") and no warnings. New
registry records are versioned and immutable.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp2_named_event_statistical_method_decision_package.md`.

## Owner

Modelling / Product

## Approval date

2026-08-19

## Addendum, 2026-08-30: event-family-to-treatment mapping approved (partially resolves an "Explicitly excluded" item)

The business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (Decision 12, "Different event types need
different timing patterns") supplies the qualitative mapping this
record's own "Explicitly excluded" list reserved ("the classification of
any concrete real-world event family"). This addendum records that
mapping; it does not rewrite the original record above, does not select
a response *structure* (decision dimension 1 in `docs/wp2_named_event_
statistical_method_decision_package.md` — S1/S2/S3/S4 remains open), and
does not supply any numeric lead/lag window length (decision dimension
5's actual values remain open).

**Approved family-to-treatment-value mapping**, using this record's
existing closed four-value vocabulary (§3):

| Event family | Examples | Approved temporal treatment |
|---|---|---|
| Gifting | Mother's Day, Father's Day, Valentine's Day, Christmas | `anticipatory` (demand may rise before the event; the model must be able to learn a pre-event effect) |
| Remembrance / commemorative | Remembrance Day, VE Day | `contemporaneous` or `post_event` (the event itself triggers interest; the main effect may occur in the event week and possibly after it) |
| Promotional / commercial | Black Friday | `post_event`, bounded to the actual promotion window (the commercial event or promotion period is the main treatment window; no automatic long pre-event effect unless the actual promotion starts earlier or the data support it — see below) |

This is a **type-level mapping approved once**, not a per-occurrence
choice — a specific real-world event (e.g. "Black Friday 2026") is
classified into one of these three families (a governed, explicit act
per this record's existing §2 "never inferred from free-text
`event_name`"), and the family's approved treatment above then applies,
still subject to this record's existing §4 requirement that a maximum
lead/lag *support* window is only support, never evidence that every
period inside it has a material effect, and subject to whatever response
structure (S1-S4) a future decision selects.

**Explicit non-goal, reaffirmed:** this addendum does not implement, and
does not approve, literal reverse adstock, and does not move any factual
event date — the named event date remains factual per this record's
existing §1 and §6, which this addendum does not relax. "Anticipatory"
demand for a gifting event is implemented, when a future decision
selects a response structure, as an event-time lead effect relative to
the unmoved factual date — never as a reversed decay of the media
adstock mechanism itself.

**Promotional events do not receive an automatic pre-event effect.** Per
Decision 12's explicit instruction, a promotional/commercial event's
treatment window is the actual promotion period, not an invented
lead window — if the real promotion starts before the named calendar
date (e.g. a "Black Friday" promotion that commercially begins the
preceding Monday), that earlier start must be represented via the
promotion's own governed start date/window (`core.promotions`,
distinct from the named-event occurrence per this record's existing §6
media/promotion separation), not by silently extending the named event's
own lead-support window.

**Still genuinely open**, exactly as `docs/wp2_named_event_statistical_
method_decision_package.md` already records: the response *structure*
(dimension 1: fixed governed profile vs. estimated kernel vs. regularised
basis vs. unconstrained dummies), the kernel/basis family (dimension 2),
priors/regularisation (dimension 3), pooling/heterogeneity (dimension 4),
the actual numeric lead/lag window *lengths* per family (the remainder of
dimension 5 — this addendum supplies only the treatment-*type* mapping,
not a number of weeks), and validation/planning-eligibility thresholds
(dimensions 6-7). None of these is chosen by this addendum.
