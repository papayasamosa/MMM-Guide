# Media-Mix-Lab: Current Repository State

This document is the concise repository-status summary for the current
checkout. It is intentionally separate from approved business requirements
and does not supersede `AGENTS.md`, `docs/approved_requirements/`, or
`docs/decision_log.md`.

## Repository baseline

Repository: `papayasamosa/Media-Mix-Lab`

Current `main` reviewed: `3e2e525300a8526a52f59384271e54fe9815cbe0`

Current head: **Reconcile repository status docs after PR #253 (WP0)**
(merged PR #254, 2026-08-15). This revision of the document additionally
describes Work Package 1 of `Media-Mix-Lab: Coding LLM Next Steps After
PR #253` (Candidate A production integration boundary), landed on top of
that baseline in the same work session.

Historical markers: earlier versions of this document reviewed
`b9b13916ad06c09e37cd53aa83a0fa3a7949a0dc` (merged PR #253, before the WP0
reconciliation) and `0845b150027dc59b192d2ec314b01910af3496ed` (merged PR
#249, before the mixed-frequency executor and Candidate A Search engine
existed). Both SHAs are superseded and are recorded here only for history,
not as current state.

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
  and a fit-consumed-variable capability gate, plus an explicit, versioned,
  **executable** mixed-frequency conversion catalogue/executor
  (`calendar_overlap_allocation` for `flow_count`, `release_aware_locf` for
  `stock_level`/`rate_index`/`survey_measurement`, `native_cadence_only` for
  `survey_measurement`, `calendar_event_alignment` for `event_flag` —
  `docs/mixed_frequency_alignment_wp1.md`). Missing method IDs, version
  mismatches, definition breaks, leakage, and unsupported parameter shapes
  still fail closed; conversion is selected from the Coverage review, never
  inferred from source frequency or column names.
- Standard source-pack semantic adoption for Outcomes, Activity and Media,
  Context and External Factors, and optional Experiment Evidence, plus the
  current source-pack template/download and realistic synthetic-pack UX.
- Current graph-authoritative Causal Graph and Search-object governance UX,
  including direct, cross-product-halo, and excluded/diagnostic-only support
  with unsupported production graph roles still blocked.
- A governed Candidate A Search mediation/capacity engine capability
  (`ancestry_mmm/core/search_capacity.py`, `REQ-SEARCH-002`): a typed
  `SearchCandidateASpec`, forward/reconciliation contracts, identification
  diagnostics, outcome-scale direct/mediated/total effect helpers, a
  Candidate A use gate, and exact Candidate A graph/compiler support.
- Candidate A production integration boundary (WP1): the Candidate A demand/
  capture chain (`attach_candidate_a_demand_capture_chain`) is now spliced
  directly into `core.hierarchical_model.build_fh_hierarchical_model` via an
  optional `search_candidate_a` parameter, reusing that builder's own shared
  multi-channel adstock/Hill-saturated media, market hierarchy, and Negative
  Binomial outcome likelihood rather than a second, simplified model - proven
  by a real `pm.Model` + `pm.draw` reconciliation/non-binding-cap-invariant
  test (`ancestry_mmm/tests/test_hierarchical_model.py::
  TestCandidateASearchIntegration`). `application/model_fit_service.py` is
  the new framework-independent engine-selection adapter
  (`resolve_engine`/`build_model_for_spec`) that
  `pages/05_Model_Training.py` now calls instead of branching on
  `model_type` inline; engine selection is governed by whether the
  project's approved causal graph requires the Candidate A engine
  (`core.graph_model_compiler.check_engine_capability`), never a UI toggle.
  `FHModelMeta.causal_graph_engine` (an existing, already-persisted field)
  carries the Candidate A engine identity through project export/import with
  no schema change - see Known bounded gaps for what remains unintegrated.

## Known bounded gaps

These are implementation or decision boundaries, not permission to invent
business or modelling definitions:

- The mixed-frequency conversion catalogue is deliberately narrow (see above).
  It is not a generic interpolation or imputation layer, and broader
  ragged-window or policy-backed method choices remain bounded gaps.
- Candidate A Search mediation/capacity status must be stated precisely, not
  as a single implemented/unimplemented flag:
  1. Search object governance (REQ-SEARCH-001): implemented.
  2. Candidate A formulation (REQ-SEARCH-002): approved for implementation
     and validation.
  3. Candidate A engine and graph/compiler capability: implemented
     (`core/search_capacity.py`), with synthetic and conditional recovery
     tests.
  4. Production integration boundary (WP1): implemented for the shared/joint
     hierarchical builder only (`build_fh_hierarchical_model(...,
     search_candidate_a=...)`, `application/model_fit_service.py`,
     `pages/05_Model_Training.py`). Market-specific (Model C) Candidate A
     integration is a documented follow-up, not yet available - requesting
     it raises a specific `ModelFitServiceError` rather than silently
     falling back to the ordinary builder. Not yet implemented (Work
     Package 3): Diagnostics, Results, official curve generation, and
     Scenario Planner integration - a Candidate A fit currently persists
     (engine identity, spec, trace) but its posterior is not yet extracted
     into those surfaces.
  5. Official Search fit eligibility: still gated by full joint posterior
     recovery evidence, prior/posterior predictive checks, and identification
     diagnostics beyond the current conditional recovery test (Work Package 2).
  6. Search planning eligibility: disabled.
  7. Search-cap optimisation: disabled.

  Ragged market-specific predictor mathematics (`FR-MOD-015`), moderated
  pathways, and residual-interaction engine support remain decision-bound or
  unsupported, independent of Candidate A.
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
