# REQ-NBT-003: GSA / Net Bill Through event-level derivation reference implementation

## PRD source

Business-decision brief "Post-UI/UX Implementation Instructions: Approved
Business Decisions" (decision date 2026-08-29), Decision 1 ("Family
History outcome definitions"), Phase B implementation ("GSA and Net Bill
Through outcome support... wiring").

## Approval and traceability

Approved for implementation by the business-decision brief cited above.
Depends on `REQ-OUT-001`, `REQ-OUT-003` (48-month LTR horizon, 120-day DNA
Cross-sell window, GSA/NBT non-aliasing), `REQ-NBT-001`, and `REQ-NBT-002`
(supplied-NBT conditional use and the current UK historical test's
authority), which this record extends rather than replaces.

## Governance boundary reaffirmed by this record

This record does **not** authorise the MMM application to reconstruct
customer-level billing events, payment maturity, or subscription history
by default. That prohibition is already established and is unchanged:

- `ancestry_mmm/core/net_billthrough.py`'s own module docstring: "Net
  bill-through is an input KPI, not a transformation performed by the MMM.
  This module deliberately contains no signup, billing, cancellation,
  refund, offer or maturity-estimation logic."
- `REQ-NBT-002`: "the MMM does not reconstruct customer-level maturity when
  the authoritative feed satisfies this contract... Modelling code must
  not invent customer-level exclusion logic."
- `docs/PRD/Ancestry_MMM_PRD_Part_5_...md` ("Net Bill Through working data
  contract"): "The MMM application must ingest and validate the supplied
  outcome. It must not reconstruct customer-level billing events, payment
  maturity or subscription history by default. A separate customer-level
  maturity use case may be introduced only through an approved requirement
  and privacy review."

A repository-wide audit performed for this Phase B pass confirmed **no
raw, event-level (one-row-per-subscriber) Family History data shape
exists anywhere** in this repository's ingestion code, data contracts,
schemas, or sample data — every FH data shape in the application is
pre-aggregated to `week x market x segment`. There is therefore no
existing default path this record could wire an event-level computation
into even if that were desired, and this record does not attempt to.

## Requirement

### 1. A tested reference implementation of Decision 1's governed rules

`ancestry_mmm/core/fh_subscription_events.py` implements Decision 1's
exact governed business rules as pure functions over a well-specified
*synthetic* input shape (`FhSubscriptionEvent`) that this record defines,
since no raw event-level shape exists to adapt to:

- GSA: a hard offer is counted the same day as signup; a free trial is
  counted on the date it successfully bills through; a trial that never
  bills through is never a GSA. Refund status does not affect GSA (it is
  a gross count).
- Net Bill Through: starts from the population that eventually became a
  GSA; a successful free trial's date is moved back to the original
  signup date; a hard offer's date already aligns; a refunded subscription
  is excluded entirely (this is what makes it "net").
- Segment: New / Winback / DNA Cross-sell only, never a fourth. A
  source-supplied segment classification is always authoritative and is
  never independently re-derived. Derivation from raw dates (used only
  when genuinely needed) applies the approved 120-day DNA Cross-sell
  window (`REQ-OUT-003` §2) and fails closed (raises) rather than
  guessing when the required fields are missing or ambiguous.

### 2. Explicitly not wired into any default path

Nothing in `data.preprocessor`, `core.net_billthrough`'s supplied-feed
validation, or any other default ingestion/model-training path imports
`core.fh_subscription_events`. This module exists for two purposes only:
(a) a precise, tested reference implementation ready to be wired into a
*future* approved event-level ingestion path, if and when one is
authorised through its own approved requirement and privacy review per
the PRD passage above; and (b) an optional, out-of-band reconciliation/QA
utility an analyst may run manually against a raw extract to sanity-check
a supplied aggregate GSA/NBT feed — never an automatic replacement for
`core.net_billthrough`'s supplied-feed validation.

### 3. 48-month FH LTR horizon wired into the valuation input contract

`ancestry_mmm/core/outcome_valuation.py`'s `WeeklyOutcomeValuationRecord`
now carries an explicit `horizon_months` field. For
`valuation_kind == VALUATION_KIND_FH_LTR`, construction fails closed
(raises `ValueError`) unless `horizon_months == FH_LTR_HORIZON_MONTHS`
(48, per `REQ-OUT-003` §1) — a missing, blank, or stale (a different,
incorrect duration) horizon blocks the record rather than being silently
accepted and later assumed correct by a downstream value/ROI calculation
(`REQ-OUT-003` §6).
`horizon_months` is not a meaningful concept for
`VALUATION_KIND_DNA_REVENUE` and must be left `None` for those records.
`ancestry_mmm/pages/07_Results_Curve_Bank.py`'s outcome-valuation
catalogue editor applies this horizon automatically based on the row's
valuation kind — it is not an analyst-typed field, so it can never be
mistyped or silently omitted.

### 4. GSA and Net Bill Through remain independently computable and never aliased

`compute_gsa_date` and `compute_net_billthrough_date` are independent
functions over the same event; a `FhComputedOutcome` carries both dates
side by side, never collapsed into one. This is a computation-layer
reaffirmation of `REQ-OUT-001`/`REQ-OUT-003`'s existing prohibition on
GSA/NBT aliasing, not a new decision.

## Out of scope (not approved by this record)

- Any change to `core.net_billthrough`'s supplied-feed validation, or to
  the current UK historical test's authority (`REQ-NBT-002`'s scope is
  unchanged).
- Wiring `core.fh_subscription_events` into any default ingestion or
  model-training path — that remains blocked pending a separate approved
  requirement and privacy review, per the PRD passage cited above.
- Any change to how the Scenario Planner's forward `ScenarioValueAssumptions`
  (WP2G, `REQ-ECON-003` Requirement 5) collects FH LTR assumptions — those
  remain analyst-declared future numbers with no historical pre-fill, per
  Decision 14's own separately-scoped reconciliation task.

## Affected modules

- `ancestry_mmm/core/fh_subscription_events.py` (new)
- `ancestry_mmm/core/outcomes.py` (new governed constants:
  `FH_LTR_HORIZON_MONTHS`, `DNA_CROSS_SELL_WINDOW_DAYS`, `FH_SEGMENT_*`)
- `ancestry_mmm/core/outcome_valuation.py` (`horizon_months` field)
- `ancestry_mmm/pages/07_Results_Curve_Bank.py` (automatic horizon
  application in the valuation catalogue editor)

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestGsaDate::test_hard_offer_counted_same_day_as_signup`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestGsaDate::test_successful_free_trial_counted_on_later_gsa_date`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestGsaDate::test_unsuccessful_trial_excluded_from_gsa`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestNetBillthroughDate::test_successful_free_trial_pulled_back_to_signup_date`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestNetBillthroughDate::test_refunded_subscriber_excluded_from_nbt`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestSegmentDerivation::test_new_winback_and_dna_cross_sell_remain_distinct`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestSegmentDerivation::test_dna_cross_sell_derivation_uses_120_day_window`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestSegmentDerivation::test_derivation_fails_closed_when_ambiguous`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestComputeFhOutcomes::test_gsa_and_nbt_cannot_be_silently_swapped`
- `ancestry_mmm/tests/test_fh_subscription_events.py::TestFhLtrHorizon::test_48_month_horizon_constant`
- `ancestry_mmm/tests/test_outcome_valuation.py::TestRecordConstruction::test_fh_ltr_record_requires_48_month_horizon`
- `ancestry_mmm/tests/test_outcome_valuation.py::TestRecordConstruction::test_fh_ltr_record_rejects_a_different_stale_horizon`
- `ancestry_mmm/tests/test_outcome_valuation.py::TestRecordConstruction::test_dna_revenue_record_must_not_carry_a_horizon`

## Migration impact

`WeeklyOutcomeValuationRecord` gained a new field (`horizon_months`,
default `None`) that is now validated for `VALUATION_KIND_FH_LTR` records.
Existing FH LTR record constructions (test fixtures, and
`07_Results_Curve_Bank.py`'s catalogue editor) were updated to supply
`horizon_months=48` (or have it applied automatically); no other
persisted-bundle migration is needed since this repository has zero
production `WeeklyOutcomeValuationRecord` data in use yet (`REQ-ECON-002`'s
capability status: zero implementation prior to this record).

## Unresolved decisions

None specific to this record's own scope. Wiring an approved event-level
ingestion path (if one is ever authorised) and the segment-derivation
logic's integration into any such path remain future, separately-scoped
work.

## Owner

Product / Analytics (business rule), Modelling / Platform engineering
(implementation)

## Approval date

2026-08-30
