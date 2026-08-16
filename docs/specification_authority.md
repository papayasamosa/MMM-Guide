# Specification Authority

## Current PRD suite

| Property | Value |
|---|---|
| Suite name | Ancestry MMM PRD Suite Manifest |
| Version | Cross-Document Coherent v1.5 |
| v1.4 baseline effective date | 28 July 2026 |
| Operating model | Direct internal build by Ancestry Marketing Data Science |
| Repository | `papayasamosa/Media-Mix-Lab` |

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

## Version history: focused Part 3 v1.6 overlay (variable coverage and mixed frequency)

A newer focused source has been supplied, covering Part 3 only:

```text
Ancestry MMM PRD Part 3
Cross-Document Coherent v1.6
Variable Coverage and Mixed Frequency
```

This is a **focused overlay/replacement for Part 3**, not a full-suite
version bump. It does not, by itself, move any other part to v1.6. The
table below is the authoritative per-part version record — a part not
listed as v1.6 remains at its v1.5-suite-manifest content (v1.4 normative
content for Parts 1, 2, 4, 5, 7, 8, 9; the v1.5 graph-first update for
Parts 6, 10, 11, per the table above).

| Part | Version | Notes |
|---|---|---|
| Part 1 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 2 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 3 | v1.6 focused overlay | Variable coverage and mixed-frequency handling — see `REQ-COVERAGE-001` |
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
| Governed FX (`REQ-FX-001`–`REQ-FX-006`) | No approved requirement/decision yet | No indexed record exists. |
| Sequential / weekly planning (`REQ-STATE-001`, `REQ-SCEN-001`–`003`) | Kernel implemented; no indexed requirement record yet | The engine capability exists (WP5, `Media-Mix-Lab: Coding LLM Next Steps After PR #253`, `core.sequential_simulation`) - real historical-carry-in reconstruction, an explicit weekly-plan contract, the candidate/reference incremental-outcome contract, and terminal carryover, for both production-supported model types. It sits alongside the existing steady-state monthly engine, never replacing it, and is not yet wired into the Scenario Planner UI or the optimiser's objective (an application-integration decision, not covered by this brief). No `REQ-STATE-001`/`REQ-SCEN-001`–`003` record has been indexed in `docs/approved_requirements/` for this capability - the implementation brief served as this work package's approval authority per this repository's standard authority hierarchy, the same pattern used for WP0–WP4. |
| Starting state and terminal state | Kernel implemented; no indexed requirement record yet | Bundled with sequential/weekly planning above - see that row. |
| Future-assumption bundles | No approved requirement/decision yet | No indexed record exists. |
| Time-varying baseline | No approved requirement/decision yet | No indexed record exists; see `AGENTS.md`'s future-variable-role #5 for the standing invariant any future approval must satisfy. |
| Search demand/capacity mathematics (latent demand estimation, cap-hit probability, captured-versus-unmet demand, joint media/cap optimisation) | Requirement exists but capability incomplete | `REQ-SEARCH-002` (approved 2026-08-15, implemented — see below) approves Candidate A, the first production Search mediation/capacity formulation, depending on the governed identities in `REQ-SEARCH-001` and the compiler in `REQ-GRAPH-001`. The approval authorises implementation and validation only; it does not approve Search estimates for official planning or optimisation — Search planning eligibility and cap optimisation remain disabled pending that separate evidence. |
| Capacity and cap semantics (`REQ-CAP-001`) | No approved requirement/decision yet | `AGENTS.md`'s "Capacity and cap invariants" section states the standing business/mathematical invariant; no `REQ-CAP-001` record yet translates it into an approved modelling contract. |
| Experiment translation and recalibration | No approved requirement/decision yet | No indexed record exists. |
| Reporting semantics | No approved requirement/decision yet | No indexed record exists. |
| Background jobs and service boundaries | No approved requirement/decision yet | No indexed record exists. |
| Prior-vs-posterior comparison summaries — `REQ-VAL-001` remaining scope | Requirement exists but capability incomplete | `REQ-VAL-001` is approved and substantially implemented, including prior predictive evidence (schema v4, `core.diagnostics.prior_predictive_summary`) and predictive-density evidence (schema v5, `core.diagnostics.predictive_density_summary` — PSIS-LOO/WAIC via `pm.compute_log_likelihood` + `az.loo`/`az.waic`, no refit). Its own record text explicitly defers this remaining check as a separately-scoped dependent package. |
| Variable coverage / mixed-frequency data contracts (Part 3 v1.6 overlay) — `REQ-COVERAGE-001` implementation scope | Requirement exists but capability incomplete | `REQ-COVERAGE-001` is approved and translates the v1.6 overlay's authority (canonical missingness-state vocabulary, coverage invariants, coverage-matrix requirement) into repository requirements. Delivered incrementally in PRs #151-#161 (2026-08-09 to 2026-08-11): source/coverage-matrix domain objects (`core.coverage`), immutable source-version capture on upload, the coverage-matrix builder and Data Coverage review UI, explicit join-mode and join-loss/unmatched-key diagnostics (`data.pipeline.join_sources_with_diagnostics`), a market x channel engine-capability report (`core.market_data_capability`) bound into model fingerprinting, project export/import, and the pre-fit prior-predictive workflow, an official-use governance gate binding that capability report (plus coverage-matrix freshness) to policy-backed model approval as an optional validation-policy gate, and canonical-calendar/mixed-frequency alignment contracts (`core.frequency_alignment`) — see "Approved requirement records already implemented" below. `REQ-COVERAGE-001` itself approves the typed contract only, not a statistical method (its own "Out of scope"); a narrow WP1 method catalogue (six method/variable-class registrations: `flow_count`/`calendar_overlap_allocation`, `stock_level`/`rate_index`/`survey_measurement`/`release_aware_locf`, `survey_measurement`/`native_cadence_only`, `event_flag`/`calendar_event_alignment`) was separately approved and registered since PR #250 (2026-08-15) by `docs/decision_required_frequency_methods.md`, is registered by default (`core.frequency_conversion.ensure_approved_frequency_methods`), and executes through `core.official_preparation` via `execute_frequency_conversion`. A variable class/method combination outside that narrow catalogue still has no approved method and remains decision-required. Still not implemented: a fit-consumed-variable capability report beyond market x channel. `FR-MOD-015` remains explicitly unresolved (record §6). |
| Market-specific / ragged predictor sets inside the hierarchical model equations (`FR-MOD-015`) | No approved requirement/decision yet | `REQ-COVERAGE-001` explicitly reserves this — no masking, zeroing, missing-data likelihood, or separate-coefficient treatment is approved; the current engine may only compile the rectangular subset it already supports and must fail closed for a requested ragged-predictor treatment it cannot represent. |
| Graph-compilable mediated / capacity-constrained / moderated / residual-interaction edges — `REQ-GRAPH-001` remaining scope | Requirement exists but capability incomplete | `REQ-GRAPH-001` is approved and implemented for `direct`, `cross_product_halo`, and `excluded_diagnostic_only` edges. The remaining edge roles are valid graph vocabulary but not yet engine-compilable (`core.graph_model_compiler.check_engine_capability` is authoritative on current support). |

## Approved requirement records already implemented (with documented capability boundaries)

`REQ-GRAPH-001` (graph-authoritative causal configuration),
`REQ-SEARCH-001` (Search object separation/governance), and `REQ-SEARCH-002`
(Candidate A Search mediation/capacity engine) are approved, indexed
requirement records with substantive implementation. None is a gap
requiring a new decision record — each has an explicit, narrower capability
boundary documented in its own record:

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
