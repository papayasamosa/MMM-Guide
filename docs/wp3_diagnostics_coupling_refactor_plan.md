# Diagnostics coupling: measured state and a scoped refactor plan

Work Package 3 (`Media-Mix-Lab Coding LLM Next Steps 2026-08-27`).

## Why a plan instead of a refactor

`ancestry_mmm/application/diagnostics_service.py` (2,186 lines) and
`ancestry_mmm/pages/06_Diagnostics.py` (2,476 lines) are the two most
coupled modules in the repository (`REPO_REVIEW_AND_NEXT_STEPS.md` and
root `AGENTS.md` already flag this). Graphify MCP was unavailable this
session (its launcher legitimately refuses to start on this machine - see
the WP0 completion report), so this assessment is import-graph analysis
via direct source inspection rather than a generated dependency graph.

WP3's own brief permits producing a scoped plan instead of performing the
refactor when "the safe refactor would be large" - that is the case here.
A same-session extraction of either file carries real risk: this is
governance code (model approval, staleness, evidence fingerprints,
`DiagnosticsArtefact` schema versioning) where a subtle behavioural change
during extraction could silently corrupt a fingerprint chain or an
approval decision, with no human review checkpoint before merge in this
autonomous workflow. That risk profile calls for staged, individually
reviewable PRs with characterisation tests landing first - not a
single-sitting split.

## Measured current state

### `ancestry_mmm/application/diagnostics_service.py` (2,186 lines)

| Section | Lines | Nature |
|---|---|---|
| `DiagnosticSection` | 249-305 | Small, pure-data helper dataclass (status/payload/error, fingerprint of its own payload). |
| `DiagnosticsArtefact` | 330-903 (~570 lines) | The persisted, versioned schema (currently schema v9, `CURRENT_DIAGNOSTICS_SCHEMA_VERSION`). Pure dataclass + `to_dict`/`from_dict`/`_from_v1`/schema-version validation. No PyMC, no fitting, no Streamlit import already. |
| `DiagnosticsInput` / `DiagnosticsResult` | 905-1039 | Small, pure-data dataclasses. |
| `DiagnosticsService` | 1040-2186 | The actual orchestration class. `evaluate()` alone spans lines 1048-1778 (~730 lines) - computes roughly a dozen evidence sections (error metrics, residual series, market-channel capability, search-capacity, graphical/latent-state identification, experiment calibration, posterior-predictive metric distributions, and more) in one method. `run_backtest`/`run_prior_predictive_check`/`run_predictive_density_check`/`run_historical_and_structural_validation_check` are separate, already-decomposed "replace one section, carry the rest" methods (~60-120 lines each) - these are NOT part of the coupling problem; they are the pattern worth extending. |

### `ancestry_mmm/pages/06_Diagnostics.py` (2,476 lines)

Imports directly from 24 distinct `ancestry_mmm.core`/`ancestry_mmm.application`
modules, spanning domains that should not need to be page-visible at all:
model builders (`core.hierarchical_model.build_fh_hierarchical_model`,
`core.market_specific_model.build_fh_market_specific_model`), fitting
(`core.models.fit_model`, `application.model_fit_service.
build_model_for_spec`), prediction (`core.predict`, `core.
market_specific_predict`), fold-refit (`application.fold_refit_service`),
approval (`core.approval`), model identity (`core.model_identity`, `core.
fingerprint`), the causal graph (`core.causal_graph`), experiments
(`application.experiment_service`, `core.experiments`), and a dozen
further diagnostic-domain core modules (`core.estimand_identification`,
`core.validation_folds`, `core.validation_policy`, `core.
market_data_capability`, `core.coverage`, `core.search_objects`, `core.
search_capacity`, `core.pathways`, `core.outcomes`, `core.
outcome_group_totals`, `core.funnel`, `core.activities`, `core.schema`).

Root `AGENTS.md`'s own architecture rule ("core for analytical logic;
application services for orchestration; components for rendering; pages
for workflow composition") is violated here: a page should not need to
call `core.hierarchical_model.build_fh_hierarchical_model` or `core.
models.fit_model` directly - that is exactly what `application.
model_fit_service`/`application.diagnostics_service` exist to wrap.

### Blast radius (fan-in)

Real (non-test) importers of `application.diagnostics_service`:
`application/curve_service.py`, `application/validation_service.py`,
`pages/06_Diagnostics.py`, `pages/09_Project_Export.py` - a contained,
already-layered set (application depending on application, pages
depending on application - no inverted-layering import found; an initial
grep hit in `core/diagnostics.py` was a docstring cross-reference, not a
real import).

### Existing test safety net (uneven - this drives the staging below)

- `DiagnosticsArtefact`: `ancestry_mmm/tests/test_diagnostics_artefact.py`
  - 2,917 lines, 130 tests. Substantial existing characterisation
    coverage of exactly the schema/serialisation surface that would move
    in Phase 1 below.
- `DiagnosticsService`: referenced across 8 test files, but no single
  dedicated characterisation suite exists for `evaluate()` as a whole -
  the higher-risk piece, and the reason Phase 2 below is explicitly
  gated on adding characterisation tests first, per WP3's own
  instruction ("Add characterisation tests before moving under-tested
  behaviour").

## What must not change (non-negotiable across every phase)

- `DiagnosticsArtefact.fingerprint()`/`chain_fingerprint`/section-level
  `fingerprint_payload()` output, byte-for-byte, for the same input -
  these gate model approval and staleness detection
  (`core.validation_policy`, `core.outcome_approval`). A refactor that
  changes field order, adds an intermediate serialisation step, or
  reorders dict construction could silently change a fingerprint's hash
  input even while "the code still works."
- `CURRENT_DIAGNOSTICS_SCHEMA_VERSION`/`from_dict`'s v1-through-v9
  upgrade-in-place behaviour for every existing persisted artefact shape.
- Every currently-passing test in `test_diagnostics_artefact.py` and the
  8 files referencing `DiagnosticsService`, unmodified in assertions -
  only import paths may change.
- No change to `docs/approved_requirements/`, evidence semantics, or any
  statistical/causal computation performed inside `evaluate()`.

## Staged plan

### Phase 1 (lowest risk - recommended first PR)

Move `DiagnosticSection`, `DiagnosticsArtefact` (including `to_dict`/
`from_dict`/`_from_v1`/`_validate_diagnostics_schema_version`),
`DiagnosticsInput`, and `DiagnosticsResult` from `application.
diagnostics_service` into a new `core.diagnostics_artefact` module.
Rationale: this is pure-data (dataclasses + dict serialisation), has no
PyMC/Streamlit dependency already, and already carries 130 dedicated
tests. `application.diagnostics_service` re-exports the same names
(`from ancestry_mmm.core.diagnostics_artefact import DiagnosticsArtefact,
...`) so every existing import site (`pages/06_Diagnostics.py`,
`pages/09_Project_Export.py`, `application/curve_service.py`,
`application/validation_service.py`, every test) continues to work
unchanged - a pure move-and-re-export, not a rename campaign.
Verification: `test_diagnostics_artefact.py`'s full 130 tests pass
unmodified; a new test asserting `core.diagnostics_artefact.
DiagnosticsArtefact is application.diagnostics_service.DiagnosticsArtefact`
(same object identity through the re-export, not a copy) guards against
future drift.

Expected size reduction: `application/diagnostics_service.py` drops from
~2,186 to ~1,620 lines (removing the ~570-line schema block) with zero
behavioural risk if the move-and-re-export discipline is followed
exactly.

### Phase 2 (needs characterisation tests first)

Before touching `DiagnosticsService.evaluate()`'s ~730 lines: add a
characterisation test suite (new `test_diagnostics_service_evaluate.py`)
that pins `evaluate()`'s full output for a small number of representative
synthetic fits (one Model A, one Model C, one Candidate A fit if
feasible without real data) - every section's `status`/`payload` shape,
not just a few fields. Only after that suite exists and passes against
the *current* (unrefactored) `evaluate()` should the method be split into
one private `_compute_<section>()` helper per evidence section (error
metrics, residual series, market-channel capability, search capacity,
graphical identification, latent-state identification, experiment
calibration, posterior-predictive metric distributions, and so on),
called in sequence from a much shorter `evaluate()` that assembles the
results - mirroring the pattern `run_backtest`/`run_prior_predictive_
check`/etc. already use for the sections that are already separate.
Each extracted helper should be independently reviewable in its own PR
(one evidence section at a time), not one large PR.

### Phase 3 (page-level de-coupling, largest scope - separate decision)

Reduce `pages/06_Diagnostics.py`'s 24 direct `core`/`application` imports
by routing model-building/fitting/prediction calls through
`application.model_fit_service`/`application.diagnostics_service` instead
of importing `core.hierarchical_model`/`core.market_specific_model`/
`core.models.fit_model`/`core.predict` directly. This phase has the
largest scope (the page is 2,476 lines and every current import likely
has a reason tied to a specific UI action), the least existing
characterisation coverage of the page's own behaviour, and the highest
UI-regression risk of the three phases - it should not start until
Phase 1 and Phase 2 are merged and stable, and should itself be broken
into per-tab or per-action sub-PRs rather than attempted whole.

## Explicitly out of scope for all three phases

- Any change to what a diagnostic section computes, its evidence
  semantics, or its threshold/verdict policy.
- Any change to `docs/approved_requirements/` records or `REQ-*`
  capability boundaries.
- Splitting `DiagnosticsArtefact`'s schema itself (e.g. a new schema
  version) - this plan is a code-organisation change only.
- Physical service separation (e.g. a diagnostics microservice) - root
  `AGENTS.md` already establishes that this is a scaling decision, not a
  default, and nothing here proposes it.

## Recommendation

Land Phase 1 as its own small, low-risk PR (module move + re-export,
verified by the existing 130-test suite). Treat Phase 2 as a separate
work package that starts with the characterisation-test PR alone, merged
and reviewed before any `evaluate()` restructuring begins. Treat Phase 3
as a separate, later decision - it is the largest and riskiest of the
three and should not be scheduled until Phase 1/2 are stable in
production.
