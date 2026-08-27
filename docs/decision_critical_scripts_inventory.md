# Decision-critical and evidence scripts: inventory and CI boundary

Work Package 2 (`Media-Mix-Lab Coding LLM Next Steps 2026-08-27`).

## Purpose

`scripts/*.py` sat entirely outside the normal Python lint/compile gates
before this package - the `Ruff` and `Compile + Import` CI jobs targeted
`ancestry_mmm` only. This document classifies every current script, states
what CI coverage now exists for each tier, and explains why - so a future
script is added to the right tier deliberately, not by accident.

This is descriptive/governance documentation, not requirements authority.
It does not itself approve, certify, or change any statistical, causal, or
business decision - see `docs/decision_log.md` and
`docs/approved_requirements/` for that.

## What this package found

Making `scripts/*.py` visible to real checks (`ruff check`/`ruff format
--check`, `python -m compileall`, and new import/CLI smoke tests in
`ancestry_mmm/tests/test_decision_critical_scripts_ci_coverage.py`) found
two genuine, previously-invisible defects, fixed in the same PR:

1. `scripts/run_historical_mmm_validation.py` imported
   `GOVERNED_START`/`GOVERNED_END` from `scripts.run_uk_production_fit` -
   names that script had since renamed to `COMMON_WINDOW_START`/
   `COMMON_WINDOW_END`. The import was broken; the script could not run at
   all. Fixed via an aliased import
   (`COMMON_WINDOW_START as GOVERNED_START`, etc.) rather than renaming
   every use-site, minimising the diff.
2. Three scripts (`resolve_search_spend_coverage.py`,
   `run_historical_mmm_remediation.py`,
   `run_uk_transform_identifiability_experiment.py`) were missing the
   `sys.path` shim every other script here already carries
   (`if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).
   resolve().parents[1]))`), so `python scripts/<name>.py` - the exact
   invocation style this repository already uses elsewhere (e.g.
   `run_uk_readiness.py` in `.github/workflows/tests.yml`) - would fail
   with `ModuleNotFoundError: No module named 'ancestry_mmm'`. Fixed by
   adding the same shim.

Also reformatted (whitespace only, `ruff format`, no behaviour change):
`run_historical_mmm_remediation.py`, `run_historical_mmm_validation.py`,
`run_uk_transform_identifiability_experiment.py`,
`run_uk_wp2_5_diagnostics.py`, `run_uk_wp2_6_control_prior_calibration.py`,
`run_uk_wp2_7_dna_collinearity_recheck.py`,
`run_uk_wp2_7_full_component_decomposition.py`,
`run_uk_wp2_7_short_sampler_screen.py`,
`run_uk_wp2_8_full_posterior_evaluation.py`.

## The three-tier CI boundary

| Tier | Scope | What runs | Blocking? |
|---|---|---|---|
| Ordinary package CI | `ancestry_mmm/**` | `Ruff` (lint+format), `Compile + Import`, `Mypy`, `Bandit`, `Python 3.11/3.12 tests`, `Streamlit AppTest`, `Bundle round-trip`, `pip-audit` | Yes, on every PR |
| Lightweight evidence-script CI (this package) | `scripts/*.py` (top-level only) | `Ruff` and `Compile + Import` now also target `scripts` (same job names, broader scope - no merge-gate script change needed); `ancestry_mmm/tests/test_decision_critical_scripts_ci_coverage.py` adds an import-only smoke test for every script plus a real `--help` CLI subprocess smoke test for the reusable-operational tier below | Yes (part of `Ruff`/`Compile + Import`/`Python 3.11/3.12 tests`), but cheap - no real data, no PyMC fit, no network |
| Expensive scheduled/manual recovery evidence | `scripts/wp2_named_event_response/` (own package, own tests, own `named-event-response-recovery` job); Candidate A posterior recovery; Fold refit recovery; Deterministic attribution recovery | Real MCMC / real synthetic-data recovery suites | No - schedule/manual `workflow_dispatch` only, per `scripts/wait_for_pr_green_then_merge.ps1`'s existing `-RequireCandidateARecovery`/`-RequireFoldRefitRecovery` gating |

The middle tier is new (this package). It deliberately stops at
"does this script still parse, import, and expose a working CLI" - it
never runs a real fit, never touches real Ancestry data, and never
promotes a diagnostic result to a production default (see "Diagnostic
challengers cannot silently mutate production defaults" below).

## Script classification

### Reusable operational (11 scripts)

Actively reused - either as ongoing operational infrastructure, or because
the WP2.11 hierarchy decision remains open and these are the tools that
would be re-run to gather further evidence for it (`docs/wp2_11_
hierarchy_decision_package_20260826.md`'s own "What evidence is still
needed"). Each gets, in addition to the whole-directory `Ruff`/`Compile +
Import` coverage: an import-only smoke test and a real `--help` CLI
subprocess smoke test (`ancestry_mmm/tests/test_decision_critical_
scripts_ci_coverage.py::REUSABLE_OPERATIONAL_SCRIPT_NAMES`).

| Script | Role |
|---|---|
| `run_uk_production_fit.py` | The governed UK production-fit entry point itself - the single most decision-critical script in the repository. |
| `run_uk_prefit_governance.py` | Governed WP2 pre-fit evidence sequence (`REQ-PREFIT-001`). |
| `run_uk_readiness.py` | Local-only synthetic/user-supplied UK readiness harness; already invoked directly in CI (`Windows tooling` job). |
| `run_uk_source_model_preflight.py` | WP1 (2026-08-27): source-to-model reconciliation and fold-preflight, no MCMC. |
| `run_uk_wp2_11_prepared_frame_backtest.py` | The current-hierarchy/H1/H2 prepared-frame fold-refit backtest tool; also gained WP1's `--preflight-only` mode. Still the tool WP5 of the master brief would use to gather further hierarchy evidence. |
| `run_uk_wp2_11_h1_complete_pooling.py` | H1 diagnostic hierarchy challenger full-posterior fit (`pooled_beta_reference=True`) - would be re-run for further hierarchy evidence. |
| `run_uk_wp2_11_h2_shared_pooling_scale.py` | H2 diagnostic hierarchy challenger full-posterior fit (`REQ-HIERARCHY-001`, `shared_pooling_scale=True`) - same. |
| `resolve_search_spend_coverage.py` | Writes the local, untracked UK Search-spend coverage resolution package - ongoing Search data-prep utility. |
| `run_historical_mmm_remediation.py` | Versioned historical UK MMM remediation/pre-fit package builder - reusable whenever source data is remediated. |
| `run_historical_mmm_validation.py` | Historical UK MMM validation gate without mutating source/old fits - reusable validation tool. |
| `run_uk_transform_identifiability_experiment.py` | Bounded transform/hierarchy identifiability ladder (C0-C5) - reusable diagnostic harness, explicitly never changes the production default itself. |

### Historical one-off (22 scripts, one superseded)

Each answered one specific, dated investigation item (WP2.5 through
WP2.10) whose evidence is already recorded in its own dated decision
document / `docs/decision_log.md` entry. Not forced into a
production-quality package (per this package's own brief) - each still
gets the whole-directory `Ruff`/`Compile + Import` coverage and the
import-only smoke test (catching a broken import exactly like the defect
this package found), but not an individual `--help` CLI smoke test.
`run_uk_wp2_10_prepared_frame_backtest.py` specifically is superseded by
`run_uk_wp2_11_prepared_frame_backtest.py` (which repairs the outcome-
catalogue propagation defect WP2.10's version had) and is kept only as a
historical record of that superseded state.

`run_uk_wp2_5_diagnostics.py`, `run_uk_wp2_6_circulation_check.py`,
`run_uk_wp2_6_control_prior_calibration.py`,
`run_uk_wp2_6_transform_collinearity.py`,
`run_uk_wp2_7_dna_collinearity_recheck.py`,
`run_uk_wp2_7_eta_controls_verification.py`,
`run_uk_wp2_7_full_component_decomposition.py`,
`run_uk_wp2_7_short_sampler_screen.py`,
`run_uk_wp2_8_full_posterior_evaluation.py`,
`run_uk_wp2_8_retain_analyst_rationale.py`,
`run_uk_wp2_9_divergence_localization.py`,
`run_uk_wp2_9_fit_and_temporal_diagnostics.py`,
`run_uk_wp2_9_identification_business_impact.py`,
`run_uk_wp2_9_product_level_totals.py`,
`run_uk_wp2_9_retain_analyst_rationale.py`,
`run_uk_wp2_9_sampler_sensitivity_comparison.py`,
`run_uk_wp2_10_overall_challenger.py`,
`run_uk_wp2_10_overall_challenger_evaluation.py`,
`run_uk_wp2_10_pooling_diagnostic_screens.py`,
`run_uk_wp2_10_pooling_geometry.py`,
`run_uk_wp2_10_prepared_frame_backtest.py`,
`run_uk_wp2_10_temporal_context_check.py`.

Two of these (`run_uk_wp2_6_circulation_check.py`,
`run_uk_wp2_7_full_component_decomposition.py`) have no `argparse` CLI at
all (`main()` takes no arguments and runs its fixed logic directly) -
consistent with being genuinely one-shot, not reusable with different
inputs.

### Its own dedicated package (not re-inventoried here)

`scripts/wp2_named_event_response/` already has its own compile/import
coverage (it is imported as a real module by the scheduled
`named-event-response-recovery` CI job, `uv run python -m scripts.wp2_
named_event_response.run_evaluation`) and its own conformance test suite
(`ancestry_mmm/tests/test_wp2_named_event_response_evidence.py`) -
duplicating that here would be redundant, not additive.

## Diagnostic challengers cannot silently mutate production defaults

Every hierarchy-challenger script (`run_uk_wp2_11_h1_complete_pooling.py`,
`run_uk_wp2_11_h2_shared_pooling_scale.py`, and the `--prior-config-mode`
flag on `run_uk_wp2_11_prepared_frame_backtest.py`) constructs its
diagnostic `prior_config` as `dict(runner.APPROVED_UK_MODEL_A_PRIOR_
CONFIG)` - a shallow **copy** of `scripts.run_uk_production_fit`'s module-
level default, then sets its own challenger flag
(`pooled_beta_reference=True`/`shared_pooling_scale=True`) on that copy.
`APPROVED_UK_MODEL_A_PRIOR_CONFIG` itself is never mutated in place, so
running a challenger script cannot change `run_uk_production_fit.py`'s own
default for any other caller in the same process or a later one. The
challenger mechanisms themselves (`pooled_beta_reference`,
`shared_pooling_scale`) also default to `False` inside `core.
hierarchical_model.build_fh_hierarchical_model` - every existing caller
that does not explicitly opt in is byte-for-byte unaffected
(`REQ-HIERARCHY-001`).

## Maintaining this document

When a new decision-critical or reusable script is added under
`scripts/`, add it to the appropriate table above in the same PR -
`ancestry_mmm/tests/test_decision_critical_scripts_ci_coverage.py`'s
`test_discovered_scripts_is_non_empty`/`test_every_reusable_operational_
script_name_exists_on_disk` guard against the inventory silently drifting
out of sync with what is actually on disk, but do not themselves classify
a new script correctly - that judgement belongs here.
