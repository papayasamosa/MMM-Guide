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

---

**Date:** 2026-07-21
**Decision:** Build `beta[market, segment, channel]` as the simplest identifiable additive form -
`log_beta = mu_channel[channel] + market_dev[market, channel] + segment_dev[segment, channel]` -
with no free market x segment x channel interaction term.
**Reason:** The redesign brief itself recommends starting with the simplest identifiable structure
and only adding an interaction term once diagnostics show the data supports it; a full interaction
term roughly triples the number of free parameters per channel with no diagnostic evidence yet that
it's needed, and risks an unidentifiable fit on realistically sized data.
**Alternatives considered:** A free `beta[market, segment, channel]` with no additive structure
(rejected - unidentifiable with typical FH data volumes, and defeats the point of partial pooling).
**Impact:** `core.market_specific_model.build_fh_market_specific_model` ("Model C"). Documented as a
next step to revisit once diagnostics on real data motivate it, not a permanent constraint.
**Owner:** Modelling.
**Status:** Accepted; implemented in Phase 2.

---

**Date:** 2026-07-21
**Decision:** Keep Model C's prediction, curve-generation and diagnostics code in fully separate
modules (`core.market_specific_predict`, `core.market_specific_diagnostics`) rather than adding
market-awareness branches into `core.predict` / `core.diagnostics`.
**Reason:** Model A's prediction and diagnostics code is already shipped and in production use;
touching it to add a market dimension risks regressing the working shared-curve path for a feature
(market-specific curves) that not every user needs. A parallel module with an identical function
contract (same `frame`/`meta` inputs, analogous output shapes) is easy to keep in sync by
inspection and impossible to accidentally break Model A with.
**Alternatives considered:** Adding an `if market_specific:` branch throughout `core.predict`/
`core.diagnostics` - rejected; increases the risk surface on Model A's tested code path for no
benefit, since the market-specific and shared-curve replay math genuinely differ (indexed vs.
non-indexed `hill_K`/`beta`).
**Impact:** `core.market_specific_predict.FHMarketSpecificPosteriorParams`,
`extract_market_specific_posterior_params`, `predict_mu_market_specific`,
`steady_state_segment_response_market_specific`, `generate_market_channel_curve`;
`core.market_specific_diagnostics.compute_scorecard_market_specific` (reuses
`core.diagnostics.posterior_predictive_coverage` and `core.models.compute_model_diagnostics`
unchanged, since those only read `mu`/`alpha`/generic posterior variables whose shape doesn't depend
on model type).
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 2.

---

**Date:** 2026-07-21
**Decision:** "Model B" (independent per-market fits, the model comparison baseline from
`docs/model_validation.md`) needs no new model-building code - it's `core.hierarchical_model.build_fh_hierarchical_model`
(Model A's own builder) fit against a single-market slice of the frame.
**Reason:** Partial pooling across a single market is meaningless (nothing to pool with), so
"independent per-market model" and "the shared-curve model fit on one market's data" are the same
thing mathematically. Writing a separate builder for Model B would be pure duplication.
**Alternatives considered:** A dedicated `build_fh_independent_market_model` - rejected as
unnecessary duplication of Model A's builder with zero structural difference.
**Impact:** `core.model_comparison.slice_frame_to_market` produces the single-market frame; the
existing Structure page's market selection already lets a user do this without any new page.
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 2.

---

**Date:** 2026-07-21
**Decision:** Extend `core.fingerprint.fingerprint_model_spec` to include `model_type` ("shared" or
"market_specific") in its hash payload, defaulting to `"shared"` for backward compatibility.
**Reason:** An approval is meant to be bound to the exact model that was reviewed. Switching model
structure (Model A <-> Model C) changes what was actually fit even if the spec, priors and DNA lag
are byte-identical, so it must invalidate any existing approval the same way a data or spec change
does - otherwise a Model A approval could be silently treated as covering a Model C fit.
**Alternatives considered:** Leaving `model_type` out of the fingerprint and relying on
`posterior_fingerprint` alone to catch the difference (rejected - the posterior fingerprint is
computed from the *fitted* params, which only exist after training; the model-spec fingerprint
needs to differ before that point too, e.g. to correctly gate re-approval prompts).
**Impact:** `core.fingerprint.fingerprint_model_spec`; every page that computes a model's identity
(`pages/06_Diagnostics.py`, `pages/07_Results_Curve_Bank.py`, `pages/08_Scenario_Planner.py`,
`core.persistence.verify_imported_approval`) now passes `model_type` through. All fingerprints
computed before this change will not match after upgrading - this is intentional, not a bug: an
approval predating this fingerprint change did not have model-type binding, so it should not survive
the upgrade as if it did.
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 2.

---

**Date:** 2026-07-21
**Decision:** Curve bank storage, Shapley attribution, and Scenario Planner stay Model-A-only for
Phase 2; Model C gets a read-only curve viewer instead, with a clear "not yet available, planned for
a later phase" message where the Model-A-only features would otherwise appear.
**Reason:** `core.curve_bank.make_entry` and `core.optimization.evaluate_scenario`/
`optimize_scenario` are built around `FHPosteriorParams`'s Model-A-only shape
(`hill_K[channel]`, `beta[segment][channel]`); passing them `FHMarketSpecificPosteriorParams`
would either raise a `KeyError` or, worse, silently read the wrong values. Building the
market-aware version of curve bank storage and the optimiser correctly is a substantial piece of
work in its own right (CPA tables, media-unit curves and inflation are explicitly Phase 3 scope,
`docs/curve_bank.md`, `docs/scenario_planner.md`) and doing it hastily here risks a subtly wrong
scenario-planning result, which is a much worse failure mode than a page saying "not available yet."
**Alternatives considered:** Best-effort adaptation of curve bank/optimiser to accept a single
market's slice of Model C's params (rejected - would silently produce a curve bank entry / scenario
that looks like a normal Model-A entry but is actually one market's posterior mean masquerading as
"the" curve, with no CPA/inflation handling; misleading rather than merely incomplete).
**Impact:** `pages/07_Results_Curve_Bank.py` (Shapley/curve-bank section gated to
`model_type == "shared"`; new "Market-specific channel curve viewer" section for
`model_type == "market_specific"` using `core.market_specific_predict.generate_market_channel_curve`),
`pages/08_Scenario_Planner.py` (blocked with `st.stop()` and a link back to Results & Curve Bank for
`model_type == "market_specific"`).
**Owner:** Product/Modelling.
**Status:** Accepted; Phase 3 will extend curve bank/optimiser to Model C alongside CPA/media-unit/
inflation calculations.

---

**Date:** 2026-07-21
**Decision:** Model C's hierarchical structure is validated by an offline (non-CI) recovery check
against `core.simulation`'s synthetic ground truth before trusting it on real data, rather than by a
committed automated test.
**Reason:** A real MCMC fit is slow (tens of seconds to minutes even at reduced draws) and
inherently noisy at the low draw counts that keep it fast - not the kind of check that should gate
every CI run, and a flaky pass/fail assertion on posterior recovery would be worse than no check at
all. This follows the same convention the codebase already uses for Model A (no test suite entry
builds or fits `build_fh_hierarchical_model` either).
**Result:** A 3-market, 2-channel, 52-week synthetic panel (`core.simulation.simulate_market_specific_panel`)
fit with a deliberately small budget (150 tune, 150 draws, 2 chains, ~90s) recovered the *correct
market ranking* for both `hill_K` and `beta` (UK > Australia > NewMarket, matching the simulation's
`k_multiplier`/`beta_multiplier` scaling) with positive rank/scale correlation against ground truth
(K: 0.72, beta: 0.67). Absolute magnitudes were compressed toward the pooled mean relative to ground
truth, as expected from partial pooling under a small draw budget and are not a concern in
themselves; `max R-hat` was 1.05 with 1 divergence, consistent with a check explicitly not run to
full convergence. This is evidence the hierarchy is structurally sound (market differentiation is
recoverable in direction, not collapsed to a single shared value), not evidence of tight
quantitative recovery - a real fit with production draw counts would be expected to recover
magnitudes much more closely.
**Impact:** No committed test file; this entry is the record. A committed, CI-gated recovery test is
a candidate for a future phase if a fast/stable-enough MCMC configuration is found.
**Owner:** Modelling.
**Status:** Accepted.

---

**Date:** 2026-07-21
**Decision:** Add a `Shared` curve status, beyond the three-tier
`Locally estimated`/`Partially pooled`/`Transferred estimate` enum the original redesign brief
specifies for curve bank entries.
**Reason:** Those three tiers are inherently about *market-specific* evidence strength - how much a
market's own data versus the pooled distribution drove its estimate. A Model A (shared-curve) entry
has no market dimension at all; forcing it into one of the three tiers would assert something false
about evidence strength that was never assessed for that curve. `Shared` says plainly "this curve is
the same for every market by construction," which is a different, true statement.
**Alternatives considered:** Omitting `market`-tier labelling entirely for Model A entries (leaving
`curve_status` blank) - rejected, since an unlabelled field invites a reader to guess, and a blank
status is easy to confuse with a bug rather than an intentional "not applicable."
**Impact:** `core.curve_bank.CURVE_STATUS_SHARED`; `make_entries` sets it automatically for every
`model_type="shared"` entry, never asks the caller to supply it.
**Owner:** Product/Modelling.
**Status:** Accepted; implemented in Phase 3a.

---

**Date:** 2026-07-21
**Decision:** Redesign `core.curve_bank.CurveBankEntry` to one record per (market, channel,
segment-or-overall) instead of one record per model run, per `docs/curve_bank.md`'s original plan -
and implement it for **both** Model A and Model C, not only Model C.
**Reason:** The per-curve shape is what makes filtering/comparing individual curves in the UI
possible (`docs/curve_bank.md`'s planned filter-by-market/channel/segment/status table), and what
lets a market-specific fit save one record per market instead of an awkward nested blob. Extending
it to Model A too (rather than leaving Model A on the old per-run shape and only building the new
shape for Model C) avoids maintaining two different curve bank schemas side by side indefinitely,
and removes the earlier Phase 2 restriction that blocked market-specific models from the curve bank
at all - that restriction was about *shape mismatch* (`FHPosteriorParams` vs.
`FHMarketSpecificPosteriorParams`), not about anything specific to Model C, so a shape both model
types can populate resolves it for both.
**Alternatives considered:** Keep a run-level Model A entry format and add a *separate*,
market-specific-only per-curve format for Model C (rejected - two formats to maintain, two things to
teach curve bank UI code to handle, and no real benefit since Model A can just produce per-curve
entries with `market=None`). Extend the existing per-run entry to nest market data inside it as a
dict (rejected - defeats the point of "one record per curve" that makes filtering/comparison
straightforward).
**Impact:** `core.curve_bank.make_entries` (renamed from `make_entry`, now returns a list),
`save_entries` (renamed from `save_entry`), `entries_to_dataframe` (now a direct 1:1 mapping, no more
per-entry segment x channel expansion loop). `pages/07_Results_Curve_Bank.py`'s curve bank section
moved out of the Model A / Model C branch entirely, since saving now works identically for both.
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 3a.

---

**Date:** 2026-07-21
**Decision:** Old, pre-Phase-3a curve bank JSON files (one file per model run, nested per-segment/
per-channel dicts) stay loadable, expanded into the new per-curve shape at read time and marked
`legacy_format=True`, rather than being dropped or requiring a one-off migration script.
**Reason:** A curve bank directory is real, potentially valued project history (calibration records
reference entry IDs from it) that could exist in a user's already-exported project bundle. Silently
failing to load it, or requiring a manual migration step before the redesigned code can read it, both
risk looking like data loss even though the underlying JSON is untouched.
**Alternatives considered:** A separate one-off migration script the user runs manually (rejected -
extra manual step, and an easy one to forget before opening a curve bank that then appears empty). A
strict schema version bump that refuses to load pre-3a files (rejected as unnecessarily destructive
for what's a straightforward, losslessly invertible expansion).
**Impact:** `core.curve_bank.CurveBankEntry.from_dict` now returns a list (one item for a
current-format file, several for an expanded legacy one) and detects format by the presence of the
`segment_or_overall` key; `_expand_legacy_entry` does the expansion, computing each channel's
"Overall" beta as the sum of its per-segment betas (valid by linearity - see `docs/curve_bank.md`).
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 3a.

---

**Date:** 2026-07-21
**Decision:** Classify a market's evidence tier (`docs/market_hierarchy.md` section 4) from two
combined signals - period count and the fitted posterior's own relative uncertainty (std/mean) on
`hill_K` and `beta` for that market/channel - rather than from period count alone.
**Reason:** Period count alone (what `core.market_config.market_data_quality_status` already uses,
pre-model) can't reflect what partial pooling actually did: a market can have plenty of periods but
still get pulled hard toward the pooled mean if its own signal was weak or noisy (e.g. flat spend, a
short bookings window), and conversely a market with fewer-but-highly-informative periods could earn
tighter posterior estimates. The *fitted* posterior's uncertainty is the direct evidence of which
happened; period count alone would mislabel both cases.
**Alternatives considered:** Reusing `market_K_sigma`/`market_beta_sigma` (the *global* pooling-
strength hyperparameters) directly as the signal - rejected; those describe how much markets are
*allowed* to differ on average across the whole model, not how confidently *this* market's own
estimate was pinned down, which is what a per-market evidence tier needs.
**Impact:** `core.evidence_tiers.classify_market_evidence` / `classify_all_markets`; thresholds
(`min_observations_for_local=52`, `min_observations_for_pooled=12`,
`max_relative_uncertainty_for_local=0.5`) are keyword arguments with defaults, adjustable by a caller
without code changes if they prove too strict or too loose against real data.
**Owner:** Modelling.
**Status:** Accepted; implemented in Phase 3a. Revisit thresholds once compared against
real-data model comparison outcomes (`docs/model_validation.md`).

---

**Date:** 2026-07-21
**Decision:** Drop `promo_coef` from the redesigned per-curve `CurveBankEntry` (it existed on the old
per-run entry).
**Reason:** `promo_coef` is a per-segment coefficient, not tied to any specific channel's curve - it
doesn't fit "one record per (market, channel, segment)" cleanly, since every channel's entry for a
given segment would otherwise carry an identical, channel-irrelevant copy of the same number. The
redesign brief's own per-record schema (`model_run_id, market, channel, segment_or_overall,
curve_type, input_type, currency, unit_type`) doesn't include it either.
**Alternatives considered:** Keeping a duplicated `promo_coef` on every channel's entry for a segment
(rejected - redundant, and invites a reader to mistake it for something channel-specific).
**Impact:** `core.curve_bank.CurveBankEntry` has no `promo_coef` field. Promo sensitivity remains
visible on Diagnostics/Model Training via the fitted `params.promo_coef` directly; it was never
saved anywhere else once a model run is superseded, so this loses no information that was uniquely
preserved by the curve bank.
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 3a.

---

**Date:** 2026-07-21
**Decision:** Derive the response-unit curve (`core.media_units.response_unit_curve`) by dividing a
spend curve's spend axis by a single average historical cost-per-unit, rather than modelling
cost-per-unit as a function of spend level.
**Reason:** No data exists (or is planned to exist) that would let a model learn "cost per unit at
spend level X" as its own curve - the media-unit config only captures a historical time series of
`spend`/`media_units` pairs at whatever spend levels actually occurred, not a spend-elasticity-of-
cost relationship. A constant-average-cost-per-unit rescaling is the honest, directly-supportable
reading of that data; anything more elaborate (e.g. a fitted cost-per-unit-vs-spend curve) would be
extrapolating a relationship the data doesn't actually speak to.
**Alternatives considered:** Fitting a secondary regression of `cost_per_unit` on `spend` per
(market, channel) to let the response-unit curve reflect non-constant unit economics at different
spend levels (rejected for this phase - meaningfully more modelling work and validation burden for a
benefit that's speculative without first checking whether real Ancestry cost-per-unit data shows any
such non-constant pattern worth capturing; a documented next step, not ruled out).
**Impact:** `docs/media_units_and_inflation.md`'s "Spend curve vs. response-unit curve" section
records this explicitly as a simplification, not silently. `core.media_units.response_unit_curve`'s
docstring says the same.
**Owner:** Modelling.
**Status:** Accepted; implemented in Phase 3b.

---

**Date:** 2026-07-21
**Decision:** `core.curve_bank.make_media_unit_entries` only mirrors curve bank entries into
`input_type="media_unit"` for a market-specific (Model C) save, not a shared (Model A) save.
**Reason:** A media-unit curve needs a cost-per-unit relationship, and cost-per-unit is inherently
market-specific (media costs differ by market) even though a shared curve's `beta`/`K`/`S` are the
same across every market it covers. There is no single, non-arbitrary market to attribute "the"
cost-per-unit context to for a curve that spans several markets by construction - picking one would
silently misrepresent the other markets' costs as if they matched it.
**Alternatives considered:** Averaging cost-per-unit across every market the shared curve covers
(rejected - blends genuinely different markets' costs into a number that doesn't represent any of
them accurately, and would need every market to have a media-unit mapping simultaneously to compute,
which is an unnecessarily strict requirement). Saving one media-unit entry per market anyway, each
tagged with that market's own cost data despite the underlying curve being shared (rejected - this
is exactly what Model C's market-specific entries already do correctly; doing the same thing for
Model A would misleadingly suggest the *curve itself* also varies by market when it explicitly
doesn't).
**Impact:** `pages/07_Results_Curve_Bank.py`'s Channel curve viewer (Model A) still shows media-unit
context (response-unit curve, historical cost trend, equivalent delivery/response) for a
user-chosen reference market - it's just not persisted to the curve bank. Extending this once Model
A curves themselves become market-aware is out of scope until/unless that redesign happens.
**Owner:** Product/Modelling.
**Status:** Accepted; implemented in Phase 3b.

---

**Date:** 2026-07-21
**Decision:** Add `core.predict.generate_channel_curve` (Model A) as a direct structural mirror of
`core.market_specific_predict.generate_market_channel_curve` (Model C) - same column shape (`spend`,
`saturation`, `{segment}_response...`, `overall_response`), just without a `market` dimension.
**Reason:** Model A never had a spend -> response curve generator at all (only Shapley/contribution
tables) - `core.media_units`'s CPA and media-unit functions need *some* curve DataFrame to operate
on for either model type, and giving them one consistent shape to expect means they never need to
know or care which model type produced it.
**Alternatives considered:** Writing CPA/media-unit functions that branch on model type and read
`FHPosteriorParams`/`FHMarketSpecificPosteriorParams` directly instead of a curve DataFrame
(rejected - re-implements curve generation inside `core.media_units`, duplicating logic that
already exists in two other modules, and reintroduces exactly the kind of model-type branching this
codebase has been deliberately avoiding since Phase 2, docs/decision_log.md).
**Impact:** `core.predict.generate_channel_curve`; `pages/07_Results_Curve_Bank.py` gained a
"Channel curve viewer" section for Model A that didn't exist before (a real UX gap this closes, not
just plumbing for Phase 3b).
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 3b.
