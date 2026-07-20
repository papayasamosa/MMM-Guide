# Business Questions

What this tool needs to be able to answer, and where each one currently stands.

| Question | Status |
|---|---|
| What is the incremental contribution of each channel, in total? | **Answered today** - Results & Curve Bank page, shared curve across markets. |
| What is the contribution by New, DNA cross-sell, and Winback? | **Answered today** - segment x channel detail table, DNA halo strength by segment. |
| What is the incremental contribution of each channel, **by market**? | **Not yet** - today's curve is shared across markets; this is the core Phase 2 deliverable. |
| What is the market-specific saturation curve for a channel? | **Not yet** - Phase 2. `core.market_config.MarketSpecConfig` (Phase 1) stores the market list and descriptors this will use; the hierarchical `K[market, channel]` model itself doesn't exist yet. |
| What spend level minimises CPA? | **Partial** - the optimiser already targets an objective (value or volume) subject to constraints; CPA is not yet reported as a first-class output. Phase 3. |
| What is the marginal CPA at additional spend? | **Not yet** - Phase 3 (`docs/media_units_and_inflation.md`, `docs/scenario_planner.md`). |
| How many impressions, GRPs, or TVRs are required for a target response? | **Not yet** - requires the response-unit curve (Phase 3); Phase 1 adds the data capture (Channel & Media Units page) this depends on. |
| How much spend is required to maintain delivery after inflation? | **Not yet** - Phase 3 equivalent-delivery calculation. |
| How much spend is required to maintain response after inflation? | **Not yet** - Phase 3 equivalent-response calculation. |
| Which smaller-market curves are locally estimated, pooled, or transferred? | **Not yet** - requires a fitted market-specific model (Phase 2) to classify; Phase 1 adds a coarse, pre-model "data quality" label (`core.market_config.market_data_quality_status`) as a placeholder, explicitly not the same thing (see `docs/market_hierarchy.md` section 4). |
| How much information is being borrowed across markets? | **Not yet** - Phase 2 (pooling diagnostics). |
| Is a model's approval still valid, or has something material changed since it was reviewed? | **Answered today** - fingerprint-bound `ModelApproval` (see `docs/decision_log.md` prior work) invalidates automatically on data/spec/posterior change. |
| Has the curve bank entry I'm looking at been through review, or is it a legacy/unverified entry? | **Answered today** - `legacy_approval` flag on curve bank entries. |
