# REQ-SEARCH-004: Governed Search Intent Taxonomy, Term/Query Mapping, and Parent-Child Activity Lineage

## PRD source

Ancestry MMM PRD Part 2 v1.5 §4.6/§4.6.1 and §26.3 items 11-13; Part 3
v1.13 `FR-SEA-001`-`FR-SEA-004` and §29 item 27-28; Part 4 v1.8 §11.2,
§11.3, §13.4; Part 5 v1.6 §11.2, §17.4, §17.5, §17.10, §17.11, `DD-009`;
Part 6 v1.11 §13.7, §15.1-§15.6; Part 7 v1.10 §16.6, §22.1-§22.5; Part 9
v1.7 §13.9-§13.11; Part 10 v1.8 §11.3, §16.9, §17.3, §18.4; Part 11 v1.8
§12.1, §16.16-§16.19, §16.23 — reconciled by Work Package 1 of
`Media-Mix-Lab Coding LLM Next Steps 2026-08-27`, continuing Work
Package 0's 2026-08-24 version-only reconciliation recorded in
`docs/specification_authority.md`'s "Version history: focused optional
Search granularity, Paid Search intent and SEO visibility overlay"
section.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-28). Target-state architecture contract only. It
extends `REQ-SEARCH-001`'s object-separation, versioning, persistence,
and validation pattern to a governed Search-intent taxonomy and raw
paid-term/organic-query mapping layer. It does not select any taxonomy
content, mapping-confidence/coverage threshold, or statistical treatment
of intent-group parameters — see
`docs/wp1_search_seo_granularity_decision_package.md`.

Depends on `REQ-SEARCH-001` (the seven governed Search objects this
taxonomy layer references, never replaces) and `REQ-GRAPH-001` (no new
graph node/edge role is required — see Requirement 5).

## Capability status

Zero implementation. `core.search_objects.SearchObjectDefinition` has no
`search_intent_group_id`, parent/child field, or taxonomy reference.
`core.activities.ActivityDefinition` has no `search_intent_group_id`
field despite Part 5 §11.2 listing it. No taxonomy, mapping, or
lineage record exists anywhere in this repository.

## Requirement

### 1. Governed `search_intent_group` taxonomy record

A versioned, governed record per Part 5 §17.4: `search_intent_group_id`,
`search_intent_group_name`, `parent_search_intent_group_id` (nullable),
`business_description`, `product_scope`, `brand_class` (closed
enum: `brand` | `generic_non_brand` | `mixed_or_ambiguous` |
`not_applicable`), `intent_type` (nullable), `cross_route_comparable_flag`,
`owner`, `approval_status`, `effective_period_start`/`effective_period_end`,
`supersedes_search_intent_group_id` (nullable), `schema_version`. Mirrors
`SearchObjectDefinition`/`CausalGraph`'s immutable-versioned-lineage
pattern — an edit is always a new version, never an in-place mutation.

### 2. Raw term/query mapping record

A versioned, governed record per Part 5 §17.5: `raw_term_type`,
`raw_term_value`, `normalized_term_value`, `match_type`, `search_route`,
`mapping_method`, `mapping_confidence`, `mapping_version`,
`mapping_status`. The raw source value is immutable; a changed mapping
creates a new mapping version, never an in-place edit.

### 3. Parent-child activity lineage

`ActivityDefinition` gains an optional `search_intent_group_id` field
(Part 5 §11.2, Part 11 §12.1), referenceable by both a Paid Search
activity and an organic Search activity for the same underlying intent
without collapsing their separate cost, delivery, or causal-effect
identity (Part 5 §17.10/§17.11 — this reuses the existing mediator-
designation pointer to `core.brand_search`'s treatment modes; no second
mediation mechanism is introduced).

### 4. Optionality and no forced common grain

Aggregate Search remains a fully valid, non-deficient configuration at
every market. No market may be required to supply a finer grain
(intent-group, raw term, or otherwise) merely because another market
supplies one (Part 3 v1.13 preamble; Part 2 §4.6.1; Part 10 §11.3's
explicit "must not flag absent keyword/query/intent/ranking/SEO data as
an error when aggregate Search is valid").

### 5. Cross-route taxonomy reuse without conflation

The same `search_intent_group_id` may be referenced by a Paid Search
activity and an organic Search activity representing the same consumer
intent (Part 4 v1.8 preamble: "shared intent identity across paid and
organic routes without collapsing distinct cost or causal objects").
Sharing a taxonomy reference never implies a shared `MediaInputSpec`,
`GovernedCostMapping`, or causal-graph node — those remain governed
per-object identities under `REQ-SEARCH-001` §1/§2. No new causal-graph
node or edge role is required for this record's scope.

### 6. No-fabrication validation contract

A dependent validator must reject, with a specific attributable reason
(mirroring `REQ-SEARCH-001` §14's "reject with a specific reason, never a
silent drop" contract), at minimum the seven behaviours Part 11 §16.23
names:

- inferring a missing child observation solely from a parent total;
- converting unavailable keyword/query/intent/ranking/visibility data
  into an observed zero;
- allocating parent spend to child intents by click share, impression
  share, platform-attributed conversion share, or posterior contribution
  as an automatic default;
- forcing every market to a common finest- or coarsest-available grain;
- collapsing a shared paid/organic intent group into a shared activity,
  shared cost object, or shared causal effect;
- labelling aggregate organic Search contribution as a separately
  identified SEO visibility effect;
- treating observed SEO ranking/visibility as an ordinary optimisation
  variable without a governed controllable-intervention contract (this
  last item is `REQ-SEO-001`'s scope; this record's validator must still
  reject it at the taxonomy/mapping layer if attempted there).

### 7. Versioning, persistence, staleness

Every object in this record carries `schema_version` and an immutable
version-history lineage (mirroring `REQ-SEARCH-001` §10); round-trips
through project export/import with the same quarantine-on-malformed
contract as `resolve_imported_search_objects` (§11); a changed taxonomy,
mapping, or lineage record stales every fit, curve, or scenario that
consumed it via the existing `search_object_fit_fingerprint`/
`core.fingerprint.fingerprint_model_spec` mechanism (Part 4 §11.2/§11.3),
never a second, parallel invalidation path.

## Out of scope (decision-required, not approved by this record)

See `docs/wp1_search_seo_granularity_decision_package.md`. In summary,
this record does not approve:

- the actual taxonomy content — which intent groups exist, their names,
  or their ownership (Part 5 `DD-020`, Part 3 §29 item 27);
- any mapping-confidence, mapping-coverage, sibling-correlation, or
  hierarchy-recovery threshold that would make an intent group
  separately reportable rather than a grouped fallback (Part 6
  `MD-008A`, Part 7 `VL-032`, Part 3 §29 item 28);
- any statistical/hierarchical estimation method or prior structure for
  intent-group parameters (Part 6 §13.7/§15.4-§15.6 describe a
  partial-pooling pattern as illustrative PRD guidance only, not approved
  here).

## Affected modules

- `ancestry_mmm/core/search_objects.py` (new taxonomy/mapping governed
  records)
- `ancestry_mmm/core/activities.py` (new optional
  `search_intent_group_id` field)
- `ancestry_mmm/core/persistence.py` (export/import round-trip,
  quarantine-on-malformed)
- `ancestry_mmm/core/fingerprint.py` (dependency-fingerprint extension)
- A future Search-taxonomy management UI surface (extension of
  `pages/10_Channel_Media_Units.py` or a new page), not created by this
  record

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_search_seo_granularity_authority_reconciliation.py::TestSearchSeoGranularityOverlayReconciled::test_req_search_004_indexed_and_classified_incomplete`
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

## Addendum, 2026-08-30: initial taxonomy content approved (resolves D3)

The business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (Decision 2, "Minimum Paid Search detail")
resolves `docs/wp1_search_seo_granularity_decision_package.md`'s **D3**
(initial governed Search intent taxonomy content and ownership),
previously fully open between candidates D3-A (adopt an existing
internal taxonomy verbatim) and D3-B (design a new MMM-specific
taxonomy). This addendum records the resolution; it does not rewrite the
original record above.

**Approved minimum taxonomy content.** Two top-level governed
`search_intent_group` records, per this record's existing §1 schema:

- `search_intent_group_name = "Brand"`, `brand_class = "brand"`
- `search_intent_group_name = "Non-Brand"`, `brand_class =
  "generic_non_brand"`

This is a D3-B outcome (a new, MMM-specific two-group taxonomy), chosen
because Decision 2 names Brand/Non-Brand directly rather than adopting
any existing media-buying campaign taxonomy, and because a two-group
split trivially satisfies §5's `cross_route_comparable_flag` requirement.
Owner: Modelling (taxonomy structure) / Product-Marketing (naming),
per the decision package's existing owner split.

**Platform (Google/Bing) is an orthogonal axis, not a taxonomy level.**
Decision 2's four minimum groups (Google Brand, Google Non-Brand, Bing
Brand, Bing Non-Brand) are the *cross* of the Brand/Non-Brand intent-group
axis above with a **platform** axis (Google, Bing) that this record's §1
schema does not currently carry — `core.search_objects.
SearchObjectDefinition` and `core.activities.ActivityDefinition` have no
governed platform field today (current Search granularity is free-text
channel names only, confirmed by repository audit). Adding a governed
`platform` field (or reusing an existing free-text field under a closed
enum) is **Phase B implementation work**, not approved by this addendum;
this addendum only records that platform and intent-group are two
independent dimensions of the same reporting hierarchy, so a future
schema change must not conflate them into one combined enum.

**Reporting roll-up hierarchy (resolves the reporting half of D3, and
Decision 4).** The required roll-up/drill-down hierarchy is: Total Paid
Search -> {Brand Search, Non-Brand Search} -> {Google Brand, Bing Brand}
under Brand Search, {Google Non-Brand, Bing Non-Brand} under Non-Brand
Search. Every parent total must be computed by summing its governed
children — the business must never manually add detailed categories to
obtain a parent total (Decision 4). This is a reporting-layer
requirement on top of the taxonomy content above; the actual roll-up
computation is Phase B implementation work.

**PMax/Demand Gen/YouTube confirmed excluded from Paid Search.** This
record's existing object-separation pattern (`REQ-SEARCH-001`) already
implies PMax, Demand Gen, and YouTube campaigns are not Paid Search
objects merely because they appear in SA360 operational data; this
addendum makes that explicit per Decision 2's instruction not to
classify them as PPC "simply because of the source system." No governed
object for PMax/Demand Gen/YouTube is created by this addendum — a
future decision may place some of them in a grouped "Other" reporting
category, but that decision has not been made (per Decision 2's own
text) and is not made here.

**D4 (deeper keyword/search-term Non-Brand groups) remains open**, per
Decision 2's own instruction that a data-support-gated deeper split
"is not permission to automatically create tiny groups." This addendum
records the *gating principle* only — a Non-Brand keyword/search-term
group may only be promoted to separately reportable once data volume,
active/non-zero weeks, variation, collinearity, and separate-
estimability evidence support it, reusing `REQ-VAL-001`'s existing
per-artefact threshold-policy-record mechanism (candidate D4-A) rather
than a new parallel mechanism — no concrete numeric threshold is
approved here, consistent with D4's own unresolved status. Where the
data are too weak, the higher-level Non-Brand grouping is retained and
the reason recorded, per Decision 2's explicit instruction.

This addendum is a contract-level record only; no `core`, `application`,
or `pages` code changes accompany it (Phase A discipline). It does not
resolve D1, D2, D5, D6, or D7 of the decision package, which remain open
as recorded in that package's own updated status section.

## Addendum, 2026-08-30 (Phase B): platform axis and reporting roll-up implemented

This addendum implements the two items the 2026-08-30 addendum above
named as approved-in-principle but not yet built: the governed platform
axis and the reporting roll-up computation.

**Governed `search_intent_group` content, now as code.**
`ancestry_mmm/core/search_intent_taxonomy.py` implements `SearchIntentGroup`
(this record's §1 schema) and the two approved top-level records,
`BRAND_SEARCH_INTENT_GROUP` and `NON_BRAND_SEARCH_INTENT_GROUP`
(`brand_class = "brand"` / `"generic_non_brand"` respectively), exposed
together as `APPROVED_MINIMUM_SEARCH_INTENT_GROUPS`. `parent_search_intent_group_id`
already supports a future group nesting under Non-Brand (D4) without a
schema change - deliberately not exercised by any built-in record yet,
since D4's evidence threshold remains open.

**Governed platform axis, kept orthogonal per the prior addendum's
instruction.** `ancestry_mmm/core/activities.py` gains two new optional
fields on `ActivityDefinition` (schema version bumped 4 -> 5):
`search_intent_group_id` (the field this record's §3 already named) and
`search_platform` (new - `SEARCH_PLATFORMS = ("google", "bing")`).
These are deliberately two separate fields, never combined into one enum
value (e.g. never a single `"google_brand"`), matching the prior
addendum's explicit instruction. `search_platform` is validated as a
closed vocabulary in `ActivityDefinition.__post_init__`; cross-checking
`search_intent_group_id` against a full taxonomy catalogue is
`core.search_intent_taxonomy.validate_activity_search_taxonomy`'s job,
since `ActivityDefinition` does not carry the taxonomy catalogue itself.

**A deliberate schema choice, not a business decision:** the pre-existing
free-text `ActivityDefinition.platform` field (used by every activity
type - TV, Social, CRM, etc.) is left untouched rather than repurposed
under a closed enum, since collapsing it to `{"google", "bing"}` would
reject every unrelated existing value. `search_platform` is a new,
narrowly-scoped field instead. This is an ordinary implementation
judgement call within this record's existing delegation, not a new
business decision.

**PMax/Demand Gen/YouTube exclusion, now enforced.**
`ActivityDefinition.__post_init__` and
`validate_activity_search_taxonomy` both reject an activity whose
`campaign_type` is `pmax`/`performance_max`/`demand_gen`/`youtube`
(case-insensitive) if it also carries `search_intent_group_id` or
`search_platform` - Decision 2's "do not classify them as PPC simply
because of the source system," enforced as a validation rule rather than
left as prose. A PMax-labelled activity with no taxonomy reference is
still perfectly valid; only the taxonomy fields are forbidden on it.

**Reporting roll-up hierarchy implemented, resolving the reporting half
of D3/Decision 4.** `roll_up_paid_search_reporting` computes every level
of Total Paid Search -> {Brand Search, Non-Brand Search} -> {Google
Brand, Bing Brand} / {Google Non-Brand, Bing Non-Brand} purely by summing
governed leaf cells - no level accepts a pre-supplied parent total,
satisfying Decision 4's "the business must never manually add detailed
categories to obtain a parent total." An unrecognised `(search_intent_group_id,
platform)` combination (e.g. a not-yet-approved deeper Non-Brand keyword
group) raises rather than being silently dropped or misattributed,
consistent with this record's §6 no-fabrication contract. A missing leaf
combination (ragged coverage, §2/REQ-SEARCH-005) contributes zero via
ordinary summation over an empty set, which ordinary roll-up arithmetic
already requires - this is not a new missingness policy.

**Fingerprint wiring.** Both new fields are added to
`REPORTING_TAXONOMY_FIELDS` (so `activity_reporting_fingerprint` changes
when the taxonomy classification changes, correctly invalidating grouped
reporting artefacts) and excluded from the hard
`activity_definitions_fingerprint`/`activity_fit_fingerprint` gates
(mirroring `pooling_group_id`'s existing precedent) - a pure taxonomy
relabelling must not force a model refit or invalidate a curve/scenario
that changed nothing fit-relevant.

**Not implemented by this addendum** (remains as scoped above/in the
decision package): D4's deeper Non-Brand keyword/search-term split and
its promotion threshold; any Search-taxonomy management UI surface;
`core.persistence` export/import quarantine wiring specific to
`SearchIntentGroup` (the dataclass's own `to_dict`/`from_dict` round-trip
correctly today; a dedicated persistence-layer quarantine path for
malformed taxonomy records, mirroring `resolve_imported_search_objects`,
is future work once a taxonomy management UI exists to produce untrusted
input for it).

### Affected modules (this addendum)

- `ancestry_mmm/core/search_intent_taxonomy.py` (new)
- `ancestry_mmm/core/activities.py` (`search_intent_group_id`,
  `search_platform` fields; schema v4 -> v5)

### Required tests (this addendum)

- `ancestry_mmm/tests/test_search_intent_taxonomy.py` (all tests)
- `ancestry_mmm/tests/test_activities.py::TestSearchTaxonomyFields` (all tests)
