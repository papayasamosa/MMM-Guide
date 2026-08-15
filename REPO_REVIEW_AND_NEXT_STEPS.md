# Media-Mix-Lab: Current Repository State

This document is the concise repository-status summary for the current
checkout. It is intentionally separate from approved business requirements
and does not supersede `AGENTS.md`, `docs/approved_requirements/`, or
`docs/decision_log.md`.

## Repository baseline

Repository: `papayasamosa/Media-Mix-Lab`

Current `main` reviewed: `0845b150027dc59b192d2ec314b01910af3496ed`

Current head: **Repository truth reconciliation before mixed-frequency execution**
(merged PR #249, 2026-08-15; WP1 is the current implementation brief).

The local Python distribution name remains `mmm-guide` for compatibility with
the existing install, script, export, and deployment surface. That legacy
distribution identifier is not the GitHub repository identity and is not
renamed by this status reconciliation.

## Delivered foundation

The current implementation includes:

- Streamlit workflow state, readiness guidance, technical pages, reporting,
  planning, project export, and project recovery.
- Immutable source versions and four logical source domains: Outcomes,
  Activity and Media, Context and External Factors, and optional Experiment
  Evidence.
- Standard workbook downloads for all four domains.
- Outcomes source-pack v2 parsing/adoption, governed outcome definitions and
  groups, draw-level grouped totals, DNA partition safeguards, and realistic
  synthetic templates.
- Explicit Family History New, DNA cross-sell, and Winback outcomes plus
  governed DNA outcomes.
- Governed activity definitions, identity-only `pooling_group_id`, ownership,
  model-input/spend/response-unit semantics, and cost mappings.
- Explicit Search-object governance separating demand, Paid Search spend and
  delivery, caps, organic/direct capture, and residual incrementality.
- Graph-authoritative direct, cross-product-halo, and excluded/diagnostic-only
  structures. Unsupported mediated, capacity-constrained, moderated, and
  residual-interaction engine structures fail closed.
- Joint hierarchical and market-specific partially pooled PyMC paths,
  outcome-scale counterfactual curves, draw-level totals, attribution,
  governed curve artefacts, and cost/FX-aware economics.
- Validation, approval, staleness, persistence, migration, resumability,
  scenario-planning, and optimisation contracts.
- Canonical native-weekly official preparation with an explicit governed
  calendar, an outer union of governed source periods, preserved missingness,
  and a fit-consumed-variable capability gate. WP1 now adds an explicit,
  versioned mixed-frequency catalogue/executor; missing method IDs, version
  mismatches, definition breaks, leakage, and unsupported parameter shapes
  still fail closed.
- Standard source-pack semantic adoption for Outcomes, Activity and Media,
  Context and External Factors, and optional Experiment Evidence, plus the
  current source-pack template/download and realistic synthetic-pack UX.
- Current graph-authoritative Causal Graph and Search-object governance UX,
  including direct, cross-product-halo, and excluded/diagnostic-only support
  with unsupported production graph roles still blocked.

## Known bounded gaps

These are implementation or decision boundaries, not permission to invent
business or modelling definitions:

- WP1's conversion catalogue is deliberately narrow: flow counts use
  calendar-day overlap allocation; stock/rate/survey values use release-aware
  LOCF (or an explicit native-cadence survey method); and events use explicit
  point/duration calendar alignment. It is not a generic interpolation or
  imputation layer, and broader ragged-window or policy-backed method choices
  remain bounded gaps.
- Ragged market-specific predictor mathematics (`FR-MOD-015`), production
  mediation, Search capacity/censoring mathematics, moderated pathways, and
  residual-interaction engine support remain decision-bound or unsupported.
- The full-core mypy debt ceiling is now 276 errors; it is a ceiling, not a
  target. CI must fail if the measured count increases.
- Scenario planning remains a steady-state monthly approximation rather than
  a sequential weekly simulation with starting adstock and terminal carryover.
- Chronos-2 or another future exogenous forecasting integration is not yet
  implemented.
- Real UK data readiness is an operational step and must be run only by an
  authorised analyst with approved local data outside Git.

## Required implementation discipline

Future substantive work must use the task-specific brief and repository
authority hierarchy, preserve the existing governance and mathematical
contracts, keep model-input units distinct from monetary spend, and record
engine capability boundaries honestly. No real Ancestry data belongs in this
repository, browser fixture, log, screenshot, or generated artefact.
