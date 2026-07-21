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
