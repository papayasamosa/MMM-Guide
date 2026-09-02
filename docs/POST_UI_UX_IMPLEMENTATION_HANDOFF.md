# Post-UI/UX Implementation Handoff

**Updated:** 2026-09-02

This is the durable continuation record for the approved Decisions 1-19
implementation work. It records verified repository behaviour; it does not
replace the approved implementation brief, decision records, or the
`AGENTS.md` requirements hierarchy.

## 1. Durable repository state

- **Repository:** `papayasamosa/Media-Mix-Lab`
- **Branch:** `agent/post-ux-business-decisions`
- **Starting point:** `f5a070faaf6485dd556941d5fe7ca7d2a315653d`
- **Last verified production implementation HEAD:**
  `af3d192346851d3d9210ed2723600f38be07f93d`.
- **Pushed:** yes. The remote branch matched that SHA before this final
  documentation update. This is the final validated production code HEAD;
  the documentation-only commit that contains this record is the final branch
  handoff commit and is reported with its exact SHA in the delivery summary
  and the post-push CI evidence below.
- `.mcp.json`, `.playwright-mcp/`, `designs/`, `tools/`, local logs, caches,
  and machine-specific files remain deliberately outside the commits.

The implementation starts from the existing branch work. Decisions 1-19 were
not recreated. This continuation completed application wiring, persistence,
analyst-facing fail-closed behaviour, tests, and governance updates.

Durability commits created in this continuation:

- `7bc5ab1c` - Complete replay and production planning integration
- `dafdd7fb` - Wire SEO fitting and durable future assumptions
- `a57bf9fa` - Record production integration governance updates
- `87dab168` - Restore export compatibility and format integration
- `210d0d6d` - Tighten SEO replay typing
- `b6424fa8` - Reconcile Candidate A mediated attribution
- `8cceb0bb` - Stabilize CI browser and recovery checks
- `af3d1923` - Apply CI formatter output
- The final handoff documentation commit follows these implementation
  commits; its exact SHA is recorded after the push.

## 2. Decision 1-19 status

The status values in this table are limited to the six values required for
this handoff.

| Decision | Status | Verified state and remaining condition |
|---|---|---|
| 1. Outcome definitions, segments, FH LTR | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | Versioned outcome definitions, separate Family History New/DNA cross-sell/Winback outcomes, and governed FH LTR handling are wired. The app accepts governed weekly GSA or Net Bill Through series at the approved upstream boundary; it does not require raw subscriber-event reconstruction. A supplied and approved outcome series is still required for a real production fit. |
| 2. Paid Search taxonomy | **COMPLETE END TO END** | Activity Mapping validates Google/Bing and Brand/Non-Brand taxonomy; Results/Curve Bank renders posterior-draw rollups. Reporting rollups remain distinct from Search demand, delivery, cap, and mediation objects. |
| 3. SEO partial-window handling | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | The full MMM history is retained; the row-aligned SEO fit input preserves missing weeks as inactive, computes the valid observed window, and uses the fitted term only in that window. UK GSC coverage appears to begin week commencing 2024-11-11 while the MMM history is approximately 2023-07-01 to 2026-06-28. Before the valid GSC window the source is unavailable/missing: the app does not shorten the MMM window, backfill or impute observations, encode them as zero, or invent a minimum-week threshold. A governed GSC positional-visibility series is required before this path can produce a real fit. |
| 4. Paid Search reporting rollups | **COMPLETE END TO END** | The taxonomy rollup is called by the analyst-facing results path and preserves leaf, intent-parent, and total levels with explicit reporting semantics. |
| 5. SEO positional visibility | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | The approved impression-weighted positional-visibility metric is computed from GSC fields, uploaded through Model Training, fitted through both model builders, persisted, restored by Diagnostics, and reported as SEO visibility. GSC observations are still external; the partial-window policy above applies. |
| 6. SEO causal contribution role | **PARTIALLY IMPLEMENTED** | The current release has a live, window-gated reduced-form `visibility -> final outcome` term that estimates an SEO visibility contribution and keeps SEO out of spend-based CPA/ROI/ROAS. This is deliberately not labelled an organic-traffic mediation decomposition. Under the approved current-release decision, the structural `visibility -> organic traffic/clicks -> outcome` decomposition is a future/conditional enhancement, not a reason to block the reduced-form path. If it is later required, the exact missing source is market-week organic traffic or organic-click observations from GSC/analytics, together with an approved joint mediator/identification specification; uploaded clicks are diagnostic-only today. |
| 7. No spend-based SEO ROI | **COMPLETE END TO END** | SEO output rows have no fabricated spend, CPA, ROI, or ROAS. Value contributions may be shown only where the selected outcome has a valid governed value. |
| 8. SEO date meaning | **COMPLETE END TO END** | No SEO boundary, truncation, intervention, or modelling meaning is attached to the disputed historical calendar date; the repository regression check remains green. |
| 9. Google Trends Brand Demand / Candidate A | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | The approved Trends anchor boundary, query-set metadata, complete weekly validation, fit-time PyMC term, posterior-draw final-outcome replay, uncertainty propagation, upstream direct/mediated/total attribution, official curves, sequential Scenario Planner, and sequential Optimiser wiring are present. The path fails closed without valid fit-time replay evidence, the approved query set, and live Trends observations. |
| 10. Search capacity cap | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | Candidate A represents latent demand, capped delivery, captured demand, unmet demand, cap-hit state, and binding probability separately. Historical cap evidence and explicit future caps are required; absent caps fail closed and cannot be replaced by realised spend. |
| 11. Experiment prior/calibration | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | Applicable positive-lift experiment records are mapped through the governed registry and attached to the real shared and market-specific raw-PyMC builders as outcome-scale calibration terms, with provenance and applicability checks. Calibration infrastructure is connected to real model fitting; a valid compatible experiment record is required for a concrete calibrated fit. |
| 12. Named-event timing | **COMPLETE END TO END** | Fit-time event-family terms, fit-pinned metadata, NumPy replay, sequential simulation, terminal response, Diagnostics/backtests, optimisation callers, persistence, identity/staleness checks, and the exact long NUTS recovery test are wired and verified. |
| 13. Finance constant-dollar FX | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | FX upload validation, annual rate-set versioning, Finance constant-dollar mode, approval/fingerprint checks, persistence, approved pair/as-of resolution, and official monetary-curve wiring are complete. No Ancestry Finance-approved rate values are invented or present. |
| 14. Minimise manual future assumptions | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | The future-assumption bundle is system-generated and persisted for trend/Fourier continuation, latent-baseline context, promotions, controls, and cost/translation inputs. Analysts are not asked to enter demand, seasonality, or baseline values that the model/system can generate, and realised values are never silently reused as future assumptions. A governed forward valuation/value mapping remains an external input where expected monetary outcomes are requested. |
| 15. Evidence-based time-varying baseline | **COMPLETE END TO END** | The existing intercept/trend/Fourier baseline remains the governed model process; residual level-shift diagnostics and persistence are live. No unsupported baseline forecast is introduced. |
| 16. Optimiser objectives, constraints, sequential parity | **IMPLEMENTATION COMPLETE, EXTERNAL DATA REQUIRED** | The application-facing ScenarioService and Optimiser default to the same sequential-weekly T1/O1 response kernel used by Scenario Planner; steady-state monthly remains an explicit diagnostic/legacy route. Objective and constraint gating is wired. `maximise_profit` is unavailable until an approved COGS/margin/profit definition is supplied. |
| 17. Per-channel support diagnostics | **COMPLETE END TO END** | Consolidated support classification, evidence, and governance labels are available in Diagnostics. |
| 18. General capacity constraints | **COMPLETE END TO END** | The current general capacity plan and Candidate A Search capacity are integrated with Scenario Planner and Optimiser. No architectural G3 generalisation is added without a second concrete constrained pathway; that is not a blocker for the approved current scope. |
| 19. PathMC | **DEFERRED** | No PathMC dependency, adapter, or UI was added. The supplemental structural-causal-engine decision remains deliberately deferred. |

### Reconciliation of previously gated items

- **Candidate A:** final-outcome replay is now a per-posterior-draw path, not a
  standalone contract. For each draw, structural replay isolates the Search
  effect caused by upstream demand-driving media, including the nonlinear cap,
  and Shapley allocation reconciles identifiable upstream channels. Analyst
  output exposes each channel's direct effect, realised mediated-through-Search
  effect, and total effect (`direct + mediated`). The separate Search pathway
  view is explicitly non-additive, so it is not counted again in official media
  totals, waterfalls, curves, or optimisation. These outputs reach attribution,
  waterfalls, official curves, sequential scenarios, and sequential
  optimisation. Missing fit-time Search evidence or future caps still fails
  closed. Live Trends observations and an approved query set remain external
  data requirements.
- **SEO:** Decisions 3 and 5 have a live fit boundary. Decision 6 has a live
  reduced-form `visibility -> final outcome` contribution estimate, correctly
  labelled as such and not as an organic-click mediation decomposition. The
  structural decomposition is not mandatory for the current release under the
  approved requirement/decision record. If it is later approved, the missing
  fields/source and identification input are explicit above; the absence of
  live GSC data is not being confused with unwired software.
- **Experiment calibration:** the adapter is connected to real model fitting;
  a valid experiment record is the remaining external requirement. It is not
  deferred merely because the application uses the approved raw-PyMC adapter
  rather than a `pymc_marketing.MMM` wrapper.
- **FX:** values, source vintage, approval owner/time, and rate-set coverage
  must come from Finance. The application boundary is complete and fails
  closed for an absent or unapproved pair.
- **Future values:** trend, seasonality, baseline, promotions, and controls
  are system/model context. A forward value mapping is needed only for an
  expected-value request when no governed catalogue is available; no realised
  history is copied silently.
- **Profit optimisation:** unavailable, not approximated. COGS/margin/profit
  is the specific missing business input.
- **Search capacity:** the current general capacity plan plus Candidate A cap
  path is retained. G3 is not generalised without another real constrained
  pathway.
- **PathMC:** correctly deferred.

## 3. Production-integration audit

| Analyst-facing path | Result |
|---|---|
| Model fitting | Model Training validates and passes outcome, SEO, Candidate A, calibration, named-event, and future-role inputs through the application service to the shared and market-specific PyMC builders. Invalid role/source combinations block the fit. |
| Diagnostics | Fit-pinned SEO/Candidate A/calibration payloads are restored for rebuild; SEO window and contribution diagnostics are visible; Candidate A fold refit/backtest remains explicitly fail-closed because the page does not yet collect per-fold Search observations. |
| Scenario Planner | Sequential weekly is the official default and uses the weekly carry-in replay. Candidate A uses explicit future Search caps and per-draw final-outcome replay. Steady-state is labelled diagnostic/legacy and is blocked for Candidate A. Future-assumption bundles persist with the scenario. |
| Optimiser | The app-facing Optimiser uses the same sequential weekly kernel as Scenario Planner. Capacity constraints and governed objective preconditions are enforced. Profit remains unavailable without COGS/margin/profit evidence. |
| Results / response curves | Candidate A Search-mediated and SEO visibility contributions are explicit result/waterfall rows. Official curves require complete replay inputs and explicit caps; monetary curves require valid cost/FX evidence. |
| Project persistence | Schema migration and round-trip paths preserve SEO fit inputs, Candidate A anchor/replay provenance, calibration provenance, FX sets, future-assumption bundles, scenarios, diagnostics, registries, workflow checkpoints, and fingerprints. |
| Exports | Project Export retains the durable bundle as the recovery object, preserves the new config payloads, keeps the ZIP uploader compatible with the existing import journey, and exposes clear missing-evidence messages. |

### Candidate A attribution audit

The final correction was audited against `REQ-SEARCH-002` at posterior-draw
level. The replay zeros only upstream demand-driving media in the no-upstream
counterfactual; fitted Search baseline demand remains, so residual Search is
not misreported as media. Direct, realised-mediated-through-Search, and total
effects reconcile draw by draw. Multiple upstream channels use the structural
replay and cap-aware Shapley allocation; correlated channels are not allocated
by spend, click share, direct share, or the retired generic reallocation
helper. A channel's total is exactly its direct plus mediated effect, and the
sum of channel totals bridges to the official media total. The generic Search
pathway row is a separate, explicitly non-additive view. Regression fixtures
cover one and multiple upstream channels, correlated media, binding and
non-binding caps, zero upstream effect, exact posterior-draw reconciliation,
and no double counting in summaries and waterfalls.

## 4. Long real-model validation continuation point

The first local attempt was stopped and is not itself a passing result. The
same run was then resumed from a clean, committed branch state and completed
successfully; the interruption remains documented so a later agent can repeat
the evidence rather than treating a partial sample as a pass.

- **Exact command:**

  ```powershell
  .venv\Scripts\python.exe -m pytest ancestry_mmm/tests/test_named_event_response_recovery_posterior.py -q --no-cov
  ```

- **Configuration:** the test's integrated PyMC model uses NUTS with two
  chains, `cores=1`, `target_accept=0.9`; the individual recovery tests use
  200 draws/tune for the two direction checks and 250 draws/tune for interval
  coverage. The negative control builds the same synthetic frame without
  event inputs.
- **Historical stopped stage:** synthetic data and the integrated model graph
  were built; the process reached real NUTS sampling.
- **Why it was stopped:** the earlier run was stopped to preserve a durable
  committed/pushed repository state rather than leave a long local process and
  uncommitted integration work running.
- **Observed runtime estimate:** approximately 66 minutes on the Windows
  environment without a C compiler; this is not a guarantee.
- **Passing result:** all four tests pass, including event-week separation,
  draw-level directional probability, credible-interval recovery, and the
  no-event negative control.
- **Resumed result on this continuation:** the exact command completed with
  `4 passed in 4709.86s (1:18:29)`.
- **Resume instruction:** run the exact command from a clean checkout of this
  branch in the project `.venv`, one copy at a time. For CI, dispatch the
  repository's schedule/manual recovery job. Never classify an interruption,
  timeout, or partial sample as a pass.

## 5. Verified tests and quality state

- Exact long named-event NUTS recovery: **4 passed in 4709.86s
  (1:18:29)**.
- Complete repository PR CI on exact implementation SHA
  `af3d192346851d3d9210ed2723600f38be07f93d`: **run 33611093424 passed**.
  Python 3.11 and 3.12 tests passed with their coverage gates; Compile +
  Import, Mypy, Ruff, Bandit, pip-audit, bundle round-trip, Streamlit
  AppTest, browser lifecycle, Requirements index, and Windows tooling all
  passed. Manual-only recovery gate checks were intentionally skipped in that
  pull-request run.
- Affected-path recovery on the same SHA: manual workflow **run 33611176082**
  **passed**. Candidate A posterior recovery, named-event
  integration/response evidence, deterministic attribution recovery, browser
  lifecycle, Mypy, bundle, tooling, fold-refit recovery, and both Python test
  jobs passed.
- Candidate A attribution regression suite: **13 passed**; deterministic
  simulation recovery: **6 passed**. The browser lifecycle journey: **5
  passed**. The focused CI-equivalent Mypy checks report no issues; the full
  core debt-ratchet remains at its approved **225-error ceiling**.
- Persistence round trip: **227 passed in 78.10s**.
- Focused replay/SEO/sequential/waterfall boundaries: **129 passed** in the
  earlier focused run, plus the post-format integration run above.
- Ruff check: clean for `ancestry_mmm` and `scripts`.
- Ruff format check: clean; **459 files already formatted** after formatting
  the 27 touched Python files.
- `python -m compileall -q ancestry_mmm`: clean.
- Graphify refresh: completed through the required D-drive wrapper; local
  graph output was refreshed and remains ignored development tooling output.
- Mypy: the new SEO replay typing findings are resolved. A focused run still
  reports the existing NumPy/ArviZ `Any` and missing-annotation baseline in
  `predict.py` and `market_specific_predict.py`; no new SEO-specific error
  remains.
- Browser smoke: the real Streamlit app reached Fit Model, Model Diagnostics,
  Scenario Planner, and Export & Recovery through the sidebar on an isolated
  local server. No-data states were explicit and the post-navigation browser
  console check was clean. Synthetic/no-data state only; no browser MCMC fit
  was run.
- No C/C++ compiler was installed or configured during this correction. The
  local PyTensor check recorded `pytensor.config.cxx == ""`, no working
  compiler, and fallback warnings for `g++`; the long local NUTS run therefore
  used the slower non-compiled path. This is an environment limitation, not a
  model result.

## 6. Remaining engineering work

1. Import the first approved external production data packages and rerun the
  relevant fit/approval evidence: governed weekly outcomes, GSC visibility,
  Google Trends, Search caps, Finance FX, and experiment records as supplied.
2. If the business later approves the full structural SEO mediator
   decomposition, add the approved organic traffic/click source and
   identification design; keep the current reduced-form visibility path and
   its labels distinct. This is not required to release the current reduced-
   form Decision 6 implementation.
3. Add leakage-safe Candidate A per-fold Search observation collection before
   enabling Candidate A fold refit/backtest outputs.
4. Repeat Candidate A recovery and run supplied real-experiment calibration
   validation when external inputs or model changes justify it.

## 7. External blockers

- Approved weekly GSA or Net Bill Through outcome series and its governed
  source metadata for a production fit; raw subscriber events are not required
  by the current approved boundary.
- Live Google Trends observations and approved branded-query list, geography,
  date range, and extraction metadata.
- Governed historical Search delivery/cap observations and future cap inputs.
- Market-week organic traffic/organic-click observations and an approved
  structural mediator specification if the full SEO decomposition is required.
- A valid applicable positive-lift experiment record for calibration.
- Finance-approved annual FX values, rate-set source vintage, approval metadata,
  and required currency-pair coverage.
- Governed forward outcome value mapping where expected monetary outcomes are
  requested and no approved catalogue is present.
- Approved COGS, margin, or profit definition for `maximise_profit`.

## 8. Deliberately deferred work

PathMC remains deferred. Capacity compiler G3 is not generalised beyond the
current general capacity plan plus Candidate A because no second constrained
pathway requires it. Automatic historical realised-value reuse, invented FX or
Trends values, unsupported baseline processes, and an ungoverned profit
objective were not added. The structural organic-click SEO decomposition is a
future/conditional enhancement under the current approved release decision,
not an unlabelled claim about the reduced-form implementation.

## 9. Next-agent first task

First verify the pushed final branch SHA and the documentation-triggered CI
result, then import the first approved external data package supplied by the
owner and run the corresponding fit/diagnostics/approval path. Do not recreate
Decisions 1-19 or reopen PathMC. If no external package is available, record a
scheduled Candidate A recovery result without changing the fail-closed gates.
