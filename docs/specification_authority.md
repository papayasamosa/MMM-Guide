# Specification Authority

## Current PRD suite

| Property | Value |
|---|---|
| Suite name | Ancestry In-House MMM PRD Suite |
| Version | v1.4 |
| Effective date | 28 July 2026 |
| Operating model | Direct internal build by Ancestry Marketing Data Science |
| Repository | `papayasamosa/MMM-Guide` |

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

The following PRD v1.4 capabilities have not yet been translated into approved
requirement records. Each needs a decision record before implementation begins:

- Governed FX (`REQ-FX-001` through `REQ-FX-006`)
- Sequential / weekly planning (`REQ-STATE-001`, `REQ-SCEN-001` through `REQ-SCEN-003`)
- Starting state and terminal state
- Future-assumption bundles
- Time-varying baseline
- Search demand/capacity mathematics (latent demand estimation, cap-hit
  probability, captured-versus-unmet demand, joint media/cap optimisation) -
  `REQ-SEARCH-001` covers Search object separation/governance only (see
  below); its own approved modelling contract is still a gap
- Capacity and cap semantics (`REQ-CAP-001`)
- Experiment translation and recalibration
- Reporting semantics
- Background jobs and service boundaries

## Approved requirement records already implemented at governance level

`REQ-SEARCH-001` (Search object separation/governance) is an approved,
indexed requirement record (`docs/approved_requirements/REQ-SEARCH-001.md`)
with governance-level implementation: distinct governed objects for
`search_demand`, `paid_search_spend`, `paid_search_delivery`,
`paid_search_cap`, `organic_search_capture`, and
`direct_navigation_capture`, plus cap-counterpart validation, effective
periods, version history, and persistence. It is not a gap requiring a new
decision record. What it does *not* cover - Search demand/capacity
mathematics - remains listed above.
