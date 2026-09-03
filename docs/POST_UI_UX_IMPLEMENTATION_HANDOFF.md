# Post-UI/UX Implementation Handoff

**Updated:** 2026-09-03

This is the durable continuation record for the approved Decisions 1-19
implementation work. It records verified repository behaviour; it does not
replace the approved implementation brief, decision records, or the
`AGENTS.md` requirements hierarchy.

## 1. Durable repository state

- **Repository:** `papayasamosa/Media-Mix-Lab`
- **Branch:** `agent/production-data-onboarding`
- **Starting point:** merged `main` at
  `980af30f6b923df206d97709a005e78437dd8115`
- **Scope:** production-data onboarding integration only. Decisions 1-19 and
  the approved post-UI/UX implementation were inherited; no production data
  has been imported and no production MMM fit has been run.
- **Final validated implementation/test HEAD:**
  `a5e1456f` (`test: cover exploratory join confirmation`). The final
  documentation commit follows this validated code/test state; the final
  branch HEAD and push state are recorded in the durability list and delivery
  summary.
- **Pushed:** pending the final scoped commits and PR publication.
- `.mcp.json`, `.playwright-mcp/`, `designs/`, `tools/`, local logs, caches,
  and machine-specific files remain deliberately outside the commits.

The implementation starts from the merged branch work. Decisions 1-19 were
not recreated. This continuation adds the missing analyst-facing production
input boundaries, exact persistence, Candidate A fold slicing, and explicit
exploratory-join safety.

Durability commits created on this branch:

- `18252a94` - Add governed Candidate A onboarding boundaries
- `060a8120` - Persist governed valuation and future assumptions
- `a5e1456f` - Cover exploratory join confirmation in the AppTests
- The final handoff documentation commit follows these validated commits;
  its exact SHA and final branch HEAD are recorded in the delivery summary.

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
| Diagnostics | Fit-pinned SEO/Candidate A/calibration payloads are restored for rebuild; SEO window and contribution diagnostics are visible; Candidate A backtest and historical fold refit now slice the exact fit-pinned Search/Trends rows per fold and fail closed when row identity is absent or incomplete. A real long fold validation has not been run on production data. |
| Scenario Planner | Sequential weekly is the official default and uses the weekly carry-in replay. Candidate A uses explicit future Search caps and per-draw final-outcome replay. Steady-state is labelled diagnostic/legacy and is blocked for Candidate A. Future-assumption bundles persist with the scenario. |
| Optimiser | The app-facing Optimiser uses the same sequential weekly kernel as Scenario Planner. Capacity constraints and governed objective preconditions are enforced. Profit remains unavailable without COGS/margin/profit evidence. |
| Results / response curves | Candidate A Search-mediated and SEO visibility contributions are explicit result/waterfall rows. Official curves require complete replay inputs and explicit caps; monetary curves require valid cost/FX evidence. |
| Project persistence | Schema 24 round-trip paths preserve SEO fit inputs, Candidate A anchor/replay provenance and row keys, weekly valuation records, calibration provenance, FX sets, future-assumption bundles, scenarios, diagnostics, registries, workflow checkpoints, and fingerprints. |
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
- Current onboarding/Search boundary suite: **33 passed in 22.91s** without
  coverage collection. This covers exact Candidate A upload alignment and
  cap-scale validation, missing-row rejection, fit-pinned fold slicing,
  valuation parsing and bundle round-trip, scenario-assumption persistence,
  and blank-template safety.
- Current persistence/Search/onboarding regression batch: **253 passed in
  117.51s** without coverage collection.
- Current affected analyst-facing AppTest batch: **77 passed in 495.95s**
  without coverage collection after updating the expected template surface.
- Current synthetic fold/refit/planning batch: **44 passed in 26694.97s
  (7:24:54)** without coverage collection. This is synthetic affected-path
  evidence only; it is not production-data evidence and did not run a
  production fit.
- The exact final blocking CI-equivalent command was run against the validated
  implementation/test state above and exited successfully: **4,811 passed, 2
  skipped in 28,271.92s (7:51:11)**, coverage **87.86%**, exit 0. The initial
  rerun exposed three stale Transform Pipeline AppTest interactions after the
  explicit exploratory-inner-join confirmation was added; those tests were
  updated in `a5e1456f` and the complete command below was then rerun cleanly.

  ```powershell
  .venv\Scripts\python.exe -m pytest ancestry_mmm/tests/ -q --ignore=ancestry_mmm/tests/test_persistence.py --ignore=ancestry_mmm/tests/test_official_lifecycle_browser.py --ignore=ancestry_mmm/tests/test_causal_graph_editor_browser.py --ignore=ancestry_mmm/tests/test_search_candidate_a_recovery_posterior.py --ignore=ancestry_mmm/tests/test_fold_refit_service_recovery.py --ignore=ancestry_mmm/tests/test_named_event_response_recovery_posterior.py --cov --cov-report=term-missing:skip-covered --cov-fail-under=75
  ```

- Ruff check: clean for `ancestry_mmm` and `scripts`.
- Ruff format check: clean after formatting the touched Python files.
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
3. Run approved production fold/backtest evidence after the external data is
  supplied. The synthetic affected-path validation for the new fit-pinned
  Candidate A row slicing has already passed; the production fold path is
  wired and fails closed when row identity is absent or incomplete.
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

First verify the pushed final branch SHA and CI result, then review the
production onboarding package below with the owner. Do not import production
data or start a production NUTS fit until that package is explicitly approved.

## 10. Production onboarding package

The following inventory is the contract for the first UK run. The modelling
window remains the full approved weekly history (approximately July 2023
through 28 June 2026). No pre-November-2024 GSC values are requested or
fabricated.

### A. Inputs required for the minimum core count fit

| Input | Exact contract and meaning | Grain, coverage and units | App path/template | Missing impact |
|---|---|---|---|---|
| Governed weekly outcome series | The approved outcome to model: GSA, sign-up, Gross Bill Through, Bill Through, or Net Bill Through only after its definition is approved. Standard Outcomes uses wide columns `period_start`, `market`, and one column per approved `source_column`; `outcome_dictionary` defines `outcome_id`, `source_column`, product, metric, segment, definition version, event/date/cohort basis, maturity, exclusions, reconciliation source, owner, unit and aggregation. | One row per market-week; weekly; full model window; non-negative count units. Supply separate FH New, DNA cross-sell and Winback measures where in scope. | Required. Standard upload/import and definition-draft review exist. Template `ancestry-mmm-outcomes-v2-template.xlsx`. | Blocks the core fit if no approved outcome exists. Raw subscriber events are not required; governed weekly upstream outcomes are accepted directly. |
| Activity/media model inputs | Standard tidy-long `activity_data`: `period_start`, `market`, `activity_id`, plus declared measure columns. `activity_dictionary` must identify channel, platform, campaign type, objective, funnel stage, product, message, ownership, model role, model input column/measure/unit/kind, spend/response fields, currency, effective dates and planning eligibility. | One row per market-week-activity; weekly; unique keys and selected fit coverage. Units are declared per activity: spend, impressions, clicks, GRPs/TVRs or another governed model-input unit. | Required for a media fit. Standard workbook adoption exists. Template `ancestry-mmm-activity-and-media-template.xlsx`. | Blocks a useful media fit if no activity source exists; a missing optional channel only removes that channel. |
| Context source-pack domain | Standard tidy-long `context_data`: `period_start`, `market`, `variable_id`, `value`, `native_frequency`; `variable_dictionary`: `variable_id`, `variable_class`, `native_frequency`, `role`, source/scope/unit/effective dates. The logical domain is required; an arbitrary context variable is not forced into the model. | Native frequency and coverage explicit. Weekly controls align to the weekly window; monthly/irregular values remain separate unless an approved conversion exists. | Required source-pack domain; standard import/adoption exists. Template `ancestry-mmm-context-and-external-factors-template.xlsx`. | Missing the source-pack domain blocks official preparation. No selected context control does not itself block the model. |

The minimum package is therefore the three standard source domains, at least
one approved outcome, and the activity/model-input dictionaries needed to
identify units and taxonomies. It does not require raw subscriber events,
SEO, Candidate A, FX, valuations, experiments, COGS, or profit optimisation.

### B. Inputs that can be added later to unlock extra features

| Input | Exact fields / grain / validation | Current path/template | Feature unavailable and core-fit impact |
|---|---|---|---|
| FH New, DNA cross-sell, Winback segmentation | Separate outcome columns and dictionary rows with explicit `segment_dimension` and `segment`; market-week counts. DNA may be New Customer vs Existing Family History Customer where supported; no self/gifted/unactivated split without approval. | Outcomes workbook and catalogue review. | Missing segment is not fitted/reported; supplied core outcomes can still fit. |
| FH LTR and DNA revenue valuation | `valuation_kind, market, week, segment, denominator_outcome_id, quality_status, segment_dimension, aggregate_value, currency, source, source_version, schema_version, horizon_months`. FH LTR requires `horizon_months=48`; DNA revenue leaves it blank. Aggregate monetary totals, not per-customer values; non-negative, ISO-3 currency, governed source/version. | Optional Data Sources uploader; blank `ancestry-mmm-outcome-valuation-template.xlsx`; exact records persist in bundle schema 24. | Monetary value/ROI curves unavailable; count fit unaffected. No historical realised value is copied as a future assumption. |
| Paid Search Brand/Non-Brand taxonomy | Activity dictionary exact identity fields plus approved Brand/Non-Brand intent/campaign classification, model input column/measure/unit and planning eligibility; market-week-activity. | Existing Activity workbook and Activity Mapping page. | Search intent rollups unavailable; other channels can fit. |
| Google Trends Candidate A anchor | CSV `week, raw_index`, plus approved query-set ID, exact branded terms, geography, category, search property, extraction date, time range and measurement sigma. Relative 0-100 index, not searches/clicks; one unique weekly extraction/query set. | Model Training boundary; persisted metadata and observations. No live values are present. | Candidate A anchor/fit remains fail-closed; ordinary MMM unaffected. |
| Candidate A Search observations and cap | CSV `period_start, market, paid_search_delivery, paid_search_cap, organic_search_capture, direct_navigation_capture`; explicit Search object IDs, cap unit, cap-to-delivery scale, provenance and approved upstream demand channel mapping. Delivery `<= cap * scale`; no missing/negative cells, no cap-from-spend derivation, no zero-fill. | Model Training importer and blank `ancestry-mmm-candidate-a-observations-template.xlsx`; exact payload and row keys persist. Fold paths slice this pinned payload and anchor without refetching. | Candidate A Search mediation, capacity, official curves, attribution and Search planning unavailable; ordinary core fit unaffected unless Candidate A is selected. |
| Search capacity/cap evidence | Governed source/provenance and explicit unit/mapping; historical binding and non-binding support; future caps are decisions/constraints, never realised delivery. | Candidate A validation path; no values invented. | Candidate A capacity identification/planning unavailable; core fit unaffected unless Candidate A is selected. |
| GSC SEO positional visibility | Raw `market, week, dimension_label, position, impressions`, optional `clicks`; positions/impressions valid and non-negative. Impression-weighted visibility is computed. UK begins around week commencing 2024-11-11; earlier cells remain inactive while full MMM history is retained. | Model Training upload and persisted `SeoModelFitInputs`; no pre-November-2024 values requested. | SEO contribution unavailable; core history and fit unaffected. Current effect is reduced-form visibility-to-outcome, not organic-click mediation; clicks are diagnostic-only. |
| Promotions and named events | Governed promotion/control columns and dates. Context `events` uses `event_id, event_name, start_date, end_date`; family and response-definition metadata are explicit. | Context workbook events sheet and registration/adoption pages; Decision 12 fitting/replay is complete. | Promotion moderation or event response unavailable; core fit can run without optional event evidence. |
| Experiments/calibration | Experiment ID/version, activity/channel, market scope, start/end, design, outcome/effect, uncertainty, applicability and compatibility metadata. Likelihood target is explicit `direct:<channel>:<outcome_id>`. | Experiment import/adoption/compatibility path. Template `ancestry-mmm-experiment-evidence-template.xlsx`. | Calibration evidence unavailable; base fit unaffected unless a selected calibration use is incomplete/incompatible. |
| Finance constant-dollar FX | Finance-approved annual rate set and records with source/target currency, rate date/value, frequency/financial year, method, provider, version, approval and pair coverage. | Existing FX upload/validation/versioning and persistence; no Finance values present. | Constant-dollar monetary outputs blocked; count fit unaffected. |
| Future valuation/value mappings | Per-scenario `ScenarioValueAssumptions`: assumptions ID/source/currency, FH outcome-value mapping, DNA mode and DNA values. | Scenario Planner editor; exact payload is now saved with each scenario and restored. | Expected monetary scenario evaluation unavailable until values exist. Demand, seasonality, baseline and controls come from governed system/model roles, not manual future entry. |
| Optimisation constraints/capacities | Channel/market/period bounds, locked cells, fixed totals, movement limits, floors and explicit Search caps; units match activity/cap contracts. | Scenario Planner/Optimiser constraint path. | Constrained planning/optimisation limited or unavailable; core fit unaffected. |
| COGS/margin/profit | Approved profit definition plus COGS/margin/contribution inputs with currency, source/version and matching market/outcome/time coverage. | No ungoverned upload or fallback; `maximise_profit` remains gated. | Profit optimisation unavailable; other approved CPA/ROI/value paths remain separate. |

### C. Deliberately deferred

PathMC adoption, structural SEO `visibility -> organic traffic/clicks ->
outcome` decomposition, Chronos-2/external forecasting, profit optimisation
without an approved profit definition, and a generalised G3 capacity
abstraction remain deferred. The current SEO release is explicitly a
windowed reduced-form visibility-to-final-outcome effect.

### Import order and onboarding checks

1. Import Outcomes; review definitions, segmentation, maturity and approval.
2. Import Activity and Media; resolve taxonomy, model-input units, currency/
   spend mappings and coverage.
3. Import Context as tidy-long; review frequency and keep events/dictionaries
   separate.
4. Run official preparation and coverage validation. Generic inner joins now
   require an explicit exploratory confirmation and are never the official
   preparation route.
5. Add GSC, Trends, Candidate A cap/observations, valuations, FX and experiment
   evidence one boundary at a time, retaining source/version provenance.
6. Review the prepared frame, model specification and pre-fit checks. Only
   after explicit owner approval of this package may the next agent start a
   production fit. No production data or production fit is present here.
