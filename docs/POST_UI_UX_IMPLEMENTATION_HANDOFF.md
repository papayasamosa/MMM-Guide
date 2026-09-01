# Post-UI/UX Implementation Handoff

**Updated:** 2026-09-01

This is the durable continuation record for the approved Decisions 1–19
implementation work. It records the repository state and verified code paths;
it does not replace the approved implementation brief, decision records, or
`AGENTS.md` requirements hierarchy.

## 1. Durable repository state

- **Repository:** `papayasamosa/Media-Mix-Lab`
- **Branch:** `agent/post-ux-business-decisions`
- **Final implementation HEAD SHA:** `958e639d` (the last code-integration
  commit before this documentation-only handoff commit).
- **Pushed:** pending final handoff push; the branch was pushed through
  `5e54cb2a` before this final integration pass, and the two integration commits
  below are now committed locally with this handoff.
- **Working tree policy:** `.mcp.json`, `.playwright-mcp/`, `designs/`, and
  `tools/` are local development artefacts and are deliberately excluded from
  commits. No logs, caches, secrets, or machine-specific files are in scope.

The implementation starts from the existing branch work. Decisions 1–19 were
not recreated. The final integration changes add only the missing application
boundaries, fit-time provenance, persistence, fail-closed UI paths, tests, and
this corrected handoff.

Commits created in this durability pass:

- `16b53076` — Wire Candidate A and governed FX boundaries
- `958e639d` — Wire calibration and governed value assumptions
- Final handoff commit — this document; the exact resulting branch SHA is
  reported with the push verification and is the only documentation-only
  commit after `958e639d`.

## 2. Decision 1–19 status

The status text in the table is intentionally limited to the six values required
for this handoff.

| Decision | Status | Verified state and remaining condition |
|---|---|---|
| 1. Outcome definitions, segments, FH LTR | **BLOCKED BY EXTERNAL BUSINESS INPUT** | Distinct outcome registry, segment handling, governed valuation and FH LTR horizon are implemented. Subscriber-event reconstruction is not wired into default ingestion because the approved privacy/raw-event input boundary is absent. An approved source and privacy review are required before that path can be added. |
| 2. Paid Search taxonomy | **COMPLETE END TO END** | Activity Mapping validates Google/Bing × Brand/Non-Brand taxonomy; Results/Curve Bank renders governed posterior-draw rollups. The rollup remains reporting-only and is not substituted for demand, delivery, cap, or mediation. |
| 3. SEO partial-window handling | **IMPLEMENTED BUT NOT FULLY WIRED** | The tested partial-window policy exists, but there is no live SEO fitting pathway in the current model builders for it to consume. |
| 4. Paid Search reporting rollups | **COMPLETE END TO END** | The taxonomy rollup is called by the analyst-facing results path and preserves leaf, intent-parent, and total levels with explicit reporting semantics. |
| 5. SEO positional visibility | **IMPLEMENTED BUT NOT FULLY WIRED** | The governed impression-weighted visibility metric is implemented and tested; no live SEO model pathway currently consumes it. |
| 6. SEO causal contribution role | **IMPLEMENTED BUT NOT FULLY WIRED** | The approved mediator/capture-efficiency role and policy are documented and tested, but no live SEO pathway exists to fit or report it. |
| 7. No spend-based SEO ROI | **COMPLETE END TO END** | The prohibited £5k/month SEO assumption is absent; SEO cannot receive spend-based CPA/ROI/ROAS without a separate governed cost basis. |
| 8. 28 August 2023 SEO meaning | **COMPLETE END TO END** | No SEO boundary or truncation meaning is attached to that date; regression coverage protects against reintroduction. |
| 9. Google Trends Brand Demand / Candidate A | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | Candidate A now accepts fit-time `GoogleTrendsAnchorFitInputs`; the Model Training boundary validates approved query-set metadata, complete weekly series, and 0–100 rescaling, and the shared PyMC Candidate A graph observes the anchor with an explicit scale. Project export/import and Diagnostics rebuild preserve it. A real Google Trends series and approved branded-query list are still required before live Candidate A fitting; no query list or series is invented. Candidate A’s final-outcome NumPy replay/planning path remains fail-closed until its search-mediated outcome contribution is supported. |
| 10. Search capacity cap | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | The latent-demand → capped delivery → captured/unmet demand contract, cap-hit states, and identification gate are implemented for Candidate A. Real Search delivery/cap observations and evidence are required for a production fit and eligibility. |
| 11. Experiment prior/calibration | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | Valid compatible positive-lift experiments can now be mapped from the governed registry and attached to the real raw-PyMC shared and market-specific builders as fit-time outcome-scale Gamma calibration terms. Applicability, target outcome, direct-primary pathway, positive lift, and fit provenance are validated; the adapter is intentionally narrower than PyMC-Marketing’s full `MMM` wrapper. A valid experiment record is still required to execute calibration. Prior-only and unsupported comparison uses remain evidence-only. |
| 12. Named-event timing | **COMPLETE END TO END** | Fit-time event-family response terms, fit-pinned metadata, NumPy replay, sequential simulation, diagnostics/backtests, terminal response, optimisation callers, persistence, and identity/staleness checks are wired. The prior expensive synthetic NUTS recovery evidence passed; the next run remains a scheduled/manual statistical recheck. |
| 13. Finance constant-dollar FX | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | FX records/rate sets, annual frequency, Finance constant-dollar method, manual upload validation, versioning, fingerprint revalidation, persistence, approved-set resolution by currency pair/as-of date, and official monetary-curve wiring are implemented. No actual Ancestry Finance rate is present. A pending/unapproved set or missing pair blocks approved-set use; same-currency identity is the only implicit identity conversion. Finance must provide and approve the real rate set. |
| 14. Minimise manual future assumptions | **PARTIALLY IMPLEMENTED** | Trend/Fourier continuation and structured promotion periods are wired. Scenario Planner now offers an explicit, opt-in suggestion from governed historical valuation records and never silently applies or reuses realised values as future assumptions. The analyst must accept/store the suggestion or enter an explicit forward value; the general future-assumption bundle composition remains unfinished. |
| 15. Evidence-based time-varying baseline | **COMPLETE END TO END** | Evidence supported retaining the existing intercept/trend/Fourier baseline rather than adding an unvalidated new process. The residual level-shift diagnostic is live in Diagnostics. |
| 16. Optimiser objectives, constraints, sequential parity | **PARTIALLY IMPLEMENTED** | Objective/constraint vocabulary and sequential-weekly T1/O1 optimiser wiring are live and tested. Profit optimisation remains fail-closed: no governed COGS/margin/profit definition exists, so `maximise_profit` is visible but unavailable. The default steady-state monthly route remains separate and labelled. |
| 17. Per-channel support diagnostics | **COMPLETE END TO END** | Consolidated data-support classification is live in Diagnostics with evidence and governance labels. |
| 18. General capacity constraints | **PARTIALLY IMPLEMENTED** | The general capacity-plan application and optimiser/Scenario Planner integration are live and tested. The second concrete pathway needed to generalise compiler G3 beyond Candidate A does not exist, so that sub-question remains deliberately open; Search-specific cap semantics are covered by Decision 10. |
| 19. PathMC | **DEFERRED** | No PathMC dependency, adapter, or UI was added. The supplemental structural-causal-engine decision remains deferred. |

### Specific reconciliation of previously gated items

- **Google Trends Candidate A:** this is not an unwired module. The application
  boundary and shared fitting graph are connected. The remaining status is
  `IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED` because the live Trends
  observations and approved query set are not in the repository.
- **Experiment calibration:** this is not blocked by the absence of a
  `pymc_marketing.MMM` object. A documented raw-PyMC adapter now attaches the
  supported direct-primary positive-lift calibration term to real fitting. A
  concrete valid experiment is the remaining external data requirement.
- **FX:** upload/validation/versioning/persistence and official monetary-curve
  resolution are connected. Finance-approved rates and approval metadata are
  intentionally absent; no values were invented.
- **Future value assumptions:** the editor does not auto-copy realised values.
  It can display a governed historical-rate suggestion, but application is an
  explicit analyst action. Without a governed valuation catalogue, the exact
  missing input is an explicit forward value, currency, and outcome/segment
  scope—not an unspecified “external decision”.
- **Profit optimisation:** the objective remains visible but blocked because
  the repository has no approved COGS, margin, or profit definition. ROI/CPA
  objectives remain separately governed.
- **Search capacity:** Candidate A fit-time capacity semantics and Diagnostics
  provenance are wired. Final-outcome replay, ordinary scenario planning, and
  optimisation still fail closed for Candidate A until the replay includes the
  search-mediated contribution and the required external observations/evidence
  exist.

## 3. Production-integration audit

| Analyst-facing surface | Result |
|---|---|
| Model fitting | Model Training passes validated Candidate A fit inputs, Google Trends anchor metadata, and applicable experiment calibration inputs through `application.model_fit_service` to both raw-PyMC builders. Invalid/missing boundaries stop the fit. |
| Diagnostics | Fit-time Candidate A arrays/anchor and calibration payload are restored for rebuild; fingerprints include calibration identity; missing provenance fails closed. Data-support and residual-baseline diagnostics remain live. |
| Scenario Planner | Sequential evaluation and optimiser paths use the existing shared services; promotion periods, capacity limits, explicit value assumptions, and opt-in value suggestions are visible. Candidate A final-outcome replay remains blocked rather than producing incomplete numbers. |
| Optimiser | Objective/constraint vocabulary, capacity limits, and sequential T1/O1 evaluation are wired. Profit is clearly unavailable; Candidate A final-outcome optimisation is fail-closed. |
| Results / Curve Bank | Search reporting taxonomy and calibration/model identity disclosures are carried into analyst-facing result/curve identity paths. Monetary economics are blocked when cost or FX evidence is missing. |
| Project persistence | Schema migrations and round trips preserve FX rate sets/records, Google Trends anchor and Candidate A fit arrays, calibration fit provenance, scenarios, registries, and existing project fields. |
| Exports | Project Export provides Finance FX upload/validation and includes the durable FX/Trends/Candidate A fields in bundles. Official monetary curves consume an approved stored rate set by pair/as-of date where available and surface missing evidence before generation. |

## 4. Long real-model validation continuation point

This is **VALIDATION NOT COMPLETED**, not a passing result and not an
implementation failure.

- **Command/configuration:** from the repository root, use the repository
  environment and run:

  ```powershell
  .venv\Scripts\python.exe -m pytest ancestry_mmm/tests/test_named_event_response_recovery_posterior.py -q --no-cov
  ```

  The recovery test uses the real integrated PyMC model and NUTS with the
  file’s governed configuration (200–250 draws, 200–250 tune, 2 chains); it
  is schedule/manual-only in CI.
- **Stage reached:** the synthetic frame and integrated model graph were built;
  the long sampling run was in the real NUTS execution stage when this
  continuation was stopped. No passing result is recorded for the stopped run.
- **Why stopped:** preserve a durable committed/pushed repository state rather
  than leave a long local process and uncommitted integration work running.
- **Expected runtime:** approximately 66 minutes on the observed Windows
  environment without a C compiler; a compiled CI runner may be faster. This
  is an estimate, not a guarantee.
- **Passing result:** all four recovery tests pass, including event-week
  separation, posterior probability/credible-interval recovery, and the
  no-event negative control, with no new diagnostics failure.
- **Resume:** run the command above from a clean checkout of this branch in the
  project `.venv`, one copy at a time. For CI, dispatch the repository’s
  schedule/manual recovery job. Do not classify a timeout/interruption as a
  pass; retain the result and runtime in this section.

## 5. Verified tests and quality state

Verified during this continuation:

- Focused persistence and new integration boundaries: **232 passed**.
- Final affected sweep: **495 passed in 10 minutes 35 seconds**. An earlier
  460-test sweep had one test-harness failure because the new regression test
  omitted its `tmp_path` fixture; that was corrected and rerun successfully.
- Official Curve Generation AppTests plus integration boundaries: **25 passed**.
- Final post-integration boundary tests: **7 passed**.
- Ruff check: clean on touched production/test files.
- Ruff format check: clean on touched production/test files.
- `python -m compileall -q ancestry_mmm`: clean.
- Application mypy scope: clean, 22 source files.
- Planning-core mypy scope: clean, 9 source files.
- Full-core mypy ratchet: **225 existing errors**, matching the repository
  baseline; the touched builder files retain the known PyTensor `Any` return
  diagnostics and did not increase the baseline.
- Streamlit browser smoke: real sidebar navigation to Fit Model and Export &
  Recovery on an isolated local server rendered the expected no-data blocking
  states with zero console errors after actual navigation. Synthetic data only;
  no browser MCMC fit was run.
- Graphify AST graph was refreshed after the structural changes. Its generated
  local output is not part of the feature commit unless already intentionally
  tracked.

The complete repository suite, the manual NUTS recovery run, and the known
schedule-only capacity recovery run are not claimed as passing in this
handoff. Existing repository-wide limitations include the local PyTensor
missing-C-compiler Candidate A recovery failures and a possible Windows
command-line-length failure in a requirements-index collection test; these are
separate from the focused production-integration validation above.

## 6. Remaining engineering work

1. Run the long real-model recovery command in §4 and record the actual result.
2. Add the remaining Candidate A final-outcome replay/uncertainty path before
   enabling ordinary curves, scenarios, or optimisation for Candidate A.
3. Complete the general future-assumption bundle composition and any missing
   SEO fitting pathway when those approved pathways exist.
4. Generalise capacity compiler G3 only after a second concrete constrained
   pathway is present.
5. Run the complete repository/CI suite in its intended jobs after the final
   branch is available to CI.

## 7. External blockers

- Finance-approved annual FX values, source vintage, approval owner/time, and
  the required rate-set coverage.
- Live Google Trends observations and the approved branded-query list/geography
  for Candidate A.
- A valid, applicable experiment record for a concrete calibration run.
- Approved subscriber-level event source/privacy review if Decision 1’s
  reconstruction path is required.
- Approved COGS/margin/profit definition for profit optimisation.
- Any external SEO source/pathway required to make Decisions 3, 5, and 6 live.

## 8. Deliberately deferred work

PathMC remains deferred. Candidate A final-outcome replay/optimisation is
fail-closed pending its missing support; it is not silently approximated.
Unvalidated new baseline processes, invented FX values, invented Trends query
sets, automatic historical value reuse, and an ungoverned profit objective were
not added.

## 9. Next-agent first task

First resume the §4 long real-model validation command from this branch and
record whether it passes. Do not recreate Decisions 1–19 or reopen PathMC;
after the validation result, address only the remaining Candidate A replay gate
or the concrete external-data import supplied by the owner.
