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
- Search object model (`REQ-SEARCH-001`)
- Capacity and cap semantics (`REQ-CAP-001`)
- Experiment translation and recalibration
- Reporting semantics
- Background jobs and service boundaries
