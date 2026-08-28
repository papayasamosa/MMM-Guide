# Specification Authority

## Current PRD suite

| Property | Value |
|---|---|
| Suite name | Ancestry MMM PRD Suite Manifest |
| Version | Cross-Document Coherent v1.5 |
| v1.4 baseline effective date | 28 July 2026 |
| Operating model | Direct internal build by Ancestry Marketing Data Science |
| Repository | `papayasamosa/Media-Mix-Lab` |

## Current consolidated PRD source authority (approved 2026-08-22)

The supplied analyst decision response approved this per-part map and the
substantive decisions below for the current repository-coherence and
implementation work at the time. Its per-part *version* column is superseded
as a current-state PRD-traceability claim by "Current consolidated PRD
version map (2026-08-24)" below — the local PRD suite has since been
refreshed with a further optional Search granularity/SEO visibility overlay
these part numbers predate. The substantive decisions recorded in this
section (the bounded historical-test window, `REQ-NBT-002`'s NBT-not-GSA
authority, and the Brand-State Mediation Model naming) are not PRD-version
facts, remain approved, and are not superseded by that later map.

| Part | Authority as approved 2026-08-22 |
|---|---|
| Part 1 | Cross-Document Coherent v1.4 |
| Part 2 | Cross-Document Coherent v1.4 |
| Part 3 | Cross-Document Coherent v1.12, Pre-Fit Model Diagnostics |
| Part 4 | Cross-Document Coherent v1.7, Pre-Fit Diagnostic Architecture |
| Part 5 | Cross-Document Coherent v1.5, Governed Named-Event Data Contracts |
| Part 6 | Cross-Document Coherent v1.10, Pre-Fit Model Diagnostics |
| Part 7 | Cross-Document Coherent v1.9, Pre-Fit Model Diagnostics |
| Part 8 | Cross-Document Coherent v1.5, Governed Named-Event Scenario Replay |
| Part 9 | Cross-Document Coherent v1.6 |
| Part 10 | Cross-Document Coherent v1.7, Pre-Fit Model Diagnostics UX |
| Part 11 | Cross-Document Coherent v1.7, Pre-Fit Model Diagnostics Service/API |

The standalone Data Input Contract amendment is historical proposal material
whose substantive source-input contract is incorporated into the current
approved Parts 3-7/10/11 wording. The FX addendum is the approved normative
product/architecture contract for FX semantics; Finance-owned provider,
rate-set, operational and future-assumption choices remain separately
deferred.

The current bounded UK historical test is identified as
`window_role=historical_test_common_window` and
`use_mode=historical_test_non_production`, with 2023-01-01 through 2025-04-06
as its 119-week estimation window. This does not change the separate PRD
production-programme period of 2023-07-03 through 2026-06-28.

The initial UK Family History test is governed by `REQ-NBT-002` as supplied
NBT, not GSA. Future brand work is named **Brand-State Mediation Model** with
machine identifier `brand_state_mediation` (BSM); the repository's existing
market-specific Model C is not renamed.

This table describes the v1.4-to-v1.5 baseline as it stood at its own
28 July 2026 effective date. As a *current-state* description it is
superseded by "Current consolidated PRD version map" immediately below;
it remains valid as a historical record of that baseline and is not
rewritten.

## Current consolidated PRD version map (2026-08-24)

This is the single authoritative statement of the latest per-part local
PRD version, reconciled against the local PRD traceability set supplied
as of 2026-08-24. It supersedes every earlier per-part version table in
this document as a *current-state* claim. Earlier tables remain valid as
a record of how each part reached its version through a specific focused
overlay and are not rewritten — see "Version history" below for that
lineage.

| Part | Latest local version | Focused-update title |
|---|---|---|
| Part 1 | v1.4 | Cross-Document Coherence and Governed FX update — unchanged since 28 July 2026; no later overlay touches Part 1 |
| Part 2 | v1.5 | Optional Search Granularity, Paid Search Intent and SEO Visibility update — also normalises `business_priority`/`delivery_status` to one approved enum value each |
| Part 3 | v1.13 | Optional Search granularity, Paid Search intent and SEO visibility — cumulative in the same file with v1.12 (compute-efficient pre-fit model diagnostics), v1.11 (governed named-event temporal response), v1.10 (primary-engine resolution), v1.9 (source-input contract) and v1.8 (structural causal integration) |
| Part 4 | v1.8 | Optional Search granularity, Paid Search intent and SEO visibility architecture — cumulative with v1.7 (compute-efficient pre-fit diagnostic execution), v1.6 (source-input architecture) and v1.5 (structural-causal architecture) |
| Part 5 | v1.6 | Optional Search granularity, Paid Search intent and SEO visibility data contracts — retains v1.5 (governed named-event data contracts) |
| Part 6 | v1.11 | Optional Search granularity, Paid Search intent and SEO visibility modelling — cumulative with v1.10 (compute-efficient pre-fit diagnostics), v1.9 (governed anticipatory named-event response) and v1.8 (structural causal modelling) |
| Part 7 | v1.10 | Optional Search granularity, Paid Search intent and SEO visibility validation — cumulative with v1.9 (pre-fit validation), v1.8 (named-event response validation) and the earlier Bayesian validation/identification/calibration overlay content |
| Part 8 | v1.6 | Optional Search granularity, Paid Search intent economics and SEO visibility planning boundaries — retains v1.5 (governed named-event scenario replay); distinct from the earlier, unrelated "Part 8 v1.5" structural-causal source recorded in the source-collision note below |
| Part 9 | v1.7 | Optional Search granularity, Paid Search intent and SEO visibility reporting — retains v1.6 Final structural-causal/causal-robustness/experiment-calibration reporting content |
| Part 10 | v1.8 | Optional Search granularity, Paid Search intent and SEO visibility UX — retains v1.7 (compute-efficient pre-fit diagnostics UX) and v1.6 (named-event configuration/scenario-replay UX) |
| Part 11 | v1.8 | Optional Search granularity, Paid Search intent and SEO visibility service/API contracts — retains v1.7 (compute-efficient pre-fit diagnostic service/API contracts) and v1.6 (named-event service/API contracts) |

A separate, non-numbered `Ancestry MMM Governed FX Translation
Requirements Addendum` document also exists in the local PRD
traceability set. It carries no Part number or Cross-Document Coherent
version of its own; it supplies supporting detail for the existing
`Governed FX (REQ-FX-001`–`REQ-FX-006)` gap row recorded below, which
remains unreconciled by this pass.

This map records versions and traceability only. Reconciling the newest
content it identifies — the optional Search granularity, Paid Search
intent and SEO visibility overlay — into approved
`docs/approved_requirements/` records is explicitly out of scope for
this reconciliation pass; see "Version history: focused optional Search
granularity, Paid Search intent and SEO visibility overlay" below. This
map does not itself approve, reject, or implement any requirement, and
does not authorise implementing Search/SEO granularity behaviour from
PRD prose.

## Version history: v1.4 to v1.5

v1.5 is a **focused update**, not a full-suite rewrite:

- Parts 3, 6, 10 and 11 are updated in v1.5 for the graph-first causal
  configuration decision (see `REQ-GRAPH-001`).
- Parts 1, 2, 4, 5, 7, 8 and 9 retain their v1.4 normative content under the
  v1.5 suite manifest, pending the next full-suite consolidation.

The v1.5 suite manifest describes Family History GSA acquisition (New, DNA
cross-sell, Winback) as the current primary business acquisition scope. Root
`AGENTS.md` separately requires that no hard-coded primary Family History
outcome be assumed without the approved outcome-definition and use-specific
approval chain (`REQ-OUT-001`, `REQ-OUT-002`). These are compatible only at
the level that GSA is the current business acquisition scope while its exact
event definition and permitted uses remain governed by the outcome-approval
chain — this repository does not hard-code a GSA default, and no change here
introduces one.

## Version history: focused Bayesian validation, causal identification, calibration and forecast-risk overlay

A newer focused source has been supplied, covering five parts:

```text
Ancestry MMM PRD Part 3, Cross-Document Coherent v1.7
  Bayesian Validation and Experiment Calibration
Ancestry MMM PRD Part 6, Cross-Document Coherent v1.6
  Causal Identification and Stability
Ancestry MMM PRD Part 7, Cross-Document Coherent v1.5
  Bayesian Validation, Structural Stability and Calibration
Ancestry MMM PRD Part 9, Cross-Document Coherent v1.5
  Bayesian Validation, Stability and Forecast Risk
Ancestry MMM PRD Part 10, Cross-Document Coherent v1.6
  Validation, Identification, Calibration and Forecast Risk
```

This is a **focused overlay/replacement for exactly these five parts**, not
a full-suite version bump. It does not, by itself, move any other part's
version, and it does not, by itself, move Part 3 beyond this overlay's
v1.7 (superseding the narrower Part 3 v1.6 variable-coverage/mixed-frequency
overlay recorded below — that overlay's own approved capability,
`REQ-COVERAGE-001`, is retained in full; only the version label advances).

| Part | Version | Notes |
|---|---|---|
| Part 1 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 2 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 3 | v1.7 focused overlay | Bayesian validation and experiment calibration — supersedes the v1.6 variable-coverage/mixed-frequency overlay's version label; that overlay's approved capability (`REQ-COVERAGE-001`) is unaffected |
| Part 4 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 5 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 6 | v1.6 focused overlay | Estimand-specific causal identification, latent-state identification, structural stability, experiment calibration — see `REQ-IDENT-001`, `REQ-LATENT-001`, `REQ-STAB-001`, `REQ-EXPMODE-001`, `REQ-CALIB-001` |
| Part 7 | v1.5 focused overlay | Uncertainty-aware predictive validation, leakage-safe historical validation, structural stability, identification, calibration, downstream forecast consequence — see `REQ-LEAK-001`, `REQ-STAB-001`, `REQ-PPD-001`, `REQ-IDENT-001`, `REQ-LATENT-001`, `REQ-EXPMODE-001`, `REQ-CALIB-001`, `REQ-FORECAST-001` |
| Part 8 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 9 | v1.5 focused overlay | Reporting requirements for the above evidence types — see the same records; reporting must consume, not recompute, these artefacts |
| Part 10 | v1.6 focused overlay | UX requirements for the above evidence types, including the mandated graphical-identification disclaimer — see the same records |
| Part 11 | v1.5 (graph-first update) | Retained; not updated by this overlay |

Do not treat this table as evidence that Part 1, 2, 4, 5, 8, or 11 is now at
any of v1.5/v1.6/v1.7 from this overlay. `REQ-LEAK-001`, `REQ-STAB-001`,
`REQ-PPD-001`, `REQ-IDENT-001`, `REQ-LATENT-001`, `REQ-EXPMODE-001`,
`REQ-CALIB-001`, and `REQ-FORECAST-001` (all `docs/approved_requirements/`)
translate this overlay's implementation-ready invariants into repository
authority. Each explicitly excludes the specific numeric thresholds,
formulas, and business/UX label decisions that the source PRD parts
themselves leave open in their own decision registers (Part 6 §37
`MD-001`–`MD-021`; Part 7 §48 `VL-001`–`VL-027`; Part 9 §48 `RP-001`–`RP-025`;
Part 10 §47 `UX-001`–`UX-030`) — none of those ~100 individually numbered
items is approved by this overlay's reconciliation, and none may be
hard-coded from PRD prose without a separate decision record.

## Version history: focused Part 3 v1.6 overlay (variable coverage and mixed frequency)

A newer focused source has been supplied, covering Part 3 only:

```text
Ancestry MMM PRD Part 3
Cross-Document Coherent v1.6
Variable Coverage and Mixed Frequency
```

This is a **focused overlay/replacement for Part 3**, not a full-suite
version bump. It does not, by itself, move any other part to v1.6. The
table below is the authoritative per-part version record for this overlay
alone — superseded for Part 3 specifically by the v1.7 overlay recorded
above, which retains this overlay's approved capability
(`REQ-COVERAGE-001`) in full and only advances the version label.

| Part | Version | Notes |
|---|---|---|
| Part 1 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 2 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 3 | v1.6 focused overlay | Variable coverage and mixed-frequency handling — see `REQ-COVERAGE-001`; superseded in version label only by the v1.7 overlay above |
| Part 4 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 5 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 6 | v1.5 (graph-first update) | Retained; not updated by this overlay |
| Part 7 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 8 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 9 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 10 | v1.5 (graph-first update) | Retained; not updated by this overlay |
| Part 11 | v1.5 (graph-first update) | Retained; not updated by this overlay |

Do not treat this table as evidence that any part other than Part 3 is now
v1.6. `REQ-COVERAGE-001` (`docs/approved_requirements/REQ-COVERAGE-001.md`)
translates the overlay's approved capability set — the v1.6 invariants,
canonical missingness-state vocabulary, and variable-coverage-matrix
requirement — into repository authority. It separates what is approved now
(data/source/coverage semantics, frequency-transformation semantics,
coverage-matrix UI behaviour) from what still requires an explicit,
separately-approved modelling contract (representing market-specific/ragged
predictor sets inside the hierarchical model equations, `FR-MOD-015`) before
any model-engine mathematics may change.

## Operating model

Ancestry Marketing Data Science builds and operates the MMM platform directly.
There is no vendor handover workflow. The platform is licensed under open-source
terms and operated without an ongoing vendor licence, but the build, maintenance
and operation are performed by Ancestry's own data science team.

## Version history: focused structural-causal engine integration overlay

Work Package 0 of `Media-Mix-Lab: Coding LLM Next Steps After PR #286`
reconciled a newer local PRD traceability set covering a bounded
supplemental structural-causal capability, and — via a later local PRD
refresh reviewed within the same work package — a resolved primary-
production-engine decision. This is a **focused overlay**, not a
full-suite version bump.

| Part | Version | Notes |
|---|---|---|
| Part 1 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 2 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 3 | v1.10 focused overlay | Cumulative: v1.10 resolves the primary production MMM engine (PyMC) as an approved decision, no longer `decision_required` — see `REQ-ENGINE-001`; retains v1.9 (approved physical source-input/template contract) and v1.8 (bounded structural causal engine integration) content in the same file |
| Part 4 | v1.6 focused overlay | Bounded structural causal engine architecture plus approved source-input architecture alignment — see `REQ-SCENGINE-001` |
| Part 5 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay. Parts 4, 6, 7, 10 and 11 each reference a further Part 5 v1.6 that was **not** supplied in the local PRD traceability set reconciled by this work package — see "Known version-reference gaps" below |
| Part 6 | v1.8 focused overlay | Structural causal model adapter, joint Bayesian mediation, estimand-specific identification and posterior intervention, approved data-input contract alignment — see `REQ-SCENGINE-001`, `REQ-SCEFFECT-001`, `REQ-CAUSALROBUST-001` |
| Part 7 | v1.7 focused overlay | Structural causal validation coherence: DAG falsification, placebo/permutation refutation, unmeasured-confounding sensitivity, approved data-input validation — see `REQ-CAUSALROBUST-001` |
| Part 8 | v1.5 focused overlay | Structural intervention response curves and bounded causal-engine use — see `REQ-SCCURVE-001` |
| Part 9 | v1.6 focused overlay | Structural causal reporting, causal-robustness evidence, structural intervention curve reporting — supersedes the v1.5 focused Bayesian-validation overlay's version label for Part 9 recorded above; that overlay's approved capabilities (`REQ-LEAK-001`, `REQ-STAB-001`, `REQ-PPD-001`, `REQ-FORECAST-001`, and the others sharing that overlay) are unaffected, only the version label advances |
| Part 10 | v1.8 focused overlay | Structural causal modelling, causal robustness, and intervention UX; approved data-input UX alignment — see `REQ-SCENGINE-001`, `REQ-CAUSALROBUST-001`, `REQ-SCCURVE-001` |
| Part 11 | v1.7 focused overlay | Bounded structural causal service and API contracts; approved data-input service contracts — see `REQ-SCENGINE-001` |

Do not treat this table as evidence that Part 1, 2, or 5 is now at any
version from this overlay. `REQ-ENGINE-001`, `REQ-SCENGINE-001`,
`REQ-SCEFFECT-001`, `REQ-CAUSALROBUST-001`, and `REQ-SCCURVE-001`
(all `docs/approved_requirements/`) translate this overlay's
implementation-ready invariants into repository authority.
`REQ-ENGINE-001` reconciles an already-resolved decision (already the
de facto implementation; zero migration impact). The other four approve
engine-independent target-state *contracts* only, with zero
implementation — each explicitly excludes the specific engine selection,
exact statistical/causal method, threshold, and UX-label decisions the
source PRD parts themselves leave open in their own decision registers
(Part 6 §37 `MD-022`; Part 7 §48 `VL-028`/`VL-029`; Part 10 §47
`UX-031`/`UX-032`/`UX-033`) — none of those items is approved by this
overlay's reconciliation. `docs/wp_structural_causal_engine_decision_
package.md` is the companion decision-support document covering all of
them; no candidate in it is chosen.

### Known version-reference gaps

Part 4 v1.6, Part 6 v1.8, Part 7 v1.7, Part 10 v1.8, and Part 11 v1.7 each
reference a further **Part 5 v1.6** ("canonical entities, physical and
logical source contracts, mapping artefacts, persistence semantics and
lineage") that was not supplied in the local PRD traceability set
reconciled by this work package.
This reconciliation does not infer Part 5 v1.6's content, does not
promote any present Part 5 file to v1.6, and does not claim the
local PRD set is fully self-contained. Where Part 5 v1.6 content would
have been needed to reconcile an invariant, that invariant remains
unreconciled pending the missing source, rather than being approved from
inference.

(A later reconciliation pass — the governed named-event overlay
recorded below, 2026-08-19 — supplied **Part 5 v1.5** (`Focused v1.5
update: governed named-event occurrence and temporal-response data
contracts`). Part 5 v1.6 remains absent, and this document does not
claim Part 5 v1.6 now exists.)

(An earlier reconciliation pass within this same work package additionally
found Part 3 v1.9 and Part 11 v1.7 referenced-but-absent against an
earlier local PRD snapshot; a subsequent local PRD refresh, reviewed
before this record was finalised, supplied Part 3 v1.10 — cumulatively
retaining its own v1.9 content — and Part 11 v1.7 Final, resolving both of
those specific gaps. Only the Part 5 v1.6 gap remains open.)

## Version history: focused governed named-event overlay

Work Package 0 of `Media-Mix-Lab: Coding LLM Next Steps Post PR #297`
(2026-08-19) reconciled a newer local PRD traceability set covering
governed named-event occurrence/family data contracts, governed
anticipatory named-event response, named-event validation, future
named-event scenario replay, named-event UX, and named-event
service/API contracts. This is a **focused overlay**, not a
full-suite version bump, and it approves no statistical response
method. The named-event sources preserve the structural-causal
overlay's Part 10 v1.8 and Part 11 v1.7 — neither is downgraded or
erased. Part 9 v1.6 Final (`964EEB444DD4663D`) contains **no
dedicated named-event reporting contract** — none is assumed or
invented. Part 1 v1.4 and Part 2 v1.4 are retained unchanged.

| Part | Version | Notes |
|---|---|---|
| Part 1 | Retained (v1.4) | Not updated by this overlay |
| Part 2 | Retained (v1.4) | Not updated by this overlay |
| Part 3 | v1.11 focused overlay | Cumulative: governed named-event temporal-response functional coherence, retaining v1.10 (PyMC engine), v1.9 (source-input contract) and v1.8 (structural causal) content in the same file — see `REQ-EVENT-001` |
| Part 4 | Retained (v1.6 Final) | Not updated by this overlay |
| Part 5 | v1.5 focused overlay | Governed named-event occurrence and temporal-response data contracts, preserving v1.4 — see `REQ-EVENT-001`. Part 5 v1.6 remains absent |
| Part 6 | v1.9 focused overlay | Governed anticipatory named-event response, preserving v1.8. Statistical form, priors, regularisation, pooling and heterogeneity remain decision-required — see `docs/wp2_named_event_statistical_method_decision_package.md` |
| Part 7 | v1.8 focused overlay | Governed named-event response validation, preserving v1.7. Validation and planning-eligibility thresholds remain decision-required — see the same package |
| Part 8 | v1.5 focused overlay (named-event scenario replay) | Governed future named-event scenario replay, preserving v1.4 — see `REQ-EVENT-002`. Distinct focused source from the structural-causal Part 8 v1.5 (`REQ-SCCURVE-001`); see the source-collision note below |
| Part 9 | Retained (v1.6 Final) | Not updated by this overlay; contains no dedicated named-event reporting contract |
| Part 10 | v1.6 focused overlay (named-event UX) | Governed named-event configuration and scenario replay UX, preserving v1.5 — does not downgrade or erase the structural-causal Part 10 v1.8 |
| Part 11 | v1.6 focused overlay (named-event service/API contracts) | Governed named-event service and API contracts, preserving v1.5 — does not downgrade or erase the structural-causal Part 11 v1.7 |

Do not treat this table as evidence that Parts 1, 2, 4, or 9 moved, or
that any Part 10 v1.8 / Part 11 v1.7 content was replaced.
`REQ-EVENT-001` and `REQ-EVENT-002` (both
`docs/approved_requirements/`) translate this overlay's
implementation-ready data/governance/replay invariants into repository
authority as target-state contracts with zero implementation;
`docs/wp2_named_event_statistical_method_decision_package.md` records
the statistical choices (response structure, kernel/basis family,
priors, regularisation, pooling, heterogeneity, family-specific
lead/lag support, validation and planning-eligibility thresholds) that
remain decision-required.

### Part 8 v1.5 source collision

The label "Part 8 v1.5" now denotes **two distinct focused updates** of
Part 8, each preserving v1.4 content:

- `Focused v1.5 update: structural intervention curves and bounded
  causal-engine use` — already reconciled by `REQ-SCCURVE-001` (Work
  Package 0 of `...Post PR #286`).
- `Focused v1.5 update: governed named-event scenario replay` —
  reconciled by `REQ-EVENT-002` (this overlay):
  `Ancestry_MMM_PRD_Part_8_Coherent_v1_5_Governed_Named_Event_Scenario_Replay.md`,
  SHA-256 prefix `837858F9BCEF6AF0`.

Same part + same version is not sufficient source identity; the two
sources are distinguished by focused-update title, filename and content
hash. Neither supersedes the other, and neither changes Part 8's v1.4
baseline for the other's topic. Any future citation of "Part 8 v1.5"
must name the focused-update title.

### Known version-reference gaps

Recorded against the local PRD set reconciled by this overlay
(2026-08-19); recorded, not resolved, and no missing source content is
invented:

- **Part 5 v1.6** is still referenced by Part 4 v1.6 and by retained
  content in Part 6 v1.9, and remains absent (see the structural-causal
  overlay's gap note above).
- Part 6 v1.9 retains cross-references to **Part 3 v1.9** and
  **Part 11 v1.7** from its v1.8 content; Part 3 is now v1.11
  (cumulative, retaining v1.9), and Part 11 now also has the
  named-event v1.6 focused update alongside the structural-causal
  v1.7.
- Part 7 v1.8 retains cross-references to **Part 3 v1.10** and
  **Part 11 v1.7**; Part 3 is now v1.11, and Part 11 v1.7 remains
  valid as the structural-causal overlay.
- Part 9 v1.6 references **Part 3 v1.9** (now v1.11) and **Part 8
  v1.5**; the latter reference is now ambiguous under the source
  collision above.
- Part 4 v1.6 references **Part 3 v1.9** (now v1.11) and **Part 5
  v1.6** (absent).

## Version history: focused optional Search granularity, Paid Search intent and SEO visibility overlay

A newer local PRD traceability set, supplied 2026-08-24, reconciles per-part
version and traceability only for a bounded, self-consistent overlay
covering optional finer-grain Paid Search and organic Search intent
analysis and an optional SEO visibility/ranking effect, across Parts 2
through 11. This is a **focused overlay**, not a full-suite version bump,
and it approves no requirement, no statistical method, no causal estimand
and no implementation. Part 1 is not touched by this overlay.

The overlay's own governing principle, stated consistently across every
touched part, is that finer Search detail is optional and
market/capability-gated: aggregate Search remains a valid production,
reporting and planning level in every part, and no part requires a market
to supply raw paid keywords, paid search terms, organic queries, governed
Search intent groups, ranking observations or SEO visibility metrics
merely because another market supplies them.

| Part | Version | Notes |
|---|---|---|
| Part 1 | Retained (v1.4) | Not touched by this overlay |
| Part 2 | v1.5 focused overlay | Optional Search decision framework, new business questions for Generic/Non-Brand Paid Search and organic-capture/SEO-visibility economics, and unrelated `business_priority`/`delivery_status` enum normalisation |
| Part 3 | v1.13 focused overlay | Functional contract for optional Search granularity, intent-level eligibility states, and SEO visibility as distinct from organic capture — retains v1.12 (compute-efficient pre-fit model diagnostics, see the pre-fit note below), v1.11, v1.10, v1.9 and v1.8 content in the same file |
| Part 4 | v1.8 focused overlay | Topology/persistence/dependency changes for optional Search granularity — retains v1.7 (compute-efficient pre-fit diagnostic execution), v1.6 and v1.5 content in the same file |
| Part 5 | v1.6 focused overlay | Canonical `search_intent_group` taxonomy, optional raw-term/query mapping, parent-child Search activity lineage, market-specific granularity records, and optional SEO visibility/ranking metric contracts — retains v1.5 (governed named-event data contracts) |
| Part 6 | v1.11 focused overlay | Hierarchical/partially-pooled intent-group estimation, parent-child reconciliation, and a bounded SEO-visibility causal-effect formulation distinct from organic-capture contribution — retains v1.10, v1.9 and v1.8 content in the same file |
| Part 7 | v1.10 focused overlay | Granularity/identification validation (variation, support, sibling correlation, hierarchy recovery, pooling sensitivity) and SEO-visibility identification/refutation requirements — retains v1.9, v1.8 and the earlier Bayesian validation/identification/calibration overlay content |
| Part 8 | v1.6 focused overlay | Response-curve, economics and planning eligibility for Search intent groups; SEO visibility explicitly excluded from optimisation by default absent a separately approved controllable-intervention contract — retains v1.5 (governed named-event scenario replay) |
| Part 9 | v1.7 focused overlay | Reporting contract for optional Search granularity and SEO visibility — supersedes the v1.6 Final structural-causal/causal-robustness/experiment-calibration overlay's version label for Part 9; that overlay's approved capabilities are unaffected, only the version label advances |
| Part 10 | v1.8 focused overlay | UX for optional Search granularity and SEO visibility — retains v1.7 (compute-efficient pre-fit diagnostics UX) and v1.6 (named-event configuration/scenario-replay UX) content in the same file |
| Part 11 | v1.8 focused overlay | Service/API contracts for optional Search granularity and SEO visibility — retains v1.7 (compute-efficient pre-fit diagnostic service/API contracts) and v1.6 (named-event service/API contracts) content in the same file |

Do not treat this table as evidence that Part 1 moved, or that any
capability described below is approved, implemented, or authorised for
implementation. No `docs/approved_requirements/` record reconciles any
part of this overlay's Search-granularity or SEO-visibility content as of
this record. Reconciliation, where the underlying choice is already
approved and unambiguous (for example, governed taxonomy/lineage data
contracts), and decision-package creation, where it is not (for example,
any SEO visibility causal estimand, intervention semantics or child-cost
allocation policy), are explicitly deferred to a dedicated,
separately-scoped future work package. This record does not select,
approve, or rule out any candidate approach it describes.

### Relationship to the compute-efficient pre-fit diagnostics sub-overlay

Within the same local PRD files, Part 3's v1.12 section, Part 4's v1.7
section, Part 6's v1.10 section, Part 7's v1.9 section, Part 10's v1.7
section and Part 11's v1.7 section together form an earlier, distinct
focused sub-overlay — compute-efficient pre-fit model diagnostics before a
full production Bayesian fit — that predates and is retained underneath
this Search-granularity overlay in every one of those files. That
sub-overlay's reconciliation vehicle, `REQ-PREFIT-001`, was proposed on an
open, still-draft pull request adding reusable Model A pre-fit,
identifiability, prior-predictive and diagnostic infrastructure. As of the
2026-08-24 Search-granularity reconciliation pass recorded above, that
record did not yet exist on `main`; it now exists on this branch (Work
Package 1 of the same coding brief, correcting and completing that pull
request's own contract before merge) and is indexed in `docs/approved_
requirements/index.json`. It is independent of, and does not depend on, the
Search-granularity overlay recorded in this section.

### Known version-reference gaps: Part 5 v1.6 gap closed as a documentation fact

The structural-causal overlay above and the named-event overlay above both
correctly recorded, as of their own reconciliation dates (2026-08-18 and
2026-08-19 respectively), that Part 5 v1.6 was referenced by other parts
but not supplied in the local PRD traceability set at that time. Neither
of those records is rewritten — they accurately describe what was true
when they were written.

As of 2026-08-24, Part 5 v1.6 (`Focused v1.6 update: optional Search
granularity, Paid Search intent and SEO visibility data contracts`, see
the table above) has been supplied locally, closing that specific gap as
a documentation/traceability fact. This does not retroactively approve or
reconcile Part 5 v1.6's content — its data contracts are recorded, not
approved, by this overlay section — and it does not change what the
structural-causal or named-event overlays themselves reconciled at their
own versions.

### Work Package 1 update (2026-08-28): partial reconciliation into approved requirements

The text above accurately describes what was true on 2026-08-24 and is
not rewritten. Work Package 1 of `Media-Mix-Lab Coding LLM Next Steps
2026-08-27` has since reconciled the implementation-ready, already-
unambiguous portion of this overlay into three new approved records:
`docs/approved_requirements/REQ-SEARCH-004.md` (governed Search-intent
taxonomy, term/query mapping, and parent-child activity lineage),
`docs/approved_requirements/REQ-SEARCH-005.md` (multi-axis Search
granularity eligibility contract), and
`docs/approved_requirements/REQ-SEO-001.md` (governed SEO visibility/
ranking metric-definition and observation data shape). Each is a
target-state architecture contract with zero implementation.

`docs/wp1_search_seo_granularity_decision_package.md` collects every
statistical, causal, business, and threshold choice this overlay's own
decision registers (`DD-020`, `MD-008A`, `MD-008B`, `MD-008C`, `VL-032`,
`VL-033`, `VL-034`, `PL-027`, `PL-028`, `RP-030`, `RP-031`, `RP-032`,
`API-029`, `FR-CAU-015`, and Part 2 §26.3 item 14) leave open — most
significantly SEO visibility's causal role and estimand, any
controllable SEO intervention, the initial taxonomy's content, every
identification/promotion threshold, and any parent-child cost-allocation
method. No candidate in that package is chosen, and no threshold is
approved. This update does not select, approve, or rule out any
candidate approach the original 2026-08-24 text above disclaimed.

## Historical status of earlier documents

| Document | Status | Notes |
|---|---|---|
| Ancestry 2026 MMM RFP brief | Historical traceability source | Referenced for original context; not current authority |
| Ebiquity proposal | Historical traceability source | Informed initial scope; not current authority |
| Vendor implementation brief (Claude Code handoff) | Historical | Superseded by PRD v1.4; the `docs/ancestry_fh_mmm.md` file retains this as a record of what was built against |
| `docs/ancestry_fh_mmm.md` | Historical implementation context | Documents what the initial prototype was built against; not current specification authority |
| `docs/approved_requirements/` | Current specification authority | Approved, versioned implementation records |

## Repository implementation-authority hierarchy

For any implementation task within this repository, follow this order of
authority:

1. The task-specific implementation brief (supplied with the task)
2. Approved requirement records in `docs/approved_requirements/`
3. Applicable `AGENTS.md` files (root and per-directory)
4. Existing schemas, migrations, tests, and documented code contracts
5. Existing implementation behaviour, where it does not conflict with the above

If these sources conflict, stop and report the conflict. Do not independently
invent a business decision, silently reinterpret the PRD, or choose one
requirement based on personal judgement.

## Process for translating PRD decisions into approved requirements

1. A PRD requirement is identified as needing implementation.
2. An approved requirement record is created in `docs/approved_requirements/`
   with a unique `REQ-xxx-nnn` identifier.
3. The record captures: requirement ID, PRD source section, capability status,
   affected modules, acceptance tests, migration impact, unresolved decisions,
   owner and approval date.
4. The record is added to `docs/approved_requirements/index.json`.
5. Implementation proceeds against the approved record, not the PRD text.

## Current implementation gaps requiring decision records

Each row below is one of two distinct states, not to be conflated:

- **no approved requirement/decision yet** — no indexed `REQ-*` record
  exists for this capability at all;
- **requirement exists but capability incomplete** — an approved, indexed
  `REQ-*` record exists and covers governance, identity, or part of the
  capability, but the record's own text explicitly reserves the remaining
  target-state capability for a future, separately-scoped requirement.

| Capability | State | Notes |
|---|---|---|
| Governed FX architecture (`REQ-FX-001`, `REQ-FX-002`, `REQ-FX-003`, `REQ-FX-004`, `REQ-FX-005`, `REQ-FX-006`) | Requirement exists but capability incomplete | Approved 2026-08-27 (Work Package 7). Target-state architecture contracts only, reconciling `Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md`'s data model and governance mechanics (currency-concept separation, canonical monetary record, immutable rate-set/cross-rate governance, conversion-method vocabulary, provider-adapter pattern, future-assumption/scenario-optimisation translation, reporting/year-on-year decomposition) into repository authority - blocked pending `docs/wp7_governed_fx_finance_decision_package.md`, which found the addendum's own Section 20 explicitly reserves every concrete operational/business choice (whether USD is the group currency, provider selection, default conversion method, rounding precision, hedged-contract handling, and more) as Finance-owned and unresolved. Zero implementation yet. |
| Sequential / weekly planning (`REQ-STATE-001`, `REQ-SCEN-001`–`004`) | Requirement exists but capability incomplete | The first four records are approved and indexed (WP0, PR #261) - see "Approved requirement records already implemented" below for what each has delivered. `application/scenario_service.py` (WP5) and the manual-plan tab of `pages/08_Scenario_Planner.py` (WP5 part 2: short/long horizon, method labelling; WP5 part 3, 2026-08-18: terminal carryover and opt-in posterior uncertainty; WP5 part 4, 2026-08-18: save/export and staleness) now consume the contract for manual (non-optimised) evaluation. `REQ-SCEN-004` (Work Package 6, 2026-08-18) reconciles sequential-weekly *optimisation* into repository authority but is explicitly blocked pending `docs/wp6_sequential_optimisation_decision_package.md` - the sequential kernel's per-call cost is structurally incompatible with SLSQP's finite-difference search loop, and no objective-definition decision (which incremental-outcome quantity the optimiser would maximise) has been made; neither is decided by this coding pass. A browser-level journey test for the manual sequential path also remains unimplemented. |
| Starting state and terminal state | Requirement exists but capability incomplete | Bundled with sequential/weekly planning above - see that row and `REQ-STATE-001`/`REQ-SCEN-003`. |
| Future-assumption bundles (`REQ-FUTURE-001`) | Requirement exists but capability incomplete | Approved 2026-08-18 (Work Package 9). Target-state contract only, reconciling the bundle-schema, materiality-grading, and external-forecaster-integration gap into repository authority - blocked pending `docs/wp9_future_assumption_bundle_decision_package.md`. Zero implementation yet; `core.planning.future_context` continues to serve one plan window's per-control contract unchanged. |
| Time-varying baseline (`REQ-BASELINE-001`) | Requirement exists but capability incomplete | Approved 2026-08-18 (Work Package 10). Target-state contract only, reconciling `AGENTS.md`'s future-variable-role #5 standing invariant into repository authority - blocked pending `docs/wp10_time_varying_baseline_decision_package.md`, which found a genuine tension between this repository's closest upstream reference (`pymc-marketing`'s `time_varying_intercept` Gaussian Process, documented by its own authors as unsuitable for forecasting beyond a short horizon) and role #5's "projected... for planning" requirement. Zero implementation yet; `core.hierarchical_model`/`core.market_specific_model` continue to use a single static per-market/outcome intercept unchanged. |
| Search demand/capacity mathematics (latent demand estimation, cap-hit probability, captured-versus-unmet demand, joint media/cap optimisation) | Requirement exists but capability incomplete | `REQ-SEARCH-002` (approved 2026-08-15, implemented — see below) approves Candidate A, the first production Search mediation/capacity formulation, depending on the governed identities in `REQ-SEARCH-001` and the compiler in `REQ-GRAPH-001`. The approval authorises implementation and validation only; it does not approve Search estimates for official planning or optimisation — Search planning eligibility and cap optimisation remain disabled pending that separate evidence. |
| Product-specific historical observed Search preparation (`REQ-SEARCH-003`) | Requirement exists but capability incomplete | The staged boundary keeps separate FH/DNA spend and click identities, fail-closed missing-spend/structural-zero resolution, mediator-specific transform namespaces, and prohibited direct spend-to-outcome graph paths. The real UK Search spend gap after 2025-04-06 remains unresolved; no Model B fit or official graph approval is claimed. |
| Capacity and cap semantics (`REQ-CAP-001`) | Requirement exists but capability incomplete | Approved 2026-08-18 (Work Package 11). Target-state contract only, reconciling `AGENTS.md`'s "Capacity and cap invariants" section into repository authority - blocked pending `docs/wp11_capacity_cap_semantics_decision_package.md`, which found `core.search_capacity`'s existing `cap_binding` field represents only two of the four required cap-hit states (capped/uncapped/ambiguous/unavailable), and that `capacity_constrained` graph edges remain compilable only for Candidate A's own authorised Search structure (`REQ-GRAPH-001`). Zero pathway-agnostic implementation yet. |
| Bounded structural causal engine adapter, capability resolution and runtime isolation (`REQ-SCENGINE-001`) | Requirement exists but capability incomplete | Approved 2026-08-18 (Work Package 0 structural-causal authority reconciliation). Target-state contract only, reconciling the newer local PRD structural-causal overlay (Part 3 v1.10 retained v1.8 section, Part 4 v1.6, Part 6 v1.8, Part 7 v1.7, Part 8 v1.5, Part 10 v1.8, Part 11 v1.7) into repository authority - blocked pending `docs/wp_structural_causal_engine_decision_package.md`, which found the PRD's own decision register (Part 6 §37 `MD-022`) explicitly leaves engine selection (including whether PathMC is adopted), eligible mediation/causal-query classes, and runtime-isolation topology as decision-required. Zero implementation yet; `core.graph_model_compiler` continues to reject every edge role beyond `direct`/`cross_product_halo`/`excluded_diagnostic_only`/Candidate A's authorised structure. |
| Structural causal posterior intervention effects (`REQ-SCEFFECT-001`) | Requirement exists but capability incomplete | Approved 2026-08-18 (Work Package 0 structural-causal authority reconciliation). Target-state contract only - blocked pending `docs/wp_structural_causal_engine_decision_package.md` and `REQ-SCENGINE-001` (an engine must first satisfy the capability-resolution contract). Zero implementation yet; Candidate A's own direct/mediated/total reconciliation (`REQ-SEARCH-002`) is unaffected and is not superseded by this record. |
| Causal robustness evidence: DAG falsification, placebo/permutation refutation, unmeasured-confounding sensitivity (`REQ-CAUSALROBUST-001`) | Requirement exists but capability incomplete | Approved 2026-08-18 (Work Package 0 structural-causal authority reconciliation). Target-state evidence contract only - blocked pending `docs/wp_structural_causal_engine_decision_package.md`, which found Part 7 §48 `VL-028`/`VL-029` explicitly reserve the exact test/method/threshold for each of the three dimensions as decision-required. Zero implementation yet; distinct from `REQ-IDENT-001`'s graphical identification and `REQ-LATENT-001`'s latent-state identification, neither of which this record replaces or extends. |
| Structural intervention curve provenance and planning-eligibility boundary (`REQ-SCCURVE-001`) | Requirement exists but capability incomplete | Approved 2026-08-18 (Work Package 0 structural-causal authority reconciliation). Target-state contract only, extending `REQ-CURVE-001` to a future structural-causal-engine-produced curve - blocked pending `docs/wp_structural_causal_engine_decision_package.md` (planning/optimisation eligibility is explicitly excluded, per Part 10 §47 `UX-033`). Zero implementation yet; no structural intervention curve type exists in `core.canonical_curves`/`core.curve_bank`. |
| Governed named-event occurrence, family and response-definition data contracts (`REQ-EVENT-001`) | Requirement exists but capability incomplete | Approved 2026-08-19 (Work Package 0 named-event authority reconciliation); data/lifecycle foundation implemented 2026-08-19 (Work Package 1): `core/named_events.py` governed records (closed four-value temporal vocabulary, factual dates, version immutability, fingerprints), `application/event_service.py` explicit adoption boundary (no text inference), `config/named_events.json` bundle persistence with quarantine-on-import (`resolve_imported_named_events`), and review/adopt/edit UI on `pages/01_Data_Upload.py`. Event-relative feature construction and every statistical response method remain decision-required - tracked by `docs/wp2_named_event_statistical_method_decision_package.md`. |
| Governed future named-event replay in sequential planning (`REQ-EVENT-002`) | Requirement exists but capability incomplete | Approved 2026-08-19 (Work Package 0 named-event authority reconciliation). Target-state contract only, extending `REQ-STATE-001`/`REQ-SCEN-001`-`004`; the existing weekly sequential simulator remains authoritative. Fixed external calendar dates are non-decision context. Zero implementation. Blocked pending `REQ-EVENT-001`'s resources and the named-event statistical-method decision package. |
| Experiment translation and recalibration | Requirement exists but capability incomplete | Superseded by `REQ-EXPMODE-001`/`REQ-CALIB-001` below (approved 2026-08-17) — see those rows. |
| Reporting semantics | No approved requirement/decision yet | No indexed record exists. |
| Background jobs and service boundaries | No approved requirement/decision yet | No indexed record exists. |
| Prior-vs-posterior comparison summaries — `REQ-VAL-001` remaining scope | Requirement exists but capability incomplete | `REQ-VAL-001` is approved and substantially implemented, including prior predictive evidence (schema v4, `core.diagnostics.prior_predictive_summary`) and predictive-density evidence (schema v5, `core.diagnostics.predictive_density_summary` — PSIS-LOO/WAIC via `pm.compute_log_likelihood` + `az.loo`/`az.waic`, no refit). Its own record text explicitly defers this remaining check as a separately-scoped dependent package. |
| Variable coverage / mixed-frequency data contracts (Part 3 v1.6 overlay) — `REQ-COVERAGE-001` implementation scope | Requirement exists but capability incomplete | `REQ-COVERAGE-001` is approved and translates the v1.6 overlay's authority (canonical missingness-state vocabulary, coverage invariants, coverage-matrix requirement) into repository requirements. Delivered incrementally in PRs #151-#161 (2026-08-09 to 2026-08-11): source/coverage-matrix domain objects (`core.coverage`), immutable source-version capture on upload, the coverage-matrix builder and Data Coverage review UI, explicit join-mode and join-loss/unmatched-key diagnostics (`data.pipeline.join_sources_with_diagnostics`), a market x channel engine-capability report (`core.market_data_capability`) bound into model fingerprinting, project export/import, and the pre-fit prior-predictive workflow, an official-use governance gate binding that capability report (plus coverage-matrix freshness) to policy-backed model approval as an optional validation-policy gate, and canonical-calendar/mixed-frequency alignment contracts (`core.frequency_alignment`) — see "Approved requirement records already implemented" below. `REQ-COVERAGE-001` itself approves the typed contract only, not a statistical method (its own "Out of scope"); a narrow WP1 method catalogue (six method/variable-class registrations: `flow_count`/`calendar_overlap_allocation`, `stock_level`/`rate_index`/`survey_measurement`/`release_aware_locf`, `survey_measurement`/`native_cadence_only`, `event_flag`/`calendar_event_alignment`) was separately approved and registered since PR #250 (2026-08-15) by `docs/decision_required_frequency_methods.md`, is registered by default (`core.frequency_conversion.ensure_approved_frequency_methods`), and executes through `core.official_preparation` via `execute_frequency_conversion`. A variable class/method combination outside that narrow catalogue still has no approved method and remains decision-required. Still not implemented: a fit-consumed-variable capability report beyond market x channel. `FR-MOD-015` remains explicitly unresolved (record §6). |
| Market-specific / ragged predictor sets inside the hierarchical model equations (`FR-MOD-015`) | No approved requirement/decision yet | `REQ-COVERAGE-001` explicitly reserves this — no masking, zeroing, missing-data likelihood, or separate-coefficient treatment is approved; the current engine may only compile the rectangular subset it already supports and must fail closed for a requested ragged-predictor treatment it cannot represent. |
| Graph-compilable mediated / capacity-constrained / moderated / residual-interaction edges — `REQ-GRAPH-001` remaining scope | Requirement exists but capability incomplete | `REQ-GRAPH-001` is approved and implemented for `direct`, `cross_product_halo`, and `excluded_diagnostic_only` edges. The remaining edge roles are valid graph vocabulary but not yet engine-compilable (`core.graph_model_compiler.check_engine_capability` is authoritative on current support). |
| Estimand-specific graphical identification (`REQ-IDENT-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core diagnostic implemented Work Package 3 (2026-08-17): `core.estimand_identification.assess_backdoor_identification` implements Pearl's back-door criterion (open backdoor paths, treatment-descendant exclusion, minimal adjustment sets, likely-collider flagging) via `networkx>=3.5` (new dependency), distinct from `REQ-GRAPH-001`'s structural validation and `core.identification_diagnostics`'s fitted-model checks. Supports adjustment-based total-effect estimands only; direct/structural estimands return `unsupported_by_current_checker`. `DiagnosticsArtefact`/Diagnostics-page wiring is now complete (schema v8 `graphical_identification`, computed inline in `DiagnosticsService.evaluate()` when the caller supplies a `causal_graph` and identification requests; every result carries `GRAPHICAL_IDENTIFICATION_DISCLAIMER`, a `direct` effect-type request resolves `unsupported_by_current_checker`, and `pages/06_Diagnostics.py` exposes an interactive assessment reported separately from every other evidence dimension). Not yet implemented: Requirement 5 — extending `core.graph_model_compiler`'s blocking-error contract to fail official compilation on an incompatible adjustment-based estimand (deferred as a separate integration follow-up). |
| Latent-state scale/location identification (`REQ-LATENT-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core diagnostic implemented Work Package 3, second record (2026-08-17): `core.latent_state_identification` provides a model-agnostic identification-declaration contract (five approved strategy kinds, explicit description, optional anchor) and an empirical cross-chain sign-flip check plus descriptive (non-threshold) scale-drift ratio, resolving a closed four-value status, with `is_eligible_for_official_use` implementing the fail-closed use-eligibility gate. Standalone module — never collapsed into `REQ-IDENT-001`'s or `REQ-STAB-001`'s result types. Candidate A's latent branded-search demand (`core.search_capacity`, `REQ-SEARCH-002`) remains the first concrete integration target, but its actual identifying anchor (`MD-021`) is still an unresolved statistical decision, not approved by this record. `DiagnosticsArtefact`/Diagnostics-page wiring is now complete (schema v8 `latent_state_identification`, computed inline in `DiagnosticsService.evaluate()`; a Candidate A fit with no supplied declaration correctly resolves `not_identified` — the fail-closed contract, never a fabricated pass — and no specific identifying anchor is asserted, `MD-021` remaining unresolved). Not yet implemented: Requirement 3 (`core.graph_model_compiler` blocking-error extension for unresolved latent-state identification) and full synthetic-recovery validation/decision-instability detection (Requirement 4's remaining two sub-items). |
| Experiment evidence modes and provenance (`REQ-EXPMODE-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core registry implemented Work Package 4 (2026-08-18): `core.experiments` provides an immutable, versioned `ExperimentRecord` (mirroring `core.causal_graph`/`core.search_objects`'s lineage pattern), `ExperimentToModelUse`'s closed four-value evidence-mode vocabulary, a caller-evidenced `CompatibilityAssessment` across all nine required dimensions, a fail-closed `build_calibrating_use` gate, a double-counting check, and a per-experiment (never averaged) provenance report. Durable adoption/persistence/Diagnostics workflow implemented Work Package 2 of `...Post PR291` (2026-08-19): `application.experiment_service` is the explicit analyst-reviewed adoption boundary (source rows never auto-adopt; missing required fields fail closed; the registry is immutable with versioned edits; calibrating uses require a fully compatible assessment, explicit prior/likelihood identity, and a dependence-handling method when a new use would create a double-counted dependence), the registry persists through the project bundle (`config/experiments.json`, `EXPERIMENT_REGISTRY_SCHEMA_VERSION`, quarantine-on-import via `core.persistence.resolve_imported_experiments`, future schema versions rejected), and the schema v8 `experiment_calibration` Diagnostics section is populated from the real saved registry (`provenance_for_model`, per-experiment, never averaged, with a live staleness note). Adoption/review UI on `pages/01_Data_Upload.py`; use declaration and provenance on `pages/06_Diagnostics.py`. Not yet implemented: any specific likelihood-/prior-calibration statistical mechanism (reserved for a future decision-support package per this record's own text) — the calibrated-vs-uncalibrated comparison half of the Diagnostics section therefore stays empty. |
| Calibrated-versus-uncalibrated model comparison (`REQ-CALIB-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core comparison contract implemented Work Package 4 (2026-08-18): `core.calibration_comparison` reuses `core.model_identity.ModelIdentity` directly (resolving this record's own identity-architecture open question), rejecting construction unless the calibrated and uncalibrated identities are genuinely distinct (Requirement 1). Generic per-metric and per-experiment-agreement comparison, with no threshold/verdict/"preferred" field anywhere — verified by an explicit field-name scan (Requirement 3). `CalibrationEventRecord` implements Requirement 5's per-event record as caller-supplied, structured facts. Depends on `REQ-EXPMODE-001` (not yet coupled by import). No calibration mechanism exists or is implied. A schema v8 `experiment_calibration` Diagnostics display slot for the comparison artefact now exists (optional `CalibratedVsUncalibratedComparisonArtefact` payload, this record's own `to_dict()` — a read-only evidence view, always `None`/`not_applicable` until a calibration mechanism produces one). Not yet implemented: the material-change criteria that trigger mandatory review, any comparison tolerance/threshold, computing any comparison metric itself, and Requirement 4's separate calibrated/uncalibrated visibility in curves/planning/reports. |
| Downstream forecast-consequence evidence (`REQ-FORECAST-001`) | Requirement exists but capability incomplete | Approved 2026-08-17. Separate from, and narrower than, the "Future-assumption bundles" row above (`REQ-FUTURE-001`, Work Package 9) — covers only the consequence-assessment contract for an already-classified exogenous control. Zero implementation yet. |
| Governed Search-intent taxonomy, term/query mapping, and parent-child activity lineage (`REQ-SEARCH-004`) | Requirement exists but capability incomplete | Approved 2026-08-28 (Work Package 1). Target-state architecture contract only, extending `REQ-SEARCH-001`'s object-separation pattern to a governed `search_intent_group` taxonomy and raw-term/query mapping layer - blocked pending `docs/wp1_search_seo_granularity_decision_package.md`, which found the taxonomy's own content/ownership (`DD-020`) and every identification/promotion threshold (`MD-008A`, `VL-032`) undecided. Zero implementation yet; `core.search_objects`/`core.activities` carry no taxonomy or intent-group fields. |
| Search granularity capability and multi-axis eligibility contract (`REQ-SEARCH-005`) | Requirement exists but capability incomplete | Approved 2026-08-28 (Work Package 1). Target-state architecture contract only, extending the existing single-valued `planning_eligibility` pattern to six independent boolean eligibility axes (model/contribution/curve/economics/planning/optimisation) at market x route x platform x parent-activity grain - blocked pending the same decision package, which found every promotion threshold for these axes undecided (`VL-032`, `PL-027`, `PL-028`). Zero implementation yet. |
| Governed SEO visibility/ranking metric-definition and observation contract (`REQ-SEO-001`) | Requirement exists but capability incomplete | Approved 2026-08-28 (Work Package 1). Target-state architecture contract only for the data/provenance shape of an SEO visibility metric definition and its observations, distinct from organic Search capture - blocked pending the same decision package, which found SEO's causal role, estimand, transformation, and any controllable intervention all undecided (`MD-008C`, `VL-034`, `PL-028`, `FR-CAU-015`). Zero implementation yet; no SEO-visibility object exists anywhere in this repository. |
| Governed FH/DNA weekly aggregate valuation input contract (`REQ-ECON-002`) | Requirement exists but capability incomplete | Approved 2026-08-28, per the "Outcome valuation and time-varying ROI: approved business decisions" brief. WP2A (2026-08-28) delivered the core contract: `core.outcome_valuation.WeeklyOutcomeValuationRecord`, catalogue validation, and the observed-denominator cross-validation carve-out for genuine zero/zero cells. Not yet implemented: project-bundle persistence/staleness wiring and the Data Upload UI. The exact FH denominator outcome_id remains a per-project reconciliation task (Requirement 3, enforced fail-closed by the code, never defaulted), and any FX conversion policy remains Finance-owned and blocked. |
| Historical valuation rate-derivation, posterior join, and forward-assumption contract (`REQ-ECON-003`) | Requirement exists but capability incomplete | Approved 2026-08-28, same brief. WP2B delivered Requirements 1-2 (rate derivation with the zero-denominator carve-out). WP2C (2026-08-28) delivered Requirements 3-4: `core.outcome_valuation_attribution` performs the draw-level, weekly-grain join strictly before aggregation (a dedicated test proves this differs from the forbidden aggregate-then-average-rate shortcut whenever rates vary by week) and summarises incremental-value/ROI posterior uncertainty via the existing `core.uncertainty.summarize_distribution` credible-interval convention. Not yet implemented: Requirement 5's Scenario Planner forward-assumption contract (WP2G), and wiring the new artefact into the existing `core.canonical_curves`/`core.attribution`/`core.optimization` CPA/ROI call sites. |
| Historical economic reporting period, aggregation, comparison, and dimension contract (`REQ-ECON-004`) | Requirement exists but capability incomplete | Approved 2026-08-28, same brief. Target-state contract for month/quarter/year/custom-range reporting, calendar-quarter convention, actual-weeks-only partial periods, explicit user-selected period comparison, and the Total-Product-Segment-Funnel-Channel reporting hierarchy gated by existing attribution support - blocked pending WP2D/WP2E implementation. Explicitly excludes the period-over-period contribution waterfall's computation method (see next row). Zero implementation yet. |
| Period-over-period contribution-waterfall computation method, and value/revenue FX conversion policy | No approved requirement/decision yet | Two distinct items remain genuinely open after the 2026-08-28 business-decision update (`docs/wp2_outcome_valuation_decision_package.md`): the waterfall's scope is resolved (an outcome-volume contribution bridge, not an economic decomposition - see `REQ-ECON-004`'s "Explicitly not covered"), but its exact allocation/ordering method is gated behind a required calculation/design note (WP2F) proven on deterministic test data before any further authority record or UI code; and FX conversion policy for a value/revenue series remains entirely Finance-owned and blocked behind `docs/wp7_governed_fx_finance_decision_package.md`, distinct from the already-approved spend-side `REQ-FX-001`-`006`. |

## Current analyst-decision overrides to historical gap rows

The following current statuses supersede older prose in the gap table above:

- `REQ-NBT-002` is approved for the bounded initial UK NBT historical test;
  GSA and NBT remain distinct and legacy `fh_gsa_*` identifiers are aliases
  only.
- `REQ-PREFIT-001` is approved and makes the full pre-fit workflow mandatory
  for official production submission. The current historical test has an
  explicit non-production exception while the service/artefact/page capability
  is implemented.
- `REQ-SEARCH-003` permits the bounded historical observed-mediator Model B
  test after Model A convergence, valid FH/DNA spend-click coverage, graph
  approval, Search prior-predictive checks, equation-level identification and
  synthetic mediation recovery. It does not approve the richer latent
  production Search decomposition or Search planning.
- The FX addendum is approved as the normative product/architecture contract;
  Finance operational provider, rate-set and future-assumption choices remain
  deferred.
- The later brand-state capability is named `brand_state_mediation` / Brand-
  State Mediation Model (BSM). Existing repository market-specific Model C
  terminology and implementation are unchanged.

## Approved requirement records already implemented (with documented capability boundaries)

`REQ-GRAPH-001` (graph-authoritative causal configuration),
`REQ-SEARCH-001` (Search object separation/governance), `REQ-SEARCH-002`
(Candidate A Search mediation/capacity engine), `REQ-STATE-001` (sequential
state contract), `REQ-SCEN-001` (sequential scenario evaluation contract),
`REQ-SCEN-002` (monthly-to-weekly phasing contract), `REQ-SCEN-003`
(response horizon and terminal reporting contract), `REQ-ENGINE-001`
(approved primary production MMM engine), `REQ-LEAK-001` (leakage-safe
historical validation folds), `REQ-STAB-001` (structural stability across
folds), `REQ-PPD-001` (posterior predictive metric distributions),
`REQ-PREFIT-001` (mandatory pre-fit gate for official production
submission), `REQ-CONTROL-001` (standardised category-demand control
prior for the current UK Model A candidate), `REQ-HIERARCHY-001`
(gated H2 diagnostic hierarchy challenger for the current UK Model A
candidate), `REQ-FX-001` through `REQ-FX-006` (governed FX
translation architecture), `REQ-SEARCH-004`, `REQ-SEARCH-005`, and
`REQ-SEO-001` (Search-granularity and SEO-visibility governed
architecture), `REQ-ECON-001` (governed CPA/ROI arithmetic and
value-join contract), and `REQ-ECON-002` through `REQ-ECON-004`
(governed FH/DNA weekly valuation input, rate-derivation/posterior-join,
and reporting-period/aggregation/comparison contracts) are approved,
indexed requirement records with substantive implementation.
None is a gap requiring a new decision record — each has an explicit,
narrower capability boundary documented in its own record:

- `REQ-ENGINE-001` (`docs/approved_requirements/REQ-ENGINE-001.md`):
  reconciles Part 3 v1.10's already-resolved primary-production-engine
  decision (PyMC) into repository authority. Zero migration/code impact —
  every production model builder (`core.hierarchical_model`,
  `core.market_specific_model`, `core.search_capacity`) already runs on
  PyMC, and Meridian is not imported anywhere in `ancestry_mmm/**`. Does
  not resolve the separate, still-open supplemental structural-causal
  adapter decision — see `REQ-SCENGINE-001` in the gaps table above.
- `REQ-GRAPH-001` (`docs/approved_requirements/REQ-GRAPH-001.md`): the graph
  domain, versioning, structural/layout fingerprints, deterministic
  validation, compiler integration, and Streamlit editor are implemented.
  Engine-compilable edge roles remain limited — see the gaps table above.
- `REQ-SEARCH-001` (`docs/approved_requirements/REQ-SEARCH-001.md`):
  distinct governed objects for `search_demand`, `paid_search_spend`,
  `paid_search_delivery`, `paid_search_cap`, `organic_search_capture`, and
  `direct_navigation_capture` are implemented, including cap-counterpart
  validation, effective periods, version history, persistence, and
  fit-relevant fingerprint integration. Search demand/capacity mathematics
  is explicitly out of scope for this record — see the gaps table above.
- `REQ-SEARCH-002` (`docs/approved_requirements/REQ-SEARCH-002.md`):
  Candidate A, the first production Search mediation/capacity formulation
  (approved 2026-08-15), depending on `REQ-SEARCH-001`'s governed identities
  and `REQ-GRAPH-001`'s compiler. `core.search_capacity` is wired into Model
  Training's fit path (`application/model_fit_service.py`,
  `core.hierarchical_model.build_fh_hierarchical_model(...,
  search_candidate_a=...)`), governed by the project's approved causal
  graph, never a UI toggle, and into a dedicated "Candidate A Search"
  Diagnostics tab (`DiagnosticsArtefact.search_capacity` schema v7,
  `core.search_capacity.extract_candidate_a_search_posterior_summary`).
  `core.predict.predict_mu` and `core.attribution.compute_shapley_
  contributions` fail closed with a specific, documented exception for a
  Candidate A fit rather than silently reconstructing an outcome missing
  the search-mediated pathway — this is the actual mechanism keeping
  Search planning/optimisation disabled, not a separate per-feature gate.
  Not yet wired: Results attribution, official response curves, and
  Scenario Planner replay (`predict_mu` has no way to re-evaluate a
  *counterfactual* Search state at a hypothetical scenario/curve point — a
  modelling design question, not a mechanical extension; reasons recorded
  in `docs/decision_log.md`). The approval authorises implementation and
  validation only; it does not approve Search estimates for official
  planning or optimisation.
- `REQ-STATE-001` (`docs/approved_requirements/REQ-STATE-001.md`): the
  sequential (weekly, state-transition) simulation state contract —
  real historical-media starting-adstock reconstruction, no cross-market
  carryover, an explicit `WeeklyPlan` input contract, ending state and
  terminal continuation as structurally separate results, both a fixed-
  carry-in and a fully draw-consistent posterior evaluator for both
  production-supported model types (`core.sequential_simulation`, WP5/PR
  #260, draw-consistent evaluators added WP3 of `...Post PR262`), and
  fail-closed historical-state resolution
  (`_resolve_and_validate_market_history`, WP3). Not yet covered: how a
  monthly plan becomes a `WeeklyPlan` (`REQ-SCEN-002`) and application-layer
  integration.
- `REQ-SCEN-001` (`docs/approved_requirements/REQ-SCEN-001.md`): the
  sequential scenario evaluation contract. Kernel-level items (same
  simulator for candidate/reference, exact-zero no-change invariant,
  Model A and Model C support, both posterior-propagation variants, and a
  typed shared evaluation context — `core.sequential_evaluation_context`,
  WP3 — guarding candidate/reference identity beyond
  `compute_incremental_outcome`'s own market/period/outcome check) are
  implemented. Application-level items (monthly aggregation after weekly
  evaluation, steady-state/sequential method labelling, shared phasing
  policy) are implemented at the application-*service* level (WP5 of
  `...Post PR262`, `core.sequential_scenario_evaluation`, `application.
  scenario_service.ScenarioService.evaluate_manual_sequential`), and, for
  the manual-plan path, in the Streamlit page (`pages/08_Scenario_
  Planner.py`, WP5 part 2 - the "Manual plan evaluation method" radio on
  the "Edited plan and calculated result" tab); the constrained and
  unconstrained-benchmark tabs remain steady-state-only.
- `REQ-SCEN-002` (`docs/approved_requirements/REQ-SCEN-002.md`): the
  monthly-to-weekly phasing and future-context contract. Phasing
  (`calendar_day_overlap_v1`, WP1, `core.planning.phasing`): exact
  day-overlap allocation, per-month conservation to strict numerical
  tolerance, auditable boundary-week attribution, an explicit
  weekly-schedule override with its own reconciliation check, and separate
  monetary/model-input-quantity paths. Future context (WP4 of `...Post
  PR262`, `core.planning.future_context`): trend/Fourier continued via the
  fitted model's own definitions, official-mode fail-closed missing-
  control checks, exploratory-mode labelled `hold_last_observed`. Governed
  `WeeklyPlan` construction (`core.planning.weekly_plan_builder`) and the
  terminal candidate/reference evaluator (`core.planning.
  terminal_response`) complete the core-module implementation. Wired into
  `application.scenario_service` (WP5) and the manual-plan tab of
  `pages/08_Scenario_Planner.py` (WP5 part 2) — the page phases its
  necessarily-partial first sequential month (the plan starts the Monday
  immediately after history ends, not at a month boundary) with the same
  day-overlap formula scoped to covered days, summed with the unmodified
  governed function's output for every subsequent whole month; `phasing.py`
  itself is unchanged.
- `REQ-SCEN-003` (`docs/approved_requirements/REQ-SCEN-003.md`): response
  horizon and terminal reporting. The typed `HorizonConfiguration`
  contract (short/long/plan/terminal horizons, explicit values required)
  is implemented (`core.planning.phasing.HorizonConfiguration`), and the
  business-facing terminal candidate/reference evaluator
  (`core.planning.terminal_response`, WP4 of `...Post PR262`) reports
  terminal incremental response as a structurally separate result, sharing
  one real future non-decision context between candidate and reference.
  Persistence with a saved scenario, and exclusion of terminal carryover
  from the optimisation objective, remain unimplemented pending
  application-layer integration.
- `REQ-COVERAGE-001` (`docs/approved_requirements/REQ-COVERAGE-001.md`):
  the variable-coverage/missingness domain (`core.coverage`:
  `SourceDefinition`, `SourceVersion`, `FrequencyMetadata`,
  `DefinitionBreak`, `VariableCoverageRecord`, `VariableCoverageMatrix`,
  strict schema versioning), immutable source-version capture on upload
  (checksum/filename/size; CSV/XLS/XLSX/XLSM/Parquet), the coverage-matrix
  builder (`build_coverage_matrix_from_frame`) and Data Coverage review UI,
  fit-relevant versus presentation-only coverage fingerprinting bound into
  model identity and project export/import, explicit join-mode and
  join-loss/unmatched-key diagnostics (`data.pipeline.
  join_sources_with_diagnostics`), a market x channel engine-capability
  report (`core.market_data_capability.check_market_channel_capability`)
  bound into model staleness and the pre-fit prior-predictive workflow, an
  official-use governance gate binding that capability report (plus
  coverage-matrix freshness against the current joined data) to
  policy-backed model approval as an optional, non-waivable
  `market_channel_capability` validation gate (`core.validation_policy`,
  `DiagnosticsArtefact.market_channel_capability`), and canonical-calendar/
  mixed-frequency alignment contracts (`core.frequency_alignment`:
  `AlignmentSpecification`, publication-leakage/definition-break/
  support-boundary checks, and `resolve_canonical_calendar` — fails closed
  with `CalendarResolutionRequiredError` rather than inferring a calendar
  from raw source intersection) are implemented. `REQ-COVERAGE-001` itself
  approves this typed contract only and starts with a genuinely empty
  conversion-method registry — it does not select a statistical method
  (its own "Out of scope"). Frequency-conversion *execution* for a narrow
  WP1 method catalogue was separately approved and registered since PR
  #250 (2026-08-15, `docs/decision_required_frequency_methods.md`,
  `core.frequency_conversion.ensure_approved_frequency_methods`) and is
  wired into official-use data preparation (`core.official_preparation`,
  `execute_frequency_conversion`) — see the gaps-table row above for the
  current catalogue and its boundary. A fit-consumed-variable capability
  report beyond market x channel (outcome source columns, controls,
  promotions) remains unimplemented — see the gaps table above.
  `FR-MOD-015` (market-specific/ragged predictor sets) remains explicitly
  unresolved (record §6).
- `REQ-LEAK-001` (`docs/approved_requirements/REQ-LEAK-001.md`):
  leakage-safe, time-respecting historical validation folds are
  implemented end-to-end. `core.validation_folds` provides typed fold
  manifests, per-variable leakage assessment against
  `core.coverage.VariableCoverageMatrix` (reusing `core.
  frequency_alignment`'s leakage/definition-break checks), and a
  leakage-safe backtest wrapper that refuses to fit an unsafe fold.
  Real per-fold PyMC re-fitting exists
  (`application.fold_refit_service.run_leakage_safe_fold_refit`, fitting
  only folds the assessment cleared, once per fold), and point-in-time
  source reconstruction exists
  (`run_leakage_safe_fold_refit_from_sources`: fold-local
  `core.official_preparation.prepare_canonical_native_frame` governed to
  each fold's own information cutoff, with `SourceVersion` upload-timing
  cross-checks). Schema v8 adds the `historical_validation` Diagnostics
  section, populated by `DiagnosticsService.
  run_historical_and_structural_validation_check()` from one fold-refit
  run, rendered as a "Historical validation & structural stability" page
  action. The page routes to the deeper from-sources path automatically
  when the project has its raw source tables and outcome definitions, and
  otherwise runs the shallower coverage-metadata-only path with that
  weaker tier recorded in the `historical_validation` payload (closed
  `RECONSTRUCTION_TIER_*` vocabulary, part of the artefact fingerprint;
  reload restores the weaker tier for pre-tier artefacts) and labelled
  explicitly in the UI — never presented as the deeper reconstruction.
  Documented boundary: the repository retains no durable
  historical-vintage byte store — a fold whose pinned `SourceVersion` was
  uploaded after its cutoff resolves `cannot_verify` and is never fit,
  and is never silently rebuilt from today's revision.
- `REQ-STAB-001` (`docs/approved_requirements/REQ-STAB-001.md`):
  structural stability evidence across time-respecting folds is
  implemented. `core.structural_stability` provides per-fold
  `FoldParameterSnapshot`s and a per-parameter cross-fold comparison with
  a descriptive `point_range` only — never a threshold, verdict, or
  composite score. The caller-supplied snapshots are now produced by a
  real per-fold re-estimation pipeline
  (`application.fold_refit_service.fit_fold_with_real_model`, both Model
  A and Model C, including the from-sources fold-local reconstruction
  path), and schema v8's `structural_stability` section is populated from
  the same single fold-refit run as `historical_validation` — never two
  divergent fits for one fold. Interpreting instability remains a human
  reviewer's judgement by design (Requirement 4 is not automated).
- `REQ-PPD-001` (`docs/approved_requirements/REQ-PPD-001.md`):
  posterior predictive metric distributions are implemented
  (`core.diagnostics.posterior_predictive_metric_distributions`,
  `core.market_specific_diagnostics.
  posterior_predictive_metric_distributions_market_specific` — one shared
  computation core, so Model A and Model C can never silently diverge).
  Per-draw MAE/RMSE/sMAPE/WAPE/bias distributions carry the existing
  posterior-mean point value passed through — never recomputed — and
  sMAPE's 0/0 safeguard is applied per draw. Schema v8 adds the
  `posterior_predictive_metric_distributions` section, computed inline in
  `DiagnosticsService.evaluate()` (no extra fit) and rendered as its own
  table; pre-v8 artefacts upgrade the section to `not_computed`, never a
  fabricated payload.
- `REQ-PREFIT-001` (`docs/approved_requirements/REQ-PREFIT-001.md`):
  the mandatory pre-fit gate is implemented with one governed readiness
  vocabulary throughout (`ready`/`review_recommended`/`blocked`) — the
  original draft exposed a second, competing vocabulary
  (`status: "computed"`, a separate `submission_gate` field) on
  `core.prefit_screening`'s own report; that is fixed at the source, and
  `core.prefit_run.consolidate_prefit_readiness`/`PrefitRun` now
  additionally binds both evidence reports, every required fingerprint,
  the fold-reconstruction tier, and the analyst-rationale precondition
  into one durable run identity, persisted through the existing project
  export/import mechanism (`config/prefit_runs.json`,
  `core.persistence.resolve_imported_prefit_runs`) rather than loose
  Streamlit session state — `pages/05_Model_Training.py`'s official-fit
  button now consults that one object
  (`core.prefit_run.official_submission_allowed`) instead of re-deriving
  its own blocking decision from scattered sub-fields. The fold-
  reconstruction tier is honestly reported as `prepared_frame_only` (the
  screen splits an already-prepared frame by date; it does not yet reuse
  `application.fold_refit_service`'s deeper point-in-time source
  reconstruction — that reuse integration remains unimplemented). The
  same review found an unconditional, undocumented control/outcome-
  control centring-and-scaling step live in `core.hierarchical_model`'s
  default production path with no compensating prior recalibration and
  no approval; it is now gated behind the same default-off,
  diagnostic-only contract as this record's other convergence-experiment
  switches (`core.hierarchical_model._resolve_control_scaling`,
  `prior_config["enable_control_scaling"]`), restoring the pre-existing
  production default. Not yet implemented: a dedicated pre-fit workspace
  distinct from Model Setup (Requirement 5 — this record does not itself
  approve a specific UX placement, so none is implemented from PRD prose
  alone); and a formally approved numeric support-threshold/prior-
  predictive-plausibility policy (`core.prefit_identifiability.
  SupportThresholdPolicy`'s defaults remain unapproved diagnostic
  values — they can only ever relax a run to `review_recommended`, never
  fabricate a `blocked` or a false `ready`, but the exact numbers are not
  themselves approved authority).
- `REQ-CONTROL-001` (`docs/approved_requirements/REQ-CONTROL-001.md`,
  approved 2026-08-25): scoped to the current UK Model A candidate's two
  named continuous category-demand controls
  (`fh_category_demand_google_trends`, `dna_category_demand_google_trends`)
  only — standardisation (`core.control_scaling.fit_control_scaling`'s
  existing `mean_sd` method) plus a `Normal(0, 0.20)` coefficient prior on
  the standardised scale, implemented as `APPROVED_UK_MODEL_A_PRIOR_
  CONFIG` and defaulted in `scripts/run_uk_production_fit.py`. Does not
  change the candidate's `historical_test`/`non_production` status, and is
  not a universal control-prior default for any other channel or model.
- `REQ-HIERARCHY-001` (`docs/approved_requirements/REQ-HIERARCHY-001.md`,
  approved 2026-08-26): authorises a gated, default-off **H2** diagnostic
  hierarchy challenger for the current UK Model A candidate only
  (`prior_config["shared_pooling_scale"]=True` in `core.hierarchical_
  model.build_fh_hierarchical_model` — one scalar `sigma_pool_global`
  replacing the production per-channel `sigma_pool[channel]` vector,
  `z_offset[o, c]` unchanged). Explicitly diagnostic-only: does not
  approve replacing the production hierarchy, does not certify H2, and
  requires a further, separate analyst decision before any production
  use. `docs/wp2_11_hierarchy_decision_package_20260826.md` records the
  gathered convergence/geometry evidence (H1 the more numerically
  well-behaved segment-preserving challenger; H2 worse on both products
  and not supportive as a segment-preserving alternative) and finds it
  not yet sufficient for a production-default decision — no out-of-sample
  fold-refit-backtest evidence exists for any candidate, and the current
  UK activity data is separately under review for suspected
  source-to-model mapping issues.
- `REQ-FX-001` through `REQ-FX-006` (`docs/approved_requirements/
  REQ-FX-001.md` through `REQ-FX-006.md`, approved 2026-08-27): reconcile
  `Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md`'s
  *architecture* — currency-concept separation and the canonical
  monetary record (`REQ-FX-001`), immutable versioned FX-rate/rate-set
  governance and cross-rate derivation (`REQ-FX-002`), the closed
  historical conversion-method vocabulary (`REQ-FX-003`), the
  provider-adapter pattern and ingestion governance (`REQ-FX-004`),
  future FX assumptions and scenario/optimisation translation
  (`REQ-FX-005`), and reporting/year-on-year FX decomposition
  (`REQ-FX-006`) — into repository authority. Each is a target-state
  contract only, with zero implementation. None approves a Finance-owned
  operational choice (whether USD is the group currency, provider
  selection, default conversion method, rounding precision, hedged-
  contract handling, and the addendum's own Section 20 items in full) —
  `docs/wp7_governed_fx_finance_decision_package.md` collects every one
  of those open questions in one place for a future Finance decision.
- `REQ-SEARCH-004` (`docs/approved_requirements/REQ-SEARCH-004.md`,
  approved 2026-08-28): reconciles the optional Search-granularity
  overlay's governed `search_intent_group` taxonomy, raw paid-term/
  organic-query mapping, and parent-child `ActivityDefinition` lineage
  into repository authority, extending `REQ-SEARCH-001`'s existing
  object-separation/versioning/persistence/validation pattern. Target-
  state contract only, with zero implementation. Does not approve the
  taxonomy's own content/ownership or any identification/mapping
  threshold — `docs/wp1_search_seo_granularity_decision_package.md`
  collects those open questions.
- `REQ-SEARCH-005` (`docs/approved_requirements/REQ-SEARCH-005.md`,
  approved 2026-08-28): reconciles the overlay's market x route x
  platform x parent-activity Search granularity capability record into
  repository authority, extending the existing single-valued
  `planning_eligibility` pattern to six independent boolean eligibility
  axes (model/contribution/curve/economics/planning/optimisation).
  Target-state contract only, with zero implementation. Does not approve
  any evidence threshold that would set an axis to `true` — the same
  decision package collects those.
- `REQ-SEO-001` (`docs/approved_requirements/REQ-SEO-001.md`, approved
  2026-08-28): reconciles the overlay's governed SEO visibility/ranking
  metric-definition and observation data shape into repository
  authority, distinct from organic Search capture. Target-state contract
  only, with zero implementation. Does not approve which metric is used,
  its causal role, its estimand, or any controllable SEO intervention —
  the same decision package collects those.
- `REQ-ECON-001` (`docs/approved_requirements/REQ-ECON-001.md`, approved
  2026-08-28): reconciles an already-true, already-implemented fact —
  like `REQ-ENGINE-001` — rather than a target-state contract. Locks in
  the existing, internally consistent CPA/ROI arithmetic (`CPA = cost /
  incremental_outcome`, `ROI = incremental_value / cost`, both average
  and marginal) already implemented identically across
  `core.canonical_curves`, `core.attribution`, and `core.optimization`,
  and the existing value-join principle (a value is multiplied against,
  never presented as, the incremental outcome). Explicitly confirms no
  PRD passage supports a net-of-investment `(value - cost)/cost`
  alternative. Zero migration/code impact. Does not approve what the
  value operand itself represents for Family History or DNA, any
  week/segment variation, FX-for-value policy, or any waterfall
  accounting method — `docs/wp2_outcome_valuation_decision_package.md`
  collects those open questions.
- `REQ-ECON-002` (`docs/approved_requirements/REQ-ECON-002.md`, approved
  2026-08-28): reconciles the business-approved governed FH/DNA weekly
  aggregate valuation input contract — market x week x segment aggregate
  monetary totals (FH LTR, DNA revenue), explicit non-defaulted
  denominator linkage, mandatory never-inferred currency-identification
  metadata, fail-closed missingness with an explicit zero-denominator
  carve-out, and versioned/provenanced source data. Target-state
  contract only, with zero implementation (WP2A). Does not approve the
  specific FH denominator outcome_id for any given project, or any FX
  conversion policy.
- `REQ-ECON-003` (`docs/approved_requirements/REQ-ECON-003.md`, approved
  2026-08-28): reconciles the weekly rate-derivation formula
  (aggregate value / denominator count), its draw-level join to
  posterior incremental outcomes before temporal aggregation, the
  fixed-value/posterior-only uncertainty treatment, and the analogous
  explicit-assumption contract for Scenario Planner forward valuation.
  Target-state contract only, with zero implementation (WP2B/WP2C/WP2G).
- `REQ-ECON-004` (`docs/approved_requirements/REQ-ECON-004.md`, approved
  2026-08-28): reconciles the historical economic reporting-period
  contract — monthly/quarterly/yearly/custom-range grains, standard
  calendar quarters, actual-weeks-only partial periods (never scaled or
  annualised), explicit user-selected period comparison, and the
  Total-Product-Segment-Funnel-Channel reporting-dimension hierarchy
  gated by existing attribution support. Target-state contract only,
  with zero implementation (WP2D/WP2E). Explicitly excludes the
  contribution-waterfall's computation method.
