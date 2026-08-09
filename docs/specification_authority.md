# Specification Authority

## Current PRD suite

| Property | Value |
|---|---|
| Suite name | Ancestry MMM PRD Suite Manifest |
| Version | Cross-Document Coherent v1.5 |
| v1.4 baseline effective date | 28 July 2026 |
| Operating model | Direct internal build by Ancestry Marketing Data Science |
| Repository | `papayasamosa/MMM-Guide` |

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
| Sequential / weekly planning (`REQ-STATE-001`, `REQ-SCEN-001`–`003`) | No approved requirement/decision yet | No indexed record exists. |
| Starting state and terminal state | No approved requirement/decision yet | Bundled with sequential/weekly planning above; no indexed record exists. |
| Future-assumption bundles | No approved requirement/decision yet | No indexed record exists. |
| Time-varying baseline | No approved requirement/decision yet | No indexed record exists; see `AGENTS.md`'s future-variable-role #5 for the standing invariant any future approval must satisfy. |
| Search demand/capacity mathematics (latent demand estimation, cap-hit probability, captured-versus-unmet demand, joint media/cap optimisation) | No approved requirement/decision yet | `REQ-SEARCH-001` (approved, implemented — see below) covers Search object separation/governance only and explicitly places this mathematics out of scope; no record yet approves the modelling contract itself. |
| Capacity and cap semantics (`REQ-CAP-001`) | No approved requirement/decision yet | `AGENTS.md`'s "Capacity and cap invariants" section states the standing business/mathematical invariant; no `REQ-CAP-001` record yet translates it into an approved modelling contract. |
| Experiment translation and recalibration | No approved requirement/decision yet | No indexed record exists. |
| Reporting semantics | No approved requirement/decision yet | No indexed record exists. |
| Background jobs and service boundaries | No approved requirement/decision yet | No indexed record exists. |
| Prior predictive checks, prior-vs-posterior comparison, and predictive log-density (PSIS-LOO/WAIC) | Requirement exists but capability incomplete | `REQ-VAL-001` is approved and substantially implemented (policy objects, readiness evaluator, nine-section diagnostics artefact). Its own record text explicitly defers these three checks as a separately-scoped dependent package. |
| Graph-compilable mediated / capacity-constrained / moderated / residual-interaction edges | Requirement exists but capability incomplete | `REQ-GRAPH-001` is approved and implemented for `direct`, `cross_product_halo`, and `excluded_diagnostic_only` edges. The remaining edge roles are valid graph vocabulary but not yet engine-compilable (`core.graph_model_compiler.check_engine_capability` is authoritative on current support). |

## Approved requirement records already implemented (with documented capability boundaries)

`REQ-GRAPH-001` (graph-authoritative causal configuration) and
`REQ-SEARCH-001` (Search object separation/governance) are approved,
indexed requirement records with substantive implementation. Neither is a
gap requiring a new decision record — each has an explicit, narrower
capability boundary documented in its own record:

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
