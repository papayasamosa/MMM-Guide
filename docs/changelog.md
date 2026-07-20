# Changelog

Entries by pull request, most recent first. Predates this file: see git history for anything
earlier than the entries below.

## Unreleased - Market-Specific MMM Redesign, Phase 1 (this PR)

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
