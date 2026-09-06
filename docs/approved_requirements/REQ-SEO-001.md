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
cited above (2026-08-28). The current implementation covers the governed
**data and provenance shape** of observed SEO visibility/ranking values, as
objects distinct from —
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

Partial implementation. `core.seo_visibility` provides the approved
positional-visibility metric, provenance-aware observations, raw or
aggregated upload handling, explicit SEO groups, group-specific masks and
windows, persisted standardisation, one fitted term per selected group, and
diagnostic-only clicks. A separate metric-definition registry and any
controllable SEO intervention remain unimplemented and deferred.

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
- `ancestry_mmm/tests/test_search_seo_granularity_authority_reconciliation.py::TestSearchSeoGranularityOverlayReconciled::test_req_seo_001_records_approved_fit_role_and_open_estimand_direction`

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

## Implementation update, 2026-09-04

The approved positional/visibility metric and mediator/capture-efficiency
boundary are implemented in `core.seo_visibility`, including provenance-aware
raw or aggregated observations, explicit Brand/Non-Brand groups, row-aligned
window masks, persisted standardisation, and grouped model coefficients. SEO
remains distinct from organic Search capture, outside spend CPA/ROI, and
non-controllable until separately approved.

## Addendum, 2026-08-30: metric type, causal role, and cost policy approved (resolves D1, D2; confirms §7/§8 audit clean)

The business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (Decisions 5, 6, 7, and 8) resolves several
of this record's previously-open items. This addendum records the
resolutions; it does not rewrite the original record above, and it does
not itself implement anything (Phase A discipline — governance/contract
only).

### Decision 5: primary SEO metric type is positional/visibility-based

Resolves this record's "Out of scope" bullet 1 ("which SEO/ranking
metric(s) are used") at the **type** level only: the primary SEO exposure
is an **organic search position / positional-visibility** measure, not
raw organic clicks. This directly answers the business question the
brief poses — "does better organic search ranking lead to more sales or
sign-ups?" — which a clicks-based exposure cannot answer on its own,
since clicks are themselves a downstream consequence of both ranking and
unrelated demand.

The **exact formula** (aggregation across queries/pages, impression
weighting, a visibility transformation of raw average position) is
listed in the governing instructions §4 as a research-first item and is
explicitly **not** decided by this addendum — it is Phase B work,
requiring review of the real GSC fields available, official Google
Search Console definitions, and relevant SEO/MMM research, with a
decision record of the options considered before implementation.
Organic clicks and impressions remain retained as supporting diagnostics
and potential pathway variables, per this record's existing §3 causal
separation from organic Search capture — this addendum does not change
that.

### Decision 6: causal role approved as `mediator_or_capture_efficiency_state` (resolves D1 -> D1-B)

This record's §5 `causal_role` field, previously an explicit
`not_yet_approved` sentinel, is approved to the value
**`mediator_or_capture_efficiency_state`** (one of Part 6 §15.8's two
non-diagnostic candidates), for the causal story: SEO work -> better
ranking/visibility -> more organic traffic -> more sign-ups/sales. Per
Part 6 §15.10 (already part of this record's schema), this role is
**estimand-specific per use**, not a single global setting — a future
use must still separately state whether visibility is upstream,
downstream, or outside the effect being estimated for that use, and must
still clear the identification/refutation evidence Part 7 §22.7/`VL-034`
requires before any resulting effect reaches reporting. This addendum
approves the *role type*, not any specific use's identification
evidence.

**Governing causal-architecture principle (Decision 6's own explicit
caution, recorded here as a binding constraint on Phase B/C
implementation):** a future causal design must not place both positional
visibility (the cause) and organic clicks (a likely downstream mediator)
into one flat regression as unrelated controls, since that risks
controlling away the very SEO effect being estimated. Positional
visibility represents the SEO exposure; organic clicks/traffic may be
used as a diagnostic or as an explicit, structurally-represented
mediator only if the causal-graph architecture (`REQ-GRAPH-001`) supports
that mediation explicitly — never as an ordinary flat control alongside
the exposure. Any Phase B/C implementation must state plainly, in its own
documentation, what the reported SEO contribution means under the chosen
design.

### Decision 7: no spend-based SEO ROI (resolves D2 -> D2-A); confirmed no cost-assumption to remove

No controllable, spend-based SEO intervention is approved (`docs/wp1_
search_seo_granularity_decision_package.md` D2 -> D2-A, per this
addendum's cross-reference in that package). This record's existing §4
("registering a metric definition or ingesting an observation changes no
fitting... behaviour by itself") and `REQ-ECON-001`'s existing CPA/ROI
arithmetic (which requires a cost operand SEO structurally lacks as a
non-paid activity) already forbid a spend-based SEO ROI/ROAS/CPA;
this addendum makes the prohibition explicit and binding for any future
implementation: **SEO must never receive a spend-based ROI, ROAS, or CPA
figure, regardless of future data availability, absent a separate,
explicitly governed cost-basis requirement that does not exist today.**
SEO's approved output vocabulary is limited to: incremental sign-ups/
sales, contribution share, incremental revenue/value (only where the
outcome can legitimately be valued per the existing outcome-valuation
contracts), and response/effectiveness diagnostics — never a spend-based
efficiency ratio.

A repository-wide search (repeated independently by two research passes
during this reconciliation) found **no reference anywhere** to an
approximately £5,000/month SEO cost figure, as either an official
assumption or a historical note. There is therefore nothing to deprecate,
remove, or relabel as non-authoritative in this repository today. This
addendum records the audit result and the forward-looking prohibition
above as a permanent guard, per the brief's own instruction to verify
this by search regardless of current cleanliness.

### Decision 8: confirmed — 28 August 2023 carries no SEO modelling meaning in this repository

A repository-wide search found zero occurrences of 28 August 2023 (or
`2023-08-28`) used as an SEO modelling boundary, truncation date,
intervention date, or SEO-start-date assumption anywhere in this
repository's code, tests, fixtures, or documentation. The only matches
are ordinary calendar-date values inside unrelated CSV sample-data rows
(`ancestry_mmm/sample_data/*.csv`), which carry no SEO-specific meaning
and are not modelling boundaries of any kind. This is an audit
confirmation, not a correction — this record does not need to remove or
correct anything, and this addendum does not invent a replacement SEO
start date (per the brief's explicit instruction not to). A regression
test guards this finding going forward.

This addendum is a contract-level record only; no `core`, `application`,
or `pages` code changes accompany it. It does not resolve D4, D5, D6, or
D7 of `docs/wp1_search_seo_granularity_decision_package.md`, and it does
not resolve the remaining, genuinely open part of D1 (the specific
estimand/transformation/counterfactual for any given use) or D3
(taxonomy content — see `REQ-SEARCH-004`'s own addendum instead).

## Addendum, 2026-08-30 (Phase B): exact positional-visibility formula approved and implemented

This addendum supplies the concrete formula the addendum above explicitly
deferred as research-first Phase B work. Full sources consulted, options
considered, and rationale are recorded in
`docs/seo_positional_visibility_metric_decision_record.md`; this
addendum records only the resulting requirement-level facts.

**Formula.** For a `market x week` cell, given the raw Google Search
Console rows available for that cell (`position`, `impressions`, each
row optionally at query/page/day grain — the metric is agnostic to which):

1. `weighted_avg_position = sum(position_i * impressions_i) /
   sum(impressions_i)` — an impression-weighted average, confirmed to
   match Google's own official BigQuery-export aggregation formula
   (`(sum(sum_top_position) / sum(impressions)) + 1.0`), never a naive
   unweighted mean across rows.
2. `visibility_index = 1.0 / weighted_avg_position` — bounded `(0, 1]`,
   `directionality = "higher_is_better"`. This resolves the "clear,
   unambiguous better-ranking direction" requirement: GSC's native
   `position` field is lower-is-better, which this transform inverts to
   match every other media variable's higher-is-better convention in
   this MMM.
3. A `market x week` cell with zero total impressions across all
   supplied rows produces `weighted_avg_position = None` and
   `visibility_index = None` (undefined, never a fabricated value) —
   confirmed by Google's own documentation that "a position is only
   recorded if the result receives an impression." `total_impressions`/
   `total_clicks` remain real numbers (including a genuine `0.0`)
   whenever source rows were actually supplied for the cell.
4. Organic clicks, impressions, and CTR remain retained as supporting
   diagnostics on the same observation record, never replaced by or
   conflated with the primary `visibility_index` (this record's existing
   §3/§6 separation, reaffirmed).

**Implementation.** `ancestry_mmm/core/seo_visibility.py`:
`SeoVisibilityMetricDefinition`/`SEO_POSITIONAL_VISIBILITY_METRIC` (this
record's §1 `dim_seo_visibility_metric_definition` schema, now
implemented — carrying Decision 6's already-approved
`causal_role = "mediator_or_capture_efficiency_state"`, with
`direction_relative_to_estimand` deliberately left `"not_yet_approved"`
per Decision 6's estimand-specific-per-use instruction), and
`SeoPositionalVisibilityObservation`/`compute_weekly_positional_
visibility` (this record's §2 `fact_seo_visibility_observation` schema).

**Not resolved by this addendum:** the functional form/transformation
this index takes if and when it enters an actual MMM regression as a
treatment variable (this record's still-open "transformation of a
non-linear ranking metric... for use as a linear treatment" item, now
explicitly the *only* remaining part of that item — the measurement-level
transformation is resolved); full partial-window SEO coverage policy
(Decision 3, tracked separately); any GSC ingestion/scheduling mechanism
(out of scope of this record entirely).

### Affected modules (this addendum)

- `ancestry_mmm/core/seo_visibility.py` (new)
- `docs/seo_positional_visibility_metric_decision_record.md` (new)

### Required tests (this addendum)

- `ancestry_mmm/tests/test_seo_visibility.py` (all tests)

## Addendum, 2026-08-30 (Phase B): partial-window SEO handling resolved (Decision 3)

`REQ-SEO-001`'s own "Out of scope" note tracked "full partial-window SEO
coverage policy (Decision 3)" separately. This addendum records that
resolution, researched directly against official PyMC and PyMC-Marketing
documentation (via Context7) rather than guessed: full options-considered
decision record in
`docs/seo_partial_window_handling_decision_record.md`; implementation in
`ancestry_mmm/core/seo_partial_window_policy.py`.

**Resolved:**

- PyMC's native `observed=`-masked-array automatic-imputation mechanism
  was investigated and NOT adopted as the primary mechanism for a
  partially-observed SEO predictor - it is a real, documented feature,
  but applying it to a predictor (rather than an outcome) would require
  an unvalidatable generative prior for periods with no SEO tracking at
  all and no ground truth to check recovery against;
- the approved architecture direction instead (candidate W2-B, a
  windowed/gated regressor: the SEO term is structurally active only
  during SEO's valid data window; the full MMM's time index, every
  other channel/control, and the final-outcome likelihood are
  completely unaffected for every period) - matching Decision 3's own
  "keep the full MMM history... never shorten the whole MMM to SEO's
  window" requirement exactly, and matching PyMC-Marketing's own
  documented idiom of excluding a variable from periods it does not
  cover rather than fabricating values for it;
- the valid-window determination contract
  (`SeoValidEstimationWindow`/`determine_valid_estimation_window`),
  reusing `core.coverage`'s existing missingness vocabulary directly
  (no parallel vocabulary invented) - a week counts as within-window if
  it was actually queried (an ordinary observed fact or a confirmed
  `observed_zero`), never if it was structurally never queried
  (`missing_expected`/`unavailable_source`/`unknown`);
- diagnostics classification of the full MMM's weekly grid relative to
  the determined window (`before_window`/`within_window`/
  `after_window`/`no_window_data`), satisfying "mark the valid
  estimation window clearly in diagnostics";
- the fail-closed official-use eligibility gate for the SEO contribution
  specifically (`assess_seo_contribution_window_eligibility`), never
  eligible without both a real window AND an approved minimum-window-
  length threshold - no threshold number is invented here (deferred to
  `REQ-DATASUPPORT-001`, mirroring that record's own deliberately
  `None`-defaulted thresholds) - satisfying "fail closed for the SEO
  contribution specifically... rather than corrupting the full MMM fit."

**Still not resolved by this addendum:**

- the approved minimum-window-length threshold itself
  (`REQ-DATASUPPORT-001`'s scope, not invented here);
- the functional form/transformation question this addendum's own
  "Out of scope" text already deferred to Decision 6/Phase C.

## Addendum, 2026-09-01 (Phase C): fit-time SEO pathway wired

The approved W2-B direction is now consumed by the shared and
market-specific PyMC model builders through
`core.seo_visibility.SeoModelFitInputs`. Model Training accepts a governed
Google Search Console positional-visibility upload, computes the existing
impression-weighted `1 / position` metric, preserves missing weeks as an
inactive mask, standardizes only observed positive-impression values, and
passes the row-aligned feature into a fitted `seo_visibility_beta` outcome
term. The full MMM history remains in the likelihood.

The fitted payload, exact row identity, window records, standardization
metadata, and posterior coefficient are persisted and restored for
Diagnostics, Results, curve generation, and replay. Sequential
planning/optimisation uses the governed active-window reference state
(zero-centred standardized visibility) as a system-generated baseline;
analysts do not enter future SEO ranking values. SEO does not acquire
spend-based CPA/ROI without an approved cost basis.

This is a reduced-form final-outcome contribution for the approved
visibility/capture-efficiency state. A separately identified decomposition
of `ranking/visibility -> organic traffic -> final outcome` would require a
governed market-week organic-traffic/click series and an approved joint
mediator specification. The current GSC `clicks` field remains diagnostic
only and is not silently used as a flat control.

The implementation is covered by fit-input, persistence, replay, and
fail-closed tests. The minimum-window eligibility threshold remains
external to this requirement and must still be supplied before an SEO
contribution can be labelled planning- or optimisation-eligible.
