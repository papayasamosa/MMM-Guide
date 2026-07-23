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

---

**Date:** 2026-07-21
**Decision:** Extend `core.optimization`'s scenario planning (`evaluate_scenario`,
`optimize_scenario`, the optimiser objective) to Model C by adding a `model_type` parameter that
dispatches to `steady_state_segment_response` or `steady_state_segment_response_market_specific`,
rather than writing separate market-specific planning functions.
**Reason:** Both response functions already share the exact same `(market, spend_by_channel, meta,
params, reference_context) -> {segment: rate}` contract - `market` already selected the right
market-specific baseline for Model A (`market_offset`), and does the same job selecting the right
market-specific `K`/`beta` for Model C. None of the surrounding planning math (constraint
translation, bounds, budget conservation, the SLSQP objective) reads `params` directly or needs to
know which model type it's driving - it only ever calls the response function and sums the result.
**Alternatives considered:** Separate `evaluate_scenario_market_specific`/`optimize_scenario_market_specific`
functions mirroring `core.market_specific_predict`'s pattern of fully separate modules (rejected -
unlike curve generation and diagnostics, which genuinely read `hill_K`/`beta`'s shape directly and
so needed parallel implementations, the planning math here has no such dependency; a parallel module
would be pure duplication of constraint/bounds/optimiser code with a one-line difference at the
call site).
**Impact:** `core.optimization.evaluate_scenario`/`optimize_scenario`/`_objective_factory` gained a
`model_type: str = "shared"` parameter (default preserves every existing caller's behaviour
unchanged); `pages/08_Scenario_Planner.py`'s market-specific block from Phase 2 was removed entirely
rather than replaced with new plumbing.
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 3c.

---

**Date:** 2026-07-21
**Decision:** Report a scenario's CPA as a *blended average* (total spend / total predicted GSAs,
current plan vs. optimised plan) rather than attempting a scenario-level *marginal* CPA.
**Reason:** `optimize_scenario` always calls with `conserve_total_budget=True` in every mode the
planner exposes (manual, constrained, unconstrained benchmark) - a deliberate, pre-existing design
choice (the tool reallocates a fixed budget, it doesn't recommend spending more or less overall).
With total spend held fixed by construction, "change in spend" between the current and optimised
plan is ~0, making a marginal-CPA ratio (`change in spend / change in response`) either undefined or
dominated by rounding noise - it would not mean what "marginal CPA" means at a single curve point
(docs/media_units_and_inflation.md), where spend genuinely varies. Average CPA, by contrast, is
well-defined and meaningful here: even at fixed total spend, reallocating across channels/months
changes total predicted GSAs, so the blended average CPA before and after reallocation are
genuinely different, informative numbers.
**Alternatives considered:** Computing marginal CPA anyway from the (near-zero) spend delta
(rejected - actively misleading, since a tiny denominator would produce wildly unstable numbers with
no real interpretation). Relaxing `conserve_total_budget` to let marginal CPA be computed against a
genuine budget change (rejected - out of scope for this phase and changes the planner's existing,
already-shipped default behaviour, which is a bigger decision than a display metric warrants).
**Impact:** `pages/08_Scenario_Planner.py`'s `_overall_avg_cpa` helper and the "Avg CPA (blended)"
metrics on the Manual/Constrained/Unconstrained panels. `core.optimization.evaluate_scenario`'s new
`avg_cpa` output column is the same blended-average definition, computed per month.
**Owner:** Modelling.
**Status:** Accepted; implemented in Phase 3c.

---

**Date:** 2026-07-21
**Decision:** The Scenario Planner's spend-plan editor always stores the plan in spend terms in
session state; media-unit planning mode only changes what's displayed/accepted in the editor widget,
converting at the display/input boundary using each channel's average historical cost-per-unit.
**Reason:** Keeping a single, canonical representation (spend) avoids two different session-state
shapes needing to stay in sync, and matches how `core.optimization` already works internally (spend
is the actual decision variable the optimiser operates on - media units are a translated view of
it, not an independent state). Recomputing the unit-mode display from the canonical spend plan on
every rerun also means switching modes back and forth never loses or corrupts data.
**Alternatives considered:** Storing the plan in whichever unit the user last edited it in (rejected
- means every downstream consumer of the plan, including the optimiser, would need to know which
unit is currently "live" and convert accordingly, and switching modes mid-session would need an
explicit, error-prone conversion step rather than being a pure display change).
**Impact:** `pages/08_Scenario_Planner.py`'s spend-plan editor section; channels without a media-unit
mapping always display in spend terms regardless of the selected planning mode, shown with a clear
per-column unit label (`dataframe_column_config`'s `label_overrides`) so a mixed-unit table is never
ambiguous about which column is in which unit.
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 3c.

---

**Date:** 2026-07-21
**Decision:** Build the Phase 4 project report (`core.report`) from the project's *actual current
session/persisted state* (spec, scorecard, approval, curve bank entries, scenarios,
`market_spec_config`) rather than by copying or templating the static `docs/*.md` files.
**Reason:** The redesign brief's own requirement is a *reproducible* report - one that reflects what
this specific project actually did, not a generic description of what the tool is capable of. A
report built from static docs would say the same thing regardless of whether a model had even been
fit yet; a report built from live state can honestly say "no scorecard has been computed yet" versus
showing real convergence numbers, and updates automatically as the project progresses without anyone
having to remember to edit a template.
**Alternatives considered:** Rendering the `docs/` directory itself (or a curated subset of it) as
the "report" (rejected - conflates the tool's general design documentation with a specific project
run's actual results; the two audiences and purposes are different, even though the report does
point back to `docs/decision_log.md` and related files for anyone who wants the full design
rationale behind what they're looking at).
**Impact:** `core.report.build_report_sections` takes the same kind of artefacts
`core.persistence.export_project` already exports (not a copy of the docs directory); every section
is independently missing-safe, since a report can legitimately be generated at any point in the
12-step workflow, not only once every step is complete.
**Owner:** Product/Engineering.
**Status:** Accepted; implemented in Phase 4.

---

**Date:** 2026-07-21
**Decision:** `core.report` renders both Markdown and HTML from one shared, structured
`List[ReportSection]` data model, rather than generating Markdown and parsing it into HTML (or vice
versa) with a template/parsing library.
**Reason:** A shared data model guarantees the two output formats can never drift apart in content -
whatever appears in one appears in the other, by construction, since both renderers read the exact
same section objects. Parsing Markdown into HTML (or the reverse) would need a Markdown parser
dependency this project doesn't otherwise have, for content this module already controls the exact
structure of - there's no need to round-trip through a text format only to reparse it.
**Alternatives considered:** Adding a Markdown-to-HTML library dependency (rejected - unnecessary new
dependency for a small, fully-known set of report constructs (headings, paragraphs, bullet lists,
tables) that a dozen lines of direct rendering code covers without needing a general-purpose parser).
Generating only one format and converting to the other in the UI layer (rejected - couples
`core.report` to a specific conversion library choice made by whichever page calls it, when the
module can just own both renderers itself).
**Impact:** `core.report.ReportSection`, `render_markdown`, `render_html`. HTML output is escaped via
Python's stdlib `html.escape` (project name and every paragraph/bullet/table cell) - untrusted
project names or notes text cannot inject markup into the generated document.
**Owner:** Engineering.
**Status:** Accepted; implemented in Phase 4.

---

**Date:** 2026-07-21
**Decision:** Extend `fingerprint_model_spec` to also cover the transformation recipe
(`pipeline_steps`) and a filtered, calculation-relevant subset of `MarketSpecConfig`
(`channel_media_units` + each market's `currency`) - not the whole config as-is.
**Reason:** Approval must bind to everything that actually determines a calculated result. Before
this change, two projects with identical `ModelSpec`/priors/DNA lag but different transformation
pipelines (e.g. a different log-transform or fill-NA step) or different spend/response-unit column
mappings would fingerprint identically even though the modelling data and the CPA/media-unit numbers
a planner reads could differ. But not everything in `MarketSpecConfig` is calculation-relevant:
`MarketDescriptors` (population, awareness, market maturity, etc.) is explicitly documented in
`core/market_config.py` as "Phase 1 only stores and displays these: nothing downstream requires
them" - true today, verified by reading every consumer of `MarketSpecConfig`
(`core.media_units`, `core.curve_bank.make_media_unit_entries`, `pages/07_Results_Curve_Bank.py`,
`pages/08_Scenario_Planner.py`, `pages/09_Project_Export.py`): none read `.descriptors`. Including
descriptive-only fields in the fingerprint would invalidate an analyst's approval every time someone
fixes a typo in a market's population estimate, for no calculation reason - eroding trust in what
"approval invalidated" actually means. The boundary rule going forward: a field belongs in the
fingerprint the moment any fitting, prediction, curve, CPA, or scenario code reads it; until then it
stays out, and moving it in later (e.g. if a future phase feeds `MarketDescriptors` into a
covariate) is itself a fingerprint-breaking change like any other.
**Alternatives considered:** Fingerprinting the entire `MarketSpecConfig.to_dict()` payload
unfiltered (rejected - couples approval validity to purely descriptive fields with no calculation
impact, forcing unnecessary re-review and training reviewers to treat "invalidated" as noise rather
than signal). Leaving `market_spec_config` and `pipeline_steps` out of the fingerprint entirely and
relying on `fingerprint_dataframe` of the transformed data alone (rejected - the transformed
DataFrame's *values* are covered, but the media-unit/currency config that turns those values into
CPA and response-unit-curve numbers downstream of the fit is not data, and would remain unbound to
approval).
**Impact:** `core.fingerprint.fingerprint_model_spec` gains two optional parameters,
`pipeline_steps` and `market_spec_config` (both default to `None`/empty, so existing call sites don't
break structurally); the new `core.fingerprint._model_relevant_market_config` helper implements the
filter. Every call site that binds an approval (`pages/06_Diagnostics.py`,
`pages/07_Results_Curve_Bank.py`, `pages/08_Scenario_Planner.py`,
`core.persistence.verify_imported_approval`) now passes both. This is an intentional breaking change
to every fingerprint value this function produces, including calls that pass neither new argument
(same precedent as adding `model_type` in Phase 2) - every pre-existing `ModelApproval` is
invalidated by upgrading, which is correct: those approvals were never actually bound to the
transformation recipe or media-unit/currency config they should have been.
**Owner:** Engineering.
**Status:** Accepted; implemented in PR1 (correctness and consistency pass).

---

**Date:** 2026-07-21
**Decision:** Add `core.outcomes.OutcomeDefinition` as an additive outcome catalogue (product,
segment, metric, column, value weight) layered on top of `ModelSpec`, rather than folding DNA
outcomes into `ModelSpec.segment_outcomes` or replacing that field.
**Reason:** `ModelSpec.segment_outcomes` means exactly one thing today - the Family History segments
the joint hierarchical model actually fits - and every existing call site (`core.hierarchical_model`,
`core.market_specific_model`, `core.predict`, `core.attribution`, the curve bank, the scenario
planner, the fingerprint) depends on that exact meaning. DNA kit purchases are a genuinely different
business outcome (a product sale, not an FH signup) with no response equations yet - building those
equations is later, separate work. Changing what `segment_outcomes` means, or silently expanding it
to include non-FH columns, would either break every one of those call sites or require them to start
guessing which entries are "real" FH segments. A separate, additive catalogue avoids both: `ModelSpec`
and the fitted model are completely unchanged, and the catalogue can describe DNA outcomes as captured
data without any of them being mistaken for something the model is already using.
**Alternatives considered:** Adding DNA columns directly into `segment_outcomes` with a naming
convention to distinguish them (rejected - every consumer of `segment_outcomes` would need new logic
to filter them back out, and a naming convention is exactly the kind of implicit, easy-to-violate
contract this schema exists to avoid). Waiting until DNA response equations exist before capturing any
DNA outcome data at all (rejected - the redesign brief explicitly wants outcome definitions and DNA
data support as their own, separately reviewable unit of work before the modelling equations land, so
data capture doesn't sit blocked behind a much larger change).
**Impact:** `core.outcomes` (new module): `OutcomeDefinition`, `fh_outcomes_from_spec` (backward-
compatible derivation from any `ModelSpec`), `dna_outcomes_from_columns` (split New Customer/Existing
FH Customer, or an explicit combined fallback), `resolve_outcome_definitions` (the single read path
every caller uses), `outcome_is_modelled`/`outcomes_to_dataframe`. New "DNA outcomes" section on
Structure: Segments & Markets. New `config/outcome_definitions.json` in the project bundle (absent =
legacy bundle, not an error - same convention as `market_spec_config.json`). New "Outcomes" section in
the project report. **Deliberately not** added to `core.fingerprint.fingerprint_model_spec`'s payload
- nothing in it feeds a calculation yet, so mapping or editing a DNA outcome must not invalidate an
existing model approval (same descriptive/model-relevant boundary principle as market descriptors).
Incidental fix while extending `pages/09_Project_Export.py`'s export/import wiring: `model_type` was
never actually passed to `export_project`, so every exported Model C bundle silently re-imported as
Model A - now fixed and covered by a regression test (`test_export_then_import_reproduces_model_type`).
**Owner:** Engineering.
**Status:** Accepted; implemented in PR2 (general outcome schema and DNA data support). See
`docs/outcomes.md` for the full design record.

---

**Date:** 2026-07-21
**Decision:** Generalise `FHModelMeta.dna_segment` (a single Family History segment) to
`FHModelMeta.direct_dna_segments` (a list) to fit DNA-product kit-sale segments (core.outcomes)
alongside the Family History segments in the same joint model, reusing the existing likelihood,
adstock/saturation, promo, price/control, trend and seasonality machinery unchanged - rather than
building a separate DNA-only model or a new halo-style pathway for kit sales.
**Reason:** The joint model was already fully generic over `segment` dims - nothing in
`build_fh_hierarchical_model`/`build_fh_market_specific_model` assumed a segment was a Family History
outcome specifically, except the single hardcoded `dna_segment` halo target. DNA-targeted media's
relationship to DNA kit sales is a *direct* effect (arguably DNA media's primary purpose), not a halo
effect - treating a DNA-kit segment as an ordinary "other segment" would have wrongly shrunk it toward
zero the same way an unrelated segment like Winback is shrunk. Generalising the one hardcoded
full-weight segment to a list, defaulting to `[dna_segment]` for exact backward compatibility, was the
minimal change that let every existing model-building/prediction/attribution code path keep working
unchanged for a project with no DNA segments, while giving DNA-kit segments the mechanically-correct
treatment once they're included. See docs/dna_fh_causal_structure.md for the full pathway-by-pathway
treatment (including what's deliberately *not* modelled - the kit-sale-to-later-FH-conversion pipeline
effect, and why).
**Alternatives considered:** A separate, DNA-only PyMC model (rejected - duplicates the entire
adstock/saturation/promo/trend/seasonality machinery for no structural reason, and would need its own
persistence/diagnostics/prediction code paths). Treating DNA-kit segments as ordinary halo recipients
(rejected - actively wrong: DNA media's effect on kit sales is not "a smaller effect elsewhere", it's
the primary effect, and shrinking it toward zero by construction would bias every downstream CPA/
attribution number for DNA kit sales low).
**Impact:** `core.hierarchical_model.FHModelMeta` gains `direct_dna_segments: List[str]` (defaults to
`[dna_segment]` via `__post_init__` if omitted/empty - existing bundles/tests unaffected).
`build_fh_hierarchical_model`/`build_fh_market_specific_model` gain an optional
`direct_dna_segments` parameter and a new `_resolve_direct_dna_segments` helper. Every NumPy-replay
and attribution function that previously hardcoded `segment == meta.dna_segment`
(`core.predict`/`core.market_specific_predict`'s `extract_posterior_params`,
`steady_state_segment_response(_market_specific)`, `generate_channel_curve`/
`generate_market_channel_curve`; `core.attribution._channel_log_terms`) now checks
`segment in meta.direct_dna_segments` instead - found and fixed as a direct, necessary consequence of
this change (a DNA-kit segment would otherwise have been silently mis-attributed by Shapley/curve
code even though correctly fit by the model). `core.attribution.total_fh_contribution` gained a
`segments` filter parameter so a DNA kit-sale count is never summed into an "FH total" alongside a GSA
count - wired at the two call sites (`pages/07_Results_Curve_Bank.py`, `pages/09_Project_Export.py`)
to exclude DNA-product segments from that specific total.
`data.preprocessor.prepare_fh_modeling_frame` gains an optional `dna_kit_outcomes` parameter
(segment -> column, same shape as `spec.segment_outcomes`) that extends the fitted segment set without
changing `ModelSpec`'s own shape - `pages/04_Model_Config.py` derives it automatically from whatever
DNA outcomes are mapped on Structure (`core.outcomes.dna_kit_outcome_columns`) and
`pages/05_Model_Training.py` passes the corresponding `direct_dna_segments` through to whichever
builder is fitting - opt-in, automatic once mapped, never silent (a caption on Model Configuration
always states which segments, FH and DNA, are about to be fit).
New `core.promotions` module (`PromotionEvent`, `promotion_weekly_series`,
`apply_promotion_events_to_frame`) gives DNA promotions the richer representation the instruction
document asks for (event name, dates, discount depth, sale price) while still feeding the *same*
`promo_cols`/`promo_coef` pathway every segment's promotion already uses - a promotion's effect is
structurally additive and separate from media response in the linear predictor either way, so it can
never be silently absorbed into a channel's media coefficient.
Incidental fix while extending `core.attribution`: the pre-existing `_channel_log_terms` DNA-halo
branch would have mis-attributed *any* second "dna"-named segment even before this PR (the auto-detect
in `_default_dna_segment` only ever resolved one), not just a newly-added DNA-kit segment - now
correctly generalised.
**Verification:** Offline recovery check (not a committed test - same precedent as Model C's original
check): a synthetic panel with a known, large *direct* DNA-media effect on a DNA-kit segment
(`beta=0.45`) and known, much smaller *effective* (halo-shrunk) effect on an ordinary FH segment
(`beta=0.15 x halo=0.10 -> effective 0.015`), fit with `direct_dna_segments=["DNA_CrossSell", "New
Customer"]` (300/400 tune/draws, 2 chains), correctly recovered: `halo_strength` fixed at exactly
`1.0` for both `DNA_CrossSell` and `New Customer` (not estimated, as designed), and the ordinary
segment's effective DNA_Media response (0.018) came out smallest of the three, versus 0.091
(`DNA_CrossSell`) and 0.095 (`New Customer`) - the correct ordering. Absolute point-estimate magnitudes
were compressed toward the pooled mean under the small draw budget, the same expected pattern as
Model C's original recovery check - this confirms the halo/direct structure is mechanically correct,
not tight quantitative recovery, which needs a production draw count. The fast, non-MCMC parts (the
`direct_dna_segments` logic itself at both the pre-PyMC-construction level and the NumPy-replay level)
are unit tested directly and committed - see `ancestry_mmm/tests/test_hierarchical_model.py`,
`test_predict.py`, `test_market_specific_predict.py`, `test_attribution.py`, `test_preprocessor.py`.
**Owner:** Engineering.
**Status:** Accepted; implemented in PR3 (DNA model equations and integrated halo). See
`docs/dna_fh_causal_structure.md` for the full design record.

---

**Date:** 2026-07-21
**Decision:** Add posterior uncertainty (`core.uncertainty`) as a re-run-per-draw subsample, and a
dedicated market-aware Shapley attribution module for Model C (`core.market_specific_attribution`)
that reuses Model A's baseline term but reimplements the channel-response term for market-indexed
parameters - rather than forcing Model A's implementation onto Model C, or computing uncertainty
analytically.
**Reason:** Every curve/CPA/scenario function in this codebase (`core.predict`,
`core.market_specific_predict`, `core.media_units`, `core.optimization`) works off the posterior
*mean* (`extract_posterior_params`/`extract_market_specific_posterior_params` with no `at=`) - a
single point estimate with no sense of how much the posterior actually varies. There's no closed-form
expression for the credible interval of a Hill-saturated, adstocked, exponentiated response curve or
a multi-step scenario evaluation, so the only general way to get one is to literally recompute the
same calculation once per posterior draw and summarize the resulting distribution - re-running the
existing point-estimate code path with a different draw's parameters each time, not a new modelling
approximation on top of it. Doing this against the *entire* posterior (often several thousand draws)
for every curve/scenario view would make the UI too slow to be usable, so `n_draws` (default 100, a
UI-exposed slider from 20-200) subsamples without replacement (`sample_draw_indices`) - a documented
speed/fidelity tradeoff, not a modelling shortcut.
Model A's Shapley decomposition (`core.attribution`) is built entirely around
`params.beta[segment][channel]`/`params.hill_K[channel]` - a single shared curve per channel. Model
C's parameters are market-indexed (`params.beta[market][segment][channel]`,
`params.hill_K[market][channel]`); every observation row already belongs to exactly one market via
`frame["market_idx"]` (the frame is built one contiguous block per market - `data.preprocessor.
prepare_fh_modeling_frame`), so a market-aware decomposition falls out of using each row's own
market's `beta`/`hill_K` in the per-channel log-term, with no separate market loop needed in the
permutation-average Shapley algorithm itself. Everything *not* market-indexed (intercept,
market_offset, trend_coef, gamma_fourier, promo_coef, control_coef, segment_control_coef) is identical
in shape between `FHPosteriorParams` and `FHMarketSpecificPosteriorParams`, so
`core.attribution._baseline_eta` is reused directly rather than duplicated.
**Alternatives considered:** A closed-form/delta-method approximation to posterior uncertainty
(rejected - would need a new derivation per calculation type, whereas re-running the exact existing
calculation per draw is mechanically simple and can never drift out of sync with the point-estimate
path it summarizes). Computing uncertainty against the full posterior every time (rejected - too slow
for interactive use; the UI exposes the subsample size as a control rather than hiding the tradeoff).
Adapting Model A's `compute_shapley_contributions` to accept market-indexed parameters via branching
(rejected per the brief's explicit instruction not to force Model A's implementation onto Model C -
a dedicated module keeps the parameter-shape difference explicit rather than threading `if
market_specific` branches through Model A's existing, working code).
**Impact:** `core.predict.extract_posterior_params` and
`core.market_specific_predict.extract_market_specific_posterior_params` gain an optional
`at: tuple[int, int]` (chain, draw) parameter - `None` (default) keeps the existing posterior-mean
behaviour byte-for-byte; every existing caller is unaffected. New `core.uncertainty` module:
`sample_draw_indices`, `summarize_distribution`, `generate_channel_curve_with_uncertainty`,
`generate_market_channel_curve_with_uncertainty`, `evaluate_scenario_with_uncertainty`. Scenario
uncertainty pairs draws (the same sampled draw index is used for both the proposed and baseline plan
in each comparison) rather than resampling independently - comparing two independently-resampled
distributions would overstate the apparent uncertainty in their *difference*, since it would include
sampling noise from two separate draws instead of one shared draw per comparison;
`prob_outperforms_baseline` is the fraction of paired draws where the proposed plan's total value
exceeds the baseline's. New `core.market_specific_attribution` module:
`compute_shapley_contributions_market_specific`, `segment_channel_market_summary` (adds a `market`
column - genuinely differs by market, unlike Model A), `total_contribution_market_specific` (adds a
`by_market` toggle; two-stage spend aggregation - `spend=("spend","first")` at the (market, channel)
level before any `spend=("spend","sum")` across markets - since spend is constant across every segment
row for a given (market, channel), summing it across segment rows first would double count). The DNA
halo logic (`direct_dna_segments`) is handled identically to Model A. UI: Results & Curve Bank's
Model C branch now shows a total-contribution table, market x segment x channel detail, and a
contribution waterfall (previously an "attribution isn't available" message); both model types' curve
viewers gained an opt-in posterior-uncertainty band (a new `create_response_curve_with_band` chart);
Scenario Planner's manual tab gained an opt-in posterior-uncertainty view with
`prob_outperforms_baseline` against the recent-average-spend baseline; Project Export's Model C Excel
branch gained "Total Contribution" and "Market x Segment x Channel" sheets. `docs/limitations.md`,
`docs/user_guide.md`, `docs/curve_bank.md`, `docs/modelling_methodology.md`, and `core/report.py`'s
limitations section had their "Shapley attribution remains Model-A-only" claims removed as now stale,
replaced where relevant with the uncertainty-approximation caveat.
**Verification:** `compute_shapley_contributions_market_specific`'s additivity
(`baseline + sum(channel_contributions) == mu_total`, exactly, for every row/segment) and correct
`direct_dna_segments` halo handling are unit tested directly
(`ancestry_mmm/tests/test_market_specific_attribution.py`), as is the two-stage spend aggregation (no
double counting across segment rows) and the `segments`/`by_market` filters.
`generate_channel_curve_with_uncertainty`/`generate_market_channel_curve_with_uncertainty` are tested
for `lower <= mean <= upper` at every spend point and for raising no warnings despite the
legitimately-all-NaN marginal-CPA-at-zero-spend case (`ancestry_mmm/tests/test_uncertainty.py`).
`evaluate_scenario_with_uncertainty` is tested for the same interval ordering and for
`prob_outperforms_baseline` correctly reaching 1.0/0.0 for a plan that strictly dominates/is dominated
by its paired baseline. `extract_posterior_params`/`extract_market_specific_posterior_params`'s new
`at=` parameter is tested directly for both model types (`test_predict.py`,
`test_market_specific_predict.py`) - a specific `(chain, draw)` selection must disagree with both
another draw and the posterior mean. All three new pages' code paths (curve-uncertainty checkboxes,
Model C attribution tables, scenario-uncertainty checkbox, Excel export's new sheets, project report)
were exercised end-to-end via `streamlit.testing.v1.AppTest` against two real (small, fast) MCMC fits -
one Model A, one Model C - not just hand-built parameter fixtures; not committed, per this project's
established convention for AppTest verification scripts.
**Owner:** Engineering.
**Status:** Accepted; implemented in PR4 (Model C attribution and uncertainty).

---

**Date:** 2026-07-21
**Decision:** Replace the single-lagged-media-series-plus-multiplier representation of "direct" DNA
response (`direct_dna_segments` fixed `halo_strength = 1.0`, still routed through the same
`dna_lag_weeks`-lagged series every halo segment used) with two genuinely separate media inputs -
`dna_direct_media` (no extra lag) and `dna_halo_media` (a further lag on top) - and let the FH
DNA-cross-sell segment use both simultaneously with an independently estimated, regularised halo
term, rather than one fixed-weight pathway.
**Reason:** A post-merge correctness audit (prompted by the instruction document "Ancestry MMM
Repository: Required Next Changes After July 2026 Review") verified this end to end - both by reading
the code and by running the real `core` functions (fit, predict, attribute, export/import) against all
four combinations of {FH-only, FH-plus-DNA} x {Model A, Model C} - and found that `direct_dna_segments`
members never actually received an undamped, immediate response: the PyMC likelihood's `eta_dna`,
`core.predict`/`core.market_specific_predict`'s `predict_mu`, and `core.attribution`/
`core.market_specific_attribution`'s Shapley decomposition all computed a DNA-kit segment's response
against `lagged_dna_sat`/`lagged_dna` - the exact same lag-shifted series a halo segment used - with
only the multiplier (`halo_strength`) differing. For real (non-constant) historical spend this is not
a cosmetic distinction: it meant a kit-sale segment's fitted response, and every dollar Shapley
attributed to it, was tied to media spend from `dna_lag_weeks` weeks earlier rather than the week the
purchase decision was actually driven by. The steady-state scenario/curve functions masked this in
manual testing (a lag of a constant series is that same constant), which is why it survived three
prior PRs' worth of review before being caught by the audit's explicit "run FH-plus-DNA end to end with
non-constant data, don't trust docs or commit messages" mandate. The instruction document also asked
that the FH DNA-cross-sell segment be allowed a direct, delayed, or both pathway rather than assuming
one - the prior design couldn't represent "both" at all (one segment, one multiplier).
**Alternatives considered:** Leaving `halo_strength = 1.0` as the sole "direct" signal and only fixing
which series it multiplies (rejected - `dna_segment` genuinely needs the ability to respond to *both*
an immediate and a delayed effect with independently-sized coefficients, which a single scalar
multiplier on a single series cannot represent). Giving `dna_segment` a wholly separate,
independently-partial-pooled beta for its halo component distinct from its direct-pathway beta
(rejected as unnecessary complexity - reusing the existing partial-pooled `beta[segment, DNA-channel]`
for both terms, differentiated only by which media input and whether an extra regularised
`halo_strength` multiplier applies, is simpler, avoids adding another hierarchical parameter block for
a small marginal benefit, and is exactly what the recovery check below confirms is sufficient to
recover both a true direct and a true delayed effect from real data).
**Impact:** `FHModelMeta` gains two properties: `kit_only_segments` (`direct_dna_segments` minus
`dna_segment` - direct pathway only, no halo term at all) and `halo_eligible_segments` (every segment
except the kit-only ones - `dna_segment` is the one member with both). Both PyMC builders
(`build_fh_hierarchical_model`, `build_fh_market_specific_model`) construct `dna_direct_media`
(`sat_media` for DNA channels, no extra lag) and `dna_halo_media` (that series further lagged by
`dna_lag_weeks`, renamed from the old `lagged_dna_sat`/`lagged_dna` naming) as two separate
deterministics, and sum two additive eta terms (`eta_dna_direct` using a fixed 0/1 `has_direct` mask,
`eta_dna_halo` using the (now segment-set-restricted) estimated `halo_strength`) instead of one. The
underlying PyMC variable name for the halo shrinkage prior changed from `halo_strength_other` to
`halo_strength_est` (its shape changed - it now covers `halo_eligible_segments`, including
`dna_segment`, not `segments - direct_dna_segments`) - this is an intentional breaking change to any
existing trace/curve-bank entry involving DNA channels, the same "re-fit and re-approve" pattern this
project has used for every prior structural model change (docs/decision_log.md's fingerprint-payload
entries). The final `halo_strength` Deterministic keeps its name/shape/dims, so
`extract_posterior_params`/`extract_market_specific_posterior_params`'s reading of it is unaffected;
only its *values* differ (exactly `0.0` for kit-only segments now, versus a placeholder `1.0` before -
this is itself a fix, not just a refactor, since `0.0` correctly states "no halo pathway" instead of
implying a full-weight halo that was never actually being used).
`core.predict`/`core.market_specific_predict`'s `predict_mu`, `steady_state_segment_response`,
`generate_channel_curve` (and Model C equivalents), and `core.attribution`/
`core.market_specific_attribution`'s `_channel_log_terms` all construct the same
`dna_direct_media`/`dna_halo_media` split and additionally mask the halo term to
`halo_eligible_segments` defensively - not merely trusting a `params` object's `halo_strength` to
already be `0` for a kit-only segment, so the "no halo pathway for kit-only segments" invariant holds
structurally in the replay/attribution code even against a malformed or hand-built `params`, not only
against a correctly-fitted one. The steady-state functions collapse the two media inputs to the same
constant value (spend held constant forever), so their formulas sum `has_direct + halo_strength` as one
combined weight - documented inline at each call site.
**Verification:** Four required invariants (kit response doesn't inherit the extra halo lag, FH halo
does, changing the halo lag doesn't alter the direct kit response, direct and halo effects are not
double counted) are proven directly and committed, for both model types at both the prediction and
Shapley-attribution layers - `ancestry_mmm/tests/test_predict.py::TestPredictMuDirectHaloSeparation`,
`test_market_specific_predict.py::TestPredictMuMarketSpecificDirectHaloSeparation`,
`test_attribution.py::TestShapleyDirectHaloSeparation`,
`test_market_specific_attribution.py::TestShapleyMarketSpecificDirectHaloSeparation` - using a
single-media-spike synthetic frame (spend nonzero in exactly one week) so the lag's effect lands on an
unambiguous, disjoint week index rather than being inferred indirectly. The full existing 500-test
suite passes unmodified (516 total after these additions), including two tests that previously encoded
the old (incorrect) fixture assumption that a kit-only segment's `halo_strength` value was irrelevant
regardless of what it was set to - those fixtures are now realistic (`halo_strength = 0.0` for
kit-only segments, matching what the model itself now guarantees) and pass under the new, structurally
correct behaviour rather than by coincidence.
Offline recovery check (not a committed test, same precedent as every prior recovery check in this
log): a synthetic panel where kit sales respond only to the *current* week's DNA media, an ordinary FH
halo segment (Winback) responds only to a *lagged* week's, and the FH DNA-cross-sell segment responds
to *both* (true direct weight 0.35, true delayed weight 0.12), fit with a real MCMC run (350
tune/draws, 2 chains, single market, 180 weeks). Recovered: kit-only segment's `halo_strength` fixed at
exactly `0.0` (structural, confirmed post-fit) with a positive, substantial `beta` (2.95); DNA-cross-sell
recovering *both* a positive, substantial `beta` (1.70, its direct term) *and* a meaningfully nonzero
`halo_strength` (0.33, its delayed term); the ordinary halo segment (Winback) still recovering a
meaningfully nonzero `halo_strength` (0.49). See docs/dna_fh_causal_structure.md's "Validation" section
for the full write-up.
**Owner:** Engineering.
**Status:** Accepted; implemented in PR B (direct DNA versus halo correction, per the post-merge
correctness audit's PR ordering). See docs/dna_fh_causal_structure.md for the full design record.

---

**Date:** 2026-07-21
**Decision:** PR C ("Outcome-aware semantics: canonical outcomes, unit-safe totals, CPA and
objectives, run-aware status and migrations", per the instruction document's PR ordering) - nine
sub-changes, each verified and tested before the next started:

1. `OutcomeDefinition` gains `unit` (derived default: `"GSA"` for Family History, `"kit"` for DNA) and
   `role` (default `"primary"`, free text) fields, migration-safe (`from_dict` filters to known
   dataclass fields, so an older/missing key just uses the field default - nothing to migrate
   explicitly).
2. Replace the single collapsed `outcome_is_modelled(outcome)` boolean with a static,
   type-level `outcome_requires_opt_in(outcome)` plus a run-aware `outcome_was_modelled(outcome,
   model_meta)`, and a six-state `outcome_status(...)` (`OUTCOME_STATUSES`: `Configured`, `Included in
   prepared frame`, `Included in fitted run`, `Missing source column`, `Excluded`, `Stale after
   configuration changes`) that a single boolean can't express. A genuine "exclude this DNA outcome
   from the next fit" `st.multiselect` on the Structure page (`excluded_outcome_ids`, session state)
   is consumed by `pages/04_Model_Config.py` to filter `dna_kit_outcomes` before preparing the frame -
   not decorative.
3. `core.predict.generate_channel_curve`/`core.market_specific_predict.generate_market_channel_curve`
   gain `fh_response`/`dna_response` columns, computed from `meta.kit_only_segments` alone (which is,
   by construction, exactly the set of segments with `OutcomeDefinition.product == DNA` - no new
   `core.outcomes` import into `core.predict`, avoiding an import-cycle risk).
4. `core.media_units.compute_cpa` raises on its `"overall_response"` default when a curve genuinely
   mixes `fh_response`/`dna_response`, unless the caller passes an explicit `response_col` or
   `allow_mixed=True`; `compute_cpa_by_product` is the new safe default entry point (always computes
   plain `avg_cpa`/`marginal_cpa` against `fh_response`, plus prefixed `dna_avg_cpa`/
   `dna_marginal_cpa` against `dna_response` where non-trivial) - wired into
   `market_specific_cpa_table`, `core.uncertainty`'s curve-uncertainty functions, and Results & Curve
   Bank. The same mixed-denominator guard was extended to `equivalent_response` (a direct correctness
   issue - it returns a single response number a caller could misread) but deliberately not to
   `cpa_stability_flags` (advisory flags about curve shape, not a dollar-denominated answer - a
   documented, lower-severity residual gap).
5. `core.optimization.evaluate_scenario` gains `fh_gsa`/`dna_kits` (month totals, each summed only
   over its own product's segments), a Family-History-scoped `avg_cpa` (replacing the previous
   behaviour, which divided total spend by predicted GSAs summed across *every* segment including
   DNA-kit segments), `dna_avg_cpa`, and `total_value` (safe to sum across products - LTV already
   expresses both in one currency unit, unlike a raw GSA/kit count). `compare_scenarios`' `total_gsa`
   (same all-segments-summed defect) is replaced with `total_fh_gsa`/`total_dna_kits`, de-duplicated
   by month before summing (`fh_gsa`/`dna_kits` are month-level totals repeated per segment row).
6. `core.optimization.optimize_scenario`'s `objective` becomes an explicit enum
   (`VALID_OBJECTIVES`: `"fh_gsa"`, `"dna_kits"`, `"weighted_mix"`, `"expected_value"`) instead of
   `"value"`/`"volume"` - `"volume"` gave every segment weight `1.0` regardless of product, silently
   summing FH GSAs and DNA kits into one meaningless total (the audit's confirmed
   `volume_objective_mixes_units` defect). A segment outside the chosen objective's scope now
   contributes weight `0`, never an implicit `1` - this also fixed a latent version of the same bug in
   the old `"value"` objective (a segment missing from `ltv` silently got weight `1.0`, mixing a raw
   count into an LTV-dollar total). `target_segments`/`weights` parameters generalise "maximise a
   single named segment" (e.g. "FH New") and a fully custom weighted mix without hardcoding segment
   names into library code. The Scenario Planner UI's objective radio, manual-tab totals, and
   optimisation-result CPA panels were updated in lockstep (not deferred to a later UI-wiring pass) -
   `"Maximise FH GSAs"` / `"Maximise DNA kit sales"` (only offered where the model has DNA-kit
   segments) / `"Maximise LTV-weighted expected value"`.
7. `fingerprint_model_spec` gains a `direct_dna_segments` parameter (sorted before hashing - an
   unordered set of segments) - closing the audit's second confirmed defect: which DNA-kit outcomes
   are included in a fit changes `meta.segments`/`direct_dna_segments` without touching `model_spec`,
   prior config, pipeline steps, or the raw data at all, so an approval could stay "matching" across
   two structurally different fits. All four production call sites (Diagnostics, Results & Curve
   Bank, Scenario Planner, `verify_imported_approval`) now pass the fitted model's own
   `meta.direct_dna_segments`. Separately, `reconstruct_model_state` now recomputes `dna_kit_outcomes`
   from the bundle's own `outcome_definitions` (`resolve_outcome_definitions` +
   `dna_kit_outcome_columns`, the identical derivation `pages/04_Model_Config.py` uses) before
   rebuilding the frame - previously it rebuilt from `transformed_data` + `model_spec` alone, silently
   dropping every DNA-kit segment, so a reimported FH-plus-DNA project's frame came back FH-only,
   disagreeing with `model_meta.segments` from the same bundle (the audit's measured
   `reimport_frame_matches_meta_segments: False`).
8. UI wiring for pages 03/07/08/09: substantially already correct as a direct consequence of fixing
   each call site immediately within steps 4/6 above rather than deferring - verified by a systematic
   sweep (no remaining bare `compute_cpa(...)` calls, no remaining `"volume"`/`"value"` objective
   strings) that found only one further gap, a stale in-app "what's out of scope" caption on Project
   Export describing the old unlabelled-volume objective; fixed in place.
9. Tests were written alongside each step above, not deferred to a separate pass - `TestComputeCpa`'s
   mixed-denominator cases, `TestComputeCpaByProduct`, `TestEquivalentResponse`'s guard tests (PR C4);
   `TestProductAwareScenarioOutputs`, `TestComputeCpaByProduct`-equivalent `compare_scenarios` tests,
   an uncertainty-summary product-aware-columns test (PR C5); `TestExplicitOptimisationObjectives`
   (10 tests covering every `VALID_OBJECTIVES` value plus the invalid-objective/missing-weights/
   missing-ltv rejection paths) (PR C6); `TestFingerprintModelSpecDirectDnaSegments` and
   `TestReconstructModelStateWithDnaKitOutcomes` (the direct regression test for the persistence
   defect - asserts a reconstructed frame's segments now match the fitted model's, both for a bundle
   with `outcome_definitions` and for a legacy bundle without one) (PR C7).

**Reason:** The instruction document's post-merge correctness audit (`docs/decision_log.md`'s PR A
entry) found that every "total" the app exposed for a project with DNA-kit outcomes mapped - curve
response, CPA, scenario predicted-GSAs, optimiser objective value - silently summed Family History
GSAs and DNA kit sales as if they were the same unit, and that neither the fingerprint nor the
persistence round-trip actually tracked which DNA-kit outcomes a given fit included. None of this was
visible in the UI as a caveat; a project with DNA-kit outcomes mapped would report numbers that looked
exactly as trustworthy as an FH-only project's, but weren't. PR C makes every one of these outputs
explicit about which product(s) it counts, blocks the generic mixed-unit path outright (raise, not a
silent default) where the output is a single dollar/count figure a business decision could ride on,
and closes the two structural gaps (fingerprint, reimport) that let a stale or mismatched model
identity go undetected.
**Alternatives considered:** A single "blended" total with a footnote (rejected - the instruction
document explicitly rules this out: "do not expose a generic total volume that adds kits and GSAs" /
"CPA must identify its denominator"; a footnote is exactly the kind of thing an analyst under time
pressure skips). Fingerprinting the full resolved `dna_kit_outcomes` dict (segment -> source column)
instead of just `direct_dna_segments` (rejected for this PR - `direct_dna_segments` closes the
measured, confirmed defect (segment membership) at much lower complexity; the column-mapping edge
case is called out as a documented residual gap rather than expanding scope). Persisting
`excluded_outcome_ids` in the project bundle now, to close the reimport's remaining residual gap fully
(rejected for this PR - the current fallback, "reimport re-includes every mapped DNA outcome", is
visible and immediately correctable on the next fit, not a silent-data-loss defect like the one this
PR fixes; adding a new persisted field is better scoped as its own small change).
**Impact:** See the nine numbered points above for the concrete API/behaviour changes. Every existing
approval computed before this PR is invalidated by the `fingerprint_model_spec` payload change (the
same "adding a genuinely model-relevant field is an intentional breaking change" pattern used for
every prior fingerprint-payload addition in this log) - correct, since an approval that didn't cover
DNA-kit segment membership was never actually binding on it. `optimize_scenario`'s default `objective`
changed from `"value"` to `"fh_gsa"` (the old default silently required nothing and fell back to
raw-volume weighting when no `ltv` was given - the new default requires nothing either, but is always
unit-safe instead).
**Verification:** Full test suite run after each of the nine steps (529 -> 540 -> 544 -> 547 -> 557 ->
563 passing across PR C4-C7; no regressions at any step), `ruff check` clean throughout. A live
`streamlit.testing.v1.AppTest` run against a real (small, fast) MCMC fit with a genuine DNA-kit
segment present drove the Scenario Planner end-to-end: page load, all three objective radio options,
and both constrained and unconstrained optimisation for every objective - zero exceptions, sane and
visibly distinct metrics per objective (e.g. `"fh_gsa"` and `"dna_kits"` current-total metrics differ
by more than 2x on the same spend plan, confirming the objectives are actually scoped to different
segment sets rather than coincidentally computing the same number).
**Owner:** Engineering.
**Status:** Accepted; implemented in PR C (outcome-aware semantics, per the post-merge correctness
audit's PR ordering). See docs/outcomes.md, docs/dna_fh_causal_structure.md, docs/scenario_planner.md,
docs/media_units_and_inflation.md and docs/limitations.md for the updated design records.

---

**Date:** 2026-07-22
**Decision:** PR E ("Canonical outcome schema and outcome_id model identity", per the instruction
document's PR ordering) - make `OutcomeDefinition` the model's sole fitting schema and `outcome_id`
(not `segment`) the identity dimension carried through every stage of the pipeline, so a Family
History sign-up and a Family History GSA in the same customer segment fit as two fully independent
outcomes instead of colliding.
1. `ModelSpec.segment_outcomes`/`segment_ltv`/`segment_control_cols` remain in `core/schema.py` but
   are now purely a migration source (`resolve_outcome_definitions` still reads them for legacy
   projects); the actual fitting path takes an explicit `outcomes: List[OutcomeDefinition]` and never
   re-derives identity from `segment` once a catalogue exists. `prepare_fh_modeling_frame(df, spec,
   outcomes=None)` filters the catalogue through a new `included_outcomes()` helper and raises if
   nothing survives, rather than silently fitting on `spec.segment_outcomes` alone.
2. `OutcomeDefinition` gains two new persisted fields, `included_in_fit` and `exclusion_reason`,
   replacing the old session-only `excluded_outcome_ids` mechanism the PR C entry above flagged as a
   documented residual gap ("adding a new persisted field is better scoped as its own small change").
   Exclusion is now data the project bundle carries across export/import, not UI state that resets on
   reload. `OutcomeDefinition.column` is renamed `source_column`, with `from_dict` translating the
   legacy `"column"` key so older exported bundles still import cleanly.
3. Every PyMC coordinate, NumPy replay dict, and downstream key that was `segment` is now
   `outcome_id`: the model builders' PyMC coord (`"segment"` -> `"outcome"`), `FHModelMeta`
   (`segments`/`dna_segment`/`direct_dna_segments`/`kit_only_segments`/`halo_eligible_segments`/
   `segment_control_names` -> `outcome_ids`/`dna_outcome_id`/`direct_dna_outcome_ids`/
   `kit_only_outcome_ids`/`halo_eligible_outcome_ids`/`outcome_control_names`, plus new
   `outcome_id_to_segment`/`outcome_id_to_product`/`outcome_id_to_metric`/`outcome_id_to_unit`/
   `outcome_id_to_role`/`outcome_id_to_source_column`/`outcome_catalogue_at_fit` fields recording the
   exact `OutcomeDefinition` list a fit was built from), `FHPosteriorParams.segment_control_coef` ->
   `outcome_control_coef`, attribution/optimisation/diagnostics/evidence-tier/curve-bank output
   columns (`"segment"` -> `"outcome_id"`, `evaluate_scenario`'s `"predicted_gsa"` ->
   `"predicted_outcome"`), and function parameters (`total_fh_contribution`/
   `total_contribution_market_specific`'s `segments=` -> `outcome_ids=`, `contribution_waterfall`'s
   `segment=` -> `outcome_id=`, `optimize_scenario`'s `target_segments` -> `target_outcome_ids`,
   `fingerprint_model_spec`'s `direct_dna_segments` -> `direct_dna_outcome_ids`). This closes the
   naming confusion the instruction document called out directly: a generic "GSA" total or a bare
   `segment` key can no longer imply a single KPI when two distinct KPIs share a segment.
4. `core/curve_bank.py`'s persisted `CurveBankEntry.segment_or_overall` field name was deliberately
   left unchanged - it is written to exported curve bank JSON, and renaming it is a much larger,
   riskier change (every page reading/filtering that column) for no correctness benefit within this
   PR's scope. Only the code that populates the field was changed to write outcome_ids instead of
   segment names.
5. Two modules outside the instruction document's originally listed scope, `core/diagnostics.py` /
   `core/market_specific_diagnostics.py` and `core/evidence_tiers.py`, were found still reading
   `meta.segments` after the `FHModelMeta` rename and would have broken at runtime; fixed in place
   since they are directly coupled to `FHModelMeta`'s shape.
6. UI pages 03-09 were updated in lockstep: page 03's save handler now applies
   `included_in_fit=False, exclusion_reason=...` onto matching outcomes via `dataclasses.replace`
   instead of writing session-only `excluded_outcome_ids`; page 04 builds the frame from
   `included_outcomes(outcome_definitions)`; pages 05/06/07/08/09 all pass and read
   `outcome_ids`/`direct_dna_outcome_ids`/`outcome_controls` instead of the old segment-named
   equivalents.
**Reason:** The instruction document required Family History sign-ups and GSAs to be modellable as
distinct KPIs within the same customer segment - impossible under the old schema, where `segment` was
simultaneously "customer cohort" and "the model's fitting identity," so two KPIs sharing a segment
could not both be fit independently. Making `OutcomeDefinition`/`outcome_id` canonical removes that
conflation at the source instead of adding another special case on top of `segment`.
**Alternatives considered:** Keep `segment` as the fitting identity and add a secondary `metric`/
`kpi` disambiguator only where two outcomes collide (rejected - this leaves every existing "segment"
key in attribution, optimisation, persistence and the UI ambiguous about which axis it means, and
only defers the same rename to whichever call site hits the first real collision). Renaming
`CurveBankEntry.segment_or_overall` to match (rejected for this PR - persisted-file field name,
larger blast radius than the correctness gain justifies; documented as a residual naming
inconsistency instead).
**Impact:** Every fitted model, persisted project bundle, and approval fingerprint from before this
PR uses segment-keyed identity and is not compatible with the outcome_id-keyed code paths this PR
introduces - existing bundles must be re-fit and re-approved, consistent with this log's established
"a genuinely model-relevant schema change is an intentional breaking change" pattern. `included_in_fit`
defaults to `True` on legacy `OutcomeDefinition.from_dict` loads, so previously-included outcomes stay
included after migration.
**Verification:** Core layer test suites rewritten and passing across every touched module
(`test_outcomes.py`, `test_preprocessor.py`, `test_hierarchical_model.py`,
`test_market_specific_model.py`, `test_predict.py`, `test_market_specific_predict.py`,
`test_attribution.py`, `test_market_specific_attribution.py`, `test_optimization.py`,
`test_media_units.py`, `test_uncertainty.py`, `test_market_specific_diagnostics.py`,
`test_evidence_tiers.py`, `test_curve_bank.py`, `test_persistence.py`, `test_fingerprint.py`,
`test_report.py`); full suite green and `ruff check` clean after each step. Two offline (not
committed, matching this codebase's established convention for anything requiring real PyMC
sampling) real-MCMC scripts additionally proved the architecture end-to-end: one fits Model A and
Model C on data with an FH sign-up and an FH GSA sharing one segment plus a DNA-kit outcome, and
confirms each outcome gets its own independent posterior and response curve; the other walks every
core-function call sequence pages 03-09 actually make (structure -> config -> training -> diagnostics
-> results/curve bank -> scenario planner -> export/import/verify-approval/report), for both model
types, with zero exceptions.
**Owner:** Engineering.
**Status:** Accepted; implemented in PR E (canonical outcomes and outcome_id model identity, per the
post-merge correctness audit's PR ordering). See docs/outcomes.md and
docs/dna_fh_causal_structure.md for the updated design records.

---

**Date:** 2026-07-22
**Decision:** PR E.1 ("Correctness hardening on top of the canonical-outcome refactor" - the
instruction document's explicit "do this before implementing the media-pathway schema" directive) -
close the gap PR E left open: the core model could already fit an FH sign-up and an FH GSA as
independent outcome_ids, but aggregation/CPA/optimiser/fingerprint/drift-detection code still keyed
off "is this outcome_id a DNA-kit outcome" rather than the catalogue's actual product/metric/role
labels, so a sign-up outcome could still be silently folded into a total labelled `fh_gsa`.
1. `core.outcomes.select_outcome_ids(model_meta, *, product=None, metric=None, unit=None, role=None)`
   is now the single place every total/CPA/objective goes to decide which outcome_ids belong in a
   named number, reading `FHModelMeta.outcome_id_to_product`/`_metric`/`_unit`/`_role` (the exact
   fit-time catalogue). Three named totals build on it - `fh_gsa_outcome_ids`
   (product=Family History, metric=GSA), `fh_signup_outcome_ids` (metric=Sign-up),
   `dna_kit_sale_outcome_ids` (product=DNA, metric=Kit sale) - each defaulting to `role="primary"`
   only, per the newly-operational role semantics (`"secondary"`/`"funnel_intermediate"`/
   `"diagnostic"` are excluded from default totals; `included_in_fit` remains the separate axis
   controlling fitting eligibility). A `FHModelMeta` with no catalogue metadata at all (a bundle
   exported before `outcome_catalogue_at_fit` existed, or a hand-built test fixture) falls back to the
   pre-PR-E.1 "every outcome_id that isn't structurally DNA-kit-only is the GSA total" behaviour,
   preserving backward compatibility for every legacy fit and this codebase's own pre-existing test
   fixtures without a mass rewrite.
2. `core.predict.generate_channel_curve`/`core.market_specific_predict.generate_market_channel_curve`
   split `overall_response` into `fh_response` (GSA-metric only, not "every non-DNA-kit outcome" as
   before), a new `fh_signup_response` column, and `dna_response`. `core.media_units.
   compute_cpa_by_product` gained `fh_signup_avg_cpa`/`cost_per_fh_signup` alongside the renamed-as-
   aliased `cost_per_fh_gsa`/`cost_per_dna_kit` (`"CPA must identify its denominator"` - the
   instruction document's explicit requirement, extended from product-aware to metric-aware).
   `core.optimization.evaluate_scenario` gained an `fh_signups` column (never summed into `fh_gsa`)
   and `VALID_OBJECTIVES` gained `"fh_signups"` (Family History sign-up outcomes only), wired into the
   Scenario Planner's objective radio alongside `"fh_gsa"`/`"dna_kits"`/`"expected_value"`.
3. **Value weights never silently default to 1.0** (the second confirmed defect). A *partial* `ltv`
   dict (some outcome_ids priced, others not) used to backfill missing entries with weight 1.0 when
   computing `value`/`total_value`/`value_contribution` in `evaluate_scenario` and
   `outcome_channel_summary` (renamed from `segment_channel_summary`) - now a missing entry makes that
   row's value `None`/`NaN`, and `evaluate_scenario` carries a `total_value_is_complete` flag
   (`compare_scenarios` propagates it) so a caller can show an explicit incomplete-value warning. An
   **entirely omitted** `ltv` is not this defect (no $-weighting was requested at all) - `value`
   there is simply raw predicted units, unchanged from pre-PR-E.1 behaviour. `core.optimization`'s
   `"expected_value"` objective goes further and fails closed: it now raises if any eligible outcome
   has no finite, non-negative `ltv` entry, rather than silently zero- or one-weighting it.
4. **General outcome catalogue editor** on the Structure page (`st.data_editor`, one row per outcome)
   replaces the legacy per-segment "map one weekly GSA column" mapper as the actual saved source of
   truth - the FH segment mapper and DNA-column mapper still exist as convenient defaults that seed
   the table, but the edited table's rows (converted to `OutcomeDefinition`s) are what gets persisted,
   closing the confirmed gap that the core model could fit two KPIs per segment but the UI could never
   actually configure that. `included_in_fit` is now an editable checkbox column in the same table,
   replacing the old separate "exclude this DNA outcome" multiselect. Removed the "FH DNA-cross-sell
   signup GSA" wording the instruction document flagged directly - a row is now either a sign-up KPI
   or a GSA KPI, never described as both.
5. **Explicit FH DNA cross-sell target** (`ModelSpec.fh_dna_cross_sell_outcome_id`) replaces
   `core.hierarchical_model._default_dna_outcome_id`'s substring-based fallback ("the first outcome_id
   containing 'dna'") - genuinely ambiguous now that DNA-product kit-sale outcome_ids (e.g.
   `dna_new_kit`) are also in the catalogue, and never validated to point at a Family History outcome
   at all. `core.outcomes.validate_fh_dna_cross_sell_outcome_id` checks it exists among included
   outcomes, belongs to Family History, and isn't a DNA-kit outcome; both model builders now **raise**
   if DNA-targeted channels are configured and no `dna_outcome_id` is resolvable, instead of guessing.
   `infer_legacy_fh_dna_cross_sell_outcome_id` offers the old substring heuristic as a one-time,
   visibly-flagged migration suggestion only for legacy projects - never a runtime fallback.
6. **Role made operational.** `OutcomeDefinition.role` (`"primary"`/`"secondary"`/
   `"funnel_intermediate"`/`"diagnostic"`, validated since PR C but not previously read anywhere) now
   controls default-total eligibility via the named selectors above - a sign-up outcome marked
   `funnel_intermediate`, for instance, is excluded from the default `fh_signups` total unless a
   caller explicitly asks for non-primary roles.
7. **Full outcome catalogue fingerprinted**, not just DNA-kit membership. PR E's
   `direct_dna_outcome_ids` fingerprint parameter only covered which DNA-kit outcomes were included -
   it missed adding/removing a non-DNA FH outcome, changing sign-up to GSA, changing unit/source
   column/role/inclusion, or changing the value weight used in planning. `core.fingerprint.
   fingerprint_model_spec`'s new `outcome_catalogue` parameter (fed
   `core.outcomes.outcome_catalogue_fingerprint_payload(meta.outcome_catalogue_at_fit)` - sorted by
   outcome_id, calculation-relevant fields only) closes this; every production call site (Diagnostics,
   Results & Curve Bank, Scenario Planner, `verify_imported_approval`) now fingerprints the fitted
   model's own fit-time catalogue, not the project's possibly-since-edited current one. Every
   pre-existing approval is invalidated by this change - the same "adding a genuinely model-relevant
   field is an intentional breaking change" pattern used for every prior fingerprint addition in this
   log.
8. **Exact fit-time drift detection.** `outcome_status` (PR C) only detects a mapped source column
   disappearing - it can't tell "the mapping changed to a different, still-present column" from
   "unchanged". `core.outcomes.outcome_drift_status`/`outcomes_drift_dataframe` compare the current
   catalogue against `FHModelMeta.outcome_catalogue_at_fit` field-by-field
   (source_column/product/segment/metric/unit/role/included_in_fit/value_weight), returning one of six
   named statuses (`Fitted and current`, `Excluded from next fit`, `Changed since fit`, `Missing
   source column`, `New since fit`, `Removed since fit`) - the instruction document's required
   vocabulary verbatim.
9. **Segment-era API renames**, with deprecated aliases retained where an existing import might still
   reference the old name: `steady_state_segment_response`/`_market_specific` ->
   `steady_state_outcome_response`/`_market_specific`; `segment_channel_summary`/
   `segment_channel_market_summary` -> `outcome_channel_summary`/`outcome_channel_market_summary`.
   `CurveBankEntry.segment_or_overall` was deliberately left unrenamed again (same persisted-field
   blast-radius reasoning as PR E) - documented in `docs/curve_bank.md`.
**Reason:** The instruction document's own audit of the merged PR E found that "make `OutcomeDefinition`
canonical" and "make `outcome_id` the identity dimension" were necessary but not sufficient - a fit
could have two independent KPIs on one segment, but every consumer of that fit (scenario evaluation,
optimisation, CPA, the fingerprint, drift detection, and the Structure page's own editor) still
reasoned about outcomes at the product level or the legacy segment level, so the two-KPI capability
was fitted but not actually usable or safe to plan against. Each of the nine points above closes one
specific way that gap could silently produce a wrong or misleadingly-labelled number.
**Alternatives considered:** Keeping `meta.kit_only_outcome_ids`-based selection and adding a second,
separate signup-specific filter only where a collision is hit (rejected - same reasoning as PR E's
segment/outcome_id conflation: defers the fix to whichever call site hits the first real two-KPI
project, rather than closing it at the source). Treating an entirely-omitted `ltv` the same as a
partially-populated one (i.e. always requiring complete coverage) for `evaluate_scenario`'s display-
only `value` column (rejected - would break the common "I don't want $-weighting, just show me
volume" usage for no correctness benefit; the actual defect is specifically the *partial*-coverage
silent-1.0 case, which `core.optimization`'s `"expected_value"` objective already fails closed on).
Renaming `CurveBankEntry.segment_or_overall` alongside the other segment-era API renames (rejected for
this PR - same persisted-file blast-radius reasoning as PR E).
**Impact:** Every fitted model, persisted project bundle, and approval fingerprint from before this PR
is invalidated by the new `outcome_catalogue` fingerprint payload - existing bundles must be re-fit and
re-approved. A project with DNA-targeted channels configured but no `fh_dna_cross_sell_outcome_id` set
will now fail to train (previously it silently guessed) until the analyst sets it explicitly on the
Structure page - a deliberate fail-closed change, not a regression. `evaluate_scenario`'s `value`
column can now be `None` for individual rows where `ltv` is partially incomplete - any caller reading
it must handle that (`total_value_is_complete` is the flag to check).
**Verification:** 672 tests passing (604 -> 672 across this PR's steps), `ruff check` clean throughout.
All 17 of the instruction document's required test cases are covered: FH GSA only / FH sign-up only /
both together / multiple segments each with both / FH plus DNA kits / same-segment independent
posterior dimensions / GSA-only and sign-up-only optimisation objectives / named CPA denominators /
missing value weights never silently 1.0 / catalogue-change invalidates approval / valid-column remap
detected as stale / explicit FH DNA cross-sell target required / legacy bundles migrate safely / Model
A and Model C parity / a Streamlit AppTest exercising the Structure page with two KPIs already
configured on one segment / export-import round trip preserving the exact outcome catalogue
bit-for-bit. Two offline (not committed, matching this codebase's established convention for anything
requiring real PyMC sampling) real-MCMC scripts additionally proved: (a) Model A and Model C both fit
an FH sign-up, an FH GSA (same segment), and a DNA-kit outcome successfully with an explicit
`dna_outcome_id`, with `select_outcome_ids`/`evaluate_scenario`/`optimize_scenario` all correctly
scoped per metric and `fingerprint_model_spec` correctly order-independent yet sensitive to a
GSA-to-sign-up relabel; (b) the Structure page's outcome catalogue editor end-to-end, seeded from the
legacy mappers, saves correctly with the new `fh_dna_cross_sell_outcome_id` selectbox wired through.
**Owner:** Engineering.
**Status:** Accepted; implemented in PR E.1 (correctness hardening on the canonical-outcome refactor,
per the instruction document's explicit pre-media-pathway-schema requirement). See docs/outcomes.md,
docs/dna_fh_causal_structure.md, docs/scenario_planner.md, docs/media_units_and_inflation.md and
docs/limitations.md for the updated design records.

---

**Date:** 2026-07-22
**Decision:** PR E.2 ("semantic hardening" - the instruction document's explicit "remaining semantic
and architecture pitfalls exposed by PR E.1 before media-pathway work begins" directive) - eleven
independent fixes, each closing one confirmed pitfall the instruction document named explicitly. Media
pathways, brand mediation, causal DAGs, dynamic planning and the UI theme are explicitly out of scope
for this PR.
1. **Metric registry replaces product-derived unit defaults.** `OutcomeDefinition.__post_init__` used
   to default every Family History outcome's `unit` to `"GSA"` regardless of metric - wrong for a Family
   History sign-up. `core.outcomes.METRIC_REGISTRY` (`MetricDefinition(metric_key, display_name,
   default_unit, product)` for `fh_gsa`/`fh_signup`/`dna_kit_sale`) now derives the default unit from
   the outcome's `metric_key`, not its `product` - a custom (unrecognised) metric gets no default unit
   at all and must set one explicitly.
2. **Stable `metric_key` replaces exact-string metric matching.** Built-in selectors used to match
   exact display strings (`"GSA"`, `"Sign-up"`, `"Kit sale"`) - a user typing `"Signup"`, `"Signups"`,
   or `"Kit Sale"` created a fitted outcome invisible to every named total and objective.
   `OutcomeDefinition.metric_key` (derived in `__post_init__`, one of `METRIC_KEY_FH_GSA`/
   `_FH_SIGNUP`/`_DNA_KIT_SALE`/`_CUSTOM`) is now what every selector filters on;
   `core.outcomes.normalize_metric_key` migrates a small, explicit table of known display variants to
   their canonical key and falls back to `METRIC_KEY_CUSTOM` for anything not on that table - never a
   fuzzy guess into a business KPI. `select_outcome_ids`, `fh_gsa_outcome_ids`, `fh_signup_outcome_ids`
   and `dna_kit_sale_outcome_ids` all switched from `metric=` display-string filtering to `metric_key=`.
3. **Four independent eligibility flags replace role-only gating.** `role="primary"`-only default
   selection meant a Family History sign-up marked `funnel_intermediate` was fitted but invisible from
   the default `fh_signups` total and its own CPA. `include_in_default_reporting`/
   `include_in_official_total`/`include_in_value`/`include_in_optimisation` (each `Optional[bool]`,
   falling back to `_ROLE_ELIGIBILITY_DEFAULTS[role]` when unset) are now independent axes -
   `core.outcomes.outcome_eligibility(outcome)` resolves all four; `eligible_outcome_ids(meta, flag)` is
   the general selector. Per the instruction document's exact defaults: `funnel_intermediate` outcomes
   are `default_reporting=True, official_total=False` - visible in their own metric's total/CPA, absent
   from the official GSA total. `official_total_outcome_ids(meta, metric_key=...)` is the new,
   stricter-than-default-reporting selector official totals must use.
4. **Raw units are never called "value."** When `ltv` is entirely omitted, `evaluate_scenario` used to
   set `value`/`total_value` to raw predicted units - unsafe once a fit mixes GSAs, sign-ups and kits,
   which cannot be added. This is now reversed: an entirely-omitted `ltv` produces `value=None`,
   `total_value=None`, `total_value_is_complete=False`, `value_status="not configured"`. A *partially*
   priced `ltv` produces `value_status="partial"`, a priced subtotal, and `unpriced_outcome_ids`. Mixed
   `value_currency` across priced outcomes now raises (`_validate_no_mixed_currency_value_weights`)
   instead of silently summing across currencies. `compare_scenarios`' `total_value` sum uses
   `min_count=1` so an all-unpriced column reports `NaN`, not a false `0.0`.
5. **The canonical outcome catalogue is now the Structure page's only workflow**, not a second one
   layered on top of a still-mandatory legacy "one GSA column per FH segment" block. The mandatory FH
   segment mapper was removed entirely; the outcome catalogue editor is seeded from two optional,
   clearly-labelled "Quick-start wizard" expanders (legacy per-segment GSA mapper, DNA kit outcomes) -
   after seeding, every edit happens in the catalogue. `promo_cols`/`segment_control_cols`/`segment_ltv`
   are now *derived* from the live catalogue rather than required separate inputs.
   `ModelSpec.validate()` no longer requires at least one `segment_outcomes` mapping;
   `validate_outcome_definitions` gained the actual enforcement point instead - at least one outcome
   configured and `included_in_fit`.
6. **Promo and control mappings moved to `outcome_id`.** A shared-segment sign-up and GSA used to
   inherit the same segment-level promo/control mapping automatically, even where the business
   definition or timing differs. `ModelSpec` gained `outcome_promo_cols`/`outcome_control_cols`
   (outcome-id-keyed, take precedence over the legacy segment-keyed fields when set) and
   `product_control_cols` (a new product-level tier) - `data.preprocessor.prepare_fh_modeling_frame`
   resolves promo per outcome_id (`outcome_promo_cols` else segment-level `promo_cols`) and controls
   additively across all three tiers, deduplicated. The Structure page's "apply this segment's mapping
   to every outcome in it" button is the explicit bulk action the instruction document required, rather
   than implicit segment-wide inheritance.
7. **Funnel-coherence diagnostics, not a constrained funnel model.** Sign-ups and GSAs are fitted as
   independent Negative-Binomial outcomes with nothing enforcing `GSA <= sign-up` - a genuine,
   documented model limitation, not fixed in this PR. New `core.funnel.FunnelLink(upstream_outcome_id,
   downstream_outcome_id)` lets an analyst declare which pairs form a funnel; `funnel_coherence_
   diagnostics` computes violation counts/rates, implied-conversion-rate range and stability, never
   raising except on a genuine shape mismatch; `funnel_channel_attribution_consistency` flags
   sign-mismatched channel attribution across the pair. Persisted and fingerprinted
   (`core.fingerprint.fingerprint_model_spec`'s `funnel_links` parameter,
   `core.persistence`'s `config/funnel_links.json`). Diagnostics page renders per-link warnings/metrics.
   The current fits remain parallel outcome equations - this PR documents that explicitly rather than
   building the sign-up -> conversion -> GSA transition model the instruction document reserves for a
   later phase.
8. **Explicit CPA denominator and spend-scope metadata.** A scenario-level CPA used to divide whole-plan
   spend by a KPI total with no visible statement of scope - useful as a whole-plan efficiency number,
   but easily mistaken for channel-specific or incremental CPA. `core.media_units.cpa_scope_metadata`
   validates and returns the required metadata (denominator metric, included outcome IDs, spend scope
   from `CPA_SPEND_SCOPES`, included channels, market, time window, incremental-vs-observed).
   `compute_cpa_by_product` gained explicitly-named `channel_incremental_cost_per_fh_gsa`/`_signup`/
   `dna_kit` aliases; `evaluate_scenario` gained `whole_plan_cost_per_fh_gsa`/`_fh_signup`/`_dna_kit`.
   Results & Curve Bank and Scenario Planner now caption their CPA numbers with the exact scope
   ("channel-incremental" vs. "whole-plan") rather than showing a bare `avg_cpa`.
9. **Hardened optimiser target validation.** `_validate_target_outcome_ids` now runs for every
   objective branch: unknown `target_outcome_id`s are rejected; a `target_outcome_id` whose `metric_key`
   doesn't match the objective's metric is rejected (skipped only for legacy metas with no catalogue
   metadata at all); an outcome with `include_in_optimisation=False` (diagnostic role default, or an
   explicit override) is rejected. `weighted_mix` now rejects non-finite/negative weights and raw-unit
   mixes across different `unit`s unless the caller explicitly passes `assume_value_scaled_weights=True`.
   `expected_value`'s default eligible set switched from `role="primary"` to
   `include_in_value ∩ include_in_optimisation`, plus the mixed-currency check from point 3.
10. **Drift status made first-class, not something only Diagnostics showed.** `core.outcomes.
   has_blocking_drift`/`BLOCKING_DRIFT_STATUSES` (`"Changed since fit"`, `"Removed since fit"` - `"New
   since fit"`/`"Excluded from next fit"` deliberately don't block) and a new shared
   `components.ui.render_drift_status` component are now wired into all seven pages the instruction
   document named (Structure, Model Configuration, Model Training, Diagnostics, Results, Scenario
   Planner, Export). Six show it informationally; **Scenario Planner blocks** (`st.stop()`) when
   calculation-relevant drift is present, even with an approved trace still in memory - the instruction
   document's explicit "block scenario planning" requirement.
11. **Promotion events became replayable pipeline steps**, not a one-way mutation of `transformed_data`.
    `PromotionEvent` gained `event_id` (stable identity, auto-generated), `product`, `affected_outcome_ids`,
    `market` and `transformation_version`. `core.promotions.promotion_events_to_transform_steps`/
    `transform_steps_to_promotion_events` convert to/from `data.pipeline.TransformStep(op=
    "promotion_event", ...)` entries in the same `pipeline_steps` list the rest of the transform
    pipeline uses (deliberately excluded from the Transform Pipeline page's manual-operation dropdown -
    only ever produced from a structured `PromotionEvent`); `apply_step` replays one event's
    contribution additively onto its segment's derived column, matching `promotion_weekly_series`'s
    existing overlapping-events-compound semantics. The Structure page's Save handler now persists
    events as `TransformStep`s (replacing any prior promotion_event steps, leaving every other step type
    untouched) alongside materialising the derived column for the current session; Project Export's
    import handler drops whatever derived promo column is sitting in the imported parquet and replays
    the `promotion_event` steps fresh against the imported data, so re-importing a project reproduces
    the derived columns from the versioned event list rather than trusting the parquet.
**Reason:** PR E.1 made two independent KPIs on one segment fittable and mostly safe to plan against,
but the instruction document's own follow-up review found eleven further places where a display label,
an implicit role default, or a one-way mutation could still silently misattribute, mislabel, or lose
reproducibility for exactly the multi-KPI, multi-product projects PR E/E.1 were built to support. Each
point above closes one specific, named pitfall rather than a general refactor.
**Alternatives considered:** Keeping `role` as the single axis controlling every downstream behaviour
and adding narrower special cases per collision (rejected - identical reasoning to PR E.1's selector
consolidation: defers the fix to whichever call site hits the first real funnel-intermediate project).
Building the full sign-up -> conversion -> GSA constrained funnel model now instead of diagnostics-only
(rejected - the instruction document explicitly reserves this for a later phase, after parallel-outcome
diagnostics and identifiability work); this PR ships the diagnostics prerequisite only. Replaying every
`TransformStep` (not just `promotion_event`) against `raw_sources` on project import (rejected as
out of scope - `pipeline_steps` replay-on-import is a pre-existing gap for every step type, not
specific to promotion events; fixing it project-wide is materially riskier and not what the instruction
document asked for here).
**Impact:** Every fitted model, persisted project bundle, and approval fingerprint from before this PR
is invalidated by the fingerprinted eligibility flags, `metric_key` and `funnel_links` payload additions
- existing bundles must be re-fit and re-approved. A `weighted_mix` objective call that previously mixed
raw units across different `unit`s now raises unless `assume_value_scaled_weights=True` is passed
explicitly. `evaluate_scenario`'s `value`/`total_value` are `None` (not raw units) whenever `ltv` is
entirely omitted - any caller reading them must check `value_status`. The Scenario Planner now hard-stops
on calculation-relevant catalogue drift where it previously allowed planning against a stale approval.
**Verification:** 773 tests passing (754 -> 773 across this PR's eleven items), `ruff check` clean
throughout. All 20 of the instruction document's required test cases are covered: blank FH sign-up unit
never becomes GSA; metric display variants migrate to canonical keys; custom metrics require explicit
units; funnel-intermediate sign-ups appear in sign-up reporting but not the official GSA total;
no-value-configured produces `value=None`; mixed currencies rejected; sign-up-only projects need no
legacy GSA mapping; promo/control mappings differ across sign-up and GSA sharing a segment;
funnel-coherence warnings; objective target-metric mismatch rejected; diagnostic outcomes cannot be
optimised; raw-unit weighted mixes blocked unless explicitly value-scaled; CPA carries denominator and
spend-scope metadata; catalogue drift blocks Scenario Planner; promotion-event pipeline replay
reproduces derived columns from raw data on import; Model A/Model C parity (both builders construct the
new `outcome_id_to_metric_key`/`outcome_id_to_eligibility` fields identically - verified by source
inspection rather than a full PyMC build, matching this codebase's established convention of not
compiling a real model in the test suite); bundle migration and round trip (legacy bundles with no
`funnel_links.json`/outcome-id-keyed promo-control config import safely, and a full export/import
round trip reproduces funnel links, outcome-id-keyed mappings, and promotion-event pipeline steps
bit-for-bit); Streamlit AppTests for the canonical Structure workflow (quick-start wizard seeding, the
outcome-level promo/control override section and its bulk-apply button, both via real
`AppTest.from_file` runs); visible green CI (full suite + ruff clean on this PR's head).
`AppTest.from_function`'s isolated single-script pattern was found to have a reproducible
pandas4/pyarrow-in-a-thread crash specific to a fresh process's first list-of-dicts DataFrame
construction (`test_drift_status_component.py`'s docstring has the full root-cause writeup) - worked
around by testing that specific code path via direct calls with monkeypatched `st.*` methods instead of
`AppTest`, while proving the same code live on a real page via `AppTest.from_file`
(`test_model_config_drift_apptest.py`), which does not reproduce the issue.
**Owner:** Engineering.
**Status:** Accepted; implemented in PR E.2 (semantic hardening on the canonical-outcome refactor, per
the instruction document's explicit pre-media-pathway-schema requirement). See docs/outcomes.md,
docs/scenario_planner.md, docs/media_units_and_inflation.md and docs/limitations.md for the updated
design records.

---

**Date:** 2026-07-22
**Decision:** PR F ("pathway catalogue" - the updated roadmap's explicit "implement PR F as the
explicit MediaOutcomePathway schema, but design it to support the expanded future outcome catalogue"
directive) - a new business definitions document introduced two future outcome-modelling directions
(Family History net bill-through attributed to sign-up date, and DNA purchase-type segmentation by
purchasing-vs-activating-account relationship) and asked for the pathway schema to be designed against
them now, without building the transformations, classifiers, or new model equations those directions
will eventually need.
1. **`core.pathways.MediaOutcomePathway`** - a new, separate catalogue of explicit
   `(channel, target_outcome_id)` relationships, with `role` (`primary_direct`/`active_cross_product`/
   `exploratory_cross_product`/`excluded`), `lag_type`/`lag_weeks`, `prior_scale`,
   `include_in_attribution`/`include_in_planning` (independent eligibility flags, matching
   `core.outcomes.outcome_eligibility`'s established four-flag pattern rather than overloading `role`),
   and `evidence_status`. **Schema, validation, persistence, fingerprinting, fit-time metadata and
   drift detection only** - no model equation reads it; `ModelSpec.dna_channels`/
   `FHModelMeta.direct_dna_outcome_ids` remain the only structural pathway input the PyMC builders
   actually use. `validate_media_outcome_pathways` checks channel/product/role/outcome_id validity and
   rejects a duplicate `(channel, target_outcome_id)` pair. Designed explicitly against the expanded
   future outcome catalogue: `target_outcome_id` is validated against whatever outcome_ids a project's
   *current* catalogue has, so a pathway can target `fh_net_billthrough_count` or
   `dna_kit_sale_self_activated` the moment a matching `OutcomeDefinition` exists - nothing hard-codes
   "every FH KPI is GSA" or "every DNA KPI is a generic kit-sale total."
2. **Fingerprinted like `FunnelLink`.** `pathway_catalogue_fingerprint_payload` is calculation-adjacent
   (not yet calculation-relevant) configuration, sorted/keyed by `(channel, target_outcome_id)` -
   deliberately excluding the auto-generated `pathway_id` from the payload, so two logically-identical
   catalogues built independently (different random ids) fingerprint identically.
   `core.fingerprint.fingerprint_model_spec` gained a `media_outcome_pathways` parameter; every
   pre-existing approval is invalidated by this addition, the established pattern. While making this
   change, a pre-existing gap was also closed: the three page-level fingerprint call sites
   (Diagnostics, Results & Curve Bank, Scenario Planner) never actually passed `funnel_links` to
   `fingerprint_model_spec` despite PR E.2 adding that parameter - an edited funnel link never
   invalidated a displayed "approval matches" check. Both `funnel_links` and the new
   `media_outcome_pathways` are now passed at all three call sites and in
   `core.persistence.verify_imported_approval`.
3. **Persisted as `config/media_outcome_pathways.json`**, same "absent means legacy, not corrupt"
   convention as every prior addition - `import_project` reports `None` for a bundle predating this PR.
   `FHModelMeta.pathway_catalogue_at_fit` (populated identically by both `build_fh_hierarchical_model`
   and `build_fh_market_specific_model`, verified by source-inspection parity test per this codebase's
   established no-real-PyMC-build-in-tests convention) captures the exact catalogue in effect at fit
   time via a pure pass-through added to `data.preprocessor.prepare_fh_modeling_frame`'s new
   `media_outcome_pathways` parameter - it does not affect any array that function builds.
4. **Drift detection, informational only everywhere it's shown.** `pathway_drift_status`/
   `pathways_drift_dataframe` mirror `outcome_drift_status`/`outcomes_drift_dataframe`, keyed by
   `pathway_id`. Unlike outcome-catalogue drift (which the Scenario Planner treats as blocking), pathway
   drift is shown informationally on Structure, Diagnostics and Project Export only - the pathway
   catalogue doesn't yet drive fitting, so there is nothing for a stale pathway to make wrong.
5. **Planned metric keys for the expanded future outcome catalogue.** `core.outcomes.METRIC_REGISTRY`
   gained seven entries: `fh_net_billthrough_count`/`fh_net_billthrough_rate`/`fh_gsa_finance_date`
   (Family History) and `dna_kit_sale_self_activated`/`_gifted_activated`/`_unactivated`/`_total` (DNA -
   `dna_kit_sale_total` kept distinct from the pre-existing `dna_kit_sale`, for backward compatibility).
   `MetricDefinition` gained `aggregation_type` (`"count"`/`"rate"`/`"currency"`/`"index"`),
   `allowed_in_optimiser`, `allowed_in_cpa` - `fh_net_billthrough_rate` is the only built-in metric with
   `aggregation_type="rate"` and the only one disallowed from the optimiser/CPA. No computation
   pipeline exists for any of these seven metrics yet - registering them only lets a
   `MediaOutcomePathway` or a manually-mapped `OutcomeDefinition` reference them ahead of that work.
6. **`OutcomeDefinition.aggregation_type`/`date_basis`/`maturity_required`** - schema/validation-only
   outcome-type metadata the roadmap calls "what allows the app to prevent unsafe aggregation."
   `aggregation_type` derives from the metric registry the same way `unit` already does.
   `validate_outcome_definitions` now rejects a `"rate"`-aggregation outcome that resolves eligible for
   the official total or optimisation, forcing an explicit non-`"primary"` role (or override) for any
   rate outcome - the roadmap's "do not use net bill-throughs and net bill-through rate as synonyms" /
   "do not allow rate outcomes into count totals or count-based CPA." `date_basis` (one of
   `event_date`/`signup_date_attributed`/`billing_date`/`purchase_date`/`activation_date`) and
   `maturity_required` are validated if set but read by no transformation - deliberately excluded from
   the outcome-catalogue fingerprint and drift-tracked fields, the same "descriptive, not
   calculation-relevant" reasoning `MarketDescriptors` is excluded from the fingerprint for.
7. **`core.pathways.OutcomeReconciliationGroup`/`reconciliation_group_diagnostics`** - diagnostics-only
   (e.g. "DNA total = self-activated + gifted-activated + unactivated"), never raises, reports `None`
   rather than a guessed value for anything it can't evaluate. Explicitly not fingerprinted (nothing
   downstream reads a reconciliation group to compute anything) and not wired into constrained
   estimation, per the roadmap's own "initially use this for validation and diagnostics, not
   necessarily constrained estimation."
8. **Structure page UI** - a new "Media-outcome pathway catalogue (optional, forward-looking)" section
   (`st.data_editor`, below Funnel links), validated against the page's own channel list and live
   outcome catalogue, persisted through the same Save handler.
**Reason:** The new business-definitions document found that the DNA New/Existing-customer
segmentation and finance-date GSA reporting under-serve two real decisions: which purchases are
self-driven vs. gifted (materially different economics and, eventually, different media response), and
which marketing-attributed acquisitions should count toward a KPI regardless of how long billing takes
to catch up. Rather than building those transformations immediately (which the roadmap explicitly
defers, pending activation-maturity/censoring design work and real-data volume review), PR F builds the
one piece that's genuinely prerequisite and low-risk now: a pathway catalogue and outcome-schema
vocabulary that won't need to be redesigned once the transformations exist.
**Alternatives considered:** Waiting to build `MediaOutcomePathway` until PR G (pathway-specific
estimation) actually needs it (rejected - the roadmap explicitly asks for the schema now, "before that
PR exists," so a later PR can be reviewed purely on estimation logic rather than schema design too).
Making `dna_kit_sale_total` an alias for the existing `dna_kit_sale` key instead of a distinct one
(rejected - the roadmap's recommended canonical DNA metric keys list it as a separate, explicit key
alongside the three atomic categories; aliasing would blur the "roll-up vs. this project's actual
generic-kit-sale total" distinction for existing projects). Fingerprinting `aggregation_type`/
`date_basis`/`maturity_required`/reconciliation groups now, defensively, in case a future PR reads them
(rejected - same reasoning as `MarketDescriptors`: fingerprinting purely descriptive fields that
nothing computes from yet would invalidate approvals for no correctness benefit; the moment a real
transformation reads one of them, that is the correct point to add it to the fingerprint, as an
intentional breaking change like every other addition in this log).
**Impact:** Every fitted model, persisted project bundle, and approval fingerprint from before this PR
is invalidated by the new `media_outcome_pathways` fingerprint payload (and by the `funnel_links` gap
fix at the three page-level call sites) - existing bundles must be re-fit and re-approved. No existing
outcome, curve, attribution, scenario, or CPA calculation changes behaviour - this PR is purely additive
schema/UI/persistence.
**Verification:** 856 tests passing (774 -> 856 across this PR), `ruff check` clean throughout. Covers:
`MediaOutcomePathway` round trip/validation/fingerprint/drift (including the required "pathway schema
can target the expanded future outcome catalogue without hard-coding fh_gsa/generic-kit-sale" case);
`OutcomeReconciliationGroup` validation/diagnostics (sum and ratio relations, missing-value handling);
the seven planned metric keys' registry entries and `aggregation_type`/`allowed_in_optimiser`/
`allowed_in_cpa` flags; `OutcomeDefinition`'s new fields and the rate-aggregation validation rule;
Model A/Model C parity for `pathway_catalogue_at_fit` construction (source-inspection, matching this
codebase's established no-real-PyMC-build convention); bundle export/import round trip and
legacy-bundle-imports-with-None for `media_outcome_pathways`; Streamlit AppTests for the Structure
page's pathway catalogue section (save + validation-error paths) and the Diagnostics page's pathway
drift info message.
**Owner:** Engineering.
**Status:** Accepted; implemented in PR F (explicit media-outcome pathway schema, designed against the
net-bill-through/DNA-purchase-type roadmap, per that document's exact instruction). Media pathways'
*estimation* (PR G), the net-bill-through transformation, the DNA activation classifier, the
constrained funnel model, the DNA composition model, the causal DAG, Brand Search mediation, the
dynamic planner and the UI theme remain explicitly out of scope, per the same instruction. See
docs/media_outcome_pathways.md, docs/outcomes.md, docs/dna_fh_causal_structure.md and
docs/limitations.md for the updated design records.

---

**Decision:** PR G1 ("statistically correct segment-level MMM" - the reprioritised roadmap's explicit
instruction to make `MediaOutcomePathway` control which coefficients are estimated in Model A and Model
C; build the deterministic Family History net bill-through count; add Brand Search treatment modes; and
add model-comparison, multicollinearity and identification diagnostics) - implemented as follows:

1. **`core.pathways.resolve_pathway_masks`/`ResolvedPathwayMasks`** - the pathway catalogue (PR F,
   schema-only) is now operational: both PyMC builders read the same resolved masks to decide which
   `(outcome, channel)` cells are `primary_direct`/`active_cross_product`/`exploratory_cross_product`/
   `excluded`, replacing the old DNA-only direct/halo split with a general mechanism that works for any
   channel. Proven exactly backward-compatible with the pre-PR-G1 legacy defaults when no pathway
   catalogue is configured.
2. **`hierarchical_model.py`/`market_specific_model.py`** - `eta_channels` built via masked matmuls
   against `resolve_pathway_masks`'s output (same call, same construction pattern in both builders,
   source-inspected for parity) - `excluded` cells contribute deterministically zero, not merely a
   tight prior; `exploratory_cross_product` cells get a tighter default HalfNormal sigma (0.08 vs
   `active_cross_product`'s 0.25).
3. **`FHModelMeta.pathway_masks`** defaults to `None` (a "not supplied" sentinel, not a literal empty
   value) and auto-resolves the legacy default in `__post_init__` when omitted, so a hand-built meta or
   a pre-PR-G1 bundle never silently replays against an all-excluded mask set.
4. **`predict.py`/`market_specific_predict.py`/`attribution.py`/`market_specific_attribution.py`** -
   `FHPosteriorParams.halo_strength` (per-outcome) generalised to `pathway_strength` (per
   `[outcome_id][channel]`); every NumPy replay/attribution function rewritten to mirror the PyMC
   construction exactly via the same resolved masks, closing a pre-existing risk where the direct/halo
   pattern was independently duplicated (and could silently diverge) across six files.
5. **`core.net_billthrough`** - `NetBillthroughOfferRule` (analyst-configured maturity windows, no
   safe default), `compute_net_billthrough_cohorts`/`net_billthrough_weekly_series` (deterministic,
   signup-date-attributed, immature cohorts excluded not zero-filled), `immature_cohort_summary`.
   `fh_gsa_finance_date` remains structurally untouched (the module has no import of `core.outcomes`).
6. **`core.brand_search`** - four explicit treatment modes (`direct_channel`/`excluded`/
   `demand_capture_mediator`/`experiment_calibrated_incremental`), mapping onto `core.pathways`'
   `primary_direct`/`excluded` roles for fitting; `mediator_reallocation` deterministically splits a
   Brand Search channel's fitted contribution across analyst-declared `mediator_of` upstream channels,
   reconciling exactly to the original total.
7. **`core.identification_diagnostics`** - channel-spend correlation matrix, media design-matrix
   condition number, posterior coefficient-of-variation stability (works for both Model A's and Model
   C's `beta` shape), and a caller-supplied-refit `leave_one_channel_out_sensitivity` helper (matching
   `core.diagnostics.expanding_window_backtest`'s injection pattern - no new PyMC fit runs inside this
   module); `identification_report` bundles all signals into one severity-ranked flag list.
8. **UI** - Model Configuration gained `active_cross_product_sigma`/`exploratory_cross_product_sigma`
   prior sliders (replacing the now-dead `dna_halo_sigma` control) and a Brand Search treatment-mode
   editor; Structure gained a net bill-through offer-rule editor and updated pathway-catalogue
   messaging (no longer "does not yet drive fitting" - it does, as of this PR); Diagnostics gained a
   multicollinearity & weak-identification panel alongside the existing scorecard.

**Reason:** The pathway catalogue built in PR F was explicitly schema-only ("nothing here changes what
gets fitted") - a genuine statistical improvement to segment-level attribution required actually
consuming it. Brand Search's last-click ambiguity and the net bill-through metric's signup-vs-event-date
attribution ambiguity were both flagged as real, unresolved measurement gaps the roadmap named
specifically; both needed deterministic, analyst-controlled treatments rather than either an unexamined
default or a full causal model this PR explicitly does not build.
**Alternatives considered:** Building a real causal DAG or a fitted mediation model for Brand Search
(rejected - explicitly out of scope per the roadmap, "do not yet build ... causal DAG"; a full DAG needs
its own dedicated design and is a large enough scope change to warrant its own PR). Zero-filling immature
net bill-through cohorts so every week has a value (rejected - a fabricated number is worse than an
honest gap; excluding immature cohorts, with `immature_cohort_summary` making the exclusion visible, was
judged the only defensible default). Per-pathway custom `lag_weeks` values instead of one shared
`cross_product_lag_weeks` (rejected for this PR - the pathway schema already stores `lag_weeks` per
pathway for a future PR to read; this limitation was later removed by G1.1.2/G1.1.3, which made
per-component lags operational across fitting and replay). Refitting
inside `leave_one_channel_out_sensitivity` itself rather than taking a caller-supplied refit function
(rejected - matches `expanding_window_backtest`'s established injection pattern; a real refit is slow and
belongs page-level/user-paced, not embedded in a diagnostics module).
**Impact:** Every fitted model, persisted project bundle, and approval fingerprint from before this PR
is invalidated the moment a pathway catalogue with any non-default role is configured - a project with
no pathway catalogue at all is bit-for-bit behaviourally unchanged (the legacy-default equivalence
proof). `CurveBankEntry.halo_strength` (the on-disk curve bank schema) keeps its field name for backward
compatibility even though it now stores the generalised `pathway_strength` value - a documented,
deliberate exception to this codebase's usual free-renaming convention, since this field is a persisted
on-disk format, not just an internal identifier.
**Verification:** 960 tests passing (873 -> 960 across this PR), `ruff check` clean throughout. Covers:
`resolve_pathway_masks` legacy-default equivalence and explicit-override semantics; Model A/Model C
parity (source-inspection, both for metadata construction and for the pathway-masking construction
itself); every existing `halo_strength`-based test migrated to `pathway_strength` and still passing
(proving the legacy invariants hold under the new mechanism); new excluded-pathway zero-contribution,
active/exploratory replay-parity, and `None`-sentinel auto-resolution tests; net bill-through offer-rule
validation, signup-date mapping, immature-cohort exclusion, and finance-date-GSA structural separation;
Brand Search mode-to-pathway-role mapping, config validation, and mediator-reallocation reconciliation;
multicollinearity/condition-number/coefficient-stability diagnostics (including a Model-C-shaped
`beta` regression case); correlated-media Shapley credit-displacement recovery and mediator-allocation
recovery against known ground truth; Streamlit AppTests for all three new UI editors (one of which
caught and fixed a real bug - a list-typed `mediator_of` field cannot bind to a `TextColumn`). Both PyMC
model builders re-verified offline (not committed, matching this codebase's established convention) to
build cleanly and evaluate to a finite log-probability with excluded and exploratory pathways configured.
**Owner:** Engineering.
**Status:** Accepted; implemented in PR G1 (pathway-masked coefficient estimation, net bill-through
transformation, Brand Search treatment modes, and multicollinearity/identification diagnostics, per the
reprioritised roadmap's exact instruction). The full scenario planner, sequential optimisation, an
automated geo-test pipeline, a brand-equity module, the DNA composition model, and the UI theme remain
explicitly out of scope, per the same instruction - the roadmap's next PR is designed to consume this
PR's `pathway_masks`/`pathway_strength`/`net_billthrough_weekly_series`/`identification_report` outputs
directly for channel x segment saturation curves, average/marginal ROI and CPA, and a pathway-aware
scenario planner. See docs/segment_level_estimation.md, docs/brand_search.md, docs/net_billthrough.md
and docs/limitations.md for the updated design records.

## G1.1.3 — authoritative resolved-component contract and resumability

**Decision:** `ResolvedPathwayComponent` is the single calculation and
governance authority. Named pathway masks and index-keyed lag/prior/planning
dictionaries remain only as regenerated, consistency-checked bundle
compatibility caches.

Direct pathway `prior_scale` is disabled because direct effects use the
hierarchical beta prior. For cross-product components it is the optional
HalfNormal pathway-strength sigma override; a blank value uses the active or
exploratory role default. Mediated and excluded records remain outside the
standard likelihood and cannot enter planning or headline output.

Evidence status no longer grants headline reporting implicitly. Headline
eligibility requires an explicit approval decision, reviewer, and approval
timestamp/reference. Pre-G1.1.3 catalogue and resolved-component payloads are
migrated once to an auditable `legacy_migration` approval when their old
evidence-derived headline flag was true.

Pathway validation now receives channel ownership, outcome ownership, fitted
outcomes, and diagnostic-only outcomes before frame construction and again
before either PyMC model is created. NBT validation remains before long-to-wide
aggregation and is repeated against the model frame.

Project bundles now include a schema/app manifest, workflow checkpoint,
diagnostics, analyst notes, calibration/comparison state, and restoration of
curve-bank files. `audit_project_resumability` checks the artefacts required at
uploaded, pre-fit, fitted, approved, curve, and scenario checkpoints; legacy
bundles remain importable with an explicit migration warning.

**Verification:** actual PyMC deterministics for Models A and C are reconciled
for simultaneous direct/delayed components, multiple active and exploratory
cells, and mixed lags; the same prior draws reconcile to NumPy prediction.
Attribution, headline attribution, and planning-only response tests prove that
only their independently eligible components are summed. Wide and long NBT
preparation is equivalent, and duplicate long rows are blocked before
aggregation. Full suite, every Streamlit AppTest, Ruff, compileall, and bundle
round trips pass.

**Scope:** G2 curves/economics, response horizons, year-on-year reporting,
dynamic planning, production mediation, brand health, and DNA composition
remain separate follow-on work.

## G1.1.4 -- final integration verification and release hardening

**Decision:** Resolved components remain the sole pathway authority.
Compatibility masks and cell caches are immutable, component-derived views;
they cannot be independently reassigned or mutated. Import continues to
reject any supplied cache that disagrees with its component collection.

The Structure editor now keeps component-specific columns read-only in the
grid and provides dynamically enabled row controls. Cross-product
`prior_scale` is explicitly the HalfNormal sigma for the component's
`pathway_strength`; it is disabled and cleared for all other component
types. Planning and headline fields are disabled and cleared for mediated
and excluded rows, with mediation labelled diagnostic-only.

Resumability auditing covers pre-fit, fitted, approved, curve, and scenario
checkpoints. Curve and scenario checkpoints require a matching model
approval, and restored stale state is rejected before scenario evaluation.
End-to-end bundle tests reconstruct model data and posterior state and verify
fingerprints at each post-fit checkpoint.

**Verification:** Component/cache immutability, corrupted-cache rejection,
legacy migration, Model A/Model C PyMC-to-NumPy algebra, attribution/headline/
planning/scenario reconciliation, NBT validation ordering and defensive
model-builder guards, dynamic UI state, and checkpoint restoration are
covered by executable tests. G2 curve dashboards, dynamic planning, and
long-horizon efficiency reporting remain out of scope.

## G1.1.5 -- final calculation and migration release gate

**Decision:** Pathway lag and prior semantics are keyed only by
`(outcome_id, channel, component_type)`. Model A, Model C, NumPy replay, and
both attribution paths use the ID-keyed API. Index-based methods are retained
only as compatibility wrappers that require the exact model outcome and
channel coordinates, eliminating the former first-seen component-order
dependency.

Mask-only pathway metadata is now an explicit legacy-governance migration,
not an all-visible compatibility mode. Deterministic direct and
cross-product components are reconstructed where the masks contain enough
information; analyst attribution remains available, while official headline
and planning output raises a governance error until the catalogue is
reviewed and re-resolved. Migration limitations and required actions are
persisted in a migration report and surfaced by resumability auditing.

Both PyMC models now expose `eta_primary` and `eta_channels` deterministics in
addition to active and exploratory cross-product terms. The complex mixed-lag
graph test reconciles each term manually, their total, full NumPy replay, and
the model's `mu`. Standard shared and market-specific curve tests use real
model metadata and posterior-parameter objects to verify NBT response plus
average and marginal NBT CPA.

Bundle restoration tests cover pre-fit, fitted, approved, curve, and scenario
checkpoints through the public export/import APIs, including data,
configuration, governance metadata, NBT metadata, posterior fingerprints,
curve files, scenario predictions, workflow stage, repeated legacy
migration, and stale-approval planning rejection.

**Scope:** This is the final G1 release gate. The G2 curve table/dashboard,
posterior curve uncertainty, response horizons, year-on-year reporting,
dynamic planner, production mediation, brand health, and DNA composition
remain separate work.

## G1.1.6 -- integration verification and legacy-review completion

**Decision:** Legacy-governance projects now have a supported upgrade
workflow on the Structure page. The migration report and reconstructed
components are visible, the rows can be loaded into the governed catalogue,
and analysts can correct ownership, role, lag, prior, evidence, attribution,
headline approval, and planning eligibility. Every reconstructed
outcome/channel pair must remain auditable, and completing the review
requires explicit certification.

Saving a completed review persists the replacement catalogue and clears the
old frame, model, posterior, approval, and run identity. The reviewed
catalogue is non-legacy configuration, but official use remains impossible
until Model Configuration and Model Training produce a new fit. Rejected
relationships are recorded as excluded rows instead of being silently
deleted.

**Verification:** Order-independence tests now compare prediction, analyst
attribution, headline attribution, planning response, fit cells, and bundle
restoration for reordered and governance-filtered component collections.
Model C downstream governance views reconcile with the equivalent Model A
fixture. Public bundle tests cover uploaded, transformed, configured,
pre-fit, fitted, approved, curve, and scenario checkpoints. The NBT
source-to-builder test constructs both model types from equivalent wide and
long inputs, and standard shared/market-specific curves reconcile two
segment-level NBT responses to total NBT response and average/marginal NBT
CPA.

**Scope:** No G2 curve dashboard, response-horizon reporting, year-on-year
analysis, dynamic planner, production mediation, brand-health model, or DNA
composition model is included.
