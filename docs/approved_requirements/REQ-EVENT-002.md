# REQ-EVENT-002: Governed Future Named-Event Replay in Sequential Scenario Planning

## PRD source

Ancestry MMM PRD, named-event focused overlay, reconciled by Work
Package 0 of `Media-Mix-Lab: Coding LLM Next Steps Post PR #297`
(2026-08-19). Source files (local traceability set, untracked and
never pushed):

- Part 8, Cross-Document Coherent v1.5 (`Focused v1.5 update:
  governed named-event scenario replay`; preserves v1.4 content):
  `Ancestry_MMM_PRD_Part_8_Coherent_v1_5_Governed_Named_Event_Scenario_Replay.md`,
  SHA-256 prefix `837858F9BCEF6AF0`
- Part 10, Cross-Document Coherent v1.6 (`Focused v1.6 update:
  governed named-event configuration and scenario replay UX`;
  preserves v1.5 content):
  `Ancestry_MMM_PRD_Part_10_Coherent_v1_6_Governed_Named_Event_UX.md`,
  SHA-256 prefix `0E93394F020BD04C`
- Part 11, Cross-Document Coherent v1.6 (`Focused v1.6 update:
  governed named-event service and API contracts`; preserves v1.5
  content):
  `Ancestry_MMM_PRD_Part_11_Coherent_v1_6_Governed_Named_Event_Service_and_API_Contracts.md`,
  SHA-256 prefix `BC1408608391EB1B`

Source-identity notes:

- The Part 8 label "v1.5" is shared with the structural
  intervention-curves focused update already reconciled by
  `REQ-SCCURVE-001`. The two sources are distinct focused updates
  distinguished by focused-update title, filename and content hash —
  neither supersedes the other, and neither changes Part 8's v1.4
  baseline for the other's topic.
- The named-event Part 10 v1.6 and Part 11 v1.6 are focused updates
  over that part's v1.5 content. The structural-causal Part 10 v1.8
  and Part 11 v1.7 already recorded in repository authority are
  neither downgraded nor erased by them.
- Part 8 does not define the statistical event-response kernel; Part 5
  defines source and canonical event contracts, Part 6 the model
  treatment, Part 7 validation and planning eligibility.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-19). Target-state contract only. Extends the
existing sequential planning contracts `REQ-STATE-001` and
`REQ-SCEN-001`–`REQ-SCEN-004`; the existing weekly sequential
simulator remains authoritative. Depends on `REQ-EVENT-001` for the
governed occurrence/family/response-definition identities it replays.
No statistical response method and no planning-eligibility threshold
is approved by this record.

## Capability status

Zero implementation. `REQ-EVENT-001`'s governed occurrence/family/
response-definition resources now exist (Work Package 1, 2026-08-19),
but the sequential simulator still replays media, baseline and
promotion structure only; there is no event-relative feature path in
`core.sequential_simulation` or `core.sequential_scenario_evaluation`
and no future event-calendar replay.

## Requirement

### 1. Future occurrence and response definition are separate governed inputs

A scenario references approved future named-event occurrences through
stable `event_family_id`, factual start and end dates, and the fitted
`event_response_definition_id`. Family classification and temporal
treatment are inherited from approved upstream artefacts — never
inferred from free-text names inside the planner.

### 2. Same approved semantics replayed, at model grain

`contemporaneous`, `anticipatory`, `post_event` and
`anticipatory_and_post_event` treatments are reproduced in the future
using the same approved deterministic basis construction and fitted
model semantics used historically. Replay runs at the model's approved
grain underneath the monthly planning interface. Negative
event-relative periods represent time before the event and are
generated from the future occurrence date without mutating that date.

### 3. Fixed external calendar dates are non-decision context

External calendar events are ordinary non-decision context unless a
separate approved business action (promotion timing, media spend,
operational capacity) is explicitly controllable. The optimiser must
not choose or move fixed calendar event dates. Scenario comparison may
hold the event calendar constant when comparing media plans.

### 4. Deliberate variation is an explicit sensitivity case

A user may deliberately vary a future occurrence or an approved
event-response assumption only through an explicit sensitivity
scenario that creates a new scenario version — never by silently
changing the fitted semantics. Sensitivity changes create new scenario
versions and participate in staleness.

### 5. Separation is maintained in replay

Named-event response remains separate from planned media, media
adstock, promotion, price and smooth seasonality during replay.
Anticipatory response is never implemented by running media adstock
backwards, and users are never asked to hand-create pre-event flags.

### 6. Planning eligibility is propagated, never granted

An event-response structure that is exploratory or not planning
eligible under Part 7 remains exploratory in Part 8 even if it
improves scenario prediction. This record grants no planning or
optimisation eligibility to any event-response structure.

### 7. Fingerprints participate in identity, staleness, export and restore

Event occurrence, family, response-definition and transformation
fingerprints must participate in scenario identity, stale-state
propagation, export and restore (`REQ-STALE-001`).

### 8. Future event calendar is carried separately from generic forecasts

The future event calendar (factual future occurrences plus the fitted
response-definition reference) is carried separately from ordinary
exogenous control forecasts (`REQ-FUTURE-001`'s boundary). Fixed known
event dates are not forecast, and the event calendar is not a
forecaster target.

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp2_named_event_statistical_method_decision_package.md`:

- the statistical event-response kernel/basis and its parameters;
- validation thresholds that decide planning eligibility (Part 7);
- which concrete event families are planning-eligible.

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record):
`core.sequential_simulation` / `core.sequential_scenario_evaluation`
(event-relative feature replay at model grain), `core.planning`
future-context (event calendar), `application.scenario_service`,
`pages/08_Scenario_Planner.py`, `core/persistence.py`,
`core/fingerprint.py`.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_named_event_authority_reconciliation.py::TestNamedEventOverlayReconciled::test_req_event_002_indexed_and_classified_incomplete`

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


## Addendum, 2026-08-30 (Phase C): statistical response method and family-specific windows resolved (Decision 12)

This record's own "Explicitly excluded" section tracked "the
statistical event-response kernel/basis and its parameters" and "which
concrete event families are planning-eligible" via `docs/wp2_named_
event_statistical_method_decision_package.md`. The user's 2026-08-29
brief, confirmed in-session 2026-08-30, explicitly delegates the
statistical-method/priors/pooling/window-selection portion of that
package to research and validation. This addendum records the
resulting resolution: full decision record, including the Work Package
2 synthetic evidence relied on, in
`docs/named_event_response_method_decision_record.md`; implementation
in the new `ancestry_mmm/core/named_event_response.py`.

**Resolved:** the event-response structure (S3, regularised cubic
B-spline basis with a shared HalfNormal(1.0) shrinkage prior - selected
over S1/S2/S4 per WP2's own recorded synthetic-recovery evidence, not
guessed); the kernel/basis family and its knot-placement formula
(generalised from WP2's fixed +/-4-week evidence testbed to an
arbitrary family-specific window, fixing a degenerate-knot edge case
for a single-sided window along the way); the pooling policy (unpooled
by default, gated fail-closed on an approved repeated-occurrence
threshold this record does not invent); and family-specific maximum
lead/lag windows for gifting (6-week anticipatory lead), remembrance
(2-week post-event lag), and promotional (bounded to the actual
promotion's own declared window) families - grounded in general
retail-seasonality research and explicitly disclosed as a starting
default, not an Ancestry-data-validated final business number.

**Still not resolved:** validation thresholds that decide planning
eligibility (Part 7) - the user's authorisation named "statistical
method, priors, pooling and window selection" specifically, not
accept/reject numeric thresholds; this remains open, per `docs/wp2_
named_event_statistical_method_decision_package.md`'s own unaffected
dimensions 6-7. No actual PyMC model-fitting integration accompanies
this addendum - `core.named_event_response` implements the
deterministic basis-construction and window-policy contract only, a
separate, materially statistical follow-up requiring its own
synthetic-recovery validation at these real family-specific windows
(WP2's own evidence used a generic testbed window, not these).
