# Changelog

Entries by pull request, most recent first. Predates this file: see git history for anything
earlier than the entries below.

## Unreleased - PR G1: Pathway-Masked Estimation, Net Bill-Through, Brand Search, Identification Diagnostics

- `core.pathways.resolve_pathway_masks`/`ResolvedPathwayMasks` made the PR F pathway catalogue
  operational: both `build_fh_hierarchical_model` (Model A) and `build_fh_market_specific_model`
  (Model C) now read the same resolved masks to decide which `(outcome, channel)` coefficients get
  estimated and how (`primary_direct`/`active_cross_product`/`exploratory_cross_product`/`excluded`),
  replacing the old DNA-only direct/halo split with a general mechanism. Exactly backward-compatible
  with the pre-PR-G1 legacy defaults when no pathway catalogue is configured. See
  `docs/segment_level_estimation.md`.
- `FHPosteriorParams.halo_strength` (per-outcome) generalised to `pathway_strength` (per
  `[outcome_id][channel]`) across `core.predict`, `core.market_specific_predict`, `core.attribution`,
  `core.market_specific_attribution` - every NumPy replay/attribution function now mirrors the PyMC
  construction exactly via the shared resolved masks.
- Added `core.net_billthrough`: deterministic `fh_net_billthrough_count` weekly series, attributed to
  signup date with analyst-configured per-`(market, offer_id)` maturity windows - immature cohorts
  excluded, never zero-filled. `fh_gsa_finance_date` remains structurally untouched. See
  `docs/net_billthrough.md`.
- Added `core.brand_search`: four explicit Brand Search treatment modes (`direct_channel`/`excluded`/
  `demand_capture_mediator`/`experiment_calibrated_incremental`), a deterministic mediator-reallocation
  helper reconciling exactly to the fitted contribution. See `docs/brand_search.md`.
- Added `core.identification_diagnostics`: channel-spend correlation matrix, media design-matrix
  condition number, posterior coefficient-of-variation stability, leave-one-channel-out sensitivity
  (caller-supplied refit), and a structured `identification_report`.
- UI: Model Configuration gained `active_cross_product_sigma`/`exploratory_cross_product_sigma` prior
  sliders (replacing the dead `dna_halo_sigma` control) and a Brand Search treatment-mode editor;
  Structure gained a net bill-through offer-rule editor and corrected pathway-catalogue drift messaging
  (it now drives fitting); Diagnostics gained a multicollinearity & weak-identification panel.
- 87 new tests across `test_pathways.py`, `test_hierarchical_model.py`, `test_market_specific_model.py`,
  `test_predict.py`, `test_market_specific_predict.py`, `test_attribution.py`,
  `test_market_specific_attribution.py`, `test_predict_pathway_masks.py`, `test_net_billthrough.py`,
  `test_brand_search.py`, `test_identification_diagnostics.py`, `test_simulation_recovery.py`, and three
  new AppTest files - 873 -> 960 total.
- No change to fitted coefficients for any project with no pathway catalogue configured (the
  legacy-default equivalence guarantee); a project with a non-default pathway role configured gets
  genuinely different, statistically improved segment-level estimation - see `docs/decision_log.md` for
  the full impact/invalidation statement.

## Unreleased - Market-Specific MMM Redesign, Phase 4 (this PR)

- Added `core.report`: `build_report_sections`/`render_markdown`/`render_html` - a reproducible
  project report (objective, data, model, diagnostics, curve bank, scenarios, known limitations, a
  decision-log pointer) built from the project's actual current state, not a static template. Every
  input is independently missing-safe, so a report can be generated at any point in the workflow.
  Both renderers consume the same structured section data, so Markdown and HTML can never drift out
  of sync with each other. No dependency on `ancestry_mmm.utils` or Streamlit, matching every other
  `core` module.
- Project Export & Handover: added a "Project report" section (Markdown + HTML download); replaced
  the page's stale "Roadmap" block (still describing the pre-redesign phase numbering) with an
  accurate "What's out of scope" list reflecting the completed market-specific redesign.
- 19 new tests (`test_report.py`), plus AppTest-based end-to-end verification of report generation in
  both an empty (no model trained yet) and fully-populated project state.
- No changes to Model A/C model-building, prediction, diagnostics, model comparison, curve bank,
  optimisation, or fingerprint behaviour.

This completes the market-specific MMM redesign's core arc (Phase 1 docs/schema/simulation -> Phase 2
hierarchical model -> Phase 3a/b/c curve bank/CPA/media-units/inflation/scenario-planner -> Phase 4
report generation) from the original redesign brief, short of the items explicitly recorded as out
of scope throughout (`docs/limitations.md`, `docs/project_objectives.md`).

## Unreleased - Market-Specific MMM Redesign, Phase 3c

- Extended `core.optimization` (`evaluate_scenario`, `optimize_scenario`, the optimiser objective) to
  Model C via a `model_type` parameter that dispatches to the correct steady-state response function -
  the planning math itself (constraints, bounds, budget conservation) needed no changes, since both
  model types' response functions share the same call contract.
- `evaluate_scenario`'s output gained `avg_cpa` (blended average CPA per month: total spend / total
  predicted GSAs across every segment).
- Removed the Phase 2 restriction blocking Scenario Planner for market-specific models entirely.
- Scenario Planner: added an evidence-tier panel (per planned channel, for the selected market, on a
  market-specific fit), a spend-vs-media-unit planning mode for the spend plan editor (built on
  `core.media_units`'s conversions, plan always stored in spend terms internally), and a blended
  "Avg CPA (current vs. optimised/theoretical-optimum)" metric on every result panel.
- 6 new tests (`test_optimization.py::TestModelTypeDispatch`, `TestAverageCpa`), plus AppTest-based
  end-to-end verification of the manual/constrained/unconstrained flows, the media-unit planning
  mode toggle, and the evidence-tier panel for both model types.
- No changes to Model A/C model-building, prediction, diagnostics, model comparison, curve bank, or
  fingerprint behaviour. Shapley attribution remains Model-A-only.

## Unreleased - Market-Specific MMM Redesign, Phase 3b

- Added `core.predict.generate_channel_curve` - Model A's spend -> response curve generator (a real
  UX gap it closes - Model A never had one before), mirroring
  `core.market_specific_predict.generate_market_channel_curve`'s column shape so downstream code
  works on either model type's curve identically.
- Added `core.media_units`: `compute_cpa` (average + marginal CPA on any curve DataFrame),
  `cpa_stability_flags` (point-estimate proxy for unstable marginal CPA), `extract_cost_per_unit_series`
  and `historical_cost_trend` (year-on-year inflation, indexed cost trend, from raw spend/media-unit
  data), `response_unit_curve` (spend curve -> media-unit curve via average historical cost-per-unit
  - a documented simplification), `equivalent_delivery` and `equivalent_response`.
- Extended `core.curve_bank`: `CurveBankEntry` gained a `cost_per_unit` field;
  `make_media_unit_entries` mirrors a market-specific run's spend entries into `input_type="media_unit"`
  entries wherever a media-unit mapping and valid cost history exist. Not built for shared (Model A)
  curves - cost-per-unit is inherently market-specific with no single market to attribute it to for
  a curve that spans several markets by construction (see decision log).
- Results & Curve Bank: both model types now have a curve viewer with CPA shown alongside the spend
  curve, plus a "Media units & inflation" section (historical cost trend, response-unit curve,
  equivalent delivery/response calculators) wherever a media-unit mapping exists. Curve bank saving
  now also saves media-unit entries for a market-specific fit.
- 41 new tests (`test_media_units.py`, `test_predict.py`, plus curve bank additions), plus
  AppTest-based end-to-end verification of the new curve/CPA/media-unit UI and save flow for both
  model types.
- No changes to Model A/C model-building, prediction (beyond the additive curve generator),
  diagnostics, model comparison, fingerprint, or Scenario Planner behaviour.

## Unreleased - Market-Specific MMM Redesign, Phase 3a

- Added `core.evidence_tiers`: `classify_market_evidence` / `classify_all_markets` - classifies a
  fitted Model C market/channel into `Locally estimated`/`Partially pooled`/`Transferred estimate`
  (`docs/market_hierarchy.md` section 4) from period count plus the posterior's own relative
  uncertainty, not period count alone.
- Redesigned `core.curve_bank.CurveBankEntry` to one record per (market, channel,
  segment-or-overall) instead of one per model run, for **both** Model A and Model C -
  `make_entries` (renamed from `make_entry`) now returns the full set for a run in one call, with
  `curve_status` set to `Shared` (Model A) or the evidence tier (Model C). Old, pre-redesign curve
  bank files remain loadable, expanded into the new shape and marked `legacy_format=True` - nothing
  on disk is dropped.
- Results & Curve Bank: curve bank saving now works for market-specific models too (previously
  blocked entirely) - Shapley attribution remains Model-A-only. Added market/channel/segment/curve-
  status filters to the curve bank history table; calibration logging now selects a curve bank entry
  directly instead of separately re-selecting its channel/segment.
- 36 tests across a new `test_evidence_tiers.py` and a rewritten `test_curve_bank.py` (evidence tier
  classification, per-curve entry creation for both model types, legacy-format expansion), plus
  AppTest-based end-to-end verification of the curve bank save/filter/calibration flow for both
  model types.
- No changes to Model A/C model-building, prediction, diagnostics, model comparison, fingerprint, or
  Scenario Planner behaviour.

## Unreleased - Market-Specific MMM Redesign, Phase 2

- Added `core.market_specific_model.build_fh_market_specific_model` ("Model C"): market-specific,
  partially pooled `hill_K[market, channel]` and `beta[market, segment, channel]`; `decay[channel]`
  and `hill_S[channel]` stay shared across markets in this initial version. Structurally identical
  to Model A otherwise (DNA halo, promo, market baseline pooling, trend, seasonality, controls).
  Requires at least 2 markets.
- Added `core.market_specific_predict`: `FHMarketSpecificPosteriorParams`,
  `extract_market_specific_posterior_params`, NumPy prediction/curve-replay
  (`predict_mu_market_specific`, `steady_state_segment_response_market_specific`,
  `generate_market_channel_curve`) - a fully separate module from `core.predict`, so Model A's
  existing prediction path is untouched.
- Added `core.market_specific_diagnostics`: `compute_scorecard_market_specific` and its supporting
  pieces (`in_sample_fit_market_specific`, `curve_plausibility_checks_market_specific`), reusing
  `core.diagnostics.posterior_predictive_coverage` and `core.models.compute_model_diagnostics`
  unchanged.
- Added `core.model_comparison`: `slice_frame_to_market` (Model B = Model A fit on one market's
  slice - no new model-building code), `ModelComparisonCandidate`, `candidates_to_dataframe`.
- Extended `core.fingerprint.fingerprint_model_spec` with a `model_type` parameter (default
  `"shared"`, backward compatible) so switching model structure invalidates an existing approval,
  same as a data/spec/posterior change would.
- Extended `core.persistence` export/import with a `model_type` config file; `reconstruct_model_state`
  and `verify_imported_approval` branch on it; legacy bundles default to `"shared"`.
- Added a "Model structure" choice (shared vs. market-specific) to Model Configuration, disabled
  below 2 markets; Model Training branches its build/fit/extract calls on it and can save a fit's
  scorecard as a comparison candidate; added **Compare Models** (new step 8, workflow now 12 steps)
  to review candidates side by side.
- Diagnostics now computes the correct scorecard for either model type and binds approval to
  `model_type`.
- Results & Curve Bank: Shapley attribution and curve-bank saving stay Model-A-only (a clear
  "not yet available, planned for a later phase" message for market-specific models); added a
  market-specific channel curve viewer using `generate_market_channel_curve`.
- Scenario Planner blocks with a clear message for market-specific models (Model-A-only for now);
  points back to Results & Curve Bank.
- No changes to Model A's model-building, prediction, diagnostics, curve bank, or optimisation code.

## Unreleased - Market-Specific MMM Redesign, Phase 1

- Added `docs/` project documentation (this directory) - objectives, business questions,
  methodology, market hierarchy, segment methodology, media units & inflation, data requirements,
  model validation, curve bank and scenario planner design records, user guide, decision log,
  limitations, glossary.
- Added `core.market_config`: `MarketDescriptors`, `MarketCurrency`, `MarketProfile`,
  `ChannelMediaUnitConfig`, `MarketSpecConfig`, and `market_data_quality_status` - optional,
  additive data capture for market context and channel media-unit mappings. Not yet consumed by
  the fitting pipeline.
- Added `core.simulation`: `simulate_market_specific_panel` - synthetic multi-market panel
  generator with known ground truth (market-specific saturation/response, one weak-data market,
  media inflation over time, spend + physical media-unit columns), for Phase 2 recovery testing.
- Added two pages to the guided workflow (now 11 steps): **Channel & Media Units** (step 4) and
  **Market Descriptors** (step 5), both optional, inserted between Structure and Model
  Configuration.
- Extended project export/import (`core.persistence`) to carry `market_spec_config`; legacy
  bundles without it import cleanly with an empty config.
- No changes to modelling, transformation, schema (`ModelSpec` itself), fingerprinting, approval,
  or scenario-optimisation logic.

## Streamlit UI/UX Redesign

- Dark-green theme (`.streamlit/config.toml`, `utils/config.py`), replacing the previous
  navy/indigo palette.
- Shared guided-workflow shell across all pages: sidebar (`components/ui.py::render_sidebar`),
  step indicator, page purpose + numbered instructions, next-step panel, empty states.
- Reusable display helpers (`utils/display.py`): date formatting (`d MMM yy`), number formatting
  (comma separators), readable column labels, `dataframe_column_config` for consistent table
  display.
- Fixed a pre-existing circular import between `ancestry_mmm.core` and `ancestry_mmm.data` that
  could crash the app depending on which page loaded first.

## Model Approval and CI

- Added `model_run_id`, `data_fingerprint`, `model_spec_fingerprint`, `posterior_fingerprint` to
  `ModelApproval` - SHA-256 fingerprint binding so an approval is tied to the exact fitted model,
  not just "an approval exists."
- Enforced approval validation at the core API level (Curve Bank, Scenario Planner), not just in
  the UI.
- Added `.github/workflows/tests.yml` (GitHub Actions: pytest + ruff on PRs/pushes to `main`).

## Phase 0 Hardening / Initial Build

- Initial `ancestry_mmm/` build: data upload/transform pipeline, structural schema, joint
  hierarchical FH model (New / DNA cross-sell / Winback), diagnostics scorecard, curve bank,
  constrained/unconstrained scenario planner, project export/import.
