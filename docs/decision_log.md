# Decision Log

Format: Date, Decision, Reason, Alternatives considered, Impact, Owner, Status.

---

**Date:** 2026-07-20
**Decision:** Reject one fully shared channel curve across all markets as the model's end state.
**Reason:** Countries differ in population, addressable audience, brand penetration, channel
maturity, and media cost - a single curve forces saturation and response strength to be identical
everywhere, which is empirically implausible and hides exactly the kind of cross-market difference
a planner needs to see.
**Alternatives considered:** Keep the shared curve and rely on segment-level variation alone to
capture market differences (rejected - segments and markets are different axes; segment variation
doesn't substitute for market variation).
**Impact:** Motivates the entire market-specific redesign (`docs/market_hierarchy.md`,
`docs/modelling_methodology.md`).
**Owner:** Modelling.
**Status:** Accepted. Phase 1 (this PR) lays the data/documentation groundwork; the model change
itself is Phase 2.

---

**Date:** 2026-07-20
**Decision:** Market-specific curves are required, but must be partially pooled, not independently
fitted per market.
**Reason:** Independent per-market fits throw away information - a market with little data would
get an equally unconstrained curve as a market with years of history, which is worse than sharing
information, not better.
**Alternatives considered:** (a) Fully independent per-market models (Model B in
`docs/model_validation.md`) - kept only as a documented comparison baseline, not the default. (b) A
single shared curve (see prior entry) - rejected for the same core reason.
**Impact:** `log_K[market, channel] ~ Normal(global_log_K[channel], market_K_sigma[channel])` is the
target structure (`docs/market_hierarchy.md` section 3); `core.simulation.simulate_market_specific_panel`
(Phase 1) already generates data under this exact hierarchical assumption, ready for Phase 2 recovery
testing.
**Owner:** Modelling.
**Status:** Accepted.

---

**Date:** 2026-07-20
**Decision:** Adstock decay and Hill saturation shape stay shared across markets in the first
production version of the market-specific model; only the saturation point (`K`) and response
strength (`beta`) become market-specific initially.
**Reason:** Adstock decay is difficult to estimate reliably even in a simpler model; making it
market-specific from day one, before diagnostics or simulation recovery justify it, risks an
unidentifiable or unstable fit.
**Alternatives considered:** Making `decay[market, channel]` and `S[market, channel]` market-specific
immediately - deferred, not rejected outright; documented as a valid next step once the simpler
hierarchy is validated (`docs/modelling_methodology.md`).
**Impact:** Scopes what Phase 2 actually has to build and what the simulation framework's ground
truth represents (`core.simulation.SimulationGroundTruth.channel_decay` / `channel_S` are per-channel,
not per-market-and-channel, by design).
**Owner:** Modelling.
**Status:** Accepted.

---

**Date:** 2026-07-20
**Decision:** Segment reporting (New / DNA cross-sell / Winback) is retained unchanged through the
market-specific redesign.
**Reason:** The three segments have materially different media response, promotional sensitivity,
and value (`docs/ancestry_fh_mmm.md`) - that was the reason the tool was built jointly-segmented in
the first place, and market-specificity is an orthogonal concern, not a replacement for it.
**Alternatives considered:** Collapsing to a blended KPI to simplify the market-specific redesign -
rejected; would reintroduce the exact measurement gap the tool exists to close.
**Impact:** `docs/segment_methodology.md`; `core.schema.DEFAULT_SEGMENTS` and the DNA halo pathway
are unchanged by this PR.
**Owner:** Product/Modelling.
**Status:** Accepted.

---

**Date:** 2026-07-20
**Decision:** Both spend-based and physical-media-unit-based curves are required, not spend alone.
**Reason:** Spend is not always the most meaningful exposure variable, and conflating media cost
inflation with media effectiveness (a channel "getting worse" vs. "getting more expensive") produces
wrong planning conclusions.
**Alternatives considered:** Spend-only curves with a manual note about inflation - rejected; the
brief specifically requires CPA and delivery questions answerable by physical unit
(`docs/business_questions.md`), which a spend-only model can't support.
**Impact:** `core.market_config.ChannelMediaUnitConfig` (Phase 1, data capture only);
`docs/media_units_and_inflation.md` records the full planned calculation design for Phase 3.
**Owner:** Product/Modelling.
**Status:** Accepted for the data model (Phase 1, this PR); calculations deferred to Phase 3.

---

**Date:** 2026-07-20
**Decision:** Media inflation is modelled as a separate, explicit cost-per-unit relationship, not
folded into the response curve.
**Reason:** If inflation were absorbed into the response curve, the curve would appear to "decay"
over time for reasons that have nothing to do with the audience's actual response to media -
undermining every downstream CPA and scenario calculation.
**Alternatives considered:** Time-varying `K`/`beta` to implicitly capture inflation - rejected;
conflates two genuinely different phenomena (audience response vs. media cost) that the business
needs to reason about separately (e.g. "should we spend more because it works better, or because
it's gotten more expensive").
**Impact:** `docs/media_units_and_inflation.md` sections "Historical cost relationship",
"Equivalent delivery calculation", "Equivalent response calculation" - all explicitly kept separate
from the response model itself.
**Owner:** Modelling.
**Status:** Accepted for the design; implementation is Phase 3.

---

**Date:** 2026-07-20
**Decision:** Phase this redesign into 4 PR-sized phases (docs/schema/simulation ->
hierarchical model -> CPA/media-units/inflation/planner -> report generation) rather than one
large change.
**Reason:** This is a major architectural change touching the model, the curve bank, the scenario
planner, and persistence. A single PR of this size would be unreviewable and would block the
already-working app on a much longer critical path than necessary.
**Alternatives considered:** One combined PR - rejected as unreviewable and high-risk to the
existing, tested, merged app.
**Impact:** This PR is Phase 1 only: documentation, data schema (`core.market_config`), the
simulation framework (`core.simulation`), and additive UI (Channel & Media Units, Market
Descriptors pages). No existing modelling, transformation, schema, fingerprint, approval,
persistence, or optimisation behaviour changes.
**Owner:** Engineering.
**Status:** Accepted; Phase 1 in progress as of this entry.
